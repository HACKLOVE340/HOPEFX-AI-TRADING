# security/production_config.py
"""
Production-grade configuration security
NO FALLBACK KEYS - Fail secure
"""

import os
import secrets
import sys
from typing import Optional

class SecureConfigError(Exception):
    """Raised when secure configuration cannot be established"""
    pass

class ProductionConfigManager:
    """
    Configuration manager that FAILS SECURE
    No default keys, no development fallbacks in production
    """
    
    def __init__(self, env: str = "production"):
        self.env = env
        self._encryption_key: Optional[bytes] = None
        self._salt: Optional[bytes] = None
        
    def initialize(self) -> None:
        """
        Initialize configuration - FAILS if secrets not provided
        """
        if self.env == "production":
            self._initialize_production()
        else:
            self._initialize_development()
    
    def _initialize_production(self) -> None:
        """Production: Strict requirements, no fallbacks"""
        # ENCRYPTION KEY
        key = os.getenv('HOPEFX_ENCRYPTION_KEY')
        if not key:
            raise SecureConfigError(
                "CRITICAL: HOPEFX_ENCRYPTION_KEY not set. "
                "Generate with: python -c \"import secrets; print(secrets.token_hex(32))\" "
                "Then export HOPEFX_ENCRYPTION_KEY=<generated_key>"
            )
        
        # Validate key strength
        try:
            key_bytes = bytes.fromhex(key)
            if len(key_bytes) < 32:
                raise SecureConfigError(f"Encryption key must be 32+ bytes, got {len(key_bytes)}")
        except ValueError:
            raise SecureConfigError("Encryption key must be valid hexadecimal")
        
        self._encryption_key = key_bytes
        
        # SALT
        salt = os.getenv('HOPEFX_SALT')
        if not salt:
            raise SecureConfigError(
                "CRITICAL: HOPEFX_SALT not set. "
                "Generate with: python -c \"import secrets; print(secrets.token_hex(16))\""
            )
        
        try:
            salt_bytes = bytes.fromhex(salt)
            if len(salt_bytes) < 16:
                raise SecureConfigError(f"Salt must be 16+ bytes, got {len(salt_bytes)}")
        except ValueError:
            raise SecureConfigError("Salt must be valid hexadecimal")
        
        self._salt = salt_bytes
        
        # Additional production checks
        self._validate_production_environment()
    
    def _validate_production_environment(self) -> None:
        """Validate production environment security"""
        checks = []
        
        # Check for debug mode
        debug = os.getenv('DEBUG', 'false').lower()
        if debug in ['true', '1', 'yes']:
            raise SecureConfigError("DEBUG mode must be disabled in production")
        
        # Check for secure database URL
        db_url = os.getenv('DATABASE_URL', '')
        if 'localhost' in db_url or '127.0.0.1' in db_url:
            raise SecureConfigError("Production must use external database, not localhost")
        
        # Check for HTTPS
        api_url = os.getenv('API_BASE_URL', '')
        if api_url and not api_url.startswith('https://'):
            raise SecureConfigError("Production API must use HTTPS")
        
        # Check for weak JWT secret
        jwt_secret = os.getenv('JWT_SECRET_KEY', '')
        if len(jwt_secret) < 32:
            raise SecureConfigError("JWT_SECRET_KEY must be at least 32 characters")
    
    def _initialize_development(self) -> None:
        """Development: Generate temporary keys with warnings"""
        import warnings
        warnings.warn("DEVELOPMENT MODE: Using auto-generated temporary keys", RuntimeWarning)
        
        self._encryption_key = secrets.token_bytes(32)
        self._salt = secrets.token_bytes(16)
        
        print("=" * 70)
        print("DEVELOPMENT KEYS GENERATED (DO NOT USE IN PRODUCTION)")
        print(f"Encryption Key: {self._encryption_key.hex()}")
        print(f"Salt: {self._salt.hex()}")
        print("Set these in environment for persistence")
        print("=" * 70)
    
    @property
    def encryption_key(self) -> bytes:
        if self._encryption_key is None:
            raise SecureConfigError("Configuration not initialized")
        return self._encryption_key
    
    @property
    def salt(self) -> bytes:
        if self._salt is None:
            raise SecureConfigError("Configuration not initialized")
        return self._salt


# Update main.py to use secure config
def initialize_secure_config():
    """Initialize with fail-secure configuration"""
    env = os.getenv('HOPEFX_ENV', 'production')
    
    try:
        config_manager = ProductionConfigManager(env=env)
        config_manager.initialize()
        return config_manager
    except SecureConfigError as e:
        logger.critical(f"Configuration error: {e}")
        sys.exit(1)  # HARD FAIL - No insecure fallbacks
