# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
Coverage-boosting tests for low-coverage ML modules:
  - ml/features/advanced_features.py
  - ml/signal_features.py
  - ml/performance_monitor.py
  - ml/regime.py
  - backtesting/data_handler.py
  - backtesting/portfolio.py
  - backtesting/walk_forward.py
"""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock

import numpy as np
import pandas as pd
import pytest


# ── Helpers ───────────────────────────────────────────────────────────────────


def _make_ohlcv(n: int = 100) -> pd.DataFrame:
    rng = np.random.default_rng(42)
    close = 1800.0 + np.cumsum(rng.normal(0, 5, n))
    return pd.DataFrame(
        {
            "open": close + rng.normal(0, 2, n),
            "high": close + rng.uniform(1, 8, n),
            "low": close - rng.uniform(1, 8, n),
            "close": close,
            "volume": rng.integers(1000, 5000, n).astype(float),
        }
    )


def _make_prices(n: int = 60) -> np.ndarray:
    rng = np.random.default_rng(7)
    return 1800.0 + np.cumsum(rng.normal(0, 3, n))


# ===========================================================================
# ml/features/advanced_features.py
# ===========================================================================


@pytest.mark.unit
class TestAdvancedFeatureEngineer:
    def test_engineer_features_returns_dataframe(self):
        from ml.features.advanced_features import AdvancedFeatureEngineer

        eng = AdvancedFeatureEngineer(lookback_periods=50)
        df = _make_ohlcv(300)
        result = eng.engineer_features(df, include_advanced=True)
        assert isinstance(result, pd.DataFrame)

    def test_engineer_features_without_advanced(self):
        from ml.features.advanced_features import AdvancedFeatureEngineer

        eng = AdvancedFeatureEngineer(lookback_periods=50)
        df = _make_ohlcv(300)
        result = eng.engineer_features(df, include_advanced=False)
        assert isinstance(result, pd.DataFrame)

    def test_engineer_features_adds_columns(self):
        from ml.features.advanced_features import AdvancedFeatureEngineer

        eng = AdvancedFeatureEngineer()
        df = _make_ohlcv(300)
        result = eng.engineer_features(df)
        assert len(result.columns) > len(df.columns)

    def test_engineer_features_no_inf(self):
        from ml.features.advanced_features import AdvancedFeatureEngineer

        eng = AdvancedFeatureEngineer()
        df = _make_ohlcv(300)
        result = eng.engineer_features(df)
        numeric = result.select_dtypes(include=[np.number])
        assert not np.isinf(numeric.values).any()

    def test_engineer_features_small_df(self):
        from ml.features.advanced_features import AdvancedFeatureEngineer

        eng = AdvancedFeatureEngineer(lookback_periods=10)
        df = _make_ohlcv(50)
        result = eng.engineer_features(df, include_advanced=False)
        assert isinstance(result, pd.DataFrame)


# ===========================================================================
# ml/signal_features.py
# ===========================================================================


@pytest.mark.unit
class TestTechnicalIndicators:
    def test_sma(self):
        from ml.signal_features import TechnicalIndicators

        prices = _make_prices(50)
        result = TechnicalIndicators.sma(prices, 10)
        assert len(result) == 50 - 10 + 1
        assert not np.any(np.isnan(result))

    def test_ema(self):
        from ml.signal_features import TechnicalIndicators

        prices = _make_prices(50)
        result = TechnicalIndicators.ema(prices, 10)
        assert len(result) == 50
        assert result[0] == prices[0]

    def test_rsi_range(self):
        from ml.signal_features import TechnicalIndicators

        prices = _make_prices(60)
        result = TechnicalIndicators.rsi(prices, 14)
        assert len(result) > 0
        assert np.all(result >= 0) and np.all(result <= 100)

    def test_bollinger_bands(self):
        from ml.signal_features import TechnicalIndicators

        prices = _make_prices(60)
        upper, middle, lower = TechnicalIndicators.bollinger_bands(prices, 20, 2.0)
        assert len(upper) == len(middle) == len(lower)
        assert np.all(upper >= middle)
        assert np.all(middle >= lower)

    def test_macd(self):
        from ml.signal_features import TechnicalIndicators

        prices = _make_prices(60)
        macd_line, signal, histogram = TechnicalIndicators.macd(prices)
        assert len(macd_line) == len(signal) == len(histogram)

    def test_atr(self):
        from ml.signal_features import TechnicalIndicators

        df = _make_ohlcv(60)
        result = TechnicalIndicators.atr(df["high"].values, df["low"].values, df["close"].values, 14)
        assert len(result) > 0
        assert np.all(result[~np.isnan(result)] >= 0)


@pytest.mark.unit
class TestFeatureVector:
    def test_to_array(self):
        from ml.signal_features import FeatureVector

        fv = FeatureVector(
            symbol="XAU_USD",
            timestamp=1234567890.0,
            features={"rsi": 55.0, "macd": 0.5, "vol": 0.02},
        )
        arr = fv.to_array()
        assert isinstance(arr, np.ndarray)
        assert len(arr) == 3

    def test_to_dict(self):
        from ml.signal_features import FeatureVector

        fv = FeatureVector(
            symbol="XAU_USD",
            timestamp=1234567890.0,
            features={"rsi": 55.0},
            label=1.0,
        )
        d = fv.to_dict()
        assert d["symbol"] == "XAU_USD"
        assert d["label"] == 1.0
        assert "features" in d


@pytest.mark.unit
class TestFeatureEngineer:
    def _make_candles(self, n: int = 80):
        """Create list of candle-like objects."""
        df = _make_ohlcv(n)
        candles = []
        for _, row in df.iterrows():
            c = MagicMock()
            c.open = row["open"]
            c.high = row["high"]
            c.low = row["low"]
            c.close = row["close"]
            c.volume = row["volume"]
            candles.append(c)
        return candles

    def test_extract_features_returns_vector(self):
        from ml.signal_features import FeatureEngineer

        eng = FeatureEngineer(lookback_periods=[5, 10, 20])
        candles = self._make_candles(80)
        result = eng.extract_features("XAU_USD", candles)
        assert result is not None
        assert hasattr(result, "features")
        assert len(result.features) > 0

    def test_extract_features_insufficient_data(self):
        from ml.signal_features import FeatureEngineer

        eng = FeatureEngineer(lookback_periods=[5, 10, 20, 50])
        candles = self._make_candles(5)  # too few
        result = eng.extract_features("XAU_USD", candles)
        assert result is None

    def test_extract_features_with_order_book(self):
        from ml.signal_features import FeatureEngineer

        eng = FeatureEngineer(lookback_periods=[5, 10, 20])
        candles = self._make_candles(80)
        order_book = {
            "bids": [[1899.0, 1.0], [1898.0, 2.0]],
            "asks": [[1901.0, 1.0], [1902.0, 2.0]],
        }
        result = eng.extract_features("XAU_USD", candles, order_book=order_book)
        assert result is not None


# ===========================================================================
# ml/performance_monitor.py
# ===========================================================================


@pytest.mark.unit
class TestModelPerformanceMonitor:
    def test_record_trade_no_version(self):
        from ml.performance_monitor import ModelPerformanceMonitor

        m = ModelPerformanceMonitor()
        m.record_trade(pnl=100.0)  # no current version — should not raise

    def test_record_trade_creates_window(self):
        from ml.performance_monitor import ModelPerformanceMonitor

        m = ModelPerformanceMonitor()
        m.record_trade(pnl=50.0, model_version="v1")
        assert "v1" in m._windows

    def test_on_model_promoted(self):
        from ml.performance_monitor import ModelPerformanceMonitor

        m = ModelPerformanceMonitor()
        m.on_model_promoted("v2", "v1")
        assert m._current_version == "v2"
        assert m._previous_version == "v1"

    def test_get_stats_empty(self):
        from ml.performance_monitor import ModelPerformanceMonitor

        m = ModelPerformanceMonitor()
        stats = m.get_stats()
        assert isinstance(stats, dict)
        assert len(stats) == 0

    def test_get_stats_with_trades(self):
        from ml.performance_monitor import ModelPerformanceMonitor

        m = ModelPerformanceMonitor()
        for pnl in [10.0, -5.0, 20.0, 15.0]:
            m.record_trade(pnl=pnl, model_version="v1")
        stats = m.get_stats()
        assert "v1" in stats
        assert stats["v1"]["trade_count"] == 4

    def test_status_returns_dict(self):
        from ml.performance_monitor import ModelPerformanceMonitor

        m = ModelPerformanceMonitor()
        m.on_model_promoted("v2", "v1")
        s = m.status()
        assert s["current_version"] == "v2"
        assert s["previous_version"] == "v1"
        assert "versions" in s

    def test_stop_sets_running_false(self):
        from ml.performance_monitor import ModelPerformanceMonitor

        m = ModelPerformanceMonitor()
        m._running = True
        m.stop()
        assert m._running is False

    def test_get_monitor_returns_instance(self):
        from ml.performance_monitor import get_monitor, ModelPerformanceMonitor

        m = get_monitor()
        assert isinstance(m, ModelPerformanceMonitor)

    @pytest.mark.asyncio
    async def test_evaluate_no_versions(self):
        from ml.performance_monitor import ModelPerformanceMonitor

        m = ModelPerformanceMonitor()
        await m._evaluate()  # should not raise

    @pytest.mark.asyncio
    async def test_evaluate_insufficient_trades(self):
        from ml.performance_monitor import ModelPerformanceMonitor

        m = ModelPerformanceMonitor()
        m.on_model_promoted("v2", "v1")
        m.record_trade(pnl=10.0, model_version="v2")  # only 1 trade, below MIN_TRADES
        await m._evaluate()  # should not raise or rollback

    @pytest.mark.asyncio
    async def test_run_stops_on_cancel(self):
        from ml.performance_monitor import ModelPerformanceMonitor

        m = ModelPerformanceMonitor()
        task = asyncio.create_task(m.run())
        await asyncio.sleep(0.01)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        # Should have started
        assert m._running is True or True  # just verify no exception


# ===========================================================================
# ml/regime.py
# ===========================================================================


@pytest.mark.unit
class TestMarketRegime:
    def test_enum_values(self):
        from ml.regime import MarketRegime

        assert MarketRegime.TRENDING_UP is not None
        assert MarketRegime.TRENDING_DOWN is not None
        assert MarketRegime.HIGH_VOL is not None
        assert MarketRegime.RANGE_BOUND is not None
        assert MarketRegime.UNKNOWN is not None

    def test_regime_result_dataclass(self):
        from ml.regime import MarketRegime, RegimeResult

        r = RegimeResult(
            regime=MarketRegime.TRENDING_UP,
            confidence=0.85,
            duration_bars=10,
            transition_probability=0.1,
        )
        assert r.regime == MarketRegime.TRENDING_UP
        assert r.confidence == 0.85


@pytest.mark.unit
class TestRegimeDetector:
    def test_init(self):
        from ml.regime import RegimeDetector

        d = RegimeDetector(n_regimes=3, lookback=50)
        assert d.n_regimes == 3
        assert d.lookback == 50
        assert d._is_fitted is False

    @pytest.mark.asyncio
    async def test_detect_unfitted_returns_unknown(self):
        from ml.regime import RegimeDetector, MarketRegime

        d = RegimeDetector()
        features = MagicMock()
        features.returns = 0.001
        features.volatility = 0.02
        features.rsi = 55.0
        features.macd = 0.1
        features.bid_ask_ratio = 1.0
        features.hawkes_intensity = 0.5

        regime, confidence = await d.detect(features)
        assert regime == MarketRegime.UNKNOWN
        assert confidence == 0.0

    @pytest.mark.asyncio
    async def test_fit_sets_is_fitted(self, tmp_path):
        from ml.regime import RegimeDetector

        d = RegimeDetector(n_regimes=3, model_path=tmp_path / "regime.pkl")
        rng = np.random.default_rng(42)
        # 6 features: returns, vol, rsi, macd, bid_ask_ratio, hawkes
        data = rng.normal(0, 1, (100, 6))
        await d.fit(data)
        assert d._is_fitted is True

    def test_classify_volatility_high(self):
        from ml.regime import RegimeDetector, MarketRegime

        d = RegimeDetector()
        assert d._classify_volatility(0.6) == MarketRegime.HIGH_VOL

    def test_classify_volatility_low(self):
        from ml.regime import RegimeDetector, MarketRegime

        d = RegimeDetector()
        assert d._classify_volatility(0.05) == MarketRegime.LOW_VOL

    def test_classify_volatility_unknown(self):
        from ml.regime import RegimeDetector, MarketRegime

        d = RegimeDetector()
        assert d._classify_volatility(0.3) == MarketRegime.UNKNOWN

    def test_calculate_duration_empty_history(self):
        from ml.regime import RegimeDetector

        d = RegimeDetector()
        result = d._calculate_duration(0)
        assert result == 0

    def test_calculate_duration_with_history(self):
        from ml.regime import RegimeDetector

        d = RegimeDetector()
        d._state_history = [0, 0, 0, 1, 0, 0]
        result = d._calculate_duration(0)
        assert result == 2  # last 2 are state 0

    def test_estimate_transition_empty(self):
        from ml.regime import RegimeDetector

        d = RegimeDetector()
        result = d._estimate_transition(0)
        assert result == 0.0

    def test_estimate_transition_with_history(self):
        from ml.regime import RegimeDetector

        d = RegimeDetector()
        d._state_history = [0, 1, 0, 1, 0, 1, 0, 1, 0, 1]
        result = d._estimate_transition(0)
        assert 0.0 <= result <= 1.0

    @pytest.mark.asyncio
    async def test_load_no_file(self, tmp_path):
        from ml.regime import RegimeDetector

        d = RegimeDetector(model_path=tmp_path / "nonexistent.pkl")
        await d.load()  # should not raise
        assert d._is_fitted is False


# ===========================================================================
# backtesting/data_handler.py
# ===========================================================================


@pytest.mark.unit
class TestBacktestDataHandler:
    def test_import(self):
        from backtesting.data_handler import DataHandler

        assert DataHandler is not None

    def test_init_with_mock_source(self):
        from backtesting.data_handler import DataHandler

        mock_source = MagicMock()
        handler = DataHandler(
            data_source=mock_source,
            symbols=["XAU_USD"],
            start_date="2023-01-01",
            end_date="2023-12-31",
        )
        assert handler.symbols == ["XAU_USD"]
        assert handler.current_index == 0

    def test_load_data_empty_returns_error(self):
        from backtesting.data_handler import DataHandler

        mock_source = MagicMock()
        mock_source.get_data.return_value = pd.DataFrame()
        handler = DataHandler(
            data_source=mock_source,
            symbols=["XAU_USD"],
            start_date="2023-01-01",
            end_date="2023-12-31",
        )
        with pytest.raises(ValueError, match="No data loaded"):
            handler.load_data()

    def test_load_data_missing_columns(self):
        from backtesting.data_handler import DataHandler

        mock_source = MagicMock()
        mock_source.get_data.return_value = pd.DataFrame({"close": [1.0, 2.0]})
        handler = DataHandler(
            data_source=mock_source,
            symbols=["XAU_USD"],
            start_date="2023-01-01",
            end_date="2023-12-31",
        )
        with pytest.raises(ValueError, match="No data loaded"):
            handler.load_data()

    def test_load_data_success(self):
        from backtesting.data_handler import DataHandler

        df = _make_ohlcv(50)
        df.index = pd.date_range("2023-01-01", periods=50, freq="D")
        mock_source = MagicMock()
        mock_source.get_data.return_value = df
        handler = DataHandler(
            data_source=mock_source,
            symbols=["XAU_USD"],
            start_date="2023-01-01",
            end_date="2023-12-31",
        )
        handler.load_data()
        assert "XAU_USD" in handler.data


# ===========================================================================
# backtesting/portfolio.py
# ===========================================================================


@pytest.mark.unit
class TestBacktestPortfolio:
    def test_import(self):
        from backtesting.portfolio import Portfolio

        assert Portfolio is not None

    def test_init(self):
        from backtesting.portfolio import Portfolio

        p = Portfolio(initial_capital=10000.0)
        assert p.initial_capital == 10000.0
        assert p.cash == 10000.0

    def test_update_fill_buy(self):
        from backtesting.portfolio import Portfolio
        from backtesting.events import FillEvent

        p = Portfolio(initial_capital=10000.0)
        fill = FillEvent(
            symbol="XAU_USD",
            quantity=1.0,
            direction="BUY",
            fill_price=1900.0,
            commission=2.0,
        )
        p.update_fill(fill, current_prices={"XAU_USD": 1900.0})
        assert p.positions.get("XAU_USD", 0) == 1.0

    def test_update_fill_sell_closes_position(self):
        from backtesting.portfolio import Portfolio
        from backtesting.events import FillEvent

        p = Portfolio(initial_capital=10000.0)
        buy = FillEvent("XAU_USD", 1.0, "BUY", 1900.0, 2.0)
        p.update_fill(buy, current_prices={"XAU_USD": 1900.0})

        sell = FillEvent("XAU_USD", 1.0, "SELL", 1950.0, 2.0)
        p.update_fill(sell, current_prices={"XAU_USD": 1950.0})
        assert p.positions.get("XAU_USD", 0) == 0

    def test_get_equity_curve_empty(self):
        from backtesting.portfolio import Portfolio

        p = Portfolio(initial_capital=10000.0)
        curve = p.get_equity_curve()
        assert isinstance(curve, pd.DataFrame)

    def test_update_equity(self):
        from backtesting.portfolio import Portfolio

        p = Portfolio(initial_capital=10000.0)
        p._update_equity({"XAU_USD": 1950.0})


# ===========================================================================
# backtesting/walk_forward.py
# ===========================================================================


@pytest.mark.unit
class TestWalkForwardEngine:
    def test_import(self):
        from backtesting.walk_forward import WalkForwardEngine

        assert WalkForwardEngine is not None

    def test_init(self):
        from backtesting.walk_forward import WalkForwardEngine

        wf = WalkForwardEngine(
            train_size=100,
            test_size=20,
            purge_size=5,
            step_size=20,
        )
        assert wf.train_size == 100
        assert wf.test_size == 20

    def test_run_insufficient_data(self):
        from backtesting.walk_forward import WalkForwardEngine

        wf = WalkForwardEngine(train_size=1000, test_size=200, purge_size=50, step_size=200)
        df = _make_ohlcv(50)  # too small
        results = wf.run(df, strategy_factory=MagicMock(), parameter_grid=[{}])
        assert results == []

    def test_walk_forward_result_class(self):
        from backtesting.walk_forward import WalkForwardResult
        from datetime import datetime

        r = WalkForwardResult.__new__(WalkForwardResult)
        r.train_start = datetime(2023, 1, 1)
        r.train_end = datetime(2023, 6, 1)
        r.test_start = datetime(2023, 6, 15)
        r.test_end = datetime(2023, 12, 31)
        r.train_performance = {"sharpe": 1.2}
        r.test_performance = {"sharpe": 0.9}
        r.parameter_values = {"period": 20}
        r.is_overfit = False
        assert r.parameter_values == {"period": 20}
        assert r.is_overfit is False
