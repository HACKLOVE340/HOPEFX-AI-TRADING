"""
Strategy Marketplace

This module handles:
- Strategy listing and discovery
- Strategy purchases and licenses
- Strategy ratings and reviews
- Revenue sharing with strategy creators
- Marketplace analytics
"""

import logging
from datetime import datetime
from decimal import Decimal
from typing import Optional, Dict, List, Any
from enum import Enum
from dataclasses import dataclass

from .pricing import SubscriptionTier

logger = logging.getLogger(__name__)


class StrategyCategory(str, Enum):
    """Strategy categories"""
    SCALPING = "scalping"
    DAY_TRADING = "day_trading"
    SWING_TRADING = "swing_trading"
    POSITION_TRADING = "position_trading"
    ALGORITHMIC = "algorithmic"
    ML_BASED = "ml_based"
    ARBITRAGE = "arbitrage"
    MARKET_MAKING = "market_making"


class StrategyStatus(str, Enum):
    """Strategy listing status"""
    DRAFT = "draft"
    PENDING_REVIEW = "pending_review"
    APPROVED = "approved"
    REJECTED = "rejected"
    SUSPENDED = "suspended"
    ARCHIVED = "archived"


class StrategyLicenseType(str, Enum):
    """Strategy license types"""
    PURCHASE = "purchase"        # One-time purchase
    SUBSCRIPTION = "subscription"  # Monthly subscription
    FREE = "free"                # Free strategy


class PurchaseStatus(str, Enum):
    """Purchase status"""
    PENDING = "pending"
    COMPLETED = "completed"
    REFUNDED = "refunded"
    EXPIRED = "expired"


# Revenue sharing percentages
CREATOR_REVENUE_SHARE = Decimal("0.70")  # 70% to creator
PLATFORM_REVENUE_SHARE = Decimal("0.30")  # 30% to platform


@dataclass
class StrategyPerformance:
    """Strategy performance metrics"""
    total_return: float
    monthly_return: float
    max_drawdown: float
    sharpe_ratio: float
    win_rate: float
    total_trades: int
    profit_factor: float
    avg_trade_duration: str
    backtest_period: str


class MarketplaceStrategy:
    """Strategy listing in marketplace"""

    def __init__(
        self,
        strategy_id: str,
        creator_id: str,
        name: str,
        description: str,
        category: StrategyCategory,
        price: Decimal,
        license_type: StrategyLicenseType = StrategyLicenseType.PURCHASE,
        min_tier: SubscriptionTier = SubscriptionTier.STARTER,
        tags: Optional[List[str]] = None
    ):
        self.strategy_id = strategy_id
        self.creator_id = creator_id
        self.name = name
        self.description = description
        self.category = category
        self.price = price
        self.license_type = license_type
        self.min_tier = min_tier
        self.tags = tags or []
        self.status = StrategyStatus.DRAFT
        self.created_at = datetime.utcnow()
        self.updated_at = datetime.utcnow()
        self.published_at: Optional[datetime] = None
        
        # Performance metrics
        self.performance: Optional[StrategyPerformance] = None
        
        # Statistics
        self.total_purchases = 0
        self.total_revenue = Decimal("0.00")
        self.avg_rating: Optional[float] = None
        self.total_ratings = 0
        self.total_reviews = 0
        
        # Strategy files/config
        self.strategy_config: Dict[str, Any] = {}
        self.documentation: str = ""
        self.version: str = "1.0.0"

    def set_performance(self, performance: StrategyPerformance) -> None:
        """Set strategy performance metrics"""
        self.performance = performance
        self.updated_at = datetime.utcnow()

    def submit_for_review(self) -> bool:
        """Submit strategy for review"""
        if self.status != StrategyStatus.DRAFT:
            return False
        
        self.status = StrategyStatus.PENDING_REVIEW
        self.updated_at = datetime.utcnow()
        logger.info(f"Strategy {self.strategy_id} submitted for review")
        return True

    def approve(self) -> None:
        """Approve strategy for marketplace"""
        self.status = StrategyStatus.APPROVED
        self.published_at = datetime.utcnow()
        self.updated_at = datetime.utcnow()
        logger.info(f"Strategy {self.strategy_id} approved")

    def reject(self, reason: str) -> None:
        """Reject strategy"""
        self.status = StrategyStatus.REJECTED
        self.updated_at = datetime.utcnow()
        logger.info(f"Strategy {self.strategy_id} rejected: {reason}")

    def suspend(self) -> None:
        """Suspend strategy listing"""
        self.status = StrategyStatus.SUSPENDED
        self.updated_at = datetime.utcnow()
        logger.info(f"Strategy {self.strategy_id} suspended")

    def archive(self) -> None:
        """Archive strategy"""
        self.status = StrategyStatus.ARCHIVED
        self.updated_at = datetime.utcnow()
        logger.info(f"Strategy {self.strategy_id} archived")

    def is_available(self) -> bool:
        """Check if strategy is available for purchase"""
        return self.status == StrategyStatus.APPROVED

    def record_purchase(self, amount: Decimal) -> None:
        """Record a purchase"""
        self.total_purchases += 1
        self.total_revenue += amount
        self.updated_at = datetime.utcnow()

    def add_rating(self, rating: float) -> None:
        """Add a rating (1-5 scale)"""
        if self.avg_rating is None:
            self.avg_rating = rating
        else:
            total = self.avg_rating * self.total_ratings + rating
            self.total_ratings += 1
            self.avg_rating = total / self.total_ratings
        
        self.total_ratings += 1
        self.updated_at = datetime.utcnow()

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary"""
        return {
            'strategy_id': self.strategy_id,
            'creator_id': self.creator_id,
            'name': self.name,
            'description': self.description,
            'category': self.category.value,
            'price': float(self.price),
            'license_type': self.license_type.value,
            'min_tier': self.min_tier.value,
            'tags': self.tags,
            'status': self.status.value,
            'version': self.version,
            'performance': {
                'total_return': self.performance.total_return,
                'monthly_return': self.performance.monthly_return,
                'max_drawdown': self.performance.max_drawdown,
                'sharpe_ratio': self.performance.sharpe_ratio,
                'win_rate': self.performance.win_rate,
                'total_trades': self.performance.total_trades,
                'profit_factor': self.performance.profit_factor,
            } if self.performance else None,
            'total_purchases': self.total_purchases,
            'total_revenue': float(self.total_revenue),
            'avg_rating': self.avg_rating,
            'total_ratings': self.total_ratings,
            'total_reviews': self.total_reviews,
            'created_at': self.created_at.isoformat(),
            'published_at': self.published_at.isoformat() if self.published_at else None
        }


class StrategyPurchase:
    """Strategy purchase record"""

    def __init__(
        self,
        purchase_id: str,
        strategy_id: str,
        buyer_id: str,
        creator_id: str,
        amount: Decimal,
        license_type: StrategyLicenseType
    ):
        self.purchase_id = purchase_id
        self.strategy_id = strategy_id
        self.buyer_id = buyer_id
        self.creator_id = creator_id
        self.amount = amount
        self.license_type = license_type
        self.status = PurchaseStatus.PENDING
        self.created_at = datetime.utcnow()
        self.completed_at: Optional[datetime] = None
        self.expires_at: Optional[datetime] = None
        
        # Revenue split
        self.creator_share = amount * CREATOR_REVENUE_SHARE
        self.platform_share = amount * PLATFORM_REVENUE_SHARE

    def complete(self) -> None:
        """Complete purchase"""
        self.status = PurchaseStatus.COMPLETED
        self.completed_at = datetime.utcnow()
        logger.info(f"Purchase {self.purchase_id} completed")

    def refund(self) -> None:
        """Refund purchase"""
        self.status = PurchaseStatus.REFUNDED
        logger.info(f"Purchase {self.purchase_id} refunded")

    def is_valid(self) -> bool:
        """Check if license is valid"""
        if self.status != PurchaseStatus.COMPLETED:
            return False
        if self.expires_at and datetime.utcnow() > self.expires_at:
            return False
        return True

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary"""
        return {
            'purchase_id': self.purchase_id,
            'strategy_id': self.strategy_id,
            'buyer_id': self.buyer_id,
            'amount': float(self.amount),
            'license_type': self.license_type.value,
            'status': self.status.value,
            'creator_share': float(self.creator_share),
            'platform_share': float(self.platform_share),
            'created_at': self.created_at.isoformat(),
            'completed_at': self.completed_at.isoformat() if self.completed_at else None,
            'expires_at': self.expires_at.isoformat() if self.expires_at else None,
            'is_valid': self.is_valid()
        }


class StrategyReview:
    """Strategy review/rating"""

    def __init__(
        self,
        review_id: str,
        strategy_id: str,
        user_id: str,
        rating: int,
        title: str,
        content: str
    ):
        self.review_id = review_id
        self.strategy_id = strategy_id
        self.user_id = user_id
        self.rating = min(max(rating, 1), 5)  # 1-5 scale
        self.title = title
        self.content = content
        self.created_at = datetime.utcnow()
        self.updated_at = datetime.utcnow()
        self.helpful_votes = 0
        self.verified_purchase = False

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary"""
        return {
            'review_id': self.review_id,
            'strategy_id': self.strategy_id,
            'user_id': self.user_id,
            'rating': self.rating,
            'title': self.title,
            'content': self.content,
            'helpful_votes': self.helpful_votes,
            'verified_purchase': self.verified_purchase,
            'created_at': self.created_at.isoformat()
        }


class StrategyMarketplace:
    """Strategy marketplace manager"""

    def __init__(self):
        self._strategies: Dict[str, MarketplaceStrategy] = {}
        self._purchases: Dict[str, StrategyPurchase] = {}
        self._reviews: Dict[str, StrategyReview] = {}
        self._user_purchases: Dict[str, List[str]] = {}  # user_id -> [purchase_ids]
        self._creator_strategies: Dict[str, List[str]] = {}  # creator_id -> [strategy_ids]

    def list_strategy(
        self,
        creator_id: str,
        name: str,
        description: str,
        category: StrategyCategory,
        price: Decimal,
        license_type: StrategyLicenseType = StrategyLicenseType.PURCHASE,
        min_tier: SubscriptionTier = SubscriptionTier.STARTER,
        tags: Optional[List[str]] = None,
        strategy_config: Optional[Dict[str, Any]] = None
    ) -> MarketplaceStrategy:
        """List a new strategy in marketplace"""
        import uuid

        strategy_id = f"STR-{uuid.uuid4().hex[:12].upper()}"
        
        strategy = MarketplaceStrategy(
            strategy_id=strategy_id,
            creator_id=creator_id,
            name=name,
            description=description,
            category=category,
            price=price,
            license_type=license_type,
            min_tier=min_tier,
            tags=tags
        )
        
        if strategy_config:
            strategy.strategy_config = strategy_config

        self._strategies[strategy_id] = strategy
        
        if creator_id not in self._creator_strategies:
            self._creator_strategies[creator_id] = []
        self._creator_strategies[creator_id].append(strategy_id)

        logger.info(f"Strategy {strategy_id} listed by creator {creator_id}")
        return strategy

    def get_strategy(self, strategy_id: str) -> Optional[MarketplaceStrategy]:
        """Get strategy by ID"""
        return self._strategies.get(strategy_id)

    def search_strategies(
        self,
        query: Optional[str] = None,
        category: Optional[StrategyCategory] = None,
        min_price: Optional[Decimal] = None,
        max_price: Optional[Decimal] = None,
        min_rating: Optional[float] = None,
        min_tier: Optional[SubscriptionTier] = None,
        tags: Optional[List[str]] = None,
        sort_by: str = "popular",
        limit: int = 20,
        offset: int = 0
    ) -> List[MarketplaceStrategy]:
        """Search and filter strategies"""
        results = [
            s for s in self._strategies.values()
            if s.is_available()
        ]

        # Apply filters
        if query:
            query_lower = query.lower()
            results = [
                s for s in results
                if query_lower in s.name.lower() or query_lower in s.description.lower()
            ]

        if category:
            results = [s for s in results if s.category == category]

        if min_price is not None:
            results = [s for s in results if s.price >= min_price]

        if max_price is not None:
            results = [s for s in results if s.price <= max_price]

        if min_rating is not None:
            results = [s for s in results if s.avg_rating and s.avg_rating >= min_rating]

        if min_tier:
            tier_order = list(SubscriptionTier)
            min_tier_idx = tier_order.index(min_tier)
            results = [
                s for s in results
                if tier_order.index(s.min_tier) <= min_tier_idx
            ]

        if tags:
            results = [
                s for s in results
                if any(t in s.tags for t in tags)
            ]

        # Sort results
        if sort_by == "popular":
            results.sort(key=lambda s: s.total_purchases, reverse=True)
        elif sort_by == "rating":
            results.sort(key=lambda s: s.avg_rating or 0, reverse=True)
        elif sort_by == "newest":
            results.sort(key=lambda s: s.published_at or s.created_at, reverse=True)
        elif sort_by == "price_low":
            results.sort(key=lambda s: s.price)
        elif sort_by == "price_high":
            results.sort(key=lambda s: s.price, reverse=True)

        return results[offset:offset + limit]

    def purchase_strategy(
        self,
        buyer_id: str,
        strategy_id: str
    ) -> Optional[StrategyPurchase]:
        """Purchase a strategy"""
        import uuid

        strategy = self.get_strategy(strategy_id)
        if not strategy or not strategy.is_available():
            logger.warning(f"Strategy {strategy_id} not available for purchase")
            return None

        # Check if already purchased
        if self.has_strategy_license(buyer_id, strategy_id):
            logger.info(f"User {buyer_id} already owns strategy {strategy_id}")
            return None

        purchase_id = f"PUR-{uuid.uuid4().hex[:12].upper()}"
        
        purchase = StrategyPurchase(
            purchase_id=purchase_id,
            strategy_id=strategy_id,
            buyer_id=buyer_id,
            creator_id=strategy.creator_id,
            amount=strategy.price,
            license_type=strategy.license_type
        )

        self._purchases[purchase_id] = purchase
        
        if buyer_id not in self._user_purchases:
            self._user_purchases[buyer_id] = []
        self._user_purchases[buyer_id].append(purchase_id)

        logger.info(f"Purchase {purchase_id} created for strategy {strategy_id}")
        return purchase

    def complete_purchase(self, purchase_id: str) -> bool:
        """Complete a purchase after payment"""
        purchase = self._purchases.get(purchase_id)
        if not purchase:
            return False

        purchase.complete()
        
        # Update strategy stats
        strategy = self.get_strategy(purchase.strategy_id)
        if strategy:
            strategy.record_purchase(purchase.amount)

        return True

    def refund_purchase(self, purchase_id: str) -> bool:
        """Refund a purchase"""
        purchase = self._purchases.get(purchase_id)
        if not purchase:
            return False

        purchase.refund()
        return True

    def has_strategy_license(self, user_id: str, strategy_id: str) -> bool:
        """Check if user has valid license for strategy"""
        purchase_ids = self._user_purchases.get(user_id, [])
        for pid in purchase_ids:
            purchase = self._purchases.get(pid)
            if purchase and purchase.strategy_id == strategy_id and purchase.is_valid():
                return True
        return False

    def get_user_purchases(self, user_id: str) -> List[StrategyPurchase]:
        """Get all purchases for a user"""
        purchase_ids = self._user_purchases.get(user_id, [])
        return [
            self._purchases[pid] for pid in purchase_ids
            if pid in self._purchases
        ]

    def get_creator_strategies(self, creator_id: str) -> List[MarketplaceStrategy]:
        """Get all strategies by a creator"""
        strategy_ids = self._creator_strategies.get(creator_id, [])
        return [
            self._strategies[sid] for sid in strategy_ids
            if sid in self._strategies
        ]

    def add_review(
        self,
        user_id: str,
        strategy_id: str,
        rating: int,
        title: str,
        content: str
    ) -> Optional[StrategyReview]:
        """Add a review for a strategy"""
        import uuid

        strategy = self.get_strategy(strategy_id)
        if not strategy:
            return None

        # Verify purchase
        verified = self.has_strategy_license(user_id, strategy_id)

        review_id = f"REV-{uuid.uuid4().hex[:12].upper()}"
        
        review = StrategyReview(
            review_id=review_id,
            strategy_id=strategy_id,
            user_id=user_id,
            rating=rating,
            title=title,
            content=content
        )
        review.verified_purchase = verified

        self._reviews[review_id] = review
        
        # Update strategy rating
        strategy.add_rating(rating)
        strategy.total_reviews += 1

        logger.info(f"Review {review_id} added for strategy {strategy_id}")
        return review

    def get_strategy_reviews(
        self,
        strategy_id: str,
        limit: int = 10
    ) -> List[StrategyReview]:
        """Get reviews for a strategy"""
        reviews = [
            r for r in self._reviews.values()
            if r.strategy_id == strategy_id
        ]
        reviews.sort(key=lambda r: r.helpful_votes, reverse=True)
        return reviews[:limit]

    def get_creator_earnings(
        self,
        creator_id: str,
        include_pending: bool = False
    ) -> Dict[str, Any]:
        """Get earnings summary for a creator"""
        strategies = self.get_creator_strategies(creator_id)
        
        total_revenue = Decimal("0.00")
        total_purchases = 0
        pending_earnings = Decimal("0.00")
        
        for strategy in strategies:
            total_revenue += strategy.total_revenue * CREATOR_REVENUE_SHARE
            total_purchases += strategy.total_purchases

        # Calculate pending earnings from uncompleted purchases
        if include_pending:
            for purchase in self._purchases.values():
                if (purchase.creator_id == creator_id and 
                    purchase.status == PurchaseStatus.PENDING):
                    pending_earnings += purchase.creator_share

        return {
            'creator_id': creator_id,
            'total_strategies': len(strategies),
            'total_purchases': total_purchases,
            'total_revenue': float(total_revenue),
            'pending_earnings': float(pending_earnings) if include_pending else None,
            'revenue_share_rate': float(CREATOR_REVENUE_SHARE)
        }

    def get_featured_strategies(self, limit: int = 10) -> List[MarketplaceStrategy]:
        """Get featured/top strategies"""
        available = [s for s in self._strategies.values() if s.is_available()]
        
        # Score based on purchases, ratings, and performance
        def score(s: MarketplaceStrategy) -> float:
            rating_score = (s.avg_rating or 0) * 20
            purchase_score = min(s.total_purchases * 2, 100)
            performance_score = 0
            if s.performance:
                performance_score = min(s.performance.total_return, 100)
            return rating_score + purchase_score + performance_score
        
        available.sort(key=score, reverse=True)
        return available[:limit]

    def get_marketplace_stats(self) -> Dict[str, Any]:
        """Get overall marketplace statistics"""
        strategies = list(self._strategies.values())
        purchases = list(self._purchases.values())
        
        total_volume = sum(
            p.amount for p in purchases 
            if p.status == PurchaseStatus.COMPLETED
        )
        platform_revenue = total_volume * PLATFORM_REVENUE_SHARE
        creator_earnings = total_volume * CREATOR_REVENUE_SHARE

        return {
            'total_strategies': len(strategies),
            'approved_strategies': len([s for s in strategies if s.is_available()]),
            'pending_review': len([s for s in strategies if s.status == StrategyStatus.PENDING_REVIEW]),
            'total_purchases': len([p for p in purchases if p.status == PurchaseStatus.COMPLETED]),
            'total_volume': float(total_volume),
            'platform_revenue': float(platform_revenue),
            'creator_earnings': float(creator_earnings),
            'unique_creators': len(set(s.creator_id for s in strategies)),
            'unique_buyers': len(self._user_purchases),
            'category_breakdown': {
                cat.value: len([s for s in strategies if s.category == cat and s.is_available()])
                for cat in StrategyCategory
            }
        }

    def approve_strategy(self, strategy_id: str) -> bool:
        """Approve a strategy for marketplace"""
        strategy = self.get_strategy(strategy_id)
        if not strategy:
            return False
        strategy.approve()
        return True

    def reject_strategy(self, strategy_id: str, reason: str) -> bool:
        """Reject a strategy"""
        strategy = self.get_strategy(strategy_id)
        if not strategy:
            return False
        strategy.reject(reason)
        return True


# Global marketplace instance
strategy_marketplace = StrategyMarketplace()
