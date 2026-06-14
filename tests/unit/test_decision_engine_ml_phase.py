# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
tests/unit/test_decision_engine_ml_phase.py
===========================================
Regression tests for HOPEFXDecisionEngine._phase2_ml.

Pins two safety/correctness behaviours that were previously broken:

1. A RuntimeError from the inference engine (raised to BLOCK on a stale/drifted
   model when STALE_MODEL_BLOCK=true) must FILTER the signal (return None), not
   be swallowed so trading continues on base confidence.
2. InferenceEngine.predict() returns a dict; its calibrated confidence must
   actually be used (the old code hit float(raw[-1]) -> KeyError and silently
   discarded every ML output), while a deterministic fallback prediction must
   preserve the base confidence rather than zeroing the signal.
"""

from unittest.mock import MagicMock

import pytest

from core.decision.HOPEFXDecisionEngine import (
    DecisionContext,
    DecisionOutcome,
    DecisionPhase,
    DecisionResult,
    HOPEFXDecisionEngine,
)


def _engine(ml_predictor) -> HOPEFXDecisionEngine:
    eng = HOPEFXDecisionEngine(
        brain=MagicMock(),
        risk_manager=MagicMock(),
        gatekeeper=MagicMock(),
        trade_executor=MagicMock(),
        event_bus=MagicMock(),
        ml_predictor=ml_predictor,
        allow_concurrent=True,
    )
    # Isolate _phase2_ml: stub the OHLCV build and the optional phase-store blend.
    eng._build_ohlcv_df = lambda data: MagicMock()
    eng._apply_phase_stores = lambda prob, ctx: prob
    return eng


def _ctx() -> DecisionContext:
    return DecisionContext(symbol="XAUUSD", data={})


def _result() -> DecisionResult:
    import datetime as _dt

    return DecisionResult(
        decision_id="test",
        symbol="XAUUSD",
        timestamp=_dt.datetime.now(_dt.timezone.utc),
        phase_reached=DecisionPhase.SIGNAL if hasattr(DecisionPhase, "SIGNAL") else list(DecisionPhase)[0],
        outcome=DecisionOutcome.NO_SIGNAL if hasattr(DecisionOutcome, "NO_SIGNAL") else list(DecisionOutcome)[0],
    )


@pytest.mark.asyncio
async def test_stale_model_runtimeerror_filters_signal():
    """A predict() RuntimeError (stale/drift block) must filter, not degrade."""
    ml = MagicMock()
    ml.predict.side_effect = RuntimeError("model stale: 9 days > 7")
    eng = _engine(ml)

    out = await eng._phase2_ml(_ctx(), {"confidence": 0.99}, _result())

    assert out is None  # signal filtered, NOT traded on base confidence


@pytest.mark.asyncio
async def test_real_dict_prediction_confidence_used():
    """A real (non-fallback) dict prediction's calibrated confidence is used."""
    ml = MagicMock()
    ml.predict.return_value = {"confidence": 0.91, "probability": 0.88, "fallback": False}
    eng = _engine(ml)
    res = _result()

    out = await eng._phase2_ml(_ctx(), {"confidence": 0.10}, res)

    assert out == pytest.approx(0.91)
    assert res.ml_probability == pytest.approx(0.91)


@pytest.mark.asyncio
async def test_fallback_prediction_preserves_base_confidence():
    """On a deterministic fallback, base confidence is kept (not zeroed)."""
    ml = MagicMock()
    ml.predict.return_value = {"confidence": 0.0, "probability": 0.5, "fallback": True}
    eng = _engine(ml)

    out = await eng._phase2_ml(_ctx(), {"confidence": 0.80}, _result())

    assert out == pytest.approx(0.80)  # base confidence preserved


@pytest.mark.asyncio
async def test_low_real_confidence_filters():
    """A real prediction below the ML threshold filters the signal."""
    ml = MagicMock()
    ml.predict.return_value = {"confidence": 0.05, "fallback": False}
    eng = _engine(ml)
    res = _result()

    out = await eng._phase2_ml(_ctx(), {"confidence": 0.99}, res)

    assert out is None
    assert res.ml_probability == pytest.approx(0.05)
