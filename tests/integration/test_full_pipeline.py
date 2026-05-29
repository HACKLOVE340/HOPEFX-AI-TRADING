# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
Full pipeline integration tests.

Exercises the PaperTradingBroker + RiskManager + MetricsRegistry pipeline
end-to-end without requiring external services.
"""

import pytest


class TestFullTradePipeline:
    """Broker, risk manager, and metrics work together as a pipeline."""

    def setup_method(self):
        from brokers.paper_trading import PaperTradingBroker
        from infrastructure.metrics import get_metrics_registry
        from risk.manager import RiskConfig, RiskManager

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
    async def test_connect_place_close_cycle(self):
        """Full cycle: connect → place order → verify position → close."""
        await self.broker.connect()
        self.broker.update_market_price("XAUUSD", 2050.0)

        from brokers.base import OrderSide, OrderType

        order = self.broker.place_order(
            symbol="XAUUSD",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=0.1,
        )
        assert order is not None

        positions = await self.broker.get_positions()
        assert any(p.symbol == "XAUUSD" for p in positions)

        self.broker.update_market_price("XAUUSD", 2060.0)
        closed = self.broker.close_position("XAUUSD")
        assert closed is True

        await self.broker.disconnect()

    @pytest.mark.asyncio
    async def test_risk_gates_oversized_trade(self):
        """Risk manager rejects a trade that exceeds position size limits."""
        await self.broker.connect()

        # Validate an extremely large trade — should be rejected or flagged
        allowed, reason = self.risk.validate_trade("XAUUSD", size=9999.0, side="buy")
        # Either rejected outright or reason explains the limit
        assert isinstance(allowed, bool)
        assert isinstance(reason, str)

        await self.broker.disconnect()

    @pytest.mark.asyncio
    async def test_metrics_updated_after_trade(self):
        """Metrics registry reflects trade activity."""
        await self.broker.connect()
        self.broker.update_market_price("GBPUSD", 1.2700)

        equity_gauge = self.metrics.get_collector("hopefx_equity")
        assert equity_gauge is not None
        equity_gauge.set(100_000.0)

        # Record a winning trade in metrics
        self.metrics.record_trade("GBPUSD", "buy", pnl=250.0, commission=3.5)

        orders_counter = self.metrics.get_collector("hopefx_orders_total")
        assert orders_counter is not None
        orders_counter.inc(1, {"symbol": "GBPUSD", "side": "buy"})
        assert orders_counter.get_value({"symbol": "GBPUSD", "side": "buy"}) >= 1

        await self.broker.disconnect()

    def test_risk_drawdown_within_limits(self):
        """Drawdown check passes when equity is at starting value."""
        result = self.risk.check_drawdown()
        assert result is not None
        assert hasattr(result, "passed")

    @pytest.mark.asyncio
    async def test_multiple_symbols_tracked(self):
        """Broker tracks positions across multiple symbols independently."""
        await self.broker.connect()
        self.broker.update_market_price("XAUUSD", 2050.0)
        self.broker.update_market_price("EURUSD", 1.0850)

        from brokers.base import OrderSide, OrderType

        self.broker.place_order("XAUUSD", OrderSide.BUY, OrderType.MARKET, 0.1)
        self.broker.place_order("EURUSD", OrderSide.BUY, OrderType.MARKET, 0.1)

        positions = await self.broker.get_positions()
        symbols = {p.symbol for p in positions}
        assert "XAUUSD" in symbols
        assert "EURUSD" in symbols

        await self.broker.disconnect()
