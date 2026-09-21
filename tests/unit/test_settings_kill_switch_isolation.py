# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
tests/unit/test_settings_kill_switch_isolation.py
=================================================
`POST /api/settings/trading` must not touch the kill switch.

It used to. `kill_switch_enabled` defaults to False on the request model, so any
save that omitted the field — a user changing their default lot size — took the
"user explicitly disabled the kill switch" branch and called
`risk_manager.resume_trading()`, whose own docstring reads "requires explicit
operator action". A halt raised by a drawdown circuit breaker could be cleared by
any authenticated user at any plan tier.

The same branch called `kill_switch.deactivate()` with no token, bypassing both
the admin role check on `POST /api/admin/resume` and the
HOPEFX_KILL_SWITCH_TOKEN requirement that exists so trading cannot resume
unattended. That call raised and was swallowed by a debug-level except, so the
attempt left no trace above DEBUG.

These tests pin the isolation. Halting and resuming belong to the admin-gated
operator endpoints.
"""

from __future__ import annotations

import sys
import types
from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.auth import TokenPayload, get_current_user
from api.settings_extended import router

CALLER = "ordinary-user"


@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_current_user] = lambda: TokenPayload(sub=CALLER, role="user")
    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture
def live_engine():
    """Install a fake app-level kill switch and risk manager, and hand both back."""
    kill_switch = MagicMock()
    kill_switch.is_active.return_value = True

    risk_manager = MagicMock()

    fake_app = types.ModuleType("app")
    fake_app.kill_switch = kill_switch
    saved = sys.modules.get("app")
    sys.modules["app"] = fake_app

    state = MagicMock()
    state.risk_manager = risk_manager
    try:
        with patch("core.app_state.app_state", state):
            yield kill_switch, risk_manager
    finally:
        if saved is not None:
            sys.modules["app"] = saved
        else:
            sys.modules.pop("app", None)


def _prefs(**overrides) -> dict:
    body = {
        "default_symbol": "XAU_USD",
        "default_timeframe": "1h",
        "default_lot_size": 0.02,
        "max_risk_per_trade": 1.0,
        "max_daily_drawdown": 5.0,
        "auto_trade_enabled": False,
        "slippage_tolerance": 3,
        "default_leverage": 50,
    }
    body.update(overrides)
    return body


class TestSavingPreferencesCannotResumeTrading:
    def test_omitting_the_field_does_not_deactivate(self, client, live_engine):
        """The realistic case: a user edits their lot size and saves."""
        kill_switch, risk_manager = live_engine

        res = client.post("/api/settings/trading", json=_prefs())

        assert res.status_code == 200
        kill_switch.deactivate.assert_not_called()
        risk_manager.resume_trading.assert_not_called()

    def test_explicit_false_does_not_deactivate(self, client, live_engine):
        """Even an explicit false must not resume trading from this endpoint."""
        kill_switch, risk_manager = live_engine

        res = client.post("/api/settings/trading", json=_prefs(kill_switch_enabled=False))

        assert res.status_code == 200
        kill_switch.deactivate.assert_not_called()
        risk_manager.resume_trading.assert_not_called()

    def test_the_halt_is_still_reported_as_active(self, client, live_engine):
        """The response must reflect real engine state, not the submitted value."""
        res = client.post("/api/settings/trading", json=_prefs(kill_switch_enabled=False))
        assert res.json()["kill_switch_enabled"] is True


class TestSavingPreferencesCannotHaltTrading:
    def test_requesting_a_halt_is_rejected_not_silently_ignored(self, client, live_engine):
        """A caller reaching for the halt must not get a bare success back.

        Returning 200 here would read as "trading halted" to the client while
        nothing had been halted.
        """
        kill_switch, _ = live_engine
        kill_switch.is_active.return_value = False

        res = client.post("/api/settings/trading", json=_prefs(kill_switch_enabled=True))

        assert res.status_code == 400
        assert "emergency stop" in res.json()["detail"].lower()
        kill_switch.activate.assert_not_called()


class TestPreferencesRoundTrip:
    def test_kill_switch_is_not_persisted_as_a_preference(self, client, live_engine):
        """It is global engine state. Storing it invites the next reader to sync from it."""
        with patch("api.settings_extended._save") as save:
            client.post("/api/settings/trading", json=_prefs())

        stored = save.call_args.args[2]
        assert "kill_switch_enabled" not in stored
        assert stored["default_lot_size"] == 0.02

    def test_get_reports_live_state_not_stored_value(self, client, live_engine):
        """A stale stored value could report trading halted when it is running."""
        with patch("api.settings_extended._load", return_value={"kill_switch_enabled": False}):
            res = client.get("/api/settings/trading")

        assert res.json()["kill_switch_enabled"] is True
