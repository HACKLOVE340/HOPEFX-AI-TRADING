
# 1. CORE DATA ENGINE - Real-time price feed with WebSocket and REST fallback

data_engine_code = '''"""
HOPEFX Real-Time Price Engine
Multi-source market data ingestion with failover
Supports: WebSocket primary, REST fallback, synthetic data for testing
"""

import asyncio
import aiohttp
import json
import logging
import time
from typing import Dict, List, Optional, Callable, Any
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
import websockets
from websockets.exceptions import ConnectionClosed

logger = logging.getLogger(__name__)

class DataSource(Enum):
    WEBSOCKET = "websocket"
    REST = "rest"
    SYNTHETIC = "synthetic"

@dataclass
class Tick:
    symbol: str
    timestamp: int
    bid: float
    ask: float
    last_price: float
    volume: float
    source: DataSource = DataSource.WEBSOCKET
    
    @property
    def spread(self) -> float:
        return self.ask - self.bid
    
    @property
    def mid(self) -> float:
        return (self.bid + self.ask) / 2

@dataclass
class OHLCV:
    timestamp: int
    open: float
    high: float
    low: float
    close: float
    volume: float
    
class RealTimePriceEngine:
    """
    Production-grade price engine with:
    - WebSocket primary feed
    - REST API fallback
    - Automatic reconnection
    - Multi-symbol support
    - Tick aggregation to OHLCV
    """
    
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.symbols: List[str] = config.get('symbols', ['XAUUSD', 'EURUSD'])
        self.active = False
        self.last_price: Dict[str, Tick] = {}
        self.price_history: Dict[str, List[Tick]] = {s: [] for s in self.symbols}
        self.ohlcv_data: Dict[str, Dict[str, List[OHLCV]]] = {
            s: {'1m': [], '5m': [], '15m': [], '1h': []} for s in self.symbols
        }
        
        # Callbacks
        self.tick_callbacks: List[Callable[[Tick], None]] = []
        self.ohlcv_callbacks: List[Callable[[str, str, OHLCV], None]] = []
        
        # WebSocket state
        self.ws_connection = None
        self.ws_task = None
        self.reconnect_delay = 1
        self.max_reconnect_delay = 60
        
        # Aggregation state
        self.current_candles: Dict[str, Dict[str, OHLCV]] = {
            s: {'1m': None, '5m': None, '15m': None, '1h': None} for s in self.symbols
        }
        
        logger.info(f"PriceEngine initialized for symbols: {self.symbols}")
    
    async def start(self):
        """Start the price engine"""
        self.active = True
        logger.info("Starting RealTimePriceEngine...")
        
        # Start WebSocket connection
        self.ws_task = asyncio.create_task(self._websocket_loop())
        
        # Start OHLCV aggregation
        asyncio.create_task(self._aggregation_loop())
        
        # Start REST fallback monitor
        asyncio.create_task(self._rest_fallback_loop())
        
        logger.info("PriceEngine started successfully")
    
    async def stop(self):
        """Graceful shutdown"""
        self.active = False
        if self.ws_task:
            self.ws_task.cancel()
            try:
                await self.ws_task
            except asyncio.CancelledError:
                pass
        
        if self.ws_connection:
            await self.ws_connection.close()
        
        logger.info("PriceEngine stopped")
    
    async def _websocket_loop(self):
        """Main WebSocket connection loop with auto-reconnect"""
        while self.active:
            try:
                await self._connect_websocket()
                self.reconnect_delay = 1  # Reset on successful connection
            except Exception as e:
                logger.error(f"WebSocket error: {e}")
                await asyncio.sleep(self.reconnect_delay)
                self.reconnect_delay = min(self.reconnect_delay * 2, self.max_reconnect_delay)
    
    async def _connect_websocket(self):
        """Establish WebSocket connection and handle messages"""
        # Using Coinbase Pro WebSocket as example (free, reliable)
        # For forex/XAUUSD, you'd use OANDA, Polygon.io, or similar
        ws_url = self.config.get('websocket_url', 'wss://ws-feed.exchange.coinbase.com')
        
        logger.info(f"Connecting to WebSocket: {ws_url}")
        
        async with websockets.connect(ws_url) as ws:
            self.ws_connection = ws
            
            # Subscribe to channels
            subscribe_msg = {
                "type": "subscribe",
                "product_ids": self._normalize_symbols(self.symbols),
                "channels": ["ticker"]
            }
            await ws.send(json.dumps(subscribe_msg))
            
            logger.info("WebSocket connected and subscribed")
            
            async for message in ws:
                if not self.active:
                    break
                await self._handle_ws_message(message)
    
    async def _handle_ws_message(self, message: str):
        """Parse and process WebSocket message"""
        try:
            data = json.loads(message)
            
            if data.get('type') == 'ticker':
                # Coinbase format - adapt to your broker
                symbol = self._denormalize_symbol(data.get('product_id', ''))
                if symbol not in self.symbols:
                    return
                
                tick = Tick(
                    symbol=symbol,
                    timestamp=int(time.time()),
                    bid=float(data.get('best_bid', 0)),
                    ask=float(data.get('best_ask', 0)),
                    last_price=float(data.get('price', 0)),
                    volume=float(data.get('volume_24h', 0)),
                    source=DataSource.WEBSOCKET
                )
                
                await self._process_tick(tick)
                
        except Exception as e:
            logger.error(f"Error handling message: {e}")
    
    async def _process_tick(self, tick: Tick):
        """Process incoming tick data"""
        # Store tick
        self.last_price[tick.symbol] = tick
        self.price_history[tick.symbol].append(tick)
        
        # Trim history (keep last 10k ticks)
        if len(self.price_history[tick.symbol]) > 10000:
            self.price_history[tick.symbol] = self.price_history[tick.symbol][-5000:]
        
        # Notify callbacks
        for callback in self.tick_callbacks:
            try:
                callback(tick)
            except Exception as e:
                logger.error(f"Tick callback error: {e}")
    
    async def _aggregation_loop(self):
        """Aggregate ticks into OHLCV candles"""
        while self.active:
            try:
                await self._aggregate_candles()
                await asyncio.sleep(1)  # Check every second
            except Exception as e:
                logger.error(f"Aggregation error: {e}")
                await asyncio.sleep(5)
    
    async def _aggregate_candles(self):
        """Create OHLCV candles from tick history"""
        now = int(time.time())
        
        for symbol in self.symbols:
            if symbol not in self.last_price:
                continue
            
            current_price = self.last_price[symbol].mid
            
            for timeframe, seconds in [('1m', 60), ('5m', 300), ('15m', 900), ('1h', 3600)]:
                candle_start = (now // seconds) * seconds
                
                current = self.current_candles[symbol][timeframe]
                
                if current is None or current.timestamp != candle_start:
                    # New candle
                    if current is not None:
                        # Close previous candle
                        self.ohlcv_data[symbol][timeframe].append(current)
                        if len(self.ohlcv_data[symbol][timeframe]) > 1000:
                            self.ohlcv_data[symbol][timeframe] = self.ohlcv_data[symbol][timeframe][-500:]
                        
                        # Notify callbacks
                        for callback in self.ohlcv_callbacks:
                            try:
                                callback(symbol, timeframe, current)
                            except Exception as e:
                                logger.error(f"OHLCV callback error: {e}")
                    
                    # Start new candle
                    self.current_candles[symbol][timeframe] = OHLCV(
                        timestamp=candle_start,
                        open=current_price,
                        high=current_price,
                        low=current_price,
                        close=current_price,
                        volume=0
                    )
                else:
                    # Update current candle
                    current.high = max(current.high, current_price)
                    current.low = min(current.low, current_price)
                    current.close = current_price
                    current.volume += self.last_price[symbol].volume
    
    async def _rest_fallback_loop(self):
        """REST API fallback when WebSocket is down"""
        while self.active:
            try:
                # If no prices for 10 seconds, use REST
                stale_symbols = [
                    s for s in self.symbols 
                    if s not in self.last_price or 
                    time.time() - self.last_price[s].timestamp > 10
                ]
                
                if stale_symbols and not self.ws_connection:
                    await self._fetch_rest_prices(stale_symbols)
                
                await asyncio.sleep(5)
            except Exception as e:
                logger.error(f"REST fallback error: {e}")
                await asyncio.sleep(10)
    
    async def _fetch_rest_prices(self, symbols: List[str]):
        """Fetch prices via REST API"""
        # Example using Coinbase REST API
        rest_url = self.config.get('rest_url', 'https://api.exchange.coinbase.com')
        
        async with aiohttp.ClientSession() as session:
            for symbol in symbols:
                try:
                    normalized = self._normalize_symbol(symbol)
                    async with session.get(f"{rest_url}/products/{normalized}/ticker") as resp:
                        if resp.status == 200:
                            data = await resp.json()
                            tick = Tick(
                                symbol=symbol,
                                timestamp=int(time.time()),
                                bid=float(data.get('bid', 0)),
                                ask=float(data.get('ask', 0)),
                                last_price=float(data.get('price', 0)),
                                volume=float(data.get('volume', 0)),
                                source=DataSource.REST
                            )
                            await self._process_tick(tick)
                except Exception as e:
                    logger.error(f"REST fetch error for {symbol}: {e}")
    
    def _normalize_symbols(self, symbols: List[str]) -> List[str]:
        """Convert to exchange format (e.g., XAUUSD -> XAU-USD)"""
        return [s.replace('/', '-') for s in symbols]
    
    def _normalize_symbol(self, symbol: str) -> str:
        return symbol.replace('/', '-')
    
    def _denormalize_symbol(self, symbol: str) -> str:
        return symbol.replace('-', '')
    
    def get_last_price(self, symbol: str) -> Optional[Tick]:
        return self.last_price.get(symbol)
    
    def get_ohlcv(self, symbol: str, timeframe: str, limit: int = 100) -> List[OHLCV]:
        """Get OHLCV data for symbol and timeframe"""
        data = self.ohlcv_data.get(symbol, {}).get(timeframe, [])
        return data[-limit:] if data else []
    
    def on_tick(self, callback: Callable[[Tick], None]):
        """Register tick callback"""
        self.tick_callbacks.append(callback)
    
    def on_ohlcv(self, callback: Callable[[str, str, OHLCV], None]):
        """Register OHLCV callback"""
        self.ohlcv_callbacks.append(callback)
'''

# Write the file
with open(project_root / "data" / "real_time_price_engine.py", "w") as f:
    f.write(data_engine_code)

print("✓ Created data/real_time_price_engine.py")
