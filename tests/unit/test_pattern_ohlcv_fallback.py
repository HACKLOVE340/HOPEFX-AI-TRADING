# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
tests/unit/test_pattern_ohlcv_fallback.py
=========================================
`/patterns` and `/levels` must have the same data fallbacks as `/ohlcv`.

Both endpoints source bars through ``_get_ohlcv_for_symbol``, which asked the
price engine and nothing else — returning ``[]`` on any miss. ``/ohlcv`` has a
full chain (price engine, yfinance, bundled gold CSV, then an explicit 503),
but these two never used it.

The visible result was worse than an empty page. With no bars the endpoint
returns ``{"patterns": [], "note": "No OHLCV data available..."}``, and
PatternDetector.tsx rendered only *"No patterns detected above 50% confidence"*
— a confident negative finding, for a scan that never ran.

Symbol form matters here: callers arrive via ``_normalise_symbol`` in OANDA
style (``XAU_USD``) while ``_yf_ticker_map`` is keyed on the compact form from
config/multi_source_feed.yaml (``XAUUSD``). Passing the OANDA form straight
through misses every entry and silently disables the fallback again.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.unit


@pytest.fixture
def no_price_engine(monkeypatch):
    """app_state with no price engine — forces the fallback path."""
    from core.app_state import app_state

    monkeypatch.setattr(app_state, "price_engine", None, raising=False)


async def test_falls_back_to_yfinance_when_the_price_engine_has_nothing(monkeypatch, no_price_engine):
    from api import trading

    captured: dict = {}

    class _FakeTicker:
        def __init__(self, sym):
            captured["ticker"] = sym

        def history(self, **kw):
            import pandas as pd

            idx = pd.date_range("2026-01-01", periods=30, freq="h", tz="UTC")
            return pd.DataFrame(
                {"Open": 1.0, "High": 1.1, "Low": 0.9, "Close": 1.05, "Volume": 10.0},
                index=idx,
            )

    monkeypatch.setitem(__import__("sys").modules, "yfinance", type("M", (), {"Ticker": _FakeTicker}))

    bars = await trading._get_ohlcv_for_symbol("EUR_USD", "1h", 200)

    assert bars, "no bars returned — the fallback did not run"
    assert len(bars) == 30
    assert {"timestamp", "open", "high", "low", "close", "volume"} <= set(bars[0])


async def test_the_ticker_lookup_uses_the_compact_form(monkeypatch, no_price_engine):
    """OANDA-form in, compact-form lookup — otherwise every entry misses."""
    from api import trading

    seen: dict = {}

    class _FakeTicker:
        def __init__(self, sym):
            seen["ticker"] = sym

        def history(self, **kw):
            import pandas as pd

            return pd.DataFrame()

    monkeypatch.setitem(__import__("sys").modules, "yfinance", type("M", (), {"Ticker": _FakeTicker}))

    await trading._get_ohlcv_for_symbol("EUR_USD", "1h", 200)

    # EURUSD maps to EURUSD=X in the feed config; the OANDA form would not.
    assert seen.get("ticker") == trading._yf_ticker_map().get("EURUSD", "EURUSD")


async def test_gold_falls_through_to_the_bundled_csv(monkeypatch, no_price_engine):
    """The last real source, matching /ohlcv."""
    from api import trading

    monkeypatch.setattr(trading, "_yf_ticker_map", lambda: {"XAUUSD": ""})
    monkeypatch.setattr(trading, "_load_gold_history_csv", lambda tf, lim: [{"timestamp": 1, "close": 4000.0}])

    bars = await trading._get_ohlcv_for_symbol("XAU_USD", "1d", 200)

    assert bars == [{"timestamp": 1, "close": 4000.0}]


async def test_a_symbol_with_no_source_at_all_returns_empty(monkeypatch, no_price_engine):
    """Still honest when nothing can serve it — no fabricated bars."""
    from api import trading

    monkeypatch.setattr(trading, "_yf_ticker_map", lambda: {"XPTUSD": ""})

    assert await trading._get_ohlcv_for_symbol("XPT_USD", "1h", 200) == []


async def test_the_price_engine_still_wins_when_it_has_data(monkeypatch):
    """The fallback must not displace the live source."""
    from api import trading
    from core.app_state import app_state

    class _Engine:
        async def get_ohlcv(self, *a, **kw):
            return [{"timestamp": 1, "close": 1.2345, "source": "engine"}]

    monkeypatch.setattr(app_state, "price_engine", _Engine(), raising=False)

    bars = await trading._get_ohlcv_for_symbol("EUR_USD", "1h", 200)

    assert bars[0]["source"] == "engine"


def test_the_pattern_page_distinguishes_no_data_from_no_patterns():
    """A scan that never ran must not render as a confident negative."""
    from pathlib import Path

    src = (Path(__file__).resolve().parents[2] / "frontend" / "src" / "pages" / "PatternDetector.tsx").read_text()

    assert "data.note ?" in src, "the backend's note is never rendered"
    assert "No price history available" in src, "no distinct no-data state"
    # The confident-negative copy must still exist, for the genuine case.
    assert "No patterns detected above" in src
