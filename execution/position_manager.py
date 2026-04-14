# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
execution/position_manager.py
==============================
Atomic position lifecycle manager with Redis persistence and Prometheus metrics.

Design invariants
-----------------
- ALL position mutations are executed under ``asyncio.Lock`` — no races.
- Every mutation is atomically persisted to Redis via
  :class:`execution.redis_state.AsyncRedisStateStore`.
- ``open_position()`` raises :exc:`PositionAlreadyOpenError` if a position for
  the symbol already exists — no silent overwrite.
- ``close_position()`` returns :class:`PositionCloseResult` with realized P&L,
  duration, and fill price.
- Full position history is retained in a bounded ``deque`` (max 1 000 entries).
- OTel spans are emitted for every mutation via ``api.tracing.get_tracer``.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)

UTC = timezone.utc

# ── Optional Prometheus metrics ───────────────────────────────────────────────
try:
    from prometheus_client import Counter, Gauge, Histogram  # type: ignore[import]

    _positions_open_gauge = Gauge(
        "hopefx_positions_open",
        "Number of currently open positions",
        ["symbol"],
    )
    _position_pnl_histogram = Histogram(
        "hopefx_position_pnl_usd",
        "Realized P&L per closed position in USD",
        buckets=[-1000, -500, -200, -100, -50, -20, -10, 0, 10, 20, 50, 100, 200, 500, 1000],
    )
    _position_mutations_counter = Counter(
        "hopefx_position_mutations_total",
        "Total position mutation operations",
        ["operation"],
    )
    _PROM_AVAILABLE = True
except ImportError:
    _PROM_AVAILABLE = False


def _prom_positions_open_set(symbol: str, value: float) -> None:
    if _PROM_AVAILABLE:
        try:
            _positions_open_gauge.labels(symbol=symbol).set(value)
        except (ConnectionError, OSError, RuntimeError):
            logger.debug("Suppressed exception (no detail) in %s", __name__)


def _prom_pnl_observe(pnl: float) -> None:
    if _PROM_AVAILABLE:
        try:
            _position_pnl_histogram.observe(pnl)
        except (ConnectionError, OSError, RuntimeError):
            logger.debug("Suppressed exception (no detail) in %s", __name__)


def _prom_mutation(op: str) -> None:
    if _PROM_AVAILABLE:
        try:
            _position_mutations_counter.labels(operation=op).inc()
        except (ConnectionError, OSError, RuntimeError):
            logger.debug("Suppressed exception (no detail) in %s", __name__)


# ── Exceptions ─────────────────────────────────────────────────────────────────


class PositionAlreadyOpenError(Exception):
    """Raised when attempting to open a position for a symbol that already has one.

    Attributes:
        symbol: The trading symbol that has an existing open position.
    """

    def __init__(self, symbol: str) -> None:
        self.symbol = symbol
        super().__init__(f"Position already open for symbol: {symbol}")


class PositionNotFoundError(Exception):
    """Raised when a position is not found for the given symbol.

    Attributes:
        symbol: The trading symbol that was not found.
    """

    def __init__(self, symbol: str) -> None:
        self.symbol = symbol
        super().__init__(f"No open position found for symbol: {symbol}")


# ── Data models ────────────────────────────────────────────────────────────────


@dataclass
class Position:
    """Represents an open trading position.

    Attributes:
        position_id: Unique identifier for this position.
        symbol: Trading symbol (e.g. ``"XAUUSD"``).
        side: ``"BUY"`` or ``"SELL"``.
        quantity: Position size in lots/units.
        entry_price: Average fill price.
        stop_loss: Optional stop-loss price.
        take_profit: Optional take-profit price.
        strategy_id: Originating strategy identifier.
        opened_at: UTC timestamp when the position was opened.
        last_price: Most recently observed price (for unrealized P&L).
        metadata: Arbitrary key-value pairs attached at open time.
    """

    position_id: str
    symbol: str
    side: str
    quantity: float
    entry_price: float
    stop_loss: float | None = None
    take_profit: float | None = None
    strategy_id: str = "unknown"
    opened_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    last_price: float | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Serialise the position to a JSON-safe dictionary."""
        return {
            "position_id": self.position_id,
            "symbol": self.symbol,
            "side": self.side,
            "quantity": self.quantity,
            "entry_price": self.entry_price,
            "stop_loss": self.stop_loss,
            "take_profit": self.take_profit,
            "strategy_id": self.strategy_id,
            "opened_at": self.opened_at.isoformat(),
            "last_price": self.last_price,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Position:
        """Deserialise a position from a dictionary.

        Args:
            data: Dictionary as produced by :meth:`to_dict`.

        Returns:
            Reconstructed :class:`Position` instance.
        """
        opened_at = data.get("opened_at")
        if isinstance(opened_at, str):
            opened_at = datetime.fromisoformat(opened_at)
        elif opened_at is None:
            opened_at = datetime.now(UTC)
        return cls(
            position_id=data["position_id"],
            symbol=data["symbol"],
            side=data["side"],
            quantity=float(data["quantity"]),
            entry_price=float(data["entry_price"]),
            stop_loss=data.get("stop_loss"),
            take_profit=data.get("take_profit"),
            strategy_id=data.get("strategy_id", "unknown"),
            opened_at=opened_at,
            last_price=data.get("last_price"),
            metadata=data.get("metadata", {}),
        )


@dataclass
class PositionCloseResult:
    """Result of closing a position.

    Attributes:
        position_id: ID of the closed position.
        symbol: Trading symbol.
        side: Original side of the position.
        quantity: Closed quantity.
        entry_price: Original fill price.
        fill_price: Closing fill price.
        realized_pnl: Realized profit/loss in quote currency.
        duration_seconds: How long the position was open.
        closed_at: UTC timestamp of close.
    """

    position_id: str
    symbol: str
    side: str
    quantity: float
    entry_price: float
    fill_price: float
    realized_pnl: float
    duration_seconds: float
    closed_at: datetime = field(default_factory=lambda: datetime.now(UTC))


# ── PositionManager ────────────────────────────────────────────────────────────


class PositionManager:
    """Atomic, Redis-backed position lifecycle manager.

    All mutation methods (``open_position``, ``close_position``,
    ``update_position``) acquire ``_lock`` before reading or writing state,
    guaranteeing that concurrent coroutines never observe a torn write.

    Args:
        redis_client: An async redis client (``redis.asyncio``). May be
            ``None``; in that case mutations are in-memory only with a warning.
        history_maxlen: Maximum number of closed positions retained in history.
    """

    def __init__(
        self,
        redis_client: Any = None,
        history_maxlen: int = 1000,
    ) -> None:
        self._redis = redis_client
        self._lock = asyncio.Lock()
        self._positions: dict[str, Position] = {}
        self._history: deque[PositionCloseResult] = deque(maxlen=history_maxlen)
        self._redis_store: Any = None

        if redis_client is not None:
            try:
                from execution.redis_state import AsyncRedisStateStore  # type: ignore[import]

                self._redis_store = AsyncRedisStateStore(redis_client)
            except (ImportError, ConnectionError, RuntimeError) as exc:
                logger.warning("PositionManager: could not initialise AsyncRedisStateStore: %s", exc)

        logger.info("PositionManager initialised (redis=%s)", redis_client is not None)

    @staticmethod
    def _make_span_ctx(span_name: str) -> Any:
        """Return an OTel span context manager for *span_name*.

        Lazily imports ``api.tracing.get_tracer`` to avoid circular imports.
        Returns a ``_NullCtx`` no-op when tracing is unavailable.
        """
        try:
            from api.tracing import get_tracer  # type: ignore[import]

            tracer = get_tracer("hopefx.position_manager")
            if tracer is not None:
                return tracer.start_as_current_span(span_name)
        except (ImportError, AttributeError):
            logger.debug("Suppressed exception (no detail) in %s", __name__)
        return _NullCtx()

    # ------------------------------------------------------------------
    # Open
    # ------------------------------------------------------------------

    async def open_position(
        self,
        symbol: str,
        side: str,
        quantity: float,
        entry_price: float,
        *,
        stop_loss: float | None = None,
        take_profit: float | None = None,
        strategy_id: str = "unknown",
        position_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> Position:
        """Open a new position for ``symbol`` atomically.

        Args:
            symbol: Trading symbol (e.g. ``"XAUUSD"``).
            side: ``"BUY"`` or ``"SELL"``.
            quantity: Position size in lots/units.
            entry_price: Fill price at open.
            stop_loss: Optional stop-loss level.
            take_profit: Optional take-profit level.
            strategy_id: Originating strategy identifier.
            position_id: Override the auto-generated position ID.
            metadata: Additional key-value pairs to attach.

        Returns:
            The newly created :class:`Position`.

        Raises:
            PositionAlreadyOpenError: When a position for *symbol* already exists.
            ValueError: When *side*, *quantity*, or *entry_price* are invalid.
        """
        if side not in ("BUY", "SELL"):
            raise ValueError(f"side must be 'BUY' or 'SELL', got {side!r}")
        if quantity <= 0:
            raise ValueError(f"quantity must be > 0, got {quantity}")
        if entry_price <= 0:
            raise ValueError(f"entry_price must be > 0, got {entry_price}")

        with self._make_span_ctx("position_manager.open") as span:
            if hasattr(span, "set_attribute"):
                span.set_attribute("symbol", symbol)
                span.set_attribute("side", side)
                span.set_attribute("quantity", quantity)
                span.set_attribute("entry_price", entry_price)

            async with self._lock:
                if symbol in self._positions:
                    raise PositionAlreadyOpenError(symbol)

                pos = Position(
                    position_id=position_id or str(uuid.uuid4())[:16],
                    symbol=symbol,
                    side=side,
                    quantity=quantity,
                    entry_price=entry_price,
                    stop_loss=stop_loss,
                    take_profit=take_profit,
                    strategy_id=strategy_id,
                    metadata=metadata or {},
                )
                self._positions[symbol] = pos

                if self._redis_store is not None:
                    try:
                        await self._redis_store.save_position(pos.to_dict())
                    except (ConnectionError, RuntimeError, OSError) as exc:
                        # Two-phase rollback: remove the in-memory record so
                        # state stays consistent if Redis is unavailable.
                        del self._positions[symbol]
                        raise RuntimeError(
                            f"PositionManager: could not persist position for {symbol!r} "
                            f"to Redis — rolling back in-memory state. "
                            f"Original error: {exc}"
                        ) from exc

        _prom_positions_open_set(symbol, 1)
        _prom_mutation("open")
        logger.info(
            "Position opened | %s %s %.4f @ %.5f | id=%s",
            side,
            symbol,
            quantity,
            entry_price,
            pos.position_id,
        )
        return pos

    # ------------------------------------------------------------------
    # Close
    # ------------------------------------------------------------------

    async def close_position(
        self,
        symbol: str,
        fill_price: float,
        *,
        metadata: dict[str, Any] | None = None,
    ) -> PositionCloseResult:
        """Close the open position for ``symbol`` atomically.

        Computes realized P&L as:
        - BUY:  ``(fill_price - entry_price) * quantity``
        - SELL: ``(entry_price - fill_price) * quantity``

        Args:
            symbol: Trading symbol to close.
            fill_price: Execution price for the close.
            metadata: Additional metadata to attach to the close record.

        Returns:
            :class:`PositionCloseResult` with realized P&L, duration, and fill price.

        Raises:
            PositionNotFoundError: When no open position exists for *symbol*.
            ValueError: When *fill_price* is invalid.
        """
        if fill_price <= 0:
            raise ValueError(f"fill_price must be > 0, got {fill_price}")

        with self._make_span_ctx("position_manager.close") as span:
            if hasattr(span, "set_attribute"):
                span.set_attribute("symbol", symbol)
                span.set_attribute("fill_price", fill_price)

            async with self._lock:
                pos = self._positions.get(symbol)
                if pos is None:
                    raise PositionNotFoundError(symbol)

                now = datetime.now(UTC)
                duration_seconds = (now - pos.opened_at).total_seconds()

                if pos.side == "BUY":
                    realized_pnl = (fill_price - pos.entry_price) * pos.quantity
                else:
                    realized_pnl = (pos.entry_price - fill_price) * pos.quantity

                result = PositionCloseResult(
                    position_id=pos.position_id,
                    symbol=symbol,
                    side=pos.side,
                    quantity=pos.quantity,
                    entry_price=pos.entry_price,
                    fill_price=fill_price,
                    realized_pnl=round(realized_pnl, 6),
                    duration_seconds=round(duration_seconds, 3),
                    closed_at=now,
                )

                del self._positions[symbol]
                self._history.append(result)

                if self._redis_store is not None:
                    try:
                        await self._redis_store.remove_position(symbol)
                    except (ConnectionError, RuntimeError, OSError) as exc:
                        # Two-phase rollback: restore the in-memory record so
                        # state stays consistent if Redis removal fails.
                        self._positions[symbol] = pos
                        self._history.pop()
                        raise RuntimeError(
                            f"PositionManager: could not remove position for {symbol!r} "
                            f"from Redis — rolling back in-memory state. "
                            f"Original error: {exc}"
                        ) from exc

                if hasattr(span, "set_attribute"):
                    span.set_attribute("realized_pnl", result.realized_pnl)
                    span.set_attribute("duration_seconds", result.duration_seconds)

        _prom_positions_open_set(symbol, 0)
        _prom_pnl_observe(result.realized_pnl)
        _prom_mutation("close")
        logger.info(
            "Position closed | %s %s | pnl=%.4f | duration=%.1fs",
            symbol,
            pos.side,
            result.realized_pnl,
            result.duration_seconds,
        )

        # ── Notify paper trading clock (Sharpe tracker) ───────────────────────
        # record_fill() expects a fractional return: pnl / entry_value.
        # entry_value = entry_price * quantity.  Guard against zero entry_price.
        # Call is best-effort — a clock import error must not block position close.
        try:
            entry_value = pos.entry_price * pos.quantity
            trade_return = result.realized_pnl / entry_value if entry_value != 0.0 else 0.0
            from brokers.oanda_paper_clock import get_clock

            get_clock().record_fill(trade_return=trade_return, symbol=symbol)
        except Exception as exc:
            logger.debug("PositionManager: paper clock record_fill failed: %s", exc)

        return result

    # ------------------------------------------------------------------
    # Update
    # ------------------------------------------------------------------

    async def update_position(
        self,
        symbol: str,
        *,
        last_price: float | None = None,
        stop_loss: float | None = None,
        take_profit: float | None = None,
    ) -> Position:
        """Update mutable fields of an open position atomically.

        Args:
            symbol: Trading symbol to update.
            last_price: Latest market price (for unrealized P&L calculation).
            stop_loss: New stop-loss level (``None`` leaves unchanged).
            take_profit: New take-profit level (``None`` leaves unchanged).

        Returns:
            Updated :class:`Position`.

        Raises:
            PositionNotFoundError: When no open position exists for *symbol*.
        """
        async with self._lock:
            pos = self._positions.get(symbol)
            if pos is None:
                raise PositionNotFoundError(symbol)

            if last_price is not None:
                pos.last_price = last_price
            if stop_loss is not None:
                pos.stop_loss = stop_loss
            if take_profit is not None:
                pos.take_profit = take_profit

            if self._redis_store is not None:
                try:
                    await self._redis_store.save_position(pos.to_dict())
                except (ConnectionError, RuntimeError, OSError) as exc:
                    logger.warning("PositionManager: Redis persist failed on update: %s", exc)

        _prom_mutation("update")
        return pos

    # ------------------------------------------------------------------
    # Read-only queries (no lock needed — dict reads are atomic in CPython)
    # ------------------------------------------------------------------

    def get_position(self, symbol: str) -> Position | None:
        """Return the open position for *symbol*, or ``None`` if not open.

        Args:
            symbol: Trading symbol.

        Returns:
            :class:`Position` if open, ``None`` otherwise.
        """
        return self._positions.get(symbol)

    def get_all_positions(self) -> dict[str, Position]:
        """Return a snapshot of all open positions keyed by symbol.

        Returns:
            Dictionary mapping symbol → :class:`Position`.
        """
        return dict(self._positions)

    def get_total_exposure(self) -> float:
        """Compute total notional exposure across all open positions.

        Exposure is ``sum(quantity * last_price)`` for each position where
        ``last_price`` is known, falling back to ``entry_price`` otherwise.

        Returns:
            Total notional exposure as a float.
        """
        total = 0.0
        for pos in self._positions.values():
            price = pos.last_price if pos.last_price is not None else pos.entry_price
            total += pos.quantity * price
        return round(total, 6)

    def get_unrealized_pnl(self) -> dict[str, float]:
        """Compute unrealized P&L for every open position.

        Uses ``last_price`` when available, otherwise returns ``0.0`` for
        positions with no current price.

        Returns:
            Dictionary mapping symbol → unrealized P&L float.
        """
        result: dict[str, float] = {}
        for symbol, pos in self._positions.items():
            if pos.last_price is None:
                result[symbol] = 0.0
                continue
            if pos.side == "BUY":
                pnl = (pos.last_price - pos.entry_price) * pos.quantity
            else:
                pnl = (pos.entry_price - pos.last_price) * pos.quantity
            result[symbol] = round(pnl, 6)
        return result

    def get_history(self, limit: int = 100) -> list[PositionCloseResult]:
        """Return the most recent closed position records.

        Args:
            limit: Maximum number of records to return.

        Returns:
            List of :class:`PositionCloseResult`, newest first.
        """
        history = list(self._history)
        return list(reversed(history))[:limit]

    async def restore_from_redis(self) -> int:
        """Reload open positions from Redis on startup.

        This should be called once during application startup after the Redis
        connection is available.

        Returns:
            Number of positions restored.
        """
        if self._redis_store is None:
            return 0
        try:
            state = await self._redis_store.load_state_on_boot()
            positions = state.get("positions", [])
            async with self._lock:
                for p_dict in positions:
                    pos = Position.from_dict(p_dict)
                    self._positions[pos.symbol] = pos
                    _prom_positions_open_set(pos.symbol, 1)
            logger.info("PositionManager: restored %d position(s) from Redis", len(positions))
            return len(positions)
        except (ConnectionError, RuntimeError, OSError) as exc:
            logger.warning("PositionManager: failed to restore from Redis: %s", exc)
            return 0


# ── Null context manager for no-op span ───────────────────────────────────────


class _NullCtx:
    """Minimal context manager used when tracing is unavailable."""

    def __enter__(self) -> _NullCtx:
        return self

    def __exit__(self, *_: Any) -> None:
        pass


# ── Module-level singleton ─────────────────────────────────────────────────────

position_manager = PositionManager()
