from __future__ import annotations

import os
import secrets
from enum import Enum
from functools import lru_cache
from pathlib import Path
from typing import Literal, Optional

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Environment(str, Enum):
    DEVELOPMENT = "development"
    STAGING = "staging"
    PRODUCTION = "production"


class TradingMode(str, Enum):
    PAPER = "paper"
    LIVE = "live"
    BACKTEST = "backtest"


class LogLevel(str, Enum):
    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # Core
    app_name: str = "HOPEFX-GODMODE"
    environment: Environment = Environment.DEVELOPMENT
    log_level: LogLevel = LogLevel.INFO
    debug: bool = Field(default=False)

    # Security
    encryption_key: str = Field(default_factory=lambda: secrets.token_hex(32))
    jwt_secret: str = Field(default_factory=lambda: secrets.token_urlsafe(32))
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 30
    refresh_token_expire_days: int = 7
    argon2_time_cost: int = 3
    argon2_memory_cost: int = 65536
    argon2_parallelism: int = 4
    
    # Cloud Secrets
    secrets_provider: str = "local"  # local, aws, azure, gcp, hashicorp
    aws_region: str = "us-east-1"
    azure_keyvault_url: Optional[str] = None
    gcp_project_id: Optional[str] = None
    vault_url: Optional[str] = None
    vault_token: Optional[str] = None
    vault_mount_point: str = "secret"

    # Database
    database_url: str = "postgresql+asyncpg://hopefx:hopefx@localhost:5432/hopefx"
    redis_url: str = "redis://localhost:6379/0"
    redis_max_connections: int = 50

    # Trading
    trading_mode: TradingMode = TradingMode.PAPER
    default_broker: str = "oanda"
    max_open_positions: int = 5
    max_daily_loss_pct: float = 0.02
    max_position_risk_pct: float = 0.01
    default_leverage: float = 30.0

    # XAUUSD Specific
    xauusd_spread_threshold: float = 0.05
    xauusd_min_volume: float = 0.01
    xauusd_max_slippage: float = 0.02

    # ML
    model_registry_path: Path = Path("./models")
    feature_window: int = 100
    prediction_horizon: int = 5
    retrain_interval_minutes: int = 60
    drift_threshold: float = 0.05
    enable_model_quantization: bool = True
    enable_onnx_export: bool = True

    # Risk
    var_confidence: float = 0.95
    var_window: int = 252
    circuit_breaker_threshold: int = 3
    circuit_breaker_timeout: int = 300

    # API
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    api_workers: int = 4
    ws_heartbeat_interval: int = 30
    
    # Rate Limiting
    rate_limit_requests_per_minute: int = 100
    rate_limit_burst: int = 20
    enable_geo_blocking: bool = False
    blocked_countries: list = Field(default_factory=list)

    # Monitoring
    prometheus_port: int = 9090
    health_check_interval: int = 30
    enable_distributed_tracing: bool = True
    jaeger_endpoint: Optional[str] = None
    
    # Compliance
    enable_auto_compliance_reporting: bool = True
    mifid_firm_id: Optional[str] = None
    arm_endpoint: Optional[str] = None
    emir_trade_repository: Optional[str] = None

    @field_validator("encryption_key")
    @classmethod
    def validate_encryption_key(cls, v: str) -> str:
        if len(v) < 32:
            raise ValueError("Encryption key must be at least 32 characters")
        return v

    @property
    def is_production(self) -> bool:
        return self.environment == Environment.PRODUCTION

    @property
    def async_database_url(self) -> str:
        return self.database_url.replace("postgresql://", "postgresql+asyncpg://")


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
