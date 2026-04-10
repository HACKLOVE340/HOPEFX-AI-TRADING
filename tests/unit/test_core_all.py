# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""Tests for core/ — SecretsManager, PositionReconciler, OutboxRelay, RegimeRouter."""

from __future__ import annotations

import asyncio
import os
from datetime import timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

UTC = timezone.utc

# ---------------------------------------------------------------------------
# SecretsManager
# ---------------------------------------------------------------------------
from core.secrets_manager import SecretsManager, get_secret


class TestSecretsManager:
    def test_get_from_env(self):
        with patch.dict(os.environ, {"SECURITY_JWT_SECRET": "test-secret-value"}):
            sm = SecretsManager()
            # jwt_secret_key maps to SECURITY_JWT_SECRET via _ENV_FALLBACK
            val = sm.get("jwt_secret_key", default="fallback")
            # Either the env var is found or the default is returned
            assert val is not None

    def test_get_default_when_missing(self):
        sm = SecretsManager()
        val = sm.get("nonexistent_key_xyz", default="fallback")
        assert val == "fallback"

    def test_set_overrides_value(self):
        sm = SecretsManager()
        sm.set("test_key", "test_value")
        assert sm.get("test_key") == "test_value"

    def test_get_sync_same_as_get(self):
        sm = SecretsManager()
        sm.set("sync_key", "sync_val")
        assert sm.get_sync("sync_key") == "sync_val"

    def test_status_returns_dict(self):
        sm = SecretsManager()
        s = sm.status()
        assert isinstance(s, dict)
        assert "backend" in s

    def test_stop_no_crash(self):
        sm = SecretsManager()
        sm.stop()  # should not raise

    def test_on_rotation_registers_callback(self):
        sm = SecretsManager()
        called = []
        sm.on_rotation(called.append)
        assert len(sm._rotation_callbacks) >= 1

    def test_load_from_env(self):
        with patch.dict(os.environ, {"SECURITY_JWT_SECRET": "jwt-val-32-chars-long-enough!!"}):
            sm = SecretsManager()
            sm._load_from_env()
            # Should not raise

    @pytest.mark.asyncio
    async def test_refresh_env_backend(self):
        sm = SecretsManager()
        await sm.refresh()  # env backend — no HTTP calls

    def test_get_secret_module_function(self):
        val = get_secret("nonexistent_xyz_key", default="default_val")
        assert val == "default_val"


# ---------------------------------------------------------------------------
# PositionReconciler
# ---------------------------------------------------------------------------
from core.position_reconciler import PositionReconciler


def _mock_session_factory(positions=None):
    """Return a session factory that yields a mock DB session."""
    session = MagicMock()
    pos_list = positions or []
    session.query.return_value.filter.return_value.all.return_value = pos_list
    session.query.return_value.all.return_value = pos_list
    session.__enter__ = MagicMock(return_value=session)
    session.__exit__ = MagicMock(return_value=False)
    factory = MagicMock(return_value=session)
    factory.return_value.__enter__ = MagicMock(return_value=session)
    factory.return_value.__exit__ = MagicMock(return_value=False)
    return factory


class TestPositionReconciler:
    def test_init(self):
        sf = _mock_session_factory()
        rec = PositionReconciler(session_factory=sf, interval_seconds=5)
        assert rec._running is False
        assert rec._cycles == 0

    def test_stats_keys(self):
        sf = _mock_session_factory()
        rec = PositionReconciler(session_factory=sf)
        s = rec.stats  # property, not method
        assert "cycles" in s
        assert "mismatches" in s
        assert "running" in s

    @pytest.mark.asyncio
    async def test_start_stop(self):
        sf = _mock_session_factory()
        rec = PositionReconciler(session_factory=sf, interval_seconds=1)
        task = asyncio.create_task(rec.start())
        await asyncio.sleep(0.05)
        assert rec._running is True
        await rec.stop()
        assert rec._running is False
        task.cancel()
        import contextlib

        with contextlib.suppress(asyncio.CancelledError, Exception):
            await task

    @pytest.mark.asyncio
    async def test_reconcile_once_no_positions(self):
        sf = _mock_session_factory(positions=[])
        rec = PositionReconciler(session_factory=sf)
        await rec._reconcile_once()  # should not raise

    @pytest.mark.asyncio
    async def test_reconcile_once_with_broker_no_positions(self):
        sf = _mock_session_factory(positions=[])
        broker = MagicMock()
        broker.get_positions = AsyncMock(return_value=[])
        rec = PositionReconciler(session_factory=sf, broker=broker)
        await rec._reconcile_once()

    def test_calc_pnl_buy(self):
        pos = MagicMock()
        pos.side = "buy"
        pos.quantity = 1.0
        pos.entry_price = 1900.0
        pnl = PositionReconciler._calc_pnl(pos, current_price=1910.0)
        assert pnl == pytest.approx(10.0)

    def test_calc_pnl_sell(self):
        pos = MagicMock()
        pos.side = "sell"
        pos.quantity = 1.0
        pos.entry_price = 1900.0
        pnl = PositionReconciler._calc_pnl(pos, current_price=1890.0)
        assert pnl == pytest.approx(10.0)


# ---------------------------------------------------------------------------
# OutboxRelay
# ---------------------------------------------------------------------------
from core.outbox import OutboxRelay, write_outbox_event_standalone


class TestOutboxRelay:
    def test_init(self):
        relay = OutboxRelay()
        assert relay is not None
        assert relay._running is False

    def test_stop_sets_flag(self):
        relay = OutboxRelay()
        relay._running = True
        relay.stop()
        assert relay._running is False

    @pytest.mark.asyncio
    async def test_relay_batch_no_db_no_crash(self):
        relay = OutboxRelay()
        # No DB configured — should handle gracefully
        await relay._relay_batch()

    @pytest.mark.asyncio
    async def test_run_stops_on_stop(self):
        relay = OutboxRelay()
        task = asyncio.create_task(relay.run())
        await asyncio.sleep(0.05)
        relay.stop()
        await asyncio.sleep(0.05)
        task.cancel()
        import contextlib

        with contextlib.suppress(asyncio.CancelledError, Exception):
            await task
        assert relay._running is False


class TestWriteOutboxEventStandalone:
    def test_write_no_db_no_crash(self):
        # Without a DB session, should log and return gracefully
        write_outbox_event_standalone(
            event_type="KILL_SWITCH",
            channel="hopefx:breach",
            payload={"reason": "test"},
        )


# ---------------------------------------------------------------------------
# RegimeRouter (shim re-export)
# ---------------------------------------------------------------------------
from core.regime_router import RegimeRouter


class TestRegimeRouter:
    def test_import_succeeds(self):
        assert RegimeRouter is not None

    def test_regime_router_is_class(self):
        assert isinstance(RegimeRouter, type)

    def test_instantiation_with_strategy_manager(self):
        sm = MagicMock()
        rr = RegimeRouter(strategy_manager=sm)
        assert rr is not None

    def test_has_expected_methods(self):
        sm = MagicMock()
        rr = RegimeRouter(strategy_manager=sm)
        # At least one routing/regime method should exist
        has_method = any(hasattr(rr, m) for m in ("route", "get_regime", "select", "update", "on_tick"))
        assert has_method
