# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
tests/unit/test_chart_analysis.py
=================================
The AI Chart Bot, rebuilt on the platform's real ML stack.

The endpoint it replaces (``POST /api/trading/ai-analysis``, 230 lines inline in
the router) had **no machine learning in it at all**, while the UI labelled its
output "ML FEATURE IMPORTANCE" and animated "Reading ML signals…". It also had
zero test coverage — ``grep -rn "ai-analysis" tests/`` returned nothing — which
is how five separate defects survived in a user-facing feature:

1. ``ZeroDivisionError`` → unhandled HTTP 500 whenever the last 15 closes were
   identical. ``(gains if d > 0 else losses)`` routes a **zero** delta into
   ``losses``, and the ``if losses else 0.001`` guard only catches an *empty*
   list, not a list of zeros. Reachable on every market close and every quiet
   1m chart.
2. ``TypeError`` / ``AttributeError`` → two more 500s, from ``{"price": null}``
   and ``{"symbol": null}``, because the signature was a bare ``dict``.
3. EMAs computed backwards — ``for c in reversed(closes[-20:])`` weights the
   *oldest* bar most and seeds on a bar it then re-consumes. Measured against a
   correct EMA over 3,000 simulated paths: **19.1% of regime verdicts differed**.
4. The click context carried **no symbol and no timeframe**. The backend read
   ``context.get("symbol", "XAUUSD")``. Clicking a EURUSD 15m chart returned an
   XAUUSD 1h analysis, rendered inside the EURUSD panel.
5. Degradation was invisible. ``data_source: "fallback"`` and
   ``bars_analyzed: 0`` were returned and **read by nothing**, so a placeholder
   rendered the same confident badge as a real read.

Every test below pins one of those, or the behaviour of the real ML path that
replaced the hand-rolled one.
"""

from __future__ import annotations

import math
from types import SimpleNamespace

import pytest

from analysis.chart_analysis import (
    ChartClickContext,
    ModelVerdict,
    atr,
    classify_regime,
    classify_volatility,
    compose,
    ema,
    is_degenerate,
    load_bars,
    rsi,
    run_model,
)

pytestmark = pytest.mark.unit


def _bars(closes, spread=1.0, volume=100.0):
    return [{"open": c, "high": c + spread, "low": c - spread, "close": c, "volume": volume} for c in closes]


def _rising(n=200, start=4000.0, step=1.0):
    return _bars([start + i * step for i in range(n)])


# ── 1. The crash: RSI on a flat tape ─────────────────────────────────────────


def test_a_perfectly_flat_window_does_not_crash():
    """The exact input that returned HTTP 500."""
    assert rsi([4000.0] * 30) is None


def test_a_flat_window_reports_undefined_rather_than_zero():
    """The old code's non-crashing sibling was worse than the crash.

    Where it survived, a flat tape produced avg_gain=0 over the 0.001 magic
    constant — RSI 0.0, "maximally oversold" — and the endpoint answered BUY at
    high confidence on a market that had not moved.
    """
    assert rsi([4000.0] * 30) is None, "a flat tape must be undefined, not oversold"


@pytest.mark.parametrize(
    "closes",
    [
        [4000.0] * 30,
        [4000.0 + i for i in range(5)] + [4100.0] * 20,  # older bars moved, window flat
        [],
        [4000.0],
        [4000.0] * 14,  # exactly one short of the window
    ],
)
def test_rsi_is_total_over_degenerate_inputs(closes):
    result = rsi(closes)
    assert result is None or (0.0 <= result <= 100.0)


def test_a_zero_delta_is_neither_a_gain_nor_a_loss():
    """The root cause. `d > 0` is False for d == 0, so every flat bar was
    counted as a loss — a standing downward bias toward "oversold → BUY"."""
    # 7 up moves, 7 flat. Counting the flats as losses would drag RSI to ~50;
    # ignoring them leaves a pure-gain window.
    closes = [4000.0]
    for _ in range(7):
        closes.append(closes[-1] + 1.0)
    for _ in range(7):
        closes.append(closes[-1])
    assert rsi(closes) == 100.0


@pytest.mark.parametrize("closes", [[4000.0 + i * 5 for i in range(30)], [4000.0 - i * 5 for i in range(30)]])
def test_one_sided_markets_pin_the_extremes(closes):
    value = rsi(closes)
    assert value in (0.0, 100.0)


def test_rsi_matches_wilder_on_a_known_series():
    """A hand-checked case, so the fix is not merely 'does not crash'."""
    closes = [44.34, 44.09, 44.15, 43.61, 44.33, 44.83, 45.10, 45.42, 45.84, 46.08, 45.89, 46.03, 45.61, 46.28, 46.28]
    value = rsi(closes, period=14)
    assert value is not None
    assert 68.0 < value < 78.0, value


# ── 2. Validated input: the other two 500s ───────────────────────────────────


@pytest.mark.parametrize(
    ("payload", "field", "expected"),
    [
        ({"price": None}, "price", 0.0),
        ({"symbol": None}, "symbol", "XAUUSD"),
        ({"symbol": "   "}, "symbol", "XAUUSD"),
        ({"timeframe": None}, "timeframe", "1h"),
        ({"price": "4000"}, "price", 4000.0),
        ({}, "symbol", "XAUUSD"),
    ],
)
def test_hostile_payloads_are_coerced_not_crashed(payload, field, expected):
    assert getattr(ChartClickContext.model_validate(payload), field) == expected


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf")])
def test_non_finite_prices_are_rejected(bad):
    """NaN propagates silently through every derived number — including the
    stop loss the user is shown."""
    ctx = ChartClickContext.model_validate({"price": bad})
    assert ctx.price == 0.0
    assert math.isfinite(ctx.price)


def test_the_symbol_is_canonicalised():
    for raw in ("XAU/USD", "xau_usd", "XAUUSD", "xau/usd"):
        assert ChartClickContext(symbol=raw).canonical_symbol() == "XAUUSD"


def test_the_context_carries_symbol_and_timeframe():
    """Defect 4. Without these fields the backend defaulted to XAUUSD/1h, so a
    click on any other chart analysed the wrong instrument."""
    ctx = ChartClickContext.model_validate({"symbol": "EURUSD", "timeframe": "15m", "price": 1.09})
    assert ctx.canonical_symbol() == "EURUSD"
    assert ctx.timeframe == "15m"


# ── 3. The EMA that ran backwards ────────────────────────────────────────────


def test_ema_of_a_constant_series_is_that_constant():
    assert ema([5.0] * 50, 20) == pytest.approx(5.0)


def test_ema_tracks_the_recent_end_of_a_trend():
    """The reversed loop weighted the OLDEST bar most, so the average lagged
    into the past instead of following price."""
    closes = [100.0 + i for i in range(60)]
    value = ema(closes, 20)
    assert value is not None
    # Must sit inside the last window and near its recent end.
    assert closes[-20] < value < closes[-1]
    assert value > (closes[-20] + closes[-1]) / 2, "the average is lagging the wrong way"


def test_ema_is_more_responsive_than_the_window_mean():
    closes = [100.0] * 40 + [200.0] * 20
    assert ema(closes, 20) == pytest.approx(200.0, abs=1.0)


@pytest.mark.parametrize("values,period", [([], 20), ([1.0], 20), ([1.0, 2.0], 0), ([1.0, 2.0], -5)])
def test_ema_is_total(values, period):
    result = ema(values, period)
    assert result is None or isinstance(result, float)


def test_the_old_reversed_ema_disagreed_on_regime_calls():
    """Pins the measurement that justified the rewrite.

    Reproduces the previous implementation verbatim and counts how often it
    reaches a different regime than the corrected one over random walks.
    """
    import random

    def old_emas(c):
        e20 = c[-1]
        for x in reversed(c[-20:]):
            e20 = e20 * 0.9 + x * 0.1
        e50 = c[-1]
        for x in reversed(c[-min(50, len(c)) :]):
            e50 = e50 * 0.96 + x * 0.04
        return e20, e50

    def verdict(e20, e50, c):
        spread = (e20 - e50) / e50
        pve = (c[-1] - e20) / e20
        if abs(spread) > 0.005 and abs(pve) > 0.003:
            return "up" if spread > 0 else "down"
        return "range"

    random.seed(7)
    differ = 0
    trials = 400
    for _ in range(trials):
        p, c = 4000.0, [4000.0]
        drift = random.uniform(-0.0015, 0.0015)
        for _ in range(99):
            p *= 1 + drift + random.gauss(0, 0.004)
            c.append(p)
        new = classify_regime(c, atr(_bars(c)), c[-1]).regime
        new_short = {"trending_up": "up", "trending_down": "down"}.get(new, "range")
        if verdict(*old_emas(c), c) != new_short:
            differ += 1
    assert differ > trials * 0.05, (
        f"only {differ}/{trials} differ — the old and new EMAs agree, so this test no longer "
        "demonstrates anything and the rewrite needs re-justifying"
    )


# ── ATR and volatility ───────────────────────────────────────────────────────


def test_atr_of_constant_range_bars_is_that_range():
    bars = [{"open": 100.0, "high": 101.0, "low": 99.0, "close": 100.0} for _ in range(30)]
    assert atr(bars) == pytest.approx(2.0)


@pytest.mark.parametrize("bars", [[], _bars([1.0]), _bars([1.0] * 14)])
def test_atr_is_total(bars):
    assert atr(bars) is None


@pytest.mark.parametrize(
    ("atr_value", "price", "expected"),
    [
        (None, 4000.0, "unknown"),
        (10.0, 0.0, "unknown"),
        (80.0, 4000.0, "high"),
        (10.0, 4000.0, "low"),
        (40.0, 4000.0, "medium"),
    ],
)
def test_volatility_buckets(atr_value, price, expected):
    assert classify_volatility(atr_value, price) == expected


# ── Regime ───────────────────────────────────────────────────────────────────


def test_a_clean_uptrend_is_called_up():
    closes = [4000.0 * (1.004**i) for i in range(80)]
    assert classify_regime(closes, atr(_bars(closes)), closes[-1]).regime == "trending_up"


def test_a_clean_downtrend_is_called_down():
    closes = [4000.0 * (0.996**i) for i in range(80)]
    assert classify_regime(closes, atr(_bars(closes)), closes[-1]).regime == "trending_down"


def test_a_flat_market_is_not_called_a_trend():
    assert classify_regime([4000.0] * 80, 1.0, 4000.0).regime in ("ranging", "volatile")


def test_a_short_history_is_admitted_not_guessed():
    v = classify_regime([4000.0, 4001.0, 4002.0], None, 4002.0)
    assert v.regime == "ranging"
    assert v.confidence <= 0.4, "a regime call on 3 bars must not be presented confidently"
    assert any("Insufficient" in r for r in v.reasons)


def test_every_regime_carries_its_reasoning():
    closes = [4000.0 * (1.004**i) for i in range(80)]
    assert classify_regime(closes, atr(_bars(closes)), closes[-1]).reasons


# ── Synthetic data ───────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("bars", "expected"),
    [(_bars([4000.0] * 100), True), ([], True), (_bars([4000.0]), True), (_rising(100), False)],
)
def test_degenerate_detection(bars, expected):
    assert is_degenerate(bars) is expected


async def test_synthetic_bars_are_refused_by_the_loader():
    """The price engine's last-resort tier repeats a static price with
    volume=0. Indicators over it are all zero and render identically to real
    ones."""

    class _Bar:
        def __init__(self, c):
            self.open = self.high = self.low = self.close = c
            self.volume = 0.0

    async def _get_ohlcv(sym, tf, limit):
        return [_Bar(4000.0) for _ in range(200)]

    bars, source = await load_bars("XAUUSD", "1h", SimpleNamespace(price_engine=SimpleNamespace(get_ohlcv=_get_ohlcv)))
    assert bars == []
    assert source == "synthetic"


@pytest.mark.parametrize(
    ("state", "expected_source"),
    [(SimpleNamespace(price_engine=None), "unavailable"), (None, "unavailable")],
)
async def test_the_loader_never_raises(state, expected_source):
    bars, source = await load_bars("XAUUSD", "1h", state)
    assert bars == []
    assert source == expected_source


async def test_a_raising_price_engine_is_reported_not_propagated():
    async def _boom(sym, tf, limit):
        raise ConnectionError("down")

    bars, source = await load_bars("XAUUSD", "1h", SimpleNamespace(price_engine=SimpleNamespace(get_ohlcv=_boom)))
    assert bars == [] and source == "error"


def _code_only(path) -> str:
    """Source with every docstring and comment stripped.

    Needed because the module documents the defect it fixes, so a naive
    substring search matches the explanation rather than the code — a mistake
    made twice already in this codebase's history.
    """
    import ast
    import io
    import tokenize

    src = path.read_text()
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


def test_the_loader_does_not_carry_a_yfinance_ticker_map():
    """Defect: the old handler embedded a FOURTH independent map, sending
    XAUUSD to GC=F — the futures contract — while
    config/multi_source_feed.yaml deliberately blanks Yahoo for spot metals."""
    import pathlib

    code = _code_only(pathlib.Path(__file__).resolve().parents[2] / "analysis/chart_analysis.py")
    assert "GC=F" not in code, "a yfinance ticker map came back"
    assert "yfinance" not in code, "the module body must go through the price engine"


def test_the_stripper_would_notice_a_real_map():
    """Guards the test above: if _code_only over-stripped, it would pass on a
    module that genuinely embedded a ticker map."""
    import pathlib
    import tempfile

    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False) as fh:
        fh.write('"""Docstring mentioning yfinance and GC=F."""\n_MAP = {"XAUUSD": "GC=F"}\n')
        name = fh.name
    code = _code_only(pathlib.Path(name))
    assert "GC=F" in code and "yfinance" not in code


# ── The ML layer ─────────────────────────────────────────────────────────────


class _Engine:
    def __init__(self, result=None, safe=True, drift=True, raises=None):
        self._result = result or {}
        self._safe, self._drift, self._raises = safe, drift, raises

    def predict(self, df, symbol="XAUUSD"):
        if self._raises:
            raise self._raises
        return self._result

    def is_safe_to_trade(self):
        return self._safe

    def drift_guard_active(self):
        return self._drift


_GOOD = {
    "direction": "long",
    "confidence": 0.72,
    "probability": 0.81,
    "model_version": "advanced_oos_v2",
    "bars_used": 200,
    "fallback": False,
}


def test_the_model_verdict_is_used():
    v = run_model(_rising(200), "XAUUSD", _Engine(_GOOD))
    assert v.available and not v.fallback
    assert v.direction == "long"
    assert v.confidence == pytest.approx(0.72)
    assert v.model_version == "advanced_oos_v2"


def test_a_missing_engine_is_stated_not_hidden():
    v = run_model(_rising(200), "XAUUSD", None)
    assert not v.available
    assert any("technical-indicator only" in w for w in v.warnings)


def test_too_few_bars_is_stated():
    v = run_model(_rising(30), "XAUUSD", _Engine(_GOOD))
    assert not v.available
    assert any("30 bars" in w for w in v.warnings)


def test_a_raising_engine_does_not_propagate():
    """A chart click must not 500 because a model file is missing."""
    v = run_model(_rising(200), "XAUUSD", _Engine(raises=RuntimeError("no model")))
    assert not v.available
    assert any("RuntimeError" in w for w in v.warnings)


def test_the_deterministic_fallback_is_called_out():
    v = run_model(_rising(200), "XAUUSD", _Engine({**_GOOD, "fallback": True}))
    assert any("deterministic fallback" in w for w in v.warnings)


def test_the_data_quality_gate_reaches_the_user():
    """`is_safe_to_trade` already governs live trading. The bot showed it to
    nobody."""
    v = run_model(_rising(200), "XAUUSD", _Engine(_GOOD, safe=False))
    assert any("gate is CLOSED" in w for w in v.warnings)


def test_a_disabled_drift_guard_reaches_the_user():
    v = run_model(_rising(200), "XAUUSD", _Engine(_GOOD, drift=False))
    assert any("drift" in w.lower() for w in v.warnings)


def test_a_healthy_engine_raises_no_gate_warnings():
    assert run_model(_rising(200), "XAUUSD", _Engine(_GOOD)).warnings == []


# ── Composition ──────────────────────────────────────────────────────────────


def _ctx(**kw):
    return ChartClickContext.model_validate({"symbol": "XAUUSD", "price": 4100.0, "timeframe": "1h", **kw})


def test_the_model_drives_the_recommendation():
    """The old code let an RSI threshold set the recommendation outright; the
    model is now the signal and indicators are context."""
    out = compose(_ctx(), _rising(200), run_model(_rising(200), "XAUUSD", _Engine(_GOOD)), data_source="price_engine")
    assert out["recommendedAction"] == "buy"
    assert out["direction"] == "long"
    assert out["modelAvailable"] is True
    assert any("advanced_oos_v2" in d for d in out["keyDrivers"])


def test_without_a_model_the_technical_read_takes_over_at_lower_confidence():
    bars = _rising(200)
    out = compose(_ctx(), bars, run_model(bars, "XAUUSD", None), data_source="price_engine")
    assert out["modelAvailable"] is False
    assert out["degraded"] is True
    assert out["actionConfidence"] <= 0.6, "an indicator-only call must not claim model-grade confidence"


def test_no_bars_produces_an_explicit_placeholder():
    """The old response was 'RANGING 50%, Recommended: HOLD at 0.0000' with an
    empty warnings list, rendered identically to a real analysis."""
    out = compose(_ctx(price=0.0), [], ModelVerdict(), data_source="unavailable")
    assert out["degraded"] is True
    assert out["barsAnalyzed"] == 0
    assert out["stop_loss"] is None and out["take_profit"] is None
    assert any("placeholder" in w for w in out["warnings"])


def test_no_atr_means_no_invented_stop():
    """The old code fell back to a flat 0.5% of price and presented that
    fabricated distance with the same authority as a measured one."""
    out = compose(_ctx(), _bars([4100.0, 4101.0]), ModelVerdict(), data_source="price_engine")
    assert out["stop_loss"] is None
    assert out["take_profit"] is None
    assert "not supported" in out["riskAssessment"]
    assert any("No ATR" in w for w in out["warnings"])


def test_stops_sit_on_the_correct_side_for_a_short():
    bars = _bars([4200.0 - i for i in range(200)])
    verdict = run_model(bars, "XAUUSD", _Engine({**_GOOD, "direction": "short"}))
    out = compose(_ctx(price=4000.0), bars, verdict, data_source="price_engine")
    assert out["recommendedAction"] == "sell"
    assert out["stop_loss"] > 4000.0, "a short's stop must sit above entry"
    assert out["take_profit"] < 4000.0


def test_stops_sit_on_the_correct_side_for_a_long():
    bars = _rising(200)
    out = compose(_ctx(price=4000.0), bars, run_model(bars, "XAUUSD", _Engine(_GOOD)), data_source="price_engine")
    assert out["stop_loss"] < 4000.0
    assert out["take_profit"] > 4000.0


def test_a_model_call_against_a_stretched_oscillator_is_flagged():
    """Worth surfacing rather than quietly averaging away."""
    bars = _rising(200)  # monotonic rally → RSI 100
    out = compose(_ctx(), bars, run_model(bars, "XAUUSD", _Engine(_GOOD)), data_source="price_engine")
    assert any("overbought" in w for w in out["warnings"])


def test_the_summary_admits_when_there_is_no_model():
    out = compose(_ctx(), _rising(200), ModelVerdict(), data_source="price_engine")
    assert "technical read only" in out["summary"]


def test_the_summary_names_the_model_when_there_is_one():
    bars = _rising(200)
    out = compose(_ctx(), bars, run_model(bars, "XAUUSD", _Engine(_GOOD)), data_source="price_engine")
    assert "advanced_oos_v2" in out["summary"]


def test_an_undefined_rsi_is_reported_as_such_in_prose():
    bars = _bars([4000.0] * 200)
    out = compose(_ctx(), bars, ModelVerdict(), data_source="price_engine")
    assert out["rsi"] is None
    assert "undefined" in out["summary"]


def test_confidence_never_exceeds_the_cap():
    out = compose(
        _ctx(),
        _rising(200),
        run_model(_rising(200), "XAUUSD", _Engine({**_GOOD, "confidence": 1.0})),
        data_source="price_engine",
    )
    assert out["confidence"] <= 0.95
    assert out["actionConfidence"] <= 0.95


def test_the_response_carries_full_provenance():
    """Defect 5: these fields existed and nothing read them. They are now part
    of the contract the UI renders."""
    bars = _rising(200)
    out = compose(_ctx(), bars, run_model(bars, "XAUUSD", _Engine(_GOOD)), data_source="price_engine")
    for key in ("modelVersion", "modelAvailable", "barsAnalyzed", "dataSource", "degraded", "rsi", "atr"):
        assert key in out, key
    assert out["barsAnalyzed"] == 200
    assert out["dataSource"] == "price_engine"


def test_the_legacy_response_keys_are_preserved():
    """Existing consumers keep working across the rewrite."""
    bars = _rising(200)
    out = compose(_ctx(), bars, run_model(bars, "XAUUSD", _Engine(_GOOD)), data_source="price_engine")
    for key in (
        "id",
        "timestamp",
        "context",
        "direction",
        "confidence",
        "reasoning",
        "regime",
        "stop_loss",
        "take_profit",
        "entry_zone",
        "key_levels",
        "regimeConfidence",
        "volatility",
        "trend",
        "summary",
        "keyDrivers",
        "riskAssessment",
        "recommendedAction",
        "actionConfidence",
        "priceTargets",
        "timeHorizon",
        "warnings",
        "data_source",
        "bars_analyzed",
    ):
        assert key in out, f"dropped from the response contract: {key}"


def test_the_echoed_context_keeps_the_symbol_the_user_clicked():
    out = compose(_ctx(symbol="EURUSD", price=1.09), _rising(200), ModelVerdict(), data_source="price_engine")
    assert out["context"]["symbol"] == "EURUSD"


@pytest.mark.parametrize("price", [0.0, -1.0])
def test_a_non_positive_click_price_falls_back_to_the_last_close(price):
    bars = _rising(200)
    out = compose(_ctx(price=price), bars, ModelVerdict(), data_source="price_engine")
    assert out["priceTargets"]["bull"] > bars[-1]["close"]


# ── Cache: the path ws_live has always read and nothing ever wrote ───────────


def _fake_redis(monkeypatch, written: list):
    """Patch the name chart_analysis actually imports.

    `get_sync_redis_client` is an alias bound at module-definition time
    (`get_sync_redis_client = get_sync_redis`), so patching `get_sync_redis`
    leaves the alias pointing at the real function — a patch that silently does
    nothing.
    """
    monkeypatch.setattr(
        "cache.redis_client.get_sync_redis_client",
        lambda: SimpleNamespace(setex=lambda *a: written.append(a)),
        raising=False,
    )


def test_a_healthy_analysis_is_published(monkeypatch):
    """The write that makes ws_live's broadcast path live for the first time."""
    from analysis import chart_analysis as ca

    written: list = []
    _fake_redis(monkeypatch, written)
    assert ca.cache_write("XAUUSD", {"degraded": False, "summary": "x"}) is True
    assert len(written) == 1
    key, ttl, _payload = written[0]
    assert key == "ai_analysis:XAUUSD"
    assert ttl == ca.CACHE_TTL_SECONDS


def test_a_degraded_analysis_is_not_published(monkeypatch):
    """Pushing a placeholder to every connected client is worse than pushing
    nothing."""
    from analysis import chart_analysis as ca

    written: list = []
    _fake_redis(monkeypatch, written)
    assert ca.cache_write("XAUUSD", {"degraded": True, "summary": "x"}) is False
    assert written == []


def test_the_cache_key_matches_what_ws_live_reads():
    """api/ws_live.py reads ai_analysis:{symbol} for six symbols on every
    broadcast cycle, under a comment claiming this endpoint writes it. It never
    did — the handler contained no Redis reference at all, so those GETs always
    returned nothing and clients never received the push."""
    import pathlib

    from analysis.chart_analysis import _CACHE_KEY

    assert _CACHE_KEY == "ai_analysis:{symbol}"
    ws = (pathlib.Path(__file__).resolve().parents[2] / "api/ws_live.py").read_text()
    assert 'f"ai_analysis:{_sym}"' in ws, "ws_live's read key changed — the write key must follow"


def test_cache_write_survives_an_unavailable_redis(monkeypatch):
    from analysis import chart_analysis as ca

    monkeypatch.setattr("cache.redis_client.get_sync_redis_client", lambda: None, raising=False)
    assert ca.cache_write("XAUUSD", {"degraded": False}) is False


# ── End to end ───────────────────────────────────────────────────────────────


async def test_analyze_never_raises_with_nothing_wired_up():
    from analysis.chart_analysis import analyze

    out = await analyze(_ctx(), SimpleNamespace(price_engine=None), engine=None)
    assert out["degraded"] is True
    assert out["summary"]
    assert out["warnings"]


# ── The endpoint layer ───────────────────────────────────────────────────────


def test_the_router_delegates_and_holds_no_indicator_maths():
    """The handler was 230 lines of hand-rolled EMA/RSI/ATR inline in the router.

    It is now a thin adapter. Pinned as a property because the failure mode was
    exactly this logic accreting where nothing tested it.
    """
    import inspect

    import api.trading as t

    src = inspect.getsource(t.get_ai_analysis)
    assert "analyze" in src and "ChartClickContext" in src
    for banned in ("yfinance", "GC=F", "avg_gain", "ema20", "_TF_MAP", "_YF_MAP"):
        assert banned not in src, f"indicator/fetch logic came back into the router: {banned}"
    assert len(src.splitlines()) < 40, "the handler is growing a body again"


def test_the_endpoint_is_rate_limited():
    """Orders next door carry _order_rate_limit_dep; this carried nothing, so a
    drag across the chart issued one uncached fetch per click."""
    import api.trading as t

    t._AI_ANALYSIS_RATE.clear()
    for _ in range(t._AI_ANALYSIS_MAX_PER_MIN):
        t._ai_analysis_rate_limit("user-1")

    from fastapi import HTTPException

    with pytest.raises(HTTPException) as exc:
        t._ai_analysis_rate_limit("user-1")
    assert exc.value.status_code == 429
    t._AI_ANALYSIS_RATE.clear()


def test_the_rate_limit_is_per_user():
    import api.trading as t

    t._AI_ANALYSIS_RATE.clear()
    for _ in range(t._AI_ANALYSIS_MAX_PER_MIN):
        t._ai_analysis_rate_limit("user-1")
    t._ai_analysis_rate_limit("user-2")  # must not raise
    t._AI_ANALYSIS_RATE.clear()


def test_the_old_implementation_is_gone_not_parked():
    """Dead code kept 'for reference' is how this file reached 230 lines of
    untested maths in the first place."""
    import pathlib

    src = (pathlib.Path(__file__).resolve().parents[2] / "api/trading.py").read_text()
    assert "_legacy_ai_analysis" not in src


# ── The platform regime classifier ───────────────────────────────────────────


def _ohlcv_bars(n=200, start=4000.0, step=4.0):
    return _bars([start + i * step for i in range(n)])


def test_the_platform_classifier_is_used_when_available():
    """nuclear/regime_classifier.py is the real engine — macro override, crisis
    detection, weighted per-timeframe voting, and its own reasoning."""
    from analysis.chart_analysis import classify_regime_platform

    v = classify_regime_platform(_ohlcv_bars(), "XAUUSD")
    assert v is not None, "the platform classifier did not run"
    assert v.regime == "trending_up"
    assert v.reasons, "the platform verdict must carry its reasoning"


def test_the_platform_classifier_reads_a_downtrend_as_a_downtrend():
    from analysis.chart_analysis import classify_regime_platform

    v = classify_regime_platform(_ohlcv_bars(start=4800.0, step=-4.0), "XAUUSD")
    assert v is not None and v.regime == "trending_down"
    assert v.trend == "bearish"


def test_consecutive_calls_do_not_contaminate_each_other():
    """The reason this does NOT go through get_regime_classifier().

    That factory returns a process-wide singleton whose debounce only moves
    _confirmed_regime after three consecutive agreeing calls — correct for the
    streaming agent that calls it once per bar, catastrophic for a per-request
    path, where the first caller's regime pins every later one across unrelated
    users, symbols and timeframes.

    Through the singleton these three series all return trending_up. Through
    fresh instances they classify independently. This test fails if anyone
    swaps in the singleton.
    """
    from analysis.chart_analysis import classify_regime_platform

    up = classify_regime_platform(_ohlcv_bars(), "XAUUSD")
    down = classify_regime_platform(_ohlcv_bars(start=4800.0, step=-4.0), "XAUUSD")
    flat = classify_regime_platform(_ohlcv_bars(step=0.0), "XAUUSD")

    assert up is not None and down is not None and flat is not None
    assert up.regime == "trending_up"
    assert down.regime == "trending_down", (
        "a downtrend was classified as an uptrend — shared debounce state has leaked "
        "between requests (see classify_regime_platform's docstring)"
    )
    assert flat.regime != "trending_up"


def test_the_shared_singleton_is_not_referenced():
    """Pinned as source, because the failure is invisible in a single call."""
    import pathlib

    code = _code_only(pathlib.Path(__file__).resolve().parents[2] / "analysis/chart_analysis.py")
    assert "get_regime_classifier" not in code, "the shared classifier singleton carries debounce state across requests"


def test_a_short_window_skips_the_platform_classifier():
    from analysis.chart_analysis import classify_regime_platform

    assert classify_regime_platform(_ohlcv_bars(10), "XAUUSD") is None


def test_the_local_read_takes_over_when_the_platform_stack_is_missing(monkeypatch):
    """A chart click must not depend on the nuclear stack being importable."""
    import builtins

    real_import = builtins.__import__

    def _blocked(name, *args, **kwargs):
        if name.startswith("nuclear."):
            raise ImportError("simulated: nuclear stack unavailable")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _blocked)

    from analysis.chart_analysis import classify_regime_platform

    assert classify_regime_platform(_ohlcv_bars(), "XAUUSD") is None

    monkeypatch.undo()
    out = compose(_ctx(), _ohlcv_bars(), ModelVerdict(), data_source="price_engine")
    assert out["regime"] in ("trending_up", "trending_down", "ranging", "volatile")


def test_the_response_states_which_regime_engine_spoke():
    out = compose(_ctx(), _ohlcv_bars(), ModelVerdict(), data_source="price_engine")
    assert out["regimeSource"] in ("platform", "local")


def test_the_regime_is_always_one_the_frontend_can_render():
    """The classifier's vocabulary is wider than the UI's MarketRegime union;
    an unmapped value would render as an unstyled string."""
    renderable = {"trending_up", "trending_down", "ranging", "volatile"}
    for bars in (_ohlcv_bars(), _ohlcv_bars(start=4800.0, step=-4.0), _ohlcv_bars(step=0.0), _ohlcv_bars(40)):
        out = compose(_ctx(), bars, ModelVerdict(), data_source="price_engine")
        assert out["regime"] in renderable, out["regime"]
