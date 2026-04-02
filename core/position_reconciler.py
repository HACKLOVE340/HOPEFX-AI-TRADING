# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
Position reconciliation loop.

Runs as a background asyncio task. Every `interval_seconds` (default: 10) it:
1. Loads open positions from the DB (positions table)
2. Compares them against the in-memory broker/paper state
3. Logs discrepancies and alerts on gaps (RECONCILE_GAP)
4. Updates unrealized P&L on each position using latest market price

This is intentionally conservative: it logs and alerts on mismatches but
does NOT auto-close positions without explicit configuration, to avoid
unintended trades in production.
"""

from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, timezone

UTC = timezone.utc

logger = logging.getLogger(__name__)

_reconciler_task: asyncio.Task | None = None

# How many consecutive mismatches for the same symbol before escalating to ERROR
_MISMATCH_ALERT_THRESHOLD = 3

# Drift thresholds — breach either to trigger RiskHaltEvent
_DRIFT_QTY_THRESHOLD = float(os.getenv("RECONCILER_DRIFT_QTY", "1.0"))  # units
_DRIFT_VALUE_THRESHOLD = float(os.getenv("RECONCILER_DRIFT_VALUE", "100.0"))  # USD


class PositionReconciler:
    """
    Lightweight reconciler that keeps the DB positions table in sync with
    the in-memory broker state and refreshes unrealized P&L.

    Polls every ``interval_seconds`` (default 10 s per the problem spec).
    Emits a WARNING for each mismatch and escalates to ERROR after
    ``_MISMATCH_ALERT_THRESHOLD`` consecutive mismatches for the same symbol.
    """

    def __init__(
        self,
        session_factory,
        broker=None,
        ws_manager=None,
        alert_engine=None,
        interval_seconds: int = 10,
        drift_qty_threshold: float = _DRIFT_QTY_THRESHOLD,
        drift_value_threshold: float = _DRIFT_VALUE_THRESHOLD,
    ):
        self._sf = session_factory
        self._broker = broker
        self._ws = ws_manager
        self._alert_engine = alert_engine
        self._interval = interval_seconds
        self._drift_qty = drift_qty_threshold
        self._drift_value = drift_value_threshold
        self._running = False
        self._cycles = 0
        self._mismatches = 0
        # Track consecutive mismatches per symbol for gap alerting
        self._consecutive_mismatches: dict[str, int] = {}
        # Track symbols already halted this session to avoid repeat halts
        self._halted_symbols: set[str] = set()

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

            # ── Drift detection ───────────────────────────────────────────────
            if broker_positions:
                if pos.symbol not in broker_positions:
                    self._mismatches += 1
                    self._consecutive_mismatches[pos.symbol] = self._consecutive_mismatches.get(pos.symbol, 0) + 1
                    count = self._consecutive_mismatches[pos.symbol]
                    if count >= _MISMATCH_ALERT_THRESHOLD:
                        logger.error(
                            "RECONCILE_GAP: position %s (%s) missing from broker "
                            "for %d consecutive cycles — manual review required",
                            pos.id,
                            pos.symbol,
                            count,
                        )
                    else:
                        logger.warning(
                            "RECONCILE: position %s (%s) in DB but not in broker state",
                            pos.id,
                            pos.symbol,
                        )
                else:
                    # Symbol present — check quantity and value drift
                    self._consecutive_mismatches.pop(pos.symbol, None)
                    broker_pos = broker_positions[pos.symbol]
                    broker_qty = float(
                        broker_pos.get("quantity", broker_pos.get("qty", 0))
                        if isinstance(broker_pos, dict)
                        else getattr(broker_pos, "quantity", 0),
                    )
                    db_qty = float(pos.quantity or 0)
                    qty_diff = abs(db_qty - broker_qty)

                    current_price_for_drift = price or 0.0
                    db_value = db_qty * current_price_for_drift
                    broker_value = broker_qty * current_price_for_drift
                    value_diff = abs(db_value - broker_value)

                    if qty_diff > self._drift_qty or value_diff > self._drift_value:
                        await self._trigger_drift_halt(
                            symbol=pos.symbol,
                            db_qty=db_qty,
                            broker_qty=broker_qty,
                            qty_diff=qty_diff,
                            db_value=db_value,
                            broker_value=broker_value,
                            value_diff=value_diff,
                        )

        if updated:
            logger.debug(
                "Reconciler cycle %d: updated P&L for %d positions",
                self._cycles,
                updated,
            )

        # Broadcast updated positions over WebSocket
        if self._ws and updated:
            try:
                await self._ws.broadcast_to_all(
                    {
                        "type": "positions_updated",
                        "count": updated,
                        "timestamp": datetime.now(UTC).isoformat(),
                    },
                )
            except Exception as _exc:
                logger.debug("Suppressed exception: %s", _exc)

    async def _trigger_drift_halt(
        self,
        symbol: str,
        db_qty: float,
        broker_qty: float,
        qty_diff: float,
        db_value: float,
        broker_value: float,
        value_diff: float,
    ) -> None:
        """
        Trigger a RiskHaltEvent and notify via alert engine when broker
        positions diverge from DB positions beyond configured thresholds.
        """
        if symbol in self._halted_symbols:
            return  # already halted this session — don't spam

        self._halted_symbols.add(symbol)
        reason = (
            f"Position drift on {symbol}: "
            f"DB qty={db_qty:.4f} broker qty={broker_qty:.4f} "
            f"(diff={qty_diff:.4f} units / ${value_diff:.2f})"
        )
        logger.error("POSITION DRIFT HALT: %s", reason)

        # Publish typed RiskHaltEvent
        try:
            from events.typed_events import (
                EventEnvelope,
                PositionDriftEvent,
                RiskHaltEvent,
                publish_sync,
            )

            drift_event = PositionDriftEvent(
                symbol=symbol,
                db_quantity=db_qty,
                broker_quantity=broker_qty,
                quantity_diff=qty_diff,
                db_value=db_value,
                broker_value=broker_value,
                value_diff=value_diff,
            )
            publish_sync(
                EventEnvelope.wrap(
                    source="position_reconciler",
                    payload=drift_event,
                ),
            )
            halt_event = RiskHaltEvent(
                reason=reason,
                triggered_by="position_reconciler",
            )
            publish_sync(
                EventEnvelope.wrap(
                    source="position_reconciler",
                    payload=halt_event,
                ),
            )
        except Exception as ev_exc:
            logger.warning("Could not publish drift events: %s", ev_exc)

        # Notify via alert engine
        if self._alert_engine is not None:
            try:
                await self._alert_engine.send_alert(
                    title="⚠ Position Drift Detected",
                    message=reason,
                    level="critical",
                )
            except Exception as ae_exc:
                logger.warning("Alert engine notification failed: %s", ae_exc)

        # Instruct risk manager to halt if available
        try:
            from app import app_state

            rm = getattr(app_state, "risk_manager", None)
            if rm is not None and hasattr(rm, "_halt_trading"):
                rm._halt_trading(reason, duration_hours=1.0)
                logger.error("Risk manager halted due to position drift on %s", symbol)
        except Exception as rm_exc:
            logger.warning("Could not halt risk manager: %s", rm_exc)

    async def _get_price(self, symbol: str) -> float | None:
        """Fetch latest price. Uses yfinance with a short timeout."""
        try:
            import yfinance as yf

            ticker = yf.Ticker(symbol)
            hist = ticker.history(period="1d", interval="1m")
            if not hist.empty:
                return float(hist["Close"].iloc[-1])
        except Exception as _exc:
            logger.debug("Suppressed exception: %s", _exc)
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
        return {
            "cycles": self._cycles,
            "mismatches": self._mismatches,
            "running": self._running,
        }


def start_reconciler(
    session_factory,
    broker=None,
    ws_manager=None,
    interval_seconds: int = 10,
) -> PositionReconciler:
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
