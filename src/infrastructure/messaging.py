"""
Production message bus using Redis Streams with consumer groups.
Provides at-least-once delivery, persistence, and horizontal scaling.
"""

import asyncio
import json
import time
import uuid
from dataclasses import asdict, dataclass, field
from typing import Any, Callable, Dict, List, Optional, Set

import aioredis

from src.core.config import settings
from src.core.exceptions import InfrastructureError
from src.core.logging_config import get_logger

logger = get_logger(__name__)


@dataclass
class StreamMessage:
    """Message structure for Redis Streams."""
    id: str
    topic: str
    payload: Dict[str, Any]
    timestamp: float
    sender: str
    priority: int = 5
    correlation_id: Optional[str] = None
    parent_id: Optional[str] = None  # For causal ordering


class RedisStreamBus:
    """
    Production message bus using Redis Streams.
    
    Features:
    - At-least-once delivery with XACK
    - Consumer groups for load balancing
    - Message persistence (survives restarts)
    - Priority handling via multiple streams
    - Dead letter queue for failed messages
    """
    
    def __init__(
        self,
        redis_url: Optional[str] = None,
        stream_maxlen: int = 100000,
        consumer_group_prefix: str = "hopefx"
    ):
        self.redis_url = redis_url or settings.redis.url
        self.stream_maxlen = stream_maxlen
        self.consumer_group_prefix = consumer_group_prefix
        
        self._redis: Optional[aioredis.Redis] = None
        self._pubsub: Optional[aioredis.client.PubSub] = None
        self._running = False
        
        # Consumer tracking
        self._consumer_groups: Dict[str, str] = {}  # topic -> group_name
        self._handlers: Dict[str, List[Callable]] = {}
        self._tasks: Set[asyncio.Task] = set()
        
        # Metrics
        self._messages_published = 0
        self._messages_consumed = 0
        self._messages_failed = 0
    
    async def connect(self) -> None:
        """Establish Redis connection with retry."""
        max_retries = 5
        for attempt in range(max_retries):
            try:
                self._redis = aioredis.from_url(
                    self.redis_url,
                    decode_responses=True,
                    socket_connect_timeout=10,
                    socket_keepalive=True,
                    health_check_interval=30,
                    retry_on_timeout=True
                )
                
                # Verify connection
                await self._redis.ping()
                logger.info("Redis Streams connected")
                return
                
            except Exception as e:
                if attempt == max_retries - 1:
                    raise InfrastructureError(f"Failed to connect to Redis: {e}")
                
                wait = 2 ** attempt
                logger.warning(f"Redis connection attempt {attempt + 1} failed, retrying in {wait}s...")
                await asyncio.sleep(wait)
    
    async def disconnect(self) -> None:
        """Graceful disconnect."""
        self._running = False
        
        # Cancel all consumer tasks
        for task in self._tasks:
            task.cancel()
        
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)
        
        if self._pubsub:
            await self._pubsub.close()
        
        if self._redis:
            await self._redis.close()
        
        logger.info("Redis Streams disconnected")
    
    async def publish(
        self,
        topic: str,
        payload: Dict[str, Any],
        priority: int = 5,
        correlation_id: Optional[str] = None
    ) -> str:
        """
        Publish message to stream.
        
        Higher priority messages go to separate stream for faster processing.
        """
        if not self._redis:
            raise InfrastructureError("Not connected")
        
        # Priority routing: 1-3 = critical stream, 4-7 = normal, 8-10 = low
        if priority <= 3:
            stream_name = f"stream:{topic}:critical"
        elif priority >= 8:
            stream_name = f"stream:{topic}:low"
        else:
            stream_name = f"stream:{topic}"
        
        message_id = await self._redis.xadd(
            stream_name,
            {
                "payload": json.dumps(payload),
                "timestamp": str(time.time()),
                "sender": settings.app_name,
                "priority": str(priority),
                "correlation_id": correlation_id or str(uuid.uuid4())
            },
            maxlen=self.stream_maxlen,
            approximate=True  # Faster, may exceed maxlen slightly
        )
        
        self._messages_published += 1
        
        # Also publish to pub/sub for real-time subscribers
        await self._redis.publish(
            f"pubsub:{topic}",
            json.dumps({
                "id": message_id,
                "payload": payload,
                "priority": priority
            })
        )
        
        return message_id
    
    async def subscribe(
        self,
        topic: str,
        handler: Callable[[StreamMessage], Any],
        consumer_group: Optional[str] = None,
        consumer_name: Optional[str] = None,
        batch_size: int = 10,
        block_ms: int = 5000
    ) -> None:
        """
        Subscribe to stream with consumer group for load balancing.
        
        If consumer_group not provided, uses pub/sub (broadcast, no persistence).
        """
        if consumer_group:
            await self._subscribe_stream(
                topic, handler, consumer_group, consumer_name, batch_size, block_ms
            )
        else:
            await self._subscribe_pubsub(topic, handler)
    
    async def _subscribe_stream(
        self,
        topic: str,
        handler: Callable,
        consumer_group: str,
        consumer_name: Optional[str],
        batch_size: int,
        block_ms: int
    ) -> None:
        """Subscribe via Redis Streams (persistent, load-balanced)."""
        if not self._redis:
            raise InfrastructureError("Not connected")
        
        stream_name = f"stream:{topic}"
        group_name = f"{self.consumer_group_prefix}:{consumer_group}"
        consumer_name = consumer_name or f"consumer-{uuid.uuid4().hex[:8]}"
        
        # Create consumer group if not exists
        try:
            await self._redis.xgroup_create(
                stream_name,
                group_name,
                id="0",  # Start from beginning
                mkstream=True
            )
            logger.info(f"Created consumer group {group_name} for {stream_name}")
        except aioredis.ResponseError as e:
            if "already exists" not in str(e):
                raise
        
        # Also create for priority streams
        for suffix in ["critical", "low"]:
            try:
                await self._redis.xgroup_create(
                    f"{stream_name}:{suffix}",
                    group_name,
                    id="0",
                    mkstream=True
                )
            except aioredis.ResponseError:
                pass  # May already exist
        
        # Start consumer task
        task = asyncio.create_task(
            self._consume_stream(
                stream_name, group_name, consumer_name,
                handler, batch_size, block_ms
            ),
            name=f"consumer-{topic}"
        )
        self._tasks.add(task)
    
    async def _consume_stream(
        self,
        stream_name: str,
        group_name: str,
        consumer_name: str,
        handler: Callable,
        batch_size: int,
        block_ms: int
    ) -> None:
        """Main consumer loop with priority handling."""
        # Process critical stream first, then normal, then low
        streams = [
            f"{stream_name}:critical",
            stream_name,
            f"{stream_name}:low"
        ]
        
        while self._running:
            try:
                # Read from all streams
                read_streams = {s: ">" for s in streams}  # ">" = undelivered messages
                
                messages = await self._redis.xreadgroup(
                    group_name=group_name,
                    consumer_name=consumer_name,
                    streams=read_streams,
                    count=batch_size,
                    block=block_ms
                )
                
                for stream, entries in messages:
                    for msg_id, fields in entries:
                        try:
                            # Parse message
                            msg = StreamMessage(
                                id=msg_id,
                                topic=stream.decode() if isinstance(stream, bytes) else stream,
                                payload=json.loads(fields["payload"]),
                                timestamp=float(fields["timestamp"]),
                                sender=fields["sender"],
                                priority=int(fields.get("priority", 5)),
                                correlation_id=fields.get("correlation_id")
                            )
                            
                            # Process
                            await handler(msg)
                            self._messages_consumed += 1
                            
                            # Acknowledge
                            await self._redis.xack(stream_name, group_name, msg_id)
                            
                        except Exception as e:
                            logger.error(f"Message processing failed: {e}")
                            self._messages_failed += 1
                            
                            # Send to dead letter queue after retries
                            await self._send_to_dlq(stream_name, msg_id, fields, str(e))
                            
                            # Still ack to prevent infinite retry
                            await self._redis.xack(stream_name, group_name, msg_id)
                            
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Consumer error: {e}")
                await asyncio.sleep(1)
    
    async def _subscribe_pubsub(
        self,
        topic: str,
        handler: Callable
    ) -> None:
        """Subscribe via Pub/Sub (ephemeral, broadcast)."""
        if not self._redis:
            raise InfrastructureError("Not connected")
        
        self._pubsub = self._redis.pubsub()
        await self._pubsub.subscribe(f"pubsub:{topic}")
        
        async def listen():
            async for message in self._pubsub.listen():
                if message["type"] == "message":
                    try:
                        data = json.loads(message["data"])
                        msg = StreamMessage(
                            id=data["id"],
                            topic=topic,
                            payload=data["payload"],
                            timestamp=time.time(),
                            sender="unknown",
                            priority=data.get("priority", 5)
                        )
                        await handler(msg)
                    except Exception as e:
                        logger.error(f"Pub/Sub handler error: {e}")
        
        task = asyncio.create_task(listen(), name=f"pubsub-{topic}")
        self._tasks.add(task)
    
    async def _send_to_dlq(
        self,
        stream: str,
        msg_id: str,
        fields: dict,
        error: str
    ) -> None:
        """Send failed message to dead letter queue."""
        dlq_entry = {
            "original_stream": stream,
            "original_id": msg_id,
            "payload": fields.get("payload"),
            "error": error,
            "failed_at": str(time.time()),
            "retry_count": fields.get("retry_count", 0)
        }
        
        await self._redis.xadd(
            "stream:dead_letter_queue",
            dlq_entry,
            maxlen=10000
        )
    
    async def claim_pending_messages(
        self,
        topic: str,
        consumer_group: str,
        idle_time_ms: int = 60000
    ) -> List[StreamMessage]:
        """
        Claim messages from failed consumers.
        Call periodically to handle consumer failures.
        """
        stream_name = f"stream:{topic}"
        group_name = f"{self.consumer_group_prefix}:{consumer_group}"
        
        # Find idle messages
        pending = await self._redis.xpending_range(
            stream_name,
            group_name,
            min="-",
            max="+",
            count=100
        )
        
        claimed = []
        for item in pending:
            if item["time_since_delivered"] > idle_time_ms:
                # Claim the message
                msgs = await self._redis.xclaim(
                    stream_name,
                    group_name,
                    "recovery-consumer",
                    min_idle_time=idle_time_ms,
                    message_ids=[item["message_id"]]
                )
                claimed.extend(msgs)
        
        return claimed
    
    async def get_stream_info(self, topic: str) -> dict:
        """Get stream statistics."""
        stream_name = f"stream:{topic}"
        
        info = await self._redis.xinfo_stream(stream_name)
        groups = await self._redis.xinfo_groups(stream_name)
        
        return {
            "length": info.get("length", 0),
            "radix_tree_keys": info.get("radix-tree-keys", 0),
            "consumer_groups": len(groups),
            "last_generated_id": info.get("last-generated-id"),
            "first_entry": info.get("first-entry"),
            "last_entry": info.get("last-entry")
        }
    
    async def start(self) -> None:
        """Start message bus."""
        self._running = True
        await self.connect()
    
    async def stop(self) -> None:
        """Stop message bus."""
        self._running = False
        await self.disconnect()


# Global instance
_message_bus: Optional[RedisStreamBus] = None


async def get_message_bus() -> RedisStreamBus:
    """Get or initialize message bus."""
    global _message_bus
    if _message_bus is None:
        _message_bus = RedisStreamBus()
        await _message_bus.start()
    return _message_bus
