"""
Monetization Module for HOPEFX AI Trading Platform

This module handles:
- Subscription management ($0 Free tier to $10,000/month tiers)
- Payment processing (Stripe integration)
- Access code generation and validation
- Commission tracking (0.1% - 1.0% per trade)
- Invoice generation
- License validation
- Affiliate/referral program
- Strategy marketplace
- Revenue analytics
- Enterprise and white-label features
- Partner program
"""

# Pricing
from .pricing import (
    SubscriptionTier,
    BillingCycle,
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

# Stripe Integration
from .stripe_integration import (
    StripeIntegration,
    StripeCustomer,
    StripePaymentIntent,
    StripeSubscription,
    StripeWebhookEvent,
    stripe_integration
)

# Affiliate Program
from .affiliate import (
    AffiliateStatus,
    AffiliateLevel,
    ReferralStatus,
    PayoutStatus,
    Affiliate,
    Referral,
    Payout,
    AffiliateManager,
    affiliate_manager
)

# Strategy Marketplace
from .marketplace import (
    StrategyCategory,
    StrategyStatus,
    StrategyLicenseType,
    PurchaseStatus,
    MarketplaceStrategy,
    StrategyPurchase,
    StrategyReview,
    StrategyMarketplace,
    strategy_marketplace
)

# Revenue Analytics
from .analytics import (
    RevenueSource,
    TimePeriod,
    RevenueEntry,
    RevenueAnalytics,
    revenue_analytics
)

# Enterprise Features
from .enterprise import (
    PartnerType,
    PartnerStatus,
    WhiteLabelStatus,
    WhiteLabelConfig,
    EnterpriseFeatures,
    Partner,
    WhiteLabelInstance,
    EnterpriseCustomer,
    EnterpriseManager,
    enterprise_manager
)

__all__ = [
    # Pricing
    'SubscriptionTier',
    'BillingCycle',
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

    # Stripe Integration
    'StripeIntegration',
    'StripeCustomer',
    'StripePaymentIntent',
    'StripeSubscription',
    'StripeWebhookEvent',
    'stripe_integration',

    # Affiliate Program
    'AffiliateStatus',
    'AffiliateLevel',
    'ReferralStatus',
    'Affiliate',
    'Referral',
    'Payout',
    'AffiliateManager',
    'affiliate_manager',

    # Strategy Marketplace
    'StrategyCategory',
    'StrategyStatus',
    'StrategyLicenseType',
    'MarketplaceStrategy',
    'StrategyPurchase',
    'StrategyReview',
    'StrategyMarketplace',
    'strategy_marketplace',

    # Revenue Analytics
    'RevenueSource',
    'TimePeriod',
    'RevenueEntry',
    'RevenueAnalytics',
    'revenue_analytics',

    # Enterprise Features
    'PartnerType',
    'PartnerStatus',
    'WhiteLabelStatus',
    'WhiteLabelConfig',
    'EnterpriseFeatures',
    'Partner',
    'WhiteLabelInstance',
    'EnterpriseCustomer',
    'EnterpriseManager',
    'enterprise_manager',
]

__version__ = '2.0.0'
