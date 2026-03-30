# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# AGPL-3.0 — Share all modifications
"""
api/tca.py
==========
Transaction Cost Analysis REST API.

Routes
------
GET /tca/report              — aggregated slippage stats (all brokers)
GET /tca/report/{broker}     — per-broker slippage stats
GET /tca/records             — recent TCA records (last N fills)
GET /tca/alerts              — brokers currently above slippage threshold
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Query, Request

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/tca", tags=["tca"])


def _require_auth(request: Request) -> Dict[str, Any]:
    try:
        from auth.jwt_handler import decode_token
        token = request.headers.get("Authorization", "").removeprefix("Bearer ").strip()
        if not token:
            from fastapi import HTTPException
            raise HTTPException(status_code=401, detail="Missing token")
        return decode_token(token)
    except Exception as exc:
        from fastapi import HTTPException
        raise HTTPException(status_code=401, detail=str(exc))


@router.get("/report")
async def get_all_reports(
    request: Request,
    last_n: int = Query(500, ge=1, le=10000),
) -> List[Dict[str, Any]]:
    """Return per-broker TCA reports for all brokers with recent fills."""
    _require_auth(request)
    from execution.tca_recorder import get_tca_recorder
    reports = get_tca_recorder().get_all_reports(last_n=last_n)
    return [
        {
            "broker": r.broker,
            "symbol": r.symbol,
            "session": r.session,
            "n_trades": r.n_trades,
            "mean_slippage_bps": round(r.mean_slippage_bps, 4),
            "median_slippage_bps": round(r.median_slippage_bps, 4),
            "p95_slippage_bps": round(r.p95_slippage_bps, 4),
            "p99_slippage_bps": round(r.p99_slippage_bps, 4),
            "std_slippage_bps": round(r.std_slippage_bps, 4),
            "total_slippage_usd": round(r.total_slippage_usd, 2),
            "mean_latency_ms": round(r.mean_latency_ms, 2),
            "p95_latency_ms": round(r.p95_latency_ms, 2),
            "mean_signal_to_fill_ms": round(r.mean_signal_to_fill_ms, 2),
            "adverse_fill_rate": round(r.adverse_fill_rate, 4),
            "price_improvement_rate": round(r.price_improvement_rate, 4),
            "alert_triggered": r.alert_triggered,
            "generated_at": r.generated_at.isoformat(),
        }
        for r in reports
    ]


@router.get("/report/{broker}")
async def get_broker_report(
    broker: str,
    request: Request,
    symbol: Optional[str] = Query(None),
    session: Optional[str] = Query(None),
    last_n: int = Query(500, ge=1, le=10000),
) -> Dict[str, Any]:
    """Return TCA report for a specific broker, optionally filtered by symbol/session."""
    _require_auth(request)
    from execution.tca_recorder import get_tca_recorder
    from fastapi import HTTPException
    report = get_tca_recorder().get_report(
        broker=broker, symbol=symbol, session=session, last_n=last_n
    )
    if report is None:
        raise HTTPException(status_code=404, detail=f"No TCA data for broker '{broker}'")
    return {
        "broker": report.broker,
        "symbol": report.symbol,
        "session": report.session,
        "n_trades": report.n_trades,
        "mean_slippage_bps": round(report.mean_slippage_bps, 4),
        "median_slippage_bps": round(report.median_slippage_bps, 4),
        "p95_slippage_bps": round(report.p95_slippage_bps, 4),
        "p99_slippage_bps": round(report.p99_slippage_bps, 4),
        "std_slippage_bps": round(report.std_slippage_bps, 4),
        "total_slippage_usd": round(report.total_slippage_usd, 2),
        "mean_latency_ms": round(report.mean_latency_ms, 2),
        "p95_latency_ms": round(report.p95_latency_ms, 2),
        "mean_signal_to_fill_ms": round(report.mean_signal_to_fill_ms, 2),
        "adverse_fill_rate": round(report.adverse_fill_rate, 4),
        "price_improvement_rate": round(report.price_improvement_rate, 4),
        "alert_triggered": report.alert_triggered,
        "generated_at": report.generated_at.isoformat(),
    }


@router.get("/records")
async def get_recent_records(
    request: Request,
    n: int = Query(100, ge=1, le=1000),
) -> List[Dict[str, Any]]:
    """Return the N most recent TCA records."""
    _require_auth(request)
    from execution.tca_recorder import get_tca_recorder
    return get_tca_recorder().get_recent_records(n=n)


@router.get("/alerts")
async def get_alerts(request: Request) -> List[Dict[str, Any]]:
    """Return brokers currently above the slippage alert threshold."""
    _require_auth(request)
    from execution.tca_recorder import get_tca_recorder, TCA_ALERT_THRESHOLD_BPS
    recorder = get_tca_recorder()
    reports = recorder.get_all_reports(last_n=TCA_ALERT_WINDOW)
    return [
        {
            "broker": r.broker,
            "mean_slippage_bps": round(r.mean_slippage_bps, 4),
            "threshold_bps": TCA_ALERT_THRESHOLD_BPS,
            "n_trades": r.n_trades,
        }
        for r in reports
        if r.alert_triggered
    ]
