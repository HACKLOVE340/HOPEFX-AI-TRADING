# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
Strategy Marketplace

Allows users to publish, list, purchase, and subscribe to trading strategies.
"""

import ast
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
UTC = timezone.utc
from decimal import Decimal
from typing import Any


@dataclass
class StrategyListing:
    """A strategy listed on the marketplace."""

    id: str = ""
    name: str = ""
    description: str = ""
    price: float = 0.0
    creator_id: str = ""
    strategy_code: str = ""
    performance_stats: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        if not self.id:
            self.id = str(uuid.uuid4())


class Strategy:
    """Represents a published trading strategy (legacy / subscription model)."""

    def __init__(self, user_id: str, name: str, description: str):
        self.strategy_id = f"STR_{user_id}_{name[:10]}"
        self.user_id = user_id
        self.name = name
        self.description = description
        self.subscription_fee = Decimal("0.0")
        self.performance_fee = Decimal("0.0")
        self.is_public = True
        self.subscribers_count = 0
        self.created_at = datetime.now(UTC)


class StrategyMarketplace:
    """Manages strategy publishing, listing, purchasing, and subscriptions."""

    PLATFORM_FEE_PCT = 0.20  # 20% platform cut

    def __init__(self, config: dict | None = None):
        self.config = config or {}
        self.listings: dict[str, StrategyListing] = {}
        self.purchases: dict[str, list[dict]] = {}  # buyer_id -> purchases
        # Legacy subscription model
        self.strategies: dict[str, Strategy] = {}
        self.subscriptions: dict[str, list[str]] = {}  # user_id -> strategy_ids

    # ── Listing API ──────────────────────────────────────────────────────────

    def list_strategy(self, listing: StrategyListing) -> dict[str, Any]:
        """Add a strategy to the marketplace."""
        self.listings[listing.id] = listing
        return {"status": "active", "id": listing.id}

    def get_all_listings(self) -> dict[str, StrategyListing]:
        """Return all active listings."""
        return self.listings

    # ── Purchase API ─────────────────────────────────────────────────────────

    def purchase_strategy(
        self,
        strategy_id: str,
        buyer_id: str,
        payment_method: str = "wallet",
    ) -> dict[str, Any]:
        """Purchase a listed strategy and return receipt with revenue split."""
        if strategy_id not in self.listings:
            raise ValueError(f"Strategy {strategy_id!r} not found")

        listing = self.listings[strategy_id]
        price = listing.price
        platform_fee = round(price * self.PLATFORM_FEE_PCT, 2)
        creator_payout = round(price - platform_fee, 2)
        license_key = str(uuid.uuid4())

        receipt = {
            "status": "completed",
            "strategy_id": strategy_id,
            "buyer_id": buyer_id,
            "payment_method": payment_method,
            "price": price,
            "platform_fee": platform_fee,
            "creator_payout": creator_payout,
            "license_key": license_key,
            "purchased_at": datetime.now(UTC).isoformat(),
        }

        self.purchases.setdefault(buyer_id, []).append(receipt)
        return receipt

    # ── Validation API ───────────────────────────────────────────────────────

    def validate_strategy(self, code: str) -> bool:
        """Parse strategy code for syntax errors. Raises ValueError on failure."""
        try:
            ast.parse(code)
        except SyntaxError as exc:
            raise ValueError(f"Invalid strategy code: {exc}") from exc
        return True

    # ── Legacy subscription API ───────────────────────────────────────────────

    def publish_strategy(
        self,
        user_id: str,
        name: str,
        description: str,
        subscription_fee: Decimal = Decimal("0.0"),
        performance_fee: Decimal = Decimal("0.0"),
    ) -> Strategy:
        """Publish a new trading strategy (subscription model)."""
        strategy = Strategy(user_id, name, description)
        strategy.subscription_fee = subscription_fee
        strategy.performance_fee = performance_fee
        self.strategies[strategy.strategy_id] = strategy
        return strategy

    def subscribe_to_strategy(self, user_id: str, strategy_id: str) -> bool:
        """Subscribe to a strategy."""
        if strategy_id not in self.strategies:
            return False
        if user_id not in self.subscriptions:
            self.subscriptions[user_id] = []
        if strategy_id not in self.subscriptions[user_id]:
            self.subscriptions[user_id].append(strategy_id)
            self.strategies[strategy_id].subscribers_count += 1
            return True
        return False

    def get_strategies(self, public_only: bool = True) -> list[Strategy]:
        """Get all available strategies."""
        strategies = list(self.strategies.values())
        if public_only:
            strategies = [s for s in strategies if s.is_public]
        return strategies

    def get_user_subscriptions(self, user_id: str) -> list[Strategy]:
        """Get strategies a user is subscribed to."""
        strategy_ids = self.subscriptions.get(user_id, [])
        return [self.strategies[sid] for sid in strategy_ids if sid in self.strategies]
