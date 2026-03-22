"""
HOPEFX Real-Time Dashboard
Web interface for monitoring the Master Control Core
"""

from fastapi import FastAPI, WebSocket
from fastapi.responses import HTMLResponse
import asyncio
import json
from datetime import datetime


class DashboardServer:
    """Web dashboard for HOPEFX Ultimate"""
    
    def __init__(self, orchestra, event_bus):
        self.orchestra = orchestra
        self.event_bus = event_bus
        self.app = FastAPI()
        self.clients = []
        self._setup_routes()
    
    def _setup_routes(self):
        @self.app.get("/")
        def home():
            return HTMLResponse(self._html())
        
        @self.app.get("/api/status")
        def status():
            return {
                'orchestra': self.orchestra.get_heatmap_data(),
                'events': self.event_bus.get_metrics(),
                'time': datetime.utcnow().isoformat()
            }
        
        @self.app.websocket("/ws")
        async def ws(websocket: WebSocket):
            await websocket.accept()
            self.clients.append(websocket)
            try:
                while True:
                    await websocket.send_json({
                        'heatmap': self.orchestra.get_heatmap_data(),
                        'events': self.event_bus.get_metrics()
                    })
                    await asyncio.sleep(1)
            except:
                self.clients.remove(websocket)
    
    def _html(self):
        return """<!DOCTYPE html>
<html>
<head>
    <title>HOPEFX Ultimate</title>
    <style>
        body { font-family: monospace; background: #0a0a0a; color: #0f0; margin: 0; }
        .header { background: #111; padding: 20px; border-bottom: 2px solid #0f0; }
        .grid { display: grid; grid-template-columns: 1fr 1fr; gap: 20px; padding: 20px; }
        .panel { background: #151515; border: 1px solid #333; padding: 15px; }
        .metric { display: inline-block; margin: 10px 20px; }
        .strategy { padding: 10px; border-left: 3px solid #333; margin: 5px 0; }
        .strategy.active { border-left-color: #0f0; background: #1a1a1a; }
    </style>
</head>
<body>
    <div class="header">
        <h1>🧠 HOPEFX Ultimate Dashboard</h1>
        <div>
            <span class="metric">Regime: <span id="regime">-</span></span>
            <span class="metric">Active: <span id="active">0</span></span>
            <span class="metric">Events: <span id="events">0</span></span>
        </div>
    </div>
    <div class="grid">
        <div class="panel">
            <h3>Strategies</h3>
            <div id="strategies"></div>
        </div>
        <div class="panel">
            <h3>System Status</h3>
            <pre id="status"></pre>
        </div>
    </div>
    <script>
        const ws = new WebSocket("ws://" + window.location.host + "/ws");
        ws.onmessage = (e) => {
            const d = JSON.parse(e.data);
            document.getElementById('regime').textContent = d.heatmap.current_regime;
            document.getElementById('active').textContent = d.heatmap.active_count;
            document.getElementById('events').textContent = d.events.published;
            
            let s = '';
            for (const [id, data] of Object.entries(d.heatmap.strategies)) {
                s += `<div class="strategy ${data.active ? 'active' : ''}">
                    <strong>${id}</strong> | Win: ${(data.win_rate * 100).toFixed(1)}% | 
                    Sharpe: ${data.sharpe.toFixed(2)} | Alloc: ${(data.allocation * 100).toFixed(0)}%
                </div>`;
            }
            document.getElementById('strategies').innerHTML = s;
            document.getElementById('status').textContent = JSON.stringify(d, null, 2);
        };
    </script>
</body>
</html>"""
    
    def run(self, port=8080):
        import uvicorn
        uvicorn.run(self.app, host="0.0.0.0", port=port)
