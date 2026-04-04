# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
Redis State Persistence for Orders and Positions

Persists open orders and positions to Redis so they can be restored after
a restart. Call :func:`save_order`, :func:`save_position` as state changes
occur, and :func:`load_state_on_boot` once at startup.

Keys used:
    hopefx:orders:<order_id>   – JSON-encoded order dict (TTL = 7 days)
    hopefx:orders:index        – Redis set of active order IDs
    hopefx:positions:<symbol>  – JSON-encoded position dict (TTL = 7 days)
    hopefx:positions:index     – Redis set of open position symbols
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
UTC = timezone.utc
from typing import Any

logger = logging.getLogger(__name__)

_ORDER_TTL = 7 * 24 * 3600  # 7 days
_POSITION_TTL = 7 * 24 * 3600  # 7 days
_ORDER_KEY_PREFIX = "hopefx:orders:"
_POSITION_KEY_PREFIX = "hopefx:positions:"
_ORDER_INDEX = "hopefx:orders:index"
_POSITION_INDEX = "hopefx:positions:index"


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


class RedisStateStore:
    """
    Thin wrapper around a Redis client for persisting trading state.

    Accepts both sync (redis.Redis) and async (redis.asyncio.Redis) clients.
    All methods are synchronous; use :class:`AsyncRedisStateStore` for async.
    """

    def __init__(self, redis_client) -> None:
        self._r = redis_client

    # ------------------------------------------------------------------
    # Orders
    # ------------------------------------------------------------------

    def save_order(self, order: dict[str, Any]) -> None:
        """Persist an order dict keyed by its ID."""
        order_id = str(order.get("id") or order.get("order_id", ""))
        if not order_id:
            logger.warning("RedisStateStore.save_order: order has no ID, skipping")
            return
        key = f"{_ORDER_KEY_PREFIX}{order_id}"
        payload = json.dumps({**order, "_saved_at": _now_iso()})
        try:
            self._r.set(key, payload, ex=_ORDER_TTL)
            self._r.sadd(_ORDER_INDEX, order_id)
            logger.debug("RedisStateStore: saved order %s", order_id)
        except (ConnectionError, OSError, ValueError) as exc:
            logger.error("RedisStateStore.save_order error: %s", exc)

    def remove_order(self, order_id: str) -> None:
        """Remove a closed/cancelled order from persistence."""
        try:
            self._r.delete(f"{_ORDER_KEY_PREFIX}{order_id}")
            self._r.srem(_ORDER_INDEX, order_id)
            logger.debug("RedisStateStore: removed order %s", order_id)
        except (ConnectionError, OSError, ValueError) as exc:
            logger.error("RedisStateStore.remove_order error: %s", exc)

    def load_orders(self) -> list[dict[str, Any]]:
        """Return all persisted open orders."""
        orders: list[dict[str, Any]] = []
        try:
            order_ids = self._r.smembers(_ORDER_INDEX)
            for oid in order_ids:
                raw = self._r.get(
                    f"{_ORDER_KEY_PREFIX}{oid.decode() if isinstance(oid, bytes) else oid}",
                )
                if raw:
                    orders.append(json.loads(raw))
        except (ConnectionError, OSError, ValueError) as exc:
            logger.error("RedisStateStore.load_orders error: %s", exc)
        return orders

    # ------------------------------------------------------------------
    # Positions
    # ------------------------------------------------------------------

    def save_position(self, position: dict[str, Any]) -> None:
        """Persist a position dict keyed by its symbol."""
        symbol = str(position.get("symbol", ""))
        if not symbol:
            logger.warning(
                "RedisStateStore.save_position: position has no symbol, skipping",
            )
            return
        key = f"{_POSITION_KEY_PREFIX}{symbol}"
        payload = json.dumps({**position, "_saved_at": _now_iso()})
        try:
            self._r.set(key, payload, ex=_POSITION_TTL)
            self._r.sadd(_POSITION_INDEX, symbol)
            logger.debug("RedisStateStore: saved position %s", symbol)
        except (ConnectionError, OSError, ValueError) as exc:
            logger.error("RedisStateStore.save_position error: %s", exc)

    def remove_position(self, symbol: str) -> None:
        """Remove a closed position from persistence."""
        try:
            self._r.delete(f"{_POSITION_KEY_PREFIX}{symbol}")
            self._r.srem(_POSITION_INDEX, symbol)
            logger.debug("RedisStateStore: removed position %s", symbol)
        except (ConnectionError, OSError, ValueError) as exc:
            logger.error("RedisStateStore.remove_position error: %s", exc)

    def load_positions(self) -> list[dict[str, Any]]:
        """Return all persisted open positions."""
        positions: list[dict[str, Any]] = []
        try:
            symbols = self._r.smembers(_POSITION_INDEX)
            for sym in symbols:
                raw = self._r.get(
                    f"{_POSITION_KEY_PREFIX}{sym.decode() if isinstance(sym, bytes) else sym}",
                )
                if raw:
                    positions.append(json.loads(raw))
        except (ConnectionError, OSError, ValueError) as exc:
            logger.error("RedisStateStore.load_positions error: %s", exc)
        return positions

    # ------------------------------------------------------------------
    # Boot restore
    # ------------------------------------------------------------------

    def load_state_on_boot(self) -> dict[str, list[dict[str, Any]]]:
        """
        Load all persisted orders and positions at startup.

        Returns:
            dict with keys ``"orders"`` and ``"positions"``.
        """
        orders = self.load_orders()
        positions = self.load_positions()
        if orders:
            logger.info(
                "RedisStateStore: restored %d open order(s) from Redis",
                len(orders),
            )
        if positions:
            logger.info(
                "RedisStateStore: restored %d open position(s) from Redis",
                len(positions),
            )
        return {"orders": orders, "positions": positions}


class AsyncRedisStateStore:
    """
    Async version of :class:`RedisStateStore` for use with ``redis.asyncio``.
    """

    def __init__(self, redis_client) -> None:
        self._r = redis_client

    async def save_order(self, order: dict[str, Any]) -> None:
        order_id = str(order.get("id") or order.get("order_id", ""))
        if not order_id:
            logger.warning("AsyncRedisStateStore.save_order: order has no ID, skipping")
            return
        key = f"{_ORDER_KEY_PREFIX}{order_id}"
        payload = json.dumps({**order, "_saved_at": _now_iso()})
        try:
            await self._r.set(key, payload, ex=_ORDER_TTL)
            await self._r.sadd(_ORDER_INDEX, order_id)
        except (ConnectionError, OSError, ValueError) as exc:
            logger.error("AsyncRedisStateStore.save_order error: %s", exc)

    async def remove_order(self, order_id: str) -> None:
        try:
            await self._r.delete(f"{_ORDER_KEY_PREFIX}{order_id}")
            await self._r.srem(_ORDER_INDEX, order_id)
        except (ConnectionError, OSError, ValueError) as exc:
            logger.error("AsyncRedisStateStore.remove_order error: %s", exc)

    async def load_orders(self) -> list[dict[str, Any]]:
        orders: list[dict[str, Any]] = []
        try:
            order_ids = await self._r.smembers(_ORDER_INDEX)
            for oid in order_ids:
                raw = await self._r.get(
                    f"{_ORDER_KEY_PREFIX}{oid.decode() if isinstance(oid, bytes) else oid}",
                )
                if raw:
                    orders.append(json.loads(raw))
        except (ConnectionError, OSError, ValueError) as exc:
            logger.error("AsyncRedisStateStore.load_orders error: %s", exc)
        return orders

    async def save_position(self, position: dict[str, Any]) -> None:
        symbol = str(position.get("symbol", ""))
        if not symbol:
            logger.warning(
                "AsyncRedisStateStore.save_position: position has no symbol, skipping",
            )
            return
        key = f"{_POSITION_KEY_PREFIX}{symbol}"
        payload = json.dumps({**position, "_saved_at": _now_iso()})
        try:
            await self._r.set(key, payload, ex=_POSITION_TTL)
            await self._r.sadd(_POSITION_INDEX, symbol)
        except (ConnectionError, OSError, ValueError) as exc:
            logger.error("AsyncRedisStateStore.save_position error: %s", exc)

    async def remove_position(self, symbol: str) -> None:
        try:
            await self._r.delete(f"{_POSITION_KEY_PREFIX}{symbol}")
            await self._r.srem(_POSITION_INDEX, symbol)
        except (ConnectionError, OSError, ValueError) as exc:
            logger.error("AsyncRedisStateStore.remove_position error: %s", exc)

    async def load_positions(self) -> list[dict[str, Any]]:
        positions: list[dict[str, Any]] = []
        try:
            symbols = await self._r.smembers(_POSITION_INDEX)
            for sym in symbols:
                raw = await self._r.get(
                    f"{_POSITION_KEY_PREFIX}{sym.decode() if isinstance(sym, bytes) else sym}",
                )
                if raw:
                    positions.append(json.loads(raw))
        except (ConnectionError, OSError, ValueError) as exc:
            logger.error("AsyncRedisStateStore.load_positions error: %s", exc)
        return positions

    async def load_state_on_boot(self) -> dict[str, list[dict[str, Any]]]:
        """Load all persisted orders and positions at startup."""
        orders = await self.load_orders()
        positions = await self.load_positions()
        if orders:
            logger.info(
                "AsyncRedisStateStore: restored %d open order(s) from Redis",
                len(orders),
            )
        if positions:
            logger.info(
                "AsyncRedisStateStore: restored %d open position(s) from Redis",
                len(positions),
            )
        return {"orders": orders, "positions": positions}


def create_state_store(redis_client, *, async_client: bool = False):
    """
    Factory that returns the appropriate store type.

    Args:
        redis_client: A sync or async Redis client instance.
        async_client: Pass ``True`` for ``redis.asyncio`` clients.

    Returns:
        :class:`AsyncRedisStateStore` or :class:`RedisStateStore`.
    """
    if async_client:
        return AsyncRedisStateStore(redis_client)
    return RedisStateStore(redis_client)
