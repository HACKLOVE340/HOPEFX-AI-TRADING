"""
Tests for trading endpoint authentication and input validation.

Covers:
- Unauthenticated requests are rejected (401)
- Insufficient role is rejected (403)
- Valid trader token can place orders / close positions
- Admin-only emergency-stop is blocked for trader role
- Symbol allowlist enforcement
- Quantity bounds enforcement
- Order side / type validation
"""

import os
import time
from typing import Any, Dict, List, Optional
from unittest.mock import AsyncMock, MagicMock

import importlib.util
import pathlib
import sys

import jwt
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

# Set env vars before any project imports so module-level reads pick them up
os.environ["SECURITY_JWT_SECRET"] = "test-secret-key-minimum-32-characters-long"
os.environ["ALLOWED_SYMBOLS"] = "XAUUSD,EURUSD,BTCUSD"
os.environ["MAX_ORDER_QUANTITY"] = "10.0"

_API_DIR = pathlib.Path(__file__).parents[2] / "api"


def _load_module(name: str, path: pathlib.Path):
    """Load a single .py file as a module, bypassing package __init__."""
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


# Register a minimal 'api' package stub so submodule dotted names resolve
if "api" not in sys.modules:
    import types
    _api_pkg = types.ModuleType("api")
    _api_pkg.__path__ = [str(_API_DIR)]
    _api_pkg.__package__ = "api"
    sys.modules["api"] = _api_pkg

# Load auth first (trading imports from it)
auth_module = _load_module("api.auth", _API_DIR / "auth.py")
trading_module = _load_module("api.trading", _API_DIR / "trading.py")

from api.auth import _ROLE_RANK, require_role, get_current_user, validate_order_symbol, validate_order_quantity
router = trading_module.router


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_SECRET = os.environ["SECURITY_JWT_SECRET"]


def _make_token(role: str = "trader", expired: bool = False, sub: str = "user-123") -> str:
    now = int(time.time())
    payload = {
        "sub": sub,
        "role": role,
        "iat": now,
        "exp": now - 10 if expired else now + 3600,
    }
    return jwt.encode(payload, _SECRET, algorithm="HS256")


def _auth(role: str = "trader") -> Dict[str, str]:
    return {"Authorization": f"Bearer {_make_token(role)}"}


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def mock_broker():
    broker = MagicMock()

    order_result = MagicMock()
    order_result.id = "ORD-001"
    order_result.average_fill_price = 1950.0
    order_result.filled_quantity = 1.0

    broker.place_market_order = AsyncMock(return_value=order_result)
    broker.get_positions = AsyncMock(return_value=[])
    broker.close_position = AsyncMock(return_value=True)
    broker.close_all_positions = AsyncMock(return_value=2)
    broker.get_account_info = AsyncMock(return_value={"balance": 10000.0, "equity": 10050.0})
    return broker


@pytest.fixture()
def mock_brain():
    brain = MagicMock()
    brain.state.to_dict.return_value = {"regime": "trending", "confidence": 0.8}
    brain.emergency_stop = MagicMock()
    return brain


@pytest.fixture()
def app(mock_broker, mock_brain):
    state = MagicMock()
    state.broker = mock_broker
    state.brain = mock_brain
    state.price_engine = None
    trading_module.set_state(state)

    application = FastAPI()
    application.include_router(router)
    return application


@pytest.fixture()
def client(app):
    return TestClient(app, raise_server_exceptions=False)


# ---------------------------------------------------------------------------
# Authentication: missing / invalid / expired tokens
# ---------------------------------------------------------------------------

class TestAuthRejection:
    def test_place_order_no_token(self, client):
        # HTTPBearer(auto_error=True) returns 403 when Authorization header is absent
        resp = client.post("/api/trading/order", json={"symbol": "XAUUSD", "side": "buy", "quantity": 1.0})
        assert resp.status_code in (401, 403)

    def test_place_order_invalid_token(self, client):
        resp = client.post(
            "/api/trading/order",
            json={"symbol": "XAUUSD", "side": "buy", "quantity": 1.0},
            headers={"Authorization": "Bearer not.a.valid.token"},
        )
        assert resp.status_code == 401

    def test_place_order_expired_token(self, client):
        resp = client.post(
            "/api/trading/order",
            json={"symbol": "XAUUSD", "side": "buy", "quantity": 1.0},
            headers={"Authorization": f"Bearer {_make_token(expired=True)}"},
        )
        assert resp.status_code == 401
        assert "expired" in resp.json()["detail"].lower()

    def test_get_positions_no_token(self, client):
        resp = client.get("/api/trading/positions")
        assert resp.status_code in (401, 403)

    def test_close_position_no_token(self, client):
        resp = client.delete("/api/trading/positions/POS-1")
        assert resp.status_code in (401, 403)

    def test_emergency_stop_no_token(self, client):
        resp = client.post("/api/trading/emergency-stop")
        assert resp.status_code in (401, 403)


# ---------------------------------------------------------------------------
# Role-based access control
# ---------------------------------------------------------------------------

class TestRoleEnforcement:
    def test_place_order_user_role_rejected(self, client):
        """'user' role must not place orders."""
        resp = client.post(
            "/api/trading/order",
            json={"symbol": "XAUUSD", "side": "buy", "quantity": 1.0},
            headers=_auth("user"),
        )
        assert resp.status_code == 403
        assert "trader" in resp.json()["detail"]

    def test_close_position_user_role_rejected(self, client):
        resp = client.delete("/api/trading/positions/POS-1", headers=_auth("user"))
        assert resp.status_code == 403

    def test_close_all_positions_user_role_rejected(self, client):
        resp = client.delete("/api/trading/positions", headers=_auth("user"))
        assert resp.status_code == 403

    def test_emergency_stop_trader_role_rejected(self, client):
        """Traders must not trigger emergency stop — admin only."""
        resp = client.post("/api/trading/emergency-stop", headers=_auth("trader"))
        assert resp.status_code == 403
        assert "admin" in resp.json()["detail"]

    def test_emergency_stop_admin_allowed(self, client, mock_brain):
        resp = client.post("/api/trading/emergency-stop", headers=_auth("admin"))
        assert resp.status_code == 200
        mock_brain.emergency_stop.assert_called_once()
        assert resp.json()["triggered_by"] == "user-123"

    def test_get_positions_user_role_allowed(self, client):
        """Read-only endpoints allow any authenticated user."""
        resp = client.get("/api/trading/positions", headers=_auth("user"))
        assert resp.status_code == 200

    def test_get_account_user_role_allowed(self, client):
        resp = client.get("/api/trading/account", headers=_auth("user"))
        assert resp.status_code == 200

    def test_trader_can_place_order(self, client, mock_broker):
        resp = client.post(
            "/api/trading/order",
            json={"symbol": "XAUUSD", "side": "buy", "quantity": 1.0},
            headers=_auth("trader"),
        )
        assert resp.status_code == 201
        assert resp.json()["order_id"] == "ORD-001"
        mock_broker.place_market_order.assert_called_once()

    def test_admin_can_place_order(self, client):
        """Admin inherits trader privileges."""
        resp = client.post(
            "/api/trading/order",
            json={"symbol": "XAUUSD", "side": "buy", "quantity": 1.0},
            headers=_auth("admin"),
        )
        assert resp.status_code == 201


# ---------------------------------------------------------------------------
# Input validation: symbol allowlist
# ---------------------------------------------------------------------------

class TestSymbolValidation:
    def test_disallowed_symbol_rejected(self, client):
        # validate_order_symbol raises HTTPException(400); FastAPI surfaces it as 400
        resp = client.post(
            "/api/trading/order",
            json={"symbol": "AAPL", "side": "buy", "quantity": 1.0},
            headers=_auth("trader"),
        )
        assert resp.status_code in (400, 422)

    def test_sql_injection_in_symbol_rejected(self, client):
        resp = client.post(
            "/api/trading/order",
            json={"symbol": "'; DROP TABLE trades; --", "side": "buy", "quantity": 1.0},
            headers=_auth("trader"),
        )
        assert resp.status_code == 422

    def test_symbol_case_insensitive(self, client):
        """Lowercase symbol should be normalised and accepted."""
        resp = client.post(
            "/api/trading/order",
            json={"symbol": "xauusd", "side": "buy", "quantity": 1.0},
            headers=_auth("trader"),
        )
        assert resp.status_code == 201

    def test_ohlcv_disallowed_symbol_rejected(self, client):
        resp = client.get("/api/trading/ohlcv/AAPL", headers=_auth("user"))
        assert resp.status_code == 400


# ---------------------------------------------------------------------------
# Input validation: quantity bounds
# ---------------------------------------------------------------------------

class TestQuantityValidation:
    def test_zero_quantity_rejected(self, client):
        resp = client.post(
            "/api/trading/order",
            json={"symbol": "XAUUSD", "side": "buy", "quantity": 0},
            headers=_auth("trader"),
        )
        assert resp.status_code == 422

    def test_negative_quantity_rejected(self, client):
        resp = client.post(
            "/api/trading/order",
            json={"symbol": "XAUUSD", "side": "buy", "quantity": -5.0},
            headers=_auth("trader"),
        )
        assert resp.status_code == 422

    def test_quantity_exceeds_max_rejected(self, client):
        # validate_order_quantity raises HTTPException(400); FastAPI surfaces it as 400
        resp = client.post(
            "/api/trading/order",
            json={"symbol": "XAUUSD", "side": "buy", "quantity": 999.0},
            headers=_auth("trader"),
        )
        assert resp.status_code in (400, 422)

    def test_quantity_at_max_accepted(self, client):
        resp = client.post(
            "/api/trading/order",
            json={"symbol": "XAUUSD", "side": "buy", "quantity": 10.0},
            headers=_auth("trader"),
        )
        assert resp.status_code == 201


# ---------------------------------------------------------------------------
# Input validation: order side / type
# ---------------------------------------------------------------------------

class TestOrderFieldValidation:
    def test_invalid_side_rejected(self, client):
        resp = client.post(
            "/api/trading/order",
            json={"symbol": "XAUUSD", "side": "long", "quantity": 1.0},
            headers=_auth("trader"),
        )
        assert resp.status_code == 422

    def test_invalid_order_type_rejected(self, client):
        resp = client.post(
            "/api/trading/order",
            json={"symbol": "XAUUSD", "side": "buy", "quantity": 1.0, "order_type": "iceberg"},
            headers=_auth("trader"),
        )
        assert resp.status_code == 422

    def test_sell_order_accepted(self, client):
        resp = client.post(
            "/api/trading/order",
            json={"symbol": "EURUSD", "side": "sell", "quantity": 2.0},
            headers=_auth("trader"),
        )
        assert resp.status_code == 201


# ---------------------------------------------------------------------------
# Unit tests for auth helpers
# ---------------------------------------------------------------------------

class TestAuthHelpers:
    def test_role_rank_ordering(self):
        assert _ROLE_RANK["user"] < _ROLE_RANK["trader"]
        assert _ROLE_RANK["trader"] < _ROLE_RANK["admin"]
        assert _ROLE_RANK["admin"] < _ROLE_RANK["superadmin"]

    def test_validate_order_symbol_normalises(self):
        assert validate_order_symbol("xauusd") == "XAUUSD"

    def test_validate_order_symbol_rejects_unknown(self):
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc_info:
            validate_order_symbol("TSLA")
        assert exc_info.value.status_code == 400

    def test_validate_order_quantity_rejects_zero(self):
        from fastapi import HTTPException
        with pytest.raises(HTTPException):
            validate_order_quantity(0.0)

    def test_validate_order_quantity_rejects_over_max(self):
        from fastapi import HTTPException
        with pytest.raises(HTTPException):
            validate_order_quantity(999.0)

    def test_validate_order_quantity_accepts_valid(self):
        assert validate_order_quantity(5.0) == 5.0
