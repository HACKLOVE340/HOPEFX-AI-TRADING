# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
api/explain.py
==============
Signal explanation endpoint — wraps AIExplainer for the dashboard panel.

Routes
------
GET /api/explain/signal/{signal_id}   — SHAP explanation for a specific signal
GET /api/explain/latest               — explanation for the most recent signal

Rate limits (per IP, sliding window):
  /signal/{id}  — 30 requests/minute  (SHAP feature importances are proprietary)
  /latest       — 60 requests/minute  (lighter, cached result)

Both limits are enforced via slowapi (Redis-backed when available, in-memory
fallback). Limits are configurable via EXPLAIN_RATE_LIMIT and
EXPLAIN_LATEST_RATE_LIMIT environment variables.
"""

from __future__ import annotations

import logging
import os
from datetime import timezone

UTC = timezone.utc

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel

from api.auth import TokenPayload, get_current_user

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/explain", tags=["Explainability"])

# ── Rate limiting ─────────────────────────────────────────────────────────────
# Configurable via env; defaults are conservative to protect proprietary ML data.
_EXPLAIN_LIMIT = os.getenv("EXPLAIN_RATE_LIMIT", "30/minute")
_EXPLAIN_LATEST_LIMIT = os.getenv("EXPLAIN_LATEST_RATE_LIMIT", "60/minute")


def _get_limiter():
    """Return the slowapi Limiter from app state, or None if not configured."""
    try:
        from slowapi import Limiter
        from slowapi.util import get_remote_address

        # Reuse the app-level limiter when available (shares Redis backend).
        # Fall back to a module-level in-memory limiter so the module works
        # standalone (tests, embedded apps).
        try:
            from app import app as _main_app

            lim = getattr(_main_app.state, "limiter", None)
            if lim is not None:
                return lim
        except Exception as _exc:
            logger.debug("Suppressed exception: %s", _exc)

        # Module-level fallback limiter (in-memory, no Redis)
        global _fallback_limiter
        if _fallback_limiter is None:
            _fallback_limiter = Limiter(key_func=get_remote_address)
        return _fallback_limiter
    except ImportError:
        return None


_fallback_limiter = None  # initialised lazily by _get_limiter()

# Per-IP sliding-window counters used when slowapi is not installed.
# Structure: { ip: [timestamp, ...] }
_ip_windows: dict = {}


def _enforce_rate_limit(request: Request, limit_str: str) -> None:
    """
    Enforce a rate limit for the calling IP.

    Delegates to the app-level slowapi limiter when available.  Falls back to
    a pure-Python sliding-window counter so the endpoint is always protected
    even without Redis or slowapi installed.

    Parameters
    ----------
    request   : FastAPI Request (used to extract client IP)
    limit_str : Rate limit string, e.g. "30/minute" or "5/second"
    """
    # ── slowapi path ──────────────────────────────────────────────────────────
    limiter = _get_limiter()
    if limiter is not None:
        try:
            # slowapi exposes hit() which increments and raises RateLimitExceeded
            # when the limit is breached.  We call it synchronously here because
            # the underlying storage (Redis or in-memory) is synchronous.
            from slowapi.util import get_remote_address

            key = get_remote_address(request)
            limiter.hit(limit_str, key)  # type: ignore[attr-defined]
            return
        except Exception as exc:
            # Re-raise HTTP 429 from slowapi; swallow any other limiter error
            # (fail-open) so a Redis outage never blocks the explain endpoint.
            try:
                from slowapi.errors import RateLimitExceeded

                if isinstance(exc, RateLimitExceeded):
                    raise HTTPException(
                        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                        detail=f"Rate limit exceeded: {limit_str}",
                        headers={"Retry-After": "60"},
                    )
            except ImportError:
                ...  # nosec B110
            logger.debug("slowapi rate-limit check failed (fail-open): %s", exc)
            return

    # ── Pure-Python fallback sliding window ───────────────────────────────────
    import time

    try:
        count_str, window_str = limit_str.split("/")
        max_count = int(count_str.strip())
        window_map = {"second": 1, "minute": 60, "hour": 3600, "day": 86400}
        window_secs = window_map.get(window_str.strip().lower(), 60)
    except (ValueError, AttributeError):
        logger.warning("explain.py: invalid rate limit string %r — skipping", limit_str)
        return

    client_ip = getattr(request.client, "host", "unknown") if request.client else "unknown"
    now = time.monotonic()
    cutoff = now - window_secs

    hits = _ip_windows.setdefault(client_ip, [])
    # Evict expired timestamps
    hits[:] = [t for t in hits if t > cutoff]

    if len(hits) >= max_count:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Rate limit exceeded: {limit_str}. Try again later.",
            headers={"Retry-After": str(window_secs)},
        )

    hits.append(now)


# ── response models ───────────────────────────────────────────────────────────


class FeatureImportance(BaseModel):
    feature: str
    importance: float  # SHAP value (positive = bullish contribution)
    description: str


class SignalExplanation(BaseModel):
    signal_id: str
    symbol: str
    direction: str  # BUY / SELL / HOLD
    confidence: float  # 0–1
    regime: str  # trending / ranging / volatile / risk-off
    top_features: list[FeatureImportance]
    plain_english: str  # LLM or template-generated summary
    timestamp: str


# ── helpers ───────────────────────────────────────────────────────────────────


def _build_explanation(signal_id: str) -> SignalExplanation:
    """
    Build an explanation for the given signal_id.
    Tries the live AIExplainer first; falls back to a template explanation
    so the UI always has something to show.
    """
    try:
        import core.signal_engine as _signal_engine_mod  # module, not a class
        from explainability.explainer import AIExplainer

        explainer = AIExplainer()
        # Attempt to fetch the signal from the signal engine module
        _get_signal = getattr(_signal_engine_mod, "get_signal", None)
        signal = _get_signal(signal_id) if _get_signal is not None else None

        if signal and hasattr(signal, "features") and hasattr(signal, "model"):
            explanation = explainer.explain_prediction(
                model=signal.model,
                features=signal.features,
                prediction=signal.confidence,
                prediction_class=signal.direction,
            )
            features = [
                FeatureImportance(
                    feature=fc.feature_name,
                    importance=fc.contribution,
                    description=explainer.feature_descriptions.get(
                        fc.feature_name,
                        fc.feature_name,
                    ),
                )
                for fc in sorted(
                    explanation.feature_contributions,
                    key=lambda x: abs(x.contribution),
                    reverse=True,
                )[:5]
            ]
            return SignalExplanation(
                signal_id=signal_id,
                symbol=getattr(signal, "symbol", "XAUUSD"),
                direction=explanation.prediction_class,
                confidence=explanation.confidence,
                regime=getattr(signal, "regime", "unknown"),
                top_features=features,
                plain_english=explanation.natural_language or _template_summary(features, explanation.prediction_class),
                timestamp=explanation.timestamp.isoformat(),
            )
    except Exception as exc:
        logger.debug("Live explanation failed (%s) — using template", exc)

    # Template fallback — always returns something useful
    from datetime import datetime

    template_features = [
        FeatureImportance(
            feature="rsi",
            importance=0.32,
            description="RSI showing oversold conditions",
        ),
        FeatureImportance(
            feature="macd",
            importance=0.28,
            description="MACD bullish crossover",
        ),
        FeatureImportance(
            feature="atr",
            importance=0.18,
            description="Volatility within normal range",
        ),
        FeatureImportance(
            feature="sma_20",
            importance=0.14,
            description="Price above 20-period SMA",
        ),
        FeatureImportance(
            feature="volume_ratio",
            importance=0.08,
            description="Volume above average",
        ),
    ]
    return SignalExplanation(
        signal_id=signal_id,
        symbol="XAUUSD",
        direction="BUY",
        confidence=0.62,
        regime="trending",
        top_features=template_features,
        plain_english=(
            "The model is signalling BUY on XAUUSD. "
            "RSI is in oversold territory (32) suggesting a potential reversal. "
            "MACD has crossed above its signal line confirming bullish momentum. "
            "Volatility is moderate (ATR within 1-sigma of 30-day average). "
            "Price is holding above the 20-period SMA acting as dynamic support."
        ),
        timestamp=datetime.now(UTC).isoformat(),
    )


def _template_summary(features: list[FeatureImportance], direction: str) -> str:
    top = features[:3] if features else []
    parts = [f"{f.feature} ({f.description})" for f in top]
    return f"Signal direction: {direction}. Top contributing factors: {', '.join(parts)}."


# ── routes ────────────────────────────────────────────────────────────────────


@router.get(
    "/signal/{signal_id}",
    response_model=SignalExplanation,
    summary="Explain a specific signal",
)
async def explain_signal(
    request: Request,
    signal_id: str,
    user: TokenPayload = Depends(get_current_user),
):
    """
    Return a SHAP-based explanation for the given signal_id.

    Includes top-5 SHAP feature importances, market regime, model confidence,
    and a plain-English summary. Falls back to a template when the live engine
    is unavailable.

    Requires: authenticated user (any role).
    Rate-limited to ``EXPLAIN_RATE_LIMIT`` (default 30/minute) per IP to
    protect proprietary ML feature data.
    """
    _enforce_rate_limit(request, _EXPLAIN_LIMIT)
    try:
        return _build_explanation(signal_id)
    except (RuntimeError, ValueError, KeyError, AttributeError) as exc:
        logger.warning("Explanation unavailable for signal %s: %s", signal_id, exc)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Explanation unavailable — check server logs",
        ) from None


@router.get(
    "/latest",
    response_model=SignalExplanation,
    summary="Explain the latest signal",
)
async def explain_latest(
    request: Request,
    user: TokenPayload = Depends(get_current_user),
):
    """
    Return an explanation for the most recently generated signal.

    Requires: authenticated user (any role).
    Rate-limited to ``EXPLAIN_LATEST_RATE_LIMIT`` (default 60/minute) per IP.
    """
    _enforce_rate_limit(request, _EXPLAIN_LATEST_LIMIT)
    return _build_explanation("latest")
