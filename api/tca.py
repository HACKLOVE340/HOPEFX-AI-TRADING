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
GET /tca/stats               — rolling execution quality statistics
DELETE /tca/records          — flush in-memory records (admin)
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/tca", tags=["tca"])


def _require_auth(request: Request) -> dict[str, Any]:
    try:
        from auth.jwt_handler import verify_token as decode_token

        token = request.headers.get("Authorization", "").removeprefix("Bearer ").strip()
        if not token:
            raise HTTPException(status_code=401, detail="Missing token")
        _creds_exc = HTTPException(status_code=401, detail="Invalid token")
        return decode_token(token, _creds_exc)
    except HTTPException:
        raise
    except Exception as exc:
        logger.warning("TCA auth token decode failed: %s", exc)
        raise HTTPException(status_code=401, detail="Invalid or expired token") from None


@router.get("/report")
async def get_all_reports(
    request: Request,
    last_n: int = Query(500, ge=1, le=10000),
) -> list[dict[str, Any]]:
    """Return per-broker TCA reports for all brokers with recent fills."""
    _require_auth(request)
    from execution.tca_recorder import get_tca_recorder

    reports = get_tca_recorder().get_all_reports(last_n=last_n)
    return [_report_to_dict(r) for r in reports]


@router.get("/report/{broker}")
async def get_broker_report(
    broker: str,
    request: Request,
    symbol: str | None = Query(None),
    session: str | None = Query(None),
    last_n: int = Query(500, ge=1, le=10000),
) -> dict[str, Any]:
    """Return TCA report for a specific broker, optionally filtered by symbol/session."""
    _require_auth(request)
    from execution.tca_recorder import get_tca_recorder

    report = get_tca_recorder().get_report(broker=broker, symbol=symbol, session=session, last_n=last_n)
    if report is None:
        raise HTTPException(status_code=404, detail=f"No TCA data for broker '{broker}'")
    return _report_to_dict(report)


@router.get("/records")
async def get_recent_records(
    request: Request,
    n: int = Query(100, ge=1, le=1000),
    broker: str | None = Query(None),
    symbol: str | None = Query(None),
) -> list[dict[str, Any]]:
    """Return the N most recent TCA records, optionally filtered."""
    _require_auth(request)
    from execution.tca_recorder import get_tca_recorder

    recorder = get_tca_recorder()
    records = recorder.get_recent_records(n=n)

    if broker:
        records = [r for r in records if r.get("broker") == broker]
    if symbol:
        records = [r for r in records if r.get("symbol") == symbol]

    return records


@router.get("/alerts")
async def get_alerts(request: Request) -> list[dict[str, Any]]:
    """Return brokers currently above the slippage alert threshold."""
    _require_auth(request)
    from execution.tca_recorder import (
        TCA_ALERT_THRESHOLD_BPS,
        TCA_ALERT_WINDOW,
        get_tca_recorder,
    )

    recorder = get_tca_recorder()
    reports = recorder.get_all_reports(last_n=TCA_ALERT_WINDOW)
    return [
        {
            "broker": r.broker,
            "symbol": r.symbol,
            "mean_slippage_bps": round(r.mean_slippage_bps, 4),
            "p95_slippage_bps": round(r.p95_slippage_bps, 4),
            "threshold_bps": TCA_ALERT_THRESHOLD_BPS,
            "n_trades": r.n_trades,
            "generated_at": r.generated_at.isoformat(),
        }
        for r in reports
        if r.alert_triggered
    ]


@router.get("/stats")
async def get_stats(
    request: Request,
    n: int = Query(100, ge=1, le=5000),
) -> dict[str, Any]:
    """
    Rolling execution quality statistics across all brokers.

    Includes mean/p95/p99 slippage, fill rate, adverse fill rate,
    and per-session/per-broker breakdown.
    """
    _require_auth(request)
    from execution.tca_recorder import get_tca_recorder

    recorder = get_tca_recorder()
    records_raw = recorder.get_recent_records(n=n)

    if not records_raw:
        return {"n_trades": 0, "message": "No TCA records available yet."}

    slippages = [r["slippage_bps"] for r in records_raw]
    latencies = [r["latency_ms"] for r in records_raw]
    s2f = [r["signal_to_fill_ms"] for r in records_raw]
    count = len(slippages)

    # Per-session breakdown
    session_stats: dict[str, Any] = {}
    for session in ("london", "new_york", "asia", "off_hours"):
        sess_slips = [r["slippage_bps"] for r in records_raw if r.get("session") == session]
        if sess_slips:
            session_stats[session] = {
                "n_trades": len(sess_slips),
                "mean_slippage_bps": round(sum(sess_slips) / len(sess_slips), 4),
                "adverse_rate": round(sum(1 for s in sess_slips if s > 0) / len(sess_slips), 4),
            }

    # Per-broker breakdown
    broker_stats: dict[str, Any] = {}
    for b in {r.get("broker", "unknown") for r in records_raw}:
        b_slips = [r["slippage_bps"] for r in records_raw if r.get("broker") == b]
        if b_slips:
            sorted_b = sorted(b_slips)
            broker_stats[b] = {
                "n_trades": len(b_slips),
                "mean_slippage_bps": round(sum(b_slips) / len(b_slips), 4),
                "p95_slippage_bps": round(sorted_b[int(len(sorted_b) * 0.95)], 4),
            }

    sorted_slips = sorted(slippages)

    return {
        "n_trades": count,
        "mean_slippage_bps": round(sum(slippages) / count, 4),
        "median_slippage_bps": round(sorted_slips[count // 2], 4),
        "p95_slippage_bps": round(sorted_slips[int(count * 0.95)], 4),
        "p99_slippage_bps": round(sorted_slips[int(count * 0.99)], 4),
        "adverse_fill_rate": round(sum(1 for s in slippages if s > 0) / count, 4),
        "price_improvement_rate": round(sum(1 for s in slippages if s < 0) / count, 4),
        "mean_latency_ms": round(sum(latencies) / count, 2),
        "p95_latency_ms": round(sorted(latencies)[int(count * 0.95)], 2),
        "mean_signal_to_fill_ms": round(sum(s2f) / count, 2),
        "by_session": session_stats,
        "by_broker": broker_stats,
    }


@router.delete("/records")
async def flush_records(request: Request) -> dict[str, str]:
    """Flush all in-memory TCA records (admin only)."""
    payload = _require_auth(request)
    role = payload.get("role", "")
    if role not in ("admin", "superadmin"):
        raise HTTPException(status_code=403, detail="Admin role required")

    from execution.tca_recorder import get_tca_recorder

    recorder = get_tca_recorder()
    recorder._all_records.clear()
    recorder._records.clear()
    recorder._broker_slippage.clear()
    logger.warning("TCA records flushed by admin: %s", payload.get("sub"))
    return {"status": "flushed"}


# ── Serialisation helper ──────────────────────────────────────────────────────


def _report_to_dict(r: Any) -> dict[str, Any]:
    return {
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
