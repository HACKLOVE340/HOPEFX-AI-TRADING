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

_bearer = HTTPBearer(auto_error=True)

# ---------------------------------------------------------------------------
# Router re-export
# ---------------------------------------------------------------------------
# api/auth.py is a *dependency* module (get_current_user, require_role, etc.).
# The actual HTTP endpoints live in auth/router.py.  Re-export that router here
# so that code doing `from api.auth import router` works without change.
try:
    from auth.router import router  # re-exported for callers doing `from api.auth import router`
except Exception as _router_import_err:  # pragma: no cover
    from fastapi import APIRouter as _APIRouter

    router = _APIRouter(prefix="/api/auth", tags=["Authentication"])
    logger.warning("auth.router unavailable, using empty fallback router: %s", _router_import_err)

__all__ = ["router", "TokenPayload", "get_current_user", "require_role"]

# Role hierarchy: higher index = more privileged
_ROLE_RANK: dict = {"user": 0, "trader": 1, "admin": 2, "superadmin": 3}
# Stable per-role dependency callables — same object identity on every call,
# required for FastAPI dependency_overrides to work correctly in tests.
_ROLE_DEPS: dict = {}

ALLOWED_SYMBOLS = frozenset(
    os.getenv(
        "ALLOWED_SYMBOLS",
        "XAUUSD,EURUSD,GBPUSD,USDJPY,BTCUSD,AUDUSD,USDCHF",
    ).split(","),
)
MAX_ORDER_QUANTITY = float(os.getenv("MAX_ORDER_QUANTITY", "100.0"))


class TokenPayload(BaseModel):
    sub: str  # user_id
    role: str = "user"
    exp: int | None = None
    iat: int | None = None


def _get_jwt_secret() -> str:
    secret = os.getenv("SECURITY_JWT_SECRET") or os.getenv("JWT_SECRET")
    if not secret:
        raise RuntimeError(
            "SECURITY_JWT_SECRET environment variable is not set. "
            'Generate one with: python -c "import secrets; print(secrets.token_hex(32))"',
        )
    if len(secret) < 32:
        raise RuntimeError("SECURITY_JWT_SECRET must be at least 32 characters")
    return secret


def _decode_token(token: str) -> TokenPayload:
    """Decode and validate a JWT bearer token, checking the revocation blacklist."""
    try:
        secret = _get_jwt_secret()
        payload = jwt.decode(
            token,
            secret,
            algorithms=["HS256"],
            options={"require": ["sub", "exp"]},
        )

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
                # Fail-closed: if the blacklist store (Redis) is unavailable we
                # cannot confirm the token has not been revoked.  Reject the
                # request with 503 so a revoked credential can never authorize
                # a trade through a Redis outage.
                logger.critical(
                    "Token blacklist unavailable — rejecting token to fail-closed: %s",
                    exc,
                )
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail="Auth service temporarily unavailable",
                ) from exc

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


def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(_bearer),
) -> TokenPayload:
    """Dependency: any authenticated user."""
    return _decode_token(credentials.credentials)


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
    """Validate symbol is in the allowed set (prevents injection via symbol field)."""
    upper = symbol.upper().strip()
    if upper not in ALLOWED_SYMBOLS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Symbol '{symbol}' is not permitted. Allowed: {sorted(ALLOWED_SYMBOLS)}",
        )
    return upper


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

    Checks app_state.compliance_manager if available on the request's app state.
    If compliance_manager is not wired (tests / paper trading), passes through.

    Usage:
        @router.post("/order")
        async def place_order(user: TokenPayload = Depends(require_kyc)):
            ...
    """
    try:
        # Resolve compliance_manager from the request's app state so that
        # test apps (which have no compliance_manager) bypass the check.
        from app import app as _main_app
        from app import app_state

        if request.app is not _main_app:
            return user  # not the main app — skip KYC (test / embedded app)
        if app_state.compliance_manager is not None and not app_state.compliance_manager.is_kyc_approved(user.sub):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="KYC verification required before trading. Please complete identity verification.",
            )
    except ImportError:
        pass  # app not fully initialised (e.g. during tests)
    return user
