"""
HOPEFX LLM Agent — real GPT-4 strategy generation and execution loop.

Flow
----
1. User submits a natural-language prompt ("Create ICT + LSTM ensemble Sharpe > 2.5").
2. Agent calls GPT-4 to generate a complete Python strategy class.
3. Generated code is sandboxed, compiled, and instantiated.
4. Strategy is back-tested against real OANDA candle data.
5. If Sharpe < target the agent reflects on the result and iterates (up to
   max_iterations).
6. Accepted strategies are registered with StrategyManager and optionally
   deployed live.

All GPT-4 calls are async.  The agent maintains a conversation history so
follow-up refinements have full context.

Environment variables
---------------------
    OPENAI_API_KEY   — required
    OPENAI_MODEL     — default "gpt-4o"
"""

from __future__ import annotations

import ast
import asyncio
import importlib.util
import inspect
import logging
import os
import sys
import tempfile
import textwrap
import traceback
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

import openai

logger = logging.getLogger(__name__)

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
from typing import Optional, Dict, Any
from strategies.base import BaseStrategy, Signal, SignalType, StrategyConfig

class GeneratedStrategy(BaseStrategy):
    \"\"\"Short description of the strategy logic.\"\"\"

    def __init__(self):
        super().__init__(StrategyConfig(
            name="GeneratedStrategy",
            symbol="XAU_USD",
            timeframe="H1",
        ))

    def analyze(self, data: Dict[str, Any]) -> Dict[str, Any]:
        candles = data.get("candles", [])
        if len(candles) < 50:
            return {"signal": "hold"}
        df = pd.DataFrame(candles)
        close = df["close"].astype(float)
        rsi = ta.momentum.RSIIndicator(close, window=14).rsi().iloc[-1]
        return {"rsi": rsi, "price": float(close.iloc[-1])}

    def generate_signal(self, analysis: Dict[str, Any]) -> Optional[Signal]:
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
    sharpe:       float
    total_return: float
    max_drawdown: float
    win_rate:     float
    trades:       int
    error:        Optional[str] = None

    def summary(self) -> str:
        if self.error:
            return f"Backtest failed: {self.error}"
        return (
            f"Sharpe={self.sharpe:.3f}  Return={self.total_return*100:.2f}%  "
            f"MaxDD={self.max_drawdown*100:.2f}%  WinRate={self.win_rate*100:.1f}%  "
            f"Trades={self.trades}"
        )


@dataclass
class AgentResult:
    success:         bool
    strategy_code:   str
    strategy_name:   str
    backtest:        Optional[BacktestResult]
    iterations:      int
    conversation:    List[Dict[str, str]] = field(default_factory=list)
    error:           Optional[str] = None
    strategy_id:     str = field(default_factory=lambda: str(uuid.uuid4())[:8])


# ── sandbox execution ─────────────────────────────────────────────────────────

def _compile_strategy(code: str) -> Tuple[Optional[Any], Optional[str]]:
    """
    Compile and instantiate a GeneratedStrategy from raw source code.

    Returns (instance, None) on success or (None, error_message) on failure.
    """
    # Static safety check — reject dangerous imports
    _BANNED = {"subprocess", "os.system", "eval", "exec", "open",
               "__import__", "socket", "requests", "aiohttp", "httpx"}
    for token in _BANNED:
        if token in code:
            return None, f"Banned token '{token}' found in generated code"

    try:
        tree = ast.parse(code)
    except SyntaxError as exc:
        return None, f"SyntaxError: {exc}"

    # Write to a temp file so tracebacks have line numbers
    with tempfile.NamedTemporaryFile(
        suffix=".py", mode="w", delete=False, dir="/tmp"
    ) as f:
        f.write(code)
        tmp_path = f.name

    try:
        spec   = importlib.util.spec_from_file_location("_gen_strategy", tmp_path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        cls    = getattr(module, "GeneratedStrategy", None)
        if cls is None:
            return None, "No class named 'GeneratedStrategy' found"
        instance = cls()
        return instance, None
    except Exception as exc:
        return None, f"{type(exc).__name__}: {exc}\n{traceback.format_exc()}"
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass


# ── quick backtest ────────────────────────────────────────────────────────────

def _run_backtest(
    strategy:        Any,
    candles:         List[Dict],
    initial_balance: float = 10_000.0,
    position_pct:    float = 0.10,
    commission:      float = 0.0035,  # 35 bps — realistic XAUUSD spread + commission
) -> BacktestResult:
    """
    Walk-forward backtest on a list of OHLCV dicts.

    Calls strategy.analyze({"candles": window}) then strategy.generate_signal(analysis)
    on a rolling window, matching the real BaseStrategy contract.
    """
    try:
        import numpy as np
        import pandas as pd
        from strategies.base import SignalType
    except ImportError as exc:
        return BacktestResult(0, 0, 0, 0, 0, error=str(exc))

    if len(candles) < 60:
        return BacktestResult(0, 0, 0, 0, 0, error="Not enough candle data")

    balance      = initial_balance
    equity_curve: List[float] = [balance]
    position     = 0.0   # positive = long units, negative = short units
    entry_price  = 0.0
    wins = losses = 0

    for i in range(50, len(candles)):
        window = candles[max(0, i - 100): i + 1]
        price  = float(candles[i]["close"])

        # call the real two-step strategy API
        sig_type = None
        try:
            analysis = strategy.analyze({"candles": window})
            signal   = strategy.generate_signal(analysis)
            if signal is not None:
                sig_type = signal.signal_type
        except Exception:
            pass

        # close on opposite signal
        if position != 0:
            if (position > 0 and sig_type == SignalType.SELL) or \
               (position < 0 and sig_type == SignalType.BUY):
                pnl = position * (price - entry_price)
                pnl -= abs(position) * price * commission
                balance += pnl
                if pnl > 0:
                    wins += 1
                else:
                    losses += 1
                position    = 0.0
                entry_price = 0.0

        # open new position
        if position == 0 and sig_type in (SignalType.BUY, SignalType.SELL):
            size        = (balance * position_pct) / price
            position    = size if sig_type == SignalType.BUY else -size
            entry_price = price
            balance    -= abs(position) * price * commission

        equity_curve.append(balance + position * (price - entry_price))

    # close any open position at last price
    if position != 0:
        last_price = float(candles[-1]["close"])
        balance   += position * (last_price - entry_price)

    eq  = np.array(equity_curve, dtype=float)
    ret = np.diff(eq) / (eq[:-1] + 1e-9)

    sharpe       = float(np.mean(ret) / (np.std(ret) + 1e-9) * np.sqrt(252 * 24))
    total_return = float((eq[-1] - eq[0]) / (eq[0] + 1e-9))
    peak         = np.maximum.accumulate(eq)
    max_dd       = float(np.min((eq - peak) / (peak + 1e-9)))
    total_trades = wins + losses
    win_rate     = wins / total_trades if total_trades > 0 else 0.0

    return BacktestResult(
        sharpe       = sharpe,
        total_return = total_return,
        max_drawdown = max_dd,
        win_rate     = win_rate,
        trades       = total_trades,
    )


# ── LLM agent ─────────────────────────────────────────────────────────────────

class LLMAgent:
    """
    Agentic GPT-4 strategy generator with iterative refinement.

    Parameters
    ----------
    api_key        : OpenAI API key (falls back to OPENAI_API_KEY env var)
    model          : OpenAI model name (default: gpt-4o)
    max_iterations : How many refinement loops before giving up
    target_sharpe  : Minimum acceptable Sharpe ratio
    candle_fetcher : Async callable(symbol, timeframe, count) → List[Dict]
                     If None, the agent skips live backtesting.
    """

    def __init__(
        self,
        api_key:         Optional[str] = None,
        model:           str           = "gpt-4o",
        max_iterations:  int           = 3,
        target_sharpe:   float         = 1.5,
        candle_fetcher:  Optional[Any] = None,
    ):
        key = api_key or os.environ.get("OPENAI_API_KEY", "")
        if not key:
            raise ValueError(
                "OpenAI API key required — set OPENAI_API_KEY env var "
                "or pass api_key= to LLMAgent()"
            )
        self._client         = openai.AsyncOpenAI(api_key=key)
        self.model           = model
        self.max_iterations  = max_iterations
        self.target_sharpe   = target_sharpe
        self.candle_fetcher  = candle_fetcher
        self._history: List[Dict[str, str]] = []

    # ── public ────────────────────────────────────────────────────────────────

    async def generate_strategy(
        self,
        prompt:     str,
        symbol:     str = "XAU_USD",
        timeframe:  str = "H1",
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
        candles: List[Dict] = []
        if self.candle_fetcher:
            try:
                candles = await self.candle_fetcher(symbol, timeframe, candle_count)
                logger.info("Fetched %d candles for %s %s", len(candles), symbol, timeframe)
            except Exception as exc:
                logger.warning("Candle fetch failed: %s — backtesting disabled", exc)

        # reset conversation
        self._history = [{"role": "system", "content": _SYSTEM_PROMPT}]
        self._history.append({"role": "user", "content": prompt})

        best_result: Optional[AgentResult] = None

        for iteration in range(1, self.max_iterations + 1):
            logger.info("Iteration %d/%d", iteration, self.max_iterations)

            # ── call GPT-4 ────────────────────────────────────────────────────
            code, llm_error = await self._call_llm()
            if llm_error:
                return AgentResult(
                    success       = False,
                    strategy_code = "",
                    strategy_name = "GeneratedStrategy",
                    backtest      = None,
                    iterations    = iteration,
                    conversation  = list(self._history),
                    error         = llm_error,
                )

            # ── compile ───────────────────────────────────────────────────────
            instance, compile_error = _compile_strategy(code)
            if compile_error:
                logger.warning("Compile error (iter %d): %s", iteration, compile_error)
                self._history.append({
                    "role":    "user",
                    "content": f"Your code had a compile error:\n{compile_error}\n\nFix it and output only the corrected code.",
                })
                continue

            # ── backtest ──────────────────────────────────────────────────────
            if candles:
                bt = _run_backtest(instance, candles)
                logger.info("Backtest iter %d: %s", iteration, bt.summary())
            else:
                # no candles — accept the code as-is
                bt = None

            result = AgentResult(
                success       = bt is None or (bt.error is None and bt.sharpe >= self.target_sharpe),
                strategy_code = code,
                strategy_name = "GeneratedStrategy",
                backtest      = bt,
                iterations    = iteration,
                conversation  = list(self._history),
            )

            # track best so far
            if best_result is None or (
                bt and best_result.backtest and
                bt.sharpe > best_result.backtest.sharpe
            ):
                best_result = result

            if result.success:
                logger.info("Target Sharpe reached on iteration %d", iteration)
                return result

            # ── reflect and retry ─────────────────────────────────────────────
            if iteration < self.max_iterations:
                reflect_msg = _REFLECT_PROMPT.format(
                    result_summary  = bt.summary() if bt else "No backtest data",
                    target_sharpe   = self.target_sharpe,
                    achieved_sharpe = bt.sharpe if bt else 0.0,
                )
                self._history.append({"role": "user", "content": reflect_msg})

        # return best attempt even if target not met
        if best_result:
            best_result.success = False
            return best_result

        return AgentResult(
            success       = False,
            strategy_code = "",
            strategy_name = "GeneratedStrategy",
            backtest      = None,
            iterations    = self.max_iterations,
            error         = "All iterations exhausted without valid strategy",
        )

    async def chat(self, message: str) -> str:
        """
        Free-form chat with the agent (maintains conversation history).
        Useful for asking questions about strategies, markets, or code.
        """
        if not self._history:
            self._history = [{"role": "system", "content": _SYSTEM_PROMPT}]
        self._history.append({"role": "user", "content": message})
        code, error = await self._call_llm()
        if error:
            return f"Error: {error}"
        return code

    # ── internals ─────────────────────────────────────────────────────────────

    async def _call_llm(self) -> Tuple[str, Optional[str]]:
        """Call GPT-4 and return (content, error)."""
        try:
            response = await self._client.chat.completions.create(
                model       = self.model,
                messages    = self._history,
                temperature = 0.3,
                max_tokens  = 2048,
            )
            content = response.choices[0].message.content.strip()
            # strip accidental markdown fences
            if content.startswith("```"):
                lines   = content.splitlines()
                content = "\n".join(
                    l for l in lines
                    if not l.startswith("```")
                ).strip()
            self._history.append({"role": "assistant", "content": content})
            return content, None
        except openai.AuthenticationError:
            return "", "Invalid OpenAI API key"
        except openai.RateLimitError:
            return "", "OpenAI rate limit exceeded"
        except openai.APIConnectionError as exc:
            return "", f"OpenAI connection error: {exc}"
        except Exception as exc:
            return "", f"LLM call failed: {exc}"


# ── convenience factory ───────────────────────────────────────────────────────

def create_agent(
    oanda_stream=None,
    api_key: Optional[str] = None,
    model:   str           = "gpt-4o",
    **kwargs,
) -> LLMAgent:
    """
    Create an LLMAgent wired to an OANDAStream for live candle data.

        agent = create_agent(oanda_stream=stream)
        result = await agent.generate_strategy(
            "Create a mean-reversion strategy on XAUUSD using Bollinger Bands"
        )
    """
    fetcher = None
    if oanda_stream is not None:
        async def fetcher(symbol: str, timeframe: str, count: int) -> List[Dict]:
            return await oanda_stream.get_candles(symbol, timeframe, count)

    return LLMAgent(
        api_key        = api_key,
        model          = model,
        candle_fetcher = fetcher,
        **kwargs,
    )
