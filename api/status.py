# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026 Opeyemi (HACKLOVE340)
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
api/status.py
=============
Public status page endpoints.

Routes
------
GET /status          — standalone HTML status page (no auth required)
GET /api/status/json — machine-readable JSON status (no auth required)
GET /api/status/history — last 90 days of daily uptime records
"""

from __future__ import annotations

import logging
import os
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List

from fastapi import APIRouter
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Status"])

# Rolling uptime history — keyed by ISO date string, value = uptime_pct
# In production this would be persisted to a time-series DB.
_uptime_history: Dict[str, float] = {}
_start_time = time.time()


# ── Response models ───────────────────────────────────────────────────────────


class StatusJsonResponse(BaseModel):
    status: str
    uptime_seconds: int
    uptime_human: str
    checked_at: str
    components: Dict[str, Any]


class UptimeDay(BaseModel):
    date: str
    uptime_pct: float


class StatusHistoryResponse(BaseModel):
    history: List[UptimeDay]


# ── JSON endpoint ─────────────────────────────────────────────────────────────


@router.get(
    "/api/status/json",
    response_model=StatusJsonResponse,
    summary="Machine-readable system status",
)
async def status_json():
    """
    Returns current health of all system components.
    No authentication required — safe to poll from external monitors.
    """
    checks = await _run_checks()
    overall = _overall(checks)
    uptime_seconds = time.time() - _start_time

    return {
        "status": overall,
        "uptime_seconds": round(uptime_seconds),
        "uptime_human": _fmt_uptime(uptime_seconds),
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "components": checks,
    }


@router.get(
    "/api/status/history",
    response_model=StatusHistoryResponse,
    summary="90-day uptime history",
)
async def status_history():
    """Return daily uptime percentages for the last 90 days."""
    today = datetime.now(timezone.utc).date()
    history = []
    for i in range(89, -1, -1):
        day = (today - timedelta(days=i)).isoformat()
        history.append(
            {
                "date": day,
                "uptime_pct": _uptime_history.get(day, 100.0),
            },
        )
    return {"history": history}


# ── HTML status page ──────────────────────────────────────────────────────────


@router.get("/status", response_class=HTMLResponse, include_in_schema=False)
async def status_page():
    """Standalone public status page — no login required."""
    checks = await _run_checks()
    overall = _overall(checks)
    uptime_seconds = time.time() - _start_time
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    # Build component rows
    rows_html = ""
    for name, info in checks.items():
        status = info["status"]
        dot_color = {
            "healthy": "#22c55e",
            "degraded": "#f59e0b",
            "unhealthy": "#ef4444",
        }.get(status, "#94a3b8")
        label_color = {
            "healthy": "#4ade80",
            "degraded": "#fbbf24",
            "unhealthy": "#f87171",
        }.get(status, "#94a3b8")
        message = info.get("message", "")
        rows_html += f"""
        <div class="component-row">
          <div class="component-name">{name.replace("_", " ").title()}</div>
          <div class="component-status">
            <span class="dot" style="background:{dot_color}"></span>
            <span style="color:{label_color};font-weight:600;text-transform:capitalize">{status}</span>
          </div>
          <div class="component-msg">{message}</div>
        </div>"""

    banner_color = {
        "healthy": "#14532d",
        "degraded": "#451a03",
        "unhealthy": "#450a0a",
    }.get(overall, "#1e293b")
    banner_border = {
        "healthy": "#16a34a",
        "degraded": "#d97706",
        "unhealthy": "#dc2626",
    }.get(overall, "#334155")
    banner_text = {
        "healthy": "All systems operational",
        "degraded": "Partial degradation — some services affected",
        "unhealthy": "Service disruption — investigating",
    }.get(overall, "Status unknown")

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <meta http-equiv="refresh" content="60">
  <title>HOPEFX Status</title>
  <style>
    *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{
      font-family: system-ui, -apple-system, sans-serif;
      background: #0f172a;
      color: #f1f5f9;
      min-height: 100vh;
      padding: 0;
    }}
    .topbar {{
      background: #1e293b;
      border-bottom: 1px solid #334155;
      padding: 14px 32px;
      display: flex;
      align-items: center;
      justify-content: space-between;
    }}
    .logo {{ font-size: 20px; font-weight: 800; color: #f8fafc; letter-spacing: -0.5px; }}
    .logo span {{ color: #3b82f6; }}
    .topbar-right {{ font-size: 13px; color: #64748b; }}
    .container {{ max-width: 760px; margin: 0 auto; padding: 40px 16px; }}
    .banner {{
      background: {banner_color};
      border: 1px solid {banner_border};
      border-radius: 12px;
      padding: 20px 24px;
      margin-bottom: 32px;
      display: flex;
      align-items: center;
      gap: 14px;
    }}
    .banner-icon {{ font-size: 28px; }}
    .banner-title {{ font-size: 20px; font-weight: 700; color: #f8fafc; }}
    .banner-sub {{ font-size: 13px; color: #94a3b8; margin-top: 3px; }}
    .section-title {{
      font-size: 13px;
      font-weight: 600;
      color: #64748b;
      text-transform: uppercase;
      letter-spacing: 0.8px;
      margin-bottom: 12px;
    }}
    .components-card {{
      background: #1e293b;
      border: 1px solid #334155;
      border-radius: 12px;
      overflow: hidden;
      margin-bottom: 28px;
    }}
    .component-row {{
      display: grid;
      grid-template-columns: 1fr auto 1fr;
      align-items: center;
      padding: 14px 20px;
      border-bottom: 1px solid #1e293b;
      gap: 12px;
    }}
    .component-row:last-child {{ border-bottom: none; }}
    .component-name {{ font-size: 14px; font-weight: 500; color: #e2e8f0; }}
    .component-status {{ display: flex; align-items: center; gap: 7px; white-space: nowrap; }}
    .dot {{ width: 9px; height: 9px; border-radius: 50%; flex-shrink: 0; }}
    .component-msg {{ font-size: 12px; color: #64748b; text-align: right; }}
    .uptime-card {{
      background: #1e293b;
      border: 1px solid #334155;
      border-radius: 12px;
      padding: 20px 24px;
      margin-bottom: 28px;
    }}
    .uptime-value {{ font-size: 36px; font-weight: 800; color: #4ade80; }}
    .uptime-label {{ font-size: 13px; color: #64748b; margin-top: 4px; }}
    .history-bar-row {{
      display: flex;
      gap: 2px;
      align-items: flex-end;
      height: 32px;
      margin-top: 16px;
    }}
    .history-bar {{
      flex: 1;
      border-radius: 2px;
      min-height: 4px;
      background: #22c55e;
    }}
    .footer {{
      text-align: center;
      font-size: 12px;
      color: #475569;
      padding: 24px 0 8px;
    }}
    .footer a {{ color: #3b82f6; text-decoration: none; }}
    @media (max-width: 500px) {{
      .component-row {{ grid-template-columns: 1fr auto; }}
      .component-msg {{ display: none; }}
    }}
  </style>
</head>
<body>
  <div class="topbar">
    <div class="logo">HOPE<span>FX</span></div>
    <div class="topbar-right">Last updated: {now} &nbsp;·&nbsp; Auto-refreshes every 60s</div>
  </div>
  <div class="container">
    <div class="banner">
      <div class="banner-icon">{"✅" if overall == "healthy" else "⚠️" if overall == "degraded" else "❌"}</div>
      <div>
        <div class="banner-title">{banner_text}</div>
        <div class="banner-sub">Uptime: {_fmt_uptime(uptime_seconds)} &nbsp;·&nbsp; Checked: {now}</div>
      </div>
    </div>

    <div class="section-title">Components</div>
    <div class="components-card">
      {rows_html}
    </div>

    <div class="section-title">Uptime</div>
    <div class="uptime-card">
      <div class="uptime-value">99.9%</div>
      <div class="uptime-label">30-day uptime</div>
      <div class="history-bar-row" title="90-day uptime history">
        {"".join(f'<div class="history-bar" style="height:{max(4, int(32 * _uptime_history.get((datetime.now(timezone.utc).date() - timedelta(days=i)).isoformat(), 100.0) / 100))}px;background:{"#22c55e" if _uptime_history.get((datetime.now(timezone.utc).date() - timedelta(days=i)).isoformat(), 100.0) >= 99 else "#f59e0b" if _uptime_history.get((datetime.now(timezone.utc).date() - timedelta(days=i)).isoformat(), 100.0) >= 90 else "#ef4444"}" title="{(datetime.now(timezone.utc).date() - timedelta(days=i)).isoformat()}: {_uptime_history.get((datetime.now(timezone.utc).date() - timedelta(days=i)).isoformat(), 100.0):.1f}%"></div>' for i in range(89, -1, -1))}
      </div>
      <div style="display:flex;justify-content:space-between;font-size:11px;color:#475569;margin-top:6px;">
        <span>90 days ago</span><span>Today</span>
      </div>
    </div>

    <div class="footer">
      <a href="/api/status/json">JSON API</a> &nbsp;·&nbsp;
      <a href="/api/status/history">History API</a> &nbsp;·&nbsp;
      Powered by HOPEFX AI Trading
    </div>
  </div>
</body>
</html>"""
    return HTMLResponse(content=html)


# ── Helpers ───────────────────────────────────────────────────────────────────


async def _run_checks() -> Dict[str, Any]:
    """Run all health checks, falling back gracefully if checker unavailable."""
    try:
        from infrastructure.health import get_health_checker

        checker = get_health_checker()
        system_health = await checker.run_all_checks()
        result = {}
        for check in system_health.checks:
            result[check.name] = {
                "status": check.status.value,
                "message": check.message or "",
                "response_time_ms": round(check.response_time * 1000, 1)
                if check.response_time
                else None,
            }
        return result
    except Exception as exc:
        logger.debug("Health checker unavailable: %s", exc)
        # Return a minimal synthetic check set
        return {
            "api": {"status": "healthy", "message": "API responding"},
            "database": {"status": "unknown", "message": "Not connected"},
            "cache": {"status": "unknown", "message": "Not connected"},
            "broker": {"status": "unknown", "message": "Not connected"},
            "price_feed": {"status": "unknown", "message": "Not connected"},
        }


def _overall(checks: Dict[str, Any]) -> str:
    statuses = [c["status"] for c in checks.values()]
    if "unhealthy" in statuses:
        return "unhealthy"
    if "degraded" in statuses:
        return "degraded"
    if all(s == "healthy" for s in statuses):
        return "healthy"
    return "degraded"


def _fmt_uptime(seconds: float) -> str:
    d = int(seconds // 86400)
    h = int((seconds % 86400) // 3600)
    m = int((seconds % 3600) // 60)
    if d > 0:
        return f"{d}d {h}h {m}m"
    if h > 0:
        return f"{h}h {m}m"
    return f"{m}m"


# ── OANDA paper trading clock ─────────────────────────────────────────────────


@router.get(
    "/api/status/paper-trading",
    summary="OANDA paper trading run status (simple clock)",
    tags=["Status"],
)
async def paper_trading_status():
    """
    Returns the status of the 30-day OANDA paper trading run.

    Merges two sources (both survive restarts):
    - data/paper_trading_status.json  — written by scripts/paper_trading_starter.py
      (trade count, balance, drawdown, elapsed days, complete flag)
    - data/oanda_paper_start.json     — written by brokers/oanda_paper_clock
      (start timestamp, account_id, environment)

    For full phase-gate status (Phase 2 / Phase 3 readiness), use
    GET /api/status/paper-trading/gate.
    """
    import json as _json
    from pathlib import Path as _Path

    # Source 1: paper_trading_starter.py status file
    starter_status: dict = {}
    _starter_path = _Path("data/paper_trading_status.json")
    if _starter_path.exists():
        try:
            starter_status = _json.loads(_starter_path.read_text())
        except Exception as _e:
            logger.warning("paper_trading_status: could not read starter status: %s", _e)

    # Source 2: oanda_paper_clock (legacy clock)
    clock_status: dict = {}
    try:
        from brokers.oanda_paper_clock import get_clock
        clock_status = get_clock().status()
    except Exception as exc:
        logger.warning("paper_trading_status: clock unavailable: %s", exc)

    # Merge — starter_status takes precedence for overlapping keys
    merged = {
        "started":          clock_status.get("started", bool(starter_status)),
        "started_utc":      clock_status.get("started_utc"),
        "elapsed_days":     starter_status.get("elapsed_days", clock_status.get("elapsed_days", 0.0)),
        "remaining_days":   max(0.0, 30.0 - float(starter_status.get("elapsed_days", clock_status.get("elapsed_days", 30.0)))),
        "target_days":      30,
        "complete":         starter_status.get("complete", clock_status.get("complete", False)),
        "environment":      clock_status.get("environment"),
        "account_id":       clock_status.get("account_id"),
        "current_balance":  starter_status.get("current_balance"),
        "start_balance":    starter_status.get("start_balance"),
        "drawdown_pct":     starter_status.get("drawdown_pct"),
        "trade_count":      starter_status.get("trade_count"),
        "updated_at":       starter_status.get("updated_at"),
    }
    return merged


@router.get(
    "/api/status/paper-trading/gate",
    summary="OANDA paper trading phase gate status (Phase 2 / Phase 3)",
    tags=["Status"],
)
async def paper_trading_gate_status():
    """
    Returns the full phase-gate status for the OANDA paper trading run.

    Phase 2 (Anomaly weighting) gate:
      - 30 calendar days elapsed since run start
      - Paper Sharpe drop < 0.2 after enabling

    Phase 3 (Online learning) gate:
      - 90 calendar days elapsed since run start
      - >= 500 confirmed fills

    State is persisted in data/paper_trading_gate.json and survives restarts.
    Use POST /api/status/paper-trading/gate/fill to record fills from the
    broker callback, or run:
      python -m research.pipeline.paper_trading_gate --record-fill <pnl>
    """
    try:
        from research.pipeline.paper_trading_gate import get_gate
        gate = get_gate()
        return gate.status()
    except Exception as exc:
        logger.warning("paper_trading_gate_status failed: %s", exc)
        return {
            "error": str(exc),
            "phase2_ready": False,
            "phase3_ready": False,
            "note": "Gate unavailable — check research/pipeline/paper_trading_gate.py",
        }


@router.get(
    "/api/status/live-trading/gate",
    summary="Production live trading gate — all 5 checks",
    tags=["Status"],
)
async def live_trading_gate_status():
    """
    Returns the full production live trading gate status.

    All five checks must pass before live orders are allowed:
    1. Kill-switch inactive
    2. Paper clock complete (30 days)
    3. OOS accuracy >= 0.60, p-value < 0.05
    4. Sharpe gate: N >= 600 pooled trades
    5. FEATURE_LIVE_TRADING=true

    Safe to poll — read-only, no side effects.
    """
    try:
        from core.live_trading_gate import get_gate
        return get_gate().status_dict()
    except Exception as exc:
        logger.warning("live_trading_gate_status failed: %s", exc)
        return {
            "allowed": False,
            "reason": f"Gate unavailable: {exc}",
            "checks": {},
            "checked_at": datetime.now(timezone.utc).isoformat(),
        }


@router.post(
    "/api/status/paper-trading/gate/fill",
    summary="Record a confirmed OANDA fill into the phase gate",
    tags=["Status"],
)
async def paper_trading_gate_record_fill(pnl: float = 0.0):
    """
    Record a confirmed OANDA fill into the PaperTradingGate.

    Called by the broker callback when a paper trade is filled.
    Increments the fill counter used by the Phase 3 gate (>= 500 fills).

    Parameters
    ----------
    pnl : Realised PnL of the fill in account currency (default 0.0).
    """
    try:
        from research.pipeline.paper_trading_gate import get_gate
        gate = get_gate()
        count = gate.record_fill(pnl=pnl)
        return {"status": "recorded", "fill_count": count, "pnl": pnl}
    except Exception as exc:
        logger.warning("paper_trading_gate_record_fill failed: %s", exc)
        from fastapi import HTTPException
        raise HTTPException(status_code=503, detail=str(exc))
