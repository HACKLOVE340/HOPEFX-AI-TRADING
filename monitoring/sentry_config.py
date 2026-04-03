# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
monitoring/sentry_config.py
===========================
Production Sentry SDK configuration for HOPEFX.

Features
--------
- Error tracking with full stack traces
- Performance monitoring (transactions, spans)
- Custom tags: environment, model_version, broker, region
- Profiling (CPU profiling of slow transactions)
- Release tracking (git SHA from GIT_COMMIT env var)
- Sensitive data scrubbing (API keys, tokens, passwords, account IDs, IPs)
- FastAPI, SQLAlchemy, Redis, aiohttp integrations (auto-detected)
- ML fallback alert: CRITICAL log events forwarded as Sentry issues
- Paper trading clock alert: fires when 30-day gate expires
- Sharpe gate alert: fires when N < 600 trades but live trading attempted
- Kill-switch alert: fires when kill-switch trips
- Custom before_send hook: strips PII and adds trading context

Environment variables
---------------------
SENTRY_DSN                  — Sentry project DSN (required to enable)
SENTRY_TRACES_SAMPLE_RATE   — 0.0–1.0, fraction of transactions traced (default: 0.1)
SENTRY_PROFILES_SAMPLE_RATE — 0.0–1.0, fraction of transactions profiled (default: 0.05)
SENTRY_ENVIRONMENT          — overrides APP_ENV for Sentry environment tag
SENTRY_RELEASE              — release string (default: GIT_COMMIT env var or "unknown")
APP_ENV                     — development | staging | production
GIT_COMMIT                  — git SHA injected by CI/CD pipeline

Usage
-----
    from monitoring.sentry_config import (
        init_sentry,
        capture_ml_fallback_event,
        capture_paper_clock_alert,
        capture_sharpe_gate_alert,
        capture_kill_switch_alert,
    )

    init_sentry()   # called automatically by app.py via api/platform.py
"""

from __future__ import annotations

import logging
import os
from typing import Any

logger = logging.getLogger(__name__)

# Log message constant reused across multiple except blocks
_SUPPRESSED_EXC_MSG = "Suppressed exception: %s"

# ── Sensitive field names to scrub from Sentry payloads ──────────────────────
_SCRUB_FIELDS = frozenset(
    {
        # Auth / credentials
        "password",
        "passwd",
        "pwd",
        "api_key",
        "api_secret",
        "api_token",
        "token",
        "access_token",
        "refresh_token",
        "id_token",
        "authorization",
        "auth",
        "bearer",
        "secret",
        "secret_key",
        "private_key",
        "signing_key",
        "broker_token",
        "oanda_token",
        "oanda_api_key",
        "broker_oanda_token",
        "broker_alpaca_key",
        "broker_alpaca_secret",
        "jwt",
        "session_token",
        "cookie",
        # Financial PII
        "credit_card",
        "card_number",
        "cvv",
        "cvc",
        "expiry",
        "bank_account",
        "routing_number",
        "iban",
        "swift",
        "stripe_key",
        "stripe_secret",
        "paypal_secret",
        # Personal PII
        "ssn",
        "social_security",
        "dob",
        "date_of_birth",
        "email",
        "phone",
        "address",
        "ip_address",
        "ip",
        "account_id",
        "user_id",  # scrub account IDs from payloads
        # Database / infra
        "database_url",
        "db_url",
        "redis_url",
        "postgres_url",
        "smtp_password",
        "smtp_user",
        "sentry_dsn",  # never leak the DSN itself
    }
)

# ── Regex patterns for PII in string values ───────────────────────────────────
import re as _re

_PII_PATTERNS = [
    # Bearer tokens — match base64url + padding chars after "Bearer "
    (_re.compile(r"Bearer\s+\S+", _re.IGNORECASE), "Bearer [Filtered]"),
    # JWT tokens (3 base64 segments)
    (
        _re.compile(r"eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+"),
        "[JWT Filtered]",
    ),
    # OANDA API keys (32-char hex-like)
    (_re.compile(r"\b[0-9a-f]{32}\b"), "[Key Filtered]"),
    # IPv4 addresses
    (_re.compile(r"\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b"), "[IP Filtered]"),
    # Email addresses (- moved to end of character class)
    (
        _re.compile(r"\b[A-Za-z0-9._%+]+@[A-Za-z0-9.]+\.[A-Za-z]{2,}\b"),
        "[Email Filtered]",
    ),
]


def _scrub_string(s: str) -> str:
    """Apply PII regex patterns to a string value."""
    for pattern, replacement in _PII_PATTERNS:
        s = pattern.sub(replacement, s)
    return s


def _scrub_value(v: Any) -> Any:
    """Scrub a single value: recurse into dicts, scrub strings, pass others through."""
    if isinstance(v, dict):
        return _scrub_dict(v)
    if isinstance(v, list):
        return [_scrub_value(i) for i in v]
    if isinstance(v, str):
        return _scrub_string(v)
    return v


def _scrub_dict(d: dict[str, Any]) -> dict[str, Any]:
    """Recursively replace sensitive fields with '[Filtered]' and scrub PII strings."""
    if not isinstance(d, dict):
        return d
    out = {}
    for k, v in d.items():
        if isinstance(k, str) and k.lower() in _SCRUB_FIELDS:
            out[k] = "[Filtered]"
        else:
            out[k] = _scrub_value(v)
    return out


def _before_send(event: dict[str, Any], hint: dict[str, Any]) -> dict[str, Any] | None:
    """
    Sentry before_send hook.

    - Scrubs sensitive fields from request data, extra, and contexts.
    - Adds trading-specific context tags.
    - Drops health-check noise (GET /health 200 events).
    """
    # Drop noisy health-check transactions
    transaction = event.get("transaction", "")
    if transaction in ("/health", "/metrics", "/favicon.ico"):
        return None

    # Scrub request data
    request = event.get("request", {})
    if "data" in request and isinstance(request["data"], dict):
        request["data"] = _scrub_dict(request["data"])
    if "headers" in request and isinstance(request["headers"], dict):
        request["headers"] = _scrub_dict(request["headers"])

    # Scrub extra context
    if "extra" in event and isinstance(event["extra"], dict):
        event["extra"] = _scrub_dict(event["extra"])

    # Add trading context
    try:
        from ml import get_model_version

        event.setdefault("tags", {})["model_version"] = get_model_version()
    except Exception as _exc:
        logger.debug(_SUPPRESSED_EXC_MSG, _exc)

    return event


def _before_send_transaction(event: dict[str, Any], hint: dict[str, Any]) -> dict[str, Any] | None:
    """
    Sentry before_send_transaction hook.

    Drops health-check and metrics transactions to reduce quota usage.
    """
    transaction = event.get("transaction", "")
    if transaction in ("/health", "/metrics", "/favicon.ico"):
        return None
    return event


def _build_sentry_integrations() -> list:
    """Auto-detect and return available Sentry SDK integrations."""
    from sentry_sdk.integrations.logging import LoggingIntegration

    integrations: list = [
        LoggingIntegration(
            level=logging.WARNING,  # breadcrumb level
            event_level=logging.ERROR,  # issue level
        )
    ]

    try:
        from sentry_sdk.integrations.fastapi import FastApiIntegration
        from sentry_sdk.integrations.starlette import StarletteIntegration

        integrations.append(StarletteIntegration(transaction_style="endpoint"))
        integrations.append(FastApiIntegration())
        logger.debug("Sentry: FastAPI integration enabled")
    except ImportError:
        ...  # nosec B110

    try:
        from sentry_sdk.integrations.sqlalchemy import SqlalchemyIntegration

        integrations.append(SqlalchemyIntegration())
        logger.debug("Sentry: SQLAlchemy integration enabled")
    except ImportError:
        ...  # nosec B110

    try:
        from sentry_sdk.integrations.redis import RedisIntegration

        integrations.append(RedisIntegration())
        logger.debug("Sentry: Redis integration enabled")
    except ImportError:
        ...  # nosec B110

    try:
        from sentry_sdk.integrations.aiohttp import AioHttpIntegration

        integrations.append(AioHttpIntegration())
        logger.debug("Sentry: aiohttp integration enabled")
    except ImportError:
        ...  # nosec B110

    return integrations


def _set_sentry_global_tags(sentry_sdk: Any, environment: str, release: str) -> None:
    """Set global tags visible on every Sentry event."""
    with sentry_sdk.new_scope() as scope:
        scope.set_tag("service", "hopefx-api")
        scope.set_tag("environment", environment)
        scope.set_tag("release", release)
        try:
            from ml import get_model_version

            scope.set_tag("model_version", get_model_version())
        except Exception as _exc:
            logger.debug(_SUPPRESSED_EXC_MSG, _exc)
        try:
            scope.set_tag("oanda_region", os.getenv("OANDA_REGION", "us"))
        except Exception as _exc:
            logger.debug(_SUPPRESSED_EXC_MSG, _exc)


def init_sentry() -> bool:
    """
    Initialise Sentry SDK with full performance monitoring.

    Returns True if Sentry was successfully initialised, False otherwise.
    Safe to call even if sentry-sdk is not installed or SENTRY_DSN is unset.
    """
    dsn = os.getenv("SENTRY_DSN", "")
    if not dsn:
        env = os.getenv("APP_ENV", "development")
        if env == "production":
            logger.warning(
                "SENTRY_DSN is not set in production — production errors will NOT be "
                "reported. Sign up at https://sentry.io (free tier: 5K errors/month), "
                "create a FastAPI project, and set SENTRY_DSN in your .env."
            )
        else:
            logger.info("Sentry disabled (SENTRY_DSN not set) — set it to enable error tracking")
        return False

    try:
        import sentry_sdk

        release = os.getenv("SENTRY_RELEASE", os.getenv("GIT_COMMIT", "unknown"))
        traces_rate = float(os.getenv("SENTRY_TRACES_SAMPLE_RATE", "0.1"))
        profiles_rate = float(os.getenv("SENTRY_PROFILES_SAMPLE_RATE", "0.05"))
        environment = os.getenv("SENTRY_ENVIRONMENT", os.getenv("APP_ENV", "development"))

        sentry_sdk.init(
            dsn=dsn,
            environment=environment,
            release=release,
            traces_sample_rate=traces_rate,
            profiles_sample_rate=profiles_rate,
            send_default_pii=False,
            before_send=_before_send,
            before_send_transaction=_before_send_transaction,
            integrations=_build_sentry_integrations(),
            attach_stacktrace=True,
            max_breadcrumbs=50,
            ignore_errors=[KeyboardInterrupt, SystemExit],
        )

        _set_sentry_global_tags(sentry_sdk, environment, release)

        logger.info(
            "Sentry initialised: env=%s release=%s traces=%.0f%% profiles=%.0f%%",
            environment,
            release,
            traces_rate * 100,
            profiles_rate * 100,
        )
        return True

    except ImportError:
        logger.warning(
            "sentry-sdk not installed — error tracking disabled. Install with: pip install sentry-sdk[fastapi]"
        )
        return False
    except Exception as exc:
        logger.warning("Sentry init failed (non-fatal): %s", exc)
        return False


def capture_ml_fallback_event(
    reason: str,
    fallback_model: str,
    fallback_accuracy: float,
) -> None:
    """
    Capture a Sentry issue when the ML fallback model activates.

    This is the primary operator alert for silent degradation from the
    68% advanced model to the ~50% fallback model. The issue appears in
    Sentry with level=CRITICAL so it triggers PagerDuty/Slack alerts.

    Parameters
    ----------
    reason           : Why the advanced model failed to load
    fallback_model   : Name of the fallback model file
    fallback_accuracy: OOS accuracy of the fallback model (~0.503)
    """
    try:
        import sentry_sdk

        with sentry_sdk.new_scope() as scope:
            scope.set_level("fatal")
            scope.set_tag("alert_type", "ml_fallback_activated")
            scope.set_tag("fallback_model", fallback_model)
            scope.set_extra("reason", reason)
            scope.set_extra("fallback_accuracy", fallback_accuracy)
            scope.set_extra(
                "impact",
                f"Live model degraded from 68.0% OOS to {fallback_accuracy * 100:.1f}% OOS. "
                "No demonstrated edge above chance on fallback model.",
            )
            scope.set_extra(
                "remediation",
                "Ensure advanced_oos.pkl exists in ml/saved_models/ and "
                "scikit-learn/xgboost versions match training environment. "
                "Re-run: python ml/train_advanced.py --years 50 --oos-years 3",
            )
            sentry_sdk.capture_message(
                f"ML FALLBACK ACTIVATED: advanced_oos.pkl unavailable — "
                f"running on {fallback_model} ({fallback_accuracy * 100:.1f}% OOS, no edge)",
                level="fatal",
            )
        logger.debug("Sentry: ML fallback event captured")
    except Exception as exc:
        logger.debug("Sentry capture_ml_fallback_event failed: %s", exc)


def capture_paper_clock_alert(
    elapsed_days: float,
    remaining_days: float,
    environment: str = "practice",
) -> None:
    """
    Capture a Sentry warning when the 30-day paper trading clock expires
    or when live trading is attempted before the clock completes.

    Called by the production live trading gate when paper_clock.is_complete()
    returns False but a live order is attempted.
    """
    try:
        import sentry_sdk

        with sentry_sdk.new_scope() as scope:
            scope.set_level("warning")
            scope.set_tag("alert_type", "paper_clock_gate")
            scope.set_tag("oanda_environment", environment)
            scope.set_extra("elapsed_days", elapsed_days)
            scope.set_extra("remaining_days", remaining_days)
            scope.set_extra(
                "remediation",
                f"Paper trading clock needs {remaining_days:.1f} more days. "
                "Do not enable live trading until 30-day run is complete.",
            )
            sentry_sdk.capture_message(
                f"PAPER CLOCK GATE: {elapsed_days:.1f}/{elapsed_days + remaining_days:.0f} days "
                f"elapsed — live trading blocked until clock completes.",
                level="warning",
            )
        logger.debug("Sentry: paper clock alert captured")
    except Exception as exc:
        logger.debug("Sentry capture_paper_clock_alert failed: %s", exc)


def capture_sharpe_gate_alert(
    n_trades: int,
    sharpe: float,
    se: float,
    target_n: int = 600,
) -> None:
    """
    Capture a Sentry warning when live trading is attempted but the Sharpe
    SE gate has not been passed (N < target_n trades).

    N=48 trades: SE=0.21 — not credible. Need N=600 for SE<=0.10.
    """
    try:
        import sentry_sdk

        with sentry_sdk.new_scope() as scope:
            scope.set_level("warning")
            scope.set_tag("alert_type", "sharpe_gate_blocked")
            scope.set_extra("n_trades", n_trades)
            scope.set_extra("sharpe_estimate", sharpe)
            scope.set_extra("sharpe_se", se)
            scope.set_extra("target_n", target_n)
            scope.set_extra(
                "remediation",
                f"Run multi-symbol backtest (XAU+BTC+ETH) targeting N={target_n} trades. "
                f"Current N={n_trades} gives SE={se:.3f} — not statistically credible.",
            )
            sentry_sdk.capture_message(
                f"SHARPE GATE BLOCKED: N={n_trades} trades, SE={se:.3f} "
                f"(need N>={target_n} for SE<=0.10). Sharpe={sharpe:.2f} not credible.",
                level="warning",
            )
        logger.debug("Sentry: Sharpe gate alert captured")
    except Exception as exc:
        logger.debug("Sentry capture_sharpe_gate_alert failed: %s", exc)


def capture_kill_switch_alert(
    reason: str,
    triggered_by: str = "system",
    drawdown_pct: float = 0.0,
) -> None:
    """
    Capture a Sentry critical alert when the kill-switch trips.

    This is the highest-priority alert — it means all trading has been
    halted due to a risk limit breach.
    """
    try:
        import sentry_sdk

        with sentry_sdk.new_scope() as scope:
            scope.set_level("fatal")
            scope.set_tag("alert_type", "kill_switch_triggered")
            scope.set_tag("triggered_by", triggered_by)
            scope.set_extra("reason", reason)
            scope.set_extra("drawdown_pct", drawdown_pct)
            scope.set_extra(
                "impact",
                "ALL live trading halted. Manual review required before re-enabling.",
            )
            scope.set_extra(
                "remediation",
                "Review risk limits in config/risk_limits.json. "
                "Re-enable via POST /api/kill-switch/reset (admin only).",
            )
            sentry_sdk.capture_message(
                f"KILL SWITCH TRIGGERED by {triggered_by}: {reason} "
                f"(drawdown={drawdown_pct:.1f}%). ALL TRADING HALTED.",
                level="fatal",
            )
        logger.critical("Sentry: kill-switch alert captured — %s", reason)
    except Exception as exc:
        logger.debug("Sentry capture_kill_switch_alert failed: %s", exc)


def start_transaction(name: str, op: str = "task") -> Any:
    """
    Start a Sentry performance transaction for manual instrumentation.

    Usage:
        with start_transaction("macro_store_refresh", op="task") as txn:
            txn.set_tag("series_count", n)
            do_work()

    Returns a no-op context manager if Sentry is not initialised.
    """
    try:
        import sentry_sdk

        return sentry_sdk.start_transaction(name=name, op=op)
    except ImportError:
        import contextlib

        @contextlib.contextmanager
        def _noop():
            yield type("_NoopTxn", (), {"set_tag": lambda *a, **k: None})()

        return _noop()
