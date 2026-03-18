"""
Institutional-grade configuration management.
Pydantic v2 settings with environment-based secrets.
"""

from __future__ import annotations

import secrets
from enum import Enum
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal, Self

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Environment(str, Enum):
    DEVELOPMENT = "development"
    STAGING = "staging"
    PRODUCTION = "production"


class LogLevel(str, Enum):
    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"


class TradingMode(str, Enum):
    PAPER = "paper"
    LIVE = "live"
    BACKTEST = "backtest"


class DatabaseSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="DB_")
    
    url: str = Field(default="postgresql+asyncpg://localhost:5432/hopefx")
    echo: bool = Field(default=False)
    pool_size: int = Field(default=20)
    max_overflow: int = Field(default=10)
    pool_pre_ping: bool = Field(default=True)
    pool_recycle: int = Field(default=3600)


class RedisSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="REDIS_")
    
    url: str = Field(default="redis://localhost:6379/0")
    socket_connect_timeout: float = Field(default=5.0)
    socket_keepalive: bool = Field(default=True)
    health_check_interval: int = Field(default=30)
    retry_on_timeout: bool = Field(default=True)


class SecuritySettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="SECURITY_")
    
    encryption_key: str = Field(default_factory=lambda: secrets.token_hex(32))
    jwt_secret: str = Field(default_factory=lambda: secrets.token_hex(32))
    jwt_algorithm: str = Field(default="HS256")
    jwt_expiration_hours: int = Field(default=24)
    argon2_time_cost: int = Field(default=3)
    argon2_memory_cost: int = Field(default=65536)
    argon2_parallelism: int = Field(default=4)
    rate_limit_requests: int = Field(default=100)
    rate_limit_window: int = Field(default=60)


class RiskSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="RISK_")
    
    max_position_size_pct: float = Field(default=0.02, gt=0, le=1.0)
    max_daily_loss_pct: float = Field(default=0.05, gt=0, le=1.0)
    max_drawdown_pct: float = Field(default=0.10, gt=0, le=1.0)
    var_confidence: float = Field(default=0.95, gt=0, le=1.0)
    var_horizon_days: int = Field(default=1, ge=1)
    monte_carlo_sims: int = Field(default=10000, ge=1000)
    kill_switch_enabled: bool = Field(default=True)
    circuit_breaker_threshold: int = Field(default=5)
    circuit_breaker_timeout: int = Field(default=300)


class BrokerSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="BROKER_")
    
    default_broker: str = Field(default="paper")
    oanda_account_id: str | None = Field(default=None)
    oanda_api_key: str | None = Field(default=None, repr=False)
    oanda_environment: Literal["practice", "live"] = Field(default="practice")
    mt5_server: str | None = Field(default=None)
    mt5_login: int | None = Field(default=None)
    mt5_password: str | None = Field(default=None, repr=False)
    ib_gateway_host: str = Field(default="127.0.0.1")
    ib_gateway_port: int = Field(default=4002)
    binance_api_key: str | None = Field(default=None, repr=False)
    binance_secret: str | None = Field(default=None, repr=False)
    binance_testnet: bool = Field(default=True)


class MLSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="ML_")
    
    model_registry_uri: str = Field(default="sqlite:///mlflow.db")
    feature_lookback: int = Field(default=100, ge=10)
    retrain_interval_hours: int = Field(default=24, ge=1)
    prediction_threshold: float = Field(default=0.6, ge=0.5, le=0.95)
    drift_threshold: float = Field(default=0.1, ge=0.01, le=0.5)
    ensemble_voting: Literal["hard", "soft"] = Field(default="soft")
    online_learning_enabled: bool = Field(default=True)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )
    
    app_name: str = Field(default="HOPEFX-AI-TRADING")
    app_version: str = Field(default="2.0.0")
    environment: Environment = Field(default=Environment.DEVELOPMENT)
    debug: bool = Field(default=False)
    log_level: LogLevel = Field(default=LogLevel.INFO)
    trading_mode: TradingMode = Field(default=TradingMode.PAPER)
    
    # Sub-settings
    database: DatabaseSettings = Field(default_factory=DatabaseSettings)
    redis: RedisSettings = Field(default_factory=RedisSettings)
    security: SecuritySettings = Field(default_factory=SecuritySettings)
    risk: RiskSettings = Field(default_factory=RiskSettings)
    broker: BrokerSettings = Field(default_factory=BrokerSettings)
    ml: MLSettings = Field(default_factory=MLSettings)
    
    # Paths
    data_dir: Path = Field(default=Path("./data"))
    logs_dir: Path = Field(default=Path("./logs"))
    models_dir: Path = Field(default=Path("./models"))
    
    @field_validator("data_dir", "logs_dir", "models_dir", mode="before")
    @classmethod
    def ensure_path(cls, v: str | Path) -> Path:
        path = Path(v) if isinstance(v, str) else v
        path.mkdir(parents=True, exist_ok=True)
        return path
    
    @model_validator(mode="after")
    def validate_production(self) -> Self:
        if self.environment == Environment.PRODUCTION:
            if self.debug:
                raise ValueError("Debug cannot be True in production")
            if self.trading_mode == TradingMode.PAPER and not self.broker.default_broker == "paper":
                raise ValueError("Paper trading mode requires paper broker in production")
        return self
    
    @property
    def is_production(self) -> bool:
        return self.environment == Environment.PRODUCTION
    
    @property
    def is_development(self) -> bool:
        return self.environment == Environment.DEVELOPMENT


@lru_cache
def get_settings() -> Settings:
    """Cached settings instance."""
    return Settings()


# Global settings instance
settings = get_settings()
