# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
api/performance.py
==================
Public and authenticated performance endpoints.

Routes
------
GET /api/performance/equity-curve   — equity curve time series (auth optional)
GET /api/performance/public         — public summary stats (no auth required)
"""

from __future__ import annotations

import logging
import math

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from api.auth import TokenPayload, require_role

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/performance", tags=["Performance"])

from pathlib import Path as _Path

# ── models ────────────────────────────────────────────────────────────────────


class EquityPoint(BaseModel):
    time: float  # Unix timestamp (seconds)
    value: float  # Equity in account currency


class PublicPerformance(BaseModel):
    total_trades: int
    win_rate: float | None  # None until 50+ trades
    avg_return_pct: float | None
    sharpe: float | None  # None until 50+ trades
    max_drawdown_pct: float
    start_date: str
    note: str


# ── helpers ───────────────────────────────────────────────────────────────────


def _load_equity_curve() -> list[EquityPoint]:
    """
    Load equity curve from the live engine or DB trade history.

    Priority:
      1. Live HopeFXEngine fill history (most accurate — includes unrealised P&L)
      2. DB Trade table (persisted closed trades — used when engine is not running)
      3. Broker equity history (broker-reported snapshots)
      4. Empty list — frontend handles the empty case gracefully
    """
    # ── 1. Live engine fill history ───────────────────────────────────────────
    try:
        from app import app_state as _app_state

        engine = getattr(_app_state, "hopefx_engine", None)
        if engine is not None:
            fills = list(getattr(engine, "_fill_history", []))
            if fills:
                starting = float(getattr(engine, "_starting_equity", 10_000.0))
                equity = starting
                points: list[EquityPoint] = []
                for f in sorted(fills, key=lambda x: x.filled_at):
                    equity += float(getattr(f, "pnl", 0.0) or 0.0)
                    ts = f.filled_at.timestamp() if hasattr(f.filled_at, "timestamp") else float(f.filled_at)
                    points.append(EquityPoint(time=ts, value=round(equity, 4)))
                if points:
                    return points
    except Exception as exc:
        logger.debug("engine fill history load failed: %s", exc)

    # ── 2. DB Trade table (closed trades) ────────────────────────────────────
    try:
        from app import app_state as _app_state_db
        from database.models import Trade, TradeStatus

        session_factory = getattr(_app_state_db, "db_session_factory", None)
        if session_factory is not None:
            db = session_factory()
            try:
                trades = (
                    db.query(Trade)
                    .filter(Trade.status == TradeStatus.CLOSED, Trade.exit_time.isnot(None))
                    .order_by(Trade.exit_time.asc())
                    .all()
                )
                if trades:
                    equity = 10_000.0  # default starting equity
                    points = []
                    for t in trades:
                        equity += float(t.realized_pnl or 0.0)
                        ts = t.exit_time.timestamp() if hasattr(t.exit_time, "timestamp") else 0.0
                        points.append(EquityPoint(time=ts, value=round(equity, 4)))
                    if points:
                        return points
            finally:
                db.close()
    except Exception as exc:
        logger.debug("DB trade history load failed: %s", exc)

    # ── 3. Broker equity history ──────────────────────────────────────────────
    try:
        from app import app_state as _app_state2

        broker = getattr(_app_state2, "broker", None)
        if broker and hasattr(broker, "get_equity_history"):
            history = broker.get_equity_history()
            if history:
                return [EquityPoint(time=float(t), value=float(v)) for t, v in history]
    except Exception as exc:
        logger.debug("broker equity history load failed: %s", exc)

    return []


def _db_trade_count() -> int:
    """Return the count of closed trades from the DB, or 0 on any error."""
    try:
        from app import app_state as _app_state_cnt
        from database.models import Trade, TradeStatus

        session_factory = getattr(_app_state_cnt, "db_session_factory", None)
        if session_factory is not None:
            db = session_factory()
            try:
                return db.query(Trade).filter(Trade.status == TradeStatus.CLOSED).count()
            finally:
                db.close()
    except Exception as exc:
        logger.debug("DB trade count failed: %s", exc)
    return 0


def _compute_public_stats(curve: list[EquityPoint]) -> PublicPerformance:
    """Compute honest public stats from the equity curve."""
    if not curve:
        db_count = _db_trade_count()
        return PublicPerformance(
            total_trades=db_count,
            win_rate=None,
            avg_return_pct=None,
            sharpe=None,
            max_drawdown_pct=0.0,
            start_date="—",
            note=(
                f"Engine not running. {db_count} closed trades in DB."
                if db_count > 0
                else "Paper trading not yet started. Deploy and run for 30+ days."
            ),
        )

    values = [p.value for p in curve]
    start = curve[0].value

    # Max drawdown
    peak = start
    max_dd = 0.0
    for v in values:
        peak = max(peak, v)
        dd = (peak - v) / peak if peak > 0 else 0.0
        max_dd = max(max_dd, dd)

    # Returns
    returns = []
    for i in range(1, len(values)):
        if values[i - 1] > 0:
            returns.append((values[i] - values[i - 1]) / values[i - 1])

    avg_ret = (sum(returns) / len(returns) * 100) if returns else None

    # Sharpe (annualised, daily returns assumed) — only after 50+ points
    sharpe = None
    if len(returns) >= 50:
        mean_r = sum(returns) / len(returns)
        variance = sum((r - mean_r) ** 2 for r in returns) / len(returns)
        std_r = math.sqrt(variance) if variance > 0 else 0
        if std_r > 0:
            sharpe = round((mean_r / std_r) * math.sqrt(252), 3)

    import datetime

    start_date = datetime.datetime.fromtimestamp(curve[0].time).strftime("%Y-%m-%d")

    note = (
        "Live paper trading results. Sharpe shown only after 50+ data points."
        if len(returns) >= 50
        else f"Accumulating data ({len(returns)}/50 points for Sharpe)."
    )

    return PublicPerformance(
        total_trades=len(returns),
        win_rate=round(sum(1 for r in returns if r > 0) / len(returns) * 100, 1) if returns else None,
        avg_return_pct=round(avg_ret, 4) if avg_ret is not None else None,
        sharpe=sharpe,
        max_drawdown_pct=round(max_dd * 100, 3),
        start_date=start_date,
        note=note,
    )


# ── routes ────────────────────────────────────────────────────────────────────


@router.get(
    "/equity-curve",
    response_model=list[EquityPoint],
    summary="Equity curve time series",
)
async def equity_curve(
    _user: TokenPayload = Depends(require_role("trader")),
):
    """
    Return the equity curve as a list of {time, value} points.
    Used by the dashboard equity chart and drawdown chart.
    Returns an empty list when no paper trading data is available yet.

    Requires trader role — exposes live account equity values.
    """
    return _load_equity_curve()


@router.get(
    "/public",
    response_model=PublicPerformance,
    summary="Public performance summary",
)
async def public_performance():
    """
    Public (no auth required) performance summary.
    Sharpe ratio is only computed after 50+ data points to prevent
    misleading statistics from small samples.
    """
    curve = _load_equity_curve()
    return _compute_public_stats(curve)


@router.post(
    "/weekly-report/generate",
    summary="Trigger weekly performance report generation",
)
async def generate_weekly_report(
    _user: TokenPayload = Depends(require_role("admin")),
):
    """
    Manually trigger the weekly performance report.
    Generates JSON + HTML output in reports/output/ and sends email if configured.
    Normally runs automatically every Monday 08:00 UTC via APScheduler.
    """
    try:
        from reports.weekly_report import (
            WeeklyReportGenerator,
            _load_trade_data,
        )

        trades, equity_curve, starting_equity = await _load_trade_data()
        gen = WeeklyReportGenerator()
        report = gen.generate(trades, equity_curve, starting_equity)
        json_path = gen.save_json(report)
        gen.save_html(report)
        emailed = gen.send_email(report)

        return {
            "report_id": report.report_id,
            "week_end": report.week_end.isoformat(),
            "total_trades": report.total_trades,
            "net_pnl": report.net_pnl,
            "sharpe_ratio": report.sharpe_ratio,
            "max_drawdown_pct": report.max_drawdown_pct,
            "win_rate": report.win_rate,
            "json_path": str(json_path),
            "emailed": emailed,
        }
    except Exception as exc:
        logger.error("Weekly report generation failed: %s", exc)
        from fastapi import HTTPException

        raise HTTPException(status_code=500, detail="Report generation failed — check server logs") from None


@router.get(
    "/weekly-report/latest",
    summary="Get the most recent weekly performance report",
)
async def get_latest_weekly_report(
    _user: TokenPayload = Depends(require_role("trader")),
):
    """
    Return the most recently generated weekly report as JSON.
    Returns 404 if no report has been generated yet.
    """
    import json as _json

    from fastapi import HTTPException
    from fastapi.responses import JSONResponse

    output_dir = _Path(__file__).parent.parent / "reports" / "output"
    reports = sorted(output_dir.glob("weekly_*.json"), reverse=True)
    if not reports:
        raise HTTPException(
            status_code=404,
            detail="No weekly reports generated yet. POST /api/performance/weekly-report/generate to create one.",
        )
    data = _json.loads(reports[0].read_text())
    return JSONResponse(content=data)


@router.get(
    "/weekly-report/list",
    summary="List all generated weekly reports",
)
async def list_weekly_reports(
    _user: TokenPayload = Depends(require_role("admin")),
):
    """Return a list of all generated weekly report filenames."""
    output_dir = _Path(__file__).parent.parent / "reports" / "output"
    reports = sorted(output_dir.glob("weekly_*.json"), reverse=True)
    return {
        "reports": [r.name for r in reports],
        "total": len(reports),
        "output_dir": str(output_dir),
    }
