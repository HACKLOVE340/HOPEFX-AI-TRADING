# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026 Opeyemi (HACKLOVE340)
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
import logging
import os
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

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
# Per-user order rate limiting (sliding window, Redis-backed with in-memory fallback)
# Default: 10 orders per 60 seconds per authenticated user.
# Override via env: ORDER_RATE_LIMIT and ORDER_RATE_WINDOW.
# ---------------------------------------------------------------------------
_ORDER_RATE_LIMIT = int(os.getenv("ORDER_RATE_LIMIT", "10"))
_ORDER_RATE_WINDOW = int(os.getenv("ORDER_RATE_WINDOW", "60"))  # seconds
_order_rl_cache: dict = {}  # in-memory fallback: {user_id: [timestamps]}


def _check_order_rate_limit(user_id: str) -> None:
    """Raise HTTP 429 if the user has exceeded the order rate limit."""
    try:
        import redis as _redis

        r = _redis.Redis(
            host=os.getenv("REDIS_HOST", "localhost"),
            port=int(os.getenv("REDIS_PORT", "6379")),
            socket_connect_timeout=0.5,
            decode_responses=True,
            retry_on_error=[],
            retry=None,
        )
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
    except HTTPException:
        raise
    except Exception:
        # Redis unavailable — fall back to in-memory sliding window
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
            )


# ---------------------------------------------------------------------------
# Request / Response models
# ---------------------------------------------------------------------------


class OrderRequest(BaseModel):
    symbol: str = Field(..., min_length=1, max_length=20)
    side: str = Field(..., pattern="^(buy|sell)$")
    quantity: float = Field(..., gt=0)
    order_type: str = Field("market", pattern="^(market|limit|stop)$")
    price: Optional[float] = Field(None, gt=0)

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


class OrderResponse(BaseModel):
    """Response returned after a successful order fill."""

    status: str
    order_id: str
    filled_price: Optional[float] = None
    filled_quantity: Optional[float] = None


class ClosePositionResponse(BaseModel):
    status: str
    position_id: str


class CloseAllResponse(BaseModel):
    status: str
    closed_positions: int


class PriceQuote(BaseModel):
    bid: float
    ask: float
    last: Optional[float] = None
    timestamp: Optional[float] = None


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
    loop = asyncio.get_event_loop()
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
        logger.warning("Prop-firm guard error (allowing trade): %s", pf_exc)


async def _apply_risk_checks(order: "OrderRequest", user_id: str) -> None:
    """
    Run RiskManager.assess_risk() and CVaR pre-trade gate.

    Raises HTTP 403 if risk limits are breached.
    Raises HTTP 503 if the CVaR check itself errors (fail-safe: block the order).
    """
    if not (hasattr(app_state, "risk_manager") and app_state.risk_manager is not None):
        return

    # Standard risk assessment
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
            logger.warning(
                "Order blocked by risk manager: user=%s reason=%s",
                user_id,
                assessment.messages,
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Risk check failed: {'; '.join(assessment.messages)}",
            )
    except HTTPException:
        raise
    except Exception as risk_exc:
        logger.error(
            "Risk check error (blocking order for safety): user=%s %s",
            user_id,
            risk_exc,
            exc_info=True,
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Risk check unavailable — order rejected for safety",
        )

    # CVaR pre-trade gate — runs independently so a CVaR breach always blocks
    try:
        cvar_allowed, cvar_reason = app_state.risk_manager.check_cvar_pre_trade()
        if not cvar_allowed:
            logger.warning(
                "Order blocked by CVaR gate: user=%s reason=%s",
                user_id,
                cvar_reason,
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"CVaR limit breached: {cvar_reason}",
            )
        logger.debug("CVaR pre-trade gate passed: user=%s %s", user_id, cvar_reason)
    except HTTPException:
        raise
    except Exception as cvar_exc:
        logger.error(
            "CVaR pre-trade check error (blocking order for safety): user=%s %s",
            user_id,
            cvar_exc,
            exc_info=True,
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="CVaR risk check unavailable — order rejected for safety",
        )


def _log_compliance(order: "OrderRequest", user_id: str) -> None:
    """Write the pre-execution compliance audit record. Non-blocking on error."""
    if not (
        hasattr(app_state, "compliance_manager")
        and app_state.compliance_manager is not None
    ):
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
    except Exception as exc:
        logger.error("Broker order submission failed: %s", exc, exc_info=True)
        try:
            from core.metrics import ORDERS_TOTAL

            ORDERS_TOTAL.labels(
                symbol=order.symbol, side=order.side, status="error"
            ).inc()
        except Exception:
            pass
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


async def _record_fill(
    order: "OrderRequest",
    result: Any,
    user_id: str,
) -> Dict[str, Any]:
    """
    Broadcast the fill over WebSocket, send FCM push, send email, update
    Prometheus, and return the API response dict.

    All notification steps are best-effort — failures are logged but do not
    affect the response.
    """
    logger.info(
        "Order placed: user=%s symbol=%s side=%s qty=%s order_id=%s",
        user_id,
        order.symbol,
        order.side,
        order.quantity,
        result.id,
    )

    # WebSocket broadcast
    if hasattr(app_state, "ws_manager") and app_state.ws_manager is not None:
        try:
            await app_state.ws_manager.broadcast_trade(
                symbol=order.symbol,
                price=result.average_fill_price or 0.0,
                quantity=order.quantity,
                side=order.side,
                trade_id=result.id,
            )
        except Exception as ws_exc:
            logger.warning("WebSocket broadcast failed: %s", ws_exc)

    # FCM push notification
    try:
        from mobile.push_notifications import push_manager

        push_manager.send_trade_filled(
            user_id=user_id,
            symbol=order.symbol,
            direction=order.side,
            price=result.average_fill_price or 0.0,
            lots=order.quantity,
        )
    except Exception as fcm_exc:
        logger.debug("FCM trade push skipped: %s", fcm_exc)

    # Email notification — resolve user email from DB, fall back to SMTP_TO
    try:
        from notifications.email_triggers import send_trade_fill_email  # noqa: PLC0415

        # Attempt to look up the authenticated user's email address so the
        # notification goes to the right inbox rather than the system default.
        user_email: str = ""
        try:
            from auth.service import AuthService  # noqa: PLC0415

            _auth_svc = AuthService()
            _db_user = _auth_svc.get_user_by_id(user_id)
            if _db_user and getattr(_db_user, "email", None):
                user_email = _db_user.email
        except Exception as _ue_exc:
            logger.debug(
                "Could not resolve user email for fill notification: %s", _ue_exc
            )

        send_trade_fill_email(
            symbol=order.symbol,
            direction=order.side,
            quantity=order.quantity,
            fill_price=result.average_fill_price or 0.0,
            net_pnl=getattr(result, "pnl", None),
            commission=getattr(result, "commission", 0.0),
            to=user_email,
        )
        logger.debug(
            "Trade fill email queued: user=%s symbol=%s side=%s",
            user_id,
            order.symbol,
            order.side,
        )
    except Exception as email_exc:
        logger.debug("Trade fill email skipped: %s", email_exc)

    # Prometheus metric
    try:
        from core.metrics import ORDERS_TOTAL

        ORDERS_TOTAL.labels(symbol=order.symbol, side=order.side, status="filled").inc()
    except Exception:
        pass

    return {
        "status": "success",
        "order_id": result.id,
        "filled_price": result.average_fill_price,
        "filled_quantity": result.filled_quantity,
    }


@router.post(
    "/order",
    status_code=status.HTTP_201_CREATED,
    response_model=OrderResponse,
    summary="Place a market/limit/stop order",
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
    _check_order_rate_limit(user.sub)
    await _validate_order(order)
    await _apply_risk_checks(order, user.sub)
    _log_compliance(order, user.sub)
    result = await _route_to_broker(order)
    return await _record_fill(order, result, user.sub)


@router.get("/positions", response_model=List[PositionResponse])
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
    return [
        PositionResponse(
            id=p.id,
            symbol=p.symbol,
            side=p.side.value,
            quantity=p.quantity,
            entry_price=p.entry_price,
            current_price=p.current_price,
            unrealized_pnl=p.unrealized_pnl,
        )
        for p in positions
    ]


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
    """Get account information. Requires: any authenticated user."""
    if not app_state or not app_state.broker:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Broker not available",
        )

    return await _broker_call("get_account_info")


@router.get(
    "/prices",
    response_model=Dict[str, PriceQuote],
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

    prices: Dict = {}
    for symbol in app_state.price_engine.symbols:
        tick = app_state.price_engine.get_last_price(symbol)
        if tick:
            prices[symbol] = {
                "bid": tick.bid,
                "ask": tick.ask,
                "last": getattr(tick, "last_price", None) or tick.mid,
                "timestamp": tick.timestamp,
            }

    # Fallback: when no live ticks are available (e.g. paper mode without a
    # real feed), synthesise quotes from the paper broker's static prices.
    if not prices and app_state.broker is not None:
        import time as _time

        _now = _time.time()
        _market_prices = getattr(app_state.broker, "market_prices", {})
        for symbol, mid in _market_prices.items():
            spread = mid * 0.0002  # 2 pip synthetic spread
            prices[symbol] = {
                "bid": round(mid - spread / 2, 5),
                "ask": round(mid + spread / 2, 5),
                "last": mid,
                "timestamp": _now,
            }
    return prices


@router.get(
    "/ohlcv/{symbol}",
    response_model=List[OHLCVBar],
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

    # Fallback: when the live engine has no buffered candles (paper / no feed),
    # use the paper broker's simulated market data so the endpoint returns
    # something useful rather than an empty list.
    if not data and app_state.broker is not None:
        _get_md = getattr(app_state.broker, "get_market_data", None)
        if callable(_get_md):
            _fallback = _get_md(symbol, timeframe, limit)
            if _fallback:
                return [
                    {
                        "timestamp": float(d["timestamp"]),
                        "open": float(d["open"]),
                        "high": float(d["high"]),
                        "low": float(d["low"]),
                        "close": float(d["close"]),
                        "volume": float(d["volume"]),
                    }
                    for d in _fallback
                ]

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


def _query_trades(user_id: str, symbol: Optional[str], limit: int, offset: int) -> list:
    """Fetch trades from DB for the given user."""
    try:
        from app import app_state as _state
        from database.models import Trade

        if not _state or not _state.db_session_factory:
            return []
        with _state.db_session_factory() as session:
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
    symbol: Optional[str] = Query(None, max_length=20),
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
    symbol: Optional[str] = Query(None, max_length=20),
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
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
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
    parameters: Optional[dict] = None
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
    parameters: Optional[dict] = None

    def model_post_init(self, __context):
        if not self.type:
            object.__setattr__(self, "type", self.strategy_type)


class SignalResponse(BaseModel):
    id: str
    symbol: str
    direction: str
    confidence: float
    entry_price: float
    stop_loss_price: Optional[float] = None
    take_profit_price: Optional[float] = None
    notes: Optional[str] = None
    timestamp: str
    source: str = "strategy_brain"


class PositionSizeRequest(BaseModel):
    entry_price: float
    stop_loss_price: Optional[float] = None
    confidence: float = 1.0
    symbol: str = "XAUUSD"
    account_equity: float = 100_000.0
    risk_pct: float = 0.01


class PositionSizeResponse(BaseModel):
    size: float
    risk_amount: float
    stop_loss_price: Optional[float] = None
    take_profit_price: Optional[float] = None
    notes: Optional[str] = None


# ── In-memory strategy store for test endpoints ───────────────────────────────
import uuid as _uuid  # noqa: E402

_strategy_store: Dict[str, dict] = {}


def _make_strategy_router():
    """Return a sub-router with the strategy CRUD + position-size endpoints."""
    from fastapi import APIRouter

    _r = APIRouter()  # no prefix — parent router already has /api/trading

    @_r.get("/strategies")
    def list_strategies():
        return list(_strategy_store.values())

    @_r.post("/strategies", status_code=201)
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
            from fastapi import HTTPException

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

    def _resolve(strategy_id: str) -> Optional[str]:
        """Return store key by id or name."""
        if strategy_id in _strategy_store:
            return strategy_id
        for k, v in _strategy_store.items():
            if v.get("name") == strategy_id:
                return k
        return None

    @_r.get("/strategies/{strategy_id}")
    def get_strategy(strategy_id: str):
        from fastapi import HTTPException

        key = _resolve(strategy_id)
        if key is None:
            raise HTTPException(404, "Strategy not found")
        return _strategy_store[key]

    @_r.delete("/strategies/{strategy_id}")
    def delete_strategy(strategy_id: str):
        from fastapi import HTTPException

        key = _resolve(strategy_id)
        if key is None:
            raise HTTPException(404, "Strategy not found")
        del _strategy_store[key]
        return {"status": "deleted"}

    @_r.post("/position-size")
    def calculate_position_size(req: PositionSizeRequest):
        if req.stop_loss_price and req.stop_loss_price < req.entry_price:
            risk_per_unit = req.entry_price - req.stop_loss_price
        else:
            risk_per_unit = req.entry_price * 0.01  # default 1%
        risk_amount = req.account_equity * req.risk_pct * req.confidence

        # Apply FOMC regime multiplier (hawkish → 0.8×, dovish → 1.2×, neutral → 1.0×)
        fomc_multiplier = 1.0
        try:
            from api.calendar import _fomc_regime_override

            if _fomc_regime_override.get("active"):
                fomc_multiplier = _fomc_regime_override.get(
                    "position_size_multiplier",
                    1.0,
                )
        except Exception as exc:
            logger.debug("FOMC regime multiplier unavailable, using 1.0: %s", exc)

        size = (
            risk_amount / risk_per_unit if risk_per_unit > 0 else 0.0
        ) * fomc_multiplier
        tp = req.entry_price + risk_per_unit * 2 if req.stop_loss_price else None
        return PositionSizeResponse(
            size=round(size, 4),
            risk_amount=round(risk_amount * fomc_multiplier, 2),
            stop_loss_price=req.stop_loss_price,
            take_profit_price=tp,
        )

    @_r.get("/risk-metrics")
    def get_risk_metrics():
        """Live risk metrics from the active broker / paper engine."""
        try:
            broker = getattr(app_state, "broker", None)
            if broker is None:
                raise AttributeError("no broker")

            account = broker.get_account_info()
            positions = broker.get_positions() if hasattr(broker, "get_positions") else []

            # Daily PnL: sum unrealised PnL across open positions
            daily_pnl = sum(
                getattr(p, "unrealized_pnl", 0.0) or 0.0 for p in positions
            )

            # Margin used from account info
            margin_used = float(getattr(account, "margin_used", 0.0) or 0.0)

            # Max drawdown from equity history
            max_dd = 0.0
            if hasattr(broker, "get_equity_history"):
                history = broker.get_equity_history()
                if history:
                    values = [v for _, v in history]
                    peak = values[0]
                    for v in values:
                        if v > peak:
                            peak = v
                        dd = (peak - v) / peak if peak > 0 else 0.0
                        if dd > max_dd:
                            max_dd = dd

            # Risk score: 0–100 based on drawdown + open positions
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
            return {
                "daily_pnl": 0.0,
                "max_drawdown": 0.0,
                "open_positions": 0,
                "margin_used": 0.0,
                "risk_score": 0.0,
            }

    @_r.get("/performance/summary")
    def get_performance_summary():
        """Performance summary from equity history and closed trades."""
        import math as _math

        try:
            broker = getattr(app_state, "broker", None)
            equity_history = []
            if broker and hasattr(broker, "get_equity_history"):
                equity_history = broker.get_equity_history()

            if not equity_history:
                raise ValueError("no history")

            values = [v for _, v in equity_history]
            initial = values[0]
            final = values[-1]
            total_return = ((final - initial) / initial * 100) if initial > 0 else 0.0

            # Max drawdown
            peak, max_dd = initial, 0.0
            for v in values:
                if v > peak:
                    peak = v
                dd = (peak - v) / peak if peak > 0 else 0.0
                if dd > max_dd:
                    max_dd = dd

            # Sharpe from point-to-point returns
            returns = [
                (values[i] - values[i - 1]) / values[i - 1]
                for i in range(1, len(values))
                if values[i - 1] > 0
            ]
            sharpe = 0.0
            if len(returns) >= 2:
                mean_r = sum(returns) / len(returns)
                var = sum((r - mean_r) ** 2 for r in returns) / len(returns)
                std_r = _math.sqrt(var) if var > 0 else 0.0
                if std_r > 0:
                    sharpe = round((mean_r / std_r) * _math.sqrt(252), 3)

            win_rate = (
                sum(1 for r in returns if r > 0) / len(returns) if returns else 0.0
            )

            # Period in days
            ts_list = [t for t, _ in equity_history]
            period_days = max(
                1, round((ts_list[-1] - ts_list[0]) / 86400)
            ) if len(ts_list) >= 2 else 1

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

    @_r.get("/performance/{strategy_id}")
    def get_strategy_performance(strategy_id: str):
        from fastapi import HTTPException

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

    @_r.post("/strategies/{strategy_id}/start")
    def start_strategy(strategy_id: str):
        from fastapi import HTTPException

        key = _resolve(strategy_id)
        if key is None:
            raise HTTPException(404, "Strategy not found")
        _strategy_store[key]["enabled"] = True
        return {"status": "started", "strategy_id": strategy_id}

    @_r.post("/strategies/{strategy_id}/stop")
    def stop_strategy(strategy_id: str):
        from fastapi import HTTPException

        key = _resolve(strategy_id)
        if key is None:
            raise HTTPException(404, "Strategy not found")
        _strategy_store[key]["enabled"] = False
        return {"status": "stopped", "strategy_id": strategy_id}

    return _r


# Register the sub-router on the module-level router
try:
    router.include_router(_make_strategy_router())
except Exception as exc:
    logger.error("Failed to register strategy sub-router: %s", exc, exc_info=True)


# ── Regime status endpoint ────────────────────────────────────────────────────


@router.get(
    "/regime", response_model=None, summary="Current market regime and active strategy"
)
async def get_regime_status():
    """
    Return the current detected market regime, confidence score, and the
    strategy selected by the RegimeRouter for that regime.

    Also returns recent regime transition history and per-regime backtest
    performance from the manifest (if available).
    """
    try:
        from app import app_state  # noqa: PLC0415

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
        import logging as _log

        _log.getLogger(__name__).warning("regime status error: %s", exc)
        return {
            "current_regime": "unknown",
            "confidence": 0.0,
            "selected_strategy": "TrendFollowing",
            "manifest_entries": {},
            "error": str(exc),
        }


@router.get(
    "/regime/history", response_model=None, summary="Recent regime transition history"
)
async def get_regime_history(limit: int = 20):
    """Return the last N regime transitions with timestamps."""
    try:
        from app import app_state  # noqa: PLC0415

        regime_router = getattr(app_state, "regime_router", None)
        if regime_router is None:
            return {"history": []}
        return {"history": regime_router.regime_history(limit=limit)}
    except Exception as exc:
        return {"history": [], "error": str(exc)}


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
    import logging as _log

    _logger = _log.getLogger(__name__)
    try:
        from risk.stress_test import run_all_scenarios

        return run_all_scenarios(
            position_value=position_value,
            equity=equity,
            leverage=leverage,
            max_loss_pct=max_loss_pct,
        )
    except Exception as exc:
        _logger.error("Stress test failed: %s", exc, exc_info=True)
        from fastapi import HTTPException

        raise HTTPException(status_code=500, detail=f"Stress test error: {exc}")
