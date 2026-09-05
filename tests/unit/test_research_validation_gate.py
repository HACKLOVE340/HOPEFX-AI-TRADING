from __future__ import annotations

import pytest

from ml.research_validation_gate import evaluate_research_validation


def test_research_gate_passes_only_with_all_evidence() -> None:
    evidence = evaluate_research_validation(
        replay_ok=True,
        walk_forward_ok=True,
        leakage_check_ok=True,
        slippage_costs_ok=True,
        model_quality_ok=True,
    )

    assert evidence.passed is True
    evidence.require_pass()


def test_research_gate_fails_closed_with_reason_codes() -> None:
    evidence = evaluate_research_validation(
        replay_ok=True,
        walk_forward_ok=False,
        leakage_check_ok=True,
        slippage_costs_ok=False,
        model_quality_ok=True,
    )

    assert evidence.passed is False
    assert evidence.reason_codes == ("walk_forward_failed", "slippage_costs_failed")
    with pytest.raises(RuntimeError, match="walk_forward_failed"):
        evidence.require_pass()
