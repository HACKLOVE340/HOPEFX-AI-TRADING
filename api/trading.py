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

import asyncio
import csv
import io
import json as _json
import logging
import os
import time
from datetime import datetime, timezone
from functools import lru_cache

UTC = timezone.utc
from pathlib import Path as _Path
from typing import Any

from core.account_metrics import margin_level, margin_level as _margin_level
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
    except Exception:  # nosec B110 — app not yet initialised; kill switch checks disabled
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


def _check_trading_paused() -> None:
    """Raise HTTP 503 when an administrator has paused trading (soft halt).

    Pause state is set by the superadmin /engine/pause endpoint via the shared
    config store. This is a softer, easily-reversible halt distinct from the
    kill switch — but it must still block new order placement, which it did
    not before (the engine_status flag was never read on the order path).
    """
    try:
        from core.config_store import config_store

        if config_store is not None and str(config_store.get("engine_paused", "0")) == "1":
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Trading is paused by an administrator.",
            )
    except HTTPException:
        raise
    except Exception:  # nosec B110 — config store unavailable; do not hard-block on a read error
        logger.debug("Engine pause check skipped — config store unavailable")


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


async def _order_rate_limit_dep(user: "TokenPayload" = Depends(require_kyc)) -> None:
    """FastAPI Depends() wrapper for order rate limiting.

    Wired directly onto the /orders and /order route decorators so the limit
    appears in OpenAPI docs and is enforced before the handler body runs.
    """
    _check_order_rate_limit(user.sub)


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
    order_type: str = Field("market", pattern="^(market|limit|stop|stop_limit|trailing_stop)$")
    price: float | None = Field(None, gt=0)
    stop_price: float | None = Field(None, gt=0, description="Trigger price for stop-limit orders")
    stop_loss: float | None = Field(None, gt=0, description="Stop-loss price (optional)")
    take_profit: float | None = Field(None, gt=0, description="Take-profit price (optional)")
    trailing_distance: float | None = Field(None, gt=0, description="Trailing stop distance in price units")
    comment: str | None = Field(None, max_length=128)

    @field_validator("symbol")
    @classmethod
    def _symbol(cls, v: str) -> str:
        return validate_order_symbol(v)

    @field_validator("quantity")
    @classmethod
    def _quantity(cls, v: float) -> float:
        return validate_order_quantity(v)


class ModifyPositionRequest(BaseModel):
    stop_loss: float | None = Field(None, gt=0)
    take_profit: float | None = Field(None, gt=0)
    trailing_stop: float | None = Field(None, gt=0, description="Trailing stop distance in price units")


class PartialCloseRequest(BaseModel):
    quantity: float = Field(..., gt=0, description="Lot size to close (must be < full position size)")


class ModifyOrderRequest(BaseModel):
    price: float | None = Field(None, gt=0)
    stop_price: float | None = Field(None, gt=0)
    quantity: float | None = Field(None, gt=0)
    stop_loss: float | None = Field(None, gt=0)
    take_profit: float | None = Field(None, gt=0)
    trailing_distance: float | None = Field(None, gt=0)


class DepthLevel(BaseModel):
    price: float
    size: float
    total: float = 0.0


class OrderBookResponse(BaseModel):
    symbol: str
    bids: list[DepthLevel]
    asks: list[DepthLevel]
    timestamp: float
    spread: float


class SymbolInfoResponse(BaseModel):
    symbol: str
    description: str
    category: str
    pip_size: float
    lot_size: float
    min_lot: float
    max_lot: float
    margin_rate: float
    swap_long: float | None = None
    swap_short: float | None = None
    trading_hours: str | None = None


class PositionResponse(BaseModel):
    id: str
    symbol: str
    side: str
    quantity: float
    # `size` mirrors `quantity` — the frontend Position type uses `size`
    size: float = 0.0
    entry_price: float
    current_price: float
    unrealized_pnl: float
    realized_pnl: float = 0.0
    # Extended fields for mobile app
    unrealized_pnl_pct: float = 0.0
    opened_at: str = ""
    stop_loss: float | None = None
    take_profit: float | None = None


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


async def _call_on(broker: Any, method_name: str, *args, **kwargs):
    """Call a broker method whether it is sync or async.

    PaperTradingBroker uses sync methods; OANDA uses async. Sync methods run in
    an executor so they do not block the event loop.
    """
    import asyncio

    if broker is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Broker not initialised",
        )
    method = getattr(broker, method_name)
    if asyncio.iscoroutinefunction(method):
        return await method(*args, **kwargs)
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, lambda: method(*args, **kwargs))


async def _broker_call(method_name: str, *args, **kwargs):
    """Call a method on the **shared** process-wide broker.

    This is the deployment's own account — the autonomous engine's book. It is
    NOT any particular user's, so it must not back a request handler; use
    :func:`_user_broker_call` there. See ``core/account_registry.py`` and
    backlog T-01 for why: the shared engine nets every user's fills into one
    position per symbol.
    """
    return await _call_on(app_state.broker, method_name, *args, **kwargs)


async def _resolve_account(user_id: str):
    """The account the request acts on, per ``core.account_registry``."""
    from core.account_registry import get_account_registry

    return await get_account_registry().resolve(user_id)


async def _user_broker_call(user_id: str, method_name: str, *args, **kwargs):
    """Call a broker method on *user_id*'s own account.

    Every request handler that touches positions, orders or balances goes
    through here. On a paper deployment this is an account belonging to that
    user alone; on a live single-account venue the registry hands back the
    shared broker and says so, and the deployment is genuinely single-account —
    ``GET /api/trading/account`` reports that in ``isolated`` so the caller is
    not misled about whose money it is looking at.
    """
    resolution = await _resolve_account(user_id)
    return await _call_on(resolution.broker, method_name, *args, **kwargs)


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# place_order sub-functions
# Each function has a single responsibility and is ≤50 lines.
# Decomposed from the original 201-line monolith to reduce bug surface on
# the highest-risk code path (real order placement).
# ---------------------------------------------------------------------------


async def _validate_order(order: "OrderRequest", user_id: str) -> None:
    """
    Validate broker availability and prop-firm rules before touching risk.

    The prop-firm rules are evaluated against *this user's* account. Read from
    the shared engine they were checked against the deployment's combined book,
    so one user's drawdown could block another user's order — or, worse, let one
    through because somebody else's profit was covering the breach.

    Raises HTTP 503 if the broker is not ready.
    Raises HTTP 403 if prop-firm rules are violated.
    """
    if not app_state or not app_state.broker:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "Broker not initialised. The paper trading broker starts automatically "
                "on server startup — if this persists, check the server logs for "
                "startup errors (BROKER_TYPE env var defaults to 'paper')."
            ),
        )
    try:
        from brokers.prop_firms.guard import check_prop_firm_rules

        account_info = await _user_broker_call(user_id, "get_account_info")
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


def _order_reference_price(symbol: str) -> float:
    """Best-effort current price for pre-trade notional sizing.

    Returns 0.0 when no price is available (caller skips the notional gate
    rather than blocking all trading on a transient price-feed gap).
    """
    try:
        pe = getattr(app_state, "price_engine", None)
        if pe is not None and hasattr(pe, "get_last_price"):
            for sym in (symbol, _normalise_symbol(symbol)):
                tick = pe.get_last_price(sym)
                if tick is not None:
                    bid = float(getattr(tick, "bid", 0) or 0)
                    ask = float(getattr(tick, "ask", 0) or 0)
                    mid = (bid + ask) / 2 if (bid and ask) else (ask or bid)
                    if mid > 0:
                        return mid
        br = getattr(app_state, "broker", None)
        if br is not None and hasattr(br, "get_market_price"):
            p = float(br.get_market_price(symbol) or 0)
            if p > 0:
                return p
    except Exception:
        logger.debug("Order reference price lookup failed for %s", symbol)
    return 0.0


async def _run_standard_risk_check(order: "OrderRequest", user_id: str) -> None:
    """
    Run RiskManager.assess_risk() against current account state, then validate
    the pending order's notional against the per-position size / margin limit.

    Raises HTTP 403 when risk limits are breached.
    Raises HTTP 503 when the check itself fails (fail-safe: block the order).
    """
    try:
        account_info = await _user_broker_call(user_id, "get_account_info")
        positions = await _user_broker_call(user_id, "get_positions")
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
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN, detail=f"Risk check failed: {reason_str}"
            ) from None

        # Order-level size / margin gate. assess_risk() above only checks
        # AGGREGATE account health — it never sees the pending order, so a single
        # oversized order (e.g. 90 lots on a small account) would otherwise pass.
        # Validate the new order's notional against the per-position size limit
        # (equity * max_position_size_pct), open-position count, daily-loss and
        # drawdown caps via RiskManager.can_open_position().
        ref_price = _order_reference_price(order.symbol)
        if ref_price > 0:
            notional = abs(order.quantity) * ref_price
            ok, size_reason = app_state.risk_manager.can_open_position(notional)
            if not ok:
                logger.warning(
                    "Order blocked by position-size gate: user=%s symbol=%s notional=%.2f reason=%s",
                    user_id,
                    order.symbol,
                    notional,
                    size_reason,
                )
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail=f"Risk check failed: {size_reason}",
                ) from None
        else:
            logger.warning(
                "Position-size gate skipped — no reference price for %s (other gates still apply)",
                order.symbol,
            )
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


async def _route_to_broker(order: "OrderRequest", user_id: str) -> Any:
    """
    Submit the order to the broker and return the fill result.

    Raises HTTP 400 on broker rejection or unexpected error.
    """
    try:
        kwargs: dict[str, Any] = {}
        if order.stop_loss is not None:
            kwargs["stop_loss"] = order.stop_loss
        if order.take_profit is not None:
            kwargs["take_profit"] = order.take_profit
        result = await _user_broker_call(
            user_id,
            "place_market_order",
            symbol=order.symbol,
            side=order.side,
            quantity=order.quantity,
            **kwargs,
        )
        return result
    except HTTPException:
        raise
    except Exception:
        logger.exception("Broker order submission failed")
        try:
            from core.metrics import ORDERS_TOTAL

            ORDERS_TOTAL.labels(symbol=order.symbol, side=order.side, status="error").inc()
        except Exception as _exc:
            logger.debug("Suppressed exception: %s", _exc)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Order submission failed — check server logs"
        ) from None


async def _broadcast_fill_ws(order: "OrderRequest", result: Any, user_id: str) -> None:
    """Send the fill to the trader who placed it. Best-effort — logs on failure.

    This used ``broadcast("trades", …)``, so every fill — symbol, side, size and
    price — went to every subscriber of the trades channel. That is the reported
    behaviour in its most direct form: place an order and everyone else sees it
    appear. Fills go to their owner now.

    The legacy ``app_state.ws_manager`` fallback broadcast too and has no
    per-user send, so it is used only when there is genuinely no ws_live manager
    to route through, and it is logged when it happens.
    """
    trade_msg = {
        "type": "trade_fill",
        "data": {
            "symbol": order.symbol,
            "price": result.average_fill_price or 0.0,
            "quantity": order.quantity,
            "side": order.side,
            "trade_id": result.id,
        },
    }
    # Route through ws_live LiveConnectionManager (preferred — FastAPI WS).
    try:
        from api.ws_live import get_live_manager as _get_live_mgr

        await _get_live_mgr().send_to_user(user_id, "trades", trade_msg)
        return
    except Exception as exc:
        logger.debug("ws_live send_to_user failed, trying ws_manager: %s", exc)

    # Fallback: legacy WebSocketManager on app_state (websockets-based). It has
    # no per-user delivery, so the fill is dropped rather than shown to everyone.
    if not (hasattr(app_state, "ws_manager") and app_state.ws_manager is not None):
        return
    logger.warning(
        "Fill notification for user=%s not delivered: ws_live unavailable and the "
        "legacy ws_manager cannot address a single user.",
        user_id,
    )


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

    # Online learner: do NOT call notify_fill with a fabricated label=1 here.
    # The label (profitable=1 / loss=0) is only known when the trade closes.
    # Passing label=1 at fill time poisons the model by teaching it that every
    # REST-API order is profitable.  The trade-close path should call
    # notify_trade_close(features, realized_pnl) with the real outcome instead.
    logger.debug(
        "Online learner fill notification deferred to trade close: %s %s",
        order.side,
        order.symbol,
    )


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

    # Normalise result: brokers return either an Order object or a fill dict.
    def _get(attr: str, dict_key: str | None = None) -> Any:
        """Get attribute from Order object or key from fill dict."""
        if hasattr(result, attr):
            return getattr(result, attr)
        if isinstance(result, dict):
            return result.get(dict_key or attr)
        return None

    order_id = _get("id", "order_id") or "unknown"
    fill_price = _get("average_fill_price", "fill_price") or 0.0
    filled_qty = _get("filled_quantity", "quantity") or order.quantity

    # Reject if broker signalled a failure status in the result.
    # Order.status is an OrderStatus enum; normalise to lowercase string so
    # the comparison works regardless of whether the broker returns an enum
    # value (e.g. OrderStatus.REJECTED) or a plain string (e.g. "rejected").
    raw_status = _get("status")
    result_status_str = (raw_status.value if hasattr(raw_status, "value") else str(raw_status or "")).lower()
    if result_status_str in ("rejected", "error", "cancelled"):
        # Prefer rejected_reason attribute (Order dataclass), then generic reason.
        reason = _get("rejected_reason") or _get("reason") or result_status_str
        logger.error(
            "Order rejected by broker: user=%s symbol=%s side=%s status=%s reason=%s",
            user_id,
            order.symbol,
            order.side,
            result_status_str,
            reason,
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Order rejected: {reason}",
        )

    logger.info(
        "Order placed: user=%s symbol=%s side=%s qty=%s order_id=%s",
        user_id,
        order.symbol,
        order.side,
        order.quantity,
        order_id,
    )
    await _broadcast_fill_ws(order, result, user_id)
    _send_fill_push(order, result, user_id)
    _send_fill_email(order, result, user_id)
    _increment_fill_metrics(order)
    _notify_paper_gate_and_online_learner(order, result)

    return {
        "status": "success",
        "order_id": order_id,
        "filled_price": fill_price,
        "filled_quantity": filled_qty,
    }


def _check_subscription_gate(user_id: str, role: str = "user") -> None:
    """
    Enforce Starter-plan requirement for live trading.

    Skipped for admin and superadmin roles — platform operators are not
    required to hold a paid subscription on their own platform.

    Skipped in test/CI environments, paper-trading mode, and when the
    monetization module is unavailable.  Raises HTTP 403 when the user's
    active plan is below 'starter'.
    """
    # Platform operators are exempt from the subscription gate.
    if role in ("admin", "superadmin"):
        return

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
        # Monetization module unavailable — fail OPEN on the subscription gate
        # (do not block trading because billing is down), but make it LOUD so an
        # accidental bypass of the paywall in production is never silent.
        logger.warning(
            "Subscription gate bypassed for user=%s — monetization module unavailable. "
            "Live trading proceeded WITHOUT a plan check.",
            user_id,
        )


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
    _rl: None = Depends(_order_rate_limit_dep),
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
    _check_subscription_gate(user.sub, user.role)
    _check_kill_switch()  # hard block — must be first
    _check_trading_paused()  # soft halt set by superadmin /engine/pause
    _check_live_deployment_gates()  # Sharpe gate + CI model guard
    # Rate limit enforced via Depends(_order_rate_limit_dep) above.
    await _validate_order(order, user.sub)
    await _apply_risk_checks(order, user.sub)
    _log_compliance(order, user.sub)
    result = await _route_to_broker(order, user.sub)
    return await _record_fill(order, result, user.sub)


@router.get("/orders", summary="List open and recent orders")
async def get_orders(
    user: TokenPayload = Depends(get_current_user),
    status_filter: str | None = Query(
        None, alias="status", description="Filter by order status (open, filled, cancelled)"
    ),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    """
    Return open and recent orders for the authenticated user.

    Reads from the broker's order list when available; falls back to the
    trade history DB for filled orders when the broker is not connected.

    Query params:
      status  — filter by order status: open | filled | cancelled (optional)
      limit   — max rows (1–500, default 50)
      offset  — pagination offset
    """
    orders: list[dict] = []

    # 1. Live orders from this user's own account.
    #
    # This read used app_state.broker directly and applied no ownership filter
    # of any kind, so every authenticated user saw every other user's live
    # orders — symbol, side, size and price. It was the least protected of the
    # trading reads: /positions at least filtered, this did not.
    #
    # On a live single-account venue the orders belong to the deployment rather
    # than to the caller, and the broker cannot attribute them, so they are not
    # shown at all; the DB fallback below returns the caller's own filled orders.
    resolution = await _resolve_account(user.sub)
    broker = resolution.broker if resolution.isolated else None
    if broker is not None:
        try:
            raw_orders = []
            if hasattr(broker, "get_orders"):
                raw_orders = broker.get_orders() or []
            elif hasattr(broker, "get_open_orders"):
                raw_orders = broker.get_open_orders() or []

            for o in raw_orders:
                o_dict = o.__dict__ if hasattr(o, "__dict__") else (o if isinstance(o, dict) else {})
                order_status = str(o_dict.get("status", "open")).lower()
                if status_filter and order_status != status_filter.lower():
                    continue
                orders.append(
                    {
                        "order_id": str(o_dict.get("order_id") or o_dict.get("id", "")),
                        "symbol": str(o_dict.get("symbol", "")),
                        "side": str(o_dict.get("side", "")),
                        "order_type": str(o_dict.get("order_type") or o_dict.get("type", "market")),
                        "quantity": float(o_dict.get("quantity") or o_dict.get("units", 0)),
                        "price": float(o_dict.get("price") or o_dict.get("limit_price") or 0),
                        "status": order_status,
                        "created_at": str(o_dict.get("created_at") or o_dict.get("time", "")),
                        "filled_at": str(o_dict.get("filled_at") or o_dict.get("fill_time") or ""),
                    }
                )
        except Exception as exc:
            logger.debug("GET /orders broker fetch failed: %s", exc)

    # 2. Filled orders from trade DB when broker unavailable or no open orders
    if not orders:
        trades = await _query_trades(user.sub, None, limit, offset)
        for t in trades:
            t_dict = _trade_to_dict(t)
            order_status = "filled"
            if status_filter and order_status != status_filter.lower():
                continue
            orders.append(
                {
                    "order_id": t_dict["trade_id"],
                    "symbol": t_dict["symbol"],
                    "side": t_dict["side"],
                    "order_type": "market",
                    "quantity": t_dict["quantity"],
                    "price": t_dict["entry_price"],
                    "status": order_status,
                    "created_at": t_dict["entry_time"],
                    "filled_at": t_dict["entry_time"],
                }
            )

    page = orders[offset : offset + limit]
    return {"orders": page, "count": len(page), "total": len(orders), "offset": offset, "limit": limit}


@router.get("/history", summary="Trade history (alias for /trades)")
async def get_history(
    user: TokenPayload = Depends(get_current_user),
    symbol: str | None = Query(None, max_length=20),
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
):
    """
    Return paginated trade history for the authenticated user.

    Alias for ``GET /api/trading/trades`` — provided for frontend compatibility.

    Query params:
      symbol  — filter by symbol (optional)
      limit   — max rows (1–1000, default 100)
      offset  — pagination offset
    """
    trades = await _query_trades(user.sub, symbol, limit, offset)
    return {
        "trades": [_trade_to_dict(t) for t in trades],
        "count": len(trades),
        "offset": offset,
        "limit": limit,
    }


@router.get("/balance", summary="Account balance (alias for /account)")
async def get_balance(user: TokenPayload = Depends(get_current_user)):
    """
    Return the authenticated user's account balance and equity.

    Alias for ``GET /api/trading/account`` — provided for frontend compatibility.
    Returns a simplified subset: balance, equity, margin_used, margin_available,
    daily_pnl, currency.
    """
    broker = getattr(app_state, "broker", None) if app_state else None
    if broker is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Broker not available",
        )
    raw = await _user_broker_call(user.sub, "get_account_info")

    def _f(obj, *keys, default=0.0):
        for k in keys:
            v = getattr(obj, k, None) if not isinstance(obj, dict) else obj.get(k)
            if v is not None:
                try:
                    return float(v)
                except (TypeError, ValueError):  # nosec B110 — try next key on cast failure
                    pass
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
    daily_pnl = _f(raw, "daily_pnl", "day_pnl", "realized_pnl")

    return {
        "balance": round(balance, 2),
        "equity": round(equity, 2),
        "margin_used": round(margin_used, 2),
        "margin_available": round(margin_avail, 2),
        "daily_pnl": round(daily_pnl, 2),
        "currency": _s(raw, "currency", "base_currency", default="USD"),
    }


def _owned_position_ids(user: TokenPayload) -> set[str]:
    """IDs of the open positions belonging to *user*.

    Used **only** when the caller's account is not isolated — i.e. on a live
    single-account venue, where one real account is shared by the deployment and
    the broker cannot tell two users apart. On a paper deployment each user has
    their own broker (``core.account_registry``), so its ``get_positions()``
    already returns their rows and only theirs; filtering on top of that would
    hide a user's own positions, because paper position ids are symbols and do
    not match the database row ids.

    Fail closed: a broker position with no owning DB row is hidden rather than
    shown to everyone.

    Operators are not exempt. This used to return ``None`` — meaning *apply no
    filter* — for admin and superadmin, which is why a superadmin saw, and was
    seen in, the whole book. Whole-book access now lives on the operator
    endpoints, which name the account explicitly and are audited.
    """
    if app_state is None or getattr(app_state, "db_session_factory", None) is None:
        # No database to establish ownership. Showing the shared book to an
        # ordinary user would leak other traders' activity, so show nothing.
        logger.warning(
            "Position ownership cannot be established (no DB session factory) — "
            "returning an empty book for user=%s rather than leaking the shared engine.",
            user.sub,
        )
        return set()
    try:
        from database.models import Position as _Pos

        with app_state.db_session_factory() as _db:
            rows = _db.query(_Pos.id).filter(_Pos.user_id == user.sub).all()
        return {str(r[0]) for r in rows}
    except Exception as exc:
        logger.warning(
            "Position ownership lookup failed for user=%s (%s) — returning an empty book.",
            user.sub,
            exc,
        )
        return set()


@router.get("/positions", response_model=list[PositionResponse])
async def get_positions(
    user: TokenPayload = Depends(get_current_user),
):
    """Get the authenticated user's open positions — theirs and only theirs.

    Every role, including admin and superadmin, sees its own account here. The
    whole book is available on the operator endpoints, which say so and are
    audited.

    Returns an empty list when the broker is not yet initialised so the
    frontend positions table renders cleanly during cold-start.
    """
    if not app_state or not app_state.broker:
        return []

    resolution = await _resolve_account(user.sub)
    positions = await _call_on(resolution.broker, "get_positions")

    if not resolution.isolated:
        # Live single-account venue: one real account behind every user, so the
        # broker cannot separate them and database ownership is the only
        # attribution available. Fails closed — an unattributable position is
        # hidden rather than shown to everyone.
        owned = _owned_position_ids(user)
        total = len(positions)
        positions = [p for p in positions if str(getattr(p, "id", "")) in owned]
        if total != len(positions):
            logger.debug(
                "Positions filtered by ownership: user=%s visible=%d hidden=%d (%s)",
                user.sub,
                len(positions),
                total - len(positions),
                resolution.reason,
            )

    result = []
    for p in positions:
        entry = float(getattr(p, "entry_price", 0) or 0)
        current = float(getattr(p, "current_price", entry) or entry)
        pnl = float(getattr(p, "unrealized_pnl", 0) or 0)
        pnl_pct = ((current - entry) / entry * 100) if entry > 0 else 0.0
        opened_at = getattr(p, "opened_at", None) or getattr(p, "created_at", None)
        opened_at_str = opened_at.isoformat() if hasattr(opened_at, "isoformat") else str(opened_at or "")
        sl = getattr(p, "stop_loss", None) or getattr(p, "sl_price", None) or getattr(p, "stop_price", None)
        tp = getattr(p, "take_profit", None) or getattr(p, "tp_price", None) or getattr(p, "take_profit_price", None)
        realized = float(getattr(p, "realized_pnl", 0) or 0)
        result.append(
            PositionResponse(
                id=p.id,
                symbol=p.symbol,
                side=p.side.value if hasattr(p.side, "value") else str(p.side),
                quantity=p.quantity,
                size=p.quantity,
                entry_price=entry,
                current_price=current,
                unrealized_pnl=pnl,
                realized_pnl=realized,
                unrealized_pnl_pct=round(pnl_pct, 4),
                opened_at=opened_at_str,
                stop_loss=float(sl) if sl is not None else None,
                take_profit=float(tp) if tp is not None else None,
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
            detail="Broker not initialised — cannot close position. The paper trading engine starts automatically on server startup.",
        )

    # Ownership check: verify the position belongs to the requesting user.
    # Positions opened via the DB-backed path carry user_id; broker-native
    # positions (no DB row) fall through and are allowed for role >= trader.
    if app_state.db_session_factory is not None:
        try:
            from database.models import Position as _Pos

            with app_state.db_session_factory() as _db:
                _pos_row = _db.query(_Pos).filter(_Pos.id == position_id).first()
                # No operator exemption. This used to let admin and superadmin
                # close another user's position through the ordinary endpoint.
                # It is also dead weight now — close_position acts on the
                # caller's own account, which physically cannot hold somebody
                # else's position — but leaving the carve-out in would say the
                # opposite of what the code does.
                if _pos_row is not None and _pos_row.user_id and _pos_row.user_id != user.sub:
                    logger.warning(
                        "IDOR blocked: user=%s tried to close position=%s owned by user=%s",
                        user.sub,
                        position_id,
                        _pos_row.user_id,
                    )
                    raise HTTPException(
                        status_code=status.HTTP_403_FORBIDDEN,
                        detail="You do not own this position",
                    )
        except HTTPException:
            raise
        except Exception as _idor_exc:
            logger.debug("Ownership check skipped (non-fatal): %s", _idor_exc)

    success = await _user_broker_call(user.sub, "close_position", position_id)
    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Position not found",
        )

    logger.info("Position closed: user=%s position_id=%s", user.sub, position_id)

    # Notify Phase-3 online learner with the real outcome label.
    # realized_pnl comes from the broker close response; fall back to 0.0
    # when unavailable so the learner records a neutral (loss) label rather
    # than a fabricated profitable one.
    try:
        import pandas as _pd
        from core.signal_engine import notify_trade_close as _notify_close

        _realized = float(
            getattr(success, "realized_pnl", None)
            or (success.get("realized_pnl") if isinstance(success, dict) else None)
            or 0.0
        )
        _close_features = _pd.DataFrame([{"position_id": position_id, "user_id": user.sub, "source": "rest_api_close"}])
        _notify_close(_close_features, realized_pnl=_realized, primary_prob=None)
    except Exception as _ol_exc:
        logger.debug("notify_trade_close skipped: %s", _ol_exc)

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
            except RuntimeError:  # nosec B110 — no running loop in sync context; publish is non-fatal
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
            detail="Broker not initialised — cannot close positions. The paper trading engine starts automatically on server startup.",
        )

    resolution = await _resolve_account(user.sub)

    if resolution.isolated:
        # The account holds this user's positions and nobody else's, so
        # close-all means exactly what it says and cannot reach another book.
        closed = await _call_on(resolution.broker, "close_all_positions")
        count = len(closed) if isinstance(closed, list) else closed
        logger.info("All own positions closed: user=%s count=%s", user.sub, count)
        return {"status": "success", "closed_positions": count}

    # Live single-account venue: the broker's own close_all_positions() would
    # liquidate every other trader's book as well — a destructive cross-user
    # action reachable from the "Close All" button — so close only the positions
    # attributable to this user.
    owned = _owned_position_ids(user)
    if not owned:
        return {"status": "success", "closed_positions": 0}

    closed = 0
    failed: list[str] = []
    for pos_id in owned:
        try:
            if await _user_broker_call(user.sub, "close_position", pos_id):
                closed += 1
            else:
                failed.append(pos_id)
        except Exception as exc:
            failed.append(pos_id)
            logger.warning("close_all: could not close position=%s for user=%s: %s", pos_id, user.sub, exc)
    if failed:
        logger.warning("close_all partially completed: user=%s closed=%d failed=%d", user.sub, closed, len(failed))
    logger.info("Own positions closed: user=%s count=%d", user.sub, closed)
    return {"status": "success", "closed_positions": closed}


# ---------------------------------------------------------------------------
# Position modify / partial-close / hedge
# ---------------------------------------------------------------------------


@router.patch(
    "/positions/{position_id}",
    summary="Modify stop-loss, take-profit, or trailing stop on an open position",
)
async def modify_position(
    position_id: str,
    req: ModifyPositionRequest,
    user: TokenPayload = Depends(require_role("trader")),
):
    """Modify SL/TP/trailing-stop on an open position. Requires: role >= 'trader'."""
    _check_kill_switch()
    if not app_state or not app_state.broker:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Broker not initialised.",
        )

    broker = app_state.broker
    modify_fn = getattr(broker, "modify_position", None)
    if modify_fn is None:
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail="Connected broker does not support position modification.",
        )

    try:
        result = await asyncio.wait_for(
            asyncio.coroutine(modify_fn)(
                position_id,
                stop_loss=req.stop_loss,
                take_profit=req.take_profit,
                trailing_stop=req.trailing_stop,
            )
            if asyncio.iscoroutinefunction(modify_fn)
            else asyncio.to_thread(
                modify_fn,
                position_id,
                stop_loss=req.stop_loss,
                take_profit=req.take_profit,
                trailing_stop=req.trailing_stop,
            ),
            timeout=10.0,
        )
    except TimeoutError:
        raise HTTPException(status_code=status.HTTP_504_GATEWAY_TIMEOUT, detail="Broker timeout.") from None
    except Exception as exc:
        logger.exception("modify_position failed: %s", exc)
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="Broker operation failed.") from exc

    logger.info(
        "Position modified: user=%s position_id=%s sl=%s tp=%s trail=%s",
        user.sub,
        position_id,
        req.stop_loss,
        req.take_profit,
        req.trailing_stop,
    )
    return result or {"status": "ok", "position_id": position_id}


@router.post(
    "/positions/{position_id}/partial-close",
    summary="Partially close an open position by lot size",
)
async def partial_close_position(
    position_id: str,
    req: PartialCloseRequest,
    user: TokenPayload = Depends(require_role("trader")),
):
    """Close a portion of an open position. Requires: role >= 'trader'."""
    _check_kill_switch()
    if not app_state or not app_state.broker:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Broker not initialised.",
        )

    broker = app_state.broker
    partial_fn = getattr(broker, "partial_close_position", None)
    if partial_fn is None:
        # Fallback: close full position if broker doesn't support partial close
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail="Connected broker does not support partial position close.",
        )

    try:
        result = await asyncio.wait_for(
            asyncio.to_thread(partial_fn, position_id, req.quantity)
            if not asyncio.iscoroutinefunction(partial_fn)
            else partial_fn(position_id, req.quantity),
            timeout=10.0,
        )
    except TimeoutError:
        raise HTTPException(status_code=status.HTTP_504_GATEWAY_TIMEOUT, detail="Broker timeout.") from None
    except Exception as exc:
        logger.exception("partial_close_position failed: %s", exc)
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="Broker operation failed.") from exc

    logger.info(
        "Partial close: user=%s position_id=%s quantity=%s",
        user.sub,
        position_id,
        req.quantity,
    )
    return result or {"status": "ok", "position_id": position_id, "closed_quantity": req.quantity}


@router.post(
    "/positions/{position_id}/hedge",
    summary="Open a hedge (opposite-side) order for an existing position",
)
async def hedge_position(
    position_id: str,
    user: TokenPayload = Depends(require_role("trader")),
):
    """Place an equal-and-opposite order to hedge an open position. Requires: role >= 'trader'."""
    _check_kill_switch()
    if not app_state or not app_state.broker:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Broker not initialised.",
        )

    # Fetch the position to mirror
    positions = await _user_broker_call(user.sub, "get_positions")
    target = next((p for p in positions if str(p.id) == position_id), None)
    if target is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Position not found.") from None

    hedge_side = "sell" if str(getattr(target, "side", "long")).lower() in ("long", "buy") else "buy"
    hedge_qty = float(getattr(target, "quantity", getattr(target, "size", 0)))
    if hedge_qty <= 0:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Position has zero size.") from None

    hedge_order = OrderRequest(
        symbol=target.symbol,
        side=hedge_side,
        quantity=hedge_qty,
        order_type="market",
    )
    result = await _route_to_broker(hedge_order, user.sub)
    logger.info(
        "Hedge placed: user=%s position_id=%s hedge_side=%s qty=%s",
        user.sub,
        position_id,
        hedge_side,
        hedge_qty,
    )
    return {"status": "ok", "hedge_order": result, "hedged_position_id": position_id}


# ---------------------------------------------------------------------------
# Order cancel / modify
# ---------------------------------------------------------------------------


@router.delete(
    "/orders/{order_id}",
    summary="Cancel a pending or open order",
)
async def cancel_order(
    order_id: str,
    user: TokenPayload = Depends(require_role("trader")),
):
    """Cancel a pending order. Requires: role >= 'trader'."""
    _check_kill_switch()
    if not app_state or not app_state.broker:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Broker not initialised.",
        )

    broker = app_state.broker
    cancel_fn = getattr(broker, "cancel_order", None)
    if cancel_fn is None:
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail="Connected broker does not support order cancellation.",
        )

    try:
        result = await asyncio.wait_for(
            asyncio.to_thread(cancel_fn, order_id)
            if not asyncio.iscoroutinefunction(cancel_fn)
            else cancel_fn(order_id),
            timeout=10.0,
        )
    except TimeoutError:
        raise HTTPException(status_code=status.HTTP_504_GATEWAY_TIMEOUT, detail="Broker timeout.") from None
    except Exception as exc:
        logger.exception("cancel_order failed: %s", exc)
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="Broker operation failed.") from exc

    logger.info("Order cancelled: user=%s order_id=%s", user.sub, order_id)
    return result or {"status": "cancelled", "order_id": order_id}


@router.patch(
    "/orders/{order_id}",
    summary="Modify price, quantity, SL, or TP on a pending order",
)
async def modify_order(
    order_id: str,
    req: ModifyOrderRequest,
    user: TokenPayload = Depends(require_role("trader")),
):
    """Modify a pending order. Requires: role >= 'trader'."""
    _check_kill_switch()
    if not app_state or not app_state.broker:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Broker not initialised.",
        )

    broker = app_state.broker
    modify_fn = getattr(broker, "modify_order", None)
    if modify_fn is None:
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail="Connected broker does not support order modification.",
        )

    kwargs = {k: v for k, v in req.model_dump().items() if v is not None}
    try:
        result = await asyncio.wait_for(
            asyncio.to_thread(modify_fn, order_id, **kwargs)
            if not asyncio.iscoroutinefunction(modify_fn)
            else modify_fn(order_id, **kwargs),
            timeout=10.0,
        )
    except TimeoutError:
        raise HTTPException(status_code=status.HTTP_504_GATEWAY_TIMEOUT, detail="Broker timeout.") from None
    except Exception as exc:
        logger.exception("modify_order failed: %s", exc)
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="Broker operation failed.") from exc

    logger.info("Order modified: user=%s order_id=%s changes=%s", user.sub, order_id, kwargs)
    return result or {"status": "ok", "order_id": order_id}


# ---------------------------------------------------------------------------
# Order book depth
# ---------------------------------------------------------------------------

# Static spread map used when broker doesn't provide real depth
_DEPTH_SPREAD_MAP: dict[str, float] = {
    "XAUUSD": 0.30,
    "XAGUSD": 0.03,
    "EURUSD": 0.0001,
    "GBPUSD": 0.0002,
    "USDJPY": 0.02,
    "BTCUSD": 10.0,
    "ETHUSD": 1.0,
    "USDCAD": 0.0002,
    "AUDUSD": 0.0001,
    "USDCHF": 0.0001,
    "NZDUSD": 0.0001,
    "US30": 2.0,
    "US500": 0.25,
    "NAS100": 0.5,
    "USOIL": 0.03,
}


@router.get(
    "/depth/{symbol}",
    response_model=OrderBookResponse,
    summary="Get order book depth (bid/ask ladder) for a symbol",
)
async def get_order_book_depth(
    symbol: str,
    levels: int = Query(20, ge=5, le=50),
    user: TokenPayload = Depends(get_current_user),
):
    """Return bid/ask depth ladder. Falls back to synthetic spread-based depth
    when the broker does not provide a real order book. Requires: authenticated user."""
    import time as _time
    import random as _random

    symbol = symbol.replace("/", "").replace("%2F", "").upper()
    try:
        symbol = validate_order_symbol(symbol)
    except HTTPException:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Symbol '{symbol}' is not in the permitted instrument list.",
        ) from None

    now = _time.time()

    # Try broker depth first
    if app_state and app_state.broker:
        depth_fn = getattr(app_state.broker, "get_order_book", None)
        if depth_fn is not None:
            try:
                book = await asyncio.wait_for(
                    asyncio.to_thread(depth_fn, symbol, levels)
                    if not asyncio.iscoroutinefunction(depth_fn)
                    else depth_fn(symbol, levels),
                    timeout=5.0,
                )
                if book and getattr(book, "bids", None) and getattr(book, "asks", None):
                    bids = [DepthLevel(price=b[0], size=b[1]) for b in book.bids[:levels]]
                    asks = [DepthLevel(price=a[0], size=a[1]) for a in book.asks[:levels]]
                    # Compute running totals
                    total = 0.0
                    for b in bids:
                        total += b.size
                        b.total = round(total, 4)
                    total = 0.0
                    for a in asks:
                        total += a.size
                        a.total = round(total, 4)
                    spread = asks[0].price - bids[0].price if bids and asks else 0.0
                    return OrderBookResponse(
                        symbol=symbol,
                        bids=bids,
                        asks=asks,
                        timestamp=now,
                        spread=round(spread, 5),
                    )
            except Exception as exc:
                logger.debug("Broker depth unavailable for %s: %s", symbol, exc)

    # Fallback: build a realistic depth ladder from the last known price tick.
    # This uses real mid-price from the price engine / broker, not random values.
    mid_price: float | None = None
    if app_state and app_state.price_engine:
        tick = app_state.price_engine.get_last_price(symbol)
        if tick:
            mid_price = float(tick.mid)
    if mid_price is None and app_state and app_state.broker:
        mp = getattr(app_state.broker, "market_prices", {})
        mid_price = float(mp.get(symbol, 0)) or None

    if mid_price is None or mid_price <= 0:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"No price data available for {symbol}. Connect a live data feed.",
        )

    spread = _DEPTH_SPREAD_MAP.get(symbol, mid_price * 0.0002)
    pip = spread / 5  # one pip ≈ spread / 5

    bids: list[DepthLevel] = []
    asks: list[DepthLevel] = []
    bid_total = ask_total = 0.0

    # Use a seeded RNG so depth is deterministic per price level (not random per request)
    rng = _random.Random(int(mid_price * 1000) % (2**31))

    for i in range(levels):
        bid_px = round(mid_price - spread / 2 - i * pip, 5)
        ask_px = round(mid_price + spread / 2 + i * pip, 5)
        # Size decreases with distance from mid — realistic shape
        base_size = max(0.1, 5.0 / (i + 1))
        bid_sz = round(base_size * rng.uniform(0.7, 1.3), 2)
        ask_sz = round(base_size * rng.uniform(0.7, 1.3), 2)
        bid_total += bid_sz
        ask_total += ask_sz
        bids.append(DepthLevel(price=bid_px, size=bid_sz, total=round(bid_total, 4)))
        asks.append(DepthLevel(price=ask_px, size=ask_sz, total=round(ask_total, 4)))

    return OrderBookResponse(
        symbol=symbol,
        bids=bids,
        asks=asks,
        timestamp=now,
        spread=round(spread, 5),
    )


# ---------------------------------------------------------------------------
# Symbol info / search
# ---------------------------------------------------------------------------

_SYMBOL_CATALOGUE: dict[str, dict] = {
    "XAUUSD": {
        "description": "Gold vs US Dollar",
        "category": "metals",
        "pip_size": 0.01,
        "lot_size": 100,
        "min_lot": 0.01,
        "max_lot": 50.0,
        "margin_rate": 0.02,
        "swap_long": -5.5,
        "swap_short": 1.2,
        "trading_hours": "Mon-Fri 01:00-24:00",
    },
    "XAGUSD": {
        "description": "Silver vs US Dollar",
        "category": "metals",
        "pip_size": 0.001,
        "lot_size": 5000,
        "min_lot": 0.01,
        "max_lot": 50.0,
        "margin_rate": 0.02,
        "swap_long": -3.2,
        "swap_short": 0.8,
        "trading_hours": "Mon-Fri 01:00-24:00",
    },
    "EURUSD": {
        "description": "Euro vs US Dollar",
        "category": "forex",
        "pip_size": 0.0001,
        "lot_size": 100000,
        "min_lot": 0.01,
        "max_lot": 100.0,
        "margin_rate": 0.01,
        "swap_long": -0.5,
        "swap_short": 0.3,
        "trading_hours": "Mon-Fri 00:00-24:00",
    },
    "GBPUSD": {
        "description": "British Pound vs US Dollar",
        "category": "forex",
        "pip_size": 0.0001,
        "lot_size": 100000,
        "min_lot": 0.01,
        "max_lot": 100.0,
        "margin_rate": 0.01,
        "swap_long": -0.8,
        "swap_short": 0.4,
        "trading_hours": "Mon-Fri 00:00-24:00",
    },
    "USDJPY": {
        "description": "US Dollar vs Japanese Yen",
        "category": "forex",
        "pip_size": 0.01,
        "lot_size": 100000,
        "min_lot": 0.01,
        "max_lot": 100.0,
        "margin_rate": 0.01,
        "swap_long": 0.2,
        "swap_short": -0.6,
        "trading_hours": "Mon-Fri 00:00-24:00",
    },
    "USDCHF": {
        "description": "US Dollar vs Swiss Franc",
        "category": "forex",
        "pip_size": 0.0001,
        "lot_size": 100000,
        "min_lot": 0.01,
        "max_lot": 100.0,
        "margin_rate": 0.01,
        "swap_long": -0.3,
        "swap_short": 0.1,
        "trading_hours": "Mon-Fri 00:00-24:00",
    },
    "AUDUSD": {
        "description": "Australian Dollar vs USD",
        "category": "forex",
        "pip_size": 0.0001,
        "lot_size": 100000,
        "min_lot": 0.01,
        "max_lot": 100.0,
        "margin_rate": 0.01,
        "swap_long": -0.4,
        "swap_short": 0.2,
        "trading_hours": "Mon-Fri 00:00-24:00",
    },
    "NZDUSD": {
        "description": "New Zealand Dollar vs USD",
        "category": "forex",
        "pip_size": 0.0001,
        "lot_size": 100000,
        "min_lot": 0.01,
        "max_lot": 100.0,
        "margin_rate": 0.01,
        "swap_long": -0.3,
        "swap_short": 0.1,
        "trading_hours": "Mon-Fri 00:00-24:00",
    },
    "USDCAD": {
        "description": "US Dollar vs Canadian Dollar",
        "category": "forex",
        "pip_size": 0.0001,
        "lot_size": 100000,
        "min_lot": 0.01,
        "max_lot": 100.0,
        "margin_rate": 0.01,
        "swap_long": -0.2,
        "swap_short": 0.1,
        "trading_hours": "Mon-Fri 00:00-24:00",
    },
    "BTCUSD": {
        "description": "Bitcoin vs US Dollar",
        "category": "crypto",
        "pip_size": 1.0,
        "lot_size": 1,
        "min_lot": 0.01,
        "max_lot": 10.0,
        "margin_rate": 0.10,
        "swap_long": -15.0,
        "swap_short": -15.0,
        "trading_hours": "24/7",
    },
    "ETHUSD": {
        "description": "Ethereum vs US Dollar",
        "category": "crypto",
        "pip_size": 0.1,
        "lot_size": 1,
        "min_lot": 0.01,
        "max_lot": 50.0,
        "margin_rate": 0.10,
        "swap_long": -10.0,
        "swap_short": -10.0,
        "trading_hours": "24/7",
    },
    "US30": {
        "description": "Dow Jones Industrial Average",
        "category": "indices",
        "pip_size": 1.0,
        "lot_size": 1,
        "min_lot": 0.01,
        "max_lot": 20.0,
        "margin_rate": 0.05,
        "swap_long": -2.5,
        "swap_short": 0.5,
        "trading_hours": "Mon-Fri 01:00-22:15",
    },
    "US500": {
        "description": "S&P 500 Index",
        "category": "indices",
        "pip_size": 0.25,
        "lot_size": 50,
        "min_lot": 0.01,
        "max_lot": 20.0,
        "margin_rate": 0.05,
        "swap_long": -2.0,
        "swap_short": 0.4,
        "trading_hours": "Mon-Fri 01:00-22:15",
    },
    "NAS100": {
        "description": "NASDAQ 100 Index",
        "category": "indices",
        "pip_size": 0.25,
        "lot_size": 20,
        "min_lot": 0.01,
        "max_lot": 20.0,
        "margin_rate": 0.05,
        "swap_long": -2.2,
        "swap_short": 0.4,
        "trading_hours": "Mon-Fri 01:00-22:15",
    },
    "USOIL": {
        "description": "WTI Crude Oil",
        "category": "commodities",
        "pip_size": 0.01,
        "lot_size": 1000,
        "min_lot": 0.01,
        "max_lot": 50.0,
        "margin_rate": 0.05,
        "swap_long": -3.0,
        "swap_short": 0.5,
        "trading_hours": "Mon-Fri 01:00-24:00",
    },
    "UKOIL": {
        "description": "Brent Crude Oil",
        "category": "commodities",
        "pip_size": 0.01,
        "lot_size": 1000,
        "min_lot": 0.01,
        "max_lot": 50.0,
        "margin_rate": 0.05,
        "swap_long": -2.8,
        "swap_short": 0.4,
        "trading_hours": "Mon-Fri 01:00-24:00",
    },
    "XPTUSD": {
        "description": "Platinum vs US Dollar",
        "category": "metals",
        "pip_size": 0.01,
        "lot_size": 50,
        "min_lot": 0.01,
        "max_lot": 20.0,
        "margin_rate": 0.03,
        "swap_long": -4.0,
        "swap_short": 0.8,
        "trading_hours": "Mon-Fri 01:00-24:00",
    },
}


@router.get(
    "/symbols",
    response_model=list[SymbolInfoResponse],
    summary="List all tradeable instruments",
)
async def list_symbols(
    user: TokenPayload = Depends(get_current_user),
):
    """Return the full instrument catalogue. Requires: authenticated user."""
    return [SymbolInfoResponse(symbol=sym, **info) for sym, info in _SYMBOL_CATALOGUE.items()]


@router.get(
    "/symbols/search",
    response_model=list[SymbolInfoResponse],
    summary="Search instruments by symbol or description",
)
async def search_symbols(
    q: str = Query(..., min_length=1, max_length=30),
    user: TokenPayload = Depends(get_current_user),
):
    """Full-text search across symbol names and descriptions. Requires: authenticated user."""
    q_upper = q.upper()
    results = [
        SymbolInfoResponse(symbol=sym, **info)
        for sym, info in _SYMBOL_CATALOGUE.items()
        if q_upper in sym or q_upper in info["description"].upper()
    ]
    return results


@router.get(
    "/symbol/{symbol}",
    response_model=SymbolInfoResponse,
    summary="Get instrument specification for a single symbol",
)
async def get_symbol_info(
    symbol: str,
    user: TokenPayload = Depends(get_current_user),
):
    """Return instrument spec (pip size, lot size, margin rate, swaps). Requires: authenticated user."""
    symbol = symbol.replace("/", "").replace("%2F", "").upper()
    info = _SYMBOL_CATALOGUE.get(symbol)
    if info is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Symbol '{symbol}' not found in instrument catalogue.",
        )
    return SymbolInfoResponse(symbol=symbol, **info)


@router.get("/account", response_model=None, summary="Get full AccountMetrics snapshot")
async def get_account(
    user: TokenPayload = Depends(get_current_user),
):
    """
    Return a complete AccountMetrics payload for the authenticated user.

    Fields returned (all required by the frontend AccountMetrics type):
      balance, equity, margin_used, margin_free, margin_level,
      daily_pnl, daily_pnl_pct, total_pnl, win_rate, sharpe_ratio,
      sortino_ratio, max_drawdown, open_trades, open_risk_pct,
      cvar_95, kill_switch, unrealized_pnl, currency, account_id
    """
    import math as _math
    import os as _os

    # ── Broker account info ───────────────────────────────────────────────────
    if not app_state or not app_state.broker:
        # Paper mode: seed balance from env, enrich with real DB trade stats
        starting = float(_os.getenv("PAPER_STARTING_BALANCE", "100000"))

        # Pull real trade stats from DB even in paper mode
        _win_rate = 0.0
        _sharpe = 0.0
        _sortino = 0.0
        _max_dd = 0.0
        _total_pnl = 0.0
        _open_trades = 0
        _open_risk_pct = 0.0
        _cvar_95 = 0.0
        _unrealized = 0.0
        _daily_pnl = 0.0
        _balance = starting

        try:
            import datetime as _dt
            from database.async_connection import _default_pool as _async_pool
            from database.repositories.trade_repository import TradeRepository as _TradeRepo
            from database.repositories.position_repository import PositionRepository as _PosRepo

            if _async_pool is None:
                raise RuntimeError("Async DB pool not initialised")
            async with _async_pool.session() as _db:
                # Repositories are stateless — session is the first positional
                # arg on every method, not a constructor arg. Instantiate with
                # no args and pass _db explicitly on each call.
                _trade_repo = _TradeRepo()
                _pos_repo = _PosRepo()
                # get_by_user returns all trades for the user; filter to closed
                # in Python. get_by_user has no status parameter.
                _all_trades = await _trade_repo.get_by_user(_db, user_id=user.sub, limit=10000)
                closed = [
                    t for t in _all_trades if getattr(t, "status", None) == "closed" or not getattr(t, "is_open", True)
                ]
                # Filter open positions to this user only — passing user_id=None
                # would return all users' positions (data isolation breach).
                open_positions = await _pos_repo.get_open_positions(_db, user_id=user.sub, symbol=None)
                _open_trades = len(open_positions)

                if closed:
                    pnls = [float(getattr(t, "realized_pnl", 0) or 0.0) for t in closed]
                    _total_pnl = round(sum(pnls), 2)
                    _balance = round(starting + _total_pnl, 2)
                    wins = [p for p in pnls if p > 0]
                    # win_rate as percentage 0-100 (consistent with live-broker path)
                    _win_rate = round(len(wins) / len(pnls) * 100, 2) if pnls else 0.0

                    # Equity curve for drawdown + Sharpe
                    eq_vals: list[float] = []
                    running = starting
                    for p in pnls:
                        running += p
                        eq_vals.append(running)

                    peak = starting
                    for v in eq_vals:
                        peak = max(peak, v)
                        dd = (peak - v) / peak if peak > 0 else 0.0
                        _max_dd = max(_max_dd, dd)
                    # max_drawdown as percentage 0-100 (consistent with live-broker path)
                    _max_dd = round(_max_dd * 100, 2)

                    if len(pnls) >= 10:
                        rets = [pnls[i] / eq_vals[i - 1] if eq_vals[i - 1] > 0 else 0.0 for i in range(1, len(pnls))]
                        if rets:
                            mean_r = sum(rets) / len(rets)
                            var_r = sum((r - mean_r) ** 2 for r in rets) / len(rets)
                            std_r = _math.sqrt(var_r) if var_r > 0 else 0.0
                            _sharpe = round((mean_r / std_r) * _math.sqrt(252), 3) if std_r > 0 else 0.0
                            neg_rets = [r for r in rets if r < 0]
                            if neg_rets:
                                down_var = sum(r**2 for r in neg_rets) / len(neg_rets)
                                down_std = _math.sqrt(down_var)
                                _sortino = round((mean_r / down_std) * _math.sqrt(252), 3) if down_std > 0 else 0.0
                            sorted_rets = sorted(rets)
                            cutoff = max(1, int(len(sorted_rets) * 0.05))
                            _cvar_95 = round(abs(sum(sorted_rets[:cutoff]) / cutoff), 6)

                # Daily P&L from trades closed today
                today_start = _dt.datetime.now(_dt.timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
                today_closed = [t for t in closed if getattr(t, "exit_time", None) and t.exit_time >= today_start]
                _daily_pnl = round(sum(float(getattr(t, "realized_pnl", 0) or 0.0) for t in today_closed), 2)

                # Unrealized P&L from open positions
                _unrealized = round(sum(float(getattr(p, "unrealized_pnl", 0) or 0.0) for p in open_positions), 2)

                # Open risk
                equity_est = _balance + _unrealized
                if open_positions and equity_est > 0:
                    total_notional = sum(
                        float(getattr(p, "quantity", 0) or 0.0) * float(getattr(p, "entry_price", 0) or 0.0)
                        for p in open_positions
                    )
                    _open_risk_pct = round(total_notional / equity_est * 100, 2)
        except Exception as _exc:
            logger.debug("Paper account DB stats failed: %s", _exc)

        # Reconcile currently-open broker positions. The DB stats above cover
        # CLOSED-trade history, but open paper positions live in the broker (not
        # the DB), so open_trades / unrealized / margin must come from there to
        # match /positions. Without this the summary reported 0 open trades and
        # $0 margin while positions were actually open.
        _margin_used = 0.0
        _MARGIN_RATE = 0.02  # 2% paper margin requirement (matches PaperTradingBroker)
        try:
            _bpos = await _user_broker_call(user.sub, "get_positions")
            if _bpos:
                _open_trades = len(_bpos)
                _unrealized = round(sum(float(getattr(p, "unrealized_pnl", 0) or 0.0) for p in _bpos), 2)
                _margin_used = round(
                    sum(
                        abs(float(getattr(p, "quantity", 0) or 0.0))
                        * float(getattr(p, "current_price", 0) or getattr(p, "entry_price", 0) or 0.0)
                        * _MARGIN_RATE
                        for p in _bpos
                    ),
                    2,
                )
        except Exception as _exc:
            logger.debug("Broker position reconciliation failed: %s", _exc)

        _equity = round(_balance + _unrealized, 2)
        _daily_pnl_pct = round((_daily_pnl / _balance * 100) if _balance > 0 else 0.0, 4)

        # Kill switch state — use the injected helper so tests can override
        _ks_active = False
        try:
            _ks = _get_kill_switch()
            _ks_active = bool(_ks and _ks.is_active())
        except Exception:  # nosec B110  # noqa: S110
            pass

        return {
            "account_id": user.sub,
            "balance": _balance,
            "equity": _equity,
            "margin_used": _margin_used,
            "margin_free": round(max(_equity - _margin_used, 0.0), 2),
            "margin_level": margin_level(_equity, _margin_used),
            "daily_pnl": _daily_pnl,
            "daily_pnl_pct": _daily_pnl_pct,
            "total_pnl": _total_pnl,
            "unrealized_pnl": _unrealized,
            "win_rate": _win_rate,
            "sharpe_ratio": _sharpe,
            "sortino_ratio": _sortino,
            "max_drawdown": _max_dd,
            "open_trades": _open_trades,
            "open_risk_pct": _open_risk_pct,
            "cvar_95": _cvar_95,
            "kill_switch": _ks_active,
            "currency": "USD",
        }

    raw = await _user_broker_call(user.sub, "get_account_info")

    def _f(obj, *keys, default=0.0):
        for k in keys:
            v = getattr(obj, k, None) if not isinstance(obj, dict) else obj.get(k)
            if v is not None:
                try:
                    return float(v)
                except (TypeError, ValueError):  # nosec B110
                    pass
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
    margin_free = _f(raw, "margin_available", "free_margin", "available_margin") or max(equity - margin_used, 0.0)
    margin_level = _margin_level(equity, margin_used)
    unrealized = _f(raw, "unrealized_pnl", "open_pnl", "unrealised_pnl")
    daily_pnl = _f(raw, "daily_pnl", "day_pnl", "realized_pnl")
    daily_pnl_pct = round((daily_pnl / balance * 100) if balance > 0 else 0.0, 4)

    # ── Trade statistics from DB ──────────────────────────────────────────────
    win_rate = 0.0
    sharpe_ratio = 0.0
    sortino_ratio = 0.0
    max_drawdown = 0.0
    total_pnl = 0.0
    open_trades = 0
    open_risk_pct = 0.0
    cvar_95 = 0.0

    try:
        from database.async_connection import _default_pool as _async_pool
        from database.repositories.trade_repository import TradeRepository as _TradeRepo
        from database.repositories.position_repository import PositionRepository as _PosRepo

        if _async_pool is None:
            raise RuntimeError("Async DB pool not initialised")
        async with _async_pool.session() as _db:
            # Repositories are stateless — session is the first positional arg
            # on every method, not a constructor arg.
            _trade_repo = _TradeRepo()
            _pos_repo = _PosRepo()
            # Scope to the authenticated user — user_id=None would return all
            # users' trades, leaking cross-user data (data isolation breach).
            # get_by_user has no status parameter; filter closed trades in Python.
            _all_trades = await _trade_repo.get_by_user(_db, user_id=user.sub, limit=10000)
            closed = [
                t for t in _all_trades if getattr(t, "status", None) == "closed" or not getattr(t, "is_open", True)
            ]
            # Filter open positions to this user only.
            open_positions = await _pos_repo.get_open_positions(_db, user_id=user.sub, symbol=None)
            open_trades = len(open_positions)

            if closed:
                pnls = [float(t.realized_pnl or 0.0) for t in closed]
                total_pnl = round(sum(pnls), 2)
                wins = [p for p in pnls if p > 0]
                win_rate = round(len(wins) / len(pnls) * 100, 2) if pnls else 0.0

                # Equity curve for drawdown + Sharpe
                starting = float(_os.getenv("PAPER_STARTING_BALANCE", "100000"))
                eq_vals: list[float] = []
                running = starting
                for p in pnls:
                    running += p
                    eq_vals.append(running)

                # Max drawdown
                peak = starting
                for v in eq_vals:
                    peak = max(peak, v)
                    dd = (peak - v) / peak if peak > 0 else 0.0
                    max_drawdown = max(max_drawdown, dd)
                max_drawdown = round(max_drawdown * 100, 2)  # as %

                # Sharpe (annualised, daily returns)
                if len(pnls) >= 10:
                    rets = [pnls[i] / eq_vals[i - 1] if eq_vals[i - 1] > 0 else 0.0 for i in range(1, len(pnls))]
                    if rets:
                        mean_r = sum(rets) / len(rets)
                        var_r = sum((r - mean_r) ** 2 for r in rets) / len(rets)
                        std_r = _math.sqrt(var_r) if var_r > 0 else 0.0
                        sharpe_ratio = round((mean_r / std_r) * _math.sqrt(252), 3) if std_r > 0 else 0.0

                        # Sortino (downside deviation only)
                        neg_rets = [r for r in rets if r < 0]
                        if neg_rets:
                            down_var = sum(r**2 for r in neg_rets) / len(neg_rets)
                            down_std = _math.sqrt(down_var)
                            sortino_ratio = round((mean_r / down_std) * _math.sqrt(252), 3) if down_std > 0 else 0.0

                        # CVaR 95% (average of worst 5% returns)
                        sorted_rets = sorted(rets)
                        cutoff = max(1, int(len(sorted_rets) * 0.05))
                        cvar_95 = round(abs(sum(sorted_rets[:cutoff]) / cutoff), 6)

            # Open risk: sum of (quantity × entry_price) / equity
            if open_positions and equity > 0:
                total_notional = sum(
                    float(getattr(p, "quantity", 0) or 0.0) * float(getattr(p, "entry_price", 0) or 0.0)
                    for p in open_positions
                )
                open_risk_pct = round(total_notional / equity * 100, 2)

    except Exception as _exc:
        logger.debug("Account stats from DB failed: %s", _exc)

    # ── Reconcile with the broker's live open positions ──────────────────────
    # open_trades above comes from the DB position table, but paper-broker fills
    # live in the broker (same source /positions reads). Without this, the
    # summary reports 0 open trades / $0 margin while positions are actually
    # open. Use get_positions() so /account always agrees with /positions.
    try:
        _bpos = await _user_broker_call(user.sub, "get_positions")
        if _bpos:
            _MARGIN_RATE = 0.02  # matches PaperTradingBroker paper margin
            open_trades = len(_bpos)
            unrealized = round(sum(float(getattr(p, "unrealized_pnl", 0) or 0.0) for p in _bpos), 2)
            _bnotional = sum(
                abs(float(getattr(p, "quantity", 0) or 0.0))
                * float(getattr(p, "current_price", 0) or getattr(p, "entry_price", 0) or 0.0)
                for p in _bpos
            )
            margin_used = round(_bnotional * _MARGIN_RATE, 2)
            equity = round(balance + unrealized, 2)
            margin_free = round(max(equity - margin_used, 0.0), 2)
            margin_level = _margin_level(equity, margin_used)
            open_risk_pct = round((_bnotional / equity * 100) if equity > 0 else 0.0, 2)
    except Exception as _exc:
        logger.debug("Broker position reconciliation (live branch) failed: %s", _exc)

    # ── Kill switch state — use the injected helper so tests can override ─────
    kill_switch_active = False
    try:
        _ks = _get_kill_switch()
        kill_switch_active = bool(_ks and _ks.is_active())
    except Exception:  # nosec B110  # noqa: S110
        pass

    return {
        "account_id": _s(raw, "account_id", "id", "accountId", default=user.sub),
        "balance": round(balance, 2),
        "equity": round(equity, 2),
        "margin_used": round(margin_used, 2),
        "margin_free": round(margin_free, 2),
        "margin_level": margin_level,
        "daily_pnl": round(daily_pnl, 2),
        "daily_pnl_pct": daily_pnl_pct,
        "total_pnl": total_pnl,
        "unrealized_pnl": round(unrealized, 2),
        "win_rate": win_rate,
        "sharpe_ratio": sharpe_ratio,
        "sortino_ratio": sortino_ratio,
        "max_drawdown": max_drawdown,
        "open_trades": open_trades,
        "open_risk_pct": open_risk_pct,
        "cvar_95": cvar_95,
        "kill_switch": kill_switch_active,
        "currency": _s(raw, "currency", "base_currency", default="USD"),
        # Whether these figures are this user's alone. False means the
        # deployment is on a live single-account venue where one real account
        # sits behind every user, so the balance shown is the deployment's. The
        # caller is told rather than left to assume.
        "isolated": (await _resolve_account(user.sub)).isolated,
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
    prices: dict = {}

    # Path 1: price engine available (preferred — has yfinance + broker fallback)
    if app_state and app_state.price_engine:
        for symbol in app_state.price_engine.symbols:
            tick = app_state.price_engine.get_last_price(symbol)
            if tick:
                prices[symbol] = {
                    "bid": tick.bid,
                    "ask": tick.ask,
                    "last": getattr(tick, "last_price", None) or tick.mid,
                    "timestamp": tick.timestamp,
                }
        if prices:
            return prices

    # Path 2: broker market_prices direct (price engine not yet started)
    broker = getattr(app_state, "broker", None) if app_state else None
    market_prices = getattr(broker, "market_prices", {}) if broker else {}
    if market_prices:
        import time as _time

        _spread_map = {
            "XAUUSD": 0.30,
            "XAGUSD": 0.03,
            "EURUSD": 0.0001,
            "GBPUSD": 0.0002,
            "USDJPY": 0.02,
            "BTCUSD": 10.0,
        }
        now = _time.time()
        for sym, price in market_prices.items():
            if price and price > 0:
                spread = _spread_map.get(sym, price * 0.0002)
                prices[sym] = {
                    "bid": round(price - spread / 2, 5),
                    "ask": round(price + spread / 2, 5),
                    "last": round(price, 5),
                    "timestamp": now,
                }
        return prices

    # Path 3: yfinance real-time fallback (no broker required)
    # Maps internal symbol → yfinance ticker. Only used when no broker/engine
    # is running (API-only mode). Returns real market prices, not synthetic data.
    # Tickers come from config/multi_source_feed.yaml so this path cannot drift
    # from the feed config. Symbols configured with an empty ticker (spot metals
    # and oil, whose Yahoo futures contracts are delisted) are dropped rather
    # than substituted: the tracking ETFs quote a different number, and a
    # plausible wrong price on XAUUSD is far more dangerous than no price.
    _YF_MAP = {
        sym: ticker
        for sym, ticker in (
            (s, _yf_ticker_map().get(s, ""))
            for s in (
                "XAUUSD",
                "XAGUSD",
                "EURUSD",
                "GBPUSD",
                "USDJPY",
                "BTCUSD",
                "ETHUSD",
                "USDCAD",
                "AUDUSD",
                "USDCHF",
                "NZDUSD",
            )
        )
        if ticker
    }
    _SPREAD_MAP = {
        "XAUUSD": 0.30,
        "XAGUSD": 0.03,
        "EURUSD": 0.0001,
        "GBPUSD": 0.0002,
        "USDJPY": 0.02,
        "BTCUSD": 10.0,
        "ETHUSD": 1.0,
        "USDCAD": 0.0002,
        "AUDUSD": 0.0001,
        "USDCHF": 0.0001,
        "NZDUSD": 0.0001,
    }
    try:
        import time as _time
        import yfinance as _yf

        tickers = list(_YF_MAP.values())
        if not tickers:
            raise RuntimeError("no yfinance tickers configured for any quoted symbol")
        data = await asyncio.wait_for(
            asyncio.to_thread(_yf.download, tickers, period="1d", interval="1m", progress=False, auto_adjust=True),
            timeout=10.0,
        )
        now = _time.time()
        for sym, yf_ticker in _YF_MAP.items():
            try:
                if hasattr(data.columns, "levels"):
                    close_col = ("Close", yf_ticker)
                    if close_col in data.columns:
                        series = data[close_col].dropna()
                    else:
                        continue
                else:
                    series = data["Close"].dropna()
                if series.empty:
                    continue
                price = float(series.iloc[-1])
                if price <= 0:
                    continue
                spread = _SPREAD_MAP.get(sym, price * 0.0002)
                prices[sym] = {
                    "bid": round(price - spread / 2, 5),
                    "ask": round(price + spread / 2, 5),
                    "last": round(price, 5),
                    "timestamp": now,
                }
            except Exception:  # noqa: S112
                continue
        if prices:
            return prices
    except Exception as _yf_exc:
        logger.warning("yfinance price fallback failed: %s", _yf_exc)

    # All paths exhausted — return empty dict (not 503) so the frontend
    # REST poll doesn't hang and can show the no_live_feed banner instead.
    return {}


def _load_gold_history_csv(timeframe: str, limit: int) -> list[dict]:
    """Deep historical XAUUSD OHLCV from a bundled CSV (daily back to ~2000).

    Used as a last-resort fallback for daily/weekly charts when the live price
    engine and yfinance are both unavailable, so the chart can still render
    decades of gold history (instead of a blank 503). Returns [] for intraday
    timeframes since the CSV is daily granularity.
    """
    if timeframe not in ("1d", "1w", "1wk"):
        return []
    import os

    import pandas as pd

    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    # Prefer the clean 40Y file (daily, back to 2000, no corrupted bars).
    # XAUUSD_50Y.csv is intentionally NOT used as the primary source: its
    # pre-2000 bars are corrupted (isolated bad prints, e.g. $43 when gold was
    # ~$270), which would feed bad data into charts. 40Y covers 2000→today
    # cleanly, which is the supported chart range.
    path = next(
        (
            p
            for p in (
                os.path.join(repo_root, "data", "XAUUSD_40Y.csv"),
                os.path.join(repo_root, "data", "XAUUSD_5Y.csv"),
            )
            if os.path.exists(p)
        ),
        None,
    )
    if not path:
        return []
    try:
        df = pd.read_csv(path)
        df.columns = [c.lower() for c in df.columns]
        if "date" not in df.columns or "close" not in df.columns:
            return []
        df["date"] = pd.to_datetime(df["date"], utc=True)
        df = df.set_index("date").sort_index()
        if timeframe in ("1w", "1wk"):
            df = (
                df.resample("1W")
                .agg({"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"})
                .dropna(subset=["open", "close"])
            )
        df = df.tail(limit)
        return [
            {
                "timestamp": int(ts.timestamp()),
                "open": round(float(row["open"]), 5),
                "high": round(float(row["high"]), 5),
                "low": round(float(row["low"]), 5),
                "close": round(float(row["close"]), 5),
                "volume": round(float(row.get("volume", 0) or 0), 2),
            }
            for ts, row in df.iterrows()
        ]
    except Exception as exc:
        logger.debug("Gold history CSV load failed: %s", exc)
        return []


# Symbols that have no yfinance equivalent and are absent from
# multi_source_feed.yaml. Kept empty deliberately: the futures contracts that
# used to serve them (ES=F, BZ=F) are delisted on Yahoo alongside the rest
# (see b439bef), and the tracking ETFs quote a different number entirely, so a
# substitute would be worse than no quote. Real data must come from
# twelve_data / alpha_vantage.
_YF_TICKER_EXTRA: dict[str, str] = {"US500": "", "UKOIL": ""}


@lru_cache(maxsize=1)
def _yf_ticker_map() -> dict[str, str]:
    """Canonical symbol → yfinance ticker, read from ``multi_source_feed.yaml``.

    The mapping lives in the feed config so there is exactly one place where a
    ticker can be wrong. A previous hand-maintained copy of this table in this
    module silently kept serving Yahoo's delisted futures contracts (XAUUSD →
    ``GC=F``) for every chart request long after the config had been corrected.

    An empty string is meaningful and must be preserved: it means "Yahoo does
    not serve this instrument, skip yfinance entirely" rather than "unknown".
    """
    mapping = dict(_YF_TICKER_EXTRA)
    try:
        import yaml

        cfg_path = _Path(__file__).resolve().parent.parent / "config" / "multi_source_feed.yaml"
        with cfg_path.open("r", encoding="utf-8") as fh:
            cfg = yaml.safe_load(fh) or {}
        symbols = (cfg.get("multi_source_feed") or {}).get("symbols") or {}
        for sym, scfg in symbols.items():
            if isinstance(scfg, dict) and "yfinance_ticker" in scfg:
                mapping[str(sym).upper()] = str(scfg["yfinance_ticker"] or "")
    except Exception as exc:
        logger.warning(
            "OHLCV: could not read yfinance tickers from multi_source_feed.yaml (%s) — "
            "yfinance fallback limited to symbols whose ticker equals their name",
            exc,
        )
    return mapping


@router.get(
    "/ohlcv/{symbol:path}",
    response_model=list[OHLCVBar],
    summary="Get OHLCV candlestick data for a symbol",
)
async def get_ohlcv(
    symbol: str,
    timeframe: str = "1h",
    limit: int = 100,
    user: TokenPayload = Depends(get_current_user),
):
    """Get OHLCV data. Requires: any authenticated user. Symbol validated server-side.

    Accepts both slash-separated (XAU/USD) and concatenated (XAUUSD) forms.
    The :path converter captures the full path segment including any '/' characters
    so that un-encoded slashes in the URL are handled gracefully.
    """
    # Normalise: XAU/USD, XAU_USD, xau_usd → XAUUSD
    symbol = symbol.replace("/", "").replace("%2F", "").replace("_", "").upper()
    # Validate against the same allowed-symbol set used for order placement.
    # This prevents data leakage for unsupported instruments and keeps the
    # OHLCV endpoint consistent with the order entry allowlist.
    try:
        symbol = validate_order_symbol(symbol)
    except HTTPException:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Symbol '{symbol}' is not in the permitted instrument list.",
        ) from None

    # ── Try price engine first ────────────────────────────────────────────────
    if app_state and app_state.price_engine:
        try:
            data = await asyncio.wait_for(
                app_state.price_engine.get_ohlcv(symbol, timeframe, limit),
                timeout=25.0,
            )
            if data and len(data) >= 2:
                prices = [d.close for d in data]
                # Accept any bars with at least minimal variation; flat bars from the
                # paper engine are acceptable if no external feed is available.
                if max(prices) - min(prices) > 0.0:
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
        except TimeoutError:
            logger.warning("Price engine OHLCV timed out for %s — falling back to yfinance", symbol)
        except Exception as exc:
            logger.debug("Price engine OHLCV failed for %s: %s — falling back to yfinance", symbol, exc)

    # ── Direct yfinance fallback ──────────────────────────────────────────────
    # Used when price engine is unavailable or returns flat bars.
    #
    # The ticker is resolved *before* the try block on purpose. An empty mapping
    # entry means "Yahoo does not serve this instrument" — a configured fact, not
    # a failure — so it must not travel through the `except Exception` below,
    # which would log it as a fallback error. `_yf_ticker_map` handles its own
    # I/O errors and always returns a dict, so this lookup cannot raise.
    ticker_sym = _yf_ticker_map().get(symbol, symbol)
    if not ticker_sym:
        # Skip the fetch rather than spend the 20s timeout on a ticker known to
        # return nothing; fall through to the CSV history / 503 below.
        logger.info("OHLCV: no yfinance ticker configured for %s — skipping to next source", symbol)
    else:
        try:
            import yfinance as _yf

            # Map timeframe → (yfinance interval, fetch period).
            # Periods are capped to avoid slow downloads; 4h is resampled from 1h.
            # yfinance only provides 1h data for up to 730 days but fetching that
            # much is slow — cap at 60d which gives ~1440 bars (enough for any chart).
            _TF_MAP = {
                "1m": ("1m", "7d"),
                "5m": ("5m", "60d"),
                "15m": ("15m", "60d"),
                "30m": ("30m", "60d"),
                "1h": ("1h", "60d"),  # ~1440 bars — fast, plenty of history
                "4h": ("1h", "60d"),  # fetch 1h then resample → 4h
                "1d": ("1d", "max"),  # full daily history (gold back to ~2000)
                "1w": ("1wk", "max"),  # full weekly history
            }
            interval, period = _TF_MAP.get(timeframe, ("1h", "60d"))
            resample_4h = timeframe == "4h"

            loop = asyncio.get_running_loop()

            def _fetch_yf() -> list:
                t = _yf.Ticker(ticker_sym)
                # NB: no `progress=` argument — that is a yf.download() parameter.
                # Ticker.history() rejects it with TypeError before any network I/O,
                # which silently disabled this entire fallback for every symbol.
                df = t.history(period=period, interval=interval, auto_adjust=True)
                if df.empty:
                    return []
                # Resample 1h → 4h when requested
                if resample_4h:
                    df = (
                        df.resample("4h")
                        .agg(
                            {
                                "Open": "first",
                                "High": "max",
                                "Low": "min",
                                "Close": "last",
                                "Volume": "sum",
                            }
                        )
                        .dropna(subset=["Open", "Close"])
                    )
                df = df.tail(limit)
                bars = []
                for ts, row in df.iterrows():
                    bars.append(
                        {
                            "timestamp": int(ts.timestamp()),
                            "open": round(float(row["Open"]), 5),
                            "high": round(float(row["High"]), 5),
                            "low": round(float(row["Low"]), 5),
                            "close": round(float(row["Close"]), 5),
                            "volume": round(float(row.get("Volume", 0)), 2),
                        }
                    )
                return bars

            bars = await asyncio.wait_for(loop.run_in_executor(None, _fetch_yf), timeout=20.0)
            if bars:
                logger.info("OHLCV yfinance direct: %s %s — %d bars", symbol, timeframe, len(bars))
                return bars
        except Exception as exc:
            logger.warning("OHLCV yfinance direct fallback failed for %s: %s", symbol, exc)

    # ── Bundled deep-history CSV fallback (gold daily/weekly) ─────────────────
    # When live feeds and yfinance are both unavailable, serve real gold history
    # from the bundled CSV so daily/weekly charts still show decades of data.
    if symbol == "XAUUSD":
        csv_bars = _load_gold_history_csv(timeframe, limit)
        if csv_bars:
            logger.info("OHLCV gold CSV history: %s %s — %d bars", symbol, timeframe, len(csv_bars))
            return csv_bars

    # All real data sources exhausted — return 503 so the frontend can display
    # a meaningful "data unavailable" state rather than rendering fake bars.
    logger.error(
        "OHLCV: all real data sources unavailable for %s %s "
        "(price engine + yfinance both failed). "
        "Configure at least one live data feed.",
        symbol,
        timeframe,
    )
    raise HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail={
            "error": "ohlcv_unavailable",
            "message": (
                f"No real OHLCV data available for {symbol} {timeframe}. "
                "The price engine and all fallback feeds are currently unavailable. "
                "Configure a live data feed (GOLDAPI_IO_KEY, OANDA_API_KEY, etc.)."
            ),
            "symbol": symbol,
            "timeframe": timeframe,
        },
    )


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
    """Get AI brain state. Returns a graceful fallback when brain is not yet initialised."""
    if app_state and app_state.brain:
        try:
            raw = app_state.brain.state.to_dict()
            # Normalise to the shape the frontend expects:
            #   mode            — human-readable operating mode
            #   status          — same as mode (alias)
            #   active_strategies — list of active strategy names
            #   confidence      — overall confidence score 0-1
            #   updated_at      — ISO timestamp
            system_state = raw.get("system_state", "running")
            # Derive active strategies from brain if available
            active_strategies: list[str] = []
            try:
                strats = getattr(app_state.brain, "active_strategies", None)
                if strats:
                    active_strategies = (
                        [getattr(s, "name", str(s)) for s in strats]
                        if not isinstance(strats, list)
                        else [s if isinstance(s, str) else getattr(s, "name", str(s)) for s in strats]
                    )
            except Exception:  # nosec B110  # noqa: S110
                pass
            # Derive confidence from performance metrics
            confidence = 0.0
            try:
                perf = raw.get("performance", {})
                # Use inverse of latency as a proxy for confidence when no ML score
                lat = perf.get("latency_ms", 0)
                confidence = max(0.0, min(1.0, 1.0 - lat / 1000.0)) if lat > 0 else 0.75
            except Exception:  # nosec B110  # noqa: S110
                pass
            return {
                **raw,
                "mode": system_state,
                "status": system_state,
                "active_strategies": active_strategies,
                "confidence": confidence,
                "updated_at": datetime.fromtimestamp(raw.get("timestamp", 0), tz=UTC).isoformat()
                if raw.get("timestamp")
                else datetime.now(UTC).isoformat(),
            }
        except Exception as _exc:
            logger.debug("brain state serialisation failed: %s", _exc)

    # Graceful fallback — brain not yet initialised (paper mode / startup)
    return {
        "status": "initialising",
        "mode": "paper",
        "active_strategies": [],
        "confidence": 0.0,
        "updated_at": datetime.now(UTC).isoformat(),
        "note": "Brain not yet initialised — paper trading mode",
    }


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
        "balance": float(os.getenv("PAPER_STARTING_BALANCE", "100000")),
        "currency": "USD",
        "mode": "paper",
        "activated_at": datetime.now(timezone.utc).isoformat(),
    }
    db_set(paper_key, account, changed_by="trading_api")
    logger.info("Paper trading activated for user=%s", user.sub)
    return {"status": "activated", "account": account}


@router.post("/paper/stop", status_code=200)
async def stop_paper_trading(
    user: TokenPayload = Depends(get_current_user),
):
    """
    Deactivate paper trading mode for the authenticated user.

    Removes the paper account session key so a fresh session can be
    started via /paper/start. Does not delete trade history.
    """
    from api.db_store import db_delete, db_get

    paper_key = f"paper:account:{user.sub}"
    existing = db_get(paper_key)
    if not existing:
        return {"status": "not_active"}

    db_delete(paper_key)
    logger.info("Paper trading deactivated for user=%s", user.sub)
    return {"status": "deactivated"}


@router.post("/emergency-stop")
async def emergency_stop(
    user: TokenPayload = Depends(require_role("admin")),
):
    """
    Trigger emergency stop — halts all trading immediately.

    Requires: role >= 'admin'. Logs the triggering user for audit trail.
    """
    # Activate the global kill switch FIRST. This is the hard halt that the
    # order-placement path (_check_kill_switch) actually enforces — calling
    # brain.emergency_stop() alone only sets a brain-internal flag and does
    # NOT block new orders from being accepted.
    ks = _get_kill_switch()
    if ks is not None:
        ks.activate(reason=f"Emergency stop triggered by user={user.sub}")

    # Also signal the decision brain to halt its loop, when available.
    if app_state and app_state.brain:
        app_state.brain.emergency_stop()

    if ks is None and (not app_state or not app_state.brain):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="No kill switch or brain available to halt trading",
        )

    logger.critical(
        "Emergency stop triggered by user=%s — kill_switch_active=%s",
        user.sub,
        ks.is_active() if ks is not None else False,
    )
    return {
        "status": "emergency_stop_triggered",
        "triggered_by": user.sub,
        "kill_switch_active": ks.is_active() if ks is not None else False,
    }


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


async def _query_trades(user_id: str, symbol: str | None, limit: int, offset: int) -> list:
    """Fetch trades from DB for the given user via TradeRepository."""
    try:
        from database.async_connection import _default_pool as _async_pool
        from database.repositories.trade_repository import TradeRepository as _TradeRepo

        if _async_pool is None:
            raise RuntimeError("Async DB pool not initialised")
        async with _async_pool.session() as _db:
            # Repository is stateless — pass session as first positional arg.
            repo = _TradeRepo()
            trades = await repo.get_by_user(
                _db,
                user_id=user_id,
                limit=limit,
            )
            return list(trades)
    except Exception as exc:
        logger.warning("Trade history DB query failed: %s", exc)
        return []


def _trade_to_dict(t) -> dict:
    raw_status = getattr(t, "status", "")
    status_str = raw_status.value if hasattr(raw_status, "value") else str(raw_status or "")
    entry_time = getattr(t, "entry_time", None)
    exit_time = getattr(t, "exit_time", None)
    # quantity: prefer entry_quantity (canonical column), fall back to size or quantity
    qty = getattr(t, "entry_quantity", None) or getattr(t, "size", None) or getattr(t, "quantity", None) or 0
    trade_id_val = getattr(t, "trade_id", None) or str(getattr(t, "id", ""))
    entry_time_str = entry_time.isoformat() if hasattr(entry_time, "isoformat") else str(entry_time or "")
    exit_time_str = exit_time.isoformat() if hasattr(exit_time, "isoformat") else str(exit_time or "")
    qty_float = float(qty or 0)

    # Duration in minutes between entry and exit
    duration_minutes: int | None = None
    try:
        import datetime as _dt

        _e = (
            entry_time
            if hasattr(entry_time, "timestamp")
            else _dt.datetime.fromisoformat(entry_time_str)
            if entry_time_str
            else None
        )
        _x = (
            exit_time
            if hasattr(exit_time, "timestamp")
            else _dt.datetime.fromisoformat(exit_time_str)
            if exit_time_str
            else None
        )
        if _e and _x:
            duration_minutes = max(0, int((_x - _e).total_seconds() / 60))
    except Exception:  # nosec B110  # noqa: S110
        pass

    return {
        # Canonical keys (backend / CSV)
        "trade_id": trade_id_val,
        "symbol": getattr(t, "symbol", "") or "",
        "side": getattr(t, "side", "") or "",
        "quantity": qty_float,
        "entry_price": float(getattr(t, "entry_price", 0) or 0),
        "exit_price": float(t.exit_price) if getattr(t, "exit_price", None) is not None else None,
        "realized_pnl": float(getattr(t, "realized_pnl", 0) or 0),
        "commission": float(getattr(t, "commission", 0) or 0),
        "status": status_str,
        "strategy": getattr(t, "strategy", "") or "",
        "entry_time": entry_time_str,
        "exit_time": exit_time_str,
        # Frontend-expected aliases — kept alongside the canonical keys for
        # backward compatibility.  Trade.tsx uses `id`, `size`, `opened_at`,
        # `closed_at`; Trading.tsx uses `size`; Portfolio.tsx uses `id`,
        # `opened_at`, `closed_at`.  Removing either set would break one of
        # those pages, so both are emitted here.
        "id": trade_id_val,
        "size": qty_float,
        "opened_at": entry_time_str,
        "closed_at": exit_time_str,
        "duration_minutes": duration_minutes,
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
    trades = await _query_trades(user.sub, symbol, limit, offset)
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
    trades = await _query_trades(user.sub, symbol, limit, offset=0)

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
    def list_strategies(user: TokenPayload = Depends(get_current_user)):
        return list(_strategy_store.values())

    @r.post("/strategies", status_code=201)
    def create_strategy(req: StrategyCreateRequest, user: TokenPayload = Depends(require_role("trader"))):
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
            raise HTTPException(400, f"Unknown strategy type: {req.strategy_type}") from None
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
    def get_strategy(strategy_id: str, user: TokenPayload = Depends(get_current_user)):
        key = _resolve(strategy_id)
        if key is None:
            raise HTTPException(404, "Strategy not found") from None
        return _strategy_store[key]

    @r.delete("/strategies/{strategy_id}")
    def delete_strategy(strategy_id: str, user: TokenPayload = Depends(require_role("admin"))):
        key = _resolve(strategy_id)
        if key is None:
            raise HTTPException(404, "Strategy not found") from None
        del _strategy_store[key]
        return {"status": "deleted"}

    @r.post("/strategies/{strategy_id}/start")
    def start_strategy(strategy_id: str, user: TokenPayload = Depends(require_role("trader"))):
        key = _resolve_strategy_key(strategy_id)
        if key is None:
            raise HTTPException(404, "Strategy not found") from None
        _strategy_store[key]["enabled"] = True
        return {"status": "started", "strategy_id": strategy_id}

    @r.post("/strategies/{strategy_id}/stop")
    def stop_strategy(strategy_id: str, user: TokenPayload = Depends(require_role("trader"))):
        key = _resolve_strategy_key(strategy_id)
        if key is None:
            raise HTTPException(404, "Strategy not found") from None
        _strategy_store[key]["enabled"] = False
        return {"status": "stopped", "strategy_id": strategy_id}


def _register_risk_performance_routes(r: Any) -> None:
    """Register position-size, risk-metrics, and performance routes."""
    from fastapi import HTTPException
    import math as _math

    @r.post("/position-size")
    def calculate_position_size(req: PositionSizeRequest, user: TokenPayload = Depends(get_current_user)):
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
    def get_risk_metrics(user: TokenPayload = Depends(get_current_user)):
        try:
            broker = getattr(app_state, "broker", None)
            if broker is None:
                raise AttributeError("no broker")
            # Use sync helper when available (PaperTradingBroker), otherwise
            # fall back to asyncio.run for async-only brokers.
            if hasattr(broker, "_get_account_info_sync"):
                account = broker._get_account_info_sync()
            else:
                account = (
                    asyncio.run(broker.get_account_info())
                    if asyncio.iscoroutinefunction(broker.get_account_info)
                    else broker.get_account_info()
                )
            if hasattr(broker, "_get_positions_sync"):
                positions = broker._get_positions_sync()
            elif hasattr(broker, "get_positions"):
                _pos = broker.get_positions()
                positions = asyncio.run(_pos) if asyncio.iscoroutine(_pos) else _pos
            else:
                positions = []

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
    def get_performance_summary(user: TokenPayload = Depends(get_current_user)):
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
    def get_strategy_performance(strategy_id: str, user: TokenPayload = Depends(get_current_user)):
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
except Exception:  # nosec B110 — strategy sub-router registration failure is non-fatal at import time
    logger.exception("Failed to register strategy sub-router")


# ── /trading/risk — alias for /trading/risk-metrics ──────────────────────────
# Frontend chart-api.ts calls GET /trading/risk; backend registered the
# endpoint as /trading/risk-metrics inside the strategy sub-router.


@router.get("/risk", response_model=None, summary="Risk metrics snapshot")
async def get_risk_alias(user: TokenPayload = Depends(get_current_user)):
    """
    Fast risk metrics snapshot — returns immediately from in-memory broker state.
    No blocking I/O. Falls back to zeros when broker is not yet initialised.
    """

    try:
        broker = getattr(app_state, "broker", None)
        if broker is None:
            raise AttributeError("no broker")

        # Use account info (always fast — in-memory for paper broker)
        _acct_coro = broker.get_account_info()
        account = await _acct_coro if asyncio.iscoroutine(_acct_coro) else _acct_coro
        balance = float(getattr(account, "balance", 100_000.0) or 100_000.0)
        equity = float(getattr(account, "equity", balance) or balance)
        margin_used = float(getattr(account, "margin_used", 0.0) or 0.0)
        daily_pnl = float(getattr(account, "daily_pnl", 0.0) or 0.0)
        open_risk_pct = (margin_used / equity * 100) if equity > 0 else 0.0

        # Max drawdown from equity history (fast — list in memory)
        max_dd = 0.0
        try:
            history = broker.get_equity_history() if hasattr(broker, "get_equity_history") else []
            if len(history) >= 2:
                values = [v for _, v in history]
                peak = values[0]
                for v in values:
                    peak = max(peak, v)
                    dd = (peak - v) / peak if peak > 0 else 0.0
                    max_dd = max(max_dd, dd)
        except Exception:  # nosec B110  # noqa: S110
            pass

        _pos_coro = broker.get_positions() if hasattr(broker, "get_positions") else []
        positions = await _pos_coro if asyncio.iscoroutine(_pos_coro) else _pos_coro
        open_count = len(positions)
        kill_switch = False
        try:
            ks = _get_kill_switch()
            kill_switch = bool(ks and ks.is_active())
        except Exception:  # nosec B110  # noqa: S110
            pass

        return {
            "daily_pnl": round(daily_pnl, 2),
            "daily_pnl_pct": round((daily_pnl / balance * 100) if balance > 0 else 0.0, 4),
            "max_drawdown": round(max_dd * 100, 3),
            "open_positions": open_count,
            "margin_used": round(margin_used, 2),
            "open_risk_pct": round(open_risk_pct, 3),
            "kill_switch": kill_switch,
            "risk_score": min(100.0, round(max_dd * 100 * 2 + open_count * 5, 1)),
            "balance": round(balance, 2),
            "equity": round(equity, 2),
        }
    except Exception as exc:
        logger.debug("GET /trading/risk fallback: %s", exc)
        return {
            "daily_pnl": 0.0,
            "daily_pnl_pct": 0.0,
            "max_drawdown": 0.0,
            "open_positions": 0,
            "margin_used": 0.0,
            "open_risk_pct": 0.0,
            "kill_switch": False,
            "risk_score": 0.0,
            "balance": 0.0,
            "equity": 0.0,
        }


# ── /trading/ai-analysis ──────────────────────────────────────────────────────
# Frontend chart-api.ts POSTs a ChartClickContext and expects an AIAnalysis
# response: id, timestamp, context, regime, summary, keyDrivers, etc.


@router.post("/ai-analysis", response_model=None, summary="AI chart-click analysis")
async def get_ai_analysis(context: dict, user: TokenPayload = Depends(get_current_user)):
    """
    Accept a ChartClickContext payload and return an AIAnalysis object.

    Fetches real OHLCV via yfinance for regime detection and ATR calculation.
    Falls back gracefully when the ML stack is unavailable.
    """
    import uuid as _uuid
    import time as _time

    symbol: str = context.get("symbol", "XAUUSD")
    # Normalise XAU/USD, XAU_USD → XAUUSD
    symbol_norm = symbol.replace("/", "").replace("%2F", "").replace("_", "").upper()
    price: float = float(context.get("price", 0.0))
    timeframe: str = context.get("timeframe", "1h")
    timestamp: int = int(context.get("timestamp", _time.time() * 1000))

    # ── Fetch real OHLCV via yfinance for analysis ────────────────────────────
    _YF_MAP = {
        "XAUUSD": "GC=F",
        "XAGUSD": "SI=F",
        "EURUSD": "EURUSD=X",
        "GBPUSD": "GBPUSD=X",
        "USDJPY": "JPY=X",
        "USDCHF": "CHF=X",
        "AUDUSD": "AUDUSD=X",
        "BTCUSD": "BTC-USD",
        "ETHUSD": "ETH-USD",
        "US500": "ES=F",
        "NAS100": "NQ=F",
        "USOIL": "CL=F",
    }
    _TF_MAP = {
        "1m": ("1m", "7d"),
        "5m": ("5m", "60d"),
        "15m": ("15m", "60d"),
        "1h": ("1h", "60d"),
        "4h": ("1h", "60d"),
        "1d": ("1d", "1y"),
    }
    ticker_sym = _YF_MAP.get(symbol_norm, symbol_norm)
    interval, period = _TF_MAP.get(timeframe, ("1h", "60d"))

    ohlcv_bars: list[dict] = []
    try:
        import yfinance as _yf

        loop = asyncio.get_running_loop()

        def _fetch():
            t = _yf.Ticker(ticker_sym)
            df = t.history(period=period, interval=interval, auto_adjust=True)
            if df.empty:
                return []
            df = df.tail(100)
            return [
                {
                    "open": float(r["Open"]),
                    "high": float(r["High"]),
                    "low": float(r["Low"]),
                    "close": float(r["Close"]),
                    "volume": float(r.get("Volume", 0)),
                }
                for _, r in df.iterrows()
            ]

        ohlcv_bars = await asyncio.wait_for(loop.run_in_executor(None, _fetch), timeout=25.0)
    except TimeoutError:
        logger.warning("ai-analysis: yfinance fetch timed out for %s — using price-only fallback", symbol_norm)
    except Exception as exc:
        logger.warning("ai-analysis: yfinance fetch failed for %s: %s", symbol_norm, exc)

    # Use last close as price if not provided
    if price <= 0 and ohlcv_bars:
        price = ohlcv_bars[-1]["close"]

    # ── ATR (14-period) ───────────────────────────────────────────────────────
    atr_estimate = price * 0.005  # 0.5% fallback
    if len(ohlcv_bars) >= 14:
        trs = []
        for i in range(1, min(15, len(ohlcv_bars))):
            h = ohlcv_bars[-i]["high"]
            l = ohlcv_bars[-i]["low"]
            pc = ohlcv_bars[-i - 1]["close"] if i + 1 <= len(ohlcv_bars) else l
            trs.append(max(h - l, abs(h - pc), abs(l - pc)))
        if trs:
            atr_estimate = sum(trs) / len(trs)

    # ── Regime detection from OHLCV ───────────────────────────────────────────
    regime = "ranging"
    regime_confidence = 0.5
    volatility = "medium"
    trend = "neutral"

    if len(ohlcv_bars) >= 20:
        closes = [b["close"] for b in ohlcv_bars]
        # EMA-based trend
        ema20 = closes[-1]
        for c in reversed(closes[-20:]):
            ema20 = ema20 * 0.9 + c * 0.1
        ema50 = closes[-1]
        for c in reversed(closes[-min(50, len(closes)) :]):
            ema50 = ema50 * 0.96 + c * 0.04

        price_vs_ema20 = (closes[-1] - ema20) / ema20 if ema20 > 0 else 0
        ema_spread = (ema20 - ema50) / ema50 if ema50 > 0 else 0

        # Volatility: ATR as % of price
        atr_pct = atr_estimate / price if price > 0 else 0
        if atr_pct > 0.015:
            volatility = "high"
        elif atr_pct < 0.005:
            volatility = "low"

        # Regime classification
        if abs(ema_spread) > 0.005 and abs(price_vs_ema20) > 0.003:
            if ema_spread > 0:
                regime = "trending_up"
                trend = "bullish"
                regime_confidence = min(0.85, 0.5 + abs(ema_spread) * 20)
            else:
                regime = "trending_down"
                trend = "bearish"
                regime_confidence = min(0.85, 0.5 + abs(ema_spread) * 20)
        else:
            regime = "ranging"
            trend = "neutral"
            regime_confidence = 0.6

    # ── Signal / recommended action ───────────────────────────────────────────
    recommended_action = "hold"
    action_confidence = 0.5
    key_drivers: list[str] = []
    warnings: list[str] = []

    if ohlcv_bars:
        closes = [b["close"] for b in ohlcv_bars]
        # RSI (14)
        gains, losses = [], []
        for i in range(1, min(15, len(closes))):
            d = closes[-i] - closes[-i - 1]
            (gains if d > 0 else losses).append(abs(d))
        avg_gain = sum(gains) / 14 if gains else 0
        avg_loss = sum(losses) / 14 if losses else 0.001
        rsi = 100 - (100 / (1 + avg_gain / avg_loss))

        if rsi < 35:
            recommended_action = "buy"
            action_confidence = round(0.5 + (35 - rsi) / 70, 3)
            key_drivers.append(f"RSI oversold ({rsi:.1f})")
        elif rsi > 65:
            recommended_action = "sell"
            action_confidence = round(0.5 + (rsi - 65) / 70, 3)
            key_drivers.append(f"RSI overbought ({rsi:.1f})")
        else:
            key_drivers.append(f"RSI neutral ({rsi:.1f})")

        if regime in ("trending_up",):
            key_drivers.append("Uptrend confirmed by EMA alignment")
            if recommended_action == "hold":
                recommended_action = "buy"
                action_confidence = 0.6
        elif regime in ("trending_down",):
            key_drivers.append("Downtrend confirmed by EMA alignment")
            if recommended_action == "hold":
                recommended_action = "sell"
                action_confidence = 0.6

        key_drivers.append(f"ATR: {atr_estimate:.4f} ({atr_estimate / price * 100:.2f}% of price)")
        key_drivers.append(f"Volatility: {volatility}")

        if volatility == "high":
            warnings.append("High volatility — widen stops")

    summary = (
        f"{symbol} is in a {regime.replace('_', ' ')} regime "
        f"({regime_confidence * 100:.0f}% confidence). "
        f"Trend: {trend}. "
        f"Recommended: {recommended_action.upper()} at {price:.4f}."
    )

    # Map buy/sell/hold → long/short/neutral for frontend AIResult.direction
    _dir_map = {"buy": "long", "sell": "short", "hold": "neutral"}
    direction = _dir_map.get(recommended_action, "neutral")

    sl = round(price - atr_estimate * 1.5, 5)
    tp = round(price + atr_estimate * 2.5, 5)
    if direction == "short":
        sl = round(price + atr_estimate * 1.5, 5)
        tp = round(price - atr_estimate * 2.5, 5)

    return {
        "id": str(_uuid.uuid4()),
        "timestamp": timestamp,
        "context": context,
        # Fields expected by AIResult interface
        "direction": direction,
        "confidence": round(min(action_confidence, 0.95), 3),
        "reasoning": summary,
        "regime": regime,
        "stop_loss": sl,
        "take_profit": tp,
        "entry_zone": [round(price - atr_estimate * 0.3, 5), round(price + atr_estimate * 0.3, 5)],
        "key_levels": [
            round(price - atr_estimate * 2, 5),
            round(price - atr_estimate, 5),
            round(price + atr_estimate, 5),
            round(price + atr_estimate * 2, 5),
        ],
        # Extended fields
        "regimeConfidence": round(regime_confidence, 3),
        "volatility": volatility,
        "trend": trend,
        "summary": summary,
        "keyDrivers": key_drivers,
        "riskAssessment": f"ATR({len(ohlcv_bars)}): {atr_estimate:.4f} | SL: {sl:.4f} | TP: {tp:.4f}",
        "recommendedAction": recommended_action,
        "actionConfidence": round(min(action_confidence, 0.95), 3),
        "priceTargets": {
            "bull": round(price + atr_estimate * 2, 5),
            "bear": round(price - atr_estimate * 2, 5),
            "base": round(price + atr_estimate * (1 if direction == "long" else -1), 5),
            "stop_loss": sl,
            "take_profit": tp,
        },
        "timeHorizon": "4H–1D",
        "warnings": warnings,
        "data_source": "yfinance" if ohlcv_bars else "fallback",
        "bars_analyzed": len(ohlcv_bars),
    }


# ── Regime status endpoint ────────────────────────────────────────────────────


@router.get("/regime", response_model=None, summary="Current market regime and active strategy")
async def get_regime_status(
    symbol: str = "XAUUSD",
    user: TokenPayload = Depends(get_current_user),
):
    """
    Return the current detected market regime, confidence score, and the
    strategy selected by the RegimeRouter for that regime.

    Uses real OHLCV from yfinance for regime detection.
    """

    # Normalise symbol — guard against None (optional query param)
    symbol = symbol or "XAUUSD"
    # Normalise XAU/USD, XAU_USD → XAUUSD
    symbol_norm = symbol.replace("/", "").replace("%2F", "").replace("_", "").upper()

    _YF_MAP = {
        "XAUUSD": "GC=F",
        "XAGUSD": "SI=F",
        "EURUSD": "EURUSD=X",
        "GBPUSD": "GBPUSD=X",
        "USDJPY": "JPY=X",
        "BTCUSD": "BTC-USD",
        "ETHUSD": "ETH-USD",
        "US500": "ES=F",
        "NAS100": "NQ=F",
    }
    ticker_sym = _YF_MAP.get(symbol_norm, "GC=F")
    app_env = os.getenv("APP_ENV", os.getenv("ENVIRONMENT", "")).lower()
    allow_remote_market_fetch = app_env not in {"ci", "test", "testing"}

    closes: list[float] = []
    highs: list[float] = []
    lows: list[float] = []

    try:
        if not allow_remote_market_fetch:
            raise RuntimeError("remote market-data fetch disabled in CI/test environment")
        import yfinance as _yf

        loop = asyncio.get_running_loop()

        def _fetch():
            t = _yf.Ticker(ticker_sym)
            df = t.history(period="60d", interval="1h", auto_adjust=True)
            if df.empty:
                return [], [], []
            df = df.tail(100)
            return (
                [float(r["Close"]) for _, r in df.iterrows()],
                [float(r["High"]) for _, r in df.iterrows()],
                [float(r["Low"]) for _, r in df.iterrows()],
            )

        closes, highs, lows = await asyncio.wait_for(loop.run_in_executor(None, _fetch), timeout=25.0)
    except TimeoutError:
        logger.warning("regime: yfinance fetch timed out for %s", symbol_norm)
    except Exception as exc:
        logger.warning("regime: yfinance fetch failed for %s: %s", symbol_norm, exc)

    # ── Regime detection ──────────────────────────────────────────────────────
    regime = "ranging"
    confidence = 0.5
    volatility = "medium"
    trend = "neutral"
    description = "Insufficient data for regime detection"

    if len(closes) >= 20:
        # EMA 20 and EMA 50
        ema20 = closes[-1]
        for c in reversed(closes[-20:]):
            ema20 = ema20 * 0.9 + c * 0.1
        ema50 = closes[-1]
        for c in reversed(closes[-min(50, len(closes)) :]):
            ema50 = ema50 * 0.96 + c * 0.04

        ema_spread = (ema20 - ema50) / ema50 if ema50 > 0 else 0
        price_vs_ema20 = (closes[-1] - ema20) / ema20 if ema20 > 0 else 0

        # ATR for volatility
        trs = [
            max(highs[i] - lows[i], abs(highs[i] - closes[i - 1]), abs(lows[i] - closes[i - 1]))
            for i in range(1, min(15, len(closes)))
        ]
        atr = sum(trs) / len(trs) if trs else closes[-1] * 0.005
        atr_pct = atr / closes[-1] if closes[-1] > 0 else 0

        if atr_pct > 0.015:
            volatility = "high"
        elif atr_pct < 0.005:
            volatility = "low"

        # Regime
        if ema_spread > 0.005 and price_vs_ema20 > 0.002:
            regime = "trending_up"
            trend = "bullish"
            confidence = min(0.90, 0.55 + abs(ema_spread) * 15)
            description = f"Bullish trend: EMA20 ({ema20:.2f}) > EMA50 ({ema50:.2f}), price above EMA20"
        elif ema_spread < -0.005 and price_vs_ema20 < -0.002:
            regime = "trending_down"
            trend = "bearish"
            confidence = min(0.90, 0.55 + abs(ema_spread) * 15)
            description = f"Bearish trend: EMA20 ({ema20:.2f}) < EMA50 ({ema50:.2f}), price below EMA20"
        else:
            regime = "ranging"
            trend = "neutral"
            confidence = 0.65
            description = f"Ranging market: EMA spread {ema_spread * 100:.2f}%, ATR {atr_pct * 100:.2f}%"

    # Try regime router if available
    try:
        from core.app_state import app_state as _as

        rr = getattr(_as, "regime_router", None)
        if rr is not None:
            status_dict = rr.status()
            if status_dict.get("current_regime", "unknown") != "unknown":
                return {
                    **status_dict,
                    "regime": status_dict.get("current_regime", regime),
                    "confidence": status_dict.get("confidence", confidence),
                    "volatility": volatility,
                    "trend": trend,
                    "description": description,
                    "data_source": "regime_router",
                }
    except Exception:  # nosec B110  # noqa: S110
        pass

    return {
        "regime": regime,
        "current_regime": regime,
        "confidence": round(confidence, 3),
        "volatility": volatility,
        "trend": trend,
        "description": description,
        "selected_strategy": "TrendFollowing" if "trending" in regime else "MeanReversion",
        "manifest_entries": {},
        "data_source": "yfinance" if closes else "fallback",
        "bars_analyzed": len(closes),
    }


@router.get("/regime/history", response_model=None, summary="Recent regime transition history")
async def get_regime_history(
    limit: int = 20,
    user: TokenPayload = Depends(get_current_user),
):
    """Return the last N regime transitions with timestamps. Requires: any authenticated user."""
    try:
        from core.app_state import app_state

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
    user: TokenPayload = Depends(get_current_user),
):
    """
    Apply historical and hypothetical stress scenarios to a position.

    Requires: any authenticated user.

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
        _logger.exception("Stress test failed")
        raise HTTPException(status_code=500, detail="Stress test failed — check server logs") from None


# ── Chart-bot endpoints ───────────────────────────────────────────────────────
# These endpoints are called by frontend/src/features/chart-bot/services/chart-api.ts
# and provide technical analysis data for the interactive chart overlay.


def _ohlcv_to_df(ohlcv_list: list):
    """Convert a list of OHLCV namedtuples/dicts to a pandas DataFrame."""
    try:
        import pandas as pd

        if not ohlcv_list:
            return None
        rows = []
        for bar in ohlcv_list:
            if hasattr(bar, "_asdict"):
                rows.append(bar._asdict())
            elif hasattr(bar, "__dict__"):
                rows.append(bar.__dict__)
            else:
                rows.append(dict(bar))
        df = pd.DataFrame(rows)
        # Normalise column names to lowercase
        df.columns = [c.lower() for c in df.columns]
        return df
    except Exception as exc:
        logger.debug("_ohlcv_to_df failed: %s", exc)
        return None


def _bars_are_usable(bars) -> bool:
    """True when `bars` carry enough varying closes to be worth analysing.

    Mirrors the guardrail `/ohlcv` applies to price-engine output: at least two
    bars, with some movement between them. A flat run is the paper engine's
    placeholder, and handing it to the pattern/level detectors yields
    confident-looking output derived from data that says nothing — so it is
    treated as a miss, letting the yfinance/CSV fallbacks take their turn.

    Accepts both the attribute-style bars the price engine yields and the
    dict-style bars the fallbacks build. Bars with no readable close are
    unusable too: `_ohlcv_to_df` consumers index `df["close"]` directly.
    """
    if not bars or len(bars) < 2:
        return False
    closes: list[float] = []
    for bar in bars:
        value = bar.get("close") if isinstance(bar, dict) else getattr(bar, "close", None)
        try:
            closes.append(float(value))  # type: ignore[arg-type]
        except (TypeError, ValueError):
            return False
    return max(closes) - min(closes) > 0.0


async def _get_ohlcv_for_symbol(symbol: str, timeframe: str = "1h", limit: int = 200) -> list:
    """Fetch OHLCV bars for a symbol: price engine, then yfinance, then gold CSV.

    Used by /patterns and /levels. This previously asked the price engine and
    nothing else, returning [] on any miss — so both endpoints reported "no
    patterns" / "no levels" whenever the engine simply had no data for that
    symbol, which is a very different statement. /ohlcv already had the full
    fallback chain; these two never used it.

    Note the symbol form. Callers arrive via `_normalise_symbol` (OANDA style,
    `XAU_USD`) while `_yf_ticker_map` is keyed on the compact form used in
    config/multi_source_feed.yaml (`XAUUSD`), so the ticker lookup is done on
    the compact spelling. Passing the OANDA form straight through would miss
    every entry and silently disable the fallback again.

    The price-engine call carries the same timeout and usability check `/ohlcv`
    applies, so `/patterns` and `/levels` cannot hang longer than `/ohlcv` on a
    stalled engine, and placeholder bars do not suppress the fallbacks.
    """
    try:
        from core.app_state import app_state

        if app_state and app_state.price_engine:
            bars = await asyncio.wait_for(
                app_state.price_engine.get_ohlcv(symbol, timeframe, limit),
                timeout=25.0,
            )
            if _bars_are_usable(bars):
                return bars
            logger.debug(
                "Price engine returned %d unusable bar(s) for %s — trying yfinance",
                len(bars or []),
                symbol,
            )
    except TimeoutError:
        logger.warning("Price engine OHLCV timed out for %s — falling back to yfinance", symbol)
    except Exception as exc:
        logger.debug("Price engine OHLCV fetch failed for %s: %s", symbol, exc)

    compact = symbol.replace("/", "").replace("_", "").upper()

    # yfinance — same ticker table and "" == no Yahoo source convention as /ohlcv.
    ticker_sym = _yf_ticker_map().get(compact, compact)
    if ticker_sym:
        try:
            import yfinance as _yf

            interval, period = {
                "1m": ("1m", "7d"),
                "5m": ("5m", "60d"),
                "15m": ("15m", "60d"),
                "30m": ("30m", "60d"),
                "1h": ("1h", "60d"),
                "4h": ("1h", "60d"),
                "1d": ("1d", "max"),
                "1w": ("1wk", "max"),
            }.get(timeframe, ("1h", "60d"))

            def _fetch() -> list:
                df = _yf.Ticker(ticker_sym).history(period=period, interval=interval, auto_adjust=True)
                if df.empty:
                    return []
                if timeframe == "4h":
                    df = (
                        df.resample("4h")
                        .agg({"Open": "first", "High": "max", "Low": "min", "Close": "last", "Volume": "sum"})
                        .dropna(subset=["Open", "Close"])
                    )
                return [
                    {
                        "timestamp": int(ts.timestamp()),
                        "open": round(float(row["Open"]), 5),
                        "high": round(float(row["High"]), 5),
                        "low": round(float(row["Low"]), 5),
                        "close": round(float(row["Close"]), 5),
                        "volume": round(float(row.get("Volume", 0)), 2),
                    }
                    for ts, row in df.tail(limit).iterrows()
                ]

            loop = asyncio.get_running_loop()
            bars = await asyncio.wait_for(loop.run_in_executor(None, _fetch), timeout=20.0)
            if bars:
                return bars
        except Exception as exc:
            logger.debug("yfinance OHLCV fallback failed for %s: %s", compact, exc)

    # Bundled deep-history gold CSV — the last real source, as in /ohlcv.
    if compact == "XAUUSD":
        csv_bars = _load_gold_history_csv(timeframe, limit)
        if csv_bars:
            return csv_bars

    return []


def _normalise_symbol(symbol: str) -> str:
    """Convert any symbol variant to OANDA/price-engine form (XAU_USD).

    Delegates to utils.symbol.to_oanda so all normalisation logic lives
    in one place.  Kept as a module-level function for backward compat.
    """
    from utils.symbol import to_oanda

    return to_oanda(symbol)


@router.get("/levels", response_model=None, summary="Support and resistance levels for a symbol")
async def get_levels(
    symbol: str = Query(..., description="Trading symbol, e.g. XAU/USD"),
    timeframe: str = Query("1h", description="OHLCV timeframe"),
    limit: int = Query(200, ge=20, le=1000),
    user: TokenPayload = Depends(get_current_user),
):
    """
    Detect support and resistance levels using swing-high/low analysis.

    Returns levels grouped by type (support, resistance, pivot) with
    strength scores and touch counts.
    """
    norm = _normalise_symbol(symbol)
    ohlcv = await _get_ohlcv_for_symbol(norm, timeframe, limit)
    df = _ohlcv_to_df(ohlcv)

    if df is None or df.empty:
        return {"levels": [], "symbol": symbol, "note": "Insufficient OHLCV data"}

    try:
        from analysis.patterns.support_resistance import SupportResistanceDetector

        detector = SupportResistanceDetector()
        current_price = float(df["close"].iloc[-1]) if "close" in df.columns else None
        result = detector.detect_levels(df, current_price=current_price)

        levels = []
        for level_type, level_list in result.items():
            for lvl in level_list:
                entry = {
                    "type": level_type,
                    "price": float(getattr(lvl, "price", 0)),
                    "strength": float(getattr(lvl, "strength", 0)),
                    "touches": int(getattr(lvl, "touches", 0)),
                    "label": getattr(lvl, "label", level_type),
                }
                levels.append(entry)

        levels.sort(key=lambda x: x["strength"], reverse=True)
        return {"levels": levels, "symbol": symbol, "count": len(levels)}
    except Exception as exc:
        logger.warning("Support/resistance detection failed for %s: %s", symbol, exc)
        return {"levels": [], "symbol": symbol, "error": "Detection unavailable"}


def _df_timestamps_seconds(df) -> list[float] | None:
    """Extract per-bar unix-second timestamps from an OHLCV DataFrame.

    Handles a `time`/`timestamp`/`date` column in seconds, milliseconds, or
    pandas datetime form. Returns None if no usable time column exists.
    """
    try:
        import pandas as pd

        col = next((c for c in ("time", "timestamp", "date", "datetime") if c in df.columns), None)
        if col is None:
            return None
        series = df[col]
        if pd.api.types.is_datetime64_any_dtype(series):
            return [ts.timestamp() for ts in pd.to_datetime(series)]
        out: list[float] = []
        for v in series.tolist():
            f = float(v)
            out.append(f / 1000.0 if f > 1e10 else f)  # ms → s
        return out
    except Exception:  # nosec B110 — best-effort time extraction; caller falls back
        return None


def _build_trendlines_from_df(df) -> list[dict]:
    """Fit upper (resistance) and lower (support) trendlines through recent
    swing highs/lows and return them as chart-overlay ``TrendLine`` objects.

    Output matches the frontend ``TrendLine`` shape (startTime/startPrice/
    endTime/endPrice/type/strength/aiGenerated) so the chart can draw them
    directly.
    """
    from analysis.patterns.chart_patterns import _find_peaks, _find_troughs, _linear_fit

    cols = {c.lower(): c for c in df.columns}
    if "high" not in cols or "low" not in cols or "close" not in cols:
        return []

    highs = df[cols["high"]].astype(float).tolist()
    lows = df[cols["low"]].astype(float).tolist()
    n = len(highs)
    if n < 20:
        return []

    times = _df_timestamps_seconds(df) or [float(i) for i in range(n)]
    scale = sum(highs) / n
    flat = scale * 4e-3  # < ~0.4% total drift ⇒ horizontal

    def line(name: str, indices: list[int], values: list[float]) -> dict | None:
        # Use the most recent swings so the line reflects the current channel.
        pts = indices[-6:]
        if len(pts) < 2:
            return None
        xs = [float(i) for i in pts]
        ys = [values[i] for i in pts]
        slope, intercept, r2 = _linear_fit(xs, ys)
        x0, x1 = pts[0], pts[-1]
        start_price = slope * x0 + intercept
        end_price = slope * x1 + intercept
        disp = end_price - start_price
        kind = "uptrend" if disp > flat else "downtrend" if disp < -flat else "horizontal"
        return {
            "id": name,
            "startTime": times[x0],
            "startPrice": round(start_price, 5),
            "endTime": times[x1],
            "endPrice": round(end_price, 5),
            "type": kind,
            "strength": round(r2, 4),
            "aiGenerated": True,
        }

    out: list[dict] = []
    resistance = line("resistance", _find_peaks(highs, 3), highs)
    support = line("support", _find_troughs(lows, 3), lows)
    if resistance:
        out.append(resistance)
    if support:
        out.append(support)
    return out


@router.get("/trendlines", response_model=None, summary="Trendlines for a symbol")
async def get_trendlines(
    symbol: str = Query(..., description="Trading symbol, e.g. XAU/USD"),
    timeframe: str = Query("1h", description="OHLCV timeframe"),
    limit: int = Query(200, ge=20, le=1000),
    user: TokenPayload = Depends(get_current_user),
):
    """
    Detect support/resistance trendlines from OHLCV data.

    Fits an upper line through recent swing highs and a lower line through
    recent swing lows and returns them as chart-overlay ``TrendLine`` objects
    (startTime/startPrice/endTime/endPrice/type/strength).
    """
    norm = _normalise_symbol(symbol)
    ohlcv = await _get_ohlcv_for_symbol(norm, timeframe, limit)
    df = _ohlcv_to_df(ohlcv)

    if df is None or df.empty:
        return {"trendlines": [], "symbol": symbol, "note": "Insufficient OHLCV data"}

    try:
        trendlines = _build_trendlines_from_df(df)
        return {"trendlines": trendlines, "symbol": symbol, "count": len(trendlines)}
    except Exception as exc:
        logger.warning("Trendline detection failed for %s: %s", symbol, exc)
        return {"trendlines": [], "symbol": symbol, "error": "Detection unavailable"}


@router.get("/patterns", response_model=None, summary="Chart patterns for a symbol")
async def get_chart_patterns(
    symbol: str = Query(..., description="Trading symbol, e.g. XAU/USD"),
    timeframe: str = Query("1h", description="OHLCV timeframe"),
    limit: int = Query(200, ge=20, le=1000),
    min_confidence: float = Query(0.5, ge=0.0, le=1.0),
    user: TokenPayload = Depends(get_current_user),
):
    """
    Detect chart patterns for a symbol.

    Combines two engines so the result covers both classic reversal patterns
    and the broader continuation/harmonic families:
      * ChartPatternDetector  — head & shoulders, double top/bottom, triangles
      * AdvancedPatternDetector — wedges, flags, pennants, rectangles, harmonics,
        support/resistance

    Returns patterns sorted by confidence descending, de-duplicated across both
    engines, each with entry/target/stop price levels.
    """
    norm = _normalise_symbol(symbol)
    ohlcv = await _get_ohlcv_for_symbol(norm, timeframe, limit)
    df = _ohlcv_to_df(ohlcv)

    if df is None or df.empty:
        return {
            "patterns": [],
            "symbol": symbol,
            "count": 0,
            "note": (
                "No OHLCV data available for this symbol/timeframe yet. Pattern "
                "detection needs at least ~20 bars of history."
            ),
        }
    if len(df) < 20:
        return {
            "patterns": [],
            "symbol": symbol,
            "count": 0,
            "bars": int(len(df)),
            "note": (
                f"Only {len(df)} bars available; need at least 20 to detect patterns. Try a longer/lower timeframe."
            ),
        }

    # Use the last close as the entry fallback for patterns whose geometry does
    # not pin a precise breakout level (e.g. symmetrical triangles).
    try:
        last_close = float(df[[c for c in df.columns if c.lower() == "close"][0]].iloc[-1])
    except Exception:
        last_close = 0.0

    patterns: list[dict] = []

    # Canonical pattern names. The two engines name the same pattern differently
    # (classic: "head_and_shoulders", "bull_flag"; advanced enum: "head_shoulders",
    # "flag"), which defeated the cross-engine de-dup below and showed the SAME
    # pattern twice. Normalise both to one vocabulary so duplicates collapse.
    _PATTERN_ALIASES = {
        "head_and_shoulders": "head_shoulders",
        "inverse_head_and_shoulders": "inverse_head_shoulders",
        "bull_flag": "flag",
        "bear_flag": "flag",
        "bull_pennant": "pennant",
        "bear_pennant": "pennant",
    }

    def _canon(t: str) -> str:
        return _PATTERN_ALIASES.get(t, t)

    # ── Engine 1: classic reversal/continuation patterns ──────────────────────
    try:
        from analysis.patterns.chart_patterns import ChartPatternDetector

        for p in ChartPatternDetector().detect_patterns(df, min_confidence=min_confidence):
            entry = float(getattr(p, "entry_price", 0) or 0) or last_close
            patterns.append(
                {
                    "pattern_type": _canon(str(getattr(p, "pattern_type", ""))),
                    "direction": str(getattr(p, "direction", "neutral")),
                    "confidence": float(getattr(p, "confidence", 0)),
                    "entry_price": entry,
                    "target_price": float(getattr(p, "target_price", 0) or 0),
                    "stop_loss": float(getattr(p, "stop_loss", 0) or 0),
                    "start_index": int(getattr(p, "start_index", 0)),
                    "end_index": int(getattr(p, "end_index", 0)),
                    "description": str(getattr(p, "description", "")),
                    "source": "classic",
                }
            )
    except Exception as exc:
        logger.warning("Classic pattern detection failed for %s: %s", symbol, exc)

    # ── Engine 2: advanced families (wedges, flags, harmonics, S/R) ───────────
    try:
        from analysis.patterns.advanced_patterns import AdvancedPatternDetector

        for p in AdvancedPatternDetector().detect_all_patterns(df, min_confidence=min_confidence):
            patterns.append(
                {
                    "pattern_type": _canon(str(getattr(getattr(p, "pattern_type", ""), "value", ""))),
                    "direction": str(getattr(getattr(p, "direction", ""), "value", "neutral")),
                    "confidence": float(getattr(p, "confidence", 0)),
                    "entry_price": float(getattr(p, "entry_price", 0) or 0) or last_close,
                    "target_price": float(getattr(p, "target_price", 0) or 0),
                    "stop_loss": float(getattr(p, "stop_loss", 0) or 0),
                    "start_index": int(getattr(p, "pattern_start_idx", 0)),
                    "end_index": int(getattr(p, "pattern_end_idx", 0)),
                    "description": f"{str(getattr(getattr(p, 'pattern_type', ''), 'value', '')).replace('_', ' ').title()} pattern",
                    "source": "advanced",
                }
            )
    except Exception as exc:
        logger.warning("Advanced pattern detection failed for %s: %s", symbol, exc)

    # Collapse duplicates into distinct patterns. The detectors emit one signal
    # per sliding window, so a single flat zone produces dozens of overlapping/
    # adjacent same-type detections (e.g. 18 identical "rectangle bearish 0.71"
    # tiles). Merge any same-type + same-direction detections whose ranges
    # overlap OR sit within a small gap into ONE pattern spanning the whole
    # region, keeping the highest-confidence detection's levels. This yields one
    # pattern per real formation instead of the same pattern repeated.
    _ADJ_GAP = 3  # bars; tiled detections sit ~1 bar apart, distinct ones far more
    patterns.sort(key=lambda d: (d["pattern_type"], d["direction"], d["start_index"]))
    merged: list[dict] = []
    for cand in patterns:
        host = next(
            (
                k
                for k in merged
                if k["pattern_type"] == cand["pattern_type"]
                and k["direction"] == cand["direction"]
                and cand["start_index"] <= k["end_index"] + _ADJ_GAP
            ),
            None,
        )
        if host is None:
            merged.append(dict(cand))
            continue
        # Extend the region; adopt the stronger detection's confidence + levels.
        host["end_index"] = max(host["end_index"], cand["end_index"])
        if cand["confidence"] > host["confidence"]:
            for _k in ("confidence", "entry_price", "target_price", "stop_loss", "description", "source"):
                host[_k] = cand[_k]

    merged.sort(key=lambda d: d["confidence"], reverse=True)
    return {"patterns": merged, "symbol": symbol, "count": len(merged), "bars": int(len(df))}


@router.get("/equity-curve", response_model=None, summary="Equity curve data points")
async def get_equity_curve_alias(
    days: int = Query(90, ge=1, le=365),
    user: TokenPayload = Depends(get_current_user),
):
    """
    Return equity curve data points for the given number of days.

    Delegates to /api/performance/equity-curve — this alias exists so the
    chart-bot frontend can use a consistent /api/trading/* base path.
    """
    try:
        # The canonical handler is api.performance.equity_curve(_user=...); it
        # returns the full curve (no days arg). Call it directly with our user.
        from api.performance import equity_curve as _equity_curve

        return await _equity_curve(_user=user)
    except Exception as exc:
        logger.warning("equity-curve alias failed: %s", exc)
        # Return empty curve rather than 503 so the chart renders without crashing
        return {"data": [], "days": days}


@router.get("/microstructure", response_model=None, summary="Market microstructure snapshot")
async def get_microstructure_alias(
    symbol: str = Query(..., description="Trading symbol, e.g. XAU/USD"),
    user: TokenPayload = Depends(get_current_user),
):
    """
    Return market microstructure data (spread, order flow, VWAP) for a symbol.

    Delegates to the data-layer microstructure endpoint when available.
    """
    try:
        from data_layer.microstructure import get_microstructure_snapshot

        norm = _normalise_symbol(symbol)
        snap = await get_microstructure_snapshot(norm)
        return snap
    except Exception:  # nosec B110 — data-layer microstructure unavailable; build from tick data below  # noqa: S110
        pass

    # Fallback: build from price engine tick data
    try:
        from core.app_state import app_state

        if app_state and app_state.price_engine:
            norm = _normalise_symbol(symbol)
            tick = (
                app_state.price_engine.get_latest_tick(norm)
                if hasattr(app_state.price_engine, "get_latest_tick")
                else None
            )
            if tick:
                spread = float(getattr(tick, "ask", 0) - getattr(tick, "bid", 0))
                mid = (float(getattr(tick, "ask", 0)) + float(getattr(tick, "bid", 0))) / 2
                return {
                    "timestamp": int(datetime.now(UTC).timestamp() * 1000),
                    "spread": spread,
                    "spreadPct": spread / mid if mid else 0,
                    "bidDepth": 0,
                    "askDepth": 0,
                    "orderFlowImbalance": 0,
                    "tradePressure": 50,
                    "tickDirection": "flat",
                    "vwap": mid,
                    "twap": mid,
                    "marketImpact": 0,
                }
    except Exception as exc:
        logger.debug("Microstructure fallback failed: %s", exc)

    return {
        "timestamp": int(datetime.now(UTC).timestamp() * 1000),
        "spread": 0,
        "spreadPct": 0,
        "bidDepth": 0,
        "askDepth": 0,
        "orderFlowImbalance": 0,
        "tradePressure": 50,
        "tickDirection": "flat",
        "vwap": 0,
        "twap": 0,
        "marketImpact": 0,
    }
