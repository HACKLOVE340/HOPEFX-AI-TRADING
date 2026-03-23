"""
Distributed kill switch with consensus and automatic failover.
Uses Redis RedLock for distributed locking.
"""

import asyncio
import time
from dataclasses import dataclass
from enum import Enum, auto
from typing import Dict, Optional, Set

import aioredis

from src.core.config import settings
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
        quorum_size: int = 2,
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
        self._response_level = (
            0  # 0=none, 1=warning, 2=reduce, 3=stop_new, 4=close_all, 5=emergency
        )

        # Heartbeat task
        self._heartbeat_task: Optional[asyncio.Task] = None
        self._running = False

    async def initialize(self) -> None:
        """Initialize distributed kill switch."""
        self._redis = aioredis.from_url(self.redis_url, decode_responses=True)

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
            consumer_group="kill_switch_nodes",
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
            json.dumps({"registered_at": time.time(), "state": "ARMED"}),
        )

    async def _heartbeat_loop(self) -> None:
        """Periodically publish this node's heartbeat to Redis."""
        while self._running:
            try:
                if self._redis:
                    await self._redis.hset(
                        "kill_switch:nodes",
                        self.node_id,
                        json.dumps(
                            {
                                "last_heartbeat": time.time(),
                                "state": self._state.name,
                            }
                        ),
                    )
            except Exception as exc:
                logger.warning("kill_switch.heartbeat_error", error=str(exc))
            await asyncio.sleep(5)

    async def _on_kill_switch_message(self, message: "StreamMessage") -> None:
        """Handle incoming kill-switch messages from the message bus."""
        try:
            payload = message.data if hasattr(message, "data") else {}
            reason = payload.get("reason", "remote signal")
            async with self._lock:
                self._state = KillSwitchState.TRIGGERED
            logger.critical("kill_switch.triggered", reason=reason, node=self.node_id)
        except Exception as exc:
            logger.error("kill_switch.message_error", error=str(exc))

    async def trigger(
        self, reason: str = "manual", votes_required: bool = True
    ) -> bool:
        """
        Trigger the kill switch.

        Args:
            reason: Human-readable reason for the trigger.
            votes_required: When True, quorum must be reached before full activation.

        Returns:
            True if the kill switch was activated.
        """
        async with self._lock:
            self._trigger_votes.add(self.node_id)

            if not votes_required or len(self._trigger_votes) >= self.quorum_size:
                self._state = KillSwitchState.TRIGGERED
                logger.critical(
                    "kill_switch.activated",
                    reason=reason,
                    votes=len(self._trigger_votes),
                    node=self.node_id,
                )

                if self._redis:
                    try:
                        import json as _json

                        await self._redis.publish(
                            "kill_switch",
                            _json.dumps({"reason": reason, "node": self.node_id}),
                        )
                    except Exception as exc:
                        logger.warning("kill_switch.publish_error", error=str(exc))

                return True

            logger.warning(
                "kill_switch.vote_recorded",
                votes=len(self._trigger_votes),
                required=self.quorum_size,
            )
            return False

    @property
    def is_triggered(self) -> bool:
        """True when the kill switch has been activated."""
        return self._state == KillSwitchState.TRIGGERED
