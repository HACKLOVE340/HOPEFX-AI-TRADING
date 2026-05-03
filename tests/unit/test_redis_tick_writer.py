# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
tests/unit/test_redis_tick_writer.py
======================================
Unit tests for data_feed/redis_tick_writer.py — RedisTickWriter.

Uses fakeredis.aioredis so the full pipeline, SETEX, PUBLISH, RPUSH, LTRIM
code paths run against a real in-process Redis implementation.
No mocks of internal methods.
"""
from __future__ import annotations

import json
import time
from unittest.mock import AsyncMock, patch

import fakeredis.aioredis as faio
import pytest

from data_feed.redis_tick_writer import (
    CH_TICK,
    DL_TICK_KEY_PREFIX,
    LEGACY_QUEUE,
    PRICE_KEY_PREFIX,
    PUBSUB_CHANNEL_PREFIX,
    TICK_KEY_PREFIX,
    RedisTickWriter,
    build_tick_payload,
    get_tick_writer,
)


# ── Helpers ───────────────────────────────────────────────────────────────────

async def _make_writer(ttl: int = 30) -> tuple[RedisTickWriter, faio.FakeRedis]:
    """Return a connected RedisTickWriter backed by fakeredis."""
    redis = faio.FakeRedis()
    writer = RedisTickWriter(tick_key_ttl=ttl)
    writer._redis = redis
    return writer, redis


# ── build_tick_payload ────────────────────────────────────────────────────────


class TestBuildTickPayload:
    def test_required_fields(self):
        p = build_tick_payload("XAUUSD", 1950.0, "yfinance")
        assert p["symbol"] == "XAUUSD"
        assert p["price"] == 1950.0
        assert p["source"] == "yfinance"
        assert "ts" in p
        assert "timestamp" in p

    def test_ts_is_recent(self):
        before = time.time()
        p = build_tick_payload("XAUUSD", 1950.0, "yfinance")
        after = time.time()
        assert before <= p["ts"] <= after

    def test_bid_ask_optional(self):
        p = build_tick_payload("XAUUSD", 1950.0, "yfinance")
        assert "bid" not in p
        assert "ask" not in p

    def test_bid_ask_included_when_provided(self):
        p = build_tick_payload("XAUUSD", 1950.0, "yfinance", bid=1949.5, ask=1950.5)
        assert p["bid"] == 1949.5
        assert p["ask"] == 1950.5

    def test_timestamp_is_iso_string(self):
        p = build_tick_payload("XAUUSD", 1950.0, "yfinance")
        # Must be parseable as ISO 8601
        from datetime import datetime
        dt = datetime.fromisoformat(p["timestamp"])
        assert dt is not None


# ── RedisTickWriter construction ──────────────────────────────────────────────


class TestRedisTickWriterInit:
    def test_default_ttl(self):
        w = RedisTickWriter()
        assert w._ttl == 30

    def test_custom_ttl(self):
        w = RedisTickWriter(tick_key_ttl=60)
        assert w._ttl == 60

    def test_initial_counts(self):
        w = RedisTickWriter()
        assert w._write_count == 0
        assert w._error_count == 0

    def test_status_disconnected(self):
        w = RedisTickWriter()
        s = w.status()
        assert s["redis_connected"] is False
        assert s["write_count"] == 0
        assert s["error_count"] == 0


# ── connect ───────────────────────────────────────────────────────────────────


class TestRedisTickWriterConnect:
    @pytest.mark.asyncio
    async def test_connect_returns_false_when_redis_unavailable(self):
        """connect() must return False (not raise) when Redis is unreachable.

        Patches both the async get_redis and the sync fakeredis fallback so
        that no in-process substitute is returned, simulating a fully
        unavailable Redis environment.
        """
        import cache.redis_client as rc_mod

        w = RedisTickWriter()
        # Disable the async client AND the fakeredis fallback so connect()
        # truly has no Redis to connect to.
        with (
            patch.object(rc_mod, "get_redis", new=AsyncMock(return_value=None)),
            patch.object(rc_mod, "_fakeredis_instance", None),
            patch.dict("sys.modules", {"fakeredis": None, "fakeredis.aioredis": None}),
        ):
            result = await w.connect()
        assert result is False
        assert w._redis is None

    @pytest.mark.asyncio
    async def test_status_after_manual_inject(self):
        w, _ = await _make_writer()
        s = w.status()
        assert s["redis_connected"] is True


# ── write ─────────────────────────────────────────────────────────────────────


class TestRedisTickWriterWrite:
    @pytest.mark.asyncio
    async def test_write_returns_true(self):
        w, _ = await _make_writer()
        ok = await w.write("XAUUSD", 1950.0, "yfinance")
        assert ok is True

    @pytest.mark.asyncio
    async def test_write_increments_count(self):
        w, _ = await _make_writer()
        await w.write("XAUUSD", 1950.0, "yfinance")
        await w.write("XAUUSD", 1951.0, "yfinance")
        assert w._write_count == 2

    @pytest.mark.asyncio
    async def test_tick_key_set(self):
        w, redis = await _make_writer()
        await w.write("XAUUSD", 1950.0, "yfinance")
        raw = await redis.get(f"{TICK_KEY_PREFIX}:XAUUSD")
        assert raw is not None
        data = json.loads(raw)
        assert data["symbol"] == "XAUUSD"
        assert data["price"] == 1950.0
        assert data["source"] == "yfinance"

    @pytest.mark.asyncio
    async def test_dl_tick_key_set(self):
        w, redis = await _make_writer()
        await w.write("EURUSD", 1.0875, "alpha_vantage")
        raw = await redis.get(f"{DL_TICK_KEY_PREFIX}:EURUSD")
        assert raw is not None
        data = json.loads(raw)
        assert data["symbol"] == "EURUSD"
        assert data["price"] == pytest.approx(1.0875)

    @pytest.mark.asyncio
    async def test_price_key_set(self):
        w, redis = await _make_writer()
        await w.write("BTCUSD", 65000.0, "twelve_data")
        raw = await redis.get(f"{PRICE_KEY_PREFIX}:BTCUSD")
        assert raw is not None
        data = json.loads(raw)
        assert data["symbol"] == "BTCUSD"

    @pytest.mark.asyncio
    async def test_legacy_queue_populated(self):
        w, redis = await _make_writer()
        await w.write("XAUUSD", 1950.0, "yfinance")
        length = await redis.llen(LEGACY_QUEUE)
        assert length == 1

    @pytest.mark.asyncio
    async def test_legacy_queue_trimmed(self):
        """Queue must not exceed legacy_queue_max entries."""
        w, redis = await _make_writer()
        w._queue_max = 5
        for i in range(10):
            await w.write("XAUUSD", 1950.0 + i, "yfinance")
        length = await redis.llen(LEGACY_QUEUE)
        assert length <= 5

    @pytest.mark.asyncio
    async def test_multiple_symbols_independent_keys(self):
        w, redis = await _make_writer()
        await w.write("XAUUSD", 1950.0, "yfinance")
        await w.write("EURUSD", 1.0875, "yfinance")
        raw_xau = await redis.get(f"{TICK_KEY_PREFIX}:XAUUSD")
        raw_eur = await redis.get(f"{TICK_KEY_PREFIX}:EURUSD")
        assert raw_xau is not None
        assert raw_eur is not None
        assert json.loads(raw_xau)["price"] == 1950.0
        assert json.loads(raw_eur)["price"] == pytest.approx(1.0875)

    @pytest.mark.asyncio
    async def test_write_with_bid_ask(self):
        w, redis = await _make_writer()
        await w.write("XAUUSD", 1950.5, "twelve_data", bid=1950.0, ask=1951.0)
        raw = await redis.get(f"{TICK_KEY_PREFIX}:XAUUSD")
        data = json.loads(raw)
        assert data["bid"] == 1950.0
        assert data["ask"] == 1951.0

    @pytest.mark.asyncio
    async def test_write_returns_false_when_disconnected(self):
        w = RedisTickWriter()
        # _redis is None — must return False without raising.
        ok = await w.write("XAUUSD", 1950.0, "yfinance")
        assert ok is False

    @pytest.mark.asyncio
    async def test_error_count_increments_on_redis_failure(self):
        w, redis = await _make_writer()
        # Corrupt the redis reference to force a pipeline error.
        w._redis = object()  # type: ignore — not a real Redis client
        ok = await w.write("XAUUSD", 1950.0, "yfinance")
        assert ok is False
        assert w._error_count >= 1


# ── read_latest ───────────────────────────────────────────────────────────────


class TestRedisTickWriterReadLatest:
    @pytest.mark.asyncio
    async def test_read_latest_after_write(self):
        w, _ = await _make_writer()
        await w.write("XAUUSD", 1950.0, "yfinance")
        tick = await w.read_latest("XAUUSD")
        assert tick is not None
        assert tick["symbol"] == "XAUUSD"
        assert tick["price"] == 1950.0

    @pytest.mark.asyncio
    async def test_read_latest_returns_none_on_miss(self):
        w, _ = await _make_writer()
        tick = await w.read_latest("UNKNOWN")
        assert tick is None

    @pytest.mark.asyncio
    async def test_read_latest_returns_none_when_disconnected(self):
        w = RedisTickWriter()
        tick = await w.read_latest("XAUUSD")
        assert tick is None

    @pytest.mark.asyncio
    async def test_read_latest_most_recent_price(self):
        w, _ = await _make_writer()
        await w.write("XAUUSD", 1950.0, "yfinance")
        await w.write("XAUUSD", 1955.0, "yfinance")
        tick = await w.read_latest("XAUUSD")
        # Latest write wins.
        assert tick["price"] == 1955.0


# ── get_tick_age ──────────────────────────────────────────────────────────────


class TestRedisTickWriterGetTickAge:
    @pytest.mark.asyncio
    async def test_tick_age_is_small_after_write(self):
        w, _ = await _make_writer()
        await w.write("XAUUSD", 1950.0, "yfinance")
        age = await w.get_tick_age("XAUUSD")
        assert age is not None
        assert 0.0 <= age < 5.0  # written just now

    @pytest.mark.asyncio
    async def test_tick_age_none_on_miss(self):
        w, _ = await _make_writer()
        age = await w.get_tick_age("UNKNOWN")
        assert age is None

    @pytest.mark.asyncio
    async def test_tick_age_none_when_disconnected(self):
        w = RedisTickWriter()
        age = await w.get_tick_age("XAUUSD")
        assert age is None


# ── close ─────────────────────────────────────────────────────────────────────


class TestRedisTickWriterClose:
    @pytest.mark.asyncio
    async def test_close_clears_redis_ref(self):
        w, _ = await _make_writer()
        assert w._redis is not None
        await w.close()
        assert w._redis is None

    @pytest.mark.asyncio
    async def test_close_idempotent(self):
        w, _ = await _make_writer()
        await w.close()
        await w.close()  # must not raise


# ── status ────────────────────────────────────────────────────────────────────


class TestRedisTickWriterStatus:
    @pytest.mark.asyncio
    async def test_status_after_writes(self):
        w, _ = await _make_writer(ttl=45)
        await w.write("XAUUSD", 1950.0, "yfinance")
        await w.write("EURUSD", 1.0875, "yfinance")
        s = w.status()
        assert s["redis_connected"] is True
        assert s["write_count"] == 2
        assert s["error_count"] == 0
        assert s["tick_key_ttl"] == 45


# ── get_tick_writer singleton ─────────────────────────────────────────────────


class TestGetTickWriterSingleton:
    @pytest.mark.asyncio
    async def test_get_tick_writer_returns_instance(self):
        import data_feed.redis_tick_writer as rtw_module
        rtw_module._writer_instance = None  # reset singleton
        writer = await get_tick_writer()
        assert isinstance(writer, RedisTickWriter)

    @pytest.mark.asyncio
    async def test_get_tick_writer_is_singleton(self):
        import data_feed.redis_tick_writer as rtw_module
        rtw_module._writer_instance = None
        w1 = await get_tick_writer()
        w2 = await get_tick_writer()
        assert w1 is w2
        rtw_module._writer_instance = None  # clean up
