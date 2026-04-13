# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
api/two_factor.py
=================
Two-Factor Authentication (TOTP) endpoints.

Routes
------
POST /api/2fa/setup        — generate TOTP secret + QR URI (auth required)
POST /api/2fa/verify       — verify code and activate 2FA (auth required)
POST /api/2fa/disable      — disable 2FA (auth required, code required)
GET  /api/2fa/backup-codes — generate one-time backup codes (auth required)
GET  /api/2fa/status       — check whether 2FA is enabled (auth required)

All user_id values are taken from the JWT — never from the request body —
to prevent one user from modifying another's 2FA state.

Persistence: db_store (configurations table) with in-memory fallback.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import logging
import secrets
import struct
import time

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from api.auth import TokenPayload, get_current_user
from api.db_store import db_delete, db_get, db_set

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/2fa", tags=["Two-Factor Auth"])

# ── In-memory fallback (used when DB unavailable) ─────────────────────────────
_secrets_mem: dict[str, str] = {}
_enabled_mem: dict[str, bool] = {}
_backup_codes_mem: dict[str, list] = {}

_KEY_SECRET = "2fa:secret:{}"  # nosec B105 - Redis key template, not a password  # pragma: allowlist secret
_KEY_ENABLED = "2fa:enabled:{}"
_KEY_BACKUP = "2fa:backup:{}"


# ── Persistence helpers ───────────────────────────────────────────────────────


def _get_secret(user_id: str) -> str | None:
    val = db_get(_KEY_SECRET.format(user_id))
    if val is not None:
        return str(val)
    return _secrets_mem.get(user_id)


def _set_secret(user_id: str, secret: str) -> None:
    _secrets_mem[user_id] = secret
    db_set(_KEY_SECRET.format(user_id), secret, changed_by="2fa")


def _del_secret(user_id: str) -> None:
    _secrets_mem.pop(user_id, None)
    db_delete(_KEY_SECRET.format(user_id))


def _get_enabled(user_id: str) -> bool:
    val = db_get(_KEY_ENABLED.format(user_id))
    if val is not None:
        return bool(val)
    return _enabled_mem.get(user_id, False)


def _set_enabled(user_id: str, value: bool) -> None:
    _enabled_mem[user_id] = value
    db_set(_KEY_ENABLED.format(user_id), value, changed_by="2fa")


def _get_backup_codes(user_id: str) -> list:
    val = db_get(_KEY_BACKUP.format(user_id))
    if isinstance(val, list):
        return val
    return _backup_codes_mem.get(user_id, [])


def _set_backup_codes(user_id: str, codes: list) -> None:
    _backup_codes_mem[user_id] = codes
    db_set(_KEY_BACKUP.format(user_id), codes, changed_by="2fa")


def _del_backup_codes(user_id: str) -> None:
    _backup_codes_mem.pop(user_id, None)
    db_delete(_KEY_BACKUP.format(user_id))


# ── TOTP helpers (RFC 6238, SHA-1, 30 s, 6 digits) ───────────────────────────


def _base32_secret() -> str:
    raw = secrets.token_bytes(20)
    return base64.b32encode(raw).decode().rstrip("=")


def _totp(secret_b32: str, t: int | None = None) -> str:
    if t is None:
        t = int(time.time()) // 30
    key = base64.b32decode(secret_b32 + "=" * (-len(secret_b32) % 8))
    msg = struct.pack(">Q", t)
    # nosec B324 — SHA-1 is mandated by RFC 6238 (TOTP) and RFC 4226 (HOTP).
    # All TOTP authenticator apps (Google Authenticator, Authy, etc.) require
    # HMAC-SHA1 for interoperability.  This is not a password hash.
    h = hmac.new(key, msg, hashlib.sha1).digest()  # nosec B324
    offset = h[-1] & 0x0F
    code = struct.unpack(">I", h[offset : offset + 4])[0] & 0x7FFFFFFF
    return str(code % 1_000_000).zfill(6)


def _verify_totp(secret_b32: str, code: str, window: int = 1) -> bool:
    """Accept codes within ±window time steps to handle clock skew."""
    t = int(time.time()) // 30
    return any(_totp(secret_b32, t + i) == code for i in range(-window, window + 1))


def _verify_backup_code(user_id: str, code: str) -> bool:
    """Consume a backup code (one-time use). Returns True if valid."""
    codes = _get_backup_codes(user_id)
    code_upper = code.upper()
    if code_upper in codes:
        codes.remove(code_upper)
        _set_backup_codes(user_id, codes)
        return True
    return False


def _otpauth_uri(secret: str, user_id: str, issuer: str = "HOPEFX") -> str:
    return f"otpauth://totp/{issuer}:{user_id}?secret={secret}&issuer={issuer}&algorithm=SHA1&digits=6&period=30"


# ── Models ────────────────────────────────────────────────────────────────────


class SetupResponse(BaseModel):
    secret: str
    otpauth_uri: str
    qr_url: str


class VerifyRequest(BaseModel):
    code: str = Field(
        ...,
        min_length=6,
        max_length=8,
        description="6-digit TOTP code or 8-character backup code",
    )


class VerifyResponse(BaseModel):
    success: bool
    message: str


class StatusResponse(BaseModel):
    user_id: str
    enabled: bool
    backup_codes_remaining: int


class BackupCodesResponse(BaseModel):
    codes: list[str]
    warning: str


# ── Endpoints ─────────────────────────────────────────────────────────────────


@router.post("/setup", response_model=SetupResponse)
async def setup_2fa(
    user: TokenPayload = Depends(get_current_user),
) -> SetupResponse:
    """
    Generate a TOTP secret and QR code URI for the authenticated user.

    Scan the QR code with an authenticator app (Google Authenticator, Authy, etc.)
    then call POST /api/2fa/verify with the first code to activate 2FA.
    The secret is stored but 2FA is not active until verified.
    """
    secret = _base32_secret()
    _set_secret(user.sub, secret)
    _set_enabled(user.sub, False)

    uri = _otpauth_uri(secret, user.sub)
    qr_url = f"https://api.qrserver.com/v1/create-qr-code/?size=200x200&data={uri}"

    logger.info("2FA setup initiated for user %s", user.sub)
    return SetupResponse(secret=secret, otpauth_uri=uri, qr_url=qr_url)


@router.post("/verify", response_model=VerifyResponse)
async def verify_2fa(
    req: VerifyRequest,
    user: TokenPayload = Depends(get_current_user),
) -> VerifyResponse:
    """
    Verify a TOTP code and activate 2FA for the authenticated user.

    Also accepts an 8-character backup code (consumed on use).
    """
    secret = _get_secret(user.sub)
    if not secret:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="2FA not set up. Call POST /api/2fa/setup first.",
        )

    # Backup code path (8 hex chars)
    if len(req.code) == 8 and _verify_backup_code(user.sub, req.code):
        logger.info("2FA verified via backup code for user %s", user.sub)
        return VerifyResponse(success=True, message="Verified via backup code.")

    # TOTP path
    if _verify_totp(secret, req.code):
        _set_enabled(user.sub, True)
        logger.info("2FA activated for user %s", user.sub)
        return VerifyResponse(success=True, message="2FA activated successfully.")

    return VerifyResponse(success=False, message="Invalid code. Please try again.")


@router.post("/disable", response_model=VerifyResponse)
async def disable_2fa(
    req: VerifyRequest,
    user: TokenPayload = Depends(get_current_user),
) -> VerifyResponse:
    """
    Disable 2FA after verifying the current TOTP code or a backup code.
    Clears the stored secret and all backup codes.
    """
    if not _get_enabled(user.sub):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="2FA is not enabled for this account.",
        )

    secret = _get_secret(user.sub)
    if not secret:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="2FA state inconsistent — no secret found.",
        )

    valid = (len(req.code) == 8 and _verify_backup_code(user.sub, req.code)) or (_verify_totp(secret, req.code))

    if valid:
        _set_enabled(user.sub, False)
        _del_secret(user.sub)
        _del_backup_codes(user.sub)
        logger.info("2FA disabled for user %s", user.sub)
        return VerifyResponse(success=True, message="2FA disabled.")

    return VerifyResponse(success=False, message="Invalid code.")


@router.get("/backup-codes", response_model=BackupCodesResponse)
async def get_backup_codes(
    user: TokenPayload = Depends(get_current_user),
) -> BackupCodesResponse:
    """
    Generate 8 one-time backup codes for account recovery.

    Replaces any previously generated codes. Each code can only be used once.
    """
    if not _get_enabled(user.sub):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="2FA must be enabled before generating backup codes.",
        )

    codes = [secrets.token_hex(4).upper() for _ in range(8)]
    _set_backup_codes(user.sub, codes)
    logger.info("Backup codes regenerated for user %s", user.sub)
    return BackupCodesResponse(
        codes=codes,
        warning="Store these codes securely. Each can only be used once.",
    )


@router.get("/status", response_model=StatusResponse)
async def get_2fa_status(
    user: TokenPayload = Depends(get_current_user),
) -> StatusResponse:
    """Return whether 2FA is enabled and how many backup codes remain."""
    return StatusResponse(
        user_id=user.sub,
        enabled=_get_enabled(user.sub),
        backup_codes_remaining=len(_get_backup_codes(user.sub)),
    )
