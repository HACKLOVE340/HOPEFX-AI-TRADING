# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
api/chaos.py
=============
Chaos engineering + mutation testing API endpoints.

Routes
------
POST /api/chaos/run              — run all chaos scenarios
POST /api/chaos/scenario/{name}  — run a single named scenario
GET  /api/chaos/results          — last chaos run results
POST /api/chaos/mutation/run     — trigger mutation testing (async)
GET  /api/chaos/mutation/results — last mutation test report
GET  /api/chaos/status           — combined chaos + mutation status

All write endpoints require admin role.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

UTC = timezone.utc
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request

from api.auth import TokenPayload, get_current_user, require_role
from pydantic import BaseModel

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/chaos", tags=["Chaos & Mutation Testing"])

# ── Response models ───────────────────────────────────────────────────────────


class ScenarioResultOut(BaseModel):
    scenario: str
    passed: bool
    duration_s: float
    sla_s: float
    within_sla: bool
    detail: str


class ChaosRunResponse(BaseModel):
    run_id: str
    started_at: str
    scenarios: list[ScenarioResultOut]
    total: int
    passed: int
    failed: int
    report: str


class MutationRunResponse(BaseModel):
    status: str  # "started" | "completed" | "error"
    run_id: str
    message: str


class MutationResultOut(BaseModel):
    engine: str
    modules: list[str]
    total: int
    killed: int
    survived: int
    timeouts: int
    score: float
    passed: bool
    min_score: float
    duration_s: float
    generated_at: str
    summary: str


class ChaosStatusResponse(BaseModel):
    chaos_last_run: str | None
    chaos_passed: int | None
    chaos_failed: int | None
    mutation_score: float | None
    mutation_passed: bool | None
    mutation_engine: str | None
    mutation_last_run: str | None


# ── In-memory state (replaced on each run) ───────────────────────────────────

_last_chaos_results: list[dict] = []
_last_chaos_run_at: str | None = None
_mutation_running: bool = False
_last_mutation_report: dict | None = None


# ── Dependency: get ChaosController from app state ───────────────────────────


def _get_chaos_controller(request: Request) -> Any:
    ctrl = getattr(request.app.state, "chaos_controller", None)
    if ctrl is None:
        raise HTTPException(
            status_code=503,
            detail="ChaosController not initialised — check startup logs",
        )
    return ctrl


def _get_mutation_runner(request: Request) -> Any:
    from chaos.mutation_runner import MutationTestRunner

    runner = getattr(request.app.state, "mutation_runner", None)
    if runner is None:
        # Create on demand — no persistent state needed
        runner = MutationTestRunner()
        request.app.state.mutation_runner = runner
    return runner


# ── Endpoints ─────────────────────────────────────────────────────────────────


@router.post("/run", response_model=ChaosRunResponse)
async def run_all_chaos_scenarios(
    user: TokenPayload = Depends(require_role("admin")),
    controller: Any = Depends(_get_chaos_controller),
) -> ChaosRunResponse:
    """
    Run all chaos scenarios against the live data pipeline (paper mode only).

    Scenarios: DQE spike rejection, stale tick detection, spread gate,
    corrupt tick rejection, clock skew detection, feed drop recovery.
    """
    global _last_chaos_results, _last_chaos_run_at

    import uuid

    run_id = str(uuid.uuid4())[:8]
    started_at = datetime.now(UTC).isoformat()

    logger.warning("CHAOS RUN %s started by API", run_id)

    await controller.run_all_scenarios()
    report_text = controller.report()

    _last_chaos_results = controller.results_dict()
    _last_chaos_run_at = started_at

    out_results = [
        ScenarioResultOut(
            scenario=r["scenario"],
            passed=r["passed"],
            duration_s=r["duration_s"],
            sla_s=r["sla_s"],
            within_sla=r["within_sla"],
            detail=r["detail"],
        )
        for r in _last_chaos_results
    ]

    passed = sum(1 for r in out_results if r.passed)
    return ChaosRunResponse(
        run_id=run_id,
        started_at=started_at,
        scenarios=out_results,
        total=len(out_results),
        passed=passed,
        failed=len(out_results) - passed,
        report=report_text,
    )


@router.post("/scenario/{scenario_name}", response_model=ScenarioResultOut)
async def run_single_scenario(
    scenario_name: str,
    user: TokenPayload = Depends(require_role("admin")),
    controller: Any = Depends(_get_chaos_controller),
) -> ScenarioResultOut:
    """
    Run a single named chaos scenario.

    Valid names: dqe_spike_rejection, stale_tick_detection, spread_gate,
    corrupt_tick_rejection, clock_skew_detection, feed_drop_recovery
    """
    scenario_map = {
        "dqe_spike_rejection": "_scenario_dqe_spike_rejection",
        "stale_tick_detection": "_scenario_stale_tick_detection",
        "spread_gate": "_scenario_spread_gate",
        "corrupt_tick_rejection": "_scenario_corrupt_tick_rejection",
        "clock_skew_detection": "_scenario_clock_skew_detection",
        "feed_drop_recovery": "_scenario_feed_drop_recovery",
    }

    method_name = scenario_map.get(scenario_name)
    if method_name is None:
        raise HTTPException(
            status_code=404,
            detail=f"Unknown scenario '{scenario_name}'. Valid: {list(scenario_map.keys())}",
        )

    method = getattr(controller, method_name, None)
    if method is None:
        raise HTTPException(status_code=500, detail=f"Scenario method not found: {method_name}")

    logger.warning("CHAOS SCENARIO %s triggered via API", scenario_name)
    result = await method()
    controller._inj.clear_all()

    return ScenarioResultOut(
        scenario=result.scenario,
        passed=result.passed,
        duration_s=result.duration_s,
        sla_s=result.sla_s,
        within_sla=result.within_sla,
        detail=result.detail,
    )


@router.get("/results", response_model=list[ScenarioResultOut])
async def get_chaos_results(user: TokenPayload = Depends(get_current_user)) -> list[ScenarioResultOut]:
    """Return results from the last chaos run."""
    if not _last_chaos_results:
        return []
    return [
        ScenarioResultOut(
            scenario=r["scenario"],
            passed=r["passed"],
            duration_s=r["duration_s"],
            sla_s=r["sla_s"],
            within_sla=r["within_sla"],
            detail=r["detail"],
        )
        for r in _last_chaos_results
    ]


@router.post("/mutation/run", response_model=MutationRunResponse)
async def run_mutation_tests(
    request: Request,
    background_tasks: BackgroundTasks,
    modules: str | None = None,
    user: TokenPayload = Depends(require_role("admin")),
    runner: Any = Depends(_get_mutation_runner),
) -> MutationRunResponse:
    """
    Trigger mutation testing in the background.

    modules: comma-separated list of module dirs to mutate
             (default: risk,execution,shadow)

    Returns immediately with run_id. Poll /api/chaos/mutation/results
    for completion.
    """
    if _mutation_running:
        raise HTTPException(
            status_code=409,
            detail="Mutation test already running — wait for it to complete",
        )

    import uuid

    run_id = str(uuid.uuid4())[:8]

    if modules:
        from chaos.mutation_runner import MutationTestRunner

        runner = MutationTestRunner(modules=modules.split(","))
        request.app.state.mutation_runner = runner

    async def _run_in_background():
        global _mutation_running, _last_mutation_report
        _mutation_running = True
        try:
            report = await runner.run()
            _last_mutation_report = {
                "engine": report.engine,
                "modules": report.modules,
                "total": report.total,
                "killed": report.killed,
                "survived": report.survived,
                "timeouts": report.timeouts,
                "score": report.score,
                "passed": report.passed,
                "min_score": report.min_score,
                "duration_s": round(report.duration_s, 2),
                "generated_at": report.generated_at,
                "summary": report.summary(),
            }
        except Exception as exc:
            logger.error("Background mutation run failed: %s", exc)
        finally:
            _mutation_running = False

    background_tasks.add_task(_run_in_background)

    return MutationRunResponse(
        status="started",
        run_id=run_id,
        message=f"Mutation testing started (run_id={run_id}). Poll /api/chaos/mutation/results for completion.",
    )


@router.get("/mutation/results", response_model=MutationResultOut | None)
async def get_mutation_results(user: TokenPayload = Depends(require_role("admin"))) -> MutationResultOut | None:
    """Return the last mutation test report, or null if none has run."""
    if _last_mutation_report is None:
        return None
    r = _last_mutation_report
    return MutationResultOut(
        engine=r["engine"],
        modules=r["modules"],
        total=r["total"],
        killed=r["killed"],
        survived=r["survived"],
        timeouts=r["timeouts"],
        score=r["score"],
        passed=r["passed"],
        min_score=r["min_score"],
        duration_s=r["duration_s"],
        generated_at=r["generated_at"],
        summary=r["summary"],
    )


@router.get("/status", response_model=ChaosStatusResponse)
async def get_chaos_status(user: TokenPayload = Depends(get_current_user)) -> ChaosStatusResponse:
    """Combined chaos + mutation testing status."""
    chaos_passed = chaos_failed = None
    if _last_chaos_results:
        chaos_passed = sum(1 for r in _last_chaos_results if r["passed"])
        chaos_failed = len(_last_chaos_results) - chaos_passed

    mut = _last_mutation_report
    return ChaosStatusResponse(
        chaos_last_run=_last_chaos_run_at,
        chaos_passed=chaos_passed,
        chaos_failed=chaos_failed,
        mutation_score=mut["score"] if mut else None,
        mutation_passed=mut["passed"] if mut else None,
        mutation_engine=mut["engine"] if mut else None,
        mutation_last_run=mut["generated_at"] if mut else None,
    )
