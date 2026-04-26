# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
Unit tests for scripts/feature_stability_analysis.py

Tests cover:
- compute_stability() classification logic (stable / marginal / unstable)
- Stability score arithmetic
- Report structure and required keys
- Smoke-mode integration (no network, synthetic OHLCV)
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

from scripts.feature_stability_analysis import compute_stability


# ── Fixtures ──────────────────────────────────────────────────────────────────


def _make_fold_results(n_folds: int, features: list[str], top_features: list[str]) -> list[dict]:
    """
    Build synthetic fold_results where `top_features` appear in every fold
    and the remaining features appear in only the first fold.
    """
    results = []
    for fold in range(1, n_folds + 1):
        importance: dict[str, float] = {}
        # Top features get high importance in every fold
        for i, feat in enumerate(top_features):
            importance[feat] = 1.0 / (i + 1)
        # Other features get low importance only in fold 1
        for feat in features:
            if feat not in top_features:
                importance[feat] = 0.001 if fold == 1 else 0.0
        results.append(
            {
                "fold": fold,
                "accuracy": 0.58,
                "f1": 0.60,
                "auc": 0.61,
                "train_size": 1000,
                "test_size": 200,
                "importance": importance,
            }
        )
    return results


# ── compute_stability tests ───────────────────────────────────────────────────


class TestComputeStability:
    """Tests for the core stability computation function."""

    def test_stable_features_appear_in_all_folds(self):
        """Features in top-N of every fold should be classified stable."""
        top = ["feat_a", "feat_b", "feat_c"]
        others = ["feat_x", "feat_y", "feat_z"]
        fold_results = _make_fold_results(n_folds=6, features=top + others, top_features=top)

        result = compute_stability(
            fold_results=fold_results,
            top_n=5,
            stable_threshold=0.67,
            marginal_threshold=0.33,
        )

        for feat in top:
            assert feat in result["stable_features"], f"{feat} should be stable (appears in all 6 folds)"

    def test_unstable_features_appear_in_one_fold(self):
        """Features in top-N of only 1/6 folds should be classified unstable.

        top_n=2 ensures only the 2 top features make the cut per fold;
        the 'others' only appear in fold 1 with low importance and are
        excluded from top-2 even there.
        """
        top = ["feat_a", "feat_b"]
        others = ["feat_x", "feat_y"]
        fold_results = _make_fold_results(n_folds=6, features=top + others, top_features=top)

        # top_n=2 means only feat_a and feat_b make the top-N in every fold;
        # feat_x and feat_y never appear in top-2 → stability=0 → unstable
        result = compute_stability(
            fold_results=fold_results,
            top_n=2,
            stable_threshold=0.67,
            marginal_threshold=0.33,
        )

        for feat in others:
            assert feat in result["unstable_features"], f"{feat} should be unstable (never in top-2 across 6 folds)"

    def test_stability_scores_sum_to_valid_range(self):
        """All stability scores must be in [0, 1]."""
        top = ["a", "b"]
        others = ["c", "d"]
        fold_results = _make_fold_results(n_folds=4, features=top + others, top_features=top)

        result = compute_stability(fold_results, top_n=3, stable_threshold=0.67, marginal_threshold=0.33)

        for feat, score in result["stability_scores"].items():
            assert 0.0 <= score <= 1.0, f"Score for {feat} out of range: {score}"

    def test_no_feature_in_multiple_categories(self):
        """Each feature must appear in exactly one category."""
        top = ["a", "b", "c"]
        others = ["d", "e"]
        fold_results = _make_fold_results(n_folds=6, features=top + others, top_features=top)

        result = compute_stability(fold_results, top_n=4, stable_threshold=0.67, marginal_threshold=0.33)

        all_classified = (
            set(result["stable_features"]) | set(result["marginal_features"]) | set(result["unstable_features"])
        )
        # No feature should appear in two categories
        assert len(result["stable_features"]) + len(result["marginal_features"]) + len(
            result["unstable_features"]
        ) == len(all_classified)

    def test_all_features_classified(self):
        """Every feature in the fold results must appear in exactly one category."""
        top = ["a", "b"]
        others = ["c", "d", "e"]
        all_feats = top + others
        fold_results = _make_fold_results(n_folds=6, features=all_feats, top_features=top)

        result = compute_stability(fold_results, top_n=3, stable_threshold=0.67, marginal_threshold=0.33)

        classified = (
            set(result["stable_features"]) | set(result["marginal_features"]) | set(result["unstable_features"])
        )
        assert classified == set(all_feats), f"Unclassified features: {set(all_feats) - classified}"

    def test_mean_importance_computed(self):
        """mean_importance must be present for every feature."""
        top = ["a", "b"]
        others = ["c"]
        fold_results = _make_fold_results(n_folds=4, features=top + others, top_features=top)

        result = compute_stability(fold_results, top_n=2, stable_threshold=0.67, marginal_threshold=0.33)

        for feat in top + others:
            assert feat in result["mean_importance"], f"mean_importance missing for {feat}"
            assert result["mean_importance"][feat] >= 0.0

    def test_cv_importance_computed(self):
        """cv_importance (coefficient of variation) must be present for every feature."""
        top = ["a", "b"]
        fold_results = _make_fold_results(n_folds=4, features=top, top_features=top)

        result = compute_stability(fold_results, top_n=2, stable_threshold=0.67, marginal_threshold=0.33)

        for feat in top:
            assert feat in result["cv_importance"], f"cv_importance missing for {feat}"

    def test_per_fold_top_n_length(self):
        """per_fold_top_n must have one entry per fold, each of length <= top_n."""
        top = ["a", "b", "c", "d", "e"]
        fold_results = _make_fold_results(n_folds=3, features=top, top_features=top)

        result = compute_stability(fold_results, top_n=3, stable_threshold=0.67, marginal_threshold=0.33)

        assert len(result["per_fold_top_n"]) == 3
        for fold_top in result["per_fold_top_n"]:
            assert len(fold_top) <= 3

    def test_single_fold_all_stable(self):
        """With 1 fold, every feature in top-N has stability=1.0 → all stable."""
        top = ["a", "b"]
        fold_results = _make_fold_results(n_folds=1, features=top, top_features=top)

        result = compute_stability(fold_results, top_n=2, stable_threshold=0.67, marginal_threshold=0.33)

        for feat in top:
            assert result["stability_scores"][feat] == 1.0

    def test_threshold_boundary_marginal(self):
        """Feature appearing in exactly 2/6 folds (0.333) should be marginal at threshold=0.33."""
        # Build fold results where "feat_m" appears in top-1 of exactly 2 folds.
        # In folds 1-2: feat_m has higher importance than feat_top → in top-1.
        # In folds 3-6: feat_top dominates → feat_m not in top-1.
        results = []
        for fold in range(1, 7):
            imp = (
                {"feat_top": 0.3, "feat_m": 0.7}  # feat_m wins top-1
                if fold <= 2
                else {"feat_top": 1.0, "feat_m": 0.0}  # feat_top wins top-1
            )
            results.append(
                {
                    "fold": fold,
                    "accuracy": 0.55,
                    "f1": 0.55,
                    "auc": 0.55,
                    "train_size": 100,
                    "test_size": 50,
                    "importance": imp,
                }
            )

        # top_n=1 → only the highest-importance feature per fold counts
        result = compute_stability(results, top_n=1, stable_threshold=0.67, marginal_threshold=0.33)

        # feat_m appears in top-1 of 2/6 folds → stability = 0.3333
        score = result["stability_scores"]["feat_m"]
        assert abs(score - 2 / 6) < 1e-4, f"Expected stability≈0.333, got {score}"
        # 0.333 >= marginal_threshold(0.33) and < stable_threshold(0.67) → marginal
        assert "feat_m" in result["marginal_features"], (
            f"feat_m (stability={score:.4f}) should be marginal, "
            f"got stable={result['stable_features']} unstable={result['unstable_features']}"
        )


# ── Report structure tests ────────────────────────────────────────────────────


class TestReportStructure:
    """Verify the report dict has all required keys."""

    REQUIRED_KEYS = {
        "stable_features",
        "marginal_features",
        "unstable_features",
        "stability_scores",
        "mean_importance",
        "cv_importance",
        "per_fold_top_n",
    }

    def test_all_required_keys_present(self):
        top = ["a", "b"]
        fold_results = _make_fold_results(n_folds=2, features=top, top_features=top)
        result = compute_stability(fold_results, top_n=2, stable_threshold=0.67, marginal_threshold=0.33)

        for key in self.REQUIRED_KEYS:
            assert key in result, f"Missing key: {key}"

    def test_stable_features_is_list(self):
        top = ["a"]
        fold_results = _make_fold_results(n_folds=2, features=top, top_features=top)
        result = compute_stability(fold_results, top_n=1, stable_threshold=0.5, marginal_threshold=0.25)
        assert isinstance(result["stable_features"], list)

    def test_stability_scores_is_dict(self):
        top = ["a"]
        fold_results = _make_fold_results(n_folds=2, features=top, top_features=top)
        result = compute_stability(fold_results, top_n=1, stable_threshold=0.5, marginal_threshold=0.25)
        assert isinstance(result["stability_scores"], dict)


# ── Integration: run_stability_analysis smoke mode ────────────────────────────


class TestRunStabilityAnalysisSmoke:
    """
    Integration test using synthetic OHLCV data injected via monkeypatching.
    No network access required.
    """

    @pytest.fixture()
    def synthetic_ohlcv(self) -> pd.DataFrame:
        """Minimal OHLCV DataFrame that satisfies the feature builders."""
        rng = np.random.default_rng(42)
        n = 600
        close = 1900.0 + np.cumsum(rng.normal(0, 5, n))
        close = np.clip(close, 1000, 3000)
        high = close + rng.uniform(1, 10, n)
        low = close - rng.uniform(1, 10, n)
        open_ = close + rng.normal(0, 3, n)
        volume = rng.integers(1000, 10000, n).astype(float)

        idx = pd.date_range("2020-01-01", periods=n, freq="B", tz="UTC")
        return pd.DataFrame(
            {"open": open_, "high": high, "low": low, "close": close, "volume": volume},
            index=idx,
        )

    def test_smoke_produces_valid_report(self, tmp_path, monkeypatch, synthetic_ohlcv):
        """Smoke run with synthetic data produces a valid JSON report."""
        import scripts.feature_stability_analysis as fsa

        # Patch _load_data to return synthetic OHLCV without network access
        monkeypatch.setattr(fsa, "_load_data", lambda **kwargs: synthetic_ohlcv)

        # Patch _build_features to use a simple feature set
        def _simple_features(df, horizon, min_move_atr):
            X = pd.DataFrame({f"feat_{i}": df["close"].pct_change(i + 1).fillna(0) for i in range(10)}, index=df.index)
            y = (df["close"].shift(-horizon) > df["close"]).astype(int).fillna(0)
            X = X.iloc[:-horizon]
            y = y.iloc[:-horizon]
            return X, y

        monkeypatch.setattr(fsa, "_build_features", _simple_features)

        out = tmp_path / "stability.json"
        fsa.run_stability_analysis(
            years=2,
            n_splits=2,
            top_n=5,
            stable_threshold=0.67,
            marginal_threshold=0.33,
            smoke=True,
            output_path=out,
        )

        # File written
        assert out.exists(), "Report file not written"

        # JSON is valid
        loaded = json.loads(out.read_text())
        assert "stable_features" in loaded
        assert "unstable_features" in loaded
        assert "stability_scores" in loaded
        assert "summary" in loaded
        assert "config" in loaded

        # Summary counts are consistent
        n_stable = loaded["summary"]["n_stable"]
        n_marginal = loaded["summary"]["n_marginal"]
        n_unstable = loaded["summary"]["n_unstable"]
        total = n_stable + n_marginal + n_unstable
        assert total == len(loaded["stability_scores"]), (
            f"Category counts ({total}) != total features ({len(loaded['stability_scores'])})"
        )

    def test_smoke_report_has_fold_results(self, tmp_path, monkeypatch, synthetic_ohlcv):
        """Report must include per-fold accuracy metrics."""
        import scripts.feature_stability_analysis as fsa

        monkeypatch.setattr(fsa, "_load_data", lambda **kwargs: synthetic_ohlcv)

        def _simple_features(df, horizon, min_move_atr):
            X = pd.DataFrame({"f0": df["close"].pct_change().fillna(0)}, index=df.index)
            y = (df["close"].shift(-horizon) > df["close"]).astype(int).fillna(0)
            X = X.iloc[:-horizon]
            y = y.iloc[:-horizon]
            return X, y

        monkeypatch.setattr(fsa, "_build_features", _simple_features)

        out = tmp_path / "stability2.json"
        fsa.run_stability_analysis(
            years=2,
            n_splits=2,
            top_n=1,
            stable_threshold=0.5,
            marginal_threshold=0.25,
            smoke=True,
            output_path=out,
        )

        loaded = json.loads(out.read_text())
        assert "fold_results" in loaded
        assert len(loaded["fold_results"]) >= 1
        for fold in loaded["fold_results"]:
            assert "accuracy" in fold
            assert "fold" in fold
