# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
Integration tests: API call → DB write → response correct.

Exercises the full HTTP stack using FastAPI TestClient against real
router instances. No external services required — DB falls back to
the in-memory store, broker falls back to PaperTradingBroker.
"""

from __future__ import annotations

import os
import time

import jwt
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

# Pin the JWT secret for this module — must be set before any api.auth import.
# We force-set (not setdefault) so other tests that mutate the env var don't
# break our token verification.
_TEST_SECRET = "integration-test-secret-key-32chars!!"  # pragma: allowlist secret
os.environ["SECURITY_JWT_SECRET"] = _TEST_SECRET

_SECRET = _TEST_SECRET


# ── JWT helpers ───────────────────────────────────────────────────────────────


def _make_token(sub: str = "user-int-001", role: str = "trader") -> str:
    now = int(time.time())
    return jwt.encode(
        {"sub": sub, "role": role, "type": "access", "iat": now, "exp": now + 3600},
        _SECRET,
        algorithm="HS256",
    )


def _auth(sub: str = "user-int-001", role: str = "trader") -> dict[str, str]:
    return {"Authorization": f"Bearer {_make_token(sub=sub, role=role)}"}


# ── App fixtures ──────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _pin_jwt_secret(monkeypatch):
    """Ensure SECURITY_JWT_SECRET matches _TEST_SECRET for every test in this module."""
    monkeypatch.setenv("SECURITY_JWT_SECRET", _TEST_SECRET)


@pytest.fixture()
def watchlist_client() -> TestClient:
    """Fresh in-memory state per test — prevents cross-test leakage.

    Injects a real PaperTradingBroker into api.watchlist.app_state so the
    /prices endpoint has live (paper) prices without any mocks.
    """
    import api.watchlist as _wl
    from api.watchlist import _reset_watchlists, router
    from brokers.paper_trading import PaperTradingBroker

    _reset_watchlists()

    # Wire a real paper broker as the price source
    broker = PaperTradingBroker()

    class _State:
        pass

    state = _State()
    state.broker = broker  # type: ignore[attr-defined]
    state.price_engine = None  # type: ignore[attr-defined]
    _wl.set_state(state)

    app = FastAPI()
    app.include_router(router)
    client = TestClient(app, raise_server_exceptions=False)
    yield client

    # Teardown: clear injected state and reset watchlist dict
    _reset_watchlists()
    _wl.set_state(None)


@pytest.fixture()
def trading_client() -> TestClient:
    from api.trading import router

    app = FastAPI()
    app.include_router(router)
    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture()
def signals_client() -> TestClient:
    from api.signals import create_signals_router

    app = FastAPI()
    app.include_router(create_signals_router())
    return TestClient(app, raise_server_exceptions=False)


# ── Watchlist: API → in-memory DB → response ─────────────────────────────────


class TestWatchlistFlow:
    """Full HTTP flow: auth → write → read → delete → verify."""

    def test_get_watchlist_requires_auth(self, watchlist_client):
        r = watchlist_client.get("/api/watchlist")
        # FastAPI HTTPBearer returns 403 when no credentials at all,
        # but some versions return 401 — both mean unauthenticated.
        assert r.status_code in (401, 403), r.text

    def test_get_watchlist_returns_defaults_for_new_user(self, watchlist_client):
        r = watchlist_client.get("/api/watchlist", headers=_auth(sub="new-user-999"))
        assert r.status_code == 200
        body = r.json()
        assert "symbols" in body
        assert "items" in body
        assert len(body["symbols"]) > 0
        assert body["user_id"] == "new-user-999"

    def test_add_symbol_persists_in_get(self, watchlist_client):
        sub = "user-wl-add-001"
        # Add a symbol
        r = watchlist_client.post("/api/watchlist/USDJPY", headers=_auth(sub=sub))
        assert r.status_code == 201, r.text
        assert r.json()["added"] is True

        # Verify it appears in GET
        r2 = watchlist_client.get("/api/watchlist", headers=_auth(sub=sub))
        assert r2.status_code == 200
        assert "USDJPY" in r2.json()["symbols"]

    def test_add_duplicate_symbol_returns_409(self, watchlist_client):
        sub = "user-wl-dup-001"
        watchlist_client.post("/api/watchlist/EURUSD", headers=_auth(sub=sub))
        r = watchlist_client.post("/api/watchlist/EURUSD", headers=_auth(sub=sub))
        assert r.status_code == 409

    def test_delete_symbol_removes_from_watchlist(self, watchlist_client):
        sub = "user-wl-del-001"
        watchlist_client.post("/api/watchlist/GBPUSD", headers=_auth(sub=sub))

        r = watchlist_client.delete("/api/watchlist/GBPUSD", headers=_auth(sub=sub))
        assert r.status_code == 200
        assert r.json()["removed"] is True

        r2 = watchlist_client.get("/api/watchlist", headers=_auth(sub=sub))
        assert "GBPUSD" not in r2.json()["symbols"]

    def test_delete_nonexistent_symbol_returns_404(self, watchlist_client):
        r = watchlist_client.delete("/api/watchlist/FAKESYM", headers=_auth(sub="user-wl-404"))
        assert r.status_code == 404

    def test_prices_endpoint_returns_items_with_bid_ask(self, watchlist_client):
        r = watchlist_client.get("/api/watchlist/prices", headers=_auth())
        assert r.status_code == 200
        items = r.json()
        assert isinstance(items, list)
        assert len(items) > 0
        first = items[0]
        assert "bid" in first
        assert "ask" in first
        assert first["ask"] >= first["bid"]

    def test_watchlists_are_isolated_per_user(self, watchlist_client):
        """Two users' watchlists must not bleed into each other."""
        user_a = "isolation-user-a"
        user_b = "isolation-user-b"

        watchlist_client.post("/api/watchlist/NZDUSD", headers=_auth(sub=user_a))

        r_b = watchlist_client.get("/api/watchlist", headers=_auth(sub=user_b))
        assert "NZDUSD" not in r_b.json()["symbols"]


# ── Trading: API → strategy store → response ─────────────────────────────────


class TestTradingFlow:
    """Strategy CRUD: create → read → start → stop → delete."""

    def test_list_strategies_returns_list(self, trading_client):
        r = trading_client.get("/api/trading/strategies", headers=_auth())
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    def test_create_strategy_returns_id(self, trading_client):
        payload = {"name": "int-test-ma", "symbol": "XAUUSD"}
        r = trading_client.post("/api/trading/strategies", json=payload, headers=_auth())
        assert r.status_code in (200, 201), r.text
        body = r.json()
        assert "id" in body or "strategy_id" in body

    def test_get_nonexistent_strategy_returns_404(self, trading_client):
        r = trading_client.get("/api/trading/strategies/does-not-exist-xyz", headers=_auth())
        assert r.status_code == 404

    def test_position_size_calculation(self, trading_client):
        payload = {
            "entry_price": 2050.0,
            "stop_loss_price": 2030.0,
            "confidence": 0.8,
        }
        r = trading_client.post("/api/trading/position-size", json=payload, headers=_auth())
        assert r.status_code == 200
        body = r.json()
        assert "recommended_size" in body or "size" in body or "position_size" in body

    def test_risk_metrics_endpoint_responds(self, trading_client):
        r = trading_client.get("/api/trading/risk-metrics", headers=_auth())
        assert r.status_code == 200

    def test_performance_summary_endpoint_responds(self, trading_client):
        r = trading_client.get("/api/trading/performance/summary", headers=_auth())
        assert r.status_code == 200


# ── Signals: read-only public endpoints ──────────────────────────────────────


class TestSignalsFlow:
    """Signal endpoints return well-formed responses."""

    def test_get_signals_summary_responds(self, signals_client):
        r = signals_client.get("/api/signals/summary", headers=_auth())
        assert r.status_code == 200

    def test_get_active_signals_returns_signals_key(self, signals_client):
        r = signals_client.get("/api/signals/active", headers=_auth())
        assert r.status_code == 200
        body = r.json()
        # Response is {"signals": [...], "count": N}
        assert "signals" in body
        assert isinstance(body["signals"], list)

    def test_get_signal_history_returns_signals_key(self, signals_client):
        r = signals_client.get("/api/signals/history", headers=_auth())
        assert r.status_code == 200
        body = r.json()
        assert "signals" in body
        assert isinstance(body["signals"], list)

    def test_get_signal_analytics_responds(self, signals_client):
        r = signals_client.get("/api/signals/analytics", headers=_auth())
        assert r.status_code == 200
