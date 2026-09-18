# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""The one definition of the Sortino denominator.

Six modules computed a Sortino ratio and five of them disagreed. F120 replaced
``returns[returns < 0].std()`` with the textbook downside deviation in
``backtesting/engine_config.py``, and ``backtesting/metrics.py`` was pointed at
that fix — but ``analytics/performance.py``, ``backtesting/enhanced_engine.py``,
``backtesting/engine.py``, ``risk/advanced_analytics.py`` and two blocks in
``api/trading.py`` were left computing their own. A fix that lives inside one
engine is a fix five other call sites cannot reach, so the definition lives
here, in a leaf module with no HOPEFX imports, and every site calls it.

Why the old form is not merely imprecise
----------------------------------------
``std(returns[returns < 0])`` measures the dispersion *among the losses*, about
the *mean loss*, over *only the losing periods*: a different centre, a different
N and a different statistic from the shortfall below a target over all periods.
The bias flips sign with the shape of the distribution — measured at 1.13x high
on symmetric returns and 0.71x low on the negatively skewed shape strategies
actually produce — so the reported figure was not a biased Sortino, it was not
Sortino.

The failure is starkest where it matters most. A strategy whose losses are all
the same size has zero dispersion among them, so the old denominator is zero and
the ratio is ``+inf``: the metric reports flawless risk-adjusted performance for
exactly the return series a downside measure exists to penalise.
"""

from __future__ import annotations

import numpy as np
from numpy.typing import ArrayLike

__all__ = ["downside_deviation"]


def downside_deviation(returns: ArrayLike, target: float = 0.0) -> float:
    """Root-mean-square shortfall below *target*, taken over ALL periods.

    This is the Sortino denominator. Periods at or above *target* contribute a
    shortfall of zero — they are counted in N, which is what makes this a
    deviation of the series rather than a dispersion of its losses.

    Non-finite observations are dropped rather than zero-filled: a bar with no
    return is an absent observation, and counting it as a zero shortfall would
    understate the downside over a series with gaps. Callers that need the mean
    return in the numerator must drop the same observations, or the two sides of
    the ratio are taken over different periods.

    Returns ``0.0`` for an empty series and for one with no shortfall at all;
    callers decide what an undefined ratio should be, since ``inf`` does not
    survive JSON serialisation or a numeric database column.
    """
    arr = np.asarray(returns, dtype=float)
    arr = arr[np.isfinite(arr)]
    if arr.size == 0:
        return 0.0
    return float(np.sqrt(np.mean(np.minimum(arr - target, 0.0) ** 2)))
