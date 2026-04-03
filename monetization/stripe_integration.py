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
from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum
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
            logger.warning("stripe SDK not installed — run: pip install stripe")
        elif not self.api_key:
            logger.warning("STRIPE_SECRET_KEY not set — Stripe operations will raise until configured.")
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
        """Dispatch a verified Stripe webhook event to the appropriate handler."""
        handlers = {
            StripeWebhookEvent.PAYMENT_INTENT_SUCCEEDED.value: self._handle_payment_success,
            StripeWebhookEvent.PAYMENT_INTENT_FAILED.value: self._handle_payment_failed,
            StripeWebhookEvent.CHECKOUT_SESSION_COMPLETED.value: self._handle_checkout_completed,
            StripeWebhookEvent.CUSTOMER_SUBSCRIPTION_CREATED.value: self._handle_subscription_created,
            StripeWebhookEvent.CUSTOMER_SUBSCRIPTION_UPDATED.value: self._handle_subscription_updated,
            StripeWebhookEvent.CUSTOMER_SUBSCRIPTION_DELETED.value: self._handle_subscription_deleted,
            StripeWebhookEvent.INVOICE_PAID.value: self._handle_invoice_paid,
            StripeWebhookEvent.INVOICE_PAYMENT_FAILED.value: self._handle_invoice_failed,
        }
        handler = handlers.get(event_type)
        if handler:
            return handler(event_data)
        logger.info("Unhandled webhook event type: %s", event_type)
        return {"status": "ignored", "event_type": event_type}

    def _handle_payment_success(self, data: dict[str, Any]) -> dict[str, Any]:
        logger.info("Payment succeeded: %s", data.get("id"))
        return {"status": "success", "action": "payment_confirmed"}

    def _handle_payment_failed(self, data: dict[str, Any]) -> dict[str, Any]:
        logger.warning("Payment failed: %s", data.get("id"))
        return {"status": "failed", "action": "payment_retry_needed"}

    def _handle_checkout_completed(self, data: dict[str, Any]) -> dict[str, Any]:
        logger.info("Checkout completed: %s", data.get("id"))
        return {"status": "success", "action": "subscription_activated"}

    def _handle_subscription_created(self, data: dict[str, Any]) -> dict[str, Any]:
        logger.info("Subscription created: %s", data.get("id"))
        return {"status": "success", "action": "access_granted"}

    def _handle_subscription_updated(self, data: dict[str, Any]) -> dict[str, Any]:
        logger.info("Subscription updated: %s", data.get("id"))
        return {"status": "success", "action": "access_updated"}

    def _handle_subscription_deleted(self, data: dict[str, Any]) -> dict[str, Any]:
        logger.info("Subscription deleted: %s", data.get("id"))
        return {"status": "success", "action": "access_revoked"}

    def _handle_invoice_paid(self, data: dict[str, Any]) -> dict[str, Any]:
        logger.info("Invoice paid: %s", data.get("id"))
        return {"status": "success", "action": "invoice_confirmed"}

    def _handle_invoice_failed(self, data: dict[str, Any]) -> dict[str, Any]:
        logger.warning("Invoice payment failed: %s", data.get("id"))
        return {"status": "failed", "action": "payment_retry_needed"}


# Global instance — configured from environment variables at import time.
stripe_integration = StripeIntegration()
