# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""The three contracts Phases 2 and 3 build against.

Phase 0.2 of the AI Hub specification. Three schemas, written before the systems
that use them, so the workspace engine and the agent bus are built against a
fixed shape rather than negotiating one as they go:

* `SurfaceRequest` (§8, §21, §23) — how the AI asks for a panel. Semantic type
  and data need, never a pixel position: §23 requires the layout engine be
  independent of the content engine, and a request that names coordinates has
  already made the layout decision.
* `AgentMessage` (§12) — the ten fields the specification lists by name.
* `ScenePanel` / `Scene` (§9) — what is on screen, so the AI can say "this
  chart" and mean something.

**The rule these tests enforce is that a wrong field fails at construction, not
at render.** A malformed panel request that survives until paint is a blank
rectangle an operator has to interpret; the same request rejected at the
boundary names what was wrong. Every invariant here is checked in
`__post_init__` for that reason.

These tests fail on the pre-fix tree — `ai.hub.contracts` does not exist there.
"""

from __future__ import annotations

import dataclasses

import pytest

pytestmark = pytest.mark.unit


# ── SurfaceRequest — §8, §21, §23 ─────────────────────────────────────────────


def test_a_surface_is_requested_by_meaning_not_by_pixels():
    """§23: the layout engine is independent of the content engine. A request
    carrying coordinates has already taken the layout decision away from it."""
    from ai.hub.contracts import SurfaceRequest

    fields = {f.name for f in dataclasses.fields(SurfaceRequest)}
    for forbidden in ("x", "y", "width", "height", "top", "left", "z_index"):
        assert forbidden not in fields, f"SurfaceRequest names {forbidden!r}; that is the layout engine's decision"


def test_a_surface_request_needs_a_kind_the_registry_knows():
    from ai.hub.contracts import SURFACE_KINDS, SurfaceRequest

    ok = SurfaceRequest(kind="chart", intent="gold price this session")
    assert ok.kind in SURFACE_KINDS

    with pytest.raises(ValueError, match="unknown surface kind"):
        SurfaceRequest(kind="teleporter", intent="whatever")


def test_every_surface_type_the_spec_lists_is_a_known_kind():
    """§8 enumerates them. A kind that is missing here cannot be requested at
    all, which is the silent omission §30 is written against."""
    from ai.hub.contracts import SURFACE_KINDS

    for kind in (
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
    ):
        assert kind in SURFACE_KINDS, f"§8 lists {kind!r} and it is not a surface kind"


def test_a_surface_request_needs_an_intent():
    """A panel with no stated purpose cannot be laid out by relevance, and
    cannot be explained by the AI afterwards."""
    from ai.hub.contracts import SurfaceRequest

    with pytest.raises(ValueError, match="intent"):
        SurfaceRequest(kind="chart", intent="   ")


def test_priority_defaults_to_the_quietest_tier():
    """§10: not everything is equally important. Defaulting to `primary` would
    make every surface shout, which is the same as none of them shouting."""
    from ai.hub.contracts import SurfaceRequest

    assert SurfaceRequest(kind="chart", intent="x").priority == "secondary"


def test_the_five_priority_tiers_are_exactly_what_the_spec_names():
    from ai.hub.contracts import PRIORITIES

    assert PRIORITIES == ("critical", "primary", "secondary", "background", "on_demand")


def test_an_unknown_priority_is_refused():
    from ai.hub.contracts import SurfaceRequest

    with pytest.raises(ValueError, match="priority"):
        SurfaceRequest(kind="chart", intent="x", priority="urgent-ish")


def test_a_surface_request_is_frozen():
    """It crosses a boundary. A caller mutating one after submission would change
    what the layout engine already decided against."""
    from ai.hub.contracts import SurfaceRequest

    req = SurfaceRequest(kind="chart", intent="x")
    with pytest.raises(dataclasses.FrozenInstanceError):
        req.kind = "table"  # type: ignore[misc]


# ── AgentMessage — §12 ────────────────────────────────────────────────────────


def test_the_envelope_carries_every_field_the_spec_lists():
    """§12 names ten. Missing one means agents cannot express something the
    specification requires them to express."""
    from ai.hub.contracts import AgentMessage

    fields = {f.name for f in dataclasses.fields(AgentMessage)}
    for required in (
        "task_id",
        "correlation_id",
        "sender",
        "recipient",
        "timestamp",
        "priority",
        "status",
        "confidence",
        "evidence",
        "recommended_action",
        "dependencies",
        "expires_at",
    ):
        assert required in fields, f"§12 names {required!r} and the envelope has no such field"


def test_confidence_is_a_probability_and_is_enforced():
    from ai.hub.contracts import AgentMessage

    with pytest.raises(ValueError, match="confidence"):
        AgentMessage(task_id="t", sender="risk", recipient="core", confidence=1.4)
    with pytest.raises(ValueError, match="confidence"):
        AgentMessage(task_id="t", sender="risk", recipient="core", confidence=-0.1)
    assert AgentMessage(task_id="t", sender="risk", recipient="core", confidence=0.5).confidence == 0.5


def test_a_message_needs_a_sender_and_a_recipient():
    """A message from nobody cannot be weighted by the sender's calibration
    (§13); one to nobody cannot be routed."""
    from ai.hub.contracts import AgentMessage

    with pytest.raises(ValueError, match="sender"):
        AgentMessage(task_id="t", sender="", recipient="core")
    with pytest.raises(ValueError, match="recipient"):
        AgentMessage(task_id="t", sender="risk", recipient="")


def test_correlation_id_defaults_to_the_task_id():
    """So a message is traceable even when nobody set one — an untraceable
    message is exactly what §12's protocol exists to prevent."""
    from ai.hub.contracts import AgentMessage

    assert AgentMessage(task_id="t-1", sender="a", recipient="b").correlation_id == "t-1"


def test_a_stale_message_can_say_so():
    """§12 asks for expiry/freshness metadata. Evidence that has aged out must be
    identifiable as such rather than weighted as current (§13)."""
    import time

    from ai.hub.contracts import AgentMessage

    fresh = AgentMessage(task_id="t", sender="a", recipient="b", expires_at=time.time() + 60)
    stale = AgentMessage(task_id="t", sender="a", recipient="b", expires_at=time.time() - 1)
    assert not fresh.is_expired()
    assert stale.is_expired()
    assert not AgentMessage(task_id="t", sender="a", recipient="b").is_expired(), (
        "a message with no expiry must not read as expired"
    )


def test_the_statuses_cover_a_whole_task_lifecycle():
    """§12 asks for lifecycle events. A vocabulary missing `cancelled` cannot
    express the cancellation §14 requires."""
    from ai.hub.contracts import MESSAGE_STATUSES

    for status in ("queued", "running", "partial", "succeeded", "failed", "cancelled", "timed_out"):
        assert status in MESSAGE_STATUSES


def test_a_disagreement_is_expressible_without_being_resolved():
    """§13: 'Do not force artificial consensus.' Two messages may hold opposite
    recommendations on one task, and the envelope must not object."""
    from ai.hub.contracts import AgentMessage

    task = "t-gold-regime"
    bull = AgentMessage(
        task_id=task, sender="trading", recipient="core", recommended_action="increase exposure", confidence=0.72
    )
    bear = AgentMessage(
        task_id=task, sender="risk", recipient="core", recommended_action="reduce exposure", confidence=0.65
    )
    assert bull.correlation_id == bear.correlation_id == task
    assert bull.recommended_action != bear.recommended_action


def test_evidence_is_a_list_of_references_not_prose():
    """§13 weights evidence. Free text cannot be weighted or followed."""
    from ai.hub.contracts import AgentMessage

    msg = AgentMessage(task_id="t", sender="a", recipient="b", evidence=("audit:call-9", "memory:note-4"))
    assert msg.evidence == ("audit:call-9", "memory:note-4")


def test_the_envelope_is_frozen_and_round_trips_as_a_dict():
    """It goes over a bus. A shape that cannot serialise cannot be published."""
    from ai.hub.contracts import AgentMessage

    msg = AgentMessage(task_id="t", sender="a", recipient="b", confidence=0.4)
    with pytest.raises(dataclasses.FrozenInstanceError):
        msg.sender = "c"  # type: ignore[misc]
    blob = msg.as_dict()
    assert blob["task_id"] == "t" and blob["confidence"] == 0.4
    assert AgentMessage.from_dict(blob) == msg


# ── Scene — §9 ────────────────────────────────────────────────────────────────


def test_a_panel_carries_the_five_things_the_spec_names():
    """§9: 'panel identity, position, size, z-order, content type and semantic
    meaning'. This is the layout engine's OUTPUT, so unlike a request it does
    carry geometry."""
    from ai.hub.contracts import ScenePanel

    fields = {f.name for f in dataclasses.fields(ScenePanel)}
    for required in ("id", "kind", "meaning", "x", "y", "width", "height", "z"):
        assert required in fields


def test_a_panel_needs_a_meaning_so_the_ai_can_refer_to_it():
    """The whole point of §9: 'this chart' has to resolve to something."""
    from ai.hub.contracts import ScenePanel

    with pytest.raises(ValueError, match="meaning"):
        ScenePanel(id="p1", kind="chart", meaning="", x=0, y=0, width=4, height=3)


def test_a_scene_finds_a_panel_by_what_it_means():
    from ai.hub.contracts import Scene, ScenePanel

    scene = Scene(
        panels=(
            ScenePanel(id="p1", kind="chart", meaning="gold price this session", x=0, y=0, width=6, height=4),
            ScenePanel(id="p2", kind="table", meaning="open positions", x=6, y=0, width=6, height=4),
        )
    )
    found = scene.resolve("the gold chart")
    assert found is not None and found.id == "p1"
    assert scene.resolve("something nobody is showing") is None


def test_a_scene_refuses_two_panels_with_the_same_id():
    """Otherwise 'focus p1' is ambiguous and the AI points at the wrong one."""
    from ai.hub.contracts import Scene, ScenePanel

    p = ScenePanel(id="p1", kind="chart", meaning="a", x=0, y=0, width=1, height=1)
    q = ScenePanel(id="p1", kind="table", meaning="b", x=1, y=0, width=1, height=1)
    with pytest.raises(ValueError, match="duplicate panel id"):
        Scene(panels=(p, q))


def test_a_scene_reports_what_is_on_top():
    """§9 layer navigation, and §10's 'what is being explained receives focus'."""
    from ai.hub.contracts import Scene, ScenePanel

    scene = Scene(
        panels=(
            ScenePanel(id="back", kind="chart", meaning="a", x=0, y=0, width=1, height=1, z=1),
            ScenePanel(id="front", kind="chart", meaning="b", x=0, y=0, width=1, height=1, z=9),
        )
    )
    assert scene.topmost().id == "front"


def test_an_empty_scene_is_valid_and_says_so():
    """The default state of the Hub is an empty canvas — §4's whole premise."""
    from ai.hub.contracts import Scene

    scene = Scene()
    assert scene.panels == ()
    assert scene.topmost() is None
    assert scene.resolve("anything") is None


def test_panels_cannot_have_zero_or_negative_size():
    """A zero-size panel is invisible and unclickable but occupies the scene
    model, so the AI would reference something the operator cannot see."""
    from ai.hub.contracts import ScenePanel

    with pytest.raises(ValueError, match="size"):
        ScenePanel(id="p", kind="chart", meaning="m", x=0, y=0, width=0, height=3)


# ── all three are registered capabilities ─────────────────────────────────────


def test_the_contracts_are_recorded_in_the_capability_registry():
    """Phase 0.1 made omission visible. These contracts must move from `planned`
    to at least `staged`, or the registry is now out of date with the code."""
    from ai.hub.capabilities import REGISTRY

    by_id = {c.id: c for c in REGISTRY}
    for cap_id in ("bus.message_envelope", "spatial.scene_model", "ui.schema_driven_panels"):
        assert by_id[cap_id].state in {"staged", "live"}, f"{cap_id} is still 'planned' but its contract now exists"
        assert by_id[cap_id].evidence, f"{cap_id} claims progress with no evidence"


def test_a_phrase_that_means_nothing_resolves_to_nothing():
    """Found while building the browser-side twin of this resolver.

    `resolve("nothing like this")` matched a panel whose meaning was "gold price
    THIS session" — one accidental common word, and the AI would have gone on to
    describe a panel the operator never referred to. Returning None is only
    useful if the score that beats it is real evidence.
    """
    from ai.hub.contracts import Scene, ScenePanel

    scene = Scene(
        panels=(
            ScenePanel(id="p1", kind="chart", meaning="gold price this session", x=0, y=0, width=6, height=4),
            ScenePanel(id="p2", kind="table", meaning="the open positions", x=6, y=0, width=6, height=4),
        )
    )
    assert scene.resolve("nothing like this") is None
    assert scene.resolve("show me the gold chart") is not None
    assert scene.resolve("what about that") is None


def test_stopwords_do_not_stop_a_real_reference():
    """The fix must not make resolution useless: a phrase that is mostly filler
    with one real noun still has to land."""
    from ai.hub.contracts import Scene, ScenePanel

    scene = Scene(panels=(ScenePanel(id="p1", kind="chart", meaning="gold price", x=0, y=0, width=6, height=4),))
    assert scene.resolve("can you show me that gold one please") == scene.panels[0]
