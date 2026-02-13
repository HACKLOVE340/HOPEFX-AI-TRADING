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
    EncryptionManager,
    APIConfig,
    DatabaseConfig,
    TradingConfig,
    LoggingConfig,
    AppConfig,
    get_config_manager,
    initialize_config,
)

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
]
