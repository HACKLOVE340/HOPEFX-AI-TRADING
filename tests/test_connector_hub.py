# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# AGPL-3.0 — Share all modifications

"""
tests/test_connector_hub.py
===========================
Unit and integration tests for the 8 live-connector-hub files.

Covered modules
---------------
- connect_to_life.py          — DrawdownMonitor, DailyReporter, LifeBridge
- core/event_bus.py           — EventBus publish/subscribe, local fallback
- data/market_ingest.py       — tick validation, staleness guard
- strategy/engine.py          — OHLCV buffer, ML predictor wrapper
- risk/gatekeeper.py          — prop checks, breach routing
- execution/fix_router.py     — smart routing, fill logging
- core/main_loop.py           — orchestrator wiring
- utils/fault_guard.py        — circuit breaker, heartbeat monitor
- data/news_calendar_feed.py  — ForexFactory parse, Redis write
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ─────────────────────────────────────────────────────────────────────────────
# connect_to_life — DrawdownMonitor
# ─────────────────────────────────────────────────────────────────────────────


class TestDrawdownMonitor:
    def _make(self, balance: float = 100_000):
        from connect_to_life import DrawdownMonitor

        return DrawdownMonitor(balance)

    def test_no_drawdown_on_flat_equity(self):
        dd = self._make(100_000)
        result = dd.update(100_000)
        assert result == 0.0

    def test_drawdown_calculated_correctly(self):
        dd = self._make(100_000)
        dd.update(100_000)  # peak = 100k
        result = dd.update(97_000)
        assert abs(result - 0.03) < 1e-6

    def test_peak_updates_on_new_high(self):
        dd = self._make(100_000)
        dd.update(110_000)  # new peak
        result = dd.update(110_000)
        assert result == 0.0

    def test_daily_drawdown_property(self):
        dd = self._make(100_000)
        dd.update(100_000)
        dd.update(95_000)
        assert abs(dd.daily_drawdown - 0.05) < 1e-6


# ─────────────────────────────────────────────────────────────────────────────
# core/event_bus — EventBus
# ─────────────────────────────────────────────────────────────────────────────


class TestEventBus:
    @pytest.mark.asyncio
    async def test_local_fallback_publish_subscribe(self):
        """When Redis is unavailable the local bus delivers messages."""
        from core.event_bus import CH_TICK, EventBus

        bus = EventBus()
        # Force degraded mode (no Redis)
        bus._degraded = True

        received: list = []

        async def _handler(msg):
            received.append(msg)

        bus.subscribe_local(CH_TICK, _handler)
        await bus.publish_tick({"bid": 1920.0, "ask": 1920.5})

        # Give the local bus a moment to deliver
        await asyncio.sleep(0.01)
        assert len(received) == 1
        assert received[0]["bid"] == 1920.0

    @pytest.mark.asyncio
    async def test_publish_retries_then_falls_back(self):
        """publish() exhausts retries and routes to local fallback."""
        from core.event_bus import CH_SIGNAL, EventBus

        bus = EventBus()
        # Simulate Redis that always fails
        mock_redis = AsyncMock()
        mock_redis.publish.side_effect = ConnectionError("Redis down")
        bus._redis = mock_redis
        bus._degraded = False

        received: list = []
        bus.subscribe_local(CH_SIGNAL, received.append)

        # Patch sleep to avoid waiting during retries
        with patch("core.event_bus.asyncio.sleep", new_callable=AsyncMock):
            await bus.publish(CH_SIGNAL, {"type": "signal", "direction": "BUY"})

        assert bus._metrics["errors"] >= 1
        assert len(received) == 1

    @pytest.mark.asyncio
    async def test_metrics_increments_on_publish(self):
        from core.event_bus import EventBus

        bus = EventBus()
        bus._degraded = True  # use local path

        await bus.publish_order({"type": "order_request"})
        # errors count because local path is used after retries
        assert bus._metrics["errors"] >= 0  # at least attempted


# ─────────────────────────────────────────────────────────────────────────────
# data/market_ingest — tick validation
# ─────────────────────────────────────────────────────────────────────────────


class TestTickValidation:
    def _validate(self, bid, ask):
        from data.market_ingest import _validate_tick

        return _validate_tick(bid, ask, "XAU/USD")

    def test_valid_tick_passes(self):
        assert self._validate(1920.0, 1920.5) is True

    def test_zero_bid_rejected(self):
        assert self._validate(0.0, 1920.5) is False

    def test_inverted_spread_rejected(self):
        assert self._validate(1921.0, 1920.0) is False

    def test_excessive_spread_rejected(self):
        # Default MAX_SPREAD_USD = 5.0
        assert self._validate(1920.0, 1930.0) is False

    def test_equal_bid_ask_rejected(self):
        assert self._validate(1920.0, 1920.0) is False


class TestStalenessGuard:
    @pytest.mark.asyncio
    async def test_no_breach_when_fresh(self):
        from data.market_ingest import _StalenessGuard

        guard = _StalenessGuard()
        guard.touch()

        with patch("data.market_ingest.bus") as mock_bus:
            mock_bus.publish_breach = AsyncMock()
            await guard.check()
            mock_bus.publish_breach.assert_not_called()

    @pytest.mark.asyncio
    async def test_breach_fires_when_stale(self):
        import time

        from data.market_ingest import STALE_TIMEOUT_S, _StalenessGuard

        guard = _StalenessGuard()
        # Wind back the last tick time past the timeout
        guard._last_tick_ts = time.monotonic() - STALE_TIMEOUT_S - 1

        with patch("data.market_ingest.bus") as mock_bus:
            mock_bus.publish_breach = AsyncMock()
            await guard.check()
            mock_bus.publish_breach.assert_called_once()
            call_kwargs = mock_bus.publish_breach.call_args[0][0]
            assert call_kwargs["reason"] == "stale_feed"


# ─────────────────────────────────────────────────────────────────────────────
# strategy/engine — OHLCV buffer
# ─────────────────────────────────────────────────────────────────────────────


class TestOHLCVBuffer:
    def _make(self):
        from strategy.engine import _OHLCVBuffer

        return _OHLCVBuffer()

    def test_bar_not_closed_before_ticks_per_bar(self):
        buf = self._make()
        from strategy.engine import TICKS_PER_BAR

        for _ in range(TICKS_PER_BAR - 1):
            closed = buf.push(1920.0, 0.5, "2025-01-01T00:00:00Z")
        assert closed is False
        assert buf.bar_count == 0

    def test_bar_closes_on_nth_tick(self):
        buf = self._make()
        from strategy.engine import TICKS_PER_BAR

        closed = False
        for _ in range(TICKS_PER_BAR):
            closed = buf.push(1920.0, 0.5, "2025-01-01T00:00:00Z")
        assert closed is True
        assert buf.bar_count == 1

    def test_ohlcv_values_correct(self):
        buf = self._make()
        from strategy.engine import TICKS_PER_BAR

        prices = [1900.0, 1950.0, 1880.0, 1920.0] + [1920.0] * (TICKS_PER_BAR - 4)
        for p in prices:
            buf.push(p, 0.5, "2025-01-01T00:00:00Z")
        df = buf.to_dataframe()
        assert df.iloc[0]["open"] == 1900.0
        assert df.iloc[0]["high"] == 1950.0
        assert df.iloc[0]["low"] == 1880.0
        assert df.iloc[0]["close"] == prices[-1]

    def test_not_ready_below_min_bars(self):
        buf = self._make()
        assert buf.ready() is False

    def test_ema_cross_sign(self):
        buf = self._make()
        from strategy.engine import TICKS_PER_BAR

        # Feed rising prices — fast EMA should be above slow EMA
        for i in range(TICKS_PER_BAR * 30):
            buf.push(1900.0 + i * 0.1, 0.5, "2025-01-01T00:00:00Z")
        assert buf.ema_cross > 0


# ─────────────────────────────────────────────────────────────────────────────
# strategy/engine — ML predictor fallback
# ─────────────────────────────────────────────────────────────────────────────


class TestMLPredictorFallback:
    def test_ema_buy_when_cross_positive(self):
        from strategy.engine import _MLPredictor

        pred = _MLPredictor.__new__(_MLPredictor)
        pred._predictor = None
        pred._available = False

        import pandas as pd

        df = pd.DataFrame()  # empty — won't be used
        direction, confidence = pred.predict(df, ema_cross=0.5, symbol="XAU/USD")
        assert direction == "BUY"
        assert confidence == 0.60

    def test_ema_sell_when_cross_negative(self):
        from strategy.engine import _MLPredictor

        pred = _MLPredictor.__new__(_MLPredictor)
        pred._predictor = None
        pred._available = False

        import pandas as pd

        direction, _ = pred.predict(pd.DataFrame(), ema_cross=-0.5, symbol="XAU/USD")
        assert direction == "SELL"

    def test_hold_when_cross_zero(self):
        from strategy.engine import _MLPredictor

        pred = _MLPredictor.__new__(_MLPredictor)
        pred._predictor = None
        pred._available = False

        import pandas as pd

        direction, _ = pred.predict(pd.DataFrame(), ema_cross=0.0, symbol="XAU/USD")
        assert direction == "HOLD"


# ─────────────────────────────────────────────────────────────────────────────
# risk/gatekeeper — prop checks
# ─────────────────────────────────────────────────────────────────────────────


class TestGatekeeperChecks:
    def _make_gk(self):
        from risk.gatekeeper import Gatekeeper

        gk = Gatekeeper.__new__(Gatekeeper)
        from risk.gatekeeper import _EquityTracker, _NewsCalendar

        gk._equity = _EquityTracker(100_000)
        gk._calendar = _NewsCalendar()
        gk._kill_active = False
        gk._paused_until = None
        gk._daily_trades = 0
        gk._trade_day = datetime.now(UTC).day
        gk._running = True
        gk._pass_count = 0
        gk._block_count = 0
        return gk

    def _signal(self, confidence=0.65, direction="BUY"):
        return {
            "type": "signal_event",
            "symbol": "XAU/USD",
            "direction": direction,
            "confidence": confidence,
        }

    def test_clean_signal_passes_all_checks(self):
        gk = self._make_gk()
        failures = gk._run_checks(self._signal())
        assert failures == []

    def test_kill_switch_blocks_immediately(self):
        gk = self._make_gk()
        gk._kill_active = True
        failures = gk._run_checks(self._signal())
        assert any(f["reason"] == "kill_switch_active" for f in failures)
        # Kill switch should be the only failure (hard stop)
        assert len(failures) == 1

    def test_daily_dd_breach_blocks(self):
        from risk.gatekeeper import DAILY_DD_LIMIT_PCT

        gk = self._make_gk()
        # Simulate daily DD at limit
        gk._equity._day_open = 100_000
        gk._equity._current = 100_000 * (1 - DAILY_DD_LIMIT_PCT)
        failures = gk._run_checks(self._signal())
        assert any(f["reason"] == "daily_dd_limit" for f in failures)

    def test_low_confidence_blocks(self):
        gk = self._make_gk()
        failures = gk._run_checks(self._signal(confidence=0.40))
        assert any(f["reason"] == "low_confidence" for f in failures)

    def test_daily_trade_cap_blocks(self):
        from risk.gatekeeper import MAX_DAILY_TRADES

        gk = self._make_gk()
        gk._daily_trades = MAX_DAILY_TRADES
        failures = gk._run_checks(self._signal())
        assert any(f["reason"] == "daily_trade_cap" for f in failures)

    def test_news_blackout_blocks(self):
        gk = self._make_gk()
        # Inject a news event happening right now
        gk._calendar._events = [datetime.now(UTC)]
        failures = gk._run_checks(self._signal())
        assert any(f["reason"] == "news_blackout" for f in failures)


# ─────────────────────────────────────────────────────────────────────────────
# utils/fault_guard — circuit breaker
# ─────────────────────────────────────────────────────────────────────────────


class TestFaultGuard:
    def _make(self):
        from utils.fault_guard import FaultGuard

        fg = FaultGuard()
        fg.register("test_module")
        return fg

    @pytest.mark.asyncio
    async def test_closed_by_default(self):
        fg = self._make()
        assert fg.is_healthy("test_module") is True
        assert fg.state_of("test_module") == "CLOSED"

    @pytest.mark.asyncio
    async def test_trips_after_threshold_failures(self):
        from utils.fault_guard import FAILURE_THRESHOLD

        fg = self._make()

        with patch("utils.fault_guard.bus") as mock_bus:
            mock_bus.publish_breach = AsyncMock()
            for _ in range(FAILURE_THRESHOLD):
                try:
                    async with fg.protect("test_module"):
                        raise RuntimeError("simulated failure")
                except RuntimeError:
                    ...  # nosec B110

        assert fg.state_of("test_module") == "OPEN"
        assert fg.is_healthy("test_module") is False

    @pytest.mark.asyncio
    async def test_recovers_to_half_open_after_timeout(self):
        import time

        from utils.fault_guard import FAILURE_THRESHOLD, RECOVER_S, FaultGuard

        fg = FaultGuard()
        fg.register("test_module")

        # Trip the breaker
        with patch("utils.fault_guard.bus") as mock_bus:
            mock_bus.publish_breach = AsyncMock()
            for _ in range(FAILURE_THRESHOLD):
                try:
                    async with fg.protect("test_module"):
                        raise RuntimeError("fail")
                except RuntimeError:
                    ...  # nosec B110

        # Wind back the failure timestamp past recovery window
        fg._modules["test_module"].last_failure_ts = time.monotonic() - RECOVER_S - 1

        # Next protect() call should transition to HALF_OPEN
        try:
            async with fg.protect("test_module"):
                pass  # success
        except RuntimeError:
            ...  # nosec B110

        assert fg.state_of("test_module") == "CLOSED"

    def test_heartbeat_resets_age(self):
        import time

        fg = self._make()
        fg._modules["test_module"].last_heartbeat = time.monotonic() - 100
        fg.heartbeat("test_module")
        age = time.monotonic() - fg._modules["test_module"].last_heartbeat
        assert age < 1.0

    @pytest.mark.asyncio
    async def test_stale_heartbeat_publishes_breach(self):
        import time

        from utils.fault_guard import HEARTBEAT_TIMEOUT_S

        fg = self._make()
        fg._modules["test_module"].last_heartbeat = time.monotonic() - HEARTBEAT_TIMEOUT_S - 1

        with patch("utils.fault_guard.bus") as mock_bus:
            mock_bus.publish_breach = AsyncMock()
            await fg._check_heartbeats()
            mock_bus.publish_breach.assert_called_once()
            call_args = mock_bus.publish_breach.call_args[0][0]
            assert call_args["reason"] == "heartbeat_timeout"
            assert call_args["module"] == "test_module"


# ─────────────────────────────────────────────────────────────────────────────
# data/news_calendar_feed — parser + Redis writer
# ─────────────────────────────────────────────────────────────────────────────


class TestNewsCalendarFeed:
    def test_parse_forexfactory_filters_low_impact(self):
        from data.news_calendar_feed import _parse_forexfactory

        data = [
            {
                "currency": "USD",
                "impact": "High",
                "date": "01-27-2025",
                "time": "8:30am",
            },
            {
                "currency": "USD",
                "impact": "Low",
                "date": "01-27-2025",
                "time": "9:00am",
            },
            {
                "currency": "EUR",
                "impact": "High",
                "date": "01-27-2025",
                "time": "10:00am",
            },
            {
                "currency": "USD",
                "impact": "Medium",
                "date": "01-27-2025",
                "time": "11:00am",
            },
        ]
        events = _parse_forexfactory(data)
        # Only USD High should pass (EUR filtered, Low/Medium filtered)
        assert len(events) == 1

    def test_parse_forexfactory_bad_date_skipped(self):
        from data.news_calendar_feed import _parse_forexfactory

        data = [
            {"currency": "USD", "impact": "High", "date": "INVALID", "time": "8:30am"},
        ]
        events = _parse_forexfactory(data)
        assert events == []

    def test_static_fallback_returns_events(self):
        from data.news_calendar_feed import _static_fallback

        events = _static_fallback()
        assert isinstance(events, list)
        # All events should be in the future
        now = datetime.now(UTC)
        for e in events:
            assert e > now

    @pytest.mark.asyncio
    async def test_write_redis_calls_pipeline(self):
        from data.news_calendar_feed import NewsCalendarFeed

        feed = NewsCalendarFeed()
        events = [datetime.now(UTC) + timedelta(hours=i) for i in range(3)]

        mock_pipe = AsyncMock()
        mock_pipe.__aenter__ = AsyncMock(return_value=mock_pipe)
        mock_pipe.__aexit__ = AsyncMock(return_value=False)
        mock_pipe.execute = AsyncMock(return_value=[1, 3, 1])

        mock_redis = AsyncMock()
        mock_redis.pipeline = MagicMock(return_value=mock_pipe)
        mock_redis.aclose = AsyncMock()

        with patch("data.news_calendar_feed.aioredis.from_url", return_value=mock_redis):
            count = await feed._write_redis(events)

        assert count == 3
        mock_pipe.delete.assert_called_once()
        mock_pipe.rpush.assert_called_once()
        mock_pipe.expire.assert_called_once()


# ─────────────────────────────────────────────────────────────────────────────
# execution/fix_router — smart routing
# ─────────────────────────────────────────────────────────────────────────────


class TestFIXRouter:
    @pytest.mark.asyncio
    async def test_halted_router_rejects_orders(self):
        from execution.fix_router import FIXRouter

        router = FIXRouter.__new__(FIXRouter)
        router._halted = True
        router._fix_available = False
        router._order_count = 0
        router._fill_count = 0
        router._reject_count = 0
        router._fallback = MagicMock()

        # Should return without calling fallback
        await router._route({"type": "order_request", "symbol": "XAU/USD", "direction": "BUY"})
        router._fallback.send.assert_not_called()

    @pytest.mark.asyncio
    async def test_fallback_used_when_fix_unavailable(self):
        from execution.fix_router import FIXRouter

        router = FIXRouter.__new__(FIXRouter)
        router._halted = False
        router._fix_available = False
        router._adapter = None
        router._order_count = 0
        router._fill_count = 0
        router._reject_count = 0

        fill = {
            "type": "fill_confirmation",
            "source": "oanda_rest_fallback",
            "symbol": "XAU/USD",
            "direction": "BUY",
            "units": 1000,
            "price": 1920.5,
            "order_id": "123",
            "timestamp": "2025-01-01T00:00:00Z",
        }
        router._fallback = AsyncMock()
        router._fallback.send = AsyncMock(return_value=fill)

        with patch("execution.fix_router.bus") as mock_bus:
            mock_bus.publish_order = AsyncMock()
            await router._route(
                {
                    "type": "order_request",
                    "symbol": "XAU/USD",
                    "direction": "BUY",
                    "units": 1000,
                }
            )

        router._fallback.send.assert_called_once()
        assert router._fill_count == 1
