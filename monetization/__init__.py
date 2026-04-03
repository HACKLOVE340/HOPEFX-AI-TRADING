# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
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
# Access Codes
from .access_codes import (
    AccessCode,
    AccessCodeGenerator,
    AccessCodeStatus,
    access_code_generator,
)

# Affiliate Program
from .affiliate import (
    Affiliate,
    AffiliateLevel,
    AffiliateManager,
    AffiliateStatus,
    Payout,
    PayoutStatus,
    Referral,
    ReferralStatus,
    affiliate_manager,
)

# Revenue Analytics
from .analytics import (
    RevenueAnalytics,
    RevenueEntry,
    RevenueSource,
    TimePeriod,
    revenue_analytics,
)

# Commission
from .commission import (
    Commission,
    CommissionStatus,
    CommissionTracker,
    commission_tracker,
)

# Enterprise Features
from .enterprise import (
    EnterpriseCustomer,
    EnterpriseFeatures,
    EnterpriseManager,
    Partner,
    PartnerStatus,
    PartnerType,
    WhiteLabelConfig,
    WhiteLabelInstance,
    WhiteLabelStatus,
    enterprise_manager,
)

# Invoices
from .invoices import Invoice, InvoiceGenerator, InvoiceStatus, invoice_generator

# License Validation
from .license import LicenseValidator, ValidationResult, license_validator

# Strategy Marketplace
from .marketplace import (
    MarketplaceStrategy,
    PurchaseStatus,
    StrategyCategory,
    StrategyLicenseType,
    StrategyMarketplace,
    StrategyPurchase,
    StrategyReview,
    StrategyStatus,
    strategy_marketplace,
)

# Payment Processing
from .payment_processor import (
    Payment,
    PaymentProcessor,
    PaymentStatus,
    payment_processor,
)
from .pricing import (
    BillingCycle,
    PricingManager,
    PricingTier,
    SubscriptionTier,
    TierFeatures,
    pricing_manager,
)

# Stripe Integration
from .stripe_integration import (
    StripeCustomer,
    StripeIntegration,
    StripePaymentIntent,
    StripeSubscription,
    StripeWebhookEvent,
    stripe_integration,
)

# Subscription
from .subscription import (
    Subscription,
    SubscriptionManager,
    SubscriptionStatus,
    subscription_manager,
)

__all__ = [
    "AccessCode",
    "AccessCodeGenerator",
    # Access Codes
    "AccessCodeStatus",
    "Affiliate",
    "AffiliateLevel",
    "AffiliateManager",
    # Affiliate Program
    "AffiliateStatus",
    "BillingCycle",
    "Commission",
    # Commission
    "CommissionStatus",
    "CommissionTracker",
    "EnterpriseCustomer",
    "EnterpriseFeatures",
    "EnterpriseManager",
    "Invoice",
    "InvoiceGenerator",
    # Invoices
    "InvoiceStatus",
    "LicenseValidator",
    "MarketplaceStrategy",
    "Partner",
    "PartnerStatus",
    # Enterprise Features
    "PartnerType",
    "Payment",
    "PaymentProcessor",
    # Payment Processing
    "PaymentStatus",
    "Payout",
    "PricingManager",
    "PricingTier",
    "Referral",
    "ReferralStatus",
    "RevenueAnalytics",
    "RevenueEntry",
    # Revenue Analytics
    "RevenueSource",
    # Strategy Marketplace
    "StrategyCategory",
    "StrategyLicenseType",
    "StrategyMarketplace",
    "StrategyPurchase",
    "StrategyReview",
    "StrategyStatus",
    "StripeCustomer",
    # Stripe Integration
    "StripeIntegration",
    "StripePaymentIntent",
    "StripeSubscription",
    "StripeWebhookEvent",
    "Subscription",
    "SubscriptionManager",
    # Subscription
    "SubscriptionStatus",
    # Pricing
    "SubscriptionTier",
    "TierFeatures",
    "TimePeriod",
    # License Validation
    "ValidationResult",
    "WhiteLabelConfig",
    "WhiteLabelInstance",
    "WhiteLabelStatus",
    "access_code_generator",
    "affiliate_manager",
    "commission_tracker",
    "enterprise_manager",
    "invoice_generator",
    "license_validator",
    "payment_processor",
    "pricing_manager",
    "revenue_analytics",
    "strategy_marketplace",
    "stripe_integration",
    "subscription_manager",
]

__version__ = "2.0.0"
