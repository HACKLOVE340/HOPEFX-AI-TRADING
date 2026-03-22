from __future__ import annotations

import base64
import json
import os
from pathlib import Path
from typing import Any, Optional

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

from hopefx.config.settings import settings


class Vault:
    """Hardware-security-module-like credential vault using Fernet."""

    _instance: Optional[Vault] = None
    _initialized: bool = False

    def __new__(cls) -> Vault:
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self) -> None:
        if self._initialized:
            return

        self._key = self._derive_key(settings.encryption_key)
        self._fernet = Fernet(self._key)
        self._cache: dict[str, Any] = {}
        self._vault_path = Path("./.vault")
        self._vault_path.mkdir(exist_ok=True)
        self._initialized = True

    def _derive_key(self, password: str) -> bytes:
        """Derive encryption key from password using PBKDF2."""
        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,
            salt=settings.encryption_key[:16].encode(),
            iterations=480000,
        )
        return base64.urlsafe_b64encode(kdf.derive(password.encode()))

    def encrypt(self, data: str) -> str:
        """Encrypt string data."""
        return self._fernet.encrypt(data.encode()).decode()

    def decrypt(self, token: str) -> str:
        """Decrypt string data."""
        try:
            return self._fernet.decrypt(token.encode()).decode()
        except InvalidToken as e:
            raise ValueError("Invalid encryption token") from e

    def store(self, key: str, value: Any, persist: bool = False) -> None:
        """Store value in vault."""
        encrypted = self.encrypt(json.dumps(value))
        self._cache[key] = value

        if persist:
            vault_file = self._vault_path / f"{key}.vault"
            vault_file.write_text(encrypted)

    def retrieve(self, key: str, default: Any = None) -> Any | None:
        """Retrieve value from vault."""
        if key in self._cache:
            return self._cache[key]

        vault_file = self._vault_path / f"{key}.vault"
        if vault_file.exists():
            encrypted = vault_file.read_text()
            try:
                value = json.loads(self.decrypt(encrypted))
                self._cache[key] = value
                return value
            except (InvalidToken, json.JSONDecodeError):
                if default is not None:
                    return default
                raise

        return default

    def delete(self, key: str) -> None:
        """Delete key from vault."""
        self._cache.pop(key, None)
        vault_file = self._vault_path / f"{key}.vault"
        if vault_file.exists():
            vault_file.unlink()

    def rotate_key(self, new_password: str) -> None:
        """Rotate encryption key and re-encrypt all vault files."""
        new_key = self._derive_key(new_password)
        new_fernet = Fernet(new_key)

        for vault_file in self._vault_path.glob("*.vault"):
            encrypted = vault_file.read_text()
            try:
                decrypted = self._fernet.decrypt(encrypted.encode())
                re_encrypted = new_fernet.encrypt(decrypted)
                vault_file.write_text(re_encrypted.decode())
            except InvalidToken:
                continue

        self._key = new_key
        self._fernet = new_fernet


vault = Vault()
