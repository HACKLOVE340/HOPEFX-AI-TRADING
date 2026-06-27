# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# AGPL-3.0 — Share all modifications
"""Regression tests for runtime bugs surfaced by live-engine logs.

Each test pins a specific crash that was observed at runtime:

* BUG A — ``MarketDataCache.__init__() got an unexpected keyword argument 'ssl'``
          (startup TLS factory passed ssl/ssl_context the cache didn't accept).
* BUG B — ``ws_audit_events`` raised a WebSocketDisconnect ASGI traceback when the
          client hung up during the initial handshake send.
* BUG C — ``TradeRepository() takes no arguments`` + ``get_by_user`` called with no
          session and unsupported kwargs from api/performance.py.
"""

from __future__ import annotations

import asyncio
import ssl

import pytest

pytestmark = pytest.mark.unit


# ── BUG A: MarketDataCache TLS kwargs ────────────────────────────────────────────
def test_market_data_cache_accepts_ssl_kwargs():
    from cache.market_data_cache import MarketDataCache

    # Must not raise; with no Redis it degrades to the in-memory fallback.
    c = MarketDataCache(ssl=True, ssl_cert_reqs="required", max_retries=1, enable_fallback=True)
    assert c.ssl is True
    k = c._client_kwargs()
    assert k["ssl"] is True and k["ssl_cert_reqs"] == "required"


def test_market_data_cache_accepts_ssl_context_for_back_compat():
    from cache.market_data_cache import MarketDataCache

    ctx = ssl.create_default_context()
    c = MarketDataCache(ssl=True, ssl_context=ctx, max_retries=1, enable_fallback=True)
    # ssl_context implies TLS on; the object itself is not forwarded (redis-py 8.x
    # only accepts individual ssl_* params), so it must not appear in client kwargs.
    assert c.ssl is True
    assert "ssl_context" not in c._client_kwargs()


def test_market_data_cache_no_ssl_by_default():
    from cache.market_data_cache import MarketDataCache

    c = MarketDataCache(max_retries=1, enable_fallback=True)
    assert c.ssl is False
    assert "ssl" not in c._client_kwargs()


# ── BUG C: stateless TradeRepository + platform-wide queries ─────────────────────
def test_trade_repository_is_stateless_and_queries_work():
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from database.models import Base, TradeStatus
    from database.repositories.trade_repository import TradeRepository

    async def _run():
        eng = create_async_engine("sqlite+aiosqlite:///:memory:")
        async with eng.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        Session = async_sessionmaker(eng, expire_on_commit=False)

        repo = TradeRepository()  # stateless — no session in the constructor
        async with Session() as s:
            await repo.create(s, trade_id="t1", symbol="XAUUSD", user_id="u1", status=TradeStatus.CLOSED)
            await repo.create(s, trade_id="t2", symbol="XAUUSD", user_id="u2", status=TradeStatus.OPEN)
            await s.commit()

            closed = await repo.get_recent(s, status="closed", limit=100)
            everything = await repo.get_recent(s, limit=100)
            n_closed = await repo.count_by_status(s, status="closed")

        await eng.dispose()
        return len(closed), len(everything), n_closed

    n_closed, n_all, count_closed = asyncio.run(_run())
    assert n_closed == 1
    assert n_all == 2
    assert count_closed == 1


def test_coerce_status_accepts_string_and_enum():
    from database.models import TradeStatus
    from database.repositories.trade_repository import TradeRepository

    assert TradeRepository._coerce_status("closed") is TradeStatus.CLOSED
    assert TradeRepository._coerce_status(TradeStatus.OPEN) is TradeStatus.OPEN
    assert TradeRepository._coerce_status(None) is None
    assert TradeRepository._coerce_status("not-a-status") is None  # tolerated, no crash


# ── BUG B: ws_audit_events tolerates a handshake-time disconnect ─────────────────
def test_ws_audit_events_handles_handshake_disconnect():
    from fastapi import WebSocketDisconnect

    from api import ws_live

    class _DisconnectingWS:
        """A WebSocket whose first send_text fails as if the client hung up."""

        def __init__(self):
            self.accepted = False
            self.closed = False

        async def accept(self):
            self.accepted = True

        async def send_text(self, _data):
            raise WebSocketDisconnect(code=1006)

        async def close(self, code=1000, reason=""):
            self.closed = True

    ws = _DisconnectingWS()
    # Must return cleanly (no WebSocketDisconnect propagating out of the handler).
    asyncio.run(ws_live.ws_audit_events(ws))
    assert ws.accepted is True
