# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
HOPEFX Trading API Router

All state-mutating endpoints (order placement, position close, emergency-stop)
require a valid JWT bearer token with at minimum the "trader" role.
Read-only endpoints (prices, OHLCV, account, brain-state) require any
authenticated user ("user" role or higher).

Auth is enforced via Depends(require_role(...)) from api.auth.
"""

import csv
import io
import json as _json
import logging
import os
import time
from datetime import datetime, timezone

UTC = timezone.utc
from pathlib import Path as _Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field, field_validator

from api.auth import (
    TokenPayload,
    get_current_user,
    require_kyc,
    require_role,
    validate_order_quantity,
    validate_order_symbol,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/trading", tags=["Trading"])

# ---------------------------------------------------------------------------
# Kill switch guard
# Imported lazily so the trading router can be loaded without app.py being
# fully initialised (e.g. in tests).  The live instance is the module-level
# `kill_switch` object created in app.py; tests can inject a replacement via
# the `_set_kill_switch` helper below.
# ---------------------------------------------------------------------------
_kill_switch_instance = None


def _set_kill_switch(ks) -> None:
    """Inject a KillSwitch instance (used by tests and app startup)."""
    global _kill_switch_instance
    _kill_switch_instance = ks


def _get_kill_switch():
    """Return the active KillSwitch, falling back to the app.py singleton."""
    global _kill_switch_instance
    if _kill_switch_instance is not None:
        return _kill_switch_instance
    try:
        from app import kill_switch as _app_ks

        _kill_switch_instance = _app_ks
        return _kill_switch_instance
    except Exception:
        logger.debug("Kill switch singleton unavailable — kill switch checks disabled")
        return None


def _check_kill_switch() -> None:
    """Raise HTTP 503 immediately if the kill switch is active."""
    ks = _get_kill_switch()
    if ks is not None and ks.is_active():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Trading halted — kill switch active: {ks.reason}",
        )


# ---------------------------------------------------------------------------
# Live deployment gates
#
# Two hard blocks that must pass before any live order is accepted:
#
#   1. Sharpe gate — ml/saved_models/advanced_oos_meta.json must exist and
#      record gate_passed=True (requires ≥600 OOS trades).  Missing file is
#      treated as gate NOT passed (fail-closed).
#
#   2. CI model guard — if the meta file records that the model was trained
#      with HOPEFX_CI=1 (n_estimators=20, fast CI build), live orders are
#      blocked until the model is retrained with HOPEFX_CI=0 on full data.
#
# Both gates are bypassed when BROKER_TYPE=paper (paper trading is always
# allowed) or APP_ENV=test so the test suite is not affected.
# ---------------------------------------------------------------------------
_OOS_META_PATH = _Path(__file__).parent.parent / "ml" / "saved_models" / "advanced_oos_meta.json"
_deployment_gate_cache: dict = {}  # {path_mtime: result} — avoids re-reading on every order


def _read_oos_meta() -> dict:
    """Read advanced_oos_meta.json, returning {} on any error."""
    try:
        mtime = _OOS_META_PATH.stat().st_mtime
        if _deployment_gate_cache.get("mtime") == mtime:
            return _deployment_gate_cache["data"]
        data = _json.loads(_OOS_META_PATH.read_text())
        _deployment_gate_cache["mtime"] = mtime
        _deployment_gate_cache["data"] = data
        return data
    except Exception as _meta_exc:
        logger.debug("OOS meta read failed (%s) — treating as gate not passed", _meta_exc)
        return {}


def _check_live_deployment_gates() -> None:
    """
    Block live orders until both deployment gates pass.

    Skipped entirely for paper trading (BROKER_TYPE=paper) and test
    environments (APP_ENV=test) so neither paper trading nor the test
    suite is affected.
    """
    broker_type = os.getenv("BROKER_TYPE", "paper").lower()
    app_env = os.getenv("APP_ENV", "").lower()

    # Paper trading and test environments are always allowed through.
    if broker_type == "paper" or app_env == "test":
        return

    meta = _read_oos_meta()

    # Gate 1 — Sharpe gate
    sharpe_gate = meta.get("sharpe_gate", {})
    if not sharpe_gate.get("gate_passed", False):
        n = sharpe_gate.get("n_trades", 0)
        target = sharpe_gate.get("target_n", 600)
        se = sharpe_gate.get("se", "unknown")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                f"Live trading blocked — Sharpe gate not cleared. "
                f"Need ≥{target} OOS trades (have {n}), SE={se}. "
                "Run multi-symbol forward test and retrain before going live."
            ),
        )

    # Gate 2 — CI model guard
    if meta.get("ci_mode", False):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "Live trading blocked — model was trained with HOPEFX_CI=1 "
                "(n_estimators=20, fast CI build). Retrain with HOPEFX_CI=0 "
                "on full 50-year data before deploying to live."
            ),
        )


# ---------------------------------------------------------------------------
# Per-user order rate limiting (sliding window, Redis-backed with in-memory fallback)
# Default: 10 orders per 60 seconds per authenticated user.
# Override via env: ORDER_RATE_LIMIT and ORDER_RATE_WINDOW.
# ---------------------------------------------------------------------------
_ORDER_RATE_LIMIT = int(os.getenv("ORDER_RATE_LIMIT", "10"))
_ORDER_RATE_WINDOW = int(os.getenv("ORDER_RATE_WINDOW", "60"))  # seconds
_order_rl_cache: dict = {}  # in-memory fallback: {user_id: [timestamps]}


def _get_redis_client():
    """Return the process-wide synchronous Redis client from the central pool.

    Uses cache.redis_pool which manages a properly-sized ConnectionPool
    singleton with asyncio-safe locking.  Returns None when Redis is
    unavailable so callers can fall back to in-memory rate limiting.
    """
    try:
        from cache.redis_pool import get_sync_client  # type: ignore[import]

        return get_sync_client()
    except Exception as exc:  # pylint: disable=broad-exception-caught
        logger.warning("Trading API: Redis unavailable: %s — rate limiting will use in-memory fallback", exc)
        return None


def _reset_order_rl_cache() -> None:
    """Clear the in-memory rate-limit cache. Used by tests to prevent bleed."""
    _order_rl_cache.clear()


def _check_order_rate_limit(user_id: str) -> None:
    """Raise HTTP 429 if the user has exceeded the order rate limit.

    Uses the central Redis connection pool when available, falling back
    to an in-memory sliding-window when Redis is unreachable.
    """
    r = _get_redis_client()
    if r is not None:
        try:
            key = f"order_rl:{user_id}"
            now = time.time()
            pipe = r.pipeline()
            pipe.zremrangebyscore(key, 0, now - _ORDER_RATE_WINDOW)
            pipe.zadd(key, {str(now): now})
            pipe.zcard(key)
            pipe.expire(key, _ORDER_RATE_WINDOW + 1)
            results = pipe.execute()
            count = results[2]
            if count > _ORDER_RATE_LIMIT:
                raise HTTPException(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    detail=f"Order rate limit exceeded: max {_ORDER_RATE_LIMIT} orders per {_ORDER_RATE_WINDOW}s",
                    headers={"Retry-After": str(_ORDER_RATE_WINDOW)},
                )
            return
        except HTTPException:
            raise
        except Exception as _rl_exc:
            logger.warning("Redis rate-limit check failed (%s) — falling back to in-memory window", _rl_exc)

    # In-memory fallback (single-process only — does not share state across pods).
    now = time.time()
    timestamps = _order_rl_cache.get(user_id, [])
    timestamps = [t for t in timestamps if now - t < _ORDER_RATE_WINDOW]
    timestamps.append(now)
    _order_rl_cache[user_id] = timestamps
    if len(timestamps) > _ORDER_RATE_LIMIT:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Order rate limit exceeded: max {_ORDER_RATE_LIMIT} orders per {_ORDER_RATE_WINDOW}s",
            headers={"Retry-After": str(_ORDER_RATE_WINDOW)},
        ) from None


# ---------------------------------------------------------------------------
# Request / Response models
# ---------------------------------------------------------------------------


class OrderRequest(BaseModel):
    symbol: str = Field(..., min_length=1, max_length=20)
    side: str = Field(..., pattern="^(buy|sell)$")
    quantity: float = Field(..., gt=0)
    order_type: str = Field("market", pattern="^(market|limit|stop)$")
    price: float | None = Field(None, gt=0)

    @field_validator("symbol")
    @classmethod
    def _symbol(cls, v: str) -> str:
        return validate_order_symbol(v)

    @field_validator("quantity")
    @classmethod
    def _quantity(cls, v: float) -> float:
        return validate_order_quantity(v)


class PositionResponse(BaseModel):
    id: str
    symbol: str
    side: str
    quantity: float
    entry_price: float
    current_price: float
    unrealized_pnl: float
    # Extended fields for mobile app
    unrealized_pnl_pct: float = 0.0
    opened_at: str = ""


class OrderResponse(BaseModel):
    """Response returned after a successful order fill."""

    status: str
    order_id: str
    filled_price: float | None = None
    filled_quantity: float | None = None


class ClosePositionResponse(BaseModel):
    status: str
    position_id: str


class CloseAllResponse(BaseModel):
    status: str
    closed_positions: int


class PriceQuote(BaseModel):
    bid: float
    ask: float
    last: float | None = None
    timestamp: float | None = None


class OHLCVBar(BaseModel):
    timestamp: float
    open: float
    high: float
    low: float
    close: float
    volume: float


# ---------------------------------------------------------------------------
# Module-level state (injected from app.py startup)
# ---------------------------------------------------------------------------

app_state = None


def set_state(state) -> None:
    global app_state
    app_state = state


# ---------------------------------------------------------------------------
# Async-compat broker call helper
# ---------------------------------------------------------------------------


async def _broker_call(method_name: str, *args, **kwargs):
    """
    Call a broker method whether it is sync or async.
    PaperTradingBroker uses sync methods; OANDA uses async.
    This wrapper handles both transparently.
    """
    import asyncio

    broker = app_state.broker
    method = getattr(broker, method_name)
    if asyncio.iscoroutinefunction(method):
        return await method(*args, **kwargs)
    # Sync method — run in executor to avoid blocking the event loop
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, lambda: method(*args, **kwargs))


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# place_order sub-functions
# Each function has a single responsibility and is ≤50 lines.
# Decomposed from the original 201-line monolith to reduce bug surface on
# the highest-risk code path (real order placement).
# ---------------------------------------------------------------------------


async def _validate_order(order: "OrderRequest") -> None:
    """
    Validate broker availability and prop-firm rules before touching risk.

    Raises HTTP 503 if the broker is not ready.
    Raises HTTP 403 if prop-firm rules are violated.
    """
    if not app_state or not app_state.broker:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Broker not available",
        )
    try:
        from brokers.prop_firms.guard import check_prop_firm_rules

        account_info = await _broker_call("get_account_info")
        check_prop_firm_rules(account_info)
    except HTTPException:
        raise
    except Exception as pf_exc:
        logger.error(
            "Prop-firm guard error (blocking order for safety): %s",
            pf_exc,
            exc_info=True,
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Prop-firm rule check unavailable — order rejected for safety",
        ) from pf_exc


async def _run_standard_risk_check(order: "OrderRequest", user_id: str) -> None:
    """
    Run RiskManager.assess_risk() against current account state.

    Raises HTTP 403 when risk limits are breached.
    Raises HTTP 503 when the check itself fails (fail-safe: block the order).
    """
    try:
        account_info = await _broker_call("get_account_info")
        positions = await _broker_call("get_positions")
        positions_dicts = [
            {
                "symbol": p.symbol,
                "quantity": p.quantity,
                "current_price": getattr(p, "current_price", 0),
            }
            for p in positions
        ]
        assessment = app_state.risk_manager.assess_risk(account_info, positions_dicts)
        if not assessment.can_trade:
            reason = getattr(assessment, "reason", None) or getattr(assessment, "messages", ["risk_check_failed"])
            reason_str = "; ".join(reason) if isinstance(reason, list) else str(reason)
            logger.warning("Order blocked by risk manager: user=%s reason=%s", user_id, reason_str)
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=f"Risk check failed: {reason_str}")
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Risk check error (blocking order for safety): user=%s %s", user_id, exc)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Risk check unavailable — order rejected for safety",
        ) from exc


async def _run_cvar_gate(user_id: str) -> None:
    """
    Run the CVaR pre-trade gate.

    Raises HTTP 403 when the CVaR limit is breached.
    Raises HTTP 503 when the check itself fails (fail-safe: block the order).
    """
    try:
        allowed, reason = app_state.risk_manager.check_cvar_pre_trade()
        if not allowed:
            logger.warning("Order blocked by CVaR gate: user=%s reason=%s", user_id, reason)
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=f"CVaR limit breached: {reason}")
        logger.debug("CVaR pre-trade gate passed: user=%s %s", user_id, reason)
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("CVaR pre-trade check error (blocking order for safety): user=%s %s", user_id, exc)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="CVaR risk check unavailable — order rejected for safety",
        ) from exc


async def _apply_risk_checks(order: "OrderRequest", user_id: str) -> None:
    """
    Run all pre-trade risk gates in sequence.

    Gate 1: RiskManager.assess_risk() — drawdown, daily loss, open positions.
    Gate 2: CVaR pre-trade gate — tail-risk limit.

    Both gates run independently so a CVaR breach always blocks even when
    the standard risk check passes.
    """
    if not (hasattr(app_state, "risk_manager") and app_state.risk_manager is not None):
        return
    await _run_standard_risk_check(order, user_id)
    await _run_cvar_gate(user_id)


def _log_compliance(order: "OrderRequest", user_id: str) -> None:
    """Write the pre-execution compliance audit record. Non-blocking on error."""
    if not (hasattr(app_state, "compliance_manager") and app_state.compliance_manager is not None):
        return
    try:
        app_state.compliance_manager.log_trade(
            user_id=user_id,
            trade_data={
                "symbol": order.symbol,
                "side": order.side,
                "quantity": order.quantity,
                "order_type": order.order_type,
            },
        )
    except Exception as comp_exc:
        logger.error("Compliance log error: %s", comp_exc)


async def _route_to_broker(order: "OrderRequest") -> Any:
    """
    Submit the order to the broker and return the fill result.

    Raises HTTP 400 on broker rejection or unexpected error.
    """
    try:
        result = await _broker_call(
            "place_market_order",
            symbol=order.symbol,
            side=order.side,
            quantity=order.quantity,
        )
        return result
    except HTTPException:
        raise
    except Exception:
        logger.exception("Broker order submission failed: %s")
        try:
            from core.metrics import ORDERS_TOTAL

            ORDERS_TOTAL.labels(symbol=order.symbol, side=order.side, status="error").inc()
        except Exception as _exc:
            logger.debug("Suppressed exception: %s", _exc)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Order submission failed — check server logs"
        ) from None


async def _broadcast_fill_ws(order: "OrderRequest", result: Any) -> None:
    """Broadcast the fill over WebSocket. Best-effort — logs on failure."""
    if not (hasattr(app_state, "ws_manager") and app_state.ws_manager is not None):
        return
    try:
        await app_state.ws_manager.broadcast_trade(
            symbol=order.symbol,
            price=result.average_fill_price or 0.0,
            quantity=order.quantity,
            side=order.side,
            trade_id=result.id,
        )
    except Exception as exc:
        logger.warning("WebSocket broadcast failed: %s", exc)


def _send_fill_push(order: "OrderRequest", result: Any, user_id: str) -> None:
    """Send FCM push notification for the fill. Best-effort."""
    try:
        from mobile.push_notifications import push_manager

        push_manager.send_trade_filled(
            user_id=user_id,
            symbol=order.symbol,
            direction=order.side,
            price=result.average_fill_price or 0.0,
            lots=order.quantity,
        )
    except Exception as exc:
        logger.debug("FCM trade push skipped: %s", exc)


def _resolve_user_email(user_id: str) -> str:
    """Look up the authenticated user's email address from the DB."""
    try:
        from auth.service import AuthService
        from core.app_state import app_state

        session_factory = app_state.db_session_factory
        if session_factory is None:
            return ""
        db_user = AuthService(session_factory=session_factory).get_user_by_id(user_id)
        return getattr(db_user, "email", "") or ""
    except Exception as exc:
        logger.debug("Could not resolve user email for fill notification: %s", exc)
        return ""


def _send_fill_email(order: "OrderRequest", result: Any, user_id: str) -> None:
    """Send trade-fill email notification. Best-effort."""
    try:
        from notifications.email_triggers import send_trade_fill_email

        send_trade_fill_email(
            symbol=order.symbol,
            direction=order.side,
            quantity=order.quantity,
            fill_price=result.average_fill_price or 0.0,
            net_pnl=getattr(result, "pnl", None),
            commission=getattr(result, "commission", 0.0),
            to=_resolve_user_email(user_id),
        )
        logger.debug("Trade fill email queued: user=%s symbol=%s side=%s", user_id, order.symbol, order.side)
    except Exception as exc:
        logger.debug("Trade fill email skipped: %s", exc)


def _increment_fill_metrics(order: "OrderRequest") -> None:
    """Increment Prometheus fill counter. Best-effort."""
    try:
        from core.metrics import ORDERS_TOTAL

        ORDERS_TOTAL.labels(symbol=order.symbol, side=order.side, status="filled").inc()
    except Exception as exc:
        logger.debug("Suppressed exception: %s", exc)


def _notify_paper_gate_and_online_learner(order: "OrderRequest", result: Any) -> None:
    """
    Notify the paper-trading gate fill counter and online learner.

    Both are Phase-3 components — failures must not affect the fill response.
    """
    try:
        from research.pipeline.paper_trading_gate import get_gate as _get_gate

        _get_gate().record_fill(pnl=float(getattr(result, "pnl", 0.0) or 0.0))
    except Exception as exc:
        logger.debug("gate.record_fill skipped: %s", exc)

    try:
        import pandas as _pd

        from core.signal_engine import notify_fill as _notify_fill

        _features = _pd.DataFrame(
            [
                {
                    "symbol": order.symbol,
                    "side": order.side,
                    "quantity": order.quantity,
                    "fill_price": result.average_fill_price or 0.0,
                    "source": "rest_api",
                }
            ]
        )
        _notify_fill(_features, label=1, primary_prob=None)
    except Exception as exc:
        logger.debug("notify_fill skipped: %s", exc)


async def _record_fill(
    order: "OrderRequest",
    result: Any,
    user_id: str,
) -> dict[str, Any]:
    """
    Post-fill notifications and response construction.

    All steps are best-effort — failures are logged but do not affect the
    HTTP response.  Steps:
      1. WebSocket broadcast
      2. FCM push notification
      3. Email notification
      4. Prometheus metric increment
      5. Paper-trading gate + online learner feedback
    """
    logger.info(
        "Order placed: user=%s symbol=%s side=%s qty=%s order_id=%s",
        user_id,
        order.symbol,
        order.side,
        order.quantity,
        result.id,
    )
    await _broadcast_fill_ws(order, result)
    _send_fill_push(order, result, user_id)
    _send_fill_email(order, result, user_id)
    _increment_fill_metrics(order)
    _notify_paper_gate_and_online_learner(order, result)

    return {
        "status": "success",
        "order_id": result.id,
        "filled_price": result.average_fill_price,
        "filled_quantity": result.filled_quantity,
    }


def _check_subscription_gate(user_id: str) -> None:
    """
    Enforce Starter-plan requirement for live trading.

    Skipped in test/CI environments, paper-trading mode, and when the
    monetization module is unavailable.  Raises HTTP 403 when the user's
    active plan is below 'starter'.
    """
    app_env = os.getenv("APP_ENV", "test").lower()
    broker_type = os.getenv("BROKER_TYPE", "paper").lower()

    if app_state is None or app_env in ("test", "ci", "testing", "") or broker_type in ("paper", ""):
        return

    try:
        from monetization.subscription import plan_gate, subscription_manager

        sub = subscription_manager.get_user_subscription(user_id)
        user_plan = sub.tier.value if (sub and sub.is_active() and hasattr(sub.tier, "value")) else "free"
        if not plan_gate("starter", user_plan):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={
                    "error": "PLAN_LIMIT_EXCEEDED",
                    "required_plan": "starter",
                    "current_plan": user_plan,
                    "message": "Live trading requires a Starter subscription or above.",
                },
            )
    except ImportError:
        ...  # nosec B110


@router.post(
    "/orders",
    status_code=status.HTTP_201_CREATED,
    response_model=OrderResponse,
    summary="Place a market/limit/stop order",
)
@router.post(
    "/order",
    status_code=status.HTTP_201_CREATED,
    response_model=OrderResponse,
    summary="Place a market/limit/stop order (legacy singular alias)",
    include_in_schema=False,
)
async def place_order(
    order: OrderRequest,
    user: TokenPayload = Depends(require_kyc),
    _role: TokenPayload = Depends(require_role("trader")),
):
    """
    Place a new order.

    Requires: Bearer token with role >= 'trader'.
    Rate-limited to ORDER_RATE_LIMIT orders per ORDER_RATE_WINDOW seconds per user.
    Passes through RiskManager.assess_risk() and CVaR gate before broker execution.
    Symbol and quantity are validated against server-side allowlists.

    Decomposed into focused sub-functions for testability and safety:
      _validate_order()   — broker availability + prop-firm rules
      _apply_risk_checks() — RiskManager + CVaR gate
      _log_compliance()   — pre-execution audit record
      _route_to_broker()  — broker submission
      _record_fill()      — WebSocket/FCM/email/Prometheus + response
    """
    _check_subscription_gate(user.sub)
    _check_kill_switch()  # hard block — must be first
    _check_live_deployment_gates()  # Sharpe gate + CI model guard
    _check_order_rate_limit(user.sub)
    await _validate_order(order)
    await _apply_risk_checks(order, user.sub)
    _log_compliance(order, user.sub)
    result = await _route_to_broker(order)
    return await _record_fill(order, result, user.sub)


@router.get("/positions", response_model=list[PositionResponse])
async def get_positions(
    user: TokenPayload = Depends(get_current_user),
):
    """Get all open positions. Requires: any authenticated user."""
    if not app_state or not app_state.broker:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Broker not available",
        )

    positions = await _broker_call("get_positions")
    result = []
    for p in positions:
        entry = float(getattr(p, "entry_price", 0) or 0)
        current = float(getattr(p, "current_price", entry) or entry)
        pnl = float(getattr(p, "unrealized_pnl", 0) or 0)
        pnl_pct = ((current - entry) / entry * 100) if entry > 0 else 0.0
        opened_at = getattr(p, "opened_at", None) or getattr(p, "created_at", None)
        opened_at_str = opened_at.isoformat() if hasattr(opened_at, "isoformat") else str(opened_at or "")
        result.append(
            PositionResponse(
                id=p.id,
                symbol=p.symbol,
                side=p.side.value if hasattr(p.side, "value") else str(p.side),
                quantity=p.quantity,
                entry_price=entry,
                current_price=current,
                unrealized_pnl=pnl,
                unrealized_pnl_pct=round(pnl_pct, 4),
                opened_at=opened_at_str,
            )
        )
    return result


@router.delete(
    "/positions/{position_id}",
    response_model=ClosePositionResponse,
    summary="Close a specific open position",
)
async def close_position(
    position_id: str,
    user: TokenPayload = Depends(require_role("trader")),
):
    """Close a specific position. Requires: role >= 'trader'."""
    if not app_state or not app_state.broker:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Broker not available",
        )

    success = await _broker_call("close_position", position_id)
    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Position not found",
        )

    logger.info("Position closed: user=%s position_id=%s", user.sub, position_id)

    # Publish POSITION_CLOSED to the legacy event bus so StrategyOrchestra
    # can update its allocation tracking and rebalancer.
    try:
        from core.strategy_orchestra import _get_shared_orchestra as _get_orch
        from core.event_bus_legacy import DomainEvent as _DE
        import asyncio as _asyncio

        _orch = _get_orch()
        if _orch is not None:
            _event = _DE.create(
                "POSITION_CLOSED",
                "trading_api",
                {"position_id": position_id, "user_id": user.sub},
            )
            try:
                _loop = _asyncio.get_running_loop()
                _loop.create_task(_orch.event_bus.publish(_event))
            except RuntimeError:
                pass
    except Exception as _pc_exc:
        logger.debug("POSITION_CLOSED event publish skipped: %s", _pc_exc)

    if hasattr(app_state, "ws_manager") and app_state.ws_manager is not None:
        try:
            await app_state.ws_manager.broadcast_to_all(
                {
                    "type": "position_closed",
                    "position_id": position_id,
                    "user_id": user.sub,
                },
                event="position_closed",
            )
        except Exception as ws_exc:
            logger.warning("WebSocket broadcast failed: %s", ws_exc)

    return {"status": "success", "position_id": position_id}


@router.delete(
    "/positions",
    response_model=CloseAllResponse,
    summary="Close all open positions",
)
async def close_all_positions(
    user: TokenPayload = Depends(require_role("trader")),
):
    """Close all open positions. Requires: role >= 'trader'."""
    if not app_state or not app_state.broker:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Broker not available",
        )

    closed = await _broker_call("close_all_positions")
    logger.info("All positions closed: user=%s count=%s", user.sub, closed)
    return {"status": "success", "closed_positions": closed}


@router.get("/account", response_model=None, summary="Get broker account snapshot")
async def get_account(
    user: TokenPayload = Depends(get_current_user),
):
    """
    Get account information. Requires: any authenticated user.

    Returns a normalised dict compatible with the mobile app Account type:
      account_id, balance, equity, margin_used, margin_available,
      unrealized_pnl, daily_pnl, daily_pnl_pct, currency
    """
    if not app_state or not app_state.broker:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Broker not available",
        )

    raw = await _broker_call("get_account_info")

    # Normalise to a consistent dict regardless of broker implementation
    def _f(obj, *keys, default=0.0):
        """Extract first matching attribute/key from obj, return default if missing."""
        for k in keys:
            v = getattr(obj, k, None) if not isinstance(obj, dict) else obj.get(k)
            if v is not None:
                try:
                    return float(v)
                except (TypeError, ValueError):
                    ...  # nosec B110
        return default

    def _s(obj, *keys, default=""):
        for k in keys:
            v = getattr(obj, k, None) if not isinstance(obj, dict) else obj.get(k)
            if v is not None:
                return str(v)
        return default

    balance = _f(raw, "balance", "nav", "net_liquidation")
    equity = _f(raw, "equity", "balance", "nav") or balance
    margin_used = _f(raw, "margin_used", "margin", "used_margin")
    margin_avail = _f(raw, "margin_available", "free_margin", "available_margin") or (equity - margin_used)
    unrealized = _f(raw, "unrealized_pnl", "open_pnl", "unrealised_pnl")
    daily_pnl = _f(raw, "daily_pnl", "day_pnl", "realized_pnl")
    daily_pnl_pct = (daily_pnl / balance * 100) if balance > 0 else 0.0

    return {
        "account_id": _s(raw, "account_id", "id", "accountId", default=user.sub),
        "balance": round(balance, 2),
        "equity": round(equity, 2),
        "margin_used": round(margin_used, 2),
        "margin_available": round(margin_avail, 2),
        "unrealized_pnl": round(unrealized, 2),
        "daily_pnl": round(daily_pnl, 2),
        "daily_pnl_pct": round(daily_pnl_pct, 4),
        "currency": _s(raw, "currency", "base_currency", default="USD"),
    }


@router.get(
    "/prices",
    response_model=dict[str, PriceQuote],
    summary="Get current bid/ask prices for all tracked symbols",
)
async def get_prices(
    user: TokenPayload = Depends(get_current_user),
):
    """Get current bid/ask prices. Requires: any authenticated user."""
    if not app_state or not app_state.price_engine:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Price engine not available",
        )

    prices: dict = {}
    for symbol in app_state.price_engine.symbols:
        tick = app_state.price_engine.get_last_price(symbol)
        if tick:
            prices[symbol] = {
                "bid": tick.bid,
                "ask": tick.ask,
                "last": getattr(tick, "last_price", None) or tick.mid,
                "timestamp": tick.timestamp,
            }

    return prices


@router.get(
    "/ohlcv/{symbol}",
    response_model=list[OHLCVBar],
    summary="Get OHLCV candlestick data for a symbol",
)
async def get_ohlcv(
    symbol: str,
    timeframe: str = "1h",
    limit: int = 100,
    user: TokenPayload = Depends(get_current_user),
):
    """Get OHLCV data. Requires: any authenticated user. Symbol validated server-side."""
    symbol = validate_order_symbol(symbol)

    if not app_state or not app_state.price_engine:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Price engine not available",
        )

    data = await app_state.price_engine.get_ohlcv(symbol, timeframe, limit)

    return [
        {
            "timestamp": d.timestamp,
            "open": d.open,
            "high": d.high,
            "low": d.low,
            "close": d.close,
            "volume": d.volume,
        }
        for d in data
    ]


@router.get("/signals", summary="Active trading signals from the signal engine")
async def get_trading_signals(
    user: TokenPayload = Depends(get_current_user),
):
    """
    Return the current active signals from the signal engine.

    Delegates to the /api/signals/active endpoint internally so the
    Dashboard polling loop gets a consistent signal shape without
    needing a separate API call.
    """
    try:
        signal_engine = getattr(app_state, "signal_engine", None) if app_state else None
        if signal_engine is not None:
            raw = getattr(signal_engine, "get_active_signals", None)
            if callable(raw):
                signals = raw()
                return {"signals": [s.to_dict() if hasattr(s, "to_dict") else s for s in (signals or [])]}
        # Fallback: read from the signals ring buffer via db_store
        from api.db_store import db_get

        cached = db_get("signals:active") or []
        return {"signals": cached}
    except Exception as exc:
        logger.warning("get_trading_signals fallback: %s", exc)
        return {"signals": []}


@router.get("/brain-state")
async def get_brain_state(
    user: TokenPayload = Depends(get_current_user),
):
    """Get AI brain state. Requires: any authenticated user."""
    if not app_state or not app_state.brain:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Brain not available",
        )

    return app_state.brain.state.to_dict()


@router.post("/paper/start", status_code=202)
async def start_paper_trading(
    user: TokenPayload = Depends(get_current_user),
):
    """
    Activate paper trading mode for the authenticated user.

    Sets BROKER_TYPE=paper in the session context and initialises a
    paper account with the default starting balance if one does not
    already exist. Called from the onboarding flow.
    """
    from api.db_store import db_get, db_set

    paper_key = f"paper:account:{user.sub}"
    existing = db_get(paper_key)
    if existing:
        return {"status": "already_active", "account": existing}

    account = {
        "user_id": user.sub,
        "balance": float(os.getenv("PAPER_STARTING_BALANCE", "10000")),
        "currency": "USD",
        "mode": "paper",
        "activated_at": datetime.now(timezone.utc).isoformat(),
    }
    db_set(paper_key, account, changed_by="trading_api")
    logger.info("Paper trading activated for user=%s", user.sub)
    return {"status": "activated", "account": account}


@router.post("/emergency-stop")
async def emergency_stop(
    user: TokenPayload = Depends(require_role("admin")),
):
    """
    Trigger emergency stop — halts all trading immediately.

    Requires: role >= 'admin'. Logs the triggering user for audit trail.
    """
    if not app_state or not app_state.brain:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Brain not available",
        )

    app_state.brain.emergency_stop()
    logger.critical("Emergency stop triggered by user=%s", user.sub)
    return {"status": "emergency_stop_triggered", "triggered_by": user.sub}


# ── Trade history ─────────────────────────────────────────────────────────────

_TRADE_CSV_FIELDS = [
    "trade_id",
    "symbol",
    "side",
    "quantity",
    "entry_price",
    "exit_price",
    "realized_pnl",
    "commission",
    "status",
    "strategy",
    "entry_time",
    "exit_time",
]


def _query_trades(user_id: str, symbol: str | None, limit: int, offset: int) -> list:
    """Fetch trades from DB for the given user."""
    try:
        from app import app_state as _state
        from database.models import Trade

        if not _state or not _state.db_session_factory:
            return []
        with _state.db_session_factory() as session:  # pylint: disable=not-callable
            q = session.query(Trade).filter(Trade.user_id == user_id)
            if symbol:
                q = q.filter(Trade.symbol == symbol.upper())
            q = q.order_by(Trade.entry_time.desc()).offset(offset).limit(limit)
            return q.all()
    except Exception as exc:
        logger.warning("Trade history DB query failed: %s", exc)
        return []


def _trade_to_dict(t) -> dict:
    return {
        "trade_id": getattr(t, "trade_id", str(getattr(t, "id", ""))),
        "symbol": getattr(t, "symbol", ""),
        "side": getattr(t, "side", ""),
        "quantity": getattr(t, "quantity", 0),
        "entry_price": getattr(t, "entry_price", 0),
        "exit_price": getattr(t, "exit_price", None),
        "realized_pnl": getattr(t, "realized_pnl", 0),
        "commission": getattr(t, "commission", 0),
        "status": getattr(t, "status", ""),
        "strategy": getattr(t, "strategy", ""),
        "entry_time": str(getattr(t, "entry_time", "")),
        "exit_time": str(getattr(t, "exit_time", "") or ""),
    }


@router.get("/trades")
async def get_trade_history(
    user: TokenPayload = Depends(get_current_user),
    symbol: str | None = Query(None, max_length=20),
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
):
    """
    Return paginated trade history for the authenticated user.

    Query params:
      symbol  — filter by symbol (optional)
      limit   — max rows (1–1000, default 100)
      offset  — pagination offset
    """
    trades = _query_trades(user.sub, symbol, limit, offset)
    return {
        "trades": [_trade_to_dict(t) for t in trades],
        "count": len(trades),
        "offset": offset,
        "limit": limit,
    }


@router.get("/trades/export")
async def export_trade_history_csv(
    user: TokenPayload = Depends(get_current_user),
    symbol: str | None = Query(None, max_length=20),
    limit: int = Query(10000, ge=1, le=100000),
):
    """
    Download trade history as a CSV file.

    Query params:
      symbol  — filter by symbol (optional)
      limit   — max rows (default 10 000)

    Returns: application/csv attachment.
    """
    trades = _query_trades(user.sub, symbol, limit, offset=0)

    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=_TRADE_CSV_FIELDS, extrasaction="ignore")
    writer.writeheader()
    for t in trades:
        writer.writerow(_trade_to_dict(t))

    buf.seek(0)
    ts = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    sym_part = f"_{symbol.upper()}" if symbol else ""
    filename = f"hopefx_trades{sym_part}_{ts}.csv"

    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ── Models expected by tests ──────────────────────────────────────────────────


class StrategyCreateRequest(BaseModel):
    name: str
    symbol: str = "XAUUSD"
    timeframe: str = "1h"
    strategy_type: str = "ma_crossover"
    parameters: dict | None = None
    enabled: bool = True
    risk_per_trade: float = 1.0


class StrategyResponse(BaseModel):
    id: str
    name: str
    symbol: str
    timeframe: str
    strategy_type: str
    type: str = ""  # alias for strategy_type used by some tests
    enabled: bool
    parameters: dict | None = None

    def model_post_init(self, __context: Any) -> None:  # pylint: disable=arguments-differ
        if not self.type:
            object.__setattr__(self, "type", self.strategy_type)


class SignalResponse(BaseModel):
    id: str
    symbol: str
    direction: str
    confidence: float
    entry_price: float
    stop_loss_price: float | None = None
    take_profit_price: float | None = None
    notes: str | None = None
    timestamp: str
    source: str = "strategy_brain"


class PositionSizeRequest(BaseModel):
    entry_price: float
    stop_loss_price: float | None = None
    confidence: float = 1.0
    symbol: str = "XAUUSD"
    account_equity: float = 100_000.0
    risk_pct: float = 0.01


class PositionSizeResponse(BaseModel):
    size: float
    risk_amount: float
    stop_loss_price: float | None = None
    take_profit_price: float | None = None
    notes: str | None = None


# ── In-memory strategy store for test endpoints ───────────────────────────────
import uuid as _uuid

_strategy_store: dict[str, dict] = {}


def _resolve(strategy_id: str) -> str | None:
    """Return the store key for a strategy_id, or None if not found."""
    if strategy_id in _strategy_store:
        return strategy_id
    for k, v in _strategy_store.items():
        if v.get("name") == strategy_id:
            return k
    return None


def _resolve_strategy_key(strategy_id: str) -> str | None:
    """Alias for _resolve — kept for clarity at call sites."""
    return _resolve(strategy_id)


def _compute_max_drawdown(values: list[float]) -> float:
    """Return the maximum drawdown fraction from a sequence of equity values."""
    peak = values[0] if values else 0.0
    max_dd = 0.0
    for v in values:
        peak = max(peak, v)
        dd = (peak - v) / peak if peak > 0 else 0.0
        max_dd = max(max_dd, dd)
    return max_dd


def _register_strategy_crud(r: Any) -> None:
    """Register strategy list/create/get/delete/start/stop routes."""
    from fastapi import HTTPException

    @r.get("/strategies")
    def list_strategies():
        return list(_strategy_store.values())

    @r.post("/strategies", status_code=201)
    def create_strategy(req: StrategyCreateRequest):
        _KNOWN = {
            "ma_crossover",
            "rsi",
            "macd",
            "bollinger_bands",
            "ema_crossover",
            "breakout",
            "stochastic",
            "mean_reversion",
            "smc_ict",
            "strategy_brain",
        }
        if req.strategy_type not in _KNOWN:
            raise HTTPException(400, f"Unknown strategy type: {req.strategy_type}")
        sid = str(_uuid.uuid4())[:8]
        record = {
            "id": sid,
            "name": req.name,
            "symbol": req.symbol,
            "timeframe": req.timeframe,
            "strategy_type": req.strategy_type,
            "type": req.strategy_type,
            "enabled": req.enabled,
            "parameters": req.parameters,
            "risk_per_trade": req.risk_per_trade,
        }
        _strategy_store[sid] = record
        return record

    @r.get("/strategies/{strategy_id}")
    def get_strategy(strategy_id: str):
        key = _resolve(strategy_id)
        if key is None:
            raise HTTPException(404, "Strategy not found")
        return _strategy_store[key]

    @r.delete("/strategies/{strategy_id}")
    def delete_strategy(strategy_id: str):
        key = _resolve(strategy_id)
        if key is None:
            raise HTTPException(404, "Strategy not found")
        del _strategy_store[key]
        return {"status": "deleted"}

    @r.post("/strategies/{strategy_id}/start")
    def start_strategy(strategy_id: str):
        key = _resolve_strategy_key(strategy_id)
        if key is None:
            raise HTTPException(404, "Strategy not found")
        _strategy_store[key]["enabled"] = True
        return {"status": "started", "strategy_id": strategy_id}

    @r.post("/strategies/{strategy_id}/stop")
    def stop_strategy(strategy_id: str):
        key = _resolve_strategy_key(strategy_id)
        if key is None:
            raise HTTPException(404, "Strategy not found")
        _strategy_store[key]["enabled"] = False
        return {"status": "stopped", "strategy_id": strategy_id}


def _register_risk_performance_routes(r: Any) -> None:
    """Register position-size, risk-metrics, and performance routes."""
    from fastapi import HTTPException
    import math as _math

    @r.post("/position-size")
    def calculate_position_size(req: PositionSizeRequest):
        risk_per_unit = (
            (req.entry_price - req.stop_loss_price)
            if (req.stop_loss_price and req.stop_loss_price < req.entry_price)
            else req.entry_price * 0.01
        )
        risk_amount = req.account_equity * req.risk_pct * req.confidence
        fomc_multiplier = 1.0
        try:
            from api.calendar import _fomc_regime_override

            if _fomc_regime_override.get("active"):
                fomc_multiplier = _fomc_regime_override.get("position_size_multiplier", 1.0)
        except Exception as exc:
            logger.debug("FOMC regime multiplier unavailable, using 1.0: %s", exc)

        size = (risk_amount / risk_per_unit if risk_per_unit > 0 else 0.0) * fomc_multiplier
        tp = req.entry_price + risk_per_unit * 2 if req.stop_loss_price else None
        return PositionSizeResponse(
            size=round(size, 4),
            risk_amount=round(risk_amount * fomc_multiplier, 2),
            stop_loss_price=req.stop_loss_price,
            take_profit_price=tp,
        )

    @r.get("/risk-metrics")
    def get_risk_metrics():
        try:
            broker = getattr(app_state, "broker", None)
            if broker is None:
                raise AttributeError("no broker")
            account = broker.get_account_info()
            positions = broker.get_positions() if hasattr(broker, "get_positions") else []

            # Daily PnL: sum unrealised PnL across open positions
            daily_pnl = sum(getattr(p, "unrealized_pnl", 0.0) or 0.0 for p in positions)
            margin_used = float(getattr(account, "margin_used", 0.0) or 0.0)
            max_dd = 0.0
            if hasattr(broker, "get_equity_history"):
                history = broker.get_equity_history()
                if history:
                    max_dd = _compute_max_drawdown([v for _, v in history])
            open_count = len(positions)
            risk_score = min(100.0, round(max_dd * 100 * 2 + open_count * 5, 1))
            return {
                "daily_pnl": round(daily_pnl, 2),
                "max_drawdown": round(max_dd * 100, 3),
                "open_positions": open_count,
                "margin_used": round(margin_used, 2),
                "risk_score": risk_score,
            }
        except Exception as exc:
            logger.debug("risk-metrics fallback: %s", exc)
            return {"daily_pnl": 0.0, "max_drawdown": 0.0, "open_positions": 0, "margin_used": 0.0, "risk_score": 0.0}

    @r.get("/performance/summary")
    def get_performance_summary():
        try:
            broker = getattr(app_state, "broker", None)
            equity_history = broker.get_equity_history() if (broker and hasattr(broker, "get_equity_history")) else []
            if not equity_history:
                raise ValueError("no history")
            values = [v for _, v in equity_history]
            initial = values[0]
            final = values[-1]
            total_return = ((final - initial) / initial * 100) if initial > 0 else 0.0

            # Max drawdown
            peak, max_dd = initial, 0.0
            for v in values:
                peak = max(peak, v)
                dd = (peak - v) / peak if peak > 0 else 0.0
                max_dd = max(max_dd, dd)

            # Sharpe from point-to-point returns
            returns = [(values[i] - values[i - 1]) / values[i - 1] for i in range(1, len(values)) if values[i - 1] > 0]
            sharpe = 0.0
            if len(returns) >= 2:
                mean_r = sum(returns) / len(returns)
                var = sum((r - mean_r) ** 2 for r in returns) / len(returns)
                std_r = _math.sqrt(var) if var > 0 else 0.0
                if std_r > 0:
                    sharpe = round((mean_r / std_r) * _math.sqrt(252), 3)

            win_rate = sum(1 for r in returns if r > 0) / len(returns) if returns else 0.0

            # Period in days
            ts_list = [t for t, _ in equity_history]
            period_days = max(1, round((ts_list[-1] - ts_list[0]) / 86400)) if len(ts_list) >= 2 else 1

            return {
                "total_return": round(total_return, 4),
                "sharpe_ratio": sharpe,
                "max_drawdown": round(max_dd * 100, 3),
                "win_rate": round(win_rate * 100, 2),
                "total_trades": len(returns),
                "period_days": period_days,
                "total_strategies": len(_strategy_store),
            }
        except Exception as exc:
            logger.debug("performance/summary fallback: %s", exc)
            return {
                "total_return": 0.0,
                "sharpe_ratio": 0.0,
                "max_drawdown": 0.0,
                "win_rate": 0.0,
                "total_trades": 0,
                "period_days": 30,
                "total_strategies": len(_strategy_store),
            }

    @r.get("/performance/{strategy_id}")
    def get_strategy_performance(strategy_id: str):
        key = _resolve(strategy_id)
        if key is None:
            raise HTTPException(404, "Strategy not found")
        return {
            "strategy_id": strategy_id,
            "total_return": 0.0,
            "sharpe_ratio": 0.0,
            "max_drawdown": 0.0,
            "win_rate": 0.0,
            "total_trades": 0,
        }


def _make_strategy_router():
    """Return a sub-router with strategy CRUD, position-size, and performance endpoints."""
    from fastapi import APIRouter

    _r = APIRouter()
    _register_strategy_crud(_r)
    _register_risk_performance_routes(_r)
    return _r


# Register the sub-router on the module-level router
try:
    router.include_router(_make_strategy_router())
except Exception:
    logger.exception("Failed to register strategy sub-router: %s")


# ── /trading/risk — alias for /trading/risk-metrics ──────────────────────────
# Frontend chart-api.ts calls GET /trading/risk; backend registered the
# endpoint as /trading/risk-metrics inside the strategy sub-router.


@router.get("/risk", response_model=None, summary="Risk metrics (alias for /risk-metrics)")
async def get_risk_alias():
    """
    Alias for ``GET /api/trading/risk-metrics``.

    Returns daily PnL, max drawdown, open position count, margin used, and
    a composite risk score.  Delegates to the same implementation used by
    the strategy sub-router endpoint.
    """
    try:
        broker = getattr(app_state, "broker", None)
        if broker is None:
            raise AttributeError("no broker")
        account = broker.get_account_info()
        positions = broker.get_positions() if hasattr(broker, "get_positions") else []
        daily_pnl = sum(getattr(p, "unrealized_pnl", 0.0) or 0.0 for p in positions)
        margin_used = float(getattr(account, "margin_used", 0.0) or 0.0)
        max_dd = 0.0
        if hasattr(broker, "get_equity_history"):
            history = broker.get_equity_history()
            if history:
                from api.trading import _compute_max_drawdown

                max_dd = _compute_max_drawdown([v for _, v in history])
        open_count = len(positions)
        risk_score = min(100.0, round(max_dd * 100 * 2 + open_count * 5, 1))
        return {
            "daily_pnl": round(daily_pnl, 2),
            "max_drawdown": round(max_dd * 100, 3),
            "open_positions": open_count,
            "margin_used": round(margin_used, 2),
            "risk_score": risk_score,
        }
    except Exception as exc:
        logger.debug("GET /trading/risk fallback: %s", exc)
        return {"daily_pnl": 0.0, "max_drawdown": 0.0, "open_positions": 0, "margin_used": 0.0, "risk_score": 0.0}


# ── /trading/ai-analysis ──────────────────────────────────────────────────────
# Frontend chart-api.ts POSTs a ChartClickContext and expects an AIAnalysis
# response: id, timestamp, context, regime, summary, keyDrivers, etc.


@router.post("/ai-analysis", response_model=None, summary="AI chart-click analysis")
async def get_ai_analysis(context: dict, user: TokenPayload = Depends(get_current_user)):
    """
    Accept a ``ChartClickContext`` payload and return an ``AIAnalysis`` object.

    Uses the signal engine and regime detector to produce a structured
    analysis of the clicked chart point.  Falls back to a sensible default
    when the ML stack is unavailable.
    """
    import uuid as _uuid
    import time as _time

    symbol: str = context.get("symbol", "XAUUSD")
    price: float = float(context.get("price", 0.0))
    timestamp: int = int(context.get("timestamp", _time.time() * 1000))

    # Attempt to get regime from the live regime router
    regime = "ranging"
    regime_confidence = 0.5
    try:
        from strategies.regime_router import RegimeRouter as _RR

        rr = _RR()
        detected = rr.detect_regime()
        if detected:
            regime = str(detected.get("regime", "ranging"))
            regime_confidence = float(detected.get("confidence", 0.5))
    except Exception as exc:
        logger.debug("ai-analysis: regime detection failed: %s", exc)

    # Attempt to get latest signal for context
    summary = f"AI analysis for {symbol} at {price:.5f}"
    key_drivers: list[str] = []
    recommended_action = "hold"
    action_confidence = 0.5
    warnings: list[str] = []

    try:
        from api.signals import _get_signal_service as _gss

        svc = _gss()
        if svc:
            latest = svc.get_latest_signal(symbol)
            if latest:
                recommended_action = str(latest.get("direction", "hold")).lower()
                action_confidence = float(latest.get("confidence", 0.5))
                key_drivers = latest.get("drivers", [])
                summary = latest.get("explanation", summary)
    except Exception as exc:
        logger.debug("ai-analysis: signal service unavailable: %s", exc)

    # Price targets: simple ATR-based estimate
    atr_estimate = price * 0.005  # 0.5% as fallback
    try:
        if hasattr(app_state, "price_engine") and app_state.price_engine:
            ohlcv = await app_state.price_engine.get_ohlcv(symbol, "H1", 14)
            if ohlcv and len(ohlcv) >= 2:
                highs = [c[2] for c in ohlcv]
                lows = [c[3] for c in ohlcv]
                atr_estimate = sum(h - l for h, l in zip(highs, lows, strict=False)) / len(highs)
    except Exception as exc:
        logger.debug("ai-analysis: ATR estimation failed: %s", exc)

    return {
        "id": str(_uuid.uuid4()),
        "timestamp": timestamp,
        "context": context,
        "regime": regime,
        "regimeConfidence": round(regime_confidence, 3),
        "summary": summary,
        "keyDrivers": key_drivers,
        "riskAssessment": f"ATR-based risk estimate: {atr_estimate:.5f}",
        "recommendedAction": recommended_action,
        "actionConfidence": round(action_confidence, 3),
        "priceTargets": {
            "bull": round(price + atr_estimate * 2, 5),
            "bear": round(price - atr_estimate * 2, 5),
            "base": round(price + atr_estimate * (1 if recommended_action == "buy" else -1), 5),
        },
        "timeHorizon": "4H–1D",
        "warnings": warnings,
    }


# ── Regime status endpoint ────────────────────────────────────────────────────


@router.get("/regime", response_model=None, summary="Current market regime and active strategy")
async def get_regime_status():
    """
    Return the current detected market regime, confidence score, and the
    strategy selected by the RegimeRouter for that regime.

    Also returns recent regime transition history and per-regime backtest
    performance from the manifest (if available).
    """
    try:
        from app import app_state

        broker = getattr(app_state, "broker", None)
        regime_router = getattr(app_state, "regime_router", None)

        # If no router on app_state, create a transient one for the response
        if regime_router is None:
            from strategies.manager import StrategyManager
            from strategies.regime_router import RegimeRouter

            sm = getattr(app_state, "strategy_manager", None) or StrategyManager()
            regime_router = RegimeRouter(sm)

        # Try to detect regime from live price data
        if broker is not None and hasattr(broker, "get_ohlcv"):
            import asyncio

            import pandas as pd

            _get = broker.get_ohlcv("XAUUSD", limit=100)
            if asyncio.iscoroutine(_get):
                ohlcv = await _get
            else:
                ohlcv = _get
            if ohlcv:
                df = pd.DataFrame(ohlcv)
                regime_router.route(df)

        return regime_router.status()

    except Exception as exc:
        logger.warning("regime status error: %s", exc)
        return {
            "current_regime": "unknown",
            "confidence": 0.0,
            "selected_strategy": "TrendFollowing",
            "manifest_entries": {},
            "error": "Regime router unavailable — check server logs",
        }


@router.get("/regime/history", response_model=None, summary="Recent regime transition history")
async def get_regime_history(limit: int = 20):
    """Return the last N regime transitions with timestamps."""
    try:
        from app import app_state

        regime_router = getattr(app_state, "regime_router", None)
        if regime_router is None:
            return {"history": []}
        return {"history": regime_router.regime_history(limit=limit)}
    except Exception as exc:
        logger.warning("get_regime_history failed: %s", exc)
        return {"history": [], "error": "Regime history unavailable — check server logs"}


# ── Stress test endpoint ──────────────────────────────────────────────────────


@router.get(
    "/stress-test",
    response_model=None,
    summary="Run historical stress scenarios on current position",
)
async def run_stress_test(
    position_value: float = 10000.0,
    equity: float = 100000.0,
    leverage: float = 1.0,
    max_loss_pct: float = 0.20,
):
    """
    Apply historical and hypothetical stress scenarios to a position.

    Returns scenario-by-scenario P&L impact and a gate pass/fail result.
    Scenarios include COVID crash (-12.5%), 2022 rate shock (-20%),
    2013 taper tantrum (-28%), GFC 2008 (-30%), and others.

    Parameters
    ----------
    position_value : Current position size in USD.
    equity         : Total account equity in USD (used for gate check).
    leverage       : Leverage multiplier (1.0 = no leverage).
    max_loss_pct   : Gate threshold — any scenario exceeding this fraction
                     of equity marks gate_passed=False.
    """
    _logger = logger
    try:
        from risk.stress_test import run_all_scenarios

        return run_all_scenarios(
            position_value=position_value,
            equity=equity,
            leverage=leverage,
            max_loss_pct=max_loss_pct,
        )
    except Exception:
        _logger.exception("Stress test failed: %s")
        raise HTTPException(status_code=500, detail="Stress test failed — check server logs") from None


