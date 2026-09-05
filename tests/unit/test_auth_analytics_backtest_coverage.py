# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
Coverage tests for:
  - auth/dependencies.py, auth/jwt_handler.py, auth/schemas.py (re-export shims)
  - backtesting/events.py, backtesting/optimizer.py (0–20% coverage)
  - analytics/performance.py, analytics/portfolio.py (25–34% coverage)
"""

from datetime import datetime, timezone

import numpy as np
import pandas as pd
import pytest

UTC = timezone.utc


# ─────────────────────────────────────────────────────────────────────────────
# auth shims — importing them is enough to cover the re-export lines
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.unit
class TestAuthShims:
    def test_dependencies_exports(self):
        import auth.dependencies as dep

        assert hasattr(dep, "get_current_user")
        assert hasattr(dep, "require_role")
        assert hasattr(dep, "TokenPayload")

    def test_jwt_handler_exports(self):
        import auth.jwt_handler as jh

        assert hasattr(jh, "create_access_token")
        assert hasattr(jh, "verify_token")
        assert hasattr(jh, "ALGORITHM")

    def test_schemas_token_payload(self):
        from auth.schemas import TokenPayload

        # Simulate a decoded JWT that carries all claims written by _create_access_token.
        tp = TokenPayload(
            sub="user123",
            exp=9999999999,
            role="admin",
            type="access",
            jti="abc123",
            email="user@hopefx.io",
            username="user123",
        )
        assert tp.sub == "user123"
        assert tp.role == "admin"
        assert tp.type == "access"
        assert tp.jti == "abc123"
        assert tp.email == "user@hopefx.io"
        assert tp.username == "user123"

    def test_schemas_token_payload_defaults(self):
        from auth.schemas import TokenPayload

        # Only sub is required; all other fields are optional (None when absent from JWT).
        tp = TokenPayload(sub="u1")
        assert tp.exp is None
        assert tp.iat is None
        assert tp.jti is None
        assert tp.type is None
        assert tp.email is None
        assert tp.username is None
        assert tp.role == "user"


# ─────────────────────────────────────────────────────────────────────────────
# backtesting/events.py
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.unit
class TestBacktestEvents:
    def test_event_type_values(self):
        from backtesting.events import EventType

        assert EventType.MARKET.value == "MARKET"
        assert EventType.SIGNAL.value == "SIGNAL"
        assert EventType.ORDER.value == "ORDER"
        assert EventType.FILL.value == "FILL"

    def test_market_event(self):
        from backtesting.events import EventType, MarketEvent

        e = MarketEvent()
        assert e.type == EventType.MARKET
        assert isinstance(e.timestamp, datetime)

    def test_signal_event(self):
        from backtesting.events import EventType, SignalEvent

        e = SignalEvent(symbol="XAUUSD", signal_type="BUY", strength=0.8)
        assert e.type == EventType.SIGNAL
        assert e.symbol == "XAUUSD"
        assert e.signal_type == "BUY"
        assert e.strength == pytest.approx(0.8)

    def test_signal_event_defaults(self):
        from backtesting.events import SignalEvent

        e = SignalEvent(symbol="EURUSD", signal_type="SELL")
        assert e.strength == pytest.approx(1.0)
        # metadata defaults to None or {} depending on implementation
        assert e.metadata is None or e.metadata == {}

    def test_signal_event_with_metadata(self):
        from backtesting.events import SignalEvent

        e = SignalEvent("XAUUSD", "BUY", metadata={"confidence": 0.9})
        assert e.metadata["confidence"] == pytest.approx(0.9)

    def test_base_event_timestamp_is_recent(self):
        from backtesting.events import MarketEvent

        before = datetime.now(UTC)
        e = MarketEvent()
        after = datetime.now(UTC)
        assert before <= e.timestamp <= after


# ─────────────────────────────────────────────────────────────────────────────
# backtesting/optimizer.py
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.unit
class TestParameterOptimizer:
    def test_instantiates(self):
        from backtesting.optimizer import ParameterOptimizer
        from unittest.mock import MagicMock

        opt = ParameterOptimizer(
            strategy_class=MagicMock,
            data_handler=MagicMock(),
            initial_capital=50_000.0,
        )
        assert opt.initial_capital == pytest.approx(50_000.0)

    def test_grid_search_empty_data_skips(self):
        from backtesting.optimizer import ParameterOptimizer
        from unittest.mock import MagicMock

        class FakeStrategy:
            def __init__(self, fast=5, slow=20):
                self.fast = fast
                self.slow = slow

        dh = MagicMock()
        dh.get_data.return_value = pd.DataFrame()  # empty → skipped

        opt = ParameterOptimizer(FakeStrategy, dh, initial_capital=10_000.0)
        result = opt.grid_search({"fast": [5], "slow": [20]})
        assert "best_params" in result
        assert "all_results" in result


# ─────────────────────────────────────────────────────────────────────────────
# analytics/performance.py
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.unit
class TestAnalyticsPerformance:
    def test_metric_period_values(self):
        from analytics.performance import MetricPeriod

        assert MetricPeriod.DAY.value == "day"
        assert MetricPeriod.YEAR.value == "year"
        assert MetricPeriod.ALL_TIME.value == "all_time"

    def test_trade_record_instantiates(self):
        from analytics.performance import TradeRecord

        now = datetime.now(UTC)
        tr = TradeRecord(
            id="t1",
            symbol="XAUUSD",
            strategy="momentum",
            side="BUY",
            entry_time=now,
            exit_time=now,
            entry_price=1950.0,
            exit_price=1960.0,
            quantity=1.0,
            pnl=10.0,
            pnl_percent=0.5,
            commission=2.0,
            duration_minutes=30,
            max_favorable_excursion=15.0,
            max_adverse_excursion=-5.0,
        )
        assert tr.pnl == pytest.approx(10.0)
        assert tr.metadata == {}

    def test_equity_point_instantiates(self):
        from analytics.performance import EquityPoint

        now = datetime.now(UTC)
        ep = EquityPoint(
            timestamp=now,
            equity=100_000.0,
            cash=50_000.0,
            open_pnl=500.0,
            drawdown=-200.0,
            drawdown_pct=-0.002,
            high_water_mark=100_500.0,
        )
        assert ep.equity == pytest.approx(100_000.0)

    def test_strategy_performance_instantiates(self):
        from analytics.performance import StrategyPerformance
        import dataclasses

        # Build with all required fields (it's a dataclass with no defaults)
        _fields = {
            f.name: f.default for f in dataclasses.fields(StrategyPerformance) if f.default is not dataclasses.MISSING
        }
        required = {
            f.name
            for f in dataclasses.fields(StrategyPerformance)
            if f.default is dataclasses.MISSING and f.default_factory is dataclasses.MISSING
        }
        kwargs = dict.fromkeys(required, 0.0)
        kwargs["strategy_name"] = "test"
        kwargs["total_trades"] = 10
        sp = StrategyPerformance(**kwargs)
        assert sp.strategy_name == "test"
        assert sp.total_trades == 10


# ─────────────────────────────────────────────────────────────────────────────
# analytics/portfolio.py
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.unit
class TestPortfolioAnalytics:
    def _make_returns(self, n=100, assets=("XAUUSD", "EURUSD")):
        rng = np.random.default_rng(42)
        data = {a: rng.normal(0.001, 0.01, n) for a in assets}
        return pd.DataFrame(data)

    def test_instantiates(self):
        from analytics.portfolio import PortfolioAnalytics

        pa = PortfolioAnalytics(risk_free_rate=0.02)
        assert pa.risk_free_rate == pytest.approx(0.02)
        assert pa.returns_data is None

    def test_load_returns_data(self):
        from analytics.portfolio import PortfolioAnalytics

        pa = PortfolioAnalytics()
        df = self._make_returns()
        pa.load_returns_data(df)
        assert pa.returns_data is not None
        assert list(pa.assets) == ["XAUUSD", "EURUSD"]

    def test_calculate_correlation_matrix(self):
        try:
            from analytics.portfolio import PortfolioAnalytics

            pa = PortfolioAnalytics()
            pa.load_returns_data(self._make_returns())
            corr = pa.calculate_correlation_matrix()
            assert corr is not None
            assert corr.shape == (2, 2)
            # Diagonal should be 1.0
            assert corr.iloc[0, 0] == pytest.approx(1.0)
        except AttributeError:
            pytest.skip("calculate_correlation_matrix not available")

    # ── F108 ─────────────────────────────────────────────────────────────────
    # `calculate_portfolio_metrics` and `calculate_var` do not exist on
    # PortfolioAnalytics and never have; `optimize_portfolio` exists but takes
    # no `method` argument. Each call was wrapped in a bare
    # `except AttributeError: pytest.skip(...)`, so all three have skipped on
    # every run since they were written -- and `optimize_portfolio`'s handler
    # was `except (AttributeError, Exception)`, which cannot let any failure
    # through at all.
    #
    # The real surface is calculate_risk_metrics / portfolio_performance /
    # optimize_portfolio(max_sharpe=...), which is what these test.

    def test_calculate_risk_metrics(self):
        from analytics.portfolio import PortfolioAnalytics

        pa = PortfolioAnalytics()
        pa.load_returns_data(self._make_returns())
        metrics = pa.calculate_risk_metrics(np.array([0.5, 0.5]))
        assert isinstance(metrics, dict) and metrics, "risk metrics came back empty"
        import numbers

        assert all(isinstance(v, numbers.Real) for v in metrics.values())
        # VaR is here, under `var_95` -- which is why the old `calculate_var`
        # test skipping was a loss: the metric exists and went unchecked.
        assert metrics["var_95"] <= 0, "VaR is expressed as a loss"
        assert metrics["volatility"] > 0

    def test_portfolio_performance_returns_return_risk_and_sharpe(self):
        from analytics.portfolio import PortfolioAnalytics

        pa = PortfolioAnalytics()
        pa.load_returns_data(self._make_returns())
        ret, vol, sharpe = pa.portfolio_performance(np.array([0.5, 0.5]))
        assert vol > 0, "a two-asset portfolio of random returns has no volatility"
        assert all(isinstance(x, float) for x in (ret, vol, sharpe))

    def test_optimize_portfolio_returns_weights_that_sum_to_one(self):
        from analytics.portfolio import PortfolioAnalytics

        pa = PortfolioAnalytics()
        pa.load_returns_data(self._make_returns())
        result = pa.optimize_portfolio(max_sharpe=True)
        assert isinstance(result, dict)
        assert result["success"] is True
        weights = result["weights"]  # {asset: weight}
        assert set(weights) == {"XAUUSD", "EURUSD"}
        assert sum(float(w) for w in weights.values()) == pytest.approx(1.0, abs=1e-6)

    def test_the_misnamed_portfolio_methods_are_pinned(self):
        """These names were tested for years and do not exist. Pinning them
        means a future `calculate_var` arrives as a deliberate addition rather
        than as a test quietly un-skipping."""
        from analytics.portfolio import PortfolioAnalytics

        for absent in ("calculate_portfolio_metrics", "calculate_var"):
            assert not hasattr(PortfolioAnalytics, absent), (
                f"{absent} now exists -- replace the pinned test with a real one"
            )
        # The capability was never missing, only the name: VaR is returned by
        # calculate_risk_metrics as `var_95`.
        assert hasattr(PortfolioAnalytics, "calculate_risk_metrics")


# ─────────────────────────────────────────────────────────────────────────────
# analytics/simulations.py
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.unit
class TestAnalyticsSimulations:
    def test_import(self):
        import analytics.simulations as sim

        assert sim is not None


# ─────────────────────────────────────────────────────────────────────────────
# backtesting/execution.py
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.unit
class TestBacktestExecution:
    """`SimulatedExecutionHandler` is the sharpest case in F108.

    Unlike the other names in this file, the class is real and the method is
    real. The tests called it as ``SimulatedExecutionHandler(initial_capital=
    100_000.0)`` -- it takes ``(data_handler, commission_pct, slippage_pct)`` --
    so construction raised TypeError, and the handler was
    ``except (ImportError, AttributeError, TypeError): pytest.skip(...)``. The
    skip reason printed "SimulatedExecutionHandler not available" about a class
    that was importable the whole time.

    That is the failure mode worth naming: a broad `except` around a whole test
    body converts *any* mistake -- including the test's own -- into a skip that
    reads as an environment limitation.
    """

    def test_import(self):
        import backtesting.execution as ex

        assert ex is not None

    def test_simulated_execution_handler_constructs(self):
        from backtesting.execution import SimulatedExecutionHandler

        handler = SimulatedExecutionHandler(data_handler=None, commission_pct=0.001, slippage_pct=0.0005)
        assert handler.commission_pct == pytest.approx(0.001)
        assert handler.slippage_pct == pytest.approx(0.0005)

    def test_the_old_call_signature_is_the_one_that_was_wrong(self):
        """Pinned so the next reader does not have to rediscover it."""
        from backtesting.execution import SimulatedExecutionHandler

        with pytest.raises(TypeError):
            SimulatedExecutionHandler(initial_capital=100_000.0)

    class _Bars:
        """The minimum data handler `execute_order` uses: one latest bar."""

        def get_latest_bar(self, symbol):
            return {"open": 1949.0, "high": 1952.0, "low": 1948.0, "close": 1950.0}

    def test_execute_order_fills_a_market_order_with_slippage(self):
        from backtesting.events import FillEvent, OrderEvent
        from backtesting.execution import SimulatedExecutionHandler

        handler = SimulatedExecutionHandler(data_handler=self._Bars(), slippage_pct=0.001)
        order = OrderEvent(symbol="XAUUSD", order_type="MARKET", quantity=1.0, direction="BUY", price=None)
        fill = handler.execute_order(order)
        assert isinstance(fill, FillEvent)
        assert fill.symbol == "XAUUSD"
        # Slippage moves a BUY against the taker: 1950 * 1.001.
        assert fill.fill_price == pytest.approx(1951.95, abs=0.01)

    def test_execute_order_returns_none_without_data(self):
        from backtesting.events import OrderEvent
        from backtesting.execution import SimulatedExecutionHandler

        class _NoBars:
            def get_latest_bar(self, symbol):
                return None

        handler = SimulatedExecutionHandler(data_handler=_NoBars())
        order = OrderEvent(symbol="XAUUSD", order_type="MARKET", quantity=1.0, direction="BUY")
        assert handler.execute_order(order) is None


# ─────────────────────────────────────────────────────────────────────────────
# backtesting/plots.py
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.unit
class TestBacktestPlots:
    def test_import(self):
        import backtesting.plots as bp

        assert bp is not None


# ─────────────────────────────────────────────────────────────────────────────
# backtesting/reports.py
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.unit
class TestBacktestReports:
    def test_import(self):
        import backtesting.reports as br

        assert br is not None
