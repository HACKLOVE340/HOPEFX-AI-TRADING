# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
tests/unit/test_core_config_store.py
=====================================
Coverage tests for core/config_store.py.

Redis and DB are patched at the boundary — ConfigStore logic is exercised
with real code paths.
"""

from __future__ import annotations

from unittest.mock import MagicMock


from core.config_store import ConfigStore, config_store


# ── helpers ───────────────────────────────────────────────────────────────────


def _store_no_redis_no_db() -> ConfigStore:
    """ConfigStore where both Redis and DB are unavailable."""
    cs = ConfigStore()
    cs._redis = lambda: None
    cs._db_session = lambda: None
    return cs


def _store_with_redis(data: dict | None = None) -> tuple[ConfigStore, MagicMock]:
    """ConfigStore backed by a mock Redis client."""
    import json

    store: dict = {}
    if data:
        store.update({f"hopefx:config:{k}": json.dumps(v) for k, v in data.items()})

    r = MagicMock()
    r.get.side_effect = lambda key: store.get(key)
    r.set.side_effect = lambda key, val: store.__setitem__(key, val)
    r.delete.side_effect = lambda key: store.pop(key, None)
    r.publish.return_value = 1

    cs = ConfigStore()
    cs._redis = lambda: r
    cs._db_session = lambda: None
    return cs, r


# ── get — no backends ─────────────────────────────────────────────────────────


def test_get_returns_default_when_no_backends():
    cs = _store_no_redis_no_db()
    assert cs.get("missing_key", default="fallback") == "fallback"


def test_get_returns_none_default_when_not_set():
    cs = _store_no_redis_no_db()
    assert cs.get("missing_key") is None


# ── get — Redis hit ───────────────────────────────────────────────────────────


def test_get_from_redis():
    cs, _ = _store_with_redis({"my_key": {"a": 1}})
    result = cs.get("my_key")
    assert result == {"a": 1}


def test_get_returns_default_on_redis_miss():
    cs, _ = _store_with_redis()
    assert cs.get("no_such_key", default=99) == 99


# ── get — Redis error degrades to DB ─────────────────────────────────────────


def test_get_degrades_when_redis_raises():
    cs = ConfigStore()
    r = MagicMock()
    r.get.side_effect = ConnectionError("redis down")
    cs._redis = lambda: r
    cs._db_session = lambda: None
    # Should not raise — returns default
    assert cs.get("key", default="safe") == "safe"


# ── set — no backends ────────────────────────────────────────────────────────


def test_set_returns_false_when_no_db():
    cs = _store_no_redis_no_db()
    result = cs.set("key", {"x": 1})
    assert result is False


# ── set — Redis only (DB unavailable) ────────────────────────────────────────


def test_set_writes_to_redis_even_when_db_fails():
    cs, r = _store_with_redis()
    cs._db_session = lambda: None  # DB unavailable
    cs.set("cfg", {"v": 42})
    # Redis.set should have been called
    r.set.assert_called()


# ── set — Redis error is non-fatal ───────────────────────────────────────────


def test_set_redis_error_non_fatal():
    cs = ConfigStore()
    r = MagicMock()
    r.set.side_effect = ConnectionError("redis down")
    r.publish.side_effect = ConnectionError("redis down")
    cs._redis = lambda: r
    cs._db_session = lambda: None
    # Must not raise
    cs.set("key", "value")


# ── delete — no backends ─────────────────────────────────────────────────────


def test_delete_returns_false_when_no_db():
    cs = _store_no_redis_no_db()
    assert cs.delete("key") is False


# ── delete — Redis ────────────────────────────────────────────────────────────


def test_delete_removes_from_redis():
    cs, r = _store_with_redis({"del_key": "val"})
    cs._db_session = lambda: None
    cs.delete("del_key")
    r.delete.assert_called_once_with("hopefx:config:del_key")


def test_delete_redis_error_non_fatal():
    cs = ConfigStore()
    r = MagicMock()
    r.delete.side_effect = ConnectionError("redis down")
    cs._redis = lambda: r
    cs._db_session = lambda: None
    cs.delete("key")  # must not raise


# ── Redis key prefix ──────────────────────────────────────────────────────────


def test_redis_key_prefix():
    cs = ConfigStore()
    assert cs._redis_key("foo") == "hopefx:config:foo"


# ── DB helpers — no session ───────────────────────────────────────────────────


def test_db_get_returns_none_when_no_session():
    cs = ConfigStore()
    cs._db_session = lambda: None
    assert cs._db_get("key") is None


def test_db_set_returns_false_when_no_session():
    cs = ConfigStore()
    cs._db_session = lambda: None
    assert cs._db_set("key", "val") is False


def test_db_delete_returns_false_when_no_session():
    cs = ConfigStore()
    cs._db_session = lambda: None
    assert cs._db_delete("key") is False


# ── Redis warm-up from DB ─────────────────────────────────────────────────────


def test_get_warms_redis_from_db():
    """When Redis misses but DB has the value, Redis is warmed."""

    cs = ConfigStore()
    r = MagicMock()
    r.get.return_value = None  # Redis miss
    r.set = MagicMock()
    cs._redis = lambda: r

    # Patch _db_get to return a value
    cs._db_get = lambda key: {"warmed": True}

    result = cs.get("some_key")
    assert result == {"warmed": True}
    r.set.assert_called_once()


# ── Module-level singleton ────────────────────────────────────────────────────


def test_module_singleton_is_config_store():
    assert isinstance(config_store, ConfigStore)


def test_module_singleton_get_no_crash():
    # No Redis/DB in test env — should return default without raising
    result = config_store.get("nonexistent_test_key_xyz", default="ok")
    assert result == "ok"
