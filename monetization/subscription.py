# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
monetization/subscription.py
=============================
Stripe-backed subscription management with license validation and FastAPI router.

Tiers:
  FREE         — paper trading only, no RL agent, no live execution
  PROFESSIONAL — live trading + RL agent + all ML features
  ENTERPRISE   — everything + white-label + dedicated support

Key components:
  LicenseValidator       — validates API keys against Stripe subscription state
  SubscriptionManager    — creates / renews / cancels subscriptions via Stripe
  create_subscription_router() — mounts /subscribe, /webhook, /license endpoints

Dependencies:
    pip install stripe fastapi pydantic
"""

import hashlib
import hmac
import logging
import os
import uuid
from datetime import datetime, timedelta, timezone

UTC = timezone.utc
from typing import Any
from enum import Enum

from .pricing import SubscriptionTier, pricing_manager

# ---------------------------------------------------------------------------
# Optional Stripe import
# ---------------------------------------------------------------------------
try:
    import stripe as _stripe  # type: ignore

    _STRIPE_AVAILABLE = True
except ImportError:
    _stripe = None  # type: ignore
    _STRIPE_AVAILABLE = False
    logger_init = logging.getLogger(__name__)
    logger_init.warning("stripe package not installed — payment processing disabled. pip install stripe")

# ---------------------------------------------------------------------------
# Tier feature gates (mirrors pricing.py, adds RL/live flags)
# ---------------------------------------------------------------------------
_TIER_FEATURES: dict[SubscriptionTier, dict[str, Any]] = {
    SubscriptionTier.FREE: {
        "live_trading": False,
        "rl_agent": False,
        "ml_features": False,
        "max_strategies": 1,
        "api_access": False,
        "news_rag": False,
        "paper_trading": True,
    },
    SubscriptionTier.PROFESSIONAL: {
        "live_trading": True,
        "rl_agent": True,
        "ml_features": True,
        "max_strategies": 10,
        "api_access": True,
        "news_rag": True,
        "paper_trading": True,
    },
    SubscriptionTier.ENTERPRISE: {
        "live_trading": True,
        "rl_agent": True,
        "ml_features": True,
        "max_strategies": -1,
        "api_access": True,
        "news_rag": True,
        "paper_trading": True,
        "white_label": True,
        "dedicated_support": True,
    },
}

# Stripe Price IDs — override via environment variables
_STRIPE_PRICE_IDS: dict[SubscriptionTier, str] = {
    SubscriptionTier.PROFESSIONAL: os.getenv("STRIPE_PRICE_PROFESSIONAL", "price_professional"),
    SubscriptionTier.ENTERPRISE: os.getenv("STRIPE_PRICE_ENTERPRISE", "price_enterprise"),
}


logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# License key helpers
# ---------------------------------------------------------------------------


def _generate_license_key(user_id: str, tier: SubscriptionTier) -> str:
    """
    Deterministic, opaque license key: HOPEFX-<TIER>-<HEX16>.
    Derived from user_id + tier + server-side secret.
    """
    secret = os.getenv("LICENSE_SECRET", "hopefx-default-secret")
    payload = f"{user_id}:{tier.value}:{secret}"
    digest = hashlib.sha256(payload.encode()).hexdigest()[:16].upper()
    return f"HOPEFX-{tier.value.upper()[:3]}-{digest}"


def _verify_license_key(license_key: str, user_id: str, tier: SubscriptionTier) -> bool:
    """Constant-time comparison to prevent timing attacks."""
    expected = _generate_license_key(user_id, tier)
    return hmac.compare_digest(license_key, expected)


class SubscriptionStatus(str, Enum):
    """Subscription status enumeration"""

    ACTIVE = "active"
    CANCELLED = "cancelled"
    EXPIRED = "expired"
    SUSPENDED = "suspended"
    PENDING = "pending"
    TRIAL = "trial"


class Subscription:
    """User subscription model"""

    def __init__(
        self,
        subscription_id: str,
        user_id: str,
        tier: SubscriptionTier,
        status: SubscriptionStatus = SubscriptionStatus.PENDING,
        start_date: datetime | None = None,
        end_date: datetime | None = None,
        access_code: str | None = None,
        auto_renew: bool = True,
        stripe_subscription_id: str | None = None,
        stripe_customer_id: str | None = None,
        license_key: str | None = None,
    ):
        self.subscription_id = subscription_id
        self.user_id = user_id
        self.tier = tier
        self.status = status
        self.start_date = start_date or datetime.now(UTC)
        self.end_date = end_date or (self.start_date + timedelta(days=30))
        self.access_code = access_code
        self.auto_renew = auto_renew
        self.stripe_subscription_id = stripe_subscription_id
        self.stripe_customer_id = stripe_customer_id
        self.license_key = license_key or _generate_license_key(user_id, tier)
        self.created_at = datetime.now(UTC)
        self.updated_at = datetime.now(UTC)

    def is_active(self) -> bool:
        """Check if subscription is active"""
        if self.status not in (SubscriptionStatus.ACTIVE, SubscriptionStatus.TRIAL):
            return False
        now = datetime.now(UTC)
        return self.start_date <= now <= self.end_date

    def has_feature(self, feature: str) -> bool:
        """Return True if this subscription's tier includes `feature`."""
        if not self.is_active():
            return False
        return bool(_TIER_FEATURES.get(self.tier, {}).get(feature, False))

    def is_expired(self) -> bool:
        """Check if subscription is expired"""
        return datetime.now(UTC) > self.end_date

    def days_remaining(self) -> int:
        """Get days remaining in subscription"""
        if self.is_expired():
            return 0
        return (self.end_date - datetime.now(UTC)).days

    def renew(self, duration_days: int = 30) -> None:
        """Renew subscription"""
        if self.is_expired():
            self.start_date = datetime.now(UTC)
        self.end_date = datetime.now(UTC) + timedelta(days=duration_days)
        self.status = SubscriptionStatus.ACTIVE
        self.updated_at = datetime.now(UTC)
        logger.info(f"Subscription {self.subscription_id} renewed until {self.end_date}")

    def cancel(self) -> None:
        """Cancel subscription"""
        self.status = SubscriptionStatus.CANCELLED
        self.auto_renew = False
        self.updated_at = datetime.now(UTC)
        logger.info(f"Subscription {self.subscription_id} cancelled")

    def suspend(self) -> None:
        """Suspend subscription"""
        self.status = SubscriptionStatus.SUSPENDED
        self.updated_at = datetime.now(UTC)
        logger.info(f"Subscription {self.subscription_id} suspended")

    def reactivate(self) -> None:
        """Reactivate subscription"""
        if self.is_expired():
            self.renew()
        else:
            self.status = SubscriptionStatus.ACTIVE
        self.updated_at = datetime.now(UTC)
        logger.info(f"Subscription {self.subscription_id} reactivated")

    def to_dict(self) -> dict:
        """Convert to dictionary"""
        return {
            "subscription_id": self.subscription_id,
            "user_id": self.user_id,
            "tier": self.tier.value,
            "status": self.status.value,
            "start_date": self.start_date.isoformat(),
            "end_date": self.end_date.isoformat(),
            "access_code": self.access_code,
            "auto_renew": self.auto_renew,
            "stripe_subscription_id": self.stripe_subscription_id,
            "license_key": self.license_key,
            "is_active": self.is_active(),
            "days_remaining": self.days_remaining(),
            "features": _TIER_FEATURES.get(self.tier, {}),
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
        }


class SubscriptionManager:
    """Manage user subscriptions"""

    def __init__(self):
        self._subscriptions: dict[str, Subscription] = {}
        self._user_subscriptions: dict[str, str] = {}  # user_id -> subscription_id

    def _create_subscription_base(
        self,
        user_id: str,
        tier: SubscriptionTier,
        duration_days: int = 30,
        access_code: str | None = None,
        auto_renew: bool = True,
    ) -> Subscription:
        """Internal base subscription creation (no Stripe fields)."""
        subscription_id = f"SUB-{uuid.uuid4().hex[:12].upper()}"
        start_date = datetime.now(UTC)
        end_date = start_date + timedelta(days=duration_days)

        subscription = Subscription(
            subscription_id=subscription_id,
            user_id=user_id,
            tier=tier,
            status=SubscriptionStatus.PENDING,
            start_date=start_date,
            end_date=end_date,
            access_code=access_code,
            auto_renew=auto_renew,
        )

        self._subscriptions[subscription_id] = subscription
        self._user_subscriptions[user_id] = subscription_id

        logger.info(f"Created subscription {subscription_id} for user {user_id}")
        return subscription

    def get_subscription(self, subscription_id: str) -> Subscription | None:
        """Get subscription by ID"""
        return self._subscriptions.get(subscription_id)

    def get_user_subscription(self, user_id: str) -> Subscription | None:
        """Get active subscription for a user"""
        subscription_id = self._user_subscriptions.get(user_id)
        if subscription_id:
            return self._subscriptions.get(subscription_id)
        return None

    def activate_subscription(self, subscription_id: str, access_code: str) -> bool:
        """Activate a subscription with access code"""
        subscription = self.get_subscription(subscription_id)
        if not subscription:
            logger.error(f"Subscription {subscription_id} not found")
            return False

        if subscription.access_code != access_code:
            logger.error(f"Invalid access code for subscription {subscription_id}")
            return False

        subscription.status = SubscriptionStatus.ACTIVE
        subscription.updated_at = datetime.now(UTC)

        logger.info(f"Activated subscription {subscription_id}")
        return True

    def upgrade_subscription(self, subscription_id: str, new_tier: SubscriptionTier) -> bool:
        """Upgrade subscription to a higher tier"""
        subscription = self.get_subscription(subscription_id)
        if not subscription:
            return False

        # Check if upgrade is valid
        upgrade_path = pricing_manager.get_upgrade_path(subscription.tier)
        if new_tier not in upgrade_path:
            logger.error(f"Invalid upgrade from {subscription.tier} to {new_tier}")
            return False

        subscription.tier = new_tier
        subscription.updated_at = datetime.now(UTC)

        logger.info(f"Upgraded subscription {subscription_id} to {new_tier}")
        return True

    def downgrade_subscription(self, subscription_id: str, new_tier: SubscriptionTier) -> bool:
        """Downgrade subscription to a lower tier"""
        subscription = self.get_subscription(subscription_id)
        if not subscription:
            return False

        # Check if downgrade is valid
        downgrade_path = pricing_manager.get_downgrade_path(subscription.tier)
        if new_tier not in downgrade_path:
            logger.error(f"Invalid downgrade from {subscription.tier} to {new_tier}")
            return False

        subscription.tier = new_tier
        subscription.updated_at = datetime.now(UTC)

        logger.info(f"Downgraded subscription {subscription_id} to {new_tier}")
        return True

    def renew_subscription(self, subscription_id: str, duration_days: int = 30) -> bool:
        """Renew a subscription"""
        subscription = self.get_subscription(subscription_id)
        if not subscription:
            return False

        subscription.renew(duration_days)
        return True

    def cancel_subscription(self, subscription_id: str) -> bool:
        """Cancel a subscription"""
        subscription = self.get_subscription(subscription_id)
        if not subscription:
            return False

        subscription.cancel()
        return True

    def check_feature_access(self, user_id: str, feature_name: str) -> bool:
        """Check if user has access to a feature"""
        subscription = self.get_user_subscription(user_id)
        if not subscription or not subscription.is_active():
            return False

        return pricing_manager.has_feature(subscription.tier, feature_name)

    def get_user_limits(self, user_id: str) -> dict:
        """Get usage limits for a user"""
        subscription = self.get_user_subscription(user_id)
        if not subscription or not subscription.is_active():
            return {
                "max_strategies": 0,
                "max_brokers": 0,
                "ml_features": False,
                "api_access": False,
            }

        tier = pricing_manager.get_tier(subscription.tier)
        if not tier:
            return {}

        return {
            "max_strategies": tier.features.max_strategies,
            "max_brokers": tier.features.max_brokers,
            "ml_features": tier.features.ml_features,
            "priority_support": tier.features.priority_support,
            "api_access": tier.features.api_access,
            "custom_development": tier.features.custom_development,
            "dedicated_support": tier.features.dedicated_support,
            "backtesting_unlimited": tier.features.backtesting_unlimited,
            "pattern_recognition": tier.features.pattern_recognition,
            "news_integration": tier.features.news_integration,
        }

    def get_all_subscriptions(self) -> list[Subscription]:
        """Get all subscriptions"""
        return list(self._subscriptions.values())

    def get_active_subscriptions(self) -> list[Subscription]:
        """Get all active subscriptions"""
        return [sub for sub in self._subscriptions.values() if sub.is_active()]

    def get_expired_subscriptions(self) -> list[Subscription]:
        """Get all expired subscriptions"""
        return [sub for sub in self._subscriptions.values() if sub.is_expired()]

    def create_subscription(
        self,
        user_id: str,
        tier: SubscriptionTier,
        duration_days: int = 30,
        access_code: str | None = None,
        auto_renew: bool = True,
        stripe_subscription_id: str | None = None,
        stripe_customer_id: str | None = None,
    ) -> "Subscription":
        """Create a new subscription (overrides base to add Stripe fields)."""
        subscription_id = f"SUB-{uuid.uuid4().hex[:12].upper()}"
        start_date = datetime.now(UTC)
        end_date = start_date + timedelta(days=duration_days)

        subscription = Subscription(
            subscription_id=subscription_id,
            user_id=user_id,
            tier=tier,
            status=SubscriptionStatus.ACTIVE if tier == SubscriptionTier.FREE else SubscriptionStatus.PENDING,
            start_date=start_date,
            end_date=end_date,
            access_code=access_code,
            auto_renew=auto_renew,
            stripe_subscription_id=stripe_subscription_id,
            stripe_customer_id=stripe_customer_id,
        )

        self._subscriptions[subscription_id] = subscription
        self._user_subscriptions[user_id] = subscription_id
        logger.info(
            "subscription.created id=%s user=%s tier=%s",
            subscription_id,
            user_id,
            tier.value,
        )
        return subscription

    # ------------------------------------------------------------------
    # Stripe checkout session
    # ------------------------------------------------------------------

    def create_checkout_session(
        self,
        user_id: str,
        tier: SubscriptionTier,
        success_url: str = "https://hopefx.ai/success",
        cancel_url: str = "https://hopefx.ai/cancel",
        email: str | None = None,
    ) -> dict:
        """
        Create a Stripe Checkout Session for the given tier.
        Returns dict with `session_id` and `checkout_url`.
        """
        if not _STRIPE_AVAILABLE:
            raise RuntimeError("stripe package not installed. pip install stripe")

        _stripe.api_key = os.getenv("STRIPE_SECRET_KEY", "")
        price_id = _STRIPE_PRICE_IDS.get(tier)
        if not price_id:
            raise ValueError(f"No Stripe price configured for tier {tier.value}")

        session_params: dict = {
            "mode": "subscription",
            "line_items": [{"price": price_id, "quantity": 1}],
            "success_url": success_url + "?session_id={CHECKOUT_SESSION_ID}",
            "cancel_url": cancel_url,
            "metadata": {"user_id": user_id, "tier": tier.value},
        }
        if email:
            session_params["customer_email"] = email

        session = _stripe.checkout.Session.create(**session_params)
        logger.info("stripe.checkout.created user=%s tier=%s", user_id, tier.value)
        return {"session_id": session.id, "checkout_url": session.url}

    # ------------------------------------------------------------------
    # Stripe webhook handler
    # ------------------------------------------------------------------

    def handle_stripe_webhook(self, payload: bytes, sig_header: str) -> dict:
        """
        Verify and process a Stripe webhook event.

        Handles:
          checkout.session.completed    → activate subscription
          customer.subscription.deleted → cancel subscription
          invoice.payment_failed        → suspend subscription
        """
        if not _STRIPE_AVAILABLE:
            raise RuntimeError("stripe package not installed")

        webhook_secret = os.getenv("STRIPE_WEBHOOK_SECRET", "")
        try:
            event = _stripe.Webhook.construct_event(payload, sig_header, webhook_secret)
        except _stripe.error.SignatureVerificationError as exc:
            logger.warning("stripe.webhook.invalid_signature: %s", exc)
            raise ValueError("Invalid Stripe webhook signature") from exc

        event_type = event["type"]
        data = event["data"]["object"]

        if event_type == "checkout.session.completed":
            user_id = data.get("metadata", {}).get("user_id", "")
            tier_str = data.get("metadata", {}).get("tier", "free")
            stripe_sub_id = data.get("subscription")
            stripe_cust_id = data.get("customer")
            tier = SubscriptionTier(tier_str)

            existing = self.get_user_subscription(user_id)
            if existing:
                existing.tier = tier
                existing.stripe_subscription_id = stripe_sub_id
                existing.stripe_customer_id = stripe_cust_id
                existing.status = SubscriptionStatus.ACTIVE
                existing.end_date = datetime.now(UTC) + timedelta(days=30)
                existing.updated_at = datetime.now(UTC)
            else:
                sub = self.create_subscription(
                    user_id=user_id,
                    tier=tier,
                    stripe_subscription_id=stripe_sub_id,
                    stripe_customer_id=stripe_cust_id,
                )
                sub.status = SubscriptionStatus.ACTIVE
            logger.info("stripe.webhook.checkout_completed user=%s tier=%s", user_id, tier_str)

        elif event_type == "customer.subscription.deleted":
            stripe_sub_id = data.get("id")
            for sub in self._subscriptions.values():
                if sub.stripe_subscription_id == stripe_sub_id:
                    sub.cancel()
                    logger.info("stripe.webhook.subscription_deleted sub=%s", stripe_sub_id)
                    break

        elif event_type == "invoice.payment_failed":
            stripe_cust_id = data.get("customer")
            for sub in self._subscriptions.values():
                if sub.stripe_customer_id == stripe_cust_id:
                    sub.suspend()
                    logger.warning("stripe.webhook.payment_failed customer=%s", stripe_cust_id)
                    break

        return {"status": "processed", "event_type": event_type}


# ---------------------------------------------------------------------------
# License validator
# ---------------------------------------------------------------------------


class LicenseValidator:
    """
    Validates a license key against the active subscription.

    Free tier: paper trading only — always allowed, no key required.
    Paid tiers: key must match the active subscription record.

    Usage:
        validator = LicenseValidator(subscription_manager)
        result = validator.validate(user_id="u123", license_key="HOPEFX-PRO-ABCD1234")
        if result.valid and result.allows_live:
            # proceed with live trading
    """

    class Result:
        def __init__(
            self,
            valid: bool,
            tier: SubscriptionTier,
            allows_live: bool,
            allows_rl: bool,
            reason: str = "",
        ) -> None:
            self.valid = valid
            self.tier = tier
            self.allows_live = allows_live
            self.allows_rl = allows_rl
            self.reason = reason

        def to_dict(self) -> dict:
            return {
                "valid": self.valid,
                "tier": self.tier.value,
                "allows_live": self.allows_live,
                "allows_rl": self.allows_rl,
                "reason": self.reason,
            }

    def __init__(self, manager: SubscriptionManager) -> None:
        self._manager = manager

    def validate(
        self,
        user_id: str,
        license_key: str | None = None,
    ) -> "LicenseValidator.Result":
        """
        Validate a user's license.

        - No key / free tier → paper-only access.
        - Valid key + active paid subscription → full access per tier.
        """
        sub = self._manager.get_user_subscription(user_id)

        if sub is None or not sub.is_active():
            return self.Result(
                valid=True,
                tier=SubscriptionTier.FREE,
                allows_live=False,
                allows_rl=False,
                reason="No active subscription — free tier (paper only)",
            )

        if sub.tier == SubscriptionTier.FREE:
            return self.Result(
                valid=True,
                tier=SubscriptionTier.FREE,
                allows_live=False,
                allows_rl=False,
                reason="Free tier",
            )

        if license_key is None:
            return self.Result(
                valid=False,
                tier=sub.tier,
                allows_live=False,
                allows_rl=False,
                reason="License key required for paid tier",
            )

        if not _verify_license_key(license_key, user_id, sub.tier):
            return self.Result(
                valid=False,
                tier=sub.tier,
                allows_live=False,
                allows_rl=False,
                reason="Invalid license key",
            )

        features = _TIER_FEATURES.get(sub.tier, {})
        return self.Result(
            valid=True,
            tier=sub.tier,
            allows_live=bool(features.get("live_trading", False)),
            allows_rl=bool(features.get("rl_agent", False)),
            reason="OK",
        )


# ---------------------------------------------------------------------------
# FastAPI router factory
# ---------------------------------------------------------------------------


def create_subscription_router(manager: SubscriptionManager | None = None):
    """
    Build and return a FastAPI APIRouter with subscription endpoints.

    Endpoints:
      POST /subscribe              — create Stripe checkout session (or free activation)
      POST /webhook                — Stripe webhook receiver
      GET  /license/validate       — validate a license key
      GET  /subscription/{user_id} — get subscription status
      DELETE /subscription/{user_id} — cancel subscription

    Mount in your FastAPI app:
        app.include_router(create_subscription_router(), prefix="/billing")
    """
    try:
        from fastapi import APIRouter, Header, HTTPException, Request
        from pydantic import BaseModel
    except ImportError:
        raise ImportError("fastapi and pydantic are required. pip install fastapi pydantic") from None

    _mgr = manager or subscription_manager
    _validator = LicenseValidator(_mgr)
    router = APIRouter(tags=["Subscriptions"])

    class SubscribeRequest(BaseModel):
        user_id: str
        tier: str = "professional"
        email: str | None = None
        success_url: str = "https://hopefx.ai/success"
        cancel_url: str = "https://hopefx.ai/cancel"

    class LicenseValidateResponse(BaseModel):
        valid: bool
        tier: str
        allows_live: bool
        allows_rl: bool
        reason: str

    @router.post("/subscribe")
    async def subscribe(req: SubscribeRequest):
        """
        Activate free tier immediately, or create a Stripe Checkout Session
        for PROFESSIONAL / ENTERPRISE tiers.
        """
        try:
            tier = SubscriptionTier(req.tier.lower())
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Unknown tier: {req.tier!r}") from None

        if tier == SubscriptionTier.FREE:
            sub = _mgr.create_subscription(req.user_id, SubscriptionTier.FREE)
            return {
                "tier": "free",
                "subscription_id": sub.subscription_id,
                "license_key": sub.license_key,
                "message": "Free tier activated — paper trading only",
            }

        if not _STRIPE_AVAILABLE:
            raise HTTPException(
                status_code=503,
                detail="Payment processing unavailable — stripe package not installed",
            )

        try:
            session = _mgr.create_checkout_session(
                user_id=req.user_id,
                tier=tier,
                success_url=req.success_url,
                cancel_url=req.cancel_url,
                email=req.email,
            )
        except Exception as exc:
            logger.exception("subscribe endpoint error: %s", exc)
            raise HTTPException(status_code=500, detail="Subscription failed — check server logs") from None

        return session

    @router.post("/webhook")
    async def stripe_webhook(
        request: Request,
        stripe_signature: str | None = Header(None, alias="stripe-signature"),
    ):
        """Receive and process Stripe webhook events."""
        payload = await request.body()
        if not stripe_signature:
            raise HTTPException(status_code=400, detail="Missing Stripe-Signature header")

        try:
            result = _mgr.handle_stripe_webhook(payload, stripe_signature)
        except ValueError as exc:
            # ValueError from Stripe signature validation is a controlled message — safe to surface.
            raise HTTPException(status_code=400, detail=str(exc)) from None
        except Exception as exc:
            logger.exception("webhook processing error: %s", exc)
            raise HTTPException(status_code=500, detail="Webhook processing failed") from None

        return result

    @router.get("/license/validate", response_model=LicenseValidateResponse)
    async def validate_license(user_id: str, license_key: str | None = None):
        """
        Validate a license key for a user.
        Free tier requires no key. Paid tiers require a matching key.
        """
        result = _validator.validate(user_id=user_id, license_key=license_key)
        return LicenseValidateResponse(
            valid=result.valid,
            tier=result.tier.value,
            allows_live=result.allows_live,
            allows_rl=result.allows_rl,
            reason=result.reason,
        )

    @router.get("/subscription/{user_id}")
    async def get_subscription(user_id: str):
        """Return the current subscription state for a user."""
        sub = _mgr.get_user_subscription(user_id)
        if not sub:
            return {
                "user_id": user_id,
                "tier": "free",
                "status": "none",
                "features": _TIER_FEATURES[SubscriptionTier.FREE],
            }
        return sub.to_dict()

    @router.delete("/subscription/{user_id}")
    async def cancel_subscription(user_id: str):
        """Cancel the active subscription for a user."""
        sub = _mgr.get_user_subscription(user_id)
        if not sub:
            raise HTTPException(status_code=404, detail="No subscription found")
        _mgr.cancel_subscription(sub.subscription_id)
        return {"status": "cancelled", "subscription_id": sub.subscription_id}

    return router


# ---------------------------------------------------------------------------
# Module-level singletons
# ---------------------------------------------------------------------------

# Global subscription manager instance
subscription_manager = SubscriptionManager()
license_validator = LicenseValidator(subscription_manager)


# ---------------------------------------------------------------------------
# require_plan — FastAPI dependency decorator
# ---------------------------------------------------------------------------

# Ordered from lowest to highest privilege
_PLAN_ORDER: list[str] = [
    "trial",
    "free",
    "starter",
    "professional",
    "enterprise",
    "elite",
]


def _plan_rank(plan: str) -> int:
    """Return the numeric rank of a plan name (higher = more access)."""
    try:
        return _PLAN_ORDER.index(plan.lower())
    except ValueError:
        return 0  # unknown plan treated as lowest


def require_plan(minimum_plan: str):
    """
    FastAPI dependency that enforces a minimum subscription tier.

    Usage:
        @router.get("/api/ml/predict")
        async def predict(user=Depends(require_plan("professional"))):
            ...

    Returns the authenticated user's TokenPayload on success.
    Raises HTTP 403 with PLAN_LIMIT_EXCEEDED when the user's plan is below
    the required minimum.

    The user's current plan is read from their active subscription record.
    Falls back to "free" when no subscription exists.
    """

    try:
        from fastapi import Request
    except ImportError:
        Request = object  # type: ignore[assignment,misc]

    async def _dependency(request: "Request", user=None):  # type: ignore[name-defined]
        # Import here to avoid circular imports
        try:
            from api.auth import get_current_user
            from fastapi.security import HTTPBearer as _HTTPBearer  # noqa: F401
            from fastapi.security.http import HTTPAuthorizationCredentials as _Creds
        except ImportError:
            # auth module not available (e.g. unit tests) — allow through
            return user

        # Resolve the current user from the Bearer token when not already injected
        if user is None:
            try:
                auth_header = request.headers.get("Authorization", "")
                if auth_header.lower().startswith("bearer "):
                    token = auth_header[7:].strip()
                    creds = _Creds(scheme="bearer", credentials=token)
                    user = get_current_user(credentials=creds)
            except Exception as _exc:
                # Propagate HTTP exceptions (401/403) from token validation;
                # swallow only unexpected errors and fall through to plan check.
                from fastapi import HTTPException as _HTTPExc

                if isinstance(_exc, _HTTPExc):
                    raise
                logger.debug("Could not resolve user from request: %s", _exc)

        # Get user's current plan from subscription manager
        user_id = getattr(user, "sub", "") if user else ""
        current_plan = "free"
        if user_id:
            sub = subscription_manager.get_user_subscription(user_id)
            if sub and sub.is_active():
                tier = sub.tier
                current_plan = tier.value if hasattr(tier, "value") else str(tier)

        if _plan_rank(current_plan) < _plan_rank(minimum_plan):
            from fastapi import HTTPException, status as _status

            raise HTTPException(
                status_code=_status.HTTP_403_FORBIDDEN,
                detail={
                    "error": "PLAN_LIMIT_EXCEEDED",
                    "required_plan": minimum_plan,
                    "current_plan": current_plan,
                    "message": (
                        f"This feature requires a {minimum_plan.title()} subscription or above. "
                        f"Your current plan is {current_plan.title()}. "
                        f"Upgrade at hopefx.com/pricing"
                    ),
                },
            )
        return user

    # Return a FastAPI Depends-compatible callable
    # The actual dependency injection is handled by FastAPI when used as:
    #   Depends(require_plan("professional"))
    # which calls require_plan("professional") to get _dependency, then
    # FastAPI calls _dependency with the resolved user.
    return _dependency


def plan_gate(minimum_plan: str, user_plan: str) -> bool:
    """
    Simple boolean check: does user_plan meet or exceed minimum_plan?

    Use this for non-FastAPI contexts (e.g. strategy manager, CLI tools).

    Example:
        if not plan_gate("professional", user.plan):
            raise PermissionError("Professional plan required")
    """
    return _plan_rank(user_plan) >= _plan_rank(minimum_plan)
