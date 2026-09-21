"""Regression tests for two sidebar-page endpoint bugs found by the live probe.

1. GET /api/calendar/today returned 500 on every request. get_today() called
   get_upcoming() directly, so the `importance` parameter kept its raw
   FastAPI Query(None) marker object. Query(None) is truthy, so the code took
   the filter branch and called importance.lower() on a Query object:
   AttributeError: 'Query' object has no attribute 'lower'. Same latent bug in
   get_high_impact(). Both now delegate to a plain-value helper.

2. GET /api/notifications (no trailing slash) 404'd. The route was reachable
   only with a trailing slash, and the SPA catch-all returns a bare 404 for
   unmatched /api/* paths, pre-empting Starlette's slash-redirect. The list
   endpoint is now registered at both "" and "/".
"""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.auth import TokenPayload, get_current_user


@pytest.fixture()
def calendar_client() -> TestClient:
    from api.calendar import router

    app = FastAPI()
    app.dependency_overrides[get_current_user] = lambda: TokenPayload(sub="u1", role="trader")
    app.include_router(router)
    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture()
def notif_client() -> TestClient:
    from api.notifications import router

    app = FastAPI()
    app.dependency_overrides[get_current_user] = lambda: TokenPayload(sub="u1", role="trader")
    app.include_router(router)
    return TestClient(app, raise_server_exceptions=False)


class TestCalendarToday:
    def test_today_does_not_500(self, calendar_client):
        r = calendar_client.get("/api/calendar/today")
        assert r.status_code == 200, r.text
        assert isinstance(r.json(), list)

    def test_high_impact_does_not_500(self, calendar_client):
        r = calendar_client.get("/api/calendar/high-impact")
        assert r.status_code == 200, r.text
        assert isinstance(r.json(), list)

    def test_upcoming_still_accepts_importance_filter(self, calendar_client):
        # The real query-param path must keep working, including a bad value.
        assert calendar_client.get("/api/calendar/upcoming?importance=high").status_code == 200
        assert calendar_client.get("/api/calendar/upcoming?importance=bogus").status_code == 200


class TestNotificationsSlash:
    def test_list_reachable_without_trailing_slash(self, notif_client):
        r = notif_client.get("/api/notifications", follow_redirects=False)
        assert r.status_code == 200, r.text
        assert "notifications" in r.json()

    def test_list_reachable_with_trailing_slash(self, notif_client):
        r = notif_client.get("/api/notifications/", follow_redirects=False)
        assert r.status_code == 200, r.text
        assert "notifications" in r.json()
