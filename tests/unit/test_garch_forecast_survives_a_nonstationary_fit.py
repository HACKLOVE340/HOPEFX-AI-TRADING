# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""`GARCHModel.forecast` must not crash or go silent on a non-stationary fit.

`simulate` and `forecast` compute the same unconditional variance,
`omega / (1 - alpha - beta)`. `simulate` floors the denominator at 1e-8.
`forecast` does not, and the two live in the same class.

`fit` cannot prevent the case. It optimises with L-BFGS-B under bounds
`[(1e-8, 1), (0, 1), (0, 1), (2.1, 30)]` — alpha and beta are each bounded to
[0, 1] and *their sum is not bounded at all*. Stationarity is only penalised
inside the likelihood, by returning 1e10, so a run that cannot improve off that
plateau returns a non-stationary pair. Nothing stops a caller assigning the
attributes either.

Measured before the fix:

    alpha + beta == 1   forecast -> ZeroDivisionError: float division by zero
    alpha + beta  > 1   forecast -> [nan nan nan]
    (simulate handled both, std ~13.7)

`MonteCarloRiskEngine.calculate_portfolio_risk` calls
`forecast(len(copula_sims))` for every asset, so the first case takes the whole
risk calculation down and the second scales every simulated return by NaN.

The fix is the floor `simulate` already applies, not a new decision: an
unconditional variance that large produces an enormous volatility, which for a
*risk* engine is the correct direction to fail in. A crash and a silent NaN are
not.
"""

from __future__ import annotations

import numpy as np
import pytest

from core.risk.advanced_engine import GARCHModel, MonteCarloRiskEngine

pytestmark = pytest.mark.unit


def _garch(alpha: float, beta: float) -> GARCHModel:
    model = GARCHModel()
    model.alpha, model.beta = alpha, beta
    return model


class TestForecastHandlesWhatSimulateAlreadyHandles:
    def test_a_stationary_fit_is_unchanged(self) -> None:
        """The defaults sum to 0.95. This pins that the fix does not move the
        ordinary case."""
        forecasts = _garch(0.1, 0.85).forecast(horizon=3)
        assert forecasts.shape == (3,)
        assert np.all(forecasts > 0)
        assert np.isfinite(forecasts).all()

    def test_alpha_plus_beta_of_exactly_one_does_not_raise(self) -> None:
        forecasts = _garch(0.5, 0.5).forecast(horizon=3)
        assert np.isfinite(forecasts).all()
        assert np.all(forecasts > 0)

    def test_alpha_plus_beta_above_one_is_not_silently_nan(self) -> None:
        """NaN volatility multiplies every simulated return into NaN, and
        `np.percentile` on NaN gives NaN — a VaR of nan reads as "no limit
        breached"."""
        forecasts = _garch(0.6, 0.5).forecast(horizon=3)
        assert np.isfinite(forecasts).all(), "forecast returned NaN volatility"

    def test_after_a_real_fit_it_does_not_forecast_zero_volatility(self) -> None:
        """The realistic path, and the quieter of the two failures.

        `fit` assigns `result.x`, so `omega` stops being a Python `float` and
        becomes `np.float64`. The same division then follows numpy's rules —
        `inf` rather than `ZeroDivisionError` — and `np.nan_to_num(posinf=0.0)`
        two lines later turns it into `0`. Measured on a fitted model with
        alpha = beta = 0.5: `forecast(3)` returns `[0. 0. 0.]` while `simulate`
        on the same parameters gives a std of 28.8.

        Which failure you get depends on whether the model has been fitted. A
        risk engine forecasting zero volatility is the one that costs money,
        because every VaR and CVaR downstream shrinks toward zero and no limit
        is ever breached.
        """
        rng = np.random.default_rng(5)
        model = GARCHModel()
        model.fit(rng.normal(0, 0.01, 300))
        assert not isinstance(model.omega, float) or isinstance(model.omega, np.floating), (
            "fit did not replace omega; this test is not exercising the numpy path"
        )
        model.alpha, model.beta = np.float64(0.5), np.float64(0.5)

        forecasts = model.forecast(horizon=3)

        assert np.isfinite(forecasts).all()
        assert np.all(forecasts > 0.0), f"forecast returned {forecasts} — zero volatility is not a forecast"

    def test_forecast_and_simulate_agree_about_the_same_parameters(self) -> None:
        """They compute the same quantity; they should not disagree about
        whether it is computable."""
        for alpha, beta in ((0.1, 0.85), (0.5, 0.5), (0.6, 0.5)):
            model = _garch(alpha, beta)
            forecast_ok = np.isfinite(model.forecast(horizon=2)).all()
            simulate_ok = np.isfinite(model.simulate(n_sims=20, horizon=2)).all()
            assert forecast_ok == simulate_ok, f"disagree at alpha={alpha}, beta={beta}"


class TestTheRiskCalculationSurvivesIt:
    def test_a_non_stationary_asset_does_not_take_down_the_portfolio_risk(self) -> None:
        """`calculate_portfolio_risk` calls `forecast` per asset.

        The copula is fitted explicitly here. `add_asset` does not do it, and
        without it `calculate_portfolio_risk` returns zero-risk metrics from its
        own guard — this test passed vacuously the first time for exactly that
        reason, never reaching `forecast` at all. See MASTER_OUTSTANDING A8.
        """
        rng = np.random.default_rng(20260911)
        engine = MonteCarloRiskEngine(n_sims=200)
        engine.add_asset("XAUUSD", rng.normal(0, 0.01, 300))
        engine.add_asset("EURUSD", rng.normal(0, 0.01, 300))
        engine.copula.fit(engine.historical_returns)
        assert engine.copula.marginals, "the copula is unfitted; this test would prove nothing"
        # Force the condition `fit` cannot rule out.
        engine.garch_models["XAUUSD"].alpha = 0.5
        engine.garch_models["XAUUSD"].beta = 0.5

        metrics = engine.calculate_portfolio_risk({"XAUUSD": 0.5, "EURUSD": 0.5})

        assert np.isfinite(metrics.var_95)
        assert np.isfinite(metrics.cvar_95)
        assert np.isfinite(metrics.volatility)
