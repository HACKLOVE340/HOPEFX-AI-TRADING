"""
Payment Processor Integration

This module handles payment processing with Stripe integration,
webhook handling, and automated access code generation.
"""

import logging
from datetime import datetime
from typing import Optional, Dict, Callable
from decimal import Decimal
from enum import Enum

from .pricing import SubscriptionTier, pricing_manager
from .subscription import subscription_manager, SubscriptionStatus
from .access_codes import access_code_generator
from .invoices import invoice_generator


logger = logging.getLogger(__name__)


class PaymentStatus(str, Enum):
    """Payment status enumeration"""
    PENDING = "pending"
    PROCESSING = "processing"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"
    REFUNDED = "refunded"


class Payment:
    """Payment record model"""

    def __init__(
        self,
        payment_id: str,
        user_id: str,
        subscription_id: str,
        invoice_id: str,
        amount: Decimal,
        currency: str = "USD",
        payment_method: str = "stripe",
        status: PaymentStatus = PaymentStatus.PENDING
    ):
        self.payment_id = payment_id
        self.user_id = user_id
        self.subscription_id = subscription_id
        self.invoice_id = invoice_id
        self.amount = amount
        self.currency = currency
        self.payment_method = payment_method
        self.status = status
        self.created_at = datetime.utcnow()
        self.processed_at: Optional[datetime] = None
        self.stripe_payment_intent_id: Optional[str] = None
        self.stripe_customer_id: Optional[str] = None
        self.error_message: Optional[str] = None

    def mark_succeeded(self) -> None:
        """Mark payment as succeeded"""
        self.status = PaymentStatus.SUCCEEDED
        self.processed_at = datetime.utcnow()
        logger.info(f"Payment {self.payment_id} succeeded")

    def mark_failed(self, error_message: str) -> None:
        """Mark payment as failed"""
        self.status = PaymentStatus.FAILED
        self.processed_at = datetime.utcnow()
        self.error_message = error_message
        logger.error(f"Payment {self.payment_id} failed: {error_message}")

    def to_dict(self) -> Dict:
        """Convert to dictionary"""
        return {
            'payment_id': self.payment_id,
            'user_id': self.user_id,
            'subscription_id': self.subscription_id,
            'invoice_id': self.invoice_id,
            'amount': float(self.amount),
            'currency': self.currency,
            'payment_method': self.payment_method,
            'status': self.status.value,
            'created_at': self.created_at.isoformat(),
            'processed_at': self.processed_at.isoformat() if self.processed_at else None,
            'error_message': self.error_message
        }


class PaymentProcessor:
    """Handle payment processing and webhooks"""

    def __init__(self, stripe_api_key: Optional[str] = None):
        self._stripe_api_key = stripe_api_key
        self._payments: Dict[str, Payment] = {}
        self._webhook_handlers: Dict[str, Callable] = {}
        self._configure_webhooks()

    def _configure_webhooks(self) -> None:
        """Configure webhook handlers"""
        self._webhook_handlers = {
            'payment_intent.succeeded': self._handle_payment_succeeded,
            'payment_intent.failed': self._handle_payment_failed,
            'customer.subscription.created': self._handle_subscription_created,
            'customer.subscription.deleted': self._handle_subscription_cancelled,
        }

    def create_payment(
        self,
        user_id: str,
        subscription_id: str,
        tier: SubscriptionTier,
        duration_months: int = 1
    ) -> tuple:
        """Create a payment for subscription"""
        import uuid

        # Generate access code
        access_code_obj = access_code_generator.generate_code(
            tier=tier,
            duration_days=30 * duration_months
        )

        # Create invoice
        invoice = invoice_generator.create_invoice(
            user_id=user_id,
            subscription_id=subscription_id,
            tier=tier,
            access_code=access_code_obj.code,
            duration_months=duration_months
        )

        # Create payment record
        payment_id = f"PAY-{uuid.uuid4().hex[:12].upper()}"
        payment = Payment(
            payment_id=payment_id,
            user_id=user_id,
            subscription_id=subscription_id,
            invoice_id=invoice.invoice_id,
            amount=invoice.amount,
            currency=invoice.currency,
            payment_method="stripe",
            status=PaymentStatus.PENDING
        )

        self._payments[payment_id] = payment

        logger.info(
            f"Created payment {payment_id} for ${invoice.amount} "
            f"with access code {access_code_obj.code}"
        )

        return payment, invoice, access_code_obj

    def process_payment(self, payment_id: str) -> bool:
        """Process a payment (simulate Stripe processing)"""
        payment = self._payments.get(payment_id)
        if not payment:
            logger.error(f"Payment {payment_id} not found")
            return False

        payment.status = PaymentStatus.PROCESSING

        # In production, this would call Stripe API
        # For now, simulate success
        try:
            # Simulate Stripe payment processing
            payment.stripe_payment_intent_id = f"pi_{payment_id}"
            payment.stripe_customer_id = f"cus_{payment.user_id}"

            # Mark payment as succeeded
            payment.mark_succeeded()

            # Update invoice
            invoice_generator.mark_invoice_paid(payment.invoice_id)

            # Activate subscription
            subscription = subscription_manager.get_subscription(payment.subscription_id)
            if subscription:
                subscription.status = SubscriptionStatus.ACTIVE
                logger.info(f"Activated subscription {subscription.subscription_id}")

            # Trigger success webhook
            self._handle_payment_succeeded({
                'payment_id': payment_id,
                'amount': float(payment.amount),
                'user_id': payment.user_id
            })

            return True

        except Exception as e:
            payment.mark_failed(str(e))
            return False

    def _handle_payment_succeeded(self, event_data: Dict) -> None:
        """Handle successful payment webhook"""
        payment_id = event_data.get('payment_id')
        logger.info(f"Payment succeeded webhook: {payment_id}")

        # Send confirmation email (would integrate with email service)
        # Generate access code email
        # Update subscription status

    def _handle_payment_failed(self, event_data: Dict) -> None:
        """Handle failed payment webhook"""
        payment_id = event_data.get('payment_id')
        error = event_data.get('error', 'Unknown error')
        logger.error(f"Payment failed webhook: {payment_id} - {error}")

        # Send failure notification
        # Update subscription status

    def _handle_subscription_created(self, event_data: Dict) -> None:
        """Handle subscription created webhook"""
        subscription_id = event_data.get('subscription_id')
        logger.info(f"Subscription created webhook: {subscription_id}")

    def _handle_subscription_cancelled(self, event_data: Dict) -> None:
        """Handle subscription cancelled webhook"""
        subscription_id = event_data.get('subscription_id')
        logger.info(f"Subscription cancelled webhook: {subscription_id}")

        # Cancel subscription
        subscription_manager.cancel_subscription(subscription_id)

    def handle_webhook(self, event_type: str, event_data: Dict) -> bool:
        """Handle Stripe webhook"""
        handler = self._webhook_handlers.get(event_type)
        if not handler:
            logger.warning(f"No handler for webhook type: {event_type}")
            return False

        try:
            handler(event_data)
            return True
        except Exception as e:
            logger.error(f"Error handling webhook {event_type}: {e}")
            return False

    def create_stripe_payment_intent(
        self,
        amount: Decimal,
        currency: str = "USD",
        customer_id: Optional[str] = None
    ) -> Optional[str]:
        """Create Stripe payment intent (placeholder)"""
        # In production, would use Stripe SDK
        # stripe.PaymentIntent.create(amount=amount, currency=currency, ...)

        import uuid
        intent_id = f"pi_{uuid.uuid4().hex[:24]}"
        logger.info(f"Created Stripe payment intent: {intent_id}")
        return intent_id

    def refund_payment(self, payment_id: str, amount: Optional[Decimal] = None) -> bool:
        """Refund a payment"""
        payment = self._payments.get(payment_id)
        if not payment:
            return False

        if payment.status != PaymentStatus.SUCCEEDED:
            logger.error(f"Cannot refund payment {payment_id} with status {payment.status}")
            return False

        refund_amount = amount or payment.amount

        # In production, would call Stripe refund API
        # stripe.Refund.create(payment_intent=payment.stripe_payment_intent_id, ...)

        payment.status = PaymentStatus.REFUNDED
        invoice_generator.refund_invoice(payment.invoice_id)

        logger.info(f"Refunded payment {payment_id}: ${refund_amount}")
        return True

    def get_payment(self, payment_id: str) -> Optional[Payment]:
        """Get payment by ID"""
        return self._payments.get(payment_id)

    def get_user_payments(self, user_id: str) -> list:
        """Get all payments for a user"""
        return [p for p in self._payments.values() if p.user_id == user_id]

    def get_payment_stats(self) -> Dict:
        """Get payment statistics"""
        total = len(self._payments)
        succeeded = len([p for p in self._payments.values() if p.status == PaymentStatus.SUCCEEDED])
        failed = len([p for p in self._payments.values() if p.status == PaymentStatus.FAILED])
        pending = len([p for p in self._payments.values() if p.status == PaymentStatus.PENDING])

        total_amount = sum(p.amount for p in self._payments.values() if p.status == PaymentStatus.SUCCEEDED)

        return {
            'total_payments': total,
            'succeeded': succeeded,
            'failed': failed,
            'pending': pending,
            'total_revenue': float(total_amount),
            'success_rate': (succeeded / total * 100) if total > 0 else 0.0
        }


# Global payment processor instance
payment_processor = PaymentProcessor()
