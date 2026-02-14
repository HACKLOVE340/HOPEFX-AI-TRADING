"""
Pricing Tier Definitions and Management

This module defines the pricing tiers for the HOPEFX AI Trading platform:
- Starter: $1,800/month (0.5% commission)
- Professional: $4,500/month (0.3% commission)
- Enterprise: $7,500/month (0.2% commission)
- Elite: $10,000/month (0.1% commission)
"""

from enum import Enum
from typing import Dict, List, Optional
from dataclasses import dataclass
from decimal import Decimal


class SubscriptionTier(str, Enum):
    """Subscription tier enumeration"""
    STARTER = "starter"
    PROFESSIONAL = "professional"
    ENTERPRISE = "enterprise"
    ELITE = "elite"


@dataclass
class TierFeatures:
    """Features available in a tier"""
    max_strategies: int
    max_brokers: int
    ml_features: bool
    priority_support: bool
    api_access: bool
    custom_development: bool
    dedicated_support: bool
    backtesting_unlimited: bool
    pattern_recognition: bool
    news_integration: bool


class PricingTier:
    """Pricing tier definition"""

    def __init__(
        self,
        tier: SubscriptionTier,
        name: str,
        monthly_price: Decimal,
        commission_rate: Decimal,
        features: TierFeatures
    ):
        self.tier = tier
        self.name = name
        self.monthly_price = monthly_price
        self.commission_rate = commission_rate
        self.features = features

    def to_dict(self) -> Dict:
        """Convert to dictionary"""
        return {
            'tier': self.tier.value,
            'name': self.name,
            'monthly_price': float(self.monthly_price),
            'commission_rate': float(self.commission_rate),
            'features': {
                'max_strategies': self.features.max_strategies,
                'max_brokers': self.features.max_brokers,
                'ml_features': self.features.ml_features,
                'priority_support': self.features.priority_support,
                'api_access': self.features.api_access,
                'custom_development': self.features.custom_development,
                'dedicated_support': self.features.dedicated_support,
                'backtesting_unlimited': self.features.backtesting_unlimited,
                'pattern_recognition': self.features.pattern_recognition,
                'news_integration': self.features.news_integration,
            }
        }


class PricingManager:
    """Manage pricing tiers and features"""

    def __init__(self):
        self._tiers = self._initialize_tiers()

    def _initialize_tiers(self) -> Dict[SubscriptionTier, PricingTier]:
        """Initialize pricing tiers"""
        return {
            SubscriptionTier.STARTER: PricingTier(
                tier=SubscriptionTier.STARTER,
                name="Starter",
                monthly_price=Decimal("1800.00"),
                commission_rate=Decimal("0.005"),  # 0.5%
                features=TierFeatures(
                    max_strategies=3,
                    max_brokers=1,
                    ml_features=False,
                    priority_support=False,
                    api_access=False,
                    custom_development=False,
                    dedicated_support=False,
                    backtesting_unlimited=False,
                    pattern_recognition=False,
                    news_integration=False
                )
            ),
            SubscriptionTier.PROFESSIONAL: PricingTier(
                tier=SubscriptionTier.PROFESSIONAL,
                name="Professional",
                monthly_price=Decimal("4500.00"),
                commission_rate=Decimal("0.003"),  # 0.3%
                features=TierFeatures(
                    max_strategies=7,
                    max_brokers=3,
                    ml_features=True,
                    priority_support=True,
                    api_access=True,
                    custom_development=False,
                    dedicated_support=False,
                    backtesting_unlimited=True,
                    pattern_recognition=True,
                    news_integration=False
                )
            ),
            SubscriptionTier.ENTERPRISE: PricingTier(
                tier=SubscriptionTier.ENTERPRISE,
                name="Enterprise",
                monthly_price=Decimal("7500.00"),
                commission_rate=Decimal("0.002"),  # 0.2%
                features=TierFeatures(
                    max_strategies=999,
                    max_brokers=999,
                    ml_features=True,
                    priority_support=True,
                    api_access=True,
                    custom_development=False,
                    dedicated_support=False,
                    backtesting_unlimited=True,
                    pattern_recognition=True,
                    news_integration=True
                )
            ),
            SubscriptionTier.ELITE: PricingTier(
                tier=SubscriptionTier.ELITE,
                name="Elite",
                monthly_price=Decimal("10000.00"),
                commission_rate=Decimal("0.001"),  # 0.1%
                features=TierFeatures(
                    max_strategies=999,
                    max_brokers=999,
                    ml_features=True,
                    priority_support=True,
                    api_access=True,
                    custom_development=True,
                    dedicated_support=True,
                    backtesting_unlimited=True,
                    pattern_recognition=True,
                    news_integration=True
                )
            )
        }

    def get_tier(self, tier: SubscriptionTier) -> Optional[PricingTier]:
        """Get pricing tier by tier enum"""
        return self._tiers.get(tier)

    def get_tier_by_name(self, tier_name: str) -> Optional[PricingTier]:
        """Get pricing tier by name"""
        try:
            tier_enum = SubscriptionTier(tier_name.lower())
            return self._tiers.get(tier_enum)
        except ValueError:
            return None

    def get_all_tiers(self) -> List[PricingTier]:
        """Get all pricing tiers"""
        return list(self._tiers.values())

    def get_tier_price(self, tier: SubscriptionTier) -> Decimal:
        """Get monthly price for a tier"""
        pricing_tier = self.get_tier(tier)
        return pricing_tier.monthly_price if pricing_tier else Decimal("0.00")

    def get_commission_rate(self, tier: SubscriptionTier) -> Decimal:
        """Get commission rate for a tier"""
        pricing_tier = self.get_tier(tier)
        return pricing_tier.commission_rate if pricing_tier else Decimal("0.00")

    def calculate_commission(self, tier: SubscriptionTier, trade_amount: Decimal) -> Decimal:
        """Calculate commission for a trade"""
        rate = self.get_commission_rate(tier)
        return trade_amount * rate

    def has_feature(self, tier: SubscriptionTier, feature_name: str) -> bool:
        """Check if tier has a specific feature"""
        pricing_tier = self.get_tier(tier)
        if not pricing_tier:
            return False
        return getattr(pricing_tier.features, feature_name, False)

    def compare_tiers(self, tier1: SubscriptionTier, tier2: SubscriptionTier) -> Dict:
        """Compare two pricing tiers"""
        t1 = self.get_tier(tier1)
        t2 = self.get_tier(tier2)

        if not t1 or not t2:
            return {}

        return {
            'tier1': t1.to_dict(),
            'tier2': t2.to_dict(),
            'price_difference': float(t1.monthly_price - t2.monthly_price),
            'commission_difference': float(t1.commission_rate - t2.commission_rate)
        }

    def get_upgrade_path(self, current_tier: SubscriptionTier) -> List[SubscriptionTier]:
        """Get available upgrade options"""
        tier_order = [
            SubscriptionTier.STARTER,
            SubscriptionTier.PROFESSIONAL,
            SubscriptionTier.ENTERPRISE,
            SubscriptionTier.ELITE
        ]

        try:
            current_index = tier_order.index(current_tier)
            return tier_order[current_index + 1:]
        except (ValueError, IndexError):
            return []

    def get_downgrade_path(self, current_tier: SubscriptionTier) -> List[SubscriptionTier]:
        """Get available downgrade options"""
        tier_order = [
            SubscriptionTier.STARTER,
            SubscriptionTier.PROFESSIONAL,
            SubscriptionTier.ENTERPRISE,
            SubscriptionTier.ELITE
        ]

        try:
            current_index = tier_order.index(current_tier)
            return tier_order[:current_index]
        except ValueError:
            return []


# Global pricing manager instance
pricing_manager = PricingManager()
