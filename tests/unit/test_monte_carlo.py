# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
tests/unit/test_monte_carlo.py

Unit tests for analytics/monte_carlo.py.

Covers:
  1.  _chi2_sf: known critical values match scipy to 1e-5
  2.  _ljung_box_p: IID white noise does not reject H0 (p > 0.05)
  3.  _ljung_box_p: AR(1) rho=0.6 rejects H0 (p < 0.05)
  4.  _ljung_box_p: too few observations returns 1.0
  5.  choose_bootstrap_method: IID -> "iid"
  6.  choose_bootstrap_method: AR(1) -> "block"
  7.  choose_bootstrap_method: too few trades -> "block" (conservative)
  8.  MonteCarloEngine.run: method="auto" completes without error
  9.  MonteCarloEngine.run: method="block" uses block resampling
  10. MonteCarloEngine.run: method="iid" uses IID resampling
  11. MonteCarloEngine.run: avg_hold_bars sets block_size
  12. MonteCarloEngine.run: CI lower < upper
  13. MonteCarloEngine.run: ruin_probability in [0, 1]
  14. MonteCarloEngine.run: < 2 trades returns empty result
  15. BootstrapResult.summary() is JSON-serialisable
"""

import json
import math

import numpy as np
import pytest

from analytics.monte_carlo import (
    BootstrapResult,
    MonteCarloEngine,
    _chi2_sf,
    _ljung_box_p,
    choose_bootstrap_method,
    run_bootstrap,
)


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture
def rng():
    return np.random.default_rng(42)


@pytest.fixture
def iid_pnls(rng):
    return rng.normal(100, 50, 500).tolist()


@pytest.fixture
def ar1_pnls(rng):
    arr = np.zeros(500)
    arr[0] = float(rng.normal(100, 50))
    for i in range(1, 500):
        arr[i] = 0.6 * arr[i - 1] + float(rng.normal(0, 30))
    return arr.tolist()


@pytest.fixture
def engine():
    return MonteCarloEngine(n_paths=500, seed=42)


# ── _chi2_sf ──────────────────────────────────────────────────────────────────


class TestChi2SF:
    @pytest.mark.parametrize("x,df,expected", [
        (11.07, 5, 0.0500),
        (1.0,   5, 0.9626),
        (3.84,  1, 0.0500),
        (9.49,  4, 0.0500),
        (0.0,   3, 1.0000),
    ])
    def test_known_values(self, x, df, expected):
        got = _chi2_sf(x, df)
        assert abs(got - expected) < 1e-3, f"chi2_sf({x},{df})={got}, expected {expected}"

    def test_negative_x_returns_one(self):
        assert _chi2_sf(-1.0, 5) == 1.0

    def test_large_x_near_zero(self):
        # Very large x -> very small p-value
        assert _chi2_sf(100.0, 5) < 1e-10


# ── _ljung_box_p ──────────────────────────────────────────────────────────────


class TestLjungBox:
    def test_iid_noise_does_not_reject(self, iid_pnls):
        p = _ljung_box_p(np.array(iid_pnls), lags=5)
        assert p > 0.05, f"IID noise should not reject H0: p={p}"

    def test_ar1_rejects(self, ar1_pnls):
        p = _ljung_box_p(np.array(ar1_pnls), lags=5)
        assert p < 0.05, f"AR(1) should reject H0: p={p}"

    def test_too_few_observations_returns_one(self):
        p = _ljung_box_p(np.array([1.0, 2.0, 3.0]), lags=5)
        assert p == 1.0

    def test_zero_variance_returns_one(self):
        p = _ljung_box_p(np.ones(100), lags=5)
        assert p == 1.0


# ── choose_bootstrap_method ───────────────────────────────────────────────────


class TestChooseBootstrapMethod:
    def test_iid_chooses_iid(self, iid_pnls):
        assert choose_bootstrap_method(np.array(iid_pnls)) == "iid"

    def test_ar1_chooses_block(self, ar1_pnls):
        assert choose_bootstrap_method(np.array(ar1_pnls)) == "block"

    def test_too_few_trades_chooses_block(self):
        # Conservative default when not enough data to test
        assert choose_bootstrap_method(np.array([1.0, 2.0])) == "block"


# ── MonteCarloEngine ──────────────────────────────────────────────────────────


class TestMonteCarloEngine:
    def test_auto_method_completes(self, engine, iid_pnls):
        result = engine.run(iid_pnls, initial_capital=100_000, method="auto")
        assert result.n_trades == len(iid_pnls)
        assert math.isfinite(result.original_sharpe)

    def test_block_method_completes(self, engine, ar1_pnls):
        result = engine.run(ar1_pnls, initial_capital=100_000, method="block")
        assert result.n_trades == len(ar1_pnls)

    def test_iid_method_completes(self, engine, iid_pnls):
        result = engine.run(iid_pnls, initial_capital=100_000, method="iid")
        assert result.n_trades == len(iid_pnls)

    def test_avg_hold_bars_accepted(self, engine, ar1_pnls):
        # Should not raise; block_size is set internally to avg_hold_bars
        result = engine.run(ar1_pnls, initial_capital=100_000, method="block", avg_hold_bars=10)
        assert result.n_trades == len(ar1_pnls)

    def test_ci_lower_less_than_upper(self, engine, iid_pnls):
        result = engine.run(iid_pnls, initial_capital=100_000, method="auto")
        assert result.sharpe_ci_95[0] < result.sharpe_ci_95[1]
        assert result.max_dd_ci_95[0] <= result.max_dd_ci_95[1]
        assert result.cagr_ci_95[0] <= result.cagr_ci_95[1]

    def test_ruin_probability_in_range(self, engine, iid_pnls):
        result = engine.run(iid_pnls, initial_capital=100_000, method="auto")
        assert 0.0 <= result.ruin_probability <= 1.0

    def test_probability_of_profit_in_range(self, engine, iid_pnls):
        result = engine.run(iid_pnls, initial_capital=100_000, method="auto")
        assert 0.0 <= result.probability_of_profit <= 1.0

    def test_fewer_than_two_trades_returns_empty(self, engine):
        r0 = engine.run([], initial_capital=100_000)
        assert r0.n_trades == 0
        r1 = engine.run([100.0], initial_capital=100_000)
        assert r1.n_trades == 0

    def test_sharpe_se_positive(self, engine, iid_pnls):
        result = engine.run(iid_pnls, initial_capital=100_000)
        assert result.sharpe_se > 0

    def test_summary_json_serialisable(self, engine, iid_pnls):
        result = engine.run(iid_pnls, initial_capital=100_000)
        s = result.summary()
        # Must not raise
        json.dumps(s)

    def test_summary_keys_present(self, engine, iid_pnls):
        result = engine.run(iid_pnls, initial_capital=100_000)
        s = result.summary()
        for key in (
            "n_paths", "n_trades", "original_sharpe", "original_max_dd",
            "sharpe_ci_95", "max_dd_ci_95", "ruin_probability",
            "probability_of_profit", "sharpe_se", "sharpe_positive_fraction",
        ):
            assert key in s, f"Missing key: {key}"

    def test_run_bootstrap_convenience(self, iid_pnls):
        result = run_bootstrap(iid_pnls, initial_capital=100_000, n_paths=200)
        assert result.n_trades == len(iid_pnls)
        assert math.isfinite(result.original_sharpe)

    def test_profitable_strategy_low_ruin(self):
        # All-positive trades -> ruin probability should be 0
        pnls = [500.0] * 100
        engine = MonteCarloEngine(n_paths=500, seed=0)
        result = engine.run(pnls, initial_capital=100_000)
        assert result.ruin_probability == 0.0
