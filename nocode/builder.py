# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""nocode/builder.py — No-code strategy builder logic."""

import logging
import re
from datetime import datetime, timezone

UTC = timezone.utc
from typing import Any

from nocode.models import (
    ActionType,
    Condition,
    ConditionGroup,
    ConditionOperator,
    Indicator,
    IndicatorType,
    LogicOperator,
    NoCodeStrategy,
    StrategyRule,
    TradingAction,
)

logger = logging.getLogger(__name__)


class NoCodeStrategyBuilder:
    """
    No-Code Strategy Builder

    Allows users to create trading strategies without writing code.

    Features:
    - Visual condition builder
    - Drag-and-drop interface support
    - Plain English strategy descriptions
    - Strategy validation
    - Export to Python code
    """

    def __init__(self, config: dict[str, Any] | None = None):
        """Initialize strategy builder."""
        self.config = config or {}
        self.strategies: dict[str, NoCodeStrategy] = {}
        self.templates: dict[str, NoCodeStrategy] = {}

        # Initialize built-in templates
        self._create_templates()

        logger.info("No-Code Strategy Builder initialized")

    def _create_templates(self):
        """Create built-in strategy templates."""
        # RSI Oversold/Overbought Template
        rsi_strategy = self.create_strategy(
            name="RSI Reversal",
            description="Buy when RSI is oversold (<30), sell when overbought (>70)",
            symbol="XAUUSD",
            timeframe="1H",
        )

        # Add buy rule
        self.add_rule(
            rsi_strategy.strategy_id,
            name="Buy on RSI Oversold",
            conditions=[{"left": {"type": "RSI", "period": 14}, "operator": "<", "right": 30}],
            action={"type": "BUY", "position_size": 1.0},
        )

        # Add sell rule
        self.add_rule(
            rsi_strategy.strategy_id,
            name="Sell on RSI Overbought",
            conditions=[{"left": {"type": "RSI", "period": 14}, "operator": ">", "right": 70}],
            action={"type": "SELL", "position_size": 1.0},
        )

        self.templates["rsi_reversal"] = rsi_strategy

        # MA Crossover Template
        ma_strategy = self.create_strategy(
            name="MA Crossover",
            description="Buy when fast MA crosses above slow MA, sell when crosses below",
            symbol="XAUUSD",
            timeframe="1H",
        )

        self.add_rule(
            ma_strategy.strategy_id,
            name="Buy on Golden Cross",
            conditions=[
                {
                    "left": {"type": "SMA", "period": 10},
                    "operator": "crosses_above",
                    "right": {"type": "SMA", "period": 50},
                }
            ],
            action={"type": "BUY", "position_size": 2.0, "stop_loss": 1.5},
        )

        self.templates["ma_crossover"] = ma_strategy

        logger.info("Created %s strategy templates", len(self.templates))

    def create_strategy(self, name: str, description: str, symbol: str, timeframe: str) -> NoCodeStrategy:
        """
        Create a new no-code strategy.

        Args:
            name: Strategy name
            description: Strategy description
            symbol: Trading symbol
            timeframe: Chart timeframe

        Returns:
            New strategy object
        """
        strategy_id = f"strategy_{len(self.strategies) + 1}_{int(datetime.now(UTC).timestamp())}"

        strategy = NoCodeStrategy(
            strategy_id=strategy_id,
            name=name,
            description=description,
            symbol=symbol,
            timeframe=timeframe,
            rules=[],
        )

        self.strategies[strategy_id] = strategy
        logger.info("Created strategy: %s", name)

        return strategy

    def add_rule(
        self,
        strategy_id: str,
        name: str,
        conditions: list[dict[str, Any]],
        action: dict[str, Any],
        logic: str = "AND",
    ) -> StrategyRule | None:
        """
        Add a rule to a strategy.

        Args:
            strategy_id: Strategy ID
            name: Rule name
            conditions: List of condition definitions
            action: Action definition
            logic: "AND" or "OR" for combining conditions

        Returns:
            New rule object
        """
        strategy = self.strategies.get(strategy_id)
        if not strategy:
            logger.error("Strategy not found: %s", strategy_id)

            return None

        # Parse conditions
        parsed_conditions = []
        for i, cond in enumerate(conditions):
            left_ind = self._parse_indicator(cond["left"])

            if isinstance(cond["right"], int | float):
                right_ind = cond["right"]
            else:
                right_ind = self._parse_indicator(cond["right"])

            operator = self._parse_operator(cond["operator"])

            parsed_conditions.append(
                Condition(
                    condition_id=f"cond_{i}",
                    left_indicator=left_ind,
                    operator=operator,
                    right_indicator=right_ind,
                )
            )

        # Create condition group
        condition_group = ConditionGroup(conditions=parsed_conditions, logic=LogicOperator[logic])

        # Parse action
        trading_action = TradingAction(
            action_type=ActionType[action["type"]],
            position_size=action.get("position_size", 1.0),
            size_type=action.get("size_type", "percent"),
            stop_loss=action.get("stop_loss"),
            take_profit=action.get("take_profit"),
            trailing_stop=action.get("trailing_stop"),
        )

        # Create rule
        rule = StrategyRule(
            rule_id=f"rule_{len(strategy.rules) + 1}",
            name=name,
            condition_groups=[condition_group],
            action=trading_action,
        )

        strategy.rules.append(rule)
        strategy.updated_at = datetime.now(UTC)

        logger.info("Added rule '%s' to strategy %s", name, strategy_id)

        return rule

    def _parse_indicator(self, ind_def: dict[str, Any]) -> Indicator:
        """Parse indicator definition."""
        return Indicator(
            indicator_type=IndicatorType[ind_def["type"]],
            period=ind_def.get("period", 14),
            source=ind_def.get("source", "close"),
            params=ind_def.get("params", {}),
        )

    def _parse_operator(self, op_str: str) -> ConditionOperator:
        """Parse operator string."""
        op_map = {
            ">": ConditionOperator.GREATER_THAN,
            "<": ConditionOperator.LESS_THAN,
            ">=": ConditionOperator.GREATER_EQUAL,
            "<=": ConditionOperator.LESS_EQUAL,
            "==": ConditionOperator.EQUAL,
            "!=": ConditionOperator.NOT_EQUAL,
            "crosses_above": ConditionOperator.CROSSES_ABOVE,
            "crosses_below": ConditionOperator.CROSSES_BELOW,
        }
        return op_map.get(op_str, ConditionOperator.GREATER_THAN)

    def parse_plain_english(self, description: str, symbol: str, timeframe: str) -> NoCodeStrategy | None:
        """
        Parse a plain English strategy description.

        Examples:
        - "Buy when RSI is below 30 and price is above SMA 200"
        - "Sell when price crosses below EMA 20"
        - "Close all positions when drawdown exceeds 5%"

        Args:
            description: Plain English strategy description
            symbol: Trading symbol
            timeframe: Chart timeframe

        Returns:
            Parsed strategy or None
        """
        description_lower = description.lower()

        # Create strategy
        strategy = self.create_strategy(
            name=f"Strategy from: {description[:50]}...",
            description=description,
            symbol=symbol,
            timeframe=timeframe,
        )

        # Parse buy conditions
        if "buy when" in description_lower or "buy if" in description_lower:
            conditions = self._parse_conditions(description_lower, "buy")
            if conditions:
                self.add_rule(
                    strategy.strategy_id,
                    name="Buy Rule",
                    conditions=conditions,
                    action={"type": "BUY", "position_size": 1.0},
                )

        # Parse sell conditions
        if "sell when" in description_lower or "sell if" in description_lower:
            conditions = self._parse_conditions(description_lower, "sell")
            if conditions:
                self.add_rule(
                    strategy.strategy_id,
                    name="Sell Rule",
                    conditions=conditions,
                    action={"type": "SELL", "position_size": 1.0},
                )

        logger.info("Parsed strategy from plain English: %s rules", len(strategy.rules))

        return strategy

    def _parse_conditions(self, text: str, action: str) -> list[dict[str, Any]]:
        """Parse conditions from text."""
        conditions = []

        # Find the relevant part of the text
        patterns = {
            "buy": r"buy (?:when|if)\s+(.+?)(?:,|$|\.|and sell)",
            "sell": r"sell (?:when|if)\s+(.+?)(?:,|$|\.)",
        }

        match = re.search(patterns[action], text)
        if not match:
            return conditions

        condition_text = match.group(1)

        # Parse RSI conditions
        rsi_match = re.search(r"rsi\s*(?:is\s*)?(?:below|<)\s*(\d+)", condition_text)
        if rsi_match:
            conditions.append(
                {
                    "left": {"type": "RSI", "period": 14},
                    "operator": "<",
                    "right": int(rsi_match.group(1)),
                }
            )

        rsi_match = re.search(r"rsi\s*(?:is\s*)?(?:above|>)\s*(\d+)", condition_text)
        if rsi_match:
            conditions.append(
                {
                    "left": {"type": "RSI", "period": 14},
                    "operator": ">",
                    "right": int(rsi_match.group(1)),
                }
            )

        # Parse SMA conditions
        sma_match = re.search(r"price\s*(?:is\s*)?above\s*sma\s*(\d+)", condition_text)
        if sma_match:
            conditions.append(
                {
                    "left": {"type": "PRICE", "period": 1},
                    "operator": ">",
                    "right": {"type": "SMA", "period": int(sma_match.group(1))},
                }
            )

        return conditions

    def export_to_python(self, strategy_id: str) -> str:
        """
        Export strategy to Python code.

        Args:
            strategy_id: Strategy ID

        Returns:
            Python code string
        """
        strategy = self.strategies.get(strategy_id)
        if not strategy:
            return ""

        code = f'''"""
Auto-generated strategy: {strategy.name}
Description: {strategy.description}
Generated: {datetime.now(UTC).isoformat()}
"""

from strategies.base import BaseStrategy, Signal, SignalType, StrategyConfig
from typing import Any

class {self._to_class_name(strategy.name)}(BaseStrategy):
    """
    {strategy.description}
    """

    def __init__(self, config: StrategyConfig):
        super().__init__(config)
        # Strategy parameters
        self.symbol = "{strategy.symbol}"
        self.timeframe = "{strategy.timeframe}"

    def analyze(self, data: dict[str, Any]) -> dict[str, Any]:
        """Analyze market data."""
        analysis = {{'analyzed': True}}

        # Calculate indicators
        close_prices = data.get('close', [])
        if len(close_prices) > 0:
            analysis['price'] = close_prices[-1]

        return analysis

    def generate_signal(self, analysis: dict[str, Any]) -> Signal:
        """Generate trading signal based on analysis."""
'''

        for rule in strategy.rules:
            code += f"""
        # Rule: {rule.name}
        # Conditions: {len(rule.condition_groups[0].conditions) if rule.condition_groups else 0}
        # Action: {rule.action.action_type.value}
"""

        code += """
        return None  # Implement signal logic
"""

        return code

    def _to_class_name(self, name: str) -> str:
        """Convert name to valid Python class name."""
        # Remove non-alphanumeric characters and convert to PascalCase
        words = re.findall(r"[a-zA-Z0-9]+", name)
        return "".join(word.capitalize() for word in words) + "Strategy"

    def get_available_indicators(self) -> list[dict[str, Any]]:
        """Get list of available indicators for the builder."""
        indicators = []
        for ind_type in IndicatorType:
            indicators.append(
                {
                    "type": ind_type.value,
                    "name": ind_type.value.replace("_", " ").title(),
                    "default_period": 14,
                    "description": self._get_indicator_description(ind_type),
                }
            )
        return indicators

    def _get_indicator_description(self, ind_type: IndicatorType) -> str:
        """Get indicator description."""
        descriptions = {
            IndicatorType.PRICE: "Current price",
            IndicatorType.SMA: "Simple Moving Average",
            IndicatorType.EMA: "Exponential Moving Average",
            IndicatorType.RSI: "Relative Strength Index (0-100)",
            IndicatorType.MACD: "Moving Average Convergence Divergence",
            IndicatorType.BOLLINGER_UPPER: "Upper Bollinger Band",
            IndicatorType.BOLLINGER_LOWER: "Lower Bollinger Band",
            IndicatorType.ATR: "Average True Range",
            IndicatorType.STOCHASTIC_K: "Stochastic %K",
            IndicatorType.ADX: "Average Directional Index",
            IndicatorType.CCI: "Commodity Channel Index",
            IndicatorType.VOLUME: "Trading Volume",
        }
        return descriptions.get(ind_type, "Technical indicator")

    def get_templates(self, category: str | None = None) -> list[dict[str, Any]]:
        """Get list of available strategy templates, optionally filtered by category."""
        out = [
            {
                "id": tid,
                "name": t.name,
                "description": t.description,
                "category": getattr(t, "category", "custom"),
                "rules_count": len(t.rules),
            }
            for tid, t in self.templates.items()
        ]
        if category:
            cat = category.lower()
            out = [t for t in out if str(t.get("category", "")).lower() == cat]
        return out

    def create_from_template(self, template_id: str, name: str, symbol: str, timeframe: str) -> NoCodeStrategy | None:
        """Create a new strategy from a template."""
        template = self.templates.get(template_id)
        if not template:
            return None

        strategy = self.create_strategy(
            name=name,
            description=template.description,
            symbol=symbol,
            timeframe=timeframe,
        )

        # Copy rules from template
        for rule in template.rules:
            strategy.rules.append(
                StrategyRule(
                    rule_id=f"rule_{len(strategy.rules) + 1}",
                    name=rule.name,
                    condition_groups=rule.condition_groups,
                    action=rule.action,
                )
            )

        return strategy
