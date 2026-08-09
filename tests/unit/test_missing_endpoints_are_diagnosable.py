# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
tests/unit/test_missing_endpoints_are_diagnosable.py
=====================================================
Two checks that could only ever return one answer, and a 404 that said nothing.

**data_feeds_module was a permanent false alarm.** security/diagnostics.py has
always probed the feed like this::

    status = get_feed_status()
    return status.get("healthy", False), status.get("message", "")

and ``get_feed_status()`` has never returned either key — its snapshot is
``{"running", "symbols", "redis", ...}``. So the check reported "Data feed
module unhealthy" continuously and identically whether the feed was streaming
every symbol or had never started. A check with one possible answer carries no
information, and a red warning that is always red trains you to stop reading
the panel — which matters because a real feed outage looked exactly the same.

**A missing endpoint family was invisible.** Routers are registered inside
``try``/``except`` blocks and behind ``FEATURE_*`` flags; a failure is one
``logger.warning`` nobody reads. When a family goes missing every request under
it 404s, and the SPA catch-all returned those 404s with an **empty body**. The
frontend's ``extractApiError`` has a branch for precisely that case:

    // For 404 with no body, return the fallback rather than the raw Axios
    // message

so each page showed whatever generic string it happened to carry — "Could not
load your subscription", "Failed to load balance", "Could not load
notifications". Three panels, three different messages, one possible cause, and
nothing anywhere that named it. ``route_health`` cannot cover this either: it
probes the routes that *are* registered, so a family that is entirely absent
has nothing left to probe.
"""

from __future__ import annotations

import asyncio
import os
import time
from datetime import datetime, timedelta, timezone

import pytest

pytestmark = pytest.mark.unit

UTC = timezone.utc

os.environ.setdefault("SECURITY_JWT_SECRET", "test-only-jwt-secret-key-minimum-32-chars!!")
os.environ.setdefault("CSRF_PROTECTION", "false")
os.environ["STARTUP_GATE"] = "false"


@pytest.fixture(scope="module")
def client():
    from fastapi.testclient import TestClient

    from app import app

    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture(scope="module")
def su_headers():
    import jwt

    token = jwt.encode(
        {"sub": "superadmin", "role": "superadmin", "type": "access", "exp": int(time.time()) + 3600},
        os.environ["SECURITY_JWT_SECRET"],
        algorithm="HS256",
    )
    return {"Authorization": f"Bearer {token}"}


# ── A 404 must say what was not found ────────────────────────────────────────


def test_an_api_404_carries_a_body_naming_the_route(client, su_headers):
    r = client.get("/api/billing/no-such-endpoint", headers=su_headers)
    assert r.status_code == 404
    body = r.json()
    assert "/api/billing/no-such-endpoint" in body["detail"], body
    assert body["method"] == "GET"
    assert body["path"] == "/api/billing/no-such-endpoint"


def test_the_body_defeats_the_frontends_empty_404_fallback(client, su_headers):
    """extractApiError returns the caller's generic fallback for a 404 with no
    body. A populated `detail` is what makes it show the real reason instead."""
    r = client.get("/api/definitely-not-a-route", headers=su_headers)
    assert r.status_code == 404
    assert r.json().get("detail"), "a bodiless 404 puts the UI back to guessing"


def test_spa_paths_still_get_html_not_json(client):
    r = client.get("/some/react/route")
    assert r.status_code == 200
    assert "html" in r.headers.get("content-type", "")


# ── The feed must be able to report health ───────────────────────────────────


def test_the_feed_snapshot_reports_health():
    """The contract security/diagnostics.py has always read."""
    from data_feed import get_feed_status

    status = get_feed_status()
    assert "healthy" in status, "get_feed_status() still cannot answer the question it is asked"
    assert isinstance(status["healthy"], bool)
    assert status.get("message"), "an unhealthy verdict with no reason is not actionable"


def _feed_with(symbol_states: dict, *, running: bool, redis_connected: bool = True):
    """A MultiSourceTickFeed stub carrying just what _health_summary reads."""
    from data_feed.multi_source_feed import MultiSourceTickFeed

    feed = MultiSourceTickFeed.__new__(MultiSourceTickFeed)
    feed._running = running
    feed._max_stale_s = 30.0
    return feed._health_summary(symbol_states, {"redis_connected": redis_connected})


def _fresh(seconds_ago: float = 1.0) -> dict:
    return {"last_update": (datetime.now(UTC) - timedelta(seconds=seconds_ago)).isoformat()}


def test_a_streaming_feed_is_healthy():
    healthy, message = _feed_with({"XAUUSD": _fresh(), "EURUSD": _fresh(2)}, running=True)
    assert healthy is True, message
    assert "2/2" in message


def test_a_stopped_feed_is_unhealthy():
    healthy, message = _feed_with({"XAUUSD": _fresh()}, running=False)
    assert healthy is False
    assert "not running" in message


def test_a_running_feed_with_only_stale_symbols_is_unhealthy():
    """Running is not health. The poll loop stays alive with every source
    circuit-open, which is the state most worth alerting on."""
    healthy, message = _feed_with({"XAUUSD": _fresh(3600), "EURUSD": _fresh(7200)}, running=True)
    assert healthy is False
    assert "stale" in message


def test_one_fresh_symbol_among_stale_ones_is_healthy_and_says_so():
    healthy, message = _feed_with(
        {"XAUUSD": _fresh(), "EURUSD": _fresh(7200), "BTCUSD": {"last_update": None}}, running=True
    )
    assert healthy is True
    assert "1/3" in message


def test_a_feed_with_no_symbols_is_unhealthy():
    healthy, message = _feed_with({}, running=True)
    assert healthy is False
    assert "no symbols" in message


def test_a_disconnected_redis_is_reported_without_failing_health():
    """Ticks not being persisted is worth saying; it does not mean the feed is
    dead, and conflating them would hide whichever happened second."""
    healthy, message = _feed_with({"XAUUSD": _fresh()}, running=True, redis_connected=False)
    assert healthy is True
    assert "Redis not connected" in message


def test_an_unparseable_timestamp_counts_as_stale():
    """Fail closed: an unreadable last_update is not evidence of freshness."""
    healthy, _ = _feed_with({"XAUUSD": {"last_update": "not-a-timestamp"}}, running=True)
    assert healthy is False


# ── The probe must not invent a verdict ──────────────────────────────────────


def test_a_snapshot_without_health_is_reported_as_such_not_as_unhealthy(monkeypatch):
    """The original defect. `status.get("healthy", False)` answered a question
    the snapshot never addressed, and the answer was always "unhealthy"."""
    import data_feed
    from security.diagnostics import DiagnosticsEngine

    monkeypatch.setattr(data_feed, "get_feed_status", lambda: {"running": True, "symbols": {}})

    results = asyncio.run(DiagnosticsEngine()._check_data_feeds())
    module = next(r for r in results if r.check_name == "data_feeds_module")
    assert module.status == "error", "a missing contract must not be graded as merely unhealthy"
    assert "no 'healthy' field" in module.message
    assert module.remediation


def test_a_healthy_snapshot_is_reported_as_ok(monkeypatch):
    import data_feed
    from security.diagnostics import DiagnosticsEngine

    monkeypatch.setattr(
        data_feed, "get_feed_status", lambda: {"healthy": True, "message": "Data feed healthy — 3/3 fresh"}
    )
    results = asyncio.run(DiagnosticsEngine()._check_data_feeds())
    module = next(r for r in results if r.check_name == "data_feeds_module")
    assert module.status == "ok"
    assert "3/3" in module.message


# ── A missing endpoint family must be a finding ──────────────────────────────


def test_all_required_route_families_are_registered():
    from security.diagnostics import DiagnosticsEngine

    results = asyncio.run(DiagnosticsEngine()._check_route_families())
    assert results[0].status == "ok", results[0].details


def test_a_missing_family_is_critical_and_names_the_page_it_breaks(monkeypatch):
    """What should have been on screen instead of "Could not load your
    subscription"."""
    import security.diagnostics as diag
    from security.diagnostics import DiagnosticsEngine

    monkeypatch.setattr(
        diag,
        "_REQUIRED_ROUTE_FAMILIES",
        [("/api/billing", "Settings → Billing, Wallet balance"), ("/api/gone", "a family that does not exist")],
    )
    results = asyncio.run(DiagnosticsEngine()._check_route_families())
    assert results[0].status == "critical"
    missing = results[0].details["missing"]
    assert len(missing) == 1
    assert "/api/gone" in missing[0]
    assert "does not exist" in missing[0], "the finding must say which page breaks"


def test_billing_is_among_the_families_that_are_checked():
    """The two panels that failed were both /api/billing. If that family ever
    goes missing again it must be named, not left to a user clicking around."""
    from security.diagnostics import _REQUIRED_ROUTE_FAMILIES

    prefixes = {p for p, _ in _REQUIRED_ROUTE_FAMILIES}
    for required in ("/api/billing", "/api/notifications", "/api/trading", "/api/auth"):
        assert required in prefixes, f"{required} is not covered"


def test_the_check_is_wired_into_the_full_run():
    """Guard against the check existing and never being called."""
    import inspect

    from security.diagnostics import DiagnosticsEngine

    src = inspect.getsource(DiagnosticsEngine.run_full_diagnostic)
    assert "_check_route_families()" in src


def test_the_superadmin_page_can_describe_the_new_check():
    from api.superadmin.diagnostics import _CHECK_DESCRIPTIONS

    assert "route_families" in _CHECK_DESCRIPTIONS
