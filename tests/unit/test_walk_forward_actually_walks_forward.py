# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""`/walk-forward/run` must walk forward, and must not test on training data.

F123. The endpoint computed five fold windows spanning three years, then threw
them away. `_run_real_backtest(strategy, symbol, days, capital)` takes a *count
of days* and always ends at `datetime.now(UTC)`, so the fold dates reached the
response as labels while every fold measured the same recent window.

Replicating the endpoint's own arithmetic at n_splits=5, train_ratio=0.7 before
any change:

    fold  labelled train           labelled test            data actually used
    1     2023-09-14..2024-02-14   2024-02-14..2024-04-20   train 2026-04-13..2026-09-13
    2     2024-04-20..2024-09-20   2024-09-20..2024-11-25   train 2026-04-13..2026-09-13
    3     2024-11-25..2025-04-27   2025-04-27..2025-07-02   train 2026-04-13..2026-09-13
    4     2025-07-02..2025-12-02   2025-12-02..2026-02-06   train 2026-04-13..2026-09-13
    5     2026-02-06..2026-07-09   2026-07-09..2026-09-13   train 2026-04-13..2026-09-13

    every fold: train = last 153 days, test = last 66 days

Three defects, not one:

1. **No walk-forward.** Five folds, one window. `avg_test_sharpe` is the Sharpe
   of the last 66 days computed five times and averaged.
2. **The test window is inside the training window.** Not merely a missing purge
   gap — total containment, which is the most complete look-ahead leak
   available. A strategy fitted on a period and scored on part of the same
   period reports whatever its fit was worth.
3. **The reported dates are fiction.** A reader checking the fold boundaries
   against a market event is checking labels that describe no computation.

This is the worst shape a backtest defect takes, because leakage does not
announce itself as an error — it announces itself as a *good number*, on the
report someone sizes positions from.

`backtesting/walk_forward.py::WalkForwardEngine` already implements purged
walk-forward correctly. It is not called here and these tests do not require it
to be: it is a parameter-grid *optimiser* (`run(data, strategy_factory,
parameter_grid)`), while this endpoint validates one parameterisation. The tests
below assert the properties, not the implementation, so either route satisfies
them.
"""

from __future__ import annotations

from datetime import datetime

import pytest

pytestmark = pytest.mark.unit


def _windows_requested(monkeypatch, **overrides) -> list[dict]:
    """Run the endpoint's executor and capture every window it asks for.

    Spies at the backtest boundary rather than reading the response, because the
    response is exactly what was wrong: it reported windows it had not used.
    """
    import api.backtesting as bt

    seen: list[tuple[str, datetime, datetime]] = []

    def _spy(strategy, symbol, start, end, capital):
        seen.append(("window", start, end))
        return {"sharpe_ratio": 1.0, "total_return_pct": 1.0, "max_drawdown_pct": 1.0}

    # The fixed function takes an explicit window; the broken one took a day
    # count. Bind whichever exists so this helper reports honestly either way.
    if hasattr(bt, "_run_backtest_window"):
        monkeypatch.setattr(bt, "_run_backtest_window", _spy)
    else:

        def _legacy(strategy, symbol, days, capital):
            from datetime import UTC, timedelta

            end = datetime.now(UTC)
            seen.append(("window", end - timedelta(days=days), end))
            return {"sharpe_ratio": 1.0, "total_return_pct": 1.0, "max_drawdown_pct": 1.0}

        monkeypatch.setattr(bt, "_run_real_backtest", _legacy)

    monkeypatch.setattr(bt, "_load_strategy", lambda *_a, **_k: object())
    captured: dict = {}
    monkeypatch.setattr(bt, "_persist_wf_result", lambda run_id, payload, user_id=None: captured.update(payload))

    req = bt.WalkForwardRequest(strategy="ma_crossover", symbol="XAUUSD", initial_capital=10_000.0, **overrides)
    bt._walk_forward_execute(req, run_id="test-run", user_id="tester")

    folds = captured.get("folds", [])
    pairs = [seen[i : i + 2] for i in range(0, len(seen), 2)]
    return [
        {
            "fold": f,
            "train": (pairs[i][0][1], pairs[i][0][2]) if i < len(pairs) else None,
            "test": (pairs[i][1][1], pairs[i][1][2]) if i < len(pairs) and len(pairs[i]) > 1 else None,
        }
        for i, f in enumerate(folds)
    ]


def test_each_fold_measures_a_different_period(monkeypatch):
    """Five folds must not be five measurements of the same window."""
    folds = _windows_requested(monkeypatch, n_splits=5, train_ratio=0.7)
    assert len(folds) == 5

    # Compared at DAY resolution on purpose. The broken code called
    # datetime.now(UTC) once per backtest, so the five windows differed by
    # microseconds and a naive tuple comparison called them distinct — this
    # assertion passed against the defect until it was tightened.
    test_windows = [(f["test"][0].date(), f["test"][1].date()) for f in folds]
    assert len(set(test_windows)) == len(test_windows), f"the folds measure the same period: {test_windows}"


def test_the_test_window_never_overlaps_the_training_window(monkeypatch):
    """Leakage. A strategy scored on data it was fitted on reports its fit."""
    for f in _windows_requested(monkeypatch, n_splits=5, train_ratio=0.7):
        (train_start, train_end), (test_start, _test_end) = f["train"], f["test"]
        assert test_start >= train_end, (
            f"fold {f['fold'].get('fold')}: test starts {test_start} inside training {train_start}..{train_end}"
        )


def test_a_purge_gap_separates_training_from_testing(monkeypatch):
    """An embargo, not merely a boundary.

    A bar immediately after the training cut still shares the state that
    produced the last training signal — an open position, a rolling window
    mid-fill. `WalkForwardEngine` embargoes for exactly this reason.
    """
    for f in _windows_requested(monkeypatch, n_splits=5, train_ratio=0.7, purge_days=5):
        (_train_start, train_end), (test_start, _test_end) = f["train"], f["test"]
        assert (test_start - train_end).days >= 5, (
            f"only {(test_start - train_end).days} days between training and testing"
        )


def test_the_reported_dates_are_the_dates_that_were_measured(monkeypatch):
    """The labels must describe the computation, or the report is fiction."""
    for f in _windows_requested(monkeypatch, n_splits=5, train_ratio=0.7):
        row = f["fold"]
        (train_start, train_end), (test_start, test_end) = f["train"], f["test"]
        assert row["train_start"] == train_start.date().isoformat()
        assert row["train_end"] == train_end.date().isoformat()
        assert row["test_start"] == test_start.date().isoformat()
        assert row["test_end"] == test_end.date().isoformat()


def test_the_folds_advance_through_time(monkeypatch):
    """Walk *forward*: each fold's test period must follow the last one's."""
    folds = _windows_requested(monkeypatch, n_splits=5, train_ratio=0.7)
    starts = [f["test"][0].date() for f in folds]
    assert starts == sorted(starts), f"folds do not advance: {starts}"
    # Strictly later, not merely non-decreasing: five folds all starting on the
    # same day are sorted, and are not a walk forward.
    assert starts[-1] > starts[0], f"every fold starts at the same point: {starts}"
    assert len(set(starts)) == len(starts)
