"""
Professional Configuration Management System
Handles API credentials, trading parameters, and database configuration with encryption support.

Features:
- Encrypted credential storage
- Environment-based configuration
- Type validation
- Secure credential loading
- Configuration hot-reloading
- Audit logging for sensitive operations
"""

import os
import json
import logging
from typing import Any, Dict, Optional, List
from dataclasses import dataclass, asdict, field
from pathlib import Path
from functools import lru_cache
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2
import base64
from datetime import datetime
import hashlib


# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class EncryptionManager:
    """Handles encryption and decryption of sensitive configuration data."""
    
    def __init__(self, master_key: Optional[str] = None):
        """
        Initialize encryption manager.
        
        Args:
            master_key: Master encryption key. If None, generates from environment.
        """
        self.master_key = master_key or os.getenv('CONFIG_ENCRYPTION_KEY')
        if not self.master_key:
            raise ValueError(
                "Encryption key required. Set CONFIG_ENCRYPTION_KEY environment variable "
                "or pass master_key parameter."
            )
        
        self._cipher = self._create_cipher()
        logger.info("Encryption manager initialized")
    
    def _create_cipher(self) -> Fernet:
        """Create Fernet cipher from master key."""
        # Derive a proper key from the master key using PBKDF2
        kdf = PBKDF2(
            algorithm=hashes.SHA256(),
            length=32,
            salt=b'hopefx_ai_trading',  # Static salt for consistency
            iterations=100000,
        )
        key = base64.urlsafe_b64encode(
            kdf.derive(self.master_key.encode())
        )
        return Fernet(key)
    
    def encrypt(self, data: str) -> str:
        """
        Encrypt sensitive string data.
        
        Args:
            data: String to encrypt
            
        Returns:
            Encrypted string (base64 encoded)
        """
        try:
            encrypted = self._cipher.encrypt(data.encode())
            return base64.b64encode(encrypted).decode()
        except Exception as e:
            logger.error(f"Encryption failed: {e}")
            raise
    
    def decrypt(self, encrypted_data: str) -> str:
        """
        Decrypt sensitive string data.
        
        Args:
            encrypted_data: Encrypted string (base64 encoded)
            
        Returns:
            Decrypted string
        """
        try:
            encrypted = base64.b64decode(encrypted_data.encode())
            decrypted = self._cipher.decrypt(encrypted)
            return decrypted.decode()
        except Exception as e:
            logger.error(f"Decryption failed: {e}")
            raise
    
    def hash_password(self, password: str) -> str:
        """
        Hash a password using SHA256 (one-way).
        
        Args:
            password: Password to hash
            
        Returns:
            Hashed password
        """
        return hashlib.sha256(password.encode()).hexdigest()


@dataclass
class APIConfig:
    """API Configuration for trading platforms."""
    
    provider: str
    api_key: str
    api_secret: str
    sandbox_mode: bool = True
    base_url: Optional[str] = None
    timeout: int = 30
    max_retries: int = 3
    rate_limit: int = 100  # requests per minute
    
    def validate(self) -> bool:
        """Validate API configuration."""
        if not all([self.provider, self.api_key, self.api_secret]):
            logger.warning(f"Invalid API config for {self.provider}: missing required fields")
            return False
        return True


@dataclass
class DatabaseConfig:
    """Database Configuration."""
    
    db_type: str  # 'postgresql', 'mysql', 'sqlite'
    host: str
    port: int
    username: str
    password: str
    database: str
    ssl_enabled: bool = True
    connection_pool_size: int = 10
    max_overflow: int = 20
    pool_timeout: int = 30
    
    def get_connection_string(self) -> str:
        """Generate database connection string."""
        if self.db_type == 'sqlite':
            return f"sqlite:///{self.database}"
        elif self.db_type == 'postgresql':
            return (
                f"postgresql://{self.username}:{self.password}@"
                f"{self.host}:{self.port}/{self.database}"
            )
        elif self.db_type == 'mysql':
            return (
                f"mysql+pymysql://{self.username}:{self.password}@"
                f"{self.host}:{self.port}/{self.database}"
            )
        else:
            raise ValueError(f"Unsupported database type: {self.db_type}")
    
    def validate(self) -> bool:
        """Validate database configuration."""
        if self.db_type not in ['postgresql', 'mysql', 'sqlite']:
            logger.warning(f"Invalid database type: {self.db_type}")
            return False
        
        if self.db_type != 'sqlite':
            if not all([self.host, self.port, self.username, self.password, self.database]):
                logger.warning("Invalid database config: missing required fields")
                return False
        
        return True


@dataclass
class TradingConfig:
    """Trading Parameters Configuration."""
    
    max_position_size: float = 10000.0  # Maximum position size in base currency
    max_leverage: float = 1.0
    stop_loss_percent: float = 2.0
    take_profit_percent: float = 5.0
    max_open_orders: int = 10
    risk_per_trade: float = 1.0  # Percentage of portfolio
    daily_loss_limit: float = 5.0  # Percentage of portfolio
    trading_enabled: bool = False  # Safety flag
    paper_trading_mode: bool = True  # Start in paper trading
    
    def validate(self) -> bool:
        """Validate trading configuration."""
        if self.max_position_size <= 0:
            logger.warning("Invalid max_position_size: must be positive")
            return False
        
        if not (0 < self.max_leverage <= 100):
            logger.warning("Invalid max_leverage: must be between 0 and 100")
            return False
        
        if not (0 < self.risk_per_trade < 100):
            logger.warning("Invalid risk_per_trade: must be between 0 and 100")
            return False
        
        return True


@dataclass
class LoggingConfig:
    """Logging Configuration."""
    
    level: str = "INFO"
    log_file: str = "logs/hopefx_ai.log"
    max_file_size_mb: int = 100
    backup_count: int = 10
    format_string: str = '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    
    def validate(self) -> bool:
        """Validate logging configuration."""
        valid_levels = ['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL']
        if self.level not in valid_levels:
            logger.warning(f"Invalid log level: {self.level}")
            return False
        return True


@dataclass
class AppConfig:
    """Main Application Configuration."""
    
    app_name: str = "HOPEFX AI Trading"
    version: str = "1.0.0"
    environment: str = "development"  # development, staging, production
    debug: bool = False
    api_configs: Dict[str, APIConfig] = field(default_factory=dict)
    database: DatabaseConfig = field(default_factory=lambda: DatabaseConfig(
        db_type="sqlite",
        host="localhost",
        port=5432,
        username="",
        password="",
        database="hopefx.db"
    ))
    trading: TradingConfig = field(default_factory=TradingConfig)
    logging: LoggingConfig = field(default_factory=LoggingConfig)
    
    def validate(self) -> bool:
        """Validate all configuration sections."""
        validations = [
            self.database.validate(),
            self.trading.validate(),
            self.logging.validate(),
        ]
        
        for api_config in self.api_configs.values():
            validations.append(api_config.validate())
        
        if not all(validations):
            logger.warning("Configuration validation failed")
            return False
        
        logger.info("Configuration validation passed")
        return True


class ConfigManager:
    """Professional configuration management with encryption support."""
    
    def __init__(self, config_dir: str = "config", encryption_key: Optional[str] = None):
        """
        Initialize configuration manager.
        
        Args:
            config_dir: Directory containing configuration files
            encryption_key: Master encryption key for credentials
        """
        self.config_dir = Path(config_dir)
        self.config_dir.mkdir(parents=True, exist_ok=True)
        
        self.encryption = EncryptionManager(encryption_key)
        self.config: Optional[AppConfig] = None
        self._config_hash: Optional[str] = None
        self._load_timestamp: Optional[datetime] = None
        
        logger.info(f"ConfigManager initialized with config_dir: {self.config_dir}")
    
    def load_config(self, environment: Optional[str] = None) -> AppConfig:
        """
        Load configuration from files.
        
        Args:
            environment: Environment to load (uses APP_ENV or 'development' by default)
            
        Returns:
            Loaded AppConfig instance
        """
        env = environment or os.getenv('APP_ENV', 'development')
        config_file = self.config_dir / f"config.{env}.json"
        
        if not config_file.exists():
            logger.warning(f"Config file not found: {config_file}, creating default")
            self._create_default_config(config_file)
        
        try:
            with open(config_file, 'r') as f:
                config_data = json.load(f)
            
            self.config = self._parse_config(config_data)
            self._load_timestamp = datetime.utcnow()
            self._config_hash = self._hash_config()
            
            if not self.config.validate():
                logger.warning("Configuration validation warnings detected")
            
            logger.info(f"Configuration loaded from {config_file}")
            return self.config
        
        except Exception as e:
            logger.error(f"Failed to load configuration: {e}")
            raise
    
    def _parse_config(self, config_data: Dict[str, Any]) -> AppConfig:
        """Parse configuration dictionary into AppConfig object."""
        # Parse API configs
        api_configs = {}
        for provider, api_data in config_data.get('api_configs', {}).items():
            try:
                api_configs[provider] = APIConfig(
                    provider=provider,
                    api_key=self._decrypt_field(api_data.get('api_key')),
                    api_secret=self._decrypt_field(api_data.get('api_secret')),
                    sandbox_mode=api_data.get('sandbox_mode', True),
                    base_url=api_data.get('base_url'),
                    timeout=api_data.get('timeout', 30),
                    max_retries=api_data.get('max_retries', 3),
                    rate_limit=api_data.get('rate_limit', 100),
                )
            except Exception as e:
                logger.error(f"Failed to parse API config for {provider}: {e}")
        
        # Parse database config
        db_data = config_data.get('database', {})
        database = DatabaseConfig(
            db_type=db_data.get('db_type', 'sqlite'),
            host=db_data.get('host', 'localhost'),
            port=db_data.get('port', 5432),
            username=self._decrypt_field(db_data.get('username', '')),
            password=self._decrypt_field(db_data.get('password', '')),
            database=db_data.get('database', 'hopefx.db'),
            ssl_enabled=db_data.get('ssl_enabled', True),
            connection_pool_size=db_data.get('connection_pool_size', 10),
            max_overflow=db_data.get('max_overflow', 20),
            pool_timeout=db_data.get('pool_timeout', 30),
        )
        
        # Parse trading config
        trading_data = config_data.get('trading', {})
        trading = TradingConfig(
            max_position_size=trading_data.get('max_position_size', 10000.0),
            max_leverage=trading_data.get('max_leverage', 1.0),
            stop_loss_percent=trading_data.get('stop_loss_percent', 2.0),
            take_profit_percent=trading_data.get('take_profit_percent', 5.0),
            max_open_orders=trading_data.get('max_open_orders', 10),
            risk_per_trade=trading_data.get('risk_per_trade', 1.0),
            daily_loss_limit=trading_data.get('daily_loss_limit', 5.0),
            trading_enabled=trading_data.get('trading_enabled', False),
            paper_trading_mode=trading_data.get('paper_trading_mode', True),
        )
        
        # Parse logging config
        logging_data = config_data.get('logging', {})
        logging_config = LoggingConfig(
            level=logging_data.get('level', 'INFO'),
            log_file=logging_data.get('log_file', 'logs/hopefx_ai.log'),
            max_file_size_mb=logging_data.get('max_file_size_mb', 100),
            backup_count=logging_data.get('backup_count', 10),
            format_string=logging_data.get('format_string', 
                '%(asctime)s - %(name)s - %(levelname)s - %(message)s'),
        )
        
        # Create main config
        return AppConfig(
            app_name=config_data.get('app_name', 'HOPEFX AI Trading'),
            version=config_data.get('version', '1.0.0'),
            environment=config_data.get('environment', 'development'),
            debug=config_data.get('debug', False),
            api_configs=api_configs,
            database=database,
            trading=trading,
            logging=logging_config,
        )
    
    def save_config(self, config: AppConfig, environment: Optional[str] = None) -> None:
        """
        Save configuration to file with encryption for sensitive data.
        
        Args:
            config: AppConfig instance to save
            environment: Environment name (uses config.environment if not provided)
        """
        env = environment or config.environment
        config_file = self.config_dir / f"config.{env}.json"
        
        try:
            config_data = self._serialize_config(config)
            
            with open(config_file, 'w') as f:
                json.dump(config_data, f, indent=2)
            
            logger.info(f"Configuration saved to {config_file}")
            self.config = config
            self._config_hash = self._hash_config()
            
        except Exception as e:
            logger.error(f"Failed to save configuration: {e}")
            raise
    
    def _serialize_config(self, config: AppConfig) -> Dict[str, Any]:
        """Serialize AppConfig to dictionary with encrypted sensitive data."""
        api_configs = {}
        for provider, api_config in config.api_configs.items():
            api_configs[provider] = {
                'api_key': self._encrypt_field(api_config.api_key),
                'api_secret': self._encrypt_field(api_config.api_secret),
                'sandbox_mode': api_config.sandbox_mode,
                'base_url': api_config.base_url,
                'timeout': api_config.timeout,
                'max_retries': api_config.max_retries,
                'rate_limit': api_config.rate_limit,
            }
        
        return {
            'app_name': config.app_name,
            'version': config.version,
            'environment': config.environment,
            'debug': config.debug,
            'api_configs': api_configs,
            'database': {
                'db_type': config.database.db_type,
                'host': config.database.host,
                'port': config.database.port,
                'username': self._encrypt_field(config.database.username),
                'password': self._encrypt_field(config.database.password),
                'database': config.database.database,
                'ssl_enabled': config.database.ssl_enabled,
                'connection_pool_size': config.database.connection_pool_size,
                'max_overflow': config.database.max_overflow,
                'pool_timeout': config.database.pool_timeout,
            },
            'trading': asdict(config.trading),
            'logging': asdict(config.logging),
        }
    
    def _encrypt_field(self, value: str) -> str:
        """Encrypt a configuration field if not empty."""
        if not value:
            return ""
        return self.encryption.encrypt(value)
    
    def _decrypt_field(self, value: str) -> str:
        """Decrypt a configuration field if not empty."""
        if not value:
            return ""
        try:
            return self.encryption.decrypt(value)
        except Exception as e:
            logger.warning(f"Failed to decrypt field: {e}")
            return value
    
    def _create_default_config(self, config_file: Path) -> None:
        """Create a default configuration file."""
        default_config = {
            'app_name': 'HOPEFX AI Trading',
            'version': '1.0.0',
            'environment': 'development',
            'debug': True,
            'api_configs': {
                'binance': {
                    'api_key': '',
                    'api_secret': '',
                    'sandbox_mode': True,
                    'base_url': 'https://testnet.binance.vision',
                    'timeout': 30,
                    'max_retries': 3,
                    'rate_limit': 100,
                }
            },
            'database': {
                'db_type': 'sqlite',
                'host': 'localhost',
                'port': 5432,
                'username': '',
                'password': '',
                'database': 'hopefx.db',
                'ssl_enabled': True,
                'connection_pool_size': 10,
                'max_overflow': 20,
                'pool_timeout': 30,
            },
            'trading': {
                'max_position_size': 10000.0,
                'max_leverage': 1.0,
                'stop_loss_percent': 2.0,
                'take_profit_percent': 5.0,
                'max_open_orders': 10,
                'risk_per_trade': 1.0,
                'daily_loss_limit': 5.0,
                'trading_enabled': False,
                'paper_trading_mode': True,
            },
            'logging': {
                'level': 'INFO',
                'log_file': 'logs/hopefx_ai.log',
                'max_file_size_mb': 100,
                'backup_count': 10,
                'format_string': '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
            },
        }
        
        with open(config_file, 'w') as f:
            json.dump(default_config, f, indent=2)
        
        logger.info(f"Default configuration created: {config_file}")
    
    def get_api_config(self, provider: str) -> Optional[APIConfig]:
        """Get API configuration for a specific provider."""
        if not self.config:
            raise RuntimeError("Configuration not loaded. Call load_config() first.")
        return self.config.api_configs.get(provider)
    
    def update_api_credential(self, provider: str, api_key: str, api_secret: str) -> None:
        """
        Update API credentials for a provider (without saving to disk).
        
        Args:
            provider: API provider name
            api_key: New API key
            api_secret: New API secret
        """
        if not self.config:
            raise RuntimeError("Configuration not loaded. Call load_config() first.")
        
        if provider not in self.config.api_configs:
            self.config.api_configs[provider] = APIConfig(
                provider=provider,
                api_key=api_key,
                api_secret=api_secret,
            )
        else:
            self.config.api_configs[provider].api_key = api_key
            self.config.api_configs[provider].api_secret = api_secret
        
        logger.info(f"API credentials updated for {provider}")
    
    def is_config_modified(self) -> bool:
        """Check if configuration has been modified since last load."""
        if not self.config or not self._config_hash:
            return False
        return self._config_hash != self._hash_config()
    
    def _hash_config(self) -> str:
        """Generate hash of current configuration."""
        if not self.config:
            return ""
        config_str = json.dumps(self._serialize_config(self.config), sort_keys=True)
        return hashlib.sha256(config_str.encode()).hexdigest()
    
    def reload_config(self) -> AppConfig:
        """Reload configuration from file."""
        if not self.config:
            raise RuntimeError("Configuration not loaded. Call load_config() first.")
        return self.load_config(self.config.environment)
    
    def get_status(self) -> Dict[str, Any]:
        """Get configuration manager status."""
        return {
            'loaded': self.config is not None,
            'environment': self.config.environment if self.config else None,
            'last_load': self._load_timestamp.isoformat() if self._load_timestamp else None,
            'modified': self.is_config_modified(),
            'config_hash': self._config_hash,
        }


# Singleton instance
_config_manager: Optional[ConfigManager] = None


def get_config_manager(config_dir: str = "config") -> ConfigManager:
    """
    Get or create the global ConfigManager instance.
    
    Args:
        config_dir: Configuration directory path
        
    Returns:
        ConfigManager instance
    """
    global _config_manager
    if _config_manager is None:
        encryption_key = os.getenv('CONFIG_ENCRYPTION_KEY')
        _config_manager = ConfigManager(config_dir, encryption_key)
    return _config_manager


def initialize_config(config_dir: str = "config", environment: Optional[str] = None) -> AppConfig:
    """
    Initialize and load configuration.
    
    Args:
        config_dir: Configuration directory path
        environment: Environment to load
        
    Returns:
        Loaded AppConfig instance
    """
    manager = get_config_manager(config_dir)
    return manager.load_config(environment)


if __name__ == "__main__":
    # Example usage
    print("Configuration Management System")
    print("-" * 50)
    
    # Set encryption key for this example
    os.environ['CONFIG_ENCRYPTION_KEY'] = 'your-secure-encryption-key-min-32-chars'
    
    try:
        # Initialize configuration
        config = initialize_config()
        
        # Display status
        manager = get_config_manager()
        status = manager.get_status()
        print(f"Config Status: {json.dumps(status, indent=2)}")
        
        # Display active configuration
        print(f"\nActive Configuration:")
        print(f"  App: {config.app_name} v{config.version}")
        print(f"  Environment: {config.environment}")
        print(f"  Database: {config.database.db_type}")
        print(f"  Trading Enabled: {config.trading.trading_enabled}")
        print(f"  Paper Trading: {config.trading.paper_trading_mode}")
        
    except Exception as e:
        print(f"Error: {e}")
