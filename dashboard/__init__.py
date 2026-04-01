# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
Phase 17: Web Dashboard UI Module

DashboardService delegates each _get_* method to real data sources when
wired (app_state/broker/orchestrator), falling back to empty structures
when not wired — same pattern as MobileAPI.
"""

from typing import Dict, List, Optional, Any  # noqa: F401
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
import logging

logger = logging.getLogger(__name__)


class DashboardWidgetType(Enum):
    PORTFOLIO_SUMMARY = "portfolio_summary"
    POSITION_LIST = "position_list"
    TRADE_HISTORY = "trade_history"
    PERFORMANCE_CHART = "performance_chart"
    STRATEGY_STATUS = "strategy_status"
    MARKET_OVERVIEW = "market_overview"
    ALERTS = "alerts"
    NEWS_FEED = "news_feed"
    RISK_METRICS = "risk_metrics"
    ORDER_BOOK = "order_book"


@dataclass
class DashboardWidget:
    widget_id: str
    widget_type: DashboardWidgetType
    title: str
    position: dict[str, int]
    settings: dict[str, Any] = field(default_factory=dict)
    refresh_interval: int = 5
    enabled: bool = True


@dataclass
class DashboardLayout:
    layout_id: str
    name: str
    widgets: list[DashboardWidget]
    created_at: datetime = field(default_factory=datetime.now)
    is_default: bool = False


class DashboardService:
    """
    Web Dashboard Service.

    Wire real data by passing:
      app_state   — object with .broker (get_account_info, get_positions,
                    get_trade_history, get_risk_metrics, get_order_book)
      orchestrator — MarketDataOrchestrator for live ticks, sentiment, quality
    """

    def __init__(
        self,
        config: dict[str, Any] | None = None,
        app_state: Any = None,
        orchestrator: Any = None,
    ):
        self.config = config or {}
        self._app_state = app_state
        self._orchestrator = orchestrator
        self.layouts: dict[str, DashboardLayout] = {}
        self.active_layout_id: str | None = None
        self._create_default_layout()
        logger.info("Dashboard service initialized")

    # ── Layout management ─────────────────────────────────────────────────────

    def _create_default_layout(self) -> None:
        default_widgets = [
            DashboardWidget(
                "portfolio_summary_1",
                DashboardWidgetType.PORTFOLIO_SUMMARY,
                "Portfolio Overview",
                {"row": 0, "col": 0, "width": 4, "height": 2},
            ),
            DashboardWidget(
                "positions_1",
                DashboardWidgetType.POSITION_LIST,
                "Open Positions",
                {"row": 0, "col": 4, "width": 4, "height": 2},
            ),
            DashboardWidget(
                "performance_1",
                DashboardWidgetType.PERFORMANCE_CHART,
                "Performance",
                {"row": 0, "col": 8, "width": 4, "height": 2},
            ),
            DashboardWidget(
                "strategy_1",
                DashboardWidgetType.STRATEGY_STATUS,
                "Active Strategies",
                {"row": 2, "col": 0, "width": 6, "height": 2},
            ),
            DashboardWidget(
                "risk_1",
                DashboardWidgetType.RISK_METRICS,
                "Risk Metrics",
                {"row": 2, "col": 6, "width": 6, "height": 2},
            ),
        ]
        layout = DashboardLayout("default", "Default Trading Dashboard", default_widgets, is_default=True)
        self.layouts["default"] = layout
        self.active_layout_id = "default"

    def get_layout(self, layout_id: str) -> DashboardLayout | None:
        return self.layouts.get(layout_id)

    def get_active_layout(self) -> DashboardLayout | None:
        if self.active_layout_id:
            return self.layouts.get(self.active_layout_id)
        return None

    def create_layout(self, name: str, widgets: list[DashboardWidget]) -> DashboardLayout:
        layout_id = f"layout_{len(self.layouts) + 1}"
        layout = DashboardLayout(layout_id=layout_id, name=name, widgets=widgets)
        self.layouts[layout_id] = layout
        logger.info("Created dashboard layout: %s", name)
        return layout

    def set_active_layout(self, layout_id: str) -> bool:
        if layout_id in self.layouts:
            self.active_layout_id = layout_id
            return True
        return False

    # ── Widget dispatch ───────────────────────────────────────────────────────

    def get_widget_data(self, widget_type: DashboardWidgetType) -> dict[str, Any]:
        handlers = {
            DashboardWidgetType.PORTFOLIO_SUMMARY: self._get_portfolio_summary,
            DashboardWidgetType.POSITION_LIST: self._get_positions,
            DashboardWidgetType.PERFORMANCE_CHART: self._get_performance_data,
            DashboardWidgetType.STRATEGY_STATUS: self._get_strategy_status,
            DashboardWidgetType.RISK_METRICS: self._get_risk_metrics,
            DashboardWidgetType.MARKET_OVERVIEW: self._get_market_overview,
            DashboardWidgetType.ALERTS: self._get_alerts,
            DashboardWidgetType.NEWS_FEED: self._get_news_feed,
            DashboardWidgetType.TRADE_HISTORY: self._get_trade_history,
            DashboardWidgetType.ORDER_BOOK: self._get_order_book,
        }
        handler = handlers.get(widget_type)
        return handler() if handler else {}

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _broker(self) -> Any:
        return getattr(self._app_state, "broker", None) if self._app_state else None

    def _safe_broker(self, method: str, *args: Any, **kwargs: Any) -> Any:
        broker = self._broker()
        if broker is None:
            return None
        fn = getattr(broker, method, None)
        if fn is None:
            return None
        try:
            return fn(*args, **kwargs)
        except Exception as exc:
            logger.warning("DashboardService broker.%s: %s", method, exc)
            return None

    def _safe_orch(self, method: str, *args: Any, **kwargs: Any) -> Any:
        if self._orchestrator is None:
            return None
        fn = getattr(self._orchestrator, method, None)
        if fn is None:
            return None
        try:
            return fn(*args, **kwargs)
        except Exception as exc:
            logger.warning("DashboardService orchestrator.%s: %s", method, exc)
            return None

    @staticmethod
    def _to_dict(obj: Any) -> dict[str, Any] | None:
        if obj is None:
            return None
        if hasattr(obj, "__dict__"):
            return obj.__dict__
        if isinstance(obj, dict):
            return obj
        return None

    # ── Data providers ────────────────────────────────────────────────────────

    def _get_portfolio_summary(self) -> dict[str, Any]:
        info = self._to_dict(self._safe_broker("get_account_info"))
        if info:
            balance = float(info.get("balance") or info.get("equity") or 0.0)
            equity = float(info.get("equity") or balance)
            margin_used = float(info.get("margin_used") or 0.0)
            return {
                "total_balance": equity,
                "available_balance": equity - margin_used,
                "margin_used": margin_used,
                "unrealized_pnl": float(info.get("unrealized_pnl") or 0.0),
                "daily_pnl": float(info.get("daily_pnl") or 0.0),
                "daily_pnl_percent": float(info.get("daily_pnl_pct") or 0.0),
                "open_positions": int(info.get("open_positions") or 0),
                "pending_orders": int(info.get("pending_orders") or 0),
                "data_source": "broker",
            }
        return {
            "total_balance": 0.0,
            "available_balance": 0.0,
            "margin_used": 0.0,
            "unrealized_pnl": 0.0,
            "daily_pnl": 0.0,
            "daily_pnl_percent": 0.0,
            "open_positions": 0,
            "pending_orders": 0,
            "data_source": "none",
        }

    def _get_positions(self) -> dict[str, Any]:
        raw = self._safe_broker("get_positions")
        if raw is not None:
            positions = [self._to_dict(p) for p in raw if self._to_dict(p) is not None]
            return {"positions": positions, "data_source": "broker"}
        return {"positions": [], "data_source": "none"}

    def _get_performance_data(self) -> dict[str, Any]:
        trades_raw = self._safe_broker("get_trade_history") or []
        equity_curve = []
        running = 0.0
        for t in trades_raw:
            d = self._to_dict(t)
            if d:
                pnl = float(d.get("pnl") or d.get("profit") or 0.0)
                running += pnl
                closed_at = d.get("closed_at") or d.get("close_time") or ""
                equity_curve.append({"date": str(closed_at)[:10], "equity": running})

        metrics: dict[str, Any] = {}
        risk_raw = self._to_dict(self._safe_broker("get_risk_metrics"))
        if risk_raw:
            metrics = {
                "total_return": risk_raw.get("total_return", 0.0),
                "sharpe_ratio": risk_raw.get("sharpe_ratio", 0.0),
                "max_drawdown": risk_raw.get("max_drawdown", 0.0),
                "win_rate": risk_raw.get("win_rate", 0.0),
            }

        return {
            "equity_curve": equity_curve,
            "metrics": metrics,
            "data_source": "broker" if trades_raw else "none",
        }

    def _get_strategy_status(self) -> dict[str, Any]:
        strategies_raw = None
        if self._app_state is not None:
            strategies_raw = getattr(self._app_state, "strategies", None)
            if strategies_raw is None:
                fn = getattr(self._app_state, "get_strategy_status", None)
                if fn:
                    try:
                        strategies_raw = fn()
                    except Exception as exc:
                        logger.warning("DashboardService get_strategy_status: %s", exc)
        if strategies_raw:
            items = strategies_raw if isinstance(strategies_raw, list) else [strategies_raw]
            strategies = [self._to_dict(s) for s in items if self._to_dict(s) is not None]
            return {"strategies": strategies, "data_source": "app_state"}
        return {"strategies": [], "data_source": "none"}

    def _get_risk_metrics(self) -> dict[str, Any]:
        raw = self._to_dict(self._safe_broker("get_risk_metrics"))
        if raw:
            return {**raw, "data_source": "broker"}

        quality = self._to_dict(self._safe_orch("get_quality_report"))
        if quality:
            return {
                "var_95": quality.get("var_95", 0.0),
                "expected_shortfall": quality.get("expected_shortfall", 0.0),
                "sharpe_ratio": quality.get("sharpe_ratio", 0.0),
                "sortino_ratio": quality.get("sortino_ratio", 0.0),
                "max_drawdown": quality.get("max_drawdown", 0.0),
                "current_drawdown": quality.get("current_drawdown", 0.0),
                "risk_utilization": quality.get("risk_utilization", 0.0),
                "data_source": "orchestrator",
            }

        return {
            "var_95": 0.0,
            "expected_shortfall": 0.0,
            "sharpe_ratio": 0.0,
            "sortino_ratio": 0.0,
            "max_drawdown": 0.0,
            "current_drawdown": 0.0,
            "risk_utilization": 0.0,
            "data_source": "none",
        }

    def _get_market_overview(self) -> dict[str, Any]:
        symbols = ["XAUUSD", "EURUSD", "BTCUSD"]
        markets = []

        tick = self._safe_orch("get_latest_tick")
        gold_price: float | None = None
        if tick is not None:
            gold_price = float(getattr(tick, "mid", None) or getattr(tick, "price", None) or 0.0) or None

        for sym in symbols:
            price: float | None = None
            source = "none"
            if sym == "XAUUSD" and gold_price is not None:
                price = gold_price
                source = "orchestrator"
            else:
                raw_quote = self._to_dict(self._safe_broker("get_quote", sym))
                if raw_quote:
                    price = float(raw_quote.get("mid") or raw_quote.get("last") or 0.0) or None
                    source = "broker" if price else "none"
            markets.append({"symbol": sym, "price": price, "change": None, "data_source": source})

        return {"markets": markets}

    def _get_alerts(self) -> dict[str, Any]:
        alerts_raw = None
        if self._app_state is not None:
            fn = getattr(self._app_state, "get_alerts", None)
            if fn:
                try:
                    alerts_raw = fn()
                except Exception as exc:
                    logger.warning("DashboardService get_alerts: %s", exc)
        if alerts_raw:
            items = alerts_raw if isinstance(alerts_raw, list) else [alerts_raw]
            alerts = [self._to_dict(a) for a in items if self._to_dict(a) is not None]
            return {"alerts": alerts, "data_source": "app_state"}
        return {"alerts": [], "data_source": "none"}

    def _get_news_feed(self) -> dict[str, Any]:
        sentiment_engine = None
        if self._orchestrator is not None:
            sentiment_engine = getattr(self._orchestrator, "_sentiment", None)

        if sentiment_engine is not None:
            fn = getattr(sentiment_engine, "get_recent_articles", None)
            if fn:
                try:
                    articles = fn() or []
                    news = []
                    for a in articles[:10]:
                        d = self._to_dict(a)
                        if d:
                            news.append(
                                {
                                    "title": d.get("title", ""),
                                    "source": d.get("source", ""),
                                    "time": str(d.get("published_at", ""))[:16],
                                    "sentiment": d.get("sentiment_score", 0.0),
                                }
                            )
                    return {"news": news, "data_source": "orchestrator"}
                except Exception as exc:
                    logger.warning("DashboardService get_news_feed: %s", exc)

        return {"news": [], "data_source": "none"}

    def _get_trade_history(self) -> dict[str, Any]:
        trades_raw = self._safe_broker("get_trade_history") or []
        trades = [self._to_dict(t) for t in trades_raw if self._to_dict(t) is not None]
        return {"trades": trades, "data_source": "broker" if trades else "none"}

    def _get_order_book(self) -> dict[str, Any]:
        raw = self._to_dict(self._safe_broker("get_order_book", "XAUUSD"))
        if raw:
            return {**raw, "data_source": "broker"}
        return {"bids": [], "asks": [], "data_source": "none"}


__all__ = [
    "DashboardLayout",
    "DashboardService",
    "DashboardWidget",
    "DashboardWidgetType",
]
