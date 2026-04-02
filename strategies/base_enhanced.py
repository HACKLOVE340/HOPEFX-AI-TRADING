# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
# strategies/base_enhanced.py
"""
Enhanced strategy base that works with your existing strategies
and adds MCC integration.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime, timezone

UTC = timezone.utc
from decimal import Decimal
from typing import Any


@dataclass
class StrategyConfig:
    """Enhanced config - backwards compatible with your existing"""

    name: str
    symbol: str  # "XAUUSD" format
    timeframe: str = "5m"
    risk_per_trade: Decimal = Decimal("0.01")  # 1%
    max_position: Decimal = Decimal("10")
    enabled: bool = True

    # New fields (optional for existing strategies)
    regime_preference: list[str] = None  # ["trending", "ranging"]
    correlation_group: str = "default"  # For diversification

    def __post_init__(self):
        if self.regime_preference is None:
            self.regime_preference = ["any"]


class StrategySignal:
    """Standardized signal format"""

    def __init__(
        self,
        action: str,  # "BUY", "SELL", "HOLD"
        strength: float = 0.5,  # 0.0 to 1.0
        confidence: float = 0.7,
        target_price: Decimal | None = None,
        stop_loss: Decimal | None = None,
        take_profit: Decimal | None = None,
        metadata: dict | None = None,
    ):
        self.action = action
        self.strength = max(0.0, min(1.0, strength))
        self.confidence = max(0.0, min(1.0, confidence))
        self.target_price = target_price
        self.stop_loss = stop_loss
        self.take_profit = take_profit
        self.metadata = metadata or {}
        self.timestamp = datetime.now(UTC)

    def is_valid(self) -> bool:
        return self.action in ["BUY", "SELL", "HOLD"] and self.confidence > 0.5  # noqa: PLR2004


class EnhancedStrategy(ABC):
    """
    Enhanced base class - your existing strategies can inherit this
    or keep using old base with wrapper.
    """

    def __init__(self, config: StrategyConfig):
        self.config = config
        self.is_active = False
        self.performance = {
            "trades": 0,
            "wins": 0,
            "losses": 0,
            "total_pnl": Decimal("0"),
            "current_drawdown": Decimal("0"),
        }
        self.price_history: list[tuple] = []  # (timestamp, price)
        self.max_history = 1000

        # MCC integration hooks
        self.mcc_callback: Any | None = None

    def activate(self):
        self.is_active = True

    def deactivate(self):
        self.is_active = False

    def on_price(
        self,
        timestamp: datetime,
        price: Decimal,
        bid: Decimal | None = None,
        ask: Decimal | None = None,
    ):
        """
        Called by MCC on every price update.
        Your existing on_tick() can call this.
        """
        if not self.is_active:
            return None

        self.price_history.append((timestamp, price))
        if len(self.price_history) > self.max_history:
            self.price_history.pop(0)

        # Generate signal
        signal = self.generate_signal(timestamp, price, bid, ask)

        # Report to MCC if connected
        if signal and signal.is_valid() and self.mcc_callback:
            self.mcc_callback(self.config.name, signal)  # pylint: disable=not-callable

        return signal

    @abstractmethod
    def generate_signal(
        self,
        timestamp: datetime,
        price: Decimal,
        bid: Decimal | None = None,
        ask: Decimal | None = None,
    ) -> StrategySignal | None:
        """
        Your existing generate_signal() goes here.
        Return StrategySignal instead of raw dict.
        """

    def on_trade_completed(self, pnl: Decimal):
        """Called by MCC when trade closes"""
        self.performance["trades"] += 1
        self.performance["total_pnl"] += pnl

        if pnl > 0:
            self.performance["wins"] += 1
        else:
            self.performance["losses"] += 1

    def get_metrics(self) -> dict:
        """Performance metrics for MCC"""
        trades = self.performance["trades"]
        return {
            "name": self.config.name,
            "win_rate": self.performance["wins"] / trades if trades > 0 else 0,
            "total_pnl": float(self.performance["total_pnl"]),
            "current_drawdown": float(self.performance["current_drawdown"]),
            "is_active": self.is_active,
        }


# Wrapper for your existing strategies
class StrategyAdapter:
    """
    Wraps your existing strategies to work with MCC.
    No need to rewrite your strategies!
    """

    def __init__(self, legacy_strategy):
        self.legacy = legacy_strategy
        self.config = StrategyConfig(
            name=getattr(legacy_strategy, "name", "unknown"),
            symbol=getattr(legacy_strategy, "symbol", "XAUUSD"),
            timeframe=getattr(legacy_strategy, "timeframe", "5m"),
        )

    def on_price(self, timestamp, price, bid=None, ask=None):
        # Call your existing method
        if hasattr(self.legacy, "on_tick"):
            result = self.legacy.on_tick(price)
            if result:
                return StrategySignal(
                    action=result.get("signal", "HOLD"),
                    strength=result.get("strength", 0.5),
                )
        return None
