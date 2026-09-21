# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# AGPL-3.0 — Share all modifications
"""
tests/unit/test_ab_baseline.py
==============================
Unit tests for ml/ab_baseline.py — the ML-vs-rule-baseline A/B harness.

Covers:
  - rule_baseline_signal returns a clean 0/1 series
  - _trade_sharpe edge cases (< 2 trades, flat returns)
  - _directional_pnl sign convention
  - run_ab produces a well-formed report with all sections on synthetic data
  - _verdict thresholds map to the right message
"""

from __future__ import annotations

import numpy as np
import pytest

from ml.ab_baseline import (
    _directional_pnl,
    _synthetic_ohlcv,
    _trade_sharpe,
    _verdict,
    rule_baseline_signal,
    run_ab,
)


def test_rule_baseline_signal_is_binary() -> None:
    df = _synthetic_ohlcv(n=300)
    sig = rule_baseline_signal(df)
    assert set(np.unique(sig.to_numpy())).issubset({0, 1})
    assert len(sig) == len(df)


def test_trade_sharpe_edge_cases() -> None:
    assert _trade_sharpe(np.array([])) == 0.0
    assert _trade_sharpe(np.array([0.01])) == 0.0  # < 2 trades
    assert _trade_sharpe(np.array([0.01, 0.01, 0.01])) == 0.0  # zero variance
    assert _trade_sharpe(np.array([0.02, -0.01, 0.03, -0.005])) != 0.0


def test_directional_pnl_sign_convention() -> None:
    # pred=1 → long → +ret; pred=0 → short → -ret
    pnl = _directional_pnl(np.array([1, 0]), np.array([0.05, 0.05]))
    assert pnl[0] == pytest.approx(0.05)
    assert pnl[1] == pytest.approx(-0.05)


@pytest.mark.parametrize(
    ("lift", "needle"),
    [
        (0.05, "adds real value"),
        (0.01, "edges out"),
        (0.0, "ties"),
        (-0.02, "UNDERPERFORMS"),
    ],
)
def test_verdict_thresholds(lift: float, needle: str) -> None:
    assert needle in _verdict(0.5, 0.5 + lift, lift)


def test_run_ab_report_shape() -> None:
    df = _synthetic_ohlcv(n=1500)
    report = run_ab(df, horizon=5, oos_years=2.0, n_estimators=80)
    # Sections present
    for key in ("baseline", "ml", "ml_as_filter", "ml_accuracy_lift", "verdict", "oos_bars"):
        assert key in report
    # Accuracies are valid probabilities
    assert 0.0 <= report["baseline"]["accuracy"] <= 1.0
    assert 0.0 <= report["ml"]["accuracy"] <= 1.0
    # Lift is consistent with the two accuracies
    assert report["ml_accuracy_lift"] == pytest.approx(
        report["ml"]["accuracy"] - report["baseline"]["accuracy"], abs=1e-4
    )
    assert report["ml_beats_baseline"] == (report["ml"]["accuracy"] > report["baseline"]["accuracy"])
    assert report["oos_bars"] > 0
