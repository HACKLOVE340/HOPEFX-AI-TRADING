"""
Configuration Management
- Environment-based settings
- Secret management
- Profile support
"""

import os
from dataclasses import dataclass
from typing import Optional
import json

@dataclass
class DatabaseConfig:
    """Database configuration"""
    host: str = os.getenv('DB_HOST', 'localhost')
    port: int = int(os.getenv('DB_PORT', '5432'))
    username: str = os.getenv('DB_USER', 'hopefx')
    password: str = os.getenv('DB_PASSWORD', '')
    database: str = os.getenv('DB_NAME', 'hopefx_db')

@dataclass
class BrokerConfig:
    """Broker configuration"""
    ftmo_api_key: str = os.getenv('FTMO_API_KEY', '')
    ftmo_api_secret: str = os.getenv('FTMO_API_SECRET', '')
    the5ers_api_key: str = os.getenv('THE5ERS_API_KEY', '')
    myforexfunds_api_key: str = os.getenv('MYFOREXFUNDS_API_KEY', '')
    topstep_api_key: str = os.getenv('TOPSTEP_API_KEY', '')

@dataclass
class MLConfig:
    """Machine Learning configuration"""
    model_version: str = "v2.0"
    lstm_sequence_length: int = 60
    lstm_units: int = 64
    lstm_dropout: float = 0.2
    ensemble_models: int = 3
    min_confidence: float = 0.70

@dataclass
class TradingConfig:
    """Trading configuration"""
    default_risk_percent: float = 0.02  # 2%
    max_position_size: float = 0.10  # 10% of account
    max_drawdown_allowed: float = 0.20  # 20%
    copy_trading_commission: float = 0.20  # 20%

@dataclass
class APIConfig:
    """API configuration"""
    host: str = os.getenv('API_HOST', '0.0.0.0')
    port: int = int(os.getenv('API_PORT', '8000'))
    workers: int = int(os.getenv('API_WORKERS', '4'))
    debug: bool = os.getenv('API_DEBUG', 'false').lower() == 'true'
    log_level: str = os.getenv('LOG_LEVEL', 'INFO')

class Config:
    """Main configuration class"""
    
    def __init__(self, profile: str = 'production'):
        self.profile = profile
        self.database = DatabaseConfig()
        self.broker = BrokerConfig()
        self.ml = MLConfig()
        self.trading = TradingConfig()
        self.api = APIConfig()
    
    @classmethod
    def from_env(cls, profile: Optional[str] = None):
        """Load config from environment"""
        profile = profile or os.getenv('HOPEFX_PROFILE', 'production')
        return cls(profile)
    
    def to_dict(self) -> dict:
        """Convert to dictionary"""
        return {
            'profile': self.profile,
            'database': self.database.__dict__,
            'broker': self.broker.__dict__,
            'ml': self.ml.__dict__,
            'trading': self.trading.__dict__,
            'api': self.api.__dict__
        }
    
    def save(self, filepath: str):
        """Save config to file"""
        with open(filepath, 'w') as f:
            json.dump(self.to_dict(), f, indent=2)

# Global config instance
_config = None

def get_config() -> Config:
    """Get global config instance"""
    global _config
    if _config is None:
        _config = Config.from_env()
    return _config

def set_config(config: Config):
    """Set global config instance"""
    global _config
    _config = config