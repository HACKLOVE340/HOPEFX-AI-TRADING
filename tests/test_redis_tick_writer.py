# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
tests/test_redis_tick_writer.py
================================
Regression tests for data_feed/redis_tick_writer.py backpressure fixes.

Covers:
  - write() is non-blocking (returns immediately, does not await Redis)
  - Queue is bounded: write() never grows the queue beyond maxsize
  - When queue is full, oldest tick is evicted (not newest)
  - drop_count increments on eviction
  - Background worker drains the queue and calls _flush_one
  - stop() drains the queue before cancelling the worker
  - get_tick_writer() singleton is safe under concurrent calls
  - status() reports correct queue_depth and drop_count
  - write() returns False when Redis is not connected
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from data_feed.redis_tick_writer import RedisTickWriter, build_tick_payload


def _make_writer(maxsize: int = 10) -> RedisTickWriter:
    """Return a RedisTickWriter with a fake Redis client and small queue."""
    writer = RedisTickWriter(write_queue_maxsize=maxsize)
    # Inject a fake Redis client so write() doesn't return False
    mock_redis = MagicMock()
    mock_redis.pipeline.return_value.__aenter__ = AsyncMock(return_value=MagicMock())
    mock_redis.pipeline.return_value.__aexit__ = AsyncMock(return_value=False)
    pipe = MagicMock()
    pipe.setex = MagicMock()
    pipe.publish = MagicMock()
    pipe.rpush = MagicMock()
    pipe.ltrim = MagicMock()
    pipe.execute = AsyncMock(return_value=[True] * 7)
    mock_redis.pipeline.return_value = pipe
    writer._redis = mock_redis
    return writer


# ── write() is non-blocking ───────────────────────────────────────────────────

class TestWriteNonBlocking:
    @pytest.mark.asyncio
    async def test_write_returns_immediately_without_awaiting_redis(self):
        """write() must enqueue and return True without calling Redis directly."""
        writer = _make_writer()
        flush_calls = [0]

        async def _spy_flush(self_inner, payload):
            flush_calls[0] += 1

        with patch.object(RedisTickWriter, "_flush_one", _spy_flush):
            result = await writer.write("XAUUSD", 2000.0, "test")

        assert result is True
        assert flush_calls[0] == 0, (
            "write() must not call _flush_one directly — only the background worker should"
        )

    @pytest.mark.asyncio
    async def test_write_returns_false_when_no_redis(self):
        """write() must return False immediately when Redis is not connected."""
        writer = RedisTickWriter(write_queue_maxsize=10)
        writer._redis = None  # not connected

        result = await writer.write("XAUUSD", 2000.0, "test")
        assert result is False
        assert writer._write_queue.qsize() == 0


# ── Bounded queue ─────────────────────────────────────────────────────────────

class TestBoundedQueue:
    @pytest.mark.asyncio
    async def test_queue_never_exceeds_maxsize(self):
        """Queue depth must never exceed maxsize regardless of write volume."""
        maxsize = 5
        writer = _make_writer(maxsize=maxsize)

        # Write 3x the queue capacity
        for i in range(maxsize * 3):
            await writer.write("XAUUSD", float(2000 + i), "test")

        assert writer._write_queue.qsize() <= maxsize, (
            f"Queue depth {writer._write_queue.qsize()} exceeds maxsize {maxsize}"
        )

    @pytest.mark.asyncio
    async def test_drop_count_increments_on_eviction(self):
        """drop_count must increment each time an old tick is evicted."""
        maxsize = 3
        writer = _make_writer(maxsize=maxsize)

        # Fill the queue exactly
        for i in range(maxsize):
            await writer.write("XAUUSD", float(2000 + i), "test")

        assert writer._drop_count == 0, "No drops yet — queue not full"

        # One more write should evict one old tick
        await writer.write("XAUUSD", 2099.0, "test")
        assert writer._drop_count == 1, f"Expected 1 drop, got {writer._drop_count}"

        # Two more writes
        await writer.write("XAUUSD", 2100.0, "test")
        await writer.write("XAUUSD", 2101.0, "test")
        assert writer._drop_count == 3

    @pytest.mark.asyncio
    async def test_newest_tick_is_kept_not_oldest(self):
        """When the queue is full, the OLDEST tick must be evicted, not the newest."""
        maxsize = 2
        writer = _make_writer(maxsize=maxsize)

        # Fill queue with prices 1000, 2000
        await writer.write("XAUUSD", 1000.0, "test")
        await writer.write("XAUUSD", 2000.0, "test")

        # Write a new tick — should evict 1000.0 (oldest)
        await writer.write("XAUUSD", 3000.0, "test")

        # Drain the queue and check prices
        prices = []
        while not writer._write_queue.empty():
            item = writer._write_queue.get_nowait()
            writer._write_queue.task_done()
            prices.append(item["price"])

        assert 1000.0 not in prices, f"Oldest tick (1000.0) should have been evicted. Got: {prices}"
        assert 3000.0 in prices, f"Newest tick (3000.0) must be present. Got: {prices}"


# ── Background worker ─────────────────────────────────────────────────────────

class TestBackgroundWorker:
    @pytest.mark.asyncio
    async def test_worker_drains_queue_and_calls_flush(self):
        """Background worker must call _flush_one for each enqueued tick."""
        writer = _make_writer(maxsize=100)
        flushed: list[dict] = []

        async def _mock_flush(self_inner, payload):
            flushed.append(payload)

        writer._stopping = False
        with patch.object(RedisTickWriter, "_flush_one", _mock_flush):
            task = asyncio.create_task(writer._write_worker())

            for i in range(5):
                await writer.write("XAUUSD", float(2000 + i), "test")

            await asyncio.wait_for(writer._write_queue.join(), timeout=2.0)

            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

        assert len(flushed) == 5, f"Expected 5 flushes, got {len(flushed)}"

    @pytest.mark.asyncio
    async def test_worker_continues_after_flush_error(self):
        """A Redis error in _flush_one must not stop the worker."""
        writer = _make_writer(maxsize=100)
        flushed: list[dict] = []
        call_count = [0]

        async def _flaky_flush(self_inner, payload):
            call_count[0] += 1
            if call_count[0] == 1:
                raise ConnectionError("Redis down")
            flushed.append(payload)

        writer._stopping = False
        with patch.object(RedisTickWriter, "_flush_one", _flaky_flush):
            task = asyncio.create_task(writer._write_worker())

            for i in range(3):
                await writer.write("XAUUSD", float(2000 + i), "test")

            await asyncio.sleep(0.5)

            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

        assert len(flushed) >= 1, f"Worker must continue after error. flushed={flushed}"


# ── stop() drains queue ───────────────────────────────────────────────────────

class TestStop:
    @pytest.mark.asyncio
    async def test_stop_drains_queue(self):
        """stop() must wait for the queue to drain before cancelling the worker."""
        writer = _make_writer(maxsize=100)
        flushed: list[dict] = []

        async def _mock_flush(self_inner, payload):
            await asyncio.sleep(0.005)  # simulate slow Redis
            flushed.append(payload)

        writer._stopping = False
        with patch.object(RedisTickWriter, "_flush_one", _mock_flush):
            writer._worker_task = asyncio.create_task(writer._write_worker())

            for i in range(10):
                await writer.write("XAUUSD", float(2000 + i), "test")

            # stop() must be inside the patch context so the worker can still flush
            await writer.stop()

            assert len(flushed) == 10, (
                f"stop() must drain all 10 ticks before returning. flushed={len(flushed)}"
            )


# ── status() ─────────────────────────────────────────────────────────────────

class TestStatus:
    @pytest.mark.asyncio
    async def test_status_reports_queue_depth(self):
        writer = _make_writer(maxsize=10)
        await writer.write("XAUUSD", 2000.0, "test")
        await writer.write("XAUUSD", 2001.0, "test")

        s = writer.status()
        assert s["queue_depth"] == 2
        assert s["queue_maxsize"] == 10
        assert s["redis_connected"] is True
        assert s["drop_count"] == 0

    @pytest.mark.asyncio
    async def test_status_reports_drop_count(self):
        maxsize = 2
        writer = _make_writer(maxsize=maxsize)
        for i in range(5):
            await writer.write("XAUUSD", float(2000 + i), "test")

        s = writer.status()
        assert s["drop_count"] == 3  # 5 writes - 2 capacity = 3 drops


# ── get_tick_writer() singleton safety ───────────────────────────────────────

class TestSingletonSafety:
    @pytest.mark.asyncio
    async def test_concurrent_calls_return_same_instance(self):
        """Concurrent get_tick_writer() calls must return the same instance."""
        import data_feed.redis_tick_writer as mod

        # Reset singleton state
        mod._writer_instance = None
        mod._writer_lock = None

        mock_writer = RedisTickWriter(write_queue_maxsize=10)
        mock_writer._redis = MagicMock()

        async def _mock_start(self_inner):
            self_inner._redis = MagicMock()
            return True

        with patch.object(RedisTickWriter, "start", _mock_start):
            results = await asyncio.gather(
                mod.get_tick_writer(),
                mod.get_tick_writer(),
                mod.get_tick_writer(),
            )

        # All three must be the same object
        assert results[0] is results[1] is results[2], (
            "get_tick_writer() must return the same singleton instance"
        )

        # Cleanup
        mod._writer_instance = None
        mod._writer_lock = None


# ── build_tick_payload ────────────────────────────────────────────────────────

class TestBuildTickPayload:
    def test_required_fields_present(self):
        p = build_tick_payload("XAUUSD", 2000.0, "test")
        assert p["symbol"] == "XAUUSD"
        assert p["price"] == 2000.0
        assert p["source"] == "test"
        assert "ts" in p
        assert "timestamp" in p

    def test_bid_ask_optional(self):
        p = build_tick_payload("XAUUSD", 2000.0, "test", bid=1999.5, ask=2000.5)
        assert p["bid"] == 1999.5
        assert p["ask"] == 2000.5

    def test_no_bid_ask_when_not_provided(self):
        p = build_tick_payload("XAUUSD", 2000.0, "test")
        assert "bid" not in p
        assert "ask" not in p
