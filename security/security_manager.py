# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
Security Management
- XSS prevention
- CSRF protection
- Input validation
- Rate limiting
"""

import hashlib
import hmac
import logging
import secrets
import threading
import time
from datetime import datetime, timedelta, timezone

UTC = timezone.utc

logger = logging.getLogger(__name__)

# CSRF token TTL in seconds (default 1 hour)
_CSRF_TOKEN_TTL: int = int(__import__("os").getenv("CSRF_TOKEN_TTL", "3600"))


class SecurityManager:
    """Manage security measures"""

    def __init__(self, rate_limit_requests: int = 100, rate_limit_window: int = 3600):
        self.rate_limit_requests = rate_limit_requests
        self.rate_limit_window = rate_limit_window  # seconds
        self.request_log: dict[str, list] = {}
        # CSRF token store: user_id → (token_hex, issued_at_monotonic)
        self._csrf_store: dict[str, tuple[str, float]] = {}
        self._csrf_lock = threading.Lock()

    @staticmethod
    def sanitize_input(user_input: str) -> str:
        """Sanitize user input (XSS prevention)"""
        dangerous_chars = {
            "<": "&lt;",
            ">": "&gt;",
            '"': "&quot;",
            "'": "&#x27;",
            "&": "&amp;",
        }

        for char, safe in dangerous_chars.items():
            user_input = user_input.replace(char, safe)

        return user_input

    @staticmethod
    def validate_email(email: str) -> bool:
        """Validate email format"""
        import re

        pattern = r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$"
        return re.match(pattern, email) is not None

    @staticmethod
    def validate_password(password: str) -> bool:
        """Validate password strength"""
        if len(password) < 12:
            return False
        if not any(c.isupper() for c in password):
            return False
        if not any(c.isdigit() for c in password):
            return False
        return any(c in "!@#$%^&*" for c in password)

    def check_rate_limit(self, user_id: str) -> bool:
        """Check if user exceeded rate limit"""
        now = datetime.now(UTC)

        if user_id not in self.request_log:
            self.request_log[user_id] = []

        # Remove old requests
        cutoff = now - timedelta(seconds=self.rate_limit_window)
        self.request_log[user_id] = [req_time for req_time in self.request_log[user_id] if req_time > cutoff]

        if len(self.request_log[user_id]) >= self.rate_limit_requests:
            logger.warning(f"Rate limit exceeded for {user_id}")
            return False

        self.request_log[user_id].append(now)
        return True

    def generate_csrf_token(self, user_id: str) -> str:
        """
        Generate a CSRF token for *user_id* and store it server-side.

        The token is a 32-byte cryptographically random hex string (64 chars).
        It is bound to the user_id via an HMAC so that tokens cannot be
        reused across accounts even if intercepted.  A new call invalidates
        the previous token for that user.
        """
        raw = secrets.token_bytes(32)
        # HMAC-SHA256 binds the random bytes to the user_id
        mac = hmac.new(user_id.encode("utf-8"), raw, hashlib.sha256).hexdigest()
        with self._csrf_lock:
            self._csrf_store[user_id] = (mac, time.monotonic())
            self._evict_expired_csrf()
        return mac

    def verify_csrf_token(self, user_id: str, token: str) -> bool:
        """
        Verify a CSRF token for *user_id*.

        Returns True only when:
          1. A token was previously issued for this user_id.
          2. The provided token matches via constant-time comparison.
          3. The token has not expired (TTL = CSRF_TOKEN_TTL seconds).

        A length-only check (the previous implementation) allows any
        64-char string to pass — this replaces it with a real comparison.
        """
        if not token or len(token) != 64:
            return False
        with self._csrf_lock:
            entry = self._csrf_store.get(user_id)
        if entry is None:
            logger.warning("CSRF verify: no token on record for user %s", user_id[:8])
            return False
        stored_token, issued_at = entry
        if time.monotonic() - issued_at > _CSRF_TOKEN_TTL:
            logger.warning("CSRF verify: token expired for user %s", user_id[:8])
            with self._csrf_lock:
                self._csrf_store.pop(user_id, None)
            return False
        # Constant-time comparison prevents timing oracle attacks
        return hmac.compare_digest(stored_token, token)

    def _evict_expired_csrf(self) -> None:
        """Remove expired CSRF tokens (called under _csrf_lock)."""
        now = time.monotonic()
        expired = [uid for uid, (_, issued_at) in self._csrf_store.items() if now - issued_at > _CSRF_TOKEN_TTL]
        for uid in expired:
            del self._csrf_store[uid]
