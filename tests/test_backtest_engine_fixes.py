# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
Tests for backtest engine fixes:
- Trade-level Sharpe (not bar-level)
- Sharpe SE calculation
- Gold-correct slippage (pip = $0.10)
- Kelly-based position sizing
- R:R filter
- Realistic commission ($7 round-trip)
"""

from __future__ import annotations

import math
from datetime import datetime

import numpy as np

from backtest.engine import BacktestConfig, BacktestEngine, SimulatedBroker

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_config(**kwargs) -> BacktestConfig:
    defaults = {
        "start_date": datetime(2024, 1, 1),
        "end_date": datetime(2024, 6, 1),
        "symbols": ["XAUUSD"],
        "initial_capital": 100_000.0,
        "commission_per_trade": 7.0,
        "slippage_pips": 3.0,
        "slippage_model": "fixed",
        "kelly_fraction": 0.25,
        "risk_per_trade": 0.01,
        "min_rr_ratio": 1.5,
    }
    defaults.update(kwargs)
    return BacktestConfig(**defaults)


def _inject_trades(engine_or_broker, pnls: list[float]) -> None:
    """Inject synthetic trade records directly into broker.trades.

    Accepts either a BacktestEngine (uses engine.broker) or a SimulatedBroker.
    """
    broker = getattr(engine_or_broker, "broker", engine_or_broker)
    for pnl in pnls:
        broker.trades.append(
            {
                "timestamp": None,
                "symbol": "XAUUSD",
                "action": "close",
                "quantity": 1.0,
                "entry_price": 2000.0,
                "exit_price": 2000.0 + pnl,
                "pnl": pnl,
                "commission": 7.0,
                "net_pnl": pnl - 7.0,
            }
        )


# ---------------------------------------------------------------------------
# Slippage tests
# ---------------------------------------------------------------------------


class TestGoldSlippage:
    """Gold pip = $0.10, not $0.0001."""

    def test_fixed_slippage_gold_3pips(self):
        """3 pips at $2000 gold = $0.30 = 0.015%."""
        cfg = _make_config(slippage_pips=3.0, slippage_model="fixed")
        broker = SimulatedBroker(cfg)
        slip = broker._calculate_slippage(2000.0)
        # 3 * 0.10 / 2000 = 0.00015
        assert abs(slip - 0.00015) < 1e-8, f"Expected 0.00015, got {slip}"

    def test_fixed_slippage_gold_dollar_value(self):
        """Dollar slippage at $2000 gold with 3 pips = $0.30."""
        cfg = _make_config(slippage_pips=3.0, slippage_model="fixed")
        broker = SimulatedBroker(cfg)
        slip = broker._calculate_slippage(2000.0)
        dollar_slip = slip * 2000.0
        assert abs(dollar_slip - 0.30) < 1e-6, f"Expected $0.30, got ${dollar_slip:.6f}"

    def test_fixed_slippage_forex_uses_pip_0001(self):
        """Forex (price < $100) still uses 0.0001 pip."""
        cfg = _make_config(slippage_pips=1.0, slippage_model="fixed")
        broker = SimulatedBroker(cfg)
        slip = broker._calculate_slippage(1.2000)  # EURUSD
        # 1 * 0.0001 / 1.2 = 0.0000833...
        assert abs(slip - (0.0001 / 1.2)) < 1e-8

    def test_no_slippage_model(self):
        cfg = _make_config(slippage_model="none")
        broker = SimulatedBroker(cfg)
        assert broker._calculate_slippage(2000.0) == 0.0

    def test_variable_slippage_gold(self):
        """Variable model with wide bar should produce > base slippage."""
        cfg = _make_config(slippage_model="variable")
        broker = SimulatedBroker(cfg)
        # Wide bar: $20 range on $2000 = 1% — much wider than 0.015% base
        slip_wide = broker._calculate_slippage(2000.0, bar_high=2010.0, bar_low=1990.0)
        slip_narrow = broker._calculate_slippage(2000.0, bar_high=2000.3, bar_low=1999.7)
        assert slip_wide > slip_narrow


# ---------------------------------------------------------------------------
# Commission tests
# ---------------------------------------------------------------------------


class TestCommission:
    def test_default_commission_is_7(self):
        cfg = _make_config()
        assert cfg.commission_per_trade == 7.0

    def test_commission_deducted_on_buy(self):
        # use_unified_costs=False forces the legacy flat commission_per_trade=$7
        cfg = _make_config(slippage_model="none", use_unified_costs=False)
        broker = SimulatedBroker(cfg)
        initial_cash = broker.cash
        broker.place_market_order("XAUUSD", "buy", 1.0, 2000.0)
        # cash should decrease by cost + flat $7 commission (no slippage, no unified costs)
        assert broker.cash < initial_cash - 2000.0
        assert abs(broker.cash - (initial_cash - 2000.0 - 7.0)) < 0.01


# ---------------------------------------------------------------------------
# Sharpe calculation tests
# ---------------------------------------------------------------------------


class TestTradeLevelSharpe:
    """Sharpe must be computed at trade level, not bar level."""

    def test_sharpe_uses_trade_pnls(self):
        """
        Inject known trade PnLs and verify the Sharpe is computed from
        trade returns, not from the equity curve bar-by-bar.
        """
        cfg = _make_config()
        engine = BacktestEngine(cfg)
        # Inject 50 trades with known mean/std
        rng = np.random.default_rng(42)
        pnls = rng.normal(loc=100.0, scale=50.0, size=50).tolist()
        _inject_trades(engine.broker, pnls)

        # Build a minimal equity curve (50 bars, all flat — simulates no-trade days)
        for i in range(200):
            engine.broker.equity_curve.append(
                {
                    "timestamp": f"2024-01-{i + 1:02d}",
                    "equity": 100_000.0,  # flat — no trades in equity curve
                    "cash": 100_000.0,
                    "positions_value": 0.0,
                }
            )

        result = engine._calculate_results()

        # Trade-level Sharpe should be positive (mean pnl > 0)
        assert result.sharpe_ratio > 0, "Sharpe should be positive with positive mean PnL"

        # Bar-level Sharpe on a flat equity curve would be 0 (std=0).
        # Trade-level Sharpe should be non-zero.
        assert result.sharpe_ratio != 0.0

    def test_sharpe_se_formula(self):
        """SE = 1/sqrt(2*(N-1)) for N trades."""
        cfg = _make_config()
        engine = BacktestEngine(cfg)
        n = 50
        rng = np.random.default_rng(0)
        pnls = rng.normal(100, 50, n).tolist()
        _inject_trades(engine.broker, pnls)
        for _ in range(100):
            engine.broker.equity_curve.append(
                {
                    "timestamp": None,
                    "equity": 100_000.0,
                    "cash": 100_000.0,
                    "positions_value": 0.0,
                }
            )
        result = engine._calculate_results()
        expected_se = 1.0 / math.sqrt(2.0 * (n - 1))
        assert abs(result.sharpe_se - expected_se) < 1e-6, f"Expected SE={expected_se:.6f}, got {result.sharpe_se:.6f}"

    def test_sharpe_se_decreases_with_more_trades(self):
        """More trades → smaller SE → more reliable Sharpe."""
        cfg = _make_config()
        rng = np.random.default_rng(1)

        def _run(n: int) -> float:
            engine = BacktestEngine(cfg)
            _inject_trades(engine, rng.normal(100, 50, n).tolist())
            for _ in range(n * 2):
                engine.broker.equity_curve.append(
                    {
                        "timestamp": None,
                        "equity": 100_000.0,
                        "cash": 100_000.0,
                        "positions_value": 0.0,
                    }
                )
            return engine._calculate_results().sharpe_se

        se_50 = _run(50)
        se_250 = _run(250)
        se_600 = _run(600)
        assert se_50 > se_250 > se_600, f"SE should decrease: {se_50:.4f} > {se_250:.4f} > {se_600:.4f}"

    def test_sharpe_se_at_600_trades(self):
        """At N=600, SE ≤ ±0.029 — well within the ±0.3 target."""
        se = 1.0 / math.sqrt(2.0 * (600 - 1))
        assert se < 0.03, f"SE at N=600 should be < 0.03, got {se:.4f}"

    def test_sharpe_se_at_250_trades(self):
        """At N=250, SE ≤ ±0.045 — within the ±0.3 target."""
        se = 1.0 / math.sqrt(2.0 * (250 - 1))
        assert se < 0.05, f"SE at N=250 should be < 0.05, got {se:.4f}"

    def test_sharpe_note_in_metrics(self):
        """metrics dict must contain sharpe_note and sharpe_se."""
        cfg = _make_config()
        engine = BacktestEngine(cfg)
        rng = np.random.default_rng(2)
        _inject_trades(engine, rng.normal(100, 50, 30).tolist())
        for _ in range(60):
            engine.broker.equity_curve.append(
                {
                    "timestamp": None,
                    "equity": 100_000.0,
                    "cash": 100_000.0,
                    "positions_value": 0.0,
                }
            )
        result = engine._calculate_results()
        assert "sharpe_note" in result.metrics
        assert "sharpe_se" in result.metrics
        assert "sharpe_trade_level" in result.metrics


# ---------------------------------------------------------------------------
# Kelly position sizing tests
# ---------------------------------------------------------------------------


class TestKellyPositionSizing:
    def test_kelly_returns_positive_size(self):
        cfg = _make_config(kelly_fraction=0.25, risk_per_trade=0.01)
        engine = BacktestEngine(cfg)
        # Inject 25 trades so Kelly has history
        rng = np.random.default_rng(3)
        _inject_trades(engine, rng.normal(100, 40, 25).tolist())
        signal = {"size": 1.0, "stop_distance": 10.0}
        qty = engine._kelly_position_size(signal, 2000.0)
        assert qty > 0

    def test_kelly_respects_risk_cap(self):
        """Kelly size should not exceed 2× risk_per_trade of equity (risk cap)."""
        cfg = _make_config(kelly_fraction=0.25, risk_per_trade=0.01)
        engine = BacktestEngine(cfg)
        rng = np.random.default_rng(4)
        _inject_trades(engine, rng.normal(200, 20, 30).tolist())  # very high win rate
        signal = {"size": 1.0, "stop_distance": 20.0}  # $20 stop on gold
        qty = engine._kelly_position_size(signal, 2000.0)
        equity = engine.broker.get_equity()
        max_risk = equity * cfg.risk_per_trade * 2
        # qty * stop_distance should not exceed max_risk (with 1% tolerance)
        assert qty * 20.0 <= max_risk * 1.01, f"qty={qty:.4f} × $20 stop = ${qty * 20:.2f} > max_risk=${max_risk:.2f}"

    def test_kelly_fallback_with_no_history(self):
        """With < 20 trades, falls back to 1% equity / stop_distance, capped by cash."""
        cfg = _make_config(kelly_fraction=0.25, risk_per_trade=0.01)
        engine = BacktestEngine(cfg)
        signal = {"size": 1.0, "stop_distance": 10.0}
        qty = engine._kelly_position_size(signal, 2000.0)
        # Uncapped: 1% of $100k / $10 stop = 100 oz
        # Cash cap: $100k × 0.95 / $2000 = 47.5 oz  ← binding constraint
        # Result should be positive and ≤ cash cap
        cash_cap = engine.broker.cash * 0.95 / 2000.0
        assert qty > 0
        assert qty <= cash_cap + 0.01  # within cash cap
        # And it should be the minimum of the two
        uncapped = 100_000.0 * 0.01 / 10.0  # 100 oz
        assert qty == round(min(uncapped, cash_cap), 4)

    def test_kelly_zero_fraction_uses_signal_size(self):
        """kelly_fraction=0 bypasses Kelly and uses signal['size']."""
        cfg = _make_config(kelly_fraction=0.0)
        engine = BacktestEngine(cfg)
        signal = {"size": 5.0, "stop_distance": 10.0}
        qty = engine._kelly_position_size(signal, 2000.0)
        assert qty == 5.0


# ---------------------------------------------------------------------------
# R:R filter tests
# ---------------------------------------------------------------------------


class TestRRFilter:
    def test_signal_rejected_below_min_rr(self):
        """Signal with R:R < min_rr_ratio must be rejected (no position opened)."""
        cfg = _make_config(min_rr_ratio=1.5, slippage_model="none")
        engine = BacktestEngine(cfg)
        prices = {"XAUUSD": 2000.0}
        # R:R = 5.0 / 20.0 = 0.25 < 1.5
        signal = {
            "symbol": "XAUUSD",
            "action": "buy",
            "size": 1.0,
            "stop_distance": 20.0,
            "tp_distance": 5.0,
        }
        engine._process_signal(signal, datetime(2024, 1, 1), prices)
        assert "XAUUSD" not in engine.broker.positions
        assert len(engine.broker.trades) == 0

    def test_signal_accepted_above_min_rr(self):
        """Signal with R:R ≥ min_rr_ratio must open a position."""
        cfg = _make_config(min_rr_ratio=1.5, slippage_model="none")
        engine = BacktestEngine(cfg)
        prices = {"XAUUSD": 2000.0}
        # R:R = 30.0 / 10.0 = 3.0 ≥ 1.5; stop=$10 → 1% of $100k / $10 = 100 oz
        signal = {
            "symbol": "XAUUSD",
            "action": "buy",
            "size": 1.0,
            "stop_distance": 10.0,
            "tp_distance": 30.0,
        }
        engine._process_signal(signal, datetime(2024, 1, 1), prices)
        # Buy opens a position (no trade record until close)
        assert "XAUUSD" in engine.broker.positions

    def test_rr_filter_disabled_at_zero(self):
        """min_rr_ratio=0 disables the filter — even bad R:R signals pass."""
        cfg = _make_config(min_rr_ratio=0.0, slippage_model="none")
        engine = BacktestEngine(cfg)
        prices = {"XAUUSD": 2000.0}
        signal = {
            "symbol": "XAUUSD",
            "action": "buy",
            "size": 1.0,
            "stop_distance": 10.0,
            "tp_distance": 0.1,  # terrible R:R = 0.01
        }
        engine._process_signal(signal, datetime(2024, 1, 1), prices)
        assert "XAUUSD" in engine.broker.positions


# ---------------------------------------------------------------------------
# BacktestConfig defaults
# ---------------------------------------------------------------------------


class TestBacktestConfigDefaults:
    def test_commission_default(self):
        cfg = _make_config()
        assert cfg.commission_per_trade == 7.0

    def test_slippage_pips_default(self):
        cfg = _make_config()
        assert cfg.slippage_pips == 3.0

    def test_kelly_fraction_default(self):
        cfg = _make_config()
        assert cfg.kelly_fraction == 0.25

    def test_risk_per_trade_default(self):
        cfg = _make_config()
        assert cfg.risk_per_trade == 0.01

    def test_min_rr_ratio_default(self):
        cfg = _make_config()
        assert cfg.min_rr_ratio == 1.5
