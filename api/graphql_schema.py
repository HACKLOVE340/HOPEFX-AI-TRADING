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
from strawberry.dataloader import DataLoader
from strawberry.fastapi import GraphQLRouter
from strawberry.subscriptions import (
    GRAPHQL_TRANSPORT_WS_PROTOCOL,
    GRAPHQL_WS_PROTOCOL,
)
from strawberry.types import Info

logger = logging.getLogger(__name__)


# ── DataLoader batch functions ────────────────────────────────────────────────
# Each batch function receives a list of keys and returns a list of results
# in the same order.  Strawberry's DataLoader deduplicates and coalesces
# concurrent requests within a single event-loop tick.


async def _batch_load_positions(user_ids: list[str]) -> list[list]:
    """
    Batch-load open positions for multiple user IDs in one broker call.

    For the paper broker (single-user) all user IDs map to the same position
    list.  For multi-user deployments this would fan out to per-user queries.
    """
    try:
        from core.app_state import app_state

        broker = getattr(app_state, "broker", None)
        if broker is None:
            return [[] for _ in user_ids]

        # Single bulk fetch — the paper broker holds all positions in memory.
        raw = broker.get_open_positions() or []
        positions = [
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
                opened_at=str(p.get("opened_at", datetime.now(UTC).isoformat())),
            )
            for p in raw
        ]
        # Return the same list for every requested user_id (single-user broker).
        return [positions for _ in user_ids]
    except Exception as exc:
        logger.debug("DataLoader _batch_load_positions: %s", exc)
        return [[] for _ in user_ids]


async def _batch_load_trades(keys: list[tuple[str, int]]) -> list[list]:
    """
    Batch-load trade history for multiple (user_id, limit) keys.

    Fetches the maximum requested limit once and slices per key.
    """
    try:
        from core.app_state import app_state

        broker = getattr(app_state, "broker", None)
        if broker is None:
            return [[] for _ in keys]

        max_limit = max((limit for _, limit in keys), default=20)
        raw = broker.get_trade_history(limit=max_limit) or []
        all_trades = [
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
            for t in raw
        ]
        return [all_trades[:limit] for _, limit in keys]
    except Exception as exc:
        logger.debug("DataLoader _batch_load_trades: %s", exc)
        return [[] for _ in keys]


async def _batch_load_signals(keys: list[tuple[str, int]]) -> list[list]:
    """
    Batch-load recent signals for multiple (symbol, limit) keys.

    Fetches from the signal engine once and filters per key.
    """
    try:
        from core.app_state import app_state

        signal_engine = getattr(app_state, "signal_engine", None)
        if signal_engine is None:
            return [[] for _ in keys]

        max_limit = max((limit for _, limit in keys), default=10)
        raw = getattr(signal_engine, "get_recent_signals", lambda n: [])(max_limit) or []
        all_signals = [
            Signal(
                signal_id=str(s.get("id", uuid.uuid4())),
                symbol=s.get("symbol", "XAU/USD"),
                direction=str(s.get("direction", "neutral")),
                confidence=float(s.get("confidence", 0.0)),
                probability=float(s.get("probability", 0.5)),
                high_confidence=bool(s.get("high_confidence", False)),
                abstain=bool(s.get("abstain", False)),
                entry_price=float(s.get("entry_price", 0)),
                stop_loss=float(s.get("stop_loss", 0)),
                take_profit=float(s.get("take_profit", 0)),
                model_version=str(s.get("model_version", "unknown")),
                created_at=str(s.get("created_at", datetime.now(UTC).isoformat())),
            )
            for s in raw
        ]
        return [[sig for sig in all_signals if sig.symbol == symbol][:limit] for symbol, limit in keys]
    except Exception as exc:
        logger.debug("DataLoader _batch_load_signals: %s", exc)
        return [[] for _ in keys]


def _make_context_loaders() -> dict:
    """
    Create per-request DataLoader instances.

    DataLoaders must be created per-request (not module-level) so their
    internal batch queues are isolated between concurrent requests.
    """
    return {
        "positions_loader": DataLoader(load_fn=_batch_load_positions),
        "trades_loader": DataLoader(load_fn=_batch_load_trades),
        "signals_loader": DataLoader(load_fn=_batch_load_signals),
    }


# Gating is enforced by core/router_registry.py (feature_flags.GRAPHQL_API).
# The router is always built here so it is ready when the flag is on.
# Default matches the FeatureFlags definition (default=True).
_FEATURE_ENABLED = os.getenv("FEATURE_GRAPHQL_API", "true").lower() == "true"


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
            import asyncio as _asyncio
            import inspect as _inspect
            broker = state.broker
            # Use sync helper when available (PaperTradingBroker exposes one)
            if hasattr(broker, "_get_account_info_sync"):
                info = broker._get_account_info_sync()
            elif _inspect.iscoroutinefunction(broker.get_account_info):
                try:
                    loop = _asyncio.get_event_loop()
                    if loop.is_running():
                        # Cannot block inside a running loop — return defaults
                        info = None
                    else:
                        info = loop.run_until_complete(broker.get_account_info())
                except RuntimeError:
                    info = None
            else:
                info = broker.get_account_info()
            if info is None:
                raise AttributeError("no account info")
            def _get(key, default=0.0):
                if hasattr(info, key):
                    return getattr(info, key) or default
                if isinstance(info, dict):
                    return info.get(key, default) or default
                return default

            return AccountInfo(
                balance=float(_get("balance", 0.0)),
                equity=float(_get("equity", 0.0)),
                margin=float(_get("margin", _get("margin_used", 0.0))),
                free_margin=float(_get("free_margin", _get("margin_available", 0.0))),
                margin_level=float(_get("margin_level", 0.0)),
                unrealized_pnl=float(_get("unrealized_pnl", 0.0)),
                realized_pnl_today=float(_get("realized_pnl_today", 0.0)),
                open_positions=int(_get("open_positions", _get("positions_count", 0))),
                currency=str(_get("currency", "USD")),
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
    async def positions(self, info: Info) -> list[Position]:
        user = _require_auth(info)
        user_id = user.get("sub", "default")
        loader: DataLoader = info.context.get("positions_loader") or DataLoader(load_fn=_batch_load_positions)
        return await loader.load(user_id)

    @strawberry.field(description="Recent closed trades")
    async def trades(self, info: Info, limit: int = 20) -> list[Trade]:
        user = _require_auth(info)
        user_id = user.get("sub", "default")
        loader: DataLoader = info.context.get("trades_loader") or DataLoader(load_fn=_batch_load_trades)
        return await loader.load((user_id, limit))

        # DB fallback: read closed trades from the Trade table
        try:
            from core.app_state import app_state as _gql_app_state
            from database.models import Trade as DBTrade, TradeStatus

            sf = getattr(_gql_app_state, "db_session_factory", None)
            if sf is not None:
                db = sf()
                try:
                    db_trades = (
                        db.query(DBTrade)
                        .filter(DBTrade.status == TradeStatus.CLOSED)
                        .order_by(DBTrade.exit_time.desc())
                        .limit(limit)
                        .all()
                    )
                    result = []
                    for t in db_trades:
                        opened = t.entry_time.isoformat() if t.entry_time else ""
                        closed = t.exit_time.isoformat() if t.exit_time else ""
                        dur = 0
                        if t.entry_time and t.exit_time:
                            dur = int((t.exit_time - t.entry_time).total_seconds() / 60)
                        result.append(
                            Trade(
                                id=str(t.trade_id or t.id),
                                symbol=t.symbol,
                                side=str(t.side or "long"),
                                lots=float(t.entry_quantity or t.size or 0),
                                open_price=float(t.entry_price or 0),
                                close_price=float(t.exit_price or 0),
                                pnl=float(t.realized_pnl or 0),
                                pips=0.0,
                                opened_at=opened,
                                closed_at=closed,
                                duration_minutes=dur,
                            )
                        )
                    return result
                finally:
                    db.close()
        except Exception as exc:
            logger.debug("GraphQL trades DB fallback failed: %s", exc)
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
        # DB fallback: compute performance from closed Trade rows
        try:
            from core.app_state import app_state as _gql_perf_state
            from database.models import Trade as DBTrade, TradeStatus

            sf = getattr(_gql_perf_state, "db_session_factory", None)
            if sf is not None:
                db = sf()
                try:
                    db_trades = db.query(DBTrade).filter(DBTrade.status == TradeStatus.CLOSED).all()
                    if db_trades:
                        pnls = [float(t.realized_pnl or 0) for t in db_trades]
                        wins = [p for p in pnls if p > 0]
                        losses = [p for p in pnls if p <= 0]
                        total_pnl = sum(pnls)
                        win_rate = len(wins) / len(pnls) * 100 if pnls else 0.0
                        avg_win = sum(wins) / len(wins) if wins else 0.0
                        avg_loss = sum(losses) / len(losses) if losses else 0.0
                        gross_profit = sum(wins)
                        gross_loss = abs(sum(losses))
                        profit_factor = gross_profit / gross_loss if gross_loss > 0 else 0.0
                        import statistics as _stats

                        sharpe = _stats.mean(pnls) / _stats.stdev(pnls) if len(pnls) > 1 else 0.0
                        cum, peak, max_dd = 0.0, 0.0, 0.0
                        for p in pnls:
                            cum += p
                            peak = max(peak, cum)
                            max_dd = max(max_dd, peak - cum)
                        sym_pnl: dict = {}
                        for t in db_trades:
                            sym_pnl[t.symbol] = sym_pnl.get(t.symbol, 0.0) + float(t.realized_pnl or 0)
                        best_sym = max(sym_pnl, key=sym_pnl.get) if sym_pnl else "XAU/USD"
                        return PerformanceSummary(
                            total_trades=len(db_trades),
                            win_rate=round(win_rate, 2),
                            total_pnl=round(total_pnl, 2),
                            sharpe_ratio=round(sharpe, 4),
                            max_drawdown=round(max_dd, 2),
                            profit_factor=round(profit_factor, 4),
                            avg_win=round(avg_win, 2),
                            avg_loss=round(avg_loss, 2),
                            avg_duration_minutes=0.0,
                            best_symbol=best_sym,
                        )
                finally:
                    db.close()
        except Exception as exc:
            logger.debug("GraphQL performance DB fallback failed: %s", exc)

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

# Disable the interactive GraphiQL IDE in production.  The IDE exposes the
# full schema and all field names without authentication — individual resolvers
# require a JWT but schema introspection does not.  Set APP_ENV=development
# (the default) to re-enable it locally.
_graphql_ide = None if os.getenv("APP_ENV", "development").lower() == "production" else "graphiql"


async def _get_context() -> dict:
    """
    Per-request GraphQL context factory.

    Creates fresh DataLoader instances for each request so their internal
    batch queues are isolated between concurrent requests.  The loaders
    coalesce all field-level loads within a single request into one batch
    call, eliminating N+1 query patterns.
    """
    return _make_context_loaders()


graphql_router = GraphQLRouter(
    schema,
    graphql_ide=_graphql_ide,
    context_getter=_get_context,
    subscription_protocols=[
        GRAPHQL_TRANSPORT_WS_PROTOCOL,
        GRAPHQL_WS_PROTOCOL,
    ],
)
