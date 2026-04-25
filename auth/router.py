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

import asyncio
import functools
import logging
import os
import secrets
import time
from collections import defaultdict
from datetime import datetime, timezone

UTC = timezone.utc

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
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

def _parse_int_env(name: str, default: int) -> int:
    """Parse an integer env var, raising a clear error if the value is not a plain integer.

    Values like '1h' or '60s' are rejected — these variables expect a bare number.
    """
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError:
        raise ValueError(
            f"Environment variable {name}={raw!r} must be a plain integer "
            f"(e.g. {default}), not a duration string. "
            f"Check your .env file or shell environment."
        )


_AUTH_RATE_LIMIT = _parse_int_env("AUTH_RATE_LIMIT_REQUESTS", 10)   # max attempts
_AUTH_RATE_WINDOW = _parse_int_env("AUTH_RATE_LIMIT_WINDOW_SECONDS", 60)  # seconds

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
            password=os.getenv("REDIS_PASSWORD") or None,
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
    """Accept either ``email`` or ``username`` — one of the two is required."""

    email: str | None = Field(None, description="User email address")
    username: str | None = Field(None, description="Username (alternative to email)")
    password: str = Field(..., min_length=1)
    totp_code: str | None = Field(None, min_length=6, max_length=8)

    @property
    def resolved_email(self) -> str | None:
        """Return whichever identifier was supplied, normalised to lowercase."""
        val = self.email or self.username
        return val.strip().lower() if val else None


class RefreshRequest(BaseModel):
    # Optional in the body — the token may also be sent via the
    # hopefx_refresh_token cookie (set on login for cookie-only clients).
    refresh_token: str | None = None


class LogoutRequest(BaseModel):
    # refresh_token is optional — the frontend may not have it available in all
    # code paths (e.g. SSO flows, cookie-only sessions).  When omitted only the
    # access token is blacklisted; the refresh token will expire naturally.
    refresh_token: str | None = None
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
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> str:
    """Extract and validate the caller's user ID from the access token.

    Token resolution order:
      1. Authorization: Bearer <token> header  (API clients, SPA fetch)
      2. hopefx_access_token cookie            (browser navigation, /me page load)

    Raises 401 if neither is present or the token is invalid/expired.
    """
    token: str | None = (
        credentials.credentials if credentials is not None else request.cookies.get("hopefx_access_token")
    )

    if not token:
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
            token,
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
    ok, msg, verify_token = await asyncio.to_thread(
        functools.partial(
            _svc().register,
            email=body.email,
            username=body.username,
            password=body.password,
        )
    )
    if not ok:
        raise HTTPException(status_code=400, detail=msg)

    if verify_token:
        try:
            from core.email_service import send_verification_email

            send_verification_email(body.email, body.username, verify_token)
        except Exception as _e:
            logger.warning("Verification email failed: %s", _e)

    # Auto-assign FREE tier so paper trading works immediately after signup.
    # Must use the user's UUID (not username) as the subscription key so that
    # /api/billing/subscription lookups by user.sub (JWT sub = UUID) work.
    try:
        from monetization.subscription import SubscriptionTier, subscription_manager

        # Resolve the UUID for the newly created user.
        new_user = await asyncio.to_thread(_svc().get_user_by_email, body.email)
        user_uuid = new_user.id if new_user else None

        if user_uuid:
            existing = subscription_manager.get_user_subscription(user_uuid)
            if not existing:
                subscription_manager.create_subscription(user_uuid, SubscriptionTier.FREE)
                logger.info("FREE tier assigned to new user %s (id=%s)", body.username, user_uuid)
        else:
            logger.warning("Could not resolve UUID for new user %s — free tier skipped", body.username)
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
    ok, msg = await asyncio.to_thread(_svc().verify_email, token)
    if not ok:
        raise HTTPException(status_code=400, detail=msg)
    return {"message": msg}


@router.post("/resend-verification")
async def resend_verification(body: ForgotPasswordRequest, request: Request):
    _check_ip_rate_limit(_get_client_ip(request))
    ok, msg, verify_token = await asyncio.to_thread(_svc().resend_verification, body.email)
    if not ok:
        raise HTTPException(status_code=400, detail=msg)
    if verify_token:
        try:
            from core.email_service import send_verification_email

            # Fetch username for the email
            user = await asyncio.to_thread(_svc().get_user_by_email, body.email)
            username = user.username if user else body.email
            send_verification_email(body.email, username, verify_token)
        except Exception as _e:
            logger.warning("Resend verification email failed: %s", _e)
    return {"message": msg}


@router.post("/login")
async def login(body: LoginRequest, request: Request, response: Response):
    """Authenticate and receive access + refresh tokens.

    Accepts either ``email`` or ``username`` in the request body.
    When a username is supplied it is resolved to an email before
    the credential check so the auth service always works with emails.

    On success, sets an HttpOnly ``hopefx_access_token`` cookie and an
    HttpOnly ``hopefx_refresh_token`` cookie (scoped to /api/auth/refresh).
    The SPA reads the new access token from the JSON response body and keeps
    it in Zustand memory only — never in localStorage.
    """
    if not body.email and not body.username:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Either 'email' or 'username' is required.",
        )

    _check_ip_rate_limit(_get_client_ip(request))
    ip = _client_ip(request)
    device = request.headers.get("User-Agent", "")

    identifier = body.resolved_email  # normalised email or username

    # If the identifier is not an email address, resolve username → email.
    resolved_email = identifier
    if identifier and "@" not in identifier:
        try:
            user_obj = await asyncio.to_thread(_svc().get_user_by_username, identifier)
            if user_obj:
                resolved_email = user_obj.email
            else:
                # Unknown username — return generic 401 (no user enumeration)
                raise HTTPException(status_code=401, detail="Invalid credentials")
        except HTTPException:
            raise
        except Exception as _exc:
            logger.debug("Username lookup failed: %s", _exc)
            raise HTTPException(status_code=401, detail="Invalid credentials") from _exc

    try:
        ok, msg, tokens = await asyncio.to_thread(
            functools.partial(
                _svc().login,
                email=resolved_email,
                password=body.password,
                ip_address=ip,
                device_info=device,
                totp_code=body.totp_code,
            )
        )
    except Exception as _login_exc:
        logger.error("Login service error for %s: %s", resolved_email, _login_exc)
        raise HTTPException(status_code=503, detail="Authentication service temporarily unavailable") from _login_exc

    if not ok:
        raise HTTPException(status_code=401, detail=msg)

    # Guard: service should always return a token dict on success, but be
    # defensive so a None tokens dict doesn't cause an AttributeError below.
    if not tokens or not isinstance(tokens, dict):
        logger.error("Login service returned ok=True but tokens=%r for %s", tokens, resolved_email)
        raise HTTPException(status_code=500, detail="Authentication service error")

    # Fire-and-forget login alert (non-blocking)
    try:
        from core.email_service import send_login_alert

        user = tokens.get("user", {})
        send_login_alert(resolved_email, user.get("username", resolved_email), ip, device[:80])
    except Exception as _exc:
        logger.debug("Suppressed exception: %s", _exc)

    # Set access token as a cookie so browser navigation to protected pages
    # (e.g. /superadmin) works without JS injecting the Authorization header.
    # Not HttpOnly — the React SPA reads it to populate the auth store on
    # page refresh. Secure flag is set in production/staging only.
    access_token = tokens.get("access_token", "")
    refresh_token_val = tokens.get("refresh_token", "")
    _secure = os.getenv("APP_ENV", "development").lower() in ("production", "staging")

    if access_token:
        # Cookie max_age must match the token TTL — read the same env var the
        # service uses (default 60 min, not 15) so the cookie doesn't expire
        # before the token does, which would force unnecessary re-logins.
        _max_age = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "60")) * 60
        response.set_cookie(
            key="hopefx_access_token",
            value=access_token,
            max_age=_max_age,
            httponly=True,
            samesite="strict",
            secure=_secure,
            path="/",
        )

    if refresh_token_val:
        # Refresh token cookie — HttpOnly so JS cannot read it (XSS protection).
        # Used by the /refresh endpoint as a fallback when the body is empty.
        _refresh_max_age = int(os.getenv("REFRESH_TOKEN_EXPIRE_DAYS", "30")) * 86400
        response.set_cookie(
            key="hopefx_refresh_token",
            value=refresh_token_val,
            max_age=_refresh_max_age,
            httponly=True,
            samesite="strict",
            secure=_secure,
            path="/api/auth/refresh",  # Scope to refresh endpoint only
        )

    return tokens


@router.post("/refresh")
async def refresh(body: RefreshRequest, request: Request, response: Response):
    """Rotate refresh token. Returns new access + refresh token pair.

    The refresh token is read from the request body (``refresh_token`` field)
    or, as a fallback, from the ``hopefx_refresh_token`` cookie so that
    cookie-only clients (e.g. server-side rendering) work without JS.
    """
    _check_ip_rate_limit(_get_client_ip(request))
    # Resolve token: body → cookie → 401
    refresh_token = body.refresh_token or request.cookies.get("hopefx_refresh_token")
    if not refresh_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="refresh_token is required (body or cookie)",
        )
    ok, msg, tokens = await asyncio.to_thread(
        functools.partial(_svc().refresh, refresh_token, ip_address=_client_ip(request))
    )
    if not ok:
        raise HTTPException(status_code=401, detail=msg)
    # Rotate the access token cookie to match the new token.
    # Use the same env var and default (60 min) as /login so the cookie
    # lifetime is always consistent with the token TTL.
    new_access = tokens.get("access_token", "")
    if new_access:
        _secure = os.getenv("ENVIRONMENT", "development").lower() in ("production", "staging")
        _max_age = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "60")) * 60
        response.set_cookie(
            key="hopefx_access_token",
            value=new_access,
            max_age=_max_age,
            httponly=True,
            samesite="strict",
            secure=_secure,
            path="/",
        )
    # Rotate the refresh token cookie as well so the new token is persisted.
    new_refresh = tokens.get("refresh_token", "")
    if new_refresh:
        _secure = os.getenv("ENVIRONMENT", "development").lower() in ("production", "staging")
        _refresh_max_age = int(os.getenv("REFRESH_TOKEN_EXPIRE_DAYS", "30")) * 86400
        response.set_cookie(
            key="hopefx_refresh_token",
            value=new_refresh,
            max_age=_refresh_max_age,
            httponly=True,
            samesite="strict",
            secure=_secure,
            path="/api/auth/refresh",
        )
    return tokens


@router.post("/logout")
async def logout(
    body: LogoutRequest,
    response: Response,
    credentials: HTTPAuthorizationCredentials = Depends(_bearer),
):
    """Revoke the current session and blacklist the access token."""
    access_token = body.access_token or (credentials.credentials if credentials else None)
    await asyncio.to_thread(functools.partial(_svc().logout, body.refresh_token, access_token=access_token))
    # Clear both auth cookies set on login
    response.delete_cookie(key="hopefx_access_token", path="/", samesite="strict")
    response.delete_cookie(key="hopefx_refresh_token", path="/api/auth/refresh", samesite="strict")
    return {"message": "Logged out successfully"}


@router.post("/logout-all")
async def logout_all(user_id: str = Depends(_get_current_user_id)):
    """Revoke all active sessions for the current user."""
    await asyncio.to_thread(_svc().logout_all, user_id)
    return {"message": "All sessions revoked"}


# ── Session management ────────────────────────────────────────────────────────


@router.get("/sessions")
async def list_sessions(user_id: str = Depends(_get_current_user_id)):
    """Return all active (non-revoked, non-expired) sessions for the current user."""
    sessions: list[dict] = []
    try:
        from database.connection import SessionLocal
        from database.user_models import UserSession

        db = SessionLocal()
        try:
            now = datetime.now(UTC)
            rows = (
                db.query(UserSession)
                .filter(
                    UserSession.user_id == user_id,
                    UserSession.is_revoked == False,
                    UserSession.expires_at > now,
                )
                .order_by(UserSession.created_at.desc())
                .all()
            )
            sessions = [
                {
                    "session_id": s.id,
                    "ip_address": s.ip_address,
                    "device_info": s.device_info,
                    "created_at": s.created_at.isoformat() if s.created_at else None,
                    "expires_at": s.expires_at.isoformat() if s.expires_at else None,
                    "revoked_at": s.revoked_at.isoformat() if s.revoked_at else None,
                    "is_revoked": s.is_revoked,
                }
                for s in rows
            ]
        finally:
            db.close()
    except Exception as exc:
        logger.warning("list_sessions error: %s", exc)
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
                s.is_revoked = True
                s.revoked_at = datetime.now(UTC)
                db.commit()
        finally:
            db.close()
    except Exception as exc:
        logger.debug("revoke_session: %s", exc)
    return {"message": "Session revoked"}


@router.delete("/sessions")
async def revoke_all_sessions(user_id: str = Depends(_get_current_user_id)):
    """Revoke all sessions for the current user (alias for logout-all)."""
    await asyncio.to_thread(_svc().logout_all, user_id)
    return {"message": "All sessions revoked"}


@router.post("/forgot-password")
async def forgot_password(body: ForgotPasswordRequest, request: Request):
    """Request a password reset link. Always returns 200 to avoid email enumeration."""
    _check_ip_rate_limit(_get_client_ip(request))
    _, msg, reset_token = await asyncio.to_thread(functools.partial(_svc().request_password_reset, body.email))
    if reset_token:
        try:
            from core.email_service import send_password_reset_email

            user = await asyncio.to_thread(_svc().get_user_by_email, body.email)
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
async def reset_password(body: ResetPasswordRequest, request: Request):
    """Set a new password using the reset token."""
    _check_ip_rate_limit(_get_client_ip(request))
    ok, msg = await asyncio.to_thread(functools.partial(_svc().reset_password, body.token, body.new_password))
    if not ok:
        raise HTTPException(status_code=400, detail=msg)
    return {"message": msg}


@router.post("/2fa/setup")
async def setup_2fa(user_id: str = Depends(_get_current_user_id)):
    """Generate TOTP secret and QR code URI. Call /2fa/confirm to activate."""
    ok, uri_or_msg, secret = await asyncio.to_thread(_svc().setup_2fa, user_id)
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
    ok, msg = await asyncio.to_thread(_svc().confirm_2fa, user_id, body.code)
    if not ok:
        raise HTTPException(status_code=400, detail=msg)
    return {"message": msg}


@router.post("/2fa/disable")
async def disable_2fa(
    body: TOTPDisableRequest,
    user_id: str = Depends(_get_current_user_id),
):
    """Disable 2FA. Requires a valid TOTP code to confirm."""
    ok, msg = await asyncio.to_thread(_svc().disable_2fa, user_id, body.code)
    if not ok:
        raise HTTPException(status_code=400, detail=msg)
    return {"message": msg}


@router.get("/me")
async def get_me(user_id: str = Depends(_get_current_user_id)):
    """Return current user profile."""
    user = await asyncio.to_thread(_svc().get_user_by_id, user_id)
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
        "plan": getattr(user, "plan", "free"),
        "created_at": user.created_at.isoformat() if user.created_at else None,
        "last_login_at": user.last_login_at.isoformat() if user.last_login_at else None,
    }


# ── CSRF token endpoint ───────────────────────────────────────────────────────
# Issues a short-lived CSRF token as a cookie (SameSite=Strict, not HttpOnly
# so JavaScript can read it) and returns it in the JSON body.
# State-changing requests must echo the token back in the X-CSRF-Token header.
# The CSRF middleware in app.py validates the header against the cookie.

_CSRF_COOKIE_NAME = "hopefx_csrf"
_CSRF_HEADER_NAME = "X-CSRF-Token"
_CSRF_TOKEN_BYTES = 32
_CSRF_COOKIE_MAX_AGE = 3600  # 1 hour


@router.get("/csrf-token")
async def get_csrf_token(response: Response) -> dict:
    """
    Issue a CSRF token.

    Sets a ``hopefx_csrf`` cookie (SameSite=Strict, Secure in production)
    and returns the token in the JSON body so the client can include it as
    the ``X-CSRF-Token`` header on all state-changing requests.

    Call this once on page load before submitting any form.
    """
    token = secrets.token_hex(_CSRF_TOKEN_BYTES)
    secure = os.getenv("APP_ENV", "development").lower() in ("production", "staging")
    response.set_cookie(
        key=_CSRF_COOKIE_NAME,
        value=token,
        max_age=_CSRF_COOKIE_MAX_AGE,
        httponly=False,  # JS must be able to read it to set the header
        samesite="strict",
        secure=secure,
        path="/",
    )
    return {"csrf_token": token}


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
