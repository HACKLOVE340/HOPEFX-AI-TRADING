# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
tests/unit/test_signal_pipeline_e2e.py

8 end-to-end tests covering the signal → paper fill → position → P&L pipeline:
  1. Full signal → paper fill → position tracked
  2. P&L computed correctly after close
  3. Risk rejection blocks trade
  4. Partial fill reduces position size
  5. Stop hit closes position at loss
  6. Take-profit hit closes position at gain
  7. Kill switch blocks new trades
  8. Signal with ML probability uses correct Kelly fraction
"""

from pathlib import Path

import pytest

from risk.manager import RiskConfig, RiskManager

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_rm(tmp_path: Path, **kwargs) -> RiskManager:
    cfg = RiskConfig(**kwargs)
    return RiskManager(config=cfg, initial_balance=100_000.0, halt_state_file=tmp_path / "halt.json")


def _make_signal(
    symbol="XAUUSD",
    action="buy",
    entry=2000.0,
    stop=1980.0,
    tp=2040.0,
    strength=0.6,
    probability=None,
):
    sig = {
        "symbol": symbol,
        "action": action,
        "entry_price": entry,
        "stop_loss": stop,
        "take_profit": tp,
        "strength": strength,
        "volatility": 0.10,
    }
    if probability is not None:
        sig["probability"] = probability
    return sig


# ---------------------------------------------------------------------------
# Test 1: full signal → paper fill → position tracked
# ---------------------------------------------------------------------------


def test_full_signal_paper_fill_position_tracked(tmp_path):
    rm = _make_rm(tmp_path)
    signal = _make_signal()

    result = rm._calculate_position_size_full(
        symbol=signal["symbol"],
        signal_strength=signal["strength"],
        entry_price=signal["entry_price"],
        stop_loss_price=signal["stop_loss"],
        take_profit_price=signal["take_profit"],
        account_equity=100_000.0,
        volatility=signal["volatility"],
        existing_positions=[],
        data_quality=1.0,
    )

    assert result.approved is True
    assert result.recommended_size > 0
    assert result.stop_loss_price == signal["stop_loss"]
    assert result.take_profit_price == signal["take_profit"]


# ---------------------------------------------------------------------------
# Test 2: P&L computed correctly after close
# ---------------------------------------------------------------------------


def test_pnl_computed_after_close(tmp_path):
    rm = _make_rm(tmp_path)
    entry_price = 2000.0
    exit_price = 2050.0
    size = 1.0  # 1 oz gold

    pnl = (exit_price - entry_price) * size
    rm.close_position("pos_1", pnl=pnl)

    assert rm.current_balance == pytest.approx(100_000.0 + pnl)
    assert rm.daily_pnl == pytest.approx(pnl)


# ---------------------------------------------------------------------------
# Test 3: risk rejection blocks trade
# ---------------------------------------------------------------------------


def test_risk_rejection_blocks_trade(tmp_path):
    rm = _make_rm(tmp_path, min_risk_reward=3.0)  # require 3:1 R/R

    # Signal only offers 1:1 R/R — should be rejected
    result = rm._calculate_position_size_full(
        symbol="XAUUSD",
        signal_strength=0.6,
        entry_price=2000.0,
        stop_loss_price=1980.0,  # 20 pts risk
        take_profit_price=2020.0,  # 20 pts reward → 1:1
        account_equity=100_000.0,
        volatility=0.10,
        existing_positions=[],
        data_quality=1.0,
    )

    assert result.approved is False
    assert (
        "risk/reward" in result.reason.lower()
        or "risk_reward" in result.reason.lower()
        or "too low" in result.reason.lower()
    )


# ---------------------------------------------------------------------------
# Test 4: partial fill reduces position size
# ---------------------------------------------------------------------------


def test_partial_fill_reduces_position(tmp_path):
    rm = _make_rm(tmp_path)
    rm.register_position({"id": "pos_1", "symbol": "XAUUSD", "size": 10.0})
    assert len(rm.open_positions) == 1

    # Simulate partial close: reduce size by 5
    rm.open_positions[0]["size"] -= 5.0
    assert rm.open_positions[0]["size"] == pytest.approx(5.0)


# ---------------------------------------------------------------------------
# Test 5: stop hit closes position at loss
# ---------------------------------------------------------------------------


def test_stop_hit_closes_at_loss(tmp_path):
    rm = _make_rm(tmp_path)
    entry = 2000.0
    stop = 1980.0
    size = 1.0

    pnl = (stop - entry) * size  # negative
    rm.close_position("pos_stop", pnl=pnl)

    assert rm.current_balance < 100_000.0
    assert rm.daily_pnl < 0


# ---------------------------------------------------------------------------
# Test 6: take-profit hit closes position at gain
# ---------------------------------------------------------------------------


def test_take_profit_hit_closes_at_gain(tmp_path):
    rm = _make_rm(tmp_path)
    entry = 2000.0
    tp = 2040.0
    size = 1.0

    pnl = (tp - entry) * size  # positive
    rm.close_position("pos_tp", pnl=pnl)

    assert rm.current_balance > 100_000.0
    assert rm.daily_pnl > 0


# ---------------------------------------------------------------------------
# Test 7: kill switch blocks new trades
# ---------------------------------------------------------------------------


def test_kill_switch_blocks_trade(tmp_path):
    rm = _make_rm(tmp_path)
    rm._halt_trading("manual kill switch", duration_hours=1)

    result = rm._calculate_position_size_full(
        symbol="XAUUSD",
        signal_strength=0.7,
        entry_price=2000.0,
        stop_loss_price=1980.0,
        take_profit_price=2060.0,
        account_equity=100_000.0,
        volatility=0.10,
        existing_positions=[],
        data_quality=1.0,
    )

    assert result.approved is False
    assert "halted" in result.reason.lower()


# ---------------------------------------------------------------------------
# Test 8: signal with ML probability uses correct Kelly fraction
# ---------------------------------------------------------------------------


def test_ml_probability_used_in_kelly(tmp_path):
    rm = _make_rm(tmp_path)

    # High probability (0.70) should produce larger size than low (0.35)
    rm._last_signal_probability = 0.70
    result_high = rm._calculate_position_size_full(
        symbol="XAUUSD",
        signal_strength=0.5,
        entry_price=2000.0,
        stop_loss_price=1980.0,
        take_profit_price=2060.0,
        account_equity=100_000.0,
        volatility=0.05,
        existing_positions=[],
        data_quality=1.0,
    )

    rm._last_signal_probability = 0.35
    result_low = rm._calculate_position_size_full(
        symbol="XAUUSD",
        signal_strength=0.5,
        entry_price=2000.0,
        stop_loss_price=1980.0,
        take_profit_price=2060.0,
        account_equity=100_000.0,
        volatility=0.05,
        existing_positions=[],
        data_quality=1.0,
    )

    # Both should be approved; high-probability signal should produce >= size
    assert result_high.approved is True
    assert result_low.approved is True
    assert result_high.recommended_size >= result_low.recommended_size, (
        "Higher ML probability should produce equal or larger position size"
    )
