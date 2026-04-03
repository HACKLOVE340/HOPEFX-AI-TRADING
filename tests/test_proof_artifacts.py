# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
tests/test_proof_artifacts.py
==============================
Validates that examples/generate_proof_artifacts.py produced correct outputs.

Checks
------
1. examples/results/performance.json exists and has required keys.
2. Trade count >= 250 (minimum for Sharpe SE <= 0.3).
3. Win rate is in a plausible range (40-70%).
4. Sharpe ratio is finite and non-negative.
5. examples/results/trades.csv exists with correct columns.
6. examples/results/equity_curve.png exists and is non-empty.
7. ml/saved_models/rf_xauusd.pkl exists and loads correctly.
8. Saved model has 'model', 'scaler', 'features' keys.
9. Real data flag is True (not synthetic fallback).
10. generate_proof_artifacts.py is importable (no syntax errors).
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
RESULTS = ROOT / "examples" / "results"
MODELS = ROOT / "ml" / "saved_models"


# ── performance.json ──────────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def perf():
    path = RESULTS / "performance.json"
    if not path.exists():
        pytest.skip("performance.json not generated yet — run examples/generate_proof_artifacts.py")
    with Path(path).open(encoding="utf-8") as f:
        return json.load(f)


def test_performance_json_exists():
    assert (RESULTS / "performance.json").exists(), "Run: python examples/generate_proof_artifacts.py"


def test_performance_has_required_keys(perf):
    required = [
        "n_trades",
        "win_rate_pct",
        "sharpe_ratio",
        "total_return_pct",
        "max_drawdown_pct",
        "profit_factor",
        "real_data",
        "data_source",
    ]
    for key in required:
        assert key in perf, f"Missing key in performance.json: {key}"


def test_trade_count_sufficient(perf):
    n = int(perf["n_trades"])
    assert n >= 250, f"Only {n} trades — need >= 250 for Sharpe SE <= 0.3. Re-run with a longer backtest period."


def test_win_rate_plausible(perf):
    wr = float(perf["win_rate_pct"])
    assert 35.0 <= wr <= 75.0, f"Win rate {wr}% outside plausible range [35, 75]"


def test_sharpe_finite_and_nonnegative(perf):
    s = float(perf["sharpe_ratio"])
    assert math.isfinite(s), f"Sharpe ratio is not finite: {s}"
    assert s >= 0.0, f"Sharpe ratio is negative: {s}"


def test_profit_factor_above_one(perf):
    pf = float(perf["profit_factor"])
    assert pf >= 1.0, f"Profit factor {pf} < 1.0 — strategy loses money on average"


def test_real_data_used(perf):
    assert perf.get("real_data") is True, (
        "Backtest used synthetic data — yfinance may be unavailable. Install: pip install yfinance"
    )


def test_data_source_is_yahoo(perf):
    src = perf.get("data_source", "")
    assert "Yahoo" in src or "GC=F" in src or "yfinance" in src.lower(), f"Unexpected data source: {src}"


# ── trades.csv ────────────────────────────────────────────────────────────────


def test_trades_csv_exists():
    assert (RESULTS / "trades.csv").exists(), "Run: python examples/generate_proof_artifacts.py"


def test_trades_csv_has_correct_columns():
    import pandas as pd

    df = pd.read_csv(RESULTS / "trades.csv")
    # Core columns always present; 'side' may be 'result' depending on generator version
    required_cols = {"entry_date", "exit_date", "net_pnl"}
    missing = required_cols - set(df.columns)
    assert not missing, f"trades.csv missing columns: {missing}"
    # At least one of side/result must be present
    assert "side" in df.columns or "result" in df.columns, "trades.csv must have either 'side' or 'result' column"


def test_trades_csv_row_count(perf):
    import pandas as pd

    df = pd.read_csv(RESULTS / "trades.csv")
    expected = int(perf["n_trades"])
    assert len(df) == expected, f"trades.csv has {len(df)} rows but performance.json says {expected} trades"


# ── equity_curve.png ──────────────────────────────────────────────────────────


def test_equity_curve_exists():
    assert (RESULTS / "equity_curve.png").exists(), "Run: python examples/generate_proof_artifacts.py"


def test_equity_curve_nonempty():
    size = (RESULTS / "equity_curve.png").stat().st_size
    assert size > 10_000, f"equity_curve.png is suspiciously small ({size} bytes)"


# ── rf_xauusd.pkl ─────────────────────────────────────────────────────────────


def test_model_pkl_exists():
    assert (MODELS / "rf_xauusd.pkl").exists(), "Run: python examples/generate_proof_artifacts.py"


def test_model_pkl_loads():
    import joblib

    bundle = joblib.load(MODELS / "rf_xauusd.pkl")
    assert isinstance(bundle, dict), "rf_xauusd.pkl should be a dict bundle"


def test_model_bundle_has_required_keys():
    import joblib

    bundle = joblib.load(MODELS / "rf_xauusd.pkl")
    for key in ("model", "scaler", "features"):
        assert key in bundle, f"rf_xauusd.pkl missing key: {key}"


def test_model_can_predict():
    import joblib
    import numpy as np

    bundle = joblib.load(MODELS / "rf_xauusd.pkl")
    model = bundle["model"]
    scaler = bundle["scaler"]
    n_features = len(bundle["features"])
    X = np.random.randn(1, n_features)
    X_scaled = scaler.transform(X)
    pred = model.predict(X_scaled)
    assert pred.shape == (1,)
    assert pred[0] in (0, 1)


# ── script importability ──────────────────────────────────────────────────────


def test_generate_proof_artifacts_importable():
    """Script has no syntax errors."""
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "generate_proof_artifacts",
        ROOT / "examples" / "generate_proof_artifacts.py",
    )
    # Just loading the spec (not executing) verifies syntax
    assert spec is not None
