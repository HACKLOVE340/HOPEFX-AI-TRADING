"""
Auth API router — /auth/*

Endpoints:
  POST /auth/register          — create account
  POST /auth/login             — get access + refresh tokens
  POST /auth/refresh           — rotate refresh token
  POST /auth/logout            — revoke current session
  POST /auth/logout-all        — revoke all sessions (after password change)
  GET  /auth/verify-email      — verify email from link
  POST /auth/resend-verification
  POST /auth/forgot-password   — request reset link
  POST /auth/reset-password    — set new password with token
  POST /auth/2fa/setup         — generate TOTP secret + QR URI
  POST /auth/2fa/confirm       — enable 2FA after scanning QR
  POST /auth/2fa/disable       — disable 2FA
  GET  /auth/me                — current user profile
"""

from __future__ import annotations

import logging
import os
import time
from collections import defaultdict
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel, EmailStr, Field

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/auth", tags=["Authentication"])
_bearer = HTTPBearer(auto_error=False)

# Module-level service reference — injected from app.py startup
_auth_service = None

# ── Per-IP rate limiter ───────────────────────────────────────────────────────
# Sliding-window counter: max N requests per window_seconds per IP.
# Uses Redis when available, falls back to in-memory (single-process only).

_AUTH_RATE_LIMIT = int(os.getenv("AUTH_RATE_LIMIT_REQUESTS", "10"))   # max attempts
_AUTH_RATE_WINDOW = int(os.getenv("AUTH_RATE_LIMIT_WINDOW_SECONDS", "60"))  # per minute

# In-memory fallback: {ip: [timestamp, ...]}
_ip_windows: dict = defaultdict(list)


def _get_client_ip(request: Request) -> str:
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _check_ip_rate_limit(ip: str) -> None:
    """Raise HTTP 429 if the IP has exceeded the auth rate limit."""
    # Try Redis first
    try:
        import redis as _redis
        r = _redis.Redis(
            host=os.getenv("REDIS_HOST", "localhost"),
            port=int(os.getenv("REDIS_PORT", "6379")),
            socket_connect_timeout=1,
            decode_responses=True,
        )
        key = f"auth_rl:{ip}"
        pipe = r.pipeline()
        now = time.time()
        pipe.zremrangebyscore(key, 0, now - _AUTH_RATE_WINDOW)
        pipe.zadd(key, {str(now): now})
        pipe.zcard(key)
        pipe.expire(key, _AUTH_RATE_WINDOW + 1)
        results = pipe.execute()
        count = results[2]
        if count > _AUTH_RATE_LIMIT:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=f"Too many auth attempts. Try again in {_AUTH_RATE_WINDOW}s.",
                headers={"Retry-After": str(_AUTH_RATE_WINDOW)},
            )
        return
    except HTTPException:
        raise
    except Exception:
        pass  # Redis unavailable — fall through to in-memory

    # In-memory fallback
    now = time.time()
    cutoff = now - _AUTH_RATE_WINDOW
    timestamps = [t for t in _ip_windows[ip] if t > cutoff]
    timestamps.append(now)
    _ip_windows[ip] = timestamps
    if len(timestamps) > _AUTH_RATE_LIMIT:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Too many auth attempts. Try again in {_AUTH_RATE_WINDOW}s.",
            headers={"Retry-After": str(_AUTH_RATE_WINDOW)},
        )


def set_auth_service(service) -> None:
    global _auth_service
    _auth_service = service


def _svc():
    if _auth_service is None:
        raise HTTPException(status_code=503, detail="Auth service not initialised")
    return _auth_service


def _client_ip(request: Request) -> str:
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


# ── Request / Response models ─────────────────────────────────────────────────

class RegisterRequest(BaseModel):
    email: EmailStr
    username: str = Field(..., min_length=3, max_length=50, pattern=r"^[a-zA-Z0-9_-]+$")
    password: str = Field(..., min_length=8, max_length=128)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=1)
    totp_code: Optional[str] = Field(None, min_length=6, max_length=8)


class RefreshRequest(BaseModel):
    refresh_token: str


class LogoutRequest(BaseModel):
    refresh_token: str
    access_token: Optional[str] = None   # if provided, immediately blacklisted


class ForgotPasswordRequest(BaseModel):
    email: EmailStr


class ResetPasswordRequest(BaseModel):
    token: str
    new_password: str = Field(..., min_length=8, max_length=128)


class TOTPConfirmRequest(BaseModel):
    code: str = Field(..., min_length=6, max_length=8)


class TOTPDisableRequest(BaseModel):
    code: str = Field(..., min_length=6, max_length=8)


# ── Dependency: current user from access token ────────────────────────────────

def _get_current_user_id(credentials: HTTPAuthorizationCredentials = Depends(_bearer)) -> str:
    if not credentials:
        raise HTTPException(status_code=401, detail="Not authenticated",
                            headers={"WWW-Authenticate": "Bearer"})
    try:
        import jwt, os
        secret = os.getenv("SECURITY_JWT_SECRET", "")
        payload = jwt.decode(credentials.credentials, secret, algorithms=["HS256"],
                             options={"require": ["sub", "exp"]})
        if payload.get("type") != "access":
            raise ValueError("Not an access token")
        return payload["sub"]
    except Exception as exc:
        raise HTTPException(status_code=401, detail="Invalid or expired token",
                            headers={"WWW-Authenticate": "Bearer"})


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post("/register", status_code=201)
async def register(body: RegisterRequest, request: Request):
    """Create a new user account and send email verification."""
    _check_ip_rate_limit(_get_client_ip(request))
    ok, msg, verify_token = _svc().register(
        email=body.email,
        username=body.username,
        password=body.password,
    )
    if not ok:
        raise HTTPException(status_code=400, detail=msg)

    if verify_token:
        try:
            from core.email_service import send_verification_email
            send_verification_email(body.email, body.username, verify_token)
        except Exception as _e:
            logger.warning("Verification email failed: %s", _e)

    response = {"message": msg}
    # Expose token in non-production so devs can test without SMTP
    if verify_token and os.getenv("APP_ENV", "development") != "production":
        response["_dev_verify_token"] = verify_token
    return response


@router.get("/verify-email")
async def verify_email(token: str):
    """Verify email address from link. token= query param."""
    ok, msg = _svc().verify_email(token)
    if not ok:
        raise HTTPException(status_code=400, detail=msg)
    return {"message": msg}


@router.post("/resend-verification")
async def resend_verification(body: ForgotPasswordRequest):
    ok, msg, verify_token = _svc().resend_verification(body.email)
    if not ok:
        raise HTTPException(status_code=400, detail=msg)
    if verify_token:
        try:
            from core.email_service import send_verification_email
            # Fetch username for the email
            user = _svc().get_user_by_email(body.email)
            username = user.username if user else body.email
            send_verification_email(body.email, username, verify_token)
        except Exception as _e:
            logger.warning("Resend verification email failed: %s", _e)
    return {"message": msg}


@router.post("/login")
async def login(body: LoginRequest, request: Request):
    """Authenticate and receive access + refresh tokens."""
    _check_ip_rate_limit(_get_client_ip(request))
    ip = _client_ip(request)
    device = request.headers.get("User-Agent", "")
    ok, msg, tokens = _svc().login(
        email=body.email,
        password=body.password,
        ip_address=ip,
        device_info=device,
        totp_code=body.totp_code,
    )
    if not ok:
        raise HTTPException(status_code=401, detail=msg)

    # Fire-and-forget login alert (non-blocking)
    try:
        from core.email_service import send_login_alert
        user = tokens.get("user", {})
        send_login_alert(body.email, user.get("username", body.email), ip, device[:80])
    except Exception:
        pass

    return tokens


@router.post("/refresh")
async def refresh(body: RefreshRequest, request: Request):
    """Rotate refresh token. Returns new access + refresh token pair."""
    ok, msg, tokens = _svc().refresh(body.refresh_token, ip_address=_client_ip(request))
    if not ok:
        raise HTTPException(status_code=401, detail=msg)
    return tokens


@router.post("/logout")
async def logout(body: LogoutRequest, credentials: HTTPAuthorizationCredentials = Depends(_bearer)):
    """Revoke the current session and blacklist the access token."""
    # Use the bearer token from the Authorization header if not explicitly provided
    access_token = body.access_token or (credentials.credentials if credentials else None)
    _svc().logout(body.refresh_token, access_token=access_token)
    return {"message": "Logged out successfully"}


@router.post("/logout-all")
async def logout_all(user_id: str = Depends(_get_current_user_id)):
    """Revoke all active sessions for the current user."""
    _svc().logout_all(user_id)
    return {"message": "All sessions revoked"}


@router.post("/forgot-password")
async def forgot_password(body: ForgotPasswordRequest, request: Request):
    """Request a password reset link. Always returns 200 to avoid email enumeration."""
    _check_ip_rate_limit(_get_client_ip(request))
    ok, msg, reset_token = _svc().request_password_reset(body.email)
    if reset_token:
        try:
            from core.email_service import send_password_reset_email
            user = _svc().get_user_by_email(body.email)
            username = user.username if user else body.email
            send_password_reset_email(body.email, username, reset_token)
        except Exception as _e:
            logger.warning("Password reset email failed: %s", _e)

    response = {"message": msg}
    if reset_token and os.getenv("APP_ENV", "development") != "production":
        response["_dev_reset_token"] = reset_token
    return response


@router.post("/reset-password")
async def reset_password(body: ResetPasswordRequest):
    """Set a new password using the reset token."""
    ok, msg = _svc().reset_password(body.token, body.new_password)
    if not ok:
        raise HTTPException(status_code=400, detail=msg)
    return {"message": msg}


@router.post("/2fa/setup")
async def setup_2fa(user_id: str = Depends(_get_current_user_id)):
    """Generate TOTP secret and QR code URI. Call /2fa/confirm to activate."""
    ok, uri_or_msg, secret = _svc().setup_2fa(user_id)
    if not ok:
        raise HTTPException(status_code=400, detail=uri_or_msg)
    return {"provisioning_uri": uri_or_msg, "secret": secret,
            "message": "Scan the QR code then call /auth/2fa/confirm with a valid code"}


@router.post("/2fa/confirm")
async def confirm_2fa(body: TOTPConfirmRequest, user_id: str = Depends(_get_current_user_id)):
    """Confirm 2FA setup with a valid TOTP code to activate it."""
    ok, msg = _svc().confirm_2fa(user_id, body.code)
    if not ok:
        raise HTTPException(status_code=400, detail=msg)
    return {"message": msg}


@router.post("/2fa/disable")
async def disable_2fa(body: TOTPDisableRequest, user_id: str = Depends(_get_current_user_id)):
    """Disable 2FA. Requires a valid TOTP code to confirm."""
    ok, msg = _svc().disable_2fa(user_id, body.code)
    if not ok:
        raise HTTPException(status_code=400, detail=msg)
    return {"message": msg}


@router.get("/me")
async def get_me(user_id: str = Depends(_get_current_user_id)):
    """Return current user profile."""
    user = _svc().get_user_by_id(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return {
        "id": user.id,
        "email": user.email,
        "username": user.username,
        "role": user.role,
        "status": user.status,
        "is_email_verified": user.is_email_verified,
        "kyc_status": user.kyc_status,
        "totp_enabled": user.totp_enabled,
        "created_at": user.created_at.isoformat() if user.created_at else None,
        "last_login_at": user.last_login_at.isoformat() if user.last_login_at else None,
    }
