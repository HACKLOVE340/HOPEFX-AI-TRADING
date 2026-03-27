# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026 Opeyemi (HACKLOVE340)
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
config/startup_validator.py
Startup environment validation — fail loud on missing or weak secrets.

Called once at process start before any broker/DB/Redis connections open.
Any validation failure raises SystemExit(1) so the container/pod restarts
rather than running with a broken configuration.

Dev-mode bypass
---------------
Set APP_ENV=development (the default) to skip the DB_HOST / DB_PASSWORD /
REDIS_URL checks so the app starts with SQLite + no Redis out of the box.
All checks are enforced when APP_ENV=production.

Env-var name alignment (canonical names used throughout the codebase):
  SECURITY_JWT_SECRET  — JWT signing key  (also accepted: JWT_SECRET_KEY)
  DATABASE_URL         — full DB URL      (SQLite OK in dev)
  REDIS_URL            — full Redis URL   (optional in dev)
  DB_HOST / DB_PASSWORD — only required when DATABASE_URL is not set in prod
"""

from __future__ import annotations

import logging
import os
import sys
from typing import List, Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _is_dev() -> bool:
    return os.getenv("APP_ENV", "development").lower() in ("development", "dev", "test")


def _jwt_secret_value() -> str:
    """Accept either canonical name (SECURITY_JWT_SECRET preferred)."""
    return (
        os.getenv("SECURITY_JWT_SECRET", "").strip()
        or os.getenv("JWT_SECRET_KEY", "").strip()
    )


# ---------------------------------------------------------------------------
# Public exception
# ---------------------------------------------------------------------------

class StartupValidationError(RuntimeError):
    """Raised when one or more required env vars are missing or invalid."""


# ---------------------------------------------------------------------------
# Validator
# ---------------------------------------------------------------------------

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
    dev_mode = _is_dev()

    # ── JWT secret ────────────────────────────────────────────────────────────
    jwt_val = _jwt_secret_value()
    if not jwt_val:
        errors.append(
            "MISSING  SECURITY_JWT_SECRET: JWT signing key — "
            'generate with: python -c "import secrets; print(secrets.token_urlsafe(48))"'
        )
    elif len(jwt_val) < 32:
        errors.append(
            f"TOO_SHORT SECURITY_JWT_SECRET (got {len(jwt_val)} chars, need >=32)"
        )
    elif jwt_val.startswith("CHANGE_ME"):
        errors.append(
            "INSECURE SECURITY_JWT_SECRET: placeholder value detected — "
            "replace with a real random secret before deploying"
        )

    # ── Database ──────────────────────────────────────────────────────────────
    if not dev_mode:
        db_url = os.getenv("DATABASE_URL", "").strip()
        db_host = os.getenv("DB_HOST", "").strip()
        db_pass = os.getenv("DB_PASSWORD", "").strip()

        if not db_url and not db_host:
            errors.append(
                "MISSING  DATABASE_URL or DB_HOST: "
                "set DATABASE_URL=postgresql://user:pass@host:5432/db"
            )
        if not db_url and db_host and not db_pass:
            errors.append(
                "MISSING  DB_PASSWORD: required when DB_HOST is set without DATABASE_URL"
            )
        if db_pass and len(db_pass) < 12:
            errors.append(
                f"TOO_SHORT DB_PASSWORD (got {len(db_pass)} chars, need >=12)"
            )

    # ── Redis ─────────────────────────────────────────────────────────────────
    if not dev_mode:
        redis_url = os.getenv("REDIS_URL", "").strip()
        redis_host = os.getenv("REDIS_HOST", "").strip()

        if not redis_url:
            if redis_host:
                redis_port = os.getenv("REDIS_PORT", "6379")
                errors.append(
                    f"MISSING  REDIS_URL: found REDIS_HOST={redis_host} — "
                    f"set REDIS_URL=redis://{redis_host}:{redis_port}/0"
                )
            else:
                errors.append(
                    "MISSING  REDIS_URL: Redis connection URL — "
                    "set REDIS_URL=redis://localhost:6379/0"
                )
        elif not redis_url.startswith(("redis://", "rediss://")):
            errors.append(
                f"INVALID  REDIS_URL={redis_url!r}: must start with redis:// or rediss://"
            )

    # ── Config encryption key ─────────────────────────────────────────────────
    enc_key = os.getenv("CONFIG_ENCRYPTION_KEY", "").strip()
    if not dev_mode:
        if not enc_key:
            errors.append(
                "MISSING  CONFIG_ENCRYPTION_KEY: required for encrypting stored credentials. "
                'Generate with: python -c "import secrets; print(secrets.token_urlsafe(48))"'
            )
        elif len(enc_key) < 32:
            errors.append(
                f"TOO_SHORT CONFIG_ENCRYPTION_KEY (got {len(enc_key)} chars, need >=32)"
            )
        elif enc_key.startswith("CHANGE_ME"):
            errors.append(
                "INSECURE CONFIG_ENCRYPTION_KEY: placeholder value — replace before deploying"
            )

    # ── Broker type + live trading guard ─────────────────────────────────────
    broker_type = os.getenv("BROKER_TYPE", "paper").strip().lower()
    valid_broker_types = {"paper", "oanda", "ibkr", "ccxt", "fix"}
    if broker_type not in valid_broker_types:
        errors.append(
            f"INVALID  BROKER_TYPE={broker_type!r}: must be one of {sorted(valid_broker_types)}"
        )

    # Prevent accidental live auto-trading: SIGNAL_ENGINE_AUTO_TRADE=true
    # requires BROKER_TYPE != paper in production.
    auto_trade = os.getenv("SIGNAL_ENGINE_AUTO_TRADE", "false").strip().lower()
    if auto_trade == "true" and broker_type == "paper" and not dev_mode:
        errors.append(
            "CONFLICT SIGNAL_ENGINE_AUTO_TRADE=true with BROKER_TYPE=paper in production — "
            "set BROKER_TYPE to a live broker or disable auto-trading"
        )

    # OANDA credentials required when BROKER_TYPE=oanda
    if broker_type == "oanda":
        oanda_key = os.getenv("BROKER_OANDA_TOKEN", os.getenv("OANDA_API_KEY", "")).strip()
        oanda_acct = os.getenv("BROKER_OANDA_ACCOUNT", os.getenv("OANDA_ACCOUNT_ID", "")).strip()
        if not oanda_key:
            errors.append(
                "MISSING  BROKER_OANDA_TOKEN (or OANDA_API_KEY): required when BROKER_TYPE=oanda"
            )
        if not oanda_acct:
            errors.append(
                "MISSING  BROKER_OANDA_ACCOUNT (or OANDA_ACCOUNT_ID): required when BROKER_TYPE=oanda"
            )

    # ── Kill switch deactivation token ───────────────────────────────────────
    # Required in production: without it the kill switch can never be
    # deactivated via the API after a drawdown-triggered halt.
    ks_token = os.getenv("HOPEFX_KILL_SWITCH_TOKEN", "").strip()
    if not dev_mode:
        if not ks_token:
            errors.append(
                "MISSING  HOPEFX_KILL_SWITCH_TOKEN: required to deactivate trading halts "
                'via API. Generate with: python -c "import secrets; print(secrets.token_urlsafe(48))"'
            )
        elif len(ks_token) < 32:
            errors.append(
                f"TOO_SHORT HOPEFX_KILL_SWITCH_TOKEN (got {len(ks_token)} chars, need >=32)"
            )
        elif ks_token.startswith("CHANGE_ME"):
            errors.append(
                "INSECURE HOPEFX_KILL_SWITCH_TOKEN: placeholder value — replace before deploying"
            )

    # ── Optional validated vars ───────────────────────────────────────────────
    sentry_dsn = os.getenv("SENTRY_DSN", "").strip()
    if sentry_dsn and not sentry_dsn.startswith("https://"):
        errors.append(
            f"INVALID  SENTRY_DSN={sentry_dsn[:40]!r}: must be a valid https:// Sentry DSN"
        )

    mobile_cors = os.getenv("MOBILE_CORS_ORIGINS", "").strip()
    if mobile_cors:
        bad = [
            o.strip()
            for o in mobile_cors.split(",")
            if o.strip()
            and not o.strip().startswith(("https://", "http://localhost", "http://127."))
        ]
        if bad:
            errors.append(
                f"INVALID  MOBILE_CORS_ORIGINS: non-https origins: {bad} — "
                "all origins must start with https:// (or http://localhost for dev)"
            )

    ibkr_port = os.getenv("IBKR_PORT", "").strip()
    if ibkr_port:
        if not ibkr_port.isdigit() or int(ibkr_port) not in (4001, 4002, 7496, 7497):
            errors.append(
                f"INVALID  IBKR_PORT={ibkr_port!r}: "
                "must be one of 4001 (gateway-live), 4002 (gateway-paper), "
                "7496 (tws-live), 7497 (tws-paper)"
            )

    # ── CORS wildcard guard ───────────────────────────────────────────────────
    # A wildcard ALLOWED_ORIGINS in production means any origin can call the
    # API — this is a security misconfiguration. Deployers who forget to set
    # this often fall back to "*" as a workaround for CORS errors.
    if not dev_mode:
        allowed_origins = os.getenv("ALLOWED_ORIGINS", "").strip()
        if "*" in [o.strip() for o in allowed_origins.split(",") if o.strip()]:
            errors.append(
                "INSECURE ALLOWED_ORIGINS contains '*' in production — "
                "set ALLOWED_ORIGINS to a comma-separated list of explicit "
                "https:// origins (e.g. https://app.example.com)"
            )

    if errors:
        env_label = "PRODUCTION" if not dev_mode else "DEVELOPMENT"
        msg = (
            "\n\n"
            f"╔══════════════════════════════════════════════════════════════╗\n"
            f"║  STARTUP VALIDATION FAILED [{env_label}]                     ║\n"
            f"╚══════════════════════════════════════════════════════════════╝\n\n"
            + "\n".join(f"  x {e}" for e in errors)
            + "\n\nFix the above environment variables and restart.\n"
        )
        logger.critical(msg)
        if strict:
            sys.exit(1)
        raise StartupValidationError(msg)

    n_optional = sum(
        1
        for v in ("SENTRY_DSN", "MOBILE_CORS_ORIGINS", "IBKR_PORT")
        if os.getenv(v)
    )
    logger.info(
        "Startup validation passed (mode=%s, %d optional vars checked).",
        "production" if not dev_mode else "development",
        n_optional,
    )


def validate_environment_or_raise() -> None:
    """Non-strict variant — raises instead of sys.exit (for test harnesses)."""
    validate_environment(strict=False)
