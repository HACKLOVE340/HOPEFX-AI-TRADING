# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""Every capability the AI Hub specification names, and whether it really exists.

Specification §30 asks for exactly this, and says why:

    "If a capability cannot be completed immediately, implement the
     architectural interface, capability registry, placeholder contract and
     roadmap integration point so it remains part of the system rather than
     being silently omitted."

This registry is the anti-omission mechanism. A capability absent from it does
not exist as far as this project is concerned; one present in it cannot be
quietly forgotten, because it appears as `planned` in a count somebody reads.

## Why every claim carries evidence

`scripts/invariant_coverage.py` is the cautionary tale in this repository
(F176). It "certified" critical components by counting hand-typed `True`
literals: it inspected no code, called no predicate and probed no component, so
it could not print anything except full coverage — while three of the components
it certified were, at that moment, provably unprotected.

A registry whose `live` entries are self-declared is that defect with a
different noun. So `live` and `staged` entries carry an `evidence` locator —
`module`, `module:Attribute`, or `path/to/file` — and `verify()` RESOLVES it.
A capability claiming to be built whose evidence does not resolve is reported as
a discrepancy, never counted as coverage.

`coverage()` therefore reports what it MEASURED separately from what it was
TOLD, which is the distinction F176 lost.

## Reading the states

* `live`    — built, wired, and reachable from a production caller.
* `staged`  — the interface or contract exists; the behaviour behind it does not.
* `planned` — named by the specification, not yet started. Carries no evidence,
              because a pointer to nothing reads as progress.
"""

from __future__ import annotations

import importlib
import re
import pathlib
from dataclasses import dataclass, field
from typing import Any, Final, Literal

State = Literal["live", "staged", "planned"]
STATES: Final[frozenset[str]] = frozenset({"live", "staged", "planned"})

#: Repository root, for evidence locators that name a file rather than a module.
_ROOT = pathlib.Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class Capability:
    """One thing the specification requires the system to be able to do."""

    id: str
    #: The specification section that asks for it. Traceability both ways.
    section: str
    #: A, B, C or D — presence, intelligence, workforce, environment (§4).
    layer: Literal["A", "B", "C", "D"]
    title: str
    state: State = "planned"
    #: `module`, `module:Attribute`, or a repo-relative path. Empty when planned.
    evidence: str = ""
    note: str = ""


@dataclass(frozen=True)
class Discrepancy:
    """A capability that claims to be built and cannot prove it."""

    id: str
    detail: str


@dataclass(frozen=True)
class VerificationReport:
    checked: int = 0
    resolved: int = 0
    discrepancies: tuple[Discrepancy, ...] = field(default_factory=tuple)


def _c(
    id: str, section: str, layer: str, title: str, state: str = "planned", evidence: str = "", note: str = ""
) -> Capability:
    return Capability(id=id, section=section, layer=layer, title=title, state=state, evidence=evidence, note=note)  # type: ignore[arg-type]


# ── The registry ──────────────────────────────────────────────────────────────
#
# Ordered by specification section so the document and this file can be read
# side by side. Every requirement section (§4-§27) appears at least once; a
# section with no entry is a section that was dropped, and the test suite fails
# on that rather than letting it pass unnoticed.

#: §4's four layer roll-ups. Their state is DERIVED, never typed — see
#: `layer_state`. Named here so `_c` can refuse evidence on them and so the
#: derivation can exclude them from their own inputs, which would otherwise be
#: a roll-up measuring itself.
ROLLUP_IDS: Final[frozenset[str]] = frozenset(
    {
        "arch.layer_a.presence",
        "arch.layer_b.intelligence",
        "arch.layer_c.workforce",
        "arch.layer_d.environment",
    },
)


def layer_state(layer: str, rows: Any = None) -> State:
    """What a §4 layer actually is, measured from the rows inside it.

    A roll-up whose state is typed is a claim about other claims with nothing
    measuring it — F176 one level up. `scripts/invariant_coverage.py` certified
    components by counting hand-typed `True` literals and so could not print
    anything except full coverage, while three of them were provably
    unprotected.

    This found the same defect here: `arch.layer_c.workforce` was marked live
    with two of its eighty-two rows staged. Written by hand, in good faith, by
    somebody who had just finished four of its departments.

    * `live`    — every row in the layer is live. One outstanding row is enough
                  to stop it, because a layer is not "mostly" anything: the
                  operator either has the capability or does not.
    * `staged`  — the layer has been started and is not finished.
    * `planned` — nothing in it has been started, or it has no rows at all. A
                  roll-up over nothing begun must not read as partly done.

    `rows` is injectable so the rule is testable on cases the registry does not
    currently contain, which is the only way to assert the empty-layer branch
    without inventing a fifth layer.
    """
    if rows is None:
        rows = [c for c in _DECLARED if c.layer == layer and c.id not in ROLLUP_IDS]
    states = [getattr(row, "state", "planned") for row in rows]
    if not states:
        return "planned"
    if all(state == "live" for state in states):
        return "live"
    if all(state == "planned" for state in states):
        return "planned"
    return "staged"


_DECLARED: Final[tuple[Capability, ...]] = (
    # §4 — Four-layer architecture
    _c("arch.layer_a.presence", "4", "A", "Presence layer — identity, voice, animation, spatial state"),
    _c(
        "arch.layer_b.intelligence",
        "4",
        "B",
        "Intelligence layer — conversation, planning, reasoning, memory",
        "live",
        "ai.agent.loop",
        "Agentic loop and synthesis stage are built and tested.",
    ),
    _c(
        "arch.layer_c.workforce",
        "4",
        "C",
        "Workforce layer — concurrent specialist agents",
        "live",
        "ai.departments",
        "Four of twelve agents exist as departments.",
    ),
    _c("arch.layer_d.environment", "4", "D", "Environment layer — the dynamic workspace"),
    _c(
        "arch.app_is_visible_to_the_ai",
        "4",
        "B",
        "The application describes itself to the AI, derived from the live route table",
        "live",
        "ai.hub.app_surface:describe_app",
        "2,234 capabilities across 88 areas, walked with iter_api_routes. A hand-kept "
        "list would be wrong within a day and wrong in the direction nobody notices.",
    ),
    _c(
        "arch.discovery_is_not_capability",
        "4",
        "B",
        "Seeing an endpoint does not make it callable — visible and invokable are two numbers",
        "live",
        "ai.hub.app_surface:AppSurface",
        "All 968 writes are visible and unreachable; the bus carries 17 tools, none of "
        "them an HTTP route. Merging the two counts is how a map becomes a menu.",
    ),
    _c(
        "arch.platform_context_reaches_the_planner",
        "4",
        "B",
        "The catalogue reaches the place a decision is made, not only an endpoint",
        "live",
        "ai.agent.loop:_platform_context",
        "LoopContext.platform_context, bounded to 12 rows and kept a separate field "
        "from `permitted` so a planner that confuses them is refused.",
    ),
    # §5 — AI Core and personality
    _c(
        "core.context_across_tasks",
        "5",
        "B",
        "Maintain conversation context across active tasks",
        "live",
        "ai.core.context:describe",
        "Written by the job runner itself, so the conversation knows what is "
        "running without anybody remembering to tell it. Finished work stays "
        'referable \u2014 "how did it go?" arrives after the job ends. Per '
        "operator, and bounded so a week-long session does not bury the "
        "question in old tasks.",
    ),
    _c(
        "core.interruptible_speech",
        "5",
        "A",
        "Permit interruption while speaking",
        "live",
        "frontend/src/hub/conversation.ts",
        "Barge-in cancels synthesis immediately.",
    ),
    _c(
        "core.adaptive_depth",
        "5",
        "B",
        "Adapt explanation depth without changing the intelligence",
        "live",
        "ai.core.depth:explain",
        "Five registers. Every number, the counter-thesis and what would change "
        "the conclusion survive all of them, asserted by rendering each and "
        "looking for all three: a shorter version missing one is a different "
        "argument, and the reader who asked for shorter cannot tell.",
    ),
    _c(
        "core.states_uncertainty",
        "5",
        "B",
        "State uncertainty honestly",
        "live",
        "ai.core.calibration:assess",
        "A confidence nobody has checked is reported as unchecked, with the "
        "sample size \u2014 not as a rate. Twenty resolved predictions in a band "
        "before any figure is claimed. Calibration annotates a stated "
        "confidence and never rewrites one: the author put their name to it.",
    ),
    _c(
        "core.challenges_assumptions",
        "5",
        "B",
        "Challenge weak assumptions and present counterarguments",
        "live",
        "ai.core.challenger:challenge",
        "States the counterargument, not the flaw \u2014 a Challenge whose text is "
        "under thirty characters fails at construction. Allowed to find nothing: "
        "a challenger that always fires is one nobody reads. Surfaced in the "
        "proposal body a human reads, not behind a link.",
    ),
    _c(
        "core.no_false_completion",
        "5",
        "B",
        "Never claim work is complete that is not",
        "live",
        "ai.jobs.runner:TERMINAL_STATES",
        "Job state is derived from the work, never asserted ahead of it.",
    ),
    # §6 — Presentation and adaptive modes
    _c(
        "modes.registry",
        "6",
        "D",
        "Presentation mode registry",
        "live",
        "frontend/src/hub/modes.ts:MODES",
        "Ten modes, each with a greeting, layout, depth, density and accent. A mode nobody can ask for is a mode that does not exist \u2014 every one is reachable by phrase, asserted.",
    ),
    _c(
        "modes.professional_core",
        "6",
        "D",
        "Default professional core mode",
        "live",
        "frontend/src/hub/modes.ts:professional_core",
        "",
    ),
    _c(
        "modes.market_analyst",
        "6",
        "D",
        "Market analyst mode",
        "live",
        "frontend/src/hub/modes.ts:market_analyst",
        "",
    ),
    _c(
        "modes.research_scientist",
        "6",
        "D",
        "Research scientist mode",
        "live",
        "frontend/src/hub/modes.ts:research_scientist",
        "",
    ),
    _c(
        "modes.engineering",
        "6",
        "D",
        "Engineering / developer mode",
        "live",
        "frontend/src/hub/modes.ts:engineering",
        "",
    ),
    _c(
        "modes.teaching",
        "6",
        "D",
        "Teaching mode",
        "live",
        "frontend/src/hub/modes.ts:teaching",
        "",
    ),
    _c(
        "modes.executive_briefing",
        "6",
        "D",
        "Executive briefing mode",
        "live",
        "frontend/src/hub/modes.ts:executive_briefing",
        "",
    ),
    _c(
        "modes.mission_control",
        "6",
        "D",
        "High-density mission control mode",
        "live",
        "frontend/src/hub/modes.ts:mission_control",
        "",
    ),
    _c(
        "modes.minimal_focus",
        "6",
        "D",
        "Minimal focus mode",
        "live",
        "frontend/src/hub/modes.ts:minimal_focus",
        "",
    ),
    _c(
        "modes.emergency",
        "6",
        "D",
        "Emergency / critical alert mode",
        "live",
        "frontend/src/hub/modes.ts:emergency",
        "Promoted over any chosen mode whenever the presence is alerting. A mode is a preference; an alert is a fact.",
    ),
    _c(
        "modes.child_simple",
        "6",
        "D",
        "Child-simple explanation mode",
        "live",
        "frontend/src/hub/modes.ts:child_simple",
        "Same digits, ordinary words. Asserted across all ten registers: a mode that rounded a drawdown to suit its register would be a mode that lies.",
    ),
    # §7 — Holographic presence system
    _c(
        "presence.head",
        "7",
        "A",
        "Professional holographic head as the default presence",
        "live",
        "frontend/src/hub/PresenceCore.tsx",
        "Drawn inside the rings, not instead of them \u2014 the rings carry "
        "measurements and a face replacing them would be decoration replacing "
        "data. Abstract rather than rendered: a human face here reads as a mascot.",
    ),
    _c(
        "presence.stage",
        "7",
        "A",
        "Holographic stage — orbital rings, scan-line, projection glow",
        "live",
        "frontend/src/index.css",
        "Two counter-rotating rings, scan-line and 3D perspective exist.",
    ),
    _c(
        "presence.reduced_motion",
        "7",
        "A",
        "Reduced-motion alternative for the stage",
        "live",
        "frontend/src/index.css",
        "prefers-reduced-motion guard is present.",
    ),
    _c(
        "presence.idle_attention",
        "7",
        "A",
        "Natural idle movement and attention states",
        "live",
        "frontend/src/hub/attention.ts:idleMotion",
        "The attention tracking this row was waiting for. Still when the "
        "operator is genuinely away \u2014 animating to an empty room is wasted "
        "frames \u2014 breathing when they are present, and breathing when attention "
        "is UNKNOWN, because a presence that goes still on unknown looks broken "
        "rather than tactful on every browser that does not report visibility. "
        "Reduced motion stops it entirely, as a floor rather than a weight.",
    ),
    _c(
        "presence.animation_states",
        "7",
        "A",
        "Listening, thinking, working, speaking, explaining, alerting",
        "live",
        "frontend/src/hub/presence.ts",
        "Eight states, derived from real inputs, each with a reason.",
    ),
    _c(
        "presence.lip_sync",
        "7",
        "A",
        "Lip synchronisation where the voice pipeline supports it",
        "live",
        "frontend/src/hub/head.ts:mouthFor",
        "Driven by the character actually being spoken, from a real engine "
        "index. Unmeasured holds a steady shape and reports measured=false; a "
        "sine wave would play identically for a word and a briefing, and keep "
        "playing after synthesis died.",
    ),
    _c(
        "presence.particle_field",
        "7",
        "A",
        "Particle field, used with restraint",
        "live",
        "frontend/src/hub/head.ts:particleField",
        "Restraint enforced in code, not left to the drawing: none under "
        "reduced motion, none when offline, and the count tracks measured "
        "intensity so a quiet system looks quiet.",
    ),
    _c(
        "presence.spatial_movement",
        "7",
        "A",
        "Move toward the panel being discussed",
        "live",
        "frontend/src/hub/head.ts:headOffset",
        "A small lean, capped at 6% of the core \u2014 a presence that slides "
        "across the screen takes the eye off the panel it is pointing at. Zero "
        "under reduced motion.",
    ),
    _c(
        "presence.gestures",
        "7",
        "A",
        "Pointing, highlighting and gesture overlays",
        "live",
        "frontend/src/hub/head.ts:gazeToward",
        "Eyes track the panel and a dashed ray points to it \u2014 only from a "
        "measured rect. An unmeasured one yields null and no gesture at all, "
        "rather than a confident point at the origin.",
    ),
    _c(
        "presence.multi_projection",
        "7",
        "A",
        "Minimise, reposition, or split into multiple projections",
        "live",
        "frontend/src/hub/projection.ts:splitProjection",
        "Split capped at three \u2014 six talking heads is a worse screen than one "
        "presence that turns. Minimised is small, never gone: the presence is "
        "where the alert state is shown.",
    ),
    _c(
        "presence.transformations",
        "7",
        "A",
        "Contextual transformation into scientific representations",
        "live",
        "frontend/src/hub/projection.ts:representationFor",
        "Only when the representation IS the subject. Schematic, not plotted: a "
        "half-size unlabelled copy of the distribution beside the real one is "
        "two charts disagreeing about which is authoritative.",
    ),
    _c(
        "presence.xr_abstraction",
        "7",
        "A",
        "Renderer abstraction for 3D, AR, VR and holographic output",
        "live",
        "frontend/src/hub/projection.ts:selectRenderer",
        "The abstraction is the deliverable; only canvas2d is implemented and "
        "availableRenderers() says so. Asking for webxr returns canvas2d with "
        "fellBack=true and a reason \u2014 never a silent fall-back that would let "
        "a deployment believe it was in VR.",
    ),
    # §8 — Dynamic generative workspace engine
    _c(
        "workspace.engine",
        "8",
        "D",
        "Generate, update, rearrange and remove surfaces from intent",
        "live",
        "frontend/src/hub/workspace.ts",
        "Opens, updates, reorders and removes surfaces from intent.",
    ),
    _c(
        "workspace.surface_types",
        "8",
        "D",
        "Charts, images, video, documents, tables, maps, terminals, code, camera, news, research, simulations",
        "live",
        "frontend/src/hub/SurfaceView.tsx:RENDERED_KINDS",
        "Ten of §8's twelve render. The blocker was not a missing renderer: surfaceData's default "
        "branch DISCARDED caller-supplied data, so an AI opening a document surface with the document "
        "in it got 'nothing is connected to a document surface yet'. Content is now passed through "
        "with every shape checked, because data reaches there from a model and a string where rows "
        "belong crashes a panel and takes the plane with it. camera draws its consent state rather "
        "than 'cannot draw a camera' — §25 already knew the answer. map and simulation stay "
        "unrendered and UNRENDERED_KINDS asserts it: there is no tile source and no simulator, and a "
        "map drawn from nothing is read as a map.",
    ),
    _c(
        "workspace.concurrent_surfaces",
        "8",
        "D",
        "1-20+ concurrent surfaces subject to device capacity",
        "live",
        "frontend/src/hub/workspace.ts",
        "Bounded, with least-important eviction.",
    ),
    _c(
        "workspace.priority_tiers",
        "8",
        "D",
        "Critical, primary, secondary, background, on-demand tiers",
        "live",
        "frontend/src/hub/layout.ts:SPAN_BY_PRIORITY",
        "place() sizes every panel from its tier and collapses only the background and on-demand ones, "
        "and PresenceStage calls it on every render. Proven by execution rather than by reading: "
        "hub_a11y_reaches_the_plane.test.tsx renders eight surfaces and drives the collapsed stack the "
        "tiers produce. The previous note said nothing ranks by them, and pointed at the Python "
        "constant — the half of the contract with no ranker behind it.",
    ),
    _c(
        "workspace.auto_layout",
        "8",
        "D",
        "Choose layout from task, viewport, object count and attention",
        "live",
        "frontend/src/hub/layout.ts",
        "suggestLayout reads focus and object count; place() collapses to one "
        "column below 640px and floors spans at half width below 1024px.",
    ),
    _c(
        "workspace.pinning",
        "8",
        "D",
        "Pin a surface so it stays visible",
        "live",
        "frontend/src/hub/workspace.ts",
        "Pinned surfaces survive clear and are never evicted.",
    ),
    _c(
        "workspace.layouts",
        "8",
        "D",
        "Focus, compare, split, timeline, war-room, presentation layouts",
        "live",
        "frontend/src/hub/layout.ts:LAYOUTS",
        "All six plus auto. Named by voice or text through readLayout; the "
        "rendered grid column is asserted, not just the placement function.",
    ),
    _c(
        "workspace.nl_commands",
        "8",
        "D",
        "Natural-language workspace commands",
        "live",
        "frontend/src/hub/intent.ts",
        "Local, instant, deterministic; unrecognised falls through.",
    ),
    _c(
        "workspace.history_snapshots",
        "8",
        "D",
        "Workspace history and named snapshots",
        "live",
        "frontend/src/hub/history.ts:SnapshotStore",
        '§8\'s own example command. "Yesterday" resolves to a snapshot taken '
        "yesterday, or nothing — never the newest one instead. Automatic "
        "capture once a minute so the command has something to find.",
    ),
    _c(
        "workspace.graceful_degrade",
        "8",
        "D",
        "Degrade on small devices rather than failing",
        "live",
        "frontend/src/hub/history.ts:capacityFor",
        "Four surfaces below 640px, eight below 1024px, twelve above. Applied on rotation, not only at mount.",
    ),
    # §9 — Spatial AI interaction
    _c(
        "spatial.scene_model",
        "9",
        "D",
        "Scene model — identity, position, size, z-order, content, meaning",
        "live",
        "frontend/src/hub/sceneFrom.ts:sceneFrom",
        "PresenceStage populates it from the same measurement pass that produces the spoken positions. "
        "It was already reading every rectangle and discarding it, so sceneGraph.ts — built in Phase D1 — "
        "was constructed in zero production modules and answered every question with a throw. z comes "
        "from paint order; a rectangle with no area is dropped rather than placed at the origin, where "
        "it would win 'the panel on the far left' while not being on screen.",
    ),
    _c(
        "spatial.panel_registry",
        "9",
        "D",
        "Semantic panel registry",
        "live",
        "frontend/src/hub/resolveReference.ts:resolveReference",
        "Meaning first, then the scene. It fixed a real defect: workspace.resolve returns null for 'the "
        "one on the right' and that null went into workspace.focus(null), so asking for a panel by its "
        "position unfocused everything and said nothing. Four refusals, each with its own reason, "
        "because the operator's next move differs; and a direction with nothing in it never wraps round.",
    ),
    _c(
        "spatial.viewport_awareness",
        "9",
        "D",
        "Coordinate and viewport awareness",
        "live",
        "frontend/src/hub/spatial.ts:positionOf",
        "Measured from a real DOMRect, never derived from the grid the layout "
        "asked for. A zero or unmeasured rect yields null and no position is "
        "claimed \u2014 a wrong corner points the operator at the wrong screen.",
    ),
    _c(
        "spatial.target_highlight",
        "9",
        "D",
        "Target highlighting",
        "live",
        "frontend/src/hub/reference.ts:referencesIn",
        "The panel the AI is describing takes a distinct border, an "
        'aria-current and the words "speaking about" \u2014 colour is never the '
        "only indicator. Whole-word matching only.",
    ),
    _c(
        "spatial.focus_transitions",
        "9",
        "D",
        "Animated focus transitions",
        "live",
        "frontend/src/hub/spatial.ts:focusTransition",
        "Transform and opacity only, 200ms, and removed outright rather than "
        "shortened under prefers-reduced-motion. Asserted by test, both.",
    ),
    _c(
        "spatial.zoom_regions",
        "9",
        "D",
        "Zoom into data regions",
        "live",
        "frontend/src/hub/spatial.ts:readZoom",
        "Applied to the series, not just the drawing, and dropped when you "
        "navigate out of the layer \u2014 a chart still showing a sliced range "
        "after you left that view is lying about its range.",
    ),
    _c(
        "spatial.layer_navigation",
        "9",
        "D",
        "Layer navigation and breadcrumbs",
        "live",
        "frontend/src/hub/spatial.ts:LayerStack",
        "Shown only when there is somewhere to go back to. Breadcrumbs for "
        "closed surfaces are pruned rather than left navigating nowhere.",
    ),
    _c(
        "spatial.speech_sync",
        "9",
        "A",
        "Speech references synchronised with visual focus",
        "live",
        "frontend/src/hub/reference.ts:spokenFocus",
        "Driven by a measurement \u2014 an audio element's playback position or a "
        "Web Speech boundary charIndex. Unmeasured is null, and null highlights "
        "the whole utterance rather than stepping from a timer that would drift.",
    ),
    # §10 — Multi-display and cognitive load
    _c(
        "load.dominant_placement",
        "10",
        "D",
        "Critical information receives dominant placement",
        "live",
        "frontend/src/hub/workspace.ts",
        "Critical spans 12 of 12; background spans 3.",
    ),
    _c(
        "load.explained_focus",
        "10",
        "D",
        "What is being explained receives visual focus",
        "live",
        "frontend/src/hub/reference.ts:spokenFocus",
        "AI attention is a separate signal from operator focus; merging them "
        "would make the AI mentioning a panel read as the operator selecting it.",
    ),
    _c(
        "load.background_collapse",
        "10",
        "D",
        "Background information collapses into stacks or summaries",
        "live",
        "frontend/src/hub/layout.ts:COLLAPSE_ABOVE",
        "Past five surfaces the background tier folds into a named, clickable "
        "stack. Collapsed is not hidden \u2014 a panel whose name you cannot see "
        "is one you cannot get back. Never a pinned or focused surface.",
    ),
    _c(
        "load.cross_surface_summary",
        "10",
        "B",
        "Summarise across surfaces and name relationships",
        "live",
        "frontend/src/hub/summary.ts:RELATIONS",
        "Relationships are declared and tested, not inferred: an unlisted pair "
        "produces silence rather than a plausible sentence. Describes the "
        "screen, never the account \u2014 asserted by a forbidden-phrase test.",
    ),
    _c(
        "load.user_override",
        "10",
        "D",
        "User can override AI layout decisions",
        "live",
        "frontend/src/hub/SurfaceView.tsx",
        "Close and pin on every surface.",
    ),
    # §11 — Multi-agent intelligence network
    _c(
        "agents.orchestrator",
        "11",
        "C",
        "Orchestrator — decompose, allocate, track, merge, resolve",
        "live",
        "ai.agent.orchestrator:decompose",
        "Executes a TaskGraph rather than re-implementing ordering \u2014 a second "
        "scheduler beside the graph is how the graph stops being the thing that "
        "decides, and a test parses this module for any sorting of its own. "
        "Decomposition is DECLARED: turning a question into steps is a "
        "planner's paid model call, and keeping it out makes the graph "
        "deterministic. Allocation NAMES what it could not place \u2014 an unknown "
        "department, an unimplemented action, or one that is not read-only \u2014 "
        "because a step dropped from the plan reads exactly like a step that "
        "ran and returned nothing. merge() reports which tasks answered nothing "
        "separately from what the others answered. A conflict goes to "
        "ai/debate/session.py and is never averaged: averaging two opposite "
        "conclusions produces a number nobody argued for, and cannot express "
        "UNRESOLVED.",
    ),
    _c("agents.trading", "11", "C", "Trading agent", "live", "ai.departments.markets_execution", ""),
    _c(
        "agents.risk",
        "11",
        "C",
        "Risk agent with an independent challenge function",
        "live",
        "ai.departments.risk_compliance",
        "",
    ),
    _c("agents.research", "11", "C", "Research agent", "live", "ai.departments.research", ""),
    _c(
        "agents.system",
        "11",
        "C",
        "System agent — infrastructure, services, resources, failures",
        "live",
        "ai.departments.system_ops",
        "Three READ_ONLY actions over measurements §22 already produced and no agent could reach. "
        "Readings pass through with their measured flag intact rather than flattened into bare "
        "numbers — flattening is how an unset gauge reads back 0.0 and the machine reports itself "
        "idle. There is no restart, scale or kill: a struggling machine is exactly when an agent "
        "acting on its own initiative does the most damage.",
    ),
    _c(
        "agents.news",
        "11",
        "C",
        "News intelligence agent",
        "live",
        "ai.departments.news_intelligence",
        "Headlines and geopolitical severity, both delegated. A handler that "
        "scored a headline itself would be a sentiment number no feed produced.",
    ),
    _c(
        "agents.vision",
        "11",
        "C",
        "Vision agent",
        "live",
        "ai.departments.vision_ops",
        "It can be SHOWN a picture and cannot go and take one. describe_image takes images as an "
        "argument, checks §25 camera consent BEFORE the pixels are read, and has no path to a capture "
        "API — asserted by parsing the module, not promised in a docstring. A camera opened mid-loop "
        "on a trading desk is a different act from interpreting a frame somebody handed over.",
    ),
    _c(
        "agents.voice",
        "11",
        "C",
        "Voice agent — recognition, synthesis, turn management",
        "live",
        "ai.departments.voice_interface",
        "Reports whether a provider key is set, never its value \u2014 an agent "
        "result lands in memory and is fenced back into a model. Read-only: it "
        "cannot speak, because a system that can talk to somebody who did not "
        "ask it to is a different risk tier.",
    ),
    _c(
        "agents.memory",
        "11",
        "C",
        "Memory agent — retrieval, consolidation, governance",
        "live",
        "ai.departments.memory_ops",
        "It reads and it may not forget. §16's right to be forgotten is the operator's, and an agent "
        "holding it is a memory hole with a permission tier — a model deciding mid-loop that some "
        "history is no longer relevant, erasing it, and leaving the person whose history it was with "
        "no way to know. describe_retention names the route to erasure and does not take it; the "
        "module calls nothing that erases or edits, asserted by parsing it. Recall is keyed by "
        "operator, not filtered — the P0 in ai/jobs/runner.py with a longer memory.",
    ),
    _c(
        "agents.notification",
        "11",
        "C",
        "Notification agent — severity, escalation, interruption",
        "live",
        "ai.departments.notification_ops",
        "The dry run calls decide(), never route() or submit() \u2014 so asking "
        '"what would happen to this?" cannot deliver it, spend the rate budget, '
        "or write the deduplication record that would silence the real one.",
    ),
    _c(
        "agents.data",
        "11",
        "C",
        "Data agent — acquisition, validation, freshness",
        "live",
        "ai.departments.data_ops",
        "An unavailable reading carries no reading at all. Of the four agents "
        "added here this is the one where inventing an answer does concrete "
        "harm: a freshness figure nobody measured reports a dead feed as live.",
    ),
    _c(
        "agents.development",
        "11",
        "C",
        "Development agent — code, debugging, architecture",
        "live",
        "ai.departments.platform_engineering",
        "scan_secrets, run_tests, check_broken_imports and propose_fix \u2014 code, "
        "debugging and architecture. This row and agents.system both pointed at "
        "this one module; the System agent's own remit (infrastructure, "
        "services, resources, failures) has no agent, and is planned again.",
    ),
    # §12 — Agent-to-agent communication
    _c(
        "bus.message_envelope",
        "12",
        "C",
        "Typed message — task id, correlation id, priority, status, confidence, evidence, expiry",
        "live",
        "ai.bus.agent_bus:AgentBus",
        "The bus carries THIS type and refuses a dict, so a second untyped envelope cannot grow beside the typed one.",
    ),
    _c(
        "bus.pubsub",
        "12",
        "C",
        "Publish/subscribe event bus",
        "live",
        "ai.bus.agent_bus:AgentBus",
        "Operator-scoped by dictionary key rather than by filter, so a lookup "
        "that forgets the scope finds nothing rather than everything. It cannot "
        "invoke a tool: ai/bus imports nothing from ai/tools, asserted by AST "
        "rather than by grep, so publishing is not a second execution path "
        "around the permission registry and the invariants.",
    ),
    _c(
        "bus.lifecycle_events",
        "12",
        "C",
        "Task lifecycle events",
        "live",
        "ai.bus.lifecycle:TaskLifecycle",
        "Terminal is terminal, and an illegal transition raises rather than "
        "logging: two contradictory reports would leave the displayed state "
        "decided by delivery order. A queued task cannot report succeeded — an "
        "outcome for work that never ran is invented, not observed.",
    ),
    _c(
        "bus.streaming_partials",
        "12",
        "C",
        "Streaming partial results",
        "live",
        "ai.bus.lifecycle:TaskLifecycle",
        "TaskLifecycle.partial. Numbered from 1, so a consumer can see 1, 2, 4 and say so instead of "
        "concatenating text that is missing a piece and looking complete.",
    ),
    _c(
        "bus.cancellation",
        "12",
        "C",
        "Cancellation and timeout handling",
        "live",
        "ai.jobs.runner:JobRunner",
        "Deadlines, cancellation and reaping are built.",
    ),
    _c(
        "bus.task_graph",
        "12",
        "C",
        "Task graph rather than a sequential queue",
        "live",
        "ai.bus.graph:TaskGraph",
        "A cycle is refused by add(), which is the last moment at which nothing "
        "has run yet; detecting one at schedule time means the first task in it "
        "already executed. A failed dependency blocks its dependents and names "
        "what blocked them, rather than dropping them from the report where "
        "they would read as succeeded.",
    ),
    # §13 — Debate and conflict resolution
    _c(
        "debate.opposing_perspectives",
        "13",
        "C",
        "Invoke opposing perspectives for high-value decisions",
        "live",
        "ai.debate.session:debate",
        "A single stance is refused as a debate: dressing one position as a "
        "debate implies an opposing view was sought and found wanting.",
    ),
    _c(
        "debate.no_forced_consensus",
        "13",
        "C",
        "Do not force artificial consensus",
        "live",
        "ai.debate.session:DECISIVE_RATIO",
        "UNRESOLVED is a distinct outcome, not a weaker verdict. Sides within "
        "1.5x have not been separated by the evidence, and calling that a "
        "resolution is artificial consensus wearing a decimal point.",
    ),
    _c(
        "debate.record_claims",
        "13",
        "C",
        "Record competing claims and evidence",
        "live",
        "ai.debate.session:DebateResult",
        "Every position keeps its evidence, its weight, and whether that "
        "evidence was stale. An unsupported dissent is recorded, not dropped.",
    ),
    _c(
        "debate.evidence_weighting",
        "13",
        "C",
        "Weight evidence by quality and freshness",
        "live",
        "ai.debate.evidence:weigh",
        "Measured outranks recalled by 8x, so repetition is no substitute for "
        "sourcing. Stale is downweighted and marked, never dropped; an absent "
        "timestamp is unmeasured, never treated as fresh.",
    ),
    _c(
        "debate.calibration",
        "13",
        "C",
        "Track agent calibration and historical reliability",
        "live",
        "ai.core.calibration:summary",
        "Per agent and per confidence band \u2014 accuracy at 90% says nothing about "
        "accuracy at 55%, and pooling them hides both. A prediction resolves "
        "once, so a retry cannot double an agent's apparent accuracy.",
    ),
    _c(
        "debate.neutral_synthesis",
        "13",
        "B",
        "Neutral synthesis step for consequential recommendations",
        "live",
        "ai.agent.synthesis",
        "",
    ),
    # §14 — Parallel task execution
    _c("parallel.foreground", "14", "C", "Foreground interactive tasks", "live", "ai.jobs.runner:JobRunner", ""),
    _c("parallel.background", "14", "C", "Background monitoring tasks", "live", "ai.awareness.watchers", ""),
    _c(
        "parallel.scheduled",
        "14",
        "C",
        "Scheduled tasks",
        "live",
        "ai.evals.schedule:run_forever",
        "Opt-in scheduling exists for the eval suite.",
    ),
    _c(
        "parallel.event_triggered",
        "14",
        "C",
        "Event-triggered tasks",
        "live",
        "ai.bus.triggers:TriggerRegistry",
        "A trigger ENQUEUES and never executes: running the task inside the "
        "subscriber callback would make the message bus an execution path, "
        "which is the one thing \u00a712 was built not to be. ai/bus/triggers.py "
        "cannot import ai.tools, asserted by parsing. Every triggered item "
        "carries a depth one higher than the message that caused it and a "
        "trigger refuses to fire past its ceiling, because a task that "
        "publishes the event that triggers it is a loop that eats the queue. A "
        "predicate that raises, and a queue that is full, are recorded on the "
        "registry rather than returned to the publisher as a broken "
        "subscriber \u2014 the message was delivered correctly and the trigger is "
        "what failed.",
    ),
    _c(
        "parallel.long_running",
        "14",
        "C",
        "Long-running research jobs",
        "live",
        "ai.jobs.store:RedisJobStore",
        "The scheduling half landed in Phase B; this is the durability half its own note said was "
        "missing. Same shape and same lesson as ai/gateway/budget_store.py, where spend lived in a "
        "module global and every restart reset the month to zero. A job that was RUNNING when the "
        "process died comes back INTERRUPTED, not running: its thread is gone, and a job that says "
        "running for ever is one nobody can act on. Memory wins over the store for a live job — the "
        "store is written after each transition and is behind by design. The operator is part of the "
        "KEY, not a filter applied after the read, because ai/jobs/runner.py is where that exact P0 "
        "was found. Without Redis the runner reports durable=False with the reason rather than "
        "losing work quietly.",
    ),
    _c("parallel.streaming_progress", "14", "C", "Streaming task progress", "live", "ai.jobs.progress:publish", ""),
    _c("parallel.budgets", "14", "C", "Cancellation and resource budgets", "live", "ai.gateway.budget:check", ""),
    _c(
        "parallel.priority_queues",
        "14",
        "C",
        "Concurrency limits and priority queues",
        "live",
        "ai.jobs.priority:AgeingPriorityQueue",
        "Rank is priority MINUS how long an item has waited, so the bottom tier "
        "cannot be starved: a background item overtakes a just-arrived critical "
        "one after exactly the tier gap in ageing periods. A plain priority "
        "queue answers 'critical' for ever under sustained load, and the "
        "starved job shows `queued` on the operator's screen \u2014 "
        "indistinguishable from one about to start. Wired into JobRunner "
        "ADMISSION and consulted only when the pool is saturated: "
        "ThreadPoolExecutor is the live path for every AI Core panel, and "
        "priority can only decide anything under contention, so uncontended "
        "submission is unchanged. The snapshot reports the longest wait as well "
        "as the depth, because depth alone hides starvation.",
    ),
    _c(
        "parallel.failure_isolation",
        "14",
        "C",
        "Graceful failure isolation",
        "live",
        "ai.jobs.runner:JobRunner",
        "One job's failure is that job's outcome.",
    ),
    # §15 — Reasoning, explainability and challenge
    _c(
        "reason.thesis",
        "15",
        "B",
        "State the thesis",
        "live",
        "ai.debate.reasoning:Reasoning",
        "",
    ),
    _c(
        "reason.counter_thesis",
        "15",
        "B",
        "State the counter-thesis",
        "live",
        "ai.debate.reasoning:ReasoningIncomplete",
        "Required at construction. It is one of the two parts dropped first "
        "under pressure, because it is one of the two that make the author "
        "less persuasive.",
    ),
    _c(
        "reason.evidence",
        "15",
        "B",
        "Show key evidence",
        "live",
        "ai.debate.evidence:Evidence",
        "Evidence for and against are separate fields, so the balance is readable without re-reading every item.",
    ),
    _c(
        "reason.assumptions",
        "15",
        "B",
        "Identify assumptions",
        "live",
        "ai.debate.reasoning:Reasoning",
        "",
    ),
    _c(
        "reason.missing_information",
        "15",
        "B",
        "Identify missing information",
        "live",
        "ai.agent.synthesis:Recommendation",
        "A department with no reading becomes stated missing information; "
        "silence about a blind spot reads as an all-clear.",
    ),
    _c(
        "reason.confidence",
        "15",
        "B",
        "Calibrated confidence where possible",
        "live",
        "ai.debate.reasoning:Reasoning",
        "Absent is allowed; unfounded is refused. A confidence requires a basis "
        "\u2014 a bare number is a mood, and somebody may size a position against "
        "it. Absence is stated in words, not omitted.",
    ),
    _c(
        "reason.what_would_change_it",
        "15",
        "B",
        "Explain what would change the conclusion",
        "live",
        "ai.debate.reasoning:ReasoningIncomplete",
        "Required at construction. An argument with no stated way to be wrong is an assertion.",
    ),
    _c(
        "reason.risk_alternatives",
        "15",
        "B",
        "Provide risk and alternative actions",
        "live",
        "ai.debate.reasoning:Reasoning",
        "Doing nothing is always among the alternatives offered.",
    ),
    # §16 — Memory and knowledge
    _c(
        "memory.working",
        "16",
        "B",
        "Working memory for the current turn",
        "live",
        "ai.memory.tiers:end_turn",
        "Cleared when the turn ends, asserted \u2014 working memory that survives "
        "the turn is not working memory, it is a leak with a label.",
    ),
    _c(
        "memory.session",
        "16",
        "B",
        "Session memory",
        "live",
        "ai.memory.tiers:end_session",
        "Ends the turn inside it too: a turn cannot outlive the session it happened in.",
    ),
    _c("memory.project", "16", "B", "Project memory for long-running work", "live", "ai.memory.store", ""),
    _c(
        "memory.long_term",
        "16",
        "B",
        "Long-term memory for approved persistent facts",
        "live",
        "ai.memory.governance:approve_long_term",
        "A fact reaches long-term when somebody approves it and not before, and "
        'the approver\'s name is stored with it. Without that, "long-term" was a '
        'synonym for "everything, for ever".',
    ),
    _c(
        "memory.episodic",
        "16",
        "B",
        "Episodic memory for significant events",
        "live",
        "ai.notify.service:_remember_if_significant",
        '"Significant" is defined rather than felt: an interrupting severity or '
        "an escalation. An episodic memory of every informational notice is a "
        "log with a grander name.",
    ),
    _c(
        "memory.knowledge_graph",
        "16",
        "B",
        "Knowledge graph across entities, projects, tasks",
        "live",
        "ai.memory.graph:RELATIONS",
        "Eight declared relations; an invented edge is refused. Per operator "
        "and cleared by a deletion \u2014 a graph left behind keeps the shape of "
        "what was deleted, which is most of what it recorded.",
    ),
    _c(
        "memory.provenance",
        "16",
        "B",
        "Memory provenance and timestamps",
        "live",
        "ai.memory.tiers:remember",
        "`source` is required at construction. An unattributable memory is one "
        "nobody can check, and it will be handed back to a model later as "
        "though somebody had.",
    ),
    _c(
        "memory.user_controls",
        "16",
        "B",
        "User review, correction and deletion",
        "live",
        "ai.memory.governance:ForgetResult",
        "Deletion reports what it could NOT reach, and `complete` is derived "
        "from that rather than stored, so the two cannot disagree. The durable "
        "department store is keyed by department with no operator column, so it "
        "is named as out of reach rather than silently skipped.",
    ),
    # §17 — Voice and real-time conversation
    _c(
        "voice.streaming_stt",
        "17",
        "A",
        "Low-latency streaming speech recognition",
        "live",
        "frontend/src/hub/listening.ts:Listening",
        "Listening.heard. An interim result is a GUESS, and guesses do not go in the transcript. "
        "Recognition revises as it hears more \u2014 'sell', 'sell gold', 'sell gold "
        "now' \u2014 and appending those builds a transcript of half-heard phrases "
        "attributed to the operator. An interim REPLACES the previous interim, "
        "only a final result commits, and an interim still pending when the "
        "microphone closes is DROPPED, because a half-heard phrase left on "
        "screen reads as something that was said. Anything heard while the "
        "microphone is shut is ignored outright.",
    ),
    _c(
        "voice.tts",
        "17",
        "A",
        "Speech synthesis",
        "live",
        "frontend/src/hooks/useVoice.ts",
        "Browser synthesis with a cloud fallback.",
    ),
    _c(
        "voice.interruptible",
        "17",
        "A",
        "Interruptible responses and barge-in",
        "live",
        "frontend/src/hub/conversation.ts",
        "Speech stops the instant the user speaks.",
    ),
    _c(
        "voice.push_to_talk",
        "17",
        "A",
        "Push-to-talk and optional continuous conversation",
        "live",
        "frontend/src/hub/listening.ts:Listening",
        "Open while held, shut the instant it is not. Every way of losing the "
        "key closes it \u2014 release, a hidden tab, a blur, dispose \u2014 because the "
        "one path that does not is the one that leaves a trading desk being "
        "recorded. dispose() is FINAL: nothing reopens the microphone "
        "afterwards, so a navigation cannot race a keypress. Key repeat is "
        "ignored rather than restarting it. Continuous mode is off by default "
        "and needs microphone consent, since it holds the mic open, and it "
        "stops the instant consent is withdrawn \u2014 a revocation that waits for "
        "the next mode change is not a revocation.",
    ),
    _c(
        "voice.wake_word",
        "17",
        "A",
        "Wake word where privacy-appropriate",
        "live",
        "frontend/src/hub/listening.ts:Listening",
        "'Where privacy-appropriate' is the whole clause: a wake word holds the "
        "microphone open, so it needs microphone consent, is off by default, "
        "and disarms the instant consent is withdrawn. Arming OPENS the "
        "microphone \u2014 a wake word that does not listen can never fire, which "
        "would be a control that exists, reads correctly and never runs, and "
        "the snapshot reports the open mic from the moment it is armed rather "
        "than from the moment somebody speaks. Matched on word boundaries, so "
        "'hopefxtrading' does not wake it, and a phrase under four characters "
        "is refused: 'hi' fires on half of ordinary speech, which is an "
        "always-on microphone with extra steps.",
    ),
    _c(
        "voice.pronunciation",
        "17",
        "A",
        "Pronunciation dictionary for names and financial terms",
        "live",
        "frontend/src/hub/pronunciation.ts:PRONUNCIATIONS",
        "Not cosmetic. The presence speaks unprompted in exactly one situation "
        "\u2014 an alert \u2014 and XAUUSD read letter by letter is unintelligible "
        "precisely when the operator needs to hear it without looking. A spoken "
        "alert they have to read anyway is not a spoken alert. Whole tokens "
        "only, because a naive replace turns PIPELINE into "
        "point-in-percentageELINE. It never returns an empty utterance: a "
        "dictionary that could silence an alert is a worse failure than one "
        "that mispronounces it.",
    ),
    _c(
        "voice.turn_detection",
        "17",
        "A",
        "Turn detection",
        "live",
        "frontend/src/hub/listening.ts:Listening",
        "Listening.endpointed. The state machine existed and automatic endpointing did not. Silence "
        "ALONE is not the end of a turn: an open microphone in a quiet room "
        "would fire one every second, so it endpoints only after something was "
        "heard and then stopped. The pending interim is committed when it "
        "endpoints, rather than being lost with the turn it belonged to.",
    ),
    _c(
        "voice.preferences",
        "17",
        "A",
        "Adjustable speech speed and voice preference",
        "live",
        "frontend/src/hub/voicePrefs.ts:clampPreferences",
        "The adjustment is trivial; the BOUNDS are the point. Both ends of the "
        "range lose the one message that had to arrive: a rate of 10 turns an "
        "alert into noise, and 0.05 turns it into something the operator mutes. "
        "A non-number falls back to the DEFAULT rather than to a bound, because "
        "NaN through a comparison yields whichever branch operator precedence "
        "reaches first \u2014 a behaviour nobody chose. Every adjustment is named, "
        "so a corrected setting is not a silent one.",
    ),
    # §18 — Camera, vision and gesture
    _c(
        "vision.scene_understanding",
        "18",
        "C",
        "Image and scene understanding",
        "live",
        "ai.vision.detect:interpret",
        "",
    ),
    _c(
        "vision.permission_gated",
        "18",
        "A",
        "Permission-gated with visible capture indication",
        "live",
        "frontend/src/components/intelligence/VisualIntelligenceWorkspaces.tsx",
        "No hidden activation; explicit stop clears the frame.",
    ),
    _c(
        "vision.no_retention",
        "18",
        "C",
        "Frames are not persisted",
        "live",
        "api.safe_agent_platform:vision_interpret",
        "",
    ),
    _c(
        "vision.gesture",
        "18",
        "A",
        "Gesture recognition",
        "staged",
        "frontend/src/hub/gestures.ts:recogniseGesture",
        "The POINTER half is built \u2014 swipes and long press, no camera and no "
        "consent, returning null rather than the nearest gesture because a "
        "wrongly-recognised swipe moves a panel somebody was reading. The "
        "CAMERA half needs hand landmarks and this repository has no landmark "
        "source; building a recogniser nothing feeds would be "
        "hopefx-dead-controls wearing a camera.",
    ),
    _c(
        "vision.pointing",
        "18",
        "A",
        "Pointing and object reference",
        "staged",
        "frontend/src/hub/gestures.ts:pointingAt",
        "The OBJECT REFERENCE half is built: a hit test against the scene graph "
        "answering the topmost panel under a point, and null on empty space "
        "rather than the nearest panel \u2014 'I am pointing at nothing' is an "
        "answer. The PHYSICAL POINTING half needs body landmarks, which no "
        "source in this repository produces.",
    ),
    _c(
        "vision.attention_aware",
        "18",
        "A",
        "Optional attention-aware interaction",
        "live",
        "frontend/src/hub/attention.ts:attentionFrom",
        "Built from document visibility, window focus and time since input \u2014 no "
        "camera, no consent conversation, nothing leaving the machine. The "
        "cheapest way to respect somebody's privacy is not to need their "
        "permission, so this half was built before the gaze-tracking half. "
        "UNKNOWN IS NOT AWAY: a state derived from inputs nobody supplied means "
        "'nobody looked', and reporting it as 'the operator has left' would "
        "have the presence go quiet on somebody sitting right in front of it. "
        "A visible but unfocused window reads as away, because attention is on "
        "whatever is on top of it.",
    ),
    _c(
        "vision.source_selection",
        "18",
        "A",
        "Screen and camera source selection",
        "live",
        "frontend/src/hub/visionSource.ts:selectSource",
        "The half worth getting right is that a SCREEN SHARE AND A WEBCAM ARE "
        "DIFFERENT CONSENTS. A webcam shows a face; a screen share shows the "
        "whole desktop, every other application and whatever was open behind "
        "the browser. A system treating them as one permission has quietly "
        "widened what it may see. Unknown capability reports as 'not checked' "
        "rather than 'no camera' \u2014 only one of those is a fact. `none` is "
        "always allowed, because a control that can be refused is not an off "
        "switch.",
    ),
    _c(
        "vision.local_processing",
        "18",
        "C",
        "Local processing where feasible",
        "live",
        "frontend/src/hub/frameTriage.ts:FrameTriage",
        "This is a PRIVACY row, not a performance one. The feasible local "
        "processing on a video stream is not running a model in the browser; it "
        "is noticing that most frames are not worth sending anywhere. A frame "
        "identical to the last carries nothing new, a blank frame is a lens "
        "cap, and forty a second is thirty-nine more than anyone can act on \u2014 "
        "each dropped ON THE MACHINE THAT CAPTURED IT, never travelling. Every "
        "drop is counted with a reason, because 'the AI saw nothing' and 'we "
        "sent nothing' are different facts; `keptLocal` is the number worth "
        "reading.",
    ),
    _c(
        "vision.hard_disable",
        "18",
        "A",
        "Hard disable and permission controls",
        "live",
        "frontend/src/components/intelligence/VisualIntelligenceWorkspaces.tsx",
        "",
    ),
    # §19 — Monitoring, sleep and alerts
    _c(
        "monitor.user_watches",
        "19",
        "C",
        "User-defined watches and thresholds",
        "live",
        "ai.notify.policy:Watch",
        "Owned by one operator, taken from the token and never from the request "
        'body. An unmeasured reading fires nothing: None is "nobody measured '
        'it", not zero, and a drawdown watch firing on a dead feed would send '
        "the operator looking for a loss that did not happen.",
    ),
    _c(
        "monitor.health_watchers",
        "19",
        "C",
        "Market, system, data and agent health monitoring",
        "live",
        "ai.awareness.watchers",
        "Watchers raise a proposal and never act.",
    ),
    _c(
        "monitor.severity",
        "19",
        "C",
        "Four notification severities",
        "live",
        "ai.notify.policy:Severity",
        "Identical to AlertSeverity in hub/presence.ts, and only high and "
        'critical interrupt \u2014 two definitions of "worth interrupting for" is '
        "one too many.",
    ),
    _c(
        "monitor.quiet_hours",
        "19",
        "C",
        "Quiet hours and sleep mode",
        "live",
        "ai.notify.policy:QuietHours",
        "Defers, never discards, and says when it will arrive. Handles a window "
        "crossing midnight, which a naive start<end check gets wrong in both "
        "directions. Never applies to a critical.",
    ),
    _c(
        "monitor.escalation",
        "19",
        "C",
        "Escalation rules",
        "live",
        "ai.notify.router:Router",
        "An unacknowledged interrupting notice rises one step, not straight to "
        "critical: escalation must not be a route by which an informational "
        "notice becomes an alarm at three in the morning.",
    ),
    _c(
        "monitor.alarm_scheduling",
        "19",
        "C",
        "Alarm scheduling",
        "live",
        "ai.notify.policy:Alarm",
        "Fires once, through the same policy as everything else.",
    ),
    _c(
        "monitor.wake_conditions",
        "19",
        "C",
        "User-configured wake-up conditions",
        "live",
        "ai.notify.policy:decide",
        "Pierces sleep mode and quiet hours, but only for the subject the "
        "operator named and only when its threshold is actually crossed.",
    ),
    _c(
        "monitor.dedup",
        "19",
        "C",
        "Notification deduplication and anti-spam",
        "live",
        "ai.notify.router:Router",
        "Suppression expires, because suppression that never expires is "
        "permanent blindness. A severity increase is news and is never "
        "deduplicated. Rate state is per operator. Never applies to a critical.",
    ),
    _c(
        "monitor.explain_interruption",
        "19",
        "C",
        "Explain why an interruption occurred",
        "live",
        "ai.notify.policy:Decision",
        "Every decision carries a reason naming the mechanism that made it \u2014 "
        '"suppressed" is not an explanation, "you have already been told about '
        'this in the last hour" is. Asserted for deliver, defer and suppress.',
    ),
    # §20 — Trading and HOPEFX integration
    _c("trading.mode_awareness", "20", "C", "Live and paper trading awareness", "live", "api.safe_agent_platform", ""),
    _c("trading.independent_risk", "20", "C", "Independent risk agent", "live", "ai.departments.risk_compliance", ""),
    _c(
        "trading.war_room",
        "20",
        "D",
        "Market war room generated on demand",
        "live",
        "frontend/src/hub/warRoom.ts:warRoomSurfaces",
        "war_room was already a LAYOUT — readLayout returned it and suggestLayout reached for it at "
        "eight surfaces — so the phrase rearranged whatever happened to be on the plane and, on an "
        "empty one, rearranged nothing. It now ASSEMBLES the panels, and only those whose feed has "
        "something: a war room of six 'nothing is connected yet' panels looks like a dead platform. "
        "What was left out is named aloud, because an operator who expected a news panel cannot "
        "otherwise tell whether the feed is silent or the war room forgot. Risk is declared critical "
        "so the crowded-plane collapse cannot fold it into a chip at the moment it matters most.",
    ),
    _c(
        "trading.thesis_counter",
        "20",
        "B",
        "Trade thesis and counter-thesis",
        "live",
        "ai.debate.trade:analyse_trade",
        "A trade thesis without a counter-thesis is a pitch, and fails to "
        "construct. The analysis carries no side, size or price: a structure an "
        "order router could read is one refactor from an AI trading on its own "
        "argument.",
    ),
    _c(
        "trading.correlation",
        "20",
        "B",
        "News, macro, technical and microstructure correlation",
        "live",
        "ai.debate.correlation:correlate",
        "The caveat that co-occurrence is not causation is part of the rendered "
        "output, not a footnote, and correlation never produces MEASURED "
        "evidence \u2014 what was measured is the price and the signal, not the "
        "link. A domain with no signal is named as a blind spot.",
    ),
    _c("trading.kill_switch_awareness", "20", "C", "Risk limits and kill-switch awareness", "live", "risk.manager", ""),
    _c(
        "trading.explainability",
        "20",
        "B",
        "Explainability for AI-generated trade analysis",
        "live",
        "ai.debate.trade:TradeAnalysis",
        "explain() carries the argument and the scored debate behind it. A "
        "conclusion with no working is not explainable.",
    ),
    _c(
        "trading.execution_permission",
        "20",
        "C",
        "Permission boundaries for live execution",
        "live",
        "ai.tools.bus",
        "Fail-closed permission gate with a reserved-key guard.",
    ),
    _c("trading.broker_status", "20", "C", "Broker and execution status monitoring", "live", "execution.oms", ""),
    # §21 — Visualization intelligence
    _c(
        "viz.financial_charts",
        "21",
        "D",
        "Financial charts for price/time data",
        "live",
        "frontend/src/features/chart-bot",
        "",
    ),
    _c(
        "viz.heatmap",
        "21",
        "D",
        "Heatmaps for intensity",
        "live",
        "frontend/src/hub/VizMarks.tsx:Heatmap",
        "Five-step sequential ramp, validated on the real composited surface: "
        "seven steps put adjacent cells \u0394L 0.047 apart, below the 0.06 floor. "
        "An unmeasured cell draws as the grid, not as step zero \u2014 quietest and "
        "unmeasured must not look the same.",
    ),
    _c(
        "viz.network_graph",
        "21",
        "D",
        "Network graphs for relationships",
        "live",
        "frontend/src/hub/VizMarks.tsx:NetworkGraph",
        "Three categorical hues is the measured ceiling on this surface; every "
        "candidate fourth fell below the normal-vision \u0394E 15 floor, which "
        "labelling does not excuse. Beyond three folds to a neutral. Circular "
        "layout, not force-directed: a graph that settles differently each "
        'render makes "the one on the left" meaningless.',
    ),
    _c(
        "viz.timeline",
        "21",
        "D",
        "Timelines for chronology",
        "live",
        "frontend/src/hub/VizMarks.tsx:Timeline",
        "Only timestamped events are placed. Headlines that carry no timestamp "
        "are counted and named rather than pinned to now, which would put "
        "yesterday's news at the right-hand edge.",
    ),
    _c(
        "viz.distributions",
        "21",
        "D",
        "Probability distributions for uncertainty",
        "live",
        "frontend/src/hub/SurfaceView.tsx",
        "",
    ),
    _c("viz.tables", "21", "D", "Tables for precise comparison", "live", "frontend/src/hub/SurfaceView.tsx", ""),
    _c(
        "viz.scientific_3d",
        "21",
        "D",
        "3D and scientific models where they aid understanding",
        "staged",
        "frontend/src/hub/projection.ts:RENDERERS",
        "The presence takes schematic scientific forms (distribution, network, "
        "waveform, timeline) and the renderer abstraction names WebGL, WebXR "
        "and holographic output \u2014 but only canvas2d is implemented, and "
        "availableRenderers() says so rather than implying otherwise.",
    ),
    _c(
        "viz.media_panels",
        "21",
        "D",
        "Video and image panels",
        "live",
        "frontend/src/hub/VizMarks.tsx:Media",
        "`alt` is a required field on the data rather than an optional prop, so "
        "a media panel nobody can describe cannot be constructed. Video ships "
        "with controls and never autoplays.",
    ),
    _c(
        "viz.drill_down",
        "21",
        "D",
        "Interactive drill-down",
        "live",
        "frontend/src/hub/SurfaceView.tsx",
        "Clicking a cell, node or event enters a \u00a79 layer named after the mark "
        "rather than after the panel, so a trail of three reads as three things. "
        "Every mark is keyboard-reachable with a 24px hit target.",
    ),
    _c(
        "viz.selection_intelligence",
        "21",
        "D",
        "Choose the representation that suits the information",
        "live",
        "frontend/src/hub/representation.ts:representationFor",
        "The earlier note said 'a model does not choose it yet', which framed this as waiting for a "
        "model call — that framing was wrong. A series is a chart, pairs are a table, timestamped "
        "events are a timeline: decidable from the shape of what arrived, instantly and while every "
        "vendor is unreachable, which is the argument intent.ts already makes for resolving the "
        "obvious commands locally. The model remains the fallback for what this cannot decide, which "
        "is what null means. It refuses a one-point series rather than undoing surfaceData's existing "
        "refusal to chart a single price, and prefers the richer shape when two are present.",
    ),
    # §22 — Real system monitoring
    _c(
        "telemetry.host",
        "22",
        "C",
        "GPU, CPU and memory telemetry",
        "live",
        "ai.telemetry.host:snapshot",
        "\u00a73 listed this as existing and it was not in this repository. Every "
        "probe returns a real reading or an absence WITH A REASON \u2014 psutil "
        "missing, the call raising, /proc unreadable. The GPU report separates "
        "'cannot look' from 'looked and found none': a dashboard showing 0 GPUs "
        "because pynvml is absent tells an operator their inference is on CPU "
        "when it may not be. The probes are fetched through a function rather "
        "than imported at module scope, so a host without psutil gets a reason "
        "instead of an ImportError \u2014 infrastructure/health.py imports it at "
        "module level and is unimportable there.",
    ),
    _c(
        "telemetry.latency",
        "22",
        "C",
        "End-to-end latency",
        "live",
        "ai.gateway.client:GatewayClient",
        "Per-call latency is recorded in the audit trail.",
    ),
    _c("telemetry.api_health", "22", "C", "API health", "live", "ai.gateway.providers", ""),
    _c("telemetry.database_health", "22", "C", "Database health", "live", "core.startup_factories", ""),
    _c("telemetry.queue_depth", "22", "C", "Queue depth", "live", "ai.jobs.runner:JobRunner", ""),
    _c(
        "telemetry.agent_health",
        "22",
        "C",
        "Agent health",
        "live",
        "ai.telemetry.agents:agent_health",
        "A department that exists and has no implemented action is a name in a "
        "directory, and `status` says which of the two each one is. Sources are "
        "INJECTED rather than reached for, so a job pool reported as running: 0 "
        "when no runner was passed cannot happen \u2014 that is the zero-gauge "
        "defect in a different costume, reading as an idle pool rather than an "
        "unobserved one. 'The watchers have never run' is likewise distinct "
        "from 'no observations', because only one of them is a problem.",
    ),
    _c("telemetry.model_availability", "22", "C", "Model availability", "live", "ai.gateway.breakers", ""),
    _c("telemetry.data_freshness", "22", "C", "Data freshness", "live", "data_layer.orchestrator", ""),
    _c(
        "telemetry.security_events",
        "22",
        "C",
        "Security events",
        "live",
        "ai.telemetry.security:security_events",
        "Counted from the tool bus's own audit trail rather than a second "
        "tally, which would be free to drift \u2014 and the drift would be towards "
        "looking calmer than the system is. No bus attached reports ABSENT, not "
        "zero: 'nothing has been refused' and 'nothing was watching' are "
        "different facts and only one of them is reassuring.",
    ),
    _c("telemetry.spend", "22", "C", "Cost and spend ceilings", "live", "ai.gateway.budget", ""),
    _c(
        "telemetry.no_decorative_values",
        "22",
        "C",
        "No fake live values in production",
        "live",
        "ai.telemetry.reading:Reading",
        "The type refuses to express a fake value. `value=None` requires a "
        "reason at construction and a value forbids one \u2014 a number and an "
        "excuse are two answers to one question. A genuine 0.0 stays "
        "expressible, which is the part 'return None everywhere' would break. "
        "The defect this closes is measurable in this repository: with psutil "
        "unavailable, infrastructure/metrics.py leaves system_cpu_percent unset "
        "and the Gauge reads back 0.0, while the same registry's "
        "get_all_metrics() reports None \u2014 two readers of one gauge "
        "disagreeing about whether the machine is idle or unknown.",
    ),
    # §23 — Dynamic UI architecture
    _c(
        "ui.component_registry",
        "23",
        "D",
        "Component registry for renderable surface types",
        "live",
        "frontend/src/hub/SurfaceView.tsx",
        "RENDERERS map; a missing kind states the gap.",
    ),
    _c(
        "ui.schema_driven_panels",
        "23",
        "D",
        "Schema-driven panel generation",
        "live",
        "frontend/src/hub/panelSchema.ts:describePanel",
        "The request schema existed and no engine read it. Now a SurfaceRequest "
        "becomes a descriptor nobody hand-wrote \u2014 and one that CANNOT EXIST "
        "without an accessible label: describePanel throws on an empty intent "
        "rather than emitting an unlabelled panel, because a panel that renders "
        "is a panel somebody ships. It invents no fields: every field listed was "
        "found in the data, since a schema listing what a kind COULD have "
        "produces permanent blank rows. An empty table is renderable because "
        "'no open positions' is an answer; an empty chart is not, because an "
        "empty frame is indistinguishable from a loading state that never "
        "resolves.",
    ),
    _c(
        "ui.layout_engine",
        "23",
        "D",
        "Layout engine independent of content",
        "live",
        "frontend/src/hub/layoutStrategy.ts:geometryFor",
        "It was independent of content and had a single geometry: everything "
        "place() produced was a twelve-column grid. A second strategy sits on "
        "top rather than inside, because 2,231 existing tests depend on place()'s "
        "output and rewriting it to add one would put all of them at risk to "
        "gain one. `grid` expresses the engine's importance ordering as width; "
        "`stack` expresses the same ordering as sequence, for reading and for "
        "narrow screens. An unknown strategy is REFUSED \u2014 falling back to grid "
        "would render a screen nobody asked for, report success, and leave the "
        "caller never finding out their strategy name was wrong.",
    ),
    _c(
        "ui.animation_engine",
        "23",
        "A",
        "Animation engine independent of business logic",
        "live",
        "frontend/src/hub/PresenceCore.tsx",
        "Draws a Presence and computes nothing.",
    ),
    _c(
        "ui.scene_graph",
        "23",
        "D",
        "Scene graph for spatial awareness",
        "live",
        "frontend/src/hub/sceneGraph.ts",
        "hub/spatial.ts answers where ONE rectangle is; this answers what needs "
        "more than one panel to mean anything \u2014 the chart on the left, inside "
        "the war room, the panel behind that one. Without it the AI can say "
        "where a panel is and cannot resolve 'the one under it', which is most "
        "of how people refer to things on a screen. An unknown id THROWS rather "
        "than returning null: 'no such panel' and 'nothing in that direction' "
        "are different facts and one value for both hides one of them. A "
        "containment cycle is refused when the edge is made, the same rule "
        "ai/bus/graph.py holds for tasks.",
    ),
    _c(
        "ui.workspace_store",
        "23",
        "D",
        "State store for workspace sessions",
        "live",
        "frontend/src/hub/workspaceStore.ts",
        "It never comes back one panel short without saying so. A saved session "
        "naming a surface kind this build no longer has is restored WITHOUT it "
        "and the drop is NAMED \u2014 returning three of four panels silently is "
        "the workspace losing an operator's work and reporting success. An "
        "unknown schema version is refused rather than coerced: reading a "
        "future session with today's rules produces something that looks "
        "restored and is not. A focus pointing at a surface that did not "
        "survive is dropped and named too.",
    ),
    _c(
        "ui.event_streaming",
        "23",
        "D",
        "WebSocket event streaming for live updates",
        "live",
        "api.ws_live",
        "15 typed channels with a private-channel rule.",
    ),
    _c(
        "ui.virtualization",
        "23",
        "D",
        "Virtualisation for high-density displays",
        "live",
        "frontend/src/hub/virtualization.ts",
        "\u00a722's rule arriving in the browser: an UNKNOWN VIEWPORT MUST NEVER "
        "RENDER ZERO ITEMS. A window computed from a height nobody measured \u2014 "
        "a container not laid out yet, a hidden tab, a late ref \u2014 gives "
        "start == end, and an empty list is indistinguishable from 'there is "
        "nothing to show'. So an unmeasured viewport falls back to a STATED "
        "number of rows and says why; not to all of them either, since "
        "rendering ten thousand nodes because a ref was late is the same "
        "failure from the other side. A genuinely empty list reports as "
        "measured, because it is.",
    ),
    _c(
        "ui.frame_protection",
        "23",
        "A",
        "Resource-aware rendering and frame-rate protection",
        "live",
        "frontend/src/hub/frameBudget.ts",
        "Reads \u00a722's telemetry and the browser's frame timing. An UNMEASURED "
        "load changes nothing: assuming idle is the 0% CPU gauge deciding to "
        "start more work, and assuming busy degrades a fast machine over a "
        "missing number \u2014 so fidelity HOLDS and the reason says the input was "
        "missing, which is a state somebody can see and act on. Degrades and "
        "recovers one step at a time, because a jump to the floor on one slow "
        "frame is a visible lurch the next measurement undoes, and a screen "
        "oscillating between two appearances is worse than one consistently "
        "reduced. Reduced motion caps fidelity outright rather than being "
        "weighed: a fast machine must not animate past somebody's "
        "accessibility setting.",
    ),
    _c(
        "ui.accessibility",
        "23",
        "D",
        "Accessibility and reduced-motion support",
        "live",
        "frontend/src/hub/panelSchema.ts:PanelA11y",
        "Generated panels are exactly where accessibility quietly dies: a "
        "hand-built panel gets a label because somebody typed one, and a "
        "generated one gets whatever the generator remembered \u2014 usually "
        "nothing, so a screen reader announces 'region' forty times. The only "
        "arrangement where it survives is one where the descriptor cannot be "
        "constructed without a label, a real ARIA role, and a text alternative. "
        "Reduced motion is a property of the PANEL rather than of the renderer, "
        "so a component cannot forget to ask.",
    ),
    # §24 — Technical architecture
    _c("stack.frontend", "24", "D", "React/TypeScript preserved and improved", "live", "frontend/src/App.tsx", ""),
    _c("stack.backend", "24", "B", "Existing FastAPI service architecture preserved", "live", "app.py", ""),
    _c("stack.realtime", "24", "D", "Typed real-time transport", "live", "api.ws_live", ""),
    _c(
        "stack.agent_runtime",
        "24",
        "C",
        "Isolated agent workers with task contracts",
        "staged",
        "ai.jobs.runner:JobRunner",
        "The CONTRACT half is real and now durable: a job carries an operator, a prompt, a priority "
        "tier, a timeout and a deadline, it is admitted through a bounded queue, and its outcome "
        "survives the process (ai/jobs/store.py). The ISOLATION half is not, and the earlier note "
        "was too vague about why. ThreadPoolExecutor gives threads in one interpreter: agent work "
        "shares a heap, a GIL, an import table and a filesystem with the API serving the screen, so "
        "one runaway agent can starve or crash the process it runs in. That needs a process or "
        "container boundary this deployment does not have, and no amount of code in this repository "
        "creates one — claiming it would be claiming a blast radius that does not exist.",
    ),
    _c(
        "stack.event_bus",
        "24",
        "C",
        "Event bus — Redis streams or equivalent",
        "live",
        "core.event_bus:EventBus",
        "This row said planned while a Redis pub/sub bus with 49 importers was "
        "connected at startup by init_event_bus. Registry error, not a gap. One "
        "caveat that matters to anything built on it: subscribe_local handlers "
        "fire only on the DEGRADED path, so a subscription registered there "
        "works in every test (no Redis, local delivery) and never in production "
        "(Redis up, published to a channel nobody reads). ai/bus/agent_bus.py "
        "therefore delivers in-process directly and treats this as additive "
        "fan-out.",
    ),
    _c(
        "stack.persistence",
        "24",
        "B",
        "Relational durable state and cache for transient",
        "live",
        "ai.gateway.budget_store",
        "",
    ),
    _c(
        "stack.observability",
        "24",
        "C",
        "Metrics, logs, traces and audit events",
        "live",
        "ai.gateway.audit",
        "Hash-chained audit trail.",
    ),
    _c("stack.feature_flags", "24", "D", "Feature flags for staged rollout", "live", "core.startup_factories", ""),
    # §25 — Security and authorization
    _c("sec.identity", "25", "B", "Identity and session management", "live", "api.auth", ""),
    _c("sec.rbac", "25", "B", "Role and capability-based permissions", "live", "api.auth:require_role", ""),
    _c("sec.tool_authorization", "25", "C", "Tool-level authorization", "live", "ai.tools.bus", ""),
    _c("sec.confirmation_policy", "25", "C", "Sensitive action confirmation", "live", "ai.policy.roles", ""),
    _c("sec.execution_controls", "25", "C", "Financial execution controls", "live", "ai.execution_shadow", ""),
    _c("sec.audit_log", "25", "C", "Audit logging", "live", "ai.gateway.audit", ""),
    _c("sec.secrets", "25", "B", "Secrets management", "live", "ai.guardrails.output:register_known_secret", ""),
    _c(
        "sec.rate_limiting",
        "25",
        "B",
        "Rate limiting and abuse protection",
        "live",
        "rate_limiting.advanced:is_allowed",
        "",
    ),
    _c("sec.kill_switches", "25", "C", "Kill switches", "live", "risk.manager", ""),
    _c(
        "sec.privacy_controls",
        "25",
        "A",
        "Privacy controls for memory, microphone and camera",
        "live",
        "ai.privacy.consent:check",
        "The row said the camera was gated. What that meant was Depends(_admin) "
        "plus a rate limit \u2014 authorisation, which answers 'may this ROLE call "
        "this endpoint' and never asks whether the person in front of the "
        "camera agreed to be looked at. Those are different questions and the "
        "second had nowhere to live. Default DENIED, because 'permitted until "
        "somebody objects' means the first frame is taken before anyone was "
        "asked and there is no way to un-take it. An unreadable store REFUSES: "
        "everywhere else here an unmeasured thing is reported as absent, but "
        "the question here is 'was I permitted', and a system that cannot read "
        "its permissions and proceeds anyway has none. A session grant really "
        "expires \u2014 one that outlives the session is a permanent grant with a "
        "reassuring label. Revocation is recorded rather than erased, because "
        "'never consented' and 'consented and withdrew it' are different facts. "
        "vision_interpret consults it BEFORE decoding the frame; refusing "
        "afterwards means the image was already in memory.",
    ),
    _c(
        "sec.least_privilege_agents",
        "25",
        "C",
        "Least-privilege agent credentials",
        "live",
        "ai.sandbox.runner",
        "Scrubbed environment; no credential reaches sandboxed code.",
    ),
    # §26 — Performance
    _c("perf.non_blocking", "26", "B", "Conversation never blocks on long-running tasks", "live", "ai.jobs.runner", ""),
    _c("perf.stream_partials", "26", "B", "Stream partial results", "live", "ai.gateway.client:GatewayClient", ""),
    _c(
        "perf.large_workspaces",
        "26",
        "D",
        "Render large workspaces efficiently",
        "live",
        "frontend/src/hub/VirtualList.tsx:VirtualList",
        "windowFor decided which slice to draw from Phase D1 onwards and was called by nothing, so a "
        "table of five thousand positions put five thousand nodes on the plane. Now a short list still "
        "renders whole — virtualising ten rows breaks find-in-page to save nothing — and a long one "
        "renders a window that states its real length in words and in aria-rowcount, because a window "
        "is a lie by omission and a scrollbar is not an indicator everybody has.",
    ),
    _c(
        "perf.reduce_animation_under_load",
        "26",
        "A",
        "Pause or reduce animation under load",
        "live",
        "frontend/src/hub/useFrameBudget.ts:useFrameBudget",
        "nextFidelity has decided since Phase D1 and was asked by nobody; hostLoad.ts is the two "
        "readings it never had. Host cpu comes from GET /api/ai-core/telemetry and is read through the "
        "§22 measured flag, not the value — an unset gauge reading back 0.0 is F176 itself. Frame time "
        "is a median over a burst, so one slow frame does not oscillate the plane between two "
        "appearances, and an interval spanning a hidden tab is dropped rather than counted. Anything "
        "below full fidelity stops the presence canvas AND names the level on screen: a plane that "
        "degrades silently teaches an operator the app is just slow.",
    ),
    _c(
        "perf.degraded_states",
        "26",
        "D",
        "Graceful offline and degraded states",
        "live",
        "frontend/src/hooks/useWebSocket.ts",
        "Three degraded states, each named in words rather than drawn as a dimmer screen: a stale feed "
        "(useWebSocket), an offline presence (PresenceCore stops the activity ring dead and says "
        "Offline), and reduced render fidelity under load (PresenceStage names the level, with the "
        "measured cause in its title).",
    ),
    _c(
        "perf.stale_detection",
        "26",
        "D",
        "Detect stale data and say so",
        "live",
        "frontend/src/hooks/useWebSocket.ts",
        "",
    ),
    _c(
        "perf.bounded_concurrency",
        "26",
        "C",
        "Bound agent concurrency",
        "live",
        "ai.jobs.runner:DEFAULT_MAX_CONCURRENT",
        "",
    ),
    _c(
        "perf.no_runaway_delegation",
        "26",
        "C",
        "Prevent runaway recursive delegation",
        "staged",
        "ai.agent.loop",
        "The loop is bounded; recursive delegation does not exist yet to bound.",
    ),
    _c("perf.latency_measurement", "26", "C", "Measure end-to-end latency", "live", "ai.gateway.audit:record_call", ""),
    # §27 — Accessibility and professional UX
    _c(
        "a11y.keyboard",
        "27",
        "D",
        "Keyboard navigation",
        "live",
        "frontend/src/hub/useRovingFocus.ts:useRovingFocus",
        "Escape exits the stage; the collapsed-surface stack is one tab stop with arrows inside. "
        "hub_a11y_reaches_the_plane.test.tsx asserts document.activeElement moves, not just tabIndex: "
        "a roving group that updates indices and never calls focus() is the ARIA pattern as decoration.",
    ),
    _c(
        "a11y.screen_reader",
        "27",
        "D",
        "Screen-reader semantics",
        "live",
        "frontend/src/hub/a11yLiveRegion.ts:LiveRegionRegistry",
        "One polite region for the whole hub, claimed by name and enforced by hub_a11y_guard. "
        "The overlay built in Phase P added a second; two polite regions interleave and the "
        "operator hears half of each sentence.",
    ),
    _c(
        "a11y.captions",
        "27",
        "A",
        "Captions and transcripts for voice",
        "live",
        "frontend/src/hub/PresenceCore.tsx",
        "The caption is the same sentence that is spoken.",
    ),
    _c(
        "a11y.reduced_motion",
        "27",
        "A",
        "Reduced motion mode",
        "live",
        "frontend/src/hub/a11yMotion.ts:motionFor",
        "index.css carries the media query; usePrefersReducedMotion feeds PresenceCore and VizMarks. "
        "motionFor is the one place the preference and the §23 frame budget are reconciled, and it "
        "keeps the hook's asymmetry: an unread preference means no motion, not full.",
    ),
    _c(
        "a11y.high_contrast",
        "27",
        "D",
        "High contrast option",
        "live",
        "frontend/src/hub/useContrastMode.ts:useContrastMode",
        "SurfaceView reads the preference and publishes the palette as CSS custom properties, so the "
        "mode reaches every leaf at once rather than being threaded through eleven components and "
        "forgotten at the twelfth. Measured, not asserted: the suite checks the high tokens clear 7:1 "
        "AND that the rendered panel actually carries them — pinning the palette to standard while "
        "still reporting data-contrast=high passed an earlier version of that test.",
    ),
    _c(
        "a11y.responsive",
        "27",
        "D",
        "Responsive layouts",
        "live",
        "frontend/src/hub/a11yBreakpoints.ts:breakpointFor",
        "One definition of every breakpoint. layout.ts, layoutStrategy.ts and presenceDock.ts each held "
        "their own 640; they agreed by copy-paste, so moving one would have produced a width where the "
        "grid collapsed and the presence overlay did not.",
    ),
    _c(
        "a11y.touch_and_mouse",
        "27",
        "D",
        "Touch and mouse support",
        "live",
        "frontend/src/hub/SurfaceView.tsx:affordanceVisibility",
        "The heatmap's mark labels were a `title` tooltip, which on a tablet never appears — a sighted "
        "touch user got the colour and nothing else, which is §27's 'never rely on colour alone' "
        "failing silently. The panel reads the pointer in use and draws the label permanently for "
        "anything that cannot hover, INCLUDING before any pointer has been seen. No single ink clears "
        "4.5:1 across the intensity ramp, so vizPalette.inkForStep picks per step with the "
        "measurements recorded.",
    ),
    _c(
        "a11y.focus_states",
        "27",
        "D",
        "Clear focus states",
        "live",
        "frontend/src/hub/a11yFocus.ts:FOCUS_RING",
        "Declared once and enforced: hub_a11y_guard fails a second declaration, a classed button without "
        "it, and any outline-none without a replacement ring.",
    ),
    # Not named by §27. Both are the mechanism that keeps the rows above true, and
    # a mechanism absent from this registry is one nobody can see has stopped working.
    _c(
        "a11y.contrast_measured",
        "27",
        "D",
        "Text contrast computed, never asserted",
        "live",
        "frontend/src/hub/a11yContrast.ts:contrastRatio",
        "Every palette token is re-measured against every composited surface on each test run, and each "
        "refused colour must still measure what its stated reason says. text-slate-500 shipped on the "
        "overlay because its ratio existed only in the head of whoever chose it.",
    ),
    _c(
        "a11y.contract_enforced",
        "27",
        "D",
        "The accessibility contract is enforced across the directory",
        "live",
        "frontend/src/test/hub_a11y_guard.test.ts",
        "Source-scans hub/ for the five defect shapes found in this session's own work. Each rule was "
        "verified by reintroducing the defect and watching it fail; the hit-target rule follows a style "
        "object spread into a button, because its first version read only the tag and reported clean on "
        "exactly the files where sizes live in a shared const.",
    ),
    _c(
        "a11y.not_colour_alone",
        "27",
        "D",
        "Never rely on colour alone for critical meaning",
        "live",
        "frontend/src/components/ai/GenerationWorkbench.tsx",
        "Every job state has a word as well as a colour.",
    ),
    # §3 — capabilities the specification says exist, which are not in this repo.
    # Tracked as work rather than dropped: that is the whole point of §30.
    _c(
        "legacy.cognitive_stream",
        "23",
        "D",
        "Cognitive stream — user-facing explanation distinct from internal trace",
        "live",
        "frontend/src/hub/cognitiveStream.ts:CognitiveStream",
        "\u00a73 listed this as existing and it was not in this repository. They are "
        "TWO streams and merging them is a leak, not a tidy-up: the trace "
        "carries prompts, tool names, model identifiers and raw tool output, "
        "while the explanation is a sentence for somebody deciding whether to "
        "trust an answer. `forOperator()` returns a shape the trace is not "
        "reachable from, because returning the object and letting the caller "
        "pick fields puts the trace one property access away from a render. A "
        "step with nothing to say reports 'Working.', never the trace \u2014 showing "
        "it because it is the only text available is the leak arriving by "
        "convenience rather than by design. Both lists are bounded and the "
        "number dropped is reported.",
    ),
    _c(
        "legacy.neural_engine",
        "22",
        "C",
        "Neural engine indicator bound to real model state",
        "live",
        "ai.telemetry.neural:neural_engine",
        "\u00a73 listed this as existing and it was not. The tempting version is a "
        "light that pulses whenever the page is open, which is the zero CPU "
        "gauge wearing different clothes \u2014 it would say 'thinking' on a "
        "deployment with no credential configured. Status is derived from three "
        "facts and nothing else: which vendors are reachable, which of their "
        "circuit breakers are open, and whether any call has succeeded. "
        "`last_success_at` stays None rather than becoming 'just now'.",
    ),
    _c(
        "legacy.sleep_monitor",
        "19",
        "C",
        "Sleep monitor bound to the notification policy",
        "live",
        "ai.notify.service:release_deferred",
        "Sleep mode holds non-critical notifications and keeps them; a "
        "sleep-mode deferral has no scheduled end and is released by the "
        "operator, never by a clock guessing at a time nobody set.",
    ),
    _c(
        "legacy.multi_display_console",
        "10",
        "D",
        "Multi-display console",
        "staged",
        "frontend/src/hooks/useAICommandCenter.ts",
        "MEASURED: NINE live sources, each carrying its own loading/ready/degraded state and the "
        "timestamp it was last updated, so one dead feed degrades its own tile instead of the "
        "console. The previous note said six and never said what was MISSING, which is the one note "
        "shape this registry forbids — a note that lists what exists reads as complete. What is "
        "missing is the display half: 'multi-display' means spanning more than one physical screen, "
        "and nothing here calls getScreenDetails or places a window on a second monitor. It is one "
        "console with nine sources, which is not the same claim.",
    ),
    _c(
        "legacy.price_action_visualization",
        "21",
        "D",
        "Price action visualisation",
        "live",
        "frontend/src/features/chart-bot",
        "",
    ),
    # ── Track S — owner request, 2026-09-07 ───────────────────────────
    #
    # An AI that walks all the code including its own, improves the app and
    # itself, stays awake to do it, and is locked away so nobody can use it to
    # change our code. Every advancement approved.
    #
    # Section "S", not a number: these rows are not in the specification, and
    # filing them under §28 would claim the specification asked for them.
    _c(
        "improve.vault",
        "S",
        "C",
        "Paths no AI-originated change may modify, whatever the approval",
        "live",
        "ai.vault.protected:FLOOR",
        "A floor, not a default: configuration adds and can never subtract. It "
        "replaces a list that SelfHealer.apply_config replaced wholesale from a "
        "config field whose Pydantic default is empty \u2014 so the first config save "
        "from the superadmin dashboard erased all thirty protected paths on the "
        "live healer, and risk/manager.py, execution/engine.py, kill_switch.py "
        "and auth/jwt.py became auto-patchable. Reproduced by execution before "
        "the fix. The floor also covers what the AI could use to STOP BEING "
        "STOPPED: the healer that checks patch signatures, the two-approver "
        "policy, the permission registry, the invariants, the guardrails, the "
        "tests, CI, and itself.",
    ),
    _c(
        "improve.path_before_content",
        "S",
        "C",
        "A protected path is refused before its content is read",
        "live",
        "ai.vault.protected:review",
        "Verdict.inspected_content records which happened, so the ordering is "
        "asserted rather than trusted. A content check that ran first could in "
        "principle be talked into a verdict; a path check never reads the "
        "argument carrying the persuasion.",
    ),
    _c(
        "improve.sandbox_target_check",
        "S",
        "C",
        "The repair sandbox refuses a protected target without running anything",
        "live",
        "security.ai_repair_sandbox:validate_repair_for_target",
        "Refused before the source is parsed, written to a disposable directory or executed.",
    ),
    _c(
        "improve.code_walker",
        "S",
        "C",
        "An agent that walks all the code, including the AI's own",
        "live",
        "ai.improve.walker:walk",
        "Deterministic static analysis, not a model call per file: seventeen "
        "hundred files on a loop meant to stay awake is a bill rather than a "
        "capability, and its findings would not be reproducible run to run. The "
        "five checks are this repository's own defect history \u2014 dead_control "
        "(F176/F260), unmeasured_as_zero (\u00a722), float_money, silent_except, "
        "permissive_env_default. Reachable as platform_engineering.walk_code at "
        "READ_ONLY, which is structural: ai/improve imports nothing from "
        "ai/tools and calls nothing that writes, both asserted by parsing the "
        "package. A restricted walk DROPS dead_control and names the drop, "
        "because a caller in a directory never entered is not an absent caller.",
    ),
    _c(
        "improve.finding_to_proposal",
        "S",
        "C",
        "A finding becomes a proposal that two humans must approve",
        "live",
        "ai.improve.proposal:prepare",
        "Five gates in order \u2014 the evidence resolves, the vault by path before "
        "any content is read, the patch changes something, it is under the "
        "64KB ceiling, the disposable-directory sandbox accepts it \u2014 then a "
        "pending record on fixes:queue and nothing further. It cannot sign and "
        "cannot apply: no import of security.self_healer, and the names "
        "_sign_patch, _apply_patch and the applied queue appear nowhere outside "
        "this module's own prose, asserted by parsing rather than grepping. "
        "Two corrections came from running the code: SelfHealer's auto-apply "
        "path is INERT in every configuration, because nothing in the "
        "repository ever signs an entry and all three writers of the applied "
        "queue push unsigned records \u2014 so the live route is a pull request a "
        "human merges, and this phase does not turn auto-apply on. And "
        "api/security/fixes.py:approve_fix, the gate an AI-authored patch "
        "actually passes, took a SINGLE admin while ai/policy/roles.py "
        "declared that a repair needs two approvers including a superadmin. "
        "That rule now lives in one place and both callers use it.",
    ),
    _c(
        "improve.always_awake",
        "S",
        "C",
        "A continuous improvement cycle with a budget, a rate limit and a kill switch",
        "live",
        "ai.improve.cycle:run_forever",
        "Bounded four ways. OFF unless AI_IMPROVE_CYCLE_HOURS is a positive "
        "number \u2014 unset, empty, zero, negative, infinite and unparseable all "
        "mean off, because a typo read as 'run continuously' is the worst "
        "available reading of a mistake. A Redis kill switch stops it with no "
        "deploy, and an UNREADABLE switch also stops it: the one place in this "
        "package where unavailable means refuse rather than report, because a "
        "loop that spends money and answers 'no halt found' to a connection "
        "error has turned its kill switch into a suggestion. The shared budget "
        "ceiling is consulted first, against the cycle's own operator so the "
        "spend is attributable. Three proposals per cycle, ordered by severity "
        "\u2014 the walker finds ~1,300 things and filing them all turns a "
        "two-person review queue into noise. Wired by "
        "init_ai_improvement_cycle; the loop sleeps FIRST, so a crash-looping "
        "deployment is not a bill.",
    ),
    _c(
        "improve.honest_cycle_report",
        "S",
        "C",
        "A cycle that proposed nothing says so, with the reason",
        "live",
        "ai.improve.cycle:CycleReport",
        "`reason` is populated whether or not the cycle ran, and every refusal "
        "is named with the evidence it belongs to. Silence from a "
        "self-improving system reads as 'nothing is wrong', which is the same "
        "defect as a gauge showing zero because its probe failed. A finding on "
        "a protected path is still REPORTED and never sent to the generator: "
        "paying a model to write a patch that cannot be applied is money for "
        "nothing.",
    ),
    # ── Track P — owner request, 2026-09-07 ──────────────────────────
    #
    # The presence available on every screen, able to diagnose the page around
    # it, move around it, and act on it. Not a specification section: filing
    # these under a number would claim the specification asked for them.
    _c(
        "presence.page_context",
        "P",
        "A",
        "The presence knows what page it is on and what is wrong with it",
        "live",
        "frontend/src/hub/pageContext.ts:describePage",
        "Derived from NAV_ITEMS, the app's own single source of truth for "
        "routes \u2014 a hand-written per-page table would be correct on the day it "
        "was written and wrong by the next release. An unknown route reports "
        "known: false with the path, because falling back to the nearest page "
        "would have the AI confidently describing a screen the operator is not "
        "looking at. `inspected` is separate from `problems`, so a page with no "
        "landmarks reported cannot be read as a healthy one \u2014 \u00a722's rule "
        "applied to the page rather than to a gauge.",
    ),
    _c(
        "presence.dock",
        "P",
        "A",
        "The presence sits where it helps and never blocks",
        "live",
        "frontend/src/hub/presenceDock.ts:dockFor",
        "Everywhere but the AI Core page the presence is a guest on somebody "
        "else's screen, one of them the order ticket. It tries each corner and "
        "takes the first that collides with nothing the operator is using; when "
        "every corner collides it REPORTS the overlap rather than quietly "
        "sitting on a form somebody is filling in. Never a keyboard trap "
        "(trapsFocus is a field, so a test can assert it). Dismissal survives "
        "navigation \u2014 a presence that returns on the next route change was "
        "delayed, not dismissed. Narrow viewports get an edge bar, the only "
        "arrangement that cannot cover content. Transform and opacity only.",
    ),
    _c(
        "presence.page_capabilities",
        "P",
        "A",
        "What the AI may read here, and what it may request here, never merged",
        "live",
        "frontend/src/hub/pageCapabilities.ts:pageCapabilities",
        "Two fields and deliberately no combined one: a caller handed a single "
        "list would reasonably conclude everything on it can be done. The same "
        "discipline as ai/agent/loop.py's permitted/platform_context split and "
        "app_surface's visible/invokable pair, arriving at the page level. A "
        "write with no registered tool is listed as UNAVAILABLE with the "
        "reason, not filtered out \u2014 'the AI cannot do this' and 'this does not "
        "exist' are different answers to an operator asking why nothing "
        "happened. The gate itself is unchanged: anything that acts still "
        "passes ai/tools/bus.py with an authenticated operator, so a presence "
        "overlay cannot become a second way to place a trade.",
    ),
    _c(
        "presence.overlay",
        "P",
        "A",
        "The presence rendered on every screen in the app",
        "live",
        "frontend/src/hub/PresenceAnywhere.tsx:PresenceAnywhere",
        "Owner approved it on 2026-09-07, after this row sat planned pending "
        "that approval \u2014 flow-by-flow requires explicit sign-off before a major "
        "UI change, and 'no post-hoc approval'. It introduces NO new visual "
        "language: PresenceCore already draws the presence, presenceDock "
        "already decides where a floating element may sit, pageContext and "
        "pageCapabilities already decide what it knows and may do. Mounted in "
        "App.tsx behind isAuth, asserted \u2014 a component nobody renders is the "
        "defect this codebase keeps finding. Absent on /ai-core, which is "
        "already a presence. Never aria-modal and never a focus trap, on a "
        "platform where the page behind it places trades. Dismissal persists "
        "across navigation, EXCEPT for an alerting presence: dismissing an "
        "assistant is not consent to be uninformed about a kill switch. One "
        "live region, not two \u2014 a second polite region here announced on every "
        "navigation and spoke over PresenceCore's.",
    ),
    _c(
        "improve.patch_generator",
        "S",
        "C",
        "A model authoring candidate patches, behind its own switch",
        "live",
        "ai.improve.patcher:GatewayPatcher",
        "Owner decision, 2026-09-07, taken separately from turning the schedule "
        "on, because those are two decisions. AI_IMPROVE_PATCHER is its own "
        "variable and off by default; a typo fails towards DISABLED. The model "
        "gains the ability to write a suggestion and nothing else: what comes "
        "back passes the same five gates in ai/improve/proposal.py and needs the "
        "same two approvers, one a superadmin. Both directions are untrusted \u2014 "
        "the whole file and the snippet are fenced separately on the way in, "
        "and scan_output runs on the way out BEFORE the text is returned, so a "
        "model echoing a credential out of the file it read cannot put it in a "
        "queue entry. A file too large to send is REFUSED, never truncated: "
        "truncating asks a model to rewrite a file it only half saw, and the "
        "answer would look complete. Prose, unparseable code, an unchanged "
        "file, a gateway failure and a guardrail refusal are each recorded "
        "against the finding \u2014 a finding that quietly vanished looks exactly "
        "like a finding that was fixed.",
    ),
)


def _rollup(layer: str) -> Capability:
    """One §4 roll-up, rebuilt from what its layer measures.

    The note NAMES what is outstanding rather than saying "not finished". A
    roll-up that reports `staged` with no list is a number somebody has to go
    and investigate, which is how a stale claim survives — the whole reason
    `agents.system` sat live on another agent's module for as long as it did.
    """
    rollup = next(c for c in _DECLARED if c.id in ROLLUP_IDS and c.layer == layer)
    rows = [c for c in _DECLARED if c.layer == layer and c.id not in ROLLUP_IDS]
    state = layer_state(layer, rows=rows)
    outstanding = [c.id for c in rows if c.state != "live"]

    if state == "live":
        note = f"Derived: all {len(rows)} rows in layer {layer} are live."
        evidence = "ai.hub.capabilities:layer_state"
    elif state == "planned":
        note = f"Derived: nothing in layer {layer} has been started."
        # No evidence for a layer nothing has begun. A pointer to the
        # derivation would resolve and mean nothing.
        evidence = ""
    else:
        note = (
            f"Derived: {len(rows) - len(outstanding)} of {len(rows)} rows in layer {layer} are live. "
            f"Outstanding — {', '.join(outstanding)}."
        )
        evidence = "ai.hub.capabilities:layer_state"

    return Capability(
        id=rollup.id,
        section=rollup.section,
        layer=rollup.layer,
        title=rollup.title,
        state=state,
        evidence=evidence,
        note=note,
    )


#: The registry as it is read everywhere else: the declared rows, with §4's
#: four roll-ups replaced by what their layers actually measure.
#:
#: Built rather than typed because a roll-up is a claim about other claims, and
#: this file exists to stop exactly that kind of claim going unmeasured.
REGISTRY: Final[tuple[Capability, ...]] = tuple(_rollup(c.layer) if c.id in ROLLUP_IDS else c for c in _DECLARED)


# ── verification ──────────────────────────────────────────────────────────────


def verify_one(cap: Capability) -> Discrepancy | None:
    """Resolve one capability's evidence. Returns a Discrepancy, or None if sound.

    Three locator shapes, checked in order of specificity:

    * `package.module:Attribute` — the module must import AND carry the symbol.
      Checking only the module would pass a file whose contents were deleted.
    * `package.module` — the module must import.
    * `path/to/file` — the file must exist, for evidence that is not Python.
    * `path/to/file:Symbol` — the file must exist AND name the symbol. The
      TypeScript half of this platform had no equivalent of the attribute check
      until a capability tried to cite `hub/layout.ts:LAYOUTS` and the verifier
      read the whole locator as a filename. Silently accepting a file whose
      export was renamed is exactly the kind of green this registry exists to
      refuse.
    """
    if cap.state == "planned":
        return Discrepancy(cap.id, "planned capabilities carry no evidence") if cap.evidence else None
    if not cap.evidence:
        return Discrepancy(cap.id, f"state is {cap.state!r} with no evidence to check")

    locator = cap.evidence
    head, _, tail = locator.partition(":")
    if "/" in head or head.endswith((".ts", ".tsx", ".css", ".py", ".json")):
        target = _ROOT / head
        if not target.exists():
            return Discrepancy(cap.id, f"file does not exist: {head}")
        if not tail:
            return None
        if target.is_dir():
            return Discrepancy(cap.id, f"{head} is a directory; a symbol cannot be checked against it")
        try:
            body = target.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            return Discrepancy(cap.id, f"cannot read {head}: {exc}")
        # Word-boundary, so `LAYOUTS` does not match `DEFAULT_LAYOUTS_LEGACY`.
        if not re.search(rf"\b{re.escape(tail)}\b", body):
            return Discrepancy(cap.id, f"{head} does not name {tail}")
        return None

    module_name, _, attribute = locator.partition(":")
    try:
        module = importlib.import_module(module_name)
    except Exception as exc:  # an unimportable module is not evidence of anything
        return Discrepancy(cap.id, f"cannot import {module_name}: {type(exc).__name__}: {exc}")
    if attribute and not hasattr(module, attribute):
        return Discrepancy(cap.id, f"{module_name} has no attribute {attribute}")
    return None


def verify(registry: tuple[Capability, ...] | None = None) -> VerificationReport:
    """Resolve every claim in the registry. This is a measurement, not a report.

    Importing modules is the point: a registry that only reads its own literals
    is `scripts/invariant_coverage.py` before F176, which could not print
    anything but success.
    """
    caps = registry if registry is not None else REGISTRY
    checked = 0
    resolved = 0
    problems: list[Discrepancy] = []
    for cap in caps:
        if cap.state == "planned" and not cap.evidence:
            continue
        checked += 1
        problem = verify_one(cap)
        if problem is None:
            resolved += 1
        else:
            problems.append(problem)
    return VerificationReport(checked=checked, resolved=resolved, discrepancies=tuple(problems))


def coverage() -> dict[str, Any]:
    """What the specification asks for, and how much of it is real.

    `verified` is reported separately from `live` on purpose: one is what the
    registry was TOLD, the other is what was MEASURED. Collapsing them is the
    defect F176 records.
    """
    report = verify()
    counts = {state: sum(1 for c in REGISTRY if c.state == state) for state in ("live", "staged", "planned")}
    return {
        "total": len(REGISTRY),
        **counts,
        "verified": report.resolved,
        "checked": report.checked,
        "discrepancies": [{"id": d.id, "detail": d.detail} for d in report.discrepancies],
        "sections": sorted({c.section for c in REGISTRY}, key=_section_order),
    }


def _section_order(section: str) -> tuple[int, str]:
    """Specification sections sort numerically; owner-requested tracks after them.

    §4-§27 come from the specification. A capability the owner asked for that
    the specification never named carries a letter, because filing it under a
    number would claim the specification required it.
    """
    return (0, f"{int(section):03d}") if section.isdigit() else (1, section)


def by_section(section: str) -> tuple[Capability, ...]:
    return tuple(c for c in REGISTRY if c.section == section)


def by_state(state: State) -> tuple[Capability, ...]:
    return tuple(c for c in REGISTRY if c.state == state)


__all__ = [
    "REGISTRY",
    "STATES",
    "Capability",
    "Discrepancy",
    "VerificationReport",
    "by_section",
    "by_state",
    "coverage",
    "verify",
    "verify_one",
]
