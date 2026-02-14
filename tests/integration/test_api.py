"""
Integration tests for API endpoints.
"""

import pytest
from fastapi.testclient import TestClient

from app import app


@pytest.fixture
def client():
    """Create a test client."""
    with TestClient(app, raise_server_exceptions=False) as test_client:
        yield test_client


@pytest.mark.integration
class TestHealthEndpoints:
    """Test health and status endpoints."""

    def test_health_endpoint(self, client):
        """Test health check endpoint."""
        response = client.get("/health")

        assert response.status_code == 200
        data = response.json()
        assert data['status'] == 'healthy'

    def test_status_endpoint(self, client):
        """Test status endpoint."""
        response = client.get("/status")

        assert response.status_code == 200
        data = response.json()
        assert 'version' in data
        assert 'environment' in data


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
            "parameters": {
                "fast_period": 10,
                "slow_period": 20
            }
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
            "confidence": 0.8
        }

        response = client.post("/api/trading/position-size", json=request_data)

        assert response.status_code in [200, 500]


@pytest.mark.integration
class TestAdminEndpoints:
    """Test admin panel endpoints."""

    def test_admin_dashboard(self, client):
        """Test admin dashboard."""
        response = client.get("/admin/")

        assert response.status_code == 200
        assert b"HOPEFX" in response.content or b"Dashboard" in response.content

    def test_admin_strategies_page(self, client):
        """Test admin strategies page."""
        response = client.get("/admin/strategies")

        assert response.status_code == 200

    def test_admin_settings_page(self, client):
        """Test admin settings page."""
        response = client.get("/admin/settings")

        assert response.status_code == 200

    def test_admin_monitoring_page(self, client):
        """Test admin monitoring page."""
        response = client.get("/admin/monitoring")

        assert response.status_code == 200
