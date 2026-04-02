# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
deploy.py
=========
Deployment manager for HOPEFX AI Trading.

Supports Docker Compose and Kubernetes deployment targets.
Performs health checks after deploy and rolls back automatically on failure.

Usage:
    python deploy.py <environment>            # deploy to environment
    python deploy.py <environment> --dry-run  # show commands without executing

Environments: development, staging, production
"""

from __future__ import annotations

import argparse
import logging
import subprocess  # nosec B404 - list-form calls with fixed tool names; no shell=True, no user input
import sys
import time

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

VALID_ENVIRONMENTS = ["development", "staging", "production"]

COMPOSE_FILES = {
    "development": "docker-compose.yml",
    "staging": "docker-compose.yml",
    "production": "docker-compose.yml",
}

K8S_NAMESPACES = {
    "development": "hopefx-dev",
    "staging": "hopefx-staging",
    "production": "hopefx-prod",
}

K8S_DEPLOYMENT = "hopefx-trading"

HEALTH_ENDPOINTS = {
    "development": "http://localhost:8000/health",
    "staging": "http://staging.hopefx.ai/health",
    "production": "http://app.hopefx.ai/health",
}

HEALTH_CHECK_RETRIES = 10
HEALTH_CHECK_INTERVAL_S = 6


def _run(cmd: list[str], dry_run: bool = False, check: bool = True) -> subprocess.CompletedProcess:
    logger.info("$ %s", " ".join(cmd))
    if dry_run:
        logger.info("  [dry-run] skipped")
        return subprocess.CompletedProcess(cmd, returncode=0, stdout=b"", stderr=b"")
    return subprocess.run(  # nosec B603 B607 - list-form calls with fixed tool names; no shell=True, no user input
        cmd, check=check, capture_output=False
    )


class DeploymentManager:
    def __init__(self, environments: list[str], dry_run: bool = False) -> None:
        self.environments = environments
        self.dry_run = dry_run
        self._previous_image: str | None = None

    def deploy(self, environment: str) -> bool:
        """
        Deploy to the given environment.

        Steps:
          1. Validate environment
          2. Record current image tag for rollback
          3. Pull latest images
          4. Apply deployment (Docker Compose or Kubernetes)
          5. Health check — rollback automatically on failure

        Returns True on success, False on failure.
        """
        if environment not in self.environments:
            logger.error("Unknown environment: %s. Valid: %s", environment, self.environments)
            return False

        logger.info("=== Deploying to %s ===", environment)
        self._record_current_state(environment)

        try:
            self._pull_images(environment)
            self._apply_deployment(environment)

            if self.check_health(environment):
                logger.info("=== Deployment to %s succeeded ===", environment)
                return True

            logger.error("Health check failed after deploy — initiating rollback")
            self.rollback(environment)
            return False

        except subprocess.CalledProcessError as exc:
            logger.error("Deployment command failed: %s — initiating rollback", exc)
            self.rollback(environment)
            return False

    def check_health(self, environment: str) -> bool:
        """Poll the health endpoint until 200 or retries exhausted."""
        import urllib.request
        import urllib.error

        url = HEALTH_ENDPOINTS.get(environment, "")
        if not url:
            logger.warning("No health endpoint for %s — skipping", environment)
            return True

        logger.info(
            "Health check: %s (up to %ds)",
            url,
            HEALTH_CHECK_RETRIES * HEALTH_CHECK_INTERVAL_S,
        )
        for attempt in range(1, HEALTH_CHECK_RETRIES + 1):
            try:
                with urllib.request.urlopen(url, timeout=5) as resp:  # nosec B310 - health check URL is always http/https
                    if resp.status == 200:
                        logger.info("Health check passed (attempt %d)", attempt)
                        return True
                    logger.warning("Attempt %d: HTTP %d", attempt, resp.status)
            except (urllib.error.URLError, OSError) as exc:
                logger.warning("Attempt %d failed: %s", attempt, exc)
            if attempt < HEALTH_CHECK_RETRIES:
                time.sleep(HEALTH_CHECK_INTERVAL_S)

        logger.error("Health check failed after %d attempts", HEALTH_CHECK_RETRIES)
        return False

    def rollback(self, environment: str) -> bool:
        """
        Roll back to the previous deployment state.

        Kubernetes: kubectl rollout undo
        Docker Compose: bring down, restore previous image tag, bring up
        """
        logger.warning("=== Rolling back %s ===", environment)
        try:
            if self._is_kubernetes_available():
                return self._rollback_kubernetes(environment)
            return self._rollback_compose(environment)
        except Exception as exc:
            logger.error("Rollback failed: %s", exc)
            return False

    # ── Private helpers ───────────────────────────────────────────────────────

    def _record_current_state(self, environment: str) -> None:
        try:
            result = subprocess.run(  # nosec B603 B607 - list-form calls with fixed tool names; no shell=True, no user input
                [
                    "docker",
                    "inspect",
                    "--format",
                    "{{.Id}}",
                    f"hopefx-trading:{environment}",
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            if result.returncode == 0:
                self._previous_image = result.stdout.strip()
                logger.info(
                    "Recorded current image: %s",
                    (self._previous_image or "")[:20] or "none",
                )
        except FileNotFoundError:
            logger.debug("docker not found — skipping image recording")

    def _pull_images(self, environment: str) -> None:
        compose_file = COMPOSE_FILES.get(environment, "docker-compose.yml")
        if self._is_compose_available():
            _run(["docker", "compose", "-f", compose_file, "pull"], dry_run=self.dry_run)

    def _apply_deployment(self, environment: str) -> None:
        if self._is_kubernetes_available():
            self._deploy_kubernetes(environment)
        else:
            self._deploy_compose(environment)

    def _deploy_compose(self, environment: str) -> None:
        compose_file = COMPOSE_FILES.get(environment, "docker-compose.yml")
        logger.info("Deploying via Docker Compose: %s", compose_file)
        _run(
            ["docker", "compose", "-f", compose_file, "up", "-d", "--remove-orphans"],
            dry_run=self.dry_run,
        )

    def _deploy_kubernetes(self, environment: str) -> None:
        namespace = K8S_NAMESPACES.get(environment, "hopefx-prod")
        logger.info("Deploying via Kubernetes: namespace=%s", namespace)
        _run(
            [
                "kubectl",
                "rollout",
                "restart",
                f"deployment/{K8S_DEPLOYMENT}",
                "-n",
                namespace,
            ],
            dry_run=self.dry_run,
        )
        _run(
            [
                "kubectl",
                "rollout",
                "status",
                f"deployment/{K8S_DEPLOYMENT}",
                "-n",
                namespace,
                "--timeout=300s",
            ],
            dry_run=self.dry_run,
        )

    def _rollback_kubernetes(self, environment: str) -> bool:
        namespace = K8S_NAMESPACES.get(environment, "hopefx-prod")
        logger.warning("Kubernetes rollback: namespace=%s", namespace)
        try:
            _run(
                [
                    "kubectl",
                    "rollout",
                    "undo",
                    f"deployment/{K8S_DEPLOYMENT}",
                    "-n",
                    namespace,
                ],
                dry_run=self.dry_run,
            )
            _run(
                [
                    "kubectl",
                    "rollout",
                    "status",
                    f"deployment/{K8S_DEPLOYMENT}",
                    "-n",
                    namespace,
                    "--timeout=120s",
                ],
                dry_run=self.dry_run,
            )
            logger.info("Kubernetes rollback completed")
            return True
        except subprocess.CalledProcessError as exc:
            logger.error("Kubernetes rollback failed: %s", exc)
            return False

    def _rollback_compose(self, environment: str) -> bool:
        compose_file = COMPOSE_FILES.get(environment, "docker-compose.yml")
        logger.warning("Docker Compose rollback: %s", compose_file)
        try:
            _run(["docker", "compose", "-f", compose_file, "down"], dry_run=self.dry_run)
            if self._previous_image:
                logger.info("Restoring previous image: %s", self._previous_image[:20])
                _run(
                    [
                        "docker",
                        "tag",
                        self._previous_image,
                        f"hopefx-trading:{environment}",
                    ],
                    dry_run=self.dry_run,
                    check=False,
                )
            _run(
                ["docker", "compose", "-f", compose_file, "up", "-d"],
                dry_run=self.dry_run,
            )
            logger.info("Docker Compose rollback completed")
            return True
        except subprocess.CalledProcessError as exc:
            logger.error("Docker Compose rollback failed: %s", exc)
            return False

    @staticmethod
    def _is_kubernetes_available() -> bool:
        try:
            r = subprocess.run(  # nosec B603 B607 - list-form calls with fixed tool names; no shell=True, no user input
                ["kubectl", "cluster-info"],
                capture_output=True,
                check=False,
                timeout=5,
            )
            return r.returncode == 0
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return False

    @staticmethod
    def _is_compose_available() -> bool:
        try:
            r = subprocess.run(  # nosec B603 B607 - list-form calls with fixed tool names; no shell=True, no user input
                ["docker", "compose", "version"],
                capture_output=True,
                check=False,
                timeout=5,
            )
            return r.returncode == 0
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return False


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="HOPEFX deployment manager")
    parser.add_argument("environment", choices=VALID_ENVIRONMENTS, help="Target environment")
    parser.add_argument("--dry-run", action="store_true", help="Print commands without executing")
    args = parser.parse_args()

    manager = DeploymentManager(environments=VALID_ENVIRONMENTS, dry_run=args.dry_run)
    success = manager.deploy(args.environment)
    sys.exit(0 if success else 1)
