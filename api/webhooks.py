# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
api/webhooks.py
===============
Inbound webhook handlers for external signal providers.

Currently supported:
  POST /api/webhooks/tradingview  — TradingView alert → signal ingestion

Security
--------
Every request is authenticated via HMAC-SHA256 of the raw request body
using the TRADINGVIEW_WEBHOOK_SECRET env var.  The signature must be
supplied in the ``X-TV-Signature`` header as a hex digest.  Requests
without a valid signature are rejected with 401.

If TRADINGVIEW_WEBHOOK_SECRET is not set the endpoint is disabled and
returns 503 so the UI can surface a clear configuration error.

TradingView alert message format (JSON body)
--------------------------------------------
{
  "symbol":     "EURUSD",          // required
  "action":     "buy" | "sell" | "close" | "hold",  // required
  "price":      1.08542,           // optional — current bar close
  "sl":         1.08200,           // optional — stop loss
  "tp":         1.09100,           // optional — take profit
  "confidence": 0.75,              // optional — 0-1
  "timeframe":  "1h",              // optional
  "comment":    "RSI oversold",    // optional — alert message text
  "secret":     "<shared secret>"  // optional — body-level secret (legacy)
}
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import os
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/webhooks", tags=["Webhooks"])

UTC = timezone.utc


# ── Request / response models ─────────────────────────────────────────────────

class TradingViewAlert(BaseModel):
    """Parsed TradingView alert payload."""

    symbol: str = Field(..., description="Instrument symbol, e.g. EURUSD")
    action: str = Field(..., description="buy | sell | close | hold")
    price: float | None = Field(None, description="Current price at alert time")
    sl: float | None = Field(None, description="Stop-loss level")
    tp: float | None = Field(None, description="Take-profit level")
    confidence: float = Field(0.7, ge=0.0, le=1.0, description="Signal confidence 0-1")
    timeframe: str = Field("1h", description="Chart timeframe")
    comment: str = Field("", description="Alert message / comment")
    secret: str | None = Field(None, description="Optional body-level shared secret (legacy)")


class WebhookResponse(BaseModel):
    received: bool
    signal_id: str | None = None
    message: str = ""


# ── Helpers ───────────────────────────────────────────────────────────────────

def _get_secret() -> str | None:
    """Return the configured webhook secret, or None if unset."""
    return os.getenv("TRADINGVIEW_WEBHOOK_SECRET", "").strip() or None


def _verify_signature(body: bytes, header_sig: str | None, secret: str) -> bool:
    """Verify HMAC-SHA256 signature from X-TV-Signature header."""
    if not header_sig:
        return False
    expected = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, header_sig.lower().lstrip("sha256="))


def _action_to_direction(action: str) -> str:
    """Normalise TradingView action string to internal direction."""
    a = action.lower().strip()
    if a in ("buy", "long"):
        return "buy"
    if a in ("sell", "short"):
        return "sell"
    if a == "close":
        return "hold"
    return "hold"


# ── Endpoint ──────────────────────────────────────────────────────────────────

@router.post(
    "/tradingview",
    response_model=WebhookResponse,
    summary="Receive TradingView alert and ingest as trading signal",
    status_code=status.HTTP_200_OK,
)
async def tradingview_webhook(request: Request) -> WebhookResponse:
    """
    Receive a TradingView alert, verify its authenticity, and ingest it
    into the live signal service so it appears on /api/signals/latest.

    Authentication
    --------------
    Set ``TRADINGVIEW_WEBHOOK_SECRET`` in .env to the same value you enter
    in TradingView's alert webhook URL field.  The endpoint verifies the
    ``X-TV-Signature`` header (HMAC-SHA256 of the raw body).

    As a fallback, if the alert JSON contains a ``secret`` field that
    matches the configured secret, the request is also accepted.  This
    supports TradingView's body-level secret pattern.
    """
    secret = _get_secret()
    if not secret:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="TRADINGVIEW_WEBHOOK_SECRET is not configured. Set it in .env to enable this endpoint.",
        )

    body = await request.body()

    # Primary: HMAC-SHA256 header verification
    header_sig = request.headers.get("X-TV-Signature") or request.headers.get("X-Tradingview-Signature")
    sig_valid = _verify_signature(body, header_sig, secret)

    # Parse JSON payload
    try:
        import json
        payload: dict[str, Any] = json.loads(body)
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Request body must be valid JSON.",
        )

    # Fallback: body-level secret field (legacy TradingView pattern)
    if not sig_valid:
        body_secret = str(payload.get("secret", "")).strip()
        if body_secret and hmac.compare_digest(body_secret, secret):
            sig_valid = True

    if not sig_valid:
        logger.warning(
            "TradingView webhook: invalid signature from %s",
            request.client.host if request.client else "unknown",
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid webhook signature. Check TRADINGVIEW_WEBHOOK_SECRET.",
        )

    # Validate payload
    try:
        alert = TradingViewAlert(**payload)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Invalid alert payload: {exc}",
        )

    direction = _action_to_direction(alert.action)
    entry = alert.price or 0.0

    # Build signal payload compatible with RealTimeSignalService.ingest_engine_signal
    signal_payload: dict[str, Any] = {
        "symbol": alert.symbol.upper().replace("/", ""),
        "direction": direction,
        "confidence": alert.confidence,
        "probability": alert.confidence,
        "entry_price": entry,
        "stop_loss": alert.sl,
        "take_profit": alert.tp,
        "timestamp": datetime.now(UTC).isoformat(),
        "source": "tradingview_webhook",
        "regime": "unknown",
        "timeframe": alert.timeframe,
        "comment": alert.comment,
    }

    signal_id: str | None = None
    try:
        from api.signals import _get_signal_service
        svc = _get_signal_service()
        signal = svc.ingest_engine_signal(signal_payload)
        if signal:
            signal_id = signal.id
            logger.info(
                "TradingView webhook: ingested signal %s — %s %s @ %.5f (conf=%.2f)",
                signal_id,
                direction.upper(),
                alert.symbol,
                entry,
                alert.confidence,
            )
    except Exception as exc:
        logger.warning("TradingView webhook: signal ingestion failed: %s", exc)

    return WebhookResponse(
        received=True,
        signal_id=signal_id,
        message=f"Alert received: {direction.upper()} {alert.symbol}",
    )
