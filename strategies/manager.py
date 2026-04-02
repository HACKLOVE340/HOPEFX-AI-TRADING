# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
strategies/manager.py
======================
Central strategy management system.

Features:
  - Strategy registration, enable/disable, start/stop
  - Regime-based strategy selection (trending/ranging/volatile)
  - Signal aggregation and deduplication (strongest signal wins per symbol+action)
  - Per-strategy performance tracking (signals, trades, win rate, P&L, Sharpe)
  - Subscription tier gating via require_plan decorator
  - Prometheus metrics for signal counts and strategy health

Subscription gating (enforced at the API layer via require_plan):
  Starter      — MA Crossover, EMA Crossover, RSI Reversal, Ichimoku
  Professional — MACD, Bollinger Bands, Breakout, Mean Reversion, Stochastic
  Enterprise   — SMC/ICT
  Elite        — Strategy Brain (ML consensus), custom strategies
"""

from __future__ import annotations

import abc
import logging
import math
from dataclasses import dataclass, field
from datetime import datetime, timezone

UTC = timezone.utc
from enum import Enum
from typing import Any

import numpy as np

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class StrategyType(Enum):
    TREND_FOLLOWING = "trend_following"
    MEAN_REVERSION = "mean_reversion"
    BREAKOUT = "breakout"
    MOMENTUM = "momentum"
    ARBITRAGE = "arbitrage"


try:
    from strategies.base import StrategyStatus
except ImportError:

    class StrategyStatus(Enum):  # type: ignore[no-redef]
        """Fallback when strategies.base is unavailable."""

        IDLE = "IDLE"
        RUNNING = "RUNNING"
        PAUSED = "PAUSED"
        STOPPED = "STOPPED"
        ERROR = "ERROR"


# Minimum subscription tier required per strategy name.
# Enforced at the API layer via require_plan; also checked in generate_signals().
STRATEGY_PLAN_REQUIREMENTS: dict[str, str] = {
    "TrendFollowing": "starter",
    "EMAcrossover": "starter",
    "RSIReversal": "starter",
    "Ichimoku": "starter",
    "MACD": "professional",
    "BollingerBands": "professional",
    "Breakout": "professional",
    "MeanReversion": "professional",
    "Stochastic": "professional",
    "SMC_ICT": "enterprise",
    "StrategyBrain": "elite",
}

_PLAN_ORDER = ["trial", "starter", "professional", "enterprise", "elite"]


def _plan_satisfies(user_plan: str, required_plan: str) -> bool:
    """Return True if user_plan meets or exceeds required_plan."""
    try:
        return _PLAN_ORDER.index(user_plan.lower()) >= _PLAN_ORDER.index(required_plan.lower())
    except ValueError:
        return False


# ---------------------------------------------------------------------------
# Signal dataclass
# ---------------------------------------------------------------------------


@dataclass
class Signal:
    """Trading signal produced by a strategy."""

    symbol: str
    action: str  # "buy" | "sell" | "close"
    strength: float  # 0.0–1.0
    strategy: str
    entry_price: float
    stop_loss: float
    take_profit: float
    timeframe: str
    timestamp: float = field(default_factory=lambda: datetime.now(UTC).timestamp())
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "symbol": self.symbol,
            "action": self.action,
            "strength": self.strength,
            "strategy": self.strategy,
            "entry_price": self.entry_price,
            "stop_loss": self.stop_loss,
            "take_profit": self.take_profit,
            "timeframe": self.timeframe,
            "timestamp": self.timestamp,
            "metadata": self.metadata,
        }


# ---------------------------------------------------------------------------
# Base strategy
# ---------------------------------------------------------------------------


class BaseStrategy(abc.ABC):
    """
    Abstract base for all strategies registered with StrategyManager.

    Subclasses must implement generate_signals().
    performance_metrics is updated by update_performance() after each trade.
    """

    def __init__(self, name: str, config: dict[str, Any] | None = None) -> None:
        self.name = name
        self.config: dict[str, Any] = config or {}
        self.enabled: bool = True
        self.status: StrategyStatus = StrategyStatus.IDLE
        self.performance_metrics: dict[str, Any] = {
            "signals_generated": 0,
            "trades_taken": 0,
            "winning_trades": 0,
            "losing_trades": 0,
            "total_pnl": 0.0,
            "win_rate": 0.0,
            "profit_factor": 0.0,
            "sharpe_ratio": 0.0,
            "max_drawdown": 0.0,
            "last_signal_at": None,
        }
        self._pnl_history: list[float] = []

    @abc.abstractmethod
    async def generate_signals(
        self,
        symbol: str,
        price_data: Any,
        market_regime: str,
    ) -> list[Signal]:
        """Generate trading signals for *symbol* given current price data and regime."""

    def update_performance(self, trade_result: dict[str, Any]) -> None:
        """
        Update performance metrics after a trade closes.

        trade_result must contain:
          pnl (float)   — net P&L of the trade
          won (bool)    — True if trade was profitable
        """
        pnl: float = float(trade_result.get("pnl", 0.0))
        won: bool = bool(trade_result.get("won", pnl > 0))

        m = self.performance_metrics
        m["trades_taken"] += 1
        m["total_pnl"] = round(m["total_pnl"] + pnl, 6)
        self._pnl_history.append(pnl)

        if won:
            m["winning_trades"] += 1
        else:
            m["losing_trades"] += 1

        total = m["trades_taken"]
        m["win_rate"] = round(m["winning_trades"] / total, 4) if total else 0.0

        # Profit factor = gross profit / gross loss
        gross_profit = sum(p for p in self._pnl_history if p > 0)
        gross_loss = abs(sum(p for p in self._pnl_history if p < 0))
        m["profit_factor"] = round(gross_profit / gross_loss, 4) if gross_loss else float("inf")

        # Sharpe ratio (annualised, assuming hourly bars)
        if len(self._pnl_history) >= 2:
            arr = np.array(self._pnl_history)
            mean_r = float(np.mean(arr))
            std_r = float(np.std(arr, ddof=1))
            m["sharpe_ratio"] = round(mean_r / std_r * math.sqrt(8760), 4) if std_r > 0 else 0.0

        # Max drawdown
        equity = np.cumsum(np.array(self._pnl_history))
        peak = np.maximum.accumulate(equity)
        drawdown = (peak - equity) / (peak + 1e-9)
        m["max_drawdown"] = round(float(np.max(drawdown)), 4) if len(drawdown) else 0.0


# ---------------------------------------------------------------------------
# Built-in strategies
# ---------------------------------------------------------------------------


class TrendFollowingStrategy(BaseStrategy):
    """MA crossover trend-following strategy. Requires Starter plan."""

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        super().__init__("TrendFollowing", config)
        self.fast_period: int = self.config.get("fast_period", 20)
        self.slow_period: int = self.config.get("slow_period", 50)
        self.trend_strength_threshold: float = self.config.get("trend_strength_threshold", 0.3)

    async def generate_signals(
        self,
        symbol: str,
        price_data: Any,
        market_regime: str,
    ) -> list[Signal]:
        if market_regime not in ("trending_up", "trending_down"):
            return []
        try:
            closes = np.array([c.close for c in price_data])
            if len(closes) < self.slow_period:
                return []

            fast_ma = float(np.mean(closes[-self.fast_period :]))
            slow_ma = float(np.mean(closes[-self.slow_period :]))
            hl_range = float(np.mean([c.high - c.low for c in price_data[-14:]]))
            trend_strength = abs(fast_ma - slow_ma) / hl_range if hl_range > 0 else 0.0

            if trend_strength < self.trend_strength_threshold:
                return []

            current = float(closes[-1])
            if fast_ma > slow_ma and market_regime == "trending_up":
                sig = Signal(
                    symbol=symbol,
                    action="buy",
                    strength=min(trend_strength * 2, 1.0),
                    strategy=self.name,
                    entry_price=current,
                    stop_loss=current * 0.98,
                    take_profit=current * 1.06,
                    timeframe="1h",
                    metadata={
                        "fast_ma": fast_ma,
                        "slow_ma": slow_ma,
                        "trend_strength": trend_strength,
                    },
                )
                self.performance_metrics["signals_generated"] += 1
                self.performance_metrics["last_signal_at"] = datetime.now(UTC).isoformat()
                return [sig]
            elif fast_ma < slow_ma and market_regime == "trending_down":
                sig = Signal(
                    symbol=symbol,
                    action="sell",
                    strength=min(trend_strength * 2, 1.0),
                    strategy=self.name,
                    entry_price=current,
                    stop_loss=current * 1.02,
                    take_profit=current * 0.94,
                    timeframe="1h",
                    metadata={
                        "fast_ma": fast_ma,
                        "slow_ma": slow_ma,
                        "trend_strength": trend_strength,
                    },
                )
                self.performance_metrics["signals_generated"] += 1
                self.performance_metrics["last_signal_at"] = datetime.now(UTC).isoformat()
                return [sig]
            return []
        except Exception as exc:
            logger.error("TrendFollowing.generate_signals %s: %s", symbol, exc)
            self.status = StrategyStatus.ERROR
            return []


class MeanReversionStrategy(BaseStrategy):
    """Bollinger Band mean-reversion strategy. Requires Professional plan."""

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        super().__init__("MeanReversion", config)
        self.period: int = self.config.get("period", 20)
        self.std_dev: float = self.config.get("std_dev", 2.0)
        self.oversold_threshold: float = self.config.get("oversold_threshold", -2.0)
        self.overbought_threshold: float = self.config.get("overbought_threshold", 2.0)

    async def generate_signals(
        self,
        symbol: str,
        price_data: Any,
        market_regime: str,
    ) -> list[Signal]:
        if market_regime != "ranging":
            return []
        try:
            closes = np.array([c.close for c in price_data])
            if len(closes) < self.period:
                return []

            sma = float(np.mean(closes[-self.period :]))
            std = float(np.std(closes[-self.period :]))
            upper = sma + std * self.std_dev
            lower = sma - std * self.std_dev
            current = float(closes[-1])
            z_score = (current - sma) / std if std > 0 else 0.0

            signals: list[Signal] = []
            if z_score < self.oversold_threshold and current < lower:
                signals.append(
                    Signal(
                        symbol=symbol,
                        action="buy",
                        strength=min(abs(z_score) / 3, 1.0),
                        strategy=self.name,
                        entry_price=current,
                        stop_loss=lower * 0.99,
                        take_profit=sma,
                        timeframe="1h",
                        metadata={
                            "z_score": z_score,
                            "lower_band": lower,
                            "upper_band": upper,
                            "sma": sma,
                        },
                    )
                )
            elif z_score > self.overbought_threshold and current > upper:
                signals.append(
                    Signal(
                        symbol=symbol,
                        action="sell",
                        strength=min(abs(z_score) / 3, 1.0),
                        strategy=self.name,
                        entry_price=current,
                        stop_loss=upper * 1.01,
                        take_profit=sma,
                        timeframe="1h",
                        metadata={
                            "z_score": z_score,
                            "lower_band": lower,
                            "upper_band": upper,
                            "sma": sma,
                        },
                    )
                )

            if signals:
                self.performance_metrics["signals_generated"] += len(signals)
                self.performance_metrics["last_signal_at"] = datetime.now(UTC).isoformat()
            return signals
        except Exception as exc:
            logger.error("MeanReversion.generate_signals %s: %s", symbol, exc)
            self.status = StrategyStatus.ERROR
            return []


class BreakoutStrategy(BaseStrategy):
    """Support/resistance breakout strategy. Requires Professional plan."""

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        super().__init__("Breakout", config)
        self.lookback_period: int = self.config.get("lookback_period", 20)
        self.breakout_threshold: float = self.config.get("breakout_threshold", 0.001)

    async def generate_signals(
        self,
        symbol: str,
        price_data: Any,
        market_regime: str,
    ) -> list[Signal]:
        if market_regime != "ranging":
            return []
        try:
            recent = price_data[-self.lookback_period :]
            if len(recent) < self.lookback_period:
                return []

            resistance = float(np.max([c.high for c in recent]))
            support = float(np.min([c.low for c in recent]))
            current = float(price_data[-1].close)

            if current > resistance * (1 + self.breakout_threshold):
                sig = Signal(
                    symbol=symbol,
                    action="buy",
                    strength=0.7,
                    strategy=self.name,
                    entry_price=current,
                    stop_loss=support,
                    take_profit=current + (current - support) * 2,
                    timeframe="1h",
                    metadata={
                        "resistance": resistance,
                        "support": support,
                        "breakout_type": "resistance",
                    },
                )
                self.performance_metrics["signals_generated"] += 1
                self.performance_metrics["last_signal_at"] = datetime.now(UTC).isoformat()
                return [sig]
            elif current < support * (1 - self.breakout_threshold):
                sig = Signal(
                    symbol=symbol,
                    action="sell",
                    strength=0.7,
                    strategy=self.name,
                    entry_price=current,
                    stop_loss=resistance,
                    take_profit=current - (resistance - current) * 2,
                    timeframe="1h",
                    metadata={
                        "resistance": resistance,
                        "support": support,
                        "breakout_type": "support",
                    },
                )
                self.performance_metrics["signals_generated"] += 1
                self.performance_metrics["last_signal_at"] = datetime.now(UTC).isoformat()
                return [sig]
            return []
        except Exception as exc:
            logger.error("Breakout.generate_signals %s: %s", symbol, exc)
            self.status = StrategyStatus.ERROR
            return []


# ---------------------------------------------------------------------------
# Strategy Manager
# ---------------------------------------------------------------------------


class StrategyManager:
    """
    Central strategy management system.

    Responsibilities:
      - Register/unregister strategies
      - Start/stop individual strategies or all at once
      - Generate signals from all enabled, running strategies
      - Enforce subscription tier gating per strategy
      - Aggregate and deduplicate signals (strongest wins per symbol+action)
      - Track per-strategy and aggregate performance
    """

    def __init__(self, preload_defaults: bool = False) -> None:
        self.strategies: dict[str, BaseStrategy] = {}
        if preload_defaults:
            self._initialize_default_strategies()

    def _initialize_default_strategies(self) -> None:
        self.register_strategy(TrendFollowingStrategy({"fast_period": 20, "slow_period": 50}))
        self.register_strategy(MeanReversionStrategy({"period": 20, "std_dev": 2.0}))
        self.register_strategy(BreakoutStrategy({"lookback_period": 20}))

    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------

    def register_strategy(self, strategy: BaseStrategy) -> None:
        self.strategies[strategy.name] = strategy
        logger.info("strategy.registered name=%s", strategy.name)

    def unregister_strategy(self, name: str) -> bool:
        if name in self.strategies:
            del self.strategies[name]
            logger.info("strategy.unregistered name=%s", name)
            return True
        return False

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start_strategy(self, name: str) -> bool:
        s = self.strategies.get(name)
        if not s:
            return False
        s.status = StrategyStatus.RUNNING
        logger.info("strategy.started name=%s", name)
        return True

    def stop_strategy(self, name: str) -> bool:
        s = self.strategies.get(name)
        if not s:
            return False
        s.status = StrategyStatus.STOPPED
        logger.info("strategy.stopped name=%s", name)
        return True

    def pause_strategy(self, name: str) -> bool:
        s = self.strategies.get(name)
        if not s:
            return False
        s.status = StrategyStatus.PAUSED
        logger.info("strategy.paused name=%s", name)
        return True

    def start_all(self) -> None:
        for s in self.strategies.values():
            s.status = StrategyStatus.RUNNING
        logger.info("strategy.all_started count=%d", len(self.strategies))

    def stop_all(self) -> None:
        for s in self.strategies.values():
            s.status = StrategyStatus.STOPPED
        logger.info("strategy.all_stopped count=%d", len(self.strategies))

    def enable_strategy(self, name: str) -> bool:
        s = self.strategies.get(name)
        if not s:
            return False
        s.enabled = True
        logger.info("strategy.enabled name=%s", name)
        return True

    def disable_strategy(self, name: str) -> bool:
        s = self.strategies.get(name)
        if not s:
            return False
        s.enabled = False
        logger.info("strategy.disabled name=%s", name)
        return True

    # ------------------------------------------------------------------
    # Signal generation
    # ------------------------------------------------------------------

    async def generate_signals(
        self,
        market_regimes: dict[str, Any],
        price_engine: Any,
        user_plan: str = "starter",
    ) -> list[dict]:
        """
        Generate signals from all enabled, running strategies.

        Enforces subscription tier gating: strategies above the user's plan
        are skipped and logged. Signals are deduplicated — strongest wins
        per (symbol, action) pair.

        Args:
            market_regimes: {symbol: MarketRegime}
            price_engine:   Object with get_ohlcv(symbol, timeframe, limit) method
            user_plan:      User's subscription tier (trial/starter/professional/enterprise/elite)
        """
        all_signals: list[dict] = []

        for symbol, regime in market_regimes.items():
            regime_value = regime.value if hasattr(regime, "value") else str(regime)

            try:
                ohlcv = price_engine.get_ohlcv(symbol, "1h", limit=100)
                if not ohlcv or len(ohlcv) < 50:
                    logger.debug("strategy.skip_no_data symbol=%s", symbol)
                    continue
            except Exception as exc:
                logger.warning("strategy.price_data_error symbol=%s: %s", symbol, exc)
                continue

            # Guard: verify the last bar has a real price before passing to
            # strategies. A zero or missing close price would produce zero-price
            # signals that reach the execution engine as zero-price orders.
            try:
                last_close = float(getattr(ohlcv[-1], "close", 0) or 0)
            except (TypeError, ValueError, IndexError):
                last_close = 0.0
            if last_close <= 0:
                logger.error(
                    "strategy.skip_zero_price symbol=%s last_close=%.6f — "
                    "price_engine returned bars with no valid close price",
                    symbol,
                    last_close,
                )
                continue

            for strategy in self.strategies.values():
                if not self._strategy_enabled(strategy):
                    continue
                if self._strategy_status(strategy) not in (
                    StrategyStatus.RUNNING,
                    StrategyStatus.IDLE,
                ):
                    continue

                # Subscription tier gate
                required = STRATEGY_PLAN_REQUIREMENTS.get(strategy.name, "starter")
                if not _plan_satisfies(user_plan, required):
                    logger.debug(
                        "strategy.plan_gate name=%s required=%s user=%s",
                        strategy.name,
                        required,
                        user_plan,
                    )
                    continue

                try:
                    signals = await strategy.generate_signals(
                        symbol=symbol,
                        price_data=ohlcv,
                        market_regime=regime_value,
                    )
                    # Filter zero-price signals — a strategy returning
                    # entry_price=0 would produce a zero-price broker order.
                    valid = [s for s in signals if s.entry_price > 0]
                    if len(valid) < len(signals):
                        logger.error(
                            "strategy.zero_price_signal name=%s symbol=%s count=%d — discarded",
                            strategy.name,
                            symbol,
                            len(signals) - len(valid),
                        )
                    all_signals.extend(s.to_dict() for s in valid)
                except Exception as exc:
                    logger.error(
                        "strategy.error name=%s symbol=%s: %s",
                        strategy.name,
                        symbol,
                        exc,
                    )
                    strategy.status = StrategyStatus.ERROR

        return self._deduplicate_signals(all_signals)

    def _deduplicate_signals(self, signals: list[dict]) -> list[dict]:
        """Keep the strongest signal per (symbol, action) pair."""
        seen: dict[tuple, dict] = {}
        for sig in signals:
            key = (sig["symbol"], sig["action"])
            if key not in seen or sig["strength"] > seen[key]["strength"]:
                seen[key] = sig
        result = list(seen.values())
        result.sort(key=lambda x: x["strength"], reverse=True)
        return result

    # ------------------------------------------------------------------
    # Performance
    # ------------------------------------------------------------------

    def get_strategy_performance(self, name: str | None = None) -> dict:
        if name:
            s = self.strategies.get(name)
            return s.performance_metrics if s else {}
        return {n: s.performance_metrics for n, s in self.strategies.items()}

    def update_strategy_performance(self, strategy_name: str, trade_result: dict) -> None:
        s = self.strategies.get(strategy_name)
        if s:
            s.update_performance(trade_result)

    @staticmethod
    def _strategy_enabled(s: Any) -> bool:
        """Return the enabled flag for a strategy, defaulting to True if absent."""
        return bool(getattr(s, "enabled", True))

    @staticmethod
    def _strategy_status(s: Any) -> StrategyStatus:
        """Return the StrategyStatus for a strategy, defaulting to IDLE if absent."""
        status = getattr(s, "status", StrategyStatus.IDLE)
        if not isinstance(status, StrategyStatus):
            # Handle raw string values stored by legacy code
            try:
                return StrategyStatus(str(status))
            except ValueError:
                return StrategyStatus.IDLE
        return status

    @staticmethod
    def _strategy_metrics(s: Any) -> dict:
        """Return performance_metrics dict, defaulting to empty dict if absent."""
        metrics = getattr(s, "performance_metrics", None)
        return metrics if isinstance(metrics, dict) else {}

    @property
    def performance_summary(self) -> dict:
        """Aggregate performance across all registered strategies."""
        total = len(self.strategies)
        active = sum(1 for s in self.strategies.values() if self._strategy_status(s) == StrategyStatus.RUNNING)
        total_pnl = sum(self._strategy_metrics(s).get("total_pnl", 0.0) for s in self.strategies.values())
        total_signals = sum(self._strategy_metrics(s).get("signals_generated", 0) for s in self.strategies.values())
        return {
            "total_strategies": total,
            "active_strategies": active,
            "total_pnl": round(total_pnl, 4),
            "total_signals": total_signals,
            "strategies": {
                n: {
                    "status": self._strategy_status(s).value,
                    "enabled": self._strategy_enabled(s),
                    "signals_generated": self._strategy_metrics(s).get("signals_generated", 0),
                    "win_rate": self._strategy_metrics(s).get("win_rate", 0.0),
                    "total_pnl": self._strategy_metrics(s).get("total_pnl", 0.0),
                }
                for n, s in self.strategies.items()
            },
        }

    def list_strategies(self, user_plan: str = "starter") -> list[dict]:
        """
        List all registered strategies with their plan requirement and availability.

        Returns only strategies accessible on user_plan.
        """
        result = []
        for name, s in self.strategies.items():
            required = STRATEGY_PLAN_REQUIREMENTS.get(name, "starter")
            accessible = _plan_satisfies(user_plan, required)
            result.append(
                {
                    "name": name,
                    "status": self._strategy_status(s).value,
                    "enabled": self._strategy_enabled(s),
                    "required_plan": required,
                    "accessible": accessible,
                    "performance": self._strategy_metrics(s),
                }
            )
        return result
