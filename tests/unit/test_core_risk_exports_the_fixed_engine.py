# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""`core/risk/__init__.py` must not ship a stale copy of the risk engine.

The L-6 fix moved the GARCH/Monte-Carlo risk code out of
`core/acceleration/gpu_engine.py` and into `core/risk/advanced_engine.py`.
`gpu_engine.py` became a re-export shim, correctly. `core/risk/__init__.py` did
not: it kept a full copy of all five classes, and its own header comment still
reads `# core/risk/advanced_engine.py`.

A package's `__init__.py` *is* the package, so `from core.risk import
RealTimeRiskMonitor` resolves to the copy — and the copy never received any of
the fixes the module has had since. Measured with `ast` + `difflib`: four of the
five classes differ, and the drift is strictly one-directional. Every line
unique to `core/risk/__init__.py` is a line `advanced_engine.py` deliberately
replaced, each one a documented defect:

* `update_portfolio` — no guard for empty positions, for a symbol missing from
  `prices`, or for a zero total value;
* `_stress_correlation` — averages the full correlation matrix including the
  1.0 diagonal, which for two assets returns (1 + rho)/2 instead of rho and
  causes false risk-limit breaches;
* `GARCHModel.simulate` — divides by `1 - alpha - beta` with no floor, and at
  t=0 reads `simulated[:, t - 1]`, which is `simulated[:, -1]`: the last column,
  all zeros at initialisation.

These tests run against the package surface, which is what a caller gets.
The last one is the structural guarantee: the package must *be* the module, not
resemble it.
"""

from __future__ import annotations

from decimal import Decimal

import numpy as np
import pandas as pd
import pytest

import core.risk as package
import core.risk.advanced_engine as module

pytestmark = pytest.mark.unit


def _monitor():
    return package.RealTimeRiskMonitor(package.MonteCarloRiskEngine(n_sims=10))


class TestUpdatePortfolioRefusesRatherThanRaising:
    """A risk monitor that raises is a risk monitor that stops monitoring."""

    def test_no_positions_is_no_violations(self) -> None:
        assert _monitor().update_portfolio({}, {}) == []

    def test_a_symbol_with_no_price_is_skipped(self) -> None:
        monitor = _monitor()
        assert monitor.update_portfolio({"XAUUSD": Decimal("1")}, {"EURUSD": Decimal("2000")}) == []

    def test_a_portfolio_worth_nothing_is_no_violations(self) -> None:
        monitor = _monitor()
        assert monitor.update_portfolio({"XAUUSD": Decimal("1")}, {"XAUUSD": Decimal("0")}) == []


class TestStressCorrelationExcludesTheDiagonal:
    """Averaging the 1.0 diagonal turns rho into (1 + rho)/2 for two assets.

    The first version of this test used independent series and asserted the
    result was below 0.45. It passed against the buggy copy — conditioning on
    the worst 5% of summed returns induces negative correlation, so the stale
    form returned 0.18 and the assertion was satisfied by a defect it was
    written to catch. Measured on the same data: stale +0.1795, fixed -0.6410.

    The discriminating case is the one where (1 + rho)/2 has a fixed point that
    is obviously wrong.
    """

    def test_perfectly_anticorrelated_assets_do_not_read_as_uncorrelated(self) -> None:
        """rho = -1 maps to (1 + -1)/2 = 0 exactly. The stale copy reports two
        assets that move perfectly opposite as having no stress correlation at
        all — and `correlation_stress` feeds the risk limits."""
        rng = np.random.default_rng(4)
        base = rng.normal(0, 0.01, 500)
        frame = pd.DataFrame({"A": base, "B": -base})

        engine = package.MonteCarloRiskEngine(n_sims=10)
        engine.historical_returns = frame

        stress = engine._stress_correlation({"A": 0.5, "B": 0.5})

        assert stress == pytest.approx(-1.0, abs=1e-9), (
            f"reads {stress:+.4f}; perfectly anti-correlated assets must read -1, and (1 + rho)/2 maps -1 to 0"
        )

    def test_perfectly_correlated_assets_still_read_as_one(self) -> None:
        """The fixed point the bug shares with the correct answer, so this
        passes either way — it is here to show the fix did not invert anything."""
        rng = np.random.default_rng(3)
        base = rng.normal(0, 0.01, 500)
        engine = package.MonteCarloRiskEngine(n_sims=10)
        engine.historical_returns = pd.DataFrame({"A": base, "B": base})

        assert engine._stress_correlation({"A": 0.5, "B": 0.5}) == pytest.approx(1.0, abs=1e-9)


class TestGarchSimulateSurvivesANonStationaryFit:
    """`fit` bounds alpha and beta to [0, 1] individually and only penalises
    their sum inside the likelihood, so an optimiser can return a pair summing
    to 1. The stale copy then computes `omega / (1 - alpha - beta)` with no
    floor; the result is `inf`, `np.nan_to_num(posinf=0.0)` turns it into 0, and
    the first simulated step comes out as exactly zero volatility.

    The first version of this test asserted the output was finite. It passed
    against the buggy copy, because the bug does not produce infinities — it
    produces silence. A risk engine reporting zero dispersion is worse than one
    that raises.
    """

    def test_the_first_step_is_not_a_column_of_zeros(self) -> None:
        garch = package.GARCHModel()
        garch.alpha, garch.beta = 0.5, 0.5

        simulated = garch.simulate(n_sims=500, horizon=4)

        assert simulated.shape == (500, 4)
        assert not np.all(simulated[:, 0] == 0.0), (
            "the first forecast step has exactly zero volatility: omega / (1 - alpha - beta) overflowed and was zeroed"
        )
        assert simulated[:, 0].std() > 0.0

    def test_a_stationary_fit_is_unaffected(self) -> None:
        """The defaults sum to 0.95, and both copies handle them. Here so the
        test above is known to be about non-stationarity and not about
        `simulate` in general."""
        garch = package.GARCHModel()
        simulated = garch.simulate(n_sims=500, horizon=3)
        assert simulated[:, 0].std() > 0.0


class TestThePackageIsTheModule:
    """The guarantee that stops this drifting again.

    Six fixes reached `advanced_engine.py` and none reached the copy. Asserting
    the classes are the same objects is the only form of this that cannot rot:
    a behavioural test per defect only ever covers the defects already known.
    """

    @pytest.mark.parametrize(
        "name",
        ["RiskMetrics", "GARCHModel", "CopulaRiskModel", "MonteCarloRiskEngine", "RealTimeRiskMonitor"],
    )
    def test_each_public_class_is_the_one_from_advanced_engine(self, name: str) -> None:
        assert getattr(package, name) is getattr(module, name), (
            f"core.risk.{name} is a different object from core.risk.advanced_engine.{name} — "
            "the package is shipping its own copy again"
        )

    def test_the_package_defines_no_classes_of_its_own(self) -> None:
        """`core/risk/__init__.py` held 285 lines that were nothing but a stale
        duplicate of `advanced_engine.py`. A re-export is what a package that
        re-exports should contain."""
        import ast
        import pathlib

        source = pathlib.Path(package.__file__).read_text()
        defined = [n.name for n in ast.parse(source).body if isinstance(n, ast.ClassDef)]
        assert defined == [], f"core/risk/__init__.py defines {defined} instead of re-exporting them"
