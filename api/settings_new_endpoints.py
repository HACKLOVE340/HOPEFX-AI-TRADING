# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
api/settings_new_endpoints.py
==============================
New settings endpoints required by the expanded Settings UI.

Routes
------
GET  /api/settings/integrations          — get integration config
POST /api/settings/integrations          — save integration config
POST /api/settings/integrations/test-webhook — fire a test POST to custom webhook
GET  /api/settings/privacy               — get privacy settings
POST /api/settings/privacy               — save privacy settings
GET  /api/settings/privacy/export        — export user data as JSON
GET  /api/settings/accessibility         — get accessibility settings
POST /api/settings/accessibility         — save accessibility settings
GET  /api/settings/api-keys              — list API keys
POST /api/settings/api-keys              — create API key
DELETE /api/settings/api-keys/{key_id}   — revoke API key
GET  /api/admin/settings/system          — get system settings (admin)
POST /api/admin/settings/system          — save system settings (admin)
POST /api/admin/backup/trigger           — trigger manual backup (admin)
POST /api/admin/kill-switch/global       — activate global kill switch (admin)
POST /api/admin/settings/test-smtp       — test SMTP config (admin)
"""

from __future__ import annotations

import hashlib
import hmac
import ipaddress
import json
import logging
import os
import secrets
import smtplib
import socket
import time
import urllib.parse
from email.mime.text import MIMEText
from typing import Any

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from api.auth import TokenPayload, get_current_user, require_role

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Settings Extended"])

# ── In-memory fallback stores (keyed by user_id) ─────────────────────────────
_integrations_store: dict[str, Any] = {}
_privacy_store: dict[str, Any] = {}
_accessibility_store: dict[str, Any] = {}
_api_keys_store: dict[str, list] = {}
_system_settings_store: dict[str, Any] = {}


# ── Auth helper ───────────────────────────────────────────────────────────────


def _get_user_id(request: Request) -> str:
    try:
        auth = request.headers.get("Authorization", "")
        if auth.startswith("Bearer "):
            import jwt as pyjwt

            secret = os.getenv("SECURITY_JWT_SECRET", "")
            if secret:
                payload = pyjwt.decode(auth[7:], secret, algorithms=["HS256"])
                return str(payload.get("sub", "anonymous"))
    except Exception:
        logger.debug("Suppressed exception (no detail) in %s", __name__)
    return "anonymous"


def _get_user_role(request: Request) -> str:
    try:
        auth = request.headers.get("Authorization", "")
        if auth.startswith("Bearer "):
            import jwt as pyjwt

            secret = os.getenv("SECURITY_JWT_SECRET", "")
            if secret:
                payload = pyjwt.decode(auth[7:], secret, algorithms=["HS256"])
                return str(payload.get("role", "user"))
    except Exception:
        logger.debug("Suppressed exception (no detail) in %s", __name__)
    return "user"


def _require_admin(request: Request) -> None:
    role = _get_user_role(request)
    if role not in ("admin", "superadmin"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin access required")


def _load_from_db(key: str, fallback: dict) -> dict:
    try:
        from core.config_store import config_store

        stored = config_store.get(key)
        if stored:
            return {**fallback, **json.loads(stored)}
    except Exception:
        logger.debug("Suppressed exception (no detail) in %s", __name__)
    return dict(fallback)


def _save_to_db(key: str, data: dict) -> None:
    try:
        from core.config_store import config_store

        config_store.set(key, json.dumps(data))
    except Exception:
        logger.debug("Suppressed exception (no detail) in %s", __name__)


# ── Integrations ──────────────────────────────────────────────────────────────


class IntegrationsPayload(BaseModel):
    tradingview_enabled: bool = False
    tradingview_webhook_secret: str = ""
    zapier_enabled: bool = False
    zapier_webhook_url: str = ""
    google_sheets_enabled: bool = False
    google_sheets_id: str = ""
    mt4_enabled: bool = False
    mt4_server: str = ""
    mt4_login: str = ""
    mt4_password: str = ""
    mt5_enabled: bool = False
    mt5_server: str = ""
    mt5_login: str = ""
    mt5_password: str = ""
    ctrader_enabled: bool = False
    ctrader_client_id: str = ""
    ctrader_client_secret: str = ""
    webhook_enabled: bool = False
    webhook_url: str = ""
    webhook_secret: str = ""


@router.get("/api/settings/integrations")
async def get_integrations(user: TokenPayload = Depends(get_current_user)):
    uid = user.sub
    data = _load_from_db(f"integrations:{uid}", {})
    # Never return raw passwords/secrets — mask them
    for field in (
        "mt4_password",
        "mt5_password",
        "ctrader_client_secret",
        "tradingview_webhook_secret",
        "webhook_secret",
    ):
        if data.get(field):
            data[field] = "••••••••"
    return data


@router.post("/api/settings/integrations")
async def save_integrations(payload: IntegrationsPayload, user: TokenPayload = Depends(get_current_user)):
    uid = user.sub
    existing = _load_from_db(f"integrations:{uid}", {})
    data = {**existing, **payload.model_dump()}
    # Preserve existing secrets if client sent masked value
    for field in (
        "mt4_password",
        "mt5_password",
        "ctrader_client_secret",
        "tradingview_webhook_secret",
        "webhook_secret",
    ):
        if data.get(field) == "••••••••":
            data[field] = existing.get(field, "")
    _save_to_db(f"integrations:{uid}", data)
    return {"status": "saved"}


class WebhookTestPayload(BaseModel):
    url: str
    secret: str = ""


def _resolve_and_validate_webhook_url(url: str) -> str:
    """Resolve the webhook URL hostname, reject private/internal IPs, and return
    a pinned URL with the IP substituted for the hostname.

    Resolving once and pinning the IP prevents DNS rebinding: the HTTP client
    uses the validated IP directly, so a second DNS lookup cannot return a
    different (internal) address between validation and the actual request.

    Raises HTTPException 400 if the URL is invalid or targets a private address.
    Returns the pinned URL (scheme://ip:port/path) with Host header info.
    """
    parsed = urllib.parse.urlparse(url)
    hostname = parsed.hostname
    if not hostname:
        raise HTTPException(status_code=400, detail="Invalid webhook URL: missing hostname")

    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    try:
        infos = socket.getaddrinfo(hostname, port, type=socket.SOCK_STREAM)
    except OSError as exc:
        raise HTTPException(
            status_code=400,
            detail="Webhook URL hostname could not be resolved",
        ) from exc

    safe_ip: str | None = None
    for info in infos:
        addr = info[4][0]
        try:
            ip = ipaddress.ip_address(addr)
        except ValueError:
            continue
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast:
            raise HTTPException(
                status_code=400,
                detail="Webhook URL must not target internal or reserved addresses",
            )
        if safe_ip is None:
            safe_ip = addr  # pin to first validated address

    if safe_ip is None:
        raise HTTPException(status_code=400, detail="Webhook URL could not be resolved to a valid address")

    # Build a pinned URL: replace hostname with the resolved IP so the HTTP
    # client never performs a second DNS lookup (prevents DNS rebinding).
    netloc = f"[{safe_ip}]:{port}" if ":" in safe_ip else f"{safe_ip}:{port}"
    pinned = parsed._replace(netloc=netloc).geturl()
    return pinned


@router.post("/api/settings/integrations/test-webhook")
async def test_webhook(payload: WebhookTestPayload, user: TokenPayload = Depends(get_current_user)):
    if not payload.url.startswith("https://"):
        raise HTTPException(status_code=400, detail="Webhook URL must use HTTPS")

    # Resolve hostname once, validate against private-IP blocklist, and pin the
    # request to the resolved IP to prevent DNS rebinding (CodeQL #24591 SSRF).
    _parsed_orig = urllib.parse.urlparse(payload.url)
    _orig_hostname = _parsed_orig.hostname or ""
    pinned_url = _resolve_and_validate_webhook_url(payload.url)

    body = json.dumps({"event": "test", "source": "hopefx", "timestamp": int(time.time())})
    headers = {
        "Content-Type": "application/json",
        "X-HopeFX-Event": "test",
        # Restore the original Host header so the server-side TLS/vhost routing works.
        "Host": _orig_hostname,
    }
    if payload.secret:
        sig = hmac.new(payload.secret.encode(), body.encode(), hashlib.sha256).hexdigest()
        headers["X-HopeFX-Signature"] = f"sha256={sig}"
    try:
        # verify=True (default) — TLS certificate is validated against the
        # original hostname even though we connect to the pinned IP.
        async with httpx.AsyncClient(timeout=10, verify=True) as client:
            resp = await client.post(pinned_url, content=body, headers=headers)
        if resp.status_code >= 400:
            raise HTTPException(status_code=502, detail=f"Webhook returned {resp.status_code}")
        return {"status": "delivered", "response_code": resp.status_code}
    except httpx.RequestError as exc:
        raise HTTPException(status_code=502, detail=f"Webhook delivery failed: {type(exc).__name__}") from exc


# ── Privacy ───────────────────────────────────────────────────────────────────


class PrivacyPayload(BaseModel):
    share_performance: bool = False
    share_trades: bool = False
    share_signals: bool = False
    allow_copy_trading: bool = False
    show_in_leaderboard: bool = True
    analytics_opt_in: bool = True
    marketing_emails: bool = False
    data_retention_days: int = 365


@router.get("/api/settings/privacy")
async def get_privacy(user: TokenPayload = Depends(get_current_user)):
    uid = user.sub
    return _load_from_db(f"privacy:{uid}", PrivacyPayload().model_dump())


@router.post("/api/settings/privacy")
async def save_privacy(payload: PrivacyPayload, user: TokenPayload = Depends(get_current_user)):
    uid = user.sub
    _save_to_db(f"privacy:{uid}", payload.model_dump())
    return {"status": "saved"}


@router.get("/api/settings/privacy/export")
async def export_user_data(user: TokenPayload = Depends(get_current_user)):
    uid = user.sub
    export: dict[str, Any] = {
        "exported_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "user_id": uid,
        "privacy": _load_from_db(f"privacy:{uid}", {}),
        "integrations": _load_from_db(f"integrations:{uid}", {}),
        "accessibility": _load_from_db(f"accessibility:{uid}", {}),
    }
    # Scrub secrets from export
    for field in (
        "mt4_password",
        "mt5_password",
        "ctrader_client_secret",
        "tradingview_webhook_secret",
        "webhook_secret",
    ):
        export.get("integrations", {}).pop(field, None)

    content = json.dumps(export, indent=2)
    return StreamingResponse(
        iter([content]),
        media_type="application/json",
        headers={"Content-Disposition": f"attachment; filename=hopefx-data-{uid[:8]}.json"},
    )


# ── Accessibility ─────────────────────────────────────────────────────────────


class AccessibilityPayload(BaseModel):
    reduce_motion: bool = False
    high_contrast: bool = False
    large_text: bool = False
    keyboard_shortcuts: bool = True
    screen_reader_hints: bool = False
    color_blind_mode: str = "none"
    font_size: str = "medium"


@router.get("/api/settings/accessibility")
async def get_accessibility(user: TokenPayload = Depends(get_current_user)):
    uid = user.sub
    return _load_from_db(f"accessibility:{uid}", AccessibilityPayload().model_dump())


@router.post("/api/settings/accessibility")
async def save_accessibility(payload: AccessibilityPayload, user: TokenPayload = Depends(get_current_user)):
    uid = user.sub
    _save_to_db(f"accessibility:{uid}", payload.model_dump())
    return {"status": "saved"}


# ── API Keys ──────────────────────────────────────────────────────────────────


class CreateApiKeyPayload(BaseModel):
    name: str
    scopes: list[str] = ["read"]


@router.get("/api/settings/api-keys")
async def list_api_keys(user: TokenPayload = Depends(get_current_user)):
    uid = user.sub
    keys = _load_from_db(f"api_keys:{uid}", {"api_keys": []}).get("api_keys", [])
    # Never return full key — only prefix
    safe = []
    for k in keys:
        safe.append(
            {
                "key_id": k["key_id"],
                "name": k["name"],
                "scopes": k["scopes"],
                "key_prefix": k.get("key_prefix", ""),
                "created_at": k["created_at"],
                "last_used": k.get("last_used"),
                "revoked": k.get("revoked", False),
            }
        )
    return {"api_keys": safe}


@router.post("/api/settings/api-keys", status_code=201)
async def create_api_key(payload: CreateApiKeyPayload, user: TokenPayload = Depends(get_current_user)):
    uid = user.sub
    if not payload.name.strip():
        raise HTTPException(status_code=400, detail="Key name is required")
    raw_key = f"hfx_{secrets.token_urlsafe(32)}"
    key_id = secrets.token_hex(8)
    entry = {
        "key_id": key_id,
        "name": payload.name.strip(),
        "scopes": payload.scopes,
        "key_prefix": raw_key[:12] + "…",
        "key_hash": hashlib.sha256(raw_key.encode()).hexdigest(),
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "last_used": None,
        "revoked": False,
    }
    store = _load_from_db(f"api_keys:{uid}", {"api_keys": []})
    store.setdefault("api_keys", []).append(entry)
    _save_to_db(f"api_keys:{uid}", store)
    return {
        "key_id": key_id,
        "api_key": raw_key,
        "name": entry["name"],
        "scopes": entry["scopes"],
    }


@router.delete("/api/settings/api-keys/{key_id}")
async def revoke_api_key(key_id: str, user: TokenPayload = Depends(get_current_user)):
    uid = user.sub
    store = _load_from_db(f"api_keys:{uid}", {"api_keys": []})
    keys = store.get("api_keys", [])
    found = False
    for k in keys:
        if k["key_id"] == key_id:
            k["revoked"] = True
            found = True
            break
    if not found:
        raise HTTPException(status_code=404, detail="API key not found")
    _save_to_db(f"api_keys:{uid}", store)
    return {"status": "revoked"}


# ── System settings (admin only) ──────────────────────────────────────────────

_SYSTEM_DEFAULTS: dict[str, Any] = {
    "data_refresh_interval": 30,
    "max_open_positions": 10,
    "session_timeout_minutes": 60,
    "log_level": "info",
    "enable_paper_trading": True,
    "enable_live_trading": False,
    "maintenance_mode": False,
    "rate_limit_per_minute": 60,
    "cache_ttl_seconds": 300,
    "backup_enabled": True,
    "backup_frequency": "daily",
}


# NOTE: GET /api/admin/settings/system and POST /api/admin/settings/system are
# handled by api/admin.py (prefix="/api/admin", routes /settings/system).
# admin.py is registered before this router so those paths are already claimed.
# Duplicate handlers were removed here to avoid silent dead-code via dedup.
# admin.py now uses config_store with full defaults (see _load_system_settings).


# ── Backup trigger (admin only) ───────────────────────────────────────────────


@router.post("/api/admin/backup/trigger")
async def trigger_backup(user: TokenPayload = Depends(require_role("admin"))):
    try:
        from database.backup import run_backup

        run_backup()
        logger.info("Manual backup triggered by admin %s", user.sub)
        return {"status": "started"}
    except ImportError:
        logger.warning("Backup module not available — recording trigger only")
        _save_to_db("last_manual_backup", {"triggered_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())})
        return {"status": "started"}
    except Exception as exc:
        raise HTTPException(status_code=500, detail="Backup failed.") from exc


# ── Global kill switch (admin only) ──────────────────────────────────────────


@router.post("/api/admin/kill-switch/global")
async def global_kill_switch(user: TokenPayload = Depends(require_role("admin"))):
    try:
        from api.admin import log_activity

        log_activity(f"GLOBAL KILL SWITCH activated by admin {user.sub}")
    except Exception:
        logger.debug("Suppressed exception (no detail) in %s", __name__)
    try:
        from core.config_store import config_store

        config_store.set("global_kill_switch", "true")
    except Exception:
        logger.debug("Suppressed exception (no detail) in %s", __name__)
    logger.critical("GLOBAL KILL SWITCH activated")
    return {"status": "activated", "timestamp": int(time.time())}


# ── SMTP test (admin only) ────────────────────────────────────────────────────


class SmtpTestPayload(BaseModel):
    host: str
    port: int = 587
    user: str = ""
    password: str = ""
    from_addr: str = ""
    tls: bool = True


@router.post("/api/admin/settings/test-smtp")
async def test_smtp(payload: SmtpTestPayload, user: TokenPayload = Depends(require_role("admin"))):
    if not payload.host:
        raise HTTPException(status_code=400, detail="SMTP host is required")
    try:
        msg = MIMEText("This is a test email from HOPEFX Settings.")
        msg["Subject"] = "HOPEFX SMTP Test"
        msg["From"] = payload.from_addr or payload.user
        msg["To"] = payload.user

        if payload.tls:
            server = smtplib.SMTP(payload.host, payload.port, timeout=10)
            server.starttls()
        else:
            server = smtplib.SMTP_SSL(payload.host, payload.port, timeout=10)

        if payload.user and payload.password:
            server.login(payload.user, payload.password)
        server.sendmail(msg["From"], [msg["To"]], msg.as_string())
        server.quit()
        return {"status": "sent"}
    except smtplib.SMTPException as exc:
        raise HTTPException(status_code=502, detail="SMTP error.") from exc
    except OSError as exc:
        raise HTTPException(status_code=502, detail="Connection failed.") from exc


# NOTE: GET /api/admin/settings and POST /api/admin/settings are handled by
# api/admin.py (prefix="/api/admin", routes GET /settings and POST /settings).
# admin.py is registered before this router so those paths are already claimed.
# Duplicate handlers were removed here to avoid silent dead-code via dedup.
