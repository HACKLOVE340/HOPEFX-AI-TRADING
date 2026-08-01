from __future__ import annotations

import sys
from pathlib import Path

import pytest
import yaml
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from api.trading import get_regime_status
from core.app_state import app_state
from health_check_service import _check_database


REPO_ROOT = Path(__file__).resolve().parents[2]


def _ci_job_steps() -> dict[str, dict]:
    workflow = yaml.safe_load((REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text())
    return {
        step["name"]: step for step in workflow["jobs"]["test"]["steps"] if isinstance(step, dict) and "name" in step
    }


def test_ci_runtime_steps_export_database_url() -> None:
    steps = _ci_job_steps()

    for step_name in (
        "Run tests with coverage (full suite, 70% baseline)",
        "Runtime invariant check (output invariants)",
    ):
        env = steps[step_name]["env"]
        assert env["DATABASE_URL"] == env["DB_URL"]


@pytest.mark.asyncio
async def test_health_ready_accepts_sync_sqlalchemy_engine() -> None:
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    previous_engine = getattr(app_state, "db_engine", None)
    app_state.db_engine = engine
    try:
        result = await _check_database()
    finally:
        app_state.db_engine = previous_engine
        engine.dispose()

    assert result.status == "ok"
    assert result.detail == "SELECT 1 OK"


@pytest.mark.asyncio
async def test_regime_status_skips_remote_fetch_in_testing(monkeypatch: pytest.MonkeyPatch) -> None:
    class ForbiddenYFinanceModule:
        def __getattr__(self, name: str) -> object:
            raise AssertionError(f"yfinance should not be accessed in tests (requested {name})")

    monkeypatch.delenv("APP_ENV", raising=False)
    monkeypatch.setenv("ENVIRONMENT", "testing")
    monkeypatch.setitem(sys.modules, "yfinance", ForbiddenYFinanceModule())

    result = await get_regime_status(user=object())

    assert result["data_source"] == "fallback"
    assert result["current_regime"] == result["regime"]
