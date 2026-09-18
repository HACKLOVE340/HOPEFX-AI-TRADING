# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
The paper broker must not carry state between test runs.

``PaperTradingBroker`` persists orders and positions to Redis so they survive a
restart — correct in production, where a deploy must not lose open paper
positions. ``__init__`` already tries to protect tests from that:

    elif os.getenv("APP_ENV", "").lower() == "test":
        # In test mode, auto-isolate each instance to prevent cross-test
        # pollution when a real Redis is available in the test environment.
        self._redis_namespace = str(uuid.uuid4())

but it is an ``elif``: it only applies when ``namespace is None``. The account
registry always passes ``namespace=f"user:{user_id}"``, so the guard is bypassed
on precisely the path the isolation tests exercise. Two users get two stable,
permanent namespaces, and everything they do accumulates in Redis for ever.

What that cost: ``test_trading_endpoints_are_isolated.py`` — a regression test
for a reported user-isolation defect — failed with "alice's order is visible in
bob's positions". It was not alice's order. It was **bob's own** position, 13
lots accumulated across earlier runs of the same test, reloaded from
``hopefx:user:bob:positions:XAUUSD``. The registry and the endpoints were both
correct; the state was stale.

It only surfaced once ``.env`` stopped being loaded into the test session: that
file set ``REDIS_PASSWORD``, Redis auth failed, persistence silently did nothing,
and the tests passed for that reason instead.

The fix keeps per-user namespaces distinct *within* a run — so the isolation
tests still do real work — while guaranteeing nothing survives *between* runs.
"""

from __future__ import annotations


import pytest

from brokers.paper_trading import PaperTradingBroker

pytestmark = pytest.mark.unit


def test_an_explicit_namespace_is_still_isolated_in_test_mode():
    """The bypass. An explicit namespace must not opt out of test isolation —
    that is the path the account registry always takes."""
    b = PaperTradingBroker(user_id="alice", namespace="user:alice")
    assert b._redis_namespace != "user:alice", (
        "an explicit namespace bypassed test isolation; this broker writes to a namespace that outlives the test run"
    )


def test_two_users_remain_distinguishable_within_one_run():
    """Isolation between runs must not collapse isolation between users, or the
    isolation tests would pass vacuously for a new reason."""
    a = PaperTradingBroker(user_id="alice", namespace="user:alice")
    b = PaperTradingBroker(user_id="bob", namespace="user:bob")
    assert a._redis_namespace != b._redis_namespace


def test_the_same_user_reaches_the_same_namespace_within_one_run():
    """Within a run the broker must still find its own state — otherwise a
    second resolve of the same user would see an empty book."""
    a1 = PaperTradingBroker(user_id="alice", namespace="user:alice")
    a2 = PaperTradingBroker(user_id="alice", namespace="user:alice")
    assert a1._redis_namespace == a2._redis_namespace


def test_the_namespace_is_marked_as_test_state():
    """A key written by a test must be identifiable as such, so it can be swept
    up afterwards rather than accumulating for ever. 424 orphaned key sets had
    built up in the shared Redis before this."""
    b = PaperTradingBroker(user_id="alice", namespace="user:alice")
    assert b._redis_namespace.startswith(PaperTradingBroker.TEST_NAMESPACE_PREFIX)


def test_production_namespaces_are_untouched(monkeypatch):
    """The guard must key off test mode only. In production an explicit
    namespace has to be honoured exactly, or a deploy loses every open
    position."""
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    monkeypatch.setattr(PaperTradingBroker, "_in_test_mode", staticmethod(lambda: False))
    monkeypatch.setenv("APP_ENV", "production")

    b = PaperTradingBroker(user_id="user-42", namespace="user:user-42")
    assert b._redis_namespace == "user:user-42"


def test_production_default_namespace_is_still_the_user_id(monkeypatch):
    monkeypatch.setattr(PaperTradingBroker, "_in_test_mode", staticmethod(lambda: False))
    monkeypatch.setenv("APP_ENV", "production")

    b = PaperTradingBroker(user_id="user-42")
    assert b._redis_namespace == "user-42"


def test_the_run_token_is_stable_within_a_process():
    """One token per process: keys from this run must be sweepable as a group."""
    assert PaperTradingBroker._test_run_token() == PaperTradingBroker._test_run_token()
    assert len(PaperTradingBroker._test_run_token()) >= 8
