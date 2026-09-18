# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""What the operator has actually looked at, and when. §19's missing half.

Owner requirement, 2026-09-10: everything on the AI Core page should run in the
background and surface itself — *"pop it up or ask if operator want to check, or
if it been a while you have check it, or operator haven't request for it at
all."*

Three of the four pieces already existed and are good:

* `ai/awareness/watchers.py` — departments observe on their own and raise
  proposals; structurally unable to act.
* `ai/notify/policy.py` — when the AI may interrupt, with a floor: a CRITICAL
  notification is never suppressed by any combination of settings.
* `frontend/src/hub/attention.ts` — whether anybody is looking, no camera
  needed, and "unknown is not away".

The fourth did not exist at all. A grep for `last_reviewed` / `unseen` /
`acknowledged_at` across `ai/`, `api/` and `frontend/src` returned one hit, and
it was a comment. Nothing recorded what an operator had looked at, so *"it has
been a while since you checked this"* was a sentence the platform could not say.

## The honesty problem this design turns on

"You have never reviewed this" is a claim about a person, and it is only as good
as the memory behind it. A store that lost its contents on restart would report
every surface as never-reviewed, and the AI would greet an operator who reads
the drift report daily by telling them they have never opened it. Say that once
and they learn to ignore the whole mechanism.

So the store declares whether it survives a restart, and the state carries it:

    durable store, no record   -> "never"    (a fact about the operator)
    volatile store, no record  -> "unknown"  (a fact about the store)

Rule 2 — an unmeasured value is absent, never best-case — pointed at the person
using the platform rather than at a price. And `due_for_review()` returns
nothing at all from a volatile store, so the first thing an operator sees after
a deploy is not a list of things they are wrongly told they have neglected.

## Cadence is declared, never assumed

"Overdue" needs an expected cadence. A surface that never declared one cannot be
overdue and is not fresh either — it is `no_cadence`. Inventing a default would
manufacture urgency about something nobody said was urgent, which is the same
defect as inventing a data-quality score.

## It reports; it does not act

Same rule as `Observation` in `watchers.py`. This module has no notifier, no
route opener and no scheduler: a tracker that could act would be a scheduler
with an opinion about your attention. It states a fact, and
`ai/notify/policy.py` — which already knows about quiet hours, sleep mode and
the critical floor — decides whether that fact is worth interrupting anyone for.
A test asserts the surface stays free of `execute`/`send`/`notify`/`open`.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal, Protocol

logger = logging.getLogger(__name__)

__all__ = [
    "REVIEWABLE_SURFACES",
    "DueItem",
    "InMemoryReviewStore",
    "ReviewState",
    "ReviewTracker",
    "ReviewableSurface",
    "UnknownSurface",
    "get_tracker",
]

ReviewStateName = Literal["never", "unknown", "fresh", "stale", "no_cadence"]

_HOUR = 3600
_DAY = 24 * _HOUR


class UnknownSurface(KeyError):
    """Asked about something nobody declared — a typo, not a review."""


@dataclass(frozen=True)
class ReviewableSurface:
    """Something an operator can look at, and how often they are expected to.

    `cadence_s` of 0 means *no stated cadence*: this surface can be reviewed but
    is never overdue. That is a deliberate value, not a missing one.
    """

    id: str
    label: str
    cadence_s: int = 0
    why: str = ""


#: The surfaces the AI may say something about. Declared rather than discovered:
#: a registry that guessed from routes would raise "you have not looked at
#: /api/health lately", which is noise, and noise is how a notification channel
#: dies.
REVIEWABLE_SURFACES: dict[str, ReviewableSurface] = {
    s.id: s
    for s in (
        ReviewableSurface(
            "model_drift",
            "Model drift report",
            cadence_s=_DAY,
            why="Drift decides whether today's predictions can be trusted.",
        ),
        ReviewableSurface(
            "calibration",
            "Model calibration",
            cadence_s=7 * _DAY,
            why="Whether a 70% forecast happens 70% of the time; feeds the quality gate.",
        ),
        ReviewableSurface(
            "risk_limits",
            "Risk limits and exposure",
            cadence_s=_DAY,
            why="The limits that decide what the platform is allowed to lose.",
        ),
        ReviewableSurface(
            "feed_status",
            "Price feed health",
            cadence_s=4 * _HOUR,
            why="A degraded feed is the input to every decision below it.",
        ),
        ReviewableSurface(
            "improve_queue",
            "AI code proposals awaiting approval",
            cadence_s=2 * _DAY,
            why="Proposals sit until two approvers act; nothing merges on its own.",
        ),
        ReviewableSurface(
            "audit_log",
            "Superadmin audit trail",
            cadence_s=7 * _DAY,
            why="The hash-chained record of who did what.",
        ),
        ReviewableSurface(
            "decision_ledger",
            "Decision ledger and refusals",
            cadence_s=_DAY,
            why="What the platform decided today, and what it refused.",
        ),
        ReviewableSurface(
            "open_positions",
            "Open positions",
            why="Reviewed continuously in the normal course of trading; no cadence is stated "
            "because being 'overdue' on it would mean the operator had stopped trading.",
        ),
    )
}


@dataclass(frozen=True)
class ReviewState:
    surface_id: str
    label: str
    state: ReviewStateName
    last_reviewed_at: datetime | None
    age_s: float | None
    reviewed_by: str | None
    cadence_s: int
    durable: bool

    def as_dict(self) -> dict[str, Any]:
        return {
            "surface_id": self.surface_id,
            "label": self.label,
            "state": self.state,
            "last_reviewed_at": self.last_reviewed_at.isoformat() if self.last_reviewed_at else None,
            "age_s": self.age_s,
            "reviewed_by": self.reviewed_by,
            "cadence_s": self.cadence_s,
            "durable": self.durable,
        }


@dataclass(frozen=True)
class DueItem:
    """A surface worth mentioning, with why and for how long."""

    surface_id: str
    label: str
    reason: Literal["never_reviewed", "stale"]
    age_s: float | None
    cadence_s: int
    why: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "surface_id": self.surface_id,
            "label": self.label,
            "reason": self.reason,
            "age_s": self.age_s,
            "cadence_s": self.cadence_s,
            "why": self.why,
        }


class ReviewStore(Protocol):
    """Where review times live, and whether that place survives a restart."""

    durable: bool

    def get(self, surface_id: str) -> tuple[datetime, str] | None: ...

    def put(self, surface_id: str, at: datetime, actor: str) -> None: ...


class InMemoryReviewStore:
    """Process-local. `durable=False` unless a caller insists otherwise.

    The flag is a constructor argument rather than a constant so tests can
    exercise both readings without a fake Redis — the two readings are the point
    of the module, and they must both be reachable.
    """

    def __init__(self, durable: bool = False) -> None:
        self.durable = durable
        self._rows: dict[str, tuple[datetime, str]] = {}

    def get(self, surface_id: str) -> tuple[datetime, str] | None:
        return self._rows.get(surface_id)

    def put(self, surface_id: str, at: datetime, actor: str) -> None:
        self._rows[surface_id] = (at, actor)


class RedisReviewStore:
    """Redis-backed, and therefore durable across a restart.

    Falls back to nothing: a caller that wants a store and cannot have this one
    should use `InMemoryReviewStore()` explicitly and inherit `durable=False`,
    rather than getting a volatile store that claims to be durable.
    """

    _KEY = "hopefx:review:last"

    def __init__(self, client: Any) -> None:
        if client is None:
            raise ValueError("RedisReviewStore needs a client; use InMemoryReviewStore() otherwise")
        self._r = client
        self.durable = True

    def get(self, surface_id: str) -> tuple[datetime, str] | None:
        try:
            raw = self._r.hget(self._KEY, surface_id)
        except Exception as exc:
            # ERROR: a read failure here makes a reviewed surface look
            # unreviewed, which is exactly the false claim this module exists
            # to avoid making.
            logger.error("review store read failed for %s: %s", surface_id, exc)
            return None
        if not raw:
            return None
        try:
            text = raw.decode() if isinstance(raw, bytes) else str(raw)
            when, _, actor = text.partition("|")
            return datetime.fromisoformat(when), actor
        except (ValueError, AttributeError) as exc:
            logger.error("review store row for %s is unreadable: %s", surface_id, exc)
            return None

    def put(self, surface_id: str, at: datetime, actor: str) -> None:
        try:
            self._r.hset(self._KEY, surface_id, f"{at.isoformat()}|{actor}")
        except Exception as exc:
            logger.error("review store write failed for %s (review NOT recorded): %s", surface_id, exc)


class ReviewTracker:
    """States what has been looked at. Decides nothing and sends nothing."""

    def __init__(self, store: ReviewStore | None = None) -> None:
        self._store: ReviewStore = store or InMemoryReviewStore()

    @property
    def durable(self) -> bool:
        return bool(getattr(self._store, "durable", False))

    def mark_reviewed(self, surface_id: str, *, actor: str, at: datetime | None = None) -> None:
        """Record that `actor` looked at `surface_id`."""
        if surface_id not in REVIEWABLE_SURFACES:
            raise UnknownSurface(
                f"{surface_id!r} is not a declared reviewable surface; known: {sorted(REVIEWABLE_SURFACES)}"
            )
        self._store.put(surface_id, at or datetime.now(UTC), actor)

    def state(self, surface_id: str) -> ReviewState:
        if surface_id not in REVIEWABLE_SURFACES:
            raise UnknownSurface(f"{surface_id!r} is not a declared reviewable surface")
        surface = REVIEWABLE_SURFACES[surface_id]
        row = self._store.get(surface_id)
        durable = self.durable

        if row is None:
            # The distinction the module exists for.
            name: ReviewStateName = "never" if durable else "unknown"
            return ReviewState(
                surface_id=surface_id,
                label=surface.label,
                state=name,
                last_reviewed_at=None,
                age_s=None,
                reviewed_by=None,
                cadence_s=surface.cadence_s,
                durable=durable,
            )

        when, actor = row
        age = (datetime.now(UTC) - when).total_seconds()
        if not surface.cadence_s:
            name = "no_cadence"
        elif age > surface.cadence_s:
            name = "stale"
        else:
            name = "fresh"

        return ReviewState(
            surface_id=surface_id,
            label=surface.label,
            state=name,
            last_reviewed_at=when,
            age_s=age,
            reviewed_by=actor,
            cadence_s=surface.cadence_s,
            durable=durable,
        )

    def due_for_review(self) -> list[DueItem]:
        """Surfaces worth mentioning. Empty from a store that cannot know.

        A volatile store returns nothing rather than everything: after a deploy
        it holds no rows, and raising every surface as neglected would be the
        platform asserting something false about the operator on every restart.
        """
        if not self.durable:
            return []

        due: list[DueItem] = []
        for surface_id in REVIEWABLE_SURFACES:
            st = self.state(surface_id)
            if st.state == "never":
                due.append(
                    DueItem(
                        surface_id=surface_id,
                        label=st.label,
                        reason="never_reviewed",
                        age_s=None,
                        cadence_s=st.cadence_s,
                        why=REVIEWABLE_SURFACES[surface_id].why,
                    )
                )
            elif st.state == "stale":
                due.append(
                    DueItem(
                        surface_id=surface_id,
                        label=st.label,
                        reason="stale",
                        age_s=st.age_s,
                        cadence_s=st.cadence_s,
                        why=REVIEWABLE_SURFACES[surface_id].why,
                    )
                )
        # Longest-neglected first; never-reviewed sorts ahead of any age.
        due.sort(key=lambda d: -1e18 if d.age_s is None else -d.age_s)
        return due

    def report(self) -> dict[str, Any]:
        """Everything, with the durability caveat stated once at the top."""
        return {
            "durable": self.durable,
            "note": (
                "Review history survives a restart."
                if self.durable
                else "Review history is process-local and did NOT survive the last restart; "
                "'unknown' means the store cannot tell, not that nobody looked."
            ),
            "surfaces": [self.state(sid).as_dict() for sid in REVIEWABLE_SURFACES],
            "due": [d.as_dict() for d in self.due_for_review()],
        }


_tracker: ReviewTracker | None = None


def get_tracker() -> ReviewTracker:
    """The process-wide tracker, Redis-backed when a client is available.

    Falls back to an explicitly non-durable in-memory store rather than to a
    volatile store that claims durability — the fallback must not be able to
    tell the operator they have never looked at something it merely forgot.
    """
    # One tracker per process so the API and the awareness loop agree.
    global _tracker
    if _tracker is not None:
        return _tracker

    store: ReviewStore
    try:
        from cache.redis_client import get_sync_redis_client

        client = get_sync_redis_client()
        store = RedisReviewStore(client) if client is not None else InMemoryReviewStore()
        if client is None:
            logger.warning(
                "review tracking: no Redis client — review history is process-local and "
                "will report 'unknown' rather than 'never' after a restart"
            )
    except Exception as exc:
        logger.warning("review tracking: Redis unavailable (%s); using a non-durable store", exc)
        store = InMemoryReviewStore()

    _tracker = ReviewTracker(store=store)
    return _tracker
