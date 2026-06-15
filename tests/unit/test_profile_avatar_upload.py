# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
tests/unit/test_profile_avatar_upload.py
========================================
Regression: POST /api/profiles/me/avatar must STORE the uploaded image and serve
it back (previously the file was ignored and a Gravatar URL returned).
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api import profiles
from api.auth import TokenPayload, get_current_user


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(profiles, "_AVATAR_DIR", tmp_path / "avatars")
    app = FastAPI()
    app.include_router(profiles.router)
    app.dependency_overrides[get_current_user] = lambda: TokenPayload(sub="user-123", role="user")
    return TestClient(app, raise_server_exceptions=False)


def test_upload_stores_and_serves_image(client):
    png = b"\x89PNG\r\n\x1a\n" + b"0" * 64  # minimal PNG-ish bytes
    r = client.post("/api/profiles/me/avatar", files={"file": ("a.png", png, "image/png")})
    assert r.status_code == 200, r.text
    url = r.json()["avatar_url"]
    assert url.startswith("/api/profiles/avatar/")

    # The stored avatar is served back with the same bytes.
    got = client.get(url)
    assert got.status_code == 200
    assert got.content == png


def test_non_image_rejected(client):
    r = client.post("/api/profiles/me/avatar", files={"file": ("x.txt", b"hello", "text/plain")})
    assert r.status_code == 415


def test_avatar_path_traversal_rejected(client):
    assert client.get("/api/profiles/avatar/..%2f..%2fetc%2fpasswd").status_code == 404
    assert client.get("/api/profiles/avatar/notahash.png").status_code == 404
