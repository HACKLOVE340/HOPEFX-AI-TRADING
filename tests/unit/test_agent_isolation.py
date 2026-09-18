# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""§24 — isolated agent workers, in a real child process.

I wrote the note that said this "needs a process or container boundary this
deployment does not have". That was wrong. `ProcessPoolExecutor`,
`multiprocessing` with `spawn`, and `resource.setrlimit` are all standard
library, and the boundary is code rather than infrastructure.

## Why a task CONTRACT and not just a process pool

`JobRunner.submit` takes a closure. A closure captures whatever the caller had
in scope and is not picklable, so no amount of process pool makes an arbitrary
job isolated — the honest unit is a task that NAMES an importable function and
picklable arguments. That is what §24's "task contracts" means here, and it is
why the probes for these tests live in an importable module: a test that could
pass with a lambda would be testing something this design refuses.

## Isolation is opt-in, and that is deliberate on a money-moving platform

Every existing job keeps running exactly as it does today, on the thread pool.
A change that silently moved all of them across a process boundary would change
the failure modes of live trading work to fix a row in a registry.

## What the boundary is actually claimed to buy

Three things, each asserted against a real child process rather than described:

* a task that leaves without unwinding — `os._exit`, which is what a
  segfaulting native extension looks like — does not take the parent with it;
* a task that allocates without bound is stopped by a limit rather than by the
  machine;
* a task that never returns is terminated, and the process is really gone
  afterwards rather than left spinning a core.
"""

from __future__ import annotations

import os

import pytest

from ai.jobs.isolation import (
    ContractRefused,
    TaskContract,
    isolation_available,
    resolve_entrypoint,
    run_isolated,
)

pytestmark = [pytest.mark.unit, pytest.mark.slow]

PROBES = "tests.support.isolated_tasks"


def _contract(function: str, **kwargs: object) -> TaskContract:
    return TaskContract(
        entrypoint=f"{PROBES}:{function}",
        operator="alice",
        args=dict(kwargs.pop("args", {})),  # type: ignore[arg-type]
        **kwargs,  # type: ignore[arg-type]
    )


class TestTheContractRefusesWhatCannotBeIsolated:
    def test_an_entrypoint_must_name_a_module_and_a_function(self) -> None:
        with pytest.raises(ContractRefused, match="module:function"):
            TaskContract(entrypoint=PROBES, operator="alice")

    def test_an_unimportable_entrypoint_is_refused_at_construction(self) -> None:
        # Not at run time, in a child, with the failure arriving as a mysterious
        # dead process. A contract that cannot be honoured is refused where the
        # caller can still do something about it.
        with pytest.raises(ContractRefused):
            TaskContract(entrypoint="no.such.module:fn", operator="alice")

    def test_a_name_that_is_not_callable_is_refused(self) -> None:
        with pytest.raises(ContractRefused, match="callable"):
            TaskContract(entrypoint=f"{PROBES}:NOT_A_FUNCTION", operator="alice")

    def test_unpicklable_arguments_are_refused_here_rather_than_in_the_child(self) -> None:
        with pytest.raises(ContractRefused, match="pickl"):
            TaskContract(entrypoint=f"{PROBES}:succeed", operator="alice", args={"fn": lambda: 1})

    def test_a_contract_needs_an_operator(self) -> None:
        # The scoping that a P0 was fixed for. An isolated task with no
        # operator is one whose result belongs to nobody.
        with pytest.raises(ContractRefused, match="operator"):
            TaskContract(entrypoint=f"{PROBES}:succeed", operator="  ")

    def test_a_timeout_must_be_positive(self) -> None:
        with pytest.raises(ContractRefused, match="timeout"):
            TaskContract(entrypoint=f"{PROBES}:succeed", operator="alice", timeout_s=0)

    def test_resolve_returns_the_real_function(self) -> None:
        from tests.support import isolated_tasks

        assert resolve_entrypoint(f"{PROBES}:succeed") is isolated_tasks.succeed


class TestItReallyRunsSomewhereElse:
    def test_the_task_runs_in_a_different_process(self) -> None:
        # The claim, measured. Everything else in this file is only interesting
        # if this is true.
        outcome = run_isolated(_contract("report_pid"))
        assert outcome.state == "succeeded", outcome.error
        assert outcome.result != os.getpid()
        assert outcome.pid and outcome.pid != os.getpid()

    def test_a_result_comes_back_across_the_boundary(self) -> None:
        outcome = run_isolated(_contract("succeed", args={"value": "the answer"}))
        assert outcome.state == "succeeded"
        assert outcome.result == "the answer"

    def test_the_operator_travels_with_the_contract(self) -> None:
        contract = TaskContract(
            entrypoint=f"{PROBES}:echo_operator",
            operator="alice",
            args={"operator": "alice"},
        )
        outcome = run_isolated(contract)
        assert outcome.result == "alice"
        assert outcome.operator == "alice"

    def test_progress_from_inside_the_child_reaches_the_parent(self) -> None:
        # A boundary that lost the progress channel would be a regression
        # dressed as a feature: §12's streaming partials and §14's long jobs
        # both depend on a worker being able to say what it is doing.
        seen: list[str] = []
        outcome = run_isolated(_contract("succeed"), report=seen.append)
        assert outcome.state == "succeeded"
        assert "starting" in seen and "half way" in seen
        assert outcome.progress == seen


class TestTheBoundaryBuysWhatItClaims:
    def test_a_task_that_dies_without_unwinding_does_not_take_the_parent(self) -> None:
        # `os._exit` is what a segfaulting native extension looks like from
        # outside. On the thread pool this kills the API process.
        outcome = run_isolated(_contract("die_hard"))
        assert outcome.state == "failed"
        assert outcome.error
        assert "exit" in outcome.error.lower() or "9" in outcome.error
        # The parent is still here to make the assertion, which is the point.
        assert os.getpid() > 0

    def test_an_ordinary_exception_comes_back_as_a_message_not_a_traceback(self) -> None:
        outcome = run_isolated(_contract("raise_error"))
        assert outcome.state == "failed"
        assert "ValueError" in outcome.error
        # A stack trace is useless to an operator and leaks internals into a
        # browser. The runner already holds this rule for threaded jobs.
        assert "Traceback" not in outcome.error

    def test_a_task_that_never_returns_is_terminated_and_really_gone(self) -> None:
        outcome = run_isolated(_contract("spin_forever", timeout_s=1.0))
        assert outcome.state == "timed_out"
        assert outcome.pid
        # Not merely abandoned. An abandoned child keeps a core busy for the
        # life of the deployment, which is the failure this row exists to stop.
        assert not _process_alive(outcome.pid), f"pid {outcome.pid} survived its timeout"

    def test_a_task_that_allocates_without_bound_is_stopped_by_the_limit(self) -> None:
        outcome = run_isolated(_contract("eat_memory", memory_mb=256, args={"megabytes": 4096}))
        assert outcome.state == "failed", outcome.result
        assert outcome.error
        # And the machine is still usable, which a 4GB allocation on an
        # unbounded worker would not guarantee.


class TestItSaysWhenItCannot:
    def test_availability_is_reported_rather_than_assumed(self) -> None:
        available, reason = isolation_available()
        assert isinstance(available, bool)
        if not available:
            assert reason, "unavailable isolation must say why"
        else:
            assert reason == ""

    def test_a_memory_cap_that_the_platform_cannot_apply_is_named(self) -> None:
        # Reported, never silently skipped: a caller that asked for a 256MB cap
        # and got none has a worker with no ceiling and no way to know.
        outcome = run_isolated(_contract("succeed", memory_mb=256))
        assert outcome.state == "succeeded"
        assert isinstance(outcome.memory_capped, bool)
        if not outcome.memory_capped:
            assert outcome.notes, "an unapplied memory cap must be reported"


class TestTheDefaultPathIsUntouched:
    def test_the_runner_still_runs_ordinary_jobs_on_threads(self) -> None:
        # The safety property for a money-moving platform: nothing about live
        # trading work changes because a registry row needed closing.
        import time as _time

        from ai.jobs.runner import TERMINAL_STATES, JobRunner

        runner = JobRunner()
        job_id = runner.submit(prompt="p", operator="alice", work=lambda _r: os.getpid())
        deadline = _time.time() + 5.0
        while _time.time() < deadline:
            if runner.get(job_id, operator="alice").state in TERMINAL_STATES:
                break
            _time.sleep(0.01)
        job = runner.get(job_id, operator="alice")
        assert job.state == "succeeded"
        # Same process. A closure cannot cross a boundary, and pretending it
        # could is what this design refuses.
        assert job.result == os.getpid()
        runner.shutdown()


def _process_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True
