# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
risk/crowding.py
=================
Strategy crowding / factor crowding risk monitor.

Detects when multiple strategies or market participants are crowded
into the same factors or positions, creating systemic unwinding risk.

Metrics:
  - Factor concentration: Herfindahl-Hirschman Index (HHI) per factor
  - Strategy overlap: pairwise cosine similarity of weight vectors
  - Crowding score: composite crowding risk metric
  - Crowding alerts: when above threshold

Reference:
  Khandani, A. & Lo, A. (2007). What Happened To The Quants In August 2007?
  Chincarini, L. (2012). The Crisis of Crowding. Wiley.
"""
from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

import numpy as np
import pandas as pd

UTC = timezone.utc
logger = logging.getLogger(__name__)

_CROWDING_WARN_THRESHOLD = float(
    __import__("os").getenv("CROWDING_WARN_THRESHOLD", "0.6")
)
_CROWDING_CRITICAL_THRESHOLD = float(
    __import__("os").getenv("CROWDING_CRITICAL_THRESHOLD", "0.80")
)


@dataclass
class CrowdingSnapshot:
    """Crowding risk snapshot."""
    timestamp: datetime
    hhi_by_factor: dict[str, float]
    """Factor → HHI (0 = diversified, 1 = fully concentrated)."""
    max_hhi: float
    strategy_overlaps: dict[str, float]
    """'stratA_stratB' → cosine similarity."""
    max_overlap: float
    composite_crowding_score: float
    """0 = uncrowded, 1 = fully crowded."""
    status: str
    """'ok', 'warning', 'critical'"""
    top_crowded_factors: list[str]
    """Factors with highest concentration."""


class CrowdingMonitor:
    """
    Factor and strategy crowding risk monitor.

    Tracks exposure concentrations across strategies and factors
    to detect emerging crowding risk before a potential unwind.
    """

    def __init__(
        self,
        warn_threshold: float = _CROWDING_WARN_THRESHOLD,
        critical_threshold: float = _CROWDING_CRITICAL_THRESHOLD,
    ) -> None:
        self.warn_threshold = warn_threshold
        self.critical_threshold = critical_threshold
        self._strategy_weights: dict[str, dict[str, float]] = {}
        self._factor_exposures: dict[str, dict[str, float]] = {}
        self._history: list[CrowdingSnapshot] = []

    def update_strategy_weights(
        self, strategy_name: str, weights: dict[str, float]
    ) -> None:
        """Register or update a strategy's asset weights."""
        self._strategy_weights[strategy_name] = dict(weights)

    def update_factor_exposures(
        self, strategy_name: str, factor_exposures: dict[str, float]
    ) -> None:
        """Register or update a strategy's factor exposures (betas)."""
        self._factor_exposures[strategy_name] = dict(factor_exposures)

    def compute_hhi(self, weights: dict[str, float]) -> float:
        """
        Herfindahl-Hirschman Index of concentration.

        HHI = sum(w_i^2) for all weights.
        HHI = 1/N for equal weight, 1.0 for single asset.
        """
        w_arr = np.array(list(weights.values()), dtype=float)
        total = w_arr.sum()
        if total == 0:
            return 0.0
        w_norm = w_arr / total
        return float(np.sum(w_norm ** 2))

    def compute_factor_hhi(self) -> dict[str, float]:
        """
        Compute HHI per factor across all strategies.

        For each factor f: HHI_f = sum(exposure_{s,f}^2) / n_strategies^2
        """
        if not self._factor_exposures:
            return {}

        # Collect all factors
        all_factors: set[str] = set()
        for exps in self._factor_exposures.values():
            all_factors.update(exps.keys())

        hhi_by_factor: dict[str, float] = {}
        for factor in all_factors:
            exposures = np.array([
                abs(self._factor_exposures[s].get(factor, 0.0))
                for s in self._factor_exposures
            ], dtype=float)
            total = exposures.sum()
            if total > 0:
                norm = exposures / total
                hhi_by_factor[factor] = float(np.sum(norm ** 2))
            else:
                hhi_by_factor[factor] = 0.0

        return hhi_by_factor

    def compute_overlap(self) -> dict[str, float]:
        """
        Compute pairwise cosine similarity between strategy weight vectors.

        High similarity = strategies likely to unwind together.
        """
        strategies = list(self._strategy_weights.keys())
        if len(strategies) < 2:
            return {}

        # Build common asset universe
        all_assets: list[str] = sorted(
            set(a for w in self._strategy_weights.values() for a in w)
        )

        vectors = {}
        for s in strategies:
            v = np.array([self._strategy_weights[s].get(a, 0.0) for a in all_assets])
            vectors[s] = v

        overlaps: dict[str, float] = {}
        for i, s1 in enumerate(strategies):
            for s2 in strategies[i + 1 :]:
                v1, v2 = vectors[s1], vectors[s2]
                n1, n2 = np.linalg.norm(v1), np.linalg.norm(v2)
                if n1 > 0 and n2 > 0:
                    sim = float(v1 @ v2 / (n1 * n2))
                else:
                    sim = 0.0
                overlaps[f"{s1}_{s2}"] = sim

        return overlaps

    def snapshot(self) -> CrowdingSnapshot:
        """Compute and return current crowding snapshot."""
        now = datetime.now(UTC)

        hhi_by_factor = self.compute_factor_hhi()
        max_hhi = max(hhi_by_factor.values(), default=0.0)
        top_factors = sorted(
            hhi_by_factor, key=hhi_by_factor.get, reverse=True  # type: ignore
        )[:5]

        overlaps = self.compute_overlap()
        max_overlap = max(overlaps.values(), default=0.0)

        # Composite crowding score: average of max_hhi and max_overlap
        composite = (max_hhi + max_overlap) / 2.0

        if composite >= self.critical_threshold:
            status = "critical"
        elif composite >= self.warn_threshold:
            status = "warning"
        else:
            status = "ok"

        snap = CrowdingSnapshot(
            timestamp=now,
            hhi_by_factor=hhi_by_factor,
            max_hhi=max_hhi,
            strategy_overlaps=overlaps,
            max_overlap=max_overlap,
            composite_crowding_score=composite,
            status=status,
            top_crowded_factors=top_factors,
        )
        self._history.append(snap)
        return snap

    def health(self) -> dict[str, Any]:
        """Return health dict for API endpoint."""
        snap = self.snapshot()
        return {
            "status": snap.status,
            "composite_crowding_score": snap.composite_crowding_score,
            "max_hhi": snap.max_hhi,
            "max_overlap": snap.max_overlap,
            "n_strategies_tracked": len(self._strategy_weights),
            "n_factors_tracked": len(self._factor_exposures),
            "top_crowded_factors": snap.top_crowded_factors,
        }


# Module-level singleton
crowding_monitor = CrowdingMonitor()
