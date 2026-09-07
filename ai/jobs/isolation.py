# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""§24 — an agent task that runs behind a real process boundary.

The registry note for this row said it needed "a process or container boundary
this deployment does not have". That was wrong, and it is worth naming the
mistake precisely: `multiprocessing` with `spawn` and `resource.setrlimit` are
standard library. The boundary was code nobody had written, not infrastructure
nobody had bought.

## Why a task CONTRACT, and not simply a process pool

`JobRunner.submit` takes a closure, and a closure captures whatever the caller
had in scope. It is not picklable, so no amount of `ProcessPoolExecutor` makes
an arbitrary job isolated. The honest unit is a task that NAMES an importable
function and picklable arguments — which is exactly what §24's phrase "task
contracts" has to mean if it means anything.

Every refusal happens at construction, in the caller's process, where somebody
can still do something about it. A contract that cannot be honoured must not
become a mysterious dead child three layers away.

## One process per task, not a pool

A pool cannot kill a running task: `Future.cancel` refuses once work has
started, and the only lever is shutting the whole pool down and taking every
other task with it. Isolated tasks are the rare, heavy ones — an hour of
research, not a chat turn — so one process each is affordable, and it buys the
`terminate()` that makes the timeout real rather than advisory.

## spawn, never fork

This process has threads: the job pool, the event loop, the metrics reporter.
`fork` copies the address space and exactly one thread, so a lock held by any
other thread at the moment of the fork is held for ever in the child — a
deadlock that reproduces once a week and never in a test. `spawn` starts clean.

## What the boundary actually buys

Stated as three things, each asserted in `tests/unit/test_agent_isolation.py`
against a real child rather than described here:

* a task that leaves without unwinding — `os._exit`, which is what a
  segfaulting native extension looks like — does not take the API process with
  it;
* a task that allocates without bound meets `RLIMIT_AS` rather than the
  machine's limits;
* a task that never returns is terminated and is really gone, rather than left
  spinning a core for the life of the deployment.

## Isolation is opt-in

Everything that runs today keeps running on the thread pool. Silently moving
live trading work across a process boundary to close a registry row would be
changing the failure modes of the thing the row was describing.
"""

from __future__ import annotations

import importlib
import logging
import multiprocessing
import pickle
import queue as queue_module
import time
from dataclasses import dataclass, field
from typing import Any, Final

logger = logging.getLogger(__name__)

#: Default ceiling for an isolated task. Generous — the point is to stop a
#: runaway, not to tune a workload.
DEFAULT_MEMORY_MB: Final = 2048

DEFAULT_TIMEOUT_S: Final = 300.0

#: How long a terminated child is given to actually die before it is killed
#: outright. `terminate` is SIGTERM, which a task inside a C call can ignore.
_REAP_GRACE_S: Final = 2.0


class ContractRefused(ValueError):
    """The task cannot be isolated as described, and was not started."""


@dataclass(frozen=True)
class TaskContract:
    """A task that a child process can be told to run, and nothing more.

    `entrypoint` is `module:function`. A string rather than a callable on
    purpose: a callable would let a closure through, and a closure is precisely
    what cannot cross this boundary.
    """

    entrypoint: str
    operator: str
    args: dict[str, Any] = field(default_factory=dict)
    timeout_s: float = DEFAULT_TIMEOUT_S
    memory_mb: int | None = DEFAULT_MEMORY_MB

    def __post_init__(self) -> None:
        if not self.operator or not self.operator.strip():
            raise ContractRefused(
                "an isolated task needs an operator; a result that belongs to nobody is one nobody may read",
            )
        if not isinstance(self.entrypoint, str) or self.entrypoint.count(":") != 1:
            raise ContractRefused(
                f"entrypoint must be module:function, got {self.entrypoint!r}",
            )
        # Resolved HERE, in the caller's process. A bad reference discovered in
        # the child arrives as a dead process with no explanation.
        resolve_entrypoint(self.entrypoint)
        try:
            pickle.dumps(self.args)
        except Exception as exc:
            raise ContractRefused(
                f"the arguments are not picklable, so they cannot cross the boundary: {exc}",
            ) from exc
        if not isinstance(self.timeout_s, (int, float)) or self.timeout_s <= 0:
            raise ContractRefused(f"timeout must be positive, got {self.timeout_s!r}")
        if self.memory_mb is not None and (not isinstance(self.memory_mb, int) or self.memory_mb <= 0):
            raise ContractRefused(f"memory_mb must be a positive number of megabytes, got {self.memory_mb!r}")


def resolve_entrypoint(reference: str) -> Any:
    """Import `module:function` and return it, or refuse.

    Refuses rather than returning None: a caller handed None would discover it
    at call time, in a child, as a `TypeError` nobody can trace back here.
    """
    if not isinstance(reference, str) or reference.count(":") != 1:
        raise ContractRefused(f"entrypoint must be module:function, got {reference!r}")
    module_name, _, attribute = reference.partition(":")
    try:
        module = importlib.import_module(module_name)
    except Exception as exc:
        raise ContractRefused(f"cannot import {module_name!r}: {type(exc).__name__}: {exc}") from exc
    target = getattr(module, attribute, None)
    if target is None:
        raise ContractRefused(f"{module_name!r} has no attribute {attribute!r}")
    if not callable(target):
        raise ContractRefused(f"{reference} is not callable")
    return target


@dataclass(frozen=True)
class IsolatedOutcome:
    """What happened, in the words the runner already uses for a job."""

    state: str
    operator: str
    result: Any = None
    error: str = ""
    progress: list[str] = field(default_factory=list)
    #: The child's pid. Kept so a caller — and a test — can check it is gone.
    pid: int = 0
    elapsed_s: float = 0.0
    #: Whether the memory ceiling was actually applied. Never assumed: a caller
    #: who asked for a cap and did not get one has an unbounded worker.
    memory_capped: bool = False
    #: Anything the caller should know that is not the outcome itself.
    notes: str = ""


def isolation_available() -> tuple[bool, str]:
    """Whether a real process boundary can be created here, and why not.

    Reported rather than assumed. A deployment where `spawn` is unavailable
    would otherwise get threads while believing it had processes, which is the
    exact shape of claim this whole registry exists to prevent.
    """
    try:
        multiprocessing.get_context("spawn")
    except Exception as exc:  # pragma: no cover - every supported platform has spawn
        return False, f"the spawn start method is unavailable: {type(exc).__name__}: {exc}"
    return True, ""


def _child(reference: str, args: dict[str, Any], memory_mb: int | None, channel: Any) -> None:
    """The child's whole life. Runs in a fresh interpreter under `spawn`.

    Everything it says goes down `channel` as a tagged tuple. It never raises
    out of here: an exception escaping would produce a non-zero exit with no
    message, and "the child died" is a much worse report than "the task raised
    ValueError".
    """
    capped = False
    try:
        if memory_mb is not None:
            try:
                import resource

                limit = memory_mb * 1024 * 1024
                resource.setrlimit(resource.RLIMIT_AS, (limit, limit))
                capped = True
            except Exception as exc:
                # Named, not skipped. See `IsolatedOutcome.memory_capped`.
                channel.put(("note", f"the memory cap could not be applied: {type(exc).__name__}: {exc}"))
        channel.put(("capped", capped))

        def report(note: str, **_: Any) -> None:
            channel.put(("progress", str(note)))

        target = resolve_entrypoint(reference)
        value = target(report=report, **args)
        try:
            channel.put(("result", value))
        except Exception as exc:
            # The task succeeded and its answer will not travel. That is a
            # different failure from the task failing, and it is reported as
            # itself rather than as a task error.
            channel.put(("error", f"the task succeeded and its result could not be returned: {exc}"))
    except MemoryError:
        channel.put(("error", "MemoryError: the task exceeded the memory this deployment allows it"))
    except BaseException as exc:
        # The message, never the traceback: the runner already holds this rule
        # because a job's error is rendered in a browser panel.
        channel.put(("error", f"{type(exc).__name__}: {exc}"))


def run_isolated(contract: TaskContract, *, report: Any = None) -> IsolatedOutcome:
    """Run `contract` in its own process and come back with what happened.

    Blocking. It is called from the job runner's worker thread, which is
    already a thread standing in for a request — the same place `ai/gateway`
    does its synchronous work.
    """
    available, reason = isolation_available()
    if not available:
        return IsolatedOutcome(
            state="failed",
            operator=contract.operator,
            error=f"this task asked to be isolated and could not be: {reason}",
        )

    context = multiprocessing.get_context("spawn")
    channel = context.Queue()
    process = context.Process(
        target=_child,
        args=(contract.entrypoint, dict(contract.args), contract.memory_mb, channel),
        daemon=True,
    )

    started = time.monotonic()
    process.start()
    pid = process.pid or 0

    progress: list[str] = []
    notes: list[str] = []
    result: Any = None
    error = ""
    capped = False
    got_result = False

    deadline = started + contract.timeout_s
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        try:
            # Short waits rather than one long one, so the deadline is honoured
            # even while the child is chatty.
            kind, payload = channel.get(timeout=min(0.1, remaining))
        except queue_module.Empty:
            if not process.is_alive():
                break
            continue
        except (EOFError, OSError):  # pragma: no cover - the queue died with the child
            break

        if kind == "progress":
            progress.append(payload)
            if report is not None:
                try:
                    report(payload)
                except Exception:
                    # A broken listener must never fail the task it is watching,
                    # which is the rule `JobRunner._notify` already holds.
                    logger.exception("ai.jobs.isolation: progress listener raised")
        elif kind == "result":
            result = payload
            got_result = True
            break
        elif kind == "error":
            error = str(payload)
            break
        elif kind == "capped":
            capped = bool(payload)
        elif kind == "note":
            notes.append(str(payload))

    timed_out = not got_result and not error and time.monotonic() >= deadline
    _reap(process)
    elapsed = time.monotonic() - started

    if timed_out:
        return IsolatedOutcome(
            state="timed_out",
            operator=contract.operator,
            progress=progress,
            pid=pid,
            elapsed_s=elapsed,
            memory_capped=capped,
            notes="; ".join(notes),
            error=f"the task did not finish within {contract.timeout_s}s and its process was terminated",
        )

    if got_result:
        return IsolatedOutcome(
            state="succeeded",
            operator=contract.operator,
            result=result,
            progress=progress,
            pid=pid,
            elapsed_s=elapsed,
            memory_capped=capped,
            notes="; ".join(notes),
        )

    if not error:
        # The child said nothing and stopped. `os._exit`, a signal, or the
        # kernel's OOM killer — from here they look the same and the exit code
        # is the only thing there is to report.
        error = (
            f"the task's process ended without returning anything (exit code {process.exitcode}); "
            "it did not unwind, so nothing was recorded about why"
        )
    return IsolatedOutcome(
        state="failed",
        operator=contract.operator,
        error=error,
        progress=progress,
        pid=pid,
        elapsed_s=elapsed,
        memory_capped=capped,
        notes="; ".join(notes),
    )


def _reap(process: Any) -> None:
    """Make sure the child is really gone.

    `terminate` is SIGTERM, which a task inside a long C call can ignore
    entirely. A worker that survived its own timeout keeps a core busy for the
    life of the deployment, so the grace period is followed by `kill`.
    """
    if not process.is_alive():
        process.join(timeout=_REAP_GRACE_S)
        return
    process.terminate()
    process.join(timeout=_REAP_GRACE_S)
    if process.is_alive():  # pragma: no cover - needs a task that ignores SIGTERM
        try:
            process.kill()
        except Exception:
            logger.exception("ai.jobs.isolation: could not kill pid %s", process.pid)
        process.join(timeout=_REAP_GRACE_S)


__all__ = [
    "DEFAULT_MEMORY_MB",
    "DEFAULT_TIMEOUT_S",
    "ContractRefused",
    "IsolatedOutcome",
    "TaskContract",
    "isolation_available",
    "resolve_entrypoint",
    "run_isolated",
]
