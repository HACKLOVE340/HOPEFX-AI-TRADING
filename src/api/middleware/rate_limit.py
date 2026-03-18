"""
Rate limiting middleware using Redis sliding window.
"""
import time
from typing import Optional
from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp

import structlog

logger = structlog.get_logger()


class RateLimitMiddleware(BaseHTTPMiddleware):
    """
    Sliding window rate limiter.
    Default: 100 requests per minute per IP.
    """
    
    def __init__(self, app: ASGIApp, requests_per_minute: int = 100):
        super().__init__(app)
        self.requests_per_minute = requests_per_minute
        self.window_size = 60  # seconds
        
    async def dispatch(self, request: Request, call_next):
        # Skip rate limiting for health checks
        if request.url.path == "/health":
            return await call_next(request)
        
        client_ip = request.client.host if request.client else "unknown"
        key = f"rate_limit:{client_ip}"
        
        # Get Redis from app state
        redis = getattr(request.app.state, "cache", None)
        
        if redis:
            current = await redis.increment(key, 1)
            if current == 1:
                await redis.expire(key, self.window_size)
            
            if current > self.requests_per_minute:
                logger.warning("rate_limit_exceeded", ip=client_ip, count=current)
                return Response(
                    content='{"detail": "Rate limit exceeded"}',
                    status_code=429,
                    media_type="application/json",
                    headers={"Retry-After": str(self.window_size)}
                )
        
        response = await call_next(request)
        
        # Add rate limit headers
        if redis:
            remaining = max(0, self.requests_per_minute - (await redis.get(key) or 0))
            response.headers["X-RateLimit-Limit"] = str(self.requests_per_minute)
            response.headers["X-RateLimit-Remaining"] = str(remaining)
        
        return response
