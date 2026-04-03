# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
"""
tests/unit/test_model_card.py
==============================
Unit tests for the GET /api/ml/model-card endpoint.

Uses FastAPI TestClient so no real network calls or ML models are required.
"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient


# ── Minimal app fixture ───────────────────────────────────────────────────────
@pytest.fixture(scope="module")
def client():
    """Return a TestClient with just the ML router mounted."""
    from fastapi import FastAPI

    from api.ml import router

    app = FastAPI()
    app.include_router(router)
    return TestClient(app, raise_server_exceptions=True)


def _auth_headers():
    """Return headers that pass the TokenPayload dependency."""
    # The ML router uses get_current_user which reads a JWT.
    # We mock the dependency so tests don't need a running auth server.
    return {}


# ── Dependency override helper ─────────────────────────────────────────────────
def _with_auth(client: TestClient):
    """Patch get_current_user to return a valid TokenPayload."""
    from api.auth import TokenPayload

    fake_user = TokenPayload(sub="test_user", role="user", exp=9999999999)

    from fastapi import FastAPI

    from api.ml import router as ml_router, get_current_user

    app = FastAPI()
    app.include_router(ml_router)
    app.dependency_overrides[get_current_user] = lambda: fake_user
    return TestClient(app, raise_server_exceptions=True)


# ── Tests ─────────────────────────────────────────────────────────────────────
class TestModelCardEndpoint:
    @pytest.fixture(autouse=True)
    def _setup_client(self):
        self.client = _with_auth(None)

    def test_model_card_200(self):
        """Endpoint should return 200 with a valid model card structure."""
        response = self.client.get("/api/ml/model-card")
        assert response.status_code == 200
        data = response.json()
        assert "schema_version" in data
        assert data["schema_version"] == "1.0"

    def test_model_card_has_required_sections(self):
        response = self.client.get("/api/ml/model-card")
        assert response.status_code == 200
        data = response.json()
        required_sections = [
            "model_details",
            "intended_use",
            "training_data",
            "evaluation_results",
            "quantitative_analysis",
            "drift_monitoring",
            "caveats_and_recommendations",
        ]
        for section in required_sections:
            assert section in data, f"Missing section: {section}"

    def test_model_details_has_version(self):
        response = self.client.get("/api/ml/model-card")
        assert response.status_code == 200
        data = response.json()
        details = data["model_details"]
        assert "version" in details
        assert "name" in details
        assert "task" in details

    def test_evaluation_results_has_oos_accuracy(self):
        response = self.client.get("/api/ml/model-card")
        assert response.status_code == 200
        eval_results = response.json()["evaluation_results"]
        assert "oos_accuracy" in eval_results
        assert "walk_forward" in eval_results

    def test_intended_use_has_out_of_scope(self):
        response = self.client.get("/api/ml/model-card")
        assert response.status_code == 200
        iu = response.json()["intended_use"]
        assert "out_of_scope" in iu
        assert isinstance(iu["out_of_scope"], list)
        assert len(iu["out_of_scope"]) > 0

    def test_caveats_has_risk_warnings(self):
        response = self.client.get("/api/ml/model-card")
        assert response.status_code == 200
        cav = response.json()["caveats_and_recommendations"]
        assert "risk_warnings" in cav
        # Must contain the standard disclaimer
        warnings_text = " ".join(cav["risk_warnings"])
        assert "PAST PERFORMANCE" in warnings_text

    def test_drift_monitoring_section_present(self):
        response = self.client.get("/api/ml/model-card")
        assert response.status_code == 200
        dm = response.json()["drift_monitoring"]
        assert "available" in dm

    def test_quantitative_analysis_has_regime_filter(self):
        response = self.client.get("/api/ml/model-card")
        assert response.status_code == 200
        qa = response.json()["quantitative_analysis"]
        assert "regime_filter" in qa
        rf = qa["regime_filter"]
        assert rf["enabled"] is True
        assert "HIGH_VOL_PARABOLIC" in rf["type"]

    def test_model_card_with_registry(self, tmp_path):
        """When registry.json exists, the endpoint should not crash."""
        registry = {
            "schema_version": 1,
            "active_version": "test_model_v1",
            "versions": {
                "test_model_v1": {
                    "name": "test_model_v1",
                    "file": "ml/saved_models/test.pkl",
                    "sha256": "abc123",
                    "state": "active",
                    "oos_accuracy": 0.62,
                    "oos_auc": 0.65,
                    "oos_f1": 0.63,
                    "oos_p_value": 0.0,
                    "sharpe_gate_passed": True,
                    "sharpe": 1.6,
                    "n_trades": 1500,
                    "feature_count": 200,
                    "horizon": 5,
                    "notes": "Test model for unit tests.",
                }
            },
        }
        registry_file = tmp_path / "registry.json"
        registry_file.write_text(json.dumps(registry))

        # The endpoint reads the real registry.json if it exists — just verify
        # the endpoint works without crashing (the actual registry may differ)
        response = self.client.get("/api/ml/model-card")
        assert response.status_code == 200

    def test_generated_at_is_iso8601(self):
        from datetime import datetime

        response = self.client.get("/api/ml/model-card")
        assert response.status_code == 200
        ts = response.json()["generated_at"]
        # Should parse as ISO 8601 datetime
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        assert dt.year >= 2025

    def test_no_authentication_returns_error(self):
        """Without dependency override, unauthenticated requests should fail."""
        from fastapi import FastAPI
        from api.ml import router as ml_router

        app = FastAPI()
        app.include_router(ml_router)
        bare_client = TestClient(app, raise_server_exceptions=False)
        response = bare_client.get("/api/ml/model-card")
        # Expect 401 or 403 or 422 (missing Authorization header)
        assert response.status_code in (401, 403, 422)
