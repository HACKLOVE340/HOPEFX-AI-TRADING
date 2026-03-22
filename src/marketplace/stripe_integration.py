"""
Production Stripe integration for strategy marketplace.
"""
from typing import Optional, Dict, Any
from decimal import Decimal
import stripe
from src.config.settings import get_settings
import structlog

logger = structlog.get_logger()

settings = get_settings()


class StripeManager:
    """
    Institutional-grade Stripe integration for subscriptions.
    Handles products, prices, customers, and subscriptions.
    """
    
    def __init__(self):
        self.api_key = settings.stripe.secret_key.get_secret_value() if settings.stripe.secret_key else None
        if self.api_key:
            stripe.api_key = self.api_key
        self.webhook_secret = settings.stripe.webhook_secret.get_secret_value() if settings.stripe.webhook_secret else None
    
    async def create_strategy_product(self, 
                                       name: str, 
                                       description: str,
                                       price_monthly: Decimal,
                                       price_yearly: Optional[Decimal] = None) -> Dict[str, Any]:
        """
        Create Stripe product and prices for a strategy.
        """
        if not self.api_key:
            raise ValueError("Stripe API key not configured")
        
        try:
            # Create product
            product = stripe.Product.create(
                name=f"HOPEFX Strategy: {name}",
                description=description,
                type="service",
                metadata={"platform": "hopefx", "category": "trading_strategy"}
            )
            
            # Create monthly price
            monthly_price = stripe.Price.create(
                product=product.id,
                unit_amount=int(price_monthly * 100),  # Convert to cents
                currency="usd",
                recurring={"interval": "month"},
                metadata={"billing_period": "monthly"}
            )
            
            result = {
                "product_id": product.id,
                "price_monthly_id": monthly_price.id
            }
            
            # Create yearly price if provided
            if price_yearly:
                yearly_price = stripe.Price.create(
                    product=product.id,
                    unit_amount=int(price_yearly * 100),
                    currency="usd",
                    recurring={"interval": "year"},
                    metadata={"billing_period": "yearly"}
                )
                result["price_yearly_id"] = yearly_price.id
            
            logger.info("stripe_product_created", product_id=product.id, name=name)
            return result
            
        except stripe.error.StripeError as e:
            logger.error("stripe_product_creation_failed", error=str(e))
            raise
    
    async def create_customer(self, 
                             email: str, 
                             user_id: str,
                             payment_method_id: Optional[str] = None) -> str:
        """
        Create or retrieve Stripe customer.
        """
        if not self.api_key:
            raise ValueError("Stripe API key not configured")
        
        try:
            # Check if customer exists
            existing = stripe.Customer.list(email=email, limit=1)
            if existing.data:
                customer = existing.data[0]
                logger.info("stripe_customer_retrieved", customer_id=customer.id)
                return customer.id
            
            # Create new customer
            customer_data = {
                "email": email,
                "metadata": {"hopefx_user_id": user_id}
            }
            
            if payment_method_id:
                customer_data["payment_method"] = payment_method_id
                customer_data["invoice_settings"] = {
                    "default_payment_method": payment_method_id
                }
            
            customer = stripe.Customer.create(**customer_data)
            logger.info("stripe_customer_created", customer_id=customer.id)
            return customer.id
            
        except stripe.error.StripeError as e:
            logger.error("stripe_customer_creation_failed", error=str(e))
            raise
    
    async def create_subscription(self,
                                   customer_id: str,
                                   price_id: str,
                                   trial_days: int = 7,
                                   metadata: Optional[Dict] = None) -> Dict[str, Any]:
        """
        Create subscription with trial period.
        """
        if not self.api_key:
            raise ValueError("Stripe API key not configured")
        
        try:
            subscription_data = {
                "customer": customer_id,
                "items": [{"price": price_id}],
                "trial_period_days": trial_days,
                "payment_behavior": "default_incomplete",
                "expand": ["latest_invoice.payment_intent"],
                "metadata": metadata or {}
            }
            
            subscription = stripe.Subscription.create(**subscription_data)
            
            logger.info("stripe_subscription_created", 
                       subscription_id=subscription.id,
                       customer_id=customer_id,
                       status=subscription.status)
            
            return {
                "subscription_id": subscription.id,
                "status": subscription.status,
                "client_secret": subscription.latest_invoice.payment_intent.client_secret 
                                if subscription.latest_invoice and subscription.latest_invoice.payment_intent 
                                else None,
                "current_period_start": subscription.current_period_start,
                "current_period_end": subscription.current_period_end,
                "trial_end": subscription.trial_end
            }
            
        except stripe.error.StripeError as e:
            logger.error("stripe_subscription_creation_failed", error=str(e))
            raise
    
    async def cancel_subscription(self, subscription_id: str, 
                                   at_period_end: bool = True) -> bool:
        """
        Cancel subscription.
        """
        if not self.api_key:
            raise ValueError("Stripe API key not configured")
        
        try:
            if at_period_end:
                subscription = stripe.Subscription.modify(
                    subscription_id,
                    cancel_at_period_end=True
                )
            else:
                subscription = stripe.Subscription.delete(subscription_id)
            
            logger.info("stripe_subscription_cancelled", 
                       subscription_id=subscription_id,
                       at_period_end=at_period_end)
            return True
            
        except stripe.error.StripeError as e:
            logger.error("stripe_subscription_cancellation_failed", error=str(e))
            return False
    
    async def handle_webhook(self, payload: bytes, signature: str) -> Dict[str, Any]:
        """
        Process Stripe webhook events securely.
        """
        if not self.webhook_secret:
            raise ValueError("Webhook secret not configured")
        
        try:
            event = stripe.Webhook.construct_event(
                payload, signature, self.webhook_secret
            )
            
            logger.info("stripe_webhook_received", event_type=event.type)
            
            if event.type == "invoice.payment_succeeded":
                return await self._handle_payment_succeeded(event.data.object)
            elif event.type == "invoice.payment_failed":
                return await self._handle_payment_failed(event.data.object)
            elif event.type == "customer.subscription.deleted":
                return await self._handle_subscription_deleted(event.data.object)
            
            return {"status": "ignored", "event_type": event.type}
            
        except stripe.error.SignatureVerificationError:
            logger.error("stripe_webhook_invalid_signature")
            raise ValueError("Invalid webhook signature")
        except Exception as e:
            logger.error("stripe_webhook_processing_failed", error=str(e))
            raise
    
    async def _handle_payment_succeeded(self, invoice: Dict) -> Dict:
        """Handle successful payment."""
        subscription_id = invoice.get("subscription")
        logger.info("payment_succeeded", subscription_id=subscription_id)
        return {
            "status": "processed",
            "event": "payment_succeeded",
            "subscription_id": subscription_id
        }
    
    async def _handle_payment_failed(self, invoice: Dict) -> Dict:
        """Handle failed payment."""
        subscription_id = invoice.get("subscription")
        logger.warning("payment_failed", subscription_id=subscription_id)
        return {
            "status": "processed",
            "event": "payment_failed",
            "subscription_id": subscription_id
        }
    
    async def _handle_subscription_deleted(self, subscription: Dict) -> Dict:
        """Handle subscription cancellation."""
        logger.info("subscription_deleted", subscription_id=subscription.id)
        return {
            "status": "processed",
            "event": "subscription_deleted",
            "subscription_id": subscription.id
        }
