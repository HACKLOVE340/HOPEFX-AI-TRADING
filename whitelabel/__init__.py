"""
White-Label Module for HOPEFX AI Trading Platform

Provides brand customisation, tenant configuration, and white-label
management for resellers and partners deploying the platform under
their own brand.

Key components:
    - BrandColors / BrandAssets / BrandTheme: visual identity dataclasses
    - TenantContact / TenantLinks / TenantFeatures: tenant sub-configs
    - WhiteLabelConfig: composed tenant configuration
    - Tenant: a white-label deployment instance
    - WhiteLabelManager: CRUD and lifecycle manager for tenants
"""

import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional
from enum import Enum

_logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------


class TenantStatus(str, Enum):
    """Lifecycle status for a white-label tenant."""

    PENDING = "pending"
    ACTIVE = "active"
    SUSPENDED = "suspended"
    TERMINATED = "terminated"


class DeploymentEnvironment(str, Enum):
    """Target deployment environment for a tenant."""

    PRODUCTION = "production"
    STAGING = "staging"
    DEVELOPMENT = "development"


# ---------------------------------------------------------------------------
# Brand theme dataclasses (composed to keep attribute counts manageable)
# ---------------------------------------------------------------------------


@dataclass
class BrandColors:
    """Colour palette for white-label branding."""

    primary: str = "#1976D2"
    secondary: str = "#424242"
    accent: str = "#FF5722"
    background: str = "#FAFAFA"
    surface: str = "#FFFFFF"
    error: str = "#D32F2F"
    text_primary: str = "#212121"


@dataclass
class BrandAssets:
    """Graphic asset URLs for white-label branding."""

    logo_url: str = ""
    favicon_url: str = ""
    banner_url: str = ""
    icon_url: str = ""


@dataclass
class BrandTheme:
    """Complete brand theme composed from colour and asset sub-themes."""

    colors: BrandColors = field(default_factory=BrandColors)
    assets: BrandAssets = field(default_factory=BrandAssets)
    font_family: str = "Roboto, sans-serif"
    border_radius: str = "4px"
    custom_css: str = ""

    def is_configured(self) -> bool:
        """Return True when the essential logo asset has been provided."""
        return bool(self.assets.logo_url)

    def to_dict(self) -> Dict[str, Any]:
        """Serialise the theme to a plain dictionary."""
        return {
            "colors": {
                "primary": self.colors.primary,
                "secondary": self.colors.secondary,
                "accent": self.colors.accent,
                "background": self.colors.background,
                "surface": self.colors.surface,
                "error": self.colors.error,
            },
            "assets": {
                "logo_url": self.assets.logo_url,
                "favicon_url": self.assets.favicon_url,
                "banner_url": self.assets.banner_url,
            },
            "font_family": self.font_family,
            "border_radius": self.border_radius,
        }


# ---------------------------------------------------------------------------
# Tenant contact, links and feature sub-dataclasses
# ---------------------------------------------------------------------------


@dataclass
class TenantContact:
    """Contact and company information for a white-label tenant."""

    company_name: str
    support_email: str
    admin_email: str
    website_url: str = ""
    support_phone: str = ""
    address: str = ""


@dataclass
class TenantLinks:
    """External URL overrides for a white-label tenant."""

    terms_url: str = ""
    privacy_url: str = ""
    help_url: str = ""
    blog_url: str = ""


@dataclass
class TenantFeatures:
    """Feature-flag configuration for a white-label tenant."""

    sso_enabled: bool = False
    custom_domain: bool = False
    api_access: bool = True
    audit_logging: bool = True
    email_branding: bool = True
    max_users: int = 50


# ---------------------------------------------------------------------------
# Deployment settings sub-dataclass
# ---------------------------------------------------------------------------


@dataclass
class TenantDeployment:
    """Deployment settings for a white-label tenant."""

    subdomain: str = ""
    custom_domain: str = ""
    environment: DeploymentEnvironment = DeploymentEnvironment.PRODUCTION
    links: TenantLinks = field(default_factory=TenantLinks)


# ---------------------------------------------------------------------------
# Composed tenant configuration
# ---------------------------------------------------------------------------


class WhiteLabelConfig:
    """
    Configuration bundle for a white-label tenant.

    Composes TenantContact, BrandTheme, TenantFeatures, and
    TenantDeployment into a single object while keeping the number
    of direct instance attributes manageable.
    """

    def __init__(
        self,
        contact: TenantContact,
        theme: BrandTheme,
        features: TenantFeatures,
        deployment: Optional[TenantDeployment] = None,
    ) -> None:
        self.contact = contact
        self.theme = theme
        self.features = features
        self.deployment = deployment or TenantDeployment()

    @property
    def primary_domain(self) -> str:
        """Return the active domain (custom domain takes priority)."""
        if self.deployment.custom_domain:
            return self.deployment.custom_domain
        if self.deployment.subdomain:
            return f"{self.deployment.subdomain}.hopefx.ai"
        return ""

    def to_dict(self) -> Dict[str, Any]:
        """Serialise the configuration to a plain dictionary."""
        return {
            "company_name": self.contact.company_name,
            "support_email": self.contact.support_email,
            "website_url": self.contact.website_url,
            "subdomain": self.deployment.subdomain,
            "custom_domain": self.deployment.custom_domain,
            "primary_domain": self.primary_domain,
            "environment": self.deployment.environment.value,
            "theme": self.theme.to_dict(),
            "links": {
                "terms_url": self.deployment.links.terms_url,
                "privacy_url": self.deployment.links.privacy_url,
                "help_url": self.deployment.links.help_url,
            },
            "features": {
                "sso_enabled": self.features.sso_enabled,
                "custom_domain": self.features.custom_domain,
                "api_access": self.features.api_access,
                "max_users": self.features.max_users,
            },
        }


# ---------------------------------------------------------------------------
# Tenant
# ---------------------------------------------------------------------------


class Tenant:
    """A white-label tenant deployment."""

    def __init__(
        self,
        tenant_id: str,
        config: WhiteLabelConfig,
        status: TenantStatus = TenantStatus.PENDING,
    ) -> None:
        self.tenant_id = tenant_id
        self.config = config
        self.status = status
        self.created_at: datetime = datetime.utcnow()
        self.activated_at: Optional[datetime] = None
        self.suspended_at: Optional[datetime] = None

    def activate(self) -> None:
        """Mark this tenant as active."""
        self.status = TenantStatus.ACTIVE
        self.activated_at = datetime.utcnow()
        _logger.info("Tenant %s activated", self.tenant_id)

    def suspend(self, reason: str = "") -> None:
        """Suspend this tenant."""
        self.status = TenantStatus.SUSPENDED
        self.suspended_at = datetime.utcnow()
        _logger.warning("Tenant %s suspended: %s", self.tenant_id, reason)

    def terminate(self) -> None:
        """Permanently terminate this tenant."""
        self.status = TenantStatus.TERMINATED
        _logger.info("Tenant %s terminated", self.tenant_id)

    def is_active(self) -> bool:
        """Return True if the tenant is currently active."""
        return self.status == TenantStatus.ACTIVE

    def update_config(self, config: WhiteLabelConfig) -> None:
        """Replace the tenant's configuration."""
        self.config = config
        _logger.info("Tenant %s configuration updated", self.tenant_id)

    def to_dict(self) -> Dict[str, Any]:
        """Serialise the tenant to a plain dictionary."""
        return {
            "tenant_id": self.tenant_id,
            "status": self.status.value,
            "config": self.config.to_dict(),
            "created_at": self.created_at.isoformat(),
            "activated_at": (
                self.activated_at.isoformat() if self.activated_at else None
            ),
            "suspended_at": (
                self.suspended_at.isoformat() if self.suspended_at else None
            ),
        }


# ---------------------------------------------------------------------------
# White-label manager
# ---------------------------------------------------------------------------


class WhiteLabelManager:
    """
    Central manager for white-label tenants.

    Responsibilities:
    - Create and provision new tenants
    - Look up tenants by ID or domain
    - Lifecycle management (activate, suspend, terminate)
    - Reporting and statistics
    """

    def __init__(self) -> None:
        self._tenants: Dict[str, Tenant] = {}

    # ------------------------------------------------------------------
    # Creation
    # ------------------------------------------------------------------

    def create_tenant(
        self,
        contact: TenantContact,
        theme: Optional[BrandTheme] = None,
        features: Optional[TenantFeatures] = None,
        deployment: Optional[TenantDeployment] = None,
    ) -> Tenant:
        """
        Create a new white-label tenant.

        Args:
            contact: Company and contact details.
            theme: Optional brand theme; a default theme is used if omitted.
            features: Optional feature flags; defaults used if omitted.
            deployment: Optional deployment settings; defaults used if omitted.

        Returns:
            The newly created Tenant.
        """
        tenant_id = f"WL-{uuid.uuid4().hex[:12].upper()}"
        config = WhiteLabelConfig(
            contact=contact,
            theme=theme or BrandTheme(),
            features=features or TenantFeatures(),
            deployment=deployment or TenantDeployment(),
        )
        tenant = Tenant(tenant_id=tenant_id, config=config)
        self._tenants[tenant_id] = tenant
        _logger.info(
            "Created white-label tenant %s for %s",
            tenant_id,
            contact.company_name,
        )
        return tenant

    # ------------------------------------------------------------------
    # Retrieval
    # ------------------------------------------------------------------

    def get_tenant(self, tenant_id: str) -> Optional[Tenant]:
        """Return the tenant with the given ID, or None."""
        return self._tenants.get(tenant_id)

    def find_by_domain(self, domain: str) -> Optional[Tenant]:
        """Look up a tenant by its primary domain."""
        for tenant in self._tenants.values():
            if tenant.config.primary_domain == domain:
                return tenant
        return None

    def get_all_tenants(
        self,
        status: Optional[TenantStatus] = None,
    ) -> List[Tenant]:
        """Return all tenants, optionally filtered by status."""
        tenants = list(self._tenants.values())
        if status is not None:
            tenants = [t for t in tenants if t.status == status]
        return tenants

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def activate_tenant(self, tenant_id: str) -> bool:
        """Activate a tenant. Returns True on success."""
        tenant = self.get_tenant(tenant_id)
        if tenant is None:
            return False
        tenant.activate()
        return True

    def suspend_tenant(self, tenant_id: str, reason: str = "") -> bool:
        """Suspend a tenant. Returns True on success."""
        tenant = self.get_tenant(tenant_id)
        if tenant is None:
            return False
        tenant.suspend(reason)
        return True

    def terminate_tenant(self, tenant_id: str) -> bool:
        """Permanently terminate a tenant. Returns True on success."""
        tenant = self.get_tenant(tenant_id)
        if tenant is None:
            return False
        tenant.terminate()
        return True

    # ------------------------------------------------------------------
    # Config helpers
    # ------------------------------------------------------------------

    def update_tenant_theme(
        self, tenant_id: str, theme: BrandTheme
    ) -> bool:
        """Replace the brand theme for a tenant. Returns True on success."""
        tenant = self.get_tenant(tenant_id)
        if tenant is None:
            return False
        tenant.config.theme = theme
        _logger.info("Theme updated for tenant %s", tenant_id)
        return True

    def update_tenant_features(
        self, tenant_id: str, features: TenantFeatures
    ) -> bool:
        """Replace the feature flags for a tenant. Returns True on success."""
        tenant = self.get_tenant(tenant_id)
        if tenant is None:
            return False
        tenant.config.features = features
        _logger.info("Features updated for tenant %s", tenant_id)
        return True

    # ------------------------------------------------------------------
    # Statistics
    # ------------------------------------------------------------------

    def get_stats(self) -> Dict[str, Any]:
        """Return a summary of tenant counts broken down by status."""
        tenants = list(self._tenants.values())
        return {
            "total": len(tenants),
            "active": sum(
                1 for t in tenants if t.status == TenantStatus.ACTIVE
            ),
            "pending": sum(
                1 for t in tenants if t.status == TenantStatus.PENDING
            ),
            "suspended": sum(
                1 for t in tenants if t.status == TenantStatus.SUSPENDED
            ),
            "terminated": sum(
                1 for t in tenants if t.status == TenantStatus.TERMINATED
            ),
        }

    def to_dict(self) -> Dict[str, Any]:
        """Serialise all tenants to a dictionary keyed by tenant ID."""
        return {tid: t.to_dict() for tid, t in self._tenants.items()}


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_white_label_manager = WhiteLabelManager()

__all__ = [
    "TenantStatus",
    "DeploymentEnvironment",
    "BrandColors",
    "BrandAssets",
    "BrandTheme",
    "TenantContact",
    "TenantLinks",
    "TenantFeatures",
    "TenantDeployment",
    "WhiteLabelConfig",
    "Tenant",
    "WhiteLabelManager",
]
