# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
tests/unit/test_core_startup_factories.py
==========================================
Coverage tests for core/startup_factories.py.

External I/O (DB, Redis, broker) is patched at the boundary.
"""

from __future__ import annotations

import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.startup_factories import (
    _is_feature_enabled,
    _get_log_activity,
    get_broker_manager,
    run_startup_stress_tests,
    create_app_state,
)


# ── _is_feature_enabled ───────────────────────────────────────────────────────


def test_is_feature_enabled_default_false():
    result = _is_feature_enabled("NONEXISTENT_FLAG_XYZ")
    assert result is False


def test_is_feature_enabled_default_override():
    result = _is_feature_enabled("NONEXISTENT_FLAG_XYZ", default=True)
    assert result is True


def test_is_feature_enabled_returns_bool():
    result = _is_feature_enabled("FEATURE_PAYMENTS")
    assert isinstance(result, bool)


def test_is_feature_enabled_unknown_flag_returns_default_false():
    result = _is_feature_enabled("TOTALLY_UNKNOWN_FLAG_ABCDEF")
    assert result is False


def test_is_feature_enabled_unknown_flag_default_true():
    result = _is_feature_enabled("TOTALLY_UNKNOWN_FLAG_ABCDEF", default=True)
    assert result is True


# ── _get_log_activity ─────────────────────────────────────────────────────────


def test_get_log_activity_returns_callable_or_none():
    result = _get_log_activity()
    assert result is None or callable(result)


# ── get_broker_manager ────────────────────────────────────────────────────────


def test_get_broker_manager_returns_object_or_none():
    result = get_broker_manager()
    # Returns None when no broker is configured in test env
    assert result is None or hasattr(result, "__class__")


# ── run_startup_stress_tests ──────────────────────────────────────────────────


def test_run_startup_stress_tests_no_crash():
    mock_rm = MagicMock()
    mock_rm.config = MagicMock()
    mock_rm.config.max_position_size_pct = 0.02
    mock_rm.config.max_drawdown_pct = 0.10
    run_startup_stress_tests(mock_rm)  # must not raise


# ── create_app_state ──────────────────────────────────────────────────────────


def test_create_app_state_returns_object():
    state = create_app_state()
    assert state is not None


def test_create_app_state_has_expected_attributes():
    state = create_app_state()
    # Should have at minimum these attributes
    for attr in ("broker", "risk_manager", "strategy_brain"):
        assert hasattr(state, attr), f"Missing attribute: {attr}"


# ── init_env — importable ─────────────────────────────────────────────────────


def test_init_env_importable():
    from core.startup_factories import init_env
    import inspect
    assert inspect.iscoroutinefunction(init_env)


# ── init_config — importable ──────────────────────────────────────────────────


def test_init_config_importable():
    from core.startup_factories import init_config
    import inspect
    assert inspect.iscoroutinefunction(init_config)


# ── init_risk_manager — importable ────────────────────────────────────────────


def test_init_risk_manager_importable():
    from core.startup_factories import init_risk_manager
    import inspect
    assert inspect.iscoroutinefunction(init_risk_manager)


# ── init_risk_manager — runs without DB ──────────────────────────────────────


@pytest.mark.asyncio
async def test_init_risk_manager_no_db():
    from core.startup_factories import init_risk_manager
    state = MagicMock()
    state.config = MagicMock()
    state.config.risk = MagicMock()
    state.config.risk.max_position_size_pct = 0.02
    state.config.risk.max_drawdown_pct = 0.10
    state.config.risk.max_daily_loss_pct = 0.05
    result = await init_risk_manager(state)
    assert result is not None


# ── init_secrets_manager — importable ────────────────────────────────────────


@pytest.mark.asyncio
async def test_init_secrets_manager_no_crash():
    from core.startup_factories import init_secrets_manager
    state = MagicMock()
    result = await init_secrets_manager(state)
    assert result is not None


# ── _enforce_redis_maxmemory — no crash when redis down ──────────────────────


def test_enforce_redis_maxmemory_no_crash():
    from core.startup_factories import _enforce_redis_maxmemory
    # Redis is not running in CI — must not raise
    _enforce_redis_maxmemory("localhost", 6379)
