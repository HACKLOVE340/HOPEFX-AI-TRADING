# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""A monthly ceiling that a restart returns to zero is not a ceiling.

`ai/gateway/budget.py` kept `_spend` and the velocity deque as module globals
with no persistence at all. Two consequences, one live and one latent:

* **Live** — every process restart reset the month's spend to $0. A deployment
  that restarts daily has no effective monthly cap.
* **Latent** — `API_WORKERS` defaults to 1, but at any higher value each worker
  process keeps its *own* `_spend` dict, so the real ceiling becomes N times
  what the operator set. Nothing warns; the number in the settings form simply
  stops meaning what it says.

The fix is a pluggable store: in-memory by default (unchanged behaviour, and
the fallback), Redis when a deployment installs it, so the counter is both
durable and shared.

These tests fail on the pre-fix tree — `set_store`, `BudgetStore` and
`store_is_shared` do not exist there.
"""

from __future__ import annotations

import logging

import pytest

from ai.gateway import budget

pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def _clean():
    budget.reset_for_testing()
    yield
    budget.reset_for_testing()


class _FakeShared:
    """Stands in for Redis: state that outlives one process's globals."""

    shared = True

    def __init__(self, seed: dict[str, float] | None = None):
        self.spend: dict[str, float] = dict(seed or {})
        self.events: list[tuple[float, str, float]] = []
        self.fail = False

    def _boom(self):
        if self.fail:
            raise ConnectionError("redis is gone")

    def get_spend(self, period):
        self._boom()
        return dict(self.spend)

    def add_spend(self, period, operator, cost):
        self._boom()
        self.spend[operator] = self.spend.get(operator, 0.0) + cost

    def record_event(self, ts, operator, cost):
        self._boom()
        self.events.append((ts, operator, cost))

    def window_events(self, since_ts):
        self._boom()
        return [e for e in self.events if e[0] >= since_ts]


def test_spend_is_read_back_from_the_shared_store():
    """The restart case: this process never charged, but the month has spend."""
    budget.set_store(_FakeShared({"owner": 12.50}))
    assert budget.spent("owner") == pytest.approx(12.50)
    assert budget.total_spent() == pytest.approx(12.50)


def test_a_restart_does_not_hand_the_operator_a_fresh_ceiling():
    """The defect, stated as a test."""
    store = _FakeShared()
    budget.set_store(store)
    budget.set_limits(per_operator_usd=10.0, global_usd=100.0)
    budget.charge("owner", 9.99)

    # A restart: module globals are gone, the shared store is not.
    budget.reset_for_testing()
    budget.set_store(store)
    budget.set_limits(per_operator_usd=10.0, global_usd=100.0)

    allowed, reason = budget.check("owner", 1.0)
    assert allowed is False, "a restart handed the operator their ceiling back"
    assert "exhausted" in reason


def test_two_workers_sharing_a_store_share_one_ceiling():
    """API_WORKERS>1 must not multiply the cap."""
    store = _FakeShared()
    budget.set_store(store)
    budget.set_limits(per_operator_usd=10.0, global_usd=100.0)
    budget.charge("owner", 6.0)  # "worker A"

    budget.reset_for_testing()  # "worker B" — separate process, same store
    budget.set_store(store)
    budget.set_limits(per_operator_usd=10.0, global_usd=100.0)
    budget.charge("owner", 5.0)

    allowed, _ = budget.check("owner", 0.0)
    assert allowed is False, "two workers each got the full ceiling"
    assert store.spend["owner"] == pytest.approx(11.0)


def test_the_velocity_brake_is_shared_too():
    """A rate limit that only sees one worker's calls is not a rate limit."""
    store = _FakeShared()
    budget.set_store(store)
    for _ in range(5):
        budget.charge("owner", 0.0)

    budget.reset_for_testing()
    budget.set_store(store)
    assert budget.recent_calls("owner") == 5


def test_a_store_outage_falls_back_locally_and_is_reported_at_error(caplog):
    """Availability vs accuracy, decided deliberately.

    A Redis blip must not stop the platform answering. But the local counter
    only ever sees this worker, so it UNDER-counts — and silently under-counting
    a money ceiling is how a cap stops binding without anyone noticing. The
    fallback is allowed; the silence is not.
    """
    store = _FakeShared()
    budget.set_store(store)
    budget.set_limits(per_operator_usd=10.0, global_usd=100.0)
    budget.charge("owner", 2.0)

    store.fail = True
    with caplog.at_level(logging.ERROR):
        allowed, _ = budget.check("owner", 0.5)

    assert allowed is True, "a store outage must not refuse every call"
    assert any(r.levelno >= logging.ERROR for r in caplog.records), "a budget store outage was not reported at ERROR"


def test_last_known_shared_spend_is_a_floor_during_an_outage():
    """Degrade to the most accurate answer available, not the most permissive.

    During an outage the local view starts at zero. Treating the last value
    read from the shared store as a floor keeps the ceiling roughly honest
    instead of handing out a fresh budget for the duration of the incident.
    """
    store = _FakeShared({"owner": 9.0})
    budget.set_store(store)
    budget.set_limits(per_operator_usd=10.0, global_usd=100.0)
    budget.spent("owner")  # observe 9.00 while the store is up

    store.fail = True
    budget.charge("owner", 0.75)

    assert budget.spent("owner") >= 9.0, "the outage reset the operator's spend to near zero"


def test_the_default_store_is_in_memory_and_says_it_is_not_shared():
    """Unchanged behaviour with nothing installed — and honest about it."""
    assert budget.store_is_shared() is False
    budget.set_limits(per_operator_usd=10.0, global_usd=100.0)
    budget.charge("owner", 3.0)
    assert budget.spent("owner") == pytest.approx(3.0)


def test_installing_a_shared_store_is_visible_to_the_health_surface():
    """So a deployment can see whether its ceiling is real."""
    assert budget.store_is_shared() is False
    budget.set_store(_FakeShared())
    assert budget.store_is_shared() is True


# ── the wiring ────────────────────────────────────────────────────────────────


def test_a_startup_factory_exists_and_is_registered():
    import pathlib

    import core.startup_factories as F

    assert hasattr(F, "init_ai_budget_store"), "no startup factory for the budget store"
    src = pathlib.Path(F.__file__).read_text(encoding="utf-8")
    assert "F.init_ai_budget_store" in src, "the factory is defined but never registered"


# ── the Redis implementation itself ───────────────────────────────────────────
# The tests above use a fake to prove budget.py's contract. These drive the real
# RedisBudgetStore against fakeredis, so the implementation is not shipped on
# the strength of a stand-in that shares none of its code.


@pytest.fixture
def redis_store():
    fakeredis = pytest.importorskip("fakeredis")
    from ai.gateway.budget_store import RedisBudgetStore

    return RedisBudgetStore(fakeredis.FakeStrictRedis())


def test_redis_store_accumulates_spend_across_calls(redis_store):
    redis_store.add_spend("2026-09", "owner", 1.25)
    redis_store.add_spend("2026-09", "owner", 2.75)
    redis_store.add_spend("2026-09", "analyst", 0.50)

    spend = redis_store.get_spend("2026-09")
    assert spend["owner"] == pytest.approx(4.0)
    assert spend["analyst"] == pytest.approx(0.5)


def test_redis_store_keeps_months_apart(redis_store):
    redis_store.add_spend("2026-08", "owner", 5.0)
    redis_store.add_spend("2026-09", "owner", 1.0)
    assert redis_store.get_spend("2026-09")["owner"] == pytest.approx(1.0)


def test_redis_store_reports_an_empty_month_as_empty(redis_store):
    assert redis_store.get_spend("2026-01") == {}


def test_redis_store_round_trips_window_events_in_the_monotonic_frame(redis_store):
    """The clock conversion is the part most likely to be wrong.

    Events are scored by wall clock so workers can agree; callers work in
    time.monotonic(). A sign error here would make the window either always
    empty or never expire.
    """
    import time

    redis_store.record_event(time.monotonic(), "owner", 0.10)
    redis_store.record_event(time.monotonic(), "owner", 0.20)

    events = redis_store.window_events(time.monotonic() - 60)
    assert len(events) == 2
    assert {who for _ts, who, _c in events} == {"owner"}
    assert sum(c for _ts, _w, c in events) == pytest.approx(0.30)
    # Returned timestamps must be comparable to the caller's own clock.
    assert all(abs(ts - time.monotonic()) < 60 for ts, _w, _c in events)


def test_redis_store_excludes_events_older_than_the_window(redis_store):
    import time

    redis_store.record_event(time.monotonic() - 7200, "owner", 1.0)
    redis_store.record_event(time.monotonic(), "owner", 2.0)

    events = redis_store.window_events(time.monotonic() - 3600)
    assert len(events) == 1, "an event outside the window was counted"
    assert events[0][2] == pytest.approx(2.0)


def test_redis_store_declares_itself_shared(redis_store):
    assert redis_store.shared is True


def test_build_from_env_returns_none_without_a_redis_url(monkeypatch):
    """A dev box with no Redis keeps the old behaviour instead of failing."""
    from ai.gateway import budget_store

    monkeypatch.delenv("REDIS_URL", raising=False)
    assert budget_store.build_from_env() is None


def test_the_real_store_satisfies_the_protocol_budget_expects(redis_store):
    """Catches a rename on one side of the seam."""
    for method in ("get_spend", "add_spend", "record_event", "window_events"):
        assert callable(getattr(redis_store, method, None)), f"RedisBudgetStore has no {method}"
