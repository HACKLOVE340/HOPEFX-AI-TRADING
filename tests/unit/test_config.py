"""
Tests for the config management module.
"""

import pytest
import os
from unittest.mock import patch

from config.config_manager import (
    EncryptionManager,
    ConfigManager,
    APIConfig,
    DatabaseConfig,
    TradingConfig,
    LoggingConfig,
    AppConfig,
)


class TestEncryptionManager:
    """Tests for EncryptionManager class."""
    
    @pytest.fixture(autouse=True)
    def setup_env(self):
        """Set up encryption environment variables."""
        # Store original env vars
        original_key = os.environ.get('CONFIG_ENCRYPTION_KEY')
        original_salt = os.environ.get('CONFIG_SALT')
        
        # Set test values
        os.environ['CONFIG_ENCRYPTION_KEY'] = 'test-encryption-key-for-testing-purposes'
        os.environ['CONFIG_SALT'] = 'a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6'
        
        yield
        
        # Restore original values
        if original_key:
            os.environ['CONFIG_ENCRYPTION_KEY'] = original_key
        elif 'CONFIG_ENCRYPTION_KEY' in os.environ:
            del os.environ['CONFIG_ENCRYPTION_KEY']
            
        if original_salt:
            os.environ['CONFIG_SALT'] = original_salt
        elif 'CONFIG_SALT' in os.environ:
            del os.environ['CONFIG_SALT']
    
    def test_encryption_manager_initialization(self):
        """Test EncryptionManager initialization."""
        manager = EncryptionManager()
        
        assert manager is not None
        assert manager.master_key is not None
    
    def test_encryption_manager_with_explicit_key(self):
        """Test EncryptionManager with explicit key."""
        manager = EncryptionManager(master_key='my-explicit-test-key')
        
        assert manager.master_key == 'my-explicit-test-key'
    
    def test_encrypt_decrypt_roundtrip(self):
        """Test encryption and decryption roundtrip."""
        manager = EncryptionManager()
        
        original = "sensitive-api-key-12345"
        encrypted = manager.encrypt(original)
        decrypted = manager.decrypt(encrypted)
        
        assert decrypted == original
        assert encrypted != original  # Should be different when encrypted
    
    def test_encrypt_decrypt_complex_string(self):
        """Test encryption with complex strings."""
        manager = EncryptionManager()
        
        original = '{"api_key": "abc123", "secret": "xyz!@#$%"}'
        encrypted = manager.encrypt(original)
        decrypted = manager.decrypt(encrypted)
        
        assert decrypted == original
    
    def test_encrypt_empty_string(self):
        """Test encryption of empty string."""
        manager = EncryptionManager()
        
        encrypted = manager.encrypt("")
        decrypted = manager.decrypt(encrypted)
        
        assert decrypted == ""
    
    def test_hash_password(self):
        """Test password hashing."""
        manager = EncryptionManager()
        
        password = "my_secure_password_123"
        hashed = manager.hash_password(password)
        
        assert hashed is not None
        assert '$' in hashed  # Format should be salt$hash
        assert hashed != password  # Should be different from original
    
    def test_verify_password_correct(self):
        """Test correct password verification."""
        manager = EncryptionManager()
        
        password = "my_secure_password_123"
        hashed = manager.hash_password(password)
        
        assert manager.verify_password(password, hashed) is True
    
    def test_verify_password_incorrect(self):
        """Test incorrect password verification."""
        manager = EncryptionManager()
        
        password = "my_secure_password_123"
        hashed = manager.hash_password(password)
        
        assert manager.verify_password("wrong_password", hashed) is False
    
    def test_different_passwords_different_hashes(self):
        """Test that different passwords produce different hashes."""
        manager = EncryptionManager()
        
        hash1 = manager.hash_password("password1")
        hash2 = manager.hash_password("password2")
        
        assert hash1 != hash2
    
    def test_same_password_different_salts(self):
        """Test that same password with different salts produces different hashes."""
        manager = EncryptionManager()
        
        # Each call generates a new random salt
        hash1 = manager.hash_password("same_password")
        hash2 = manager.hash_password("same_password")
        
        assert hash1 != hash2


class TestAPIConfig:
    """Tests for APIConfig dataclass."""
    
    def test_api_config_creation(self):
        """Test APIConfig creation."""
        config = APIConfig(
            provider='OANDA',
            api_key='test-api-key',
            api_secret='test-api-secret'
        )
        
        assert config.provider == 'OANDA'
        assert config.api_key == 'test-api-key'
        assert config.api_secret == 'test-api-secret'
    
    def test_api_config_defaults(self):
        """Test APIConfig default values."""
        config = APIConfig(
            provider='Binance',
            api_key='key',
            api_secret='secret'
        )
        
        assert config.sandbox_mode is True  # Default should be sandbox
        assert config.timeout == 30
        assert config.max_retries == 3
    
    def test_api_config_validate(self):
        """Test APIConfig validation."""
        config = APIConfig(
            provider='OANDA',
            api_key='key',
            api_secret='secret'
        )
        
        assert config.validate() is True


class TestDatabaseConfig:
    """Tests for DatabaseConfig dataclass."""
    
    def test_database_config_sqlite(self):
        """Test SQLite database config."""
        config = DatabaseConfig(
            db_type='sqlite',
            host='localhost',
            port=5432,
            username='',
            password='',
            database='test.db'
        )
        
        assert config.db_type == 'sqlite'
        assert config.database == 'test.db'
    
    def test_database_config_connection_string_sqlite(self):
        """Test SQLite connection string."""
        config = DatabaseConfig(
            db_type='sqlite',
            host='localhost',
            port=5432,
            username='',
            password='',
            database='test.db'
        )
        
        conn_str = config.get_connection_string()
        assert 'sqlite:///' in conn_str
        assert 'test.db' in conn_str
    
    def test_database_config_postgresql(self):
        """Test PostgreSQL connection string."""
        config = DatabaseConfig(
            db_type='postgresql',
            host='localhost',
            port=5432,
            username='user',
            password='pass',
            database='mydb'
        )
        
        conn_str = config.get_connection_string()
        assert 'postgresql://' in conn_str
        assert 'user:pass' in conn_str


class TestTradingConfig:
    """Tests for TradingConfig dataclass."""
    
    def test_trading_config_paper_trading(self):
        """Test paper trading configuration."""
        config = TradingConfig(
            paper_trading_mode=True,
            trading_enabled=False
        )
        
        assert config.paper_trading_mode is True
        assert config.trading_enabled is False
    
    def test_trading_config_defaults(self):
        """Test TradingConfig defaults."""
        config = TradingConfig()
        
        assert config.paper_trading_mode is True  # Default to paper trading
        assert config.max_position_size == 10000.0
        assert config.risk_per_trade == 1.0  # 1% risk per trade
    
    def test_trading_config_validate(self):
        """Test TradingConfig validation."""
        config = TradingConfig()
        
        assert config.validate() is True


class TestLoggingConfig:
    """Tests for LoggingConfig dataclass."""
    
    def test_logging_config_defaults(self):
        """Test LoggingConfig defaults."""
        config = LoggingConfig()
        
        assert config.level == 'INFO'
        assert config.format_string is not None
        assert 'asctime' in config.format_string
    
    def test_logging_config_validate(self):
        """Test LoggingConfig validation."""
        config = LoggingConfig()
        
        assert config.validate() is True


class TestAppConfig:
    """Tests for AppConfig dataclass."""
    
    def test_app_config_creation(self):
        """Test AppConfig creation."""
        config = AppConfig(
            app_name='Test App',
            version='1.0.0',
            environment='testing'
        )
        
        assert config.app_name == 'Test App'
        assert config.version == '1.0.0'
        assert config.environment == 'testing'
    
    def test_app_config_defaults(self):
        """Test AppConfig defaults."""
        config = AppConfig()
        
        assert config.app_name == 'HOPEFX AI Trading'
        assert config.version == '1.0.0'
        assert config.environment == 'development'
        assert config.debug is False


class TestConfigManager:
    """Tests for ConfigManager class."""
    
    @pytest.fixture(autouse=True)
    def setup_env(self):
        """Set up encryption environment variables."""
        os.environ['CONFIG_ENCRYPTION_KEY'] = 'test-encryption-key-for-testing-purposes'
        os.environ['CONFIG_SALT'] = 'a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6'
        yield
    
    def test_config_manager_initialization(self):
        """Test ConfigManager initialization."""
        manager = ConfigManager()
        
        assert manager is not None
    
    def test_config_manager_with_config_dir(self):
        """Test ConfigManager with specific config directory."""
        import tempfile
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = ConfigManager(config_dir=tmpdir)
            
            assert manager.config_dir.exists()
