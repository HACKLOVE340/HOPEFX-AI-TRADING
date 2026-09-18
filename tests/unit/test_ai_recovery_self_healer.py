from __future__ import annotations

import pytest

from security.self_healer import SelfHealer


@pytest.mark.asyncio
async def test_self_healer_ai_assessment_is_fail_closed_and_non_mutating(monkeypatch) -> None:
    healer = SelfHealer.__new__(SelfHealer)

    async def fake_diagnostics() -> dict:
        return {"results": [{"check_name": "database", "status": "critical", "message": "unavailable"}]}

    monkeypatch.setattr(healer, "run_diagnostics_now", fake_diagnostics)

    result = await healer.run_ai_recovery_assessment("healer-observation")

    assert result["decision"]["action"] == "escalate"
    assert result["decision"]["status"] == "escalated"
    assert result["repair_applied"] is False
    assert result["observation"]["observation_hash"]
