# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""Integration test: /health/invariants is actually mounted on the real app.

Guards against the route being registered on the wrong app factory (it must live
on the health router that app.py includes, not only on api/server.py).
"""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("SECURITY_JWT_SECRET", "test-only-jwt-secret-key-minimum-32-chars!!")
os.environ.setdefault("CSRF_PROTECTION", "false")
os.environ["STARTUP_GATE"] = "false"

try:
    from fastapi.testclient import TestClient

    from app import app

    _import_error = None
except (ImportError, ModuleNotFoundError, SystemExit) as e:  # pragma: no cover
    _import_error = e

if _import_error is not None:  # pragma: no cover
    pytest.skip(f"Skipping invariants endpoint test: {_import_error}", allow_module_level=True)


@pytest.mark.integration
def test_health_invariants_is_mounted_and_reports_status():
    client = TestClient(app, raise_server_exceptions=False)
    r = client.get("/health/invariants")
    assert r.status_code == 200          # engine healthy by default
    body = r.json()
    assert body["mode"] in ("off", "monitor", "enforce")
    assert body["engine_healthy"] is True
    assert "counters" in body and "checks" in body["counters"]
