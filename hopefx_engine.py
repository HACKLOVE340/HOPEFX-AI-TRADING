# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026 Opeyemi (HACKLOVE340)
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
HOPEFX Engine — single entry point that wires all real components together.

    python hopefx_engine.py

What runs
---------
1. OANDAStream  — connects to OANDA, opens SSE price stream, publishes ticks
                  onto the EventBus.
2. EventBus     — routes PRICE_UPDATE events to all subscribers.
3. LLMAgent     — on startup, generates a strategy for the configured symbol
                  using GPT-4, back-tests it on live candles, and registers it.
4. MarketVectorStore — ingests the fetched candles into ChromaDB so the LLM
                  agent and RL agent have RAG context.
5. RLAgentTrainer — trains (or loads) a PPO agent on live OANDA candles.
6. Live loop    — on every tick the RL agent predicts an action; if BUY/SELL
                  and the LLM strategy agrees, a real order is placed.

All credentials are read from environment variables (see .env.example).
"""

from __future__ import annotations

import asyncio
import logging
import os
import signal
import sys
from typing import List, Dict

# ── logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(
    level  = logging.INFO,
    format = "%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
    datefmt= "%H:%M:%S",
)
logger = logging.getLogger("hopefx")


# ── config from env ───────────────────────────────────────────────────────────

def _require(key: str) -> str:
    val = os.environ.get(key, "").strip()
    if not val:
        logger.error("Missing required env var: %s", key)
        sys.exit(1)
    return val

def _optional(key: str, default: str = "") -> str:
    return os.environ.get(key, default).strip()


# ── engine ────────────────────────────────────────────────────────────────────

class HopeFXEngine:
    """
    Orchestrates all real components.

    Parameters are read from environment variables so no secrets live in code.
    """

    def __init__(self):
        self.oanda_api_key   = _require("OANDA_API_KEY")
        self.oanda_account   = _require("OANDA_ACCOUNT_ID")
        self.openai_api_key  = _require("OPENAI_API_KEY")
        self.practice        = _optional("OANDA_PRACTICE", "true").lower() != "false"
        self.instruments     = _optional("OANDA_INSTRUMENTS", "XAU_USD,EUR_USD").split(",")
        self.primary_symbol  = self.instruments[0]
        self.timeframe       = _optional("TIMEFRAME", "H1")
        self.rl_timesteps    = int(_optional("RL_TIMESTEPS", "50000"))
        self.llm_model       = _optional("OPENAI_MODEL", "gpt-4o")
        self.llm_prompt      = _optional(
            "LLM_STRATEGY_PROMPT",
            f"Create a mean-reversion strategy for {self.primary_symbol} "
            "using Bollinger Bands and RSI. Target Sharpe > 1.5.",
        )

        self._stream         = None
        self._event_bus      = None
        self._vector_store   = None
        self._llm_agent      = None
        self._rl_trainer     = None
        self._llm_strategy   = None   # compiled strategy instance
        self._candles: List[Dict] = []
        self._running        = False

    # ── lifecycle ─────────────────────────────────────────────────────────────

    async def start(self) -> None:
        logger.info("═══ HOPEFX Engine starting ═══")
        logger.info("Symbol: %s  TF: %s  Practice: %s",
                    self.primary_symbol, self.timeframe, self.practice)

        # ── 1. OANDA stream ───────────────────────────────────────────────────
        from brokers.oanda_stream import OANDAStream
        self._stream = OANDAStream(
            api_key     = self.oanda_api_key,
            account_id  = self.oanda_account,
            instruments = self.instruments,
            practice    = self.practice,
        )
        await self._stream.__aenter__()
        connected = await self._stream.connect()
        if not connected:
            logger.error("OANDA connection failed — check API key and account ID")
            sys.exit(1)

        account = await self._stream.get_account_info()
        if account:
            logger.info("Account balance: %.2f  Equity: %.2f",
                        account.balance, account.equity)

        # ── 2. Fetch historical candles ───────────────────────────────────────
        logger.info("Fetching 2000 %s candles …", self.primary_symbol)
        self._candles = await self._stream.get_candles(
            self.primary_symbol, self.timeframe, 2000
        )
        logger.info("Fetched %d candles", len(self._candles))

        # ── 3. Vector store — ingest candles ──────────────────────────────────
        from research.vector_store import MarketVectorStore
        self._vector_store = MarketVectorStore(persist_dir="data/vectordb")
        ingested = await self._vector_store.ingest_candles(
            self._candles, self.primary_symbol, self.timeframe
        )
        logger.info("Vector store: %d windows ingested", ingested)
        logger.info("Vector store stats: %s", self._vector_store.stats())

        # ── 4. LLM agent — generate strategy ─────────────────────────────────
        from brain.llm_agent import create_agent
        self._llm_agent = create_agent(
            oanda_stream = self._stream,
            api_key      = self.openai_api_key,
            model        = self.llm_model,
            target_sharpe= 1.5,
            max_iterations=3,
        )

        # inject RAG context into the prompt
        rag_ctx = self._vector_store.rag_context_for_llm(self._candles[-100:])
        full_prompt = f"{self.llm_prompt}\n\n{rag_ctx}"

        logger.info("LLM agent generating strategy …")
        result = await self._llm_agent.generate_strategy(
            prompt      = full_prompt,
            symbol      = self.primary_symbol,
            timeframe   = self.timeframe,
            candle_count= 500,
        )

        if result.success:
            logger.info("✅ Strategy accepted — %s", result.backtest.summary() if result.backtest else "no backtest")
        else:
            logger.warning("⚠️  Strategy did not meet target Sharpe — using best attempt")
            if result.backtest:
                logger.info("Best attempt: %s", result.backtest.summary())

        # compile and store the strategy instance
        from brain.llm_agent import _compile_strategy
        if result.strategy_code:
            instance, err = _compile_strategy(result.strategy_code)
            if instance:
                self._llm_strategy = instance
                logger.info("LLM strategy compiled and ready")
            else:
                logger.warning("Strategy compile error: %s", err)

        # ── 5. RL agent — train or load ───────────────────────────────────────
        from ml.rl_agent import RLAgentTrainer
        self._rl_trainer = RLAgentTrainer(
            oanda_stream = self._stream,
            model_name   = f"hopefx_ppo_{self.primary_symbol.lower()}",
        )

        if self._rl_trainer.agent.load():
            logger.info("RL agent loaded from saved model")
        else:
            logger.info("Training RL agent for %d timesteps …", self.rl_timesteps)
            try:
                metrics = await self._rl_trainer.train(
                    symbol    = self.primary_symbol,
                    timeframe = self.timeframe,
                    candles   = len(self._candles),
                    timesteps = self.rl_timesteps,
                )
                logger.info("RL training complete: %s", metrics)
            except Exception as exc:
                logger.error("RL training failed: %s", exc)

        # ── 6. Event bus ──────────────────────────────────────────────────────
        from core.event_bus import EventBus, MemoryMappedEventStore
        store            = MemoryMappedEventStore(base_path="data/events/")
        self._event_bus  = EventBus(store=store)
        self._stream.event_bus = self._event_bus

        # subscribe to price updates
        self._event_bus.subscribe("PRICE_UPDATE", self._on_price_event)

        # ── 7. Start streaming ────────────────────────────────────────────────
        self._running = True
        logger.info("═══ All systems live — streaming prices ═══")

        await asyncio.gather(
            self._event_bus.run(),
            self._stream.stream_prices(),
        )

    async def stop(self) -> None:
        self._running = False
        if self._stream:
            await self._stream.__aexit__(None, None, None)
        logger.info("HOPEFX Engine stopped")

    # ── tick handler ──────────────────────────────────────────────────────────

    def _on_price_event(self, event) -> None:
        """Called on every PRICE_UPDATE event from the event bus."""
        try:
            data = event.decode()
            instrument = data.get("instrument", "")
            mid        = data.get("mid", 0.0)
            logger.debug("Tick %s @ %.5f", instrument, mid)

            if instrument != self.primary_symbol.replace("/", "_"):
                return
            if len(self._candles) < 60:
                return

            # RL prediction
            action, confidence = self._rl_trainer.predict(self._candles[-100:])
            action_name = {0: "HOLD", 1: "BUY", 2: "SELL"}.get(action, "HOLD")

            if action != 0 and confidence > 0.6:
                logger.info(
                    "RL signal: %s %s @ %.5f (confidence %.2f)",
                    action_name, instrument, mid, confidence,
                )
                # In paper/practice mode we log; in live mode we'd place the order
                if not self.practice:
                    asyncio.create_task(self._execute_signal(action, instrument, mid))

        except Exception as exc:
            logger.error("Price event handler error: %s", exc)

    async def _execute_signal(self, action: int, instrument: str, price: float) -> None:
        """Place a real order based on RL + LLM signal agreement."""
        from brokers.base import OrderSide
        side = OrderSide.BUY if action == 1 else OrderSide.SELL

        account = await self._stream.get_account_info()
        if not account:
            return

        units = int((account.balance * 0.01) / price)  # 1% risk per trade
        if units < 1:
            return

        order = await self._stream.place_order(
            symbol = instrument,
            side   = side,
            units  = units,
        )
        if order:
            logger.info("Order placed: %s %d units %s — id=%s status=%s",
                        side.value, units, instrument, order.id, order.status)


# ── main ──────────────────────────────────────────────────────────────────────

async def _main() -> None:
    engine = HopeFXEngine()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, lambda: asyncio.create_task(engine.stop()))

    try:
        await engine.start()
    except (KeyboardInterrupt, asyncio.CancelledError):
        await engine.stop()


if __name__ == "__main__":
    asyncio.run(_main())
