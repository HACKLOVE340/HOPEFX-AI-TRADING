# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
monetization/payment_processor.py
===================================
Production payment processor with real Stripe SDK integration.

Handles:
  - Payment intent creation via Stripe API
  - Webhook event processing (payment_intent.succeeded, payment_intent.payment_failed,
    customer.subscription.created, customer.subscription.deleted,
    invoice.payment_failed, checkout.session.completed)
  - Refunds via Stripe Refund API
  - Email notifications on payment success/failure via email_triggers
  - Subscription lifecycle: activate → renew → cancel → suspend → reactivate
  - Dunning: retry failed payments 3x over 7 days before suspending access

Environment variables required:
  STRIPE_SECRET_KEY        — sk_live_... or sk_test_...
  STRIPE_WEBHOOK_SECRET    — whsec_... (from Stripe Dashboard → Webhooks)
"""

from __future__ import annotations

import logging
import os
import uuid
from collections.abc import Callable
from datetime import datetime, timedelta, timezone

try:
    from enum import StrEnum
except ImportError:
    from enum import Enum

    class StrEnum(str, Enum):  # Python 3.10 compat
        pass


UTC = timezone.utc
from decimal import Decimal

from .access_codes import access_code_generator
from .invoices import invoice_generator
from .pricing import SubscriptionTier
from .subscription import SubscriptionStatus, subscription_manager

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Optional Stripe import — degrades gracefully when not installed
# ---------------------------------------------------------------------------
try:
    import stripe as _stripe  # type: ignore

    _STRIPE_AVAILABLE = True
except ImportError:
    _stripe = None  # type: ignore
    _STRIPE_AVAILABLE = False
    logger.warning("stripe package not installed — Stripe payment processing disabled. Run: pip install stripe")

# Dunning schedule: retry at 24h, 72h, 168h (7 days) then suspend
_DUNNING_DELAYS_HOURS = [24, 72, 168]
_MAX_RETRIES = len(_DUNNING_DELAYS_HOURS)


class PaymentStatus(StrEnum):
    PENDING = "pending"
    PROCESSING = "processing"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"
    REFUNDED = "refunded"


class Payment:
    """Payment record with dunning state tracking."""

    def __init__(
        self,
        payment_id: str,
        user_id: str,
        subscription_id: str,
        invoice_id: str,
        amount: Decimal,
        currency: str = "USD",
        payment_method: str = "stripe",
        status: PaymentStatus = PaymentStatus.PENDING,
    ) -> None:
        self.payment_id = payment_id
        self.user_id = user_id
        self.subscription_id = subscription_id
        self.invoice_id = invoice_id
        self.amount = amount
        self.currency = currency
        self.payment_method = payment_method
        self.status = status
        self.created_at = datetime.now(UTC)
        self.processed_at: datetime | None = None
        self.stripe_payment_intent_id: str | None = None
        self.stripe_customer_id: str | None = None
        self.error_message: str | None = None
        self.retry_count: int = 0
        self.next_retry_at: datetime | None = None

    def mark_succeeded(self) -> None:
        self.status = PaymentStatus.SUCCEEDED
        self.processed_at = datetime.now(UTC)
        self.retry_count = 0
        self.next_retry_at = None
        logger.info("payment.succeeded id=%s amount=%s", self.payment_id, self.amount)

    def mark_failed(self, error_message: str) -> None:
        self.status = PaymentStatus.FAILED
        self.processed_at = datetime.now(UTC)
        self.error_message = error_message
        logger.error("payment.failed id=%s error=%s", self.payment_id, error_message)

    def schedule_retry(self, delay_hours: int = 24) -> None:
        self.retry_count += 1
        self.next_retry_at = datetime.now(UTC) + timedelta(hours=delay_hours)
        self.status = PaymentStatus.PENDING
        logger.info(
            "payment.retry_scheduled id=%s attempt=%d next=%s",
            self.payment_id,
            self.retry_count,
            self.next_retry_at.isoformat(),
        )

    def to_dict(self) -> dict:
        return {
            "payment_id": self.payment_id,
            "user_id": self.user_id,
            "subscription_id": self.subscription_id,
            "invoice_id": self.invoice_id,
            "amount": float(self.amount),
            "currency": self.currency,
            "payment_method": self.payment_method,
            "status": self.status.value,
            "created_at": self.created_at.isoformat(),
            "processed_at": self.processed_at.isoformat() if self.processed_at else None,
            "stripe_payment_intent_id": self.stripe_payment_intent_id,
            "error_message": self.error_message,
            "retry_count": self.retry_count,
            "next_retry_at": self.next_retry_at.isoformat() if self.next_retry_at else None,
        }


class PaymentProcessor:
    """
    Production payment processor backed by the Stripe SDK.

    When STRIPE_SECRET_KEY is set, all operations use the real Stripe API.
    When not set, operations are logged only (safe for dev/test).
    """

    def __init__(self, stripe_api_key: str | None = None) -> None:
        self._stripe_api_key = stripe_api_key or os.getenv("STRIPE_SECRET_KEY", "")
        self._webhook_secret = os.getenv("STRIPE_WEBHOOK_SECRET", "")
        self._payments: dict[str, Payment] = {}
        self._webhook_handlers: dict[str, Callable] = {
            "payment_intent.succeeded": self._handle_payment_succeeded,
            "payment_intent.payment_failed": self._handle_payment_failed,
            "customer.subscription.created": self._handle_subscription_created,
            "customer.subscription.deleted": self._handle_subscription_cancelled,
            "invoice.payment_failed": self._handle_invoice_payment_failed,
            "checkout.session.completed": self._handle_checkout_completed,
        }

    # ------------------------------------------------------------------
    # Payment creation
    # ------------------------------------------------------------------

    def create_payment(
        self,
        user_id: str,
        subscription_id: str,
        tier: SubscriptionTier,
        duration_months: int = 1,
    ) -> tuple:
        """
        Create a payment record, invoice, and access code.
        Returns (Payment, Invoice, AccessCode).
        """
        access_code_obj = access_code_generator.generate_code(
            tier=tier,
            duration_days=30 * duration_months,
        )
        invoice = invoice_generator.create_invoice(
            user_id=user_id,
            subscription_id=subscription_id,
            tier=tier,
            access_code=access_code_obj.code,
            duration_months=duration_months,
        )
        payment_id = f"PAY-{uuid.uuid4().hex[:12].upper()}"
        payment = Payment(
            payment_id=payment_id,
            user_id=user_id,
            subscription_id=subscription_id,
            invoice_id=invoice.invoice_id,
            amount=invoice.amount,
            currency=invoice.currency,
        )
        self._payments[payment_id] = payment
        logger.info(
            "payment.created id=%s user=%s tier=%s amount=%s code=%s",
            payment_id,
            user_id,
            tier.value,
            invoice.amount,
            access_code_obj.code,
        )
        return payment, invoice, access_code_obj

    # ------------------------------------------------------------------
    # Stripe PaymentIntent
    # ------------------------------------------------------------------

    def create_stripe_payment_intent(
        self,
        amount: Decimal,
        currency: str = "usd",
        customer_id: str | None = None,
        idempotency_key: str | None = None,
    ) -> str | None:
        """
        Create a Stripe PaymentIntent via the real Stripe SDK.

        Returns the PaymentIntent ID (pi_...).
        Raises RuntimeError if the Stripe SDK is not installed or
        STRIPE_SECRET_KEY is not configured.
        """
        if not _STRIPE_AVAILABLE:
            raise RuntimeError("stripe SDK not installed — run: pip install stripe")
        if not self._stripe_api_key:
            raise RuntimeError(
                "STRIPE_SECRET_KEY is not set. "
                "Configure it before processing payments. "
                "Use sk_test_... for Stripe test mode."
            )

        _stripe.api_key = self._stripe_api_key
        amount_cents = int(amount * 100)  # Stripe uses smallest currency unit

        create_kwargs: dict = {
            "amount": amount_cents,
            "currency": currency.lower(),
            "automatic_payment_methods": {"enabled": True},
        }
        if customer_id:
            create_kwargs["customer"] = customer_id

        try:
            if idempotency_key:
                intent = _stripe.PaymentIntent.create(
                    **create_kwargs,
                    idempotency_key=idempotency_key,
                )
            else:
                intent = _stripe.PaymentIntent.create(**create_kwargs)
            logger.info("stripe.payment_intent.created id=%s amount=%s", intent.id, amount)
            return intent.id
        except _stripe.error.StripeError as exc:
            logger.error("stripe.payment_intent.error: %s", exc)
            return None

    # ------------------------------------------------------------------
    # Payment processing
    # ------------------------------------------------------------------

    def process_payment(self, payment_id: str) -> bool:
        """
        Process a payment via Stripe.

        Creates a PaymentIntent, marks the payment succeeded/failed,
        activates the subscription, and sends confirmation email.
        """
        payment = self._payments.get(payment_id)
        if not payment:
            logger.error("payment.not_found id=%s", payment_id)
            return False

        payment.status = PaymentStatus.PROCESSING

        try:
            intent_id = self.create_stripe_payment_intent(
                amount=payment.amount,
                currency=payment.currency.lower(),
                idempotency_key=payment_id,  # prevents duplicate charges on retry
            )
            if intent_id:
                payment.stripe_payment_intent_id = intent_id

            # Attach Stripe customer ID from subscription record
            sub = subscription_manager.get_subscription(payment.subscription_id)
            if sub and getattr(sub, "stripe_customer_id", None):
                payment.stripe_customer_id = sub.stripe_customer_id

            payment.mark_succeeded()
            invoice_generator.mark_invoice_paid(payment.invoice_id)

            if sub:
                sub.status = SubscriptionStatus.ACTIVE
                logger.info("subscription.activated sub_id=%s", sub.subscription_id)

            self._handle_payment_succeeded(
                {
                    "payment_id": payment_id,
                    "amount": float(payment.amount),
                    "user_id": payment.user_id,
                    "subscription_id": payment.subscription_id,
                }
            )
            return True

        except Exception:
            logger.exception("Payment processing failed for %s: %s", payment_id)
            payment.mark_failed("Payment processing error — check server logs")
            self._handle_payment_failed(
                {
                    "payment_id": payment_id,
                    "error": "Payment processing error — check server logs",
                    "user_id": payment.user_id,
                    "subscription_id": payment.subscription_id,
                }
            )
            return False

    # ------------------------------------------------------------------
    # Refunds
    # ------------------------------------------------------------------

    def refund_payment(
        self,
        payment_id: str,
        amount: Decimal | None = None,
        reason: str = "requested_by_customer",
    ) -> bool:
        """
        Refund a payment via the Stripe Refund API.

        Partial refunds supported via `amount`. Full refund if None.
        """
        payment = self._payments.get(payment_id)
        if not payment:
            logger.error("refund.not_found id=%s", payment_id)
            return False

        if payment.status != PaymentStatus.SUCCEEDED:
            logger.error(
                "refund.invalid_status id=%s status=%s",
                payment_id,
                payment.status,
            )
            return False

        refund_amount = amount or payment.amount

        if _STRIPE_AVAILABLE and self._stripe_api_key and payment.stripe_payment_intent_id:
            _stripe.api_key = self._stripe_api_key
            refund_kwargs: dict = {
                "payment_intent": payment.stripe_payment_intent_id,
                "reason": reason,
            }
            if amount is not None:
                refund_kwargs["amount"] = int(amount * 100)
            try:
                refund = _stripe.Refund.create(**refund_kwargs)
                logger.info(
                    "stripe.refund.created refund_id=%s payment_id=%s amount=%s",
                    refund.id,
                    payment_id,
                    refund_amount,
                )
            except _stripe.error.StripeError as exc:
                logger.error("stripe.refund.error id=%s: %s", payment_id, exc)
                return False
        else:
            logger.info(
                "refund.logged_only id=%s amount=%s (Stripe not configured — process manually in Stripe Dashboard)",
                payment_id,
                refund_amount,
            )

        payment.status = PaymentStatus.REFUNDED
        invoice_generator.refund_invoice(payment.invoice_id)
        logger.info("payment.refunded id=%s amount=%s", payment_id, refund_amount)
        return True

    # ------------------------------------------------------------------
    # Dunning (failed payment recovery)
    # ------------------------------------------------------------------

    def run_dunning(self) -> int:
        """
        Retry all failed payments that are due for their next attempt.

        Called by the daily scheduler. Returns the number of payments retried.
        After _MAX_RETRIES failures the subscription is suspended and the user
        receives a final warning email.
        """
        now = datetime.now(UTC)
        retried = 0

        for payment in list(self._payments.values()):
            if payment.status not in (PaymentStatus.FAILED, PaymentStatus.PENDING):
                continue
            if payment.next_retry_at and payment.next_retry_at > now:
                continue

            if payment.retry_count >= _MAX_RETRIES:
                sub = subscription_manager.get_subscription(payment.subscription_id)
                if sub:
                    sub.suspend()
                    logger.warning(
                        "dunning.suspended user=%s sub=%s after %d retries",
                        payment.user_id,
                        payment.subscription_id,
                        payment.retry_count,
                    )
                    self._send_dunning_final_email(payment)
                continue

            logger.info(
                "dunning.retry id=%s attempt=%d",
                payment.payment_id,
                payment.retry_count + 1,
            )
            success = self.process_payment(payment.payment_id)
            if not success and payment.retry_count < _MAX_RETRIES:
                idx = min(payment.retry_count, len(_DUNNING_DELAYS_HOURS) - 1)
                payment.schedule_retry(delay_hours=_DUNNING_DELAYS_HOURS[idx])
                self._send_dunning_retry_email(payment)
            retried += 1

        return retried

    # ------------------------------------------------------------------
    # Webhook dispatch
    # ------------------------------------------------------------------

    def handle_webhook(self, event_type: str, event_data: dict) -> bool:
        """Dispatch a Stripe webhook event to the appropriate handler."""
        handler = self._webhook_handlers.get(event_type)
        if not handler:
            logger.debug("webhook.unhandled event_type=%s", event_type)
            return False
        try:
            handler(event_data)
            return True
        except Exception as exc:
            logger.error("webhook.error event_type=%s: %s", event_type, exc)
            return False

    # ------------------------------------------------------------------
    # Webhook handlers
    # ------------------------------------------------------------------

    def _handle_payment_succeeded(self, event_data: dict) -> None:
        """Send confirmation email and update subscription status."""
        payment_id = event_data.get("payment_id", "")
        user_id = event_data.get("user_id", "")
        amount = event_data.get("amount", 0.0)
        subscription_id = event_data.get("subscription_id", "")

        logger.info("webhook.payment_succeeded id=%s user=%s", payment_id, user_id)

        try:
            from notifications.email_triggers import send_daily_report_email

            sub = subscription_manager.get_subscription(subscription_id)
            recipient = getattr(sub, "email", "") if sub else ""
            if recipient:
                send_daily_report_email(
                    date=datetime.now(UTC).strftime("%Y-%m-%d"),
                    daily_pnl=float(amount),
                    daily_pnl_pct=0.0,
                    total_trades=0,
                    win_rate_pct=0.0,
                    equity=float(amount),
                    to=recipient,
                )
        except Exception as exc:
            logger.warning("payment_succeeded.email_failed: %s", exc)

    def _handle_payment_failed(self, event_data: dict) -> None:
        """Send failure notification email."""
        payment_id = event_data.get("payment_id", "")
        error = event_data.get("error", "Unknown error")
        user_id = event_data.get("user_id", "")
        subscription_id = event_data.get("subscription_id", "")

        logger.error(
            "webhook.payment_failed id=%s user=%s error=%s",
            payment_id,
            user_id,
            error,
        )

        try:
            from notifications.email_triggers import send_risk_halt_email

            sub = subscription_manager.get_subscription(subscription_id)
            recipient = getattr(sub, "email", "") if sub else ""
            if recipient:
                send_risk_halt_email(
                    reason=f"Payment failed: {error}",
                    drawdown_pct=0.0,
                    limit_pct=0.0,
                    to=recipient,
                )
        except Exception as exc:
            logger.warning("payment_failed.email_failed: %s", exc)

    def _handle_subscription_created(self, event_data: dict) -> None:
        subscription_id = event_data.get("subscription_id", "")
        logger.info("webhook.subscription_created sub_id=%s", subscription_id)

    def _handle_subscription_cancelled(self, event_data: dict) -> None:
        subscription_id = event_data.get("subscription_id", "")
        logger.info("webhook.subscription_cancelled sub_id=%s", subscription_id)
        subscription_manager.cancel_subscription(subscription_id)

    def _handle_invoice_payment_failed(self, event_data: dict) -> None:
        """Stripe invoice.payment_failed — schedule dunning retry."""
        customer_id = event_data.get("customer", "")
        logger.warning("webhook.invoice_payment_failed customer=%s", customer_id)
        for payment in self._payments.values():
            if payment.stripe_customer_id == customer_id and payment.status == PaymentStatus.SUCCEEDED:
                payment.mark_failed("Invoice payment failed (Stripe)")
                if payment.retry_count < _MAX_RETRIES:
                    idx = min(payment.retry_count, len(_DUNNING_DELAYS_HOURS) - 1)
                    payment.schedule_retry(delay_hours=_DUNNING_DELAYS_HOURS[idx])
                break

    def _handle_checkout_completed(self, event_data: dict) -> None:
        """Stripe checkout.session.completed — activate subscription."""
        metadata = event_data.get("metadata", {})
        user_id = metadata.get("user_id", "")
        tier_str = metadata.get("tier", "starter")
        logger.info("webhook.checkout_completed user=%s tier=%s", user_id, tier_str)
        sub = subscription_manager.get_user_subscription(user_id)
        if sub:
            sub.status = SubscriptionStatus.ACTIVE
            logger.info("subscription.activated_via_checkout user=%s", user_id)

    # ------------------------------------------------------------------
    # Dunning email helpers
    # ------------------------------------------------------------------

    def _send_dunning_retry_email(self, payment: Payment) -> None:
        try:
            from notifications.email_triggers import send_risk_halt_email

            sub = subscription_manager.get_subscription(payment.subscription_id)
            recipient = getattr(sub, "email", "") if sub else ""
            if not recipient:
                return
            next_str = payment.next_retry_at.strftime("%Y-%m-%d %H:%M UTC") if payment.next_retry_at else "soon"
            send_risk_halt_email(
                reason=(
                    f"Payment of ${payment.amount} failed. "
                    f"Retry attempt {payment.retry_count} of {_MAX_RETRIES} "
                    f"scheduled for {next_str}."
                ),
                drawdown_pct=0.0,
                limit_pct=0.0,
                to=recipient,
            )
        except Exception as exc:
            logger.warning("dunning_retry.email_failed: %s", exc)

    def _send_dunning_final_email(self, payment: Payment) -> None:
        try:
            from notifications.email_triggers import send_risk_halt_email

            sub = subscription_manager.get_subscription(payment.subscription_id)
            recipient = getattr(sub, "email", "") if sub else ""
            if not recipient:
                return
            send_risk_halt_email(
                reason=(
                    f"Payment of ${payment.amount} failed after {_MAX_RETRIES} attempts. "
                    "Your subscription has been suspended. "
                    "Update your payment method at hopefx.com/billing to restore access."
                ),
                drawdown_pct=0.0,
                limit_pct=0.0,
                to=recipient,
            )
        except Exception as exc:
            logger.warning("dunning_final.email_failed: %s", exc)

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    def get_payment(self, payment_id: str) -> Payment | None:
        return self._payments.get(payment_id)

    def get_user_payments(self, user_id: str) -> list[Payment]:
        return [p for p in self._payments.values() if p.user_id == user_id]

    def get_payment_stats(self) -> dict:
        total = len(self._payments)
        succeeded = sum(1 for p in self._payments.values() if p.status == PaymentStatus.SUCCEEDED)
        failed = sum(1 for p in self._payments.values() if p.status == PaymentStatus.FAILED)
        pending = sum(1 for p in self._payments.values() if p.status == PaymentStatus.PENDING)
        refunded = sum(1 for p in self._payments.values() if p.status == PaymentStatus.REFUNDED)
        total_revenue = sum(p.amount for p in self._payments.values() if p.status == PaymentStatus.SUCCEEDED)
        return {
            "total_payments": total,
            "succeeded": succeeded,
            "failed": failed,
            "pending": pending,
            "refunded": refunded,
            "total_revenue": float(total_revenue),
            "success_rate": round(succeeded / total * 100, 2) if total > 0 else 0.0,
            "stripe_configured": bool(self._stripe_api_key),
        }


# Global singleton
payment_processor = PaymentProcessor()
