# src/hopefx/api/dependencies.py
"""
FastAPI auth dependencies — delegates to the main app's auth.service so both
entry points share the same JWT logic and secret.
"""
from __future__ import annotations

import os
from datetime import datetime
from typing import Optional

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel

security = HTTPBearer()


class TokenData(BaseModel):
    user_id: str
    email: str
    roles: list[str]
    exp: datetime


class User(BaseModel):
    id: str
    email: str
    roles: list[str]
    is_active: bool = True

    def has_permission(self, permission: str) -> bool:
        if "admin" in self.roles:
            return True
        return permission in self.roles


def _decode(token: str) -> dict:
    """Decode a JWT using SECURITY_JWT_SECRET (shared with main app)."""
    try:
        import jwt as _jwt
        secret = os.environ.get("SECURITY_JWT_SECRET", "")
        if not secret:
            from hopefx.config.settings import settings as _s
            secret = _s.jwt_secret
        return _jwt.decode(token, secret, algorithms=["HS256"])
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid token: {exc}",
            headers={"WWW-Authenticate": "Bearer"},
        )


def verify_token(token: str) -> TokenData:
    payload = _decode(token)
    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")
    return TokenData(
        user_id=user_id,
        email=payload.get("email", ""),
        roles=payload.get("roles", [payload.get("role", "user")]),
        exp=datetime.fromtimestamp(payload.get("exp", 0)),
    )


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
) -> User:
    token_data = verify_token(credentials.credentials)
    return User(id=token_data.user_id, email=token_data.email, roles=token_data.roles)


def require_roles(required_roles: list[str]):
    async def role_checker(user: User = Depends(get_current_user)) -> User:
        if not any(r in user.roles for r in required_roles):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Required roles: {required_roles}",
            )
        return user
    return role_checker


async def get_rate_limit_key(request: Request) -> str:
    user_id = getattr(request.state, "user_id", None)
    if user_id:
        return f"ratelimit:user:{user_id}"
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        ip = forwarded.split(",")[0].strip()
    else:
        ip = request.client.host if request.client else "unknown"
    return f"ratelimit:ip:{ip}"
