# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
tests/unit/test_dqe_future_timestamp.py
=======================================
Regression test: DataQualityEngine.validate_tick must reject ticks whose
timestamp is implausibly in the future (feed clock skew / ms-vs-epoch parse
error). A future tick clamps its measured latency to 0, making it look like the
freshest source and inflating its confidence-weighted consensus contribution.
"""

from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone

from data_layer.quality.engine import DataQualityEngine
from data_layer.types import FeedSource, GoldTick, TickQuality

UTC = timezone.utc


def _tick(ts: datetime) -> GoldTick:
    return GoldTick(
        symbol="XAU_USD",
        timestamp=ts,
        bid=1999.5,
        ask=2000.5,
        mid=2000.0,
        source=FeedSource.GOLDAPI,
    )


def test_future_dated_tick_rejected():
    dqe = DataQualityEngine()
    received_at = time.time()
    future_ts = datetime.now(UTC) + timedelta(seconds=60)  # 60s ahead
    out = dqe.validate_tick(_tick(future_ts), received_at=received_at)
    assert out.quality == TickQuality.REJECTED


def test_fresh_tick_not_rejected_for_timestamp():
    dqe = DataQualityEngine()
    received_at = time.time()
    now_ts = datetime.now(UTC)
    out = dqe.validate_tick(_tick(now_ts), received_at=received_at)
    # A current tick must not be rejected on the future-timestamp rule.
    assert out.quality != TickQuality.REJECTED


def test_small_clock_skew_tolerated():
    dqe = DataQualityEngine()
    received_at = time.time()
    # 2s ahead is within the default 5s skew tolerance — must be accepted.
    skewed_ts = datetime.now(UTC) + timedelta(seconds=2)
    out = dqe.validate_tick(_tick(skewed_ts), received_at=received_at)
    assert out.quality != TickQuality.REJECTED
