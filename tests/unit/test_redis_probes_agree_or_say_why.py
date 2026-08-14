# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
tests/unit/test_redis_probes_agree_or_say_why.py
================================================
Four pages reported four different answers about the same Redis.

    System Health      Redis  HEALTHY 6.92ms
    Reliability        data_feeds_redis  OK (0 active keys)
    Diagnostics        redis: connection healthy  OK
    Health Engine      Redis Cache  ERROR — "Redis client not initialised — check REDIS_URL"

Three probes call ``get_sync_redis()``; the fourth calls ``await get_redis()``.
**Only the async client has a circuit breaker** — ``get_redis`` fast-fails and
returns ``None`` while ``redis_breaker.is_open``, and ``get_sync_redis`` has no
breaker at all. So the two can legitimately disagree, and neither page said
which client it had tested. The operator is left choosing which page to believe
about a component the tick feed, the WebSocket broadcaster and the cache all
depend on.

The message made it worse. ``get_redis`` returns ``None`` for reasons that need
completely different fixes:

* the circuit breaker is open — the URL is fine, wait for the probe window;
* Redis is not configured — set ``REDIS_URL``;
* Redis is configured but unreachable — check the server and credentials;

and every one of them was reported as *"check REDIS_URL"*. The
configured-but-unreachable case was also logged as *"no connection configured
(REDIS_CLUSTER_HOSTS / REDIS_SENTINEL_HOSTS / REDIS_URL)"* — naming three
variables as missing when one of them was set and working as far as
configuration goes.

Note what is deliberately **not** done here: the probes are not forced to agree.
They test genuinely different clients, and papering over that would replace a
visible contradiction with an invisible one. They now each name the client and
the reason, so a disagreement is readable instead of baffling.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.unit


# ── The structural cause ─────────────────────────────────────────────────────


def test_only_the_async_client_has_a_circuit_breaker():
    """The reason the two clients can disagree. If the sync client ever gains a
    breaker, or the async one loses it, the disagreement's explanation changes
    and these tests should be revisited."""
    import inspect

    from cache import redis_client

    async_src = inspect.getsource(redis_client.get_redis)
    sync_src = inspect.getsource(redis_client.get_sync_redis)

    assert "redis_breaker" in async_src, "the async client lost its circuit breaker"
    assert "breaker" not in sync_src, "the sync client gained a breaker — the probes may now agree"


# ── The reason is recorded, not guessed ──────────────────────────────────────


def test_an_open_breaker_is_reported_as_such_not_as_a_bad_url(monkeypatch):
    """The exact defect: a tripped breaker rendered as "check REDIS_URL"."""
    import asyncio

    from cache import redis_client

    class _OpenBreaker:
        is_open = True

        def _seconds_until_probe(self):
            return 42.0

    import resilience.service_circuit_breakers as breakers

    monkeypatch.setattr(breakers, "redis_breaker", _OpenBreaker(), raising=False)
    monkeypatch.setattr(redis_client, "_redis_instance", None, raising=False)

    result = asyncio.run(redis_client.get_redis())
    assert result is None

    code, explanation = redis_client.redis_unavailable_reason()
    assert code == "circuit_open"
    assert "breaker" in explanation.lower()
    assert "not necessarily wrong" in explanation, "the operator is still being pointed at the URL"


def test_missing_configuration_is_distinguished_from_an_unreachable_server(monkeypatch):
    """Two faults, two fixes. They used to share one message."""
    import asyncio

    from cache import redis_client

    for var in ("REDIS_URL", "REDIS_CLUSTER_HOSTS", "REDIS_SENTINEL_HOSTS"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setattr(redis_client, "_redis_instance", None, raising=False)
    monkeypatch.setattr(redis_client, "_no_config_warned", False, raising=False)

    asyncio.run(redis_client.get_redis())
    code, explanation = redis_client.redis_unavailable_reason()

    assert code in ("not_configured", "none_available")
    assert "REDIS_URL" in explanation, "must name the variable to set"


def test_a_configured_but_unreachable_server_says_so(monkeypatch):
    """The log used to claim no connection was configured while REDIS_URL was
    set — naming three variables as missing when one was present."""
    import asyncio

    from cache import redis_client

    monkeypatch.setenv("REDIS_URL", "redis://nonexistent-host-for-tests:6379/0")
    monkeypatch.delenv("REDIS_CLUSTER_HOSTS", raising=False)
    monkeypatch.delenv("REDIS_SENTINEL_HOSTS", raising=False)
    monkeypatch.setattr(redis_client, "_redis_instance", None, raising=False)
    monkeypatch.setattr(redis_client, "_no_config_warned", False, raising=False)

    asyncio.run(redis_client.get_redis())
    code, explanation = redis_client.redis_unavailable_reason()

    assert code in ("connect_failed", "none_available")
    assert "configured but" in explanation, f"reported as unconfigured: {explanation}"


@pytest.mark.parametrize("code", ["circuit_open", "connect_failed", "not_configured", "none_available", "unknown"])
def test_every_documented_reason_code_is_reachable_in_source(code):
    """Guards the docstring's contract against drift."""
    import inspect

    from cache import redis_client

    src = inspect.getsource(redis_client)
    assert f'"{code}"' in src, f"reason code {code} is documented but never set"


# ── The probes name their client ─────────────────────────────────────────────


def test_the_async_probe_names_the_async_client():
    import infrastructure.health_engine as he

    from tests.support.source_text import code_only

    src = code_only(he)
    assert "redis_unavailable_reason" in src, "the health engine still guesses the reason"
    assert '"client": "async"' in src, "the probe does not say which client it tested"
    assert "check REDIS_URL" not in src, "the misleading hard-coded message is back"


def test_the_sync_probe_names_the_sync_client():
    import inspect

    import api.superadmin.reliability as rel

    src = inspect.getsource(rel._probe_redis)  # single function — no module prose to strip
    assert '"client": "sync"' in src
    assert "sync Redis client unavailable" in src


def test_neither_probe_claims_a_cause_it_did_not_check():
    """ "Redis client not initialised" was a conclusion, not an observation."""
    import api.superadmin.reliability as rel
    import infrastructure.health_engine as he

    from tests.support.source_text import code_only

    for mod in (he, rel):
        assert "Redis client not initialised — check REDIS_URL" not in code_only(mod)


# ── The accessor itself ──────────────────────────────────────────────────────


def test_the_reason_accessor_returns_a_pair():
    from cache.redis_client import redis_unavailable_reason

    value = redis_unavailable_reason()
    assert isinstance(value, tuple) and len(value) == 2
    assert all(isinstance(v, str) for v in value)


def test_the_reason_is_never_empty():
    """An empty explanation would put the probes back where they started."""
    from cache.redis_client import redis_unavailable_reason

    code, explanation = redis_unavailable_reason()
    assert code and explanation
