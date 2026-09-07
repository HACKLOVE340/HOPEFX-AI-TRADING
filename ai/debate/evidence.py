# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""§13: weight evidence by quality and freshness.

Two properties decide how much a claim should count, and neither is what the
claim says:

* **Where it came from.** A measured number from this platform's own books is
  not the same kind of thing as a model's recollection, and treating them alike
  is how a hallucinated figure ends up outranking a reconciliation.
* **When it was observed.** A correct reading of the order book from four hours
  ago is a wrong reading of the order book now.

## Stale is downweighted and said, never dropped

Dropping stale evidence silently produces a conclusion that looks better
supported than it is: the operator sees three strong points and never learns
that the fourth, which contradicted them, was merely old. So age reduces the
weight and sets `stale`, and the caller renders it.

## No timestamp is not "fresh"

Evidence with no `observed_at` is `unmeasured`, weighted as if it were at the
staleness boundary, and flagged. The alternative — treating an absent timestamp
as "now" — makes the least-verifiable evidence the heaviest, which is exactly
backwards.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import Enum

#: Past this, a reading is stale enough to say so.
STALE_AFTER_S = 900.0

#: Weight never decays below this. Old evidence still counts for something, and
#: a floor of zero would let age silently delete a contradiction.
MIN_FRESHNESS = 0.15


class EvidenceQuality(str, Enum):
    """Where a claim came from, ordered by how much it can be checked.

    `MEASURED` is a number this platform computed from its own records.
    `REPORTED` came from an external feed that could be wrong but is at least
    attributable. `INFERRED` is a model's own reasoning about other evidence.
    `RECALLED` is a model asserting something from memory with no source — the
    weakest thing that is still evidence rather than noise.
    """

    MEASURED = "measured"
    REPORTED = "reported"
    INFERRED = "inferred"
    RECALLED = "recalled"


#: Deliberately a wide spread rather than a gentle slope. A recalled claim
#: should not be able to outvote a measured one by arriving three times.
QUALITY_WEIGHT: dict[EvidenceQuality, float] = {
    EvidenceQuality.MEASURED: 1.0,
    EvidenceQuality.REPORTED: 0.6,
    EvidenceQuality.INFERRED: 0.3,
    EvidenceQuality.RECALLED: 0.12,
}


@dataclass(frozen=True)
class Evidence:
    """One checkable claim, and where and when it came from."""

    claim: str
    source: str
    quality: EvidenceQuality
    #: When the underlying observation was made. `None` means nobody recorded
    #: it, which is a fact about the evidence rather than a default of "now".
    observed_at: datetime | None = None

    def __post_init__(self) -> None:
        if not self.claim.strip():
            raise ValueError("evidence needs a claim a human can read")
        if not self.source.strip():
            raise ValueError("evidence with no source cannot be weighed; say who said it")
        if self.observed_at is not None and self.observed_at.tzinfo is None:
            # A naive datetime compared against an aware `now` raises at the
            # worst possible moment. Refusing here is cheaper than a TypeError
            # inside a risk decision.
            raise ValueError("observed_at must be timezone-aware")


@dataclass(frozen=True)
class Weighed:
    evidence: Evidence
    #: 0-1. Quality multiplied by freshness.
    weight: float
    stale: bool
    #: True when there was no timestamp at all — distinct from merely old.
    unmeasured_age: bool
    #: Seconds since observation, or None when unmeasured.
    age_s: float | None


def weigh(evidence: Evidence, *, now: datetime | None = None) -> Weighed:
    """How much this should count, and why it counts that much."""
    moment = now or datetime.now(UTC)
    quality = QUALITY_WEIGHT[evidence.quality]

    if evidence.observed_at is None:
        # Weighted as if it sat exactly on the staleness boundary: not deleted,
        # not trusted. Treating an absent timestamp as "now" would make the
        # least verifiable evidence the heaviest.
        return Weighed(
            evidence=evidence,
            weight=round(quality * _freshness(STALE_AFTER_S), 4),
            stale=True,
            unmeasured_age=True,
            age_s=None,
        )

    age = max(0.0, (moment - evidence.observed_at).total_seconds())
    return Weighed(
        evidence=evidence,
        weight=round(quality * _freshness(age), 4),
        stale=age > STALE_AFTER_S,
        unmeasured_age=False,
        age_s=age,
    )


def _freshness(age_s: float) -> float:
    """Exponential decay with a floor.

    Half-life at the staleness boundary, so a reading exactly at the limit is
    worth half of a fresh one rather than falling off a cliff — a step function
    here would make two readings a second apart differ by everything.
    """
    decayed = math.exp(-math.log(2) * (age_s / STALE_AFTER_S))
    return max(MIN_FRESHNESS, decayed)


__all__ = [
    "MIN_FRESHNESS",
    "QUALITY_WEIGHT",
    "STALE_AFTER_S",
    "Evidence",
    "EvidenceQuality",
    "Weighed",
    "weigh",
]
