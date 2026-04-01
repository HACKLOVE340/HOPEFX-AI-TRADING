# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
ml/alpha_decay.py
==================
Alpha decay analysis and Information Coefficient (IC) diagnostics.

Measures how quickly a signal's predictive power decays over time:
  - IC (Information Coefficient): Spearman rank correlation between
    signal and forward returns at each lag
  - IC decay curve: IC vs holding horizon (H = 1, 2, ..., max_lag)
  - IC mean, IC std, ICIR (IC / std) — signal quality metrics
  - Half-life of IC decay (fitted exponential)

Reference:
  Grinold, R. & Kahn, R. (2000). Active Portfolio Management. McGraw-Hill.
"""
from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from typing import Sequence

import numpy as np
import pandas as pd
from scipy.stats import spearmanr

logger = logging.getLogger(__name__)


@dataclass
class ICResult:
    """Information Coefficient analysis output."""
    ic_mean: float
    """Mean IC across all lags."""
    ic_std: float
    """Std deviation of IC values."""
    icir: float
    """IC Information Ratio = mean / std."""
    ic_by_lag: dict[int, float]
    """IC at each forward return lag (horizon)."""
    half_life: float
    """Estimated IC half-life in periods (-∞ if IC doesn't decay)."""
    t_stat: float
    """t-statistic on IC_mean (H0: IC=0)."""
    n_observations: int
    """Number of (signal, return) pairs used."""


class AlphaDecay:
    """
    Alpha decay / IC analysis toolkit.

    Evaluates how quickly a trading signal's edge decays as the
    holding horizon increases.
    """

    def __init__(
        self,
        max_lag: int = 20,
        min_obs: int = 30,
    ) -> None:
        """
        Parameters
        ----------
        max_lag : int
            Maximum forward return horizon to test (default 20).
        min_obs : int
            Minimum observations required for valid IC (default 30).
        """
        self.max_lag = max_lag
        self.min_obs = min_obs

    def compute_ic(
        self,
        signal: pd.Series,
        returns: pd.Series,
        lag: int = 1,
    ) -> float:
        """
        Compute Spearman IC between signal and forward returns at lag.

        Parameters
        ----------
        signal : pd.Series
            Signal values (any scale; ranked internally).
        returns : pd.Series
            Asset returns. Must share index with signal.
        lag : int
            Forward return horizon in periods.

        Returns
        -------
        float — Spearman IC in [-1, 1]. NaN if insufficient data.
        """
        # Align and shift: signal at t predicts return at t+lag
        fwd_ret = returns.shift(-lag)
        aligned = pd.concat([signal, fwd_ret], axis=1).dropna()
        if len(aligned) < self.min_obs:
            return float("nan")

        ic, _ = spearmanr(aligned.iloc[:, 0], aligned.iloc[:, 1])
        return float(ic)

    def ic_decay_curve(
        self,
        signal: pd.Series,
        returns: pd.Series,
    ) -> ICResult:
        """
        Compute full IC decay curve from lag=1 to max_lag.

        Parameters
        ----------
        signal : pd.Series
            Signal values indexed by time.
        returns : pd.Series
            Asset returns indexed by time.

        Returns
        -------
        ICResult with full decay analysis.
        """
        ic_by_lag: dict[int, float] = {}
        for lag in range(1, self.max_lag + 1):
            ic_by_lag[lag] = self.compute_ic(signal, returns, lag)

        valid_ics = [v for v in ic_by_lag.values() if not math.isnan(v)]
        n_obs = len(signal.dropna())

        if not valid_ics:
            return ICResult(
                ic_mean=0.0, ic_std=0.0, icir=0.0,
                ic_by_lag=ic_by_lag, half_life=float("inf"),
                t_stat=0.0, n_observations=n_obs,
            )

        ic_mean = float(np.mean(valid_ics))
        ic_std = float(np.std(valid_ics, ddof=1)) if len(valid_ics) > 1 else 0.0
        icir = ic_mean / ic_std if ic_std > 0 else 0.0

        # t-stat: IC_mean / (IC_std / sqrt(T))
        t_stat = ic_mean / (ic_std / math.sqrt(len(valid_ics))) if ic_std > 0 else 0.0

        # Estimate IC half-life via exponential fit to |IC| decay
        half_life = self._estimate_half_life(ic_by_lag)

        return ICResult(
            ic_mean=ic_mean,
            ic_std=ic_std,
            icir=icir,
            ic_by_lag=ic_by_lag,
            half_life=half_life,
            t_stat=t_stat,
            n_observations=n_obs,
        )

    def rolling_ic(
        self,
        signal: pd.Series,
        returns: pd.Series,
        window: int = 63,
        lag: int = 1,
    ) -> pd.Series:
        """
        Rolling IC (63-day default) to detect regime changes in signal quality.

        Returns pd.Series of IC values indexed by time.
        """
        fwd_ret = returns.shift(-lag)
        aligned = pd.concat([signal, fwd_ret], axis=1).dropna()
        if len(aligned) < window:
            return pd.Series(dtype=float)

        ics = []
        dates = []
        for i in range(window, len(aligned) + 1):
            chunk = aligned.iloc[i - window : i]
            ic, _ = spearmanr(chunk.iloc[:, 0], chunk.iloc[:, 1])
            ics.append(float(ic))
            dates.append(aligned.index[i - 1])

        return pd.Series(ics, index=pd.DatetimeIndex(dates))

    def _estimate_half_life(self, ic_by_lag: dict[int, float]) -> float:
        """Fit exponential decay to |IC| curve and return half-life."""
        lags = []
        abs_ics = []
        for lag, ic in ic_by_lag.items():
            if not math.isnan(ic):
                lags.append(lag)
                abs_ics.append(abs(ic))

        if len(lags) < 3 or max(abs_ics) == 0:
            return float("inf")

        # Log-linear regression: log(|IC|) = a - b*lag  =>  half_life = log(2)/b
        try:
            log_ics = np.log(np.maximum(abs_ics, 1e-10))
            lag_arr = np.array(lags, dtype=float)
            # OLS
            A = np.column_stack([np.ones_like(lag_arr), lag_arr])
            coeffs, _, _, _ = np.linalg.lstsq(A, log_ics, rcond=None)
            b = -coeffs[1]
            if b <= 0:
                return float("inf")
            return float(math.log(2) / b)
        except Exception:
            return float("inf")
