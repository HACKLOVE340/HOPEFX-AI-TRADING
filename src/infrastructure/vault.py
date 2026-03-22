"""
Encryption vault using Fernet for secure credential storage.
"""
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
import base64
import os
from typing import Optional
from src.config.settings import get_settings

settings = get_settings()


class Vault:
    """Secure encryption vault for sensitive data."""
    
    def __init__(self, key: Optional[str] = None):
        if key is None:
            key = settings.security.encryption_key.get_secret_value()
        
        # Derive Fernet key from provided key
        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,
            salt=os.urandom(16),
            iterations=480000,
        )
        key_bytes = base64.urlsafe_b64encode(kdf.derive(key.encode()))
        self._fernet = Fernet(key_bytes)
    
    def encrypt(self, plaintext: str) -> str:
        """Encrypt string data."""
        return self._fernet.encrypt(plaintext.encode()).decode()
    
    def decrypt(self, ciphertext: str) -> str:
        """Decrypt string data."""
        return self._fernet.decrypt(ciphertext.encode()).decode()
    
    def encrypt_dict(self, data: dict) -> dict:
        """Encrypt all string values in a dictionary."""
        return {k: self.encrypt(v) if isinstance(v, str) else v 
                for k, v in data.items()}
    
    def decrypt_dict(self, data: dict) -> dict:
        """Decrypt all string values in a dictionary."""
        return {k: self.decrypt(v) if isinstance(v, str) else v 
                for k, v in data.items()}


# Global vault instance
_vault: Optional[Vault] = None


def get_vault() -> Vault:
    """Get or create vault singleton."""
    global _vault
    if _vault is None:
        _vault = Vault()
    return _vault
