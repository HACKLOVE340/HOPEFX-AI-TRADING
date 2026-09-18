# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""HOPEFX advanced risk engine — the package surface.

The implementation is `core/risk/advanced_engine.py`. This file re-exports it
and holds no code of its own.

## Why that sentence is worth writing down

The L-6 fix moved the GARCH/Monte-Carlo risk code out of
`core/acceleration/gpu_engine.py`. That module became a re-export shim,
correctly. This one did not: it kept a complete copy of all five classes, and
its header comment still read `# core/risk/advanced_engine.py` — a copy that
remembered where it came from.

A package's `__init__.py` *is* the package, so `from core.risk import
RealTimeRiskMonitor` resolved here, to the copy. Six fixes landed in
`advanced_engine.py` afterwards and none of them reached it. Measured with
`ast` + `difflib`, four of the five classes had drifted, strictly in one
direction — every line unique to this file was a line the module had
deliberately replaced:

* `update_portfolio` raised `KeyError` for a position whose symbol was missing
  from `prices`, and `ValueError` out of `np.random.multivariate_normal` for an
  empty portfolio or one worth zero. The module returns `[]` for all three.
* `_stress_correlation` averaged the correlation matrix *including* its 1.0
  diagonal, which for two assets returns `(1 + rho) / 2`. Two perfectly
  anti-correlated assets read as `0.0` rather than `-1.0`, and
  `correlation_stress` is a risk-limit input.
* `GARCHModel.simulate` divided by `1 - alpha - beta` with no floor. `fit`
  bounds alpha and beta to [0, 1] individually and only penalises their sum
  inside the likelihood, so a non-stationary pair is reachable; the division
  then gave `inf`, `np.nan_to_num(posinf=0.0)` turned it into `0`, and the
  first simulated step came out as *exactly zero volatility*. Measured: a
  per-step std of `[0.0, 0.00127, 0.00198, 0.00281]` where the module gives
  `[16.1, 19.0, 26.2, 20.6]`. A risk engine reporting no risk is worse than one
  that raises, because nothing downstream can tell.

No production module imported this surface — only tests — so the drift was
latent rather than live. It was still the public name, and the next caller to
write `from core.risk import ...` would have got all six defects.

`tests/unit/test_core_risk_exports_the_fixed_engine.py` holds this: it asserts
each exported class *is* the object from `advanced_engine`, and that this file
defines no classes at all. A behavioural test per defect only ever covers the
defects already known; identity covers the next one too.
"""

from core.risk.advanced_engine import (
    CopulaRiskModel,
    GARCHModel,
    MonteCarloRiskEngine,
    RealTimeRiskMonitor,
    RiskMetrics,
)

__all__ = [
    "CopulaRiskModel",
    "GARCHModel",
    "MonteCarloRiskEngine",
    "RealTimeRiskMonitor",
    "RiskMetrics",
]
