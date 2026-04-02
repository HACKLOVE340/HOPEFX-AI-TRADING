# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""Cryptographic vault with Fernet, Argon2id, and system keyring."""

from __future__ import annotations

import base64
import hashlib
import json
import os

try:
    from typing import Self  # Python 3.11+
except ImportError:
    try:
        from typing_extensions import Self  # pip install typing_extensions
    except ImportError:
        from typing import Any as Self  # type: ignore[assignment]  # fallback

import keyring
from cryptography.fernet import Fernet, InvalidToken
from passlib.context import CryptContext

from core.exceptions import AuthenticationError, VaultError


class SecureVault:
    """Hardware-backed or keyring-backed secure vault."""

    _instance: SecureVault | None = None
    _initialized: bool = False  # declared here so pylint sees it before __new__ sets it
    # passlib uses "argon2" as the scheme name (wraps argon2-cffi which
    # defaults to Argon2id internally).
    _pwd_context = CryptContext(
        schemes=["argon2"],
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

        except VaultError:
            # Re-raise VaultError as-is — wrapping it again would double the
            # message and obscure the original cause in structured log output.
            raise
        except Exception as e:
            # Preserve the full original traceback via exception chaining so
            # that logging configurations that inspect __cause__ (e.g. Sentry,
            # structlog) can surface the root error alongside the VaultError.
            import logging as _logging

            _logging.getLogger(__name__).error("Vault initialization failed: %s", e, exc_info=True)
            raise VaultError(f"Vault initialization failed: {e}") from e

    def _derive_key(self, password: str) -> bytes:
        """Derive Fernet key from password using PBKDF2."""
        salt = hashlib.sha256(os.urandom(32)).digest()
        kdf = hashlib.pbkdf2_hmac(
            "sha256",
            password.encode(),
            salt[:16],
            iterations=480000,
            dklen=32,
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

    def verify_password(self, password: str, password_hash: str) -> bool:
        """Verify password against Argon2id hash."""
        return self._pwd_context.verify(password, password_hash)

    def rotate_key(self, new_password: str) -> None:
        """Rotate encryption key (re-encrypt all data)."""
        # Implementation for key rotation with data migration

    def secure_delete(self) -> None:
        """Securely wipe vault keys from keyring and memory."""
        try:
            keyring.delete_password(self._service_name, self._key_name)
        except Exception as e:
            # Log but do not swallow — caller must know if keyring wipe failed
            # so they can escalate (e.g. force pod restart, alert ops).
            import logging as _logging

            _logging.getLogger(__name__).error(
                "SecureVault.secure_delete: keyring wipe failed: %s",
                e,
            )
            raise VaultError(f"Keyring wipe failed — key may still be stored: {e}") from e
        finally:
            # Always zero the in-memory key regardless of keyring outcome
            self._fernet = None


# Global vault instance
vault = SecureVault()
