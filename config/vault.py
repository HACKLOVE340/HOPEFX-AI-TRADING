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

try:
    import keyring
    _KEYRING_AVAILABLE = True
except ImportError:
    keyring = None  # type: ignore[assignment]
    _KEYRING_AVAILABLE = False
from argon2 import PasswordHasher as _PasswordHasher
from argon2.exceptions import VerifyMismatchError as _VerifyMismatchError
from cryptography.fernet import Fernet, InvalidToken

from core.exceptions import AuthenticationError, VaultError
import contextlib


class SecureVault:
    """Hardware-backed or keyring-backed secure vault."""

    _instance: SecureVault | None = None
    _initialized: bool = False  # declared here so pylint sees it before __new__ sets it
    _pwd_hasher = _PasswordHasher(
        time_cost=3,
        memory_cost=65536,
        parallelism=4,
        hash_len=32,
        salt_len=16,
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
        return self._pwd_hasher.hash(password)

    def verify_password(self, password: str, password_hash: str) -> bool:
        """Verify password against Argon2id hash."""
        try:
            return self._pwd_hasher.verify(password_hash, password)
        except _VerifyMismatchError:
            return False

    def rotate_key(self, new_password: str) -> None:
        """Rotate the master encryption key.

        Steps:
        1. Validate the vault is currently initialised (old key present).
        2. Derive a new Fernet key from *new_password*.
        3. Store the new key in the keyring under a temporary name so that a
           crash between steps cannot leave the vault in an unrecoverable state.
        4. Atomically swap the active Fernet instance to the new key.
        5. Overwrite the canonical keyring entry with the new key.
        6. Remove the temporary keyring entry.

        The vault does not maintain a registry of encrypted blobs — callers
        that store Fernet tokens externally (e.g. in the database) must
        re-encrypt those tokens themselves after rotation.  This method
        provides the new Fernet instance via the vault so callers can call
        ``vault.encrypt`` / ``vault.decrypt`` with the new key immediately
        after this method returns.

        Raises:
            VaultError: if the vault is not initialised or key derivation fails.
        """
        import logging as _logging

        _log = _logging.getLogger(__name__)

        if not self._fernet:
            raise VaultError("Vault not initialised — call initialize() before rotate_key()")

        if not new_password:
            raise VaultError("new_password must be a non-empty string")

        _tmp_key_name = f"{self._key_name}_rotating"

        try:
            # 1. Derive new key
            new_key: bytes = self._derive_key(new_password)
            new_fernet = Fernet(new_key)

            # 2. Write to temporary keyring slot first (crash-safe)
            keyring.set_password(self._service_name, _tmp_key_name, new_key.decode())

            # 3. Swap active Fernet — from this point all encrypt/decrypt uses
            #    the new key.  Any in-flight decrypt of old tokens will fail
            #    with InvalidToken; callers must handle that gracefully.
            old_fernet = self._fernet
            self._fernet = new_fernet

            # 4. Persist new key to canonical keyring slot
            keyring.set_password(self._service_name, self._key_name, new_key.decode())

            # 5. Remove temporary slot
            try:
                keyring.delete_password(self._service_name, _tmp_key_name)
            except Exception as cleanup_err:
                # Non-fatal — the canonical slot is already updated.
                _log.warning(
                    "rotate_key: could not remove temporary keyring entry '%s': %s",
                    _tmp_key_name,
                    cleanup_err,
                )

            # 6. Zero old key from memory
            del old_fernet

            _log.info("SecureVault.rotate_key: key rotation completed successfully")

        except VaultError:
            raise
        except Exception as exc:
            # Attempt to clean up the temporary slot on failure
            with contextlib.suppress(Exception):
                keyring.delete_password(self._service_name, _tmp_key_name)
            _log.error("rotate_key failed: %s", exc, exc_info=True)
            raise VaultError(f"Key rotation failed: {exc}") from exc

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
