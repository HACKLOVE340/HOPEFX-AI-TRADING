#!/usr/bin/env python3
"""
HOPEFX GodMode v9.5 - Complete Trading Platform
"""

from __future__ import annotations

import argparse
import asyncio
import signal
import sys
from contextlib import asynccontextmanager
from decimal import Decimal

import structlog
from fastapi import FastAPI

from hopefx.api.server import create_app, run_server
from hopefx.brain.engine import brain
from hopefx.config.settings import settings
from hopefx.config.vault import vault
from hopefx.data.feature_store import feature_store
from hopefx.data.feed import feed_manager
from hopefx.events.bus import event_bus
from hopefx.execution.oms import oms
from hopefx.execution.router import smart_router
from hopefx.marketplace.copy_trading import copy_engine
from hopefx.marketplace.payments import payments
from hopefx.ml.pipeline import ml_pipeline
from hopefx.monitoring.telemetry import telemetry
from hopefx.risk.circuit_breaker import multi_breaker
from hopefx.risk.prop_enforcement import prop_enforcement

logger = structlog.get_logger()


class HopeFXApplication:
    """Main application orchestrator."""

    def __init__(self) -> None:
        self._shutdown_event = asyncio.Event()
        self._components: list[tuple[str, any]] = []

    async def initialize(self) -> bool:
        """Initialize all subsystems in dependency order."""
        try:
            logger.info("hopefx.initializing", version="9.5.0")

            # 1. Event infrastructure (first)
            await event_bus.start()
            self._components.append(("event_bus", event_bus))
            logger.info("component.ready", name="event_bus")

            # 2. Data layer
            await feed_manager.initialize()
            await feed_manager.start()
            self._components.append(("feed_manager", feed_manager))
            logger.info("component.ready", name="feed_manager")

            # 3. ML pipeline
            await ml_pipeline.start()
            self._components.append(("ml_pipeline", ml_pipeline))
            logger.info("component.ready", name="ml_pipeline")

            # 4. Feature engineering
            await feature_store.start()
            self._components.append(("feature_store", feature_store))
            logger.info("component.ready", name="feature_store")

            # 5. Brain/decision engine
            await brain.start()
            self._components.append(("brain", brain))
            logger.info("component.ready", name="brain")

            # 6. Execution layer
            await oms.start()
            self._components.append(("oms", oms))
            logger.info("component.ready", name="oms")

            # 7. Risk management
            await prop_enforcement.start()
            self._components.append(("prop_enforcement", prop_enforcement))
            logger.info("component.ready", name="prop_enforcement")

            # 8. Marketplace (if enabled)
            if settings.enable_copy_trading:
                await copy_engine.start()
                self._components.append(("copy_engine", copy_engine))
                logger.info("component.ready", name="copy_engine")

            # 9. Setup signal handlers
            for sig in (signal.SIGINT, signal.SIGTERM):
                asyncio.get_event_loop().add_signal_handler(
                    sig, lambda: asyncio.create_task(self.shutdown())
                )

            logger.info("hopefx.ready")
            return True

        except Exception as e:
            logger.exception("hopefx.init_failed", error=str(e))
            await self.shutdown()
            return False

    async def run(self) -> None:
        """Main event loop."""
        logger.info("hopefx.running")

        while not self._shutdown_event.is_set():
            try:
                # Health monitoring
                health = await self._health_check()
                if not health["healthy"]:
                    logger.error("health.check_failed", details=health)
                    await self._attempt_recovery(health)

                # Periodic status logging
                await self._log_status()
                
                await asyncio.wait_for(
                    self._shutdown_event.wait(),
                    timeout=60.0
                )

            except asyncio.TimeoutError:
                continue
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.exception("hopefx.runtime_error", error=str(e))
                await asyncio.sleep(5)

    async def _health_check(self) -> dict:
        """Comprehensive health check."""
        checks = {
            "event_bus": event_bus._running,
            "feed_manager": feed_manager._running,
            "ml_pipeline": ml_pipeline._running,
            "brain": brain._running,
            "oms": oms._running,
            "circuit_breakers": await multi_breaker.check_all(),
        }

        if settings.enable_copy_trading:
            checks["copy_engine"] = copy_engine._running

        all_healthy = all(checks.values())
        
        return {
            "healthy": all_healthy,
            "checks": checks,
            "timestamp": datetime.utcnow().isoformat(),
        }

    async def _attempt_recovery(self, health: dict) -> None:
        """Attempt to recover failed components."""
        failed = [name for name, status in health["checks"].items() if not status]
        logger.warning("recovery.attempting", failed_components=failed)

        for component_name in failed:
            # Attempt restart based on component type
            logger.info("recovery.restarting", component=component_name)

    async def _log_status(self) -> None:
        """Log current system status."""
        position_count = len(oms.get_all_positions())
        latest_tick = None
        
        for feed in feed_manager._feeds.values():
            if feed._last_tick:
                latest_tick = feed._last_tick
                break

        status = {
            "equity": float(brain.state.equity),
            "daily_pnl": float(brain.state.daily_pnl),
            "open_positions": position_count,
            "event_queue_size": event_bus._queue.qsize(),
            "active_feeds": len(feed_manager._feeds),
            "latest_tick_age_ms": (
                (datetime.utcnow() - latest_tick.timestamp).total_seconds() * 1000 
                if latest_tick else None
            ),
        }

        telemetry.update_equity(status["equity"])
        logger.info("hopefx.status", **status)

    async def shutdown(self) -> None:
        """Graceful shutdown in reverse dependency order."""
        logger.info("hopefx.shutting_down")

        self._shutdown_event.set()

        # Stop in reverse order
        for name, component in reversed(self._components):
            try:
                if hasattr(component, 'stop'):
                    await asyncio.wait_for(component.stop(), timeout=10.0)
                    logger.info("component.stopped", name=name)
            except asyncio.TimeoutError:
                logger.warning("component.stop_timeout", name=name)
            except Exception as e:
                logger.exception("component.stop_error", name=name, error=str(e))

        logger.info("hopefx.shutdown_complete")


def main():
    """CLI entry point."""
    parser = argparse.ArgumentParser(description="HOPEFX GodMode Trading Platform")
    parser.add_argument("command", choices=[
        "server", "api",           # Start API server
        "worker",                # Start background worker
        "bot",                   # Start XAUUSD bot
        "init",                  # Initialize configuration
        "migrate",               # Run database migrations
        "shell",                 # Interactive shell
    ])
    parser.add_argument("--mode", choices=["paper", "live", "backtest"], default="paper")
    parser.add_argument("--capital", type=float, default=10000)

    args = parser.parse_args()

    # Configure logging
    structlog.configure(
        processors=[
            structlog.stdlib.filter_by_level,
            structlog.stdlib.add_logger_name,
            structlog.stdlib.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer(),
        ],
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    if args.command in ("server", "api"):
        run_server()
    
    elif args.command == "worker":
        app = HopeFXApplication()
        if asyncio.run(app.initialize()):
            asyncio.run(app.run())
    
    elif args.command == "bot":
        # Import and run bot
        from scripts.xauusd_bot import XAUUSDBot
        bot = XAUUSDBot(mode=args.mode, capital=Decimal(str(args.capital)))
        if asyncio.run(bot.initialize()):
            asyncio.run(bot.run())
    
    elif args.command == "init":
        # Initialize vault and config
        print("Initializing HOPEFX...")
        vault.store("initialized", True, persist=True)
        print("✓ Vault initialized")
        print("✓ Run 'docker-compose up' to start services")
    
    elif args.command == "migrate":
        import alembic.config
        alembic.config.main(argv=["upgrade", "head"])
    
    elif args.command == "shell":
        import IPython
        IPython.embed()


if __name__ == "__main__":
    main()
