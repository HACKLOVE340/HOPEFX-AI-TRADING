"""
HOPEFX Real-Time Price Engine
WebSocket and REST hybrid data feed with automatic failover
"""

import asyncio
import logging
import time
import json
import threading
from typing import Dict, List, Optional, Callable, Any
from dataclasses import dataclass, field
from datetime import datetime, timezone
from collections import defaultdict, deque
import numpy as np

try:
    import aiohttp
    import aiohttp.web
    AIOHTTP_AVAILABLE = True
except ImportError:
    AIOHTTP_AVAILABLE = False

try:
    import websockets
    WEBSOCKETS_AVAILABLE = True
except ImportError:
    WEBSOCKETS_AVAILABLE = False

logger = logging.getLogger(__name__)


@dataclass
class Tick:
    """Price tick data"""
    symbol: str
    timestamp: float
    bid: float
    ask: float
    mid: float
    volume: float = 0.0
    bid_volume: float = 0.0
    ask_volume: float = 0.0
    
    @property
    def spread(self) -> float:
        return self.ask - self.bid if self.ask > self.bid else 0.0
    
    @property
    def spread_pct(self) -> float:
        return (self.spread / self.mid * 100) if self.mid > 0 else 0.0


@dataclass
class OHLCV:
    """OHLCV candle data"""
    timestamp: float
    open: float
    high: float
    low: float
    close: float
    volume: float
    
    def to_dict(self) -> Dict:
        return {
            'timestamp': self.timestamp,
            'open': self.open,
            'high': self.high,
            'low': self.low,
            'close': self.close,
            'volume': self.volume
        }


class PriceFeedBase:
    """Base class for price feeds"""
    
    def __init__(self, symbols: List[str], config: Dict[str, Any]):
        self.symbols = symbols
        self.config = config
        self.active = False
        self._callbacks: List[Callable] = []
        self._last_prices: Dict[str, Tick] = {}
        self._lock = asyncio.Lock()
    
    async def connect(self):
        raise NotImplementedError
    
    async def disconnect(self):
        raise NotImplementedError
    
    def register_callback(self, callback: Callable[[Tick], None]):
        """Register price update callback"""
        self._callbacks.append(callback)
    
    def _notify_callbacks(self, tick: Tick):
        """Notify all registered callbacks"""
        for callback in self._callbacks:
            try:
                callback(tick)
            except Exception as e:
                logger.error(f"Callback error: {e}")
    
    def get_last_price(self, symbol: str) -> Optional[Tick]:
        """Get last known price"""
        return self._last_prices.get(symbol)
    
    async def get_ohlcv(self, symbol: str, timeframe: str, limit: int = 100) -> List[OHLCV]:
        """Get historical OHLCV data"""
        raise NotImplementedError


class WebSocketPriceFeed(PriceFeedBase):
    """
    WebSocket-based real-time price feed
    Automatic reconnection with exponential backoff
    """
    
    def __init__(self, symbols: List[str], config: Dict[str, Any]):
        super().__init__(symbols, config)
        self.ws_url = config.get('websocket_url', 'wss://ws-feed.exchange.coinbase.com')
        self.reconnect_delay = config.get('reconnect_delay', 1.0)
        self.max_reconnect_delay = config.get('max_reconnect_delay', 60.0)
        self.heartbeat_interval = config.get('heartbeat_interval', 30.0)
        
        self._websocket = None
        self._reconnect_attempts = 0
        self._running = False
        self._heartbeat_task = None
        self._receive_task = None
        self._ohlcv_buffers: Dict[str, Dict[str, deque]] = defaultdict(
            lambda: defaultdict(lambda: deque(maxlen=1000))
        )
    
    async def connect(self):
        """Connect to WebSocket feed"""
        if not WEBSOCKETS_AVAILABLE:
            raise ImportError("websockets library required: pip install websockets")
        
        self._running = True
        
        while self._running:
            try:
                logger.info(f"Connecting to WebSocket: {self.ws_url}")
                
                self._websocket = await websockets.connect(
                    self.ws_url,
                    ping_interval=self.heartbeat_interval,
                    ping_timeout=10
                )
                
                # Subscribe to channels
                subscribe_msg = {
                    "type": "subscribe",
                    "product_ids": self.symbols,
                    "channels": ["ticker", "heartbeat"]
                }
                await self._websocket.send(json.dumps(subscribe_msg))
                
                self.active = True
                self._reconnect_attempts = 0
                
                logger.info(f"WebSocket connected, subscribed to {len(self.symbols)} symbols")
                
                # Start tasks
                self._receive_task = asyncio.create_task(self._receive_loop())
                self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())
                
                # Wait for disconnect
                await self._receive_task
                
            except Exception as e:
                logger.error(f"WebSocket error: {e}")
                self.active = False
                
                if not self._running:
                    break
                
                # Exponential backoff
                delay = min(
                    self.reconnect_delay * (2 ** self._reconnect_attempts),
                    self.max_reconnect_delay
                )
                self._reconnect_attempts += 1
                
                logger.info(f"Reconnecting in {delay}s (attempt {self._reconnect_attempts})")
                await asyncio.sleep(delay)
    
    async def disconnect(self):
        """Disconnect from WebSocket"""
        self._running = False
        self.active = False
        
        if self._heartbeat_task:
            self._heartbeat_task.cancel()
        
        if self._receive_task:
            self._receive_task.cancel()
        
        if self._websocket:
            await self._websocket.close()
        
        logger.info("WebSocket disconnected")
    
    async def _receive_loop(self):
        """Main receive loop"""
        try:
            async for message in self._websocket:
                try:
                    data = json.loads(message)
                    await self._process_message(data)
                except json.JSONDecodeError:
                    logger.warning(f"Invalid JSON received: {message[:100]}")
                except Exception as e:
                    logger.error(f"Message processing error: {e}")
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"Receive loop error: {e}")
    
    async def _process_message(self, data: Dict):
        """Process incoming message"""
        msg_type = data.get('type')
        
        if msg_type == 'ticker':
            # Process tick
            symbol = data.get('product_id')
            if symbol not in self.symbols:
                return
            
            tick = Tick(
                symbol=symbol,
                timestamp=time.time(),
                bid=float(data.get('best_bid', 0)),
                ask=float(data.get('best_ask', 0)),
                mid=(float(data.get('best_bid', 0)) + float(data.get('best_ask', 0))) / 2,
                volume=float(data.get('volume_24h', 0)),
                bid_volume=float(data.get('bid_volume', 0)),
                ask_volume=float(data.get('ask_volume', 0))
            )
            
            async with self._lock:
                self._last_prices[symbol] = tick
            
            # Update OHLCV buffers
            self._update_ohlcv_buffers(symbol, tick)
            
            # Notify callbacks
            self._notify_callbacks(tick)
            
        elif msg_type == 'heartbeat':
            logger.debug("Heartbeat received")
            
        elif msg_type == 'error':
            logger.error(f"WebSocket error message: {data}")
    
    def _update_ohlcv_buffers(self, symbol: str, tick: Tick):
        """Update OHLCV buffers with new tick"""
        now = datetime.now(timezone.utc)
        
        for timeframe, seconds in [
            ('1m', 60), ('5m', 300), ('15m', 900),
            ('1h', 3600), ('4h', 14400), ('1d', 86400)
        ]:
            bucket_time = int(now.timestamp() / seconds) * seconds
            
            buffer = self._ohlcv_buffers[symbol][timeframe]
            
            if buffer and buffer[-1].timestamp == bucket_time:
                # Update existing candle
                candle = buffer[-1]
                candle.high = max(candle.high, tick.mid)
                candle.low = min(candle.low, tick.mid)
                candle.close = tick.mid
                candle.volume += tick.volume
            else:
                # New candle
                new_candle = OHLCV(
                    timestamp=bucket_time,
                    open=tick.mid,
                    high=tick.mid,
                    low=tick.mid,
                    close=tick.mid,
                    volume=tick.volume
                )
                buffer.append(new_candle)
    
    async def _heartbeat_loop(self):
        """Send periodic heartbeats"""
        try:
            while self._running:
                await asyncio.sleep(self.heartbeat_interval)
                if self._websocket and self._websocket.open:
                    try:
                        await self._websocket.send(json.dumps({"type": "heartbeat"}))
                    except Exception as e:
                        logger.warning(f"Heartbeat send failed: {e}")
        except asyncio.CancelledError:
            pass
    
    async def get_ohlcv(self, symbol: str, timeframe: str, limit: int = 100) -> List[OHLCV]:
        """Get OHLCV from buffer"""
        if symbol not in self._ohlcv_buffers or timeframe not in self._ohlcv_buffers[symbol]:
            return []
        
        buffer = self._ohlcv_buffers[symbol][timeframe]
        return list(buffer)[-limit:]
    
    def get_spread(self, symbol: str) -> Optional[float]:
        """Get current spread for symbol"""
        tick = self.get_last_price(symbol)
        return tick.spread if tick else None


class RESTPriceFeed(PriceFeedBase):
    """
    REST API fallback for historical data
    """
    
    def __init__(self, symbols: List[str], config: Dict[str, Any]):
        super().__init__(symbols, config)
        self.rest_url = config.get('rest_url', 'https://api.exchange.coinbase.com')
        self.rate_limit_per_sec = config.get('rate_limit_per_sec', 10)
        self._session: Optional[aiohttp.ClientSession] = None
        self._request_times: deque = deque(maxlen=100)
        self._cache: Dict[str, Any] = {}
        self._cache_ttl = 5  # seconds
    
    async def connect(self):
        """Initialize REST client"""
        if not AIOHTTP_AVAILABLE:
            raise ImportError("aiohttp required: pip install aiohttp")
        
        self._session = aiohttp.ClientSession(
            headers={'Accept': 'application/json'},
            timeout=aiohttp.ClientTimeout(total=30)
        )
        self.active = True
        logger.info("REST price feed initialized")
    
    async def disconnect(self):
        """Close REST client"""
        if self._session:
            await self._session.close()
        self.active = False
    
    async def _rate_limited_request(self, url: str) -> Dict:
        """Make rate-limited request"""
        # Enforce rate limit
        now = time.time()
        while self._request_times and now - self._request_times[0] < 1.0:
            if len(self._request_times) >= self.rate_limit_per_sec:
                await asyncio.sleep(0.1)
                now = time.time()
            else:
                break
        
        self._request_times.append(now)
        
        async with self._session.get(url) as response:
            if response.status == 200:
                return await response.json()
            else:
                raise ValueError(f"HTTP {response.status}: {await response.text()}")
    
    async def get_ohlcv(self, symbol: str, timeframe: str, limit: int = 100) -> List[OHLCV]:
        """Get OHLCV from REST API"""
        cache_key = f"{symbol}_{timeframe}_{limit}"
        
        # Check cache
        if cache_key in self._cache:
            cached_time, data = self._cache[cache_key]
            if time.time() - cached_time < self._cache_ttl:
                return data
        
        # Map timeframe to API granularity
        granularity_map = {
            '1m': 60, '5m': 300, '15m': 900,
            '1h': 3600, '6h': 21600, '1d': 86400
        }
        granularity = granularity_map.get(timeframe, 3600)
        
        # Calculate time range
        end_time = datetime.now(timezone.utc)
        start_time = end_time - timedelta(seconds=granularity * limit)
        
        url = (
            f"{self.rest_url}/products/{symbol}/candles?"
            f"granularity={granularity}&"
            f"start={start_time.isoformat()}&"
            f"end={end_time.isoformat()}"
        )
        
        try:
            data = await self._rate_limited_request(url)
            
            # Parse response (Coinbase format: [time, low, high, open, close, volume])
            ohlcv_list = []
            for candle in reversed(data):  # Reverse to chronological order
                ohlcv_list.append(OHLCV(
                    timestamp=candle[0],
                    low=float(candle[1]),
                    high=float(candle[2]),
                    open=float(candle[3]),
                    close=float(candle[4]),
                    volume=float(candle[5])
                ))
            
            # Cache result
            self._cache[cache_key] = (time.time(), ohlcv_list)
            
            return ohlcv_list
            
        except Exception as e:
            logger.error(f"REST API error for {symbol}: {e}")
            return []


class RealTimePriceEngine:
    """
    Hybrid price engine with WebSocket primary and REST fallback
    
    Features:
    - Automatic failover between WebSocket and REST
    - OHLCV aggregation from ticks
    - Spread monitoring
    - Latency tracking
    """
    
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.symbols = config.get('symbols', ['EURUSD', 'XAUUSD'])
        
        # Primary and fallback feeds
        self._ws_feed = WebSocketPriceFeed(self.symbols, config)
        self._rest_feed = RESTPriceFeed(self.symbols, config)
        
        # State
        self.active = False
        self._primary_active = False
        self._fallback_active = False
        self._latency_metrics: deque = deque(maxlen=1000)
        self._spread_metrics: Dict[str, deque] = {
            s: deque(maxlen=100) for s in self.symbols
        }
        
        # Callbacks
        self._price_callbacks: List[Callable[[Tick], None]] = []
        self._candle_callbacks: List[Callable[[str, str, OHLCV], None]] = []
        
        # Tasks
        self._tasks: List[asyncio.Task] = []
        self._monitor_task: Optional[asyncio.Task] = None
    
    async def start(self):
        """Start price engine"""
        logger.info(f"Starting price engine for {len(self.symbols)} symbols")
        
        # Start fallback first
        try:
            await self._rest_feed.connect()
            self._fallback_active = True
            logger.info("REST fallback active")
        except Exception as e:
            logger.warning(f"REST fallback failed: {e}")
        
        # Start primary WebSocket
        try:
            ws_task = asyncio.create_task(self._ws_feed.connect())
            self._tasks.append(ws_task)
            self._primary_active = True
            
            # Register for updates
            self._ws_feed.register_callback(self._on_price_update)
            
            logger.info("WebSocket feed active")
        except Exception as e:
            logger.warning(f"WebSocket failed, using REST only: {e}")
            self._primary_active = False
        
        self.active = self._primary_active or self._fallback_active
        
        # Start monitoring
        self._monitor_task = asyncio.create_task(self._monitor_loop())
        
        logger.info("Price engine started")
    
    async def stop(self):
        """Stop price engine"""
        logger.info("Stopping price engine")
        
        # Cancel tasks
        for task in self._tasks:
            task.cancel()
        
        if self._monitor_task:
            self._monitor_task.cancel()
        
        # Disconnect feeds
        await self._ws_feed.disconnect()
        await self._rest_feed.disconnect()
        
        self.active = False
        logger.info("Price engine stopped")
    
    def _on_price_update(self, tick: Tick):
        """Handle price update from WebSocket"""
        # Record metrics
        self._spread_metrics[tick.symbol].append(tick.spread)
        
        # Notify callbacks
        for callback in self._price_callbacks:
            try:
                callback(tick)
            except Exception as e:
                logger.error(f"Price callback error: {e}")
    
    def register_price_callback(self, callback: Callable[[Tick], None]):
        """Register for price updates"""
        self._price_callbacks.append(callback)
    
    def register_candle_callback(self, callback: Callable[[str, str, OHLCV], None]):
        """Register for candle updates"""
        self._candle_callbacks.append(callback)
    
    def get_last_price(self, symbol: str) -> Optional[Tick]:
        """Get last price (prefer WebSocket)"""
        # Try WebSocket first
        tick = self._ws_feed.get_last_price(symbol)
        if tick:
            return tick
        
        # Fall back to REST
        return self._rest_feed.get_last_price(symbol)
    
    async def get_ohlcv(self, symbol: str, timeframe: str, limit: int = 100) -> List[OHLCV]:
        """Get OHLCV data"""
        # Try WebSocket buffer first
        if self._primary_active:
            data = self._ws_feed.get_ohlcv(symbol, timeframe, limit)
            if data:
                return data
        
        # Fall back to REST
        return await self._rest_feed.get_ohlcv(symbol, timeframe, limit)
    
    async def _monitor_loop(self):
        """Monitor feed health"""
        while self.active:
            try:
                # Check WebSocket health
                if self._primary_active and not self._ws_feed.active:
                    logger.warning("WebSocket disconnected, activating REST fallback")
                    self._primary_active = False
                
                # Log statistics
                avg_spreads = {
                    s: np.mean(list(self._spread_metrics[s])) if self._spread_metrics[s] else 0
                    for s in self.symbols
                }
                
                logger.debug(f"Price engine stats: {avg_spreads}")
                
                await asyncio.sleep(60)  # Check every minute
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Monitor loop error: {e}")
                await asyncio.sleep(5)
    
    def get_status(self) -> Dict[str, Any]:
        """Get engine status"""
        return {
            'active': self.active,
            'primary_active': self._primary_active,
            'fallback_active': self._fallback_active,
            'symbols': self.symbols,
            'websocket_connected': self._ws_feed.active if self._ws_feed else False,
            'rest_available': self._rest_feed.active if self._rest_feed else False
        }


# Convenience function
async def create_price_engine(config: Dict[str, Any]) -> RealTimePriceEngine:
    """Factory function to create price engine"""
    engine = RealTimePriceEngine(config)
    await engine.start()
    return engine
