#!/usr/bin/env python3
# HOPEFX-AI-TRADING — Gate C: docker-compose.yml structural validation.
#
# Verifies that critical safety defaults are set correctly in docker-compose.yml:
#   • PAPER_TRADING defaults to "true" (prevents accidental live trading)
#   • IS_FORCE_TLS defaults to "false" (prevents Redis startup failures)
#   • REDIS_FORCE_TLS defaults to "false" (same reason)
#   • alertmanager uses build: not image: (so envsubst entrypoint is used)
#
# Exits 0 on pass, 1 on failure.
from __future__ import annotations

import re
import sys
from pathlib import Path

try:
    import yaml  # PyYAML
    _HAVE_YAML = True
except ImportError:
    _HAVE_YAML = False

REPO_ROOT = Path(__file__).resolve().parents[2]
DOCKER_COMPOSE = REPO_ROOT / "docker-compose.yml"


def _check_yaml(content: str) -> list[str]:
    """Parse YAML and validate structural constraints."""
    failures: list[str] = []
    try:
        doc = yaml.safe_load(content)
    except yaml.YAMLError as exc:
        return [f"docker-compose.yml YAML parse error: {exc}"]

    services = doc.get("services", {})

    for svc_name, svc in services.items():
        env = svc.get("environment", {}) or {}
        if isinstance(env, list):
            # List form: ["KEY=VALUE", ...]
            env_dict = {}
            for item in env:
                if "=" in item:
                    k, v = item.split("=", 1)
                    env_dict[k] = v
            env = env_dict

        # Check PAPER_TRADING default
        pt = env.get("PAPER_TRADING", "")
        if pt and ":-" in pt:
            default = re.search(r"\$\{[^}]+:-([^}]*)\}", pt)
            if default and default.group(1).lower() not in ("true", "1"):
                failures.append(
                    f"services.{svc_name}: PAPER_TRADING default is "
                    f"'{default.group(1)}', must be 'true'"
                )

        # Check IS_FORCE_TLS default
        tls = env.get("IS_FORCE_TLS", "")
        if tls and ":-" in tls:
            default = re.search(r"\$\{[^}]+:-([^}]*)\}", tls)
            if default and default.group(1).lower() not in ("false", "0", ""):
                failures.append(
                    f"services.{svc_name}: IS_FORCE_TLS default is "
                    f"'{default.group(1)}', must be 'false' (prevents Redis TLS startup failure)"
                )

        # Check REDIS_FORCE_TLS default
        rtls = env.get("REDIS_FORCE_TLS", "")
        if rtls and ":-" in rtls:
            default = re.search(r"\$\{[^}]+:-([^}]*)\}", rtls)
            if default and default.group(1).lower() not in ("false", "0", ""):
                failures.append(
                    f"services.{svc_name}: REDIS_FORCE_TLS default is "
                    f"'{default.group(1)}', must be 'false'"
                )

    # Alertmanager must use build: not image: (so envsubst entrypoint runs)
    alertmanager = services.get("alertmanager", {})
    if alertmanager:
        if "image" in alertmanager and "build" not in alertmanager:
            failures.append(
                "services.alertmanager: uses image: without build: — "
                "env vars in alertmanager.yml.tmpl won't be substituted. "
                "Use build: ./monitoring/alertmanager with the envsubst entrypoint."
            )

    return failures


def _check_regex(content: str) -> list[str]:
    """Fallback regex checks when PyYAML is not available."""
    failures: list[str] = []

    for m in re.finditer(r"PAPER_TRADING:\s+\$\{PAPER_TRADING:-([^}]+)\}", content):
        if m.group(1).lower() not in ("true", "1"):
            failures.append(f"PAPER_TRADING default is '{m.group(1)}', must be 'true'")

    for m in re.finditer(r"IS_FORCE_TLS:\s+\$\{IS_FORCE_TLS:-([^}]+)\}", content):
        if m.group(1).lower() not in ("false", "0", ""):
            failures.append(f"IS_FORCE_TLS default is '{m.group(1)}', must be 'false'")

    for m in re.finditer(r"REDIS_FORCE_TLS:\s+\$\{REDIS_FORCE_TLS:-([^}]+)\}", content):
        if m.group(1).lower() not in ("false", "0", ""):
            failures.append(f"REDIS_FORCE_TLS default is '{m.group(1)}', must be 'false'")

    if re.search(r"alertmanager:\s*\n\s+image:", content) and \
            not re.search(r"alertmanager:\s*\n\s+build:", content):
        failures.append("alertmanager uses image: without build: — envsubst won't run")

    return failures


def main() -> int:
    if not DOCKER_COMPOSE.exists():
        print(f"Gate C ERROR: {DOCKER_COMPOSE} not found")
        return 1

    content = DOCKER_COMPOSE.read_text(encoding="utf-8")

    if _HAVE_YAML:
        failures = _check_yaml(content)
    else:
        failures = _check_regex(content)

    if failures:
        print(f"Gate C FAILED — {len(failures)} structural issue(s) in docker-compose.yml:")
        for f in failures:
            print(f"  • {f}")
        return 1

    print("Gate C PASSED — docker-compose.yml structural validation OK.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
