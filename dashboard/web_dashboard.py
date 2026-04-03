# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
HOPEFX Real-Time Web Dashboard
Professional trading dashboard with WebSocket updates
"""

import asyncio
import json
import logging
from collections import deque
from datetime import UTC, datetime
from typing import Any

try:
    import aiohttp_jinja2
    import jinja2
    from aiohttp import WSMsgType, web

    AIOHTTP_AVAILABLE = True
except ImportError:
    AIOHTTP_AVAILABLE = False

try:
    import plotly  # type: ignore[import]
    PLOTLY_AVAILABLE = True
except ImportError:
    PLOTLY_AVAILABLE = False

logger = logging.getLogger(__name__)


class DashboardWebSocketManager:
    """
    Manages WebSocket connections for real-time dashboard updates
    """

    def __init__(self):
        self.clients: set[web.WebSocketResponse] = set()
        self._lock = asyncio.Lock()
        self._running = False
        self._broadcast_task: asyncio.Task | None = None

    async def register(self, ws: web.WebSocketResponse):
        """Register new client"""
        async with self._lock:
            self.clients.add(ws)
            logger.info("Dashboard client connected. Total: %s", len(self.clients))


    async def unregister(self, ws: web.WebSocketResponse):
        """Unregister client"""
        async with self._lock:
            self.clients.discard(ws)
            logger.info("Dashboard client disconnected. Total: %s", len(self.clients))


    async def broadcast(self, message: dict):
        """Broadcast message to all clients"""
        if not self.clients:
            return

        message_str = json.dumps(message, default=str)
        disconnected = []

        async with self._lock:
            for ws in self.clients:
                try:
                    ws.send_str(message_str)
                except Exception:
                    disconnected.append(ws)

            # Remove disconnected clients
            for ws in disconnected:
                self.clients.discard(ws)

    async def start_broadcasting(self, data_source, interval: float = 1.0):
        """Start periodic data broadcasting"""
        self._running = True

        while self._running:
            try:
                # Get latest data
                data = await data_source.get_dashboard_data()
                await self.broadcast(
                    {
                        "type": "update",
                        "timestamp": datetime.now(UTC).isoformat(),
                        "data": data,
                    }
                )

                await asyncio.sleep(interval)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("Broadcast error: %s", e)

                await asyncio.sleep(5)

    def stop(self):
        """Stop broadcasting"""
        self._running = False


class DashboardDataSource:
    """
    Provides data for dashboard from trading system
    """

    def __init__(self, trading_app):
        self.app = trading_app
        self._price_history: dict[str, deque] = {
            symbol: deque(maxlen=100) for symbol in getattr(trading_app, "symbols", ["EURUSD", "XAUUSD"])
        }
        self._trade_history: deque = deque(maxlen=50)
        self._performance_metrics: dict[str, Any] = {}

    async def get_dashboard_data(self) -> dict:
        """Compile all dashboard data"""
        try:
            # Account info
            account = {}
            if self.app.broker:
                try:
                    account = await self.app.broker.get_account_info()
                except Exception as e:
                    logger.error("Error getting account: %s", e)


            # Positions
            positions = []
            if self.app.broker:
                try:
                    positions = await self.app.broker.get_positions()
                    positions = [
                        p.to_dict()
                        if hasattr(p, "to_dict")
                        else {
                            "id": getattr(p, "id", "unknown"),
                            "symbol": getattr(p, "symbol", "unknown"),
                            "side": getattr(p, "side", "unknown"),
                            "quantity": getattr(p, "quantity", 0),
                            "entry_price": getattr(p, "entry_price", 0),
                            "current_price": getattr(p, "current_price", 0),
                            "unrealized_pnl": getattr(p, "unrealized_pnl", 0),
                        }
                        for p in positions
                    ]
                except Exception as e:
                    logger.error("Error getting positions: %s", e)


            # Brain state
            brain_state = {}
            if self.app.brain:
                try:
                    state = self.app.brain.get_state()
                    brain_state = {
                        "system_state": state.system_state.value
                        if hasattr(state.system_state, "value")
                        else str(state.system_state),
                        "equity": state.equity,
                        "open_trades": state.open_trades_count,
                        "daily_pnl": state.daily_pnl,
                        "market_regime": {
                            k: v.value if hasattr(v, "value") else str(v) for k, v in state.market_regime.items()
                        },
                    }
                except Exception as e:
                    logger.error("Error getting brain state: %s", e)


            # Price data
            price_data = {}
            if self.app.price_engine:
                for symbol in self.app.price_engine.symbols[:5]:  # Limit to 5
                    tick = self.app.price_engine.get_last_price(symbol)
                    if tick:
                        price_data[symbol] = {
                            "bid": tick.bid,
                            "ask": tick.ask,
                            "spread": tick.spread,
                            "timestamp": tick.timestamp,
                        }

            # Recent signals
            recent_signals = []
            if self.app.brain:
                recent_signals = self.app.brain.get_decision_history(10)

            return {
                "account": account,
                "positions": positions,
                "brain_state": brain_state,
                "prices": price_data,
                "recent_signals": recent_signals,
                "timestamp": datetime.now(UTC).isoformat(),
            }

        except Exception as e:
            logger.error("Error compiling dashboard data: %s", e)

            return {"error": str(e)}

    def record_trade(self, trade: dict):
        """Record trade for history"""
        self._trade_history.append({**trade, "timestamp": datetime.now(UTC).isoformat()})


def create_dashboard_app(trading_app, host: str = "0.0.0.0", port: int = 8081):  # nosec B104 - host configurable via parameter
    """Create and configure dashboard web application"""
    if not AIOHTTP_AVAILABLE:
        logger.error("aiohttp required for dashboard")
        return None

    app = web.Application()

    # Setup Jinja2 templates
    template_loader = jinja2.PackageLoader("dashboard", "templates")
    aiohttp_jinja2.setup(app, loader=template_loader)

    # WebSocket manager
    ws_manager = DashboardWebSocketManager()
    data_source = DashboardDataSource(trading_app)

    # Store in app
    app["trading_app"] = trading_app
    app["ws_manager"] = ws_manager
    app["data_source"] = data_source

    # Routes
    app.router.add_get("/", index_handler)
    app.router.add_get("/ws", websocket_handler)
    app.router.add_get("/api/data", api_data_handler)
    app.router.add_get("/api/chart/{symbol}", chart_data_handler)
    app.router.add_static("/static", path="dashboard/static", name="static")

    # Start background broadcasting
    async def on_startup(app):
        app["broadcast_task"] = asyncio.create_task(ws_manager.start_broadcasting(data_source, interval=1.0))

    async def on_cleanup(app):
        ws_manager.stop()
        if "broadcast_task" in app:
            app["broadcast_task"].cancel()

    app.on_startup.append(on_startup)
    app.on_cleanup.append(on_cleanup)

    return app, host, port



_DASHBOARD_TEMPLATE = Path(__file__).parent / "templates" / "dashboard.html"


async def index_handler(request):
    """Main dashboard page — serves the pre-built HTML template."""
    try:
        html_content = _DASHBOARD_TEMPLATE.read_text(encoding="utf-8")
    except FileNotFoundError:
        logger.error("Dashboard template not found: %s", _DASHBOARD_TEMPLATE)
        html_content = "<h1>Dashboard template missing — please redeploy.</h1>"
    except OSError as exc:
        logger.error("Failed to read dashboard template: %s", exc)
        html_content = "<h1>Dashboard temporarily unavailable.</h1>"
    return web.Response(text=html_content, content_type="text/html")


async def websocket_handler(request):
    """WebSocket endpoint for real-time updates"""
    ws = web.WebSocketResponse()
    await ws.prepare(request)

    ws_manager = request.app["ws_manager"]
    await ws_manager.register(ws)

    try:
        async for msg in ws:
            if msg.type == WSMsgType.TEXT:
                # Handle client messages if needed
                data = json.loads(msg.data)
                if data.get("action") == "ping":
                    await ws.send_str(json.dumps({"type": "pong"}))
            elif msg.type == WSMsgType.ERROR:
                logger.error("WebSocket error: %s", ws.exception())

    finally:
        await ws_manager.unregister(ws)

    return ws


async def api_data_handler(request):
    """REST API for dashboard data"""
    data_source = request.app["data_source"]
    data = await data_source.get_dashboard_data()
    return web.json_response(data)


async def chart_data_handler(request):
    """Get historical chart data"""
    symbol = request.match_info["symbol"]
    # Return historical data for charting
    return web.json_response(
        {
            "symbol": symbol,
            "data": [],  # Would fetch from database
        }
    )


async def start_dashboard(trading_app, host: str = "0.0.0.0", port: int = 8081):  # nosec B104 - host configurable via parameter
    """Start dashboard server"""
    app, host, port = create_dashboard_app(trading_app, host, port)

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, host, port)
    await site.start()

    logger.info("🎛️ Dashboard started at http://%s:%s", host, port)

    return runner
