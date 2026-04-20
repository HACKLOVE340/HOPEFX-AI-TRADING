# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
api/settings_extended.py
========================
Extended user settings endpoints — appearance, trading preferences,
broker config, user preferences (timezone/language), password change,
and account deletion.

All sections use the same DB persistence pattern as api/settings.py:
  - Primary store: `configurations` table keyed by `{section}:{user_id}`
  - Fallback: in-memory dict when DB is unavailable

Routes
------
GET  /api/settings/preferences      — timezone, language
POST /api/settings/preferences      — save timezone, language
GET  /api/settings/appearance       — theme, accent, chart style, display
POST /api/settings/appearance       — save appearance
GET  /api/settings/trading          — symbol, timeframe, risk limits, automation
POST /api/settings/trading          — save trading preferences
POST /api/settings/broker           — save broker connection (type, api_key, account_id)
POST /api/auth/change-password      — change authenticated user password
DELETE /api/auth/account            — permanently delete account
"""

from __future__ import annotations

import json
import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel

from api.auth import TokenPayload, get_current_user

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Settings"])

# In-memory fallback keyed as "{section}:{user_id}"
_store: dict[str, Any] = {}


# ── Shared helpers ────────────────────────────────────────────────────────────


def _get_user_id(request: Request) -> str:
    """Extract user_id from JWT Bearer token; fall back to 'anonymous'."""
    try:
        import os

        auth = request.headers.get("Authorization", "")
        if auth.startswith("Bearer "):
            import jwt as pyjwt

            secret = os.getenv("SECURITY_JWT_SECRET", "")
            if secret:
                payload = pyjwt.decode(auth[7:], secret, algorithms=["HS256"])
                return str(payload.get("sub", "anonymous"))
    except Exception as exc:
        logger.debug("settings_extended JWT extraction failed: %s", exc)
    return "anonymous"


def _db_save(user_id: str, section: str, data: dict) -> bool:
    """Persist a settings section to the configurations table."""
    try:
        from database.connection import get_db_manager
        from database.models import Configuration

        mgr = get_db_manager()
        if not mgr:
            return False
        ctx = mgr.session()
        session = ctx.__enter__()
        if not session:
            return False

        key = f"{section}:{user_id}"
        value = json.dumps(data)
        existing = session.query(Configuration).filter_by(config_key=key).first()
        if existing:
            existing.config_value = value
            existing.changed_by = user_id
        else:
            from database.models import Configuration as Cfg

            record = Cfg(
                environment="production",
                config_key=key,
                config_value=value,
                changed_by=user_id,
                change_reason=f"user {section} update",
            )
            session.add(record)
        session.commit()
        return True
    except Exception as exc:
        logger.debug("DB save failed for %s/%s: %s", section, user_id, exc)
        return False


def _db_load(user_id: str, section: str) -> dict | None:
    """Load a settings section from the configurations table."""
    try:
        from database.connection import get_db_manager
        from database.models import Configuration

        mgr = get_db_manager()
        if not mgr:
            return None
        ctx = mgr.session()
        session = ctx.__enter__()
        if not session:
            return None

        key = f"{section}:{user_id}"
        record = session.query(Configuration).filter_by(config_key=key).first()
        if record and record.config_value:
            return json.loads(record.config_value)
    except Exception as exc:
        logger.debug("DB load failed for %s/%s: %s", section, user_id, exc)
    return None


def _save(user_id: str, section: str, data: dict) -> None:
    """Save to DB; fall back to in-memory store."""
    if not _db_save(user_id, section, data):
        _store[f"{section}:{user_id}"] = data


def _load(user_id: str, section: str, defaults: dict) -> dict:
    """Load from DB → in-memory → defaults."""
    data = _db_load(user_id, section) or _store.get(f"{section}:{user_id}")
    return {**defaults, **(data or {})}


# ── Preferences (timezone / language) ────────────────────────────────────────


class PreferencesBody(BaseModel):
    timezone: str = "UTC"
    language: str = "en"


@router.get("/api/settings/preferences", summary="Get user preferences")
async def get_preferences(user: TokenPayload = Depends(get_current_user)):
    """Return timezone and language preferences for the authenticated user."""
    uid = user.sub
    return _load(uid, "preferences", PreferencesBody().model_dump())


@router.post("/api/settings/preferences", summary="Save user preferences")
async def save_preferences(body: PreferencesBody, user: TokenPayload = Depends(get_current_user)):
    """Persist timezone and language preferences."""
    uid = user.sub
    _save(uid, "preferences", body.model_dump())
    return {"status": "saved"}


# ── Appearance ────────────────────────────────────────────────────────────────


class AppearanceBody(BaseModel):
    theme: str = "dark"
    accent_color: str = "#3b82f6"
    chart_style: str = "candles"
    compact_sidebar: bool = False
    show_pnl_in_header: bool = True
    number_format: str = "standard"
    currency_display: str = "USD"


@router.get("/api/settings/appearance", summary="Get appearance settings")
async def get_appearance(user: TokenPayload = Depends(get_current_user)):
    """Return appearance/theme settings for the authenticated user."""
    uid = user.sub
    return _load(uid, "appearance", AppearanceBody().model_dump())


@router.post("/api/settings/appearance", summary="Save appearance settings")
async def save_appearance(body: AppearanceBody, user: TokenPayload = Depends(get_current_user)):
    """Persist appearance/theme settings."""
    uid = user.sub
    _save(uid, "appearance", body.model_dump())
    return {"status": "saved"}


# ── Trading preferences ───────────────────────────────────────────────────────


class TradingPrefsBody(BaseModel):
    default_symbol: str = "XAU_USD"
    default_timeframe: str = "1h"
    default_lot_size: float = 0.01
    max_risk_per_trade: float = 1.0
    max_daily_drawdown: float = 5.0
    auto_trade_enabled: bool = False
    kill_switch_enabled: bool = False
    slippage_tolerance: int = 3
    default_leverage: int = 50


@router.get("/api/settings/trading", summary="Get trading preferences")
async def get_trading_prefs(user: TokenPayload = Depends(get_current_user)):
    """Return trading preferences for the authenticated user."""
    uid = user.sub
    return _load(uid, "trading", TradingPrefsBody().model_dump())


@router.post("/api/settings/trading", summary="Save trading preferences")
async def save_trading_prefs(body: TradingPrefsBody, user: TokenPayload = Depends(get_current_user)):
    """Persist trading preferences and sync kill switch with the risk engine."""
    uid = user.sub
    _save(uid, "trading", body.model_dump())

    if body.kill_switch_enabled:
        try:
            # Activate the app-level kill switch singleton directly so the halt
            # reaches the running risk manager and all subsystems.  Creating a
            # new RiskManager() instance would apply the halt to a throwaway
            # object that has no effect on the live trading engine.
            import sys as _sys

            _app = _sys.modules.get("app")
            _ks = getattr(_app, "kill_switch", None)
            if _ks is not None and callable(getattr(_ks, "activate", None)):
                if not _ks.is_active():
                    _ks.activate(reason="user settings")
                    logger.warning("Kill switch activated via user settings for user %s", uid)
            else:
                # Fallback: reach the live risk manager via app_state
                from core.app_state import app_state as _state

                _rm = getattr(_state, "risk_manager", None)
                if _rm is not None and callable(getattr(_rm, "_halt_trading", None)):
                    _rm._halt_trading("user settings")
                    logger.warning("RiskManager halted via user settings for user %s", uid)
        except Exception as exc:
            logger.debug("Kill switch propagation failed: %s", exc)

    elif not body.kill_switch_enabled:
        # User explicitly disabled the kill switch — resume trading if halted.
        try:
            import sys as _sys

            _app = _sys.modules.get("app")
            _ks = getattr(_app, "kill_switch", None)
            if _ks is not None and _ks.is_active():
                _ks.deactivate()
                logger.info("Kill switch deactivated via user settings for user %s", uid)
            # Also resume the live risk manager if it was halted.
            from core.app_state import app_state as _state

            _rm = getattr(_state, "risk_manager", None)
            if _rm is not None and callable(getattr(_rm, "resume_trading", None)):
                _rm.resume_trading()
        except Exception as exc:
            logger.debug("Kill switch deactivation failed: %s", exc)

    return {"status": "saved"}


# ── Broker settings ───────────────────────────────────────────────────────────


class BrokerSettingsBody(BaseModel):
    type: str = "paper"
    api_key: str = ""
    account_id: str = ""
    practice: bool = True


@router.post("/api/settings/broker", summary="Save broker connection settings")
async def save_broker_settings(body: BrokerSettingsBody, user: TokenPayload = Depends(get_current_user)):
    """Persist broker connection settings. API key is stored server-side only."""
    uid = user.sub
    _save(uid, "broker", body.model_dump())
    logger.info("Broker settings saved for user %s (type=%s)", uid, body.type)
    return {"status": "saved", "broker": body.type}


# ── Password change ───────────────────────────────────────────────────────────


class ChangePasswordBody(BaseModel):
    current_password: str
    new_password: str


@router.post("/api/auth/change-password", summary="Change authenticated user password")
async def change_password(body: ChangePasswordBody, user: TokenPayload = Depends(get_current_user)):
    """Change the password for the currently authenticated user."""
    uid = user.sub

    if len(body.new_password) < 8:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="New password must be at least 8 characters",
        )

    try:
        import bcrypt

        from database.connection import get_db_manager
        from database.models import User

        mgr = get_db_manager()
        if not mgr:
            raise HTTPException(status_code=503, detail="Database unavailable")

        ctx = mgr.session()
        session = ctx.__enter__()
        user = session.query(User).filter_by(id=uid).first()
        if not user:
            raise HTTPException(status_code=404, detail="User not found")

        if not bcrypt.checkpw(body.current_password.encode(), user.password_hash.encode()):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Current password is incorrect",
            )

        user.password_hash = bcrypt.hashpw(body.new_password.encode(), bcrypt.gensalt()).decode()
        session.commit()
        logger.info("Password changed for user %s", uid)
        return {"status": "updated"}

    except HTTPException:
        raise
    except Exception as exc:
        logger.warning("Password change failed for user %s: %s", uid, exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Password change failed. Please try again.",
        ) from exc


# ── Account deletion ──────────────────────────────────────────────────────────


@router.delete("/api/auth/account", summary="Delete authenticated user account")
async def delete_account(user: TokenPayload = Depends(get_current_user)):
    """Permanently delete the authenticated user's account and all associated data."""
    uid = user.sub

    try:
        from database.connection import get_db_manager
        from database.models import User

        mgr = get_db_manager()
        if not mgr:
            raise HTTPException(status_code=503, detail="Database unavailable")

        ctx = mgr.session()
        session = ctx.__enter__()
        user = session.query(User).filter_by(id=uid).first()
        if not user:
            raise HTTPException(status_code=404, detail="User not found")

        session.delete(user)
        session.commit()
        logger.info("Account deleted for user %s", uid)
        return {"status": "deleted"}

    except HTTPException:
        raise
    except Exception as exc:
        logger.warning("Account deletion failed for user %s: %s", uid, exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Account deletion failed. Contact support.",
        ) from exc
