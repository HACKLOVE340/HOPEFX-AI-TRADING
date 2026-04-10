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
        e.update_equity(93_000.0)   # 7% drop > 5% limit
        e.before_order()            # triggers the compliance check
        assert e.kill_switch.is_active is True

    def test_total_drawdown_breach_via_before_order(self):
        e = _engine(initial_equity=100_000.0, max_dd=0.10, breach_action="liquidate")
        e.update_equity(89_000.0)   # 11% drop > 10% limit
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
