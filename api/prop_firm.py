# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
api/prop_firm.py
================
Prop firm challenge tracker API endpoints.

Routes
------
GET  /api/risk/prop-firm-status                          — current challenge metrics
GET  /api/risk/prop-firm/history                         — challenge history
GET  /api/risk/prop-firm/challenges                      — active challenges list
GET  /api/risk/prop-firm/daily-stats                     — daily P&L stats
GET  /api/risk/prop-firm/breach-alerts                   — breach alert log
POST /api/risk/prop-firm/breach-alerts/{id}/acknowledge  — acknowledge alert
GET  /api/risk/prop-firm/accounts                        — prop firm accounts
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel

from api.auth import TokenPayload, get_current_user
from api.db_store import db_get, db_set

logger = logging.getLogger(__name__)
UTC = timezone.utc

router = APIRouter(prefix="/api/risk", tags=["Risk / Prop Firm"])

# ── In-memory stores (Redis-backed via db_store) ──────────────────────────────
_CHALLENGES_KEY = "prop_firm:challenges:{uid}"
_ALERTS_KEY = "prop_firm:alerts:{uid}"
_DAILY_KEY = "prop_firm:daily:{uid}"


class PropFirmStatus(BaseModel):
    """Current prop firm challenge state returned to the dashboard."""

    # Drawdown metrics (fractions 0–1)
    daily_loss_pct: float
    daily_loss_limit: float
    max_drawdown_pct: float
    max_drawdown_limit: float
    # Profit progress
    profit_target_pct: float  # fraction of target achieved
    profit_target_amount: float  # $ amount earned so far
    profit_target_goal: float  # $ target (e.g. 10 000 for $100K account)
    # Trading days
    trading_days_completed: int
    trading_days_required: int
    # Status
    paused: bool
    kill_switch_active: bool
    ai_message: str
    # Raw equity
    current_equity: float
    starting_equity: float


@router.get(
    "/prop-firm-status",
    response_model=PropFirmStatus,
    summary="Prop firm challenge status",
)
async def prop_firm_status(user: TokenPayload = Depends(get_current_user)):
    """
    Return the current prop firm challenge metrics.

    Reads live state from PropComplianceEngine if available; falls back to
    prop_firm_mode.json defaults with zero drawdown when the engine is not
    yet initialised (e.g. before first trade).
    """
    try:
        from core.app_state import app_state
        from risk.compliance import PropComplianceEngine, PropFirmConfig

        # Try to get the engine from app state first
        engine = getattr(app_state, "prop_compliance_engine", None)

        if engine is None:
            # Build a read-only engine from config file for status display
            cfg = PropFirmConfig.from_file()
            engine = PropComplianceEngine(cfg)
            # Seed with a default $100K account so percentages make sense
            engine.update_equity(100_000.0)

        raw = engine.status()

        starting = raw.get("day_start_equity") or raw.get("current_equity", 100_000.0)
        current = raw.get("current_equity", starting)
        daily_dd = raw.get("daily_dd", 0.0)
        total_dd = raw.get("total_dd", 0.0)
        daily_limit = raw.get("daily_dd_limit", 0.05)
        max_limit = raw.get("max_dd_limit", 0.10)

        # Profit target: 10% of starting equity is the FTMO standard
        profit_goal = starting * 0.10
        profit_earned = max(0.0, current - starting)
        profit_pct = min(profit_earned / profit_goal, 1.0) if profit_goal > 0 else 0.0

        paused = raw.get("paused", False)
        ks_active = raw.get("kill_switch", False)

        # AI message
        if ks_active:
            ai_msg = "🔴 CHALLENGE PROTECTED — all positions closed (drawdown limit reached)"
        elif paused:
            ai_msg = "🛑 TRADING PAUSED — approaching drawdown limit"
        elif total_dd >= max_limit * 0.95:
            ai_msg = f"⚠️ At {total_dd / max_limit * 100:.0f}% of max drawdown — reduce size immediately"
        elif daily_dd >= daily_limit * 0.80:
            ai_msg = f"⚠️ At {daily_dd / daily_limit * 100:.0f}% of daily loss limit — halving position size"
        else:
            ai_msg = "✅ Within all prop firm limits — trading active"

        return PropFirmStatus(
            daily_loss_pct=daily_dd,
            daily_loss_limit=daily_limit,
            max_drawdown_pct=total_dd,
            max_drawdown_limit=max_limit,
            profit_target_pct=profit_pct,
            profit_target_amount=profit_earned,
            profit_target_goal=profit_goal,
            trading_days_completed=0,  # populated when trade log is wired
            trading_days_required=30,
            paused=paused,
            kill_switch_active=ks_active,
            ai_message=ai_msg,
            current_equity=current,
            starting_equity=starting,
        )

    except Exception:
        logger.exception("prop_firm_status error")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Prop firm status unavailable — check server logs",
        ) from None


# ── Extended models ───────────────────────────────────────────────────────────

class ChallengeRecord(BaseModel):
    challenge_id: str
    account_size: float
    phase: str
    result: str  # 'passed' | 'failed' | 'active'
    started_at: str
    ended_at: str | None
    profit_pct: float
    max_drawdown_pct: float


class BreachAlert(BaseModel):
    alert_id: str
    alert_type: str
    message: str
    severity: str  # 'warning' | 'critical'
    created_at: str
    acknowledged: bool


class DailyStat(BaseModel):
    date: str
    pnl: float
    trades: int
    drawdown_pct: float


class PropFirmAccount(BaseModel):
    account_id: str
    label: str
    account_size: float
    current_equity: float
    phase: str
    status: str
    broker: str
    started_at: str


# ── Helpers ───────────────────────────────────────────────────────────────────

def _get_challenges(user_id: str) -> list[dict]:
    key = _CHALLENGES_KEY.format(uid=user_id)
    stored = db_get(key)
    if stored and isinstance(stored, list):
        return stored
    # Derive from live engine if available
    challenges = []
    try:
        from core.app_state import app_state
        engine = getattr(app_state, "hopefx_engine", None)
        if engine is not None:
            fills = list(getattr(engine, "_fill_history", []))
            starting = float(getattr(engine, "_starting_equity", 100_000.0))
            current = starting
            for f in fills:
                current += float(getattr(f, "pnl", 0.0) or 0.0)
            profit_pct = (current - starting) / starting * 100 if starting > 0 else 0.0
            challenges.append({
                "challenge_id": "active-001",
                "account_size": starting,
                "phase": "phase_1",
                "result": "active",
                "started_at": datetime.now(UTC).replace(day=1).isoformat(),
                "ended_at": None,
                "profit_pct": round(profit_pct, 4),
                "max_drawdown_pct": 0.0,
            })
    except Exception as exc:
        logger.debug("prop firm challenges from engine: %s", exc)
    return challenges


def _get_alerts(user_id: str) -> list[dict]:
    key = _ALERTS_KEY.format(uid=user_id)
    stored = db_get(key)
    if stored and isinstance(stored, list):
        return stored
    return []


def _get_daily_stats(user_id: str, days: int = 30) -> list[dict]:
    key = _DAILY_KEY.format(uid=user_id)
    stored = db_get(key)
    if stored and isinstance(stored, list):
        return stored[-days:]
    # Build from engine fill history
    stats: dict[str, dict] = {}
    try:
        from core.app_state import app_state
        engine = getattr(app_state, "hopefx_engine", None)
        if engine is not None:
            fills = list(getattr(engine, "_fill_history", []))
            for f in fills:
                ts = f.filled_at if hasattr(f, "filled_at") else datetime.now(UTC)
                date_str = ts.strftime("%Y-%m-%d") if hasattr(ts, "strftime") else str(ts)[:10]
                pnl = float(getattr(f, "pnl", 0.0) or 0.0)
                if date_str not in stats:
                    stats[date_str] = {"date": date_str, "pnl": 0.0, "trades": 0, "drawdown_pct": 0.0}
                stats[date_str]["pnl"] += pnl
                stats[date_str]["trades"] += 1
    except Exception as exc:
        logger.debug("prop firm daily stats: %s", exc)
    return sorted(stats.values(), key=lambda x: x["date"])[-days:]


# ── Extended endpoints ────────────────────────────────────────────────────────

@router.get("/prop-firm/history", summary="Prop firm challenge history")
async def prop_firm_history(
    limit: int = Query(20, ge=1, le=100),
    user: TokenPayload = Depends(get_current_user),
) -> dict:
    challenges = _get_challenges(user.sub)
    return {"challenges": challenges, "total": len(challenges)}


@router.get("/prop-firm/challenges", summary="Active prop firm challenges")
async def prop_firm_challenges(user: TokenPayload = Depends(get_current_user)) -> dict:
    challenges = _get_challenges(user.sub)
    active = [c for c in challenges if c.get("result") == "active"]
    return {"challenges": active, "total": len(active)}


@router.get("/prop-firm/daily-stats", summary="Daily P&L stats for prop firm")
async def prop_firm_daily_stats(
    days: int = Query(30, ge=1, le=365),
    user: TokenPayload = Depends(get_current_user),
) -> dict:
    stats = _get_daily_stats(user.sub, days)
    return {"stats": stats, "total": len(stats)}


@router.get("/prop-firm/breach-alerts", summary="Prop firm breach alerts")
async def prop_firm_breach_alerts(user: TokenPayload = Depends(get_current_user)) -> dict:
    alerts = _get_alerts(user.sub)
    return {"alerts": alerts, "total": len(alerts)}


@router.post(
    "/prop-firm/breach-alerts/{alert_id}/acknowledge",
    summary="Acknowledge a breach alert",
)
async def acknowledge_breach_alert(
    alert_id: str,
    user: TokenPayload = Depends(get_current_user),
) -> dict:
    key = _ALERTS_KEY.format(uid=user.sub)
    alerts = _get_alerts(user.sub)
    updated = False
    for a in alerts:
        if a.get("alert_id") == alert_id:
            a["acknowledged"] = True
            updated = True
    if not updated:
        raise HTTPException(status_code=404, detail="Alert not found")
    db_set(key, alerts)
    return {"ok": True, "alert_id": alert_id}


@router.get("/prop-firm/accounts", summary="Prop firm accounts")
async def prop_firm_accounts(user: TokenPayload = Depends(get_current_user)) -> dict:
    accounts = []
    try:
        from core.app_state import app_state
        engine = getattr(app_state, "hopefx_engine", None)
        if engine is not None:
            starting = float(getattr(engine, "_starting_equity", 100_000.0))
            fills = list(getattr(engine, "_fill_history", []))
            current = starting
            for f in fills:
                current += float(getattr(f, "pnl", 0.0) or 0.0)
            accounts.append({
                "account_id": "main-001",
                "label": "Main Challenge Account",
                "account_size": starting,
                "current_equity": round(current, 2),
                "phase": "phase_1",
                "status": "active",
                "broker": getattr(getattr(engine, "broker", None), "name", "paper"),
                "started_at": datetime.now(UTC).replace(day=1).isoformat(),
            })
    except Exception as exc:
        logger.debug("prop firm accounts: %s", exc)
    return {"accounts": accounts, "total": len(accounts)}
