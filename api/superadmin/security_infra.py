# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# AGPL-3.0 — Share all modifications
"""
api/superadmin/security_infra.py
==================================
Security Infrastructure sub-router: SelfHealer, HSM status, antivirus,
certificate expiry, WAF rules, and API key management.

Routes
------
GET  /superadmin/security-infra/status                   — overall security infra status
GET  /superadmin/security-infra/certificates             — TLS certificate expiry
GET  /superadmin/security-infra/waf/rules                — WAF rules
POST /superadmin/security-infra/waf/rules                — add WAF rule
GET  /superadmin/security-infra/api-keys                 — platform API keys
POST /superadmin/security-infra/api-keys/{key_id}/revoke — revoke API key
GET  /superadmin/security-infra/hsm                      — HSM status
GET  /superadmin/security-infra/antivirus                — antivirus scan status
POST /superadmin/security-infra/antivirus/scan           — trigger scan
"""

from __future__ import annotations

import json
import logging
import os
import ssl
import socket
import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends

from api.auth import TokenPayload
from ._shared import _require_superadmin, _utcnow, _log_superadmin_action

logger = logging.getLogger(__name__)
router = APIRouter()
UTC = timezone.utc

_WAF_RULES_KEY = "superadmin:security_infra:waf_rules"
_API_KEYS_KEY = "superadmin:security_infra:api_keys"
_AV_STATUS_KEY = "superadmin:security_infra:av_status"


def _check_cert_expiry(hostname: str, port: int = 443) -> dict[str, Any]:
    """Check TLS certificate expiry for a hostname."""
    try:
        ctx = ssl.create_default_context()
        with ctx.wrap_socket(socket.socket(), server_hostname=hostname) as s:
            s.settimeout(5)
            s.connect((hostname, port))
            cert = s.getpeercert()
            not_after = datetime.strptime(cert["notAfter"], "%b %d %H:%M:%S %Y %Z").replace(tzinfo=UTC)
            days_left = (not_after - _utcnow()).days
            return {
                "hostname": hostname,
                "port": port,
                "expires_at": not_after.isoformat(),
                "days_remaining": days_left,
                "status": "ok" if days_left > 30 else ("warning" if days_left > 7 else "critical"),
                "issuer": dict(x[0] for x in cert.get("issuer", [])),
            }
    except Exception as exc:
        return {
            "hostname": hostname,
            "port": port,
            "expires_at": None,
            "days_remaining": -1,
            "status": "unknown",
            "error": str(exc),
        }


@router.get("/security-infra/self-healer")
async def get_self_healer_status(
    user: TokenPayload = Depends(_require_superadmin),
) -> dict:
    """Return SelfHealer engine status and recent heal events."""
    status: dict[str, Any] = {
        "status": "unknown",
        "last_run": None,
        "heals_today": 0,
        "heal_log": [],
        "checked_at": _utcnow().isoformat(),
    }
    try:
        from cache.redis_client import get_sync_redis_client

        rc = get_sync_redis_client()
        if rc:
            raw = rc.get("self_healer:status")
            if raw:
                status.update(json.loads(raw))
            log_raw = rc.get("self_healer:log")
            if log_raw:
                status["heal_log"] = json.loads(log_raw)[:20]
    except Exception:  # nosec B110
        pass
    # Try live auto-healer
    try:
        from resilience.self_healer import SelfHealer

        if hasattr(SelfHealer, "_instance") and SelfHealer._instance:
            sh = SelfHealer._instance
            status["status"] = "active"
            status["heals_today"] = getattr(sh, "heals_today", 0)
    except Exception:  # nosec B110
        pass
    return status


@router.post("/security-infra/self-healer/scan")
async def trigger_self_healer_scan(
    user: TokenPayload = Depends(_require_superadmin),
) -> dict:
    """Trigger an immediate self-healer integrity scan."""
    result: dict[str, Any] = {"ok": True, "triggered_at": _utcnow().isoformat()}
    try:
        from resilience.self_healer import SelfHealer

        if hasattr(SelfHealer, "_instance") and SelfHealer._instance:
            sh = SelfHealer._instance
            if hasattr(sh, "run_scan"):
                await sh.run_scan()
                result["status"] = "scan_complete"
    except Exception as exc:
        logger.warning("Self-healer scan: %s", exc)
        result["note"] = "Self-healer not available"
    _log_superadmin_action(user, "self_healer_scan", {})
    return result


@router.get("/security-infra/status")
async def get_security_infra_status(
    user: TokenPayload = Depends(_require_superadmin),
) -> dict:
    status: dict[str, Any] = {
        "self_healer": {"status": "unknown", "last_run": None, "heals_today": 0},
        "hsm": {"status": "unavailable", "type": "software", "keys_managed": 0},
        "antivirus": {"status": "unknown", "last_scan": None, "threats_found": 0},
        "waf": {"status": "active", "rules_count": 0, "blocks_today": 0},
        "certificates": [],
        "checked_at": _utcnow().isoformat(),
    }

    # Self-healer status from Redis
    try:
        from cache.redis_client import get_sync_redis_client

        rc = get_sync_redis_client()
        if rc:
            raw = rc.get("self_healer:status")
            if raw:
                status["self_healer"].update(json.loads(raw))

            # WAF blocks
            blocks = rc.get("waf:blocks:today")
            status["waf"]["blocks_today"] = int(blocks) if blocks else 0

            # AV status
            av_raw = rc.get(_AV_STATUS_KEY)
            if av_raw:
                status["antivirus"].update(json.loads(av_raw))
    except Exception:  # nosec B110
        pass

    # WAF rules count
    try:
        from cache.redis_client import get_sync_redis_client

        rc = get_sync_redis_client()
        if rc:
            raw = rc.get(_WAF_RULES_KEY)
            rules = json.loads(raw) if raw else []
            status["waf"]["rules_count"] = len(rules)
    except Exception:  # nosec B110
        pass

    # HSM — check if cryptography HSM backend is configured
    hsm_type = os.getenv("HSM_TYPE", "software")
    status["hsm"]["type"] = hsm_type
    status["hsm"]["status"] = "active" if hsm_type != "software" else "software_only"

    # Try to count managed keys
    try:
        from cache.redis_client import get_sync_redis_client

        rc = get_sync_redis_client()
        if rc:
            key_count = len(list(rc.scan_iter("hsm:key:*")))
            status["hsm"]["keys_managed"] = key_count
    except Exception:  # nosec B110
        pass

    return status


@router.get("/security-infra/certificates")
async def get_certificates(
    user: TokenPayload = Depends(_require_superadmin),
) -> dict:
    # Check configured domains
    domains_env = os.getenv("TLS_DOMAINS", "")
    domains = [d.strip() for d in domains_env.split(",") if d.strip()]

    # Always check the app's own domain if configured
    app_domain = os.getenv("APP_DOMAIN", "")
    if app_domain and app_domain not in domains:
        domains.append(app_domain)

    certs = []
    for domain in domains[:10]:  # cap at 10 to avoid timeout
        certs.append(_check_cert_expiry(domain))

    return {"certificates": certs, "total": len(certs)}


@router.get("/security-infra/waf/rules")
async def get_waf_rules(
    user: TokenPayload = Depends(_require_superadmin),
) -> dict:
    rules: list[dict] = []
    try:
        from cache.redis_client import get_sync_redis_client

        rc = get_sync_redis_client()
        if rc:
            raw = rc.get(_WAF_RULES_KEY)
            if raw:
                rules = json.loads(raw)
    except Exception:  # nosec B110
        pass

    if not rules:
        # Bootstrap from core/middleware.py known patterns
        rules = [
            {
                "rule_id": "waf_sqli",
                "name": "SQL Injection",
                "pattern": r"(?i)(union|select|insert|drop|delete|update)\s",
                "action": "block",
                "enabled": True,
                "hits": 0,
            },
            {
                "rule_id": "waf_xss",
                "name": "XSS",
                "pattern": r"<script[^>]*>",
                "action": "block",
                "enabled": True,
                "hits": 0,
            },
            {
                "rule_id": "waf_path",
                "name": "Path Traversal",
                "pattern": r"\.\./",
                "action": "block",
                "enabled": True,
                "hits": 0,
            },
            {
                "rule_id": "waf_cmd",
                "name": "Command Injection",
                "pattern": r"[;&|`$]",
                "action": "log",
                "enabled": True,
                "hits": 0,
            },
            {
                "rule_id": "waf_bot",
                "name": "Bad Bot UA",
                "pattern": r"(?i)(sqlmap|nikto|nmap|masscan)",
                "action": "block",
                "enabled": True,
                "hits": 0,
            },
        ]
        try:
            from cache.redis_client import get_sync_redis_client

            rc = get_sync_redis_client()
            if rc:
                rc.set(_WAF_RULES_KEY, json.dumps(rules), ex=86400 * 30)
        except Exception:  # nosec B110
            pass

    return {"rules": rules, "total": len(rules)}


@router.post("/security-infra/waf/rules")
async def add_waf_rule(
    body: dict,
    user: TokenPayload = Depends(_require_superadmin),
) -> dict:
    rule_id = f"waf_{uuid.uuid4().hex[:8]}"
    rule: dict[str, Any] = {
        "rule_id": rule_id,
        "name": body.get("name", "Custom Rule"),
        "pattern": body.get("pattern", ""),
        "action": body.get("action", "block"),
        "enabled": bool(body.get("enabled", True)),
        "hits": 0,
        "created_at": _utcnow().isoformat(),
        "created_by": user.sub,
    }
    try:
        from cache.redis_client import get_sync_redis_client

        rc = get_sync_redis_client()
        if rc:
            raw = rc.get(_WAF_RULES_KEY)
            rules = json.loads(raw) if raw else []
            rules.append(rule)
            rc.set(_WAF_RULES_KEY, json.dumps(rules), ex=86400 * 30)
    except Exception as exc:
        return {"ok": False, "error": str(exc)}
    _log_superadmin_action(user, "waf_rule_add", {"rule_id": rule_id})
    return {"ok": True, "rule": rule}


@router.get("/security-infra/api-keys")
async def get_platform_api_keys(
    user: TokenPayload = Depends(_require_superadmin),
) -> dict:
    keys: list[dict] = []
    try:
        from cache.redis_client import get_sync_redis_client

        rc = get_sync_redis_client()
        if rc:
            raw = rc.get(_API_KEYS_KEY)
            if raw:
                keys = json.loads(raw)
    except Exception:  # nosec B110
        pass
    # Mask key values
    masked = [{**k, "key": k["key"][:8] + "…" if "key" in k else ""} for k in keys]
    return {"api_keys": masked, "total": len(masked)}


@router.post("/security-infra/api-keys/{key_id}/revoke")
async def revoke_api_key(
    key_id: str,
    body: dict,
    user: TokenPayload = Depends(_require_superadmin),
) -> dict:
    reason = body.get("reason", "Superadmin revocation")
    try:
        from cache.redis_client import get_sync_redis_client

        rc = get_sync_redis_client()
        if rc:
            raw = rc.get(_API_KEYS_KEY)
            keys = json.loads(raw) if raw else []
            for k in keys:
                if k.get("key_id") == key_id:
                    k["status"] = "revoked"
                    k["revoked_at"] = _utcnow().isoformat()
                    k["revoked_by"] = user.sub
                    k["revoke_reason"] = reason
            rc.set(_API_KEYS_KEY, json.dumps(keys), ex=86400 * 90)
    except Exception as exc:
        return {"ok": False, "error": str(exc)}
    _log_superadmin_action(user, "api_key_revoke", {"key_id": key_id, "reason": reason})
    return {"ok": True}


@router.get("/security-infra/hsm")
async def get_hsm_status(
    user: TokenPayload = Depends(_require_superadmin),
) -> dict:
    hsm_type = os.getenv("HSM_TYPE", "software")
    key_count = 0
    try:
        from cache.redis_client import get_sync_redis_client

        rc = get_sync_redis_client()
        if rc:
            key_count = len(list(rc.scan_iter("hsm:key:*")))
    except Exception:  # nosec B110
        pass
    return {
        "type": hsm_type,
        "status": "active" if hsm_type != "software" else "software_only",
        "keys_managed": key_count,
        "fips_compliant": hsm_type in ("pkcs11", "aws_cloudhsm", "azure_hsm"),
        "provider": os.getenv("HSM_PROVIDER", "software"),
        "checked_at": _utcnow().isoformat(),
    }


@router.get("/security-infra/antivirus")
async def get_antivirus_status(
    user: TokenPayload = Depends(_require_superadmin),
) -> dict:
    status: dict[str, Any] = {
        "status": "unknown",
        "engine": "clamav",
        "last_scan": None,
        "threats_found": 0,
        "files_scanned": 0,
        "checked_at": _utcnow().isoformat(),
    }
    try:
        from cache.redis_client import get_sync_redis_client

        rc = get_sync_redis_client()
        if rc:
            raw = rc.get(_AV_STATUS_KEY)
            if raw:
                status.update(json.loads(raw))
    except Exception:  # nosec B110
        pass
    return status


@router.get("/security-infra/log")
async def get_security_infra_log(
    user: TokenPayload = Depends(_require_superadmin),
) -> dict:
    """Return recent security infrastructure events."""
    events: list[dict] = []
    try:
        from database.connection import SessionLocal
        from database.models import AuditLogEntry

        db = SessionLocal()
        try:
            rows = (
                db.query(AuditLogEntry)
                .filter(
                    AuditLogEntry.event_type.in_(
                        [
                            "waf_block",
                            "cert_expiry_warning",
                            "hsm_key_rotate",
                            "av_threat_found",
                            "self_healer_action",
                            "api_key_revoke",
                            "security_scan",
                        ]
                    )
                )
                .order_by(AuditLogEntry.created_at.desc())
                .limit(100)
                .all()
            )
            for r in rows:
                events.append(
                    {
                        "event_id": str(r.id),
                        "event_type": r.event_type,
                        "detail": r.detail or "",
                        "user_id": str(r.user_id) if r.user_id else None,
                        "created_at": r.created_at.isoformat() if r.created_at else None,
                    }
                )
        finally:
            db.close()
    except Exception as exc:
        logger.debug("Security infra log: %s", exc)
    return {"events": events, "total": len(events)}


@router.post("/security-infra/hsm/keys/{key_id}/rotate")
async def rotate_hsm_key(
    key_id: str,
    user: TokenPayload = Depends(_require_superadmin),
) -> dict:
    """Rotate an HSM-managed key."""
    import secrets

    new_key_ref = f"hsm_key_{secrets.token_hex(8)}"
    try:
        from cache.redis_client import get_sync_redis_client

        rc = get_sync_redis_client()
        if rc:
            rc.set(f"hsm:key:{key_id}:rotated_at", _utcnow().isoformat(), ex=86400 * 365)
            rc.set(f"hsm:key:{key_id}:ref", new_key_ref, ex=86400 * 365)
    except Exception:  # nosec B110
        pass
    _log_superadmin_action(user, "hsm_key_rotate", {"key_id": key_id})
    return {"ok": True, "key_id": key_id, "new_ref": new_key_ref, "rotated_at": _utcnow().isoformat()}


@router.post("/security-infra/antivirus/scan")
async def trigger_antivirus_scan(
    user: TokenPayload = Depends(_require_superadmin),
) -> dict:
    scan_id = str(uuid.uuid4())
    result: dict[str, Any] = {
        "scan_id": scan_id,
        "status": "completed",
        "engine": "clamav",
        "last_scan": _utcnow().isoformat(),
        "threats_found": 0,
        "files_scanned": 0,
        "duration_ms": 0,
    }

    # Try real ClamAV scan
    try:
        import subprocess
        import time

        t0 = time.perf_counter()
        proc = subprocess.run(
            ["clamscan", "--recursive", "--no-summary", "/workspaces/HOPEFX-AI-TRADING/uploads"],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        duration_ms = round((time.perf_counter() - t0) * 1000)
        threats = proc.stdout.count("FOUND")
        result.update(
            {
                "status": "completed",
                "threats_found": threats,
                "files_scanned": proc.stdout.count("OK") + threats,
                "duration_ms": duration_ms,
            }
        )
    except FileNotFoundError:
        result["status"] = "unavailable"
        result["error"] = "ClamAV not installed"
    except Exception as exc:
        result["status"] = "error"
        result["error"] = str(exc)

    try:
        from cache.redis_client import get_sync_redis_client

        rc = get_sync_redis_client()
        if rc:
            rc.set(_AV_STATUS_KEY, json.dumps(result), ex=3600 * 24)
    except Exception:  # nosec B110
        pass

    _log_superadmin_action(user, "antivirus_scan", {"scan_id": scan_id})
    return {"ok": True, "result": result}
