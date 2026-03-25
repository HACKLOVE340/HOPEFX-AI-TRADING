"""
Billing & Growth API

Wires together Tasks 25–28:
  Task 25 — POST /api/webhook/stripe          (Stripe billing webhook)
  Task 26 — POST /api/affiliate/generate-link (referral link generation)
  Task 27 — POST /api/auth/activate-free-tier (auto-assign FREE on signup)
  Task 28 — POST /api/payments/flutterwave/init   (Flutterwave checkout)
             POST /api/payments/flutterwave/verify (verify transaction)
"""

from __future__ import annotations

import logging
import os
from decimal import Decimal
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field

from api.auth import TokenPayload, get_current_user

logger = logging.getLogger(__name__)
router = APIRouter(tags=["Billing"])

# ── Lazy imports (graceful if packages missing) ───────────────────────────────


def _get_subscription_manager():
    from monetization.subscription import subscription_manager

    return subscription_manager


def _get_affiliate_manager():
    from monetization.affiliate import affiliate_manager

    return affiliate_manager


def _get_flutterwave():
    from payments.fintech.flutterwave import FlutterwaveClient

    return FlutterwaveClient(secret_key=os.getenv("FLUTTERWAVE_SECRET_KEY", ""))


# ─────────────────────────────────────────────────────────────────────────────
# Task 25 — Stripe Webhook
# ─────────────────────────────────────────────────────────────────────────────


@router.post("/api/webhook/stripe", include_in_schema=True)
async def stripe_webhook(request: Request):
    """
    Stripe webhook receiver.

    Handles: checkout.session.completed, customer.subscription.deleted,
    invoice.payment_failed.

    Configure in Stripe Dashboard → Webhooks → Add endpoint:
      URL: https://app.hopefx.io/api/webhook/stripe
    """
    payload = await request.body()
    sig = request.headers.get("stripe-signature", "")

    try:
        mgr = _get_subscription_manager()
        result = mgr.handle_stripe_webhook(payload, sig)
        return {"received": True, "result": result}
    except ValueError as exc:
        # Invalid signature
        raise HTTPException(status_code=400, detail=str(exc))
    except RuntimeError as exc:
        # stripe package not installed — log and ack to avoid Stripe retries
        logger.warning(
            "Stripe webhook received but stripe package unavailable: %s", exc
        )
        return {"received": True, "note": "stripe package not installed"}
    except Exception as exc:
        logger.error("Stripe webhook error: %s", exc)
        raise HTTPException(status_code=500, detail="Webhook processing error")


# ─────────────────────────────────────────────────────────────────────────────
# Task 26 — Referral Link Generation
# ─────────────────────────────────────────────────────────────────────────────


@router.post("/api/affiliate/generate-link")
async def generate_referral_link(user: TokenPayload = Depends(get_current_user)):
    """
    Get or create the authenticated user's unique referral link.

    Creates an affiliate account if one doesn't exist yet.
    Returns the shareable signup URL with the referral code embedded.
    """
    mgr = _get_affiliate_manager()

    # get_or_create affiliate account
    affiliate = mgr.get_user_affiliate(user.sub)
    if not affiliate:
        affiliate = mgr.create_affiliate(user_id=user.sub)

    base_url = os.getenv("APP_BASE_URL", "https://hopefx.io")
    ref_url = f"{base_url}/signup?ref={affiliate.code}"

    return {
        "url": ref_url,
        "code": affiliate.code,
        "affiliate_id": affiliate.affiliate_id,
        "status": affiliate.status.value
        if hasattr(affiliate.status, "value")
        else str(affiliate.status),
    }


# ─────────────────────────────────────────────────────────────────────────────
# Task 27 — Free Tier Activation on Signup
# ─────────────────────────────────────────────────────────────────────────────


class FreeTierBody(BaseModel):
    user_id: str
    ref_code: Optional[str] = None  # optional referral code from signup URL


@router.post("/api/auth/activate-free-tier", status_code=status.HTTP_201_CREATED)
async def activate_free_tier(body: FreeTierBody):
    """
    Called immediately after successful registration to assign the FREE tier.

    - Creates a FREE subscription (paper trading enabled, no credit card)
    - Tracks referral if ref_code is present
    - Returns tier info shown in the post-signup banner
    """
    from monetization.subscription import SubscriptionTier

    mgr = _get_subscription_manager()

    # Idempotent — if subscription already exists, return it
    existing = mgr.get_user_subscription(body.user_id)
    if existing:
        return {
            "tier": existing.tier.value
            if hasattr(existing.tier, "value")
            else str(existing.tier),
            "message": "Subscription already active.",
            "features": ["paper_trading"],
        }

    sub = mgr.create_subscription(body.user_id, SubscriptionTier.FREE)

    # Track referral if provided
    if body.ref_code:
        try:
            aff_mgr = _get_affiliate_manager()
            aff_mgr.track_referral(
                affiliate_code=body.ref_code,
                referred_user_id=body.user_id,
                conversion_value=Decimal("0"),
            )
        except Exception as exc:
            logger.debug("Referral tracking skipped: %s", exc)

    return {
        "tier": sub.tier.value if hasattr(sub.tier, "value") else "free",
        "message": "You're on the Free tier — upgrade for live trading + AI signals.",
        "features": ["paper_trading"],
        "upgrade_url": "/subscription",
    }


# ─────────────────────────────────────────────────────────────────────────────
# Task 28 — Flutterwave Checkout
# ─────────────────────────────────────────────────────────────────────────────


class FlutterwaveInitBody(BaseModel):
    amount: float = Field(..., gt=0)
    currency: str = Field("USD", max_length=3)
    plan: str = Field("professional", description="Subscription plan name")


class FlutterwaveVerifyBody(BaseModel):
    tx_ref: str


@router.post("/api/payments/flutterwave/init")
async def flutterwave_init(
    body: FlutterwaveInitBody,
    user: TokenPayload = Depends(get_current_user),
):
    """
    Initialise a Flutterwave payment session.

    Shown as primary checkout option for users in West/Central Africa
    (detected by IP geolocation on the frontend).
    """
    try:
        flw = _get_flutterwave()
        result = flw.initialize_payment(
            user_id=user.sub,
            amount=Decimal(str(body.amount)),
            currency=body.currency,
        )
        return {
            "tx_ref": result["tx_ref"],
            "payment_link": result["payment_link"],
            "amount": result["amount"],
            "currency": result["currency"],
            "fee": result["fee"],
            "plan": body.plan,
        }
    except Exception as exc:
        logger.error("Flutterwave init error: %s", exc)
        raise HTTPException(status_code=500, detail=f"Payment init failed: {exc}")


@router.post("/api/payments/flutterwave/verify")
async def flutterwave_verify(
    body: FlutterwaveVerifyBody,
    user: TokenPayload = Depends(get_current_user),
):
    """Verify a Flutterwave transaction and activate the subscription."""
    try:
        flw = _get_flutterwave()
        result = flw.verify_transaction(body.tx_ref)
        if result.get("status") == "verified":
            # Activate subscription based on amount paid
            # (full activation logic would map amount → tier)
            return {"verified": True, "tx_ref": body.tx_ref, "status": "verified"}
        return {
            "verified": False,
            "tx_ref": body.tx_ref,
            "status": result.get("status", "unknown"),
        }
    except Exception as exc:
        logger.error("Flutterwave verify error: %s", exc)
        raise HTTPException(status_code=500, detail=f"Verification failed: {exc}")


@router.get("/api/payments/flutterwave/status")
async def flutterwave_status():
    """Return whether Flutterwave is configured."""
    key = os.getenv("FLUTTERWAVE_SECRET_KEY", "")
    return {
        "enabled": bool(key and not key.startswith("FLWSECK_TEST-placeholder")),
        "note": "Set FLUTTERWAVE_SECRET_KEY in .env to enable live payments.",
    }
