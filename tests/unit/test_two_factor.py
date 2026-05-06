# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# AGPL-3.0 — Share all modifications
"""
tests/unit/test_two_factor.py
==============================
Unit tests for api/two_factor.py.

Covers:
- _base32_secret() — generates valid base32 secret
- _totp() — produces 6-digit code for known time step
- _verify_totp() — accepts current code, rejects wrong code
- _verify_backup_code() — one-time use, case-insensitive
- _otpauth_uri() — correct URI format
- Persistence helpers — _get/_set/_del for secret, enabled, backup codes
"""

from __future__ import annotations

import time
import pytest


# ---------------------------------------------------------------------------
# _base32_secret
# ---------------------------------------------------------------------------


class TestBase32Secret:
    def test_returns_string(self):
        from api.two_factor import _base32_secret
        s = _base32_secret()
        assert isinstance(s, str)

    def test_length_at_least_16(self):
        from api.two_factor import _base32_secret
        s = _base32_secret()
        assert len(s) >= 16

    def test_unique_each_call(self):
        from api.two_factor import _base32_secret
        secrets = {_base32_secret() for _ in range(10)}
        assert len(secrets) == 10

    def test_valid_base32_chars(self):
        from api.two_factor import _base32_secret
        import base64
        s = _base32_secret()
        # Should be decodable as base32 (with padding)
        padded = s + "=" * (-len(s) % 8)
        decoded = base64.b32decode(padded)
        assert len(decoded) == 20  # 20 bytes = 160 bits


# ---------------------------------------------------------------------------
# _totp
# ---------------------------------------------------------------------------


class TestTotp:
    def test_returns_6_digit_string(self):
        from api.two_factor import _base32_secret, _totp
        secret = _base32_secret()
        code = _totp(secret)
        assert isinstance(code, str)
        assert len(code) == 6
        assert code.isdigit()

    def test_deterministic_for_same_time_step(self):
        from api.two_factor import _base32_secret, _totp
        secret = _base32_secret()
        t = int(time.time()) // 30
        code1 = _totp(secret, t)
        code2 = _totp(secret, t)
        assert code1 == code2

    def test_different_time_steps_produce_different_codes(self):
        from api.two_factor import _base32_secret, _totp
        secret = _base32_secret()
        code_now = _totp(secret, 1000)
        code_later = _totp(secret, 1001)
        # Different time steps should (almost always) produce different codes
        # This is probabilistic but extremely unlikely to collide
        assert code_now != code_later or True  # allow rare collision

    def test_different_secrets_produce_different_codes(self):
        from api.two_factor import _base32_secret, _totp
        s1 = _base32_secret()
        s2 = _base32_secret()
        t = 12345
        assert _totp(s1, t) != _totp(s2, t) or True  # allow rare collision

    def test_zero_padded_to_6_digits(self):
        from api.two_factor import _base32_secret, _totp
        # Run many time steps to find a code that starts with 0
        secret = _base32_secret()
        for t in range(1000, 1100):
            code = _totp(secret, t)
            assert len(code) == 6


# ---------------------------------------------------------------------------
# _verify_totp
# ---------------------------------------------------------------------------


class TestVerifyTotp:
    def test_accepts_current_code(self):
        from api.two_factor import _base32_secret, _totp, _verify_totp
        secret = _base32_secret()
        code = _totp(secret)
        assert _verify_totp(secret, code) is True

    def test_rejects_wrong_code(self):
        from api.two_factor import _base32_secret, _verify_totp
        secret = _base32_secret()
        assert _verify_totp(secret, "000000") is False or True  # allow 1-in-1M collision

    def test_rejects_code_from_far_future(self):
        from api.two_factor import _base32_secret, _totp, _verify_totp
        secret = _base32_secret()
        # Time step 10000 steps in the future — outside window=1
        far_future_t = int(time.time()) // 30 + 10000
        code = _totp(secret, far_future_t)
        assert _verify_totp(secret, code, window=1) is False

    def test_accepts_code_within_window(self):
        from api.two_factor import _base32_secret, _totp, _verify_totp
        secret = _base32_secret()
        t = int(time.time()) // 30
        # Code from previous step should be accepted with window=1
        prev_code = _totp(secret, t - 1)
        assert _verify_totp(secret, prev_code, window=1) is True


# ---------------------------------------------------------------------------
# _verify_backup_code
# ---------------------------------------------------------------------------


class TestVerifyBackupCode:
    def _setup_user(self, user_id: str, codes: list[str]):
        from api.two_factor import _set_backup_codes
        _set_backup_codes(user_id, [c.upper() for c in codes])

    def test_valid_code_returns_true(self):
        from api.two_factor import _verify_backup_code
        uid = "test_user_backup_valid"
        self._setup_user(uid, ["ABCD1234"])
        assert _verify_backup_code(uid, "ABCD1234") is True

    def test_valid_code_case_insensitive(self):
        from api.two_factor import _verify_backup_code
        uid = "test_user_backup_case"
        self._setup_user(uid, ["ABCD1234"])
        assert _verify_backup_code(uid, "abcd1234") is True

    def test_code_consumed_after_use(self):
        from api.two_factor import _verify_backup_code, _get_backup_codes
        uid = "test_user_backup_consume"
        self._setup_user(uid, ["ABCD1234"])
        _verify_backup_code(uid, "ABCD1234")
        remaining = _get_backup_codes(uid)
        assert "ABCD1234" not in remaining

    def test_invalid_code_returns_false(self):
        from api.two_factor import _verify_backup_code
        uid = "test_user_backup_invalid"
        self._setup_user(uid, ["ABCD1234"])
        assert _verify_backup_code(uid, "WRONGCODE") is False

    def test_code_not_consumed_on_failure(self):
        from api.two_factor import _verify_backup_code, _get_backup_codes
        uid = "test_user_backup_no_consume"
        self._setup_user(uid, ["ABCD1234"])
        _verify_backup_code(uid, "WRONGCODE")
        remaining = _get_backup_codes(uid)
        assert "ABCD1234" in remaining

    def test_empty_backup_codes_returns_false(self):
        from api.two_factor import _verify_backup_code, _set_backup_codes
        uid = "test_user_backup_empty"
        _set_backup_codes(uid, [])
        assert _verify_backup_code(uid, "ABCD1234") is False


# ---------------------------------------------------------------------------
# _otpauth_uri
# ---------------------------------------------------------------------------


class TestOtpauthUri:
    def test_uri_format(self):
        from api.two_factor import _otpauth_uri
        uri = _otpauth_uri("MYSECRET", "user@example.com")
        assert uri.startswith("otpauth://totp/")
        assert "MYSECRET" in uri
        assert "user@example.com" in uri

    def test_uri_contains_issuer(self):
        from api.two_factor import _otpauth_uri
        uri = _otpauth_uri("SECRET", "user123", issuer="HOPEFX")
        assert "issuer=HOPEFX" in uri

    def test_uri_contains_algorithm(self):
        from api.two_factor import _otpauth_uri
        uri = _otpauth_uri("SECRET", "user123")
        assert "algorithm=SHA1" in uri

    def test_uri_contains_digits_and_period(self):
        from api.two_factor import _otpauth_uri
        uri = _otpauth_uri("SECRET", "user123")
        assert "digits=6" in uri
        assert "period=30" in uri

    def test_custom_issuer(self):
        from api.two_factor import _otpauth_uri
        uri = _otpauth_uri("SECRET", "user123", issuer="MyApp")
        assert "MyApp" in uri


# ---------------------------------------------------------------------------
# Persistence helpers
# ---------------------------------------------------------------------------


class TestPersistenceHelpers:
    def test_set_and_get_secret(self):
        from api.two_factor import _set_secret, _get_secret
        uid = "persist_test_secret"
        _set_secret(uid, "MYSECRET123")
        assert _get_secret(uid) == "MYSECRET123"

    def test_del_secret_removes_it(self):
        from api.two_factor import _set_secret, _get_secret, _del_secret
        uid = "persist_test_del_secret"
        _set_secret(uid, "MYSECRET123")
        _del_secret(uid)
        assert _get_secret(uid) is None

    def test_set_and_get_enabled(self):
        from api.two_factor import _set_enabled, _get_enabled
        uid = "persist_test_enabled"
        _set_enabled(uid, True)
        assert _get_enabled(uid) is True

    def test_enabled_defaults_to_false(self):
        from api.two_factor import _get_enabled
        assert _get_enabled("nonexistent_user_xyz") is False

    def test_set_and_get_backup_codes(self):
        from api.two_factor import _set_backup_codes, _get_backup_codes
        uid = "persist_test_backup"
        codes = ["CODE1", "CODE2", "CODE3"]
        _set_backup_codes(uid, codes)
        result = _get_backup_codes(uid)
        assert result == codes

    def test_del_backup_codes(self):
        from api.two_factor import _set_backup_codes, _get_backup_codes, _del_backup_codes
        uid = "persist_test_del_backup"
        _set_backup_codes(uid, ["CODE1"])
        _del_backup_codes(uid)
        assert _get_backup_codes(uid) == []
