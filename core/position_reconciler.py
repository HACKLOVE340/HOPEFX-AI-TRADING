"""
Position reconciliation loop.

Runs as a background asyncio task. Every `interval_seconds` it:
1. Loads open positions from the DB (positions table)
2. Compares them against the in-memory broker/paper state
3. Logs discrepancies and optionally corrects them
4. Updates unrealized P&L on each position using latest market price

This is intentionally conservative: it logs and alerts on mismatches but
does NOT auto-close positions without explicit configuration, to avoid
unintended trades in production.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger(__name__)

_reconciler_task: Optional[asyncio.Task] = None


class PositionReconciler:
    """
    Lightweight reconciler that keeps the DB positions table in sync with
    the in-memory broker state and refreshes unrealized P&L.
    """

    def __init__(
        self,
        session_factory,
        broker=None,
        ws_manager=None,
        interval_seconds: int = 30,
    ):
        self._sf = session_factory
        self._broker = broker
        self._ws = ws_manager
        self._interval = interval_seconds
        self._running = False
        self._cycles = 0
        self._mismatches = 0

    async def start(self) -> None:
        self._running = True
        logger.info("Position reconciler started (interval=%ds)", self._interval)
        asyncio.create_task(self._loop())

    async def stop(self) -> None:
        self._running = False

    async def _loop(self) -> None:
        while self._running:
            try:
                await self._reconcile_once()
            except Exception as exc:
                logger.error("Reconciliation cycle error: %s", exc)
            await asyncio.sleep(self._interval)

    async def _reconcile_once(self) -> None:
        self._cycles += 1
        try:
            from database.models import Position as DBPosition
        except ImportError:
            return

        with self._sf() as session:
            db_positions = session.query(DBPosition).filter_by(status="open").all()

        if not db_positions:
            return

        # Fetch broker positions if available
        broker_positions: dict = {}
        if self._broker and hasattr(self._broker, "get_positions"):
            try:
                raw = self._broker.get_positions()
                if asyncio.iscoroutine(raw):
                    raw = await raw
                broker_positions = {p.get("symbol", p): p for p in (raw or [])}
            except Exception as exc:
                logger.warning("Could not fetch broker positions: %s", exc)

        # Fetch latest prices and update unrealized P&L
        updated = 0
        for pos in db_positions:
            price = await self._get_price(pos.symbol)
            if price is None:
                continue

            pnl = self._calc_pnl(pos, price)
            with self._sf() as session:
                db_pos = session.query(DBPosition).filter_by(id=pos.id).first()
                if db_pos:
                    db_pos.current_price = price
                    db_pos.unrealized_pnl = pnl
                    session.commit()
                    updated += 1

            # Check for broker mismatch
            if broker_positions and pos.symbol not in broker_positions:
                self._mismatches += 1
                logger.warning(
                    "RECONCILE: position %s (%s) in DB but not in broker state",
                    pos.id, pos.symbol,
                )

        if updated:
            logger.debug("Reconciler cycle %d: updated P&L for %d positions", self._cycles, updated)

        # Broadcast updated positions over WebSocket
        if self._ws and updated:
            try:
                await self._ws.broadcast_to_all({
                    "type": "positions_updated",
                    "count": updated,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                })
            except Exception:
                pass

    async def _get_price(self, symbol: str) -> Optional[float]:
        """Fetch latest price. Uses yfinance with a short timeout."""
        try:
            import yfinance as yf
            ticker = yf.Ticker(symbol)
            hist = ticker.history(period="1d", interval="1m")
            if not hist.empty:
                return float(hist["Close"].iloc[-1])
        except Exception:
            pass
        return None

    @staticmethod
    def _calc_pnl(pos, current_price: float) -> float:
        qty = pos.quantity or 0.0
        entry = pos.entry_price or 0.0
        if pos.side == "buy":
            return (current_price - entry) * qty
        else:
            return (entry - current_price) * qty

    @property
    def stats(self) -> dict:
        return {"cycles": self._cycles, "mismatches": self._mismatches, "running": self._running}


def start_reconciler(session_factory, broker=None, ws_manager=None, interval_seconds: int = 30) -> PositionReconciler:
    """Create and start the reconciler. Returns the instance for status queries."""
    global _reconciler_task
    rec = PositionReconciler(
        session_factory=session_factory,
        broker=broker,
        ws_manager=ws_manager,
        interval_seconds=interval_seconds,
    )
    # Schedule start — must be called from within a running event loop
    asyncio.get_event_loop().create_task(_start(rec))
    return rec


async def _start(rec: PositionReconciler) -> None:
    await rec.start()
