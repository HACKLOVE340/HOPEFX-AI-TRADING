# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""The data-quality gate in `size_order()` could not fire when the feed was down.

`RiskManager.size_order()` refuses to size a position when data quality is
below `RISK_MIN_DATA_QUALITY` (0.40). The value came from:

    def _get_data_quality(self, signal) -> float:
        if self._orch is not None:
            try:
                tick = self._orch.get_latest_tick()
                if tick is not None:
                    return tick.confidence
            except Exception as exc:
                logger.debug(...)
        return getattr(signal, "data_quality", 1.0)

`core.domain_models.Signal` has **no** `data_quality` field — verified by
introspection, not by reading — so that `getattr` default is not a fallback
that rarely fires. It is the answer in every case except "the orchestrator
returned a fresh tick":

* no orchestrator on the RiskManager
* `get_latest_tick()` raised
* `get_latest_tick()` returned None — Redis down, gold feed down, or the
  cached tick older than DQE_STALE_THRESHOLD_S (30s) and discarded

All of those scored **1.0 — perfect** — and sailed through `< 0.40`. So the
gate could only ever fire when the feed was *working* and honestly reporting
low confidence. In the condition it exists for — the feed being down or stale
— it was structurally unable to refuse. That is the "guard that can never
open" shape, in the position-sizing path.

## What changed, and what deliberately did not

`_measured_data_quality()` distinguishes three cases where the old code
collapsed all of them into 1.0:

1. the orchestrator produced a tick — that confidence is the measurement;
2. the caller *supplied* a `data_quality` — a backtest or replay that knows its
   own data has asserted it, so it is honoured;
3. neither — `None`, and `size_order()` refuses.

The distinction that matters is between a value a caller **supplied** and a
`getattr` **default**. The first is an assertion someone made; the second is
silence being read as perfection. Rule 2: an unmeasured value is absent, never
best case — and for a safety gate, absent has to behave like failure.

The same fabrication existed one level up. `_MinimalSignal` — the adapter
`calculate_position_size()` wraps its arguments in — hardcoded
`self.data_quality = 1.0` with no way for a caller to set it, so the **live**
decision-engine path (`HOPEFXDecisionEngine` → `calculate_position_size` →
`size_order`) asserted flawless data on every trade. It now defaults to `None`,
and `calculate_position_size()` takes a `data_quality` argument for callers who
genuinely have one.

`_get_data_quality()` keeps its old signature and its 1.0 fallback, because
`assess_risk()` uses it for *reporting* into `RiskAssessment.data_quality`
(typed `float`). Changing the gate is the safety fix; changing the reported
number is a separate, wider change and is tracked rather than smuggled in here.

Safe for the live paths: both build `RiskManager` **with** an orchestrator —
`hopefx_engine.py` explicitly, and `core/startup_factories.py::init_risk_manager`
for the FastAPI app the container actually runs. So the new refusal fires
exactly when that orchestrator cannot produce a tick, which is the condition the
gate was written for.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.unit


class _Tick:
    def __init__(self, confidence: float) -> None:
        self.confidence = confidence


class _Orch:
    """An orchestrator whose tick behaviour the test dictates."""

    def __init__(self, tick=None, raises: bool = False) -> None:
        self._tick = tick
        self._raises = raises

    def get_latest_tick(self, symbol: str = "XAU_USD"):
        if self._raises:
            raise RuntimeError("feed unavailable")
        return self._tick


def _rm(orch=None):
    """A real, fully constructed RiskManager wired to *orch*.

    `size_order()` reads halt state, drawdown and the state lock, so a
    hand-stubbed instance would test a different object than production runs.
    """
    from risk.manager import RiskManager

    return RiskManager(orchestrator=orch, initial_balance=100_000.0)


def _signal():
    """A real Signal — the object production actually passes."""
    from core.domain_enums import TradeDirection
    from core.domain_models import Signal

    return Signal(
        strategy_id="test",
        symbol="XAUUSD",
        direction=TradeDirection.LONG,
        strength=0.7,
        confidence=0.7,
    )


class TestTheSignalNeverCarriedDataQuality:
    """The premise of the whole defect, asserted rather than assumed."""

    def test_signal_has_no_data_quality_field(self) -> None:
        from core.domain_models import Signal

        assert "data_quality" not in Signal.model_fields, (
            "Signal now carries data_quality — the getattr fallback is no longer "
            "unconditional and this file's reasoning needs revisiting"
        )


class TestMeasuredDataQualityReportsAbsence:
    def test_no_orchestrator_is_unmeasured(self) -> None:
        assert _rm(orch=None)._measured_data_quality(_signal()) is None

    def test_a_raising_orchestrator_is_unmeasured(self) -> None:
        assert _rm(orch=_Orch(raises=True))._measured_data_quality(_signal()) is None

    def test_no_tick_is_unmeasured(self) -> None:
        # Redis down, gold feed down, or a cached tick too stale to trust.
        assert _rm(orch=_Orch(tick=None))._measured_data_quality(_signal()) is None

    def test_a_real_tick_is_measured(self) -> None:
        assert _rm(orch=_Orch(tick=_Tick(0.83)))._measured_data_quality(_signal()) == pytest.approx(0.83)

    def test_a_caller_supplied_value_counts_as_measured(self) -> None:
        # A backtest or replay knows its own data quality. That is an assertion
        # somebody made, not a default nobody chose.
        signal = _signal()
        signal_with_quality = type("_Supplied", (), {"data_quality": 0.55})()
        assert _rm(orch=None)._measured_data_quality(signal_with_quality) == pytest.approx(0.55)
        assert _rm(orch=None)._measured_data_quality(signal) is None

    def test_a_live_tick_beats_a_supplied_value(self) -> None:
        # The orchestrator is the authoritative source; a caller's guess must
        # not override a real measurement.
        supplied = type("_Supplied", (), {"data_quality": 1.0})()
        assert _rm(orch=_Orch(tick=_Tick(0.2)))._measured_data_quality(supplied) == pytest.approx(0.2)

    def test_a_non_numeric_supplied_value_is_unmeasured(self) -> None:
        junk = type("_Junk", (), {"data_quality": "excellent"})()
        assert _rm(orch=None)._measured_data_quality(junk) is None

    def test_a_malformed_tick_confidence_does_not_crash_sizing(self) -> None:
        # A bad confidence must degrade to "unmeasured" and be refused, not
        # raise out of the decision loop.
        manager = _rm(orch=_Orch(tick=_Tick("excellent")))
        assert manager._measured_data_quality(_signal()) is None
        assert manager.size_order(_signal()).quantity == 0


class TestTheGateCanNowFireWhenTheFeedIsDown:
    def _size(self, manager):
        return manager.size_order(_signal())

    def test_an_unmeasured_feed_refuses_to_size(self) -> None:
        # THE defect. Before this, a down feed scored 1.0 and sized normally.
        result = self._size(_rm(orch=_Orch(tick=None)))
        assert result.quantity == 0, "a feed that cannot be measured still sized a position"
        assert "data_quality" in (result.reason or "").lower()

    def test_no_orchestrator_refuses_to_size(self) -> None:
        result = self._size(_rm(orch=None))
        assert result.quantity == 0

    def test_a_raising_orchestrator_refuses_to_size(self) -> None:
        result = self._size(_rm(orch=_Orch(raises=True)))
        assert result.quantity == 0

    def test_a_measured_but_poor_feed_still_refuses(self) -> None:
        # The gate's original job, which must keep working.
        from risk.manager import _MIN_DATA_QUALITY

        result = self._size(_rm(orch=_Orch(tick=_Tick(_MIN_DATA_QUALITY - 0.1))))
        assert result.quantity == 0

    def test_a_measured_good_feed_is_not_refused_for_data_quality(self) -> None:
        # A gate that refuses everything is indistinguishable from a working one
        # until somebody tries to use it. This must not be rejected FOR DATA
        # QUALITY — other gates may still reject it, so the reason is what is
        # asserted, not the quantity.
        from risk.manager import _MIN_DATA_QUALITY

        result = self._size(_rm(orch=_Orch(tick=_Tick(_MIN_DATA_QUALITY + 0.5))))
        assert "data_quality" not in (result.reason or "").lower()


class TestCalculatePositionSizeNoLongerFabricates:
    """The live decision-engine path went through here, asserting a hardcoded 1.0."""

    def _size(self, manager, **kwargs):
        return manager.calculate_position_size(
            symbol="XAU_USD",
            entry_price=3300.0,
            account_equity=100_000.0,
            signal_strength=0.9,
            **kwargs,
        )

    def test_minimal_signal_no_longer_hardcodes_perfect_quality(self) -> None:
        from risk.manager import _MinimalSignal

        sig = _MinimalSignal(symbol="XAU_USD", direction="long", confidence=0.7, probability=0.6)
        assert sig.data_quality is None, "_MinimalSignal still fabricates a data-quality score"

    def test_an_unmeasured_caller_refuses_to_size(self) -> None:
        result = self._size(_rm(orch=None))
        assert result.quantity == 0
        assert "data_quality" in (result.reason or "").lower()

    def test_a_caller_that_supplies_quality_is_sized(self) -> None:
        result = self._size(_rm(orch=None), data_quality=1.0)
        assert result.quantity > 0

    def test_a_caller_that_supplies_poor_quality_is_refused(self) -> None:
        from risk.manager import _MIN_DATA_QUALITY

        result = self._size(_rm(orch=None), data_quality=_MIN_DATA_QUALITY - 0.1)
        assert result.quantity == 0
        assert "data_quality" in (result.reason or "").lower()


class TestRefusalsSayWhichGateRefused:
    def test_the_reason_names_the_gate_not_just_the_zero(self) -> None:
        # _zero_sizing used to log the reason and drop it, so every refusal
        # surfaced to callers as the generic "position_size_zero".
        result = _rm(orch=_Orch(tick=None)).size_order(_signal())
        assert result.reason != "position_size_zero"
        assert result.reason == "data_quality:unmeasured"


class TestReportingBehaviourIsDeliberatelyUnchanged:
    def test_get_data_quality_still_returns_a_float_for_reporting(self) -> None:
        # assess_risk() feeds this into RiskAssessment.data_quality, typed
        # float. Narrowing the gate must not change the reported record's
        # shape — that is a separate change, tracked separately.
        value = _rm(orch=_Orch(tick=None))._get_data_quality(_signal())
        assert isinstance(value, float)

    def test_get_data_quality_still_prefers_a_real_measurement(self) -> None:
        value = _rm(orch=_Orch(tick=_Tick(0.61)))._get_data_quality(_signal())
        assert value == pytest.approx(0.61)
