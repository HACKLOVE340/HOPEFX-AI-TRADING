# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
resilience/hot_standby.py
==========================
HotStandbyReplicator — position-state sync, standby promotion, and
auto-failover beyond Redis Sentinel.

What Redis Sentinel already handles
------------------------------------
Redis Sentinel provides HA for the cache layer: it monitors the Redis
master, elects a new master on failure, and updates clients via the
Sentinel protocol. That covers cache-level HA only.

What this module adds
---------------------
1. **Position-state replication** — every open position, fill, and equity
   snapshot is written to a Redis replication key with a TTL. A standby
   pod reads this key on startup and restores full trading state without
   replaying the entire order book.

2. **Heartbeat + liveness** — the primary pod writes a heartbeat key every
   HEARTBEAT_INTERVAL_S seconds. Standby pods monitor this key. If the
   primary misses HEARTBEAT_MISS_THRESHOLD consecutive beats, the standby
   initiates promotion.

3. **Leader election via Redis SET NX** — only one pod holds the
   ``hopefx:leader`` key at a time. The primary refreshes it every
   HEARTBEAT_INTERVAL_S. A standby acquires it only after the TTL expires
   (primary is confirmed dead). This prevents split-brain.

4. **Standby promotion** — on acquiring the leader key, the standby:
   a. Restores position state from the replication snapshot.
   b. Calls ``on_promote_callback`` so the application layer can start
      the execution engine and reconnect brokers.
   c. Begins writing its own heartbeat and state snapshots.

5. **Graceful primary handoff** — the primary can voluntarily release the
   leader key (e.g. on planned maintenance), triggering immediate standby
   promotion without waiting for TTL expiry.

Architecture
------------
  Primary pod                         Standby pod(s)
  ──────────────────────────────────  ──────────────────────────────────
  HotStandbyReplicator(role=PRIMARY)  HotStandbyReplicator(role=STANDBY)
    │                                   │
    ├── write_heartbeat() every 5s      ├── monitor_heartbeat() every 5s
    ├── replicate_state() every 1s      ├── try_acquire_leader() on miss
    └── refresh_leader_key() every 5s  └── restore_state() on promotion

Redis key schema
----------------
  hopefx:leader                — leader lock (SET NX PX ttl_ms)
  hopefx:heartbeat:{pod_id}    — last heartbeat epoch (float, TTL=30s)
  hopefx:state:positions       — JSON snapshot of open positions
  hopefx:state:equity          — JSON snapshot of equity/balance
  hopefx:state:fills           — JSON list of last N fills (ring buffer)
  hopefx:state:version         — monotonic state version counter

Configuration (env vars)
------------------------
  STANDBY_HEARTBEAT_INTERVAL_S    — heartbeat write interval (default: 5)
  STANDBY_HEARTBEAT_MISS_THRESHOLD — missed beats before promotion (default: 3)
  STANDBY_LEADER_TTL_S            — leader key TTL in seconds (default: 15)
  STANDBY_STATE_INTERVAL_S        — state snapshot interval (default: 1)
  STANDBY_FILLS_RING_SIZE         — max fills kept in replication ring (default: 500)
  STANDBY_POD_ID                  — unique pod identifier (default: hostname)
  STANDBY_ROLE                    — \"primary\" | \"standby\" | \"auto\" (default: auto)

Usage
-----
    from resilience.hot_standby import HotStandbyReplicator
    replicator = HotStandbyReplicator(
        redis_client=redis_client,
        on_promote_callback=my_promote_fn,   # async def promote(state_snapshot)
        on_demote_callback=my_demote_fn,     # async def demote()
    )
    await replicator.start()

    # In the execution engine, call on every state change:
    replicator.update_positions(open_positions)
    replicator.update_equity(equity=99_500, balance=99_800)
    replicator.record_fill(fill_dict)

    # On planned shutdown:
    await replicator.graceful_handoff()
    await replicator.stop()
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import socket
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone

UTC = timezone.utc
from typing import Any

try:
    from enum import StrEnum
except ImportError:
    from enum import Enum

    class StrEnum(str, Enum):  # Python 3.10 compat
        pass


logger = logging.getLogger(__name__)

# ── Configuration ─────────────────────────────────────────────────────────────
_HEARTBEAT_INTERVAL_S = float(os.getenv("STANDBY_HEARTBEAT_INTERVAL_S", "5.0"))
_HEARTBEAT_MISS_THRESHOLD = int(os.getenv("STANDBY_HEARTBEAT_MISS_THRESHOLD", "3"))
_LEADER_TTL_S = float(os.getenv("STANDBY_LEADER_TTL_S", "60.0"))  # default 60s — safe for single-pod dev
_STATE_INTERVAL_S = float(os.getenv("STANDBY_STATE_INTERVAL_S", "1.0"))
_FILLS_RING_SIZE = int(os.getenv("STANDBY_FILLS_RING_SIZE", "500"))
_POD_ID = os.getenv("STANDBY_POD_ID", socket.gethostname())
_ROLE_ENV = os.getenv("STANDBY_ROLE", "auto").lower()  # may be "auto" if .env not yet loaded


def _role_env() -> str:
    """Read STANDBY_ROLE at call time so .env values loaded after import are respected."""
    return os.getenv("STANDBY_ROLE", _ROLE_ENV).lower()


def _decode(value: str | bytes | None) -> str | None:
    """Return a str from a Redis value regardless of decode_responses setting."""
    if value is None:
        return None
    if isinstance(value, bytes):
        return value.decode()
    return value  # already str when decode_responses=True


# ── Redis key constants ───────────────────────────────────────────────────────
_KEY_LEADER = "hopefx:leader"
_KEY_HEARTBEAT = f"hopefx:heartbeat:{_POD_ID}"
_KEY_POSITIONS = "hopefx:state:positions"
_KEY_EQUITY = "hopefx:state:equity"
_KEY_FILLS = "hopefx:state:fills"
_KEY_VERSION = "hopefx:state:version"

# ── Prometheus ────────────────────────────────────────────────────────────────
try:
    from prometheus_client import Counter, Gauge, Histogram

    _prom_role = Gauge("hopefx_standby_role", "Current pod role: 1=primary 0=standby")
    _prom_promotions = Counter("hopefx_standby_promotions_total", "Number of standby→primary promotions")
    _prom_heartbeat_age = Gauge("hopefx_standby_heartbeat_age_s", "Seconds since last primary heartbeat")
    _prom_state_version = Gauge("hopefx_standby_state_version", "Current replicated state version")
    _prom_repl_lag_ms = Histogram(
        "hopefx_standby_replication_lag_ms",
        "State replication write latency ms",
        buckets=[1, 5, 10, 25, 50, 100, 250],
    )
    _PROM_OK = True
except ImportError:
    _PROM_OK = False


class Role(StrEnum):
    PRIMARY = "primary"
    STANDBY = "standby"


@dataclass
class StateSnapshot:
    """Complete trading state snapshot for standby restoration."""

    positions: dict[str, Any]  # symbol → position dict
    equity: float
    balance: float
    fills: list[dict]  # last N fills (ring buffer)
    version: int
    captured_at: str  # ISO timestamp
    pod_id: str


@dataclass
class ReplicationStats:
    """Runtime replication statistics."""

    role: Role
    pod_id: str
    state_version: int = 0
    last_heartbeat_ts: float = 0.0
    missed_heartbeats: int = 0
    promotions: int = 0
    last_replication_ms: float = 0.0
    is_leader: bool = False
    started_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())


class HotStandbyReplicator:
    """
    Hot-standby replication with leader election and auto-failover.

    Thread-safe: all Redis writes are async; state updates are synchronous
    (called from the engine's event loop) and buffered for the async writer.
    """

    def __init__(
        self,
        redis_client: Any,
        on_promote_callback: Callable | None = None,
        on_demote_callback: Callable | None = None,
        role: Role | None = None,
    ) -> None:
        self._redis = redis_client
        self._on_promote = on_promote_callback  # async def(StateSnapshot)
        self._on_demote = on_demote_callback  # async def()

        # Determine initial role
        if role is not None:
            self._role = role
        elif _role_env() == "primary":
            self._role = Role.PRIMARY
        elif _role_env() == "standby":
            self._role = Role.STANDBY
        else:
            # Auto: try to acquire leader key; if acquired → primary
            self._role = Role.STANDBY  # will be resolved in start()

        self._pod_id = _POD_ID
        self._stats = ReplicationStats(role=self._role, pod_id=self._pod_id)

        # In-memory state buffer (written by engine, read by replication loop)
        self._positions: dict[str, Any] = {}
        self._equity: float = 0.0
        self._balance: float = 0.0
        self._fills: list[dict] = []

        self._running = False
        self._tasks: list[asyncio.Task] = []

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    async def start(self) -> None:
        """Start replication loops. Resolves role if STANDBY_ROLE=auto."""
        if self._redis is None:
            logger.warning(
                "HotStandbyReplicator: Redis unavailable — replication disabled pod=%s",
                self._pod_id,
            )
            return

        self._running = True

        if _role_env() == "auto":
            acquired = await self._try_acquire_leader(initial=True)
            self._role = Role.PRIMARY if acquired else Role.STANDBY
            self._stats.role = self._role
            logger.info(
                "HotStandbyReplicator: auto-resolved role=%s pod=%s",
                self._role.value,
                self._pod_id,
            )

        if _PROM_OK:
            _prom_role.set(1 if self._role == Role.PRIMARY else 0)

        if self._role == Role.PRIMARY:
            await self._start_as_primary()
        else:
            await self._start_as_standby()

    async def stop(self) -> None:
        """Stop all replication tasks."""
        self._running = False
        for task in self._tasks:
            task.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks.clear()
        logger.info(
            "HotStandbyReplicator: stopped role=%s pod=%s",
            self._role.value,
            self._pod_id,
        )

    async def graceful_handoff(self) -> None:
        """
        Voluntarily release the leader key so a standby can promote
        immediately without waiting for TTL expiry.

        Call this before a planned shutdown or rolling restart.
        """
        if self._role != Role.PRIMARY or self._redis is None:
            return
        try:
            await self._redis.delete(_KEY_LEADER)
            logger.warning(
                "HotStandbyReplicator: graceful handoff — leader key released pod=%s",
                self._pod_id,
            )
        except Exception as exc:
            logger.error("graceful_handoff: Redis delete failed: %s", exc)

    # ── State update API (called by execution engine) ─────────────────────────

    def update_positions(self, positions: dict[str, Any]) -> None:
        """Update the in-memory position snapshot. Thread-safe (GIL)."""
        self._positions = dict(positions)

    def update_equity(self, equity: float, balance: float | None = None) -> None:
        """Update equity/balance snapshot."""
        self._equity = equity
        self._balance = balance if balance is not None else equity

    def record_fill(self, fill: dict[str, Any]) -> None:
        """Append a fill to the replication ring buffer."""
        self._fills.append(fill)
        if len(self._fills) > _FILLS_RING_SIZE:
            self._fills = self._fills[-_FILLS_RING_SIZE:]

    # ── Primary loops ─────────────────────────────────────────────────────────

    async def _start_as_primary(self) -> None:
        self._stats.is_leader = True
        logger.info("HotStandbyReplicator: starting as PRIMARY pod=%s", self._pod_id)
        self._tasks.append(asyncio.create_task(self._heartbeat_loop(), name="standby_heartbeat"))
        self._tasks.append(asyncio.create_task(self._state_replication_loop(), name="standby_state_repl"))
        self._tasks.append(asyncio.create_task(self._leader_refresh_loop(), name="standby_leader_refresh"))

    async def _heartbeat_loop(self) -> None:
        """Write heartbeat key every HEARTBEAT_INTERVAL_S seconds."""
        while self._running:
            try:
                await self._redis.setex(
                    _KEY_HEARTBEAT,
                    int(_LEADER_TTL_S * 2),  # TTL = 2× leader TTL
                    str(time.time()),
                )
                self._stats.last_heartbeat_ts = time.time()
                if _PROM_OK:
                    _prom_heartbeat_age.set(0.0)
            except Exception as exc:
                logger.error("Heartbeat write failed: %s", exc)
            await asyncio.sleep(_HEARTBEAT_INTERVAL_S)

    async def _state_replication_loop(self) -> None:
        """Replicate full position/equity/fill state every STATE_INTERVAL_S."""
        while self._running:
            t0 = time.monotonic()
            try:
                await self._write_state_snapshot()
            except Exception as exc:
                logger.error("State replication failed: %s", exc)
            elapsed_ms = (time.monotonic() - t0) * 1000
            self._stats.last_replication_ms = elapsed_ms
            if _PROM_OK:
                _prom_repl_lag_ms.observe(elapsed_ms)
            await asyncio.sleep(_STATE_INTERVAL_S)

    async def _leader_refresh_loop(self) -> None:
        """Refresh the leader key TTL every HEARTBEAT_INTERVAL_S."""
        _forced_primary = _role_env() == "primary"
        while self._running:
            try:
                # GETSET pattern: only refresh if we still own the key
                current = await self._redis.get(_KEY_LEADER)
                if current and _decode(current) == self._pod_id:
                    await self._redis.pexpire(_KEY_LEADER, int(_LEADER_TTL_S * 1000))
                elif _forced_primary:
                    # STANDBY_ROLE=primary: re-acquire the key rather than demoting.
                    # In single-pod dev the key may have expired between refreshes.
                    await self._redis.set(_KEY_LEADER, self._pod_id, px=int(_LEADER_TTL_S * 1000))
                    logger.debug("HotStandbyReplicator: re-acquired leader key (forced primary)")
                else:
                    # Lost the leader key — demote
                    logger.critical(
                        "HotStandbyReplicator: lost leader key! current=%s pod=%s — demoting",
                        _decode(current),
                        self._pod_id,
                    )
                    await self._demote()
                    return
            except Exception as exc:
                logger.error("Leader refresh failed: %s", exc)
            await asyncio.sleep(_HEARTBEAT_INTERVAL_S)

    # ── Standby loops ─────────────────────────────────────────────────────────

    async def _start_as_standby(self) -> None:
        self._stats.is_leader = False
        logger.info("HotStandbyReplicator: starting as STANDBY pod=%s", self._pod_id)
        self._tasks.append(asyncio.create_task(self._monitor_loop(), name="standby_monitor"))

    async def _monitor_loop(self) -> None:
        """
        Monitor primary heartbeat. Attempt promotion after
        HEARTBEAT_MISS_THRESHOLD consecutive missed beats.
        """
        while self._running:
            await asyncio.sleep(_HEARTBEAT_INTERVAL_S)
            if self._redis is None:
                logger.debug("Standby monitor: Redis unavailable — skipping heartbeat check")
                continue
            try:
                raw = await self._redis.get(_KEY_HEARTBEAT)
                if raw is None:
                    self._stats.missed_heartbeats += 1
                    age_s = _HEARTBEAT_INTERVAL_S * self._stats.missed_heartbeats
                else:
                    last_ts = float(_decode(raw))
                    age_s = time.time() - last_ts
                    if age_s < _HEARTBEAT_INTERVAL_S * 1.5:
                        self._stats.missed_heartbeats = 0
                    else:
                        self._stats.missed_heartbeats += 1

                if _PROM_OK:
                    _prom_heartbeat_age.set(age_s)

                logger.debug(
                    "Standby monitor: missed=%d age=%.1fs pod=%s",
                    self._stats.missed_heartbeats,
                    age_s,
                    self._pod_id,
                )

                if self._stats.missed_heartbeats >= _HEARTBEAT_MISS_THRESHOLD:
                    logger.warning(
                        "Primary heartbeat missed %d times — attempting promotion pod=%s",
                        self._stats.missed_heartbeats,
                        self._pod_id,
                    )
                    acquired = await self._try_acquire_leader(initial=False)
                    if acquired:
                        await self._promote()
                        return  # monitor loop ends; primary loops take over

            except Exception as exc:
                logger.error("Standby monitor error: %s", exc)

    # ── Leader election ───────────────────────────────────────────────────────

    async def _try_acquire_leader(self, initial: bool = False) -> bool:
        """
        Attempt to acquire the leader key via SET NX PX.

        Returns True if this pod is now the leader.
        """
        if self._redis is None:
            return False
        try:
            ttl_ms = int(_LEADER_TTL_S * 1000)
            result = await self._redis.set(
                _KEY_LEADER,
                self._pod_id,
                nx=True,  # only set if not exists
                px=ttl_ms,  # TTL in milliseconds
            )
            if result:
                logger.info(
                    "HotStandbyReplicator: acquired leader key pod=%s ttl=%.1fs",
                    self._pod_id,
                    _LEADER_TTL_S,
                )
                return True
            if initial:
                # Key exists — check if it's ours (restart scenario)
                current = await self._redis.get(_KEY_LEADER)
                if current and _decode(current) == self._pod_id:
                    # We already own it (e.g. pod restart with same hostname)
                    await self._redis.pexpire(_KEY_LEADER, ttl_ms)
                    return True
            return False
        except Exception as exc:
            logger.error("Leader acquisition failed: %s", exc)
            return False

    # ── Promotion / demotion ──────────────────────────────────────────────────

    async def _promote(self) -> None:
        """Promote this standby to primary."""
        logger.warning("HotStandbyReplicator: PROMOTING to PRIMARY pod=%s", self._pod_id)
        self._role = Role.PRIMARY
        self._stats.role = Role.PRIMARY
        self._stats.is_leader = True
        self._stats.promotions += 1
        self._stats.missed_heartbeats = 0

        if _PROM_OK:
            _prom_role.set(1)
            _prom_promotions.inc()

        # Restore state from Redis snapshot
        snapshot = await self._restore_state_snapshot()

        # Notify application layer
        if self._on_promote and snapshot:
            try:
                await self._on_promote(snapshot)
            except Exception as exc:
                logger.error("on_promote_callback failed: %s", exc)

        # Start primary loops
        await self._start_as_primary()

    async def _demote(self) -> None:
        """Demote this primary to standby (lost leader key)."""
        logger.critical("HotStandbyReplicator: DEMOTING to STANDBY pod=%s", self._pod_id)
        self._role = Role.STANDBY
        self._stats.role = Role.STANDBY
        self._stats.is_leader = False

        if _PROM_OK:
            _prom_role.set(0)

        if self._on_demote:
            try:
                await self._on_demote()
            except Exception as exc:
                logger.error("on_demote_callback failed: %s", exc)

        # Cancel primary tasks and start standby monitor
        for task in self._tasks:
            task.cancel()
        self._tasks.clear()
        await self._start_as_standby()

    # ── State snapshot I/O ────────────────────────────────────────────────────

    async def _write_state_snapshot(self) -> None:
        """Atomically write position/equity/fill state to Redis."""
        if self._redis is None:
            return
        version = self._stats.state_version + 1

        positions_json = json.dumps(self._positions, default=str)
        equity_json = json.dumps(
            {
                "equity": self._equity,
                "balance": self._balance,
                "version": version,
                "pod_id": self._pod_id,
                "captured_at": datetime.now(UTC).isoformat(),
            }
        )
        fills_json = json.dumps(self._fills[-_FILLS_RING_SIZE:], default=str)

        # Use a pipeline for atomic multi-key write
        pipe = self._redis.pipeline()
        pipe.setex(_KEY_POSITIONS, int(_LEADER_TTL_S * 10), positions_json)
        pipe.setex(_KEY_EQUITY, int(_LEADER_TTL_S * 10), equity_json)
        pipe.setex(_KEY_FILLS, int(_LEADER_TTL_S * 10), fills_json)
        pipe.set(_KEY_VERSION, str(version))
        await pipe.execute()

        self._stats.state_version = version
        if _PROM_OK:
            _prom_state_version.set(version)

    async def _restore_state_snapshot(self) -> StateSnapshot | None:
        """Read state snapshot from Redis. Returns None if unavailable."""
        if self._redis is None:
            return None
        try:
            pos_raw = await self._redis.get(_KEY_POSITIONS)
            equity_raw = await self._redis.get(_KEY_EQUITY)
            fills_raw = await self._redis.get(_KEY_FILLS)
            ver_raw = await self._redis.get(_KEY_VERSION)

            if not pos_raw or not equity_raw:
                logger.warning("HotStandbyReplicator: no state snapshot in Redis — starting with empty state")
                return None

            positions = json.loads(_decode(pos_raw))
            equity_data = json.loads(_decode(equity_raw))
            fills = json.loads(_decode(fills_raw)) if fills_raw else []
            version = int(_decode(ver_raw)) if ver_raw else 0

            snapshot = StateSnapshot(
                positions=positions,
                equity=float(equity_data.get("equity", 0.0)),
                balance=float(equity_data.get("balance", 0.0)),
                fills=fills,
                version=version,
                captured_at=equity_data.get("captured_at", ""),
                pod_id=equity_data.get("pod_id", "unknown"),
            )

            # Restore into local buffer so we start replicating from here
            self._positions = positions
            self._equity = snapshot.equity
            self._balance = snapshot.balance
            self._fills = fills
            self._stats.state_version = version

            logger.info(
                "HotStandbyReplicator: restored state version=%d positions=%d equity=%.2f from pod=%s captured_at=%s",
                version,
                len(positions),
                snapshot.equity,
                snapshot.pod_id,
                snapshot.captured_at,
            )
            return snapshot

        except Exception as exc:
            logger.error("State restore failed: %s", exc)
            return None

    # ── Diagnostics ───────────────────────────────────────────────────────────

    def stats(self) -> dict[str, Any]:
        """Return current replication statistics."""
        return {
            "role": self._role.value,
            "pod_id": self._pod_id,
            "is_leader": self._stats.is_leader,
            "state_version": self._stats.state_version,
            "last_heartbeat_ts": self._stats.last_heartbeat_ts,
            "missed_heartbeats": self._stats.missed_heartbeats,
            "promotions": self._stats.promotions,
            "last_replication_ms": round(self._stats.last_replication_ms, 2),
            "open_positions": len(self._positions),
            "fills_buffered": len(self._fills),
            "started_at": self._stats.started_at,
        }
