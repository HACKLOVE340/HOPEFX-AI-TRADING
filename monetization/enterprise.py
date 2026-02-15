"""
Enterprise and White-Label Features

This module provides:
- Enterprise-specific features and configurations
- White-label customization options
- Partner program management
- Custom branding settings
- Multi-tenant configurations
"""

import logging
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Optional, Dict, List, Any
from enum import Enum
from dataclasses import dataclass

from .pricing import SubscriptionTier

logger = logging.getLogger(__name__)


class PartnerType(str, Enum):
    """Partner program types"""
    RESELLER = "reseller"
    WHITE_LABEL = "white_label"
    INTEGRATION = "integration"
    REFERRAL = "referral"
    TECHNOLOGY = "technology"


class PartnerStatus(str, Enum):
    """Partner status"""
    PENDING = "pending"
    ACTIVE = "active"
    SUSPENDED = "suspended"
    TERMINATED = "terminated"


class WhiteLabelStatus(str, Enum):
    """White-label deployment status"""
    PENDING = "pending"
    CONFIGURING = "configuring"
    DEPLOYED = "deployed"
    MAINTENANCE = "maintenance"
    SUSPENDED = "suspended"


# Partner commission rates
PARTNER_COMMISSION_RATES = {
    PartnerType.RESELLER: Decimal("0.20"),      # 20%
    PartnerType.WHITE_LABEL: Decimal("0.30"),   # 30%
    PartnerType.INTEGRATION: Decimal("0.10"),   # 10%
    PartnerType.REFERRAL: Decimal("0.15"),      # 15%
    PartnerType.TECHNOLOGY: Decimal("0.25"),    # 25%
}


@dataclass
class WhiteLabelConfig:
    """White-label branding configuration"""
    company_name: str
    logo_url: str
    primary_color: str
    secondary_color: str
    favicon_url: Optional[str] = None
    support_email: Optional[str] = None
    support_url: Optional[str] = None
    terms_url: Optional[str] = None
    privacy_url: Optional[str] = None
    custom_domain: Optional[str] = None
    custom_css: Optional[str] = None
    email_from_name: Optional[str] = None
    email_from_address: Optional[str] = None
    footer_text: Optional[str] = None
    show_powered_by: bool = True


@dataclass
class EnterpriseFeatures:
    """Enterprise-specific feature configuration"""
    sso_enabled: bool = False
    sso_provider: Optional[str] = None
    sso_config: Optional[Dict[str, Any]] = None
    api_rate_limit_override: Optional[int] = None
    custom_webhooks: bool = True
    dedicated_support: bool = True
    sla_tier: str = "standard"
    data_retention_days: int = 365
    audit_logging: bool = True
    ip_whitelist: Optional[List[str]] = None
    mfa_required: bool = False
    custom_reports: bool = True
    api_key_limit: int = 10
    max_users: int = 100
    custom_integrations: bool = True


class Partner:
    """Partner account model"""

    def __init__(
        self,
        partner_id: str,
        company_name: str,
        contact_email: str,
        partner_type: PartnerType,
        status: PartnerStatus = PartnerStatus.PENDING,
        contact_name: Optional[str] = None,
        contact_phone: Optional[str] = None
    ):
        self.partner_id = partner_id
        self.company_name = company_name
        self.contact_email = contact_email
        self.contact_name = contact_name
        self.contact_phone = contact_phone
        self.partner_type = partner_type
        self.status = status
        self.created_at = datetime.utcnow()
        self.approved_at: Optional[datetime] = None
        
        # Commission settings
        self.commission_rate = PARTNER_COMMISSION_RATES.get(
            partner_type, Decimal("0.10")
        )
        self.custom_commission_rate: Optional[Decimal] = None
        
        # Revenue tracking
        self.total_revenue = Decimal("0.00")
        self.total_commissions = Decimal("0.00")
        self.pending_payout = Decimal("0.00")
        
        # Referrals/clients
        self.client_count = 0
        self.api_key: Optional[str] = None
        
        # Contract details
        self.contract_start: Optional[datetime] = None
        self.contract_end: Optional[datetime] = None
        self.notes: str = ""

    def get_commission_rate(self) -> Decimal:
        """Get effective commission rate"""
        return self.custom_commission_rate or self.commission_rate

    def is_active(self) -> bool:
        """Check if partner is active"""
        return self.status == PartnerStatus.ACTIVE

    def approve(self) -> None:
        """Approve partner application"""
        self.status = PartnerStatus.ACTIVE
        self.approved_at = datetime.utcnow()
        self.contract_start = datetime.utcnow()
        logger.info(f"Partner {self.partner_id} approved")

    def suspend(self) -> None:
        """Suspend partner"""
        self.status = PartnerStatus.SUSPENDED
        logger.info(f"Partner {self.partner_id} suspended")

    def terminate(self) -> None:
        """Terminate partnership"""
        self.status = PartnerStatus.TERMINATED
        self.contract_end = datetime.utcnow()
        logger.info(f"Partner {self.partner_id} terminated")

    def record_sale(self, amount: Decimal) -> Decimal:
        """Record a sale and calculate commission"""
        commission = amount * self.get_commission_rate()
        self.total_revenue += amount
        self.total_commissions += commission
        self.pending_payout += commission
        self.client_count += 1
        return commission

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary"""
        return {
            'partner_id': self.partner_id,
            'company_name': self.company_name,
            'contact_email': self.contact_email,
            'contact_name': self.contact_name,
            'partner_type': self.partner_type.value,
            'status': self.status.value,
            'commission_rate': float(self.get_commission_rate()),
            'total_revenue': float(self.total_revenue),
            'total_commissions': float(self.total_commissions),
            'pending_payout': float(self.pending_payout),
            'client_count': self.client_count,
            'created_at': self.created_at.isoformat(),
            'approved_at': self.approved_at.isoformat() if self.approved_at else None,
            'contract_start': self.contract_start.isoformat() if self.contract_start else None,
            'contract_end': self.contract_end.isoformat() if self.contract_end else None
        }


class WhiteLabelInstance:
    """White-label deployment instance"""

    def __init__(
        self,
        instance_id: str,
        partner_id: str,
        name: str,
        config: WhiteLabelConfig,
        status: WhiteLabelStatus = WhiteLabelStatus.PENDING
    ):
        self.instance_id = instance_id
        self.partner_id = partner_id
        self.name = name
        self.config = config
        self.status = status
        self.created_at = datetime.utcnow()
        self.deployed_at: Optional[datetime] = None
        
        # Enterprise features
        self.enterprise_features = EnterpriseFeatures()
        
        # Usage stats
        self.total_users = 0
        self.active_users = 0
        self.total_revenue = Decimal("0.00")
        
        # Technical details
        self.subdomain: Optional[str] = None
        self.api_endpoint: Optional[str] = None
        self.environment: str = "production"

    def deploy(self) -> None:
        """Mark instance as deployed"""
        self.status = WhiteLabelStatus.DEPLOYED
        self.deployed_at = datetime.utcnow()
        logger.info(f"White-label instance {self.instance_id} deployed")

    def enter_maintenance(self) -> None:
        """Enter maintenance mode"""
        self.status = WhiteLabelStatus.MAINTENANCE
        logger.info(f"White-label instance {self.instance_id} in maintenance")

    def suspend(self) -> None:
        """Suspend instance"""
        self.status = WhiteLabelStatus.SUSPENDED
        logger.info(f"White-label instance {self.instance_id} suspended")

    def update_config(self, new_config: WhiteLabelConfig) -> None:
        """Update branding configuration"""
        self.config = new_config
        logger.info(f"White-label instance {self.instance_id} config updated")

    def update_enterprise_features(self, features: EnterpriseFeatures) -> None:
        """Update enterprise features"""
        self.enterprise_features = features
        logger.info(f"White-label instance {self.instance_id} features updated")

    def is_active(self) -> bool:
        """Check if instance is active"""
        return self.status == WhiteLabelStatus.DEPLOYED

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary"""
        return {
            'instance_id': self.instance_id,
            'partner_id': self.partner_id,
            'name': self.name,
            'status': self.status.value,
            'config': {
                'company_name': self.config.company_name,
                'logo_url': self.config.logo_url,
                'primary_color': self.config.primary_color,
                'secondary_color': self.config.secondary_color,
                'custom_domain': self.config.custom_domain,
                'support_email': self.config.support_email
            },
            'enterprise_features': {
                'sso_enabled': self.enterprise_features.sso_enabled,
                'dedicated_support': self.enterprise_features.dedicated_support,
                'sla_tier': self.enterprise_features.sla_tier,
                'audit_logging': self.enterprise_features.audit_logging,
                'max_users': self.enterprise_features.max_users
            },
            'total_users': self.total_users,
            'active_users': self.active_users,
            'total_revenue': float(self.total_revenue),
            'subdomain': self.subdomain,
            'api_endpoint': self.api_endpoint,
            'created_at': self.created_at.isoformat(),
            'deployed_at': self.deployed_at.isoformat() if self.deployed_at else None
        }


class EnterpriseCustomer:
    """Enterprise customer model"""

    def __init__(
        self,
        customer_id: str,
        company_name: str,
        contact_email: str,
        tier: SubscriptionTier = SubscriptionTier.ENTERPRISE,
        contact_name: Optional[str] = None
    ):
        self.customer_id = customer_id
        self.company_name = company_name
        self.contact_email = contact_email
        self.contact_name = contact_name
        self.tier = tier
        self.created_at = datetime.utcnow()
        
        # Enterprise features configuration
        self.features = EnterpriseFeatures()
        
        # Contract details
        self.contract_value = Decimal("0.00")
        self.contract_start: Optional[datetime] = None
        self.contract_end: Optional[datetime] = None
        self.billing_cycle: str = "annual"
        self.auto_renew = True
        
        # Usage
        self.user_count = 0
        self.api_calls = 0
        self.data_storage_gb = 0

    def configure_sso(
        self,
        provider: str,
        config: Dict[str, Any]
    ) -> None:
        """Configure SSO for enterprise customer"""
        self.features.sso_enabled = True
        self.features.sso_provider = provider
        self.features.sso_config = config
        logger.info(f"SSO configured for {self.customer_id}: {provider}")

    def set_api_rate_limit(self, limit: int) -> None:
        """Set custom API rate limit"""
        self.features.api_rate_limit_override = limit
        logger.info(f"API rate limit set for {self.customer_id}: {limit}")

    def set_ip_whitelist(self, ips: List[str]) -> None:
        """Set IP whitelist"""
        self.features.ip_whitelist = ips
        logger.info(f"IP whitelist set for {self.customer_id}")

    def enable_mfa(self) -> None:
        """Enable mandatory MFA"""
        self.features.mfa_required = True
        logger.info(f"MFA enabled for {self.customer_id}")

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary"""
        return {
            'customer_id': self.customer_id,
            'company_name': self.company_name,
            'contact_email': self.contact_email,
            'contact_name': self.contact_name,
            'tier': self.tier.value,
            'features': {
                'sso_enabled': self.features.sso_enabled,
                'sso_provider': self.features.sso_provider,
                'dedicated_support': self.features.dedicated_support,
                'sla_tier': self.features.sla_tier,
                'audit_logging': self.features.audit_logging,
                'mfa_required': self.features.mfa_required,
                'max_users': self.features.max_users,
                'api_rate_limit': self.features.api_rate_limit_override
            },
            'contract': {
                'value': float(self.contract_value),
                'start': self.contract_start.isoformat() if self.contract_start else None,
                'end': self.contract_end.isoformat() if self.contract_end else None,
                'billing_cycle': self.billing_cycle,
                'auto_renew': self.auto_renew
            },
            'usage': {
                'users': self.user_count,
                'api_calls': self.api_calls,
                'storage_gb': self.data_storage_gb
            },
            'created_at': self.created_at.isoformat()
        }


class EnterpriseManager:
    """Manage enterprise customers, partners, and white-label instances"""

    def __init__(self):
        self._partners: Dict[str, Partner] = {}
        self._white_label_instances: Dict[str, WhiteLabelInstance] = {}
        self._enterprise_customers: Dict[str, EnterpriseCustomer] = {}

    def register_partner(
        self,
        company_name: str,
        contact_email: str,
        partner_type: PartnerType,
        contact_name: Optional[str] = None,
        contact_phone: Optional[str] = None,
        custom_commission_rate: Optional[Decimal] = None
    ) -> Partner:
        """Register a new partner"""
        import uuid

        partner_id = f"PTR-{uuid.uuid4().hex[:12].upper()}"
        
        partner = Partner(
            partner_id=partner_id,
            company_name=company_name,
            contact_email=contact_email,
            partner_type=partner_type,
            contact_name=contact_name,
            contact_phone=contact_phone
        )
        
        if custom_commission_rate:
            partner.custom_commission_rate = custom_commission_rate

        self._partners[partner_id] = partner
        logger.info(f"Registered partner {partner_id}: {company_name}")
        return partner

    def get_partner(self, partner_id: str) -> Optional[Partner]:
        """Get partner by ID"""
        return self._partners.get(partner_id)

    def approve_partner(self, partner_id: str) -> bool:
        """Approve partner application"""
        partner = self.get_partner(partner_id)
        if not partner:
            return False
        partner.approve()
        
        # Generate API key for partner
        import secrets
        partner.api_key = f"pk_{secrets.token_hex(24)}"
        
        return True

    def create_white_label_instance(
        self,
        partner_id: str,
        name: str,
        config: WhiteLabelConfig
    ) -> Optional[WhiteLabelInstance]:
        """Create white-label instance for partner"""
        import uuid

        partner = self.get_partner(partner_id)
        if not partner or not partner.is_active():
            logger.warning(f"Invalid or inactive partner: {partner_id}")
            return None

        if partner.partner_type != PartnerType.WHITE_LABEL:
            logger.warning(f"Partner {partner_id} is not white-label type")
            return None

        instance_id = f"WL-{uuid.uuid4().hex[:12].upper()}"
        
        instance = WhiteLabelInstance(
            instance_id=instance_id,
            partner_id=partner_id,
            name=name,
            config=config
        )
        
        # Generate subdomain
        subdomain_base = name.lower().replace(' ', '-')
        instance.subdomain = f"{subdomain_base}.hopefx.ai"
        instance.api_endpoint = f"https://api.{subdomain_base}.hopefx.ai"

        self._white_label_instances[instance_id] = instance
        logger.info(f"Created white-label instance {instance_id} for partner {partner_id}")
        
        return instance

    def get_white_label_instance(
        self,
        instance_id: str
    ) -> Optional[WhiteLabelInstance]:
        """Get white-label instance by ID"""
        return self._white_label_instances.get(instance_id)

    def deploy_white_label_instance(self, instance_id: str) -> bool:
        """Deploy white-label instance"""
        instance = self.get_white_label_instance(instance_id)
        if not instance:
            return False
        instance.deploy()
        return True

    def register_enterprise_customer(
        self,
        company_name: str,
        contact_email: str,
        tier: SubscriptionTier = SubscriptionTier.ENTERPRISE,
        contact_name: Optional[str] = None,
        contract_value: Optional[Decimal] = None,
        contract_months: int = 12
    ) -> EnterpriseCustomer:
        """Register enterprise customer"""
        import uuid

        customer_id = f"ENT-{uuid.uuid4().hex[:12].upper()}"
        
        customer = EnterpriseCustomer(
            customer_id=customer_id,
            company_name=company_name,
            contact_email=contact_email,
            tier=tier,
            contact_name=contact_name
        )
        
        if contract_value:
            customer.contract_value = contract_value
            customer.contract_start = datetime.utcnow()
            customer.contract_end = datetime.utcnow() + timedelta(days=30 * contract_months)

        self._enterprise_customers[customer_id] = customer
        logger.info(f"Registered enterprise customer {customer_id}: {company_name}")
        
        return customer

    def get_enterprise_customer(
        self,
        customer_id: str
    ) -> Optional[EnterpriseCustomer]:
        """Get enterprise customer by ID"""
        return self._enterprise_customers.get(customer_id)

    def configure_enterprise_sso(
        self,
        customer_id: str,
        provider: str,
        config: Dict[str, Any]
    ) -> bool:
        """Configure SSO for enterprise customer"""
        customer = self.get_enterprise_customer(customer_id)
        if not customer:
            return False
        customer.configure_sso(provider, config)
        return True

    def get_partner_clients(
        self,
        partner_id: str
    ) -> List[WhiteLabelInstance]:
        """Get all white-label instances for a partner"""
        return [
            inst for inst in self._white_label_instances.values()
            if inst.partner_id == partner_id
        ]

    def get_all_partners(
        self,
        partner_type: Optional[PartnerType] = None,
        status: Optional[PartnerStatus] = None
    ) -> List[Partner]:
        """Get all partners with optional filters"""
        partners = list(self._partners.values())
        
        if partner_type:
            partners = [p for p in partners if p.partner_type == partner_type]
        if status:
            partners = [p for p in partners if p.status == status]
            
        return partners

    def get_all_white_label_instances(
        self,
        status: Optional[WhiteLabelStatus] = None
    ) -> List[WhiteLabelInstance]:
        """Get all white-label instances"""
        instances = list(self._white_label_instances.values())
        
        if status:
            instances = [i for i in instances if i.status == status]
            
        return instances

    def get_all_enterprise_customers(
        self,
        tier: Optional[SubscriptionTier] = None
    ) -> List[EnterpriseCustomer]:
        """Get all enterprise customers"""
        customers = list(self._enterprise_customers.values())
        
        if tier:
            customers = [c for c in customers if c.tier == tier]
            
        return customers

    def process_partner_payout(
        self,
        partner_id: str,
        amount: Optional[Decimal] = None
    ) -> Optional[Dict[str, Any]]:
        """Process payout for partner"""
        import uuid

        partner = self.get_partner(partner_id)
        if not partner or not partner.is_active():
            return None

        payout_amount = amount or partner.pending_payout
        
        if payout_amount <= 0:
            return None

        # Record payout
        payout_id = f"PAY-{uuid.uuid4().hex[:12].upper()}"
        partner.pending_payout -= payout_amount

        return {
            'payout_id': payout_id,
            'partner_id': partner_id,
            'amount': float(payout_amount),
            'status': 'processed',
            'timestamp': datetime.utcnow().isoformat()
        }

    def get_enterprise_stats(self) -> Dict[str, Any]:
        """Get enterprise program statistics"""
        partners = list(self._partners.values())
        instances = list(self._white_label_instances.values())
        customers = list(self._enterprise_customers.values())

        total_partner_revenue = sum(p.total_revenue for p in partners)
        total_partner_commissions = sum(p.total_commissions for p in partners)
        total_enterprise_contract_value = sum(c.contract_value for c in customers)

        return {
            'partners': {
                'total': len(partners),
                'active': len([p for p in partners if p.is_active()]),
                'pending': len([p for p in partners if p.status == PartnerStatus.PENDING]),
                'by_type': {
                    pt.value: len([p for p in partners if p.partner_type == pt])
                    for pt in PartnerType
                },
                'total_revenue': float(total_partner_revenue),
                'total_commissions': float(total_partner_commissions)
            },
            'white_label': {
                'total_instances': len(instances),
                'deployed': len([i for i in instances if i.is_active()]),
                'pending': len([i for i in instances if i.status == WhiteLabelStatus.PENDING]),
                'total_users': sum(i.total_users for i in instances),
                'total_revenue': float(sum(i.total_revenue for i in instances))
            },
            'enterprise_customers': {
                'total': len(customers),
                'by_tier': {
                    tier.value: len([c for c in customers if c.tier == tier])
                    for tier in [SubscriptionTier.ENTERPRISE, SubscriptionTier.ELITE]
                },
                'total_contract_value': float(total_enterprise_contract_value),
                'total_users': sum(c.user_count for c in customers)
            }
        }


# Global enterprise manager instance
enterprise_manager = EnterpriseManager()
