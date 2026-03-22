"""Web Application Firewall rules."""

from __future__ import annotations

import re
from typing import Optional

from fastapi import Request, HTTPException
from starlette.middleware.base import BaseHTTPMiddleware


class WAFMiddleware(BaseHTTPMiddleware):
    """Basic WAF protection."""

    # SQL Injection patterns
    SQLI_PATTERNS = [
        r"(\%27)|(\')|(\-\-)|(\%23)|(#)",
        r"((\%3D)|(=))[^\n]*((\%27)|(\')|(\-\-)|(\%3B)|(;))",
        r"\w*((\%27)|(\'))((\%6F)|o|(\%4F))((\%72)|r|(\%52))",
        r"((\%27)|(\'))union",
        r"exec(\s|\+)+(s|x)p\w+",
        r"UNION\s+SELECT",
        r"INSERT\s+INTO",
        r"DELETE\s+FROM",
        r"DROP\s+TABLE",
    ]

    # XSS patterns
    XSS_PATTERNS = [
        r"<script[^>]*>[\s\S]*?</script>",
        r"javascript:",
        r"on\w+\s*=",
        r"<iframe",
        r"<object",
        r"<embed",
    ]

    # Path traversal
    PATH_TRAVERSAL = [
        r"\.\./",
        r"\.\.\\",
        r"%2e%2e%2f",
        r"%252e%252e%252f",
    ]

    def __init__(self, app, block_mode: bool = True):
        super().__init__(app)
        self.block_mode = block_mode
        self._compile_patterns()

    def _compile_patterns(self) -> None:
        """Compile regex patterns."""
        self._sqli = [re.compile(p, re.IGNORECASE) for p in self.SQLI_PATTERNS]
        self._xss = [re.compile(p, re.IGNORECASE) for p in self.XSS_PATTERNS]
        self._traversal = [re.compile(p, re.IGNORECASE) for p in self.PATH_TRAVERSAL]

    async def dispatch(self, request: Request, call_next):
        """Check request for attacks."""
        # Check path
        path = request.url.path
        if self._check_path_traversal(path):
            await self._block(request, "path_traversal")
            raise HTTPException(403, "Security violation detected")

        # Check query params
        query = str(request.query_params)
        if self._check_sqli(query) or self._check_xss(query):
            await self._block(request, "injection_attempt")
            raise HTTPException(403, "Security violation detected")

        # Check body for POST/PUT
        if request.method in ("POST", "PUT", "PATCH"):
            body = await request.body()
            body_str = body.decode("utf-8", errors="ignore")
            
            if self._check_sqli(body_str) or self._check_xss(body_str):
                await self._block(request, "injection_attempt")
                raise HTTPException(403, "Security violation detected")

        return await call_next(request)

    def _check_sqli(self, text: str) -> bool:
        """Check for SQL injection."""
        return any(p.search(text) for p in self._sqli)

    def _check_xss(self, text: str) -> bool:
        """Check for XSS."""
        return any(p.search(text) for p in self._xss)

    def _check_path_traversal(self, path: str) -> bool:
        """Check for path traversal."""
        return any(p.search(path) for p in self._traversal)

    async def _block(self, request: Request, reason: str) -> None:
        """Log and block request."""
        # Log to security audit
        # Rate limit by IP
        # Potentially ban IP
        pass
