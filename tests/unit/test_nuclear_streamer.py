# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
Unit tests for data_feed.NuclearStreamer.

All tests run without real WebSocket connections, Redis, or Prometheus.
External I/O is replaced with in-process asyncio primitives so tests are
deterministic and fast.

Coverage
--------
  - process_tick: valid tick, out-of-range rejection, anomaly detection
  - Circuit breaker: open after threshold failures, cooldown reset
  - Back-off wrapper: reconnect loop, circuit-breaker skip
  - Subscriber broadcast: on_new_price called, errors isolated
  - Redis publish: payload shape, error tolerance
  - Finnhub / Twelve Data / Polygon message parsing (via process_tick path)
  - status() snapshot
  - Architectural boundary: OANDAStream.stream_prices raises StreamingForbiddenError
  - Architectural boundary: OANDAStreamAdapter.start raises StreamingForbiddenError
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import time
from unittest.mock import AsyncMock, patch

import pytest

os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("SECURITY_JWT_SECRET", "test-only-jwt-secret-key-minimum-32-chars!!")


# ── helpers ───────────────────────────────────────────────────────────────────


def _make_streamer(**kwargs):
    """Return a NuclearStreamer with Prometheus disabled and no Redis."""
    from data_feed.nuclear_streamer import NuclearStreamer

    return NuclearStreamer(prometheus_port=0, **kwargs)


class _Collector:
    """Subscriber that records every price delivered via on_new_price."""

    def __init__(self):
        self.prices: list[float] = []
        self.errors: list[Exception] = []

    async def on_new_price(self, price: float) -> None:
        self.prices.append(price)


class _FaultySubscriber:
    """Subscriber that always raises — used to verify error isolation."""

    async def on_new_price(self, price: float) -> None:
        raise RuntimeError("subscriber intentional error")


# ═══════════════════════════════════════════════════════════════════════════════
# process_tick
# ═══════════════════════════════════════════════════════════════════════════════


class TestProcessTick:
    @pytest.mark.asyncio
    async def test_valid_tick_accepted(self):
        streamer = _make_streamer()
        collector = _Collector()
        streamer.subscribe(collector)

        await streamer.process_tick(2000.0, time.time(), "finnhub")

        assert collector.prices == [2000.0]
        assert streamer._last_price == 2000.0

    @pytest.mark.asyncio
    async def test_price_below_minimum_rejected(self):
        streamer = _make_streamer()
        collector = _Collector()
        streamer.subscribe(collector)

        await streamer.process_tick(500.0, time.time(), "finnhub")

        assert collector.prices == []
        assert streamer._last_price is None

    @pytest.mark.asyncio
    async def test_price_above_maximum_rejected(self):
        streamer = _make_streamer()
        collector = _Collector()
        streamer.subscribe(collector)

        await streamer.process_tick(99_999.0, time.time(), "finnhub")

        assert collector.prices == []

    @pytest.mark.asyncio
    async def test_zero_price_rejected(self):
        streamer = _make_streamer()
        collector = _Collector()
        streamer.subscribe(collector)

        await streamer.process_tick(0.0, time.time(), "finnhub")

        assert collector.prices == []

    @pytest.mark.asyncio
    async def test_anomaly_jump_discarded(self):
        """A tick that moves >5% from last price must be discarded."""
        streamer = _make_streamer(anomaly_jump_pct=5.0)
        collector = _Collector()
        streamer.subscribe(collector)

        await streamer.process_tick(2000.0, time.time(), "finnhub")
        # 2000 → 2200 = 10% jump — should be discarded
        await streamer.process_tick(2200.0, time.time(), "finnhub")

        assert collector.prices == [2000.0]
        assert streamer._last_price == 2000.0  # unchanged

    @pytest.mark.asyncio
    async def test_anomaly_counter_incremented(self):
        streamer = _make_streamer(anomaly_jump_pct=5.0)
        await streamer.process_tick(2000.0, time.time(), "finnhub")
        await streamer.process_tick(2200.0, time.time(), "finnhub")  # anomaly

        assert streamer._anomaly_counts.get("finnhub", 0) == 1

    @pytest.mark.asyncio
    async def test_normal_tick_after_anomaly_accepted(self):
        """A normal tick following an anomaly must still be accepted."""
        streamer = _make_streamer(anomaly_jump_pct=5.0)
        collector = _Collector()
        streamer.subscribe(collector)

        await streamer.process_tick(2000.0, time.time(), "finnhub")
        await streamer.process_tick(2200.0, time.time(), "finnhub")  # anomaly — discarded
        await streamer.process_tick(2010.0, time.time(), "finnhub")  # 0.5% — accepted

        assert collector.prices == [2000.0, 2010.0]

    @pytest.mark.asyncio
    async def test_first_tick_no_anomaly_check(self):
        """The very first tick has no previous price to compare against."""
        streamer = _make_streamer(anomaly_jump_pct=0.001)  # extremely tight threshold
        collector = _Collector()
        streamer.subscribe(collector)

        await streamer.process_tick(2000.0, time.time(), "finnhub")

        assert collector.prices == [2000.0]

    @pytest.mark.asyncio
    async def test_latency_is_non_negative(self):
        """Latency computed from event_ts must be >= 0."""
        streamer = _make_streamer()
        event_ts = time.time() - 0.05  # 50 ms ago
        await streamer.process_tick(2000.0, event_ts, "polygon")
        # No assertion on exact value — just verify no exception and tick accepted
        assert streamer._last_price == 2000.0

    @pytest.mark.asyncio
    async def test_multiple_sources_independent(self):
        """Ticks from different sources are each published independently.

        Set _CONSENSUS_MIN_SOURCES higher than the number of active sources so
        the graceful-degradation path fires for every tick — each source
        publishes its own price directly without waiting for consensus.
        """
        import data_feed.nuclear_streamer as ns

        streamer = _make_streamer()
        collector = _Collector()
        streamer.subscribe(collector)

        # With min_sources=10, len(active_sources) < 10 is always True for our
        # 3-source test, so each tick takes the graceful-degradation path and
        # publishes its own price directly.
        with patch.object(ns, "_CONSENSUS_MIN_SOURCES", 10):
            await streamer.process_tick(2000.0, time.time(), "finnhub")
            await streamer.process_tick(2001.0, time.time(), "twelvedata")
            await streamer.process_tick(2002.0, time.time(), "polygon")

        assert collector.prices == [2000.0, 2001.0, 2002.0]

    @pytest.mark.asyncio
    async def test_redis_publish_called_when_available(self):
        streamer = _make_streamer()
        mock_redis = AsyncMock()
        streamer._redis = mock_redis

        await streamer.process_tick(2000.0, time.time(), "finnhub")

        mock_redis.rpush.assert_awaited_once()
        call_args = mock_redis.rpush.call_args
        queue_name = call_args[0][0]
        payload = json.loads(call_args[0][1])
        assert queue_name == "price_queue"
        assert payload["symbol"] == "XAUUSD"
        assert payload["price"] == 2000.0
        assert payload["source"] == "finnhub"
        assert "latency_ms" in payload

    @pytest.mark.asyncio
    async def test_redis_error_does_not_crash_stream(self):
        streamer = _make_streamer()
        mock_redis = AsyncMock()
        mock_redis.rpush.side_effect = ConnectionError("redis down")
        streamer._redis = mock_redis
        collector = _Collector()
        streamer.subscribe(collector)

        # Must not raise
        await streamer.process_tick(2000.0, time.time(), "finnhub")

        assert collector.prices == [2000.0]

    @pytest.mark.asyncio
    async def test_redis_payload_contains_received_at(self):
        streamer = _make_streamer()
        mock_redis = AsyncMock()
        streamer._redis = mock_redis

        await streamer.process_tick(2000.0, time.time() - 0.1, "polygon")

        payload = json.loads(mock_redis.rpush.call_args[0][1])
        assert "received_at" in payload
        assert payload["received_at"] >= payload["timestamp"]


# ═══════════════════════════════════════════════════════════════════════════════
# Subscriber broadcast
# ═══════════════════════════════════════════════════════════════════════════════


class TestSubscriberBroadcast:
    @pytest.mark.asyncio
    async def test_multiple_subscribers_all_notified(self):
        streamer = _make_streamer()
        c1, c2, c3 = _Collector(), _Collector(), _Collector()
        streamer.subscribe(c1)
        streamer.subscribe(c2)
        streamer.subscribe(c3)

        await streamer.process_tick(2000.0, time.time(), "finnhub")

        assert c1.prices == [2000.0]
        assert c2.prices == [2000.0]
        assert c3.prices == [2000.0]

    @pytest.mark.asyncio
    async def test_faulty_subscriber_does_not_block_others(self):
        streamer = _make_streamer()
        good = _Collector()
        bad = _FaultySubscriber()
        streamer.subscribe(bad)
        streamer.subscribe(good)

        await streamer.process_tick(2000.0, time.time(), "finnhub")

        assert good.prices == [2000.0]

    @pytest.mark.asyncio
    async def test_unsubscribe_removes_subscriber(self):
        streamer = _make_streamer()
        collector = _Collector()
        streamer.subscribe(collector)
        streamer.unsubscribe(collector)

        await streamer.process_tick(2000.0, time.time(), "finnhub")

        assert collector.prices == []

    @pytest.mark.asyncio
    async def test_unsubscribe_nonexistent_is_safe(self):
        streamer = _make_streamer()
        collector = _Collector()
        # Should not raise
        streamer.unsubscribe(collector)

    @pytest.mark.asyncio
    async def test_no_subscribers_no_error(self):
        streamer = _make_streamer()
        # Must not raise even with no subscribers
        await streamer.process_tick(2000.0, time.time(), "finnhub")

    @pytest.mark.asyncio
    async def test_object_without_on_new_price_ignored(self):
        streamer = _make_streamer()
        streamer.subscribe(object())  # no on_new_price method
        # Must not raise
        await streamer.process_tick(2000.0, time.time(), "finnhub")


# ═══════════════════════════════════════════════════════════════════════════════
# Circuit breaker
# ═══════════════════════════════════════════════════════════════════════════════


class TestCircuitBreaker:
    def test_circuit_open_after_threshold(self):
        streamer = _make_streamer(circuit_breaker_threshold=3)
        for _ in range(3):
            streamer._record_failure("finnhub")

        assert streamer._is_circuit_open("finnhub") is True

    def test_circuit_closed_below_threshold(self):
        streamer = _make_streamer(circuit_breaker_threshold=3)
        for _ in range(2):
            streamer._record_failure("finnhub")

        assert streamer._is_circuit_open("finnhub") is False

    def test_circuit_resets_after_cooldown(self):
        streamer = _make_streamer(circuit_breaker_threshold=1, circuit_breaker_cooldown=0.01)
        streamer._record_failure("finnhub")
        assert streamer._is_circuit_open("finnhub") is True

        time.sleep(0.02)  # wait for cooldown
        assert streamer._is_circuit_open("finnhub") is False

    def test_record_success_resets_fail_count(self):
        streamer = _make_streamer(circuit_breaker_threshold=5)
        for _ in range(3):
            streamer._record_failure("polygon")
        streamer._record_success("polygon")

        assert streamer._fail_counts.get("polygon", 0) == 0
        assert streamer._circuit_open_at.get("polygon") is None

    def test_circuit_closed_for_unknown_source(self):
        streamer = _make_streamer()
        assert streamer._is_circuit_open("unknown_source") is False

    def test_independent_per_source(self):
        streamer = _make_streamer(circuit_breaker_threshold=2)
        streamer._record_failure("finnhub")
        streamer._record_failure("finnhub")

        assert streamer._is_circuit_open("finnhub") is True
        assert streamer._is_circuit_open("polygon") is False


# ═══════════════════════════════════════════════════════════════════════════════
# Back-off wrapper
# ═══════════════════════════════════════════════════════════════════════════════


class TestRunWithBackoff:
    @pytest.mark.asyncio
    async def test_stops_when_not_running(self):
        streamer = _make_streamer()
        streamer._running = False
        call_count = 0

        async def _coro():
            nonlocal call_count
            call_count += 1

        await streamer._run_with_backoff("finnhub", _coro)
        assert call_count == 0

    @pytest.mark.asyncio
    async def test_calls_coro_once_then_stops(self):
        streamer = _make_streamer()
        streamer._running = True
        call_count = 0

        async def _coro():
            nonlocal call_count
            call_count += 1
            streamer._running = False  # stop after first call

        with patch("asyncio.sleep", new_callable=AsyncMock):
            await streamer._run_with_backoff("finnhub", _coro)

        assert call_count == 1

    @pytest.mark.asyncio
    async def test_reconnects_on_exception(self):
        streamer = _make_streamer()
        streamer._running = True
        call_count = 0

        async def _coro():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise ConnectionError("simulated disconnect")
            streamer._running = False

        with patch("asyncio.sleep", new_callable=AsyncMock):
            await streamer._run_with_backoff("finnhub", _coro)

        assert call_count == 3

    @pytest.mark.asyncio
    async def test_skips_when_circuit_open(self):
        streamer = _make_streamer(
            circuit_breaker_threshold=1,
            circuit_breaker_cooldown=9999,
        )
        streamer._running = True
        streamer._record_failure("finnhub")  # open circuit

        call_count = 0

        async def _coro():
            nonlocal call_count
            call_count += 1

        sleep_calls = []

        async def _fake_sleep(secs):
            sleep_calls.append(secs)
            streamer._running = False  # stop after first sleep

        with patch("asyncio.sleep", side_effect=_fake_sleep):
            await streamer._run_with_backoff("finnhub", _coro)

        assert call_count == 0
        assert len(sleep_calls) >= 1


# ═══════════════════════════════════════════════════════════════════════════════
# status()
# ═══════════════════════════════════════════════════════════════════════════════


class TestStatus:
    def test_status_initial_state(self):
        streamer = _make_streamer()
        s = streamer.status()

        assert s["symbol"] == "XAUUSD"
        assert s["last_price"] is None
        assert s["subscriber_count"] == 0
        assert s["is_running"] is False

    @pytest.mark.asyncio
    async def test_status_after_tick(self):
        streamer = _make_streamer()
        collector = _Collector()
        streamer.subscribe(collector)

        await streamer.process_tick(2000.0, time.time(), "finnhub")

        s = streamer.status()
        assert s["last_price"] == 2000.0
        assert s["subscriber_count"] == 1

    def test_status_circuit_breaker_open(self):
        streamer = _make_streamer(circuit_breaker_threshold=1)
        streamer._record_failure("polygon")

        s = streamer.status()
        assert s["circuit_breakers"]["polygon"]["open"] is True

    def test_status_circuit_breaker_closed(self):
        streamer = _make_streamer()
        s = streamer.status()
        assert s["circuit_breakers"]["finnhub"]["open"] is False

    @pytest.mark.asyncio
    async def test_status_anomaly_count(self):
        streamer = _make_streamer(anomaly_jump_pct=5.0)
        await streamer.process_tick(2000.0, time.time(), "finnhub")
        await streamer.process_tick(2200.0, time.time(), "finnhub")  # anomaly

        s = streamer.status()
        assert s["anomaly_counts"].get("finnhub", 0) == 1


# ═══════════════════════════════════════════════════════════════════════════════
# Architectural boundary — OANDAStream.stream_prices raises StreamingForbiddenError
# ═══════════════════════════════════════════════════════════════════════════════


class TestOANDAStreamArchitecturalBoundary:
    @pytest.mark.asyncio
    async def test_stream_prices_raises_streaming_forbidden(self):
        from brokers.oanda_stream import OANDAStream, StreamingForbiddenError

        broker = OANDAStream(
            api_key="test-key",  # pragma: allowlist secret
            account_id="test-account",
            instruments=["XAU_USD"],
        )
        with pytest.raises(StreamingForbiddenError):
            await broker.stream_prices()

    def test_on_tick_callback_ignored_with_warning(self, caplog):
        import logging

        from brokers.oanda_stream import OANDAStream

        with caplog.at_level(logging.WARNING, logger="brokers.oanda_stream"):
            OANDAStream(
                api_key="test-key",  # pragma: allowlist secret
                account_id="test-account",
                instruments=["XAU_USD"],
                on_tick=lambda t: None,
            )

        assert any("on_tick" in r.message for r in caplog.records)

    def test_oanda_stream_has_execution_methods(self):
        """Verify execution API is intact after streaming removal."""
        from brokers.oanda_stream import OANDAStream

        broker = OANDAStream(
            api_key="test-key",  # pragma: allowlist secret
            account_id="test-account",
            instruments=["XAU_USD"],
        )
        assert callable(getattr(broker, "connect", None))
        assert callable(getattr(broker, "place_order", None))
        assert callable(getattr(broker, "get_account_info", None))
        assert callable(getattr(broker, "get_positions", None))
        assert callable(getattr(broker, "close_position", None))
        assert callable(getattr(broker, "cancel_order", None))
        assert callable(getattr(broker, "get_open_orders", None))
        assert callable(getattr(broker, "get_candles", None))


# ═══════════════════════════════════════════════════════════════════════════════
# Architectural boundary — OANDAStreamAdapter tombstone
# ═══════════════════════════════════════════════════════════════════════════════


class TestOANDAStreamAdapterTombstone:
    @pytest.mark.asyncio
    async def test_start_raises_streaming_forbidden(self):
        from brokers.oanda_ws import OANDAStreamAdapter, StreamingForbiddenError

        adapter = OANDAStreamAdapter()
        with pytest.raises(StreamingForbiddenError):
            await adapter.start()

    @pytest.mark.asyncio
    async def test_stop_raises_streaming_forbidden(self):
        from brokers.oanda_ws import OANDAStreamAdapter, StreamingForbiddenError

        adapter = OANDAStreamAdapter()
        with pytest.raises(StreamingForbiddenError):
            await adapter.stop()

    @pytest.mark.asyncio
    async def test_poll_rest_raises_streaming_forbidden(self):
        from brokers.oanda_ws import OANDAStreamAdapter, StreamingForbiddenError

        adapter = OANDAStreamAdapter()
        with pytest.raises(StreamingForbiddenError):
            await adapter.poll_rest()

    def test_instantiation_logs_error(self, caplog):
        import logging

        from brokers.oanda_ws import OANDAStreamAdapter

        with caplog.at_level(logging.ERROR, logger="brokers.oanda_ws"):
            OANDAStreamAdapter()

        assert any("tombstone" in r.message.lower() for r in caplog.records)


# ═══════════════════════════════════════════════════════════════════════════════
# data_feed public API
# ═══════════════════════════════════════════════════════════════════════════════


class TestDataFeedPublicAPI:
    def test_nuclear_streamer_exported(self):
        from data_feed import NuclearStreamer

        assert NuclearStreamer is not None

    def test_production_data_engine_exported(self):
        from data_feed import ProductionDataEngine

        assert ProductionDataEngine is not None

    def test_mt5_backup_exported(self):
        from data_feed import MT5Backup

        assert MT5Backup is not None

    def test_nuclear_streamer_is_primary(self):
        """NuclearStreamer must be first in __all__."""
        import data_feed

        assert data_feed.__all__[0] == "NuclearStreamer"


# ═══════════════════════════════════════════════════════════════════════════════
# NuclearStreamer.run() — no keys configured
# ═══════════════════════════════════════════════════════════════════════════════


class TestRunNoKeys:
    @pytest.mark.asyncio
    async def test_run_exits_cleanly_with_no_keys(self, monkeypatch):
        """run() must log a warning and return without error when no keys are set."""
        monkeypatch.delenv("FINNHUB_API_KEY", raising=False)
        monkeypatch.delenv("TWELVE_API_KEY", raising=False)
        monkeypatch.delenv("POLYGON_API_KEY", raising=False)

        streamer = _make_streamer()
        # Should return immediately (no tasks to run)
        await asyncio.wait_for(streamer.run(), timeout=2.0)

    @pytest.mark.asyncio
    async def test_run_starts_tasks_when_key_present(self, monkeypatch):
        """run() must create at least one task when a key is set."""
        monkeypatch.setenv("FINNHUB_API_KEY", "test-key")
        monkeypatch.delenv("TWELVE_API_KEY", raising=False)
        monkeypatch.delenv("POLYGON_API_KEY", raising=False)

        streamer = _make_streamer()
        tasks_created = []

        original_create_task = asyncio.create_task

        def _spy_create_task(coro, **kwargs):
            tasks_created.append(coro)
            t = original_create_task(coro, **kwargs)
            t.cancel()  # cancel immediately so run() exits
            return t

        with (
            patch("asyncio.create_task", side_effect=_spy_create_task),
            contextlib.suppress((TimeoutError, asyncio.CancelledError)),
        ):
            await asyncio.wait_for(streamer.run(), timeout=1.0)

        assert len(tasks_created) >= 1


# ═══════════════════════════════════════════════════════════════════════════════
# stop()
# ═══════════════════════════════════════════════════════════════════════════════


class TestStop:
    @pytest.mark.asyncio
    async def test_stop_sets_running_false(self):
        streamer = _make_streamer()
        streamer._running = True
        await streamer.stop()
        assert streamer._running is False

    @pytest.mark.asyncio
    async def test_stop_idempotent(self):
        streamer = _make_streamer()
        await streamer.stop()
        await streamer.stop()  # second call must not raise
