"""
Main trading engine orchestrating all components.
"""

import asyncio
import signal
from datetime import datetime, timezone
from typing import Any

import anyio

from src.brokers.base import Broker
from src.core.config import settings
from src.core.events import (
    Event,
    KillSwitchTriggered,
    PositionClosed,
    PositionOpened,
    SignalGenerated,
    TickReceived,
    get_event_bus,
)
from src.core.exceptions import TradingError
from src.core.lifecycle import LifecycleManager
from src.core.logging_config import get_logger
from src.data.feeds.base import DataFeed
from src.execution.oms import OrderManagementSystem
from src.risk.kill_switch import KillSwitch
from src.risk.manager import RiskManager
from src.strategies.base import Strategy

logger = get_logger(__name__)


class TradingEngine:
    """
    Production trading engine with full lifecycle management.
    """
    
    def __init__(
        self,
        broker: Broker,
        data_feed: DataFeed,
        strategies: list[Strategy],
        risk_manager: RiskManager | None = None
    ):
        self.broker = broker
        self.data_feed = data_feed
        self.strategies = strategies
        self.risk_manager = risk_manager or RiskManager()
        
        self._oms: OrderManagementSystem | None = None
        self._event_bus = get_event_bus()
        self._kill_switch = KillSwitch()
        self._lifecycle = LifecycleManager()
        
        self._running = False
        self._shutdown_event = asyncio.Event()
    
    async def initialize(self) -> None:
        """Initialize all components."""
        logger.info("Initializing trading engine...")
        
        # Connect to broker
        await self.broker.connect()
        logger.info(f"Connected to {self.broker.broker_type.value}")
        
        # Initialize OMS
        self._oms = OrderManagementSystem(self.broker)
        
        # Initialize risk manager
        await self.risk_manager.initialize()
        
        # Initialize kill switch
        await self._kill_switch.initialize()
        self._kill_switch.register_handler(self._on_kill_switch)
        
        # Initialize strategies
        for strategy in self.strategies:
            await strategy.initialize()
            logger.info(f"Initialized strategy: {strategy.strategy_id}")
        
        # Subscribe to events
        await self._subscribe_events()
        
        # Setup signal handlers
        self._setup_signal_handlers()
        
        self._lifecycle.mark_initialized()
        logger.info("Trading engine initialized")
    
    async def _subscribe_events(self) -> None:
        """Subscribe to domain events."""
        await self._event_bus.start()
        
        # Market data events
        self._event_bus.subscribe(
            TickReceived,
            self._on_tick,
            priority=10
        )
        
        # Signal events
        self._event_bus.subscribe(
            SignalGenerated,
            self._on_signal,
            priority=5
        )
        
        # Position events
        self._event_bus.subscribe(
            PositionOpened,
            self._on_position_opened,
            priority=3
        )
        self._event_bus.subscribe(
            PositionClosed,
            self._on_position_closed,
            priority=3
        )
        
        # Risk events
        self._event_bus.subscribe(
            KillSwitchTriggered,
            self._on_kill_switch_event,
            priority=1
        )
    
    async def _on_tick(self, event: Event[TickReceived]) -> None:
        """Process tick data."""
        tick = event.payload
        
        # Update risk manager
        await self.risk_manager.update_price(tick.symbol, tick.mid)
        
        # Distribute to strategies
        for strategy in self.strategies:
            if strategy.state.value == "ACTIVE":
                try:
                    signal = await strategy.on_market_data(tick)
                    if signal:
                        await self._event_bus.emit(
                            Event.create(
                                SignalGenerated(
                                    strategy_id=signal.strategy_id,
                                    symbol=signal.symbol,
                                    direction=signal.direction.value,
                                    strength=signal.strength,
                                    confidence=signal.confidence
                                ),
                                source=strategy.strategy_id
                            )
                        )
                except Exception as e:
                    logger.error(f"Strategy error in {strategy.strategy_id}: {e}")
    
    async def _on_signal(self, event: Event[SignalGenerated]) -> None:
        """Process trading signal."""
        if self._kill_switch.is_active:
            logger.warning("Signal ignored: kill switch active")
            return
        
        signal = event.payload
        
        # Risk check
        allowed, reason = await self.risk_manager.check_signal(signal)
        if not allowed:
            logger.info(f"Signal rejected by risk manager: {reason}")
            return
        
        # Execute
        if self._oms:
            from src.domain.enums import OrderType, TradeDirection
            from decimal import Decimal
            
            direction = TradeDirection.LONG if signal.direction == "LONG" else TradeDirection.SHORT
            
            try:
                await self._oms.submit_order(
                    symbol=signal.symbol,
                    direction=direction,
                    quantity=Decimal("1.0"),  # Size determined by risk manager
                    order_type=OrderType.MARKET,
                    strategy_id=signal.strategy_id
                )
            except Exception as e:
                logger.error(f"Order execution failed: {e}")
    
    async def _on_position_opened(self, event: Event[PositionOpened]) -> None:
        """Handle position opened."""
        logger.info(f"Position opened: {event.payload.position_id}")
    
    async def _on_position_closed(self, event: Event[PositionClosed]) -> None:
        """Handle position closed."""
        logger.info(f"Position closed: {event.payload.position_id} P&L: {event.payload.realized_pnl}")
    
    def _on_kill_switch(self) -> None:
        """Handle kill switch trigger."""
        logger.critical("Kill switch activated - stopping trading")
        asyncio.create_task(self.emergency_stop())
    
    async def _on_kill_switch_event(self, event: Event[KillSwitchTriggered]) -> None:
        """Handle kill switch event."""
        await self.emergency_stop()
    
    def _setup_signal_handlers(self) -> None:
        """Setup OS signal handlers."""
        for sig in (signal.SIGTERM, signal.SIGINT):
            asyncio.get_event_loop().add_signal_handler(
                sig, lambda: asyncio.create_task(self.shutdown())
            )
    
    async def run(self) -> None:
        """Main trading loop."""
        if not self._lifecycle.is_initialized:
            raise RuntimeError("Engine not initialized")
        
        self._running = True
        
        # Start data feed
        await self.data_feed.start()
        
        # Start strategies
        for strategy in self.strategies:
            await strategy.start()
        
        logger.info("Trading engine running")
        
        # Wait for shutdown
        await self._shutdown_event.wait()
    
    async def shutdown(self) -> None:
        """Graceful shutdown."""
        if not self._running:
            return
        
        logger.info("Initiating shutdown...")
        self._running = False
        
        # Stop strategies
        for strategy in self.strategies:
            await strategy.stop()
        
        # Stop data feed
        await self.data_feed.stop()
        
        # Close positions (configurable)
        # await self._close_all_positions()
        
        # Disconnect broker
        await self.broker.disconnect()
        
        # Stop event bus
        await self._event_bus.stop()
        
        self._shutdown_event.set()
        logger.info("Shutdown complete")
    
    async def emergency_stop(self) -> None:
        """Emergency stop - close everything immediately."""
        logger.critical("EMERGENCY STOP")
        
        # Cancel all pending orders
        if self._oms:
            for order in self._oms.get_open_orders():
                await self._oms.cancel_order(order.id)
        
        # Close all positions
        positions = await self.broker.get_positions()
        for pos in positions:
            # Emit close order
            pass
        
        await self.shutdown()
