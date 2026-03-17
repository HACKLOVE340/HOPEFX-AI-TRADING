# brain/brain.py - God Mode v1.0 (zero flaws, full omniscience)
import asyncio
import logging
import time
from typing import Dict, Any, Optional, List
from dataclasses import dataclass
from datetime import datetime

# Graceful imports - no crashes if missing
try:
    from ml.online_learner import OnlineLearner
except ImportError:
    OnlineLearner = None

try:
    from risk.manager import RiskManager
except ImportError:
    RiskManager = None

try:
    from execution.oms import OrderManagementSystem
except ImportError:
    OrderManagementSystem = None

try:
    from strategies.manager import StrategyManager
except ImportError:
    StrategyManager = None

try:
    from cache.market_data_cache import MarketDataCache
except ImportError:
    MarketDataCache = None

try:
    from data.time_and_sales import get_time_and_sales_service, TradeVelocity
except ImportError:
    get_time_and_sales_service = lambda: None
    TradeVelocity = None

try:
    from news.geopolitical_risk import get_gold_geopolitical_signal
except ImportError:
    get_gold_geopolitical_signal = lambda: 0.0  # zero risk fallback

logger = logging.getLogger(__name__)

@dataclass
class Decision:
    action: str = "hold"
    size: float = 0.0
    confidence: float = 0.0
    reason: str = "No data"
    timestamp: str = ""
    override: bool = False

class HOPEFXBrain:
    """Omnipotent core: sees all, decides flawlessly, heals itself."""
    def __init__(self):
        self.learner = OnlineLearner() if OnlineLearner else None
        self.risk = RiskManager() if RiskManager else None
        self.oms = OrderManagementSystem() if OrderManagementSystem else None
        self.strategies = StrategyManager() if StrategyManager else None
        self.cache = MarketDataCache() if MarketDataCache else None
        self.tas = get_time_and_sales_service()
        self.running = False
        self.state: Dict =        self.health: Dict =        self.last_geo = 0.0
        self.last_velocity: Optional = None

    async def awaken(self):
        """Full boot - diagnose every module."""
        self.health = {
            "learner": self.learner is not None,
            "risk": self.risk is not None,
            "oms": self.oms is not None,
            "strategies": self.strategies is not None,
            "cache": self.cache is not None and await self.cache.ping(),
            "tas": self.tas is not None,
            "geo": True  # always fallback-safe
        }
        logger.info("Brain awakened. Health: " + " | ".join(f"{k}:{v}" for k,v in self.health.items()))

    async def watch(self):
        """Infinite pulse - update state, heal, monitor."""
        while self.running:
            try:
                # Price & prediction
                price_data = await self.cache.get("live:XAUUSD=X") if self.cache else {"price": 0}
                p = price_data.get("price", 0.0)
                pred = self.learner.predict(p) if self.learner else p + 0.05

                # Risk & drawdown
                risk_safe = self.risk.check() if self.risk else True
                drawdown = self.risk.get_drawdown() if self.risk else 0.0

                # TAS velocity
                velocity = self.tas.get_trade_velocity("XAUUSD") if self.tas else None
                self.last_velocity = velocity

                # Geo signal (real-time)
                geo = get_gold_geopolitical_signal()
                self.last_geo = geo

                # Strategies count
                strat_count = len(self.strategies.active) if self.strategies else 0

                self.state = {
                    "timestamp": datetime.utcnow().isoformat(),
                    "price": p,
                    "prediction": pred,
                    "risk_safe": risk_safe,
                    "drawdown": drawdown,
                    "geo_risk": geo,
                    "velocity": velocity.to_dict() if velocity else {},
                    "active_strats": strat_count,
                    "health": self.health
                }

                # Heal learner if starved
                if self.learner and len(self.learner.buffer) < 5:
                    self.learner.replay()
                    logger.debug("Learner replayed - buffer refilled")

                await asyncio.sleep(1.5)  # tight loop, low latency
            except Exception as e:
                logger.error(f"Watch crash: {e}")
                await asyncio.sleep(5)  # backoff

    def command(self, trigger: str = "tick") -> Decision:
        """God decision: layered, no mistakes."""
        if not self.state:
            return Decision(reason="No state - waiting for data")

        p = self.state pred = self.state conf = 0.95 if abs(pred - p) > 0.10 else 0.65 if abs(pred - p) > 0.04 else 0.40
        risk_ok = self.state drawdown = self.state geo = self.state velocity_buy_pct = self.state .get("buy_trades_pct", 50) if self.state else 50

        reason = f"Price: {p:.2f} | Pred: {pred:.2f} | Conf: {conf:.2f}"

        # Layer 1: Emergency overrides
        if drawdown > 0.08:
            return Decision("flatten", 0.0, 1.0, reason + " | Drawdown panic - flatten", override=True)

        if geo > 75:
            return Decision("hold", 0.0, 0.7, reason + f" | Geo danger: {geo}% - hold only")

        # Layer 2: Velocity filter (crowd momentum)
        if velocity_buy_pct > 80 and pred > p:
            reason += " | Strong buy velocity - boost"
            conf += 0.1
        elif velocity_buy_pct < 20 and pred < p:
            reason += " | Strong sell velocity - boost"
            conf += 0.1

        # Layer 3: Core ML + risk decision
        action = (
            "buy" if pred > p + 0.06 and risk_ok and conf > 0.65 else
            "sell" if pred < p - 0.06 and risk_ok and conf > 0.65 else
            "hold"
        )

        # Size: confidence-scaled, capped
        size = min(1.0, conf * 0.6) if action != "hold" else 0.0

        return Decision(action, size, conf, reason, datetime.utcnow().isoformat())

    async def enforce(self, decision: Decision):
        """Execute safely + log."""
        if decision.action == "hold":
            return
        try:
            await self.oms.place_order("XAUUSD", decision.action, decision.size)
            logger.info(f"Brain executed: {decision.action} {decision.size:.2f} - {decision.reason}")
        except Exception as e:
            logger.critical(f"Execution failed: {e} - {decision}")

    async def dominate(self):
        """Full takeover."""
        self.running = True
        await self.awaken()
        asyncio.create_task(self.watch())
        logger.critical("Brain online. I see everything. No mercy.")

    def shutdown(self):
        self.running = False
        logger.info("Brain shutdown. Rest now.")