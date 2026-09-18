# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""One operator's generations are not another operator's business.

`JobRunner` records the operator on every job and then ignored it everywhere it
mattered. Measured, before this file existed:

    jobs returned by ONE snapshot call: 2
      - alice's confidential position question
      - bob's question
    bob cancels alice's running job by id -> True

`snapshot()` returned every job in the process, and `cancel(job_id)` cancelled
anyone's. Both endpoints take `user` and neither used it for scoping. On a
deployment with two admins, one admin's AI Core screen showed the other's
prompts AND the model's answers, and could stop their work.

This is the same shape as the WebSocket defect the private-channel work fixed:
the right user is authenticated, and the wrong scope is served. Authentication
is not authorisation, and a screen that renders whatever the API returns will
render somebody else's question without anyone noticing.

**Retention is here too**, because it is the same object and the same risk from
a different direction: `_jobs` never shrank, so every prompt and every answer
stayed in memory for the life of the process. A leak needs something to leak.

These tests fail on the pre-fix tree.
"""

from __future__ import annotations

import time

import pytest

pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def _clean():
    from ai.jobs import runner

    runner.reset_for_testing()
    yield
    runner.reset_for_testing()


def _settle(runner, job_id, timeout=5.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if runner.get(job_id).state in {"succeeded", "failed", "cancelled", "timed_out"}:
            return
        time.sleep(0.01)
    raise AssertionError("job never settled")


# ── reading ───────────────────────────────────────────────────────────────────


def test_a_snapshot_shows_only_the_asking_operators_jobs():
    from ai.jobs.runner import JobRunner

    runner = JobRunner(max_concurrent=2)
    alice = runner.submit(prompt="alice's confidential question", work=lambda r: "A", operator="alice")
    runner.submit(prompt="bob's question", work=lambda r: "B", operator="bob")
    _settle(runner, alice)

    snap = runner.snapshot(operator="alice")
    prompts = [j["prompt"] for j in snap["jobs"]]
    assert prompts == ["alice's confidential question"]
    assert "bob's question" not in repr(snap)


def test_the_counts_describe_what_the_operator_can_see():
    """A queue depth that counts other people's work makes 'why is mine
    waiting' unanswerable, and leaks how busy someone else is."""
    from ai.jobs.runner import JobRunner

    runner = JobRunner(max_concurrent=1)
    runner.submit(prompt="alice one", work=lambda r: time.sleep(0.4), operator="alice")
    runner.submit(prompt="bob one", work=lambda r: time.sleep(0.4), operator="bob")
    runner.submit(prompt="bob two", work=lambda r: time.sleep(0.4), operator="bob")
    time.sleep(0.1)

    snap = runner.snapshot(operator="bob")
    assert len(snap["jobs"]) == 2
    assert snap["running"] + snap["queued"] <= 2


def test_an_unscoped_snapshot_is_still_possible_for_the_platform_view():
    """A superadmin overview and the health surface legitimately need the whole
    picture. The default must be scoped; the whole picture must be asked for."""
    from ai.jobs.runner import JobRunner

    runner = JobRunner(max_concurrent=2)
    a = runner.submit(prompt="alice", work=lambda r: "A", operator="alice")
    b = runner.submit(prompt="bob", work=lambda r: "B", operator="bob")
    _settle(runner, a)
    _settle(runner, b)

    assert len(runner.snapshot().get("jobs", [])) == 2


# ── writing ───────────────────────────────────────────────────────────────────


def test_one_operator_cannot_cancel_another_operators_job():
    from ai.jobs.runner import JobRunner

    runner = JobRunner(max_concurrent=2)
    alice = runner.submit(prompt="alice's long job", work=lambda r: time.sleep(3), operator="alice")
    time.sleep(0.15)
    assert runner.get(alice).state == "running"

    assert runner.cancel(alice, operator="bob") is False
    assert runner.get(alice).state == "running", "bob stopped alice's work"


def test_an_operator_can_still_cancel_their_own_job():
    from ai.jobs.runner import JobRunner

    runner = JobRunner(max_concurrent=2)
    alice = runner.submit(prompt="alice's long job", work=lambda r: time.sleep(3), operator="alice")
    time.sleep(0.15)
    assert runner.cancel(alice, operator="alice") is True


def test_a_cancel_refusal_is_indistinguishable_from_a_job_that_does_not_exist():
    """Otherwise the API is an oracle for guessing other operators' job ids."""
    from ai.jobs.runner import JobRunner

    runner = JobRunner(max_concurrent=2)
    alice = runner.submit(prompt="alice's long job", work=lambda r: time.sleep(3), operator="alice")
    time.sleep(0.15)

    assert runner.cancel(alice, operator="bob") == runner.cancel("no-such-job-id", operator="bob")


def test_reading_one_job_is_scoped_too():
    from ai.jobs.runner import JobRunner

    runner = JobRunner(max_concurrent=2)
    alice = runner.submit(prompt="alice's question", work=lambda r: "A", operator="alice")
    _settle(runner, alice)

    with pytest.raises(KeyError):
        runner.get(alice, operator="bob")
    assert runner.get(alice, operator="alice").prompt == "alice's question"


# ── the endpoints, which is where it actually mattered ────────────────────────


def test_the_list_endpoint_scopes_to_the_caller():
    import inspect

    import api.safe_agent_platform as sp

    src = inspect.getsource(sp.list_generations)
    assert "operator=" in src, "the endpoint takes `user` and still returns every operator's jobs"


def test_the_cancel_endpoint_scopes_to_the_caller():
    import inspect

    import api.safe_agent_platform as sp

    src = inspect.getsource(sp.cancel_generation)
    assert "operator=" in src, "the endpoint takes `user` and still cancels anyone's job"


# ── retention: a leak needs something to leak ─────────────────────────────────


def test_finished_jobs_do_not_accumulate_forever():
    from ai.jobs.runner import MAX_RETAINED_JOBS, JobRunner

    runner = JobRunner(max_concurrent=4, max_queued=512)
    for i in range(MAX_RETAINED_JOBS + 40):
        job_id = runner.submit(prompt=f"question {i}", work=lambda r: "ok", operator="owner")
        _settle(runner, job_id)

    assert len(runner.snapshot()["jobs"]) <= MAX_RETAINED_JOBS


def test_eviction_takes_the_oldest_finished_job_first():
    from ai.jobs.runner import MAX_RETAINED_JOBS, JobRunner

    runner = JobRunner(max_concurrent=2, max_queued=512)
    first = runner.submit(prompt="the very first question", work=lambda r: "ok", operator="owner")
    _settle(runner, first)
    for i in range(MAX_RETAINED_JOBS + 5):
        _settle(runner, runner.submit(prompt=f"q{i}", work=lambda r: "ok", operator="owner"))

    prompts = [j["prompt"] for j in runner.snapshot()["jobs"]]
    assert "the very first question" not in prompts
    assert f"q{MAX_RETAINED_JOBS + 4}" in prompts, "the newest job was evicted instead of the oldest"


def test_a_running_job_is_never_evicted():
    """Evicting live work would lose an answer somebody is waiting for and paying
    for. Only terminal jobs are candidates."""
    from ai.jobs.runner import MAX_RETAINED_JOBS, JobRunner

    runner = JobRunner(max_concurrent=2, max_queued=512)
    live = runner.submit(prompt="still going", work=lambda r: time.sleep(2.5), operator="owner")
    time.sleep(0.1)
    for i in range(MAX_RETAINED_JOBS + 5):
        _settle(runner, runner.submit(prompt=f"q{i}", work=lambda r: "ok", operator="owner"))

    assert runner.get(live).state == "running", "a running job was evicted"
