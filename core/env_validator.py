"""
Startup environment validator.

Checks required and recommended environment variables before the app starts.
Raises RuntimeError on missing critical vars so the process fails fast with
a clear message rather than crashing later with a cryptic error.
"""

from __future__ import annotations

import logging
import os
import sys
from dataclasses import dataclass, field
from typing import List, Optional

logger = logging.getLogger(__name__)


@dataclass
class EnvVar:
    name: str
    required: bool = True
    min_length: int = 0
    description: str = ""
    default: Optional[str] = None  # only used for optional vars in the report


# ── Variable definitions ──────────────────────────────────────────────────────

REQUIRED_VARS: List[EnvVar] = [
    EnvVar(
        "SECURITY_JWT_SECRET",
        required=True,
        min_length=32,
        description="JWT signing secret (≥32 chars)",
    ),
    EnvVar(
        "CONFIG_ENCRYPTION_KEY",
        required=True,
        min_length=32,
        description="Config encryption key (≥32 chars)",
    ),
]

RECOMMENDED_VARS: List[EnvVar] = [
    EnvVar("DATABASE_URL", required=False, description="SQLAlchemy DB URL (default: sqlite:///hopefx.db)", default="sqlite:///hopefx.db"),
    EnvVar("REDIS_HOST", required=False, description="Redis host (default: localhost)", default="localhost"),
    EnvVar("REDIS_PORT", required=False, description="Redis port (default: 6379)", default="6379"),
    EnvVar("RISK_MAX_POSITION_SIZE_PCT", required=False, description="Max position size % (default: 0.02)", default="0.02"),
    EnvVar("RISK_MAX_DRAWDOWN_PCT", required=False, description="Max drawdown % (default: 0.10)", default="0.10"),
    EnvVar("RISK_MAX_DAILY_LOSS_PCT", required=False, description="Max daily loss % (default: 0.05)", default="0.05"),
    EnvVar("ACCESS_TOKEN_EXPIRE_MINUTES", required=False, description="JWT access token TTL (default: 15)", default="15"),
    EnvVar("REFRESH_TOKEN_EXPIRE_DAYS", required=False, description="JWT refresh token TTL (default: 7)", default="7"),
    EnvVar("SIGNAL_ENGINE_AUTO_TRADE", required=False, description="Auto-execute signals (default: false)", default="false"),
    EnvVar("SMTP_HOST", required=False, description="SMTP host for email delivery"),
    EnvVar("SMTP_PORT", required=False, description="SMTP port", default="587"),
    EnvVar("SMTP_USER", required=False, description="SMTP username"),
    EnvVar("SMTP_PASSWORD", required=False, description="SMTP password"),
    EnvVar("FROM_EMAIL", required=False, description="Sender address for system emails"),
]


@dataclass
class ValidationResult:
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return len(self.errors) == 0


def validate_environment(strict: bool = False) -> ValidationResult:
    """
    Validate environment variables.

    Args:
        strict: If True, treat missing recommended vars as errors.

    Returns:
        ValidationResult with errors and warnings lists.
    """
    result = ValidationResult()

    for var in REQUIRED_VARS:
        val = os.getenv(var.name)
        if not val:
            result.errors.append(
                f"Missing required env var: {var.name} — {var.description}"
            )
        elif var.min_length and len(val) < var.min_length:
            result.errors.append(
                f"{var.name} is too short ({len(val)} chars, need ≥{var.min_length}) — {var.description}"
            )

    for var in RECOMMENDED_VARS:
        val = os.getenv(var.name)
        if not val:
            msg = f"Env var not set: {var.name} — {var.description}"
            if var.default:
                msg += f" (using default: {var.default})"
            if strict:
                result.errors.append(msg)
            else:
                result.warnings.append(msg)

    return result


def validate_and_report(strict: bool = False, exit_on_error: bool = True) -> ValidationResult:
    """
    Run validation, log results, and optionally exit on errors.

    Args:
        strict: Treat missing recommended vars as errors.
        exit_on_error: Call sys.exit(1) if there are errors (default True).
    """
    result = validate_environment(strict=strict)

    if result.warnings:
        for w in result.warnings:
            logger.warning("ENV: %s", w)

    if result.errors:
        logger.error("=" * 60)
        logger.error("STARTUP ABORTED — environment configuration errors:")
        for e in result.errors:
            logger.error("  ✗ %s", e)
        logger.error("=" * 60)
        if exit_on_error:
            sys.exit(1)
    else:
        logger.info("ENV: all required variables present")

    return result
