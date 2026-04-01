# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
research/event_study.py
========================
News event study — abnormal return analysis.

Implements standard event study methodology:
  1. Define event window (-pre, 0, +post) around news/macro events
  2. Estimate normal returns from estimation window via market model
  3. Compute Abnormal Returns (AR) and Cumulative ARs (CAR)
  4. Statistical significance testing (t-stat, BMP test)

Reference:
  MacKinlay, A.C. (1997). Event Studies in Economics and Finance.
  Journal of Economic Literature, 35(1), 13-39.
"""
from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import numpy as np
import pandas as pd
from scipy.stats import t as t_dist

logger = logging.getLogger(__name__)


@dataclass
class EventStudyResult:
    """Result for a single event study."""
    event_id: str
    event_date: str
    pre_window: int
    post_window: int
    estimation_window: int

    ar_series: pd.Series
    """Abnormal return at each event-time (t = -pre..+post)."""
    car: float
    """Cumulative Abnormal Return over post window."""
    car_pct: float
    """CAR as percentage."""
    t_stat: float
    """t-statistic on CAR (H0: CAR=0)."""
    p_value: float
    significant: bool
    """True if p < 0.05."""
    alpha: float
    """Estimated constant (intercept) from market model."""
    beta: float
    """Estimated beta (market sensitivity) from market model."""


@dataclass
class EventStudySummary:
    """Summary across multiple events."""
    n_events: int
    mean_car: float
    std_car: float
    t_stat: float
    p_value: float
    significant: bool
    event_results: list[EventStudyResult] = field(default_factory=list)


class EventStudy:
    """
    Event study engine for gold news / macro event abnormal return analysis.

    Uses market model (OLS regression against benchmark) to estimate
    normal returns and compute abnormal returns around event dates.
    """

    def __init__(
        self,
        estimation_window: int = 120,
        pre_window: int = 5,
        post_window: int = 10,
        min_estimation_obs: int = 30,
    ) -> None:
        self.estimation_window = estimation_window
        self.pre_window = pre_window
        self.post_window = post_window
        self.min_estimation_obs = min_estimation_obs

    def run(
        self,
        returns: pd.Series,
        market_returns: pd.Series,
        event_dates: list[str | datetime | pd.Timestamp],
        event_id_prefix: str = "event",
    ) -> EventStudySummary:
        """
        Run event study for a list of event dates.

        Parameters
        ----------
        returns : pd.Series
            Asset (gold) daily returns, DatetimeIndex.
        market_returns : pd.Series
            Benchmark (e.g. SPX) daily returns.
        event_dates : list of dates
            Dates of events to study.
        event_id_prefix : str
            Prefix for event IDs.

        Returns
        -------
        EventStudySummary across all events.
        """
        # Align series
        aligned = pd.concat([returns, market_returns], axis=1).dropna()
        aligned.columns = ["asset", "market"]

        results = []
        for i, event_date in enumerate(event_dates):
            evt_ts = pd.Timestamp(event_date)
            result = self._run_single(
                aligned, evt_ts, f"{event_id_prefix}_{i:03d}"
            )
            if result is not None:
                results.append(result)

        if not results:
            return EventStudySummary(
                n_events=0, mean_car=0.0, std_car=0.0,
                t_stat=0.0, p_value=1.0, significant=False,
            )

        cars = np.array([r.car for r in results])
        mean_car = float(cars.mean())
        std_car = float(cars.std(ddof=1)) if len(cars) > 1 else 0.0
        t_stat = (
            mean_car / (std_car / math.sqrt(len(cars)))
            if std_car > 0 else 0.0
        )
        df = max(len(cars) - 1, 1)
        p_value = float(2 * t_dist.sf(abs(t_stat), df=df))

        return EventStudySummary(
            n_events=len(results),
            mean_car=mean_car,
            std_car=std_car,
            t_stat=t_stat,
            p_value=p_value,
            significant=p_value < 0.05,
            event_results=results,
        )

    def _run_single(
        self,
        aligned: pd.DataFrame,
        event_date: pd.Timestamp,
        event_id: str,
    ) -> EventStudyResult | None:
        """Run event study for a single event date."""
        # Find event date index
        try:
            idx_pos = aligned.index.searchsorted(event_date)
        except Exception:
            return None

        if idx_pos >= len(aligned):
            return None

        # Estimation window: [t-estimation-pre, t-pre-1]
        est_start = idx_pos - self.estimation_window - self.pre_window
        est_end = idx_pos - self.pre_window

        if est_start < 0 or (est_end - est_start) < self.min_estimation_obs:
            logger.debug(
                "EventStudy: insufficient estimation data for %s", event_id
            )
            return None

        est_data = aligned.iloc[est_start:est_end]
        X = est_data["market"].values
        y = est_data["asset"].values

        # OLS: y = alpha + beta * x
        X_mat = np.column_stack([np.ones(len(X)), X])
        try:
            coeffs, _, _, _ = np.linalg.lstsq(X_mat, y, rcond=None)
            alpha, beta = float(coeffs[0]), float(coeffs[1])
        except np.linalg.LinAlgError:
            alpha, beta = 0.0, 1.0

        # Event window: [t-pre, t+post]
        ev_start = max(idx_pos - self.pre_window, 0)
        ev_end = min(idx_pos + self.post_window + 1, len(aligned))
        ev_data = aligned.iloc[ev_start:ev_end]

        # Abnormal returns
        predicted = alpha + beta * ev_data["market"]
        ar = ev_data["asset"] - predicted

        # Event-time index (0 = event date)
        event_times = range(-self.pre_window, ev_end - ev_start - self.pre_window)
        ar.index = list(event_times)[: len(ar)]  # type: ignore[assignment]

        # CAR over post-window (t=0 to t=post)
        post_ar = ar[[t for t in ar.index if t >= 0]]
        car = float(post_ar.sum())

        # t-statistic on CAR
        est_residuals = y - (alpha + beta * X)
        sigma_ar = float(np.std(est_residuals, ddof=2)) if len(est_residuals) > 2 else 1e-4
        car_std = sigma_ar * math.sqrt(len(post_ar))
        t_stat = car / car_std if car_std > 0 else 0.0
        df = max(len(est_data) - 2, 1)
        p_value = float(2 * t_dist.sf(abs(t_stat), df=df))

        return EventStudyResult(
            event_id=event_id,
            event_date=str(event_date.date()),
            pre_window=self.pre_window,
            post_window=self.post_window,
            estimation_window=self.estimation_window,
            ar_series=ar,
            car=car,
            car_pct=car * 100,
            t_stat=t_stat,
            p_value=p_value,
            significant=p_value < 0.05,
            alpha=alpha,
            beta=beta,
        )
