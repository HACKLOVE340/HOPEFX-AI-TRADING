"""
Phase 17: Web Dashboard UI Module

Provides the backend API and components for the web dashboard interface.
This module powers the React/Vue frontend with real-time data.
"""

from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
import logging

logger = logging.getLogger(__name__)


class DashboardWidgetType(Enum):
    """Dashboard widget types"""
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
    """Dashboard widget configuration"""
    widget_id: str
    widget_type: DashboardWidgetType
    title: str
    position: Dict[str, int]  # {row, col, width, height}
    settings: Dict[str, Any] = field(default_factory=dict)
    refresh_interval: int = 5  # seconds
    enabled: bool = True


@dataclass
class DashboardLayout:
    """Dashboard layout configuration"""
    layout_id: str
    name: str
    widgets: List[DashboardWidget]
    created_at: datetime = field(default_factory=datetime.now)
    is_default: bool = False


class DashboardService:
    """
    Web Dashboard Service
    
    Provides data and configuration for the web dashboard interface.
    """
    
    def __init__(self, config: Optional[Dict[str, Any]] = None):
        """Initialize dashboard service."""
        self.config = config or {}
        self.layouts: Dict[str, DashboardLayout] = {}
        self.active_layout_id: Optional[str] = None
        
        # Initialize default layout
        self._create_default_layout()
        
        logger.info("Dashboard service initialized")
    
    def _create_default_layout(self):
        """Create default dashboard layout."""
        default_widgets = [
            DashboardWidget(
                widget_id="portfolio_summary_1",
                widget_type=DashboardWidgetType.PORTFOLIO_SUMMARY,
                title="Portfolio Overview",
                position={"row": 0, "col": 0, "width": 4, "height": 2}
            ),
            DashboardWidget(
                widget_id="positions_1",
                widget_type=DashboardWidgetType.POSITION_LIST,
                title="Open Positions",
                position={"row": 0, "col": 4, "width": 4, "height": 2}
            ),
            DashboardWidget(
                widget_id="performance_1",
                widget_type=DashboardWidgetType.PERFORMANCE_CHART,
                title="Performance",
                position={"row": 0, "col": 8, "width": 4, "height": 2}
            ),
            DashboardWidget(
                widget_id="strategy_1",
                widget_type=DashboardWidgetType.STRATEGY_STATUS,
                title="Active Strategies",
                position={"row": 2, "col": 0, "width": 6, "height": 2}
            ),
            DashboardWidget(
                widget_id="risk_1",
                widget_type=DashboardWidgetType.RISK_METRICS,
                title="Risk Metrics",
                position={"row": 2, "col": 6, "width": 6, "height": 2}
            ),
        ]
        
        default_layout = DashboardLayout(
            layout_id="default",
            name="Default Trading Dashboard",
            widgets=default_widgets,
            is_default=True
        )
        
        self.layouts["default"] = default_layout
        self.active_layout_id = "default"
    
    def get_layout(self, layout_id: str) -> Optional[DashboardLayout]:
        """Get a dashboard layout by ID."""
        return self.layouts.get(layout_id)
    
    def get_active_layout(self) -> Optional[DashboardLayout]:
        """Get the currently active layout."""
        if self.active_layout_id:
            return self.layouts.get(self.active_layout_id)
        return None
    
    def create_layout(self, name: str, widgets: List[DashboardWidget]) -> DashboardLayout:
        """Create a new dashboard layout."""
        layout_id = f"layout_{len(self.layouts) + 1}"
        layout = DashboardLayout(
            layout_id=layout_id,
            name=name,
            widgets=widgets
        )
        self.layouts[layout_id] = layout
        logger.info(f"Created dashboard layout: {name}")
        return layout
    
    def set_active_layout(self, layout_id: str) -> bool:
        """Set the active dashboard layout."""
        if layout_id in self.layouts:
            self.active_layout_id = layout_id
            logger.info(f"Active layout set to: {layout_id}")
            return True
        return False
    
    def get_widget_data(self, widget_type: DashboardWidgetType) -> Dict[str, Any]:
        """Get data for a specific widget type."""
        data_handlers = {
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
        
        handler = data_handlers.get(widget_type)
        if handler:
            return handler()
        return {}
    
    def _get_portfolio_summary(self) -> Dict[str, Any]:
        """Get portfolio summary data."""
        return {
            "total_balance": 100000.00,
            "available_balance": 75000.00,
            "margin_used": 25000.00,
            "unrealized_pnl": 1250.50,
            "daily_pnl": 450.25,
            "daily_pnl_percent": 0.45,
            "open_positions": 3,
            "pending_orders": 2,
        }
    
    def _get_positions(self) -> Dict[str, Any]:
        """Get open positions data."""
        return {
            "positions": [
                {
                    "id": "pos_1",
                    "symbol": "XAUUSD",
                    "side": "BUY",
                    "size": 0.5,
                    "entry_price": 1950.00,
                    "current_price": 1955.00,
                    "pnl": 250.00,
                    "pnl_percent": 0.26,
                },
                {
                    "id": "pos_2",
                    "symbol": "EURUSD",
                    "side": "SELL",
                    "size": 1.0,
                    "entry_price": 1.0850,
                    "current_price": 1.0845,
                    "pnl": 50.00,
                    "pnl_percent": 0.05,
                },
            ]
        }
    
    def _get_performance_data(self) -> Dict[str, Any]:
        """Get performance chart data."""
        return {
            "equity_curve": [
                {"date": "2024-01-01", "equity": 100000},
                {"date": "2024-01-02", "equity": 100250},
                {"date": "2024-01-03", "equity": 100150},
                {"date": "2024-01-04", "equity": 100500},
                {"date": "2024-01-05", "equity": 101000},
            ],
            "metrics": {
                "total_return": 1.0,
                "sharpe_ratio": 1.5,
                "max_drawdown": -2.5,
                "win_rate": 65.0,
            }
        }
    
    def _get_strategy_status(self) -> Dict[str, Any]:
        """Get strategy status data."""
        return {
            "strategies": [
                {
                    "name": "MA_Crossover",
                    "status": "RUNNING",
                    "signals": 15,
                    "win_rate": 68.5,
                    "pnl": 1500.00,
                },
                {
                    "name": "RSI_Strategy",
                    "status": "RUNNING",
                    "signals": 8,
                    "win_rate": 62.0,
                    "pnl": 800.00,
                },
            ]
        }
    
    def _get_risk_metrics(self) -> Dict[str, Any]:
        """Get risk metrics data."""
        return {
            "var_95": -2500.00,
            "expected_shortfall": -3500.00,
            "sharpe_ratio": 1.5,
            "sortino_ratio": 2.1,
            "max_drawdown": -5.2,
            "current_drawdown": -1.5,
            "risk_utilization": 45.0,
        }
    
    def _get_market_overview(self) -> Dict[str, Any]:
        """Get market overview data. Prices are fetched via /api/trading/market-price/{symbol}."""
        return {
            "markets": [
                {"symbol": "XAUUSD", "price": None, "change": None, "source": "/api/trading/market-price/XAUUSD"},
                {"symbol": "EURUSD", "price": None, "change": None, "source": "/api/trading/market-price/EURUSD"},
                {"symbol": "BTCUSD", "price": None, "change": None, "source": "/api/trading/market-price/BTCUSD"},
            ],
            "note": "Live prices are served via /api/trading/market-price/{symbol} (yfinance)",
        }
    
    def _get_alerts(self) -> Dict[str, Any]:
        """Get alerts data."""
        return {
            "alerts": [
                {"id": 1, "type": "INFO", "message": "Strategy started", "time": "10:30"},
                {"id": 2, "type": "WARNING", "message": "High volatility detected", "time": "11:15"},
            ]
        }
    
    def _get_news_feed(self) -> Dict[str, Any]:
        """Get news feed data."""
        return {
            "news": [
                {"title": "Fed announces rate decision", "source": "Reuters", "time": "12:00"},
                {"title": "Gold prices surge on dollar weakness", "source": "Bloomberg", "time": "11:30"},
            ]
        }
    
    def _get_trade_history(self) -> Dict[str, Any]:
        """Get trade history data."""
        return {
            "trades": [
                {"id": 1, "symbol": "XAUUSD", "side": "BUY", "pnl": 150.00, "time": "09:30"},
                {"id": 2, "symbol": "EURUSD", "side": "SELL", "pnl": -50.00, "time": "10:15"},
            ]
        }
    
    def _get_order_book(self) -> Dict[str, Any]:
        """Get order book data."""
        return {
            "bids": [
                {"price": 1954.50, "size": 10.5},
                {"price": 1954.00, "size": 25.0},
            ],
            "asks": [
                {"price": 1955.50, "size": 8.0},
                {"price": 1956.00, "size": 15.5},
            ]
        }


# Module exports
__all__ = [
    'DashboardService',
    'DashboardWidget',
    'DashboardLayout',
    'DashboardWidgetType',
]
