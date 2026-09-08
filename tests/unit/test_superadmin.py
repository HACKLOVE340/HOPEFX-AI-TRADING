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
from contextlib import contextmanager
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


@contextmanager
def _two_factor_verified_override(sa_client):
    """Scope a passing require_superadmin_2fa override to one test.

    sa_client's app-level override only satisfies the base `_require_superadmin`
    dependency, so any route now behind `require_superadmin_2fa` (rollback,
    deploy) 403s under it by default — correctly. Tests for the success path
    opt in here rather than weakening the shared fixture for every other test.
    """
    from api.auth import TokenPayload
    from api.superadmin._shared import require_superadmin_2fa

    app = sa_client.app
    app.dependency_overrides[require_superadmin_2fa] = lambda: TokenPayload(
        sub="test-superadmin", role="superadmin", two_factor_verified=True
    )
    try:
        yield
    finally:
        del app.dependency_overrides[require_superadmin_2fa]


def _ensure_db_tables() -> None:
    """Drop and recreate all SQLAlchemy tables for a clean test schema.

    Uses an isolated in-memory SQLite DB so this module never touches the
    shared hopefx.db file used by other test modules.

    Resets the database.connection._db_manager singleton so that any prior
    test that initialised the manager against a different DB (e.g.
    test_api_exception_leak_fixes.py sets DATABASE_URL=sqlite:///./test_leak_fixes.db)
    does not pollute this module's sessions.
    """
    try:
        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker

        from database.models import Base  # user_models also uses this Base

        # Import user_models to register User/Session/LoginAttempt with Base
        import database.user_models  # pylint: disable=unused-import

        # Use a unique in-memory DB per test module to avoid cross-module pollution
        mem_engine = create_engine(
            "sqlite:///file:superadmin_test?mode=memory&cache=shared&uri=true",
            connect_args={"check_same_thread": False},
        )
        if Base is not None:
            Base.metadata.drop_all(mem_engine)
            Base.metadata.create_all(mem_engine)

        # Reset the global _db_manager singleton so SessionLocal binds to our
        # isolated in-memory DB, not whatever DB a prior test module initialised.
        import database.connection as _db_conn

        _db_conn._db_manager = None  # type: ignore[attr-defined]

        # Re-initialise the manager with our isolated engine
        from database.connection import DatabaseManager

        new_manager = DatabaseManager.__new__(DatabaseManager)
        new_manager._engine = mem_engine
        new_manager._session_factory = sessionmaker(bind=mem_engine)
        new_manager._metrics = None  # type: ignore[attr-defined]
        _db_conn._db_manager = new_manager  # type: ignore[attr-defined]

        # Also patch the module-level engine proxy
        try:
            _db_conn.engine = mem_engine  # type: ignore[attr-defined]
        except Exception:
            pass

        # Patch SessionLocal in api.superadmin.users directly so it uses our engine
        try:
            import api.superadmin.users as _users_mod

            _users_mod.SessionLocal = sessionmaker(bind=mem_engine)  # type: ignore[attr-defined]
        except Exception:
            pass

    except Exception:
        # Fall back to the shared file DB — drop/recreate for a clean schema
        try:
            from database.connection import engine
            from database.models import Base

            import database.user_models  # noqa: F401

            if Base is not None and engine is not None:
                Base.metadata.drop_all(engine)
                Base.metadata.create_all(engine)
        except Exception:
            pass


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

    def test_rollback_model_403_without_2fa(self, sa_client):
        # rollback() bypasses quality gates to force-promote a previous model
        # version into live trading. A superadmin token with no TOTP claim
        # must not reach it — the sa_client fixture's default override never
        # sets two_factor_verified, so this is the "stolen token" case.
        # get_registry is mocked even though the request should be blocked
        # before reaching it: if the gate ever regresses, this must not fall
        # through to mutating the real committed ml/saved_models/registry.json.
        with (
            patch("api.admin.log_activity"),
            patch("ml.model_registry.get_registry", side_effect=AssertionError("must not reach the registry")),
        ):
            resp = sa_client.post("/api/superadmin/ml/rollback/xgboost")
        assert resp.status_code == 403

    def test_rollback_model_200(self, sa_client):
        # Mock the registry so the rollback always finds a staging candidate,
        # regardless of the real registry state on disk.
        mock_registry = MagicMock()
        mock_registry._load.return_value = {
            "active_version": "xgb_v2",
            "versions": {
                "xgb_v2": {"state": "active", "registered_at": "2026-05-01T00:00:00+00:00"},
                "xgb_v1": {"state": "staging", "registered_at": "2026-04-01T00:00:00+00:00"},
            },
        }
        mock_registry.rollback = MagicMock()
        with (
            _two_factor_verified_override(sa_client),
            patch("api.admin.log_activity"),
            patch("ml.model_registry.get_registry", return_value=mock_registry),
        ):
            resp = sa_client.post("/api/superadmin/ml/rollback/xgboost")
        assert resp.status_code == 200

    def test_deploy_model_403_without_2fa(self, sa_client):
        # Mocked for the same reason as the rollback case above: a regressed
        # gate must not fall through to mutating the real registry on disk.
        with (
            patch("api.admin.log_activity"),
            patch("ml.model_registry.get_registry", side_effect=AssertionError("must not reach the registry")),
        ):
            resp = sa_client.post("/api/superadmin/ml/deploy", json={"model": "xgboost", "version": "v3"})
        assert resp.status_code == 403

    def test_deploy_model_200(self, sa_client):
        mock_registry = MagicMock()
        mock_registry.promote = MagicMock()
        with (
            _two_factor_verified_override(sa_client),
            patch("api.admin.log_activity"),
            patch("ml.model_registry.get_registry", return_value=mock_registry),
        ):
            resp = sa_client.post("/api/superadmin/ml/deploy", json={"model": "xgboost", "version": "v3"})
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# HTTP endpoints — dashboard HTML
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestBackupTriggerEndpoint:
    """POST /api/superadmin/system-health/backups/trigger.

    This used to run its own ad-hoc pg_dump/shutil copy instead of the
    verified database/backup.py::run_backup() path from Phase R1, and its
    except block forced status="completed" on ANY exception — so a missing
    pg_dump binary, a permission error, or a timeout all reported success
    with size_mb=0.0 and a location that was never written. §B2 item 14 in
    docs/ai/MASTER_OUTSTANDING.md names the unverified-path half of this;
    this covers the fail-open half found while fixing it.
    """

    def test_a_failed_backup_is_reported_as_failed_not_completed(self, sa_client):
        with (
            patch("database.backup.run_backup", side_effect=RuntimeError("DATABASE_URL is not set")),
            patch("api.superadmin.system_health._log_superadmin_action"),
        ):
            resp = sa_client.post("/api/superadmin/system-health/backups/trigger", json={"type": "incremental"})
        assert resp.status_code == 200
        body = resp.json()
        assert body["backup"]["status"] == "failed"
        assert body["ok"] is False
        assert body["backup"]["size_mb"] == 0.0

    def test_a_successful_backup_is_verified_and_reports_the_real_path(self, sa_client, tmp_path):
        fake_backup = tmp_path / "hopefx_20260908.sql.gz"
        fake_backup.write_bytes(b"not a real dump, just needs to exist")
        fake_report = MagicMock(bytes_uncompressed=2 * 1024 * 1024)
        with (
            patch("database.backup.run_backup", return_value=fake_backup),
            patch("database.restore.verify_backup", return_value=fake_report),
            patch("api.superadmin.system_health._log_superadmin_action"),
        ):
            resp = sa_client.post("/api/superadmin/system-health/backups/trigger", json={"type": "incremental"})
        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        assert body["backup"]["status"] == "completed"
        assert body["backup"]["location"] == str(fake_backup)
        assert body["backup"]["size_mb"] == 2.0

    def test_an_unverifiable_backup_is_reported_as_failed(self, sa_client, tmp_path):
        # run_backup() succeeded but the artefact it wrote does not survive
        # verify_backup() (e.g. the WAL-sidecar defect Phase R1 found) — the
        # trigger must not call that success either.
        fake_backup = tmp_path / "hopefx_20260908.sql.gz"
        fake_backup.write_bytes(b"not a real dump, just needs to exist")
        with (
            patch("database.backup.run_backup", return_value=fake_backup),
            patch("database.restore.verify_backup", side_effect=RuntimeError("backup contains no tables")),
            patch("api.superadmin.system_health._log_superadmin_action"),
        ):
            resp = sa_client.post("/api/superadmin/system-health/backups/trigger", json={"type": "incremental"})
        assert resp.status_code == 200
        body = resp.json()
        assert body["backup"]["status"] == "failed"
        assert body["ok"] is False


@pytest.mark.unit
class TestDashboardEndpoint:
    def test_dashboard_returns_html(self, sa_client):
        resp = sa_client.get("/api/superadmin/")
        assert resp.status_code == 200
        assert "text/html" in resp.headers.get("content-type", "")
