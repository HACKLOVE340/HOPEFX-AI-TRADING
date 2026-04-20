# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""SuperAdmin platform config and trading engine sub-router."""

import logging
import sys
import time

from fastapi import APIRouter, Depends, Request

from api.auth import TokenPayload

from ._shared import (
    BroadcastBody,
    EngineConfigBody,
    KillSwitchBody,
    MaintenanceBody,
    PauseBody,
    PlatformConfigBody,
    _get_config_store as _shared_get_config_store,
    _log_superadmin_action,
    _require_superadmin,
    _utcnow,
)

logger = logging.getLogger(__name__)

router = APIRouter()


def _get_config_store():
    """Return config store, honouring any test-level patch on api.superadmin._get_config_store."""
    parent = sys.modules.get("api.superadmin")
    if parent is not None:
        fn = getattr(parent, "_get_config_store", None)
        if fn is not None and fn is not _get_config_store:
            return fn()
    return _shared_get_config_store()


# ── Platform config ───────────────────────────────────────────────────────────

_PLATFORM_CONFIG_KEY = "superadmin_platform_config"

_PLATFORM_CONFIG_DEFAULTS: dict = {
    "platform_name": "HOPEFX AI Trading",
    "support_email": "support@hopefx.ai",
    "max_users": 10000,
    "allow_registrations": True,
    "require_email_verification": True,
    "default_new_user_plan": "free",
    "default_new_user_role": "trader",
    "session_timeout_minutes": 60,
    "max_api_keys_per_user": 5,
    "rate_limit_per_minute": 60,
    "maintenance_mode": False,
    "maintenance_message": "We're performing scheduled maintenance. Back shortly.",
    "announcement_enabled": False,
    "announcement_text": "",
    "announcement_type": "info",
    "force_2fa_for_admins": False,
    "ip_whitelist_enabled": False,
    "ip_whitelist": "",
    # SMTP / Email
    "smtp_host": "",
    "smtp_port": 587,
    "smtp_user": "",
    "smtp_password": "",
    "smtp_from": "noreply@hopefx.ai",
    "smtp_from_name": "HOPEFX Trading",
    "smtp_tls": True,
    "smtp_enabled": False,
    # Monitoring / Observability
    "sentry_dsn": "",
    "sentry_environment": "production",
    "sentry_traces_sample_rate": 0.1,
    "sentry_profiles_sample_rate": 0.1,
    "prometheus_port": 9090,
    "prometheus_scrape_interval_seconds": 15,
    "prometheus_url": "http://prometheus:9090",
    "alertmanager_smtp_host": "localhost:587",
    "alertmanager_smtp_from": "alerts@hopefx.ai",
    "alertmanager_smtp_to": "",
    # Celery / Task Queue
    "celery_broker_url": "redis://redis:6379/1",
    "celery_result_backend": "redis://redis:6379/2",
    "celery_task_serializer": "json",
    "celery_result_expires": 3600,
    "celery_worker_concurrency": 4,
    "celery_max_tasks_per_child": 1000,
    # Compliance thresholds
    "kyc_required_for_live": True,
    "aml_transaction_threshold": 10000,
    "aml_daily_volume_threshold": 50000,
    "sanctions_check_enabled": True,
    "gdpr_data_retention_days": 365,
    "gdpr_erasure_grace_days": 30,
    "regulatory_reporting_enabled": False,
}


def _load_platform_config() -> dict:
    cs = _get_config_store()
    if cs:
        stored = cs.get(_PLATFORM_CONFIG_KEY)
        if stored:
            import json

            try:
                return {**_PLATFORM_CONFIG_DEFAULTS, **json.loads(stored)}
            except Exception:
                logger.debug("Suppressed exception (no detail) in %s", __name__)
    return dict(_PLATFORM_CONFIG_DEFAULTS)


def _save_platform_config(cfg: dict) -> None:
    cs = _get_config_store()
    if cs:
        import json

        cs.set(_PLATFORM_CONFIG_KEY, json.dumps(cfg))


@router.get("/platform/config")
async def get_platform_config(user: TokenPayload = Depends(_require_superadmin)) -> dict:
    return _load_platform_config()


@router.patch("/platform/config")
async def update_platform_config(body: PlatformConfigBody, user: TokenPayload = Depends(_require_superadmin)) -> dict:
    cfg = _load_platform_config()
    updates = body.model_dump(exclude_none=True)
    cfg.update(updates)
    _save_platform_config(cfg)
    _log_superadmin_action(user, "update_platform_config", str(list(updates.keys())))
    return {"ok": True}


@router.post("/platform/maintenance")
async def set_maintenance_mode(body: MaintenanceBody, user: TokenPayload = Depends(_require_superadmin)) -> dict:
    cfg = _load_platform_config()
    cfg["maintenance_mode"] = body.enabled
    if body.message:
        cfg["maintenance_message"] = body.message
    _save_platform_config(cfg)
    cs = _get_config_store()
    if cs:
        cs.set("maintenance_mode", "1" if body.enabled else "0")
    _log_superadmin_action(user, "maintenance_mode", str(body.enabled))
    return {"ok": True, "maintenance_mode": body.enabled}


@router.post("/platform/broadcast")
async def broadcast_message(body: BroadcastBody, user: TokenPayload = Depends(_require_superadmin)) -> dict:
    _log_superadmin_action(user, "broadcast", f"[{body.type}] {body.title}")
    try:
        from cache.redis_client import get_redis_client
        import json

        rc = get_redis_client()
        if rc:
            msg = {"title": body.title, "body": body.body, "type": body.type, "ts": _utcnow().isoformat()}
            rc.lpush("platform:broadcasts", json.dumps(msg))
            rc.ltrim("platform:broadcasts", 0, 49)
    except Exception as exc:
        logger.debug("broadcast redis: %s", exc)
    return {"ok": True}


# ── Trading engine ────────────────────────────────────────────────────────────

_ENGINE_CONFIG_KEY = "superadmin_engine_config"

_ENGINE_CONFIG_DEFAULTS: dict = {
    "paper_trading_mode": True,
    "live_trading_enabled": False,
    "max_open_positions": 5,
    "max_risk_per_trade": 2.0,
    "max_daily_loss_pct": 5.0,
    "max_drawdown_pct": 10.0,
    "default_lot_size": 0.01,
    "slippage_tolerance": 2.0,
    "default_leverage": 50,
    "auto_trade_enabled": False,
    "signal_confidence_threshold": 0.65,
    "kill_switch_active": False,
    "engine_status": "running",
    "broker_type": "paper",
    "execution_mode": "market",
}


def _load_engine_config() -> dict:
    cs = _get_config_store()
    if cs:
        stored = cs.get(_ENGINE_CONFIG_KEY)
        if stored:
            import json

            try:
                return {**_ENGINE_CONFIG_DEFAULTS, **json.loads(stored)}
            except Exception:
                logger.debug("Suppressed exception (no detail) in %s", __name__)
    # Also pull from legacy risk settings
    try:
        from api.admin import _get_risk_settings

        rs = _get_risk_settings()
        merged = dict(_ENGINE_CONFIG_DEFAULTS)
        merged["max_open_positions"] = rs.get("max_open_positions", merged["max_open_positions"])
        merged["max_risk_per_trade"] = rs.get("max_risk_per_trade", merged["max_risk_per_trade"])
        merged["max_daily_loss_pct"] = rs.get("max_daily_loss", merged["max_daily_loss_pct"])
        merged["max_drawdown_pct"] = rs.get("max_drawdown", merged["max_drawdown_pct"])
        merged["paper_trading_mode"] = rs.get("paper_trading_mode", merged["paper_trading_mode"])
        return merged
    except Exception:
        logger.debug("Suppressed exception (no detail) in %s", __name__)
    return dict(_ENGINE_CONFIG_DEFAULTS)


def _save_engine_config(cfg: dict) -> None:
    cs = _get_config_store()
    if cs:
        import json

        cs.set(_ENGINE_CONFIG_KEY, json.dumps(cfg))


@router.get("/engine/status")
async def get_engine_status(user: TokenPayload = Depends(_require_superadmin)) -> dict:
    cfg = _load_engine_config()
    return {"status": cfg.get("engine_status", "unknown"), "kill_switch_active": cfg.get("kill_switch_active", False)}


@router.get("/engine/config")
async def get_engine_config(user: TokenPayload = Depends(_require_superadmin)) -> dict:
    return _load_engine_config()


@router.patch("/engine/config")
async def update_engine_config(body: EngineConfigBody, user: TokenPayload = Depends(_require_superadmin)) -> dict:
    cfg = _load_engine_config()
    updates = body.model_dump(exclude_none=True)
    cfg.update(updates)
    _save_engine_config(cfg)
    try:
        from api.admin import apply_persisted_risk_settings

        apply_persisted_risk_settings()
    except Exception:
        logger.debug("Suppressed exception (no detail) in %s", __name__)
    _log_superadmin_action(user, "update_engine_config", str(list(updates.keys())))
    return {"ok": True}


@router.post("/engine/kill-switch")
async def toggle_kill_switch(body: KillSwitchBody, user: TokenPayload = Depends(_require_superadmin)) -> dict:
    cfg = _load_engine_config()
    cfg["kill_switch_active"] = body.enabled
    cfg["engine_status"] = "stopped" if body.enabled else "running"
    _save_engine_config(cfg)
    cs = _get_config_store()
    if cs:
        cs.set("kill_switch_active", "1" if body.enabled else "0")
    try:
        from kill_switch import KillSwitch

        ks = KillSwitch()
        if body.enabled:
            ks.activate("Superadmin kill switch")
        else:
            ks.deactivate()
    except Exception as exc:
        logger.debug("kill_switch module: %s", exc)
    _log_superadmin_action(user, "kill_switch", str(body.enabled))
    return {"ok": True, "kill_switch_active": body.enabled}


@router.post("/engine/pause")
async def pause_trading(body: PauseBody, user: TokenPayload = Depends(_require_superadmin)) -> dict:
    cfg = _load_engine_config()
    cfg["engine_status"] = "paused"
    _save_engine_config(cfg)
    _log_superadmin_action(user, "pause_trading", body.reason)
    return {"ok": True, "engine_status": "paused"}


@router.post("/engine/resume")
async def resume_trading(user: TokenPayload = Depends(_require_superadmin)) -> dict:
    cfg = _load_engine_config()
    cfg["engine_status"] = "running"
    _save_engine_config(cfg)
    _log_superadmin_action(user, "resume_trading")
    return {"ok": True, "engine_status": "running"}


@router.put("/platform/config/full")
async def save_full_platform_config(
    request: Request,
    user: TokenPayload = Depends(_require_superadmin),
) -> dict:
    """Accept and persist the complete platform config (all 200+ fields).

    Uses a free-form dict so new fields added to the frontend don't require
    a backend schema change.  Merges with existing config so partial updates
    are safe.
    """
    body: dict = await request.json()
    cfg = _load_platform_config()
    cfg.update(body)
    _save_platform_config(cfg)
    _log_superadmin_action(user, "full_platform_config_save", f"keys={len(body)}")
    return {"ok": True, "saved_keys": len(body), "saved_at": _utcnow().isoformat()}


@router.post("/platform/test-smtp")
async def test_smtp_config(
    request: Request,
    user: TokenPayload = Depends(_require_superadmin),
) -> dict:
    """Test SMTP connectivity using the current platform config or a provided override."""
    import smtplib
    import socket

    body: dict = {}
    try:
        body = await request.json()
    except Exception:
        pass

    cfg = _load_platform_config()
    host = body.get("host") or cfg.get("smtp_host", "")
    port = int(body.get("port") or cfg.get("smtp_port", 587))
    user_val = body.get("user") or cfg.get("smtp_user", "")
    password = body.get("password") or cfg.get("smtp_password", "")
    use_tls = body.get("tls", cfg.get("smtp_tls", True))

    if not host:
        return {"ok": False, "error": "SMTP host not configured"}

    try:
        if use_tls:
            server = smtplib.SMTP(host, port, timeout=10)
            server.starttls()
        else:
            server = smtplib.SMTP(host, port, timeout=10)
        if user_val and password:
            server.login(user_val, password)
        server.quit()
        _log_superadmin_action(user, "smtp_test", f"host={host}:{port} ok")
        return {"ok": True, "host": host, "port": port}
    except (smtplib.SMTPException, socket.error, OSError) as exc:
        _log_superadmin_action(user, "smtp_test_failed", f"host={host}:{port} err={exc}")
        return {"ok": False, "error": str(exc)}


@router.get("/platform/config/validate")
async def validate_platform_config(
    user: TokenPayload = Depends(_require_superadmin),
) -> dict:
    """
    Validate the current platform config for consistency and completeness.

    Checks required fields, value ranges, and cross-field constraints.
    Returns a list of warnings and errors without modifying any state.
    """
    cfg = _load_platform_config()
    issues: list[dict] = []

    def warn(field: str, msg: str) -> None:
        issues.append({"severity": "warning", "field": field, "message": msg})

    def error(field: str, msg: str) -> None:
        issues.append({"severity": "error", "field": field, "message": msg})

    # Platform identity
    if not cfg.get("support_email"):
        warn("support_email", "Support email not configured")
    if not cfg.get("platform_name"):
        error("platform_name", "Platform name is required")

    # Security
    if cfg.get("debug") and cfg.get("env") == "production":
        error("debug", "Debug mode must not be enabled in production")
    if cfg.get("access_token_expire_minutes", 30) > 1440:
        warn("access_token_expire_minutes", "Access token expiry > 24h is a security risk")

    # ML
    if cfg.get("ml_drift_threshold", 0.05) > 0.2:
        warn("ml_drift_threshold", "Drift threshold > 0.2 may miss significant model degradation")
    if cfg.get("signal_threshold_long", 0.58) < 0.5:
        error("signal_threshold_long", "Long signal threshold below 0.5 means random signals")

    # Risk
    if cfg.get("risk_max_daily_loss_pct", 0.05) > 0.2:
        warn("risk_max_daily_loss_pct", "Daily loss limit > 20% is extremely high risk")
    if cfg.get("risk_max_drawdown_pct", 0.10) > 0.5:
        error("risk_max_drawdown_pct", "Max drawdown > 50% will likely cause account wipeout")
    if cfg.get("risk_kelly_fraction", 0.25) > 0.5:
        warn("risk_kelly_fraction", "Kelly fraction > 0.5 is aggressive; consider 0.25 or less")

    # Execution
    if cfg.get("engine_tick_loop_hz", 1.0) > 100:
        warn("engine_tick_loop_hz", "Tick loop > 100 Hz may overload the system")

    # Kill switch
    if cfg.get("hopefx_kill_switch") and cfg.get("trading_mode") == "live":
        warn("hopefx_kill_switch", "Kill switch is active but trading mode is live — all trades blocked")

    # SMTP
    if cfg.get("smtp_enabled") and not cfg.get("smtp_host"):
        error("smtp_host", "SMTP enabled but host not configured")

    # Compliance
    if cfg.get("trading_mode") == "live" and not cfg.get("kyc_required_for_live"):
        warn("kyc_required_for_live", "Live trading without KYC requirement is a compliance risk")

    errors = [i for i in issues if i["severity"] == "error"]
    warnings = [i for i in issues if i["severity"] == "warning"]

    return {
        "valid": len(errors) == 0,
        "error_count": len(errors),
        "warning_count": len(warnings),
        "issues": issues,
        "checked_at": _utcnow().isoformat(),
    }


@router.get("/engine/metrics")
async def get_engine_metrics(user: TokenPayload = Depends(_require_superadmin)) -> dict:
    metrics: dict = {
        "trades_today": 0,
        "open_positions": 0,
        "pnl_today": 0.0,
        "win_rate_today": 0.0,
        "avg_execution_ms": 0,
        "rejected_orders": 0,
        "kill_switch_triggers": 0,
        "uptime_hours": 0.0,
    }
    try:
        from api.admin import app_state, _start_time

        metrics["uptime_hours"] = round((time.time() - _start_time) / 3600, 2)
        if app_state and hasattr(app_state, "engine"):
            eng = app_state.engine
            metrics["open_positions"] = len(getattr(eng, "positions", {}))
    except Exception:
        logger.debug("Suppressed exception (no detail) in %s", __name__)
    return metrics
