# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
nocode/state_machine.py
========================
State Machine Engine for the No-Code Strategy Builder.

Enables users to define complex trading strategies as finite state machines
with transitions triggered by market conditions, time events, and ML signals.

Architecture
------------
- State: represents a discrete market/position state (e.g., "flat", "long", "scaling_in")
- Transition: defines conditions that trigger movement between states
- Action: operations executed on state entry/exit (place order, adjust SL, etc.)
- StateMachineStrategy: wraps the FSM into a strategy compatible with the engine

States can have:
- Entry actions (executed when entering the state)
- Exit actions (executed when leaving the state)
- Dwell time limits (max time in state before forced transition)
- Nested sub-states for complex multi-phase entries

Usage
-----
    from nocode.state_machine import StateMachineBuilder, StateMachineStrategy

    builder = StateMachineBuilder()
    sm = builder.create("Trend Follower FSM")

    # Define states
    builder.add_state(sm, "flat", is_initial=True)
    builder.add_state(sm, "long_entry", entry_actions=["place_buy_order"])
    builder.add_state(sm, "long_hold", entry_actions=["set_trailing_stop"])
    builder.add_state(sm, "exit", entry_actions=["close_position"])

    # Define transitions
    builder.add_transition(sm, "flat", "long_entry",
        conditions=[{"type": "indicator", "name": "RSI", "operator": "<", "value": 30}])
    builder.add_transition(sm, "long_entry", "long_hold",
        conditions=[{"type": "fill", "status": "filled"}])
    builder.add_transition(sm, "long_hold", "exit",
        conditions=[{"type": "indicator", "name": "RSI", "operator": ">", "value": 70}])
    builder.add_transition(sm, "exit", "flat",
        conditions=[{"type": "position", "status": "closed"}])

    # Convert to executable strategy
    strategy = StateMachineStrategy(sm)
"""
from __future__ import annotations

import asyncio
import logging
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable

import numpy as np

UTC = timezone.utc
logger = logging.getLogger(__name__)


# ── Enums ─────────────────────────────────────────────────────────────────────


class ConditionType(Enum):
    INDICATOR = "indicator"
    PRICE = "price"
    TIME = "time"
    POSITION = "position"
    FILL = "fill"
    ML_SIGNAL = "ml_signal"
    CUSTOM = "custom"
    DWELL_TIME = "dwell_time"


class ActionType(Enum):
    PLACE_ORDER = "place_order"
    CLOSE_POSITION = "close_position"
    MODIFY_SL = "modify_sl"
    MODIFY_TP = "modify_tp"
    SET_TRAILING_STOP = "set_trailing_stop"
    SCALE_IN = "scale_in"
    SCALE_OUT = "scale_out"
    SEND_ALERT = "send_alert"
    LOG_EVENT = "log_event"
    CANCEL_ORDERS = "cancel_orders"


class ComparisonOperator(Enum):
    GT = ">"
    GTE = ">="
    LT = "<"
    LTE = "<="
    EQ = "=="
    NEQ = "!="
    CROSSES_ABOVE = "crosses_above"
    CROSSES_BELOW = "crosses_below"


# ── Data Models ───────────────────────────────────────────────────────────────


@dataclass
class Condition:
    """A single condition that must be met for a transition."""
    condition_type: ConditionType
    params: dict[str, Any] = field(default_factory=dict)

    def evaluate(self, context: dict[str, Any]) -> bool:
        """Evaluate this condition against the current market context."""
        if self.condition_type == ConditionType.INDICATOR:
            return self._eval_indicator(context)
        elif self.condition_type == ConditionType.PRICE:
            return self._eval_price(context)
        elif self.condition_type == ConditionType.TIME:
            return self._eval_time(context)
        elif self.condition_type == ConditionType.POSITION:
            return self._eval_position(context)
        elif self.condition_type == ConditionType.ML_SIGNAL:
            return self._eval_ml_signal(context)
        elif self.condition_type == ConditionType.DWELL_TIME:
            return self._eval_dwell_time(context)
        return False

    def _eval_indicator(self, context: dict[str, Any]) -> bool:
        """Evaluate an indicator condition."""
        indicators = context.get("indicators", {})
        name = self.params.get("name", "")
        period = self.params.get("period", 14)
        operator = self.params.get("operator", ">")
        value = self.params.get("value", 0)

        key = f"{name}_{period}" if period else name
        current_value = indicators.get(key, indicators.get(name))
        if current_value is None:
            return False

        return self._compare(float(current_value), operator, float(value))

    def _eval_price(self, context: dict[str, Any]) -> bool:
        """Evaluate a price condition."""
        price = context.get("price", 0)
        operator = self.params.get("operator", ">")
        value = self.params.get("value", 0)
        return self._compare(float(price), operator, float(value))

    def _eval_time(self, context: dict[str, Any]) -> bool:
        """Evaluate a time-based condition."""
        current_hour = datetime.now(UTC).hour
        target_hour = self.params.get("hour")
        if target_hour is not None:
            return current_hour == target_hour

        # Day of week check
        current_day = datetime.now(UTC).weekday()
        target_day = self.params.get("day_of_week")
        if target_day is not None:
            return current_day == target_day

        return False

    def _eval_position(self, context: dict[str, Any]) -> bool:
        """Evaluate a position status condition."""
        position = context.get("position", {})
        expected_status = self.params.get("status", "")
        actual_status = position.get("status", "flat")
        return actual_status == expected_status

    def _eval_ml_signal(self, context: dict[str, Any]) -> bool:
        """Evaluate an ML model signal condition."""
        ml_signals = context.get("ml_signals", {})
        model_name = self.params.get("model", "")
        operator = self.params.get("operator", ">")
        threshold = self.params.get("threshold", 0.5)

        signal_value = ml_signals.get(model_name)
        if signal_value is None:
            return False

        return self._compare(float(signal_value), operator, float(threshold))

    def _eval_dwell_time(self, context: dict[str, Any]) -> bool:
        """Evaluate if the state has been active for longer than max dwell time."""
        state_entered_at = context.get("state_entered_at", 0)
        max_seconds = self.params.get("max_seconds", 3600)
        elapsed = time.time() - state_entered_at
        return elapsed > max_seconds

    def _compare(self, left: float, operator: str, right: float) -> bool:
        """Perform a comparison operation."""
        if operator in (">", ComparisonOperator.GT.value):
            return left > right
        elif operator in (">=", ComparisonOperator.GTE.value):
            return left >= right
        elif operator in ("<", ComparisonOperator.LT.value):
            return left < right
        elif operator in ("<=", ComparisonOperator.LTE.value):
            return left <= right
        elif operator in ("==", ComparisonOperator.EQ.value):
            return abs(left - right) < 1e-10
        elif operator in ("!=", ComparisonOperator.NEQ.value):
            return abs(left - right) >= 1e-10
        return False

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": self.condition_type.value,
            "params": self.params,
        }


@dataclass
class Action:
    """An action to execute on state entry or exit."""
    action_type: ActionType
    params: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": self.action_type.value,
            "params": self.params,
        }


@dataclass
class Transition:
    """A transition between two states."""
    transition_id: str
    from_state: str
    to_state: str
    conditions: list[Condition] = field(default_factory=list)
    condition_logic: str = "AND"  # "AND" or "OR"
    priority: int = 0  # Higher priority transitions are checked first

    def evaluate(self, context: dict[str, Any]) -> bool:
        """Evaluate all conditions for this transition."""
        if not self.conditions:
            return False

        if self.condition_logic == "AND":
            return all(c.evaluate(context) for c in self.conditions)
        else:  # OR
            return any(c.evaluate(context) for c in self.conditions)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.transition_id,
            "from": self.from_state,
            "to": self.to_state,
            "conditions": [c.to_dict() for c in self.conditions],
            "logic": self.condition_logic,
            "priority": self.priority,
        }


@dataclass
class State:
    """A state in the finite state machine."""
    name: str
    is_initial: bool = False
    is_terminal: bool = False
    entry_actions: list[Action] = field(default_factory=list)
    exit_actions: list[Action] = field(default_factory=list)
    max_dwell_seconds: int | None = None  # Max time in this state
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "is_initial": self.is_initial,
            "is_terminal": self.is_terminal,
            "entry_actions": [a.to_dict() for a in self.entry_actions],
            "exit_actions": [a.to_dict() for a in self.exit_actions],
            "max_dwell_seconds": self.max_dwell_seconds,
            "metadata": self.metadata,
        }


@dataclass
class StateMachineDefinition:
    """Complete definition of a state machine strategy."""
    machine_id: str
    name: str
    description: str = ""
    states: dict[str, State] = field(default_factory=dict)
    transitions: list[Transition] = field(default_factory=list)
    initial_state: str = ""
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    symbol: str = "XAU_USD"
    timeframe: str = "M15"

    def to_dict(self) -> dict[str, Any]:
        return {
            "machine_id": self.machine_id,
            "name": self.name,
            "description": self.description,
            "states": {k: v.to_dict() for k, v in self.states.items()},
            "transitions": [t.to_dict() for t in self.transitions],
            "initial_state": self.initial_state,
            "created_at": self.created_at.isoformat(),
            "symbol": self.symbol,
            "timeframe": self.timeframe,
        }


# ── State Machine Builder ────────────────────────────────────────────────────


class StateMachineBuilder:
    """
    Builder for creating state machine strategy definitions.

    Provides a fluent API for constructing FSM-based trading strategies
    that can be exported to Python code or executed directly.
    """

    def __init__(self) -> None:
        self._machines: dict[str, StateMachineDefinition] = {}

    def create(
        self,
        name: str,
        description: str = "",
        symbol: str = "XAU_USD",
        timeframe: str = "M15",
    ) -> StateMachineDefinition:
        """Create a new state machine definition."""
        machine_id = f"sm_{uuid.uuid4().hex[:8]}"
        sm = StateMachineDefinition(
            machine_id=machine_id,
            name=name,
            description=description,
            symbol=symbol,
            timeframe=timeframe,
        )
        self._machines[machine_id] = sm
        return sm

    def add_state(
        self,
        sm: StateMachineDefinition,
        name: str,
        is_initial: bool = False,
        is_terminal: bool = False,
        entry_actions: list[dict[str, Any]] | None = None,
        exit_actions: list[dict[str, Any]] | None = None,
        max_dwell_seconds: int | None = None,
    ) -> State:
        """Add a state to the state machine."""
        state = State(
            name=name,
            is_initial=is_initial,
            is_terminal=is_terminal,
            max_dwell_seconds=max_dwell_seconds,
        )

        if entry_actions:
            for action_def in entry_actions:
                action_type = ActionType(action_def.get("type", "log_event"))
                state.entry_actions.append(
                    Action(action_type=action_type, params=action_def.get("params", {}))
                )

        if exit_actions:
            for action_def in exit_actions:
                action_type = ActionType(action_def.get("type", "log_event"))
                state.exit_actions.append(
                    Action(action_type=action_type, params=action_def.get("params", {}))
                )

        sm.states[name] = state

        if is_initial:
            sm.initial_state = name

        return state

    def add_transition(
        self,
        sm: StateMachineDefinition,
        from_state: str,
        to_state: str,
        conditions: list[dict[str, Any]],
        condition_logic: str = "AND",
        priority: int = 0,
    ) -> Transition:
        """Add a transition between two states."""
        if from_state not in sm.states:
            raise ValueError(f"Source state '{from_state}' not found")
        if to_state not in sm.states:
            raise ValueError(f"Target state '{to_state}' not found")

        parsed_conditions = []
        for cond_def in conditions:
            cond_type = ConditionType(cond_def.get("type", "indicator"))
            params = {k: v for k, v in cond_def.items() if k != "type"}
            parsed_conditions.append(Condition(condition_type=cond_type, params=params))

        transition = Transition(
            transition_id=f"t_{uuid.uuid4().hex[:6]}",
            from_state=from_state,
            to_state=to_state,
            conditions=parsed_conditions,
            condition_logic=condition_logic,
            priority=priority,
        )

        sm.transitions.append(transition)
        return transition

    def validate(self, sm: StateMachineDefinition) -> list[str]:
        """Validate the state machine definition for completeness."""
        errors = []

        if not sm.states:
            errors.append("State machine has no states defined")

        if not sm.initial_state:
            errors.append("No initial state defined")
        elif sm.initial_state not in sm.states:
            errors.append(f"Initial state '{sm.initial_state}' not found in states")

        if not sm.transitions:
            errors.append("State machine has no transitions defined")

        # Check for unreachable states
        reachable = {sm.initial_state}
        changed = True
        while changed:
            changed = False
            for t in sm.transitions:
                if t.from_state in reachable and t.to_state not in reachable:
                    reachable.add(t.to_state)
                    changed = True

        unreachable = set(sm.states.keys()) - reachable
        if unreachable:
            errors.append(f"Unreachable states: {unreachable}")

        # Check for dead-end states (non-terminal with no outgoing transitions)
        for state_name, state in sm.states.items():
            if state.is_terminal:
                continue
            outgoing = [t for t in sm.transitions if t.from_state == state_name]
            if not outgoing:
                errors.append(f"State '{state_name}' has no outgoing transitions and is not terminal")

        return errors

    def export_to_python(self, sm: StateMachineDefinition) -> str:
        """Export the state machine to executable Python strategy code."""
        class_name = "".join(
            word.capitalize() for word in sm.name.replace("-", " ").split()
        ) + "Strategy"

        code = f'''"""
Auto-generated State Machine Strategy: {sm.name}
Description: {sm.description}
Generated: {datetime.now(UTC).isoformat()}
Symbol: {sm.symbol} | Timeframe: {sm.timeframe}
States: {len(sm.states)} | Transitions: {len(sm.transitions)}
"""
from __future__ import annotations
import time
import logging
from typing import Any
import numpy as np

logger = logging.getLogger(__name__)

try:
    from strategies.base import BaseStrategy, Signal, SignalType, StrategyConfig
except ImportError:
    class BaseStrategy:
        def __init__(self, config=None): self.config = config
    class Signal:
        def __init__(self, **kwargs): self.__dict__.update(kwargs)
    class SignalType:
        BUY = "buy"
        SELL = "sell"
        CLOSE = "close"
    class StrategyConfig:
        def __init__(self, **kwargs): self.__dict__.update(kwargs)


class {class_name}(BaseStrategy):
    """
    {sm.description or sm.name}

    State Machine with {len(sm.states)} states and {len(sm.transitions)} transitions.
    """

    def __init__(self, config: StrategyConfig = None):
        super().__init__(config or StrategyConfig(name="{sm.name}", symbol="{sm.symbol}"))
        self._current_state = "{sm.initial_state}"
        self._state_entered_at = time.time()
        self._previous_indicators: dict[str, float] = {{}}

    @property
    def current_state(self) -> str:
        return self._current_state

    def generate_signal(self, data: dict[str, Any]) -> Signal | None:
        """
        Evaluate state machine transitions and generate signals.

        Args:
            data: Market data dict with keys: price, indicators, position, ml_signals
        """
        context = self._build_context(data)

        # Check transitions from current state (priority-ordered)
        transitions = self._get_transitions(self._current_state)

        for transition in transitions:
            if self._evaluate_transition(transition, context):
                # Execute exit actions for current state
                exit_signal = self._execute_exit_actions(self._current_state, context)

                # Transition to new state
                old_state = self._current_state
                self._current_state = transition["to"]
                self._state_entered_at = time.time()

                # Execute entry actions for new state
                entry_signal = self._execute_entry_actions(self._current_state, context)

                logger.info(
                    "State transition: %s -> %s",
                    old_state, self._current_state,
                )

                # Return the most relevant signal
                return entry_signal or exit_signal

        return None

    def _build_context(self, data: dict[str, Any]) -> dict[str, Any]:
        """Build evaluation context from market data."""
        return {{
            "price": data.get("price", data.get("close", [0])[-1] if isinstance(data.get("close"), list) else 0),
            "indicators": data.get("indicators", {{}}),
            "position": data.get("position", {{"status": "flat"}}),
            "ml_signals": data.get("ml_signals", {{}}),
            "state_entered_at": self._state_entered_at,
            "previous_indicators": self._previous_indicators,
        }}

    def _get_transitions(self, state_name: str) -> list[dict]:
        """Get all transitions from the given state, sorted by priority."""
        transitions = [t for t in self._TRANSITIONS if t["from"] == state_name]
        return sorted(transitions, key=lambda t: t.get("priority", 0), reverse=True)

    def _evaluate_transition(self, transition: dict, context: dict) -> bool:
        """Evaluate all conditions for a transition."""
        conditions = transition.get("conditions", [])
        logic = transition.get("logic", "AND")

        if not conditions:
            return False

        results = [self._evaluate_condition(c, context) for c in conditions]

        if logic == "AND":
            return all(results)
        return any(results)

    def _evaluate_condition(self, condition: dict, context: dict) -> bool:
        """Evaluate a single condition."""
        cond_type = condition.get("type", "")

        if cond_type == "indicator":
            return self._eval_indicator(condition, context)
        elif cond_type == "price":
            return self._eval_price(condition, context)
        elif cond_type == "position":
            return self._eval_position(condition, context)
        elif cond_type == "ml_signal":
            return self._eval_ml_signal(condition, context)
        elif cond_type == "dwell_time":
            return self._eval_dwell_time(condition, context)
        elif cond_type == "time":
            return self._eval_time(condition, context)

        return False

    def _eval_indicator(self, condition: dict, context: dict) -> bool:
        indicators = context.get("indicators", {{}})
        name = condition.get("name", "")
        operator = condition.get("operator", ">")
        value = float(condition.get("value", 0))
        current = indicators.get(name)
        if current is None:
            return False
        return self._compare(float(current), operator, value)

    def _eval_price(self, condition: dict, context: dict) -> bool:
        price = float(context.get("price", 0))
        operator = condition.get("operator", ">")
        value = float(condition.get("value", 0))
        return self._compare(price, operator, value)

    def _eval_position(self, condition: dict, context: dict) -> bool:
        position = context.get("position", {{}})
        expected = condition.get("status", "")
        return position.get("status", "flat") == expected

    def _eval_ml_signal(self, condition: dict, context: dict) -> bool:
        ml_signals = context.get("ml_signals", {{}})
        model = condition.get("model", "")
        operator = condition.get("operator", ">")
        threshold = float(condition.get("threshold", 0.5))
        signal_val = ml_signals.get(model)
        if signal_val is None:
            return False
        return self._compare(float(signal_val), operator, threshold)

    def _eval_dwell_time(self, condition: dict, context: dict) -> bool:
        entered_at = context.get("state_entered_at", time.time())
        max_seconds = float(condition.get("max_seconds", 3600))
        return (time.time() - entered_at) > max_seconds

    def _eval_time(self, condition: dict, context: dict) -> bool:
        import datetime as dt
        now = dt.datetime.now(dt.timezone.utc)
        hour = condition.get("hour")
        if hour is not None:
            return now.hour == int(hour)
        return False

    def _compare(self, left: float, operator: str, right: float) -> bool:
        if operator == ">": return left > right
        elif operator == ">=": return left >= right
        elif operator == "<": return left < right
        elif operator == "<=": return left <= right
        elif operator == "==": return abs(left - right) < 1e-10
        elif operator == "!=": return abs(left - right) >= 1e-10
        return False

    def _execute_entry_actions(self, state_name: str, context: dict) -> Signal | None:
        """Execute entry actions for a state and return any generated signal."""
        state_def = self._STATES.get(state_name, {{}})
        actions = state_def.get("entry_actions", [])

        for action in actions:
            action_type = action.get("type", "")
            params = action.get("params", {{}})

            if action_type == "place_order":
                side = params.get("side", "buy")
                return Signal(
                    symbol="{sm.symbol}",
                    action=side,
                    strength=0.8,
                    strategy="{sm.name}",
                    entry_price=float(context.get("price", 0)),
                    stop_loss=float(params.get("stop_loss", 0)),
                    take_profit=float(params.get("take_profit", 0)),
                    timeframe="{sm.timeframe}",
                    metadata={{"state": state_name, "source": "state_machine"}},
                )
            elif action_type == "close_position":
                return Signal(
                    symbol="{sm.symbol}",
                    action="close",
                    strength=1.0,
                    strategy="{sm.name}",
                    entry_price=float(context.get("price", 0)),
                    stop_loss=0,
                    take_profit=0,
                    timeframe="{sm.timeframe}",
                    metadata={{"state": state_name, "source": "state_machine"}},
                )

        return None

    def _execute_exit_actions(self, state_name: str, context: dict) -> Signal | None:
        """Execute exit actions for a state."""
        state_def = self._STATES.get(state_name, {{}})
        actions = state_def.get("exit_actions", [])
        # Exit actions typically don't generate signals
        for action in actions:
            logger.debug("Exit action: %s from state %s", action.get("type"), state_name)
        return None

    # ── State Machine Definition (auto-generated) ─────────────────────────────

    _STATES = {{
'''

        # Add state definitions
        for state_name, state in sm.states.items():
            code += f'        "{state_name}": {{\n'
            code += f'            "is_initial": {state.is_initial},\n'
            code += f'            "is_terminal": {state.is_terminal},\n'
            code += f'            "entry_actions": {[a.to_dict() for a in state.entry_actions]},\n'
            code += f'            "exit_actions": {[a.to_dict() for a in state.exit_actions]},\n'
            code += f'            "max_dwell_seconds": {state.max_dwell_seconds},\n'
            code += f'        }},\n'

        code += '    }\n\n'
        code += '    _TRANSITIONS = [\n'

        # Add transition definitions
        for t in sm.transitions:
            code += f'        {{\n'
            code += f'            "from": "{t.from_state}",\n'
            code += f'            "to": "{t.to_state}",\n'
            code += f'            "conditions": {[c.to_dict() for c in t.conditions]},\n'
            code += f'            "logic": "{t.condition_logic}",\n'
            code += f'            "priority": {t.priority},\n'
            code += f'        }},\n'

        code += '    ]\n'

        return code

    def get_machine(self, machine_id: str) -> StateMachineDefinition | None:
        """Get a state machine by ID."""
        return self._machines.get(machine_id)

    def list_machines(self) -> list[dict[str, Any]]:
        """List all state machines."""
        return [sm.to_dict() for sm in self._machines.values()]


# ── Module-level singleton ────────────────────────────────────────────────────

_builder: StateMachineBuilder | None = None


def get_state_machine_builder() -> StateMachineBuilder:
    """Return the module-level StateMachineBuilder singleton."""
    global _builder
    if _builder is None:
        _builder = StateMachineBuilder()
    return _builder
