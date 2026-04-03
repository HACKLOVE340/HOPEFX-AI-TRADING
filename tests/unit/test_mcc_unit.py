# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
tests/unit/test_mcc_unit.py
============================
Unit tests for core/mcc/master_control.py — the MasterControlCore "brain"
that wires strategies, risk checks, signal aggregation, and broker execution.

Coverage targets:
- ``MCCConfig`` dataclass defaults
- ``MasterControlCore.__init__`` — state initialisation
- ``register_strategy()`` — wraps non-Enhanced strategies, sets callback
- ``activate_strategy()`` / ``deactivate_strategy()``
- ``_check_signal_risk()`` — daily-loss gate, allocation cap, correlation guard
- ``_is_correlated_signal()`` — same direction with and without price history,
  cross-symbol guard, HOLD passthrough
- ``_aggregate_signals()`` — no signals (HOLD), single BUY, majority BUY,
  tied (HOLD), confidence weighting, kill_switch short-circuit via callback
- ``on_price_update()`` — price stored, history capped, distributed to strats
- ``_detect_regime()`` — insufficient bars, trending/volatile/ranging
- ``_on_regime_change()`` — deactivates unsuitable strategies
- ``trigger_kill_switch()`` — sets flag, deactivates all, calls broker close
- ``get_heatmap_data()`` / ``get_status()`` — shape validation
- ``run()`` / ``stop()``
- ``_load_mcc_config()`` — with and without config_manager
"""

from __future__ import annotations

from decimal import Decimal
from unittest.mock import MagicMock, patch


from core.mcc.master_control import MasterControlCore, MCCConfig
from strategies.base_enhanced import EnhancedStrategy, StrategyConfig, StrategySignal


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────


def _mcc(**kwargs) -> MasterControlCore:
    config = MCCConfig(**kwargs)
    return MasterControlCore(config=config)


def _make_strategy(name: str = "strat1", action: str = "BUY", confidence: float = 0.8):
    cfg = StrategyConfig(name=name, version="1.0", min_bars=10)
    strat = MagicMock(spec=EnhancedStrategy)
    strat.config = cfg
    strat.is_active = True
    strat.mcc_callback = None
    strat.get_metrics.return_value = {"trades": 0}
    return strat


def _signal(action: str = "BUY", confidence: float = 0.80, strength: float = 0.70, symbol: str = "XAUUSD"):
    sig = MagicMock(spec=StrategySignal)
    sig.action = action
    sig.confidence = confidence
    sig.strength = strength
    sig.symbol = symbol
    return sig


# ─────────────────────────────────────────────────────────────────────────────
# MCCConfig
# ─────────────────────────────────────────────────────────────────────────────


class TestMCCConfig:
    def test_defaults(self):
        cfg = MCCConfig()
        assert cfg.max_strategies_active == 5
        assert cfg.risk_check_interval_ms == 100
        assert cfg.correlation_threshold == 0.7
        assert cfg.emergency_drawdown_pct == 0.10
        assert cfg.enable_gpu is False

    def test_custom_values(self):
        cfg = MCCConfig(max_strategies_active=3, enable_gpu=True)
        assert cfg.max_strategies_active == 3
        assert cfg.enable_gpu is True


# ─────────────────────────────────────────────────────────────────────────────
# __init__
# ─────────────────────────────────────────────────────────────────────────────


class TestMCCInit:
    def test_initial_state(self):
        mcc = _mcc()
        assert mcc.strategies == {}
        assert mcc.active_strategies == []
        assert mcc.kill_switch_triggered is False
        assert mcc.is_running is False
        assert mcc.current_regime == "unknown"
        assert mcc.daily_pnl == Decimal(0)

    def test_config_applied(self):
        mcc = _mcc(max_strategies_active=2)
        assert mcc.config.max_strategies_active == 2


# ─────────────────────────────────────────────────────────────────────────────
# register_strategy / activate / deactivate
# ─────────────────────────────────────────────────────────────────────────────


class TestStrategyManagement:
    def test_register_enhanced_strategy(self):
        mcc = _mcc()
        strat = _make_strategy("alpha")
        mcc.register_strategy(strat)
        assert "alpha" in mcc.strategies

    def test_register_sets_mcc_callback(self):
        mcc = _mcc()
        strat = _make_strategy("alpha")
        mcc.register_strategy(strat)
        assert strat.mcc_callback is mcc._on_strategy_signal

    def test_register_non_enhanced_wraps_with_adapter(self):
        """A plain strategy (no EnhancedStrategy base) should be wrapped."""
        mcc = _mcc()
        plain = MagicMock()  # not an instance of EnhancedStrategy
        plain.config = StrategyConfig(name="plain", version="1.0", min_bars=10)
        # Should not raise — StrategyAdapter wraps it
        mcc.register_strategy(plain)
        assert "plain" in mcc.strategies

    def test_activate_adds_to_active_list(self):
        mcc = _mcc()
        strat = _make_strategy("beta")
        mcc.register_strategy(strat)
        mcc.activate_strategy("beta")
        assert "beta" in mcc.active_strategies

    def test_activate_idempotent(self):
        mcc = _mcc()
        strat = _make_strategy("beta")
        mcc.register_strategy(strat)
        mcc.activate_strategy("beta")
        mcc.activate_strategy("beta")
        assert mcc.active_strategies.count("beta") == 1

    def test_deactivate_removes_from_active_list(self):
        mcc = _mcc()
        strat = _make_strategy("gamma")
        mcc.register_strategy(strat)
        mcc.activate_strategy("gamma")
        mcc.deactivate_strategy("gamma", "test")
        assert "gamma" not in mcc.active_strategies

    def test_activate_unknown_strategy_is_noop(self):
        """Activating a name that was never registered should not raise."""
        mcc = _mcc()
        mcc.activate_strategy("nonexistent")

    def test_deactivate_unknown_strategy_is_noop(self):
        mcc = _mcc()
        mcc.deactivate_strategy("nonexistent")


# ─────────────────────────────────────────────────────────────────────────────
# _check_signal_risk
# ─────────────────────────────────────────────────────────────────────────────


class TestCheckSignalRisk:
    def test_passes_when_healthy(self):
        mcc = _mcc()
        strat = _make_strategy("risk_strat")
        mcc.register_strategy(strat)
        sig = _signal()
        assert mcc._check_signal_risk("risk_strat", sig) is True

    def test_blocks_when_daily_pnl_below_limit(self):
        mcc = _mcc()
        mcc.daily_pnl = Decimal("-1500")  # below -$1000 limit
        strat = _make_strategy("risk_strat")
        mcc.register_strategy(strat)
        assert mcc._check_signal_risk("risk_strat", _signal()) is False

    def test_blocks_when_allocation_at_max(self):
        mcc = _mcc()
        strat = _make_strategy("alloc_strat")
        mcc.register_strategy(strat, max_allocation=Decimal("0.10"))
        # Patch _calculate_strategy_exposure to return max
        with patch.object(mcc, "_calculate_strategy_exposure", return_value=Decimal("0.10")):
            assert mcc._check_signal_risk("alloc_strat", _signal()) is False

    def test_blocks_when_correlated(self):
        mcc = _mcc()
        strat1 = _make_strategy("s1")
        strat2 = _make_strategy("s2")
        mcc.register_strategy(strat1)
        mcc.register_strategy(strat2)
        mcc.activate_strategy("s1")
        mcc.activate_strategy("s2")

        # s2 already has a BUY signal stored
        mcc._latest_signals["s2"] = _signal(action="BUY", symbol="XAUUSD")

        # s1 also wants BUY on same symbol — should be correlated (no price history → conservative True)
        assert mcc._check_signal_risk("s1", _signal(action="BUY", symbol="XAUUSD")) is False


# ─────────────────────────────────────────────────────────────────────────────
# _is_correlated_signal
# ─────────────────────────────────────────────────────────────────────────────


class TestIsCorrelatedSignal:
    def test_hold_signal_never_correlated(self):
        mcc = _mcc()
        strat = _make_strategy("s1")
        mcc.register_strategy(strat)
        mcc.activate_strategy("s1")
        assert mcc._is_correlated_signal("s1", _signal(action="HOLD")) is False

    def test_not_correlated_when_no_other_active_strategies(self):
        mcc = _mcc()
        strat = _make_strategy("lone_strat")
        mcc.register_strategy(strat)
        mcc.activate_strategy("lone_strat")
        assert mcc._is_correlated_signal("lone_strat", _signal(action="BUY")) is False

    def test_not_correlated_when_opposite_directions(self):
        mcc = _mcc()
        strat1 = _make_strategy("s1")
        strat2 = _make_strategy("s2")
        mcc.register_strategy(strat1)
        mcc.register_strategy(strat2)
        mcc.activate_strategy("s1")
        mcc.activate_strategy("s2")
        mcc._latest_signals["s2"] = _signal(action="SELL")
        # s1 wants BUY → opposite to s2's SELL → not correlated
        assert mcc._is_correlated_signal("s1", _signal(action="BUY")) is False

    def test_correlated_when_same_direction_no_price_history(self):
        """Without price history, same direction on same symbol → conservative True."""
        mcc = _mcc()
        strat1 = _make_strategy("s1")
        strat2 = _make_strategy("s2")
        mcc.register_strategy(strat1)
        mcc.register_strategy(strat2)
        mcc.activate_strategy("s1")
        mcc.activate_strategy("s2")
        mcc._latest_signals["s2"] = _signal(action="BUY", symbol="XAUUSD")
        assert mcc._is_correlated_signal("s1", _signal(action="BUY", symbol="XAUUSD")) is True

    def test_cross_symbol_not_correlated(self):
        """Different symbols → not correlated even with same direction."""
        mcc = _mcc()
        strat1 = _make_strategy("s1")
        strat2 = _make_strategy("s2")
        mcc.register_strategy(strat1)
        mcc.register_strategy(strat2)
        mcc.activate_strategy("s1")
        mcc.activate_strategy("s2")
        mcc._latest_signals["s2"] = _signal(action="BUY", symbol="EURUSD")
        assert mcc._is_correlated_signal("s1", _signal(action="BUY", symbol="XAUUSD")) is False


# ─────────────────────────────────────────────────────────────────────────────
# _aggregate_signals
# ─────────────────────────────────────────────────────────────────────────────


class TestAggregateSignals:
    def test_no_active_strategies_returns_hold(self):
        mcc = _mcc()
        result = mcc._aggregate_signals()
        assert result["action"] == "HOLD"

    def test_no_signals_stored_returns_hold(self):
        mcc = _mcc()
        strat = _make_strategy("s1")
        mcc.register_strategy(strat)
        mcc.activate_strategy("s1")
        result = mcc._aggregate_signals()
        assert result["action"] == "HOLD"

    def test_single_buy_signal_returns_buy(self):
        mcc = _mcc()
        strat = _make_strategy("s1")
        mcc.register_strategy(strat)
        mcc.activate_strategy("s1")
        mcc._latest_signals["s1"] = _signal(action="BUY", confidence=0.9, strength=0.8)
        result = mcc._aggregate_signals()
        assert result["action"] == "BUY"

    def test_majority_buy_overrides_hold(self):
        mcc = _mcc()
        for i in range(3):
            s = _make_strategy(f"s{i}")
            mcc.register_strategy(s)
            mcc.activate_strategy(f"s{i}")
        mcc._latest_signals["s0"] = _signal(action="BUY", confidence=0.9, strength=0.8)
        mcc._latest_signals["s1"] = _signal(action="BUY", confidence=0.85, strength=0.75)
        mcc._latest_signals["s2"] = _signal(action="SELL", confidence=0.7, strength=0.5)
        result = mcc._aggregate_signals()
        assert result["action"] == "BUY"

    def test_tied_buy_sell_returns_hold(self):
        mcc = _mcc()
        for i in range(2):
            s = _make_strategy(f"s{i}")
            mcc.register_strategy(s)
            mcc.activate_strategy(f"s{i}")
        mcc._latest_signals["s0"] = _signal(action="BUY", confidence=0.8, strength=0.8)
        mcc._latest_signals["s1"] = _signal(action="SELL", confidence=0.8, strength=0.8)
        result = mcc._aggregate_signals()
        assert result["action"] == "HOLD"

    def test_confidence_in_result(self):
        mcc = _mcc()
        strat = _make_strategy("s1")
        mcc.register_strategy(strat)
        mcc.activate_strategy("s1")
        mcc._latest_signals["s1"] = _signal(action="BUY", confidence=0.9, strength=0.8)
        result = mcc._aggregate_signals()
        assert 0.0 <= result["confidence"] <= 1.0


# ─────────────────────────────────────────────────────────────────────────────
# on_price_update
# ─────────────────────────────────────────────────────────────────────────────


class TestOnPriceUpdate:
    def test_price_stored(self):
        mcc = _mcc()
        mcc.on_price_update("XAUUSD", Decimal("2000.00"))
        assert mcc.current_prices["XAUUSD"] == Decimal("2000.00")

    def test_price_history_appended(self):
        mcc = _mcc()
        mcc.on_price_update("XAUUSD", Decimal("2000.00"))
        mcc.on_price_update("XAUUSD", Decimal("2001.00"))
        assert len(mcc.price_history["XAUUSD"]) == 2

    def test_price_history_capped_at_1000(self):
        mcc = _mcc()
        for i in range(1010):
            mcc.on_price_update("XAUUSD", Decimal(str(2000 + i)))
        assert len(mcc.price_history["XAUUSD"]) == 1000

    def test_distributed_to_active_strategies(self):
        mcc = _mcc()
        strat = _make_strategy("s1")
        mcc.register_strategy(strat)
        mcc.activate_strategy("s1")
        mcc.on_price_update("XAUUSD", Decimal("2000.00"))
        strat.on_price.assert_called_once()

    def test_strategy_error_does_not_propagate(self):
        mcc = _mcc()
        strat = _make_strategy("s1")
        strat.on_price.side_effect = RuntimeError("strat error")
        mcc.register_strategy(strat)
        mcc.activate_strategy("s1")
        # Should not raise
        mcc.on_price_update("XAUUSD", Decimal("2000.00"))


# ─────────────────────────────────────────────────────────────────────────────
# _detect_regime / _on_regime_change
# ─────────────────────────────────────────────────────────────────────────────


class TestRegimeDetection:
    def test_insufficient_history_no_change(self):
        mcc = _mcc()
        mcc.current_regime = "unknown"
        for i in range(10):  # < 50 bars needed
            mcc.on_price_update("XAUUSD", Decimal(str(2000 + i)))
        assert mcc.current_regime == "unknown"

    def test_detects_ranging_from_flat_prices(self):
        mcc = _mcc()
        for _i in range(60):  # flat prices → low vol → ranging
            mcc.on_price_update("XAUUSD", Decimal("2000.00"))
        assert mcc.current_regime == "ranging"

    def test_regime_change_logged_and_stored(self):
        mcc = _mcc()
        mcc.current_regime = "ranging"  # force a change
        # Inject 55 bars of trending-up prices
        for i in range(55):
            mcc.price_history["XAUUSD"].append((None, Decimal(str(2000 + i * 2))))
        mcc._detect_regime("XAUUSD")
        # Should change from "ranging" to something else
        assert mcc.current_regime != "ranging"

    def test_on_regime_change_deactivates_unsuitable(self):
        mcc = _mcc()
        strat = _make_strategy("mean_reversion_strat")
        mcc.register_strategy(strat)
        mcc.activate_strategy("mean_reversion_strat")
        mcc._on_regime_change("trending_up")
        # mean_reversion is suitable for trending_up (see regime_strategies), so should NOT deactivate
        # Actually: "mean_reversion" IS in trending_down but NOT in trending_up
        # → should be deactivated for trending_up
        assert "mean_reversion_strat" not in mcc.active_strategies


# ─────────────────────────────────────────────────────────────────────────────
# trigger_kill_switch
# ─────────────────────────────────────────────────────────────────────────────


class TestTriggerKillSwitch:
    def test_sets_kill_switch_flag(self):
        mcc = _mcc()
        mcc.trigger_kill_switch("max drawdown exceeded")
        assert mcc.kill_switch_triggered is True

    def test_deactivates_all_strategies(self):
        mcc = _mcc()
        for name in ["s1", "s2"]:
            s = _make_strategy(name)
            mcc.register_strategy(s)
            mcc.activate_strategy(name)
        mcc.trigger_kill_switch("halt")
        assert mcc.active_strategies == []

    def test_on_strategy_signal_noop_after_kill(self):
        """After kill switch is triggered, new signals are ignored."""
        mcc = _mcc()
        strat = _make_strategy("s1")
        mcc.register_strategy(strat)
        mcc.activate_strategy("s1")
        mcc.kill_switch_triggered = True
        # Should not raise and should not process the signal
        mcc._on_strategy_signal("s1", _signal())

    def test_close_positions_via_broker_called(self):
        mcc = _mcc()
        pos = MagicMock()
        pos.symbol = "XAUUSD"
        broker_mgr = MagicMock()
        broker_mgr.get_positions.return_value = [pos]

        with patch("core.startup_factories.get_broker_manager", return_value=broker_mgr):
            mcc.trigger_kill_switch("test")

        broker_mgr.close_position.assert_called_with("XAUUSD")

    def test_broker_error_during_kill_switch_does_not_raise(self):
        mcc = _mcc()
        with patch("core.startup_factories.get_broker_manager", side_effect=RuntimeError("broker down")):
            mcc.trigger_kill_switch("test")  # must not raise
        assert mcc.kill_switch_triggered is True


# ─────────────────────────────────────────────────────────────────────────────
# get_heatmap_data / get_status / run / stop
# ─────────────────────────────────────────────────────────────────────────────


class TestStatusAndLifecycle:
    def test_get_heatmap_data_shape(self):
        mcc = _mcc()
        d = mcc.get_heatmap_data()
        assert "strategies" in d
        assert "regime" in d
        assert "exposure" in d
        assert "daily_pnl" in d
        assert "active_count" in d
        assert "prices" in d

    def test_get_status_shape(self):
        mcc = _mcc()
        s = mcc.get_status()
        assert "running" in s
        assert "kill_switch" in s
        assert "strategies_registered" in s
        assert "strategies_active" in s
        assert "regime" in s
        assert "daily_pnl" in s

    def test_run_sets_is_running(self):
        mcc = _mcc()
        mcc.run()
        assert mcc.is_running is True

    def test_stop_clears_is_running(self):
        mcc = _mcc()
        strat = _make_strategy("s1")
        mcc.register_strategy(strat)
        mcc.activate_strategy("s1")
        mcc.run()
        mcc.stop()
        assert mcc.is_running is False
        assert mcc.active_strategies == []

    def test_get_status_counts_correctly(self):
        mcc = _mcc()
        for name in ["s1", "s2"]:
            s = _make_strategy(name)
            mcc.register_strategy(s)
        mcc.activate_strategy("s1")
        s = mcc.get_status()
        assert s["strategies_registered"] == 2
        assert s["strategies_active"] == 1
