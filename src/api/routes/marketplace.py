"""
FastAPI routes for marketplace operations.
"""
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, status, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update
from decimal import Decimal

from src.infrastructure.database import get_db
from src.marketplace.models import MarketplaceStrategy, MarketplaceSubscription
from src.marketplace.stripe_integration import StripeManager
from src.api.middleware.auth import get_current_user

router = APIRouter(prefix="/marketplace", tags=["marketplace"])


@router.post("/strategies", status_code=status.HTTP_201_CREATED)
async def create_strategy_listing(
    name: str,
    description: str,
    price_monthly: Decimal,
    price_yearly: Optional[Decimal] = None,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """
    Create a new strategy listing in the marketplace.
    """
    # Create Stripe product
    stripe_mgr = StripeManager()
    stripe_data = await stripe_mgr.create_strategy_product(
        name=name,
        description=description,
        price_monthly=price_monthly,
        price_yearly=price_yearly
    )
    
    # Create database record
    strategy = MarketplaceStrategy(
        name=name,
        description=description,
        owner_id=current_user["id"],
        price_monthly=price_monthly,
        price_yearly=price_yearly,
        stripe_product_id=stripe_data["product_id"],
        stripe_price_id_monthly=stripe_data["price_monthly_id"],
        stripe_price_id_yearly=stripe_data.get("price_yearly_id")
    )
    
    db.add(strategy)
    await db.commit()
    await db.refresh(strategy)
    
    return {
        "id": strategy.id,
        "name": strategy.name,
        "stripe_product_id": strategy.stripe_product_id,
        "status": "pending_approval"
    }


@router.get("/strategies")
async def list_strategies(
    category: Optional[str] = None,
    min_rating: Optional[float] = None,
    db: AsyncSession = Depends(get_db)
):
    """
    List available strategies with filtering.
    """
    query = select(MarketplaceStrategy).where(
        MarketplaceStrategy.is_active == True,
        MarketplaceStrategy.is_approved == True
    )
    
    if category:
        query = query.where(MarketplaceStrategy.category == category)
    if min_rating:
        query = query.where(MarketplaceStrategy.avg_rating >= min_rating)
    
    result = await db.execute(query)
    strategies = result.scalars().all()
    
    return [
        {
            "id": s.id,
            "name": s.name,
            "description": s.description[:200] + "..." if len(s.description) > 200 else s.description,
            "price_monthly": float(s.price_monthly),
            "price_yearly": float(s.price_yearly) if s.price_yearly else None,
            "rating": s.avg_rating,
            "review_count": s.review_count,
            "subscriber_count": s.subscriber_count,
            "performance": {
                "return_30d": s.total_return_30d,
                "sharpe": s.sharpe_ratio,
                "max_drawdown": s.max_drawdown
            }
        }
        for s in strategies
    ]


@router.post("/subscribe/{strategy_id}")
async def subscribe_to_strategy(
    strategy_id: str,
    payment_method_id: str,
    billing_period: str = "monthly",  # monthly or yearly
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """
    Subscribe to a strategy with Stripe checkout.
    """
    # Get strategy
    result = await db.execute(
        select(MarketplaceStrategy).where(MarketplaceStrategy.id == strategy_id)
    )
    strategy = result.scalar_one_or_none()
    
    if not strategy or not strategy.is_active:
        raise HTTPException(status_code=404, detail="Strategy not found")
    
    # Create Stripe customer
    stripe_mgr = StripeManager()
    customer_id = await stripe_mgr.create_customer(
        email=current_user["email"],
        user_id=current_user["id"],
        payment_method_id=payment_method_id
    )
    
    # Get correct price ID
    price_id = (
        strategy.stripe_price_id_yearly 
        if billing_period == "yearly" and strategy.stripe_price_id_yearly 
        else strategy.stripe_price_id_monthly
    )
    
    # Create subscription
    subscription_data = await stripe_mgr.create_subscription(
        customer_id=customer_id,
        price_id=price_id,
        trial_days=strategy.trial_days,
        metadata={
            "strategy_id": strategy_id,
            "user_id": current_user["id"],
            "platform": "hopefx"
        }
    )
    
    # Create local subscription record
    subscription = MarketplaceSubscription(
        strategy_id=strategy_id,
        subscriber_id=current_user["id"],
        stripe_subscription_id=subscription_data["subscription_id"],
        stripe_customer_id=customer_id,
        status="trialing" if strategy.trial_days > 0 else "active",
        multiplier=1.0
    )
    
    db.add(subscription)
    
    # Update subscriber count
    await db.execute(
        update(MarketplaceStrategy)
        .where(MarketplaceStrategy.id == strategy_id)
        .values(subscriber_count=MarketplaceStrategy.subscriber_count + 1)
    )
    
    await db.commit()
    
    return {
        "subscription_id": subscription.id,
        "stripe_subscription_id": subscription_data["subscription_id"],
        "status": subscription_data["status"],
        "client_secret": subscription_data["client_secret"],
        "trial_end": subscription_data.get("trial_end"),
        "message": f"Trial started. You will be charged after {strategy.trial_days} days."
    }


@router.post("/webhook")
async def stripe_webhook(request: Request, db: AsyncSession = Depends(get_db)):
    """
    Handle Stripe webhook events.
    """
    payload = await request.body()
    signature = request.headers.get("stripe-signature")
    
    if not signature:
        raise HTTPException(status_code=400, detail="Missing signature")
    
    stripe_mgr = StripeManager()
    result = await stripe_mgr.handle_webhook(payload, signature)
    
    # Update database based on event
    if result["event"] == "payment_succeeded":
        # Update subscription status
        pass
    elif result["event"] == "subscription_deleted":
        # Deactivate subscription
        await db.execute(
            update(MarketplaceSubscription)
            .where(MarketplaceSubscription.stripe_subscription_id == result["subscription_id"])
            .values(is_active=False, status="cancelled")
        )
        await db.commit()
    
    return {"received": True}
