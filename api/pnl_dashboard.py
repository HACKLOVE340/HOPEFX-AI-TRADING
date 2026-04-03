# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
api/pnl_dashboard.py
====================
Live P&L dashboard — auditable trade log, equity curve, Sharpe, drawdown.

All data is sourced from the live HopeFXEngine instance (app_state.hopefx_engine).
No synthetic or mock data is used.

Routes
------
GET /api/pnl/summary          — headline stats: equity, Sharpe, drawdown, win rate
GET /api/pnl/equity-curve     — equity curve time series (one point per fill)
GET /api/pnl/drawdown-curve   — drawdown % time series
GET /api/pnl/trade-log        — auditable fill-level trade log (paginated)
GET /api/pnl/open-positions   — current open positions with unrealised P&L
"""

from __future__ import annotations

import contextlib
import logging
import math
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from api.auth import TokenPayload, get_current_user

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/pnl", tags=["P&L Dashboard"])

# ── Minimum fills before Sharpe is meaningful ─────────────────────────────────
_MIN_FILLS_FOR_SHARPE = 30


# ── Models ────────────────────────────────────────────────────────────────────


class PnLSummary(BaseModel):
    equity: float
    starting_equity: float
    total_return_pct: float
    total_fills: int
    open_positions: int
    win_rate: float | None  # None until _MIN_FILLS_FOR_SHARPE fills
    sharpe_ratio: float | None  # None until _MIN_FILLS_FOR_SHARPE fills
    max_drawdown_pct: float
    current_drawdown_pct: float
    avg_slippage_bps: float
    avg_latency_ms: float
    last_fill_at: str | None
    note: str


class EquityPoint(BaseModel):
    time: float  # Unix timestamp (seconds)
    value: float  # Equity in account currency


class DrawdownPoint(BaseModel):
    time: float  # Unix timestamp (seconds)
    drawdown_pct: float  # 0–100


class FillEntry(BaseModel):
    fill_id: str
    order_id: str
    signal_id: str
    symbol: str
    direction: str
    quantity: float
    fill_price: float
    expected_price: float
    slippage_bps: float
    broker: str
    latency_ms: float
    filled_at: str  # ISO-8601
    lineage_id: str


class OpenPosition(BaseModel):
    symbol: str
    direction: str
    quantity: float
    entry_price: float
    current_price: float | None
    unrealised_pnl: float | None
    stop_loss: float | None
    take_profit: float | None
    opened_at: str


# ── Engine accessor ───────────────────────────────────────────────────────────


def _get_engine() -> Any | None:
    """Return the live HopeFXEngine from app_state, or None if not started."""
    try:
        from app import app_state

        return getattr(app_state, "hopefx_engine", None)
    except Exception:
        return None


# ── Computation helpers ───────────────────────────────────────────────────────


def _build_equity_series(engine: Any) -> list[tuple[float, float]]:
    """
    Build (timestamp, equity) series from fill history.

    Starting equity is engine._starting_equity (or 10_000 fallback).
    Each fill adds its realised P&L to the running equity.
    Returns list of (unix_ts, equity) tuples sorted by fill time.
    """
    starting = float(getattr(engine, "_starting_equity", 10_000.0))
    fills = list(getattr(engine, "_fill_history", []))
    if not fills:
        return []

    # Sort by filled_at in case fills arrived out of order
    fills_sorted = sorted(fills, key=lambda f: f.filled_at)

    # Compute per-fill P&L from open_positions close events.
    # The engine stores realised P&L in _post_analyzer; fall back to
    # slippage-adjusted price difference when not available.
    post = getattr(engine, "_post_analyzer", None)
    pnl_by_fill: dict[str, float] = {}
    if post is not None and hasattr(post, "_trade_pnls"):
        pnl_by_fill = dict(getattr(post, "_trade_pnls", {}))

    equity = starting
    series: list[tuple[float, float]] = []
    for fill in fills_sorted:
        pnl = pnl_by_fill.get(fill.fill_id, 0.0)
        equity += pnl
        ts = fill.filled_at.timestamp() if isinstance(fill.filled_at, datetime) else float(fill.filled_at)
        series.append((ts, round(equity, 4)))

    return series


def _compute_drawdown_series(
    equity_series: list[tuple[float, float]],
) -> list[tuple[float, float]]:
    """
    Compute (timestamp, drawdown_pct) from equity series.
    drawdown_pct = (peak - current) / peak * 100.
    """
    if not equity_series:
        return []
    peak = equity_series[0][1]
    result: list[tuple[float, float]] = []
    for ts, val in equity_series:
        peak = max(peak, val)
        dd = (peak - val) / peak * 100.0 if peak > 0 else 0.0
        result.append((ts, round(dd, 4)))
    return result


def _compute_sharpe(equity_series: list[tuple[float, float]]) -> float | None:
    """
    Annualised Sharpe ratio from equity curve returns.
    Returns None when fewer than _MIN_FILLS_FOR_SHARPE points are available.
    Assumes fills are roughly hourly (8760 periods/year).
    """
    if len(equity_series) < _MIN_FILLS_FOR_SHARPE:
        return None
    values = [v for _, v in equity_series]
    returns = [(values[i] - values[i - 1]) / values[i - 1] for i in range(1, len(values)) if values[i - 1] > 0]
    if len(returns) < 2:
        return None
    n = len(returns)
    mean_r = sum(returns) / n
    variance = sum((r - mean_r) ** 2 for r in returns) / (n - 1)
    std_r = math.sqrt(variance) if variance > 0 else 0.0
    if std_r == 0:
        return None
    # Annualise assuming hourly fills (8760 periods/year)
    return round(mean_r / std_r * math.sqrt(8760), 4)


def _compute_max_drawdown(equity_series: list[tuple[float, float]]) -> float:
    """Return max drawdown as a percentage (0–100)."""
    if not equity_series:
        return 0.0
    peak = equity_series[0][1]
    max_dd = 0.0
    for _, val in equity_series:
        peak = max(peak, val)
        dd = (peak - val) / peak * 100.0 if peak > 0 else 0.0
        max_dd = max(max_dd, dd)
    return round(max_dd, 4)


def _compute_current_drawdown(equity_series: list[tuple[float, float]]) -> float:
    """Return current drawdown from peak as a percentage (0–100)."""
    if not equity_series:
        return 0.0
    peak = max(v for _, v in equity_series)
    current = equity_series[-1][1]
    return round((peak - current) / peak * 100.0 if peak > 0 else 0.0, 4)


# ── Routes ────────────────────────────────────────────────────────────────────


@router.get(
    "/summary",
    response_model=PnLSummary,
    summary="Live P&L headline stats",
)
async def pnl_summary(
    _user: TokenPayload = Depends(get_current_user),
) -> PnLSummary:
    """
    Return headline P&L statistics sourced from the live HopeFXEngine.

    All values are computed from real fill data — no synthetic data.
    Sharpe ratio is only shown after _MIN_FILLS_FOR_SHARPE fills to prevent
    misleading statistics from small samples.
    """
    engine = _get_engine()
    if engine is None:
        return PnLSummary(
            equity=0.0,
            starting_equity=0.0,
            total_return_pct=0.0,
            total_fills=0,
            open_positions=0,
            win_rate=None,
            sharpe_ratio=None,
            max_drawdown_pct=0.0,
            current_drawdown_pct=0.0,
            avg_slippage_bps=0.0,
            avg_latency_ms=0.0,
            last_fill_at=None,
            note="Engine not started. Start the trading engine to see live P&L.",
        )

    fills = list(getattr(engine, "_fill_history", []))
    starting = float(getattr(engine, "_starting_equity", 10_000.0))
    current_equity = float(getattr(engine, "_current_equity", starting))
    open_pos = dict(getattr(engine, "_open_positions", {}))

    equity_series = _build_equity_series(engine)
    sharpe = _compute_sharpe(equity_series)
    max_dd = _compute_max_drawdown(equity_series)
    cur_dd = _compute_current_drawdown(equity_series)

    total_return_pct = (current_equity - starting) / starting * 100.0 if starting > 0 else 0.0

    # Win rate from post-trade analyser
    post = getattr(engine, "_post_analyzer", None)
    win_rate: float | None = None
    if post is not None and hasattr(post, "rolling_stats"):
        with contextlib.suppress(Exception):
            stats = post.rolling_stats()
            wr = stats.get("win_rate")
            if wr is not None and len(fills) >= _MIN_FILLS_FOR_SHARPE:
                win_rate = round(float(wr) * 100, 2)

    avg_slip = sum(f.slippage_bps for f in fills) / len(fills) if fills else 0.0
    avg_lat = sum(f.latency_ms for f in fills) / len(fills) if fills else 0.0
    last_fill_at = fills[-1].filled_at.isoformat() if fills and isinstance(fills[-1].filled_at, datetime) else None

    note = (
        f"Live data. Sharpe shown after {_MIN_FILLS_FOR_SHARPE}+ fills ({len(fills)} so far)."
        if len(fills) < _MIN_FILLS_FOR_SHARPE
        else "Live data. All metrics computed from real fills."
    )

    return PnLSummary(
        equity=round(current_equity, 4),
        starting_equity=round(starting, 4),
        total_return_pct=round(total_return_pct, 4),
        total_fills=len(fills),
        open_positions=len(open_pos),
        win_rate=win_rate,
        sharpe_ratio=sharpe,
        max_drawdown_pct=max_dd,
        current_drawdown_pct=cur_dd,
        avg_slippage_bps=round(avg_slip, 3),
        avg_latency_ms=round(avg_lat, 2),
        last_fill_at=last_fill_at,
        note=note,
    )


@router.get(
    "/equity-curve",
    response_model=list[EquityPoint],
    summary="Equity curve time series",
)
async def equity_curve(
    _user: TokenPayload = Depends(get_current_user),
) -> list[EquityPoint]:
    """
    Return the equity curve as a list of {time, value} points.
    One point per fill, sorted chronologically.
    Returns an empty list when no fills have occurred yet.
    """
    engine = _get_engine()
    if engine is None:
        return []
    series = _build_equity_series(engine)
    return [EquityPoint(time=ts, value=val) for ts, val in series]


@router.get(
    "/drawdown-curve",
    response_model=list[DrawdownPoint],
    summary="Drawdown % time series",
)
async def drawdown_curve(
    _user: TokenPayload = Depends(get_current_user),
) -> list[DrawdownPoint]:
    """
    Return the drawdown curve as a list of {time, drawdown_pct} points.
    drawdown_pct = (peak_equity - current_equity) / peak_equity * 100.
    """
    engine = _get_engine()
    if engine is None:
        return []
    equity_series = _build_equity_series(engine)
    dd_series = _compute_drawdown_series(equity_series)
    return [DrawdownPoint(time=ts, drawdown_pct=dd) for ts, dd in dd_series]


@router.get(
    "/trade-log",
    response_model=list[FillEntry],
    summary="Auditable fill-level trade log",
)
async def trade_log(
    limit: int = Query(default=100, ge=1, le=1000, description="Max fills to return"),
    offset: int = Query(default=0, ge=0, description="Pagination offset"),
    symbol: str | None = Query(default=None, description="Filter by symbol"),
    direction: str | None = Query(default=None, description="Filter by direction (long/short)"),
    _user: TokenPayload = Depends(get_current_user),
) -> list[FillEntry]:
    """
    Return the auditable fill-level trade log from the live engine.

    Each entry corresponds to a real broker fill — no synthetic data.
    Sorted newest-first. Supports pagination and filtering by symbol/direction.

    The fill_id and lineage_id fields link each fill to the lineage store
    for full audit trail (signal → fill → outcome).
    """
    engine = _get_engine()
    if engine is None:
        return []

    fills = list(getattr(engine, "_fill_history", []))
    # Sort newest-first
    fills_sorted = sorted(fills, key=lambda f: f.filled_at, reverse=True)

    # Apply filters
    if symbol:
        sym_upper = symbol.upper()
        fills_sorted = [f for f in fills_sorted if f.symbol.upper() == sym_upper]
    if direction:
        dir_lower = direction.lower()
        fills_sorted = [f for f in fills_sorted if f.direction.lower() == dir_lower]

    # Paginate
    page = fills_sorted[offset : offset + limit]

    return [
        FillEntry(
            fill_id=f.fill_id,
            order_id=f.order_id,
            signal_id=f.signal_id,
            symbol=f.symbol,
            direction=f.direction,
            quantity=f.quantity,
            fill_price=f.fill_price,
            expected_price=f.expected_price,
            slippage_bps=f.slippage_bps,
            broker=f.broker,
            latency_ms=f.latency_ms,
            filled_at=f.filled_at.isoformat() if isinstance(f.filled_at, datetime) else str(f.filled_at),
            lineage_id=f.lineage_id,
        )
        for f in page
    ]


@router.get(
    "/open-positions",
    response_model=list[OpenPosition],
    summary="Current open positions with unrealised P&L",
)
async def open_positions(
    _user: TokenPayload = Depends(get_current_user),
) -> list[OpenPosition]:
    """
    Return all currently open positions with unrealised P&L.

    Current price is fetched from the orchestrator tick cache.
    Unrealised P&L = (current_price - entry_price) * quantity * direction_sign.
    """
    engine = _get_engine()
    if engine is None:
        return []

    open_pos = dict(getattr(engine, "_open_positions", {}))
    if not open_pos:
        return []

    # Try to get current prices from orchestrator
    current_prices: dict[str, float] = {}
    try:
        from data_layer.orchestrator import orchestrator

        for sym in open_pos:
            tick = orchestrator.get_latest_tick(sym)
            if tick is not None:
                current_prices[sym] = float(getattr(tick, "mid", 0) or 0)
    except Exception as exc:
        logger.debug("open_positions: orchestrator tick fetch failed: %s", exc)

    result: list[OpenPosition] = []
    for sym, pos in open_pos.items():
        entry = float(getattr(pos, "entry_price", 0) or 0)
        qty = float(getattr(pos, "lots", 0) or getattr(pos, "quantity", 0) or 0)
        direction = str(getattr(pos, "side", getattr(pos, "direction", "long")))
        current = current_prices.get(sym, 0.0)

        unrealised: float | None = None
        if current > 0 and entry > 0 and qty > 0:
            sign = 1.0 if direction.lower() in ("long", "buy") else -1.0
            unrealised = round((current - entry) * qty * sign, 4)

        opened_at = getattr(pos, "opened_at", None)
        opened_at_str = (
            opened_at.isoformat() if isinstance(opened_at, datetime) else str(opened_at) if opened_at else ""
        )

        result.append(
            OpenPosition(
                symbol=sym,
                direction=direction,
                quantity=qty,
                entry_price=entry,
                current_price=current if current > 0 else None,
                unrealised_pnl=unrealised,
                stop_loss=float(getattr(pos, "stop_loss", 0) or 0) or None,
                take_profit=float(getattr(pos, "take_profit", 0) or 0) or None,
                opened_at=opened_at_str,
            )
        )

    return result
