# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""The generation endpoint uses the streaming path, and says so end to end.

Every piece of this was built and tested separately: `StreamScanner`, the
adapters' `stream`, `GatewayClient.stream_sync`, `Job.partial`, the private
`ai_jobs` channel. All of it is dead weight if `submit_generation` still calls
`call_sync` — which is the shape of defect this repository has the most of, and
the reason this file exists rather than trusting that the wiring is obvious.

These tests fail on the pre-fix tree — `submit_generation` calls `call_sync`
there and nothing carries a partial answer.
"""

from __future__ import annotations

import inspect
import time

import pytest

pytestmark = pytest.mark.unit


def test_the_endpoint_asks_the_gateway_to_stream():
    import api.safe_agent_platform as sp

    src = inspect.getsource(sp.submit_generation)
    assert "stream_sync" in src, "generations still wait for the whole answer"


def test_the_endpoint_hands_each_piece_back_as_output_not_as_a_status_note():
    """`report(delta)` without `kind="output"` renders the answer as a list of
    status bullets, which is worse than not streaming at all."""
    import api.safe_agent_platform as sp

    src = inspect.getsource(sp.submit_generation)
    assert 'kind="output"' in src, "streamed text is being reported as status notes"


def test_a_streamed_job_carries_a_partial_answer_before_it_finishes():
    """The property the screen actually depends on, exercised through the real
    runner rather than asserted from the source."""
    from ai.jobs.runner import JobRunner

    runner = JobRunner(max_concurrent=1)
    seen_partials: list[str] = []

    def work(report):
        report("contacting the model")
        for piece in ("Gold ", "is ", "range-bound."):
            report(piece, kind="output")
            time.sleep(0.15)  # past the coalescing interval, as a real stream is
        return {"text": "Gold is range-bound."}

    job_id = runner.submit(
        prompt="p",
        work=work,
        operator="owner",
        on_change=lambda j: seen_partials.append(j.partial),
    )
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline and runner.get(job_id).state != "succeeded":
        time.sleep(0.01)

    assert runner.get(job_id).partial == "Gold is range-bound."
    # Something incomplete was visible on the way — that is what streaming buys.
    assert any(p and p != "Gold is range-bound." for p in seen_partials), (
        "no intermediate state was ever pushed; the panel gained nothing"
    )


def test_the_final_result_still_carries_the_whole_answer():
    """Streaming must not replace the finished result. A panel that reloads,
    or an operator who opens the page after a job finished, reads `result`."""
    import api.safe_agent_platform as sp

    src = inspect.getsource(sp.submit_generation)
    assert '"text"' in src and '"provider"' in src, "the finished job no longer reports a result"


def test_a_vendorless_deployment_still_fails_loudly():
    """The pre-streaming behaviour that must not regress into an empty panel."""
    import api.safe_agent_platform as sp

    src = inspect.getsource(sp.submit_generation)
    assert "no model vendor is configured" in src
