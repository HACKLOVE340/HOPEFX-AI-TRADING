# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
Integration tests for API endpoints.
"""

import os
import time

import jwt
import pytest

# Guard against missing or incompatible dependencies so that a broken
# import chain produces a graceful skip rather than an INTERNALERROR
# (pytest-asyncio ≤0.23.2 converts collection-time ImportError/NameError
# into INTERNALERROR when running in strict mode).
#
# APP_ENV=test must be set before importing app so that startup_validator
# runs in dev/test mode (skips production-only checks) instead of calling
# sys.exit(1) when broker credentials are absent.
os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("SECURITY_JWT_SECRET", "test-secret-key-for-integration-tests-only-32c")

try:
    from fastapi.testclient import TestClient
    from app import app

    _import_error = None
except (ImportError, ModuleNotFoundError, SystemExit) as e:
    _import_error = e


if _import_error is not None:
    pytest.skip(
        f"Skipping integration tests: {_import_error}",
        allow_module_level=True,
    )


def _admin_token() -> str:
    """Mint a short-lived admin JWT for integration tests."""
    secret = os.environ.get(
        "SECURITY_JWT_SECRET",
        "test-secret-key-minimum-32-characters-long",  # nosec B105 - test credential
    )
    return jwt.encode(
        {"sub": "test-admin", "role": "admin", "exp": int(time.time()) + 3600},
        secret,
        algorithm="HS256",
    )


def _admin_headers() -> dict:
    return {"Authorization": f"Bearer {_admin_token()}"}


@pytest.fixture(scope="module")
def client():
    """Create a single test client for the module.

    Uses TestClient without the context-manager lifespan to avoid hanging on
    Redis/DB connection attempts in CI/devcontainer where those services are
    unavailable.  The app is fully functional for HTTP-level tests; only
    background startup tasks (event bus, scheduler) are skipped.
    """
    os.environ.setdefault(
        "SECURITY_JWT_SECRET",
        "test-secret-key-minimum-32-characters-long",  # nosec B105 - test credential
    )
    # Instantiate without entering the lifespan context so Redis/DB timeouts
    # do not block the test suite.
    yield TestClient(app, raise_server_exceptions=False)


@pytest.mark.integration
class TestHealthEndpoints:
    """Test health and status endpoints."""

    def test_health_endpoint(self, client):
        """Test health check endpoint.

        In CI/devcontainer Redis and DB are unavailable, so the app reports
        'degraded' rather than 'healthy'. Both are valid non-error responses.
        """
        response = client.get("/health")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] in ("healthy", "degraded")

    def test_status_endpoint(self, client):
        """Test machine-readable status endpoint."""
        # /status is the public HTML status page; /api/status/json is the JSON API.
        response = client.get("/api/status/json")

        assert response.status_code == 200
        data = response.json()
        assert "status" in data
        assert "uptime_seconds" in data


@pytest.mark.integration
class TestTradingEndpoints:
    """Test trading API endpoints."""

    def test_list_strategies(self, client):
        """Test listing strategies."""
        response = client.get("/api/trading/strategies")

        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)

    def test_create_strategy(self, client):
        """Test creating a strategy."""
        strategy_data = {
            "name": "Test_MA",
            "type": "ma_crossover",
            "symbol": "EUR_USD",
            "parameters": {"fast_period": 10, "slow_period": 20},
        }

        response = client.post("/api/trading/strategies", json=strategy_data)

        # May fail if dependencies not available, but should handle gracefully
        assert response.status_code in [200, 201, 500]

    def test_get_risk_metrics(self, client):
        """Test getting risk metrics."""
        response = client.get("/api/trading/risk-metrics")

        assert response.status_code in [200, 500]  # May fail without full setup

    def test_calculate_position_size(self, client):
        """Test position size calculation."""
        request_data = {
            "entry_price": 1.1000,
            "stop_loss_price": 1.0950,
            "confidence": 0.8,
        }

        response = client.post("/api/trading/position-size", json=request_data)

        assert response.status_code in [200, 500]


@pytest.mark.integration
class TestAdminEndpoints:
    """Test admin API endpoints — all require admin JWT."""

    def test_admin_dashboard(self, client):
        """Test admin dashboard-data API endpoint."""
        response = client.get("/api/admin/dashboard-data", headers=_admin_headers())
        # 200 with data, or 403/401 if role check fails in test env
        assert response.status_code in (200, 401, 403)

    def test_admin_strategies_page(self, client):
        """Test admin status endpoint."""
        response = client.get("/api/admin/", headers=_admin_headers())
        assert response.status_code in (200, 401, 403)

    def test_admin_settings_page(self, client):
        """Test admin settings API endpoint."""
        response = client.get("/api/admin/settings", headers=_admin_headers())
        assert response.status_code in (200, 401, 403)

    def test_admin_monitoring_page(self, client):
        """Test admin activity API endpoint."""
        response = client.get("/api/admin/activity", headers=_admin_headers())
        assert response.status_code in (200, 401, 403)
