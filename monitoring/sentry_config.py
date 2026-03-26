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
- Sensitive data scrubbing (API keys, tokens, passwords)
- FastAPI, SQLAlchemy, Redis, aiohttp integrations (auto-detected)
- ML fallback alert: CRITICAL log events forwarded as Sentry issues
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
    from monitoring.sentry_config import init_sentry, capture_ml_fallback_event

    # At app startup (called automatically by app.py via api/platform.py):
    init_sentry()

    # When the ML fallback activates (called from ml/__init__.py):
    capture_ml_fallback_event(
        reason="advanced_oos.pkl not found",
        fallback_model="xgb_macro.pkl",
        fallback_accuracy=0.503,
    )
"""

from __future__ import annotations

import logging
import os
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

# ── Sensitive field names to scrub from Sentry payloads ──────────────────────
_SCRUB_FIELDS = frozenset(
    {
        "password",
        "api_key",
        "api_secret",
        "token",
        "access_token",
        "refresh_token",
        "authorization",
        "secret",
        "private_key",
        "broker_token",
        "oanda_token",
        "jwt",
        "credit_card",
        "card_number",
        "cvv",
        "ssn",
    }
)


def _scrub_dict(d: Dict[str, Any]) -> Dict[str, Any]:
    """Recursively replace sensitive values with '[Filtered]'."""
    if not isinstance(d, dict):
        return d
    out = {}
    for k, v in d.items():
        if isinstance(k, str) and k.lower() in _SCRUB_FIELDS:
            out[k] = "[Filtered]"
        elif isinstance(v, dict):
            out[k] = _scrub_dict(v)
        elif isinstance(v, list):
            out[k] = [_scrub_dict(i) if isinstance(i, dict) else i for i in v]
        else:
            out[k] = v
    return out


def _before_send(event: Dict[str, Any], hint: Dict[str, Any]) -> Optional[Dict[str, Any]]:
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
    except Exception:
        pass

    return event


def _before_send_transaction(
    event: Dict[str, Any], hint: Dict[str, Any]
) -> Optional[Dict[str, Any]]:
    """
    Sentry before_send_transaction hook.

    Drops health-check and metrics transactions to reduce quota usage.
    """
    transaction = event.get("transaction", "")
    if transaction in ("/health", "/metrics", "/favicon.ico"):
        return None
    return event


def init_sentry() -> bool:
    """
    Initialise Sentry SDK with full performance monitoring.

    Returns True if Sentry was successfully initialised, False otherwise.
    Safe to call even if sentry-sdk is not installed or SENTRY_DSN is unset.
    """
    dsn = os.getenv("SENTRY_DSN", "")
    if not dsn:
        logger.info(
            "Sentry disabled — set SENTRY_DSN to enable error tracking and "
            "performance monitoring"
        )
        return False

    try:
        import sentry_sdk
        from sentry_sdk.integrations.logging import LoggingIntegration

        # Auto-detect available integrations
        integrations = []

        # Logging: capture ERROR+ as Sentry issues, WARNING+ as breadcrumbs
        integrations.append(
            LoggingIntegration(
                level=logging.WARNING,   # breadcrumb level
                event_level=logging.ERROR,  # issue level
            )
        )

        # FastAPI integration
        try:
            from sentry_sdk.integrations.fastapi import FastApiIntegration
            from sentry_sdk.integrations.starlette import StarletteIntegration
            integrations.append(StarletteIntegration(transaction_style="endpoint"))
            integrations.append(FastApiIntegration())
            logger.debug("Sentry: FastAPI integration enabled")
        except ImportError:
            pass

        # SQLAlchemy integration
        try:
            from sentry_sdk.integrations.sqlalchemy import SqlalchemyIntegration
            integrations.append(SqlalchemyIntegration())
            logger.debug("Sentry: SQLAlchemy integration enabled")
        except ImportError:
            pass

        # Redis integration
        try:
            from sentry_sdk.integrations.redis import RedisIntegration
            integrations.append(RedisIntegration())
            logger.debug("Sentry: Redis integration enabled")
        except ImportError:
            pass

        # aiohttp integration (used by AsyncOANDAConnector)
        try:
            from sentry_sdk.integrations.aiohttp import AioHttpIntegration
            integrations.append(AioHttpIntegration())
            logger.debug("Sentry: aiohttp integration enabled")
        except ImportError:
            pass

        # Determine release string
        release = os.getenv(
            "SENTRY_RELEASE",
            os.getenv("GIT_COMMIT", "unknown"),
        )

        # Sample rates
        traces_rate   = float(os.getenv("SENTRY_TRACES_SAMPLE_RATE",   "0.1"))
        profiles_rate = float(os.getenv("SENTRY_PROFILES_SAMPLE_RATE", "0.05"))
        environment   = os.getenv("SENTRY_ENVIRONMENT", os.getenv("APP_ENV", "development"))

        sentry_sdk.init(
            dsn=dsn,
            environment=environment,
            release=release,
            # Performance monitoring
            traces_sample_rate=traces_rate,
            profiles_sample_rate=profiles_rate,
            # Privacy
            send_default_pii=False,
            # Hooks
            before_send=_before_send,
            before_send_transaction=_before_send_transaction,
            # Integrations
            integrations=integrations,
            # Attach stack traces to all log-level events
            attach_stacktrace=True,
            # Max breadcrumbs per event
            max_breadcrumbs=50,
            # Ignore common noise
            ignore_errors=[
                KeyboardInterrupt,
                SystemExit,
            ],
        )

        # Set global tags visible on every event
        with sentry_sdk.configure_scope() as scope:
            scope.set_tag("service", "hopefx-api")
            scope.set_tag("environment", environment)
            scope.set_tag("release", release)
            try:
                from ml import get_model_version
                scope.set_tag("model_version", get_model_version())
            except Exception:
                pass
            try:
                oanda_region = os.getenv("OANDA_REGION", "us")
                scope.set_tag("oanda_region", oanda_region)
            except Exception:
                pass

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
            "sentry-sdk not installed — error tracking disabled. "
            "Install with: pip install sentry-sdk[fastapi]"
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

        with sentry_sdk.push_scope() as scope:
            scope.set_level("fatal")
            scope.set_tag("alert_type", "ml_fallback_activated")
            scope.set_tag("fallback_model", fallback_model)
            scope.set_extra("reason", reason)
            scope.set_extra("fallback_accuracy", fallback_accuracy)
            scope.set_extra(
                "impact",
                f"Live model degraded from 68.0% OOS to {fallback_accuracy*100:.1f}% OOS. "
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
                f"running on {fallback_model} ({fallback_accuracy*100:.1f}% OOS, no edge)",
                level="fatal",
            )
        logger.debug("Sentry: ML fallback event captured")
    except Exception as exc:
        logger.debug("Sentry capture_ml_fallback_event failed: %s", exc)


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
    except Exception:
        import contextlib

        @contextlib.contextmanager
        def _noop():
            yield type("_NoopTxn", (), {"set_tag": lambda *a, **k: None})()

        return _noop()
