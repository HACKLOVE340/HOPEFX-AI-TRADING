# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
strategies/registry.py — resolve a strategy *name* to a strategy *instance*
===========================================================================

``strategies/__init__.py`` has told contributors since it was written to
"Register in strategies/manager.py STRATEGY_REGISTRY". No such registry exists,
in that module or anywhere else. Every caller that wanted a strategy by name had
to invent its own lookup, and the one in ``api/advanced_trading.py`` did not:
``_run_real_backtest`` accepted ``strategy_name`` and never used it, so the A/B
endpoint backtested nothing and compared two identical empty runs.

This is that registry.

Two constructor conventions
---------------------------
The eight backtestable strategies were written by different hands and take their
arguments two different ways::

    RSIStrategy(config: StrategyConfig, *_args, period=14, ...)
    EMAcrossoverStrategy(name: str, symbol: str, config, fast_period=12, ...)

``build()`` picks the right one by inspecting the first parameter name rather
than hardcoding a table, so a strategy that changes convention keeps working and
a new one is picked up without a second edit here.

Only strategies that accept an OHLCV DataFrame are registered
-------------------------------------------------------------
``BacktestEngine`` drives strategies from bar data. Three classes
(``ITS8OSStrategy``, ``MovingAverageCrossover``, ``SMCICTStrategy``) implement
only the dict-analysis path — ``analyze(dict) -> generate_signal(dict) ->
Signal`` — and cannot be run from bars without an analysis pipeline that does not
exist here. Registering them would mean a backtest that silently produces zero
trades, which is exactly the failure this module was written to remove. They are
listed in ``UNSUPPORTED`` with the reason, so asking for one gets an explanation
instead of a flat "unknown strategy".
"""

from __future__ import annotations

import inspect
from typing import Any

from strategies.base import BaseStrategy, StrategyConfig
from strategies.bollinger_bands import BollingerBandsStrategy
from strategies.breakout import BreakoutStrategy
from strategies.ema_crossover import EMAcrossoverStrategy
from strategies.macd_strategy import MACDStrategy
from strategies.mean_reversion import MeanReversionStrategy
from strategies.pullback_strategy import PullbackStrategy
from strategies.rsi_strategy import RSIStrategy
from strategies.stochastic import StochasticStrategy

__all__ = [
    "STRATEGY_REGISTRY",
    "UNSUPPORTED",
    "UnknownStrategyError",
    "available_strategies",
    "build",
    "normalise",
]


class UnknownStrategyError(ValueError):
    """Raised when a strategy name cannot be resolved to a runnable class."""


#: Canonical name → class. Keys are lower-case with no separators; ``normalise``
#: maps user input onto them, so "RSI Strategy", "rsi_strategy" and "RSI" all
#: land on the same entry.
STRATEGY_REGISTRY: dict[str, type[BaseStrategy]] = {
    "rsi": RSIStrategy,
    "macd": MACDStrategy,
    "bollingerbands": BollingerBandsStrategy,
    "breakout": BreakoutStrategy,
    "emacrossover": EMAcrossoverStrategy,
    "meanreversion": MeanReversionStrategy,
    "pullback": PullbackStrategy,
    "stochastic": StochasticStrategy,
}

#: Names that exist as strategies but cannot be driven from OHLCV bars, with the
#: reason. Kept separate from "unknown" so the error can say which it is.
UNSUPPORTED: dict[str, str] = {
    "macrossover": (
        "MovingAverageCrossover implements only the dict-analysis path "
        "(analyze() → generate_signal(dict) → Signal) and cannot be driven from "
        "OHLCV bars by BacktestEngine."
    ),
    "its8os": (
        "ITS8OSStrategy implements only the dict-analysis path and cannot be driven from OHLCV bars by BacktestEngine."
    ),
    "smcict": (
        "SMCICTStrategy implements only the dict-analysis path and cannot be driven from OHLCV bars by BacktestEngine."
    ),
}

#: Aliases a user or the UI might plausibly send.
_ALIASES: dict[str, str] = {
    "rsistrategy": "rsi",
    "macdstrategy": "macd",
    "bollinger": "bollingerbands",
    "bb": "bollingerbands",
    "ema": "emacrossover",
    "emacrossoverstrategy": "emacrossover",
    "breakoutstrategy": "breakout",
    "meanreversionstrategy": "meanreversion",
    "pullbackstrategy": "pullback",
    "stochasticstrategy": "stochastic",
    "movingaveragecrossover": "macrossover",
    "ma": "macrossover",
    "its8osstrategy": "its8os",
    "smcictstrategy": "smcict",
}


def normalise(name: str) -> str:
    """Fold a user-supplied strategy name onto a registry key."""
    key = "".join(ch for ch in str(name).lower() if ch.isalnum())
    return _ALIASES.get(key, key)


def available_strategies() -> list[str]:
    """Runnable strategy names, sorted. Safe to put in an error message."""
    return sorted(STRATEGY_REGISTRY)


def build(
    name: str,
    symbol: str,
    timeframe: str = "1h",
    **params: Any,
) -> BaseStrategy:
    """Instantiate the strategy called *name* for *symbol*.

    Raises
    ------
    UnknownStrategyError
        When the name is not registered. The message lists what is, and says
        explicitly when the name exists but cannot be backtested from bars —
        those two cases used to collapse into one unhelpful 422.
    """
    key = normalise(name)

    if key in UNSUPPORTED:
        raise UnknownStrategyError(
            f"Strategy {name!r} is not backtestable: {UNSUPPORTED[key]} "
            f"Runnable strategies: {', '.join(available_strategies())}."
        )

    cls = STRATEGY_REGISTRY.get(key)
    if cls is None:
        raise UnknownStrategyError(f"Unknown strategy {name!r}. Available: {', '.join(available_strategies())}.")

    config = StrategyConfig(name=key, symbol=symbol, timeframe=timeframe)

    # Which convention does this constructor use? First parameter after `self`
    # is either `config` or `name`.
    try:
        sig = inspect.signature(cls.__init__)
        first = [p for p in sig.parameters if p != "self"][0]
    except (ValueError, IndexError):  # pragma: no cover — defensive
        first = "config"

    if first == "name":
        return cls(key, symbol, config, **params)  # type: ignore[call-arg]
    return cls(config, **params)  # type: ignore[call-arg]
