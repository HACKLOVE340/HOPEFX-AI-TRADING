# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""Tests for risk/compliance/prop_engine.py — PropComplianceEngine, KillSwitch."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from risk.compliance.prop_engine import (
    BreachType,
    KillSwitch,
    PropComplianceEngine,
    PropFirmConfig,
)

UTC = timezone.utc


def _engine(
    initial_equity: float = 100_000.0,
    daily_dd: float = 0.05,
    max_dd: float = 0.10,
    breach_action: str = "liquidate",
) -> PropComplianceEngine:
    cfg = PropFirmConfig(
        daily_dd=daily_dd,
        max_dd=max_dd,
        weekend_close=False,
        breach_action=breach_action,
    )
    return PropComplianceEngine(config=cfg, initial_equity=initial_equity)


class TestKillSwitch:
    def test_initially_inactive(self):
        ks = KillSwitch()
        assert ks.is_active is False

    def test_activate(self):
        ks = KillSwitch()
        ks.activate("test reason")
        assert ks.is_active is True

    def test_deactivate(self):
        ks = KillSwitch()
        ks.activate("test")
        ks.deactivate()
        assert ks.is_active is False


class TestPropFirmConfig:
    def test_defaults(self):
        cfg = PropFirmConfig()
        assert cfg.daily_dd == pytest.approx(0.05)
        assert cfg.max_dd == pytest.approx(0.10)
        assert cfg.news_blackout == 5
        assert cfg.weekend_close is True

    def test_from_file_missing(self, tmp_path):
        cfg = PropFirmConfig.from_file(tmp_path / "missing.json")
        assert cfg.daily_dd == pytest.approx(0.05)

    def test_from_file_valid(self, tmp_path):
        p = tmp_path / "prop.json"
        p.write_text(json.dumps({"daily_dd": 0.03, "max_dd": 0.07, "news_blackout": 10}))
        cfg = PropFirmConfig.from_file(p)
        assert cfg.daily_dd == pytest.approx(0.03)
        assert cfg.max_dd == pytest.approx(0.07)
        assert cfg.news_blackout == 10


class TestPropComplianceEngineInit:
    def test_kill_switch_inactive(self):
        e = _engine()
        assert e.kill_switch.is_active is False

    def test_initial_equity_set(self):
        e = _engine(initial_equity=50_000.0)
        assert e._initial_equity == pytest.approx(50_000.0)

    def test_from_config_file_missing(self, tmp_path):
        e = PropComplianceEngine.from_config_file(str(tmp_path / "missing.json"))
        assert e is not None


class TestUpdateEquity:
    def test_equity_updated(self):
        e = _engine()
        e.update_equity(105_000.0)
        assert e._current_equity == pytest.approx(105_000.0)

    def test_high_water_mark_tracks_peak(self):
        e = _engine()
        e.update_equity(110_000.0)
        e.update_equity(105_000.0)
        assert e._high_water_mark == pytest.approx(110_000.0)

    def test_daily_drawdown_breach_via_before_order(self):
        # breach_action="liquidate" -> kill_switch.activate()
        e = _engine(initial_equity=100_000.0, daily_dd=0.05, breach_action="liquidate")
        e.update_equity(93_000.0)  # 7% drop > 5% limit
        e.before_order()  # triggers the compliance check
        assert e.kill_switch.is_active is True

    def test_total_drawdown_breach_via_before_order(self):
        e = _engine(initial_equity=100_000.0, max_dd=0.10, breach_action="liquidate")
        e.update_equity(89_000.0)  # 11% drop > 10% limit
        e.before_order()
        assert e.kill_switch.is_active is True


class TestBeforeOrder:
    def test_allows_normal_order(self):
        e = _engine()
        allowed, reason = e.before_order()
        assert allowed is True
        assert reason == ""

    def test_blocks_when_kill_switch_active(self):
        e = _engine()
        e.kill_switch.activate("test")
        allowed, reason = e.before_order()
        assert allowed is False
        assert reason != ""

    def test_blocks_when_paused(self):
        e = _engine(breach_action="pause")
        e._paused = True
        allowed, reason = e.before_order()
        assert allowed is False

    def test_blocks_during_news_blackout(self):
        e = _engine()
        future = datetime.now(UTC) + timedelta(minutes=2)
        e.set_news_events([future])
        allowed, reason = e.before_order()
        assert allowed is False
        assert "news" in reason.lower() or "blackout" in reason.lower()

    def test_allows_after_news_window(self):
        e = _engine()
        past = datetime.now(UTC) - timedelta(hours=1)
        e.set_news_events([past])
        allowed, reason = e.before_order()
        assert allowed is True

    def test_daily_dd_breach_blocks_order(self):
        e = _engine(initial_equity=100_000.0, daily_dd=0.05, breach_action="pause")
        e.update_equity(93_000.0)
        allowed, reason = e.before_order()
        assert allowed is False

    def test_total_dd_breach_blocks_order(self):
        e = _engine(initial_equity=100_000.0, max_dd=0.10, breach_action="pause")
        e.update_equity(89_000.0)
        allowed, reason = e.before_order()
        assert allowed is False


class TestBreachCallback:
    def test_on_breach_called_on_daily_dd(self):
        breaches = []
        e = _engine(initial_equity=100_000.0, daily_dd=0.05, breach_action="pause")
        e._on_breach = lambda bt, msg: breaches.append(bt)
        e.update_equity(93_000.0)
        e.before_order()
        assert BreachType.DAILY_DD in breaches

    def test_on_breach_called_on_total_dd(self):
        breaches = []
        # Set daily_dd very high so only max_dd fires
        e = _engine(initial_equity=100_000.0, daily_dd=0.99, max_dd=0.10, breach_action="pause")
        e._on_breach = lambda bt, msg: breaches.append(bt)
        e.update_equity(89_000.0)
        e.before_order()
        assert BreachType.MAX_DD in breaches


class TestStatus:
    def test_status_keys(self):
        e = _engine()
        s = e.status()
        assert "kill_switch" in s
        assert "current_equity" in s
        assert "daily_dd" in s
        assert "total_dd" in s

    def test_status_values(self):
        e = _engine(initial_equity=100_000.0)
        e.update_equity(100_000.0)
        s = e.status()
        assert s["kill_switch"] is False
        assert s["daily_dd"] == pytest.approx(0.0, abs=0.01)


class TestEdgeCases:
    def test_daily_drawdown_zero_when_day_start_equity_zero(self):
        e = _engine()
        e._day_start_equity = 0.0
        assert e._daily_drawdown() == pytest.approx(0.0)

    def test_total_drawdown_zero_when_hwm_zero(self):
        e = _engine()
        e._high_water_mark = 0.0
        assert e._total_drawdown() == pytest.approx(0.0)

    def test_send_telegram_alert_no_token_no_crash(self):
        e = _engine()
        e._send_telegram_alert("test message")

    def test_send_telegram_alert_with_token_handles_exception(self):
        from unittest.mock import patch

        e = _engine()
        e.cfg.telegram_token = "fake_token"
        e.cfg.telegram_chat_id = "fake_chat"
        with patch("risk.compliance.prop_engine.requests.post", side_effect=Exception("network error")):
            e._send_telegram_alert("test")

    def test_is_weekend_window_friday_before_21_false(self):
        e = _engine()
        friday_early = datetime(2025, 1, 3, 18, 0, 0, tzinfo=UTC)
        assert e._is_weekend_window(friday_early) is False

    def test_is_weekend_window_friday_after_21_true(self):
        e = _engine()
        friday_late = datetime(2025, 1, 3, 22, 0, 0, tzinfo=UTC)
        assert e._is_weekend_window(friday_late) is True

    def test_is_weekend_window_sunday_before_23_true(self):
        e = _engine()
        sunday_early = datetime(2025, 1, 5, 10, 0, 0, tzinfo=UTC)
        assert e._is_weekend_window(sunday_early) is True

    def test_is_weekend_window_sunday_after_23_false(self):
        e = _engine()
        sunday_late = datetime(2025, 1, 5, 23, 30, 0, tzinfo=UTC)
        assert e._is_weekend_window(sunday_late) is False

    def test_weekend_close_blocks_saturday(self):
        cfg = PropFirmConfig(weekend_close=True, breach_action="pause")
        e = PropComplianceEngine(config=cfg, initial_equity=100_000.0)
        saturday = datetime(2025, 1, 4, 12, 0, 0, tzinfo=UTC)
        allowed, reason = e.before_order(now=saturday)
        assert allowed is False
        assert "weekend" in reason.lower()

    def test_in_news_blackout_false_no_events(self):
        e = _engine()
        assert e._in_news_blackout(datetime.now(UTC)) is False

    def test_breach_action_pause_sets_paused(self):
        e = _engine(breach_action="pause")
        e._breach(BreachType.DAILY_DD, "test breach")
        assert e._paused is True

    def test_breach_action_liquidate_activates_kill_switch(self):
        e = _engine(breach_action="liquidate")
        e._breach(BreachType.MAX_DD, "test breach")
        assert e.kill_switch.is_active is True

    def test_on_breach_callback_exception_does_not_propagate(self):
        def bad_cb(bt, msg):
            raise RuntimeError("boom")

        e = _engine(breach_action="pause")
        e._on_breach = bad_cb
        e._breach(BreachType.DAILY_DD, "test")  # should not raise
