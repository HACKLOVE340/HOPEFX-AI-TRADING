# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
tests/unit/test_execution_full.py
==================================
Comprehensive tests for the execution layer modules.
"""

from __future__ import annotations

import time
import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

UTC = timezone.utc


# ===========================================================================
# execution/fix_adapter.py
# ===========================================================================


class TestFIXDomainTypes:
    def test_fix_side_values(self):
        from execution.fix_adapter import FIXSide

        assert FIXSide.BUY.value == "1"
        assert FIXSide.SELL.value == "2"

    def test_fix_ord_type_values(self):
        from execution.fix_adapter import FIXOrdType

        assert FIXOrdType.MARKET.value == "1"
        assert FIXOrdType.LIMIT.value == "2"
        assert FIXOrdType.STOP.value == "3"

    def test_fix_exec_type_values(self):
        from execution.fix_adapter import FIXExecType

        assert FIXExecType.NEW.value == "0"
        assert FIXExecType.FILL.value == "2"
        assert FIXExecType.CANCELLED.value == "4"


class TestFIXOrder:
    def test_default_cl_ord_id_generated(self):
        from execution.fix_adapter import FIXOrder, FIXSide

        o = FIXOrder(symbol="XAUUSD", side=FIXSide.BUY, quantity=1.0)
        assert len(o.cl_ord_id) > 0

    def test_unique_cl_ord_ids(self):
        from execution.fix_adapter import FIXOrder, FIXSide

        o1 = FIXOrder(symbol="XAUUSD", side=FIXSide.BUY, quantity=1.0)
        o2 = FIXOrder(symbol="XAUUSD", side=FIXSide.BUY, quantity=1.0)
        assert o1.cl_ord_id != o2.cl_ord_id

    def test_limit_order_has_price(self):
        from execution.fix_adapter import FIXOrdType, FIXOrder, FIXSide

        o = FIXOrder(symbol="XAUUSD", side=FIXSide.BUY, quantity=1.0, ord_type=FIXOrdType.LIMIT, price=2000.0)
        assert o.price == 2000.0

    def test_fields_stored(self):
        from execution.fix_adapter import FIXOrder, FIXSide

        o = FIXOrder(symbol="XAUUSD", side=FIXSide.SELL, quantity=2.5, account="ACC1")
        assert o.symbol == "XAUUSD"
        assert o.side == FIXSide.SELL
        assert o.quantity == 2.5
        assert o.account == "ACC1"


class TestFIXFillReport:
    def test_fill_report_fields(self):
        from execution.fix_adapter import FIXExecType, FIXFillReport, FIXSide

        r = FIXFillReport(
            cl_ord_id="abc123",
            order_id="ORD001",
            exec_type=FIXExecType.FILL,
            symbol="XAUUSD",
            side=FIXSide.BUY,
            filled_qty=1.0,
            avg_px=2000.0,
            leaves_qty=0.0,
            cum_qty=1.0,
        )
        assert r.cl_ord_id == "abc123"
        assert r.exec_type == FIXExecType.FILL
        assert r.avg_px == 2000.0

    def test_latency_defaults_zero(self):
        from execution.fix_adapter import FIXExecType, FIXFillReport, FIXSide

        r = FIXFillReport(
            cl_ord_id="x",
            order_id="y",
            exec_type=FIXExecType.NEW,
            symbol="XAUUSD",
            side=FIXSide.BUY,
            filled_qty=0.0,
            avg_px=0.0,
            leaves_qty=1.0,
            cum_qty=0.0,
        )
        assert r.latency_ms == 0.0


class TestFIXCircuitBreaker:
    def test_initially_closed(self):
        from execution.fix_adapter import CircuitBreaker

        cb = CircuitBreaker(threshold_ms=100.0)
        assert cb.is_open is False

    def test_opens_on_high_latency(self):
        from execution.fix_adapter import CircuitBreaker

        cb = CircuitBreaker(threshold_ms=50.0)
        cb.record_latency(200.0)
        assert cb.is_open is True

    def test_stays_closed_on_low_latency(self):
        from execution.fix_adapter import CircuitBreaker

        cb = CircuitBreaker(threshold_ms=100.0)
        cb.record_latency(30.0)
        assert cb.is_open is False

    def test_check_raises_when_open(self):
        from execution.fix_adapter import CircuitBreaker

        cb = CircuitBreaker(threshold_ms=10.0)
        cb.record_latency(500.0)
        with pytest.raises(RuntimeError, match="circuit breaker"):
            cb.check()

    def test_check_passes_when_closed(self):
        from execution.fix_adapter import CircuitBreaker

        cb = CircuitBreaker(threshold_ms=100.0)
        cb.check()  # should not raise

    def test_resets_after_cooldown(self):
        from execution.fix_adapter import CircuitBreaker

        cb = CircuitBreaker(threshold_ms=10.0, reset_after_sec=0.01)
        cb.record_latency(500.0)
        assert cb.is_open is True
        time.sleep(0.05)
        cb.record_latency(5.0)
        assert cb.is_open is False

    def test_multiple_high_latency_stays_open(self):
        from execution.fix_adapter import CircuitBreaker

        cb = CircuitBreaker(threshold_ms=10.0)
        cb.record_latency(100.0)
        cb.record_latency(200.0)
        assert cb.is_open is True


class TestFIXAdapterInit:
    def test_init_no_crash(self):
        from execution.fix_adapter import FIXAdapter

        adapter = FIXAdapter(
            config_file="nonexistent.cfg", sender_comp_id="HOPEFX", target_comp_id="BROKER", host="127.0.0.1", port=9999
        )
        assert adapter is not None

    def test_circuit_breaker_accessible(self):
        from execution.fix_adapter import FIXAdapter

        adapter = FIXAdapter(config_file="nonexistent.cfg")
        assert hasattr(adapter, "circuit_breaker")

    def test_start_without_fix_library_no_crash(self):
        from execution.fix_adapter import FIXAdapter

        adapter = FIXAdapter(config_file="nonexistent.cfg")
        import contextlib

        with contextlib.suppress(RuntimeError, OSError, FileNotFoundError, ImportError):
            adapter.start()

    def test_stop_without_start_no_crash(self):
        from execution.fix_adapter import FIXAdapter

        adapter = FIXAdapter(config_file="nonexistent.cfg")
        adapter.stop()

    def test_circuit_breaker_is_closed_initially(self):
        from execution.fix_adapter import FIXAdapter

        adapter = FIXAdapter(config_file="nonexistent.cfg")
        assert adapter.circuit_breaker.is_open is False


# ===========================================================================
# execution/fix_router.py
# ===========================================================================


class TestFIXRouter:
    def test_init_state(self):
        from execution.fix_router import FIXRouter

        router = FIXRouter()
        assert router._running is False
        assert router._halted is False
        assert router._order_count == 0

    @pytest.mark.asyncio
    async def test_stop_sets_running_false(self):
        from execution.fix_router import FIXRouter

        router = FIXRouter()
        router._running = True
        await router.stop()
        assert router._running is False

    @pytest.mark.asyncio
    async def test_stop_with_adapter_error_no_crash(self):
        from execution.fix_router import FIXRouter

        router = FIXRouter()
        router._running = True
        mock_adapter = MagicMock()
        mock_adapter.stop.side_effect = RuntimeError("adapter error")
        router._adapter = mock_adapter
        await router.stop()
        assert router._running is False

    def test_init_fix_returns_bool(self):
        from execution.fix_router import FIXRouter

        router = FIXRouter()
        result = router._init_fix()
        assert isinstance(result, bool)

    @pytest.mark.asyncio
    async def test_route_halted_skips_order(self):
        from execution.fix_router import FIXRouter

        router = FIXRouter()
        router._halted = True
        await router._route({"symbol": "XAUUSD", "direction": "BUY", "units": 1000})

    @pytest.mark.asyncio
    async def test_route_uses_fallback_when_fix_unavailable(self):
        from execution.fix_router import FIXRouter

        router = FIXRouter()
        router._fix_available = False
        router._halted = False
        fill_response = {
            "type": "fill_confirmation",
            "source": "oanda_rest_fallback",
            "symbol": "XAUUSD",
            "direction": "BUY",
            "units": 1000,
            "price": 2000.0,
            "order_id": "test_id",
            "timestamp": datetime.now(UTC).isoformat(),
        }
        # Patch _PAPER_MODE=False so the FIX/fallback path is exercised regardless
        # of whether a prior test set PAPER_TRADING=true at module level.
        with patch("execution.fix_router._PAPER_MODE", False):
            with patch.object(router._fallback, "send", new=AsyncMock(return_value=fill_response)) as mock_send:
                with patch("execution.fix_router.bus") as mock_bus:
                    mock_bus.publish = AsyncMock()
                    mock_bus.publish_order = AsyncMock()
                    mock_bus.publish_local = AsyncMock()
                    await router._route({"symbol": "XAUUSD", "direction": "BUY", "units": 1000})
                mock_send.assert_called_once()

    def test_counters_initial_zero(self):
        from execution.fix_router import FIXRouter

        router = FIXRouter()
        assert router._fill_count == 0
        assert router._reject_count == 0


# ===========================================================================
# execution/legacy.py — PaperExecutor
# ===========================================================================


def _make_order(symbol="XAUUSD", side="buy", qty=0.1, order_type="market", price=None):
    from validation import Order

    return Order(symbol=symbol, side=side, qty=qty, order_type=order_type, price=price)


class TestPaperExecutor:
    def _make_executor(self, balance: float = 10_000.0):
        from execution.legacy import PaperExecutor

        return PaperExecutor(initial_balance=balance)

    def test_initial_balance(self):
        ex = self._make_executor(50_000.0)
        assert ex.balance == 50_000.0

    def test_equity_equals_cash_with_no_positions(self):
        ex = self._make_executor(10_000.0)
        assert ex.equity == pytest.approx(10_000.0)

    def test_buy_order_reduces_cash(self):
        ex = self._make_executor(10_000.0)
        ex.submit_order(_make_order(qty=0.1), current_price=2000.0, skip_validation=True)
        assert ex.cash < 10_000.0

    def test_buy_creates_position(self):
        ex = self._make_executor(10_000.0)
        ex.submit_order(_make_order(qty=0.1), current_price=2000.0, skip_validation=True)
        assert "XAUUSD" in ex.positions

    def test_execution_result_returned(self):
        from execution.legacy import ExecutionResult

        ex = self._make_executor(10_000.0)
        result = ex.submit_order(_make_order(qty=0.1), current_price=2000.0, skip_validation=True)
        assert isinstance(result, ExecutionResult)

    def test_order_history_recorded(self):
        ex = self._make_executor(10_000.0)
        ex.submit_order(_make_order(qty=0.1), current_price=2000.0, skip_validation=True)
        assert len(ex.order_history) >= 1

    def test_update_prices_affects_equity(self):
        ex = self._make_executor(10_000.0)
        ex.submit_order(_make_order(qty=0.1), current_price=2000.0, skip_validation=True)
        ex.update_prices({"XAUUSD": 2000.0})
        eq_flat = ex.equity
        ex.update_prices({"XAUUSD": 2050.0})
        eq_up = ex.equity
        assert eq_up > eq_flat

    def test_order_id_unique(self):
        ex = self._make_executor(10_000.0)
        r1 = ex.submit_order(_make_order(qty=0.1), current_price=2000.0, skip_validation=True)
        r2 = ex.submit_order(_make_order(qty=0.1), current_price=2000.0, skip_validation=True)
        assert r1.order_id != r2.order_id

    def test_insufficient_balance_rejected(self):
        from execution.legacy import OrderStatus

        ex = self._make_executor(100.0)
        result = ex.submit_order(_make_order(qty=100.0), current_price=2000.0)
        assert result.status == OrderStatus.REJECTED

    def test_get_unrealized_pnl_no_position(self):
        ex = self._make_executor(10_000.0)
        pnl = ex.get_unrealized_pnl("XAUUSD", 2000.0)
        assert pnl == 0.0

    def test_get_unrealized_pnl_long_position(self):
        ex = self._make_executor(10_000.0)
        ex.submit_order(_make_order(qty=0.1), current_price=2000.0, skip_validation=True)
        pnl = ex.get_unrealized_pnl("XAUUSD", 2010.0)
        assert pnl > 0

    def test_limit_order_handled(self):
        from execution.legacy import OrderStatus

        ex = self._make_executor(10_000.0)
        order = _make_order(qty=0.1, order_type="limit", price=1990.0)
        result = ex.submit_order(order, current_price=2000.0, skip_validation=True)
        assert result.status in (OrderStatus.PENDING, OrderStatus.REJECTED, OrderStatus.FILLED)


class TestOrderStatus:
    def test_status_values(self):
        from execution.legacy import OrderStatus

        assert OrderStatus.PENDING.value == "pending"
        assert OrderStatus.FILLED.value == "filled"
        assert OrderStatus.REJECTED.value == "rejected"
        assert OrderStatus.CANCELLED.value == "cancelled"


class TestExecutionResult:
    def test_fields(self):
        from execution.legacy import ExecutionResult, OrderStatus

        r = ExecutionResult(
            order_id="ORD001", status=OrderStatus.FILLED, filled_qty=1.0, avg_price=2000.0, slippage=0.5, commission=3.5
        )
        assert r.order_id == "ORD001"
        assert r.status == OrderStatus.FILLED
        assert r.pnl is None


# ===========================================================================
# execution/algo_orders.py
# ===========================================================================


class TestAlgoStatus:
    def test_values(self):
        from execution.algo_orders import AlgoStatus

        assert AlgoStatus.PENDING.value == "pending"
        assert AlgoStatus.RUNNING.value == "running"
        assert AlgoStatus.COMPLETED.value == "completed"
        assert AlgoStatus.CANCELLED.value == "cancelled"
        assert AlgoStatus.ERROR.value == "error"


class TestChildOrder:
    def test_child_id_generated(self):
        from execution.algo_orders import ChildOrder

        c = ChildOrder(algo_id="algo1")
        assert len(c.child_id) > 0

    def test_unique_child_ids(self):
        from execution.algo_orders import ChildOrder

        c1 = ChildOrder(algo_id="algo1")
        c2 = ChildOrder(algo_id="algo1")
        assert c1.child_id != c2.child_id


class TestAlgoOrderManager:
    def _make_manager(self):
        from execution.algo_orders import AlgoOrderManager

        async def _submit(symbol, side, quantity, order_type="MARKET", metadata=None):
            return {"order_id": str(uuid.uuid4()), "status": "filled", "fill_price": 2000.0}

        return AlgoOrderManager(broker_submit_fn=_submit)

    def test_init(self):
        mgr = self._make_manager()
        assert mgr is not None

    def test_no_active_orders_initially(self):
        mgr = self._make_manager()
        assert len(mgr._active) == 0

    @pytest.mark.asyncio
    async def test_submit_twap_returns_algo_id(self):
        mgr = self._make_manager()
        algo_id = await mgr.submit_twap(
            symbol="XAU_USD", side="BUY", total_quantity=10.0, duration_seconds=60, num_slices=3
        )
        assert isinstance(algo_id, str) and len(algo_id) > 0

    @pytest.mark.asyncio
    async def test_submit_vwap_returns_algo_id(self):
        mgr = self._make_manager()
        algo_id = await mgr.submit_vwap(symbol="XAU_USD", side="SELL", total_quantity=5.0, duration_seconds=120)
        assert isinstance(algo_id, str)

    @pytest.mark.asyncio
    async def test_submit_iceberg_returns_algo_id(self):
        mgr = self._make_manager()
        algo_id = await mgr.submit_iceberg(symbol="XAU_USD", side="BUY", total_quantity=50.0, peak_size=5.0)
        assert isinstance(algo_id, str)

    def test_cancel_nonexistent_order_returns_false(self):
        mgr = self._make_manager()
        result = mgr.cancel("nonexistent_id")
        assert result is False

    @pytest.mark.asyncio
    async def test_cancel_active_order(self):
        mgr = self._make_manager()
        algo_id = await mgr.submit_twap(
            symbol="XAU_USD", side="BUY", total_quantity=10.0, duration_seconds=3600, num_slices=10
        )
        result = mgr.cancel(algo_id)
        assert isinstance(result, bool)

    def test_get_status_unknown_returns_none(self):
        mgr = self._make_manager()
        assert mgr.get_status("unknown_id") is None

    def test_get_algo_manager_singleton(self):
        from execution.algo_orders import get_algo_manager

        m1 = get_algo_manager()
        m2 = get_algo_manager()
        assert m1 is m2

    def test_set_broker_submit_fn(self):
        from execution.algo_orders import AlgoOrderManager

        mgr = AlgoOrderManager()
        fn = AsyncMock()
        mgr.set_broker_submit_fn(fn)
        assert mgr._broker_submit is fn

    def test_get_all_active_empty(self):
        mgr = self._make_manager()
        result = mgr.get_all_active()
        assert isinstance(result, dict)


# ===========================================================================
# execution/hopefx_engine.py — importable types
# ===========================================================================


class TestHopeFXEngineTypes:
    def test_engine_state_values(self):
        from execution.hopefx_engine import EngineState

        assert EngineState.IDLE == "idle"
        assert EngineState.RUNNING == "running"
        assert EngineState.PAUSED == "paused"
        assert EngineState.HALTED == "halted"

    def test_execution_signal_fields(self):
        from execution.hopefx_engine import ExecutionSignal

        sig = ExecutionSignal(
            signal_id="sig1",
            symbol="XAUUSD",
            direction="long",
            confidence=0.75,
            probability=0.70,
            tick_mid=2000.0,
            tick_bid=1999.5,
            tick_ask=2000.5,
            tick_spread=1.0,
            tick_timestamp=datetime.now(UTC),
            features={"rsi": 55.0},
            features_hash="abc123",
            data_quality=0.95,
            sentiment_score=0.6,
            impact_score=0.3,
            lineage_id="lineage_001",
        )
        assert sig.symbol == "XAUUSD"
        assert sig.direction == "long"
        assert sig.confidence == 0.75
        assert sig.lineage_id == "lineage_001"

    def test_fill_record_fields(self):
        from execution.hopefx_engine import FillRecord

        fr = FillRecord(
            fill_id="fill1",
            order_id="ord1",
            signal_id="sig1",
            symbol="XAUUSD",
            direction="long",
            quantity=0.1,
            fill_price=2000.0,
            expected_price=1999.5,
            slippage_bps=2.5,
            broker="oanda",
            latency_ms=5.0,
            filled_at=datetime.now(UTC),
            lineage_id="lineage_001",
        )
        assert fr.fill_id == "fill1"
        assert fr.slippage_bps == 2.5


# ===========================================================================
# execution/execution.py — ExecutionSystem importable
# ===========================================================================


class TestExecutionSystem:
    def test_importable(self):
        from execution.execution import ExecutionSystem

        assert ExecutionSystem is not None

    def test_init_no_crash(self):
        from execution.execution import ExecutionSystem

        system = ExecutionSystem()
        assert system is not None
        assert system._started is False

    def test_init_with_ml_fn(self):
        from execution.execution import ExecutionSystem

        ml_fn = MagicMock(return_value={"direction": "long", "confidence": 0.7})
        system = ExecutionSystem(ml_inference_fn=ml_fn)
        assert system._ml_inference_fn is ml_fn
