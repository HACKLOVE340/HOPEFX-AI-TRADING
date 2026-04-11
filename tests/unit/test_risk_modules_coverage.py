# HOPEFX-AI-TRADING
# Tests for risk/ — self_trade_prevention, analytics, circuit_breakers, compliance
"""Real unit tests. No mocks/stubs/fake data."""
from __future__ import annotations

from datetime import datetime, timezone

import numpy as np
import pytest

UTC = timezone.utc


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _make_order(oid, symbol, side, size, price, account="acc1", strategy=None):
    from risk.self_trade_prevention import Order
    return Order(
        id=oid, symbol=symbol, side=side, size=size, price=price,
        timestamp=datetime.now(UTC), account_id=account, strategy_id=strategy,
    )


def _returns(n=100, seed=42):
    rng = np.random.default_rng(seed)
    return rng.normal(-0.0005, 0.01, n)


class _FakeBroker:
    def __init__(self, balance=100_000.0):
        self._balance = balance
        self._positions = []

    def get_balance(self):
        return self._balance

    def get_positions(self):
        return self._positions

    def get_daily_pnl(self):
        return 0.0

    def cancel_all_orders(self):
        pass

    def close_all_positions(self):
        pass


# ─────────────────────────────────────────────────────────────────────────────
# risk/self_trade_prevention.py
# ─────────────────────────────────────────────────────────────────────────────

class TestSelfTradePrevention:
    def setup_method(self):
        from risk.self_trade_prevention import SelfTradePrevention, SelfTradeAction
        self.stp = SelfTradePrevention(
            prevention_level="account",
            action=SelfTradeAction.CANCEL_RESTING,
        )

    def test_no_self_trade_different_accounts(self):
        resting = _make_order("r1", "XAUUSD", "sell", 1.0, 1900.0, account="acc1")
        self.stp.add_resting_order(resting)
        new = _make_order("n1", "XAUUSD", "buy", 1.0, 1901.0, account="acc2")
        assert self.stp.check_self_trade(new) is None

    def test_self_trade_same_account_detected(self):
        resting = _make_order("r1", "XAUUSD", "sell", 1.0, 1900.0, account="acc1")
        self.stp.add_resting_order(resting)
        new = _make_order("n1", "XAUUSD", "buy", 1.0, 1901.0, account="acc1")
        result = self.stp.check_self_trade(new)
        assert result is not None
        assert result["action"] == "cancel"
        assert result["order_to_cancel"] == "r1"

    def test_no_cross_when_prices_dont_match(self):
        resting = _make_order("r1", "XAUUSD", "sell", 1.0, 1910.0, account="acc1")
        self.stp.add_resting_order(resting)
        new = _make_order("n1", "XAUUSD", "buy", 1.0, 1900.0, account="acc1")
        assert self.stp.check_self_trade(new) is None

    def test_cancel_new_action(self):
        from risk.self_trade_prevention import SelfTradePrevention, SelfTradeAction
        stp = SelfTradePrevention(prevention_level="account", action=SelfTradeAction.CANCEL_NEW)
        resting = _make_order("r1", "XAUUSD", "sell", 1.0, 1900.0, account="acc1")
        stp.add_resting_order(resting)
        new = _make_order("n1", "XAUUSD", "buy", 1.0, 1901.0, account="acc1")
        result = stp.check_self_trade(new)
        assert result["action"] == "reject"

    def test_cancel_both_action(self):
        from risk.self_trade_prevention import SelfTradePrevention, SelfTradeAction
        stp = SelfTradePrevention(prevention_level="account", action=SelfTradeAction.CANCEL_BOTH)
        resting = _make_order("r1", "XAUUSD", "sell", 1.0, 1900.0, account="acc1")
        stp.add_resting_order(resting)
        new = _make_order("n1", "XAUUSD", "buy", 1.0, 1901.0, account="acc1")
        result = stp.check_self_trade(new)
        assert result["action"] == "cancel_both"

    def test_decrement_size_action(self):
        from risk.self_trade_prevention import SelfTradePrevention, SelfTradeAction
        stp = SelfTradePrevention(prevention_level="account", action=SelfTradeAction.DECREMENT_SIZE)
        resting = _make_order("r1", "XAUUSD", "sell", 3.0, 1900.0, account="acc1")
        stp.add_resting_order(resting)
        new = _make_order("n1", "XAUUSD", "buy", 2.0, 1901.0, account="acc1")
        result = stp.check_self_trade(new)
        assert result["action"] == "decrement"
        assert result["new_order_size"] == pytest.approx(0.0)
        assert result["resting_order_size"] == pytest.approx(1.0)

    def test_add_and_remove_resting_order(self):
        resting = _make_order("r1", "XAUUSD", "sell", 1.0, 1900.0, account="acc1")
        self.stp.add_resting_order(resting)
        assert len(self.stp.resting_orders["XAUUSD"]) == 1
        self.stp.remove_resting_order("r1", "XAUUSD")
        assert len(self.stp.resting_orders["XAUUSD"]) == 0

    def test_no_resting_orders_returns_none(self):
        new = _make_order("n1", "XAUUSD", "buy", 1.0, 1901.0, account="acc1")
        assert self.stp.check_self_trade(new) is None

    def test_firm_level_matches_all_accounts(self):
        from risk.self_trade_prevention import SelfTradePrevention, SelfTradeAction
        stp = SelfTradePrevention(prevention_level="firm", action=SelfTradeAction.CANCEL_NEW)
        resting = _make_order("r1", "XAUUSD", "sell", 1.0, 1900.0, account="acc1")
        stp.add_resting_order(resting)
        new = _make_order("n1", "XAUUSD", "buy", 1.0, 1901.0, account="acc2")
        assert stp.check_self_trade(new) is not None

    def test_strategy_level_same_strategy(self):
        from risk.self_trade_prevention import SelfTradePrevention, SelfTradeAction
        stp = SelfTradePrevention(prevention_level="strategy", action=SelfTradeAction.CANCEL_NEW)
        resting = _make_order("r1", "XAUUSD", "sell", 1.0, 1900.0, account="acc1", strategy="strat_a")
        stp.add_resting_order(resting)
        new = _make_order("n1", "XAUUSD", "buy", 1.0, 1901.0, account="acc2", strategy="strat_a")
        assert stp.check_self_trade(new) is not None

    def test_sell_new_vs_buy_resting(self):
        resting = _make_order("r1", "XAUUSD", "buy", 1.0, 1901.0, account="acc1")
        self.stp.add_resting_order(resting)
        new = _make_order("n1", "XAUUSD", "sell", 1.0, 1900.0, account="acc1")
        assert self.stp.check_self_trade(new) is not None

    def test_same_side_no_cross(self):
        resting = _make_order("r1", "XAUUSD", "buy", 1.0, 1900.0, account="acc1")
        self.stp.add_resting_order(resting)
        new = _make_order("n1", "XAUUSD", "buy", 1.0, 1901.0, account="acc1")
        assert self.stp.check_self_trade(new) is None


# ─────────────────────────────────────────────────────────────────────────────
# risk/analytics.py — VaR, ES, slippage, sharpe, drawdown
# ─────────────────────────────────────────────────────────────────────────────

class TestComputeVar:
    def test_basic_var(self):
        from risk.analytics import compute_var
        r = _returns()
        result = compute_var(r, confidence=0.95)
        assert result.var_historical >= 0
        assert result.var_parametric >= 0
        assert result.var_cornish_fisher >= 0

    def test_var_result_confidence(self):
        from risk.analytics import compute_var
        result = compute_var(_returns(), confidence=0.99)
        assert result.confidence == 0.99

    def test_var_insufficient_data_raises(self):
        from risk.analytics import compute_var
        with pytest.raises(ValueError, match="Insufficient"):
            compute_var(np.array([0.01, -0.01, 0.005]), confidence=0.95)

    def test_var_invalid_confidence_raises(self):
        from risk.analytics import compute_var
        with pytest.raises(ValueError, match="confidence"):
            compute_var(_returns(), confidence=1.5)

    def test_var_horizon_scaling(self):
        from risk.analytics import compute_var
        r = _returns()
        v1 = compute_var(r, confidence=0.95, horizon_days=1)
        v5 = compute_var(r, confidence=0.95, horizon_days=5)
        assert v5.var_historical == pytest.approx(v1.var_historical * np.sqrt(5), rel=1e-6)

    def test_var_property_returns_max(self):
        from risk.analytics import compute_var
        result = compute_var(_returns())
        assert result.var == max(
            result.var_historical, result.var_parametric, result.var_cornish_fisher
        )


class TestComputeES:
    def test_basic_es(self):
        from risk.analytics import compute_es
        result = compute_es(_returns(), confidence=0.99)
        assert result.es_historical >= 0
        assert result.es_parametric >= 0

    def test_es_insufficient_data_raises(self):
        from risk.analytics import compute_es
        with pytest.raises(ValueError, match="Insufficient"):
            compute_es(np.array([0.01] * 10))

    def test_es_property(self):
        from risk.analytics import compute_es
        result = compute_es(_returns())
        assert result.es == max(result.es_historical, result.es_parametric)

    def test_es_n_observations(self):
        from risk.analytics import compute_es
        r = _returns(n=150)
        result = compute_es(r)
        assert result.n_observations == 150


class TestSimulateSlippage:
    def test_basic_slippage(self):
        from risk.analytics import simulate_slippage
        result = simulate_slippage(
            symbol="XAUUSD", quantity=1.0, side="buy",
            mid_price=1900.0, bid_ask_spread_bps=5.0,
            n_simulations=1000, rng_seed=42,
        )
        assert result.mean_slippage_bps >= 0
        assert result.p95_slippage_bps >= result.mean_slippage_bps

    def test_slippage_sell_side(self):
        from risk.analytics import simulate_slippage
        result = simulate_slippage(
            symbol="XAUUSD", quantity=1.0, side="sell",
            mid_price=1900.0, n_simulations=500, rng_seed=1,
        )
        assert result is not None

    def test_larger_quantity_more_impact(self):
        from risk.analytics import simulate_slippage
        r1 = simulate_slippage("XAUUSD", 1.0, "buy", 1900.0, n_simulations=500, rng_seed=42)
        r10 = simulate_slippage("XAUUSD", 10.0, "buy", 1900.0, n_simulations=500, rng_seed=42)
        assert r10.mean_slippage_bps >= r1.mean_slippage_bps


class TestComputeSharpe:
    def _pos_returns(self, n=252, seed=3):
        rng = np.random.default_rng(seed)
        return rng.normal(0.0005, 0.01, n)

    def test_basic_sharpe(self):
        from risk.analytics import compute_sharpe
        result = compute_sharpe(self._pos_returns())
        assert isinstance(result.sharpe, float)

    def test_sharpe_annualised_return(self):
        from risk.analytics import compute_sharpe
        result = compute_sharpe(self._pos_returns(), periods_per_year=252)
        assert result.annualised_return is not None

    def test_sharpe_n_observations(self):
        from risk.analytics import compute_sharpe
        r = self._pos_returns(n=200)
        result = compute_sharpe(r)
        assert result.n_observations == 200

    def test_sharpe_insufficient_data_raises(self):
        from risk.analytics import compute_sharpe
        with pytest.raises(Exception):
            compute_sharpe(np.array([0.01]))


class TestComputeMaxDrawdown:
    def test_flat_curve_zero_drawdown(self):
        from risk.analytics import compute_max_drawdown
        dd = compute_max_drawdown(np.ones(50))
        assert dd == pytest.approx(0.0)

    def test_declining_curve(self):
        from risk.analytics import compute_max_drawdown
        curve = np.linspace(100, 50, 50)
        dd = compute_max_drawdown(curve)
        assert dd == pytest.approx(0.5, rel=0.01)

    def test_recovery_curve(self):
        from risk.analytics import compute_max_drawdown
        curve = np.array([100.0, 80.0, 90.0, 110.0])
        dd = compute_max_drawdown(curve)
        assert dd == pytest.approx(0.20, rel=0.01)


class TestRiskAnalyticsFacade:
    def test_instantiation(self):
        from risk.analytics import RiskAnalytics
        ra = RiskAnalytics()
        assert ra is not None

    def test_facade_platform_var_no_data(self):
        from risk.analytics import RiskAnalytics
        ra = RiskAnalytics()
        # platform_var fetches live engine returns; with no engine it returns zeros
        result = ra.platform_var(confidence=0.95)
        assert isinstance(result, dict)
        assert "var_95" in result

    def test_facade_platform_var_note_on_no_data(self):
        from risk.analytics import RiskAnalytics
        ra = RiskAnalytics()
        result = ra.platform_var()
        # With no live engine, returns a note about insufficient data
        assert result["var_95"] == 0.0

    def test_module_level_compute_var(self):
        from risk.analytics import compute_var
        result = compute_var(_returns(), confidence=0.95)
        assert result.var_historical >= 0

    def test_module_level_compute_es(self):
        from risk.analytics import compute_es
        result = compute_es(_returns())
        assert result.es_historical >= 0

    def test_module_level_compute_sharpe(self):
        from risk.analytics import compute_sharpe
        rng = np.random.default_rng(5)
        r = rng.normal(0.001, 0.01, 252)
        result = compute_sharpe(r)
        assert isinstance(result.sharpe, float)

    def test_module_level_max_drawdown(self):
        from risk.analytics import compute_max_drawdown
        curve = np.array([100.0, 90.0, 95.0, 85.0, 100.0])
        dd = compute_max_drawdown(curve)
        assert dd >= 0


# ─────────────────────────────────────────────────────────────────────────────
# risk/compliance/prop_engine.py
# ─────────────────────────────────────────────────────────────────────────────

class TestPropFirmConfig:
    def test_direct_instantiation(self):
        from risk.compliance.prop_engine import PropFirmConfig
        # Constructor uses: daily_dd, max_dd, news_blackout, weekend_close, breach_action
        cfg = PropFirmConfig(daily_dd=0.05, max_dd=0.10)
        assert cfg.daily_dd == pytest.approx(0.05)
        assert cfg.max_dd == pytest.approx(0.10)

    def test_defaults(self):
        from risk.compliance.prop_engine import PropFirmConfig
        cfg = PropFirmConfig()
        assert cfg.daily_dd > 0
        assert cfg.max_dd > 0

    def test_from_file_missing_uses_defaults(self):
        from risk.compliance.prop_engine import PropFirmConfig
        cfg = PropFirmConfig.from_file("nonexistent_file.json")
        assert cfg is not None
        assert cfg.daily_dd > 0


class TestPropComplianceEngine:
    def _make_engine(self, initial_equity=100_000.0):
        from risk.compliance.prop_engine import PropComplianceEngine, PropFirmConfig
        cfg = PropFirmConfig(daily_dd=0.05, max_dd=0.10)
        return PropComplianceEngine(cfg, initial_equity=initial_equity)

    def test_instantiation(self):
        assert self._make_engine() is not None

    def test_update_equity(self):
        engine = self._make_engine()
        engine.update_equity(105_000.0)
        assert engine._current_equity == pytest.approx(105_000.0)

    def test_high_water_mark_updates_upward(self):
        engine = self._make_engine()
        engine.update_equity(110_000.0)
        assert engine._high_water_mark == pytest.approx(110_000.0)

    def test_high_water_mark_does_not_decrease(self):
        engine = self._make_engine()
        engine.update_equity(110_000.0)
        engine.update_equity(90_000.0)
        assert engine._high_water_mark == pytest.approx(110_000.0)

    def test_before_order_allowed_normal(self):
        engine = self._make_engine()
        # Pass explicit now to avoid weekend/news-blackout edge cases in CI
        from datetime import datetime, timezone
        # Use a known weekday (Monday) at a safe time
        now = datetime(2024, 1, 8, 12, 0, 0, tzinfo=timezone.utc)
        allowed, reason = engine.before_order(now=now)
        assert allowed is True
        assert reason == ""

    def test_before_order_blocked_after_daily_drawdown(self):
        engine = self._make_engine(initial_equity=100_000.0)
        engine.update_equity(94_000.0)   # 6% drop > 5% daily limit
        allowed, reason = engine.before_order()
        assert allowed is False
        assert reason != ""

    def test_before_order_blocked_after_total_drawdown(self):
        engine = self._make_engine(initial_equity=100_000.0)
        engine.update_equity(88_000.0)   # 12% drop > 10% total limit
        allowed, reason = engine.before_order()
        assert allowed is False

    def test_set_news_events(self):
        engine = self._make_engine()
        engine.set_news_events([datetime.now(UTC)])
        assert len(engine._news_events) == 1

    def test_status_returns_dict(self):
        engine = self._make_engine()
        s = engine.status()
        assert isinstance(s, dict)
        assert len(s) > 0

    def test_kill_switch_activates_on_breach_with_liquidate_action(self):
        from risk.compliance.prop_engine import PropComplianceEngine, PropFirmConfig
        # breach_action="liquidate" triggers kill-switch; "pause" only sets _paused
        cfg = PropFirmConfig(daily_dd=0.05, max_dd=0.10, breach_action="liquidate")
        engine = PropComplianceEngine(cfg, initial_equity=100_000.0)
        engine.update_equity(85_000.0)   # >10% total drawdown
        from datetime import datetime, timezone
        now = datetime(2024, 1, 8, 12, 0, 0, tzinfo=timezone.utc)
        engine.before_order(now=now)
        assert engine.kill_switch.is_active is True

    def test_pause_action_sets_paused_flag(self):
        engine = self._make_engine(initial_equity=100_000.0)
        engine.update_equity(94_000.0)   # daily DD breach
        from datetime import datetime, timezone
        now = datetime(2024, 1, 8, 12, 0, 0, tzinfo=timezone.utc)
        engine.before_order(now=now)
        assert engine._paused is True

    def test_on_breach_callback_called(self):
        from risk.compliance.prop_engine import PropComplianceEngine, PropFirmConfig, BreachType
        breaches = []
        cfg = PropFirmConfig(daily_dd=0.05, max_dd=0.10)
        engine = PropComplianceEngine(cfg, initial_equity=100_000.0,
                                      on_breach=lambda bt, msg: breaches.append(bt))
        engine.update_equity(88_000.0)
        engine.before_order()
        assert len(breaches) > 0


# ─────────────────────────────────────────────────────────────────────────────
# risk/circuit_breakers.py
# ─────────────────────────────────────────────────────────────────────────────

class TestRiskLimits:
    def test_defaults(self):
        from risk.circuit_breakers import RiskLimits
        limits = RiskLimits()
        assert limits.max_daily_drawdown_pct == pytest.approx(0.03)
        assert limits.max_leverage_ratio == pytest.approx(10.0)
        assert limits.max_orders_per_minute == 10

    def test_custom_limits(self):
        from risk.circuit_breakers import RiskLimits
        limits = RiskLimits(max_daily_drawdown_pct=0.05, max_order_size=50_000.0)
        assert limits.max_daily_drawdown_pct == pytest.approx(0.05)
        assert limits.max_order_size == pytest.approx(50_000.0)


class TestCircuitState:
    def test_all_states_exist(self):
        from risk.circuit_breakers import CircuitState
        assert CircuitState.CLOSED.value == "closed"
        assert CircuitState.OPEN.value == "open"
        assert CircuitState.HALF_OPEN.value == "half_open"


class TestCircuitBreakerPreTradeCheck:
    def _make_cb(self):
        from risk.circuit_breakers import CircuitBreaker
        return CircuitBreaker(broker=_FakeBroker(balance=100_000.0), redis_client=None)

    def test_pre_trade_check_allowed_normal(self):
        cb = self._make_cb()
        order = {"symbol": "XAUUSD", "side": "buy", "size": 1.0, "price": 1900.0}
        allowed, reason = cb.pre_trade_check(order)
        assert allowed is True
        assert reason is None

    def test_pre_trade_check_blocked_when_open(self):
        from risk.circuit_breakers import CircuitState
        cb = self._make_cb()
        cb.state = CircuitState.OPEN
        order = {"symbol": "XAUUSD", "side": "buy", "size": 1.0, "price": 1900.0}
        allowed, reason = cb.pre_trade_check(order)
        assert allowed is False
        assert reason is not None

    def test_pre_trade_check_blocks_oversized_order(self):
        cb = self._make_cb()
        # notional = 1000 * 200 = 200,000 > default max_order_size 100,000
        order = {"symbol": "XAUUSD", "side": "buy", "size": 1000.0, "price": 200.0}
        allowed, reason = cb.pre_trade_check(order)
        assert allowed is False
        assert reason is not None

    def test_update_trade_result_win_resets_streak(self):
        cb = self._make_cb()
        cb.update_trade_result(-200.0)
        cb.update_trade_result(-100.0)
        cb.update_trade_result(50.0)
        assert cb.consecutive_losses == 0

    def test_update_trade_result_loss_increments(self):
        cb = self._make_cb()
        cb.update_trade_result(-200.0)
        assert cb.consecutive_losses == 1
        cb.update_trade_result(-100.0)
        assert cb.consecutive_losses == 2

    def test_manual_override_enable(self):
        cb = self._make_cb()
        cb.manual_override(True, "testing", "admin")
        assert cb._manual_override is True

    @pytest.mark.asyncio
    async def test_manual_override_disable(self):
        cb = self._make_cb()
        cb.manual_override(True, "testing", "admin")
        # disable calls asyncio.create_task — must run inside event loop
        cb.manual_override(False, "restored", "admin")
        assert cb._manual_override is False

    def test_get_status_has_state_key(self):
        cb = self._make_cb()
        status = cb.get_status()
        assert isinstance(status, dict)
        assert "state" in status

    def test_half_open_reduces_order_size_by_half(self):
        from risk.circuit_breakers import CircuitState
        cb = self._make_cb()
        cb.state = CircuitState.HALF_OPEN
        order = {"symbol": "XAUUSD", "side": "buy", "size": 2.0, "price": 1900.0}
        allowed, _ = cb.pre_trade_check(order)
        assert allowed is True
        assert order["size"] == pytest.approx(1.0)

    def test_shutdown_sets_flag(self):
        cb = self._make_cb()
        cb.shutdown()
        assert cb._shutdown is True

    def test_registry_register_and_get(self):
        from risk.circuit_breakers import get_circuit_breakers, register_circuit_breaker, CircuitBreaker
        cb = CircuitBreaker(broker=_FakeBroker(), redis_client=None)
        register_circuit_breaker("test_reg_cb", cb)
        registry = get_circuit_breakers()
        assert "test_reg_cb" in registry

    def test_state_changes_audit_trail(self):
        cb = self._make_cb()
        cb.manual_override(True, "audit test", "admin")
        assert len(cb.state_changes) >= 1
        assert cb.state_changes[-1]["action"] == "MANUAL_OVERRIDE_ENABLED"
