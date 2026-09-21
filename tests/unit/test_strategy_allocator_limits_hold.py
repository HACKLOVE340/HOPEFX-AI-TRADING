"""F222 (TODO item 5) — `portfolio/strategy_allocator.py` allocated capital untested.

585 lines named by no test file, and it decides what fraction of the book each
strategy gets. Writing the first test found three defects, all reproduced by
execution before being fixed.

**1 · The per-pod concentration cap was violated by the code enforcing it.**
`_sharpe_proportional` clipped weights to `MAX_WEIGHT_PER_POD` and then divided
by the new sum, which pushes the clipped weight straight back over the cap:

    sharpes [9.0, 0.5, 0.5] -> [0.8, 0.1, 0.1]   with the cap at 0.4

A risk limit that does not limit. `CLAUDE.md` forbids weakening a risk gate;
this one arrived weakened.

**2 · Strategies that all lose money received the whole book.** With every
Sharpe negative, `total == 0` after the `maximum(sharpes, 0)` clamp and the
fallback returned `ones(n) / n` — an equal split of 100% of capital across
strategies that are all losing. "Everything is losing" allocates nothing.

**3 · Correlations were computed over invented returns.** Shorter histories were
padded with zeros, so a pod with 3 days of data against one with 200 contributed
197 fabricated 0.00% days. Zero is not "no data", it is "flat that day" — a
measurement nobody made, feeding the optimiser that allocates capital.
"""

from __future__ import annotations

import sys

import numpy as np
import pytest


def _module():
    import portfolio.strategy_allocator  # noqa: F401

    return sys.modules["portfolio.strategy_allocator"]


_MOD = _module()
CorrelationMatrix = _MOD.CorrelationMatrix
MeanVarianceOptimiser = _MOD.MeanVarianceOptimiser
StrategyPod = _MOD.StrategyPod
MAX_WEIGHT_PER_POD = _MOD.MAX_WEIGHT_PER_POD


@pytest.fixture
def optimiser():
    return MeanVarianceOptimiser()


def _pod(name: str, history: list[float], sharpe: float = 2.0) -> StrategyPod:
    return StrategyPod(name=name, oos_sharpe=sharpe, oos_n=100, oos_se=0.1, return_history=history)


# ── 1 · the concentration cap actually caps ──────────────────────────────────


@pytest.mark.parametrize(
    "sharpes",
    [
        [9.0, 0.5, 0.5],
        [100.0, 1.0, 1.0],
        [5.0, 0.1, 0.1, 0.1],
        [3.0, 3.0, 0.01],
        [1.0, 1.0, 1.0],
    ],
    ids=lambda value: "-".join(str(x) for x in value),
)
def test_no_pod_exceeds_the_concentration_cap(optimiser, sharpes: list[float]) -> None:
    weights = optimiser._sharpe_proportional(np.array(sharpes))

    assert weights.max() <= MAX_WEIGHT_PER_POD + 1e-9, (
        f"a pod got {weights.max():.3f} against a cap of {MAX_WEIGHT_PER_POD}"
    )


def test_the_excess_is_redistributed_not_discarded(optimiser) -> None:
    """Capping the leader must move its excess to the others, not shrink the book."""
    weights = optimiser._sharpe_proportional(np.array([9.0, 0.5, 0.5]))

    assert weights[0] == pytest.approx(MAX_WEIGHT_PER_POD)
    assert weights.sum() == pytest.approx(1.0)
    assert weights[1] == pytest.approx(weights[2]), "equal Sharpes should get equal weight"


def test_a_cap_that_cannot_reach_full_allocation_leaves_the_rest_unallocated(optimiser) -> None:
    """Two pods at a 0.4 cap can hold 0.8 of the book. The other 0.2 is cash.

    Scaling up to reach 1.0 would break the cap, which is the bug this replaced.
    """
    weights = optimiser._sharpe_proportional(np.array([2.0, 2.0]))

    assert weights.max() <= MAX_WEIGHT_PER_POD + 1e-9
    assert weights.sum() == pytest.approx(2 * MAX_WEIGHT_PER_POD)
    assert weights.sum() < 1.0


# ── 2 · losing strategies do not get the book ────────────────────────────────


def test_all_negative_sharpes_allocate_nothing(optimiser) -> None:
    weights = optimiser._sharpe_proportional(np.array([-1.5, -2.0, -0.8]))

    assert weights.sum() == pytest.approx(0.0)
    assert (weights == 0).all()


def test_all_zero_sharpes_allocate_nothing(optimiser) -> None:
    """No measured edge is not the same as an equal edge."""
    weights = optimiser._sharpe_proportional(np.array([0.0, 0.0]))

    assert weights.sum() == pytest.approx(0.0)


def test_one_positive_among_losers_takes_only_its_cap(optimiser) -> None:
    weights = optimiser._sharpe_proportional(np.array([3.0, -1.0, -2.0]))

    assert weights[1] == 0.0 and weights[2] == 0.0
    assert weights[0] == pytest.approx(MAX_WEIGHT_PER_POD)


# ── 3 · correlation uses measured returns only ───────────────────────────────


def test_a_short_history_is_not_padded_with_invented_zeros() -> None:
    """197 fabricated flat days decided how two strategies correlate."""
    alternating = [0.01 * ((-1) ** index) for index in range(200)]
    short = _pod("short", alternating[-3:])
    long = _pod("long", alternating)

    corr = CorrelationMatrix().compute([short, long])

    # On the overlapping window the two are identical, so the correlation is 1.
    # Zero-padding gave 0.0578 — a number produced by the padding, not the data.
    assert corr[0, 1] == pytest.approx(1.0, abs=1e-6)


def test_an_overlap_too_short_to_measure_reports_no_correlation() -> None:
    """One shared day cannot produce a correlation. Identity, not a guess."""
    corr = CorrelationMatrix().compute([_pod("a", [0.01]), _pod("b", [0.01] * 50)])

    assert corr[0, 1] == pytest.approx(0.0)
    assert corr[0, 0] == pytest.approx(1.0)


def test_two_opposite_strategies_correlate_negatively() -> None:
    series = [0.01, -0.02, 0.03, -0.01, 0.02, -0.03]
    corr = CorrelationMatrix().compute([_pod("a", series), _pod("b", [-x for x in series])])

    assert corr[0, 1] == pytest.approx(-1.0, abs=1e-6)


def test_the_matrix_is_symmetric_with_a_unit_diagonal() -> None:
    pods = [_pod("a", [0.01, 0.02, -0.01, 0.03]), _pod("b", [0.02, -0.01, 0.01, 0.02])]
    corr = CorrelationMatrix().compute(pods)

    assert np.allclose(corr, corr.T)
    assert np.allclose(np.diag(corr), 1.0)


def test_no_pods_and_one_pod_are_handled(optimiser) -> None:
    assert CorrelationMatrix().compute([]).shape == (0, 0)
    assert CorrelationMatrix().compute([_pod("a", [0.01, 0.02])]).shape == (1, 1)
    assert optimiser.optimise(np.array([]), np.eye(0)).size == 0
    assert optimiser.optimise(np.array([2.0]), np.eye(1)) == pytest.approx([1.0])


# ── the validation gate, previously untested ─────────────────────────────────


def test_a_pod_below_the_sharpe_gate_is_not_validated() -> None:
    assert StrategyPod(name="p", oos_sharpe=0.1, oos_n=500, oos_se=0.1).gate_passed is False


def test_a_pod_with_too_few_trades_is_not_validated() -> None:
    assert StrategyPod(name="p", oos_sharpe=3.0, oos_n=1, oos_se=0.1).gate_passed is False


def test_a_pod_with_too_wide_a_standard_error_is_not_validated() -> None:
    """A high Sharpe with a huge standard error is noise, not an edge."""
    assert StrategyPod(name="p", oos_sharpe=3.0, oos_n=500, oos_se=99.0).gate_passed is False


# ── 4 · a non-finite Sharpe does not become a non-finite allocation ──────────


def test_a_nan_sharpe_allocates_nothing(optimiser) -> None:
    """Found by the repo's own code analyzer (nan_leak), and it was real.

    `total <= 0` is False when `total` is NaN, so the guard for "no measured
    edge" let NaN straight through and every weight came out NaN. Measured:
    `[2.0, nan, 1.0]` produced `[nan, nan, nan]`.

    Refusing is the safe direction for capital: a NaN weight multiplied by the
    book is a NaN position size, and whatever consumes it downstream decides
    what that means.
    """
    weights = optimiser._sharpe_proportional(np.array([2.0, float("nan"), 1.0]))

    assert not np.isnan(weights).any()
    assert weights.sum() == pytest.approx(0.0)


@pytest.mark.parametrize("bad", [float("inf"), float("-inf"), float("nan")])
def test_any_non_finite_sharpe_allocates_nothing(optimiser, bad: float) -> None:
    weights = optimiser._sharpe_proportional(np.array([2.0, bad]))

    assert np.isfinite(weights).all()
    assert weights.sum() == pytest.approx(0.0)


def test_a_nan_weight_never_leaves_the_capper() -> None:
    """The cap loop compares against NaN, and every comparison is False."""
    from portfolio.strategy_allocator import _cap_weights

    capped = _cap_weights(np.array([0.5, float("nan"), 0.2]))

    assert np.isfinite(capped).all()
    assert capped.sum() == pytest.approx(0.0)


def test_finite_sharpes_are_unaffected(optimiser) -> None:
    """The guard must not refuse a perfectly good allocation.

    Three pods, not two: with the cap at 0.4 a two-pod book tops out at 0.8 by
    design (see `test_a_cap_that_cannot_reach_full_allocation_leaves_the_rest_unallocated`),
    so two pods cannot show that a full allocation still happens.
    """
    weights = optimiser._sharpe_proportional(np.array([3.0, 2.0, 1.0]))

    assert np.isfinite(weights).all()
    assert weights.sum() == pytest.approx(1.0)
    assert weights.max() <= MAX_WEIGHT_PER_POD + 1e-9
    # The weakest pod stays the smallest; the two ahead of it are both at the cap.
    assert weights[2] < weights[1]
