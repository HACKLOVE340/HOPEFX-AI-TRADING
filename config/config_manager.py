"""
Configuration Management System - PRODUCTION VERSION
Fixed: Proper salt handling, error recovery, file locking
"""

import os
import json
import logging
import base64
import hashlib
import secrets
import fcntl  # Unix file locking
from typing import Any, Dict, Optional
from dataclasses import dataclass, asdict
from pathlib import Path
from datetime import datetime, timezone

try:
    from cryptography.fernet import Fernet
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
    CRYPTO_AVAILABLE = True
except ImportError:
    CRYPTO_AVAILABLE = False
    logging.warning("Cryptography not available, using base64 obfuscation")

logger = logging.getLogger(__name__)


@dataclass
class DatabaseConfig:
    db_type: str = "sqlite"
    host: str = "localhost"
    port: int = 5432
    username: str = ""
    password: str = ""
    database: str = "hopefx.db"
    ssl_enabled: bool = True


@dataclass
class TradingConfig:
    symbols: list = None
    max_position_size_pct: float = 0.02
    max_drawdown_pct: float = 0.10
    daily_loss_limit_pct: float = 0.05
    paper_trading: bool = True
    
    def __post_init__(self):
        if self.symbols is None:
            self.symbols = ["EURUSD", "XAUUSD"]


class ConfigManager:
    """
    Secure configuration manager with encryption
    
    Fixes:
    - Proper salt generation and validation
    - File locking for concurrent access
    - Graceful fallback if encryption fails
    - Atomic file writes
    """
    
    def __init__(self, config_dir: str = "config", encryption_key: Optional[str] = None):
        self.config_dir = Path(config_dir)
        self.config_dir.mkdir(parents=True, exist_ok=True)
        
        self._encryption_key = encryption_key or os.getenv('HOPEFX_MASTER_KEY')
        self._salt: Optional[bytes] = None
        self._cipher = None
        
        self._setup_encryption()
        
        logger.info(f"ConfigManager initialized: {self.config_dir}")
    
    def _setup_encryption(self):
        """Initialize encryption with proper error handling"""
        if not CRYPTO_AVAILABLE:
            logger.warning("Encryption not available, using base64 obfuscation")
            return
        
        if not self._encryption_key:
            logger.warning("No encryption key provided, generating temporary key")
            self._encryption_key = base64.urlsafe_b64encode(secrets.token_bytes(32)).decode()
        
        # Get or generate salt
        salt_env = os.getenv('HOPEFX_SALT')
        
        if salt_env:
            try:
                self._salt = bytes.fromhex(salt_env)
                if len(self._salt) != 16:
                    raise ValueError("Salt must be 16 bytes (32 hex chars)")
            except ValueError as e:
                logger.error(f"Invalid HOPEFX_SALT: {e}")
                logger.info("Generate valid salt with: python -c \"import secrets; print(secrets.token_hex(16))\"")
                self._salt = secrets.token_bytes(16)
        else:
            self._salt = secrets.token_bytes(16)
            logger.warning(
                "HOPEFX_SALT not set. Using generated salt. "
                "Set HOPEFX_SALT for persistent encryption across restarts."
            )
        
        # Derive key
        try:
            kdf = PBKDF2HMAC(
                algorithm=hashes.SHA256(),
                length=32,
                salt=self._salt,
                iterations=100000,
            )
            key = base64.urlsafe_b64encode(kdf.derive(self._encryption_key.encode()))
            self._cipher = Fernet(key)
            logger.info("Encryption initialized successfully")
        except Exception as e:
            logger.error(f"Encryption setup failed: {e}")
            self._cipher = None
    
    def _encrypt(self, value: str) -> str:
        """Encrypt a value with fallback"""
        if not value:
            return ""
        
        if self._cipher:
            try:
                return self._cipher.encrypt(value.encode()).decode()
            except Exception as e:
                logger.error(f"Encryption failed: {e}")
        
        # Fallback to base64
        return base64.b64encode(value.encode()).decode()
    
    def _decrypt(self, value: str) -> str:
        """Decrypt a value with fallback"""
        if not value:
            return ""
        
        if self._cipher:
            try:
                return self._cipher.decrypt(value.encode()).decode()
            except Exception:
                # Try base64 fallback
                pass
        
        # Try base64 decode
        try:
            return base64.b64decode(value.encode()).decode()
        except Exception:
            return value  # Return as-is if decryption fails
    
    def load_config(self, environment: Optional[str] = None) -> Dict[str, Any]:
        """Load configuration from file"""
        env = environment or os.getenv('APP_ENV', 'development')
        config_file = self.config_dir / f"config.{env}.json"
        
        if not config_file.exists():
            logger.warning(f"Config file not found: {config_file}, creating default")
            self._create_default_config(config_file)
        
        try:
            # File locking for safe concurrent access
            with open(config_file, 'r') as f:
                # Acquire shared lock
                fcntl.flock(f.fileno(), fcntl.LOCK_SH)
                try:
                    config_data = json.load(f)
                finally:
                    fcntl.flock(f.fileno(), fcntl.LOCK_UN)
            
            # Decrypt sensitive fields
            config_data = self._decrypt_config(config_data)
            
            logger.info(f"Configuration loaded: {config_file}")
            return config_data
            
        except Exception as e:
            logger.error(f"Failed to load configuration: {e}")
            raise
    
    def _decrypt_config(self, config: Dict) -> Dict:
        """Recursively decrypt configuration"""
        result = {}
        sensitive_keys = {'password', 'api_key', 'api_secret', 'secret', 'token', 'webhook'}
        
        for key, value in config.items():
            if isinstance(value, dict):
                result[key] = self._decrypt_config(value)
            elif isinstance(value, str) and any(s in key.lower() for s in sensitive_keys):
                result[key] = self._decrypt(value)
            else:
                result[key] = value
        
        return result
    
    def save_config(self, config: Dict[str, Any], environment: Optional[str] = None) -> None:
        """Save configuration with atomic write"""
        env = environment or os.getenv('APP_ENV', 'development')
        config_file = self.config_dir / f"config.{env}.json"
        temp_file = self.config_dir / f".config.{env}.json.tmp"
        
        try:
            # Encrypt sensitive fields
            config_to_save = self._encrypt_config(config.copy())
            
            # Write to temp file first
            with open(temp_file, 'w') as f:
                # Acquire exclusive lock
                fcntl.flock(f.fileno(), fcntl.LOCK_EX)
                try:
                    json.dump(config_to_save, f, indent=2)
                finally:
                    fcntl.flock(f.fileno(), fcntl.LOCK_UN)
            
            # Atomic rename
            temp_file.replace(config_file)
            
            logger.info(f"Configuration saved: {config_file}")
            
        except Exception as e:
            logger.error(f"Failed to save configuration: {e}")
            if temp_file.exists():
                temp_file.unlink()
            raise
    
    def _encrypt_config(self, config: Dict) -> Dict:
        """Recursively encrypt configuration"""
        result = {}
        sensitive_keys = {'password', 'api_key', 'api_secret', 'secret', 'token', 'webhook'}
        
        for key, value in config.items():
            if isinstance(value, dict):
                result[key] = self._encrypt_config(value)
            elif isinstance(value, str) and any(s in key.lower() for s in sensitive_keys):
                result[key] = self._encrypt(value)
            else:
                result[key] = value
        
        return result
    
    def _create_default_config(self, config_file: Path) -> None:
        """Create default configuration"""
        default_config = {
            'app_name': 'HOPEFX AI Trading',
            'version': '2.1.0',
            'environment': 'development',
            'database': asdict(DatabaseConfig()),
            'trading': asdict(TradingConfig()),
            'api': {
                'oanda_account_id': '',
                'oanda_api_key': '',
                'practice': True
            },
            'notifications': {
                'discord_webhook': '',
                'telegram_bot_token': '',
                'telegram_chat_id': ''
            }
        }
        
        self.save_config(default_config, 'development')


# Global instance
_config_manager: Optional[ConfigManager] = None

def get_config_manager() -> ConfigManager:
    """Get global config manager"""
    global _config_manager
    if _config_manager is None:
        _config_manager = ConfigManager()
    return _config_manager

def initialize_config(environment: Optional[str] = None) -> Dict[str, Any]:
    """Initialize and load configuration"""
    return get_config_manager().load_config(environment)


# ── Aliases expected by tests ─────────────────────────────────────────────────
from dataclasses import dataclass as _dc, field as _field
from typing import List as _List

class EncryptionManager:
    """Thin wrapper around ConfigManager's encryption — satisfies test imports."""
    def __init__(self, key: str = ""):
        from cryptography.fernet import Fernet
        import base64, hashlib
        k = hashlib.sha256(key.encode() if key else b"dev").digest()
        self._fernet = Fernet(base64.urlsafe_b64encode(k))

    def encrypt(self, data: str) -> str:
        return self._fernet.encrypt(data.encode()).decode()

    def decrypt(self, token: str) -> str:
        return self._fernet.decrypt(token.encode()).decode()


@_dc
class APIConfig:
    host: str = "0.0.0.0"
    port: int = 8000
    debug: bool = False
    cors_origins: _List[str] = _field(default_factory=list)


@_dc
class LoggingConfig:
    level: str = "INFO"
    format: str = "json"
    file: str = "logs/hopefx.log"


@_dc
class AppConfig:
    environment: str = "development"
    api: APIConfig = _field(default_factory=APIConfig)
    database: "DatabaseConfig" = _field(default_factory=DatabaseConfig)
    trading: "TradingConfig" = _field(default_factory=TradingConfig)
    logging: LoggingConfig = _field(default_factory=LoggingConfig)
