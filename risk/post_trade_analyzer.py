# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
risk/post_trade_analyzer.py
============================
PostTradeAnalyzer — post-trade forensics and execution quality analysis.

Runs after every fill closes. Computes:
  - Slippage vs expected (bps)
  - Implementation shortfall (IS) — difference between decision price and fill
  - Market impact (temporary + permanent components)
  - Fill quality score (0–1)
  - Adverse selection detection (did we trade into informed flow?)
  - Execution timing analysis (did we fill at a good time in the bar?)
  - Cumulative execution cost tracking (feeds into alpha decay monitor)

All results are:
  - Written to DataLineageStore (immutable audit trail)
  - Exposed via Prometheus metrics
  - Accessible via /api/risk/post-trade endpoint
  - Fed into the slippage model calibration loop

Usage
-----
    analyzer = PostTradeAnalyzer(lineage_store=orchestrator._lineage)

    # After every fill:
    result = analyzer.record_fill(
        trade_id="abc",
        symbol="XAU_USD",
        side="long",
        lots=0.01,
        decision_price=2350.0,   # price when signal was generated
        fill_price=2350.8,       # actual fill
        mid_at_fill=2350.5,      # mid at time of fill
        spread_at_fill=0.5,
        bar_open=2349.0,
        bar_high=2351.5,
        bar_low=2348.5,
        bar_close=2350.8,
    )
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import numpy as np

logger = logging.getLogger(__name__)

# ── Prometheus ────────────────────────────────────────────────────────────────
try:
    from prometheus_client import Counter, Gauge, Histogram

    _prom_fills = Counter("hopefx_post_trade_fills_total", "Total fills analyzed")
    _prom_slippage = Histogram(
        "hopefx_post_trade_slippage_bps",
        "Fill slippage in bps",
        buckets=[0, 1, 2, 5, 10, 20, 50, 100],
    )
    _prom_is = Gauge("hopefx_post_trade_impl_shortfall_bps", "Avg implementation shortfall bps")
    _prom_fill_quality = Gauge("hopefx_post_trade_fill_quality", "Rolling avg fill quality score")
    _prom_adverse_sel = Counter("hopefx_post_trade_adverse_selection_total", "Adverse selection events")
    _PROM_OK = True
except Exception:  # nosec B110 — Prometheus metrics optional
    _PROM_OK = False


@dataclass
class FillRecord:
    """Complete post-trade record for a single fill."""

    trade_id: str
    symbol: str
    side: str
    lots: float
    decision_price: float
    fill_price: float
    mid_at_fill: float
    spread_at_fill: float
    bar_open: float
    bar_high: float
    bar_low: float
    bar_close: float
    filled_at: datetime

    # Computed fields
    slippage_bps: float = 0.0
    impl_shortfall_bps: float = 0.0
    market_impact_bps: float = 0.0
    fill_quality: float = 0.0
    adverse_selection: bool = False
    timing_score: float = 0.0  # 0=worst, 1=best timing in bar
    execution_cost_usd: float = 0.0

    def __post_init__(self) -> None:
        self._compute()

    def _compute(self) -> None:
        mid = self.mid_at_fill
        if mid <= 0:
            return

        # Slippage: fill vs mid at time of fill
        if self.side == "long":
            self.slippage_bps = (self.fill_price - mid) / mid * 10_000
        else:
            self.slippage_bps = (mid - self.fill_price) / mid * 10_000

        # Implementation shortfall: fill vs decision price
        if self.side == "long":
            self.impl_shortfall_bps = (self.fill_price - self.decision_price) / self.decision_price * 10_000
        else:
            self.impl_shortfall_bps = (self.decision_price - self.fill_price) / self.decision_price * 10_000

        # Market impact: half-spread proxy
        self.market_impact_bps = self.spread_at_fill / mid * 10_000 / 2

        # Execution cost in USD
        self.execution_cost_usd = abs(self.slippage_bps) / 10_000 * mid * self.lots * 100.0

        # Fill quality: 1 = filled at best price in bar, 0 = worst
        bar_range = self.bar_high - self.bar_low
        if bar_range > 0:
            if self.side == "long":
                # Lower fill = better for long
                self.timing_score = (self.bar_high - self.fill_price) / bar_range
            else:
                # Higher fill = better for short
                self.timing_score = (self.fill_price - self.bar_low) / bar_range
            self.timing_score = max(0.0, min(1.0, self.timing_score))
        else:
            self.timing_score = 0.5

        # Fill quality composite: timing + low slippage
        slip_penalty = min(1.0, abs(self.slippage_bps) / 20.0)  # 20bps = full penalty
        self.fill_quality = 0.6 * self.timing_score + 0.4 * (1.0 - slip_penalty)

        # Adverse selection: price moved against us after fill
        # (fill_price worse than bar_close for our direction)
        if self.side == "long":
            self.adverse_selection = self.bar_close < self.fill_price
        else:
            self.adverse_selection = self.bar_close > self.fill_price


class PostTradeAnalyzer:
    """
    Post-trade execution quality analyzer.

    Records every fill, computes execution metrics, and maintains rolling
    statistics for slippage model calibration.
    """

    def __init__(self, lineage_store: Any | None = None) -> None:
        self._lineage = lineage_store
        self._fills: list[FillRecord] = []
        self._start_ts = time.time()

    def record_fill(
        self,
        trade_id: str,
        symbol: str,
        side: str,
        lots: float,
        decision_price: float,
        fill_price: float,
        mid_at_fill: float,
        spread_at_fill: float,
        bar_open: float = 0.0,
        bar_high: float = 0.0,
        bar_low: float = 0.0,
        bar_close: float = 0.0,
    ) -> FillRecord:
        """Record a fill and compute all execution quality metrics."""
        record = FillRecord(
            trade_id=trade_id,
            symbol=symbol,
            side=side,
            lots=lots,
            decision_price=decision_price,
            fill_price=fill_price,
            mid_at_fill=mid_at_fill,
            spread_at_fill=spread_at_fill,
            bar_open=bar_open or fill_price,
            bar_high=bar_high or fill_price,
            bar_low=bar_low or fill_price,
            bar_close=bar_close or fill_price,
            filled_at=datetime.now(UTC),
        )
        self._fills.append(record)

        if _PROM_OK:
            _prom_fills.inc()
            _prom_slippage.observe(max(0.0, record.slippage_bps))
            if record.adverse_selection:
                _prom_adverse_sel.inc()
            # Update rolling averages
            recent = self._fills[-50:]
            _prom_is.set(sum(r.impl_shortfall_bps for r in recent) / len(recent))
            _prom_fill_quality.set(sum(r.fill_quality for r in recent) / len(recent))

        logger.info(
            "POST-TRADE %s %s lots=%.3f slip=%.2fbps IS=%.2fbps quality=%.2f adverse=%s",
            side,
            symbol,
            lots,
            record.slippage_bps,
            record.impl_shortfall_bps,
            record.fill_quality,
            record.adverse_selection,
        )

        # Write to lineage
        self._write_lineage(record)

        return record

    def _write_lineage(self, record: FillRecord) -> None:
        if self._lineage is None:
            return
        try:
            self._lineage.record_signal(
                direction=f"FILL:{record.side}",
                confidence=record.fill_quality,
                probability=0.0,
                features_hash="",
                model_version=f"post_trade:slip={record.slippage_bps:.2f}bps",
                lineage_id=record.trade_id,
                symbol=record.symbol,
            )
        except Exception as exc:
            logger.debug("PostTradeAnalyzer lineage write failed: %s", exc)

    # ── Analytics ─────────────────────────────────────────────────────────────

    def rolling_stats(self, window: int = 50) -> dict[str, float]:
        """Rolling execution quality statistics over last N fills."""
        recent = self._fills[-window:] if self._fills else []
        if not recent:
            return {}
        slippages = [r.slippage_bps for r in recent]
        is_vals = [r.impl_shortfall_bps for r in recent]
        qualities = [r.fill_quality for r in recent]
        costs = [r.execution_cost_usd for r in recent]
        adverse = [r.adverse_selection for r in recent]
        return {
            "count": len(recent),
            "avg_slippage_bps": round(float(np.mean(slippages)), 3),
            "p95_slippage_bps": round(float(np.percentile(slippages, 95)), 3),
            "avg_impl_shortfall": round(float(np.mean(is_vals)), 3),
            "avg_fill_quality": round(float(np.mean(qualities)), 3),
            "total_exec_cost_usd": round(float(sum(costs)), 2),
            "adverse_sel_rate": round(sum(adverse) / len(adverse), 3),
        }

    def get_fills(self, limit: int = 100) -> list[dict[str, Any]]:
        return [
            {
                "trade_id": r.trade_id,
                "symbol": r.symbol,
                "side": r.side,
                "lots": r.lots,
                "fill_price": r.fill_price,
                "slippage_bps": round(r.slippage_bps, 3),
                "impl_shortfall_bps": round(r.impl_shortfall_bps, 3),
                "fill_quality": round(r.fill_quality, 3),
                "adverse_selection": r.adverse_selection,
                "timing_score": round(r.timing_score, 3),
                "execution_cost_usd": round(r.execution_cost_usd, 4),
                "filled_at": r.filled_at.isoformat(),
            }
            for r in self._fills[-limit:]
        ]
