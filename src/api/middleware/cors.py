"""
Enhanced CORS middleware with security headers.
"""

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware


class EnhancedCORSMiddleware(BaseHTTPMiddleware):
    """
    CORS with additional security headers and origin validation.
    """
    
    def __init__(
        self,
        app,
        allow_origins: list[str] | None = None,
        allow_credentials: bool = True,
        allow_methods: list[str] | None = None,
        allow_headers: list[str] | None = None,
        max_age: int = 600
    ):
        super().__init__(app)
        
        self.allow_origins = allow_origins or ["https://hopefx.trading"]
        self.allow_credentials = allow_credentials
        self.allow_methods = allow_methods or ["GET", "POST", "PUT", "DELETE", "OPTIONS"]
        self.allow_headers = allow_headers or ["*"]
        self.max_age = max_age
        
        # Security headers
        self.security_headers = {
            "X-Content-Type-Options": "nosniff",
            "X-Frame-Options": "DENY",
            "X-XSS-Protection": "1; mode=block",
            "Strict-Transport-Security": "max-age=31536000; includeSubDomains",
            "Referrer-Policy": "strict-origin-when-cross-origin",
            "Permissions-Policy": "geolocation=(), microphone=(), camera=()",
        }
    
    async def dispatch(self, request: Request, call_next):
        origin = request.headers.get("origin")
        
        # Validate origin
        if origin and origin not in self.allow_origins:
            # Check wildcard
            allowed = any(
                o == "*" or (o.startswith("*.") and origin.endswith(o[1:]))
                for o in self.allow_origins
            )
            if not allowed:
                origin = None
        
        # Handle preflight
        if request.method == "OPTIONS":
            response = Response()
            self._set_cors_headers(response, origin)
            return response
        
        # Process request
        response = await call_next(request)
        
        # Set CORS headers
        self._set_cors_headers(response, origin)
        
        # Add security headers
        for header, value in self.security_headers.items():
            response.headers[header] = value
        
        return response
    
    def _set_cors_headers(self, response: Response, origin: str | None) -> None:
        """Set CORS headers on response."""
        if origin:
            response.headers["Access-Control-Allow-Origin"] = origin
        
        if self.allow_credentials:
            response.headers["Access-Control-Allow-Credentials"] = "true"
        
        response.headers["Access-Control-Allow-Methods"] = ", ".join(self.allow_methods)
        response.headers["Access-Control-Allow-Headers"] = ", ".join(self.allow_headers)
        response.headers["Access-Control-Max-Age"] = str(self.max_age)
