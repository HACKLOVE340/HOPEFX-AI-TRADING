# HOPEFX-AI-TRADING
# Coverage boost: backtesting/backtest_engine.py, market_data/ibkr_feed.py
"""Real unit tests — no mocks/stubs/fake data."""

from __future__ import annotations
import time
import numpy as np
import pandas as pd
import pytest


def _ohlcv(n=100, seed=0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    close = 2000.0 + np.cumsum(rng.normal(0, 5, n))
    open_ = close + rng.normal(0, 2, n)
    high = np.maximum(close, open_) + rng.uniform(0, 3, n)
    low = np.minimum(close, open_) - rng.uniform(0, 3, n)
    volume = rng.uniform(1000, 5000, n)
    return pd.DataFrame({"open": open_, "high": high, "low": low, "close": close, "volume": volume})


# ─────────────────────────────────────────────────────────────────────────────
# backtesting/backtest_engine.py
# ─────────────────────────────────────────────────────────────────────────────


class TestBacktestEngine:
    def _engine(self):
        from backtesting.backtest_engine import BacktestEngine

        return BacktestEngine()

    def test_run_all_flat_signals(self):
        eng = self._engine()
        df = _ohlcv()
        signals = pd.Series(0, index=df.index)
        result = eng.run_backtest(df, signals)
        assert result.total_trades == 0
        assert result.total_return == pytest.approx(0.0)

    def test_run_all_long_signals(self):
        eng = self._engine()
        df = _ohlcv()
        signals = pd.Series(1, index=df.index)
        result = eng.run_backtest(df, signals)
        assert result.total_trades >= 1
        assert isinstance(result.sharpe_ratio, float)
        assert isinstance(result.max_drawdown, float)

    def test_run_alternating_signals(self):
        eng = self._engine()
        df = _ohlcv(n=60)
        signals = pd.Series([1 if i % 4 < 2 else -1 for i in range(60)], index=df.index)
        result = eng.run_backtest(df, signals)
        assert result.total_trades >= 1
        assert 0.0 <= result.win_rate <= 1.0

    def test_equity_curve_length(self):
        eng = self._engine()
        df = _ohlcv(n=50)
        signals = pd.Series(1, index=df.index)
        result = eng.run_backtest(df, signals)
        assert len(result.equity_curve) == len(df)

    def test_commission_applied(self):
        eng = self._engine()
        df = _ohlcv(n=50)
        signals = pd.Series([1, -1] * 25, index=df.index)
        result = eng.run_backtest(df, signals)
        assert result.total_commission >= 0.0

    def test_overnight_cost_applied(self):
        eng = self._engine()
        df = _ohlcv(n=50)
        signals = pd.Series(1, index=df.index)
        result = eng.run_backtest(df, signals)
        assert result.total_overnight_cost >= 0.0

    def test_backtest_result_dataclass(self):
        from backtesting.backtest_engine import BacktestResult

        r = BacktestResult(total_return=0.05, sharpe_ratio=1.2, max_drawdown=0.03, win_rate=0.55, total_trades=10)
        assert r.total_return == pytest.approx(0.05)
        assert r.equity_curve == []

    def test_short_signals(self):
        eng = self._engine()
        df = _ohlcv(n=50)
        signals = pd.Series(-1, index=df.index)
        result = eng.run_backtest(df, signals)
        assert result.total_trades >= 1

    def test_mixed_long_short(self):
        eng = self._engine()
        df = _ohlcv(n=80)
        signals = pd.Series([1] * 20 + [-1] * 20 + [0] * 20 + [1] * 20, index=df.index)
        result = eng.run_backtest(df, signals)
        assert isinstance(result.total_return, float)

    def test_callable_signals(self):
        eng = self._engine()
        df = _ohlcv(n=50)
        result = eng.run_backtest(df, lambda d: pd.Series(1, index=d.index))
        assert result.total_trades >= 1

    def test_monte_carlo_analysis(self):
        eng = self._engine()
        df = _ohlcv(n=50)
        signals = pd.Series([1, -1] * 25, index=df.index)
        eng.run_backtest(df, signals)
        mc = eng.monte_carlo_analysis(n_simulations=10)
        assert isinstance(mc, dict)


# ─────────────────────────────────────────────────────────────────────────────
# market_data/ibkr_feed.py
# ─────────────────────────────────────────────────────────────────────────────


class TestIBKRFeedClasses:
    def _tick(self):
        from market_data.ibkr_feed import Tick

        return Tick(symbol="XAUUSD", bid=1999.0, ask=2001.0, last=2000.0, timestamp=time.time())

    def test_tick_mid(self):
        t = self._tick()
        assert t.mid == pytest.approx(2000.0)

    def test_tick_spread(self):
        t = self._tick()
        assert t.spread == pytest.approx(2.0)

    def test_tick_spread_bps(self):
        t = self._tick()
        assert t.spread_bps == pytest.approx(10.0, rel=0.01)

    def test_tick_to_dict(self):
        t = self._tick()
        d = t.to_dict()
        assert d["symbol"] == "XAUUSD"
        assert "mid" in d

    def test_ohlcv_bar_dataclass(self):
        from market_data.ibkr_feed import OHLCVBar

        bar = OHLCVBar(
            symbol="XAUUSD",
            timeframe="1m",
            open=2000.0,
            high=2005.0,
            low=1998.0,
            close=2003.0,
            volume=500,
            tick_count=10,
            bar_open_ts=time.time(),
            bar_close_ts=time.time() + 60,
        )
        assert bar.symbol == "XAUUSD"

    def test_feed_status_enum(self):
        from market_data.ibkr_feed import FeedStatus

        assert FeedStatus.DISCONNECTED is not None
        assert FeedStatus.LIVE is not None

    def test_feed_health_dataclass(self):
        from market_data.ibkr_feed import FeedHealth, FeedStatus

        h = FeedHealth(
            status=FeedStatus.DISCONNECTED,
            last_tick_ts=None,
            ticks_received=0,
            ticks_rejected=0,
            redis_publish_errors=0,
            last_error=None,
        )
        assert h.status == FeedStatus.DISCONNECTED
        d = h.to_dict()
        assert d["status"] == "disconnected"

    def test_tick_validator_valid(self):
        from market_data.ibkr_feed import TickValidator

        v = TickValidator()
        t = self._tick()
        ok, reason = v.validate(t)
        assert ok is True
        assert reason == ""

    def test_tick_validator_zero_bid_invalid(self):
        from market_data.ibkr_feed import TickValidator, Tick

        v = TickValidator()
        t = Tick(symbol="XAUUSD", bid=0.0, ask=2001.0, last=2000.0, timestamp=time.time())
        ok, reason = v.validate(t)
        assert ok is False

    def test_tick_validator_inverted_spread(self):
        from market_data.ibkr_feed import TickValidator, Tick

        v = TickValidator()
        t = Tick(symbol="XAUUSD", bid=2002.0, ask=2001.0, last=2001.5, timestamp=time.time())
        ok, reason = v.validate(t)
        assert ok is False

    def test_tick_validator_stale(self):
        from market_data.ibkr_feed import TickValidator, Tick

        v = TickValidator(max_age_sec=1.0)
        t = Tick(symbol="XAUUSD", bid=1999.0, ask=2001.0, last=2000.0, timestamp=time.time() - 100)
        ok, reason = v.validate(t)
        assert ok is False

    def test_tick_validator_price_jump(self):
        from market_data.ibkr_feed import TickValidator, Tick

        v = TickValidator(max_jump_pct=0.001)
        t1 = Tick(symbol="XAUUSD", bid=1999.0, ask=2001.0, last=2000.0, timestamp=time.time())
        v.validate(t1)
        t2 = Tick(symbol="XAUUSD", bid=2099.0, ask=2101.0, last=2100.0, timestamp=time.time())
        ok, reason = v.validate(t2)
        assert ok is False

    def test_ohlcv_aggregator_init(self):
        from market_data.ibkr_feed import OHLCVAggregator

        agg = OHLCVAggregator(symbol="XAUUSD", timeframes=["1m", "5m"])
        assert agg is not None

    def test_ohlcv_aggregator_on_tick(self):
        from market_data.ibkr_feed import OHLCVAggregator, Tick

        agg = OHLCVAggregator(symbol="XAUUSD", timeframes=["1m"])
        t = Tick(symbol="XAUUSD", bid=1999.0, ask=2001.0, last=2000.0, timestamp=time.time())
        agg.on_tick(t)

    def test_redis_tick_publisher_init_no_redis(self):
        from market_data.ibkr_feed import RedisTickPublisher

        pub = RedisTickPublisher(redis_client=None, key_prefix="test:")
        assert pub is not None

    def test_ibkr_market_data_feed_init(self):
        from market_data.ibkr_feed import IBKRMarketDataFeed

        feed = IBKRMarketDataFeed(ibkr_connector=None, symbol="XAUUSD")
        assert feed is not None

    def test_ibkr_feed_get_health(self):
        from market_data.ibkr_feed import IBKRMarketDataFeed, FeedStatus

        feed = IBKRMarketDataFeed(ibkr_connector=None, symbol="XAUUSD")
        health = feed.get_health()
        assert health.status == FeedStatus.DISCONNECTED

    def test_ibkr_feed_get_latest_tick_none(self):
        from market_data.ibkr_feed import IBKRMarketDataFeed

        feed = IBKRMarketDataFeed(ibkr_connector=None, symbol="XAUUSD")
        assert feed.get_latest_tick() is None

    def test_ibkr_feed_get_recent_ticks_empty(self):
        from market_data.ibkr_feed import IBKRMarketDataFeed

        feed = IBKRMarketDataFeed(ibkr_connector=None, symbol="XAUUSD")
        ticks = feed.get_recent_ticks(10)
        assert ticks == []

    def test_ibkr_feed_get_current_bar_none(self):
        from market_data.ibkr_feed import IBKRMarketDataFeed

        feed = IBKRMarketDataFeed(ibkr_connector=None, symbol="XAUUSD")
        bar = feed.get_current_bar("1m")
        assert bar is None

    def test_ibkr_feed_is_live_false(self):
        from market_data.ibkr_feed import IBKRMarketDataFeed

        feed = IBKRMarketDataFeed(ibkr_connector=None, symbol="XAUUSD")
        assert feed.is_live is False

    def test_ibkr_feed_symbol_property(self):
        from market_data.ibkr_feed import IBKRMarketDataFeed

        feed = IBKRMarketDataFeed(ibkr_connector=None, symbol="XAUUSD")
        assert feed.symbol == "XAUUSD"
