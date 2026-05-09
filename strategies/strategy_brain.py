# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
Strategy Brain - Multi-Strategy Joint Analysis Core

This module provides the central intelligence for combining signals from
multiple strategies into unified, high-confidence trading decisions.

Features:
- Multi-strategy signal aggregation
- Confidence weighting system
- Consensus-based decision making
- Signal correlation analysis
- Risk-adjusted signal combining
- Real-time strategy coordination
- Performance-weighted voting
"""

import logging
from collections import deque
from datetime import datetime, timezone

UTC = timezone.utc
from typing import Any

import numpy as np

from .base import BaseStrategy, Signal, SignalType, StrategyStatus

logger = logging.getLogger(__name__)


class StrategyBrain:
    """
    Central intelligence for multi-strategy coordination and joint analysis.

    Combines signals from multiple strategies using:
    - Weighted voting based on historical performance
    - Confidence score aggregation
    - Correlation analysis between strategies
    - Risk-adjusted position sizing recommendations
    """

    def __init__(self, config: dict[str, Any] | None = None):
        """
        Initialize Strategy Brain.

        Args:
            config: Brain configuration
        """
        self.config = config or {}

        # Brain parameters
        self.min_strategies_required = self.config.get("min_strategies_required", 2)
        self.consensus_threshold = self.config.get("consensus_threshold", 0.6)  # 60%
        self.performance_weight = self.config.get(
            "performance_weight",
            0.4,
        )  # 40% weight to performance
        self.confidence_weight = self.config.get(
            "confidence_weight",
            0.6,
        )  # 60% weight to signal confidence

        # Strategy tracking
        self.strategies: dict[str, BaseStrategy] = {}
        self.strategy_performance: dict[str, dict[str, float]] = {}
        self.strategy_weights: dict[str, float] = {}

        # Signal history — bounded deques prevent unbounded memory growth.
        # Defaults: 1000 signal entries and 500 consensus signals.
        # Override via config keys "max_signal_history" / "max_consensus_signals".
        _max_sig = int(self.config.get("max_signal_history", 1000))
        _max_con = int(self.config.get("max_consensus_signals", 500))
        self.signal_history: deque[dict[str, Any]] = deque(maxlen=_max_sig)
        self.consensus_signals: deque[Signal] = deque(maxlen=_max_con)

        # Statistics
        self.stats = {
            "total_analyses": 0,
            "consensus_reached": 0,
            "bullish_consensus": 0,
            "bearish_consensus": 0,
            "neutral_count": 0,
            "average_confidence": 0.0,
        }

        logger.info("Strategy Brain initialized")

    def register_strategy(self, strategy: BaseStrategy):
        """
        Register a strategy with the brain.

        Args:
            strategy: Strategy instance to register
        """
        strategy_name = strategy.config.name
        self.strategies[strategy_name] = strategy

        # Initialize performance tracking
        if strategy_name not in self.strategy_performance:
            self.strategy_performance[strategy_name] = {
                "total_signals": 0,
                "correct_signals": 0,
                "win_rate": 0.5,  # Start at 50%
                "average_confidence": 0.5,
                "total_pnl": 0.0,
            }

        # Calculate initial weight (equal weight, updated by performance)
        self._recalculate_weights()

        logger.info("Strategy Brain: Registered %s", strategy_name)

    def unregister_strategy(self, strategy_name: str):
        """
        Unregister a strategy from the brain.

        Args:
            strategy_name: Name of strategy to remove
        """
        if strategy_name in self.strategies:
            del self.strategies[strategy_name]
            self._recalculate_weights()
            logger.info("Strategy Brain: Unregistered %s", strategy_name)

    def analyze_joint(self, data: dict[str, Any]) -> dict[str, Any]:
        """
        Perform joint analysis using all registered strategies.

        Args:
            data: Market data to analyze

        Returns:
            Joint analysis results with consensus signal
        """
        self.stats["total_analyses"] += 1

        try:
            # Collect signals from all active strategies
            strategy_signals = {}

            for name, strategy in self.strategies.items():
                if strategy.status != StrategyStatus.RUNNING:
                    continue

                try:
                    # Get signal from strategy
                    signal = strategy.on_bar(data)
                    if signal:
                        strategy_signals[name] = signal
                except Exception as e:
                    logger.error("Error getting signal from %s: %s", name, e)

            # If not enough strategies provided signals, return neutral
            if len(strategy_signals) < self.min_strategies_required:
                self.stats["neutral_count"] += 1
                return {
                    "consensus_reached": False,
                    "reason": f"Insufficient strategies ({len(strategy_signals)} < {self.min_strategies_required})",
                    "signal": None,
                }

            # Analyze signals for consensus
            consensus_result = self._calculate_consensus(strategy_signals, data)

            if consensus_result["consensus_reached"]:
                self.stats["consensus_reached"] += 1
                if consensus_result["consensus_signal"].signal_type == SignalType.BUY:
                    self.stats["bullish_consensus"] += 1
                elif consensus_result["consensus_signal"].signal_type == SignalType.SELL:
                    self.stats["bearish_consensus"] += 1

                # Update average confidence
                self.stats["average_confidence"] = (
                    self.stats["average_confidence"] * (self.stats["total_analyses"] - 1)
                    + consensus_result["consensus_signal"].confidence
                ) / self.stats["total_analyses"]

                # Record consensus signal
                self.consensus_signals.append(consensus_result["consensus_signal"])
            else:
                self.stats["neutral_count"] += 1

            # Record in history
            self.signal_history.append(
                {
                    "timestamp": datetime.now(UTC),
                    "strategy_signals": strategy_signals,
                    "consensus": consensus_result,
                    "data_snapshot": data.get("prices", [])[-1] if data.get("prices") else {},
                },
            )

            return consensus_result

        except Exception as e:
            logger.error("Error in joint analysis: %s", e)

            return {
                "consensus_reached": False,
                "reason": "Analysis error",
                "signal": None,
            }

    def _calculate_consensus(
        self,
        strategy_signals: dict[str, Signal],
        data: dict[str, Any],
    ) -> dict[str, Any]:
        """
        Calculate consensus from multiple strategy signals.

        Args:
            strategy_signals: Signals from different strategies
            data: Market data context

        Returns:
            Consensus analysis result
        """
        try:
            # Categorize signals by type
            buy_signals = []
            sell_signals = []

            for strategy_name, signal in strategy_signals.items():
                weight = self.strategy_weights.get(
                    strategy_name,
                    1.0 / len(self.strategies),
                )

                # Weight the signal by strategy performance and confidence
                weighted_confidence = (
                    signal.confidence * self.confidence_weight
                    + self.strategy_performance[strategy_name]["win_rate"] * self.performance_weight
                ) * weight

                if signal.signal_type == SignalType.BUY:
                    buy_signals.append(
                        {
                            "strategy": strategy_name,
                            "signal": signal,
                            "weight": weight,
                            "weighted_confidence": weighted_confidence,
                        },
                    )
                elif signal.signal_type == SignalType.SELL:
                    sell_signals.append(
                        {
                            "strategy": strategy_name,
                            "signal": signal,
                            "weight": weight,
                            "weighted_confidence": weighted_confidence,
                        },
                    )

            # Calculate total weighted confidence for each direction
            total_buy_confidence = sum(s["weighted_confidence"] for s in buy_signals)
            total_sell_confidence = sum(s["weighted_confidence"] for s in sell_signals)

            # Calculate consensus
            total_confidence = total_buy_confidence + total_sell_confidence

            if total_confidence == 0:
                return {
                    "consensus_reached": False,
                    "reason": "No directional signals",
                    "signal": None,
                }

            # Determine if consensus is reached
            buy_ratio = total_buy_confidence / total_confidence
            sell_ratio = total_sell_confidence / total_confidence

            consensus_signal = None
            consensus_reached = False
            reason = ""

            # BULLISH CONSENSUS
            if buy_ratio >= self.consensus_threshold:
                consensus_reached = True

                # Create consensus signal
                avg_price = np.mean([s["signal"].price for s in buy_signals])
                consensus_confidence = total_buy_confidence / len(buy_signals) if buy_signals else 0

                consensus_signal = Signal(
                    signal_type=SignalType.BUY,
                    symbol=next(iter(strategy_signals.values())).symbol,
                    price=avg_price,
                    timestamp=datetime.now(UTC),
                    confidence=min(consensus_confidence, 1.0),
                    metadata={
                        "type": "consensus",
                        "agreeing_strategies": [s["strategy"] for s in buy_signals],
                        "total_strategies": len(strategy_signals),
                        "buy_ratio": buy_ratio,
                        "weighted_confidence": total_buy_confidence,
                        "strategy_details": {
                            s["strategy"]: {
                                "confidence": s["signal"].confidence,
                                "weight": s["weight"],
                                "metadata": s["signal"].metadata,
                            }
                            for s in buy_signals
                        },
                    },
                )
                reason = f"Bullish consensus: {len(buy_signals)}/{len(strategy_signals)} strategies agree"

            # BEARISH CONSENSUS
            elif sell_ratio >= self.consensus_threshold:
                consensus_reached = True

                # Create consensus signal
                avg_price = np.mean([s["signal"].price for s in sell_signals])
                consensus_confidence = total_sell_confidence / len(sell_signals) if sell_signals else 0

                consensus_signal = Signal(
                    signal_type=SignalType.SELL,
                    symbol=next(iter(strategy_signals.values())).symbol,
                    price=avg_price,
                    timestamp=datetime.now(UTC),
                    confidence=min(consensus_confidence, 1.0),
                    metadata={
                        "type": "consensus",
                        "agreeing_strategies": [s["strategy"] for s in sell_signals],
                        "total_strategies": len(strategy_signals),
                        "sell_ratio": sell_ratio,
                        "weighted_confidence": total_sell_confidence,
                        "strategy_details": {
                            s["strategy"]: {
                                "confidence": s["signal"].confidence,
                                "weight": s["weight"],
                                "metadata": s["signal"].metadata,
                            }
                            for s in sell_signals
                        },
                    },
                )
                reason = f"Bearish consensus: {len(sell_signals)}/{len(strategy_signals)} strategies agree"

            else:
                reason = f"No consensus: Buy {buy_ratio:.1%}, Sell {sell_ratio:.1%}"

            return {
                "consensus_reached": consensus_reached,
                "consensus_signal": consensus_signal,
                "buy_signals": len(buy_signals),
                "sell_signals": len(sell_signals),
                "total_signals": len(strategy_signals),
                "buy_ratio": buy_ratio,
                "sell_ratio": sell_ratio,
                "reason": reason,
                "analysis_details": {
                    "buy_confidence": total_buy_confidence,
                    "sell_confidence": total_sell_confidence,
                    "buy_strategies": [s["strategy"] for s in buy_signals],
                    "sell_strategies": [s["strategy"] for s in sell_signals],
                },
            }

        except Exception as e:
            logger.error("Error calculating consensus: %s", e)

            return {
                "consensus_reached": False,
                "reason": "Consensus calculation error",
                "signal": None,
            }

    def update_strategy_performance(
        self,
        strategy_name: str,
        signal_correct: bool,
        pnl: float,
    ):
        """
        Update performance metrics for a strategy.

        Args:
            strategy_name: Name of strategy
            signal_correct: Whether signal was correct
            pnl: Profit/loss from signal
        """
        if strategy_name not in self.strategy_performance:
            return

        perf = self.strategy_performance[strategy_name]

        # Update metrics
        perf["total_signals"] += 1
        if signal_correct:
            perf["correct_signals"] += 1
        perf["total_pnl"] += pnl

        # Recalculate win rate
        perf["win_rate"] = perf["correct_signals"] / perf["total_signals"]

        # Recalculate strategy weights
        self._recalculate_weights()

        logger.info(
            "Updated performance for %s: Win rate: %s, PnL: $%s", strategy_name, perf["win_rate"], perf["total_pnl"]
        )

    def _recalculate_weights(self):
        """Recalculate strategy weights based on performance"""
        if not self.strategies:
            return

        # Calculate weights based on win rate and PnL
        total_performance = 0.0
        strategy_scores = {}

        for name in self.strategies:
            if name in self.strategy_performance:
                perf = self.strategy_performance[name]
                # Combine win rate and normalized PnL for score
                score = perf["win_rate"] * 0.7 + min(perf["total_pnl"] / 1000, 1.0) * 0.3
            else:
                score = 0.5  # Default score for new strategies

            strategy_scores[name] = max(score, 0.1)  # Minimum weight of 0.1
            total_performance += strategy_scores[name]

        # Normalize weights
        if total_performance > 0:
            self.strategy_weights = {name: score / total_performance for name, score in strategy_scores.items()}
        else:
            # Equal weights if no performance data
            equal_weight = 1.0 / len(self.strategies)
            self.strategy_weights = dict.fromkeys(self.strategies.keys(), equal_weight)

    def get_statistics(self) -> dict[str, Any]:
        """
        Get brain statistics.

        Returns:
            Statistics dictionary
        """
        consensus_rate = (
            self.stats["consensus_reached"] / self.stats["total_analyses"] if self.stats["total_analyses"] > 0 else 0
        )

        return {
            "total_analyses": self.stats["total_analyses"],
            "consensus_reached": self.stats["consensus_reached"],
            "consensus_rate": consensus_rate,
            "bullish_consensus": self.stats["bullish_consensus"],
            "bearish_consensus": self.stats["bearish_consensus"],
            "neutral_count": self.stats["neutral_count"],
            "average_confidence": self.stats["average_confidence"],
            "registered_strategies": len(self.strategies),
            "strategy_weights": self.strategy_weights.copy(),
            "strategy_performance": self.strategy_performance.copy(),
        }

    def get_strategy_correlations(self) -> dict[str, dict[str, float]]:
        """
        Calculate correlation between strategies based on signal history.

        Returns:
            Correlation matrix
        """
        correlations = {}
        strategy_names = list(self.strategies.keys())

        # Build signal agreement matrix
        for strategy1 in strategy_names:
            correlations[strategy1] = {}
            for strategy2 in strategy_names:
                if strategy1 == strategy2:
                    correlations[strategy1][strategy2] = 1.0
                else:
                    # Calculate how often they agree
                    agreements = 0
                    total_comparisons = 0

                    for history_entry in self.signal_history:
                        signals = history_entry["strategy_signals"]
                        if strategy1 in signals and strategy2 in signals:
                            total_comparisons += 1
                            if signals[strategy1].signal_type == signals[strategy2].signal_type:
                                agreements += 1

                    correlation = agreements / total_comparisons if total_comparisons > 0 else 0.5
                    correlations[strategy1][strategy2] = correlation

        return correlations

    async def generate_signals(self, market_regime: dict, price_engine=None) -> list[dict]:
        """
        Bridge method called each HOPEFXBrain cycle.

        Iterates over symbols in *market_regime*, runs analyze_joint for each,
        and converts consensus Signal objects into the action-dict format that
        _execute_signal expects (keys: action, symbol, size, confidence, …).
        """
        import asyncio
        import inspect

        if not self.strategies:
            return []

        result_signals: list[dict] = []

        for symbol, regime in (market_regime or {}).items():
            try:
                current_price = 0.0
                ohlcv: list = []

                if price_engine is not None:
                    try:
                        raw = price_engine.get_ohlcv(symbol, "1h", limit=50)
                        if inspect.iscoroutine(raw):
                            raw = await raw
                        ohlcv = raw or []
                        if ohlcv:
                            current_price = float(ohlcv[-1].close)
                    except Exception:  # noqa: BLE001 — OHLCV fetch is best-effort
                        pass

                    if current_price == 0.0:
                        try:
                            tick = price_engine.get_last_price(symbol)
                            if tick is not None:
                                current_price = (tick.bid + tick.ask) / 2.0
                        except Exception:  # noqa: BLE001 — tick fetch is best-effort
                            pass

                if current_price == 0.0:
                    continue

                regime_str = regime.value if hasattr(regime, "value") else str(regime)
                data = {
                    "symbol": symbol,
                    "price": current_price,
                    "prices": ohlcv,
                    "regime": regime_str,
                    "timestamp": __import__("time").time(),
                }

                consensus = self.analyze_joint(data)

                if consensus.get("consensus_reached") and consensus.get("consensus_signal"):
                    sig = consensus["consensus_signal"]
                    action = "buy" if sig.signal_type == __import__("strategies.base", fromlist=["SignalType"]).SignalType.BUY else "sell"
                    meta = sig.metadata or {}
                    agreeing = meta.get("agreeing_strategies") or ["strategy_brain"]
                    result_signals.append({
                        "action": action,
                        "symbol": symbol,
                        "size": float(meta.get("size", 0.01)),
                        "confidence": float(sig.confidence),
                        "price": float(sig.price),
                        "entry_price": float(sig.price),
                        "strategy": agreeing[0] if agreeing else "strategy_brain",
                        "regime": regime_str,
                    })

            except Exception as e:
                logger.error("generate_signals error for %s: %s", symbol, e)

        return result_signals

    def __repr__(self) -> str:
        return (
            f"StrategyBrain("
            f"strategies={len(self.strategies)}, "
            f"consensus_rate={self.stats['consensus_reached']}/{self.stats['total_analyses']})"
        )
