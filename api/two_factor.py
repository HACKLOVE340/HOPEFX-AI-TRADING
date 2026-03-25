"""
api/two_factor.py
=================
Two-Factor Authentication (TOTP) endpoints.

Routes
------
POST /api/2fa/setup          — generate TOTP secret + QR code URI for user
POST /api/2fa/verify         — verify a TOTP code and activate 2FA
POST /api/2fa/disable        — disable 2FA for user
GET  /api/2fa/backup-codes   — generate one-time backup codes
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import logging
import os
import secrets
import struct
import time
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/2fa", tags=["Two-Factor Auth"])

# In-memory store — replace with DB in production
_secrets: dict[str, str] = {}
_enabled: dict[str, bool] = {}
_backup_codes: dict[str, list[str]] = {}


# ── TOTP helpers ──────────────────────────────────────────────────────────────

def _base32_secret() -> str:
    """Generate a random base32-encoded TOTP secret."""
    raw = secrets.token_bytes(20)
    return base64.b32encode(raw).decode().rstrip("=")


def _totp(secret_b32: str, t: Optional[int] = None) -> str:
    """Compute TOTP code (RFC 6238, SHA-1, 30s window, 6 digits)."""
    if t is None:
        t = int(time.time()) // 30
    key = base64.b32decode(secret_b32 + "=" * (-len(secret_b32) % 8))
    msg = struct.pack(">Q", t)
    h = hmac.new(key, msg, hashlib.sha1).digest()
    offset = h[-1] & 0x0F
    code = struct.unpack(">I", h[offset:offset + 4])[0] & 0x7FFFFFFF
    return str(code % 1_000_000).zfill(6)


def _verify_totp(secret_b32: str, code: str, window: int = 1) -> bool:
    """Verify TOTP code allowing ±window time steps."""
    t = int(time.time()) // 30
    return any(_totp(secret_b32, t + i) == code for i in range(-window, window + 1))


def _otpauth_uri(secret: str, user_id: str, issuer: str = "HOPEFX") -> str:
    return (
        f"otpauth://totp/{issuer}:{user_id}"
        f"?secret={secret}&issuer={issuer}&algorithm=SHA1&digits=6&period=30"
    )


# ── Models ────────────────────────────────────────────────────────────────────

class SetupRequest(BaseModel):
    user_id: str = Field(..., min_length=1)


class SetupResponse(BaseModel):
    secret: str
    otpauth_uri: str
    qr_placeholder: str  # In production: base64 PNG from qrcode library


class VerifyRequest(BaseModel):
    user_id: str
    code: str = Field(..., min_length=6, max_length=6)


class VerifyResponse(BaseModel):
    success: bool
    message: str


class DisableRequest(BaseModel):
    user_id: str
    code: str = Field(..., min_length=6, max_length=6)


class BackupCodesResponse(BaseModel):
    codes: List[str]


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post("/setup", response_model=SetupResponse)
async def setup_2fa(req: SetupRequest) -> SetupResponse:
    """Generate a TOTP secret and QR code URI for the user."""
    secret = _base32_secret()
    _secrets[req.user_id] = secret
    _enabled[req.user_id] = False  # not active until verified

    uri = _otpauth_uri(secret, req.user_id)

    # In production: generate actual QR PNG with `qrcode` library
    # For now return the URI so the frontend can render it via a QR library
    return SetupResponse(
        secret=secret,
        otpauth_uri=uri,
        qr_placeholder=f"https://api.qrserver.com/v1/create-qr-code/?size=200x200&data={uri}",
    )


@router.post("/verify", response_model=VerifyResponse)
async def verify_2fa(req: VerifyRequest) -> VerifyResponse:
    """Verify a TOTP code and activate 2FA for the user."""
    secret = _secrets.get(req.user_id)
    if not secret:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="2FA not set up for this user")

    if _verify_totp(secret, req.code):
        _enabled[req.user_id] = True
        logger.info("2FA activated for user %s", req.user_id)
        return VerifyResponse(success=True, message="2FA activated successfully.")

    return VerifyResponse(success=False, message="Invalid code. Please try again.")


@router.post("/disable", response_model=VerifyResponse)
async def disable_2fa(req: DisableRequest) -> VerifyResponse:
    """Disable 2FA after verifying the current TOTP code."""
    secret = _secrets.get(req.user_id)
    if not secret or not _enabled.get(req.user_id):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="2FA is not enabled")

    if _verify_totp(secret, req.code):
        _enabled[req.user_id] = False
        _secrets.pop(req.user_id, None)
        _backup_codes.pop(req.user_id, None)
        logger.info("2FA disabled for user %s", req.user_id)
        return VerifyResponse(success=True, message="2FA disabled.")

    return VerifyResponse(success=False, message="Invalid code.")


@router.get("/backup-codes/{user_id}", response_model=BackupCodesResponse)
async def get_backup_codes(user_id: str) -> BackupCodesResponse:
    """Generate 8 one-time backup codes for account recovery."""
    if not _enabled.get(user_id):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="2FA must be enabled first")

    codes = [secrets.token_hex(4).upper() for _ in range(8)]
    _backup_codes[user_id] = codes
    return BackupCodesResponse(codes=codes)


@router.get("/status/{user_id}")
async def get_2fa_status(user_id: str) -> dict:
    return {"user_id": user_id, "enabled": _enabled.get(user_id, False)}
