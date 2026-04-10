# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""Tests for risk/stress_test.py — StressTester, StressScenario, run_all_scenarios."""

from __future__ import annotations

import pytest

from risk.stress_test import (
    SCENARIOS,
    StressResult,
    StressScenario,
    StressTester,
    run_all_scenarios,
)


class TestStressScenario:
    def test_scenarios_list_non_empty(self):
        assert len(SCENARIOS) >= 5

    def test_scenario_fields(self):
        s = SCENARIOS[0]
        assert isinstance(s.name, str)
        assert isinstance(s.gold_shock_pct, float)
        assert isinstance(s.description, str)

    def test_custom_scenario(self):
        s = StressScenario(
            name="TEST",
            description="test scenario",
            gold_shock_pct=-10.0,
            dxy_shock_pct=5.0,
        )
        assert s.name == "TEST"
        assert s.gold_shock_pct == pytest.approx(-10.0)


class TestStressTesterInit:
    def test_valid_init(self):
        t = StressTester(position_value=50_000.0, leverage=1.0, equity=100_000.0)
        assert t.position_value == pytest.approx(50_000.0)
        assert t.equity == pytest.approx(100_000.0)

    def test_negative_position_value_raises(self):
        with pytest.raises(ValueError):
            StressTester(position_value=-1.0)

    def test_zero_leverage_raises(self):
        with pytest.raises(ValueError):
            StressTester(position_value=1000.0, leverage=0.0)

    def test_equity_defaults_to_position_value(self):
        t = StressTester(position_value=10_000.0)
        assert t.equity == pytest.approx(10_000.0)

    def test_custom_scenarios(self):
        custom = [StressScenario("A", "desc", -5.0)]
        t = StressTester(position_value=1000.0, scenarios=custom)
        assert len(t.scenarios) == 1


class TestRunAll:
    def test_returns_all_scenarios(self):
        t = StressTester(position_value=10_000.0)
        results = t.run_all()
        assert len(results) == len(SCENARIOS)

    def test_sorted_worst_first(self):
        t = StressTester(position_value=10_000.0)
        results = t.run_all()
        pnls = [r.pnl_usd for r in results]
        assert pnls == sorted(pnls)

    def test_loss_scenario_negative_pnl(self):
        t = StressTester(position_value=10_000.0)
        results = t.run_all()
        # At least one scenario should produce a loss
        assert any(r.pnl_usd < 0 for r in results)

    def test_pnl_calculation(self):
        scenario = StressScenario("TEST", "test", gold_shock_pct=-10.0)
        t = StressTester(position_value=10_000.0, leverage=1.0, scenarios=[scenario])
        results = t.run_all()
        assert results[0].pnl_usd == pytest.approx(-1000.0)

    def test_leverage_amplifies_pnl(self):
        scenario = StressScenario("TEST", "test", gold_shock_pct=-10.0)
        t1 = StressTester(position_value=10_000.0, leverage=1.0, scenarios=[scenario])
        t2 = StressTester(position_value=10_000.0, leverage=2.0, scenarios=[scenario])
        r1 = t1.run_all()[0]
        r2 = t2.run_all()[0]
        assert r2.pnl_usd == pytest.approx(r1.pnl_usd * 2)


class TestWorstCase:
    def test_worst_case_is_largest_loss(self):
        t = StressTester(position_value=50_000.0, equity=100_000.0)
        results = t.run_all()
        worst = t.worst_case(results)
        assert worst.pnl_usd == min(r.pnl_usd for r in results)

    def test_worst_case_runs_scenarios_if_none(self):
        t = StressTester(position_value=50_000.0)
        worst = t.worst_case()
        assert isinstance(worst, StressResult)


class TestGateCheck:
    def test_gate_passes_small_position(self):
        # 1% of equity position — no scenario should breach 20% gate
        t = StressTester(position_value=1_000.0, equity=100_000.0, max_loss_pct=0.20)
        assert t.gate_check() is True

    def test_gate_fails_large_leveraged_position(self):
        # 100% equity, 10x leverage — GFC scenario (-30%) = -300% equity
        t = StressTester(position_value=100_000.0, leverage=10.0, equity=100_000.0, max_loss_pct=0.20)
        assert t.gate_check() is False

    def test_gate_check_with_override_equity(self):
        t = StressTester(position_value=1_000.0, equity=100_000.0)
        # Override equity to tiny value — should fail
        assert t.gate_check(equity=100.0, max_loss_pct=0.01) is False


class TestSummary:
    def test_summary_keys(self):
        t = StressTester(position_value=10_000.0, equity=100_000.0)
        s = t.summary()
        assert "position_value" in s
        assert "worst_case" in s
        assert "results" in s
        assert "gate_passed" in s

    def test_summary_results_count(self):
        t = StressTester(position_value=10_000.0)
        s = t.summary()
        assert s["scenarios_run"] == len(SCENARIOS)


class TestRunAllScenarios:
    def test_convenience_function(self):
        result = run_all_scenarios(position_value=5_000.0, equity=100_000.0)
        assert "worst_case" in result
        assert "results" in result
        assert result["position_value"] == pytest.approx(5_000.0)
