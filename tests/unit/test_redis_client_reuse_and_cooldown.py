# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
tests/unit/test_redis_client_reuse_and_cooldown.py
==================================================
Two Redis clients that were rebuilt on every call, one of them on the order path.

**`core/idempotency.py::_redis`** constructed a fresh client and issued a
blocking `ping()` on every store operation. The idempotency layer performs two
or three of those per order, none of the clients were ever closed, and the whole
thing sits on the async order path — so each order opened several sockets that
were left to the garbage collector and blocked the event loop waiting on
round-trips it did not need.

**`rate_limiting/advanced.py::_get_redis`** grew a 30-second cooldown so a
Redis-less deployment would stop retrying on every request. The cooldown never
applied. Its failure path sets `_redis_client` to a sentinel but never assigns
`_redis_loop`, so the next call computes

    loop_changed = _redis_client is not None and running_loop is not _redis_loop

as True, takes the rebuild branch, and resets `_redis_retry_after = 0.0` —
putting the cooldown check permanently out of reach. With the per-request
`DefaultRateLimitMiddleware` now installed, that is a reconnect attempt and a
WARNING on every single request.
"""

from __future__ import annotations

import asyncio

import pytest

pytestmark = pytest.mark.unit


class TestIdempotencyReusesItsClient:
    def test_the_client_is_built_once(self, monkeypatch):
        import core.idempotency as idem

        calls = {"n": 0}

        class _Client:
            def ping(self):
                calls["n"] += 1
                return True

        monkeypatch.setattr(idem, "_CLIENT", None, raising=False)
        monkeypatch.setattr(idem, "_CLIENT_RESOLVED", False, raising=False)
        monkeypatch.setattr(idem, "_build_client", lambda: _Client(), raising=False)

        first = idem._redis()
        second = idem._redis()
        third = idem._redis()

        assert first is second is third, "a new client per store operation leaks sockets and blocks the order path"

    def test_an_unavailable_redis_is_not_retried_on_every_call(self, monkeypatch):
        import core.idempotency as idem

        attempts = {"n": 0}

        def _fail():
            attempts["n"] += 1
            raise RuntimeError("no redis")

        monkeypatch.setattr(idem, "_CLIENT", None, raising=False)
        monkeypatch.setattr(idem, "_CLIENT_RESOLVED", False, raising=False)
        monkeypatch.setattr(idem, "_build_client", _fail, raising=False)

        assert idem._redis() is None
        assert idem._redis() is None
        assert idem._redis() is None

        assert attempts["n"] == 1, "the in-process fallback must not re-probe per call"


class TestRateLimiterCooldownApplies:
    def test_the_loop_is_recorded_on_the_failure_path(self, monkeypatch):
        """Without this the cooldown branch is unreachable."""
        import rate_limiting.advanced as adv

        monkeypatch.setattr(adv, "_redis_client", None, raising=False)
        monkeypatch.setattr(adv, "_redis_available", False, raising=False)
        monkeypatch.setattr(adv, "_redis_loop", None, raising=False)
        monkeypatch.setattr(adv, "_redis_retry_after", 0.0, raising=False)

        async def _drive():
            monkeypatch.setattr(adv, "REDIS_URL", "redis://127.0.0.1:1/0")
            await adv._get_redis()
            return adv._redis_loop, adv._redis_retry_after

        loop_recorded, retry_after = asyncio.run(_drive())

        assert loop_recorded is not None, (
            "the failure path must record the loop, or loop_changed is True next call "
            "and wipes the cooldown it just set"
        )
        assert retry_after > 0

    def test_a_second_call_stays_on_the_fallback(self, monkeypatch):
        import rate_limiting.advanced as adv

        monkeypatch.setattr(adv, "_redis_client", None, raising=False)
        monkeypatch.setattr(adv, "_redis_available", False, raising=False)
        monkeypatch.setattr(adv, "_redis_loop", None, raising=False)
        monkeypatch.setattr(adv, "_redis_retry_after", 0.0, raising=False)
        monkeypatch.setattr(adv, "REDIS_URL", "redis://127.0.0.1:1/0")

        connects = {"n": 0}
        real_from_url = None

        async def _drive():
            nonlocal real_from_url
            import redis.asyncio as aioredis

            real_from_url = aioredis.from_url

            def _counting(*args, **kwargs):
                connects["n"] += 1
                return real_from_url(*args, **kwargs)

            monkeypatch.setattr(aioredis, "from_url", _counting)
            await adv._get_redis()
            await adv._get_redis()
            await adv._get_redis()

        asyncio.run(_drive())

        assert connects["n"] == 1, (
            f"reconnected {connects['n']} times inside the cooldown; with the per-request "
            f"rate-limit middleware that is a connection attempt and a WARNING per request"
        )


class TestTheDashboardRegistersOneServiceWorker:
    def test_no_hand_written_root_registration_remains(self):
        """vite-plugin-pwa already injects a correctly-scoped registerSW.js.

        The hand-written block registered '/sw.js' — a root path the SPA
        catch-all answers with HTML, so the registration fails — while the
        bundle is mounted at the /godmode/ base.
        """
        import re
        from pathlib import Path

        for path in ("dashboard/index.html", "dashboard/dist/index.html"):
            # Strip HTML comments first. Asserting on raw source makes the note
            # explaining *why* the registration was removed trip the check that
            # it was removed — a trap this session fell into four times.
            code = re.sub(r"<!--.*?-->", "", Path(path).read_text(), flags=re.DOTALL)
            assert "serviceWorker.register('/sw.js')" not in code, (
                f"{path} hand-registers a root-scoped service worker that duplicates "
                f"vite-plugin-pwa's injected registerSW.js and requests a path the SPA "
                f"catch-all serves as HTML"
            )

    def test_the_plugin_registration_is_still_present_in_the_build(self):
        from pathlib import Path

        dist = Path("dashboard/dist/index.html").read_text()
        assert "registerSW.js" in dist, "the real registration must survive"
