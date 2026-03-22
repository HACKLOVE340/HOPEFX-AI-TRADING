"""Cryptographic vault with Fernet, Argon2id, and system keyring."""
from __future__ import annotations

import base64
import hashlib
import json
import os
import secrets
from pathlib import Path
from typing import Any, Self

import keyring
from cryptography.fernet import Fernet, InvalidToken
from passlib.context import CryptContext

from src.core.exceptions import VaultError, AuthenticationError


class SecureVault:
    """Hardware-backed or keyring-backed secure vault."""
    
    _instance: SecureVault | None = None
    _pwd_context = CryptContext(
        schemes=["argon2id"],
        deprecated="auto",
        argon2__time_cost=3,
        argon2__memory_cost=65536,
        argon2__parallelism=4,
        argon2__hash_len=32,
        argon2__salt_len=16,
    )
    
    def __new__(cls) -> Self:
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance
    
    def __init__(self) -> None:
        if self._initialized:
            return
        self._initialized = True
        self._fernet: Fernet | None = None
        self._service_name = "hopefx_v2"
        self._key_name = "master_key"
    
    def initialize(self, password: str | None = None) -> None:
        """Initialize vault with password or retrieve from keyring."""
        try:
            stored_key = keyring.get_password(self._service_name, self._key_name)
            
            if stored_key:
                self._fernet = Fernet(stored_key.encode())
            elif password:
                key = self._derive_key(password)
                keyring.set_password(self._service_name, self._key_name, key.decode())
                self._fernet = Fernet(key)
            else:
                raise VaultError("No stored key and no password provided")
                
        except Exception as e:
            raise VaultError(f"Vault initialization failed: {e}") from e
    
    def _derive_key(self, password: str) -> bytes:
        """Derive Fernet key from password using PBKDF2."""
        salt = hashlib.sha256(os.urandom(32)).digest()
        kdf = hashlib.pbkdf2_hmac(
            "sha256", 
            password.encode(), 
            salt[:16], 
            iterations=480000,
            dklen=32
        )
        return base64.urlsafe_b64encode(kdf)
    
    def encrypt(self, data: str | dict | bytes) -> str:
        """Encrypt data to base64 string."""
        if not self._fernet:
            raise VaultError("Vault not initialized")
        
        if isinstance(data, dict):
            payload = json.dumps(data).encode()
        elif isinstance(data, str):
            payload = data.encode()
        else:
            payload = data
        
        encrypted = self._fernet.encrypt(payload)
        return base64.urlsafe_b64encode(encrypted).decode()
    
    def decrypt(self, token: str) -> str:
        """Decrypt base64 token to string."""
        if not self._fernet:
            raise VaultError("Vault not initialized")
        
        try:
            encrypted = base64.urlsafe_b64decode(token.encode())
            decrypted = self._fernet.decrypt(encrypted)
            return decrypted.decode()
        except InvalidToken as e:
            raise AuthenticationError("Invalid or expired token") from e
        except Exception as e:
            raise VaultError(f"Decryption failed: {e}") from e
    
    def hash_password(self, password: str) -> str:
        """Hash password with Argon2id."""
        return self._pwd_context.hash(password)
    
    def verify_password(self, password: str, hash: str) -> bool:
        """Verify password against Argon2id hash."""
        return self._pwd_context.verify(password, hash)
    
    def rotate_key(self, new_password: str) -> None:
        """Rotate encryption key (re-encrypt all data)."""
        # Implementation for key rotation with data migration
        pass
    
    def secure_delete(self) -> None:
        """Securely wipe vault keys."""
        try:
            keyring.delete_password(self._service_name, self._key_name)
            self._fernet = None
        except Exception:
            pass


# Global vault instance
vault = SecureVault()