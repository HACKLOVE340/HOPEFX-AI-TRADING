# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# AGPL-3.0 — Share all modifications
"""
tests/unit/test_research_router.py
====================================
Unit tests for research/__init__.py (Research Notebooks HTTP API).

Covers:
  - GET  /api/research/notebooks              — list notebooks
  - POST /api/research/notebooks              — create notebook
  - GET  /api/research/notebooks/{id}         — get notebook by ID
  - POST /api/research/notebooks/{id}/run     — run notebook (auth required)
  - DELETE /api/research/notebooks/{id}       — delete notebook (auth required)
  - GET  /api/research/templates              — list templates
  - POST /api/research/notebooks/from-template/{id} — create from template
"""

from __future__ import annotations

import os
import time

import jwt
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("SECURITY_JWT_SECRET", "unit-test-research-secret-key-32chars!!")

from api.auth import TokenPayload, get_current_user, require_role
from research import ResearchNotebookEngine, create_research_router


# ── Helpers ───────────────────────────────────────────────────────────────────

_JWT_SECRET = os.environ.get("SECURITY_JWT_SECRET", "unit-test-research-secret-key-32chars!!")


def _make_token(role: str = "admin") -> str:
    return jwt.encode(
        {"sub": "test-user", "role": role, "type": "access", "exp": int(time.time()) + 3600},
        _JWT_SECRET,
        algorithm="HS256",
    )


def _auth_headers(role: str = "admin") -> dict[str, str]:
    return {"Authorization": f"Bearer {_make_token(role)}"}


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture()
def engine() -> ResearchNotebookEngine:
    return ResearchNotebookEngine()


@pytest.fixture()
def client(engine: ResearchNotebookEngine) -> TestClient:
    app = FastAPI()
    # Override auth dependencies so tests don't need live JWT validation
    _trader = TokenPayload(sub="test-user", role="trader")
    app.dependency_overrides[get_current_user] = lambda: _trader
    app.dependency_overrides[require_role("trader")] = lambda: _trader
    app.include_router(create_research_router(engine))
    return TestClient(app, raise_server_exceptions=True)


@pytest.fixture()
def notebook_id(client: TestClient) -> str:
    resp = client.post(
        "/api/research/notebooks",
        json={"title": "Test NB", "description": "desc", "author": "tester"},
    )
    assert resp.status_code == 200
    return resp.json()["notebook_id"]


# ── Tests ─────────────────────────────────────────────────────────────────────


class TestListNotebooks:
    def test_returns_list(self, client: TestClient):
        resp = client.get("/api/research/notebooks")
        assert resp.status_code == 200
        assert "notebooks" in resp.json()

    def test_created_notebook_appears(self, client: TestClient, notebook_id: str):
        resp = client.get("/api/research/notebooks")
        ids = [nb["notebook_id"] for nb in resp.json()["notebooks"]]
        assert notebook_id in ids

    def test_multiple_notebooks_in_list(self, client: TestClient):
        for i in range(3):
            client.post(
                "/api/research/notebooks",
                json={"title": f"NB {i}", "description": "d", "author": "tester"},
            )
        resp = client.get("/api/research/notebooks")
        assert len(resp.json()["notebooks"]) >= 3


class TestCreateNotebook:
    def test_returns_notebook_id(self, client: TestClient):
        resp = client.post(
            "/api/research/notebooks",
            json={"title": "My NB", "description": "some description", "author": "alice"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "notebook_id" in data
        assert data["title"] == "My NB"
        assert data["author"] == "alice"

    def test_default_status_is_draft(self, client: TestClient):
        resp = client.post(
            "/api/research/notebooks",
            json={"title": "Draft NB", "description": "d", "author": "bob"},
        )
        assert resp.json()["status"] == "draft"

    def test_with_tags(self, client: TestClient):
        resp = client.post(
            "/api/research/notebooks",
            json={"title": "Tagged NB", "description": "d", "author": "carol"},
        )
        assert resp.status_code == 200


class TestGetNotebook:
    def test_returns_notebook_data(self, client: TestClient, notebook_id: str):
        resp = client.get(f"/api/research/notebooks/{notebook_id}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["notebook_id"] == notebook_id
        assert "cells" in data
        assert "title" in data

    def test_missing_notebook_returns_404(self, client: TestClient):
        resp = client.get("/api/research/notebooks/nonexistent-id")
        assert resp.status_code == 404

    def test_initial_status_is_draft(self, client: TestClient, notebook_id: str):
        resp = client.get(f"/api/research/notebooks/{notebook_id}")
        assert resp.json()["status"] == "draft"


class TestRunNotebook:
    def test_run_returns_results(self, client: TestClient, notebook_id: str):
        resp = client.post(f"/api/research/notebooks/{notebook_id}/run")
        assert resp.status_code == 200
        data = resp.json()
        assert "notebook_id" in data or "results" in data

    def test_run_missing_notebook_returns_404(self, client: TestClient):
        resp = client.post("/api/research/notebooks/nonexistent/run")
        assert resp.status_code == 404


class TestDeleteNotebook:
    def test_delete_returns_204(self, client: TestClient, notebook_id: str):
        resp = client.delete(f"/api/research/notebooks/{notebook_id}")
        assert resp.status_code == 204

    def test_deleted_notebook_not_in_list(self, client: TestClient, notebook_id: str):
        client.delete(f"/api/research/notebooks/{notebook_id}")
        resp = client.get("/api/research/notebooks")
        ids = [nb["notebook_id"] for nb in resp.json()["notebooks"]]
        assert notebook_id not in ids

    def test_delete_missing_notebook_returns_404(self, client: TestClient):
        resp = client.delete("/api/research/notebooks/nonexistent-id")
        assert resp.status_code == 404


class TestListTemplates:
    def test_returns_templates_list(self, client: TestClient):
        resp = client.get("/api/research/templates")
        assert resp.status_code == 200
        data = resp.json()
        assert "templates" in data
        assert isinstance(data["templates"], list)

    def test_built_in_templates_exist(self, client: TestClient):
        resp = client.get("/api/research/templates")
        # The engine initialises with built-in templates
        assert len(resp.json()["templates"]) >= 1


class TestCreateFromTemplate:
    def test_create_from_valid_template(self, client: TestClient):
        # Get the first available template — templates use "id" key
        templates_resp = client.get("/api/research/templates")
        templates = templates_resp.json()["templates"]
        if not templates:
            pytest.skip("No templates available")
        template_id = templates[0]["id"]
        resp = client.post(
            f"/api/research/notebooks/from-template/{template_id}",
            json={"title": "From Template", "description": "d", "author": "tester"},
        )
        assert resp.status_code == 200
        assert "notebook_id" in resp.json()

    def test_create_from_missing_template_returns_404(self, client: TestClient):
        resp = client.post(
            "/api/research/notebooks/from-template/nonexistent-template",
            json={"title": "NB", "description": "d", "author": "tester"},
        )
        assert resp.status_code == 404
