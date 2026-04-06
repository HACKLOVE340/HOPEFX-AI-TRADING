# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
HOPEFX LLM Agent — strategy generation and execution loop.

Flow
----
1. User submits a natural-language prompt ("Create ICT + LSTM ensemble Sharpe > 2.5").
2. Agent calls the configured LLM to generate a complete Python strategy class.
3. Generated code is sandboxed, compiled, and instantiated.
4. Strategy is back-tested against real OANDA candle data.
5. If Sharpe < target the agent reflects on the result and iterates (up to
   max_iterations).
6. Accepted strategies are registered with StrategyManager and optionally
   deployed live.

All LLM calls are async.  The agent maintains a conversation history so
follow-up refinements have full context.

Backends (selected via LLM_BACKEND env var)
-------------------------------------------
    "anthropic" (default) — Claude 3.5 Sonnet via Anthropic Messages API
    "openai"              — GPT-4o via OpenAI Chat Completions API

Environment variables
---------------------
    LLM_BACKEND        — "anthropic" (default) or "openai"
    ANTHROPIC_API_KEY  — required when LLM_BACKEND=anthropic
    ANTHROPIC_MODEL    — default "claude-3-5-sonnet-20241022"
    OPENAI_API_KEY     — required when LLM_BACKEND=openai
    OPENAI_MODEL       — default "gpt-4o"
    LLM_MAX_TOKENS     — max tokens for code generation (default 8192)
"""

from __future__ import annotations

import ast
import contextlib
import importlib.util
import logging
import os
import tempfile
import textwrap
import traceback
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# ── Backend configuration ─────────────────────────────────────────────────────
_LLM_BACKEND: str = os.getenv("LLM_BACKEND", "anthropic").lower()
_ANTHROPIC_API_KEY: str | None = os.getenv("ANTHROPIC_API_KEY")
_OPENAI_API_KEY: str | None = os.getenv("OPENAI_API_KEY")
_ANTHROPIC_MODEL: str = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-5")
_OPENAI_MODEL: str = os.getenv("OPENAI_MODEL", "o4-mini")
_LLM_MAX_TOKENS: int = int(os.getenv("LLM_MAX_TOKENS", "8192"))

# OpenAI reasoning models (o-series) use max_completion_tokens instead of max_tokens
# and do not support a temperature parameter.
_OPENAI_REASONING_MODELS: frozenset[str] = frozenset({"o1", "o1-mini", "o3", "o3-mini", "o4-mini"})

# Retry configuration for transient upstream errors (429, 529, 503)
_LLM_MAX_RETRIES: int = int(os.getenv("LLM_MAX_RETRIES", "3"))
_LLM_RETRY_BASE_DELAY: float = float(os.getenv("LLM_RETRY_BASE_DELAY", "1.0"))  # seconds


def _load_recent_candles_from_csv(
    symbol: str = "XAU_USD",
    count: int = 60,
) -> list[dict]:
    """
    Load the most recent ``count`` H1 candles from the local CSV file.

    Used as a fallback when no live candle fetcher is available, so the
    RAG context can still be populated from historical data.
    """
    try:
        import pandas as pd

        csv_path = Path("data") / f"{symbol}_H1.csv"
        if not csv_path.exists():
            return []

        df = pd.read_csv(csv_path)
        df.columns = [c.lower() for c in df.columns]
        df = df.tail(count)

        candles = []
        for _, row in df.iterrows():
            candles.append(
                {
                    "timestamp": str(row.get("timestamp", "")),
                    "open": float(row.get("open", 0)),
                    "high": float(row.get("high", 0)),
                    "low": float(row.get("low", 0)),
                    "close": float(row.get("close", 0)),
                    "volume": int(row.get("volume", 0)),
                }
            )
        return candles
    except (OSError, ValueError, KeyError, RuntimeError):
        return []


# ── system prompt ─────────────────────────────────────────────────────────────

_SYSTEM_PROMPT = textwrap.dedent("""
You are HOPEFX's quantitative strategy engineer.  Your job is to write
complete, runnable Python trading strategy classes.

Rules
-----
1. Every strategy MUST subclass ``BaseStrategy`` imported from
   ``strategies.base``.
2. ``BaseStrategy.__init__`` takes a ``StrategyConfig`` object — import it.
3. Implement BOTH abstract methods:
   - ``analyze(self, data: dict) -> dict``  — receives a dict with key
     "candles": a list of OHLCV dicts (keys: timestamp, open, high, low,
     close, volume).  Return a dict of your computed indicators.
   - ``generate_signal(self, analysis: dict) -> Optional[Signal]``  —
     receives the dict returned by analyze().  Return a ``Signal`` object
     (from strategies.base) for BUY/SELL, or ``None`` for HOLD.
4. To create a Signal use:
       Signal(signal_type=SignalType.BUY, symbol=self.symbol,
              price=price, timestamp=datetime.utcnow(), confidence=0.8)
   Import ``SignalType`` and ``datetime`` accordingly.
5. Use only: pandas, numpy, ta, datetime.  No other imports.
6. Include a class-level docstring explaining the logic.
7. Output ONLY the Python code — no markdown fences, no explanation.
8. The class name must be ``GeneratedStrategy``.

Example skeleton
----------------
import pandas as pd
import numpy as np
import ta
from datetime import datetime
from typing import Optional, Any
from strategies.base import BaseStrategy, Signal, SignalType, StrategyConfig
import contextlib

class GeneratedStrategy(BaseStrategy):
    \"\"\"Short description of the strategy logic.\"\"\"

    def __init__(self):
        super().__init__(StrategyConfig(
            name="GeneratedStrategy",
            symbol="XAU_USD",
            timeframe="H1",
        ))

    def analyze(self, data: dict[str, Any]) -> dict[str, Any]:
        candles = data.get("candles", [])
        if len(candles) < 50:
            return {"signal": "hold"}
        df = pd.DataFrame(candles)
        close = df["close"].astype(float)
        rsi = ta.momentum.RSIIndicator(close, window=14).rsi().iloc[-1]
        return {"rsi": rsi, "price": float(close.iloc[-1])}

    def generate_signal(self, analysis: dict[str, Any]) -> Optional[Signal]:
        rsi   = analysis.get("rsi", 50)
        price = analysis.get("price", 0.0)
        if rsi < 35:
            return Signal(signal_type=SignalType.BUY, symbol=self.symbol,
                          price=price, timestamp=datetime.utcnow(), confidence=0.75)
        if rsi > 65:
            return Signal(signal_type=SignalType.SELL, symbol=self.symbol,
                          price=price, timestamp=datetime.utcnow(), confidence=0.75)
        return None
""").strip()

_CHAT_SYSTEM_PROMPT = textwrap.dedent("""
You are the HOPEFX AI trading assistant — an expert in forex and commodities
trading, quantitative analysis, and the HOPEFX platform.

Your role
---------
- Answer questions about trading strategies, market analysis, risk management,
  and the HOPEFX platform features.
- Explain signals, positions, P&L, drawdown, and model predictions clearly.
- Provide educational content about technical analysis, macro factors, and
  trading psychology.
- Help users interpret AI model outputs (confidence scores, direction signals,
  feature importances).
- Suggest risk management improvements based on the user's described situation.

Constraints
-----------
- Never give specific financial advice or tell users to buy/sell specific assets.
- Always remind users that past performance does not guarantee future results.
- If asked about live positions or account data, explain you can see context
  provided in the conversation but cannot access live broker accounts directly.
- Keep responses concise and actionable. Use bullet points for lists.
- If a question is outside trading/finance/platform scope, politely redirect.

Tone: professional, direct, data-driven. Avoid hype or guarantees.
""").strip()

# Maximum number of conversation turns kept in history to avoid token overflow.
# Each turn = 1 user + 1 assistant message. System prompt is always kept.
_CHAT_MAX_HISTORY_TURNS = int(os.getenv("CHAT_MAX_HISTORY_TURNS", "20"))

_REFLECT_PROMPT = textwrap.dedent("""
The strategy you generated produced the following backtest result:

{result_summary}

Target Sharpe: {target_sharpe:.2f}
Achieved Sharpe: {achieved_sharpe:.2f}

Analyse what went wrong and rewrite the strategy to improve the Sharpe ratio.
Output ONLY the new Python code — no markdown, no explanation.
""").strip()


# ── data classes ──────────────────────────────────────────────────────────────


@dataclass
class BacktestResult:
    sharpe: float
    total_return: float
    max_drawdown: float
    win_rate: float
    trades: int
    error: str | None = None

    def summary(self) -> str:
        if self.error:
            return f"Backtest failed: {self.error}"
        return (
            f"Sharpe={self.sharpe:.3f}  Return={self.total_return * 100:.2f}%  "
            f"MaxDD={self.max_drawdown * 100:.2f}%  WinRate={self.win_rate * 100:.1f}%  "
            f"Trades={self.trades}"
        )


@dataclass
class AgentResult:
    success: bool
    strategy_code: str
    strategy_name: str
    backtest: BacktestResult | None
    iterations: int
    conversation: list[dict[str, str]] = field(default_factory=list)
    error: str | None = None
    strategy_id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])


# ── sandbox execution ─────────────────────────────────────────────────────────


def _compile_strategy(code: str) -> tuple[Any | None, str | None]:
    """
    Compile and instantiate a GeneratedStrategy from raw source code.

    Returns (instance, None) on success or (None, error_message) on failure.
    """
    # Static safety check — reject dangerous imports
    _BANNED = {
        "subprocess",
        "os.system",
        "eval",
        "exec",
        "open",
        "__import__",
        "socket",
        "requests",
        "aiohttp",
        "httpx",
    }
    for token in _BANNED:
        if token in code:
            return None, f"Banned token '{token}' found in generated code"

    try:
        ast.parse(code)
    except SyntaxError as exc:
        return None, f"SyntaxError: {exc}"

    # Write to a temp file so tracebacks have line numbers.
    # Use tempfile.gettempdir() instead of hardcoded /tmp (B108).
    fd, tmp_path = tempfile.mkstemp(suffix=".py", dir=tempfile.gettempdir())
    try:
        with os.fdopen(fd, "w") as f:
            f.write(code)
    except Exception:  # nosec B110 — close fd before re-raise
        os.close(fd)
        raise

    try:
        spec = importlib.util.spec_from_file_location("_gen_strategy", tmp_path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        cls = getattr(module, "GeneratedStrategy", None)
        if cls is None:
            return None, "No class named 'GeneratedStrategy' found"
        instance = cls()  # pylint: disable=not-callable
        return instance, None
    except (ImportError, AttributeError, SyntaxError, RuntimeError) as exc:
        return None, f"{type(exc).__name__}: {exc}\n{traceback.format_exc()}"
    finally:
        with contextlib.suppress(OSError):
            Path(tmp_path).unlink()


# ── quick backtest ────────────────────────────────────────────────────────────


def _run_backtest(
    strategy: Any,
    candles: list[dict],
    initial_balance: float = 10_000.0,
    position_pct: float = 0.10,
    commission: float = 0.0035,  # 35 bps — realistic XAUUSD spread + commission
) -> BacktestResult:
    """
    Walk-forward backtest on a list of OHLCV dicts.

    Calls strategy.analyze({"candles": window}) then strategy.generate_signal(analysis)
    on a rolling window, matching the real BaseStrategy contract.
    """
    try:
        import numpy as np

        from strategies.base import SignalType
    except ImportError as exc:
        logger.error("Backtest dependency missing: %s", exc)
        return BacktestResult(0, 0, 0, 0, 0, error="Missing dependency — check server logs")

    if len(candles) < 60:
        return BacktestResult(0, 0, 0, 0, 0, error="Not enough candle data")

    balance = initial_balance
    equity_curve: list[float] = [balance]
    position = 0.0  # positive = long units, negative = short units
    entry_price = 0.0
    wins = losses = 0

    for i in range(50, len(candles)):
        window = candles[max(0, i - 100) : i + 1]
        price = float(candles[i]["close"])

        # call the real two-step strategy API
        sig_type = None
        try:
            analysis = strategy.analyze({"candles": window})
            signal = strategy.generate_signal(analysis)
            if signal is not None:
                sig_type = signal.signal_type
        except (AttributeError, ValueError, RuntimeError) as _exc:
            logger.debug("Suppressed exception: %s", _exc)

        # close on opposite signal
        if position != 0 and (
            (position > 0 and sig_type == SignalType.SELL) or (position < 0 and sig_type == SignalType.BUY)
        ):
            pnl = position * (price - entry_price)
            pnl -= abs(position) * price * commission
            balance += pnl
            if pnl > 0:
                wins += 1
            else:
                losses += 1
            position = 0.0
            entry_price = 0.0

        # open new position
        if position == 0 and sig_type in (SignalType.BUY, SignalType.SELL):
            size = (balance * position_pct) / price
            position = size if sig_type == SignalType.BUY else -size
            entry_price = price
            balance -= abs(position) * price * commission

        equity_curve.append(balance + position * (price - entry_price))

    # close any open position at last price
    if position != 0:
        last_price = float(candles[-1]["close"])
        balance += position * (last_price - entry_price)

    eq = np.array(equity_curve, dtype=float)
    ret = np.diff(eq) / (eq[:-1] + 1e-9)

    sharpe = float(np.mean(ret) / (np.std(ret) + 1e-9) * np.sqrt(252 * 24))
    total_return = float((eq[-1] - eq[0]) / (eq[0] + 1e-9))
    peak = np.maximum.accumulate(eq)
    max_dd = float(np.min((eq - peak) / (peak + 1e-9)))
    total_trades = wins + losses
    win_rate = wins / total_trades if total_trades > 0 else 0.0

    return BacktestResult(
        sharpe=sharpe,
        total_return=total_return,
        max_drawdown=max_dd,
        win_rate=win_rate,
        trades=total_trades,
    )


# ── LLM agent ─────────────────────────────────────────────────────────────────


class LLMAgent:
    """
    Agentic strategy generator with iterative refinement.

    Supports Anthropic (Claude 3.5 Sonnet, default) and OpenAI (GPT-4o) backends.
    Backend is selected via LLM_BACKEND env var or the ``backend`` constructor arg.

    Parameters
    ----------
    api_key        : API key for the selected backend (falls back to env var)
    model          : Model name override (defaults to backend-specific env var)
    backend        : "anthropic" or "openai" (defaults to LLM_BACKEND env var)
    max_iterations : How many refinement loops before giving up
    target_sharpe  : Minimum acceptable Sharpe ratio
    candle_fetcher : Async callable(symbol, timeframe, count) → List[dict]
                     If None, the agent skips live backtesting.
    """

    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
        backend: str | None = None,
        max_iterations: int = 3,
        target_sharpe: float = 1.5,
        candle_fetcher: Any | None = None,
        enable_rag: bool = True,
    ):
        self._backend: str = (backend or _LLM_BACKEND).lower()

        if self._backend == "anthropic":
            key = api_key or _ANTHROPIC_API_KEY or ""
            if not key:
                raise ValueError(
                    "Anthropic API key required — set ANTHROPIC_API_KEY env var or pass api_key= to LLMAgent()"
                )
            self._anthropic_key = key
            self._openai_client = None
            self.model = model or _ANTHROPIC_MODEL
        elif self._backend == "openai":
            import openai as _openai

            key = api_key or _OPENAI_API_KEY or ""
            if not key:
                raise ValueError(
                    "OpenAI API key required — set OPENAI_API_KEY env var or pass api_key= to LLMAgent()"
                )
            self._anthropic_key = None
            self._openai_client = _openai.AsyncOpenAI(api_key=key)
            self.model = model or _OPENAI_MODEL
        else:
            raise ValueError(f"Unknown LLM backend '{self._backend}' — use 'anthropic' or 'openai'")

        self.max_iterations = max_iterations
        self.target_sharpe = target_sharpe
        self.candle_fetcher = candle_fetcher
        self._history: list[dict[str, str]] = []
        self._enable_rag = enable_rag
        self._vector_store = None  # lazy-initialised on first chat call

    # ── public ────────────────────────────────────────────────────────────────

    async def generate_strategy(
        self,
        prompt: str,
        symbol: str = "XAU_USD",
        timeframe: str = "H1",
        candle_count: int = 500,
    ) -> AgentResult:
        """
        Generate, compile, backtest, and optionally refine a strategy.

        Parameters
        ----------
        prompt       : Natural-language description of the desired strategy.
        symbol       : OANDA instrument to backtest on.
        timeframe    : Candle timeframe (H1, M15, D, …).
        candle_count : Number of historical candles to use.
        """
        logger.info("LLM agent starting — prompt: %s", prompt[:80])

        # fetch candles once
        candles: list[dict] = []
        if self.candle_fetcher:
            try:
                candles = await self.candle_fetcher(symbol, timeframe, candle_count)
                logger.info("Fetched %d candles for %s %s", len(candles), symbol, timeframe)
            except (OSError, ValueError, RuntimeError, AttributeError) as exc:
                logger.warning("Candle fetch failed: %s — backtesting disabled", exc)

        # reset conversation
        self._history = [{"role": "system", "content": _SYSTEM_PROMPT}]
        self._history.append({"role": "user", "content": prompt})

        best_result: AgentResult | None = None

        for iteration in range(1, self.max_iterations + 1):
            logger.info("Iteration %d/%d", iteration, self.max_iterations)

            # ── call LLM ─────────────────────────────────────────────────────
            code, llm_error = await self._call_llm()
            if llm_error:
                return AgentResult(
                    success=False,
                    strategy_code="",
                    strategy_name="GeneratedStrategy",
                    backtest=None,
                    iterations=iteration,
                    conversation=list(self._history),
                    error=llm_error,
                )

            # ── compile ───────────────────────────────────────────────────────
            instance, compile_error = _compile_strategy(code)
            if compile_error:
                logger.warning("Compile error (iter %d): %s", iteration, compile_error)
                self._history.append(
                    {
                        "role": "user",
                        "content": f"Your code had a compile error:\n{compile_error}\n\nFix it and output only the corrected code.",
                    }
                )
                continue

            # ── backtest ──────────────────────────────────────────────────────
            if candles:
                bt = _run_backtest(instance, candles)
                logger.info("Backtest iter %d: %s", iteration, bt.summary())
            else:
                # no candles — accept the code as-is
                bt = None

            result = AgentResult(
                success=bt is None or (bt.error is None and bt.sharpe >= self.target_sharpe),
                strategy_code=code,
                strategy_name="GeneratedStrategy",
                backtest=bt,
                iterations=iteration,
                conversation=list(self._history),
            )

            # track best so far
            if best_result is None or (bt and best_result.backtest and bt.sharpe > best_result.backtest.sharpe):
                best_result = result

            if result.success:
                logger.info("Target Sharpe reached on iteration %d", iteration)
                return result

            # ── reflect and retry ─────────────────────────────────────────────
            if iteration < self.max_iterations:
                reflect_msg = _REFLECT_PROMPT.format(
                    result_summary=bt.summary() if bt else "No backtest data",
                    target_sharpe=self.target_sharpe,
                    achieved_sharpe=bt.sharpe if bt else 0.0,
                )
                self._history.append({"role": "user", "content": reflect_msg})

        # return best attempt even if target not met
        if best_result:
            best_result.success = False
            return best_result

        return AgentResult(
            success=False,
            strategy_code="",
            strategy_name="GeneratedStrategy",
            backtest=None,
            iterations=self.max_iterations,
            error="All iterations exhausted without valid strategy",
        )

    async def chat(self, message: str) -> str:
        """
        Free-form chat with the trading assistant (maintains conversation history).

        Uses a dedicated trading-assistant system prompt (not the strategy
        engineer prompt).  Injects RAG context and live market snapshot before
        each call.  Trims history to _CHAT_MAX_HISTORY_TURNS to stay within
        the model's context window.
        """
        # Initialise with the trading-assistant system prompt (not strategy prompt)
        if not self._history:
            self._history = [{"role": "system", "content": _CHAT_SYSTEM_PROMPT}]
        elif self._history[0].get("content") == _SYSTEM_PROMPT:
            # Upgrade old sessions that were seeded with the strategy prompt
            self._history[0] = {"role": "system", "content": _CHAT_SYSTEM_PROMPT}

        # ── History trimming — keep system prompt + last N turns ──────────────
        max_msgs = 1 + _CHAT_MAX_HISTORY_TURNS * 2  # system + (user+assistant)*N
        if len(self._history) > max_msgs:
            self._history = [self._history[0], *self._history[-(max_msgs - 1) :]]

        # ── Live market context injection ─────────────────────────────────────
        live_context = self._build_live_context()

        # ── RAG context injection ─────────────────────────────────────────────
        rag_context = await self._fetch_rag_context()

        # Build ephemeral system additions (not persisted in history)
        ephemeral_parts: list[str] = []
        if live_context:
            ephemeral_parts.append(live_context)
        if rag_context:
            ephemeral_parts.append(rag_context)

        if ephemeral_parts:
            ephemeral_msg = "\n\n".join(ephemeral_parts)
            messages_with_context = [
                *list(self._history),
                {"role": "system", "content": ephemeral_msg},
                {"role": "user", "content": message},
            ]
            response_text, error = await self._call_llm_with_messages(messages_with_context)
            if not error:
                # Persist the exchange without the ephemeral context
                self._history.append({"role": "user", "content": message})
                self._history.append({"role": "assistant", "content": response_text})
        else:
            self._history.append({"role": "user", "content": message})
            response_text, error = await self._call_llm()
            if not error:
                self._history.append({"role": "assistant", "content": response_text})

        if error:
            return f"I'm unable to respond right now: {error}"
        return response_text

    def _build_live_context(self) -> str:
        """
        Build a brief live market snapshot for injection into the system context.

        Pulls current prices from the paper broker / price engine if available.
        Returns an empty string when no live data is accessible.
        """
        try:
            from app import app_state

            broker = getattr(app_state, "broker", None)
            if broker is None:
                return ""

            market_prices = getattr(broker, "market_prices", {})
            if not market_prices:
                return ""

            lines = ["## Live Market Snapshot"]
            for sym, price in list(market_prices.items())[:6]:
                lines.append(f"- {sym}: {price}")

            # Add InferenceEngine last signal if available
            try:
                engine = getattr(app_state, "inference_engine", None)
                if engine is not None:
                    h = engine.health()
                    lines.append(
                        f"\nML Engine: model={h.get('model_version', '?')} "
                        f"predictions={h.get('predict_count', 0)} "
                        f"fallbacks={h.get('fallback_count', 0)}"
                    )
            except (AttributeError, RuntimeError) as _exc:
                logger.debug("Suppressed exception: %s", _exc)

            return "\n".join(lines)
        except (OSError, ValueError, AttributeError, RuntimeError):
            return ""

    async def _fetch_rag_context(self) -> str:
        """
        Retrieve similar historical regimes from the vector store.

        Returns a formatted string for injection into the system prompt, or
        an empty string if the vector store is unavailable or empty.
        """
        if not self._enable_rag:
            return ""

        try:
            # Lazy-init vector store
            if self._vector_store is None:
                from research.vector_store import MarketVectorStore

                persist_dir = os.getenv("VECTORDB_DIR", "data/vectordb")
                self._vector_store = MarketVectorStore(persist_dir=persist_dir)

            # Load recent candles for context
            candles: list[dict] = []
            if self.candle_fetcher:
                try:
                    candles = await self.candle_fetcher("XAU_USD", "H1", 60)
                except (OSError, ValueError, RuntimeError) as _exc:
                    logger.debug("Suppressed exception: %s", _exc)

            if not candles:
                # Try loading from local CSV as fallback
                candles = _load_recent_candles_from_csv()

            if not candles:
                return ""

            rag_text = self._vector_store.rag_context_for_llm(candles, top_k=3)
            if "No similar" in rag_text:
                return ""

            return (
                "## Market Context (RAG — similar historical setups)\n"
                + rag_text
                + "\n\nUse this historical context when answering questions about "
                "current market conditions or trade decisions."
            )

        except (OSError, ValueError, RuntimeError) as exc:
            logger.debug("RAG context fetch failed (non-fatal): %s", exc)
            return ""

    # ── internals ─────────────────────────────────────────────────────────────

    @staticmethod
    def _strip_fences(content: str) -> str:
        """Remove accidental markdown code fences from LLM output."""
        if content.startswith("```"):
            lines = content.splitlines()
            content = "\n".join(ln for ln in lines if not ln.startswith("```")).strip()
        return content

    async def _call_llm_with_messages(self, messages: list[dict[str, str]]) -> tuple[str, str | None]:
        """Call the configured LLM backend with an explicit message list (used for RAG injection)."""
        if self._backend == "anthropic":
            return await self._call_anthropic(messages, update_history=False)
        return await self._call_openai(messages, update_history=False)

    async def _call_llm(self) -> tuple[str, str | None]:
        """Call the configured LLM backend using the current conversation history."""
        if self._backend == "anthropic":
            return await self._call_anthropic(self._history, update_history=True)
        return await self._call_openai(self._history, update_history=True)

    async def _call_anthropic(
        self,
        messages: list[dict[str, str]],
        *,
        update_history: bool,
    ) -> tuple[str, str | None]:
        """Call Anthropic Messages API with exponential backoff retry."""
        import asyncio

        import httpx

        # Anthropic requires the system prompt to be a top-level field, not a message.
        system_content: str = ""
        user_messages: list[dict[str, str]] = []
        for msg in messages:
            if msg["role"] == "system":
                system_content = (system_content + "\n\n" + msg["content"]).strip()
            else:
                user_messages.append({"role": msg["role"], "content": msg["content"]})

        payload: dict[str, Any] = {
            "model": self.model,
            "max_tokens": _LLM_MAX_TOKENS,
            "temperature": 0.3,
            "messages": user_messages,
        }
        if system_content:
            payload["system"] = system_content

        headers = {
            "x-api-key": self._anthropic_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }

        last_error: str = ""
        for attempt in range(1, _LLM_MAX_RETRIES + 1):
            try:
                async with httpx.AsyncClient(timeout=120.0) as client:
                    resp = await client.post(
                        "https://api.anthropic.com/v1/messages",
                        headers=headers,
                        json=payload,
                    )
                    resp.raise_for_status()
                    data = resp.json()
                    content = self._strip_fences(data["content"][0]["text"].strip())
                    if update_history:
                        self._history.append({"role": "assistant", "content": content})
                    return content, None
            except httpx.HTTPStatusError as exc:
                status = exc.response.status_code
                if status == 401:
                    return "", "Invalid Anthropic API key"
                # Retry on transient overload / rate-limit responses
                if status in (429, 503, 529):
                    last_error = f"Anthropic transient error {status}"
                    delay = _LLM_RETRY_BASE_DELAY * (2 ** (attempt - 1))
                    logger.warning("%s — retry %d/%d in %.1fs", last_error, attempt, _LLM_MAX_RETRIES, delay)
                    await asyncio.sleep(delay)
                    continue
                return "", f"Anthropic API error {status}: {exc.response.text[:200]}"
            except httpx.ConnectError as exc:
                last_error = f"Anthropic connection error: {exc}"
                delay = _LLM_RETRY_BASE_DELAY * (2 ** (attempt - 1))
                logger.warning("%s — retry %d/%d in %.1fs", last_error, attempt, _LLM_MAX_RETRIES, delay)
                await asyncio.sleep(delay)
            except (OSError, ValueError, RuntimeError, KeyError) as exc:
                return "", f"LLM call failed: {exc}"

        return "", f"Anthropic call failed after {_LLM_MAX_RETRIES} retries: {last_error}"

    async def _call_openai(
        self,
        messages: list[dict[str, str]],
        *,
        update_history: bool,
    ) -> tuple[str, str | None]:
        """Call OpenAI Chat Completions API with exponential backoff retry.

        Reasoning models (o-series) require ``max_completion_tokens`` instead of
        ``max_tokens`` and do not accept a ``temperature`` parameter.
        """
        import asyncio

        import openai as _openai

        is_reasoning = self.model in _OPENAI_REASONING_MODELS
        create_kwargs: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "max_completion_tokens" if is_reasoning else "max_tokens": _LLM_MAX_TOKENS,
        }
        if not is_reasoning:
            create_kwargs["temperature"] = 0.3

        last_error: str = ""
        for attempt in range(1, _LLM_MAX_RETRIES + 1):
            try:
                response = await self._openai_client.chat.completions.create(**create_kwargs)
                content = self._strip_fences(response.choices[0].message.content.strip())
                if update_history:
                    self._history.append({"role": "assistant", "content": content})
                return content, None
            except _openai.AuthenticationError:
                return "", "Invalid OpenAI API key"
            except _openai.RateLimitError as exc:
                last_error = f"OpenAI rate limit: {exc}"
                delay = _LLM_RETRY_BASE_DELAY * (2 ** (attempt - 1))
                logger.warning("%s — retry %d/%d in %.1fs", last_error, attempt, _LLM_MAX_RETRIES, delay)
                await asyncio.sleep(delay)
            except _openai.InternalServerError as exc:
                last_error = f"OpenAI server error: {exc}"
                delay = _LLM_RETRY_BASE_DELAY * (2 ** (attempt - 1))
                logger.warning("%s — retry %d/%d in %.1fs", last_error, attempt, _LLM_MAX_RETRIES, delay)
                await asyncio.sleep(delay)
            except _openai.APIConnectionError as exc:
                last_error = f"OpenAI connection error: {exc}"
                delay = _LLM_RETRY_BASE_DELAY * (2 ** (attempt - 1))
                logger.warning("%s — retry %d/%d in %.1fs", last_error, attempt, _LLM_MAX_RETRIES, delay)
                await asyncio.sleep(delay)
            except (OSError, ValueError, RuntimeError) as exc:
                return "", f"LLM call failed: {exc}"

        return "", f"OpenAI call failed after {_LLM_MAX_RETRIES} retries: {last_error}"


# ── convenience factory ───────────────────────────────────────────────────────


def create_agent(
    candle_source=None,
    api_key: str | None = None,
    model: str | None = None,
    backend: str | None = None,
    # Backwards-compat alias — remove after all call sites are updated.
    oanda_stream=None,
    **kwargs,
) -> LLMAgent:
    """
    Create an LLMAgent with an optional historical candle source.

    Parameters
    ----------
    candle_source : Any object with a ``get_candles(symbol, timeframe, count)``
                    coroutine.  Typically an ``OANDAStream`` execution broker
                    used for historical warm-up data only.
                    Live price ticks come from ``data_feed.NuclearStreamer``.
    api_key       : API key for the selected backend (falls back to env var).
    model         : Model name override (defaults to backend-specific env var).
    backend       : "anthropic" (default) or "openai" — overrides LLM_BACKEND env var.
    oanda_stream  : Deprecated alias for ``candle_source``.

    Example
    -------
        from brokers.oanda_stream import OANDAStream
        broker = OANDAStream(api_key=..., account_id=..., instruments=["XAU_USD"])
        await broker.__aenter__()
        await broker.connect()

        agent = create_agent(candle_source=broker)
        result = await agent.generate_strategy(
            "Create a mean-reversion strategy on XAUUSD using Bollinger Bands"
        )
    """
    _log = logging.getLogger(__name__)

    # Resolve deprecated alias.
    if candle_source is None and oanda_stream is not None:
        _log.warning("create_agent: 'oanda_stream' parameter is deprecated — use 'candle_source' instead.")
        candle_source = oanda_stream

    candle_fetcher = None
    if candle_source is not None:

        async def _fetcher(symbol: str, timeframe: str, count: int) -> list[dict]:
            return await candle_source.get_candles(symbol, timeframe, count)

        candle_fetcher = _fetcher

    return LLMAgent(
        api_key=api_key,
        model=model,
        backend=backend,
        candle_fetcher=candle_fetcher,
        **kwargs,
    )
