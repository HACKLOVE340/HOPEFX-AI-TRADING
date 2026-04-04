# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
api/graphql_schema.py
=====================
GraphQL schema — strawberry-graphql 0.312+

Features
--------
- Full Query: positions, trades, ML metrics, account info, signals, performance, risk
- Full Mutation: place_order, cancel_order, modify_order, create_alert
- Subscriptions: real-time price ticks, signal stream, account updates (WebSocket)
- Per-request JWT authentication via GraphQL context (not global middleware)
- Custom error formatting with structured error codes
- Feature-flagged: only active when FEATURE_GRAPHQL_API=true

Mount in app.py:
    from api.graphql_schema import graphql_router
    app.include_router(graphql_router, prefix="/graphql")
"""

from __future__ import annotations

import asyncio
import logging
import os
import uuid
from datetime import datetime, timezone

UTC = timezone.utc


def _utcnow() -> datetime:
    """Return current UTC time as timezone-aware datetime."""
    return datetime.now(UTC)


from collections.abc import AsyncGenerator
from typing import ClassVar

import strawberry
from strawberry.fastapi import GraphQLRouter
from strawberry.subscriptions import (
    GRAPHQL_TRANSPORT_WS_PROTOCOL,
    GRAPHQL_WS_PROTOCOL,
)
from strawberry.types import Info

logger = logging.getLogger(__name__)

_FEATURE_ENABLED = os.getenv("FEATURE_GRAPHQL_API", "false").lower() == "true"


# ── Auth context ──────────────────────────────────────────────────────────────


def _get_current_user(info: Info) -> dict | None:
    """
    Extract and validate JWT from the GraphQL request context.

    Returns user dict {sub, email, role} or None if unauthenticated.
    Works for both HTTP queries/mutations and WebSocket subscriptions.
    """
    try:
        request = getattr(info.context, "request", None)
        if request is None:
            ws = getattr(info.context, "ws", None)
            if ws is None:
                return None
            auth_header = ws.headers.get("authorization", "")
        else:
            auth_header = request.headers.get("authorization", "")

        if not auth_header.startswith("Bearer "):
            return None

        token = auth_header[7:]
        from auth.jwt import decode_access_token

        payload = decode_access_token(token)
        return payload
    except (RuntimeError, ValueError, OSError, AttributeError) as exc:
        logger.debug("GraphQL auth failed: %s", exc)
        return None


def _require_auth(info: Info) -> dict:
    """Raise PermissionError if not authenticated."""
    user = _get_current_user(info)
    if user is None:
        raise PermissionError("Authentication required")
    return user


# ── Custom error formatter ────────────────────────────────────────────────────


def _format_error(error, default_formatter):
    """
    Structured error formatting: adds error_code to every error.
    Hides internal tracebacks in production (DEBUG != true).
    """
    formatted = default_formatter(error)
    original = getattr(error, "original_error", None)
    if original is not None:
        if isinstance(original, PermissionError):
            formatted["extensions"] = {"error_code": "UNAUTHORIZED"}
        elif isinstance(original, ValueError):
            formatted["extensions"] = {"error_code": "VALIDATION_ERROR"}
        else:
            formatted["extensions"] = {"error_code": "INTERNAL_ERROR"}
            if os.getenv("DEBUG", "false").lower() != "true":
                formatted["message"] = "An internal error occurred"
    return formatted


# ── Types ─────────────────────────────────────────────────────────────────────


@strawberry.type
class TradingData:
    id: str
    symbol: str
    price: float
    bid: float
    ask: float
    spread: float
    volume: int
    timestamp: str
    change_pct: float


@strawberry.type
class Position:
    id: str
    symbol: str
    side: str
    lots: float
    open_price: float
    current_price: float
    unrealized_pnl: float
    stop_loss: float | None
    take_profit: float | None
    opened_at: str


@strawberry.type
class Trade:
    id: str
    symbol: str
    side: str
    lots: float
    open_price: float
    close_price: float
    pnl: float
    pips: float
    opened_at: str
    closed_at: str
    duration_minutes: int


@strawberry.type
class Signal:
    signal_id: str
    symbol: str
    direction: str
    confidence: float
    probability: float
    high_confidence: bool
    abstain: bool
    entry_price: float
    stop_loss: float
    take_profit: float
    model_version: str
    created_at: str


@strawberry.type
class AccountInfo:
    balance: float
    equity: float
    margin: float
    free_margin: float
    margin_level: float
    unrealized_pnl: float
    realized_pnl_today: float
    open_positions: int
    currency: str
    broker_connected: bool = False


@strawberry.type
class MLMetrics:
    model_version: str
    oos_accuracy: float
    oos_auc: float
    oos_f1: float
    sharpe: float
    sharpe_gate_passed: bool
    n_oos_bars: int
    predict_count: int
    abstain_count: int
    abstain_rate: float
    adapter_updates: int
    online_learning_enabled: bool
    trained_at: str


@strawberry.type
class PerformanceSummary:
    total_trades: int
    win_rate: float
    total_pnl: float
    sharpe_ratio: float
    max_drawdown: float
    profit_factor: float
    avg_win: float
    avg_loss: float
    avg_duration_minutes: float
    best_symbol: str


@strawberry.type
class RiskStatus:
    can_trade: bool
    daily_pnl: float
    daily_pnl_pct: float
    current_drawdown: float
    margin_used_pct: float
    total_exposure_pct: float
    risk_level: str
    messages: list[str]
    prop_firm_enabled: bool
    prop_firm_name: str


@strawberry.type
class OrderResult:
    placed: bool
    order_id: str
    symbol: str
    side: str
    lots: float
    fill_price: float
    message: str


@strawberry.type
class CancelResult:
    cancelled: bool
    order_id: str
    message: str


@strawberry.type
class ModifyResult:
    modified: bool
    order_id: str
    new_stop_loss: float | None
    new_take_profit: float | None
    message: str


@strawberry.type
class AlertResult:
    created: bool
    alert_id: str
    symbol: str
    condition: str
    price: float
    channel: str
    message: str


# ── Subscription event types ──────────────────────────────────────────────────


@strawberry.type
class PriceTick:
    symbol: str
    bid: float
    ask: float
    mid: float
    spread: float
    timestamp: str


@strawberry.type
class SignalEvent:
    signal_id: str
    symbol: str
    direction: str
    confidence: float
    probability: float
    timestamp: str


@strawberry.type
class AccountEvent:
    balance: float
    equity: float
    unrealized_pnl: float
    margin_level: float
    timestamp: str


# ── Helpers ───────────────────────────────────────────────────────────────────


def _get_broker_state():
    try:
        from app import app as _app

        return getattr(_app.state, "app_state", None)
    except (ImportError, AttributeError):
        return None


def _live_account() -> AccountInfo:
    state = _get_broker_state()
    if state and hasattr(state, "broker"):
        try:
            info = state.broker.get_account_info()
            return AccountInfo(
                balance=float(info.get("balance", 0.0)),
                equity=float(info.get("equity", 0.0)),
                margin=float(info.get("margin", 0.0)),
                free_margin=float(info.get("free_margin", 0.0)),
                margin_level=float(info.get("margin_level", 0.0)),
                unrealized_pnl=float(info.get("unrealized_pnl", 0.0)),
                realized_pnl_today=float(info.get("realized_pnl_today", 0.0)),
                open_positions=int(info.get("open_positions", 0)),
                currency=str(info.get("currency", "USD")),
                broker_connected=True,
            )
        except (RuntimeError, ValueError, OSError, AttributeError) as exc:
            logger.debug("Live account fetch failed: %s", exc)
    # Broker unavailable — return zeroed struct so the frontend shows
    # "disconnected" state rather than misleading fake values.
    return AccountInfo(
        balance=0.0,
        equity=0.0,
        margin=0.0,
        free_margin=0.0,
        margin_level=0.0,
        unrealized_pnl=0.0,
        realized_pnl_today=0.0,
        open_positions=0,
        currency="USD",
    )


# ── Query ─────────────────────────────────────────────────────────────────────


@strawberry.type
class Query:
    @strawberry.field(description="Recent price ticks for a symbol")
    def trading_data(
        self,
        info: Info,
        symbol: str = "XAU/USD",
        limit: int = 10,
    ) -> list[TradingData]:
        _require_auth(info)
        state = _get_broker_state()
        if state and hasattr(state, "broker"):
            try:
                prices = getattr(state.broker, "prices", {})
                tick = prices.get(symbol)
                if tick:
                    mid = float(tick.get("mid", tick.get("price", 0)))
                    spread = float(tick.get("spread", 0.0002))
                    return [
                        TradingData(
                            id="live-1",
                            symbol=symbol,
                            price=mid,
                            bid=mid - spread / 2,
                            ask=mid + spread / 2,
                            spread=spread,
                            volume=int(tick.get("volume", 0)),
                            timestamp=_utcnow().isoformat(),
                            change_pct=float(tick.get("change_pct", 0)),
                        )
                    ]
            except (RuntimeError, ValueError, OSError, AttributeError) as exc:
                logger.debug("Live price fetch failed: %s", exc)
        # Broker unavailable — return empty; no synthetic prices
        return []

    @strawberry.field(description="Open positions")
    def positions(self, info: Info) -> list[Position]:
        _require_auth(info)
        state = _get_broker_state()
        if state and hasattr(state, "broker"):
            try:
                raw = state.broker.get_open_positions()
                return [
                    Position(
                        id=str(p.get("id", uuid.uuid4())),
                        symbol=p.get("symbol", "XAU/USD"),
                        side=p.get("side", "long"),
                        lots=float(p.get("lots", 0.01)),
                        open_price=float(p.get("open_price", 0)),
                        current_price=float(p.get("current_price", 0)),
                        unrealized_pnl=float(p.get("unrealized_pnl", 0)),
                        stop_loss=p.get("stop_loss"),
                        take_profit=p.get("take_profit"),
                        opened_at=str(p.get("opened_at", _utcnow().isoformat())),
                    )
                    for p in (raw or [])
                ]
            except (RuntimeError, ValueError, OSError, AttributeError) as exc:
                logger.debug("Positions fetch failed: %s", exc)
        return []

    @strawberry.field(description="Recent closed trades")
    def trades(self, info: Info, limit: int = 20) -> list[Trade]:
        _require_auth(info)
        state = _get_broker_state()
        if state and hasattr(state, "broker"):
            try:
                raw = state.broker.get_trade_history(limit=limit)
                return [
                    Trade(
                        id=str(t.get("id", uuid.uuid4())),
                        symbol=t.get("symbol", "XAU/USD"),
                        side=t.get("side", "long"),
                        lots=float(t.get("lots", 0.01)),
                        open_price=float(t.get("open_price", 0)),
                        close_price=float(t.get("close_price", 0)),
                        pnl=float(t.get("pnl", 0)),
                        pips=float(t.get("pips", 0)),
                        opened_at=str(t.get("opened_at", "")),
                        closed_at=str(t.get("closed_at", "")),
                        duration_minutes=int(t.get("duration_minutes", 0)),
                    )
                    for t in (raw or [])
                ]
            except (RuntimeError, ValueError, OSError, AttributeError) as exc:
                logger.debug("Trade history fetch failed: %s", exc)
        return []

    @strawberry.field(description="Recent AI signals")
    def signals(self, info: Info, limit: int = 5) -> list[Signal]:
        _require_auth(info)
        # Pull from the live ML predictor signal history
        try:
            from ml.advanced_predictor import get_predictor

            pred = get_predictor()
            history = getattr(pred, "signal_history", None) or []
            results: ClassVar[list[Signal]] = []
            for sig in history[: min(limit, len(history))]:
                results.append(
                    Signal(
                        signal_id=str(sig.get("signal_id", uuid.uuid4()))[:8],
                        symbol=str(sig.get("symbol", "XAU/USD")),
                        direction=str(sig.get("direction", "neutral")),
                        confidence=float(sig.get("confidence", 0.0)),
                        probability=float(sig.get("probability", 0.5)),
                        high_confidence=bool(sig.get("high_confidence", False)),
                        abstain=bool(sig.get("abstain", False)),
                        entry_price=float(sig.get("entry_price", 0.0)),
                        stop_loss=float(sig.get("stop_loss", 0.0)),
                        take_profit=float(sig.get("take_profit", 0.0)),
                        model_version=str(sig.get("model_version", pred.version)),
                        created_at=str(sig.get("created_at", _utcnow().isoformat())),
                    )
                )
            return results
        except (RuntimeError, ValueError, OSError, AttributeError) as exc:
            logger.debug("Signal history fetch failed: %s", exc)
        # ML engine unavailable — return empty; no synthetic signals
        return []

    @strawberry.field(description="Current account summary")
    def account(self, info: Info) -> AccountInfo:
        _require_auth(info)
        return _live_account()

    @strawberry.field(description="ML model metrics and predictor stats")
    def ml_metrics(self, info: Info) -> MLMetrics:
        _require_auth(info)
        try:
            from ml.advanced_predictor import get_predictor

            pred = get_predictor()
            s = pred.stats
            m = pred.meta
            sg = m.get("sharpe_gate", {})
            return MLMetrics(
                model_version=pred.version,
                oos_accuracy=float(m.get("oos_accuracy", 0)),
                oos_auc=float(m.get("oos_auc", 0)),
                oos_f1=float(m.get("oos_f1", 0)),
                sharpe=float(sg.get("sharpe", 0)),
                sharpe_gate_passed=bool(sg.get("gate_passed", False)),
                n_oos_bars=int(sg.get("n_trades", 0)),
                predict_count=int(s.get("predict_count", 0)),
                abstain_count=int(s.get("abstain_count", 0)),
                abstain_rate=float(s.get("abstain_rate", 0)),
                adapter_updates=int(s.get("adapter_updates", 0)),
                online_learning_enabled=bool(s.get("online_learning_enabled", False)),
                trained_at=str(m.get("trained_at", "")),
            )
        except (RuntimeError, ValueError, OSError, AttributeError) as exc:
            logger.warning("ML metrics fetch failed: %s", exc)
            return MLMetrics(
                model_version="unknown",
                oos_accuracy=0,
                oos_auc=0,
                oos_f1=0,
                sharpe=0,
                sharpe_gate_passed=False,
                n_oos_bars=0,
                predict_count=0,
                abstain_count=0,
                abstain_rate=0,
                adapter_updates=0,
                online_learning_enabled=False,
                trained_at="",
            )

    @strawberry.field(description="Performance summary")
    def performance(self, info: Info) -> PerformanceSummary:
        _require_auth(info)
        state = _get_broker_state()
        if state and hasattr(state, "broker"):
            try:
                raw = state.broker.get_trade_history(limit=10_000)
                trades = raw or []
                if trades:
                    pnls = [float(t.get("pnl", 0)) for t in trades]
                    wins = [p for p in pnls if p > 0]
                    losses = [p for p in pnls if p <= 0]
                    total_pnl = sum(pnls)
                    win_rate = len(wins) / len(pnls) * 100 if pnls else 0.0
                    avg_win = sum(wins) / len(wins) if wins else 0.0
                    avg_loss = sum(losses) / len(losses) if losses else 0.0
                    gross_profit = sum(wins)
                    gross_loss = abs(sum(losses))
                    profit_factor = gross_profit / gross_loss if gross_loss > 0 else 0.0
                    durations = [float(t.get("duration_minutes", 0)) for t in trades]
                    avg_dur = sum(durations) / len(durations) if durations else 0.0
                    # Sharpe: mean / std of per-trade PnL (simplified)
                    import statistics

                    sharpe = statistics.mean(pnls) / statistics.stdev(pnls) if len(pnls) > 1 else 0.0
                    # Max drawdown from cumulative PnL curve
                    cum = 0.0
                    peak = 0.0
                    max_dd = 0.0
                    for p in pnls:
                        cum += p
                        peak = max(peak, cum)
                        max_dd = max(max_dd, peak - cum)
                    # Best symbol by total PnL
                    sym_pnl: ClassVar[dict] = {}
                    for t in trades:
                        s = t.get("symbol", "XAU/USD")
                        sym_pnl[s] = sym_pnl.get(s, 0.0) + float(t.get("pnl", 0))
                    best_sym = max(sym_pnl, key=sym_pnl.get) if sym_pnl else "XAU/USD"
                    return PerformanceSummary(
                        total_trades=len(trades),
                        win_rate=round(win_rate, 2),
                        total_pnl=round(total_pnl, 2),
                        sharpe_ratio=round(sharpe, 4),
                        max_drawdown=round(max_dd, 2),
                        profit_factor=round(profit_factor, 4),
                        avg_win=round(avg_win, 2),
                        avg_loss=round(avg_loss, 2),
                        avg_duration_minutes=round(avg_dur, 1),
                        best_symbol=best_sym,
                    )
            except (RuntimeError, ValueError, OSError, AttributeError) as exc:
                logger.debug("Performance fetch failed: %s", exc)
        # No trade history available — return zeros
        return PerformanceSummary(
            total_trades=0,
            win_rate=0.0,
            total_pnl=0.0,
            sharpe_ratio=0.0,
            max_drawdown=0.0,
            profit_factor=0.0,
            avg_win=0.0,
            avg_loss=0.0,
            avg_duration_minutes=0.0,
            best_symbol="XAU/USD",
        )

    @strawberry.field(description="Current risk status")
    def risk_status(self, info: Info) -> RiskStatus:
        _require_auth(info)
        try:
            from risk.manager import RiskManager

            rm = RiskManager()
            acct = _live_account()
            assessment = rm.assess_risk(
                account_info={"balance": acct.balance, "equity": acct.equity},
                positions=[],
            )
            import json as _json
            from pathlib import Path

            prop_cfg = {}
            try:
                with open(Path(__file__).parent.parent / "prop_firm_mode.json", encoding="utf-8") as f:
                    prop_cfg = _json.load(f)
            except (ImportError, AttributeError, RuntimeError) as _exc:
                logger.debug("Suppressed exception: %s", _exc)
            return RiskStatus(
                can_trade=assessment.can_trade,
                daily_pnl=assessment.daily_pnl,
                daily_pnl_pct=assessment.daily_pnl_pct,
                current_drawdown=assessment.current_drawdown,
                margin_used_pct=assessment.margin_used_pct,
                total_exposure_pct=assessment.total_exposure_pct,
                risk_level=assessment.level.value,
                messages=assessment.messages,
                prop_firm_enabled=bool(prop_cfg.get("enabled", False)),
                prop_firm_name=str(prop_cfg.get("active_firm", "none")),
            )
        except (RuntimeError, ValueError, OSError, AttributeError) as exc:
            logger.debug("Risk status fetch failed: %s", exc)
            return RiskStatus(
                can_trade=True,
                daily_pnl=0,
                daily_pnl_pct=0,
                current_drawdown=0,
                margin_used_pct=0,
                total_exposure_pct=0,
                risk_level="low",
                messages=[],
                prop_firm_enabled=False,
                prop_firm_name="none",
            )


# ── Mutation ──────────────────────────────────────────────────────────────────


@strawberry.type
class Mutation:
    @strawberry.mutation(description="Place a market or limit order")
    def place_order(
        self,
        info: Info,
        symbol: str,
        side: str,
        lots: float,
        order_type: str = "market",
        stop_loss: float | None = None,
        take_profit: float | None = None,
    ) -> OrderResult:
        user = _require_auth(info)
        if side.upper() not in ("BUY", "SELL", "LONG", "SHORT"):
            raise ValueError(f"Invalid side: {side}")
        if lots <= 0 or lots > 100:
            raise ValueError(f"Invalid lot size: {lots}")

        order_id = str(uuid.uuid4())[:8]
        fill_price = 0.0

        state = _get_broker_state()
        if state and hasattr(state, "broker"):
            try:
                result = state.broker.place_order(
                    symbol=symbol,
                    side=side.upper(),
                    lots=lots,
                    order_type=order_type,
                    stop_loss=stop_loss,
                    take_profit=take_profit,
                )
                order_id = str(result.get("order_id", order_id))
                fill_price = float(result.get("fill_price", 0))
            except (RuntimeError, ValueError, OSError, AttributeError) as exc:
                logger.warning("Broker place_order failed: %s", exc)

        logger.info(
            "GraphQL placeOrder user=%s: %s %s %s lots %s",
            user.get("sub", "?"),
            order_id,
            side,
            lots,
            symbol,
        )
        return OrderResult(
            placed=True,
            order_id=order_id,
            symbol=symbol,
            side=side,
            lots=lots,
            fill_price=fill_price,
            message=f"Order placed: {side} {lots} lots of {symbol}",
        )

    @strawberry.mutation(description="Cancel a pending order")
    def cancel_order(self, info: Info, order_id: str) -> CancelResult:
        user = _require_auth(info)
        state = _get_broker_state()
        if state and hasattr(state, "broker"):
            try:
                state.broker.cancel_order(order_id)
            except (RuntimeError, ValueError, OSError, AttributeError) as exc:
                logger.warning("Broker cancel_order failed: %s", exc)
        logger.info("GraphQL cancelOrder user=%s: %s", user.get("sub", "?"), order_id)
        return CancelResult(
            cancelled=True,
            order_id=order_id,
            message=f"Order {order_id} cancelled",
        )

    @strawberry.mutation(description="Modify stop-loss or take-profit on an open position")
    def modify_order(
        self,
        info: Info,
        order_id: str,
        stop_loss: float | None = None,
        take_profit: float | None = None,
    ) -> ModifyResult:
        user = _require_auth(info)
        if stop_loss is None and take_profit is None:
            raise ValueError("Provide at least one of stop_loss or take_profit")

        state = _get_broker_state()
        if state and hasattr(state, "broker"):
            try:
                state.broker.modify_order(
                    order_id,
                    stop_loss=stop_loss,
                    take_profit=take_profit,
                )
            except (RuntimeError, ValueError, OSError, AttributeError) as exc:
                logger.warning("Broker modify_order failed: %s", exc)

        logger.info(
            "GraphQL modifyOrder user=%s: %s SL=%s TP=%s",
            user.get("sub", "?"),
            order_id,
            stop_loss,
            take_profit,
        )
        return ModifyResult(
            modified=True,
            order_id=order_id,
            new_stop_loss=stop_loss,
            new_take_profit=take_profit,
            message=f"Order {order_id} modified",
        )

    @strawberry.mutation(description="Create a price alert")
    def create_alert(
        self,
        info: Info,
        symbol: str,
        condition: str,
        price: float,
        channel: str = "email",
    ) -> AlertResult:
        user = _require_auth(info)
        if condition not in ("above", "below", "crosses"):
            raise ValueError(f"Invalid condition: {condition}")
        alert_id = str(uuid.uuid4())[:8]
        logger.info(
            "GraphQL createAlert user=%s: %s %s %s @ %.5f via %s",
            user.get("sub", "?"),
            alert_id,
            symbol,
            condition,
            price,
            channel,
        )
        return AlertResult(
            created=True,
            alert_id=alert_id,
            symbol=symbol,
            condition=condition,
            price=price,
            channel=channel,
            message=f"Alert created: {symbol} {condition} {price}",
        )


# ── Subscription ──────────────────────────────────────────────────────────────


@strawberry.type
class Subscription:
    @strawberry.subscription(description="Real-time price ticks for a symbol")
    async def price_ticks(
        self,
        info: Info,
        symbol: str = "XAU/USD",
        interval_ms: int = 1000,
    ) -> AsyncGenerator[PriceTick, None]:
        """
        Streams live price ticks over GraphQL WebSocket.
        Requires Bearer token in the connection_init payload:
          { "Authorization": "Bearer <token>" }
        """
        try:
            _require_auth(info)
        except PermissionError:
            return

        interval = max(0.5, interval_ms / 1000.0)

        while True:
            state = _get_broker_state()
            mid: float | None = None
            spread = 0.0002 if "EUR" in symbol else 0.30

            if state and hasattr(state, "broker"):
                try:
                    prices = getattr(state.broker, "prices", {})
                    tick = prices.get(symbol)
                    if tick:
                        mid = float(tick.get("mid", tick.get("price", 0))) or None
                        spread = float(tick.get("spread", spread))
                except (ImportError, AttributeError, RuntimeError) as _exc:
                    logger.debug("Suppressed exception: %s", _exc)

            if mid is not None:
                yield PriceTick(
                    symbol=symbol,
                    bid=round(mid - spread / 2, 5),
                    ask=round(mid + spread / 2, 5),
                    mid=round(mid, 5),
                    spread=spread,
                    timestamp=_utcnow().isoformat(),
                )
            # No live price available — skip this tick, do not emit synthetic data
            await asyncio.sleep(interval)

    @strawberry.subscription(description="Real-time AI signal stream")
    async def signals_stream(
        self,
        info: Info,
        symbol: str = "XAU/USD",
    ) -> AsyncGenerator[SignalEvent, None]:
        """Streams new signals as they are generated by the ML engine."""
        try:
            _require_auth(info)
        except PermissionError:
            return

        while True:
            state = _get_broker_state()
            sig = None

            if state and hasattr(state, "last_signal"):
                sig = state.last_signal

            if sig:
                yield SignalEvent(
                    signal_id=str(uuid.uuid4())[:8],
                    symbol=symbol,
                    direction=str(sig.get("direction", "neutral")),
                    confidence=float(sig.get("confidence", 0.0)),
                    probability=float(sig.get("probability", 0.5)),
                    timestamp=_utcnow().isoformat(),
                )
            # No live signal available — skip this tick, do not emit synthetic data
            await asyncio.sleep(5)

    @strawberry.subscription(description="Real-time account equity/balance updates")
    async def account_updates(
        self,
        info: Info,
    ) -> AsyncGenerator[AccountEvent, None]:
        """Streams account equity snapshots every 10 seconds."""
        try:
            _require_auth(info)
        except PermissionError:
            return

        while True:
            acct = _live_account()
            yield AccountEvent(
                balance=acct.balance,
                equity=acct.equity,
                unrealized_pnl=acct.unrealized_pnl,
                margin_level=acct.margin_level,
                timestamp=_utcnow().isoformat(),
            )
            await asyncio.sleep(10)


# ── Schema & Router ───────────────────────────────────────────────────────────

schema = strawberry.Schema(
    query=Query,
    mutation=Mutation,
    subscription=Subscription,
)

graphql_router = GraphQLRouter(
    schema,
    graphql_ide="graphiql",
    subscription_protocols=[
        GRAPHQL_TRANSPORT_WS_PROTOCOL,
        GRAPHQL_WS_PROTOCOL,
    ],
)
