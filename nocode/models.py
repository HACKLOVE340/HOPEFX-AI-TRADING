# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""nocode/models.py — Data models for the no-code strategy builder."""

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)


class ConditionOperator(Enum):
    """Condition operators"""

    GREATER_THAN = ">"
    LESS_THAN = "<"
    GREATER_EQUAL = ">="
    LESS_EQUAL = "<="
    EQUAL = "=="
    NOT_EQUAL = "!="
    CROSSES_ABOVE = "crosses_above"
    CROSSES_BELOW = "crosses_below"


class LogicOperator(Enum):
    """Logic operators for combining conditions"""

    AND = "AND"
    OR = "OR"


class ActionType(Enum):
    """Trading action types"""

    BUY = "BUY"
    SELL = "SELL"
    CLOSE_LONG = "CLOSE_LONG"
    CLOSE_SHORT = "CLOSE_SHORT"
    CLOSE_ALL = "CLOSE_ALL"


class IndicatorType(Enum):
    """Available indicators"""

    PRICE = "PRICE"
    SMA = "SMA"
    EMA = "EMA"
    RSI = "RSI"
    MACD = "MACD"
    MACD_SIGNAL = "MACD_SIGNAL"
    MACD_HISTOGRAM = "MACD_HISTOGRAM"
    BOLLINGER_UPPER = "BOLLINGER_UPPER"
    BOLLINGER_LOWER = "BOLLINGER_LOWER"
    BOLLINGER_MIDDLE = "BOLLINGER_MIDDLE"
    ATR = "ATR"
    STOCHASTIC_K = "STOCHASTIC_K"
    STOCHASTIC_D = "STOCHASTIC_D"
    ADX = "ADX"
    CCI = "CCI"
    WILLIAMS_R = "WILLIAMS_R"
    VOLUME = "VOLUME"
    CONSTANT = "CONSTANT"


@dataclass
class Indicator:
    """Indicator configuration"""

    indicator_type: IndicatorType
    period: int = 14
    source: str = "close"  # open, high, low, close
    params: dict[str, Any] = field(default_factory=dict)

    def get_id(self) -> str:
        """Get unique identifier for this indicator."""
        return f"{self.indicator_type.value}_{self.period}_{self.source}"


@dataclass
class Condition:
    """Single condition in a strategy rule"""

    condition_id: str
    left_indicator: Indicator
    operator: ConditionOperator
    right_indicator: Indicator | float  # Can be indicator or constant

    def evaluate(self, data: dict[str, float]) -> bool:
        """Evaluate the condition against current data."""
        left_value = self._get_value(self.left_indicator, data)

        if isinstance(self.right_indicator, int | float):
            right_value = self.right_indicator
        else:
            right_value = self._get_value(self.right_indicator, data)

        if left_value is None or right_value is None:
            return False

        operators = {
            ConditionOperator.GREATER_THAN: lambda l, r: l > r,
            ConditionOperator.LESS_THAN: lambda l, r: l < r,
            ConditionOperator.GREATER_EQUAL: lambda l, r: l >= r,
            ConditionOperator.LESS_EQUAL: lambda l, r: l <= r,
            ConditionOperator.EQUAL: lambda l, r: l == r,
            ConditionOperator.NOT_EQUAL: lambda l, r: l != r,
        }

        op_func = operators.get(self.operator)
        if op_func:
            return op_func(left_value, right_value)
        return False

    def _get_value(self, indicator: Indicator, data: dict[str, float]) -> float | None:
        """Get indicator value from data."""
        key = indicator.get_id()
        return data.get(key)


@dataclass
class ConditionGroup:
    """Group of conditions combined with logic operators"""

    conditions: list[Condition]
    logic: LogicOperator = LogicOperator.AND

    def evaluate(self, data: dict[str, float]) -> bool:
        """Evaluate all conditions in the group."""
        if not self.conditions:
            return False

        results = [c.evaluate(data) for c in self.conditions]

        if self.logic == LogicOperator.AND:
            return all(results)
        # OR
        return any(results)


@dataclass
class TradingAction:
    """Trading action to execute when conditions are met"""

    action_type: ActionType
    position_size: float = 1.0  # Percentage of balance or fixed size
    size_type: str = "percent"  # "percent" or "fixed"
    stop_loss: float | None = None  # Percentage or pips
    take_profit: float | None = None  # Percentage or pips
    trailing_stop: float | None = None


@dataclass
class StrategyRule:
    """A complete strategy rule with conditions and actions"""

    rule_id: str
    name: str
    condition_groups: list[ConditionGroup]
    action: TradingAction
    enabled: bool = True
    priority: int = 1  # Lower = higher priority


@dataclass
class NoCodeStrategy:
    """Complete no-code strategy definition"""

    strategy_id: str
    name: str
    description: str
    symbol: str
    timeframe: str
    rules: list[StrategyRule]
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)
    enabled: bool = True

    def to_json(self) -> str:
        """Serialize strategy to JSON."""
        return json.dumps(self.to_dict(), indent=2)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "strategy_id": self.strategy_id,
            "name": self.name,
            "description": self.description,
            "symbol": self.symbol,
            "timeframe": self.timeframe,
            "rules": [self._rule_to_dict(r) for r in self.rules],
            "enabled": self.enabled,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
        }

    def _rule_to_dict(self, rule: StrategyRule) -> dict[str, Any]:
        """Convert rule to dictionary."""
        return {
            "rule_id": rule.rule_id,
            "name": rule.name,
            "enabled": rule.enabled,
            "priority": rule.priority,
            "condition_groups": [
                {
                    "logic": cg.logic.value,
                    "conditions": [
                        {
                            "id": c.condition_id,
                            "left": {
                                "type": c.left_indicator.indicator_type.value,
                                "period": c.left_indicator.period,
                            },
                            "operator": c.operator.value,
                            "right": c.right_indicator
                            if isinstance(c.right_indicator, int | float)
                            else {
                                "type": c.right_indicator.indicator_type.value,
                                "period": c.right_indicator.period,
                            },
                        }
                        for c in cg.conditions
                    ],
                }
                for cg in rule.condition_groups
            ],
            "action": {
                "type": rule.action.action_type.value,
                "position_size": rule.action.position_size,
                "size_type": rule.action.size_type,
                "stop_loss": rule.action.stop_loss,
                "take_profit": rule.action.take_profit,
            },
        }
