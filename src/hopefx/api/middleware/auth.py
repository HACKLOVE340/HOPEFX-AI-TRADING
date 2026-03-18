from __future__ import annotations

from fastapi import Request, HTTPException
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import JWTError, jwt
from starlette.middleware.base import BaseHTTPMiddleware

from hopefx.config.settings import settings

security = HTTPBearer()


class JWTAuthMiddleware(BaseHTTPMiddleware):
    """JWT authentication middleware."""

    async def dispatch(self, request: Request, call_next):
        # Skip auth for health endpoints
        if request.url.path in ["/health", "/api/v1/health", "/docs", "/openapi.json", "/metrics"]:
            return await call_next(request)

        auth = request.headers.get("authorization")
        if not auth:
            raise HTTPException(status_code=401, detail="Missing authorization header")

        try:
            scheme, token = auth.split()
            if scheme.lower() != "bearer":
                raise HTTPException(status_code=401, detail="Invalid scheme")

            payload = jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
            request.state.user = payload.get("sub")
        except (ValueError, JWTError) as e:
            raise HTTPException(status_code=401, detail=f"Invalid token: {e}")

        return await call_next(request)
