# data/real_time_price_engine.py (enhanced v2 - 2026 god-mode)
import asyncio
import logging
import threading
import time
from datetime import datetime, timezone
from typing import Dict, Optional, Callable, List
import json

try:
    import yfinance as yf
except ImportError:
    yf = None

try:
    import redis
except ImportError:
    redis = None

from data.time_and_sales import TimeAndSalesService, ExecutedTrade
from brain.brain import HOPEFXBrain  # <--- NEW: brain integration

logger = logging.getLogger(__name__)

class RealTimePriceEngine:
    def __init__(self, poll_interval=3.0, ticker="GC=F", symbol="XAUUSD"):
        self.ticker = ticker
        self.symbol = symbol
        self.interval = poll_interval
        self.running = False
        self._tas = TimeAndSalesService()
        self._redis = self._connect_redis() if redis else None
        self._brain = None  # lazy load brain
        self._callbacks = []  # price callbacks
        self._latest = None
        self._thread = None

    def _connect_redis(self):
        try:
            r = redis.Redis(host='localhost', port=6379, db=0, decode_responses=True)
            r.ping()
            return r
        except:
            logger.warning("Redis down—using memory only")
            return None

    def _load_brain(self):
        if not self._brain:
            try:
                self._brain = HOPEFXBrain()
                asyncio.create_task(self._brain.dominate())
                logger.info("Brain linked—now decides on every tick!")
            except:
                logger.error("Brain load failed—fallback to dumb mode")

    async def start(self):
        self.running = True
        self._load_brain()  # wire brain once
        self._thread = threading.Thread(target=self._poll, daemon=True)
        self._thread.start()
        logger.info("Engine roaring—XAUUSD live!")

    def stop(self):
        self.running = False
        if self._thread:
            self._thread.join(timeout=5)

    def _poll(self):
        while self.running:
            tick = self._fetch()
            if tick:
                self._latest = tick
                trade = self._tas.add_trade(
                    self.symbol, tick , 50, "buy" if tick > 0 else "sell",
                    tick )
                self._store(tick)
                self._notify(tick, trade)
                if self._brain:
                    decision = self._brain.command("tick")  # brain sees this tick!
                    asyncio.run(self._brain.enforce(decision))  # auto-execute
            time.sleep(self.interval)

    def _fetch(self):
        if not yf:
            return {'last': 1950 + time.time() % 100, 'change': 0.5, 'timestamp': datetime.now(timezone.utc)}
        try:
            data = yf.Ticker(self.ticker).info
            return {
                'last': data.get('regularMarketPrice', 1950),
                'change': data.get('regularMarketChange', 0),
                'timestamp': datetime.now(timezone.utc)
            }
        
    def _store(self, tick):
        if self._redis:
            self._redis.set(f"live:{self.symbol}", json.dumps(tick))

    def _notify(self, tick, trade):
        for cb in self._callbacks:
            cb(tick, trade)

    def register_callback(self, cb):
        self._callbacks.append(cb)

    def get_latest(self):
        return self._latest