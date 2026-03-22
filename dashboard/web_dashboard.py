"""
HOPEFX Real-Time Web Dashboard
Professional trading dashboard with WebSocket updates
"""

import asyncio
import json
import logging
from typing import Dict, List, Optional, Any, Set
from dataclasses import dataclass, asdict
from datetime import datetime
from collections import deque
import random

try:
    from aiohttp import web, WSMsgType
    import aiohttp_jinja2
    import jinja2
    AIOHTTP_AVAILABLE = True
except ImportError:
    AIOHTTP_AVAILABLE = False

try:
    import plotly
    import plotly.graph_objs as go
    PLOTLY_AVAILABLE = True
except ImportError:
    PLOTLY_AVAILABLE = False

logger = logging.getLogger(__name__)


class DashboardWebSocketManager:
    """
    Manages WebSocket connections for real-time dashboard updates
    """
    
    def __init__(self):
        self.clients: Set[web.WebSocketResponse] = set()
        self._lock = asyncio.Lock()
        self._running = False
        self._broadcast_task: Optional[asyncio.Task] = None
    
    async def register(self, ws: web.WebSocketResponse):
        """Register new client"""
        async with self._lock:
            self.clients.add(ws)
            logger.info(f"Dashboard client connected. Total: {len(self.clients)}")
    
    async def unregister(self, ws: web.WebSocketResponse):
        """Unregister client"""
        async with self._lock:
            self.clients.discard(ws)
            logger.info(f"Dashboard client disconnected. Total: {len(self.clients)}")
    
    async def broadcast(self, message: Dict):
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
                await self.broadcast({
                    'type': 'update',
                    'timestamp': datetime.now().isoformat(),
                    'data': data
                })
                
                await asyncio.sleep(interval)
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Broadcast error: {e}")
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
        self._price_history: Dict[str, deque] = {
            symbol: deque(maxlen=100) 
            for symbol in getattr(trading_app, 'symbols', ['EURUSD', 'XAUUSD'])
        }
        self._trade_history: deque = deque(maxlen=50)
        self._performance_metrics: Dict[str, Any] = {}
    
    async def get_dashboard_data(self) -> Dict:
        """Compile all dashboard data"""
        try:
            # Account info
            account = {}
            if self.app.broker:
                try:
                    account = await self.app.broker.get_account_info()
                except Exception as e:
                    logger.error(f"Error getting account: {e}")
            
            # Positions
            positions = []
            if self.app.broker:
                try:
                    positions = await self.app.broker.get_positions()
                    positions = [p.to_dict() if hasattr(p, 'to_dict') else {
                        'id': getattr(p, 'id', 'unknown'),
                        'symbol': getattr(p, 'symbol', 'unknown'),
                        'side': getattr(p, 'side', 'unknown'),
                        'quantity': getattr(p, 'quantity', 0),
                        'entry_price': getattr(p, 'entry_price', 0),
                        'current_price': getattr(p, 'current_price', 0),
                        'unrealized_pnl': getattr(p, 'unrealized_pnl', 0)
                    } for p in positions]
                except Exception as e:
                    logger.error(f"Error getting positions: {e}")
            
            # Brain state
            brain_state = {}
            if self.app.brain:
                try:
                    state = self.app.brain.get_state()
                    brain_state = {
                        'system_state': state.system_state.value if hasattr(state.system_state, 'value') else str(state.system_state),
                        'equity': state.equity,
                        'open_trades': state.open_trades_count,
                        'daily_pnl': state.daily_pnl,
                        'market_regime': {k: v.value if hasattr(v, 'value') else str(v) 
                                        for k, v in state.market_regime.items()}
                    }
                except Exception as e:
                    logger.error(f"Error getting brain state: {e}")
            
            # Price data
            price_data = {}
            if self.app.price_engine:
                for symbol in self.app.price_engine.symbols[:5]:  # Limit to 5
                    tick = self.app.price_engine.get_last_price(symbol)
                    if tick:
                        price_data[symbol] = {
                            'bid': tick.bid,
                            'ask': tick.ask,
                            'spread': tick.spread,
                            'timestamp': tick.timestamp
                        }
            
            # Recent signals
            recent_signals = []
            if self.app.brain:
                recent_signals = self.app.brain.get_decision_history(10)
            
            return {
                'account': account,
                'positions': positions,
                'brain_state': brain_state,
                'prices': price_data,
                'recent_signals': recent_signals,
                'timestamp': datetime.now().isoformat()
            }
            
        except Exception as e:
            logger.error(f"Error compiling dashboard data: {e}")
            return {'error': str(e)}
    
    def record_trade(self, trade: Dict):
        """Record trade for history"""
        self._trade_history.append({
            **trade,
            'timestamp': datetime.now().isoformat()
        })


def create_dashboard_app(trading_app, host: str = "0.0.0.0", port: int = 8081):
    """Create and configure dashboard web application"""
    if not AIOHTTP_AVAILABLE:
        logger.error("aiohttp required for dashboard")
        return None
    
    app = web.Application()
    
    # Setup Jinja2 templates
    template_loader = jinja2.PackageLoader('dashboard', 'templates')
    aiohttp_jinja2.setup(app, loader=template_loader)
    
    # WebSocket manager
    ws_manager = DashboardWebSocketManager()
    data_source = DashboardDataSource(trading_app)
    
    # Store in app
    app['trading_app'] = trading_app
    app['ws_manager'] = ws_manager
    app['data_source'] = data_source
    
    # Routes
    app.router.add_get('/', index_handler)
    app.router.add_get('/ws', websocket_handler)
    app.router.add_get('/api/data', api_data_handler)
    app.router.add_get('/api/chart/{symbol}', chart_data_handler)
    app.router.add_static('/static', path='dashboard/static', name='static')
    
    # Start background broadcasting
    async def on_startup(app):
        app['broadcast_task'] = asyncio.create_task(
            ws_manager.start_broadcasting(data_source, interval=1.0)
        )
    
    async def on_cleanup(app):
        ws_manager.stop()
        if 'broadcast_task' in app:
            app['broadcast_task'].cancel()
    
    app.on_startup.append(on_startup)
    app.on_cleanup.append(on_cleanup)
    
    return app, host, port


async def index_handler(request):
    """Main dashboard page"""
    html_content = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>HOPEFX AI Trading Dashboard</title>
    <script src="https://cdn.plot.ly/plotly-latest.min.js"></script>
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body { 
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            background: #0a0e27;
            color: #fff;
            min-height: 100vh;
        }
        .header { 
            background: linear-gradient(135deg, #1e3c72 0%, #2a5298 100%);
            padding: 20px;
            text-align: center;
            border-bottom: 3px solid #00d4ff;
        }
        .header h1 { 
            font-size: 2.5em; 
            text-transform: uppercase;
            letter-spacing: 3px;
            text-shadow: 0 0 20px rgba(0, 212, 255, 0.5);
        }
        .status-bar {
            display: flex;
            justify-content: center;
            gap: 30px;
            padding: 15px;
            background: rgba(0, 0, 0, 0.3);
        }
        .status-item {
            display: flex;
            align-items: center;
            gap: 10px;
        }
        .status-indicator {
            width: 12px;
            height: 12px;
            border-radius: 50%;
            animation: pulse 2s infinite;
        }
        .status-online { background: #00ff88; }
        .status-offline { background: #ff4444; }
        .status-warning { background: #ffaa00; }
        @keyframes pulse {
            0%, 100% { opacity: 1; }
            50% { opacity: 0.5; }
        }
        .dashboard-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(350px, 1fr));
            gap: 20px;
            padding: 20px;
        }
        .card {
            background: rgba(255, 255, 255, 0.05);
            border-radius: 15px;
            padding: 20px;
            border: 1px solid rgba(0, 212, 255, 0.2);
            backdrop-filter: blur(10px);
        }
        .card h3 {
            color: #00d4ff;
            margin-bottom: 15px;
            font-size: 1.2em;
            text-transform: uppercase;
            letter-spacing: 2px;
        }
        .metric-row {
            display: flex;
            justify-content: space-between;
            padding: 10px 0;
            border-bottom: 1px solid rgba(255, 255, 255, 0.1);
        }
        .metric-label { color: #8892b0; }
        .metric-value { 
            font-weight: bold; 
            font-family: 'Courier New', monospace;
        }
        .positive { color: #00ff88; }
        .negative { color: #ff4444; }
        .neutral { color: #ffd700; }
        .chart-container {
            height: 300px;
            margin-top: 10px;
        }
        .positions-table {
            width: 100%;
            border-collapse: collapse;
        }
        .positions-table th,
        .positions-table td {
            padding: 12px;
            text-align: left;
            border-bottom: 1px solid rgba(255, 255, 255, 0.1);
        }
        .positions-table th {
            color: #00d4ff;
            text-transform: uppercase;
            font-size: 0.9em;
        }
        .btn {
            background: linear-gradient(135deg, #00d4ff 0%, #0099cc 100%);
            border: none;
            padding: 10px 20px;
            border-radius: 25px;
            color: #fff;
            cursor: pointer;
            font-weight: bold;
            transition: all 0.3s;
        }
        .btn:hover {
            transform: translateY(-2px);
            box-shadow: 0 5px 20px rgba(0, 212, 255, 0.4);
        }
        .log-stream {
            height: 200px;
            overflow-y: auto;
            background: rgba(0, 0, 0, 0.3);
            border-radius: 10px;
            padding: 10px;
            font-family: 'Courier New', monospace;
            font-size: 0.85em;
        }
        .log-entry {
            padding: 5px 0;
            border-bottom: 1px solid rgba(255, 255, 255, 0.05);
        }
        .log-time { color: #00d4ff; }
        .log-info { color: #00ff88; }
        .log-warning { color: #ffaa00; }
        .log-error { color: #ff4444; }
        .heatmap {
            display: grid;
            grid-template-columns: repeat(10, 1fr);
            gap: 2px;
            margin-top: 10px;
        }
        .heatmap-cell {
            aspect-ratio: 1;
            border-radius: 3px;
            transition: all 0.3s;
        }
        @media (max-width: 768px) {
            .dashboard-grid { grid-template-columns: 1fr; }
            .header h1 { font-size: 1.5em; }
        }
    </style>
</head>
<body>
    <div class="header">
        <h1>🚀 HOPEFX AI Trading</h1>
        <div class="status-bar">
            <div class="status-item">
                <div class="status-indicator status-online" id="brain-status"></div>
                <span>Brain: <span id="brain-state">Running</span></span>
            </div>
            <div class="status-item">
                <div class="status-indicator status-online" id="broker-status"></div>
                <span>Broker: <span id="broker-state">Connected</span></span>
            </div>
            <div class="status-item">
                <div class="status-indicator status-online" id="data-status"></div>
                <span>Data Feed: <span id="data-state">Live</span></span>
            </div>
            <div class="status-item">
                <span id="uptime">Uptime: 00:00:00</span>
            </div>
        </div>
    </div>

    <div class="dashboard-grid">
        <!-- Account Overview -->
        <div class="card">
            <h3>💰 Account Overview</h3>
            <div class="metric-row">
                <span class="metric-label">Balance</span>
                <span class="metric-value" id="balance">$0.00</span>
            </div>
            <div class="metric-row">
                <span class="metric-label">Equity</span>
                <span class="metric-value" id="equity">$0.00</span>
            </div>
            <div class="metric-row">
                <span class="metric-label">Free Margin</span>
                <span class="metric-value" id="free-margin">$0.00</span>
            </div>
            <div class="metric-row">
                <span class="metric-label">Daily P&L</span>
                <span class="metric-value" id="daily-pnl">$0.00</span>
            </div>
            <div class="metric-row">
                <span class="metric-label">Open Positions</span>
                <span class="metric-value" id="open-positions">0</span>
            </div>
            <div class="metric-row">
                <span class="metric-label">Total Exposure</span>
                <span class="metric-value" id="exposure">0%</span>
            </div>
        </div>

        <!-- Live Prices -->
        <div class="card">
            <h3>📊 Live Prices</h3>
            <div id="prices-container">
                <!-- Populated by WebSocket -->
            </div>
            <div class="chart-container" id="price-chart"></div>
        </div>

        <!-- Active Positions -->
        <div class="card">
            <h3>📈 Active Positions</h3>
            <table class="positions-table">
                <thead>
                    <tr>
                        <th>Symbol</th>
                        <th>Side</th>
                        <th>Size</th>
                        <th>Entry</th>
                        <th>Current</th>
                        <th>P&L</th>
                    </tr>
                </thead>
                <tbody id="positions-tbody">
                    <!-- Populated by WebSocket -->
                </tbody>
            </table>
        </div>

        <!-- Performance Chart -->
        <div class="card">
            <h3>📉 Performance</h3>
            <div class="chart-container">
                <canvas id="performance-chart"></canvas>
            </div>
        </div>

        <!-- Market Regime -->
        <div class="card">
            <h3>🎯 Market Regime</h3>
            <div id="regime-container">
                <!-- Populated by WebSocket -->
            </div>
            <div class="heatmap" id="regime-heatmap"></div>
        </div>

        <!-- Recent Activity -->
        <div class="card">
            <h3>🔔 Recent Signals</h3>
            <div class="log-stream" id="signal-log">
                <!-- Populated by WebSocket -->
            </div>
        </div>

        <!-- Risk Metrics -->
        <div class="card">
            <h3>⚠️ Risk Metrics</h3>
            <div class="metric-row">
                <span class="metric-label">Drawdown</span>
                <span class="metric-value" id="drawdown">0.00%</span>
            </div>
            <div class="metric-row">
                <span class="metric-label">Margin Used</span>
                <span class="metric-value" id="margin-used">0.00%</span>
            </div>
            <div class="metric-row">
                <span class="metric-label">Risk/Reward</span>
                <span class="metric-value" id="risk-reward">0.0</span>
            </div>
            <div class="metric-row">
                <span class="metric-label">Win Rate</span>
                <span class="metric-value" id="win-rate">0.0%</span>
            </div>
        </div>

        <!-- System Control -->
        <div class="card">
            <h3>🎮 System Control</h3>
            <button class="btn" onclick="pauseTrading()">⏸️ Pause</button>
            <button class="btn" onclick="resumeTrading()">▶️ Resume</button>
            <button class="btn" onclick="emergencyStop()" style="background: linear-gradient(135deg, #ff4444 0%, #cc0000 100%);">🛑 Emergency Stop</button>
            <div style="margin-top: 15px;">
                <label>Max Position Size: <input type="range" min="1" max="10" value="2" id="position-size">%</label>
            </div>
        </div>
    </div>

    <script>
        // WebSocket connection
        const ws = new WebSocket(`ws://${window.location.host}/ws`);
        let priceHistory = {};
        let chartInstances = {};

        ws.onopen = function() {
            console.log('Dashboard connected');
            addLogEntry('Connected to trading system', 'info');
        };

        ws.onmessage = function(event) {
            const message = JSON.parse(event.data);
            updateDashboard(message.data);
        };

        ws.onclose = function() {
            console.log('Dashboard disconnected');
            addLogEntry('Disconnected from trading system', 'warning');
            document.getElementById('brain-status').className = 'status-indicator status-offline';
        };

        function updateDashboard(data) {
            // Update account metrics
            if (data.account) {
                document.getElementById('balance').textContent = formatCurrency(data.account.balance);
                document.getElementById('equity').textContent = formatCurrency(data.account.equity);
                document.getElementById('free-margin').textContent = formatCurrency(data.account.free_margin);
                
                const dailyPnl = data.account.realized_pnl || 0;
                const pnlElement = document.getElementById('daily-pnl');
                pnlElement.textContent = formatCurrency(dailyPnl);
                pnlElement.className = 'metric-value ' + (dailyPnl >= 0 ? 'positive' : 'negative');
            }

            // Update brain state
            if (data.brain_state) {
                document.getElementById('brain-state').textContent = data.brain_state.system_state;
                document.getElementById('open-positions').textContent = data.brain_state.open_trades;
                
                const drawdown = (data.brain_state.daily_pnl / (data.account?.balance || 1)) * 100;
                document.getElementById('drawdown').textContent = drawdown.toFixed(2) + '%';
                document.getElementById('drawdown').className = 'metric-value ' + (drawdown > 10 ? 'negative' : 'positive');
            }

            // Update prices
            if (data.prices) {
                updatePrices(data.prices);
            }

            // Update positions
            if (data.positions) {
                updatePositions(data.positions);
            }

            // Update signals
            if (data.recent_signals) {
                data.recent_signals.slice(-5).forEach(signal => {
                    addLogEntry(`${signal.signal.symbol}: ${signal.signal.action} @ ${signal.fill_price}`, 'info');
                });
            }

            // Update market regime
            if (data.brain_state && data.brain_state.market_regime) {
                updateRegime(data.brain_state.market_regime);
            }
        }

        function updatePrices(prices) {
            const container = document.getElementById('prices-container');
            container.innerHTML = '';
            
            Object.entries(prices).forEach(([symbol, data]) => {
                const div = document.createElement('div');
                div.className = 'metric-row';
                div.innerHTML = `
                    <span class="metric-label">${symbol}</span>
                    <span class="metric-value">
                        Bid: ${data.bid.toFixed(5)} | 
                        Ask: ${data.ask.toFixed(5)} | 
                        Spread: ${(data.spread * 10000).toFixed(1)}p
                    </span>
                `;
                container.appendChild(div);
                
                // Update price history for chart
                if (!priceHistory[symbol]) priceHistory[symbol] = [];
                priceHistory[symbol].push({ x: new Date(), y: (data.bid + data.ask) / 2 });
                if (priceHistory[symbol].length > 50) priceHistory[symbol].shift();
            });
            
            updatePriceChart();
        }

        function updatePriceChart() {
            const traces = Object.entries(priceHistory).map(([symbol, data]) => ({
                x: data.map(d => d.x),
                y: data.map(d => d.y),
                mode: 'lines',
                name: symbol,
                line: { width: 2 }
            }));
            
            Plotly.newPlot('price-chart', traces, {
                paper_bgcolor: 'rgba(0,0,0,0)',
                plot_bgcolor: 'rgba(0,0,0,0)',
                font: { color: '#fff' },
                xaxis: { gridcolor: 'rgba(255,255,255,0.1)' },
                yaxis: { gridcolor: 'rgba(255,255,255,0.1)' },
                margin: { t: 10, b: 30, l: 40, r: 10 },
                showlegend: true,
                legend: { font: { color: '#fff' } }
            }, { responsive: true });
        }

        function updatePositions(positions) {
            const tbody = document.getElementById('positions-tbody');
            tbody.innerHTML = '';
            
            positions.forEach(pos => {
                const tr = document.createElement('tr');
                const pnlClass = pos.unrealized_pnl >= 0 ? 'positive' : 'negative';
                tr.innerHTML = `
                    <td>${pos.symbol}</td>
                    <td class="${pos.side === 'long' ? 'positive' : 'negative'}">${pos.side.toUpperCase()}</td>
                    <td>${pos.quantity.toFixed(2)}</td>
                    <td>${pos.entry_price.toFixed(5)}</td>
                    <td>${pos.current_price.toFixed(5)}</td>
                    <td class="${pnlClass}">$${pos.unrealized_pnl.toFixed(2)}</td>
                `;
                tbody.appendChild(tr);
            });
        }

        function updateRegime(regimes) {
            const container = document.getElementById('regime-container');
            container.innerHTML = '';
            
            Object.entries(regimes).forEach(([symbol, regime]) => {
                const div = document.createElement('div');
                div.className = 'metric-row';
                const regimeColors = {
                    'trending_up': 'positive',
                    'trending_down': 'negative',
                    'ranging': 'neutral',
                    'volatile': 'negative'
                };
                div.innerHTML = `
                    <span class="metric-label">${symbol}</span>
                    <span class="metric-value ${regimeColors[regime] || 'neutral'}">${regime.replace('_', ' ').toUpperCase()}</span>
                `;
                container.appendChild(div);
            });
        }

        function addLogEntry(message, level) {
            const log = document.getElementById('signal-log');
            const entry = document.createElement('div');
            entry.className = 'log-entry';
            const time = new Date().toLocaleTimeString();
            entry.innerHTML = `<span class="log-time">[${time}]</span> <span class="log-${level}">${message}</span>`;
            log.insertBefore(entry, log.firstChild);
            if (log.children.length > 50) log.removeChild(log.lastChild);
        }

        function formatCurrency(value) {
            return '$' + (value || 0).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
        }

        // Control functions
        function pauseTrading() {
            fetch('/api/control/pause', { method: 'POST' })
                .then(() => addLogEntry('Trading paused', 'warning'));
        }

        function resumeTrading() {
            fetch('/api/control/resume', { method: 'POST' })
                .then(() => addLogEntry('Trading resumed', 'info'));
        }

        function emergencyStop() {
            if (confirm('EMERGENCY STOP: Close all positions and halt trading?')) {
                fetch('/api/control/emergency', { method: 'POST' })
                    .then(() => addLogEntry('EMERGENCY STOP executed', 'error'));
            }
        }

        // Initialize performance chart
        const ctx = document.getElementById('performance-chart').getContext('2d');
        new Chart(ctx, {
            type: 'line',
            data: {
                labels: [],
                datasets: [{
                    label: 'Equity',
                    data: [],
                    borderColor: '#00d4ff',
                    backgroundColor: 'rgba(0, 212, 255, 0.1)',
                    fill: true
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: { labels: { color: '#fff' } }
                },
                scales: {
                    x: { grid: { color: 'rgba(255,255,255,0.1)' }, ticks: { color: '#fff' } },
                    y: { grid: { color: 'rgba(255,255,255,0.1)' }, ticks: { color: '#fff' } }
                }
            }
        });

        // Uptime counter
        let uptimeSeconds = 0;
        setInterval(() => {
            uptimeSeconds++;
            const hours = Math.floor(uptimeSeconds / 3600);
            const minutes = Math.floor((uptimeSeconds % 3600) / 60);
            const seconds = uptimeSeconds % 60;
            document.getElementById('uptime').textContent = 
                `Uptime: ${hours.toString().padStart(2, '0')}:${minutes.toString().padStart(2, '0')}:${seconds.toString().padStart(2, '0')}`;
        }, 1000);
    </script>
</body>
</html>
    """
    return web.Response(text=html_content, content_type='text/html')


async def websocket_handler(request):
    """WebSocket endpoint for real-time updates"""
    ws = web.WebSocketResponse()
    await ws.prepare(request)
    
    ws_manager = request.app['ws_manager']
    await ws_manager.register(ws)
    
    try:
        async for msg in ws:
            if msg.type == WSMsgType.TEXT:
                # Handle client messages if needed
                data = json.loads(msg.data)
                if data.get('action') == 'ping':
                    await ws.send_str(json.dumps({'type': 'pong'}))
            elif msg.type == WSMsgType.ERROR:
                logger.error(f"WebSocket error: {ws.exception()}")
    finally:
        await ws_manager.unregister(ws)
    
    return ws


async def api_data_handler(request):
    """REST API for dashboard data"""
    data_source = request.app['data_source']
    data = await data_source.get_dashboard_data()
    return web.json_response(data)


async def chart_data_handler(request):
    """Get historical chart data"""
    symbol = request.match_info['symbol']
    # Return historical data for charting
    return web.json_response({
        'symbol': symbol,
        'data': []  # Would fetch from database
    })


async def start_dashboard(trading_app, host: str = "0.0.0.0", port: int = 8081):
    """Start dashboard server"""
    app, host, port = create_dashboard_app(trading_app, host, port)
    
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, host, port)
    await site.start()
    
    logger.info(f"🎛️ Dashboard started at http://{host}:{port}")
    return runner
