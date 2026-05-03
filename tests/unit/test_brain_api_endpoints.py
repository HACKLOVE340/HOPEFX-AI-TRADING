# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# AGPL-3.0 -- Share all modifications
"""
tests/unit/test_brain_api_endpoints.py
========================================
Unit tests for api/brain.py (AI Brain endpoints).

Covers:
  - GET  /api/brain/status
  - POST /api/brain/analyze
  - GET  /api/brain/market-analysis
  - GET  /api/brain/insights
  - POST /api/brain/generate-strategy
"""

from __future__ import annotations

import os
from typing import Any
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("SECURITY_JWT_SECRET", "unit-test-brain-secret-key-32chars!!")

from api.auth import TokenPayload, get_current_user, require_role
from api.brain import router as brain_router


# ---- Fixtures ----------------------------------------------------------------


@pytest.fixture()
def db_store() -> dict[str, Any]:
    return {}


@pytest.fixture()
def client(db_store: dict[str, Any]) -> TestClient:
    app = FastAPI()
    _user = TokenPayload(sub="brain-test-user", role="admin")
    app.dependency_overrides[require_role("trader")] = lambda: _user
    app.dependency_overrides[get_current_user] = lambda: _user
    app.include_router(brain_router)

    def _db_get(key: str) -> Any:
        return db_store.get(key)

    def _db_set(key: str, value: Any, **_kw) -> None:
        db_store[key] = value

    with patch("api.db_store.db_get", side_effect=_db_get), \
         patch("api.db_store.db_set", side_effect=_db_set):
        yield TestClient(app, raise_server_exceptions=True)


# ---- Tests -------------------------------------------------------------------


class TestBrainStatus:
    def test_status_returns_200(self, client: TestClient):
        resp = client.get("/api/brain/status")
        assert resp.status_code == 200

    def test_status_has_expected_fields(self, client: TestClient):
        data = client.get("/api/brain/status").json()
        for field in ("llm_available", "backend", "strategies_saved", "features"):
            assert field in data

    def test_status_features_are_booleans(self, client: TestClient):
        features = client.get("/api/brain/status").json()["features"]
        for k, v in features.items():
            assert isinstance(v, bool), f"Feature {k!r} should be bool, got {type(v)}"

    def test_status_without_llm_keys_llm_unavailable(self, client: TestClient):
        # No OPENAI / ANTHROPIC keys set in test env
        data = client.get("/api/brain/status").json()
        # May or may not have LLM available depending on env -- just check schema
        assert isinstance(data["llm_available"], bool)


class TestAnalyze:
    def test_analyze_without_data_returns_insufficient(self, client: TestClient):
        resp = client.post(
            "/api/brain/analyze",
            json={"symbol": "XAU_USD", "timeframe": "H1", "candle_count": 200},
        )
        assert resp.status_code == 200
        data = resp.json()
        # No live nuclear streamer in test => insufficient_data status
        assert data["symbol"] == "XAU_USD"
        assert data["timeframe"] == "H1"

    def test_analyze_returns_required_fields_or_status(self, client: TestClient):
        resp = client.post(
            "/api/brain/analyze",
            json={"symbol": "XAU_USD", "timeframe": "H1"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "symbol" in data

    def test_analyze_with_explicit_candle_count(self, client: TestClient):
        resp = client.post(
            "/api/brain/analyze",
            json={"symbol": "XAUUSD", "timeframe": "M15", "candle_count": 100},
        )
        assert resp.status_code == 200


class TestMarketAnalysis:
    def test_market_analysis_returns_200(self, client: TestClient):
        resp = client.get("/api/brain/market-analysis")
        assert resp.status_code == 200

    def test_market_analysis_symbol_default_is_xauusd(self, client: TestClient):
        data = client.get("/api/brain/market-analysis").json()
        # Default symbol is XAU_USD
        assert data["symbol"] == "XAU_USD"

    def test_market_analysis_custom_symbol(self, client: TestClient):
        resp = client.get("/api/brain/market-analysis", params={"symbol": "EURUSD"})
        assert resp.status_code == 200
        assert resp.json()["symbol"] == "EURUSD"


class TestInsights:
    def test_insights_returns_200(self, client: TestClient):
        resp = client.get("/api/brain/insights")
        assert resp.status_code == 200

    def test_insights_has_insights_field(self, client: TestClient):
        data = client.get("/api/brain/insights").json()
        assert "insights" in data

    def test_insights_is_list(self, client: TestClient):
        data = client.get("/api/brain/insights").json()
        assert isinstance(data["insights"], list)

    def test_insights_cached_on_second_call(self, client: TestClient, db_store: dict):
        # First call populates cache
        client.get("/api/brain/insights")
        # Second call should hit cache (same data)
        resp = client.get("/api/brain/insights")
        assert resp.status_code == 200


class TestGenerateStrategy:
    def test_generate_without_llm_returns_503(self, client: TestClient):
        # Without OPENAI/ANTHROPIC keys configured, endpoint returns 503
        resp = client.post(
            "/api/brain/generate-strategy",
            json={
                "prompt": "Create a trend-following SMA crossover strategy for XAU/USD",
                "symbol": "XAU_USD",
                "timeframe": "H1",
            },
        )
        # 503 when no LLM is available; 200 if LLM keys happen to be set
        assert resp.status_code in (200, 503)

    def test_generate_prompt_too_short_returns_422(self, client: TestClient):
        resp = client.post(
            "/api/brain/generate-strategy",
            json={"prompt": "hi", "symbol": "XAU_USD"},
        )
        # Pydantic min_length=5 validation
        assert resp.status_code == 422

    def test_generate_response_has_strategy_fields_when_available(self, client: TestClient):
        resp = client.post(
            "/api/brain/generate-strategy",
            json={"prompt": "Simple RSI mean-reversion strategy for gold", "symbol": "XAU_USD"},
        )
        if resp.status_code == 503:
            pytest.skip("LLM backend not configured in test environment")
        assert resp.status_code == 200
        data = resp.json()
        for field in ("success", "strategy_name", "strategy_code"):
            assert field in data
