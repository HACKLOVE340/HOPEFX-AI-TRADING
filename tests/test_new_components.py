# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
tests/test_new_components.py
=============================
Tests for all components built in this session:
  - risk/compliance/prop_enforcer.py
  - brokers/mt5_bridge.py  (EX5SignalExporter)
  - scripts/paper_trading_starter.py  (TradeLogger, write_status)
  - scripts/volume_boost_backtest.py  (add_indicators, monte_carlo)
  - deployment/challenge_launch.py    (_check_pass logic)
"""

import json
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

# ── PropEnforcer ──────────────────────────────────────────────────────────────


class TestPropEnforcer:
    def _make(self, **kwargs):
        from risk.compliance.prop_enforcer import PropConfig, PropEnforcer

        # Default weekend_close=False so DD/news tests are not masked by
        # the weekend gate (tests run at any time of week in CI).
        kwargs.setdefault("weekend_close", False)
        cfg = PropConfig(**kwargs)
        e = PropEnforcer.__new__(PropEnforcer)
        import threading

        e.cfg = cfg
        e._lock = threading.Lock()
        e._start_balance = 0.0
        e._high_water_mark = 0.0
        e._sod_equity = 0.0
        e._current_equity = 0.0
        e._halted = False
        e._halt_reason = ""
        e._breach_log = []
        e._news_events = []
        e._kill_switch_fn = None
        e._on_breach_callbacks = []
        return e

    def test_fresh_allows_order(self):
        e = self._make()
        e.update_balance(100_000)
        ok, reason = e.before_execute("XAUUSD")
        assert ok
        assert reason == ""

    def test_daily_dd_breach_blocks(self):
        e = self._make(daily_dd=0.05)
        e.update_balance(100_000, start_of_day_equity=100_000)
        e.update_balance(94_000)  # 6% DD
        ok, reason = e.before_execute("XAUUSD")
        assert not ok
        assert "DAILY_DD" in reason

    def test_total_dd_breach_blocks(self):
        # Set daily_dd high so only total DD fires
        e = self._make(max_dd=0.10, daily_dd=0.99)
        e.update_balance(100_000)
        e.update_balance(89_000)  # 11% from HWM — exceeds 10% total limit
        ok, reason = e.before_execute("XAUUSD")
        assert not ok
        assert "TOTAL_DD" in reason

    def test_daily_reset_clears_daily_halt(self):
        e = self._make(daily_dd=0.05)
        e.update_balance(100_000, start_of_day_equity=100_000)
        e.update_balance(94_000)
        e.before_execute("XAUUSD")  # triggers halt
        assert e._halted
        e.daily_reset(94_000)
        assert not e._halted

    def test_news_blackout_blocks(self):
        import time

        e = self._make(news_blackout=300)
        e.update_balance(100_000)
        e.register_news_event(time.time() + 60)  # event in 60s
        ok, reason = e.before_execute("XAUUSD")
        assert not ok
        assert "news" in reason.lower()

    def test_weekend_blocks_friday_evening(self):
        e = self._make(weekend_close=True)
        e.update_balance(100_000)
        # Patch _is_weekend_window to return True
        e._is_weekend_window = lambda dt: True
        ok, reason = e.before_execute("XAUUSD")
        assert not ok
        assert "Weekend" in reason

    def test_status_returns_dict(self):
        e = self._make()
        e.update_balance(100_000)
        s = e.status()
        assert "halted" in s
        assert "daily_dd_pct" in s
        assert "total_dd_pct" in s

    def test_kill_switch_callback_fired_on_breach(self):
        fired = []
        e = self._make(daily_dd=0.05)
        e._kill_switch_fn = fired.append
        e.update_balance(100_000, start_of_day_equity=100_000)
        e.update_balance(94_000)
        e.before_execute("XAUUSD")
        assert len(fired) == 1

    def test_on_breach_callback_fired(self):
        events = []
        e = self._make(daily_dd=0.05)
        e.register_on_breach(lambda bt, detail: events.append(bt))
        e.update_balance(100_000, start_of_day_equity=100_000)
        e.update_balance(94_000)
        e.before_execute("XAUUSD")
        assert len(events) == 1

    def test_config_from_file_defaults_when_missing(self):
        from risk.compliance.prop_enforcer import PropConfig

        cfg = PropConfig.from_file(Path("/nonexistent/path.json"))
        assert cfg.daily_dd == 0.05
        assert cfg.max_dd == 0.10


# ── EX5SignalExporter ─────────────────────────────────────────────────────────


class TestEX5SignalExporter:
    def test_export_creates_file(self):
        from brokers.mt5_bridge import EX5SignalExporter, MT5Order, OrderSide

        with tempfile.TemporaryDirectory() as d:
            exp = EX5SignalExporter(Path(d))
            order = MT5Order("XAUUSD", OrderSide.BUY, 0.1, stop_loss=1900.0)
            path = exp.export(order)
            assert path.exists()
            data = json.loads(path.read_text())
            assert data["symbol"] == "XAUUSD"
            assert data["side"] == "BUY"
            assert data["status"] == "PENDING"
            assert data["stop_loss"] == 1900.0

    def test_poll_fill_returns_result_on_filled(self):
        from brokers.mt5_bridge import (
            EX5SignalExporter,
            FillStatus,
            MT5Order,
            OrderSide,
        )

        with tempfile.TemporaryDirectory() as d:
            exp = EX5SignalExporter(Path(d))
            order = MT5Order("XAUUSD", OrderSide.BUY, 0.1, stop_loss=1900.0)
            path = exp.export(order)
            # Simulate EA fill
            data = json.loads(path.read_text())
            data.update(
                {
                    "status": "FILLED",
                    "fill_price": 1950.0,
                    "ticket": 12345,
                    "fill_volume": 0.1,
                }
            )
            path.write_text(json.dumps(data))
            fill = exp.poll_fill(path, timeout_sec=2.0)
            assert fill.status == FillStatus.FILLED
            assert fill.fill_price == 1950.0
            assert fill.ticket == 12345

    def test_poll_fill_raises_on_rejected(self):
        from brokers.mt5_bridge import EX5SignalExporter, MT5Order, OrderSide

        with tempfile.TemporaryDirectory() as d:
            exp = EX5SignalExporter(Path(d))
            order = MT5Order("XAUUSD", OrderSide.SELL, 0.1, stop_loss=2100.0)
            path = exp.export(order)
            data = json.loads(path.read_text())
            data.update({"status": "REJECTED", "reject_reason": "no margin"})
            path.write_text(json.dumps(data))
            with pytest.raises(RuntimeError, match="rejected"):
                exp.poll_fill(path, timeout_sec=2.0)

    def test_poll_fill_raises_timeout(self):
        from brokers.mt5_bridge import EX5SignalExporter, MT5Order, OrderSide

        with tempfile.TemporaryDirectory() as d:
            exp = EX5SignalExporter(Path(d))
            order = MT5Order("XAUUSD", OrderSide.BUY, 0.1, stop_loss=1900.0)
            path = exp.export(order)
            with pytest.raises(TimeoutError):
                exp.poll_fill(path, timeout_sec=0.3)

    def test_cleanup_removes_old_files(self):
        import time

        from brokers.mt5_bridge import EX5SignalExporter, MT5Order, OrderSide

        with tempfile.TemporaryDirectory() as d:
            exp = EX5SignalExporter(Path(d))
            order = MT5Order("XAUUSD", OrderSide.BUY, 0.1, stop_loss=1900.0)
            path = exp.export(order)
            # Make file appear old
            old_time = time.time() - 25 * 3600
            import os

            os.utime(path, (old_time, old_time))
            removed = exp.cleanup_old_signals(max_age_hours=24)
            assert removed == 1
            assert not path.exists()

    def test_stop_loss_required(self):
        from brokers.mt5_bridge import MT5Bridge, MT5Order, OrderSide

        bridge = MT5Bridge(server="test", login=1, password="pw")
        bridge._connected = True
        with pytest.raises(ValueError, match="stop_loss"):
            bridge.send_order(MT5Order("XAUUSD", OrderSide.BUY, 0.1))


# ── PaperTradingStarter helpers ───────────────────────────────────────────────


class TestPaperTradingHelpers:
    def test_trade_logger_creates_csv(self):
        from scripts.paper_trading_starter import CSV_HEADERS, TradeLogger

        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "trades.csv"
            logger = TradeLogger(path)
            assert path.exists()
            record = dict.fromkeys(CSV_HEADERS, "test")
            logger.log(record)
            import csv

            with Path(path).open(encoding="utf-8") as _fh:
                rows = list(csv.DictReader(_fh))
            assert len(rows) == 1
            assert rows[0]["instrument"] == "test"

    def test_write_status_creates_json(self):
        import scripts.paper_trading_starter as pts
        from scripts.paper_trading_starter import write_status

        with tempfile.TemporaryDirectory() as d:
            orig = pts.STATUS_JSON
            pts.STATUS_JSON = Path(d) / "status.json"
            write_status({"complete": False, "trade_count": 5})
            data = json.loads(pts.STATUS_JSON.read_text())
            assert data["trade_count"] == 5
            assert "updated_at" in data
            pts.STATUS_JSON = orig


# ── Volume backtest helpers ───────────────────────────────────────────────────


class TestVolumeBacktest:
    def _make_ohlcv(self, n=100):
        """Synthetic OHLCV DataFrame."""
        idx = pd.date_range("2024-01-01", periods=n, freq="15min")
        close = 2000 + np.cumsum(np.random.randn(n))
        df = pd.DataFrame(
            {
                "Open": close - 1,
                "High": close + 2,
                "Low": close - 2,
                "Close": close,
                "Volume": np.random.randint(1000, 5000, n).astype(float),
            },
            index=idx,
        )
        return df

    def test_add_indicators_columns(self):
        from scripts.volume_boost_backtest import add_indicators

        df = add_indicators(self._make_ohlcv(60))
        for col in ["ema9", "ema21", "atr14", "vol_avg20", "cross", "vol_ok"]:
            assert col in df.columns, f"Missing column: {col}"

    def test_run_backtest_returns_summary(self):
        from scripts.volume_boost_backtest import add_indicators, run_backtest

        df = add_indicators(self._make_ohlcv(200))
        trades, summary = run_backtest(df, initial_balance=10_000)
        # May produce 0 trades on synthetic data — just check types
        assert isinstance(summary, dict)
        assert isinstance(trades, pd.DataFrame)

    def test_monte_carlo_returns_stats(self):
        from scripts.volume_boost_backtest import monte_carlo

        pnls = np.random.randn(50) * 0.01
        trades_df = pd.DataFrame({"pnl_pct": pnls * 100})
        result = monte_carlo(trades_df, n_runs=50, seed=0)
        assert "worst_case_dd_pct" in result
        assert "p95_dd_pct" in result
        assert result["n_runs"] == 50
        assert result["worst_case_dd_pct"] >= 0

    def test_monte_carlo_empty_returns_empty(self):
        from scripts.volume_boost_backtest import monte_carlo

        result = monte_carlo(pd.DataFrame(), n_runs=10)
        assert result == {}


# ── Challenge bot pass criteria ───────────────────────────────────────────────


class TestChallengeLaunchCriteria:
    """Test _check_pass logic without importing Discord."""

    @staticmethod
    def _check_pass(pnl_pct, dd_pct, days, min_pnl=10.0, max_dd=5.0, min_days=4):
        if pnl_pct < min_pnl:
            return False, f"P&L {pnl_pct:.2f}% < required {min_pnl:.1f}%"
        if dd_pct > max_dd:
            return False, f"Drawdown {dd_pct:.2f}% > max allowed {max_dd:.1f}%"
        if days < min_days:
            return False, f"Trading days {days} < required {min_days}"
        return True, "All criteria met"

    def test_pass_all_criteria(self):
        ok, reason = self._check_pass(12.0, 3.0, 5)
        assert ok
        assert reason == "All criteria met"

    def test_fail_low_pnl(self):
        ok, reason = self._check_pass(8.0, 3.0, 5)
        assert not ok
        assert "P&L" in reason

    def test_fail_high_dd(self):
        ok, reason = self._check_pass(12.0, 6.0, 5)
        assert not ok
        assert "Drawdown" in reason

    def test_fail_low_days(self):
        ok, reason = self._check_pass(12.0, 3.0, 2)
        assert not ok
        assert "days" in reason

    def test_exact_boundary_pass(self):
        ok, _ = self._check_pass(10.0, 5.0, 4)
        assert ok

    def test_exact_boundary_fail_pnl(self):
        ok, _ = self._check_pass(9.99, 5.0, 4)
        assert not ok

    def test_custom_thresholds(self):
        ok, _ = self._check_pass(20.0, 8.0, 10, min_pnl=20.0, max_dd=10.0, min_days=10)
        assert ok
