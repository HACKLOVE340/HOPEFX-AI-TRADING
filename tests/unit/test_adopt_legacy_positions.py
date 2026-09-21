# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
tests/unit/test_adopt_legacy_positions.py
==========================================
Tests for the migration that carries the shared paper book into per-user
accounts.

The shared ``PaperTradingBroker`` persisted to ``hopefx:paper:*``. Per-user
brokers read ``hopefx:user:<id>:*``. After the upgrade nothing opens the old
keys, so every open position stops appearing anywhere — not deleted, just
unreachable. This script moves them, and these tests hold it to the two
properties that matter for a tool that rewrites positions:

* it never moves anything the operator did not name, and
* it never merges two accounts' holdings, because merging is precisely the
  defect the per-user work exists to remove.
"""

from __future__ import annotations

import json

import pytest

from scripts.adopt_legacy_positions import (
    Assignment,
    apply_moves,
    describe_legacy_book,
    discover_user_namespaces,
    load_mapping_file,
    parse_assignment,
    plan_moves,
    write_backup,
)

pytestmark = pytest.mark.unit


class _FakeRedis:
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

    def scan_iter(self, match, count=100):
        import fnmatch

        yield from (k for k in list(self.kv) + list(self.sets) if fnmatch.fnmatch(k, match))


def _seed_legacy(redis, positions):
    from execution.redis_state import RedisStateStore

    store = RedisStateStore(redis, namespace="paper")
    for p in positions:
        store.save_position(p)
    return store


def _pos(symbol="XAUUSD", quantity=2.0, side="BUY", entry=2400.0):
    return {
        "id": f"pos-{symbol}",
        "symbol": symbol,
        "side": side,
        "quantity": quantity,
        "entry_price": entry,
        "current_price": entry + 5,
        "unrealized_pnl": 10.0,
    }


@pytest.fixture
def redis():
    return _FakeRedis()


# ── Parsing ──────────────────────────────────────────────────────────────────


def test_whole_position_assignment():
    a = parse_assignment("XAUUSD=user-42")
    assert (a.symbol, a.user_id, a.quantity) == ("XAUUSD", "user-42", None)


def test_split_assignment():
    a = parse_assignment("XAUUSD=user-42:1.5")
    assert (a.symbol, a.user_id, a.quantity) == ("XAUUSD", "user-42", 1.5)


@pytest.mark.parametrize("spec", ["XAUUSD", "=user-42", "XAUUSD=", "XAUUSD=u:abc", "XAUUSD=u:0", "XAUUSD=u:-1"])
def test_malformed_assignments_are_rejected(spec):
    """A typo here rewrites somebody's positions. It must fail, not improvise."""
    with pytest.raises(ValueError):
        parse_assignment(spec)


def test_mapping_file_accepts_both_shapes(tmp_path):
    path = tmp_path / "m.json"
    path.write_text(
        json.dumps({"XAUUSD": "user-42", "EURUSD": [{"user_id": "a", "quantity": 1}, {"user_id": "b", "quantity": 2}]})
    )
    out = load_mapping_file(path)
    assert len(out) == 3
    assert any(a.symbol == "XAUUSD" and a.quantity is None for a in out)
    assert sum(a.quantity for a in out if a.symbol == "EURUSD") == 3


# ── Reading the legacy book ──────────────────────────────────────────────────


def test_it_reads_positions_orders_and_balance(redis):
    from execution.redis_state import RedisStateStore, _balance_key

    _seed_legacy(redis, [_pos("XAUUSD"), _pos("EURUSD", 1.0)])
    RedisStateStore(redis, namespace="paper").save_order({"id": "o1", "symbol": "XAUUSD"})
    redis.kv[_balance_key("paper")] = json.dumps({"balance": 12_345.0})

    book = describe_legacy_book(redis, "paper")
    assert {p["symbol"] for p in book["positions"]} == {"XAUUSD", "EURUSD"}
    assert len(book["orders"]) == 1
    assert book["balance"] == 12_345.0


def test_a_never_persisted_balance_reads_as_none(redis):
    _seed_legacy(redis, [_pos()])
    assert describe_legacy_book(redis, "paper")["balance"] is None


def test_it_discovers_existing_user_namespaces(redis):
    from execution.redis_state import RedisStateStore

    RedisStateStore(redis, namespace="user:alice").save_position(_pos())
    RedisStateStore(redis, namespace="user:bob").save_balance(1.0)
    assert discover_user_namespaces(redis) == ["user:alice", "user:bob"]


# ── Planning ─────────────────────────────────────────────────────────────────


def test_a_whole_assignment_moves_the_whole_quantity(redis):
    _seed_legacy(redis, [_pos("XAUUSD", 2.0)])
    book = describe_legacy_book(redis, "paper")
    moves, problems = plan_moves(book, [Assignment("XAUUSD", "alice", None)])
    assert problems == []
    assert len(moves) == 1
    assert moves[0]["quantity"] == 2.0


def test_an_unknown_symbol_is_reported_not_invented(redis):
    _seed_legacy(redis, [_pos("XAUUSD")])
    book = describe_legacy_book(redis, "paper")
    moves, problems = plan_moves(book, [Assignment("GBPUSD", "alice", None)])
    assert moves == []
    assert any("GBPUSD" in p for p in problems)


def test_an_oversized_split_is_refused(redis):
    """Handing out more than the book holds would conjure quantity out of
    nothing."""
    _seed_legacy(redis, [_pos("XAUUSD", 2.0)])
    book = describe_legacy_book(redis, "paper")
    moves, problems = plan_moves(book, [Assignment("XAUUSD", "alice", 1.5), Assignment("XAUUSD", "bob", 1.0)])
    assert moves == []
    assert any("only 2" in p for p in problems)


def test_an_undersized_split_says_what_stays_behind(redis):
    _seed_legacy(redis, [_pos("XAUUSD", 2.0)])
    book = describe_legacy_book(redis, "paper")
    moves, problems = plan_moves(book, [Assignment("XAUUSD", "alice", 1.5)])
    assert len(moves) == 1
    assert any("stays in the legacy namespace" in p for p in problems)


def test_mixing_a_whole_assignment_with_a_split_is_refused(redis):
    _seed_legacy(redis, [_pos("XAUUSD", 2.0)])
    book = describe_legacy_book(redis, "paper")
    moves, problems = plan_moves(book, [Assignment("XAUUSD", "alice", None), Assignment("XAUUSD", "bob", 1.0)])
    assert moves == []
    assert any("pick one" in p for p in problems)


# ── Applying ─────────────────────────────────────────────────────────────────


def test_dry_run_writes_nothing(redis):
    from execution.redis_state import RedisStateStore

    _seed_legacy(redis, [_pos("XAUUSD", 2.0)])
    book = describe_legacy_book(redis, "paper")
    moves, _ = plan_moves(book, [Assignment("XAUUSD", "alice", None)])

    before = dict(redis.kv), {k: set(v) for k, v in redis.sets.items()}
    log = apply_moves(redis, "paper", moves, dry_run=True)

    assert redis.kv == before[0] and {k: set(v) for k, v in redis.sets.items()} == before[1]
    assert any("WOULD WRITE" in line for line in log)
    assert RedisStateStore(redis, namespace="user:alice").load_positions() == []


def test_apply_moves_the_position_and_clears_the_legacy_entry(redis):
    from execution.redis_state import RedisStateStore

    _seed_legacy(redis, [_pos("XAUUSD", 2.0)])
    book = describe_legacy_book(redis, "paper")
    moves, _ = plan_moves(book, [Assignment("XAUUSD", "alice", None)])
    apply_moves(redis, "paper", moves, dry_run=False)

    alice = RedisStateStore(redis, namespace="user:alice").load_positions()
    assert len(alice) == 1
    assert alice[0]["symbol"] == "XAUUSD"
    assert alice[0]["quantity"] == 2.0
    assert alice[0]["_adopted_from"] == "hopefx:paper"
    assert RedisStateStore(redis, namespace="paper").load_positions() == []


def test_it_refuses_to_merge_into_an_account_that_already_holds_the_symbol(redis):
    """The exact defect the per-user work removes. A migration that recreated
    it would be worse than doing nothing."""
    from execution.redis_state import RedisStateStore

    RedisStateStore(redis, namespace="user:alice").save_position(_pos("XAUUSD", 5.0))
    _seed_legacy(redis, [_pos("XAUUSD", 2.0)])
    book = describe_legacy_book(redis, "paper")
    moves, _ = plan_moves(book, [Assignment("XAUUSD", "alice", None)])
    log = apply_moves(redis, "paper", moves, dry_run=False)

    assert any("REFUSED" in line for line in log)
    held = RedisStateStore(redis, namespace="user:alice").load_positions()
    assert len(held) == 1 and held[0]["quantity"] == 5.0, "alice's position was modified"
    assert len(RedisStateStore(redis, namespace="paper").load_positions()) == 1, (
        "the legacy entry was dropped even though the move was refused"
    )


def test_a_split_writes_both_sides_and_clears_the_legacy_entry(redis):
    from execution.redis_state import RedisStateStore

    _seed_legacy(redis, [_pos("XAUUSD", 3.0)])
    book = describe_legacy_book(redis, "paper")
    moves, problems = plan_moves(book, [Assignment("XAUUSD", "alice", 2.0), Assignment("XAUUSD", "bob", 1.0)])
    assert problems == []
    apply_moves(redis, "paper", moves, dry_run=False)

    assert RedisStateStore(redis, namespace="user:alice").load_positions()[0]["quantity"] == 2.0
    assert RedisStateStore(redis, namespace="user:bob").load_positions()[0]["quantity"] == 1.0
    assert RedisStateStore(redis, namespace="paper").load_positions() == []


def test_a_partial_assignment_leaves_the_remainder_in_place(redis):
    from execution.redis_state import RedisStateStore

    _seed_legacy(redis, [_pos("XAUUSD", 3.0)])
    book = describe_legacy_book(redis, "paper")
    moves, _ = plan_moves(book, [Assignment("XAUUSD", "alice", 1.0)])
    log = apply_moves(redis, "paper", moves, dry_run=False)

    assert any("kept XAUUSD" in line for line in log)
    assert len(RedisStateStore(redis, namespace="paper").load_positions()) == 1


def test_running_it_twice_is_a_no_op(redis):
    from execution.redis_state import RedisStateStore

    _seed_legacy(redis, [_pos("XAUUSD", 2.0)])
    for _ in range(2):
        book = describe_legacy_book(redis, "paper")
        moves, problems = plan_moves(book, [Assignment("XAUUSD", "alice", None)])
        apply_moves(redis, "paper", moves, dry_run=False)

    held = RedisStateStore(redis, namespace="user:alice").load_positions()
    assert len(held) == 1 and held[0]["quantity"] == 2.0
    assert problems, "the second pass should report the symbol as already moved"


def test_untouched_symbols_stay_untouched(redis):
    from execution.redis_state import RedisStateStore

    _seed_legacy(redis, [_pos("XAUUSD", 2.0), _pos("EURUSD", 1.0)])
    book = describe_legacy_book(redis, "paper")
    moves, _ = plan_moves(book, [Assignment("XAUUSD", "alice", None)])
    apply_moves(redis, "paper", moves, dry_run=False)

    left = RedisStateStore(redis, namespace="paper").load_positions()
    assert [p["symbol"] for p in left] == ["EURUSD"]


# ── Backup ───────────────────────────────────────────────────────────────────


def test_the_backup_captures_the_whole_legacy_namespace(redis, tmp_path):
    from execution.redis_state import RedisStateStore, _balance_key

    _seed_legacy(redis, [_pos("XAUUSD", 2.0)])
    RedisStateStore(redis, namespace="paper").save_order({"id": "o1", "symbol": "XAUUSD"})
    redis.kv[_balance_key("paper")] = json.dumps({"balance": 999.0})

    book = describe_legacy_book(redis, "paper")
    out = tmp_path / "backup.json"
    write_backup(book, out, "paper")

    saved = json.loads(out.read_text())
    assert saved["namespace"] == "paper"
    assert saved["balance"] == 999.0
    assert len(saved["positions"]) == 1
    assert len(saved["orders"]) == 1
