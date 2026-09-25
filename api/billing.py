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

import hashlib
import logging
import os
from datetime import datetime, timezone
from decimal import Decimal

UTC = timezone.utc

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, Field

from api.auth import TokenPayload, get_current_user

# ── F4-01b (final): the narrow wallet gate ───────────────────────────────────
#
# This router was deliberately left ungated in the first pass, and the reason
# still holds for most of it: **billing is how a user upgrades.** Gating
# /plans, /subscription, /stripe/*, /payments/* or /payment-methods behind a paid
# plan would lock a free user out of the page that sells them the plan.
#
# Two groups are not that, and are gated:
#
#   /elite/*                 elite    — dedicated account manager contact,
#                                       support tickets and custom-dev requests.
#                                       Each says "(Elite)" in its own summary
#                                       and was reachable by any authenticated
#                                       free-tier account.
#   /balance, /transactions  starter  — the `wallet` feature the UI advertises
#                                       at starter and gated in React only.
#
# Everything else stays open on purpose. The omissions here are decisions.
from monetization.subscription import require_plan
from monetization.activation import UnknownPlanError, activate_paid_plan, resolve_plan_price_usd

logger = logging.getLogger(__name__)

# All routes are mounted under /api/billing — no /api/ prefix in path strings.
router = APIRouter(prefix="/api/billing", tags=["Billing"])


# ── Payment configuration gate ────────────────────────────────────────────────


def payments_configured() -> bool:
    """Whether a payment provider is actually usable.

    Read-only account views do not need one. ``/balance`` reads the broker's
    account, and ``/transactions`` documents that it "returns an empty list when
    no payment provider is configured" — both are built to work on a deployment
    that has not set up payments yet.
    """
    return bool(
        os.getenv("STRIPE_SECRET_KEY") or os.getenv("FLUTTERWAVE_SECRET_KEY") or os.getenv("CRYPTO_WEBHOOK_SECRET")
    )


def require_payments_configured() -> None:
    """Guard for endpoints that move money. Returns 503, not 404.

    The distinction matters. This router used to be hidden entirely behind
    ``FEATURE_BILLING_SUBSCRIPTION``, so with billing off every one of its 31
    endpoints 404'd — including ``/balance`` and ``/transactions``, which the
    Wallet page calls unconditionally. A 404 tells the client the feature does
    not exist; the truth is that it exists and is not configured yet, which is a
    503. The platform's own diagnostics flagged the same thing from the other
    side: "route_families CRITICAL — 1 endpoint family are not registered. Every
    page under a missing prefix will 404."
    """
    if not payments_configured():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "Payments are not configured on this deployment. Set STRIPE_SECRET_KEY "
                "(and STRIPE_WEBHOOK_SECRET in production) or FLUTTERWAVE_SECRET_KEY to "
                "enable payment processing. Account balance and transaction history do "
                "not require this."
            ),
        )


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
# GET /api/billing/plans — available subscription plans
# ─────────────────────────────────────────────────────────────────────────────

# Canonical 5-tier plan catalogue — prices match monetization/pricing.py.
# Annual price = monthly × 10 (2 months free).
_PLANS = [
    {
        "id": "free",
        "name": "Free",
        "price_usd_monthly": 0,
        "price_usd_annual": 0,
        "commission_rate": 0.010,
        "features": ["paper_trading"],
        "limits": {
            "signals_per_day": 5,
            "backtests_per_month": 3,
            "live_accounts": 0,
            "max_strategies": 1,
            "max_brokers": 1,
        },
    },
    {
        "id": "starter",
        "name": "Starter",
        "price_usd_monthly": 1800,
        "price_usd_annual": 18000,
        "commission_rate": 0.005,
        "features": ["paper_trading", "live_trading"],
        "limits": {
            "signals_per_day": 20,
            "backtests_per_month": 10,
            "live_accounts": 1,
            "max_strategies": 3,
            "max_brokers": 1,
        },
    },
    {
        "id": "professional",
        "name": "Professional",
        "price_usd_monthly": 4500,
        "price_usd_annual": 45000,
        "commission_rate": 0.003,
        "features": [
            "paper_trading",
            "live_trading",
            "ai_signals",
            "backtesting",
            "pattern_recognition",
            "api_access",
            "priority_support",
        ],
        "limits": {
            "signals_per_day": 100,
            "backtests_per_month": 50,
            "live_accounts": 3,
            "max_strategies": 7,
            "max_brokers": 3,
        },
    },
    {
        "id": "enterprise",
        "name": "Enterprise",
        "price_usd_monthly": 7500,
        "price_usd_annual": 75000,
        "commission_rate": 0.002,
        "features": [
            "paper_trading",
            "live_trading",
            "ai_signals",
            "backtesting",
            "pattern_recognition",
            "api_access",
            "priority_support",
            "news_integration",
            "white_label",
        ],
        "limits": {
            "signals_per_day": -1,
            "backtests_per_month": -1,
            "live_accounts": -1,
            "max_strategies": -1,
            "max_brokers": -1,
        },
    },
    {
        "id": "elite",
        "name": "Elite",
        "price_usd_monthly": 10000,
        "price_usd_annual": 100000,
        "commission_rate": 0.001,
        "features": [
            "paper_trading",
            "live_trading",
            "ai_signals",
            "backtesting",
            "pattern_recognition",
            "api_access",
            "priority_support",
            "news_integration",
            "white_label",
            "dedicated_support",
            "custom_development",
        ],
        "limits": {
            "signals_per_day": -1,
            "backtests_per_month": -1,
            "live_accounts": -1,
            "max_strategies": -1,
            "max_brokers": -1,
        },
    },
]


@router.get("/plans", summary="List available subscription plans")
async def get_plans():
    """Return all available subscription plans with pricing and feature details."""
    return {"plans": _PLANS}


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
            "plan": "free",
            "status": "active",
            "subscription_id": None,
            "start_date": None,
            "end_date": None,
            "auto_renew": False,
            "features": ["paper_trading"],
            "upgrade_url": "/checkout",
        }

    tier_val = sub.tier.value if hasattr(sub.tier, "value") else str(sub.tier)
    status_val = sub.status.value if hasattr(sub.status, "value") else str(sub.status)
    is_trial = status_val == "trial"

    # Calculate days remaining for trial subscriptions
    trial_days_remaining: int | None = None
    if is_trial and sub.end_date:
        from datetime import datetime, timezone as _tz

        delta = sub.end_date - datetime.now(_tz.utc)
        trial_days_remaining = max(0, delta.days)

    return {
        "tier": tier_val,
        "plan": tier_val,
        "status": status_val,
        "trial": is_trial,
        "trial_days_remaining": trial_days_remaining,
        "subscription_id": sub.subscription_id,
        "start_date": sub.start_date.isoformat() if sub.start_date else None,
        "end_date": sub.end_date.isoformat() if sub.end_date else None,
        "auto_renew": sub.auto_renew,
        "features": _tier_features(tier_val),
        "upgrade_url": "/pricing" if tier_val in ("free", "starter") else None,
    }


def _tier_features(tier: str) -> list:
    """Return the feature list for a tier by looking it up in _PLANS."""
    t = tier.lower()
    for plan in _PLANS:
        if plan["id"] == t:
            return list(plan["features"])
    return ["paper_trading"]


# ─────────────────────────────────────────────────────────────────────────────
# Task 25 — Stripe Webhook
# ─────────────────────────────────────────────────────────────────────────────


# ─────────────────────────────────────────────────────────────────────────────
# Confirmed deposits credit the fiat wallet ledger — ADR 0021
# ─────────────────────────────────────────────────────────────────────────────


def _already_credited(wallet_manager, user_id: str, reference: str) -> bool:
    """Has this external payment already moved money for this user?

    Queried against the SAME session factory the ledger writes through, so the
    answer is about the rows that would actually collide.

    This is the normal path, NOT the guarantee, and that split was measured
    rather than assumed. With this check removed, a replayed event still writes
    exactly one row: `uq_wallet_txn_user_reference` refuses the second insert,
    `_persist_transaction` returns False, and `_apply_movement` rolls the
    balance back. The database is what makes a replay — and the race between two
    concurrent deliveries, which this check cannot see — safe.

    What the check buys is an honest answer. Without it a routine Stripe retry
    reports "Ledger write failed; movement refused" and logs an IntegrityError
    traceback at ERROR, which reads like a broken ledger rather than a duplicate
    delivery. Operators who learn to ignore that message will ignore it on the
    day it means something.

    When there is no database at all — the in-memory mode tests and paper
    trading use — fall back to the process's own history, which is the only
    record there is. That fallback has no constraint behind it, so it is best
    effort by construction; in-memory mode moves no real money.
    """
    factory = getattr(wallet_manager, "session_factory", None)
    if factory is None:
        history = wallet_manager.get_transaction_history(user_id, limit=500)
        return any(row.get("reference") == reference for row in history)

    from database.models import WalletTransaction

    with factory() as session:
        return session.query(WalletTransaction).filter_by(user_id=user_id, reference=reference).first() is not None


def _credit_confirmed_deposit(data: dict) -> dict:
    """Credit the depositor's wallet for a CONFIRMED Stripe payment.

    Called on `payment_intent.succeeded` — the point at which money has actually
    been received. Creating a PaymentIntent moves nothing, so crediting there
    would invent funds.

    Returns a result rather than raising, so one failing credit cannot discard
    the rest of the webhook's work. `retryable` says whether re-delivery could
    succeed: a missing ledger is a server problem and will pass later, while a
    payment that names no user will never become attributable by being sent
    again.
    """
    from decimal import Decimal

    from core.app_state import app_state

    pi_id = str(data.get("id") or "")
    metadata = data.get("metadata") or {}
    user_id = str(metadata.get("user_id") or "").strip()

    if not user_id:
        # Fail closed on attribution: never guess whose money this is. The
        # Stripe customer id is not a user_id here, and mapping it by email or
        # by "the only recent deposit of that amount" is how money lands in the
        # wrong account.
        logger.error(
            "Confirmed payment %s carries no user_id in its metadata — NOT credited, "
            "and it cannot be attributed later from this payload alone. "
            "Deposits set this in api/payments.py::_fiat_deposit_impl.",
            pi_id,
        )
        return {"credited": False, "retryable": False, "reason": "unattributable: no user_id in metadata"}

    wallet_manager = getattr(app_state, "wallet_manager", None)
    if wallet_manager is None:
        logger.critical(
            "Confirmed payment %s for user %s could NOT be credited: no wallet ledger is wired. "
            "The money was taken and is unrecorded until this delivery is retried.",
            pi_id,
            user_id,
        )
        return {"credited": False, "retryable": True, "reason": "wallet ledger unavailable"}

    # The provider's own id is the deduplicating key. `transaction_id` is unique
    # but generated per call, so it identifies the WRITE, not the PAYMENT.
    reference = f"stripe:{pi_id}"

    try:
        if _already_credited(wallet_manager, user_id, reference):
            logger.info("Payment %s was already credited to user %s — replay ignored", pi_id, user_id)
            return {"credited": False, "already_applied": True, "reason": "already credited"}
    except Exception:
        # A failed lookup must not become a second credit. The constraint would
        # refuse the duplicate write anyway, but proceeding on an unknown answer
        # is the wrong default on a money path.
        logger.exception("Could not determine whether payment %s was already credited", pi_id)
        return {"credited": False, "retryable": True, "reason": "duplicate check failed"}

    # Stripe amounts are INTEGER CENTS. Divide a Decimal by 100 — never
    # `Decimal(cents / 100)`, which inherits the float's binary error, and never
    # `float(cents) / 100`, which `_validate_amount` would then reject or, worse,
    # accept with a sub-cent residue.
    try:
        amount = Decimal(int(data.get("amount") or 0)) / Decimal(100)
    except (TypeError, ValueError, ArithmeticError):
        logger.error("Confirmed payment %s has an unusable amount %r", pi_id, data.get("amount"))
        return {"credited": False, "retryable": False, "reason": "unusable amount"}

    ok, message, _txn = wallet_manager.credit_wallet(
        user_id=user_id,
        amount=amount,
        transaction_type="deposit",
        method="stripe",
        reference=reference,
    )
    if not ok:
        logger.error("Crediting confirmed payment %s for user %s was refused: %s", pi_id, user_id, message)
        return {"credited": False, "retryable": True, "reason": message}

    logger.info("Credited %s to user %s for confirmed payment %s", amount, user_id, pi_id)
    return {"credited": True, "amount": str(amount), "reference": reference}


@router.post("/webhook/stripe", include_in_schema=True)
async def stripe_webhook(request: Request):
    """
    Stripe webhook receiver — production client with signature verification.

    This endpoint is intentionally unauthenticated: Stripe calls it directly
    using HTTPS + HMAC-SHA256 signature (stripe-signature header).
    Signature verification is enforced via STRIPE_WEBHOOK_SECRET.
    In production, a missing STRIPE_WEBHOOK_SECRET raises RuntimeError at
    startup (see monetization/stripe_live.py verify_webhook).

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
    try:
        event = client.verify_webhook(payload, sig)
    except RuntimeError as exc:
        # Misconfiguration (e.g. missing STRIPE_WEBHOOK_SECRET in production).
        logger.critical("Stripe webhook misconfiguration: %s", exc)
        raise HTTPException(status_code=500, detail="Webhook endpoint misconfigured — check server logs") from exc

    if event is None:
        raise HTTPException(status_code=400, detail="Invalid Stripe webhook signature")

    result = client.handle_webhook_event(event)

    # A confirmed payment credits the depositor's wallet — ADR 0021.
    #
    # Done here rather than inside `handle_webhook_event` so the Stripe client
    # stays a Stripe client and does not grow knowledge of this platform's
    # ledger. It runs AFTER signature verification, never on an unverified body.
    if event.get("type") == "payment_intent.succeeded":
        credit = _credit_confirmed_deposit(event.get("data", {}).get("object", {}) or {})
        if credit.get("retryable"):
            # Tell Stripe to deliver again. The money has been taken and is not
            # yet recorded, so acknowledging this delivery would lose it
            # silently — at-least-once delivery is the only thing that recovers
            # it. The credit path is idempotent, so a redelivery that arrives
            # after the problem clears cannot double-credit.
            logger.critical(
                "Stripe webhook %s: the deposit could not be credited (%s) — returning 503 so it is redelivered",
                event.get("id", "<no id>"),
                credit.get("reason"),
            )
            raise HTTPException(
                status_code=503,
                detail="Deposit ledger temporarily unavailable; please redeliver this event",
            )
        if isinstance(result, dict):
            result = {**result, "wallet_credit": credit}

    # Also forward to legacy subscription manager for backward compat
    try:
        mgr = _get_subscription_manager()
        mgr.handle_stripe_webhook(payload, sig)
    except Exception as _exc:
        logger.debug("Suppressed exception: %s", _exc)

    logger.info(
        "Stripe webhook processed: event_type=%s result_status=%s",
        event.get("type"),
        result.get("status") if isinstance(result, dict) else "ok",
    )
    return {"received": True}


@router.get("/stripe/config", dependencies=[Depends(require_payments_configured)])
async def stripe_config():
    """
    Return safe Stripe configuration for the frontend (no secret keys).
    Used by the checkout page to initialise Stripe.js.
    """
    from monetization.stripe_live import get_stripe_client

    return get_stripe_client().get_config()


class CreatePaymentIntentRequest(BaseModel):
    # Defensive bounds on the charge amount. This route does not grant a plan —
    # the Stripe checkout.session webhook does that — so the amount is not a
    # pricing hole, but it was previously unbounded in both directions.
    amount_usd: float = Field(..., gt=0, le=float(os.getenv("MAX_CHECKOUT_AMOUNT_USD", "1_000_000")))
    currency: str = "USD"
    description: str = "HopeFX subscription"
    metadata: dict | None = None
    user_ip: str | None = None
    idempotency_key: str | None = None


@router.post("/stripe/payment-intent", dependencies=[Depends(require_payments_configured)])
async def create_payment_intent(
    body: CreatePaymentIntentRequest,
    request: Request,
    user: TokenPayload = Depends(get_current_user),
):
    """
    Create a Stripe PaymentIntent for the authenticated user.

    Supported currencies: USD, EUR, GBP, AED, NGN, JPY, CHF, CAD, AUD, SGD.
    Returns client_secret for frontend Stripe.js confirmation.
    """
    from monetization.stripe_live import get_stripe_client

    client = get_stripe_client()
    # Derive customer_id from the authenticated user — never accept it from the request body.
    customer_id = client.get_or_create_customer(user.sub, getattr(user, "email", None))
    user_ip = body.user_ip or request.client.host if request.client else None
    user_agent = request.headers.get("user-agent", "")

    # Idempotency: if the client did not supply a key, derive one from the
    # stable tuple (user_id, amount, currency) so that retries within the
    # same billing cycle do not create duplicate PaymentIntents.
    # The key is scoped to the user so different users with the same amount
    # never collide.
    effective_idempotency_key = (
        body.idempotency_key or hashlib.sha256(f"{user.sub}:{body.amount_usd}:{body.currency}".encode()).hexdigest()
    )

    result = client.create_payment_intent(
        customer_id=customer_id,
        amount_usd=Decimal(str(body.amount_usd)),
        currency=body.currency,
        description=body.description,
        metadata=body.metadata,
        user_ip=user_ip,
        user_agent=user_agent,
        idempotency_key=effective_idempotency_key,
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
    # /signup is not a route — the SPA registers /register. A link to /signup hits
    # the catch-all, redirects to /login, and the ref code is lost, so the referral
    # is never attributed.
    ref_url = f"{base_url}/register?ref={affiliate.code}"

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
    """Body for POST /auth/activate-free-tier.

    `user_id` is deliberately absent: it was client-supplied on an
    UNAUTHENTICATED route that both creates subscriptions and attributes
    affiliate referrals, so a caller could farm commissions against any user id
    they could enumerate. The account is now taken from the bearer token, which
    is what every other route in this file already does.
    """

    ref_code: str | None = None  # optional referral code from signup URL


_TRIAL_DAYS: int = int(os.getenv("NEW_USER_TRIAL_DAYS", "14"))


@router.post("/auth/activate-free-tier", status_code=status.HTTP_201_CREATED)
async def activate_free_tier(
    body: FreeTierBody,
    user: TokenPayload = Depends(get_current_user),
):
    """
    Called immediately after successful registration.

    Grants a 14-day Starter trial (configurable via NEW_USER_TRIAL_DAYS env var)
    so new users can explore journal, performance, alerts, and wallet without
    hitting upgrade walls on their first login.  After the trial expires the
    account reverts to the Free tier automatically.

    - Creates a STARTER trial subscription (no credit card required)
    - Tracks referral if ref_code is present
    - Returns tier info shown in the post-signup banner
    """
    from monetization.subscription import SubscriptionStatus, SubscriptionTier

    mgr = _get_subscription_manager()

    existing = mgr.get_user_subscription(user.sub)
    if existing:
        tier_val = existing.tier.value if hasattr(existing.tier, "value") else str(existing.tier)
        return {
            "tier": tier_val,
            "trial": existing.status == SubscriptionStatus.TRIAL if hasattr(existing, "status") else False,
            "message": "Subscription already active.",
            "features": ["paper_trading", "journal", "performance", "alerts"],
        }

    # Create a STARTER trial — gives access to journal, performance, alerts, wallet
    # without requiring a credit card.  Reverts to FREE after _TRIAL_DAYS.
    sub = mgr.create_subscription(
        user.sub,
        SubscriptionTier.STARTER,
        duration_days=_TRIAL_DAYS,
    )
    # Mark as TRIAL so the billing page shows the correct status badge.
    #
    # This bare assignment IS the write: the manager keeps subscriptions in a
    # module-level dict holding this same object, and there is no
    # save_subscription/update_subscription to call.
    #
    # It is therefore not durable. User.plan (database/user_models.py) is the only
    # persisted record of a plan and it has no concept of a trial, so after a
    # restart a trial reads as whatever `plan` says, with no expiry. Making trials
    # genuinely expire needs a real subscriptions table.
    sub.status = SubscriptionStatus.TRIAL

    if body.ref_code:
        try:
            aff_mgr = _get_affiliate_manager()
            aff_mgr.create_referral(
                affiliate_code=body.ref_code,
                referred_user_id=user.sub,
            )
        except Exception as exc:
            logger.debug("Referral tracking skipped: %s", exc)

    return {
        "tier": "starter",
        "trial": True,
        "trial_days": _TRIAL_DAYS,
        "message": (f"Welcome! You have a {_TRIAL_DAYS}-day free trial of the Starter plan. No credit card required."),
        "features": ["paper_trading", "journal", "performance", "alerts", "wallet"],
        "upgrade_url": "/pricing",
    }


# ─────────────────────────────────────────────────────────────────────────────
# Task 28 — Flutterwave Checkout
# ─────────────────────────────────────────────────────────────────────────────


class FlutterwaveInitBody(BaseModel):
    """Body for POST /payments/flutterwave/init.

    `amount` is deliberately absent: the client set its own price and `plan` was
    accepted, echoed back, and never used to validate it. The charge is now
    derived from `plan` against the catalogue.
    """

    currency: str = Field("USD", max_length=3)
    plan: str = Field("professional", description="Subscription plan name")


class FlutterwaveVerifyBody(BaseModel):
    tx_ref: str
    # Which plan the transaction was for — needed to grant it on verify. Validated
    # against the catalogue before anything is granted. Once flutterwave_init
    # persists a payment row this should be read back from the stored tx_ref
    # instead of being supplied by the client.
    plan: str = Field("professional", description="Plan purchased")


@router.post("/payments/flutterwave/init", dependencies=[Depends(require_payments_configured)])
async def flutterwave_init(
    body: FlutterwaveInitBody,
    user: TokenPayload = Depends(get_current_user),
):
    """
    Initialise a Flutterwave payment session.

    Shown as primary checkout option for users in West/Central Africa
    (detected by IP geolocation on the frontend).

    Idempotency: tx_ref is derived from (user_id, plan, amount, currency) so
    that retrying the same checkout does not create a second payment session.
    The client should pass the returned tx_ref to /verify after payment.
    """
    # Server-derived price — never a client-supplied amount.
    try:
        amount = resolve_plan_price_usd(body.plan)
    except UnknownPlanError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None

    # Deterministic tx_ref — same user+plan+amount+currency always maps to the
    # same reference, so a network retry cannot create a duplicate charge.
    idempotent_tx_ref = (
        "FLW-" + hashlib.sha256(f"{user.sub}:{body.plan}:{amount}:{body.currency}".encode()).hexdigest()[:24]
    )

    try:
        flw = _get_flutterwave()
        result = flw.initialize_payment(
            user_id=user.sub,
            amount=Decimal(str(amount)),
            currency=body.currency,
            tx_ref=idempotent_tx_ref,
        )
        return {
            "tx_ref": result.get("tx_ref", idempotent_tx_ref),
            "payment_link": result["payment_link"],
            "amount": result["amount"],
            "currency": result["currency"],
            "fee": result.get("fee", 0),
            "plan": body.plan,
        }
    except Exception as exc:
        logger.error("Flutterwave init error: %s", exc)
        raise HTTPException(status_code=500, detail="Payment init failed — check server logs") from exc


@router.post("/payments/flutterwave/verify", dependencies=[Depends(require_payments_configured)])
async def flutterwave_verify(
    body: FlutterwaveVerifyBody,
    user: TokenPayload = Depends(get_current_user),
):
    """
    Verify a Flutterwave transaction and activate the subscription.

    Idempotency: if this tx_ref has already been verified and the subscription
    activated, return the cached result immediately without calling Flutterwave
    again or re-activating the subscription.  This prevents double-activation
    when the client retries on a network timeout.
    """
    # Check whether this tx_ref was already processed for this user.
    # Uses a lightweight DB/cache key: flw_verified:{user_id}:{tx_ref}
    _verified_cache_key = f"flw_verified:{user.sub}:{body.tx_ref}"
    try:
        from api.db_store import db_get, db_set  # type: ignore[import]

        cached = db_get(_verified_cache_key)
        if cached and cached.get("status") == "verified":
            logger.info(
                "Flutterwave verify: tx_ref=%s already processed for user=%s — returning cached result",
                body.tx_ref,
                user.sub,
            )
            return {"verified": True, "tx_ref": body.tx_ref, "status": "verified", "idempotent": True}
    except Exception as _cache_exc:
        logger.debug("flutterwave_verify: cache lookup failed (non-fatal): %s", _cache_exc)
        db_set = None  # type: ignore[assignment]

    try:
        flw = _get_flutterwave()
        result = flw.verify_transaction(body.tx_ref)
        if result.get("status") == "verified":
            # Persist the verified state so retries are idempotent
            try:
                if db_set is not None:
                    db_set(
                        _verified_cache_key,
                        {"status": "verified", "tx_ref": body.tx_ref, "user_id": user.sub},
                        changed_by=user.sub,
                    )
            except Exception as _persist_exc:
                logger.warning("flutterwave_verify: failed to persist idempotency record: %s", _persist_exc)

            # Deliver what was paid for. This function's docstring has always
            # claimed it activates the subscription; until now it verified,
            # cached an idempotency record, and returned. The customer paid and
            # stayed on Free.
            #
            # activate_paid_plan never raises: the idempotency record above means
            # a 5xx here would be retried, short-circuited, and the grant lost.
            activated = activate_paid_plan(
                user.sub,
                body.plan,
                source="flutterwave",
                reference=body.tx_ref,
            )
            return {
                "verified": True,
                "tx_ref": body.tx_ref,
                "status": "verified",
                "subscription_activated": activated,
            }
        return {
            "verified": False,
            "tx_ref": body.tx_ref,
            "status": result.get("status", "unknown"),
        }
    except Exception as exc:
        logger.error("Flutterwave verify error: %s", exc)
        raise HTTPException(status_code=500, detail="Verification failed — check server logs") from exc


@router.get("/payments/flutterwave/status", dependencies=[Depends(require_payments_configured)])
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
async def get_balance(user: TokenPayload = Depends(require_plan("starter"))):
    """
    Return the balance this platform can show, and say where it came from.

    Two sources answer this, and NEITHER is the wallet ledger: the **broker**
    account, then the subscription manager's `wallet_balance`, which overwrites
    it when present. Meanwhile ADR 0021 makes `wallet_transactions` the ledger a
    withdrawal is refused against. So the number a user is shown and the number
    a withdrawal is checked against come from different places.

    This function does not decide which is authoritative — that is
    reconciliation, and it is the owner's call (`BALANCE-SOURCE-SPLIT`). It
    makes the disagreement visible instead of hiding it, and reports the ledger
    alongside so the two can be compared at all.

    The docstring here used to say the subscription manager was read "when
    available" and the broker was the fallback. The code does the opposite, and
    has since it was written.

    `balance_known` exists because a failed lookup used to be indistinguishable
    from an empty account: both sources were wrapped in
    `except Exception: logger.debug(...)`, DEBUG is off in production, and a user
    whose broker call timed out was shown `0.00` in a response byte-identical to
    a real zero.
    """
    from decimal import ROUND_HALF_UP, Decimal

    def _account_field(account, name: str) -> float:
        """Read a field from a broker account that may be an object OR a mapping.

        This was `getattr(account, name, 0) or account.get(name, 0)`, and the
        `or` conflated "the attribute is missing" with "the attribute is ZERO".
        A broker reporting a genuine zero balance fell through to the mapping
        branch, and an object-style account has no `.get`, so it raised
        AttributeError — into an `except` that logged at DEBUG. A real zero
        balance crashed the lookup and nobody could see why.
        """
        value = getattr(account, name, None)
        if value is None and hasattr(account, "get"):
            value = account.get(name, 0)
        return float(value if value is not None else 0)

    def _cents(value) -> float:
        """Quantize to cents, HALF_UP.

        `round(x, 2)` is banker's rounding: `round(2.675, 2)` is 2.67. On a
        displayed balance that is a cent, always in the same direction.
        """
        return float(Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))

    balance = 0.0
    frozen = 0.0
    pending = 0.0
    source: str | None = None
    failures: list[str] = []

    # The broker account first — most accurate for paper accounts.
    try:
        from core.app_state import app_state

        broker = getattr(app_state, "broker", None)
        if broker is not None:
            import asyncio

            account = await asyncio.wait_for(broker.get_account(), timeout=3.0)
            if account:
                balance = _account_field(account, "balance")
                frozen = _account_field(account, "margin_used")
                source = "broker"
        else:
            failures.append("broker: not configured")
    except Exception as exc:
        # WARNING, not DEBUG. This is the difference between an operator seeing
        # why a user was shown zero and an operator seeing nothing at all.
        logger.warning("Balance: broker lookup failed for user=%s: %s", user.sub, exc)
        failures.append(f"broker: {exc}")

    # The subscription manager OVERWRITES the broker when it has a figure.
    try:
        mgr = _get_subscription_manager()
        sub = mgr.get_user_subscription(user.sub)
        if sub and hasattr(sub, "wallet_balance"):
            balance = float(sub.wallet_balance)
            source = "subscription_manager"
    except Exception as exc:
        logger.warning("Balance: subscription lookup failed for user=%s: %s", user.sub, exc)
        failures.append(f"subscription_manager: {exc}")

    # The ledger a withdrawal is actually refused against, reported alongside so
    # the split is measurable rather than merely documented. `None` means "no
    # wallet", which is not the same as a wallet holding nothing.
    ledger_balance: float | None = None
    try:
        from core.app_state import app_state as _app_state

        wallet_manager = getattr(_app_state, "wallet_manager", None)
        if wallet_manager is not None and wallet_manager.get_wallet(user.sub) is not None:
            ledger_balance = _cents(wallet_manager.get_balance(user.sub)["total_balance"])
    except Exception as exc:
        logger.warning("Balance: wallet ledger lookup failed for user=%s: %s", user.sub, exc)
        failures.append(f"wallet_ledger: {exc}")

    if source is None:
        logger.warning(
            "Balance: no source could answer for user=%s (%s) — reporting balance_known=false "
            "rather than a zero that looks like an empty account",
            user.sub,
            "; ".join(failures) or "no reason recorded",
        )

    shown = _cents(balance)
    return {
        "balance": shown,
        "frozen": _cents(frozen),
        "pending": _cents(pending),
        "currency": "USD",
        # Everything below is additive. Existing callers keep reading `balance`.
        "balance_known": source is not None,
        "source": source,
        "ledger_balance": ledger_balance,
        "sources_agree": None if (ledger_balance is None or source is None) else ledger_balance == shown,
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
                            if isinstance(c.get("created"), int | float)
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
        from datetime import timedelta

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

    # Do not report success for work that was never queued. There is no review
    # queue behind this branch — returning ok:true left an operator believing a
    # refund was in flight when nothing existed anywhere.
    logger.error(
        "process_refund: payment %s not found in processor and Stripe not configured — NO refund issued (reason=%s)",
        payment_id,
        reason,
    )
    raise HTTPException(
        status_code=422,
        detail=(
            f"Payment {payment_id} was not found in the payment processor and Stripe is not "
            "configured. No refund has been issued — this must be handled manually in the "
            "processor dashboard."
        ),
    )


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
    user: TokenPayload = Depends(require_plan("starter")),
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


# ─────────────────────────────────────────────────────────────────────────────
# Elite Tier 5 — Dedicated Support, Custom Development, Account Manager
# ─────────────────────────────────────────────────────────────────────────────

import uuid as _uuid


def _assert_elite(user: TokenPayload) -> None:
    """Raise 403 unless the user holds an Elite subscription (or is admin/superadmin)."""
    # Admins and superadmins bypass the plan gate
    role = getattr(user, "role", "user")
    if role in ("admin", "superadmin"):
        return

    try:
        mgr = _get_subscription_manager()
        sub = mgr.get_user_subscription(user.sub)
        tier = ""
        if sub is not None:
            tier = sub.tier.value if hasattr(sub.tier, "value") else str(sub.tier)
        if tier.lower() != "elite":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Elite subscription required for this feature.",
            )
    except HTTPException:
        raise
    except Exception as exc:
        logger.warning("_assert_elite: subscription check failed: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Elite subscription required for this feature.",
        ) from exc


# ── Account Manager ───────────────────────────────────────────────────────────

# Default account manager contact — overridden by ELITE_AM_* env vars in production.
_DEFAULT_ACCOUNT_MANAGER = {
    "name": os.getenv("ELITE_AM_NAME", "HopeFX Elite Support"),
    "email": os.getenv("ELITE_AM_EMAIL", "elite@hopefx.io"),
    "phone": os.getenv("ELITE_AM_PHONE", "+1-800-HOPEFX-1"),
    "calendar_url": os.getenv("ELITE_AM_CALENDAR_URL", "https://calendly.com/hopefx-elite"),
    "slack_channel": os.getenv("ELITE_AM_SLACK", "#elite-support"),
    "response_sla": {
        "urgent": "1 hour",
        "high": "4 hours",
        "normal": "24 hours",
    },
    "support_hours": "24/7 for urgent; Mon–Fri 08:00–20:00 UTC for normal",
}


@router.get("/elite/account-manager", summary="Get dedicated account manager contact (Elite)")
async def get_account_manager(user: TokenPayload = Depends(require_plan("elite"))):
    """
    Return the dedicated account manager details for the authenticated Elite user.

    Contact details are configured via ELITE_AM_* environment variables.
    """
    _assert_elite(user)
    return _DEFAULT_ACCOUNT_MANAGER


# ── Support Tickets ───────────────────────────────────────────────────────────


class SupportTicketRequest(BaseModel):
    subject: str = Field(..., min_length=5, max_length=200)
    message: str = Field(..., min_length=20, max_length=5000)
    priority: str = Field("high", pattern="^(normal|high|urgent)$")
    category: str = Field("general", pattern="^(general|technical|billing|strategy|api|onboarding)$")


@router.post("/elite/support/ticket", summary="Submit a dedicated support ticket (Elite)")
async def create_support_ticket(
    body: SupportTicketRequest,
    user: TokenPayload = Depends(require_plan("elite")),
):
    """
    Create a dedicated support ticket for an Elite subscriber.

    Tickets are persisted in the DB store under the key
    ``elite:support:{ticket_id}`` and can be retrieved via
    GET /api/billing/elite/support/tickets.
    """
    _assert_elite(user)

    from api.db_store import db_set

    ticket_id = f"ELITE-{_uuid.uuid4().hex[:10].upper()}"
    now = datetime.now(tz=UTC).isoformat()

    ticket = {
        "ticket_id": ticket_id,
        "user_id": user.sub,
        "subject": body.subject,
        "message": body.message,
        "priority": body.priority,
        "category": body.category,
        "status": "open",
        "created_at": now,
        "updated_at": now,
    }

    db_set(f"elite:support:{ticket_id}", ticket, changed_by=user.sub)

    # SLA response times by priority
    sla_map = {"urgent": "1 hour", "high": "4 hours", "normal": "24 hours"}

    return {
        "ticket_id": ticket_id,
        "status": "open",
        "priority": body.priority,
        "sla": sla_map.get(body.priority, "24 hours"),
        "message": (
            f"Ticket {ticket_id} submitted. "
            f"Your dedicated account manager will respond within {sla_map.get(body.priority, '24 hours')}."
        ),
        "contact_email": _DEFAULT_ACCOUNT_MANAGER["email"],
    }


@router.get("/elite/support/tickets", summary="List support tickets for the authenticated Elite user")
async def list_support_tickets(
    limit: int = 50,
    offset: int = 0,
    user: TokenPayload = Depends(require_plan("elite")),
):
    """
    Return all support tickets submitted by the authenticated Elite user.

    Tickets are stored in the DB store and filtered by user_id.
    """
    _assert_elite(user)

    from api.db_store import db_get, db_keys_prefix

    keys = db_keys_prefix("elite:support:ELITE-")
    all_tickets = [db_get(k) for k in keys]
    user_tickets = [t for t in all_tickets if isinstance(t, dict) and t.get("user_id") == user.sub]
    # Sort newest first
    user_tickets.sort(key=lambda t: t.get("created_at", ""), reverse=True)
    page = user_tickets[offset : offset + limit]

    return {
        "tickets": page,
        "total": len(user_tickets),
        "limit": limit,
        "offset": offset,
    }


@router.get(
    "/elite/support/tickets/{ticket_id}/timeline",
    summary="Event timeline for a specific Elite support ticket",
)
async def get_ticket_timeline(
    ticket_id: str,
    user: TokenPayload = Depends(require_plan("elite")),
):
    """
    Return the event timeline for a specific Elite support ticket.
    Timeline events include: created, status changes, replies, and resolution.
    """
    _assert_elite(user)

    from api.db_store import db_get

    ticket = db_get(f"elite:support:{ticket_id}")
    if not ticket or not isinstance(ticket, dict):
        raise HTTPException(status_code=404, detail="Ticket not found") from None
    if ticket.get("user_id") != user.sub:
        raise HTTPException(status_code=403, detail="Access denied") from None

    # Build timeline from ticket fields — real events stored in ticket dict
    events: list[dict] = []
    events.append(
        {
            "event": "created",
            "timestamp": ticket.get("created_at"),
            "actor": "user",
            "detail": f"Ticket {ticket_id} submitted with priority '{ticket.get('priority', 'normal')}'",
        }
    )

    # Append any stored reply/status-change events
    for ev in ticket.get("timeline_events", []):
        events.append(ev)

    # If ticket is resolved, add resolution event
    if ticket.get("status") == "resolved" and ticket.get("resolved_at"):
        events.append(
            {
                "event": "resolved",
                "timestamp": ticket.get("resolved_at"),
                "actor": "support",
                "detail": ticket.get("resolution_note", "Ticket resolved"),
            }
        )

    events.sort(key=lambda e: e.get("timestamp") or "")

    return {
        "ticket_id": ticket_id,
        "status": ticket.get("status", "open"),
        "timeline": events,
        "total_events": len(events),
    }


# ── Custom Development Requests ───────────────────────────────────────────────


class CustomDevRequest(BaseModel):
    title: str = Field(..., min_length=5, max_length=200)
    description: str = Field(..., min_length=50, max_length=10000)
    request_type: str = Field(
        "strategy",
        pattern="^(strategy|indicator|integration|dashboard|api|other)$",
    )
    target_symbols: list[str] = Field(default_factory=list)
    target_timeframes: list[str] = Field(default_factory=list)
    budget_usd: float | None = Field(None, ge=0)
    deadline: str | None = None  # ISO date string YYYY-MM-DD


@router.post("/elite/custom-dev/request", summary="Submit a custom development request (Elite)")
async def submit_custom_dev_request(
    body: CustomDevRequest,
    user: TokenPayload = Depends(require_plan("elite")),
):
    """
    Submit a bespoke development request (strategy, indicator, integration, etc.)
    for an Elite subscriber.

    Requests are persisted under ``elite:custom_dev:{request_id}`` and reviewed
    by the HopeFX development team within 2 business days.
    """
    _assert_elite(user)

    from api.db_store import db_set

    request_id = f"CDR-{_uuid.uuid4().hex[:10].upper()}"
    now = datetime.now(tz=UTC).isoformat()

    dev_request = {
        "request_id": request_id,
        "user_id": user.sub,
        "title": body.title,
        "description": body.description,
        "request_type": body.request_type,
        "target_symbols": body.target_symbols,
        "target_timeframes": body.target_timeframes,
        "budget_usd": body.budget_usd,
        "deadline": body.deadline,
        "status": "submitted",
        "created_at": now,
        "updated_at": now,
    }

    db_set(f"elite:custom_dev:{request_id}", dev_request, changed_by=user.sub)

    return {
        "request_id": request_id,
        "status": "submitted",
        "message": (
            f"Custom development request {request_id} submitted. "
            "Our team will provide a scoping estimate within 2 business days."
        ),
        "contact_email": _DEFAULT_ACCOUNT_MANAGER["email"],
    }


@router.get("/elite/custom-dev/requests", summary="List custom development requests for the authenticated Elite user")
async def list_custom_dev_requests(
    limit: int = 50,
    offset: int = 0,
    user: TokenPayload = Depends(require_plan("elite")),
):
    """
    Return all custom development requests submitted by the authenticated Elite user.
    """
    _assert_elite(user)

    from api.db_store import db_get, db_keys_prefix

    keys = db_keys_prefix("elite:custom_dev:CDR-")
    all_reqs = [db_get(k) for k in keys]
    user_reqs = [r for r in all_reqs if isinstance(r, dict) and r.get("user_id") == user.sub]
    user_reqs.sort(key=lambda r: r.get("created_at", ""), reverse=True)
    page = user_reqs[offset : offset + limit]

    return {
        "requests": page,
        "total": len(user_reqs),
        "limit": limit,
        "offset": offset,
    }


# ── Subscription management ───────────────────────────────────────────────────


@router.post("/subscription/cancel", summary="Cancel active subscription")
async def cancel_subscription(user: TokenPayload = Depends(get_current_user)):
    try:
        from api.db_store import db_get, db_set

        sub = db_get(f"subscription:{user.sub}") or {}
        sub["cancel_at_period_end"] = True
        sub["cancelled_at"] = datetime.now(UTC).isoformat()
        db_set(f"subscription:{user.sub}", sub, changed_by=user.sub)
    except Exception as exc:
        logger.warning("cancel_subscription: %s", exc)
    return {"success": True, "cancel_at_period_end": True, "message": "Subscription will cancel at period end"}


@router.post("/subscription/resume", summary="Resume cancelled subscription")
async def resume_subscription(user: TokenPayload = Depends(get_current_user)):
    try:
        from api.db_store import db_get, db_set

        sub = db_get(f"subscription:{user.sub}") or {}
        sub["cancel_at_period_end"] = False
        sub["resumed_at"] = datetime.now(UTC).isoformat()
        db_set(f"subscription:{user.sub}", sub, changed_by=user.sub)
    except Exception as exc:
        logger.warning("resume_subscription: %s", exc)
    return {"success": True, "cancel_at_period_end": False, "message": "Subscription resumed"}


@router.post("/subscription/change", summary="Change subscription plan")
async def change_subscription_plan(body: dict, user: TokenPayload = Depends(get_current_user)):
    plan = body.get("plan", "")
    # Derived, not transcribed. The other hand-written copy of this set — in
    # api/superadmin/users.py — had drifted and was missing "elite", so the same
    # plan was valid here and rejected there.
    from monetization.pricing import SubscriptionTier

    valid_plans = {t.value for t in SubscriptionTier}
    if plan not in valid_plans:
        raise HTTPException(status_code=400, detail=f"Invalid plan. Must be one of: {', '.join(sorted(valid_plans))}")
    try:
        from api.db_store import db_get, db_set

        sub = db_get(f"subscription:{user.sub}") or {}
        old_plan = sub.get("plan", "free")
        sub["plan"] = plan
        sub["plan_changed_at"] = datetime.now(UTC).isoformat()
        db_set(f"subscription:{user.sub}", sub, changed_by=user.sub)
        return {"success": True, "old_plan": old_plan, "new_plan": plan}
    except Exception as exc:
        logger.warning("change_subscription_plan: %s", exc)
        return {"success": True, "old_plan": "unknown", "new_plan": plan}


@router.post("/payment-methods/{payment_method_id}/default", summary="Set default payment method")
async def set_default_payment_method(
    payment_method_id: str,
    user: TokenPayload = Depends(get_current_user),
):
    try:
        from api.db_store import db_get, db_set

        methods = db_get(f"payment_methods:{user.sub}") or []
        for m in methods:
            m["is_default"] = m.get("id") == payment_method_id
        db_set(f"payment_methods:{user.sub}", methods, changed_by=user.sub)
    except Exception as exc:
        logger.warning("set_default_payment_method: %s", exc)
    return {"success": True, "default_method_id": payment_method_id}


@router.get("/invoices", summary="List invoices")
async def list_invoices(
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    user: TokenPayload = Depends(get_current_user),
):
    try:
        from api.db_store import db_get

        invoices = db_get(f"invoices:{user.sub}") or []
        invoices.sort(key=lambda x: x.get("created_at", ""), reverse=True)
        page = invoices[offset : offset + limit]
        return {"invoices": page, "total": len(invoices), "limit": limit, "offset": offset}
    except Exception:
        return {"invoices": [], "total": 0, "limit": limit, "offset": offset}


@router.get("/invoices/{invoice_id}", summary="Get invoice detail")
async def get_invoice(invoice_id: str, user: TokenPayload = Depends(get_current_user)):
    try:
        from api.db_store import db_get

        invoices = db_get(f"invoices:{user.sub}") or []
        inv = next((i for i in invoices if i.get("id") == invoice_id), None)
        if not inv:
            raise HTTPException(status_code=404, detail="Invoice not found") from None
        return inv
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=404, detail="Invoice not found") from None


# ── Crypto checkout (/api/billing/crypto/*) ───────────────────────────────────
# Delegates to /api/payments/crypto/* under the hood; exposed here so the
# frontend cryptoCheckoutApi can use a single /billing prefix.


@router.get(
    "/crypto/rates",
    summary="Live crypto exchange rates for checkout",
    dependencies=[Depends(require_payments_configured)],
)
async def crypto_rates(user: TokenPayload = Depends(get_current_user)):
    """Return live BTC/ETH/USDT rates in USD for the crypto checkout flow."""
    try:
        import aiohttp

        async with (
            aiohttp.ClientSession() as session,
            session.get(
                "https://api.coingecko.com/api/v3/simple/price",
                params={"ids": "bitcoin,ethereum,tether", "vs_currencies": "usd"},
                timeout=aiohttp.ClientTimeout(total=5),
            ) as resp,
        ):
            data = await resp.json()
            return {
                "BTC": {"rate": data.get("bitcoin", {}).get("usd", 0), "symbol": "BTC"},
                "ETH": {"rate": data.get("ethereum", {}).get("usd", 0), "symbol": "ETH"},
                "USDT": {"rate": data.get("tether", {}).get("usd", 1), "symbol": "USDT"},
                "timestamp": datetime.now(UTC).isoformat(),
            }
    except Exception as exc:
        logger.debug("crypto rates fetch error: %s", exc)
        # Fallback approximate rates
        return {
            "BTC": {"rate": 65000.0, "symbol": "BTC"},
            "ETH": {"rate": 3500.0, "symbol": "ETH"},
            "USDT": {"rate": 1.0, "symbol": "USDT"},
            "timestamp": datetime.now(UTC).isoformat(),
            "source": "fallback",
        }


@router.post(
    "/crypto/order", summary="Create a crypto payment order", dependencies=[Depends(require_payments_configured)]
)
async def create_crypto_order(
    payload: dict,
    user: TokenPayload = Depends(get_current_user),
):
    """Create a crypto payment order and return a deposit address."""
    import uuid as _uuid

    currency = str(payload.get("currency", "BTC")).upper()
    amount_usd = float(payload.get("amount_usd", 0))
    if amount_usd <= 0:
        raise HTTPException(status_code=400, detail="amount_usd must be positive") from None
    if currency not in ("BTC", "ETH", "USDT"):
        raise HTTPException(status_code=400, detail="Unsupported currency") from None

    order_id = str(_uuid.uuid4())
    # Delegate to payments router for address generation.
    #
    # This used to end with::
    #
    #     except Exception:
    #         address = f"hopefx_{currency.lower()}_{user.sub[:8]}"
    #
    # so a failure to derive an address produced the string
    # "hopefx_btc_a1b2c3d4", returned with HTTP 200 and rendered in the UI as a
    # deposit address beside a QR code. It was not a hypothetical branch:
    # BitcoinClient was calling a hdwallet API that has not existed since v3,
    # which requirements.txt has pinned throughout, so *every* BTC deposit
    # request took it (F267).
    #
    # There is no fallback value for a deposit address. Anything returned here
    # is somewhere a user sends money that cannot be retrieved, so the only
    # honest failure is to not return one.
    try:
        from api.payments import _generate_address

        address = _generate_address(currency, user.sub, "mainnet")
    except Exception as exc:
        logger.error("Deposit address generation failed for %s/%s: %s", currency, user.sub, exc)
        raise HTTPException(
            status_code=503,
            detail=f"{currency} deposit addresses are temporarily unavailable. No funds should be sent.",
        ) from exc

    order = {
        "order_id": order_id,
        "user_id": user.sub,
        "currency": currency,
        "amount_usd": amount_usd,
        "address": address,
        "status": "pending",
        "created_at": datetime.now(UTC).isoformat(),
        "expires_at": None,
    }

    # Fail closed, mirroring api/payments.py::generate_deposit_address (§A11
    # item 1). This used to be::
    #
    #     try:
    #         db_set(...)
    #         db_set(...)
    #     except Exception:
    #         pass
    #
    # but db_set() never raises — it swallows every exception internally and
    # returns False on failure. That False was discarded, so a save that failed
    # (DB unavailable, insert error) still returned 200 with the address and
    # amount, for an order GET /crypto/order/{order_id} can never find.
    #
    # The address was derived above via _generate_address (the same helper
    # payments.py uses). For ETH/USDT it durably advances the shared HD
    # derivation counter; that index is NOT rolled back here, for the same
    # reason it isn't there: rolling back could re-issue an index a concurrent
    # request has since taken. The address is simply never returned.
    from api.db_store import db_get, db_set

    try:
        orders = db_get(f"crypto_orders:{user.sub}") or []
        orders.append(order)
    except (TypeError, AttributeError) as exc:
        # A corrupted stored value (not a list) — the only way this block can
        # raise; db_get/db_set themselves catch and return None/False.
        logger.error(
            "Crypto order %s NOT persisted — crypto_orders:%s is not a list (%s). Refusing to issue it.",
            order_id,
            user.sub,
            exc,
        )
        raise HTTPException(
            status_code=503,
            detail="Order could not be recorded, so no deposit address was issued. Do not send funds; please try again shortly.",
        ) from exc

    list_saved = db_set(f"crypto_orders:{user.sub}", orders)
    order_saved = db_set(f"crypto_order:{order_id}", order)

    if not (list_saved and order_saved):
        logger.error(
            "Crypto order %s NOT persisted — db_set returned False (list_saved=%s, order_saved=%s). Refusing to issue it.",
            order_id,
            list_saved,
            order_saved,
        )
        raise HTTPException(
            status_code=503,
            detail="Order could not be recorded, so no deposit address was issued. Do not send funds; please try again shortly.",
        )

    return order


@router.get("/crypto/order/{order_id}", summary="Get crypto order status")
async def get_crypto_order(order_id: str, user: TokenPayload = Depends(get_current_user)):
    """Return the current status of a crypto payment order."""
    try:
        from api.db_store import db_get

        order = db_get(f"crypto_order:{order_id}")
        if not order or order.get("user_id") != user.sub:
            raise HTTPException(status_code=404, detail="Order not found") from None
        return order
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=404, detail="Order not found") from None


@router.post("/crypto/order/{order_id}/cancel", summary="Cancel a pending crypto order")
async def cancel_crypto_order(order_id: str, user: TokenPayload = Depends(get_current_user)):
    """Cancel a pending crypto payment order."""
    try:
        from api.db_store import db_get, db_set

        order = db_get(f"crypto_order:{order_id}")
        if not order or order.get("user_id") != user.sub:
            raise HTTPException(status_code=404, detail="Order not found") from None
        if order.get("status") != "pending":
            raise HTTPException(status_code=400, detail="Only pending orders can be cancelled") from None
        order["status"] = "cancelled"
        db_set(f"crypto_order:{order_id}", order)
        return {"ok": True, "order_id": order_id, "status": "cancelled"}
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=500, detail="Failed to cancel order") from None
