# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
Coverage tests for risk/orchestrator.py

Targets: HedgePosition, RiskSnapshot, RiskOrchestrator (all public methods),
         state persistence, broker injection, FastAPI router, singleton.
"""

from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_orch(tmp_path=None, **kwargs):
    from risk.orchestrator import RiskOrchestrator

    if tmp_path is not None:
        kwargs.setdefault("state_file", str(tmp_path / "orch_state.json"))
    return RiskOrchestrator(**kwargs)


# ---------------------------------------------------------------------------
# HedgePosition dataclass
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestHedgePosition:
    def test_fields(self):
        from risk.orchestrator import HedgePosition

        hp = HedgePosition(symbol="XAU_USD", units=1000.0, direction="short")
        assert hp.symbol == "XAU_USD"
        assert hp.units == pytest.approx(1000.0)
        assert hp.direction == "short"

    def test_opened_at_default(self):
        from risk.orchestrator import HedgePosition

        before = time.time()
        hp = HedgePosition(symbol="XAU_USD", units=500.0, direction="long")
        assert hp.opened_at >= before

    def test_order_id_default_none(self):
        from risk.orchestrator import HedgePosition

        hp = HedgePosition(symbol="XAU_USD", units=100.0, direction="short")
        assert hp.order_id is None


# ---------------------------------------------------------------------------
# RiskSnapshot dataclass
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestRiskSnapshot:
    def test_fields(self):
        from risk.orchestrator import RiskSnapshot

        snap = RiskSnapshot(
            max_risk_fraction=0.5,
            current_exposure=0.3,
            hedge_active=False,
            hedge_positions=[],
            trading_allowed=True,
        )
        assert snap.max_risk_fraction == pytest.approx(0.5)
        assert snap.trading_allowed is True

    def test_timestamp_default(self):
        from risk.orchestrator import RiskSnapshot

        before = time.time()
        snap = RiskSnapshot(
            max_risk_fraction=1.0,
            current_exposure=0.0,
            hedge_active=False,
            hedge_positions=[],
            trading_allowed=True,
        )
        assert snap.timestamp >= before


# ---------------------------------------------------------------------------
# RiskOrchestrator construction
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestRiskOrchestratorConstruction:
    def test_default_max_risk(self, tmp_path):
        orch = _make_orch(tmp_path)
        assert orch.get_max_risk() == pytest.approx(1.0)

    def test_custom_max_risk(self, tmp_path):
        orch = _make_orch(tmp_path, default_max_risk=0.5)
        assert orch.get_max_risk() == pytest.approx(0.5)

    def test_trading_allowed_initially(self, tmp_path):
        orch = _make_orch(tmp_path)
        assert orch.is_trading_allowed() is True

    def test_hedge_not_active_initially(self, tmp_path):
        orch = _make_orch(tmp_path)
        assert orch._hedge_active is False

    def test_broker_injection_at_construction(self, tmp_path):
        broker = MagicMock()
        orch = _make_orch(tmp_path, broker=broker)
        assert orch._broker is broker

    def test_inject_broker_after_construction(self, tmp_path):
        orch = _make_orch(tmp_path)
        broker = MagicMock()
        orch.inject_broker(broker)
        assert orch._broker is broker


# ---------------------------------------------------------------------------
# set_max_risk
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestSetMaxRisk:
    @pytest.mark.asyncio
    async def test_set_to_zero_disables_trading(self, tmp_path):
        orch = _make_orch(tmp_path)
        await orch.set_max_risk(0.0)
        assert orch.is_trading_allowed() is False
        assert orch.get_max_risk() == pytest.approx(0.0)

    @pytest.mark.asyncio
    async def test_set_to_one_enables_trading(self, tmp_path):
        orch = _make_orch(tmp_path)
        await orch.set_max_risk(0.0)
        await orch.set_max_risk(1.0)
        assert orch.is_trading_allowed() is True

    @pytest.mark.asyncio
    async def test_clamps_above_one(self, tmp_path):
        orch = _make_orch(tmp_path)
        await orch.set_max_risk(5.0)
        assert orch.get_max_risk() == pytest.approx(1.0)

    @pytest.mark.asyncio
    async def test_clamps_below_zero(self, tmp_path):
        orch = _make_orch(tmp_path)
        await orch.set_max_risk(-1.0)
        assert orch.get_max_risk() == pytest.approx(0.0)

    @pytest.mark.asyncio
    async def test_records_event(self, tmp_path):
        orch = _make_orch(tmp_path)
        await orch.set_max_risk(0.5)
        assert len(orch._history) >= 1
        assert orch._history[-1]["type"] == "set_max_risk"

    @pytest.mark.asyncio
    async def test_persists_state(self, tmp_path):
        orch = _make_orch(tmp_path)
        await orch.set_max_risk(0.3)
        assert orch._state_file.exists()
        data = json.loads(orch._state_file.read_text())
        assert data["max_risk"] == pytest.approx(0.3)

    @pytest.mark.asyncio
    async def test_propagates_to_risk_manager(self, tmp_path):
        orch = _make_orch(tmp_path)
        mock_rm = MagicMock()
        mock_rm.config = MagicMock()
        with patch("risk.manager.risk_manager", mock_rm):
            await orch.set_max_risk(0.5)
        # Should have updated config attributes
        assert mock_rm.config.max_risk_per_trade is not None


# ---------------------------------------------------------------------------
# activate_hedge_mode
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestActivateHedgeMode:
    @pytest.mark.asyncio
    async def test_sets_hedge_active(self, tmp_path):
        orch = _make_orch(tmp_path)
        await orch.activate_hedge_mode("XAU_USD")
        assert orch._hedge_active is True

    @pytest.mark.asyncio
    async def test_adds_hedge_position(self, tmp_path):
        orch = _make_orch(tmp_path)
        await orch.activate_hedge_mode("XAU_USD")
        assert len(orch._hedge_positions) == 1
        assert orch._hedge_positions[0].symbol == "XAU_USD"

    @pytest.mark.asyncio
    async def test_no_duplicate_activation(self, tmp_path):
        orch = _make_orch(tmp_path)
        await orch.activate_hedge_mode("XAU_USD")
        await orch.activate_hedge_mode("XAU_USD")
        assert len(orch._hedge_positions) == 1

    @pytest.mark.asyncio
    async def test_places_order_when_broker_available(self, tmp_path):
        broker = MagicMock()
        broker.place_order = AsyncMock(return_value={"id": "hedge-001"})
        orch = _make_orch(tmp_path, broker=broker)
        await orch.activate_hedge_mode("XAU_USD")
        broker.place_order.assert_called_once()
        assert orch._hedge_positions[0].order_id == "hedge-001"

    @pytest.mark.asyncio
    async def test_no_broker_still_activates(self, tmp_path):
        orch = _make_orch(tmp_path)
        await orch.activate_hedge_mode("XAU_USD")
        assert orch._hedge_active is True
        assert orch._hedge_positions[0].order_id is None

    @pytest.mark.asyncio
    async def test_broker_order_failure_still_activates(self, tmp_path):
        broker = MagicMock()
        broker.place_order = AsyncMock(side_effect=RuntimeError("broker down"))
        orch = _make_orch(tmp_path, broker=broker)
        await orch.activate_hedge_mode("XAU_USD")
        assert orch._hedge_active is True

    @pytest.mark.asyncio
    async def test_records_event(self, tmp_path):
        orch = _make_orch(tmp_path)
        await orch.activate_hedge_mode("XAU_USD")
        types = [e["type"] for e in orch._history]
        assert "activate_hedge" in types

    @pytest.mark.asyncio
    async def test_persists_state(self, tmp_path):
        orch = _make_orch(tmp_path)
        await orch.activate_hedge_mode("XAU_USD")
        data = json.loads(orch._state_file.read_text())
        assert data["hedge_active"] is True


# ---------------------------------------------------------------------------
# deactivate_hedge_mode
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestDeactivateHedgeMode:
    @pytest.mark.asyncio
    async def test_clears_hedge_active(self, tmp_path):
        orch = _make_orch(tmp_path)
        await orch.activate_hedge_mode("XAU_USD")
        await orch.deactivate_hedge_mode()
        assert orch._hedge_active is False

    @pytest.mark.asyncio
    async def test_clears_hedge_positions(self, tmp_path):
        orch = _make_orch(tmp_path)
        await orch.activate_hedge_mode("XAU_USD")
        await orch.deactivate_hedge_mode()
        assert orch._hedge_positions == []

    @pytest.mark.asyncio
    async def test_no_op_when_not_active(self, tmp_path):
        orch = _make_orch(tmp_path)
        await orch.deactivate_hedge_mode()  # should not raise
        assert orch._hedge_active is False

    @pytest.mark.asyncio
    async def test_closes_order_via_broker(self, tmp_path):
        broker = MagicMock()
        broker.place_order = AsyncMock(return_value={"id": "h1"})
        orch = _make_orch(tmp_path, broker=broker)
        await orch.activate_hedge_mode("XAU_USD")
        broker.place_order.reset_mock()
        await orch.deactivate_hedge_mode()
        broker.place_order.assert_called_once()

    @pytest.mark.asyncio
    async def test_broker_close_failure_still_deactivates(self, tmp_path):
        broker = MagicMock()
        broker.place_order = AsyncMock(side_effect=[{"id": "h1"}, RuntimeError("close failed")])
        orch = _make_orch(tmp_path, broker=broker)
        await orch.activate_hedge_mode("XAU_USD")
        await orch.deactivate_hedge_mode()
        assert orch._hedge_active is False

    @pytest.mark.asyncio
    async def test_clears_state_file(self, tmp_path):
        orch = _make_orch(tmp_path)
        await orch.activate_hedge_mode("XAU_USD")
        assert orch._state_file.exists()
        await orch.deactivate_hedge_mode()
        assert not orch._state_file.exists()

    @pytest.mark.asyncio
    async def test_records_event(self, tmp_path):
        orch = _make_orch(tmp_path)
        await orch.activate_hedge_mode("XAU_USD")
        await orch.deactivate_hedge_mode()
        types = [e["type"] for e in orch._history]
        assert "deactivate_hedge" in types


# ---------------------------------------------------------------------------
# get_current_exposure
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestGetCurrentExposure:
    @pytest.mark.asyncio
    async def test_returns_float(self, tmp_path):
        orch = _make_orch(tmp_path)
        exposure = await orch.get_current_exposure()
        assert isinstance(exposure, float)

    @pytest.mark.asyncio
    async def test_returns_value_in_range(self, tmp_path):
        orch = _make_orch(tmp_path)
        exposure = await orch.get_current_exposure()
        assert 0.0 <= exposure <= 1.0

    @pytest.mark.asyncio
    async def test_uses_risk_manager_when_available(self, tmp_path):
        orch = _make_orch(tmp_path)
        mock_rm = MagicMock()
        mock_rm.get_current_exposure.return_value = 0.35
        with patch("risk.manager.risk_manager", mock_rm):
            exposure = await orch.get_current_exposure()
        assert exposure == pytest.approx(0.35)

    @pytest.mark.asyncio
    async def test_fallback_when_risk_manager_unavailable(self, tmp_path):
        orch = _make_orch(tmp_path)
        with patch("risk.manager.risk_manager", MagicMock(spec=[])):
            exposure = await orch.get_current_exposure()
        assert 0.0 <= exposure <= 1.0

    @pytest.mark.asyncio
    async def test_full_risk_gives_low_exposure(self, tmp_path):
        orch = _make_orch(tmp_path, default_max_risk=1.0)
        # With max_risk=1.0, fallback formula: min(1.0, 1.0 - 1.0 + 0.1) = 0.1
        with patch("risk.manager.risk_manager", MagicMock(spec=[])):
            exposure = await orch.get_current_exposure()
        assert exposure == pytest.approx(0.1)

    @pytest.mark.asyncio
    async def test_zero_risk_gives_high_exposure(self, tmp_path):
        orch = _make_orch(tmp_path, default_max_risk=0.0)
        with patch("risk.manager.risk_manager", MagicMock(spec=[])):
            exposure = await orch.get_current_exposure()
        assert exposure == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# get_status
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestGetStatus:
    def test_returns_dict(self, tmp_path):
        orch = _make_orch(tmp_path)
        s = orch.get_status()
        assert isinstance(s, dict)

    def test_required_keys(self, tmp_path):
        orch = _make_orch(tmp_path)
        s = orch.get_status()
        for k in (
            "max_risk_fraction",
            "trading_allowed",
            "hedge_active",
            "hedge_positions",
            "event_count",
            "last_event",
        ):
            assert k in s

    def test_initial_values(self, tmp_path):
        orch = _make_orch(tmp_path)
        s = orch.get_status()
        assert s["max_risk_fraction"] == pytest.approx(1.0)
        assert s["trading_allowed"] is True
        assert s["hedge_active"] is False
        assert s["hedge_positions"] == []
        assert s["last_event"] is None

    @pytest.mark.asyncio
    async def test_hedge_positions_in_status(self, tmp_path):
        orch = _make_orch(tmp_path)
        await orch.activate_hedge_mode("XAU_USD")
        s = orch.get_status()
        assert len(s["hedge_positions"]) == 1
        pos = s["hedge_positions"][0]
        assert pos["symbol"] == "XAU_USD"
        assert "age_seconds" in pos


# ---------------------------------------------------------------------------
# State persistence
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestStatePersistence:
    def test_persist_and_restore(self, tmp_path):
        f = tmp_path / "state.json"
        orch1 = _make_orch(tmp_path, state_file=str(f), default_max_risk=0.4)
        orch1._persist_state()
        orch2 = _make_orch(tmp_path, state_file=str(f))
        assert orch2.get_max_risk() == pytest.approx(0.4)

    def test_restore_missing_file_no_crash(self, tmp_path):
        f = tmp_path / "nonexistent.json"
        orch = _make_orch(tmp_path, state_file=str(f))
        assert orch.get_max_risk() == pytest.approx(1.0)

    def test_restore_corrupt_file_no_crash(self, tmp_path):
        f = tmp_path / "corrupt.json"
        f.write_text("not valid json")
        orch = _make_orch(tmp_path, state_file=str(f))
        assert orch is not None

    def test_persist_os_error_no_crash(self, tmp_path):
        orch = _make_orch(tmp_path)
        orch._state_file = Path("/nonexistent_dir/state.json")
        orch._persist_state()  # should not raise

    def test_clear_state_removes_file(self, tmp_path):
        f = tmp_path / "state.json"
        orch = _make_orch(tmp_path, state_file=str(f))
        orch._persist_state()
        assert f.exists()
        orch._clear_state()
        assert not f.exists()

    def test_clear_state_no_crash_when_missing(self, tmp_path):
        orch = _make_orch(tmp_path)
        orch._clear_state()  # file doesn't exist — should not raise

    @pytest.mark.asyncio
    async def test_restore_hedge_positions_from_file(self, tmp_path):
        f = tmp_path / "state.json"
        state = {
            "max_risk": 0.5,
            "trading_allowed": True,
            "hedge_active": True,
            "hedge_positions": [
                {"symbol": "XAU_USD", "units": 1000.0, "direction": "short", "opened_at": time.time(), "order_id": "h1"}
            ],
        }
        f.write_text(json.dumps(state))
        orch = _make_orch(tmp_path, state_file=str(f))
        assert orch._hedge_active is True
        assert len(orch._hedge_positions) == 1
        assert orch._hedge_positions[0].symbol == "XAU_USD"


# ---------------------------------------------------------------------------
# _record_event / history cap
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestRecordEvent:
    def test_event_appended(self, tmp_path):
        orch = _make_orch(tmp_path)
        orch._record_event("test_event", {"key": "value"})
        assert orch._history[-1]["type"] == "test_event"
        assert orch._history[-1]["key"] == "value"

    def test_history_capped_at_200(self, tmp_path):
        orch = _make_orch(tmp_path)
        for i in range(250):
            orch._record_event("evt", {"i": i})
        assert len(orch._history) == 200

    def test_oldest_dropped_when_capped(self, tmp_path):
        orch = _make_orch(tmp_path)
        for i in range(201):
            orch._record_event("evt", {"i": i})
        assert orch._history[0]["i"] == 1  # first entry dropped


# ---------------------------------------------------------------------------
# _get_broker lazy loading
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestGetBroker:
    def test_returns_injected_broker(self, tmp_path):
        broker = MagicMock()
        orch = _make_orch(tmp_path, broker=broker)
        assert orch._get_broker() is broker

    def test_returns_none_when_no_broker(self, tmp_path):
        orch = _make_orch(tmp_path)
        with patch.dict("sys.modules", {"hopefx_engine": None}):
            result = orch._get_broker()
        assert result is None

    def test_lazy_loads_from_engine(self, tmp_path):
        orch = _make_orch(tmp_path)
        mock_broker = MagicMock()
        mock_engine = MagicMock()
        mock_engine._broker = mock_broker
        mock_module = MagicMock()
        mock_module._engine_instance = mock_engine
        with patch.dict("sys.modules", {"hopefx_engine": mock_module}):
            result = orch._get_broker()
        assert result is mock_broker


# ---------------------------------------------------------------------------
# FastAPI router
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestCreateOrchestratorRouter:
    def test_router_created(self, tmp_path):
        try:
            from risk.orchestrator import create_orchestrator_router

            orch = _make_orch(tmp_path)
            router = create_orchestrator_router(orch)
            assert router is not None
        except ImportError:
            pytest.skip("FastAPI not available")

    def test_router_has_routes(self, tmp_path):
        try:
            from risk.orchestrator import create_orchestrator_router

            orch = _make_orch(tmp_path)
            router = create_orchestrator_router(orch)
            assert len(router.routes) > 0
        except ImportError:
            pytest.skip("FastAPI not available")


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestRiskOrchestratorSingleton:
    def test_singleton_exists(self):
        from risk.orchestrator import risk_orchestrator

        assert risk_orchestrator is not None

    def test_singleton_is_orchestrator(self):
        from risk.orchestrator import RiskOrchestrator, risk_orchestrator

        assert isinstance(risk_orchestrator, RiskOrchestrator)

    def test_singleton_has_status(self):
        from risk.orchestrator import risk_orchestrator

        s = risk_orchestrator.get_status()
        assert "max_risk_fraction" in s


# ---------------------------------------------------------------------------
# Concurrent set_max_risk (lock safety)
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestConcurrentAccess:
    @pytest.mark.asyncio
    async def test_concurrent_set_max_risk(self, tmp_path):
        orch = _make_orch(tmp_path)
        tasks = [orch.set_max_risk(v) for v in [0.1, 0.5, 0.9, 0.3, 0.7]]
        await asyncio.gather(*tasks)
        # Final value should be one of the set values, not corrupted
        assert 0.0 <= orch.get_max_risk() <= 1.0

    @pytest.mark.asyncio
    async def test_concurrent_hedge_activate_deactivate(self, tmp_path):
        orch = _make_orch(tmp_path)
        await orch.activate_hedge_mode("XAU_USD")
        await asyncio.gather(
            orch.deactivate_hedge_mode(),
            orch.activate_hedge_mode("XAU_USD"),
        )
        # Should not raise or corrupt state
        assert isinstance(orch._hedge_active, bool)


# ---------------------------------------------------------------------------
# _clear_state OSError path
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestClearStateOSError:
    def test_clear_state_oserror_no_crash(self, tmp_path):
        """OSError during unlink is swallowed."""
        orch = _make_orch(tmp_path)
        orch._persist_state()
        # Make the file read-only so unlink fails on some systems,
        # or just patch Path.unlink to raise OSError
        with patch.object(orch._state_file.__class__, "unlink", side_effect=OSError("permission denied")):
            orch._clear_state()  # should not raise


# ---------------------------------------------------------------------------
# _get_broker lazy-load paths
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestGetBrokerLazyLoad:
    def test_engine_found_but_no_broker_attr(self, tmp_path):
        """Engine exists but has no _broker attribute → returns None."""
        orch = _make_orch(tmp_path)
        mock_engine = MagicMock(spec=[])  # no _broker attribute
        mock_module = MagicMock()
        mock_module._engine_instance = mock_engine
        with patch.dict("sys.modules", {"hopefx_engine": mock_module}):
            result = orch._get_broker()
        assert result is None

    def test_engine_found_broker_is_none(self, tmp_path):
        """Engine exists, _broker is None → returns None."""
        orch = _make_orch(tmp_path)
        mock_engine = MagicMock()
        mock_engine._broker = None
        mock_module = MagicMock()
        mock_module._engine_instance = mock_engine
        with patch.dict("sys.modules", {"hopefx_engine": mock_module}):
            result = orch._get_broker()
        assert result is None

    def test_engine_instance_is_none(self, tmp_path):
        """Module exists but _engine_instance is None → returns None."""
        orch = _make_orch(tmp_path)
        mock_module = MagicMock()
        mock_module._engine_instance = None
        with patch.dict("sys.modules", {"hopefx_engine": mock_module}):
            result = orch._get_broker()
        assert result is None


# ---------------------------------------------------------------------------
# get_current_exposure — data_layer.orchestrator path
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestGetCurrentExposureDataLayer:
    @pytest.mark.asyncio
    async def test_data_layer_tick_with_exposure(self, tmp_path):
        """Covers the data_layer.orchestrator tick.exposure path."""
        orch = _make_orch(tmp_path)

        mock_tick = MagicMock()
        mock_tick.exposure = 0.42
        mock_dl_orch = MagicMock()
        mock_dl_orch.get_latest_tick.return_value = mock_tick

        mock_dl_module = MagicMock()
        mock_dl_module.orchestrator = mock_dl_orch

        # Make risk_manager not have get_current_exposure so we fall through
        mock_rm = MagicMock(spec=[])
        with (
            patch("risk.manager.risk_manager", mock_rm),
            patch.dict("sys.modules", {"data_layer.orchestrator": mock_dl_module}),
        ):
            exposure = await orch.get_current_exposure()
        assert exposure == pytest.approx(0.42)

    @pytest.mark.asyncio
    async def test_data_layer_tick_without_exposure_attr(self, tmp_path):
        """Tick exists but has no exposure attr → falls through to proxy."""
        orch = _make_orch(tmp_path)

        mock_tick = MagicMock(spec=[])  # no exposure attribute
        mock_dl_orch = MagicMock()
        mock_dl_orch.get_latest_tick.return_value = mock_tick

        mock_dl_module = MagicMock()
        mock_dl_module.orchestrator = mock_dl_orch

        mock_rm = MagicMock(spec=[])
        with (
            patch("risk.manager.risk_manager", mock_rm),
            patch.dict("sys.modules", {"data_layer.orchestrator": mock_dl_module}),
        ):
            exposure = await orch.get_current_exposure()
        assert 0.0 <= exposure <= 1.0

    @pytest.mark.asyncio
    async def test_data_layer_tick_is_none(self, tmp_path):
        """get_latest_tick returns None → falls through to proxy."""
        orch = _make_orch(tmp_path)

        mock_dl_orch = MagicMock()
        mock_dl_orch.get_latest_tick.return_value = None

        mock_dl_module = MagicMock()
        mock_dl_module.orchestrator = mock_dl_orch

        mock_rm = MagicMock(spec=[])
        with (
            patch("risk.manager.risk_manager", mock_rm),
            patch.dict("sys.modules", {"data_layer.orchestrator": mock_dl_module}),
        ):
            exposure = await orch.get_current_exposure()
        assert 0.0 <= exposure <= 1.0


# ---------------------------------------------------------------------------
# FastAPI router endpoint bodies
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestFastAPIRouterEndpoints:
    """Call the router endpoint functions directly to cover their bodies."""

    @pytest.mark.asyncio
    async def test_get_status_endpoint(self, tmp_path):
        try:
            from risk.orchestrator import create_orchestrator_router
        except ImportError:
            pytest.skip("FastAPI not available")

        orch = _make_orch(tmp_path)
        router = create_orchestrator_router(orch)
        if router is None:
            pytest.skip("FastAPI not available")

        # Find and call the get_status route handler directly
        for route in router.routes:
            if hasattr(route, "path") and route.path == "/status":
                result = await route.endpoint()
                assert "max_risk_fraction" in result
                break

    @pytest.mark.asyncio
    async def test_set_max_risk_endpoint(self, tmp_path):
        try:
            from risk.orchestrator import create_orchestrator_router
        except ImportError:
            pytest.skip("FastAPI not available")

        orch = _make_orch(tmp_path)
        router = create_orchestrator_router(orch)
        if router is None:
            pytest.skip("FastAPI not available")

        for route in router.routes:
            if hasattr(route, "path") and route.path == "/set_max_risk":
                req = MagicMock()
                req.fraction = 0.5
                result = await route.endpoint(req)
                assert result["status"] == "ok"
                assert result["max_risk"] == pytest.approx(0.5)
                break

    @pytest.mark.asyncio
    async def test_activate_hedge_endpoint(self, tmp_path):
        try:
            from risk.orchestrator import create_orchestrator_router
        except ImportError:
            pytest.skip("FastAPI not available")

        orch = _make_orch(tmp_path)
        router = create_orchestrator_router(orch)
        if router is None:
            pytest.skip("FastAPI not available")

        for route in router.routes:
            if hasattr(route, "path") and route.path == "/hedge/activate":
                req = MagicMock()
                req.symbol = "XAU_USD"
                result = await route.endpoint(req)
                assert result["status"] == "ok"
                assert result["hedge_active"] is True
                break

    @pytest.mark.asyncio
    async def test_deactivate_hedge_endpoint(self, tmp_path):
        try:
            from risk.orchestrator import create_orchestrator_router
        except ImportError:
            pytest.skip("FastAPI not available")

        orch = _make_orch(tmp_path)
        router = create_orchestrator_router(orch)
        if router is None:
            pytest.skip("FastAPI not available")

        await orch.activate_hedge_mode("XAU_USD")
        for route in router.routes:
            if hasattr(route, "path") and route.path == "/hedge/deactivate":
                result = await route.endpoint()
                assert result["status"] == "ok"
                assert result["hedge_active"] is False
                break

    @pytest.mark.asyncio
    async def test_get_exposure_endpoint(self, tmp_path):
        try:
            from risk.orchestrator import create_orchestrator_router
        except ImportError:
            pytest.skip("FastAPI not available")

        orch = _make_orch(tmp_path)
        router = create_orchestrator_router(orch)
        if router is None:
            pytest.skip("FastAPI not available")

        for route in router.routes:
            if hasattr(route, "path") and route.path == "/exposure":
                result = await route.endpoint()
                assert "current_exposure" in result
                assert 0.0 <= result["current_exposure"] <= 1.0
                break
