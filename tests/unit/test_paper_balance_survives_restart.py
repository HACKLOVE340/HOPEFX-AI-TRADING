# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
tests/unit/test_paper_balance_survives_restart.py
==================================================
Realised P&L did not survive a restart, and nothing said so.

``PaperTradingBroker`` persists positions and orders to Redis specifically so a
deploy or a crash does not lose the open book — the comment at
``_init_redis_state`` says as much: *"Without this, a restart (deploy, crash,
OOM) silently loses all open paper positions, making P&L tracking unreliable."*

The balance those positions settle into was never persisted. ``self.balance``
is set to ``self.initial_balance`` in ``__init__`` and moved in exactly two
places — commission and realised P&L on close — neither of which wrote
anywhere durable. ``_persist_trade`` writes a ``Trade`` row to the database,
but nothing ever reads those rows back to reconstruct a balance.

So every restart replayed the surviving positions against starting capital.
An account that had made $3,000 over a month came back at exactly
``INITIAL_BALANCE``, and an account that had lost $3,000 came back at the same
number. No error, no warning: from the process's point of view a fresh account
is a perfectly ordinary thing to be, and $10,000.00 looks like a real balance.

This is the pattern that made the per-user account work worth doing at all — a
user's own account is not much use if its P&L history evaporates on deploy.
"""

from __future__ import annotations

import asyncio
import json

import pytest

pytestmark = pytest.mark.unit


class _FakeRedis:
    """Just enough Redis for RedisStateStore, with contents that outlive a
    broker instance — which is the whole point of the test."""

    def __init__(self) -> None:
        self.kv: dict[str, str] = {}
        self.sets: dict[str, set[str]] = {}

    def set(self, key, value, ex=None):
        self.kv[key] = value

    def get(self, key):
        return self.kv.get(key)

    def delete(self, key):
        self.kv.pop(key, None)

    def sadd(self, key, member):
        self.sets.setdefault(key, set()).add(member)

    def srem(self, key, member):
        self.sets.get(key, set()).discard(member)

    def smembers(self, key):
        return set(self.sets.get(key, set()))


@pytest.fixture
def store_factory():
    from execution.redis_state import RedisStateStore

    redis = _FakeRedis()

    def _make(namespace: str = "user:alice"):
        return RedisStateStore(redis, namespace=namespace), redis

    return _make


# ── The store itself ─────────────────────────────────────────────────────────


def test_a_saved_balance_round_trips(store_factory):
    store, _ = store_factory()
    store.save_balance(12_345.67)
    assert store.load_balance() == pytest.approx(12_345.67)


def test_an_unsaved_balance_is_none_not_zero(store_factory):
    """None means "this namespace has no history" and must keep
    ``initial_balance``. Zero means "wiped out" and must restore as zero.
    Collapsing the two would hand a blown-up account its starting capital
    back."""
    store, _ = store_factory()
    assert store.load_balance() is None


def test_a_zero_balance_restores_as_zero(store_factory):
    store, _ = store_factory()
    store.save_balance(0.0)
    assert store.load_balance() == 0.0


def test_balance_is_scoped_by_namespace(store_factory):
    """Two users' balances must not be the same key. This is the same failure
    the account registry exists to prevent, one layer down."""
    alice, redis = store_factory("user:alice")
    from execution.redis_state import RedisStateStore

    bob = RedisStateStore(redis, namespace="user:bob")
    alice.save_balance(9_000.0)
    bob.save_balance(11_000.0)
    assert alice.load_balance() == 9_000.0
    assert bob.load_balance() == 11_000.0


def test_the_balance_key_has_no_expiry(store_factory):
    """Positions and orders carry a 7-day TTL; a balance must not. An expired
    balance is not a gap in the record, it is a wrong number that looks
    entirely plausible."""
    from execution.redis_state import _balance_key

    store, redis = store_factory("user:alice")
    calls: list = []
    original = redis.set
    redis.set = lambda k, v, ex=None: (calls.append((k, ex)), original(k, v, ex))[1]

    store.save_balance(500.0)
    assert calls == [(_balance_key("user:alice"), None)]


def test_a_corrupt_balance_payload_reads_as_none(store_factory):
    """Fail to the documented "no history" state rather than raising into a
    broker that is trying to boot."""
    store, redis = store_factory("user:alice")
    from execution.redis_state import _balance_key

    redis.kv[_balance_key("user:alice")] = "{not json"
    assert store.load_balance() is None

    redis.kv[_balance_key("user:alice")] = json.dumps({"wrong_field": 1})
    assert store.load_balance() is None


# ── The broker end to end ────────────────────────────────────────────────────


def _broker(namespace: str, redis, *, initial_balance: float = 10_000.0):
    """A broker wired to the shared fake Redis, bypassing _init_redis_state's
    real connection attempt."""
    from brokers.paper_trading import PaperTradingBroker
    from execution.redis_state import RedisStateStore

    broker = PaperTradingBroker(initial_balance=initial_balance, namespace=namespace)
    broker._redis_state = RedisStateStore(redis, namespace=namespace)
    return broker


def test_realised_pnl_survives_a_restart():
    """The defect, end to end: close a winning trade, restart, keep the win."""
    redis = _FakeRedis()

    first = _broker("user:alice", redis)
    first.balance = 10_000.0
    first.balance += 2_500.0  # stand-in for a closed winner
    first._save_balance_to_redis()

    second = _broker("user:alice", redis)
    assert second.balance == 10_000.0, "a fresh instance starts at initial_balance"
    second._restore_state_from_redis()

    assert second.balance == pytest.approx(12_500.0), (
        "the account came back at its starting capital — every closed trade was erased"
    )
    assert second.equity == pytest.approx(12_500.0)


def test_a_loss_survives_a_restart_too():
    """A restart that resets a losing account to starting capital is the more
    dangerous direction: it hides the loss and re-arms the risk budget."""
    redis = _FakeRedis()

    first = _broker("user:bob", redis)
    first.balance = 10_000.0 - 3_200.0
    first._save_balance_to_redis()

    second = _broker("user:bob", redis)
    second._restore_state_from_redis()
    assert second.balance == pytest.approx(6_800.0)


def test_a_new_account_keeps_its_initial_balance():
    """Nothing persisted → no substitution. The restore must not zero a fresh
    account."""
    redis = _FakeRedis()
    broker = _broker("user:carol", redis, initial_balance=25_000.0)
    broker._restore_state_from_redis()
    assert broker.balance == pytest.approx(25_000.0)


def test_two_users_restore_their_own_balances():
    redis = _FakeRedis()
    for ns, bal in (("user:alice", 12_500.0), ("user:bob", 6_800.0)):
        b = _broker(ns, redis)
        b.balance = bal
        b._save_balance_to_redis()

    for ns, bal in (("user:alice", 12_500.0), ("user:bob", 6_800.0)):
        b = _broker(ns, redis)
        b._restore_state_from_redis()
        assert b.balance == pytest.approx(bal), f"{ns} restored another user's balance"


def test_commission_is_persisted_when_charged():
    """Commission is the other place the balance moves, and it moves on every
    fill — not only on close."""
    redis = _FakeRedis()
    broker = _broker("user:dave", redis)
    broker._commission_per_lot = 7.0
    charged = broker._deduct_commission(broker._standard_lot_units)
    assert charged == pytest.approx(7.0)

    restored = _broker("user:dave", redis)
    restored._restore_state_from_redis()
    assert restored.balance == pytest.approx(10_000.0 - 7.0)


def test_persistence_failure_never_breaks_a_fill():
    """A durability aid must not be able to reject a trade."""
    redis = _FakeRedis()
    broker = _broker("user:erin", redis)

    def _explode(_balance):
        raise OSError("redis is down")

    broker._redis_state.save_balance = _explode
    broker.balance = 11_000.0
    broker._save_balance_to_redis()  # must not raise
    assert broker.balance == 11_000.0


def test_a_broker_with_no_redis_still_works():
    from brokers.paper_trading import PaperTradingBroker

    broker = PaperTradingBroker(initial_balance=10_000.0, namespace="user:frank")
    broker._redis_state = None
    broker._save_balance_to_redis()  # must not raise
    assert broker.balance == 10_000.0


# ── Async store parity ───────────────────────────────────────────────────────


def test_the_async_store_has_the_same_balance_api():
    """The two stores are a duplicated pair; every previous divergence between
    them has been a defect. Whatever the sync one persists, the async one must."""
    from execution.redis_state import AsyncRedisStateStore, RedisStateStore

    for name in ("save_balance", "load_balance"):
        assert hasattr(AsyncRedisStateStore, name), f"AsyncRedisStateStore is missing {name}"
        assert hasattr(RedisStateStore, name)


def test_the_async_store_round_trips_a_balance():
    from execution.redis_state import AsyncRedisStateStore

    class _AsyncFake:
        def __init__(self):
            self.kv = {}

        async def set(self, key, value, ex=None):
            self.kv[key] = value

        async def get(self, key):
            return self.kv.get(key)

    async def _run():
        store = AsyncRedisStateStore(_AsyncFake(), namespace="user:alice")
        assert await store.load_balance() is None
        await store.save_balance(4_321.0)
        return await store.load_balance()

    assert asyncio.run(_run()) == pytest.approx(4_321.0)
