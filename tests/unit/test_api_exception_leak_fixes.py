# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# AGPL-3.0 — Share all modifications
"""
tests/unit/test_api_exception_leak_fixes.py
============================================
Regression tests verifying that API endpoints do NOT leak raw internal
exception messages to HTTP clients.

Each test triggers an error path and asserts:
  1. The HTTP status code is correct.
  2. The response detail does NOT contain the raw exception message.

Covered endpoints / files:
  - api/trading.py              — broker operation errors (502)
  - api/nuclear_strategy.py     — pipeline / agent errors (500)
  - api/ml_anomaly.py           — anomaly subsystem errors (503/500)
  - api/brain.py                — LLM backend errors (502)
  - api/superadmin/users.py     — DB errors (500)
  - api/superadmin/ml_ai.py     — deploy / rollback errors (500)
"""

from __future__ import annotations

import os
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("SECURITY_JWT_SECRET", "test-secret-key-32chars-minimum!!")
os.environ.setdefault("DATABASE_URL", "sqlite:///./test_leak_fixes.db")

from api.auth import TokenPayload, get_current_user, require_role

# Sentinel string that must never appear in any HTTP response body
_INTERNAL_MSG = "internal-secret-db-error-xyz-do-not-expose"


# ─────────────────────────────────────────────────────────────────────────────
# api/trading.py — broker operation errors must not leak to client
# ─────────────────────────────────────────────────────────────────────────────


class TestTradingBrokerErrorsNotLeaked:
    """Broker errors on modify/cancel/partial-close must return generic 502."""

    @pytest.fixture()
    def client(self) -> TestClient:
        from api.trading import router as trading_router

        app = FastAPI()
        _user = TokenPayload(sub="test-trader", role="trader")
        app.dependency_overrides[get_current_user] = lambda: _user
        app.dependency_overrides[require_role("trader")] = lambda: _user
        app.include_router(trading_router)
        return TestClient(app, raise_server_exceptions=False)

    def test_modify_position_broker_error_returns_generic_502(self, client: TestClient):
        import api.trading as trading_mod

        mock_broker = MagicMock()
        mock_broker.modify_position = MagicMock(side_effect=RuntimeError(_INTERNAL_MSG))
        mock_state = MagicMock()
        mock_state.broker = mock_broker

        with patch.object(trading_mod, "app_state", mock_state), \
             patch.object(trading_mod, "_check_kill_switch", return_value=None):
            resp = client.patch(
                "/api/trading/positions/pos-001",
                json={"stop_loss": 1900.0},
            )

        assert resp.status_code == 502
        assert _INTERNAL_MSG not in resp.text
        assert resp.json()["detail"] == "Broker operation failed."

    def test_cancel_order_broker_error_returns_generic_502(self, client: TestClient):
        import api.trading as trading_mod

        mock_broker = MagicMock()
        mock_broker.cancel_order = MagicMock(side_effect=RuntimeError(_INTERNAL_MSG))
        mock_state = MagicMock()
        mock_state.broker = mock_broker

        with patch.object(trading_mod, "app_state", mock_state), \
             patch.object(trading_mod, "_check_kill_switch", return_value=None):
            resp = client.delete("/api/trading/orders/ord-001")

        assert resp.status_code == 502
        assert _INTERNAL_MSG not in resp.text
        assert resp.json()["detail"] == "Broker operation failed."

    def test_modify_order_broker_error_returns_generic_502(self, client: TestClient):
        import api.trading as trading_mod

        mock_broker = MagicMock()
        mock_broker.modify_order = MagicMock(side_effect=RuntimeError(_INTERNAL_MSG))
        mock_state = MagicMock()
        mock_state.broker = mock_broker

        with patch.object(trading_mod, "app_state", mock_state), \
             patch.object(trading_mod, "_check_kill_switch", return_value=None):
            resp = client.patch(
                "/api/trading/orders/ord-001",
                json={"price": 2000.0},
            )

        assert resp.status_code == 502
        assert _INTERNAL_MSG not in resp.text
        assert resp.json()["detail"] == "Broker operation failed."

    def test_partial_close_broker_error_returns_generic_502(self, client: TestClient):
        import api.trading as trading_mod

        mock_broker = MagicMock()
        mock_broker.partial_close_position = MagicMock(side_effect=RuntimeError(_INTERNAL_MSG))
        mock_state = MagicMock()
        mock_state.broker = mock_broker

        with patch.object(trading_mod, "app_state", mock_state), \
             patch.object(trading_mod, "_check_kill_switch", return_value=None):
            resp = client.post(
                "/api/trading/positions/pos-001/partial-close",
                json={"quantity": 0.5},
            )

        assert resp.status_code == 502
        assert _INTERNAL_MSG not in resp.text
        assert resp.json()["detail"] == "Broker operation failed."


# ─────────────────────────────────────────────────────────────────────────────
# api/nuclear_strategy.py — pipeline errors must not leak
# ─────────────────────────────────────────────────────────────────────────────


class TestNuclearStrategyErrorsNotLeaked:
    @pytest.fixture()
    def client(self) -> TestClient:
        from api.nuclear_strategy import router as ns_router

        app = FastAPI()
        _admin = TokenPayload(sub="test-admin", role="admin")
        _trader = TokenPayload(sub="test-trader", role="trader")
        app.dependency_overrides[get_current_user] = lambda: _trader
        app.dependency_overrides[require_role("trader")] = lambda: _trader
        app.dependency_overrides[require_role("admin")] = lambda: _admin
        app.include_router(ns_router)
        return TestClient(app, raise_server_exceptions=False)

    def test_analyze_pipeline_error_not_leaked(self, client: TestClient):
        mock_agent = MagicMock()
        mock_agent.analyze.side_effect = RuntimeError(_INTERNAL_MSG)

        with patch("api.nuclear_strategy._get_agent", return_value=mock_agent):
            resp = client.get("/analyze")

        assert resp.status_code == 500
        assert _INTERNAL_MSG not in resp.text
        assert resp.json()["detail"] == "Pipeline error."

    def test_agent_start_error_not_leaked(self, client: TestClient):
        mock_agent = AsyncMock()
        mock_agent.start.side_effect = RuntimeError(_INTERNAL_MSG)
        mock_agent.status.return_value = {}

        with patch("nuclear.nuclear_agent.get_nuclear_agent", return_value=mock_agent):
            resp = client.post("/agent/start", json={"symbol": "XAU_USD"})

        assert resp.status_code == 500
        assert _INTERNAL_MSG not in resp.text
        assert resp.json()["detail"] == "Agent start failed."

    def test_agent_stop_error_not_leaked(self, client: TestClient):
        mock_agent = AsyncMock()
        mock_agent.stop.side_effect = RuntimeError(_INTERNAL_MSG)
        mock_agent.status.return_value = {}

        with patch("nuclear.nuclear_agent.get_nuclear_agent", return_value=mock_agent):
            resp = client.post("/agent/stop")

        assert resp.status_code == 500
        assert _INTERNAL_MSG not in resp.text
        assert resp.json()["detail"] == "Agent stop failed."


# ─────────────────────────────────────────────────────────────────────────────
# api/ml_anomaly.py — anomaly subsystem errors must not leak
# ─────────────────────────────────────────────────────────────────────────────


class TestMlAnomalyErrorsNotLeaked:
    @pytest.fixture()
    def client(self) -> TestClient:
        from api.ml_anomaly import router as anomaly_router

        app = FastAPI()
        _user = TokenPayload(sub="test-admin", role="admin")
        app.dependency_overrides[get_current_user] = lambda: _user
        app.dependency_overrides[require_role("admin")] = lambda: _user
        app.include_router(anomaly_router)
        return TestClient(app, raise_server_exceptions=False)

    def test_status_store_error_not_leaked(self, client: TestClient):
        with patch("api.ml_anomaly._get_live_store", side_effect=RuntimeError(_INTERNAL_MSG)):
            resp = client.get("/api/ml/anomaly/status")

        assert resp.status_code in (500, 503)
        assert _INTERNAL_MSG not in resp.text

    def test_fit_store_error_not_leaked(self, client: TestClient):
        with patch("api.ml_anomaly._get_live_store", side_effect=RuntimeError(_INTERNAL_MSG)):
            resp = client.post("/api/ml/anomaly/fit", json={"symbol": "XAUUSD"})

        assert resp.status_code in (500, 503)
        assert _INTERNAL_MSG not in resp.text

    def test_fit_error_detail_is_generic(self, client: TestClient):
        mock_store = MagicMock()
        mock_store.status.return_value = {"fitted": False, "buffer_size": 0}

        with patch("api.ml_anomaly._get_live_store", return_value=mock_store), \
             patch("api.ml_anomaly._load_ohlcv", side_effect=RuntimeError(_INTERNAL_MSG)):
            resp = client.post("/api/ml/anomaly/fit", json={"symbol": "XAUUSD"})

        assert resp.status_code == 500
        assert _INTERNAL_MSG not in resp.text
        assert resp.json()["detail"] == "Anomaly detector fit failed."


# ─────────────────────────────────────────────────────────────────────────────
# api/brain.py — LLM backend errors must not leak
# ─────────────────────────────────────────────────────────────────────────────


class TestBrainLLMErrorsNotLeaked:
    @pytest.fixture()
    def client(self) -> TestClient:
        from api.brain import router as brain_router

        app = FastAPI()
        _user = TokenPayload(sub="test-user", role="trader")
        app.dependency_overrides[get_current_user] = lambda: _user
        app.include_router(brain_router)
        return TestClient(app, raise_server_exceptions=False)

    def test_complete_openai_error_not_leaked(self, client: TestClient):
        import api.brain as brain_mod

        mock_openai = MagicMock()
        mock_openai.chat.completions.create.side_effect = RuntimeError(_INTERNAL_MSG)

        with patch.object(brain_mod, "_detect_llm_backend", return_value=("openai", "gpt-4")), \
             patch.dict("sys.modules", {"openai": mock_openai}):
            resp = client.post("/api/brain/complete", json={"prompt": "hello"})

        assert resp.status_code in (502, 503)
        assert _INTERNAL_MSG not in resp.text
        if resp.status_code == 502:
            assert resp.json()["detail"] == "LLM backend error."

    def test_complete_ollama_error_not_leaked(self, client: TestClient):
        import api.brain as brain_mod

        mock_httpx = MagicMock()
        mock_httpx.post.side_effect = RuntimeError(_INTERNAL_MSG)

        with patch.object(brain_mod, "_detect_llm_backend", return_value=("ollama", "llama3")), \
             patch.dict("sys.modules", {"httpx": mock_httpx}):
            resp = client.post("/api/brain/complete", json={"prompt": "hello"})

        assert resp.status_code in (502, 503)
        assert _INTERNAL_MSG not in resp.text
        if resp.status_code == 502:
            assert resp.json()["detail"] == "LLM backend error."

    def test_embed_openai_error_not_leaked(self, client: TestClient):
        import api.brain as brain_mod

        mock_openai = MagicMock()
        mock_openai.embeddings.create.side_effect = RuntimeError(_INTERNAL_MSG)

        with patch.object(brain_mod, "_detect_llm_backend", return_value=("openai", "text-embedding-3-small")), \
             patch.dict("sys.modules", {"openai": mock_openai}):
            resp = client.post("/api/brain/embed", json={"input": "test text"})

        assert resp.status_code in (502, 503)
        assert _INTERNAL_MSG not in resp.text
        if resp.status_code == 502:
            assert resp.json()["detail"] == "LLM embed error."

    def test_embed_ollama_error_not_leaked(self, client: TestClient):
        import api.brain as brain_mod

        mock_httpx = MagicMock()
        mock_httpx.post.side_effect = RuntimeError(_INTERNAL_MSG)

        with patch.object(brain_mod, "_detect_llm_backend", return_value=("ollama", "nomic-embed-text")), \
             patch.dict("sys.modules", {"httpx": mock_httpx}):
            resp = client.post("/api/brain/embed", json={"input": "test text"})

        assert resp.status_code in (502, 503)
        assert _INTERNAL_MSG not in resp.text
        if resp.status_code == 502:
            assert resp.json()["detail"] == "LLM embed error."


# ─────────────────────────────────────────────────────────────────────────────
# api/superadmin/users.py — DB errors must not leak
# ─────────────────────────────────────────────────────────────────────────────


class TestSuperadminUsersErrorsNotLeaked:
    @pytest.fixture()
    def client(self) -> TestClient:
        from api.superadmin.users import router as users_router, _require_superadmin

        app = FastAPI()
        _user = TokenPayload(sub="superadmin-001", role="superadmin")
        app.dependency_overrides[_require_superadmin] = lambda: _user
        app.include_router(users_router)
        return TestClient(app, raise_server_exceptions=False)

    def test_list_users_db_error_not_leaked(self, client: TestClient):
        import api.superadmin.users as users_mod

        with patch.object(users_mod, "SessionLocal", side_effect=RuntimeError(_INTERNAL_MSG)):
            resp = client.get("/users")

        assert resp.status_code == 500
        assert _INTERNAL_MSG not in resp.text
        assert resp.json()["detail"] == "Internal server error."

    def test_get_user_db_error_not_leaked(self, client: TestClient):
        import api.superadmin.users as users_mod

        with patch.object(users_mod, "SessionLocal", side_effect=RuntimeError(_INTERNAL_MSG)):
            resp = client.get("/users/user-001")

        assert resp.status_code == 500
        assert _INTERNAL_MSG not in resp.text
        assert resp.json()["detail"] == "Internal server error."

    def test_update_user_db_error_not_leaked(self, client: TestClient):
        import api.superadmin.users as users_mod

        with patch.object(users_mod, "SessionLocal", side_effect=RuntimeError(_INTERNAL_MSG)):
            resp = client.patch("/users/user-001", json={"plan": "professional"})

        assert resp.status_code == 500
        assert _INTERNAL_MSG not in resp.text
        assert resp.json()["detail"] == "Internal server error."

    def test_delete_user_db_error_not_leaked(self, client: TestClient):
        import api.superadmin.users as users_mod

        with patch.object(users_mod, "SessionLocal", side_effect=RuntimeError(_INTERNAL_MSG)):
            resp = client.delete("/users/user-999")

        assert resp.status_code == 500
        assert _INTERNAL_MSG not in resp.text
        assert resp.json()["detail"] == "Internal server error."


# ─────────────────────────────────────────────────────────────────────────────
# api/superadmin/ml_ai.py — deploy/rollback errors must not leak
# ─────────────────────────────────────────────────────────────────────────────


class TestSuperadminMlAiErrorsNotLeaked:
    @pytest.fixture()
    def client(self) -> TestClient:
        from api.superadmin.ml_ai import router as ml_router, _require_superadmin

        app = FastAPI()
        _user = TokenPayload(sub="superadmin-001", role="superadmin")
        app.dependency_overrides[_require_superadmin] = lambda: _user
        app.include_router(ml_router)
        return TestClient(app, raise_server_exceptions=False)

    def test_deploy_model_error_not_leaked(self, client: TestClient):
        import api.superadmin.ml_ai as ml_mod

        with patch.object(ml_mod, "_log_superadmin_action", return_value=None):
            mock_registry = MagicMock()
            mock_registry.get_registry.side_effect = RuntimeError(_INTERNAL_MSG)
            with patch.dict("sys.modules", {"ml.model_registry": mock_registry}):
                resp = client.post(
                    "/ml/deploy",
                    json={"model": "advanced_oos", "version": "v2"},
                )

        assert resp.status_code in (500, 422)
        assert _INTERNAL_MSG not in resp.text
        if resp.status_code == 500:
            assert resp.json()["detail"] == "Deploy failed."

    def test_rollback_model_error_not_leaked(self, client: TestClient):
        import api.superadmin.ml_ai as ml_mod

        with patch.object(ml_mod, "_log_superadmin_action", return_value=None):
            mock_registry = MagicMock()
            mock_registry.get_registry.side_effect = RuntimeError(_INTERNAL_MSG)
            with patch.dict("sys.modules", {"ml.model_registry": mock_registry}):
                resp = client.post("/ml/rollback/advanced_oos")

        assert resp.status_code in (500, 422)
        assert _INTERNAL_MSG not in resp.text
        if resp.status_code == 500:
            assert resp.json()["detail"] == "Rollback failed."
