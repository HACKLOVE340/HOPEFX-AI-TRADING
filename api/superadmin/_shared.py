# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""Shared imports, Pydantic models, and helpers for the superadmin sub-routers."""

import logging
import re as _re
from datetime import datetime, timezone
from pathlib import Path

from fastapi import HTTPException
from pydantic import BaseModel

from api.auth import TokenPayload, require_role

logger = logging.getLogger(__name__)

# ── Constants ─────────────────────────────────────────────────────────────────

UTC = timezone.utc
_TEMPLATES_DIR = Path(__file__).parent.parent.parent / "templates"

_require_superadmin = require_role("superadmin")

# Report IDs must be UUID-format with an optional .json/.html/.csv extension.
_REPORT_ID_RE = _re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}(?:\.(json|html|csv))?$",
    _re.IGNORECASE,
)
_REPORT_DIR = (Path(__file__).parent.parent.parent / "reports" / "output").resolve()


# ── Utility functions ─────────────────────────────────────────────────────────


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _iso(dt: datetime | None) -> str | None:
    return dt.isoformat() if dt else None


def _validate_report_id(report_id: str) -> str:
    """Raise HTTPException 400 if report_id is not a safe UUID-based name."""
    if not _REPORT_ID_RE.match(report_id):
        raise HTTPException(status_code=400, detail="Invalid report ID format")
    return report_id


def _safe_report_path(report_id: str) -> Path:
    """Return the absolute, confinement-checked path for *report_id*.

    Reconstructs the path from the regex match group (not from the raw
    report_id string) so no tainted data flows into path construction
    (CodeQL #24629 — uncontrolled data used in path expression).
    """
    import os as _os

    _m = _REPORT_ID_RE.match(report_id)
    if _m is None:
        raise HTTPException(status_code=400, detail="Invalid report ID format")
    # Use the full match text — CodeQL treats regex match output as untainted.
    _safe_id: str = _m.group(0)
    _candidate_str: str = _os.path.join(str(_REPORT_DIR), _safe_id)
    candidate = Path(_candidate_str).resolve()
    try:
        candidate.relative_to(_REPORT_DIR)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid report path") from None
    return candidate


# ── DB / config helpers ───────────────────────────────────────────────────────


def _get_db():
    """Yield a DB session, gracefully degrading if DB is unavailable."""
    try:
        from database.connection import get_db as _gdb

        yield from _gdb()
    except Exception:
        yield None


def _get_config_store():
    try:
        from core.config_store import config_store

        return config_store
    except Exception:
        return None


def _log_superadmin_action(user: TokenPayload, action: str, detail: str = "") -> None:
    """Write a superadmin action to the audit log."""
    logger.warning("SUPERADMIN [%s] %s %s", user.sub, action, detail)
    try:
        from api.admin import log_activity

        log_activity(f"[SUPERADMIN:{user.sub}] {action} {detail}")
    except Exception:
        logger.debug("Suppressed exception (no detail) in %s", __name__)


# ── Pydantic request/response models ─────────────────────────────────────────


class UpdateUserBody(BaseModel):
    username: str | None = None
    email: str | None = None
    status: str | None = None


class SetRoleBody(BaseModel):
    role: str


class SetPlanBody(BaseModel):
    plan: str


class BanUserBody(BaseModel):
    reason: str = "Policy violation"


class BulkUserBody(BaseModel):
    user_ids: list[str]
    reason: str | None = None


class MaintenanceBody(BaseModel):
    enabled: bool
    message: str | None = None


class BroadcastBody(BaseModel):
    title: str
    body: str
    type: str = "info"


class PlatformConfigBody(BaseModel):
    platform_name: str | None = None
    support_email: str | None = None
    max_users: int | None = None
    allow_registrations: bool | None = None
    require_email_verification: bool | None = None
    default_new_user_plan: str | None = None
    default_new_user_role: str | None = None
    session_timeout_minutes: int | None = None
    max_api_keys_per_user: int | None = None
    rate_limit_per_minute: int | None = None
    maintenance_mode: bool | None = None
    maintenance_message: str | None = None
    announcement_enabled: bool | None = None
    announcement_text: str | None = None
    announcement_type: str | None = None
    force_2fa_for_admins: bool | None = None
    ip_whitelist_enabled: bool | None = None
    ip_whitelist: str | None = None


class EngineConfigBody(BaseModel):
    paper_trading_mode: bool | None = None
    live_trading_enabled: bool | None = None
    max_open_positions: int | None = None
    max_risk_per_trade: float | None = None
    max_daily_loss_pct: float | None = None
    max_drawdown_pct: float | None = None
    default_lot_size: float | None = None
    slippage_tolerance: float | None = None
    default_leverage: int | None = None
    auto_trade_enabled: bool | None = None
    signal_confidence_threshold: float | None = None
    broker_type: str | None = None
    execution_mode: str | None = None


class KillSwitchBody(BaseModel):
    enabled: bool


class PauseBody(BaseModel):
    reason: str = "Superadmin manual pause"


class BlockIPBody(BaseModel):
    ip: str
    reason: str = "Manual block"


class SetLogLevelBody(BaseModel):
    logger: str
    level: str


class SetFeatureFlagBody(BaseModel):
    enabled: bool
    user_ids: list[str] | None = None


class SetUserFlagOverrideBody(BaseModel):
    enabled: bool


class RefundBody(BaseModel):
    reason: str = "Superadmin refund"


class MLControlBody(BaseModel):
    action: str  # start | pause | stop | reset


class DeployModelBody(BaseModel):
    model: str
    version: str


# ── Additional Pydantic models (institutional-grade extensions) ───────────────


class KYCDecisionBody(BaseModel):
    reason: str = ""


class AMLAlertUpdateBody(BaseModel):
    status: str
    notes: str = ""


class SanctionsClearBody(BaseModel):
    notes: str = ""


class RegReportTriggerBody(BaseModel):
    report_type: str
    period: str


class CircuitBreakerActionBody(BaseModel):
    reason: str = "Superadmin manual action"


class StressTestRunBody(BaseModel):
    scenario: str


class BrokerActionBody(BaseModel):
    reason: str = ""


class BrokerRoutingBody(BaseModel):
    primary_broker: str | None = None
    fallback_broker: str | None = None
    routing_mode: str | None = None


class TenantCreateBody(BaseModel):
    name: str
    domain: str
    plan: str = "starter"
    company_name: str = ""
    primary_color: str = "#3b82f6"


class TenantUpdateBody(BaseModel):
    status: str | None = None
    plan: str | None = None
    primary_color: str | None = None
    logo_url: str | None = None
    company_name: str | None = None


class GDPRProcessBody(BaseModel):
    action: str  # approve | reject
    notes: str = ""


class GDPREraseBody(BaseModel):
    reason: str


class RetentionPolicyBody(BaseModel):
    data_type: str
    retention_days: int


class NuclearHaltBody(BaseModel):
    reason: str


class NuclearHedgeBody(BaseModel):
    hedge_ratio: float = 1.0
    instrument: str = "XAUUSD"
    reason: str = ""


class NuclearRiskOverrideBody(BaseModel):
    max_risk_fraction: float
    reason: str = ""


class RateLimitRuleBody(BaseModel):
    endpoint: str
    limit: int
    window_seconds: int
    scope: str = "per_user"
    enabled: bool = True


class RateLimitRuleUpdateBody(BaseModel):
    limit: int | None = None
    window_seconds: int | None = None
    enabled: bool | None = None


class AlertRuleBody(BaseModel):
    name: str
    condition: str
    severity: str = "warning"
    channels: list[str] = []
    enabled: bool = True


class AlertRuleUpdateBody(BaseModel):
    name: str | None = None
    condition: str | None = None
    severity: str | None = None
    enabled: bool | None = None
    channels: list[str] | None = None


class SilenceAlertBody(BaseModel):
    duration_minutes: int = 60


class ReportGenerateBody(BaseModel):
    type: str
    period: str


class BackupTriggerBody(BaseModel):
    type: str = "incremental"


class ApiKeyRevokeBody(BaseModel):
    reason: str = "Superadmin revocation"
