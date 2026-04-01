# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
tests/test_cvar_order_gate.py
=============================
Verify that CVaR breaches block order submission in the place_order path,
not just inside assess_risk().

Uses RiskManager directly (no broker/DB required).
"""

from __future__ import annotations

import pytest
from risk.manager import RiskConfig, RiskManager


@pytest.fixture
def rm(tmp_path):
    cfg = RiskConfig(
        max_drawdown_pct=0.10,
        daily_loss_limit_pct=0.05,
    )
    manager = RiskManager(cfg, initial_balance=100_000.0, halt_state_file=tmp_path / "halt.json")
    # Set a tight CVaR daily limit so we can trigger it easily
    manager._cvar_daily_limit = 0.01  # 1% CVaR limit
    return manager


# ── check_cvar_pre_trade: insufficient history ────────────────────────────────


def test_cvar_allowed_when_insufficient_history(rm):
    """Fewer than 10 observations → gate passes (can't compute reliable CVaR)."""
    rm._returns_history.clear()
    for _ in range(5):
        rm._returns_history.append(-0.05)  # large losses, but only 5 obs

    allowed, reason = rm.check_cvar_pre_trade()
    assert allowed is True
    assert "Insufficient" in reason


# ── check_cvar_pre_trade: within limit ───────────────────────────────────────


def test_cvar_allowed_when_within_limit(rm):
    """Small losses → CVaR below limit → gate passes."""
    rm._returns_history.clear()
    for _ in range(30):
        rm._returns_history.append(-0.001)  # tiny losses

    allowed, reason = rm.check_cvar_pre_trade()
    assert allowed is True
    assert "CVaR=" in reason


# ── check_cvar_pre_trade: breach ─────────────────────────────────────────────


def test_cvar_blocked_when_limit_breached(rm):
    """Large tail losses → CVaR exceeds limit → gate blocks."""
    rm._returns_history.clear()
    # 30 observations with severe tail losses
    for _ in range(25):
        rm._returns_history.append(-0.001)
    for _ in range(5):
        rm._returns_history.append(-0.20)  # 20% loss days in the tail

    allowed, reason = rm.check_cvar_pre_trade()
    assert allowed is False
    assert "Pre-trade CVaR check failed" in reason
    assert "exceeds" in reason


# ── check_cvar_pre_trade: disabled ───────────────────────────────────────────


def test_cvar_gate_disabled_when_limit_zero(rm):
    """CVaR limit = 0 means disabled → always passes."""
    rm._cvar_daily_limit = 0.0
    rm._returns_history.clear()
    for _ in range(30):
        rm._returns_history.append(-0.50)  # catastrophic losses

    allowed, reason = rm.check_cvar_pre_trade()
    assert allowed is True
    assert "disabled" in reason.lower()


# ── check_cvar_pre_trade: trading halted ─────────────────────────────────────


def test_cvar_gate_blocked_when_trading_halted(rm):
    """If trading is already halted, CVaR gate must also block."""
    rm._trading_halted = True
    rm._halt_reason = "max drawdown reached"

    allowed, reason = rm.check_cvar_pre_trade()
    assert allowed is False
    assert "halted" in reason.lower()


# ── CVaR computation correctness ─────────────────────────────────────────────


def test_compute_cvar_value(rm):
    """CVaR at 95% confidence should equal mean of worst 5% of returns."""
    import numpy as np

    rm._returns_history.clear()
    returns = list(range(-100, 0))  # -100 to -1 (100 observations)
    returns_f = [r / 1000.0 for r in returns]  # -0.100 to -0.001
    for r in returns_f:
        rm._returns_history.append(r)

    cvar = rm._compute_cvar(confidence=0.95)
    # Worst 5% of 100 obs = bottom 5 values: -0.100, -0.099, -0.098, -0.097, -0.096
    expected = abs(np.mean([-0.100, -0.099, -0.098, -0.097, -0.096]))
    assert abs(cvar - expected) < 0.001, f"CVaR={cvar:.4f}, expected≈{expected:.4f}"


# ── Integration: assess_risk also blocks on CVaR ─────────────────────────────


def test_assess_risk_blocks_on_cvar_breach(rm):
    """assess_risk() must also return can_trade=False when CVaR is breached."""
    rm._returns_history.clear()
    for _ in range(25):
        rm._returns_history.append(-0.001)
    for _ in range(5):
        rm._returns_history.append(-0.20)

    account_info = {"equity": 100_000.0, "margin_used": 0.0}
    assessment = rm.assess_risk(account_info, [])

    assert assessment.can_trade is False
    assert any("CVaR" in m for m in assessment.messages)
