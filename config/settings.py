# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""Pydantic v2 settings with vault integration."""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from config.vault import vault


import logging

logger = logging.getLogger(__name__)


class DatabaseSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="DB_")

    url: SecretStr = Field(default="postgresql+asyncpg://localhost/hopefx")
    pool_size: int = 20
    max_overflow: int = 10
    echo: bool = False

    @field_validator("url", mode="before")
    @classmethod
    def decrypt_if_vaulted(cls, v: Any) -> Any:
        if isinstance(v, str) and v.startswith("vault:"):
            return vault.decrypt(v[6:])
        return v


class RedisSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="REDIS_")

    url: SecretStr = Field(default="redis://localhost:6379/0")
    socket_timeout: float = 5.0
    socket_connect_timeout: float = 5.0
    health_check_interval: int = 30
    max_connections: int = 100
    # TLS enforcement — IS_FORCE_TLS (canonical) or REDIS_FORCE_TLS (alias)
    force_tls: bool = Field(default=False, alias="REDIS_FORCE_TLS")
    tls_skip_verify: bool = Field(default=False, alias="REDIS_TLS_SKIP_VERIFY")
    tls_ca_cert: str = Field(default="", alias="REDIS_TLS_CA_CERT")
    tls_client_cert: str = Field(default="", alias="REDIS_TLS_CLIENT_CERT")
    tls_client_key: str = Field(default="", alias="REDIS_TLS_CLIENT_KEY")

    @model_validator(mode="before")
    @classmethod
    def _resolve_is_force_tls(cls, values: Any) -> Any:
        """IS_FORCE_TLS overrides REDIS_FORCE_TLS when set."""
        if isinstance(values, dict):
            is_force = os.getenv("IS_FORCE_TLS", "").lower()
            if is_force == "true":
                values["REDIS_FORCE_TLS"] = True
        return values


def resolve_oanda_token() -> str:
    """
    Return the OANDA API token from the first set env var in priority order.

    Canonical name: OANDA_API_KEY
    Accepted aliases (legacy / broker-config style):
      OANDA_ACCESS_TOKEN, OANDA_API_TOKEN, BROKER_OANDA_TOKEN

    Use this helper everywhere instead of calling os.getenv() directly so
    that operators only need to set one variable and the alias confusion is
    contained to a single place.
    """
    for var in (
        "OANDA_API_KEY",
        "OANDA_ACCESS_TOKEN",
        "OANDA_API_TOKEN",
        "BROKER_OANDA_TOKEN",
    ):
        val = os.getenv(var, "").strip()
        if val:
            if var != "OANDA_API_KEY":
                logger.warning(
                    "OANDA token read from %s — prefer OANDA_API_KEY (canonical name)", var
                )
            return val
    return ""


def resolve_oanda_account() -> str:
    """
    Return the OANDA account ID from the first set env var in priority order.

    Canonical name: OANDA_ACCOUNT_ID
    Accepted alias: BROKER_OANDA_ACCOUNT
    """
    for var in ("OANDA_ACCOUNT_ID", "BROKER_OANDA_ACCOUNT"):
        val = os.getenv(var, "").strip()
        if val:
            if var != "OANDA_ACCOUNT_ID":
                logger.warning(
                    "OANDA account ID read from %s — prefer OANDA_ACCOUNT_ID (canonical name)", var
                )
            return val
    return ""


def resolve_oanda_environment() -> str:
    """
    Return the OANDA environment ('practice' or 'live') from env vars.

    Canonical name: OANDA_ENVIRONMENT
    Accepted aliases: OANDA_ENV, BROKER_OANDA_ENVIRONMENT
    """
    for var in ("OANDA_ENVIRONMENT", "OANDA_ENV", "BROKER_OANDA_ENVIRONMENT"):
        val = os.getenv(var, "").strip().lower()
        if val in ("practice", "live"):
            if var != "OANDA_ENVIRONMENT":
                logger.warning(
                    "OANDA environment read from %s — prefer OANDA_ENVIRONMENT (canonical name)", var
                )
            return val
    return "practice"


class BrokerSettings(BaseSettings):
    model_config = SettingsConfigDict(env_ignore_empty=True)

    # OANDA — resolved via resolve_oanda_token() to handle all legacy aliases.
    # Do not add new OANDA_* aliases here; update resolve_oanda_token() instead.
    oanda_token: SecretStr | None = None
    oanda_account: str | None = None
    oanda_environment: Literal["practice", "live"] = "practice"

    @model_validator(mode="before")
    @classmethod
    def _resolve_oanda_aliases(cls, values: Any) -> Any:
        """Populate oanda_token/account/environment from canonical resolver."""
        if isinstance(values, dict):
            if not values.get("oanda_token"):
                token = resolve_oanda_token()
                if token:
                    values["oanda_token"] = token
            if not values.get("oanda_account"):
                account = resolve_oanda_account()
                if account:
                    values["oanda_account"] = account
            if not values.get("oanda_environment"):
                values["oanda_environment"] = resolve_oanda_environment()
        return values

    mt5_server: str | None = None
    mt5_login: int | None = None
    mt5_password: SecretStr | None = None

    ibkr_host: str = "127.0.0.1"
    ibkr_port: int = 7497
    ibkr_client_id: int = 1

    binance_key: SecretStr | None = None
    binance_secret: SecretStr | None = None
    binance_testnet: bool = True


class MLSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="ML_")

    model_path: Path = Path("./models")
    feature_store_path: Path = Path("./data/features")
    retrain_interval_minutes: int = 60
    drift_threshold: float = 0.05
    ensemble_weights: list[float] = Field(default=[0.4, 0.35, 0.25])
    online_learning_rate: float = 0.01


class RiskSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="RISK_")

    max_daily_loss_pct: float = 2.0
    max_position_size_pct: float = 5.0
    max_open_positions: int = 5
    var_confidence: float = 0.95
    var_horizon_days: int = 1
    monte_carlo_sims: int = 10000
    circuit_breaker_threshold: float = 1000.0  # USD


class SecuritySettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="SECURITY_")

    # Accepts SECURITY_JWT_SECRET (primary) or JWT_SECRET_KEY (legacy alias).
    jwt_secret: SecretStr = Field(default=...)
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 30
    refresh_token_expire_days: int = 7
    rate_limit_requests: int = 100
    rate_limit_window: int = 60

    @model_validator(mode="before")
    @classmethod
    def _resolve_jwt_secret(cls, values: Any) -> Any:
        """Accept JWT_SECRET_KEY as a fallback alias for SECURITY_JWT_SECRET."""
        if isinstance(values, dict) and not values.get("jwt_secret"):
            alias = os.getenv("JWT_SECRET_KEY", "")
            if alias:
                values["jwt_secret"] = alias
        return values

    @field_validator("jwt_secret", mode="before")
    @classmethod
    def require_jwt_secret(cls, v: Any) -> Any:
        raw = v.get_secret_value() if hasattr(v, "get_secret_value") else str(v)
        if not raw or raw.startswith("CHANGE_ME"):
            raise ValueError(
                "SECURITY_JWT_SECRET must be set to a strong random value. "
                'Generate one with: python -c "import secrets; logger.info(secrets.token_hex(32))"'
            )
        return v


class NewsSettings(BaseSettings):
    """News and geopolitical data source configuration."""

    model_config = SettingsConfigDict(env_prefix="NEWS_")

    # World Monitor — open-source geopolitical intelligence dashboard
    # Public API: https://worldmonitor.app/docs/api-reference
    # GitHub: https://github.com/koala73/worldmonitor
    #
    # The public REST API requires no authentication for web access.
    # WORLDMONITOR_API_URL: override only when running a self-hosted instance.
    worldmonitor_api_url: str = Field(
        default="https://worldmonitor.app",
        alias="WORLDMONITOR_API_URL",
    )
    worldmonitor_timeout: int = 30

    # GDELT — free global news intelligence (no key required)
    gdelt_enabled: bool = True
    gdelt_timeout: int = 15

    # ACLED — conflict event data (free academic key)
    acled_api_key: str = Field(default="", alias="ACLED_API_KEY")
    acled_email: str = Field(default="", alias="ACLED_EMAIL")
    acled_enabled: bool = True
    acled_timeout: int = 15

    # ReliefWeb — humanitarian crisis data (no key required)
    reliefweb_enabled: bool = True
    reliefweb_timeout: int = 15

    # Cache TTL for geopolitical events
    geo_cache_ttl_seconds: int = 300

    @model_validator(mode="before")
    @classmethod
    def _resolve_aliases(cls, values: Any) -> Any:
        """Pull top-level env vars that don't carry the NEWS_ prefix."""
        if isinstance(values, dict):
            for alias in ("WORLDMONITOR_API_URL", "ACLED_API_KEY", "ACLED_EMAIL"):
                env_val = os.getenv(alias, "")
                if env_val and alias not in values:
                    values[alias] = env_val
        return values


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    env: Literal["development", "staging", "production"] = "development"
    debug: bool = False
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"

    # Sub-settings
    db: DatabaseSettings = Field(default_factory=DatabaseSettings)
    redis: RedisSettings = Field(default_factory=RedisSettings)
    broker: BrokerSettings = Field(default_factory=BrokerSettings)
    ml: MLSettings = Field(default_factory=MLSettings)
    risk: RiskSettings = Field(default_factory=RiskSettings)
    security: SecuritySettings = Field(default_factory=SecuritySettings)
    news: NewsSettings = Field(default_factory=NewsSettings)

    # TLS flags at top level (mirrors redis sub-settings for convenience)
    is_force_tls: bool = Field(default=False, alias="IS_FORCE_TLS")
    redis_force_tls: bool = Field(default=False, alias="REDIS_FORCE_TLS")

    # Paths
    data_dir: Path = Path("./data")
    log_dir: Path = Path("./logs")

    @model_validator(mode="after")
    def validate_paths(self) -> Settings:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.ml.model_path.mkdir(parents=True, exist_ok=True)  # pylint: disable=no-member
        self.ml.feature_store_path.mkdir(parents=True, exist_ok=True)  # pylint: disable=no-member
        return self


@lru_cache
def get_settings() -> Settings:
    """Cached settings instance."""
    return Settings()
