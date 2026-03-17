enhanced_realtime_engine = '''
"""
Enhanced Real-Time Price Engine with Multi-Source Fallback & True Tick Data
Replaces 5-second yfinance polling with institutional-grade data aggregation.
"""

import asyncio
import websockets
import json
import logging
from dataclasses import dataclass, asdict
from typing import Dict, List, Optional, Callable, Set, Any
from datetime import datetime, timedelta
from enum import Enum
import numpy as np
import pandas as pd
from abc import ABC, abstractmethod
import aiohttp
import redis.asyncio as redis
from collections import deque

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class DataSource(Enum):
    """Priority-ordered data sources"""
    POLYGON = "polygon"           # Real-time WebSocket (paid)
    ALPACA = "alpaca"             # Real-time crypto/equities
    OANDA_STREAM = "oanda_stream" # FX streaming API
    TRUEFX = "truefx"             # Free FX data
    YFINANCE = "yfinance"         # Fallback (delayed)
    MOCK = "mock"                 # Simulation mode


@dataclass
class Tick:
    """Normalized tick data structure"""
    symbol: str
    timestamp: datetime
    bid: float
    ask: float
    bid_size: float = 0.0
    ask_size: float = 0.0
    last_price: float = 0.0
    last_size: float = 0.0
    volume: float = 0.0
    source: str = "unknown"
    
    @property
    def mid(self) -> float:
        return (self.bid + self.ask) / 2 if self.bid > 0 and self.ask > 0 else self.last_price
    
    @property
    def spread(self) -> float:
        return self.ask - self.bid if self.bid > 0 and self.ask > 0 else 0.0
    
    def to_dict(self) -> Dict:
        return {
            **asdict(self),
            "timestamp": self.timestamp.isoformat(),
            "mid": self.mid,
            "spread": self.spread
        }


class DataProvider(ABC):
    """Abstract base for data providers"""
    
    def __init__(self, name: str, priority: int):
        self.name = name
        self.priority = priority
        self.is_connected = False
        self.last_tick: Optional[Tick] = None
        self.error_count = 0
        self.max_errors = 5
    
    @abstractmethod
    async def connect(self):
        pass
    
    @abstractmethod
    async def subscribe(self, symbols: List[str]):
        pass
    
    @abstractmethod
    async def stream(self) -> Tick:
        """Yield ticks asynchronously"""
        pass
    
    @abstractmethod
    async def disconnect(self):
        pass
    
    def is_healthy(self) -> bool:
        return self.error_count < self.max_errors


class PolygonProvider(DataProvider):
    """Polygon.io real-time stock/crypto data (WebSocket)"""
    
    def __init__(self, api_key: str):
        super().__init__("polygon", 1)
        self.api_key = api_key
        self.ws = None
        self.uri = f"wss://socket.polygon.io/stocks"
    
    async def connect(self):
        try:
            self.ws = await websockets.connect(self.uri)
            auth_msg = {"action": "auth", "params": self.api_key}
            await self.ws.send(json.dumps(auth_msg))
            response = await self.ws.recv()
            logger.info(f"Polygon connected: {response}")
            self.is_connected = True
        except Exception as e:
            logger.error(f"Polygon connection failed: {e}")
            self.error_count += 1
    
    async def subscribe(self, symbols: List[str]):
        if not self.is_connected:
            return
        msg = {"action": "subscribe", "params": f"T.{','.join(symbols)}"}
        await self.ws.send(json.dumps(msg))
    
    async def stream(self) -> Tick:
        if not self.is_connected:
            return None
        
        try:
            data = await self.ws.recv()
            packet = json.loads(data)
            
            for item in packet:
                if item.get("ev") == "T":  # Trade event
                    tick = Tick(
                        symbol=item["sym"],
                        timestamp=datetime.fromtimestamp(item["t"] / 1000),
                        last_price=item["p"],
                        last_size=item["s"],
                        bid=item.get("bp", item["p"]),
                        ask=item.get("ap", item["p"]),
                        source="polygon"
                    )
                    self.last_tick = tick
                    return tick
        except Exception as e:
            logger.error(f"Polygon stream error: {e}")
            self.error_count += 1
        return None
    
    async def disconnect(self):
        if self.ws:
            await self.ws.close()
            self.is_connected = False


class OandaProvider(DataProvider):
    """OANDA streaming API for FX (RESTful streaming)"""
    
    def __init__(self, account_id: str, api_key: str, environment: str = "practice"):
        super().__init__("oanda", 2)
        self.account_id = account_id
        self.api_key = api_key
        self.base_url = f"https://stream-fx{'' if environment == 'live' else 'practice'}.oanda.com"
        self.session = None
    
    async def connect(self):
        self.session = aiohttp.ClientSession()
        self.is_connected = True
    
    async def subscribe(self, instruments: List[str]):
        """OANDA uses instrument names like XAU_USD"""
        self.instruments = instruments
    
    async def stream(self) -> Tick:
        if not self.is_connected:
            return None
        
        url = f"{self.base_url}/v3/accounts/{self.account_id}/pricing/stream"
        headers = {"Authorization": f"Bearer {self.api_key}"}
        params = {"instruments": ",".join(self.instruments)}
        
        try:
            async with self.session.get(url, headers=headers, params=params) as resp:
                async for line in resp.content:
                    if not line:
                        continue
                    data = json.loads(line)
                    
                    if data.get("type") == "PRICE":
                        tick = Tick(
                            symbol=data["instrument"].replace("_", ""),
                            timestamp=datetime.now(),
                            bid=float(data["bids"][0]["price"]),
                            ask=float(data["asks"][0]["price"]),
                            bid_size=float(data["bids"][0]["liquidity"]),
                            ask_size=float(data["asks"][0]["liquidity"]),
                            source="oanda"
                        )
                        self.last_tick = tick
                        return tick
        except Exception as e:
            logger.error(f"OANDA stream error: {e}")
            self.error_count += 1
        return None
    
    async def disconnect(self):
        if self.session:
            await self.session.close()
            self.is_connected = False


class TrueFXProvider(DataProvider):
    """TrueFX free forex data (HTTP polling)"""
    
    def __init__(self):
        super().__init__("truefx", 3)
        self.session = None
        self.base_url = "https://webrates.truefx.com/rates/connect.html"
    
    async def connect(self):
        self.session = aiohttp.ClientSession()
        self.is_connected = True
    
    async def subscribe(self, symbols: List[str]):
        pass  # TrueFX provides all pairs
    
    async def stream(self) -> Tick:
        """Poll every 5 seconds (rate limited)"""
        try:
            async with self.session.get(f"{self.base_url}?f=csv") as resp:
                text = await resp.text()
                # Parse CSV format: pair, timestamp, bid, ask
                lines = text.strip().split("\\n")
                for line in lines[1:]:  # Skip header
                    parts = line.split(",")
                    if len(parts) >= 4:
                        symbol = parts[0].replace("/", "")
                        bid = float(parts[2])
                        ask = float(parts[3])
                        return Tick(
                            symbol=symbol,
                            timestamp=datetime.now(),
                            bid=bid,
                            ask=ask,
                            source="truefx"
                        )
        except Exception as e:
            logger.error(f"TrueFX error: {e}")
            self.error_count += 1
        return None
    
    async def disconnect(self):
        if self.session:
            await self.session.close()


class YFinanceProvider(DataProvider):
    """YFinance fallback (delayed, for simulation)"""
    
    def __init__(self):
        super().__init__("yfinance", 4)
        self.session = None
    
    async def connect(self):
        self.session = aiohttp.ClientSession()
        self.is_connected = True
    
    async def subscribe(self, symbols: List[str]):
        self.symbols = symbols
    
    async def stream(self) -> Tick:
        """Poll yfinance every 30 seconds (it's delayed anyway)"""
        import yfinance as yf
        
        try:
            for symbol in self.symbols:
                # Map XAUUSD to GC=F (Gold futures)
                yf_symbol = "GC=F" if symbol in ["XAUUSD", "XAU_USD"] else symbol
                
                ticker = yf.Ticker(yf_symbol)
                data = ticker.history(period="1d", interval="1m", prepost=True)
                
                if not data.empty:
                    last = data.iloc[-1]
                    return Tick(
                        symbol=symbol,
                        timestamp=datetime.now(),
                        bid=last["Close"] * 0.9995,  # Estimate spread
                        ask=last["Close"] * 1.0005,
                        last_price=last["Close"],
                        volume=last["Volume"],
                        source="yfinance_delayed"
                    )
        except Exception as e:
            logger.error(f"YFinance error: {e}")
            self.error_count += 1
        return None
    
    async def disconnect(self):
        if self.session:
            await self.session.close()


class MockProvider(DataProvider):
    """Simulated data for testing with realistic microstructure"""
    
    def __init__(self, volatility: float = 0.0001):
        super().__init__("mock", 5)
        self.volatility = volatility
        self.price = 1950.0  # XAUUSD starting price
        self.last_update = datetime.now()
    
    async def connect(self):
        self.is_connected = True
    
    async def subscribe(self, symbols: List[str]):
        pass
    
    async def stream(self) -> Tick:
        """Generate realistic tick data with microstructure noise"""
        await asyncio.sleep(0.1)  # 10 ticks per second
        
        # Geometric Brownian Motion with mean reversion
        dt = 0.1 / 86400  # Time step in days
        drift = 0.0
        
        # Add microstructure noise
        noise = np.random.normal(0, self.volatility * np.sqrt(dt))
        self.price *= np.exp(drift * dt + noise)
        
        # Realistic spread (2-8 pips for XAUUSD)
        spread = np.random.uniform(0.02, 0.08)
        
        # Bid/ask asymmetry based on recent direction
        direction_bias = np.sign(noise) * spread * 0.1
        
        return Tick(
            symbol="XAUUSD",
            timestamp=datetime.now(),
            bid=self.price - spread/2 - direction_bias,
            ask=self.price + spread/2 - direction_bias,
            bid_size=np.random.exponential(10),
            ask_size=np.random.exponential(10),
            last_price=self.price,
            last_size=np.random.exponential(5),
            source="mock_simulation"
        )
    
    async def disconnect(self):
        self.is_connected = False


class MultiSourcePriceEngine:
    """
    Aggregates multiple data sources with automatic failover.
    Provides normalized tick stream with quality metrics.
    """
    
    def __init__(self, 
                 redis_url: str = None,
                 max_latency_ms: float = 1000.0):
        self.providers: Dict[str, DataProvider] = {}
        self.active_provider: Optional[DataProvider] = None
        self.redis_client = None
        self.redis_url = redis_url
        self.max_latency = max_latency_ms
        
        # Statistics
        self.ticks_received = 0
        self.ticks_by_source: Dict[str, int] = {}
        self.latency_history: deque = deque(maxlen=1000)
        
        # Subscribers
        self.subscribers: Set[Callable] = set()
        self.symbols: List[str] = []
        
    def add_provider(self, provider: DataProvider):
        """Add a data source (lower priority = better)"""
        self.providers[provider.name] = provider
        logger.info(f"Added provider: {provider.name} (priority {provider.priority})")
    
    async def initialize(self):
        """Connect to Redis and all providers"""
        if self.redis_url:
            self.redis_client = await redis.from_url(self.redis_url)
        
        # Sort providers by priority
        sorted_providers = sorted(self.providers.values(), key=lambda p: p.priority)
        
        # Try to connect to each provider
        for provider in sorted_providers:
            await provider.connect()
            if provider.is_connected:
                logger.info(f"Connected to {provider.name}")
                if not self.active_provider:
                    self.active_provider = provider
            else:
                logger.warning(f"Failed to connect to {provider.name}")
    
    async def subscribe(self, symbols: List[str]):
        """Subscribe to symbols across all providers"""
        self.symbols = symbols
        for provider in self.providers.values():
            if provider.is_connected:
                await provider.subscribe(symbols)
    
    async def start_streaming(self):
        """Main streaming loop with failover"""
        while True:
            try:
                # Check if we need to failover
                if not self.active_provider or not self.active_provider.is_healthy():
                    await self._failover()
                
                if not self.active_provider:
                    logger.error("No active data provider available!")
                    await asyncio.sleep(1)
                    continue
                
                # Stream from active provider
                start_time = datetime.now()
                tick = await self.active_provider.stream()
                
                if tick:
                    # Calculate latency
                    latency = (datetime.now() - start_time).total_seconds() * 1000
                    self.latency_history.append(latency)
                    
                    # Validate tick
                    if self._validate_tick(tick):
                        await self._distribute_tick(tick)
                        self.ticks_received += 1
                        self.ticks_by_source[tick.source] = self.ticks_by_source.get(tick.source, 0) + 1
                        
                        # Cache in Redis
                        if self.redis_client:
                            await self._cache_tick(tick)
                
            except Exception as e:
                logger.error(f"Streaming error: {e}")
                self.active_provider.error_count += 1
                await asyncio.sleep(0.1)
    
    def _validate_tick(self, tick: Tick) -> bool:
        """Validate tick quality"""
        # Check for stale data
        age = (datetime.now() - tick.timestamp).total_seconds()
        if age > 60:  # Older than 1 minute
            return False
        
        # Check for invalid prices
        if tick.bid <= 0 or tick.ask <= 0 or tick.bid >= tick.ask:
            return False
        
        # Check for extreme spread
        spread_pct = tick.spread / tick.mid if tick.mid > 0 else 0
        if spread_pct > 0.01:  # > 1% spread is suspicious
            return False
        
        return True
    
    async def _cache_tick(self, tick: Tick):
        """Cache tick in Redis for other services"""
        if not self.redis_client:
            return
        
        key = f"tick:{tick.symbol}"
        await self.redis_client.setex(
            key, 
            60,  # TTL 60 seconds
            json.dumps(tick.to_dict())
        )
    
    async def _distribute_tick(self, tick: Tick):
        """Send tick to all subscribers"""
        for callback in self.subscribers:
            try:
                if asyncio.iscoroutinefunction(callback):
                    await callback(tick)
                else:
                    callback(tick)
            except Exception as e:
                logger.error(f"Subscriber error: {e}")
    
    async def _failover(self):
        """Switch to next healthy provider"""
        sorted_providers = sorted(self.providers.values(), key=lambda p: p.priority)
        
        for provider in sorted_providers:
            if provider.is_healthy() and provider.is_connected:
                if self.active_provider:
                    logger.warning(f"Failing over from {self.active_provider.name} to {provider.name}")
                else:
                    logger.info(f"Activating provider: {provider.name}")
                
                self.active_provider = provider
                await provider.subscribe(self.symbols)
                return
        
        logger.error("No healthy providers available!")
        self.active_provider = None
    
    def on_tick(self, callback: Callable):
        """Subscribe to tick updates"""
        self.subscribers.add(callback)
    
    def get_stats(self) -> Dict:
        """Get engine statistics"""
        avg_latency = np.mean(self.latency_history) if self.latency_history else 0
        return {
            "ticks_received": self.ticks_received,
            "ticks_by_source": self.ticks_by_source,
            "active_provider": self.active_provider.name if self.active_provider else None,
            "avg_latency_ms": avg_latency,
            "providers_status": {
                name: {"connected": p.is_connected, "healthy": p.is_healthy(), "errors": p.error_count}
                for name, p in self.providers.items()
            }
        }
    
    async def shutdown(self):
        """Graceful shutdown"""
        for provider in self.providers.values():
            await provider.disconnect()
        if self.redis_client:
            await self.redis_client.close()


class WebSocketServer:
    """
    WebSocket server for distributing ticks to frontend clients.
    Supports multiple clients with automatic reconnection.
    """
    
    def __init__(self, price_engine: MultiSourcePriceEngine, host: str = "0.0.0.0", port: int = 8765):
        self.price_engine = price_engine
        self.host = host
        self.port = port
        self.clients: Set[websockets.WebSocketServerProtocol] = set()
        self.subscriptions: Dict[websockets.WebSocketServerProtocol, Set[str]] = {}
    
    async def register(self, websocket: websockets.WebSocketServerProtocol):
        """New client connection"""
        self.clients.add(websocket)
        self.subscriptions[websocket] = set()
        logger.info(f"Client connected. Total clients: {len(self.clients)}")
    
    async def unregister(self, websocket: websockets.WebSocketServerProtocol):
        """Client disconnection"""
        self.clients.discard(websocket)
        self.subscriptions.pop(websocket, None)
        logger.info(f"Client disconnected. Total clients: {len(self.clients)}")
    
    async def broadcast_tick(self, tick: Tick):
        """Send tick to subscribed clients"""
        if not self.clients:
            return
        
        message = json.dumps(tick.to_dict())
        
        # Send only to clients subscribed to this symbol
        disconnected = []
        for client in self.clients:
            try:
                subs = self.subscriptions.get(client, set())
                if not subs or tick.symbol in subs:  # Empty = all symbols
                    await client.send(message)
            except websockets.exceptions.ConnectionClosed:
                disconnected.append(client)
            except Exception as e:
                logger.error(f"Broadcast error: {e}")
        
        # Clean up disconnected clients
        for client in disconnected:
            await self.unregister(client)
    
    async def handle_client(self, websocket: websockets.WebSocketServerProtocol, path: str):
        """Handle client messages (subscriptions, etc.)"""
        await self.register(websocket)
        try:
            async for message in websocket:
                try:
                    data = json.loads(message)
                    action = data.get("action")
                    
                    if action == "subscribe":
                        symbols = set(data.get("symbols", []))
                        self.subscriptions[websocket] = symbols
                        await websocket.send(json.dumps({
                            "type": "subscribed",
                            "symbols": list(symbols)
                        }))
                    
                    elif action == "ping":
                        await websocket.send(json.dumps({"type": "pong"}))
                    
                    elif action == "stats":
                        stats = self.price_engine.get_stats()
                        await websocket.send(json.dumps({
                            "type": "stats",
                            "data": stats
                        }))
                
                except json.JSONDecodeError:
                    await websocket.send(json.dumps({"error": "Invalid JSON"}))
        
        except websockets.exceptions.ConnectionClosed:
            pass
        finally:
            await self.unregister(websocket)
    
    async def start(self):
        """Start WebSocket server"""
        # Subscribe price engine to broadcast
        self.price_engine.on_tick(self.broadcast_tick)
        
        # Start server
        async with websockets.serve(self.handle_client, self.host, self.port):
            logger.info(f"WebSocket server started on {self.host}:{self.port}")
            await asyncio.Future()  # Run forever


# Usage example
async def main():
    """Example: Multi-source price engine with WebSocket distribution"""
    
    # Initialize engine
    engine = MultiSourcePriceEngine(
        redis_url="redis://localhost:6379",
        max_latency_ms=500.0
    )
    
    # Add providers in priority order
    # 1. OANDA (if credentials available)
    # engine.add_provider(OandaProvider("account_id", "api_key"))
    
    # 2. TrueFX (free)
    engine.add_provider(TrueFXProvider())
    
    # 3. YFinance (delayed fallback)
    engine.add_provider(YFinanceProvider())
    
    # 4. Mock (last resort for testing)
    engine.add_provider(MockProvider(volatility=0.0002))
    
    # Initialize
    await engine.initialize()
    await engine.subscribe(["XAUUSD", "EURUSD", "GBPUSD"])
    
    # Start WebSocket server in background
    ws_server = WebSocketServer(engine)
    ws_task = asyncio.create_task(ws_server.start())
    
    # Start streaming
    stream_task = asyncio.create_task(engine.start_streaming())
    
    # Run for 60 seconds then shutdown
    await asyncio.sleep(60)
    
    print("\\nEngine Statistics:")
    print(json.dumps(engine.get_stats(), indent=2))
    
    await engine.shutdown()
    ws_task.cancel()
    stream_task.cancel()


if __name__ == "__main__":
    asyncio.run(main())
'''

print("✅ Enhanced Real-Time Price Engine created with:")
print("   • Multi-source aggregation (Polygon, OANDA, TrueFX, yfinance, mock)")
print("   • Automatic failover with health checking")
print("   • Realistic mock data with microstructure noise")
print("   • Tick validation (stale data detection, spread checks)")
print("   • Redis caching for cross-service data sharing")
print("   • WebSocket server with client subscription management")
print("   • Latency tracking and quality metrics")
print(f"\nFile length: {len(enhanced_realtime_engine)} characters")