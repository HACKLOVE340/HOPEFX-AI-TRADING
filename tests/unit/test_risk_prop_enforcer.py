# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""Tests for risk/compliance/prop_enforcer.py — PropEnforcer, PropConfig."""

from __future__ import annotations

import json
import time

import pytest

from risk.compliance.prop_enforcer import BreachType, PropConfig, PropEnforcer


def _enforcer(tmp_path, weekend_close: bool = False, **kwargs) -> PropEnforcer:
    """Create a PropEnforcer for testing.

    weekend_close defaults to False so tests pass on any day of the week.
    Tests that specifically exercise the weekend gate pass weekend_close=True.
    """
    import json

    cfg_path = tmp_path / "test_prop_config.json"
    cfg_path.write_text(json.dumps({"weekend_close": weekend_close}))
    return PropEnforcer(config_path=cfg_path, **kwargs)


class TestPropConfig:
    def test_defaults(self):
        cfg = PropConfig()
        assert cfg.daily_dd == pytest.approx(0.05)
        assert cfg.max_dd == pytest.approx(0.10)
        assert cfg.news_blackout == 300
        assert cfg.weekend_close is True
        assert cfg.breach_action == "pause"

    def test_from_file_missing_uses_defaults(self, tmp_path):
        cfg = PropConfig.from_file(tmp_path / "nonexistent.json")
        assert cfg.daily_dd == pytest.approx(0.05)

    def test_from_file_flat_schema(self, tmp_path):
        p = tmp_path / "prop.json"
        p.write_text(
            json.dumps(
                {
                    "daily_dd": 0.03,
                    "max_dd": 0.08,
                    "news_blackout": 600,
                    "weekend_close": False,
                    "breach_action": "liquidate",
                }
            )
        )
        cfg = PropConfig.from_file(p)
        assert cfg.daily_dd == pytest.approx(0.03)
        assert cfg.max_dd == pytest.approx(0.08)
        assert cfg.news_blackout == 600
        assert cfg.breach_action == "liquidate"

    def test_from_file_malformed_uses_defaults(self, tmp_path):
        p = tmp_path / "bad.json"
        p.write_text("not valid json {{{")
        cfg = PropConfig.from_file(p)
        assert cfg.daily_dd == pytest.approx(0.05)


class TestPropEnforcerInit:
    def test_not_halted_initially(self, tmp_path):
        e = _enforcer(tmp_path)
        assert e._halted is False

    def test_missing_config_uses_defaults(self, tmp_path):
        e = _enforcer(tmp_path)
        assert e.cfg.daily_dd == pytest.approx(0.05)


class TestUpdateBalance:
    def test_first_call_sets_start_balance(self, tmp_path):
        e = _enforcer(tmp_path)
        e.update_balance(current_equity=100_000.0, start_of_day_equity=100_000.0)
        assert e._start_balance == pytest.approx(100_000.0)

    def test_high_water_mark_tracks_peak(self, tmp_path):
        e = _enforcer(tmp_path)
        e.update_balance(100_000.0, 100_000.0)
        e.update_balance(105_000.0, 100_000.0)
        e.update_balance(102_000.0, 100_000.0)
        assert e._high_water_mark == pytest.approx(105_000.0)

    def test_sod_equity_set_on_first_call(self, tmp_path):
        e = _enforcer(tmp_path)
        e.update_balance(100_000.0, start_of_day_equity=100_000.0)
        assert e._sod_equity == pytest.approx(100_000.0)


class TestBeforeExecute:
    def test_allows_normal_order(self, tmp_path):
        e = _enforcer(tmp_path)
        e.update_balance(100_000.0, 100_000.0)
        ok, reason = e.before_execute(instrument="XAUUSD")
        assert ok is True
        assert reason == ""

    def test_blocks_when_halted(self, tmp_path):
        e = _enforcer(tmp_path)
        e._halted = True
        e._halt_reason = "DAILY_DD breach"
        ok, reason = e.before_execute(instrument="XAUUSD")
        assert ok is False
        assert reason != ""

    def test_daily_dd_breach_halts(self, tmp_path):
        e = _enforcer(tmp_path)
        e.update_balance(100_000.0, 100_000.0)
        # Drop 6% (limit is 5%) — before_execute checks and halts
        e.update_balance(94_000.0, 100_000.0)
        ok, reason = e.before_execute(instrument="XAUUSD")
        assert ok is False
        assert e._halted is True

    def test_total_dd_breach_halts(self, tmp_path):
        e = _enforcer(tmp_path)
        e.update_balance(100_000.0, 100_000.0)
        # Drop 11% total (limit is 10%)
        e.update_balance(89_000.0, 100_000.0)
        ok, reason = e.before_execute(instrument="XAUUSD")
        assert ok is False
        assert e._halted is True

    def test_blocks_during_news_blackout(self, tmp_path):
        e = _enforcer(tmp_path)
        e.update_balance(100_000.0, 100_000.0)
        # Register a news event 60 seconds from now (within 300s blackout)
        e.register_news_event(time.time() + 60)
        ok, reason = e.before_execute(instrument="XAUUSD")
        assert ok is False
        assert "news" in reason.lower() or "blackout" in reason.lower()

    def test_allows_after_news_window(self, tmp_path):
        e = _enforcer(tmp_path)
        e.update_balance(100_000.0, 100_000.0)
        # News event 1000 seconds ago (outside 300s blackout)
        e.register_news_event(time.time() - 1000)
        ok, reason = e.before_execute(instrument="XAUUSD")
        assert ok is True


class TestDailyReset:
    def test_daily_reset_updates_sod_equity(self, tmp_path):
        e = _enforcer(tmp_path)
        e.update_balance(100_000.0, 100_000.0)
        e.daily_reset(new_equity=98_000.0)
        assert e._sod_equity == pytest.approx(98_000.0)

    def test_daily_reset_clears_daily_dd_halt(self, tmp_path):
        e = _enforcer(tmp_path)
        e.update_balance(100_000.0, 100_000.0)
        # Trigger daily DD halt
        e.update_balance(94_000.0, 100_000.0)
        e.before_execute()
        assert e._halted is True
        # Reset should clear daily-DD halt
        e.daily_reset(new_equity=100_000.0)
        assert e._halted is False

    def test_daily_reset_resets_alert_flags(self, tmp_path):
        e = _enforcer(tmp_path)
        e._daily_alert_sent = True
        e._total_alert_sent = True
        e.daily_reset(new_equity=100_000.0)
        assert e._daily_alert_sent is False


class TestBreachCallback:
    def test_callback_fired_on_daily_breach(self, tmp_path):
        breaches = []
        e = _enforcer(tmp_path)
        e.register_on_breach(lambda bt, msg: breaches.append((bt, msg)))
        e.update_balance(100_000.0, 100_000.0)
        e.update_balance(94_000.0, 100_000.0)
        e.before_execute()  # triggers the breach
        assert len(breaches) >= 1
        assert any(bt == BreachType.DAILY_DD for bt, _ in breaches)

    def test_status_dict(self, tmp_path):
        e = _enforcer(tmp_path)
        e.update_balance(100_000.0, 100_000.0)
        s = e.status()
        assert "halted" in s
        assert "current_equity" in s
        assert "daily_dd_pct" in s


class TestPropConfigNestedSchema:
    """Cover the nested enforcement/firms schema path in PropConfig.from_file."""

    def test_nested_enforcement_schema(self, tmp_path):
        p = tmp_path / "prop.json"
        p.write_text(
            json.dumps(
                {
                    "enforcement": {
                        "max_daily_drawdown_pct": 3.0,
                        "max_total_drawdown_pct": 7.0,
                    },
                    "weekend_close": False,
                }
            )
        )
        cfg = PropConfig.from_file(p)
        assert cfg.daily_dd == pytest.approx(0.03)
        assert cfg.max_dd == pytest.approx(0.07)

    def test_nested_firms_schema(self, tmp_path):
        p = tmp_path / "prop.json"
        p.write_text(
            json.dumps(
                {
                    "active_firm": "ftmo",
                    "firms": {
                        "ftmo": {
                            "drawdown": {
                                "max_daily_drawdown_pct": 4.0,
                                "max_total_drawdown_pct": 8.0,
                            },
                            "news_trading": {"blackout_minutes_before_news": 10},
                            "overnight_holding": {"weekend_holding_allowed": False},
                        }
                    },
                }
            )
        )
        cfg = PropConfig.from_file(p)
        # weekend_holding_allowed=False → weekend_close=True
        assert cfg.weekend_close is True

    def test_weekend_close_fallback_from_firm_cfg(self, tmp_path):
        """No 'weekend_close' key → derive from overnight_holding."""
        p = tmp_path / "prop.json"
        p.write_text(
            json.dumps(
                {
                    "active_firm": "goat",
                    "firms": {
                        "goat": {
                            "overnight_holding": {"weekend_holding_allowed": True},
                        }
                    },
                }
            )
        )
        cfg = PropConfig.from_file(p)
        assert cfg.weekend_close is False

    def test_telegram_from_env(self, tmp_path, monkeypatch):
        monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "tok123")
        monkeypatch.setenv("TELEGRAM_CHAT_ID", "chat456")
        p = tmp_path / "prop.json"
        p.write_text(json.dumps({"daily_dd": 0.05}))
        cfg = PropConfig.from_file(p)
        assert cfg.telegram_token == "tok123"
        assert cfg.telegram_chat_id == "chat456"


class TestUpdateBalanceAlerts:
    """Cover the 80% drawdown warning alert paths."""

    def test_daily_dd_80pct_alert_fires_once(self, tmp_path):
        """Alert fires when daily DD reaches 80% of limit (non-halting)."""
        e = _enforcer(tmp_path)
        e.update_balance(100_000.0, 100_000.0)
        # 80% of 5% daily limit = 4% drawdown → equity at 96_000
        e.update_balance(96_000.0, 100_000.0)
        assert e._daily_alert_sent is True
        # Second call should not re-fire
        e.update_balance(96_000.0, 100_000.0)
        assert e._daily_alert_sent is True

    def test_total_dd_80pct_alert_fires_once(self, tmp_path):
        """Alert fires when total DD reaches 80% of max_dd limit."""
        e = _enforcer(tmp_path)
        e.update_balance(100_000.0, 100_000.0)
        # 80% of 10% total limit = 8% drawdown → equity at 92_000
        e.update_balance(92_000.0, 100_000.0)
        assert e._total_alert_sent is True

    def test_daily_alert_not_fired_below_threshold(self, tmp_path):
        """Alert does NOT fire when DD is below 80% of limit."""
        e = _enforcer(tmp_path)
        e.update_balance(100_000.0, 100_000.0)
        # Only 2% drawdown (limit is 5%, 80% threshold is 4%)
        e.update_balance(98_000.0, 100_000.0)
        assert e._daily_alert_sent is False

    def test_daily_reset_clears_total_alert_flag(self, tmp_path):
        """daily_reset clears _daily_alert_sent but NOT _total_alert_sent."""
        e = _enforcer(tmp_path)
        e._daily_alert_sent = True
        e._total_alert_sent = True
        e.daily_reset(new_equity=100_000.0)
        assert e._daily_alert_sent is False
        # total_alert_sent is NOT reset by daily_reset (by design)
        assert e._total_alert_sent is True

    def test_daily_reset_does_not_clear_total_dd_halt(self, tmp_path):
        """daily_reset only clears DAILY_DD halts, not TOTAL_DD halts."""
        e = _enforcer(tmp_path)
        e._halted = True
        e._halt_reason = "TOTAL_DD breach: ..."
        e.daily_reset(new_equity=100_000.0)
        # Total-DD halt must persist
        assert e._halted is True


class TestKillSwitchCallback:
    """Cover kill_switch_fn invocation and exception handling."""

    def test_kill_switch_fn_called_on_halt(self, tmp_path):
        calls = []
        e = _enforcer(tmp_path, kill_switch_fn=lambda msg: calls.append(msg))
        e.update_balance(100_000.0, 100_000.0)
        e.update_balance(94_000.0, 100_000.0)
        e.before_execute()
        assert len(calls) >= 1

    def test_kill_switch_fn_exception_does_not_propagate(self, tmp_path):
        def bad_ks(msg):
            raise RuntimeError("ks exploded")

        e = _enforcer(tmp_path, kill_switch_fn=bad_ks)
        e.update_balance(100_000.0, 100_000.0)
        e.update_balance(94_000.0, 100_000.0)
        # Should not raise
        ok, reason = e.before_execute()
        assert ok is False


class TestTelegramAlerts:
    """Cover _send_telegram_warning and _send_telegram_alert with token set."""

    def test_send_telegram_warning_with_token_handles_network_error(self, tmp_path):
        """With token+chat_id set, network failure is swallowed."""
        cfg_path = tmp_path / "prop.json"
        cfg_path.write_text(
            json.dumps(
                {
                    "telegram_token": "fake_token",
                    "telegram_chat_id": "fake_chat",
                    "weekend_close": False,
                }
            )
        )
        e = PropEnforcer(config_path=cfg_path)
        # Should not raise even though the URL is invalid
        e._send_telegram_warning("test warning detail")

    def test_send_telegram_alert_with_token_handles_network_error(self, tmp_path):
        """With token+chat_id set, network failure is swallowed."""
        cfg_path = tmp_path / "prop.json"
        cfg_path.write_text(
            json.dumps(
                {
                    "telegram_token": "fake_token",
                    "telegram_chat_id": "fake_chat",
                    "weekend_close": False,
                }
            )
        )
        e = PropEnforcer(config_path=cfg_path)
        e._send_telegram_alert(BreachType.DAILY_DD, "test breach detail")

    def test_send_telegram_alert_all_breach_types(self, tmp_path):
        """Exercise all BreachType emoji branches."""
        cfg_path = tmp_path / "prop.json"
        cfg_path.write_text(
            json.dumps(
                {
                    "telegram_token": "fake_token",
                    "telegram_chat_id": "fake_chat",
                    "weekend_close": False,
                }
            )
        )
        e = PropEnforcer(config_path=cfg_path)
        for bt in BreachType:
            e._send_telegram_alert(bt, f"detail for {bt.name}")


class TestGetEnforcerSingleton:
    """Cover the module-level get_enforcer() singleton."""

    def test_get_enforcer_returns_instance(self):
        from risk.compliance.prop_enforcer import get_enforcer

        inst = get_enforcer()
        assert isinstance(inst, PropEnforcer)

    def test_get_enforcer_returns_same_instance(self):
        from risk.compliance import prop_enforcer as _mod
        from risk.compliance.prop_enforcer import get_enforcer

        # Reset singleton so we get a fresh one
        _mod._default_enforcer = None
        a = get_enforcer()
        b = get_enforcer()
        assert a is b
