# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
api/transparency.py
====================
Trade Transparency & Explainability API.
Exposes decision logs, factor breakdowns, and audit trails.
Connected to: transparency/engine.py, core/decision/HOPEFXDecisionEngine.py
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Query

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/transparency", tags=["Transparency"])


def _get_transparency_engine():
    """Retrieve the transparency engine from app state."""
    try:
        from core.app_state import app_state

        engine = getattr(app_state, "transparency_engine", None)
        if engine is None:
            from transparency.engine import TransparencyEngine

            engine = TransparencyEngine()
            app_state.transparency_engine = engine
        return engine
    except Exception:
        return None


def _get_decision_store():
    """Retrieve the decision store for logged trade decisions."""
    try:
        from core.app_state import app_state

        store = getattr(app_state, "decision_store", None)
        if store is None:
            app_state.decision_store = []
        return app_state.decision_store
    except Exception:
        return []


@router.get("/decisions")
async def get_decisions(
    limit: int = Query(30, ge=1, le=200),
    symbol: str | None = Query(None),
    outcome: str | None = Query(None),
):
    """
    Retrieve recent trade decisions with full factor breakdowns.
    Each decision includes: confidence, direction, reasoning, contributing factors,
    model version, execution time, and outcome.
    """
    store = _get_decision_store()
    decisions = list(store) if store else []

    # Filter by symbol
    if symbol:
        decisions = [d for d in decisions if d.get("symbol") == symbol]

    # Filter by outcome
    if outcome:
        decisions = [d for d in decisions if d.get("outcome") == outcome]

    # Sort by timestamp descending and limit
    decisions.sort(key=lambda d: d.get("timestamp", ""), reverse=True)
    decisions = decisions[:limit]

    return {"decisions": decisions, "total": len(store) if store else 0}


@router.get("/explain/{trade_id}")
async def explain_trade(trade_id: str):
    """
    Get detailed explanation for a specific trade decision.
    Returns the full factor breakdown, model inputs, and reasoning chain.
    """
    engine = _get_transparency_engine()
    store = _get_decision_store()

    # Find the decision
    decision = None
    for d in store or []:
        if d.get("id") == trade_id:
            decision = d
            break

    if not decision:
        raise HTTPException(status_code=404, detail=f"Trade decision {trade_id} not found")

    # Enrich with engine explanation if available
    explanation = decision.copy()
    if engine:
        try:
            enriched = await engine.explain_decision(trade_id)
            if enriched:
                explanation.update(enriched)
        except Exception as e:
            logger.warning(f"Transparency engine enrichment failed: {e}")

    return explanation


@router.get("/audit-log")
async def get_audit_log(
    limit: int = Query(50, ge=1, le=500),
    action_type: str | None = Query(None),
):
    """
    Retrieve the audit log of all system actions (trades, config changes, risk events).
    """
    try:
        from core.app_state import app_state

        audit_log = getattr(app_state, "audit_log", [])
    except Exception:
        audit_log = []

    entries = list(audit_log) if audit_log else []

    if action_type:
        entries = [e for e in entries if e.get("action_type") == action_type]

    entries.sort(key=lambda e: e.get("timestamp", ""), reverse=True)
    entries = entries[:limit]

    return {"entries": entries, "total": len(audit_log) if audit_log else 0}


@router.get("/stats")
async def get_transparency_stats():
    """
    Get aggregate statistics about decision quality and model performance.
    """
    store = _get_decision_store()
    decisions = list(store) if store else []

    total = len(decisions)
    if total == 0:
        return {
            "total_decisions": 0,
            "win_rate": 0,
            "avg_confidence": 0,
            "avg_execution_ms": 0,
            "skip_rate": 0,
        }

    wins = sum(1 for d in decisions if d.get("outcome") == "win")
    losses = sum(1 for d in decisions if d.get("outcome") == "loss")
    skips = sum(1 for d in decisions if d.get("direction") == "skip")
    resolved = wins + losses

    confidences = [d.get("confidence", 0) for d in decisions if d.get("confidence")]
    exec_times = [d.get("execution_ms", 0) for d in decisions if d.get("execution_ms")]

    return {
        "total_decisions": total,
        "win_rate": (wins / resolved * 100) if resolved > 0 else 0,
        "avg_confidence": sum(confidences) / len(confidences) if confidences else 0,
        "avg_execution_ms": sum(exec_times) / len(exec_times) if exec_times else 0,
        "skip_rate": (skips / total * 100) if total > 0 else 0,
        "wins": wins,
        "losses": losses,
        "pending": total - resolved - skips,
        "skipped": skips,
    }
