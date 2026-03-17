# brain/brain.py - Ultimate HOPEFX Brain (enhanced 2026)
import asyncio
import logging
import time
from typing import Dict, Any, Optional
from dataclasses import dataclass

# Core imports - graceful
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
except: get_gold_geopolitical_signal = lambda: 0  # fallback

logger = logging.getLogger(__name__)

@dataclass
class Decision:
    action: str = "hold"
    size: float = 0.0
    confidence: float = 0.0
    reason: str = ""
    timestamp: str = ""
    override: bool = False

class HOPEFXBrain:
    """Central brain: full visibility, smart decisions, self-healing."""
    def __init__(self):
        self.learner = OnlineLearner() if OnlineLearner else None
        self.risk = RiskManager() if RiskManager else None
        self.oms = OrderManagementSystem() if OrderManagementSystem else None
        self.strategies = StrategyManager() if StrategyManager else None
        self.cache = MarketDataCache() if MarketDataCache else None
        self.tas = get_time_and_sales_service()
        self.running = False
        self.state: Dict =  # live snapshot
        self.health: Dict =  # module status

    async def awaken(self):
        """Boot + diagnose all modules."""
        try:
            self.health = {
                "learner": bool(self.learner),
                "risk": bool(self.risk),
                "oms": bool(self.oms),
                "strategies": bool(self.strategies),
                "cache": self.cache.ping() if self.cache else False,
                "tas": bool(self.tas),
                "news": True  # geo always fallback
            }
            logger.info("Brain awake. Modules: " + ", ".join( ))
        except Exception as e:
            logger.critical(f"Boot fail: {e} - rules-only mode")

    async def watch(self):
        """Heartbeat: update state every 2s, heal if stuck."""
        while self.running:
            try:
                price_data = await self.cache.get("live:XAUUSD=X") if self.cache else {"price": 0}
                p = price_data.get("price", 0)
                pred = self.learner.predict(p) if self.learner else p + 0.05
                risk_safe = self.risk.check() if self.risk else True
                tas_latest = self.tas.get_latest() if self.tas else                strat_count = len(self.strategies.active) if self.strategies else 0
                drawdown = self.risk.get_drawdown() if self.risk else 0

                self.state = {
                    "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
                    "price": p,
                    "prediction": pred,
                    "risk_safe": risk_safe,
                    "last_trade": tas_latest,
                    "active_strats": strat_count,
                    "drawdown": drawdown
                }

                # Heal: replay learner if stalled
                if self.learner and len(self.learner.buffer) < 10:
                    self.learner.replay()

                await asyncio.sleep(2)
            except Exception as e:
                logger.warning(f"Watch fail: {e}")
                await asyncio.sleep(5)

    def command(self, trigger: str = "tick") -> Decision:
        """Core: full context → smart decision."""
        if not self.state:
            return Decision(reason="No data")

        p = self.state["price"]
        pred = self.state conf = 0.92 if abs(pred - p) > 0.08 else 0.58
        risk_ok = self.state drawdown = self.state["drawdown"]

        # Geo filter - real news
        geo = get_gold_geopolitical_signal()
        geo_reason = f" | Geo risk: {geo}%"

        action = "hold"
        if geo > 70:
            action = "hold"
            reason = f"High geo risk ({geo}%) - hold"
        elif drawdown > 0.08:
            action = "flatten"
            reason = "Drawdown alert - flatten"
        else:
            action = (
                "buy" if pred > p + 0.06 and risk_ok else
                "sell" if pred < p - 0.06 and risk_ok else
                "hold"
            )
            reason = f"Pred {pred:.2f} vs {p:.2f} | Risk: {risk_ok} | Conf: {conf:.2f}{geo_reason}"

        size = 0.4 if conf > 0.8 else 0.15 if conf > 0.6 else 0
        return Decision(action, size, conf, reason, self.state )

    async def enforce(self, decision: Decision):
        """Execute + log + alert."""
        if decision.action == "hold":
            return
        try:
            await self.oms.place_order("XAUUSD", decision.action, decision.size)
            logger.info(f"EXEC: {decision.action} {decision.size} - {decision.reason}")
        except Exception as e:
            logger.error(f"Exec fail: {e}")

    async def dominate(self):
        self.running = True
        await self.awaken()
        asyncio.create_task(self.watch())
        logger.info("Brain dominating - full control.")

    def shutdown(self):
        self.running = False
        logger.info("Brain offline.")