"""
Stripe Payment Gateway Integration

This module provides real Stripe SDK integration for:
- Creating payment intents
- Handling subscriptions
- Processing webhooks
- Managing customers
- Handling refunds
"""

import logging
import os
import hmac
import hashlib
from datetime import datetime
from decimal import Decimal
from typing import Optional, Dict, Any, List
from enum import Enum

from .pricing import SubscriptionTier, BillingCycle, pricing_manager

logger = logging.getLogger(__name__)


class StripeWebhookEvent(str, Enum):
    """Stripe webhook event types"""
    PAYMENT_INTENT_SUCCEEDED = "payment_intent.succeeded"
    PAYMENT_INTENT_FAILED = "payment_intent.payment_failed"
    CHECKOUT_SESSION_COMPLETED = "checkout.session.completed"
    CUSTOMER_SUBSCRIPTION_CREATED = "customer.subscription.created"
    CUSTOMER_SUBSCRIPTION_UPDATED = "customer.subscription.updated"
    CUSTOMER_SUBSCRIPTION_DELETED = "customer.subscription.deleted"
    INVOICE_PAID = "invoice.paid"
    INVOICE_PAYMENT_FAILED = "invoice.payment_failed"


class StripeCustomer:
    """Stripe customer model"""

    def __init__(
        self,
        customer_id: str,
        user_id: str,
        email: str,
        name: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None
    ):
        self.customer_id = customer_id
        self.user_id = user_id
        self.email = email
        self.name = name
        self.metadata = metadata or {}
        self.created_at = datetime.utcnow()

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary"""
        return {
            'customer_id': self.customer_id,
            'user_id': self.user_id,
            'email': self.email,
            'name': self.name,
            'metadata': self.metadata,
            'created_at': self.created_at.isoformat()
        }


class StripePaymentIntent:
    """Stripe payment intent model"""

    def __init__(
        self,
        intent_id: str,
        customer_id: str,
        amount: int,  # in cents
        currency: str,
        status: str,
        metadata: Optional[Dict[str, Any]] = None
    ):
        self.intent_id = intent_id
        self.customer_id = customer_id
        self.amount = amount
        self.currency = currency
        self.status = status
        self.metadata = metadata or {}
        self.created_at = datetime.utcnow()
        self.client_secret: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary"""
        return {
            'intent_id': self.intent_id,
            'customer_id': self.customer_id,
            'amount': self.amount,
            'amount_display': self.amount / 100,  # Convert cents to dollars
            'currency': self.currency,
            'status': self.status,
            'metadata': self.metadata,
            'created_at': self.created_at.isoformat()
        }


class StripeSubscription:
    """Stripe subscription model"""

    def __init__(
        self,
        subscription_id: str,
        customer_id: str,
        tier: SubscriptionTier,
        billing_cycle: BillingCycle,
        status: str,
        current_period_start: datetime,
        current_period_end: datetime,
        cancel_at_period_end: bool = False
    ):
        self.subscription_id = subscription_id
        self.customer_id = customer_id
        self.tier = tier
        self.billing_cycle = billing_cycle
        self.status = status
        self.current_period_start = current_period_start
        self.current_period_end = current_period_end
        self.cancel_at_period_end = cancel_at_period_end
        self.created_at = datetime.utcnow()

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary"""
        return {
            'subscription_id': self.subscription_id,
            'customer_id': self.customer_id,
            'tier': self.tier.value,
            'billing_cycle': self.billing_cycle.value,
            'status': self.status,
            'current_period_start': self.current_period_start.isoformat(),
            'current_period_end': self.current_period_end.isoformat(),
            'cancel_at_period_end': self.cancel_at_period_end,
            'created_at': self.created_at.isoformat()
        }


class StripeIntegration:
    """
    Stripe payment integration handler.
    
    This class provides methods for integrating with Stripe's API
    for payment processing, subscription management, and webhook handling.
    
    In production, this would use the actual Stripe SDK (import stripe).
    For development/testing, it provides mock implementations.
    """

    # Stripe price IDs mapping (would be configured from Stripe Dashboard)
    PRICE_IDS = {
        (SubscriptionTier.FREE, BillingCycle.MONTHLY): None,  # No payment needed
        (SubscriptionTier.STARTER, BillingCycle.MONTHLY): "price_starter_monthly",
        (SubscriptionTier.STARTER, BillingCycle.ANNUAL): "price_starter_annual",
        (SubscriptionTier.PROFESSIONAL, BillingCycle.MONTHLY): "price_professional_monthly",
        (SubscriptionTier.PROFESSIONAL, BillingCycle.ANNUAL): "price_professional_annual",
        (SubscriptionTier.ENTERPRISE, BillingCycle.MONTHLY): "price_enterprise_monthly",
        (SubscriptionTier.ENTERPRISE, BillingCycle.ANNUAL): "price_enterprise_annual",
        (SubscriptionTier.ELITE, BillingCycle.MONTHLY): "price_elite_monthly",
        (SubscriptionTier.ELITE, BillingCycle.ANNUAL): "price_elite_annual",
    }

    def __init__(
        self,
        api_key: Optional[str] = None,
        webhook_secret: Optional[str] = None,
        test_mode: bool = True
    ):
        """
        Initialize Stripe integration.
        
        Args:
            api_key: Stripe API key (defaults to env var STRIPE_SECRET_KEY)
            webhook_secret: Stripe webhook secret (defaults to env var STRIPE_WEBHOOK_SECRET)
            test_mode: Whether to run in test/sandbox mode
        """
        self.api_key = api_key or os.getenv('STRIPE_SECRET_KEY', '')
        self.webhook_secret = webhook_secret or os.getenv('STRIPE_WEBHOOK_SECRET', '')
        self.test_mode = test_mode
        
        # Storage for mock mode
        self._customers: Dict[str, StripeCustomer] = {}
        self._payment_intents: Dict[str, StripePaymentIntent] = {}
        self._subscriptions: Dict[str, StripeSubscription] = {}
        
        # Check if real Stripe SDK is available
        self._stripe_sdk_available = self._check_stripe_sdk()
        
        if self._stripe_sdk_available and self.api_key:
            self._configure_stripe()
        else:
            logger.warning(
                "Stripe SDK not available or API key not set. "
                "Running in mock mode for development."
            )

    def _check_stripe_sdk(self) -> bool:
        """Check if Stripe SDK is available"""
        try:
            import stripe
            return True
        except ImportError:
            return False

    def _configure_stripe(self) -> None:
        """Configure Stripe SDK with API key"""
        try:
            import stripe
            stripe.api_key = self.api_key
            logger.info("Stripe SDK configured successfully")
        except ImportError:
            logger.warning("Stripe SDK not installed")

    def create_customer(
        self,
        user_id: str,
        email: str,
        name: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> StripeCustomer:
        """
        Create a Stripe customer.
        
        Args:
            user_id: Internal user ID
            email: Customer email
            name: Customer name
            metadata: Additional metadata
            
        Returns:
            StripeCustomer object
        """
        try:
            if self._stripe_sdk_available and self.api_key and not self.test_mode:
                import stripe
                customer = stripe.Customer.create(
                    email=email,
                    name=name,
                    metadata={'user_id': user_id, **(metadata or {})}
                )
                stripe_customer = StripeCustomer(
                    customer_id=customer.id,
                    user_id=user_id,
                    email=email,
                    name=name,
                    metadata=metadata
                )
            else:
                # Mock implementation
                import uuid
                customer_id = f"cus_{uuid.uuid4().hex[:14]}"
                stripe_customer = StripeCustomer(
                    customer_id=customer_id,
                    user_id=user_id,
                    email=email,
                    name=name,
                    metadata=metadata
                )
                
            self._customers[stripe_customer.customer_id] = stripe_customer
            logger.info(f"Created Stripe customer: {stripe_customer.customer_id}")
            return stripe_customer
            
        except Exception as e:
            logger.error(f"Error creating Stripe customer: {e}")
            raise

    def create_payment_intent(
        self,
        customer_id: str,
        amount: Decimal,
        currency: str = "usd",
        tier: Optional[SubscriptionTier] = None,
        billing_cycle: BillingCycle = BillingCycle.MONTHLY,
        metadata: Optional[Dict[str, Any]] = None
    ) -> StripePaymentIntent:
        """
        Create a payment intent for one-time payments.
        
        Args:
            customer_id: Stripe customer ID
            amount: Amount in dollars
            currency: Currency code
            tier: Subscription tier (for metadata)
            billing_cycle: Billing cycle
            metadata: Additional metadata
            
        Returns:
            StripePaymentIntent object with client_secret
        """
        try:
            amount_cents = int(amount * 100)  # Convert to cents
            
            intent_metadata = {
                'tier': tier.value if tier else None,
                'billing_cycle': billing_cycle.value,
                **(metadata or {})
            }
            
            if self._stripe_sdk_available and self.api_key and not self.test_mode:
                import stripe
                intent = stripe.PaymentIntent.create(
                    amount=amount_cents,
                    currency=currency,
                    customer=customer_id,
                    metadata=intent_metadata,
                    automatic_payment_methods={'enabled': True}
                )
                payment_intent = StripePaymentIntent(
                    intent_id=intent.id,
                    customer_id=customer_id,
                    amount=amount_cents,
                    currency=currency,
                    status=intent.status,
                    metadata=intent_metadata
                )
                payment_intent.client_secret = intent.client_secret
            else:
                # Mock implementation
                import uuid
                intent_id = f"pi_{uuid.uuid4().hex[:24]}"
                payment_intent = StripePaymentIntent(
                    intent_id=intent_id,
                    customer_id=customer_id,
                    amount=amount_cents,
                    currency=currency,
                    status="requires_payment_method",
                    metadata=intent_metadata
                )
                payment_intent.client_secret = f"{intent_id}_secret_{uuid.uuid4().hex[:24]}"
                
            self._payment_intents[payment_intent.intent_id] = payment_intent
            logger.info(f"Created payment intent: {payment_intent.intent_id}")
            return payment_intent
            
        except Exception as e:
            logger.error(f"Error creating payment intent: {e}")
            raise

    def create_checkout_session(
        self,
        customer_id: str,
        tier: SubscriptionTier,
        billing_cycle: BillingCycle = BillingCycle.MONTHLY,
        success_url: str = "https://app.hopefx.ai/success",
        cancel_url: str = "https://app.hopefx.ai/cancel"
    ) -> Dict[str, Any]:
        """
        Create a Stripe Checkout session for subscription.
        
        Args:
            customer_id: Stripe customer ID
            tier: Subscription tier
            billing_cycle: Monthly or Annual
            success_url: Redirect URL on success
            cancel_url: Redirect URL on cancel
            
        Returns:
            Checkout session info with URL
        """
        try:
            price_id = self.PRICE_IDS.get((tier, billing_cycle))
            
            if not price_id:
                raise ValueError(f"No price configured for {tier.value} {billing_cycle.value}")
                
            if self._stripe_sdk_available and self.api_key and not self.test_mode:
                import stripe
                session = stripe.checkout.Session.create(
                    customer=customer_id,
                    payment_method_types=['card'],
                    line_items=[{
                        'price': price_id,
                        'quantity': 1,
                    }],
                    mode='subscription',
                    success_url=success_url,
                    cancel_url=cancel_url,
                    metadata={
                        'tier': tier.value,
                        'billing_cycle': billing_cycle.value
                    }
                )
                return {
                    'session_id': session.id,
                    'url': session.url,
                    'tier': tier.value,
                    'billing_cycle': billing_cycle.value
                }
            else:
                # Mock implementation
                import uuid
                session_id = f"cs_{uuid.uuid4().hex[:24]}"
                return {
                    'session_id': session_id,
                    'url': f"https://checkout.stripe.com/mock/{session_id}",
                    'tier': tier.value,
                    'billing_cycle': billing_cycle.value,
                    'test_mode': True
                }
                
        except Exception as e:
            logger.error(f"Error creating checkout session: {e}")
            raise

    def create_subscription(
        self,
        customer_id: str,
        tier: SubscriptionTier,
        billing_cycle: BillingCycle = BillingCycle.MONTHLY
    ) -> StripeSubscription:
        """
        Create a subscription for a customer.
        
        Args:
            customer_id: Stripe customer ID
            tier: Subscription tier
            billing_cycle: Monthly or Annual
            
        Returns:
            StripeSubscription object
        """
        try:
            price_id = self.PRICE_IDS.get((tier, billing_cycle))
            
            if self._stripe_sdk_available and self.api_key and not self.test_mode:
                import stripe
                subscription = stripe.Subscription.create(
                    customer=customer_id,
                    items=[{'price': price_id}],
                    metadata={
                        'tier': tier.value,
                        'billing_cycle': billing_cycle.value
                    }
                )
                stripe_sub = StripeSubscription(
                    subscription_id=subscription.id,
                    customer_id=customer_id,
                    tier=tier,
                    billing_cycle=billing_cycle,
                    status=subscription.status,
                    current_period_start=datetime.fromtimestamp(
                        subscription.current_period_start
                    ),
                    current_period_end=datetime.fromtimestamp(
                        subscription.current_period_end
                    )
                )
            else:
                # Mock implementation
                import uuid
                from datetime import timedelta
                
                sub_id = f"sub_{uuid.uuid4().hex[:14]}"
                now = datetime.utcnow()
                
                if billing_cycle == BillingCycle.ANNUAL:
                    period_end = now + timedelta(days=365)
                else:
                    period_end = now + timedelta(days=30)
                    
                stripe_sub = StripeSubscription(
                    subscription_id=sub_id,
                    customer_id=customer_id,
                    tier=tier,
                    billing_cycle=billing_cycle,
                    status="active",
                    current_period_start=now,
                    current_period_end=period_end
                )
                
            self._subscriptions[stripe_sub.subscription_id] = stripe_sub
            logger.info(f"Created subscription: {stripe_sub.subscription_id}")
            return stripe_sub
            
        except Exception as e:
            logger.error(f"Error creating subscription: {e}")
            raise

    def cancel_subscription(
        self,
        subscription_id: str,
        at_period_end: bool = True
    ) -> bool:
        """
        Cancel a subscription.
        
        Args:
            subscription_id: Stripe subscription ID
            at_period_end: Whether to cancel at period end or immediately
            
        Returns:
            True if successful
        """
        try:
            if self._stripe_sdk_available and self.api_key and not self.test_mode:
                import stripe
                if at_period_end:
                    stripe.Subscription.modify(
                        subscription_id,
                        cancel_at_period_end=True
                    )
                else:
                    stripe.Subscription.delete(subscription_id)
            else:
                # Mock implementation
                if subscription_id in self._subscriptions:
                    sub = self._subscriptions[subscription_id]
                    if at_period_end:
                        sub.cancel_at_period_end = True
                    else:
                        sub.status = "canceled"
                        
            logger.info(f"Cancelled subscription: {subscription_id}")
            return True
            
        except Exception as e:
            logger.error(f"Error cancelling subscription: {e}")
            return False

    def verify_webhook_signature(
        self,
        payload: bytes,
        signature: str
    ) -> bool:
        """
        Verify Stripe webhook signature.
        
        Args:
            payload: Raw webhook payload
            signature: Stripe-Signature header
            
        Returns:
            True if signature is valid
        """
        if not self.webhook_secret:
            logger.warning("Webhook secret not configured")
            return False
            
        try:
            if self._stripe_sdk_available:
                import stripe
                stripe.Webhook.construct_event(
                    payload, signature, self.webhook_secret
                )
                return True
            else:
                # Simple HMAC verification for testing
                expected_sig = hmac.new(
                    self.webhook_secret.encode(),
                    payload,
                    hashlib.sha256
                ).hexdigest()
                return hmac.compare_digest(expected_sig, signature)
                
        except Exception as e:
            logger.error(f"Webhook signature verification failed: {e}")
            return False

    def handle_webhook(
        self,
        event_type: str,
        event_data: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Handle Stripe webhook event.
        
        Args:
            event_type: Stripe event type
            event_data: Event payload data
            
        Returns:
            Processing result
        """
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
        else:
            logger.info(f"Unhandled webhook event type: {event_type}")
            return {'status': 'ignored', 'event_type': event_type}

    def _handle_payment_success(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Handle successful payment"""
        logger.info(f"Payment succeeded: {data.get('id')}")
        return {'status': 'success', 'action': 'payment_confirmed'}

    def _handle_payment_failed(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Handle failed payment"""
        logger.warning(f"Payment failed: {data.get('id')}")
        return {'status': 'failed', 'action': 'payment_retry_needed'}

    def _handle_checkout_completed(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Handle checkout session completed"""
        logger.info(f"Checkout completed: {data.get('id')}")
        return {'status': 'success', 'action': 'subscription_activated'}

    def _handle_subscription_created(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Handle subscription created"""
        logger.info(f"Subscription created: {data.get('id')}")
        return {'status': 'success', 'action': 'access_granted'}

    def _handle_subscription_updated(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Handle subscription updated"""
        logger.info(f"Subscription updated: {data.get('id')}")
        return {'status': 'success', 'action': 'access_updated'}

    def _handle_subscription_deleted(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Handle subscription deleted/canceled"""
        logger.info(f"Subscription deleted: {data.get('id')}")
        return {'status': 'success', 'action': 'access_revoked'}

    def _handle_invoice_paid(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Handle invoice paid"""
        logger.info(f"Invoice paid: {data.get('id')}")
        return {'status': 'success', 'action': 'invoice_confirmed'}

    def _handle_invoice_failed(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Handle invoice payment failed"""
        logger.warning(f"Invoice payment failed: {data.get('id')}")
        return {'status': 'failed', 'action': 'payment_retry_needed'}

    def refund_payment(
        self,
        payment_intent_id: str,
        amount: Optional[Decimal] = None
    ) -> Dict[str, Any]:
        """
        Refund a payment.
        
        Args:
            payment_intent_id: Payment intent ID to refund
            amount: Amount to refund (full refund if None)
            
        Returns:
            Refund result
        """
        try:
            if self._stripe_sdk_available and self.api_key and not self.test_mode:
                import stripe
                refund_params = {'payment_intent': payment_intent_id}
                if amount:
                    refund_params['amount'] = int(amount * 100)
                refund = stripe.Refund.create(**refund_params)
                return {
                    'refund_id': refund.id,
                    'status': refund.status,
                    'amount': refund.amount / 100
                }
            else:
                # Mock implementation
                import uuid
                refund_id = f"re_{uuid.uuid4().hex[:14]}"
                
                # Get original payment intent
                original = self._payment_intents.get(payment_intent_id)
                refund_amount = float(amount) if amount else (
                    original.amount / 100 if original else 0
                )
                
                return {
                    'refund_id': refund_id,
                    'status': 'succeeded',
                    'amount': refund_amount,
                    'test_mode': True
                }
                
        except Exception as e:
            logger.error(f"Error processing refund: {e}")
            raise

    def get_subscription(self, subscription_id: str) -> Optional[StripeSubscription]:
        """Get subscription by ID"""
        return self._subscriptions.get(subscription_id)

    def get_customer(self, customer_id: str) -> Optional[StripeCustomer]:
        """Get customer by ID"""
        return self._customers.get(customer_id)

    def get_payment_intent(self, intent_id: str) -> Optional[StripePaymentIntent]:
        """Get payment intent by ID"""
        return self._payment_intents.get(intent_id)

    def list_customer_subscriptions(self, customer_id: str) -> List[StripeSubscription]:
        """List all subscriptions for a customer"""
        return [
            sub for sub in self._subscriptions.values()
            if sub.customer_id == customer_id
        ]


# Global Stripe integration instance
stripe_integration = StripeIntegration()
