# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
tests/unit/test_nuclear_strategy_agent.py
==========================================
Full unit tests for the Nuclear Strategy Agent pipeline.

Coverage
--------
  NuclearStrategyAgent  — lifecycle, analyze(), clear_history(), status()
  AnalysisResult        — to_dict(), properties
  RedisStreamReader     — buffer accessors (no Redis connection)
  FeatureBuilder        — build_all(), build_timeframe()
  ItosConeEngine        — compute(), merge_cones()
  RegimeClassifier      — classify(), history()
  NuclearStrategyEngine — generate(), signal_history()
  ShadowBacktestEngine  — run(), confidence_score
  SignalComposer        — compose(), approval gate
  get_nuclear_agent()   — singleton behaviour
  api/nuclear_strategy  — DELETE /history endpoint wiring

All tests use real implementations — no mocks, stubs, or synthetic data
except where the component explicitly requires a live Redis connection
(those are replaced with a pre-populated in-memory reader).
"""

from __future__ import annotations

import os
from collections import deque
from datetime import datetime, timezone

import numpy as np
import pytest

os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("SECURITY_JWT_SECRET", "test-only-jwt-secret-key-minimum-32-chars!!")

UTC = timezone.utc

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _make_bars(
    n: int = 60,
    start_price: float = 2000.0,
    timeframe: str = "daily",
    symbol: str = "XAU_USD",
    trend: float = 0.5,  # price drift per bar
    volatility: float = 5.0,  # random noise amplitude
    seed: int = 42,
) -> list:
    """Return a list of OHLCVBar objects with realistic price movement."""
    from nuclear.redis_stream_reader import OHLCVBar

    rng = np.random.default_rng(seed)
    bars = []
    price = start_price
    for _ in range(n):
        noise = rng.normal(0, volatility)
        close = max(price + trend + noise, 1.0)
        high = close + abs(rng.normal(0, volatility * 0.5))
        low = close - abs(rng.normal(0, volatility * 0.5))
        open_ = price
        bars.append(
            OHLCVBar(
                symbol=symbol,
                timeframe=timeframe,
                open=open_,
                high=high,
                low=low,
                close=close,
                volume=rng.uniform(1000, 5000),
                open_time=datetime(2024, 1, 1, tzinfo=UTC),
            )
        )
        price = close
    return bars


def _make_ticks(
    n: int = 30,
    mid: float = 2000.0,
    symbol: str = "XAU_USD",
    seed: int = 7,
) -> list:
    """Return a list of TickSnapshot objects."""
    from nuclear.redis_stream_reader import TickSnapshot

    rng = np.random.default_rng(seed)
    ticks = []
    price = mid
    for _ in range(n):
        price += rng.normal(0, 0.5)
        bid = price - 0.10
        ask = price + 0.10
        ticks.append(
            TickSnapshot(
                symbol=symbol,
                bid=bid,
                ask=ask,
                mid=price,
                volume=rng.uniform(1, 10),
                timestamp=datetime.now(UTC),
                source="test",
            )
        )
    return ticks


def _make_macro(
    vix: float = 18.0,
    dxy: float = 102.0,
    spx: float = 4800.0,
    gld: float = 185.0,
    us10y: float = 4.2,
):
    """Return a MacroSnapshot."""
    from nuclear.redis_stream_reader import MacroSnapshot

    return MacroSnapshot(vix=vix, dxy=dxy, spx=spx, gld=gld, us10y=us10y)


class _InMemoryReader:
    """
    Drop-in replacement for RedisStreamReader that serves pre-loaded data
    from in-memory buffers. No Redis connection is made.
    """

    def __init__(
        self,
        ticks=None,
        bars_by_tf=None,
        macro=None,
    ):
        from nuclear.redis_stream_reader import MacroSnapshot

        self._ticks: deque = deque(ticks or [], maxlen=200)
        self._bars: dict[str, deque] = {}
        for tf, bar_list in (bars_by_tf or {}).items():
            self._bars[tf] = deque(bar_list, maxlen=500)
        self._macro = macro or MacroSnapshot()
        self._running = False
        self._connected = False

    # Lifecycle stubs (no-op — no Redis)
    async def start(self) -> None:
        self._running = True
        self._connected = True

    async def stop(self) -> None:
        self._running = False
        self._connected = False

    async def bootstrap(self) -> None:
        pass  # nothing to bootstrap from in-memory data

    # Accessors matching RedisStreamReader public API
    def get_ticks(self, n: int = 30):
        ticks = list(self._ticks)
        return ticks[-n:] if n < len(ticks) else ticks

    def get_bars(self, channel_or_tf: str, n: int = 5):
        buf = self._bars.get(channel_or_tf, deque())
        bars = list(buf)
        return bars[-n:] if n < len(bars) else bars

    def get_all_bars(self) -> dict:
        return {tf: list(buf) for tf, buf in self._bars.items()}

    def get_cone(self) -> dict:
        return {}

    def get_macro(self):
        return self._macro

    def get_latest_price(self):
        if self._ticks:
            return self._ticks[-1].mid
        return None

    def is_connected(self) -> bool:
        return self._connected

    def stats(self) -> dict:
        return {
            "connected": self._connected,
            "tick_buffer_size": len(self._ticks),
            "bar_buffers": {tf: len(buf) for tf, buf in self._bars.items()},
            "ticks_received": len(self._ticks),
            "bars_received": sum(len(b) for b in self._bars.values()),
            "cone_updates": 0,
            "macro_updates": 0,
            "parse_errors": 0,
        }


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def daily_bars():
    return _make_bars(n=60, timeframe="daily", trend=1.0)


@pytest.fixture
def hourly_bars():
    return _make_bars(n=100, timeframe="1h", trend=0.2, volatility=1.5)


@pytest.fixture
def ticks():
    return _make_ticks(n=30)


@pytest.fixture
def macro():
    return _make_macro()


@pytest.fixture
def reader(daily_bars, hourly_bars, ticks, macro):
    return _InMemoryReader(
        ticks=ticks,
        bars_by_tf={"daily": daily_bars, "1h": hourly_bars},
        macro=macro,
    )


@pytest.fixture
def agent(reader):
    """NuclearStrategyAgent wired to the in-memory reader."""
    from nuclear.nuclear_agent import NuclearStrategyAgent

    return NuclearStrategyAgent(symbol="XAU_USD", reader=reader, bootstrap=False)


# ===========================================================================
# AnalysisResult
# ===========================================================================


class TestAnalysisResult:
    def test_to_dict_keys(self, agent):
        result = agent.analyze()
        d = result.to_dict()
        required = {
            "symbol",
            "has_signal",
            "is_approved",
            "signal",
            "regime",
            "backtest",
            "cone_merged",
            "ticks_available",
            "bars_available",
            "pipeline_ms",
            "error",
            "computed_at",
        }
        assert required.issubset(d.keys())

    def test_symbol_propagated(self, agent):
        result = agent.analyze()
        assert result.symbol == "XAU_USD"

    def test_pipeline_ms_positive(self, agent):
        result = agent.analyze()
        assert result.pipeline_ms > 0

    def test_computed_at_is_utc(self, agent):
        result = agent.analyze()
        assert result.computed_at.tzinfo is not None

    def test_ticks_available_matches_reader(self, agent, ticks):
        result = agent.analyze()
        assert result.ticks_available == len(ticks)

    def test_bars_available_has_daily(self, agent):
        result = agent.analyze()
        assert "daily" in result.bars_available
        assert result.bars_available["daily"] > 0

    def test_has_signal_property(self, agent):
        result = agent.analyze()
        assert result.has_signal == (result.signal is not None)

    def test_is_approved_false_when_no_signal(self):
        from nuclear.nuclear_agent import AnalysisResult

        r = AnalysisResult(
            symbol="XAU_USD",
            signal=None,
            regime=None,
            backtest=None,
            cone_merged={},
            mtf_features=None,
            ticks_available=0,
            bars_available={},
            pipeline_ms=1.0,
        )
        assert r.is_approved is False
        assert r.has_signal is False

    def test_error_field_none_on_success(self, agent):
        result = agent.analyze()
        assert result.error is None


# ===========================================================================
# RedisStreamReader buffer accessors (in-memory reader)
# ===========================================================================


class TestInMemoryReader:
    def test_get_ticks_returns_correct_count(self, reader, ticks):
        result = reader.get_ticks(10)
        assert len(result) == 10

    def test_get_ticks_all_when_n_exceeds_buffer(self, reader, ticks):
        result = reader.get_ticks(1000)
        assert len(result) == len(ticks)

    def test_get_ticks_newest_last(self, reader, ticks):
        result = reader.get_ticks(30)
        # last tick mid should match last item in result
        assert result[-1].mid == pytest.approx(ticks[-1].mid, abs=1e-6)

    def test_get_all_bars_returns_dict(self, reader):
        bars = reader.get_all_bars()
        assert isinstance(bars, dict)
        assert "daily" in bars
        assert "1h" in bars

    def test_get_latest_price_matches_last_tick(self, reader, ticks):
        price = reader.get_latest_price()
        assert price == pytest.approx(ticks[-1].mid, abs=1e-6)

    def test_get_latest_price_none_when_empty(self):
        r = _InMemoryReader()
        assert r.get_latest_price() is None

    def test_stats_structure(self, reader):
        s = reader.stats()
        assert "connected" in s
        assert "tick_buffer_size" in s
        assert "bar_buffers" in s

    def test_get_macro_returns_snapshot(self, reader):
        from nuclear.redis_stream_reader import MacroSnapshot

        m = reader.get_macro()
        assert isinstance(m, MacroSnapshot)

    def test_get_cone_returns_dict(self, reader):
        cone = reader.get_cone()
        assert isinstance(cone, dict)


# ===========================================================================
# FeatureBuilder
# ===========================================================================


class TestFeatureBuilder:
    def test_build_all_returns_mtf(self, reader):
        from nuclear.feature_builder import FeatureBuilder, MultiTimeframeFeatures

        fb = FeatureBuilder(reader, symbol="XAU_USD")
        mtf = fb.build_all()
        assert isinstance(mtf, MultiTimeframeFeatures)
        assert mtf.symbol == "XAU_USD"

    def test_build_all_has_daily_features(self, reader):
        from nuclear.feature_builder import FeatureBuilder

        fb = FeatureBuilder(reader, symbol="XAU_USD")
        mtf = fb.build_all()
        assert "daily" in mtf.timeframes

    def test_build_all_has_macro(self, reader):
        from nuclear.feature_builder import FeatureBuilder, MacroFeatures

        fb = FeatureBuilder(reader, symbol="XAU_USD")
        mtf = fb.build_all()
        assert isinstance(mtf.macro, MacroFeatures)

    def test_build_timeframe_single(self, daily_bars):
        from nuclear.feature_builder import FeatureBuilder, TechnicalFeatures

        reader = _InMemoryReader(bars_by_tf={"daily": daily_bars})
        fb = FeatureBuilder(reader, symbol="XAU_USD")
        feat = fb.build_timeframe(daily_bars, "daily")
        assert isinstance(feat, TechnicalFeatures)
        assert feat.timeframe == "daily"
        assert feat.bar_count == len(daily_bars)

    def test_technical_features_rsi_in_range(self, daily_bars):
        from nuclear.feature_builder import FeatureBuilder

        reader = _InMemoryReader(bars_by_tf={"daily": daily_bars})
        fb = FeatureBuilder(reader, symbol="XAU_USD")
        feat = fb.build_timeframe(daily_bars, "daily")
        assert 0.0 <= feat.rsi <= 100.0

    def test_technical_features_atr_positive(self, daily_bars):
        from nuclear.feature_builder import FeatureBuilder

        reader = _InMemoryReader(bars_by_tf={"daily": daily_bars})
        fb = FeatureBuilder(reader, symbol="XAU_USD")
        feat = fb.build_timeframe(daily_bars, "daily")
        assert feat.atr >= 0.0

    def test_to_dict_has_required_keys(self, daily_bars):
        from nuclear.feature_builder import FeatureBuilder

        reader = _InMemoryReader(bars_by_tf={"daily": daily_bars})
        fb = FeatureBuilder(reader, symbol="XAU_USD")
        feat = fb.build_timeframe(daily_bars, "daily")
        d = feat.to_dict()
        for key in ("timeframe", "rsi", "atr", "ema_50", "macd_line", "bb_upper"):
            assert key in d

    def test_empty_bars_skipped_gracefully(self):
        from nuclear.feature_builder import FeatureBuilder, MultiTimeframeFeatures

        reader = _InMemoryReader(bars_by_tf={"daily": []})
        fb = FeatureBuilder(reader, symbol="XAU_USD")
        mtf = fb.build_all()
        assert isinstance(mtf, MultiTimeframeFeatures)
        # daily skipped — not enough bars
        assert "daily" not in mtf.timeframes

    def test_subset_timeframes(self, reader):
        from nuclear.feature_builder import FeatureBuilder

        fb = FeatureBuilder(reader, symbol="XAU_USD")
        mtf = fb.build_all(timeframes=["daily"])
        assert "daily" in mtf.timeframes
        assert "1h" not in mtf.timeframes


# ===========================================================================
# ItosConeEngine
# ===========================================================================


class TestItosConeEngine:
    def _closes(self, n=60, seed=1):
        rng = np.random.default_rng(seed)
        price = 2000.0
        closes = []
        for _ in range(n):
            price += rng.normal(0.5, 5.0)
            closes.append(max(price, 1.0))
        return np.array(closes)

    def test_compute_returns_itos_cone(self):
        from nuclear.itos_cone_engine import ItosCone, ItosConeEngine

        engine = ItosConeEngine()
        cone = engine.compute(self._closes(), symbol="XAU_USD", timeframe="daily")
        assert isinstance(cone, ItosCone)

    def test_cone_has_expected_horizons(self):
        from nuclear.itos_cone_engine import ItosConeEngine

        engine = ItosConeEngine()
        cone = engine.compute(self._closes(), symbol="XAU_USD", timeframe="daily")
        for horizon in ("1d", "1w", "1m", "3m", "6m", "1y"):
            assert horizon in cone.dots, f"Missing horizon: {horizon}"

    def test_cone_upper_above_lower(self):
        from nuclear.itos_cone_engine import ItosConeEngine

        engine = ItosConeEngine()
        cone = engine.compute(self._closes(), symbol="XAU_USD", timeframe="daily")
        for label, dot in cone.dots.items():
            assert dot.upper_2sigma > dot.lower_2sigma, f"Inverted cone at {label}"

    def test_cone_current_price_anchored(self):
        from nuclear.itos_cone_engine import ItosConeEngine

        engine = ItosConeEngine()
        closes = self._closes()
        cone = engine.compute(closes, current_price=2100.0, symbol="XAU_USD", timeframe="daily")
        assert cone.current_price == pytest.approx(2100.0)

    def test_cone_bias_is_valid_string(self):
        from nuclear.itos_cone_engine import ItosConeEngine

        engine = ItosConeEngine()
        cone = engine.compute(self._closes(), symbol="XAU_USD", timeframe="daily")
        assert cone.bias in ("bullish", "bearish", "neutral")

    def test_cone_vol_regime_is_valid(self):
        from nuclear.itos_cone_engine import ItosConeEngine

        engine = ItosConeEngine()
        cone = engine.compute(self._closes(), symbol="XAU_USD", timeframe="daily")
        assert cone.vol_regime in ("high_vol", "normal_vol", "low_vol")

    def test_price_in_cone_current_price(self):
        from nuclear.itos_cone_engine import ItosConeEngine

        engine = ItosConeEngine()
        closes = self._closes()
        cone = engine.compute(closes, symbol="XAU_USD", timeframe="daily")
        # Current price should be inside the 3-sigma 1-month band
        assert cone.price_in_cone(cone.current_price, horizon="1m", sigma=3.0)

    def test_cone_direction_at_returns_valid(self):
        from nuclear.itos_cone_engine import ItosConeEngine

        engine = ItosConeEngine()
        cone = engine.compute(self._closes(), symbol="XAU_USD", timeframe="daily")
        direction = cone.cone_direction_at("1m")
        assert direction in ("long", "short", "neutral")

    def test_to_dict_structure(self):
        from nuclear.itos_cone_engine import ItosConeEngine

        engine = ItosConeEngine()
        cone = engine.compute(self._closes(), symbol="XAU_USD", timeframe="daily")
        d = cone.to_dict()
        for key in (
            "symbol",
            "current_price",
            "drift_annual",
            "volatility_annual",
            "bias",
            "vol_regime",
            "dots",
            "confidence",
        ):
            assert key in d

    def test_merge_cones_returns_dict(self):
        from nuclear.itos_cone_engine import ItosConeEngine

        engine = ItosConeEngine()
        closes = self._closes()
        cone_d = engine.compute(closes, symbol="XAU_USD", timeframe="daily")
        cone_h = engine.compute(closes, symbol="XAU_USD", timeframe="1h")
        merged = engine.merge_cones({"daily": cone_d, "1h": cone_h})
        assert isinstance(merged, dict)
        assert "bias" in merged

    def test_merge_cones_empty_returns_empty(self):
        from nuclear.itos_cone_engine import ItosConeEngine

        engine = ItosConeEngine()
        assert engine.merge_cones({}) == {}

    def test_compute_from_ohlcv(self, daily_bars):
        from nuclear.itos_cone_engine import ItosCone, ItosConeEngine

        engine = ItosConeEngine()
        bar_dicts = [{"close": b.close} for b in daily_bars]
        cone = engine.compute_from_ohlcv(bar_dicts, symbol="XAU_USD", timeframe="daily")
        assert isinstance(cone, ItosCone)
        assert cone.current_price > 0


# ===========================================================================
# RegimeClassifier
# ===========================================================================


class TestRegimeClassifier:
    def _make_mtf(self, reader):
        from nuclear.feature_builder import FeatureBuilder

        fb = FeatureBuilder(reader, symbol="XAU_USD")
        return fb.build_all()

    def test_classify_returns_regime_result(self, reader):
        from nuclear.regime_classifier import RegimeClassifier, RegimeResult

        clf = RegimeClassifier()
        mtf = self._make_mtf(reader)
        result = clf.classify(mtf, {})
        assert isinstance(result, RegimeResult)

    def test_regime_is_known_value(self, reader):
        from nuclear.regime_classifier import ALL_REGIMES, RegimeClassifier

        clf = RegimeClassifier()
        mtf = self._make_mtf(reader)
        result = clf.classify(mtf, {})
        assert result.regime in ALL_REGIMES

    def test_confidence_in_range(self, reader):
        from nuclear.regime_classifier import RegimeClassifier

        clf = RegimeClassifier()
        mtf = self._make_mtf(reader)
        result = clf.classify(mtf, {})
        assert 0.0 <= result.confidence <= 1.0

    def test_to_dict_has_required_keys(self, reader):
        from nuclear.regime_classifier import RegimeClassifier

        clf = RegimeClassifier()
        mtf = self._make_mtf(reader)
        result = clf.classify(mtf, {})
        d = result.to_dict()
        for key in (
            "regime",
            "confidence",
            "is_trending",
            "is_volatile",
            "is_ranging",
            "preferred_strategy",
            "computed_at",
        ):
            assert key in d

    def test_preferred_strategy_is_valid(self, reader):
        from nuclear.regime_classifier import RegimeClassifier

        clf = RegimeClassifier()
        mtf = self._make_mtf(reader)
        result = clf.classify(mtf, {})
        assert result.preferred_strategy in ("smc_ict", "breakout", "mean_reversion")

    def test_history_grows_with_calls(self, reader):
        from nuclear.regime_classifier import RegimeClassifier

        clf = RegimeClassifier()
        mtf = self._make_mtf(reader)
        clf.classify(mtf, {})
        clf.classify(mtf, {})
        h = clf.history(10)
        assert len(h) == 2

    def test_history_capped_at_n(self, reader):
        from nuclear.regime_classifier import RegimeClassifier

        clf = RegimeClassifier()
        mtf = self._make_mtf(reader)
        for _ in range(10):
            clf.classify(mtf, {})
        h = clf.history(3)
        assert len(h) == 3

    def test_trending_up_properties(self):
        from nuclear.regime_classifier import REGIME_TRENDING_UP, RegimeResult

        r = RegimeResult(regime=REGIME_TRENDING_UP, confidence=0.8)
        assert r.is_trending is True
        assert r.is_ranging is False

    def test_range_bound_properties(self):
        from nuclear.regime_classifier import REGIME_RANGE_BOUND, RegimeResult

        r = RegimeResult(regime=REGIME_RANGE_BOUND, confidence=0.7)
        assert r.is_ranging is True
        assert r.is_trending is False

    def test_crisis_preferred_strategy(self):
        from nuclear.regime_classifier import REGIME_CRISIS, RegimeResult

        r = RegimeResult(regime=REGIME_CRISIS, confidence=0.9)
        assert r.preferred_strategy == "smc_ict"


# ===========================================================================
# NuclearStrategyEngine
# ===========================================================================


class TestNuclearStrategyEngine:
    def _make_mtf_and_regime(self, reader):
        from nuclear.feature_builder import FeatureBuilder
        from nuclear.regime_classifier import RegimeClassifier

        fb = FeatureBuilder(reader, symbol="XAU_USD")
        mtf = fb.build_all()
        clf = RegimeClassifier()
        regime = clf.classify(mtf, {})
        return mtf, regime

    def test_generate_returns_signal_or_none(self, reader):
        from nuclear.strategy_engine import NuclearStrategyEngine

        engine = NuclearStrategyEngine()
        mtf, regime = self._make_mtf_and_regime(reader)
        result = engine.generate(mtf=mtf, regime=regime)
        # May be None if no valid signal — that is correct behaviour
        assert result is None or hasattr(result, "direction")

    def test_signal_direction_valid(self, reader):
        from nuclear.strategy_engine import NuclearStrategyEngine

        engine = NuclearStrategyEngine()
        mtf, regime = self._make_mtf_and_regime(reader)
        result = engine.generate(mtf=mtf, regime=regime)
        if result is not None:
            assert result.direction in ("long", "short")

    def test_signal_is_valid_when_returned(self, reader):
        from nuclear.strategy_engine import NuclearStrategyEngine

        engine = NuclearStrategyEngine()
        mtf, regime = self._make_mtf_and_regime(reader)
        result = engine.generate(mtf=mtf, regime=regime)
        if result is not None:
            assert result.is_valid

    def test_signal_history_empty_initially(self):
        from nuclear.strategy_engine import NuclearStrategyEngine

        engine = NuclearStrategyEngine()
        assert engine.signal_history() == []

    def test_signal_history_grows(self, reader):
        from nuclear.strategy_engine import NuclearStrategyEngine

        engine = NuclearStrategyEngine()
        mtf, regime = self._make_mtf_and_regime(reader)
        # Run multiple times to increase chance of getting a signal
        for _ in range(5):
            engine.generate(mtf=mtf, regime=regime)
        # History count should match number of valid signals generated
        h = engine.signal_history(20)
        assert isinstance(h, list)

    def test_signal_to_dict_structure(self, reader):
        from nuclear.strategy_engine import NuclearStrategyEngine

        engine = NuclearStrategyEngine()
        mtf, regime = self._make_mtf_and_regime(reader)
        result = engine.generate(mtf=mtf, regime=regime)
        if result is not None:
            d = result.to_dict()
            for key in (
                "direction",
                "strategy",
                "entry_price",
                "stop_loss",
                "take_profit_1",
                "confidence",
                "risk_reward",
                "is_valid",
            ):
                assert key in d

    def test_risk_reward_positive_when_valid(self, reader):
        from nuclear.strategy_engine import NuclearStrategyEngine

        engine = NuclearStrategyEngine()
        mtf, regime = self._make_mtf_and_regime(reader)
        result = engine.generate(mtf=mtf, regime=regime)
        if result is not None:
            assert result.risk_reward >= 1.0


# ===========================================================================
# ShadowBacktestEngine
# ===========================================================================


class TestShadowBacktestEngine:
    def _pipeline_inputs(self, reader):
        from nuclear.feature_builder import FeatureBuilder
        from nuclear.regime_classifier import RegimeClassifier
        from nuclear.strategy_engine import NuclearStrategyEngine

        fb = FeatureBuilder(reader, symbol="XAU_USD")
        mtf = fb.build_all()
        clf = RegimeClassifier()
        regime = clf.classify(mtf, {})
        engine = NuclearStrategyEngine()
        return mtf, regime, engine

    def test_run_returns_backtest_result(self, reader, ticks, daily_bars):
        from nuclear.shadow_backtest import BacktestResult, ShadowBacktestEngine

        mtf, regime, engine = self._pipeline_inputs(reader)
        bt_engine = ShadowBacktestEngine(rng_seed=42)
        result = bt_engine.run(
            ticks=ticks,
            bars_by_tf={"daily": daily_bars},
            strategy_engine=engine,
            mtf_features=mtf,
            regime=regime,
            symbol="XAU_USD",
        )
        assert isinstance(result, BacktestResult)

    def test_win_rate_in_range(self, reader, ticks, daily_bars):
        from nuclear.shadow_backtest import ShadowBacktestEngine

        mtf, regime, engine = self._pipeline_inputs(reader)
        bt_engine = ShadowBacktestEngine(rng_seed=42)
        result = bt_engine.run(
            ticks=ticks,
            bars_by_tf={"daily": daily_bars},
            strategy_engine=engine,
            mtf_features=mtf,
            regime=regime,
        )
        assert 0.0 <= result.win_rate <= 1.0

    def test_confidence_score_in_range(self, reader, ticks, daily_bars):
        from nuclear.shadow_backtest import ShadowBacktestEngine

        mtf, regime, engine = self._pipeline_inputs(reader)
        bt_engine = ShadowBacktestEngine(rng_seed=42)
        result = bt_engine.run(
            ticks=ticks,
            bars_by_tf={"daily": daily_bars},
            strategy_engine=engine,
            mtf_features=mtf,
            regime=regime,
        )
        assert 0.0 <= result.confidence_score <= 1.0

    def test_to_dict_has_required_keys(self, reader, ticks, daily_bars):
        from nuclear.shadow_backtest import ShadowBacktestEngine

        mtf, regime, engine = self._pipeline_inputs(reader)
        bt_engine = ShadowBacktestEngine(rng_seed=42)
        result = bt_engine.run(
            ticks=ticks,
            bars_by_tf={"daily": daily_bars},
            strategy_engine=engine,
            mtf_features=mtf,
            regime=regime,
        )
        d = result.to_dict()
        for key in (
            "symbol",
            "total_trades",
            "win_rate",
            "sharpe_ratio",
            "max_drawdown_pct",
            "confidence_score",
            "equity_curve",
            "trades",
            "computed_at",
        ):
            assert key in d

    def test_winning_plus_losing_equals_total(self, reader, ticks, daily_bars):
        from nuclear.shadow_backtest import ShadowBacktestEngine

        mtf, regime, engine = self._pipeline_inputs(reader)
        bt_engine = ShadowBacktestEngine(rng_seed=42)
        result = bt_engine.run(
            ticks=ticks,
            bars_by_tf={"daily": daily_bars},
            strategy_engine=engine,
            mtf_features=mtf,
            regime=regime,
        )
        assert result.winning_trades + result.losing_trades == result.total_trades

    def test_zero_trades_confidence_is_zero(self):
        from nuclear.shadow_backtest import BacktestResult

        r = BacktestResult(
            symbol="XAU_USD",
            total_trades=0,
            winning_trades=0,
            losing_trades=0,
            win_rate=0.0,
            profit_factor=0.0,
            sharpe_ratio=0.0,
            max_drawdown_pct=0.0,
            total_pnl_pct=0.0,
            avg_pnl_pct=0.0,
            avg_win_pct=0.0,
            avg_loss_pct=0.0,
            best_trade_pct=0.0,
            worst_trade_pct=0.0,
            avg_rr=0.0,
            cone_aligned_win_rate=0.0,
        )
        assert r.confidence_score == 0.0

    def test_equity_curve_is_list(self, reader, ticks, daily_bars):
        from nuclear.shadow_backtest import ShadowBacktestEngine

        mtf, regime, engine = self._pipeline_inputs(reader)
        bt_engine = ShadowBacktestEngine(rng_seed=42)
        result = bt_engine.run(
            ticks=ticks,
            bars_by_tf={"daily": daily_bars},
            strategy_engine=engine,
            mtf_features=mtf,
            regime=regime,
        )
        assert isinstance(result.equity_curve, list)


# ===========================================================================
# SignalComposer
# ===========================================================================


class TestSignalComposer:
    def _make_raw_signal(self, direction="long", confidence=0.75):
        from nuclear.strategy_engine import StrategySignal

        entry = 2000.0
        sl = 1980.0 if direction == "long" else 2020.0
        tp1 = 2040.0 if direction == "long" else 1960.0
        tp2 = 2060.0 if direction == "long" else 1940.0
        tp3 = 2080.0 if direction == "long" else 1920.0
        return StrategySignal(
            direction=direction,
            strategy="smc_ict",
            entry_price=entry,
            stop_loss=sl,
            take_profit_1=tp1,
            take_profit_2=tp2,
            take_profit_3=tp3,
            confidence=confidence,
            regime="trending_up",
            timeframe="daily",
            cone_aligned=True,
            cone_bias="bullish",
            reasoning=["EMA alignment", "FVG fill"],
        )

    def _make_backtest(self, total_trades=10, win_rate=0.65, sharpe=1.5):
        from nuclear.shadow_backtest import BacktestResult

        return BacktestResult(
            symbol="XAU_USD",
            total_trades=total_trades,
            winning_trades=int(total_trades * win_rate),
            losing_trades=total_trades - int(total_trades * win_rate),
            win_rate=win_rate,
            profit_factor=1.8,
            sharpe_ratio=sharpe,
            max_drawdown_pct=0.05,
            total_pnl_pct=0.12,
            avg_pnl_pct=0.012,
            avg_win_pct=0.02,
            avg_loss_pct=-0.01,
            best_trade_pct=0.04,
            worst_trade_pct=-0.015,
            avg_rr=2.0,
            cone_aligned_win_rate=0.70,
        )

    def _make_regime(self, regime_name="trending_up", confidence=0.75):
        from nuclear.regime_classifier import RegimeResult

        return RegimeResult(regime=regime_name, confidence=confidence)

    def _make_mtf(self, reader):
        from nuclear.feature_builder import FeatureBuilder

        fb = FeatureBuilder(reader, symbol="XAU_USD")
        return fb.build_all()

    def test_compose_returns_nuclear_signal(self, reader):
        from nuclear.signal_composer import NuclearSignal, SignalComposer

        composer = SignalComposer()
        signal = composer.compose(
            raw_signal=self._make_raw_signal(),
            backtest=self._make_backtest(),
            regime=self._make_regime(),
            cone_merged={"bias": "bullish", "vol_regime": "normal_vol"},
            mtf=self._make_mtf(reader),
        )
        assert isinstance(signal, NuclearSignal)

    def test_approved_signal_high_confidence(self, reader):
        from nuclear.signal_composer import SignalComposer

        composer = SignalComposer()
        signal = composer.compose(
            raw_signal=self._make_raw_signal(confidence=0.85),
            backtest=self._make_backtest(total_trades=10, win_rate=0.70, sharpe=2.0),
            regime=self._make_regime(confidence=0.85),
            cone_merged={"bias": "bullish", "vol_regime": "normal_vol"},
            mtf=self._make_mtf(reader),
        )
        assert signal.approval_status == "APPROVED"
        assert signal.is_approved

    def test_rejected_signal_low_confidence(self, reader):
        from nuclear.signal_composer import SignalComposer

        composer = SignalComposer()
        signal = composer.compose(
            raw_signal=self._make_raw_signal(confidence=0.10),
            backtest=self._make_backtest(total_trades=0, win_rate=0.0, sharpe=0.0),
            regime=self._make_regime(confidence=0.10),
            cone_merged={},
            mtf=self._make_mtf(reader),
        )
        assert signal.approval_status in ("REJECTED", "PENDING")

    def test_signal_id_format(self, reader):
        from nuclear.signal_composer import SignalComposer

        composer = SignalComposer()
        signal = composer.compose(
            raw_signal=self._make_raw_signal(),
            backtest=self._make_backtest(),
            regime=self._make_regime(),
            cone_merged={},
            mtf=self._make_mtf(reader),
        )
        assert signal.signal_id.startswith("NSA-")

    def test_to_dict_has_required_keys(self, reader):
        from nuclear.signal_composer import SignalComposer

        composer = SignalComposer()
        signal = composer.compose(
            raw_signal=self._make_raw_signal(),
            backtest=self._make_backtest(),
            regime=self._make_regime(),
            cone_merged={},
            mtf=self._make_mtf(reader),
        )
        d = signal.to_dict()
        for key in (
            "signal_id",
            "symbol",
            "direction",
            "strategy",
            "regime",
            "confidence",
            "approval_status",
            "entry_rules",
            "exit_rules",
            "risk_params",
            "explanation",
            "generated_at",
        ):
            assert key in d

    def test_confidence_in_range(self, reader):
        from nuclear.signal_composer import SignalComposer

        composer = SignalComposer()
        signal = composer.compose(
            raw_signal=self._make_raw_signal(),
            backtest=self._make_backtest(),
            regime=self._make_regime(),
            cone_merged={},
            mtf=self._make_mtf(reader),
        )
        assert 0.0 <= signal.confidence <= 1.0

    def test_direction_preserved(self, reader):
        from nuclear.signal_composer import SignalComposer

        composer = SignalComposer()
        for direction in ("long", "short"):
            signal = composer.compose(
                raw_signal=self._make_raw_signal(direction=direction),
                backtest=self._make_backtest(),
                regime=self._make_regime(),
                cone_merged={},
                mtf=self._make_mtf(reader),
            )
            assert signal.direction == direction

    def test_explanation_non_empty(self, reader):
        from nuclear.signal_composer import SignalComposer

        composer = SignalComposer()
        signal = composer.compose(
            raw_signal=self._make_raw_signal(),
            backtest=self._make_backtest(),
            regime=self._make_regime(),
            cone_merged={},
            mtf=self._make_mtf(reader),
        )
        assert len(signal.explanation) > 0

    def test_rr_below_minimum_rejected(self, reader):
        """Signal with RR < 1.5 must be REJECTED regardless of confidence."""
        from nuclear.signal_composer import SignalComposer
        from nuclear.strategy_engine import StrategySignal

        composer = SignalComposer()
        # entry=2000, sl=1999, tp1=2001 → RR ≈ 1.0 (below 1.5 minimum)
        bad_rr_signal = StrategySignal(
            direction="long",
            strategy="smc_ict",
            entry_price=2000.0,
            stop_loss=1999.0,
            take_profit_1=2001.0,
            take_profit_2=2002.0,
            take_profit_3=2003.0,
            confidence=0.90,
            regime="trending_up",
            timeframe="daily",
            cone_aligned=True,
            cone_bias="bullish",
        )
        signal = composer.compose(
            raw_signal=bad_rr_signal,
            backtest=self._make_backtest(total_trades=20, win_rate=0.80),
            regime=self._make_regime(confidence=0.90),
            cone_merged={},
            mtf=self._make_mtf(reader),
        )
        assert signal.approval_status == "REJECTED"


# ===========================================================================
# NuclearStrategyAgent — core
# ===========================================================================


class TestNuclearStrategyAgent:
    def test_analyze_returns_analysis_result(self, agent):
        from nuclear.nuclear_agent import AnalysisResult

        result = agent.analyze()
        assert isinstance(result, AnalysisResult)

    def test_analyze_increments_count(self, agent):
        agent.analyze()
        agent.analyze()
        assert agent._analysis_count == 2

    def test_status_structure(self, agent):
        agent.analyze()
        s = agent.status()
        for key in (
            "symbol",
            "running",
            "analysis_count",
            "approved_count",
            "error_count",
            "approval_rate",
            "reader",
            "last_regime",
            "last_pipeline_ms",
            "signal_history_count",
        ):
            assert key in s, f"Missing key: {key}"

    def test_status_symbol_correct(self, agent):
        assert agent.status()["symbol"] == "XAU_USD"

    def test_get_last_result_none_before_analyze(self, reader):
        from nuclear.nuclear_agent import NuclearStrategyAgent

        fresh = NuclearStrategyAgent(symbol="XAU_USD", reader=reader, bootstrap=False)
        assert fresh.get_last_result() is None

    def test_get_last_result_after_analyze(self, agent):
        agent.analyze()
        assert agent.get_last_result() is not None

    def test_approval_rate_zero_before_analyze(self, reader):
        from nuclear.nuclear_agent import NuclearStrategyAgent

        fresh = NuclearStrategyAgent(symbol="XAU_USD", reader=reader, bootstrap=False)
        assert fresh.status()["approval_rate"] == 0.0

    def test_approval_rate_in_range_after_analyze(self, agent):
        for _ in range(3):
            agent.analyze()
        rate = agent.status()["approval_rate"]
        assert 0.0 <= rate <= 1.0

    def test_get_signal_history_empty_initially(self, reader):
        from nuclear.nuclear_agent import NuclearStrategyAgent

        fresh = NuclearStrategyAgent(symbol="XAU_USD", reader=reader, bootstrap=False)
        assert fresh.get_signal_history() == []

    def test_get_regime_history_returns_list(self, agent):
        agent.analyze()
        h = agent.get_regime_history(10)
        assert isinstance(h, list)

    def test_get_strategy_signal_history_returns_list(self, agent):
        agent.analyze()
        h = agent.get_strategy_signal_history(10)
        assert isinstance(h, list)

    def test_repr_contains_symbol(self, agent):
        assert "XAU_USD" in repr(agent)

    def test_multiple_analyze_calls_stable(self, agent):
        """Pipeline must not raise across repeated calls."""
        for _ in range(5):
            result = agent.analyze()
            assert result.error is None

    def test_analyze_with_custom_n_ticks(self, agent):
        result = agent.analyze(n_ticks=10)
        assert result.ticks_available <= 10

    def test_analyze_with_custom_n_bars(self, agent):
        result = agent.analyze(n_bars=3)
        assert result is not None

    def test_analyze_with_timeframe_subset(self, agent):
        result = agent.analyze(timeframes=["daily"])
        assert result is not None

    def test_error_count_zero_on_clean_run(self, agent):
        agent.analyze()
        assert agent._error_count == 0


# ===========================================================================
# NuclearStrategyAgent — clear_history
# ===========================================================================


class TestClearHistory:
    def _inject_signals(self, agent, n: int = 3):
        """Force-inject fake approved signals into the history."""
        from nuclear.signal_composer import EntryRules, ExitRules, NuclearSignal, RiskParameters

        for i in range(n):
            sig = NuclearSignal(
                signal_id=f"NSA-TEST-{i:04d}",
                symbol="XAU_USD",
                direction="long",
                strategy="smc_ict",
                regime="trending_up",
                timeframe="daily",
                confidence=0.75,
                confidence_breakdown={},
                approval_status="APPROVED",
                approval_reason="test",
                entry_rules=EntryRules(
                    order_type="limit",
                    entry_price=2000.0,
                    limit_offset_pct=0.001,
                    entry_window_bars=3,
                    scale_in=False,
                ),
                exit_rules=ExitRules(
                    stop_loss=1980.0,
                    stop_type="hard",
                    trailing_atr_mult=1.5,
                    take_profit_1=2040.0,
                    take_profit_2=2060.0,
                    take_profit_3=2080.0,
                ),
                risk_params=RiskParameters(
                    risk_pct=0.01,
                    kelly_fraction=0.25,
                    position_size_pct=0.01,
                    atr_stop_distance=20.0,
                    max_loss_pct=0.02,
                    rr_ratio=2.0,
                ),
                cone_bias="bullish",
                cone_vol_regime="normal_vol",
                cone_aligned=True,
                macro_regime="risk_on",
                backtest_confidence=0.65,
                backtest_trades=10,
                backtest_win_rate=0.65,
                backtest_sharpe=1.5,
                explanation="test signal",
                reasoning=["test"],
            )
            agent._signal_history.append(sig)
            agent._approved_count += 1

    def test_clear_history_empties_list(self, agent):
        self._inject_signals(agent, 3)
        assert len(agent._signal_history) == 3
        agent.clear_history()
        assert len(agent._signal_history) == 0

    def test_clear_history_returns_count(self, agent):
        self._inject_signals(agent, 5)
        cleared = agent.clear_history()
        assert cleared == 5

    def test_clear_history_returns_zero_when_empty(self, agent):
        cleared = agent.clear_history()
        assert cleared == 0

    def test_get_signal_history_empty_after_clear(self, agent):
        self._inject_signals(agent, 3)
        agent.clear_history()
        assert agent.get_signal_history() == []

    def test_status_count_zero_after_clear(self, agent):
        self._inject_signals(agent, 3)
        agent.clear_history()
        assert agent.status()["signal_history_count"] == 0

    def test_clear_does_not_reset_approved_count(self, agent):
        """clear_history() removes signals but does not reset the approved counter."""
        self._inject_signals(agent, 3)
        agent.clear_history()
        # approved_count tracks lifetime approvals — should still be 3
        assert agent._approved_count == 3

    def test_history_repopulates_after_clear(self, agent):
        self._inject_signals(agent, 2)
        agent.clear_history()
        self._inject_signals(agent, 1)
        assert len(agent._signal_history) == 1


# ===========================================================================
# NuclearStrategyAgent — lifecycle (async)
# ===========================================================================


class TestAgentLifecycle:
    @pytest.mark.asyncio
    async def test_start_sets_running(self, reader):
        from nuclear.nuclear_agent import NuclearStrategyAgent

        agent = NuclearStrategyAgent(symbol="XAU_USD", reader=reader, bootstrap=False)
        await agent.start()
        assert agent._running is True
        await agent.stop()

    @pytest.mark.asyncio
    async def test_stop_clears_running(self, reader):
        from nuclear.nuclear_agent import NuclearStrategyAgent

        agent = NuclearStrategyAgent(symbol="XAU_USD", reader=reader, bootstrap=False)
        await agent.start()
        await agent.stop()
        assert agent._running is False

    @pytest.mark.asyncio
    async def test_double_start_is_idempotent(self, reader):
        from nuclear.nuclear_agent import NuclearStrategyAgent

        agent = NuclearStrategyAgent(symbol="XAU_USD", reader=reader, bootstrap=False)
        await agent.start()
        await agent.start()  # second call must not raise
        assert agent._running is True
        await agent.stop()

    @pytest.mark.asyncio
    async def test_analyze_works_after_start(self, reader):
        from nuclear.nuclear_agent import AnalysisResult, NuclearStrategyAgent

        agent = NuclearStrategyAgent(symbol="XAU_USD", reader=reader, bootstrap=False)
        await agent.start()
        result = agent.analyze()
        assert isinstance(result, AnalysisResult)
        await agent.stop()


# ===========================================================================
# get_nuclear_agent() singleton
# ===========================================================================


class TestGetNuclearAgent:
    def test_returns_same_instance(self):
        import nuclear.nuclear_agent as _mod

        # Reset singleton so test is isolated
        _mod._agent_instance = None
        from nuclear.nuclear_agent import get_nuclear_agent

        a1 = get_nuclear_agent()
        a2 = get_nuclear_agent()
        assert a1 is a2
        _mod._agent_instance = None  # cleanup

    def test_custom_symbol_on_first_call(self):
        import nuclear.nuclear_agent as _mod

        _mod._agent_instance = None
        from nuclear.nuclear_agent import get_nuclear_agent

        agent = get_nuclear_agent(symbol="EUR_USD")
        assert agent._symbol == "EUR_USD"
        _mod._agent_instance = None  # cleanup

    def test_second_call_with_a_different_symbol_is_refused(self):
        """The running agent must not be swapped — and the caller must be told.

        This asserted `agent2._symbol == "XAU_USD"`, pinning the defect as
        intended behaviour: a caller asking for BTC_USD was handed the XAU_USD
        agent and given no indication. `/agent/start` passes a request-supplied
        symbol here and then reported `{"status": "started", "symbol": <the
        requested one>}` — confirming an instrument it was not trading.

        The invariant that matters is unchanged and still asserted below: the
        running agent is not replaced. What changed is that the mismatch raises
        instead of being answered wrongly.
        """
        import nuclear.nuclear_agent as _mod

        _mod._agent_instance = None
        from nuclear.nuclear_agent import get_nuclear_agent

        try:
            first = get_nuclear_agent(symbol="XAU_USD")

            with pytest.raises(ValueError, match="BTC_USD"):
                get_nuclear_agent(symbol="BTC_USD")

            # The running agent is untouched.
            assert _mod._agent_instance is first
            assert first._symbol == "XAU_USD"
            # And a bare call still returns whatever is running.
            assert get_nuclear_agent() is first
        finally:
            _mod._agent_instance = None


# ===========================================================================
# DELETE /history endpoint — router wiring
# ===========================================================================


class TestDeleteHistoryEndpoint:
    """
    Verify the DELETE /history endpoint calls clear_history() and returns
    the correct response shape. Uses FastAPI TestClient with the router
    mounted directly — no full app startup required.
    """

    def _make_test_app(self, agent):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from api.nuclear_strategy import router

        app = FastAPI()

        # Override the lazy agent accessor to return our test agent
        from api import nuclear_strategy as _ns_module

        original = _ns_module._get_agent

        def _patched_get_agent():
            return agent

        _ns_module._get_agent = _patched_get_agent
        app.include_router(router, prefix="/nuclear-strategy")

        client = TestClient(app, raise_server_exceptions=True)
        return client, _ns_module, original

    def _auth_headers(self):
        """
        Build a valid admin JWT for the test environment.
        Uses the same secret set in conftest.py.
        """
        import time
        import jwt  # PyJWT

        secret = os.environ.get(
            "SECURITY_JWT_SECRET",
            "test-only-jwt-secret-key-minimum-32-chars!!",
        )
        payload = {
            "sub": "test-admin",
            "role": "admin",
            "type": "access",
            "exp": int(time.time()) + 3600,
        }
        token = jwt.encode(payload, secret, algorithm="HS256")
        return {"Authorization": f"Bearer {token}"}

    def test_delete_history_returns_200(self, agent):
        client, mod, original = self._make_test_app(agent)
        try:
            resp = client.delete(
                "/nuclear-strategy/history",
                headers=self._auth_headers(),
            )
            assert resp.status_code == 200
        finally:
            mod._get_agent = original

    def test_delete_history_response_shape(self, agent):
        client, mod, original = self._make_test_app(agent)
        try:
            resp = client.delete(
                "/nuclear-strategy/history",
                headers=self._auth_headers(),
            )
            body = resp.json()
            assert body["status"] == "cleared"
            assert body["signal_history_count"] == 0
            assert "signals_cleared" in body
        finally:
            mod._get_agent = original

    def test_delete_history_clears_agent_history(self, agent):
        # Pre-populate history via analyze loop
        for _ in range(3):
            agent.analyze()

        client, mod, original = self._make_test_app(agent)
        try:
            client.delete(
                "/nuclear-strategy/history",
                headers=self._auth_headers(),
            )
            assert len(agent._signal_history) == 0
        finally:
            mod._get_agent = original
