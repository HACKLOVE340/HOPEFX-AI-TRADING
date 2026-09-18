# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""The AI screen has to do several things at once.

Owner requirement, 2026-09-06: the AI Core screen must generate multiple things
simultaneously, stay interactive while it does, and say what is happening. Today
every model call is one request, one answer, one blocked panel.

**A dedicated pool, not the shared one.** `app.py` sets a 64-worker default
executor, and `asyncio.to_thread` uses it — but so does yfinance and every other
blocking call in the process. Ten concurrent 60-second model calls would sit on
ten of those workers for a minute each and starve market data. AI jobs get their
own bounded pool so their concurrency cannot become somebody else's outage.

**One job failing must never touch another.** Panels are independent by
construction: a raise, a refusal, a budget denial or a cancellation is that
job's outcome and nothing else's.

These tests fail on the pre-fix tree — `ai.jobs` does not exist there.
"""

from __future__ import annotations

import asyncio
import time

import pytest

pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def _clean():
    from ai.jobs import runner

    runner.reset_for_testing()
    yield
    runner.reset_for_testing()


# ── concurrency ───────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_several_jobs_run_at_the_same_time():
    """The requirement, stated as a test.

    Four jobs that each sleep 0.3s must finish in well under 1.2s. Run
    sequentially they could not.
    """
    from ai.jobs.runner import JobRunner

    runner = JobRunner(max_concurrent=4)

    def work(_report):
        time.sleep(0.3)
        return "done"

    started = time.monotonic()
    ids = [runner.submit(prompt=f"job {i}", work=work, operator="owner") for i in range(4)]
    await runner.wait_for(ids, timeout=5.0)
    elapsed = time.monotonic() - started

    assert elapsed < 1.0, f"four 0.3s jobs took {elapsed:.2f}s — they ran sequentially"
    assert all(runner.get(i).state == "succeeded" for i in ids)


@pytest.mark.asyncio
async def test_the_concurrency_ceiling_is_enforced():
    """Unbounded concurrency is how a budget disappears in a minute."""
    from ai.jobs.runner import JobRunner

    runner = JobRunner(max_concurrent=2)
    live = {"now": 0, "peak": 0}

    def work(_report):
        live["now"] += 1
        live["peak"] = max(live["peak"], live["now"])
        time.sleep(0.15)
        live["now"] -= 1
        return "ok"

    ids = [runner.submit(prompt=f"j{i}", work=work, operator="owner") for i in range(6)]
    await runner.wait_for(ids, timeout=10.0)

    assert live["peak"] <= 2, f"{live['peak']} jobs ran at once against a ceiling of 2"


@pytest.mark.asyncio
async def test_the_ai_pool_is_not_the_shared_io_executor():
    """Otherwise AI concurrency starves market data."""
    from ai.jobs.runner import JobRunner

    runner = JobRunner(max_concurrent=2)
    assert runner.executor is not None
    assert runner.executor is not asyncio.get_running_loop()._default_executor


# ── isolation ─────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_one_job_failing_does_not_affect_the_others():
    from ai.jobs.runner import JobRunner

    runner = JobRunner(max_concurrent=4)

    def boom(_report):
        raise RuntimeError("vendor exploded")

    def fine(_report):
        return "ok"

    bad = runner.submit(prompt="bad", work=boom, operator="owner")
    good = [runner.submit(prompt=f"g{i}", work=fine, operator="owner") for i in range(3)]
    await runner.wait_for([bad, *good], timeout=5.0)

    assert runner.get(bad).state == "failed"
    assert runner.get(bad).error
    for i in good:
        assert runner.get(i).state == "succeeded", "a sibling job was affected by an unrelated failure"


@pytest.mark.asyncio
async def test_a_failed_job_reports_why_without_leaking_a_stack_trace():
    from ai.jobs.runner import JobRunner

    runner = JobRunner(max_concurrent=2)

    def boom(_report):
        raise RuntimeError("connection reset by peer")

    job_id = runner.submit(prompt="p", work=boom, operator="owner")
    await runner.wait_for([job_id], timeout=5.0)

    job = runner.get(job_id)
    assert "connection reset" in job.error
    assert "Traceback" not in job.error


# ── cancellation ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_a_queued_job_can_be_cancelled_before_it_starts():
    from ai.jobs.runner import JobRunner

    runner = JobRunner(max_concurrent=1)

    def slow(_report):
        time.sleep(0.4)
        return "ok"

    first = runner.submit(prompt="first", work=slow, operator="owner")
    queued = runner.submit(prompt="queued", work=slow, operator="owner")

    assert runner.cancel(queued) is True
    await runner.wait_for([first, queued], timeout=5.0)

    assert runner.get(queued).state == "cancelled"
    assert runner.get(first).state == "succeeded"


@pytest.mark.asyncio
async def test_cancelling_an_unknown_job_is_false_not_an_error():
    from ai.jobs.runner import JobRunner

    assert JobRunner(max_concurrent=1).cancel("no-such-job") is False


# ── progress ──────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_a_job_reports_progress_while_it_runs():
    """ "Communicate very well" — a panel must show more than a spinner."""
    from ai.jobs.runner import JobRunner

    runner = JobRunner(max_concurrent=2)

    def work(report):
        report("contacting the model")
        time.sleep(0.05)
        report("reading the answer")
        return "done"

    job_id = runner.submit(prompt="p", work=work, operator="owner")
    await runner.wait_for([job_id], timeout=5.0)

    notes = runner.get(job_id).progress
    assert "contacting the model" in notes
    assert "reading the answer" in notes


@pytest.mark.asyncio
async def test_state_moves_queued_then_running_then_succeeded():
    from ai.jobs.runner import JobRunner

    runner = JobRunner(max_concurrent=1)
    seen: list[str] = []

    def work(_report):
        time.sleep(0.1)
        return "ok"

    job_id = runner.submit(prompt="p", work=work, operator="owner", on_change=lambda j: seen.append(j.state))
    await runner.wait_for([job_id], timeout=5.0)

    assert "running" in seen
    assert seen[-1] == "succeeded"


@pytest.mark.asyncio
async def test_a_finished_job_reports_how_long_it_took():
    from ai.jobs.runner import JobRunner

    runner = JobRunner(max_concurrent=2)
    job_id = runner.submit(prompt="p", work=lambda _r: "ok", operator="owner")
    await runner.wait_for([job_id], timeout=5.0)

    assert runner.get(job_id).elapsed_s >= 0.0
    assert runner.get(job_id).finished_at


@pytest.mark.asyncio
async def test_the_runner_can_report_every_job_for_the_screen():
    from ai.jobs.runner import JobRunner

    runner = JobRunner(max_concurrent=3)
    ids = [runner.submit(prompt=f"p{i}", work=lambda _r: "ok", operator="owner") for i in range(3)]
    await runner.wait_for(ids, timeout=5.0)

    snapshot = runner.snapshot()
    assert len(snapshot["jobs"]) == 3
    assert snapshot["max_concurrent"] == 3


# ── bounds ────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_a_job_that_overruns_its_deadline_is_stopped():
    from ai.jobs.runner import JobRunner

    runner = JobRunner(max_concurrent=2)

    def forever(_report):
        time.sleep(5.0)
        return "never"

    job_id = runner.submit(prompt="p", work=forever, operator="owner", timeout_s=0.2)
    await runner.wait_for([job_id], timeout=5.0)

    assert runner.get(job_id).state == "timed_out"


@pytest.mark.asyncio
async def test_the_queue_refuses_work_past_its_ceiling():
    """Backpressure. An unbounded queue is a memory leak with a UI."""
    from ai.jobs.runner import JobRunner, QueueFull

    runner = JobRunner(max_concurrent=1, max_queued=2)

    def slow(_report):
        time.sleep(0.3)
        return "ok"

    runner.submit(prompt="a", work=slow, operator="owner")
    runner.submit(prompt="b", work=slow, operator="owner")
    runner.submit(prompt="c", work=slow, operator="owner")
    with pytest.raises(QueueFull):
        runner.submit(prompt="d", work=slow, operator="owner")


@pytest.mark.asyncio
async def test_an_empty_prompt_is_refused_at_submit():
    from ai.jobs.runner import JobRunner

    with pytest.raises(ValueError):
        JobRunner(max_concurrent=1).submit(prompt="   ", work=lambda _r: "x", operator="owner")


# ── the endpoints the screen drives ───────────────────────────────────────────


def _user():
    class _U:
        sub = "owner"
        role = "admin"

    return _U()


def test_the_three_endpoints_are_registered():
    import api.safe_agent_platform as sp

    paths = {r.path for r in sp.router.routes}
    assert "/api/safe-platform/generate" in paths
    assert "/api/safe-platform/generate/jobs" in paths
    assert "/api/safe-platform/generate/{job_id}/cancel" in paths


def test_every_generation_endpoint_is_classified():
    """An endpoint with no CAPABILITIES row is treated as refused."""
    from ai.policy.roles import CAPABILITIES, PROPOSE, VIEW

    assert CAPABILITIES["submit_generation"].tier == PROPOSE, "starting a paid job is not a read"
    assert CAPABILITIES["list_generations"].tier == VIEW
    assert CAPABILITIES["cancel_generation"].tier == PROPOSE


@pytest.mark.asyncio
async def test_submitting_returns_immediately_with_a_job_id():
    """Nothing blocks — that is what lets four panels work at once."""
    import api.safe_agent_platform as sp

    result = await sp.submit_generation(sp.GenerateRequest(prompt="what is the drawdown?"), user=_user())
    assert result["job_id"]
    assert result["state"] == "queued"

    from ai.jobs.runner import get_runner

    get_runner().cancel(result["job_id"])


@pytest.mark.asyncio
async def test_the_screen_can_read_every_job_at_once():
    import api.safe_agent_platform as sp

    for i in range(3):
        await sp.submit_generation(sp.GenerateRequest(prompt=f"question {i}"), user=_user())

    snapshot = await sp.list_generations(user=_user())
    assert len(snapshot["jobs"]) >= 3
    assert "max_concurrent" in snapshot


@pytest.mark.asyncio
async def test_cancelling_an_unknown_job_is_a_404_not_a_500():
    import api.safe_agent_platform as sp
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as exc:
        await sp.cancel_generation("no-such-job", user=_user())
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_backpressure_is_a_429_not_a_500():
    """A full queue is the caller going too fast, not the server breaking.

    Reporting it as 500 would have an operator chasing an outage that is not
    happening.
    """
    import api.safe_agent_platform as sp
    from fastapi import HTTPException

    from ai.jobs.runner import JobRunner, set_runner

    def slow(_report):
        time.sleep(0.5)
        return "ok"

    runner = JobRunner(max_concurrent=1, max_queued=1)
    set_runner(runner)
    for _ in range(3):
        try:
            runner.submit(prompt="filler", work=slow, operator="owner")
        except Exception:
            break

    with pytest.raises(HTTPException) as exc:
        await sp.submit_generation(sp.GenerateRequest(prompt="one too many"), user=_user())
    assert exc.value.status_code == 429
