# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""Gold futures (GC=F) must never be served as XAU/USD spot, undisclosed.

CLAUDE.md records the decision explicitly: Yahoo delisted spot gold
(verified 2026-07-26), the bundled CSV is daily/weekly only, and
"a previous hand-maintained copy served delisted GC=F futures as spot" —
"Do not put a yfinance ticker back."

`config/multi_source_feed.yaml` and `data_feed/sources/yfinance_source.py`
already get this right: XAUUSD's `yfinance_ticker` is blank and the source
skips it (`can_serve()` returns False rather than substituting GC=F).

Four other live-serving paths still had their own hand-maintained copy of
the same map, each pointing XAU_USD/XAUUSD at "GC=F" — gold FUTURES, which
carry a real, varying basis to spot:

  * ``api/ws_public.py``       — the unauthenticated public ticker (`/ws/public`)
  * ``api/data_layer.py``      — ``GET /api/data-layer/tick``
  * ``api/advanced_trading.py``— ``GET /api/advanced/correlation``
  * ``data/scheduler.py``      — the background scheduler that APPENDS bars to
    the very CSVs other endpoints later read as ground truth for XAU_USD/XAUUSD

The defect is not "there is a fallback" — a disclosed one is fine. It is that
the substitution was undisclosed: the response/artifact is labelled XAU_USD
while the number underneath is a different, non-spot instrument.

The fix here is REFUSAL (CLAUDE.md's option (b)): each site must not resolve
gold to a yfinance ticker at all, so the existing "no data" / "missing"
handling at each site takes over instead of fabricating a price. Non-gold
symbols (EURUSD=X, GBPUSD=X, BTC-USD, ...) are genuine spot tickers and must
keep working — every test class below includes a positive control proving
the non-gold path is unaffected and that the mocking harness actually
observes something (an empty loop / a silently-not-called mock satisfies
nothing).
"""

from __future__ import annotations

import ast
import io
import sys
import tokenize
import types
from pathlib import Path

import pytest

pytestmark = [pytest.mark.unit]

REPO_ROOT = Path(__file__).resolve().parents[2]


def _code_only(path: Path) -> str:
    """Source with comments and docstrings stripped, so historical prose
    mentioning "GC=F" (explaining why it must NOT be used) does not trip a
    literal source scan of the executable code."""
    src = path.read_text(encoding="utf-8")
    tree = ast.parse(src)
    doc_lines: set[int] = set()
    for node in ast.walk(tree):
        body = getattr(node, "body", None)
        if not body or not isinstance(node, ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef):
            continue
        first = body[0]
        if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant) and isinstance(first.value.value, str):
            doc_lines.update(range(first.lineno, (first.end_lineno or first.lineno) + 1))

    out: list[str] = []
    for tok in tokenize.generate_tokens(io.StringIO(src).readline):
        if tok.type == tokenize.COMMENT or tok.start[0] in doc_lines:
            continue
        out.append(tok.string)
    return " ".join(out)


def test_the_stripper_would_notice_a_real_map(tmp_path):
    """Positive control for `_code_only` itself: if it over-stripped, every
    assertion below that relies on it would pass vacuously."""
    f = tmp_path / "fake.py"
    f.write_text('"""Docstring mentioning GC=F."""\n# GC=F comment\n_MAP = {"XAUUSD": "GC=F"}\n')
    code = _code_only(f)
    assert "GC=F" in code
    assert "Docstring mentioning" not in code
    assert "GC=F comment" not in code


# ═══════════════════════════════════════════════════════════════════════════
# api/ws_public.py — the public landing-page ticker
# ═══════════════════════════════════════════════════════════════════════════


class _FakeFastInfo:
    def __init__(self, last_price: float | None):
        self.last_price = last_price


class _FakeTickerInstance:
    def __init__(self, ticker: str, price: float | None):
        self.ticker = ticker
        self.fast_info = _FakeFastInfo(price)


class _FakeCloseSeries:
    def __init__(self, values: list[float]):
        self._values = list(values)

    def dropna(self):
        return self

    def tolist(self) -> list[float]:
        return list(self._values)


class _FakeDownloadFrame:
    def __init__(self, values: list[float]):
        self._values = list(values)
        self.columns = ["Close"]
        self.empty = not values

    def __getitem__(self, key):
        if key != "Close":
            raise KeyError(key)
        return _FakeCloseSeries(self._values)


@pytest.fixture
def fake_yfinance(monkeypatch):
    """Installs a fake `yfinance` module and records EVERY ticker requested,
    through both call styles the live paths use: ``Ticker(x).fast_info`` (ws
    public / data-layer) and ``download(x)`` (advanced-trading correlation).

    GC=F/SI=F are wired to return plausible data so that, pre-fix, a gold or
    silver lookup silently "succeeds" using the futures contract — and so a
    test that never actually reached the substitution would show no calls at
    all rather than an empty pass. Post-fix, GC=F/SI=F must never even be
    requested for XAU_USD/XAUUSD/XAG_USD.
    """
    calls: list[str] = []
    prices = {
        "GC=F": 2050.0,
        "SI=F": 24.0,
        "EURUSD=X": 1.09,
        "GBPUSD=X": 1.27,
        "BTC-USD": 65000.0,
    }

    def _ticker(ticker: str):
        calls.append(ticker)
        return _FakeTickerInstance(ticker, prices.get(ticker))

    def _download(ticker: str, *_a, **_k):
        calls.append(ticker)
        price = prices.get(ticker)
        if price is None:
            return _FakeDownloadFrame([])
        values = [price * (1 + 0.001 * i) for i in range(-10, 1)]
        return _FakeDownloadFrame(values)

    mod = types.ModuleType("yfinance")
    mod.Ticker = _ticker
    mod.download = _download
    monkeypatch.setitem(sys.modules, "yfinance", mod)
    return calls


class TestWsPublicTickerMap:
    def test_source_has_no_gold_futures_ticker_for_gold_symbols(self):
        from api import ws_public

        assert not ws_public._YF_TICKER_MAP.get("XAU_USD"), (
            "XAU_USD must have no yfinance fallback ticker — Yahoo has no spot gold, and GC=F is futures, not spot"
        )
        assert not ws_public._YF_TICKER_MAP.get("XAUUSD")
        # Same defect class, same config-level decision (multi_source_feed.yaml
        # blanks XAGUSD too): SI=F is silver futures, not spot silver.
        assert not ws_public._YF_TICKER_MAP.get("XAG_USD")
        assert "GC=F" not in ws_public._YF_TICKER_MAP.values()
        assert "SI=F" not in ws_public._YF_TICKER_MAP.values()

    def test_fetch_yf_sync_never_calls_yfinance_for_gold(self, fake_yfinance):
        from api import ws_public

        result = ws_public._fetch_yf_sync("XAU_USD")
        assert result is None
        assert "GC=F" not in fake_yfinance, f"GC=F was requested: {fake_yfinance}"

    def test_fetch_yf_sync_still_works_for_non_gold_symbols(self, fake_yfinance):
        """Positive control: the mock is live, and the non-gold fallback path
        the fix must not break still returns a tick."""
        from api import ws_public

        result = ws_public._fetch_yf_sync("EUR_USD")
        assert result is not None
        assert result["source"] == "delayed"
        assert result["mid"] > 0
        assert "EURUSD=X" in fake_yfinance

    def test_no_gold_futures_ticker_anywhere_in_the_executable_source(self):
        code = _code_only(REPO_ROOT / "api" / "ws_public.py")
        assert "GC=F" not in code


# ═══════════════════════════════════════════════════════════════════════════
# api/data_layer.py — GET /api/data-layer/tick
# ═══════════════════════════════════════════════════════════════════════════


class _NoTickOrchestrator:
    def get_latest_tick(self, symbol):
        return None


@pytest.fixture
def no_live_feed(monkeypatch):
    from api import data_layer

    monkeypatch.setattr(data_layer, "_get_orchestrator", lambda: _NoTickOrchestrator())


class TestDataLayerTickEndpoint:
    @pytest.mark.asyncio
    async def test_gold_tick_refuses_instead_of_substituting_futures(self, no_live_feed, fake_yfinance):
        from api.data_layer import get_latest_tick

        for symbol in ("XAU_USD", "XAUUSD"):
            result = await get_latest_tick(symbol=symbol, user=None)
            assert result["available"] is False, (
                f"{symbol}: must refuse rather than serve a GC=F price under the XAU/USD symbol — got {result!r}"
            )
            assert result.get("source") != "yfinance_fallback"
        assert "GC=F" not in fake_yfinance, f"GC=F was requested for gold: {fake_yfinance}"

    @pytest.mark.asyncio
    async def test_non_gold_tick_still_uses_yfinance_fallback(self, no_live_feed, fake_yfinance):
        """Positive control: the harness observes a real call, and the
        legitimate non-gold fallback the fix must not break still serves."""
        from api.data_layer import get_latest_tick

        result = await get_latest_tick(symbol="EURUSD=X", user=None)
        assert result["available"] is True
        assert result["source"] == "yfinance_fallback"
        assert result["mid"] == pytest.approx(1.09)
        assert "EURUSD=X" in fake_yfinance

    def test_gc_f_is_never_passed_to_the_yfinance_ticker_constructor(self):
        """Unlike ws_public/advanced_trading/scheduler, this file's refusal
        note NAMES "GC=F" to explain to an operator why gold has no fallback
        (the same style `test_ohlcv_refusal_says_what_works.py` requires) —
        so a blanket "GC=F not in code" scan would fail on the disclosure
        itself. What must never happen is passing it to the ticker
        constructor or the ternary that used to select it, so assert those
        precisely instead."""
        code = _code_only(REPO_ROOT / "api" / "data_layer.py")
        assert 'Ticker("GC=F"' not in code
        assert "Ticker('GC=F'" not in code
        assert '"GC=F" if' not in code, "the old ticker-substitution ternary is back"


# ═══════════════════════════════════════════════════════════════════════════
# api/advanced_trading.py — GET /api/advanced/correlation
# ═══════════════════════════════════════════════════════════════════════════


class TestAdvancedTradingCorrelationTicker:
    def test_gold_symbols_resolve_to_no_ticker(self):
        from api.advanced_trading import _yfinance_correlation_ticker

        assert _yfinance_correlation_ticker("XAU_USD") is None
        assert _yfinance_correlation_ticker("XAUUSD") is None

    def test_non_gold_symbols_still_resolve(self):
        """Positive control: the resolver is not a stub that returns None for
        everything — non-gold symbols the fix must not break still resolve."""
        from api.advanced_trading import _yfinance_correlation_ticker

        assert _yfinance_correlation_ticker("EUR_USD") == "EURUSD=X"
        assert _yfinance_correlation_ticker("BTC_USD") == "BTC-USD"
        # Unknown symbol falls through to the generic "=X" guess, unchanged.
        assert _yfinance_correlation_ticker("SEK_USD") == "SEKUSD=X"

    @pytest.mark.asyncio
    async def test_collect_series_never_calls_yfinance_with_gc_f_for_gold(self, monkeypatch, fake_yfinance):
        """End-to-end: even when the price-engine and CSV tiers both miss for
        gold, the yfinance tier must not silently resolve it to GC=F."""
        from api import advanced_trading

        # Force the price-engine tier to miss for every symbol.
        monkeypatch.setattr(advanced_trading, "app_state", None)

        # Force the local-CSV tier to miss: `_collect_series_from_engine`
        # derives data_dir as Path(__file__).parent.parent / "data", so nest
        # the fake module two levels under a throwaway directory with no CSVs.
        import pathlib
        import tempfile

        empty_dir = pathlib.Path(tempfile.mkdtemp())
        fake_module_file = str(empty_dir / "api" / "advanced_trading.py")
        (empty_dir / "api").mkdir(parents=True, exist_ok=True)
        monkeypatch.setattr(advanced_trading, "__file__", fake_module_file)

        result = await advanced_trading._collect_series_from_engine(None, ["XAU_USD"], 30)

        assert "GC=F" not in fake_yfinance, f"GC=F was requested for gold: {fake_yfinance}"
        assert "XAU_USD" not in result["symbols"], "gold must not appear via a fabricated futures series"

    def test_no_gold_futures_ticker_anywhere_in_the_executable_source(self):
        code = _code_only(REPO_ROOT / "api" / "advanced_trading.py")
        assert "GC=F" not in code


# ═══════════════════════════════════════════════════════════════════════════
# data/scheduler.py — background scheduler that WRITES the CSVs other
# endpoints later read as ground truth for XAU_USD/XAUUSD
# ═══════════════════════════════════════════════════════════════════════════


class _FakeYfDownloadModule:
    """Fake `yfinance` exposing both `.download()` and `.Ticker()`, since
    `_fetch_yfinance` uses either depending on whether `from_dt` is given."""

    def __init__(self, calls: list[str]):
        self._calls = calls

    def download(self, ticker, *_a, **_k):
        self._calls.append(ticker)
        return _EmptyFrame()

    def Ticker(self, ticker):
        self._calls.append(ticker)
        return _FakeSchedulerTickerInstance()


class _EmptyFrame:
    empty = True


class _FakeSchedulerTickerInstance:
    def history(self, *_a, **_k):
        return _EmptyFrame()


@pytest.fixture
def fake_scheduler_yfinance(monkeypatch):
    calls: list[str] = []
    mod = _FakeYfDownloadModule(calls)
    monkeypatch.setitem(sys.modules, "yfinance", mod)
    return calls


class TestSchedulerYfinanceMap:
    def test_symbol_map_has_no_gold_futures_ticker(self):
        from data import scheduler

        assert scheduler._YF_SYMBOL_MAP.get("XAU_USD") is None
        assert scheduler._YF_SYMBOL_MAP.get("XAUUSD") is None
        assert "GC=F" not in scheduler._YF_SYMBOL_MAP.values()

    @pytest.mark.asyncio
    async def test_fetch_yfinance_refuses_gold_without_calling_yfinance(self, fake_scheduler_yfinance):
        from data.scheduler import _fetch_yfinance

        bars = await _fetch_yfinance("XAU_USD", "D")
        assert bars == []
        assert "GC=F" not in fake_scheduler_yfinance, f"GC=F was requested for gold: {fake_scheduler_yfinance}"

    @pytest.mark.asyncio
    async def test_fetch_yfinance_still_resolves_non_gold_symbols(self, fake_scheduler_yfinance, monkeypatch):
        """Positive control: the fake module IS reached (proving the mock
        works), and a non-gold symbol still maps through to its ticker."""
        from data import scheduler

        await scheduler._fetch_yfinance("EUR_USD", "D")
        assert "EURUSD=X" in fake_scheduler_yfinance

    def test_no_gold_futures_ticker_anywhere_in_the_executable_source(self):
        code = _code_only(REPO_ROOT / "data" / "scheduler.py")
        assert "GC=F" not in code
