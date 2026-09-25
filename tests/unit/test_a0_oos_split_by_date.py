# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
A0 fix #7 — ``--oos-years`` counted filtered ROWS, not calendar years (D6).

``ml/train_advanced.py`` turned ``--oos-years N`` into ``N * 252`` rows of the
feature frame. The filtered target drops ~9% of bars, so "8 years" was recorded
for a window of 2016-08-17 → 2026-03-25 — 9.6 years. A silent 40% cap also
shortened the dry run's "2 years" to 476 rows with nothing recorded.

The OOS window is now every row dated after ``last_date - N years``, and the
report records the dates and the calendar length it actually covers. When the
40% cap applies it is logged and recorded, not silent.
"""

from __future__ import annotations


import numpy as np
import pandas as pd
import pytest


LAST = pd.Timestamp("2026-03-25")


def _filtered_frame(start="2016-01-04", drop=0.09, seed=0):
    """A daily frame with ~9% of bars missing, like the ATR-filtered target."""
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range(start, LAST)
    keep = rng.uniform(size=len(idx)) > drop
    keep[-1] = True
    idx = idx[keep]
    X = pd.DataFrame(rng.normal(size=(len(idx), 3)), index=idx, columns=["a", "b", "c"])
    y = pd.Series(rng.integers(0, 2, len(idx)), index=idx)
    return X, y


def test_oos_window_starts_n_calendar_years_before_the_last_row():
    from ml.train_advanced import split_oos_by_date

    X, y = _filtered_frame()
    s = split_oos_by_date(X, y, oos_years=2.0, horizon=5)

    cutoff = LAST - pd.DateOffset(years=2)
    first = s["X_oos"].index[0]
    assert first > cutoff, (first, cutoff)
    assert (first - cutoff).days <= 5, (
        f"OOS starts {first.date()}, {(first - cutoff).days} days after {cutoff.date()} — the window is not 2 "
        "calendar years (D6: it used to be 2*252 filtered rows)"
    )
    assert s["X_oos"].index[-1] == LAST
    assert s["oos_start"] == str(first.date()) and s["oos_end"] == str(LAST.date())
    assert s["oos_calendar_years"] == pytest.approx(2.0, abs=0.02)
    assert s["capped"] is False


def test_train_ends_before_oos_with_the_horizon_purged():
    from ml.train_advanced import split_oos_by_date

    X, y = _filtered_frame()
    s = split_oos_by_date(X, y, oos_years=2.0, horizon=5)
    n_before = int((X.index < s["X_oos"].index[0]).sum())
    assert len(s["X_cv"]) == n_before - 5, "the last `horizon` training rows must be purged"
    assert s["X_cv"].index[-1] < s["X_oos"].index[0]
    assert s["y_cv"].index.equals(s["X_cv"].index) and s["y_oos"].index.equals(s["X_oos"].index)


def test_a_window_over_the_cap_is_shortened_and_says_so():
    from ml.train_advanced import split_oos_by_date

    X, y = _filtered_frame(start="2021-01-04")  # ~5 years
    s = split_oos_by_date(X, y, oos_years=3.0, horizon=5)
    assert s["capped"] is True
    assert len(s["X_oos"]) == int(len(X) * 0.40)
    assert s["oos_calendar_years"] < 3.0
    assert s["oos_years_requested"] == 3.0


def test_too_short_a_window_is_no_window():
    from ml.train_advanced import split_oos_by_date

    X, y = _filtered_frame()
    s = split_oos_by_date(X, y, oos_years=0.1, horizon=5)  # ~24 rows < 100
    assert s["X_oos"] is None and len(s["X_cv"]) == len(X)


def test_main_evaluates_oos_on_the_dated_window(tmp_path, monkeypatch):
    """End to end through main(): what reaches oos_eval_advanced is the dated
    window, and the report records its dates and calendar length."""
    import ml.features_extended as fe
    import ml.train_advanced as ta

    X, y = _filtered_frame()
    ohlcv = pd.DataFrame({"open": 1.0, "high": 1.0, "low": 1.0, "close": 1.0, "volume": 1.0}, index=X.index)
    captured = {}

    monkeypatch.setattr(ta, "fetch_gold_ohlcv", lambda *a, **k: ohlcv)
    monkeypatch.setattr(fe, "build_extended_features", lambda *a, **k: (X, y))
    monkeypatch.setattr(ta, "walk_forward_eval", lambda *a, **k: {"mean_accuracy": 0.5})
    monkeypatch.setattr(ta, "train_final_model", lambda *a, **k: (None, {"accuracy": 0.5, "f1": 0.5, "auc": 0.5}))
    monkeypatch.setattr(ta, "extract_feature_importance", lambda *a, **k: {})
    monkeypatch.setattr(ta, "write_feature_importances", lambda *a, **k: None)
    monkeypatch.setattr(ta, "write_feature_stats", lambda *a, **k: None)

    def _oos(X_cv, y_cv, X_oos, y_oos, **k):
        captured["X_oos"] = X_oos
        return {"accuracy": 0.5, "f1": 0.5, "auc": 0.5, "oos_size": len(X_oos), "p_value_binomial": 1.0}

    monkeypatch.setattr(ta, "oos_eval_advanced", _oos)
    original_dir = ta.MODEL_DIR
    try:
        report = ta.main(
            ["--years", "11", "--oos-years", "2", "--horizon", "5", "--no-macro", "--model-dir", str(tmp_path)]
        )
    finally:
        ta.MODEL_DIR = original_dir

    first = captured["X_oos"].index[0]
    cutoff = LAST - pd.DateOffset(years=2)
    assert first > cutoff and (first - cutoff).days <= 5, (first, cutoff)
    assert report["oos_start"] == str(first.date())
    assert report["oos_end"] == str(LAST.date())
    assert report["oos_calendar_years"] == pytest.approx(2.0, abs=0.02)
    assert report["oos_sample_count"] == len(captured["X_oos"])


def test_smoke_mode_does_not_force_oos_years_to_zero(monkeypatch, tmp_path):
    """``--smoke`` used to force ``--oos-years`` to 0.0 unconditionally, inside
    ``main()`` itself, discarding whatever the caller passed on the command
    line. ``scripts/retrain_horizon5.py`` computes ``oos_years=1.0`` for its
    own ``--smoke`` path specifically so the CI smoke run produces a real OOS
    split (see its docstring) and passes it explicitly as ``--oos-years 1`` —
    but this override silently rewrote it back to 0 every time.

    With ``oos_years=0``, ``split_oos_by_date()`` always returns
    ``X_oos=None``, so ``oos_eval_advanced()`` — the ONLY function that writes
    ``advanced_oos.pkl``, ``advanced_oos_meta.json`` and
    ``calibration_report.json`` — was never called. The smoke CI step could
    then only ever "pass" by finding an artifact some earlier, unrelated run
    had committed, never one the smoke run itself produced.
    docs/ai/MASTER_OUTSTANDING.md §A0 · --id RETRAIN-SMOKE-NO-OOS.
    """
    import ml.features_extended as fe
    import ml.train_advanced as ta

    X, y = _filtered_frame()
    ohlcv = pd.DataFrame({"open": 1.0, "high": 1.0, "low": 1.0, "close": 1.0, "volume": 1.0}, index=X.index)
    captured = {}

    monkeypatch.setattr(ta, "fetch_gold_ohlcv", lambda *a, **k: ohlcv)
    monkeypatch.setattr(fe, "build_extended_features", lambda *a, **k: (X, y))
    monkeypatch.setattr(ta, "walk_forward_eval", lambda *a, **k: {"mean_accuracy": 0.5})
    monkeypatch.setattr(ta, "train_final_model", lambda *a, **k: (None, {"accuracy": 0.5, "f1": 0.5, "auc": 0.5}))
    monkeypatch.setattr(ta, "extract_feature_importance", lambda *a, **k: {})
    monkeypatch.setattr(ta, "write_feature_importances", lambda *a, **k: None)
    monkeypatch.setattr(ta, "write_feature_stats", lambda *a, **k: None)

    def _oos(X_cv, y_cv, X_oos, y_oos, **k):
        captured["X_oos_len"] = len(X_oos)
        return {"accuracy": 0.5, "f1": 0.5, "auc": 0.5, "oos_size": len(X_oos), "p_value_binomial": 1.0}

    monkeypatch.setattr(ta, "oos_eval_advanced", _oos)
    original_dir = ta.MODEL_DIR
    try:
        report = ta.main(["--smoke", "--oos-years", "1", "--model-dir", str(tmp_path)])
    finally:
        ta.MODEL_DIR = original_dir

    assert "X_oos_len" in captured, (
        "oos_eval_advanced() was never called — --smoke forced --oos-years back to 0, "
        "discarding the explicit --oos-years 1 the caller passed"
    )
    assert captured["X_oos_len"] > 0
    assert report["oos_sample_count"] == captured["X_oos_len"]
