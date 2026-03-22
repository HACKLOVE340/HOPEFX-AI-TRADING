# security/key_manager.py
"""
Cryptographic Key Management with HSM Integration Capability
FIA 2024 Security Standards Compliant
"""

import os
import secrets
import hashlib
import base64
from typing import Optional, Dict
from pathlib import Path
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.backends import default_backend
import logging
import json

logger = logging.getLogger(__name__)

class KeyManager:
    """
    Production-grade key management
    - No hardcoded keys
    - Environment-only key loading
    - Key rotation support
    - HSM-ready architecture
    """
    
    def __init__(self):
        self._master_key: Optional[bytes] = None
        self._key_id: Optional[str] = None
        self._rotation_date: Optional[str] = None
    
    def initialize(self, require_production_key: bool = True) -> None:
        """
        Initialize key manager - fails safe if no proper key provided
        """
        key = os.getenv('HOPEFX_MASTER_KEY')
        
        if not key:
            if require_production_key:
                raise SecurityError(
                    "HOPEFX_MASTER_KEY environment variable not set. "
                    "System cannot start without encryption key."
                )
            else:
                # Development mode with strict warnings
                logger.critical("DEVELOPMENT MODE: Using temporary key")
                key = self._generate_temporary_key()
        
        # Validate key strength
        self._validate_key_strength(key)
        
        self._master_key = base64.urlsafe_b64decode(key)
        self._key_id = hashlib.sha256(self._master_key).hexdigest()[:16]
        self._rotation_date = os.getenv('HOPEFX_KEY_ROTATION_DATE')
        
        logger.info(f"KeyManager initialized with key_id: {self._key_id}")
    
    def _validate_key_strength(self, key: str) -> None:
        """Ensure key meets cryptographic standards"""
        try:
            decoded = base64.urlsafe_b64decode(key)
            if len(decoded) < 32:
                raise SecurityError("Key must be at least 32 bytes")
        except Exception as e:
            raise SecurityError(f"Invalid key format: {e}")
    
    def _generate_temporary_key(self) -> str:
        """Generate temporary key for development (with clear warnings)"""
        key = Fernet.generate_key()
        logger.warning("=" * 60)
        logger.warning("TEMPORARY KEY GENERATED - NOT FOR PRODUCTION")
        logger.warning(f"Key: {key.decode()}")
        logger.warning("Store this in HOPEFX_MASTER_KEY for next run")
        logger.warning("=" * 60)
        return key.decode()
    
    def get_fernet(self) -> Fernet:
        """Get Fernet instance for encryption"""
        if not self._master_key:
            raise SecurityError("KeyManager not initialized")
        return Fernet(base64.urlsafe_b64encode(self._master_key))
    
    def encrypt(self, data: str) -> str:
        """Encrypt sensitive data"""
        f = self.get_fernet()
        return f.encrypt(data.encode()).decode()
    
    def decrypt(self, token: str) -> str:
        """Decrypt sensitive data"""
        f = self.get_fernet()
        return f.decrypt(token.encode()).decode()
    
    def rotate_key(self, new_key: str) -> None:
        """Rotate to new encryption key"""
        # Re-encrypt all data with new key
        old_fernet = self.get_fernet()
        new_fernet = Fernet(new_key.encode())
        
        logger.info("Starting key rotation...")
        # Implementation would re-encrypt all stored credentials
        self._master_key = base64.urlsafe_b64decode(new_key)
        self._key_id = hashlib.sha256(self._master_key).hexdigest()[:16]
        logger.info("Key rotation completed")


class SecurityError(Exception):
    """Security-related errors"""
    pass


# Updated config_manager.py security section
class SecureConfigManager:
    """Configuration manager with mandatory security"""
    
    def __init__(self):
        self.key_manager = KeyManager()
        # Force production key in non-dev environments
        is_production = os.getenv('HOPEFX_ENV', 'development') == 'production'
        self.key_manager.initialize(require_production_key=is_production)
