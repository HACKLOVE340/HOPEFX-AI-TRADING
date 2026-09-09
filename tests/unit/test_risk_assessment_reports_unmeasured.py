# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""The risk *report* must not claim data quality nobody measured.

§E12 closed the gate: `size_order()` now refuses when data quality is
unmeasured, instead of scoring a dead feed a perfect 1.0. It deliberately left
the reporting side alone, because `RiskAssessment.data_quality` is typed
`float` and widening a published record is a bigger change than closing a
sizing hole. That was the right call for that commit and the wrong state to
leave permanently — this is §B item 17.

The remaining hole is narrow and real. `assess()` still calls
`_get_data_quality()`, which falls back to `1.0`:

    def _get_data_quality(self, signal) -> float:
        measured = self._measured_data_quality(signal)
        if measured is not None:
            return measured
        return float(getattr(signal, "data_quality", 1.0))

So a RiskAssessment produced with the feed down reads `data_quality: 1.0` —
"perfect" — beside a decision that had nothing to measure. The number is
carried into `_rejected_assessment` too, whose signature defaults it to 1.0
outright.

The type widens to `float | None`, and `None` means unmeasured. Blast radius
checked before writing this: nothing outside `risk/manager.py` reads the field
(`api/graphql_schema.py` builds a different assessment shape and never touches
`data_quality`), so this widens a record no external consumer depends on.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.unit


class _Tick:
    def __init__(self, confidence: float) -> None:
        self.confidence = confidence


class _Orch:
    def __init__(self, tick=None) -> None:
        self._tick = tick

    def get_latest_tick(self, symbol: str = "XAU_USD"):
        return self._tick

    def get_ml_features(self) -> dict:
        return {}


def _rm(orch=None):
    from risk.manager import RiskManager

    return RiskManager(orchestrator=orch, initial_balance=100_000.0)


def _signal():
    from core.domain_enums import TradeDirection
    from core.domain_models import Signal

    return Signal(
        strategy_id="test",
        symbol="XAUUSD",
        direction=TradeDirection.LONG,
        strength=0.7,
        confidence=0.7,
    )


class TestTheReportDistinguishesUnmeasuredFromPerfect:
    def test_an_unmeasured_feed_reports_none_not_one(self) -> None:
        assessment = _rm(orch=_Orch(tick=None)).assess(_signal())
        assert assessment.data_quality is None, "the risk report claims a data-quality figure that nothing measured"

    def test_no_orchestrator_reports_none(self) -> None:
        assert _rm(orch=None).assess(_signal()).data_quality is None

    def test_a_measured_feed_reports_its_value(self) -> None:
        assessment = _rm(orch=_Orch(tick=_Tick(0.83))).assess(_signal())
        assert assessment.data_quality == pytest.approx(0.83)

    def test_a_measured_zero_is_reported_as_zero(self) -> None:
        # 0.0 is a real reading and must survive the widening intact.
        assessment = _rm(orch=_Orch(tick=_Tick(0.0))).assess(_signal())
        assert assessment.data_quality == 0.0
        assert assessment.data_quality is not None


class TestAssessHasItsOwnGateWithTheSameHole:
    """`assess()` carries a *second* data-quality gate, missed by §E12.

        data_quality = self._get_data_quality(signal)      # 1.0 fallback
        ...
        if data_quality < _MIN_DATA_QUALITY:               # cannot fire

    §E12 fixed `size_order()` and left this one reading the fallback, so it can
    no more refuse an unmeasured feed than the original could. The trade is
    still rejected today — `assess()` calls `size_order()`, which does refuse —
    but the assessment reports `reason: "zero_size"` and `data_quality: 1.0`,
    naming neither the cause nor the truth. An operator reading the rejection
    cannot tell a dead feed from an ordinary zero-size result.
    """

    def test_an_unmeasured_feed_is_rejected_by_name(self) -> None:
        assessment = _rm(orch=_Orch(tick=None)).assess(_signal())
        assert assessment.approved is False
        assert "data_quality" in assessment.reason, f"the rejection does not name data quality: {assessment.reason!r}"
        assert "unmeasured" in assessment.reason

    def test_a_measured_poor_feed_keeps_reporting_its_number(self) -> None:
        from risk.manager import _MIN_DATA_QUALITY

        assessment = _rm(orch=_Orch(tick=_Tick(_MIN_DATA_QUALITY - 0.1))).assess(_signal())
        assert assessment.approved is False
        assert "data_quality" in assessment.reason
        assert "unmeasured" not in assessment.reason, "a real reading was reported as unmeasured"

    def test_the_gate_does_not_raise_on_none(self) -> None:
        # `None < 0.40` is a TypeError. Widening the type without widening the
        # comparison would trade a silent hole for a crash in the money path.
        _rm(orch=_Orch(tick=None)).assess(_signal())


class TestTheDefaultIsAbsenceNotPerfection:
    def test_riskassessment_defaults_to_none(self) -> None:
        from risk.manager import RiskAssessment

        blank = RiskAssessment(symbol="XAUUSD", direction="long", approved=False, risk_level="LOW", reason="test")
        assert blank.data_quality is None, "a fresh RiskAssessment asserts perfect data by default"

    def test_a_rejection_built_without_a_measurement_says_so(self) -> None:
        manager = _rm(orch=None)
        rejected = manager._rejected_assessment(_signal(), reason="test", risk_level="HIGH")
        assert rejected.data_quality is None


class TestTheGateItselfIsUnchanged:
    """§E12's fix must keep working — this commit touches reporting only."""

    def test_sizing_still_refuses_an_unmeasured_feed(self) -> None:
        result = _rm(orch=_Orch(tick=None)).size_order(_signal())
        assert result.quantity == 0
        assert result.reason == "data_quality:unmeasured"

    def test_measured_data_quality_still_returns_none_when_unmeasured(self) -> None:
        assert _rm(orch=_Orch(tick=None))._measured_data_quality(_signal()) is None
