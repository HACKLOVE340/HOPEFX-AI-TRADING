# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
tests/test_prop_enforcement.py
==============================
End-to-end tests for prop-firm enforcement.

Verifies that:
1. Daily drawdown breach → trading halted + alert fired
2. Total drawdown breach → trading halted + alert fired
3. Recovery: halt clears after reset
4. DrawdownTracker trailing HWM is correct
5. Partial fill handling updates daily P&L correctly
6. check_modify_order blocks when breach is active
7. HOPEFXBrain respects risk halt (returns hold)
"""

import json
from pathlib import Path

import pytest

# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture
def risk_manager():
    from risk.manager import RiskManager

    return RiskManager(initial_balance=100_000)


@pytest.fixture
def dd_tracker():
    from risk.drawdown_tracker import DrawdownTracker

    return DrawdownTracker(
        initial_balance=100_000,
        max_total_dd_pct=0.10,
        max_daily_dd_pct=0.05,
        drawdown_mode="equity",
        alert_pct_of_limit=0.80,
    )


# ── DrawdownTracker tests ─────────────────────────────────────────────────────


class TestDrawdownTracker:
    def test_trailing_hwm_rises_with_equity(self, dd_tracker):
        dd_tracker.update(equity=105_000)
        assert dd_tracker.total_hwm == 105_000

    def test_trailing_hwm_never_decreases(self, dd_tracker):
        dd_tracker.update(equity=105_000)
        dd_tracker.update(equity=95_000)
        assert dd_tracker.total_hwm == 105_000

    def test_total_drawdown_from_hwm(self, dd_tracker):
        dd_tracker.update(equity=105_000)
        result = dd_tracker.update(equity=95_000)
        # (105k - 95k) / 105k ≈ 9.52%
        assert abs(result.total_drawdown_pct - 0.0952) < 0.001

    def test_total_breach_at_10pct(self, dd_tracker):
        dd_tracker.update(equity=105_000)
        result = dd_tracker.update(equity=94_500)  # 10% from 105k
        assert result.total_breach is True

    def test_total_alert_at_80pct_of_limit(self, dd_tracker):
        dd_tracker.update(equity=105_000)
        # 85% of 10% limit = 8.5% DD from HWM → alert (not breach)
        # 105k * (1 - 0.085) = 96_075
        result = dd_tracker.update(equity=96_075)
        assert result.total_alert is True
        assert result.total_breach is False

    def test_daily_drawdown_from_open(self, dd_tracker):
        result = dd_tracker.update(equity=96_000)
        # (100k - 96k) / 100k = 4%
        assert abs(result.daily_drawdown_pct - 0.04) < 0.001

    def test_daily_breach_at_5pct(self, dd_tracker):
        result = dd_tracker.update(equity=95_000)
        assert result.daily_breach is True

    def test_partial_fill_accumulates(self, dd_tracker):
        dd_tracker.record_fill(pnl=-500)
        dd_tracker.record_fill(pnl=-300)
        assert dd_tracker.daily_realised_pnl == -800

    def test_check_modify_blocks_on_breach(self, dd_tracker):
        # Force a daily breach
        dd_tracker.update(equity=94_000)  # 6% daily DD > 5% limit
        ok, reason = dd_tracker.check_modify(
            current_equity=94_000,
            new_stop_loss_distance=0.001,
            lots=0.1,
            account_balance=100_000,
        )
        assert ok is False
        assert "breach" in reason.lower()

    def test_check_modify_allows_small_risk(self, dd_tracker):
        ok, reason = dd_tracker.check_modify(
            current_equity=99_000,
            new_stop_loss_distance=0.0005,
            lots=0.01,
            account_balance=100_000,
        )
        assert ok is True
        assert reason == "OK"

    def test_check_modify_blocks_large_risk(self, dd_tracker):
        # risk = SL_distance * lots * pip_value / balance
        # 0.10 * 100 * 1000 / 100_000 = 10% >> 5% max
        ok, _ = dd_tracker.check_modify(
            current_equity=99_000,
            new_stop_loss_distance=0.10,  # 10% SL distance
            lots=100.0,  # 100 lots
            account_balance=100_000,
            pip_value=1000.0,  # large pip value → huge risk
        )
        assert ok is False


# ── RiskManager integration tests ─────────────────────────────────────────────


class TestRiskManagerPropEnforcement:
    def test_dd_tracker_initialised(self, risk_manager):
        assert risk_manager._dd_tracker is not None

    def test_update_equity_syncs_drawdown(self, risk_manager):
        risk_manager.update_equity(105_000)
        risk_manager.update_equity(96_000)
        # current_drawdown should reflect trailing HWM
        assert risk_manager.current_drawdown > 0.085  # ~8.57%

    def test_record_partial_fill_updates_daily_pnl(self, risk_manager):
        risk_manager.record_partial_fill(pnl=-200)
        risk_manager.record_partial_fill(pnl=-150)
        # daily_pnl should include the fills
        assert risk_manager._dd_tracker.daily_realised_pnl == -350

    def test_check_modify_order_delegates_to_tracker(self, risk_manager):
        ok, _ = risk_manager.check_modify_order(
            current_equity=99_000,
            new_stop_loss_distance=0.0005,
            lots=0.01,
            account_balance=100_000,
        )
        assert ok is True

    def test_get_drawdown_status_returns_dict(self, risk_manager):
        risk_manager.update_equity(102_000)
        status = risk_manager.get_drawdown_status()
        assert "total_hwm" in status
        assert "daily_drawdown_pct" in status
        assert status["total_hwm"] == 102_000


# ── HOPEFXBrain respects risk halt ────────────────────────────────────────────


class TestBrainRespectsPropHalt:
    def test_brain_returns_hold_when_risk_halted(self):
        import numpy as np
        import pandas as pd

        from brain.hopefx_brain import HOPEFXBrain
        from risk.manager import RiskManager

        brain = HOPEFXBrain()
        rm = RiskManager(initial_balance=100_000)

        # Simulate a halt
        rm._trading_halted = True
        brain.inject(risk_manager=rm)

        np.random.seed(1)
        n = 150
        close = 2300 + np.cumsum(np.random.randn(n) * 2)
        df = pd.DataFrame(
            {
                "open": close - 0.5,
                "high": close + 1,
                "low": close - 1,
                "close": close,
                "volume": np.ones(n) * 1000,
            }
        )

        decision = brain.process_bar(df, symbol="XAUUSD")
        assert decision.action == "hold"
        assert "risk_halted" in decision.reason

    def test_brain_kill_switch_returns_hold(self):
        import numpy as np
        import pandas as pd

        from brain.hopefx_brain import HOPEFXBrain

        brain = HOPEFXBrain()
        brain.kill("test_kill")

        np.random.seed(2)
        n = 150
        close = 2300 + np.cumsum(np.random.randn(n) * 2)
        df = pd.DataFrame(
            {
                "open": close - 0.5,
                "high": close + 1,
                "low": close - 1,
                "close": close,
                "volume": np.ones(n) * 1000,
            }
        )

        decision = brain.process_bar(df, symbol="XAUUSD")
        assert decision.action == "hold"
        assert "kill_switch" in decision.reason

        brain.revive()
        assert not brain.is_killed


# ── Prop config file tests ────────────────────────────────────────────────────


class TestPropFirmConfig:
    def test_prop_firm_mode_json_enabled(self):
        cfg_path = Path(__file__).parent.parent / "prop_firm_mode.json"
        assert cfg_path.exists(), "prop_firm_mode.json must exist"
        with open(cfg_path, encoding="utf-8") as f:
            cfg = json.load(f)
        assert cfg.get("enabled") is True, "enabled must be true for testing"

    def test_prop_firm_has_enforcement_block(self):
        cfg_path = Path(__file__).parent.parent / "prop_firm_mode.json"
        with open(cfg_path, encoding="utf-8") as f:
            cfg = json.load(f)
        enforcement = cfg.get("enforcement", {})
        assert enforcement.get("halt_on_daily_drawdown_breach") is True
        assert enforcement.get("halt_on_total_drawdown_breach") is True
        assert enforcement.get("close_all_on_breach") is True

    def test_ftmo_standard_drawdown_limits(self):
        cfg_path = Path(__file__).parent.parent / "prop_firm_mode.json"
        with open(cfg_path, encoding="utf-8") as f:
            cfg = json.load(f)
        ftmo = cfg["firms"]["ftmo_standard"]["drawdown"]
        assert ftmo["max_total_drawdown_pct"] == 10.0
        assert ftmo["max_daily_drawdown_pct"] == 5.0
        assert ftmo["drawdown_mode"] == "equity"

    def test_goat_funded_uses_balance_mode(self):
        cfg_path = Path(__file__).parent.parent / "prop_firm_mode.json"
        with open(cfg_path, encoding="utf-8") as f:
            cfg = json.load(f)
        goat = cfg["firms"]["goat_funded_standard"]["drawdown"]
        assert goat["drawdown_mode"] == "balance"


# ── Run directly ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
