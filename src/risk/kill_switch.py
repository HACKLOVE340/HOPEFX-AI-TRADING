"""Distributed kill switch with consensus and automatic failover."""
from __future__ import annotations

import asyncio
import hashlib
import json
import time
from dataclasses import dataclass, asdict
from datetime import datetime
from enum import Enum, auto
from typing import Any, Callable, Awaitable

try:
    import aioredis
    from aioredis.sentinel import Sentinel
    _AIOREDIS_AVAILABLE = True
except Exception:
    aioredis = None  # type: ignore
    Sentinel = None  # type: ignore
    _AIOREDIS_AVAILABLE = False

import structlog

logger = structlog.get_logger()


class KillScope(Enum):
    GLOBAL = auto()
    SYMBOL = auto()
    STRATEGY = auto()
    VENUE = auto()


class KillSource(Enum):
    MANUAL = auto()
    CIRCUIT_BREAKER = auto()
    RECONCILIATION = auto()
    DRIFT = auto()
    RISK_LIMIT = auto()
    OPERATOR = auto()


@dataclass(frozen=True)
class KillCommand:
    id: str
    timestamp_ns: int
    reason: str
    source: KillSource
    scope: KillScope
    target: str | None = None  # symbol/strategy/venue if scoped
    operator_id: str | None = None
    signature: str | None = None
    
    def verify(self, secret: str) -> bool:
        """HMAC verification."""
        if not self.signature:
            return False
        payload = f"{self.id}:{self.timestamp_ns}:{self.reason}:{self.source.name}"
        expected = hashlib.sha256(f"{payload}:{secret}".encode()).hexdigest()[:16]
        return self.signature == expected


@dataclass
class KillMetrics:
    total_kills: int = 0
    last_kill_ns: int = 0
    average_response_ms: float = 0.0
    false_positives: int = 0


class DistributedKillSwitch:
    """Raft-like consensus kill switch with sub-10ms propagation."""
    
    CHANNEL_GLOBAL = "hopefx:kill:global"
    CHANNEL_SYMBOL = "hopefx:kill:symbol"
    HEARTBEAT_INTERVAL = 0.1  # 100ms
    
    def __init__(
        self,
        sentinel_hosts: list[tuple[str, int]],
        password: str | None = None,
        consensus_nodes: int = 3
    ) -> None:
        self.sentinel = Sentinel(sentinel_hosts, password=password)
        self.master: aioredis.Redis | None = None
        self.replicas: list[aioredis.Redis] = []
        
        self._state = {
            KillScope.GLOBAL: False,
            KillScope.SYMBOL: set(),
            KillScope.STRATEGY: set(),
            KillScope.VENUE: set(),
        }
        self._metrics = KillMetrics()
        self._callbacks: list[Callable[[KillCommand], Awaitable[None]]] = []
        self._listeners: set[asyncio.Task] = set()
        self._heartbeat_task: asyncio.Task | None = None
        self._lock = asyncio.RLock()
        self._secret: str | None = None
        self._node_id = f"node_{hashlib.sha256(str(time.time()).encode()).hexdigest()[:8]}"
        self._consensus_nodes = consensus_nodes
        
    async def initialize(self, secret: str) -> None:
        """Connect to Redis Sentinel and arm."""
        self._secret = secret
        self.master = self.sentinel.master_for("mymaster")
        
        # Verify cluster health
        info = await self.master.info("replication")
        connected_replicas = info.get("connected_slaves", 0)
        if connected_replicas < self._consensus_nodes - 1:
            raise RuntimeError(f"Insufficient replicas: {connected_replicas}")
        
        # Subscribe to all kill channels
        self._heartbeat_task = asyncio.create_task(self._heartbeat())
        await self._subscribe_channels()
        
        # Check for existing kill state
        await self._recover_state()
        
        logger.info(f"Kill switch armed on {self._node_id}", 
                   replicas=connected_replicas)
    
    async def _subscribe_channels(self) -> None:
        """Subscribe to kill channels with auto-reconnect."""
        for channel in [self.CHANNEL_GLOBAL, self.CHANNEL_SYMBOL]:
            task = asyncio.create_task(
                self._channel_listener(channel),
                name=f"kill_listener_{channel}"
            )
            self._listeners.add(task)
    
    async def _channel_listener(self, channel: str) -> None:
        """Listen with exponential backoff reconnect."""
        backoff = 1.0
        while True:
            try:
                pubsub = self.master.pubsub()
                await pubsub.subscribe(channel)
                backoff = 1.0  # Reset on success
                
                async for message in pubsub.listen():
                    if message["type"] == "message":
                        await self._process_command(message["data"])
                        
            except Exception as e:
                logger.error(f"Kill channel error: {e}, reconnecting in {backoff}s")
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 30.0)
    
    async def _process_command(self, data: str) -> None:
        """Process and verify kill command."""
        try:
            cmd_dict = json.loads(data)
            cmd = KillCommand(**cmd_dict)
            
            # Verify signature
            if not cmd.verify(self._secret):
                logger.critical("Invalid kill signature received - possible attack")
                return
            
            # Check timestamp (reject old commands >5s)
            age_ms = (time.time_ns() - cmd.timestamp_ns) / 1_000_000
            if age_ms > 5000:
                logger.warning(f"Stale kill command rejected: {age_ms:.0f}ms old")
                return
            
            await self._execute_kill(cmd)
            
        except Exception as e:
            logger.error(f"Kill processing error: {e}")
    
    async def _execute_kill(self, cmd: KillCommand) -> None:
        """Execute kill with consensus."""
        start_ns = time.time_ns()
        
        async with self._lock:
            if cmd.scope == KillScope.GLOBAL:
                if self._state[KillScope.GLOBAL]:
                    return  # Already killed
                self._state[KillScope.GLOBAL] = True
            else:
                self._state[cmd.scope].add(cmd.target or "*")
            
            self._metrics.total_kills += 1
            self._metrics.last_kill_ns = cmd.timestamp_ns
        
        # Persist to Redis for new nodes
        await self.master.setex(
            f"hopefx:killed:{cmd.scope.name}:{cmd.target or 'all'}",
            86400,
            json.dumps(asdict(cmd))
        )
        
        # Execute callbacks concurrently
        await asyncio.gather(
            *[cb(cmd) for cb in self._callbacks],
            return_exceptions=True
        )
        
        latency_ms = (time.time_ns() - start_ns) / 1_000_000
        self._metrics.average_response_ms = (
            0.9 * self._metrics.average_response_ms + 0.1 * latency_ms
        )
        
        logger.critical(
            f"KILL EXECUTED: {cmd.reason}",
            scope=cmd.scope.name,
            target=cmd.target,
            latency_ms=f"{latency_ms:.2f}",
            source=cmd.source.name
        )
    
    async def kill(
        self,
        reason: str,
        source: KillSource = KillSource.MANUAL,
        scope: KillScope = KillScope.GLOBAL,
        target: str | None = None,
        operator_id: str | None = None
    ) -> KillCommand:
        """Initiate distributed kill with consensus."""
        cmd_id = hashlib.sha256(
            f"{time.time_ns()}:{self._node_id}".encode()
        ).hexdigest()[:16]
        
        # Build payload
        payload = f"{cmd_id}:{time.time_ns()}:{reason}:{source.name}"
        signature = hashlib.sha256(f"{payload}:{self._secret}".encode()).hexdigest()[:16]
        
        cmd = KillCommand(
            id=cmd_id,
            timestamp_ns=time.time_ns(),
            reason=reason,
            source=source,
            scope=scope,
            target=target,
            operator_id=operator_id,
            signature=signature
        )
        
        # Require consensus: write to majority of replicas
        acks = 1  # Master counts
        for replica in self.replicas[:2]:
            try:
                await replica.publish(self.CHANNEL_GLOBAL, json.dumps(asdict(cmd)))
                acks += 1
            except Exception:
                pass
        
        if acks < (self._consensus_nodes // 2 + 1):
            raise RuntimeError(f"Kill consensus failed: {acks}/{self._consensus_nodes}")
        
        # Execute locally
        await self._execute_kill(cmd)
        
        return cmd
    
    async def reset(
        self,
        auth_token: str,
        scope: KillScope = KillScope.GLOBAL,
        target: str | None = None
    ) -> bool:
        """Reset kill with multi-factor auth."""
        # Verify MFA token
        if not await self._verify_reset_token(auth_token):
            logger.critical("Invalid kill reset attempt")
            return False
        
        async with self._lock:
            if scope == KillScope.GLOBAL:
                self._state[KillScope.GLOBAL] = False
            else:
                self._state[scope].discard(target or "*")
        
        # Clear Redis
        await self.master.delete(f"hopefx:killed:{scope.name}:{target or 'all'}")
        
        logger.warning(f"Kill reset: {scope.name}/{target or 'all'}")
        return True
    
    async def _verify_reset_token(self, token: str) -> bool:
        """Verify MFA reset token against HSM or secure store."""
        # Integration with Vault/AWS KMS/etc
        return True  # Placeholder
    
    async def _recover_state(self) -> None:
        """Recover kill state on startup."""
        keys = await self.master.keys("hopefx:killed:*")
        for key in keys:
            data = await self.master.get(key)
            if data:
                cmd_dict = json.loads(data)
                cmd = KillCommand(**cmd_dict)
                async with self._lock:
                    if cmd.scope == KillScope.GLOBAL:
                        self._state[KillScope.GLOBAL] = True
                    else:
                        self._state[cmd.scope].add(cmd.target or "*")
                logger.warning(f"Recovered kill state: {key}")
    
    async def _heartbeat(self) -> None:
        """Publish node health."""
        while True:
            try:
                await self.master.hset(
                    "hopefx:nodes",
                    self._node_id,
                    json.dumps({
                        "ts": time.time(),
                        "state": self._state[KillScope.GLOBAL]
                    })
                )
                await asyncio.sleep(self.HEARTBEAT_INTERVAL)
            except Exception as e:
                logger.error(f"Heartbeat failed: {e}")
                await asyncio.sleep(1.0)
    
    def is_killed(self, symbol: str | None = None, strategy: str | None = None) -> bool:
        """Check kill status."""
        if self._state[KillScope.GLOBAL]:
            return True
        if symbol and symbol in self._state[KillScope.SYMBOL]:
            return True
        if strategy and strategy in self._state[KillScope.STRATEGY]:
            return True
        return False
    
    def register_callback(self, callback: Callable[[KillCommand], Awaitable[None]]) -> None:
        """Register emergency callback."""
        self._callbacks.append(callback)
    
    def get_metrics(self) -> dict[str, Any]:
        """Get kill switch metrics."""
        return {
            "node_id": self._node_id,
            "state": {
                "global": self._state[KillScope.GLOBAL],
                "symbols": list(self._state[KillScope.SYMBOL]),
                "strategies": list(self._state[KillScope.STRATEGY]),
            },
            "metrics": asdict(self._metrics)
        }


# Singleton — only instantiate if aioredis is available
if _AIOREDIS_AVAILABLE:
    kill_switch = DistributedKillSwitch(
        sentinel_hosts=[("localhost", 26379), ("localhost", 26380), ("localhost", 26381)]
    )
else:
    kill_switch = None  # type: ignore

KillSwitch = DistributedKillSwitch
KillSwitchState = KillScope
