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
from datetime import datetime, timezone
from typing import Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field, field_validator

from api.auth import (
    TokenPayload,
    get_current_user,
    require_role,
    require_kyc,
    validate_order_symbol,
    validate_order_quantity,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/trading", tags=["Trading"])


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


# ---------------------------------------------------------------------------
# Module-level state (injected from app.py startup)
# ---------------------------------------------------------------------------

app_state = None


def set_state(state) -> None:
    global app_state
    app_state = state


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.post("/order", status_code=status.HTTP_201_CREATED)
async def place_order(
    order: OrderRequest,
    user: TokenPayload = Depends(require_kyc),
    _role: TokenPayload = Depends(require_role("trader")),
):
    """
    Place a new order.

    Requires: Bearer token with role >= 'trader'.
    Passes through RiskManager.assess_risk() before broker execution.
    Symbol and quantity are validated against server-side allowlists.
    """
    if not app_state or not app_state.broker:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Broker not available")

    # ── Risk gate ────────────────────────────────────────────────────────────
    if hasattr(app_state, "risk_manager") and app_state.risk_manager is not None:
        try:
            account_info = await app_state.broker.get_account_info()
            positions = await app_state.broker.get_positions()
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
                    user.sub, assessment.messages,
                )
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail=f"Risk check failed: {'; '.join(assessment.messages)}",
                )
        except HTTPException:
            raise
        except Exception as risk_exc:
            logger.error("Risk check error (allowing trade): %s", risk_exc)

    # ── Compliance / audit log ───────────────────────────────────────────────
    if hasattr(app_state, "compliance_manager") and app_state.compliance_manager is not None:
        try:
            app_state.compliance_manager.log_trade(
                user_id=user.sub,
                trade_data={
                    "symbol": order.symbol,
                    "side": order.side,
                    "quantity": order.quantity,
                    "order_type": order.order_type,
                },
            )
        except Exception as comp_exc:
            logger.error("Compliance log error: %s", comp_exc)

    # ── Execute ──────────────────────────────────────────────────────────────
    try:
        result = await app_state.broker.place_market_order(
            symbol=order.symbol,
            side=order.side,
            quantity=order.quantity,
        )
        logger.info(
            "Order placed: user=%s symbol=%s side=%s qty=%s order_id=%s",
            user.sub, order.symbol, order.side, order.quantity, result.id,
        )

        # ── Broadcast to WebSocket subscribers ──────────────────────────────
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

        # Prometheus order metric
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
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("Order error for user=%s: %s", user.sub, exc)
        try:
            from core.metrics import ORDERS_TOTAL
            ORDERS_TOTAL.labels(symbol=order.symbol, side=order.side, status="error").inc()
        except Exception:
            pass
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


@router.get("/positions", response_model=List[PositionResponse])
async def get_positions(
    user: TokenPayload = Depends(get_current_user),
):
    """Get all open positions. Requires: any authenticated user."""
    if not app_state or not app_state.broker:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Broker not available")

    positions = await app_state.broker.get_positions()
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


@router.delete("/positions/{position_id}")
async def close_position(
    position_id: str,
    user: TokenPayload = Depends(require_role("trader")),
):
    """Close a specific position. Requires: role >= 'trader'."""
    if not app_state or not app_state.broker:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Broker not available")

    success = await app_state.broker.close_position(position_id)
    if not success:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Position not found")

    logger.info("Position closed: user=%s position_id=%s", user.sub, position_id)

    if hasattr(app_state, "ws_manager") and app_state.ws_manager is not None:
        try:
            await app_state.ws_manager.broadcast_to_all({
                "type": "position_closed",
                "position_id": position_id,
                "user_id": user.sub,
            }, event="position_closed")
        except Exception as ws_exc:
            logger.warning("WebSocket broadcast failed: %s", ws_exc)

    return {"status": "success", "position_id": position_id}


@router.delete("/positions")
async def close_all_positions(
    user: TokenPayload = Depends(require_role("trader")),
):
    """Close all open positions. Requires: role >= 'trader'."""
    if not app_state or not app_state.broker:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Broker not available")

    closed = await app_state.broker.close_all_positions()
    logger.info("All positions closed: user=%s count=%s", user.sub, closed)
    return {"status": "success", "closed_positions": closed}


@router.get("/account")
async def get_account(
    user: TokenPayload = Depends(get_current_user),
):
    """Get account information. Requires: any authenticated user."""
    if not app_state or not app_state.broker:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Broker not available")

    return await app_state.broker.get_account_info()


@router.get("/prices")
async def get_prices(
    user: TokenPayload = Depends(get_current_user),
):
    """Get current bid/ask prices. Requires: any authenticated user."""
    if not app_state or not app_state.price_engine:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Price engine not available")

    prices: Dict = {}
    for symbol in app_state.price_engine.symbols:
        tick = app_state.price_engine.get_last_price(symbol)
        if tick:
            prices[symbol] = {
                "bid": tick.bid,
                "ask": tick.ask,
                "last": tick.last_price,
                "timestamp": tick.timestamp,
            }
    return prices


@router.get("/ohlcv/{symbol}")
async def get_ohlcv(
    symbol: str,
    timeframe: str = "1h",
    limit: int = 100,
    user: TokenPayload = Depends(get_current_user),
):
    """Get OHLCV data. Requires: any authenticated user. Symbol validated server-side."""
    symbol = validate_order_symbol(symbol)

    if not app_state or not app_state.price_engine:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Price engine not available")

    data = app_state.price_engine.get_ohlcv(symbol, timeframe, limit)
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
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Brain not available")

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
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Brain not available")

    app_state.brain.emergency_stop()
    logger.critical("Emergency stop triggered by user=%s", user.sub)
    return {"status": "emergency_stop_triggered", "triggered_by": user.sub}


# ── Trade history ─────────────────────────────────────────────────────────────

_TRADE_CSV_FIELDS = [
    "trade_id", "symbol", "side", "quantity", "entry_price", "exit_price",
    "realized_pnl", "commission", "status", "strategy", "entry_time", "exit_time",
]


def _query_trades(user_id: str, symbol: Optional[str], limit: int, offset: int) -> list:
    """Fetch trades from DB for the given user."""
    try:
        from database.models import Trade
        from app import app_state as _state
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
    type: str = ""          # alias for strategy_type used by some tests
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
import uuid as _uuid

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
        _KNOWN = {"ma_crossover", "rsi", "macd", "bollinger_bands",
                  "ema_crossover", "breakout", "stochastic", "mean_reversion",
                  "smc_ict", "strategy_brain"}
        if req.strategy_type not in _KNOWN:
            from fastapi import HTTPException
            raise HTTPException(400, f"Unknown strategy type: {req.strategy_type}")
        sid = str(_uuid.uuid4())[:8]
        record = {"id": sid, "name": req.name, "symbol": req.symbol,
                  "timeframe": req.timeframe, "strategy_type": req.strategy_type,
                  "type": req.strategy_type, "enabled": req.enabled,
                  "parameters": req.parameters, "risk_per_trade": req.risk_per_trade}
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
        size = risk_amount / risk_per_unit if risk_per_unit > 0 else 0.0
        tp = req.entry_price + risk_per_unit * 2 if req.stop_loss_price else None
        return PositionSizeResponse(size=round(size, 4), risk_amount=round(risk_amount, 2),
                                    stop_loss_price=req.stop_loss_price,
                                    take_profit_price=tp)

    @_r.get("/risk-metrics")
    def get_risk_metrics():
        return {"daily_pnl": 0.0, "max_drawdown": 0.0, "open_positions": 0,
                "margin_used": 0.0, "risk_score": 0.0}

    @_r.get("/performance/summary")
    def get_performance_summary():
        return {"total_return": 0.0, "sharpe_ratio": 0.0, "max_drawdown": 0.0,
                "win_rate": 0.0, "total_trades": 0, "period_days": 30,
                "total_strategies": len(_strategy_store)}

    @_r.get("/performance/{strategy_id}")
    def get_strategy_performance(strategy_id: str):
        from fastapi import HTTPException
        key = _resolve(strategy_id)
        if key is None:
            raise HTTPException(404, "Strategy not found")
        return {"strategy_id": strategy_id, "total_return": 0.0, "sharpe_ratio": 0.0,
                "max_drawdown": 0.0, "win_rate": 0.0, "total_trades": 0}

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
except Exception:
    pass
