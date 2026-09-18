# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""Whether the AI's durable state is actually durable, said out loud.

Three functions exist to answer that question:

    ai.gateway.budget.store_is_shared()
    ai.gateway.audit.durable_sink_installed()
    ai.evals.store.store_is_shared()

Each is described in `core/startup_factories.py` as what "the health surface
reads back". Measured: nothing read any of them. Three accessors written for a
consumer that was never built — and meanwhile the difference they report is one
an operator has to know, because every one of them fails in the same silent
direction. A per-process spend ceiling still refuses calls, an in-memory audit
trail still records them, a per-process eval report still gates promotions. They
just do it with a fraction of the state they appear to have.

The second half of this file is a narrower bug with the same shape:
`GET /ai-core/evals` read `_EVAL_REPORT` — the private module global — rather
than the accessor the gate uses. With a shared store installed, the page would
show "no report" while the gate promoted happily from Redis.

These tests fail on the pre-fix tree.
"""

from __future__ import annotations

import time

import pytest

pytestmark = pytest.mark.unit


class _FakeRedis:
    def __init__(self) -> None:
        self.data: dict[str, str] = {}

    def set(self, key, value, ex=None):
        self.data[key] = value

    def get(self, key):
        return self.data.get(key)


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    from ai.evals import store
    import api.safe_agent_platform as sp

    monkeypatch.delenv("AI_EVAL_SCHEDULE_HOURS", raising=False)
    store.set_store(None)
    sp.set_eval_report(None)
    yield
    store.set_store(None)
    sp.set_eval_report(None)


def _report(score=0.95, ran_at=None):
    from ai.evals.suite import SuiteReport

    return SuiteReport(score=score, total=6, passed=6, failed_case_ids=(), ran_at=ran_at or time.time())


# ── the page and the gate must agree ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_the_evals_page_sees_a_report_that_only_the_store_holds():
    """Otherwise the page says 'no report' while the gate promotes from Redis."""
    import api.safe_agent_platform as sp
    from ai.evals import store
    from api.ai_core import ai_core_evals

    redis = _FakeRedis()
    store.set_store(store.RedisEvalReportStore(redis))
    sp.set_eval_report(_report(score=0.93))
    sp.set_eval_report(None)  # this worker restarted; Redis did not

    body = await ai_core_evals(_viewer_token())
    assert body["report"] is not None, "the page cannot see the report the gate is using"
    assert body["report"]["score"] == pytest.approx(0.93)


@pytest.mark.asyncio
async def test_the_evals_page_still_shows_no_report_when_there_is_none():
    """'No report' is a state the page must show — it is the reason a promotion
    is being refused, and a blank panel hides it."""
    from api.ai_core import ai_core_evals

    body = await ai_core_evals(_viewer_token())
    assert body["report"] is None
    assert body["promotion_allowed"] is False


# ── durability, reported ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_the_summary_says_whether_each_durable_store_is_actually_installed():
    from api.ai_core import ai_core_summary

    body = await ai_core_summary(_viewer_token())
    durability = body.get("durability")
    assert durability is not None, "nothing reports whether the AI's state survives a restart"
    for key in ("budget_shared", "audit_durable", "eval_report_shared", "eval_schedule_hours"):
        assert key in durability, f"durability does not report {key!r}"


@pytest.mark.asyncio
async def test_it_reports_the_truth_rather_than_a_constant():
    """A report that cannot say 'no' is the shape of `invariant_coverage.py`
    before F176: a measurement that counted hand-typed True literals."""
    from ai.evals import store
    from api.ai_core import ai_core_summary

    before = (await ai_core_summary(_viewer_token()))["durability"]
    assert before["eval_report_shared"] is False

    store.set_store(store.RedisEvalReportStore(_FakeRedis()))
    after = (await ai_core_summary(_viewer_token()))["durability"]
    assert after["eval_report_shared"] is True


@pytest.mark.asyncio
async def test_it_reports_the_eval_schedule_being_off(monkeypatch):
    from api.ai_core import ai_core_summary

    assert (await ai_core_summary(_viewer_token()))["durability"]["eval_schedule_hours"] is None

    monkeypatch.setenv("AI_EVAL_SCHEDULE_HOURS", "12")
    assert (await ai_core_summary(_viewer_token()))["durability"]["eval_schedule_hours"] == pytest.approx(12.0)


def _viewer_token():
    from api.auth import TokenPayload

    return TokenPayload(sub="owner", role="superadmin")
