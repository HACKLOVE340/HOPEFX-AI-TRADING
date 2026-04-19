# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
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

import importlib.util
import os
import pathlib
import sys
import time
from unittest.mock import AsyncMock, MagicMock

import jwt
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

# Set env vars before any project imports so module-level reads pick them up
os.environ["SECURITY_JWT_SECRET"] = "test-only-jwt-secret-key-minimum-32-chars!!"  # pragma: allowlist secret
os.environ["ALLOWED_SYMBOLS"] = "XAUUSD,EURUSD,BTCUSD"
os.environ["MAX_ORDER_QUANTITY"] = "10.0"
# Ensure kill switch is never active during tests regardless of persisted state.
# The flag and state files may be left by integration runs or backtests.
os.environ["HOPEFX_KILL_SWITCH"] = "0"
_KS_ROOT = pathlib.Path(__file__).parents[2]
for _ks_artifact in ("kill_switch.flag", "kill_switch.state.json"):
    _p = _KS_ROOT / _ks_artifact
    if _p.exists():
        _p.unlink()

_API_DIR = pathlib.Path(__file__).parents[2] / "api"


def _load_module(name: str, path: pathlib.Path):
    """Load a single .py file as a module, bypassing package __init__.

    If the module is already in sys.modules (e.g. imported by an earlier test
    in the full suite), reuse it. Replacing it would create a second copy of
    every function object, breaking dependency_overrides in other tests that
    captured the original references.
    """
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


# Register a minimal 'api' package stub so submodule dotted names resolve.
# If the real 'api' package is already in sys.modules (full test suite run),
# we reuse it so that patch("api.auth._decode_token") works in later tests.
if "api" not in sys.modules:
    import types

    _api_pkg = types.ModuleType("api")
    _api_pkg.__path__ = [str(_API_DIR)]
    _api_pkg.__package__ = "api"
    sys.modules["api"] = _api_pkg

# Load auth first (trading imports from it).
# Always set the loaded module as an attribute on the api package so that
# patch("api.auth._decode_token") resolves correctly in subsequent tests.
auth_module = _load_module("api.auth", _API_DIR / "auth.py")
sys.modules["api"].auth = auth_module  # type: ignore[attr-defined]
trading_module = _load_module("api.trading", _API_DIR / "trading.py")

from api.auth import _ROLE_RANK, validate_order_quantity, validate_order_symbol

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
        "type": "access",
        "iat": now,
        "exp": now - 10 if expired else now + 3600,
    }
    return jwt.encode(payload, _SECRET, algorithm="HS256")


def _auth(role: str = "trader") -> dict[str, str]:
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
def app(mock_broker, mock_brain, tmp_path, monkeypatch):
    # Re-pin the secret at fixture time (not just module level) so it stays
    # correct even when other test modules change SECURITY_JWT_SECRET between
    # collection and execution.
    os.environ["SECURITY_JWT_SECRET"] = _SECRET

    state = MagicMock()
    state.broker = mock_broker
    state.brain = mock_brain
    state.price_engine = None
    # Disable risk/compliance/prop-firm gates so they don't interfere with auth tests
    state.risk_manager = None
    state.compliance_manager = None
    state.prop_firm_manager = None
    trading_module.set_state(state)

    # Inject a fresh, inactive KillSwitch so that any kill switch activated by
    # a previous test module (e.g. test_risk.py triggering a drawdown halt)
    # does not bleed into these auth tests via the cached singleton.
    from kill_switch import KillSwitch

    fresh_ks = KillSwitch(flag_file=tmp_path / "ks_auth_test.flag")
    trading_module._set_kill_switch(fresh_ks)

    # Prevent _get_redis_client() from attempting a real TCP connection, which
    # blocks indefinitely when Redis is not running in the test environment.
    monkeypatch.setattr(trading_module, "_get_redis_client", lambda: None)

    # Reset in-memory rate-limit cache so prior test requests don't cause 429s.
    trading_module._reset_order_rl_cache()

    application = FastAPI()
    application.include_router(router)

    yield application

    # Restore to None so other test modules get a clean slate.
    trading_module._set_kill_switch(None)
    trading_module._reset_order_rl_cache()


@pytest.fixture()
def client(app):
    return TestClient(app, raise_server_exceptions=False)


# ---------------------------------------------------------------------------
# Authentication: missing / invalid / expired tokens
# ---------------------------------------------------------------------------


class TestAuthRejection:
    def test_place_order_no_token(self, client):
        # HTTPBearer(auto_error=True) returns 403 when Authorization header is absent
        resp = client.post(
            "/api/trading/order",
            json={"symbol": "XAUUSD", "side": "buy", "quantity": 1.0},
        )
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
            json={
                "symbol": "XAUUSD",
                "side": "buy",
                "quantity": 1.0,
                "order_type": "iceberg",
            },
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
