"""Pydantic v2 settings with vault integration."""
from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from configs.vault import vault


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


class BrokerSettings(BaseSettings):
    oanda_token: SecretStr | None = None
    oanda_account: str | None = None
    oanda_environment: Literal["practice", "live"] = "practice"
    
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
    
    jwt_secret: SecretStr = Field(default_factory=lambda: SecretStr(os.urandom(32).hex()))
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 30
    refresh_token_expire_days: int = 7
    rate_limit_requests: int = 100
    rate_limit_window: int = 60


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
    
    # Paths
    data_dir: Path = Path("./data")
    log_dir: Path = Path("./logs")
    
    @model_validator(mode="after")
    def validate_paths(self) -> Self:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.ml.model_path.mkdir(parents=True, exist_ok=True)
        self.ml.feature_store_path.mkdir(parents=True, exist_ok=True)
        return self


@lru_cache
def get_settings() -> Settings:
    """Cached settings instance."""
    return Settings()