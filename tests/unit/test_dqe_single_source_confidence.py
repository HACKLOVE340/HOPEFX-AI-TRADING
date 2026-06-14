# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
tests/unit/test_dqe_single_source_confidence.py
================================================
Regression: a single-source cross-source consensus has had no cross-validation,
so its confidence must be degraded relative to a multi-source consensus — the
DQE-level complement to the MIN_FEED_QUORUM gate.
"""

from __future__ import annotations

from datetime import datetime, timezone

from data_layer.quality.engine import DataQualityEngine
from data_layer.types import FeedSource, GoldTick

UTC = timezone.utc


def _tick(source: FeedSource, mid: float = 2000.0) -> GoldTick:
    return GoldTick(
        symbol="XAU_USD",
        timestamp=datetime.now(UTC),
        bid=mid - 0.5,
        ask=mid + 0.5,
        mid=mid,
        source=source,
    )


def test_single_source_confidence_is_degraded():
    dqe = DataQualityEngine()
    t1 = _tick(FeedSource.GOLDAPI)
    t2 = _tick(FeedSource.METALS_DEV)

    _, conf_single, _ = dqe.cross_source_consensus({FeedSource.GOLDAPI: t1})
    _, conf_multi, _ = dqe.cross_source_consensus(
        {FeedSource.GOLDAPI: t1, FeedSource.METALS_DEV: t2}
    )

    assert conf_single > 0.0
    # Two aligned sources cross-validate → higher confidence than a lone source.
    assert conf_single < conf_multi
