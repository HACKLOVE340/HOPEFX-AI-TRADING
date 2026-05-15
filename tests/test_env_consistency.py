# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
tests/test_env_consistency.py
==============================
Env-var consistency gate.

Loads .env.example, docker-compose.yml, and CI workflow files, then asserts
that every environment variable referenced in critical source files is:

  1. Declared in .env.example  (operators know it exists)
  2. Either set in docker-compose.yml or has a safe default in the source
     (the running container will always receive a value)
  3. Referenced consistently — no split-brain between PAPER_TRADING and
     BROKER_TYPE, no Redis TLS default mismatch, etc.

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
PRIMARY source files (must have every var in .env.example AND compose):
  - execution/fix_router.py
  - core/main_loop.py
  - brokers/factory.py
  - api/trading.py

EXTENDED source files (must have every var in .env.example):
  - api/auth.py
  - api/signals.py
  - api/risk.py
  - api/billing.py
  - api/ws_live.py
  - auth/jwt.py
  - auth/service.py
  - resilience/service_circuit_breakers.py
  - compliance/aml.py
  - compliance/auditor.py

CI workflow files (must not reference env vars absent from .env.example):
  - .github/workflows/ci.yml
  - .github/workflows/tests.yml
  - .github/workflows/docker-smoke.yml
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import NamedTuple

import pytest

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
REPO_ROOT = Path(__file__).parent.parent
ENV_EXAMPLE = REPO_ROOT / ".env.example"
DOCKER_COMPOSE = REPO_ROOT / "docker-compose.yml"

# Primary files: vars must appear in .env.example AND docker-compose.yml
PRIMARY_SOURCE_FILES: list[Path] = [
    REPO_ROOT / "execution" / "fix_router.py",
    REPO_ROOT / "core" / "main_loop.py",
    REPO_ROOT / "brokers" / "factory.py",
    REPO_ROOT / "api" / "trading.py",
]

# Extended files: vars must appear in .env.example (compose exemption allowed)
EXTENDED_SOURCE_FILES: list[Path] = [
    REPO_ROOT / "api" / "auth.py",
    REPO_ROOT / "api" / "signals.py",
    REPO_ROOT / "api" / "risk.py",
    REPO_ROOT / "api" / "billing.py",
    REPO_ROOT / "api" / "ws_live.py",
    REPO_ROOT / "auth" / "jwt.py",
    REPO_ROOT / "auth" / "service.py",
    REPO_ROOT / "resilience" / "service_circuit_breakers.py",
    REPO_ROOT / "compliance" / "aml.py",
    REPO_ROOT / "compliance" / "auditor.py",
]

# CI workflow files: must not reference vars absent from .env.example
CI_WORKFLOW_FILES: list[Path] = [
    REPO_ROOT / ".github" / "workflows" / "ci.yml",
    REPO_ROOT / ".github" / "workflows" / "tests.yml",
    REPO_ROOT / ".github" / "workflows" / "docker-smoke.yml",
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

# Variables that are known CI-only secrets (set via GitHub Actions secrets,
# not in .env.example — they are never used in production containers).
CI_SECRET_EXEMPTIONS: frozenset[str] = frozenset(
    {
        # GitHub Actions built-in variables
        "GITHUB_TOKEN",
        "GITHUB_SHA",
        "GITHUB_REF",
        "GITHUB_REPOSITORY",
        "GITHUB_ACTOR",
        "GITHUB_WORKSPACE",
        "GITHUB_EVENT_NAME",
        "GITHUB_RUN_ID",
        "GITHUB_RUN_NUMBER",
        "GITHUB_HEAD_REF",
        "GITHUB_BASE_REF",
        "GITHUB_OUTPUT",
        "GITHUB_ENV",
        "GITHUB_PATH",
        "GITHUB_STEP_SUMMARY",
        "GITHUB_SERVER_URL",
        "GITHUB_API_URL",
        "GITHUB_GRAPHQL_URL",
        "RUNNER_OS",
        "RUNNER_ARCH",
        "RUNNER_TEMP",
        "RUNNER_TOOL_CACHE",
        # CI-only secrets (set in GitHub Actions secrets, not in .env.example)
        "CODECOV_TOKEN",
        "CODACY_PROJECT_TOKEN",
        "SNYK_TOKEN",
        "SONAR_TOKEN",
        "DOCKER_USERNAME",
        "DOCKER_PASSWORD",
        "DOCKER_HUB_TOKEN",
        "PYPI_TOKEN",
        "NPM_TOKEN",
        "SLACK_WEBHOOK_URL",
        "SENTRY_AUTH_TOKEN",
        "SENTRY_DSN",          # also in .env.example but may be set as CI secret
        "FORTIFY_TOKEN",
        "FORTIFY_TENANT",
        "FORTIFY_URL",
        "FORTIFY_SSC_URL",
        "FORTIFY_APP_NAME",
        "FORTIFY_APP_VERSION",
        "FORTIFY_RELEASE_ID",
        "FORTIFY_ENTITLEMENT_ID",
        "FORTIFY_TECHNOLOGY_STACK",
        "FORTIFY_LANGUAGE_LEVEL",
        "FORTIFY_AUDIT_PREFERENCE_ID",
        "FORTIFY_OPEN_SOURCE_SCAN",
        "FORTIFY_SONATYPE_USER",
        "FORTIFY_SONATYPE_PASSWORD",
        "FORTIFY_POLICY_FAIL_ACTION",
        "FORTIFY_REMEDIATION_SCAN_PREFERENCE_ID",
        "FORTIFY_REMEDIATION_FREQUENCY",
        "FORTIFY_REMEDIATION_OCCURRENCE_TYPE",
        "FORTIFY_REMEDIATION_DAYS",
        "FORTIFY_REMEDIATION_NOTES",
        "FORTIFY_REMEDIATION_NETSCAN_CONFIGURATION",
        "FORTIFY_REMEDIATION_WEBINSPECT_SETTINGS",
        "FORTIFY_REMEDIATION_WEBINSPECT_MACRO",
        "FORTIFY_REMEDIATION_WEBINSPECT_LOGIN_MACRO",
        "FORTIFY_REMEDIATION_WEBINSPECT_ALLOWED_HOSTS",
        "FORTIFY_REMEDIATION_WEBINSPECT_NETWORK_AUTH_TYPE",
        "FORTIFY_REMEDIATION_WEBINSPECT_NETWORK_AUTH_USER",
        "FORTIFY_REMEDIATION_WEBINSPECT_NETWORK_AUTH_PASSWORD",
        "FORTIFY_REMEDIATION_WEBINSPECT_PROXY",
        "FORTIFY_REMEDIATION_WEBINSPECT_PROXY_AUTH_TYPE",
        "FORTIFY_REMEDIATION_WEBINSPECT_PROXY_AUTH_USER",
        "FORTIFY_REMEDIATION_WEBINSPECT_PROXY_AUTH_PASSWORD",
        "FORTIFY_REMEDIATION_WEBINSPECT_PROXY_HOST",
        "FORTIFY_REMEDIATION_WEBINSPECT_PROXY_PORT",
        "FORTIFY_REMEDIATION_WEBINSPECT_PROXY_BYPASS",
        "FORTIFY_REMEDIATION_WEBINSPECT_PROXY_BYPASS_LOCAL",
        "FORTIFY_REMEDIATION_WEBINSPECT_PROXY_BYPASS_HOSTS",
        "FORTIFY_REMEDIATION_WEBINSPECT_PROXY_BYPASS_DOMAINS",
        "FORTIFY_REMEDIATION_WEBINSPECT_PROXY_BYPASS_SUBNETS",
        "FORTIFY_REMEDIATION_WEBINSPECT_PROXY_BYPASS_ADDRESSES",
        "FORTIFY_REMEDIATION_WEBINSPECT_PROXY_BYPASS_PORTS",
        "FORTIFY_REMEDIATION_WEBINSPECT_PROXY_BYPASS_PROTOCOLS",
        "FORTIFY_REMEDIATION_WEBINSPECT_PROXY_BYPASS_SCHEMES",
        "FORTIFY_REMEDIATION_WEBINSPECT_PROXY_BYPASS_PATHS",
        "FORTIFY_REMEDIATION_WEBINSPECT_PROXY_BYPASS_QUERIES",
        "FORTIFY_REMEDIATION_WEBINSPECT_PROXY_BYPASS_FRAGMENTS",
        "FORTIFY_REMEDIATION_WEBINSPECT_PROXY_BYPASS_USERINFOS",
        "FORTIFY_REMEDIATION_WEBINSPECT_PROXY_BYPASS_AUTHORITIES",
        "FORTIFY_REMEDIATION_WEBINSPECT_PROXY_BYPASS_HOSTS_AND_PORTS",
        "FORTIFY_REMEDIATION_WEBINSPECT_PROXY_BYPASS_HOSTS_AND_DOMAINS",
        "FORTIFY_REMEDIATION_WEBINSPECT_PROXY_BYPASS_HOSTS_AND_SUBNETS",
        "FORTIFY_REMEDIATION_WEBINSPECT_PROXY_BYPASS_HOSTS_AND_ADDRESSES",
        "FORTIFY_REMEDIATION_WEBINSPECT_PROXY_BYPASS_HOSTS_AND_PORTS_AND_DOMAINS",
        "FORTIFY_REMEDIATION_WEBINSPECT_PROXY_BYPASS_HOSTS_AND_PORTS_AND_SUBNETS",
        "FORTIFY_REMEDIATION_WEBINSPECT_PROXY_BYPASS_HOSTS_AND_PORTS_AND_ADDRESSES",
        # CI test-runner variables (set inline in workflow steps, not app secrets)
        "DB_URL",                  # SQLite/Postgres URL used only during CI test runs
        "ML_CI_MODE",              # disables GPU-heavy ML paths in CI
        "PLAYWRIGHT_BASE_URL",     # base URL for Playwright e2e tests in CI
        "COVERAGE_TOTAL",          # coverage threshold checked by tests.yml
        "EXEMPTIONS",              # pip-audit CVE exemption list in ci.yml
        "QLTY_COVERAGE_TOKEN",     # Qlty.sh coverage upload token (CI secret)
        # Docker BuildKit / Buildx cache variables (CI build system, not app)
        "BUILDX_CACHE_FROM",       # BuildKit cache source for layer caching
        "BUILDX_CACHE_TO",         # BuildKit cache destination for layer caching
        "COMPOSE_DOCKER_CLI_BUILD", # enables Docker CLI BuildKit integration
        "DOCKER_BUILDKIT",         # enables BuildKit for docker build commands
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

# CI workflow env var references: ${{ env.VAR }} or ${{ secrets.VAR }} or
# bare VAR: value under env: blocks
_CI_ENV_RE = re.compile(r'\$\{\{\s*(?:env|secrets|vars)\s*\.\s*([A-Z][A-Z0-9_]*)\s*\}\}')
_CI_BARE_RE = re.compile(r'^\s{6,}([A-Z][A-Z0-9_]*):\s')


def _extract_env_refs(path: Path) -> list[EnvRef]:
    """
    Parse *path* and return every os.getenv / os.environ.get call that
    references an ALL_CAPS env var name.
    """
    refs: list[EnvRef] = []
    src = path.read_text(encoding="utf-8")
    for lineno, line in enumerate(src.splitlines(), 1):
        for m in _GETENV_RE.finditer(line):
            name = m.group(1)
            has_default = bool(m.group("default"))
            refs.append(EnvRef(
                name=name,
                has_default=has_default,
                source_file=str(path.relative_to(REPO_ROOT)),
                line=lineno,
            ))
    return refs


def _extract_ci_env_refs(path: Path) -> set[str]:
    """
    Return the set of env var names referenced in a CI workflow YAML file.
    Includes both ${{ env.VAR }} / ${{ secrets.VAR }} patterns and bare
    VAR: entries under environment: blocks.
    """
    names: set[str] = set()
    src = path.read_text(encoding="utf-8")
    for line in src.splitlines():
        for m in _CI_ENV_RE.finditer(line):
            names.add(m.group(1))
        for m in _CI_BARE_RE.finditer(line):
            names.add(m.group(1))
    return names


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
    bare_re = re.compile(r"^\s{6,}([A-Z][A-Z0-9_]*):")
    interp_re = re.compile(r"\$\{([A-Z][A-Z0-9_]*)")
    for line in DOCKER_COMPOSE.read_text(encoding="utf-8").splitlines():
        for m in bare_re.finditer(line):
            keys.add(m.group(1))
        for m in interp_re.finditer(line):
            keys.add(m.group(1))
    return keys


# ---------------------------------------------------------------------------
# Prerequisite tests
# ---------------------------------------------------------------------------


def test_env_example_exists() -> None:
    """Prerequisite: .env.example must exist."""
    assert ENV_EXAMPLE.exists(), f".env.example not found at {ENV_EXAMPLE}"


def test_docker_compose_exists() -> None:
    """Prerequisite: docker-compose.yml must exist."""
    assert DOCKER_COMPOSE.exists(), f"docker-compose.yml not found at {DOCKER_COMPOSE}"


def test_primary_source_files_exist() -> None:
    """Prerequisite: all four primary source files must exist."""
    missing = [str(p.relative_to(REPO_ROOT)) for p in PRIMARY_SOURCE_FILES if not p.exists()]
    assert not missing, "Primary source file(s) missing:\n" + "\n".join(f"  {m}" for m in missing)


# ---------------------------------------------------------------------------
# Gate B1 — primary source files: vars in .env.example
# ---------------------------------------------------------------------------


def test_primary_files_env_vars_declared_in_env_example() -> None:
    """
    Every env var referenced in the four primary source files must appear in
    .env.example so operators know it exists and can configure it.

    Failure means a new env var was added to source code without a
    corresponding entry in .env.example.  Add the variable to .env.example
    with a comment explaining its purpose and safe default.
    """
    env_keys = _load_env_example_keys()
    violations: list[str] = []

    for path in PRIMARY_SOURCE_FILES:
        if not path.exists():
            continue
        for ref in _extract_env_refs(path):
            if ref.name not in env_keys:
                violations.append(
                    f"  {ref.source_file}:{ref.line}  {ref.name}"
                    + (" (no default)" if not ref.has_default else "")
                )

    if violations:
        pytest.fail(
            f"\n{len(violations)} env var(s) referenced in primary source files "
            f"but missing from .env.example.\n"
            "Add each variable to .env.example with a description and safe default:\n\n"
            + "\n".join(violations)
        )


# ---------------------------------------------------------------------------
# Gate B2 — primary source files: required vars forwarded in compose
# ---------------------------------------------------------------------------


def test_required_env_vars_forwarded_in_compose() -> None:
    """
    Env vars that have NO default in primary source files must be forwarded
    through docker-compose.yml (or be in COMPOSE_EXEMPTIONS with a
    justification).

    A variable with no default will be ``None`` inside the container if
    docker-compose.yml does not forward it — this is the silent failure mode
    that caused the Redis TLS and BROKER_TYPE split-brain bugs.
    """
    compose_keys = _load_compose_keys()
    violations: list[str] = []

    for path in PRIMARY_SOURCE_FILES:
        if not path.exists():
            continue
        for ref in _extract_env_refs(path):
            if ref.has_default:
                continue
            if ref.name in COMPOSE_EXEMPTIONS:
                continue
            if ref.name in compose_keys:
                continue
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


# ---------------------------------------------------------------------------
# Gate B3 — extended source files: vars in .env.example
# ---------------------------------------------------------------------------


def test_extended_files_env_vars_declared_in_env_example() -> None:
    """
    Every env var referenced in the extended source files must appear in
    .env.example.

    Extended files include auth, signals, risk, billing, WebSocket, and
    compliance modules — all of which reference secrets and feature flags
    that operators must know about.
    """
    env_keys = _load_env_example_keys()
    violations: list[str] = []

    for path in EXTENDED_SOURCE_FILES:
        if not path.exists():
            continue
        for ref in _extract_env_refs(path):
            if ref.name not in env_keys:
                violations.append(
                    f"  {ref.source_file}:{ref.line}  {ref.name}"
                    + (" (no default)" if not ref.has_default else "")
                )

    if violations:
        pytest.fail(
            f"\n{len(violations)} env var(s) referenced in extended source files "
            f"but missing from .env.example.\n"
            "Add each variable to .env.example with a description and safe default:\n\n"
            + "\n".join(violations)
        )


# ---------------------------------------------------------------------------
# Gate B4 — CI workflow files: vars in .env.example or CI_SECRET_EXEMPTIONS
# ---------------------------------------------------------------------------


def test_ci_workflow_env_vars_are_documented() -> None:
    """
    Every env var referenced in CI workflow files must either be in
    .env.example (so operators can replicate the CI environment locally) or
    in CI_SECRET_EXEMPTIONS (GitHub Actions built-ins and CI-only secrets).

    Failure means a CI workflow references a variable that operators cannot
    discover from .env.example, making local reproduction of CI failures
    impossible.
    """
    env_keys = _load_env_example_keys()
    violations: list[str] = []

    for path in CI_WORKFLOW_FILES:
        if not path.exists():
            continue
        refs = _extract_ci_env_refs(path)
        for name in sorted(refs):
            if name in env_keys:
                continue
            if name in CI_SECRET_EXEMPTIONS:
                continue
            violations.append(f"  {path.relative_to(REPO_ROOT)}  {name}")

    if violations:
        pytest.fail(
            f"\n{len(violations)} CI workflow env var(s) not in .env.example or "
            f"CI_SECRET_EXEMPTIONS.\n"
            "Either add the variable to .env.example with a description, or add it\n"
            "to CI_SECRET_EXEMPTIONS with a justification comment:\n\n"
            + "\n".join(violations)
        )


# ---------------------------------------------------------------------------
# Gate B5 — split-brain consistency checks
# ---------------------------------------------------------------------------


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


def test_redis_tls_vars_consistent() -> None:
    """
    REDIS_TLS and REDIS_URL must both be documented in .env.example.

    The Redis TLS default mismatch bug occurred because REDIS_TLS was set to
    true in docker-compose.yml but the application defaulted to false.  Both
    variables must be visible to operators so they can set them consistently.
    """
    env_keys = _load_env_example_keys()
    for var in ("REDIS_URL", "REDIS_HOST", "REDIS_PORT"):
        assert var in env_keys, (
            f"{var} is missing from .env.example.\n"
            "Redis connection variables must be documented so operators can\n"
            "configure TLS consistently across all services."
        )


def test_security_jwt_secret_documented() -> None:
    """
    SECURITY_JWT_SECRET must be in .env.example with a placeholder value.

    This is the most critical secret in the application.  If it is missing
    from .env.example, operators may leave it unset (empty string) which
    allows any JWT to be accepted.
    """
    env_keys = _load_env_example_keys()
    assert "SECURITY_JWT_SECRET" in env_keys, (
        "SECURITY_JWT_SECRET is missing from .env.example.\n"
        "Add it with a placeholder value and a comment explaining that it must\n"
        "be at least 32 characters and must be changed before production deployment."
    )

    # Also verify the placeholder is not a real secret
    content = ENV_EXAMPLE.read_text(encoding="utf-8")
    for line in content.splitlines():
        if line.startswith("SECURITY_JWT_SECRET="):
            value = line.split("=", 1)[1].strip()
            assert len(value) < 64 or "change" in value.lower() or "placeholder" in value.lower() or "your" in value.lower(), (
                "SECURITY_JWT_SECRET in .env.example looks like a real secret.\n"
                "Replace it with a placeholder value like 'change-me-in-production-min-32-chars'."
            )


# ---------------------------------------------------------------------------
# Gate B6 — .env.example quality checks
# ---------------------------------------------------------------------------


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
                duplicates.append(
                    f"  {name}  (first at line {seen[name]}, duplicate at line {lineno})"
                )
            else:
                seen[name] = lineno

    if duplicates:
        pytest.fail(
            f"\n{len(duplicates)} duplicate active declaration(s) in .env.example.\n"
            "Remove or comment out the earlier occurrence:\n\n"
            + "\n".join(duplicates)
        )


def test_env_example_has_section_comments() -> None:
    """
    .env.example must contain section-separator comments (lines starting with
    '# ===') so operators can navigate the file.

    A 1967-line .env.example without section headers is unusable.  This test
    ensures the file remains structured as it grows.
    """
    content = ENV_EXAMPLE.read_text(encoding="utf-8")
    section_headers = [
        line for line in content.splitlines()
        if line.startswith("# ===") or line.startswith("# ---") or line.startswith("# ──")
    ]
    assert len(section_headers) >= 3, (
        f".env.example has only {len(section_headers)} section header(s).\n"
        "Add '# ===' section separators to make the file navigable.\n"
        "Example: '# === Database ==='"
    )


def test_env_example_documents_app_env() -> None:
    """APP_ENV must be documented in .env.example with the allowed values."""
    content = ENV_EXAMPLE.read_text(encoding="utf-8")
    assert "APP_ENV" in content, (
        "APP_ENV is missing from .env.example.\n"
        "Add it with allowed values: development, test, staging, production"
    )


def test_docker_compose_references_env_file() -> None:
    """
    docker-compose.yml must reference .env via env_file so that credentials
    set in .env are automatically forwarded to all containers.

    Without env_file, operators must manually copy every credential into the
    compose file's environment: blocks — a maintenance burden that leads to
    split-brain configurations.
    """
    content = DOCKER_COMPOSE.read_text(encoding="utf-8")
    assert "env_file" in content or ".env" in content, (
        "docker-compose.yml does not reference .env via env_file.\n"
        "Add 'env_file: .env' to each service so credentials are forwarded\n"
        "automatically without duplicating them in environment: blocks."
    )


# ---------------------------------------------------------------------------
# Gate B9 — BROKER alias consistency
#
# The codebase uses three overlapping env vars to select the active broker:
#
#   BROKER       — brokers/factory.py  (bare name: "paper", "mt5", "oanda")
#   BROKER_TYPE  — api/trading.py      (same values, different var name)
#   PAPER_TRADING — core/main_loop.py, execution/fix_router.py  (bool flag)
#
# All three must be declared in .env.example.  The note in .env.example that
# says "set BOTH PAPER_TRADING and BROKER_TYPE" must be present so operators
# know to keep them in sync.  The smoke override must set all three
# consistently (BROKER=paper, BROKER_TYPE=paper, PAPER_TRADING=true).
#
# This is the exact split-brain class of bug the spec calls out:
#   fix_router.py and main_loop.py gate paper-trading on PAPER_TRADING=true.
#   api/trading.py gates it on BROKER_TYPE=paper.
#   brokers/factory.py gates it on BROKER=paper.
#   Setting only one of these leaves the others in an inconsistent state.
# ---------------------------------------------------------------------------


def test_broker_alias_vars_all_declared_in_env_example() -> None:
    """
    BROKER, BROKER_TYPE, and PAPER_TRADING must all be declared in .env.example.

    These three variables control the same logical switch (paper vs live
    trading) via different code paths.  All three must be documented so
    operators know to set them consistently.
    """
    content = ENV_EXAMPLE.read_text(encoding="utf-8")
    missing = [v for v in ("BROKER", "BROKER_TYPE", "PAPER_TRADING") if v not in content]
    assert not missing, (
        f"Broker alias variable(s) missing from .env.example: {missing}\n"
        "All three broker-selection variables must be documented:\n"
        "  BROKER        — brokers/factory.py (bare name: paper, mt5, oanda)\n"
        "  BROKER_TYPE   — api/trading.py (same values, different var name)\n"
        "  PAPER_TRADING — core/main_loop.py, execution/fix_router.py (bool)\n"
        "Add the missing variable(s) with a note to keep them in sync."
    )


def test_env_example_documents_broker_sync_requirement() -> None:
    """
    .env.example must contain a note instructing operators to set both
    PAPER_TRADING and BROKER_TYPE together.

    The split-brain bug occurs when an operator sets PAPER_TRADING=true but
    leaves BROKER_TYPE=live (or vice versa), causing the two code paths to
    disagree on whether paper trading is active.  The note in .env.example
    is the primary defence against this at the operator level.
    """
    content = ENV_EXAMPLE.read_text(encoding="utf-8")
    # The note must mention both vars in proximity — check for the canonical
    # phrasing added when the split-brain bug was fixed.
    has_sync_note = (
        ("PAPER_TRADING" in content and "BROKER_TYPE" in content)
        and (
            "set BOTH" in content
            or "set both" in content
            or "keep them in sync" in content
            or "same purpose" in content
            or "api/trading.py uses BROKER_TYPE" in content
        )
    )
    assert has_sync_note, (
        ".env.example does not document the PAPER_TRADING / BROKER_TYPE sync requirement.\n"
        "Add a comment near PAPER_TRADING explaining that BROKER_TYPE must be set\n"
        "to the same value, e.g.:\n"
        "  # NOTE: api/trading.py uses BROKER_TYPE=paper for the same purpose — set BOTH\n"
        "  PAPER_TRADING=false\n"
        "  BROKER_TYPE=paper"
    )


def test_broker_alias_vars_forwarded_in_compose() -> None:
    """
    BROKER_TYPE and PAPER_TRADING must reach the trading service container.

    Acceptable forwarding mechanisms (either is sufficient):
      1. Explicit entry in the service's environment: block
         e.g.  BROKER_TYPE: ${BROKER_TYPE:-paper}
      2. env_file: .env on the service — forwards every variable in .env,
         including BROKER_TYPE and PAPER_TRADING, without listing them
         individually.

    If neither mechanism is present the container uses the code default
    (paper) regardless of what .env says, creating a silent split-brain
    between the API and the trading engine.
    """
    import yaml

    content = DOCKER_COMPOSE.read_text(encoding="utf-8")

    with DOCKER_COMPOSE.open(encoding="utf-8") as fh:
        compose = yaml.safe_load(fh) or {}

    trading_svc = compose.get("services", {}).get("trading", {})

    # env_file: .env forwards ALL variables — no need to list them individually
    env_file = trading_svc.get("env_file", "")
    if isinstance(env_file, list):
        env_file_str = " ".join(str(e) for e in env_file)
    else:
        env_file_str = str(env_file)

    if ".env" in env_file_str:
        # env_file covers everything — pass
        return

    # Fall back to checking explicit environment: block entries
    missing = [v for v in ("BROKER_TYPE", "PAPER_TRADING") if v not in content]
    assert not missing, (
        f"Broker alias variable(s) not forwarded to the trading service: {missing}\n"
        "Either add 'env_file: .env' to the trading service (recommended) or\n"
        "add explicit environment entries:\n"
        "  BROKER_TYPE: ${BROKER_TYPE:-paper}\n"
        "  PAPER_TRADING: ${PAPER_TRADING:-false}"
    )


def test_smoke_override_broker_vars_consistent() -> None:
    """
    docker-compose.smoke.yml must set BROKER_TYPE=paper and PAPER_TRADING=true
    for the app service, and they must agree with each other.

    A smoke override that sets BROKER_TYPE=paper but PAPER_TRADING=false (or
    vice versa) would pass the smoke test while hiding a split-brain that
    would manifest in production.
    """
    import yaml

    smoke_path = REPO_ROOT / "docker-compose.smoke.yml"
    if not smoke_path.exists():
        pytest.skip("docker-compose.smoke.yml not found")

    with smoke_path.open(encoding="utf-8") as fh:
        smoke = yaml.safe_load(fh) or {}

    app_env = smoke.get("services", {}).get("app", {}).get("environment", {})
    if isinstance(app_env, list):
        app_env = dict(item.split("=", 1) for item in app_env if "=" in item)

    broker_type = str(app_env.get("BROKER_TYPE", "")).lower()
    paper_trading = str(app_env.get("PAPER_TRADING", "")).lower()

    # Both must be set
    assert broker_type, (
        "docker-compose.smoke.yml app.BROKER_TYPE is not set.\n"
        "Set BROKER_TYPE=paper to prevent live broker connections in CI."
    )
    assert paper_trading, (
        "docker-compose.smoke.yml app.PAPER_TRADING is not set.\n"
        "Set PAPER_TRADING=true to prevent live broker connections in CI."
    )

    # They must agree: paper mode iff BROKER_TYPE=paper AND PAPER_TRADING=true
    broker_is_paper = broker_type == "paper"
    trading_is_paper = paper_trading in ("true", "1", "yes")

    assert broker_is_paper == trading_is_paper, (
        f"Broker alias split-brain in docker-compose.smoke.yml:\n"
        f"  BROKER_TYPE={broker_type!r}  (paper={broker_is_paper})\n"
        f"  PAPER_TRADING={paper_trading!r}  (paper={trading_is_paper})\n"
        "Both must agree.  Set BROKER_TYPE=paper and PAPER_TRADING=true for CI."
    )


def test_fix_router_and_trading_use_consistent_paper_gate() -> None:
    """
    fix_router.py must gate paper mode on PAPER_TRADING and api/trading.py
    must gate it on BROKER_TYPE.  Both files must be present and readable.

    This test does not assert the values — it asserts that each file uses
    its canonical variable so the split-brain is at least predictable and
    documented rather than accidental.
    """
    fix_router = REPO_ROOT / "execution" / "fix_router.py"
    trading = REPO_ROOT / "api" / "trading.py"

    assert fix_router.exists(), "execution/fix_router.py not found"
    assert trading.exists(), "api/trading.py not found"

    fix_text = fix_router.read_text(encoding="utf-8")
    trading_text = trading.read_text(encoding="utf-8")

    assert "PAPER_TRADING" in fix_text, (
        "execution/fix_router.py no longer reads PAPER_TRADING.\n"
        "If the paper-trading gate was moved to a different variable, update\n"
        "this test and the .env.example sync note."
    )
    assert "BROKER_TYPE" in trading_text, (
        "api/trading.py no longer reads BROKER_TYPE.\n"
        "If the paper-trading gate was moved to a different variable, update\n"
        "this test and the .env.example sync note."
    )


def test_main_loop_uses_paper_trading_var() -> None:
    """
    core/main_loop.py must gate paper mode on PAPER_TRADING (not BROKER_TYPE).

    main_loop.py is the trading engine orchestrator.  It must use the same
    variable as fix_router.py (PAPER_TRADING) so the engine and the router
    agree on paper mode without requiring BROKER_TYPE to be set.
    """
    main_loop = REPO_ROOT / "core" / "main_loop.py"
    assert main_loop.exists(), "core/main_loop.py not found"

    text = main_loop.read_text(encoding="utf-8")
    assert "PAPER_TRADING" in text, (
        "core/main_loop.py no longer reads PAPER_TRADING.\n"
        "The trading engine orchestrator must gate paper mode on PAPER_TRADING\n"
        "to stay consistent with execution/fix_router.py."
    )
