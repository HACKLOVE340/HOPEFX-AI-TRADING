# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
monetization/stripe_integration.py
===================================
Stripe payment gateway integration — real SDK only, no in-process test doubles.

Requires:
  STRIPE_SECRET_KEY        — sk_live_... (production) or sk_test_... (Stripe test mode)
  STRIPE_WEBHOOK_SECRET    — whsec_... from Stripe Dashboard > Webhooks

Price IDs must be configured in the Stripe Dashboard and set via env vars:
  STRIPE_PRICE_STARTER_MONTHLY, STRIPE_PRICE_STARTER_ANNUAL,
  STRIPE_PRICE_PROFESSIONAL_MONTHLY, STRIPE_PRICE_PROFESSIONAL_ANNUAL,
  STRIPE_PRICE_ENTERPRISE_MONTHLY, STRIPE_PRICE_ENTERPRISE_ANNUAL,
  STRIPE_PRICE_ELITE_MONTHLY, STRIPE_PRICE_ELITE_ANNUAL

Testing: patch the stripe SDK at the module level using unittest.mock.patch:
  with patch("monetization.stripe_integration._stripe") as mock_stripe:
      mock_stripe.Customer.create.return_value = MagicMock(id="cus_test", ...)
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta, timezone

try:
    from enum import StrEnum
except ImportError:
    from enum import Enum

    class StrEnum(str, Enum):  # Python 3.10 compat
        pass


UTC = timezone.utc
from decimal import Decimal
from typing import Any, ClassVar

from .pricing import BillingCycle, SubscriptionTier

logger = logging.getLogger(__name__)

# ── Stripe SDK availability ───────────────────────────────────────────────────

try:
    import stripe as _stripe  # type: ignore[import]

    _STRIPE_AVAILABLE = True
except ImportError:
    _stripe = None  # type: ignore[assignment]
    _STRIPE_AVAILABLE = False


# ── Webhook event types ───────────────────────────────────────────────────────


class StripeWebhookEvent(StrEnum):
    PAYMENT_INTENT_SUCCEEDED = "payment_intent.succeeded"
    PAYMENT_INTENT_FAILED = "payment_intent.payment_failed"
    CHECKOUT_SESSION_COMPLETED = "checkout.session.completed"
    CUSTOMER_SUBSCRIPTION_CREATED = "customer.subscription.created"
    CUSTOMER_SUBSCRIPTION_UPDATED = "customer.subscription.updated"
    CUSTOMER_SUBSCRIPTION_DELETED = "customer.subscription.deleted"
    INVOICE_PAID = "invoice.paid"
    INVOICE_PAYMENT_FAILED = "invoice.payment_failed"


# ── Domain models ─────────────────────────────────────────────────────────────


class StripeCustomer:
    def __init__(
        self,
        customer_id: str,
        user_id: str,
        email: str,
        name: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        self.customer_id = customer_id
        self.user_id = user_id
        self.email = email
        self.name = name
        self.metadata = metadata or {}
        self.created_at = datetime.now(UTC)

    def to_dict(self) -> dict[str, Any]:
        return {
            "customer_id": self.customer_id,
            "user_id": self.user_id,
            "email": self.email,
            "name": self.name,
            "metadata": self.metadata,
            "created_at": self.created_at.isoformat(),
        }


class StripePaymentIntent:
    def __init__(
        self,
        intent_id: str,
        customer_id: str,
        amount: int,  # cents
        currency: str,
        status: str,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        self.intent_id = intent_id
        self.customer_id = customer_id
        self.amount = amount
        self.currency = currency
        self.status = status
        self.metadata = metadata or {}
        self.created_at = datetime.now(UTC)
        self.client_secret: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "intent_id": self.intent_id,
            "customer_id": self.customer_id,
            "amount": self.amount,
            "amount_display": self.amount / 100,
            "currency": self.currency,
            "status": self.status,
            "metadata": self.metadata,
            "created_at": self.created_at.isoformat(),
        }


class StripeSubscription:
    def __init__(
        self,
        subscription_id: str,
        customer_id: str,
        tier: SubscriptionTier,
        billing_cycle: BillingCycle,
        status: str,
        current_period_start: datetime,
        current_period_end: datetime,
        cancel_at_period_end: bool = False,
    ) -> None:
        self.subscription_id = subscription_id
        self.customer_id = customer_id
        self.tier = tier
        self.billing_cycle = billing_cycle
        self.status = status
        self.current_period_start = current_period_start
        self.current_period_end = current_period_end
        self.cancel_at_period_end = cancel_at_period_end
        self.created_at = datetime.now(UTC)

    def to_dict(self) -> dict[str, Any]:
        return {
            "subscription_id": self.subscription_id,
            "customer_id": self.customer_id,
            "tier": self.tier.value,
            "billing_cycle": self.billing_cycle.value,
            "status": self.status,
            "current_period_start": self.current_period_start.isoformat(),
            "current_period_end": self.current_period_end.isoformat(),
            "cancel_at_period_end": self.cancel_at_period_end,
            "created_at": self.created_at.isoformat(),
        }


# ── Integration class ─────────────────────────────────────────────────────────


#: Events we receive, understand, and do not act on. Stripe needs a 200 so it
#: stops retrying; naming this set explicitly is what stops "we do nothing here"
#: from being written as "access_granted".
#:
#: The subscription lifecycle is driven by checkout.session.completed,
#: customer.subscription.deleted and invoice.payment_failed. The rest are
#: notifications about state those three already produced.
_ACKNOWLEDGED_EVENTS: frozenset[str] = frozenset(
    {
        "payment_intent.succeeded",
        "customer.subscription.created",
        "customer.subscription.updated",
        "invoice.paid",
        "invoice.payment_succeeded",
    }
)


class StripeIntegration:
    """
    Stripe payment integration — delegates all operations to the real Stripe SDK.

    Production: set STRIPE_SECRET_KEY (sk_live_...) and STRIPE_WEBHOOK_SECRET.
    Stripe test mode: set STRIPE_SECRET_KEY=sk_test_... (no code changes needed).
    Unit tests: patch monetization.stripe_integration._stripe with unittest.mock.
    """

    # Price IDs loaded from env vars configured in the Stripe Dashboard.
    PRICE_IDS: ClassVar[dict[tuple, str | None]] = {
        (SubscriptionTier.FREE, BillingCycle.MONTHLY): None,
        (SubscriptionTier.STARTER, BillingCycle.MONTHLY): os.getenv(
            "STRIPE_PRICE_STARTER_MONTHLY", "price_starter_monthly"
        ),
        (SubscriptionTier.STARTER, BillingCycle.ANNUAL): os.getenv(
            "STRIPE_PRICE_STARTER_ANNUAL", "price_starter_annual"
        ),
        (SubscriptionTier.PROFESSIONAL, BillingCycle.MONTHLY): os.getenv(
            "STRIPE_PRICE_PROFESSIONAL_MONTHLY", "price_pro_monthly"
        ),
        (SubscriptionTier.PROFESSIONAL, BillingCycle.ANNUAL): os.getenv(
            "STRIPE_PRICE_PROFESSIONAL_ANNUAL", "price_pro_annual"
        ),
        (SubscriptionTier.ENTERPRISE, BillingCycle.MONTHLY): os.getenv(
            "STRIPE_PRICE_ENTERPRISE_MONTHLY", "price_ent_monthly"
        ),
        (SubscriptionTier.ENTERPRISE, BillingCycle.ANNUAL): os.getenv(
            "STRIPE_PRICE_ENTERPRISE_ANNUAL", "price_ent_annual"
        ),
        (SubscriptionTier.ELITE, BillingCycle.MONTHLY): os.getenv("STRIPE_PRICE_ELITE_MONTHLY", "price_elite_monthly"),
        (SubscriptionTier.ELITE, BillingCycle.ANNUAL): os.getenv("STRIPE_PRICE_ELITE_ANNUAL", "price_elite_annual"),
    }

    def __init__(
        self,
        api_key: str | None = None,
        webhook_secret: str | None = None,
    ) -> None:
        """
        Initialise Stripe integration.

        Args:
            api_key: Stripe secret key. Defaults to STRIPE_SECRET_KEY env var.
                     Use sk_test_... for Stripe test mode, sk_live_... for production.
            webhook_secret: Stripe webhook signing secret. Defaults to
                            STRIPE_WEBHOOK_SECRET env var.
        """
        self.api_key = api_key or os.getenv("STRIPE_SECRET_KEY", "")
        self.webhook_secret = webhook_secret or os.getenv("STRIPE_WEBHOOK_SECRET", "")

        if not _STRIPE_AVAILABLE:
            logger.info("stripe SDK not installed — run: pip install stripe to enable payments")
        elif not self.api_key:
            # Startup validator (config.startup_validator) owns the user-facing
            # warning for missing STRIPE_SECRET_KEY. Log at DEBUG here to avoid
            # duplicate noise on every import.
            logger.debug("STRIPE_SECRET_KEY not set — Stripe operations will raise until configured.")
        else:
            _stripe.api_key = self.api_key
            # Log only the key mode (test/live), never the key value itself.
            key_type = "test" if self.api_key.startswith("sk_test_") else "live"
            logger.info("Stripe SDK configured (mode: %s)", key_type)  # nosec B105

    def _require_stripe(self) -> None:
        """Raise RuntimeError if the Stripe SDK or API key is missing."""
        if not _STRIPE_AVAILABLE:
            raise RuntimeError("stripe SDK not installed. Run: pip install stripe")
        if not self.api_key:
            raise RuntimeError(
                "STRIPE_SECRET_KEY is not set. "
                "Configure it before calling Stripe APIs. "
                "Use sk_test_... for Stripe test mode."
            )
        _stripe.api_key = self.api_key

    # ── Customer ──────────────────────────────────────────────────────────────

    def create_customer(
        self,
        user_id: str,
        email: str,
        name: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> StripeCustomer:
        """Create a Stripe customer and return the domain model."""
        self._require_stripe()
        try:
            customer = _stripe.Customer.create(
                email=email,
                name=name,
                metadata={"user_id": user_id, **(metadata or {})},
            )
            result = StripeCustomer(
                customer_id=customer.id,
                user_id=user_id,
                email=email,
                name=name,
                metadata=metadata,
            )
            logger.info("Created Stripe customer: %s", result.customer_id)
            return result
        except Exception as exc:  # pylint: disable=broad-exception-caught
            logger.error("Error creating Stripe customer: %s", exc)
            raise

    def get_customer(self, customer_id: str) -> StripeCustomer | None:
        """Retrieve a customer from Stripe by ID."""
        self._require_stripe()
        try:
            c = _stripe.Customer.retrieve(customer_id)
            return StripeCustomer(
                customer_id=c.id,
                user_id=c.metadata.get("user_id", ""),
                email=c.email or "",
                name=c.name,
                metadata=dict(c.metadata),
            )
        except Exception as exc:  # pylint: disable=broad-exception-caught
            logger.error("Error retrieving Stripe customer %s: %s", customer_id, exc)
            return None

    # ── Payment intent ────────────────────────────────────────────────────────

    def create_payment_intent(
        self,
        customer_id: str | None,
        amount: Decimal,
        currency: str = "usd",
        tier: SubscriptionTier | None = None,
        billing_cycle: BillingCycle = BillingCycle.MONTHLY,
        metadata: dict[str, Any] | None = None,
    ) -> StripePaymentIntent:
        """Create a Stripe PaymentIntent and return the domain model."""
        self._require_stripe()
        try:
            amount_cents = int(amount * 100)
            intent_metadata: dict[str, Any] = {
                "tier": tier.value if tier else "",
                "billing_cycle": billing_cycle.value,
                **(metadata or {}),
            }
            create_kwargs: dict[str, Any] = {
                "amount": amount_cents,
                "currency": currency.lower(),
                "metadata": intent_metadata,
                "automatic_payment_methods": {"enabled": True},
            }
            if customer_id:
                create_kwargs["customer"] = customer_id
            intent = _stripe.PaymentIntent.create(**create_kwargs)
            pi = StripePaymentIntent(
                intent_id=intent.id,
                customer_id=customer_id,
                amount=amount_cents,
                currency=currency,
                status=intent.status,
                metadata=intent_metadata,
            )
            pi.client_secret = intent.client_secret
            logger.info("Created payment intent: %s", pi.intent_id)
            return pi
        except Exception as exc:  # pylint: disable=broad-exception-caught
            logger.error("Error creating payment intent: %s", exc)
            raise

    def get_payment_intent(self, intent_id: str) -> StripePaymentIntent | None:
        """Retrieve a PaymentIntent from Stripe by ID."""
        self._require_stripe()
        try:
            intent = _stripe.PaymentIntent.retrieve(intent_id)
            pi = StripePaymentIntent(
                intent_id=intent.id,
                customer_id=intent.customer or "",
                amount=intent.amount,
                currency=intent.currency,
                status=intent.status,
                metadata=dict(intent.metadata),
            )
            pi.client_secret = intent.client_secret
            return pi
        except Exception as exc:  # pylint: disable=broad-exception-caught
            logger.error("Error retrieving payment intent %s: %s", intent_id, exc)
            return None

    # ── Checkout session ──────────────────────────────────────────────────────

    def create_checkout_session(
        self,
        customer_id: str,
        tier: SubscriptionTier,
        billing_cycle: BillingCycle = BillingCycle.MONTHLY,
        success_url: str = "https://app.hopefx.ai/success",
        cancel_url: str = "https://app.hopefx.ai/cancel",
    ) -> dict[str, Any]:
        """Create a Stripe Checkout session for subscription purchase."""
        self._require_stripe()
        price_id = self.PRICE_IDS.get((tier, billing_cycle))
        if not price_id:
            raise ValueError(
                f"No Stripe price ID configured for {tier.value}/{billing_cycle.value}. "
                f"Set STRIPE_PRICE_{tier.value.upper()}_{billing_cycle.value.upper()} "
                "in your environment."
            )
        try:
            session = _stripe.checkout.Session.create(
                customer=customer_id,
                payment_method_types=["card"],
                line_items=[{"price": price_id, "quantity": 1}],
                mode="subscription",
                success_url=success_url,
                cancel_url=cancel_url,
                metadata={"tier": tier.value, "billing_cycle": billing_cycle.value},
            )
            return {
                "session_id": session.id,
                "url": session.url,
                "tier": tier.value,
                "billing_cycle": billing_cycle.value,
            }
        except Exception as exc:  # pylint: disable=broad-exception-caught
            logger.error("Error creating checkout session: %s", exc)
            raise

    # ── Subscription ──────────────────────────────────────────────────────────

    def create_subscription(
        self,
        customer_id: str,
        tier: SubscriptionTier,
        billing_cycle: BillingCycle = BillingCycle.MONTHLY,
    ) -> StripeSubscription:
        """Create a Stripe subscription and return the domain model."""
        self._require_stripe()
        price_id = self.PRICE_IDS.get((tier, billing_cycle))
        if not price_id:
            raise ValueError(f"No Stripe price ID configured for {tier.value}/{billing_cycle.value}.")
        try:
            sub = _stripe.Subscription.create(
                customer=customer_id,
                items=[{"price": price_id}],
                metadata={"tier": tier.value, "billing_cycle": billing_cycle.value},
            )
            result = StripeSubscription(
                subscription_id=sub.id,
                customer_id=customer_id,
                tier=tier,
                billing_cycle=billing_cycle,
                status=sub.status,
                current_period_start=datetime.fromtimestamp(sub.current_period_start, tz=UTC),
                current_period_end=datetime.fromtimestamp(sub.current_period_end, tz=UTC),
            )
            logger.info("Created subscription: %s", result.subscription_id)
            return result
        except Exception as exc:  # pylint: disable=broad-exception-caught
            logger.error("Error creating subscription: %s", exc)
            raise

    def get_subscription(self, subscription_id: str) -> StripeSubscription | None:
        """Retrieve a subscription from Stripe by ID."""
        self._require_stripe()
        try:
            sub = _stripe.Subscription.retrieve(subscription_id)
            return StripeSubscription(
                subscription_id=sub.id,
                customer_id=sub.customer,
                tier=SubscriptionTier.FREE,  # resolved by caller from sub.metadata
                billing_cycle=BillingCycle.MONTHLY,
                status=sub.status,
                current_period_start=datetime.fromtimestamp(sub.current_period_start, tz=UTC),
                current_period_end=datetime.fromtimestamp(sub.current_period_end, tz=UTC),
                cancel_at_period_end=sub.cancel_at_period_end,
            )
        except Exception as exc:  # pylint: disable=broad-exception-caught
            logger.error("Error retrieving subscription %s: %s", subscription_id, exc)
            return None

    def list_customer_subscriptions(self, customer_id: str) -> list[StripeSubscription]:
        """List all subscriptions for a customer from Stripe."""
        self._require_stripe()
        try:
            subs = _stripe.Subscription.list(customer=customer_id, limit=100)
            results = []
            for sub in subs.auto_paging_iter():
                results.append(
                    StripeSubscription(
                        subscription_id=sub.id,
                        customer_id=customer_id,
                        tier=SubscriptionTier.FREE,
                        billing_cycle=BillingCycle.MONTHLY,
                        status=sub.status,
                        current_period_start=datetime.fromtimestamp(sub.current_period_start, tz=UTC),
                        current_period_end=datetime.fromtimestamp(sub.current_period_end, tz=UTC),
                        cancel_at_period_end=sub.cancel_at_period_end,
                    )
                )
            return results
        except Exception as exc:  # pylint: disable=broad-exception-caught
            logger.error("Error listing subscriptions for %s: %s", customer_id, exc)
            return []

    def cancel_subscription(self, subscription_id: str, at_period_end: bool = True) -> bool:
        """Cancel a subscription immediately or at period end."""
        self._require_stripe()
        try:
            if at_period_end:
                _stripe.Subscription.modify(subscription_id, cancel_at_period_end=True)
            else:
                _stripe.Subscription.delete(subscription_id)
            logger.info(
                "Cancelled subscription: %s (at_period_end=%s)",
                subscription_id,
                at_period_end,
            )
            return True
        except Exception as exc:  # pylint: disable=broad-exception-caught
            logger.error("Error cancelling subscription %s: %s", subscription_id, exc)
            return False

    # ── Refunds ───────────────────────────────────────────────────────────────

    def refund_payment(
        self,
        payment_intent_id: str,
        amount: Decimal | None = None,
    ) -> dict[str, Any]:
        """Issue a full or partial refund for a PaymentIntent."""
        self._require_stripe()
        try:
            params: dict[str, Any] = {"payment_intent": payment_intent_id}
            if amount is not None:
                params["amount"] = int(amount * 100)
            refund = _stripe.Refund.create(**params)
            logger.info("Refunded payment %s: refund_id=%s", payment_intent_id, refund.id)
            return {
                "refund_id": refund.id,
                "status": refund.status,
                "amount": refund.amount / 100,
            }
        except Exception as exc:  # pylint: disable=broad-exception-caught
            logger.error("Error processing refund for %s: %s", payment_intent_id, exc)
            raise

    # ── Webhooks ──────────────────────────────────────────────────────────────

    def verify_webhook_signature(self, payload: bytes, signature: str) -> bool:
        """Verify the Stripe-Signature header on an incoming webhook."""
        if not self.webhook_secret:
            logger.warning("STRIPE_WEBHOOK_SECRET not configured — rejecting webhook")
            return False
        if not _STRIPE_AVAILABLE:
            logger.error("stripe SDK not installed — cannot verify webhook")
            return False
        try:
            _stripe.Webhook.construct_event(payload, signature, self.webhook_secret)
            return True
        except Exception as exc:  # pylint: disable=broad-exception-caught
            logger.error("Webhook signature verification failed: %s", exc)
            return False

    def handle_webhook(self, event_type: str, event_data: dict[str, Any]) -> dict[str, Any]:
        """Dispatch a verified Stripe webhook event to the appropriate handler.

        **Every handler here used to log one line and return a success claim.**
        `customer.subscription.deleted` returned `{"status": "success",
        "action": "access_revoked"}` and revoked nothing, so a customer who
        cancelled kept paid access indefinitely; `checkout.session.completed`
        claimed `subscription_activated` and activated nothing. The endpoint
        then returned 200, Stripe marked the delivery successful, and never
        retried — so the failure left no trace anywhere.

        A correct implementation already existed in
        `monetization/subscription.py::handle_stripe_webhook` (activate, cancel,
        suspend, all real). Two handlers for the same events, one decorative,
        was the root of it. These delegate to that one now, so there is a single
        implementation of each lifecycle transition.

        Events with no implementation return `acknowledged` rather than a named
        action. Stripe needs a 200 so it stops retrying; what it must not be
        given is the name of something no code performed.
        """
        handlers = {
            StripeWebhookEvent.PAYMENT_INTENT_FAILED.value: self._handle_payment_failed,
            StripeWebhookEvent.CHECKOUT_SESSION_COMPLETED.value: self._handle_checkout_completed,
            StripeWebhookEvent.CUSTOMER_SUBSCRIPTION_DELETED.value: self._handle_subscription_deleted,
            StripeWebhookEvent.INVOICE_PAYMENT_FAILED.value: self._handle_invoice_failed,
        }
        handler = handlers.get(event_type)
        if handler:
            return handler(event_data)

        if event_type in _ACKNOWLEDGED_EVENTS:
            # Received and understood; no lifecycle transition is driven by it.
            # Named explicitly so the list of what we do NOT act on is visible.
            logger.info("stripe.webhook.acknowledged type=%s id=%s", event_type, event_data.get("id"))
            return {"status": "acknowledged", "event_type": event_type}

        logger.info("Unhandled webhook event type: %s", event_type)
        return {"status": "ignored", "event_type": event_type}

    @staticmethod
    def _subscription_status():
        """The SubscriptionStatus enum, resolved through the module.

        Imported at call time for the same reason as the manager: the import
        direction stays one-way, so subscription.py never has to know this
        module exists.
        """
        from monetization import subscription as _subscription_module

        return _subscription_module.SubscriptionStatus

    @staticmethod
    def _subscriptions():
        """The live SubscriptionManager.

        Resolved at call time through the module rather than imported at the top:
        it keeps the import direction one-way (subscription.py does not know
        about this module) and lets a test substitute the manager.
        """
        from monetization import subscription as _subscription_module

        return _subscription_module.subscription_manager

    def _handle_payment_failed(self, data: dict[str, Any]) -> dict[str, Any]:
        logger.warning("Payment failed: %s", data.get("id"))
        return {"status": "failed", "action": "payment_retry_needed"}

    def _handle_checkout_completed(self, data: dict[str, Any]) -> dict[str, Any]:
        """Activate the subscription the checkout paid for."""
        from monetization.pricing import SubscriptionTier

        metadata = data.get("metadata") or {}
        user_id = str(metadata.get("user_id") or "").strip()
        if not user_id:
            # Activating a subscription for nobody is worse than refusing: it
            # creates a paid record no user can be billed for or supported on.
            logger.error("stripe.webhook.checkout_completed has no user_id in metadata: %s", data.get("id"))
            return {"status": "failed", "reason": "no_user_id_in_metadata", "event_type": "checkout.session.completed"}

        try:
            tier = SubscriptionTier(str(metadata.get("tier", "free")))
        except ValueError:
            logger.error("stripe.webhook.checkout_completed unknown tier %r", metadata.get("tier"))
            return {"status": "failed", "reason": "unknown_tier", "event_type": "checkout.session.completed"}

        manager = self._subscriptions()
        stripe_sub_id = data.get("subscription")
        stripe_cust_id = data.get("customer")

        existing = manager.get_user_subscription(user_id)
        if existing is not None:
            # Idempotent: Stripe retries, and a replay must update the record
            # rather than create a second subscription for the same user.
            existing.tier = tier
            existing.stripe_subscription_id = stripe_sub_id
            existing.stripe_customer_id = stripe_cust_id
            existing.status = self._subscription_status().ACTIVE
            existing.end_date = datetime.now(UTC) + timedelta(days=30)
            existing.updated_at = datetime.now(UTC)
        else:
            created = manager.create_subscription(
                user_id=user_id,
                tier=tier,
                stripe_subscription_id=stripe_sub_id,
                stripe_customer_id=stripe_cust_id,
            )
            created.status = self._subscription_status().ACTIVE

        logger.info("stripe.webhook.checkout_completed user=%s tier=%s", user_id, tier.value)
        return {"status": "success", "action": "subscription_activated", "user_id": user_id}

    def _handle_subscription_deleted(self, data: dict[str, Any]) -> dict[str, Any]:
        """Revoke access for the cancelled subscription."""
        stripe_sub_id = data.get("id")
        for sub in self._subscriptions()._subscriptions.values():
            if sub.stripe_subscription_id == stripe_sub_id:
                sub.cancel()
                logger.info("stripe.webhook.subscription_deleted sub=%s", stripe_sub_id)
                return {"status": "success", "action": "access_revoked", "subscription": stripe_sub_id}

        # Nothing was revoked. Saying "success" here is exactly how the original
        # defect stayed invisible.
        logger.error("stripe.webhook.subscription_deleted: no_matching_subscription for %s", stripe_sub_id)
        return {"status": "failed", "reason": "no_matching_subscription", "subscription": stripe_sub_id}

    def _handle_invoice_failed(self, data: dict[str, Any]) -> dict[str, Any]:
        """Suspend the subscription whose invoice failed."""
        stripe_cust_id = data.get("customer")
        for sub in self._subscriptions()._subscriptions.values():
            if sub.stripe_customer_id == stripe_cust_id:
                sub.suspend()
                logger.warning("stripe.webhook.payment_failed customer=%s", stripe_cust_id)
                return {"status": "success", "action": "access_suspended", "customer": stripe_cust_id}

        logger.error("stripe.webhook.payment_failed: no_matching_subscription for customer %s", stripe_cust_id)
        return {"status": "failed", "reason": "no_matching_subscription", "customer": stripe_cust_id}


# Global instance — configured from environment variables at import time.
stripe_integration = StripeIntegration()
