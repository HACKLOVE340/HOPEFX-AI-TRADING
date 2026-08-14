# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
backtesting/strategy_adapter.py — run a ``strategies/`` class in BacktestEngine
==============================================================================

``BacktestEngine`` drives its strategies like this::

    signals = strategy.generate_signals(timestamp=..., prices=..., data=...)
    for signal in signals:
        self._process_signal(signal, ...)   # signal["symbol"], signal["action"]

Nothing in ``strategies/`` implements ``generate_signals``. Every class there
implements ``generate_signal`` (singular) and returns either a ``Signal`` object
or a dict shaped ``{"type": "BUY"|"SELL"|"HOLD", "confidence": float}``. So
``engine.add_strategy(RSIStrategy(...))`` produced an ``AttributeError`` on the
first bar, which the engine's ``except Exception: logger.error(...)`` swallowed —
and the backtest completed "successfully" with zero trades and a 0.00% return.

That is the worst possible failure mode for a backtester: not an error, a
result. This adapter is the missing translation layer.

What it does
------------
* Slices the symbol's OHLCV frame to bars at or before the current timestamp,
  so the strategy sees exactly the history a live run would have.
* Calls the strategy's DataFrame path and normalises both dict shapes in use —
  seven strategies key the direction as ``type``; ``PullbackStrategy`` keys it as
  ``signal_type`` and also supplies ``stop_loss``/``take_profit``.
* Holds its own flat/long state so a strategy that reports "oversold" on forty
  consecutive bars opens one position, not forty. The rule strategies report a
  *condition*, not a transition, so without this the engine would pyramid until
  it ran out of cash and every backtest would measure position sizing rather
  than the strategy.
* Marks exits with ``exit: True`` so the engine closes the whole open position.
  Kelly sizing computes an entry quantity from equity and would otherwise
  part-close a position by an unrelated amount.

Long/flat only
--------------
Entries are long, exits are back to flat; a SELL while flat is ignored rather
than opened as a short. The engine nets by quantity, so entering a short from a
Kelly-sized quantity while an unrelated long is open produces a position neither
side asked for. Long-only is stated here and asserted in the tests rather than
left for a reader to infer from an equity curve.
"""

from __future__ import annotations

import logging
import math
from datetime import datetime
from typing import Any

import pandas as pd

logger = logging.getLogger(__name__)

__all__ = ["BacktestStrategyAdapter", "StrategyAdapterError", "normalise_signal"]

_BUY = {"BUY", "LONG", "STRONG_BUY"}
_SELL = {"SELL", "SHORT", "STRONG_SELL", "CLOSE", "CLOSE_LONG", "EXIT"}


class StrategyAdapterError(RuntimeError):
    """Raised when a strategy cannot be driven from OHLCV bars at all.

    Deliberately *not* caught by the adapter: the engine swallows strategy
    exceptions into a zero-trade run, and a backtest that silently ran no
    strategy is a lie. Callers should let this surface.
    """


def normalise_signal(raw: Any) -> tuple[str, float]:
    """Return ``(direction, confidence)`` from any signal shape in this repo.

    Direction is one of ``"BUY"``, ``"SELL"``, ``"HOLD"``. Unrecognised shapes
    return ``("HOLD", 0.0)`` rather than guessing a direction — the one thing
    worse than no trade is a trade in an invented direction.
    """
    if raw is None:
        return "HOLD", 0.0

    if isinstance(raw, dict):
        # Seven strategies use "type"; PullbackStrategy uses "signal_type".
        value = raw.get("type", raw.get("signal_type"))
        confidence = raw.get("confidence", 0.0)
    else:
        # Signal dataclass: signal_type is a SignalType enum.
        value = getattr(raw, "signal_type", None)
        confidence = getattr(raw, "confidence", 0.0)

    if value is None:
        return "HOLD", 0.0
    text = str(getattr(value, "value", value)).upper()

    try:
        conf = float(confidence)
    except (TypeError, ValueError):
        conf = 0.0

    if text in _BUY:
        return "BUY", conf
    if text in _SELL:
        return "SELL", conf
    return "HOLD", conf


class BacktestStrategyAdapter:
    """Wrap a ``strategies/`` class so ``BacktestEngine`` can run it."""

    def __init__(
        self,
        strategy: Any,
        symbol: str,
        *,
        min_confidence: float = 0.0,
        atr_period: int = 14,
    ) -> None:
        if not hasattr(strategy, "generate_signal"):
            raise StrategyAdapterError(f"{type(strategy).__name__} has no generate_signal(); it cannot be backtested.")
        self.strategy = strategy
        self.symbol = symbol
        self.min_confidence = min_confidence
        self.atr_period = atr_period

        self.position: str = "flat"  # "flat" | "long"
        #: Bars where the strategy raised. Surfaced by the engine rather than
        #: logged and forgotten — a run where every bar raised must not be
        #: reported as a flat equity curve.
        self.errors: list[str] = []

    # ── engine contract ───────────────────────────────────────────────────────

    @property
    def name(self) -> str:
        return getattr(self.strategy, "name", type(self.strategy).__name__)

    def generate_signals(
        self,
        timestamp: datetime,
        prices: dict[str, float],
        data: dict[str, pd.DataFrame],
    ) -> list[dict]:
        frame = data.get(self.symbol)
        if frame is None or frame.empty:
            return []

        history = frame[frame["timestamp"] <= timestamp]
        if len(history) < 2:
            return []

        try:
            raw = self.strategy.generate_signal(history)
        except Exception as exc:
            # Recorded, not swallowed: `errors` is read back by the caller.
            self.errors.append(f"{timestamp}: {type(exc).__name__}: {exc}")
            return []

        direction, confidence = normalise_signal(raw)
        if direction == "HOLD" or confidence < self.min_confidence:
            return []

        price = prices.get(self.symbol)
        if not price or price <= 0:
            return []

        if direction == "BUY" and self.position == "flat":
            self.position = "long"
            return [
                {
                    "symbol": self.symbol,
                    "action": "buy",
                    "size": 1.0,
                    "confidence": confidence,
                    "stop_distance": self._stop_distance(history, price),
                    # No tp_distance: these strategies do not emit targets, and
                    # inventing one would feed the engine's min_rr_ratio filter a
                    # number the strategy never produced.
                    "tp_distance": 0.0,
                }
            ]

        if direction == "SELL" and self.position == "long":
            self.position = "flat"
            return [
                {
                    "symbol": self.symbol,
                    "action": "sell",
                    "exit": True,
                    "confidence": confidence,
                    "stop_distance": 0.0,
                    "tp_distance": 0.0,
                }
            ]

        return []

    # ── helpers ───────────────────────────────────────────────────────────────

    def _stop_distance(self, history: pd.DataFrame, price: float) -> float:
        """ATR over ``atr_period`` bars, falling back to 1% of price.

        The engine's Kelly sizer divides risk capital by this, so a zero or NaN
        here silently becomes a fixed-size position.
        """
        try:
            window = history.tail(self.atr_period + 1)
            if len(window) < 2 or not {"high", "low", "close"} <= set(window.columns):
                return price * 0.01
            high = window["high"].astype(float)
            low = window["low"].astype(float)
            prev_close = window["close"].astype(float).shift(1)
            # shift(1) leaves the first row's previous close NaN, so the first
            # true range is undefined. Dropped explicitly rather than left to
            # pandas' skipna default — this feeds the Kelly sizer, and an
            # implicit NaN policy on a position-sizing input is how a silent
            # fixed-size position gets substituted for a risk-based one.
            true_range = pd.concat(
                [high - low, (high - prev_close).abs(), (low - prev_close).abs()],
                axis=1,
            ).max(axis=1)
            atr = float(true_range.tail(self.atr_period).dropna().mean())
        except Exception:
            return price * 0.01
        if not math.isfinite(atr) or atr <= 0:
            return price * 0.01
        return atr
