# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
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
from typing import ClassVar

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _is_dev() -> bool:
    return os.getenv("APP_ENV", "development").lower() in ("development", "dev", "test")


def _jwt_secret_value() -> str:
    """Accept either canonical name (SECURITY_JWT_SECRET preferred)."""
    return os.getenv("SECURITY_JWT_SECRET", "").strip() or os.getenv("JWT_SECRET_KEY", "").strip()


def _env(name: str) -> str:
    return os.getenv(name, "").strip()


# ---------------------------------------------------------------------------
# Public exception
# ---------------------------------------------------------------------------


class StartupValidationError(RuntimeError):
    """Raised when one or more required env vars are missing or invalid."""


# ---------------------------------------------------------------------------
# Private section validators — each appends to the errors list
# ---------------------------------------------------------------------------


def _validate_jwt(errors: list[str]) -> None:
    jwt_val = _jwt_secret_value()
    if not jwt_val:
        errors.append(
            "MISSING  SECURITY_JWT_SECRET: JWT signing key — "
            'generate with: python -c "import secrets; logger.info(secrets.token_urlsafe(48))"',
        )
    elif len(jwt_val) < 32:
        errors.append(
            f"TOO_SHORT SECURITY_JWT_SECRET (got {len(jwt_val)} chars, need >=32)",
        )
    elif jwt_val.startswith("CHANGE_ME"):
        errors.append(
            "INSECURE SECURITY_JWT_SECRET: placeholder value detected — "
            "replace with a real random secret before deploying",
        )


def _validate_database(errors: list[str]) -> None:
    db_url = _env("DATABASE_URL")
    db_host = _env("DB_HOST")
    db_pass = _env("DB_PASSWORD")

    if not db_url and not db_host:
        errors.append(
            "MISSING  DATABASE_URL or DB_HOST: set DATABASE_URL=postgresql://user:pass@host:5432/db",
        )
    if not db_url and db_host and not db_pass:
        errors.append(
            "MISSING  DB_PASSWORD: required when DB_HOST is set without DATABASE_URL",
        )
    if db_pass and len(db_pass) < 12:
        errors.append(
            f"TOO_SHORT DB_PASSWORD (got {len(db_pass)} chars, need >=12)",
        )


def _validate_redis(errors: list[str]) -> None:
    redis_url = _env("REDIS_URL")
    redis_host = _env("REDIS_HOST")

    if not redis_url:
        if redis_host:
            redis_port = _env("REDIS_PORT") or "6379"
            errors.append(
                f"MISSING  REDIS_URL: found REDIS_HOST={redis_host} — "
                f"set REDIS_URL=redis://{redis_host}:{redis_port}/0",
            )
        else:
            errors.append(
                "MISSING  REDIS_URL: Redis connection URL — set REDIS_URL=redis://localhost:6379/0",
            )
    elif not redis_url.startswith(("redis://", "rediss://")):
        errors.append(
            f"INVALID  REDIS_URL={redis_url!r}: must start with redis:// or rediss://",
        )


def _validate_encryption_key(errors: list[str]) -> None:
    enc_key = _env("CONFIG_ENCRYPTION_KEY")
    if not enc_key:
        errors.append(
            "MISSING  CONFIG_ENCRYPTION_KEY: required for encrypting stored credentials. "
            'Generate with: python -c "import secrets; logger.info(secrets.token_urlsafe(48))"',
        )
    elif len(enc_key) < 32:
        errors.append(
            f"TOO_SHORT CONFIG_ENCRYPTION_KEY (got {len(enc_key)} chars, need >=32)",
        )
    elif enc_key.startswith("CHANGE_ME"):
        errors.append(
            "INSECURE CONFIG_ENCRYPTION_KEY: placeholder value — replace before deploying",
        )


def _validate_broker(errors: list[str], dev_mode: bool) -> None:
    broker_type = _env("BROKER_TYPE") or "paper"
    broker_type = broker_type.lower()
    valid_broker_types = {"paper", "oanda", "ibkr", "ccxt", "fix"}

    if broker_type not in valid_broker_types:
        errors.append(
            f"INVALID  BROKER_TYPE={broker_type!r}: must be one of {sorted(valid_broker_types)}",
        )

    auto_trade = (_env("SIGNAL_ENGINE_AUTO_TRADE") or "false").lower()
    if auto_trade == "true" and broker_type == "paper" and not dev_mode:
        errors.append(
            "CONFLICT SIGNAL_ENGINE_AUTO_TRADE=true with BROKER_TYPE=paper in production — "
            "set BROKER_TYPE to a live broker or disable auto-trading",
        )

    if broker_type == "oanda":
        _validate_oanda_credentials(errors)


def _validate_oanda_credentials(errors: list[str]) -> None:
    oanda_key = _env("BROKER_OANDA_TOKEN") or _env("OANDA_API_KEY")
    oanda_acct = _env("BROKER_OANDA_ACCOUNT") or _env("OANDA_ACCOUNT_ID")
    if not oanda_key:
        errors.append(
            "MISSING  BROKER_OANDA_TOKEN (or OANDA_API_KEY): required when BROKER_TYPE=oanda",
        )
    if not oanda_acct:
        errors.append(
            "MISSING  BROKER_OANDA_ACCOUNT (or OANDA_ACCOUNT_ID): required when BROKER_TYPE=oanda",
        )


def _validate_kill_switch_token(errors: list[str]) -> None:
    ks_token = _env("HOPEFX_KILL_SWITCH_TOKEN")
    if not ks_token:
        errors.append(
            "MISSING  HOPEFX_KILL_SWITCH_TOKEN: required to deactivate trading halts "
            'via API. Generate with: python -c "import secrets; logger.info(secrets.token_urlsafe(48))"',
        )
    elif len(ks_token) < 32:
        errors.append(
            f"TOO_SHORT HOPEFX_KILL_SWITCH_TOKEN (got {len(ks_token)} chars, need >=32)",
        )
    elif ks_token.startswith("CHANGE_ME"):
        errors.append(
            "INSECURE HOPEFX_KILL_SWITCH_TOKEN: placeholder value — replace before deploying",
        )


def _validate_llm_backend(errors: list[str]) -> None:
    """Validate LLM backend config; warn (not error) when API key is absent."""
    llm_backend = (_env("LLM_BACKEND") or "anthropic").lower()
    valid_backends = {"anthropic", "openai"}

    if llm_backend not in valid_backends:
        errors.append(
            f"INVALID  LLM_BACKEND={llm_backend!r}: must be one of "
            f"{sorted(valid_backends)}. "
            "Set LLM_BACKEND=anthropic (default) or LLM_BACKEND=openai."
        )
        return

    key_map = {
        "anthropic": ("ANTHROPIC_API_KEY", "https://console.anthropic.com/settings/keys"),
        "openai": ("OPENAI_API_KEY", "https://platform.openai.com/api-keys"),
    }
    env_name, url = key_map[llm_backend]
    api_key = _env(env_name)

    if not api_key:
        logger.warning(
            "HOPEFXBrain: %s not set — brain will use stub responses (no real attack analysis). Get a key at %s",
            env_name,
            url,
        )
    elif api_key.startswith("CHANGE_ME"):
        errors.append(f"INSECURE {env_name}: placeholder value detected — replace with a real key from {url}")


def _validate_crypto_webhook_secret(errors: list[str]) -> None:
    """Require CRYPTO_WEBHOOK_SECRET in production to prevent unsigned webhook acceptance."""
    secret = _env("CRYPTO_WEBHOOK_SECRET")
    if not secret:
        errors.append(
            "MISSING  CRYPTO_WEBHOOK_SECRET — crypto payment webhooks will be rejected in production. "
            "Generate with: python3 -c \"import secrets; logger.info(secrets.token_hex(32))\""
        )
    elif len(secret) < 32:
        errors.append(
            f"WEAK     CRYPTO_WEBHOOK_SECRET is only {len(secret)} chars — minimum 32 required. "
            "Regenerate with: python3 -c \"import secrets; logger.info(secrets.token_hex(32))\""
        )


def _validate_argocd_webhook(errors: list[str]) -> None:
    argocd_webhook = _env("ARGOCD_ROLLBACK_WEBHOOK")
    if not argocd_webhook:
        logger.warning(
            "HOPEFXBrain: ARGOCD_ROLLBACK_WEBHOOK not set — nuclear lockdown "
            "will block IPs and set Redis flag but cannot trigger auto-rollback. "
            "Set to: https://<argocd-server>/api/v1/applications/hopefx/sync"
        )
    elif not argocd_webhook.startswith("https://"):
        errors.append(f"INVALID  ARGOCD_ROLLBACK_WEBHOOK={argocd_webhook[:60]!r}: must be an https:// URL")


def _validate_optional_vars(errors: list[str]) -> None:
    sentry_dsn = _env("SENTRY_DSN")
    if sentry_dsn and not sentry_dsn.startswith("https://"):
        errors.append(
            f"INVALID  SENTRY_DSN={sentry_dsn[:40]!r}: must be a valid https:// Sentry DSN",
        )

    _validate_mobile_cors(errors)
    _validate_ibkr_port(errors)


def _validate_mobile_cors(errors: list[str]) -> None:
    mobile_cors = _env("MOBILE_CORS_ORIGINS")
    if not mobile_cors:
        return
    bad = [
        o.strip()
        for o in mobile_cors.split(",")
        if o.strip() and not o.strip().startswith(("https://", "http://localhost", "http://127."))
    ]
    if bad:
        errors.append(
            f"INVALID  MOBILE_CORS_ORIGINS: non-https origins: {bad} — "
            "all origins must start with https:// (or http://localhost for dev)",
        )


def _validate_ibkr_port(errors: list[str]) -> None:
    ibkr_port = _env("IBKR_PORT")
    if not ibkr_port:
        return
    valid_ports = {4001, 4002, 7496, 7497}
    if not ibkr_port.isdigit() or int(ibkr_port) not in valid_ports:
        errors.append(
            f"INVALID  IBKR_PORT={ibkr_port!r}: "
            "must be one of 4001 (gateway-live), 4002 (gateway-paper), "
            "7496 (tws-live), 7497 (tws-paper)",
        )


def _validate_cors_wildcard(errors: list[str]) -> None:
    allowed_origins = _env("ALLOWED_ORIGINS")
    origins = [o.strip() for o in allowed_origins.split(",") if o.strip()]
    if "*" in origins:
        errors.append(
            "INSECURE ALLOWED_ORIGINS contains '*' in production — "
            "set ALLOWED_ORIGINS to a comma-separated list of explicit "
            "https:// origins (e.g. https://app.example.com)",
        )


# ---------------------------------------------------------------------------
# Public entry point
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
    errors: ClassVar[list[str]] = []
    dev_mode = _is_dev()

    _validate_jwt(errors)

    if not dev_mode:
        _validate_database(errors)
        _validate_redis(errors)
        _validate_encryption_key(errors)
        _validate_kill_switch_token(errors)
        _validate_argocd_webhook(errors)
        _validate_cors_wildcard(errors)
        _validate_crypto_webhook_secret(errors)

    _validate_broker(errors, dev_mode)
    _validate_llm_backend(errors)
    _validate_optional_vars(errors)

    if not errors:
        n_optional = sum(1 for v in ("SENTRY_DSN", "MOBILE_CORS_ORIGINS", "IBKR_PORT") if _env(v))
        logger.info(
            "Startup validation passed (mode=%s, %d optional vars checked).",
            "production" if not dev_mode else "development",
            n_optional,
        )
        return

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


def validate_environment_or_raise() -> None:
    """Non-strict variant — raises instead of sys.exit (for test harnesses)."""
    validate_environment(strict=False)
