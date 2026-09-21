# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""Phase H6 — §14's durability half.

The scheduling half landed in Phase B: a job can carry any deadline at
`background` priority without starving interactive work, and the ageing queue
stops it being starved in return. The staged note said what was still missing,
and said it plainly: `JobRunner` holds jobs in an in-process dict, so an
hour-long research job dies with the process and its result is not recoverable.

The precedent for the fix is `ai/gateway/budget_store.py`, which is the same
lesson already learnt once: spend lived in a module global, every restart reset
the month to zero, and four workers meant four full allowances.

## The three rules this file exists to hold

**A job that was RUNNING when the process died did not survive.** Its thread is
gone. Reporting it as `running` after a restart is the worst of the options: a
job that says running for ever is one nobody can act on, and the screen would
spin against a worker that does not exist. It comes back `interrupted`, which
is a terminal state with a reason.

**Durability must not become a second source of truth.** For a job this process
is actually running, memory wins — the store is behind by design, and a reader
that preferred it would show a stale state to somebody watching their own job
progress.

**Recovery is operator-scoped, keyed rather than filtered.** `ai/jobs/runner.py`
is where a P0 leak was found: one operator's prompt and the model's answer could
reach another operator's screen. A recovery path that read every job and
filtered afterwards would rebuild it, so the operator is part of the key.
"""

from __future__ import annotations

import time

import pytest

from ai.jobs import runner as runner_module
from ai.jobs.runner import TERMINAL_STATES, JobRunner
from ai.jobs.store import InMemoryJobStore, JobRecord, recovered_state

pytestmark = pytest.mark.unit


def _finished(runner: JobRunner, prompt: str, operator: str) -> str:
    """Run one job to completion through a real runner and return its id.

    `submit` returns an id, and `wait_for` is a coroutine — polling the state
    here keeps this a plain synchronous test, which is what the runner's own
    suite does.
    """
    job_id = runner.submit(prompt=prompt, operator=operator, work=lambda _report: f"answer to {prompt}")
    deadline = time.time() + 5.0
    while time.time() < deadline:
        if runner.get(job_id, operator=operator).state in TERMINAL_STATES:
            return job_id
        time.sleep(0.01)
    raise AssertionError(f"job {job_id} did not finish within 5s")


class TestAFinishedJobOutlivesTheProcess:
    def test_its_result_is_readable_from_a_new_runner(self) -> None:
        store = InMemoryJobStore()
        first = JobRunner(store=store)
        job_id = _finished(first, "how deep is the gold drawdown", "alice")
        first.shutdown()

        # A different runner, as after a deploy. Nothing shared but the store.
        second = JobRunner(store=store)
        recovered = second.recover("alice")
        assert job_id in {r.id for r in recovered}
        answer = next(r for r in recovered if r.id == job_id)
        assert answer.state == "succeeded"
        assert "answer to" in str(answer.result)

    def test_another_operator_cannot_recover_it(self) -> None:
        # The P0 this module is keyed against.
        store = InMemoryJobStore()
        first = JobRunner(store=store)
        job_id = _finished(first, "alice's private research", "alice")
        first.shutdown()

        second = JobRunner(store=store)
        assert second.recover("bob") == []
        assert "alice's private research" not in repr(second.recover("bob"))
        assert job_id in {r.id for r in second.recover("alice")}


class TestARunningJobDidNotSurvive:
    def test_it_comes_back_interrupted_rather_than_running(self) -> None:
        # A job that says `running` for ever is one nobody can act on, and the
        # screen spins against a worker that does not exist.
        record = JobRecord(id="j1", operator="alice", prompt="p", state="running")
        assert recovered_state(record) == "interrupted"

    def test_interrupted_is_terminal_and_carries_a_reason(self) -> None:
        store = InMemoryJobStore()
        store.write(JobRecord(id="j1", operator="alice", prompt="p", state="running"))
        runner = JobRunner(store=store)
        recovered = runner.recover("alice")
        assert len(recovered) == 1
        assert recovered[0].state == "interrupted"
        assert recovered[0].error, "an interrupted job with no reason is indistinguishable from a bug"
        assert "restart" in recovered[0].error.lower() or "process" in recovered[0].error.lower()

    def test_a_queued_job_is_interrupted_too(self) -> None:
        # It never started, so nothing was lost — but nothing will start it
        # either. Leaving it `queued` promises a worker that is not coming.
        record = JobRecord(id="j1", operator="alice", prompt="p", state="queued")
        assert recovered_state(record) == "interrupted"

    def test_a_terminal_state_is_returned_unchanged(self) -> None:
        for state in ("succeeded", "failed", "cancelled", "timed_out"):
            record = JobRecord(id="j", operator="a", prompt="p", state=state)
            assert recovered_state(record) == state


class TestMemoryWinsForALiveJob:
    def test_recover_does_not_shadow_a_job_this_process_is_running(self) -> None:
        store = InMemoryJobStore()
        runner = JobRunner(store=store)
        job_id = _finished(runner, "live one", "alice")

        # The store deliberately made stale, as it is between two writes.
        store.write(JobRecord(id=job_id, operator="alice", prompt="live one", state="running"))

        recovered = runner.recover("alice")
        # Exactly one. Without the de-duplication the operator sees the job
        # TWICE — once succeeded from memory and once interrupted from the
        # store — and the first version of this test found the live one and
        # passed while that was happening.
        matching = [r for r in recovered if r.id == job_id]
        assert len(matching) == 1, f"the job appears {len(matching)} times"
        # Memory, not the stale store. A reader that preferred the store would
        # show `interrupted` for a job that succeeded in this very process.
        assert matching[0].state == "succeeded"
        runner.shutdown()


class TestAnUnavailableStoreIsReportedNotHidden:
    def test_a_runner_with_no_store_says_jobs_do_not_survive(self) -> None:
        runner = JobRunner()
        assert runner.durable is False
        assert runner.durability_reason, "a runner that cannot persist must say so"
        assert "restart" in runner.durability_reason.lower()
        runner.shutdown()

    def test_a_store_that_raises_never_takes_a_job_down_with_it(self) -> None:
        class _Broken(InMemoryJobStore):
            def write(self, record: JobRecord) -> None:
                raise RuntimeError("redis is unreachable")

        runner = JobRunner(store=_Broken())
        job_id = _finished(runner, "p", "alice")
        # The work is what matters. A durability layer that fails a job it was
        # only supposed to record is worse than having no durability at all.
        assert runner.get(job_id, operator="alice").state == "succeeded"
        runner.shutdown()

    def test_a_store_that_raises_on_read_recovers_nothing_rather_than_crashing(self) -> None:
        class _Broken(InMemoryJobStore):
            def read_for(self, operator: str) -> list[JobRecord]:
                raise RuntimeError("redis is unreachable")

        runner = JobRunner(store=_Broken())
        assert runner.recover("alice") == []
        runner.shutdown()


class TestTheStoreKeepsWhatTheScreenNeedsAndNoMore:
    def test_a_record_round_trips_through_its_own_serialisation(self) -> None:
        record = JobRecord(
            id="j1",
            operator="alice",
            prompt="p",
            state="succeeded",
            result={"text": "answer"},
            progress=["started", "done"],
        )
        assert JobRecord.from_dict(record.as_dict()) == record

    def test_a_malformed_record_is_skipped_rather_than_raised_over(self) -> None:
        # Written by an older version, or by something else entirely. One bad
        # record must not stop an operator recovering the other nine.
        store = InMemoryJobStore()
        store.write(JobRecord(id="good", operator="alice", prompt="p", state="succeeded"))
        store.put_raw("alice", {"not": "a job record"})
        runner = JobRunner(store=store)
        recovered = runner.recover("alice")
        assert [r.id for r in recovered] == ["good"]
        runner.shutdown()

    def test_the_module_still_exposes_its_concurrency_default(self) -> None:
        # `agents.*` capability rows point at this constant. A durability
        # change that moved it would break evidence resolution elsewhere.
        assert runner_module.DEFAULT_MAX_CONCURRENT >= 1
