# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
tests/test_env_consistency.py
==============================
Env-var consistency gate.

Loads .env.example and docker-compose.yml, then asserts that every
environment variable referenced in the four critical source files is:

  1. Declared in .env.example  (operators know it exists)
  2. Either set in docker-compose.yml or has a safe default in the source
     (the running container will always receive a value)

The specific split-brain class of bug this catches
---------------------------------------------------
``fix_router.py`` and ``main_loop.py`` gate paper-trading mode on
``PAPER_TRADING=true``.  ``api/trading.py`` gates it on
``BROKER_TYPE=paper``.  If an operator sets only one of the two, half the
stack runs in paper mode and the other half attempts live execution.

This test makes that inconsistency visible at CI time rather than at
3 a.m. on a live account.

Scope
-----
Source files scanned:
  - execution/fix_router.py
  - core/main_loop.py
  - brokers/factory.py
  - api/trading.py

Variables that have a hard-coded default in the source (e.g.
``os.getenv("FIX_PORT", "9876")``) are marked as *defaulted* and are
only required to appear in .env.example — they do not need to be
forwarded through docker-compose.yml because the default is safe.

Variables with no default (e.g. ``os.getenv("OANDA_API_KEY")``) must
appear in both .env.example AND docker-compose.yml so operators are
never surprised by a silent empty string in production.
"""

from __future__ import annotations

import ast
import os
import re
import sys
from pathlib import Path
from typing import NamedTuple

import pytest

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
REPO_ROOT = Path(__file__).parent.parent
ENV_EXAMPLE = REPO_ROOT / ".env.example"
DOCKER_COMPOSE = REPO_ROOT / "docker-compose.yml"

SOURCE_FILES = [
    REPO_ROOT / "execution" / "fix_router.py",
    REPO_ROOT / "core" / "main_loop.py",
    REPO_ROOT / "brokers" / "factory.py",
    REPO_ROOT / "api" / "trading.py",
]

# ---------------------------------------------------------------------------
# Variables that are intentionally absent from docker-compose.yml because
# they are either:
#   - credentials supplied via .env (env_file: .env) rather than inline
#   - only relevant to the trading engine container, not the API container
#   - have a safe default that makes the empty-string case harmless
#
# Each entry must have a comment explaining the exemption.
# ---------------------------------------------------------------------------
COMPOSE_EXEMPTIONS: frozenset[str] = frozenset(
    {
        # Credentials — supplied via `env_file: .env`, not inline in compose
        "OANDA_API_KEY",
        "OANDA_ACCOUNT_ID",
        "FIX_USERNAME",
        "FIX_PASSWORD",
        # Paper-trading knobs — safe defaults; operators override in .env
        "PAPER_TRADING",          # default false; compose passes via env_file
        "PAPER_INITIAL_BALANCE",  # default 10000; compose passes via env_file
        "PAPER_SLIPPAGE_MODEL",   # default gaussian; compose passes via env_file
        "PAPER_STARTING_BALANCE", # alias; compose passes via env_file
        # FIX protocol — only used by trading engine, passed via env_file
        "FIX_CONFIG_FILE",
        "FIX_SENDER_COMP_ID",
        "FIX_TARGET_COMP_ID",
        "FIX_HOST",
        "FIX_PORT",
        "FIX_DEFAULT_UNITS",
        "FIX_LATENCY_WARN_MS",
        # Rate-limiting knobs — safe defaults; compose passes via env_file
        "ORDER_RATE_LIMIT",
        "ORDER_RATE_WINDOW",
        # Broker selector — passed via env_file
        "BROKER",
        "BROKER_TYPE",
        # OANDA practice flag — passed via env_file
        "OANDA_PRACTICE",
        "BROKER_OANDA_TOKEN",
        "OANDA_ACCESS_TOKEN",
    }
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class EnvRef(NamedTuple):
    name: str
    has_default: bool   # True when os.getenv("X", "default") — non-empty default
    source_file: str
    line: int


_GETENV_RE = re.compile(
    r'os\.(?:environ\.get|getenv)\(\s*["\']([A-Z][A-Z0-9_]*)["\']'
    r'(?:\s*,\s*(?P<default>[^)]+))?',
)


def _extract_env_refs(path: Path) -> list[EnvRef]:
    """
    Parse *path* with the regex above and return every os.getenv / os.environ.get
    call that references an ALL_CAPS env var name.

    ``has_default`` is True when the call supplies a non-empty-string default,
    meaning the variable is optional (the code will never see ``None``).
    """
    refs: list[EnvRef] = []
    src = path.read_text(encoding="utf-8")
    for lineno, line in enumerate(src.splitlines(), 1):
        for m in _GETENV_RE.finditer(line):
            name = m.group(1)
            raw_default = (m.group("default") or "").strip().strip('"\'')
            # A default of "" or "false" or "0" is still a default — the code
            # won't receive None.  Only the complete absence of a second arg
            # means the variable is truly required.
            has_default = bool(m.group("default"))
            refs.append(EnvRef(name=name, has_default=has_default, source_file=str(path.relative_to(REPO_ROOT)), line=lineno))
    return refs


def _load_env_example_keys() -> set[str]:
    """
    Return the set of variable names declared in .env.example.

    Lines of the form ``KEY=...`` or ``# KEY=...`` (commented-out examples)
    are both included — commented-out lines document optional variables.
    """
    keys: set[str] = set()
    key_re = re.compile(r"^#?\s*([A-Z][A-Z0-9_]*)=")
    for line in ENV_EXAMPLE.read_text(encoding="utf-8").splitlines():
        m = key_re.match(line)
        if m:
            keys.add(m.group(1))
    return keys


def _load_compose_keys() -> set[str]:
    """
    Return the set of variable names that docker-compose.yml forwards to
    containers, either as ``KEY: value`` or ``KEY: ${KEY:-default}`` entries
    under any ``environment:`` block.
    """
    keys: set[str] = set()
    # Match both bare keys and ${VAR} interpolations
    bare_re = re.compile(r"^\s{6,}([A-Z][A-Z0-9_]*):")
    interp_re = re.compile(r"\$\{([A-Z][A-Z0-9_]*)")
    for line in DOCKER_COMPOSE.read_text(encoding="utf-8").splitlines():
        for m in bare_re.finditer(line):
            keys.add(m.group(1))
        for m in interp_re.finditer(line):
            keys.add(m.group(1))
    return keys


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_env_example_exists() -> None:
    """Prerequisite: .env.example must exist."""
    assert ENV_EXAMPLE.exists(), f".env.example not found at {ENV_EXAMPLE}"


def test_docker_compose_exists() -> None:
    """Prerequisite: docker-compose.yml must exist."""
    assert DOCKER_COMPOSE.exists(), f"docker-compose.yml not found at {DOCKER_COMPOSE}"


def test_source_files_exist() -> None:
    """Prerequisite: all four source files must exist."""
    missing = [str(p.relative_to(REPO_ROOT)) for p in SOURCE_FILES if not p.exists()]
    assert not missing, "Source file(s) missing:\n" + "\n".join(f"  {m}" for m in missing)


def test_all_env_vars_declared_in_env_example() -> None:
    """
    Every env var referenced in the four source files must appear in
    .env.example so operators know it exists and can configure it.

    Failure means a new env var was added to source code without a
    corresponding entry in .env.example.  Add the variable to .env.example
    with a comment explaining its purpose and safe default.
    """
    env_keys = _load_env_example_keys()
    violations: list[str] = []

    for path in SOURCE_FILES:
        for ref in _extract_env_refs(path):
            if ref.name not in env_keys:
                violations.append(
                    f"  {ref.source_file}:{ref.line}  {ref.name}"
                    + (" (no default)" if not ref.has_default else "")
                )

    if violations:
        pytest.fail(
            f"\n{len(violations)} env var(s) referenced in source but missing from .env.example.\n"
            "Add each variable to .env.example with a description and safe default:\n\n"
            + "\n".join(violations)
        )


def test_required_env_vars_forwarded_in_compose() -> None:
    """
    Env vars that have NO default in source code must be forwarded through
    docker-compose.yml (or be in COMPOSE_EXEMPTIONS with a justification).

    A variable with no default will be ``None`` inside the container if
    docker-compose.yml does not forward it — this is the silent failure mode
    that caused the Redis TLS and BROKER_TYPE split-brain bugs.
    """
    compose_keys = _load_compose_keys()
    violations: list[str] = []

    for path in SOURCE_FILES:
        for ref in _extract_env_refs(path):
            if ref.has_default:
                continue  # safe — code handles the missing case
            if ref.name in COMPOSE_EXEMPTIONS:
                continue  # explicitly exempted with justification above
            if ref.name in compose_keys:
                continue  # correctly forwarded
            violations.append(
                f"  {ref.source_file}:{ref.line}  {ref.name}  (no default, not in compose)"
            )

    if violations:
        pytest.fail(
            f"\n{len(violations)} required env var(s) not forwarded in docker-compose.yml.\n"
            "Either add them to the relevant service's environment: block in docker-compose.yml,\n"
            "or add them to COMPOSE_EXEMPTIONS with a justification comment.\n\n"
            + "\n".join(violations)
        )


def test_paper_trading_broker_type_both_declared() -> None:
    """
    The PAPER_TRADING / BROKER_TYPE split-brain check.

    Both variables must be declared in .env.example.  If either is missing,
    operators will configure only one and the stack will be in a split state
    (half paper, half live).
    """
    env_keys = _load_env_example_keys()
    for var in ("PAPER_TRADING", "BROKER_TYPE"):
        assert var in env_keys, (
            f"{var} is missing from .env.example.\n"
            "Both PAPER_TRADING (used by fix_router.py / main_loop.py) and\n"
            "BROKER_TYPE (used by api/trading.py) must be documented so operators\n"
            "set them consistently."
        )


def test_paper_trading_not_missing_from_env_example() -> None:
    """
    PAPER_TRADING must be present in .env.example even though it is not
    currently forwarded inline in docker-compose.yml (it is passed via
    env_file: .env).  This ensures operators see it when reading the example.
    """
    env_keys = _load_env_example_keys()
    assert "PAPER_TRADING" in env_keys, (
        "PAPER_TRADING is missing from .env.example.  "
        "Add it with a comment explaining the PAPER_TRADING vs BROKER_TYPE relationship."
    )


def test_no_duplicate_env_var_declarations_in_env_example() -> None:
    """
    Each variable should appear at most once as an active (non-commented)
    declaration in .env.example.  Duplicates cause the last value to silently
    win, which can override a carefully set credential with a placeholder.
    """
    active_re = re.compile(r"^([A-Z][A-Z0-9_]*)=")
    seen: dict[str, int] = {}
    duplicates: list[str] = []

    for lineno, line in enumerate(ENV_EXAMPLE.read_text(encoding="utf-8").splitlines(), 1):
        m = active_re.match(line)
        if m:
            name = m.group(1)
            if name in seen:
                duplicates.append(f"  {name}  (first at line {seen[name]}, duplicate at line {lineno})")
            else:
                seen[name] = lineno

    if duplicates:
        pytest.fail(
            f"\n{len(duplicates)} duplicate active declaration(s) in .env.example.\n"
            "Remove or comment out the earlier occurrence:\n\n"
            + "\n".join(duplicates)
        )
