# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
tests/unit/test_stationarity_fails_closed.py
============================================
Round 3 audit, Slice 4 (docs/HARDENING_BACKLOG.md S4-06).

`StationarityTester.test()` returned a **permissive** result when `statsmodels`
could not be imported:

    return StationarityResult(
        adf_pvalue=0.01,        # looks like strong evidence of stationarity
        kpss_pvalue=0.10,
        is_stationary=True,     # ← claims the test passed
        method="SKIPPED (statsmodels unavailable)",
    )

The fabricated p-values are the problem, not just the boolean. `adf_pvalue=0.01`
is what a *confidently stationary* series looks like, so any caller reading the
numbers rather than `method` sees strong evidence for a test that never ran.

This is the S4-05 pattern again: a guard that cannot run reports the reassuring
answer instead of "unknown". `statsmodels` is in `requirements.txt`, so a
correct deployment has it — but an import failure in production would silently
declare every feature stationary, and non-stationary features are exactly what
this check exists to keep out of training and inference.

Fails closed now: unavailable means not stationary, with p-values that do not
impersonate a result.
"""

from __future__ import annotations

import pandas as pd
import pytest


@pytest.fixture
def tester():
    from ml.pipeline import StationarityTester

    return StationarityTester()


def _without_statsmodels(monkeypatch):
    from ml import pipeline

    monkeypatch.setattr(pipeline, "_STATSMODELS", False, raising=False)


def test_unavailable_statsmodels_does_not_claim_stationary(tester, monkeypatch):
    """The core property: cannot test => not stationary."""
    _without_statsmodels(monkeypatch)

    result = tester.test(pd.Series([1.0, 2.0, 3.0, 4.0, 5.0]), name="f")

    # bool(): the real path returns numpy bool_, so identity checks are unsafe.
    assert bool(result.is_stationary) is False, (
        "the stationarity test could not run and still reported is_stationary=True — "
        "a non-stationary feature would pass straight into training (S4-06)"
    )


def test_the_skipped_result_does_not_fabricate_evidence(tester, monkeypatch):
    """p-values must not impersonate a confident pass."""
    _without_statsmodels(monkeypatch)

    result = tester.test(pd.Series([1.0, 2.0, 3.0]), name="f")

    assert result.adf_pvalue != 0.01, (
        "adf_pvalue=0.01 is what a strongly stationary series looks like; a test that never ran must not report it"
    )
    assert result.adf_pvalue >= 0.5, "a skipped ADF must not read as significant"
    assert result.kpss_pvalue <= 0.5, "a skipped KPSS must not read as passing"


def test_the_reason_is_still_visible(tester, monkeypatch):
    """Operators need to tell 'failed the test' from 'could not test'."""
    _without_statsmodels(monkeypatch)

    result = tester.test(pd.Series([1.0, 2.0, 3.0]), name="f")
    assert "statsmodels" in result.method.lower()
    assert "skip" in result.method.lower() or "unavailable" in result.method.lower()


def test_real_stationary_series_still_passes_when_statsmodels_is_present(tester):
    """Control: the fix must not make the tester useless.

    White noise is stationary; the tester must still say so.
    """
    pytest.importorskip("statsmodels")
    import numpy as np

    rng = np.random.default_rng(42)
    noise = pd.Series(rng.normal(0, 1, 500))

    assert bool(tester.test(noise, name="white_noise").is_stationary) is True


def test_real_random_walk_still_fails_when_statsmodels_is_present(tester):
    """Control, the other way: a random walk is not stationary."""
    pytest.importorskip("statsmodels")
    import numpy as np

    rng = np.random.default_rng(7)
    walk = pd.Series(np.cumsum(rng.normal(0, 1, 500)))

    assert bool(tester.test(walk, name="random_walk").is_stationary) is False
