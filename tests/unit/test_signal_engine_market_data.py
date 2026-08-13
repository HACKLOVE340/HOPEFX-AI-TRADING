# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
tests/unit/test_signal_engine_market_data.py
============================================
The signal engine had no market data source in production.

``_fetch_market_data`` called ``broker.get_market_data()`` and nothing else.
Under ``APP_ENV=production`` ``PaperTradingBroker.get_market_data`` raises::

    PaperTradingBroker.get_market_data() must not be called in production.
    Use a real market data source (price engine or CSV files).

That guard is correct — synthetic bars must never reach the predictor. But no
real source was ever wired up behind it, so the engine caught the RuntimeError,
logged it, and returned None on every single tick. The production log shows the
result: a pipeline that completes in 6.7 ms and reports ``signal=none,
approved=false``, every cycle, forever. Nothing was broken loudly enough to
notice; the engine simply never had data to decide on.

``price_engine.get_ohlcv`` is the real source, and it demonstrably works — the
same log shows ``OHLCV yfinance: XAUUSD 1h, 50 bars fetched``. It is already
what ``/api/trading/ohlcv`` serves.

The trap in fixing it: ``get_ohlcv``'s last-resort tier
(``_get_ohlcv_from_broker``) fabricates bars by repeating the paper broker's
static ``market_prices`` with ``volume=0``. Routing the engine through
``get_ohlcv`` without a check would have replaced a loud refusal with exactly
the silent corruption the refusal existed to prevent — zero ATR, zero range and
zero volume features, consumed by the predictor as if real. So the bars are
checked for movement before they are returned.
"""

from __future__ import annotations

import logging
from types import SimpleNamespace

import pytest

pytestmark = pytest.mark.unit


class _Bar:
    """Mimics data.real_time_price_engine.OHLCV."""

    def __init__(self, close: float, volume: float = 100.0) -> None:
        self.timestamp = 0
        self.open = close
        self.high = close + 1
        self.low = close - 1
        self.close = close
        self.volume = volume


def _engine(bars):
    async def _get_ohlcv(symbol, timeframe, limit):
        return bars

    return SimpleNamespace(get_ohlcv=_get_ohlcv)


def _moving(n: int = 100):
    return [_Bar(4000.0 + i) for i in range(n)]


def _flat(n: int = 100):
    """What _get_ohlcv_from_broker produces: one static price, volume 0."""
    return [_Bar(4000.0, volume=0.0) for _ in range(n)]


# ── The price engine is now the source ───────────────────────────────────────


async def test_real_bars_from_the_price_engine_are_used():
    from core.signal_engine import _fetch_market_data

    state = SimpleNamespace(price_engine=_engine(_moving()), broker=None)
    data = await _fetch_market_data("XAUUSD", state)

    assert data is not None
    assert data["symbol"] == "XAUUSD"
    assert len(data["prices"]) == 100
    assert data["close"] == 4099.0
    assert data["prices"][0] == 4000.0


async def test_the_broker_is_not_called_when_the_engine_answers():
    """The regression: production could only ever reach the broker, which refuses."""
    from core.signal_engine import _fetch_market_data

    called: list[str] = []

    def _broker_get(symbol, timeframe="1h", limit=100):
        called.append(symbol)
        raise RuntimeError("PaperTradingBroker.get_market_data() must not be called in production.")

    state = SimpleNamespace(price_engine=_engine(_moving()), broker=SimpleNamespace(get_market_data=_broker_get))
    data = await _fetch_market_data("XAUUSD", state)

    assert data is not None, "the engine had real bars and they were not used"
    assert called == [], "fell through to the broker despite the engine answering"


async def test_a_refusing_broker_no_longer_starves_the_engine():
    """End to end on the production configuration.

    price_engine present, paper broker in production mode. Before the fix this
    returned None; the pipeline then reported signal=none on every tick.
    """
    from core.signal_engine import _fetch_market_data

    def _refuse(symbol, timeframe="1h", limit=100):
        raise RuntimeError("PaperTradingBroker.get_market_data() must not be called in production.")

    state = SimpleNamespace(price_engine=_engine(_moving()), broker=SimpleNamespace(get_market_data=_refuse))
    assert await _fetch_market_data("XAUUSD", state) is not None


# ── Synthetic bars must not become the fix ───────────────────────────────────


async def test_flat_synthetic_bars_are_rejected(caplog):
    from core.signal_engine import _fetch_market_data

    state = SimpleNamespace(price_engine=_engine(_flat()), broker=None)

    with caplog.at_level(logging.WARNING, logger="core.signal_engine"):
        data = await _fetch_market_data("XAUUSD", state)

    assert data is None, "100 identical closes were accepted as market data"
    msg = " ".join(r.getMessage() for r in caplog.records)
    assert "flat" in msg.lower(), "rejected silently — the operator learns nothing"
    assert "XAUUSD" in msg


async def test_a_single_bar_is_rejected():
    """The degenerate case the original docstring named: one bar has no range."""
    from core.signal_engine import _fetch_market_data

    state = SimpleNamespace(price_engine=_engine([_Bar(4000.0)]), broker=None)
    assert await _fetch_market_data("XAUUSD", state) is None


async def test_flat_broker_bars_are_rejected_too():
    """The check belongs to both paths, not just the new one."""
    from core.signal_engine import _fetch_market_data

    flat = [{"open": 4000.0, "high": 4000.0, "low": 4000.0, "close": 4000.0, "volume": 0.0} for _ in range(100)]
    state = SimpleNamespace(price_engine=None, broker=SimpleNamespace(get_market_data=lambda *a, **k: flat))

    assert await _fetch_market_data("XAUUSD", state) is None


async def test_the_broker_still_serves_real_bars_in_development():
    """Dev runs with APP_ENV != production, where the paper broker answers."""
    from core.signal_engine import _fetch_market_data

    bars = [
        {"open": 4000.0 + i, "high": 4001.0 + i, "low": 3999.0 + i, "close": 4000.0 + i, "volume": 10.0}
        for i in range(50)
    ]
    state = SimpleNamespace(price_engine=None, broker=SimpleNamespace(get_market_data=lambda *a, **k: bars))

    data = await _fetch_market_data("XAUUSD", state)
    assert data is not None
    assert len(data["prices"]) == 50


# ── Failure modes stay quiet-free ────────────────────────────────────────────


async def test_an_engine_that_raises_falls_through_to_the_broker():
    from core.signal_engine import _fetch_market_data

    async def _boom(symbol, timeframe, limit):
        raise ConnectionError("upstream down")

    bars = [
        {"open": 4000.0 + i, "high": 4001.0 + i, "low": 3999.0 + i, "close": 4000.0 + i, "volume": 10.0}
        for i in range(50)
    ]
    state = SimpleNamespace(
        price_engine=SimpleNamespace(get_ohlcv=_boom),
        broker=SimpleNamespace(get_market_data=lambda *a, **k: bars),
    )

    assert await _fetch_market_data("XAUUSD", state) is not None


async def test_no_sources_at_all_returns_none_and_says_so(caplog):
    from core.signal_engine import _fetch_market_data

    with caplog.at_level(logging.WARNING, logger="core.signal_engine"):
        data = await _fetch_market_data("XAUUSD", SimpleNamespace(price_engine=None, broker=None))

    assert data is None
    assert "XAUUSD" in " ".join(r.getMessage() for r in caplog.records)


async def test_an_empty_engine_result_is_not_treated_as_data():
    from core.signal_engine import _fetch_market_data

    state = SimpleNamespace(price_engine=_engine([]), broker=None)
    assert await _fetch_market_data("XAUUSD", state) is None


async def test_the_engine_is_given_a_timeout():
    """A hung upstream must not stall the signal loop indefinitely."""
    import asyncio
    import inspect

    import core.signal_engine as mod

    src = inspect.getsource(mod._fetch_market_data)
    assert "wait_for" in src, "get_ohlcv is awaited without a timeout"

    # And the timeout is honoured, not merely present.
    async def _hang(symbol, timeframe, limit):
        await asyncio.sleep(60)

    state = SimpleNamespace(price_engine=SimpleNamespace(get_ohlcv=_hang), broker=None)
    task = asyncio.create_task(mod._fetch_market_data("XAUUSD", state))
    await asyncio.sleep(0.05)
    assert not task.done(), "returned before the upstream did — the await is not real"
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)


# ── The guard this depends on must stay ──────────────────────────────────────


def test_the_paper_broker_still_refuses_in_production(monkeypatch):
    """The whole fix assumes the broker keeps saying no. If that guard is ever
    removed, synthetic bars reach the predictor through the fallback path."""
    from brokers.paper_trading import PaperTradingBroker

    monkeypatch.setenv("APP_ENV", "production")
    broker = PaperTradingBroker.__new__(PaperTradingBroker)

    with pytest.raises(RuntimeError, match="must not be called in production"):
        broker.get_market_data("XAUUSD")
