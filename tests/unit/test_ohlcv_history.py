"""Tests for the deep-history CSV fallback behind /api/trading/ohlcv.

Locks in the fix that lets daily/weekly gold charts render decades of
history (back past 2000) when the live price engine and yfinance are
unavailable, instead of returning a blank 503.
"""

import datetime as dt

from api.trading import _load_gold_history_csv


def test_daily_history_reaches_back_decades():
    bars = _load_gold_history_csv("1d", 8000)
    assert len(bars) > 1000
    first = dt.datetime.fromtimestamp(bars[0]["timestamp"], tz=dt.timezone.utc).year
    assert first <= 2000, f"expected daily history before 2000, got {first}"
    # Bars carry full OHLCV and are chronologically ordered.
    assert {"timestamp", "open", "high", "low", "close", "volume"} <= bars[0].keys()
    assert bars[0]["timestamp"] < bars[-1]["timestamp"]


def test_weekly_resample_returns_bars():
    bars = _load_gold_history_csv("1w", 2000)
    assert len(bars) > 100
    assert bars[0]["timestamp"] < bars[-1]["timestamp"]


def test_intraday_returns_empty():
    # CSV is daily granularity — intraday must fall through to other feeds.
    assert _load_gold_history_csv("1h", 500) == []
    assert _load_gold_history_csv("5m", 500) == []


def test_limit_is_respected():
    assert len(_load_gold_history_csv("1d", 50)) == 50
