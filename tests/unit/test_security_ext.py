# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
tests/test_security.py

Security regression tests — auth, CORS, env validation.
Scope: auth/, config/startup_validator.py, mobile/api.py
"""

import os
from pathlib import Path
from unittest.mock import patch

import pytest

# ---------------------------------------------------------------------------
# auth/routes.py must not exist (deleted — contained hardcoded secret)
# ---------------------------------------------------------------------------


class TestAuthRoutesDeleted:
    def test_routes_py_does_not_exist(self):
        """auth/routes.py must be deleted — it contained a hardcoded JWT secret."""
        routes_path = Path(__file__).resolve().parents[2] / "auth" / "routes.py"
        assert not routes_path.exists(), (
            "auth/routes.py still exists. It contains SECRET_KEY='your_secret_key' "  # pragma: allowlist secret
            "and fake_hash_password backdoor. Delete it immediately."
        )

    def test_no_hardcoded_secret_in_auth_jwt(self):
        """auth/jwt.py must not contain a hardcoded production secret."""
        jwt_path = Path(__file__).resolve().parents[2] / "auth" / "jwt.py"
        if not jwt_path.exists():
            pytest.skip("auth/jwt.py not found")
        content = jwt_path.read_text()
        # The file may have a default for dev, but must warn and not silently use it
        assert "your_secret_key" not in content, "auth/jwt.py contains literal 'your_secret_key'"  # healer: ignore
        assert "fakehashedsecret" not in content, "auth/jwt.py contains 'fakehashedsecret' backdoor"


# ---------------------------------------------------------------------------
# CORS: allow_credentials=True with wildcard origins is forbidden
# ---------------------------------------------------------------------------


class TestCORSConfiguration:
    def _read_file(self, rel_path: str) -> str:
        p = Path(__file__).resolve().parents[2] / rel_path
        if not p.exists():
            pytest.skip(f"{rel_path} not found")
        return p.read_text()

    def test_mobile_api_no_wildcard_with_credentials(self):
        content = self._read_file("mobile/api.py")
        # If allow_credentials=True is present, allow_origins must NOT be ["*"]
        if "allow_credentials=True" in content:
            assert 'allow_origins=["*"]' not in content, (
                "mobile/api.py: allow_credentials=True with allow_origins=['*'] "
                "violates CORS spec — browsers reject such responses."
            )

    def test_mobile_api_v2_no_wildcard_with_credentials(self):
        content = self._read_file("mobile/api_v2.py")
        if "allow_credentials=True" in content:
            assert 'allow_origins=["*"]' not in content, (
                "mobile/api_v2.py: allow_credentials=True with allow_origins=['*']"
            )

    def test_mobile_api_credentials_false(self):
        """After fix, allow_credentials must be False."""
        content = self._read_file("mobile/api.py")
        assert "allow_credentials=False" in content, "mobile/api.py: allow_credentials must be False"

    def test_mobile_api_v2_credentials_false(self):
        content = self._read_file("mobile/api_v2.py")
        assert "allow_credentials=False" in content, "mobile/api_v2.py: allow_credentials must be False"


# ---------------------------------------------------------------------------
# Startup env validator
# ---------------------------------------------------------------------------


class TestStartupValidator:
    def test_raises_on_missing_secret_key(self):
        from config.startup_validator import (
            StartupValidationError,
            validate_environment,
        )

        env = {
            "DB_PASSWORD": "strongpassword123",  # nosec B105 - test file  # pragma: allowlist secret
            "DB_HOST": "localhost",
            "REDIS_URL": "redis://localhost:6379/0",
        }
        with patch.dict(os.environ, env, clear=True), pytest.raises((SystemExit, StartupValidationError)):
            validate_environment(strict=False)

    def test_raises_on_weak_secret_key(self):
        from config.startup_validator import (
            StartupValidationError,
            validate_environment,
        )

        env = {
            "SECRET_KEY": "short",  # < 32 chars  # nosec B105 - test file  # pragma: allowlist secret
            "DB_PASSWORD": "strongpassword123",  # nosec B105 - test file  # pragma: allowlist secret
            "DB_HOST": "localhost",
            "REDIS_URL": "redis://localhost:6379/0",
        }
        with patch.dict(os.environ, env, clear=True), pytest.raises((SystemExit, StartupValidationError)):
            validate_environment(strict=False)

    def test_raises_on_missing_db_password(self):
        from config.startup_validator import (
            StartupValidationError,
            validate_environment,
        )

        env = {
            "SECRET_KEY": "a" * 32,
            "DB_HOST": "localhost",
            "REDIS_URL": "redis://localhost:6379/0",
        }
        with patch.dict(os.environ, env, clear=True), pytest.raises((SystemExit, StartupValidationError)):
            validate_environment(strict=False)

    def test_raises_on_invalid_redis_url(self):
        from config.startup_validator import (
            StartupValidationError,
            validate_environment,
        )

        env = {
            "SECRET_KEY": "a" * 32,
            "DB_PASSWORD": "strongpassword123",  # nosec B105 - test file  # pragma: allowlist secret
            "DB_HOST": "localhost",
            "REDIS_URL": "http://localhost:6379",  # wrong scheme
        }
        with patch.dict(os.environ, env, clear=True), pytest.raises((SystemExit, StartupValidationError)):
            validate_environment(strict=False)

    def test_passes_with_valid_env(self):
        from config.startup_validator import validate_environment

        env = {
            # Canonical JWT secret key name used by startup_validator
            "SECURITY_JWT_SECRET": "a" * 32,
            "APP_ENV": "development",  # skip production-only checks
        }
        with patch.dict(os.environ, env, clear=True):
            # Should not raise
            validate_environment(strict=False)

    def test_invalid_ibkr_port_rejected(self):
        from config.startup_validator import (
            StartupValidationError,
            validate_environment,
        )

        env = {
            "SECRET_KEY": "a" * 32,
            "DB_PASSWORD": "strongpassword123",  # nosec B105 - test file  # pragma: allowlist secret
            "DB_HOST": "localhost",
            "REDIS_URL": "redis://localhost:6379/0",
            "IBKR_PORT": "9999",  # not a valid IBKR port
        }
        with patch.dict(os.environ, env, clear=True), pytest.raises((SystemExit, StartupValidationError)):
            validate_environment(strict=False)
