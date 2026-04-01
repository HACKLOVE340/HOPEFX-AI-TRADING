# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
ml/realized_vol.py
===================
Realized Volatility (RV) and HAR-RV (Heterogeneous Autoregressive) model.

Implements:
  1. Realized Variance/Volatility from intraday returns (Andersen & Bollerslev)
  2. Bipower Variation (jump-robust RV estimator)
  3. HAR-RV model: daily, weekly, monthly volatility components
  4. HAR-RV forecasting (1-day, 5-day, 22-day horizons)

Reference:
  Corsi, F. (2009). A Simple Approximate Long-Memory Model of Realized Volatility.
  Journal of Financial Econometrics, 7(2), 174-196.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

import numpy as np
import pandas as pd
from sklearn.linear_model import Ridge

logger = logging.getLogger(__name__)


@dataclass
class HARRVResult:
    """HAR-RV model fit and forecast result."""
    model_coeffs: dict[str, float]
    """Fitted coefficients: intercept, beta_d, beta_w, beta_m."""
    r_squared: float
    """In-sample R²."""
    forecast_1d: float
    """1-day ahead RV forecast."""
    forecast_5d: float
    """5-day ahead RV forecast (average daily)."""
    forecast_22d: float
    """22-day ahead RV forecast (average daily)."""
    rv_series: pd.Series
    """Historical daily realised volatility."""
    n_observations: int


def realized_variance(
    intraday_returns: pd.Series | np.ndarray,
    annualise: bool = False,
    frequency: int = 252,
) -> float:
    """
    Compute Realized Variance from intraday returns.

    RV_t = sum(r_{t,i}^2) for i = 1..M intraday periods

    Parameters
    ----------
    intraday_returns : array-like
        Intraday log-returns within a single day.
    annualise : bool
        Multiply by frequency for annualised variance.
    frequency : int
        Trading days per year for annualisation.

    Returns
    -------
    float — realized variance
    """
    r = np.asarray(intraday_returns, dtype=float)
    r = r[~np.isnan(r)]
    rv = float(np.sum(r ** 2))
    if annualise:
        rv *= frequency
    return rv


def bipower_variation(
    intraday_returns: pd.Series | np.ndarray,
) -> float:
    """
    Bipower Variation (jump-robust realized variance estimator).

    BV_t = (π/2) * sum(|r_{t,i}| * |r_{t,i-1}|)

    Consistent estimator of integrated variance even in presence of jumps.
    """
    r = np.asarray(intraday_returns, dtype=float)
    r = r[~np.isnan(r)]
    if len(r) < 2:
        return 0.0
    bv = float(np.pi / 2) * float(np.sum(np.abs(r[1:]) * np.abs(r[:-1])))
    return bv


def daily_rv_from_ohlcv(
    ohlcv: pd.DataFrame,
    method: str = "parkinson",
) -> pd.Series:
    """
    Estimate daily realised volatility from OHLCV bars.

    Parameters
    ----------
    ohlcv : pd.DataFrame
        Must have columns: open, high, low, close (case-insensitive).
    method : str
        'parkinson'    — Parkinson (1980) range estimator
        'garman_klass' — Garman-Klass (1980) open-high-low-close estimator
        'close'        — Simple close-to-close returns

    Returns
    -------
    pd.Series of daily RV (variance units, i.e. squared returns)
    """
    cols = {c.lower(): c for c in ohlcv.columns}
    h = ohlcv[cols.get("high", "high")].astype(float)
    lo = ohlcv[cols.get("low", "low")].astype(float)
    o = ohlcv[cols.get("open", "open")].astype(float)
    c = ohlcv[cols.get("close", "close")].astype(float)

    if method == "parkinson":
        # Parkinson: RV = (1 / (4*ln2)) * (ln(H/L))^2
        rv = (1 / (4 * np.log(2))) * (np.log(h / lo.replace(0, float("nan")))) ** 2
    elif method == "garman_klass":
        # Garman-Klass: RV = 0.5*(ln(H/L))^2 - (2*ln2-1)*(ln(C/O))^2
        hl_term = 0.5 * (np.log(h / lo.replace(0, float("nan")))) ** 2
        co_term = (2 * np.log(2) - 1) * (np.log(c / o.replace(0, float("nan")))) ** 2
        rv = hl_term - co_term
    else:
        # Close-to-close
        log_ret = np.log(c / c.shift(1))
        rv = log_ret ** 2

    return rv.dropna().rename("rv")


class HARV:
    """
    Heterogeneous AutoRegressive model for Realized Volatility (HAR-RV).

    Captures persistence at daily (d), weekly (w=5), and monthly (m=22)
    horizons via a simple OLS regression on lagged RV components.

    Model: RV_{t+1} = c + β_d * RV_d_t + β_w * RV_w_t + β_m * RV_m_t + ε
    where:
      RV_d_t = RV_t
      RV_w_t = (1/5)  * sum(RV_{t-4:t})
      RV_m_t = (1/22) * sum(RV_{t-21:t})
    """

    def __init__(self, alpha: float = 1e-4) -> None:
        """
        Parameters
        ----------
        alpha : float
            Ridge regularisation parameter. Default 1e-4.
        """
        self._model: Ridge | None = None
        self._alpha = alpha

    def fit(self, rv_series: pd.Series) -> HARRVResult:
        """
        Fit HAR-RV model.

        Parameters
        ----------
        rv_series : pd.Series
            Daily realised volatility (or variance). Must have DatetimeIndex.

        Returns
        -------
        HARRVResult
        """
        rv = rv_series.dropna().astype(float)
        n = len(rv)
        if n < 30:
            raise ValueError("HAR-RV requires at least 30 observations")

        rv_arr = rv.values

        # Build feature matrix
        rv_d = rv_arr  # daily
        rv_w = pd.Series(rv_arr).rolling(5).mean().values  # weekly avg
        rv_m = pd.Series(rv_arr).rolling(22).mean().values  # monthly avg

        # Align: predict RV_{t+1} from RV components at t
        valid_start = 22  # first valid row
        X = np.column_stack([
            rv_d[valid_start:-1],
            rv_w[valid_start:-1],
            rv_m[valid_start:-1],
        ])
        y = rv_arr[valid_start + 1:]

        self._model = Ridge(alpha=self._alpha, fit_intercept=True)
        self._model.fit(X, y)

        y_pred = self._model.predict(X)
        ss_res = float(np.sum((y - y_pred) ** 2))
        ss_tot = float(np.sum((y - y.mean()) ** 2))
        r2 = 1.0 - ss_res / ss_tot if ss_tot > 0 else 0.0

        coeffs = {
            "intercept": float(self._model.intercept_),
            "beta_d": float(self._model.coef_[0]),
            "beta_w": float(self._model.coef_[1]),
            "beta_m": float(self._model.coef_[2]),
        }

        # 1-step forecast
        fc1 = self._forecast_step(rv_arr, rv_w, rv_m)

        # 5-day and 22-day forecasts (iterated 1-step)
        fc5 = self._iterated_forecast(rv_arr, rv_w, rv_m, horizon=5)
        fc22 = self._iterated_forecast(rv_arr, rv_w, rv_m, horizon=22)

        logger.info(
            "HAR-RV: fitted n=%d, R²=%.4f, fc1=%.6f", n, r2, fc1
        )

        return HARRVResult(
            model_coeffs=coeffs,
            r_squared=r2,
            forecast_1d=fc1,
            forecast_5d=fc5,
            forecast_22d=fc22,
            rv_series=rv,
            n_observations=n,
        )

    def _forecast_step(
        self,
        rv_arr: np.ndarray,
        rv_w: np.ndarray,
        rv_m: np.ndarray,
    ) -> float:
        """1-step ahead forecast from most recent data point."""
        if self._model is None:
            return 0.0
        X_pred = np.array([[rv_arr[-1], rv_w[-1], rv_m[-1]]])
        pred = float(self._model.predict(X_pred)[0])
        return max(pred, 0.0)

    def _iterated_forecast(
        self,
        rv_arr: np.ndarray,
        rv_w: np.ndarray,
        rv_m: np.ndarray,
        horizon: int,
    ) -> float:
        """Iterated multi-step forecast (average daily RV over horizon)."""
        if self._model is None:
            return 0.0

        rv_trail = list(rv_arr[-22:])
        forecasts = []
        for _ in range(horizon):
            d = rv_trail[-1]
            w = float(np.mean(rv_trail[-5:]))
            m = float(np.mean(rv_trail[-22:]))
            fc = float(self._model.predict([[d, w, m]])[0])
            fc = max(fc, 0.0)
            forecasts.append(fc)
            rv_trail.append(fc)

        return float(np.mean(forecasts))
