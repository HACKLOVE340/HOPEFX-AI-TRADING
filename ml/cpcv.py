# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
ml/cpcv.py
===========
Combinatorial Purged Cross-Validation (CPCV).

Implements López de Prado's CPCV (Advances in Financial Machine Learning,
Chapter 12). Generates train/test splits that:
  1. Prevent data leakage across overlapping labels (purging)
  2. Add an embargo gap after each test fold
  3. Enumerate all C(N, k) combinations of test paths for unbiased evaluation

Reference:
  López de Prado, M. (2018). Advances in Financial Machine Learning. Wiley.
"""
from __future__ import annotations

import logging
from itertools import combinations
from typing import Iterator

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


class CPCV:
    """
    Combinatorial Purged Cross-Validation.

    Parameters
    ----------
    n_splits : int
        Number of folds (N). Must be >= 2.
    n_test_splits : int
        Number of folds used for testing per combination (k). Default 2.
    pct_embargo : float
        Fraction of samples used as embargo gap after each test fold.
        Default 0.01 (1%).
    """

    def __init__(
        self,
        n_splits: int = 6,
        n_test_splits: int = 2,
        pct_embargo: float = 0.01,
    ) -> None:
        if n_splits < 2:
            raise ValueError("n_splits must be >= 2")
        if n_test_splits < 1 or n_test_splits >= n_splits:
            raise ValueError("n_test_splits must satisfy 1 <= k < n_splits")
        if not 0.0 <= pct_embargo < 1.0:
            raise ValueError("pct_embargo must be in [0, 1)")

        self.n_splits = n_splits
        self.n_test_splits = n_test_splits
        self.pct_embargo = pct_embargo

    def split(
        self,
        X: pd.DataFrame | np.ndarray,
        y: pd.Series | np.ndarray | None = None,
        pred_times: pd.Series | None = None,
        eval_times: pd.Series | None = None,
    ) -> Iterator[tuple[np.ndarray, np.ndarray]]:
        """
        Generate (train_indices, test_indices) pairs.

        Parameters
        ----------
        X : array-like of shape (n_samples, n_features)
        y : ignored (kept for sklearn compatibility)
        pred_times : pd.Series, optional
            Prediction (start) times. Index aligned with X. If None, uses
            integer positions.
        eval_times : pd.Series, optional
            Evaluation (end) times — when the label becomes known. Used
            for purging. If None, same as pred_times.
        """
        n = len(X) if not hasattr(X, "shape") else X.shape[0]
        idx = np.arange(n)

        if pred_times is None:
            pred_times = pd.Series(np.arange(n), dtype=float)
        if eval_times is None:
            eval_times = pred_times.copy()

        # Embargo size in samples
        embargo_size = int(n * self.pct_embargo)

        # Split index into N equal-width folds
        fold_bounds = _fold_bounds(n, self.n_splits)

        # Enumerate all C(N, k) test fold combinations
        for test_folds in combinations(range(self.n_splits), self.n_test_splits):
            test_idx = _folds_to_indices(fold_bounds, test_folds, n)

            # Purge: remove training samples whose eval_times overlap test period
            test_pred_min = pred_times.iloc[test_idx].min()
            test_eval_max = eval_times.iloc[test_idx].max()

            # Embargo: remove training samples in the gap after each test fold
            embargoing_idx = set()
            for fold in test_folds:
                fold_end = fold_bounds[fold][1]
                embargo_end = min(fold_end + embargo_size, n)
                embargoing_idx.update(range(fold_end, embargo_end))

            train_mask = np.ones(n, dtype=bool)
            train_mask[test_idx] = False

            # Purge: drop samples where eval_time > test start (would leak)
            purge_mask = (eval_times.values >= test_pred_min) & (
                pred_times.values <= test_eval_max
            )
            train_mask &= ~purge_mask

            # Embargo
            if embargoing_idx:
                emb_arr = np.array(list(embargoing_idx))
                emb_arr = emb_arr[emb_arr < n]
                train_mask[emb_arr] = False

            train_idx = idx[train_mask]
            if len(train_idx) == 0:
                logger.warning("CPCV: empty training set for test_folds=%s", test_folds)
                continue

            yield train_idx, test_idx

    def get_n_splits(
        self,
        X: pd.DataFrame | np.ndarray | None = None,
        y=None,
        groups=None,
    ) -> int:
        """Number of splitting iterations (C(N, k))."""
        from math import comb
        return comb(self.n_splits, self.n_test_splits)


def _fold_bounds(n: int, k: int) -> list[tuple[int, int]]:
    """Return list of (start, end) indices for k equal folds over n samples."""
    fold_size = n // k
    remainder = n % k
    bounds = []
    start = 0
    for i in range(k):
        extra = 1 if i < remainder else 0
        end = start + fold_size + extra
        bounds.append((start, end))
        start = end
    return bounds


def _folds_to_indices(
    bounds: list[tuple[int, int]], folds: tuple[int, ...], n: int
) -> np.ndarray:
    """Convert fold indices to sample indices."""
    parts = [np.arange(bounds[f][0], bounds[f][1]) for f in folds]
    if not parts:
        return np.array([], dtype=int)
    return np.concatenate(parts)
