# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
The regime badge's EMA is folded backwards.

`api/trading.py` computes the EMAs behind the regime badge and its confidence
figure (AIChart.tsx) like this:

    ema20 = closes[-1]
    for c in reversed(closes[-20:]):
        ema20 = ema20 * 0.9 + c * 0.1

`reversed()` walks the window newest -> oldest, and in this recurrence the value
folded in LAST carries the full 0.1 coefficient while each earlier one decays by
0.9. The weighting is inverted end to end. Measured by replicating the loop
(F125):

    weight on the NEWEST bar (folded first) : 0.01351
    weight on the OLDEST bar (folded last)  : 0.10000
    -> the oldest bar carries 7.4x the weight of the newest

    rising series,  last close 3295:  code 3238.92   correct EMA20 3254.59
    falling series, last close 2705:  code 2761.08   correct EMA20 2745.41

To be precise about the impact: the *classification* is not reversed — the code
EMA still sits below price in an uptrend, so `ema_spread > 0.005` still reads
"up". What is wrong is responsiveness: the indicator is dominated by the oldest
bar in its window, so it lags far more than a 20-period EMA should, and the
`confidence` derived from `ema_spread` is computed from a spread that is not the
spread between a 20- and a 50-period EMA. Both numbers are shown to the trader.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.unit


def _reference_ema(values, alpha):
    """A textbook EMA: seed on the oldest value, fold forward."""
    ema = values[0]
    for v in values[1:]:
        ema = ema * (1 - alpha) + v * alpha
    return ema


def test_the_helper_matches_a_hand_computed_ema():
    from api.trading import _ema

    # alpha 0.5 makes the arithmetic checkable by eye:
    #   seed 10 -> (10+20)/2 = 15 -> (15+30)/2 = 22.5
    assert _ema([10.0, 20.0, 30.0], 0.5) == pytest.approx(22.5)


def _bar_weights(ema_fn, n: int, alpha: float) -> list[float]:
    """Weight the EMA gives each bar, measured by bumping one bar at a time."""
    base = [100.0] * n
    flat = ema_fn(base, alpha)
    weights = []
    for i in range(n):
        bumped = list(base)
        bumped[i] += 1.0
        weights.append(ema_fn(bumped, alpha) - flat)
    return weights


def test_weight_increases_towards_the_present():
    """The finding, stated as the property that fails today.

    Folded backwards the NEWEST bar was the least-weighted of the window
    (alpha * (1 - alpha) ** 19 = 0.01351) and the oldest carried the full alpha.
    Folded forwards the weights rise monotonically towards the present.
    """
    from api.trading import _ema

    weights = _bar_weights(_ema, 20, 0.1)

    # weights[0] is the seed, which is not a folded bar — see the next test.
    folded = weights[1:]
    assert folded == sorted(folded), f"weight does not increase towards the present: {folded}"
    assert weights[-1] == pytest.approx(0.1), "the newest bar must carry the full alpha"
    assert weights[-1] > weights[1] * 5, "the newest bar barely outweighs the oldest folded bar"


def test_the_seed_keeps_the_standard_warm_up_residual():
    """Stated rather than asserted away: a 20-bar window at alpha=0.1 seeded on
    its oldest value leaves that value (1 - alpha) ** 19 = 13.5% of the result —
    more than the newest bar's 10%.

    That is the ordinary warm-up artifact of a short EMA window, present in any
    textbook implementation and in the "correct EMA20" figures the finding
    computed. It is not F125: F125 was the *ordering*, which made the newest bar
    the least-weighted of the twenty. Recorded here so a future reader does not
    mistake the residual for the bug — the way to shrink it is a longer warm-up
    window, not a different fold.
    """
    from api.trading import _ema

    weights = _bar_weights(_ema, 20, 0.1)
    assert weights[0] == pytest.approx(0.9**19, rel=1e-6)


def test_it_matches_the_reference_on_a_rising_series():
    from api.trading import _ema

    closes = [3000.0 + 15.0 * i for i in range(20)]
    assert _ema(closes, 0.1) == pytest.approx(_reference_ema(closes, 0.1), rel=1e-9)


def test_it_matches_the_reference_on_a_falling_series():
    from api.trading import _ema

    closes = [3000.0 - 15.0 * i for i in range(20)]
    assert _ema(closes, 0.1) == pytest.approx(_reference_ema(closes, 0.1), rel=1e-9)


def test_the_ema_tracks_price_rather_than_lagging_behind_the_window():
    """On a steadily rising series the EMA must sit between the middle of the
    window and the newest close. Folded backwards it sat below the whole
    window (3238.92 against a last close of 3295)."""
    from api.trading import _ema

    closes = [3000.0 + 15.0 * i for i in range(21)]  # last close 3300
    ema = _ema(closes[-20:], 0.1)

    assert closes[-20] < ema < closes[-1]
    assert ema > sum(closes[-20:]) / 20 - 30


def test_a_single_bar_window_is_that_bar():
    from api.trading import _ema

    assert _ema([2750.0], 0.1) == pytest.approx(2750.0)


def test_an_empty_window_is_zero_not_a_crash():
    from api.trading import _ema

    assert _ema([], 0.1) == 0.0
