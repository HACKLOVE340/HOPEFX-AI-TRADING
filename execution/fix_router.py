# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# AGPL-3.0 — Share all modifications

"""
execution/fix_router.py
=======================
Event-driven FIX order router.

Flow
----
  hopefx:order  →  format FIX message  →  FIXAdapter.send_order()
                →  monitor fill / reject  →  publish fill to hopefx:order
                →  on breach / kill       →  halt and publish to hopefx:breach

Features
--------
- Subscribes to hopefx:order for order_request events.
- Formats each request into a FIXOrder (FIX 4.4 NewOrderSingle).
- Sends via the existing FIXAdapter (execution/fix_adapter.py).
- Smart routing: tries primary FIX session first; falls back to OANDA REST
  when FIX is unavailable or circuit-breaker is open.
- Monitors fills: logs fill price, quantity, latency, and slippage.
- On kill_event / breach received on hopefx:breach → stops accepting new orders.
- Publishes fill confirmations back to hopefx:order so other modules can track.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from datetime import UTC, datetime

from core.event_bus import CH_BREACH, CH_ORDER, bus
from execution.fix_adapter import (
    FIXAdapter,
    FIXExecType,
    FIXFillReport,
    FIXOrder,
    FIXOrdType,
    FIXSide,
)

logger = logging.getLogger(__name__)

# ── config ────────────────────────────────────────────────────────────────────
FIX_CONFIG_FILE: str = os.environ.get("FIX_CONFIG_FILE", "fix.cfg")
FIX_SENDER_ID: str = os.environ.get("FIX_SENDER_COMP_ID", "HOPEFX")
FIX_TARGET_ID: str = os.environ.get("FIX_TARGET_COMP_ID", "BROKER")
FIX_HOST: str = os.environ.get("FIX_HOST", "127.0.0.1")
FIX_PORT: int = int(os.environ.get("FIX_PORT", "9876"))
FIX_USERNAME: str = os.environ.get("FIX_USERNAME", "")
FIX_PASSWORD: str = os.environ.get("FIX_PASSWORD", "")
DEFAULT_UNITS: float = float(os.environ.get("FIX_DEFAULT_UNITS", "1000"))
LATENCY_WARN_MS: float = float(os.environ.get("FIX_LATENCY_WARN_MS", "50"))


# ─────────────────────────────────────────────────────────────────────────────
# OANDA REST fallback sender
# ─────────────────────────────────────────────────────────────────────────────


class _OandaFallback:
    """
    Sends market orders via OANDA v20 REST when FIX is unavailable.

    Returns a minimal fill dict on success, raises on failure.
    """

    def __init__(self) -> None:
        self._api_key = os.environ.get("OANDA_API_KEY", "")
        self._account_id = os.environ.get("OANDA_ACCOUNT_ID", "")
        self._practice = os.environ.get("OANDA_PRACTICE", "true").lower() != "false"
        env_prefix = "practice" if self._practice else "trade"
        self._base_url = f"https://{env_prefix}-api.oanda.com"

    async def send(self, symbol: str, direction: str, units: float) -> dict:
        """Place a market order; return fill dict."""
        import aiohttp

        # OANDA uses negative units for SELL
        oanda_units = units if direction == "BUY" else -units
        instrument = symbol.replace("/", "_")
        url = f"{self._base_url}/v3/accounts/{self._account_id}/orders"
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
        body = {
            "order": {
                "type": "MARKET",
                "instrument": instrument,
                "units": str(int(oanda_units)),
            }
        }

        async with (
            aiohttp.ClientSession() as session,
            session.post(
                url,
                json=body,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp,
        ):
            data = await resp.json()
            if resp.status not in (200, 201):
                raise RuntimeError(f"OANDA REST order failed: HTTP {resp.status} — {data}")

        fill = data.get("orderFillTransaction", {})
        price = float(fill.get("price", 0))
        return {
            "type": "fill_confirmation",
            "source": "oanda_rest_fallback",
            "symbol": symbol,
            "direction": direction,
            "units": units,
            "price": price,
            "order_id": fill.get("orderID", ""),
            "timestamp": datetime.now(UTC).isoformat(),
        }


# ─────────────────────────────────────────────────────────────────────────────
# FIX Router
# ─────────────────────────────────────────────────────────────────────────────


class FIXRouter:
    """
    Subscribes to hopefx:order, routes each order_request through FIX,
    monitors fills, and publishes confirmations.

    Usage
    -----
    router = FIXRouter()
    await router.start()   # runs until cancelled or kill received
    """

    def __init__(self) -> None:
        self._adapter: FIXAdapter | None = None
        self._fallback = _OandaFallback()
        self._fix_available: bool = False
        self._halted: bool = False
        self._running: bool = False
        self._order_count: int = 0
        self._fill_count: int = 0
        self._reject_count: int = 0

    # ── lifecycle ─────────────────────────────────────────────────────────────

    async def start(self) -> None:
        """Initialise FIX adapter and begin consuming order events."""
        self._running = True
        self._fix_available = self._init_fix()
        logger.info(
            "FIXRouter starting — fix_available=%s fallback=oanda_rest",
            self._fix_available,
        )
        # Listen for kill/breach events in background
        _t = asyncio.create_task(self._breach_listener())
        _t.add_done_callback(lambda _: None)
        # Main order consumer
        await self._order_consumer()

    async def stop(self) -> None:
        """Shut down FIX session cleanly."""
        self._running = False
        if self._adapter:
            try:
                self._adapter.stop()
            except Exception as exc:
                logger.warning("FIXRouter: adapter stop error: %s", exc)
        logger.info(
            "FIXRouter stopped. orders=%d fills=%d rejects=%d",
            self._order_count,
            self._fill_count,
            self._reject_count,
        )

    def _init_fix(self) -> bool:
        """Start FIXAdapter; return True on success."""
        try:
            self._adapter = FIXAdapter(
                config_file=FIX_CONFIG_FILE,
                sender_comp_id=FIX_SENDER_ID,
                target_comp_id=FIX_TARGET_ID,
                host=FIX_HOST,
                port=FIX_PORT,
                username=FIX_USERNAME,
                password=FIX_PASSWORD,
            )
            self._adapter.start()
            logger.info("FIXRouter: FIX session started.")
            return True
        except Exception as exc:
            logger.warning(
                "FIXRouter: FIX session unavailable (%s) — will use OANDA REST fallback.",
                exc,
            )
            return False

    # ── order consumer ────────────────────────────────────────────────────────

    async def _order_consumer(self) -> None:
        """Read order_request events from hopefx:order and route them."""
        async for msg in bus.subscribe(CH_ORDER):
            if not self._running:
                break
            if msg.get("type") != "order_request":
                continue
            try:
                await self._route(msg)
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.error("FIXRouter order error: %s", exc)

    # ── breach listener ───────────────────────────────────────────────────────

    async def _breach_listener(self) -> None:
        """Halt order flow on kill_event or kill_switch breach."""
        async for msg in bus.subscribe(CH_BREACH):
            if not self._running:
                break
            reason = msg.get("reason", "")
            if reason in ("kill_switch_active", "kill_event", "kill_switch"):
                self._halted = True
                logger.critical("FIXRouter: HALTED by breach event — reason=%s", reason)

    # ── routing logic ─────────────────────────────────────────────────────────

    async def _route(self, order_request: dict) -> None:
        """
        Route a single order_request.

        Smart routing priority
        ----------------------
        1. FIX session (if available and circuit-breaker closed)
        2. OANDA REST fallback
        """
        if self._halted:
            logger.warning("FIXRouter: order rejected — router is halted.")
            return

        symbol = order_request.get("symbol", "XAU/USD")
        direction = order_request.get("direction", "BUY").upper()
        units = float(order_request.get("units", DEFAULT_UNITS))
        self._order_count += 1

        logger.info(
            "FIXRouter routing  #%d  %s %s  units=%.0f",
            self._order_count,
            direction,
            symbol,
            units,
        )

        # Attempt FIX first
        if self._fix_available and self._adapter:
            cb = self._adapter.circuit_breaker
            if not cb.is_open:
                try:
                    fill = await self._send_fix(symbol, direction, units, order_request)
                    await self._on_fill(fill)
                    return
                except Exception as exc:
                    logger.warning(
                        "FIXRouter: FIX send failed (%s) — falling back to OANDA REST.",
                        exc,
                    )
            else:
                logger.warning("FIXRouter: FIX circuit-breaker OPEN — using OANDA REST fallback.")

        # OANDA REST fallback
        try:
            fill = await self._fallback.send(symbol, direction, units)
            await self._on_fill(fill)
        except Exception as exc:
            self._reject_count += 1
            logger.error("FIXRouter: all routes failed for order #%d: %s", self._order_count, exc)
            await bus.publish_breach(
                {
                    "reason": "order_route_failure",
                    "order_seq": self._order_count,
                    "symbol": symbol,
                    "direction": direction,
                    "error": "All routes failed — check server logs",
                    "timestamp": datetime.now(UTC).isoformat(),
                }
            )

    # ── FIX send ──────────────────────────────────────────────────────────────

    async def _send_fix(self, symbol: str, direction: str, units: float, order_request: dict) -> dict:
        """
        Format and send a FIX NewOrderSingle; await ExecutionReport.

        Returns a normalised fill dict.
        """
        side = FIXSide.BUY if direction == "BUY" else FIXSide.SELL

        # Map symbol to FIX instrument format (XAU/USD → XAUUSD)
        fix_symbol = symbol.replace("/", "")

        fix_order = FIXOrder(
            symbol=fix_symbol,
            side=side,
            quantity=units,
            ord_type=FIXOrdType.MARKET,
        )

        t0 = time.monotonic()

        # FIXAdapter.send_order is async-compatible (returns a coroutine or future)
        report: FIXFillReport = await self._adapter.send_order(fix_order)

        latency_ms = (time.monotonic() - t0) * 1000
        if latency_ms > LATENCY_WARN_MS:
            logger.warning(
                "FIXRouter: high latency %.1f ms for order %s",
                latency_ms,
                fix_order.cl_ord_id,
            )

        # Log fill details
        self._log_fill(report, latency_ms, order_request)

        return {
            "type": "fill_confirmation",
            "source": "fix",
            "cl_ord_id": report.cl_ord_id,
            "order_id": report.order_id,
            "symbol": symbol,
            "direction": direction,
            "units": report.cum_qty,
            "price": report.avg_px,
            "exec_type": report.exec_type.name,
            "latency_ms": round(latency_ms, 2),
            "timestamp": datetime.now(UTC).isoformat(),
        }

    # ── fill handler ──────────────────────────────────────────────────────────

    async def _on_fill(self, fill: dict) -> None:
        """Publish fill confirmation back to hopefx:order."""
        self._fill_count += 1
        logger.info(
            "FILL #%d  %s %s  price=%.5f  units=%.0f  source=%s",
            self._fill_count,
            fill.get("direction"),
            fill.get("symbol"),
            fill.get("price", 0),
            fill.get("units", 0),
            fill.get("source"),
        )
        await bus.publish_order(fill)

    # ── fill logger ───────────────────────────────────────────────────────────

    def _log_fill(self, report: FIXFillReport, latency_ms: float, order_request: dict) -> None:
        """Log fill with slippage calculation."""
        expected_price = float(order_request.get("mid", report.avg_px))
        slippage = abs(report.avg_px - expected_price) if expected_price else 0.0

        if report.exec_type == FIXExecType.REJECTED:
            self._reject_count += 1
            logger.error(
                "FIX REJECT  cl_ord_id=%s  text=%s",
                report.cl_ord_id,
                report.text,
            )
        else:
            logger.info(
                "FIX FILL  cl_ord_id=%s  qty=%.0f  avg_px=%.5f  slippage=%.5f  latency=%.1f ms",
                report.cl_ord_id,
                report.cum_qty,
                report.avg_px,
                slippage,
                latency_ms,
            )

    # ── metrics ───────────────────────────────────────────────────────────────

    def metrics(self) -> dict:
        return {
            "order_count": self._order_count,
            "fill_count": self._fill_count,
            "reject_count": self._reject_count,
            "halted": self._halted,
            "fix_available": self._fix_available,
        }
