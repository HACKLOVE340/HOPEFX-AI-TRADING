"""
Stripe payment processing for strategy marketplace.
"""

import asyncio
from dataclasses import dataclass
from decimal import Decimal
from enum import Enum

import stripe

from src.core.config import settings
from src.core.logging_config import get_logger

logger = get_logger(__name__)


class PaymentStatus(Enum):
    PENDING = "pending"
    COMPLETED = "completed"
    FAILED = "failed"
    REFUNDED = "refunded"


@dataclass
class Payment:
    payment_id: str
    user_id: str
    strategy_id: str
    amount: Decimal
    currency: str
    status: PaymentStatus
    stripe_payment_intent_id: str | None = None


class PaymentProcessor:
    """
    Async Stripe payment processing with webhook handling.
    """
    
    def __init__(self, api_key: str | None = None):
        self.api_key = api_key or settings.payments.stripe_api_key
        stripe.api_key = self.api_key
    
    async def create_payment_intent(
        self,
        amount: Decimal,
        currency: str,
        user_id: str,
        strategy_id: str,
        metadata: dict | None = None
    ) -> Payment:
        """Create Stripe payment intent."""
        # Convert to cents
        amount_cents = int(amount * 100)
        
        intent = stripe.PaymentIntent.create(
            amount=amount_cents,
            currency=currency.lower(),
            metadata={
                "user_id": user_id,
                "strategy_id": strategy_id,
                **(metadata or {})
            },
            automatic_payment_methods={"enabled": True}
        )
        
        return Payment(
            payment_id=intent.id,
            user_id=user_id,
            strategy_id=strategy_id,
            amount=amount,
            currency=currency,
            status=PaymentStatus.PENDING,
            stripe_payment_intent_id=intent.id
        )
    
    async def confirm_payment(self, payment_intent_id: str) -> Payment:
        """Confirm payment completion."""
        intent = stripe.PaymentIntent.retrieve(payment_intent_id)
        
        if intent.status == "succeeded":
            status = PaymentStatus.COMPLETED
        elif intent.status in ["requires_payment_method", "canceled"]:
            status = PaymentStatus.FAILED
        else:
            status = PaymentStatus.PENDING
        
        return Payment(
            payment_id=intent.id,
            user_id=intent.metadata.get("user_id", ""),
            strategy_id=intent.metadata.get("strategy_id", ""),
            amount=Decimal(intent.amount) / 100,
            currency=intent.currency.upper(),
            status=status,
            stripe_payment_intent_id=intent.id
        )
    
    async def process_refund(self, payment: Payment, reason: str | None = None) -> bool:
        """Process refund."""
        try:
            stripe.Refund.create(
                payment_intent=payment.stripe_payment_intent_id,
                reason="requested_by_customer" if not reason else None
            )
            return True
        except stripe.error.StripeError as e:
            logger.error(f"Refund failed: {e}")
            return False
    
    async def handle_webhook(self, payload: bytes, signature: str) -> dict:
        """Handle Stripe webhook."""
        webhook_secret = settings.payments.stripe_webhook_secret
        
        try:
            event = stripe.Webhook.construct_event(
                payload, signature, webhook_secret
            )
            
            if event["type"] == "payment_intent.succeeded":
                await self._on_payment_success(event["data"]["object"])
            elif event["type"] == "payment_intent.payment_failed":
                await self._on_payment_failed(event["data"]["object"])
            
            return {"status": "processed"}
            
        except ValueError as e:
            logger.error(f"Invalid webhook payload: {e}")
            return {"error": "Invalid payload"}
        except stripe.error.SignatureVerificationError as e:
            logger.error(f"Invalid webhook signature: {e}")
            return {"error": "Invalid signature"}
    
    async def _on_payment_success(self, payment_intent: dict) -> None:
        """Handle successful payment."""
        user_id = payment_intent["metadata"].get("user_id")
        strategy_id = payment_intent["metadata"].get("strategy_id")
        
        logger.info(f"Payment succeeded for user {user_id}, strategy {strategy_id}")
        
        # Grant license, notify user, etc.
    
    async def _on_payment_failed(self, payment_intent: dict) -> None:
        """Handle failed payment."""
        logger.warning(f"Payment failed: {payment_intent['id']}")
