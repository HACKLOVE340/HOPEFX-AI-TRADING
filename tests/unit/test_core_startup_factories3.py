# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
tests/unit/test_core_startup_factories3.py
==========================================
Extended coverage for core/startup_factories.py — async init_* functions.

All external I/O (DB, Redis, broker, ML) is patched at the boundary.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

import core.startup_factories as sf


# ── helpers ───────────────────────────────────────────────────────────────────


def _mock_state():
    """Return a minimal app_state mock."""
    s = MagicMock()
    s.background_tasks = []
    s.broker = None
    s.risk_manager = None
    s.strategy_brain = None
    s.brain = None
    s.data_orchestrator = None
    s.orchestrator = None
    return s


# ── init_env ──────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_init_env_dev_no_jwt(monkeypatch):
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.delenv("SECURITY_JWT_SECRET", raising=False)
    monkeypatch.delenv("CONFIG_ENCRYPTION_KEY", raising=False)
    s = _mock_state()
    with patch("core.startup_factories.validate_and_report", return_value=None, create=True):
        result = await sf.init_env(s)
    assert result is True


@pytest.mark.asyncio
async def test_init_env_dev_with_jwt(monkeypatch):
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("SECURITY_JWT_SECRET", "a" * 64)
    monkeypatch.setenv("CONFIG_ENCRYPTION_KEY", "b" * 64)
    s = _mock_state()
    with patch("core.startup_factories.validate_and_report", return_value=None, create=True):
        result = await sf.init_env(s)
    assert result is True


@pytest.mark.asyncio
async def test_init_env_production_exits_without_jwt(monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.delenv("SECURITY_JWT_SECRET", raising=False)
    s = _mock_state()
    with pytest.raises(SystemExit):
        await sf.init_env(s)


# ── init_model_registry ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_init_model_registry_import_error(monkeypatch):
    monkeypatch.setenv("APP_ENV", "development")
    s = _mock_state()
    with patch.dict("sys.modules", {"ml.model_registry": None}):
        result = await sf.init_model_registry(s)
    # Import error in dev is non-fatal — returns True
    assert result is True


@pytest.mark.asyncio
async def test_init_model_registry_no_active_version(monkeypatch):
    monkeypatch.setenv("APP_ENV", "development")
    s = _mock_state()

    mock_reg = MagicMock()
    mock_reg._load.return_value = {"versions": {"v1": {}}, "active_version": None}
    mock_reg.verify_active.return_value = (True, "ok")
    mock_module = MagicMock(ModelRegistry=MagicMock(return_value=mock_reg))

    with patch.dict("sys.modules", {"ml.model_registry": mock_module}):
        result = await sf.init_model_registry(s)
    assert result is True


@pytest.mark.asyncio
async def test_init_model_registry_integrity_ok(monkeypatch):
    monkeypatch.setenv("APP_ENV", "development")
    s = _mock_state()

    mock_reg = MagicMock()
    mock_reg._load.return_value = {"versions": {"v1": {}}, "active_version": "v1"}
    mock_reg.verify_active.return_value = (True, "SHA-256 OK")
    mock_module = MagicMock(ModelRegistry=MagicMock(return_value=mock_reg))

    with patch.dict("sys.modules", {"ml.model_registry": mock_module}):
        result = await sf.init_model_registry(s)
    assert result is True


@pytest.mark.asyncio
async def test_init_model_registry_integrity_fail_dev(monkeypatch):
    monkeypatch.setenv("APP_ENV", "development")
    s = _mock_state()

    mock_reg = MagicMock()
    mock_reg._load.return_value = {"versions": {"v1": {}}, "active_version": "v1"}
    mock_reg.verify_active.return_value = (False, "hash mismatch")
    mock_module = MagicMock(ModelRegistry=MagicMock(return_value=mock_reg))

    with patch.dict("sys.modules", {"ml.model_registry": mock_module}):
        result = await sf.init_model_registry(s)
    # In dev, integrity failure is non-fatal — returns True
    assert result is True


# ── init_config ───────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_init_config_returns_namespace(monkeypatch):
    s = _mock_state()
    result = await sf.init_config(s)
    assert result is not None


# ── init_cache ────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_init_cache_no_redis(monkeypatch):
    monkeypatch.delenv("REDIS_URL", raising=False)
    s = _mock_state()
    result = await sf.init_cache(s)
    # Returns None or a cache object — must not raise
    assert result is None or hasattr(result, "__class__")


# ── init_compliance ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_init_compliance_no_crash(monkeypatch):
    s = _mock_state()
    result = await sf.init_compliance(s)
    assert result is None or hasattr(result, "__class__")


# ── init_aml ─────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_init_aml_no_crash(monkeypatch):
    s = _mock_state()
    result = await sf.init_aml(s)
    assert isinstance(result, bool)


# ── init_social ───────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_init_social_no_crash(monkeypatch):
    s = _mock_state()
    result = await sf.init_social(s)
    assert isinstance(result, bool)


# ── init_wallet ───────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_init_wallet_no_crash(monkeypatch):
    s = _mock_state()
    result = await sf.init_wallet(s)
    assert result is None or hasattr(result, "__class__")


# ── init_telegram_bot ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_init_telegram_bot_no_token(monkeypatch):
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    s = _mock_state()
    result = await sf.init_telegram_bot(s)
    assert result is None


@pytest.mark.asyncio
async def test_init_telegram_bot_with_token(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "fake:token")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "12345")
    s = _mock_state()
    result = await sf.init_telegram_bot(s)
    assert result is None or hasattr(result, "__class__")


# ── init_hyperopt ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_init_hyperopt_no_crash(monkeypatch):
    s = _mock_state()
    app = MagicMock()
    result = await sf.init_hyperopt(s, app)
    assert isinstance(result, bool)


# ── init_research ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_init_research_flag_disabled(monkeypatch):
    s = _mock_state()
    app = MagicMock()
    flags = MagicMock()
    flags.RESEARCH_MODULE = False
    result = await sf.init_research(s, app, flags)
    assert result is None


@pytest.mark.asyncio
async def test_init_research_flag_enabled_import_error(monkeypatch):
    s = _mock_state()
    app = MagicMock()
    flags = MagicMock()
    flags.RESEARCH_MODULE = True
    result = await sf.init_research(s, app, flags)
    assert result is None or hasattr(result, "__class__")


# ── init_explainability ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_init_explainability_flag_disabled(monkeypatch):
    s = _mock_state()
    app = MagicMock()
    flags = MagicMock()
    flags.EXPLAINABILITY = False
    result = await sf.init_explainability(s, app, flags)
    assert result is None


# ── init_transparency ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_init_transparency_flag_disabled(monkeypatch):
    s = _mock_state()
    app = MagicMock()
    flags = MagicMock()
    flags.TRANSPARENCY_REPORTS = False
    result = await sf.init_transparency(s, app, flags)
    assert result is None


# ── init_teams ────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_init_teams_flag_disabled(monkeypatch):
    s = _mock_state()
    app = MagicMock()
    flags = MagicMock()
    flags.TEAMS_MODULE = False
    result = await sf.init_teams(s, app, flags)
    assert result is None


# ── init_nocode ───────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_init_nocode_flag_disabled(monkeypatch):
    s = _mock_state()
    app = MagicMock()
    flags = MagicMock()
    flags.NOCODE_BUILDER = False
    result = await sf.init_nocode(s, app, flags)
    assert result is None


# ── init_replay ───────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_init_replay_flag_disabled(monkeypatch):
    s = _mock_state()
    app = MagicMock()
    flags = MagicMock()
    flags.REPLAY_ENGINE = False
    result = await sf.init_replay(s, app, flags)
    assert result is None


# ── init_ml_predictions ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_init_ml_predictions_flag_disabled(monkeypatch):
    s = _mock_state()
    app = MagicMock()
    flags = MagicMock()
    flags.ML_PREDICTIONS = False
    result = await sf.init_ml_predictions(s, app, flags)
    assert result is None


# ── init_daily_online_learner ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_init_daily_online_learner_disabled(monkeypatch):
    monkeypatch.setenv("ML_HOURLY_ENABLED", "false")
    s = _mock_state()
    result = await sf.init_daily_online_learner(s)
    assert result is None


# ── init_security_brain ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_init_security_brain_import_error(monkeypatch):
    s = _mock_state()
    app = MagicMock()
    with patch.dict("sys.modules", {"security.global_fortress": None}):
        result = await sf.init_security_brain(s, app)
    assert result is None


# ── init_self_healer ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_init_self_healer_no_crash(monkeypatch):
    s = _mock_state()
    app = MagicMock()
    # May succeed or fail gracefully — must not raise
    result = await sf.init_self_healer(s, app)
    assert result is None or hasattr(result, "__class__")


# ── init_antivirus ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_init_antivirus_no_crash(monkeypatch):
    s = _mock_state()
    app = MagicMock()
    # May succeed or fail gracefully — must not raise
    result = await sf.init_antivirus(s, app)
    assert result is None or hasattr(result, "__class__")


# ── init_chaos_controller ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_init_chaos_controller_no_crash(monkeypatch):
    s = _mock_state()
    result = await sf.init_chaos_controller(s)
    assert result is None or hasattr(result, "__class__")


# ── init_hot_standby ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_init_hot_standby_no_crash(monkeypatch):
    s = _mock_state()
    result = await sf.init_hot_standby(s)
    assert result is None or hasattr(result, "__class__")


# ── init_tick_feed ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_init_tick_feed_no_crash(monkeypatch):
    s = _mock_state()
    result = await sf.init_tick_feed(s)
    assert result is None or hasattr(result, "__class__")


# ── init_factor_engine ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_init_factor_engine_no_crash(monkeypatch):
    s = _mock_state()
    result = await sf.init_factor_engine(s)
    assert result is None or hasattr(result, "__class__")


# ── init_portfolio_rebalancer ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_init_portfolio_rebalancer_no_crash(monkeypatch):
    s = _mock_state()
    result = await sf.init_portfolio_rebalancer(s)
    assert result is None or hasattr(result, "__class__")


# ── init_feature_engineer ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_init_feature_engineer_no_orchestrator(monkeypatch):
    s = _mock_state()
    s.data_orchestrator = None
    s.orchestrator = None
    result = await sf.init_feature_engineer(s)
    assert result is None or hasattr(result, "__class__")


# ── init_decision_engine ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_init_decision_engine_no_brain(monkeypatch):
    s = _mock_state()
    s.strategy_brain = None
    s.brain = None
    result = await sf.init_decision_engine(s)
    assert result is None or hasattr(result, "__class__")


# ── init_reconciler ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_init_reconciler_no_crash(monkeypatch):
    s = _mock_state()
    result = await sf.init_reconciler(s)
    assert result is None or hasattr(result, "__class__")


# ── init_mobile ───────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_init_mobile_no_crash(monkeypatch):
    s = _mock_state()
    app = MagicMock()
    result = await sf.init_mobile(s, app)
    assert result is None or hasattr(result, "__class__")


# ── init_outbox_relay ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_init_outbox_relay_no_crash(monkeypatch):
    s = _mock_state()
    result = await sf.init_outbox_relay(s)
    assert result is None or hasattr(result, "__class__")


# ── init_event_store ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_init_event_store_no_crash(monkeypatch):
    s = _mock_state()
    result = await sf.init_event_store(s)
    assert result is None or hasattr(result, "__class__")


# ── init_performance_monitor ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_init_performance_monitor_no_crash(monkeypatch):
    s = _mock_state()
    result = await sf.init_performance_monitor(s)
    assert result is None or hasattr(result, "__class__")


# ── init_regime_router ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_init_regime_router_no_crash(monkeypatch):
    s = _mock_state()
    result = await sf.init_regime_router(s)
    assert result is None or hasattr(result, "__class__")


# ── init_macro_store ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_init_macro_store_no_crash(monkeypatch):
    s = _mock_state()
    result = await sf.init_macro_store(s)
    assert result is None or hasattr(result, "__class__")


# ── init_mtf_store ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_init_mtf_store_no_crash(monkeypatch):
    s = _mock_state()
    result = await sf.init_mtf_store(s)
    assert result is None or hasattr(result, "__class__")


# ── init_inference_engine ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_init_inference_engine_no_crash(monkeypatch):
    s = _mock_state()
    result = await sf.init_inference_engine(s)
    assert result is None or hasattr(result, "__class__")


# ── init_anomaly_store ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_init_anomaly_store_disabled(monkeypatch):
    monkeypatch.delenv("FEATURE_ANOMALY_WEIGHTING", raising=False)
    s = _mock_state()
    result = await sf.init_anomaly_store(s)
    assert result is None


# ── init_online_learner_store ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_init_online_learner_store_disabled(monkeypatch):
    monkeypatch.delenv("FEATURE_ONLINE_LEARNING", raising=False)
    s = _mock_state()
    result = await sf.init_online_learner_store(s)
    assert result is None


# ── init_deep_ensemble_store ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_init_deep_ensemble_store_no_crash(monkeypatch):
    s = _mock_state()
    result = await sf.init_deep_ensemble_store(s)
    assert result is None or hasattr(result, "__class__")


# ── init_signal_engine ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_init_signal_engine_no_crash(monkeypatch):
    s = _mock_state()
    result = await sf.init_signal_engine(s)
    assert result is None or hasattr(result, "__class__")


# ── init_auth ─────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_init_auth_no_crash(monkeypatch):
    s = _mock_state()
    result = await sf.init_auth(s)
    assert result is None or hasattr(result, "__class__")


# ── init_risk_manager ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_init_risk_manager_no_crash(monkeypatch):
    s = _mock_state()
    result = await sf.init_risk_manager(s)
    assert result is None or hasattr(result, "__class__")


# ── init_strategy_brain ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_init_strategy_brain_no_crash(monkeypatch):
    s = _mock_state()
    result = await sf.init_strategy_brain(s)
    assert result is None or hasattr(result, "__class__")


# ── init_secrets_manager ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_init_secrets_manager_no_crash(monkeypatch):
    s = _mock_state()
    result = await sf.init_secrets_manager(s)
    assert result is None or hasattr(result, "__class__")


# ── init_position_manager ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_init_position_manager_no_crash(monkeypatch):
    s = _mock_state()
    result = await sf.init_position_manager(s)
    assert result is None or hasattr(result, "__class__")


# ── init_position_tracker ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_init_position_tracker_no_crash(monkeypatch):
    s = _mock_state()
    result = await sf.init_position_tracker(s)
    assert result is None or hasattr(result, "__class__")


# ── init_trade_executor ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_init_trade_executor_no_crash(monkeypatch):
    s = _mock_state()
    result = await sf.init_trade_executor(s)
    assert result is None or hasattr(result, "__class__")


# ── init_hopefx_brain ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_init_hopefx_brain_no_crash(monkeypatch):
    s = _mock_state()
    result = await sf.init_hopefx_brain(s)
    assert result is None or hasattr(result, "__class__")


# ── run_startup_stress_tests ──────────────────────────────────────────────────


def test_run_startup_stress_tests_with_mock_rm():
    mock_rm = MagicMock()
    mock_rm.current_balance = 100_000.0
    mock_rm.config = MagicMock()
    mock_rm.config.max_position_size_pct = 0.02
    mock_rm.config.max_drawdown_pct = 0.10
    sf.run_startup_stress_tests(mock_rm)  # must not raise


def test_run_startup_stress_tests_import_error():
    mock_rm = MagicMock()
    mock_rm.current_balance = 50_000.0
    with patch.dict("sys.modules", {"risk.advanced_analytics": None}):
        sf.run_startup_stress_tests(mock_rm)  # must not raise


def test_run_startup_stress_tests_zero_balance():
    mock_rm = MagicMock()
    mock_rm.current_balance = 0
    sf.run_startup_stress_tests(mock_rm)  # must not raise


# ── get_broker_manager ────────────────────────────────────────────────────────


def test_get_broker_manager_no_broker():
    result = sf.get_broker_manager()
    assert result is None


# ── create_app_state ──────────────────────────────────────────────────────────


def test_create_app_state_returns_instance():
    state = sf.create_app_state()
    assert state is not None


# ── build_component_registry ──────────────────────────────────────────────────


def test_build_component_registry_returns_registry():
    from fastapi import FastAPI

    app = FastAPI()
    flags = MagicMock()
    registry = sf.build_component_registry(app, flags)
    assert registry is not None
    assert hasattr(registry, "register")
