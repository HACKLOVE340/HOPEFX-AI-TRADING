# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""When the model abstains, the caller must be told why.

Found by running the AI, not by reading it. Handed a 300-bar hourly window,
`InferenceEngine.predict()` returned:

    {"direction": "neutral", "probability": 0.5, "confidence": 0.0,
     "model_version": "fallback", "fallback": True, ...}

and nothing else. No reason in the result, and nothing in the logs at INFO or
WARNING. The abstention was *correct* — 300 hourly bars resample to roughly 12
daily ones, below `_MIN_BARS`, and the model is trained on daily data, so it
refused rather than guessing. That is the behaviour anyone would want.

The problem is that the reason existed and went somewhere the caller cannot
read. Every abstention path does:

    _PROM.fallback_total.labels(symbol=..., reason="insufficient_daily_bars").inc()
    logger.debug(...)          # DEBUG is off in production
    return base_result         # carries no reason

So the cause is recorded in a Prometheus label, and `HOPEFXDecisionEngine`,
`core/signal_engine.py` and the dashboards — every actual consumer of
`predict()` — see a flat neutral with no explanation. Reading it back out of the
metrics registry is how this was diagnosed at all.

Ten abstention paths behave this way: insufficient_bars, insufficient_daily_bars,
feature_build_failed, feature_validation_failed, stale_model, feature_drift,
model_fallback, reduced_feature_set, nan_features, all_zero_features. A neutral
signal is the system declining to trade; an operator who cannot tell a short
data window from a drifting model from a stale artifact cannot act on it.

`predict()` now returns `reason` alongside `fallback`, and the counter keeps
its label — the metric and the payload agree rather than one of them knowing
something the other does not.
"""

from __future__ import annotations

import logging

import numpy as np
import pandas as pd
import pytest

pytestmark = pytest.mark.unit


def _bars(n: int, freq: str = "h") -> pd.DataFrame:
    rng = np.random.default_rng(7)
    close = 3300 * np.exp(np.cumsum(rng.normal(0.0002, 0.004, n)))
    open_ = np.r_[close[0], close[:-1]]
    return pd.DataFrame(
        {
            "open": open_,
            "high": np.maximum(open_, close) * 1.001,
            "low": np.minimum(open_, close) * 0.999,
            "close": close,
            "volume": rng.integers(800, 5000, n).astype(float),
        },
        index=pd.date_range("2026-08-27", periods=n, freq=freq, tz="UTC"),
    )


@pytest.fixture(scope="module")
def engine():
    from ml.inference_engine import get_inference_engine

    return get_inference_engine()


class TestAnAbstentionCarriesItsReason:
    def test_too_few_bars_says_so(self, engine) -> None:
        out = engine.predict(_bars(5), symbol="XAU_USD")
        assert out["fallback"] is True
        assert out.get("reason") == "insufficient_bars", (
            "the model abstained and the result does not say why — the cause only "
            f"reached Prometheus. Got: {out.get('reason')!r}"
        )

    def test_too_few_daily_bars_after_resampling_says_so(self, engine) -> None:
        # 300 hourly bars is ~12 daily. This is the exact case that surfaced it.
        out = engine.predict(_bars(300), symbol="XAU_USD")
        assert out["fallback"] is True
        assert out.get("reason") == "insufficient_daily_bars"

    def test_the_reason_is_always_present_when_falling_back(self, engine) -> None:
        # Whatever the path, `fallback: True` without a reason is the defect.
        for n in (1, 5, 60, 300):
            out = engine.predict(_bars(n), symbol="XAU_USD")
            if out.get("fallback"):
                assert out.get("reason"), f"fallback with no reason for {n} bars: {out}"

    def test_reason_is_absent_or_empty_when_not_falling_back(self, engine) -> None:
        # A real prediction must not carry a stray abstention reason.
        out = engine.predict(_bars(400, freq="D"), symbol="XAU_USD")
        if not out.get("fallback"):
            assert not out.get("reason"), f"a served prediction claims a fallback reason: {out.get('reason')!r}"


class TestTheAbstentionIsAudible:
    """DEBUG is off in production. A refusal to trade is not a debug detail."""

    def test_abstaining_logs_above_debug(self, engine, caplog) -> None:
        with caplog.at_level(logging.INFO, logger="ml.inference_engine"):
            engine.predict(_bars(300), symbol="XAU_USD")
        assert any(r.levelno >= logging.INFO for r in caplog.records), (
            "the model declined to predict and said nothing above DEBUG"
        )


class TestTheMetricAndThePayloadAgree:
    def test_the_returned_reason_matches_the_counter_label(self, engine) -> None:
        from prometheus_client import REGISTRY

        def counter_for(reason: str) -> float:
            total = 0.0
            for metric in REGISTRY.collect():
                if "fallback" not in metric.name:
                    continue
                for s in metric.samples:
                    if s.labels.get("reason") == reason and s.name.endswith("_total"):
                        total += s.value
            return total

        out = engine.predict(_bars(300), symbol="XAU_USD")
        reason = out.get("reason")
        assert reason, "no reason returned"
        assert counter_for(reason) > 0, (
            f"predict() reported reason={reason!r} but no counter carries that label — "
            "the metric and the payload disagree"
        )
