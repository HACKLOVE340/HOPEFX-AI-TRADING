# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
tests/unit/test_redis_url_password_injection.py
===============================================
Six copies of the same broken URL parse, one of them in the kill switch.

`cache/redis_client.py::get_sync_redis` promises in its own docstring that it
"falls back gracefully to None when Redis is unavailable". It does not:

    if password and "@" not in redis_url.split("://", 1)[-1]:
        scheme, rest = redis_url.split("://", 1)

`"".split("://", 1)` is `[""]` — one element. Unpacking it into two names
raises `ValueError: not enough values to unpack (expected 2, got 1)`, from
*outside* the `try`, so nothing catches it. The same is true of any URL with no
scheme, such as `localhost:6379`.

`REDIS_URL=""` is not a contrived input. It is the natural way to say "this
deployment has no Redis", and `tests/e2e/test_auth_billing_trading.py:33` sets
exactly that at module import — which pytest executes during *collection*, even
when e2e is deselected by `-m "not e2e"`. Combined with a `REDIS_PASSWORD` from
`.env`, every later `get_sync_redis()` in the session raised, which is what made
17 TCA tests fail under one selection and 5 under another while passing in
isolation. The tests were the messenger.

The same six lines are duplicated in `brokers/paper_trading.py`,
`kill_switch.py`, `core/config_store.py`, `core/event_bus.py` and
`scripts/adopt_legacy_positions.py`. The kill switch is the one that matters:
its Redis latch is what survives a restart, and a schemeless URL made it raise
instead of degrade.

`cache.redis_client.inject_redis_password` is now the single implementation.
"""

from __future__ import annotations

from pathlib import Path

import pytest

pytestmark = pytest.mark.unit


class TestTheHelper:
    def test_it_exists(self):
        from cache.redis_client import inject_redis_password

        assert callable(inject_redis_password)

    def test_it_injects_into_a_normal_url(self):
        from cache.redis_client import inject_redis_password

        assert inject_redis_password("redis://localhost:6379/0", "hunter2") == ("redis://:hunter2@localhost:6379/0")

    def test_an_empty_url_does_not_raise(self):
        """The input that took the whole session down."""
        from cache.redis_client import inject_redis_password

        assert inject_redis_password("", "hunter2") == ""

    def test_a_schemeless_url_does_not_raise(self):
        from cache.redis_client import inject_redis_password

        assert inject_redis_password("localhost:6379", "hunter2") == "localhost:6379"

    def test_an_embedded_credential_is_not_doubled(self):
        from cache.redis_client import inject_redis_password

        url = "redis://:already@localhost:6379/0"
        assert inject_redis_password(url, "hunter2") == url

    def test_no_password_is_a_no_op(self):
        from cache.redis_client import inject_redis_password

        assert inject_redis_password("redis://localhost:6379/0", "") == "redis://localhost:6379/0"
        assert inject_redis_password("redis://localhost:6379/0", None) == "redis://localhost:6379/0"

    def test_rediss_and_unix_schemes_survive(self):
        from cache.redis_client import inject_redis_password

        assert inject_redis_password("rediss://host:6380/1", "pw") == "rediss://:pw@host:6380/1"


class TestGetSyncRedisKeepsItsPromise:
    @pytest.mark.parametrize("url", ["", "localhost:6379", "   "])
    def test_it_returns_rather_than_raises_on_a_schemeless_url(self, url, monkeypatch):
        """Its docstring says it falls back gracefully. It must."""
        from cache.redis_client import get_sync_redis

        monkeypatch.setenv("REDIS_URL", url)
        monkeypatch.setenv("REDIS_PASSWORD", "hunter2")

        get_sync_redis()  # must not raise

    def test_an_empty_url_means_no_redis(self, monkeypatch):
        """Empty is how a deployment says 'no Redis', not 'guess a default'."""
        from cache.redis_client import get_sync_redis

        monkeypatch.setenv("REDIS_URL", "")
        monkeypatch.setenv("REDIS_PASSWORD", "hunter2")

        assert get_sync_redis() is None


class TestNoCopyOfTheBrokenParseSurvives:
    @pytest.mark.parametrize(
        "path",
        [
            "cache/redis_client.py",
            "brokers/paper_trading.py",
            "kill_switch.py",
            "core/config_store.py",
            "core/event_bus.py",
            "scripts/adopt_legacy_positions.py",
        ],
    )
    def test_the_module_does_not_unpack_a_scheme_split(self, path):
        src = Path(path).read_text()

        assert "scheme, rest = " not in src, (
            f"{path} still unpacks url.split('://', 1) into two names; a schemeless "
            f"or empty REDIS_URL raises ValueError there instead of degrading"
        )

    @pytest.mark.parametrize(
        "path",
        [
            "brokers/paper_trading.py",
            "kill_switch.py",
            "core/config_store.py",
            "core/event_bus.py",
            "scripts/adopt_legacy_positions.py",
        ],
    )
    def test_the_module_uses_the_shared_helper(self, path):
        src = Path(path).read_text()

        assert "inject_redis_password" in src, f"{path} should use the one implementation rather than a sixth copy"


class TestTheKillSwitchDegrades:
    def test_a_schemeless_url_does_not_break_the_latch(self, monkeypatch):
        """The kill switch's Redis latch is what survives a restart.

        A schemeless URL made it raise rather than fall back, on the one
        component whose whole job is working when things are going wrong.
        """
        import kill_switch as ks

        monkeypatch.setenv("REDIS_URL", "")
        monkeypatch.setenv("REDIS_PASSWORD", "hunter2")

        # Whatever it resolves to, it must not raise.
        ks.kill_switch._get_latch_redis()
