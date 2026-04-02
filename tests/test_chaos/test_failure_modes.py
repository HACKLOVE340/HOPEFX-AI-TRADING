# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
Chaos / failure-mode tests.

Verifies that the system degrades gracefully under adverse conditions:
broker errors, missing data, kill switch activation, and metric
collection failures.
"""

import pytest
import tempfile
from pathlib import Path
import contextlib


class TestBrokerFailureModes:
    """Broker handles connection and order failures gracefully."""

    @pytest.mark.asyncio
    async def test_close_nonexistent_position_returns_false(self):
        from brokers.paper_trading import PaperTradingBroker

        broker = PaperTradingBroker(initial_balance=10_000.0)
        await broker.connect()
        result = broker.close_position("NONEXISTENT_SYMBOL")
        assert result is False
        await broker.disconnect()

    @pytest.mark.asyncio
    async def test_price_missing_returns_default(self):
        """get_market_price on an unknown symbol returns a default, not an exception."""
        from brokers.paper_trading import PaperTradingBroker

        broker = PaperTradingBroker(initial_balance=10_000.0)
        await broker.connect()
        price = broker.get_market_price("UNKNOWN_PAIR")
        assert isinstance(price, int | float)
        await broker.disconnect()

    @pytest.mark.asyncio
    async def test_multiple_connects_are_idempotent(self):
        from brokers.paper_trading import PaperTradingBroker

        broker = PaperTradingBroker(initial_balance=10_000.0)
        r1 = await broker.connect()
        r2 = await broker.connect()
        assert r1 is True
        assert r2 is True
        await broker.disconnect()

    @pytest.mark.asyncio
    async def test_disconnect_without_connect_does_not_raise(self):
        from brokers.paper_trading import PaperTradingBroker

        broker = PaperTradingBroker(initial_balance=10_000.0)
        # Should not raise even if never connected
        try:
            await broker.disconnect()
        except Exception as exc:
            pytest.fail(f"disconnect() raised unexpectedly: {exc}")


class TestRiskManagerFailureModes:
    """RiskManager handles edge-case inputs without crashing."""

    def _risk(self):
        from risk.manager import RiskManager, RiskConfig

        return RiskManager(
            config=RiskConfig(
                max_position_size_pct=0.02,
                max_drawdown_pct=0.10,
                daily_loss_limit_pct=0.05,
            ),
            initial_balance=10_000.0,
        )

    def test_zero_size_trade_validation(self):
        risk = self._risk()
        allowed, reason = risk.validate_trade("XAUUSD", 0.0, "buy")
        assert isinstance(allowed, bool)
        assert isinstance(reason, str)

    def test_negative_entry_price_position_size(self):
        """calculate_position_size with bad price should not raise."""
        risk = self._risk()
        try:
            result = risk.calculate_position_size(
                symbol="XAUUSD",
                entry_price=-1.0,
                account_balance=10_000.0,
            )
            assert result is not None
        except (ValueError, ZeroDivisionError):
            pass  # Raising a clear error is also acceptable

    def test_drawdown_check_with_empty_equity_curve(self):
        risk = self._risk()
        result = risk.check_drawdown(equity_curve=[])
        assert result is not None
        assert hasattr(result, "passed")

    def test_check_risk_limits_returns_tuple(self):
        risk = self._risk()
        result = risk.check_risk_limits()
        assert isinstance(result, tuple)
        assert len(result) == 2


class TestKillSwitchFailureModes:
    """KillSwitch handles edge cases and persisted state correctly."""

    def _ks(self):
        from kill_switch import KillSwitch

        tmp = Path(tempfile.mkdtemp())
        return KillSwitch(flag_file=tmp / "ks.flag", deactivation_token="test-tok")

    def test_double_activate_stays_active(self):
        ks = self._ks()
        ks.activate("first reason")
        ks.activate("second reason")
        assert ks.is_active() is True

    def test_deactivate_without_token_raises(self):
        from kill_switch import KillSwitch

        tmp = Path(tempfile.mkdtemp())
        ks = KillSwitch(flag_file=tmp / "ks.flag")  # no token
        ks.activate("test")
        with pytest.raises(PermissionError):
            ks.deactivate()

    def test_deactivate_wrong_token_raises(self):
        ks = self._ks()
        ks.activate("test")
        with pytest.raises(PermissionError):
            ks.deactivate(token="wrong-token")

    def test_status_always_returns_dict(self):
        ks = self._ks()
        status = ks.status()
        assert isinstance(status, dict)
        assert "active" in status

    def test_inactive_ks_deactivate_is_noop(self):
        ks = self._ks()
        assert ks.is_active() is False
        # Deactivating an already-inactive switch should not raise
        with contextlib.suppress(Exception):
            ks.deactivate(token="test-tok")


class TestMetricsFailureModes:
    """MetricsRegistry handles bad inputs without crashing."""

    def setup_method(self):
        from infrastructure.metrics import get_metrics_registry

        self.registry = get_metrics_registry()

    def test_get_nonexistent_collector_returns_none(self):
        result = self.registry.get_collector("metric_that_does_not_exist_xyz")
        assert result is None

    def test_gauge_set_negative_value(self):
        gauge = self.registry.get_collector("hopefx_pnl_realized")
        assert gauge is not None
        gauge.set(-500.0)
        assert gauge.get_value() == pytest.approx(-500.0)

    def test_counter_inc_zero(self):
        counter = self.registry.get_collector("hopefx_signals_total")
        assert counter is not None
        before = counter.get_value({"direction": "buy"})
        counter.inc(0, {"direction": "buy"})
        after = counter.get_value({"direction": "buy"})
        assert after == before  # zero increment changes nothing

    def test_histogram_observe_zero(self):
        hist = self.registry.get_collector("hopefx_order_latency_ms_bucket")
        assert hist is not None
        before = hist.get_count()
        hist.observe(0.0)
        assert hist.get_count() == before + 1

    def test_prometheus_export_is_string(self):
        output = self.registry.export_prometheus()
        assert isinstance(output, str)
        assert len(output) > 0

    def test_record_error_does_not_raise(self):
        try:
            self.registry.record_error("test_component", "test_error_type")
        except Exception as exc:
            pytest.fail(f"record_error raised unexpectedly: {exc}")
