"""
JWT authentication middleware.
"""

from fastapi import Request, HTTPException
from starlette.middleware.base import BaseHTTPMiddleware

from src.infrastructure.security import decode_jwt_token


class JWTAuthMiddleware(BaseHTTPMiddleware):
    """JWT validation middleware."""
    
    async def dispatch(self, request: Request, call_next):
        # Skip auth for public endpoints
        if request.url.path in ["/health", "/docs", "/openapi.json", "/metrics"]:
            return await call_next(request)
        
        auth_header = request.headers.get("Authorization")
        if not auth_header or not auth_header.startswith("Bearer "):
            raise HTTPException(status_code=401, detail="Missing or invalid authorization header")
        
        token = auth_header.replace("Bearer ", "")
        
        try:
            payload = decode_jwt_token(token)
            request.state.user = payload.get("sub")
            request.state.claims = payload
        except Exception as e:
            raise HTTPException(status_code=401, detail=f"Invalid token: {e}")
        
        return await call_next(request)
