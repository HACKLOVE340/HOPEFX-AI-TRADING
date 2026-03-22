"""
Institutional-grade configuration management.
Pydantic v2 with strict validation and secrets handling.
"""
from functools import lru_cache
from typing import Literal, List, Optional
from pydantic import Field, field_validator, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict
import os


class DatabaseSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="DB_")
    
    host: str = "localhost"
    port: int = 5432
    name: str = "hopefx"
    user: str = "hopefx"
    password: SecretStr
    pool_size: int = 20
    max_overflow: int = 10
    echo: bool = False
    
    @property
    def async_url(self) -> str:
        return f"postgresql+asyncpg://{self.user}:{self.password.get_secret_value()}@{self.host}:{self.port}/{self.name}"


class RedisSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="REDIS_")
    
    host: str = "localhost"
    port: int = 6379
    db: int = 0
    password: Optional[SecretStr] = None
    ssl: bool = False


class SecuritySettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="SECURITY_")
    
    encryption_key: SecretStr
    jwt_secret: SecretStr
    jwt_algorithm: str = "HS256"
    jwt_expiration_hours: int = 24
    rate_limit_requests: int = 100
    rate_limit_window: int = 60


class BrokerSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="BROKER_")
    
    default: Literal["paper", "oanda", "mt5", "ibkr", "binance"] = "paper"
    oanda_token: Optional[SecretStr] = None
    oanda_account: Optional[str] = None
    oanda_environment: Literal["practice", "live"] = "practice"
    mt5_server: Optional[str] = None
    mt5_login: Optional[int] = None
    mt5_password: Optional[SecretStr] = None


class RiskSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="RISK_")
    
    max_daily_loss_pct: float = Field(default=2.0, ge=0.1, le=10.0)
    max_position_size_pct: float = Field(default=5.0, ge=0.1, le=100.0)
    max_drawdown_pct: float = Field(default=10.0, ge=1.0, le=50.0)
    var_confidence: float = Field(default=0.95, ge=0.9, le=0.99)
    kill_switch_enabled: bool = True


class MLSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="ML_")
    
    model_path: str = "./models"
    retrain_interval_hours: int = 24
    feature_lookback: int = 100
    prediction_threshold: float = 0.6


class StripeSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="STRIPE_")
    
    secret_key: Optional[SecretStr] = None
    publishable_key: Optional[str] = None
    webhook_secret: Optional[SecretStr] = None


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )
    
    app_name: str = "HOPEFX Trading Platform"
    app_version: str = "3.0.0"
    environment: Literal["development", "staging", "production"] = "development"
    debug: bool = False
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
    
    database: DatabaseSettings = DatabaseSettings()
    redis: RedisSettings = RedisSettings()
    security: SecuritySettings = SecuritySettings()
    broker: BrokerSettings = BrokerSettings()
    risk: RiskSettings = RiskSettings()
    ml: MLSettings = MLSettings()
    stripe: StripeSettings = StripeSettings()
    
    @field_validator("debug", mode="after")
    @classmethod
    def validate_debug(cls, v: bool, info) -> bool:
        if info.data.get("environment") == "production":
            return False
        return v


@lru_cache
def get_settings() -> Settings:
    """Cached settings instance."""
    return Settings()
