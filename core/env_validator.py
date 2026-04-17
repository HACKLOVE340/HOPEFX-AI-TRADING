# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
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

logger = logging.getLogger(__name__)


@dataclass
class EnvVar:
    name: str
    required: bool = True
    min_length: int = 0
    description: str = ""
    default: str | None = None  # only used for optional vars in the report


# ── Variable definitions ──────────────────────────────────────────────────────

REQUIRED_VARS: list[EnvVar] = [
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

RECOMMENDED_VARS: list[EnvVar] = [
    EnvVar(
        "DATABASE_URL",
        required=False,
        description="SQLAlchemy DB URL (default: sqlite:///hopefx.db)",
        default="sqlite:///hopefx.db",
    ),
    EnvVar(
        "REDIS_HOST",
        required=False,
        description="Redis host (default: localhost)",
        default="localhost",
    ),
    EnvVar(
        "REDIS_PORT",
        required=False,
        description="Redis port (default: 6379)",
        default="6379",
    ),
    EnvVar(
        "RISK_MAX_POSITION_SIZE_PCT",
        required=False,
        description="Max position size % (default: 0.02)",
        default="0.02",
    ),
    EnvVar(
        "RISK_MAX_DRAWDOWN_PCT",
        required=False,
        description="Max drawdown % (default: 0.10)",
        default="0.10",
    ),
    EnvVar(
        "RISK_MAX_DAILY_LOSS_PCT",
        required=False,
        description="Max daily loss % (default: 0.05)",
        default="0.05",
    ),
    EnvVar(
        "ACCESS_TOKEN_EXPIRE_MINUTES",
        required=False,
        description="JWT access token TTL (default: 15)",
        default="15",
    ),
    EnvVar(
        "REFRESH_TOKEN_EXPIRE_DAYS",
        required=False,
        description="JWT refresh token TTL (default: 7)",
        default="7",
    ),
    EnvVar(
        "SIGNAL_ENGINE_AUTO_TRADE",
        required=False,
        description="Auto-execute signals (default: false)",
        default="false",
    ),
    EnvVar("SMTP_HOST", required=False, description="SMTP host for email delivery"),
    EnvVar("SMTP_PORT", required=False, description="SMTP port", default="587"),
    EnvVar("SMTP_USER", required=False, description="SMTP username"),
    EnvVar("SMTP_PASSWORD", required=False, description="SMTP password"),
    EnvVar(
        "FROM_EMAIL",
        required=False,
        description="Sender address for system emails",
    ),
    # ── Connector hub — live trading pipeline ─────────────────────────────────
    EnvVar(
        "OANDA_API_KEY",
        required=False,
        description="OANDA v20 API key — required for live/paper trading",
    ),
    EnvVar(
        "OANDA_ACCOUNT_ID",
        required=False,
        description="OANDA account ID — required for live/paper trading",
    ),
    EnvVar(
        "OANDA_PRACTICE",
        required=False,
        description="'true' = paper (practice) account, 'false' = live money",
        default="true",
    ),
    EnvVar(
        "REDIS_URL",
        required=False,
        description="Full Redis URL used by EventBus (default: redis://localhost:6379/0)",
        default="redis://localhost:6379/0",
    ),
    EnvVar(
        "TELEGRAM_BOT_TOKEN",
        required=False,
        description="Telegram bot token for daily P&L alerts and DD breach notifications",
    ),
    EnvVar(
        "TELEGRAM_CHAT_ID",
        required=False,
        description="Telegram chat/channel ID to receive alerts",
    ),
    EnvVar(
        "INITIAL_BALANCE",
        required=False,
        description="Starting account balance for drawdown calculations (default: 100000)",
        default="100000",
    ),
    EnvVar(
        "ML_MIN_TRADE_PROB",
        required=False,
        description="Minimum ML confidence to generate a signal (default: 0.58)",
        default="0.58",
    ),
    EnvVar(
        "FIX_CONFIG_FILE",
        required=False,
        description="Path to FIX 4.4 session config (copy fix.cfg → fix.cfg.local and fill in)",
        default="fix.cfg",
    ),
    EnvVar(
        "FIX_SENDER_COMP_ID",
        required=False,
        description="FIX SenderCompID assigned by your broker",
    ),
    EnvVar(
        "FIX_TARGET_COMP_ID",
        required=False,
        description="FIX TargetCompID (broker identifier)",
    ),
    EnvVar(
        "NEWS_BLACKOUT_BEFORE_MIN",
        required=False,
        description="Minutes before a high-impact news event to pause trading (default: 5)",
        default="5",
    ),
    EnvVar(
        "NEWS_BLACKOUT_AFTER_MIN",
        required=False,
        description="Minutes after a high-impact news event to resume trading (default: 5)",
        default="5",
    ),
    EnvVar(
        "HOPEFX_KILL_SWITCH_TOKEN",
        required=False,
        description="HMAC token to deactivate a trading halt via the API",
    ),
]


# ── Known dev-only placeholder values — always rejected in production ─────────
_DEV_PLACEHOLDERS: dict[str, str] = {
    "SECURITY_JWT_SECRET": "dev-jwt-secret-minimum-32-characters-long!!",  # pragma: allowlist secret
    "CONFIG_ENCRYPTION_KEY": "dev-key-minimum-32-characters-long-for-testing",
    "HOPEFX_KILL_SWITCH_TOKEN": "CHANGE_ME_generate_64_char_hex_token",  # noqa: healer
    "POSTGRES_PASSWORD": "CHANGE_ME_db_password",  # pragma: allowlist secret  # noqa: healer
    "REDIS_PASSWORD": "CHANGE_ME_redis_password",  # pragma: allowlist secret  # noqa: healer
}


@dataclass
class ValidationResult:
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return len(self.errors) == 0


def validate_environment(strict: bool = False) -> ValidationResult:
    """
    Validate environment variables.

    Args:
        strict: If True, treat missing recommended vars as errors.
                Always True in production (APP_ENV=production).

    Returns:
        ValidationResult with errors and warnings lists.
    """
    result = ValidationResult()
    app_env = os.getenv("APP_ENV", "development").lower()
    is_production = app_env == "production"

    for var in REQUIRED_VARS:
        val = os.getenv(var.name)  # pylint: disable=invalid-envvar-value
        if not val:
            result.errors.append(
                f"Missing required env var: {var.name} — {var.description}",
            )
        elif var.min_length and len(val) < var.min_length:
            result.errors.append(
                f"{var.name} is too short ({len(val)} chars, need ≥{var.min_length}) — {var.description}",
            )
        elif is_production and var.name in _DEV_PLACEHOLDERS and val == _DEV_PLACEHOLDERS[var.name]:
            result.errors.append(
                f"{var.name} is set to the dev placeholder value in production. "
                f"Generate a real secret before deploying."
            )

    # Check all known placeholders even if not in REQUIRED_VARS
    if is_production:
        for name, placeholder in _DEV_PLACEHOLDERS.items():
            if name in {v.name for v in REQUIRED_VARS}:
                continue  # already checked above
            val = os.getenv(name)
            if val and val == placeholder:
                result.errors.append(
                    f"{name} is set to the dev placeholder value in production. Generate a real value before deploying."
                )

    for var in RECOMMENDED_VARS:
        val = os.getenv(var.name)  # pylint: disable=invalid-envvar-value
        if not val:
            msg = f"Env var not set: {var.name} — {var.description}"
            if var.default:
                msg += f" (using default: {var.default})"
            if strict:
                result.errors.append(msg)
            else:
                result.warnings.append(msg)

    return result


def validate_and_report(
    strict: bool = False,
    exit_on_error: bool = True,
) -> ValidationResult:
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
