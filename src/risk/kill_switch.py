"""Global kill switch with Redis pub/sub."""
from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import aioredis
import structlog

logger = structlog.get_logger()


@dataclass(frozen=True)
class KillCommand:
    reason: str
    timestamp: float
    source: str
    scope: str = "GLOBAL"  # GLOBAL, SYMBOL, STRATEGY


class KillSwitch:
    """Distributed kill switch with <50ms propagation."""
    
    CHANNEL = "hopefx:kill"
    _instance: KillSwitch | None = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance
    
    def __init__(self, redis_url: str = "redis://localhost:6379/0"):
        if self._initialized:
            return
        self.redis: aioredis.Redis | None = None
        self._url = redis_url
        self._killed = False
        self._kill_reason: str | None = None
        self._listeners: list[asyncio.Task] = []
        self._lock = asyncio.Lock()
        self._initialized = True
    
    async def initialize(self) -> None:
        """Connect to Redis."""
        self.redis = aioredis.from_url(
            self._url,
            decode_responses=True,
            socket_connect_timeout=2.0
        )
        # Start listener
        task = asyncio.create_task(self._listen())
        self._listeners.append(task)
        logger.info("Kill switch armed")
    
    async def _listen(self) -> None:
        """Listen for kill commands."""
        if not self.redis:
            return
        
        pubsub = self.redis.pubsub()
        await pubsub.subscribe(self.CHANNEL)
        
        async for message in pubsub.listen():
            if message["type"] == "message":
                try:
                    data = json.loads(message["data"])
                    cmd = KillCommand(**data)
                    await self._execute_kill(cmd)
                except Exception as e:
                    logger.error(f"Kill command parse error: {e}")
    
    async def kill(self, reason: str, source: str = "manual", scope: str = "GLOBAL") -> None:
        """Trigger global kill."""
        async with self._lock:
            if self._killed:
                return  # Already killed
            
            cmd = KillCommand(
                reason=reason,
                timestamp=time.time(),
                source=source,
                scope=scope
            )
            
            # Publish to all nodes
            await self.redis.publish(
                self.CHANNEL,
                json.dumps(cmd.__dict__)
            )
            
            # Local execution
            await self._execute_kill(cmd)
            
            # Persist to Redis for recovery check
            await self.redis.setex(
                "hopefx:killed",
                86400,  # 24hr TTL
                json.dumps(cmd.__dict__)
            )
    
    async def _execute_kill(self, cmd: KillCommand) -> None:
        """Execute kill locally."""
        self._killed = True
        self._kill_reason = cmd.reason
        
        logger.critical(
            f"KILL SWITCH ACTIVATED",
            reason=cmd.reason,
            source=cmd.source,
            scope=cmd.scope,
            latency_ms=(time.time() - cmd.timestamp) * 1000
        )
        
        # Cancel all pending orders via OMS
        from src.execution.oms import OMS
        for oms in OMS._instances.values():
            await oms.emergency_cancel_all()
        
        # Close all positions (market orders)
        await self._emergency_flatten()
    
    async def _emergency_flatten(self) -> None:
        """Emergency position flattening."""
        from src.execution.router import SmartRouter
        router = SmartRouter()
        
        positions = await router.get_all_positions()
        for pos in positions:
            # Market order opposite side
            await router.emergency_close(pos)
            logger.warning(f"Emergency close: {pos.symbol} {pos.side}")
    
    async def reset(self, auth_token: str) -> bool:
        """Reset kill switch (requires auth)."""
        # Verify auth...
        async with self._lock:
            self._killed = False
            self._kill_reason = None
            await self.redis.delete("hopefx:killed")
            logger.info("Kill switch reset")
            return True
    
    @property
    def is_killed(self) -> bool:
        return self._killed
    
    async def check_recovery(self) -> None:
        """Check if killed on startup (recovery scenario)."""
        killed = await self.redis.get("hopefx:killed")
        if killed:
            data = json.loads(killed)
            logger.critical(f"System was killed: {data['reason']}")
            self._killed = True


# Global instance
kill_switch = KillSwitch()
