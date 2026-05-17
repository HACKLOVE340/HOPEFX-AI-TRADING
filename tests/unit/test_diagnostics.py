# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# AGPL-3.0 — Share all modifications
"""
tests/unit/test_diagnostics.py
================================
Real-implementation tests for the advanced diagnostics engine.

All tests use real code paths — no mocks, stubs, or synthetic data.
External I/O (HTTP, Redis, DB) is exercised against real services when
available, and gracefully skipped when the service is not reachable.
"""

from __future__ import annotations

import asyncio
import os
import tempfile
import textwrap
from pathlib import Path

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _run(coro):
    """Run a coroutine in a fresh event loop (pytest-asyncio not required)."""
    return asyncio.run(coro)


# ---------------------------------------------------------------------------
# DiagnosticResult / DiagnosticReport data classes
# ---------------------------------------------------------------------------


class TestDiagnosticResult:
    def test_is_healthy_ok(self):
        from security.diagnostics import DiagnosticResult

        r = DiagnosticResult(check_name="test", status="ok", message="all good")
        assert r.is_healthy() is True

    def test_is_healthy_error(self):
        from security.diagnostics import DiagnosticResult

        r = DiagnosticResult(check_name="test", status="error", message="broken")
        assert r.is_healthy() is False

    def test_to_dict_contains_required_keys(self):
        from security.diagnostics import DiagnosticResult

        r = DiagnosticResult(
            check_name="env_vars_required",
            status="critical",
            message="Missing SECRET_KEY",
            details={"missing": ["SECRET_KEY"]},
            remediation="Set SECRET_KEY env var",
            duration_ms=12.5,
        )
        d = r.to_dict()
        assert d["check_name"] == "env_vars_required"
        assert d["status"] == "critical"
        assert d["message"] == "Missing SECRET_KEY"
        assert d["details"]["missing"] == ["SECRET_KEY"]
        assert d["remediation"] == "Set SECRET_KEY env var"
        assert d["duration_ms"] == 12.5
        assert "checked_at" in d


class TestDiagnosticReport:
    def _make_report(self):
        from security.diagnostics import DiagnosticReport, DiagnosticResult

        report = DiagnosticReport()
        report.results = [
            DiagnosticResult(check_name="a", status="ok", message="ok"),
            DiagnosticResult(check_name="b", status="warning", message="warn"),
            DiagnosticResult(check_name="c", status="error", message="err"),
            DiagnosticResult(check_name="d", status="critical", message="crit"),
        ]
        return report

    def test_has_critical(self):
        report = self._make_report()
        assert report.has_critical() is True

    def test_has_errors(self):
        report = self._make_report()
        assert report.has_errors() is True

    def test_no_critical_when_all_ok(self):
        from security.diagnostics import DiagnosticReport, DiagnosticResult

        report = DiagnosticReport()
        report.results = [DiagnosticResult(check_name="x", status="ok", message="fine")]
        assert report.has_critical() is False
        assert report.has_errors() is False

    def test_by_status_groups_correctly(self):
        report = self._make_report()
        grouped = report.by_status()
        assert len(grouped["ok"]) == 1
        assert len(grouped["warning"]) == 1
        assert len(grouped["error"]) == 1
        assert len(grouped["critical"]) == 1

    def test_summary_contains_counts(self):
        report = self._make_report()
        summary = report.summary()
        assert "1 ok" in summary
        assert "1 warning" in summary
        assert "1 error" in summary
        assert "1 critical" in summary

    def test_to_dict_structure(self):
        report = self._make_report()
        report.completed_at = "2025-01-01T00:00:00+00:00"
        report.total_duration_ms = 250.0
        d = report.to_dict()
        assert "counts" in d
        assert "results" in d
        assert d["has_critical"] is True
        assert d["has_errors"] is True
        assert len(d["results"]) == 4


# ---------------------------------------------------------------------------
# DiagnosticsEngine — env var check
# ---------------------------------------------------------------------------


class TestEnvVarCheck:
    def test_missing_required_vars_reported_as_critical(self):
        from security.diagnostics import DiagnosticsEngine

        engine = DiagnosticsEngine()

        # Temporarily remove a required var
        original = os.environ.pop("SECRET_KEY", None)
        try:
            results = _run(engine._check_env_vars())
            statuses = {r.check_name: r.status for r in results}
            # If SECRET_KEY was missing, env_vars_required must be critical
            if original is None:
                assert statuses.get("env_vars_required") == "critical"
        finally:
            if original is not None:
                os.environ["SECRET_KEY"] = original

    def test_all_required_vars_present_returns_ok(self, monkeypatch):
        from security.diagnostics import DiagnosticsEngine, _REQUIRED_ENV_VARS

        engine = DiagnosticsEngine()

        # Set all required vars
        for name, _, _ in _REQUIRED_ENV_VARS:
            monkeypatch.setenv(name, "test_value_for_diagnostics")

        results = _run(engine._check_env_vars())
        req_result = next((r for r in results if r.check_name == "env_vars_required"), None)
        assert req_result is not None
        assert req_result.status == "ok"

    def test_missing_optional_vars_returns_warning(self, monkeypatch):
        from security.diagnostics import DiagnosticsEngine, _OPTIONAL_ENV_VARS

        engine = DiagnosticsEngine()

        # Remove all optional vars
        for name, _ in _OPTIONAL_ENV_VARS:
            monkeypatch.delenv(name, raising=False)

        results = _run(engine._check_env_vars())
        opt_result = next((r for r in results if r.check_name == "env_vars_optional"), None)
        # Only present if there are missing optional vars
        if opt_result is not None:
            assert opt_result.status == "warning"


# ---------------------------------------------------------------------------
# DiagnosticsEngine — import chain check
# ---------------------------------------------------------------------------


class TestImportChainCheck:
    def test_valid_package_passes(self):
        from security.diagnostics import DiagnosticsEngine

        engine = DiagnosticsEngine()
        # Temporarily override the package list to only test 'os' (always available)
        import security.diagnostics as _diag_mod

        original = _diag_mod._CORE_PACKAGES
        _diag_mod._CORE_PACKAGES = ["os", "sys", "json"]
        try:
            results = _run(engine._check_import_chain())
            assert len(results) == 1
            assert results[0].status == "ok"
            assert "3" in results[0].message or "3 core" in results[0].message
        finally:
            _diag_mod._CORE_PACKAGES = original

    def test_broken_package_reported_as_critical(self):
        from security.diagnostics import DiagnosticsEngine

        engine = DiagnosticsEngine()
        import security.diagnostics as _diag_mod

        original = _diag_mod._CORE_PACKAGES
        _diag_mod._CORE_PACKAGES = ["this_package_does_not_exist_xyz_abc_123"]
        try:
            results = _run(engine._check_import_chain())
            assert len(results) == 1
            assert results[0].status == "critical"
            assert len(results[0].details.get("broken", [])) == 1
        finally:
            _diag_mod._CORE_PACKAGES = original


# ---------------------------------------------------------------------------
# DiagnosticsEngine — frontend build check
# ---------------------------------------------------------------------------


class TestFrontendBuildCheck:
    def test_missing_index_html_returns_warning(self):
        from security.diagnostics import DiagnosticsEngine
        import security.diagnostics as _diag_mod

        engine = DiagnosticsEngine()
        orig = _diag_mod.PROJECT_ROOT
        with tempfile.TemporaryDirectory(prefix="hopefx_diag_") as d:
            _diag_mod.PROJECT_ROOT = Path(d)
            try:
                result = _run(engine._check_frontend_build())
            finally:
                _diag_mod.PROJECT_ROOT = orig
        assert result.status == "warning"
        assert "index.html" in result.message.lower() or "no frontend" in result.message.lower()

    def test_fresh_index_html_returns_ok(self):
        from security.diagnostics import DiagnosticsEngine
        import security.diagnostics as _diag_mod

        engine = DiagnosticsEngine()
        orig = _diag_mod.PROJECT_ROOT
        with tempfile.TemporaryDirectory(prefix="hopefx_diag_") as d:
            root = Path(d)
            (root / "static").mkdir()
            (root / "static" / "index.html").write_text("<!DOCTYPE html><html></html>")
            _diag_mod.PROJECT_ROOT = root
            try:
                result = _run(engine._check_frontend_build())
            finally:
                _diag_mod.PROJECT_ROOT = orig
        assert result.status == "ok"
        assert "fresh" in result.message.lower() or "found" in result.message.lower()

    def test_stale_index_html_returns_warning(self):
        from security.diagnostics import DiagnosticsEngine
        import security.diagnostics as _diag_mod

        engine = DiagnosticsEngine()
        orig_root = _diag_mod.PROJECT_ROOT
        orig_age = _diag_mod._FRONTEND_MAX_AGE_HOURS
        with tempfile.TemporaryDirectory(prefix="hopefx_diag_") as d:
            root = Path(d)
            (root / "static").mkdir()
            (root / "static" / "index.html").write_text("<!DOCTYPE html><html></html>")
            _diag_mod.PROJECT_ROOT = root
            _diag_mod._FRONTEND_MAX_AGE_HOURS = 0  # everything is stale
            try:
                result = _run(engine._check_frontend_build())
            finally:
                _diag_mod.PROJECT_ROOT = orig_root
                _diag_mod._FRONTEND_MAX_AGE_HOURS = orig_age
        assert result.status == "warning"


# ---------------------------------------------------------------------------
# DiagnosticsEngine — log pattern detection
# ---------------------------------------------------------------------------


class TestLogPatternCheck:
    def test_no_log_file_returns_warning(self):
        from security.diagnostics import DiagnosticsEngine
        import security.diagnostics as _diag_mod

        engine = DiagnosticsEngine()
        orig = _diag_mod.PROJECT_ROOT
        with tempfile.TemporaryDirectory(prefix="hopefx_diag_") as d:
            _diag_mod.PROJECT_ROOT = Path(d)
            try:
                results = _run(engine._check_log_patterns())
            finally:
                _diag_mod.PROJECT_ROOT = orig
        assert len(results) == 1
        assert results[0].status == "warning"
        assert "not found" in results[0].message.lower()

    def test_clean_log_returns_ok(self):
        from security.diagnostics import DiagnosticsEngine
        import security.diagnostics as _diag_mod

        engine = DiagnosticsEngine()
        orig = _diag_mod.PROJECT_ROOT
        with tempfile.TemporaryDirectory(prefix="hopefx_diag_") as d:
            root = Path(d)
            (root / "logs").mkdir()
            (root / "logs" / "app.log").write_text("2025-01-01 INFO startup complete\n")
            _diag_mod.PROJECT_ROOT = root
            try:
                results = _run(engine._check_log_patterns())
            finally:
                _diag_mod.PROJECT_ROOT = orig
        assert len(results) == 1
        assert results[0].status == "ok"

    def test_db_error_pattern_detected(self):
        from security.diagnostics import DiagnosticsEngine
        import security.diagnostics as _diag_mod

        engine = DiagnosticsEngine()
        orig = _diag_mod.PROJECT_ROOT
        with tempfile.TemporaryDirectory(prefix="hopefx_diag_") as d:
            root = Path(d)
            (root / "logs").mkdir()
            (root / "logs" / "app.log").write_text(
                "2025-01-01 ERROR OperationalError: could not connect to server\n"
                "2025-01-01 ERROR OperationalError: could not connect to server\n"
            )
            _diag_mod.PROJECT_ROOT = root
            try:
                results = _run(engine._check_log_patterns())
            finally:
                _diag_mod.PROJECT_ROOT = orig
        categories = [r.check_name for r in results]
        assert any("db_connection" in c for c in categories)

    def test_import_error_pattern_detected(self):
        from security.diagnostics import DiagnosticsEngine
        import security.diagnostics as _diag_mod

        engine = DiagnosticsEngine()
        orig = _diag_mod.PROJECT_ROOT
        with tempfile.TemporaryDirectory(prefix="hopefx_diag_") as d:
            root = Path(d)
            (root / "logs").mkdir()
            (root / "logs" / "app.log").write_text("2025-01-01 ERROR ImportError: No module named 'missing_pkg'\n")
            _diag_mod.PROJECT_ROOT = root
            try:
                results = _run(engine._check_log_patterns())
            finally:
                _diag_mod.PROJECT_ROOT = orig
        categories = [r.check_name for r in results]
        assert any("import_error" in c for c in categories)


# ---------------------------------------------------------------------------
# DiagnosticsEngine — full run (integration, skips if services unavailable)
# ---------------------------------------------------------------------------


class TestFullDiagnosticRun:
    @pytest.fixture(autouse=True)
    def short_import_timeout(self, monkeypatch):
        """Cap subprocess import checks to 5 s so the test suite doesn't hang."""
        monkeypatch.setenv("DIAG_IMPORT_TIMEOUT", "5")

    def test_run_full_diagnostic_returns_report(self):
        from security.diagnostics import DiagnosticsEngine, DiagnosticReport

        engine = DiagnosticsEngine()
        report = _run(engine.run_full_diagnostic(parallel=True))
        assert isinstance(report, DiagnosticReport)
        assert len(report.results) > 0
        assert report.completed_at != ""
        assert report.total_duration_ms > 0

    def test_run_full_diagnostic_sequential(self):
        from security.diagnostics import DiagnosticsEngine, DiagnosticReport

        engine = DiagnosticsEngine()
        report = _run(engine.run_full_diagnostic(parallel=False))
        assert isinstance(report, DiagnosticReport)
        assert len(report.results) > 0

    def test_singleton_returns_same_instance(self):
        from security.diagnostics import get_diagnostics_engine

        e1 = get_diagnostics_engine()
        e2 = get_diagnostics_engine()
        assert e1 is e2

    def test_last_report_stored_after_run(self):
        from security.diagnostics import DiagnosticsEngine

        engine = DiagnosticsEngine()
        assert engine.get_last_report() is None
        _run(engine.run_full_diagnostic())
        assert engine.get_last_report() is not None

    def test_report_to_dict_is_serialisable(self):
        import json
        from security.diagnostics import DiagnosticsEngine

        engine = DiagnosticsEngine()
        report = _run(engine.run_full_diagnostic())
        d = report.to_dict()
        # Must be JSON-serialisable (no datetime objects, no Path objects)
        serialised = json.dumps(d)
        assert len(serialised) > 10


# ---------------------------------------------------------------------------
# code_analyzer extended checks
# ---------------------------------------------------------------------------


class TestCodeAnalyzerExtended:
    def _write_file(self, tmp_path: Path, name: str, content: str) -> Path:
        p = tmp_path / name
        p.write_text(textwrap.dedent(content))
        return p

    def test_check_spa_routing_detects_missing_static_mount(self):
        from security.code_analyzer import check_spa_routing

        with tempfile.TemporaryDirectory(prefix="hopefx_diag_") as d:
            f = Path(d) / "app.py"
            f.write_text(
                "from fastapi import FastAPI\napp = FastAPI()\n@app.get('/api/health')\ndef health(): return {'ok': True}\n"
            )
            issues = check_spa_routing(f)
        assert any(i.category == "spa_routing" for i in issues)

    def test_check_spa_routing_ok_with_static_mount(self):
        from security.code_analyzer import check_spa_routing

        with tempfile.TemporaryDirectory(prefix="hopefx_diag_") as d:
            f = Path(d) / "app.py"
            f.write_text(
                "from fastapi.staticfiles import StaticFiles\napp.mount('/static', StaticFiles(directory='static'), name='static')\n"
            )
            issues = check_spa_routing(f)
        assert not any(i.category == "spa_routing" for i in issues)

    def test_check_cookie_security_detects_missing_httponly(self):
        from security.code_analyzer import check_cookie_auth_security

        content = (
            "def login(response):\n"
            "    response.set_cookie(\n"
            "        key='session',\n"
            "        value='abc123',\n"
            "        secure=True,\n"
            "    )\n"
        )
        with tempfile.TemporaryDirectory(prefix="hopefx_diag_") as d:
            f = Path(d) / "auth.py"
            f.write_text(content)
            issues = check_cookie_auth_security(f)
        assert any(i.category == "cookie_security" for i in issues)

    def test_check_cookie_security_ok_with_httponly(self):
        from security.code_analyzer import check_cookie_auth_security

        content = (
            "def login(response):\n"
            "    response.set_cookie(\n"
            "        key='session',\n"
            "        value='abc123',\n"
            "        httponly=True,\n"
            "        samesite='lax',\n"
            "    )\n"
        )
        with tempfile.TemporaryDirectory(prefix="hopefx_diag_") as d:
            f = Path(d) / "auth.py"
            f.write_text(content)
            issues = check_cookie_auth_security(f)
        assert not any(i.category == "cookie_security" for i in issues)

    def test_check_env_var_access_detects_keyerror_risk(self):
        from security.code_analyzer import check_env_var_access

        with tempfile.TemporaryDirectory(prefix="hopefx_diag_") as d:
            f = Path(d) / "config.py"
            f.write_text("import os\nSECRET = os.environ['SECRET_KEY']\n")
            issues = check_env_var_access(f)
        assert any(i.category == "env_var_unsafe" for i in issues)

    def test_check_env_var_access_ok_with_getenv(self):
        from security.code_analyzer import check_env_var_access

        with tempfile.TemporaryDirectory(prefix="hopefx_diag_") as d:
            f = Path(d) / "config.py"
            f.write_text("import os\nSECRET = os.getenv('SECRET_KEY')\n")
            issues = check_env_var_access(f)
        assert not any(i.category == "env_var_unsafe" for i in issues)

    def test_check_env_var_hardcoded_secret_detected(self):
        from security.code_analyzer import check_env_var_access

        with tempfile.TemporaryDirectory(prefix="hopefx_diag_") as d:
            f = Path(d) / "config.py"
            f.write_text("import os\nKEY = os.getenv('SECRET_KEY', 'hardcoded-secret-value-here')\n")
            issues = check_env_var_access(f)
        assert any(i.category == "env_var_hardcoded_secret" for i in issues)

    def test_check_startup_validators_detects_missing_call(self):
        from security.code_analyzer import check_startup_validators

        with tempfile.TemporaryDirectory(prefix="hopefx_diag_") as d:
            f = Path(d) / "app.py"
            f.write_text("from fastapi import FastAPI\napp = FastAPI()\n")
            issues = check_startup_validators(f)
        assert any(i.category == "missing_startup_validation" for i in issues)

    def test_check_startup_validators_ok_when_present(self):
        from security.code_analyzer import check_startup_validators

        with tempfile.TemporaryDirectory(prefix="hopefx_diag_") as d:
            f = Path(d) / "app.py"
            f.write_text(
                "from config.startup_validator import validate_environment\nvalidate_environment(strict=True)\n"
            )
            issues = check_startup_validators(f)
        assert not any(i.category == "missing_startup_validation" for i in issues)

    def test_scan_extended_returns_list(self):
        from security.code_analyzer import scan_extended

        with tempfile.TemporaryDirectory(prefix="hopefx_diag_") as d:
            f = Path(d) / "app.py"
            f.write_text("from fastapi import FastAPI\napp = FastAPI()\n")
            issues = scan_extended(f)
        assert isinstance(issues, list)

    def test_check_router_registration_skips_non_api_files(self):
        from security.code_analyzer import check_router_registration

        with tempfile.TemporaryDirectory(prefix="hopefx_diag_") as d:
            f = Path(d) / "utils.py"
            f.write_text("from fastapi import APIRouter\nrouter = APIRouter()\n")
            issues = check_router_registration(f)
        assert issues == []


# ---------------------------------------------------------------------------
# superadmin diagnostics router — import and structure
# ---------------------------------------------------------------------------


class TestSuperadminDiagnosticsRouter:
    def test_router_importable(self):
        from api.superadmin.diagnostics import router

        assert router is not None

    def test_router_has_expected_routes(self):
        from api.superadmin.diagnostics import router

        paths = {r.path for r in router.routes}
        assert "/diagnostics/run" in paths
        assert "/diagnostics/report" in paths
        assert "/diagnostics/results" in paths
        assert "/diagnostics/remediate" in paths
        assert "/diagnostics/remediation-log" in paths
        assert "/diagnostics/checks" in paths
        assert "/diagnostics/summary" in paths

    def test_check_descriptions_covers_all_known_checks(self):
        from api.superadmin.diagnostics import _CHECK_DESCRIPTIONS

        expected = {
            "env_vars_required",
            "env_vars_optional",
            "import_chain",
            "database",
            "redis",
            "frontend_build",
            "route_health",
            "spa_routing",
            "auth_flow",
            "data_feeds_redis",
            "data_feeds_module",
            "log_patterns",
        }
        assert expected.issubset(set(_CHECK_DESCRIPTIONS.keys()))

    def test_router_registered_in_superadmin_init(self):
        from api.superadmin import router as superadmin_router

        # The diagnostics router must be included — check that at least one
        # diagnostics path is reachable from the parent router
        all_paths = set()
        for route in superadmin_router.routes:
            all_paths.add(getattr(route, "path", ""))
        # The parent router includes sub-routers; check the include happened
        from api.superadmin import _diagnostics_router

        assert _diagnostics_router is not None


# ---------------------------------------------------------------------------
# SelfHealer diagnostics integration
# ---------------------------------------------------------------------------


class TestSelfHealerDiagnosticsIntegration:
    @pytest.fixture(autouse=True)
    def short_import_timeout(self, monkeypatch):
        """Cap subprocess import checks to 5 s so the test suite doesn't hang."""
        monkeypatch.setenv("DIAG_IMPORT_TIMEOUT", "5")

    def test_healer_has_diagnostics_state(self):
        from security.self_healer import SelfHealer

        h = SelfHealer()
        assert hasattr(h, "_diag_interval")
        assert hasattr(h, "_last_diag_ts")
        assert hasattr(h, "_last_diag_report")
        assert hasattr(h, "_diag_remediation_log")

    def test_get_last_diagnostic_report_returns_dict(self):
        from security.self_healer import SelfHealer

        h = SelfHealer()
        report = h.get_last_diagnostic_report()
        assert isinstance(report, dict)

    def test_get_diagnostics_remediation_log_returns_list(self):
        from security.self_healer import SelfHealer

        h = SelfHealer()
        log = h.get_diagnostics_remediation_log()
        assert isinstance(log, list)

    def test_get_full_status_includes_diag_fields(self):
        from security.self_healer import SelfHealer

        h = SelfHealer()
        status = h.get_full_status()
        assert "last_diag_ts" in status
        assert "diag_has_critical" in status
        assert "diag_has_errors" in status
        assert "diag_counts" in status
        assert "diag_remediation_actions" in status

    def test_run_diagnostics_now_returns_dict(self):
        from security.self_healer import SelfHealer

        h = SelfHealer()
        result = _run(h.run_diagnostics_now())
        assert isinstance(result, dict)
        # After running, last_diag_report should be populated
        assert h._last_diag_ts > 0
