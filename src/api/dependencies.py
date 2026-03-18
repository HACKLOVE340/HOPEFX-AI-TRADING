"""
FastAPI dependency injection container with lifecycle management.
"""

from contextlib import asynccontextmanager
from typing import AsyncGenerator, Annotated

from fastapi import Depends, Request

from src.brokers.base import Broker
from src.brokers.paper import PaperBroker
from src.core.config import settings
from src.execution.oms import OrderManagementSystem
from src.infrastructure.cache import get_cache, RedisCache
from src.infrastructure.database import get_db, AsyncSession
from src.risk.manager import RiskManager


class DependencyContainer:
    """
    Singleton dependency container with connection pooling.
    """
    
    def __init__(self):
        self._broker: Broker | None = None
        self._oms: OrderManagementSystem | None = None
        self._risk_manager: RiskManager | None = None
        self._initialized = False
    
    async def initialize(self) -> None:
        """Initialize all dependencies."""
        if self._initialized:
            return
        
        # Initialize broker
        if settings.trading_mode == "paper":
            self._broker = PaperBroker(initial_balance=settings.initial_capital)
        elif settings.broker.default_broker == "oanda":
            from src.brokers.oanda import OandaBroker
            self._broker = OandaBroker()
        
        await self._broker.connect()
        
        # Initialize OMS
        self._oms = OrderManagementSystem(self._broker)
        
        # Initialize risk manager
        self._risk_manager = RiskManager()
        await self._risk_manager.initialize()
        
        self._initialized = True
    
    async def shutdown(self) -> None:
        """Cleanup resources."""
        if self._broker:
            await self._broker.disconnect()
        self._initialized = False
    
    def get_broker(self) -> Broker:
        """Get broker instance."""
        if not self._broker:
            raise RuntimeError("Container not initialized")
        return self._broker
    
    def get_oms(self) -> OrderManagementSystem:
        """Get OMS instance."""
        if not self._oms:
            raise RuntimeError("Container not initialized")
        return self._oms
    
    def get_risk_manager(self) -> RiskManager:
        """Get risk manager instance."""
        if not self._risk_manager:
            raise RuntimeError("Container not initialized")
        return self._risk_manager


# Global container instance
_container = DependencyContainer()


async def get_container() -> DependencyContainer:
    """Get initialized container."""
    if not _container._initialized:
        await _container.initialize()
    return _container


async def get_oms() -> OrderManagementSystem:
    """FastAPI dependency for OMS."""
    container = await get_container()
    return container.get_oms()


async def get_risk_mgr() -> RiskManager:
    """FastAPI dependency for risk manager."""
    container = await get_container()
    return container.get_risk_manager()


async def get_redis() -> RedisCache:
    """FastAPI dependency for Redis."""
    return await get_cache()


# Annotated dependencies for type safety
OMSDep = Annotated[OrderManagementSystem, Depends(get_oms)]
RiskDep = Annotated[RiskManager, Depends(get_risk_mgr)]
RedisDep = Annotated[RedisCache, Depends(get_redis)]
DBDep = Annotated[AsyncSession, Depends(get_db)]
