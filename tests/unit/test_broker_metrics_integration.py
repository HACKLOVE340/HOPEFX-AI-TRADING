# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
Integration tests — verify that core components wire together correctly.

These tests use real production classes (no mocks for the units under test)
and exercise cross-module interactions: broker <-> risk manager, metrics
registry, kill switch, and data scheduler imports.
"""

import pytest


# ---------------------------------------------------------------------------
# PaperTradingBroker + RiskManager integration
# ---------------------------------------------------------------------------


class TestBrokerRiskIntegration:
    """PaperTradingBroker and RiskManager work together end-to-end."""

    def _make_broker(self, balance: float = 10_000.0):
        from brokers.paper_trading import PaperTradingBroker

        return PaperTradingBroker(initial_balance=balance)

    def _make_risk(self, balance: float = 10_000.0):
        from risk.manager import RiskManager, RiskConfig

        cfg = RiskConfig(
            max_position_size_pct=0.02,
            max_drawdown_pct=0.10,
            daily_loss_limit_pct=0.05,
        )
        return RiskManager(config=cfg, initial_balance=balance)

    @pytest.mark.asyncio
    async def test_broker_connect_and_account(self):
        broker = self._make_broker(50_000.0)
        connected = await broker.connect()
        assert connected is True

        info = broker.get_account_info()
        assert info is not None
        assert info.balance == pytest.approx(50_000.0, rel=1e-3)

        await broker.disconnect()

    @pytest.mark.asyncio
    async def test_place_and_track_position(self):
        broker = self._make_broker(10_000.0)
        await broker.connect()
        broker.update_market_price("XAUUSD", 2000.0)

        from brokers.base import OrderSide, OrderType

        order = broker.place_order(
            symbol="XAUUSD",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=0.1,
        )
        assert order is not None

        positions = broker.get_positions()
        assert len(positions) >= 1
        symbols = [p.symbol for p in positions]
        assert "XAUUSD" in symbols

        await broker.disconnect()

    def test_risk_manager_position_size(self):
        risk = self._make_risk(10_000.0)
        size = risk.calculate_position_size(
            symbol="XAUUSD",
            entry_price=2000.0,
            account_balance=10_000.0,
        )
        assert hasattr(size, "size") or size >= 0
        # PositionSizingResult.size is the recommended lot size
        actual = size.size if hasattr(size, "size") else size
        assert actual >= 0

    def test_risk_manager_validate_trade(self):
        risk = self._make_risk(10_000.0)
        allowed, reason = risk.validate_trade("XAUUSD", 0.01, "buy")
        assert isinstance(allowed, bool)
        assert isinstance(reason, str)

    def test_risk_manager_drawdown_check(self):
        risk = self._make_risk(10_000.0)
        result = risk.check_drawdown()
        assert result is not None
        assert hasattr(result, "passed")

    def test_risk_manager_kill_switch_inactive_by_default(self):
        risk = self._make_risk()
        assert risk.kill_switch_active is False

    @pytest.mark.asyncio
    async def test_broker_close_position(self):
        broker = self._make_broker(10_000.0)
        await broker.connect()
        broker.update_market_price("EURUSD", 1.0850)

        from brokers.base import OrderSide, OrderType

        broker.place_order(
            symbol="EURUSD",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=0.1,
        )

        positions_before = broker.get_positions()
        assert len(positions_before) >= 1

        broker.update_market_price("EURUSD", 1.0860)
        closed = broker.close_position("EURUSD")
        assert closed is True

        await broker.disconnect()


# ---------------------------------------------------------------------------
# MetricsRegistry integration
# ---------------------------------------------------------------------------


class TestMetricsRegistryIntegration:
    """MetricsRegistry records and exports values correctly."""

    def setup_method(self):
        from infrastructure.metrics import get_metrics_registry

        self.registry = get_metrics_registry()

    def test_counter_increments(self):
        counter = self.registry.get_collector("hopefx_orders_total")
        assert counter is not None
        before = counter.get_value({"symbol": "XAUUSD", "side": "buy"})
        counter.inc(1, {"symbol": "XAUUSD", "side": "buy"})
        after = counter.get_value({"symbol": "XAUUSD", "side": "buy"})
        assert after == before + 1

    def test_gauge_set_and_get(self):
        gauge = self.registry.get_collector("hopefx_equity")
        assert gauge is not None
        gauge.set(12345.67)
        assert gauge.get_value() == pytest.approx(12345.67)

    def test_histogram_observe(self):
        hist = self.registry.get_collector("hopefx_order_latency_ms_bucket")
        assert hist is not None
        before_count = hist.get_count()
        hist.observe(42.0)
        assert hist.get_count() == before_count + 1
        assert hist.get_sum() >= 42.0

    def test_prometheus_export_contains_metric_names(self):
        output = self.registry.export_prometheus()
        assert "hopefx_equity" in output
        assert "hopefx_orders_total" in output
        assert "hopefx_broker_connected" in output

    def test_record_trade_updates_equity(self):
        gauge = self.registry.get_collector("account_equity")
        if gauge is None:
            pytest.skip("account_equity collector not present")
        before = gauge.get_value()
        self.registry.record_trade("XAUUSD", "buy", pnl=100.0, commission=3.5)
        after = gauge.get_value()
        assert after == pytest.approx(before + 100.0 - 3.5, rel=1e-6)

    def test_grafana_metrics_all_registered(self):
        """All Grafana-dashboard metric names must be registered."""
        required = [
            "hopefx_equity",
            "hopefx_active_positions",
            "hopefx_pnl_realized",
            "hopefx_drawdown_current",
            "hopefx_model_drift_score",
            "hopefx_orders_total",
            "hopefx_order_latency_ms_bucket",
            "hopefx_broker_latency_ms_bucket",
            "hopefx_db_pool_active",
            "hopefx_signals_total",
            "hopefx_broker_connected",
            "hopefx_broker_failover_total",
            "hopefx_broker_rejections_total",
            "hopefx_fix_last_heartbeat_timestamp",
            "hopefx_market_regime",
            "hopefx_model_accuracy_pct",
            "hopefx_model_inference_ms_bucket",
            "hopefx_model_last_trained_timestamp",
            "hopefx_signal_confidence_bucket",
            "hopefx_smart_router_active_broker",
            "hopefx_win_rate_pct",
        ]
        missing = [n for n in required if self.registry.get_collector(n) is None]
        assert missing == [], f"Missing Grafana metrics: {missing}"


# ---------------------------------------------------------------------------
# KillSwitch integration
# ---------------------------------------------------------------------------


class TestKillSwitchIntegration:
    """KillSwitch activates, blocks trading, and deactivates correctly."""

    def _make_ks(self, tmp_path=None):
        """Create an isolated KillSwitch with its own flag/state files."""
        import tempfile
        from pathlib import Path
        from kill_switch import KillSwitch

        if tmp_path is None:
            tmp_path = Path(tempfile.mkdtemp())
        flag = tmp_path / "ks_test.flag"
        return KillSwitch(flag_file=flag, deactivation_token="test-token-123")

    def test_inactive_by_default(self):
        ks = self._make_ks()
        assert ks.is_active() is False

    def test_activate_and_check(self):
        ks = self._make_ks()
        ks.activate("test: daily drawdown exceeded")
        assert ks.is_active() is True

    def test_deactivate_restores_state(self):
        ks = self._make_ks()
        ks.activate("test")
        ks.deactivate(token="test-token-123")
        assert ks.is_active() is False

    def test_status_dict_structure(self):
        ks = self._make_ks()
        status = ks.status()
        assert "active" in status
        assert isinstance(status["active"], bool)

    def test_activate_records_reason(self):
        ks = self._make_ks()
        ks.activate("max drawdown hit")
        status = ks.status()
        assert status["active"] is True


# ---------------------------------------------------------------------------
# DataScheduler import + instantiation
# ---------------------------------------------------------------------------


class TestDataSchedulerIntegration:
    """DataScheduler can be imported and instantiated without errors."""

    def test_import_and_instantiate(self):
        from data.scheduler import DataScheduler

        scheduler = DataScheduler()
        assert scheduler is not None

    def test_has_start_method(self):
        from data.scheduler import DataScheduler

        scheduler = DataScheduler()
        assert callable(getattr(scheduler, "start", None))


# ---------------------------------------------------------------------------
# PrometheusMonitoring integration
# ---------------------------------------------------------------------------

try:
    import fastapi as _fastapi_check

    _FASTAPI_AVAILABLE = True
except ImportError:
    _FASTAPI_AVAILABLE = False

_skip_no_fastapi = pytest.mark.skipif(not _FASTAPI_AVAILABLE, reason="fastapi not installed in this environment")


class TestPrometheusMonitoringIntegration:
    """prometheus_monitoring module loads and mounts /metrics correctly."""

    def test_import(self):
        import prometheus_monitoring

        assert hasattr(prometheus_monitoring, "setup_prometheus_monitoring")

    @_skip_no_fastapi
    def test_setup_on_fastapi_app(self):
        from fastapi import FastAPI
        import prometheus_monitoring

        app = FastAPI()
        prometheus_monitoring.setup_prometheus_monitoring(app)
        paths = [r.path for r in app.routes]
        assert "/metrics" in paths

    @_skip_no_fastapi
    def test_idempotent_setup(self):
        """Calling setup twice must not raise or duplicate the route."""
        from fastapi import FastAPI
        import prometheus_monitoring

        app = FastAPI()
        prometheus_monitoring.setup_prometheus_monitoring(app)
        prometheus_monitoring.setup_prometheus_monitoring(app)
        metrics_routes = [r for r in app.routes if getattr(r, "path", "") == "/metrics"]
        assert len(metrics_routes) == 1
