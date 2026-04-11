# tests/unit/test_execution_coverage13.py
"""Targeted coverage for position_manager, execution/__init__, tca, trade_executor missing lines."""
from __future__ import annotations

import pytest


# ── execution/__init__.py — import all re-exports ─────────────────────────────

class TestExecutionInit:
    def test_import_execution_package(self):
        import execution
        assert execution is not None

    def test_legacy_exports(self):
        from execution import ExecutionResult, Order, OrderStatus, PaperExecutor, SmartOrderRouter
        assert ExecutionResult is not None
        assert Order is not None
        assert OrderStatus is not None
        assert PaperExecutor is not None
        assert SmartOrderRouter is not None

    def test_trade_executor_export(self):
        from execution import TradeExecutor
        assert TradeExecutor is not None

    def test_smart_router_export(self):
        from execution import SmartRouter
        assert SmartRouter is not None

    def test_position_manager_export(self):
        from execution import PositionManager
        assert PositionManager is not None

    def test_oms_exports(self):
        from execution import ComplexOrderManager, OrderLifecycleManager
        assert OrderLifecycleManager is not None
        assert ComplexOrderManager is not None

    def test_position_tracker_export(self):
        from execution import PositionTracker
        assert PositionTracker is not None

    def test_async_engine_export(self):
        from execution import AsyncExecutionEngine
        assert AsyncExecutionEngine is not None

    def test_tca_engine_export(self):
        from execution import TCAEngine
        assert TCAEngine is not None

    def test_sl_tp_monitor_export(self):
        from execution import SLTPMonitor
        assert SLTPMonitor is not None

    def test_throttler_export(self):
        from execution import MessageThrottler
        assert MessageThrottler is not None

    def test_spread_monitor_export(self):
        from execution import SpreadMonitor
        assert SpreadMonitor is not None

    def test_broker_circuit_breaker_export(self):
        from execution import BrokerCircuitBreaker
        assert BrokerCircuitBreaker is not None

    def test_order_algorithms_export(self):
        from execution import TWAPExecutor, VWAPExecutor
        assert TWAPExecutor is not None
        assert VWAPExecutor is not None


# ── position_manager — Prometheus helpers and validation paths ────────────────

class TestPositionManagerValidation:
    @pytest.mark.asyncio
    async def test_open_invalid_side_raises(self):
        from execution.position_manager import PositionManager

        pm = PositionManager()
        with pytest.raises(ValueError, match="side must be"):
            await pm.open_position("XAUUSD", "long", 0.1, 2350.0)

    @pytest.mark.asyncio
    async def test_open_zero_quantity_raises(self):
        from execution.position_manager import PositionManager

        pm = PositionManager()
        with pytest.raises(ValueError, match="quantity"):
            await pm.open_position("XAUUSD", "BUY", 0.0, 2350.0)

    @pytest.mark.asyncio
    async def test_open_negative_quantity_raises(self):
        from execution.position_manager import PositionManager

        pm = PositionManager()
        with pytest.raises(ValueError, match="quantity"):
            await pm.open_position("XAUUSD", "BUY", -1.0, 2350.0)

    @pytest.mark.asyncio
    async def test_open_zero_price_raises(self):
        from execution.position_manager import PositionManager

        pm = PositionManager()
        with pytest.raises(ValueError, match="entry_price"):
            await pm.open_position("XAUUSD", "BUY", 0.1, 0.0)

    @pytest.mark.asyncio
    async def test_close_zero_price_raises(self):
        from execution.position_manager import PositionManager

        pm = PositionManager()
        await pm.open_position("XAUUSD", "BUY", 0.1, 2350.0)
        with pytest.raises(ValueError, match="fill_price"):
            await pm.close_position("XAUUSD", fill_price=0.0)

    @pytest.mark.asyncio
    async def test_open_with_sl_tp(self):
        from execution.position_manager import PositionManager

        pm = PositionManager()
        pos = await pm.open_position(
            "XAUUSD", "BUY", 0.1, 2350.0,
            stop_loss=2340.0, take_profit=2370.0,
            strategy_id="test_strat",
        )
        assert pos.stop_loss == 2340.0
        assert pos.take_profit == 2370.0
        assert pos.strategy_id == "test_strat"

    @pytest.mark.asyncio
    async def test_open_with_position_id(self):
        from execution.position_manager import PositionManager

        pm = PositionManager()
        pos = await pm.open_position("XAUUSD", "BUY", 0.1, 2350.0, position_id="custom_id")
        assert pos.position_id == "custom_id"

    @pytest.mark.asyncio
    async def test_open_with_metadata(self):
        from execution.position_manager import PositionManager

        pm = PositionManager()
        pos = await pm.open_position("XAUUSD", "BUY", 0.1, 2350.0, metadata={"source": "test"})
        assert pos.metadata["source"] == "test"

    @pytest.mark.asyncio
    async def test_update_stop_loss(self):
        from execution.position_manager import PositionManager

        pm = PositionManager()
        await pm.open_position("XAUUSD", "BUY", 0.1, 2350.0)
        pos = await pm.update_position("XAUUSD", stop_loss=2345.0)
        assert pos.stop_loss == 2345.0

    @pytest.mark.asyncio
    async def test_update_take_profit(self):
        from execution.position_manager import PositionManager

        pm = PositionManager()
        await pm.open_position("XAUUSD", "BUY", 0.1, 2350.0)
        pos = await pm.update_position("XAUUSD", take_profit=2380.0)
        assert pos.take_profit == 2380.0

    @pytest.mark.asyncio
    async def test_sell_pnl_profit(self):
        from execution.position_manager import PositionManager

        pm = PositionManager()
        await pm.open_position("XAUUSD", "SELL", 1.0, 2350.0)
        result = await pm.close_position("XAUUSD", fill_price=2340.0)
        assert result.realized_pnl > 0  # sold high, closed lower

    @pytest.mark.asyncio
    async def test_sell_pnl_loss(self):
        from execution.position_manager import PositionManager

        pm = PositionManager()
        await pm.open_position("XAUUSD", "SELL", 1.0, 2350.0)
        result = await pm.close_position("XAUUSD", fill_price=2360.0)
        assert result.realized_pnl < 0

    @pytest.mark.asyncio
    async def test_get_unrealized_pnl_sell(self):
        from execution.position_manager import PositionManager

        pm = PositionManager()
        await pm.open_position("XAUUSD", "SELL", 1.0, 2350.0)
        await pm.update_position("XAUUSD", last_price=2340.0)
        pnl = pm.get_unrealized_pnl()
        assert pnl["XAUUSD"] > 0

    @pytest.mark.asyncio
    async def test_get_history_limit(self):
        from execution.position_manager import PositionManager

        pm = PositionManager()
        for i in range(5):
            await pm.open_position(f"SYM{i}", "BUY", 0.1, 2350.0)
            await pm.close_position(f"SYM{i}", fill_price=2360.0)
        history = pm.get_history(limit=3)
        assert len(history) == 3

    @pytest.mark.asyncio
    async def test_prom_helpers_no_crash(self):
        """Prometheus helpers should not raise even when prometheus_client is absent."""
        from execution.position_manager import _prom_mutation, _prom_pnl_observe, _prom_positions_open_set

        _prom_positions_open_set("XAUUSD", 1.0)
        _prom_pnl_observe(100.0)
        _prom_mutation("open")


# ── tca.py — missing benchmark types and VWAP/TWAP paths ─────────────────────

class TestTCABenchmarkTypes:
    @pytest.mark.asyncio
    async def test_vwap_benchmark(self):
        from decimal import Decimal
        from core.types import Side
        from execution.tca import BenchmarkType, TCAEngine

        engine = TCAEngine()
        await engine.start_order(
            "ord_vwap", "XAUUSD", Side.BUY, Decimal("1"), Decimal("2350"),
            benchmark=BenchmarkType.VWAP,
        )
        assert "ord_vwap" in engine._active_orders

    @pytest.mark.asyncio
    async def test_twap_benchmark(self):
        from decimal import Decimal
        from core.types import Side
        from execution.tca import BenchmarkType, TCAEngine

        engine = TCAEngine()
        await engine.start_order(
            "ord_twap", "XAUUSD", Side.BUY, Decimal("1"), Decimal("2350"),
            benchmark=BenchmarkType.TWAP,
        )
        assert "ord_twap" in engine._active_orders

    @pytest.mark.asyncio
    async def test_close_benchmark(self):
        from decimal import Decimal
        from core.types import Side
        from execution.tca import BenchmarkType, TCAEngine

        engine = TCAEngine()
        await engine.start_order(
            "ord_close", "XAUUSD", Side.BUY, Decimal("1"), Decimal("2350"),
            benchmark=BenchmarkType.CLOSE,
        )
        assert "ord_close" in engine._active_orders

    @pytest.mark.asyncio
    async def test_complete_with_vwap_cache(self):
        from collections import deque
        from decimal import Decimal
        from datetime import datetime, timezone
        from core.types import Fill, Side, Venue
        from execution.tca import BenchmarkType, TCAEngine

        engine = TCAEngine()
        # _vwap_cache stores a deque of (ts, price, qty) tuples
        engine._vwap_cache["XAUUSD"] = deque([(datetime.now(timezone.utc), Decimal("2348"), Decimal("1"))])
        await engine.start_order(
            "ord_v2", "XAUUSD", Side.BUY, Decimal("1"), Decimal("2350"),
            benchmark=BenchmarkType.VWAP,
        )
        fill = Fill(
            order_id="ord_v2", fill_id="f1", symbol="XAUUSD",
            side=Side.BUY, price=Decimal("2351"), quantity=Decimal("1"),
            commission=Decimal("0.5"), timestamp=datetime.now(timezone.utc),
            venue=Venue.PAPER,
        )
        await engine.record_fill("ord_v2", fill)
        metrics = await engine.complete_order("ord_v2")
        assert metrics is not None

    @pytest.mark.asyncio
    async def test_complete_with_twap_cache(self):
        from collections import deque
        from decimal import Decimal
        from datetime import datetime, timezone
        from core.types import Fill, Side, Venue
        from execution.tca import BenchmarkType, TCAEngine

        engine = TCAEngine()
        engine._twap_cache["XAUUSD"] = deque([(datetime.now(timezone.utc), Decimal("2349"))])
        await engine.start_order(
            "ord_t2", "XAUUSD", Side.BUY, Decimal("1"), Decimal("2350"),
            benchmark=BenchmarkType.TWAP,
        )
        fill = Fill(
            order_id="ord_t2", fill_id="f2", symbol="XAUUSD",
            side=Side.BUY, price=Decimal("2351"), quantity=Decimal("1"),
            commission=Decimal("0.5"), timestamp=datetime.now(timezone.utc),
            venue=Venue.PAPER,
        )
        await engine.record_fill("ord_t2", fill)
        metrics = await engine.complete_order("ord_t2")
        assert metrics is not None

    def test_register_cost_callback(self):
        from execution.tca import TCAEngine

        engine = TCAEngine()
        cb = lambda m: None  # noqa: E731
        engine.register_cost_callback(cb)
        assert cb in engine._cost_callbacks

    def test_active_orders_dict(self):
        from execution.tca import TCAEngine

        engine = TCAEngine()
        assert isinstance(engine._active_orders, dict)


# ── trade_executor — _notify_inference_engine_fill and get_risk_status ────────

class TestTradeExecutorMiscPaths:
    def _executor(self):
        from unittest.mock import AsyncMock, MagicMock
        from execution.trade_executor import TradeExecutor

        rm = MagicMock()
        rm.current_drawdown = 0.0
        rm._trading_halted = False
        rm._halt_reason = None
        rm.current_equity = 100000.0
        rm.daily_starting_equity = 100000.0
        rm.update_equity = MagicMock()
        broker = MagicMock()
        broker.place_market_order = AsyncMock()
        pt = MagicMock()
        pt.get_position = MagicMock(return_value=None)
        pt.add_position = AsyncMock()
        return TradeExecutor(broker=broker, risk_manager=rm, position_tracker=pt)

    def test_get_risk_status_keys(self):
        ex = self._executor()
        status = ex.get_risk_status()
        assert "consecutive_losses" in status
        assert "trading_halted" in status

    @pytest.mark.asyncio
    async def test_notify_inference_engine_fill_no_crash(self):
        from execution.trade_executor import ExecutionResult, OrderStatus

        ex = self._executor()
        result = ExecutionResult(
            success=True, order_id="o1",
            filled_quantity=0.01, average_price=2350.0,
            commission=0.5, status=OrderStatus.FILLED, message="ok",
        )
        # Should not raise even if inference engine is unavailable
        await ex._notify_inference_engine_fill(result, {"symbol": "XAUUSD", "confidence": 0.8})

    @pytest.mark.asyncio
    async def test_async_callback_fires(self):
        from execution.trade_executor import ExecutionResult, OrderStatus

        ex = self._executor()
        fired = []

        async def async_cb(r, s):
            fired.append(r)

        ex.register_callback(async_cb)
        result = ExecutionResult(
            success=True, order_id="o1",
            filled_quantity=0.01, average_price=2350.0,
            commission=0.5, status=OrderStatus.FILLED, message="ok",
        )
        await ex._notify_callbacks(result, {"symbol": "XAUUSD"})
        assert len(fired) == 1

    def test_clamp_no_equity_returns_size(self):
        from unittest.mock import MagicMock
        from execution.trade_executor import TradeExecutor

        rm = MagicMock()
        rm.current_drawdown = 0.0
        rm._trading_halted = False
        rm.current_equity = None
        rm.current_balance = None
        rm.initial_balance = 0.0
        broker = MagicMock()
        pt = MagicMock()
        ex = TradeExecutor(broker=broker, risk_manager=rm, position_tracker=pt)
        result = ex._clamp_size_to_risk_cap({"size": 1.0, "entry_price": 2350.0}, 1.0)
        assert result == 1.0

    def test_clamp_no_entry_price_notional_cap(self):
        from unittest.mock import MagicMock
        from execution.trade_executor import TradeExecutor

        rm = MagicMock()
        rm.current_drawdown = 0.0
        rm._trading_halted = False
        rm.current_equity = 100000.0
        rm.current_balance = 100000.0
        rm.initial_balance = 100000.0
        broker = MagicMock()
        pt = MagicMock()
        ex = TradeExecutor(broker=broker, risk_manager=rm, position_tracker=pt)
        # No entry_price → returns size unchanged
        result = ex._clamp_size_to_risk_cap({"size": 1.0}, 1.0)
        assert result == 1.0
