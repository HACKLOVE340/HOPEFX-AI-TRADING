"""
config/startup_validator.py
Startup environment validation — fail loud on missing or weak secrets.

Called once at process start before any broker/DB connections are opened.
Any validation failure raises SystemExit(1) so the container/pod restarts
rather than running with a broken configuration.
"""

from __future__ import annotations

import logging
import os
import sys
from dataclasses import dataclass, field
from typing import Callable, List, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Required variable definitions
# ---------------------------------------------------------------------------

@dataclass
class EnvVar:
    """Specification for a required environment variable."""
    name: str
    description: str
    min_length: int = 1
    validator: Optional[Callable[[str], bool]] = None
    validator_msg: str = ""
    secret: bool = False  # if True, value is redacted in logs


_REQUIRED: List[EnvVar] = [
    EnvVar(
        name="SECRET_KEY",
        description="Application master secret (JWT signing, CSRF)",
        min_length=32,
        validator=lambda v: len(v) >= 32,
        validator_msg="must be ≥32 characters — generate with: python -c \"import secrets; print(secrets.token_hex(32))\"",
        secret=True,
    ),
    EnvVar(
        name="DB_PASSWORD",
        description="PostgreSQL database password",
        min_length=12,
        validator=lambda v: len(v) >= 12,
        validator_msg="must be ≥12 characters",
        secret=True,
    ),
    EnvVar(
        name="DB_HOST",
        description="PostgreSQL host",
        min_length=1,
    ),
    EnvVar(
        name="REDIS_URL",
        description="Redis connection URL (redis://host:port/db)",
        min_length=8,
        validator=lambda v: v.startswith(("redis://", "rediss://")),
        validator_msg="must start with redis:// or rediss://",
    ),
]

# Optional but validated if present
_OPTIONAL_VALIDATED: List[EnvVar] = [
    EnvVar(
        name="IBKR_HOST",
        description="IBKR TWS/Gateway host",
        min_length=7,
    ),
    EnvVar(
        name="IBKR_PORT",
        description="IBKR TWS/Gateway port (7496=live, 7497=paper, 4001=gateway-live, 4002=gateway-paper)",
        min_length=4,
        validator=lambda v: v.isdigit() and int(v) in (4001, 4002, 7496, 7497),
        validator_msg="must be one of: 4001 (gateway-live), 4002 (gateway-paper), 7496 (tws-live), 7497 (tws-paper)",
    ),
    EnvVar(
        name="SENTRY_DSN",
        description="Sentry DSN for error alerting",
        min_length=20,
        validator=lambda v: v.startswith("https://"),
        validator_msg="must be a valid https:// Sentry DSN",
    ),
    EnvVar(
        name="MOBILE_CORS_ORIGINS",
        description="Comma-separated list of allowed CORS origins for mobile API",
        min_length=1,
        validator=lambda v: all(
            o.strip().startswith(("https://", "http://localhost", "http://127."))
            for o in v.split(",") if o.strip()
        ),
        validator_msg="all origins must start with https:// (or http://localhost for dev)",
    ),
]


# ---------------------------------------------------------------------------
# Validator
# ---------------------------------------------------------------------------

class StartupValidationError(RuntimeError):
    """Raised when one or more required env vars are missing or invalid."""


def validate_environment(*, strict: bool = True) -> None:
    """
    Validate all required environment variables.

    Args:
        strict: If True (default), call sys.exit(1) on failure.
                If False, raise StartupValidationError instead (useful in tests).

    Raises:
        StartupValidationError: when strict=False and validation fails.
    """
    errors: List[str] = []

    # --- Required vars ---
    for spec in _REQUIRED:
        value = os.environ.get(spec.name, "").strip()
        display = "[REDACTED]" if spec.secret else repr(value[:40])

        if not value:
            errors.append(
                f"MISSING  {spec.name}: {spec.description}"
            )
            continue

        if len(value) < spec.min_length:
            errors.append(
                f"TOO_SHORT {spec.name} (got {len(value)} chars, need ≥{spec.min_length}): "
                f"{spec.description}"
            )
            continue

        if spec.validator and not spec.validator(value):
            errors.append(
                f"INVALID  {spec.name}={display}: {spec.validator_msg}"
            )

    # --- Optional vars — only validate if set ---
    for spec in _OPTIONAL_VALIDATED:
        value = os.environ.get(spec.name, "").strip()
        if not value:
            continue  # optional — skip

        display = "[REDACTED]" if spec.secret else repr(value[:40])

        if spec.validator and not spec.validator(value):
            errors.append(
                f"INVALID  {spec.name}={display}: {spec.validator_msg}"
            )

    if errors:
        msg = (
            "\n\n"
            "╔══════════════════════════════════════════════════════════════╗\n"
            "║  STARTUP VALIDATION FAILED — refusing to start              ║\n"
            "╚══════════════════════════════════════════════════════════════╝\n\n"
            + "\n".join(f"  ✗ {e}" for e in errors)
            + "\n\nFix the above environment variables and restart.\n"
        )
        logger.critical(msg)
        if strict:
            sys.exit(1)
        raise StartupValidationError(msg)

    logger.info(
        "Startup validation passed (%d required vars, %d optional vars checked).",
        len(_REQUIRED),
        sum(1 for s in _OPTIONAL_VALIDATED if os.environ.get(s.name)),
    )


def validate_environment_or_raise() -> None:
    """Non-strict variant — raises instead of sys.exit (for test harnesses)."""
    validate_environment(strict=False)
