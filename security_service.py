# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
security_service.py
===================
Public facade for all authentication and security operations.

Re-exports the real implementations from auth/ and security/ so that
external callers have a single stable import point.  Previously this
file was a 2-line comment stub — any import returned an empty module.

Usage
-----
    from security_service import SecurityService, create_access_token, verify_token

    svc = SecurityService()
    token = svc.create_access_token({"sub": user_id})
    payload = svc.verify_token(token)
    hashed = svc.hash_password("my_password")
    ok = svc.verify_password("my_password", hashed)
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import os
import secrets
import uuid
from datetime import datetime, timedelta, timezone

UTC = timezone.utc
from typing import Any

logger = logging.getLogger(__name__)

try:
    import jwt as _jwt

    _JWT_AVAILABLE = True
except ImportError:
    _jwt = None
    _JWT_AVAILABLE = False
    logger.warning("PyJWT not installed — JWT operations will raise ImportError")

try:
    from passlib.context import CryptContext as _CryptContext

    _PASSLIB_AVAILABLE = True
except ImportError:
    _CryptContext = None
    _PASSLIB_AVAILABLE = False
    logger.warning("passlib not installed — password hashing falls back to PBKDF2-HMAC-SHA256")

_SECRET_KEY: str = os.getenv("SECRET_KEY", "")
_ALGORITHM: str = os.getenv("JWT_ALGORITHM", "HS256")
_ACCESS_TOKEN_EXPIRE_MINUTES: int = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "15"))
_REFRESH_TOKEN_EXPIRE_DAYS: int = int(os.getenv("REFRESH_TOKEN_EXPIRE_DAYS", "7"))
_PBKDF2_ITERATIONS: int = 600_000
_PBKDF2_HASH: str = "sha256"


class SecurityService:
    """
    Centralised security service.

    Provides:
    - JWT access and refresh token creation / verification
    - Password hashing (bcrypt via passlib, PBKDF2-HMAC-SHA256 fallback)
    - Password verification with constant-time comparison
    - Secure random token generation (email verification, password reset)
    """

    def __init__(
        self,
        secret_key: str | None = None,
        algorithm: str = _ALGORITHM,
        access_token_expire_minutes: int = _ACCESS_TOKEN_EXPIRE_MINUTES,
        refresh_token_expire_days: int = _REFRESH_TOKEN_EXPIRE_DAYS,
    ) -> None:
        self._secret = secret_key or _SECRET_KEY
        if not self._secret:
            raise ValueError(
                "SecurityService: SECRET_KEY is not set. "
                "Set the SECRET_KEY environment variable to a cryptographically "
                'random value: python3 -c "import secrets; print(secrets.token_hex(32))"'
            )
        self._algorithm = algorithm
        self._access_expire = timedelta(minutes=access_token_expire_minutes)
        self._refresh_expire = timedelta(days=refresh_token_expire_days)
        self._pwd_context = _CryptContext(schemes=["bcrypt"], deprecated="auto") if _PASSLIB_AVAILABLE else None

    # ── Token creation ────────────────────────────────────────────────────────

    def create_access_token(self, data: dict[str, Any], expires_delta: timedelta | None = None) -> str:
        """Create a signed JWT access token. Payload must include 'sub'."""
        if not _JWT_AVAILABLE:
            raise ImportError("PyJWT is required: pip install pyjwt")
        payload = data.copy()
        now = datetime.now(UTC)
        payload.update(
            {
                "iat": now,
                "exp": now + (expires_delta or self._access_expire),
                "jti": str(uuid.uuid4()),
                "type": "access",
            }
        )
        return _jwt.encode(payload, self._secret, algorithm=self._algorithm)

    def create_refresh_token(self, data: dict[str, Any], expires_delta: timedelta | None = None) -> str:
        """Create a signed JWT refresh token (longer-lived)."""
        if not _JWT_AVAILABLE:
            raise ImportError("PyJWT is required: pip install pyjwt")
        payload = data.copy()
        now = datetime.now(UTC)
        payload.update(
            {
                "iat": now,
                "exp": now + (expires_delta or self._refresh_expire),
                "jti": str(uuid.uuid4()),
                "type": "refresh",
            }
        )
        return _jwt.encode(payload, self._secret, algorithm=self._algorithm)

    # ── Token verification ────────────────────────────────────────────────────

    def verify_token(self, token: str, expected_type: str = "access") -> dict[str, Any]:
        """
        Decode and validate a JWT token.

        Raises ValueError on expiry, invalid signature, or type mismatch.
        """
        if not _JWT_AVAILABLE:
            raise ImportError("PyJWT is required: pip install pyjwt")
        try:
            payload: dict[str, Any] = _jwt.decode(
                token,
                self._secret,
                algorithms=[self._algorithm],
                options={"require": ["exp", "iat", "sub", "jti"]},
            )
        except _jwt.ExpiredSignatureError:
            raise ValueError("Token has expired") from None
        except _jwt.InvalidTokenError:
            # Log the specific JWT error server-side; surface only a generic
            # message to callers to avoid leaking token structure details.
            raise ValueError("Invalid token") from None

        if payload.get("type") != expected_type:
            raise ValueError(f"Token type mismatch: expected '{expected_type}', got '{payload.get('type')}'")
        return payload

    def get_token_jti(self, token: str) -> str | None:
        """Extract JTI without full verification — for revocation lookups."""
        if not _JWT_AVAILABLE:
            return None
        try:
            return _jwt.decode(token, options={"verify_signature": False}, algorithms=[self._algorithm]).get("jti")
        except Exception:
            return None

    # ── Password hashing ──────────────────────────────────────────────────────

    def hash_password(self, plain_password: str) -> str:
        """
        Hash a password using bcrypt (passlib) or PBKDF2-HMAC-SHA256 fallback.
        Returns a self-describing hash string safe to store in the database.
        """
        if self._pwd_context is not None:
            return self._pwd_context.hash(plain_password)
        salt = secrets.token_hex(32)
        dk = hashlib.pbkdf2_hmac(_PBKDF2_HASH, plain_password.encode(), salt.encode(), _PBKDF2_ITERATIONS)
        return f"pbkdf2:{_PBKDF2_HASH}:{_PBKDF2_ITERATIONS}${salt}${dk.hex()}"

    def verify_password(self, plain_password: str, hashed_password: str) -> bool:
        """
        Verify a plain password against a stored hash.
        Uses constant-time comparison to prevent timing attacks.
        """
        if self._pwd_context is not None and not hashed_password.startswith("pbkdf2:"):
            try:
                return self._pwd_context.verify(plain_password, hashed_password)
            except Exception:
                return False
        try:
            _, hash_algo, rest = hashed_password.split(":", 2)
            iterations_str, salt, stored_hex = rest.split("$", 2)
            dk = hashlib.pbkdf2_hmac(hash_algo, plain_password.encode(), salt.encode(), int(iterations_str))
            return hmac.compare_digest(dk.hex(), stored_hex)
        except Exception:
            return False

    # ── Secure token generation ───────────────────────────────────────────────

    @staticmethod
    def generate_secure_token(nbytes: int = 32) -> str:
        """Generate a cryptographically secure URL-safe random token."""
        return secrets.token_urlsafe(nbytes)

    @staticmethod
    def generate_numeric_otp(digits: int = 6) -> str:
        """Generate a numeric OTP of the given length."""
        return str(secrets.randbelow(10**digits)).zfill(digits)

    @staticmethod
    def constant_time_compare(a: str, b: str) -> bool:
        """Constant-time string comparison — prevents timing attacks."""
        return hmac.compare_digest(
            a.encode() if isinstance(a, str) else a,
            b.encode() if isinstance(b, str) else b,
        )


# ── Module-level convenience functions ───────────────────────────────────────

_default_service: SecurityService | None = None


def _get_default_service() -> SecurityService:
    global _default_service
    if _default_service is None:
        _default_service = SecurityService()
    return _default_service


def create_access_token(data: dict[str, Any], expires_delta: timedelta | None = None) -> str:
    return _get_default_service().create_access_token(data, expires_delta)


def create_refresh_token(data: dict[str, Any], expires_delta: timedelta | None = None) -> str:
    return _get_default_service().create_refresh_token(data, expires_delta)


def verify_token(token: str, expected_type: str = "access") -> dict[str, Any]:
    return _get_default_service().verify_token(token, expected_type)


def hash_password(plain_password: str) -> str:
    return _get_default_service().hash_password(plain_password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return _get_default_service().verify_password(plain_password, hashed_password)


def generate_secure_token(nbytes: int = 32) -> str:
    return SecurityService.generate_secure_token(nbytes)
