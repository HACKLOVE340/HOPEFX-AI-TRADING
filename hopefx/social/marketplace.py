"""hopefx.social.marketplace — shim for tests"""
from dataclasses import dataclass, field
from typing import Optional, Dict, Any

from monetization.marketplace import (
    StrategyMarketplace,
    StrategyCategory,
    StrategyLicenseType,
    StrategyStatus,
    PurchaseStatus,
    StrategyPerformance,
)


@dataclass
class StrategyListing:
    """Test-friendly listing with simple field names."""
    id: str = ""
    name: str = ""
    description: str = ""
    price: float = 0.0
    creator_id: str = ""
    strategy_code: str = ""
    performance_stats: Dict[str, Any] = field(default_factory=dict)
    category: str = "trend_following"
    tags: list = field(default_factory=list)


__all__ = [
    "StrategyMarketplace", "StrategyListing", "StrategyCategory",
    "StrategyLicenseType", "StrategyStatus", "PurchaseStatus", "StrategyPerformance",
]
