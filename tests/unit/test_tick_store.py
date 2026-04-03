# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
"""
tests/unit/test_tick_store.py
==============================
Unit tests for data_layer/tick_store.py.

All tests use the in-memory backend so they run without Redis or PostgreSQL.
"""

from __future__ import annotations

import time

import pandas as pd


# ── helpers ──────────────────────────────────────────────────────────────────
def _make_store():
    """Return a fresh TickStore backed by the in-memory backend."""
    import importlib
    import os

    os.environ["TICK_STORE_BACKEND"] = "memory"
    # Re-import with the forced backend
    import data_layer.tick_store as mod

    importlib.reload(mod)  # ensure singleton is reset with new env
    return mod.TickStore()


# ── Basic insert / query ──────────────────────────────────────────────────────
class TestInsertQuery:
    def test_insert_single_tick(self):
        store = _make_store()
        ts = time.time_ns()
        store.insert("XAUUSD", ts_ns=ts, bid=2300.10, ask=2300.20)
        df = store.query("XAUUSD", limit=10)
        assert isinstance(df, pd.DataFrame)
        assert len(df) == 1
        assert abs(df.iloc[0]["bid"] - 2300.10) < 1e-6

    def test_insert_multiple_ticks(self):
        store = _make_store()
        base = time.time_ns()
        for i in range(20):
            store.insert("XAUUSD", ts_ns=base + i * 1_000_000, bid=2300.0 + i, ask=2300.1 + i)
        df = store.query("XAUUSD", limit=5)
        assert len(df) == 5

    def test_query_limit_respected(self):
        store = _make_store()
        base = time.time_ns()
        for i in range(100):
            store.insert("XAUUSD", ts_ns=base + i * 1_000_000, bid=2000.0, ask=2000.1)
        df = store.query("XAUUSD", limit=50)
        assert len(df) <= 50

    def test_query_empty_symbol_returns_empty_df(self):
        store = _make_store()
        df = store.query("EURUSD", limit=100)
        assert isinstance(df, pd.DataFrame)
        assert len(df) == 0

    def test_mid_and_spread_computed(self):
        store = _make_store()
        ts = time.time_ns()
        store.insert("XAUUSD", ts_ns=ts, bid=2300.0, ask=2301.0)
        df = store.query("XAUUSD", limit=1)
        assert abs(df.iloc[0]["mid"] - 2300.5) < 1e-6
        assert abs(df.iloc[0]["spread"] - 1.0) < 1e-6

    def test_default_ts_ns(self):
        """insert() without explicit ts_ns should use time.time_ns()."""
        store = _make_store()
        before = time.time_ns()
        store.insert("XAUUSD", bid=2300.0, ask=2300.1)
        after = time.time_ns()
        df = store.query("XAUUSD", limit=1)
        assert len(df) == 1
        ts = int(df.iloc[0]["ts_ns"])
        assert before <= ts <= after

    def test_volume_and_source_stored(self):
        store = _make_store()
        ts = time.time_ns()
        store.insert("XAUUSD", ts_ns=ts, bid=2300.0, ask=2300.1, volume=10.5, source="oanda")
        df = store.query("XAUUSD", limit=1)
        assert abs(df.iloc[0]["volume"] - 10.5) < 1e-6


# ── OHLCV aggregation ─────────────────────────────────────────────────────────
class TestOHLCV:
    def test_ohlcv_single_bar(self):
        store = _make_store()
        base_ns = 1_700_000_000_000_000_000  # fixed timestamp
        # 3 ticks in the same 1-minute bar
        store.insert("XAUUSD", ts_ns=base_ns + 0, bid=2300.0, ask=2300.2)
        store.insert("XAUUSD", ts_ns=base_ns + 1_000_000, bid=2302.0, ask=2302.2)
        store.insert("XAUUSD", ts_ns=base_ns + 2_000_000, bid=2301.0, ask=2301.2)

        df = store.ohlcv("XAUUSD", timeframe_s=60, limit=10)
        assert isinstance(df, pd.DataFrame)
        assert len(df) == 1
        row = df.iloc[0]
        # open should be first tick mid, close should be last tick mid
        assert abs(row["open"] - 2300.1) < 0.01
        assert abs(row["close"] - 2301.1) < 0.01
        assert row["high"] >= row["low"]
        assert int(row["tick_count"]) == 3

    def test_ohlcv_multiple_bars(self):
        store = _make_store()
        base_ns = 1_700_000_000_000_000_000
        bar_ns = 60 * 1_000_000_000  # 1 minute in nanoseconds
        # 5 ticks spread across 3 bars
        for bar in range(3):
            for tick in range(2):
                ts = base_ns + bar * bar_ns + tick * 1_000_000
                store.insert("XAUUSD", ts_ns=ts, bid=2300.0 + bar, ask=2300.1 + bar)
        store.insert("XAUUSD", ts_ns=base_ns + 2 * bar_ns + 5_000_000, bid=2302.0, ask=2302.1)

        df = store.ohlcv("XAUUSD", timeframe_s=60, limit=10)
        assert len(df) == 3

    def test_ohlcv_empty_returns_empty_df(self):
        store = _make_store()
        df = store.ohlcv("XAUUSD", timeframe_s=60, limit=10)
        assert isinstance(df, pd.DataFrame)
        assert len(df) == 0

    def test_to_ohlcv_df_format(self):
        store = _make_store()
        base_ns = 1_700_000_000_000_000_000
        store.insert("XAUUSD", ts_ns=base_ns, bid=2300.0, ask=2300.2, volume=5.0)
        df = store.to_ohlcv_df("XAUUSD", timeframe_s=60, limit=10)
        assert isinstance(df, pd.DataFrame)
        # Should have standard OHLCV columns
        for col in ["open", "high", "low", "close", "volume"]:
            assert col in df.columns


# ── latest / flush ────────────────────────────────────────────────────────────
class TestLatestFlush:
    def test_latest_returns_most_recent(self):
        store = _make_store()
        base = time.time_ns()
        store.insert("XAUUSD", ts_ns=base, bid=2300.0, ask=2300.1)
        store.insert("XAUUSD", ts_ns=base + 1_000, bid=2305.0, ask=2305.1)
        latest = store.latest("XAUUSD")
        assert latest is not None
        assert abs(latest["bid"] - 2305.0) < 1e-6

    def test_latest_none_for_empty_symbol(self):
        store = _make_store()
        assert store.latest("UNKNOWN") is None

    def test_flush_removes_ticks(self):
        store = _make_store()
        base = time.time_ns()
        for i in range(10):
            store.insert("XAUUSD", ts_ns=base + i, bid=2300.0, ask=2300.1)
        n = store.flush("XAUUSD")
        assert n == 10
        df = store.query("XAUUSD", limit=100)
        assert len(df) == 0


# ── health check ─────────────────────────────────────────────────────────────
class TestHealth:
    def test_health_returns_dict(self):
        store = _make_store()
        h = store.health()
        assert isinstance(h, dict)
        assert h["status"] == "ok"
        assert "backend" in h

    def test_health_includes_backend_class(self):
        store = _make_store()
        h = store.health()
        assert "backend_class" in h
        assert "Memory" in h["backend_class"]


# ── since_ns filter ───────────────────────────────────────────────────────────
class TestSinceFilter:
    def test_since_ns_filters_older_ticks(self):
        store = _make_store()
        base = 1_700_000_000_000_000_000
        for i in range(10):
            store.insert("XAUUSD", ts_ns=base + i * 1_000_000_000, bid=2300.0, ask=2300.1)
        cutoff = base + 5 * 1_000_000_000
        df = store.query("XAUUSD", since_ns=cutoff, limit=100)
        assert all(df["ts_ns"] >= cutoff)


# ── _aggregate_ohlcv (standalone function) ────────────────────────────────────
class TestAggregateOHLCV:
    def test_empty_input_returns_empty(self):
        from data_layer.tick_store import _aggregate_ohlcv

        result = _aggregate_ohlcv([], 60, 10)
        assert result == []

    def test_aggregates_high_low(self):
        from data_layer.tick_store import _aggregate_ohlcv

        base_ns = 1_700_000_000_000_000_000
        ticks = [
            {"ts_ns": base_ns + i * 1_000_000, "mid": float(2300 + i), "volume": 1.0}
            for i in range(5)
        ]
        bars = _aggregate_ohlcv(ticks, timeframe_s=60, limit=5)
        assert len(bars) == 1
        assert bars[0]["high"] == max(t["mid"] for t in ticks)
        assert bars[0]["low"] == min(t["mid"] for t in ticks)

    def test_limit_respected(self):
        from data_layer.tick_store import _aggregate_ohlcv

        base_ns = 1_700_000_000_000_000_000
        bar_ns = 60 * 1_000_000_000
        ticks = [
            {"ts_ns": base_ns + i * bar_ns, "mid": 2300.0, "volume": 1.0}
            for i in range(20)
        ]
        bars = _aggregate_ohlcv(ticks, timeframe_s=60, limit=5)
        assert len(bars) == 5


# ── get_tick_store singleton ──────────────────────────────────────────────────
class TestSingleton:
    def test_get_tick_store_returns_instance(self):
        import os

        os.environ["TICK_STORE_BACKEND"] = "memory"
        # Reset singleton
        import data_layer.tick_store as mod

        mod._instance = None
        store = mod.get_tick_store()
        assert store is not None
        # Second call returns same instance
        store2 = mod.get_tick_store()
        assert store is store2
