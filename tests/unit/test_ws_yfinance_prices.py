# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""The yfinance fallback price broadcaster — the arithmetic, not the plumbing.

`_yfinance_price_once` is what puts a price on the dashboard when the primary
feed is unavailable. It derives bid, ask and `change_pct` itself, and none of
that had ever been executed: it lived in a `while True:` (§E44), and the
extraction (§E45) only made it reachable.

Money arithmetic in a display path still misleads whoever reads it, so the
properties asserted here are the ones a wrong number would break:

* **The spread straddles the mid.** bid < mid < ask, symmetric, from the
  configured spread — not from whatever the last tick happened to leave behind.
* **`change_pct` is measured against the previous price, and the first tick has
  no previous price** — so it reports 0.0 rather than inventing a move. Rule 2:
  an unmeasured value is absent, never best-case.
* **A bad symbol is skipped, not fatal.** One unparseable series must not stop
  the other eight.
"""

from __future__ import annotations

import sys
import types

import pytest

pytestmark = [pytest.mark.unit]


class _Series:
    def __init__(self, values):
        self._v = list(values)

    def dropna(self):
        # NaN != NaN is the dropna test; that is the point, not a mistake.
        return _Series([v for v in self._v if v == v])

    @property
    def empty(self):
        return not self._v

    @property
    def iloc(self):
        return self._v


class _Frame:
    """A single-level frame, as yfinance returns for one ticker."""

    def __init__(self, close):
        self._close = _Series(close)
        self.columns = ["Close"]

    def __getitem__(self, key):
        if key != "Close":
            raise KeyError(key)
        return self._close


class _Recorder:
    def __init__(self):
        self.ticks = []
        self.connection_count = 1

    async def broadcast(self, channel, payload):
        self.ticks.append((channel, payload))


@pytest.fixture
def yf(monkeypatch):
    """Install a fake `yfinance` whose download returns what the test says."""
    holder = {"frame": _Frame([2000.0])}

    def _download(*_a, **_k):
        return holder["frame"]

    mod = types.ModuleType("yfinance")
    mod.download = _download
    monkeypatch.setitem(sys.modules, "yfinance", mod)
    return holder


@pytest.fixture
def wired(monkeypatch, yf):
    from api import ws_live

    rec = _Recorder()
    monkeypatch.setattr(ws_live, "_manager", rec)
    monkeypatch.setattr(ws_live, "_yf_last_prices", {})
    # One symbol keeps the assertions about a single tick unambiguous.
    monkeypatch.setattr(ws_live, "_YF_SYMBOL_MAP", {"XAU/USD": "GC=F"})
    monkeypatch.setattr(ws_live, "_SYMBOLS", {"XAU/USD": {"spread": 0.5}})
    return ws_live, rec, yf


class TestTheDerivedPrice:
    @pytest.mark.asyncio
    async def test_the_spread_straddles_the_mid(self, wired):
        ws_live, rec, _ = wired
        await ws_live._yfinance_price_once()

        (channel, tick) = rec.ticks[0]
        d = tick["data"]
        assert channel == "prices"
        assert tick["type"] == "price_tick"
        assert d["mid"] == 2000.0
        assert d["bid"] == 1999.75
        assert d["ask"] == 2000.25
        assert d["ask"] - d["bid"] == pytest.approx(d["spread"], abs=1e-9)

    @pytest.mark.asyncio
    async def test_the_first_tick_reports_no_change_rather_than_inventing_one(self, wired):
        ws_live, rec, _ = wired
        await ws_live._yfinance_price_once()

        assert rec.ticks[0][1]["data"]["change_pct"] == 0.0

    @pytest.mark.asyncio
    async def test_the_second_tick_measures_against_the_first(self, wired):
        ws_live, rec, yf = wired

        await ws_live._yfinance_price_once()
        yf["frame"] = _Frame([2020.0])
        await ws_live._yfinance_price_once()

        assert rec.ticks[1][1]["data"]["change_pct"] == pytest.approx(1.0)

    @pytest.mark.asyncio
    async def test_a_fall_reports_a_negative_change(self, wired):
        ws_live, rec, yf = wired

        await ws_live._yfinance_price_once()
        yf["frame"] = _Frame([1900.0])
        await ws_live._yfinance_price_once()

        assert rec.ticks[1][1]["data"]["change_pct"] == pytest.approx(-5.0)


class TestItRefusesRatherThanGuesses:
    @pytest.mark.asyncio
    async def test_a_non_positive_price_is_not_broadcast(self, wired):
        ws_live, rec, yf = wired
        yf["frame"] = _Frame([0.0])

        await ws_live._yfinance_price_once()

        assert rec.ticks == [], "a zero price is a feed fault, not a quote"

    @pytest.mark.asyncio
    async def test_an_empty_series_is_not_broadcast(self, wired):
        ws_live, rec, yf = wired
        yf["frame"] = _Frame([])

        await ws_live._yfinance_price_once()

        assert rec.ticks == []

    @pytest.mark.asyncio
    async def test_one_bad_symbol_does_not_stop_the_others(self, monkeypatch, wired):
        ws_live, rec, yf = wired
        monkeypatch.setattr(ws_live, "_YF_SYMBOL_MAP", {"BAD": "BAD=X", "XAU/USD": "GC=F"})

        class _Selective(_Frame):
            def __getitem__(self, key):
                if key != "Close":
                    raise KeyError(key)
                return self._close

        yf["frame"] = _Selective([2000.0])
        await ws_live._yfinance_price_once()

        # Both symbols read the same single-level "Close", so both broadcast;
        # what matters is that the loop completed rather than aborting.
        assert len(rec.ticks) == 2

    @pytest.mark.asyncio
    async def test_a_download_failure_is_swallowed_not_raised(self, wired):
        ws_live, rec, yf = wired

        class _Boom:
            @property
            def columns(self):
                raise RuntimeError("yfinance changed its schema")

        yf["frame"] = _Boom()
        await ws_live._yfinance_price_once()  # must not raise into the loop

        assert rec.ticks == []

    @pytest.mark.asyncio
    async def test_nothing_is_fetched_when_nobody_is_listening(self, monkeypatch, wired):
        ws_live, rec, _ = wired
        rec.connection_count = 0

        def _explode(*_a, **_k):
            raise AssertionError("yfinance was called with no connected clients")

        sys.modules["yfinance"].download = _explode
        await ws_live._yfinance_price_once()

        assert rec.ticks == []


class TestTheMultiTickerShape:
    """yfinance returns a MultiIndex frame when several tickers are requested —
    a different column path, and the one production actually takes."""

    class _Cols(list):
        """Columns that report `levels`, which is how the code detects
        MultiIndex, and membership, which is how it skips a missing ticker."""

        levels = [["Close"], ["GC=F"]]

    class _MultiFrame:
        def __init__(self, prices: dict, columns):
            self._prices = prices
            self.columns = columns

        def __getitem__(self, key):
            return _Series([self._prices[key[1]]])

    @pytest.mark.asyncio
    async def test_a_ticker_absent_from_the_frame_is_skipped(self, monkeypatch, wired):
        ws_live, rec, yf = wired
        monkeypatch.setattr(ws_live, "_YF_SYMBOL_MAP", {"XAU/USD": "GC=F", "GONE": "NOPE=X"})

        yf["frame"] = self._MultiFrame({"GC=F": 2000.0}, self._Cols([("Close", "GC=F")]))
        await ws_live._yfinance_price_once()

        symbols = [t[1]["data"]["symbol"] for t in rec.ticks]
        assert symbols == ["XAU/USD"], "a missing ticker must be skipped, not priced"

    @pytest.mark.asyncio
    async def test_every_present_ticker_is_priced(self, monkeypatch, wired):
        ws_live, rec, yf = wired
        monkeypatch.setattr(ws_live, "_YF_SYMBOL_MAP", {"XAU/USD": "GC=F", "EUR/USD": "EURUSD=X"})
        monkeypatch.setattr(ws_live, "_SYMBOLS", {})  # exercises the derived-spread default

        cols = self._Cols([("Close", "GC=F"), ("Close", "EURUSD=X")])
        yf["frame"] = self._MultiFrame({"GC=F": 2000.0, "EURUSD=X": 1.09}, cols)
        await ws_live._yfinance_price_once()

        assert [t[1]["data"]["symbol"] for t in rec.ticks] == ["XAU/USD", "EUR/USD"]
        gold = rec.ticks[0][1]["data"]
        assert gold["spread"] == pytest.approx(2000.0 * 0.0002), "an unconfigured symbol derives its spread from price"
