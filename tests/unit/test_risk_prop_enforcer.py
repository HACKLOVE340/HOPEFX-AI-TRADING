# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""Tests for risk/compliance/prop_enforcer.py — PropEnforcer, PropConfig."""

from __future__ import annotations

import json
import time

import pytest

from risk.compliance.prop_enforcer import BreachType, PropConfig, PropEnforcer


def _enforcer(tmp_path, **kwargs) -> PropEnforcer:
    return PropEnforcer(config_path=tmp_path / "missing.json", **kwargs)


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
        p.write_text(json.dumps({
            "daily_dd": 0.03,
            "max_dd": 0.08,
            "news_blackout": 600,
            "weekend_close": False,
            "breach_action": "liquidate",
        }))
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
