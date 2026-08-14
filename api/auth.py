# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
API authentication dependencies for HOPEFX trading endpoints.

Provides JWT-based bearer token verification with role-based access control.
All trading-mutating endpoints must use require_role("trader") or higher.
Read-only endpoints use get_current_user.

Token generation is handled externally (login endpoint / mobile auth).
"""

import logging
import os

import jwt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel

logger = logging.getLogger(__name__)

_bearer = HTTPBearer(auto_error=False)  # auto_error=False so we can fall back to cookie auth

# ---------------------------------------------------------------------------
# Router re-export
# ---------------------------------------------------------------------------
# api/auth.py is a *dependency* module (get_current_user, require_role, etc.).
# The actual HTTP endpoints live in auth/router.py.  Re-export that router here
# so that code doing `from api.auth import router` works without change.
try:
    from auth.router import router  # re-exported for callers doing `from api.auth import router`
except Exception as _router_import_err:  # pragma: no cover
    # Do NOT silently substitute an empty router — a broken auth.router would
    # cause all auth endpoints to disappear at startup with no visible error.
    # Raise immediately so the misconfiguration is caught at process start.
    raise ImportError(
        f"Failed to import auth.router — all auth endpoints would be lost. "
        f"Fix the underlying error before starting the server: {_router_import_err}"
    ) from _router_import_err

__all__ = ["TokenPayload", "get_current_user", "require_role", "router"]

# Role hierarchy: higher index = more privileged.
# "starter" is the free-tier role — lowest privilege, below "user".
# All roles must be listed here; any role absent from this map gets rank -1
# (denied everywhere) which would silently block legitimate users.
_ROLE_RANK: dict = {
    "starter": 0,
    "user": 1,
    "trader": 2,
    "admin": 3,
    "superadmin": 4,
}
# Derived rather than hardcoded so it cannot drift if the hierarchy changes.
_LOWEST_ROLE: str = min(_ROLE_RANK, key=lambda r: _ROLE_RANK[r])

# Stable per-role dependency callables — same object identity on every call,
# required for FastAPI dependency_overrides to work correctly in tests.
_ROLE_DEPS: dict = {}

# The one default instrument allowlist. `api/server.py` imports this rather
# than repeating the literal: it previously carried its own copy that omitted
# ETHUSD, so with no env var set the order routes and validate_order_symbol()
# disagreed about whether ETH/USD existed. `.env.example` must also list the
# same set — a deployment copies that file, and its copy was the one the live
# site was running, which is why the terminal offered ETH/USD in the symbol
# dropdown and then answered "Symbol 'ETHUSD' is not in the permitted
# instrument list." Kept in sync by tests/unit/test_instrument_allowlist_agrees.py.
DEFAULT_ALLOWED_SYMBOLS = "XAUUSD,EURUSD,GBPUSD,USDJPY,BTCUSD,ETHUSD,AUDUSD,USDCHF"


def parse_allowed_symbols(raw: str | None) -> frozenset[str]:
    """Parse an ALLOWED_SYMBOLS value into a canonical set.

    Entries are stripped and upper-cased, and blanks dropped. Without the
    strip, the natural way to write the variable — ``XAUUSD, ETHUSD`` with a
    space after the comma — produced the member ``" ETHUSD"``, which no
    canonicalised symbol can ever equal, silently disabling the instrument.
    """
    return frozenset(s.strip().upper() for s in (raw or "").split(",") if s.strip())


ALLOWED_SYMBOLS = parse_allowed_symbols(os.getenv("ALLOWED_SYMBOLS", DEFAULT_ALLOWED_SYMBOLS))
MAX_ORDER_QUANTITY = float(os.getenv("MAX_ORDER_QUANTITY", "100.0"))


class TokenPayload(BaseModel):
    """Decoded JWT access-token claims.

    All fields written by ``AuthService._create_access_token()`` are declared
    here so downstream dependencies can access them without ``getattr`` fallbacks.
    Pydantic ignores extra claims, so adding new JWT fields does not break
    existing tokens.
    """

    sub: str  # user_id (UUID string)
    # Defaults to the LOWEST-ranked role, not "user". Every token this service
    # issues carries an explicit role, so this default only applies to a token
    # that omits the claim — and such a token should get least privilege. With
    # "user" it outranked "starter", so a malformed or legacy token was granted
    # more than a real starter-tier customer.
    role: str = _LOWEST_ROLE
    exp: int | None = None
    iat: int | None = None
    jti: str | None = None  # JWT ID — used for blacklist revocation on logout
    type: str | None = None  # "access" discriminator checked by _decode_token
    email: str | None = None
    username: str | None = None
    two_factor_verified: bool = False  # True only when TOTP 2FA was completed at login


def _get_jwt_secret() -> str:
    """Return the JWT signing secret.

    Delegates to ``auth.jwt._get_secret()`` — the single source of truth for
    secret loading, validation, and env-var fallback order
    (SECURITY_JWT_SECRET → JWT_SECRET_KEY).

    Previously this function read SECURITY_JWT_SECRET → JWT_SECRET, which
    differs from auth.jwt._load_secret()'s fallback (JWT_SECRET_KEY not
    JWT_SECRET). That mismatch meant tokens signed via one path could fail
    verification on the other when only the alias was set.
    """
    from auth.jwt import _get_secret as _jwt_get_secret

    return _jwt_get_secret()


def _decode_token(token: str) -> TokenPayload:
    """Decode and validate a JWT bearer token, checking type claim and revocation blacklist."""
    try:
        secret = _get_jwt_secret()
        payload = jwt.decode(
            token,
            secret,
            algorithms=["HS256"],
            options={"require": ["sub", "exp"]},
        )

        # Enforce access-token type — reject refresh tokens used as access tokens.
        # Consistent with auth.jwt.decode_access_token().
        if payload.get("type") != "access":
            raise jwt.InvalidTokenError("Not an access token")

        # Check access-token blacklist (populated on logout)
        jti = payload.get("jti")
        if jti:
            try:
                from auth.service import is_access_token_revoked

                if is_access_token_revoked(jti):
                    raise HTTPException(
                        status_code=status.HTTP_401_UNAUTHORIZED,
                        detail="Token has been revoked",
                        headers={"WWW-Authenticate": "Bearer"},
                    )
            except HTTPException:
                raise
            except Exception as exc:
                # Redis is unavailable — fall through and allow the request.
                # The in-memory fallback in _TokenBlacklist handles revocations
                # within the same process. A Redis outage does not block logins;
                # tokens issued before the outage remain valid until they expire
                # naturally (ACCESS_TOKEN_EXPIRE_MINUTES, default 60 min).
                # This is the correct trade-off for a trading platform: a brief
                # window where a logged-out token could be reused is far less
                # harmful than locking every user out during a Redis restart.
                logger.warning(
                    "Token blacklist check failed (Redis unavailable) — allowing request: %s",
                    exc,
                )

        return TokenPayload(**payload)
    except HTTPException:
        raise
    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token expired",
            headers={"WWW-Authenticate": "Bearer"},
        ) from None
    except jwt.InvalidTokenError as exc:
        logger.warning("Invalid JWT token: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc
    except RuntimeError as exc:
        logger.critical("JWT secret misconfiguration: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Authentication service misconfigured",
        ) from exc


def _update_session_activity(user_id: str) -> None:
    """Update last_active_at on the most-recent non-revoked session for user_id.

    Called as a fire-and-forget background task from get_current_user so that
    the superadmin sessions panel shows real activity timestamps rather than
    the session creation time.  Failures are suppressed — this is best-effort.
    """
    try:
        from datetime import datetime, timezone as _tz

        from database.connection import SessionLocal
        from database.user_models import UserSession

        now = datetime.now(_tz.utc)
        db = SessionLocal()
        try:
            sess = (
                db.query(UserSession)
                .filter(
                    UserSession.user_id == user_id,
                    UserSession.is_revoked == False,
                )
                .order_by(UserSession.created_at.desc())
                .first()
            )
            if sess:
                sess.last_active_at = now
                db.commit()
        finally:
            db.close()
    except Exception as exc:
        logger.debug("session activity update suppressed: %s", exc)


def get_current_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> TokenPayload:
    """Dependency: any authenticated user.

    Token resolution order:
      1. Authorization: Bearer <token> header  (API clients, React SPA fetch)
      2. hopefx_access_token cookie            (browser navigation fallback)

    Raises 401 if neither is present or the token is invalid.

    Also schedules a background update of UserSession.last_active_at so the
    superadmin sessions panel reflects real activity rather than creation time.
    """
    token: str | None = (
        credentials.credentials if credentials is not None else request.cookies.get("hopefx_access_token")
    )

    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )

    payload = _decode_token(token)

    # Update session activity in the background — non-blocking, best-effort.
    # Use starlette's BackgroundTasks attached to the request state so the
    # update runs after the response is sent without delaying the caller.
    try:
        if not hasattr(request.state, "background_tasks"):
            from starlette.background import BackgroundTasks as _BT

            request.state.background_tasks = _BT()
        request.state.background_tasks.add_task(_update_session_activity, payload.sub)
    except Exception:  # nosec B110  # noqa: S110
        pass

    return payload


def require_role(minimum_role: str):
    """
    Dependency factory: require caller to hold at least `minimum_role`.

    Always delegates to the canonical sys.modules["api.auth"] instance so
    that the returned callable is the same object regardless of how this
    module was imported (direct import vs importlib.util.spec_from_file_location).
    This ensures FastAPI dependency_overrides key-identity works in tests.

    Usage:
        @router.post("/order")
        async def place_order(user: TokenPayload = Depends(require_role("trader"))):
            ...
    """
    import sys as _sys

    _canonical = _sys.modules.get("api.auth")
    # If a canonical instance exists and it's not us, delegate to it so the
    # returned callable is always from the canonical module.
    if _canonical is not None and _canonical is not _sys.modules.get(__name__):
        return _canonical.require_role(minimum_role)

    if minimum_role in _ROLE_DEPS:
        return _ROLE_DEPS[minimum_role]

    def _check(user: TokenPayload = Depends(get_current_user)) -> TokenPayload:
        caller_rank = _ROLE_RANK.get(user.role, -1)
        required_rank = _ROLE_RANK.get(minimum_role, 999)
        if caller_rank < required_rank:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Role '{minimum_role}' required, caller has '{user.role}'",
            )
        return user

    _ROLE_DEPS[minimum_role] = _check
    return _check


def validate_order_symbol(symbol: str) -> str:
    """Validate symbol is in the allowed set (prevents injection via symbol field).

    Normalises common alternate formats to canonical MT5 form before checking:
      XAU/USD  -> XAUUSD
      XAU_USD  -> XAUUSD
      xauusd   -> XAUUSD
    """
    try:
        from utils.symbol import canonical as _canonical

        canonical = _canonical(symbol.strip())
    except Exception:
        canonical = symbol.upper().strip().replace("/", "").replace("_", "").replace("-", "")
    if canonical not in ALLOWED_SYMBOLS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Symbol '{symbol}' is not permitted. Allowed: {sorted(ALLOWED_SYMBOLS)}",
        )
    return canonical


def validate_order_quantity(quantity: float) -> float:
    """Validate order quantity is positive and within configured maximum."""
    if quantity <= 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Quantity must be positive",
        )
    if quantity > MAX_ORDER_QUANTITY:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Quantity {quantity} exceeds maximum allowed {MAX_ORDER_QUANTITY}",
        )
    return quantity


def require_kyc(
    request: Request,
    user: TokenPayload = Depends(get_current_user),
) -> TokenPayload:
    """
    Dependency: require the caller to have passed KYC verification.

    Admin and superadmin roles are exempt — platform operators are not
    required to submit identity documents to trade on their own platform.

    Enforcement is gated on whether a compliance_manager is actually wired —
    NOT on app identity. The previous code skipped KYC for any app instance that
    was not the app.py singleton, which silently let a second app (e.g.
    api/server.py's app, which exposes real order routes) trade without KYC.
    Test / embedded apps wire no compliance_manager (it stays None), so they
    still pass through.

    Fail-open vs fail-closed
    ------------------------
    Passing through on a missing manager is a development convenience that must
    not survive into production: this dependency also guards fiat withdrawal, so
    a compliance manager that failed to wire (bad config, import error, partial
    startup) would silently disable identity checks on money leaving the
    platform, with nothing in the response to indicate it.

    In production the absence of a compliance manager is therefore a hard
    failure. Same shape as ``_verify_webhook_hmac`` in api/payments.py: reject in
    production, allow in dev only when nothing is wired at all. Set
    ``HOPEFX_REQUIRE_KYC_STRICT=true`` to get production behaviour elsewhere, or
    ``false`` to opt out in a non-production deployment that genuinely has no
    compliance layer.

    Usage:
        @router.post("/order")
        async def place_order(user: TokenPayload = Depends(require_kyc)):
            ...
    """
    # Platform operators are exempt from KYC.
    if user.role in ("admin", "superadmin"):
        return user

    _strict_default = "true" if os.getenv("APP_ENV", "development").lower() == "production" else "false"
    _strict = os.getenv("HOPEFX_REQUIRE_KYC_STRICT", _strict_default).lower() in ("true", "1", "yes")

    def _unavailable(reason: str) -> None:
        """Handle 'we cannot tell whether this user passed KYC'."""
        if _strict:
            logger.critical(
                "KYC enforcement unavailable (%s) — REJECTING request for user=%s. "
                "A compliance manager must be wired in production.",
                reason,
                user.sub,
            )
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Identity verification is temporarily unavailable. Please try again shortly.",
            )
        logger.warning("KYC enforcement skipped (%s) — permitted outside production only.", reason)

    try:
        from core.app_state import app_state as _global_app_state
    except ImportError as exc:
        _unavailable(f"app_state import failed: {exc}")
        return user

    # Prefer the compliance_manager wired onto THIS request's app state
    # (app.py exposes app_state at app.state.app_state); fall back to the
    # process-wide singleton.
    _state = getattr(getattr(request, "app", None), "state", None)
    _app_state = getattr(_state, "app_state", None) or _global_app_state
    cm = getattr(_app_state, "compliance_manager", None)

    if cm is None:
        _unavailable("no compliance_manager wired")
        return user

    if not cm.is_kyc_approved(user.sub):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="KYC verification required before trading. Please complete identity verification.",
        )
    return user
