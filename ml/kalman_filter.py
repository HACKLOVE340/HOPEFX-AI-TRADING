# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
ml/kalman_filter.py
====================
Kalman filter dynamic hedge ratio.

Implements a time-varying hedge ratio using a Kalman filter state-space model.
Used for dynamic pair trading, spread trading (gold vs silver, gold vs GLD ETF),
and portfolio hedging with time-varying betas.

State equation: beta_t = beta_{t-1} + eta_t       (random walk)
Obs  equation:  y_t    = x_t * beta_t + alpha + eps_t

Reference:
  Pole, A. (2007). Statistical Arbitrage. Wiley Finance.
  Chan, E. (2013). Algorithmic Trading. Wiley.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


@dataclass
class KalmanState:
    """Kalman filter state at time t."""
    beta: float
    """Current dynamic hedge ratio estimate."""
    alpha: float
    """Current alpha (intercept) estimate."""
    spread: float
    """Current spread: y - alpha - beta * x."""
    spread_std: float
    """1-sigma uncertainty of the spread."""
    beta_std: float
    """1-sigma uncertainty of beta."""
    P: np.ndarray
    """State covariance matrix."""


class KalmanHedgeRatio:
    """
    Kalman filter for dynamic hedge ratio estimation.

    Estimates time-varying linear relationship y_t = alpha + beta_t * x_t
    where beta_t evolves as a random walk.

    Parameters
    ----------
    delta : float
        State transition noise (controls how fast beta can change).
        Smaller → more stable beta. Default 1e-4.
    obs_noise : float
        Observation noise variance (R). Default 1e-3.
    """

    def __init__(
        self,
        delta: float = 1e-4,
        obs_noise: float = 1e-3,
    ) -> None:
        self.delta = delta
        self.obs_noise = obs_noise

        # State: [alpha, beta]^T
        self._theta = np.array([0.0, 1.0])  # initial [alpha, beta]
        self._P = np.eye(2) * 1.0           # state covariance
        self._R = obs_noise                  # observation noise
        self._Q = delta / (1 - delta) * np.eye(2)  # transition noise

        self._history: list[KalmanState] = []

    def update(self, y: float, x: float) -> KalmanState:
        """
        Process one observation (y_t, x_t).

        Parameters
        ----------
        y : float
            Dependent variable (e.g. gold price).
        x : float
            Independent variable / hedge instrument (e.g. silver, GLD).

        Returns
        -------
        KalmanState with updated estimates.
        """
        # Observation matrix F = [1, x]
        F = np.array([1.0, x])

        # Prediction step (state transition = identity for random walk)
        # theta_{t|t-1} = theta_{t-1|t-1}
        # P_{t|t-1} = P_{t-1|t-1} + Q
        P_pred = self._P + self._Q

        # Innovation
        y_pred = float(F @ self._theta)
        innovation = y - y_pred

        # Innovation covariance S = F * P_pred * F^T + R
        S = float(F @ P_pred @ F) + self._R

        # Kalman gain K = P_pred * F^T / S
        K = P_pred @ F / S

        # Update state
        self._theta = self._theta + K * innovation

        # Update covariance: P = (I - K*F) * P_pred
        I_KF = np.eye(2) - np.outer(K, F)
        self._P = I_KF @ P_pred

        alpha = float(self._theta[0])
        beta = float(self._theta[1])
        spread = float(innovation)  # same as y - F @ old_theta
        spread_std = float(np.sqrt(S))
        beta_std = float(np.sqrt(self._P[1, 1]))

        state = KalmanState(
            beta=beta,
            alpha=alpha,
            spread=spread,
            spread_std=spread_std,
            beta_std=beta_std,
            P=self._P.copy(),
        )
        self._history.append(state)
        return state

    def fit_series(
        self,
        y: pd.Series,
        x: pd.Series,
    ) -> pd.DataFrame:
        """
        Process full time series, returning state history as DataFrame.

        Parameters
        ----------
        y, x : pd.Series aligned by index.

        Returns
        -------
        pd.DataFrame with columns: alpha, beta, spread, spread_std, beta_std
        """
        aligned = pd.concat([y, x], axis=1).dropna()
        if aligned.empty:
            return pd.DataFrame()

        # Reset state
        self.__init__(delta=self.delta, obs_noise=self.obs_noise)

        records = []
        for ts, row in aligned.iterrows():
            state = self.update(float(row.iloc[0]), float(row.iloc[1]))
            records.append({
                "date": ts,
                "alpha": state.alpha,
                "beta": state.beta,
                "spread": state.spread,
                "spread_std": state.spread_std,
                "beta_std": state.beta_std,
                "spread_zscore": state.spread / max(state.spread_std, 1e-8),
            })

        return pd.DataFrame(records).set_index("date")

    def get_current_state(self) -> KalmanState | None:
        """Return the most recent Kalman state."""
        return self._history[-1] if self._history else None

    def spread_zscore(self) -> float:
        """Return current spread z-score (signal for mean-reversion)."""
        state = self.get_current_state()
        if state is None:
            return 0.0
        return state.spread / max(state.spread_std, 1e-8)
