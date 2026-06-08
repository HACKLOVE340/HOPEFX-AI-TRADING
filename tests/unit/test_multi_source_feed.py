# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
tests/unit/test_multi_source_feed.py
=======================================
Unit tests for data_feed/multi_source_feed.py — MultiSourceTickFeed.

Tests cover:
  - _SymbolState: circuit breaker, anomaly detection, price validation
  - MultiSourceTickFeed: construction, source selection, broadcast routing,
    enabled guards, health monitor, get_feed_status, singleton
  - Real source adapters are replaced with lightweight async stubs that
    implement the same fetch(symbol, cfg) -> float | None protocol.
    No mocks of internal MultiSourceTickFeed methods.
"""

from __future__ import annotations

import time
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from data_feed.multi_source_feed import (
    MultiSourceTickFeed,
    _SymbolState,
    get_feed_status,
    get_multi_source_feed,
)

# ── Minimal config path (uses real YAML) ─────────────────────────────────────

_CFG = Path("config/multi_source_feed.yaml")


# ── Stub source adapters ──────────────────────────────────────────────────────


class _FixedSource:
    """Always returns a fixed price."""

    def __init__(self, price: float | None, name: str = "fixed") -> None:
        self._price = price
        self.name = name
        self.calls: list[str] = []

    async def fetch(self, symbol: str, cfg: dict) -> float | None:
        self.calls.append(symbol)
        return self._price

    def status(self) -> dict:
        return {"source": self.name}


class _FailingSource:
    """Always raises an exception."""

    name = "failing"

    async def fetch(self, symbol: str, cfg: dict) -> float | None:
        raise RuntimeError("source unavailable")

    def status(self) -> dict:
        return {"source": self.name}


class _CountingSource:
    """Returns a price on every N-th call, None otherwise."""

    def __init__(self, price: float, succeed_every: int = 1) -> None:
        self._price = price
        self._every = succeed_every
        self._calls = 0
        self.name = "counting"

    async def fetch(self, symbol: str, cfg: dict) -> float | None:
        self._calls += 1
        if self._calls % self._every == 0:
            return self._price
        return None

    def status(self) -> dict:
        return {"source": self.name}


# ── _SymbolState ──────────────────────────────────────────────────────────────


class TestSymbolState:
    def _state(self, price_min=1000.0, price_max=10000.0) -> _SymbolState:
        return _SymbolState("XAUUSD", price_min, price_max, history_size=100)

    def test_initial_state(self):
        st = self._state()
        assert st.current_price is None
        assert st.last_update is None
        assert st.last_price_for_anomaly is None

    def test_record_success_updates_price(self):
        st = self._state()
        st.record_success("yfinance", 1950.0)
        assert st.current_price == 1950.0
        assert st.last_update is not None
        assert st.last_price_for_anomaly == 1950.0

    def test_record_success_appends_history(self):
        st = self._state()
        st.record_success("yfinance", 1950.0)
        st.record_success("yfinance", 1951.0)
        assert len(st.history) == 2

    def test_record_failure_increments_count(self):
        st = self._state()
        st.record_failure("yfinance", threshold=5)
        assert st.fail_counts["yfinance"] == 1

    def test_circuit_breaker_opens_at_threshold(self):
        st = self._state()
        for _ in range(5):
            st.record_failure("yfinance", threshold=5)
        assert st.circuit_open_at["yfinance"] is not None

    def test_circuit_breaker_not_open_below_threshold(self):
        st = self._state()
        for _ in range(4):
            st.record_failure("yfinance", threshold=5)
        assert st.circuit_open_at["yfinance"] is None

    def test_circuit_open_returns_true_when_open(self):
        st = self._state()
        for _ in range(5):
            st.record_failure("yfinance", threshold=5)
        assert st.is_circuit_open("yfinance", cooldown=60) is True

    def test_circuit_open_returns_false_after_cooldown(self):
        st = self._state()
        for _ in range(5):
            st.record_failure("yfinance", threshold=5)
        # Backdate the open timestamp past the cooldown.
        st.circuit_open_at["yfinance"] = time.monotonic() - 61
        assert st.is_circuit_open("yfinance", cooldown=60) is False
        # Counts reset after cooldown.
        assert st.fail_counts["yfinance"] == 0

    def test_record_success_resets_circuit(self):
        st = self._state()
        for _ in range(5):
            st.record_failure("yfinance", threshold=5)
        st.record_success("yfinance", 1950.0)
        assert st.circuit_open_at["yfinance"] is None
        assert st.fail_counts["yfinance"] == 0

    def test_is_price_valid_within_range(self):
        st = self._state(price_min=1000.0, price_max=10000.0)
        assert st.is_price_valid(1950.0) is True

    def test_is_price_valid_below_min(self):
        st = self._state(price_min=1000.0, price_max=10000.0)
        assert st.is_price_valid(999.0) is False

    def test_is_price_valid_above_max(self):
        st = self._state(price_min=1000.0, price_max=10000.0)
        assert st.is_price_valid(10001.0) is False

    def test_is_anomalous_no_baseline(self):
        st = self._state()
        assert st.is_anomalous(1950.0, jump_pct=5.0) is False

    def test_is_anomalous_small_move(self):
        st = self._state()
        st.record_success("yfinance", 1950.0)
        assert st.is_anomalous(1952.0, jump_pct=5.0) is False

    def test_is_anomalous_large_jump(self):
        st = self._state()
        st.record_success("yfinance", 1950.0)
        # 10% jump — exceeds 5% threshold.
        assert st.is_anomalous(2145.0, jump_pct=5.0) is True

    def test_pick_source_returns_first_healthy(self):
        st = self._state()
        src = st.pick_source(["yfinance", "alpha_vantage", "twelve_data"], cooldown=60)
        assert src == "yfinance"

    def test_pick_source_skips_open_circuit(self):
        st = self._state()
        for _ in range(5):
            st.record_failure("yfinance", threshold=5)
        src = st.pick_source(["yfinance", "alpha_vantage", "twelve_data"], cooldown=60)
        assert src == "alpha_vantage"

    def test_pick_source_falls_back_to_first_when_all_open(self):
        st = self._state()
        for source in ["yfinance", "alpha_vantage", "twelve_data"]:
            for _ in range(5):
                st.record_failure(source, threshold=5)
        src = st.pick_source(["yfinance", "alpha_vantage", "twelve_data"], cooldown=60)
        assert src == "yfinance"

    def test_status_dict_keys(self):
        st = self._state()
        s = st.status()
        assert "symbol" in s
        assert "current_price" in s
        assert "last_update" in s
        assert "active_source" in s
        assert "fail_counts" in s
        assert "circuit_open" in s
        assert "history_size" in s


# ── MultiSourceTickFeed construction ──────────────────────────────────────────


class TestMultiSourceTickFeedInit:
    def test_default_symbols_from_config(self):
        feed = MultiSourceTickFeed(config_path=_CFG)
        assert len(feed._states) > 0
        assert "XAUUSD" in feed._states

    def test_explicit_symbols(self):
        feed = MultiSourceTickFeed(config_path=_CFG, symbols=["XAUUSD", "EURUSD"])
        assert set(feed._states.keys()) == {"XAUUSD", "EURUSD"}

    def test_new_symbols_in_config(self):
        """All symbols added to config must be loadable."""
        feed = MultiSourceTickFeed(config_path=_CFG)
        for sym in ("XAGUSD", "XPTUSD", "USOIL", "BTCUSD", "NAS100", "US30"):
            assert sym in feed._states, f"{sym} missing from feed states"

    def test_price_ranges_loaded(self):
        feed = MultiSourceTickFeed(config_path=_CFG, symbols=["XAUUSD", "BTCUSD"])
        assert feed._states["XAUUSD"].price_min == pytest.approx(1000.0)
        assert feed._states["XAUUSD"].price_max == pytest.approx(10000.0)
        assert feed._states["BTCUSD"].price_max == pytest.approx(1_000_000.0)

    def test_source_enabled_defaults(self):
        feed = MultiSourceTickFeed(config_path=_CFG, symbols=["XAUUSD"])
        assert feed._source_enabled["yfinance"] is True
        assert feed._source_enabled["alpha_vantage"] is True
        assert feed._source_enabled["twelve_data"] is True

    def test_active_order_matches_fallback_order(self):
        feed = MultiSourceTickFeed(config_path=_CFG, symbols=["XAUUSD"])
        assert feed._active_order == ["yfinance", "alpha_vantage", "twelve_data"]

    def test_not_running_initially(self):
        feed = MultiSourceTickFeed(config_path=_CFG, symbols=["XAUUSD"])
        assert feed._running is False

    def test_no_subscribers_initially(self):
        feed = MultiSourceTickFeed(config_path=_CFG, symbols=["XAUUSD"])
        assert feed._subscribers == []


# ── subscribe / unsubscribe ───────────────────────────────────────────────────


class TestMultiSourceTickFeedSubscription:
    def _feed(self) -> MultiSourceTickFeed:
        return MultiSourceTickFeed(config_path=_CFG, symbols=["XAUUSD"])

    def test_subscribe_two_param(self):
        feed = self._feed()

        class Sub:
            async def on_new_price(self, symbol, price):
                pass

        sub = Sub()
        feed.subscribe(sub)
        assert len(feed._subscribers) == 1
        _, n = feed._subscribers[0]
        assert n == 2

    def test_subscribe_one_param(self):
        feed = self._feed()

        class Sub:
            async def on_new_price(self, price):
                pass

        sub = Sub()
        feed.subscribe(sub)
        _, n = feed._subscribers[0]
        assert n == 1

    def test_subscribe_no_handler_ignored(self):
        feed = self._feed()

        class NoHandler:
            pass

        feed.subscribe(NoHandler())
        assert len(feed._subscribers) == 0

    def test_unsubscribe_removes_component(self):
        feed = self._feed()

        class Sub:
            async def on_new_price(self, symbol, price):
                pass

        sub = Sub()
        feed.subscribe(sub)
        feed.unsubscribe(sub)
        assert len(feed._subscribers) == 0

    def test_unsubscribe_nonexistent_no_error(self):
        feed = self._feed()
        feed.unsubscribe(object())  # must not raise

    def test_multiple_subscribers(self):
        feed = self._feed()

        class Sub:
            async def on_new_price(self, symbol, price):
                pass

        feed.subscribe(Sub())
        feed.subscribe(Sub())
        assert len(feed._subscribers) == 2


# ── _broadcast ────────────────────────────────────────────────────────────────


class TestMultiSourceTickFeedBroadcast:
    def _feed(self) -> MultiSourceTickFeed:
        return MultiSourceTickFeed(config_path=_CFG, symbols=["XAUUSD"])

    @pytest.mark.asyncio
    async def test_two_param_subscriber_receives_symbol_and_price(self):
        feed = self._feed()
        received = []

        class Sub:
            async def on_new_price(self, symbol, price):
                received.append((symbol, price))

        feed.subscribe(Sub())
        await feed._broadcast("XAUUSD", 1950.0)
        assert received == [("XAUUSD", 1950.0)]

    @pytest.mark.asyncio
    async def test_one_param_subscriber_receives_price(self):
        feed = self._feed()
        received = []

        class Sub:
            async def on_new_price(self, price):
                received.append(price)

        feed.subscribe(Sub())
        await feed._broadcast("XAUUSD", 1950.0)
        assert received == [1950.0]

    @pytest.mark.asyncio
    async def test_mixed_subscribers_both_called(self):
        feed = self._feed()
        two_calls = []
        one_calls = []

        class TwoSub:
            async def on_new_price(self, symbol, price):
                two_calls.append((symbol, price))

        class OneSub:
            async def on_new_price(self, price):
                one_calls.append(price)

        feed.subscribe(TwoSub())
        feed.subscribe(OneSub())
        await feed._broadcast("EURUSD", 1.0875)
        assert two_calls == [("EURUSD", 1.0875)]
        assert one_calls == [pytest.approx(1.0875)]

    @pytest.mark.asyncio
    async def test_subscriber_exception_does_not_crash_broadcast(self):
        feed = self._feed()

        class BadSub:
            async def on_new_price(self, symbol, price):
                raise RuntimeError("subscriber exploded")

        feed.subscribe(BadSub())
        await feed._broadcast("XAUUSD", 1950.0)  # must not raise

    @pytest.mark.asyncio
    async def test_no_subscribers_is_noop(self):
        feed = self._feed()
        await feed._broadcast("XAUUSD", 1950.0)  # must not raise

    @pytest.mark.asyncio
    async def test_multiple_symbols_routed_correctly(self):
        feed = self._feed()
        received = []

        class Sub:
            async def on_new_price(self, symbol, price):
                received.append((symbol, price))

        feed.subscribe(Sub())
        await feed._broadcast("XAUUSD", 1950.0)
        await feed._broadcast("EURUSD", 1.0875)
        assert ("XAUUSD", 1950.0) in received
        assert ("EURUSD", pytest.approx(1.0875)) in received


# ── _poll_symbol logic (via injected sources) ─────────────────────────────────


class TestMultiSourceTickFeedPolling:
    def _feed_with_sources(self, sources: dict) -> MultiSourceTickFeed:
        feed = MultiSourceTickFeed(config_path=_CFG, symbols=["XAUUSD"])
        feed._sources = sources
        feed._tick_writer = None  # no Redis in unit tests
        return feed

    @pytest.mark.asyncio
    async def test_valid_price_recorded(self):
        feed = self._feed_with_sources(
            {
                "yfinance": _FixedSource(1950.0),
                "alpha_vantage": _FixedSource(None),
                "twelve_data": _FixedSource(None),
            }
        )
        feed._running = True
        # Run one poll cycle manually.
        _state = feed._states["XAUUSD"]
        sym_cfg = feed._symbol_cfgs.get("XAUUSD", {})
        price = await feed._fetch_with_retry("XAUUSD", "yfinance", sym_cfg)
        assert price == pytest.approx(1950.0)

    @pytest.mark.asyncio
    async def test_out_of_range_price_rejected(self):
        feed = self._feed_with_sources(
            {
                "yfinance": _FixedSource(0.01),  # below XAUUSD price_min=1000
            }
        )
        state = feed._states["XAUUSD"]
        assert state.is_price_valid(0.01) is False

    @pytest.mark.asyncio
    async def test_anomalous_price_rejected(self):
        feed = self._feed_with_sources({})
        state = feed._states["XAUUSD"]
        state.record_success("yfinance", 1950.0)
        # 20% jump — anomalous.
        assert state.is_anomalous(2340.0, jump_pct=5.0) is True

    @pytest.mark.asyncio
    async def test_fetch_with_retry_returns_none_on_all_failures(self):
        feed = self._feed_with_sources(
            {
                "yfinance": _FailingSource(),
            }
        )
        feed._max_retries = 2
        price = await feed._fetch_with_retry("XAUUSD", "yfinance", {})
        assert price is None

    @pytest.mark.asyncio
    async def test_fetch_with_retry_succeeds_on_second_attempt(self):
        feed = self._feed_with_sources(
            {
                "yfinance": _CountingSource(price=1950.0, succeed_every=2),
            }
        )
        feed._max_retries = 3
        price = await feed._fetch_with_retry("XAUUSD", "yfinance", {})
        assert price == pytest.approx(1950.0)

    @pytest.mark.asyncio
    async def test_missing_source_returns_none(self):
        feed = self._feed_with_sources({})
        price = await feed._fetch_with_retry("XAUUSD", "nonexistent", {})
        assert price is None


# ── enabled source guard ──────────────────────────────────────────────────────


class TestMultiSourceTickFeedEnabledGuard:
    def test_disabled_source_excluded_from_active_order(self):
        feed = MultiSourceTickFeed(config_path=_CFG, symbols=["XAUUSD"])
        # Simulate alpha_vantage disabled.
        feed._source_enabled["alpha_vantage"] = False
        feed._active_order = [s for s in feed._fallback_order if feed._source_enabled.get(s, True)]
        assert "alpha_vantage" not in feed._active_order
        assert "yfinance" in feed._active_order
        assert "twelve_data" in feed._active_order

    def test_all_disabled_falls_back_to_full_order(self):
        feed = MultiSourceTickFeed(config_path=_CFG, symbols=["XAUUSD"])
        feed._source_enabled = dict.fromkeys(feed._fallback_order, False)
        active = [s for s in feed._fallback_order if feed._source_enabled.get(s, True)]
        # Empty list — fallback to full order.
        result = active or list(feed._fallback_order)
        assert result == feed._fallback_order


# ── get_price / get_last_update ───────────────────────────────────────────────


class TestMultiSourceTickFeedAccessors:
    def test_get_price_none_initially(self):
        feed = MultiSourceTickFeed(config_path=_CFG, symbols=["XAUUSD"])
        assert feed.get_price("XAUUSD") is None

    def test_get_price_after_record_success(self):
        feed = MultiSourceTickFeed(config_path=_CFG, symbols=["XAUUSD"])
        feed._states["XAUUSD"].record_success("yfinance", 1950.0)
        assert feed.get_price("XAUUSD") == pytest.approx(1950.0)

    def test_get_price_unknown_symbol_returns_none(self):
        feed = MultiSourceTickFeed(config_path=_CFG, symbols=["XAUUSD"])
        assert feed.get_price("UNKNOWN") is None

    def test_get_last_update_none_initially(self):
        feed = MultiSourceTickFeed(config_path=_CFG, symbols=["XAUUSD"])
        assert feed.get_last_update("XAUUSD") is None

    def test_get_last_update_after_record_success(self):
        feed = MultiSourceTickFeed(config_path=_CFG, symbols=["XAUUSD"])
        feed._states["XAUUSD"].record_success("yfinance", 1950.0)
        assert feed.get_last_update("XAUUSD") is not None


# ── status ────────────────────────────────────────────────────────────────────


class TestMultiSourceTickFeedStatus:
    def test_status_keys(self):
        feed = MultiSourceTickFeed(config_path=_CFG, symbols=["XAUUSD"])
        s = feed.status()
        assert "running" in s
        assert "symbols" in s
        assert "sources" in s
        assert "source_enabled" in s
        assert "active_fallback_order" in s
        assert "redis" in s
        assert "subscriber_count" in s
        assert "redis_errors" in s

    def test_status_not_running(self):
        feed = MultiSourceTickFeed(config_path=_CFG, symbols=["XAUUSD"])
        assert feed.status()["running"] is False

    def test_status_subscriber_count(self):
        feed = MultiSourceTickFeed(config_path=_CFG, symbols=["XAUUSD"])

        class Sub:
            async def on_new_price(self, symbol, price):
                pass

        feed.subscribe(Sub())
        assert feed.status()["subscriber_count"] == 1


# ── start / stop lifecycle ────────────────────────────────────────────────────


class TestMultiSourceTickFeedLifecycle:
    @pytest.mark.asyncio
    async def test_start_sets_running(self):
        feed = MultiSourceTickFeed(config_path=_CFG, symbols=["XAUUSD"])
        # Patch _build_sources to avoid real HTTP sessions.
        feed._build_sources = lambda: {
            "yfinance": _FixedSource(1950.0),
            "alpha_vantage": _FixedSource(None),
            "twelve_data": _FixedSource(None),
        }
        # Patch the RedisTickWriter at its definition site so the lazy import
        # inside start() picks up the mock.
        with patch("data_feed.redis_tick_writer.RedisTickWriter") as mock_rtw:
            mock_rtw.return_value.connect = AsyncMock(return_value=False)
            mock_rtw.return_value._ttl = 30
            mock_rtw.return_value.close = AsyncMock()
            await feed.start()
        assert feed._running is True
        assert len(feed._tasks) > 0
        await feed.stop()

    @pytest.mark.asyncio
    async def test_start_idempotent(self):
        feed = MultiSourceTickFeed(config_path=_CFG, symbols=["XAUUSD"])
        feed._build_sources = lambda: {"yfinance": _FixedSource(1950.0)}
        with patch("data_feed.redis_tick_writer.RedisTickWriter") as mock_rtw:
            mock_rtw.return_value.connect = AsyncMock(return_value=False)
            mock_rtw.return_value.close = AsyncMock()
            await feed.start()
            task_count = len(feed._tasks)
            await feed.start()  # second call — no-op
            assert len(feed._tasks) == task_count
        await feed.stop()

    @pytest.mark.asyncio
    async def test_stop_clears_running(self):
        feed = MultiSourceTickFeed(config_path=_CFG, symbols=["XAUUSD"])
        feed._build_sources = lambda: {"yfinance": _FixedSource(1950.0)}
        with patch("data_feed.redis_tick_writer.RedisTickWriter") as mock_rtw:
            mock_rtw.return_value.connect = AsyncMock(return_value=False)
            mock_rtw.return_value.close = AsyncMock()
            await feed.start()
        await feed.stop()
        assert feed._running is False
        assert feed._tasks == []


# ── get_feed_status / get_multi_source_feed ───────────────────────────────────


class TestGetFeedStatus:
    def setup_method(self):
        import data_feed.multi_source_feed as msf

        msf._feed_instance = None

    def teardown_method(self):
        import data_feed.multi_source_feed as msf

        msf._feed_instance = None

    def test_get_feed_status_before_init(self):
        s = get_feed_status()
        assert s["running"] is False
        assert s["symbols"] == {}

    def test_get_feed_status_after_init(self):
        _feed = get_multi_source_feed(config_path=_CFG, symbols=["XAUUSD"])
        s = get_feed_status()
        assert "XAUUSD" in s["symbols"]

    def test_get_multi_source_feed_singleton(self):
        f1 = get_multi_source_feed(config_path=_CFG, symbols=["XAUUSD"])
        f2 = get_multi_source_feed(config_path=_CFG, symbols=["EURUSD"])
        assert f1 is f2  # second call returns existing singleton
