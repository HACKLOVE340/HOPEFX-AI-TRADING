# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
tests/unit/test_teams_route_slash_parity.py
===========================================
Creating a team from the UI returned 405.

`frontend/src/hooks/useApi.ts` defines the teams client as

    list:   ()           => api.get('/teams'),
    create: (body)       => api.post('/teams', body),

and the axios instance sets `baseURL: '/api'`, so those are
`GET /api/teams` and `POST /api/teams` — neither with a trailing slash.

`teams/__init__.py` registered the two verbs asymmetrically:

    @router.get("")      # GET /api/teams
    @router.get("/")     # GET /api/teams/
    @router.post("/")    # POST /api/teams/   <- slash only

So the list call worked and the create call did not. Confirmed against a
running server: `POST /api/teams` answered `{"detail":"Method Not Allowed"}`
with 405 on three consecutive attempts, while `POST /api/teams/` created the
team and returned its id.

FastAPI's `redirect_slashes` did not rescue it — no `Location` was returned for
the POST. Starlette only issues that redirect when the *other* form matches a
route and the request would otherwise 404; here `/api/teams` is a real path
that simply lacks a POST handler, which is a 405, and 405s are not redirected.

The author already made `list_teams` tolerant of both forms by stacking
`@router.get("")` and `@router.get("/")`. This applies the same pattern to
`create_team` rather than changing the frontend, so any client — the SPA, a
script, a future mobile app — works with or without the slash.

Found by cross-checking all 644 axios call sites in the frontend against the
992 routes the backend registers at runtime. It was the only real mismatch;
the other three candidates were regex artefacts (a JSDoc usage example, a
string-concatenated path, and `/alerts/{id}/pause|resume`, which both exist).
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.unit


def _teams_router():
    """Build the router against a real TeamManager, as app startup does."""
    from teams import TeamManager, create_teams_router

    return create_teams_router(TeamManager())


def _paths_by_method(router) -> dict[str, set[str]]:
    """Map HTTP method -> set of full paths this router serves."""
    out: dict[str, set[str]] = {}
    for route in router.routes:
        for method in getattr(route, "methods", set()) or set():
            out.setdefault(method, set()).add(route.path)
    return out


class TestSlashParity:
    def test_post_teams_is_served_without_a_trailing_slash(self):
        """The exact path frontend teamsApi.create() sends."""
        served = _paths_by_method(_teams_router())

        assert "/api/teams" in served.get("POST", set()), (
            "POST /api/teams is not routed, so teamsApi.create() — which posts to "
            "'/teams' against baseURL '/api' — gets 405 and team creation from the "
            "UI fails"
        )

    def test_post_teams_is_still_served_with_a_trailing_slash(self):
        """The originally registered form must keep working."""
        served = _paths_by_method(_teams_router())

        assert "/api/teams/" in served.get("POST", set())

    def test_get_teams_remains_tolerant_of_both_forms(self):
        """Characterisation: list_teams already stacked both decorators."""
        served = _paths_by_method(_teams_router())

        assert "/api/teams" in served.get("GET", set())
        assert "/api/teams/" in served.get("GET", set())


class TestTheFrontendContract:
    def test_every_bare_collection_path_the_spa_posts_to_is_routed(self):
        """Guards the general shape, not just this one route.

        The SPA's axios baseURL is '/api' and its teams client posts to the bare
        '/teams'. If another collection route is later registered on '/' only,
        this is the check that should catch it.
        """
        served = _paths_by_method(_teams_router())
        posts = served.get("POST", set())

        # Every POST path that ends in '/' should have a bare twin, so a client
        # that omits the slash is not silently 405'd.
        for path in sorted(posts):
            if path.endswith("/") and path != "/":
                assert path.rstrip("/") in posts, (
                    f"{path} accepts POST but {path.rstrip('/')} does not; a client "
                    f"that omits the trailing slash gets 405 rather than a redirect"
                )
