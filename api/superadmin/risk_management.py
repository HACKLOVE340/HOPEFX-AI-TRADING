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
from ._shared import _audit_payload, _require_superadmin, _utcnow, _log_superadmin_action
from api.error_details import safe_error
from analytics.ratios import downside_deviation

logger = logging.getLogger(__name__)
router = APIRouter()
UTC = timezone.utc

_CB_STATE_KEY = "superadmin:risk:circuit_breakers"
_STRESS_KEY = "superadmin:risk:stress_results"
_BREACH_KEY = "superadmin:risk:prop_breaches"


# ── Circuit Breakers ──────────────────────────────────────────────────────────


# Limit names this page has always displayed. They are thresholds inside one
# CircuitBreaker, not separately addressable breakers, so they are shown as
# placeholders and are never reported as live.
_PLACEHOLDER_LIMITS = (
    ("daily_drawdown", "max_daily_drawdown_pct"),
    ("total_drawdown", "max_total_drawdown_pct"),
    ("order_rate", "max_orders_per_minute"),
    ("position_size", "max_position_size_pct"),
    ("consecutive_losses", "max_consecutive_losses"),
)


def _live_cb_state(name: str, cb: Any) -> dict:
    """Project a registered CircuitBreaker onto the page's row shape.

    Read off ``get_status()`` rather than guessed attributes: the previous
    version reported ``failure_count``, ``last_failure_time`` and
    ``failure_threshold``, none of which exist on this class, so every row
    showed the ``getattr`` defaults regardless of the breaker's real state.
    """
    status = cb.get_status()
    breach = status.get("last_breach") or {}
    return {
        "name": name,
        "live": True,
        "state": status.get("state", "closed"),
        "manual_override": status.get("manual_override", False),
        "consecutive_losses": status.get("consecutive_losses", 0),
        "daily_drawdown": status.get("daily_drawdown", 0.0),
        "total_drawdown": status.get("total_drawdown", 0.0),
        "open_positions": status.get("open_positions", 0),
        "last_failure": breach.get("timestamp"),
        "last_failure_reason": breach.get("reason"),
        "limits": status.get("limits", {}),
    }


def _placeholder_cb_states() -> list[dict]:
    """Rows to render when no CircuitBreaker has been constructed yet.

    Marked ``live: False`` so the page cannot imply that a breaker is armed
    when none exists. This block previously invented six breaker names with
    plausible thresholds and served them as state.
    """
    try:
        from risk.circuit_breakers import RiskLimits

        limits = RiskLimits()
    except Exception:  # pragma: no cover - defensive
        limits = None

    return [
        {
            "name": name,
            "live": False,
            "state": "unknown",
            "threshold": getattr(limits, attr, None),
            "note": "no CircuitBreaker is registered; this is a configured limit, not live state",
        }
        for name, attr in _PLACEHOLDER_LIMITS
    ]


def _load_cb_states() -> list[dict]:
    """Circuit breaker rows for the superadmin risk page.

    Live registered breakers first. Only when none is registered does the page
    fall back to the Redis cache and then to placeholder rows, and both of
    those carry ``live: False`` so an operator can tell "the breaker is closed"
    from "there is no breaker".
    """
    states: list[dict] = []
    try:
        from risk.circuit_breakers import get_circuit_breakers

        for name, cb in get_circuit_breakers().items():
            try:
                states.append(_live_cb_state(name, cb))
            except Exception as exc:
                logger.warning("Circuit breaker %s could not be read: %s", name, exc)
    except Exception as exc:
        logger.debug("Circuit breaker live load: %s", exc)

    if states:
        _persist_cb_states(states)
        return states

    # Fall back to the last known snapshot, then to placeholders.
    try:
        from cache.redis_client import get_sync_redis_client

        rc = get_sync_redis_client()
        if rc:
            raw = rc.get(_CB_STATE_KEY)
            if raw:
                cached = json.loads(raw)
                if isinstance(cached, list) and cached:
                    # A cached row describes a breaker that is not registered
                    # right now, so it is history, not live state.
                    for row in cached:
                        if isinstance(row, dict):
                            row["live"] = False
                            row.setdefault("note", "cached snapshot; no breaker is currently registered")
                    return cached
    except Exception:  # nosec B110  # noqa: S110
        pass

    return _placeholder_cb_states()


def _persist_cb_states(states: list[dict]) -> None:
    try:
        from cache.redis_client import get_sync_redis_client

        rc = get_sync_redis_client()
        if rc:
            rc.set(_CB_STATE_KEY, json.dumps(states), ex=3600)
    except Exception:  # nosec B110  # noqa: S110
        pass


@router.get("/risk/circuit-breakers")
async def get_circuit_breakers(
    user: TokenPayload = Depends(_require_superadmin),
) -> dict:
    states = _load_cb_states()
    return {"circuit_breakers": states, "total": len(states)}


def _live_breaker(name: str):
    """Return the registered CircuitBreaker called *name*, or None."""
    try:
        from risk.circuit_breakers import get_circuit_breakers

        return get_circuit_breakers().get(name)
    except Exception as exc:
        logger.error("Circuit breaker registry unavailable: %s", exc)
        return None


def _actor(user: TokenPayload) -> str:
    """Who to write into the breaker's audit trail."""
    for attr in ("email", "username", "sub", "user_id"):
        value = getattr(user, attr, None)
        if isinstance(value, str) and value:
            return value
    return "superadmin"


@router.post("/risk/circuit-breakers/{name}/reset")
async def reset_circuit_breaker(
    name: str,
    reason: str = Query("manual reset from superadmin console", max_length=500),
    user: TokenPayload = Depends(_require_superadmin),
) -> dict:
    """Lift the manual hold on a breaker and re-arm its normal recovery path.

    This does not force the breaker closed. If the underlying drawdown breach
    is still live the breaker stays OPEN, because resuming trading through the
    limit on an operator's click is the failure this subsystem exists to
    prevent. The response says which of the two happened.
    """
    cb = _live_breaker(name)
    if cb is None:
        # Previously this edited a cached JSON blob and answered ok: true, so a
        # name that matched nothing real looked like a successful reset.
        return {
            "ok": False,
            "name": name,
            "error": f"No live circuit breaker named '{name}' is registered",
            "hint": "GET /superadmin/risk/circuit-breakers lists registered breakers; rows with live=false cannot be actioned",
        }

    cb.reset(reason=reason, authorized_by=_actor(user))
    state_after = cb.get_status().get("state")
    _persist_cb_states(_load_cb_states())
    _log_superadmin_action(user, "circuit_breaker_reset", {"name": name, "reason": reason, "state_after": state_after})
    return {
        "ok": True,
        "name": name,
        "new_state": state_after,
        "trading_resumed": state_after == "closed",
        "detail": (
            "manual hold lifted; breaker is closed and trading is permitted"
            if state_after == "closed"
            else "manual hold lifted, but the breaker remains open on live risk state and will recover on its own cooldown"
        ),
    }


@router.post("/risk/circuit-breakers/{name}/open")
async def force_open_circuit_breaker(
    name: str,
    reason: str = Query("manual halt from superadmin console", max_length=500),
    user: TokenPayload = Depends(_require_superadmin),
) -> dict:
    """Halt new orders on a breaker and hold it open until a human resets it.

    Open positions are not flattened and resting orders are not cancelled —
    that is the kill switch (`POST /superadmin/nuclear/kill-switch`).
    """
    cb = _live_breaker(name)
    if cb is None:
        return {
            "ok": False,
            "name": name,
            "error": f"No live circuit breaker named '{name}' is registered",
            "hint": "nothing was halted; use the kill switch to stop trading when no breaker is registered",
        }

    cb.force_open(reason=reason, authorized_by=_actor(user))
    state_after = cb.get_status().get("state")
    _persist_cb_states(_load_cb_states())
    _log_superadmin_action(
        user, "circuit_breaker_force_open", {"name": name, "reason": reason, "state_after": state_after}
    )
    return {
        "ok": True,
        "name": name,
        "new_state": state_after,
        "new_orders_blocked": state_after == "open",
        "detail": "new orders are rejected; open positions were not flattened",
    }


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
    except Exception:  # nosec B110  # noqa: S110
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
                # Downside deviation: RMS shortfall below zero over ALL periods.
                # This was `returns[returns < 0].std()` (F120) with a second
                # defect on top: `downside = downside or 1.0` substituted a
                # denominator of 1.0 whenever the real one was zero, so a series
                # with no losses — or with identical losses, whose dispersion is
                # zero — reported `mean_r * sqrt(252)` as a Sortino ratio. That
                # is a fabricated number, not a fallback.
                downside = downside_deviation(returns)
                sharpe = mean_r / std_r * (252**0.5)
                sortino = mean_r / downside * (252**0.5) if downside > 1e-12 else 0.0
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
                except Exception:  # nosec B110  # noqa: S110
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
    except Exception:  # nosec B110  # noqa: S110
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
    except Exception:  # nosec B110  # noqa: S110
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
        except Exception:  # nosec B110  # noqa: S110
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
        return {"ok": False, "error": safe_error(exc)}


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
    except Exception:  # nosec B110  # noqa: S110
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
                    meta = _audit_payload(r)
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
                        "current_drawdown_pct": round(
                            float(arr.mean()), 4
                        ),  # healer: ignore — nan_to_num applied above
                        "max_drawdown_pct": round(float(arr.max()), 4),
                        "accounts_in_drawdown": accounts_in_dd,
                        "accounts_near_limit": accounts_near_limit,
                        "drawdown_distribution": [
                            {
                                "bucket": "0-2%",
                                "count": int((arr < 0.02).sum()),  # healer: ignore — arr is nan_to_num guarded above
                            },
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
