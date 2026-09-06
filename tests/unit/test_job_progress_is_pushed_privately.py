# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""Job progress reaches the screen without polling — and only its own operator.

The workbench polls every 900ms while anything is live. That works, but it puts
a floor under how fast a panel can react and a load under a page nobody is
watching. Pushing each state change over the WebSocket already carrying prices
removes both.

**The security property is the whole point of this file.** A job payload carries
the operator's prompt and the model's answer. `ws_live` delivers a channel to a
connection with an EMPTY subscription unless that channel is listed private —
the exact defect S8-02 records, where `send_to_user` had the right user and the
wrong channel. So `ai_jobs` must be private, and a second operator's connection
must never receive these frames.

**Threads, not the loop.** Jobs run on the AI pool; `send_to_user` is a
coroutine on the event loop. The bridge has to be explicit, and a publish
failing must never fail the job it is reporting on.

These tests fail on the pre-fix tree — `ai.jobs.progress` does not exist there.
"""

from __future__ import annotations

import asyncio
import time

import pytest

pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def _clean():
    from ai.jobs import progress, runner

    runner.reset_for_testing()
    progress.reset_for_testing()
    yield
    runner.reset_for_testing()
    progress.reset_for_testing()


# ── the security property ─────────────────────────────────────────────────────


def test_the_job_channel_is_private():
    """Otherwise an empty-subscription connection receives another operator's
    prompts. This is S8-02's shape, and the reason that finding exists."""
    from api.ws_live import LiveConnectionManager

    assert "ai_jobs" in LiveConnectionManager._PRIVATE_CHANNELS, (
        "ai_jobs is not private, so the empty-subscription firehose delivers it"
    )


@pytest.mark.asyncio
async def test_progress_is_addressed_to_the_operator_who_started_the_job():
    from ai.jobs import progress

    sent: list[tuple[str, str, dict]] = []

    async def fake_send(user_id, channel, msg):
        sent.append((user_id, channel, msg))

    progress.install(send_to_user=fake_send, loop=asyncio.get_running_loop())

    from ai.jobs.runner import Job

    progress.publish(Job(id="j1", prompt="my private question", operator="alice"))
    await asyncio.sleep(0.05)

    assert sent, "nothing was published"
    user_id, channel, _msg = sent[0]
    assert user_id == "alice"
    assert channel == "ai_jobs"


@pytest.mark.asyncio
async def test_a_job_payload_never_goes_to_another_operator():
    """The end-to-end version of the property above."""
    from ai.jobs import progress
    from ai.jobs.runner import Job

    seen_by: dict[str, list[dict]] = {}

    async def fake_send(user_id, channel, msg):
        seen_by.setdefault(user_id, []).append(msg)

    progress.install(send_to_user=fake_send, loop=asyncio.get_running_loop())
    progress.publish(Job(id="j1", prompt="alice's secret prompt", operator="alice"))
    await asyncio.sleep(0.05)

    assert "bob" not in seen_by
    blob = repr(seen_by.get("alice", []))
    assert "alice's secret prompt" in blob


# ── the bridge ────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_a_change_from_a_worker_thread_reaches_the_loop():
    """Jobs run on the AI pool; send_to_user is a coroutine. The hop is real."""
    from ai.jobs import progress
    from ai.jobs.runner import JobRunner

    sent: list[dict] = []

    async def fake_send(_user_id, _channel, msg):
        sent.append(msg)

    progress.install(send_to_user=fake_send, loop=asyncio.get_running_loop())

    runner = JobRunner(max_concurrent=2)

    def work(report):
        report("contacting the model")
        return "ok"

    job_id = runner.submit(prompt="p", work=work, operator="owner", on_change=progress.publish)
    await runner.wait_for([job_id], timeout=5.0)
    await asyncio.sleep(0.1)

    states = [m["data"]["state"] for m in sent]
    assert "running" in states
    assert "succeeded" in states


@pytest.mark.asyncio
async def test_a_publish_failure_never_fails_the_job(caplog):
    """A browser that went away must not break the work it was watching."""
    import logging

    from ai.jobs import progress
    from ai.jobs.runner import JobRunner

    async def explode(_user_id, _channel, _msg):
        raise RuntimeError("socket is gone")

    progress.install(send_to_user=explode, loop=asyncio.get_running_loop())
    runner = JobRunner(max_concurrent=2)

    with caplog.at_level(logging.WARNING):
        job_id = runner.submit(prompt="p", work=lambda _r: "ok", operator="owner", on_change=progress.publish)
        await runner.wait_for([job_id], timeout=5.0)
        await asyncio.sleep(0.1)

    assert runner.get(job_id).state == "succeeded", "a publish failure failed the job"


def test_publishing_with_nothing_installed_is_a_no_op():
    """A dev box with no WebSocket must not raise on every state change."""
    from ai.jobs import progress
    from ai.jobs.runner import Job

    progress.publish(Job(id="j", prompt="p", operator="owner"))  # must not raise


@pytest.mark.asyncio
async def test_the_frame_carries_what_a_panel_needs_to_render():
    from ai.jobs import progress
    from ai.jobs.runner import Job

    sent: list[dict] = []

    async def fake_send(_u, _c, msg):
        sent.append(msg)

    progress.install(send_to_user=fake_send, loop=asyncio.get_running_loop())
    progress.publish(Job(id="j1", prompt="p", operator="owner", state="running", progress=["step one"]))
    await asyncio.sleep(0.05)

    frame = sent[0]
    assert frame["type"] == "ai_job_update"
    # The body lives under `data`, the shape every other handler in
    # `useWebSocket` reads — and the shape that keeps a job's own keys out of
    # the same namespace as the envelope's `type`/`channel`/`seq`.
    body = frame["data"]
    for key in ("id", "state", "prompt", "progress", "rev"):
        assert key in body, f"the frame has no {key!r}, so a panel cannot render it"


# ── the wiring ────────────────────────────────────────────────────────────────


def test_a_startup_factory_installs_the_publisher():
    import pathlib

    import core.startup_factories as F

    assert hasattr(F, "init_ai_job_progress"), "no startup factory for job progress"
    src = pathlib.Path(F.__file__).read_text(encoding="utf-8")
    assert "F.init_ai_job_progress" in src, "the factory is defined but never registered"


@pytest.mark.asyncio
async def test_the_submit_endpoint_attaches_the_publisher():
    """Otherwise jobs run and the screen still has to poll for everything."""
    import inspect

    import api.safe_agent_platform as sp

    src = inspect.getsource(sp.submit_generation)
    assert "on_change" in src, "submitted jobs do not report their changes anywhere"


def test_the_runner_still_works_without_a_publisher():
    """Polling stays the fallback; push is an improvement, not a dependency."""
    from ai.jobs.runner import JobRunner

    runner = JobRunner(max_concurrent=1)
    job_id = runner.submit(prompt="p", work=lambda _r: "ok", operator="owner")
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline and runner.get(job_id).state != "succeeded":
        time.sleep(0.01)
    assert runner.get(job_id).state == "succeeded"


# ── the factory has to actually run ───────────────────────────────────────────


@pytest.mark.asyncio
async def test_the_startup_factory_installs_the_publisher_when_called():
    """`hasattr` and "is registered" are not execution.

    The first draft of this factory imported `api.ws_live.manager`, a name that
    does not exist — the module exposes `get_live_manager()`. It passed both
    assertions above and would have raised ImportError on the first startup.
    This test calls it.
    """
    from types import SimpleNamespace

    import core.startup_factories as F
    from ai.jobs import progress

    assert not progress.installed()
    await F.init_ai_job_progress(SimpleNamespace())
    assert progress.installed(), "the factory ran and progress is still not installed"


# ── the frame the browser routes on ───────────────────────────────────────────


@pytest.mark.asyncio
async def test_a_frame_says_what_kind_of_message_it_is():
    """`ws_live` stamps a channel, but the browser routes on `type`. Without
    one, every job frame falls through the client's switch and is dropped —
    a push channel that pushes into nothing."""
    from ai.jobs import progress
    from ai.jobs.runner import Job

    sent: list[dict] = []

    async def fake_send(_u, _c, msg):
        sent.append(msg)

    progress.install(send_to_user=fake_send, loop=asyncio.get_running_loop())
    progress.publish(Job(id="j1", prompt="p", operator="owner"))
    await asyncio.sleep(0.05)

    assert sent[0].get("type") == "ai_job_update"
    assert sent[0]["data"]["id"] == "j1"


# ── ordering: a late push must not overwrite a newer poll ──────────────────────


def test_every_change_raises_the_revision():
    """The screen merges pushed frames over polled ones. Without a monotonic
    marker it cannot tell a late frame from a new one, and a job that already
    succeeded flickers back to `running` when a delayed frame lands."""
    from ai.jobs.runner import JobRunner

    seen: list[int] = []
    runner = JobRunner(max_concurrent=1)

    def work(report):
        report("one")
        report("two")
        return "ok"

    job_id = runner.submit(prompt="p", work=work, operator="owner", on_change=lambda j: seen.append(j.rev))
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline and runner.get(job_id).state != "succeeded":
        time.sleep(0.01)

    assert seen == sorted(seen) and len(set(seen)) == len(seen), f"revisions not monotonic: {seen}"
    assert runner.get(job_id).as_dict()["rev"] == seen[-1]


def test_a_reaped_timeout_raises_the_revision_too():
    """`_reap` promotes a job on a READ path and notifies nobody, so the poll is
    the only way that transition reaches the screen. It has to outrank whatever
    frame was pushed last, or the panel keeps showing `running` forever."""
    from ai.jobs.runner import Job, JobRunner

    runner = JobRunner(max_concurrent=1)
    job = Job(id="stuck", prompt="p", operator="owner", state="running")
    job.deadline = time.monotonic() - 1.0
    job.rev = 7
    runner._jobs[job.id] = job

    reaped = runner.get("stuck")
    assert reaped.state == "timed_out"
    assert reaped.rev > 7, "a reaped timeout did not raise the revision, so a stale push outranks it"


def test_the_operator_id_is_the_same_identity_ws_live_addresses():
    """The two sides have to agree on what a user is called, or every frame is
    addressed to a name no connection is registered under and the push is a
    dead control: publishing happily, delivering to nobody.

    `ws_live` registers a connection under the JWT `sub`; `submit_generation`
    labels a job with `user.sub`. Same claim, checked here because nothing else
    makes the two files agree.
    """
    import inspect
    import re

    import api.safe_agent_platform as sp
    import api.ws_live as wl

    ws_src = inspect.getsource(wl)
    assert re.search(r'user_id\s*=\s*str\(payload\.get\("sub"', ws_src), (
        "ws_live no longer registers connections under the JWT `sub`"
    )

    submit_src = inspect.getsource(sp.submit_generation)
    assert "operator=user.sub" in submit_src, "a job is no longer labelled with the JWT `sub`"
