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
from typing import ClassVar

logger = logging.getLogger(__name__)

_reconciler_task: asyncio.Task | None = None

# How many consecutive mismatches for the same symbol before escalating to ERROR
_MISMATCH_ALERT_THRESHOLD = 3

# Drift thresholds — breach either to trigger RiskHaltEvent
_DRIFT_QTY_THRESHOLD = float(os.getenv("RECONCILER_DRIFT_QTY", "1.0"))  # units
_DRIFT_VALUE_THRESHOLD = float(os.getenv("RECONCILER_DRIFT_VALUE", "100.0"))  # USD

# Max per-symbol notional exposure (USD). The exposure invariant flags any symbol
# whose summed open notional exceeds this (No Hidden Exposure).
_MAX_SYMBOL_EXPOSURE_USD = float(os.getenv("RISK_MAX_SYMBOL_EXPOSURE_USD", "1000000.0"))

# Approved portfolio VaR limit (USD, positive loss magnitude). 0 disables the
# per-cycle VaR invariant (No Hidden Risk).
_APPROVED_VAR_USD = float(os.getenv("RISK_APPROVED_VAR_USD", "0"))


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
        _t = asyncio.create_task(self._loop())
        _t.add_done_callback(lambda _: None)

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

        # Fetch broker positions if available. Keep fetch success separate from
        # mapping truthiness: an honest empty broker book must detect DB-only
        # positions, while a failed fetch must remain an unknown state.
        broker_positions: dict = {}
        broker_snapshot_available = False
        if self._broker and hasattr(self._broker, "get_positions"):
            try:
                raw = self._broker.get_positions()
                if asyncio.iscoroutine(raw):
                    raw = await raw
                if raw is None:
                    raise RuntimeError("broker returned no position snapshot")
                broker_positions = {}
                for position in raw or []:
                    if isinstance(position, dict):
                        symbol = position.get("symbol")
                    else:
                        symbol = getattr(position, "symbol", None)
                    if symbol:
                        broker_positions[str(symbol)] = position
                broker_snapshot_available = True
            except Exception as exc:
                logger.warning("Could not fetch broker positions: %s", exc)

        # Fetch latest prices and update unrealized P&L
        updated = 0
        # Aggregate book value (DB vs broker) for the constitutional
        # reconciliation invariant run after the loop.
        agg_db_value = 0.0
        agg_broker_value = 0.0
        have_broker_values = False
        # Per-symbol notional exposure (sums multiple positions on the same
        # symbol) for the No Hidden Exposure invariant run after the loop.
        symbol_exposure: dict[str, float] = {}
        for pos in db_positions:
            price = await self._get_price(pos.symbol)
            if price is None:
                continue

            symbol_exposure[pos.symbol] = symbol_exposure.get(pos.symbol, 0.0) + abs(float(pos.quantity or 0) * price)

            pnl = self._calc_pnl(pos, price)
            with self._sf() as session:
                db_pos = session.query(DBPosition).filter_by(id=pos.id).first()
                if db_pos:
                    db_pos.current_price = price
                    db_pos.unrealized_pnl = pnl
                    session.commit()
                    updated += 1

            # ── Drift detection ───────────────────────────────────────────────
            if broker_snapshot_available:
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

                    if price:
                        db_value = db_qty * price
                        broker_value = broker_qty * price
                        value_diff = abs(db_value - broker_value)
                        agg_db_value += db_value
                        agg_broker_value += broker_value
                        have_broker_values = True
                    else:
                        db_value = broker_value = 0.0
                        value_diff = 0.0

                    if qty_diff > self._drift_qty or (price and value_diff > self._drift_value):
                        await self._trigger_drift_halt(
                            symbol=pos.symbol,
                            db_qty=db_qty,
                            broker_qty=broker_qty,
                            qty_diff=qty_diff,
                            db_value=db_value,
                            broker_value=broker_value,
                            value_diff=value_diff,
                        )

        # ── Constitutional reconciliation invariant (feature-flagged) ─────────
        # Aggregate book value the platform believes (DB) vs. what the broker
        # reports must reconcile.  In MONITOR mode this only logs; in ENFORCE
        # mode a CONSTITUTIONAL breach trips the kill switch (No Hidden Loss).
        if have_broker_values:
            await self._enforce_reconciliation(agg_db_value, agg_broker_value)

        # ── Per-symbol exposure invariant (feature-flagged) ───────────────────
        if symbol_exposure:
            self._enforce_exposure(symbol_exposure)

        # ── Portfolio VaR invariant (No Hidden Risk, feature-flagged) ─────────
        if _APPROVED_VAR_USD > 0:
            self._enforce_var()

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

    async def _enforce_reconciliation(self, db_value: float, broker_value: float) -> None:
        """Run the constitutional reconciliation invariant on aggregate book value
        and, in ENFORCE mode, trip the kill switch on a CONSTITUTIONAL breach.

        Fail-safe: any error here is logged and swallowed — a bug in the
        invariant layer must never crash the reconciliation loop.
        """
        try:
            from invariants.enforcement import enforce_reconciliation

            result = enforce_reconciliation(
                internal_value=db_value,
                external_value=broker_value,
                value_tol=self._drift_value,
            )
            if result.should_halt:
                reason = (
                    f"Reconciliation breach: DB book ${db_value:.2f} vs broker ${broker_value:.2f} — {result.reason}"
                )
                logger.critical("RECONCILE_KILL: %s", reason)
                try:
                    from kill_switch import KillSwitch

                    KillSwitch().activate(reason)
                except Exception as ks_exc:
                    logger.error("Could not activate kill switch on reconciliation breach: %s", ks_exc)
        except Exception as exc:
            logger.warning("Reconciliation invariant check failed (suppressed): %s", exc)

    def _enforce_exposure(self, symbol_exposure: dict[str, float]) -> None:
        """Run the No Hidden Exposure invariant on per-symbol notional. In MONITOR
        mode this only logs; in ENFORCE mode an over-limit symbol is surfaced via
        the facade (and counted) for the control center. Fail-safe: swallow errors.
        """
        try:
            from invariants.enforcement import enforce_exposure

            limits = dict.fromkeys(symbol_exposure, _MAX_SYMBOL_EXPOSURE_USD)
            result = enforce_exposure(symbol_exposure, limits)
            if result.violations:
                logger.warning("EXPOSURE: %s", result.reason)
        except Exception as exc:
            logger.warning("Exposure invariant check failed (suppressed): %s", exc)

    def _enforce_var(self) -> None:
        """Run the portfolio-VaR invariant each cycle (No Hidden Risk): current
        VaR must stay within the approved limit. Reads the live risk manager;
        MONITOR logs, fail-safe (errors suppressed)."""
        try:
            from core.app_state import app_state

            rm = getattr(app_state, "risk_manager", None)
            if rm is None or not hasattr(rm, "value_at_risk"):
                return
            current_var = abs(float(rm.value_at_risk()))
            from invariants.enforcement import enforce_var

            result = enforce_var(current_var, _APPROVED_VAR_USD)
            if result.violations:
                logger.warning("VAR: %s", result.reason)
        except Exception as exc:
            logger.warning("VaR invariant check failed (suppressed): %s", exc)

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
            from core.app_state import app_state

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
    rec = PositionReconciler(
        session_factory=session_factory,
        broker=broker,
        ws_manager=ws_manager,
        interval_seconds=interval_seconds,
    )
    # Schedule start — must be called from within a running event loop
    asyncio.get_running_loop().create_task(_start(rec))
    return rec


async def _start(rec: PositionReconciler) -> None:
    await rec.start()
