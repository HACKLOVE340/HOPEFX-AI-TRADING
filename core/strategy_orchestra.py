# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
HOPEFX Strategy Orchestra
Coordinates multiple strategies to prevent conflicts and maximize returns
"""

import logging
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone

UTC = timezone.utc
from typing import Any

from core.event_bus import DomainEvent, EventBus
from strategies.base import BaseStrategy, Signal

logger = logging.getLogger(__name__)


@dataclass
class StrategyPerformance:
    strategy_id: str
    total_signals: int = 0
    win_rate: float = 0.0
    profit_factor: float = 0.0
    sharpe_ratio: float = 0.0
    current_drawdown: float = 0.0
    correlation_to_portfolio: float = 0.0
    regime_suitability: dict[str, float] = field(default_factory=dict)


class StrategyOrchestra:
    """Conducts multiple strategies like an orchestra"""

    def __init__(self, event_bus: EventBus):
        self.event_bus = event_bus
        self.strategies: dict[str, BaseStrategy] = {}
        self.performance: dict[str, StrategyPerformance] = {}
        self.allocations: dict[str, float] = {}
        self.active_strategies: list[str] = []
        self.current_regime: str = "unknown"
        self.signal_buffer: dict[str, list[Signal]] = defaultdict(list)
        self._rebalancer: Any | None = None
        self._returns_buffer: dict[str, list[float]] = defaultdict(list)

        self.event_bus.subscribe("POSITION_CLOSED", self._on_position_closed)
        self.event_bus.subscribe("REGIME_CHANGE", self._on_regime_change)

    def attach_rebalancer(
        self,
        method: str = "risk_parity",
        max_weight: float = 0.40,
        dd_limit: float = 0.15,
        interval_hours: float = 4.0,
    ) -> Any:
        """
        Attach a DynamicRebalancer to the orchestra.

        Once attached, the orchestra feeds each strategy's return stream into
        the rebalancer on every POSITION_CLOSED event and uses the rebalancer's
        target weights to update ``self.allocations``.

        Returns the rebalancer so callers can inspect or force a rebalance.
        """
        try:
            from portfolio.rebalancer import DynamicRebalancer

            self._rebalancer = DynamicRebalancer(
                method=method,
                max_weight=max_weight,
                dd_limit=dd_limit,
                interval_hours=interval_hours,
            )
            # Seed current weights
            for sid, alloc in self.allocations.items():
                self._rebalancer.update_current_weight(sid, alloc)
            logger.info("DynamicRebalancer attached: method=%s", method)
            return self._rebalancer
        except Exception as exc:
            logger.warning("DynamicRebalancer attach failed: %s", exc)
            return None

    def run_rebalance(self, force: bool = False) -> dict | None:
        """
        Trigger a rebalance check and apply resulting weights to allocations.

        Returns the RebalanceResult dict, or None if no rebalance was triggered.
        """
        if self._rebalancer is None:
            return None

        # Feed current drawdowns
        for sid, perf in self.performance.items():
            self._rebalancer.update_drawdown(sid, perf.current_drawdown)

        result = self._rebalancer.rebalance(force=force)
        if result is None:
            return None

        # Apply new weights to allocations
        for sid, weight in result.weights.items():
            if sid in self.allocations:
                self.allocations[sid] = weight

        self.event_bus.publish(
            DomainEvent.create(
                "REBALANCE_COMPLETE",
                "orchestra",
                {
                    "method": result.method,
                    "weights": result.weights,
                    "sharpe": result.expected_sharpe,
                },
            )
        )
        logger.info("Rebalanced: method=%s sharpe=%.2f strategies=%s", result.method, result.expected_sharpe, list(result.weights.keys()))
        return result.to_dict()

    def get_rebalancer_status(self) -> dict:
        """Return rebalancer status dict."""
        if self._rebalancer is None:
            return {"attached": False}
        return {"attached": True, **self._rebalancer.status()}

    def register_strategy(self, strategy: BaseStrategy, max_allocation: float = 0.20):
        sid = strategy.config.name
        self.strategies[sid] = strategy
        self.allocations[sid] = max_allocation
        self.performance[sid] = StrategyPerformance(
            strategy_id=sid,
            regime_suitability=self._detect_regime_suitability(strategy),
        )
        logger.info("Strategy registered: %s (max alloc: %.0f%%)", sid, max_allocation * 100)

    def _detect_regime_suitability(self, strategy: BaseStrategy) -> dict[str, float]:
        name = strategy.config.name.lower()
        if "trend" in name or "momentum" in name:
            return {
                "trending_up": 0.9,
                "trending_down": 0.8,
                "ranging": 0.3,
                "volatile": 0.5,
            }
        if "mean" in name or "reversion" in name:
            return {
                "trending_up": 0.3,
                "trending_down": 0.3,
                "ranging": 0.9,
                "volatile": 0.4,
            }
        if "breakout" in name or "volatility" in name:
            return {
                "trending_up": 0.5,
                "trending_down": 0.5,
                "ranging": 0.4,
                "volatile": 0.9,
            }
        return {
            "trending_up": 0.5,
            "trending_down": 0.5,
            "ranging": 0.5,
            "volatile": 0.5,
        }

    def activate_strategy(self, strategy_id: str):
        if strategy_id in self.strategies:
            self.strategies[strategy_id].start()
            if strategy_id not in self.active_strategies:
                self.active_strategies.append(strategy_id)
            logger.info("Strategy activated: %s", strategy_id)

    def deactivate_strategy(self, strategy_id: str, reason: str = ""):
        if strategy_id in self.strategies:
            self.strategies[strategy_id].stop()
            if strategy_id in self.active_strategies:
                self.active_strategies.remove(strategy_id)
            logger.info("Strategy deactivated: %s %s", strategy_id, f"({reason})" if reason else "")

    def distribute_price(self, price: float):
        """Distribute price to all active strategies"""
        for sid in self.active_strategies:
            try:
                bar = {"close": price, "timestamp": datetime.now(UTC)}
                signal = self.strategies[sid].on_bar(bar)
                if signal:
                    self.signal_buffer[sid].append(signal)
                    if len(self.signal_buffer[sid]) > 100:
                        self.signal_buffer[sid].pop(0)
                    self.event_bus.publish(
                        DomainEvent.create(
                            "SIGNAL_GENERATED",
                            sid,
                            {
                                "signal_type": signal.signal_type.value,
                                "confidence": signal.confidence,
                            },
                        ),
                    )
            except Exception as e:
                logger.warning("Strategy error in %s: %s", sid, e)

        # Calculate and emit composite signal
        composite = self._calculate_composite_signal()
        if composite:
            self.event_bus.publish(
                DomainEvent.create(
                    "COMPOSITE_SIGNAL",
                    "orchestra",
                    {
                        "action": composite.signal_type.value,
                        "strength": composite.confidence,
                    },
                    priority=2,
                ),
            )

    def _calculate_composite_signal(self) -> Signal | None:
        if not self.active_strategies:
            return None

        votes = defaultdict(float)
        total_weight = 0

        for sid in self.active_strategies:
            perf = self.performance[sid]
            weight = perf.sharpe_ratio * self.allocations[sid]
            if self.current_regime in perf.regime_suitability:
                weight *= perf.regime_suitability[self.current_regime]

            if self.signal_buffer[sid]:
                latest = self.signal_buffer[sid][-1]
                votes[latest.signal_type] += weight * latest.confidence
                total_weight += weight

        if not votes or total_weight == 0:
            return None

        best_signal = max(votes.items(), key=lambda x: x[1])
        if best_signal[1] > 0.3 * total_weight:
            return Signal(
                signal_type=best_signal[0],
                symbol="XAUUSD",
                price=0,
                timestamp=datetime.now(UTC),
                confidence=min(best_signal[1] / total_weight, 1.0),
            )
        return None

    def _on_position_closed(self, event: DomainEvent):
        data = event.decode()
        sid = data.get("strategy_id")
        pnl = float(data.get("pnl", 0))
        entry_price = float(data.get("entry_price", 1.0))
        if sid in self.performance:
            perf = self.performance[sid]
            perf.total_signals += 1
            # Track return for rebalancer
            ret = pnl / entry_price if entry_price > 0 else 0.0
            self._returns_buffer[sid].append(ret)
            # Feed into rebalancer when we have enough history
            if self._rebalancer is not None and len(self._returns_buffer[sid]) >= 5:
                import pandas as pd

                returns_series = pd.Series(self._returns_buffer[sid])
                self._rebalancer.update_strategy_returns(sid, returns_series)
                self._rebalancer.update_drawdown(sid, perf.current_drawdown)

    def _on_regime_change(self, event: DomainEvent):
        data = event.decode()
        new_regime = data.get("regime")
        self.current_regime = new_regime
        logger.info("Regime change → %s", new_regime)

        for sid, perf in self.performance.items():
            suit = perf.regime_suitability.get(new_regime, 0.5)
            if suit > 0.7 and sid not in self.active_strategies:
                self.activate_strategy(sid)
            elif suit < 0.3 and sid in self.active_strategies:
                self.deactivate_strategy(sid, f"unsuitable for {new_regime}")

    def get_heatmap_data(self) -> dict:
        return {
            "strategies": {
                sid: {
                    "allocation": self.allocations.get(sid, 0),
                    "active": sid in self.active_strategies,
                    "win_rate": perf.win_rate,
                    "sharpe": perf.sharpe_ratio,
                    "drawdown": perf.current_drawdown,
                    "regime_fit": perf.regime_suitability.get(self.current_regime, 0),
                }
                for sid, perf in self.performance.items()
            },
            "current_regime": self.current_regime,
            "active_count": len(self.active_strategies),
        }


# =============================================================================
# Shared orchestra singleton — used by regime_router and execution engine
# to publish POSITION_CLOSED and REGIME_CHANGE events to subscribers.
# =============================================================================

_shared_orchestra: "StrategyOrchestra | None" = None


def set_shared_orchestra(orchestra: "StrategyOrchestra") -> None:
    """Register the application-level orchestra instance."""
    global _shared_orchestra
    _shared_orchestra = orchestra


def _get_shared_orchestra() -> "StrategyOrchestra | None":
    """Return the shared orchestra, or None if not yet initialised."""
    if _shared_orchestra is not None:
        return _shared_orchestra
    # Fallback: try to get it from app_state
    try:
        from app import app_state  # type: ignore[import]

        return getattr(app_state, "orchestra", None)
    except Exception as _exc:
        logger.debug("get_shared_orchestra: app_state unavailable: %s", _exc)
        return None
