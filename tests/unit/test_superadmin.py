# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
Tests for api/superadmin.py

Covers: Pydantic models, _load_platform_config, _save_platform_config,
        _load_engine_config, _log_superadmin_action, _iso helper,
        and all HTTP endpoints via TestClient with auth bypass.
"""

import json
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

UTC = timezone.utc


# ---------------------------------------------------------------------------
# Auth bypass helpers
# ---------------------------------------------------------------------------


def _make_superadmin_app() -> FastAPI:
    """Create a minimal FastAPI app with the superadmin router and auth bypassed."""
    from api.auth import TokenPayload, require_role
    from api.superadmin import router

    app = FastAPI()
    app.include_router(router)

    # Bypass auth: replace the superadmin dependency with a no-op
    superadmin_dep = require_role("superadmin")
    app.dependency_overrides[superadmin_dep] = lambda: TokenPayload(sub="test-superadmin", role="superadmin")
    return app


def _ensure_db_tables() -> None:
    """Drop and recreate all SQLAlchemy tables for a clean test schema.

    drop_all + create_all is necessary because SQLite's create_all() does not
    add new columns to existing tables.  When the ORM model gains a new column
    (e.g. kyc_submitted_at) the stale hopefx.db would otherwise cause 500
    errors on every endpoint that touches the users table.
    """
    try:
        from database.connection import engine
        from database.models import Base  # user_models also uses this Base

        # Import user_models to register User/Session/LoginAttempt with Base
        import database.user_models  # noqa: F401  # pylint: disable=unused-import

        if Base is not None and engine is not None:
            Base.metadata.drop_all(engine)
            Base.metadata.create_all(engine)
    except Exception:
        pass  # non-fatal; DB may be unavailable in this environment


@pytest.fixture(scope="module")
def sa_client():
    _ensure_db_tables()
    app = _make_superadmin_app()
    return TestClient(app, raise_server_exceptions=True)


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestSuperadminModels:
    def test_update_user_body_all_optional(self):
        from api.superadmin import UpdateUserBody

        body = UpdateUserBody()
        assert body.username is None
        assert body.email is None
        assert body.status is None

    def test_update_user_body_with_values(self):
        from api.superadmin import UpdateUserBody

        body = UpdateUserBody(username="alice", email="alice@example.com", status="active")
        assert body.username == "alice"

    def test_set_role_body(self):
        from api.superadmin import SetRoleBody

        body = SetRoleBody(role="admin")
        assert body.role == "admin"

    def test_set_plan_body(self):
        from api.superadmin import SetPlanBody

        body = SetPlanBody(plan="pro")
        assert body.plan == "pro"

    def test_ban_user_body_default_reason(self):
        from api.superadmin import BanUserBody

        body = BanUserBody()
        assert body.reason == "Policy violation"

    def test_ban_user_body_custom_reason(self):
        from api.superadmin import BanUserBody

        body = BanUserBody(reason="Fraud")
        assert body.reason == "Fraud"

    def test_maintenance_body(self):
        from api.superadmin import MaintenanceBody

        body = MaintenanceBody(enabled=True, message="Down for maintenance")
        assert body.enabled is True
        assert body.message == "Down for maintenance"

    def test_broadcast_body_defaults(self):
        from api.superadmin import BroadcastBody

        body = BroadcastBody(title="Alert", body="Something happened")
        assert body.type == "info"

    def test_platform_config_body_all_optional(self):
        from api.superadmin import PlatformConfigBody

        body = PlatformConfigBody()
        assert body.platform_name is None
        assert body.max_users is None

    def test_platform_config_body_with_values(self):
        from api.superadmin import PlatformConfigBody

        body = PlatformConfigBody(platform_name="MyPlatform", max_users=500)
        assert body.platform_name == "MyPlatform"
        assert body.max_users == 500

    def test_kill_switch_body(self):
        from api.superadmin import KillSwitchBody

        body = KillSwitchBody(enabled=True)
        assert body.enabled is True

    def test_engine_config_body_all_optional(self):
        from api.superadmin import EngineConfigBody

        body = EngineConfigBody()
        assert body.paper_trading_mode is None

    def test_set_feature_flag_body(self):
        from api.superadmin import SetFeatureFlagBody

        body = SetFeatureFlagBody(enabled=True)
        assert body.enabled is True

    def test_ml_control_body(self):
        from api.superadmin import MLControlBody

        body = MLControlBody(action="start")
        assert body.action == "start"

    def test_deploy_model_body(self):
        from api.superadmin import DeployModelBody

        body = DeployModelBody(model="xgboost", version="v2")
        assert body.model == "xgboost"
        assert body.version == "v2"


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestHelperFunctions:
    def test_iso_with_datetime(self):
        from api.superadmin import _iso

        dt = datetime(2025, 1, 15, 10, 30, 0, tzinfo=UTC)
        result = _iso(dt)
        assert "2025-01-15" in result

    def test_iso_with_none(self):
        from api.superadmin import _iso

        assert _iso(None) is None

    def test_load_platform_config_returns_defaults_when_no_store(self):
        from api.superadmin import _PLATFORM_CONFIG_DEFAULTS, _load_platform_config

        with patch("api.superadmin.platform._get_config_store", return_value=None):
            cfg = _load_platform_config()
        assert cfg["platform_name"] == _PLATFORM_CONFIG_DEFAULTS["platform_name"]
        assert cfg["max_users"] == _PLATFORM_CONFIG_DEFAULTS["max_users"]

    def test_load_platform_config_merges_stored_values(self):
        from api.superadmin import _load_platform_config

        mock_store = MagicMock()
        mock_store.get.return_value = json.dumps({"platform_name": "Custom", "max_users": 999})
        with patch("api.superadmin.platform._get_config_store", return_value=mock_store):
            cfg = _load_platform_config()
        assert cfg["platform_name"] == "Custom"
        assert cfg["max_users"] == 999
        # Defaults for unset keys should still be present
        assert "support_email" in cfg

    def test_load_platform_config_handles_invalid_json(self):
        from api.superadmin import _PLATFORM_CONFIG_DEFAULTS, _load_platform_config

        mock_store = MagicMock()
        mock_store.get.return_value = "not valid json {{{"
        with patch("api.superadmin.platform._get_config_store", return_value=mock_store):
            cfg = _load_platform_config()
        # Falls back to defaults
        assert cfg == dict(_PLATFORM_CONFIG_DEFAULTS)

    def test_save_platform_config_calls_store(self):
        from api.superadmin import _save_platform_config

        mock_store = MagicMock()
        with patch("api.superadmin.platform._get_config_store", return_value=mock_store):
            _save_platform_config({"platform_name": "Test"})
        mock_store.set.assert_called_once()
        _, value = mock_store.set.call_args[0]
        assert "platform_name" in value

    def test_save_platform_config_noop_when_no_store(self):
        from api.superadmin import _save_platform_config

        with patch("api.superadmin.platform._get_config_store", return_value=None):
            # Should not raise
            _save_platform_config({"platform_name": "Test"})

    def test_load_engine_config_returns_defaults_when_no_store(self):
        from api.superadmin import _load_engine_config

        with (
            patch("api.superadmin.platform._get_config_store", return_value=None),
            patch("api.admin._get_risk_settings", side_effect=ImportError),
        ):
            cfg = _load_engine_config()
        assert "paper_trading_mode" in cfg
        assert "kill_switch_active" in cfg

    def test_log_superadmin_action_does_not_raise(self):
        from api.auth import TokenPayload
        from api.superadmin import _log_superadmin_action

        user = TokenPayload(sub="admin-user", role="superadmin")
        with patch("api.admin.log_activity"):
            _log_superadmin_action(user, "test_action", "detail here")


# ---------------------------------------------------------------------------
# HTTP endpoints — overview
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestOverviewEndpoint:
    def test_get_overview_200(self, sa_client):
        resp = sa_client.get("/api/superadmin/overview")
        assert resp.status_code == 200

    def test_get_overview_required_keys(self, sa_client):
        resp = sa_client.get("/api/superadmin/overview")
        body = resp.json()
        for key in ("total_users", "system_health", "engine_status", "kill_switch_active"):
            assert key in body, f"Missing key: {key}"

    def test_get_overview_system_health_valid(self, sa_client):
        resp = sa_client.get("/api/superadmin/overview")
        assert resp.json()["system_health"] in ("healthy", "degraded", "critical")

    def test_get_overview_unauthenticated_returns_403(self):
        """Without auth bypass, unauthenticated requests should be rejected."""
        from api.superadmin import router

        bare_app = FastAPI()
        bare_app.include_router(router)
        client = TestClient(bare_app, raise_server_exceptions=False)
        resp = client.get("/api/superadmin/overview")
        assert resp.status_code in (401, 403, 422)


# ---------------------------------------------------------------------------
# HTTP endpoints — platform config
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestPlatformConfigEndpoints:
    def test_get_platform_config_200(self, sa_client):
        with patch("api.superadmin.platform._get_config_store", return_value=None):
            resp = sa_client.get("/api/superadmin/platform/config")
        assert resp.status_code == 200

    def test_get_platform_config_has_defaults(self, sa_client):
        with patch("api.superadmin.platform._get_config_store", return_value=None):
            resp = sa_client.get("/api/superadmin/platform/config")
        body = resp.json()
        assert "platform_name" in body
        assert "max_users" in body

    def test_patch_platform_config_200(self, sa_client):
        mock_store = MagicMock()
        mock_store.get.return_value = None
        with (
            patch("api.superadmin.platform._get_config_store", return_value=mock_store),
            patch("api.admin.log_activity"),
        ):
            resp = sa_client.patch(
                "/api/superadmin/platform/config",
                json={"platform_name": "Updated Platform", "max_users": 5000},
            )
        assert resp.status_code == 200
        assert resp.json()["ok"] is True

    def test_patch_platform_config_saves_to_store(self, sa_client):
        mock_store = MagicMock()
        mock_store.get.return_value = None
        with (
            patch("api.superadmin.platform._get_config_store", return_value=mock_store),
            patch("api.admin.log_activity"),
        ):
            sa_client.patch(
                "/api/superadmin/platform/config",
                json={"platform_name": "NewName"},
            )
        mock_store.set.assert_called()

    def test_post_maintenance_mode_enable(self, sa_client):
        mock_store = MagicMock()
        mock_store.get.return_value = None
        with (
            patch("api.superadmin.platform._get_config_store", return_value=mock_store),
            patch("api.admin.log_activity"),
        ):
            resp = sa_client.post(
                "/api/superadmin/platform/maintenance",
                json={"enabled": True, "message": "Scheduled maintenance"},
            )
        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        assert body["maintenance_mode"] is True

    def test_post_maintenance_mode_disable(self, sa_client):
        mock_store = MagicMock()
        mock_store.get.return_value = None
        with (
            patch("api.superadmin.platform._get_config_store", return_value=mock_store),
            patch("api.admin.log_activity"),
        ):
            resp = sa_client.post(
                "/api/superadmin/platform/maintenance",
                json={"enabled": False},
            )
        assert resp.status_code == 200
        assert resp.json()["maintenance_mode"] is False

    def test_post_broadcast_200(self, sa_client):
        with patch("api.admin.log_activity"):
            resp = sa_client.post(
                "/api/superadmin/platform/broadcast",
                json={"title": "Test Alert", "body": "This is a test", "type": "warning"},
            )
        assert resp.status_code == 200
        assert resp.json()["ok"] is True


# ---------------------------------------------------------------------------
# HTTP endpoints — engine
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestEngineEndpoints:
    def test_get_engine_status_200(self, sa_client):
        with (
            patch("api.superadmin.platform._get_config_store", return_value=None),
            patch("api.admin._get_risk_settings", return_value={}),
        ):
            resp = sa_client.get("/api/superadmin/engine/status")
        assert resp.status_code == 200
        body = resp.json()
        assert "status" in body
        assert "kill_switch_active" in body

    def test_get_engine_config_200(self, sa_client):
        with (
            patch("api.superadmin.platform._get_config_store", return_value=None),
            patch("api.admin._get_risk_settings", return_value={}),
        ):
            resp = sa_client.get("/api/superadmin/engine/config")
        assert resp.status_code == 200
        body = resp.json()
        assert "paper_trading_mode" in body

    def test_patch_engine_config_200(self, sa_client):
        mock_store = MagicMock()
        mock_store.get.return_value = None
        with (
            patch("api.superadmin.platform._get_config_store", return_value=mock_store),
            patch("api.admin._get_risk_settings", return_value={}),
            patch("api.admin.log_activity"),
            patch("api.admin.apply_persisted_risk_settings", side_effect=ImportError),
        ):
            resp = sa_client.patch(
                "/api/superadmin/engine/config",
                json={"paper_trading_mode": False, "max_open_positions": 10},
            )
        assert resp.status_code == 200
        assert resp.json()["ok"] is True

    def test_post_kill_switch_enable(self, sa_client):
        mock_store = MagicMock()
        mock_store.get.return_value = None
        with (
            patch("api.superadmin.platform._get_config_store", return_value=mock_store),
            patch("api.admin._get_risk_settings", return_value={}),
            patch("api.admin.log_activity"),
        ):
            resp = sa_client.post(
                "/api/superadmin/engine/kill-switch",
                json={"enabled": True, "reason": "Test"},
            )
        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        assert body["kill_switch_active"] is True

    def test_post_kill_switch_disable(self, sa_client):
        mock_store = MagicMock()
        mock_store.get.return_value = None
        with (
            patch("api.superadmin.platform._get_config_store", return_value=mock_store),
            patch("api.admin._get_risk_settings", return_value={}),
            patch("api.admin.log_activity"),
        ):
            resp = sa_client.post(
                "/api/superadmin/engine/kill-switch",
                json={"enabled": False},
            )
        assert resp.status_code == 200
        assert resp.json()["kill_switch_active"] is False

    def test_post_engine_pause(self, sa_client):
        mock_store = MagicMock()
        mock_store.get.return_value = None
        with (
            patch("api.superadmin.platform._get_config_store", return_value=mock_store),
            patch("api.admin._get_risk_settings", return_value={}),
            patch("api.admin.log_activity"),
        ):
            resp = sa_client.post(
                "/api/superadmin/engine/pause",
                json={"reason": "Manual pause"},
            )
        assert resp.status_code == 200

    def test_post_engine_resume(self, sa_client):
        mock_store = MagicMock()
        mock_store.get.return_value = None
        with (
            patch("api.superadmin.platform._get_config_store", return_value=mock_store),
            patch("api.admin._get_risk_settings", return_value={}),
            patch("api.admin.log_activity"),
        ):
            resp = sa_client.post("/api/superadmin/engine/resume")
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# HTTP endpoints — users
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestUserEndpoints:
    def test_list_users_200(self, sa_client):
        resp = sa_client.get("/api/superadmin/users")
        assert resp.status_code == 200
        body = resp.json()
        assert "users" in body
        assert "total" in body

    def test_list_users_pagination_params(self, sa_client):
        resp = sa_client.get("/api/superadmin/users?page=1&page_size=10")
        assert resp.status_code == 200

    def test_get_user_not_found(self, sa_client):
        resp = sa_client.get("/api/superadmin/users/nonexistent-user-id")
        assert resp.status_code in (200, 404)

    def test_delete_user_not_found(self, sa_client):
        resp = sa_client.delete("/api/superadmin/users/nonexistent-user-id")
        assert resp.status_code in (200, 404)

    def test_set_user_role(self, sa_client):
        with patch("api.admin.log_activity"):
            resp = sa_client.patch(
                "/api/superadmin/users/some-user-id/role",
                json={"role": "admin"},
            )
        assert resp.status_code in (200, 404)

    def test_ban_user(self, sa_client):
        with patch("api.admin.log_activity"):
            resp = sa_client.post(
                "/api/superadmin/users/some-user-id/ban",
                json={"reason": "Violation"},
            )
        assert resp.status_code in (200, 404)

    def test_unban_user(self, sa_client):
        with patch("api.admin.log_activity"):
            resp = sa_client.post("/api/superadmin/users/some-user-id/unban")
        assert resp.status_code in (200, 404)


# ---------------------------------------------------------------------------
# HTTP endpoints — ML
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestMLEndpoints:
    def test_get_ml_status_200(self, sa_client):
        resp = sa_client.get("/api/superadmin/ml/status")
        assert resp.status_code == 200

    def test_list_ml_models_200(self, sa_client):
        resp = sa_client.get("/api/superadmin/ml/models")
        assert resp.status_code == 200
        body = resp.json()
        assert "models" in body

    def test_get_ml_metrics_200(self, sa_client):
        resp = sa_client.get("/api/superadmin/ml/metrics")
        assert resp.status_code == 200

    def test_retrain_model_200(self, sa_client):
        with patch("api.admin.log_activity"):
            resp = sa_client.post("/api/superadmin/ml/retrain/xgboost")
        assert resp.status_code == 200
        body = resp.json()
        assert "status" in body

    def test_rollback_model_200(self, sa_client):
        with patch("api.admin.log_activity"):
            resp = sa_client.post("/api/superadmin/ml/rollback/xgboost")
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# HTTP endpoints — dashboard HTML
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestDashboardEndpoint:
    def test_dashboard_returns_html(self, sa_client):
        resp = sa_client.get("/api/superadmin/")
        assert resp.status_code == 200
        assert "text/html" in resp.headers.get("content-type", "")
