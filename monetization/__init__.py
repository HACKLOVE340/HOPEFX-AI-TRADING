"""
Monetization Module for HOPEFX AI Trading Platform

This module handles:
- Subscription management ($1,800 - $10,000/month tiers)
- Payment processing (Stripe integration)
- Access code generation and validation
- Commission tracking (0.1% - 0.5% per trade)
- Invoice generation
- License validation
"""

from .pricing import PricingTier, get_tier_by_price, get_tier_info
from .subscription import SubscriptionManager, SubscriptionStatus
from .commission import CommissionTracker, calculate_commission
from .access_codes import AccessCodeGenerator, validate_access_code
from .invoices import InvoiceGenerator, Invoice
from .payment_processor import PaymentProcessor, process_payment
from .license import LicenseValidator, check_feature_access

__all__ = [
    'PricingTier',
    'get_tier_by_price',
    'get_tier_info',
    'SubscriptionManager',
    'SubscriptionStatus',
    'CommissionTracker',
    'calculate_commission',
    'AccessCodeGenerator',
    'validate_access_code',
    'InvoiceGenerator',
    'Invoice',
    'PaymentProcessor',
    'process_payment',
    'LicenseValidator',
    'check_feature_access',
]

__version__ = '1.0.0'
