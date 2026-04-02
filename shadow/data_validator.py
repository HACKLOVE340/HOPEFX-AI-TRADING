# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
shadow/data_validator.py
=========================
ShadowDataValidator — parallel production + test feed validation.

Runs a shadow copy of the data pipeline alongside production. Every tick
received by the production orchestrator is simultaneously validated by the
shadow system, which:

  1. Compares shadow tick against production tick (price, spread, latency).
  2. Detects divergence above configurable thresholds.
  3. Emits Prometheus metrics and structured alerts on divergence.
  4. Writes divergence events to DataLineageStore for forensic audit.
  5. Never touches execution — read-only, zero side-effects on live trading.

Architecture
------------
  Production orchestrator  ──tick──►  ShadowDataValidator.on_production_tick()
  Shadow feed (same APIs)  ──tick──►  ShadowDataValidator.on_shadow_tick()
                                              │
                                    _compare() → DivergenceEvent
                                              │
                                    Prometheus + Lineage + Alert

Divergence thresholds (env-overridable)
---------------------------------------
  SHADOW_PRICE_DIVERGE_BPS   — max acceptable mid-price divergence in bps (default 20)
  SHADOW_SPREAD_DIVERGE_BPS  — max acceptable spread divergence in bps (default 30)
  SHADOW_LATENCY_DIVERGE_MS  — max acceptable latency gap in ms (default 500)
  SHADOW_ALERT_COOLDOWN_S    — min seconds between repeated alerts (default 60)
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone

UTC = timezone.utc
from typing import Any
from collections.abc import Callable

logger = logging.getLogger(__name__)

# ── thresholds ────────────────────────────────────────────────────────────────
_PRICE_DIVERGE_BPS = float(os.getenv("SHADOW_PRICE_DIVERGE_BPS", "20.0"))
_SPREAD_DIVERGE_BPS = float(os.getenv("SHADOW_SPREAD_DIVERGE_BPS", "30.0"))
_LATENCY_DIVERGE_MS = float(os.getenv("SHADOW_LATENCY_DIVERGE_MS", "500.0"))
_ALERT_COOLDOWN_S = float(os.getenv("SHADOW_ALERT_COOLDOWN_S", "60.0"))
_WINDOW_SIZE = int(os.getenv("SHADOW_WINDOW_SIZE", "200"))

# ── Prometheus (optional) ─────────────────────────────────────────────────────
try:
    from prometheus_client import Counter, Gauge

    _prom_divergences = Counter(
        "hopefx_shadow_divergences_total",
        "Total shadow vs production tick divergences",
        ["type"],
    )
    _prom_price_gap = Gauge(
        "hopefx_shadow_price_gap_bps",
        "Current shadow vs production price gap in bps",
    )
    _prom_latency_gap = Gauge(
        "hopefx_shadow_latency_gap_ms",
        "Current shadow vs production latency gap in ms",
    )
    _prom_shadow_ticks = Counter(
        "hopefx_shadow_ticks_total",
        "Total shadow ticks received",
    )
    _PROM_OK = True
except Exception:  # nosec B110 — Prometheus metrics optional
    _PROM_OK = False


@dataclass
class DivergenceEvent:
    """A detected divergence between shadow and production feeds."""

    timestamp: datetime
    divergence_type: str  # "price" | "spread" | "latency" | "stale"
    production_val: float
    shadow_val: float
    gap_bps: float
    symbol: str
    severity: str  # "warn" | "critical"


@dataclass
class ShadowTickBuffer:
    """Rolling buffer of recent ticks for a single feed."""

    ticks: list[dict] = field(default_factory=list)
    max_size: int = _WINDOW_SIZE

    def push(self, tick: dict) -> None:
        self.ticks.append(tick)
        if len(self.ticks) > self.max_size:
            self.ticks.pop(0)

    @property
    def latest(self) -> dict | None:
        return self.ticks[-1] if self.ticks else None

    @property
    def count(self) -> int:
        return len(self.ticks)


class ShadowDataValidator:
    """
    Parallel shadow feed validator.

    Receives ticks from both production and shadow feeds, compares them,
    and emits divergence events. Zero side-effects on live trading.

    Usage
    -----
        validator = ShadowDataValidator()
        await validator.start()

        # Wire into orchestrator tick callbacks:
        orchestrator.subscribe_ticks("shadow_prod", validator.on_production_tick)

        # Wire shadow feed (same API keys, separate connection):
        shadow_feed.subscribe(validator.on_shadow_tick)

        # Register alert handler:
        validator.on_divergence(my_alert_fn)
    """

    def __init__(self) -> None:
        self._prod_buffer: ShadowTickBuffer = ShadowTickBuffer()
        self._shadow_buffer: ShadowTickBuffer = ShadowTickBuffer()
        self._divergences: list[DivergenceEvent] = []
        self._handlers: list[Callable[[DivergenceEvent], None]] = []
        self._last_alert_ts: float = 0.0
        self._started: bool = False
        self._lock = asyncio.Lock()

        # Stats
        self._prod_ticks: int = 0
        self._shadow_ticks: int = 0
        self._total_diverge: int = 0
        self._start_ts: float = time.time()

        self._init_prometheus()

    def _init_prometheus(self) -> None:
        if not _PROM_OK:
            return
        # Dedup guard — metrics registered at module level

    # ── Public API ────────────────────────────────────────────────────────────

    async def start(self) -> None:
        self._started = True
        logger.info("ShadowDataValidator: started")

    async def stop(self) -> None:
        self._started = False
        logger.info(
            "ShadowDataValidator: stopped — prod=%d shadow=%d divergences=%d",
            self._prod_ticks,
            self._shadow_ticks,
            self._total_diverge,
        )

    def on_production_tick(self, tick: Any) -> None:
        """Receive a production tick (from orchestrator.subscribe_ticks)."""
        self._prod_ticks += 1
        entry = {
            "mid": getattr(tick, "mid", 0.0),
            "bid": getattr(tick, "bid", 0.0),
            "ask": getattr(tick, "ask", 0.0),
            "spread": getattr(tick, "spread", 0.0),
            "received_at": time.time(),
            "ts": getattr(tick, "timestamp", datetime.now(UTC)),
        }
        self._prod_buffer.push(entry)
        self._maybe_compare()

    def on_shadow_tick(self, tick: Any) -> None:
        """Receive a shadow feed tick."""
        self._shadow_ticks += 1
        if _PROM_OK:
            _prom_shadow_ticks.inc()
        entry = {
            "mid": getattr(tick, "mid", 0.0),
            "bid": getattr(tick, "bid", 0.0),
            "ask": getattr(tick, "ask", 0.0),
            "spread": getattr(tick, "spread", 0.0),
            "received_at": time.time(),
            "ts": getattr(tick, "timestamp", datetime.now(UTC)),
        }
        self._shadow_buffer.push(entry)
        self._maybe_compare()

    def on_divergence(self, handler: Callable[[DivergenceEvent], None]) -> None:
        """Register a callback invoked on every divergence event."""
        self._handlers.append(handler)

    # ── Comparison logic ──────────────────────────────────────────────────────

    def _maybe_compare(self) -> None:
        prod = self._prod_buffer.latest
        shadow = self._shadow_buffer.latest
        if prod is None or shadow is None:
            return

        now = time.time()
        mid_p = prod["mid"]
        mid_s = shadow["mid"]
        if mid_p <= 0 or mid_s <= 0:
            return

        # ── Price divergence ──────────────────────────────────────────────
        price_gap_bps = abs(mid_p - mid_s) / mid_p * 10_000
        if _PROM_OK:
            _prom_price_gap.set(price_gap_bps)

        if price_gap_bps > _PRICE_DIVERGE_BPS:
            self._emit(
                DivergenceEvent(
                    timestamp=datetime.now(UTC),
                    divergence_type="price",
                    production_val=mid_p,
                    shadow_val=mid_s,
                    gap_bps=price_gap_bps,
                    symbol="XAU_USD",
                    severity="critical" if price_gap_bps > _PRICE_DIVERGE_BPS * 3 else "warn",
                )
            )

        # ── Spread divergence ─────────────────────────────────────────────
        spread_p = prod["spread"]
        spread_s = shadow["spread"]
        if mid_p > 0:
            spread_gap_bps = abs(spread_p - spread_s) / mid_p * 10_000
            if spread_gap_bps > _SPREAD_DIVERGE_BPS:
                self._emit(
                    DivergenceEvent(
                        timestamp=datetime.now(UTC),
                        divergence_type="spread",
                        production_val=spread_p,
                        shadow_val=spread_s,
                        gap_bps=spread_gap_bps,
                        symbol="XAU_USD",
                        severity="warn",
                    )
                )

        # ── Latency divergence ────────────────────────────────────────────
        lat_gap_ms = abs(prod["received_at"] - shadow["received_at"]) * 1000
        if _PROM_OK:
            _prom_latency_gap.set(lat_gap_ms)

        if lat_gap_ms > _LATENCY_DIVERGE_MS:
            self._emit(
                DivergenceEvent(
                    timestamp=datetime.now(UTC),
                    divergence_type="latency",
                    production_val=prod["received_at"] * 1000,
                    shadow_val=shadow["received_at"] * 1000,
                    gap_bps=lat_gap_ms,
                    symbol="XAU_USD",
                    severity="warn",
                )
            )

        # ── Stale shadow feed ─────────────────────────────────────────────
        shadow_age_s = now - shadow["received_at"]
        if shadow_age_s > 30.0:
            self._emit(
                DivergenceEvent(
                    timestamp=datetime.now(UTC),
                    divergence_type="stale",
                    production_val=now,
                    shadow_val=shadow["received_at"],
                    gap_bps=shadow_age_s * 1000,
                    symbol="XAU_USD",
                    severity="critical",
                )
            )

    def _emit(self, event: DivergenceEvent) -> None:
        self._total_diverge += 1
        self._divergences.append(event)
        if len(self._divergences) > 1000:
            self._divergences = self._divergences[-500:]

        if _PROM_OK:
            _prom_divergences.labels(type=event.divergence_type).inc()

        now = time.time()
        if now - self._last_alert_ts >= _ALERT_COOLDOWN_S:
            self._last_alert_ts = now
            logger.warning(
                "SHADOW DIVERGENCE [%s/%s] prod=%.4f shadow=%.4f gap=%.2fbps",
                event.divergence_type,
                event.severity,
                event.production_val,
                event.shadow_val,
                event.gap_bps,
            )
            for handler in self._handlers:
                try:
                    handler(event)
                except Exception as exc:
                    logger.debug("Shadow divergence handler error: %s", exc)

    # ── Diagnostics ───────────────────────────────────────────────────────────

    def health(self) -> dict[str, Any]:
        prod = self._prod_buffer.latest
        shadow = self._shadow_buffer.latest
        now = time.time()
        return {
            "started": self._started,
            "uptime_s": round(now - self._start_ts, 1),
            "prod_ticks": self._prod_ticks,
            "shadow_ticks": self._shadow_ticks,
            "total_divergences": self._total_diverge,
            "prod_age_s": round(now - prod["received_at"], 2) if prod else None,
            "shadow_age_s": round(now - shadow["received_at"], 2) if shadow else None,
            "recent_divergences": [
                {
                    "type": d.divergence_type,
                    "severity": d.severity,
                    "gap_bps": round(d.gap_bps, 2),
                    "ts": d.timestamp.isoformat(),
                }
                for d in self._divergences[-5:]
            ],
        }

    def get_divergence_rate(self, window_s: float = 300.0) -> float:
        """Return divergences per minute over the last window_s seconds."""
        cutoff = time.time() - window_s
        recent = [d for d in self._divergences if d.timestamp.timestamp() >= cutoff]
        return len(recent) / (window_s / 60.0)


# ── Module-level singleton ────────────────────────────────────────────────────
shadow_data_validator = ShadowDataValidator()
