# brain/brain.py - God-tier rewrite (full visibility, no randoms, geo-locked)
import asyncio
import logging
import time
from typing import Dict, Any, Optional
from dataclasses import dataclass
from datetime import datetime

try: from ml.online_learner import OnlineLearner
except: OnlineLearner = None

try: from risk.manager import RiskManager
except: RiskManager = None

try: from execution.oms import OrderManagementSystem
except: OrderManagementSystem = None

try: from strategies.manager import StrategyManager
except: StrategyManager = None

try: from cache.market_data_cache import MarketDataCache
except: MarketDataCache = None

try: from data.time_and_sales import get_time_and_sales_service
except: get_time_and_sales_service = lambda: None

try: from news.geopolitical_risk import get_gold_geopolitical_signal
except: get_gold_geopolitical_signal = lambda: 0.0

logger = logging.getLogger(__name__)

@dataclass
class Decision:
    action: str
    size: float = 0.0
    confidence: float = 0.0
    reason: str = ""
    timestamp: str = ""

class HOPEFXBrain:
    def __init__(self):
        self.learner = OnlineLearner() if OnlineLearner else None
        self.risk = RiskManager() if RiskManager else None
        self.oms = OrderManagementSystem() if OrderManagementSystem else None
        self.strategies = StrategyManager() if StrategyManager else None
        self.cache = MarketDataCache() if MarketDataCache else None
        self.tas = get_time_and_sales_service()
        self.running = False
        self.state =
    async def awaken(self):
        self.state = {"price": 0, "prediction": 0, "risk_safe": True, "drawdown": 0, "geo": 0}
        logger.info("Brain online - watching everything.")

    async def watch(self):
        while self.running:
            try:
                p_data = await self.cache.get("live:XAUUSD=X") if self.cache else {"price": 0}
                p = p_data.get("price", 0)
                pred = self.learner.predict(p) if self.learner else p + 0.05
                geo = get_gold_geopolitical_signal()
                self.state.update({
                    "price": p, "prediction": pred, "geo": geo,
                    "risk_safe": self.risk.check() if self.risk else True,
                    "drawdown": self.risk.get_drawdown() if self.risk else 0,
                    "velocity": self.tas.get_trade_velocity("XAUUSD").to_dict() if self.tas else                })
                await asyncio.sleep(2)
            except:
                await asyncio.sleep(5)

    def command(self, trigger="tick") -> Decision:
        if not self.state: return Decision("hold", reason="No data")

        p = self.state["price" "risk_safe"]
        drawdown = self.state if drawdown > 0.08:
            return Decision("flatten", reason="Emergency flatten - drawdown >8%")

        if geo > 70:
            return Decision("hold", reason=f"Geo risk {geo}% - no trade")

        conf = 0.92 if abs(pred - p) > 0.08 else 0.58
        action = (
            "buy" if pred > p + 0.06 and risk_ok else
            "sell" if pred < p - 0.06 and risk_ok else
            "hold"
        )
        size = 0.5 if conf > 0.8 else 0.2 if conf > 0.6 else 0.0

        return Decision(action, size, conf, f"{action.upper()} - conf {conf:.2f} | geo {geo}%", datetime.utcnow().isoformat())

    async def dominate(self):
        self.running = True
        await self.awaken()
        asyncio.create_task(self.watch())
        while self.running:
            dec = self.command()
            await self.enforce(dec)
            await asyncio.sleep(5)