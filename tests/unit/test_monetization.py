"""
Tests for Monetization System

Tests for all monetization modules including:
- Pricing and billing cycles
- Stripe integration
- Affiliate program
- Strategy marketplace
- Revenue analytics
- Enterprise features
"""

import pytest
from decimal import Decimal
from datetime import datetime, timedelta

from monetization.pricing import (
    SubscriptionTier,
    BillingCycle,
    PricingManager,
    TierFeatures,
    PricingTier
)
from monetization.affiliate import (
    AffiliateManager,
    AffiliateLevel,
    AffiliateStatus,
    ReferralStatus,
    AFFILIATE_COMMISSION_RATES
)
from monetization.marketplace import (
    StrategyMarketplace,
    StrategyCategory,
    StrategyLicenseType,
    StrategyStatus,
    PurchaseStatus,
    StrategyPerformance
)
from monetization.analytics import (
    RevenueAnalytics,
    RevenueSource,
    TimePeriod
)
from monetization.enterprise import (
    EnterpriseManager,
    PartnerType,
    PartnerStatus,
    WhiteLabelConfig,
    WhiteLabelStatus
)
from monetization.stripe_integration import (
    StripeIntegration,
    StripeWebhookEvent
)


class TestPricing:
    """Test pricing module"""

    def test_subscription_tiers_exist(self):
        """Test all subscription tiers are defined"""
        assert SubscriptionTier.FREE.value == "free"
        assert SubscriptionTier.STARTER.value == "starter"
        assert SubscriptionTier.PROFESSIONAL.value == "professional"
        assert SubscriptionTier.ENTERPRISE.value == "enterprise"
        assert SubscriptionTier.ELITE.value == "elite"

    def test_billing_cycles(self):
        """Test billing cycle enumeration"""
        assert BillingCycle.MONTHLY.value == "monthly"
        assert BillingCycle.ANNUAL.value == "annual"

    def test_pricing_manager_initialization(self):
        """Test pricing manager has all tiers"""
        pm = PricingManager()
        tiers = pm.get_all_tiers()
        assert len(tiers) == 5

    def test_free_tier_pricing(self):
        """Test free tier configuration"""
        pm = PricingManager()
        free = pm.get_tier(SubscriptionTier.FREE)
        
        assert free is not None
        assert free.monthly_price == Decimal("0.00")
        assert free.commission_rate == Decimal("0.010")  # 1%
        assert free.features.max_strategies == 1
        assert free.features.max_brokers == 1
        assert free.features.ml_features is False

    def test_tier_prices(self):
        """Test all tier prices are correct"""
        pm = PricingManager()
        
        assert pm.get_tier_price(SubscriptionTier.FREE) == Decimal("0.00")
        assert pm.get_tier_price(SubscriptionTier.STARTER) == Decimal("1800.00")
        assert pm.get_tier_price(SubscriptionTier.PROFESSIONAL) == Decimal("4500.00")
        assert pm.get_tier_price(SubscriptionTier.ENTERPRISE) == Decimal("7500.00")
        assert pm.get_tier_price(SubscriptionTier.ELITE) == Decimal("10000.00")

    def test_commission_rates(self):
        """Test commission rates by tier"""
        pm = PricingManager()
        
        assert pm.get_commission_rate(SubscriptionTier.FREE) == Decimal("0.010")  # 1%
        assert pm.get_commission_rate(SubscriptionTier.STARTER) == Decimal("0.005")  # 0.5%
        assert pm.get_commission_rate(SubscriptionTier.PROFESSIONAL) == Decimal("0.003")  # 0.3%
        assert pm.get_commission_rate(SubscriptionTier.ENTERPRISE) == Decimal("0.002")  # 0.2%
        assert pm.get_commission_rate(SubscriptionTier.ELITE) == Decimal("0.001")  # 0.1%

    def test_annual_pricing_discount(self):
        """Test annual pricing has discount (2 months free)"""
        pm = PricingManager()
        pro = pm.get_tier(SubscriptionTier.PROFESSIONAL)
        
        monthly_total = pro.monthly_price * 12
        annual_price = pro.get_annual_price()
        
        # Annual should be less than 12x monthly
        assert annual_price < monthly_total
        # Discount should be approximately 16.67%
        discount = (monthly_total - annual_price) / monthly_total
        assert 0.15 < float(discount) < 0.18

    def test_upgrade_path(self):
        """Test upgrade path from free tier"""
        pm = PricingManager()
        upgrade_options = pm.get_upgrade_path(SubscriptionTier.FREE)
        
        assert SubscriptionTier.STARTER in upgrade_options
        assert SubscriptionTier.PROFESSIONAL in upgrade_options
        assert SubscriptionTier.ENTERPRISE in upgrade_options
        assert SubscriptionTier.ELITE in upgrade_options
        assert SubscriptionTier.FREE not in upgrade_options

    def test_downgrade_path(self):
        """Test downgrade path from elite tier"""
        pm = PricingManager()
        downgrade_options = pm.get_downgrade_path(SubscriptionTier.ELITE)
        
        assert SubscriptionTier.FREE in downgrade_options
        assert SubscriptionTier.STARTER in downgrade_options
        assert SubscriptionTier.ELITE not in downgrade_options

    def test_calculate_commission(self):
        """Test commission calculation"""
        pm = PricingManager()
        trade_amount = Decimal("10000.00")
        
        starter_commission = pm.calculate_commission(SubscriptionTier.STARTER, trade_amount)
        assert starter_commission == Decimal("50.00")  # 0.5%
        
        elite_commission = pm.calculate_commission(SubscriptionTier.ELITE, trade_amount)
        assert elite_commission == Decimal("10.00")  # 0.1%


class TestAffiliateProgram:
    """Test affiliate program module"""

    def test_create_affiliate(self):
        """Test creating an affiliate account"""
        am = AffiliateManager()
        affiliate = am.create_affiliate(
            user_id="user123",
            payment_details={"email": "affiliate@test.com"}
        )
        
        assert affiliate is not None
        assert affiliate.user_id == "user123"
        assert affiliate.level == AffiliateLevel.BRONZE
        assert affiliate.status == AffiliateStatus.PENDING

    def test_affiliate_commission_rates(self):
        """Test affiliate commission rates by level"""
        assert AFFILIATE_COMMISSION_RATES[AffiliateLevel.BRONZE] == Decimal("0.10")
        assert AFFILIATE_COMMISSION_RATES[AffiliateLevel.SILVER] == Decimal("0.15")
        assert AFFILIATE_COMMISSION_RATES[AffiliateLevel.GOLD] == Decimal("0.20")
        assert AFFILIATE_COMMISSION_RATES[AffiliateLevel.PLATINUM] == Decimal("0.25")

    def test_approve_affiliate(self):
        """Test approving an affiliate"""
        am = AffiliateManager()
        affiliate = am.create_affiliate(user_id="user456")
        
        assert affiliate.status == AffiliateStatus.PENDING
        
        am.approve_affiliate(affiliate.affiliate_id)
        assert affiliate.status == AffiliateStatus.ACTIVE

    def test_create_referral(self):
        """Test creating a referral"""
        am = AffiliateManager()
        affiliate = am.create_affiliate(user_id="affiliate1")
        am.approve_affiliate(affiliate.affiliate_id)
        
        referral = am.create_referral(
            affiliate_code=affiliate.code,
            referred_user_id="newuser1"
        )
        
        assert referral is not None
        assert referral.affiliate_id == affiliate.affiliate_id
        assert referral.status == ReferralStatus.PENDING

    def test_convert_referral(self):
        """Test converting a referral"""
        am = AffiliateManager()
        affiliate = am.create_affiliate(user_id="affiliate2")
        am.approve_affiliate(affiliate.affiliate_id)
        
        am.create_referral(affiliate.code, "converteduser1")
        
        commission = am.convert_referral(
            referred_user_id="converteduser1",
            tier=SubscriptionTier.PROFESSIONAL,
            subscription_amount=Decimal("4500.00")
        )
        
        assert commission is not None
        # Bronze level = 10% of $4500
        assert commission == Decimal("450.00")

    def test_affiliate_leaderboard(self):
        """Test affiliate leaderboard"""
        am = AffiliateManager()
        
        # Create and approve affiliates
        for i in range(5):
            aff = am.create_affiliate(f"leader{i}")
            am.approve_affiliate(aff.affiliate_id)
        
        leaderboard = am.get_leaderboard(limit=5)
        assert isinstance(leaderboard, list)


class TestMarketplace:
    """Test strategy marketplace module"""

    def test_list_strategy(self):
        """Test listing a strategy"""
        mp = StrategyMarketplace()
        strategy = mp.list_strategy(
            creator_id="creator1",
            name="Scalping Pro",
            description="High-frequency scalping strategy",
            category=StrategyCategory.SCALPING,
            price=Decimal("499.00"),
            tags=["scalping", "forex"]
        )
        
        assert strategy is not None
        assert strategy.name == "Scalping Pro"
        assert strategy.status == StrategyStatus.DRAFT
        assert strategy.price == Decimal("499.00")

    def test_strategy_categories(self):
        """Test all strategy categories exist"""
        categories = list(StrategyCategory)
        assert StrategyCategory.SCALPING in categories
        assert StrategyCategory.ML_BASED in categories
        assert StrategyCategory.ALGORITHMIC in categories

    def test_strategy_approval_flow(self):
        """Test strategy approval workflow"""
        mp = StrategyMarketplace()
        strategy = mp.list_strategy(
            creator_id="creator2",
            name="Test Strategy",
            description="Test",
            category=StrategyCategory.DAY_TRADING,
            price=Decimal("99.00")
        )
        
        assert strategy.status == StrategyStatus.DRAFT
        
        strategy.submit_for_review()
        assert strategy.status == StrategyStatus.PENDING_REVIEW
        
        mp.approve_strategy(strategy.strategy_id)
        assert strategy.status == StrategyStatus.APPROVED
        assert strategy.is_available()

    def test_purchase_strategy(self):
        """Test purchasing a strategy"""
        mp = StrategyMarketplace()
        
        strategy = mp.list_strategy(
            creator_id="seller1",
            name="Pro Strategy",
            description="Professional trading strategy",
            category=StrategyCategory.SWING_TRADING,
            price=Decimal("199.00")
        )
        mp.approve_strategy(strategy.strategy_id)
        
        purchase = mp.purchase_strategy(
            buyer_id="buyer1",
            strategy_id=strategy.strategy_id
        )
        
        assert purchase is not None
        assert purchase.amount == Decimal("199.00")
        
        # Complete purchase
        mp.complete_purchase(purchase.purchase_id)
        assert mp.has_strategy_license("buyer1", strategy.strategy_id)

    def test_strategy_review(self):
        """Test adding a strategy review"""
        mp = StrategyMarketplace()
        
        strategy = mp.list_strategy(
            creator_id="seller2",
            name="Review Test",
            description="Test",
            category=StrategyCategory.ALGORITHMIC,
            price=Decimal("50.00")
        )
        mp.approve_strategy(strategy.strategy_id)
        
        review = mp.add_review(
            user_id="reviewer1",
            strategy_id=strategy.strategy_id,
            rating=5,
            title="Great strategy!",
            content="Works perfectly for my needs."
        )
        
        assert review is not None
        assert review.rating == 5
        assert strategy.avg_rating == 5.0

    def test_search_strategies(self):
        """Test searching strategies"""
        mp = StrategyMarketplace()
        
        # Create and approve strategies
        for i in range(3):
            s = mp.list_strategy(
                creator_id=f"creator{i}",
                name=f"Strategy {i}",
                description="Test strategy",
                category=StrategyCategory.SCALPING,
                price=Decimal(str(100 + i * 50))
            )
            mp.approve_strategy(s.strategy_id)
        
        results = mp.search_strategies(
            category=StrategyCategory.SCALPING,
            limit=10
        )
        
        assert len(results) == 3


class TestRevenueAnalytics:
    """Test revenue analytics module"""

    def test_record_revenue(self):
        """Test recording revenue"""
        ra = RevenueAnalytics()
        
        entry = ra.record_revenue(
            source=RevenueSource.SUBSCRIPTION,
            amount=Decimal("4500.00"),
            user_id="user1",
            tier=SubscriptionTier.PROFESSIONAL,
            description="Monthly subscription"
        )
        
        assert entry is not None
        assert entry.amount == Decimal("4500.00")
        assert entry.source == RevenueSource.SUBSCRIPTION

    def test_revenue_by_source(self):
        """Test getting revenue by source"""
        ra = RevenueAnalytics()
        
        ra.record_revenue(RevenueSource.SUBSCRIPTION, Decimal("1000.00"))
        ra.record_revenue(RevenueSource.COMMISSION, Decimal("500.00"))
        ra.record_revenue(RevenueSource.MARKETPLACE, Decimal("200.00"))
        
        breakdown = ra.get_revenue_by_source()
        
        assert breakdown[RevenueSource.SUBSCRIPTION.value] == Decimal("1000.00")
        assert breakdown[RevenueSource.COMMISSION.value] == Decimal("500.00")
        assert breakdown[RevenueSource.MARKETPLACE.value] == Decimal("200.00")

    def test_subscription_events(self):
        """Test recording subscription events"""
        ra = RevenueAnalytics()
        
        ra.record_subscription_event(
            event_type="new",
            user_id="user1",
            tier=SubscriptionTier.STARTER,
            billing_cycle=BillingCycle.MONTHLY,
            amount=Decimal("1800.00")
        )
        
        metrics = ra.get_subscription_metrics()
        assert metrics.new_subscriptions >= 1

    def test_growth_metrics(self):
        """Test growth metrics calculation"""
        ra = RevenueAnalytics()
        
        # Record some revenue
        ra.record_revenue(RevenueSource.SUBSCRIPTION, Decimal("10000.00"))
        
        metrics = ra.get_growth_metrics()
        
        assert metrics.mrr >= Decimal("0")
        assert metrics.arr == metrics.mrr * 12

    def test_generate_report(self):
        """Test report generation"""
        ra = RevenueAnalytics()
        
        report = ra.generate_report(
            period=TimePeriod.MONTHLY,
            include_projections=True
        )
        
        assert 'summary' in report
        assert 'subscriptions' in report
        assert 'revenue' in report
        assert 'projections' in report


class TestEnterpriseFeatures:
    """Test enterprise features module"""

    def test_register_partner(self):
        """Test registering a partner"""
        em = EnterpriseManager()
        
        partner = em.register_partner(
            company_name="Test Corp",
            contact_email="partner@test.com",
            partner_type=PartnerType.RESELLER,
            contact_name="John Doe"
        )
        
        assert partner is not None
        assert partner.company_name == "Test Corp"
        assert partner.status == PartnerStatus.PENDING

    def test_approve_partner(self):
        """Test approving a partner"""
        em = EnterpriseManager()
        
        partner = em.register_partner(
            company_name="Approved Corp",
            contact_email="approved@test.com",
            partner_type=PartnerType.WHITE_LABEL
        )
        
        em.approve_partner(partner.partner_id)
        
        assert partner.status == PartnerStatus.ACTIVE
        assert partner.api_key is not None

    def test_create_white_label_instance(self):
        """Test creating white-label instance"""
        em = EnterpriseManager()
        
        partner = em.register_partner(
            company_name="WL Corp",
            contact_email="wl@test.com",
            partner_type=PartnerType.WHITE_LABEL
        )
        em.approve_partner(partner.partner_id)
        
        config = WhiteLabelConfig(
            company_name="WL Corp Trading",
            logo_url="https://wlcorp.com/logo.png",
            primary_color="#00FF00",
            secondary_color="#0000FF"
        )
        
        instance = em.create_white_label_instance(
            partner_id=partner.partner_id,
            name="WL Corp Platform",
            config=config
        )
        
        assert instance is not None
        assert instance.subdomain is not None
        assert instance.api_endpoint is not None

    def test_deploy_white_label(self):
        """Test deploying white-label instance"""
        em = EnterpriseManager()
        
        partner = em.register_partner(
            company_name="Deploy Corp",
            contact_email="deploy@test.com",
            partner_type=PartnerType.WHITE_LABEL
        )
        em.approve_partner(partner.partner_id)
        
        config = WhiteLabelConfig(
            company_name="Deploy Corp",
            logo_url="https://deploy.com/logo.png",
            primary_color="#FF0000",
            secondary_color="#00FF00"
        )
        
        instance = em.create_white_label_instance(
            partner_id=partner.partner_id,
            name="Deploy Platform",
            config=config
        )
        
        em.deploy_white_label_instance(instance.instance_id)
        
        assert instance.status == WhiteLabelStatus.DEPLOYED
        assert instance.is_active()

    def test_register_enterprise_customer(self):
        """Test registering enterprise customer"""
        em = EnterpriseManager()
        
        customer = em.register_enterprise_customer(
            company_name="Big Corp",
            contact_email="enterprise@bigcorp.com",
            tier=SubscriptionTier.ENTERPRISE,
            contract_value=Decimal("90000.00"),
            contract_months=12
        )
        
        assert customer is not None
        assert customer.tier == SubscriptionTier.ENTERPRISE
        assert customer.contract_value == Decimal("90000.00")

    def test_enterprise_stats(self):
        """Test enterprise statistics"""
        em = EnterpriseManager()
        
        stats = em.get_enterprise_stats()
        
        assert 'partners' in stats
        assert 'white_label' in stats
        assert 'enterprise_customers' in stats


class TestStripeIntegration:
    """Test Stripe integration module"""

    def test_create_customer(self):
        """Test creating Stripe customer"""
        stripe = StripeIntegration(test_mode=True)
        
        customer = stripe.create_customer(
            user_id="user123",
            email="customer@test.com",
            name="Test Customer"
        )
        
        assert customer is not None
        assert customer.email == "customer@test.com"
        assert customer.customer_id.startswith("cus_")

    def test_create_payment_intent(self):
        """Test creating payment intent"""
        stripe = StripeIntegration(test_mode=True)
        
        customer = stripe.create_customer("user456", "payer@test.com")
        
        intent = stripe.create_payment_intent(
            customer_id=customer.customer_id,
            amount=Decimal("1800.00"),
            tier=SubscriptionTier.STARTER
        )
        
        assert intent is not None
        assert intent.amount == 180000  # cents
        assert intent.client_secret is not None

    def test_create_checkout_session(self):
        """Test creating checkout session"""
        stripe = StripeIntegration(test_mode=True)
        
        customer = stripe.create_customer("user789", "checkout@test.com")
        
        session = stripe.create_checkout_session(
            customer_id=customer.customer_id,
            tier=SubscriptionTier.PROFESSIONAL,
            billing_cycle=BillingCycle.MONTHLY
        )
        
        assert session is not None
        assert 'url' in session
        assert session['tier'] == 'professional'

    def test_create_subscription(self):
        """Test creating subscription"""
        stripe = StripeIntegration(test_mode=True)
        
        customer = stripe.create_customer("subuser", "sub@test.com")
        
        subscription = stripe.create_subscription(
            customer_id=customer.customer_id,
            tier=SubscriptionTier.ENTERPRISE,
            billing_cycle=BillingCycle.ANNUAL
        )
        
        assert subscription is not None
        assert subscription.tier == SubscriptionTier.ENTERPRISE
        assert subscription.status == "active"

    def test_cancel_subscription(self):
        """Test canceling subscription"""
        stripe = StripeIntegration(test_mode=True)
        
        customer = stripe.create_customer("canceluser", "cancel@test.com")
        subscription = stripe.create_subscription(
            customer_id=customer.customer_id,
            tier=SubscriptionTier.STARTER
        )
        
        result = stripe.cancel_subscription(
            subscription.subscription_id,
            at_period_end=True
        )
        
        assert result is True
        assert subscription.cancel_at_period_end is True

    def test_handle_webhook(self):
        """Test webhook handling"""
        stripe = StripeIntegration(test_mode=True)
        
        result = stripe.handle_webhook(
            event_type=StripeWebhookEvent.PAYMENT_INTENT_SUCCEEDED.value,
            event_data={'id': 'pi_test123'}
        )
        
        assert result['status'] == 'success'

    def test_refund_payment(self):
        """Test refunding payment"""
        stripe = StripeIntegration(test_mode=True)
        
        customer = stripe.create_customer("refunduser", "refund@test.com")
        intent = stripe.create_payment_intent(
            customer_id=customer.customer_id,
            amount=Decimal("500.00")
        )
        
        refund = stripe.refund_payment(intent.intent_id)
        
        assert refund is not None
        assert refund['status'] == 'succeeded'
