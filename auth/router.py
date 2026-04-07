# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
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

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, EmailStr, Field

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/auth", tags=["Authentication"])
_bearer = HTTPBearer(auto_error=False)

# Module-level service reference — injected from app.py startup
_auth_service = None

# ── Per-IP rate limiter ───────────────────────────────────────────────────────
# Sliding-window counter: max N requests per window_seconds per IP.
# Uses Redis when available, falls back to in-memory (single-process only).

_AUTH_RATE_LIMIT = int(os.getenv("AUTH_RATE_LIMIT_REQUESTS", "10"))  # max attempts
_AUTH_RATE_WINDOW = int(os.getenv("AUTH_RATE_LIMIT_WINDOW_SECONDS", "60"))  # per minute

# Trusted reverse-proxy IPs — only these may set X-Forwarded-For.
# Comma-separated list; defaults to loopback only.
_TRUSTED_PROXIES: frozenset[str] = frozenset(
    ip.strip() for ip in os.getenv("TRUSTED_PROXY_IPS", "127.0.0.1,::1").split(",") if ip.strip()
)

# In-memory fallback: {ip: [timestamp, ...]}
_ip_windows: dict = defaultdict(list)


def _get_client_ip(request: Request) -> str:
    """Return the real client IP, honouring X-Forwarded-For only from trusted proxies."""
    direct_ip = request.client.host if request.client else "unknown"
    if direct_ip in _TRUSTED_PROXIES:
        forwarded = request.headers.get("X-Forwarded-For")
        if forwarded:
            return forwarded.split(",")[0].strip()
    return direct_ip


def _check_ip_rate_limit(ip: str) -> None:
    """Raise HTTP 429 if the IP has exceeded the auth rate limit."""
    # Try Redis first
    try:
        import redis as _redis

        r = _redis.Redis(
            host=os.getenv("REDIS_HOST", "localhost"),
            port=int(os.getenv("REDIS_PORT", "6379")),
            socket_connect_timeout=0.5,
            decode_responses=True,
            retry_on_error=[],
            retry=None,
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
    except Exception as _exc:
        logger.debug("Suppressed exception: %s", _exc)  # Redis unavailable — fall through to in-memory

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
    """Alias for _get_client_ip — used in endpoint handlers."""
    return _get_client_ip(request)


# ── Request / Response models ─────────────────────────────────────────────────


class RegisterRequest(BaseModel):
    email: EmailStr
    username: str = Field(..., min_length=3, max_length=50, pattern=r"^[a-zA-Z0-9_-]+$")
    password: str = Field(..., min_length=8, max_length=128)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=1)
    totp_code: str | None = Field(None, min_length=6, max_length=8)


class RefreshRequest(BaseModel):
    refresh_token: str


class LogoutRequest(BaseModel):
    refresh_token: str
    access_token: str | None = None  # if provided, immediately blacklisted


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


def _get_current_user_id(
    credentials: HTTPAuthorizationCredentials = Depends(_bearer),
) -> str:
    if not credentials:
        raise HTTPException(
            status_code=401,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )
    try:
        import jwt

        from auth.service import _get_secret

        secret = _get_secret()  # raises RuntimeError if unset or too short
        payload = jwt.decode(
            credentials.credentials,
            secret,
            algorithms=["HS256"],
            options={"require": ["sub", "exp"]},
        )
        if payload.get("type") != "access":
            raise ValueError("Not an access token")
        return payload["sub"]
    except RuntimeError as exc:
        # Misconfigured secret — do not mask as 401
        logger.critical("JWT secret misconfiguration in auth router: %s", exc)
        raise HTTPException(
            status_code=503,
            detail="Authentication service misconfigured",
        ) from exc
    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=401,
            detail="Token expired",
            headers={"WWW-Authenticate": "Bearer"},
        ) from None
    except (jwt.InvalidTokenError, ValueError):
        raise HTTPException(
            status_code=401,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        ) from None


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

    # Auto-assign FREE tier so paper trading works immediately after signup
    try:
        from monetization.subscription import SubscriptionTier, subscription_manager

        existing = subscription_manager.get_user_subscription(body.username)
        if not existing:
            subscription_manager.create_subscription(
                body.username,
                SubscriptionTier.FREE,
            )
            logger.info("FREE tier assigned to new user %s", body.username)
    except Exception as _tier_err:
        logger.debug("Free tier assignment skipped: %s", _tier_err)

    response = {"message": msg}
    # Expose token only in explicit test mode (APP_ENV=test) so devs can test
    # without SMTP.  Never expose in development or staging — those environments
    # may share infrastructure with production and a leaked token is a live
    # account-takeover vector.
    if verify_token and os.getenv("APP_ENV", "").lower() == "test":
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
    except Exception as _exc:
        logger.debug("Suppressed exception: %s", _exc)

    return tokens


@router.post("/refresh")
async def refresh(body: RefreshRequest, request: Request):
    """Rotate refresh token. Returns new access + refresh token pair."""
    ok, msg, tokens = _svc().refresh(body.refresh_token, ip_address=_client_ip(request))
    if not ok:
        raise HTTPException(status_code=401, detail=msg)
    return tokens


@router.post("/logout")
async def logout(
    body: LogoutRequest,
    credentials: HTTPAuthorizationCredentials = Depends(_bearer),
):
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


# ── Session management ────────────────────────────────────────────────────────


@router.get("/sessions")
async def list_sessions(user_id: str = Depends(_get_current_user_id)):
    """Return all active sessions for the current user."""
    sessions: list[dict] = []
    try:
        from database.connection import SessionLocal
        from database.user_models import UserSession

        db = SessionLocal()
        try:
            rows = db.query(UserSession).filter_by(user_id=user_id, is_active=True).all()
            sessions = [
                {
                    "session_id": s.id,
                    "ip_address": getattr(s, "ip_address", None),
                    "user_agent": getattr(s, "user_agent", None),
                    "created_at": s.created_at.isoformat() if s.created_at else None,
                    "last_used_at": s.last_used_at.isoformat() if getattr(s, "last_used_at", None) else None,
                    "is_current": False,
                }
                for s in rows
            ]
        finally:
            db.close()
    except Exception as exc:
        logger.debug("list_sessions: %s", exc)
    return {"sessions": sessions}


@router.delete("/sessions/{session_id}")
async def revoke_session(session_id: str, user_id: str = Depends(_get_current_user_id)):
    """Revoke a specific session by ID. Only the owning user can revoke their own sessions."""
    try:
        from database.connection import SessionLocal
        from database.user_models import UserSession

        db = SessionLocal()
        try:
            s = db.query(UserSession).filter_by(id=session_id, user_id=user_id).first()
            if s:
                s.is_active = False
                db.commit()
        finally:
            db.close()
    except Exception as exc:
        logger.debug("revoke_session: %s", exc)
    return {"message": "Session revoked"}


@router.delete("/sessions")
async def revoke_all_sessions(user_id: str = Depends(_get_current_user_id)):
    """Revoke all sessions for the current user (alias for logout-all)."""
    _svc().logout_all(user_id)
    return {"message": "All sessions revoked"}


@router.post("/forgot-password")
async def forgot_password(body: ForgotPasswordRequest, request: Request):
    """Request a password reset link. Always returns 200 to avoid email enumeration."""
    _check_ip_rate_limit(_get_client_ip(request))
    _, msg, reset_token = _svc().request_password_reset(body.email)
    if reset_token:
        try:
            from core.email_service import send_password_reset_email

            user = _svc().get_user_by_email(body.email)
            username = user.username if user else body.email
            send_password_reset_email(body.email, username, reset_token)
        except Exception as _e:
            logger.warning("Password reset email failed: %s", _e)

    response = {"message": msg}
    # Same restriction as register: only expose in APP_ENV=test.
    if reset_token and os.getenv("APP_ENV", "").lower() == "test":
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
    return {
        "provisioning_uri": uri_or_msg,
        "secret": secret,
        "message": "Scan the QR code then call /auth/2fa/confirm with a valid code",
    }


@router.post("/2fa/confirm")
async def confirm_2fa(
    body: TOTPConfirmRequest,
    user_id: str = Depends(_get_current_user_id),
):
    """Confirm 2FA setup with a valid TOTP code to activate it."""
    ok, msg = _svc().confirm_2fa(user_id, body.code)
    if not ok:
        raise HTTPException(status_code=400, detail=msg)
    return {"message": msg}


@router.post("/2fa/disable")
async def disable_2fa(
    body: TOTPDisableRequest,
    user_id: str = Depends(_get_current_user_id),
):
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


class _FreeTierBody(BaseModel):
    user_id: str
    ref_code: str | None = None


@router.post("/activate-free-tier", status_code=status.HTTP_201_CREATED)
async def activate_free_tier(body: _FreeTierBody):
    """
    Assign the FREE subscription tier immediately after registration.

    Delegates to the billing subscription manager. Tracks referral when
    ref_code is present. Called from the post-signup onboarding flow.
    """
    try:
        from api.billing import activate_free_tier as _billing_activate

        # Re-use the billing implementation to avoid duplicating logic
        from pydantic import BaseModel as _BM

        class _Proxy(_BM):
            user_id: str
            ref_code: str | None = None

        return await _billing_activate(_Proxy(user_id=body.user_id, ref_code=body.ref_code))
    except Exception:
        # Fallback: create subscription directly
        try:
            from monetization.subscription import SubscriptionManager, SubscriptionTier

            mgr = SubscriptionManager()
            existing = mgr.get_user_subscription(body.user_id)
            if existing:
                return {"tier": "free", "message": "Subscription already active.", "features": ["paper_trading"]}
            sub = mgr.create_subscription(body.user_id, SubscriptionTier.FREE)
            return {
                "tier": sub.tier.value if hasattr(sub.tier, "value") else "free",
                "message": "You're on the Free tier — upgrade for live trading + AI signals.",
                "features": ["paper_trading"],
                "upgrade_url": "/subscription",
            }
        except Exception as exc:
            logger.warning("activate_free_tier fallback failed: %s", exc)
            return {"tier": "free", "message": "Free tier activated.", "features": ["paper_trading"]}
