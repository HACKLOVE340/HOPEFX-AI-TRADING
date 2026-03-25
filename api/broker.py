"""
api/broker.py
=============
Broker management endpoints.

Routes
------
POST /api/broker/test-connection  — test broker credentials and return latency + balance
GET  /api/broker/status           — current broker type and connection state
"""

from __future__ import annotations

import logging
import time
from typing import Optional

from fastapi import APIRouter
from pydantic import BaseModel

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
    latency_ms: Optional[int] = None
    balance: Optional[str] = None
    currency: Optional[str] = None
    error: Optional[str] = None


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
            ok=False, broker="oanda", error="Account ID is required"
        )

    base = (
        "https://api-fxpractice.oanda.com"
        if req.practice
        else "https://api-fxtrade.oanda.com"
    )
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
            if resp_sync.status_code == 401:
                return BrokerTestResponse(
                    ok=False,
                    broker="oanda",
                    error="401 Unauthorized — check your API token",
                    latency_ms=latency,
                )
            if resp_sync.status_code == 404:
                return BrokerTestResponse(
                    ok=False,
                    broker="oanda",
                    error=f"Account {req.accountId!r} not found",
                    latency_ms=latency,
                )
            if resp_sync.status_code != 200:
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

    if resp.status_code == 401:
        return BrokerTestResponse(
            ok=False,
            broker="oanda",
            error="401 Unauthorized — check your API token",
            latency_ms=latency,
        )
    if resp.status_code == 404:
        return BrokerTestResponse(
            ok=False,
            broker="oanda",
            error=f"Account {req.accountId!r} not found",
            latency_ms=latency,
        )
    if resp.status_code != 200:
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

    base = (
        "https://paper-api.alpaca.markets"
        if req.practice
        else "https://api.alpaca.markets"
    )
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
        if resp.status_code == 403:
            return BrokerTestResponse(
                ok=False,
                broker="alpaca",
                error="403 Forbidden — check API key and secret",
                latency_ms=latency,
            )
        if resp.status_code != 200:
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


@router.get("/status", summary="Current broker connection status")
async def broker_status():
    """Return the current broker type and connection state."""
    try:
        from app import app_state  # noqa: PLC0415

        broker = getattr(app_state, "broker", None)
        if broker is None:
            return {"connected": False, "broker_type": "none", "balance": None}

        broker_type = getattr(broker, "broker_type", type(broker).__name__.lower())
        balance = None
        try:
            if hasattr(broker, "get_account_balance"):
                balance = broker.get_account_balance()
            elif hasattr(broker, "balance"):
                balance = broker.balance
        except Exception as exc:
            logger.warning("Could not retrieve broker balance: %s", exc)

        return {
            "connected": True,
            "broker_type": broker_type,
            "balance": balance,
        }
    except Exception as exc:
        return {"connected": False, "broker_type": "unknown", "error": str(exc)}
