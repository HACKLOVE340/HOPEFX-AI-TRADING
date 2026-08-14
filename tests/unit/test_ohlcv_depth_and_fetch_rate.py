# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
tests/unit/test_ohlcv_depth_and_fetch_rate.py
=============================================
Deeper charts, and not hammering yfinance to get them.

The deployed logs showed, repeatedly and within the same second::

    OHLCV yfinance: XAUUSD 1h — 50 bars fetched
    OHLCV yfinance: EURUSD 1h — 50 bars fetched
    OHLCV yfinance: XAUUSD 1h — 100 bars fetched

Two separate problems.

**Depth.** The 1h period was ``"60d"``, about 1,440 bars at best and far fewer
for instruments that only trade in session hours — so the chart was capped no
matter how large a ``limit`` the caller passed. yfinance serves 1h back to 730
days, which is ~17,500 bars continuous.

**Rate.** ``_get_ohlcv_yfinance`` had no cache at all, and the Coinbase feed's
cache keys on ``f"{symbol}_{timeframe}_{limit}"`` — so a caller asking for 50
bars and another asking for 100 were separate entries and separate upstream
fetches. That is why the same series appears twice a second above. Pulling
2,000+ bars per call would have made it considerably worse.

The cache is now keyed by symbol and timeframe only, at full depth, with the
tail sliced on the way out, and its TTL scaled to the bar it serves: refetching
a 1h candle every 5 seconds buys nothing.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.unit


def test_one_hour_period_allows_more_than_two_thousand_bars():
    """`60d` capped 1h at ~1,440 regardless of the requested limit."""
    import inspect

    from data.real_time_price_engine import RealTimePriceEngine

    src = inspect.getsource(RealTimePriceEngine._get_ohlcv_yfinance)
    assert '"1h": "60d"' not in src, "1h is still capped at 60 days (~1,440 bars)"
    assert '"1h": "730d"' in src, "1h period does not reach yfinance's 730-day maximum"


def test_the_cache_is_not_keyed_by_limit():
    """Keying on limit made every distinct depth its own upstream fetch."""
    import inspect

    from data.real_time_price_engine import RealTimePriceEngine

    src = inspect.getsource(RealTimePriceEngine._get_ohlcv_yfinance)
    assert 'f"{symbol}:{timeframe}"' in src, "the yfinance cache key still varies with limit"


def test_ttl_is_scaled_to_the_bar_not_a_flat_five_seconds():
    from data.real_time_price_engine import _YF_CACHE_TTL

    assert _YF_CACHE_TTL["1h"] >= 300, "a 1h bar does not need refetching every few minutes"
    assert _YF_CACHE_TTL["1m"] <= 60, "a 1m bar must still refresh promptly"
    # Monotonic: a longer bar is never refreshed more often than a shorter one.
    order = ["1m", "5m", "15m", "30m", "1h", "4h", "1d"]
    ttls = [_YF_CACHE_TTL[k] for k in order]
    assert ttls == sorted(ttls), f"TTLs are not monotonic in timeframe: {dict(zip(order, ttls, strict=True))}"


async def test_a_second_call_at_a_different_depth_does_not_refetch(monkeypatch):
    """The exact deployed pattern: 50 bars then 100 bars, same series."""
    import time

    import data.real_time_price_engine as rtp
    from data.real_time_price_engine import OHLCV, RealTimePriceEngine

    bars = [OHLCV(timestamp=i, open=1, high=2, low=0, close=1.5, volume=10) for i in range(2000)]
    rtp._YF_CACHE.clear()
    rtp._YF_CACHE["XAUUSD:1h"] = (time.time(), bars)

    feed = RealTimePriceEngine.__new__(RealTimePriceEngine)

    fifty = await RealTimePriceEngine._get_ohlcv_yfinance(feed, "XAUUSD", "1h", 50)
    hundred = await RealTimePriceEngine._get_ohlcv_yfinance(feed, "XAUUSD", "1h", 100)

    assert len(fifty) == 50
    assert len(hundred) == 100
    # Both served from one cached fetch, and both from the newest end.
    assert fifty[-1].timestamp == bars[-1].timestamp
    assert hundred[-1].timestamp == bars[-1].timestamp
    rtp._YF_CACHE.clear()


async def test_an_expired_entry_is_not_served(monkeypatch):
    """Control — the cache must expire, or the chart freezes."""
    import time

    import data.real_time_price_engine as rtp
    from data.real_time_price_engine import OHLCV, RealTimePriceEngine

    rtp._YF_CACHE.clear()
    rtp._YF_CACHE["XAUUSD:1h"] = (
        time.time() - rtp._YF_CACHE_TTL["1h"] - 1,
        [OHLCV(timestamp=1, open=1, high=1, low=1, close=1, volume=0)],
    )

    feed = RealTimePriceEngine.__new__(RealTimePriceEngine)
    feed._YF_TICKER_MAP = {}
    feed._YF_INTERVAL_MAP = {}

    # Expired: falls through to a real fetch, which fails closed in this
    # environment (no network / no yfinance) and returns [].
    result = await RealTimePriceEngine._get_ohlcv_yfinance(feed, "XAUUSD", "1h", 50)
    assert result == [] or len(result) > 1, "an expired entry was served from cache"
    rtp._YF_CACHE.clear()
