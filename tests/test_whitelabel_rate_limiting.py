# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
tests/test_whitelabel_rate_limiting.py
=======================================
Unit tests for whitelabel/rate_limiting.py — WhitelabelRateLimitMiddleware.

Covers:
- Requests on non-matching path prefix pass through unchanged
- Requests without X-API-Key header pass through unchanged
- Requests with an unknown API key pass through unchanged
- Known key: counters increment and rate-limit headers are set
- Minute-window limit exceeded → 429 with Retry-After
- Day-window limit exceeded → 429 with Retry-After
- Window reset: counters clear after the window expires
"""

from __future__ import annotations

import time

import pytest
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import PlainTextResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from whitelabel.api_auth import _key_store, register_api_key
from whitelabel.config import TierName
from whitelabel.rate_limiting import WhitelabelRateLimitMiddleware, _counters

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

TEST_KEY = "hfx_test_ratelimit_key_abc123"
TEST_TENANT = "tenant-rl-test"
TEST_TIER = TierName.STARTER  # 60 req/min, 5000 req/day


def _make_app(path_prefix: str = "/api/v1/wl") -> Starlette:
    """Build a minimal Starlette app with the middleware attached."""

    async def endpoint(request: Request) -> PlainTextResponse:
        return PlainTextResponse("ok")

    app = Starlette(routes=[Route("/{path:path}", endpoint)])
    app.add_middleware(WhitelabelRateLimitMiddleware, path_prefix=path_prefix)
    return app


def _register_key() -> str:
    """Register TEST_KEY in the key store and return its hash."""
    key_hash = register_api_key(TEST_KEY, TEST_TENANT, TEST_TIER)
    return key_hash


def _clear_counters(key_hash: str) -> None:
    """Reset in-memory counters for a key so tests are independent."""
    if key_hash in _counters:
        _counters[key_hash] = {"min": [0, 0.0], "day": [0, 0.0]}


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def isolated_key_store():
    """Ensure each test starts with a clean key store entry for TEST_KEY."""
    key_hash = _register_key()
    _clear_counters(key_hash)
    yield key_hash
    # Cleanup: remove the key and its counters after each test
    _key_store.pop(key_hash, None)
    _counters.pop(key_hash, None)


# ---------------------------------------------------------------------------
# Pass-through cases
# ---------------------------------------------------------------------------


class TestPassThrough:
    def test_non_matching_path_passes_through(self, isolated_key_store):
        """Requests outside path_prefix are never inspected."""
        app = _make_app(path_prefix="/api/v1/wl")
        client = TestClient(app, raise_server_exceptions=True)
        # /public is not under /api/v1/wl — should pass through regardless of key
        resp = client.get("/public/health", headers={"X-API-Key": TEST_KEY})
        assert resp.status_code == 200
        assert resp.text == "ok"
        # No rate-limit headers should be present
        assert "X-RateLimit-Limit-Minute" not in resp.headers

    def test_missing_api_key_passes_through(self, isolated_key_store):
        """Requests on the prefix path but without X-API-Key pass through."""
        app = _make_app()
        client = TestClient(app, raise_server_exceptions=True)
        resp = client.get("/api/v1/wl/data")
        assert resp.status_code == 200
        assert "X-RateLimit-Limit-Minute" not in resp.headers

    def test_unknown_api_key_passes_through(self, isolated_key_store):
        """An unregistered key is not rate-limited (auth dep handles 401)."""
        app = _make_app()
        client = TestClient(app, raise_server_exceptions=True)
        resp = client.get("/api/v1/wl/data", headers={"X-API-Key": "hfx_unknown_key"})
        assert resp.status_code == 200
        assert "X-RateLimit-Limit-Minute" not in resp.headers


# ---------------------------------------------------------------------------
# Happy-path: counters and headers
# ---------------------------------------------------------------------------


class TestRateLimitHeaders:
    def test_known_key_sets_ratelimit_headers(self, isolated_key_store):
        """A valid key on the prefix path gets rate-limit response headers."""
        app = _make_app()
        client = TestClient(app, raise_server_exceptions=True)
        resp = client.get("/api/v1/wl/data", headers={"X-API-Key": TEST_KEY})
        assert resp.status_code == 200
        assert "X-RateLimit-Limit-Minute" in resp.headers
        assert "X-RateLimit-Remaining-Minute" in resp.headers
        assert "X-RateLimit-Limit-Day" in resp.headers
        assert "X-RateLimit-Remaining-Day" in resp.headers

    def test_remaining_decrements_on_each_request(self, isolated_key_store):
        """Remaining counter decreases with each request."""
        app = _make_app()
        client = TestClient(app, raise_server_exceptions=True)

        resp1 = client.get("/api/v1/wl/data", headers={"X-API-Key": TEST_KEY})
        resp2 = client.get("/api/v1/wl/data", headers={"X-API-Key": TEST_KEY})

        remaining1 = int(resp1.headers["X-RateLimit-Remaining-Minute"])
        remaining2 = int(resp2.headers["X-RateLimit-Remaining-Minute"])
        assert remaining2 == remaining1 - 1

    def test_limit_header_matches_tier_config(self, isolated_key_store):
        """X-RateLimit-Limit-Minute reflects the STARTER tier limit (60)."""
        from whitelabel.config import get_tier_config

        tier_cfg = get_tier_config(TEST_TIER)
        app = _make_app()
        client = TestClient(app, raise_server_exceptions=True)
        resp = client.get("/api/v1/wl/data", headers={"X-API-Key": TEST_KEY})
        assert int(resp.headers["X-RateLimit-Limit-Minute"]) == tier_cfg.requests_per_minute
        assert int(resp.headers["X-RateLimit-Limit-Day"]) == tier_cfg.requests_per_day


# ---------------------------------------------------------------------------
# Rate-limit enforcement
# ---------------------------------------------------------------------------


class TestRateLimitEnforcement:
    def test_minute_limit_exceeded_returns_429(self, isolated_key_store):
        """Exceeding requests_per_minute returns 429 with window=minute."""
        from whitelabel.config import get_tier_config

        key_hash = isolated_key_store
        tier_cfg = get_tier_config(TEST_TIER)

        # Pre-fill the minute counter to the limit
        _counters[key_hash]["min"] = [tier_cfg.requests_per_minute, time.monotonic()]

        app = _make_app()
        client = TestClient(app, raise_server_exceptions=True)
        resp = client.get("/api/v1/wl/data", headers={"X-API-Key": TEST_KEY})

        assert resp.status_code == 429
        body = resp.json()
        assert body["error"] == "rate_limit_exceeded"
        assert body["window"] == "minute"
        assert body["limit"] == tier_cfg.requests_per_minute
        assert "retry_after_seconds" in body
        assert "Retry-After" in resp.headers

    def test_day_limit_exceeded_returns_429(self, isolated_key_store):
        """Exceeding requests_per_day returns 429 with window=day."""
        from whitelabel.config import get_tier_config

        key_hash = isolated_key_store
        tier_cfg = get_tier_config(TEST_TIER)

        # Minute counter is fine; day counter is at the limit
        _counters[key_hash]["min"] = [0, time.monotonic()]
        _counters[key_hash]["day"] = [tier_cfg.requests_per_day, time.monotonic()]

        app = _make_app()
        client = TestClient(app, raise_server_exceptions=True)
        resp = client.get("/api/v1/wl/data", headers={"X-API-Key": TEST_KEY})

        assert resp.status_code == 429
        body = resp.json()
        assert body["error"] == "rate_limit_exceeded"
        assert body["window"] == "day"
        assert body["limit"] == tier_cfg.requests_per_day
        assert "Retry-After" in resp.headers

    def test_minute_limit_checked_before_day_limit(self, isolated_key_store):
        """When both limits are exceeded, minute limit is reported first."""
        from whitelabel.config import get_tier_config

        key_hash = isolated_key_store
        tier_cfg = get_tier_config(TEST_TIER)

        _counters[key_hash]["min"] = [tier_cfg.requests_per_minute, time.monotonic()]
        _counters[key_hash]["day"] = [tier_cfg.requests_per_day, time.monotonic()]

        app = _make_app()
        client = TestClient(app, raise_server_exceptions=True)
        resp = client.get("/api/v1/wl/data", headers={"X-API-Key": TEST_KEY})

        assert resp.status_code == 429
        assert resp.json()["window"] == "minute"

    def test_retry_after_header_is_positive_integer(self, isolated_key_store):
        """Retry-After header is a positive integer string."""
        from whitelabel.config import get_tier_config

        key_hash = isolated_key_store
        tier_cfg = get_tier_config(TEST_TIER)
        _counters[key_hash]["min"] = [tier_cfg.requests_per_minute, time.monotonic()]

        app = _make_app()
        client = TestClient(app, raise_server_exceptions=True)
        resp = client.get("/api/v1/wl/data", headers={"X-API-Key": TEST_KEY})

        retry_after = int(resp.headers["Retry-After"])
        assert 0 < retry_after <= 60


# ---------------------------------------------------------------------------
# Window reset behaviour
# ---------------------------------------------------------------------------


class TestWindowReset:
    def test_minute_window_resets_after_expiry(self, isolated_key_store):
        """Counter resets when the minute window has elapsed."""
        from whitelabel.config import get_tier_config

        key_hash = isolated_key_store
        tier_cfg = get_tier_config(TEST_TIER)

        # Set counter at limit but with a reset timestamp 61 seconds ago
        old_ts = time.monotonic() - 61.0
        _counters[key_hash]["min"] = [tier_cfg.requests_per_minute, old_ts]

        app = _make_app()
        client = TestClient(app, raise_server_exceptions=True)
        # Window has expired — counter should reset and request should succeed
        resp = client.get("/api/v1/wl/data", headers={"X-API-Key": TEST_KEY})
        assert resp.status_code == 200

    def test_day_window_resets_after_expiry(self, isolated_key_store):
        """Counter resets when the day window has elapsed."""
        from whitelabel.config import get_tier_config

        key_hash = isolated_key_store
        tier_cfg = get_tier_config(TEST_TIER)

        old_ts = time.monotonic() - 86401.0
        _counters[key_hash]["min"] = [0, time.monotonic()]
        _counters[key_hash]["day"] = [tier_cfg.requests_per_day, old_ts]

        app = _make_app()
        client = TestClient(app, raise_server_exceptions=True)
        resp = client.get("/api/v1/wl/data", headers={"X-API-Key": TEST_KEY})
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Custom path prefix
# ---------------------------------------------------------------------------


class TestCustomPathPrefix:
    def test_custom_prefix_is_respected(self, isolated_key_store):
        """Middleware only gates the configured path_prefix."""
        app = _make_app(path_prefix="/wl/v2")
        client = TestClient(app, raise_server_exceptions=True)

        # /api/v1/wl is NOT the configured prefix — should pass through
        resp = client.get("/api/v1/wl/data", headers={"X-API-Key": TEST_KEY})
        assert resp.status_code == 200
        assert "X-RateLimit-Limit-Minute" not in resp.headers

        # /wl/v2 IS the configured prefix — should be gated
        resp2 = client.get("/wl/v2/data", headers={"X-API-Key": TEST_KEY})
        assert resp2.status_code == 200
        assert "X-RateLimit-Limit-Minute" in resp2.headers
