# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
tests/unit/test_redis_tls_private_destinations.py
==================================================
The production TLS check made the shipped stack unrunnable.

``docker-compose.yml`` sets ``APP_ENV`` to ``production`` by default and
``REDIS_URL`` to ``redis://:<pw>@redis:6379/0`` — plaintext, to the Compose
service named ``redis``. ``_enforce_tls`` raised on exactly that, so on the
server:

    RedisTickWriter: connection failed: Redis TLS required in production …
    MultiSourceTickFeed: RedisTickWriter did not start — ticks will NOT be
    persisted or broadcast.

There was no configuration that worked. ``rediss://`` fails because
``redis:7-alpine`` serves no TLS, and ``REDIS_FORCE_TLS=true`` only rewrites the
scheme to ``rediss://``, so it fails the same way. The stack could not persist a
single tick as shipped.

The rule is narrowed, not dropped. TLS exists so credentials never cross a
network somebody can listen on; loopback, RFC-1918 and a single-label Compose
service name are not that network. A routable host on plaintext still raises —
which is the case the check was written for and the one these tests pin hardest.
"""

from __future__ import annotations

import importlib

import pytest

pytestmark = pytest.mark.unit


@pytest.fixture
def redis_client(monkeypatch):
    """A freshly imported module so the once-per-process log latches reset."""
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.delenv("IS_FORCE_TLS", raising=False)
    monkeypatch.delenv("REDIS_FORCE_TLS", raising=False)
    import cache.redis_client as mod

    return importlib.reload(mod)


# ── Destinations that must still be refused ──────────────────────────────────


@pytest.mark.parametrize(
    "url",
    [
        "redis://redis.example.com:6379/0",
        "redis://:pw@cache.production.example.net:6379/0",
        # Globally routable addresses only. 198.51.100.0/24 and 203.0.113.0/24
        # look like plausible "public" examples but Python classifies them as
        # private — they are IANA documentation ranges and are not globally
        # reachable, so allowing plaintext to them is correct.
        "redis://8.8.8.8:6379/0",
        "redis://1.1.1.1:6379/0",
        "redis://my-redis.cache.amazonaws.com:6379/0",
    ],
)
def test_plaintext_to_a_routable_host_still_raises_in_production(redis_client, url):
    """The reason the check exists. Narrowing it must not touch this."""
    with pytest.raises(RuntimeError, match="TLS required"):
        redis_client._enforce_tls(url)


def test_a_public_host_is_not_classified_as_private(redis_client):
    assert redis_client.is_private_redis_host("redis://redis.example.com:6379/0") is False
    assert redis_client.is_private_redis_host("redis://8.8.8.8:6379/0") is False


# ── Destinations that cannot be eavesdropped ─────────────────────────────────


@pytest.mark.parametrize(
    "url",
    [
        "redis://:password@redis:6379/0",  # the shipped compose URL
        "redis://redis:6379/0",
        "redis://localhost:6379/0",
        "redis://127.0.0.1:6379/0",
        "redis://[::1]:6379/0",
        "redis://10.0.0.5:6379/0",
        "redis://172.17.0.2:6379/0",  # docker bridge
        "redis://192.168.1.50:6379/0",
        "redis://hopefx-redis:6379/0",  # container name, no dot
    ],
)
def test_private_destinations_are_allowed_in_production(redis_client, url):
    assert redis_client.is_private_redis_host(url) is True
    assert redis_client._enforce_tls(url) == url, "the URL must be returned unchanged, not upgraded"


def test_the_exact_compose_configuration_starts(redis_client, monkeypatch):
    """The end-to-end premise: APP_ENV=production plus the compose REDIS_URL.

    This raised, which is why the tick writer never started and prices froze.
    """
    url = "redis://:s3cret@redis:6379/0"
    assert redis_client._enforce_tls(url) == url


# ── Behaviour that must not change ───────────────────────────────────────────


def test_rediss_is_left_alone_everywhere(redis_client):
    for url in ("rediss://redis:6379/0", "rediss://redis.example.com:6379/0"):
        assert redis_client._enforce_tls(url) == url


def test_force_tls_still_upgrades(redis_client, monkeypatch):
    monkeypatch.setenv("REDIS_FORCE_TLS", "true")
    assert redis_client._enforce_tls("redis://redis.example.com:6379/0").startswith("rediss://")


def test_non_production_is_unaffected(monkeypatch):
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.delenv("IS_FORCE_TLS", raising=False)
    monkeypatch.delenv("REDIS_FORCE_TLS", raising=False)
    import cache.redis_client as mod

    mod = importlib.reload(mod)
    url = "redis://redis.example.com:6379/0"
    assert mod._enforce_tls(url) == url  # warns, does not raise


def test_a_malformed_url_is_not_treated_as_private(redis_client):
    """Fail closed: if the destination cannot be parsed, do not assume it is safe."""
    assert redis_client.is_private_redis_host("") is False
    assert redis_client.is_private_redis_host("not a url") is False
    assert redis_client.is_private_redis_host("redis://") is False
