# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
# security/production_config.py
"""
Production-grade configuration security
NO FALLBACK KEYS - Fail secure
"""

import logging
import os
import secrets
import sys

logger = logging.getLogger(__name__)


class SecureConfigError(Exception):
    """Raised when secure configuration cannot be established"""


class ProductionConfigManager:
    """
    Configuration manager that FAILS SECURE
    No default keys, no development fallbacks in production
    """

    def __init__(self, env: str = "production"):
        self.env = env
        self._encryption_key: bytes | None = None
        self._salt: bytes | None = None

    def initialize(self) -> None:
        """
        Initialize configuration - FAILS if secrets not provided
        """
        if self.env == "production":
            self._initialize_production()
        else:
            self._initialize_development()

    def _initialize_production(self) -> None:
        """Production: Strict requirements, no fallbacks"""
        # ENCRYPTION KEY
        key = os.getenv("HOPEFX_ENCRYPTION_KEY")
        if not key:
            raise SecureConfigError(
                "CRITICAL: HOPEFX_ENCRYPTION_KEY not set. "
                'Generate with: python -c "import secrets; logger.info(secrets.token_hex(32))" '
                "Then export HOPEFX_ENCRYPTION_KEY=<generated_key>"
            )

        # Validate key strength
        try:
            key_bytes = bytes.fromhex(key)
            if len(key_bytes) < 32:
                raise SecureConfigError(f"Encryption key must be 32+ bytes, got {len(key_bytes)}")
        except ValueError:
            raise SecureConfigError("Encryption key must be valid hexadecimal") from None

        self._encryption_key = key_bytes

        # SALT
        salt = os.getenv("HOPEFX_SALT")
        if not salt:
            raise SecureConfigError(
                'CRITICAL: HOPEFX_SALT not set. Generate with: python -c "import secrets; logger.error(secrets.token_hex(16))"'
            )

        try:
            salt_bytes = bytes.fromhex(salt)
            if len(salt_bytes) < 16:
                raise SecureConfigError(f"Salt must be 16+ bytes, got {len(salt_bytes)}")
        except ValueError:
            raise SecureConfigError("Salt must be valid hexadecimal") from None

        self._salt = salt_bytes

        # Additional production checks
        self._validate_production_environment()

    def _validate_production_environment(self) -> None:
        """Validate production environment security"""

        # Check for debug mode
        debug = os.getenv("DEBUG", "false").lower()
        if debug in ["true", "1", "yes"]:
            raise SecureConfigError("DEBUG mode must be disabled in production")

        # Check for secure database URL
        db_url = os.getenv("DATABASE_URL", "")
        if "localhost" in db_url or "127.0.0.1" in db_url:
            raise SecureConfigError("Production must use external database, not localhost")

        # Check for HTTPS
        api_url = os.getenv("API_BASE_URL", "")
        if api_url and not api_url.startswith("https://"):
            raise SecureConfigError("Production API must use HTTPS")

        # Check for weak JWT secret — accept canonical name or legacy alias.
        jwt_secret = os.getenv("SECURITY_JWT_SECRET", "").strip() or os.getenv("JWT_SECRET_KEY", "").strip()
        if not jwt_secret:
            raise SecureConfigError(
                "SECURITY_JWT_SECRET is not set. "
                'Generate with: python -c "import secrets; logger.info(secrets.token_urlsafe(48))"'
            )
        if len(jwt_secret) < 32:
            raise SecureConfigError(f"SECURITY_JWT_SECRET is too short ({len(jwt_secret)} chars). Must be >=32.")
        if jwt_secret.startswith("CHANGE_ME"):
            raise SecureConfigError("SECURITY_JWT_SECRET contains a placeholder value. Replace before deploying.")

    def _initialize_development(self) -> None:
        """Development: Generate temporary keys with warnings"""
        import warnings

        warnings.warn("DEVELOPMENT MODE: Using auto-generated temporary keys", RuntimeWarning, stacklevel=2)

        self._encryption_key = secrets.token_bytes(32)
        self._salt = secrets.token_bytes(16)

        logger.info("=" * 70)
        logger.info("DEVELOPMENT KEYS GENERATED (DO NOT USE IN PRODUCTION)")
        logger.info("Encryption Key: %s", self._encryption_key.hex())
        logger.info("Salt: %s", self._salt.hex())
        logger.info("Set these in environment for persistence")
        logger.info("=" * 70)

    @property
    def encryption_key(self) -> bytes:
        if self._encryption_key is None:
            raise SecureConfigError("Configuration not initialized")
        return self._encryption_key

    @property
    def salt(self) -> bytes:
        if self._salt is None:
            raise SecureConfigError("Configuration not initialized")
        return self._salt


# Update main.py to use secure config
def initialize_secure_config():
    """Initialize with fail-secure configuration"""
    env = os.getenv("HOPEFX_ENV", "production")

    try:
        config_manager = ProductionConfigManager(env=env)
        config_manager.initialize()
        return config_manager
    except SecureConfigError as e:
        logger.critical("Configuration error: %s", e)

        sys.exit(1)  # HARD FAIL - No insecure fallbacks
