from __future__ import annotations

from fastapi import Request, HTTPException
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from starlette.middleware.base import BaseHTTPMiddleware

limiter = Limiter(key_func=get_remote_address)


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Rate limiting middleware."""

    async def dispatch(self, request: Request, call_next):
        # Use slowapi decorator on routes instead
        return await call_next(request)
