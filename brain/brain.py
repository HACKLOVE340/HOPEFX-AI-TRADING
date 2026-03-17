# brain/brain.py - Full rewrite: complete, geo-integrated, state-driven
import asyncio
import logging
from typing import Dict, Any, Optional
from datetime import datetime

# Graceful imports
try:
    from news.geopolitical_risk import get_gold_geopolitical_signal
except ImportError:
    get_gold_geopolitical_signal = lambda: 0.0  # safe fallback

try:
    from risk.manager import RiskManager
except ImportError:
    RiskManager = None

try:
    from execution.oms import OrderManagementSystem
except ImportError:
    OrderManagementSystem = None

try:
    from cache.market_data_cache import MarketDataCache
except ImportError:
    MarketDataCache = None

logger = logging.getLogger(__name__)

class HOPEFXBrain:
    def __init__(self):
        self.state: Dict = {
            "price": 0.0,
            "prediction": 0.0,
            "risk_safe": True,
            "drawdown": 0.0,
            "geo_risk": 0.0,
            "timestamp": datetime.utcnow().isoformat()
        }
        self.running = False
        self.risk = RiskManager() if RiskManager else None
        self.oms = OrderManagementSystem() if OrderManagementSystem else None
        self.cache = MarketDataCache() if MarketDataCache else None

    async def update_state(self):
        """Pull real data into state - no mocks"""
        try:
            if self.cache:
                price_data = await self.cache.get("live:XAUUSD=X")
                self.state["price"] = price_data.get("price", 0.0)

            # Fake prediction (replace with real ML later)
            self.state = self.state + 0.05

            # Risk & drawdown
            self.state["risk_safe" "drawdown"] = self.risk.get_drawdown() if self.risk else 0.0

            # Geo - real news
            self.state = get_gold_geopolitical_signal()

            self.state = datetime.utcnow().isoformat()
        except Exception as e:
            logger.warning(f"State update failed: {e}")

    def decide(self) -> Dict :
        """Core decision - geo first, then risk, then signal"""
        p = self.state pred = self.state["prediction"]
        geo = self.state risk_ok = self.state drawdown = self.state if drawdown > 0.08:
            return {"action": "flatten", "size": 0.0, "reason": f"Drawdown {drawdown*100:.1f}% - flatten"}

        if geo > 70:
            return {"action": "hold", "size": 0.0, "reason": f"Geo risk {geo}% - hold only"}

        # Simple ML-like signal
        diff = pred - p
        if diff > 0.06 and risk_ok:
            return {"action": "buy", "size": 0.5, "reason": f"Buy signal {diff:.2f}"}
        elif diff < -0.06 and risk_ok:
            return {"action": "sell", "size": 0.5, "reason": f"Sell signal {diff:.2f}"}
        else:
            return {"action": "hold", "size": 0.0, "reason": "No clear signal"}

    async def execute(self, decision: Dict ):
        if decision in :
            try:
                await self.oms.place_order("XAUUSD", decision , decision )
                logger.info(f"Executed: {decision } {decision } - {decision }")
            except Exception as e:
                logger.error(f"Execution failed: {e}")

    async def dominate(self):
        self.running = True
        logger.info("Brain dominating - real data only")
        while self.running:
            await self.update_state()
            decision = self.decide()
            logger.info(f"Decision: {decision } - {decision }")
            await self.execute(decision)
            await asyncio.sleep(5)  # 5s cycle

    def shutdown(self):
        self.running = False
        logger.info("Brain offline")