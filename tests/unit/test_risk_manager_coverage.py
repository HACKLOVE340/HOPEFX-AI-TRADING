# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
Coverage tests for risk/manager.py — Part 1
Targets: data classes, RiskConfig, RiskState, RiskManager construction,
         size_order hard gates, assess, update_equity, on_fill/on_close.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_rm(**kwargs):
    from risk.manager import RiskManager
    return RiskManager(**kwargs)


def _signal(
    confidence=0.75,
    probability=0.55,
    direction="long",
    symbol="XAU_USD",
    tick_mid=1950.0,
    tick_spread=1.0,
    data_quality=1.0,
    features=None,
):
    s = MagicMock()
    s.confidence = confidence
    s.probability = probability
    s.direction = direction
    s.symbol = symbol

    s.tick_mid = tick_mid
    s.tick_spread = tick_spread
    s.data_quality = data_quality
    s.features = features or {}
    return s


# ---------------------------------------------------------------------------
# PositionSizingResult
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestPositionSizingResult:
    def _make(self, qty=1.0):
        from risk.manager import PositionSizingResult
        return PositionSizingResult(
            symbol="XAU_USD", direction="long", quantity=qty,
            notional_usd=qty * 1950.0, stop_loss_usd=1940.0,
            take_profit_usd=1970.0, risk_usd=10.0, lineage_id="x",
        )

    def test_size_alias(self):
        assert self._make(2.0).size == pytest.approx(2.0)

    def test_approved_positive(self):
        assert self._make(0.5).approved is True

    def test_approved_zero(self):
        assert self._make(0.0).approved is False

    def test_lot_size(self):
        r = self._make(2.5)
        assert r.lot_size == pytest.approx(2.5)

    def test_recommended_size(self):
        assert self._make(3.0).recommended_size == pytest.approx(3.0)

    def test_stop_loss_price_property(self):
        assert self._make().stop_loss_price == pytest.approx(1940.0)

    def test_take_profit_price_property(self):
        assert self._make().take_profit_price == pytest.approx(1970.0)


# ---------------------------------------------------------------------------
# RiskConfig
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestRiskConfig:
    def test_defaults(self):
        from risk.manager import RiskConfig
        c = RiskConfig()
        assert c.max_drawdown_pct > 0
        assert c.max_daily_loss_pct > 0
        assert c.kelly_fraction > 0

    def test_custom_values(self):
        from risk.manager import RiskConfig
        c = RiskConfig(max_drawdown_pct=0.15, max_daily_loss_pct=0.03)
        assert c.max_drawdown_pct == pytest.approx(0.15)
        assert c.max_daily_loss_pct == pytest.approx(0.03)

    def test_kelly_fraction_stored(self):
        from risk.manager import RiskConfig
        c = RiskConfig(kelly_fraction=0.30)
        assert c.kelly_fraction == pytest.approx(0.30)


# ---------------------------------------------------------------------------
# RiskState
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestRiskState:
    def _make(self, equity=100_000.0, peak=100_000.0, day_open=100_000.0):
        from risk.manager import RiskState
        import datetime
        return RiskState(
            account_equity=equity, peak_equity=peak,
            day_open_equity=day_open,
            trade_day=datetime.datetime.now(datetime.timezone.utc).day,
        )

    def test_zero_drawdown_at_start(self):
        assert self._make().current_drawdown == pytest.approx(0.0)

    def test_current_drawdown_after_loss(self):
        s = self._make(equity=90_000.0, peak=100_000.0)
        assert s.current_drawdown == pytest.approx(0.10)

    def test_daily_drawdown(self):
        s = self._make(equity=95_000.0, day_open=100_000.0)
        assert s.daily_drawdown == pytest.approx(0.05)

    def test_update_equity_raises_peak(self):
        s = self._make()
        s.update_equity(110_000.0)
        assert s.peak_equity == pytest.approx(110_000.0)

    def test_update_equity_day_rollover(self):
        import datetime
        from risk.manager import RiskState
        today = datetime.datetime.now(datetime.timezone.utc).day
        other_day = (today % 28) + 1
        s = RiskState(account_equity=100_000.0, peak_equity=100_000.0,
                      day_open_equity=100_000.0, trade_day=other_day)
        s.update_equity(95_000.0)
        assert s.day_open_equity == pytest.approx(95_000.0)


# ---------------------------------------------------------------------------
# RiskManager construction
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestRiskManagerConstruction:
    def test_default_construction(self):
        assert _make_rm() is not None

    def test_custom_initial_balance(self):
        rm = _make_rm(initial_balance=50_000.0)
        assert rm._state.account_equity == pytest.approx(50_000.0)

    def test_custom_config(self):
        from risk.manager import RiskConfig
        cfg = RiskConfig(max_drawdown_pct=0.20)
        rm = _make_rm(config=cfg)
        assert rm.config.max_drawdown_pct == pytest.approx(0.20)

    def test_kill_switch_false_initially(self):
        assert _make_rm().kill_switch_active is False

    def test_open_positions_empty_initially(self):
        assert _make_rm().open_positions == []

    def test_peak_equity_property(self):
        rm = _make_rm(initial_balance=100_000.0)
        assert rm.peak_equity == pytest.approx(100_000.0)

    def test_daily_starting_equity_property(self):
        rm = _make_rm(initial_balance=100_000.0)
        assert rm.daily_starting_equity == pytest.approx(100_000.0)

    def test_halt_state_file_param(self, tmp_path):
        from pathlib import Path
        f = tmp_path / "halt.json"
        rm = _make_rm(halt_state_file=str(f))
        assert rm._halt_state_file == f

    def test_open_positions_setter(self):
        rm = _make_rm(initial_balance=100_000.0)
        rm.open_positions = [{"symbol": "XAU_USD"}]
        assert rm._state.open_positions == 1

    def test_peak_equity_setter(self):
        rm = _make_rm(initial_balance=100_000.0)
        rm.peak_equity = 120_000.0
        assert rm._state.peak_equity == pytest.approx(120_000.0)

    def test_daily_starting_equity_setter(self):
        rm = _make_rm(initial_balance=100_000.0)
        rm.daily_starting_equity = 95_000.0
        assert rm._state.day_open_equity == pytest.approx(95_000.0)


# ---------------------------------------------------------------------------
# size_order — hard gates
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestSizeOrderHardGates:
    def test_returns_positive_quantity_normal(self):
        rm = _make_rm(initial_balance=100_000.0)
        assert rm.size_order(_signal()).quantity > 0

    def test_halted_returns_zero(self):
        rm = _make_rm(initial_balance=100_000.0)
        rm._halt = True
        rm._halt_reason = "test"
        assert rm.size_order(_signal()).quantity == pytest.approx(0.0)

    def test_daily_dd_limit_returns_zero(self):
        rm = _make_rm(initial_balance=100_000.0)
        rm._state.account_equity = 94_000.0
        rm._state.day_open_equity = 100_000.0
        assert rm.size_order(_signal()).quantity == pytest.approx(0.0)

    def test_max_dd_limit_returns_zero(self):
        rm = _make_rm(initial_balance=100_000.0)
        rm._state.account_equity = 89_000.0
        rm._state.peak_equity = 100_000.0
        assert rm.size_order(_signal()).quantity == pytest.approx(0.0)

    def test_max_open_positions_returns_zero(self):
        rm = _make_rm(initial_balance=100_000.0)
        rm._state.open_positions = 10
        assert rm.size_order(_signal()).quantity == pytest.approx(0.0)

    def test_low_data_quality_returns_zero(self):
        rm = _make_rm(initial_balance=100_000.0)
        assert rm.size_order(_signal(data_quality=0.10)).quantity == pytest.approx(0.0)

    def test_symbol_and_direction_preserved(self):
        rm = _make_rm(initial_balance=100_000.0)
        r = rm.size_order(_signal(symbol="XAGUSD", direction="short"))
        assert r.symbol == "XAGUSD"
        assert r.direction == "short"

    def test_sizing_history_appended(self):
        rm = _make_rm(initial_balance=100_000.0)
        rm.size_order(_signal())
        assert len(rm._sizing_history) == 1

    def test_lineage_write_called(self):
        lineage = MagicMock()
        rm = _make_rm(initial_balance=100_000.0, lineage_store=lineage)
        rm.size_order(_signal())
        lineage.record_signal.assert_called_once()

    def test_lineage_write_no_crash_on_exception(self):
        lineage = MagicMock()
        lineage.record_signal.side_effect = RuntimeError("db down")
        rm = _make_rm(initial_balance=100_000.0, lineage_store=lineage)
        assert rm.size_order(_signal()).quantity > 0

    def test_notional_within_bounds(self):
        rm = _make_rm(initial_balance=100_000.0)
        r = rm.size_order(_signal())
        assert r.notional_usd >= 100_000.0 * 0.001
        assert r.notional_usd <= 100_000.0 * 0.05


# ---------------------------------------------------------------------------
# size_order — scaling factors and directions
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestSizeOrderScaling:
    def test_short_stop_above_entry(self):
        rm = _make_rm(initial_balance=100_000.0)
        r = rm.size_order(_signal(direction="short", tick_mid=1950.0))
        assert r.stop_loss_usd > 1950.0

    def test_long_stop_below_entry(self):
        rm = _make_rm(initial_balance=100_000.0)
        r = rm.size_order(_signal(direction="long", tick_mid=1950.0))
        assert r.stop_loss_usd < 1950.0

    def test_high_sentiment_reduces_size(self):
        orch = MagicMock()
        orch.get_latest_tick.return_value = MagicMock(confidence=1.0)
        orch.get_ml_features.return_value = {"news_sentiment_score": 0.90, "macro_impact_score": 0.0}
        rm_base = _make_rm(initial_balance=100_000.0)
        rm_sent = _make_rm(initial_balance=100_000.0, orchestrator=orch)
        assert rm_sent.size_order(_signal()).quantity <= rm_base.size_order(_signal()).quantity

    def test_high_impact_reduces_size(self):
        orch = MagicMock()
        orch.get_latest_tick.return_value = MagicMock(confidence=1.0)
        orch.get_ml_features.return_value = {"news_sentiment_score": 0.0, "macro_impact_score": 0.90}
        rm_base = _make_rm(initial_balance=100_000.0)
        rm_imp = _make_rm(initial_balance=100_000.0, orchestrator=orch)
        assert rm_imp.size_order(_signal()).quantity <= rm_base.size_order(_signal()).quantity

    def test_zero_mid_price_uses_fallback(self):
        rm = _make_rm(initial_balance=100_000.0)
        r = rm.size_order(_signal(tick_mid=0.0))
        assert r.quantity > 0  # fallback price used


# ---------------------------------------------------------------------------
# assess
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestAssess:
    def test_approved_normal(self):
        rm = _make_rm(initial_balance=100_000.0)
        assert rm.assess(_signal()).approved is True

    def test_rejected_when_halted(self):
        rm = _make_rm(initial_balance=100_000.0)
        rm._halt = True
        rm._halt_reason = "test"
        r = rm.assess(_signal())
        assert r.approved is False
        assert "halted" in r.reason

    def test_rejected_daily_dd(self):
        rm = _make_rm(initial_balance=100_000.0)
        rm._state.account_equity = 94_000.0
        rm._state.day_open_equity = 100_000.0
        r = rm.assess(_signal())
        assert r.approved is False
        assert "daily_dd" in r.reason

    def test_rejected_low_data_quality(self):
        rm = _make_rm(initial_balance=100_000.0)
        r = rm.assess(_signal(data_quality=0.10))
        assert r.approved is False
        assert "data_quality" in r.reason

    def test_returns_risk_assessment_type(self):
        from risk.manager import RiskAssessment
        assert isinstance(_make_rm(initial_balance=100_000.0).assess(_signal()), RiskAssessment)

    def test_includes_drawdown_pct(self):
        assert _make_rm(initial_balance=100_000.0).assess(_signal()).drawdown_pct >= 0.0

    def test_includes_var(self):
        assert _make_rm(initial_balance=100_000.0).assess(_signal()).var_95 is not None


# ---------------------------------------------------------------------------
# update_equity / on_fill / on_close
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestEquityAndPositionUpdates:
    def test_update_equity_raises_peak(self):
        rm = _make_rm(initial_balance=100_000.0)
        rm.update_equity(110_000.0)
        assert rm.peak_equity == pytest.approx(110_000.0)

    def test_update_equity_auto_halt_on_max_dd(self):
        rm = _make_rm(initial_balance=100_000.0)
        rm.update_equity(85_000.0)
        assert rm._halt is True

    def test_update_equity_auto_halt_on_daily_loss(self):
        rm = _make_rm(initial_balance=100_000.0)
        rm._state.day_open_equity = 100_000.0
        rm.update_equity(94_000.0)
        assert rm._halt is True

    def test_on_fill_increments_open_positions(self):
        rm = _make_rm(initial_balance=100_000.0)
        rm.on_fill("XAU_USD", "long", 1.0, 1950.0)
        assert rm._state.open_positions == 1

    def test_on_close_decrements_open_positions(self):
        rm = _make_rm(initial_balance=100_000.0)
        rm._state.open_positions = 2
        rm.on_close("XAU_USD", 100.0)
        assert rm._state.open_positions == 1

    def test_on_close_updates_pnl(self):
        rm = _make_rm(initial_balance=100_000.0)
        rm.on_close("XAU_USD", 250.0)
        assert rm._state.daily_pnl == pytest.approx(250.0)

    def test_on_close_no_negative_positions(self):
        rm = _make_rm(initial_balance=100_000.0)
        rm._state.open_positions = 0
        rm.on_close("XAU_USD", -50.0)
        assert rm._state.open_positions == 0

    def test_notify_position_opened(self):
        rm = _make_rm(initial_balance=100_000.0)
        rm.notify_position_opened("XAU_USD")
        assert rm._state.open_positions == 1

    def test_notify_position_closed(self):
        rm = _make_rm(initial_balance=100_000.0)
        rm._state.open_positions = 1
        rm.notify_position_closed("XAU_USD")
        assert rm._state.open_positions == 0

    def test_record_partial_fill(self):
        rm = _make_rm(initial_balance=100_000.0)
        rm.record_partial_fill(75.0)
        assert rm._state.daily_pnl == pytest.approx(75.0)


# ---------------------------------------------------------------------------
# halt / resume
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestHaltResume:
    def test_halt_trading_sets_halt(self):
        rm = _make_rm(initial_balance=100_000.0)
        rm._halt_trading("test_reason")
        assert rm._halt is True
        assert rm._halt_reason == "test_reason"

    def test_resume_trading_clears_halt(self):
        rm = _make_rm(initial_balance=100_000.0)
        rm._halt_trading("test")
        rm.resume_trading()
        assert rm._halt is False

    def test_halt_persists_to_file(self, tmp_path):
        import json
        f = tmp_path / "halt.json"
        rm = _make_rm(initial_balance=100_000.0, halt_state_file=str(f))
        rm._halt_trading("drawdown")
        assert f.exists()
        data = json.loads(f.read_text())
        assert data["halt"] is True

    def test_restore_halt_state_from_file(self, tmp_path):
        import json
        f = tmp_path / "halt.json"
        f.write_text(json.dumps({"halt": True, "halted": True, "reason": "restored"}))
        rm = _make_rm(initial_balance=100_000.0, halt_state_file=str(f))
        assert rm._halt is True
        assert rm._halt_reason == "restored"

    def test_clear_halt_state_removes_file(self, tmp_path):
        import json
        f = tmp_path / "halt.json"
        f.write_text(json.dumps({"halt": True, "reason": "x"}))
        rm = _make_rm(initial_balance=100_000.0, halt_state_file=str(f))
        rm._clear_halt_state()
        assert not f.exists()

    def test_halt_state_file_none_no_crash(self):
        rm = _make_rm(initial_balance=100_000.0)
        rm._halt_state_file = None
        rm._halt_trading("test")  # should not raise
        assert rm._halt is True


# ---------------------------------------------------------------------------
# calculate_position_size convenience wrapper
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestCalculatePositionSize:
    def test_returns_positive_quantity(self):
        rm = _make_rm(initial_balance=100_000.0)
        r = rm.calculate_position_size(
            symbol="XAU_USD", entry_price=1950.0,
            account_balance=100_000.0, direction="long",
        )
        assert r.quantity > 0

    def test_uses_account_equity_param(self):
        rm = _make_rm(initial_balance=100_000.0)
        r = rm.calculate_position_size(
            symbol="XAU_USD", entry_price=1950.0,
            account_equity=200_000.0,
        )
        assert r.notional_usd > 0

    def test_stop_loss_override(self):
        rm = _make_rm(initial_balance=100_000.0)
        r = rm.calculate_position_size(
            symbol="XAU_USD", entry_price=1950.0,
            account_balance=100_000.0, stop_loss_price=1930.0,
        )
        assert r.stop_loss_usd == pytest.approx(1930.0)

    def test_take_profit_override(self):
        rm = _make_rm(initial_balance=100_000.0)
        r = rm.calculate_position_size(
            symbol="XAU_USD", entry_price=1950.0,
            account_balance=100_000.0, take_profit_price=1990.0,
        )
        assert r.take_profit_usd == pytest.approx(1990.0)

    def test_signal_strength_used_as_confidence(self):
        rm = _make_rm(initial_balance=100_000.0)
        r = rm.calculate_position_size(
            symbol="XAU_USD", entry_price=1950.0,
            account_balance=100_000.0, signal_strength=0.90,
        )
        assert r.quantity > 0


# ---------------------------------------------------------------------------
# assess_risk
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestAssessRisk:
    def test_approved_normal(self):
        rm = _make_rm(initial_balance=100_000.0)
        r = rm.assess_risk({"equity": 100_000.0}, [])
        assert r.can_trade is True

    def test_blocked_invalid_equity(self):
        rm = _make_rm(initial_balance=100_000.0)
        r = rm.assess_risk({"equity": 0.0}, [])
        assert r.can_trade is False

    def test_blocked_when_halted(self):
        rm = _make_rm(initial_balance=100_000.0)
        rm._halt = True
        rm._halt_reason = "test"
        r = rm.assess_risk({"equity": 100_000.0}, [])
        assert r.can_trade is False

    def test_blocked_max_drawdown(self):
        rm = _make_rm(initial_balance=100_000.0)
        rm._state.peak_equity = 100_000.0
        r = rm.assess_risk({"equity": 85_000.0}, [])
        assert r.can_trade is False

    def test_blocked_max_positions(self):
        rm = _make_rm(initial_balance=100_000.0)
        positions = [{"symbol": "X"}] * 10
        r = rm.assess_risk({"equity": 100_000.0}, positions)
        assert r.can_trade is False

    def test_uses_balance_key_fallback(self):
        rm = _make_rm(initial_balance=100_000.0)
        r = rm.assess_risk({"balance": 100_000.0}, [])
        assert r.can_trade is True


# ---------------------------------------------------------------------------
# check_modify_order
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestCheckModifyOrder:
    def test_allowed_within_limits(self):
        rm = _make_rm(initial_balance=100_000.0)
        rm._dd_tracker = None  # force fallback path
        allowed, reason = rm.check_modify_order(
            current_equity=100_000.0,
            new_stop_loss_distance=10.0,
            lots=0.1,
            account_balance=100_000.0,
            pip_value=10.0,
        )
        assert allowed is True

    def test_blocked_exceeds_limit(self):
        rm = _make_rm(initial_balance=100_000.0)
        rm._dd_tracker = None
        allowed, reason = rm.check_modify_order(
            current_equity=100_000.0,
            new_stop_loss_distance=1000.0,
            lots=100.0,
            account_balance=100_000.0,
            pip_value=10.0,
        )
        assert allowed is False


# ---------------------------------------------------------------------------
# get_drawdown_status
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestGetDrawdownStatus:
    def test_returns_dict_with_keys(self):
        rm = _make_rm(initial_balance=100_000.0)
        s = rm.get_drawdown_status()
        for k in ("total_hwm", "total_drawdown_pct", "daily_drawdown_pct",
                  "daily_realised_pnl", "total_breach", "daily_breach"):
            assert k in s

    def test_fallback_path_without_tracker(self):
        rm = _make_rm(initial_balance=100_000.0)
        rm._dd_tracker = None
        s = rm.get_drawdown_status()
        assert "total_drawdown_pct" in s


# ---------------------------------------------------------------------------
# Scaling factor helpers
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestScalingFactors:
    def test_quality_factor_at_min(self):
        rm = _make_rm()
        assert rm._quality_factor(0.40) == pytest.approx(0.5)

    def test_quality_factor_at_max(self):
        rm = _make_rm()
        assert rm._quality_factor(1.0) == pytest.approx(1.0)

    def test_sentiment_factor_zero_sentiment(self):
        rm = _make_rm()
        assert rm._sentiment_factor(0.0) == pytest.approx(1.0)

    def test_sentiment_factor_high_sentiment(self):
        rm = _make_rm()
        assert rm._sentiment_factor(1.0) < 1.0

    def test_impact_factor_zero(self):
        rm = _make_rm()
        assert rm._impact_factor(0.0) == pytest.approx(1.0)

    def test_impact_factor_high(self):
        rm = _make_rm()
        assert rm._impact_factor(1.0) < 1.0

    def test_drawdown_factor_no_drawdown(self):
        rm = _make_rm(initial_balance=100_000.0)
        assert rm._drawdown_factor() == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# Orchestrator accessors
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestOrchestratorAccessors:
    def test_get_current_gold_price_with_orch(self):
        orch = MagicMock()
        orch.get_current_gold_price.return_value = 1950.0
        rm = _make_rm(orchestrator=orch)
        assert rm.get_current_gold_price() == pytest.approx(1950.0)

    def test_get_current_gold_price_no_orch(self):
        rm = _make_rm()
        assert rm.get_current_gold_price() is None

    def test_get_current_gold_price_exception(self):
        orch = MagicMock()
        orch.get_current_gold_price.side_effect = RuntimeError("feed down")
        rm = _make_rm(orchestrator=orch)
        assert rm.get_current_gold_price() is None

    def test_get_macro_impact_score_with_orch(self):
        orch = MagicMock()
        orch.get_macro_impact_score.return_value = 0.65
        rm = _make_rm(orchestrator=orch)
        assert rm.get_macro_impact_score() == pytest.approx(0.65)

    def test_get_macro_impact_score_no_orch(self):
        rm = _make_rm()
        assert rm.get_macro_impact_score() == pytest.approx(0.0)

    def test_get_data_quality_from_orch(self):
        orch = MagicMock()
        orch.get_latest_tick.return_value = MagicMock(confidence=0.88)
        rm = _make_rm(orchestrator=orch)
        assert rm._get_data_quality(_signal()) == pytest.approx(0.88)

    def test_get_data_quality_fallback_to_signal(self):
        rm = _make_rm()
        assert rm._get_data_quality(_signal(data_quality=0.75)) == pytest.approx(0.75)

    def test_get_orchestrator_features_with_orch(self):
        orch = MagicMock()
        orch.get_ml_features.return_value = {"news_sentiment_score": 0.3}
        rm = _make_rm(orchestrator=orch)
        feats = rm._get_orchestrator_features(_signal())
        assert feats["news_sentiment_score"] == pytest.approx(0.3)

    def test_get_orchestrator_features_fallback(self):
        rm = _make_rm()
        sig = _signal(features={"macro_impact_score": 0.5})
        feats = rm._get_orchestrator_features(sig)
        assert feats.get("macro_impact_score") == pytest.approx(0.5)


# ---------------------------------------------------------------------------
# value_at_risk
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestValueAtRisk:
    def test_returns_zero_with_few_samples(self):
        rm = _make_rm(initial_balance=100_000.0)
        assert rm.value_at_risk() == pytest.approx(0.0)

    def test_returns_negative_with_losses(self):
        rm = _make_rm(initial_balance=100_000.0)
        for i in range(20):
            rm._pnl_history.append(-100.0 * (i + 1))
        assert rm.value_at_risk() < 0

    def test_returns_float(self):
        rm = _make_rm(initial_balance=100_000.0)
        for _ in range(15):
            rm._pnl_history.append(50.0)
        assert isinstance(rm.value_at_risk(), float)


# ---------------------------------------------------------------------------
# check_price_tolerance
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestCheckPriceTolerance:
    def test_within_tolerance_passes(self):
        rm = _make_rm()
        r = rm.check_price_tolerance({"price": 1950.0}, current_price=1951.0, tolerance=0.02)
        assert r.passed is True

    def test_exceeds_tolerance_fails(self):
        rm = _make_rm()
        r = rm.check_price_tolerance({"price": 2100.0}, current_price=1950.0, tolerance=0.02)
        assert r.passed is False

    def test_zero_reference_price_passes(self):
        rm = _make_rm()
        r = rm.check_price_tolerance({"price": 1950.0}, current_price=0.0)
        assert r.passed is True

    def test_object_order(self):
        rm = _make_rm()
        order = MagicMock()
        order.price = 1950.0
        r = rm.check_price_tolerance(order, current_price=1951.0, tolerance=0.02)
        assert r.passed is True


# ---------------------------------------------------------------------------
# _drawdown_risk_level
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestDrawdownRiskLevel:
    def test_low_at_zero_drawdown(self):
        from risk.manager import RiskLevel
        rm = _make_rm(initial_balance=100_000.0)
        assert rm._drawdown_risk_level() == RiskLevel.LOW

    def test_medium_at_mid_drawdown(self):
        from risk.manager import RiskLevel
        rm = _make_rm(initial_balance=100_000.0)
        rm._state.account_equity = 95_000.0
        rm._state.peak_equity = 100_000.0
        assert rm._drawdown_risk_level() in (RiskLevel.LOW, RiskLevel.MEDIUM)

    def test_high_near_limit(self):
        from risk.manager import RiskLevel
        rm = _make_rm(initial_balance=100_000.0)
        rm._state.account_equity = 91_500.0
        rm._state.peak_equity = 100_000.0
        assert rm._drawdown_risk_level() == RiskLevel.HIGH


# ---------------------------------------------------------------------------
# current_drawdown setter
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestCurrentDrawdownSetter:
    def test_setter_updates_state(self):
        rm = _make_rm(initial_balance=100_000.0)
        rm.current_drawdown = 0.05
        assert rm.current_drawdown == pytest.approx(0.05, abs=0.01)

    def test_setter_zero(self):
        rm = _make_rm(initial_balance=100_000.0)
        rm.current_drawdown = 0.0
        assert rm.current_drawdown == pytest.approx(0.0, abs=0.01)


# ---------------------------------------------------------------------------
# check_cvar_pre_trade
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestCheckCvarPreTrade:
    def test_passes_with_no_history(self):
        rm = _make_rm(initial_balance=100_000.0)
        ok, msg = rm.check_cvar_pre_trade()
        assert ok is True

    def test_returns_tuple(self):
        rm = _make_rm(initial_balance=100_000.0)
        result = rm.check_cvar_pre_trade()
        assert isinstance(result, tuple)
        assert len(result) == 2

    def test_blocked_when_halted(self):
        rm = _make_rm(initial_balance=100_000.0)
        rm._halt = True
        rm._halt_reason = "test"
        ok, msg = rm.check_cvar_pre_trade()
        assert ok is False

    def test_disabled_when_limit_zero(self):
        rm = _make_rm(initial_balance=100_000.0)
        rm._cvar_daily_limit = 0.0
        ok, msg = rm.check_cvar_pre_trade()
        assert ok is True

    def test_blocked_when_cvar_exceeds_limit(self):
        rm = _make_rm(initial_balance=100_000.0)
        rm._cvar_daily_limit = 0.001
        for _ in range(20):
            rm._returns_history.append(-0.05)
        ok, msg = rm.check_cvar_pre_trade()
        assert ok is False

    def test_record_return_appends(self):
        rm = _make_rm(initial_balance=100_000.0)
        rm.record_return(-100.0, 100_000.0)
        assert len(rm._returns_history) == 1


# ---------------------------------------------------------------------------
# factor_scale_size
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestFactorScaleSize:
    def _make_sizing(self):
        from risk.manager import PositionSizingResult
        return PositionSizingResult(
            symbol="XAU_USD", direction="long", quantity=1.0,
            notional_usd=1950.0, stop_loss_usd=1940.0,
            take_profit_usd=1970.0, risk_usd=10.0, lineage_id="x",
            kelly_f=0.25, quality_f=0.9, sentiment_f=0.9,
            impact_f=0.9, dd_f=1.0,
        )

    def test_returns_unchanged_when_no_engine(self):
        rm = _make_rm(initial_balance=100_000.0)
        sizing = self._make_sizing()
        result = rm.factor_scale_size(sizing, {"XAU_USD": 1.0})
        assert result.quantity == pytest.approx(1.0)

    def test_returns_unchanged_on_exception(self):
        rm = _make_rm(initial_balance=100_000.0)
        sizing = self._make_sizing()
        with patch("core.signal_engine._get_factor_engine", side_effect=RuntimeError("engine error")):
            result = rm.factor_scale_size(sizing, {})
        assert result.quantity == pytest.approx(1.0)

    def test_scales_down_when_ratio_exceeds_limit(self):
        rm = _make_rm(initial_balance=100_000.0)
        sizing = self._make_sizing()
        engine = MagicMock()
        engine.factor_var.return_value = {"XAU_USD": 0.9, "OTHER": 0.1}
        with patch("risk.manager.os.getenv", return_value="0.40"):
            with patch("core.signal_engine._get_factor_engine", return_value=engine):
                result = rm.factor_scale_size(sizing, {"XAU_USD": 1.0})
        # ratio = 0.9/1.0 = 0.90 > 0.40 → scale = 0.40/0.90 ≈ 0.44
        assert result.quantity < 1.0


# ---------------------------------------------------------------------------
# get_factor_risk_report
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestGetFactorRiskReport:
    def test_returns_dict(self):
        rm = _make_rm(initial_balance=100_000.0)
        r = rm.get_factor_risk_report({"XAU_USD": 1.0})
        assert isinstance(r, dict)
        assert "available" in r

    def test_returns_unavailable_on_exception(self):
        rm = _make_rm(initial_balance=100_000.0)
        with patch("core.signal_engine._get_factor_engine", side_effect=RuntimeError("err")):
            r = rm.get_factor_risk_report({})
        assert r["available"] is False


# ---------------------------------------------------------------------------
# _check_circuit_breakers
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestCheckCircuitBreakers:
    def test_no_action_when_already_halted(self):
        rm = _make_rm(initial_balance=100_000.0)
        rm._halt = True
        rm._halt_reason = "existing"
        rm._check_circuit_breakers(100_000.0)
        assert rm._halt_reason == "existing"

    def test_halts_on_max_drawdown(self):
        rm = _make_rm(initial_balance=100_000.0)
        # Drive drawdown through update_equity so dd_tracker stays in sync
        rm.update_equity(100_000.0)  # establish peak
        rm.update_equity(85_000.0)   # 15% drawdown > 10% limit
        assert rm._halt is True

    def test_amber_warning_at_60pct_threshold(self):
        rm = _make_rm(initial_balance=100_000.0)
        rm._halt = False
        rm._amber_warned = False
        # 60% of 10% = 6% → equity at 94k triggers amber
        rm.update_equity(100_000.0)
        rm._halt = False  # reset auto-halt from update_equity if triggered
        rm._amber_warned = False
        rm._state.peak_equity = 100_000.0
        rm._state.account_equity = 93_500.0
        if rm._dd_tracker:
            rm._dd_tracker._total_hwm = 100_000.0
            rm._dd_tracker._last_equity = 93_500.0
        rm._check_circuit_breakers(93_500.0)
        assert rm._amber_warned is True

    def test_amber_warning_not_repeated(self):
        rm = _make_rm(initial_balance=100_000.0)
        rm._state.peak_equity = 100_000.0
        rm._state.account_equity = 93_500.0
        rm._amber_warned = True  # already warned
        rm._check_circuit_breakers(93_500.0)
        # Should not raise or double-warn


# ---------------------------------------------------------------------------
# validate_trade
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestValidateTrade:
    def test_approved_normal(self):
        rm = _make_rm(initial_balance=100_000.0)
        ok, reason = rm.validate_trade("XAU_USD", quantity=100.0)
        assert ok is True

    def test_blocked_when_halted(self):
        rm = _make_rm(initial_balance=100_000.0)
        rm._halt = True
        rm._halt_reason = "test"
        ok, reason = rm.validate_trade("XAU_USD", quantity=100.0)
        assert ok is False

    def test_blocked_max_positions(self):
        rm = _make_rm(initial_balance=100_000.0)
        rm._state.open_positions = 10
        ok, reason = rm.validate_trade("XAU_USD", quantity=100.0)
        assert ok is False

    def test_blocked_size_too_large(self):
        rm = _make_rm(initial_balance=100_000.0)
        ok, reason = rm.validate_trade("XAU_USD", quantity=999_999_999.0)
        assert ok is False

    def test_blocked_zero_quantity(self):
        rm = _make_rm(initial_balance=100_000.0)
        ok, reason = rm.validate_trade("XAU_USD", quantity=0.0)
        assert ok is False

    def test_accepts_size_kwarg(self):
        rm = _make_rm(initial_balance=100_000.0)
        ok, reason = rm.validate_trade("XAU_USD", size=100.0)
        assert ok is True


# ---------------------------------------------------------------------------
# check_risk_limits
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestCheckRiskLimits:
    def test_within_limits(self):
        rm = _make_rm(initial_balance=100_000.0)
        ok, violations = rm.check_risk_limits()
        assert ok is True
        assert violations == []

    def test_violation_when_halted(self):
        rm = _make_rm(initial_balance=100_000.0)
        rm._halt = True
        rm._halt_reason = "test"
        ok, violations = rm.check_risk_limits()
        assert ok is False
        assert len(violations) > 0

    def test_violation_on_drawdown(self):
        rm = _make_rm(initial_balance=100_000.0)
        rm._state.peak_equity = 100_000.0
        rm._state.account_equity = 85_000.0
        ok, violations = rm.check_risk_limits()
        assert ok is False


# ---------------------------------------------------------------------------
# can_open_position
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestCanOpenPosition:
    def test_approved(self):
        rm = _make_rm(initial_balance=100_000.0)
        ok, reason = rm.can_open_position(100.0)
        assert ok is True

    def test_blocked_halted(self):
        rm = _make_rm(initial_balance=100_000.0)
        rm._halt = True
        rm._halt_reason = "test"
        ok, _ = rm.can_open_position(100.0)
        assert ok is False

    def test_blocked_max_positions(self):
        rm = _make_rm(initial_balance=100_000.0)
        rm._state.open_positions = 10
        ok, _ = rm.can_open_position(100.0)
        assert ok is False

    def test_blocked_size_too_large(self):
        rm = _make_rm(initial_balance=100_000.0)
        ok, _ = rm.can_open_position(999_999_999.0)
        assert ok is False

    def test_blocked_max_drawdown(self):
        rm = _make_rm(initial_balance=100_000.0)
        rm._state.peak_equity = 100_000.0
        rm._state.account_equity = 85_000.0
        ok, _ = rm.can_open_position(100.0)
        assert ok is False


# ---------------------------------------------------------------------------
# register_position / close_position
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestPositionRegistry:
    def test_register_position(self):
        rm = _make_rm(initial_balance=100_000.0)
        rm.register_position({"id": "p1", "symbol": "XAU_USD"})
        assert rm._state.open_positions == 1

    def test_close_position_removes_it(self):
        rm = _make_rm(initial_balance=100_000.0)
        rm.register_position({"id": "p1", "symbol": "XAU_USD"})
        rm.close_position("p1", pnl=100.0)
        assert rm._state.open_positions == 0

    def test_close_position_updates_pnl(self):
        rm = _make_rm(initial_balance=100_000.0)
        rm.register_position({"id": "p1", "symbol": "XAU_USD"})
        rm.close_position("p1", pnl=250.0)
        assert rm._state.daily_pnl == pytest.approx(250.0)


# ---------------------------------------------------------------------------
# metrics
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestMetrics:
    def test_metrics_shape(self):
        rm = _make_rm(initial_balance=100_000.0)
        m = rm.metrics()
        for k in ("account_equity", "peak_equity", "current_drawdown",
                  "daily_drawdown", "daily_pnl", "total_pnl",
                  "open_positions", "var_95", "halt", "halt_reason"):
            assert k in m

    def test_metrics_initial_values(self):
        rm = _make_rm(initial_balance=100_000.0)
        m = rm.metrics()
        assert m["halt"] is False
        assert m["open_positions"] == 0


# ---------------------------------------------------------------------------
# balance / equity property aliases
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestBalanceAliases:
    def test_current_balance_getter(self):
        rm = _make_rm(initial_balance=100_000.0)
        assert rm.current_balance == pytest.approx(100_000.0)

    def test_current_balance_setter(self):
        rm = _make_rm(initial_balance=100_000.0)
        rm.current_balance = 95_000.0
        assert rm._state.account_equity == pytest.approx(95_000.0)

    def test_peak_balance_getter(self):
        rm = _make_rm(initial_balance=100_000.0)
        assert rm.peak_balance == pytest.approx(100_000.0)

    def test_peak_balance_setter(self):
        rm = _make_rm(initial_balance=100_000.0)
        rm.peak_balance = 110_000.0
        assert rm._state.peak_equity == pytest.approx(110_000.0)

    def test_daily_pnl_getter(self):
        rm = _make_rm(initial_balance=100_000.0)
        rm._state.daily_pnl = 500.0
        assert rm.daily_pnl == pytest.approx(500.0)

    def test_daily_pnl_setter(self):
        rm = _make_rm(initial_balance=100_000.0)
        rm.daily_pnl = 300.0
        assert rm._state.daily_pnl == pytest.approx(300.0)

    def test_daily_trades_getter(self):
        rm = _make_rm(initial_balance=100_000.0)
        assert rm.daily_trades == 0

    def test_daily_trades_setter(self):
        rm = _make_rm(initial_balance=100_000.0)
        rm.daily_trades = 5
        assert rm._daily_trades == 5


# ---------------------------------------------------------------------------
# module-level singleton
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestRiskManagerSingleton:
    def test_singleton_exists(self):
        from risk.manager import risk_manager
        assert risk_manager is not None

    def test_singleton_is_risk_manager(self):
        from risk.manager import RiskManager, risk_manager
        assert isinstance(risk_manager, RiskManager)
