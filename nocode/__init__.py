"""
Phase 19: No-Code Strategy Builder Module

Provides a visual, no-code interface for building trading strategies
without programming knowledge.
"""

from typing import Dict, List, Optional, Any, Union
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
import logging
import json
import re

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
    params: Dict[str, Any] = field(default_factory=dict)
    
    def get_id(self) -> str:
        """Get unique identifier for this indicator."""
        return f"{self.indicator_type.value}_{self.period}_{self.source}"


@dataclass
class Condition:
    """Single condition in a strategy rule"""
    condition_id: str
    left_indicator: Indicator
    operator: ConditionOperator
    right_indicator: Union[Indicator, float]  # Can be indicator or constant
    
    def evaluate(self, data: Dict[str, float]) -> bool:
        """Evaluate the condition against current data."""
        left_value = self._get_value(self.left_indicator, data)
        
        if isinstance(self.right_indicator, (int, float)):
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
    
    def _get_value(self, indicator: Indicator, data: Dict[str, float]) -> Optional[float]:
        """Get indicator value from data."""
        key = indicator.get_id()
        return data.get(key)


@dataclass
class ConditionGroup:
    """Group of conditions combined with logic operators"""
    conditions: List[Condition]
    logic: LogicOperator = LogicOperator.AND
    
    def evaluate(self, data: Dict[str, float]) -> bool:
        """Evaluate all conditions in the group."""
        if not self.conditions:
            return False
        
        results = [c.evaluate(data) for c in self.conditions]
        
        if self.logic == LogicOperator.AND:
            return all(results)
        else:  # OR
            return any(results)


@dataclass
class TradingAction:
    """Trading action to execute when conditions are met"""
    action_type: ActionType
    position_size: float = 1.0  # Percentage of balance or fixed size
    size_type: str = "percent"  # "percent" or "fixed"
    stop_loss: Optional[float] = None  # Percentage or pips
    take_profit: Optional[float] = None  # Percentage or pips
    trailing_stop: Optional[float] = None


@dataclass
class StrategyRule:
    """A complete strategy rule with conditions and actions"""
    rule_id: str
    name: str
    condition_groups: List[ConditionGroup]
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
    rules: List[StrategyRule]
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)
    enabled: bool = True
    
    def to_json(self) -> str:
        """Serialize strategy to JSON."""
        return json.dumps(self.to_dict(), indent=2)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            'strategy_id': self.strategy_id,
            'name': self.name,
            'description': self.description,
            'symbol': self.symbol,
            'timeframe': self.timeframe,
            'rules': [self._rule_to_dict(r) for r in self.rules],
            'enabled': self.enabled,
            'created_at': self.created_at.isoformat(),
            'updated_at': self.updated_at.isoformat(),
        }
    
    def _rule_to_dict(self, rule: StrategyRule) -> Dict[str, Any]:
        """Convert rule to dictionary."""
        return {
            'rule_id': rule.rule_id,
            'name': rule.name,
            'enabled': rule.enabled,
            'priority': rule.priority,
            'condition_groups': [
                {
                    'logic': cg.logic.value,
                    'conditions': [
                        {
                            'id': c.condition_id,
                            'left': {
                                'type': c.left_indicator.indicator_type.value,
                                'period': c.left_indicator.period,
                            },
                            'operator': c.operator.value,
                            'right': c.right_indicator if isinstance(c.right_indicator, (int, float)) else {
                                'type': c.right_indicator.indicator_type.value,
                                'period': c.right_indicator.period,
                            }
                        }
                        for c in cg.conditions
                    ]
                }
                for cg in rule.condition_groups
            ],
            'action': {
                'type': rule.action.action_type.value,
                'position_size': rule.action.position_size,
                'size_type': rule.action.size_type,
                'stop_loss': rule.action.stop_loss,
                'take_profit': rule.action.take_profit,
            }
        }


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
    
    def __init__(self, config: Optional[Dict[str, Any]] = None):
        """Initialize strategy builder."""
        self.config = config or {}
        self.strategies: Dict[str, NoCodeStrategy] = {}
        self.templates: Dict[str, NoCodeStrategy] = {}
        
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
            timeframe="1H"
        )
        
        # Add buy rule
        self.add_rule(
            rsi_strategy.strategy_id,
            name="Buy on RSI Oversold",
            conditions=[
                {
                    'left': {'type': 'RSI', 'period': 14},
                    'operator': '<',
                    'right': 30
                }
            ],
            action={'type': 'BUY', 'position_size': 1.0}
        )
        
        # Add sell rule
        self.add_rule(
            rsi_strategy.strategy_id,
            name="Sell on RSI Overbought",
            conditions=[
                {
                    'left': {'type': 'RSI', 'period': 14},
                    'operator': '>',
                    'right': 70
                }
            ],
            action={'type': 'SELL', 'position_size': 1.0}
        )
        
        self.templates['rsi_reversal'] = rsi_strategy
        
        # MA Crossover Template
        ma_strategy = self.create_strategy(
            name="MA Crossover",
            description="Buy when fast MA crosses above slow MA, sell when crosses below",
            symbol="XAUUSD",
            timeframe="1H"
        )
        
        self.add_rule(
            ma_strategy.strategy_id,
            name="Buy on Golden Cross",
            conditions=[
                {
                    'left': {'type': 'SMA', 'period': 10},
                    'operator': 'crosses_above',
                    'right': {'type': 'SMA', 'period': 50}
                }
            ],
            action={'type': 'BUY', 'position_size': 2.0, 'stop_loss': 1.5}
        )
        
        self.templates['ma_crossover'] = ma_strategy
        
        logger.info(f"Created {len(self.templates)} strategy templates")
    
    def create_strategy(
        self,
        name: str,
        description: str,
        symbol: str,
        timeframe: str
    ) -> NoCodeStrategy:
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
        strategy_id = f"strategy_{len(self.strategies) + 1}_{int(datetime.now().timestamp())}"
        
        strategy = NoCodeStrategy(
            strategy_id=strategy_id,
            name=name,
            description=description,
            symbol=symbol,
            timeframe=timeframe,
            rules=[]
        )
        
        self.strategies[strategy_id] = strategy
        logger.info(f"Created strategy: {name}")
        return strategy
    
    def add_rule(
        self,
        strategy_id: str,
        name: str,
        conditions: List[Dict[str, Any]],
        action: Dict[str, Any],
        logic: str = "AND"
    ) -> Optional[StrategyRule]:
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
            logger.error(f"Strategy not found: {strategy_id}")
            return None
        
        # Parse conditions
        parsed_conditions = []
        for i, cond in enumerate(conditions):
            left_ind = self._parse_indicator(cond['left'])
            
            if isinstance(cond['right'], (int, float)):
                right_ind = cond['right']
            else:
                right_ind = self._parse_indicator(cond['right'])
            
            operator = self._parse_operator(cond['operator'])
            
            parsed_conditions.append(Condition(
                condition_id=f"cond_{i}",
                left_indicator=left_ind,
                operator=operator,
                right_indicator=right_ind
            ))
        
        # Create condition group
        condition_group = ConditionGroup(
            conditions=parsed_conditions,
            logic=LogicOperator[logic]
        )
        
        # Parse action
        trading_action = TradingAction(
            action_type=ActionType[action['type']],
            position_size=action.get('position_size', 1.0),
            size_type=action.get('size_type', 'percent'),
            stop_loss=action.get('stop_loss'),
            take_profit=action.get('take_profit'),
            trailing_stop=action.get('trailing_stop')
        )
        
        # Create rule
        rule = StrategyRule(
            rule_id=f"rule_{len(strategy.rules) + 1}",
            name=name,
            condition_groups=[condition_group],
            action=trading_action
        )
        
        strategy.rules.append(rule)
        strategy.updated_at = datetime.now()
        
        logger.info(f"Added rule '{name}' to strategy {strategy_id}")
        return rule
    
    def _parse_indicator(self, ind_def: Dict[str, Any]) -> Indicator:
        """Parse indicator definition."""
        return Indicator(
            indicator_type=IndicatorType[ind_def['type']],
            period=ind_def.get('period', 14),
            source=ind_def.get('source', 'close'),
            params=ind_def.get('params', {})
        )
    
    def _parse_operator(self, op_str: str) -> ConditionOperator:
        """Parse operator string."""
        op_map = {
            '>': ConditionOperator.GREATER_THAN,
            '<': ConditionOperator.LESS_THAN,
            '>=': ConditionOperator.GREATER_EQUAL,
            '<=': ConditionOperator.LESS_EQUAL,
            '==': ConditionOperator.EQUAL,
            '!=': ConditionOperator.NOT_EQUAL,
            'crosses_above': ConditionOperator.CROSSES_ABOVE,
            'crosses_below': ConditionOperator.CROSSES_BELOW,
        }
        return op_map.get(op_str, ConditionOperator.GREATER_THAN)
    
    def parse_plain_english(self, description: str, symbol: str, timeframe: str) -> Optional[NoCodeStrategy]:
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
            timeframe=timeframe
        )
        
        # Parse buy conditions
        if 'buy when' in description_lower or 'buy if' in description_lower:
            conditions = self._parse_conditions(description_lower, 'buy')
            if conditions:
                self.add_rule(
                    strategy.strategy_id,
                    name="Buy Rule",
                    conditions=conditions,
                    action={'type': 'BUY', 'position_size': 1.0}
                )
        
        # Parse sell conditions
        if 'sell when' in description_lower or 'sell if' in description_lower:
            conditions = self._parse_conditions(description_lower, 'sell')
            if conditions:
                self.add_rule(
                    strategy.strategy_id,
                    name="Sell Rule",
                    conditions=conditions,
                    action={'type': 'SELL', 'position_size': 1.0}
                )
        
        logger.info(f"Parsed strategy from plain English: {len(strategy.rules)} rules")
        return strategy
    
    def _parse_conditions(self, text: str, action: str) -> List[Dict[str, Any]]:
        """Parse conditions from text."""
        conditions = []
        
        # Find the relevant part of the text
        patterns = {
            'buy': r'buy (?:when|if)\s+(.+?)(?:,|$|\.|and sell)',
            'sell': r'sell (?:when|if)\s+(.+?)(?:,|$|\.)',
        }
        
        match = re.search(patterns[action], text)
        if not match:
            return conditions
        
        condition_text = match.group(1)
        
        # Parse RSI conditions
        rsi_match = re.search(r'rsi\s*(?:is\s*)?(?:below|<)\s*(\d+)', condition_text)
        if rsi_match:
            conditions.append({
                'left': {'type': 'RSI', 'period': 14},
                'operator': '<',
                'right': int(rsi_match.group(1))
            })
        
        rsi_match = re.search(r'rsi\s*(?:is\s*)?(?:above|>)\s*(\d+)', condition_text)
        if rsi_match:
            conditions.append({
                'left': {'type': 'RSI', 'period': 14},
                'operator': '>',
                'right': int(rsi_match.group(1))
            })
        
        # Parse SMA conditions
        sma_match = re.search(r'price\s*(?:is\s*)?above\s*sma\s*(\d+)', condition_text)
        if sma_match:
            conditions.append({
                'left': {'type': 'PRICE', 'period': 1},
                'operator': '>',
                'right': {'type': 'SMA', 'period': int(sma_match.group(1))}
            })
        
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
Generated: {datetime.now().isoformat()}
"""

from strategies.base import BaseStrategy, Signal, SignalType, StrategyConfig
from typing import Dict, Any

class {self._to_class_name(strategy.name)}(BaseStrategy):
    """
    {strategy.description}
    """
    
    def __init__(self, config: StrategyConfig):
        super().__init__(config)
        # Strategy parameters
        self.symbol = "{strategy.symbol}"
        self.timeframe = "{strategy.timeframe}"
    
    def analyze(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Analyze market data."""
        analysis = {{'analyzed': True}}
        
        # Calculate indicators
        close_prices = data.get('close', [])
        if len(close_prices) > 0:
            analysis['price'] = close_prices[-1]
        
        return analysis
    
    def generate_signal(self, analysis: Dict[str, Any]) -> Signal:
        """Generate trading signal based on analysis."""
'''
        
        for rule in strategy.rules:
            code += f'''
        # Rule: {rule.name}
        # Conditions: {len(rule.condition_groups[0].conditions) if rule.condition_groups else 0}
        # Action: {rule.action.action_type.value}
'''
        
        code += '''
        return None  # Implement signal logic
'''
        
        return code
    
    def _to_class_name(self, name: str) -> str:
        """Convert name to valid Python class name."""
        # Remove non-alphanumeric characters and convert to PascalCase
        words = re.findall(r'[a-zA-Z0-9]+', name)
        return ''.join(word.capitalize() for word in words) + 'Strategy'
    
    def get_available_indicators(self) -> List[Dict[str, Any]]:
        """Get list of available indicators for the builder."""
        indicators = []
        for ind_type in IndicatorType:
            indicators.append({
                'type': ind_type.value,
                'name': ind_type.value.replace('_', ' ').title(),
                'default_period': 14,
                'description': self._get_indicator_description(ind_type)
            })
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
    
    def get_templates(self) -> List[Dict[str, Any]]:
        """Get list of available strategy templates."""
        return [
            {
                'id': tid,
                'name': t.name,
                'description': t.description,
                'rules_count': len(t.rules)
            }
            for tid, t in self.templates.items()
        ]
    
    def create_from_template(self, template_id: str, name: str, symbol: str, timeframe: str) -> Optional[NoCodeStrategy]:
        """Create a new strategy from a template."""
        template = self.templates.get(template_id)
        if not template:
            return None
        
        strategy = self.create_strategy(
            name=name,
            description=template.description,
            symbol=symbol,
            timeframe=timeframe
        )
        
        # Copy rules from template
        for rule in template.rules:
            strategy.rules.append(StrategyRule(
                rule_id=f"rule_{len(strategy.rules) + 1}",
                name=rule.name,
                condition_groups=rule.condition_groups,
                action=rule.action
            ))
        
        return strategy


def create_nocode_router(builder: 'NoCodeStrategyBuilder'):
    """
    Create a FastAPI router for the No-Code Strategy Builder module.

    Args:
        builder: NoCodeStrategyBuilder instance

    Returns:
        FastAPI APIRouter
    """
    from fastapi import APIRouter, HTTPException
    from pydantic import BaseModel
    from typing import Optional, List, Dict, Any

    router = APIRouter(prefix="/api/nocode", tags=["No-Code Builder"])

    class CreateStrategyRequest(BaseModel):
        name: str
        description: str = ""
        symbol: str = "XAUUSD"
        timeframe: str = "1h"

    class PlainEnglishRequest(BaseModel):
        description: str
        symbol: str = "XAUUSD"
        timeframe: str = "1h"

    class FromTemplateRequest(BaseModel):
        name: str
        symbol: str = "XAUUSD"
        timeframe: str = "1h"

    @router.get("/strategies")
    async def list_strategies():
        """List all no-code strategies."""
        return [
            {
                "strategy_id": sid,
                "name": s.name,
                "description": s.description,
                "symbol": s.symbol,
                "timeframe": s.timeframe,
                "is_active": s.is_active,
                "rules_count": len(s.rules),
                "created_at": s.created_at.isoformat(),
            }
            for sid, s in builder.strategies.items()
        ]

    @router.post("/strategies")
    async def create_strategy(req: CreateStrategyRequest):
        """Create a new empty no-code strategy."""
        strategy = builder.create_strategy(
            name=req.name,
            description=req.description,
            symbol=req.symbol,
            timeframe=req.timeframe,
        )
        return {
            "strategy_id": strategy.strategy_id,
            "name": strategy.name,
            "symbol": strategy.symbol,
            "timeframe": strategy.timeframe,
        }

    @router.get("/strategies/{strategy_id}/export")
    async def export_strategy(strategy_id: str):
        """Export a no-code strategy as Python code."""
        code = builder.export_to_python(strategy_id)
        if code is None:
            raise HTTPException(status_code=404, detail=f"Strategy {strategy_id} not found")
        return {"strategy_id": strategy_id, "python_code": code}

    @router.post("/strategies/parse")
    async def parse_plain_english(req: PlainEnglishRequest):
        """Parse a plain-English strategy description into a structured strategy."""
        strategy = builder.parse_plain_english(
            req.description, req.symbol, req.timeframe
        )
        if strategy is None:
            raise HTTPException(
                status_code=422,
                detail="Could not parse strategy description. Try including trigger conditions and actions.",
            )
        return {
            "strategy_id": strategy.strategy_id,
            "name": strategy.name,
            "rules_count": len(strategy.rules),
            "symbol": strategy.symbol,
            "timeframe": strategy.timeframe,
        }

    @router.get("/indicators")
    async def get_indicators():
        """Get list of available indicators for building conditions."""
        return builder.get_available_indicators()

    @router.get("/templates")
    async def get_templates():
        """Get list of built-in strategy templates."""
        return builder.get_templates()

    @router.post("/strategies/from-template/{template_id}")
    async def create_from_template(template_id: str, req: FromTemplateRequest):
        """Create a strategy from a built-in template."""
        strategy = builder.create_from_template(
            template_id, req.name, req.symbol, req.timeframe
        )
        if strategy is None:
            raise HTTPException(status_code=404, detail=f"Template {template_id} not found")
        return {
            "strategy_id": strategy.strategy_id,
            "name": strategy.name,
            "rules_count": len(strategy.rules),
        }

    return router


# Module exports
__all__ = [
    'NoCodeStrategyBuilder',
    'NoCodeStrategy',
    'StrategyRule',
    'Condition',
    'ConditionGroup',
    'TradingAction',
    'Indicator',
    'IndicatorType',
    'ConditionOperator',
    'LogicOperator',
    'ActionType',
    'create_nocode_router',
]
