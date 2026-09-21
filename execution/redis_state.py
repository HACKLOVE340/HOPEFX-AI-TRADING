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

Keys used (without namespace):
    hopefx:orders:<order_id>   – JSON-encoded order dict (TTL = 7 days)
    hopefx:orders:index        – Redis set of active order IDs
    hopefx:positions:<symbol>  – JSON-encoded position dict (TTL = 7 days)
    hopefx:positions:index     – Redis set of open position symbols

Keys used (with namespace, e.g. "user-42"):
    hopefx:user-42:orders:<order_id>
    hopefx:user-42:orders:index
    hopefx:user-42:positions:<symbol>
    hopefx:user-42:positions:index

Namespacing isolates broker instances from each other — especially important
in test environments where multiple broker instances share the same Redis DB.
Each instance should be given a stable namespace (e.g. user_id) so its state
persists across restarts without bleeding into other instances.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any, Union

UTC = timezone.utc

logger = logging.getLogger(__name__)

_ORDER_TTL = 7 * 24 * 3600  # 7 days
_POSITION_TTL = 7 * 24 * 3600  # 7 days


def _key_prefixes(namespace: str) -> tuple[str, str, str, str]:
    """Return (order_prefix, position_prefix, order_index, position_index) for namespace.

    When *namespace* is an empty string the legacy un-namespaced layout is used::

        hopefx:orders:<id>
        hopefx:positions:<symbol>
        hopefx:orders:index
        hopefx:positions:index

    When *namespace* is non-empty (e.g. ``"user-42"`` or a UUID) the keys are
    scoped under that namespace to isolate this instance from all others::

        hopefx:user-42:orders:<id>
        hopefx:user-42:positions:<symbol>
        hopefx:user-42:orders:index
        hopefx:user-42:positions:index
    """
    base = f"hopefx:{namespace}:" if namespace else "hopefx:"
    return (
        f"{base}orders:",
        f"{base}positions:",
        f"{base}orders:index",
        f"{base}positions:index",
    )


def _balance_key(namespace: str) -> str:
    """Key holding the account's cash balance for *namespace*.

    Deliberately has no TTL, unlike orders and positions. Orders and positions
    expiring after a week is a bounded loss — they are working state. A balance
    that expires reverts the account to its starting capital, which is not a
    gap in the record but a wrong number that looks entirely plausible.
    """
    base = f"hopefx:{namespace}:" if namespace else "hopefx:"
    return f"{base}balance"


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


class RedisStateStore:
    """
    Thin wrapper around a Redis client for persisting trading state.

    Accepts both sync (redis.Redis) and async (redis.asyncio.Redis) clients.
    All methods are synchronous; use :class:`AsyncRedisStateStore` for async.

    Parameters
    ----------
    redis_client : sync Redis client
    namespace : str
        Optional namespace that scopes all Redis keys to this broker instance.
        Pass a stable identifier (e.g. user_id or broker name) for production
        deployments so state survives restarts.  Each test broker instance
        should use a unique namespace (e.g. a UUID) to prevent cross-test
        state pollution.  Empty string (default) preserves the legacy
        un-namespaced key layout.
    """

    def __init__(self, redis_client: Any, namespace: str = "") -> None:
        self._r = redis_client
        (
            self._order_prefix,
            self._position_prefix,
            self._order_index,
            self._position_index,
        ) = _key_prefixes(namespace)
        self._balance_key = _balance_key(namespace)

    # ------------------------------------------------------------------
    # Balance
    # ------------------------------------------------------------------

    def save_balance(self, balance: float) -> None:
        """Persist the account's cash balance.

        Positions were already durable; the balance they settle into was not.
        Every restart therefore replayed open positions against starting
        capital, so realised P&L — every closed trade the account had ever
        made — silently vanished and equity jumped to whatever the initial
        balance was. Nothing logged an error, because from the process's point
        of view a fresh account is a perfectly ordinary thing to be.
        """
        try:
            self._r.set(self._balance_key, json.dumps({"balance": float(balance), "_saved_at": _now_iso()}))
        except (OSError, ValueError, TypeError) as exc:
            logger.error("RedisStateStore.save_balance error: %s", exc)

    def load_balance(self) -> float | None:
        """Return the persisted balance, or None if this account has none yet.

        None means "never saved", which is different from 0.0 and must not be
        confused with it — a fresh namespace starts at its initial balance, a
        wiped-out account starts at zero.
        """
        try:
            raw = self._r.get(self._balance_key)
            if not raw:
                return None
            return float(json.loads(raw)["balance"])
        except (OSError, ValueError, TypeError, KeyError) as exc:
            logger.error("RedisStateStore.load_balance error: %s", exc)
            return None

    # ------------------------------------------------------------------
    # Orders
    # ------------------------------------------------------------------

    def save_order(self, order: dict[str, Any]) -> None:
        """Persist an order dict keyed by its ID."""
        order_id = str(order.get("id") or order.get("order_id", ""))
        if not order_id:
            logger.warning("RedisStateStore.save_order: order has no ID, skipping")
            return
        key = f"{self._order_prefix}{order_id}"
        payload = json.dumps({**order, "_saved_at": _now_iso()})
        try:
            self._r.set(key, payload, ex=_ORDER_TTL)
            self._r.sadd(self._order_index, order_id)
            logger.debug("RedisStateStore: saved order %s", order_id)
        except (OSError, ValueError) as exc:
            logger.error("RedisStateStore.save_order error: %s", exc)

    def remove_order(self, order_id: str) -> None:
        """Remove a closed/cancelled order from persistence."""
        try:
            self._r.delete(f"{self._order_prefix}{order_id}")
            self._r.srem(self._order_index, order_id)
            logger.debug("RedisStateStore: removed order %s", order_id)
        except (OSError, ValueError) as exc:
            logger.error("RedisStateStore.remove_order error: %s", exc)

    def load_orders(self) -> list[dict[str, Any]]:
        """Return all persisted open orders."""
        orders: list[dict[str, Any]] = []
        try:
            order_ids = self._r.smembers(self._order_index)
            for oid in order_ids:
                raw = self._r.get(
                    f"{self._order_prefix}{oid.decode() if isinstance(oid, bytes) else oid}",
                )
                if raw:
                    orders.append(json.loads(raw))
        except (OSError, ValueError) as exc:
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
        key = f"{self._position_prefix}{symbol}"
        payload = json.dumps({**position, "_saved_at": _now_iso()})
        try:
            self._r.set(key, payload, ex=_POSITION_TTL)
            self._r.sadd(self._position_index, symbol)
            logger.debug("RedisStateStore: saved position %s", symbol)
        except (OSError, ValueError) as exc:
            logger.error("RedisStateStore.save_position error: %s", exc)

    def remove_position(self, symbol: str) -> None:
        """Remove a closed position from persistence."""
        try:
            self._r.delete(f"{self._position_prefix}{symbol}")
            self._r.srem(self._position_index, symbol)
            logger.debug("RedisStateStore: removed position %s", symbol)
        except (OSError, ValueError) as exc:
            logger.error("RedisStateStore.remove_position error: %s", exc)

    def load_positions(self) -> list[dict[str, Any]]:
        """Return all persisted open positions."""
        positions: list[dict[str, Any]] = []
        try:
            symbols = self._r.smembers(self._position_index)
            for sym in symbols:
                raw = self._r.get(
                    f"{self._position_prefix}{sym.decode() if isinstance(sym, bytes) else sym}",
                )
                if raw:
                    positions.append(json.loads(raw))
        except (OSError, ValueError) as exc:
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

    Parameters
    ----------
    redis_client : async Redis client
    namespace : str
        Optional namespace to scope all Redis keys.  See :class:`RedisStateStore`
        for the full description of namespace semantics.
    """

    def __init__(self, redis_client: Any, namespace: str = "") -> None:
        self._r = redis_client
        (
            self._order_prefix,
            self._position_prefix,
            self._order_index,
            self._position_index,
        ) = _key_prefixes(namespace)
        self._balance_key = _balance_key(namespace)

    async def save_balance(self, balance: float) -> None:
        """See :meth:`RedisStateStore.save_balance`."""
        try:
            await self._r.set(self._balance_key, json.dumps({"balance": float(balance), "_saved_at": _now_iso()}))
        except (OSError, ValueError, TypeError) as exc:
            logger.error("AsyncRedisStateStore.save_balance error: %s", exc)

    async def load_balance(self) -> float | None:
        """See :meth:`RedisStateStore.load_balance`."""
        try:
            raw = await self._r.get(self._balance_key)
            if not raw:
                return None
            return float(json.loads(raw)["balance"])
        except (OSError, ValueError, TypeError, KeyError) as exc:
            logger.error("AsyncRedisStateStore.load_balance error: %s", exc)
            return None

    async def save_order(self, order: dict[str, Any]) -> None:
        order_id = str(order.get("id") or order.get("order_id", ""))
        if not order_id:
            logger.warning("AsyncRedisStateStore.save_order: order has no ID, skipping")
            return
        key = f"{self._order_prefix}{order_id}"
        payload = json.dumps({**order, "_saved_at": _now_iso()})
        try:
            await self._r.set(key, payload, ex=_ORDER_TTL)
            await self._r.sadd(self._order_index, order_id)
        except (OSError, ValueError) as exc:
            logger.error("AsyncRedisStateStore.save_order error: %s", exc)

    async def remove_order(self, order_id: str) -> None:
        try:
            await self._r.delete(f"{self._order_prefix}{order_id}")
            await self._r.srem(self._order_index, order_id)
        except (OSError, ValueError) as exc:
            logger.error("AsyncRedisStateStore.remove_order error: %s", exc)

    async def load_orders(self) -> list[dict[str, Any]]:
        orders: list[dict[str, Any]] = []
        try:
            order_ids = await self._r.smembers(self._order_index)
            for oid in order_ids:
                raw = await self._r.get(
                    f"{self._order_prefix}{oid.decode() if isinstance(oid, bytes) else oid}",
                )
                if raw:
                    orders.append(json.loads(raw))
        except (OSError, ValueError) as exc:
            logger.error("AsyncRedisStateStore.load_orders error: %s", exc)
        return orders

    async def save_position(self, position: dict[str, Any]) -> None:
        symbol = str(position.get("symbol", ""))
        if not symbol:
            logger.warning(
                "AsyncRedisStateStore.save_position: position has no symbol, skipping",
            )
            return
        key = f"{self._position_prefix}{symbol}"
        payload = json.dumps({**position, "_saved_at": _now_iso()})
        try:
            await self._r.set(key, payload, ex=_POSITION_TTL)
            await self._r.sadd(self._position_index, symbol)
        except (OSError, ValueError) as exc:
            logger.error("AsyncRedisStateStore.save_position error: %s", exc)

    async def remove_position(self, symbol: str) -> None:
        try:
            await self._r.delete(f"{self._position_prefix}{symbol}")
            await self._r.srem(self._position_index, symbol)
        except (OSError, ValueError) as exc:
            logger.error("AsyncRedisStateStore.remove_position error: %s", exc)

    async def load_positions(self) -> list[dict[str, Any]]:
        positions: list[dict[str, Any]] = []
        try:
            symbols = await self._r.smembers(self._position_index)
            for sym in symbols:
                raw = await self._r.get(
                    f"{self._position_prefix}{sym.decode() if isinstance(sym, bytes) else sym}",
                )
                if raw:
                    positions.append(json.loads(raw))
        except (OSError, ValueError) as exc:
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


def create_state_store(
    redis_client: Any,
    *,
    async_client: bool = False,
    namespace: str = "",
) -> Union[AsyncRedisStateStore, RedisStateStore]:
    """
    Factory that returns the appropriate store type.

    Args:
        redis_client: A sync or async Redis client instance.
        async_client: Pass ``True`` for ``redis.asyncio`` clients.
        namespace: Optional namespace string to scope all Redis keys.
            Each broker instance should pass a stable unique identifier so its
            keys do not collide with other broker instances on the same Redis DB.

    Returns:
        :class:`AsyncRedisStateStore` or :class:`RedisStateStore`.
    """
    if async_client:
        return AsyncRedisStateStore(redis_client, namespace=namespace)
    return RedisStateStore(redis_client, namespace=namespace)
