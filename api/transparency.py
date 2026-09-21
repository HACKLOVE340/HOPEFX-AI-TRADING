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

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from api.auth import TokenPayload, require_role
from api.error_details import safe_error

UTC = timezone.utc
logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/transparency", tags=["Transparency"])
_ROOT = Path(__file__).resolve().parent.parent


def _get_transparency_engine():
    """Retrieve the transparency engine from app state."""
    try:
        from core.app_state import app_state

        engine = getattr(app_state, "transparency_engine", None)
        if engine is None:
            from transparency.engine import ExecutionTransparencyEngine

            engine = ExecutionTransparencyEngine()
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
    user: TokenPayload = Depends(require_role("admin")),
):
    """
    Retrieve the audit log of all system actions (trades, config changes, risk events).

    Admin-only. The rest of this router is deliberately public — decisions,
    per-trade explanations, aggregate stats and the client statement exist so a
    client or auditor can verify the system's behaviour without an account. The
    audit log is a different kind of record: it carries config changes and risk
    events, i.e. operator actions rather than published trading conduct, so it
    is gated even though its neighbours are not.
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


def _compute_stats(decisions: list) -> dict[str, Any]:
    """Aggregate decision-quality stats from a list of decision dicts."""
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


@router.get("/stats")
async def get_transparency_stats():
    """Aggregate statistics about decision quality and model performance."""
    store = _get_decision_store()
    return _compute_stats(list(store) if store else [])


# ── Client audit statement (institutional transparency #9) ──────────────────────
def _active_model_summary() -> dict[str, Any]:
    """Active model + its honest OOS metrics, read from the committed registry.

    Degrades to an ``error`` field rather than raising — a statement endpoint must
    never 500 because one section is unavailable.
    """
    md = _ROOT / "ml" / "saved_models"
    try:
        reg = json.loads((md / "registry.json").read_text())
        active = reg.get("active_version")
        v = reg.get("versions", {}).get(active, {})
        return {
            "active_version": active,
            "horizon": v.get("horizon"),
            "oos_accuracy": v.get("oos_accuracy"),
            "oos_n": v.get("oos_n") or v.get("n_trades"),
            "oos_significant": v.get("oos_significant"),
            "sharpe_gate_passed": v.get("sharpe_gate_passed"),
            "sha256": (v.get("sha256") or "")[:12],
        }
    except (OSError, ValueError) as exc:
        return {"error": f"model registry unavailable: {exc}"}


@router.get("/statement")
async def client_statement() -> dict[str, Any]:
    """One auditable client statement bundling the controls a client/auditor wants:
    invariant-enforcement posture, the active model + its honest metrics, decision
    transparency stats, and audit-trail availability. Every section is best-effort
    and self-describing so the document is always returned.
    """
    statement: dict[str, Any] = {
        "generated_at": datetime.now(UTC).isoformat(),
        "disclaimer": (
            "Paper-trading / research statement. Model edge is statistically "
            "significant but below the production bar; not investment advice."
        ),
    }

    # 1. Safety / governance posture (always available — pure in-process).
    try:
        from invariants.enforcement import status as _inv_status

        s = _inv_status()
        statement["governance"] = {
            "invariant_mode": s.get("mode"),
            "blocking_enabled": s.get("blocking_enabled"),
            "enforced_checks": s.get("enforce_kinds"),
            "engine_healthy": s.get("engine_healthy"),
            "checker_errors": s.get("counters", {}).get("checker_errors"),
        }
    except Exception as exc:  # never let one section sink the statement
        statement["governance"] = {"error": safe_error(exc)}

    # 2. Active model + honest metrics.
    statement["model"] = _active_model_summary()

    # 3. Decision transparency (defensive — needs app state / decision store).
    try:
        store = _get_decision_store()
        decisions = list(store) if store else []
        statement["decisions"] = _compute_stats(decisions)
    except Exception as exc:
        statement["decisions"] = {"available": False, "reason": safe_error(exc)}

    # 4. Audit-trail availability.
    statement["audit_trail"] = {
        "decision_log": "decisions" in statement and "error" not in statement.get("decisions", {}),
        "hash_chain": "verified in CI (scripts/runtime_invariant_check.py)",
    }
    return statement
