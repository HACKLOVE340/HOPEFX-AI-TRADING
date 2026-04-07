# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
Coverage tests for brokers/ohlcv_store.py and risk/fia_compliance.py.
"""

import asyncio
from datetime import datetime, timezone

import pytest

UTC = timezone.utc


# ─────────────────────────────────────────────────────────────────────────────
# brokers/ohlcv_store.py
# ─────────────────────────────────────────────────────────────────────────────

def _make_bar(ts=None, o=1950.0, h=1960.0, l=1940.0, c=1955.0, v=100.0):
    return {
        "ts": ts or datetime.now(UTC).isoformat(),
        "open": o, "high": h, "low": l, "close": c, "volume": v,
    }


@pytest.mark.unit
class TestBarsToDF:
    def test_empty_list_returns_none(self):
        from brokers.ohlcv_store import _bars_to_df
        assert _bars_to_df([]) is None

    def test_single_bar_returns_df(self):
        from brokers.ohlcv_store import _bars_to_df
        df = _bars_to_df([_make_bar()])
        assert df is not None
        assert len(df) == 1
        assert "close" in df.columns

    def test_multiple_bars_sorted(self):
        from brokers.ohlcv_store import _bars_to_df
        bars = [
            _make_bar(ts="2024-01-02T00:00:00+00:00", c=1960.0),
            _make_bar(ts="2024-01-01T00:00:00+00:00", c=1950.0),
        ]
        df = _bars_to_df(bars)
        assert df is not None
        assert df.index[0] < df.index[1]

    def test_epoch_timestamp(self):
        from brokers.ohlcv_store import _bars_to_df
        bar = {"ts": 1700000000.0, "open": 1950.0, "high": 1960.0,
               "low": 1940.0, "close": 1955.0, "volume": 100.0}
        df = _bars_to_df([bar])
        assert df is not None

    def test_bar_open_ts_key(self):
        from brokers.ohlcv_store import _bars_to_df
        bar = {"bar_open_ts": 1700000000.0, "o": 1950.0, "h": 1960.0,
               "l": 1940.0, "c": 1955.0, "v": 100.0}
        df = _bars_to_df([bar])
        assert df is not None

    def test_no_timestamp_skipped(self):
        from brokers.ohlcv_store import _bars_to_df
        bar = {"open": 1950.0, "high": 1960.0, "low": 1940.0,
               "close": 1955.0, "volume": 100.0}
        result = _bars_to_df([bar])
        assert result is None  # no valid rows

    def test_duplicate_timestamps_deduplicated(self):
        from brokers.ohlcv_store import _bars_to_df
        ts = "2024-01-01T00:00:00+00:00"
        bars = [_make_bar(ts=ts, c=1950.0), _make_bar(ts=ts, c=1960.0)]
        df = _bars_to_df(bars)
        assert df is not None
        assert len(df) == 1


@pytest.mark.unit
class TestOHLCVStore:
    def _make_store(self):
        from brokers.ohlcv_store import OHLCVStore
        return OHLCVStore(timeframe="H1", max_bars=100)

    def test_push_and_buffer_size(self):
        store = self._make_store()
        store.push("XAUUSD", _make_bar())
        assert store.buffer_size("XAUUSD") == 1

    def test_push_multiple(self):
        store = self._make_store()
        for _ in range(5):
            store.push("XAUUSD", _make_bar())
        assert store.buffer_size("XAUUSD") == 5

    def test_buffer_size_unknown_symbol(self):
        store = self._make_store()
        assert store.buffer_size("UNKNOWN") == 0

    def test_symbols_returns_pushed(self):
        store = self._make_store()
        store.push("XAUUSD", _make_bar())
        store.push("EURUSD", _make_bar())
        assert "XAUUSD" in store.symbols()
        assert "EURUSD" in store.symbols()

    def test_get_returns_none_when_insufficient(self):
        from brokers.ohlcv_store import OHLCVStore
        store = OHLCVStore(max_bars=100)  # fresh instance, no shared state
        # Use a unique symbol that has no Redis history
        store.push("TEST_ONLY_SYMBOL_XYZ", _make_bar())
        result = store.get("TEST_ONLY_SYMBOL_XYZ", bars=500)
        assert result is None

    def test_get_returns_df_when_sufficient(self):
        store = self._make_store()
        import pandas as pd
        for i in range(20):
            ts = f"2024-01-{i+1:02d}T00:00:00+00:00"
            store.push("XAUUSD", _make_bar(ts=ts))
        result = store.get("XAUUSD", bars=10)
        assert result is not None
        assert isinstance(result, pd.DataFrame)
        assert len(result) >= 10

    def test_get_unknown_symbol_returns_none(self):
        store = self._make_store()
        assert store.get("UNKNOWN", bars=5) is None

    def test_push_adds_timestamp_if_missing(self):
        store = self._make_store()
        bar = {"open": 1950.0, "high": 1960.0, "low": 1940.0,
               "close": 1955.0, "volume": 100.0}
        store.push("XAUUSD", bar)
        assert store.buffer_size("XAUUSD") == 1

    def test_health_keys(self):
        store = self._make_store()
        h = store.health()
        assert "redis_ok" in h
        assert "timeframe" in h
        assert "max_bars" in h
        assert "symbols" in h

    def test_max_bars_ring_buffer(self):
        from brokers.ohlcv_store import OHLCVStore
        store = OHLCVStore(max_bars=5)
        for _ in range(10):
            store.push("XAUUSD", _make_bar())
        assert store.buffer_size("XAUUSD") == 5  # capped at max_bars

    def test_get_ohlcv_store_singleton(self):
        from brokers.ohlcv_store import get_ohlcv_store, OHLCVStore
        s1 = get_ohlcv_store()
        s2 = get_ohlcv_store()
        assert s1 is s2
        assert isinstance(s1, OHLCVStore)


# ─────────────────────────────────────────────────────────────────────────────
# risk/fia_compliance.py
# ─────────────────────────────────────────────────────────────────────────────

def _make_manager(config=None):
    from risk.fia_compliance import FIAComplianceManager
    return FIAComplianceManager(config or {
        "max_order_size": 100,
        "max_intraday_position": 500,
        "max_messages_per_second": 50,
        "daily_loss_limit": 0.03,
        "price_tolerance": 0.02,
    })


@pytest.mark.unit
class TestFIAComplianceManager:
    def test_check_max_order_size_pass(self):
        from risk.fia_compliance import RiskControlStatus
        mgr = _make_manager()
        result = mgr.check_max_order_size(50.0, "XAUUSD")
        assert result.status == RiskControlStatus.PASS

    def test_check_max_order_size_block(self):
        from risk.fia_compliance import RiskControlStatus
        mgr = _make_manager()
        result = mgr.check_max_order_size(200.0, "XAUUSD")
        assert result.status == RiskControlStatus.BLOCK
        assert "FIA_1.1" in result.rule

    def test_check_intraday_position_pass(self):
        from risk.fia_compliance import RiskControlStatus
        mgr = _make_manager()
        result = mgr.check_intraday_position("XAUUSD", 10.0)
        assert result.status == RiskControlStatus.PASS

    def test_check_intraday_position_block(self):
        from risk.fia_compliance import RiskControlStatus
        mgr = _make_manager()
        result = mgr.check_intraday_position("XAUUSD", 600.0)
        assert result.status == RiskControlStatus.BLOCK

    def test_check_intraday_position_accumulates(self):
        from risk.fia_compliance import RiskControlStatus
        mgr = _make_manager()
        mgr.check_intraday_position("XAUUSD", 300.0)
        result = mgr.check_intraday_position("XAUUSD", 300.0)
        assert result.status == RiskControlStatus.BLOCK

    def test_check_price_tolerance_pass(self):
        from risk.fia_compliance import RiskControlStatus
        mgr = _make_manager()
        result = mgr.check_price_tolerance(1950.0, 1950.0, tolerance_pct=0.02)
        assert result.status == RiskControlStatus.PASS

    def test_check_price_tolerance_block(self):
        from risk.fia_compliance import RiskControlStatus
        mgr = _make_manager()
        result = mgr.check_price_tolerance(2100.0, 1950.0, tolerance_pct=0.02)
        assert result.status == RiskControlStatus.BLOCK

    def test_check_price_tolerance_invalid_reference(self):
        from risk.fia_compliance import RiskControlStatus
        mgr = _make_manager()
        result = mgr.check_price_tolerance(1950.0, 0.0)
        assert result.status == RiskControlStatus.BLOCK

    def test_check_kill_switch_pass(self):
        from risk.fia_compliance import RiskControlStatus
        mgr = _make_manager()
        result = mgr.check_kill_switch(-1000.0, 100_000.0, threshold_pct=0.03)
        assert result.status == RiskControlStatus.PASS

    def test_check_kill_switch_activates(self):
        from risk.fia_compliance import RiskControlStatus
        mgr = _make_manager()
        result = mgr.check_kill_switch(-5000.0, 100_000.0, threshold_pct=0.03)
        assert result.status == RiskControlStatus.KILL_SWITCH
        assert mgr.kill_switch_active is True

    def test_kill_switch_callback_fires(self):
        mgr = _make_manager()
        fired = []
        mgr.register_kill_switch_callback(lambda pnl, pct: fired.append(pnl))
        mgr.check_kill_switch(-5000.0, 100_000.0, threshold_pct=0.03)
        assert len(fired) == 1
        assert fired[0] == pytest.approx(-5000.0)

    def test_validate_market_data_pass(self):
        from risk.fia_compliance import RiskControlStatus
        mgr = _make_manager()
        tick = {
            "timestamp": datetime.now(UTC),
            "bid": 1950.0,
            "ask": 1950.5,
        }
        result = mgr.validate_market_data(tick)
        assert result.status == RiskControlStatus.PASS

    def test_validate_market_data_invalid_prices(self):
        from risk.fia_compliance import RiskControlStatus
        mgr = _make_manager()
        result = mgr.validate_market_data({"bid": 0, "ask": 0})
        assert result.status == RiskControlStatus.BLOCK

    def test_validate_market_data_ask_less_than_bid(self):
        from risk.fia_compliance import RiskControlStatus
        mgr = _make_manager()
        result = mgr.validate_market_data({"bid": 1960.0, "ask": 1950.0})
        assert result.status == RiskControlStatus.BLOCK

    def test_check_message_throttle_pass(self):
        from risk.fia_compliance import RiskControlStatus
        mgr = _make_manager()
        result = mgr.check_message_throttle()
        assert result.status == RiskControlStatus.PASS

    def test_check_message_throttle_block(self):
        from risk.fia_compliance import RiskControlStatus
        mgr = _make_manager({"max_messages_per_second": 3})
        for _ in range(3):
            mgr.check_message_throttle()
        result = mgr.check_message_throttle()
        assert result.status == RiskControlStatus.BLOCK

    def test_check_self_trade_no_conflict(self):
        from risk.fia_compliance import RiskControlStatus
        mgr = _make_manager()
        order = {"side": "buy", "price": 1950.0}
        resting = [{"side": "buy", "price": 1950.0}]  # same side
        result = mgr.check_self_trade(order, resting)
        assert result.status == RiskControlStatus.PASS

    def test_check_self_trade_buy_crosses_sell(self):
        from risk.fia_compliance import RiskControlStatus
        mgr = _make_manager()
        order = {"side": "buy", "price": 1960.0}
        resting = [{"side": "sell", "price": 1950.0}]
        result = mgr.check_self_trade(order, resting)
        assert result.status == RiskControlStatus.BLOCK

    def test_check_self_trade_sell_crosses_buy(self):
        from risk.fia_compliance import RiskControlStatus
        mgr = _make_manager()
        order = {"side": "sell", "price": 1940.0}
        resting = [{"side": "buy", "price": 1950.0}]
        result = mgr.check_self_trade(order, resting)
        assert result.status == RiskControlStatus.BLOCK

    def test_validate_order_full_pipeline(self):
        from risk.fia_compliance import RiskControlStatus
        mgr = _make_manager()
        order = {"symbol": "XAUUSD", "side": "buy", "size": 1.0, "price": 1950.0}
        market = {"mid": 1950.0, "bid": 1949.5, "ask": 1950.5,
                  "timestamp": datetime.now(UTC)}
        portfolio = {"daily_pnl": -100.0, "capital": 100_000.0}
        results = asyncio.run(mgr.validate_order(order, market, portfolio))
        assert len(results) > 0
        statuses = [r.status for r in results]
        assert RiskControlStatus.PASS in statuses

    def test_validate_order_kill_switch_stops_early(self):
        from risk.fia_compliance import RiskControlStatus
        mgr = _make_manager()
        order = {"symbol": "XAUUSD", "side": "buy", "size": 1.0, "price": 1950.0}
        market = {"mid": 1950.0, "bid": 1949.5, "ask": 1950.5,
                  "timestamp": datetime.now(UTC)}
        portfolio = {"daily_pnl": -5000.0, "capital": 100_000.0}
        results = asyncio.run(mgr.validate_order(order, market, portfolio))
        assert results[0].status == RiskControlStatus.KILL_SWITCH
        assert len(results) == 1  # stopped early
