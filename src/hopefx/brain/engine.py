import asyncio
from decimal import Decimal

import structlog

from hopefx.core.bus import EventBus, EventType
from hopefx.core.events import OrderEvent, SignalEvent
from hopefx.risk.sizing import PositionSizer

logger = structlog.get_logger()


class BrainEngine:
    """Signal → Decision → Risk Gate → Order."""
    
    def __init__(
        self, 
        bus: EventBus,
        position_sizer: PositionSizer,
        max_daily_signals: int = 10
    ) -> None:
        self.bus = bus
        self.sizer = position_sizer
        self.max_daily_signals = max_daily_signals
        self._daily_count = 0
        self._last_reset = asyncio.get_event_loop().time()
        
        # Subscribe to signals
        self.bus.subscribe(EventType.SIGNAL, self._on_signal)
    
    async def _on_signal(self, event: SignalEvent) -> None:
        """Process signal through risk gate."""
        # Rate limit check
        now = asyncio.get_event_loop().time()
        if now - self._last_reset > 86400:  # 24h
            self._daily_count = 0
            self._last_reset = now
        
        if self._daily_count >= self.max_daily_signals:
            logger.warning("brain.daily_limit_reached")
            return
        
        if event.direction == "flat":
            return
        
        # Risk check
        size = self.sizer.calculate(
            symbol=event.symbol,
            confidence=event.confidence,
            atr=event.features.get("atr_14", 0.0)
        )
        
        if size <= 0:
            logger.info("brain.risk_rejected", signal=event)
            return
        
        # Create order
        order = OrderEvent(
            order_id=f"ord_{asyncio.get_event_loop().time()}",
            symbol=event.symbol,
            side="buy" if event.direction == "long" else "sell",
            quantity=Decimal(str(size)),
            order_type="market",
            timestamp=event.timestamp
        )
        
        await self.bus.publish(EventType.ORDER, order)
        self._daily_count += 1
        
        logger.info("brain.order_issued", 
                   order_id=order.order_id,
                   side=order.side,
                   size=float(size),
                   confidence=event.confidence)
