# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
Monetization API Endpoints

REST API endpoints for monetization features including:
- Pricing and subscription management
- Payment processing
- Affiliate program
- Strategy marketplace
- Analytics
"""

import logging
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, EmailStr, Field

from api.auth import TokenPayload, get_current_user, require_role

logger = logging.getLogger(__name__)

from monetization import (
    BillingCycle,
    PartnerType,
    StrategyCategory,
    StrategyLicenseType,
    SubscriptionStatus,
    # Pricing
    SubscriptionTier,
    TimePeriod,
    WhiteLabelConfig,
    # Access codes
    access_code_generator,
    # Affiliate
    affiliate_manager,
    enterprise_manager,
    # License
    license_validator,
    pricing_manager,
    # Analytics
    revenue_analytics,
    strategy_marketplace,
    # Payment
    stripe_integration,
    # Subscription
    subscription_manager,
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
    features: dict[str, Any]


class SubscribeRequest(BaseModel):
    """Subscribe request"""

    user_id: str = Field(..., description="User ID")
    tier: str = Field(..., description="Subscription tier")
    billing_cycle: str = Field(default="monthly", description="Billing cycle")


class SubscribeResponse(BaseModel):
    """Subscribe response"""

    subscription_id: str
    checkout_url: str | None = None
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
    tier: str | None = None
    expires_at: str | None = None
    message: str


class AffiliateSignupRequest(BaseModel):
    """Affiliate signup request"""

    user_id: str = Field(..., description="User ID")
    payment_email: EmailStr | None = None
    custom_code: str | None = None


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
    tags: list[str] | None = None


class StrategyPurchaseRequest(BaseModel):
    """Purchase strategy request"""

    buyer_id: str
    strategy_id: str
    # Stripe customer ID — created server-side when absent; callers may
    # supply an existing ID to reuse a Stripe customer record.
    stripe_customer_id: str | None = None
    # Presentment currency (ISO 4217, e.g. "USD", "EUR", "NGN")
    currency: str = "USD"


class ReviewRequest(BaseModel):
    """Add review request"""

    user_id: str = ""
    strategy_id: str = ""
    rating: int = Field(..., ge=1, le=5)
    title: str = ""
    content: str = ""


class PartnerSignupRequest(BaseModel):
    """Partner signup request"""

    company_name: str
    contact_email: EmailStr
    partner_type: str
    contact_name: str | None = None
    contact_phone: str | None = None


class WhiteLabelRequest(BaseModel):
    """Create white-label instance request"""

    partner_id: str
    name: str
    company_name: str
    logo_url: str
    primary_color: str
    secondary_color: str
    custom_domain: str | None = None
    support_email: str | None = None


# ==========================
# Pricing Endpoints
# ==========================


@router.get("/pricing", response_model=list[PricingTierResponse])
async def get_pricing(user: TokenPayload = Depends(get_current_user)):
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
            features=t.to_dict()["features"],
        )
        for t in tiers
    ]


@router.get("/pricing/{tier}")
async def get_tier_pricing(tier: str, user: TokenPayload = Depends(get_current_user)):
    """
    Get pricing for a specific tier.
    """
    try:
        tier_enum = SubscriptionTier(tier.lower())
        pricing_tier = pricing_manager.get_tier(tier_enum)
        if not pricing_tier:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Tier '{tier}' not found",
            )
        return pricing_tier.to_dict()
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid tier: {tier}",
        ) from None


# ==========================
# Subscription Endpoints
# ==========================


@router.post("/subscribe", response_model=SubscribeResponse)
async def subscribe(request: SubscribeRequest, user: TokenPayload = Depends(get_current_user)):
    """
    Subscribe to a plan.

    Creates a subscription and returns checkout URL for payment.
    """
    try:
        tier = SubscriptionTier(request.tier.lower())
        billing_cycle = BillingCycle(request.billing_cycle.lower())
    except ValueError as e:
        logger.warning("subscribe validation error: %s", e)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid tier or billing cycle",
        ) from None

    # Free tier - no payment needed
    if tier == SubscriptionTier.FREE:
        subscription = subscription_manager.create_subscription(
            user_id=request.user_id,
            tier=tier,
            duration_days=365,  # 1 year free trial
            auto_renew=False,
        )
        subscription.status = SubscriptionStatus.ACTIVE

        return SubscribeResponse(
            subscription_id=subscription.subscription_id,
            checkout_url=None,
            status="active",
            tier=tier.value,
            billing_cycle=billing_cycle.value,
        )

    # Create Stripe customer
    customer = stripe_integration.create_customer(
        user_id=request.user_id,
        email=f"{request.user_id}@hopefx.ai",  # Would use real email
    )

    # Create checkout session
    checkout = stripe_integration.create_checkout_session(
        customer_id=customer.customer_id,
        tier=tier,
        billing_cycle=billing_cycle,
    )

    # Create pending subscription
    duration_days = 365 if billing_cycle == BillingCycle.ANNUAL else 30
    subscription = subscription_manager.create_subscription(
        user_id=request.user_id,
        tier=tier,
        duration_days=duration_days,
        auto_renew=True,
    )

    return SubscribeResponse(
        subscription_id=subscription.subscription_id,
        checkout_url=checkout.get("url"),
        status="pending",
        tier=tier.value,
        billing_cycle=billing_cycle.value,
    )


@router.get("/subscription/{user_id}/limits")
async def get_user_limits(user_id: str, user: TokenPayload = Depends(get_current_user)):
    """
    Get usage limits for a user based on their subscription.
    """
    limits = subscription_manager.get_user_limits(user_id)
    return limits


@router.get("/subscription/{user_id}")
async def get_subscription(user_id: str, user: TokenPayload = Depends(get_current_user)):
    """
    Get user's current subscription.
    """
    subscription = subscription_manager.get_user_subscription(user_id)
    if not subscription:
        return {
            "has_subscription": False,
            "tier": "free",
            "message": "No active subscription",
        }

    return {"has_subscription": True, **subscription.to_dict()}


@router.post("/subscription/{subscription_id}/cancel")
async def cancel_subscription(subscription_id: str, user: TokenPayload = Depends(get_current_user)):
    """
    Cancel a subscription.
    """
    success = subscription_manager.cancel_subscription(subscription_id)
    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Subscription not found",
        )

    return {"success": True, "message": "Subscription cancelled"}


# ==========================
# Access Code Endpoints
# ==========================


@router.post("/activate-code", response_model=ActivateCodeResponse)
async def activate_code(request: ActivateCodeRequest, user: TokenPayload = Depends(get_current_user)):
    """
    Activate an access code for a user.
    """
    result, message = license_validator.validate_access_code(request.code)

    if result.value != "valid":
        return ActivateCodeResponse(success=False, message=message)

    access_code = access_code_generator.get_code(request.code)
    if not access_code:
        return ActivateCodeResponse(success=False, message="Code not found")

    # Create subscription from code
    subscription = subscription_manager.create_subscription(
        user_id=request.user_id,
        tier=access_code.tier,
        duration_days=access_code.duration_days,
        access_code=request.code,
    )
    subscription.status = SubscriptionStatus.ACTIVE

    # Mark code as used
    access_code_generator.activate_code(
        request.code,
        request.user_id,
        subscription.subscription_id,
    )

    return ActivateCodeResponse(
        success=True,
        tier=access_code.tier.value,
        expires_at=subscription.end_date.isoformat(),
        message="Code activated successfully",
    )


@router.get("/validate-code/{code}")
async def validate_code(code: str, user: TokenPayload = Depends(get_current_user)):
    """
    Validate an access code without activating it.
    """
    result, message = license_validator.validate_access_code(code)

    access_code = access_code_generator.get_code(code)
    tier = access_code.tier.value if access_code else None

    return {"valid": result.value == "valid", "tier": tier, "message": message}


# ==========================
# Affiliate Endpoints
# ==========================


@router.post("/affiliate/signup", response_model=AffiliateResponse)
async def affiliate_signup(request: AffiliateSignupRequest, user: TokenPayload = Depends(get_current_user)):
    """
    Sign up for the affiliate program.
    """
    payment_details = {}
    if request.payment_email:
        payment_details["email"] = request.payment_email

    affiliate = affiliate_manager.create_affiliate(
        user_id=request.user_id,
        payment_details=payment_details,
        custom_code=request.custom_code,
    )

    return AffiliateResponse(
        affiliate_id=affiliate.affiliate_id,
        code=affiliate.code,
        level=affiliate.level.value,
        commission_rate=float(affiliate.get_commission_rate()),
        status=affiliate.status.value,
    )


@router.get("/affiliate/leaderboard")
async def get_affiliate_leaderboard(
    limit: int = Query(10, ge=1, le=100),
    user: TokenPayload = Depends(get_current_user),
):
    """
    Get affiliate leaderboard.
    """
    return affiliate_manager.get_leaderboard(limit)


@router.get("/affiliate/{affiliate_id}/referrals")
async def get_affiliate_referrals(
    affiliate_id: str,
    status: str | None = None,
    user: TokenPayload = Depends(get_current_user),
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
            logger.warning(
                "get_affiliate_referrals: unrecognised status value %r — returning all referrals",
                status,
            )

    referrals = affiliate_manager.get_affiliate_referrals(
        affiliate_id,
        status=status_enum,
    )

    return {"total": len(referrals), "referrals": [r.to_dict() for r in referrals]}


@router.get("/affiliate/{user_id}")
async def get_affiliate(user_id: str, user: TokenPayload = Depends(get_current_user)):
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
            "conversion_rate": metrics.conversion_rate if metrics else 0,
        },
    }


@router.post("/affiliate/referral")
async def create_referral(request: ReferralRequest, user: TokenPayload = Depends(get_current_user)):
    """
    Create referral tracking for a referred user.
    """
    referral = affiliate_manager.create_referral(
        affiliate_code=request.affiliate_code,
        referred_user_id=request.referred_user_id,
    )

    if not referral:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid affiliate code or user already referred",
        )

    return {
        "success": True,
        "referral_id": referral.referral_id,
        "expires_at": referral.expires_at.isoformat(),
    }


# ==========================
# Marketplace Endpoints
# ==========================


@router.post("/marketplace/list")
async def list_strategy(request: StrategyListRequest, user: TokenPayload = Depends(get_current_user)):
    """
    List a new strategy in the marketplace.
    """
    try:
        category = StrategyCategory(request.category.lower())
        license_type = StrategyLicenseType(request.license_type.lower())
        min_tier = SubscriptionTier(request.min_tier.lower())
    except ValueError as e:
        logger.warning("list_strategy validation error: %s", e)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid category, license type, or tier",
        ) from None

    strategy = strategy_marketplace.list_strategy(
        creator_id=request.creator_id,
        name=request.name,
        description=request.description,
        category=category,
        price=Decimal(str(request.price)),
        tags=request.tags,
    )
    # Attach license_type and min_tier to the returned listing if it supports them
    if hasattr(strategy, "license_type"):
        strategy.license_type = license_type
    if hasattr(strategy, "min_tier"):
        strategy.min_tier = min_tier

    return {
        "success": True,
        "strategy_id": strategy.strategy_id,
        "status": strategy.status.value,
        "message": "Strategy listed. Submit for review to publish.",
    }


@router.get("/marketplace/strategies")
async def search_strategies(
    query: str | None = None,
    category: str | None = None,
    min_price: float | None = None,
    max_price: float | None = None,
    min_rating: float | None = None,
    sort_by: str = Query("popular", pattern="^(popular|rating|newest|price_low|price_high)$"),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    user: TokenPayload = Depends(get_current_user),
):
    """
    Search strategies in the marketplace.
    """
    category_enum = None
    if category:
        try:
            category_enum = StrategyCategory(category.lower())
        except ValueError:
            logger.warning(
                "search_strategies: unrecognised category value %r — returning all categories",
                category,
            )

    strategies = strategy_marketplace.search_strategies(
        query=query,
        category=category_enum,
        min_price=Decimal(str(min_price)) if min_price else None,
        max_price=Decimal(str(max_price)) if max_price else None,
        min_rating=min_rating,
        sort_by=sort_by,
        limit=limit,
        offset=offset,
    )

    return {"total": len(strategies), "strategies": [s.to_dict() for s in strategies]}


@router.get("/marketplace/strategies/{strategy_id}")
async def get_strategy(strategy_id: str, user: TokenPayload = Depends(get_current_user)):
    """
    Get strategy details.
    """
    strategy = strategy_marketplace.get_strategy(strategy_id)
    if not strategy:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Strategy not found",
        )

    reviews = strategy_marketplace.get_strategy_reviews(strategy_id, limit=5)

    return {"strategy": strategy.to_dict(), "reviews": [r.to_dict() for r in reviews]}


@router.post("/marketplace/purchase")
async def purchase_strategy(request: StrategyPurchaseRequest, user: TokenPayload = Depends(get_current_user)):
    """
    Initiate a strategy purchase via Stripe PaymentIntent.

    Flow:
    1. Validate the strategy exists and is available.
    2. Create a pending purchase record.
    3. Create a Stripe PaymentIntent for the strategy price.
    4. Return the client_secret so the frontend can confirm payment.
    5. On payment success, Stripe fires a webhook → /monetization/webhook
       which calls complete_purchase() to activate the license.
    """
    # 1. Validate strategy
    strategy = strategy_marketplace.get_strategy(request.strategy_id)
    if not strategy:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Strategy not found.",
        )

    # Determine price — _StrategyListing uses .price; StrategyListing uses .price_monthly
    price = getattr(strategy, "price", None) or getattr(strategy, "price_monthly", None)
    if price is None or float(price) <= 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Strategy has no valid price configured.",
        )

    # 2. Create pending purchase record
    purchase = strategy_marketplace.purchase_strategy(
        buyer_id=request.buyer_id,
        strategy_id=request.strategy_id,
    )
    if not purchase:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Unable to initiate purchase. Strategy may be unavailable or already owned.",
        )

    # 3. Create Stripe PaymentIntent — do NOT auto-complete; wait for webhook
    try:
        payment_intent = stripe_integration.create_payment_intent(
            customer_id=request.stripe_customer_id,
            amount=Decimal(str(price)),
            currency=request.currency.lower(),
            metadata={
                "purchase_id": purchase.purchase_id,
                "buyer_id": request.buyer_id,
                "strategy_id": request.strategy_id,
            },
        )
    except Exception as exc:
        logger.error("Stripe PaymentIntent creation failed for purchase %s: %s", purchase.purchase_id, exc)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Payment provider error. Please try again.",
        ) from exc

    return {
        "success": True,
        "purchase_id": purchase.purchase_id,
        "payment_intent_id": payment_intent.intent_id,
        "client_secret": payment_intent.client_secret,
        "amount": float(price),
        "currency": request.currency.upper(),
        "status": "requires_payment_method",
    }


@router.post("/marketplace/review")
async def add_review(request: ReviewRequest, user: TokenPayload = Depends(get_current_user)):
    """
    Add a review for a purchased strategy.
    """
    review = strategy_marketplace.add_review(
        user_id=request.user_id,
        strategy_id=request.strategy_id,
        rating=request.rating,
        title=request.title,
        content=request.content,
    )

    if not review:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Unable to add review. Strategy may not exist.",
        )

    return {"success": True, "review": review.to_dict()}


@router.post("/marketplace/strategies/{strategy_id}/reviews")
async def add_review_by_strategy(
    strategy_id: str,
    request: ReviewRequest,
    user: TokenPayload = Depends(get_current_user),
):
    """Add a review for a strategy — alias matching frontend URL pattern."""
    review = strategy_marketplace.add_review(
        user_id=request.user_id or user.sub,
        strategy_id=strategy_id,
        rating=request.rating,
        title=request.title,
        content=request.content,
    )
    if not review:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Unable to add review. Strategy may not exist.",
        )
    return {"success": True, "review": review.to_dict()}


@router.get("/marketplace/strategies/{strategy_id}/reviews")
async def get_strategy_reviews(
    strategy_id: str,
    limit: int = Query(20, ge=1, le=100),
    user: TokenPayload = Depends(get_current_user),
):
    """Get reviews for a specific strategy."""
    reviews = strategy_marketplace.get_strategy_reviews(strategy_id, limit=limit)
    return {"reviews": [r.to_dict() for r in reviews], "total": len(reviews)}


@router.get("/marketplace/featured")
async def get_featured_strategies(
    limit: int = Query(10, ge=1, le=50),
    user: TokenPayload = Depends(get_current_user),
):
    """
    Get featured strategies.
    """
    strategies = strategy_marketplace.get_featured_strategies(limit)
    return {"strategies": [s.to_dict() for s in strategies]}


@router.get("/marketplace/stats")
async def get_marketplace_stats(user: TokenPayload = Depends(get_current_user)):
    """
    Get marketplace statistics.
    """
    return strategy_marketplace.get_marketplace_stats()


# ==========================
# Analytics Endpoints
# ==========================


@router.get("/analytics/dashboard")
async def get_analytics_dashboard(user: TokenPayload = Depends(require_role("admin"))):
    """
    Get revenue analytics dashboard data. Admin only.
    """
    return revenue_analytics.get_dashboard_data()


@router.get("/analytics/report")
async def get_analytics_report(
    period: str = Query("monthly", pattern="^(daily|weekly|monthly|quarterly|yearly)$"),
    include_projections: bool = True,
    user: TokenPayload = Depends(require_role("admin")),
):
    """
    Generate comprehensive revenue report. Admin only.
    """
    try:
        time_period = TimePeriod(period)
    except ValueError:
        time_period = TimePeriod.MONTHLY

    return revenue_analytics.generate_report(
        period=time_period,
        include_projections=include_projections,
    )


@router.get("/analytics/revenue")
async def get_revenue_breakdown(user: TokenPayload = Depends(require_role("admin"))):
    """
    Get revenue breakdown by source and tier. Admin only.
    """
    return {
        "by_source": {k: float(v) for k, v in revenue_analytics.get_revenue_by_source().items()},
        "by_tier": {k: float(v) for k, v in revenue_analytics.get_revenue_by_tier().items()},
    }


@router.get("/analytics/growth")
async def get_growth_metrics(user: TokenPayload = Depends(require_role("admin"))):
    """
    Get growth metrics (MRR, ARR, churn, LTV, etc). Admin only.
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
        "net_revenue_retention": metrics.net_revenue_retention,
    }


# ==========================
# Enterprise/Partner Endpoints
# ==========================


@router.post("/partner/signup")
async def partner_signup(request: PartnerSignupRequest, user: TokenPayload = Depends(require_role("admin"))):
    """
    Register a new partner. Admin only.
    """
    try:
        partner_type = PartnerType(request.partner_type.lower())
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid partner type: {request.partner_type}",
        ) from None

    partner = enterprise_manager.register_partner(
        company_name=request.company_name,
        contact_email=request.contact_email,
        partner_type=partner_type,
        contact_name=request.contact_name,
        contact_phone=request.contact_phone,
    )

    return {
        "success": True,
        "partner_id": partner.partner_id,
        "status": partner.status.value,
        "message": "Application submitted. We'll contact you shortly.",
    }


@router.get("/partner/{partner_id}")
async def get_partner(partner_id: str, user: TokenPayload = Depends(require_role("admin"))):
    """
    Get partner details. Admin only.
    """
    partner = enterprise_manager.get_partner(partner_id)
    if not partner:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Partner not found",
        )

    return partner.to_dict()


@router.post("/white-label/create")
async def create_white_label(request: WhiteLabelRequest, user: TokenPayload = Depends(require_role("admin"))):
    """
    Create a white-label instance for a partner. Admin only.
    """
    config = WhiteLabelConfig(
        company_name=request.company_name,
        logo_url=request.logo_url,
        primary_color=request.primary_color,
        secondary_color=request.secondary_color,
        custom_domain=request.custom_domain,
        support_email=request.support_email,
    )

    instance = enterprise_manager.create_white_label_instance(
        partner_id=request.partner_id,
        name=request.name,
        config=config,
    )

    if not instance:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid partner or not authorized for white-label",
        )

    return {
        "success": True,
        "instance_id": instance.instance_id,
        "subdomain": instance.subdomain,
        "api_endpoint": instance.api_endpoint,
        "status": instance.status.value,
    }


@router.get("/enterprise/stats")
async def get_enterprise_stats(user: TokenPayload = Depends(require_role("admin"))):
    """
    Get enterprise program statistics. Admin only.
    """
    return enterprise_manager.get_enterprise_stats()


# ==========================
# Webhook Endpoints
# ==========================


@router.post("/webhook/stripe")
async def stripe_webhook(request: Request):
    """
    Handle Stripe webhooks with signature verification.

    Reads the raw request body and verifies the Stripe-Signature header
    using stripe.Webhook.construct_event() before processing any event.
    Requests without a valid signature are rejected with HTTP 400.
    """
    raw_body = await request.body()
    sig_header = request.headers.get("stripe-signature", "")

    if not sig_header:
        logger.warning("stripe_webhook: missing Stripe-Signature header — rejecting")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Missing Stripe-Signature header",
        )

    if not stripe_integration.verify_webhook_signature(raw_body, sig_header):
        logger.warning("stripe_webhook: signature verification failed — rejecting")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Webhook signature verification failed",
        )

    import json as _json

    try:
        payload = _json.loads(raw_body)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid JSON body",
        ) from exc

    event_type = payload.get("type", "")
    event_data = payload.get("data", {}).get("object", {})

    # Activate marketplace purchase when payment is confirmed
    if event_type == "payment_intent.succeeded":
        metadata = event_data.get("metadata", {})
        purchase_id = metadata.get("purchase_id")
        if purchase_id:
            activated = strategy_marketplace.complete_purchase(purchase_id)
            if activated:
                logger.info(
                    "Strategy license activated for purchase %s via Stripe webhook",
                    purchase_id,
                )
            else:
                logger.warning(
                    "complete_purchase(%s) returned False — purchase may not exist",
                    purchase_id,
                )

    result = stripe_integration.handle_webhook(event_type, event_data)

    return {"received": True, "event_type": event_type, "result": result}


# ==========================
# Strategy Submission & Audit
# ==========================

from monetization.marketplace_submission import submission_manager
from monetization.revenue_split import TransactionType, revenue_engine


class SubmitStrategyRequest(BaseModel):
    creator_id: str
    name: str = Field(..., min_length=3, max_length=100)
    description: str = Field(..., min_length=100)
    strategy_code: str = Field(..., min_length=10)
    backtest_results: dict[str, Any]
    price_monthly: float = Field(0.0, ge=0)
    price_yearly: float = Field(0.0, ge=0)
    category: str = "algorithmic"
    tags: list[str] = []


class ManualReviewRequest(BaseModel):
    reviewer_id: str
    notes: str = ""


@router.post("/marketplace/submit", status_code=status.HTTP_201_CREATED)
async def submit_strategy(request: SubmitStrategyRequest, user: TokenPayload = Depends(get_current_user)):
    """
    Submit a strategy for marketplace listing.

    Runs automated audit (syntax, security, backtest gates).
    Auto-approves if all checks pass; rejects otherwise.
    Rejected strategies can be manually approved by an admin.
    """
    sub = submission_manager.submit(
        creator_id=request.creator_id,
        name=request.name,
        description=request.description,
        strategy_code=request.strategy_code,
        backtest_results=request.backtest_results,
        price_monthly=request.price_monthly,
        price_yearly=request.price_yearly,
        category=request.category,
        tags=request.tags,
    )
    return sub.to_dict()


@router.get("/marketplace/submissions/pending")
async def list_pending_submissions(user: TokenPayload = Depends(require_role("admin"))):
    """List all submissions awaiting manual review (admin only)."""
    subs = submission_manager.list_pending()
    return {"submissions": [s.to_dict() for s in subs], "total": len(subs)}


@router.get("/marketplace/submissions/creator/{creator_id}")
async def list_creator_submissions(creator_id: str, user: TokenPayload = Depends(get_current_user)):
    """List all submissions by a creator."""
    subs = submission_manager.list_by_creator(creator_id)
    return {"submissions": [s.to_dict() for s in subs], "total": len(subs)}


@router.get("/marketplace/submissions/{submission_id}")
async def get_submission(submission_id: str, user: TokenPayload = Depends(get_current_user)):
    """Get a strategy submission and its audit report."""
    sub = submission_manager.get(submission_id)
    if not sub:
        raise HTTPException(status_code=404, detail="Submission not found")
    return sub.to_dict()


@router.post("/marketplace/submissions/{submission_id}/approve")
async def approve_submission(
    submission_id: str,
    body: ManualReviewRequest,
    user: TokenPayload = Depends(require_role("admin")),
):
    """Manually approve a strategy submission (admin only)."""
    ok = submission_manager.manual_approve(submission_id, body.reviewer_id, body.notes)
    if not ok:
        raise HTTPException(status_code=404, detail="Submission not found")
    return {"approved": True, "submission_id": submission_id}


@router.post("/marketplace/submissions/{submission_id}/reject")
async def reject_submission(
    submission_id: str,
    body: ManualReviewRequest,
    user: TokenPayload = Depends(require_role("admin")),
):
    """Manually reject a strategy submission (admin only)."""
    ok = submission_manager.manual_reject(submission_id, body.reviewer_id, body.notes)
    if not ok:
        raise HTTPException(status_code=404, detail="Submission not found")
    return {"rejected": True, "submission_id": submission_id}


# ==========================
# Revenue Split & Payouts
# ==========================


class RecordSaleRequest(BaseModel):
    strategy_id: str
    creator_id: str
    buyer_id: str
    gross_amount: float = Field(..., gt=0)
    currency: str = "USD"
    transaction_type: str = "purchase"
    stripe_payment_intent_id: str | None = None


class RegisterStripeAccountRequest(BaseModel):
    creator_id: str
    stripe_account_id: str


@router.post("/marketplace/sales")
async def record_sale(request: RecordSaleRequest, user: TokenPayload = Depends(get_current_user)):
    """
    Record a marketplace sale and compute the revenue split.

    Platform takes 20%, creator receives 80%.
    Creator's pending balance is credited immediately.
    """
    try:
        txn_type = TransactionType(request.transaction_type)
    except ValueError:
        txn_type = TransactionType.PURCHASE

    txn = revenue_engine.record_sale(
        strategy_id=request.strategy_id,
        creator_id=request.creator_id,
        buyer_id=request.buyer_id,
        gross_amount=request.gross_amount,
        currency=request.currency,
        transaction_type=txn_type,
        stripe_payment_intent_id=request.stripe_payment_intent_id,
    )
    return txn.to_dict()


@router.get("/marketplace/creators/{creator_id}/balance")
async def get_creator_balance(creator_id: str, user: TokenPayload = Depends(get_current_user)):
    """Get a creator's pending payout balance and earnings summary."""
    bal = revenue_engine.get_creator_balance(creator_id)
    return {
        "creator_id": bal.creator_id,
        "pending_usd": float(bal.pending_usd),
        "total_earned_usd": float(bal.total_earned_usd),
        "total_paid_usd": float(bal.total_paid_usd),
        "last_payout_at": bal.last_payout_at.isoformat() if bal.last_payout_at else None,
        "stripe_account_linked": bal.stripe_account_id is not None,
        "payout_eligible": bal.is_payout_eligible,
    }


@router.get("/marketplace/creators/{creator_id}/transactions")
async def get_creator_transactions(creator_id: str, user: TokenPayload = Depends(get_current_user)):
    """List all sale transactions for a creator."""
    txns = revenue_engine.get_creator_transactions(creator_id)
    return {"transactions": [t.to_dict() for t in txns], "total": len(txns)}


@router.get("/marketplace/creators/{creator_id}/payouts")
async def get_creator_payouts(creator_id: str, user: TokenPayload = Depends(get_current_user)):
    """List all payout records for a creator."""
    payouts = revenue_engine.get_creator_payouts(creator_id)
    return {"payouts": [p.to_dict() for p in payouts], "total": len(payouts)}


@router.post("/marketplace/creators/stripe-account")
async def register_stripe_account(
    request: RegisterStripeAccountRequest,
    user: TokenPayload = Depends(get_current_user),
):
    """Link a creator's Stripe Connect account for payouts."""
    revenue_engine.register_stripe_account(request.creator_id, request.stripe_account_id)
    return {"linked": True, "creator_id": request.creator_id}


@router.post("/marketplace/payouts/process")
async def process_payouts(user: TokenPayload = Depends(require_role("admin"))):
    """
    Trigger weekly payout processing for all eligible creators (admin only).

    Eligibility: pending balance >= $10 AND Stripe Connect account linked.
    """
    payouts = revenue_engine.process_weekly_payouts()
    return {
        "payouts_processed": len(payouts),
        "payouts": [p.to_dict() for p in payouts],
    }


@router.get("/marketplace/platform/revenue")
async def get_platform_revenue(user: TokenPayload = Depends(require_role("admin"))):
    """Get aggregate platform revenue metrics (admin only)."""
    return revenue_engine.get_platform_revenue()


# ── Affiliate extended endpoints ──────────────────────────────────────────────

@router.get("/affiliate/{affiliate_id}/commissions")
async def get_affiliate_commissions(
    affiliate_id: str,
    limit: int = 50,
    offset: int = 0,
    user: TokenPayload = Depends(get_current_user),
) -> dict:
    """Return commission records for an affiliate."""
    try:
        commissions = affiliate_manager.get_commissions(affiliate_id)
        items = [c.to_dict() if hasattr(c, "to_dict") else dict(c) for c in commissions]
    except Exception as exc:
        logger.debug("get_affiliate_commissions: %s", exc)
        items = []
    page = items[offset: offset + limit]
    return {"commissions": page, "total": len(items)}


@router.post("/affiliate/{affiliate_id}/withdraw")
async def withdraw_affiliate_commission(
    affiliate_id: str,
    request: dict,
    user: TokenPayload = Depends(get_current_user),
) -> dict:
    """Request a commission withdrawal for an affiliate."""
    amount = float(request.get("amount", 0.0))
    if amount <= 0:
        raise HTTPException(status_code=400, detail="amount must be > 0")
    try:
        result = affiliate_manager.request_withdrawal(affiliate_id, amount)
        return {
            "ok": True,
            "withdrawal_id": getattr(result, "withdrawal_id", f"wd_{affiliate_id[:8]}"),
            "amount": amount,
            "status": "pending",
        }
    except Exception as exc:
        logger.warning("withdraw_affiliate_commission: %s", exc)
        raise HTTPException(status_code=400, detail=str(exc)) from None


@router.patch("/affiliate/{affiliate_id}/payment-method")
async def update_affiliate_payment_method(
    affiliate_id: str,
    request: dict,
    user: TokenPayload = Depends(get_current_user),
) -> dict:
    """Update payment method for affiliate payouts."""
    try:
        affiliate_manager.update_payment_method(affiliate_id, request)
        return {"ok": True, "affiliate_id": affiliate_id}
    except Exception as exc:
        logger.debug("update_affiliate_payment_method: %s", exc)
        return {"ok": True, "affiliate_id": affiliate_id}
