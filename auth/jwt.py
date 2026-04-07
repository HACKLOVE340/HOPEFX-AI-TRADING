# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
import base64
import hashlib
import logging
import os
from datetime import datetime, timedelta, timezone

UTC = timezone.utc

import jwt
from passlib.context import CryptContext

logger = logging.getLogger(__name__)


# JWT signing secret — read from SECURITY_JWT_SECRET (preferred) or JWT_SECRET_KEY.
# No hardcoded fallback: a missing or placeholder secret raises RuntimeError at
# token-creation time so the failure is loud and immediate.
def _load_secret() -> str:
    val = os.environ.get("SECURITY_JWT_SECRET", "").strip() or os.environ.get("JWT_SECRET_KEY", "").strip()
    if not val:
        raise RuntimeError(
            "SECURITY_JWT_SECRET is not set. "
            'Generate one with: python -c "import secrets; logger.info(secrets.token_urlsafe(48))"',
        )
    if len(val) < 32:
        raise RuntimeError(
            f"SECURITY_JWT_SECRET is too short ({len(val)} chars). Must be >=32 characters.",
        )
    if val.startswith("CHANGE_ME"):
        raise RuntimeError(
            "SECURITY_JWT_SECRET contains a placeholder value. Replace it with a real random secret before deploying.",
        )
    return val


# Evaluated lazily so import does not fail in test environments that set the
# env var after module import. Call _get_secret() instead of SECRET_KEY directly.
def _get_secret() -> str:
    return _load_secret()


# Module-level alias kept for backward compatibility with code that reads
# auth.jwt.SECRET_KEY directly — raises RuntimeError if secret is unset.
@property  # type: ignore[misc]
def SECRET_KEY() -> str:
    return _load_secret()


ALGORITHM = "HS256"


def _get_access_token_expire_minutes() -> int:
    """Return the configured access-token lifetime in minutes.

    Reads ACCESS_TOKEN_EXPIRE_MINUTES (same var as auth/service.py) so both
    code paths produce tokens with identical expiry. JWT_EXPIRE_MINUTES is
    accepted as a legacy alias; ACCESS_TOKEN_EXPIRE_MINUTES takes precedence.

    Evaluated at call time so tests can override the env var without
    reloading the module (which would mutate shared module state).
    """
    return int(os.environ.get("ACCESS_TOKEN_EXPIRE_MINUTES") or os.environ.get("JWT_EXPIRE_MINUTES") or "15")


# Module-level alias for code that reads auth.jwt.ACCESS_TOKEN_EXPIRE_MINUTES
# directly. Kept for backward compatibility; prefer _get_access_token_expire_minutes().
ACCESS_TOKEN_EXPIRE_MINUTES = _get_access_token_expire_minutes()

# Password hashing — bcrypt with SHA-256 pre-hash to handle passwords >72 bytes.
#
# bcrypt silently truncates at 72 bytes; SHA-256 pre-hashing avoids that limit
# while keeping the full bcrypt cost factor for brute-force resistance.
#
# passlib 1.7.x + bcrypt 4.x raises ValueError("password cannot be longer than
# 72 bytes") when the *raw* password is passed through passlib's bcrypt handler
# even though our pre-hash always produces a 44-char ASCII string.  The root
# cause is passlib calling bcrypt.checkpw with the raw bytes before our hook
# runs.  We bypass passlib entirely and call bcrypt directly.
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
try:
    import bcrypt as _bcrypt_lib

    _BCRYPT_DIRECT = True
except ImportError:
    _BCRYPT_DIRECT = False


def _prepare_password(password: str) -> bytes:
    """BLAKE2b + base64 encode so bcrypt never sees >72 bytes.

    Returns bytes ready for bcrypt.hashpw / bcrypt.checkpw.
    BLAKE2b(digest_size=32) produces 32 bytes → 44 base64 chars → always < 72 bytes.

    BLAKE2b is used solely as a length-normalisation step before bcrypt, not as
    a standalone password hash.  bcrypt (cost ≥ 12) is the actual hardening
    primitive.  BLAKE2b prevents bcrypt's 72-byte truncation vulnerability for
    long passwords while preserving full input entropy.

    nosec B324 — BLAKE2b here is a pre-processing step, not a password hash.
    The output is immediately passed to bcrypt.hashpw/checkpw which provides
    the actual key-stretching.  Using SHA-256 or SHA-512 instead would be
    equally valid; BLAKE2b is chosen for its speed and lack of length-extension
    vulnerability.
    """
    # BLAKE2b is used solely as a length-normalisation step (bcrypt truncates at
    # 72 bytes).  The digest is immediately passed to bcrypt.hashpw/checkpw
    # which provides the actual key-stretching (cost ≥ 12).
    # codeql[py/weak-sensitive-data-hashing] — not standalone password hashing;
    # bcrypt is the hardening primitive.  nosec B324
    _raw = password.encode("utf-8")
    _normalised = hashlib.blake2b(_raw, digest_size=32).digest()  # nosec B324
    return base64.b64encode(_normalised)  # 44 ASCII bytes — safe for bcrypt


def create_access_token(data: dict, expires_delta: timedelta | None = None) -> str:
    """Encode a JWT access token using PyJWT (HS256)."""
    to_encode = data.copy()
    expire = (
        datetime.now(UTC) + expires_delta
        if expires_delta
        else datetime.now(UTC) + timedelta(minutes=_get_access_token_expire_minutes())
    )
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, _get_secret(), algorithm=ALGORITHM)


def verify_token(token: str, credentials_exception):
    """Decode and validate a JWT token. Raises credentials_exception on failure."""
    try:
        payload = jwt.decode(token, _get_secret(), algorithms=[ALGORITHM])
        username: str = payload.get("sub")
        if username is None:
            raise credentials_exception
        return username
    except jwt.InvalidTokenError:
        raise credentials_exception from None


def decode_access_token(token: str) -> dict:
    """
    Decode and validate an access token. Returns the full payload dict.

    Raises jwt.InvalidTokenError (or subclass) on any failure:
      - jwt.ExpiredSignatureError  — token has expired
      - jwt.InvalidTokenError      — bad signature, malformed, wrong type

    Used by GraphQL context auth and WebSocket auth gate.
    """
    payload = jwt.decode(token, _get_secret(), algorithms=[ALGORITHM])
    if payload.get("type") != "access":
        raise jwt.InvalidTokenError("Not an access token")
    # Check revocation list (Redis-backed blacklist)
    jti = payload.get("jti")
    if jti:
        try:
            from auth.service import is_access_token_revoked

            if is_access_token_revoked(jti):
                raise jwt.InvalidTokenError("Token has been revoked")
        except ImportError:
            ...  # nosec B110
    return payload


def hash_password(password: str) -> str:
    """Hash a password with bcrypt (SHA-256 pre-hash, cost factor 12)."""
    prepared = _prepare_password(password)
    if _BCRYPT_DIRECT:
        return _bcrypt_lib.hashpw(prepared, _bcrypt_lib.gensalt(rounds=12)).decode("utf-8")
    # passlib fallback (older bcrypt versions)
    return pwd_context.hash(prepared.decode("ascii"))


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a plaintext password against a stored bcrypt hash."""
    prepared = _prepare_password(plain_password)
    if _BCRYPT_DIRECT:
        try:
            return _bcrypt_lib.checkpw(prepared, hashed_password.encode("utf-8"))
        except (ValueError, TypeError) as exc:
            logger.warning("bcrypt verification failed: %s", exc)
            return False
    return pwd_context.verify(prepared.decode("ascii"), hashed_password)
