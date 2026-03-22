"""
Global kill switch using Redis for distributed systems.
"""
from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from datetime import datetime
from typing import Callable

import aioredis
import structlog

from hopefx.config.settings import settings

logger = structlog.get_logger()


@dataclass
class KillSwitchState:
    """Kill switch state with metadata."""
    triggered: bool
    reason: str
    triggered_by: str
    triggered_at: datetime
    scope: str  # "global", "symbol:XAUUSD", "strategy:abc"


class DistributedKillSwitch:
    """
    Redis-backed kill switch for multi-instance deployments.
    All instances subscribe to kill events.
    """
    
    CHANNEL = "hopefx:kill_switch"
    
    def __init__(self):
        self._redis: aioredis.Redis | None = None
        self._pubsub: aioredis.client.PubSub | None = None
        self._listeners: list[Callable[[KillSwitchState], None]] = []
        self._local_state = False
        self._task: asyncio.Task | None = None
    
    async def initialize(self):
        """Connect to Redis and subscribe."""
        self._redis = await aioredis.from_url(
            f"redis://{settings.redis.host}:{settings.redis.port}",
            password=settings.redis.password,
            decode_responses=True
        )
        
        self._pubsub = self._redis.pubsub()
        await self._pubsub.subscribe(self.CHANNEL)
        
        # Start listener
        self._task = asyncio.create_task(self._listen())
        
        logger.info("kill_switch_initialized")
    
    async def _listen(self):
        """Listen for kill messages."""
        async for message in self._pubsub.listen():
            if message["type"] == "message":
                try:
                    data = json.loads(message["data"])
                    state = KillSwitchState(**data)
                    
                    self._local_state = state.triggered
                    
                    # Notify listeners
                    for listener in self._listeners:
                        try:
                            listener(state)
                        except Exception as e:
                            logger.error("kill_listener_error", error=str(e))
                    
                    logger.critical(
                        "kill_switch_triggered_received",
                        reason=state.reason,
                        scope=state.scope
                    )
                    
                except json.JSONDecodeError:
                    logger.error("invalid_kill_message", data=message["data"])
    
    async def trigger(
        self,
        reason: str,
        triggered_by: str,
        scope: str = "global"
    ) -> None:
        """Trigger kill switch globally."""
        state = KillSwitchState(
            triggered=True,
            reason=reason,
            triggered_by=triggered_by,
            triggered_at=datetime.utcnow(),
            scope=scope
        )
        
        await self._redis.publish(
            self.CHANNEL,
            json.dumps(state.__dict__, default=str)
        )
        
        logger.critical(
            "kill_switch_triggered_sent",
            reason=reason,
            scope=scope
        )
    
    def add_listener(self, callback: Callable[[KillSwitchState], None]) -> None:
        """Add callback for kill events."""
        self._listeners.append(callback)
    
    @property
    def is_triggered(self) -> bool:
        """Check if kill switch is active."""
        return self._local_state
    
    async def reset(self, reset_by: str) -> None:
        """Reset kill switch (requires manual intervention)."""
        state = KillSwitchState(
            triggered=False,
            reason=f"Reset by {reset_by}",
            triggered_by=reset_by,
            triggered_at=datetime.utcnow(),
            scope="global"
        )
        
        await self._redis.publish(self.CHANNEL, json.dumps(state.__dict__, default=str))
        self._local_state = False
        
        logger.warning("kill_switch_reset", reset_by=reset_by)
    
    async def close(self):
        """Cleanup."""
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        
        if self._pubsub:
            await self._pubsub.unsubscribe(self.CHANNEL)
        
        if self._redis:
            await self._redis.close()
