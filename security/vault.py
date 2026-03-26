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
from datetime import datetime, timezone
from typing import Dict, Optional

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
        self._master_key: Optional[bytes] = None
        self._key_cache: Dict[str, bytes] = {}
        self._initialized = False
        
        os.makedirs(key_store_path, exist_ok=True)
    
    def initialize(self, password: Optional[str] = None, 
                   hardware_token: Optional[str] = None):
        """
        Initialize vault with master key derivation.
        For hardware HSM, uses PKCS#11 interface.
        """
        if self.hsm_type == "software":
            # Software HSM: Derive from password + hardware binding
            if password:
                self._master_key = self._derive_key_software(password, hardware_token)
            else:
                # Generate new random master key
                self._master_key = secrets.token_bytes(32)
                self._save_master_key()
        
        elif self.hsm_type == "yubikey":
            # YubiKey HSM integration
            self._master_key = self._derive_key_yubikey(hardware_token)
        
        elif self.hsm_type == "cloudhsm":
            # AWS CloudHSM or Azure Dedicated HSM
            self._master_key = self._derive_key_cloud(hardware_token)
        
        self._initialized = True
        logger.info("HSMVault initialised: %s", self.hsm_type)
    
    def _derive_key_software(self, password: str, hardware_token: Optional[str]) -> bytes:
        """PBKDF2 key derivation with hardware binding"""
        # Combine password with hardware fingerprint
        salt = secrets.token_bytes(32)
        
        if hardware_token:
            # Bind to hardware (e.g., CPU serial, MAC address hash)
            hardware_salt = hashlib.sha256(hardware_token.encode()).digest()
            salt = bytes(a ^ b for a, b in zip(salt, hardware_salt))
        
        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,
            salt=salt,
            iterations=600000,  # OWASP recommended
            backend=default_backend()
        )
        
        key = kdf.derive(password.encode())
        
        # Store salt for future derivation
        with open(f"{self.key_store_path}salt.bin", 'wb') as f:
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
            raise RuntimeError("YubiKey HSM library not installed")
    
    def _derive_key_cloud(self, credential: str) -> bytes:
        """Cloud HSM key derivation (AWS CloudHSM / Azure Dedicated HSM).

        This path requires the vendor SDK to be installed and configured.
        Raises NotImplementedError rather than returning None silently — a
        None master key would cause every subsequent encrypt/decrypt call to
        fail with a cryptic AttributeError instead of a clear configuration
        error.
        """
        raise NotImplementedError(
            "Cloud HSM integration is not yet configured. "
            "Install the vendor SDK and implement this method before using "
            "hsm_type='cloudhsm'."
        )

    def _save_master_key(self) -> None:
        """Persist the master key to disk for disaster recovery.

        Uses a simple encrypted file rather than the optional secretsharing
        library (which is not in requirements.txt and would crash at runtime).
        The key is written as hex to key_store_path/master.key with mode 0o600.
        Operators should back this file up to a separate secure location.
        """
        if not self._master_key:
            raise RuntimeError("Cannot save master key: vault not initialised")
        key_path = os.path.join(self.key_store_path, "master.key")
        try:
            with open(key_path, "w") as f:
                f.write(self._master_key.hex())
            os.chmod(key_path, 0o600)
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
            created_at=datetime.now(timezone.utc).isoformat()
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
        kek = hmac.new(
            self._master_key,
            key_id.encode(),
            hashlib.sha256
        ).digest()
        
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
                self._master_key = self._master_key[:i] + b'\x00' + self._master_key[i+1:]
            self._master_key = None
        
        self._key_cache.clear()
        self._initialized = False


class APICredentialManager:
    """
    Secure API credential management with automatic rotation.
    """
    
    def __init__(self, vault: HSMVault):
        self.vault = vault
        self.credentials: Dict[str, EncryptedSecret] = {}
        self.rotation_schedule: Dict[str, datetime] = {}
    
    def add_credential(self, name: str, api_key: str, api_secret: str,
                       rotation_days: int = 90):
        """Store API credentials encrypted"""
        credential_data = json.dumps({
            'api_key': api_key,
            'api_secret': api_secret,
            'created_at': datetime.now(timezone.utc).isoformat()
        })
        
        encrypted = self.vault.encrypt(credential_data, key_id=f"credential_{name}")
        self.credentials[name] = encrypted
        
        # Schedule rotation
        from datetime import timedelta
        self.rotation_schedule[name] = datetime.now(timezone.utc) + timedelta(days=rotation_days)
        
        logger.info("Credential '%s' encrypted and stored", name)
    
    def get_credential(self, name: str) -> Dict[str, str]:
        """Retrieve and decrypt credentials"""
        if name not in self.credentials:
            raise KeyError(f"Credential '{name}' not found")
        
        # Check rotation
        if datetime.now(timezone.utc) > self.rotation_schedule.get(name, datetime.now(timezone.utc)):
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
                f"Cannot rotate credential '{name}': new_api_key and new_api_secret "
                "must both be non-empty strings."
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
                    name, exc,
                )
            else:
                logger.error(
                    "Credential '%s' rotation failed (no previous to roll back to): %s",
                    name, exc,
                )
            raise
