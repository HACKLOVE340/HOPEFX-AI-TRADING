# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""What the token blacklist does when Redis answers badly.

`_TokenBlacklist` is what makes logout, session revocation and "sign out
everywhere" real. Without it a JWT is valid until it expires, whatever the user
clicked.

Both of its Redis calls are wrapped in `except Exception` that logs at DEBUG
and falls through to an in-memory set. That fallback is sound for a process
that has only ever used memory. It is **not** sound after Redis has been
working: the JTIs live in Redis, the local set is empty, so a read failure
turns `is_revoked` into `False` — a revoked token reads as valid (STRIDE-S).

The same is true in reverse for `revoke`: a write that fails lands in a
per-process set, so in a multi-worker deployment the token stays live on every
other worker.

Neither behaviour is changed here — failing closed would sign every user out
during a Redis blip, which is a policy call for the owner (recorded as a task).
What is asserted is that the system **says** so, at a level someone sees. DEBUG
is off in production, so today the one moment revocation silently stops working
is the one moment nobody is told (F248).
"""

from __future__ import annotations

import logging

import pytest

pytestmark = [pytest.mark.unit]


class _RedisThatBreaksAfterWorking:
    """Answers normally until `fail` is set, then raises like a dropped link."""

    def __init__(self):
        self.store: dict[str, str] = {}
        self.fail = False

    def setex(self, key, _ttl, val):
        if self.fail:
            raise ConnectionError("redis link dropped")
        self.store[key] = val

    def exists(self, key):
        if self.fail:
            raise ConnectionError("redis link dropped")
        return 1 if key in self.store else 0

    def ping(self):
        return True


@pytest.fixture
def blacklist(monkeypatch):
    from auth.service import _TokenBlacklist

    bl = _TokenBlacklist()
    fake = _RedisThatBreaksAfterWorking()
    # Installed directly, and _try_connect neutered, so the test controls the
    # link rather than racing a real probe.
    monkeypatch.setattr(bl, "_try_connect", lambda: None)
    bl._redis = fake
    return bl, fake


class TestTheHarnessIsLive:
    """Every assertion below is about a degraded path. If the healthy path is
    not working, none of them mean anything."""

    def test_a_revoked_token_reads_as_revoked_while_redis_is_healthy(self, blacklist):
        bl, _ = blacklist
        bl.revoke("jti-abc", 60)

        assert bl.is_revoked("jti-abc") is True
        assert bl.is_revoked("jti-never-issued") is False


class TestAReadFailureIsAnnounced:
    def test_a_revoked_token_currently_reads_as_valid_when_redis_breaks(self, blacklist):
        """Pinned as observed behaviour, not endorsed. If this ever starts
        failing closed, that is a deliberate change and this test says so."""
        bl, fake = blacklist
        bl.revoke("jti-abc", 60)
        fake.fail = True

        assert bl.is_revoked("jti-abc") is False, (
            "revocation now fails closed — a policy change; update this test and the owner task"
        )

    def test_the_failure_is_logged_above_debug(self, blacklist, caplog):
        bl, fake = blacklist
        bl.revoke("jti-abc", 60)
        fake.fail = True

        caplog.set_level(logging.INFO, logger="auth.service")
        bl.is_revoked("jti-abc")

        loud = [r for r in caplog.records if r.levelno >= logging.ERROR]
        assert loud, "a revocation check silently failed open and logged nothing above DEBUG"

    def test_the_message_names_the_consequence(self, blacklist, caplog):
        bl, fake = blacklist
        bl.revoke("jti-abc", 60)
        fake.fail = True

        caplog.set_level(logging.INFO, logger="auth.service")
        bl.is_revoked("jti-abc")

        text = " ".join(r.getMessage().lower() for r in caplog.records if r.levelno >= logging.ERROR)
        assert "revok" in text and ("valid" in text or "not check" in text or "unchecked" in text), (
            f"the log names the fault but not what it means for the caller: {text!r}"
        )


class TestAWriteFailureIsAnnounced:
    def test_a_failed_revoke_is_logged_above_debug(self, blacklist, caplog):
        bl, fake = blacklist
        fake.fail = True

        caplog.set_level(logging.INFO, logger="auth.service")
        bl.revoke("jti-xyz", 60)

        loud = [r for r in caplog.records if r.levelno >= logging.ERROR]
        assert loud, "a revocation that reached only this process logged nothing above DEBUG"

    def test_the_write_fallback_is_still_local_so_the_token_is_revoked_here(self, blacklist):
        """The fallback is not useless — it holds for this worker. The log is
        what tells an operator it holds for *only* this worker."""
        bl, fake = blacklist
        fake.fail = True

        bl.revoke("jti-xyz", 60)

        assert bl.is_revoked("jti-xyz") is True
