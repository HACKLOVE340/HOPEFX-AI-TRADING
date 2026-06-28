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
            self.headers = {}  # no Origin → origin check allows (JWT still gates)

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


# ── WS origin check (defense-in-depth against cross-site WS) ──────────────────────
def _fake_ws(origin=None, host="app.hopefx.io", allowed=None):
    class _State:
        allowed_origins = allowed if allowed is not None else []

    class _App:
        state = _State()

    class _WS:
        app = _App()
        headers = {}

    ws = _WS()
    h = {}
    if origin is not None:
        h["origin"] = origin
    if host is not None:
        h["host"] = host
    ws.headers = h
    return ws


def test_ws_origin_allowed_logic():
    from api import ws_live

    allow = ["https://app.hopefx.io"]
    # Allow-listed origin
    assert ws_live._ws_origin_allowed(_fake_ws(origin="https://app.hopefx.io", allowed=allow)) is True
    # Cross-site origin → rejected
    assert ws_live._ws_origin_allowed(_fake_ws(origin="https://evil.example", allowed=allow)) is False
    # Missing Origin (non-browser client) → allowed (JWT still gates)
    assert ws_live._ws_origin_allowed(_fake_ws(origin=None, allowed=allow)) is True
    # Same-origin (Origin host == Host) even if not explicitly listed
    assert ws_live._ws_origin_allowed(_fake_ws(origin="https://app.hopefx.io", host="app.hopefx.io", allowed=[])) is True
    # No allow-list configured → don't block (dev safety)
    assert ws_live._ws_origin_allowed(_fake_ws(origin="https://anything.example", allowed=[])) is True


# ── BUG D: poll loop tolerates a scalar get_price() return ───────────────────────
def _engine_with_broker(broker):
    """Build a HOPEFXEngine shell wired to *broker* without running __init__."""
    from hopefx_engine import HopeFXEngine

    eng = HopeFXEngine.__new__(HopeFXEngine)
    eng._broker = broker
    eng._ticks = []

    async def _capture(symbol, bid, ask, mid):
        eng._ticks.append((symbol, bid, ask, mid))

    eng._on_tick = _capture  # type: ignore[method-assign]
    return eng


def test_poll_symbol_handles_scalar_price():
    """get_price() returning a float (e.g. MultiSourceFeed) must not crash with
    "'float' object has no attribute 'get'"."""

    class _ScalarBroker:
        def get_price(self, symbol):
            return 1.1390  # a bare float, not a dict

    eng = _engine_with_broker(_ScalarBroker())
    asyncio.run(eng._poll_symbol("EUR_USD"))
    assert eng._ticks == [("EUR/USD", 1.1390, 1.1390, 1.1390)]


def test_poll_symbol_handles_dict_price():
    class _DictBroker:
        def get_price(self, symbol):
            return {"bid": 1.10, "ask": 1.12}

    eng = _engine_with_broker(_DictBroker())
    asyncio.run(eng._poll_symbol("EUR_USD"))
    assert eng._ticks[0][0] == "EUR/USD"
    assert eng._ticks[0][3] == pytest.approx(1.11)  # mid


def test_poll_symbol_ignores_zero_and_none():
    class _NoneBroker:
        def get_price(self, symbol):
            return None

    eng = _engine_with_broker(_NoneBroker())
    asyncio.run(eng._poll_symbol("EUR_USD"))
    assert eng._ticks == []  # nothing emitted, no crash


# ── BUG E: streamer clamps a future-dated / mis-parsed timestamp ─────────────────
def _minimal_streamer():
    from data_feed.nuclear_streamer import NuclearStreamer

    s = NuclearStreamer.__new__(NuclearStreamer)
    s.symbol = "XAUUSD"
    s.anomaly_jump_pct = 5.0
    s._dedup_cache = {}
    s._dedup_counts = {}
    s._last_seq = {}
    s._seq_gap_counts = {}
    s._latency_samples = {}
    s._latency_samples_max = 100
    s._price_lock = asyncio.Lock()
    s._last_price = None
    s._anomaly_counts = {}
    s._source_prices = {}
    s._consensus_reject_count = 0
    s._redis = None
    s._redis_publish_errors = 0
    s._subscribers = []
    return s


def test_streamer_clamps_future_timestamp():
    import time

    s = _minimal_streamer()
    future_ts = time.time() + 8 * 3600  # 8h ahead — what the tz-naive bug produced
    asyncio.run(s.process_tick(price=4080.0, event_ts=future_ts, source="twelvedata"))

    # The tick is still published (single source → graceful degradation), and the
    # recorded latency is clamped to a non-negative value rather than a huge
    # negative number.
    samples = s._latency_samples.get("twelvedata", [])
    assert samples, "future-dated tick should not be discarded"
    assert all(v >= 0 for v in samples), f"negative latency leaked: {samples}"


# ── BUG F: MultiSourceFeed suppresses repeated stale-rotation warnings ────────────
def test_symbol_state_stale_warning_is_suppressed_then_rearmed():
    from data_feed.multi_source_feed import _SymbolState

    st = _SymbolState("XAUUSD", price_min=1000.0, price_max=10000.0, history_size=10)
    assert st.stale_warned is False
    # Simulate the health monitor flagging it stale: first time warns, then latches.
    st.stale_warned = True
    assert st.stale_warned is True
    # A successful update re-arms the warning so the next stale spell logs once more.
    st.record_success(st.active_source, 4080.0)
    assert st.stale_warned is False
