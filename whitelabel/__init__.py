"""
White-Label Module for HOPEFX AI Trading Platform

Provides brand customisation, tenant configuration, and white-label
management for resellers and partners deploying the platform under
their own brand.

Key components:
    - BrandTheme: visual identity with CSS variable generation
    - FeatureFlag: enumeration of available platform features
    - TenantStatus / ResellerTier: lifecycle and tier enumerations
    - Tenant: a white-label deployment instance
    - Reseller: a reseller partner with commission tracking
    - WhiteLabelManager: full CRUD and lifecycle manager
"""

import logging
import uuid
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any, Dict, List, Optional

_logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _generate_id(prefix: str) -> str:
    """Generate a unique prefixed ID."""
    return f"{prefix}-{uuid.uuid4().hex[:12].upper()}"


def _generate_referral_code() -> str:
    """Generate a short referral code."""
    return uuid.uuid4().hex[:8].upper()


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------


class TenantStatus(str, Enum):
    """Lifecycle status for a white-label tenant."""

    PENDING = "pending"
    ACTIVE = "active"
    TRIAL = "trial"
    SUSPENDED = "suspended"
    TERMINATED = "terminated"


class FeatureFlag(str, Enum):
    """Platform feature flags that can be enabled per tenant."""

    TRADING = "trading"
    BACKTESTING = "backtesting"
    SOCIAL_TRADING = "social_trading"
    ANALYTICS = "analytics"
    NEWS = "news"
    ALERTS = "alerts"
    API_ACCESS = "api_access"
    CUSTOM_BRANDING = "custom_branding"
    WHITE_LABEL = "white_label"
    RISK_MANAGEMENT = "risk_management"
    PORTFOLIO = "portfolio"
    REPORTING = "reporting"
    MOBILE = "mobile"


class ResellerTier(str, Enum):
    """Reseller partnership tier."""

    STANDARD = "standard"
    SILVER = "silver"
    GOLD = "gold"
    PLATINUM = "platinum"


# ---------------------------------------------------------------------------
# Tier constants
# ---------------------------------------------------------------------------

TIER_COMMISSION_RATES: Dict[ResellerTier, float] = {
    ResellerTier.STANDARD: 0.15,
    ResellerTier.SILVER: 0.20,
    ResellerTier.GOLD: 0.25,
    ResellerTier.PLATINUM: 0.30,
}

TIER_TENANT_THRESHOLDS: Dict[ResellerTier, int] = {
    ResellerTier.STANDARD: 0,
    ResellerTier.SILVER: 5,
    ResellerTier.GOLD: 15,
    ResellerTier.PLATINUM: 30,
}

# Ordered from highest to lowest for upgrade logic
_TIER_ORDER: List[ResellerTier] = [
    ResellerTier.PLATINUM,
    ResellerTier.GOLD,
    ResellerTier.SILVER,
    ResellerTier.STANDARD,
]


# ---------------------------------------------------------------------------
# Brand theme
# ---------------------------------------------------------------------------


class BrandTheme:
    """
    Visual identity settings for a white-label tenant.

    Attributes:
        primary_color: Main brand colour (CSS hex value).
        app_name: Branded application name.
        font_family: CSS font-family string.
        custom_css: Additional raw CSS injected into the platform.
        tagline: Short marketing tagline.
    """

    def __init__(
        self,
        primary_color: str = "#1976D2",
        app_name: str = "Trading Platform",
        font_family: str = "Inter, sans-serif",
        custom_css: str = "",
        tagline: str = "",
    ) -> None:
        self.primary_color = primary_color
        self.app_name = app_name
        self.font_family = font_family
        self.custom_css = custom_css
        self.tagline = tagline

    def to_dict(self) -> Dict[str, Any]:
        """Serialise the theme to a plain dictionary."""
        return {
            "primary_color": self.primary_color,
            "app_name": self.app_name,
            "font_family": self.font_family,
            "custom_css": self.custom_css,
            "tagline": self.tagline,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "BrandTheme":
        """Deserialise a BrandTheme from a plain dictionary."""
        return cls(
            primary_color=data.get("primary_color", "#1976D2"),
            app_name=data.get("app_name", "Trading Platform"),
            font_family=data.get("font_family", "Inter, sans-serif"),
            custom_css=data.get("custom_css", ""),
            tagline=data.get("tagline", ""),
        )

    def to_css_variables(self) -> str:
        """Generate a CSS string containing custom properties for this theme."""
        css = (
            ":root {\n"
            f"    --color-primary: {self.primary_color};\n"
            f"    --font-family: {self.font_family};\n"
            "}\n"
        )
        if self.custom_css:
            css += self.custom_css
        return css


# ---------------------------------------------------------------------------
# Tenant
# ---------------------------------------------------------------------------


class Tenant:
    """A white-label tenant deployment."""

    def __init__(
        self,
        tenant_id: str,
        name: str,
        owner_email: str,
        status: TenantStatus = TenantStatus.ACTIVE,
        expires_at: Optional[datetime] = None,
        features: Optional[List[FeatureFlag]] = None,
        max_users: int = 50,
        user_count: int = 0,
        reseller_id: Optional[str] = None,
        custom_domain: str = "",
        theme: Optional[BrandTheme] = None,
    ) -> None:
        self.tenant_id = tenant_id
        self.name = name
        self.owner_email = owner_email
        self.status = status
        self.expires_at = expires_at
        self.features: List[FeatureFlag] = features if features is not None else []
        self.max_users = max_users
        self.user_count = user_count
        self.reseller_id = reseller_id
        self.custom_domain = custom_domain
        self.theme: BrandTheme = theme if theme is not None else BrandTheme()
        self.created_at: datetime = datetime.now(timezone.utc)

    def is_active(self) -> bool:
        """Return True if the tenant is currently active or in trial (and not expired)."""
        if self.expires_at is not None and self.expires_at <= datetime.now(timezone.utc):
            return False
        return self.status in (TenantStatus.ACTIVE, TenantStatus.TRIAL)

    def has_feature(self, flag: FeatureFlag) -> bool:
        """Return True if the given feature flag is enabled for this tenant."""
        return flag in self.features

    def can_add_user(self) -> bool:
        """Return True if the tenant has not reached its maximum user count."""
        return self.user_count < self.max_users


# ---------------------------------------------------------------------------
# Reseller
# ---------------------------------------------------------------------------


class Reseller:
    """A reseller partner with commission tracking."""

    def __init__(
        self,
        reseller_id: str,
        company_name: str,
        contact_email: str,
        tier: ResellerTier = ResellerTier.STANDARD,
        commission_rate: Optional[float] = None,
        is_active: bool = True,
        referral_code: Optional[str] = None,
        total_revenue: float = 0.0,
        total_tenants: int = 0,
    ) -> None:
        self.reseller_id = reseller_id
        self.company_name = company_name
        self.contact_email = contact_email
        self.tier = tier
        self.commission_rate = (
            commission_rate
            if commission_rate is not None
            else TIER_COMMISSION_RATES[tier]
        )
        self.is_active = is_active
        self.referral_code = (
            referral_code if referral_code is not None else _generate_referral_code()
        )
        self.total_revenue = total_revenue
        self.total_tenants = total_tenants


# ---------------------------------------------------------------------------
# White-label manager
# ---------------------------------------------------------------------------


class WhiteLabelManager:
    """
    Central manager for white-label tenants and resellers.

    Responsibilities:
    - Create and provision new tenants and resellers
    - Look up tenants by ID or domain
    - Lifecycle management (activate, suspend, delete)
    - Feature flag management
    - Commission calculation and tier upgrades
    - Tenant config export/import
    - Platform summary reporting
    """

    def __init__(self) -> None:
        self._tenants: Dict[str, Tenant] = {}
        self._resellers: Dict[str, Reseller] = {}
        self._domains: Dict[str, str] = {}  # domain -> tenant_id

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def tenants(self) -> Dict[str, Tenant]:
        """Return the internal tenants mapping."""
        return self._tenants

    # ------------------------------------------------------------------
    # Tenant CRUD
    # ------------------------------------------------------------------

    def create_tenant(
        self,
        name: str,
        owner_email: str,
        trial_days: int = 0,
        features: Optional[List[FeatureFlag]] = None,
        reseller_id: Optional[str] = None,
    ) -> Tenant:
        """
        Create a new white-label tenant.

        Args:
            name: Display name of the tenant organisation.
            owner_email: Email address of the tenant owner.
            trial_days: Number of trial days; 0 means permanent (ACTIVE).
            features: Initial list of enabled feature flags.
            reseller_id: Optional ID of the referring reseller.

        Returns:
            The newly created Tenant.
        """
        tenant_id = _generate_id("WL")
        if trial_days > 0:
            status = TenantStatus.TRIAL
            expires_at: Optional[datetime] = datetime.now(timezone.utc) + timedelta(days=trial_days)
        else:
            status = TenantStatus.ACTIVE
            expires_at = None

        tenant = Tenant(
            tenant_id=tenant_id,
            name=name,
            owner_email=owner_email,
            status=status,
            expires_at=expires_at,
            features=list(features) if features is not None else [],
            reseller_id=reseller_id,
        )
        self._tenants[tenant_id] = tenant

        if reseller_id is not None:
            reseller = self._resellers.get(reseller_id)
            if reseller is not None:
                reseller.total_tenants += 1

        _logger.info("Created white-label tenant %s (%s)", tenant_id, name)
        return tenant

    def get_tenant(self, tenant_id: str) -> Optional[Tenant]:
        """Return the tenant with the given ID, or None."""
        return self._tenants.get(tenant_id)

    def activate_tenant(self, tenant_id: str) -> bool:
        """Activate a tenant, clearing any trial expiry. Returns True on success."""
        tenant = self.get_tenant(tenant_id)
        if tenant is None:
            return False
        tenant.status = TenantStatus.ACTIVE
        tenant.expires_at = None
        _logger.info("Tenant %s activated", tenant_id)
        return True

    def suspend_tenant(self, tenant_id: str) -> bool:
        """Suspend a tenant. Returns True on success."""
        tenant = self.get_tenant(tenant_id)
        if tenant is None:
            return False
        tenant.status = TenantStatus.SUSPENDED
        _logger.warning("Tenant %s suspended", tenant_id)
        return True

    def delete_tenant(self, tenant_id: str) -> bool:
        """Delete a tenant and remove any domain mapping. Returns True on success."""
        tenant = self._tenants.pop(tenant_id, None)
        if tenant is None:
            return False
        if tenant.custom_domain:
            self._domains.pop(tenant.custom_domain, None)
        _logger.info("Tenant %s deleted", tenant_id)
        return True

    def list_tenants(
        self, status: Optional[TenantStatus] = None
    ) -> List[Tenant]:
        """Return all tenants, optionally filtered by status."""
        tenants = list(self._tenants.values())
        if status is not None:
            tenants = [t for t in tenants if t.status == status]
        return tenants

    # ------------------------------------------------------------------
    # Theme management
    # ------------------------------------------------------------------

    def update_theme(self, tenant_id: str, theme_dict: Dict[str, Any]) -> bool:
        """Update the brand theme for a tenant from a dictionary of attributes."""
        tenant = self.get_tenant(tenant_id)
        if tenant is None:
            return False
        for key, value in theme_dict.items():
            if hasattr(tenant.theme, key):
                setattr(tenant.theme, key, value)
        _logger.info("Theme updated for tenant %s", tenant_id)
        return True

    def get_theme(self, tenant_id: str) -> Optional[BrandTheme]:
        """Return the BrandTheme for a tenant, or None if not found."""
        tenant = self.get_tenant(tenant_id)
        if tenant is None:
            return None
        return tenant.theme

    # ------------------------------------------------------------------
    # Feature flag management
    # ------------------------------------------------------------------

    def enable_feature(self, tenant_id: str, feature: FeatureFlag) -> bool:
        """Enable a feature flag for a tenant (idempotent). Returns True on success."""
        tenant = self.get_tenant(tenant_id)
        if tenant is None:
            return False
        if feature not in tenant.features:
            tenant.features.append(feature)
        return True

    def disable_feature(self, tenant_id: str, feature: FeatureFlag) -> bool:
        """Disable a feature flag for a tenant (no-op if not present). Returns True on success."""
        tenant = self.get_tenant(tenant_id)
        if tenant is None:
            return False
        if feature in tenant.features:
            tenant.features.remove(feature)
        return True

    def get_tenant_features(self, tenant_id: str) -> List[FeatureFlag]:
        """Return the list of enabled feature flags for a tenant, or [] if not found."""
        tenant = self.get_tenant(tenant_id)
        if tenant is None:
            return []
        return list(tenant.features)

    # ------------------------------------------------------------------
    # Domain management
    # ------------------------------------------------------------------

    def set_custom_domain(self, tenant_id: str, domain: str) -> bool:
        """
        Assign a custom domain to a tenant.

        Returns False if the domain is already assigned to a different tenant.
        Removes the old domain mapping when the tenant changes its domain.
        """
        tenant = self.get_tenant(tenant_id)
        if tenant is None:
            return False
        existing_owner = self._domains.get(domain)
        if existing_owner is not None and existing_owner != tenant_id:
            return False
        if tenant.custom_domain and tenant.custom_domain != domain:
            self._domains.pop(tenant.custom_domain, None)
        tenant.custom_domain = domain
        self._domains[domain] = tenant_id
        return True

    def resolve_domain(self, domain: str) -> Optional[Tenant]:
        """Return the tenant that owns the given domain, or None."""
        tenant_id = self._domains.get(domain)
        if tenant_id is None:
            return None
        return self._tenants.get(tenant_id)

    # ------------------------------------------------------------------
    # Reseller management
    # ------------------------------------------------------------------

    def create_reseller(
        self,
        company_name: str,
        contact_email: str,
        tier: ResellerTier = ResellerTier.STANDARD,
    ) -> Reseller:
        """
        Create a new reseller partner.

        Args:
            company_name: Name of the reseller's company.
            contact_email: Primary contact email.
            tier: Starting reseller tier (default: STANDARD).

        Returns:
            The newly created Reseller.
        """
        reseller_id = _generate_id("RS")
        reseller = Reseller(
            reseller_id=reseller_id,
            company_name=company_name,
            contact_email=contact_email,
            tier=tier,
        )
        self._resellers[reseller_id] = reseller
        _logger.info("Created reseller %s (%s)", reseller_id, company_name)
        return reseller

    def get_reseller(self, reseller_id: str) -> Optional[Reseller]:
        """Return the reseller with the given ID, or None."""
        return self._resellers.get(reseller_id)

    def calculate_commission(self, reseller_id: str, amount: float) -> float:
        """
        Calculate the commission owed to a reseller for a given transaction amount.

        Returns 0.0 if the reseller is not found or is inactive.
        Accumulates the commission amount in reseller.total_revenue.
        """
        reseller = self.get_reseller(reseller_id)
        if reseller is None or not reseller.is_active:
            return 0.0
        commission = amount * reseller.commission_rate
        reseller.total_revenue += amount
        return commission

    def upgrade_reseller_tier(self, reseller_id: str) -> Optional[ResellerTier]:
        """
        Upgrade a reseller's tier based on their total_tenants count.

        Returns the new ResellerTier if upgraded, or None if no upgrade is needed
        or the reseller does not exist.
        """
        reseller = self.get_reseller(reseller_id)
        if reseller is None:
            return None
        best_tier = ResellerTier.STANDARD
        for tier in _TIER_ORDER:
            if reseller.total_tenants >= TIER_TENANT_THRESHOLDS[tier]:
                best_tier = tier
                break
        if best_tier == reseller.tier:
            return None
        reseller.tier = best_tier
        reseller.commission_rate = TIER_COMMISSION_RATES[best_tier]
        _logger.info(
            "Reseller %s upgraded to %s", reseller_id, best_tier.value
        )
        return best_tier

    # ------------------------------------------------------------------
    # Export / Import
    # ------------------------------------------------------------------

    def export_tenant_config(self, tenant_id: str) -> Optional[Dict[str, Any]]:
        """
        Export a tenant's configuration as a serialisable dictionary.

        Returns None if the tenant does not exist.
        """
        tenant = self.get_tenant(tenant_id)
        if tenant is None:
            return None
        return {
            "name": tenant.name,
            "owner_email": tenant.owner_email,
            "theme": tenant.theme.to_dict(),
            "features": [f.value for f in tenant.features],
            "custom_domain": tenant.custom_domain,
        }

    def import_tenant_config(self, config: Dict[str, Any]) -> Tenant:
        """
        Import a tenant from a previously exported configuration dictionary.

        Creates a new tenant in this manager instance.
        """
        features = [
            FeatureFlag(v) for v in config.get("features", [])
        ]
        tenant = self.create_tenant(
            name=config["name"],
            owner_email=config.get("owner_email", ""),
            features=features,
        )
        theme_data = config.get("theme")
        if theme_data:
            tenant.theme = BrandTheme.from_dict(theme_data)
        custom_domain = config.get("custom_domain", "")
        if custom_domain:
            self.set_custom_domain(tenant.tenant_id, custom_domain)
        return tenant

    # ------------------------------------------------------------------
    # Summary
    # ------------------------------------------------------------------

    def get_platform_summary(self) -> Dict[str, Any]:
        """Return a high-level summary of the platform's tenants and resellers."""
        tenants = list(self._tenants.values())
        return {
            "total_tenants": len(tenants),
            "active_tenants": sum(
                1 for t in tenants if t.status == TenantStatus.ACTIVE
            ),
            "trial_tenants": sum(
                1 for t in tenants if t.status == TenantStatus.TRIAL
            ),
            "total_resellers": len(self._resellers),
            "total_users": sum(t.user_count for t in tenants),
        }


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

white_label_manager = WhiteLabelManager()

__all__ = [
    "TenantStatus",
    "FeatureFlag",
    "ResellerTier",
    "TIER_COMMISSION_RATES",
    "TIER_TENANT_THRESHOLDS",
    "BrandTheme",
    "Tenant",
    "Reseller",
    "WhiteLabelManager",
    "white_label_manager",
]
