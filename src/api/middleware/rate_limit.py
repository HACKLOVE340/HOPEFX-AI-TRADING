"""
Rate limiting middleware using slowapi pattern.
"""

import time
from collections import defaultdict

from fastapi import Request, HTTPException
from starlette.middleware.base import BaseHTTPMiddleware


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Simple in-memory rate limiting."""
    
    def __init__(self, app, requests_per_minute: int = 60):
        super().__init__(app)
        self.requests_per_minute = requests_per_minute
        self._requests: defaultdict[str, list[float]] = defaultdict(list)
    
    async def dispatch(self, request: Request, call_next):
        client_ip = request.client.host if request.client else "unknown"
        now = time.time()
        
        # Clean old requests
        self._requests[client_ip] = [
            ts for ts in self._requests[client_ip]
            if now - ts < 60
        ]
        
        # Check limit
        if len(self._requests[client_ip]) >= self.requests_per_minute:
            raise HTTPException(status_code=429, detail="Rate limit exceeded")
        
        self._requests[client_ip].append(now)
        
        return await call_next(request)
