# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
api/risk_tools.py
==================
REST API endpoints for new risk tools:
  - Margin stress simulation
  - Margin call handler history
  - Crowding monitor
"""
from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/risk", tags=["Risk Tools"])


class MarginStressRequest(BaseModel):
    accounts: list[dict[str, Any]]
    """List of broker account dicts: name, equity, positions, initial_margin_pct, maintenance_margin_pct."""


@router.post("/margin-stress/run-all")
async def margin_stress_run_all(request: MarginStressRequest) -> dict[str, Any]:
    """Run all margin stress scenarios across broker accounts."""
    try:
        from risk.margin_stress import (
            MarginStressSimulator,
            BrokerAccount,
        )
        accounts = []
        for acc_data in request.accounts:
            accounts.append(BrokerAccount(
                name=str(acc_data.get("name", "broker")),
                equity=float(acc_data.get("equity", 0)),
                positions=acc_data.get("positions", {}),
                initial_margin_pct=float(acc_data.get("initial_margin_pct", 0.02)),
                maintenance_margin_pct=float(acc_data.get("maintenance_margin_pct", 0.01)),
            ))
        sim = MarginStressSimulator()
        results = sim.run_all(accounts)
        return sim.summary(results)
    except Exception as exc:
        logger.error("Margin stress error: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/margin-call/history")
async def margin_call_history() -> dict[str, Any]:
    """Return margin call handler history."""
    try:
        from risk.margin_call_handler import margin_call_handler
        return {"history": margin_call_handler.history()}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/crowding")
async def crowding_status() -> dict[str, Any]:
    """Return strategy crowding status."""
    try:
        from risk.crowding import crowding_monitor
        return crowding_monitor.health()
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
