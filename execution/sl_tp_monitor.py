# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
execution/sl_tp_monitor.py
===========================
SL/TP Monitor — background asyncio task that polls open positions and
closes them when the current mid-price breaches stop-loss or take-profit
levels.

This is the critical safety net that prevents unlimited loss when the
strategy function crashes or is unable to manage its own positions.

Design
------
- Runs as an ``asyncio`` background task started by :class:`ExecutionEngine`.
- Polls the :class:`PositionManager` every ``SLTP_POLL_INTERVAL_MS`` ms.
- For each open position that has a non-None ``stop_loss`` or ``take_profit``,
  checks the latest mid-price from the engine's tick cache.
- When a level is breached, submits a market close order via the broker,
  retrying up to ``SLTP_MAX_RETRIES`` times.
- Emits Prometheus counters and Sentry captures on failures.
- Sends a Telegram alert when a position is closed by SL or TP.

Environment variables
---------------------
SLTP_POLL_INTERVAL_MS   Polling interval in milliseconds (default: 200)
SLTP_MAX_RETRIES        Max broker close retries per breach (default: 3)
SLTP_RETRY_DELAY_S      Seconds between retries (default: 1.0)
"""

from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

UTC = timezone.utc

_POLL_INTERVAL_MS = int(os.getenv("SLTP_POLL_INTERVAL_MS", "200"))
_MAX_RETRIES = int(os.getenv("SLTP_MAX_RETRIES", "3"))
_RETRY_DELAY_S = float(os.getenv("SLTP_RETRY_DELAY_S", "1.0"))

# ── Optional Prometheus metrics ───────────────────────────────────────────────
try:
    from prometheus_client import Counter  # type: ignore[import]

    _sltp_closes = Counter(
        "hopefx_sltp_closes_total",
        "Positions closed by SL/TP monitor",
        ["reason"],
    )
    _sltp_errors = Counter(
        "hopefx_sltp_close_errors_total",
        "SL/TP close attempts that failed after all retries",
    )
    _PROM_OK = True
except Exception:  # nosec B110
    _PROM_OK = False

# Optional Sentry
try:
    import sentry_sdk as _sentry_sdk  # type: ignore[import]

    _SENTRY = True
except ImportError:
    _SENTRY = False


def _send_alert(subject: str, body: str) -> None:
    """Fire-and-forget Telegram/notification alert (non-blocking)."""
    try:
        from notifications import get_alert_engine

        engine = get_alert_engine()
        if engine is None:
            return

        async def _do() -> None:
            await engine.send_alert("critical", f"🔴 SL/TP MONITOR — {subject}: {body}")

        try:
            loop = asyncio.get_running_loop()
            loop.create_task(_do())
        except RuntimeError:
            asyncio.run(_do())
    except Exception as exc:  # nosec B110
        logger.debug("SL/TP monitor alert suppressed: %s", exc)


class SLTPMonitor:
    """
    Background asyncio task that enforces stop-loss and take-profit levels
    by submitting market close orders when price levels are breached.

    Usage
    -----
        monitor = SLTPMonitor(position_manager, broker, tick_cache)
        await monitor.start()
        # ...engine runs...
        await monitor.stop()
    """

    def __init__(
        self,
        position_manager,
        broker,
        tick_cache: dict,
    ) -> None:
        """
        Parameters
        ----------
        position_manager:
            :class:`execution.position_manager.PositionManager` instance.
        broker:
            BrokerManager or BrokerConnector — must expose ``place_order()``.
        tick_cache:
            Reference to the engine's ``_last_ticks`` dict
            (``{symbol: tick}``).  Updated externally by the tick feed.
        """
        self._pm = position_manager
        self._broker = broker
        self._ticks = tick_cache
        self._task: asyncio.Task | None = None
        self._running = False
        # Track which positions are currently being closed (avoid duplicate closes)
        self._closing: set[str] = set()

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._loop(), name="sltp_monitor")
        self._task.add_done_callback(self._on_task_done)
        logger.info(
            "SLTPMonitor started (poll_interval=%dms, max_retries=%d)",
            _POLL_INTERVAL_MS,
            _MAX_RETRIES,
        )

    async def stop(self) -> None:
        self._running = False
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        logger.info("SLTPMonitor stopped.")

    def _on_task_done(self, fut: asyncio.Future) -> None:  # noqa: ARG002
        if not fut.cancelled() and fut.exception() is not None:
            exc = fut.exception()
            logger.critical("SLTPMonitor task crashed: %s", exc, exc_info=exc)
            if _SENTRY:
                try:
                    _sentry_sdk.capture_exception(exc)
                except Exception:  # nosec B110
                    pass
            # Auto-restart on crash to preserve safety guarantee
            if self._running:
                logger.warning("SLTPMonitor: restarting after crash")
                self._task = asyncio.create_task(self._loop(), name="sltp_monitor")
                self._task.add_done_callback(self._on_task_done)

    # ── Main loop ─────────────────────────────────────────────────────────────

    async def _loop(self) -> None:
        poll_seconds = _POLL_INTERVAL_MS / 1000.0
        while self._running:
            try:
                await self._check_all_positions()
            except Exception as exc:  # noqa: BLE001
                logger.error("SLTPMonitor._loop error: %s", exc)
            await asyncio.sleep(poll_seconds)

    async def _check_all_positions(self) -> None:
        """Iterate over all open positions and check SL/TP levels."""
        if self._pm is None:
            return

        try:
            positions = self._pm.get_all_positions()
        except Exception as exc:  # noqa: BLE001
            logger.debug("SLTPMonitor: could not get positions: %s", exc)
            return

        for pos in positions:
            if pos.position_id in self._closing:
                continue
            mid = self._get_mid(pos.symbol)
            if mid is None or mid <= 0:
                continue
            reason = self._check_breach(pos, mid)
            if reason:
                asyncio.create_task(
                    self._close_position(pos, reason, mid),
                    name=f"sltp_close_{pos.position_id}",
                )

    def _get_mid(self, symbol: str) -> float | None:
        """Return the latest mid-price for *symbol* from the tick cache."""
        tick = self._ticks.get(symbol)
        if tick is None:
            return None
        if hasattr(tick, "mid"):
            return float(tick.mid)
        if hasattr(tick, "price"):
            return float(tick.price)
        return None

    @staticmethod
    def _check_breach(pos, mid: float) -> str | None:
        """
        Return a reason string if *mid* has breached the position's SL or TP,
        otherwise ``None``.

        Logic:
        - LONG  position: SL breached when mid ≤ stop_loss;
                          TP breached when mid ≥ take_profit.
        - SHORT position: SL breached when mid ≥ stop_loss;
                          TP breached when mid ≤ take_profit.
        """
        side = (getattr(pos, "side", "") or "").upper()
        sl = getattr(pos, "stop_loss", None)
        tp = getattr(pos, "take_profit", None)

        if side in ("BUY", "LONG"):
            if sl is not None and sl > 0 and mid <= sl:
                return "stop_loss"
            if tp is not None and tp > 0 and mid >= tp:
                return "take_profit"
        elif side in ("SELL", "SHORT"):
            if sl is not None and sl > 0 and mid >= sl:
                return "stop_loss"
            if tp is not None and tp > 0 and mid <= tp:
                return "take_profit"
        return None

    async def _close_position(self, pos, reason: str, trigger_price: float) -> None:
        """
        Attempt to close *pos* at market due to *reason* (stop_loss or take_profit).

        Retries up to ``_MAX_RETRIES`` times with exponential backoff.
        Emits Prometheus counter, logs, and sends Telegram alert on success.
        Captures to Sentry and increments error counter if all retries fail.
        """
        pos_id = pos.position_id
        symbol = pos.symbol
        self._closing.add(pos_id)
        logger.warning(
            "SLTPMonitor: %s BREACHED | pos=%s symbol=%s mid=%.5f",
            reason.upper(),
            pos_id,
            symbol,
            trigger_price,
        )

        try:
            from brokers.base import OrderSide, OrderType

            side = (getattr(pos, "side", "") or "").upper()
            # Close direction is opposite to the position direction
            close_side = OrderSide.SELL if side in ("BUY", "LONG") else OrderSide.BUY
            qty = abs(getattr(pos, "quantity", 0.0) or 0.0)
            if qty <= 0:
                logger.error("SLTPMonitor: position %s has zero quantity — cannot close", pos_id)
                return

            success = False
            for attempt in range(1, _MAX_RETRIES + 1):
                try:
                    loop = asyncio.get_event_loop()
                    order = await loop.run_in_executor(
                        None,
                        lambda: self._broker.place_order(
                            symbol=symbol,
                            side=close_side,
                            order_type=OrderType.MARKET,
                            quantity=qty,
                            price=None,
                            stop_price=None,
                        ),
                    )
                    if order is not None:
                        logger.info(
                            "SLTPMonitor: closed pos=%s reason=%s attempt=%d order_id=%s",
                            pos_id,
                            reason,
                            attempt,
                            getattr(order, "id", "?"),
                        )
                        # Remove from position manager
                        try:
                            await self._pm.close_position(
                                symbol=symbol,
                                close_price=trigger_price,
                                close_time=datetime.now(UTC),
                            )
                        except Exception as pm_exc:  # noqa: BLE001
                            logger.warning("SLTPMonitor: pm.close_position error: %s", pm_exc)

                        if _PROM_OK:
                            _sltp_closes.labels(reason=reason).inc()
                        _send_alert(
                            f"{reason.upper()} HIT",
                            f"Closed {side} {qty} {symbol} @ {trigger_price:.5f} "
                            f"| SL={getattr(pos, 'stop_loss', None)} "
                            f"TP={getattr(pos, 'take_profit', None)}",
                        )
                        success = True
                        break
                except Exception as broker_exc:  # noqa: BLE001
                    logger.error(
                        "SLTPMonitor: close attempt %d/%d failed for pos=%s: %s",
                        attempt,
                        _MAX_RETRIES,
                        pos_id,
                        broker_exc,
                    )
                    if attempt < _MAX_RETRIES:
                        await asyncio.sleep(_RETRY_DELAY_S * attempt)

            if not success:
                msg = (
                    f"SLTPMonitor FAILED to close position {pos_id} ({symbol}) "
                    f"after {_MAX_RETRIES} retries — MANUAL INTERVENTION REQUIRED"
                )
                logger.critical(msg)
                if _SENTRY:
                    try:
                        _sentry_sdk.capture_message(msg, level="fatal")
                    except Exception:  # nosec B110
                        pass
                if _PROM_OK:
                    _sltp_errors.inc()
                _send_alert("CLOSE FAILURE — MANUAL INTERVENTION REQUIRED", msg)

        finally:
            self._closing.discard(pos_id)
