#!/usr/bin/env python3
"""
HOPEFX Trading System Entry Point
"""
import asyncio
import signal
import sys
from contextlib import AsyncExitStack

import structlog

from hopefx.config.settings import settings
from hopefx.core.events import get_event_bus
from hopefx.data.feeds.oanda import OandaFeed
from hopefx.execution.oms import OrderManager
from hopefx.risk.manager import RiskManager

logger = structlog.get_logger()


class TradingSystem:
    """Main trading system orchestrator."""
    
    def __init__(self):
        self._shutdown_event = asyncio.Event()
        self._components = []
    
    async def run(self):
        """Main async entry point."""
        # Setup signal handlers
        for sig in (signal.SIGTERM, signal.SIGINT):
            asyncio.get_event_loop().add_signal_handler(
                sig, lambda: self._shutdown_event.set()
            )
        
        async with AsyncExitStack() as stack:
            # Initialize components
            event_bus = await stack.enter_async_context(
                await get_event_bus()
            )
            
            risk_manager = await stack.enter_async_context(
                RiskManager()
            )
            
            oms = await stack.enter_async_context(
                OrderManager()
            )
            
            feed = OandaFeed()
            await feed.connect()
            
            logger.info("system_ready")
            
            # Wait for shutdown signal
            await self._shutdown_event.wait()
            
            logger.info("system_shutting_down")
        
        logger.info("system_stopped")


def main():
    """CLI entry point."""
    asyncio.run(TradingSystem().run())


if __name__ == "__main__":
    main()
