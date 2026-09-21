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


# ═══════════════════════════════════════════════════════════════════════════
# api/ws_live.py — the AUTHENTICATED live WebSocket (/ws/live)
#
# This is the "last site" of the same defect, flagged but out of scope in
# ce72406: two independent GC=F/SI=F maps, both on paths that actually
# execute against every connected client, not merely a fallback that might
# fire:
#
#   * `_SLASH_SYMBOL` (~line 653) — normalises an INCOMING tick's raw symbol
#     to the frontend's slash form. It is consulted by `_to_slash`, which
#     `_eventbus_tick_once` calls on every tick relayed from the EventBus
#     (`_eventbus_tick_broadcaster`, one of the three tasks `_price_broadcaster`
#     always starts). Pre-fix, a tick published under "GC=F"/"SI=F" — from any
#     publisher, present or future — would be silently relabelled "XAU/USD"/
#     "XAG/USD" and broadcast as spot.
#
#   * `_YF_SYMBOL_MAP` (~line 1282) — feeds `_yfinance_price_once`, which
#     `start_broadcasters()` (called unconditionally from `app.py`'s lifespan)
#     runs every 15 seconds via `_yfinance_price_broadcaster`, for as long as
#     any client is connected. Pre-fix it called `yf.download(["GC=F", "SI=F",
#     ...])` directly and broadcast the result under "symbol": "XAU/USD" /
#     "XAG/USD" — not a rare fallback, a periodic feed.
# ═══════════════════════════════════════════════════════════════════════════


class TestWsLiveSlashSymbolMap:
    def test_source_has_no_gold_or_silver_futures_alias(self):
        from api import ws_live

        assert "GC=F" not in ws_live._SLASH_SYMBOL, (
            "GC=F must not normalise to a gold spot symbol — that IS the undisclosed substitution"
        )
        assert "SI=F" not in ws_live._SLASH_SYMBOL
        assert "XAU/USD" not in ws_live._SLASH_SYMBOL.values() or all(
            k != "GC=F" for k, v in ws_live._SLASH_SYMBOL.items() if v == "XAU/USD"
        )

    def test_futures_codes_pass_through_unrelabelled(self):
        """With no entry, `_to_slash` has no rule that could reconstruct
        XAU/USD from GC=F (4 chars: no '/', no '-', not a 6-char pair), so it
        must fall through unchanged — like any other futures/index code with
        no pair structure (compare "US30" in test_ws_live_symbols.py)."""
        from api.ws_live import _to_slash

        assert _to_slash("GC=F") == "GC=F"
        assert _to_slash("SI=F") == "SI=F"

    def test_non_gold_aliases_still_resolve(self):
        """Positive control: removing the gold/silver entries must not break
        the alias table's real job for symbols the fix must not touch."""
        from api.ws_live import _to_slash

        assert _to_slash("XAUUSD") == "XAU/USD"  # genuine spot alias — kept
        assert _to_slash("EURUSD=X") == "EUR/USD"
        assert _to_slash("BTCUSD") == "BTC/USD"


class _WsLiveSeries:
    def __init__(self, values):
        self._v = list(values)

    def dropna(self):
        return self

    @property
    def empty(self):
        return not self._v

    @property
    def iloc(self):
        return self._v


class _WsLiveCols(list):
    """Columns object reporting `.levels`, which is how the code under test
    detects a MultiIndex frame (yfinance's shape when several tickers are
    requested at once — the shape production actually takes)."""

    def __init__(self, tickers):
        super().__init__([("Close", t) for t in tickers])
        self.levels = [["Close"], list(tickers)]


class _WsLiveMultiFrame:
    def __init__(self, price_by_ticker: dict[str, float]):
        self._prices = price_by_ticker
        self.columns = _WsLiveCols(list(price_by_ticker))

    def __getitem__(self, col):
        return _WsLiveSeries([self._prices[col[1]]])


class _WsLiveRecorder:
    def __init__(self):
        self.connection_count = 1
        self.broadcast_calls: list[tuple[str, dict]] = []

    async def broadcast(self, channel, payload):
        self.broadcast_calls.append((channel, payload))


class TestWsLiveYfinancePoller:
    def test_symbol_map_has_no_gold_or_silver_futures_ticker(self):
        from api import ws_live

        assert ws_live._YF_SYMBOL_MAP.get("XAU/USD") is None
        assert ws_live._YF_SYMBOL_MAP.get("XAG/USD") is None
        assert "GC=F" not in ws_live._YF_SYMBOL_MAP.values()
        assert "SI=F" not in ws_live._YF_SYMBOL_MAP.values()

    @pytest.mark.asyncio
    async def test_poller_never_requests_gold_or_silver_futures(self, monkeypatch):
        """End-to-end, against the REAL (unmocked) `_YF_SYMBOL_MAP` — proves
        the periodic poller that actually runs in production never asks
        yfinance for GC=F/SI=F, and never broadcasts a tick under the
        XAU/USD or XAG/USD label from this path. A non-gold symbol still
        broadcasting is the positive control: it proves the harness observed
        the real `download()` call rather than passing vacuously."""
        from api import ws_live

        real_map = dict(ws_live._YF_SYMBOL_MAP)
        assert real_map, "the real symbol map is empty — this test would prove nothing"

        calls: list[list[str]] = []

        def _download(tickers, *_a, **_k):
            calls.append(list(tickers))
            return _WsLiveMultiFrame(dict.fromkeys(tickers, 1.2345))

        mod = types.ModuleType("yfinance")
        mod.download = _download
        monkeypatch.setitem(sys.modules, "yfinance", mod)

        rec = _WsLiveRecorder()
        monkeypatch.setattr(ws_live, "_manager", rec)
        monkeypatch.setattr(ws_live, "_yf_last_prices", {})

        await ws_live._yfinance_price_once()

        assert calls, "the fake yfinance was never reached — the test observed nothing"
        requested = calls[0]
        assert "GC=F" not in requested, f"GC=F was requested: {requested}"
        assert "SI=F" not in requested, f"SI=F was requested: {requested}"

        broadcast_symbols = [payload["data"]["symbol"] for _channel, payload in rec.broadcast_calls]
        assert "XAU/USD" not in broadcast_symbols
        assert "XAG/USD" not in broadcast_symbols
        assert broadcast_symbols, (
            "no symbol was broadcast at all — the positive control did not fire, "
            "so 'gold absent' above is not distinguishable from 'nothing works'"
        )

    def test_no_gold_futures_ticker_anywhere_in_the_executable_source(self):
        code = _code_only(REPO_ROOT / "api" / "ws_live.py")
        assert "GC=F" not in code
        assert "SI=F" not in code


# ═══════════════════════════════════════════════════════════════════════════
# research/pipeline/mtf_fusion.py — MTFFusionStore, reaches LIVE ML INFERENCE
#
# Unlike the four sites above, this is not a display or an API response: its
# output (d_*/h_* regime columns) is appended to the feature matrix inside
# ml/inference_engine.py::InferenceEngine._get_mtf_df -> predict(), and that
# result is what core/decision/HOPEFXDecisionEngine.py::_phase2_ml uses to
# override the trade probability — i.e. the order path itself. The store is
# only ever constructed with symbol="XAU_USD" in production
# (core/startup_factories.py::init_mtf_store, DATA_SYMBOL env var default),
# and no data/XAU_USD_H4.csv or data/XAU_USD_D.csv is bundled (only
# data/XAU_USD_M.csv, monthly), so with FEATURE_MTF_FUSION=true (the default)
# and no OANDA credentials writing those files, the yfinance(GC=F) fallback
# fires on every default-config startup — reproduced in a real
# `uvicorn app:app` boot log:
#   "MTFFusionStore: falling back to yfinance (GC=F)"
# ═══════════════════════════════════════════════════════════════════════════


class _EmptyMtfFrame:
    """Stands in for an empty yfinance download — enough to prove whether the
    call happened at all without simulating pandas resample/groupby, which
    `_load_from_yfinance` used to do to the real result before the fix."""

    empty = True


@pytest.fixture
def fake_mtf_yfinance(monkeypatch):
    """Fake `yfinance.download`, recording every ticker requested."""
    calls: list[str] = []

    def _download(ticker, *_a, **_k):
        calls.append(ticker)
        return _EmptyMtfFrame()

    mod = types.ModuleType("yfinance")
    mod.download = _download
    monkeypatch.setitem(sys.modules, "yfinance", mod)
    return calls


class TestMTFFusionStoreYfinanceFallback:
    def test_no_bundled_h4_or_daily_csv_for_xau_usd(self):
        """Documents WHY the fallback fires in the real default config: this
        is not a hypothetical path. Only data/XAU_USD_M.csv (monthly) is
        bundled — no H4 or daily CSV — so `_load_data()` always falls
        through to `_load_from_yfinance()` for the symbol every production
        MTFFusionStore is actually constructed with."""
        data_dir = REPO_ROOT / "data"
        assert not (data_dir / "XAU_USD_H4.csv").exists()
        assert not (data_dir / "XAU_USD_D.csv").exists()

    def test_load_from_yfinance_refuses_for_gold_and_silver(self, fake_mtf_yfinance):
        from research.pipeline.mtf_fusion import MTFFusionStore

        for symbol in ("XAU_USD", "XAUUSD", "XAG_USD", "XAGUSD"):
            store = MTFFusionStore(symbol=symbol, data_dir="/tmp/nonexistent_mtf_data_dir")
            store._load_from_yfinance()
            assert store._h4_df is None, f"{symbol}: H4 must stay empty, not futures-derived"
            assert store._d1_df is None, f"{symbol}: D1 must stay empty, not futures-derived"
        assert "GC=F" not in fake_mtf_yfinance, f"GC=F was requested: {fake_mtf_yfinance}"
        assert "SI=F" not in fake_mtf_yfinance, f"SI=F was requested: {fake_mtf_yfinance}"

    def test_refusal_is_disclosed_not_silent(self):
        """A silent refusal is indistinguishable from 'nobody tried' — the
        store must say WHY, on the same status() surface
        core/signal_engine.py exposes to diagnostics (status['phase1_mtf'])."""
        from research.pipeline.mtf_fusion import MTFFusionStore

        store = MTFFusionStore(symbol="XAU_USD", data_dir="/tmp/nonexistent_mtf_data_dir")
        store._load_from_yfinance()
        assert store._bootstrap_error, "the refusal must be recorded, not silent"
        assert "GC=F" not in store._bootstrap_error, (
            "the disclosure text must not itself name the futures ticker as if it had been used"
        )

    def test_positive_control_the_harness_observes_a_real_call(self, fake_mtf_yfinance):
        """Mutation-style positive control: prove the fake `yfinance` module
        IS reached and recorded by this file's fixture, by performing the
        exact call `_load_from_yfinance` used to make unconditionally before
        the fix (`yf.download("GC=F", ...)`). If this ever failed, every
        'GC=F not requested' assertion above would be passing vacuously
        because the mock was never wired in the first place."""
        import yfinance as yf  # the fake module installed by fake_mtf_yfinance

        yf.download("GC=F", period="2y", interval="1h", progress=False, auto_adjust=True)
        assert "GC=F" in fake_mtf_yfinance, "the harness did not observe a call it should have — the mock is not live"

    @pytest.mark.asyncio
    async def test_bootstrap_end_to_end_leaves_store_not_ready_for_gold(self, fake_mtf_yfinance):
        """End-to-end through the real startup path: bootstrap() ->
        _load_data() -> CSV miss (no H4/D1 CSV bundled) -> the yfinance
        fallback. With the substitution refused, the store must be not-ready
        rather than silently ready on futures data, and align_to_h1 must
        return None — the existing 'features unavailable' path — not a
        DataFrame derived from a different instrument."""
        from research.pipeline.mtf_fusion import MTFFusionStore

        store = MTFFusionStore(symbol="XAU_USD", data_dir="/tmp/nonexistent_mtf_data_dir")
        await store.bootstrap()

        assert store._bootstrapped is True
        assert store.is_ready is False, "no CSV and a refused fallback must leave the store not-ready"
        assert "GC=F" not in fake_mtf_yfinance

        import pandas as pd

        idx = pd.date_range("2024-01-01", periods=5, freq="h", tz="UTC")
        ohlcv = pd.DataFrame(
            {"open": 1.0, "high": 1.0, "low": 1.0, "close": 1.0, "volume": 1.0},
            index=idx,
        )
        assert store.align_to_h1(ohlcv) is None, "must refuse (None), never a GC=F-derived DataFrame"

    def test_no_gold_futures_ticker_anywhere_in_the_executable_source(self):
        code = _code_only(REPO_ROOT / "research" / "pipeline" / "mtf_fusion.py")
        assert "GC=F" not in code
        assert "SI=F" not in code
