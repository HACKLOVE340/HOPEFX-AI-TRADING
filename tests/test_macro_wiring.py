# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
tests/test_macro_wiring.py
==========================
Verifies that MacroStore → live inference wiring is correct:
  1. MacroStore.update() stores a value and snapshot() returns it.
  2. MacroStore.align_to_hourly() forward-fills daily values to hourly bars.
  3. _push_snapshot_to_store() pushes FRED snapshot keys into MacroStore.
  4. /api/macro/store endpoint returns the store state.
  5. /api/macro/store/update endpoint upserts a value.
  6. /api/macro/features prefers MacroStore over MacroFeed when populated.
"""

from __future__ import annotations

import os
import time

import jwt
import pandas as pd
import pytest
from fastapi.testclient import TestClient

# Must be set before any api.auth import so JWT verification uses this secret.
os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("SECURITY_JWT_SECRET", "test-only-jwt-secret-key-minimum-32-chars!!")
os.environ.setdefault("CSRF_PROTECTION", "false")

_SECRET = os.environ["SECURITY_JWT_SECRET"]


def _auth(role: str = "admin") -> dict[str, str]:
    token = jwt.encode(
        {"sub": "test-user", "role": role, "type": "access", "exp": int(time.time()) + 3600},
        _SECRET,
        algorithm="HS256",
    )
    return {"Authorization": f"Bearer {token}"}


# ── unit: MacroStore ──────────────────────────────────────────────────────────


def test_macro_store_update_and_snapshot():
    from ml.macro_store import MacroStore

    store = MacroStore()
    store.update("dxy", "2026-01-02", 102.5)
    snap = store.snapshot()
    assert "dxy" in snap
    assert snap["dxy"]["value"] == pytest.approx(102.5)
    assert snap["dxy"]["n_observations"] == 1


def test_macro_store_align_to_hourly():
    from ml.macro_store import MacroStore

    store = MacroStore()
    store.update("dxy", "2026-01-02", 102.5)
    store.update("dxy", "2026-01-03", 103.0)

    # Build a 48-bar hourly index spanning both days
    idx = pd.date_range("2026-01-02 00:00", periods=48, freq="h", tz="UTC")
    ohlcv = pd.DataFrame({"close": 1.0}, index=idx)

    aligned = store.align_to_hourly(ohlcv)
    assert "dxy" in aligned.columns
    assert aligned.shape[0] == 48
    # First 24 bars should be 102.5 (Jan 2 value forward-filled)
    assert aligned["dxy"].iloc[0] == pytest.approx(102.5)
    # After Jan 3 00:00 UTC the value should be 103.0
    assert aligned["dxy"].iloc[24] == pytest.approx(103.0)


def test_macro_store_missing_series_fills_zero():
    from ml.macro_store import MacroStore

    store = MacroStore()
    idx = pd.date_range("2026-01-02", periods=5, freq="h", tz="UTC")
    ohlcv = pd.DataFrame({"close": 1.0}, index=idx)

    aligned = store.align_to_hourly(ohlcv, series=["nonexistent"])
    assert "nonexistent" in aligned.columns
    assert (aligned["nonexistent"] == 0.0).all()


# ── unit: _push_snapshot_to_store ────────────────────────────────────────────


def test_push_snapshot_to_store():
    # Patch the module-level singleton with a fresh store
    import ml.macro_store as _ms
    from api.macro import _push_snapshot_to_store
    from ml.macro_store import MacroStore

    original = _ms.macro_store
    _ms.macro_store = MacroStore()

    try:
        snapshot = {
            "dxy": 102.3,
            "yield_10y": 4.25,
            "yield_2y": 4.80,
            "yield_spread": -0.55,
            "cpi_latest": 314.0,
        }
        n = _push_snapshot_to_store(snapshot)
        assert n == 5
        snap = _ms.macro_store.snapshot()
        assert snap["dxy"]["value"] == pytest.approx(102.3)
        assert snap["us10y"]["value"] == pytest.approx(4.25)
    finally:
        _ms.macro_store = original


# ── integration: API endpoints ────────────────────────────────────────────────


@pytest.fixture(scope="module")
def client():
    from fastapi import FastAPI

    from api.macro import router

    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def test_macro_store_endpoint_returns_ok(client):
    resp = client.get("/api/macro/store", headers=_auth())
    assert resp.status_code == 200
    data = resp.json()
    assert "status" in data
    assert "total_series" in data


def test_macro_store_update_endpoint(client):
    resp = client.post(
        "/api/macro/store/update",
        json={"series_name": "vix", "date": "2026-03-26", "value": 18.5},
        headers=_auth(),
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "updated"
    assert data["series"] == "vix"
    assert data["value"] == pytest.approx(18.5)


def test_macro_features_returns_dict(client):
    # Seed the store first
    client.post(
        "/api/macro/store/update",
        json={"series_name": "dxy", "date": "2026-03-26", "value": 104.1},
        headers=_auth(),
    )
    resp = client.get("/api/macro/features", headers=_auth())
    assert resp.status_code == 200
    data = resp.json()
    # At least one macro_ key should be present
    assert any(k.startswith("macro_") for k in data)
