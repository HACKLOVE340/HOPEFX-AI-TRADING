# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
Configuration Management System
"""

import base64
import contextlib
import fcntl
import hashlib
import json
import logging
import os
import secrets
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

try:
    from cryptography.fernet import Fernet
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

    CRYPTO_AVAILABLE = True
except ImportError:
    CRYPTO_AVAILABLE = False

logger = logging.getLogger(__name__)


class EncryptionManager:
    """Fernet-based encryption with PBKDF2 key derivation."""

    def __init__(self, master_key: str = ""):
        key = master_key or os.environ.get("CONFIG_ENCRYPTION_KEY", "")
        if not key:
            # Auto-generate an ephemeral key; persist it to .encryption_key in cwd
            # so the same key survives process restarts within the same directory.
            key_file = Path(".encryption_key")
            if key_file.exists():
                key = key_file.read_text(encoding="utf-8").strip()
            else:
                key = secrets.token_hex(32)
                with contextlib.suppress(OSError):
                    key_file.write_text(key, encoding="utf-8")
            logger.warning(
                "CONFIG_ENCRYPTION_KEY not set — using auto-generated key (not for production)",
            )
        self.master_key = key

        salt_hex = os.environ.get("CONFIG_SALT", "")
        if salt_hex:
            try:
                self._salt = bytes.fromhex(salt_hex)
            except ValueError:
                raise ValueError(f"CONFIG_SALT is not valid hex: {salt_hex!r}") from None
        else:
            logger.warning("CONFIG_SALT not set; deriving salt from master key")
            self._salt = hashlib.sha256(key.encode()).digest()[:16]

        if CRYPTO_AVAILABLE:
            kdf = PBKDF2HMAC(
                algorithm=hashes.SHA256(),
                length=32,
                salt=self._salt,
                iterations=100_000,
            )
            derived = base64.urlsafe_b64encode(kdf.derive(key.encode()))
            self._fernet = Fernet(derived)
        else:
            self._fernet = None

    def encrypt(self, data: str) -> str:
        if self._fernet:
            return self._fernet.encrypt(data.encode()).decode()
        return base64.b64encode(data.encode()).decode()

    def decrypt(self, token: str) -> str:
        if self._fernet:
            return self._fernet.decrypt(token.encode()).decode()
        return base64.b64decode(token.encode()).decode()

    def hash_password(self, password: str, salt: bytes | None = None) -> str:
        if salt is None:
            salt = secrets.token_bytes(16)
        dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 100_000)
        return f"{salt.hex()}${dk.hex()}"

    def verify_password(self, password: str, hashed: str) -> bool:
        try:
            salt_hex, dk_hex = hashed.split("$", 1)
        except ValueError:
            return False
        salt = bytes.fromhex(salt_hex)
        dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 100_000)
        return dk.hex() == dk_hex


@dataclass
class APIConfig:
    provider: str = ""
    api_key: str = ""
    api_secret: str = ""
    sandbox_mode: bool = True
    rate_limit: int = 100
    base_url: str = ""
    timeout: int = 30
    max_retries: int = 3

    def validate(self) -> bool:
        return bool(self.provider and self.api_key and self.api_secret)


@dataclass
class DatabaseConfig:
    db_type: str = "sqlite"
    host: str = "localhost"
    port: int = 5432
    username: str = ""
    password: str = ""
    database: str = "hopefx.db"
    ssl_enabled: bool = True
    ssl_mode: str = "prefer"
    connection_pool_size: int = 10
    max_overflow: int = 20
    pool_timeout: int = 30

    def validate(self) -> bool:
        return self.db_type in ("sqlite", "postgresql", "mysql")

    def get_connection_string(self) -> str:
        if self.db_type == "sqlite":
            return f"sqlite:///{self.database}"
        if self.db_type == "postgresql":
            base = f"postgresql://{self.username}:{self.password}@{self.host}:{self.port}/{self.database}"
            if self.ssl_enabled:
                base += f"?sslmode={self.ssl_mode}"
            return base
        if self.db_type == "mysql":
            base = f"mysql+pymysql://{self.username}:{self.password}@{self.host}:{self.port}/{self.database}"
            if self.ssl_enabled:
                base += "?ssl=true"
            return base
        raise ValueError(f"Unsupported db_type: {self.db_type}")


@dataclass
class TradingConfig:
    max_position_size: float = 10000.0
    max_leverage: float = 10.0
    stop_loss_percent: float = 2.0
    take_profit_percent: float = 4.0
    max_open_orders: int = 10
    risk_per_trade: float = 1.0
    daily_loss_limit: float = 5.0
    trading_enabled: bool = False
    paper_trading_mode: bool = True

    def validate(self) -> bool:
        if self.max_position_size <= 0:
            return False
        if self.max_leverage <= 0 or self.max_leverage > 100:
            return False
        return self.risk_per_trade > 0


@dataclass
class LoggingConfig:
    level: str = "INFO"
    log_file: str = "logs/hopefx.log"
    max_file_size_mb: int = 100
    backup_count: int = 10
    format_string: str = "%(asctime)s %(levelname)s %(name)s %(message)s"

    def validate(self) -> bool:
        return self.level in ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL")


@dataclass
class AppConfig:
    app_name: str = "HOPEFX AI Trading"
    version: str = "1.0.0"
    environment: str = "development"
    debug: bool = False
    api_configs: dict[str, APIConfig] = field(default_factory=dict)
    database: DatabaseConfig = field(default_factory=DatabaseConfig)
    trading: TradingConfig = field(default_factory=TradingConfig)
    logging: LoggingConfig = field(default_factory=LoggingConfig)

    def validate(self) -> bool:
        if not self.trading.validate():
            return False
        if not self.logging.validate():
            return False
        return all(cfg.validate() for cfg in self.api_configs.values())

    def copy(self):
        import copy

        return copy.deepcopy(self)

    def to_dict(self) -> dict:
        return {
            "app_name": self.app_name,
            "version": self.version,
            "environment": self.environment,
            "debug": self.debug,
            "api_configs": {k: asdict(v) for k, v in self.api_configs.items()},
            "database": asdict(self.database),
            "trading": asdict(self.trading),
            "logging": asdict(self.logging),
        }

    @classmethod
    def from_dict(cls, d: dict) -> "AppConfig":
        cfg = cls(
            app_name=d.get("app_name", "HOPEFX AI Trading"),
            version=d.get("version", "1.0.0"),
            environment=d.get("environment", "development"),
            debug=d.get("debug", False),
        )
        db_d = d.get("database", {})
        if db_d:
            cfg.database = DatabaseConfig(
                **{k: db_d[k] for k in DatabaseConfig.__dataclass_fields__ if k in db_d},  # pylint: disable=no-member
            )
        tr_d = d.get("trading", {})
        if tr_d:
            cfg.trading = TradingConfig(
                **{k: tr_d[k] for k in TradingConfig.__dataclass_fields__ if k in tr_d},  # pylint: disable=no-member
            )
        lg_d = d.get("logging", {})
        if lg_d:
            cfg.logging = LoggingConfig(
                **{k: lg_d[k] for k in LoggingConfig.__dataclass_fields__ if k in lg_d},  # pylint: disable=no-member
            )
        for name, api_d in d.get("api_configs", {}).items():
            cfg.api_configs[name] = APIConfig(
                **{k: api_d[k] for k in APIConfig.__dataclass_fields__ if k in api_d},  # pylint: disable=no-member
            )
        return cfg


class _Settings:
    """Dynamic settings namespace."""

    def __setattr__(self, name, value):
        object.__setattr__(self, name, value)

    def __getattr__(self, name):
        return None


class ConfigManager:
    """Secure configuration manager with encryption and hash-based change detection."""

    def __init__(
        self,
        config_dir: str = "config",
        encryption_key: str | None = None,
    ):
        self.config_dir = Path(config_dir)
        self.config_dir.mkdir(parents=True, exist_ok=True)

        self._encryption_key = encryption_key or os.environ.get(
            "CONFIG_ENCRYPTION_KEY",
            "",
        )
        self._enc: EncryptionManager | None = None
        if self._encryption_key:
            try:
                self._enc = EncryptionManager(master_key=self._encryption_key)
            except Exception as e:  # pylint: disable=broad-exception-caught
                logger.warning("EncryptionManager init failed: %s", e)

        self.config: AppConfig | None = None
        self._environment: str | None = None
        self._load_timestamp: float | None = None
        self._config_hash: str | None = None
        self.settings = _Settings()  # dynamic attribute bag for test compatibility

    def _config_file(self, environment: str) -> Path:
        return self.config_dir / f"config.{environment}.json"

    def _hash_config(self, cfg: AppConfig) -> str:
        raw = json.dumps(cfg.to_dict(), sort_keys=True)
        return hashlib.sha256(raw.encode()).hexdigest()

    def _encrypt_value(self, value: str) -> str:
        if self._enc and value:
            return self._enc.encrypt(value)
        return value

    def _decrypt_value(self, value: str) -> str:
        if self._enc and value:
            try:
                return self._enc.decrypt(value)
            except Exception:  # pylint: disable=broad-exception-caught
                return value
        return value

    def _default_config(self, environment: str) -> AppConfig:
        cfg = AppConfig(environment=environment)
        cfg.api_configs["binance"] = APIConfig(provider="binance")
        return cfg

    def _write_config(self, cfg: AppConfig, path: Path) -> None:
        d = cfg.to_dict()
        for api_d in d.get("api_configs", {}).values():
            api_d["api_key"] = self._encrypt_value(api_d.get("api_key", ""))
            api_d["api_secret"] = self._encrypt_value(api_d.get("api_secret", ""))
        with open(path, "w", encoding="utf-8") as f:
            try:
                fcntl.flock(f, fcntl.LOCK_EX)
                json.dump(d, f, indent=2)
            finally:
                fcntl.flock(f, fcntl.LOCK_UN)

    def _read_config(self, path: Path) -> AppConfig:
        with open(path, encoding="utf-8") as f:
            try:
                fcntl.flock(f, fcntl.LOCK_SH)
                d = json.load(f)
            finally:
                fcntl.flock(f, fcntl.LOCK_UN)
        for api_d in d.get("api_configs", {}).values():
            api_d["api_key"] = self._decrypt_value(api_d.get("api_key", ""))
            api_d["api_secret"] = self._decrypt_value(api_d.get("api_secret", ""))
        return AppConfig.from_dict(d)

    def load_config(self, environment: str | None = None) -> AppConfig:
        env = environment or os.environ.get("APP_ENV", "development")
        path = self._config_file(env)
        if not path.exists():
            cfg = self._default_config(env)
            self._write_config(cfg, path)
        else:
            cfg = self._read_config(path)
        self.config = cfg
        self._environment = env
        self._load_timestamp = time.time()
        self._config_hash = self._hash_config(cfg)
        return cfg

    def save_config(self, cfg: AppConfig) -> None:
        path = self._config_file(cfg.environment)
        self._write_config(cfg, path)
        if self._environment == cfg.environment:
            self._config_hash = self._hash_config(cfg)

    def reload_config(self) -> AppConfig:
        if self._environment is None:
            raise RuntimeError("No config loaded yet; call load_config() first")
        return self.load_config(self._environment)

    def get_api_config(self, provider: str) -> APIConfig | None:
        if self.config is None:
            raise RuntimeError("Config not loaded; call load_config() first")
        return self.config.api_configs.get(provider)

    def update_api_credential(
        self,
        provider: str,
        api_key: str,
        api_secret: str,
    ) -> None:
        if self.config is None:
            raise RuntimeError("Config not loaded; call load_config() first")
        if provider in self.config.api_configs:
            self.config.api_configs[provider].api_key = api_key
            self.config.api_configs[provider].api_secret = api_secret
        else:
            self.config.api_configs[provider] = APIConfig(
                provider=provider,
                api_key=api_key,
                api_secret=api_secret,
            )

    def is_config_modified(self) -> bool:
        if self.config is None or self._config_hash is None:
            return False
        return self._hash_config(self.config) != self._config_hash

    def get_status(self) -> dict:
        return {
            "loaded": self.config is not None,
            "environment": self._environment,
            "last_load": self._load_timestamp,
            "config_hash": self._config_hash,
            "modified": self.is_config_modified(),
        }

    # Legacy compat
    def _encrypt(self, value: str) -> str:
        return self._encrypt_value(value)

    def _decrypt(self, value: str) -> str:
        return self._decrypt_value(value)


_manager: ConfigManager | None = None


def get_config_manager() -> ConfigManager:
    global _manager  # pylint: disable=global-statement
    if _manager is None:
        _manager = ConfigManager()
    return _manager


def initialize_config(environment: str | None = None) -> AppConfig:
    return get_config_manager().load_config(environment)
