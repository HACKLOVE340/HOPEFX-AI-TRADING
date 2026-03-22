from __future__ import annotations

import os

from fastapi import Request, HTTPException
from fastapi.security import HTTPBearer
from starlette.middleware.base import BaseHTTPMiddleware

security = HTTPBearer()

_SKIP_PATHS = {"/health", "/api/v1/health", "/docs", "/openapi.json", "/metrics", "/redoc"}


class JWTAuthMiddleware(BaseHTTPMiddleware):
    """JWT authentication middleware — uses SECURITY_JWT_SECRET shared with main app."""

    async def dispatch(self, request: Request, call_next):
        if request.url.path in _SKIP_PATHS:
            return await call_next(request)

        auth = request.headers.get("authorization")
        if not auth:
            raise HTTPException(status_code=401, detail="Missing authorization header")

        try:
            scheme, token = auth.split()
            if scheme.lower() != "bearer":
                raise HTTPException(status_code=401, detail="Invalid scheme")

            import jwt as _jwt
            secret = os.environ.get("SECURITY_JWT_SECRET", "")
            if not secret:
                from hopefx.config.settings import settings as _s
                secret = _s.jwt_secret
            payload = _jwt.decode(token, secret, algorithms=["HS256"])
            request.state.user = payload.get("sub")
        except (ValueError, Exception) as e:
            raise HTTPException(status_code=401, detail=f"Invalid token: {e}")

        return await call_next(request)
