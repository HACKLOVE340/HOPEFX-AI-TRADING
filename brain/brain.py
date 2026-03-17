# brain/brain.py
import asyncio
import logging
import time
from typing import Dict, Any, Optional
from dataclasses import dataclass

from ml.online_learner import OnlineLearner
from risk.manager import RiskManager
from execution.oms import OrderManagementSystem
from strategies.manager import StrategyManager
from cache.market_data_cache import MarketDataCache
from data.time_and_sales import get_time_and_sales_service
from notifications.alert_engine import AlertEngine  # if exists, else stub

logger = logging.getLogger(__name__)

@dataclass
class Decision:
    action: str
    size: float
    confidence: float
    reason: str
    timestamp: str
    override: bool = False  # for emergency flatten

class HOPEFXBrain:
    """Omniscient core: sees every tick, model, risk, trade—commands all."""
    def __init__(self):
        self.learner: Optional = None
        self.risk: Optional = None
        self.oms: Optional = None
        self.strategies: Optional = None
        self.cache = MarketDataCache()
        self.tas = get_time_and_sales_service()
        self.alerts = AlertEngine() if 'AlertEngine' in globals() else None
        self.running = False
        self.state: Dict =  # live snapshot
        self.health: Dict =  # module status

    async def awaken(self):
        """Boot + self-diagnose: load everything, report weak links."""
        try:
            self.learner = OnlineLearner()
            self.risk = RiskManager()
            self.oms = OrderManagementSystem()
            self.strategies = StrategyManager()
            self.health = {
                "learner": True, "risk": True, "oms": True, "strategies": True,
                "cache": await self.cache.ping(), "tas": True
            }
            logger.critical("Brain: All modules loaded. I am awake.")
        except Exception as e:
            logger.fatal(f"Brain boot error: {e} — emergency mode: rules only")
            self.health = False

    async def watch(self):
        """Infinite loop: pulse every 2s, update state, heal if needed."""
        while self.running:
            try:
                price = await self.cache.get("live:XAUUSD=X") or {"price": 0}
                current_price = price.get("price", 0)
                pred = self.learner.predict(current_price) if self.learner else current_price + 0.05
                risk_safe = self.risk.check() if self.risk else True
                last_trade = self.tas.get_latest() or                strat_count = len(self.strategies.active) if self.strategies else 0

                self.state = {
                    "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
                    "price": current_price,
                    "prediction": pred,
                    "risk_safe": risk_safe,
                    "last_trade": last_trade,
                    "active_strats": strat_count,
                    "drawdown": self.risk.get_drawdown() if self.risk else 0
                }

                # Auto-heal: if learner stalls, reset buffer
                if self.learner and self.learner.buffer_full():
                    self.learner.replay()

                await asyncio.sleep(2)
            except Exception as e:
                logger.warning(f"Watch failed: {e} — retrying...")
                await asyncio.sleep(5)

    def command(self, trigger: str = "tick") -> Decision:
        """Ultimate verdict: full context → action."""
        if not self.state:
            return Decision("hold", 0, 0.1, "No state", "")

                p = self.state pred = self.state conf = 0.92 if abs(pred - p) > 0.08 else 0.58
        risk_ok = self.state action = (
            "buy" if pred > p + 0.06 and risk_ok else
            "sell" if pred < p - 0.06 and risk_ok else
            "hold"
        )
        )

        size = 0.4 if conf > 0.8 else 0.15 if conf > 0.6 else 0
        reason = f"Pred {pred:.2f} vs {p:.2f} | Risk: {risk_ok} | Strats: {self.state }"

        # Emergency override: high drawdown → flatten
                if self.state > 0.08:
            return Decision("flatten", 0, 1.0, "Drawdown alert - flatten", "", override=True)

        return Decision(action, size, conf, reason, "")

    async def enforce(self, decision: Decision):
        """Execute + alert if needed."""
        if decision.action == "hold":
            return
        try:
            await self.oms.place("XAUUSD", decision.action, decision.size)
            if self.alerts:
                await self.alerts.send(f"Brain executed: {decision.action} {decision.size}")
            logger.info(f"Brain: {decision}")
        except Exception as e:
            logger.error(f"Enforce fail: {e}")
            if self.alerts:
                await self.alerts.send("Execution failed - check OMS")

    async def dominate(self):
        self.running = True
        await self.awaken()
        asyncio.create_task(self.watch())
        logger.info("Brain: Dominating. All yours.")

    def sleep(self):
        self.running = False
        logger.info("Brain: Resting. Wake me when needed.")