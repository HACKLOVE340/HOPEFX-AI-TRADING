#!/usr/bin/env python3
"""
HOPEFX XAUUSD One-Click Trading Bot
Professional deployment script with automatic configuration.
"""

import argparse
import asyncio
import json
import signal
import sys
from decimal import Decimal
from pathlib import Path

import structlog

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from hopefx.brain.engine import brain
from hopefx.config.settings import settings, Settings
from hopefx.config.vault import vault
from hopefx.data.feed import OandaFeed, FeedConfig, feed_manager
from hopefx.data.feature_store import feature_store
from hopefx.events.bus import event_bus
from hopefx.execution.brokers.oanda import OandaBroker
from hopefx.execution.oms import oms
from hopefx.execution.router import smart_router
from hopefx.ml.pipeline import ml_pipeline
from hopefx.risk.circuit_breaker import multi_breaker
from hopefx.risk.prop_enforcement import prop_enforcement

logger = structlog.get_logger()


class XAUUSDBot:
    """Production-ready XAUUSD automated trading bot."""

    def __init__(self, mode: str = "paper", capital: Decimal = Decimal("10000")):
        self.mode = mode
        self.capital = capital
        self._running = False
        self._shutdown_event = asyncio.Event()

    async def initialize(self) -> bool:
        """Initialize all components."""
        try:
            logger.info("xauusd_bot.initializing", mode=self.mode, capital=float(self.capital))

            # 1. Event Bus
            await event_bus.start()
            logger.info("xauusd_bot.event_bus_ready")

            # 2. Price Feed (OANDA for XAUUSD)
            feed_config = FeedConfig(
                symbol="XAUUSD",
                ws_endpoint="wss://stream-fxpractice.oanda.com" if self.mode == "paper" else "wss://stream-fxtrade.oanda.com",
                api_key=vault.retrieve("oanda_api_key"),
                reconnect_interval=5,
            )
            oanda_feed = OandaFeed(feed_config)
            await feed_manager.initialize()
            feed_manager.add_feed(oanda_feed, primary=True)
            await feed_manager.start()
            logger.info("xauusd_bot.feed_ready")

            # 3. ML Pipeline
            await ml_pipeline.start()
            logger.info("xauusd_bot.ml_ready")

            # 4. Feature Store
            await feature_store.start()
            logger.info("xauusd_bot.features_ready")

            # 5. Brain Engine
            await brain.start()
            brain.state.cash = self.capital
            brain.state.equity = self.capital
            logger.info("xauusd_bot.brain_ready")

            # 6. Broker & Router
            broker = OandaBroker(
                account_id=vault.retrieve("oanda_account_id"),
                paper=(self.mode == "paper")
            )
            await broker.connect()
            smart_router.register_broker("oanda", broker)
            logger.info("xauusd_bot.broker_ready", connected=broker.connected)

            # 7. OMS
            await oms.start()
            logger.info("xauusd_bot.oms_ready")

            # 8. Risk Systems
            await prop_enforcement.start()
            logger.info("xauusd_bot.risk_ready")

            # 9. Setup signal handlers
            for sig in (signal.SIGINT, signal.SIGTERM):
                asyncio.get_event_loop().add_signal_handler(
                    sig, lambda: asyncio.create_task(self.shutdown())
                )

            self._running = True
            logger.info("xauusd_bot.initialized")
            return True

        except Exception as e:
            logger.exception("xauusd_bot.init_failed", error=str(e))
            return False

    async def run(self) -> None:
        """Main trading loop."""
        logger.info("xauusd_bot.running")

        while self._running and not self._shutdown_event.is_set():
            try:
                # Health check
                if not await self._health_check():
                    logger.error("xauusd_bot.health_check_failed")
                    await self._emergency_stop()
                    break

                # Log status every 60 seconds
                await self._log_status()
                await asyncio.sleep(60)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.exception("xauusd_bot.loop_error", error=str(e))
                await asyncio.sleep(5)

    async def _health_check(self) -> bool:
        """System health verification."""
        checks = [
            event_bus._running,
            feed_manager._running,
            ml_pipeline._running,
            brain._running,
            oms._running,
            await multi_breaker.check_all(),
        ]
        return all(checks)

    async def _log_status(self) -> None:
        """Log current trading status."""
        position = oms.get_position("XAUUSD")
        latest_features = feature_store.get_latest_features("XAUUSD")

        status = {
            "equity": float(brain.state.equity),
            "daily_pnl": float(brain.state.daily_pnl),
            "open_position": position is not None,
            "position_side": position.get("side") if position else None,
            "position_qty": float(position.get("qty", 0)) if position else 0,
            "feature_count": len(latest_features.features) if latest_features else 0,
            "buffer_health": len(feature_store._buffers.get("XAUUSD", [])),
        }

        logger.info("xauusd_bot.status", **status)

    async def _emergency_stop(self) -> None:
        """Emergency stop all trading."""
        logger.error("xauusd_bot.emergency_stop")

        # Close all positions
        position = oms.get_position("XAUUSD")
        if position:
            # Submit closing order
            pass

        # Stop all components
        await oms.stop()
        await brain.stop()
        await feed_manager.stop()
        await event_bus.stop()

    async def shutdown(self) -> None:
        """Graceful shutdown."""
        logger.info("xauusd_bot.shutting_down")
        self._running = False
        self._shutdown_event.set()

        # Close positions if configured
        if self.mode == "live":
            await self._emergency_stop()
        else:
            await oms.stop()
            await brain.stop()
            await feed_manager.stop()
            await event_bus.stop()

        logger.info("xauusd_bot.shutdown_complete")
        sys.exit(0)


def create_default_config() -> dict:
    """Create default bot configuration."""
    return {
        "symbol": "XAUUSD",
        "timeframe": "1m",
        "max_spread": 0.05,
        "risk_per_trade": 0.01,
        "max_daily_trades": 10,
        "trading_hours": {
            "start": "06:00",
            "end": "22:00",
            "timezone": "America/New_York"
        },
        "ml_config": {
            "confidence_threshold": 0.65,
            "min_prediction_edge": 0.1,
            "feature_window": 100,
        },
        "risk_limits": {
            "max_daily_loss_pct": 0.02,
            "max_position_risk_pct": 0.01,
            "max_drawdown_pct": 0.05,
        },
        "prop_challenge": {
            "enabled": False,
            "firm": "ftmo",
            "account_size": 100000,
        }
    }


def main():
    parser = argparse.ArgumentParser(description="HOPEFX XAUUSD Trading Bot")
    parser.add_argument("--mode", choices=["paper", "live", "backtest"], default="paper")
    parser.add_argument("--capital", type=float, default=10000)
    parser.add_argument("--config", type=str, help="Path to config JSON")
    parser.add_argument("--init", action="store_true", help="Initialize config file")

    args = parser.parse_args()

    if args.init:
        config_path = args.config or "xauusd_config.json"
        with open(config_path, "w") as f:
            json.dump(create_default_config(), f, indent=2)
        print(f"Created default config: {config_path}")
        return

    # Load config
    config = create_default_config()
    if args.config:
        with open(args.config) as f:
            config.update(json.load(f))

    # Setup logging
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

    # Run bot
    bot = XAUUSDBot(mode=args.mode, capital=Decimal(str(args.capital)))

    try:
        if asyncio.run(bot.initialize()):
            asyncio.run(bot.run())
        else:
            print("Failed to initialize bot")
            sys.exit(1)
    except KeyboardInterrupt:
        print("\nShutdown requested")
        asyncio.run(bot.shutdown())


if __name__ == "__main__":
    main()
