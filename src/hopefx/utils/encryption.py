# src/hopefx/utils/encryption.py
"""
Fernet encryption for sensitive data at rest.
"""
from __future__ import annotations

import base64
import hashlib
from typing import Union

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

from hopefx.config.settings import settings


class SecureVault:
    """
    Encryption/decryption for sensitive data.
    Uses Fernet (AES-128-CBC + HMAC-SHA256).
    """
    
    def __init__(self):
        self._fernet: Fernet | None = None
        self._init_encryption()
    
    def _init_encryption(self) -> None:
        """Initialize Fernet with settings key."""
        if settings.security.encryption_key:
            key = settings.security.encryption_key.get_secret_value()
            self._fernet = Fernet(key.encode())
    
    def encrypt(self, data: Union[str, bytes]) -> str:
        """
        Encrypt data.
        
        Args:
            data: String or bytes to encrypt
            
        Returns:
            Base64-encoded encrypted string
        """
        if self._fernet is None:
            raise RuntimeError("Encryption not initialized")
        
        if isinstance(data, str):
            data = data.encode()
        
        encrypted = self._fernet.encrypt(data)
        return base64.urlsafe_b64encode(encrypted).decode()
    
    def decrypt(self, token: str) -> str:
        """
        Decrypt data.
        
        Args:
            token: Base64-encoded encrypted string
            
        Returns:
            Decrypted string
        """
        if self._fernet is None:
            raise RuntimeError("Encryption not initialized")
        
        try:
            encrypted = base64.urlsafe_b64decode(token.encode())
            decrypted = self._fernet.decrypt(encrypted)
            return decrypted.decode()
        except InvalidToken:
            raise ValueError("Invalid or expired encryption token")
    
    def hash_sensitive(self, data: str, salt: str | None = None) -> str:
        """
        One-way hash for sensitive identifiers (PII).
        Uses SHA-256 with salt.
        """
        if salt is None:
            salt = settings.security.secret_key.get_secret_value()[:16]
        
        combined = f"{salt}{data}".encode()
        return hashlib.sha256(combined).hexdigest()
    
    @staticmethod
    def generate_key() -> str:
        """Generate new encryption key."""
        return Fernet.generate_key().decode()


# Global instance
_vault: SecureVault | None = None


def get_vault() -> SecureVault:
    """Get or create secure vault."""
    global _vault
    if _vault is None:
        _vault = SecureVault()
    return _vault
