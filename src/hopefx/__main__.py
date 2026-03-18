# src/hopefx/__main__.py
"""
HOPEFX Trading System - Secure Async Entry Point
"""
from __future__ import annotations

import asyncio
import signal
import sys
from contextlib import AsyncExitStack, suppress

import anyio
import structlog

from pydantic import SecretStr
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

logger = structlog.get_logger()


class SecureTradingSystem:
    """
    Production trading system with:
    - Graceful shutdown on SIGTERM/SIGINT
    - Distributed kill switch support
    - Structured resource cleanup
    - Health check integration
    """
    
    def __init__(self):
        self.settings = get_settings()
        self._shutdown_event = asyncio.Event()
        self._components: dict[str, Any] = {}
        self._vault: VaultSecretProvider | None = None
        self._kill_switch: DistributedKillSwitch | None = None
        self._metrics: MetricsExporter | None = None
    
    async def _setup_signal_handlers(self) -> None:
        """Setup graceful shutdown handlers."""
        loop = asyncio.get_event_loop()
        
        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(sig, self._request_shutdown)
        
        logger.debug("signal_handlers_registered")
    
    def _request_shutdown(self) -> None:
        """Request graceful shutdown."""
        logger.info("shutdown_requested")
        self._shutdown_event.set()
    
    async def _initialize_vault(self) -> None:
        """Initialize Vault for secret management."""
        if self.settings.vault.enabled:
            self._vault = VaultSecretProvider(self.settings.vault)
            await self._vault.initialize()
            
            # Override secrets with Vault values if available
            db_password = await self._vault.get_secret("database/password")
            if db_password:
                self.settings.database.password = SecretStr(db_password)
    
    async def _initialize_kill_switch(self) -> None:
        """Initialize distributed kill switch."""
        self._kill_switch = DistributedKillSwitch()
        await self._kill_switch.initialize()
        
        # Register kill listener
        self._kill_switch.add_listener(self._on_kill_signal)
    
    def _on_kill_signal(self, state) -> None:
        """Handle kill switch trigger."""
        logger.critical(
            "kill_switch_activated",
            reason=state.reason,
            scope=state.scope
        )
        self._request_shutdown()
    
    async def _initialize_metrics(self) -> None:
        """Initialize observability."""
        self._metrics = get_metrics_exporter()
        self._metrics.health.set_ready("system", True)
    
    async def run(self) -> int:
        """
        Main async entry point with structured initialization.
        
        Returns:
            Exit code (0 for success, 1 for error)
        """
        try:
            await self._setup_signal_handlers()
            
            async with AsyncExitStack() as stack:
                # 1. Initialize Vault (if enabled)
                await self._initialize_vault()
                
                # 2. Initialize database
                await init_db()
                stack.push_async_callback(close_db)
                
                # 3. Initialize Redis
                redis_pool = await get_redis_pool()
                stack.push_async_callback(close_redis)
                
                # 4. Initialize event bus
                event_bus = await get_event_bus()
                await event_bus.start()
                stack.push_async_callback(event_bus.stop)
                
                # 5. Initialize kill switch
                await self._initialize_kill_switch()
                stack.push_async_callback(self._kill_switch.close)
                
                # 6. Initialize metrics
                await self._initialize_metrics()
                
                # 7. Initialize trading components
                risk_manager = RiskManager()
                await risk_manager.initialize()
                
                oms = OrderManager()
                await oms.initialize()
                
                router = SmartRouter(oms)
                
                # 8. Connect to market data
                feed = OandaFeed()
                if await feed.connect():
                    await feed.subscribe(["XAUUSD"])
                
                logger.info(
                    "system_ready",
                    environment=self.settings.environment.value,
                    paper_trading=self.settings.trading.paper_trading
                )
                
                # 9. Main loop - wait for shutdown
                await self._shutdown_event.wait()
                
                logger.info("shutdown_initiated")
                
                # 10. Graceful cleanup happens via AsyncExitStack
                
        except Exception as e:
            logger.critical("system_fatal_error", error=str(e), exc_info=True)
            return 1
        
        logger.info("system_stopped_gracefully")
        return 0


def main() -> int:
    """CLI entry point."""
    # Configure structlog before anything else
    structlog.configure(
        processors=[
            structlog.stdlib.filter_by_level,
            structlog.stdlib.add_logger_name,
            structlog.stdlib.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer()
        ],
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )
    
    # Run async main
    return asyncio.run(SecureTradingSystem().run())


if __name__ == "__main__":
    sys.exit(main())
