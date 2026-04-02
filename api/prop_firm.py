# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
api/prop_firm.py
================
Prop firm challenge tracker API endpoint.

Routes
------
GET /api/risk/prop-firm-status   — current challenge metrics for the UI tracker
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from api.auth import TokenPayload, get_current_user

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/risk", tags=["Risk / Prop Firm"])


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
        from app import app_state
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

    except Exception as exc:
        logger.error("prop_firm_status error: %s", exc, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Prop firm status unavailable — check server logs",
        ) from None
