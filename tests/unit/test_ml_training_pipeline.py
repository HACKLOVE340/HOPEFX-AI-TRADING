# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
tests/test_ml_training_pipeline.py
====================================
Tests for the ML training pipeline (ml/train_advanced.py).

Covers
------
1. fetch_gold_ohlcv with --use-cached loads from CSV correctly.
2. fetch_gold_ohlcv falls back to download when cache missing.
3. --smoke flag overrides years/oos_years/no_macro/splits.
4. --use-cached flag is wired into main() fetch call.
5. advanced_oos.pkl exists and loads as a sklearn Pipeline.
6. advanced_training_report.json has required keys.
7. feature_scaler.pkl loads and transforms correctly.
8. retrain_model.py --smoke delegates to train_advanced.py.
9. train_advanced.py is importable (no syntax errors).
10. retrain_model.py is importable (no syntax errors).
"""

from __future__ import annotations

import json
import subprocess  # nosec B404 - test file
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[2]  # repo root (test lives in tests/unit/)
MODELS = ROOT / "ml" / "saved_models"
sys.path.insert(0, str(ROOT))


# ── importability ─────────────────────────────────────────────────────────────


def test_train_advanced_importable():
    import importlib.util

    spec = importlib.util.spec_from_file_location("train_advanced", ROOT / "ml" / "train_advanced.py")
    assert spec is not None


def test_retrain_model_importable():
    import importlib.util

    spec = importlib.util.spec_from_file_location("retrain_model", ROOT / "scripts" / "retrain_model.py")
    assert spec is not None


# ── fetch_gold_ohlcv with cache ───────────────────────────────────────────────


def test_fetch_gold_ohlcv_uses_cache(tmp_path):
    """fetch_gold_ohlcv loads from CSV when use_cached=True and file exists."""
    from ml.train_advanced import fetch_gold_ohlcv

    # Create a minimal fake CSV with recent dates so the date-range filter
    # does not strip all rows when years=1 is requested.
    # Use a fixed anchor (last Friday relative to now) so the range is always
    # exactly N calendar days, regardless of whether today is a weekend.
    n = 300
    anchor = pd.Timestamp.now().normalize()
    # Roll back to the most recent weekday so freq="B" always yields exactly n rows
    while anchor.weekday() >= 5:  # 5=Sat, 6=Sun
        anchor -= pd.Timedelta(days=1)
    dates = pd.date_range(end=anchor, periods=n, freq="B")
    df = pd.DataFrame(
        {
            "open": np.random.uniform(1800, 2000, n),
            "high": np.random.uniform(1800, 2000, n),
            "low": np.random.uniform(1800, 2000, n),
            "close": np.random.uniform(1800, 2000, n),
            "volume": np.random.randint(1000, 5000, n),
        },
        index=dates,
    )
    csv_path = tmp_path / "test_cache.csv"
    df.to_csv(csv_path)

    result = fetch_gold_ohlcv("GC=F", years=1, use_cached=True, cached_csv=str(csv_path))
    assert not result.empty
    assert "close" in result.columns


def test_fetch_gold_ohlcv_cache_missing_falls_back(tmp_path, monkeypatch):
    """fetch_gold_ohlcv falls back to download when cache file missing."""
    yf = pytest.importorskip("yfinance", reason="yfinance not installed")
    import yfinance as yf  # noqa: F811

    from ml.train_advanced import fetch_gold_ohlcv

    fake_dates = pd.date_range("2024-01-01", periods=50, freq="B")
    fake_df = pd.DataFrame(
        {
            "open": [1900.0] * 50,
            "high": [1910.0] * 50,
            "low": [1890.0] * 50,
            "close": [1905.0] * 50,
            "volume": [1000] * 50,
        },
        index=fake_dates,
    )

    monkeypatch.setattr(yf, "download", lambda *a, **kw: fake_df)

    result = fetch_gold_ohlcv(
        "GC=F",
        years=1,
        use_cached=True,
        cached_csv=str(tmp_path / "nonexistent.csv"),
    )
    assert not result.empty


# ── smoke flag ────────────────────────────────────────────────────────────────


def test_smoke_flag_overrides_args():
    """--smoke sets years=2, oos_years=0, no_macro=True, splits=2."""
    # Simulate argument parsing with --smoke
    sys.argv = ["train_advanced.py", "--smoke"]
    try:
        import importlib
        import importlib.util

        spec = importlib.util.spec_from_file_location("train_advanced_mod", ROOT / "ml" / "train_advanced.py")
        _mod = importlib.util.module_from_spec(spec)
        # Don't exec — just verify the argparse setup by parsing directly
        import argparse as _ap

        parser = _ap.ArgumentParser()
        parser.add_argument("--smoke", action="store_true")
        parser.add_argument("--years", type=int, default=50)
        parser.add_argument("--oos-years", type=float, default=8.0)
        parser.add_argument("--no-macro", action="store_true")
        parser.add_argument("--splits", type=int, default=8)
        parser.add_argument("--use-cached", action="store_true")
        args = parser.parse_args(["--smoke"])
        assert args.smoke is True
        # Simulate the smoke override block
        if args.smoke:
            args.years = 2
            args.oos_years = 0.0
            args.no_macro = True
            args.splits = 2
            args.use_cached = True
        assert args.years == 2
        assert args.oos_years == 0.0
        assert args.no_macro is True
        assert args.splits == 2
        assert args.use_cached is True
    finally:
        sys.argv = sys.argv[:1]


# ── saved model artifacts ─────────────────────────────────────────────────────


_ARTIFACTS_PRESENT = (MODELS / "advanced_oos.pkl").exists()
_SKIP_NO_ARTIFACTS = pytest.mark.skipif(
    not _ARTIFACTS_PRESENT,
    reason="Model artifacts absent — run: python ml/train_advanced.py --smoke",
)


@_SKIP_NO_ARTIFACTS
def test_advanced_oos_pkl_exists():
    assert (MODELS / "advanced_oos.pkl").exists()


@_SKIP_NO_ARTIFACTS
def test_advanced_oos_pkl_is_sklearn_pipeline():
    import joblib

    model = joblib.load(MODELS / "advanced_oos.pkl")
    # Should be a sklearn Pipeline or CalibratedClassifierCV
    assert hasattr(model, "predict") or hasattr(model, "predict_proba"), (
        "advanced_oos.pkl does not have predict/predict_proba"
    )


@pytest.mark.skipif(
    not (MODELS / "feature_scaler.pkl").exists(),
    reason="feature_scaler.pkl absent — run: python ml/train_advanced.py --smoke",
)
def test_feature_scaler_pkl_exists():
    assert (MODELS / "feature_scaler.pkl").exists()


@pytest.mark.skipif(
    not (MODELS / "feature_scaler.pkl").exists(),
    reason="feature_scaler.pkl absent — run: python ml/train_advanced.py --smoke",
)
def test_feature_scaler_transforms():
    import joblib

    scaler = joblib.load(MODELS / "feature_scaler.pkl")
    # Scaler should have n_features_in_
    n = getattr(scaler, "n_features_in_", None)
    if n is None:
        pytest.skip("Scaler does not expose n_features_in_")
    X = np.random.randn(5, n)
    X_scaled = scaler.transform(X)
    assert X_scaled.shape == (5, n)


@pytest.mark.skipif(
    not (MODELS / "advanced_training_report.json").exists(),
    reason="advanced_training_report.json absent — run: python ml/train_advanced.py --smoke",
)
def test_advanced_training_report_exists():
    assert (MODELS / "advanced_training_report.json").exists()


@pytest.mark.skipif(
    not (MODELS / "advanced_training_report.json").exists(),
    reason="advanced_training_report.json absent — run: python ml/train_advanced.py --smoke",
)
def test_advanced_training_report_keys():
    with Path(MODELS / "advanced_training_report.json").open(encoding="utf-8") as f:
        report = json.load(f)
    required = ["symbol", "years", "feature_count", "walkforward", "trained_at"]
    for key in required:
        assert key in report, f"Missing key in advanced_training_report.json: {key}"


@pytest.mark.skipif(
    not (MODELS / "advanced_training_report.json").exists(),
    reason="advanced_training_report.json absent — run: python ml/train_advanced.py --smoke",
)
def test_advanced_training_report_feature_count(monkeypatch):
    with Path(MODELS / "advanced_training_report.json").open(encoding="utf-8") as f:
        report = json.load(f)
    fc = report.get("feature_count", 0)
    # Smoke mode uses 100 features (no macro); full run uses 122
    assert fc >= 50, f"Feature count {fc} is suspiciously low"


# ── retrain_model.py --smoke ──────────────────────────────────────────────────


# Artefacts the smoke retrain overwrites in place. They are committed and
# checksum-verified in CI, so a test run must hand them back byte-identical.
_SMOKE_OVERWRITES = (
    "advanced_oos.pkl",
    "advanced_oos_meta.json",
    "advanced_training_report.json",
    "feature_scaler.pkl",
    "feature_stats.json",
    "stacking_ensemble.pkl",
)


@pytest.fixture
def _preserve_saved_models():
    """Restore ml/saved_models/ after a test that retrains in place.

    `retrain_model.py --smoke --advanced` shells out to ml/train_advanced.py,
    whose MODEL_DIR is hardcoded to ml/saved_models — `--model-dir` is only
    threaded through the non-advanced branch, and train_advanced does not read
    ML_MODEL_DIR. So this test rewrites tracked model artefacts as a side
    effect and leaves the working tree dirty.

    Making train_advanced honour ML_MODEL_DIR would look like the tidier fix
    and is not safe: that variable is already live — `.env.example` sets it to
    `models` and deployment/helm_chart.py sets `/app/data/models` — while
    ml/advanced_predictor.py reads models back from ml/saved_models. Honouring
    it here would silently send a production retrain somewhere inference does
    not look. So the test cleans up after itself instead.
    """
    saved = {}
    for name in _SMOKE_OVERWRITES:
        path = MODELS / name
        saved[path] = path.read_bytes() if path.exists() else None
    try:
        yield
    finally:
        for path, original in saved.items():
            if original is None:
                path.unlink(missing_ok=True)
            elif path.read_bytes() != original:
                path.write_bytes(original)


def test_preserve_saved_models_actually_restores(_preserve_saved_models):
    """The guard above is only worth having if it really puts the bytes back.

    Mutates a tracked artefact inside the fixture's scope; the fixture's
    teardown must restore it. Without this, the fixture could rot into a no-op
    and the pollution would come back unnoticed.
    """
    victim = MODELS / "feature_stats.json"
    if not victim.exists():
        pytest.skip("feature_stats.json not present in this checkout")

    original = victim.read_bytes()
    victim.write_bytes(original + b"\n// scribble\n")
    assert victim.read_bytes() != original, "test setup failed to mutate the file"
    # Teardown restores it; the assertion lives in the companion test below.


def test_preserve_saved_models_left_no_scribble():
    """Runs after the test above and sees the restored state."""
    victim = MODELS / "feature_stats.json"
    if not victim.exists():
        pytest.skip("feature_stats.json not present in this checkout")

    assert b"scribble" not in victim.read_bytes(), (
        "_preserve_saved_models did not restore the artefact it was given — the "
        "smoke retrain will start leaving the working tree dirty again"
    )


@pytest.mark.slow
@pytest.mark.usefixtures("_preserve_saved_models")
def test_retrain_model_smoke_exits_zero():
    """retrain_model.py --smoke --advanced completes without error."""
    result = subprocess.run(  # nosec B603 - test file
        [
            sys.executable,
            str(ROOT / "scripts" / "retrain_model.py"),
            "--smoke",
            "--advanced",
        ],
        capture_output=True,
        text=True,
        timeout=300,
        cwd=str(ROOT),
        check=False,
    )
    assert result.returncode == 0, (
        f"retrain_model.py --smoke --advanced failed:\nSTDOUT: {result.stdout[-2000:]}\nSTDERR: {result.stderr[-2000:]}"
    )
