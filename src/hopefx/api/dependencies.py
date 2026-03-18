# src/hopefx/api/dependencies.py
"""
FastAPI dependencies for authentication and authorization.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Optional

from fastapi import Depends, HTTPException, status, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import JWTError, jwt
from pydantic import BaseModel

from hopefx.config.settings import settings

security = HTTPBearer()


class TokenData(BaseModel):
    """JWT token payload."""
    user_id: str
    email: str
    roles: list[str]
    exp: datetime


class User(BaseModel):
    """Authenticated user."""
    id: str
    email: str
    roles: list[str]
    is_active: bool = True
    
    def has_permission(self, permission: str) -> bool:
        """Check if user has specific permission."""
        # Admin has all permissions
        if "admin" in self.roles:
            return True
        return permission in self.roles


def create_access_token(user_id: str, email: str, roles: list[str]) -> str:
    """
    Create JWT access token.
    
    Args:
        user_id: User identifier
        email: User email
        roles: List of role strings
        
    Returns:
        JWT token string
    """
    expire = datetime.utcnow() + timedelta(
        minutes=settings.security.access_token_expire_minutes
    )
    
    to_encode = {
        "sub": user_id,
        "email": email,
        "roles": roles,
        "exp": expire,
        "iat": datetime.utcnow(),
        "type": "access"
    }
    
    return jwt.encode(
        to_encode,
        settings.security.secret_key.get_secret_value(),
        algorithm=settings.security.algorithm
    )


def verify_token(token: str) -> TokenData:
    """
    Verify and decode JWT token.
    
    Args:
        token: JWT token string
        
    Returns:
        TokenData with user info
        
    Raises:
        HTTPException: If token is invalid
    """
    try:
        payload = jwt.decode(
            token,
            settings.security.secret_key.get_secret_value(),
            algorithms=[settings.security.algorithm]
        )
        
        user_id: str = payload.get("sub")
        email: str = payload.get("email")
        roles: list = payload.get("roles", [])
        exp = payload.get("exp")
        
        if user_id is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid authentication credentials",
                headers={"WWW-Authenticate": "Bearer"},
            )
        
        return TokenData(
            user_id=user_id,
            email=email,
            roles=roles,
            exp=datetime.fromtimestamp(exp)
        )
        
    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security)
) -> User:
    """
    Dependency to get current authenticated user.
    
    Usage:
        @app.get("/protected")
        async def protected_route(user: User = Depends(get_current_user)):
            return {"message": f"Hello {user.email}"}
    """
    token_data = verify_token(credentials.credentials)
    
    # Here you would fetch user from database
    # For now, create user from token
    return User(
        id=token_data.user_id,
        email=token_data.email,
        roles=token_data.roles
    )


def require_roles(required_roles: list[str]):
    """
    Factory for role-based access control dependency.
    
    Usage:
        @app.delete("/admin/users")
        async def delete_user(
            user: User = Depends(require_roles(["admin"]))
        ):
            pass
    """
    async def role_checker(user: User = Depends(get_current_user)) -> User:
        if not any(role in user.roles for role in required_roles):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Required roles: {required_roles}"
            )
        return user
    return role_checker


async def get_rate_limit_key(request: Request) -> str:
    """
    Generate rate limit key based on user or IP.
    """
    # Try to get user from request state (set by auth middleware)
    user_id = getattr(request.state, "user_id", None)
    if user_id:
        return f"ratelimit:user:{user_id}"
    
    # Fall back to IP
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        ip = forwarded.split(",")[0].strip()
    else:
        ip = request.client.host if request.client else "unknown"
    
    return f"ratelimit:ip:{ip}"
