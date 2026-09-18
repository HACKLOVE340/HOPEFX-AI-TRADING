# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""§20: news, macro, technical and microstructure correlation.

Four kinds of signal move gold, and an operator asking "why did it just do that"
is asking which of them lines up with the move. This assembles that answer and —
the part that matters — states its own limits inside the answer rather than in a
comment nobody reads.

## Co-occurrence is not causation, and the output says so

Every correlation engine ever built has been read as a causal claim by somebody
under time pressure. Three signals aligning with a move is a fact about
timestamps. `Correlation.caveat` is a required part of the rendered output, not
an optional footnote, and `as_evidence()` produces `REPORTED`/`INFERRED`
evidence rather than `MEASURED` — because what was measured is the price and the
signal, not the link between them.

## A domain with no signal is a blind spot, stated

"No news moved it" and "the news feed did not answer" are different facts that
render identically as an empty list. `domains_missing` names every domain that
produced nothing, so an analysis built on three of the four says which one it is
blind in.

## A signal outside the window is excluded and counted

Silently dropping it makes the surviving evidence look denser than it is. The
count is reported.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Literal

from ai.debate.evidence import Evidence, EvidenceQuality

Domain = Literal["news", "macro", "technical", "microstructure"]

DOMAINS: tuple[Domain, ...] = ("news", "macro", "technical", "microstructure")

#: How each domain's signals are sourced, and therefore how far they can be
#: checked. Technical and microstructure are computed here from this platform's
#: own tick and book data; news and macro arrive from outside it.
DOMAIN_QUALITY: dict[Domain, EvidenceQuality] = {
    "news": EvidenceQuality.REPORTED,
    "macro": EvidenceQuality.REPORTED,
    "technical": EvidenceQuality.MEASURED,
    "microstructure": EvidenceQuality.MEASURED,
}

#: Default window either side of the move. Fifteen minutes because that is the
#: horizon over which a headline still plausibly relates to a gold tick; longer
#: and everything correlates with everything.
DEFAULT_WINDOW_S = 900.0


@dataclass(frozen=True)
class Signal:
    """One thing that happened, in one domain, at one time."""

    domain: Domain
    label: str
    at: datetime
    #: +1 up, -1 down, 0 neutral, None when the direction is not known. `None`
    #: is not `0`: "this does not push either way" and "nobody worked out which
    #: way this pushes" are different, and merging them fabricates a neutral.
    direction: int | None = None
    source: str = ""

    def __post_init__(self) -> None:
        if self.domain not in DOMAINS:
            raise ValueError(f"domain {self.domain!r} is not one of {DOMAINS}")
        if not self.label.strip():
            raise ValueError("a signal needs a label a human can read")
        if self.at.tzinfo is None:
            raise ValueError("a signal's timestamp must be timezone-aware")
        if self.direction not in (None, -1, 0, 1):
            raise ValueError("direction must be -1, 0, 1, or None for unknown")


@dataclass(frozen=True)
class PriceMove:
    symbol: str
    at: datetime
    #: Signed. The sign is what signals are compared against.
    change: float

    def __post_init__(self) -> None:
        if self.at.tzinfo is None:
            raise ValueError("a price move's timestamp must be timezone-aware")

    @property
    def direction(self) -> int:
        return 1 if self.change > 0 else -1 if self.change < 0 else 0


@dataclass
class Correlation:
    symbol: str
    move: PriceMove
    aligned: list[Signal] = field(default_factory=list)
    opposing: list[Signal] = field(default_factory=list)
    #: In the window, but pushing neither way or with an unknown direction.
    unaligned: list[Signal] = field(default_factory=list)
    #: Outside the window. Counted, not silently dropped.
    out_of_window: int = 0
    #: Domains that produced nothing at all. A blind spot, not an absence.
    domains_missing: list[Domain] = field(default_factory=list)

    caveat: str = (
        "These signals share a window with the move. That is a fact about "
        "timestamps, not a cause: nothing here establishes that any of them "
        "moved the price."
    )

    @property
    def domains_seen(self) -> list[Domain]:
        return sorted({s.domain for s in [*self.aligned, *self.opposing, *self.unaligned]})

    def as_evidence(self) -> list[Evidence]:
        """The aligned signals as evidence, at a quality that reflects the link.

        Never `MEASURED`. What was measured is the price and the signal; the
        connection between them is this module's inference, and evidence quality
        has to describe the weakest link rather than the strongest.
        """
        out: list[Evidence] = []
        for signal in self.aligned:
            declared = DOMAIN_QUALITY[signal.domain]
            quality = EvidenceQuality.INFERRED if declared is EvidenceQuality.MEASURED else EvidenceQuality.RECALLED
            out.append(
                Evidence(
                    claim=f"{signal.label} ({signal.domain}) moved with the price",
                    source=signal.source or f"correlation:{signal.domain}",
                    quality=quality,
                    observed_at=signal.at,
                )
            )
        return out

    def as_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "move": {"at": self.move.at.isoformat(), "change": self.move.change, "direction": self.move.direction},
            "aligned": [_signal_dict(s) for s in self.aligned],
            "opposing": [_signal_dict(s) for s in self.opposing],
            "unaligned": [_signal_dict(s) for s in self.unaligned],
            "out_of_window": self.out_of_window,
            "domains_seen": self.domains_seen,
            "domains_missing": list(self.domains_missing),
            "caveat": self.caveat,
        }

    def as_prose(self) -> str:
        lines = [
            f"{self.symbol} moved {self.move.change:+.2f} at {self.move.at.isoformat()}.",
        ]
        if self.aligned:
            lines.append("Moving the same way: " + "; ".join(f"{s.label} [{s.domain}]" for s in self.aligned))
        if self.opposing:
            lines.append("Pointing the other way: " + "; ".join(f"{s.label} [{s.domain}]" for s in self.opposing))
        if self.unaligned:
            lines.append(
                "In the window, direction not established: "
                + "; ".join(f"{s.label} [{s.domain}]" for s in self.unaligned)
            )
        if self.out_of_window:
            lines.append(f"{self.out_of_window} signal(s) fell outside the window and were not used.")
        if self.domains_missing:
            # Stated, because "no news moved it" and "the news feed did not
            # answer" render identically as an empty list.
            lines.append(
                "No signal at all from: " + ", ".join(self.domains_missing) + " — a blind spot here, not an all-clear."
            )
        lines.extend(["", self.caveat])
        return "\n".join(lines)


def _signal_dict(s: Signal) -> dict[str, Any]:
    return {"domain": s.domain, "label": s.label, "at": s.at.isoformat(), "direction": s.direction, "source": s.source}


def correlate(
    *,
    move: PriceMove,
    signals: list[Signal],
    window_s: float = DEFAULT_WINDOW_S,
    now: datetime | None = None,
) -> Correlation:
    """Sort signals by whether they share a window with the move and point the same way."""
    _ = now or datetime.now(UTC)  # accepted for symmetry with the rest of the package
    result = Correlation(symbol=move.symbol, move=move)

    for signal in signals:
        if abs((signal.at - move.at).total_seconds()) > window_s:
            result.out_of_window += 1
            continue
        if signal.direction is None or signal.direction == 0 or move.direction == 0:
            # Unknown and neutral are both "does not tell us which way", but
            # they are kept out of `aligned` rather than counted for either side.
            result.unaligned.append(signal)
        elif signal.direction == move.direction:
            result.aligned.append(signal)
        else:
            result.opposing.append(signal)

    seen = set(result.domains_seen)
    result.domains_missing = [d for d in DOMAINS if d not in seen]
    return result


__all__ = [
    "DEFAULT_WINDOW_S",
    "DOMAINS",
    "DOMAIN_QUALITY",
    "Correlation",
    "Domain",
    "PriceMove",
    "Signal",
    "correlate",
]
