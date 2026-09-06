# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""The three contracts the AI Hub's later phases build against.

Phase 0.2. Written before the systems that use them, so the workspace engine
(§8) and the agent bus (§12) are built against a fixed shape rather than
negotiating one as they go.

* `SurfaceRequest` — how the AI asks for a panel (§8, §21, §23).
* `AgentMessage`   — the ten fields §12 lists by name.
* `Scene` / `ScenePanel` — what is on screen, so "this chart" resolves (§9).

## The rule all three follow

**A wrong field fails at construction, not at render.** A malformed panel
request that survives until paint is a blank rectangle an operator has to
interpret; the same request refused at the boundary names what was wrong. Every
invariant is checked in `__post_init__`, and every one of these types is frozen
because each crosses a boundary — a caller mutating a request after submission
would change what the layout engine already decided against.

## Why a request carries no geometry

§23 requires the layout engine be independent of the content engine. A request
that names coordinates has already taken the layout decision away from it, which
is how a "dynamic" workspace quietly becomes a fixed grid with extra steps. So
`SurfaceRequest` states meaning, priority and a size *hint*; `ScenePanel` — the
layout engine's output — is the only place geometry appears.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Final, Literal

# ── Vocabularies ──────────────────────────────────────────────────────────────

#: Every surface type §8 enumerates. A kind absent from here cannot be requested
#: at all, which is precisely the silent omission §30 is written against.
SURFACE_KINDS: Final[tuple[str, ...]] = (
    "chart",
    "image",
    "video",
    "document",
    "table",
    "map",
    "terminal",
    "code",
    "camera",
    "news",
    "research",
    "simulation",
    # Beyond §8's list, and named rather than improvised later:
    "heatmap",
    "network",
    "timeline",
    "distribution",
    "agent_activity",
    "text",
)

#: §8's priority tiers, in order of loudness.
PRIORITIES: Final[tuple[str, ...]] = ("critical", "primary", "secondary", "background", "on_demand")

#: §12 lifecycle. `cancelled` and `timed_out` are distinct from `failed` because
#: §14 requires cancellation and deadlines, and an operator's next move differs
#: for each: retry a failure, raise the ceiling for a timeout, nothing for a cancel.
MESSAGE_STATUSES: Final[tuple[str, ...]] = (
    "queued",
    "running",
    "partial",
    "succeeded",
    "failed",
    "cancelled",
    "timed_out",
)

#: Words shorter than this are dropped when resolving "the gold chart" — "the",
#: "my", "on" match everything and would make every panel score equally.
_MIN_MATCH_WORD = 3

#: Words long enough to survive the length filter and still meaningless here.
#:
#: Found by building the browser-side twin of this resolver:
#: `resolve("nothing like this")` matched a panel meaning "gold price THIS
#: session". One accidental common word, and the AI would have gone on to
#: describe a panel the operator never referred to. Returning None is only
#: useful if the score that beats it is real evidence.
_STOPWORDS = frozenset(
    {
        "the",
        "this",
        "that",
        "these",
        "those",
        "and",
        "for",
        "with",
        "about",
        "show",
        "give",
        "need",
        "want",
        "please",
        "from",
        "into",
        "onto",
        "what",
        "whats",
        "have",
        "has",
        "are",
        "was",
        "were",
        "can",
        "you",
        "your",
        "his",
        "her",
        "its",
        "our",
        "their",
        "not",
        "but",
        "all",
        "any",
        "now",
        "then",
        "one",
        "some",
        "here",
        "there",
        "them",
        "they",
        "who",
        "how",
        "why",
    }
)

Priority = Literal["critical", "primary", "secondary", "background", "on_demand"]
Status = Literal["queued", "running", "partial", "succeeded", "failed", "cancelled", "timed_out"]


# ── §8, §21, §23 — asking for a surface ───────────────────────────────────────


@dataclass(frozen=True)
class SurfaceRequest:
    """What the AI asks for when it wants something on screen.

    Meaning and need, never position. `size_hint` is advisory — "this wants to be
    wide" — and the layout engine may ignore it; that is the difference between a
    hint and a coordinate.
    """

    kind: str
    #: Why this surface should exist, in the AI's own words. Not a title: the
    #: layout engine ranks by relevance and the AI explains by intent, so a
    #: surface with no stated purpose can be neither placed nor described.
    intent: str
    priority: Priority = "secondary"
    #: What the surface needs in order to render — a symbol, a time range, a
    #: document id. Opaque here on purpose: the contract should not have to
    #: change every time a new surface type needs a new parameter.
    data: dict[str, Any] = field(default_factory=dict)
    #: "narrow" | "wide" | "tall" | "full". Advisory.
    size_hint: str = "wide"
    #: Set when this surface elaborates another — §9 layer navigation.
    parent_id: str = ""
    #: Stable across re-requests, so asking twice updates rather than duplicates.
    key: str = ""

    def __post_init__(self) -> None:
        if self.kind not in SURFACE_KINDS:
            raise ValueError(f"unknown surface kind {self.kind!r}; known kinds are {', '.join(SURFACE_KINDS)}")
        if not self.intent.strip():
            raise ValueError("a surface request needs an intent; a panel with no purpose cannot be placed or explained")
        if self.priority not in PRIORITIES:
            raise ValueError(f"unknown priority {self.priority!r}; expected one of {', '.join(PRIORITIES)}")


# ── §12 — how agents talk to each other ───────────────────────────────────────


@dataclass(frozen=True)
class AgentMessage:
    """One structured message between agents. §12's ten fields, by name.

    Deliberately says nothing about transport. The bus that carries these does
    not exist yet; when it does, it should not be able to change their shape.
    """

    task_id: str
    sender: str
    recipient: str
    #: Defaults to `task_id` so a message is always traceable, even unset — an
    #: untraceable message is what §12's protocol exists to prevent.
    correlation_id: str = ""
    timestamp: float = field(default_factory=time.time)
    priority: Priority = "secondary"
    status: Status = "queued"
    #: 0.0-1.0. §13 weights claims by confidence, so a value outside the range
    #: would silently distort every synthesis that reads it.
    confidence: float = 0.0
    #: References, not prose — `audit:call-9`, `memory:note-4`. §13 weights and
    #: follows evidence; free text can be neither weighted nor followed.
    evidence: tuple[str, ...] = ()
    recommended_action: str = ""
    dependencies: tuple[str, ...] = ()
    #: Wall-clock. None means it does not go stale.
    expires_at: float | None = None
    message_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    body: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.task_id.strip():
            raise ValueError("an agent message needs a task_id")
        if not self.sender.strip():
            raise ValueError("an agent message needs a sender; an anonymous claim cannot be weighted by calibration")
        if not self.recipient.strip():
            raise ValueError("an agent message needs a recipient; it cannot be routed otherwise")
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError(f"confidence must be between 0 and 1, got {self.confidence}")
        if self.status not in MESSAGE_STATUSES:
            raise ValueError(f"unknown status {self.status!r}; expected one of {', '.join(MESSAGE_STATUSES)}")
        if self.priority not in PRIORITIES:
            raise ValueError(f"unknown priority {self.priority!r}")
        if not self.correlation_id:
            object.__setattr__(self, "correlation_id", self.task_id)

    def is_expired(self, now: float | None = None) -> bool:
        """Whether this message's evidence has aged out.

        A message with no expiry never reads as expired — absence of a deadline
        is not a deadline that has passed.
        """
        if self.expires_at is None:
            return False
        return (now if now is not None else time.time()) > self.expires_at

    def as_dict(self) -> dict[str, Any]:
        """A JSON-safe shape. It goes over a bus; it has to serialise."""
        return {
            "message_id": self.message_id,
            "task_id": self.task_id,
            "correlation_id": self.correlation_id,
            "sender": self.sender,
            "recipient": self.recipient,
            "timestamp": self.timestamp,
            "priority": self.priority,
            "status": self.status,
            "confidence": self.confidence,
            "evidence": list(self.evidence),
            "recommended_action": self.recommended_action,
            "dependencies": list(self.dependencies),
            "expires_at": self.expires_at,
            "body": dict(self.body),
        }

    @classmethod
    def from_dict(cls, blob: dict[str, Any]) -> AgentMessage:
        return cls(
            task_id=str(blob["task_id"]),
            sender=str(blob["sender"]),
            recipient=str(blob["recipient"]),
            correlation_id=str(blob.get("correlation_id", "") or ""),
            timestamp=float(blob.get("timestamp", time.time())),
            priority=blob.get("priority", "secondary"),
            status=blob.get("status", "queued"),
            confidence=float(blob.get("confidence", 0.0)),
            evidence=tuple(blob.get("evidence", ()) or ()),
            recommended_action=str(blob.get("recommended_action", "") or ""),
            dependencies=tuple(blob.get("dependencies", ()) or ()),
            expires_at=blob.get("expires_at"),
            message_id=str(blob.get("message_id", "") or uuid.uuid4()),
            body=dict(blob.get("body", {}) or {}),
        )


# ── §9 — what is on screen ────────────────────────────────────────────────────


@dataclass(frozen=True)
class ScenePanel:
    """One placed surface. The layout engine's output, so this does carry geometry.

    Coordinates are in abstract grid units rather than pixels: §7 asks for a
    future abstraction over 3D, AR and holographic output, and a scene model
    measured in CSS pixels cannot be handed to a renderer that has none.
    """

    id: str
    kind: str
    #: What this panel MEANS, in words the AI would use out loud. This is what
    #: makes §9 work: "focus the gold chart" resolves against these.
    meaning: str
    x: float
    y: float
    width: float
    height: float
    z: int = 0
    priority: Priority = "secondary"
    pinned: bool = False

    def __post_init__(self) -> None:
        if not self.id.strip():
            raise ValueError("a panel needs an id")
        if not self.meaning.strip():
            raise ValueError("a panel needs a meaning; without one the AI cannot refer to it")
        if self.width <= 0 or self.height <= 0:
            raise ValueError(
                f"a panel needs a positive size, got {self.width}x{self.height}; "
                "a zero-size panel is invisible but still occupies the scene model"
            )


@dataclass(frozen=True)
class Scene:
    """Everything currently on screen. The AI's spatial awareness (§9).

    Empty is the normal resting state, not an error — §4's whole premise is that
    the default view is a clean canvas.
    """

    panels: tuple[ScenePanel, ...] = ()

    def __post_init__(self) -> None:
        ids = [p.id for p in self.panels]
        dupes = sorted({i for i in ids if ids.count(i) > 1})
        if dupes:
            raise ValueError(f"duplicate panel id in scene: {', '.join(dupes)}")

    def resolve(self, phrase: str) -> ScenePanel | None:
        """Find the panel a phrase refers to, or None.

        Word overlap against `meaning` and `kind`. Deliberately simple: this is
        the contract, and the real resolver — which will have the conversation
        for context — replaces the body without changing the signature.

        Returns None rather than guessing. Pointing at the wrong panel while
        confidently describing another is worse than saying "which one?".
        """
        wanted = {w for w in phrase.lower().split() if len(w) >= _MIN_MATCH_WORD and w not in _STOPWORDS}
        if not wanted:
            return None
        best: tuple[int, ScenePanel] | None = None
        for panel in self.panels:
            haystack = f"{panel.meaning} {panel.kind}".lower().split()
            score = sum(1 for w in wanted if any(w in h or h in w for h in haystack))
            if score and (best is None or score > best[0]):
                best = (score, panel)
        return best[1] if best else None

    def topmost(self) -> ScenePanel | None:
        """The panel in front, or None on an empty canvas."""
        return max(self.panels, key=lambda p: p.z, default=None)

    def by_priority(self, priority: Priority) -> tuple[ScenePanel, ...]:
        return tuple(p for p in self.panels if p.priority == priority)


__all__ = [
    "MESSAGE_STATUSES",
    "PRIORITIES",
    "SURFACE_KINDS",
    "AgentMessage",
    "Priority",
    "Scene",
    "ScenePanel",
    "Status",
    "SurfaceRequest",
]
