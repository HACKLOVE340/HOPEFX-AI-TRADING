# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
tests/unit/test_execution_engine_deep.py
=========================================
Deep unit tests for execution/engine.py covering sub-steps that are NOT
exercised in tests/test_execution_engine.py:

- ``_enrich_price_from_data_layer()`` — safe-to-trade block, price injection
- ``_enrich_price_from_tick_feed()`` — tick available / missing / no mid
- ``update_last_tick()`` / ``get_last_tick()`` / ``get_tick_feed_status()``
- ``_check_sharpe_circuit_breaker()`` — open, closed, unavailable
- ``_try_algo_routing()`` — algo submit, small order pass-through, error
- ``_record_tca_signal_price()`` — success and recorder error
- ``_warn_on_latency_breach()`` — breach and no-breach paths
- ``_update_sharpe_circuit_breaker()`` — success, no model_version, error
- ``_make_algo_broker_fn()`` — returned callable round-trip
- ``_clone_request_with_price()`` — static method
- ``ExecutionReport.success`` property
"""

from __future__ import annotations

import time
from datetime import datetime, timezone

UTC = timezone.utc
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from execution.engine import (
    ExecutionEngine,
    ExecutionReport,
    ExecutionRequest,
    ExecutionStatus,
)


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────


def _make_engine(max_latency_ms: float = 50.0) -> ExecutionEngine:
    """Return a running ExecutionEngine backed by a mock broker+risk."""
    broker = MagicMock()
    risk = MagicMock()
    risk._trading_halted = False
    risk._kill_switch = None
    risk.validate_trade = MagicMock(return_value=(True, "OK"))
    risk.check_cvar_pre_trade = MagicMock(return_value=(True, "OK"))
    risk.current_balance = 100_000.0
    risk.initial_balance = 100_000.0
    risk.daily_pnl = 0.0
    risk.daily_starting_equity = 100_000.0
    risk.current_drawdown = 0.0
    risk.open_positions = []
    risk.config = MagicMock()
    risk.config.daily_loss_limit_pct = 0.05
    risk.config.max_drawdown_pct = 0.10
    risk.config.max_position_size_pct = 0.02
    risk.config.max_open_positions = 5
    risk._returns_history = [0.001] * 20

    engine = ExecutionEngine(broker, risk, max_latency_ms=max_latency_ms)
    engine._running = True
    return engine


def _buy_request(**kwargs) -> ExecutionRequest:
    defaults = dict(symbol="XAUUSD", side="BUY", quantity=1.0, order_type="MARKET")
    defaults.update(kwargs)
    return ExecutionRequest(**defaults)


def _make_tick(mid: float = 2000.0, source: str = "tick_feed") -> MagicMock:
    tick = MagicMock()
    tick.mid = mid
    tick.source = source
    tick.confidence = 1.0
    tick.timestamp = datetime.now(UTC)
    return tick


# ─────────────────────────────────────────────────────────────────────────────
# ExecutionReport.success
# ─────────────────────────────────────────────────────────────────────────────


class TestExecutionReportSuccess:
    def test_filled_is_success(self):
        r = ExecutionReport(request_id="x", status=ExecutionStatus.FILLED)
        assert r.success is True

    def test_submitted_is_success(self):
        r = ExecutionReport(request_id="x", status=ExecutionStatus.SUBMITTED)
        assert r.success is True

    def test_blocked_is_not_success(self):
        r = ExecutionReport(request_id="x", status=ExecutionStatus.BLOCKED)
        assert r.success is False

    def test_error_is_not_success(self):
        r = ExecutionReport(request_id="x", status=ExecutionStatus.ERROR)
        assert r.success is False


# ─────────────────────────────────────────────────────────────────────────────
# Tick feed management
# ─────────────────────────────────────────────────────────────────────────────


class TestTickFeed:
    def test_update_and_get_last_tick(self):
        eng = _make_engine()
        tick = _make_tick(mid=1980.0)
        eng.update_last_tick("XAUUSD", tick)
        assert eng.get_last_tick("XAUUSD") is tick

    def test_get_last_tick_unknown_symbol_returns_none(self):
        eng = _make_engine()
        assert eng.get_last_tick("EURUSD") is None

    def test_tick_feed_status_empty(self):
        eng = _make_engine()
        status = eng.get_tick_feed_status()
        assert status["tick_count"] == 0
        assert status["symbols_with_ticks"] == []
        assert status["last_ticks"] == {}

    def test_tick_feed_status_with_tick(self):
        eng = _make_engine()
        tick = _make_tick(mid=2010.0)
        eng.update_last_tick("XAUUSD", tick)
        status = eng.get_tick_feed_status()
        assert status["tick_count"] == 1
        assert "XAUUSD" in status["symbols_with_ticks"]
        assert "XAUUSD" in status["last_ticks"]
        assert abs(status["last_ticks"]["XAUUSD"]["mid"] - 2010.0) < 1e-3

    def test_update_overwrites_previous_tick(self):
        eng = _make_engine()
        eng.update_last_tick("XAUUSD", _make_tick(mid=1950.0))
        eng.update_last_tick("XAUUSD", _make_tick(mid=2050.0))
        assert eng.get_last_tick("XAUUSD").mid == 2050.0


# ─────────────────────────────────────────────────────────────────────────────
# _enrich_price_from_tick_feed
# ─────────────────────────────────────────────────────────────────────────────


class TestEnrichPriceFromTickFeed:
    def test_injects_mid_price_when_request_has_no_price(self):
        eng = _make_engine()
        tick = _make_tick(mid=2000.0)
        eng.update_last_tick("XAUUSD", tick)
        req = _buy_request(price=None)
        enriched = eng._enrich_price_from_tick_feed(req)
        assert enriched.price == 2000.0

    def test_does_not_overwrite_existing_price(self):
        eng = _make_engine()
        eng.update_last_tick("XAUUSD", _make_tick(mid=2000.0))
        req = _buy_request(price=1990.0)
        enriched = eng._enrich_price_from_tick_feed(req)
        assert enriched.price == 1990.0  # unchanged

    def test_returns_request_unchanged_when_no_tick(self):
        eng = _make_engine()
        req = _buy_request(price=None)
        enriched = eng._enrich_price_from_tick_feed(req)
        assert enriched.price is None

    def test_limit_order_not_enriched(self):
        eng = _make_engine()
        eng.update_last_tick("XAUUSD", _make_tick(mid=2000.0))
        req = _buy_request(order_type="LIMIT", price=1990.0)
        enriched = eng._enrich_price_from_tick_feed(req)
        assert enriched.price == 1990.0  # limit orders keep their price

    def test_tick_with_zero_mid_skipped(self):
        eng = _make_engine()
        tick = _make_tick(mid=0.0)
        eng.update_last_tick("XAUUSD", tick)
        req = _buy_request(price=None)
        enriched = eng._enrich_price_from_tick_feed(req)
        assert enriched.price is None

    def test_tick_without_mid_attr_skipped(self):
        eng = _make_engine()
        tick = MagicMock(spec=[])  # no attributes at all
        eng.update_last_tick("XAUUSD", tick)
        req = _buy_request(price=None)
        enriched = eng._enrich_price_from_tick_feed(req)
        assert enriched.price is None


# ─────────────────────────────────────────────────────────────────────────────
# _enrich_price_from_data_layer
# ─────────────────────────────────────────────────────────────────────────────


class TestEnrichPriceFromDataLayer:
    def test_skips_when_data_layer_unavailable(self):
        """Import error → non-fatal, returns original request."""
        eng = _make_engine()
        req = _buy_request()
        with patch.dict("sys.modules", {"data_layer.orchestrator": None}):
            result = eng._enrich_price_from_data_layer(req, time.monotonic())
        # Should return an ExecutionRequest (not a blocked report)
        assert isinstance(result, ExecutionRequest)

    def test_returns_blocked_report_when_not_safe_to_trade(self):
        eng = _make_engine()
        req = _buy_request()

        mock_orch = MagicMock()
        mock_orch._started = True
        mock_orch.is_safe_to_trade.return_value = False

        mock_module = MagicMock()
        mock_module.orchestrator = mock_orch

        with patch.dict("sys.modules", {"data_layer.orchestrator": mock_module}):
            result = eng._enrich_price_from_data_layer(req, time.monotonic())

        assert isinstance(result, ExecutionReport)
        assert result.status == ExecutionStatus.BLOCKED
        assert "DATA_LAYER" in result.message

    def test_injects_price_from_data_layer_when_no_price(self):
        eng = _make_engine()
        req = _buy_request(price=None)

        mock_orch = MagicMock()
        mock_orch._started = True
        mock_orch.is_safe_to_trade.return_value = True
        tick = _make_tick(mid=2005.0)
        mock_orch.get_latest_tick.return_value = tick

        mock_module = MagicMock()
        mock_module.orchestrator = mock_orch

        with patch.dict("sys.modules", {"data_layer.orchestrator": mock_module}):
            result = eng._enrich_price_from_data_layer(req, time.monotonic())

        assert isinstance(result, ExecutionRequest)
        assert result.price == 2005.0

    def test_does_not_overwrite_existing_price(self):
        eng = _make_engine()
        req = _buy_request(price=1995.0)

        mock_orch = MagicMock()
        mock_orch._started = True
        mock_orch.is_safe_to_trade.return_value = True
        mock_orch.get_latest_tick.return_value = _make_tick(mid=2005.0)

        mock_module = MagicMock()
        mock_module.orchestrator = mock_orch

        with patch.dict("sys.modules", {"data_layer.orchestrator": mock_module}):
            result = eng._enrich_price_from_data_layer(req, time.monotonic())

        assert result.price == 1995.0  # existing price preserved

    def test_orchestrator_not_started_skips_check(self):
        """When orchestrator._started is False, safety check is not run."""
        eng = _make_engine()
        req = _buy_request()

        mock_orch = MagicMock()
        mock_orch._started = False

        mock_module = MagicMock()
        mock_module.orchestrator = mock_orch

        with patch.dict("sys.modules", {"data_layer.orchestrator": mock_module}):
            result = eng._enrich_price_from_data_layer(req, time.monotonic())

        # Not started → should NOT call is_safe_to_trade
        mock_orch.is_safe_to_trade.assert_not_called()
        assert isinstance(result, ExecutionRequest)

    def test_skips_when_data_layer_raises_import_error(self):
        """ModuleNotFoundError (subclass of ImportError) is non-fatal."""
        eng = _make_engine()
        req = _buy_request()
        # Simulate a broken sub-import inside data_layer.orchestrator by
        # patching the module to None (triggers ModuleNotFoundError on import).
        with patch.dict("sys.modules", {"data_layer": None, "data_layer.orchestrator": None}):
            result = eng._enrich_price_from_data_layer(req, time.monotonic())
        assert isinstance(result, ExecutionRequest)

    def test_skips_when_orchestrator_raises_attribute_error(self):
        """AttributeError from a malformed orchestrator object is non-fatal."""
        eng = _make_engine()
        req = _buy_request()

        mock_module = MagicMock()
        # Accessing .orchestrator raises AttributeError
        type(mock_module).orchestrator = property(lambda self: (_ for _ in ()).throw(AttributeError("no attr")))

        with patch.dict("sys.modules", {"data_layer.orchestrator": mock_module}):
            result = eng._enrich_price_from_data_layer(req, time.monotonic())
        assert isinstance(result, ExecutionRequest)

    def test_skips_when_is_safe_to_trade_raises_value_error(self):
        """ValueError from is_safe_to_trade is non-fatal."""
        eng = _make_engine()
        req = _buy_request()

        mock_orch = MagicMock()
        mock_orch._started = True
        mock_orch.is_safe_to_trade.side_effect = ValueError("bad state")

        mock_module = MagicMock()
        mock_module.orchestrator = mock_orch

        with patch.dict("sys.modules", {"data_layer.orchestrator": mock_module}):
            result = eng._enrich_price_from_data_layer(req, time.monotonic())
        assert isinstance(result, ExecutionRequest)


# ─────────────────────────────────────────────────────────────────────────────
# _clone_request_with_price — static method
# ─────────────────────────────────────────────────────────────────────────────


class TestCloneRequestWithPrice:
    def test_creates_new_request_with_given_price(self):
        req = _buy_request(price=None, metadata={"strategy": "trend"})
        cloned = ExecutionEngine._clone_request_with_price(req, 2000.0, {"dl_mid": 2000.0})
        assert cloned.price == 2000.0
        assert cloned.metadata["strategy"] == "trend"
        assert cloned.metadata["dl_mid"] == 2000.0

    def test_original_request_unchanged(self):
        req = _buy_request(price=None)
        ExecutionEngine._clone_request_with_price(req, 2000.0, {})
        assert req.price is None

    def test_symbol_and_side_copied(self):
        req = _buy_request(symbol="EURUSD", side="SELL", quantity=2.0)
        cloned = ExecutionEngine._clone_request_with_price(req, 1.1, {})
        assert cloned.symbol == "EURUSD"
        assert cloned.side == "SELL"
        assert cloned.quantity == 2.0


# ─────────────────────────────────────────────────────────────────────────────
# _check_sharpe_circuit_breaker
# ─────────────────────────────────────────────────────────────────────────────


class TestSharpeCircuitBreaker:
    def test_no_model_version_returns_none(self):
        eng = _make_engine()
        req = _buy_request(strategy_id=None, metadata={})
        result = eng._check_sharpe_circuit_breaker(req, time.monotonic())
        assert result is None

    def test_open_circuit_returns_blocked_report(self):
        eng = _make_engine()
        req = _buy_request(metadata={"model_version": "advanced_oos_v1"})

        mock_cb = MagicMock()
        mock_cb.is_open.return_value = True

        mock_module = MagicMock()
        mock_module.get_sharpe_cb.return_value = mock_cb

        with patch.dict("sys.modules", {"ml.sharpe_circuit_breaker": mock_module}):
            result = eng._check_sharpe_circuit_breaker(req, time.monotonic())

        assert isinstance(result, ExecutionReport)
        assert result.status == ExecutionStatus.BLOCKED
        assert "SHARPE_CIRCUIT_OPEN" in result.message

    def test_closed_circuit_returns_none(self):
        eng = _make_engine()
        req = _buy_request(metadata={"model_version": "advanced_oos_v1"})

        mock_cb = MagicMock()
        mock_cb.is_open.return_value = False

        mock_module = MagicMock()
        mock_module.get_sharpe_cb.return_value = mock_cb

        with patch.dict("sys.modules", {"ml.sharpe_circuit_breaker": mock_module}):
            result = eng._check_sharpe_circuit_breaker(req, time.monotonic())

        assert result is None

    def test_cb_unavailable_returns_none(self):
        """Import error or exception → non-fatal, returns None."""
        eng = _make_engine()
        req = _buy_request(metadata={"model_version": "advanced_oos_v1"})

        with patch.dict("sys.modules", {"ml.sharpe_circuit_breaker": None}):
            result = eng._check_sharpe_circuit_breaker(req, time.monotonic())

        assert result is None

    def test_strategy_id_used_as_fallback_model_version(self):
        eng = _make_engine()
        req = _buy_request(strategy_id="my_strategy", metadata={})

        mock_cb = MagicMock()
        mock_cb.is_open.return_value = True

        mock_module = MagicMock()
        mock_module.get_sharpe_cb.return_value = mock_cb

        with patch.dict("sys.modules", {"ml.sharpe_circuit_breaker": mock_module}):
            result = eng._check_sharpe_circuit_breaker(req, time.monotonic())

        # is_open called with strategy_id
        mock_cb.is_open.assert_called_with("my_strategy")
        assert result is not None


# ─────────────────────────────────────────────────────────────────────────────
# _try_algo_routing
# ─────────────────────────────────────────────────────────────────────────────


class TestAlgoRouting:
    @pytest.mark.asyncio
    async def test_small_order_not_routed_returns_none(self):
        """submit_auto returns None for small orders."""
        eng = _make_engine()
        req = _buy_request(quantity=0.01)

        mock_algo = MagicMock()
        mock_algo._broker_submit = None
        mock_algo.set_broker_submit_fn = MagicMock()
        mock_algo.submit_auto = AsyncMock(return_value=None)

        mock_module = MagicMock()
        mock_module.get_algo_manager.return_value = mock_algo

        with patch.dict("sys.modules", {"execution.algo_orders": mock_module}):
            result = await eng._try_algo_routing(req, time.monotonic())

        assert result is None

    @pytest.mark.asyncio
    async def test_large_order_routed_returns_submitted_report(self):
        """submit_auto returns an algo_id for large orders."""
        eng = _make_engine()
        req = _buy_request(quantity=100.0)

        mock_algo = MagicMock()
        mock_algo._broker_submit = None
        mock_algo.set_broker_submit_fn = MagicMock()
        mock_algo.submit_auto = AsyncMock(return_value="algo-001")

        mock_module = MagicMock()
        mock_module.get_algo_manager.return_value = mock_algo

        with patch.dict("sys.modules", {"execution.algo_orders": mock_module}):
            result = await eng._try_algo_routing(req, time.monotonic())

        assert isinstance(result, ExecutionReport)
        assert result.status == ExecutionStatus.SUBMITTED
        assert "ALGO" in result.message
        assert result.metadata["algo_id"] == "algo-001"

    @pytest.mark.asyncio
    async def test_algo_import_error_returns_none(self):
        """Algo module unavailable → non-fatal, returns None."""
        eng = _make_engine()
        req = _buy_request(quantity=10.0)

        with patch.dict("sys.modules", {"execution.algo_orders": None}):
            result = await eng._try_algo_routing(req, time.monotonic())

        assert result is None

    @pytest.mark.asyncio
    async def test_algo_exception_returns_none(self):
        """submit_auto raising exception → non-fatal, returns None."""
        eng = _make_engine()
        req = _buy_request(quantity=10.0)

        mock_algo = MagicMock()
        mock_algo._broker_submit = None
        mock_algo.set_broker_submit_fn = MagicMock()
        mock_algo.submit_auto = AsyncMock(side_effect=RuntimeError("algo down"))

        mock_module = MagicMock()
        mock_module.get_algo_manager.return_value = mock_algo

        with patch.dict("sys.modules", {"execution.algo_orders": mock_module}):
            result = await eng._try_algo_routing(req, time.monotonic())

        assert result is None


# ─────────────────────────────────────────────────────────────────────────────
# _record_tca_signal_price
# ─────────────────────────────────────────────────────────────────────────────


class TestRecordTcaSignalPrice:
    def test_records_when_signal_price_in_metadata(self):
        eng = _make_engine()
        req = _buy_request(metadata={"signal_price": 2000.0, "model_version": "v1"})

        mock_recorder = MagicMock()
        mock_module = MagicMock()
        mock_module.get_tca_recorder.return_value = mock_recorder

        with patch.dict("sys.modules", {"execution.tca_recorder": mock_module}):
            eng._record_tca_signal_price(req)

        mock_recorder.record_signal.assert_called_once()

    def test_skips_when_no_signal_price(self):
        eng = _make_engine()
        req = _buy_request(price=None, metadata={})

        mock_recorder = MagicMock()
        mock_module = MagicMock()
        mock_module.get_tca_recorder.return_value = mock_recorder

        with patch.dict("sys.modules", {"execution.tca_recorder": mock_module}):
            eng._record_tca_signal_price(req)

        mock_recorder.record_signal.assert_not_called()

    def test_recorder_error_does_not_raise(self):
        eng = _make_engine()
        req = _buy_request(price=2000.0, metadata={"signal_price": 2000.0})

        mock_recorder = MagicMock()
        mock_recorder.record_signal.side_effect = RuntimeError("recorder down")
        mock_module = MagicMock()
        mock_module.get_tca_recorder.return_value = mock_recorder

        with patch.dict("sys.modules", {"execution.tca_recorder": mock_module}):
            eng._record_tca_signal_price(req)  # must not raise

    def test_recorder_import_error_does_not_raise(self):
        eng = _make_engine()
        req = _buy_request(price=2000.0, metadata={"signal_price": 2000.0})

        with patch.dict("sys.modules", {"execution.tca_recorder": None}):
            eng._record_tca_signal_price(req)  # must not raise


# ─────────────────────────────────────────────────────────────────────────────
# _warn_on_latency_breach
# ─────────────────────────────────────────────────────────────────────────────


class TestWarnOnLatencyBreach:
    def test_warning_logged_when_latency_exceeds_target(self, caplog):
        eng = _make_engine(max_latency_ms=10.0)
        req = _buy_request()
        report = ExecutionReport(
            request_id=req.request_id,
            status=ExecutionStatus.FILLED,
            latency_ms=100.0,
        )
        import logging

        with caplog.at_level(logging.WARNING, logger="execution.engine"):
            eng._warn_on_latency_breach(req, report)
        assert any("latency" in r.message.lower() for r in caplog.records)

    def test_no_warning_when_within_target(self, caplog):
        import logging

        eng = _make_engine(max_latency_ms=500.0)
        req = _buy_request()
        report = ExecutionReport(
            request_id=req.request_id,
            status=ExecutionStatus.FILLED,
            latency_ms=5.0,
        )
        caplog.clear()  # discard INFO init messages (contain "latency" in "max_latency=500ms")
        with caplog.at_level(logging.WARNING, logger="execution.engine"):
            eng._warn_on_latency_breach(req, report)
        assert not any("latency" in r.message.lower() for r in caplog.records)


# ─────────────────────────────────────────────────────────────────────────────
# _update_sharpe_circuit_breaker
# ─────────────────────────────────────────────────────────────────────────────


class TestUpdateSharpeCircuitBreaker:
    def test_records_pnl_when_model_version_present(self):
        eng = _make_engine()
        req = _buy_request(metadata={"model_version": "v1", "realised_pnl": 50.0})
        report = ExecutionReport(
            request_id=req.request_id,
            status=ExecutionStatus.FILLED,
            metadata={"realised_pnl": 50.0},
        )
        mock_cb = MagicMock()
        mock_module = MagicMock()
        mock_module.get_sharpe_cb.return_value = mock_cb

        with patch.dict("sys.modules", {"ml.sharpe_circuit_breaker": mock_module}):
            eng._update_sharpe_circuit_breaker(req, report)

        mock_cb.record_trade.assert_called_once_with(pnl=50.0, model_version="v1")

    def test_skips_when_no_model_version(self):
        eng = _make_engine()
        req = _buy_request(strategy_id=None, metadata={})
        report = ExecutionReport(request_id=req.request_id, status=ExecutionStatus.FILLED)

        mock_cb = MagicMock()
        mock_module = MagicMock()
        mock_module.get_sharpe_cb.return_value = mock_cb

        with patch.dict("sys.modules", {"ml.sharpe_circuit_breaker": mock_module}):
            eng._update_sharpe_circuit_breaker(req, report)

        mock_cb.record_trade.assert_not_called()

    def test_exception_does_not_raise(self):
        eng = _make_engine()
        req = _buy_request(metadata={"model_version": "v1"})
        report = ExecutionReport(request_id=req.request_id, status=ExecutionStatus.FILLED)

        mock_module = MagicMock()
        mock_module.get_sharpe_cb.side_effect = RuntimeError("cb down")

        with patch.dict("sys.modules", {"ml.sharpe_circuit_breaker": mock_module}):
            eng._update_sharpe_circuit_breaker(req, report)  # must not raise
