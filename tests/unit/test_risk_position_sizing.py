# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""Tests for risk/position_sizing.py — PositionSizer (atr, kelly, percent, fixed)."""

from __future__ import annotations

from decimal import Decimal


from risk.position_sizing import PositionSizer


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _Account:
    def __init__(self, equity=None, balance=None):
        self.equity = equity
        self.balance = balance


def _acct(equity=10_000.0, balance=None):
    return _Account(
        equity=Decimal(str(equity)) if equity is not None else None,
        balance=Decimal(str(balance)) if balance is not None else None,
    )


# ---------------------------------------------------------------------------
# Construction
# ---------------------------------------------------------------------------


class TestPositionSizerInit:
    def test_defaults(self):
        s = PositionSizer()
        assert s.method == "atr"
        assert s.risk_pct == Decimal("0.01")
        assert s.max_lots == Decimal("100")

    def test_custom_params(self):
        s = PositionSizer(method="kelly", risk_pct=0.02, max_lots=50.0)
        assert s.method == "kelly"
        assert s.risk_pct == Decimal("0.02")
        assert s.max_lots == Decimal("50")

    def test_method_lowercased(self):
        s = PositionSizer(method="ATR")
        assert s.method == "atr"


# ---------------------------------------------------------------------------
# ATR method
# ---------------------------------------------------------------------------


class TestATRMethod:
    def test_basic_calculation(self):
        # risk_amount = 10000 * 0.01 = 100; size = 100 / 2 = 50
        s = PositionSizer(method="atr", risk_pct=0.01, max_lots=100)
        size = s.calculate_size(_acct(10_000), entry_price=Decimal("1.2"), atr=Decimal("2"))
        assert size == Decimal("50")

    def test_zero_atr_returns_zero(self):
        # atr=Decimal("0") is falsy → defaults to Decimal(1) in calculate_size,
        # but _atr_size checks atr <= 0 and returns 0
        s = PositionSizer(method="atr", risk_pct=0.01, max_lots=100)
        # Pass atr explicitly via _atr_size path: atr=Decimal("0") is falsy,
        # so calculate_size uses atr or Decimal(1) = Decimal(1). Test _atr_size directly.
        result = s._atr_size(Decimal("10000"), Decimal("1.2"), Decimal("0"))
        assert result == Decimal("0")

    def test_zero_entry_price_returns_zero(self):
        s = PositionSizer(method="atr", risk_pct=0.01, max_lots=100)
        size = s.calculate_size(_acct(10_000), entry_price=Decimal("0"), atr=Decimal("1"))
        assert size == Decimal("0")

    def test_negative_atr_returns_zero(self):
        # Test _atr_size directly since calculate_size uses `atr or Decimal(1)`
        s = PositionSizer(method="atr", risk_pct=0.01, max_lots=100)
        result = s._atr_size(Decimal("10000"), Decimal("1.2"), Decimal("-1"))
        assert result == Decimal("0")

    def test_capped_at_max_lots(self):
        # risk_pct=0.5 → risk_amount=5000; atr=1 → size=5000, capped at 10
        s = PositionSizer(method="atr", risk_pct=0.5, max_lots=10)
        size = s.calculate_size(_acct(10_000), entry_price=Decimal("1.2"), atr=Decimal("1"))
        assert size == Decimal("10")

    def test_uses_equity_over_balance(self):
        # Account has both equity and balance; equity should be used
        acct = _Account(equity=Decimal("20000"), balance=Decimal("10000"))
        s = PositionSizer(method="atr", risk_pct=0.01, max_lots=100)
        size = s.calculate_size(acct, entry_price=Decimal("1.0"), atr=Decimal("2"))
        # risk_amount = 20000 * 0.01 = 200; size = 200 / 2 = 100
        assert size == Decimal("100")

    def test_falls_back_to_balance_when_no_equity(self):
        acct = _Account(equity=None, balance=Decimal("5000"))
        s = PositionSizer(method="atr", risk_pct=0.01, max_lots=100)
        size = s.calculate_size(acct, entry_price=Decimal("1.0"), atr=Decimal("1"))
        # risk_amount = 5000 * 0.01 = 50
        assert size == Decimal("50")

    def test_default_atr_of_one_when_none_passed(self):
        # atr=None → defaults to Decimal(1)
        s = PositionSizer(method="atr", risk_pct=0.01, max_lots=100)
        size = s.calculate_size(_acct(10_000), entry_price=Decimal("1.0"))
        # risk_amount = 100; atr=1 → size=100
        assert size == Decimal("100")


# ---------------------------------------------------------------------------
# Kelly method
# ---------------------------------------------------------------------------


class TestKellyMethod:
    def test_basic_calculation(self):
        # kelly = 0.6 - 0.4/2 = 0.4; half_kelly = 0.2
        # risk_amount = 10000 * 0.2 = 2000; entry=2 → size=1000, capped at 100
        s = PositionSizer(method="kelly", max_lots=100)
        size = s.calculate_size(_acct(10_000), entry_price=Decimal("2"), win_rate=0.6, payoff_ratio=2)
        assert size == Decimal("100")

    def test_zero_payoff_returns_zero(self):
        # payoff_ratio=0 is falsy → calculate_size uses `payoff_ratio or 1.0` = 1.0
        # Test _kelly_size directly for the zero-payoff guard
        s = PositionSizer(method="kelly", max_lots=100)
        result = s._kelly_size(Decimal("10000"), Decimal("1.2"), 0.6, 0)
        assert result == Decimal("0")

    def test_negative_payoff_returns_zero(self):
        # Test _kelly_size directly for negative payoff guard
        s = PositionSizer(method="kelly", max_lots=100)
        result = s._kelly_size(Decimal("10000"), Decimal("1.2"), 0.6, -1)
        assert result == Decimal("0")

    def test_zero_entry_price_returns_zero(self):
        s = PositionSizer(method="kelly", max_lots=100)
        size = s.calculate_size(_acct(10_000), entry_price=Decimal("0"), win_rate=0.6, payoff_ratio=2)
        assert size == Decimal("0")

    def test_negative_kelly_returns_zero(self):
        # win_rate=0.2, payoff=1 → kelly = 0.2 - 0.8/1 = -0.6 → half_kelly=0 → size=0
        s = PositionSizer(method="kelly", max_lots=100)
        size = s.calculate_size(_acct(10_000), entry_price=Decimal("1.0"), win_rate=0.2, payoff_ratio=1)
        assert size == Decimal("0")

    def test_defaults_win_rate_and_payoff_when_none(self):
        # win_rate=None → 0.5, payoff_ratio=None → 1.0
        # kelly = 0.5 - 0.5/1 = 0.0 → half_kelly=0 → size=0
        s = PositionSizer(method="kelly", max_lots=100)
        size = s.calculate_size(_acct(10_000), entry_price=Decimal("1.0"))
        assert size == Decimal("0")


# ---------------------------------------------------------------------------
# Percent method
# ---------------------------------------------------------------------------


class TestPercentMethod:
    def test_basic_calculation(self):
        # risk_amount = 10000 * 0.01 = 100; stop_distance=100 → size=1
        s = PositionSizer(method="percent", risk_pct=0.01, max_lots=100)
        size = s.calculate_size(_acct(10_000), entry_price=Decimal("2000"), stop_distance=Decimal("100"))
        assert size == Decimal("1")

    def test_zero_stop_distance_returns_zero(self):
        # stop_distance=Decimal("0") is falsy → calculate_size falls back to entry*0.01
        # Test _percent_size directly for the zero guard
        s = PositionSizer(method="percent", risk_pct=0.01, max_lots=100)
        result = s._percent_size(Decimal("10000"), Decimal("0"))
        assert result == Decimal("0")

    def test_negative_stop_distance_returns_zero(self):
        # Test _percent_size directly for negative stop guard
        s = PositionSizer(method="percent", risk_pct=0.01, max_lots=100)
        result = s._percent_size(Decimal("10000"), Decimal("-10"))
        assert result == Decimal("0")

    def test_default_stop_distance_from_entry(self):
        # stop_distance=None → entry_price * 0.01 = 2000 * 0.01 = 20
        # size = (10000 * 0.01) / 20 = 5
        s = PositionSizer(method="percent", risk_pct=0.01, max_lots=100)
        size = s.calculate_size(_acct(10_000), entry_price=Decimal("2000"))
        assert size == Decimal("5")

    def test_capped_at_max_lots(self):
        s = PositionSizer(method="percent", risk_pct=0.5, max_lots=5)
        size = s.calculate_size(_acct(10_000), entry_price=Decimal("100"), stop_distance=Decimal("1"))
        assert size == Decimal("5")


# ---------------------------------------------------------------------------
# Fixed method
# ---------------------------------------------------------------------------


class TestFixedMethod:
    def test_always_returns_one(self):
        s = PositionSizer(method="fixed", max_lots=100)
        size = s.calculate_size(_acct(10_000), entry_price=Decimal("1.0"))
        assert size == Decimal("1")

    def test_unknown_method_falls_through_to_fixed(self):
        s = PositionSizer(method="unknown_method", max_lots=100)
        size = s.calculate_size(_acct(10_000), entry_price=Decimal("1.0"))
        assert size == Decimal("1")

    def test_fixed_respects_max_lots_cap(self):
        # Fixed always returns 1, which is always <= max_lots
        s = PositionSizer(method="fixed", max_lots=0.5)
        size = s.calculate_size(_acct(10_000), entry_price=Decimal("1.0"))
        # min(1, 0.5) = 0.5
        assert size == Decimal("0.5")
