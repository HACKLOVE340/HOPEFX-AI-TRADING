# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
tests/unit/test_core_env_validator.py
======================================
Coverage tests for core/env_validator.py.
"""

from __future__ import annotations


import pytest

from core.env_validator import (
    EnvVar,
    ValidationResult,
    validate_and_report,
    validate_environment,
)


# ── EnvVar dataclass ──────────────────────────────────────────────────────────


def test_envvar_defaults():
    v = EnvVar("MY_VAR")
    assert v.required is True
    assert v.min_length == 0
    assert v.description == ""
    assert v.default is None


# ── ValidationResult ──────────────────────────────────────────────────────────


def test_validation_result_ok_when_no_errors():
    r = ValidationResult()
    assert r.ok is True


def test_validation_result_not_ok_with_errors():
    r = ValidationResult(errors=["something wrong"])
    assert r.ok is False


# ── validate_environment — required vars ──────────────────────────────────────


def test_validate_passes_when_required_vars_set(monkeypatch):
    monkeypatch.setenv("SECURITY_JWT_SECRET", "a" * 32)
    monkeypatch.setenv("CONFIG_ENCRYPTION_KEY", "b" * 32)
    monkeypatch.setenv("APP_ENV", "development")
    result = validate_environment()
    # Required vars are set — no errors about them
    required_errors = [e for e in result.errors if "SECURITY_JWT_SECRET" in e or "CONFIG_ENCRYPTION_KEY" in e]
    assert required_errors == []


def test_validate_error_when_jwt_missing(monkeypatch):
    monkeypatch.delenv("SECURITY_JWT_SECRET", raising=False)
    monkeypatch.setenv("CONFIG_ENCRYPTION_KEY", "b" * 32)
    result = validate_environment()
    assert any("SECURITY_JWT_SECRET" in e for e in result.errors)


def test_validate_error_when_jwt_too_short(monkeypatch):
    monkeypatch.setenv("SECURITY_JWT_SECRET", "short")
    monkeypatch.setenv("CONFIG_ENCRYPTION_KEY", "b" * 32)
    result = validate_environment()
    assert any("SECURITY_JWT_SECRET" in e and "too short" in e for e in result.errors)


def test_validate_error_when_encryption_key_missing(monkeypatch):
    monkeypatch.setenv("SECURITY_JWT_SECRET", "a" * 32)
    monkeypatch.delenv("CONFIG_ENCRYPTION_KEY", raising=False)
    result = validate_environment()
    assert any("CONFIG_ENCRYPTION_KEY" in e for e in result.errors)


# ── validate_environment — production placeholder check ───────────────────────


def test_validate_production_rejects_dev_placeholder(monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("SECURITY_JWT_SECRET", "dev-jwt-secret-minimum-32-characters-long!!")
    monkeypatch.setenv("CONFIG_ENCRYPTION_KEY", "b" * 32)
    result = validate_environment()
    assert any("SECURITY_JWT_SECRET" in e and "placeholder" in e for e in result.errors)


def test_validate_production_rejects_encryption_key_placeholder(monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("SECURITY_JWT_SECRET", "a" * 32)
    monkeypatch.setenv("CONFIG_ENCRYPTION_KEY", "dev-key-minimum-32-characters-long-for-testing")
    result = validate_environment()
    assert any("CONFIG_ENCRYPTION_KEY" in e and "placeholder" in e for e in result.errors)


def test_validate_production_rejects_other_placeholders(monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("SECURITY_JWT_SECRET", "a" * 32)
    monkeypatch.setenv("CONFIG_ENCRYPTION_KEY", "b" * 32)
    monkeypatch.setenv("HOPEFX_KILL_SWITCH_TOKEN", "CHANGE_ME_generate_64_char_hex_token")  # healer: ignore
    result = validate_environment()
    assert any("HOPEFX_KILL_SWITCH_TOKEN" in e for e in result.errors)


# ── validate_environment — recommended vars ───────────────────────────────────


def test_validate_warns_on_missing_recommended(monkeypatch):
    monkeypatch.setenv("SECURITY_JWT_SECRET", "a" * 32)
    monkeypatch.setenv("CONFIG_ENCRYPTION_KEY", "b" * 32)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    result = validate_environment()
    assert any("DATABASE_URL" in w for w in result.warnings)


def test_validate_strict_treats_missing_recommended_as_error(monkeypatch):
    monkeypatch.setenv("SECURITY_JWT_SECRET", "a" * 32)
    monkeypatch.setenv("CONFIG_ENCRYPTION_KEY", "b" * 32)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    result = validate_environment(strict=True)
    assert any("DATABASE_URL" in e for e in result.errors)


# ── validate_and_report ───────────────────────────────────────────────────────


def test_validate_and_report_no_exit_on_success(monkeypatch):
    monkeypatch.setenv("SECURITY_JWT_SECRET", "a" * 32)
    monkeypatch.setenv("CONFIG_ENCRYPTION_KEY", "b" * 32)
    result = validate_and_report(exit_on_error=False)
    # Should not raise or exit
    assert isinstance(result, ValidationResult)


def test_validate_and_report_no_exit_on_error(monkeypatch):
    monkeypatch.delenv("SECURITY_JWT_SECRET", raising=False)
    monkeypatch.setenv("CONFIG_ENCRYPTION_KEY", "b" * 32)
    result = validate_and_report(exit_on_error=False)
    assert not result.ok


def test_validate_and_report_exits_on_error(monkeypatch):
    monkeypatch.delenv("SECURITY_JWT_SECRET", raising=False)
    monkeypatch.setenv("CONFIG_ENCRYPTION_KEY", "b" * 32)
    with pytest.raises(SystemExit):
        validate_and_report(exit_on_error=True)
