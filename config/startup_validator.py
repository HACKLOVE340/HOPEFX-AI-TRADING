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
            'generate with: python -c "import secrets; print(secrets.token_urlsafe(48))"',
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
            "MISSING  DATABASE_URL or DB_HOST: set DATABASE_URL=postgresql://user:pass@host:5432/db",  # pragma: allowlist secret
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
    redis_password = _env("REDIS_PASSWORD")

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

    # Require a non-empty REDIS_PASSWORD in production.
    # docker-compose.yml passes --requirepass ${REDIS_PASSWORD:-} which means
    # an empty value leaves Redis unauthenticated inside the Docker network.
    if not redis_password:
        errors.append(
            "MISSING  REDIS_PASSWORD: Redis runs without authentication in production. "
            "Set REDIS_PASSWORD to a strong random value (e.g. openssl rand -hex 32).",
        )


def _validate_encryption_key(errors: list[str]) -> None:
    enc_key = _env("CONFIG_ENCRYPTION_KEY")
    if not enc_key:
        errors.append(
            "MISSING  CONFIG_ENCRYPTION_KEY: required for encrypting stored credentials. "
            'Generate with: python -c "import secrets; print(secrets.token_urlsafe(48))"',
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
    from config.settings import resolve_oanda_account, resolve_oanda_token

    oanda_key = resolve_oanda_token()
    oanda_acct = resolve_oanda_account()
    if not oanda_key:
        errors.append(
            "MISSING  OANDA_API_KEY: required when BROKER_TYPE=oanda. "
            "Accepted aliases: OANDA_ACCESS_TOKEN, OANDA_API_TOKEN, BROKER_OANDA_TOKEN "
            "(prefer OANDA_API_KEY — canonical name).",
        )
    if not oanda_acct:
        errors.append(
            "MISSING  OANDA_ACCOUNT_ID: required when BROKER_TYPE=oanda. "
            "Accepted alias: BROKER_OANDA_ACCOUNT (prefer OANDA_ACCOUNT_ID — canonical name).",
        )


def _validate_kill_switch_token(errors: list[str]) -> None:
    ks_token = _env("HOPEFX_KILL_SWITCH_TOKEN")
    if not ks_token:
        errors.append(
            "MISSING  HOPEFX_KILL_SWITCH_TOKEN: required to deactivate trading halts "
            'via API. Generate with: python -c "import secrets; print(secrets.token_urlsafe(48))"',
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
        # In production this is a meaningful gap; in dev the brain degrades
        # gracefully to stub responses so it is informational only.
        if _is_dev():
            logger.debug(
                "HOPEFXBrain: %s not set — brain will use stub responses. Set it to enable real AI analysis.",
                env_name,
            )
        else:
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
            'Generate with: python3 -c "import secrets; print(secrets.token_hex(32))"'
        )
    elif len(secret) < 32:
        errors.append(
            f"WEAK     CRYPTO_WEBHOOK_SECRET is only {len(secret)} chars — minimum 32 required. "
            'Regenerate with: python3 -c "import secrets; print(secrets.token_hex(32))"'
        )


def _validate_argocd_webhook(errors: list[str]) -> None:
    argocd_webhook = _env("ARGOCD_ROLLBACK_WEBHOOK")

    # Only warn when running in production with a live broker.
    # In dev mode or paper trading the ArgoCD webhook is not expected to be
    # configured, so emitting the warning would be noise on every startup.
    broker_type = (_env("BROKER_TYPE") or "paper").lower()
    is_live_broker = broker_type not in ("paper", "")

    if not argocd_webhook:
        if not _is_dev() and is_live_broker:
            logger.warning(
                "HOPEFXBrain: ARGOCD_ROLLBACK_WEBHOOK not set — nuclear lockdown "
                "will block IPs and set Redis flag but cannot trigger auto-rollback. "
                "Set to: https://<argocd-server>/api/v1/applications/hopefx/sync"
            )
        # Dev mode or paper trading: silently skip — ArgoCD is not expected.
    elif not argocd_webhook.startswith("https://"):
        errors.append(f"INVALID  ARGOCD_ROLLBACK_WEBHOOK={argocd_webhook[:60]!r}: must be an https:// URL")


def _validate_finnhub(errors: list[str]) -> None:
    """
    Warn when FINNHUB_API_KEY is absent.

    The MacroCalendarEngine falls back to a hardcoded schedule of recurring
    high-impact events when the key is missing, so this is not a hard failure.
    However, the live Finnhub calendar provides exact release dates and actual
    vs forecast values that drive the surprise-factor amplification in the ML
    pipeline — missing it degrades signal quality.
    """
    key = _env("FINNHUB_API_KEY")
    if not key:
        # Not added to errors (not a hard failure) — log at appropriate level.
        if _is_dev():
            logger.debug(
                "FINNHUB_API_KEY not set — MacroCalendarEngine will use the hardcoded "
                "fallback schedule instead of live Finnhub data. "
                "Get a free key at https://finnhub.io/register"
            )
        else:
            logger.warning(
                "FINNHUB_API_KEY not set — MacroCalendarEngine is running on the "
                "hardcoded fallback schedule. Live economic calendar data (exact release "
                "dates, actual vs forecast values) will not be available. "
                "Set FINNHUB_API_KEY to a valid Finnhub API key to enable live data."
            )
    elif key.startswith("CHANGE_ME"):
        errors.append(
            "INSECURE FINNHUB_API_KEY: placeholder value detected — "
            "replace with a real Finnhub API key from https://finnhub.io/dashboard"
        )


def _validate_optional_vars(errors: list[str]) -> None:
    sentry_dsn = _env("SENTRY_DSN")
    if sentry_dsn and not sentry_dsn.startswith("https://"):
        errors.append(
            f"INVALID  SENTRY_DSN={sentry_dsn[:40]!r}: must be a valid https:// Sentry DSN",
        )

    _validate_finnhub(errors)
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


def _validate_stripe(errors: list[str]) -> None:
    """Validate Stripe configuration; hard-fail in production on missing webhook secret."""
    key = _env("STRIPE_SECRET_KEY")
    webhook = _env("STRIPE_WEBHOOK_SECRET")
    billing_enabled = _env("FEATURE_BILLING_SUBSCRIPTION").lower() in ("true", "1", "yes")

    if not key:
        if _is_dev():
            logger.debug(
                "STRIPE_SECRET_KEY not set — Stripe payments disabled. "
                "Set to sk_test_... (test) or sk_live_... (production) to enable."
            )
        else:
            logger.warning(
                "STRIPE_SECRET_KEY not set — Stripe payment endpoints will raise "
                "until configured. Set to sk_live_... for production."
            )
    elif key.startswith("CHANGE_ME"):
        errors.append("INSECURE STRIPE_SECRET_KEY: placeholder value — replace with a real Stripe key.")
    elif not key.startswith(("sk_live_", "sk_test_")):
        errors.append(f"INVALID  STRIPE_SECRET_KEY: expected sk_live_... or sk_test_... prefix, got {key[:12]!r}...")

    if not webhook:
        if not _is_dev() and billing_enabled:
            # Hard error in production with billing enabled — an unsigned webhook
            # endpoint allows arbitrary event injection (fake payment confirmations,
            # subscription upgrades, etc.).
            errors.append(
                "MISSING  STRIPE_WEBHOOK_SECRET: required in production when "
                "FEATURE_BILLING_SUBSCRIPTION=true. Without it, the webhook endpoint "
                "accepts unsigned requests, enabling fake payment event injection. "
                "Set to whsec_... from Stripe Dashboard → Webhooks → your endpoint → Signing secret."
            )
        elif not _is_dev():
            logger.warning(
                "STRIPE_WEBHOOK_SECRET not set — Stripe webhook signature verification "
                "is disabled. Set to whsec_... from your Stripe dashboard."
            )
    elif webhook.startswith("CHANGE_ME"):
        errors.append("INSECURE STRIPE_WEBHOOK_SECRET: placeholder value — replace with the real whsec_... value.")


def _validate_redis_tls(errors: list[str]) -> None:
    """Hard-fail in production when Redis TLS certificate verification is disabled."""
    skip_verify = _env("REDIS_TLS_SKIP_VERIFY").lower()
    if skip_verify == "true":
        errors.append(
            "INSECURE REDIS_TLS_SKIP_VERIFY=true is not permitted in production. "
            "Disabling TLS certificate verification exposes the Redis connection "
            "(which carries session tokens and the JWT revocation blacklist) to "
            "MITM attacks. Remove REDIS_TLS_SKIP_VERIFY or set it to false. "
            "If using a self-signed cert, provide the CA via REDIS_TLS_CA_CERT instead."
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
    for origin in origins:
        if origin == "*":
            continue
        if origin.startswith("http://") and not origin.startswith("http://localhost") and "127.0.0.1" not in origin:
            errors.append(
                f"INSECURE ALLOWED_ORIGINS contains plain http:// origin '{origin}' — "
                "all production origins must use https:// to prevent downgrade attacks.",
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
    errors: list[str] = []
    dev_mode = _is_dev()

    _validate_jwt(errors)

    if not dev_mode:
        _validate_database(errors)
        _validate_redis(errors)
        _validate_redis_tls(errors)
        _validate_encryption_key(errors)
        _validate_kill_switch_token(errors)
        _validate_argocd_webhook(errors)
        _validate_cors_wildcard(errors)
        _validate_crypto_webhook_secret(errors)

    _validate_broker(errors, dev_mode)
    _validate_llm_backend(errors)
    _validate_stripe(errors)
    _validate_optional_vars(errors)

    if not errors:
        n_optional = sum(1 for v in ("SENTRY_DSN", "MOBILE_CORS_ORIGINS", "IBKR_PORT") if _env(v))
        logger.debug(
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
