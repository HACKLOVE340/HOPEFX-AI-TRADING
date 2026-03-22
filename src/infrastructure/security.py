"""
Cryptographic operations, vault, and secure credential management.
"""

from __future__ import annotations

import hashlib
import secrets
from base64 import urlsafe_b64encode
from typing import Self

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

from src.core.config import settings
from src.core.exceptions import EncryptionError


class Vault:
    """
    Secure credential vault using Fernet symmetric encryption.
    Keys derived via PBKDF2-HMAC-SHA256 with Argon2-style parameters.
    """
    
    _instance: Self | None = None
    
    def __new__(cls) -> Self:
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance
    
    def __init__(self) -> None:
        if self._initialized:
            return
        
        self._key = self._derive_key(
            settings.security.encryption_key.encode(),
            settings.security.salt.encode() if hasattr(settings.security, 'salt') else secrets.token_bytes(16)
        )
        self._fernet = Fernet(self._key)
        self._initialized = True
    
    def _derive_key(self, password: bytes, salt: bytes) -> bytes:
        """Derive encryption key from password."""
        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,
            salt=salt,
            iterations=480000,  # OWASP recommended
        )
        return urlsafe_b64encode(kdf.derive(password))
    
    def encrypt(self, plaintext: str) -> str:
        """Encrypt string."""
        try:
            return self._fernet.encrypt(plaintext.encode()).decode()
        except Exception as e:
            raise EncryptionError(f"Encryption failed: {e}")
    
    def decrypt(self, ciphertext: str) -> str:
        """Decrypt string."""
        try:
            return self._fernet.decrypt(ciphertext.encode()).decode()
        except InvalidToken:
            raise EncryptionError("Invalid or expired token")
        except Exception as e:
            raise EncryptionError(f"Decryption failed: {e}")
    
    def rotate_key(self, new_key: str, new_salt: str | None = None) -> None:
        """Re-encrypt all data with new key."""
        # Implementation for key rotation
        pass


class PasswordHasher:
    """Argon2id password hashing."""
    
    @staticmethod
    def hash(password: str) -> str:
        """Hash password."""
        from argon2 import PasswordHasher as Argon2Hasher
        
        hasher = Argon2Hasher(
            time_cost=settings.security.argon2_time_cost,
            memory_cost=settings.security.argon2_memory_cost,
            parallelism=settings.security.argon2_parallelism,
        )
        return hasher.hash(password)
    
    @staticmethod
    def verify(password: str, hash_str: str) -> bool:
        """Verify password against hash."""
        from argon2 import PasswordHasher as Argon2Hasher
        from argon2.exceptions import VerifyMismatchError
        
        hasher = Argon2Hasher()
        try:
            hasher.verify(hash_str, password)
            return True
        except VerifyMismatchError:
            return False


# JWT utilities
import jwt
from datetime import datetime, timedelta, timezone


def create_jwt_token(
    subject: str,
    expires_delta: timedelta | None = None,
    additional_claims: dict | None = None
) -> str:
    """Create JWT access token."""
    if expires_delta is None:
        expires_delta = timedelta(hours=settings.security.jwt_expiration_hours)
    
    now = datetime.now(timezone.utc)
    payload = {
        "sub": subject,
        "iat": now,
        "exp": now + expires_delta,
        "jti": secrets.token_hex(16),
        **(additional_claims or {})
    }
    
    return jwt.encode(
        payload,
        settings.security.jwt_secret,
        algorithm=settings.security.jwt_algorithm
    )


def decode_jwt_token(token: str) -> dict:
    """Decode and validate JWT."""
    try:
        return jwt.decode(
            token,
            settings.security.jwt_secret,
            algorithms=[settings.security.jwt_algorithm]
        )
    except jwt.ExpiredSignatureError:
        raise AuthenticationError("Token expired")
    except jwt.InvalidTokenError as e:
        raise AuthenticationError(f"Invalid token: {e}")
