# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
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


# EncryptionManager, APIConfig, LoggingConfig, AppConfig were consolidated
# into ConfigManager in a prior refactor. These shims preserve import
# compatibility for callers that reference them by name.
class EncryptionManager:  # pragma: no cover
    """Backwards-compat shim. Encryption is handled by ConfigManager._setup_encryption."""


class APIConfig:  # pragma: no cover
    """Backwards-compat shim. API configuration is managed by ConfigManager."""


class LoggingConfig:  # pragma: no cover
    """Backwards-compat shim. Logging configuration is managed by ConfigManager."""


class AppConfig:  # pragma: no cover
    """Backwards-compat shim. Application configuration is managed by ConfigManager."""


from .feature_flags import FeatureFlags, FeatureStatus, flags

__all__ = [
    "APIConfig",
    "AppConfig",
    "ConfigManager",
    "DatabaseConfig",
    "EncryptionManager",
    "FeatureFlags",
    "FeatureStatus",
    "LoggingConfig",
    "TradingConfig",
    "flags",
    "get_config_manager",
    "initialize_config",
]

# Module metadata
__version__ = "1.0.0"
__author__ = "HOPEFX Development Team"
__description__ = "Configuration management with encryption support"
