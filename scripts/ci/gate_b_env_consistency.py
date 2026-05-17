#!/usr/bin/env python3
# HOPEFX-AI-TRADING — Gate B: env-var consistency between .env.example
# and docker-compose.yml.
#
# Every environment variable injected into services in docker-compose.yml
# must have a corresponding entry in .env.example so operators know what
# to set.  Exits 0 on pass, 1 on failure.
from __future__ import annotations

import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
ENV_EXAMPLE = REPO_ROOT / ".env.example"
DOCKER_COMPOSE = REPO_ROOT / "docker-compose.yml"

# Vars set directly by docker-compose internals or well-known tooling;
# they don't need a .env.example entry.
COMPOSE_INTERNAL: frozenset[str] = frozenset({
    "DATABASE_URL",   # composed from individual DB vars
    "REDIS_URL",      # composed from REDIS_HOST + REDIS_PASSWORD
    "REDIS_HOST",     # set to the redis service name
    "REDIS_PORT",     # set to the redis service port
    "API_HOST",       # hardcoded to 0.0.0.0
    "API_PORT",       # hardcoded to 8000
    "ALLOWED_ORIGINS",  # derived from HOPEFX_DOMAIN in compose
})


def _parse_env_example(path: Path) -> set[str]:
    """Return all KEY names from .env.example (lines matching KEY=...)."""
    keys: set[str] = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        m = re.match(r"^([A-Z][A-Z0-9_]*)=", line)
        if m:
            keys.add(m.group(1))
    return keys


def _parse_docker_compose_env(path: Path) -> set[str]:
    """
    Return all env var names REFERENCED (via ${VAR} or ${VAR:-default}) in
    `environment:` blocks in docker-compose.yml.

    Only variable names that operators must supply in .env are collected —
    literal values (e.g. GF_USERS_ALLOW_SIGN_UP: "false") are ignored because
    they don't need a .env.example entry.

    Handles the indented YAML used in this repo:
      services:
        app:                         (2-space indent)
          environment:               (4-space indent)
            IS_FORCE_TLS: ${IS_FORCE_TLS:-false}  (6-space indent)
          volumes:                   (4-space indent — exits env block)
    """
    keys: set[str] = set()
    env_indent: int | None = None

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        if not raw_line.strip() or raw_line.strip().startswith("#"):
            continue

        indent = len(raw_line) - len(raw_line.lstrip())
        stripped = raw_line.strip()

        if stripped == "environment:":
            env_indent = indent
            continue

        if env_indent is not None:
            if indent <= env_indent:
                env_indent = None
                if stripped == "environment:":
                    env_indent = indent
                continue

            # Extract all ${VAR} and ${VAR:-default} references in the value
            for m in re.finditer(r"\$\{([A-Z][A-Z0-9_]*)[^}]*\}", raw_line):
                keys.add(m.group(1))

    return keys


def main() -> int:
    if not ENV_EXAMPLE.exists():
        print(f"Gate B ERROR: {ENV_EXAMPLE} not found")
        return 1
    if not DOCKER_COMPOSE.exists():
        print(f"Gate B ERROR: {DOCKER_COMPOSE} not found")
        return 1

    env_keys = _parse_env_example(ENV_EXAMPLE)
    compose_keys = _parse_docker_compose_env(DOCKER_COMPOSE)

    missing_from_env = (compose_keys - env_keys) - COMPOSE_INTERNAL

    if missing_from_env:
        print(f"Gate B FAILED — {len(missing_from_env)} var(s) in docker-compose.yml "
              f"have no entry in .env.example:")
        for k in sorted(missing_from_env):
            print(f"  {k}")
        print()
        print("Add these variables to .env.example so operators know what to configure.")
        return 1

    print(
        f"Gate B PASSED — all {len(compose_keys)} docker-compose env vars "
        f"have .env.example entries ({len(env_keys)} total in .env.example)."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
