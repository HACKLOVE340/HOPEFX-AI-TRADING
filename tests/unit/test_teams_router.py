# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# AGPL-3.0 — Share all modifications
"""
tests/unit/test_teams_router.py
=================================
Unit tests for teams/__init__.py (Teams HTTP API).

Covers:
  - POST /api/teams/           — create team
  - GET  /api/teams/           — list teams
  - GET  /api/teams/{id}       — get team by ID
  - POST /api/teams/{id}/members — invite member
  - DELETE /api/teams/{id}/members/{uid} — remove member
  - DELETE /api/teams/{id}     — delete team
  - GET  /api/teams/{id}/performance — team performance
"""

from __future__ import annotations

import os
import time

import jwt
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("SECURITY_JWT_SECRET", "unit-test-teams-secret-key-32chars!!")

from api.auth import TokenPayload, get_current_user
from teams import TeamManager, create_teams_router

_JWT_SECRET = os.environ.get("SECURITY_JWT_SECRET", "unit-test-teams-secret-key-32chars!!")


def _make_token(sub: str = "owner-user", role: str = "admin") -> str:
    return jwt.encode(
        {"sub": sub, "role": role, "type": "access", "exp": int(time.time()) + 3600},
        _JWT_SECRET,
        algorithm="HS256",
    )


def _auth_headers(sub: str = "owner-user") -> dict[str, str]:
    return {"Authorization": f"Bearer {_make_token(sub=sub)}"}


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture()
def manager() -> TeamManager:
    return TeamManager()


@pytest.fixture()
def client(manager: TeamManager) -> TestClient:
    app = FastAPI()
    _user = TokenPayload(sub="owner-user", role="admin")
    app.dependency_overrides[get_current_user] = lambda: _user
    app.include_router(create_teams_router(manager))
    return TestClient(app, raise_server_exceptions=True)


@pytest.fixture()
def team_id(client: TestClient) -> str:
    resp = client.post(
        "/api/teams/",
        json={"name": "Alpha Team", "description": "Test team"},
    )
    assert resp.status_code == 200
    return resp.json()["team_id"]


# ── Tests ─────────────────────────────────────────────────────────────────────


class TestCreateTeam:
    def test_returns_team_id(self, client: TestClient):
        resp = client.post(
            "/api/teams/",
            json={"name": "Beta Team", "description": "Another team"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "team_id" in data
        assert data["name"] == "Beta Team"

    def test_returned_data_has_expected_fields(self, client: TestClient):
        resp = client.post(
            "/api/teams/",
            json={"name": "Gamma Team", "description": "desc"},
        )
        data = resp.json()
        for field in ("team_id", "name", "owner_id", "member_count", "created_at"):
            assert field in data

    def test_multiple_teams_have_unique_ids(self, client: TestClient):
        ids = set()
        for i in range(3):
            resp = client.post("/api/teams/", json={"name": f"Team {i}", "description": "d"})
            ids.add(resp.json()["team_id"])
        assert len(ids) == 3


class TestListTeams:
    def test_empty_initially(self, client: TestClient):
        resp = client.get("/api/teams/")
        assert resp.status_code == 200
        data = resp.json()
        assert "teams" in data
        assert data["total"] == 0

    def test_created_team_appears(self, client: TestClient, team_id: str):
        resp = client.get("/api/teams/")
        ids = [t["team_id"] for t in resp.json()["teams"]]
        assert team_id in ids

    def test_total_count_matches(self, client: TestClient):
        for i in range(2):
            client.post("/api/teams/", json={"name": f"Team {i}", "description": "d"})
        resp = client.get("/api/teams/")
        assert resp.json()["total"] == 2


class TestGetTeam:
    def test_returns_team_summary(self, client: TestClient, team_id: str):
        resp = client.get(f"/api/teams/{team_id}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["team_id"] == team_id

    def test_missing_team_returns_404(self, client: TestClient):
        resp = client.get("/api/teams/nonexistent-id")
        assert resp.status_code == 404


class TestInviteMember:
    def test_invite_returns_invitation(self, client: TestClient, team_id: str):
        resp = client.post(
            f"/api/teams/{team_id}/members",
            # invited_by must match the team owner_id ("owner-user" from fixture)
            json={"email": "trader@example.com", "role": "trader", "invited_by": "owner-user"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "invitation_id" in data
        assert "token" in data
        assert data["email"] == "trader@example.com"

    def test_invite_with_admin_role(self, client: TestClient, team_id: str):
        resp = client.post(
            f"/api/teams/{team_id}/members",
            json={"email": "admin@example.com", "role": "admin", "invited_by": "owner-user"},
        )
        assert resp.status_code == 200
        assert resp.json()["role"] == "admin"

    def test_invite_invalid_role_returns_400(self, client: TestClient, team_id: str):
        resp = client.post(
            f"/api/teams/{team_id}/members",
            json={"email": "user@example.com", "role": "superuser", "invited_by": "owner-user"},
        )
        assert resp.status_code == 400

    def test_invite_missing_team_returns_404(self, client: TestClient):
        resp = client.post(
            "/api/teams/nonexistent/members",
            json={"email": "x@x.com", "role": "trader", "invited_by": "owner-user"},
        )
        assert resp.status_code == 404


class TestRemoveMember:
    def _add_member(self, manager: TeamManager, team_id: str) -> str:
        """Invite and accept an invitation to get a real member in the team."""
        from teams import UserRole

        invitation = manager.invite_member(team_id, "member@test.com", UserRole.TRADER, "owner-user")
        assert invitation is not None, "invite_member returned None (check owner permissions)"
        member = manager.accept_invitation(invitation.token, "member-uid-1", "Test Member")
        assert member is not None
        return member.user_id

    def test_remove_existing_member(self, client: TestClient, manager: TeamManager, team_id: str):
        member_uid = self._add_member(manager, team_id)
        # removed_by must match the team owner_id ("owner-user")
        resp = client.delete(
            f"/api/teams/{team_id}/members/{member_uid}",
            params={"removed_by": "owner-user"},
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "removed"

    def test_remove_nonexistent_member_returns_404(self, client: TestClient, team_id: str):
        resp = client.delete(f"/api/teams/{team_id}/members/unknown-user")
        assert resp.status_code == 404

    def test_remove_member_from_missing_team_returns_404(self, client: TestClient):
        resp = client.delete("/api/teams/nonexistent/members/some-user")
        assert resp.status_code == 404


class TestDeleteTeam:
    def test_delete_team_succeeds(self, client: TestClient, team_id: str):
        resp = client.delete(f"/api/teams/{team_id}")
        assert resp.status_code == 200
        assert resp.json()["status"] == "deleted"

    def test_deleted_team_not_in_list(self, client: TestClient, team_id: str):
        client.delete(f"/api/teams/{team_id}")
        resp = client.get("/api/teams/")
        ids = [t["team_id"] for t in resp.json()["teams"]]
        assert team_id not in ids

    def test_delete_missing_team_returns_404(self, client: TestClient):
        resp = client.delete("/api/teams/nonexistent-id")
        assert resp.status_code == 404


class TestTeamPerformance:
    def test_returns_performance_data(self, client: TestClient, team_id: str):
        resp = client.get(f"/api/teams/{team_id}/performance")
        assert resp.status_code == 200
        data = resp.json()
        assert data["team_id"] == team_id
        for field in ("total_pnl", "win_rate", "total_trades", "sharpe", "max_drawdown_pct"):
            assert field in data

    def test_performance_missing_team_returns_404(self, client: TestClient):
        resp = client.get("/api/teams/nonexistent/performance")
        assert resp.status_code == 404
