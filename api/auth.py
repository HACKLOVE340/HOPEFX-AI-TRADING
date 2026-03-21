"""
API authentication dependencies for HOPEFX trading endpoints.

Provides JWT-based bearer token verification with role-based access control.
All trading-mutating endpoints must use require_role("trader") or higher.
Read-only endpoints use get_current_user.

Token generation is handled externally (login endpoint / mobile auth).
"""

import os
import logging
from datetime import datetime, timezone
from typing import Optional

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel

logger = logging.getLogger(__name__)

_bearer = HTTPBearer(auto_error=True)

# Role hierarchy: higher index = more privileged
_ROLE_RANK = {"user": 0, "trader": 1, "admin": 2, "superadmin": 3}

ALLOWED_SYMBOLS = frozenset(
    os.getenv("ALLOWED_SYMBOLS", "XAUUSD,EURUSD,GBPUSD,USDJPY,BTCUSD,AUDUSD,USDCHF").split(",")
)
MAX_ORDER_QUANTITY = float(os.getenv("MAX_ORDER_QUANTITY", "100.0"))


class TokenPayload(BaseModel):
    sub: str          # user_id
    role: str = "user"
    exp: Optional[int] = None
    iat: Optional[int] = None


def _get_jwt_secret() -> str:
    secret = os.getenv("SECURITY_JWT_SECRET") or os.getenv("JWT_SECRET")
    if not secret:
        raise RuntimeError(
            "SECURITY_JWT_SECRET environment variable is not set. "
            "Generate one with: python -c \"import secrets; print(secrets.token_hex(32))\""
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
            except Exception:
                pass  # blacklist unavailable — allow token (fail open)

        return TokenPayload(**payload)
    except HTTPException:
        raise
    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token expired",
            headers={"WWW-Authenticate": "Bearer"},
        )
    except jwt.InvalidTokenError as exc:
        logger.warning("Invalid JWT token: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    except RuntimeError as exc:
        logger.critical("JWT secret misconfiguration: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Authentication service misconfigured",
        )


def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(_bearer),
) -> TokenPayload:
    """Dependency: any authenticated user."""
    return _decode_token(credentials.credentials)


def require_role(minimum_role: str):
    """
    Dependency factory: require caller to hold at least `minimum_role`.

    Usage:
        @router.post("/order")
        async def place_order(user: TokenPayload = Depends(require_role("trader"))):
            ...
    """
    def _check(user: TokenPayload = Depends(get_current_user)) -> TokenPayload:
        caller_rank = _ROLE_RANK.get(user.role, -1)
        required_rank = _ROLE_RANK.get(minimum_role, 999)
        if caller_rank < required_rank:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Role '{minimum_role}' required, caller has '{user.role}'",
            )
        return user

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


def require_kyc(user: TokenPayload = Depends(get_current_user)) -> TokenPayload:
    """
    Dependency: require the caller to have passed KYC verification.

    Checks app_state.compliance_manager if available.
    If compliance_manager is not wired (tests / paper trading), passes through.

    Usage:
        @router.post("/order")
        async def place_order(user: TokenPayload = Depends(require_kyc)):
            ...
    """
    try:
        # Import here to avoid circular imports at module load time
        from app import app_state
        if app_state.compliance_manager is not None:
            if not app_state.compliance_manager.is_kyc_approved(user.sub):
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="KYC verification required before trading. "
                           "Please complete identity verification.",
                )
    except ImportError:
        pass  # app not fully initialised (e.g. during tests)
    return user
