# src/hopefx/config/settings.py
"""
Centralized configuration management with Pydantic v2.
Environment-aware, secrets-safe, strictly typed.
"""

from __future__ import annotations

import os
from enum import Enum
from functools import lru_cache
from pathlib import Path
from typing import Literal, Self

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Environment(str, Enum):
    """Deployment environment."""
    DEVELOPMENT = "development"
    STAGING = "staging"
    PRODUCTION = "production"
    TESTING = "testing"


class LogLevel(str, Enum):
    """Structured logging levels."""
    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"


class DatabaseConfig(BaseSettings):
    """PostgreSQL/TimescaleDB configuration."""
    model_config = SettingsConfigDict(env_prefix="DB_")
    
    host: str = "localhost"
    port: int = 5432
    name: str = "hopefx"
    user: str = "hopefx"
    password: str = Field(default="", repr=False)
    pool_size: int = 20
    max_overflow: int = 10
    echo: bool = False
    
    @property
    def async_url(self) -> str:
        """Async PostgreSQL URL."""
        return f"postgresql+asyncpg://{self.user}:{self.password}@{self.host}:{self.port}/{self.name}"


class RedisConfig(BaseSettings):
    """Redis configuration."""
    model_config = SettingsConfigDict(env_prefix="REDIS_")
    
    host: str = "localhost"
    port: int = 6379
    db: int = 0
    password: str | None = Field(default=None, repr=False)
    ssl: bool = False
    socket_timeout: float = 5.0
    socket_connect_timeout: float = 5.0
    max_connections: int = 100


class SecurityConfig(BaseSettings):
    """Security hardening configuration."""
    model_config = SettingsConfigDict(env_prefix="SECURITY_")
    
    secret_key: str = Field(default="", repr=False, min_length=32)
    algorithm: Literal["HS256", "HS384", "HS512"] = "HS256"
    access_token_expire_minutes: int = 30
    refresh_token_expire_days: int = 7
    argon2_time_cost: int = 3
    argon2_memory_cost: int = 65536
    argon2_parallelism: int = 4
    rate_limit_requests: int = 100
    rate_limit_window: int = 60
    cors_origins: list[str] = Field(default_factory=list)
    allowed_hosts: list[str] = Field(default_factory=lambda: ["*"])
    
    @field_validator("secret_key", mode="after")
    @classmethod
    def validate_secret_key(cls, v: str) -> str:
        if len(v) < 32:
            raise ValueError("SECRET_KEY must be at least 32 characters")
        return v


class TradingConfig(BaseSettings):
    """Trading parameters."""
    model_config = SettingsConfigDict(env_prefix="TRADING_")
    
    default_symbol: str = "XAUUSD"
    default_timeframe: str = "M5"
    max_position_size: float = 100.0  # Lots
    max_daily_loss_pct: float = 2.0
    max_drawdown_pct: float = 5.0
    risk_per_trade_pct: float = 1.0
    paper_trading: bool = True
    slippage_model: Literal["fixed", "volatility", "none"] = "volatility"


class MLConfig(BaseSettings):
    """Machine learning configuration."""
    model_config = SettingsConfigDict(env_prefix="ML_")
    
    model_registry_path: Path = Path("./models")
    feature_lookback: int = 100
    prediction_horizon: int = 5
    retrain_interval_hours: int = 24
    confidence_threshold: float = 0.65
    drift_threshold: float = 0.05
    device: Literal["cpu", "cuda", "mps"] = "cpu"


class BrokerConfig(BaseSettings):
    """Broker-specific configurations."""
    model_config = SettingsConfigDict(env_prefix="BROKER_")
    
    oanda_api_key: str = Field(default="", repr=False)
    oanda_account_id: str = ""
    oanda_environment: Literal["practice", "live"] = "practice"
    
    mt5_server: str = ""
    mt5_login: int = 0
    mt5_password: str = Field(default="", repr=False)
    
    ib_host: str = "127.0.0.1"
    ib_port: int = 7497
    ib_client_id: int = 1


class Settings(BaseSettings):
    """Root configuration."""
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )
    
    app_name: str = "HOPEFX v6.0"
    version: str = "6.0.0"
    environment: Environment = Environment.DEVELOPMENT
    debug: bool = False
    log_level: LogLevel = LogLevel.INFO
    
    # Sub-configs
    database: DatabaseConfig = Field(default_factory=DatabaseConfig)
    redis: RedisConfig = Field(default_factory=RedisConfig)
    security: SecurityConfig = Field(default_factory=SecurityConfig)
    trading: TradingConfig = Field(default_factory=TradingConfig)
    ml: MLConfig = Field(default_factory=MLConfig)
    broker: BrokerConfig = Field(default_factory=BrokerConfig)
    
    @model_validator(mode="after")
    def validate_environment(self) -> Self:
        """Cross-field validation."""
        if self.environment == Environment.PRODUCTION:
            if self.debug:
                raise ValueError("DEBUG cannot be True in production")
            if self.trading.paper_trading is False:
                # Require explicit confirmation for live trading
                if os.getenv("LIVE_TRADING_CONFIRMED") != "I_UNDERSTAND_RISKS":
                    raise ValueError("Live trading requires LIVE_TRADING_CONFIRMED=I_UNDERSTAND_RISKS")
        return self
    
    @property
    def is_production(self) -> bool:
        return self.environment == Environment.PRODUCTION
    
    @property
    def is_testing(self) -> bool:
        return self.environment == Environment.TESTING


@lru_cache
def get_settings() -> Settings:
    """Cached settings singleton."""
    return Settings()


# Export for convenience
settings = get_settings()
