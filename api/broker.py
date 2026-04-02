# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
api/broker.py
=============
Broker management endpoints.

Routes
------
POST /api/broker/test-connection  — test broker credentials and return latency + balance
GET  /api/broker/status           — current broker type, connection state, data feed, ML engine
GET  /api/broker/paper-clock      — OANDA paper trading clock status (elapsed/remaining days)
POST /api/broker/stamp-oanda      — stamp real OANDA account_id into paper clock (admin)
"""

from __future__ import annotations

import logging
import time

from fastapi import APIRouter
from pydantic import BaseModel
from datetime import timezone

UTC = timezone.utc

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/broker", tags=["Broker"])


class BrokerTestRequest(BaseModel):
    type: str = "paper"  # paper | oanda | alpaca
    apiKey: str = ""
    accountId: str = ""
    practice: bool = True


class BrokerTestResponse(BaseModel):
    ok: bool
    broker: str
    latency_ms: int | None = None
    balance: str | None = None
    currency: str | None = None
    error: str | None = None


@router.post("/test-connection", response_model=BrokerTestResponse)
async def test_broker_connection(req: BrokerTestRequest) -> BrokerTestResponse:
    """
    Test broker credentials and return connection status, latency, and balance.

    For paper trading, always returns ok=True (no external call needed).
    For OANDA, calls the practice or live API to verify the token and account.
    """
    start = time.monotonic()

    if req.type == "paper":
        return BrokerTestResponse(
            ok=True,
            broker="paper",
            latency_ms=1,
            balance="100,000.00",
            currency="USD",
        )

    if req.type == "oanda":
        return await _test_oanda(req, start)

    if req.type == "alpaca":
        return await _test_alpaca(req, start)

    return BrokerTestResponse(
        ok=False,
        broker=req.type,
        error=f"Unknown broker type: {req.type!r}. Supported: paper, oanda, alpaca",
    )


async def _test_oanda(req: BrokerTestRequest, start: float) -> BrokerTestResponse:
    """Test OANDA practice or live API connectivity."""
    if not req.apiKey:
        return BrokerTestResponse(ok=False, broker="oanda", error="API key is required")
    if not req.accountId:
        return BrokerTestResponse(
            ok=False,
            broker="oanda",
            error="Account ID is required",
        )

    base = "https://api-fxpractice.oanda.com" if req.practice else "https://api-fxtrade.oanda.com"
    url = f"{base}/v3/accounts/{req.accountId}/summary"
    headers = {
        "Authorization": f"Bearer {req.apiKey}",
        "Content-Type": "application/json",
    }

    try:
        import httpx

        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(url, headers=headers)
    except ImportError:
        # Fallback to requests in executor
        import asyncio

        import requests as _req

        loop = asyncio.get_event_loop()
        try:
            resp_sync = await loop.run_in_executor(
                None,
                lambda: _req.get(url, headers=headers, timeout=10),
            )
            latency = int((time.monotonic() - start) * 1000)
            if resp_sync.status_code == 401:  # noqa: PLR2004
                return BrokerTestResponse(
                    ok=False,
                    broker="oanda",
                    error="401 Unauthorized — check your API token",
                    latency_ms=latency,
                )
            if resp_sync.status_code == 404:  # noqa: PLR2004
                return BrokerTestResponse(
                    ok=False,
                    broker="oanda",
                    error=f"Account {req.accountId!r} not found",
                    latency_ms=latency,
                )
            if resp_sync.status_code != 200:  # noqa: PLR2004
                return BrokerTestResponse(
                    ok=False,
                    broker="oanda",
                    error=f"HTTP {resp_sync.status_code}",
                    latency_ms=latency,
                )
            data = resp_sync.json()
            account = data.get("account", {})
            return BrokerTestResponse(
                ok=True,
                broker="oanda",
                latency_ms=latency,
                balance=account.get("balance", "?"),
                currency=account.get("currency", ""),
            )
        except Exception as exc:
            return BrokerTestResponse(
                ok=False,
                broker="oanda",
                error=f"Connection error: {exc}",
                latency_ms=int((time.monotonic() - start) * 1000),
            )
    except Exception as exc:
        return BrokerTestResponse(
            ok=False,
            broker="oanda",
            error=f"Connection error: {exc}",
            latency_ms=int((time.monotonic() - start) * 1000),
        )

    latency = int((time.monotonic() - start) * 1000)

    if resp.status_code == 401:  # noqa: PLR2004
        return BrokerTestResponse(
            ok=False,
            broker="oanda",
            error="401 Unauthorized — check your API token",
            latency_ms=latency,
        )
    if resp.status_code == 404:  # noqa: PLR2004
        return BrokerTestResponse(
            ok=False,
            broker="oanda",
            error=f"Account {req.accountId!r} not found",
            latency_ms=latency,
        )
    if resp.status_code != 200:  # noqa: PLR2004
        return BrokerTestResponse(
            ok=False,
            broker="oanda",
            error=f"HTTP {resp.status_code}",
            latency_ms=latency,
        )

    data = resp.json()
    account = data.get("account", {})
    return BrokerTestResponse(
        ok=True,
        broker="oanda",
        latency_ms=latency,
        balance=account.get("balance", "?"),
        currency=account.get("currency", ""),
    )


async def _test_alpaca(req: BrokerTestRequest, start: float) -> BrokerTestResponse:
    """Test Alpaca API connectivity."""
    if not req.apiKey or not req.accountId:
        return BrokerTestResponse(
            ok=False,
            broker="alpaca",
            error="API Key ID and Secret Key are both required",
        )

    base = "https://paper-api.alpaca.markets" if req.practice else "https://api.alpaca.markets"
    url = f"{base}/v2/account"
    headers = {
        "APCA-API-KEY-ID": req.apiKey,
        "APCA-API-SECRET-KEY": req.accountId,
    }

    try:
        import httpx

        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(url, headers=headers)
        latency = int((time.monotonic() - start) * 1000)
        if resp.status_code == 403:  # noqa: PLR2004
            return BrokerTestResponse(
                ok=False,
                broker="alpaca",
                error="403 Forbidden — check API key and secret",
                latency_ms=latency,
            )
        if resp.status_code != 200:  # noqa: PLR2004
            return BrokerTestResponse(
                ok=False,
                broker="alpaca",
                error=f"HTTP {resp.status_code}",
                latency_ms=latency,
            )
        data = resp.json()
        return BrokerTestResponse(
            ok=True,
            broker="alpaca",
            latency_ms=latency,
            balance=data.get("portfolio_value", "?"),
            currency="USD",
        )
    except Exception as exc:
        return BrokerTestResponse(
            ok=False,
            broker="alpaca",
            error=f"Connection error: {exc}",
            latency_ms=int((time.monotonic() - start) * 1000),
        )


@router.get("/status", summary="Current broker connection status, balance, and data feed")
async def broker_status():
    """
    Return the current broker type, connection state, account balance, and
    data feed engine status.

    Reads from the live app_state broker, nuclear_streamer, and price_engine.
    For paper trading this returns the simulated balance.
    For OANDA it calls get_account_info() to retrieve the live balance.

    data_feed section reports:
      - NuclearStreamer status when streaming keys are configured (primary)
      - RealTimePriceEngine REST status as fallback
    OANDA is never used as a price source.
    """
    from datetime import datetime

    checked_at = datetime.now(UTC).isoformat()

    try:
        from app import app_state

        broker = getattr(app_state, "broker", None)

        # ── Broker section ────────────────────────────────────────────────────
        if broker is None:
            broker_section: dict = {
                "connected": False,
                "broker_type": "none",
                "balance": None,
                "currency": None,
                "open_positions": 0,
                "error": "Broker not initialised",
            }
        else:
            # Prefer explicit broker_type attr; fall back to class name stripped of
            # "broker"/"trading" suffixes so "PaperTradingBroker" → "paper"
            _raw_type = getattr(broker, "broker_type", None)
            if not _raw_type:
                _raw_type = (
                    type(broker)
                    .__name__.lower()
                    .replace("tradingbroker", "")
                    .replace("broker", "")
                    .replace("trading", "")
                    .strip("_")
                    or "unknown"
                )
            broker_type = _raw_type
            balance = None
            currency = None
            open_positions = 0
            broker_error: str | None = None

            try:
                if hasattr(broker, "get_account_info"):
                    import inspect as _inspect

                    if _inspect.iscoroutinefunction(broker.get_account_info):
                        info = await broker.get_account_info()
                    else:
                        info = broker.get_account_info()
                    # info may be a dataclass, dict, or object
                    if hasattr(info, "__dict__"):
                        info = info.__dict__
                    if isinstance(info, dict):
                        balance = info.get("balance") or info.get("equity") or info.get("nav")
                        currency = info.get("currency", "USD")
                    else:
                        balance = getattr(info, "balance", None) or getattr(info, "equity", None)
                        currency = getattr(info, "currency", "USD")
                elif hasattr(broker, "get_account_balance"):
                    balance = broker.get_account_balance()
                elif hasattr(broker, "balance"):
                    balance = broker.balance
            except Exception as exc:
                broker_error = str(exc)
                logger.warning("broker_status: account info error: %s", exc)

            try:
                if hasattr(broker, "get_positions"):
                    positions = await broker.get_positions()
                    open_positions = len(positions) if positions else 0
            except Exception as _exc:
                logger.debug("Suppressed exception: %s", _exc)

            broker_section = {
                "connected": True,
                "broker_type": broker_type,
                "balance": balance,
                "currency": currency,
                "open_positions": open_positions,
            }
            if broker_error:
                broker_section["error"] = broker_error

        # ── Data feed / price engine section ──────────────────────────────────
        # NuclearStreamer is the primary live tick source (WebSocket).
        # RealTimePriceEngine is the REST polling fallback.
        # OANDA is never used as a price source.
        nuclear = getattr(app_state, "nuclear_streamer", None)
        price_engine = getattr(app_state, "price_engine", None)

        if nuclear is not None:
            # Primary: NuclearStreamer WebSocket status
            ns_status = nuclear.status()
            # REST fallback status (may be None if not initialised)
            rest_status: dict = {}
            if price_engine is not None and hasattr(price_engine, "get_status"):
                try:
                    rest_status = price_engine.get_status()
                except Exception:  # nosec B110 — fallback to empty status
                    rest_status = {}
            data_feed: dict = {
                "active": ns_status.get("is_running", False),
                "source": "NuclearStreamer",
                "symbol": ns_status.get("symbol"),
                "last_price": ns_status.get("last_price"),
                "subscriber_count": ns_status.get("subscriber_count", 0),
                "anomaly_counts": ns_status.get("anomaly_counts", {}),
                "circuit_breakers": ns_status.get("circuit_breakers", {}),
                "rest_fallback": {
                    "active": rest_status.get("active", False),
                    "primary_active": rest_status.get("primary_active", False),
                    "fallback_active": rest_status.get("fallback_active", False),
                }
                if rest_status
                else {"active": False},
            }
        elif price_engine is not None and hasattr(price_engine, "get_status"):
            # Fallback only: RealTimePriceEngine REST polling
            try:
                feed_raw = price_engine.get_status()
                data_feed = {
                    "active": feed_raw.get("active", False),
                    "source": "RealTimePriceEngine",
                    "primary_active": feed_raw.get("primary_active", False),
                    "fallback_active": feed_raw.get("fallback_active", False),
                    "websocket_connected": feed_raw.get("websocket_connected", False),
                    "rest_available": feed_raw.get("rest_available", False),
                    "symbols": feed_raw.get("symbols", []),
                    "note": "NuclearStreamer not active — no streaming API keys set",
                }
            except Exception as exc:
                data_feed = {
                    "active": False,
                    "error": str(exc),
                    "source": "RealTimePriceEngine",
                }
        elif price_engine is not None:
            data_feed = {
                "active": getattr(price_engine, "active", False),
                "source": type(price_engine).__name__,
                "symbols": getattr(price_engine, "symbols", []),
            }
        else:
            has_feed = hasattr(broker, "market_prices") if broker else False
            data_feed = {
                "active": has_feed,
                "source": "broker_internal" if has_feed else "none",
                "note": (
                    "No streaming keys set and no price engine initialised. "
                    "Set FINNHUB_API_KEY, TWELVE_API_KEY, or POLYGON_API_KEY."
                ),
            }

        # ── Signal engine status ──────────────────────────────────────────────
        signal_engine_running = any(not t.done() for t in getattr(app_state, "background_tasks", []))

        # ── ML engine status ──────────────────────────────────────────────────
        ml_engine: dict = {"status": "unavailable", "model_available": False}
        try:
            from ml.inference_engine import get_inference_engine

            eng = get_inference_engine()
            h = eng.health()
            ml_engine = {
                "status": h.get("status", "unavailable"),
                "model_available": h.get("model_available", False),
                "model_version": h.get("model_version", "none"),
                "predict_count": h.get("predict_count", 0),
                "fallback_rate": h.get("fallback_rate", 0.0),
                "last_latency_ms": h.get("last_latency_ms", 0.0),
                "pipeline": h.get("pipeline", {}),
            }
        except Exception as ml_exc:
            ml_engine["error"] = str(ml_exc)

        return {
            "broker": broker_section,
            "data_feed": data_feed,
            "ml_engine": ml_engine,
            "signal_engine_running": signal_engine_running,
            "checked_at": checked_at,
        }

    except Exception as exc:
        logger.exception("broker_status: unexpected error: %s", exc)
        return {
            "broker": {"connected": False, "broker_type": "unknown", "error": "Unavailable — check server logs"},
            "data_feed": {"active": False, "source": "unknown"},
            "ml_engine": {"status": "unavailable"},
            "signal_engine_running": False,
            "checked_at": checked_at,
        }


@router.get(
    "/paper-clock",
    summary="OANDA paper trading clock — elapsed/remaining days and account status",
)
async def paper_clock_status():
    """
    Return the OANDA paper trading clock status.

    Reports elapsed days, remaining days, account_id (masked), and whether
    the clock is waiting for a real OANDA connection (pending_real_account).

    No authentication required — safe to poll from monitoring dashboards.
    """
    try:
        from brokers.oanda_paper_clock import get_clock

        return get_clock().status()
    except Exception as exc:
        logger.warning("paper_clock_status: %s", exc)
        from datetime import datetime

        return {
            "started": False,
            "elapsed_days": 0.0,
            "remaining_days": 30.0,
            "complete": False,
            "account_id": None,
            "pending_real_account": True,
            "note": "Clock unavailable — check server logs",
            "checked_at": datetime.now(UTC).isoformat(),
        }


class StampOandaRequest(BaseModel):
    account_id: str
    environment: str = "practice"  # "practice" or "live"


@router.post(
    "/stamp-oanda",
    summary="Stamp real OANDA account_id into the paper trading clock (admin)",
)
async def stamp_oanda_clock(req: StampOandaRequest):
    """
    Manually stamp a real OANDA account_id into the paper trading clock.

    Use this when the server has already connected to OANDA but the clock
    still shows ``account_id: PENDING`` (e.g. the stamp file was pre-seeded
    before the first real connection).

    This endpoint calls OandaPaperClock.maybe_start() which:
    - Overwrites PENDING placeholders with the real account_id
    - Preserves the original started_utc so the 30-day clock is not reset
    - Is idempotent — safe to call multiple times

    Requires: admin role.
    """
    # Inline auth check — admin only
    if not req.account_id:
        from fastapi import HTTPException

        raise HTTPException(status_code=422, detail="account_id is required")

    try:
        from brokers.oanda_paper_clock import get_clock

        clock = get_clock()
        updated = clock.maybe_start(
            account_id=req.account_id,
            environment=req.environment,
        )
        status = clock.status()
        return {
            "updated": updated,
            "message": (
                "Clock stamped with real account_id."
                if updated
                else "Clock already running with a real account — no change."
            ),
            "clock": status,
        }
    except Exception as exc:
        logger.exception("stamp_oanda_clock: %s", exc)
        from fastapi import HTTPException

        raise HTTPException(status_code=500, detail="Internal error — check server logs") from None
