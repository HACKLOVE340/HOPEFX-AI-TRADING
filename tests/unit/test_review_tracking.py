# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""What the operator has actually looked at, and when.

Owner requirement, 2026-09-10: everything on the AI Core page should run in the
background and surface itself — *"pop it up or ask if operator want to check, or
if it been a while you have check it, or operator haven't request for it at
all."*

Three of the four pieces already existed:

* `ai/awareness/watchers.py` — departments observe on their own and raise
  proposals. Structurally cannot act.
* `ai/notify/policy.py` — when the AI may interrupt, with a floor: a CRITICAL
  notification is never suppressed.
* `frontend/src/hub/attention.ts` — whether anybody is looking, without a camera.

The fourth did not. A grep for `last_reviewed` / `unseen` / `acknowledged_at`
across `ai/`, `api/` and `frontend/src` returned exactly one hit, and it was a
comment. Nothing recorded what an operator had looked at, so "it has been a
while since you checked this" was a sentence the platform could not say.

## The honesty problem this design turns on

"Never reviewed" is a claim, and it is only as good as the memory behind it. A
store that lost its contents on restart would report *every* surface as never
reviewed, and the AI would open by telling an operator who checks the drift
report daily that they have never looked at it. That is not a cosmetic bug — it
is the platform asserting something false about the person using it, and it
would train them to ignore the whole mechanism.

So the store says which it is. `ReviewState.durable` is False when the record
came from a store that does not survive a restart, and `state` is `"unknown"`
rather than `"never"` in that case. Never-measured is absent, not best-case and
not worst-case — Rule 2, pointed at the operator instead of at a price.

## Cadence

"Overdue" needs an expected cadence. A surface that never declared one cannot be
overdue and is not fresh either; it is `no_cadence`. Inventing a default would
manufacture urgency about something nobody said was urgent.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from unittest.mock import patch


def _at(seconds_ago: float) -> datetime:
    return datetime.now(UTC) - timedelta(seconds=seconds_ago)


@pytest.fixture
def tracker():
    """A tracker over an explicitly non-durable store."""
    from ai.awareness.reviewed import InMemoryReviewStore, ReviewTracker

    return ReviewTracker(store=InMemoryReviewStore())


@pytest.fixture
def durable_tracker():
    """A tracker whose store claims to survive a restart."""
    from ai.awareness.reviewed import InMemoryReviewStore, ReviewTracker

    return ReviewTracker(store=InMemoryReviewStore(durable=True))


# ── the registry ──────────────────────────────────────────────────────────────


class TestSurfacesAreDeclaredNotGuessed:
    def test_an_unregistered_surface_is_refused(self):
        """Reviewing something nobody declared is a typo, not a review."""
        from ai.awareness.reviewed import ReviewTracker, UnknownSurface

        t = ReviewTracker()
        with pytest.raises(UnknownSurface):
            t.mark_reviewed("not-a-real-surface", actor="ops")

    def test_the_registry_carries_a_human_label(self):
        from ai.awareness.reviewed import REVIEWABLE_SURFACES

        assert REVIEWABLE_SURFACES, "no surfaces declared"
        for sid, surface in REVIEWABLE_SURFACES.items():
            assert surface.label.strip(), f"{sid} has no label an operator could read"
            assert surface.id == sid


# ── the four states ───────────────────────────────────────────────────────────


class TestStateIsHonest:
    def test_a_never_reviewed_surface_on_a_durable_store_says_never(self, durable_tracker):
        sid = next(iter(_ids()))
        state = durable_tracker.state(sid)
        assert state.state == "never"
        assert state.last_reviewed_at is None
        assert state.age_s is None, "an unmeasured age must be None, never 0.0"

    def test_a_never_reviewed_surface_on_a_volatile_store_says_unknown(self, tracker):
        """The distinction the whole design exists for.

        A volatile store cannot tell "you have never looked at this" apart from
        "I forgot". Reporting the first would have the AI open by telling a
        daily reader they have never opened it.
        """
        sid = next(iter(_ids()))
        state = tracker.state(sid)
        assert state.state == "unknown"
        assert state.durable is False

    def test_a_recent_review_is_fresh(self, durable_tracker):
        sid = _with_cadence()
        durable_tracker.mark_reviewed(sid, actor="ops", at=_at(5))
        state = durable_tracker.state(sid)
        assert state.state == "fresh"
        assert state.age_s == pytest.approx(5, abs=2)
        assert state.reviewed_by == "ops"

    def test_a_review_older_than_the_cadence_is_stale(self, durable_tracker):
        from ai.awareness.reviewed import REVIEWABLE_SURFACES

        sid = _with_cadence()
        cadence = REVIEWABLE_SURFACES[sid].cadence_s
        durable_tracker.mark_reviewed(sid, actor="ops", at=_at(cadence * 3))
        assert durable_tracker.state(sid).state == "stale"

    def test_a_surface_with_no_cadence_is_never_stale(self, durable_tracker):
        """Inventing a cadence would manufacture urgency nobody asked for."""
        sid = _without_cadence()
        if sid is None:
            pytest.skip("every declared surface has a cadence")
        durable_tracker.mark_reviewed(sid, actor="ops", at=_at(86_400 * 30))
        state = durable_tracker.state(sid)
        assert state.state == "no_cadence"


# ── what the AI should raise ──────────────────────────────────────────────────


class TestDueForReview:
    def test_stale_surfaces_are_returned(self, durable_tracker):
        sid = _with_cadence()
        from ai.awareness.reviewed import REVIEWABLE_SURFACES

        durable_tracker.mark_reviewed(sid, actor="ops", at=_at(REVIEWABLE_SURFACES[sid].cadence_s * 5))
        due = durable_tracker.due_for_review()
        assert sid in {s.surface_id for s in due}

    def test_a_freshly_reviewed_surface_is_not_returned(self, durable_tracker):
        sid = _with_cadence()
        durable_tracker.mark_reviewed(sid, actor="ops", at=_at(1))
        assert sid not in {s.surface_id for s in durable_tracker.due_for_review()}

    def test_never_reviewed_counts_as_due_on_a_durable_store(self, durable_tracker):
        """ "Operator haven't request for it at all" — the owner's third case."""
        sid = _with_cadence()
        assert sid in {s.surface_id for s in durable_tracker.due_for_review()}

    def test_unknown_does_not_count_as_due(self, tracker):
        """A volatile store must not raise everything as due after a restart.

        Otherwise the first thing an operator sees after every deploy is a full
        list of things they are told they have never looked at.
        """
        assert tracker.due_for_review() == []

    def test_due_items_carry_why_and_for_how_long(self, durable_tracker):
        sid = _with_cadence()
        from ai.awareness.reviewed import REVIEWABLE_SURFACES

        durable_tracker.mark_reviewed(sid, actor="ops", at=_at(REVIEWABLE_SURFACES[sid].cadence_s * 4))
        item = next(s for s in durable_tracker.due_for_review() if s.surface_id == sid)
        assert item.reason in ("never_reviewed", "stale")
        assert item.label.strip()
        assert item.age_s is None or item.age_s > 0


# ── it must not be able to act ────────────────────────────────────────────────


class TestTheTrackerCannotAct:
    def test_it_has_no_execute_surface(self, tracker):
        """Same rule as `Observation`: this states a fact, it does not do things.

        A tracker that could open a page, place an order or send a notification
        would be a scheduler with an opinion. It reports; `ai/notify/policy.py`
        decides whether to interrupt.
        """
        forbidden = {"execute", "send", "notify", "open", "act", "trigger", "run"}
        surface = {n for n in dir(tracker) if not n.startswith("_")}
        assert not (surface & forbidden), f"the tracker can act: {surface & forbidden}"


# ── serialisation ─────────────────────────────────────────────────────────────


class TestItSerialises:
    def test_state_survives_json(self, durable_tracker):
        import json

        sid = _with_cadence()
        durable_tracker.mark_reviewed(sid, actor="ops")
        payload = json.loads(json.dumps(durable_tracker.state(sid).as_dict()))
        assert set(payload) >= {"surface_id", "state", "age_s", "durable", "last_reviewed_at"}

    def test_the_report_names_the_store_durability_once(self, durable_tracker):
        """A consumer must be able to caveat the whole report, not each row."""
        report = durable_tracker.report()
        assert "durable" in report
        assert isinstance(report["surfaces"], list)


# ── helpers ───────────────────────────────────────────────────────────────────


def _ids():
    from ai.awareness.reviewed import REVIEWABLE_SURFACES

    return list(REVIEWABLE_SURFACES)


def _with_cadence() -> str:
    from ai.awareness.reviewed import REVIEWABLE_SURFACES

    for sid, s in REVIEWABLE_SURFACES.items():
        if s.cadence_s:
            return sid
    raise AssertionError("no surface declares a cadence")


def _without_cadence() -> str | None:
    from ai.awareness.reviewed import REVIEWABLE_SURFACES

    for sid, s in REVIEWABLE_SURFACES.items():
        if not s.cadence_s:
            return sid
    return None


# ── the Redis store, and the fallback that must not overclaim ─────────────────


class _FakeRedis:
    """Enough Redis to exercise the store, including its failure modes."""

    def __init__(self, *, raises: bool = False, garbage: bool = False) -> None:
        self.h: dict[str, str] = {}
        self._raises = raises
        self._garbage = garbage

    def hget(self, key, field):
        if self._raises:
            raise ConnectionError("redis down")
        if self._garbage:
            return b"not-a-timestamp"
        return self.h.get(field)

    def hset(self, key, field, value):
        if self._raises:
            raise ConnectionError("redis down")
        self.h[field] = value


class TestRedisReviewStore:
    def test_it_claims_durability(self):
        from ai.awareness.reviewed import RedisReviewStore

        assert RedisReviewStore(_FakeRedis()).durable is True

    def test_it_refuses_to_be_built_without_a_client(self):
        """A store with no client must not exist rather than silently do nothing.

        Returning a durable-looking store backed by None is how "never
        reviewed" becomes a lie.
        """
        from ai.awareness.reviewed import RedisReviewStore

        with pytest.raises(ValueError, match="needs a client"):
            RedisReviewStore(None)

    def test_a_round_trip_preserves_the_time_and_the_actor(self):
        from ai.awareness.reviewed import RedisReviewStore, ReviewTracker

        store = RedisReviewStore(_FakeRedis())
        t = ReviewTracker(store=store)
        when = _at(30)
        t.mark_reviewed("model_drift", actor="alice", at=when)

        state = t.state("model_drift")
        assert state.reviewed_by == "alice"
        assert state.last_reviewed_at is not None
        assert abs((state.last_reviewed_at - when).total_seconds()) < 1

    def test_a_read_failure_does_not_raise_into_the_caller(self):
        """It reads as unreviewed — which is why the failure logs at ERROR.

        A read failure making a reviewed surface look unreviewed is the exact
        false claim this module exists to avoid, so it cannot be silent.
        """
        from ai.awareness.reviewed import RedisReviewStore, ReviewTracker

        t = ReviewTracker(store=RedisReviewStore(_FakeRedis(raises=True)))
        assert t.state("model_drift").state == "never"

    def test_an_unreadable_row_is_treated_as_absent(self):
        from ai.awareness.reviewed import RedisReviewStore, ReviewTracker

        t = ReviewTracker(store=RedisReviewStore(_FakeRedis(garbage=True)))
        assert t.state("model_drift").state == "never"

    def test_a_write_failure_does_not_raise_into_the_caller(self):
        """Recording a review must never break the page the operator opened."""
        from ai.awareness.reviewed import RedisReviewStore, ReviewTracker

        t = ReviewTracker(store=RedisReviewStore(_FakeRedis(raises=True)))
        t.mark_reviewed("model_drift", actor="ops")  # must not raise
        assert t.state("model_drift").state == "never"


class TestTheProcessWideTracker:
    def test_it_is_one_tracker_per_process(self):
        """The API and the awareness loop must agree on what has been seen."""
        import ai.awareness.reviewed as mod

        mod._tracker = None
        try:
            assert mod.get_tracker() is mod.get_tracker()
        finally:
            mod._tracker = None

    def test_no_redis_falls_back_to_a_store_that_admits_it_is_volatile(self):
        """The fallback must never claim durability it does not have."""
        import ai.awareness.reviewed as mod

        mod._tracker = None
        try:
            with patch("cache.redis_client.get_sync_redis_client", return_value=None):
                tracker = mod.get_tracker()
            assert tracker.durable is False
            assert tracker.state("model_drift").state == "unknown"
            assert tracker.due_for_review() == []
        finally:
            mod._tracker = None

    def test_a_redis_import_failure_also_falls_back_safely(self):
        import ai.awareness.reviewed as mod

        mod._tracker = None
        try:
            with patch("cache.redis_client.get_sync_redis_client", side_effect=RuntimeError("no cache module")):
                tracker = mod.get_tracker()
            assert tracker.durable is False
        finally:
            mod._tracker = None

    def test_the_report_caveats_a_volatile_store_in_words(self):
        """A consumer must be able to show the caveat, not infer it from a bool."""
        from ai.awareness.reviewed import InMemoryReviewStore, ReviewTracker

        report = ReviewTracker(store=InMemoryReviewStore()).report()
        assert report["durable"] is False
        assert "did NOT survive" in report["note"]
