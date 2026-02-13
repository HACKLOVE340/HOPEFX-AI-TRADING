"""
Strategy Marketplace

Allows users to publish and subscribe to trading strategies.
"""

from typing import Dict, List, Optional
from decimal import Decimal
from datetime import datetime


class Strategy:
    """Represents a published trading strategy"""
    def __init__(self, user_id: str, name: str, description: str):
        self.strategy_id = f"STR_{user_id}_{name[:10]}"
        self.user_id = user_id
        self.name = name
        self.description = description
        self.subscription_fee = Decimal('0.0')
        self.performance_fee = Decimal('0.0')
        self.is_public = True
        self.subscribers_count = 0
        self.created_at = datetime.utcnow()


class StrategyMarketplace:
    """Manages strategy publishing and subscriptions"""

    def __init__(self):
        self.strategies: Dict[str, Strategy] = {}
        self.subscriptions: Dict[str, List[str]] = {}  # user_id -> strategy_ids

    def publish_strategy(
        self,
        user_id: str,
        name: str,
        description: str,
        subscription_fee: Decimal = Decimal('0.0'),
        performance_fee: Decimal = Decimal('0.0')
    ) -> Strategy:
        """Publish a new trading strategy"""
        strategy = Strategy(user_id, name, description)
        strategy.subscription_fee = subscription_fee
        strategy.performance_fee = performance_fee

        self.strategies[strategy.strategy_id] = strategy
        return strategy

    def subscribe_to_strategy(self, user_id: str, strategy_id: str) -> bool:
        """Subscribe to a strategy"""
        if strategy_id not in self.strategies:
            return False

        if user_id not in self.subscriptions:
            self.subscriptions[user_id] = []

        if strategy_id not in self.subscriptions[user_id]:
            self.subscriptions[user_id].append(strategy_id)
            self.strategies[strategy_id].subscribers_count += 1
            return True

        return False

    def get_strategies(self, public_only: bool = True) -> List[Strategy]:
        """Get all available strategies"""
        strategies = list(self.strategies.values())
        if public_only:
            strategies = [s for s in strategies if s.is_public]
        return strategies

    def get_user_subscriptions(self, user_id: str) -> List[Strategy]:
        """Get strategies a user is subscribed to"""
        strategy_ids = self.subscriptions.get(user_id, [])
        return [self.strategies[sid] for sid in strategy_ids if sid in self.strategies]
