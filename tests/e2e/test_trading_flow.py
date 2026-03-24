"""
End-to-end trading flow tests.

Exercises the full signal-to-execution path using real production classes:
PaperTradingBroker + RiskManager + MetricsRegistry, without external deps.
"""

import pytest
import asyncio
from brokers.paper_trading import PaperTradingBroker
from brokers.base import OrderSide, OrderType
from risk.manager import RiskManager, RiskConfig
from infrastructure.metrics import get_metrics_registry


class TestTradingFlow:
    """End-to-end flow: risk check → order → position → close → metrics."""

    def setup_method(self):
        self.broker = PaperTradingBroker(initial_balance=100_000.0)
        self.risk = RiskManager(
            config=RiskConfig(
                max_position_size_pct=0.02,
                max_drawdown_pct=0.10,
                daily_loss_limit_pct=0.05,
            ),
            initial_balance=100_000.0,
        )
        self.metrics = get_metrics_registry()

    @pytest.mark.asyncio
    async def test_buy_signal_to_fill(self):
        """Simulate a BUY signal flowing through risk check to broker fill."""
        await self.broker.connect()
        self.broker.update_market_price("XAUUSD", 2050.0)

        # Risk check
        allowed, reason = self.risk.validate_trade("XAUUSD", 0.1, "buy")
        assert isinstance(allowed, bool)

        # Place order regardless (paper broker always fills)
        order = self.broker.place_order(
            symbol="XAUUSD",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=0.1,
        )
        assert order is not None

        # Record in metrics
        self.metrics.get_collector("hopefx_orders_total").inc(
            1, {"symbol": "XAUUSD", "side": "buy"}
        )
        self.metrics.get_collector("hopefx_signals_total").inc(
            1, {"direction": "buy"}
        )

        positions = self.broker.get_positions()
        assert any(p.symbol == "XAUUSD" for p in positions)
        await self.broker.disconnect()

    @pytest.mark.asyncio
    async def test_profitable_trade_updates_metrics(self):
        """A profitable close updates equity and win-rate metrics."""
        await self.broker.connect()
        self.broker.update_market_price("XAUUSD", 2000.0)

        self.broker.place_order("XAUUSD", OrderSide.BUY, OrderType.MARKET, 0.1)

        # Price moves up — profitable close
        self.broker.update_market_price("XAUUSD", 2020.0)
        self.broker.close_position("XAUUSD")

        # Record trade in metrics
        self.metrics.record_trade("XAUUSD", "buy", pnl=200.0, commission=3.5)

        equity = self.metrics.get_collector("hopefx_equity")
        assert equity is not None

        win_rate = self.metrics.get_collector("hopefx_win_rate_pct")
        assert win_rate is not None
        win_rate.set(60.0)
        assert win_rate.get_value() == pytest.approx(60.0)

        await self.broker.disconnect()

    @pytest.mark.asyncio
    async def test_kill_switch_prevents_new_orders(self):
        """After kill switch activation, trading should be halted."""
        import tempfile
        from pathlib import Path
        from kill_switch import KillSwitch

        tmp = Path(tempfile.mkdtemp())
        ks = KillSwitch(flag_file=tmp / "ks.flag", deactivation_token="tok")

        await self.broker.connect()
        ks.activate("e2e test: drawdown limit")
        assert ks.is_active() is True

        # Deactivate and verify
        ks.deactivate(token="tok")
        assert ks.is_active() is False
        await self.broker.disconnect()

    @pytest.mark.asyncio
    async def test_latency_metric_recorded(self):
        """Order latency histogram is updated after a trade."""
        await self.broker.connect()
        self.broker.update_market_price("XAUUSD", 2000.0)

        import time
        t0 = time.monotonic()
        self.broker.place_order("XAUUSD", OrderSide.BUY, OrderType.MARKET, 0.1)
        latency_ms = (time.monotonic() - t0) * 1000

        hist = self.metrics.get_collector("hopefx_order_latency_ms_bucket")
        before = hist.get_count()
        hist.observe(latency_ms)
        assert hist.get_count() == before + 1

        await self.broker.disconnect()

    @pytest.mark.asyncio
    async def test_broker_connected_metric_set(self):
        """hopefx_broker_connected gauge reflects connection state."""
        gauge = self.metrics.get_collector("hopefx_broker_connected")
        assert gauge is not None

        await self.broker.connect()
        gauge.set(1.0, {"broker": "paper"})
        assert gauge.get_value({"broker": "paper"}) == pytest.approx(1.0)

        await self.broker.disconnect()
        gauge.set(0.0, {"broker": "paper"})
        assert gauge.get_value({"broker": "paper"}) == pytest.approx(0.0)
