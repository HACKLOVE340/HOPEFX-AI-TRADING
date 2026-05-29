# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
tests/test_jwt_pyjwt.py
=======================
Verify auth/jwt.py uses PyJWT (not python-jose) and that token
encode/decode and password hashing work correctly.
"""

from __future__ import annotations

import importlib.util
import os
import pathlib
import time

import pytest

os.environ.setdefault("SECURITY_JWT_SECRET", "test-only-jwt-secret-key-minimum-32-chars!!")
os.environ.setdefault("JWT_SECRET_KEY", "test-only-jwt-secret-key-minimum-32-chars!!")

# Load auth/jwt.py directly to avoid auth/__init__.py pulling in EmailStr
_spec = importlib.util.spec_from_file_location("auth_jwt", pathlib.Path(__file__).parent.parent / "auth" / "jwt.py")
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)

create_access_token = _mod.create_access_token
verify_token = _mod.verify_token
hash_password = _mod.hash_password
verify_password = _mod.verify_password


# ── Helpers ───────────────────────────────────────────────────────────────────


class _FakeExc(Exception):
    status_code = 401


_CRED_EXC = _FakeExc("invalid credentials")


# ── Token tests ───────────────────────────────────────────────────────────────


def test_jose_not_imported():
    """python-jose must not be present in the module's imports."""
    # jose should not be importable (or at least not used by auth/jwt.py)
    src = pathlib.Path(__file__).parent.parent / "auth" / "jwt.py"
    content = src.read_text()
    assert "from jose" not in content, "auth/jwt.py still imports from jose"
    assert "import jose" not in content, "auth/jwt.py still imports jose"


def test_pyjwt_used():
    """auth/jwt.py must import the PyJWT top-level 'jwt' package."""
    src = pathlib.Path(__file__).parent.parent / "auth" / "jwt.py"
    content = src.read_text()
    assert "import jwt" in content, "auth/jwt.py does not import PyJWT"


def test_create_and_verify_token():
    token = create_access_token({"sub": "user-abc"})
    assert isinstance(token, str)
    result = verify_token(token, _CRED_EXC)
    assert result == "user-abc"


def test_token_with_custom_expiry():
    from datetime import timedelta

    token = create_access_token({"sub": "user-xyz"}, expires_delta=timedelta(hours=1))
    result = verify_token(token, _CRED_EXC)
    assert result == "user-xyz"


def test_expired_token_raises():
    """A token with exp in the past must be rejected with the credentials_exception."""
    import jwt as pyjwt

    secret = os.environ["JWT_SECRET_KEY"]
    expired_payload = {"sub": "user-exp", "exp": int(time.time()) - 10}
    token = pyjwt.encode(expired_payload, secret, algorithm="HS256")
    # verify_token raises the credentials_exception it was given (_FakeExc here)
    with pytest.raises(_FakeExc):
        verify_token(token, _CRED_EXC)


def test_tampered_token_raises():
    token = create_access_token({"sub": "user-tamper"})
    bad_token = token[:-4] + "XXXX"
    with pytest.raises(_FakeExc):
        verify_token(bad_token, _CRED_EXC)


def test_missing_sub_raises():
    """Token without 'sub' claim must be rejected."""
    import jwt as pyjwt

    secret = os.environ["JWT_SECRET_KEY"]
    token = pyjwt.encode({"exp": int(time.time()) + 3600}, secret, algorithm="HS256")
    with pytest.raises(_FakeExc):
        verify_token(token, _CRED_EXC)


# ── Password hashing tests ────────────────────────────────────────────────────


def test_hash_and_verify_password():
    hashed = hash_password("MySecureP@ss1")
    assert hashed != "MySecureP@ss1"
    assert verify_password("MySecureP@ss1", hashed)


def test_wrong_password_rejected():
    hashed = hash_password("correct-horse-battery")
    assert not verify_password("wrong-password", hashed)


def test_hash_is_not_deterministic():
    """bcrypt must produce different hashes for the same input (salted)."""
    h1 = hash_password("same-password")
    h2 = hash_password("same-password")
    assert h1 != h2, "Password hashes must be salted (non-deterministic)"
