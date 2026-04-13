# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""Tests for execution/redis_state.py — RedisStateStore, AsyncRedisStateStore."""

from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest

from execution.redis_state import AsyncRedisStateStore, RedisStateStore, create_state_store


def _mock_redis() -> MagicMock:
    r = MagicMock()
    r.set.return_value = True
    r.get.return_value = None
    r.delete.return_value = 1
    r.sadd.return_value = 1
    r.srem.return_value = 1
    r.smembers.return_value = set()
    return r


class TestRedisStateStore:
    def test_save_order_calls_set(self):
        r = _mock_redis()
        store = RedisStateStore(r)
        store.save_order({"id": "ord1", "symbol": "XAUUSD", "side": "buy"})
        r.set.assert_called_once()
        r.sadd.assert_called_once()

    def test_save_order_no_id_skipped(self):
        r = _mock_redis()
        store = RedisStateStore(r)
        store.save_order({"symbol": "XAUUSD"})  # no id
        r.set.assert_not_called()

    def test_remove_order(self):
        r = _mock_redis()
        store = RedisStateStore(r)
        store.remove_order("ord1")
        r.delete.assert_called_once()
        r.srem.assert_called_once()

    def test_load_orders_empty(self):
        r = _mock_redis()
        r.smembers.return_value = set()
        store = RedisStateStore(r)
        orders = store.load_orders()
        assert orders == []

    def test_load_orders_with_data(self):
        r = _mock_redis()
        r.smembers.return_value = {b"ord1"}
        r.get.return_value = json.dumps({"id": "ord1", "symbol": "XAUUSD"}).encode()
        store = RedisStateStore(r)
        orders = store.load_orders()
        assert len(orders) == 1
        assert orders[0]["id"] == "ord1"

    def test_save_position(self):
        r = _mock_redis()
        store = RedisStateStore(r)
        store.save_position({"symbol": "XAUUSD", "side": "long", "quantity": 1.0})
        r.set.assert_called_once()
        r.sadd.assert_called_once()

    def test_remove_position(self):
        r = _mock_redis()
        store = RedisStateStore(r)
        store.remove_position("XAUUSD")
        r.delete.assert_called_once()
        r.srem.assert_called_once()

    def test_load_positions_empty(self):
        r = _mock_redis()
        r.smembers.return_value = set()
        store = RedisStateStore(r)
        positions = store.load_positions()
        assert positions == []

    def test_load_state_on_boot(self):
        r = _mock_redis()
        r.smembers.return_value = set()
        store = RedisStateStore(r)
        state = store.load_state_on_boot()
        assert "orders" in state
        assert "positions" in state

    def test_connection_error_handled(self):
        r = _mock_redis()
        r.set.side_effect = ConnectionError("Redis down")
        store = RedisStateStore(r)
        # Should not raise — errors are logged
        store.save_order({"id": "ord1", "symbol": "XAUUSD"})

    def test_save_order_uses_order_id_key(self):
        r = _mock_redis()
        store = RedisStateStore(r)
        store.save_order({"order_id": "ord99", "symbol": "XAUUSD"})
        call_args = r.set.call_args[0]
        assert "ord99" in call_args[0]


class TestAsyncRedisStateStore:
    @pytest.mark.asyncio
    async def test_save_order_async(self):
        r = MagicMock()
        r.set = MagicMock(return_value=None)
        r.sadd = MagicMock(return_value=None)

        async def _async_true(*a, **kw):
            return True

        r.set = MagicMock(side_effect=_async_true)

        store = AsyncRedisStateStore(r)
        # Just verify it doesn't crash on construction
        assert store._r is r

    @pytest.mark.asyncio
    async def test_load_state_on_boot_async(self):
        r = MagicMock()

        async def _smembers(key):
            return set()

        r.smembers = _smembers
        store = AsyncRedisStateStore(r)
        state = await store.load_state_on_boot()
        assert "orders" in state
        assert "positions" in state


class TestCreateStateStore:
    def test_sync_store(self):
        r = _mock_redis()
        store = create_state_store(r, async_client=False)
        assert isinstance(store, RedisStateStore)

    def test_async_store(self):
        r = _mock_redis()
        store = create_state_store(r, async_client=True)
        assert isinstance(store, AsyncRedisStateStore)
