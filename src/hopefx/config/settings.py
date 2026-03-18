"""
HOPEFX Trading System - Secure Async Entry Point
"""
from __future__ import annotations

import asyncio
import signal
import sys
from contextlib import AsyncExitStack, suppress
from typing import Any  # ✅ ADDED

import anyio
import structlog
from pydantic import SecretStr  # ✅ ADDED

from hopefx.config.settings import get_settings, VaultSecretProvider
from hopefx.core.events import get_event_bus, EventBus
from hopefx.core.distributed_kill_switch import DistributedKillSwitch
from hopefx.data.feeds.oanda import OandaFeed
from hopefx.execution.oms import OrderManager
from hopefx.execution.router import SmartRouter
from hopefx.risk.manager import RiskManager
from hopefx.infrastructure.database import init_db, close_db
from hopefx.infrastructure.redis import get_redis_pool, close_redis
from hopefx.infrastructure.monitoring import get_metrics_exporter, MetricsExporter

        return self

class SecurityConfig(BaseSettings):
    """
    Security hardening with cryptographic validation.
    ZERO hardcoded defaults - all must come from environment/Vault.
    """
    model_config = SettingsConfigDict(env_prefix="SECURITY_")
    
    secret_key: SecretStr = Field(
        ...,  # REQUIRED - no default!
        min_length=32,
        description="Application secret key (32+ chars, random)"
    )
    algorithm: Literal["HS256", "HS384", "HS512"] = "HS256"
    access_token_expire_minutes: int = Field(default=30, ge=5, le=1440)
    refresh_token_expire_days: int = Field(default=7, ge=1, le=90)
    
    # Argon2id parameters (OWASP recommended)
    argon2_time_cost: int = Field(default=3, ge=2, le=10)
    argon2_memory_cost: int = Field(default=65536, ge=1024, le=1048576)
    argon2_parallelism: int = Field(default=4, ge=1, le=16)
    
    # Rate limiting
    rate_limit_requests: int = Field(default=100, ge=10, le=10000)
    rate_limit_window: int = Field(default=60, ge=1, le=3600)
    
    # CORS (strict defaults)
    cors_origins: list[str] = Field(default_factory=list)
    allowed_hosts: list[str] = Field(default_factory=list)
    
    # Encryption
    encryption_key: SecretStr | None = Field(
        default=None,
        description="Fernet encryption key (32 bytes base64)"
    )
    
    @field_validator("secret_key", mode="after")
    @classmethod
    def validate_no_default_key(cls, v: SecretStr) -> SecretStr:
        """Ensure no development/test keys in production."""
        secret = v.get_secret_value().lower()
        forbidden_patterns = [
            "dev", "test", "example", "sample", "default",
            "password", "secret", "key", "123", "abc", "xyz"
        ]
        
        for pattern in forbidden_patterns:
            if pattern in secret and len(pattern) > 2:
                raise ValueError(
                    f"Secret key contains forbidden pattern: '{pattern}'. "
                    "Generate with: openssl rand -hex 32"
                )
        return v
    
    @field_validator("cors_origins", mode="after")
    @classmethod
    def validate_cors_origins(cls, v: list[str]) -> list[str]:
        """Validate CORS origins."""
        for origin in v:
            if origin == "*":
                raise ValueError(
                    "CORS origin '*' is not allowed in production. "
                    "Specify explicit origins."
                )
            if not origin.startswith(("https://", "http://localhost")):
                raise ValueError(f"Invalid CORS origin: {origin}")
        return v
    
    @field_validator("encryption_key", mode="after")
    @classmethod
    def validate_encryption_key(cls, v: SecretStr | None) -> SecretStr | None:
        """Validate Fernet key format."""
        if v is None:
            return v
        
        key = v.get_secret_value()
        # Fernet keys are 32 bytes, base64 encoded = 44 chars
        if len(key) != 44:
            raise ValueError(
                "Encryption key must be 32 bytes base64 encoded (44 chars). "
                "Generate with: python -c \"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\""
            )
        return v


class TradingConfig(BaseSettings):
    """Trading parameters with safety limits."""
    model_config = SettingsConfigDict(env_prefix="TRADING_")
    
    default_symbol: str = "XAUUSD"
    default_timeframe: str = "M5"
    max_position_size: float = Field(default=100.0, gt=0, le=1000)
    max_daily_loss_pct: float = Field(default=2.0, gt=0, le=10)
    max_drawdown_pct: float = Field(default=5.0, gt=0, le=20)
    risk_per_trade_pct: float = Field(default=1.0, gt=0, le=5)
    paper_trading: bool = True
    slippage_model: Literal["fixed", "volatility", "none"] = "volatility"
    
    @model_validator(mode="after")
    def validate_risk_limits(self) -> Self:
        """Ensure risk limits are sane."""
        if self.risk_per_trade_pct > self.max_daily_loss_pct:
            raise ValueError("risk_per_trade_pct cannot exceed max_daily_loss_pct")
        if self.max_daily_loss_pct > self.max_drawdown_pct:
            raise ValueError("max_daily_loss_pct cannot exceed max_drawdown_pct")
        return self


class MLConfig(BaseSettings):
    """Machine learning configuration."""
    model_config = SettingsConfigDict(env_prefix="ML_")
    
    model_registry_path: Path = Path("./models")
    feature_lookback: int = Field(default=100, ge=10, le=1000)
    prediction_horizon: int = Field(default=5, ge=1, le=100)
    retrain_interval_hours: int = Field(default=24, ge=1, le=168)
    confidence_threshold: float = Field(default=0.65, ge=0.5, le=0.99)
    drift_threshold: float = Field(default=0.05, ge=0.01, le=0.5)
    device: Literal["cpu", "cuda", "mps"] = "cpu"


class BrokerConfig(BaseSettings):
    """Broker credentials - ALL from environment, no defaults."""
    model_config = SettingsConfigDict(env_prefix="BROKER_")
    
    # OANDA
    oanda_api_key: SecretStr | None = Field(default=None, repr=False)
    oanda_account_id: str = ""
    oanda_environment: Literal["practice", "live"] = "practice"
    
    # MT5
    mt5_server: str = ""
    mt5_login: int = 0
    mt5_password: SecretStr | None = Field(default=None, repr=False)
    
    # Interactive Brokers
    ib_host: str = "127.0.0.1"
    ib_port: int = Field(default=7497, ge=1, le=65535)
    ib_client_id: int = 1


class Settings(BaseSettings):
    """
    Root configuration with Vault integration.
    """
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="forbid",  # Strict - no extra fields allowed
    )
    
    app_name: str = "HOPEFX v6.0"
    version: str = "6.0.0"
    environment: Environment = Environment.DEVELOPMENT
    debug: bool = False
    log_level: str = "INFO"
    
    # Sub-configs
    vault: VaultConfig = Field(default_factory=VaultConfig)
    database: DatabaseConfig = Field(...)
    redis: RedisConfig = Field(...)
    security: SecurityConfig = Field(...)
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
                if os.getenv("LIVE_TRADING_CONFIRMED") != "I_UNDERSTAND_RISKS":
                    raise ValueError(
                        "Live trading requires LIVE_TRADING_CONFIRMED=I_UNDERSTAND_RISKS"
                    )
            
            # Production security checks
            if not self.vault.enabled:
                logger.warning("Vault not enabled in production - secrets in environment")
            
            if self.security.encryption_key is None:
                raise ValueError("Encryption key required in production")
        
        return self
    
    @property
    def is_production(self) -> bool:
        return self.environment == Environment.PRODUCTION
    
    @property
    def is_testing(self) -> bool:
        return self.environment == Environment.TESTING


class VaultSecretProvider:
    """
    HashiCorp Vault secret provider for dynamic secret retrieval.
    """
    
    def __init__(self, config: VaultConfig):
        self.config = config
        self._client = None
    
    async def initialize(self):
        """Initialize Vault client."""
        if not self.config.enabled:
            return
        
        import hvac
        
        self._client = hvac.AsyncClient(
            url=self.config.addr,
            token=self.config.token.get_secret_value(),
            verify=self.config.verify_ssl
        )
        
        # Verify connection
        await self._client.sys.read_health()
        logger.info("vault_connected", addr=self.config.addr)
    
    async def get_secret(self, key: str) -> str | None:
        """Retrieve secret from Vault."""
        if not self._client:
            return None
        
        try:
            response = await self._client.secrets.kv.v2.read_secret_version(
                path=f"{self.config.path}/{key}",
                mount_point=self.config.mount_point
            )
            return response["data"]["data"].get("value")
        except Exception as e:
            logger.error("vault_read_error", key=key, error=str(e))
            return None
    
    async def close(self):
        """Cleanup."""
        if self._client:
            await self._client.close()


@lru_cache
def get_settings() -> Settings:
    """Cached settings singleton with validation."""
    try:
        return Settings()
    except Exception as e:
        logger.error("settings_validation_failed", error=str(e))
        raise RuntimeError(f"Configuration error: {e}") from e


# Export for convenience
settings = get_settings()
