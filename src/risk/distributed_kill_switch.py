"""
Distributed kill switch with consensus and automatic failover.
Uses Redis RedLock for distributed locking.
"""

import asyncio
import time
from dataclasses import dataclass
from enum import Enum, auto
from typing import Dict, List, Optional, Set

import aioredis

from src.core.config import settings
from src.core.events import Event, get_event_bus
from src.core.logging_config import get_logger
from src.infrastructure.messaging import get_message_bus, StreamMessage

logger = get_logger(__name__)


class KillSwitchState(Enum):
    ARMED = auto()
    TRIGGERED = auto()
    ACKNOWLEDGED = auto()  # All nodes acknowledged
    RESETTING = auto()


@dataclass
class KillSwitchNode:
    node_id: str
    last_heartbeat: float
    state: KillSwitchState
    latency_ms: float


class DistributedKillSwitch:
    """
    Production kill switch with:
    - Distributed consensus across all trading nodes
    - Automatic failover if coordinator fails
    - Multi-factor triggering (voting)
    - Graduated response levels
    """
    
    def __init__(
        self,
        node_id: Optional[str] = None,
        redis_url: Optional[str] = None,
        quorum_size: int = 2
    ):
        self.node_id = node_id or settings.node_id or "node-1"
        self.redis_url = redis_url or settings.redis.url
        self.quorum_size = quorum_size
        
        self._state = KillSwitchState.ARMED
        self._redis: Optional[aioredis.Redis] = None
        self._nodes: Dict[str, KillSwitchNode] = {}
        self._trigger_votes: Set[str] = set()
        self._lock = asyncio.Lock()
        
        # Response levels
        self._response_level = 0  # 0=none, 1=warning, 2=reduce, 3=stop_new, 4=close_all, 5=emergency
        
        # Heartbeat task
        self._heartbeat_task: Optional[asyncio.Task] = None
        self._running = False
    
    async def initialize(self) -> None:
        """Initialize distributed kill switch."""
        self._redis = aioredis.from_url(
            self.redis_url,
            decode_responses=True
        )
        
        # Register this node
        await self._register_node()
        
        # Start heartbeat
        self._running = True
        self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())
        
        # Subscribe to kill switch channel
        bus = await get_message_bus()
        await bus.subscribe(
            "kill_switch",
            self._on_kill_switch_message,
            consumer_group="kill_switch_nodes"
        )
        
        logger.info(f"Kill switch initialized for node {self.node_id}")
    
    async def shutdown(self) -> None:
        """Graceful shutdown."""
        self._running = False
        if self._heartbeat_task:
            self._heartbeat_task.cancel()
        
        # Deregister node
        if self._redis:
            await self._redis.hdel("kill_switch:nodes", self.node_id)
            await self._redis.close()
    
    async def _register_node(self) -> None:
        """Register this node in the cluster."""
        await self._redis.hset(
            "kill_switch:nodes",
            self.node_id,
            json.dumps({
                "registered_at": time.time(),
                "state": "ARMED"
            })
        )
    
    async def
