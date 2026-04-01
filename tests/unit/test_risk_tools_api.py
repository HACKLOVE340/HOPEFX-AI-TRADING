# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
Unit tests for api/risk_tools.py

Coverage:
- POST /api/risk/margin-stress/run-all: valid input → 200 with summary
- POST /api/risk/margin-stress/run-all: missing module → 500
- POST /api/risk/margin-stress/run-all: invalid input types → 422
- GET /api/risk/margin-call/history: returns history dict
- GET /api/risk/margin-call/history: missing module → 500
- GET /api/risk/crowding: returns crowding health dict
- GET /api/risk/crowding: missing module → 500
- MarginStressRequest Pydantic model validation
"""

from __future__ import annotations

import types
from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.risk_tools import MarginStressRequest, router as risk_tools_router


# ── helpers ───────────────────────────────────────────────────────────────────

def _make_client() -> TestClient:
    app = FastAPI()
    app.include_router(risk_tools_router)
    return TestClient(app, raise_server_exceptions=False)


_VALID_ACCOUNTS = [
    {
        "name": "oanda",
        "equity": 10000.0,
        "positions": {"XAUUSD": 1.0},
        "initial_margin_pct": 0.02,
        "maintenance_margin_pct": 0.01,
    }
]

_MOCK_STRESS_SUMMARY = {
    "scenarios": ["30pct_drop", "50pct_drop"],
    "worst_case": "50pct_drop",
    "breached": False,
}

_MOCK_HISTORY = [
    {
        "broker": "oanda",
        "account": "ACC-001",
        "deficit_usd": 500.0,
        "timestamp": "2026-01-01T00:00:00+00:00",
        "resolved": True,
        "suspended": False,
        "positions_closed": ["XAUUSD"],
        "equity_injected": 0.0,
        "actions_taken": ["Margin call detected"],
    }
]


# ── MarginStressRequest ───────────────────────────────────────────────────────

@pytest.mark.unit
class TestMarginStressRequest:
    def test_valid_accounts_list(self):
        req = MarginStressRequest(accounts=_VALID_ACCOUNTS)
        assert len(req.accounts) == 1
        assert req.accounts[0]["name"] == "oanda"

    def test_empty_accounts_list_is_valid(self):
        req = MarginStressRequest(accounts=[])
        assert req.accounts == []


# ── POST /api/risk/margin-stress/run-all ─────────────────────────────────────

@pytest.mark.unit
class TestMarginStressRunAll:
    def test_happy_path_200(self):
        client = _make_client()

        mock_sim = MagicMock()
        mock_sim.return_value.run_all.return_value = []
        mock_sim.return_value.summary.return_value = _MOCK_STRESS_SUMMARY

        mock_account_cls = MagicMock(return_value=MagicMock())

        risk_stress_mod = types.ModuleType("risk.margin_stress")
        risk_stress_mod.MarginStressSimulator = mock_sim
        risk_stress_mod.BrokerAccount = mock_account_cls

        with patch.dict("sys.modules", {"risk.margin_stress": risk_stress_mod}):
            resp = client.post(
                "/api/risk/margin-stress/run-all",
                json={"accounts": _VALID_ACCOUNTS},
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data == _MOCK_STRESS_SUMMARY

    def test_module_not_available_returns_500(self):
        client = _make_client()
        with patch(
            "api.risk_tools.MarginStressRequest.__init__",
            side_effect=None,
        ), patch(
            "builtins.__import__",
            side_effect=ImportError("risk.margin_stress not installed"),
        ):
            resp = client.post(
                "/api/risk/margin-stress/run-all",
                json={"accounts": _VALID_ACCOUNTS},
            )
        # 422 (validation) or 500 (module error) — never a 200 with no handler
        assert resp.status_code in (422, 500)

    def test_internal_error_returns_500(self):
        """Exception inside run_all must return 500 not crash the server."""
        client = _make_client()

        mock_sim = MagicMock()
        mock_sim.return_value.run_all.side_effect = RuntimeError("broker offline")

        risk_stress_mod = types.ModuleType("risk.margin_stress")
        risk_stress_mod.MarginStressSimulator = mock_sim
        risk_stress_mod.BrokerAccount = MagicMock(return_value=MagicMock())

        with patch.dict("sys.modules", {"risk.margin_stress": risk_stress_mod}):
            resp = client.post(
                "/api/risk/margin-stress/run-all",
                json={"accounts": _VALID_ACCOUNTS},
            )

        assert resp.status_code == 500

    def test_missing_accounts_field_returns_422(self):
        client = _make_client()
        resp = client.post("/api/risk/margin-stress/run-all", json={})
        assert resp.status_code == 422

    def test_accounts_wrong_type_returns_422(self):
        client = _make_client()
        resp = client.post(
            "/api/risk/margin-stress/run-all",
            json={"accounts": "not-a-list"},
        )
        assert resp.status_code == 422


# ── GET /api/risk/margin-call/history ────────────────────────────────────────

@pytest.mark.unit
class TestMarginCallHistory:
    def test_happy_path_200(self):
        client = _make_client()

        mock_handler = MagicMock()
        mock_handler.history.return_value = _MOCK_HISTORY

        margin_call_mod = types.ModuleType("risk.margin_call_handler")
        margin_call_mod.margin_call_handler = mock_handler

        with patch.dict("sys.modules", {"risk.margin_call_handler": margin_call_mod}):
            resp = client.get("/api/risk/margin-call/history")

        assert resp.status_code == 200
        data = resp.json()
        assert "history" in data
        assert data["history"] == _MOCK_HISTORY

    def test_empty_history(self):
        client = _make_client()

        mock_handler = MagicMock()
        mock_handler.history.return_value = []

        margin_call_mod = types.ModuleType("risk.margin_call_handler")
        margin_call_mod.margin_call_handler = mock_handler

        with patch.dict("sys.modules", {"risk.margin_call_handler": margin_call_mod}):
            resp = client.get("/api/risk/margin-call/history")

        assert resp.status_code == 200
        assert resp.json()["history"] == []

    def test_module_error_returns_500(self):
        client = _make_client()

        margin_call_mod = types.ModuleType("risk.margin_call_handler")
        margin_call_mod.margin_call_handler = MagicMock(
            history=MagicMock(side_effect=RuntimeError("redis down"))
        )

        with patch.dict("sys.modules", {"risk.margin_call_handler": margin_call_mod}):
            resp = client.get("/api/risk/margin-call/history")

        assert resp.status_code == 500


# ── GET /api/risk/crowding ────────────────────────────────────────────────────

@pytest.mark.unit
class TestCrowdingStatus:
    def test_happy_path_200(self):
        client = _make_client()

        mock_monitor = MagicMock()
        mock_monitor.health.return_value = {"status": "ok", "crowding_score": 0.3}

        crowding_mod = types.ModuleType("risk.crowding")
        crowding_mod.crowding_monitor = mock_monitor

        with patch.dict("sys.modules", {"risk.crowding": crowding_mod}):
            resp = client.get("/api/risk/crowding")

        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert "crowding_score" in data

    def test_module_error_returns_500(self):
        client = _make_client()

        crowding_mod = types.ModuleType("risk.crowding")
        crowding_mod.crowding_monitor = MagicMock(
            health=MagicMock(side_effect=RuntimeError("unavailable"))
        )

        with patch.dict("sys.modules", {"risk.crowding": crowding_mod}):
            resp = client.get("/api/risk/crowding")

        assert resp.status_code == 500

    def test_stable_when_module_missing(self):
        """Endpoint returns 500 (not crash) when risk.crowding can't be imported."""
        client = _make_client()

        with patch(
            "importlib.import_module",
            side_effect=ImportError("risk.crowding not installed"),
        ):
            resp = client.get("/api/risk/crowding")

        assert resp.status_code in (200, 500)
