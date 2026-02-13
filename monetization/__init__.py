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

# Pricing
from .pricing import (
    SubscriptionTier,
    TierFeatures,
    PricingTier,
    PricingManager,
    pricing_manager
)

# Subscription
from .subscription import (
    SubscriptionStatus,
    Subscription,
    SubscriptionManager,
    subscription_manager
)

# Commission
from .commission import (
    CommissionStatus,
    Commission,
    CommissionTracker,
    commission_tracker
)

# Access Codes
from .access_codes import (
    AccessCodeStatus,
    AccessCode,
    AccessCodeGenerator,
    access_code_generator
)

# Invoices
from .invoices import (
    InvoiceStatus,
    Invoice,
    InvoiceGenerator,
    invoice_generator
)

# Payment Processing
from .payment_processor import (
    PaymentStatus,
    Payment,
    PaymentProcessor,
    payment_processor
)

# License Validation
from .license import (
    ValidationResult,
    LicenseValidator,
    license_validator
)

__all__ = [
    # Pricing
    'SubscriptionTier',
    'TierFeatures',
    'PricingTier',
    'PricingManager',
    'pricing_manager',
    
    # Subscription
    'SubscriptionStatus',
    'Subscription',
    'SubscriptionManager',
    'subscription_manager',
    
    # Commission
    'CommissionStatus',
    'Commission',
    'CommissionTracker',
    'commission_tracker',
    
    # Access Codes
    'AccessCodeStatus',
    'AccessCode',
    'AccessCodeGenerator',
    'access_code_generator',
    
    # Invoices
    'InvoiceStatus',
    'Invoice',
    'InvoiceGenerator',
    'invoice_generator',
    
    # Payment Processing
    'PaymentStatus',
    'Payment',
    'PaymentProcessor',
    'payment_processor',
    
    # License Validation
    'ValidationResult',
    'LicenseValidator',
    'license_validator',
]

__version__ = '1.0.0'
