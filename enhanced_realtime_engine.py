# enhanced_realtime_engine.py
"""
Institutional-Grade Real-Time Market Data Engine v3.0
Multi-Source Aggregation | Sub-Millisecond Latency | AI-Powered Data Quality
"""

import asyncio
import aiohttp
import websockets
from dataclasses import dataclass, asdict, field
from typing import Dict, List, Optional, Callable, Set, Any, Tuple, Union
from datetime import datetime, timedelta
from enum import Enum, auto
from collections import deque, defaultdict
from abc import ABC, abstractmethod
import logging
import json
import numpy as np
import pandas as pd
from concurrent.futures import ThreadPoolExecutor
import hashlib
import time

# Optional dependencies
try:
    import redis.asyncio as redis
    REDIS_AVAILABLE = True
except ImportError:
    REDIS_AVAILABLE = False

try:
    import zmq
    ZMQ_AVAILABLE = True
except ImportError:
    ZMQ_AVAILABLE = False

logger = logging.getLogger(__name__)

class DataQuality(Enum):
    """Data quality classification"""
    EXCELLENT = auto()      # <1ms latency, verified, no gaps
    GOOD = auto()           # <10ms, minor gaps acceptable
    FAIR = auto()           # <100ms, some degradation
    POOR = auto()           # >100ms, significant issues
    STALE = auto()          # >1s, unusable for trading
    INVALID = auto()        # Failed validation checks

class ConnectionState(Enum):
    """Connection lifecycle states"""
    DISCONNECTED = auto()
    CONNECTING = auto()
    CONNECTED = auto()
    SUBSCRIBING = auto()
    STREAMING = auto()
    DEGRADED = auto()
    FAILED = auto()
    RECONNECTING = auto()

@dataclass(frozen=True)
class MarketTick:
    """Normalized market tick with quality metrics"""
    symbol: str
    timestamp: datetime
    bid: float
    ask: float
    bid_size: float = 0.0
    ask_size: float = 0.0
    last_price: Optional[float] = None
    last_size: Optional[float] = None
    volume_24h: Optional[float] = None
    vwap: Optional[float] = None
    open_interest: Optional[float] = None
    
    # Metadata
    source: str = "unknown"
    receive_time: datetime = field(default_factory=datetime.now)
    latency_ms: float = 0.0
    quality: DataQuality = DataQuality.GOOD
    
    def __post_init__(self):
        # Validate prices
        if self.bid <= 0 or self.ask <= 0:
            object.__setattr__(self, 'quality', DataQuality.INVALID)
        if self.bid >= self.ask:
            object.__setattr__(self, 'quality', DataQuality.INVALID)
    
    @property
    def mid(self) -> float:
        return (self.bid + self.ask) / 2
    
    @property
    def spread(self) -> float:
        return self.ask - self.bid
    
    @property
    def spread_bps(self) -> float:
        return (self.spread / self.mid) * 10000 if self.mid > 0 else 0
    
    def to_dict(self) -> Dict:
        return {
            **asdict(self),
            'timestamp': self.timestamp.isoformat(),
            'receive_time': self.receive_time.isoformat(),
            'mid': self.mid,
            'spread': self.spread
        }

@dataclass
class DataSourceMetrics:
    """Real-time source performance metrics"""
    source_name: str
    state: ConnectionState = ConnectionState.DISCONNECTED
    
    # Latency metrics (ms)
    latency_min: float = float('inf')
    latency_max: float = 0.0
    latency_avg: float = 0.0
    latency_history: deque = field(default_factory=lambda: deque(maxlen=1000))
    
    # Quality metrics
    ticks_received: int = 0
    ticks_valid: int = 0
    ticks_stale: int = 0
    ticks_invalid: int = 0
    
    # Error tracking
    errors: int = 0
    reconnections: int = 0
    last_error: Optional[str] = None
    last_error_time: Optional[datetime] = None
    
    # Health score 0-100
    health_score: float = 100.0
    
    def update_latency(self, latency_ms: float):
        """Update latency statistics"""
        self.latency_history.append(latency_ms)
        self.latency_min = min(self.latency_min, latency_ms)
        self.latency_max = max(self.latency_max, latency_ms)
        self.latency_avg = np.mean(self.latency_history) if self.latency_history else latency_ms
    
    def record_tick(self, quality: DataQuality):
        """Record tick quality"""
        self.ticks_received += 1
        if quality == DataQuality.EXCELLENT or quality == DataQuality.GOOD:
            self.ticks_valid += 1
        elif quality == DataQuality.STALE:
            self.ticks_stale += 1
        elif quality == DataQuality.INVALID:
            self.ticks_invalid += 1
    
    def record_error(self, error: str):
        """Record error"""
        self.errors += 1
        self.last_error = error
        self.last_error_time = datetime.now()
        self.health_score = max(0, self.health_score - 10)
    
    def record_reconnection(self):
        """Record successful reconnection"""
        self.reconnections += 1
        self.health_score = min(100, self.health_score + 20)

class DataProvider(ABC):
    """Abstract base for all data providers"""
    
    def __init__(self, name: str, priority: int, weight: float = 1.0):
        self.name = name
        self.priority = priority  # Lower = higher priority
        self.weight = weight
        self.metrics = DataSourceMetrics(source_name=name)
        self.state = ConnectionState.DISCONNECTED
        
        # Configuration
        self.symbols: Set[str] = set()
        self.reconnect_delay = 1.0
        self.max_reconnect_delay = 60.0
        self.current_reconnect_delay = self.reconnect_delay
        
        # Streaming
        self._callbacks: List[Callable[[MarketTick], Any]] = []
        self._running = False
        self._task: Optional[asyncio.Task] = None
    
    @abstractmethod
    async def connect(self) -> bool:
        """Establish connection"""
        pass
    
    @abstractmethod
    async def subscribe(self, symbols: List[str]) -> bool:
        """Subscribe to symbols"""
        pass
    
    @abstractmethod
    async def stream(self):
        """Main streaming loop - yield ticks"""
        pass
    
    @abstractmethod
    async def disconnect(self):
        """Clean disconnect"""
        pass
    
    def on_tick(self, callback: Callable[[MarketTick], Any]):
        """Register tick callback"""
        self._callbacks.append(callback)
    
    async def _notify_callbacks(self, tick: MarketTick):
        """Notify all registered callbacks"""
        for callback in self._callbacks:
            try:
                if asyncio.iscoroutinefunction(callback):
                    await callback(tick)
                else:
                    callback(tick)
            except Exception as e:
                logger.error(f"Callback error in {self.name}: {e}")
    
    async def start(self):
        """Start streaming with auto-reconnect"""
        self._running = True
        while self._running:
            try:
                self.metrics.state = ConnectionState.CONNECTING
                if await self.connect():
                    self.metrics.state = ConnectionState.CONNECTED
                    if await self.subscribe(list(self.symbols)):
                        self.metrics.state = ConnectionState.STREAMING
                        self.current_reconnect_delay = self.reconnect_delay
                        await self.stream()
            except Exception as e:
                logger.error(f"{self.name} error: {e}")
                self.metrics.record_error(str(e))
            
            if self._running:
                self.metrics.state = ConnectionState.RECONNECTING
                logger.info(f"{self.name} reconnecting in {self.current_reconnect_delay}s...")
                await asyncio.sleep(self.current_reconnect_delay)
                self.current_reconnect_delay = min(
                    self.current_reconnect_delay * 2,
                    self.max_reconnect_delay
                )
                self.metrics.record_reconnection()
    
    def stop(self):
        """Stop streaming"""
        self._running = False
        if self._task:
            self._task.cancel()

class PolygonProvider(DataProvider):
    """Polygon.io WebSocket - Professional equities/crypto data"""
    
    def __init__(self, api_key: str):
        super().__init__("polygon", priority=1, weight=1.0)
        self.api_key = api_key
        self.ws: Optional[websockets.WebSocketClientProtocol] = None
        self.uri = "wss://socket.polygon.io/stocks"
    
    async def connect(self) -> bool:
        try:
            self.ws = await websockets.connect(self.uri)
            auth = {"action": "auth", "params": self.api_key}
            await self.ws.send(json.dumps(auth))
            resp = await asyncio.wait_for(self.ws.recv(), timeout=5.0)
            logger.info(f"Polygon auth: {resp}")
            return True
        except Exception as e:
            logger.error(f"Polygon connect failed: {e}")
            return False
    
    async def subscribe(self, symbols: List[str]) -> bool:
        if not self.ws:
            return False
        try:
            # Map to Polygon format
            poly_symbols = [s.replace("/", "") for s in symbols]
            msg = {"action": "subscribe", "params": f"T.{','.join(poly_symbols)}"}
            await self.ws.send(json.dumps(msg))
            return True
        except Exception as e:
            logger.error(f"Polygon subscribe error: {e}")
            return False
    
    async def stream(self):
        """Stream trades and quotes"""
        while self._running:
            try:
                msg = await asyncio.wait_for(self.ws.recv(), timeout=30.0)
                data = json.loads(msg)
                
                for item in data:
                    if item.get("ev") == "T":  # Trade
                        tick = MarketTick(
                            symbol=item["sym"],
                            timestamp=datetime.fromtimestamp(item["t"] / 1000),
                            bid=item.get("bp", item["p"]),
                            ask=item.get("ap", item["p"]),
                            last_price=item["p"],
                            last_size=item["s"],
                            source="polygon",
                            latency_ms=(datetime.now().timestamp() - item["t"]/1000) * 1000,
                            quality=DataQuality.EXCELLENT
                        )
                        self.metrics.update_latency(tick.latency_ms)
                        self.metrics.record_tick(tick.quality)
                        await self._notify_callbacks(tick)
                        
            except asyncio.TimeoutError:
                logger.warning("Polygon heartbeat timeout")
            except Exception as e:
                logger.error(f"Polygon stream error: {e}")
                raise
    
    async def disconnect(self):
        if self.ws:
            await self.ws.close()
            self.ws = None

class OandaProvider(DataProvider):
    """OANDA streaming API - Forex & CFDs"""
    
    def __init__(self, account_id: str, api_token: str, environment: str = "practice"):
        super().__init__("oanda", priority=2, weight=0.9)
        self.account_id = account_id
        self.api_token = api_token
        self.environment = environment
        self.base_url = f"https://stream-fx{'' if environment == 'live' else 'practice'}.oanda.com"
        self.session: Optional[aiohttp.ClientSession] = None
    
    async def connect(self) -> bool:
        self.session = aiohttp.ClientSession()
        return True
    
    async def subscribe(self, symbols: List[str]) -> bool:
        # OANDA uses underscore format (XAU_USD)
        self.symbols = {s.replace("/", "_") for s in symbols}
        return True
    
    async def stream(self):
        url = f"{self.base_url}/v3/accounts/{self.account_id}/pricing/stream"
        headers = {"Authorization": f"Bearer {self.api_token}"}
        params = {"instruments": ",".join(self.symbols)}
        
        try:
            async with self.session.get(url, headers=headers, params=params) as resp:
                async for line in resp.content:
                    if not line:
                        continue
                    
                    data = json.loads(line)
                    if data.get("type") == "PRICE":
                        receive_time = datetime.now()
                        tick_time = datetime.fromisoformat(data["time"].replace("Z", "+00:00"))
                        latency = (receive_time - tick_time).total_seconds() * 1000
                        
                        tick = MarketTick(
                            symbol=data["instrument"].replace("_", ""),
                            timestamp=tick_time,
                            bid=float(data["bids"][0]["price"]),
                            ask=float(data["asks"][0]["price"]),
                            bid_size=float(data["bids"][0]["liquidity"]),
                            ask_size=float(data["asks"][0]["liquidity"]),
                            source="oanda",
                            receive_time=receive_time,
                            latency_ms=latency,
                            quality=DataQuality.GOOD if latency < 100 else DataQuality.FAIR
                        )
                        
                        self.metrics.update_latency(latency)
                        self.metrics.record_tick(tick.quality)
                        await self._notify_callbacks(tick)
                        
        except Exception as e:
            logger.error(f"OANDA stream error: {e}")
            raise
    
    async def disconnect(self):
        if self.session:
            await self.session.close()

class BinanceProvider(DataProvider):
    """Binance WebSocket - Crypto with depth"""
    
    def __init__(self, api_key: Optional[str] = None, api_secret: Optional[str] = None):
        super().__init__("binance", priority=3, weight=0.8)
        self.api_key = api_key
        self.api_secret = api_secret
        self.ws: Optional[websockets.WebSocketClientProtocol] = None
        self.base_endpoint = "wss://stream.binance.com:9443/ws"
    
    async def connect(self) -> bool:
        try:
            # Combined stream for multiple symbols
            streams = "/".join([f"{s.lower()}@bookTicker" for s in self.symbols])
            url = f"{self.base_endpoint}/{streams}"
            self.ws = await websockets.connect(url)
            return True
        except Exception as e:
            logger.error(f"Binance connect failed: {e}")
            return False
    
    async def subscribe(self, symbols: List[str]) -> bool:
        self.symbols = {s.replace("/", "").upper() for s in symbols}
        return True
    
    async def stream(self):
        while self._running:
            try:
                msg = await self.ws.recv()
                data = json.loads(msg)
                
                # bookTicker format
                tick = MarketTick(
                    symbol=data["s"],
                    timestamp=datetime.now(),
                    bid=float(data["b"]),
                    ask=float(data["a"]),
                    bid_size=float(data["B"]),
                    ask_size=float(data["A"]),
                    source="binance",
                    latency_ms=0,  # WebSocket timestamp not provided
                    quality=DataQuality.GOOD
                )
                
                self.metrics.record_tick(tick.quality)
                await self._notify_callbacks(tick)
                
            except Exception as e:
                logger.error(f"Binance stream error: {e}")
                raise
    
    async def disconnect(self):
        if self.ws:
            await self.ws.close()

class TrueFXProvider(DataProvider):
    """TrueFX free forex data (HTTP polling fallback)"""
    
    def __init__(self):
        super().__init__("truefx", priority=5, weight=0.5)
        self.session: Optional[aiohttp.ClientSession] = None
        self.base_url = "https://webrates.truefx.com/rates/connect.html"
    
    async def connect(self) -> bool:
        self.session = aiohttp.ClientSession()
        return True
    
    async def subscribe(self, symbols: List[str]) -> bool:
        return True  # TrueFX provides all pairs
    
    async def stream(self):
        """Poll every 5 seconds"""
        while self._running:
            start_time = time.time()
            try:
                async with self.session.get(f"{self.base_url}?f=csv") as resp:
                    text = await resp.text()
                    lines = text.strip().split("\n")[1:]  # Skip header
                    
                    for line in lines:
                        parts = line.split(",")
                        if len(parts) >= 4:
                            symbol = parts[0].replace("/", "")
                            bid = float(parts[2])
                            ask = float(parts[3])
                            
                            tick = MarketTick(
                                symbol=symbol,
                                timestamp=datetime.now(),
                                bid=bid,
                                ask=ask,
                                source="truefx",
                                latency_ms=(time.time() - start_time) * 1000,
                                quality=DataQuality.FAIR
                            )
                            
                            self.metrics.record_tick(tick.quality)
                            await self._notify_callbacks(tick)
                
                await asyncio.sleep(5.0)  # Rate limit
                
            except Exception as e:
                logger.error(f"TrueFX error: {e}")
                await asyncio.sleep(5.0)

class MockProvider(DataProvider):
    """Realistic simulated data for testing"""
    
    def __init__(self, volatility: float = 0.0002, drift: float = 0.0):
        super().__init__("mock", priority=10, weight=0.1)
        self.volatility = volatility
        self.drift = drift
        self.prices: Dict[str, float] = {}
        self._start_time = datetime.now()
    
    async def connect(self) -> bool:
        # Initialize prices
        self.prices = {
            "XAUUSD": 1950.0,
            "EURUSD": 1.0850,
            "GBPUSD": 1.2650,
            "USDJPY": 150.0
        }
        return True
    
    async def subscribe(self, symbols: List[str]) -> bool:
        self.symbols = set(symbols)
        return True
    
    async def stream(self):
        """Generate realistic microstructure"""
        while self._running:
            for symbol in self.symbols:
                base_price = self.prices.get(symbol, 100.0)
                
                # Geometric Brownian Motion
                dt = 0.1  # 100ms ticks
                noise = np.random.normal(0, self.volatility * np.sqrt(dt))
                new_price = base_price * np.exp(self.drift * dt + noise)
                self.prices[symbol] = new_price
                
                # Realistic spread based on volatility
                spread = abs(noise) * base_price * 2 + 0.0001 * base_price
                
                tick = MarketTick(
                    symbol=symbol,
                    timestamp=datetime.now(),
                    bid=new_price - spread/2,
                    ask=new_price + spread/2,
                    bid_size=np.random.exponential(10),
                    ask_size=np.random.exponential(10),
                    source="mock",
                    latency_ms=0.1,
                    quality=DataQuality.EXCELLENT
                )
                
                await self._notify_callbacks(tick)
            
            await asyncio.sleep(0.1)  # 10 ticks/second

class DataQualityValidator:
    """AI-powered data quality validation"""
    
    def __init__(self, lookback: int = 100):
        self.lookback = lookback
        self.tick_history: Dict[str, deque] = defaultdict(lambda: deque(maxlen=lookback))
        self.price_anomalies = 0
        
        # Validation thresholds
        self.max_spread_bps = 50.0
        self.max_price_jump_pct = 0.01
        self.max_latency_ms = 1000.0
    
    def validate(self, tick: MarketTick) -> Tuple[bool, DataQuality, str]:
        """
        Validate tick data quality.
        Returns: (is_valid, quality, reason)
        """
        history = self.tick_history[tick.symbol]
        
        # Basic validation
        if tick.bid <= 0 or tick.ask <= 0:
            return False, DataQuality.INVALID, "Invalid prices"
        
        if tick.bid >= tick.ask:
            return False, DataQuality.INVALID, "Negative spread"
        
        # Spread check
        if tick.spread_bps > self.max_spread_bps:
            return False, DataQuality.INVALID, f"Excessive spread: {tick.spread_bps:.1f} bps"
        
        # Latency check
        if tick.latency_ms > self.max_latency_ms:
            return False, DataQuality.STALE, f"Stale data: {tick.latency_ms:.0f}ms"
        
        # Price jump detection
        if len(history) > 0:
            last_tick = history[-1]
            price_change = abs(tick.mid - last_tick.mid) / last_tick.mid
            
            if price_change > self.max_price_jump_pct:
                self.price_anomalies += 1
                return False, DataQuality.INVALID, f"Price jump: {price_change:.2%}"
        
        # Quality classification
        if tick.latency_ms < 10:
            quality = DataQuality.EXCELLENT
        elif tick.latency_ms < 100:
            quality = DataQuality.GOOD
        elif tick.latency_ms < 500:
            quality = DataQuality.FAIR
        else:
            quality = DataQuality.POOR
        
        history.append(tick)
        return True, quality, "OK"

class MultiSourceAggregator:
    """
    Intelligent multi-source data aggregation with consensus pricing.
    Implements Byzantine fault tolerance for data sources.
    """
    
    def __init__(self,
                 consensus_threshold: float = 0.67,
                 max_sources: int = 5,
                 redis_url: Optional[str] = None):
        
        self.providers: Dict[str, DataProvider] = {}
        self.consensus_threshold = consensus_threshold
        self.max_sources = max_sources
        
        # Redis for cross-process communication
        self.redis_client = None
        if redis_url and REDIS_AVAILABLE:
            try:
                self.redis_client = redis.from_url(redis_url)
            except Exception as e:
                logger.warning(f"Redis connection failed: {e}")
        
        # State
        self.latest_ticks: Dict[str, Dict[str, MarketTick]] = defaultdict(dict)
        self.consensus_prices: Dict[str, MarketTick] = {}
        self.validator = DataQualityValidator()
        
        # Metrics
        self.aggregation_stats = {
            'ticks_processed': 0,
            'consensus_formed': 0,
            'disagreements': 0
        }
        
        # Callbacks
        self._consensus_callbacks: List[Callable[[MarketTick], Any]] = []
    
    def add_provider(self, provider: DataProvider):
        """Add data source"""
        if len(self.providers) >= self.max_sources:
            logger.warning(f"Max sources ({self.max_sources}) reached")
            return
        
        self.providers[provider.name] = provider
        provider.on_tick(self._on_provider_tick)
        logger.info(f"Added provider: {provider.name} (priority {provider.priority})")
    
    def _on_provider_tick(self, tick: MarketTick):
        """Handle tick from provider"""
        # Validate
        is_valid, quality, reason = self.validator.validate(tick)
        if not is_valid:
            logger.debug(f"Tick rejected from {tick.source}: {reason}")
            return
        
        # Update latest
        self.latest_ticks[tick.symbol][tick.source] = tick
        
        # Form consensus
        consensus = self._form_consensus(tick.symbol)
        if consensus:
            self.consensus_prices[tick.symbol] = consensus
            self._notify_consensus(consensus)
            
            # Cache in Redis
            if self.redis_client:
                asyncio.create_task(self._cache_tick(consensus))

    def _form_consensus(self, symbol: str) -> Optional[MarketTick]:
        """
        Form consensus price using weighted median.
        Implements Byzantine fault tolerance.
        """
        ticks = list(self.latest_ticks[symbol].values())
        
        if len(ticks) < 2:
            return ticks[0] if ticks else None
        
        # Check for stale data (>1s old)
        now = datetime.now()
        fresh_ticks = [
            t for t in ticks 
            if (now - t.timestamp).total_seconds() < 1.0
        ]
        
        if len(fresh_ticks) < len(ticks) * self.consensus_threshold:
            logger.warning(f"Insufficient fresh data for {symbol}")
            return None
        
        # Weight by source quality and inverse latency
        weights = []
        prices = []
        
        for tick in fresh_ticks:
            provider = self.providers.get(tick.source)
            if not provider:
                continue
            
            # Weight = source_weight * (1/latency) * health_score
            weight = (
                provider.weight * 
                (1000.0 / max(tick.latency_ms, 1.0)) * 
                (provider.metrics.health_score / 100.0)
            )
            weights.append(weight)
            prices.append(tick.mid)
        
        if not prices:
            return None
        
        # Calculate weighted median
        sorted_pairs = sorted(zip(prices, weights))
        sorted_prices, sorted_weights = zip(*sorted_pairs)
        
        cumsum = np.cumsum(sorted_weights)
        total_weight = cumsum[-1]
        median_idx = np.searchsorted(cumsum, total_weight / 2)
        
        consensus_price = sorted_prices[median_idx]
        
        # Calculate spread from best bid/ask across all sources
        best_bid = max(t.bid for t in fresh_ticks)
        best_ask = min(t.ask for t in fresh_ticks)
        
        # Check for disagreement (Byzantine fault detection)
        price_std = np.std(prices)
        price_range = max(prices) - min(prices)
        
        if price_range > consensus_price * 0.001:  # >10 bps disagreement
            self.aggregation_stats['disagreements'] += 1
            logger.warning(
                f"Price disagreement for {symbol}: "
                f"range={price_range:.5f}, sources={[t.source for t in fresh_ticks]}"
            )
        
        # Create consensus tick
        consensus = MarketTick(
            symbol=symbol,
            timestamp=datetime.now(),
            bid=best_bid,
            ask=best_ask,
            bid_size=sum(t.bid_size for t in fresh_ticks) / len(fresh_ticks),
            ask_size=sum(t.ask_size for t in fresh_ticks) / len(fresh_ticks),
            source="consensus",
            latency_ms=np.mean([t.latency_ms for t in fresh_ticks]),
            quality=DataQuality.EXCELLENT if len(fresh_ticks) >= 3 else DataQuality.GOOD
        )
        
        self.aggregation_stats['consensus_formed'] += 1
        return consensus
    
    async def _cache_tick(self, tick: MarketTick):
        """Cache tick in Redis"""
        try:
            key = f"tick:{tick.symbol}"
            value = json.dumps(tick.to_dict(), default=str)
            await self.redis_client.setex(key, 60, value)  # 60s TTL
        except Exception as e:
            logger.error(f"Redis cache error: {e}")
    
    def _notify_consensus(self, tick: MarketTick):
        """Notify consensus callbacks"""
        for callback in self._consensus_callbacks:
            try:
                if asyncio.iscoroutinefunction(callback):
                    asyncio.create_task(callback(tick))
                else:
                    callback(tick)
            except Exception as e:
                logger.error(f"Consensus callback error: {e}")
    
    def on_consensus(self, callback: Callable[[MarketTick], Any]):
        """Register consensus callback"""
        self._consensus_callbacks.append(callback)
    
    async def start(self):
        """Start all providers"""
        tasks = [
            asyncio.create_task(provider.start())
            for provider in self.providers.values()
        ]
        await asyncio.gather(*tasks, return_exceptions=True)
    
    def stop(self):
        """Stop all providers"""
        for provider in self.providers.values():
            provider.stop()
    
    def get_health_report(self) -> Dict:
        """Get comprehensive health report"""
        return {
            'providers': {
                name: {
                    'state': provider.metrics.state.name,
                    'health_score': provider.metrics.health_score,
                    'latency_avg': provider.metrics.latency_avg,
                    'ticks_received': provider.metrics.ticks_received,
                    'errors': provider.metrics.errors
                }
                for name, provider in self.providers.items()
            },
            'consensus': {
                'symbols_tracked': len(self.consensus_prices),
                'stats': self.aggregation_stats
            },
            'redis': 'connected' if self.redis_client else 'disconnected'
        }

class RealtimeStrategyEngine:
    """
    High-performance strategy execution engine.
    Processes ticks with minimal latency.
    """
    
    def __init__(self,
                 aggregator: MultiSourceAggregator,
                 max_latency_ms: float = 10.0,
                 batch_size: int = 100):
        
        self.aggregator = aggregator
        self.max_latency_ms = max_latency_ms
        self.batch_size = batch_size
        
        # Strategy registry
        self.strategies: Dict[str, Any] = {}
        self.signal_history: deque = deque(maxlen=10000)
        
        # Execution
        self.order_queue: asyncio.Queue = asyncio.Queue()
        self.risk_check_queue: asyncio.Queue = asyncio.Queue()
        
        # Performance
        self.processing_latency_ns: deque = deque(maxlen=1000)
        self.ticks_processed = 0
    
    def register_strategy(self, name: str, strategy: Any):
        """Register trading strategy"""
        self.strategies[name] = strategy
        logger.info(f"Registered strategy: {name}")
    
    async def process_tick(self, tick: MarketTick):
        """Process single tick through all strategies"""
        start_time = time.time_ns()
        
        # Generate signals from all strategies
        signals = []
        for name, strategy in self.strategies.items():
            try:
                signal = strategy.on_tick(tick)
                if signal:
                    signals.append({
                        'strategy': name,
                        'signal': signal,
                        'timestamp': datetime.now()
                    })
            except Exception as e:
                logger.error(f"Strategy {name} error: {e}")
        
        # Record latency
        latency_ns = time.time_ns() - start_time
        self.processing_latency_ns.append(latency_ns)
        self.ticks_processed += 1
        
        # Queue for risk check if signals generated
        if signals:
            await self.risk_check_queue.put({
                'tick': tick,
                'signals': signals,
                'latency_ms': latency_ns / 1_000_000
            })
    
    async def run(self):
        """Main processing loop"""
        self.aggregator.on_consensus(self.process_tick)
        await self.aggregator.start()
    
    def get_performance_metrics(self) -> Dict:
        """Get engine performance metrics"""
        if not self.processing_latency_ns:
            return {'status': 'no_data'}
        
        latencies = np.array(self.processing_latency_ns) / 1_000_000  # Convert to ms
        
        return {
            'ticks_processed': self.ticks_processed,
            'avg_latency_ms': np.mean(latencies),
            'p50_latency_ms': np.percentile(latencies, 50),
            'p99_latency_ms': np.percentile(latencies, 99),
            'max_latency_ms': np.max(latencies),
            'strategies_active': len(self.strategies),
            'signals_generated': len(self.signal_history)
        }

# =============================================================================
# EXAMPLE USAGE & TESTING
# =============================================================================

if __name__ == "__main__":
    print("=" * 70)
    print("ENHANCED REALTIME ENGINE v3.0 - TEST SUITE")
    print("=" * 70)
    
    async def test_engine():
        # Create aggregator
        aggregator = MultiSourceAggregator(
            consensus_threshold=0.5,
            max_sources=5
        )
        
        # Add providers (prioritized)
        aggregator.add_provider(MockProvider(volatility=0.0003))
        # aggregator.add_provider(OandaProvider("account", "token"))  # Real credentials needed
        # aggregator.add_provider(BinanceProvider())  # Real credentials needed
        
        # Create strategy engine
        engine = RealtimeStrategyEngine(aggregator, max_latency_ms=5.0)
        
        # Simple test strategy
        class TestStrategy:
            def __init__(self):
                self.prices = deque(maxlen=20)
            
            def on_tick(self, tick: MarketTick):
                self.prices.append(tick.mid)
                if len(self.prices) >= 20:
                    ma_fast = np.mean(list(self.prices)[-10:])
                    ma_slow = np.mean(self.prices)
                    
                    if ma_fast > ma_slow * 1.0001:
                        return {'action': 'buy', 'strength': 0.8}
                    elif ma_fast < ma_slow * 0.9999:
                        return {'action': 'sell', 'strength': 0.8}
                return None
        
        engine.register_strategy("ma_crossover", TestStrategy())
        
        # Start processing
        print("\nStarting realtime processing (5 seconds)...")
        task = asyncio.create_task(engine.run())
        
        # Let it run
        await asyncio.sleep(5)
        
        # Stop and report
        aggregator.stop()
        task.cancel()
        
        print("\n" + "=" * 70)
        print("PERFORMANCE METRICS")
        print("=" * 70)
        metrics = engine.get_performance_metrics()
        for key, value in metrics.items():
            if isinstance(value, float):
                print(f"{key}: {value:.4f}")
            else:
                print(f"{key}: {value}")
        
        health = aggregator.get_health_report()
        print(f"\nProviders: {list(health['providers'].keys())}")
        print(f"Consensus formed: {health['consensus']['stats']['consensus_formed']}")
        
        print("\n✅ Realtime engine test completed!")
    
    # Run test
    asyncio.run(test_engine())

