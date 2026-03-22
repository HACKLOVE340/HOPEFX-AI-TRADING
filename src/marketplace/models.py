"""
Marketplace database models for strategy monetization.
"""
from datetime import datetime
from decimal import Decimal
from typing import Optional, List
from sqlmodel import SQLModel, Field, Relationship
import uuid


class MarketplaceStrategy(SQLModel, table=True):
    """Strategy listing in marketplace."""
    __tablename__ = "marketplace_strategies"
    
    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    
    # Strategy info
    name: str = Field(index=True)
    description: str
    owner_id: str = Field(index=True)
    category: str = "XAUUSD"  # XAUUSD, Forex, Crypto, etc.
    
    # Pricing
    price_monthly: Decimal = Field(decimal_places=2)
    price_yearly: Optional[Decimal] = Field(default=None, decimal_places=2)
    trial_days: int = Field(default=7, ge=0, le=30)
    
    # Stripe integration
    stripe_product_id: Optional[str] = None
    stripe_price_id_monthly: Optional[str] = None
    stripe_price_id_yearly: Optional[str] = None
    
    # Stats
    subscriber_count: int = Field(default=0)
    avg_rating: float = Field(default=0.0, ge=0, le=5)
    review_count: int = Field(default=0)
    
    # Performance (verified from live trading)
    total_return_30d: Optional[float] = None
    sharpe_ratio: Optional[float] = None
    max_drawdown: Optional[float] = None
    win_rate: Optional[float] = None
    
    # Status
    is_active: bool = Field(default=True)
    is_approved: bool = Field(default=False)
    requires_kyc: bool = Field(default=False)
    
    subscriptions: List["MarketplaceSubscription"] = Relationship(back_populates="strategy")


class MarketplaceSubscription(SQLModel, table=True):
    """User subscription to a strategy."""
    __tablename__ = "marketplace_subscriptions"
    
    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    
    strategy_id: str = Field(foreign_key="marketplace_strategies.id")
    strategy: Optional[MarketplaceStrategy] = Relationship(back_populates="subscriptions")
    
    subscriber_id: str = Field(index=True)
    
    # Stripe
    stripe_subscription_id: Optional[str] = None
    stripe_customer_id: Optional[str] = None
    
    # Billing
    status: str = "trialing"  # trialing, active, past_due, cancelled
    current_period_start: Optional[datetime] = None
    current_period_end: Optional[datetime] = None
    cancel_at_period_end: bool = False
    
    # Copy trading settings
    multiplier: float = Field(default=1.0, ge=0.1, le=10.0)
    max_position_size: Optional[Decimal] = Field(default=None, decimal_places=2)
    max_daily_loss: Optional[Decimal] = Field(default=None, decimal_places=2)
    is_active: bool = Field(default=True)


class StrategyReview(SQLModel, table=True):
    """User reviews for strategies."""
    __tablename__ = "strategy_reviews"
    
    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    
    strategy_id: str = Field(foreign_key="marketplace_strategies.id")
    user_id: str
    rating: int = Field(ge=1, le=5)
    comment: Optional[str] = None
    is_verified_purchase: bool = False
