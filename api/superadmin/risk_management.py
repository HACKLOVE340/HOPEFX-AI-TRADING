# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# AGPL-3.0 — Share all modifications
"""
api/superadmin/risk_management.py
==================================
Risk Management sub-router: circuit breakers, VaR/ES, stress tests,
prop firm breach tracking, and drawdown statistics.

Routes
------
GET  /superadmin/risk/circuit-breakers                   — all circuit breaker states
POST /superadmin/risk/circuit-breakers/{name}/reset      — reset a breaker
POST /superadmin/risk/circuit-breakers/{name}/open       — force-open a breaker
GET  /superadmin/risk/var                                — VaR / ES metrics
GET  /superadmin/risk/stress-tests                       — last stress test results
POST /superadmin/risk/stress-tests/run                   — run a stress scenario
GET  /superadmin/risk/prop-breaches                      — prop firm breach log
GET  /superadmin/risk/drawdown                           — drawdown statistics
"""

from __future__ import annotations

import json
import logging
from datetime import timezone
from typing import Any

from fastapi import APIRouter, Depends, Query

from api.auth import TokenPayload
from ._shared import _require_superadmin, _utcnow, _log_superadmin_action

logger = logging.getLogger(__name__)
router = APIRouter()
UTC = timezone.utc

_CB_STATE_KEY = "superadmin:risk:circuit_breakers"
_STRESS_KEY = "superadmin:risk:stress_results"
_BREACH_KEY = "superadmin:risk:prop_breaches"


# ── Circuit Breakers ──────────────────────────────────────────────────────────


def _load_cb_states() -> list[dict]:
    """Load circuit breaker states from the live risk module, falling back to Redis cache."""
    states: list[dict] = []
    try:
        # Attempt to get the global registry if it exists
        try:
            from risk.circuit_breakers import _GLOBAL_REGISTRY

            for name, cb in _GLOBAL_REGISTRY.items():
                states.append(
                    {
                        "name": name,
                        "state": cb.state.value if hasattr(cb, "state") else "closed",
                        "failure_count": getattr(cb, "failure_count", 0),
                        "last_failure": cb.last_failure_time.isoformat()
                        if getattr(cb, "last_failure_time", None)
                        else None,
                        "last_success": cb.last_success_time.isoformat()
                        if getattr(cb, "last_success_time", None)
                        else None,
                        "threshold": getattr(cb, "failure_threshold", 5),
                    }
                )
        except (ImportError, AttributeError):  # nosec B110
            pass
    except Exception as exc:
        logger.debug("Circuit breaker live load: %s", exc)

    if not states:
        # Fall back to Redis-persisted state
        try:
            from cache.redis_client import get_sync_redis_client

            rc = get_sync_redis_client()
            if rc:
                raw = rc.get(_CB_STATE_KEY)
                if raw:
                    states = json.loads(raw)
        except Exception:  # nosec B110
            pass

    if not states:
        # Bootstrap with known breaker names from the codebase
        states = [
            {
                "name": "daily_drawdown",
                "state": "closed",
                "failure_count": 0,
                "last_failure": None,
                "last_success": None,
                "threshold": 3,
            },
            {
                "name": "total_drawdown",
                "state": "closed",
                "failure_count": 0,
                "last_failure": None,
                "last_success": None,
                "threshold": 1,
            },
            {
                "name": "order_rate",
                "state": "closed",
                "failure_count": 0,
                "last_failure": None,
                "last_success": None,
                "threshold": 10,
            },
            {
                "name": "position_size",
                "state": "closed",
                "failure_count": 0,
                "last_failure": None,
                "last_success": None,
                "threshold": 5,
            },
            {
                "name": "broker_connection",
                "state": "closed",
                "failure_count": 0,
                "last_failure": None,
                "last_success": None,
                "threshold": 3,
            },
            {
                "name": "ml_engine",
                "state": "closed",
                "failure_count": 0,
                "last_failure": None,
                "last_success": None,
                "threshold": 5,
            },
        ]
        _persist_cb_states(states)
    return states


def _persist_cb_states(states: list[dict]) -> None:
    try:
        from cache.redis_client import get_sync_redis_client

        rc = get_sync_redis_client()
        if rc:
            rc.set(_CB_STATE_KEY, json.dumps(states), ex=3600)
    except Exception:  # nosec B110
        pass


@router.get("/risk/circuit-breakers")
async def get_circuit_breakers(
    user: TokenPayload = Depends(_require_superadmin),
) -> dict:
    states = _load_cb_states()
    return {"circuit_breakers": states, "total": len(states)}


@router.post("/risk/circuit-breakers/{name}/reset")
async def reset_circuit_breaker(
    name: str,
    user: TokenPayload = Depends(_require_superadmin),
) -> dict:
    states = _load_cb_states()
    found = False
    for cb in states:
        if cb["name"] == name:
            cb["state"] = "closed"
            cb["failure_count"] = 0
            cb["last_success"] = _utcnow().isoformat()
            found = True
            break
    if not found:
        return {"ok": False, "error": f"Circuit breaker '{name}' not found"}
    _persist_cb_states(states)
    # Also reset on live object if available
    try:
        from risk.circuit_breakers import _GLOBAL_REGISTRY

        if name in _GLOBAL_REGISTRY:
            _GLOBAL_REGISTRY[name].reset()
    except Exception:  # nosec B110
        pass
    _log_superadmin_action(user, "circuit_breaker_reset", {"name": name})
    return {"ok": True, "name": name, "new_state": "closed"}


@router.post("/risk/circuit-breakers/{name}/open")
async def force_open_circuit_breaker(
    name: str,
    user: TokenPayload = Depends(_require_superadmin),
) -> dict:
    states = _load_cb_states()
    found = False
    for cb in states:
        if cb["name"] == name:
            cb["state"] = "open"
            cb["last_failure"] = _utcnow().isoformat()
            found = True
            break
    if not found:
        return {"ok": False, "error": f"Circuit breaker '{name}' not found"}
    _persist_cb_states(states)
    try:
        from risk.circuit_breakers import _GLOBAL_REGISTRY

        if name in _GLOBAL_REGISTRY:
            _GLOBAL_REGISTRY[name].force_open()
    except Exception:  # nosec B110
        pass
    _log_superadmin_action(user, "circuit_breaker_force_open", {"name": name})
    return {"ok": True, "name": name, "new_state": "open"}


# ── VaR / ES Metrics ─────────────────────────────────────────────────────────


@router.get("/risk/var")
async def get_var_metrics(
    user: TokenPayload = Depends(_require_superadmin),
) -> dict:
    metrics: dict[str, Any] = {
        "var_95": 0.0,
        "var_99": 0.0,
        "expected_shortfall": 0.0,
        "max_drawdown": 0.0,
        "current_drawdown": 0.0,
        "sharpe_ratio": 0.0,
        "sortino_ratio": 0.0,
        "calmar_ratio": 0.0,
        "portfolio_value": 0.0,
        "currency": "USD",
        "computed_at": _utcnow().isoformat(),
    }

    # Try Redis cache first (populated by risk engine)
    try:
        from cache.redis_client import get_sync_redis_client

        rc = get_sync_redis_client()
        if rc:
            raw = rc.get("risk:var:latest")
            if raw:
                cached = json.loads(raw)
                metrics.update(cached)
                return metrics
    except Exception:  # nosec B110
        pass

    # Compute from DB trade history
    try:
        from database.connection import SessionLocal
        from database.models import Trade
        import numpy as np

        db = SessionLocal()
        try:
            trades = db.query(Trade).filter(Trade.status == "closed").order_by(Trade.closed_at.desc()).limit(500).all()
            if trades:
                pnls = [float(t.pnl or 0) for t in trades]
                returns = np.array(pnls)
                portfolio_value = (
                    sum(float(t.entry_price or 0) * float(t.quantity or 0) for t in trades[:10]) or 100_000.0
                )

                # Drop NaN before any aggregation to prevent silent propagation
                returns = returns[~np.isnan(returns)]

                # Historical VaR
                var_95 = float(np.percentile(returns, 5)) if len(returns) > 0 else 0.0
                var_99 = float(np.percentile(returns, 1)) if len(returns) > 0 else 0.0
                tail = returns[returns <= var_95]
                es = float(tail.mean()) if len(tail) > 0 else var_95

                # Drawdown
                cumulative = np.cumsum(returns)
                running_max = np.maximum.accumulate(cumulative)
                drawdowns = cumulative - running_max
                max_dd = float(drawdowns.min()) if len(drawdowns) > 0 else 0.0
                current_dd = float(drawdowns[-1]) if len(drawdowns) > 0 else 0.0

                # Ratios
                mean_r = float(np.nan_to_num(returns.mean()))
                std_r = float(np.nan_to_num(returns.std())) or 1.0
                downside_vals = returns[returns < 0]
                downside = float(np.nan_to_num(downside_vals.std())) if len(downside_vals) > 0 else 1.0
                downside = downside or 1.0
                sharpe = mean_r / std_r * (252**0.5)
                sortino = mean_r / downside * (252**0.5)
                calmar = mean_r / abs(max_dd) if max_dd != 0 else 0.0

                metrics.update(
                    {
                        "var_95": round(var_95, 2),
                        "var_99": round(var_99, 2),
                        "expected_shortfall": round(es, 2),
                        "max_drawdown": round(max_dd, 2),
                        "current_drawdown": round(current_dd, 2),
                        "sharpe_ratio": round(sharpe, 4),
                        "sortino_ratio": round(sortino, 4),
                        "calmar_ratio": round(calmar, 4),
                        "portfolio_value": round(portfolio_value, 2),
                        "trade_count": len(trades),
                    }
                )
                # Cache result
                try:
                    from cache.redis_client import get_sync_redis_client

                    rc = get_sync_redis_client()
                    if rc:
                        rc.set("risk:var:latest", json.dumps(metrics), ex=300)
                except Exception:  # nosec B110
                    pass
        finally:
            db.close()
    except Exception as exc:
        logger.warning("VaR computation error: %s", exc)

    return metrics


# ── Stress Tests ──────────────────────────────────────────────────────────────


@router.get("/risk/stress-tests")
async def get_stress_test_results(
    user: TokenPayload = Depends(_require_superadmin),
) -> dict:
    results: list[dict] = []
    try:
        from cache.redis_client import get_sync_redis_client

        rc = get_sync_redis_client()
        if rc:
            raw = rc.get(_STRESS_KEY)
            if raw:
                results = json.loads(raw)
    except Exception:  # nosec B110
        pass
    return {"results": results, "total": len(results)}


@router.post("/risk/stress-tests/run")
async def run_stress_test(
    body: dict,
    user: TokenPayload = Depends(_require_superadmin),
) -> dict:
    scenario = body.get("scenario", "COVID_CRASH_2020")

    # Get portfolio value from DB
    portfolio_value = 100_000.0
    try:
        from database.connection import SessionLocal
        from database.models import Trade

        db = SessionLocal()
        try:
            open_trades = db.query(Trade).filter(Trade.status == "open").all()
            portfolio_value = sum(float(t.entry_price or 0) * float(t.quantity or 0) for t in open_trades) or 100_000.0
        finally:
            db.close()
    except Exception:  # nosec B110
        pass

    # Run real stress test
    try:
        from risk.stress_test import StressTester

        tester = StressTester(position_value=portfolio_value, leverage=1.0)
        all_results = tester.run_all()

        # Find the requested scenario
        target = next((r for r in all_results if r.name == scenario), None)
        if target is None and all_results:
            target = all_results[0]

        results_list = [
            {
                "scenario": r.name,
                "name": r.name,
                "pnl_usd": round(r.pnl_usd, 2),
                "pnl_impact": round(r.pnl_usd, 2),
                "pnl_pct": round(r.pnl_pct, 2),
                "breaches_gate": r.breaches_gate,
                "run_at": _utcnow().isoformat(),
            }
            for r in all_results
        ]

        # Cache results
        try:
            from cache.redis_client import get_sync_redis_client

            rc = get_sync_redis_client()
            if rc:
                rc.set(_STRESS_KEY, json.dumps(results_list), ex=3600)
        except Exception:  # nosec B110
            pass

        _log_superadmin_action(user, "stress_test_run", {"scenario": scenario})
        return {
            "ok": True,
            "scenario": scenario,
            "results": results_list,
            "portfolio_value": portfolio_value,
            "run_at": _utcnow().isoformat(),
        }
    except Exception as exc:
        logger.error("Stress test run error: %s", exc)
        return {"ok": False, "error": str(exc)}


# ── Prop Firm Breaches ────────────────────────────────────────────────────────


@router.get("/risk/prop-breaches")
async def get_prop_breaches(
    status: str | None = Query(None),
    severity: str | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
    user: TokenPayload = Depends(_require_superadmin),
) -> dict:
    breaches: list[dict] = []

    # Pull from Redis cache
    try:
        from cache.redis_client import get_sync_redis_client

        rc = get_sync_redis_client()
        if rc:
            raw = rc.get(_BREACH_KEY)
            if raw:
                breaches = json.loads(raw)
    except Exception:  # nosec B110
        pass

    # Pull from DB audit log for real breach events
    try:
        from database.connection import SessionLocal
        from database.models import AuditLogEntry

        db = SessionLocal()
        try:
            rows = (
                db.query(AuditLogEntry)
                .filter(
                    AuditLogEntry.event_type.in_(
                        [
                            "prop_breach",
                            "daily_loss_breach",
                            "drawdown_breach",
                            "position_size_breach",
                            "news_trading_breach",
                        ]
                    )
                )
                .order_by(AuditLogEntry.created_at.desc())
                .limit(limit)
                .all()
            )
            existing_ids = {b["breach_id"] for b in breaches}
            for r in rows:
                bid = f"breach_{r.id}"
                if bid not in existing_ids:
                    meta = json.loads(r.metadata or "{}") if r.metadata else {}
                    breaches.append(
                        {
                            "breach_id": bid,
                            "user_id": str(r.user_id) if r.user_id else "unknown",
                            "username": meta.get("username", "unknown"),
                            "account_id": meta.get("account_id", "unknown"),
                            "breach_type": r.event_type.replace("_breach", ""),
                            "threshold": float(meta.get("threshold", 0)),
                            "actual_value": float(meta.get("actual_value", 0)),
                            "severity": meta.get("severity", "warning"),
                            "status": "open",
                            "detected_at": r.created_at.isoformat() if r.created_at else _utcnow().isoformat(),
                            "resolved_at": None,
                            "notes": r.detail,
                        }
                    )
        finally:
            db.close()
    except Exception as exc:
        logger.debug("Prop breaches DB: %s", exc)

    if status:
        breaches = [b for b in breaches if b.get("status") == status]
    if severity:
        breaches = [b for b in breaches if b.get("severity") == severity]

    return {"breaches": breaches[:limit], "total": len(breaches)}


# ── Drawdown Statistics ───────────────────────────────────────────────────────


@router.get("/risk/drawdown")
async def get_drawdown_stats(
    user: TokenPayload = Depends(_require_superadmin),
) -> dict:
    stats: dict[str, Any] = {
        "current_drawdown_pct": 0.0,
        "max_drawdown_pct": 0.0,
        "peak_equity": 0.0,
        "trough_equity": 0.0,
        "accounts_in_drawdown": 0,
        "accounts_near_limit": 0,
        "drawdown_distribution": [],
        "computed_at": _utcnow().isoformat(),
    }

    try:
        from database.connection import SessionLocal
        from database.models import Trade
        from database.user_models import User
        import numpy as np

        db = SessionLocal()
        try:
            # Per-user equity curves from closed trades
            users = db.query(User).filter(User.role == "trader").limit(200).all()
            accounts_in_dd = 0
            accounts_near_limit = 0
            all_dd_pcts: list[float] = []

            for u in users:
                trades = (
                    db.query(Trade)
                    .filter(Trade.user_id == u.user_id, Trade.status == "closed")
                    .order_by(Trade.closed_at)
                    .all()
                )
                if not trades:
                    continue
                pnls = [float(t.pnl or 0) for t in trades]
                cumulative = np.cumsum(pnls)
                running_max = np.maximum.accumulate(cumulative)
                drawdowns = (cumulative - running_max) / (running_max + 1e-9)
                current_dd = float(drawdowns[-1]) if len(drawdowns) > 0 else 0.0
                float(drawdowns.min()) if len(drawdowns) > 0 else 0.0
                all_dd_pcts.append(abs(current_dd))
                if abs(current_dd) > 0.05:
                    accounts_in_dd += 1
                if abs(current_dd) > 0.08:
                    accounts_near_limit += 1

            if all_dd_pcts:
                # Replace NaN with 0 before comparisons to prevent silent propagation
                arr = np.nan_to_num(np.array(all_dd_pcts), nan=0.0)
                stats.update(
                    {
                        "current_drawdown_pct": round(float(arr.mean()), 4),
                        "max_drawdown_pct": round(float(arr.max()), 4),
                        "accounts_in_drawdown": accounts_in_dd,
                        "accounts_near_limit": accounts_near_limit,
                        "drawdown_distribution": [
                            {
                                "bucket": "0-2%",
                                "count": int((arr < 0.02).sum()),
                            },  # healer: ignore — arr is nan_to_num guarded above
                            {"bucket": "2-5%", "count": int(((arr >= 0.02) & (arr < 0.05)).sum())},  # healer: ignore
                            {"bucket": "5-8%", "count": int(((arr >= 0.05) & (arr < 0.08)).sum())},  # healer: ignore
                            {"bucket": "8-10%", "count": int(((arr >= 0.08) & (arr < 0.10)).sum())},  # healer: ignore
                            {"bucket": ">10%", "count": int((arr >= 0.10).sum())},  # healer: ignore
                        ],
                    }
                )
        finally:
            db.close()
    except Exception as exc:
        logger.warning("Drawdown stats error: %s", exc)

    return stats
