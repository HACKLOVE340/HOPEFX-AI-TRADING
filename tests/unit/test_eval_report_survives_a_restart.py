# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""The promotion gate's evidence has to outlive the process holding it.

`_EVAL_REPORT` is a module global in `api/safe_agent_platform.py`. That makes
the gate blind in two ordinary situations, both of which look like the gate
working:

* **After any restart** it is `None`, so canary promotion refuses
  `no_eval_report` until somebody remembers to run the suite by hand.
* **On a second worker** it is `None` too. `ai/gateway/budget_store.py` records
  the same lesson from the same shape: `API_WORKERS` above 1 means each process
  keeps its own copy, and the number in the settings form stops meaning what it
  says.

Fail-closed makes this an availability problem rather than a safety one — which
is precisely how it gets "fixed" by someone raising `max_age_s` to a month, and
then it is a safety problem.

**Persistence must not resurrect a stale pass.** The gate's 24h age bound binds
on a restored report exactly as it does on a fresh one; a report is evidence
about the model that was measured, and storing it durably does not make it
newer. That is the test this file exists for.

These tests fail on the pre-fix tree — `ai.evals.store` does not exist there.
"""

from __future__ import annotations

import time

import pytest

pytestmark = pytest.mark.unit


class _FakeRedis:
    """Enough of the client surface for the store, with a failure switch."""

    def __init__(self) -> None:
        self.data: dict[str, str] = {}
        self.fail = False

    def set(self, key, value, ex=None):
        if self.fail:
            raise RuntimeError("redis is down")
        self.data[key] = value

    def get(self, key):
        if self.fail:
            raise RuntimeError("redis is down")
        return self.data.get(key)


@pytest.fixture(autouse=True)
def _clean():
    from ai.evals import store
    import api.safe_agent_platform as sp

    store.set_store(None)
    sp.set_eval_report(None)
    yield
    store.set_store(None)
    sp.set_eval_report(None)


def _report(score=1.0, ran_at=None, failed=()):
    from ai.evals.suite import SuiteReport

    return SuiteReport(
        score=score,
        total=6,
        passed=int(round(score * 6)),
        failed_case_ids=tuple(failed),
        ran_at=ran_at if ran_at is not None else time.time(),
    )


# ── round trip ────────────────────────────────────────────────────────────────


def test_a_report_round_trips_without_losing_anything_the_gate_reads():
    from ai.evals import store

    store.set_store(store.RedisEvalReportStore(_FakeRedis()))
    original = _report(score=0.83, failed=("risk.drawdown_above_limit",))
    store.save(original)
    restored = store.load()

    assert restored is not None
    assert restored.score == pytest.approx(original.score)
    assert restored.total == original.total
    assert restored.passed == original.passed
    assert restored.failed_case_ids == original.failed_case_ids
    assert restored.ran_at == pytest.approx(original.ran_at)


def test_the_report_survives_a_restart():
    """The whole point: a new process reads what the old one measured."""
    import api.safe_agent_platform as sp
    from ai.evals import store

    redis = _FakeRedis()
    store.set_store(store.RedisEvalReportStore(redis))
    sp.set_eval_report(_report(score=0.97))

    # A restart: the process-local global is gone, the store is not.
    sp.set_eval_report(None)
    store.set_store(store.RedisEvalReportStore(redis))

    assert sp.get_eval_report() is not None, "the gate is blind after a restart"
    assert sp.get_eval_report().score == pytest.approx(0.97)


def test_a_second_worker_sees_the_first_worker_s_report():
    """Same store, two processes' worth of module state."""
    import api.safe_agent_platform as sp
    from ai.evals import store

    redis = _FakeRedis()
    store.set_store(store.RedisEvalReportStore(redis))
    sp.set_eval_report(_report(score=0.94))

    sp.set_eval_report(None)  # worker two has never run the suite
    assert sp.get_eval_report() is not None


# ── persistence must not weaken the gate ──────────────────────────────────────


def test_a_restored_report_is_still_refused_once_it_is_stale():
    """Storing evidence durably does not make it newer. This is the assertion
    that keeps persistence from becoming a way to resurrect a passing score."""
    import api.safe_agent_platform as sp
    from ai.evals import store
    from ai.evals.gate import PromotionGate, PromotionRefused

    redis = _FakeRedis()
    store.set_store(store.RedisEvalReportStore(redis))
    sp.set_eval_report(_report(score=1.0, ran_at=time.time() - 30 * 3600))
    sp.set_eval_report(None)
    store.set_store(store.RedisEvalReportStore(redis))

    gate = PromotionGate(minimum_score={"canary": 0.9})
    with pytest.raises(PromotionRefused) as refused:
        gate.check(sp.get_eval_report(), target="canary")
    assert "stale_report" in refused.value.reason_codes


def test_no_report_anywhere_still_refuses():
    import api.safe_agent_platform as sp

    assert sp.get_eval_report() is None
    allowed, reason = sp._eval_gate_allows("canary")
    assert not allowed
    assert "no_eval_report" in reason


# ── a store outage must not become an outage of the gate ──────────────────────


def test_a_store_that_cannot_be_written_does_not_lose_the_run():
    """A Redis blip during an eval run must not discard six paid model calls."""
    import api.safe_agent_platform as sp
    from ai.evals import store

    redis = _FakeRedis()
    redis.fail = True
    store.set_store(store.RedisEvalReportStore(redis))
    sp.set_eval_report(_report(score=0.99))  # must not raise

    assert sp.get_eval_report().score == pytest.approx(0.99), "the in-process copy was dropped when the store failed"


def test_a_store_that_cannot_be_read_falls_back_to_this_process():
    """Refusing promotion because Redis blipped, while this process holds a
    perfectly good report, is a gate refusing on the wrong evidence."""
    import api.safe_agent_platform as sp
    from ai.evals import store

    redis = _FakeRedis()
    store.set_store(store.RedisEvalReportStore(redis))
    sp.set_eval_report(_report(score=0.96))
    redis.fail = True

    assert sp.get_eval_report() is not None
    assert sp.get_eval_report().score == pytest.approx(0.96)


def test_with_no_store_installed_nothing_changes():
    """A dev box has no Redis. It must behave exactly as it did before."""
    import api.safe_agent_platform as sp

    sp.set_eval_report(_report(score=0.91))
    assert sp.get_eval_report().score == pytest.approx(0.91)


def test_stored_junk_is_ignored_rather_than_crashing_the_gate():
    """Something else wrote the key, or a schema changed. Refusing to promote
    is correct; raising inside the gate's evidence lookup is not."""
    from ai.evals import store

    redis = _FakeRedis()
    redis.data[store.REPORT_KEY] = "{not json"
    store.set_store(store.RedisEvalReportStore(redis))
    assert store.load() is None
