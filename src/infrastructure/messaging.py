"""
Advanced messaging with Redis Streams and consumer groups.
"""

import asyncio
import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Coroutine

import aioredis

from src.core.config import settings
from src.core.logging_config import get_logger

logger = get_logger(__name__)


@dataclass
class Message:
    """Message structure for pub/sub."""
    topic: str
    payload: dict[str, Any]
    timestamp: str
    sender: str
    message_id: str | None = None


class RedisMessageBus:
    """
    Production message bus with Redis Streams.
    Supports consumer groups for horizontal scaling.
    """
    
    def __init__(self, redis_url: str | None = None):
        self.redis_url = redis_url or settings.redis.url
        self._redis: aioredis.Redis | None = None
        self._pubsub: aioredis.client.PubSub | None = None
        self._running = False
        self._handlers: dict[str, list[Callable[[Message], Coroutine]]] = {}
    
    async def connect(self) -> None:
        """Connect to Redis."""
        self._redis = aioredis.from_url(
            self.redis_url,
            decode_responses=True
        )
        
        # Test connection
        await self._redis.ping()
        logger.info("Message bus connected")
    
    async def disconnect(self) -> None:
        """Disconnect."""
        if self._pubsub:
            await self._pubsub.close()
        if self._redis:
            await self._redis.close()
    
    async def publish(self, message: Message) -> str:
        """
        Publish message to stream.
        
        Returns:
            Message ID
        """
        if not self._redis:
            raise RuntimeError("Not connected")
        
        # Add timestamp if not set
        if not message.timestamp:
            message.timestamp = datetime.now(timezone.utc).isoformat()
        
        # Publish to Redis Stream
        msg_id = await self._redis.xadd(
            f"stream:{message.topic}",
            {
                "payload": json.dumps(message.payload),
                "timestamp": message.timestamp,
                "sender": message.sender
            },
            maxlen=10000  # Keep last 10k messages
        )
        
        # Also publish to pub/sub for real-time
        await self._redis.publish(
            message.topic,
            json.dumps({
                "id": msg_id,
                "payload": message.payload,
                "timestamp": message.timestamp
            })
        )
        
        return msg_id
    
    async def subscribe(
        self,
        topic: str,
        handler: Callable[[Message], Coroutine],
        consumer_group: str | None = None
    ) -> None:
        """
        Subscribe to topic.
        
        If consumer_group provided, uses consumer group for load balancing.
        """
        if topic not in self._handlers:
            self._handlers[topic] = []
        
        self._handlers[topic].append(handler)
        
        if consumer_group:
            await self._join_consumer_group(topic, consumer_group, handler)
        else:
            await self._subscribe_pubsub(topic, handler)
    
    async def _subscribe_pubsub(
        self,
        topic: str,
        handler: Callable[[Message], Coroutine]
    ) -> None:
        """Subscribe via pub/sub for real-time."""
        if not self._pubsub:
            self._pubsub = self._redis.pubsub()
        
        await self._pubsub.subscribe(topic)
        
        async def listen():
            async for message in self._pubsub.listen():
                if message["type"] == "message":
                    data = json.loads(message["data"])
                    msg = Message(
                        topic=topic,
                        payload=data["payload"],
                        timestamp=data["timestamp"],
                        sender="unknown"
                    )
                    await handler(msg)
        
        asyncio.create_task(listen())
    
    async def _join_consumer_group(
        self,
        topic: str,
        group: str,
        handler: Callable[[Message], Coroutine]
    ) -> None:
        """Join consumer group for stream processing."""
        stream_key = f"stream:{topic}"
        
        # Create consumer group if not exists
        try:
            await self._redis.xgroup_create(stream_key, group, id="0", mkstream=True)
        except aioredis.ResponseError as e:
            if "already exists" not in str(e):
                raise
        
        consumer_name = f"consumer_{id(handler)}"
        
        async def consume():
            while self._running:
                try:
                    # Read from group
                    messages = await self._redis.xreadgroup(
                        group,
                        consumer_name,
                        {stream_key: ">"},
                        count=10,
                        block=5000
                    )
                    
                    for stream, msgs in messages:
                        for msg_id, fields in msgs:
                            msg = Message(
                                topic=topic,
                                payload=json.loads(fields["payload"]),
                                timestamp=fields["timestamp"],
                                sender=fields.get("sender", "unknown"),
                                message_id=msg_id
                            )
                            
                            try:
                                await handler(msg)
                                # Acknowledge
                                await self._redis.xack(stream_key, group, msg_id)
                            except Exception as e:
                                logger.error(f"Message handling failed: {e}")
                                
                except Exception as e:
                    logger.error(f"Consumer error: {e}")
                    await asyncio.sleep(1)
        
        asyncio.create_task(consume())
    
    async def start(self) -> None:
        """Start message bus."""
        self._running = True
        await self.connect()
    
    async def stop(self) -> None:
        """Stop message bus."""
        self._running = False
        await self.disconnect()
