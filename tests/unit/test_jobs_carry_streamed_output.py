# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""A job can report the answer as it arrives, not only that it is working.

`report(note)` says what a job is doing; that is a status line, and a panel
showing "contacting the model" for forty seconds still communicates nothing
about the answer. Streamed text needs somewhere else to go: `progress` is a
list of notes, and appending every delta to it would turn a status log into a
transcript rendered as bullet points.

So `report(text, kind="output")` accumulates into `Job.partial`, and the
`as_dict` the screen reads carries it.

**Coalescing is the point of the second half of this file.** One notification
per delta is one WebSocket frame per delta. A fast model emits hundreds a
second, per panel, times four panels — a push channel that becomes its own
outage. Frames are coalesced on a short interval, and the terminal state always
flushes so the last words of an answer are never the ones that get dropped.

These tests fail on the pre-fix tree — `Job.partial` does not exist there.
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


def _await(runner, job_id, timeout=5.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        job = runner.get(job_id)
        if job.state in {"succeeded", "failed", "cancelled", "timed_out"}:
            return job
        time.sleep(0.01)
    raise AssertionError(f"job never finished; last state {runner.get(job_id).state}")


# ── output has its own place to go ────────────────────────────────────────────


def test_streamed_text_accumulates_on_the_job():
    from ai.jobs.runner import JobRunner

    runner = JobRunner(max_concurrent=1)

    def work(report):
        report("contacting the model")
        report("Gold is ", kind="output")
        report("range-bound.", kind="output")
        return "done"

    job = _await(runner, runner.submit(prompt="p", work=work, operator="owner"))
    assert job.partial == "Gold is range-bound."


def test_a_status_note_is_not_mistaken_for_output():
    """Otherwise 'contacting the model' is rendered as part of the answer."""
    from ai.jobs.runner import JobRunner

    runner = JobRunner(max_concurrent=1)

    def work(report):
        report("contacting the model")
        report("the answer", kind="output")
        return "done"

    job = _await(runner, runner.submit(prompt="p", work=work, operator="owner"))
    assert job.partial == "the answer"
    assert job.progress == ["contacting the model"]


def test_the_screen_can_read_the_partial_answer():
    from ai.jobs.runner import JobRunner

    runner = JobRunner(max_concurrent=1)
    job = _await(
        runner,
        runner.submit(prompt="p", work=lambda r: r("half an answer", kind="output"), operator="owner"),
    )
    assert runner.get(job.id).as_dict()["partial"] == "half an answer"


# ── coalescing ────────────────────────────────────────────────────────────────


def test_hundreds_of_deltas_do_not_become_hundreds_of_frames():
    """One frame per token, per panel, times four panels, is a push channel
    that becomes its own outage."""
    from ai.jobs.runner import JobRunner

    frames: list[str] = []
    runner = JobRunner(max_concurrent=1)

    def work(report):
        for i in range(400):
            report(f"token{i} ", kind="output")
        return "done"

    job_id = runner.submit(prompt="p", work=work, operator="owner", on_change=lambda j: frames.append(j.partial))
    _await(runner, job_id)
    # Non-emptiness first: "fewer than 100" is satisfied by zero, and a test
    # that passes against an unimplemented feature is not a test.
    assert frames, "no frames at all"
    assert len(frames) < 100, f"{len(frames)} frames for 400 deltas; nothing is being coalesced"


def test_the_last_words_of_an_answer_are_never_dropped():
    """The failure coalescing invites: a final burst inside the quiet window,
    so the panel ends up showing an answer missing its ending."""
    from ai.jobs.runner import JobRunner

    frames: list[str] = []
    runner = JobRunner(max_concurrent=1)

    def work(report):
        for i in range(400):
            report(f"token{i} ", kind="output")
        report("THE FINAL WORD", kind="output")
        return "done"

    job_id = runner.submit(prompt="p", work=work, operator="owner", on_change=lambda j: frames.append(j.partial))
    job = _await(runner, job_id)
    assert job.partial.endswith("THE FINAL WORD")
    assert frames and frames[-1].endswith("THE FINAL WORD"), "the terminal state did not flush the tail"


def test_a_slow_stream_still_updates_as_it_goes():
    """Coalescing must not turn streaming back into buffering."""
    from ai.jobs.runner import JobRunner

    frames: list[str] = []
    runner = JobRunner(max_concurrent=1)

    def work(report):
        for i in range(5):
            report(f"chunk{i} ", kind="output")
            time.sleep(0.2)
        return "done"

    _await(runner, runner.submit(prompt="p", work=work, operator="owner", on_change=lambda j: frames.append(j.partial)))
    # running + several output frames + terminal.
    assert len(frames) >= 5, f"only {len(frames)} frames for a stream spread over a second"


def test_the_revision_still_rises_across_coalesced_frames():
    """The screen orders push against poll by `rev`. A coalesced frame that
    reuses a revision lets a later poll silently win over newer text."""
    from ai.jobs.runner import JobRunner

    revs: list[int] = []
    runner = JobRunner(max_concurrent=1)

    def work(report):
        for i in range(200):
            report(f"t{i} ", kind="output")
        return "done"

    _await(runner, runner.submit(prompt="p", work=work, operator="owner", on_change=lambda j: revs.append(j.rev)))
    assert revs, "no frames at all"
    assert revs == sorted(revs)
    assert len(set(revs)) == len(revs), "two frames shared a revision"
