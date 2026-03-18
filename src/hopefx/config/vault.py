import json
import keyring
from cryptography.fernet import Fernet
from pydantic import BaseModel

from .settings import get_settings


class Credentials(BaseModel):
    oanda_token: str | None = None
    oanda_account: str | None = None
    binance_key: str | None = None
    binance_secret: str | None = None
    ibkr_account: str | None = None
    stripe_secret: str | None = None

class SecurityPolicy:
    ALLOWED_IPS = ["your_vpn_ip"]  # Restrict production access
    REQUIRE_2FA = True  # Implement TOTP
    
    @staticmethod
    def check_ip(request_ip: str) -> bool:
        return request_ip in SecurityPolicy.ALLOWED_IPS


class SecureVault:
    """Fernet encryption with OS keyring for service credentials."""
    
    _service_name = "hopefx_vault"
    
    def __init__(self) -> None:
        key_hex = get_settings().encryption_key
        self._fernet = Fernet(bytes.fromhex(key_hex))
    
    def store(self, creds: Credentials) -> None:
        encrypted = self._fernet.encrypt(creds.model_dump_json().encode())
        keyring.set_password(self._service_name, "creds", encrypted.decode())
    
    def retrieve(self) -> Credentials:
        encrypted = keyring.get_password(self._service_name, "creds")
        if not encrypted:
            return Credentials()
        decrypted = self._fernet.decrypt(encrypted.encode())
        return Credentials.model_validate_json(decrypted)
    
    def rotate_key(self, new_key: str) -> None:
        old_creds = self.retrieve()
        # Re-initialize with new key
        self._fernet = Fernet(bytes.fromhex(new_key))
        self.store(old_creds)
