"""
Configuration Management Module

This module provides professional configuration management with encryption support
for the HOPEFX AI Trading framework.

Main components:
- ConfigManager: Central configuration management
- EncryptionManager: Secure credential encryption
- APIConfig, DatabaseConfig, TradingConfig: Configuration data structures
"""

from .config_manager import (
    ConfigManager,
    DatabaseConfig,
    TradingConfig,
    get_config_manager,
    initialize_config,
)

# EncryptionManager, APIConfig, LoggingConfig, AppConfig were removed from
# config_manager.py in a prior refactor. Import stubs keep existing callers
# from breaking at import time.
class EncryptionManager:  # pragma: no cover
    """Stub — encryption is handled inside ConfigManager._setup_encryption."""
    pass

class APIConfig:  # pragma: no cover
    pass

class LoggingConfig:  # pragma: no cover
    pass

class AppConfig:  # pragma: no cover
    pass
from .feature_flags import FeatureFlags, FeatureStatus, flags

__all__ = [
    'ConfigManager',
    'EncryptionManager',
    'APIConfig',
    'DatabaseConfig',
    'TradingConfig',
    'LoggingConfig',
    'AppConfig',
    'get_config_manager',
    'initialize_config',
    'FeatureFlags',
    'FeatureStatus',
    'flags',
]

# Module metadata
__version__ = '1.0.0'
__author__ = 'HOPEFX Development Team'
__description__ = 'Configuration management with encryption support'
