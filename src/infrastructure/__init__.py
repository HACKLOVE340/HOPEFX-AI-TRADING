"""
Infrastructure layer - external services integration.
"""

from src.infrastructure.security import Vault, PasswordHasher, create_jwt_token, decode_jwt_token
from src.infrastructure.database import engine, AsyncSessionLocal, init_db, close_db, get_session, get_db
from src.infrastructure.cache import RedisCache, get_cache, close_cache
from src.infrastructure.monitoring import (
    REGISTRY,
    get_metrics,
    HealthChecker,
    ORDERS_SUBMITTED,
    ORDERS_FILLED,
    POSITIONS_OPEN,
    PNL_REALIZED,
    PNL_UNREALIZED,
    EQUITY,
    DRAWDOWN,
    KILL_SWITCH_ACTIVE,
)

__all__ = [
    "Vault",
    "PasswordHasher",
    "create_jwt_token",
    "decode_jwt_token",
    "engine",
    "AsyncSessionLocal",
    "init_db",
    "close_db",
    "get_session",
    "get_db",
    "RedisCache",
    "get_cache",
    "close_cache",
    "REGISTRY",
    "get_metrics",
    "HealthChecker",
    "ORDERS_SUBMITTED",
    "ORDERS_FILLED",
    "POSITIONS_OPEN",
    "PNL_REALIZED",
    "PNL_UNREALIZED",
    "EQUITY",
    "DRAWDOWN",
    "KILL_SWITCH_ACTIVE",
]
