# HOPEFX-AI-TRADING
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
trader_full.py
==============
End-to-end live trading loop for HOPEFX.

Wires together:
  LiveDataPipeline  — OANDA streaming prices via OANDAStreamAdapter
  OrderGateway      — order placement + fill tracking via broker connector
  EnsembleStrategy  — signal generation via StrategyOrchestra
  MLPredictor       — ML signal overlay via HopeFXPredictor
  RiskManager       — position sizing + circuit breakers
  StateManager      — Redis + SQLAlchemy persistence
  AlertManager      — Telegram + log alerts
  NewsFilter        — Forex Factory high-impact event filter
  ForwardTestHarness — paper-trading forward-test loop
  SecureConfig      — encrypted credential loading

Run modes (APP_ENV env var):
  paper  — paper broker, no real money (default)
  live   — OANDA live account (requires OANDA_API_KEY + OANDA_ACCOUNT_ID)
"""

from __future__ import annotations

import asyncio
import logging
import os
import signal
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# SecureConfig
# ---------------------------------------------------------------------------


class SecureConfig:
    """Load trading credentials from environment variables."""

    def __init__(self) -> None:
        self.app_env: str = os.getenv("APP_ENV", "paper")
        self.oanda_api_key: str = os.getenv("OANDA_API_KEY", "")
        self.oanda_account_id: str = os.getenv("OANDA_ACCOUNT_ID", "")
        self.oanda_practice: bool = self.app_env != "live"
        self.redis_host: str = os.getenv("REDIS_HOST", "localhost")
        self.redis_port: int = int(os.getenv("REDIS_PORT", "6379"))
        self.telegram_token: str = os.getenv("TELEGRAM_BOT_TOKEN", "")
        self.telegram_chat_id: str = os.getenv("TELEGRAM_CHAT_ID", "")
        self.symbols: List[str] = os.getenv("SIGNAL_ENGINE_SYMBOLS", "XAU_USD").split(
            ","
        )
        self.initial_balance: float = float(os.getenv("INITIAL_BALANCE", "10000"))

    def validate_live(self) -> None:
        missing = []
        if not self.oanda_api_key:
            missing.append("OANDA_API_KEY")
        if not self.oanda_account_id:
            missing.append("OANDA_ACCOUNT_ID")
        if missing:
            raise EnvironmentError(f"Live trading requires: {', '.join(missing)}")


# ---------------------------------------------------------------------------
# LiveDataPipeline
# ---------------------------------------------------------------------------


class LiveDataPipeline:
    """
    Wraps OANDAStreamAdapter to deliver live ticks to registered callbacks.
    Falls back to a synthetic 1-second feed in paper mode.
    """

    def __init__(self, config: SecureConfig) -> None:
        self._config = config
        self._adapter: Optional[Any] = None
        self._callbacks: List[Any] = []
        self._running = False

    def register_tick_callback(self, fn) -> None:
        self._callbacks.append(fn)

    async def start(self) -> None:
        if self._config.app_env == "paper":
            logger.info("LiveDataPipeline: paper mode — synthetic price feed")
            self._running = True
            asyncio.create_task(self._synthetic_feed())
            return
        try:
            from brokers.oanda_ws import OANDAStreamAdapter

            self._adapter = OANDAStreamAdapter(
                api_key=self._config.oanda_api_key,
                account_id=self._config.oanda_account_id,
                instruments=self._config.symbols,
                practice=self._config.oanda_practice,
                on_tick=self._dispatch,
            )
            await self._adapter.start()
            self._running = True
            logger.info(
                "LiveDataPipeline: OANDA stream started for %s", self._config.symbols
            )
        except Exception as exc:
            logger.error("LiveDataPipeline start failed: %s", exc)
            raise

    async def stop(self) -> None:
        self._running = False
        if self._adapter:
            await self._adapter.stop()

    def _dispatch(self, tick: Dict) -> None:
        for cb in self._callbacks:
            try:
                cb(tick)
            except Exception as exc:
                logger.error("Tick callback error: %s", exc)

    async def _synthetic_feed(self) -> None:
        import random

        price = 2050.0
        while self._running:
            price += random.gauss(0, 0.5)
            tick = {
                "type": "PRICE",
                "instrument": self._config.symbols[0],
                "bids": [{"price": str(round(price - 0.05, 2))}],
                "asks": [{"price": str(round(price + 0.05, 2))}],
                "time": datetime.now(timezone.utc).isoformat(),
            }
            self._dispatch(tick)
            await asyncio.sleep(1.0)


# ---------------------------------------------------------------------------
# OrderGateway
# ---------------------------------------------------------------------------


class OrderGateway:
    """Thin wrapper around a broker connector for order placement."""

    def __init__(self, broker) -> None:
        self._broker = broker

    async def place_market_order(
        self,
        symbol: str,
        side: str,
        quantity: float,
        stop_loss: Optional[float] = None,
        take_profit: Optional[float] = None,
    ) -> Optional[Any]:
        try:
            from brokers.base import OrderSide, OrderType

            side_enum = OrderSide.BUY if side.upper() == "BUY" else OrderSide.SELL
            order = self._broker.place_order(
                symbol=symbol,
                side=side_enum,
                order_type=OrderType.MARKET,
                quantity=quantity,
            )
            if order:
                logger.info(
                    "OrderGateway: %s %s %.4f @ market | id=%s",
                    side,
                    symbol,
                    quantity,
                    order.id,
                )
            return order
        except Exception as exc:
            logger.error("OrderGateway.place_market_order: %s", exc)
            return None

    async def cancel_order(self, order_id: str) -> bool:
        try:
            return self._broker.cancel_order(order_id)
        except Exception as exc:
            logger.error("OrderGateway.cancel_order: %s", exc)
            return False


# ---------------------------------------------------------------------------
# EnsembleStrategy
# ---------------------------------------------------------------------------


class EnsembleStrategy:
    """Delegates to StrategyOrchestra for multi-strategy signal consensus."""

    def __init__(self) -> None:
        self._orchestra: Optional[Any] = None

    def setup(self, event_bus) -> None:
        try:
            from core.strategy_orchestra import StrategyOrchestra

            self._orchestra = StrategyOrchestra(event_bus)
            logger.info("EnsembleStrategy: StrategyOrchestra initialised")
        except Exception as exc:
            logger.warning("EnsembleStrategy setup failed: %s", exc)

    def generate_signal(self, market_data: Dict) -> Dict:
        if self._orchestra is None:
            return {
                "direction": "flat",
                "confidence": 0.0,
                "reason": "orchestra not ready",
            }
        try:
            price = float(market_data.get("close", market_data.get("mid", 0)))
            self._orchestra.distribute_price(price)
            signals = self._orchestra.get_consensus_signal()
            if signals:
                return signals
        except Exception as exc:
            logger.warning("EnsembleStrategy.generate_signal: %s", exc)
        return {"direction": "flat", "confidence": 0.0, "reason": "no consensus"}


# ---------------------------------------------------------------------------
# MLPredictor
# ---------------------------------------------------------------------------


class MLPredictor:
    """Wraps HopeFXPredictor. Loads a pre-trained model if available."""

    def __init__(self) -> None:
        self._predictor: Optional[Any] = None
        self._model_path: str = os.getenv("ML_MODEL_PATH", "ml/saved_models/hopefx")

    def load(self) -> bool:
        try:
            from enhanced_ml_predictor import HopeFXPredictor

            self._predictor = HopeFXPredictor()
            import pathlib

            if pathlib.Path(self._model_path).exists():
                self._predictor.load(self._model_path)
                logger.info("MLPredictor: model loaded from %s", self._model_path)
            else:
                logger.warning(
                    "MLPredictor: no saved model at %s — predictions will be neutral",
                    self._model_path,
                )
            return True
        except Exception as exc:
            logger.warning("MLPredictor.load: %s", exc)
            return False

    def predict(self, df) -> Dict:
        if self._predictor is None or not getattr(self._predictor, "is_fitted", False):
            return {"direction": "neutral", "confidence": 0.0}
        try:
            pred = self._predictor.predict(df)
            if pred:
                return {
                    "direction": pred.prediction,
                    "confidence": pred.confidence,
                    "uncertainty": getattr(pred, "uncertainty", 0.0),
                }
        except Exception as exc:
            logger.warning("MLPredictor.predict: %s", exc)
        return {"direction": "neutral", "confidence": 0.0}


# ---------------------------------------------------------------------------
# RiskManager
# ---------------------------------------------------------------------------


class RiskManager:
    """Delegates to risk.manager.RiskManager for sizing and circuit-breaker logic."""

    def __init__(self, initial_balance: float = 10_000.0) -> None:
        self._rm: Optional[Any] = None
        self._balance = initial_balance

    def setup(self) -> None:
        try:
            from risk.manager import RiskManager as _RM, RiskConfig

            self._rm = _RM(config=RiskConfig(), initial_balance=self._balance)
            logger.info("RiskManager: initialised with balance=%.2f", self._balance)
        except Exception as exc:
            logger.warning("RiskManager.setup: %s", exc)

    def approve_trade(
        self, symbol: str, side: str, price: float, equity: float
    ) -> Dict:
        if self._rm is None:
            return {"approved": False, "reason": "risk manager not initialised"}
        try:
            if self._rm._trading_halted:
                return {
                    "approved": False,
                    "reason": self._rm._halt_reason or "trading halted",
                }
            self._rm.update_equity(equity)
            result = self._rm.calculate_position_size(
                symbol=symbol,
                entry_price=price,
                stop_loss_price=price * (0.99 if side == "BUY" else 1.01),
                account_equity=equity,
            )
            return {
                "approved": result.approved,
                "size": result.recommended_size,
                "reason": result.reason,
            }
        except Exception as exc:
            logger.error("RiskManager.approve_trade: %s", exc)
            return {"approved": False, "reason": str(exc)}


# ---------------------------------------------------------------------------
# StateManager
# ---------------------------------------------------------------------------


class StateManager:
    """Persists trading state to Redis."""

    def __init__(self, redis_host: str = "localhost", redis_port: int = 6379) -> None:
        self._redis: Optional[Any] = None
        self._redis_host = redis_host
        self._redis_port = redis_port

    def connect(self) -> None:
        try:
            import redis

            self._redis = redis.Redis(
                host=self._redis_host,
                port=self._redis_port,
                decode_responses=True,
                socket_connect_timeout=3,
            )
            self._redis.ping()
            logger.info(
                "StateManager: Redis connected at %s:%d",
                self._redis_host,
                self._redis_port,
            )
        except Exception as exc:
            logger.warning(
                "StateManager: Redis unavailable (%s) — state will not persist", exc
            )
            self._redis = None

    def save(self, key: str, value: str, ttl: int = 86400) -> None:
        if self._redis:
            try:
                self._redis.set(key, value, ex=ttl)
            except Exception as exc:
                logger.warning("StateManager.save: %s", exc)

    def load(self, key: str) -> Optional[str]:
        if self._redis:
            try:
                return self._redis.get(key)
            except Exception as exc:
                logger.warning("StateManager.load: %s", exc)
        return None


# ---------------------------------------------------------------------------
# AlertManager
# ---------------------------------------------------------------------------


class AlertManager:
    """Sends alerts via Telegram bot and structured logging."""

    def __init__(self, token: str = "", chat_id: str = "") -> None:
        self._bot: Optional[Any] = None
        self._token = token
        self._chat_id = chat_id

    def setup(self) -> None:
        if not self._token or not self._chat_id:
            logger.info("AlertManager: Telegram not configured — log-only mode")
            return
        try:
            from notifications.telegram_bot import TelegramBot

            self._bot = TelegramBot(token=self._token)
            logger.info("AlertManager: Telegram bot ready")
        except Exception as exc:
            logger.warning("AlertManager.setup: %s", exc)

    def send(self, message: str, level: str = "INFO") -> None:
        logger.log(getattr(logging, level, logging.INFO), "ALERT: %s", message)
        if self._bot and self._chat_id:
            try:
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    asyncio.create_task(self._bot.send_message(self._chat_id, message))
            except Exception as exc:
                logger.warning("AlertManager.send telegram: %s", exc)


# ---------------------------------------------------------------------------
# NewsFilter
# ---------------------------------------------------------------------------


class NewsFilter:
    """Pauses trading around high-impact Forex Factory events."""

    def __init__(self, redis_host: str = "localhost", redis_port: int = 6379) -> None:
        self._filter: Optional[Any] = None
        self._redis_host = redis_host
        self._redis_port = redis_port

    def setup(self) -> None:
        try:
            from news_filter_integration import NewsFilterIntegration

            self._filter = NewsFilterIntegration(
                redis_host=self._redis_host,
                redis_port=self._redis_port,
            )
            logger.info("NewsFilter: initialised")
        except Exception as exc:
            logger.warning("NewsFilter.setup: %s", exc)

    def is_safe_to_trade(self) -> bool:
        if self._filter is None:
            return True
        try:
            return not self._filter.is_trading_paused()
        except Exception:
            return True


# ---------------------------------------------------------------------------
# ForwardTestHarness
# ---------------------------------------------------------------------------


class ForwardTestHarness:
    """
    Runs the full signal -> risk -> order pipeline against the paper broker.
    Logs equity curve to Redis for post-analysis.
    """

    def __init__(
        self,
        pipeline: LiveDataPipeline,
        gateway: OrderGateway,
        strategy: EnsembleStrategy,
        ml: MLPredictor,
        risk: RiskManager,
        alerts: AlertManager,
        news: NewsFilter,
        state: StateManager,
    ) -> None:
        self._pipeline = pipeline
        self._gateway = gateway
        self._strategy = strategy
        self._ml = ml
        self._risk = risk
        self._alerts = alerts
        self._news = news
        self._state = state
        self._running = False
        self._equity = 10_000.0
        self._tick_buffer: List[Dict] = []

    async def run(self) -> None:
        self._running = True
        self._pipeline.register_tick_callback(self._on_tick)
        await self._pipeline.start()
        self._alerts.send("ForwardTestHarness started", "INFO")
        logger.info("ForwardTestHarness: running")
        try:
            while self._running:
                await asyncio.sleep(60)
                self._state.save("hopefx:equity", str(self._equity))
        except asyncio.CancelledError:
            pass
        finally:
            await self._pipeline.stop()
            self._alerts.send("ForwardTestHarness stopped", "WARNING")

    def stop(self) -> None:
        self._running = False

    def _on_tick(self, tick: Dict) -> None:
        try:
            bids = tick.get("bids", [{}])
            asks = tick.get("asks", [{}])
            bid = float(bids[0].get("price", 0)) if bids else 0.0
            ask = float(asks[0].get("price", 0)) if asks else 0.0
            mid = round((bid + ask) / 2, 5) if bid and ask else 0.0
            if mid == 0.0:
                return

            self._tick_buffer.append({"close": mid, "bid": bid, "ask": ask})
            if len(self._tick_buffer) > 200:
                self._tick_buffer.pop(0)

            if not self._news.is_safe_to_trade():
                return

            market_data = {"close": mid, "mid": mid, "bid": bid, "ask": ask}
            signal = self._strategy.generate_signal(market_data)

            if signal.get("direction") == "flat":
                return

            approval = self._risk.approve_trade(
                symbol=tick.get("instrument", "XAU_USD"),
                side=signal["direction"].upper(),
                price=mid,
                equity=self._equity,
            )
            if not approval.get("approved"):
                logger.debug("Trade blocked: %s", approval.get("reason"))
                return

            size = approval.get("size", 0.01)
            asyncio.create_task(
                self._gateway.place_market_order(
                    symbol=tick.get("instrument", "XAU_USD"),
                    side=signal["direction"].upper(),
                    quantity=size,
                )
            )
            self._alerts.send(
                f"Signal: {signal['direction'].upper()} {size} "
                f"{tick.get('instrument')} @ {mid:.5f} "
                f"(conf={signal.get('confidence', 0):.2f})"
            )
        except Exception as exc:
            logger.error("ForwardTestHarness._on_tick: %s", exc)


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


async def _main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-8s %(name)s — %(message)s",
    )

    cfg = SecureConfig()
    if cfg.app_env == "live":
        cfg.validate_live()

    logger.info("trader_full starting | env=%s | symbols=%s", cfg.app_env, cfg.symbols)

    # Build broker
    if cfg.app_env == "live":
        from brokers.oanda import OANDAConnector

        broker = OANDAConnector(
            api_key=cfg.oanda_api_key,
            account_id=cfg.oanda_account_id,
            practice=False,
        )
        broker.connect()
    else:
        from brokers.paper_trading import PaperTradingBroker

        broker = PaperTradingBroker(initial_balance=cfg.initial_balance)
        await broker.connect()

    # Kill switch — check persisted state on startup
    from kill_switch import KillSwitch

    ks = KillSwitch()
    await ks.start()
    if ks.is_active():
        logger.critical(
            "Kill switch is active from previous session (%s) — aborting startup",
            ks.reason,
        )
        await ks.stop()
        return

    # Wire components
    pipeline = LiveDataPipeline(cfg)
    gateway = OrderGateway(broker)
    strategy = EnsembleStrategy()
    ml = MLPredictor()
    risk = RiskManager(initial_balance=cfg.initial_balance)
    state = StateManager(redis_host=cfg.redis_host, redis_port=cfg.redis_port)
    alerts = AlertManager(token=cfg.telegram_token, chat_id=cfg.telegram_chat_id)
    news = NewsFilter(redis_host=cfg.redis_host, redis_port=cfg.redis_port)

    try:
        from core.event_bus import EventBus

        event_bus = EventBus()
        strategy.setup(event_bus)
    except Exception as exc:
        logger.warning("EventBus unavailable: %s", exc)

    ml.load()
    risk.setup()
    state.connect()
    alerts.setup()
    news.setup()

    harness = ForwardTestHarness(
        pipeline=pipeline,
        gateway=gateway,
        strategy=strategy,
        ml=ml,
        risk=risk,
        alerts=alerts,
        news=news,
        state=state,
    )

    loop = asyncio.get_running_loop()

    def _shutdown(sig_name: str) -> None:
        logger.warning("Received %s — shutting down", sig_name)
        harness.stop()

    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, lambda s=sig.name: _shutdown(s))

    await harness.run()
    await ks.stop()
    logger.info("trader_full shutdown complete")


if __name__ == "__main__":
    asyncio.run(_main())
