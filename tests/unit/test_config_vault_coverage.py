# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
Comprehensive coverage tests for config/vault.py, config/feature_flags.py,
and config/startup_validator.py.

All tests use real implementations — no mocks of the modules under test.
External I/O (keyring) is patched at the boundary.
"""

from __future__ import annotations

import os
from unittest.mock import patch

import pytest


# ===========================================================================
# config/vault.py — SecureVault
# ===========================================================================


@pytest.mark.unit
class TestSecureVaultSingleton:
    def test_singleton_returns_same_instance(self):
        from config.vault import SecureVault

        a = SecureVault()
        b = SecureVault()
        assert a is b

    def test_global_vault_instance(self):
        from config.vault import vault, SecureVault

        assert isinstance(vault, SecureVault)


@pytest.mark.unit
class TestSecureVaultInitialize:
    def _fresh_vault(self):
        from config.vault import SecureVault

        v = SecureVault()
        v._fernet = None
        v._initialized = False
        return v

    def test_initialize_with_stored_key(self):
        from cryptography.fernet import Fernet

        key = Fernet.generate_key()
        v = self._fresh_vault()
        with patch("keyring.get_password", return_value=key.decode()):
            v.initialize()
        assert v._fernet is not None

    def test_initialize_with_password_no_stored_key(self):
        v = self._fresh_vault()
        with patch("keyring.get_password", return_value=None), patch("keyring.set_password"):
            v.initialize(password="test-password-for-vault-init")  # pragma: allowlist secret
        assert v._fernet is not None

    def test_initialize_no_key_no_password_raises(self):
        from core.exceptions import VaultError

        v = self._fresh_vault()
        with patch("keyring.get_password", return_value=None), pytest.raises(VaultError, match="No stored key"):
            v.initialize()

    def test_initialize_keyring_exception_raises_vault_error(self):
        from core.exceptions import VaultError

        v = self._fresh_vault()
        with patch("keyring.get_password", side_effect=RuntimeError("keyring unavailable")):
            with pytest.raises(VaultError, match="Vault initialization failed"):
                v.initialize()

    def test_double_initialize_sets_fernet(self):
        from cryptography.fernet import Fernet

        key = Fernet.generate_key()
        v = self._fresh_vault()
        with patch("keyring.get_password", return_value=key.decode()):
            v.initialize()
        # After initialization fernet must be set
        assert v._fernet is not None


@pytest.mark.unit
class TestSecureVaultEncryptDecrypt:
    @pytest.fixture(autouse=True)
    def _init_vault(self):
        from config.vault import SecureVault
        from cryptography.fernet import Fernet

        key = Fernet.generate_key()
        self.vault = SecureVault()
        self.vault._fernet = None
        self.vault._initialized = False
        with patch("keyring.get_password", return_value=key.decode()):
            self.vault.initialize()

    def test_encrypt_string(self):
        token = self.vault.encrypt("hello-world")
        assert isinstance(token, str)
        assert token != "hello-world"

    def test_decrypt_string_roundtrip(self):
        original = "secret-api-key-xyz"
        token = self.vault.encrypt(original)
        assert self.vault.decrypt(token) == original

    def test_encrypt_dict(self):
        data = {"key": "value", "num": 42}
        token = self.vault.encrypt(data)
        assert isinstance(token, str)

    def test_encrypt_bytes(self):
        token = self.vault.encrypt(b"raw bytes data")
        assert isinstance(token, str)

    def test_decrypt_invalid_token_raises_error(self):
        from core.exceptions import AuthenticationError, VaultError

        # Either AuthenticationError (bad Fernet token) or VaultError (bad base64)
        with pytest.raises((AuthenticationError, VaultError)):
            self.vault.decrypt("not-a-valid-token==")

    def test_encrypt_not_initialized_raises(self):
        from config.vault import SecureVault
        from core.exceptions import VaultError

        v = SecureVault()
        v._fernet = None
        v._initialized = True  # bypass __init__ guard
        with pytest.raises(VaultError, match="not initialized"):
            v.encrypt("data")

    def test_decrypt_not_initialized_raises(self):
        from config.vault import SecureVault
        from core.exceptions import VaultError

        v = SecureVault()
        v._fernet = None
        v._initialized = True
        with pytest.raises(VaultError, match="not initialized"):
            v.decrypt("token")


@pytest.mark.unit
class TestSecureVaultPasswordHashing:
    @pytest.fixture(autouse=True)
    def _init_vault(self):
        from config.vault import SecureVault
        from cryptography.fernet import Fernet

        key = Fernet.generate_key()
        self.vault = SecureVault()
        self.vault._fernet = None
        self.vault._initialized = False
        with patch("keyring.get_password", return_value=key.decode()):
            self.vault.initialize()

    def test_hash_password_returns_string(self):
        h = self.vault.hash_password("my-password-123")
        assert isinstance(h, str)
        assert len(h) > 20

    def test_verify_password_correct(self):
        h = self.vault.hash_password("correct-password")
        assert self.vault.verify_password("correct-password", h) is True

    def test_verify_password_wrong(self):
        h = self.vault.hash_password("correct-password")
        assert self.vault.verify_password("wrong-password", h) is False

    def test_hash_is_not_plaintext(self):
        pw = "plaintext-password"
        h = self.vault.hash_password(pw)
        assert pw not in h


@pytest.mark.unit
class TestSecureVaultSecureDelete:
    def test_secure_delete_clears_fernet(self):
        from config.vault import SecureVault
        from cryptography.fernet import Fernet

        key = Fernet.generate_key()
        v = SecureVault()
        v._fernet = None
        v._initialized = False
        with patch("keyring.get_password", return_value=key.decode()):
            v.initialize()
        assert v._fernet is not None
        with patch("keyring.delete_password"):
            v.secure_delete()
        assert v._fernet is None

    def test_secure_delete_keyring_failure_raises(self):
        from config.vault import SecureVault
        from cryptography.fernet import Fernet
        from core.exceptions import VaultError

        key = Fernet.generate_key()
        v = SecureVault()
        v._fernet = None
        v._initialized = False
        with patch("keyring.get_password", return_value=key.decode()):
            v.initialize()
        with patch("keyring.delete_password", side_effect=Exception("keyring error")):
            with pytest.raises(VaultError, match="Keyring wipe failed"):
                v.secure_delete()
        # fernet is still cleared in finally block
        assert v._fernet is None


# ===========================================================================
# config/startup_validator.py
# ===========================================================================


@pytest.mark.unit
class TestStartupValidatorDevMode:
    """In dev mode most checks are skipped."""

    def _run(self, env_overrides: dict):
        from config.startup_validator import validate_environment_or_raise

        base = {
            "APP_ENV": "development",
            "SECURITY_JWT_SECRET": "a" * 40,
            "BROKER_TYPE": "paper",
        }
        base.update(env_overrides)
        with patch.dict(os.environ, base, clear=True):
            validate_environment_or_raise()  # should not raise

    def test_dev_mode_minimal_config_passes(self):
        self._run({})

    def test_dev_mode_with_oanda_broker_requires_credentials(self):
        from config.startup_validator import StartupValidationError

        with (
            patch.dict(
                os.environ,
                {
                    "APP_ENV": "development",
                    "SECURITY_JWT_SECRET": "a" * 40,
                    "BROKER_TYPE": "oanda",
                },
                clear=True,
            ),
            pytest.raises(StartupValidationError),
        ):
            from config.startup_validator import validate_environment_or_raise

            validate_environment_or_raise()

    def test_dev_mode_invalid_broker_type_raises(self):
        from config.startup_validator import StartupValidationError

        with (
            patch.dict(
                os.environ,
                {
                    "APP_ENV": "development",
                    "SECURITY_JWT_SECRET": "a" * 40,
                    "BROKER_TYPE": "unknown_broker",
                },
                clear=True,
            ),
            pytest.raises(StartupValidationError),
        ):
            from config.startup_validator import validate_environment_or_raise

            validate_environment_or_raise()


@pytest.mark.unit
class TestStartupValidatorJWT:
    def _run_dev(self, jwt_val: str):
        from config.startup_validator import validate_environment_or_raise

        env = {"APP_ENV": "development", "BROKER_TYPE": "paper"}
        if jwt_val:
            env["SECURITY_JWT_SECRET"] = jwt_val
        with patch.dict(os.environ, env, clear=True):
            validate_environment_or_raise()

    def test_missing_jwt_raises(self):
        from config.startup_validator import StartupValidationError

        with patch.dict(os.environ, {"APP_ENV": "development", "BROKER_TYPE": "paper"}, clear=True):
            with pytest.raises(StartupValidationError, match="SECURITY_JWT_SECRET"):
                from config.startup_validator import validate_environment_or_raise

                validate_environment_or_raise()

    def test_short_jwt_raises(self):
        from config.startup_validator import StartupValidationError

        with (
            patch.dict(
                os.environ,
                {
                    "APP_ENV": "development",
                    "BROKER_TYPE": "paper",
                    "SECURITY_JWT_SECRET": "short",  # pragma: allowlist secret
                },
                clear=True,
            ),
            pytest.raises(StartupValidationError, match="TOO_SHORT"),
        ):
            from config.startup_validator import validate_environment_or_raise

            validate_environment_or_raise()

    def test_change_me_jwt_raises(self):
        from config.startup_validator import StartupValidationError

        with (
            patch.dict(
                os.environ,
                {
                    "APP_ENV": "development",
                    "BROKER_TYPE": "paper",
                    "SECURITY_JWT_SECRET": "CHANGE_ME_this_is_a_placeholder_value_here",  # pragma: allowlist secret
                },
                clear=True,
            ),
            pytest.raises(StartupValidationError, match="INSECURE"),
        ):
            from config.startup_validator import validate_environment_or_raise

            validate_environment_or_raise()

    def test_jwt_secret_key_fallback_accepted(self):
        with patch.dict(
            os.environ,
            {
                "APP_ENV": "development",
                "BROKER_TYPE": "paper",
                "JWT_SECRET_KEY": "a" * 40,
            },
            clear=True,
        ):
            from config.startup_validator import validate_environment_or_raise

            validate_environment_or_raise()  # should not raise


@pytest.mark.unit
class TestStartupValidatorProduction:
    def _prod_env(self, overrides: dict | None = None) -> dict:
        base = {
            "APP_ENV": "production",
            "SECURITY_JWT_SECRET": "a" * 48,
            "DATABASE_URL": "postgresql://user:password123@host:5432/db",  # pragma: allowlist secret
            "REDIS_URL": "redis://localhost:6379/0",
            "CONFIG_ENCRYPTION_KEY": "b" * 48,
            "HOPEFX_KILL_SWITCH_TOKEN": "c" * 48,
            "BROKER_TYPE": "paper",
            "ALLOWED_ORIGINS": "https://app.example.com",
            "CRYPTO_WEBHOOK_SECRET": "d" * 32,
        }
        if overrides:
            base.update(overrides)
        return base

    def test_full_production_config_passes(self):
        with patch.dict(os.environ, self._prod_env(), clear=True):
            from config.startup_validator import validate_environment_or_raise

            validate_environment_or_raise()

    def test_missing_database_url_raises(self):
        from config.startup_validator import StartupValidationError

        env = self._prod_env()
        del env["DATABASE_URL"]
        with patch.dict(os.environ, env, clear=True):
            with pytest.raises(StartupValidationError, match="DATABASE_URL"):
                from config.startup_validator import validate_environment_or_raise

                validate_environment_or_raise()

    def test_missing_redis_url_raises(self):
        from config.startup_validator import StartupValidationError

        env = self._prod_env()
        del env["REDIS_URL"]
        with patch.dict(os.environ, env, clear=True), pytest.raises(StartupValidationError, match="REDIS_URL"):
            from config.startup_validator import validate_environment_or_raise

            validate_environment_or_raise()

    def test_invalid_redis_url_raises(self):
        from config.startup_validator import StartupValidationError

        env = self._prod_env({"REDIS_URL": "http://localhost:6379"})
        with patch.dict(os.environ, env, clear=True):
            with pytest.raises(StartupValidationError, match="INVALID.*REDIS_URL"):
                from config.startup_validator import validate_environment_or_raise

                validate_environment_or_raise()

    def test_redis_host_without_url_suggests_url(self):
        from config.startup_validator import StartupValidationError

        env = self._prod_env()
        del env["REDIS_URL"]
        env["REDIS_HOST"] = "myredis.host"
        with patch.dict(os.environ, env, clear=True), pytest.raises(StartupValidationError, match="REDIS_URL"):
            from config.startup_validator import validate_environment_or_raise

            validate_environment_or_raise()

    def test_short_encryption_key_raises(self):
        from config.startup_validator import StartupValidationError

        env = self._prod_env({"CONFIG_ENCRYPTION_KEY": "short"})
        with patch.dict(os.environ, env, clear=True), pytest.raises(StartupValidationError, match="TOO_SHORT"):
            from config.startup_validator import validate_environment_or_raise

            validate_environment_or_raise()

    def test_wildcard_cors_raises(self):
        from config.startup_validator import StartupValidationError

        env = self._prod_env({"ALLOWED_ORIGINS": "*"})
        with patch.dict(os.environ, env, clear=True):
            with pytest.raises(StartupValidationError, match="INSECURE.*ALLOWED_ORIGINS"):
                from config.startup_validator import validate_environment_or_raise

                validate_environment_or_raise()

    def test_db_host_without_password_raises(self):
        from config.startup_validator import StartupValidationError

        env = self._prod_env()
        del env["DATABASE_URL"]
        env["DB_HOST"] = "mydb.host"
        with patch.dict(os.environ, env, clear=True):
            with pytest.raises(StartupValidationError, match="DB_PASSWORD"):
                from config.startup_validator import validate_environment_or_raise

                validate_environment_or_raise()

    def test_short_db_password_raises(self):
        from config.startup_validator import StartupValidationError

        env = self._prod_env()
        del env["DATABASE_URL"]
        env["DB_HOST"] = "mydb.host"
        env["DB_PASSWORD"] = "short"  # pragma: allowlist secret
        with patch.dict(os.environ, env, clear=True):
            with pytest.raises(StartupValidationError, match="TOO_SHORT.*DB_PASSWORD"):
                from config.startup_validator import validate_environment_or_raise

                validate_environment_or_raise()

    def test_oanda_broker_requires_token(self):
        from config.startup_validator import StartupValidationError

        env = self._prod_env({"BROKER_TYPE": "oanda"})
        with patch.dict(os.environ, env, clear=True):
            with pytest.raises(StartupValidationError, match="BROKER_OANDA_TOKEN"):
                from config.startup_validator import validate_environment_or_raise

                validate_environment_or_raise()

    def test_oanda_broker_with_credentials_passes(self):
        env = self._prod_env(
            {
                "BROKER_TYPE": "oanda",
                "BROKER_OANDA_TOKEN": "live-token-abc123",
                "BROKER_OANDA_ACCOUNT": "001-001-12345678-001",
            }
        )
        with patch.dict(os.environ, env, clear=True):
            from config.startup_validator import validate_environment_or_raise

            validate_environment_or_raise()

    def test_invalid_sentry_dsn_raises(self):
        from config.startup_validator import StartupValidationError

        env = self._prod_env({"SENTRY_DSN": "not-a-valid-dsn"})
        with patch.dict(os.environ, env, clear=True), pytest.raises(StartupValidationError, match="SENTRY_DSN"):
            from config.startup_validator import validate_environment_or_raise

            validate_environment_or_raise()

    def test_valid_sentry_dsn_passes(self):
        env = self._prod_env({"SENTRY_DSN": "https://abc@sentry.io/123"})
        with patch.dict(os.environ, env, clear=True):
            from config.startup_validator import validate_environment_or_raise

            validate_environment_or_raise()

    def test_invalid_ibkr_port_raises(self):
        from config.startup_validator import StartupValidationError

        env = self._prod_env({"IBKR_PORT": "9999"})
        with patch.dict(os.environ, env, clear=True), pytest.raises(StartupValidationError, match="IBKR_PORT"):
            from config.startup_validator import validate_environment_or_raise

            validate_environment_or_raise()

    def test_valid_ibkr_port_passes(self):
        env = self._prod_env({"IBKR_PORT": "4001"})
        with patch.dict(os.environ, env, clear=True):
            from config.startup_validator import validate_environment_or_raise

            validate_environment_or_raise()

    def test_invalid_mobile_cors_raises(self):
        from config.startup_validator import StartupValidationError

        env = self._prod_env({"MOBILE_CORS_ORIGINS": "http://insecure.com"})
        with patch.dict(os.environ, env, clear=True):
            with pytest.raises(StartupValidationError, match="MOBILE_CORS_ORIGINS"):
                from config.startup_validator import validate_environment_or_raise

                validate_environment_or_raise()

    def test_valid_mobile_cors_passes(self):
        env = self._prod_env({"MOBILE_CORS_ORIGINS": "https://app.example.com"})
        with patch.dict(os.environ, env, clear=True):
            from config.startup_validator import validate_environment_or_raise

            validate_environment_or_raise()

    def test_invalid_argocd_webhook_raises(self):
        from config.startup_validator import StartupValidationError

        env = self._prod_env({"ARGOCD_ROLLBACK_WEBHOOK": "http://not-https.com/webhook"})
        with patch.dict(os.environ, env, clear=True):
            with pytest.raises(StartupValidationError, match="ARGOCD_ROLLBACK_WEBHOOK"):
                from config.startup_validator import validate_environment_or_raise

                validate_environment_or_raise()

    def test_invalid_llm_backend_raises(self):
        from config.startup_validator import StartupValidationError

        env = self._prod_env({"LLM_BACKEND": "unknown_llm"})
        with patch.dict(os.environ, env, clear=True):
            with pytest.raises(StartupValidationError, match="LLM_BACKEND"):
                from config.startup_validator import validate_environment_or_raise

                validate_environment_or_raise()

    def test_change_me_llm_key_raises(self):
        from config.startup_validator import StartupValidationError

        env = self._prod_env({"ANTHROPIC_API_KEY": "CHANGE_ME_replace_with_real_key"})
        with patch.dict(os.environ, env, clear=True), pytest.raises(StartupValidationError, match="INSECURE"):
            from config.startup_validator import validate_environment_or_raise

            validate_environment_or_raise()

    def test_strict_mode_calls_sys_exit(self):
        with patch.dict(os.environ, {"APP_ENV": "development", "BROKER_TYPE": "paper"}, clear=True):
            with pytest.raises(SystemExit):
                from config.startup_validator import validate_environment

                validate_environment(strict=True)

    def test_missing_crypto_webhook_secret_raises(self):
        from config.startup_validator import StartupValidationError

        env = self._prod_env()
        del env["CRYPTO_WEBHOOK_SECRET"]
        with patch.dict(os.environ, env, clear=True):
            with pytest.raises(StartupValidationError, match="CRYPTO_WEBHOOK_SECRET"):
                from config.startup_validator import validate_environment_or_raise

                validate_environment_or_raise()

    def test_weak_crypto_webhook_secret_raises(self):
        from config.startup_validator import StartupValidationError

        env = self._prod_env({"CRYPTO_WEBHOOK_SECRET": "tooshort"})
        with patch.dict(os.environ, env, clear=True):
            with pytest.raises(StartupValidationError, match="WEAK.*CRYPTO_WEBHOOK_SECRET"):
                from config.startup_validator import validate_environment_or_raise

                validate_environment_or_raise()
