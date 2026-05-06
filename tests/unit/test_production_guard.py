# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# AGPL-3.0 — Share all modifications
"""
tests/unit/test_production_guard.py
====================================
Unit tests for utils/production_guard.py.

Covers:
- current_env() reads APP_ENV correctly
- is_production() returns True only for blocked envs
- assert_not_production() raises in prod/staging, passes in dev/test
- production_blocked() decorator enforces the same rules
"""

from __future__ import annotations

import os
import pytest


# ---------------------------------------------------------------------------
# current_env
# ---------------------------------------------------------------------------


class TestCurrentEnv:
    def test_returns_app_env_lowercase(self, monkeypatch):
        monkeypatch.setenv("APP_ENV", "Production")
        from utils.production_guard import current_env
        assert current_env() == "production"

    def test_defaults_to_production_when_unset(self, monkeypatch):
        monkeypatch.delenv("APP_ENV", raising=False)
        from utils.production_guard import current_env
        assert current_env() == "production"

    def test_returns_test_env(self, monkeypatch):
        monkeypatch.setenv("APP_ENV", "test")
        from utils.production_guard import current_env
        assert current_env() == "test"

    def test_returns_development_env(self, monkeypatch):
        monkeypatch.setenv("APP_ENV", "development")
        from utils.production_guard import current_env
        assert current_env() == "development"


# ---------------------------------------------------------------------------
# is_production
# ---------------------------------------------------------------------------


class TestIsProduction:
    @pytest.mark.parametrize("env", ["production", "prod", "staging", "stage"])
    def test_blocked_envs_return_true(self, monkeypatch, env):
        monkeypatch.setenv("APP_ENV", env)
        from utils.production_guard import is_production
        assert is_production() is True

    @pytest.mark.parametrize("env", ["development", "dev", "test", "ci", "local"])
    def test_non_blocked_envs_return_false(self, monkeypatch, env):
        monkeypatch.setenv("APP_ENV", env)
        from utils.production_guard import is_production
        assert is_production() is False


# ---------------------------------------------------------------------------
# assert_not_production
# ---------------------------------------------------------------------------


class TestAssertNotProduction:
    def test_raises_in_production(self, monkeypatch):
        monkeypatch.setenv("APP_ENV", "production")
        from utils.production_guard import assert_not_production
        with pytest.raises(RuntimeError, match="MockFoo"):
            assert_not_production("MockFoo", replacement="RealFoo")

    def test_raises_in_staging(self, monkeypatch):
        monkeypatch.setenv("APP_ENV", "staging")
        from utils.production_guard import assert_not_production
        with pytest.raises(RuntimeError):
            assert_not_production("SyntheticFeed")

    def test_passes_in_development(self, monkeypatch):
        monkeypatch.setenv("APP_ENV", "development")
        from utils.production_guard import assert_not_production
        # Must not raise
        assert_not_production("MockFoo")

    def test_passes_in_test(self, monkeypatch):
        monkeypatch.setenv("APP_ENV", "test")
        from utils.production_guard import assert_not_production
        assert_not_production("MockFoo")

    def test_error_message_includes_replacement(self, monkeypatch):
        monkeypatch.setenv("APP_ENV", "production")
        from utils.production_guard import assert_not_production
        with pytest.raises(RuntimeError, match="RealFoo"):
            assert_not_production("MockFoo", replacement="RealFoo")

    def test_error_message_includes_extra(self, monkeypatch):
        monkeypatch.setenv("APP_ENV", "production")
        from utils.production_guard import assert_not_production
        with pytest.raises(RuntimeError, match="extra guidance"):
            assert_not_production("MockFoo", extra="extra guidance")


# ---------------------------------------------------------------------------
# production_blocked decorator
# ---------------------------------------------------------------------------


class TestProductionBlockedDecorator:
    def test_decorator_raises_in_production(self, monkeypatch):
        monkeypatch.setenv("APP_ENV", "production")
        from utils.production_guard import production_blocked

        @production_blocked("SyntheticDataGenerator")
        def generate():
            return "data"

        with pytest.raises(RuntimeError, match="SyntheticDataGenerator"):
            generate()

    def test_decorator_passes_in_development(self, monkeypatch):
        monkeypatch.setenv("APP_ENV", "development")
        from utils.production_guard import production_blocked

        @production_blocked("SyntheticDataGenerator")
        def generate():
            return "data"

        result = generate()
        assert result == "data"

    def test_decorator_preserves_function_name(self, monkeypatch):
        monkeypatch.setenv("APP_ENV", "test")
        from utils.production_guard import production_blocked

        @production_blocked("Foo")
        def my_function():
            return 42

        assert my_function.__name__ == "my_function"

    def test_decorator_passes_args_through(self, monkeypatch):
        monkeypatch.setenv("APP_ENV", "test")
        from utils.production_guard import production_blocked

        @production_blocked("Foo")
        def add(a, b):
            return a + b

        assert add(3, 4) == 7
