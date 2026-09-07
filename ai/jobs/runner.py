# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""Many AI generations at once, each one independent and bounded.

Owner requirement, 2026-09-06: the AI Core screen must generate several things
simultaneously, stay interactive while it does, and say what is happening. Every
model call was one request, one answer, one blocked panel.

## Why a dedicated pool rather than `asyncio.to_thread`

`app.py` installs a 64-worker default executor, and `to_thread` uses it — but so
does yfinance and every other blocking call in the process. Ten concurrent model
calls at the 60-second default timeout would occupy ten of those workers for a
minute each, and the first symptom would be market data going quiet. AI
concurrency must not become somebody else's outage, so it gets its own bounded
pool.

## Why threads rather than a native async gateway

The gateway is synchronous end to end, and `async-python-patterns` is explicit
that a call path should be fully one or the other. Converting it — and every
vendor adapter — to `httpx.AsyncClient` is a large change with real regression
risk on the path that routes, budgets and audits every model call, in exchange
for thread-pool efficiency that a dedicated bounded pool already provides at
this scale. Threads here, natively async when streaming needs it, and nothing
half-converted in between.

## What each job guarantees

* **Isolation.** A raise, a refusal, a budget denial or a timeout is that job's
  outcome and nothing else's. Panels are independent by construction.
* **A deadline.** A job that overruns is marked `timed_out` rather than held
  open. The worker thread cannot be killed — Python has no safe way — so the
  ceiling is honest about that: the slot is released and the result discarded.
* **Backpressure.** The queue has a ceiling. An unbounded one is a memory leak
  with a user interface attached.
* **Progress.** A job reports what it is doing while it does it, because a
  panel showing a spinner communicates nothing.
"""

from __future__ import annotations

import asyncio
import logging
import threading
import time
import uuid
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

logger = logging.getLogger(__name__)

#: Jobs in flight at once, by default.
#:
#: Four is a screen with four panels working, not a stress test. Each in-flight
#: job holds a worker for up to its timeout and spends real money, so the
#: ceiling is deliberately close to what a person can actually read at once.
DEFAULT_MAX_CONCURRENT = 4

#: Jobs waiting for a slot. Past this, submit refuses rather than queues.
DEFAULT_MAX_QUEUED = 16

DEFAULT_JOB_TIMEOUT_S = 120.0

#: Finished jobs kept before the oldest are dropped.
#:
#: `_jobs` never shrank, which is two problems wearing one coat: memory that
#: grows for the life of the process, and every operator prompt plus every model
#: answer retained indefinitely in it. A leak needs something to leak.
#:
#: 64 is comfortably more than a screen shows and more than a session's history
#: is worth scrolling. Only TERMINAL jobs are candidates — evicting live work
#: would lose an answer somebody is waiting for and has paid for.
MAX_RETAINED_JOBS = 64

#: How often a streaming job may push a frame while text is arriving.
#:
#: One notification per delta is one WebSocket frame per delta. A fast model
#: emits hundreds a second, per panel, across four panels — a push channel that
#: becomes its own outage. 120ms is about eight updates a second, which reads as
#: continuous to a person and is two orders of magnitude below the raw rate.
#:
#: This throttles OUTPUT only. State transitions and status notes are rare and
#: always pushed, and the terminal state always flushes, so the last words of an
#: answer are never the ones dropped.
OUTPUT_FRAME_INTERVAL_S = 0.12

#: queued -> running -> one of the three terminal states.
TERMINAL_STATES = frozenset({"succeeded", "failed", "cancelled", "timed_out"})


def _remember_task(job: Job) -> None:
    """Tell §5's conversation context that this job exists.

    Wrapped, because "is the backtest done?" being answerable is worth less than
    the backtest running. A context store that cannot be written to degrades the
    conversation; it must not be able to refuse work.
    """
    try:
        from ai.core import context

        context.note_task(job.operator, task_id=job.id, summary=job.prompt.strip()[:120])
    except Exception:
        logger.exception("ai.jobs: could not record %s in the conversation context", job.id)


def _forget_task(job: Job) -> None:
    """Move it out of the active list, keeping it referable.

    "How did it go?" arrives after the work finishes, so the outcome goes with
    it rather than the task simply disappearing.
    """
    try:
        from ai.core import context

        outcome = job.error.strip() if job.error else job.state
        context.finish_task(job.operator, task_id=job.id, outcome=outcome[:160])
    except Exception:
        logger.exception("ai.jobs: could not close %s in the conversation context", job.id)


class QueueFull(RuntimeError):
    """The runner is at its queue ceiling. Backpressure, not an error condition."""


@dataclass
class Job:
    id: str
    prompt: str
    operator: str
    state: str = "queued"
    result: Any = None
    error: str = ""
    progress: list[str] = field(default_factory=list)
    submitted_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    started_at: str = ""
    finished_at: str = ""
    elapsed_s: float = 0.0
    #: Monotonic instant this job stops being worth waiting for. Set when it
    #: starts running; `_reap` promotes it to `timed_out` once passed.
    deadline: float = 0.0
    timeout_s: float = DEFAULT_JOB_TIMEOUT_S
    #: Bumped on every observable change. The screen receives this job twice —
    #: pushed over `ai_jobs` and polled over REST — and needs to tell a late
    #: frame from a new one. Without it a job that already succeeded flickers
    #: back to `running` when a delayed push lands after a poll.
    rev: int = 0
    #: The answer as it arrives. Separate from `progress`, which is a list of
    #: status notes — appending every delta there would turn a status log into
    #: a transcript rendered as bullet points.
    partial: str = ""

    def as_dict(self) -> dict[str, Any]:
        """What the screen renders. The prompt is included; the result is not
        truncated here — the caller decides what a panel shows."""
        return {
            "id": self.id,
            "prompt": self.prompt,
            "state": self.state,
            "result": self.result,
            "error": self.error,
            "progress": list(self.progress),
            "submitted_at": self.submitted_at,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "elapsed_s": round(self.elapsed_s, 3),
            "rev": self.rev,
            "partial": self.partial,
        }


class JobRunner:
    """A bounded pool of concurrent AI jobs."""

    def __init__(
        self,
        *,
        max_concurrent: int = DEFAULT_MAX_CONCURRENT,
        max_queued: int = DEFAULT_MAX_QUEUED,
    ) -> None:
        self.max_concurrent = max(1, int(max_concurrent))
        self.max_queued = max(1, int(max_queued))
        self._jobs: dict[str, Job] = {}
        self._futures: dict[str, Future] = {}
        self._cancelled: set[str] = set()
        # Guards `_jobs`, `_futures` and `_cancelled`. Worker threads mutate job
        # state while the event loop reads it for the screen, so this is a real
        # race rather than a theoretical one.
        self._lock = threading.RLock()
        self.executor = ThreadPoolExecutor(
            max_workers=self.max_concurrent,
            thread_name_prefix="hopefx-ai-job",
        )
        # §14's priority queue, consulted ONLY when the pool is saturated.
        #
        # `ThreadPoolExecutor` is strictly FIFO, and it is the live path for
        # every panel on the AI Core screen. Replacing it would put a scheduler
        # in front of code that works; instead the queue sits beside it and
        # engages exactly where priority can matter -- when there is contention.
        # Uncontended submission is unchanged, which is what the existing tests
        # exercise.
        #
        # Imported here rather than at module scope: ai/jobs/priority.py imports
        # QueueFull from this module, and a top-level import would be a cycle.
        from ai.jobs.priority import AgeingPriorityQueue

        self._admission = AgeingPriorityQueue(max_queued=self.max_queued)
        self._running = 0

    # -- submitting ------------------------------------------------------------

    def submit(
        self,
        *,
        prompt: str,
        work: Callable[[Callable[[str], None]], Any],
        operator: str,
        timeout_s: float = DEFAULT_JOB_TIMEOUT_S,
        on_change: Callable[[Job], None] | None = None,
        priority: str = "secondary",
    ) -> str:
        """Queue a job and return its id.

        `work` is handed a `report(note)` callable so it can say what it is
        doing while it does it.

        `priority` is one of §8's tiers. It only decides anything when the pool
        is saturated: with a free worker the job starts immediately, exactly as
        before. Waiting jobs are ordered by priority MINUS how long they have
        waited, so the bottom tier cannot be starved by a stream of critical
        work — see `ai/jobs/priority.py`.
        """
        if not prompt or not prompt.strip():
            raise ValueError("a job needs a prompt")

        with self._lock:
            job = Job(id=str(uuid.uuid4()), prompt=prompt, operator=operator)
            start_now = self._running < self.max_concurrent
            if start_now:
                self._running += 1
            else:
                # Raises QueueFull at the ceiling, before the job is recorded --
                # a refused submission must not leave a job nobody will run.
                self._admission.push(
                    job.id,
                    priority=priority,
                    operator=operator,
                    payload=(work, timeout_s, on_change),
                )
            self._jobs[job.id] = job

        # §5: the conversation should know this is running. Outside the lock and
        # swallowed on failure — a context store that cannot be written to must
        # not stop work from being queued.
        _remember_task(job)

        if start_now:
            self._start(job, work, timeout_s, on_change)
        return job.id

    def _start(
        self,
        job: Job,
        work: Callable[[Callable[[str], None]], Any],
        timeout_s: float,
        on_change: Callable[[Job], None] | None,
    ) -> None:
        """Hand one job to the pool. The caller has already taken its slot."""
        future = self.executor.submit(self._run, job, work, timeout_s, on_change)
        with self._lock:
            self._futures[job.id] = future

    def _dispatch_next(self) -> None:
        """Give the freed slot to the highest-effective-priority waiter.

        Called when a job ends. If nothing is waiting the slot is released, so a
        later submission takes the immediate path rather than queueing behind an
        empty queue.
        """
        with self._lock:
            item = self._admission.pop()
            if item is None:
                self._running = max(0, self._running - 1)
                return
            job = self._jobs.get(item.id)
            if job is None or job.state != "queued":
                # Cancelled or evicted while waiting. The slot stays taken for
                # this pass and the next end releases it; recursing here would
                # hold the lock across an unbounded chain.
                self._running = max(0, self._running - 1)
                return
        work, timeout_s, on_change = item.payload
        self._start(job, work, timeout_s, on_change)

    # -- running ---------------------------------------------------------------

    def _run(
        self,
        job: Job,
        work: Callable[[Callable[[str], None]], Any],
        timeout_s: float,
        on_change: Callable[[Job], None] | None,
    ) -> None:
        """The worker body. Runs on the dedicated pool, never on the loop."""
        if job.id in self._cancelled:
            self._finish(job, "cancelled", on_change=on_change)
            return

        job.state = "running"
        job.started_at = datetime.now(UTC).isoformat()
        started = time.monotonic()
        job.timeout_s = timeout_s
        job.deadline = started + timeout_s
        self._notify(job, on_change)

        last_output_frame = [0.0]

        def report(note: str, *, kind: str = "note") -> None:
            """Say what the job is doing, or hand back a piece of the answer.

            `kind="output"` accumulates into `job.partial` and is throttled;
            everything else is a status note and is pushed immediately, because
            notes are rare and each one is a real change of what the job is
            doing.
            """
            if kind == "output":
                job.partial += str(note)
                now = time.monotonic()
                if now - last_output_frame[0] < OUTPUT_FRAME_INTERVAL_S:
                    # Coalesced. `_finish` always notifies, so the text held
                    # back here reaches the screen with the terminal state.
                    return
                last_output_frame[0] = now
                self._notify(job, on_change)
                return
            job.progress.append(str(note))
            self._notify(job, on_change)

        try:
            result = work(report)
        except Exception as exc:
            job.elapsed_s = time.monotonic() - started
            # The message, never the traceback: a job's error is rendered in a
            # panel, and a stack trace there is both useless to an operator and
            # a way to leak internals into a browser. The full trace goes to the
            # log, where it belongs.
            job.error = f"{type(exc).__name__}: {exc}"
            logger.exception("ai.jobs: job %s failed", job.id)
            self._finish(job, "failed", on_change=on_change)
            return

        job.elapsed_s = time.monotonic() - started
        if job.state == "timed_out":
            # A reader already reaped it. Its result is discarded, which is the
            # whole point of the deadline.
            return
        if job.id in self._cancelled:
            self._finish(job, "cancelled", on_change=on_change)
            return
        if job.elapsed_s > timeout_s:
            # Honest about what this can and cannot do. A Python thread cannot
            # be killed from outside, so the work has already finished by the
            # time we notice; what the deadline buys is that the result is
            # discarded and the caller is told, rather than a panel silently
            # showing an answer computed long after anyone cared.
            job.error = f"exceeded its {timeout_s:.0f}s deadline"
            self._finish(job, "timed_out", on_change=on_change)
            return

        job.result = result
        self._finish(job, "succeeded", on_change=on_change)

    def _finish(self, job: Job, state: str, *, on_change: Callable[[Job], None] | None) -> None:
        job.state = state
        job.finished_at = datetime.now(UTC).isoformat()
        _forget_task(job)
        self._notify(job, on_change)
        # Last, and outside the notify: a listener that raises must not leave
        # the slot held, or one broken screen would stall the whole pool.
        self._dispatch_next()

    @staticmethod
    def _notify(job: Job, on_change: Callable[[Job], None] | None) -> None:
        # Bump BEFORE the listener check: `rev` orders what the screen sees, and
        # the poll sees every change whether or not a publisher is installed.
        # Each job is mutated by exactly one worker thread, so a plain increment
        # is sound here; `_reap` is the one other writer and it bumps too.
        job.rev += 1
        if on_change is None:
            return
        try:
            on_change(job)
        except Exception:
            # A broken listener must never fail the job it is watching.
            logger.exception("ai.jobs: on_change listener raised for %s", job.id)

    # -- reading ---------------------------------------------------------------

    def _reap(self) -> None:
        """Promote overdue running jobs to `timed_out`.

        Called from every read path rather than by a reaper thread. A worker
        thread cannot be killed from outside, so the work carries on either way
        — but the STATE has to tell the truth at the deadline, not whenever the
        work happens to return. A panel reading "running" ten minutes past a
        two-minute ceiling is the screen lying about what it is doing.

        Lazy rather than scheduled because the only thing that cares is a
        reader, and a background thread per job would cost more than the
        problem is worth.
        """
        now = time.monotonic()
        for job in self._jobs.values():
            if job.state == "running" and job.deadline and now > job.deadline:
                job.state = "timed_out"
                job.error = f"exceeded its {job.timeout_s:.0f}s deadline"
                job.finished_at = datetime.now(UTC).isoformat()
                job.elapsed_s = job.timeout_s
                # This transition happens on a READ path and notifies nobody, so
                # the poll is the only way it reaches the screen. It has to
                # outrank the last pushed frame or a panel shows `running`
                # forever.
                job.rev += 1
                logger.warning(
                    "ai.jobs: job %s passed its %.0fs deadline; the worker thread cannot be "
                    "killed, so its result will be discarded when it returns",
                    job.id,
                    job.timeout_s,
                )

    def get(self, job_id: str, *, operator: str | None = None) -> Job:
        """One job. With `operator`, only if it is theirs.

        A missing job and another operator's job raise the same `KeyError` on
        purpose: distinguishing them turns this into an oracle for guessing
        which job ids exist.
        """
        with self._lock:
            self._reap()
            job = self._jobs[job_id]
            if operator is not None and job.operator != operator:
                raise KeyError(job_id)
            return job

    def cancel(self, job_id: str, *, operator: str | None = None) -> bool:
        """Ask a job to stop. True if it was known and this caller owns it.

        A queued job never starts. A running one is marked and its result
        discarded when it returns — see the note in `_run` about threads.

        **`operator` is what stops one admin stopping another's work.** Without
        it, any caller holding a job id could cancel any job in the process:
        measured, `bob` cancelled `alice`'s running generation. A refusal
        returns exactly what a missing job returns, so this cannot be used to
        discover which ids exist.
        """
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return False
            if operator is not None and job.operator != operator:
                return False
            if job.state in TERMINAL_STATES:
                return False
            self._cancelled.add(job_id)
            future = self._futures.get(job_id)

        if future is not None and future.cancel():
            job.state = "cancelled"
            job.finished_at = datetime.now(UTC).isoformat()
        return True

    async def wait_for(self, job_ids: list[str], *, timeout: float = 60.0) -> None:
        """Wait until every named job reaches a terminal state.

        Polls rather than awaiting the futures directly: a cancelled queued job
        has no future left to await, and its state is still the answer.
        """
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            with self._lock:
                self._reap()
                pending = [i for i in job_ids if self._jobs.get(i) and self._jobs[i].state not in TERMINAL_STATES]
            if not pending:
                return
            await asyncio.sleep(0.01)
        raise TimeoutError(f"jobs still running after {timeout}s: {pending}")

    def _evict(self) -> None:
        """Drop the oldest terminal jobs past the retention ceiling.

        Called under the lock from the same read paths as `_reap`, for the same
        reason: a reader is the only thing that cares, and a background thread
        per runner would cost more than the problem is worth.

        Insertion order is submission order — `dict` preserves it — so the
        oldest candidates come first without needing a sort.
        """
        finished = [jid for jid, job in self._jobs.items() if job.state in TERMINAL_STATES]
        excess = len(self._jobs) - MAX_RETAINED_JOBS
        for job_id in finished[: max(0, excess)]:
            self._jobs.pop(job_id, None)
            self._futures.pop(job_id, None)
            self._cancelled.discard(job_id)

    def snapshot(self, *, operator: str | None = None) -> dict[str, Any]:
        """What the screen renders. Scoped to `operator` unless asked otherwise.

        **Scoped by default.** This returned every job in the process, so on a
        two-admin deployment one admin's AI Core screen showed the other's
        prompts and the model's answers. Authentication is not authorisation,
        and a screen renders whatever the API hands it.

        `operator=None` is the unscoped platform view — a superadmin overview,
        the health surface. It has to be asked for, never defaulted to.

        The counts describe what the caller can see. A queue depth that included
        other people's work would make "why is mine waiting" unanswerable, and
        would leak how busy somebody else is.
        """
        with self._lock:
            self._reap()
            self._evict()
            mine = [j for j in self._jobs.values() if operator is None or j.operator == operator]
            jobs = [j.as_dict() for j in mine]
            running = sum(1 for j in mine if j.state == "running")
            queued = sum(1 for j in mine if j.state == "queued")
            admission = self._admission.snapshot()
        return {
            "jobs": jobs,
            "running": running,
            "queued": queued,
            # The admission queue's own depth and, more usefully, the longest
            # wait on it. Depth alone hides starvation: three waiting jobs could
            # be three seconds old or three hours old.
            "waiting": admission["waiting"],
            "longest_wait_s": admission["longest_wait_s"],
            "waiting_by_priority": admission["by_priority"],
            "max_concurrent": self.max_concurrent,
            "max_queued": self.max_queued,
        }

    def shutdown(self) -> None:
        self.executor.shutdown(wait=False, cancel_futures=True)


#: The process-wide runner, installed at startup.
_RUNNER: JobRunner | None = None


def get_runner() -> JobRunner:
    global _RUNNER
    if _RUNNER is None:
        _RUNNER = JobRunner()
    return _RUNNER


def set_runner(runner: JobRunner | None) -> None:
    global _RUNNER
    _RUNNER = runner


def reset_for_testing() -> None:
    global _RUNNER
    if _RUNNER is not None:
        _RUNNER.shutdown()
    _RUNNER = None


__all__ = [
    "DEFAULT_JOB_TIMEOUT_S",
    "DEFAULT_MAX_CONCURRENT",
    "DEFAULT_MAX_QUEUED",
    "TERMINAL_STATES",
    "Job",
    "JobRunner",
    "QueueFull",
    "get_runner",
    "reset_for_testing",
    "set_runner",
]
