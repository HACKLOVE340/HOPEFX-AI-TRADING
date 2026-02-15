"""
Monetization API Endpoints

REST API endpoints for monetization features including:
- Pricing and subscription management
- Payment processing
- Affiliate program
- Strategy marketplace
- Analytics
"""

from fastapi import APIRouter, HTTPException, status, Query, Body
from pydantic import BaseModel, Field, EmailStr
from typing import List, Optional, Dict, Any
from decimal import Decimal
from datetime import datetime

from monetization import (
    # Pricing
    SubscriptionTier,
    BillingCycle,
    pricing_manager,
    # Subscription
    subscription_manager,
    SubscriptionStatus,
    # Payment
    payment_processor,
    stripe_integration,
    # License
    license_validator,
    # Access codes
    access_code_generator,
    # Affiliate
    affiliate_manager,
    AffiliateLevel,
    # Marketplace
    strategy_marketplace,
    StrategyCategory,
    StrategyLicenseType,
    # Analytics
    revenue_analytics,
    TimePeriod,
    RevenueSource,
    # Enterprise
    enterprise_manager,
    PartnerType,
    WhiteLabelConfig,
)

# Create router
router = APIRouter(prefix="/api/monetization", tags=["Monetization"])


# ==========================
# Request/Response Models
# ==========================

class PricingTierResponse(BaseModel):
    """Pricing tier response"""
    tier: str
    name: str
    monthly_price: float
    annual_price: float
    commission_rate: float
    features: Dict[str, Any]


class SubscribeRequest(BaseModel):
    """Subscribe request"""
    user_id: str = Field(..., description="User ID")
    tier: str = Field(..., description="Subscription tier")
    billing_cycle: str = Field(default="monthly", description="Billing cycle")


class SubscribeResponse(BaseModel):
    """Subscribe response"""
    subscription_id: str
    checkout_url: Optional[str] = None
    status: str
    tier: str
    billing_cycle: str


class ActivateCodeRequest(BaseModel):
    """Activate access code request"""
    user_id: str = Field(..., description="User ID")
    code: str = Field(..., description="Access code")


class ActivateCodeResponse(BaseModel):
    """Activate code response"""
    success: bool
    tier: Optional[str] = None
    expires_at: Optional[str] = None
    message: str


class AffiliateSignupRequest(BaseModel):
    """Affiliate signup request"""
    user_id: str = Field(..., description="User ID")
    payment_email: Optional[EmailStr] = None
    custom_code: Optional[str] = None


class AffiliateResponse(BaseModel):
    """Affiliate response"""
    affiliate_id: str
    code: str
    level: str
    commission_rate: float
    status: str


class ReferralRequest(BaseModel):
    """Create referral tracking request"""
    affiliate_code: str = Field(..., description="Affiliate referral code")
    referred_user_id: str = Field(..., description="ID of referred user")


class StrategyListRequest(BaseModel):
    """List strategy in marketplace request"""
    creator_id: str
    name: str
    description: str
    category: str
    price: float
    license_type: str = "purchase"
    min_tier: str = "starter"
    tags: Optional[List[str]] = None


class StrategyPurchaseRequest(BaseModel):
    """Purchase strategy request"""
    buyer_id: str
    strategy_id: str


class ReviewRequest(BaseModel):
    """Add review request"""
    user_id: str
    strategy_id: str
    rating: int = Field(..., ge=1, le=5)
    title: str
    content: str


class PartnerSignupRequest(BaseModel):
    """Partner signup request"""
    company_name: str
    contact_email: EmailStr
    partner_type: str
    contact_name: Optional[str] = None
    contact_phone: Optional[str] = None


class WhiteLabelRequest(BaseModel):
    """Create white-label instance request"""
    partner_id: str
    name: str
    company_name: str
    logo_url: str
    primary_color: str
    secondary_color: str
    custom_domain: Optional[str] = None
    support_email: Optional[str] = None


# ==========================
# Pricing Endpoints
# ==========================

@router.get("/pricing", response_model=List[PricingTierResponse])
async def get_pricing():
    """
    Get all pricing tiers.
    
    Returns pricing information for all subscription tiers including
    monthly/annual prices, commission rates, and features.
    """
    tiers = pricing_manager.get_all_tiers()
    return [
        PricingTierResponse(
            tier=t.tier.value,
            name=t.name,
            monthly_price=float(t.monthly_price),
            annual_price=float(t.get_annual_price()),
            commission_rate=float(t.commission_rate),
            features=t.to_dict()['features']
        )
        for t in tiers
    ]


@router.get("/pricing/{tier}")
async def get_tier_pricing(tier: str):
    """
    Get pricing for a specific tier.
    """
    try:
        tier_enum = SubscriptionTier(tier.lower())
        pricing_tier = pricing_manager.get_tier(tier_enum)
        if not pricing_tier:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Tier '{tier}' not found"
            )
        return pricing_tier.to_dict()
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid tier: {tier}"
        )


# ==========================
# Subscription Endpoints
# ==========================

@router.post("/subscribe", response_model=SubscribeResponse)
async def subscribe(request: SubscribeRequest):
    """
    Subscribe to a plan.
    
    Creates a subscription and returns checkout URL for payment.
    """
    try:
        tier = SubscriptionTier(request.tier.lower())
        billing_cycle = BillingCycle(request.billing_cycle.lower())
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid tier or billing cycle: {str(e)}"
        )

    # Free tier - no payment needed
    if tier == SubscriptionTier.FREE:
        subscription = subscription_manager.create_subscription(
            user_id=request.user_id,
            tier=tier,
            duration_days=365,  # 1 year free trial
            auto_renew=False
        )
        subscription.status = SubscriptionStatus.ACTIVE
        
        return SubscribeResponse(
            subscription_id=subscription.subscription_id,
            checkout_url=None,
            status="active",
            tier=tier.value,
            billing_cycle=billing_cycle.value
        )

    # Create Stripe customer
    customer = stripe_integration.create_customer(
        user_id=request.user_id,
        email=f"{request.user_id}@hopefx.ai"  # Would use real email
    )

    # Create checkout session
    checkout = stripe_integration.create_checkout_session(
        customer_id=customer.customer_id,
        tier=tier,
        billing_cycle=billing_cycle
    )

    # Create pending subscription
    duration_days = 365 if billing_cycle == BillingCycle.ANNUAL else 30
    subscription = subscription_manager.create_subscription(
        user_id=request.user_id,
        tier=tier,
        duration_days=duration_days,
        auto_renew=True
    )

    return SubscribeResponse(
        subscription_id=subscription.subscription_id,
        checkout_url=checkout.get('url'),
        status="pending",
        tier=tier.value,
        billing_cycle=billing_cycle.value
    )


@router.get("/subscription/{user_id}")
async def get_subscription(user_id: str):
    """
    Get user's current subscription.
    """
    subscription = subscription_manager.get_user_subscription(user_id)
    if not subscription:
        return {
            "has_subscription": False,
            "tier": "free",
            "message": "No active subscription"
        }

    return {
        "has_subscription": True,
        **subscription.to_dict()
    }


@router.post("/subscription/{subscription_id}/cancel")
async def cancel_subscription(subscription_id: str):
    """
    Cancel a subscription.
    """
    success = subscription_manager.cancel_subscription(subscription_id)
    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Subscription not found"
        )
    
    return {"success": True, "message": "Subscription cancelled"}


@router.get("/subscription/{user_id}/limits")
async def get_user_limits(user_id: str):
    """
    Get usage limits for a user based on their subscription.
    """
    limits = subscription_manager.get_user_limits(user_id)
    return limits


# ==========================
# Access Code Endpoints
# ==========================

@router.post("/activate-code", response_model=ActivateCodeResponse)
async def activate_code(request: ActivateCodeRequest):
    """
    Activate an access code for a user.
    """
    result, message = license_validator.validate_access_code(request.code)
    
    if result.value != "valid":
        return ActivateCodeResponse(
            success=False,
            message=message
        )

    access_code = access_code_generator.get_code(request.code)
    if not access_code:
        return ActivateCodeResponse(
            success=False,
            message="Code not found"
        )

    # Create subscription from code
    subscription = subscription_manager.create_subscription(
        user_id=request.user_id,
        tier=access_code.tier,
        duration_days=access_code.duration_days,
        access_code=request.code
    )
    subscription.status = SubscriptionStatus.ACTIVE

    # Mark code as used
    access_code_generator.activate_code(
        request.code,
        request.user_id,
        subscription.subscription_id
    )

    return ActivateCodeResponse(
        success=True,
        tier=access_code.tier.value,
        expires_at=subscription.end_date.isoformat(),
        message="Code activated successfully"
    )


@router.get("/validate-code/{code}")
async def validate_code(code: str):
    """
    Validate an access code without activating it.
    """
    result, message = license_validator.validate_access_code(code)
    
    access_code = access_code_generator.get_code(code)
    tier = access_code.tier.value if access_code else None
    
    return {
        "valid": result.value == "valid",
        "tier": tier,
        "message": message
    }


# ==========================
# Affiliate Endpoints
# ==========================

@router.post("/affiliate/signup", response_model=AffiliateResponse)
async def affiliate_signup(request: AffiliateSignupRequest):
    """
    Sign up for the affiliate program.
    """
    payment_details = {}
    if request.payment_email:
        payment_details['email'] = request.payment_email

    affiliate = affiliate_manager.create_affiliate(
        user_id=request.user_id,
        payment_details=payment_details,
        custom_code=request.custom_code
    )

    return AffiliateResponse(
        affiliate_id=affiliate.affiliate_id,
        code=affiliate.code,
        level=affiliate.level.value,
        commission_rate=float(affiliate.get_commission_rate()),
        status=affiliate.status.value
    )


@router.get("/affiliate/{user_id}")
async def get_affiliate(user_id: str):
    """
    Get affiliate account for a user.
    """
    affiliate = affiliate_manager.get_user_affiliate(user_id)
    if not affiliate:
        return {"has_affiliate_account": False}

    metrics = affiliate_manager.get_affiliate_metrics(affiliate.affiliate_id)
    
    return {
        "has_affiliate_account": True,
        "affiliate": affiliate.to_dict(),
        "metrics": {
            "total_referrals": metrics.total_referrals if metrics else 0,
            "converted_referrals": metrics.converted_referrals if metrics else 0,
            "total_revenue": float(metrics.total_revenue) if metrics else 0,
            "total_commissions": float(metrics.total_commissions) if metrics else 0,
            "pending_commissions": float(metrics.pending_commissions) if metrics else 0,
            "conversion_rate": metrics.conversion_rate if metrics else 0
        }
    }


@router.post("/affiliate/referral")
async def create_referral(request: ReferralRequest):
    """
    Create referral tracking for a referred user.
    """
    referral = affiliate_manager.create_referral(
        affiliate_code=request.affiliate_code,
        referred_user_id=request.referred_user_id
    )
    
    if not referral:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid affiliate code or user already referred"
        )

    return {
        "success": True,
        "referral_id": referral.referral_id,
        "expires_at": referral.expires_at.isoformat()
    }


@router.get("/affiliate/{affiliate_id}/referrals")
async def get_affiliate_referrals(
    affiliate_id: str,
    status: Optional[str] = None
):
    """
    Get all referrals for an affiliate.
    """
    from monetization import ReferralStatus
    
    status_enum = None
    if status:
        try:
            status_enum = ReferralStatus(status)
        except ValueError:
            pass

    referrals = affiliate_manager.get_affiliate_referrals(
        affiliate_id,
        status=status_enum
    )

    return {
        "total": len(referrals),
        "referrals": [r.to_dict() for r in referrals]
    }


@router.get("/affiliate/leaderboard")
async def get_affiliate_leaderboard(limit: int = Query(10, ge=1, le=100)):
    """
    Get affiliate leaderboard.
    """
    return affiliate_manager.get_leaderboard(limit)


# ==========================
# Marketplace Endpoints
# ==========================

@router.post("/marketplace/list")
async def list_strategy(request: StrategyListRequest):
    """
    List a new strategy in the marketplace.
    """
    try:
        category = StrategyCategory(request.category.lower())
        license_type = StrategyLicenseType(request.license_type.lower())
        min_tier = SubscriptionTier(request.min_tier.lower())
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid category, license type, or tier: {str(e)}"
        )

    strategy = strategy_marketplace.list_strategy(
        creator_id=request.creator_id,
        name=request.name,
        description=request.description,
        category=category,
        price=Decimal(str(request.price)),
        license_type=license_type,
        min_tier=min_tier,
        tags=request.tags
    )

    return {
        "success": True,
        "strategy_id": strategy.strategy_id,
        "status": strategy.status.value,
        "message": "Strategy listed. Submit for review to publish."
    }


@router.get("/marketplace/strategies")
async def search_strategies(
    query: Optional[str] = None,
    category: Optional[str] = None,
    min_price: Optional[float] = None,
    max_price: Optional[float] = None,
    min_rating: Optional[float] = None,
    sort_by: str = Query("popular", regex="^(popular|rating|newest|price_low|price_high)$"),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0)
):
    """
    Search strategies in the marketplace.
    """
    category_enum = None
    if category:
        try:
            category_enum = StrategyCategory(category.lower())
        except ValueError:
            pass

    strategies = strategy_marketplace.search_strategies(
        query=query,
        category=category_enum,
        min_price=Decimal(str(min_price)) if min_price else None,
        max_price=Decimal(str(max_price)) if max_price else None,
        min_rating=min_rating,
        sort_by=sort_by,
        limit=limit,
        offset=offset
    )

    return {
        "total": len(strategies),
        "strategies": [s.to_dict() for s in strategies]
    }


@router.get("/marketplace/strategies/{strategy_id}")
async def get_strategy(strategy_id: str):
    """
    Get strategy details.
    """
    strategy = strategy_marketplace.get_strategy(strategy_id)
    if not strategy:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Strategy not found"
        )

    reviews = strategy_marketplace.get_strategy_reviews(strategy_id, limit=5)

    return {
        "strategy": strategy.to_dict(),
        "reviews": [r.to_dict() for r in reviews]
    }


@router.post("/marketplace/purchase")
async def purchase_strategy(request: StrategyPurchaseRequest):
    """
    Purchase a strategy.
    """
    purchase = strategy_marketplace.purchase_strategy(
        buyer_id=request.buyer_id,
        strategy_id=request.strategy_id
    )

    if not purchase:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Unable to purchase. Strategy may be unavailable or already owned."
        )

    # In production, would initiate payment here
    # For now, auto-complete
    strategy_marketplace.complete_purchase(purchase.purchase_id)

    return {
        "success": True,
        "purchase": purchase.to_dict()
    }


@router.post("/marketplace/review")
async def add_review(request: ReviewRequest):
    """
    Add a review for a purchased strategy.
    """
    review = strategy_marketplace.add_review(
        user_id=request.user_id,
        strategy_id=request.strategy_id,
        rating=request.rating,
        title=request.title,
        content=request.content
    )

    if not review:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Unable to add review. Strategy may not exist."
        )

    return {
        "success": True,
        "review": review.to_dict()
    }


@router.get("/marketplace/featured")
async def get_featured_strategies(limit: int = Query(10, ge=1, le=50)):
    """
    Get featured strategies.
    """
    strategies = strategy_marketplace.get_featured_strategies(limit)
    return {
        "strategies": [s.to_dict() for s in strategies]
    }


@router.get("/marketplace/stats")
async def get_marketplace_stats():
    """
    Get marketplace statistics.
    """
    return strategy_marketplace.get_marketplace_stats()


# ==========================
# Analytics Endpoints
# ==========================

@router.get("/analytics/dashboard")
async def get_analytics_dashboard():
    """
    Get revenue analytics dashboard data.
    """
    return revenue_analytics.get_dashboard_data()


@router.get("/analytics/report")
async def get_analytics_report(
    period: str = Query("monthly", regex="^(daily|weekly|monthly|quarterly|yearly)$"),
    include_projections: bool = True
):
    """
    Generate comprehensive revenue report.
    """
    try:
        time_period = TimePeriod(period)
    except ValueError:
        time_period = TimePeriod.MONTHLY

    return revenue_analytics.generate_report(
        period=time_period,
        include_projections=include_projections
    )


@router.get("/analytics/revenue")
async def get_revenue_breakdown():
    """
    Get revenue breakdown by source and tier.
    """
    return {
        "by_source": {
            k: float(v) 
            for k, v in revenue_analytics.get_revenue_by_source().items()
        },
        "by_tier": {
            k: float(v) 
            for k, v in revenue_analytics.get_revenue_by_tier().items()
        }
    }


@router.get("/analytics/growth")
async def get_growth_metrics():
    """
    Get growth metrics (MRR, ARR, churn, LTV, etc).
    """
    metrics = revenue_analytics.get_growth_metrics()
    return {
        "mrr": float(metrics.mrr),
        "arr": float(metrics.arr),
        "mrr_growth_rate": metrics.mrr_growth_rate,
        "churn_rate": metrics.churn_rate,
        "ltv": float(metrics.ltv),
        "cac": float(metrics.cac),
        "ltv_cac_ratio": metrics.ltv_cac_ratio,
        "net_revenue_retention": metrics.net_revenue_retention
    }


# ==========================
# Enterprise/Partner Endpoints
# ==========================

@router.post("/partner/signup")
async def partner_signup(request: PartnerSignupRequest):
    """
    Apply to become a partner.
    """
    try:
        partner_type = PartnerType(request.partner_type.lower())
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid partner type: {request.partner_type}"
        )

    partner = enterprise_manager.register_partner(
        company_name=request.company_name,
        contact_email=request.contact_email,
        partner_type=partner_type,
        contact_name=request.contact_name,
        contact_phone=request.contact_phone
    )

    return {
        "success": True,
        "partner_id": partner.partner_id,
        "status": partner.status.value,
        "message": "Application submitted. We'll contact you shortly."
    }


@router.get("/partner/{partner_id}")
async def get_partner(partner_id: str):
    """
    Get partner details.
    """
    partner = enterprise_manager.get_partner(partner_id)
    if not partner:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Partner not found"
        )

    return partner.to_dict()


@router.post("/white-label/create")
async def create_white_label(request: WhiteLabelRequest):
    """
    Create a white-label instance for a partner.
    """
    config = WhiteLabelConfig(
        company_name=request.company_name,
        logo_url=request.logo_url,
        primary_color=request.primary_color,
        secondary_color=request.secondary_color,
        custom_domain=request.custom_domain,
        support_email=request.support_email
    )

    instance = enterprise_manager.create_white_label_instance(
        partner_id=request.partner_id,
        name=request.name,
        config=config
    )

    if not instance:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid partner or not authorized for white-label"
        )

    return {
        "success": True,
        "instance_id": instance.instance_id,
        "subdomain": instance.subdomain,
        "api_endpoint": instance.api_endpoint,
        "status": instance.status.value
    }


@router.get("/enterprise/stats")
async def get_enterprise_stats():
    """
    Get enterprise program statistics.
    """
    return enterprise_manager.get_enterprise_stats()


# ==========================
# Webhook Endpoints
# ==========================

@router.post("/webhook/stripe")
async def stripe_webhook(
    payload: Dict[str, Any] = Body(...)
):
    """
    Handle Stripe webhooks.
    """
    event_type = payload.get('type', '')
    event_data = payload.get('data', {}).get('object', {})

    result = stripe_integration.handle_webhook(event_type, event_data)

    return {
        "received": True,
        "event_type": event_type,
        "result": result
    }
