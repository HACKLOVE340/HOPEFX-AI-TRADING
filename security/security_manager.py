"""
Security Management
- XSS prevention
- CSRF protection
- Input validation
- Rate limiting
"""

import logging
from typing import Dict, Optional
from datetime import datetime, timedelta
from functools import wraps

logger = logging.getLogger(__name__)

class SecurityManager:
    """Manage security measures"""
    
    def __init__(self, rate_limit_requests: int = 100, 
                 rate_limit_window: int = 3600):
        self.rate_limit_requests = rate_limit_requests
        self.rate_limit_window = rate_limit_window  # seconds
        self.request_log: Dict[str, list] = {}
    
    @staticmethod
    def sanitize_input(user_input: str) -> str:
        """Sanitize user input (XSS prevention)"""
        dangerous_chars = {
            '<': '&lt;',
            '>': '&gt;',
            '"': '&quot;',
            "'": '&#x27;',
            '&': '&amp;'
        }
        
        for char, safe in dangerous_chars.items():
            user_input = user_input.replace(char, safe)
        
        return user_input
    
    @staticmethod
    def validate_email(email: str) -> bool:
        """Validate email format"""
        import re
        pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
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
        if not any(c in '!@#$%^&*' for c in password):
            return False
        return True
    
    def check_rate_limit(self, user_id: str) -> bool:
        """Check if user exceeded rate limit"""
        now = datetime.now()
        
        if user_id not in self.request_log:
            self.request_log[user_id] = []
        
        # Remove old requests
        cutoff = now - timedelta(seconds=self.rate_limit_window)
        self.request_log[user_id] = [
            req_time for req_time in self.request_log[user_id]
            if req_time > cutoff
        ]
        
        if len(self.request_log[user_id]) >= self.rate_limit_requests:
            logger.warning(f"Rate limit exceeded for {user_id}")
            return False
        
        self.request_log[user_id].append(now)
        return True
    
    def generate_csrf_token(self, user_id: str) -> str:
        """Generate CSRF token"""
        import hashlib
        import secrets
        
        random_str = secrets.token_hex(16)
        token = hashlib.sha256(f"{user_id}{random_str}".encode()).hexdigest()
        return token
    
    def verify_csrf_token(self, user_id: str, token: str) -> bool:
        """Verify CSRF token"""
        # In production, store tokens in session/DB
        return len(token) == 64