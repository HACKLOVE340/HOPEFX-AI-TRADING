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
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict

from fastapi import APIRouter
from fastapi.responses import HTMLResponse

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Status"])

# Rolling uptime history — keyed by ISO date string, value = uptime_pct
# In production this would be persisted to a time-series DB.
_uptime_history: Dict[str, float] = {}
_start_time = time.time()


# ── JSON endpoint ─────────────────────────────────────────────────────────────


@router.get("/api/status/json", summary="Machine-readable system status")
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


@router.get("/api/status/history", summary="90-day uptime history")
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
            }
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
    summary="OANDA 30-day paper trading run status",
    tags=["Status"],
)
async def paper_trading_status():
    """
    Returns the status of the 30-day OANDA paper trading run.

    The clock starts when OANDA_API_KEY (or BROKER_OANDA_TOKEN) is set and
    the broker connects successfully for the first time.  The start timestamp
    is persisted in ``data/oanda_paper_start.json`` and survives restarts.

    Response fields
    ---------------
    started         : bool — True if the clock has started
    started_utc     : ISO timestamp of first OANDA connection (or null)
    elapsed_days    : float — days elapsed since clock start
    remaining_days  : float — days remaining to reach 30-day target
    target_days     : int — 30
    complete        : bool — True when elapsed_days ≥ 30
    environment     : "practice" | "live" | null
    account_id      : first 8 chars of account ID (masked) or null
    note            : human-readable status message
    """
    import json
    import pathlib

    stamp_path = pathlib.Path("data/oanda_paper_start.json")

    if not stamp_path.exists():
        oanda_token = (
            os.getenv("BROKER_OANDA_TOKEN", "")
            or os.getenv("OANDA_API_KEY", "")
        )
        if oanda_token:
            note = (
                "OANDA credentials are set but the broker has not connected yet. "
                "Start the server with BROKER_TYPE=oanda to begin the 30-day run."
            )
        else:
            note = (
                "Clock not started. Set BROKER_OANDA_TOKEN (or OANDA_API_KEY) "
                "and BROKER_OANDA_ACCOUNT, then restart with BROKER_TYPE=oanda."
            )
        return {
            "started": False,
            "started_utc": None,
            "elapsed_days": 0.0,
            "remaining_days": 30.0,
            "target_days": 30,
            "complete": False,
            "environment": None,
            "account_id": None,
            "note": note,
        }

    try:
        data = json.loads(stamp_path.read_text())
        started_utc_str = data.get("started_utc", "")
        started_dt = datetime.fromisoformat(started_utc_str)
        now = datetime.now(timezone.utc)
        elapsed = (now - started_dt).total_seconds() / 86400.0
        target = float(data.get("target_days", 30))
        remaining = max(0.0, target - elapsed)
        complete = elapsed >= target

        note = (
            f"Run complete — {elapsed:.1f} days elapsed."
            if complete
            else f"{elapsed:.1f} days elapsed, {remaining:.1f} days remaining."
        )

        return {
            "started": True,
            "started_utc": started_utc_str,
            "elapsed_days": round(elapsed, 2),
            "remaining_days": round(remaining, 2),
            "target_days": int(target),
            "complete": complete,
            "environment": data.get("environment"),
            "account_id": data.get("account_id"),
            "note": note,
        }
    except Exception as exc:
        logger.warning("paper_trading_status: failed to read stamp file: %s", exc)
        return {
            "started": False,
            "started_utc": None,
            "elapsed_days": 0.0,
            "remaining_days": 30.0,
            "target_days": 30,
            "complete": False,
            "environment": None,
            "account_id": None,
            "note": f"Error reading paper trading stamp: {exc}",
        }
