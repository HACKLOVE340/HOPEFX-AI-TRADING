# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""One metric, and whether it was actually measured. §22.

## Why this type exists at all

`infrastructure/metrics.py:update_system_metrics` returns early when psutil is
unavailable, leaving the gauge unset — and an unset `Gauge` reads back its
default. Measured, before any of this was written:

    >>> m.PSUTIL_AVAILABLE = False
    >>> reg.update_system_metrics()
    >>> reg.get_collector("system_cpu_percent").get_value()
    0.0

A CPU gauge reading 0% because the probe never ran is worse than no gauge at
all. No gauge says "I do not know". 0% says "the machine is idle" —
confidently, to somebody deciding whether to start more work. The same
registry's `get_all_metrics()` reports `None` for that gauge, so its two
readers disagree about whether the machine is idle or unknown.

## Zero has to stay expressible

The fix is not "return None everywhere": a CPU genuinely at 0.0% must still be
reportable as idle. So `value=0.0` is a measurement and `value=None` is not,
and the two are different states of the same type rather than the same number.

## Absent without a reason is refused

An "I do not know" that cannot say why is a different way of telling somebody
nothing. `None` requires a reason, at construction, and a value forbids one —
a number and an excuse are two answers to one question.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class Reading:
    """A measurement, or a stated absence. Never a stand-in number."""

    name: str
    value: float | None
    unit: str = ""
    #: Required when `value` is None, and forbidden when it is not.
    reason: str = ""
    at: float = field(default_factory=time.time)

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("a reading needs a name")
        if self.value is None and not self.reason.strip():
            raise ValueError(
                f"{self.name}: an absent reading must say why it is absent; "
                "'I do not know' that cannot say why is a different way of saying nothing"
            )
        if self.value is not None and self.reason.strip():
            raise ValueError(f"{self.name}: a value and a reason are two answers to one question")

    @property
    def measured(self) -> bool:
        return self.value is not None

    def as_dict(self) -> dict[str, Any]:
        """JSON-safe. An absent reading serialises as null, never as 0."""
        return {
            "name": self.name,
            "value": self.value,
            "unit": self.unit,
            "reason": self.reason,
            "measured": self.measured,
            "at": self.at,
        }


def measured(name: str, value: float, *, unit: str = "") -> Reading:
    return Reading(name=name, value=float(value), unit=unit)


def absent(name: str, reason: str, *, unit: str = "") -> Reading:
    return Reading(name=name, value=None, unit=unit, reason=reason)


__all__ = ["Reading", "absent", "measured"]
