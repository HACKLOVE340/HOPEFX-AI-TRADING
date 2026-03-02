"""
Tests for Real-Time Streaming Service (data/streaming.py)
"""

import pytest
from datetime import datetime, timedelta


class TestTick:
    """Tests for Tick dataclass."""

    def test_tick_creation(self):
        from data.streaming import Tick

        tick = Tick(
            symbol="XAUUSD",
            timestamp=datetime.utcnow(),
            bid=1950.0,
            ask=1950.1,
            last=1950.05,
            volume=100.0,
        )

        assert tick.symbol == "XAUUSD"
        assert tick.bid == 1950.0
        assert tick.ask == 1950.1

    def test_tick_mid(self):
        from data.streaming import Tick

        tick = Tick(
            symbol="XAUUSD",
            timestamp=datetime.utcnow(),
            bid=1950.0,
            ask=1950.1,
            last=1950.05,
        )

        assert tick.mid == pytest.approx(1950.05, rel=1e-5)

    def test_tick_spread(self):
        from data.streaming import Tick

        tick = Tick(
            symbol="XAUUSD",
            timestamp=datetime.utcnow(),
            bid=1950.0,
            ask=1950.1,
            last=1950.05,
        )

        assert tick.spread == pytest.approx(0.1, rel=1e-5)

    def test_tick_to_dict(self):
        from data.streaming import Tick

        tick = Tick(
            symbol="XAUUSD",
            timestamp=datetime.utcnow(),
            bid=1950.0,
            ask=1950.1,
            last=1950.05,
            volume=50.0,
        )

        d = tick.to_dict()
        assert d["symbol"] == "XAUUSD"
        assert "mid" in d
        assert "spread" in d


class TestAggregatedBar:
    """Tests for AggregatedBar dataclass."""

    def test_bar_to_dict(self):
        from data.streaming import AggregatedBar

        bar = AggregatedBar(
            symbol="XAUUSD",
            timeframe="1m",
            timestamp=datetime.utcnow(),
            open=1950.0,
            high=1951.0,
            low=1949.5,
            close=1950.5,
            volume=1000.0,
            tick_count=20,
        )

        d = bar.to_dict()
        assert d["symbol"] == "XAUUSD"
        assert d["timeframe"] == "1m"
        assert d["high"] == 1951.0


class TestTickAggregator:
    """Tests for TickAggregator."""

    def test_initialization(self):
        from data.streaming import TickAggregator

        agg = TickAggregator(timeframe_minutes=1)
        assert agg is not None

    def test_no_bar_on_first_tick(self):
        from data.streaming import Tick, TickAggregator

        agg = TickAggregator(1)
        tick = Tick("XAUUSD", datetime.utcnow(), 1950.0, 1950.1, 1950.05)

        bar = agg.add_tick(tick)
        assert bar is None  # No completed bar yet

    def test_bar_completes_on_period_change(self):
        from data.streaming import Tick, TickAggregator

        agg = TickAggregator(1)

        # Tick in minute 0
        ts0 = datetime(2024, 1, 1, 10, 0, 30)
        agg.add_tick(Tick("XAUUSD", ts0, 1950.0, 1950.1, 1950.0, volume=100.0))

        # Tick in minute 1 - should close minute 0's bar
        ts1 = datetime(2024, 1, 1, 10, 1, 0)
        bar = agg.add_tick(Tick("XAUUSD", ts1, 1951.0, 1951.1, 1951.0, volume=50.0))

        assert bar is not None
        assert bar.symbol == "XAUUSD"
        assert bar.close == 1950.0
        assert bar.volume == 100.0

    def test_ohlc_tracking(self):
        from data.streaming import Tick, TickAggregator

        agg = TickAggregator(1)
        ts_base = datetime(2024, 1, 1, 10, 0, 0)

        prices_vols = [
            (1950.0, 100.0),
            (1952.0, 50.0),
            (1948.0, 75.0),
            (1951.0, 30.0),
        ]
        for price, vol in prices_vols:
            agg.add_tick(Tick("XAUUSD", ts_base, 1950.0, price + 0.1, price, volume=vol))
            ts_base = ts_base.replace(second=ts_base.second + 10)

        # Close the bar with a tick in next minute
        ts_next = datetime(2024, 1, 1, 10, 1, 0)
        bar = agg.add_tick(Tick("XAUUSD", ts_next, 1950.0, 1950.1, 1950.0))

        assert bar is not None
        assert bar.high == 1952.0
        assert bar.low == 1948.0
        assert bar.open == 1950.0

    def test_get_open_bar(self):
        from data.streaming import Tick, TickAggregator

        agg = TickAggregator(1)
        tick = Tick("XAUUSD", datetime.utcnow(), 1950.0, 1950.1, 1950.05)
        agg.add_tick(tick)

        open_bar = agg.get_open_bar("XAUUSD")
        assert open_bar is not None
        assert open_bar["open"] == 1950.05


class TestStreamingService:
    """Tests for StreamingService."""

    def test_initialization(self):
        from data.streaming import StreamingService

        service = StreamingService()
        assert service is not None

    def test_connect_disconnect(self):
        from data.streaming import StreamingService, StreamStatus

        service = StreamingService()
        service.connect()
        assert service.status == StreamStatus.CONNECTED

        service.disconnect()
        assert service.status == StreamStatus.DISCONNECTED

    def test_subscribe_unsubscribe(self):
        from data.streaming import StreamingService

        service = StreamingService()
        events = []

        def handler(event):
            events.append(event)

        service.subscribe("XAUUSD", handler)
        assert "XAUUSD" in service.get_subscriptions()

        service.unsubscribe("XAUUSD", handler)

    def test_publish_tick_dispatches_event(self):
        from data.streaming import StreamingService, Tick

        service = StreamingService()
        events = []
        service.subscribe("XAUUSD", events.append)

        tick = Tick("XAUUSD", datetime.utcnow(), 1950.0, 1950.1, 1950.05, volume=100.0)
        service.publish_tick(tick)

        assert len(events) == 1
        assert events[0].event_type == "tick"

    def test_global_listener_receives_all(self):
        from data.streaming import StreamingService, Tick

        service = StreamingService()
        all_events = []
        service.subscribe("*", all_events.append)

        service.publish_tick(Tick("XAUUSD", datetime.utcnow(), 1950.0, 1950.1, 1950.05))
        service.publish_tick(Tick("EURUSD", datetime.utcnow(), 1.08, 1.0801, 1.0800))

        # At least one tick event per symbol
        tick_events = [e for e in all_events if e.event_type == "tick"]
        assert len(tick_events) == 2

    def test_get_recent_ticks(self):
        from data.streaming import StreamingService, Tick

        service = StreamingService()
        for i in range(20):
            service.publish_tick(
                Tick("XAUUSD", datetime.utcnow(), 1950.0, 1950.1, 1950.0 + i)
            )

        ticks = service.get_recent_ticks("XAUUSD", n=5)
        assert len(ticks) == 5

    def test_get_recent_ticks_empty(self):
        from data.streaming import StreamingService

        service = StreamingService()
        assert service.get_recent_ticks("NONEXISTENT") == []

    def test_get_latest_tick(self):
        from data.streaming import StreamingService, Tick

        service = StreamingService()
        service.publish_tick(Tick("XAUUSD", datetime.utcnow(), 1950.0, 1950.1, 1950.0))
        service.publish_tick(Tick("XAUUSD", datetime.utcnow(), 1951.0, 1951.1, 1951.0))

        latest = service.get_latest_tick("XAUUSD")
        assert latest is not None
        assert latest.last == 1951.0

    def test_get_latest_tick_empty(self):
        from data.streaming import StreamingService

        service = StreamingService()
        assert service.get_latest_tick("NONEXISTENT") is None

    def test_bar_aggregation(self):
        from data.streaming import StreamingService, Tick

        service = StreamingService(config={"default_timeframes": [1]})
        bars_received = []
        service.subscribe("XAUUSD", lambda e: bars_received.append(e) if e.event_type == "bar" else None)

        # Minute 0
        ts0 = datetime(2024, 1, 1, 10, 0, 30)
        service.publish_tick(Tick("XAUUSD", ts0, 1950.0, 1950.1, 1950.05, volume=100.0))

        # Minute 1 - should trigger bar close
        ts1 = datetime(2024, 1, 1, 10, 1, 0)
        service.publish_tick(Tick("XAUUSD", ts1, 1951.0, 1951.1, 1951.05, volume=50.0))

        assert len(bars_received) == 1
        bar_data = bars_received[0].data
        assert bar_data["volume"] == 100.0

    def test_get_bars(self):
        from data.streaming import StreamingService, Tick

        service = StreamingService(config={"default_timeframes": [1]})

        # Minute 0
        ts0 = datetime(2024, 1, 1, 10, 0, 30)
        service.publish_tick(Tick("XAUUSD", ts0, 1950.0, 1950.1, 1950.05, volume=100.0))

        # Minute 1
        ts1 = datetime(2024, 1, 1, 10, 1, 0)
        service.publish_tick(Tick("XAUUSD", ts1, 1951.0, 1951.1, 1951.05, volume=50.0))

        bars = service.get_bars("XAUUSD", timeframe="1m")
        assert len(bars) == 1

    def test_clear_symbol(self):
        from data.streaming import StreamingService, Tick

        service = StreamingService()
        service.publish_tick(Tick("XAUUSD", datetime.utcnow(), 1950.0, 1950.1, 1950.05))
        service.clear_symbol("XAUUSD")

        assert service.get_recent_ticks("XAUUSD") == []

    def test_clear_all(self):
        from data.streaming import StreamingService, Tick

        service = StreamingService()
        service.publish_tick(Tick("XAUUSD", datetime.utcnow(), 1950.0, 1950.1, 1950.05))
        service.publish_tick(Tick("EURUSD", datetime.utcnow(), 1.08, 1.0801, 1.08))
        service.clear_all()

        assert service.get_recent_ticks("XAUUSD") == []
        assert service.get_recent_ticks("EURUSD") == []

    def test_get_stats(self):
        from data.streaming import StreamingService

        service = StreamingService()
        stats = service.get_stats()

        assert "status" in stats
        assert "subscribed_symbols" in stats
        assert "available_timeframes" in stats

    def test_reconnect_with_backoff_success(self):
        from data.streaming import StreamingService

        service = StreamingService(config={"reconnect_base_delay": 0})
        call_count = [0]

        def mock_connect():
            call_count[0] += 1
            return call_count[0] >= 2  # Succeed on second attempt

        result = service.reconnect_with_backoff(mock_connect, max_attempts=3)
        assert result is True

    def test_reconnect_with_backoff_failure(self):
        from data.streaming import StreamingService, StreamStatus

        service = StreamingService(config={"reconnect_base_delay": 0})

        result = service.reconnect_with_backoff(lambda: False, max_attempts=2)
        assert result is False
        assert service.status == StreamStatus.ERROR

    def test_global_instance(self):
        from data.streaming import get_streaming_service

        s1 = get_streaming_service()
        s2 = get_streaming_service()
        assert s1 is s2
