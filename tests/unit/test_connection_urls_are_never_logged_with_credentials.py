"""
tests/unit/test_connection_urls_are_never_logged_with_credentials.py
====================================================================
A hosting-panel log scan flagged a Redis authentication value sitting in the
application's container logs.

``REDIS_URL`` in this deployment carries a password in its userinfo, and six
call sites logged it whole, at INFO or DEBUG, on every boot::

    api/platform.py          logger.info("Rate limiter: Redis backend at %s", redis_url)
    rate_limiting/advanced.py  logger.info("... connected at %s", REDIS_URL)
    data_layer/orchestrator.py logger.info("... Redis connected (%s)", _REDIS_URL)
    core/startup_factories.py  logger.info("PositionManager: Redis client wired (%s)", redis_url)
    whitelabel/api_auth.py     logger.info("... Redis backend at %s", _REDIS_URL)
    brokers/ohlcv_store.py     logger.debug("OHLCVStore: Redis connected at %s", _REDIS_URL)

Six independent sites made the same mistake because the codebase had no
redaction helper at all — so each author wrote the obvious thing. `utils/redaction.py`
is that helper, and this file is the guard that stops a seventh appearing.

The AST scan below is the point of the file. Asserting that today's six sites are
fixed would pass forever while a new site leaked; this walks every module and
fails on any logging call that passes a connection URL through un-redacted.
"""

from __future__ import annotations

import ast
import pathlib

import pytest

from utils.redaction import redact_url

ROOT = pathlib.Path(__file__).resolve().parents[2]

_LOG_METHODS = {"debug", "info", "warning", "warn", "error", "critical", "exception", "log"}

#: Names that hold a URL which may carry credentials. Matched case-insensitively
#: against the identifier, so `REDIS_URL`, `_REDIS_URL`, `redis_url`, `db_url`
#: and `dsn` all count.
_URL_NAME_HINTS = ("redis_url", "database_url", "postgres_url", "db_url", "broker_url", "dsn", "celery_url")

_SKIP_DIRS = {
    ".git",
    ".venv",
    "venv",
    "node_modules",
    "__pycache__",
    "tests",
    "dashboard",
    "frontend",
    "build",
    "dist",
    ".mypy_cache",
    ".ruff_cache",
}


# ── The helper does what it claims ────────────────────────────────────────────


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("redis://:s3cret@redis:6379/0", "redis://:***@redis:6379/0"),  # pragma: allowlist secret
        ("rediss://:s3cret@redis:6380/1", "rediss://:***@redis:6380/1"),  # pragma: allowlist secret
        ("redis://user:s3cret@redis:6379/0", "redis://user:***@redis:6379/0"),  # pragma: allowlist secret
        (
            "postgresql+asyncpg://hopefx:pw@db:5432/hopefx",  # pragma: allowlist secret
            "postgresql+asyncpg://hopefx:***@db:5432/hopefx",  # pragma: allowlist secret
        ),
        # Nothing to hide — left exactly as it was, so the log stays useful.
        ("redis://redis:6379/0", "redis://redis:6379/0"),
        ("redis://localhost:6379", "redis://localhost:6379"),
    ],
)
def test_redact_url(raw, expected):
    assert redact_url(raw) == expected


def test_the_password_never_survives_redaction():
    for raw in [
        "redis://:hunter2@redis:6379/0",  # pragma: allowlist secret
        "redis://admin:hunter2@redis:6379/0",  # pragma: allowlist secret
        "rediss://:hunter2@r:6380",  # pragma: allowlist secret
        "postgresql://u:hunter2@db/x",  # pragma: allowlist secret
    ]:
        assert "hunter2" not in redact_url(raw), raw


def test_empty_and_malformed_input_is_safe():
    assert redact_url("") == ""
    assert redact_url(None) == ""
    # A userinfo-bearing string that is not a real URL must not come back raw.
    assert "hunter2" not in redact_url("not a url at all @ hunter2")


def test_a_host_only_url_is_not_mangled():
    """Over-redacting would make the logs useless and invite someone to revert."""
    assert redact_url("redis://redis:6379/0") == "redis://redis:6379/0"


# ── No module logs a connection URL without redacting it ──────────────────────


def _python_files() -> list[pathlib.Path]:
    files = []
    for path in ROOT.rglob("*.py"):
        if any(part in _SKIP_DIRS for part in path.relative_to(ROOT).parts):
            continue
        files.append(path)
    return files


def _looks_like_a_url_name(node: ast.AST) -> str | None:
    """Identifier of a URL-ish variable, or None."""
    if isinstance(node, ast.Name):
        name = node.id
    elif isinstance(node, ast.Attribute):
        name = node.attr
    else:
        return None
    lowered = name.lower().lstrip("_")
    return name if any(hint in lowered for hint in _URL_NAME_HINTS) else None


def _leaky_log_calls(path: pathlib.Path) -> list[str]:
    """Logging calls that pass a credential-bearing URL through un-redacted."""
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (SyntaxError, UnicodeDecodeError):  # pragma: no cover
        return []

    try:
        where = str(path.relative_to(ROOT))
    except ValueError:
        where = str(path)  # a tmp_path fixture in the control test below

    findings: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            continue
        if node.func.attr not in _LOG_METHODS:
            continue
        # `logger.info(...)` / `self.logger.info(...)` / `log.info(...)`
        receiver = node.func.value
        receiver_name = getattr(receiver, "id", getattr(receiver, "attr", ""))
        if "log" not in str(receiver_name).lower():
            continue

        for arg in node.args:
            # Already wrapped: redact_url(REDIS_URL) — the whole point.
            if isinstance(arg, ast.Call):
                func_name = getattr(arg.func, "id", getattr(arg.func, "attr", ""))
                if func_name == "redact_url":
                    continue
            name = _looks_like_a_url_name(arg)
            if name:
                findings.append(f"{where}:{node.lineno} logs {name}")
    return findings


def test_no_module_logs_a_connection_url_in_the_clear():
    leaks = [finding for path in _python_files() for finding in _leaky_log_calls(path)]
    assert leaks == [], (
        "These logging calls pass a connection URL straight through. In this "
        "deployment REDIS_URL carries the password, so each one writes a "
        "credential to stdout on every boot. Wrap the value in "
        "utils.redaction.redact_url():\n  " + "\n  ".join(leaks)
    )


def test_the_scan_would_actually_catch_a_leak(tmp_path):
    """Control: without this, the test above passes on a scanner that finds nothing."""
    leaky = tmp_path / "leaky.py"
    leaky.write_text(
        "import logging\n"
        "logger = logging.getLogger(__name__)\n"
        "REDIS_URL = 'redis://:pw@r:6379/0'\n"  # pragma: allowlist secret
        "logger.info('Redis at %s', REDIS_URL)\n",
        encoding="utf-8",
    )
    assert _leaky_log_calls(leaky), "the scanner does not detect the exact defect it exists for"

    clean = tmp_path / "clean.py"
    clean.write_text(
        "import logging\n"
        "from utils.redaction import redact_url\n"
        "logger = logging.getLogger(__name__)\n"
        "REDIS_URL = 'redis://:pw@r:6379/0'\n"  # pragma: allowlist secret
        "logger.info('Redis at %s', redact_url(REDIS_URL))\n",
        encoding="utf-8",
    )
    assert not _leaky_log_calls(clean), "the scanner flags a correctly redacted call"


def test_the_scan_covers_the_six_modules_that_leaked():
    """Guard the guard: a skip-list typo would silently stop scanning them."""
    scanned = {str(p.relative_to(ROOT)) for p in _python_files()}
    for module in [
        "api/platform.py",
        "rate_limiting/advanced.py",
        "data_layer/orchestrator.py",
        "core/startup_factories.py",
        "whitelabel/api_auth.py",
        "brokers/ohlcv_store.py",
    ]:
        assert module in scanned, f"{module} is no longer being scanned"
