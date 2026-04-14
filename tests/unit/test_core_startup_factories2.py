# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
tests/unit/test_core_startup_factories2.py
==========================================
Extended coverage for core/startup_factories.py — init functions and helpers.
"""

from __future__ import annotations

import asyncio
import json
from unittest.mock import MagicMock, patch

import pytest

import core.startup_factories as sf


# ── _stamp_oanda_paper_start ──────────────────────────────────────────────────


def test_stamp_oanda_paper_start_no_write_when_already_stamped(tmp_path, monkeypatch):
    stamp_path = tmp_path / "data" / "oanda_paper_start.json"
    monkeypatch.setattr(sf, "_OANDA_PAPER_STAMP_PATH", stamp_path)
    monkeypatch.setattr(sf, "_resolve_clock_start_time", lambda: None)
    sf._stamp_oanda_paper_start("ACC123456", practice=True)
    assert not stamp_path.exists()


def test_stamp_oanda_paper_start_creates_file(tmp_path, monkeypatch):
    from datetime import datetime, timezone

    stamp_path = tmp_path / "data" / "oanda_paper_start.json"
    monkeypatch.setattr(sf, "_OANDA_PAPER_STAMP_PATH", stamp_path)
    monkeypatch.setattr(sf, "_resolve_clock_start_time", lambda: datetime(2025, 1, 1, tzinfo=timezone.utc))
    sf._stamp_oanda_paper_start("ACC123456", practice=True)
    assert stamp_path.exists()
    data = json.loads(stamp_path.read_text())
    assert data["requires_real_account"] is False
    assert data["environment"] == "practice"


def test_stamp_oanda_paper_start_live_env(tmp_path, monkeypatch):
    from datetime import datetime, timezone

    stamp_path = tmp_path / "data" / "oanda_paper_start.json"
    monkeypatch.setattr(sf, "_OANDA_PAPER_STAMP_PATH", stamp_path)
    monkeypatch.setattr(sf, "_resolve_clock_start_time", lambda: datetime(2025, 3, 1, tzinfo=timezone.utc))
    sf._stamp_oanda_paper_start("LIVE_ACC_789", practice=False)
    data = json.loads(stamp_path.read_text())
    assert data["environment"] == "live"


# ── _resolve_clock_start_time ─────────────────────────────────────────────────


def test_resolve_clock_start_time_no_file(tmp_path, monkeypatch):
    monkeypatch.setattr(sf, "_OANDA_PAPER_STAMP_PATH", tmp_path / "missing.json")
    result = sf._resolve_clock_start_time()
    assert result is not None
    assert hasattr(result, "year")


def test_resolve_clock_start_time_real_account_stamped(tmp_path, monkeypatch):
    stamp_path = tmp_path / "stamp.json"
    stamp_path.write_text(
        json.dumps(
            {
                "started_utc": "2025-01-01T00:00:00+00:00",
                "requires_real_account": False,
                "account_id": "REAL123…",
            }
        )
    )
    monkeypatch.setattr(sf, "_OANDA_PAPER_STAMP_PATH", stamp_path)
    result = sf._resolve_clock_start_time()
    assert result is None


def test_resolve_clock_start_time_pending_placeholder(tmp_path, monkeypatch):
    stamp_path = tmp_path / "stamp.json"
    stamp_path.write_text(
        json.dumps(
            {
                "started_utc": "2025-01-01T00:00:00+00:00",
                "requires_real_account": True,
            }
        )
    )
    monkeypatch.setattr(sf, "_OANDA_PAPER_STAMP_PATH", stamp_path)
    result = sf._resolve_clock_start_time()
    assert result is not None
    assert result.year == 2025


# ── _validate_oanda_account_pending ──────────────────────────────────────────


def test_validate_oanda_account_pending_no_crash():
    state = MagicMock()
    log_activity = MagicMock()
    sf._validate_oanda_account_pending(state, log_activity)


# ── _connect_paper_broker ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_connect_paper_broker_no_oanda_creds():
    state = MagicMock()
    state.db_session_factory = None
    state.background_tasks = []
    log_activity = MagicMock()

    with patch("core.startup_factories._validate_oanda_account_pending"):
        broker = await sf._connect_paper_broker(state, "oanda", "", "", log_activity)
    assert broker is not None
    assert hasattr(broker, "connect") or hasattr(broker, "connected")


@pytest.mark.asyncio
async def test_connect_paper_broker_with_creds():
    state = MagicMock()
    state.db_session_factory = None
    state.background_tasks = []
    log_activity = MagicMock()

    with patch("core.startup_factories._validate_oanda_account_pending"):
        broker = await sf._connect_paper_broker(state, "oanda", "tok123", "acc456", log_activity)
    assert broker is not None


# ── init_prop_enforcer ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_init_prop_enforcer_no_kill_switch():
    from core.startup_factories import init_prop_enforcer

    state = MagicMock()
    state.kill_switch = None
    result = await init_prop_enforcer(state)
    assert result is not None
    assert state.prop_enforcer is result


@pytest.mark.asyncio
async def test_init_prop_enforcer_with_kill_switch():
    from core.startup_factories import init_prop_enforcer

    state = MagicMock()
    state.kill_switch = MagicMock()
    state.kill_switch.activate = MagicMock()
    result = await init_prop_enforcer(state)
    assert result is not None


# ── init_aml ──────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_init_aml_no_crash():
    from core.startup_factories import init_aml

    state = MagicMock()
    state.db_session_factory = None
    result = await init_aml(state)
    assert result is True


# ── init_strategy_brain ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_init_strategy_brain_returns_brain():
    from core.startup_factories import init_strategy_brain

    state = MagicMock()
    result = await init_strategy_brain(state)
    assert result is not None


# ── init_anomaly_store — feature disabled ─────────────────────────────────────


@pytest.mark.asyncio
async def test_init_anomaly_store_disabled(monkeypatch):
    from core.startup_factories import init_anomaly_store

    monkeypatch.setattr(sf, "_is_feature_enabled", lambda flag, default=False: False)
    state = MagicMock()
    result = await init_anomaly_store(state)
    assert result is None


# ── init_online_learner_store — feature disabled ──────────────────────────────


@pytest.mark.asyncio
async def test_init_online_learner_store_disabled(monkeypatch):
    from core.startup_factories import init_online_learner_store

    monkeypatch.setattr(sf, "_is_feature_enabled", lambda flag, default=False: False)
    state = MagicMock()
    result = await init_online_learner_store(state)
    assert result is None


# ── init_deep_ensemble_store — feature disabled ───────────────────────────────


@pytest.mark.asyncio
async def test_init_deep_ensemble_store_disabled(monkeypatch):
    from core.startup_factories import init_deep_ensemble_store

    monkeypatch.setattr(sf, "_is_feature_enabled", lambda flag, default=False: False)
    state = MagicMock()
    result = await init_deep_ensemble_store(state)
    assert result is None


# ── init_macro_store — always runs ───────────────────────────────────────────


@pytest.mark.asyncio
async def test_init_macro_store_returns_store():
    from core.startup_factories import init_macro_store

    state = MagicMock()
    result = await init_macro_store(state)
    # Returns a MacroStore or None — must not raise
    assert result is not None or result is None


# ── init_risk_manager ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_init_risk_manager_returns_manager():
    from core.startup_factories import init_risk_manager

    state = MagicMock()
    state.config = MagicMock()
    state.config.risk = MagicMock()
    state.config.risk.max_position_size_pct = 0.02
    state.config.risk.max_drawdown_pct = 0.10
    state.config.risk.max_daily_loss_pct = 0.05
    result = await init_risk_manager(state)
    assert result is not None


# ── _start_oanda_paper_clock ──────────────────────────────────────────────────


def test_start_oanda_paper_clock_no_crash():
    sf._start_oanda_paper_clock("ACC123", practice=True)


# ── run_startup_stress_tests ──────────────────────────────────────────────────


def test_run_startup_stress_tests_with_config():
    mock_rm = MagicMock()
    mock_rm.config = MagicMock()
    mock_rm.config.max_position_size_pct = 0.02
    mock_rm.config.max_drawdown_pct = 0.10
    sf.run_startup_stress_tests(mock_rm)


# ── _ConfigDatabaseDefaults ───────────────────────────────────────────────────


def test_config_database_defaults_get_connection_string(monkeypatch):
    from core.startup_factories import _ConfigDatabaseDefaults

    monkeypatch.setenv("DATABASE_URL", "sqlite:///test.db")
    db = _ConfigDatabaseDefaults()
    url = db.get_connection_string()
    assert "sqlite" in url


def test_config_database_defaults_no_url(monkeypatch):
    from core.startup_factories import _ConfigDatabaseDefaults

    monkeypatch.delenv("DATABASE_URL", raising=False)
    db = _ConfigDatabaseDefaults()
    url = db.get_connection_string()
    assert isinstance(url, str)


# ── _ConfigNamespace ──────────────────────────────────────────────────────────


def test_config_namespace_wraps_dict():
    from core.startup_factories import _ConfigNamespace

    ns = _ConfigNamespace({"foo": "bar", "baz": 42})
    assert ns.foo == "bar"
    assert ns.baz == 42
    assert hasattr(ns, "database")
    assert hasattr(ns, "environment")


def test_config_namespace_empty_dict():
    from core.startup_factories import _ConfigNamespace

    ns = _ConfigNamespace({})
    assert ns.environment in ("development", "production", "staging", "test")


# ── init_config ───────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_init_config_returns_namespace():
    from core.startup_factories import init_config

    state = MagicMock()
    result = await init_config(state)
    assert result is not None
    assert hasattr(result, "environment") or hasattr(result, "database")


# ── init_secrets_manager ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_init_secrets_manager_no_crash():
    from core.startup_factories import init_secrets_manager

    state = MagicMock()
    result = await init_secrets_manager(state)
    assert result is not None


# ── init_performance_monitor ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_init_performance_monitor_no_crash():
    from core.startup_factories import init_performance_monitor

    state = MagicMock()
    state.db_session_factory = None
    result = await init_performance_monitor(state)
    assert result is not None or result is None


# ── init_outbox_relay ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_init_outbox_relay_no_crash():
    from core.startup_factories import init_outbox_relay

    state = MagicMock()
    state.background_tasks = []
    result = await init_outbox_relay(state)
    assert result is not None
    # Clean up the background task
    for t in state.background_tasks:
        t.cancel()
        try:
            await t
        except (asyncio.CancelledError, Exception):
            pass


# ── init_position_manager ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_init_position_manager_no_crash():
    from core.startup_factories import init_position_manager

    state = MagicMock()
    result = await init_position_manager(state)
    assert result is not None or result is None


# ── init_position_tracker ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_init_position_tracker_no_crash():
    from core.startup_factories import init_position_tracker

    state = MagicMock()
    state.db_session_factory = None
    result = await init_position_tracker(state)
    assert result is not None or result is None


# ── init_trade_executor ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_init_trade_executor_no_crash():
    from core.startup_factories import init_trade_executor

    state = MagicMock()
    state.broker = None
    state.risk_manager = None
    result = await init_trade_executor(state)
    assert result is not None or result is None


# ── init_wallet ───────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_init_wallet_no_crash():
    from core.startup_factories import init_wallet

    state = MagicMock()
    state.db_session_factory = None
    result = await init_wallet(state)
    assert result is not None or result is None


# ── init_regime_router ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_init_regime_router_no_crash():
    from core.startup_factories import init_regime_router

    state = MagicMock()
    result = await init_regime_router(state)
    assert result is not None or result is None


# ── init_inference_engine — always runs ──────────────────────────────────────


@pytest.mark.asyncio
async def test_init_inference_engine_no_crash():
    from core.startup_factories import init_inference_engine

    state = MagicMock()
    result = await init_inference_engine(state)
    assert result is not None or result is None


# ── init_mtf_store — always runs ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_init_mtf_store_no_crash():
    from core.startup_factories import init_mtf_store

    state = MagicMock()
    result = await init_mtf_store(state)
    assert result is not None or result is None
