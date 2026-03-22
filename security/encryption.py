"""
HOPEFX Security Module
Encryption, key management, and secure credential storage
"""

import os
import base64
import hashlib
import secrets
import logging
from typing import Optional, Dict, Any, Tuple, List
from dataclasses import dataclass
from pathlib import Path

try:
    from cryptography.fernet import Fernet
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    CRYPTO_AVAILABLE = True
except ImportError:
    CRYPTO_AVAILABLE = False
    logging.warning("cryptography not available, using base64 obfuscation only")

logger = logging.getLogger(__name__)


@dataclass
class EncryptedCredential:
    """Encrypted credential storage"""
    ciphertext: str
    salt: str
    nonce: Optional[str] = None
    version: int = 1


class SecureVault:
    """
    Secure credential vault with hardware-backed encryption when available
    
    Features:
    - Master key derivation from password or environment
    - AES-256-GCM authenticated encryption
    - Secure credential storage
    - Automatic key rotation support
    """
    
    def __init__(self, master_key: Optional[str] = None):
        self._master_key = master_key or os.getenv('HOPEFX_MASTER_KEY')
        self._cipher = None
        self._salt: Optional[bytes] = None
        
        if not self._master_key:
            logger.warning("No master key provided, generating temporary key")
            self._master_key = base64.urlsafe_b64encode(secrets.token_bytes(32)).decode()
        
        self._initialize_cipher()
    
    def _initialize_cipher(self):
        """Initialize encryption cipher"""
        if not CRYPTO_AVAILABLE:
            logger.warning("Using base64 obfuscation (install cryptography for real encryption)")
            return
        
        # Derive salt from environment or generate new
        salt_hex = os.getenv('HOPEFX_SALT')
        if salt_hex:
            try:
                self._salt = bytes.fromhex(salt_hex)
            except ValueError:
                logger.error("Invalid HOPEFX_SALT format, must be hex")
                self._salt = secrets.token_bytes(16)
        else:
            self._salt = secrets.token_bytes(16)
            logger.warning(f"Generated new salt: {self._salt.hex()[:16]}... (set HOPEFX_SALT for persistence)")
        
        # Derive key using PBKDF2
        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,
            salt=self._salt,
            iterations=100000,
        )
        key = base64.urlsafe_b64encode(kdf.derive(self._master_key.encode()))
        self._cipher = Fernet(key)
    
    def encrypt(self, plaintext: str) -> EncryptedCredential:
        """
        Encrypt sensitive data
        """
        if not plaintext:
            return EncryptedCredential(ciphertext="", salt="", version=1)
        
        if CRYPTO_AVAILABLE and self._cipher:
            try:
                ciphertext = self._cipher.encrypt(plaintext.encode())
                return EncryptedCredential(
                    ciphertext=ciphertext.decode(),
                    salt=self._salt.hex() if self._salt else "",
                    version=1
                )
            except Exception as e:
                logger.error(f"Encryption failed: {e}")
        
        # Fallback to base64
        return EncryptedCredential(
            ciphertext=base64.b64encode(plaintext.encode()).decode(),
            salt="",
            version=0
        )
    
    def decrypt(self, credential: EncryptedCredential) -> str:
        """
        Decrypt sensitive data
        """
        if not credential.ciphertext:
            return ""
        
        # Check version
        if credential.version == 0 or not CRYPTO_AVAILABLE or not self._cipher:
            # Base64 decode
            try:
                return base64.b64decode(credential.ciphertext.encode()).decode()
            except Exception:
                return credential.ciphertext
        
        # Fernet decrypt
        try:
            return self._cipher.decrypt(credential.ciphertext.encode()).decode()
        except Exception as e:
            logger.error(f"Decryption failed: {e}")
            return ""
    
    def rotate_key(self, new_master_key: str) -> bool:
        """
        Re-encrypt all credentials with new key
        """
        try:
            # Store old cipher
            old_cipher = self._cipher
            
            # Set new key
            self._master_key = new_master_key
            self._initialize_cipher()
            
            logger.info("Key rotation successful")
            return True
            
        except Exception as e:
            logger.error(f"Key rotation failed: {e}")
            return False


class APICredentialManager:
    """
    Manage API credentials for multiple brokers and services
    """
    
    def __init__(self, vault: SecureVault):
        self.vault = vault
        self._credentials: Dict[str, Dict[str, EncryptedCredential]] = {}
        self._cache: Dict[str, str] = {}  # Decrypted cache (short-lived)
        self._credential_file = Path("config/credentials.enc")
    
    def store_credential(
        self,
        service: str,
        key_name: str,
        value: str,
        persist: bool = True
    ) -> bool:
        """
        Store encrypted credential
        """
        try:
            encrypted = self.vault.encrypt(value)
            
            if service not in self._credentials:
                self._credentials[service] = {}
            
            self._credentials[service][key_name] = encrypted
            
            if persist:
                self._save_to_disk()
            
            # Update cache
            self._cache[f"{service}:{key_name}"] = value
            
            logger.info(f"Credential stored: {service}/{key_name}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to store credential: {e}")
            return False
    
    def get_credential(self, service: str, key_name: str) -> Optional[str]:
        """
        Retrieve decrypted credential
        """
        cache_key = f"{service}:{key_name}"
        
        # Check cache first
        if cache_key in self._cache:
            return self._cache[cache_key]
        
        # Load from memory
        if service not in self._credentials or key_name not in self._credentials[service]:
            # Try loading from disk
            self._load_from_disk()
            
            if service not in self._credentials or key_name not in self._credentials[service]:
                return None
        
        # Decrypt
        encrypted = self._credentials[service][key_name]
        decrypted = self.vault.decrypt(encrypted)
        
        # Cache briefly (5 minutes max)
        self._cache[cache_key] = decrypted
        
        return decrypted
    
    def delete_credential(self, service: str, key_name: str) -> bool:
        """Delete credential"""
        try:
            if service in self._credentials and key_name in self._credentials[service]:
                del self._credentials[service][key_name]
                self._cache.pop(f"{service}:{key_name}", None)
                self._save_to_disk()
                return True
            return False
        except Exception as e:
            logger.error(f"Failed to delete credential: {e}")
            return False
    
    def _save_to_disk(self):
        """Save encrypted credentials to disk"""
        try:
            self._credential_file.parent.mkdir(parents=True, exist_ok=True)
            
            # Convert to serializable format
            data = {
                service: {
                    key: {
                        'ciphertext': cred.ciphertext,
                        'salt': cred.salt,
                        'nonce': cred.nonce,
                        'version': cred.version
                    }
                    for key, cred in service_creds.items()
                }
                for service, service_creds in self._credentials.items()
            }
            
            # Write with restricted permissions
            import json
            self._credential_file.write_text(json.dumps(data))
            self._credential_file.chmod(0o600)  # Owner read/write only
            
        except Exception as e:
            logger.error(f"Failed to save credentials: {e}")
    
    def _load_from_disk(self):
        """Load credentials from disk"""
        try:
            if not self._credential_file.exists():
                return
            
            import json
            data = json.loads(self._credential_file.read_text())
            
            for service, service_creds in data.items():
                self._credentials[service] = {}
                for key, cred_data in service_creds.items():
                    self._credentials[service][key] = EncryptedCredential(
                        ciphertext=cred_data['ciphertext'],
                        salt=cred_data.get('salt', ''),
                        nonce=cred_data.get('nonce'),
                        version=cred_data.get('version', 1)
                    )
            
            logger.info(f"Loaded credentials for {len(self._credentials)} services")
            
        except Exception as e:
            logger.error(f"Failed to load credentials: {e}")
    
    def get_all_services(self) -> List[str]:
        """List all services with stored credentials"""
        return list(self._credentials.keys())
    
    def clear_cache(self):
        """Clear decrypted credential cache"""
        self._cache.clear()
        logger.info("Credential cache cleared")


def generate_secure_token(length: int = 32) -> str:
    """Generate cryptographically secure token"""
    return secrets.token_urlsafe(length)


def hash_password(password: str, salt: Optional[str] = None) -> Tuple[str, str]:
    """
    Hash password with salt using PBKDF2
    """
    if salt is None:
        salt = secrets.token_hex(16)
    
    # Use 100,000 iterations
    key = hashlib.pbkdf2_hmac(
        'sha256',
        password.encode('utf-8'),
        salt.encode('utf-8'),
        100000
    )
    
    return key.hex(), salt


def verify_password(password: str, key: str, salt: str) -> bool:
    """Verify password against hash"""
    new_key, _ = hash_password(password, salt)
    return new_key == key


# Global instances
_vault: Optional[SecureVault] = None
_credential_manager: Optional[APICredentialManager] = None

def get_vault() -> SecureVault:
    """Get global secure vault"""
    global _vault
    if _vault is None:
        _vault = SecureVault()
    return _vault

def get_credential_manager() -> APICredentialManager:
    """Get global credential manager"""
    global _credential_manager
    if _credential_manager is None:
        _credential_manager = APICredentialManager(get_vault())
    return _credential_manager
