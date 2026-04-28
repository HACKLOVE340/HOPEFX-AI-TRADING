# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# AGPL-3.0 — Share all modifications
"""
api/superadmin/alerting.py
===========================
Alerting management sub-router: alert rules, Prometheus integration,
silence windows, and alert history.

Routes
------
GET   /superadmin/alerting/rules                         — list alert rules
POST  /superadmin/alerting/rules                         — create rule
PATCH /superadmin/alerting/rules/{rule_id}               — update rule
DELETE /superadmin/alerting/rules/{rule_id}              — delete rule
POST  /superadmin/alerting/rules/{rule_id}/silence       — silence rule
POST  /superadmin/alerting/rules/{rule_id}/test          — test-fire rule
GET   /superadmin/alerting/history                       — alert fire history
GET   /superadmin/alerting/channels                      — notification channels
"""

from __future__ import annotations

import json
import logging
import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from api.auth import TokenPayload
from ._shared import _require_superadmin, _utcnow, _log_superadmin_action

logger = logging.getLogger(__name__)
router = APIRouter()

_RULES_KEY   = "superadmin:alerting:rules"
_HISTORY_KEY = "superadmin:alerting:history"


def _load_alert_rules() -> list[dict]:
    try:
        from cache.redis_client import get_sync_redis_client
        rc = get_sync_redis_client()
        if rc:
            raw = rc.get(_RULES_KEY)
            if raw:
                return json.loads(raw)
    except Exception:
        pass
    # Bootstrap with sensible defaults
    return [
        {
            "rule_id": "ar_kill_switch",
            "name": "Kill Switch Activated",
            "condition": "kill_switch.active == true",
            "severity": "critical",
            "enabled": True,
            "channels": ["telegram", "email"],
            "last_fired": None,
            "fire_count": 0,
            "created_at": _utcnow().isoformat(),
        },
        {
            "rule_id": "ar_drawdown_10",
            "name": "Portfolio Drawdown > 10%",
            "condition": "drawdown_pct > 0.10",
            "severity": "critical",
            "enabled": True,
            "channels": ["telegram", "email"],
            "last_fired": None,
            "fire_count": 0,
            "created_at": _utcnow().isoformat(),
        },
        {
            "rule_id": "ar_error_rate",
            "name": "API Error Rate > 5%",
            "condition": "error_rate_pct > 5",
            "severity": "warning",
            "enabled": True,
            "channels": ["email"],
            "last_fired": None,
            "fire_count": 0,
            "created_at": _utcnow().isoformat(),
        },
        {
            "rule_id": "ar_redis_down",
            "name": "Redis Unavailable",
            "condition": "redis.status != ok",
            "severity": "critical",
            "enabled": True,
            "channels": ["telegram", "email", "pagerduty"],
            "last_fired": None,
            "fire_count": 0,
            "created_at": _utcnow().isoformat(),
        },
        {
            "rule_id": "ar_ml_drift",
            "name": "ML Model Drift > 0.3",
            "condition": "ml.drift_score > 0.3",
            "severity": "warning",
            "enabled": True,
            "channels": ["email"],
            "last_fired": None,
            "fire_count": 0,
            "created_at": _utcnow().isoformat(),
        },
    ]


def _save_alert_rules(rules: list[dict]) -> None:
    try:
        from cache.redis_client import get_sync_redis_client
        rc = get_sync_redis_client()
        if rc:
            rc.set(_RULES_KEY, json.dumps(rules), ex=86400 * 90)
    except Exception:
        pass


def _append_alert_history(rule_id: str, rule_name: str, severity: str, detail: str) -> None:
    try:
        from cache.redis_client import get_sync_redis_client
        rc = get_sync_redis_client()
        if rc:
            raw = rc.get(_HISTORY_KEY)
            history = json.loads(raw) if raw else []
            history.insert(0, {
                "event_id": str(uuid.uuid4()),
                "rule_id": rule_id,
                "rule_name": rule_name,
                "severity": severity,
                "detail": detail,
                "fired_at": _utcnow().isoformat(),
            })
            rc.set(_HISTORY_KEY, json.dumps(history[:500]), ex=86400 * 30)
    except Exception:
        pass


@router.get("/alerting/rules")
async def get_alert_rules(
    user: TokenPayload = Depends(_require_superadmin),
) -> dict:
    rules = _load_alert_rules()
    return {"rules": rules, "total": len(rules)}


@router.post("/alerting/rules")
async def create_alert_rule(
    body: dict,
    user: TokenPayload = Depends(_require_superadmin),
) -> dict:
    rule_id = f"ar_{uuid.uuid4().hex[:8]}"
    rule: dict[str, Any] = {
        "rule_id": rule_id,
        "name": body.get("name", "New Alert"),
        "condition": body.get("condition", ""),
        "severity": body.get("severity", "warning"),
        "enabled": bool(body.get("enabled", True)),
        "channels": body.get("channels", ["email"]),
        "last_fired": None,
        "fire_count": 0,
        "created_at": _utcnow().isoformat(),
        "created_by": user.sub,
    }
    rules = _load_alert_rules()
    rules.append(rule)
    _save_alert_rules(rules)
    await _log_superadmin_action(user.sub, "alert_rule_create", {"rule_id": rule_id})
    return {"ok": True, "rule": rule}


@router.patch("/alerting/rules/{rule_id}")
async def update_alert_rule(
    rule_id: str,
    body: dict,
    user: TokenPayload = Depends(_require_superadmin),
) -> dict:
    rules = _load_alert_rules()
    for r in rules:
        if r["rule_id"] == rule_id:
            for k, v in body.items():
                if k not in ("rule_id", "created_at", "fire_count"):
                    r[k] = v
            r["updated_at"] = _utcnow().isoformat()
            _save_alert_rules(rules)
            await _log_superadmin_action(user.sub, "alert_rule_update", {"rule_id": rule_id})
            return {"ok": True, "rule": r}
    raise HTTPException(status_code=404, detail="Alert rule not found")


@router.delete("/alerting/rules/{rule_id}")
async def delete_alert_rule(
    rule_id: str,
    user: TokenPayload = Depends(_require_superadmin),
) -> dict:
    rules = _load_alert_rules()
    before = len(rules)
    rules = [r for r in rules if r["rule_id"] != rule_id]
    if len(rules) == before:
        raise HTTPException(status_code=404, detail="Alert rule not found")
    _save_alert_rules(rules)
    await _log_superadmin_action(user.sub, "alert_rule_delete", {"rule_id": rule_id})
    return {"ok": True}


@router.post("/alerting/rules/{rule_id}/silence")
async def silence_alert_rule(
    rule_id: str,
    body: dict,
    user: TokenPayload = Depends(_require_superadmin),
) -> dict:
    duration_minutes = int(body.get("duration_minutes", 60))
    rules = _load_alert_rules()
    for r in rules:
        if r["rule_id"] == rule_id:
            from datetime import timedelta
            r["silenced_until"] = (_utcnow() + timedelta(minutes=duration_minutes)).isoformat()
            r["silenced_by"] = user.sub
            _save_alert_rules(rules)
            await _log_superadmin_action(user.sub, "alert_rule_silence", {"rule_id": rule_id, "minutes": duration_minutes})
            return {"ok": True, "silenced_until": r["silenced_until"]}
    raise HTTPException(status_code=404, detail="Alert rule not found")


@router.post("/alerting/rules/{rule_id}/test")
async def test_alert_rule(
    rule_id: str,
    user: TokenPayload = Depends(_require_superadmin),
) -> dict:
    rules = _load_alert_rules()
    rule = next((r for r in rules if r["rule_id"] == rule_id), None)
    if not rule:
        raise HTTPException(status_code=404, detail="Alert rule not found")

    # Fire test notification
    sent_channels: list[str] = []
    try:
        from notifications import get_alert_engine
        engine = get_alert_engine()
        if engine:
            await engine.send_alert(
                rule["severity"],
                f"[TEST] {rule['name']}: {rule['condition']}",
            )
            sent_channels = rule.get("channels", [])
    except Exception as exc:
        logger.warning("Test alert send: %s", exc)

    # Update fire count
    rule["fire_count"] = rule.get("fire_count", 0) + 1
    rule["last_fired"] = _utcnow().isoformat()
    _save_alert_rules(rules)
    _append_alert_history(rule_id, rule["name"], rule["severity"], "Test fire by superadmin")
    await _log_superadmin_action(user.sub, "alert_rule_test", {"rule_id": rule_id})
    return {"ok": True, "sent_channels": sent_channels}


@router.get("/alerting/history")
async def get_alert_history(
    user: TokenPayload = Depends(_require_superadmin),
) -> dict:
    history: list[dict] = []
    try:
        from cache.redis_client import get_sync_redis_client
        rc = get_sync_redis_client()
        if rc:
            raw = rc.get(_HISTORY_KEY)
            if raw:
                history = json.loads(raw)
    except Exception:
        pass
    return {"history": history, "total": len(history)}


@router.get("/alerting/channels")
async def get_alert_channels(
    user: TokenPayload = Depends(_require_superadmin),
) -> dict:
    import os
    channels = [
        {
            "channel_id": "email",
            "name": "Email",
            "type": "email",
            "enabled": bool(os.getenv("SMTP_HOST")),
            "config": {"host": os.getenv("SMTP_HOST", ""), "port": os.getenv("SMTP_PORT", "587")},
        },
        {
            "channel_id": "telegram",
            "name": "Telegram",
            "type": "telegram",
            "enabled": bool(os.getenv("TELEGRAM_BOT_TOKEN")),
            "config": {"chat_id": os.getenv("TELEGRAM_CHAT_ID", "")},
        },
        {
            "channel_id": "pagerduty",
            "name": "PagerDuty",
            "type": "pagerduty",
            "enabled": bool(os.getenv("PAGERDUTY_KEY")),
            "config": {},
        },
        {
            "channel_id": "slack",
            "name": "Slack",
            "type": "slack",
            "enabled": bool(os.getenv("SLACK_WEBHOOK_URL")),
            "config": {},
        },
    ]
    return {"channels": channels}
