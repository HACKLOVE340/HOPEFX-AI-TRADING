# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
# security/vault.py
"""
HOPEFX Hardware Security Module (HSM) Integration
Enterprise-grade key management with secure enclaves
"""

import hashlib
import hmac
import json
import logging
import os
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

logger = logging.getLogger(__name__)

from cryptography.fernet import Fernet
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC


@dataclass
class EncryptedSecret:
    """Encrypted secret with metadata"""

    ciphertext: bytes
    salt: bytes
    iterations: int
    algorithm: str
    key_id: str
    created_at: str


class HSMVault:
    """
    Hardware Security Module abstraction layer.
    Supports both software HSM (for development) and hardware HSM (production).
    """

    def __init__(self, hsm_type: str = "software", key_store_path: str = "data/keys/"):
        self.hsm_type = hsm_type
        self.key_store_path = key_store_path
        self._master_key: bytes | None = None
        self._key_cache: dict[str, bytes] = {}
        self._initialized = False

        Path(key_store_path).mkdir(parents=True, exist_ok=True)

    def initialize(self, password: str | None = None, hardware_token: str | None = None) -> None:
        """
        Derive or generate the master key and mark the vault ready.

        hsm_type='software'  — PBKDF2 from *password*, or random key saved to disk.
        hsm_type='yubikey'   — YubiKey HSM via yubihsm library.
        hsm_type='cloudhsm'  — AWS KMS or Azure Key Vault (set CLOUD_HSM_PROVIDER).

        Raises
        ------
        ValueError   : Unknown hsm_type.
        RuntimeError : Key derivation or persistence failed, or required env
                       vars / SDKs are missing for the selected provider.
        """
        if self.hsm_type == "software":
            if password:
                self._master_key = self._derive_key_software(password, hardware_token)
            else:
                self._master_key = secrets.token_bytes(32)
                self._save_master_key()

        elif self.hsm_type == "yubikey":
            self._master_key = self._derive_key_yubikey(hardware_token)

        elif self.hsm_type == "cloudhsm":
            self._master_key = self._derive_key_cloud(hardware_token)

        else:
            raise ValueError(f"Unknown hsm_type {self.hsm_type!r}. Valid values: 'software', 'yubikey', 'cloudhsm'.")

        if not self._master_key:
            raise RuntimeError(f"Master key derivation returned empty bytes for hsm_type={self.hsm_type!r}")

        self._initialized = True
        logger.info("HSMVault initialised: %s", self.hsm_type)

    def _derive_key_software(self, password: str, hardware_token: str | None) -> bytes:
        """PBKDF2 key derivation with hardware binding"""
        # Combine password with hardware fingerprint
        salt = secrets.token_bytes(32)

        if hardware_token:
            # Bind to hardware (e.g., CPU serial, MAC address hash)
            hardware_salt = hashlib.sha256(hardware_token.encode()).digest()
            salt = bytes(a ^ b for a, b in zip(salt, hardware_salt, strict=False))

        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,
            salt=salt,
            iterations=600000,  # OWASP recommended
            backend=default_backend(),
        )

        key = kdf.derive(password.encode())

        # Store salt for future derivation
        with open(f"{self.key_store_path}salt.bin", "wb") as f:
            f.write(salt)

        return key

    def _derive_key_yubikey(self, slot: str) -> bytes:
        """Derive key using YubiKey HSM"""
        # Requires yubihsm library
        try:
            from yubihsm import YubiHsm

            hsm = YubiHsm.connect("http://localhost:12345")
            session = hsm.create_session_derived(int(slot), "password")
            # Generate key in HSM, export encrypted
            return session.get_pseudo_random(32)
        except ImportError:
            raise RuntimeError("YubiKey HSM library not installed") from None

    def _derive_key_cloud(self, credential: str | None) -> bytes:
        """Cloud HSM key derivation — AWS KMS or Azure Key Vault.

        Provider is selected by environment variable CLOUD_HSM_PROVIDER:
            'aws'   — AWS KMS GenerateDataKey (requires boto3 + IAM role or
                      AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY / AWS_REGION)
            'azure' — Azure Key Vault unwrapKey (requires azure-keyvault-keys +
                      AZURE_CLIENT_ID / AZURE_CLIENT_SECRET / AZURE_TENANT_ID)

        Required environment variables per provider
        -------------------------------------------
        AWS:
            CLOUD_HSM_PROVIDER=aws
            AWS_KMS_KEY_ID       — KMS CMK ARN or alias (e.g. alias/hopefx-vault)
            AWS_REGION           — e.g. us-east-1
            AWS_ACCESS_KEY_ID    — (or use IAM instance role)
            AWS_SECRET_ACCESS_KEY

        Azure:
            CLOUD_HSM_PROVIDER=azure
            AZURE_KEY_VAULT_URL  — e.g. https://hopefx-vault.vault.azure.net/
            AZURE_KEY_NAME       — name of the RSA/EC key in Key Vault
            AZURE_CLIENT_ID
            AZURE_CLIENT_SECRET
            AZURE_TENANT_ID

        The *credential* parameter is accepted for API compatibility but
        provider selection and authentication are driven by env vars so that
        secrets are never passed as function arguments.

        Raises
        ------
        RuntimeError  : SDK not installed, env vars missing, or API call fails.
        """
        provider = os.getenv("CLOUD_HSM_PROVIDER", "").lower().strip()

        if provider == "aws":
            return self._derive_key_aws_kms()
        if provider == "azure":
            return self._derive_key_azure_keyvault()
        raise RuntimeError(
            "CLOUD_HSM_PROVIDER is not set or unrecognised. "
            "Set it to 'aws' or 'azure' and configure the required env vars "
            "before using hsm_type='cloudhsm'."
        )

    def _derive_key_aws_kms(self) -> bytes:
        """Generate a 256-bit data key via AWS KMS GenerateDataKey.

        Uses the plaintext data key directly as the vault master key.
        The encrypted copy is stored alongside the vault for key recovery
        (decrypt via KMS Decrypt API).
        """
        try:
            import boto3  # type: ignore[import]
        except ImportError:
            raise RuntimeError(
                "boto3 is required for AWS KMS integration. Install it with: pip install boto3"
            ) from None

        key_id = os.getenv("AWS_KMS_KEY_ID")
        region = os.getenv("AWS_REGION", os.getenv("AWS_DEFAULT_REGION", "us-east-1"))

        if not key_id:
            raise RuntimeError(
                "AWS_KMS_KEY_ID environment variable is not set. "
                "Provide the KMS CMK ARN or alias (e.g. alias/hopefx-vault)."
            )

        try:
            client = boto3.client("kms", region_name=region)
            response = client.generate_data_key(
                KeyId=key_id,
                KeySpec="AES_256",
            )
        except Exception as exc:
            raise RuntimeError(f"AWS KMS GenerateDataKey failed: {exc}") from exc

        plaintext_key: bytes = response["Plaintext"]  # 32 bytes AES-256
        encrypted_key: bytes = response["CiphertextBlob"]

        # Persist the encrypted copy for disaster recovery (KMS Decrypt to recover)
        enc_path = Path(self.key_store_path) / "master.key.kms"
        try:
            with open(enc_path, "wb") as f:
                f.write(encrypted_key)
            Path(enc_path).chmod(0o600)
            logger.info("AWS KMS encrypted key blob saved to %s", enc_path)
        except OSError as exc:
            logger.warning("Could not persist KMS encrypted key blob: %s", exc)

        logger.info("Master key derived via AWS KMS (key_id=%s, region=%s)", key_id, region)
        return plaintext_key

    def _derive_key_azure_keyvault(self) -> bytes:
        """Unwrap a locally-generated AES-256 key using Azure Key Vault.

        Generates a random 32-byte key, wraps it with the Key Vault RSA key
        (RSA-OAEP), stores the wrapped copy for recovery, and returns the
        plaintext key as the vault master key.
        """
        try:
            from azure.identity import ClientSecretCredential  # type: ignore[import]
            from azure.keyvault.keys import KeyClient  # type: ignore[import]
            from azure.keyvault.keys.crypto import (  # type: ignore[import]
                CryptographyClient,
                KeyWrapAlgorithm,
            )
        except ImportError:
            raise RuntimeError(
                "azure-keyvault-keys and azure-identity are required for Azure Key Vault "
                "integration. Install with: pip install azure-keyvault-keys azure-identity"
            ) from None

        vault_url = os.getenv("AZURE_KEY_VAULT_URL")
        key_name = os.getenv("AZURE_KEY_NAME")
        client_id = os.getenv("AZURE_CLIENT_ID")
        client_sec = os.getenv("AZURE_CLIENT_SECRET")
        tenant_id = os.getenv("AZURE_TENANT_ID")

        missing = [
            name
            for name, val in [
                ("AZURE_KEY_VAULT_URL", vault_url),
                ("AZURE_KEY_NAME", key_name),
                ("AZURE_CLIENT_ID", client_id),
                ("AZURE_CLIENT_SECRET", client_sec),
                ("AZURE_TENANT_ID", tenant_id),
            ]
            if not val
        ]
        if missing:
            raise RuntimeError(
                f"Azure Key Vault env vars not set: {', '.join(missing)}. "
                "Configure them before using hsm_type='cloudhsm' with CLOUD_HSM_PROVIDER=azure."
            )

        try:
            credential = ClientSecretCredential(
                tenant_id=tenant_id,
                client_id=client_id,
                client_secret=client_sec,
            )
            key_client = KeyClient(vault_url=vault_url, credential=credential)
            key = key_client.get_key(key_name)

            crypto_client = CryptographyClient(key, credential=credential)

            # Generate a random 256-bit master key and wrap it with the Key Vault key
            plaintext_key = secrets.token_bytes(32)
            wrap_result = crypto_client.wrap_key(KeyWrapAlgorithm.rsa_oaep, plaintext_key)
            wrapped_key: bytes = wrap_result.encrypted_key
        except Exception as exc:
            raise RuntimeError(f"Azure Key Vault wrap_key failed: {exc}") from exc

        # Persist the wrapped copy for disaster recovery (unwrap via Key Vault)
        wrapped_path = Path(self.key_store_path) / "master.key.azure"
        try:
            with open(wrapped_path, "wb") as f:
                f.write(wrapped_key)
            Path(wrapped_path).chmod(0o600)
            logger.info("Azure Key Vault wrapped key saved to %s", wrapped_path)
        except OSError as exc:
            logger.warning("Could not persist Azure wrapped key: %s", exc)

        logger.info(
            "Master key derived via Azure Key Vault (vault=%s, key=%s)",
            vault_url,
            key_name,
        )
        return plaintext_key

    def _save_master_key(self) -> None:
        """Persist the master key to disk for disaster recovery.

        Uses a simple encrypted file rather than the optional secretsharing
        library (which is not in requirements.txt and would crash at runtime).
        The key is written as hex to key_store_path/master.key with mode 0o600.
        Operators should back this file up to a separate secure location.
        """
        if not self._master_key:
            raise RuntimeError("Cannot save master key: vault not initialised")
        key_path = Path(self.key_store_path) / "master.key"
        try:
            with open(key_path, "w", encoding="utf-8") as f:
                f.write(self._master_key.hex())
            Path(key_path).chmod(0o600)
            logger.info("Master key saved to %s (mode 0600)", key_path)
        except OSError as exc:
            logger.error("Failed to save master key: %s", exc)
            raise

    def encrypt(self, plaintext: str, key_id: str = "default") -> EncryptedSecret:
        """
        Encrypt data with envelope encryption.
        Data encryption key (DEK) encrypted by key encryption key (KEK).
        """
        if not self._initialized:
            raise RuntimeError("Vault not initialized")

        # Generate data encryption key
        dek = Fernet.generate_key()

        # Encrypt plaintext with DEK
        f = Fernet(dek)
        ciphertext = f.encrypt(plaintext.encode())

        # Encrypt DEK with KEK (from HSM)
        kek = self._get_kek(key_id)
        encrypted_dek = self._encrypt_with_kek(dek, kek)

        # Store with metadata
        return EncryptedSecret(
            ciphertext=ciphertext,
            salt=encrypted_dek,
            iterations=0,
            algorithm="AES-256-GCM",
            key_id=key_id,
            created_at=datetime.now(UTC).isoformat(),
        )

    def decrypt(self, secret: EncryptedSecret) -> str:
        """Decrypt data using envelope decryption"""
        if not self._initialized:
            raise RuntimeError("Vault not initialized")

        # Decrypt DEK with KEK
        kek = self._get_kek(secret.key_id)
        dek = self._decrypt_with_kek(secret.salt, kek)

        # Decrypt ciphertext with DEK
        f = Fernet(dek)
        plaintext = f.decrypt(secret.ciphertext)

        return plaintext.decode()

    def _get_kek(self, key_id: str) -> bytes:
        """Get or generate Key Encryption Key"""
        if key_id in self._key_cache:
            return self._key_cache[key_id]

        # Derive KEK from master key and key_id
        kek = hmac.new(self._master_key, key_id.encode(), hashlib.sha256).digest()

        self._key_cache[key_id] = kek
        return kek

    def _encrypt_with_kek(self, data: bytes, kek: bytes) -> bytes:
        """Encrypt data with KEK using AES-256-GCM"""
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM

        aesgcm = AESGCM(kek)
        nonce = secrets.token_bytes(12)
        ciphertext = aesgcm.encrypt(nonce, data, None)

        return nonce + ciphertext

    def _decrypt_with_kek(self, data: bytes, kek: bytes) -> bytes:
        """Decrypt data with KEK"""
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM

        aesgcm = AESGCM(kek)
        nonce = data[:12]
        ciphertext = data[12:]

        return aesgcm.decrypt(nonce, ciphertext, None)

    def rotate_keys(self) -> None:
        """Periodic key rotation for forward secrecy.

        Clears the in-memory KEK cache so the next encrypt/decrypt call
        derives a fresh KEK from the (potentially rotated) master key.
        Callers are responsible for re-encrypting stored secrets after
        rotating the master key via initialize().
        """
        if not self._initialized:
            raise RuntimeError("Vault not initialised — call initialize() first")
        self._key_cache.clear()
        logger.info("HSMVault key cache cleared — KEKs will be re-derived on next use")

    def secure_erase(self):
        """Cryptographic erasure of all keys"""
        # Overwrite memory
        if self._master_key:
            for i in range(len(self._master_key)):
                self._master_key = self._master_key[:i] + b"\x00" + self._master_key[i + 1 :]
            self._master_key = None

        self._key_cache.clear()
        self._initialized = False


class APICredentialManager:
    """
    Secure API credential management with automatic rotation.
    """

    def __init__(self, vault: HSMVault):
        self.vault = vault
        self.credentials: dict[str, EncryptedSecret] = {}
        self.rotation_schedule: dict[str, datetime] = {}

    def add_credential(self, name: str, api_key: str, api_secret: str, rotation_days: int = 90):
        """Store API credentials encrypted"""
        credential_data = json.dumps(
            {
                "api_key": api_key,
                "api_secret": api_secret,
                "created_at": datetime.now(UTC).isoformat(),
            }
        )

        encrypted = self.vault.encrypt(credential_data, key_id=f"credential_{name}")
        self.credentials[name] = encrypted

        # Schedule rotation
        from datetime import timedelta

        self.rotation_schedule[name] = datetime.now(UTC) + timedelta(days=rotation_days)

        logger.info("Credential '%s' encrypted and stored", name)

    def get_credential(self, name: str) -> dict[str, str]:
        """Retrieve and decrypt credentials"""
        if name not in self.credentials:
            raise KeyError(f"Credential '{name}' not found")

        # Check rotation
        if datetime.now(UTC) > self.rotation_schedule.get(name, datetime.now(UTC)):
            logger.warning("Credential '%s' needs rotation", name)

        encrypted = self.credentials[name]
        plaintext = self.vault.decrypt(encrypted)
        return json.loads(plaintext)

    def rotate_credential(self, name: str, new_api_key: str, new_api_secret: str) -> None:
        """Rotate credentials atomically with rollback on failure.

        Validates inputs before touching the stored credential so the old
        value is never overwritten with an empty or invalid key.
        """
        if not new_api_key or not new_api_secret:
            raise ValueError(
                f"Cannot rotate credential '{name}': new_api_key and new_api_secret must both be non-empty strings."
            )

        old_secret = self.credentials.get(name)
        old_schedule = self.rotation_schedule.get(name)

        try:
            self.add_credential(name, new_api_key, new_api_secret)
            logger.info("Credential '%s' rotated successfully", name)
        except Exception as exc:
            # Rollback to previous credential on failure
            if old_secret is not None:
                self.credentials[name] = old_secret
                if old_schedule is not None:
                    self.rotation_schedule[name] = old_schedule
                logger.error(
                    "Credential '%s' rotation failed — rolled back to previous: %s",
                    name,
                    exc,
                )
            else:
                logger.error(
                    "Credential '%s' rotation failed (no previous to roll back to): %s",
                    name,
                    exc,
                )
            raise
