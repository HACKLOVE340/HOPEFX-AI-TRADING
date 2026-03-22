# market_data/feed_handler.py
"""
HOPEFX Market Data Feed Handler
Ultra-low latency tick processing with normalization
"""

import asyncio
from typing import Dict, List, Callable, Optional, Set
from dataclasses import dataclass
from datetime import datetime
from collections import deque
import struct
import numpy as np


@dataclass
class Tick:
    """Normalized market tick"""
    symbol: str
    timestamp: datetime
    bid: float
    ask: float
    bid_size: float
    ask_size: float
    last_price: float
    last_size: float
    exchange: str
    is_trade: bool = False  # True if this is a trade, False if quote
    
    @property
    def mid(self) -> float:
        return (self.bid + self.ask) / 2 if self.bid > 0 and self.ask > 0 else self.last_price
    
    @property
    def spread(self) -> float:
        return self.ask - self.bid if self.bid > 0 and self.ask > 0 else 0


class FeedHandler:
    """
    Normalizes feeds from multiple exchanges into unified tick stream.
    """
    
    def __init__(self):
        self.exchanges: Dict[str, 'ExchangeFeed'] = {}
        self.normalized_callbacks: List[Callable[[Tick], None]] = []
        self.symbol_subscriptions: Set[str] = set()
        self.tick_buffer: deque = deque(maxlen=10000)
        self.stats = {
            'ticks_processed': 0,
            'ticks_per_second': 0.0,
            'latency_ns': 0
        }
    
    def add_exchange(self, name: str, feed: 'ExchangeFeed'):
        """Add exchange feed"""
        self.exchanges[name] = feed
        feed.set_callback(self._on_exchange_tick)
    
    def subscribe(self, symbols: List[str]):
        """Subscribe to symbols"""
        self.symbol_subscriptions.update(symbols)
        for exchange in self.exchanges.values():
            exchange.subscribe(symbols)
    
    def _on_exchange_tick(self, raw_data: Dict, exchange_name: str):
        """Process raw tick from exchange"""
        start_ns = datetime.utcnow().timestamp() * 1e9
        
        # Normalize to common format
        tick = self._normalize(raw_data, exchange_name)
        
        if tick.symbol not in self.symbol_subscriptions:
            return
        
        # Store
        self.tick_buffer.append(tick)
        
        # Calculate latency
        latency_ns = datetime.utcnow().timestamp() * 1e9 - start_ns
        self.stats['latency_ns'] = 0.9 * self.stats['latency_ns'] + 0.1 * latency_ns
        
        # Distribute
        for callback in self.normalized_callbacks:
            try:
                callback(tick)
            except Exception as e:
                print(f"Tick callback error: {e}")
        
        self.stats['ticks_processed'] += 1
    
    def _normalize(self, raw: Dict, exchange: str) -> Tick:
        """Normalize exchange-specific format to Tick"""
        # Exchange-specific parsing
        parsers = {
            'oanda': self._parse_oanda,
            'binance': self._parse_binance,
            'coinbase': self._parse_coinbase
        }
        
        parser = parsers.get(exchange, self._parse_generic)
        return parser(raw, exchange)
    
    def _parse_oanda(self, raw: Dict, exchange: str) -> Tick:
        return Tick(
            symbol=raw.get('instrument', '').replace('_', ''),
            timestamp=datetime.utcnow(),
            bid=float(raw.get('bids', [{}])[0].get('price', 0)),
            ask=float(raw.get('asks', [{}])[0].get('price', 0)),
            bid_size=float(raw.get('bids', [{}])[0].get('liquidity', 0)),
            ask_size=float(raw.get('asks', [{}])[0].get('liquidity', 0)),
            last_price=(float(raw.get('bids', [{}])[0].get('price', 0)) + 
                       float(raw.get('asks', [{}])[0].get('price', 0))) / 2,
            last_size=0,
            exchange=exchange
        )
    
    def _parse_binance(self, raw: Dict, exchange: str) -> Tick:
        return Tick(
            symbol=raw.get('s', ''),
            timestamp=datetime.fromtimestamp(raw.get('E', 0) / 1000),
            bid=float(raw.get('b', 0)),
            ask=float(raw.get('a', 0)),
            bid_size=float(raw.get('B', 0)),
            ask_size=float(raw.get('A', 0)),
            last_price=float(raw.get('c', 0)),
            last_size=float(raw.get('v', 0)),
            exchange=exchange,
            is_trade=raw.get('e') == 'trade'
        )
    
    def _parse_coinbase(self, raw: Dict, exchange: str) -> Tick:
        # Coinbase Pro format
        return Tick(
            symbol=raw.get('product_id', '').replace('-', ''),
            timestamp=datetime.fromisoformat(raw.get('time', '').replace('Z', '+00:00')),
            bid=float(raw.get('best_bid', 0)),
            ask=float(raw.get('best_ask', 0)),
            bid_size=float(raw.get('bid_size', 0)),
            ask_size=float(raw.get('ask_size', 0)),
            last_price=float(raw.get('price', 0)),
            last_size=float(raw.get('last_size', 0)),
            exchange=exchange,
            is_trade=raw.get('type') == 'match'
        )
    
    def _parse_generic(self, raw: Dict, exchange: str) -> Tick:
        return Tick(
            symbol=str(raw.get('symbol', '')),
            timestamp=datetime.utcnow(),
            bid=float(raw.get('bid', 0)),
            ask=float(raw.get('ask', 0)),
            bid_size=float(raw.get('bidSize', 0)),
            ask_size=float(raw.get('askSize', 0)),
            last_price=float(raw.get('price', 0)),
            last_size=float(raw.get('size', 0)),
            exchange=exchange
        )
    
    def on_tick(self, callback: Callable[[Tick], None]):
        """Register tick callback"""
        self.normalized_callbacks.append(callback)
    
    def get_l1_book(self, symbol: str) -> Optional[Tick]:
        """Get current L1 quote for symbol"""
        for tick in reversed(self.tick_buffer):
            if tick.symbol == symbol and not tick.is_trade:
                return tick
        return None
    
    def get_recent_trades(self, symbol: str, n: int = 100) -> List[Tick]:
        """Get recent trades for symbol"""
        return [
            tick for tick in self.tick_buffer 
            if tick.symbol == symbol and tick.is_trade
        ][-n:]


class ExchangeFeed:
    """Base class for exchange-specific feeds"""
    
    def __init__(self, name: str, ws_url: str):
        self.name = name
        self.ws_url = ws_url
        self.callback: Optional[Callable] = None
        self.subscribed_symbols: Set[str] = set()
        self.connected = False
    
    def set_callback(self, callback: Callable[[Dict, str], None]):
        self.callback = callback
    
    def subscribe(self, symbols: List[str]):
        self.subscribed_symbols.update(symbols)
    
    async def connect(self):
        """Connect to WebSocket feed"""
        import aiohttp
        
        self.session = aiohttp.ClientSession()
        self.ws = await self.session.ws_connect(self.ws_url)
        self.connected = True
        
        # Send subscription
        await self._send_subscription()
        
        # Start receive loop
        asyncio.create_task(self._receive_loop())
    
    async def _send_subscription(self):
        """Send subscription message"""
        # Override in subclass
        pass
    
    async def _receive_loop(self):
        """Receive and process messages"""
        while self.connected:
            try:
                msg = await self.ws.receive()
                
                if msg.type == aiohttp.WSMsgType.TEXT:
                    data = json.loads(msg.data)
                    if self.callback:
                        self.callback(data, self.name)
                
                elif msg.type == aiohttp.WSMsgType.CLOSED:
                    break
                    
            except Exception as e:
                print(f"Feed error: {e}")
                await asyncio.sleep(1)
        
        # Reconnect
        self.connected = False
        await asyncio.sleep(5)
        await self.connect()
