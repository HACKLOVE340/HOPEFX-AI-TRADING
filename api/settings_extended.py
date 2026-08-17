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
        with mgr.session() as session:
            key = f"{section}:{user_id}"
            value = json.dumps(data)
            existing = session.query(Configuration).filter_by(config_key=key).first()
            if existing:
                existing.config_value = value
                existing.changed_by = user_id
            else:
                record = Configuration(
                    environment="production",
                    config_key=key,
                    config_value=value,
                    changed_by=user_id,
                    change_reason=f"user {section} update",
                )
                session.add(record)
            try:
                session.commit()
            except Exception:
                session.rollback()
                raise
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
        with mgr.session() as session:
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


def _kill_switch_active() -> bool:
    """Report whether the app-level kill switch is currently engaged.

    Read-only. Returns False when no kill switch is wired up, which matches the
    behaviour of every other read path.
    """
    try:
        import sys as _sys

        _ks = getattr(_sys.modules.get("app"), "kill_switch", None)
        if _ks is not None and callable(getattr(_ks, "is_active", None)):
            return bool(_ks.is_active())
    except Exception as exc:  # pragma: no cover — defensive
        logger.debug("kill switch status unavailable: %s", exc)
    return False


@router.get("/api/settings/trading", summary="Get trading preferences")
async def get_trading_prefs(user: TokenPayload = Depends(get_current_user)):
    """Return trading preferences for the authenticated user.

    `kill_switch_enabled` reflects the LIVE kill switch, not a stored preference.
    It used to be read back from whatever was last saved, so the settings page
    could report trading as halted when it was running, or running when it was
    halted.
    """
    uid = user.sub
    prefs = _load(uid, "trading", TradingPrefsBody().model_dump())
    prefs["kill_switch_enabled"] = _kill_switch_active()
    return prefs


@router.post("/api/settings/trading", summary="Save trading preferences")
async def save_trading_prefs(body: TradingPrefsBody, user: TokenPayload = Depends(get_current_user)):
    """Persist trading preferences.

    This endpoint does NOT touch the kill switch, in either direction.

    It used to. `kill_switch_enabled` defaults to False on this model, so any
    save that omitted the field — a user changing their lot size — took the
    "user explicitly disabled the kill switch" branch and called
    `risk_manager.resume_trading()`, whose own docstring reads "requires explicit
    operator action". A halt raised by a drawdown circuit breaker could be
    cleared by any authenticated user, at any plan tier, saving an unrelated
    preference.

    It also attempted `kill_switch.deactivate()` with no token, bypassing both
    the admin role check on `POST /api/admin/resume` and the
    HOPEFX_KILL_SWITCH_TOKEN requirement that exists so trading cannot resume
    unattended. That call raised and was swallowed by a debug-level except, so
    the bypass left no trace.

    Halting and resuming live trading belong to the operator endpoints:
    `POST /api/trading/emergency-stop`, `POST /api/admin/pause`,
    `POST /api/admin/resume` and `/api/nuclear/kill_switch/*` — all admin-gated.
    """
    uid = user.sub

    # Never persist the kill switch as a user preference: it is global engine
    # state, and storing it invites the next reader to sync from it.
    prefs = body.model_dump()
    requested_halt = prefs.pop("kill_switch_enabled", False)
    _save(uid, "trading", prefs)

    if requested_halt and not _kill_switch_active():
        # Someone reached the halt through a door that no longer opens it. Say so
        # loudly rather than returning a bare success the caller reads as "halted".
        logger.warning(
            "settings/trading: user=%s sent kill_switch_enabled=true — ignored. "
            "Use POST /api/trading/emergency-stop (admin) to halt trading.",
            uid,
        )
        raise HTTPException(
            status_code=400,
            detail=(
                "Trading preferences cannot engage the kill switch. "
                "Use the emergency stop control — it requires an administrator."
            ),
        )

    return {"status": "saved", "kill_switch_enabled": _kill_switch_active()}


# ── Broker settings ───────────────────────────────────────────────────────────


class BrokerSettingsBody(BaseModel):
    type: str = "paper"
    api_key: str = ""
    account_id: str = ""
    practice: bool = True


@router.get("/api/settings/broker", summary="Get broker connection settings")
async def get_broker_settings(user: TokenPayload = Depends(get_current_user)):
    """Return saved broker settings so the UI can hydrate on revisit.

    The API key is NEVER returned raw — only a key-set flag and last-4 — so the
    secret is not exposed while non-secret fields (type/account_id/practice)
    survive a page reload (previously they silently reset to defaults).
    """
    uid = user.sub
    data = _load(uid, "broker", BrokerSettingsBody().model_dump())
    key = str(data.get("api_key") or "")
    return {
        "type": data.get("type", "paper"),
        "account_id": data.get("account_id", ""),
        "practice": bool(data.get("practice", True)),
        "api_key_set": bool(key),
        "api_key_last4": key[-4:] if len(key) >= 4 else "",
    }


@router.post("/api/settings/broker", summary="Save broker connection settings")
async def save_broker_settings(body: BrokerSettingsBody, user: TokenPayload = Depends(get_current_user)):
    """Persist broker connection settings. API key is stored server-side only."""
    uid = user.sub
    payload = body.model_dump()
    # The UI never prefills the secret API key (it shows a masked placeholder),
    # so a blank api_key on re-save means "keep the existing one" — don't wipe it.
    if not payload.get("api_key"):
        existing = _load(uid, "broker", {"api_key": ""})
        if existing.get("api_key"):
            payload["api_key"] = existing["api_key"]
    _save(uid, "broker", payload)
    logger.info("Broker settings saved for user %s (type=%s)", uid, body.type)
    return {"status": "saved", "broker": body.type}


# ── Password change ───────────────────────────────────────────────────────────


class ChangePasswordBody(BaseModel):
    current_password: str
    new_password: str


@router.post("/api/auth/change-password", summary="Change authenticated user password")
async def change_password(
    body: ChangePasswordBody,
    request: Request,
    user: TokenPayload = Depends(get_current_user),
):
    """Change the password for the currently authenticated user.

    This route was non-functional in three independent ways, each of which alone
    would have broken it (pre-launch finding Q-01):

    1. It read and wrote ``user.password_hash``. The column on
       ``database.user_models.User`` is ``hashed_password``; no ``password_hash``
       attribute exists, so line one of the check raised AttributeError, the
       broad ``except Exception`` below caught it, and every single request
       returned 500 "Password change failed. Please try again." Nobody could
       change their password, ever.

    2. It hashed with bare ``bcrypt.hashpw(password)``. Registration and login go
       through ``auth.jwt.hash_password`` / ``verify_password``, which BLAKE2b
       pre-hash the input before bcrypt to dodge bcrypt's 72-byte truncation. So
       even with the column name fixed, the ``checkpw`` would have rejected every
       correct current password, and any hash it did write would not verify at
       login — locking the user out of their own account. auth/service.py already
       carries a comment about this exact failure happening once before, when
       that module used pbkdf2_sha256 while auth.jwt used bcrypt.

    3. It did not revoke sessions. Changing a password is what a user does when
       they believe someone else has access; leaving existing sessions valid
       means the attacker keeps it. ``logout_all`` now runs after the change.

    Also fixed: ``mgr.session()`` was entered with ``ctx.__enter__()`` and never
    exited, leaking a DB session per call, and the route had no rate limit while
    accepting a password guess.
    """
    uid = user.sub

    if len(body.new_password) < 8:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="New password must be at least 8 characters",
        )

    # The current_password field makes this a credential-guessing surface, so it
    # is throttled like the login route rather than left open.
    try:
        from auth.router import _check_ip_rate_limit, _get_client_ip

        _check_ip_rate_limit(_get_client_ip(request))
    except HTTPException:
        raise
    except Exception as exc:  # limiter unavailable — do not fail the request closed
        logger.debug("change-password rate limit unavailable: %s", exc)

    try:
        # The one hashing scheme the rest of auth uses. Importing it rather than
        # reimplementing bcrypt here is the point: a second scheme in a second
        # file is how defect 2 above happened.
        from auth.jwt import hash_password, verify_password
        from database.connection import get_db_manager
        from database.models import User

        mgr = get_db_manager()
        if not mgr:
            raise HTTPException(status_code=503, detail="Database unavailable")

        with mgr.session() as session:
            row = session.query(User).filter_by(id=uid).first()
            if not row:
                raise HTTPException(status_code=404, detail="User not found")

            if not verify_password(body.current_password, row.hashed_password):
                logger.warning("change-password: wrong current password for user %s", uid)
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Current password is incorrect",
                )

            row.hashed_password = hash_password(body.new_password)
            session.commit()

    except HTTPException:
        raise
    except Exception as exc:
        logger.warning("Password change failed for user %s: %s", uid, exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Password change failed. Please try again.",
        ) from exc

    # Outside the DB block: the password is already committed, so a failure to
    # revoke must not turn a successful change into a 500 that tells the user it
    # did not happen. It is logged loudly instead, because a change that leaves
    # old sessions alive is the security-relevant half of this endpoint.
    revoked = False
    try:
        import asyncio

        from auth.router import _svc

        # _svc() is the initialised singleton — AuthService requires a
        # session_factory, so constructing one here would raise. logout_all is
        # blocking SQLAlchemy, which auth/service.py's threading model requires
        # callers in async contexts to wrap.
        await asyncio.to_thread(_svc().logout_all, uid)
        revoked = True
    except Exception as exc:
        logger.error(
            "Password changed for user %s but session revocation FAILED (%s) — "
            "pre-existing sessions may still be valid",
            uid,
            exc,
        )

    logger.info("Password changed for user %s (sessions_revoked=%s)", uid, revoked)
    return {"status": "updated", "sessions_revoked": revoked}


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
