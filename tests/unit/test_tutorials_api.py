# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# AGPL-3.0 — Share all modifications
"""
tests/unit/test_tutorials_api.py
================================
Unit tests for api/tutorials.py (Video Academy catalogue + per-episode gating).

Covers:
  - GET /api/tutorials            — catalogue with per-episode `locked` flag
  - GET /api/tutorials/{episode}  — detail, video_url gated by plan
  - free episodes (1–3) are never locked
  - plan-gated episodes are locked for a free user and return 403 on detail
  - admin/superadmin bypass the gate
  - unknown episode → 404
"""

from __future__ import annotations

import os

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("SECURITY_JWT_SECRET", "unit-test-tutorials-secret-key-32chars!!")

from api.auth import TokenPayload, get_current_user
from api.tutorials import router as tutorials_router


def _client(role: str = "user") -> TestClient:
    app = FastAPI()
    app.dependency_overrides[get_current_user] = lambda: TokenPayload(sub="u-tut", role=role)
    app.include_router(tutorials_router)
    return TestClient(app)


def test_catalogue_lists_all_episodes() -> None:
    r = _client().get("/api/tutorials")
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 15
    assert len(body["episodes"]) == 15
    # Catalogue never leaks the playable URL.
    assert all("video_url" not in ep for ep in body["episodes"])


def test_free_episodes_never_locked_for_free_user() -> None:
    eps = {e["episode"]: e for e in _client().get("/api/tutorials").json()["episodes"]}
    for n in (1, 2, 3):
        assert eps[n]["plan"] == "free"
        assert eps[n]["locked"] is False


def test_gated_episode_locked_for_free_user() -> None:
    eps = {e["episode"]: e for e in _client().get("/api/tutorials").json()["episodes"]}
    # Episode 8 is professional-gated in the spec.
    assert eps[8]["plan"] == "professional"
    assert eps[8]["locked"] is True


def test_detail_free_episode_returns_video_url_key() -> None:
    r = _client().get("/api/tutorials/1")
    assert r.status_code == 200
    body = r.json()
    assert body["episode"] == 1
    # Key is present (value may be None until the episode is filmed).
    assert "video_url" in body


def test_detail_gated_episode_403_for_free_user() -> None:
    r = _client().get("/api/tutorials/8")
    assert r.status_code == 403
    detail = r.json()["detail"]
    assert detail["error"] == "PLAN_LIMIT_EXCEEDED"
    assert detail["required_plan"] == "professional"


@pytest.mark.parametrize("role", ["admin", "superadmin"])
def test_admin_bypasses_gate(role: str) -> None:
    # Catalogue shows nothing locked …
    eps = _client(role).get("/api/tutorials").json()["episodes"]
    assert all(ep["locked"] is False for ep in eps)
    # … and the gated detail is accessible.
    assert _client(role).get("/api/tutorials/8").status_code == 200


def test_unknown_episode_404() -> None:
    assert _client().get("/api/tutorials/999").status_code == 404
