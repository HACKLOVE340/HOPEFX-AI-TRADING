"""
Emergency kill switch with circuit breaker pattern.
"""

import asyncio
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Callable

from src.core.events import Event, EventBus, KillSwitchTriggered, get_event_bus
from src.core.logging_config import get_logger

logger = get_logger(__name__)


class KillSwitchState(Enum):
    ARMED = "armed"
    TRIGGERED = "triggered"
    RESET = "reset"


class KillSwitch:
    """
    Emergency stop mechanism with automatic and manual triggers.
    """
    
    def __init__(
        self,
        auto_triggers: dict[str, float] | None = None,
        cooldown_minutes: int = 15
    ):
        self.state = KillSwitchState.ARMED
        self.auto_triggers = auto_triggers or {
            "max_drawdown": 0.10,
            "daily_loss": 0.05,
            "consecutive_losses": 5,
            "latency_spike_ms": 5000
        }
        self.cooldown = timedelta(minutes=cooldown_minutes)
        self._triggered_at: datetime | None = None
        self._event_bus: EventBus | None = None
        self._handlers: list[Callable] = []
    
    async def initialize(self) -> None:
        """Initialize event bus connection."""
        self._event_bus = get_event_bus()
    
    def register_handler(self, handler: Callable[[], None]) -> None:
        """Register callback for kill switch trigger."""
        self._handlers.append(handler)
    
    def check_conditions(
        self,
        current_drawdown: float,
        daily_pnl: float,
        consecutive_losses: int,
        latency_ms: float
    ) -> bool:
        """
        Check if any kill conditions are met.
        """
        if self.state == KillSwitchState.TRIGGERED:
            # Check cooldown
            if self._triggered_at and datetime.now(timezone.utc) - self._triggered_at < self.cooldown:
                return True  # Still active
            else:
                self.state = KillSwitchState.RESET
                logger.info("Kill switch cooldown expired, resetting")
                return False
        
        triggers = []
        
        if current_drawdown >= self.auto_triggers["max_drawdown"]:
            triggers.append(f"Max drawdown: {current_drawdown:.2%}")
        
        if daily_pnl <= -self.auto_triggers["daily_loss"]:
            triggers.append(f"Daily loss: {daily_pnl:.2%}")
        
        if consecutive_losses >= self.auto_triggers["consecutive_losses"]:
            triggers.append(f"Consecutive losses: {consecutive_losses}")
        
        if latency_ms >= self.auto_triggers["latency_spike_ms"]:
            triggers.append(f"Latency spike: {latency_ms}ms")
        
        if triggers:
            self.trigger(f"Auto-triggers: {', '.join(triggers)}")
            return True
        
        return False
    
    def trigger(self, reason: str) -> None:
        """Manually trigger kill switch."""
        if self.state == KillSwitchState.TRIGGERED:
            return
        
        self.state = KillSwitchState.TRIGGERED
        self._triggered_at = datetime.now(timezone.utc)
        
        logger.critical(f"KILL SWITCH TRIGGERED: {reason}")
        
        # Emit event
        if self._event_bus:
            asyncio.create_task(self._event_bus.emit(
                Event.create(
                    KillSwitchTriggered(
                        reason=reason,
                        triggered_at=self._triggered_at
                    ),
                    source="kill_switch",
                    priority=1  # Highest priority
                )
            ))
        
        # Execute handlers
        for handler in self._handlers:
            try:
                handler()
            except Exception as e:
                logger.error(f"Kill switch handler error: {e}")
    
    def reset(self, manual: bool = False) -> bool:
        """
        Reset kill switch after cooldown or manual override.
        """
        if not manual and self._triggered_at:
            if datetime.now(timezone.utc) - self._triggered_at < self.cooldown:
                logger.warning("Cannot reset kill switch during cooldown")
                return False
        
        self.state = KillSwitchState.ARMED
        self._triggered_at = None
        logger.info("Kill switch reset")
        return True
    
    @property
    def is_active(self) -> bool:
        """Check if kill switch is currently active."""
        return self.state == KillSwitchState.TRIGGERED
