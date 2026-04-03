# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
Chaos and fault injection tests.

Verifies that safety-critical components behave correctly under adversarial
conditions: broker failures, kill-switch activation mid-flight, circuit-breaker
cascades, and dependency injection failures.

Test strategy:
  - Inject faults via unittest.mock to simulate broker timeouts, exceptions,
    and partial failures without touching real infrastructure.
  - Verify that every fault path results in a safe outcome:
      * No trade is placed when a safety gate fails
      * Kill switch activation blocks all subsequent orders immediately
      * Circuit breaker opens after the configured failure threshold
      * Post-fill side-effects (TCA, Redis, callbacks) never block order flow
  - All tests are deterministic and hermetic — no real network calls.
"""

import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("SECURITY_JWT_SECRET", "test-only-jwt-secret-key-minimum-32-chars!!")
# Ensure kill switch env var is NOT set for tests that need a clean state
os.environ.pop("HOPEFX_KILL_SWITCH", None)


# ---------------------------------------------------------------------------
# KillSwitch fault injection
# ---------------------------------------------------------------------------


class TestKillSwitchFaultInjection:
    """
    The KillSwitch must block all trading immediately upon activation and
    must not allow deactivation without the correct token.
    """

    @pytest.fixture()
    def kill_switch(self, tmp_path):
        """Fresh KillSwitch with a temp flag file and known deactivation token."""
        from kill_switch import KillSwitch

        return KillSwitch(
            flag_file=tmp_path / "kill_switch.flag",
            poll_interval_sec=999.0,  # disable background polling
            deactivation_token="test-token-abc123",
        )

    def test_inactive_by_default(self, kill_switch) -> None:
        assert kill_switch.is_active() is False
        assert kill_switch._reason == ""

    def test_activate_sets_active_and_reason(self, kill_switch) -> None:
        kill_switch.activate("broker timeout cascade")
        assert kill_switch.is_active() is True
        assert "broker timeout cascade" in kill_switch._reason

    def test_activate_idempotent(self, kill_switch) -> None:
        """Activating twice must not raise and must preserve the first reason."""
        kill_switch.activate("first reason")
        first_reason = kill_switch._reason
        kill_switch.activate("second reason")
        # First activation reason is preserved
        assert kill_switch._reason == first_reason

    def test_deactivate_wrong_token_raises(self, kill_switch) -> None:
        kill_switch.activate("test")
        with pytest.raises(PermissionError):
            kill_switch.deactivate(token="wrong-token")
        assert kill_switch.is_active() is True  # still active

    def test_deactivate_no_token_raises(self, kill_switch) -> None:
        kill_switch.activate("test")
        with pytest.raises(PermissionError):
            kill_switch.deactivate(token=None)
        assert kill_switch.is_active() is True

    def test_deactivate_correct_token_clears_state(self, kill_switch) -> None:
        kill_switch.activate("test")
        kill_switch.deactivate(token="test-token-abc123")
        assert kill_switch.is_active() is False
        assert kill_switch._reason == ""

    def test_flag_file_activates_on_construction(self, tmp_path) -> None:
        """A pre-existing flag file must activate the switch on construction."""
        from kill_switch import KillSwitch

        flag = tmp_path / "kill_switch.flag"
        flag.write_text("manual halt", encoding="utf-8")
        ks = KillSwitch(flag_file=flag, poll_interval_sec=999.0)
        assert ks.is_active() is True

    def test_env_var_activates_on_construction(self, tmp_path) -> None:
        """HOPEFX_KILL_SWITCH=1 must activate the switch on construction."""
        from kill_switch import KillSwitch

        with patch.dict(os.environ, {"HOPEFX_KILL_SWITCH": "1"}):
            ks = KillSwitch(flag_file=tmp_path / "ks.flag", poll_interval_sec=999.0)
        assert ks.is_active() is True

    def test_callback_fired_on_activation(self, kill_switch) -> None:
        """Registered callbacks must be called synchronously on activate()."""
        fired: list[str] = []
        kill_switch.register_callback(fired.append)
        kill_switch.activate("cascade failure")
        assert fired == ["cascade failure"]

    def test_multiple_callbacks_all_fired(self, kill_switch) -> None:
        fired: list[str] = []
        kill_switch.register_callback(lambda r: fired.append(f"cb1:{r}"))
        kill_switch.register_callback(lambda r: fired.append(f"cb2:{r}"))
        kill_switch.activate("test")
        assert len(fired) == 2
        assert all("test" in f for f in fired)

    def test_callback_exception_does_not_prevent_activation(self, kill_switch) -> None:
        """A failing callback must not prevent the kill switch from activating."""

        def bad_callback(reason):
            raise RuntimeError("callback exploded")

        kill_switch.register_callback(bad_callback)
        # Must not raise — kill switch activation is safety-critical
        kill_switch.activate("test")
        assert kill_switch.is_active() is True


# ---------------------------------------------------------------------------
# EngineCircuitBreaker fault injection
# ---------------------------------------------------------------------------


class TestCircuitBreakerFaultInjection:
    """
    The EngineCircuitBreaker must open after max_failures consecutive errors
    and must block all subsequent check() calls until reset_sec elapses.
    """

    @pytest.fixture()
    def cb(self):
        from execution.engine import EngineCircuitBreaker

        return EngineCircuitBreaker(max_failures=3, window_sec=60.0, reset_sec=3600.0)

    @pytest.mark.asyncio
    async def test_opens_after_max_failures(self, cb) -> None:
        for _ in range(cb._max_failures):
            await cb.record_failure()
        assert cb._open is True

    @pytest.mark.asyncio
    async def test_does_not_open_before_max_failures(self, cb) -> None:
        for _ in range(cb._max_failures - 1):
            await cb.record_failure()
        assert cb._open is False

    @pytest.mark.asyncio
    async def test_check_passes_when_closed(self, cb) -> None:
        await cb.check()  # must not raise

    @pytest.mark.asyncio
    async def test_check_raises_when_open(self, cb) -> None:
        for _ in range(cb._max_failures):
            await cb.record_failure()
        with pytest.raises(RuntimeError, match="circuit breaker is OPEN"):
            await cb.check()

    @pytest.mark.asyncio
    async def test_success_resets_failures(self, cb) -> None:
        for _ in range(cb._max_failures - 1):
            await cb.record_failure()
        await cb.record_success()
        assert cb._failures == []
        assert cb._open is False

    @pytest.mark.asyncio
    async def test_failures_outside_window_are_pruned(self, cb) -> None:
        """Failures older than window_sec must not count toward the threshold."""
        import time

        # Inject stale timestamps directly (older than window_sec)
        stale_time = time.monotonic() - cb._window_sec - 1.0
        cb._failures = [stale_time] * (cb._max_failures + 5)

        # One fresh failure — stale ones are pruned, so breaker stays closed
        await cb.record_failure()
        assert cb._open is False
        assert len(cb._failures) == 1  # only the fresh one remains

    @pytest.mark.asyncio
    async def test_auto_reset_after_reset_sec(self, cb) -> None:
        """After reset_sec elapses, check() must auto-reset and not raise."""
        import time

        for _ in range(cb._max_failures):
            await cb.record_failure()
        assert cb._open is True

        # Simulate reset_sec elapsed by backdating _opened_at
        cb._opened_at = time.monotonic() - cb._reset_sec - 1.0
        await cb.check()  # must not raise — auto-reset triggered
        assert cb._open is False


# ---------------------------------------------------------------------------
# ExecutionEngine fault injection (broker failures)
# ---------------------------------------------------------------------------


class TestExecutionEngineBrokerFaultInjection:
    """
    The ExecutionEngine must handle broker failures gracefully:
    - Broker timeout → ERROR report, circuit breaker records failure
    - Broker raises ValueError → ERROR report, no exception escapes
    - Pre-trade gate raises → blocked report, no order placed
    """

    def _make_engine(self):
        """Build a minimal ExecutionEngine with mocked dependencies."""
        from execution.engine import ExecutionEngine

        broker = AsyncMock()
        broker.place_order = AsyncMock(side_effect=TimeoutError("broker timeout"))
        broker.get_account_info = AsyncMock(return_value={"equity": 100_000.0})

        risk = MagicMock()
        engine = ExecutionEngine(
            broker_manager=broker,
            risk_manager=risk,
            kill_switch=None,
            max_latency_ms=500.0,
        )
        engine._running = True
        return engine, broker

    @pytest.mark.asyncio
    async def test_kill_switch_active_blocks_order(self) -> None:
        """An active kill switch must block the order before any broker call."""
        from execution.engine import ExecutionRequest, ExecutionStatus

        engine, broker = self._make_engine()
        ks = MagicMock()
        ks.is_active.return_value = True
        ks._reason = "emergency halt"
        engine._kill_switch = ks

        request = ExecutionRequest(symbol="XAUUSD", side="BUY", quantity=0.1, order_type="MARKET", strategy_id="test")
        report = await engine.execute(request)

        assert report.status == ExecutionStatus.BLOCKED
        assert "KILL_SWITCH" in report.message
        broker.place_order.assert_not_called()

    @pytest.mark.asyncio
    async def test_engine_stopped_blocks_order(self) -> None:
        """A stopped engine must block the order immediately."""
        from execution.engine import ExecutionRequest, ExecutionStatus

        engine, broker = self._make_engine()
        engine._running = False

        request = ExecutionRequest(symbol="XAUUSD", side="BUY", quantity=0.1, order_type="MARKET", strategy_id="test")
        report = await engine.execute(request)

        assert report.status == ExecutionStatus.BLOCKED
        assert "ENGINE_STOPPED" in report.message
        broker.place_order.assert_not_called()

    @pytest.mark.asyncio
    async def test_open_circuit_breaker_blocks_order(self) -> None:
        """An open circuit breaker must block the order before broker submission."""
        from execution.engine import ExecutionRequest, ExecutionStatus

        engine, broker = self._make_engine()
        # Force the circuit breaker open
        for _ in range(engine._circuit_breaker._max_failures):
            await engine._circuit_breaker.record_failure()

        request = ExecutionRequest(symbol="XAUUSD", side="BUY", quantity=0.1, order_type="MARKET", strategy_id="test")
        report = await engine.execute(request)

        assert report.status == ExecutionStatus.BLOCKED
        assert "CIRCUIT_BREAKER" in report.message
        broker.place_order.assert_not_called()

    @pytest.mark.asyncio
    async def test_post_fill_tca_failure_does_not_block_report(self) -> None:
        """
        A TCA recorder failure after a successful fill must not prevent the
        ExecutionReport from being returned — post-fill side-effects are
        best-effort.
        """
        from execution.engine import ExecutionRequest, ExecutionStatus

        engine, broker = self._make_engine()

        # Mock a successful broker submission
        mock_report = MagicMock()
        mock_report.success = True
        mock_report.latency_ms = 12.5
        mock_report.metadata = {"realised_pnl": 0.0}
        mock_report.request_id = "test-req-001"
        mock_report.status = ExecutionStatus.FILLED

        with (
            patch.object(engine, "_submit_to_broker", AsyncMock(return_value=mock_report)),
            patch.object(engine, "_run_pre_trade_gate", AsyncMock(return_value=None)),
            patch.object(engine, "_persist_to_redis", AsyncMock(side_effect=RuntimeError("redis down"))),
            patch.object(engine, "_record_tca", AsyncMock(side_effect=RuntimeError("tca down"))),
            patch.object(engine, "_notify_callbacks", AsyncMock(return_value=None)),
        ):
            request = ExecutionRequest(
                symbol="XAUUSD", side="BUY", quantity=0.1, order_type="MARKET", strategy_id="test"
            )
            # Must not raise even though Redis and TCA are down
            report = await engine.execute(request)

        # The fill report must still be returned
        assert report.success is True


# ---------------------------------------------------------------------------
# Signal engine gate fault injection
# ---------------------------------------------------------------------------


class TestSignalEngineGateFaultInjection:
    """
    _execute_if_approved() must fail safe when any dependency raises:
    - LiveTradingGate unavailable → trade blocked
    - Risk manager raises → trade blocked, error logged
    - Broker raises on place_order → error logged, no exception escapes
    """

    def _make_signal_payload(self, direction: str = "BUY") -> dict:
        return {
            "direction": direction,
            "entry_price": 2000.0,
            "stop_loss": 1985.0,
            "take_profit": 2030.0,
            "confidence": 0.75,
            "probability": 0.72,
        }

    def _make_app_state(self, broker=None, risk_manager=None):
        state = MagicMock()
        state.broker = broker or AsyncMock()
        state.risk_manager = risk_manager or MagicMock()
        state.ws_manager = None
        state.compliance_manager = None
        return state

    @pytest.mark.asyncio
    async def test_auto_trade_disabled_skips_all_gates(self) -> None:
        """When AUTO_TRADE is false, no gate should be checked."""
        from core.signal_engine import _execute_if_approved

        app_state = self._make_app_state()
        with patch("core.signal_engine._AUTO_TRADE", False):
            await _execute_if_approved(app_state, "XAUUSD", self._make_signal_payload())

        app_state.broker.place_market_order.assert_not_called()

    @pytest.mark.asyncio
    async def test_live_trading_gate_exception_blocks_trade(self) -> None:
        """LiveTradingGate raising must block the trade (fail-safe)."""
        from core.signal_engine import _execute_if_approved

        app_state = self._make_app_state()
        with (
            patch("core.signal_engine._AUTO_TRADE", True),
            patch("core.signal_engine._check_live_trading_gate", return_value=False),
        ):
            await _execute_if_approved(app_state, "XAUUSD", self._make_signal_payload())

        app_state.broker.place_market_order.assert_not_called()

    @pytest.mark.asyncio
    async def test_missing_risk_manager_blocks_trade(self) -> None:
        """No risk_manager on app_state must block the trade with an error log."""
        from core.signal_engine import _execute_if_approved

        app_state = self._make_app_state()
        app_state.risk_manager = None

        with (
            patch("core.signal_engine._AUTO_TRADE", True),
            patch("core.signal_engine._check_live_trading_gate", return_value=True),
        ):
            await _execute_if_approved(app_state, "XAUUSD", self._make_signal_payload())

        app_state.broker.place_market_order.assert_not_called()

    @pytest.mark.asyncio
    async def test_risk_assessment_exception_blocks_trade(self) -> None:
        """An exception in _assess_risk_and_size must block the trade."""
        from core.signal_engine import _execute_if_approved

        app_state = self._make_app_state()

        with (
            patch("core.signal_engine._AUTO_TRADE", True),
            patch("core.signal_engine._check_live_trading_gate", return_value=True),
            patch("core.signal_engine._assess_risk_and_size", AsyncMock(side_effect=RuntimeError("risk db down"))),
        ):
            await _execute_if_approved(app_state, "XAUUSD", self._make_signal_payload())

        app_state.broker.place_market_order.assert_not_called()

    @pytest.mark.asyncio
    async def test_broker_place_order_exception_does_not_propagate(self) -> None:
        """A broker exception on place_market_order must be caught and logged."""
        from core.signal_engine import _execute_if_approved

        broker = AsyncMock()
        broker.place_market_order = AsyncMock(side_effect=ConnectionError("broker unreachable"))
        app_state = self._make_app_state(broker=broker)

        with (
            patch("core.signal_engine._AUTO_TRADE", True),
            patch("core.signal_engine._check_live_trading_gate", return_value=True),
            patch("core.signal_engine._assess_risk_and_size", AsyncMock(return_value=0.5)),
        ):
            # Must not raise — broker errors are caught inside _execute_if_approved
            await _execute_if_approved(app_state, "XAUUSD", self._make_signal_payload())

    @pytest.mark.asyncio
    async def test_invalid_direction_blocks_trade(self) -> None:
        """An unrecognised direction must block the trade before any gate."""
        from core.signal_engine import _execute_if_approved

        app_state = self._make_app_state()
        payload = self._make_signal_payload()
        payload["direction"] = "HOLD"  # invalid

        with (
            patch("core.signal_engine._AUTO_TRADE", True),
            patch("core.signal_engine._check_live_trading_gate", return_value=True),
        ):
            await _execute_if_approved(app_state, "XAUUSD", payload)

        app_state.broker.place_market_order.assert_not_called()


# ---------------------------------------------------------------------------
# Startup factory fault injection
# ---------------------------------------------------------------------------


class TestStartupFactoryFaultInjection:
    """
    Startup factories must degrade gracefully when optional dependencies
    are unavailable — a missing ML phase must never crash the application.
    """

    @pytest.mark.asyncio
    async def test_anomaly_store_import_failure_returns_none(self) -> None:
        """AnomalyWeightStore import failure must return None, not raise."""
        from core.startup_factories import init_anomaly_store

        state = MagicMock()
        with (
            patch("core.startup_factories._is_feature_enabled", return_value=True),
            patch.dict("sys.modules", {"research.pipeline.anomaly": None}),
        ):
            result = await init_anomaly_store(state)
        assert result is None

    @pytest.mark.asyncio
    async def test_online_learner_store_import_failure_returns_none(self) -> None:
        """OnlineLearnerStore import failure must return None, not raise."""
        from core.startup_factories import init_online_learner_store

        state = MagicMock()
        with (
            patch("core.startup_factories._is_feature_enabled", return_value=True),
            patch.dict("sys.modules", {"research.pipeline.online_learning": None}),
        ):
            result = await init_online_learner_store(state)
        assert result is None

    @pytest.mark.asyncio
    async def test_deep_ensemble_store_import_failure_returns_none(self) -> None:
        """DeepEnsembleStore import failure must return None, not raise."""
        from core.startup_factories import init_deep_ensemble_store

        state = MagicMock()
        with (
            patch("core.startup_factories._is_feature_enabled", return_value=True),
            patch.dict("sys.modules", {"research.pipeline.models_ensemble": None}),
        ):
            result = await init_deep_ensemble_store(state)
        assert result is None

    def test_is_feature_enabled_returns_false_on_import_error(self) -> None:
        """_is_feature_enabled must return False when flags module is unavailable."""
        from core.startup_factories import _is_feature_enabled

        with patch.dict("sys.modules", {"config.feature_flags": None}):
            result = _is_feature_enabled("SOME_FLAG", default=False)
        assert result is False

    def test_resolve_clock_start_time_returns_now_when_no_file(self, tmp_path) -> None:
        """_resolve_clock_start_time must return a datetime when no stamp file exists."""
        from core.startup_factories import _resolve_clock_start_time
        from datetime import datetime

        with patch("core.startup_factories._OANDA_PAPER_STAMP_PATH", tmp_path / "nonexistent.json"):
            result = _resolve_clock_start_time()

        assert result is not None
        assert isinstance(result, datetime)

    def test_resolve_clock_start_time_returns_none_for_real_account(self, tmp_path) -> None:
        """_resolve_clock_start_time must return None when a real account is stamped."""
        import json
        from core.startup_factories import _resolve_clock_start_time

        stamp = tmp_path / "stamp.json"
        stamp.write_text(
            json.dumps(
                {
                    "started_utc": "2025-01-01T00:00:00+00:00",
                    "requires_real_account": False,
                    "account_id": "ABC12345…",
                }
            ),
            encoding="utf-8",
        )

        with patch("core.startup_factories._OANDA_PAPER_STAMP_PATH", stamp):
            result = _resolve_clock_start_time()

        assert result is None  # real account already stamped — do not overwrite
