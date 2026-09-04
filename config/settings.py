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

    # Connection pool sizing
    # pool_size: number of persistent connections kept open.
    # max_overflow: extra connections allowed above pool_size under load.
    # pool_timeout: seconds to wait for a connection before raising.
    # pool_recycle: seconds before a connection is replaced (prevents stale
    #   connections after DB-side idle timeouts, typically 8 h on RDS/Cloud SQL).
    # pool_pre_ping: issue a lightweight SELECT 1 before handing out a
    #   connection so dead connections are detected and replaced transparently.
    pool_size: int = Field(default=20, ge=1)
    max_overflow: int = Field(default=10, ge=0)
    pool_timeout: float = Field(default=30.0, gt=0)
    pool_recycle: int = Field(default=1800, ge=60)  # 30 min — well under RDS 8 h idle timeout
    pool_pre_ping: bool = True

    # asyncpg connect_args — passed directly to the asyncpg driver.
    # command_timeout: per-query timeout in seconds (None = no limit).
    # server_settings: PostgreSQL session-level GUCs applied at connect time.
    command_timeout: float | None = Field(default=60.0)
    application_name: str = Field(default="hopefx")

    echo: bool = False

    @field_validator("url", mode="before")
    @classmethod
    def decrypt_if_vaulted(cls, v: Any) -> Any:
        if isinstance(v, str) and v.startswith("vault:"):
            return vault.decrypt(v[6:])
        return v

    def asyncpg_connect_args(self) -> dict:
        """Return connect_args dict for create_async_engine().

        Includes command_timeout and server_settings so every connection
        carries the application name (visible in pg_stat_activity) and
        respects the per-query timeout.
        """
        args: dict = {
            "server_settings": {"application_name": self.application_name},
        }
        if self.command_timeout is not None:
            args["command_timeout"] = self.command_timeout
        return args


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

    def build_ssl_context(self):
        """Return an ssl.SSLContext for TLS Redis connections, or None.

        Called by the Redis client factory in database/connection.py and
        cache/redis_client.py.  Returns None when TLS is not required so
        callers can pass ``ssl=settings.redis.build_ssl_context()`` directly
        without branching.

        Behaviour:
        - force_tls=False and URL does not start with rediss:// → None
        - force_tls=True or URL starts with rediss:// → SSLContext
          - tls_skip_verify=True  → CERT_NONE (internal networks only)
          - tls_ca_cert set       → CERT_REQUIRED with custom CA bundle
          - otherwise             → CERT_REQUIRED with system CA store
          - tls_client_cert + tls_client_key set → mutual TLS (mTLS)
        """
        import ssl

        redis_url = self.url.get_secret_value() if hasattr(self.url, "get_secret_value") else str(self.url)
        needs_tls = self.force_tls or redis_url.startswith("rediss://")
        if not needs_tls:
            return None

        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)

        if self.tls_skip_verify:
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
            logger.warning(
                "Redis TLS: certificate verification disabled (REDIS_TLS_SKIP_VERIFY=true). "
                "Only acceptable on private internal networks."
            )
        elif self.tls_ca_cert:
            ctx.load_verify_locations(cafile=self.tls_ca_cert)
        else:
            ctx.load_default_certs()

        if self.tls_client_cert and self.tls_client_key:
            ctx.load_cert_chain(
                certfile=self.tls_client_cert,
                keyfile=self.tls_client_key,
            )
            logger.info("Redis TLS: mTLS client certificate loaded")

        return ctx

    def client_kwargs(self) -> dict:
        """Return kwargs for redis.Redis() / redis.asyncio.Redis() construction.

        Merges connection pool sizing, socket timeouts, health-check interval,
        and TLS ssl_context into a single dict so every Redis client factory
        in the codebase uses identical settings.

        Usage::

            import redis
            from config.settings import get_settings

            r = redis.Redis(**get_settings().redis.client_kwargs())
        """
        redis_url = self.url.get_secret_value() if hasattr(self.url, "get_secret_value") else str(self.url)
        kwargs: dict = {
            "url": redis_url,
            "socket_timeout": self.socket_timeout,
            "socket_connect_timeout": self.socket_connect_timeout,
            "health_check_interval": self.health_check_interval,
            "max_connections": self.max_connections,
            "decode_responses": True,
        }
        ssl_ctx = self.build_ssl_context()
        if ssl_ctx is not None:
            kwargs["ssl"] = True
            kwargs["ssl_context"] = ssl_ctx
        return kwargs


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
                logger.warning("OANDA token read from %s — prefer OANDA_API_KEY (canonical name)", var)
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
                logger.warning("OANDA account ID read from %s — prefer OANDA_ACCOUNT_ID (canonical name)", var)
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
                logger.warning("OANDA environment read from %s — prefer OANDA_ENVIRONMENT (canonical name)", var)
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
    # env_ignore_empty: each sub-settings field below is a nested model, so
    # pydantic-settings looks for an env var of the same name (`DB`, `REDIS`,
    # `BROKER`, `ML`, `RISK`…) and JSON-parses whatever it finds. `.env` ships a
    # bare `BROKER=`, which parsed as the empty string and made the whole
    # Settings object unconstructable with a JSONDecodeError pointing at
    # "broker" — a field nobody had touched. Ignoring empty values makes an
    # unset variable mean unset (F264).
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_ignore_empty=True,
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

    @model_validator(mode="after")
    def fail_fast_production(self) -> Settings:
        """
        Fail-fast validation for production deployments.

        Raises ValueError at startup if any critical secret is missing or
        still set to a placeholder value when env=production.  This prevents
        silent misconfiguration from reaching live traffic.
        """
        if self.env != "production":
            return self

        errors: list[str] = []

        # JWT secret must be set and long enough to be secure
        jwt_secret = (
            self.security.jwt_secret.get_secret_value()
            if hasattr(self.security.jwt_secret, "get_secret_value")
            else str(self.security.jwt_secret or "")
        )
        if len(jwt_secret) < 32:
            errors.append("SECURITY_JWT_SECRET must be at least 32 characters in production")

        # Database URL must point to a real server (not SQLite)
        db_url = str(self.db.url or "")
        if not db_url or "sqlite" in db_url.lower():
            errors.append("DATABASE_URL must be a PostgreSQL URL in production (not SQLite)")

        # Redis URL must be configured
        redis_url = str(self.redis.url or "")
        if not redis_url:
            errors.append("REDIS_URL must be set in production")

        # Redis must use TLS in production
        if redis_url.startswith("redis://") and not redis_url.startswith("redis://localhost"):
            errors.append(
                "REDIS_URL must use rediss:// (TLS) in production; "
                "set REDIS_TLS_SKIP_VERIFY=true only for internal networks"
            )

        if errors:
            raise ValueError(
                "Production configuration errors — fix before deploying:\n" + "\n".join(f"  • {e}" for e in errors)
            )

        return self


@lru_cache
def get_settings() -> Settings:
    """Cached settings instance."""
    return Settings()
