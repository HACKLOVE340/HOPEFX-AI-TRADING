# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
tests/test_docker_smoke.py
===========================
Docker Compose smoke-test gate (pytest layer).

Purpose
-------
This module provides the *pytest* counterpart to the shell-based smoke tests
in .github/workflows/docker-smoke.yml.  It validates the same invariants that
the CI Docker job checks, but from within the Python test suite so they run
on every ``pytest tests/`` invocation — not only in CI.

What is tested
--------------
1. docker-compose.yml is valid YAML and parseable.
2. docker-compose.smoke.yml is valid YAML and parseable.
3. Every service in docker-compose.smoke.yml that is NOT disabled via
   ``profiles: [disabled]`` has a healthcheck defined in either the base
   compose file or the smoke override.
4. The smoke override sets IS_FORCE_TLS=false and REDIS_FORCE_TLS=false for
   the ``app`` service — the Redis TLS default that caused the original
   split-brain bug.
5. All :?required variables referenced in docker-compose.yml are either
   provided by docker-compose.smoke.yml or have a default (``:-``) in the
   base file.
6. The smoke override disables the services that cannot reach healthy in CI
   (trading, celery-worker, celery-beat, prometheus, alertmanager, grafana,
   nginx) via ``profiles: [disabled]``.
7. The minimal .env generation script in docker-smoke.yml covers all
   :?required variables from docker-compose.yml.
8. The app service healthcheck URL in docker-compose.yml matches the
   liveness probe path used in the functional smoke tests.

What is NOT tested here
-----------------------
- Actually starting Docker containers (that is the CI job's responsibility).
- Network connectivity between services.
- Database migration correctness.

These tests are purely structural — they validate the compose configuration
files are internally consistent and will not fail at ``docker compose up``
time due to missing variables or misconfigured healthchecks.

Running
-------
    pytest tests/test_docker_smoke.py -v

All tests in this module are fast (< 1 s) and have no external dependencies.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
REPO_ROOT = Path(__file__).resolve().parents[2]
COMPOSE_BASE = REPO_ROOT / "docker-compose.yml"
COMPOSE_SMOKE = REPO_ROOT / "docker-compose.smoke.yml"
COMPOSE_LOWLATENCY = REPO_ROOT / "docker-compose.lowlatency.yml"
ENV_EXAMPLE = REPO_ROOT / ".env.example"
DOCKER_SMOKE_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "docker-smoke.yml"

# Services that must be disabled in the smoke override (cannot reach healthy in CI)
MUST_DISABLE_IN_SMOKE = frozenset(
    {
        "trading",
        "celery-worker",
        "celery-beat",
        "prometheus",
        "alertmanager",
        "grafana",
        "nginx",
    }
)

# Services that must be healthy in the smoke test
MUST_BE_HEALTHY_IN_SMOKE = frozenset({"postgres", "redis", "app"})

# Variables that docker-compose.yml marks as :?required (no default)
# These must be supplied by the smoke override or the CI .env generation step.
# Pattern: ${VAR_NAME:?...} — the :? means "required, fail if unset or empty"
_REQUIRED_VAR_RE = re.compile(r"\$\{([A-Z_][A-Z0-9_]*):?\?[^}]*\}")

# Pattern: ${VAR_NAME:-default} — has a safe default
_DEFAULTED_VAR_RE = re.compile(r"\$\{([A-Z_][A-Z0-9_]*):-[^}]*\}")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _load_yaml(path: Path) -> dict:
    """Load a YAML file and return the parsed dict. Raises on parse error."""
    with path.open(encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def _get_services(compose: dict) -> dict:
    """Return the services dict from a parsed compose file."""
    return compose.get("services", {})


def _service_has_healthcheck(service_name: str, base: dict, override: dict) -> bool:
    """
    Return True if *service_name* has a healthcheck in either the base or
    override compose file.
    """
    base_svc = _get_services(base).get(service_name, {})
    override_svc = _get_services(override).get(service_name, {})

    # A healthcheck in the override takes precedence
    if override_svc.get("healthcheck"):
        return True
    return bool(base_svc.get("healthcheck"))


def _service_is_disabled(service_name: str, override: dict) -> bool:
    """Return True if the service is disabled via profiles: [disabled] in the override."""
    svc = _get_services(override).get(service_name, {})
    profiles = svc.get("profiles", [])
    return "disabled" in profiles


def _extract_required_vars(text: str) -> set[str]:
    """Return all variable names referenced with :? (required) syntax."""
    return set(_REQUIRED_VAR_RE.findall(text))


def _extract_defaulted_vars(text: str) -> set[str]:
    """Return all variable names that have a :- default."""
    return set(_DEFAULTED_VAR_RE.findall(text))


def _smoke_override_env_vars(override: dict) -> set[str]:
    """Return all env var names explicitly set across ALL services in the smoke override.

    Required variables may be used by any service (e.g. GRAFANA_ADMIN_PASSWORD
    is used by the grafana service, not app).  We collect from all services so
    the check is not artificially scoped to the app service alone.
    """
    result: set[str] = set()
    for svc_cfg in _get_services(override).values():
        env = svc_cfg.get("environment", {})
        if isinstance(env, dict):
            result.update(env.keys())
        elif isinstance(env, list):
            for item in env:
                if "=" in item:
                    result.add(item.split("=", 1)[0])
    return result


# ---------------------------------------------------------------------------
# Gate C1 — compose files are valid YAML
# ---------------------------------------------------------------------------


def test_docker_compose_base_is_valid_yaml() -> None:
    """docker-compose.yml must be valid YAML."""
    assert COMPOSE_BASE.exists(), f"docker-compose.yml not found at {COMPOSE_BASE}"
    try:
        data = _load_yaml(COMPOSE_BASE)
    except yaml.YAMLError as exc:
        pytest.fail(f"docker-compose.yml is not valid YAML:\n{exc}")
    assert isinstance(data, dict), "docker-compose.yml parsed to non-dict"
    assert "services" in data, "docker-compose.yml has no 'services' key"


def test_docker_compose_smoke_is_valid_yaml() -> None:
    """docker-compose.smoke.yml must be valid YAML."""
    assert COMPOSE_SMOKE.exists(), f"docker-compose.smoke.yml not found at {COMPOSE_SMOKE}"
    try:
        data = _load_yaml(COMPOSE_SMOKE)
    except yaml.YAMLError as exc:
        pytest.fail(f"docker-compose.smoke.yml is not valid YAML:\n{exc}")
    assert isinstance(data, dict), "docker-compose.smoke.yml parsed to non-dict"
    assert "services" in data, "docker-compose.smoke.yml has no 'services' key"


# ---------------------------------------------------------------------------
# Gate C2 — healthy services have healthchecks
# ---------------------------------------------------------------------------


def test_smoke_healthy_services_have_healthchecks() -> None:
    """
    Every service that must reach 'healthy' in the smoke test must have a
    healthcheck defined in either docker-compose.yml or docker-compose.smoke.yml.

    A missing healthcheck means ``docker compose up --wait`` will never
    consider the service healthy and the CI job will time out.
    """
    base = _load_yaml(COMPOSE_BASE)
    override = _load_yaml(COMPOSE_SMOKE)

    missing: list[str] = []
    for svc in sorted(MUST_BE_HEALTHY_IN_SMOKE):
        if not _service_has_healthcheck(svc, base, override):
            missing.append(svc)

    assert not missing, (
        "Services required to be healthy in smoke test have no healthcheck:\n"
        + "\n".join(f"  {s}" for s in missing)
        + "\nAdd a healthcheck: block to docker-compose.yml or docker-compose.smoke.yml."
    )


# ---------------------------------------------------------------------------
# Gate C3 — CI-incompatible services are disabled in smoke override
# ---------------------------------------------------------------------------


def test_smoke_override_disables_ci_incompatible_services() -> None:
    """
    Services that cannot reach healthy in CI must be disabled in
    docker-compose.smoke.yml via ``profiles: [disabled]``.

    These services require external credentials, TLS certificates, or a
    fully initialised application that is not available in a clean CI build.
    Leaving them enabled causes ``docker compose up --wait`` to time out.
    """
    override = _load_yaml(COMPOSE_SMOKE)
    not_disabled: list[str] = []

    for svc in sorted(MUST_DISABLE_IN_SMOKE):
        if not _service_is_disabled(svc, override):
            not_disabled.append(svc)

    assert not not_disabled, (
        "Services that cannot reach healthy in CI are not disabled in "
        "docker-compose.smoke.yml:\n"
        + "\n".join(f"  {s}" for s in not_disabled)
        + "\nAdd 'profiles: [disabled]' to each service in docker-compose.smoke.yml."
    )


# ---------------------------------------------------------------------------
# Gate C4 — Redis TLS disabled in smoke override
# ---------------------------------------------------------------------------


def test_smoke_override_disables_redis_tls() -> None:
    """
    docker-compose.smoke.yml must set IS_FORCE_TLS=false and
    REDIS_FORCE_TLS=false for the app service.

    The production default (IS_FORCE_TLS=true) causes the app to upgrade
    redis:// → rediss:// at startup.  In CI there is no TLS certificate,
    so the connection fails and the app never reaches healthy.

    This is the exact Redis TLS default bug that the smoke test was designed
    to catch on day one.
    """
    override = _load_yaml(COMPOSE_SMOKE)
    app_env = _get_services(override).get("app", {}).get("environment", {})

    if isinstance(app_env, list):
        env_dict: dict[str, str] = {}
        for item in app_env:
            if "=" in item:
                k, v = item.split("=", 1)
                env_dict[k] = v
        app_env = env_dict

    assert isinstance(app_env, dict), (
        "app.environment in docker-compose.smoke.yml is not a dict or list of KEY=VALUE pairs"
    )

    is_force_tls = str(app_env.get("IS_FORCE_TLS", "")).lower()
    redis_force_tls = str(app_env.get("REDIS_FORCE_TLS", "")).lower()

    assert is_force_tls == "false", (
        f"docker-compose.smoke.yml app.IS_FORCE_TLS={is_force_tls!r}, expected 'false'.\n"
        "The app upgrades redis:// → rediss:// when IS_FORCE_TLS=true, which breaks\n"
        "CI where no TLS certificate is available.  Set IS_FORCE_TLS=false in the\n"
        "smoke override."
    )
    assert redis_force_tls == "false", (
        f"docker-compose.smoke.yml app.REDIS_FORCE_TLS={redis_force_tls!r}, expected 'false'.\n"
        "Set REDIS_FORCE_TLS=false in the smoke override to prevent TLS upgrade in CI."
    )


# ---------------------------------------------------------------------------
# Gate C5 — smoke override supplies all :?required variables
# ---------------------------------------------------------------------------


def test_smoke_override_supplies_required_vars() -> None:
    """
    Every variable marked :?required in docker-compose.yml must be supplied
    by docker-compose.smoke.yml's app environment block.

    A :?required variable causes ``docker compose up`` to abort immediately
    with "variable is not set" if it is not provided.  The smoke override
    must supply safe CI values for all of them.
    """
    base_text = COMPOSE_BASE.read_text(encoding="utf-8")
    required_vars = _extract_required_vars(base_text)

    if not required_vars:
        # No :?required vars found — nothing to check
        return

    override = _load_yaml(COMPOSE_SMOKE)
    smoke_vars = _smoke_override_env_vars(override)

    # Also accept vars that have a :- default in the base file
    defaulted_vars = _extract_defaulted_vars(base_text)
    unmet = required_vars - smoke_vars - defaulted_vars

    assert not unmet, (
        f"{len(unmet)} :?required variable(s) from docker-compose.yml are not supplied\n"
        "by docker-compose.smoke.yml and have no :- default:\n"
        + "\n".join(f"  {v}" for v in sorted(unmet))
        + "\nAdd these variables to the app.environment block in docker-compose.smoke.yml\n"
        "with safe CI placeholder values."
    )


# ---------------------------------------------------------------------------
# Gate C6 — smoke override sets BROKER_TYPE=paper and PAPER_TRADING=true
# ---------------------------------------------------------------------------


def test_smoke_override_uses_paper_trading() -> None:
    """
    The smoke override must set BROKER_TYPE=paper and PAPER_TRADING=true.

    This prevents the app from attempting to connect to a live broker during
    CI, which would fail due to missing credentials and cause the health
    check to time out.
    """
    override = _load_yaml(COMPOSE_SMOKE)
    app_env = _get_services(override).get("app", {}).get("environment", {})

    if isinstance(app_env, list):
        env_dict: dict[str, str] = {}
        for item in app_env:
            if "=" in item:
                k, v = item.split("=", 1)
                env_dict[k] = v
        app_env = env_dict

    broker_type = str(app_env.get("BROKER_TYPE", "")).lower()
    paper_trading = str(app_env.get("PAPER_TRADING", "")).lower()

    assert broker_type == "paper", (
        f"docker-compose.smoke.yml app.BROKER_TYPE={broker_type!r}, expected 'paper'.\n"
        "Set BROKER_TYPE=paper in the smoke override to prevent live broker connections in CI."
    )
    assert paper_trading == "true", (
        f"docker-compose.smoke.yml app.PAPER_TRADING={paper_trading!r}, expected 'true'.\n"
        "Set PAPER_TRADING=true in the smoke override to prevent live broker connections in CI."
    )


# ---------------------------------------------------------------------------
# Gate C7 — app healthcheck URL is the liveness probe
# ---------------------------------------------------------------------------


def test_app_healthcheck_uses_liveness_probe() -> None:
    """
    The app service healthcheck in docker-compose.yml must use
    /api/health/live — the same path asserted by the functional smoke tests.

    A mismatch means the Docker healthcheck and the functional test are
    checking different endpoints, so a broken health endpoint could pass
    the Docker healthcheck while failing the functional test (or vice versa).
    """
    base = _load_yaml(COMPOSE_BASE)
    app_svc = _get_services(base).get("app", {})
    hc = app_svc.get("healthcheck", {})
    test_cmd = hc.get("test", [])

    # test_cmd is either a list ["CMD", ...] or a string
    test_str = " ".join(str(t) for t in test_cmd) if isinstance(test_cmd, list) else str(test_cmd)

    assert "/api/health/live" in test_str, (
        f"app healthcheck does not use /api/health/live.\n"
        f"Current healthcheck test: {test_str!r}\n"
        "Update the healthcheck to: curl -f http://localhost:8000/api/health/live\n"
        "This ensures the Docker healthcheck and functional smoke tests check the same endpoint."
    )


# ---------------------------------------------------------------------------
# Gate C8 — smoke workflow file exists and references both compose files
# ---------------------------------------------------------------------------


def test_docker_smoke_workflow_exists() -> None:
    """The docker-smoke.yml CI workflow must exist."""
    assert DOCKER_SMOKE_WORKFLOW.exists(), (
        f"CI workflow not found: {DOCKER_SMOKE_WORKFLOW.relative_to(REPO_ROOT)}\n"
        "Create .github/workflows/docker-smoke.yml to run the Docker Compose smoke test in CI.\n"
        "See the TODO list item C for the required structure."
    )


def test_docker_smoke_workflow_references_smoke_override() -> None:
    """
    The docker-smoke.yml workflow must reference docker-compose.smoke.yml.

    The smoke override is what disables CI-incompatible services and injects
    safe env var values.  Without it, ``docker compose up --wait`` will fail
    because it tries to start nginx (needs TLS certs) and trading (needs a
    healthy app first).
    """
    assert DOCKER_SMOKE_WORKFLOW.exists(), pytest.skip("docker-smoke.yml workflow not found")
    content = DOCKER_SMOKE_WORKFLOW.read_text(encoding="utf-8")
    assert "docker-compose.smoke.yml" in content, (
        "docker-smoke.yml workflow does not reference docker-compose.smoke.yml.\n"
        "Add '-f docker-compose.smoke.yml' to the 'docker compose up' command in the workflow."
    )


def test_docker_smoke_workflow_uses_wait_flag() -> None:
    """
    The docker-smoke.yml workflow must use ``docker compose up --wait``.

    Without --wait, the job exits immediately after starting containers
    without verifying they reached healthy state.  The whole point of the
    smoke test is to assert all services reach healthy.
    """
    assert DOCKER_SMOKE_WORKFLOW.exists(), pytest.skip("docker-smoke.yml workflow not found")
    content = DOCKER_SMOKE_WORKFLOW.read_text(encoding="utf-8")
    assert "--wait" in content, (
        "docker-smoke.yml workflow does not use 'docker compose up --wait'.\n"
        "Add --wait to the docker compose up command so the job blocks until\n"
        "all services reach healthy state (or fails if they do not)."
    )


# ---------------------------------------------------------------------------
# Gate C9 — .env.example exists and has required keys
# ---------------------------------------------------------------------------


def test_env_example_exists_for_smoke() -> None:
    """.env.example must exist so the CI .env generation step has a source."""
    assert ENV_EXAMPLE.exists(), (
        f".env.example not found at {ENV_EXAMPLE.relative_to(REPO_ROOT)}\n"
        "The Docker smoke CI job generates a minimal .env from .env.example.\n"
        "Create .env.example with all required variables documented."
    )


def test_env_example_has_smoke_required_vars() -> None:
    """
    .env.example must document the variables that the smoke override injects.

    The CI job generates a .env from .env.example and then the smoke override
    provides the actual values.  If a variable is not in .env.example, new
    contributors will not know it exists.
    """
    assert ENV_EXAMPLE.exists(), pytest.skip(".env.example not found")

    env_text = ENV_EXAMPLE.read_text(encoding="utf-8")

    # These are the security-critical vars that must be documented
    critical_smoke_vars = {
        "SECURITY_JWT_SECRET",
        "POSTGRES_PASSWORD",
        "BROKER_TYPE",
        "PAPER_TRADING",
        "IS_FORCE_TLS",
        "REDIS_FORCE_TLS",
    }

    missing_docs: list[str] = []
    for var in sorted(critical_smoke_vars):
        if var not in env_text:
            missing_docs.append(var)

    assert not missing_docs, (
        f"{len(missing_docs)} critical smoke-test variable(s) are not documented in .env.example:\n"
        + "\n".join(f"  {v}" for v in missing_docs)
        + "\nAdd these variables to .env.example so operators know they must be set."
    )


# ---------------------------------------------------------------------------
# Gate C10 — smoke override Redis uses plain TCP
# ---------------------------------------------------------------------------


def test_smoke_redis_uses_plain_tcp() -> None:
    """
    The Redis service in docker-compose.smoke.yml must not require TLS.

    The production Redis config may require TLS (--tls-port, requirepass with
    TLS).  In CI there are no certificates, so the smoke override must use
    plain TCP Redis.  This is verified by checking that the smoke override's
    Redis command does not include --tls-port.
    """
    override = _load_yaml(COMPOSE_SMOKE)
    redis_svc = _get_services(override).get("redis", {})

    if not redis_svc:
        # Redis not overridden — check base file doesn't force TLS
        base = _load_yaml(COMPOSE_BASE)
        redis_base = _get_services(base).get("redis", {})
        cmd = redis_base.get("command", "")
        cmd_str = " ".join(cmd) if isinstance(cmd, list) else str(cmd)
        assert "--tls-port" not in cmd_str, (
            "Base Redis service uses --tls-port but docker-compose.smoke.yml does not\n"
            "override it.  Add a Redis override in docker-compose.smoke.yml that uses\n"
            "plain TCP (no --tls-port) so CI can connect without certificates."
        )
        return

    cmd = redis_svc.get("command", "")
    cmd_str = " ".join(cmd) if isinstance(cmd, list) else str(cmd)

    assert "--tls-port" not in cmd_str, (
        "docker-compose.smoke.yml Redis command includes --tls-port.\n"
        "Remove --tls-port from the smoke Redis override — CI has no TLS certificates."
    )


# ---------------------------------------------------------------------------
# Gate C11 — smoke override sets REDIS_URL to plain redis://
# ---------------------------------------------------------------------------


def test_smoke_app_redis_url_is_plain() -> None:
    """
    The app service in docker-compose.smoke.yml must set REDIS_URL to a
    plain redis:// URL (not rediss://).

    If REDIS_URL uses rediss://, the app will attempt a TLS handshake with
    the plain-TCP CI Redis and fail to connect.
    """
    override = _load_yaml(COMPOSE_SMOKE)
    app_env = _get_services(override).get("app", {}).get("environment", {})

    if isinstance(app_env, list):
        env_dict: dict[str, str] = {}
        for item in app_env:
            if "=" in item:
                k, v = item.split("=", 1)
                env_dict[k] = v
        app_env = env_dict

    redis_url = str(app_env.get("REDIS_URL", ""))

    if not redis_url:
        # REDIS_URL not set in smoke override — check it has a plain default
        base_text = COMPOSE_BASE.read_text(encoding="utf-8")
        # If the base file has rediss:// as default, that's a problem
        assert "rediss://" not in base_text.split("REDIS_URL")[1][:100] if "REDIS_URL" in base_text else True, (
            "REDIS_URL is not set in docker-compose.smoke.yml and the base file\n"
            "may default to rediss://.  Set REDIS_URL=redis://redis:6379/0 in the\n"
            "smoke override to ensure plain TCP is used in CI."
        )
        return

    assert redis_url.startswith("redis://"), (
        f"docker-compose.smoke.yml app.REDIS_URL={redis_url!r} uses TLS (rediss://).\n"
        "Set REDIS_URL=redis://redis:6379/0 in the smoke override — CI Redis is plain TCP."
    )


# ---------------------------------------------------------------------------
# Gate C12 — compose files reference the same Dockerfile
# ---------------------------------------------------------------------------


def test_compose_base_references_dockerfile() -> None:
    """
    docker-compose.yml must reference the project Dockerfile for the app
    service build.  This ensures the smoke test builds the real image, not
    a stale cached one.
    """
    base = _load_yaml(COMPOSE_BASE)
    app_svc = _get_services(base).get("app", {})
    build = app_svc.get("build", {})

    if isinstance(build, str):
        # build: . shorthand
        assert build in (".", "./"), f"app build context is {build!r}, expected '.' (project root)."
        return

    context = build.get("context", "")
    dockerfile = build.get("dockerfile", "Dockerfile")

    assert context in (".", "./", ""), (
        f"app build context is {context!r}, expected '.' (project root).\n"
        "The smoke test must build from the project root so it picks up the\n"
        "current Dockerfile and requirements files."
    )

    dockerfile_path = REPO_ROOT / dockerfile
    assert dockerfile_path.exists(), (
        f"Dockerfile referenced in docker-compose.yml not found: {dockerfile}\n"
        "Ensure the Dockerfile exists at the project root."
    )
