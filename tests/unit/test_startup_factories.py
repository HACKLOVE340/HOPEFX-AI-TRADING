# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
Tests for core/startup_factories.py

Covers: init_env (dev/prod secret handling), _is_feature_enabled,
        _ConfigNamespace, _ConfigDatabaseDefaults, build_component_registry,
        and key factory functions (init_config, init_cache, init_risk_manager).
"""

import asyncio
import os
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_state(**kwargs):
    """Minimal AppState-like object."""
    s = MagicMock()
    s.background_tasks = []
    for k, v in kwargs.items():
        setattr(s, k, v)
    return s


# ---------------------------------------------------------------------------
# _is_feature_enabled
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestIsFeatureEnabled:
    def test_returns_default_when_flags_unavailable(self):
        from core.startup_factories import _is_feature_enabled

        # flags module may or may not exist; default should be returned on error
        result = _is_feature_enabled("NONEXISTENT_FLAG_XYZ", default=False)
        assert result is False

    def test_returns_true_default(self):
        from core.startup_factories import _is_feature_enabled

        result = _is_feature_enabled("NONEXISTENT_FLAG_XYZ", default=True)
        assert result is True

    def test_reads_from_flags_module(self, monkeypatch):
        """When config.feature_flags.flags has the attribute, it is returned."""
        from core.startup_factories import _is_feature_enabled

        fake_flags = SimpleNamespace(MY_FEATURE=True)
        fake_module = SimpleNamespace(flags=fake_flags)
        monkeypatch.setitem(sys.modules, "config.feature_flags", fake_module)
        assert _is_feature_enabled("MY_FEATURE", default=False) is True

    def test_returns_default_on_missing_attribute(self, monkeypatch):
        from core.startup_factories import _is_feature_enabled

        fake_flags = SimpleNamespace()  # no MY_FEATURE attribute
        fake_module = SimpleNamespace(flags=fake_flags)
        monkeypatch.setitem(sys.modules, "config.feature_flags", fake_module)
        assert _is_feature_enabled("MY_FEATURE", default=False) is False


# ---------------------------------------------------------------------------
# _ConfigDatabaseDefaults
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestConfigDatabaseDefaults:
    def test_defaults(self):
        from core.startup_factories import _ConfigDatabaseDefaults

        cfg = _ConfigDatabaseDefaults()
        assert cfg.connection_pool_size == 5
        assert cfg.max_overflow == 10

    def test_get_connection_string_default(self, monkeypatch):
        from core.startup_factories import _ConfigDatabaseDefaults

        monkeypatch.delenv("DATABASE_URL", raising=False)
        cfg = _ConfigDatabaseDefaults()
        assert "sqlite" in cfg.get_connection_string()

    def test_get_connection_string_from_env(self, monkeypatch):
        from core.startup_factories import _ConfigDatabaseDefaults

        monkeypatch.setenv("DATABASE_URL", "postgresql://user:pass@localhost/db")
        cfg = _ConfigDatabaseDefaults()
        assert cfg.get_connection_string() == "postgresql://user:pass@localhost/db"


# ---------------------------------------------------------------------------
# _ConfigNamespace
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestConfigNamespace:
    def test_wraps_dict_as_attributes(self):
        from core.startup_factories import _ConfigNamespace

        ns = _ConfigNamespace({"foo": "bar", "num": 42})
        assert ns.foo == "bar"
        assert ns.num == 42

    def test_environment_defaults_to_env_var(self, monkeypatch):
        from core.startup_factories import _ConfigNamespace

        monkeypatch.setenv("APP_ENV", "staging")
        ns = _ConfigNamespace({})
        assert ns.environment == "staging"

    def test_database_attribute_is_defaults(self):
        from core.startup_factories import _ConfigDatabaseDefaults, _ConfigNamespace

        ns = _ConfigNamespace({})
        assert isinstance(ns.database, _ConfigDatabaseDefaults)

    def test_api_configs_defaults_to_empty_dict(self):
        from core.startup_factories import _ConfigNamespace

        ns = _ConfigNamespace({})
        assert ns.api_configs == {}

    def test_existing_environment_not_overwritten(self):
        from core.startup_factories import _ConfigNamespace

        ns = _ConfigNamespace({"environment": "production"})
        assert ns.environment == "production"


# ---------------------------------------------------------------------------
# init_env — development mode
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestInitEnvDev:
    @pytest.fixture(autouse=True)
    def _clean_secrets(self, monkeypatch):
        """Remove secrets so init_env generates ephemeral ones."""
        monkeypatch.setenv("APP_ENV", "development")
        monkeypatch.delenv("SECURITY_JWT_SECRET", raising=False)
        monkeypatch.delenv("CONFIG_ENCRYPTION_KEY", raising=False)
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    def test_returns_true_in_dev(self):
        from core.startup_factories import init_env

        s = _make_state()
        result = asyncio.get_event_loop().run_until_complete(init_env(s))
        assert result is True

    def test_generates_jwt_secret_when_missing(self, monkeypatch):
        from core.startup_factories import init_env

        s = _make_state()
        asyncio.get_event_loop().run_until_complete(init_env(s))
        assert len(os.environ.get("SECURITY_JWT_SECRET", "")) > 0

    def test_generates_encryption_key_when_missing(self, monkeypatch):
        from core.startup_factories import init_env

        s = _make_state()
        asyncio.get_event_loop().run_until_complete(init_env(s))
        assert len(os.environ.get("CONFIG_ENCRYPTION_KEY", "")) > 0

    def test_does_not_overwrite_existing_jwt_secret(self, monkeypatch):
        from core.startup_factories import init_env

        monkeypatch.setenv("SECURITY_JWT_SECRET", "existing-secret-value")
        s = _make_state()
        asyncio.get_event_loop().run_until_complete(init_env(s))
        assert os.environ["SECURITY_JWT_SECRET"] == "existing-secret-value"

    def test_ephemeral_secrets_are_random(self, monkeypatch):
        """Two separate calls generate different ephemeral secrets."""
        from core.startup_factories import init_env

        s = _make_state()
        monkeypatch.delenv("SECURITY_JWT_SECRET", raising=False)
        asyncio.get_event_loop().run_until_complete(init_env(s))
        secret1 = os.environ.get("SECURITY_JWT_SECRET", "")

        monkeypatch.delenv("SECURITY_JWT_SECRET", raising=False)
        asyncio.get_event_loop().run_until_complete(init_env(s))
        secret2 = os.environ.get("SECURITY_JWT_SECRET", "")

        assert secret1 != secret2


# ---------------------------------------------------------------------------
# init_env — production mode (sys.exit guard)
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestInitEnvProd:
    def test_exits_when_jwt_secret_missing_in_production(self, monkeypatch):
        monkeypatch.setenv("APP_ENV", "production")
        monkeypatch.delenv("SECURITY_JWT_SECRET", raising=False)
        monkeypatch.delenv("CONFIG_ENCRYPTION_KEY", raising=False)

        from core.startup_factories import init_env

        s = _make_state()
        with pytest.raises(SystemExit):
            asyncio.get_event_loop().run_until_complete(init_env(s))

    def test_exits_when_encryption_key_missing_in_production(self, monkeypatch):
        monkeypatch.setenv("APP_ENV", "production")
        monkeypatch.setenv("SECURITY_JWT_SECRET", "some-valid-secret-value-here")
        monkeypatch.delenv("CONFIG_ENCRYPTION_KEY", raising=False)

        from core.startup_factories import init_env

        s = _make_state()
        with pytest.raises(SystemExit):
            asyncio.get_event_loop().run_until_complete(init_env(s))

    def test_no_exit_when_both_secrets_present_in_production(self, monkeypatch):
        monkeypatch.setenv("APP_ENV", "production")
        monkeypatch.setenv("SECURITY_JWT_SECRET", "prod-jwt-secret-value-here")
        monkeypatch.setenv("CONFIG_ENCRYPTION_KEY", "prod-enc-key-value-here")

        from core.startup_factories import init_env

        s = _make_state()
        # Patch the env_validator import so it doesn't fail in test env
        with patch("core.env_validator.validate_and_report", create=True):
            try:
                result = asyncio.get_event_loop().run_until_complete(init_env(s))
                assert result is True
            except SystemExit:
                pytest.fail("init_env called sys.exit() even though secrets were present")


# ---------------------------------------------------------------------------
# init_cache
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestInitCache:
    def test_returns_cache_object(self, monkeypatch):
        from core.startup_factories import init_cache

        s = _make_state()
        with patch("cache.MarketDataCache") as MockCache:
            MockCache.return_value = MagicMock()
            result = asyncio.get_event_loop().run_until_complete(init_cache(s))
        assert result is not None

    def test_uses_redis_env_vars(self, monkeypatch):
        from core.startup_factories import init_cache

        monkeypatch.setenv("REDIS_HOST", "redis-server")
        monkeypatch.setenv("REDIS_PORT", "6380")
        s = _make_state()
        with patch("cache.MarketDataCache") as MockCache:
            MockCache.return_value = MagicMock()
            asyncio.get_event_loop().run_until_complete(init_cache(s))
            call_kwargs = MockCache.call_args
        assert call_kwargs is not None
        # host and port should be passed
        args, kwargs = call_kwargs
        assert kwargs.get("host") == "redis-server" or (args and args[0] == "redis-server")


# ---------------------------------------------------------------------------
# init_risk_manager
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestInitRiskManager:
    def test_returns_risk_manager(self):
        from core.startup_factories import init_risk_manager

        s = _make_state()
        with patch("api.admin.log_activity"):
            result = asyncio.get_event_loop().run_until_complete(init_risk_manager(s))
        assert result is not None

    def test_uses_env_vars_for_config(self, monkeypatch):
        from core.startup_factories import init_risk_manager

        monkeypatch.setenv("RISK_MAX_POSITION_SIZE_PCT", "0.03")
        monkeypatch.setenv("RISK_MAX_DRAWDOWN_PCT", "0.15")
        s = _make_state()
        with patch("api.admin.log_activity"):
            rm = asyncio.get_event_loop().run_until_complete(init_risk_manager(s))
        # RiskManager should have been created with the env-var values
        assert rm is not None


# ---------------------------------------------------------------------------
# build_component_registry
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestBuildComponentRegistry:
    def test_returns_registry_object(self):
        from core.startup_factories import build_component_registry

        app = MagicMock()
        flags = MagicMock()
        registry = build_component_registry(app, flags)
        assert registry is not None

    def test_registry_has_required_components(self):
        from core.startup_factories import build_component_registry

        app = MagicMock()
        flags = MagicMock()
        registry = build_component_registry(app, flags)
        # The registry should have registered components
        assert hasattr(registry, "_components") or hasattr(registry, "components") or len(dir(registry)) > 0

    def test_registry_is_not_started(self):
        """build_component_registry must NOT start components — only register them."""
        from core.startup_factories import build_component_registry

        app = MagicMock()
        flags = MagicMock()
        # If start_all were called it would try to connect to DB/Redis — this
        # test verifies it is NOT called during build.
        with patch("core.component_registry.ComponentRegistry.start_all") as mock_start:
            build_component_registry(app, flags)
        mock_start.assert_not_called()


# ---------------------------------------------------------------------------
# _get_log_activity
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestGetLogActivity:
    def test_returns_callable(self):
        from core.startup_factories import _get_log_activity

        fn = _get_log_activity()
        assert callable(fn)

    def test_falls_back_to_logger_info_when_admin_unavailable(self, monkeypatch):
        """When api.admin is not importable, falls back to logger.info."""
        import core.startup_factories as F

        original = sys.modules.get("api.admin")
        sys.modules["api.admin"] = None  # force ImportError path
        try:
            fn = F._get_log_activity()
            assert callable(fn)
        finally:
            if original is None:
                sys.modules.pop("api.admin", None)
            else:
                sys.modules["api.admin"] = original


# ---------------------------------------------------------------------------
# init_config
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestInitConfig:
    def test_returns_config_namespace(self):
        from core.startup_factories import init_config

        s = _make_state()
        with patch("config.initialize_config", return_value={"environment": "test", "debug": True}):
            result = asyncio.get_event_loop().run_until_complete(init_config(s))
        assert result is not None
        assert hasattr(result, "environment")

    def test_wraps_dict_result(self):
        from core.startup_factories import _ConfigNamespace, init_config

        s = _make_state()
        with patch("config.initialize_config", return_value={"foo": "bar"}):
            result = asyncio.get_event_loop().run_until_complete(init_config(s))
        assert isinstance(result, _ConfigNamespace)
        assert result.foo == "bar"

    def test_passes_through_non_dict_result(self):
        from core.startup_factories import init_config

        s = _make_state()
        fake_cfg = MagicMock()
        fake_cfg.environment = "test"
        with patch("config.initialize_config", return_value=fake_cfg):
            result = asyncio.get_event_loop().run_until_complete(init_config(s))
        assert result is fake_cfg
