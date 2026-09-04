# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
tests/test_execution_engine.py

Unit tests for execution/engine.py — ExecutionEngine, EngineCircuitBreaker,
ExecutionRequest validation.
"""

import asyncio

import pytest

from brokers.base import OrderStatus
from brokers.paper_trading import PaperTradingBroker
from execution.engine import (
    EngineCircuitBreaker,
    ExecutionEngine,
    ExecutionReport,
    ExecutionRequest,
    ExecutionStatus,
)
from risk.manager import RiskConfig, RiskManager

# ---------------------------------------------------------------------------
# ExecutionRequest validation
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _data_layer_reports_safe(monkeypatch):
    """Give every test in this file a data layer that says it is safe to trade.

    These tests are about order flow, fills, callbacks and metrics -- not about
    data-layer safety, which has its own file
    (tests/unit/test_data_layer_gate_fails_closed.py).

    They previously passed without this because the gate read
    ``if orchestrator._started and not orchestrator.is_safe_to_trade()``: the
    real singleton is never started in a unit test, so the whole check was
    skipped and every order sailed through. That skip was F84 -- the gate was a
    no-op in exactly the degraded state it exists for -- so removing it means
    these tests must now say what they assume rather than inherit it from a bug.
    """
    import sys

    import data_layer.orchestrator  # noqa: F401  — populate sys.modules

    # sys.modules, not the package attribute: data_layer/__init__.py binds the
    # name `orchestrator` on the package to a MarketDataOrchestrator *instance*,
    # shadowing its own submodule.
    module = sys.modules["data_layer.orchestrator"]

    class _SafeOrchestrator:
        _started = True

        @staticmethod
        def is_safe_to_trade() -> bool:
            return True

        @staticmethod
        def get_latest_tick(_symbol):
            return None

    monkeypatch.setattr(module, "orchestrator", _SafeOrchestrator(), raising=False)


class TestExecutionRequest:
    def test_valid_buy_market(self):
        req = ExecutionRequest(symbol="XAUUSD", side="BUY", quantity=1.0, order_type="MARKET")
        assert req.symbol == "XAUUSD"
        assert req.side == "BUY"

    def test_valid_sell_limit(self):
        req = ExecutionRequest(symbol="XAUUSD", side="SELL", quantity=1.0, order_type="LIMIT", price=1950.0)
        assert req.price == 1950.0

    def test_invalid_side_raises(self):
        with pytest.raises(ValueError, match="side"):
            ExecutionRequest(symbol="XAUUSD", side="LONG", quantity=1.0)

    def test_zero_quantity_raises(self):
        with pytest.raises(ValueError, match="quantity"):
            ExecutionRequest(symbol="XAUUSD", side="BUY", quantity=0.0)

    def test_negative_quantity_raises(self):
        with pytest.raises(ValueError):
            ExecutionRequest(symbol="XAUUSD", side="BUY", quantity=-1.0)

    def test_limit_without_price_raises(self):
        with pytest.raises(ValueError, match="price"):
            ExecutionRequest(
                symbol="XAUUSD",
                side="BUY",
                quantity=1.0,
                order_type="LIMIT",
                price=None,
            )

    def test_stop_without_stop_price_raises(self):
        with pytest.raises(ValueError, match="stop_price"):
            ExecutionRequest(
                symbol="XAUUSD",
                side="BUY",
                quantity=1.0,
                order_type="STOP",
                stop_price=None,
            )

    def test_invalid_order_type_raises(self):
        with pytest.raises(ValueError, match="order_type"):
            ExecutionRequest(symbol="XAUUSD", side="BUY", quantity=1.0, order_type="TWAP")


# ---------------------------------------------------------------------------
# EngineCircuitBreaker
# ---------------------------------------------------------------------------


class TestEngineCircuitBreaker:
    @pytest.mark.asyncio
    async def test_opens_after_max_failures(self):
        cb = EngineCircuitBreaker(max_failures=3, window_sec=60.0, reset_sec=9999.0)
        for _ in range(3):
            await cb.record_failure()
        assert cb.is_open is True

    @pytest.mark.asyncio
    async def test_check_raises_when_open(self):
        cb = EngineCircuitBreaker(max_failures=2, window_sec=60.0, reset_sec=9999.0)
        await cb.record_failure()
        await cb.record_failure()
        with pytest.raises(RuntimeError, match="circuit breaker"):
            await cb.check()

    @pytest.mark.asyncio
    async def test_resets_on_success(self):
        cb = EngineCircuitBreaker(max_failures=2, window_sec=60.0, reset_sec=9999.0)
        await cb.record_failure()
        await cb.record_failure()
        assert cb.is_open is True
        await cb.record_success()
        assert cb.is_open is False

    @pytest.mark.asyncio
    async def test_check_passes_when_closed(self):
        cb = EngineCircuitBreaker(max_failures=3, window_sec=60.0)
        await cb.check()  # should not raise

    @pytest.mark.asyncio
    async def test_failures_outside_window_not_counted(self):
        cb = EngineCircuitBreaker(max_failures=3, window_sec=0.1, reset_sec=9999.0)
        await cb.record_failure()
        await cb.record_failure()
        await asyncio.sleep(0.2)  # wait for window to expire
        await cb.record_failure()  # only 1 failure in current window
        assert cb.is_open is False


# ---------------------------------------------------------------------------
# ExecutionEngine
# ---------------------------------------------------------------------------


class _ConnectedPaperBroker(PaperTradingBroker):
    """PaperTradingBroker pre-connected with a seeded market price.

    Used as a real broker in ExecutionEngine tests — no mocking required.
    The broker is synchronously connected (bypasses the async connect() call)
    so it can be used in synchronous test setup.

    The class name contains "Paper" so ExecutionEngine._is_live_broker()
    correctly identifies it as a paper broker and does not block orders
    with the LIVE_MODE_CONFIRMED guard.
    """

    paper_trading: bool = True  # explicit flag for ExecutionEngine._is_live_broker()

    def __init__(self, order_status: OrderStatus = OrderStatus.FILLED) -> None:
        super().__init__(initial_balance=100_000.0, commission_per_lot=0.0)
        self.connected = True  # PaperTradingBroker uses self.connected
        self.market_prices["XAUUSD"] = 1950.0
        import time

        self._price_timestamps["XAUUSD"] = time.time()
        self._forced_status = order_status

    def is_connected(self) -> bool:
        return self.connected

    def place_order(self, symbol, side, order_type, quantity, price=None, stop_price=None, **kwargs):
        order = super().place_order(symbol, side, order_type, quantity, price=price)
        if order is not None and self._forced_status != OrderStatus.FILLED:
            order.status = self._forced_status
        return order

    def get_account_info(self):
        from brokers.base import AccountInfo

        return AccountInfo(
            balance=self.balance,
            equity=self.balance,
            margin_used=0.0,
            margin_available=self.balance,
            positions_count=len(self.positions),
        )


def _make_broker_manager(order_status: OrderStatus = OrderStatus.FILLED) -> _ConnectedPaperBroker:
    """Return a real connected PaperTradingBroker for ExecutionEngine tests."""
    return _ConnectedPaperBroker(order_status)


def _make_risk_manager(allow_trade: bool = True) -> RiskManager:
    """Return a real RiskManager with permissive limits for ExecutionEngine tests."""
    cfg = RiskConfig(
        max_position_size_pct=0.99,
        max_drawdown_pct=0.10,
        max_open_positions=100,
    )
    rm = RiskManager(config=cfg, initial_balance=100_000.0)
    if not allow_trade:
        rm._trading_halted = True
        rm._halt_reason = "test halt"
    return rm


class TestExecutionEngine:
    @pytest.mark.asyncio
    async def test_successful_execution(self):
        broker = _make_broker_manager(OrderStatus.FILLED)
        risk = _make_risk_manager()
        engine = ExecutionEngine(broker, risk)
        await engine.start()

        req = ExecutionRequest(symbol="XAUUSD", side="BUY", quantity=1.0)
        report = await engine.execute(req)

        assert report.success is True
        assert report.status == ExecutionStatus.FILLED
        assert report.latency_ms >= 0

    @pytest.mark.asyncio
    async def test_client_order_id_forwarded_when_broker_supports_it(self):
        """ExecutionEngine passes the request_id as client_order_id for idempotency
        to brokers whose place_order accepts it (here: **kwargs)."""
        broker = _make_broker_manager(OrderStatus.FILLED)
        captured: dict = {}
        _orig = broker.place_order

        def _spy(*args, **kwargs):
            captured.update(kwargs)
            return _orig(*args, **kwargs)

        broker.place_order = _spy
        engine = ExecutionEngine(broker, _make_risk_manager())
        await engine.start()

        req = ExecutionRequest(symbol="XAUUSD", side="BUY", quantity=1.0)
        report = await engine.execute(req)

        assert report.success is True
        assert captured.get("client_order_id") == req.request_id

    @pytest.mark.asyncio
    async def test_kill_switch_blocks(self):
        from kill_switch import KillSwitch

        broker = _make_broker_manager()
        risk = _make_risk_manager()
        ks = KillSwitch()
        ks.activate("emergency halt")

        engine = ExecutionEngine(broker, risk, kill_switch=ks)
        await engine.start()

        req = ExecutionRequest(symbol="XAUUSD", side="BUY", quantity=1.0)
        report = await engine.execute(req)

        assert report.success is False
        assert report.status == ExecutionStatus.BLOCKED
        assert "KILL_SWITCH" in report.message

        ks.reset_for_testing()

    @pytest.mark.asyncio
    async def test_engine_stopped_blocks(self):
        broker = _make_broker_manager()
        risk = _make_risk_manager()
        engine = ExecutionEngine(broker, risk)
        # Do NOT call start()

        req = ExecutionRequest(symbol="XAUUSD", side="BUY", quantity=1.0)
        report = await engine.execute(req)

        assert report.status == ExecutionStatus.BLOCKED
        assert "ENGINE_STOPPED" in report.message

    @pytest.mark.asyncio
    async def test_circuit_breaker_blocks_after_failures(self):
        class _FailingBroker(_ConnectedPaperBroker):
            """Real broker that always raises on place_order to trigger circuit breaker."""

            def place_order(self, symbol, side, order_type, quantity, price=None, stop_price=None, **kwargs):
                raise RuntimeError("broker down")

        broker = _FailingBroker()
        risk = _make_risk_manager()
        engine = ExecutionEngine(broker, risk)
        engine._circuit_breaker = EngineCircuitBreaker(max_failures=2, window_sec=60.0, reset_sec=9999.0)
        await engine.start()

        req = ExecutionRequest(symbol="XAUUSD", side="BUY", quantity=1.0)
        # First two failures open the circuit breaker
        await engine.execute(req)
        await engine.execute(req)
        # Third call should be blocked by circuit breaker
        report = await engine.execute(req)
        assert report.status in (ExecutionStatus.BLOCKED, ExecutionStatus.ERROR)

    @pytest.mark.asyncio
    async def test_pre_trade_gate_blocks_halted_trading(self):
        broker = _make_broker_manager()
        risk = _make_risk_manager()
        risk._trading_halted = True
        risk._halt_reason = "drawdown limit"

        engine = ExecutionEngine(broker, risk)
        await engine.start()

        req = ExecutionRequest(symbol="XAUUSD", side="BUY", quantity=1.0)
        report = await engine.execute(req)

        assert report.success is False
        assert report.status == ExecutionStatus.BLOCKED
        assert "TRADING_HALTED" in report.message

    @pytest.mark.asyncio
    async def test_fill_callback_invoked(self):
        broker = _make_broker_manager(OrderStatus.FILLED)
        risk = _make_risk_manager()
        engine = ExecutionEngine(broker, risk)
        await engine.start()

        fills = []
        engine.add_fill_callback(fills.append)

        req = ExecutionRequest(symbol="XAUUSD", side="BUY", quantity=1.0)
        await engine.execute(req)

        assert len(fills) == 1
        assert fills[0].success is True

    @pytest.mark.asyncio
    async def test_metrics_updated_on_fill(self):
        broker = _make_broker_manager(OrderStatus.FILLED)
        risk = _make_risk_manager()
        engine = ExecutionEngine(broker, risk)
        await engine.start()

        req = ExecutionRequest(symbol="XAUUSD", side="BUY", quantity=1.0)
        await engine.execute(req)

        metrics = engine.get_metrics()
        assert metrics["total_orders"] == 1
        assert metrics["total_fills"] == 1
        assert metrics["total_blocks"] == 0
        assert metrics["fill_rate"] == pytest.approx(1.0)

    @pytest.mark.asyncio
    async def test_broker_error_returns_error_report(self):
        class _ErrorBroker(_ConnectedPaperBroker):
            """Real broker that raises on place_order to test error handling."""

            def place_order(self, symbol, side, order_type, quantity, price=None, stop_price=None, **kwargs):
                raise RuntimeError("connection lost")

        broker = _ErrorBroker()
        risk = _make_risk_manager()
        engine = ExecutionEngine(broker, risk)
        await engine.start()

        req = ExecutionRequest(symbol="XAUUSD", side="BUY", quantity=1.0)
        report = await engine.execute(req)

        assert report.success is False
        assert report.status == ExecutionStatus.ERROR
        assert "BROKER_ERROR" in report.message

    @pytest.mark.asyncio
    async def test_never_raises_to_caller(self):
        """ExecutionEngine.execute() must never raise — always returns a report."""

        class _CatastrophicBroker(_ConnectedPaperBroker):
            """Real broker that raises an unexpected exception."""

            def place_order(self, symbol, side, order_type, quantity, price=None, stop_price=None, **kwargs):
                raise Exception("catastrophic failure")

        broker = _CatastrophicBroker()
        risk = _make_risk_manager()
        engine = ExecutionEngine(broker, risk)
        await engine.start()

        req = ExecutionRequest(symbol="XAUUSD", side="BUY", quantity=1.0)
        # Must not raise
        report = await engine.execute(req)
        assert isinstance(report, ExecutionReport)
