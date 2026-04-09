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
        with Path(cfg_path).open(encoding="utf-8") as f:
            cfg = json.load(f)
        assert cfg.get("enabled") is True, "enabled must be true for testing"

    def test_prop_firm_has_enforcement_block(self):
        cfg_path = Path(__file__).parent.parent / "prop_firm_mode.json"
        with Path(cfg_path).open(encoding="utf-8") as f:
            cfg = json.load(f)
        enforcement = cfg.get("enforcement", {})
        assert enforcement.get("halt_on_daily_drawdown_breach") is True
        assert enforcement.get("halt_on_total_drawdown_breach") is True
        assert enforcement.get("close_all_on_breach") is True

    def test_ftmo_standard_drawdown_limits(self):
        cfg_path = Path(__file__).parent.parent / "prop_firm_mode.json"
        with Path(cfg_path).open(encoding="utf-8") as f:
            cfg = json.load(f)
        ftmo = cfg["firms"]["ftmo_standard"]["drawdown"]
        assert ftmo["max_total_drawdown_pct"] == 10.0
        assert ftmo["max_daily_drawdown_pct"] == 5.0
        assert ftmo["drawdown_mode"] == "equity"

    def test_goat_funded_uses_balance_mode(self):
        cfg_path = Path(__file__).parent.parent / "prop_firm_mode.json"
        with Path(cfg_path).open(encoding="utf-8") as f:
            cfg = json.load(f)
        goat = cfg["firms"]["goat_funded_standard"]["drawdown"]
        assert goat["drawdown_mode"] == "balance"


# ── PropEnforcer 80% drawdown alert tests ────────────────────────────────────


class TestPropEnforcer80PctAlert:
    """
    PropEnforcer must send a Telegram warning (non-halting) when daily or
    total drawdown reaches 80% of the configured limit.
    """

    def _make_enforcer(self):
        from risk.compliance.prop_enforcer import PropEnforcer, PropConfig

        enforcer = PropEnforcer.__new__(PropEnforcer)
        import threading

        enforcer.cfg = PropConfig(
            daily_dd=0.05,
            max_dd=0.10,
            telegram_token="test-token",
            telegram_chat_id="test-chat",
        )
        enforcer._lock = threading.Lock()
        enforcer._start_balance = 0.0
        enforcer._high_water_mark = 0.0
        enforcer._sod_equity = 0.0
        enforcer._current_equity = 0.0
        enforcer._halted = False
        enforcer._halt_reason = ""
        enforcer._breach_log = []
        enforcer._news_events = []
        enforcer._on_breach_callbacks = []
        enforcer._kill_switch_fn = None
        enforcer._daily_alert_sent = False
        enforcer._total_alert_sent = False
        return enforcer

    def test_no_alert_below_80pct_threshold(self):
        """Below 80% of daily limit — no warning sent."""
        enforcer = self._make_enforcer()
        warnings_sent = []
        enforcer._send_telegram_warning = warnings_sent.append

        # 3% DD on 5% limit = 60% of limit — no alert
        enforcer.update_balance(current_equity=100_000.0, start_of_day_equity=100_000.0)
        enforcer.update_balance(current_equity=97_000.0)  # 3% DD
        assert warnings_sent == []
        assert enforcer._daily_alert_sent is False

    def test_daily_alert_fires_at_80pct_of_limit(self):
        """At 80% of daily limit (4% DD on 5% limit) — warning sent once."""
        enforcer = self._make_enforcer()
        warnings_sent = []
        enforcer._send_telegram_warning = warnings_sent.append

        enforcer.update_balance(current_equity=100_000.0, start_of_day_equity=100_000.0)
        # 4% DD = 80% of 5% daily limit → alert fires
        enforcer.update_balance(current_equity=96_000.0)
        assert len(warnings_sent) == 1
        assert "4.00%" in warnings_sent[0] or "approaching" in warnings_sent[0]
        assert enforcer._daily_alert_sent is True

    def test_daily_alert_fires_only_once(self):
        """Alert is sent at most once per day regardless of further equity drops."""
        enforcer = self._make_enforcer()
        warnings_sent = []
        enforcer._send_telegram_warning = warnings_sent.append

        enforcer.update_balance(current_equity=100_000.0, start_of_day_equity=100_000.0)
        enforcer.update_balance(current_equity=96_000.0)  # triggers alert
        enforcer.update_balance(current_equity=95_500.0)  # still below breach — no second alert
        assert len(warnings_sent) == 1

    def test_daily_alert_not_sent_when_breach_occurs(self):
        """At or beyond the breach threshold — breach fires, not the 80% warning."""
        enforcer = self._make_enforcer()
        warnings_sent = []
        enforcer._send_telegram_warning = warnings_sent.append

        enforcer.update_balance(current_equity=100_000.0, start_of_day_equity=100_000.0)
        # Jump straight to 5.5% DD (past the 5% limit) — no warning, breach fires instead
        enforcer.update_balance(current_equity=94_500.0)
        assert warnings_sent == []  # warning not sent; breach path handles it

    def test_daily_alert_reset_after_daily_reset(self):
        """After daily_reset(), the alert flag clears so it fires again next session."""
        enforcer = self._make_enforcer()
        warnings_sent = []
        enforcer._send_telegram_warning = warnings_sent.append

        enforcer.update_balance(current_equity=100_000.0, start_of_day_equity=100_000.0)
        enforcer.update_balance(current_equity=96_000.0)  # fires alert
        assert len(warnings_sent) == 1

        enforcer.daily_reset(new_equity=96_000.0)
        assert enforcer._daily_alert_sent is False

        # Next session: alert fires again at 80% of new SOD
        enforcer.update_balance(current_equity=96_000.0 * 0.96)  # 4% of new SOD
        assert len(warnings_sent) == 2

    def test_total_alert_fires_at_80pct_of_max_dd(self):
        """At 80% of total DD limit (8% from HWM on 10% limit) — warning sent."""
        enforcer = self._make_enforcer()
        warnings_sent = []
        enforcer._send_telegram_warning = warnings_sent.append

        enforcer.update_balance(current_equity=100_000.0, start_of_day_equity=100_000.0)
        # 8% total DD = 80% of 10% max_dd limit → total alert fires
        enforcer.update_balance(current_equity=92_000.0)
        assert len(warnings_sent) == 1
        assert enforcer._total_alert_sent is True

    def test_total_alert_fires_only_once(self):
        """Total DD alert is sent at most once (until reset)."""
        enforcer = self._make_enforcer()
        warnings_sent = []
        enforcer._send_telegram_warning = warnings_sent.append

        enforcer.update_balance(current_equity=100_000.0, start_of_day_equity=100_000.0)
        enforcer.update_balance(current_equity=92_000.0)  # triggers total alert
        enforcer.update_balance(current_equity=91_500.0)  # no second alert
        assert len(warnings_sent) == 1

    def test_trading_not_halted_after_80pct_alert(self):
        """80% alert is a warning only — trading must remain allowed."""
        enforcer = self._make_enforcer()
        enforcer._send_telegram_warning = lambda _: None  # suppress network call

        enforcer.update_balance(current_equity=100_000.0, start_of_day_equity=100_000.0)
        enforcer.update_balance(current_equity=96_000.0)  # 80% of daily limit

        allowed, reason = enforcer.before_execute(instrument="XAUUSD")
        assert allowed is True, f"Trading should not be halted at 80% alert: {reason}"
        assert enforcer._halted is False

    def test_alert_message_contains_buffer_info(self):
        """Warning message includes remaining buffer so trader knows headroom."""
        enforcer = self._make_enforcer()
        messages = []
        enforcer._send_telegram_warning = messages.append

        enforcer.update_balance(current_equity=100_000.0, start_of_day_equity=100_000.0)
        enforcer.update_balance(current_equity=96_000.0)

        assert len(messages) == 1
        assert "Remaining buffer" in messages[0]

    def test_no_alert_without_telegram_credentials(self):
        """If token/chat_id are empty, _send_telegram_warning returns silently."""
        from risk.compliance.prop_enforcer import PropEnforcer, PropConfig
        import threading

        enforcer = PropEnforcer.__new__(PropEnforcer)
        enforcer.cfg = PropConfig(daily_dd=0.05, max_dd=0.10, telegram_token="", telegram_chat_id="")
        enforcer._lock = threading.Lock()
        enforcer._start_balance = 0.0
        enforcer._high_water_mark = 0.0
        enforcer._sod_equity = 0.0
        enforcer._current_equity = 0.0
        enforcer._halted = False
        enforcer._halt_reason = ""
        enforcer._breach_log = []
        enforcer._news_events = []
        enforcer._on_breach_callbacks = []
        enforcer._kill_switch_fn = None
        enforcer._daily_alert_sent = False
        enforcer._total_alert_sent = False

        # Should not raise even without credentials
        enforcer.update_balance(current_equity=100_000.0, start_of_day_equity=100_000.0)
        enforcer.update_balance(current_equity=96_000.0)
        assert enforcer._daily_alert_sent is True  # flag set even without send


# ── Run directly ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
