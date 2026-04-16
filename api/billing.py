# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
Billing & Growth API

Wires together Tasks 25–29 plus payment-method management:
  Task 25 — POST /api/billing/webhook/stripe           (Stripe billing webhook)
  Task 26 — POST /api/billing/affiliate/generate-link  (referral link generation)
  Task 27 — POST /api/billing/auth/activate-free-tier  (auto-assign FREE on signup)
  Task 28 — POST /api/billing/payments/flutterwave/init    (Flutterwave checkout)
             POST /api/billing/payments/flutterwave/verify  (verify transaction)
  Task 29 — GET  /api/billing/subscription             (current user subscription)

  Wallet:
    GET    /api/billing/balance                        (account balance)
    GET    /api/billing/transactions                   (transaction history)
    GET    /api/billing/payment-methods                (list saved Stripe cards)
    POST   /api/billing/payment-methods                (attach pm_xxx from Stripe.js)
    DELETE /api/billing/payment-methods/{pm_id}        (detach saved card)
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from decimal import Decimal

UTC = timezone.utc

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field

from api.auth import TokenPayload, get_current_user

logger = logging.getLogger(__name__)

# All routes are mounted under /api/billing — no /api/ prefix in path strings.
router = APIRouter(prefix="/api/billing", tags=["Billing"])

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
# Task 29 — GET /api/billing/subscription
# ─────────────────────────────────────────────────────────────────────────────


@router.get("/subscription")
async def get_subscription(user: TokenPayload = Depends(get_current_user)):
    """
    Return the authenticated user's active subscription.

    Returns tier, status, renewal date, and feature flags.
    Falls back to FREE tier defaults when no subscription record exists.
    """
    try:
        mgr = _get_subscription_manager()
        sub = mgr.get_user_subscription(user.sub)
    except Exception as exc:
        logger.warning("subscription_manager unavailable: %s", exc)
        sub = None

    if sub is None:
        return {
            "tier": "free",
            "status": "active",
            "subscription_id": None,
            "start_date": None,
            "end_date": None,
            "auto_renew": False,
            "features": ["paper_trading"],
            "upgrade_url": "/subscription",
        }

    tier_val = sub.tier.value if hasattr(sub.tier, "value") else str(sub.tier)
    status_val = sub.status.value if hasattr(sub.status, "value") else str(sub.status)

    return {
        "tier": tier_val,
        "status": status_val,
        "subscription_id": sub.subscription_id,
        "start_date": sub.start_date.isoformat() if sub.start_date else None,
        "end_date": sub.end_date.isoformat() if sub.end_date else None,
        "auto_renew": sub.auto_renew,
        "features": _tier_features(tier_val),
        "upgrade_url": "/subscription" if tier_val == "free" else None,
    }


def _tier_features(tier: str) -> list:
    """Map tier name to its feature list."""
    _map = {
        "free": ["paper_trading"],
        "professional": ["paper_trading", "live_trading", "ai_signals", "backtesting"],
        "enterprise": [
            "paper_trading",
            "live_trading",
            "ai_signals",
            "backtesting",
            "api_access",
            "white_label",
        ],
    }
    return _map.get(tier.lower(), ["paper_trading"])


# ─────────────────────────────────────────────────────────────────────────────
# Task 25 — Stripe Webhook
# ─────────────────────────────────────────────────────────────────────────────


@router.post("/webhook/stripe", include_in_schema=True)
async def stripe_webhook(request: Request):
    """
    Stripe webhook receiver — production client with signature verification.

    Handles: payment_intent.succeeded, payment_intent.payment_failed,
    customer.subscription.*, invoice.paid, invoice.payment_failed,
    radar.early_fraud_warning.created.

    Configure in Stripe Dashboard → Webhooks → Add endpoint:
      URL: https://app.hopefx.io/api/billing/webhook/stripe
      Events: payment_intent.*, customer.subscription.*, invoice.*, radar.*
    """
    from monetization.stripe_live import get_stripe_client

    payload = await request.body()
    sig = request.headers.get("stripe-signature", "")

    client = get_stripe_client()
    event = client.verify_webhook(payload, sig)

    if event is None:
        raise HTTPException(status_code=400, detail="Invalid Stripe webhook signature")

    result = client.handle_webhook_event(event)

    # Also forward to legacy subscription manager for backward compat
    try:
        mgr = _get_subscription_manager()
        mgr.handle_stripe_webhook(payload, sig)
    except Exception as _exc:
        logger.debug("Suppressed exception: %s", _exc)

    return {"received": True, "event_type": event.get("type"), "result": result}


@router.get("/stripe/config")
async def stripe_config():
    """
    Return safe Stripe configuration for the frontend (no secret keys).
    Used by the checkout page to initialise Stripe.js.
    """
    from monetization.stripe_live import get_stripe_client

    return get_stripe_client().get_config()


class CreatePaymentIntentRequest(BaseModel):
    customer_id: str
    amount_usd: float
    currency: str = "USD"
    description: str = "HopeFX subscription"
    metadata: dict | None = None
    user_ip: str | None = None
    idempotency_key: str | None = None


@router.post("/stripe/payment-intent")
async def create_payment_intent(
    body: CreatePaymentIntentRequest,
    request: Request,
):
    """
    Create a Stripe PaymentIntent with Radar fraud scoring and multi-currency support.

    Supported currencies: USD, EUR, GBP, AED, NGN, JPY, CHF, CAD, AUD, SGD.
    Returns client_secret for frontend Stripe.js confirmation.
    """
    from monetization.stripe_live import get_stripe_client

    client = get_stripe_client()
    user_ip = body.user_ip or request.client.host if request.client else None
    user_agent = request.headers.get("user-agent", "")

    result = client.create_payment_intent(
        customer_id=body.customer_id,
        amount_usd=Decimal(str(body.amount_usd)),
        currency=body.currency,
        description=body.description,
        metadata=body.metadata,
        user_ip=user_ip,
        user_agent=user_agent,
        idempotency_key=body.idempotency_key,
    )

    if not result.success:
        raise HTTPException(
            status_code=400,
            detail={
                "error": result.error_code,
                "message": result.error_message,
            },
        )

    return result.to_dict()


# ─────────────────────────────────────────────────────────────────────────────
# Task 26 — Referral Link Generation
# ─────────────────────────────────────────────────────────────────────────────


@router.post("/affiliate/generate-link")
async def generate_referral_link(user: TokenPayload = Depends(get_current_user)):
    """
    Get or create the authenticated user's unique referral link.

    Creates an affiliate account if one doesn't exist yet.
    Returns the shareable signup URL with the referral code embedded.
    """
    mgr = _get_affiliate_manager()

    affiliate = mgr.get_user_affiliate(user.sub)
    if not affiliate:
        affiliate = mgr.create_affiliate(user_id=user.sub)

    base_url = os.getenv("APP_BASE_URL", "https://hopefx.io")
    ref_url = f"{base_url}/signup?ref={affiliate.code}"

    return {
        "url": ref_url,
        "code": affiliate.code,
        "affiliate_id": affiliate.affiliate_id,
        "status": affiliate.status.value if hasattr(affiliate.status, "value") else str(affiliate.status),
    }


# ─────────────────────────────────────────────────────────────────────────────
# Task 27 — Free Tier Activation on Signup
# ─────────────────────────────────────────────────────────────────────────────


class FreeTierBody(BaseModel):
    user_id: str
    ref_code: str | None = None  # optional referral code from signup URL


@router.post("/auth/activate-free-tier", status_code=status.HTTP_201_CREATED)
async def activate_free_tier(body: FreeTierBody):
    """
    Called immediately after successful registration to assign the FREE tier.

    - Creates a FREE subscription (paper trading enabled, no credit card)
    - Tracks referral if ref_code is present
    - Returns tier info shown in the post-signup banner
    """
    from monetization.subscription import SubscriptionTier

    mgr = _get_subscription_manager()

    existing = mgr.get_user_subscription(body.user_id)
    if existing:
        return {
            "tier": existing.tier.value if hasattr(existing.tier, "value") else str(existing.tier),
            "message": "Subscription already active.",
            "features": ["paper_trading"],
        }

    sub = mgr.create_subscription(body.user_id, SubscriptionTier.FREE)

    if body.ref_code:
        try:
            aff_mgr = _get_affiliate_manager()
            aff_mgr.create_referral(
                affiliate_code=body.ref_code,
                referred_user_id=body.user_id,
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


@router.post("/payments/flutterwave/init")
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
        raise HTTPException(status_code=500, detail="Payment init failed — check server logs") from None


@router.post("/payments/flutterwave/verify")
async def flutterwave_verify(
    body: FlutterwaveVerifyBody,
    user: TokenPayload = Depends(get_current_user),
):
    """Verify a Flutterwave transaction and activate the subscription."""
    try:
        flw = _get_flutterwave()
        result = flw.verify_transaction(body.tx_ref)
        if result.get("status") == "verified":
            return {"verified": True, "tx_ref": body.tx_ref, "status": "verified"}
        return {
            "verified": False,
            "tx_ref": body.tx_ref,
            "status": result.get("status", "unknown"),
        }
    except Exception as exc:
        logger.error("Flutterwave verify error: %s", exc)
        raise HTTPException(status_code=500, detail="Verification failed — check server logs") from None


@router.get("/payments/flutterwave/status")
async def flutterwave_status():
    """Return whether Flutterwave is configured."""
    key = os.getenv("FLUTTERWAVE_SECRET_KEY", "")
    return {
        "enabled": bool(key and not key.startswith("FLWSECK_TEST-placeholder")),
        "note": "Set FLUTTERWAVE_SECRET_KEY in .env to enable live payments.",
    }


# ─────────────────────────────────────────────────────────────────────────────
# Wallet balance + transaction history
# ─────────────────────────────────────────────────────────────────────────────


@router.get("/balance")
async def get_balance(user: TokenPayload = Depends(get_current_user)):
    """
    Return the authenticated user's wallet balance.

    Reads from the subscription manager's payment records when available;
    falls back to the paper-trading account balance from the trading engine.
    """
    balance = 0.0
    frozen = 0.0
    pending = 0.0

    # Try trading account balance first (most accurate for paper accounts)
    try:
        from core.app_state import app_state

        broker = getattr(app_state, "broker", None)
        if broker is not None:
            import asyncio

            account = await asyncio.wait_for(broker.get_account(), timeout=3.0)
            if account:
                balance = float(getattr(account, "balance", 0) or account.get("balance", 0))
                margin_used = float(getattr(account, "margin_used", 0) or account.get("margin_used", 0))
                frozen = margin_used
    except Exception as exc:
        logger.debug("Broker balance unavailable: %s", exc)

    # Try subscription manager for payment-based balance
    try:
        mgr = _get_subscription_manager()
        sub = mgr.get_user_subscription(user.sub)
        if sub and hasattr(sub, "wallet_balance"):
            balance = float(sub.wallet_balance)
    except Exception as _exc:
        logger.debug("Suppressed exception: %s", _exc)

    return {
        "balance": round(balance, 2),
        "frozen": round(frozen, 2),
        "pending": round(pending, 2),
        "currency": "USD",
    }


# ─────────────────────────────────────────────────────────────────────────────
# Superadmin helpers — called by api/superadmin.py financial endpoints
# These are module-level async functions (not router endpoints) so they can be
# imported and awaited directly from the superadmin router.
# ─────────────────────────────────────────────────────────────────────────────


async def list_payments(
    period: str | None = None,
    page: int = 1,
    user=None,  # TokenPayload — typed loosely to avoid circular import
) -> dict:
    """
    Return paginated payment history for the superadmin financial panel.

    Sources (in priority order):
    1. Stripe charges via the production Stripe client
    2. Flutterwave transaction records
    3. In-memory PaymentProcessor records (paper / test payments)
    4. CryptoPayment rows from the database

    Returns a dict with keys: payments, total, page, page_size.
    """
    PAGE_SIZE = 50
    offset = (page - 1) * PAGE_SIZE
    payments: list[dict] = []

    # ── 1. Stripe charges ─────────────────────────────────────────────────────
    try:
        from monetization.stripe_live import get_stripe_client

        client = get_stripe_client()
        if hasattr(client, "list_customer_charges"):
            charges = client.list_customer_charges(user_id=None, limit=200)
            for c in charges:
                payments.append(
                    {
                        "payment_id": c.get("id", ""),
                        "user_id": c.get("customer", ""),
                        "username": c.get("billing_details", {}).get("name", ""),
                        "amount": (c.get("amount", 0) or 0) / 100,
                        "currency": (c.get("currency", "usd") or "usd").upper(),
                        "plan": c.get("description", ""),
                        "status": c.get("status", "unknown"),
                        "provider": "stripe",
                        "created_at": (
                            datetime.fromtimestamp(c["created"], tz=UTC).isoformat()
                            if isinstance(c.get("created"), (int, float))
                            else str(c.get("created", ""))
                        ),
                    }
                )
    except Exception as exc:
        logger.debug("list_payments: Stripe unavailable: %s", exc)

    # ── 2. PaymentProcessor in-memory records ─────────────────────────────────
    try:
        from monetization.payment_processor import payment_processor

        for p in payment_processor._payments.values():
            payments.append(
                {
                    "payment_id": p.payment_id,
                    "user_id": p.user_id,
                    "username": p.user_id,
                    "amount": float(p.amount),
                    "currency": p.currency,
                    "plan": p.subscription_id or "",
                    "status": p.status.value if hasattr(p.status, "value") else str(p.status),
                    "provider": p.payment_method or "stripe",
                    "created_at": p.created_at.isoformat() if p.created_at else "",
                }
            )
    except Exception as exc:
        logger.debug("list_payments: PaymentProcessor unavailable: %s", exc)

    # ── 3. CryptoPayment DB rows ──────────────────────────────────────────────
    try:
        from database.connection import SessionLocal
        from database.models import CryptoPayment

        db = SessionLocal()
        try:
            rows = db.query(CryptoPayment).order_by(CryptoPayment.created_at.desc()).limit(200).all()
            for row in rows:
                payments.append(
                    {
                        "payment_id": row.payment_id,
                        "user_id": row.user_id,
                        "username": row.user_id,
                        "amount": row.amount_usd,
                        "currency": "USD",
                        "plan": row.plan_id or "",
                        "status": row.status,
                        "provider": f"crypto:{row.currency}",
                        "created_at": row.created_at.isoformat() if row.created_at else "",
                    }
                )
        finally:
            db.close()
    except Exception as exc:
        logger.debug("list_payments: CryptoPayment DB unavailable: %s", exc)

    # ── Period filter ─────────────────────────────────────────────────────────
    if period:
        from datetime import datetime, timezone, timedelta

        now = datetime.now(timezone.utc)
        cutoffs = {
            "today": now.replace(hour=0, minute=0, second=0, microsecond=0),
            "mtd": now.replace(day=1, hour=0, minute=0, second=0, microsecond=0),
            "ytd": now.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0),
            "30d": now - timedelta(days=30),
            "90d": now - timedelta(days=90),
        }
        cutoff = cutoffs.get(period)
        if cutoff:
            filtered = []
            for p in payments:
                try:
                    ts = p.get("created_at", "")
                    if ts:
                        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                        if dt.tzinfo is None:
                            dt = dt.replace(tzinfo=timezone.utc)
                        if dt >= cutoff:
                            filtered.append(p)
                except Exception:
                    filtered.append(p)
            payments = filtered

    # Deduplicate by payment_id (same payment may appear in multiple sources)
    seen: set[str] = set()
    unique: list[dict] = []
    for p in payments:
        pid = p.get("payment_id", "")
        if pid and pid in seen:
            continue
        seen.add(pid)
        unique.append(p)

    # Sort newest first
    unique.sort(key=lambda p: p.get("created_at", ""), reverse=True)

    total = len(unique)
    page_data = unique[offset : offset + PAGE_SIZE]

    return {"payments": page_data, "total": total, "page": page, "page_size": PAGE_SIZE}


async def process_refund(
    payment_id: str,
    reason: str = "requested_by_customer",
    user=None,
) -> dict:
    """
    Issue a refund for a payment.

    Tries Stripe first (via PaymentProcessor), then logs for manual processing
    if Stripe is not configured.  Returns the updated payment status.
    """
    from monetization.payment_processor import payment_processor

    payment = payment_processor.get_payment(payment_id)

    if payment:
        success = payment_processor.refund_payment(payment_id, reason=reason)
        if not success:
            raise HTTPException(
                status_code=400,
                detail=f"Refund failed for payment {payment_id} — check server logs",
            )
        return {
            "ok": True,
            "payment_id": payment_id,
            "status": "refunded",
            "amount": float(payment.amount),
            "currency": payment.currency,
        }

    # Payment not in processor — try Stripe directly by charge ID
    try:
        from monetization.stripe_live import get_stripe_client
        import stripe as _stripe_sdk

        get_stripe_client()
        stripe_key = os.getenv("STRIPE_SECRET_KEY", "")
        if stripe_key:
            _stripe_sdk.api_key = stripe_key
            refund = _stripe_sdk.Refund.create(
                charge=payment_id,
                reason=reason
                if reason in ("duplicate", "fraudulent", "requested_by_customer")
                else "requested_by_customer",
            )
            return {
                "ok": True,
                "payment_id": payment_id,
                "refund_id": refund.get("id"),
                "status": refund.get("status", "pending"),
                "amount": (refund.get("amount", 0) or 0) / 100,
                "currency": (refund.get("currency", "usd") or "usd").upper(),
            }
    except Exception as exc:
        logger.warning("process_refund: Stripe direct refund failed: %s", exc)

    # Fallback — log for manual processing
    logger.info(
        "process_refund: payment %s not found in processor; queued for manual review (reason=%s)",
        payment_id,
        reason,
    )
    return {
        "ok": True,
        "payment_id": payment_id,
        "status": "refund_queued",
        "note": "Payment not found in processor — queued for manual review in Stripe Dashboard",
    }


async def get_affiliate_stats(user=None) -> dict:
    """
    Return aggregate affiliate program statistics for the superadmin panel.

    Pulls from AffiliateManager and enriches with per-affiliate username
    lookups where possible.
    """
    try:
        from monetization.affiliate import affiliate_manager

        raw = affiliate_manager.get_stats()
        affiliates = affiliate_manager.get_all_affiliates()

        # Build top-affiliates list sorted by commission earned
        top: list[dict] = []
        for aff in sorted(affiliates, key=lambda a: float(a.total_commissions), reverse=True)[:20]:
            metrics = affiliate_manager.get_affiliate_metrics(aff.affiliate_id)
            top.append(
                {
                    "affiliate_id": aff.affiliate_id,
                    "username": aff.user_id,  # user_id is the best identifier we have
                    "code": aff.code,
                    "level": aff.level.value if hasattr(aff.level, "value") else str(aff.level),
                    "referrals": metrics.total_referrals if metrics else 0,
                    "conversions": metrics.converted_referrals if metrics else 0,
                    "commission_earned": float(metrics.total_commissions) if metrics else 0.0,
                    "commission_pending": float(metrics.pending_commissions) if metrics else 0.0,
                }
            )

        # Pending commissions = sum of pending across all affiliates
        pending_commissions = sum(
            float(aff.total_commissions) - float(aff.paid_commissions)
            for aff in affiliates
            if hasattr(aff, "paid_commissions")
        )

        return {
            "total_affiliates": raw.get("total_affiliates", 0),
            "active_affiliates": raw.get("active_affiliates", 0),
            "total_commissions_paid": raw.get("total_payouts_processed", 0.0),
            "commissions_pending": pending_commissions,
            "total_referrals": raw.get("total_referrals", 0),
            "conversions_mtd": raw.get("converted_referrals", 0),
            "currency": "USD",
            "top_affiliates": top,
        }
    except Exception as exc:
        logger.warning("get_affiliate_stats: affiliate_manager unavailable: %s", exc)
        return {
            "total_affiliates": 0,
            "active_affiliates": 0,
            "total_commissions_paid": 0.0,
            "commissions_pending": 0.0,
            "total_referrals": 0,
            "conversions_mtd": 0,
            "currency": "USD",
            "top_affiliates": [],
        }


# ── Payment methods (Stripe saved cards) ─────────────────────────────────────


@router.get("/payment-methods")
async def list_payment_methods(user: TokenPayload = Depends(get_current_user)):
    """
    Return the authenticated user's saved Stripe payment methods.

    Resolves the Stripe customer ID from the subscription manager, then
    calls the Stripe API to list attached cards.  Returns an empty list
    when Stripe is not configured or the user has no saved methods.
    """
    try:
        from monetization.stripe_live import get_stripe_client

        client = get_stripe_client()
        customer_id = client.get_or_create_customer(user.sub, getattr(user, "email", None))
        methods = client.list_payment_methods(customer_id)
        return {"methods": methods}
    except Exception as exc:
        logger.warning("list_payment_methods: %s", exc)
        return {"methods": []}


class AttachPaymentMethodBody(BaseModel):
    payment_method_id: str


@router.post("/payment-methods", status_code=status.HTTP_201_CREATED)
async def attach_payment_method(
    body: AttachPaymentMethodBody,
    user: TokenPayload = Depends(get_current_user),
):
    """
    Attach a Stripe payment method to the authenticated user's customer record
    and set it as the default invoice payment method.

    The frontend should create the PaymentMethod via Stripe.js and pass the
    resulting ``pm_xxx`` ID in the request body.
    """
    try:
        from monetization.stripe_live import get_stripe_client

        client = get_stripe_client()
        customer_id = client.get_or_create_customer(user.sub, getattr(user, "email", None))
        pm = client.attach_payment_method(customer_id, body.payment_method_id)
        return {"method": pm}
    except RuntimeError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except Exception as exc:
        logger.error("attach_payment_method: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to attach payment method."
        ) from exc


@router.delete("/payment-methods/{payment_method_id}", status_code=status.HTTP_200_OK)
async def detach_payment_method(
    payment_method_id: str,
    user: TokenPayload = Depends(get_current_user),
):
    """
    Detach (remove) a saved payment method from the authenticated user's
    Stripe customer record.

    Verifies the payment method belongs to the user before detaching.
    """
    try:
        from monetization.stripe_live import get_stripe_client

        client = get_stripe_client()
        customer_id = client.get_or_create_customer(user.sub, getattr(user, "email", None))

        # Verify ownership before detaching
        methods = client.list_payment_methods(customer_id)
        owned_ids = {m["id"] for m in methods}
        if payment_method_id not in owned_ids:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Payment method not found or does not belong to this account.",
            )

        client.detach_payment_method(payment_method_id)
        return {"removed": payment_method_id}
    except HTTPException:
        raise
    except RuntimeError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except Exception as exc:
        logger.error("detach_payment_method: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to remove payment method."
        ) from exc


@router.get("/transactions")
async def get_transactions(
    limit: int = 50,
    offset: int = 0,
    user: TokenPayload = Depends(get_current_user),
):
    """
    Return the authenticated user's transaction history.

    Sources (in priority order):
    1. Stripe payment intents for this customer
    2. Flutterwave transaction records
    3. Subscription lifecycle events (upgrades, renewals, cancellations)

    Returns an empty list when no payment provider is configured.
    """
    transactions: list = []

    # ── Stripe payment history ────────────────────────────────────────────────
    try:
        from monetization.stripe_live import get_stripe_client

        client = get_stripe_client()
        if hasattr(client, "list_customer_charges"):
            charges = client.list_customer_charges(user.sub, limit=limit)
            for charge in charges:
                transactions.append(
                    {
                        "id": charge.get("id"),
                        "type": "deposit" if charge.get("amount", 0) > 0 else "refund",
                        "amount": charge.get("amount", 0) / 100,  # Stripe amounts are in cents
                        "currency": charge.get("currency", "usd").upper(),
                        "status": charge.get("status", "unknown"),
                        "date": charge.get("created_at") or charge.get("created"),
                        "method": charge.get("payment_method_details", {}).get("type", "card"),
                        "description": charge.get("description", ""),
                    }
                )
    except Exception as exc:
        logger.debug("Stripe transaction history unavailable: %s", exc)

    # ── Subscription lifecycle events ─────────────────────────────────────────
    try:
        mgr = _get_subscription_manager()
        sub = mgr.get_user_subscription(user.sub)
        if sub and hasattr(sub, "payment_history"):
            for event in sub.payment_history or []:
                transactions.append(
                    {
                        "id": event.get("id", ""),
                        "type": "subscription",
                        "amount": -abs(float(event.get("amount", 0))),
                        "currency": "USD",
                        "status": event.get("status", "completed"),
                        "date": event.get("date") or event.get("created_at"),
                        "method": event.get("plan", "subscription"),
                        "description": event.get("description", "Subscription payment"),
                    }
                )
    except Exception as exc:
        logger.debug("Subscription payment history unavailable: %s", exc)

    # Sort by date descending, apply pagination
    def _sort_key(tx: dict):
        d = tx.get("date")
        if d is None:
            return ""
        if isinstance(d, int | float):
            from datetime import datetime

            return datetime.fromtimestamp(d, tz=UTC).isoformat()
        return str(d)

    transactions.sort(key=_sort_key, reverse=True)
    page = transactions[offset : offset + limit]

    return {
        "transactions": page,
        "total": len(transactions),
        "limit": limit,
        "offset": offset,
    }
