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

REGISTRY: Final[tuple[Capability, ...]] = (
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
    # §5 — AI Core and personality
    _c("core.context_across_tasks", "5", "B", "Maintain conversation context across active tasks"),
    _c("core.interruptible_speech", "5", "A", "Permit interruption while speaking"),
    _c("core.adaptive_depth", "5", "B", "Adapt explanation depth without changing the intelligence"),
    _c(
        "core.states_uncertainty",
        "5",
        "B",
        "State uncertainty honestly",
        "staged",
        "ai.guardrails.output:bounded_severity",
        "Bounded severity exists; calibrated uncertainty does not.",
    ),
    _c("core.challenges_assumptions", "5", "B", "Challenge weak assumptions and present counterarguments"),
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
    _c("modes.registry", "6", "D", "Presentation mode registry"),
    _c("modes.professional_core", "6", "D", "Default professional core mode"),
    _c("modes.market_analyst", "6", "D", "Market analyst mode"),
    _c("modes.research_scientist", "6", "D", "Research scientist mode"),
    _c("modes.engineering", "6", "D", "Engineering / developer mode"),
    _c("modes.teaching", "6", "D", "Teaching mode"),
    _c("modes.executive_briefing", "6", "D", "Executive briefing mode"),
    _c("modes.mission_control", "6", "D", "High-density mission control mode"),
    _c("modes.minimal_focus", "6", "D", "Minimal focus mode"),
    _c("modes.emergency", "6", "D", "Emergency / critical alert mode"),
    _c("modes.child_simple", "6", "D", "Child-simple explanation mode"),
    # §7 — Holographic presence system
    _c("presence.head", "7", "A", "Professional holographic head as the default presence"),
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
    _c("presence.idle_attention", "7", "A", "Natural idle movement and attention states"),
    _c("presence.animation_states", "7", "A", "Listening, thinking, working, speaking, explaining, alerting"),
    _c("presence.lip_sync", "7", "A", "Lip synchronisation where the voice pipeline supports it"),
    _c(
        "presence.particle_field",
        "7",
        "A",
        "Particle field, used with restraint",
        note="§3 lists this as existing; it is not in this repository. Tracked as work.",
    ),
    _c("presence.spatial_movement", "7", "A", "Move toward the panel being discussed"),
    _c("presence.gestures", "7", "A", "Pointing, highlighting and gesture overlays"),
    _c("presence.multi_projection", "7", "A", "Minimise, reposition, or split into multiple projections"),
    _c("presence.transformations", "7", "A", "Contextual transformation into scientific representations"),
    _c("presence.xr_abstraction", "7", "A", "Renderer abstraction for 3D, AR, VR and holographic output"),
    # §8 — Dynamic generative workspace engine
    _c("workspace.engine", "8", "D", "Generate, update, rearrange and remove surfaces from intent"),
    _c(
        "workspace.surface_types",
        "8",
        "D",
        "Charts, images, video, documents, tables, maps, terminals, code, camera, news, research, simulations",
    ),
    _c("workspace.concurrent_surfaces", "8", "D", "1-20+ concurrent surfaces subject to device capacity"),
    _c("workspace.priority_tiers", "8", "D", "Critical, primary, secondary, background, on-demand tiers"),
    _c("workspace.auto_layout", "8", "D", "Choose layout from task, viewport, object count and attention"),
    _c("workspace.pinning", "8", "D", "Pin a surface so it stays visible"),
    _c("workspace.layouts", "8", "D", "Focus, compare, split, timeline, war-room, presentation layouts"),
    _c("workspace.nl_commands", "8", "D", "Natural-language workspace commands"),
    _c("workspace.history_snapshots", "8", "D", "Workspace history and named snapshots"),
    _c("workspace.graceful_degrade", "8", "D", "Degrade on small devices rather than failing"),
    # §9 — Spatial AI interaction
    _c("spatial.scene_model", "9", "D", "Scene model — identity, position, size, z-order, content, meaning"),
    _c("spatial.panel_registry", "9", "D", "Semantic panel registry"),
    _c("spatial.viewport_awareness", "9", "D", "Coordinate and viewport awareness"),
    _c("spatial.target_highlight", "9", "D", "Target highlighting"),
    _c("spatial.focus_transitions", "9", "D", "Animated focus transitions"),
    _c("spatial.zoom_regions", "9", "D", "Zoom into data regions"),
    _c("spatial.layer_navigation", "9", "D", "Layer navigation and breadcrumbs"),
    _c("spatial.speech_sync", "9", "A", "Speech references synchronised with visual focus"),
    # §10 — Multi-display and cognitive load
    _c("load.dominant_placement", "10", "D", "Critical information receives dominant placement"),
    _c("load.explained_focus", "10", "D", "What is being explained receives visual focus"),
    _c("load.background_collapse", "10", "D", "Background information collapses into stacks or summaries"),
    _c("load.cross_surface_summary", "10", "B", "Summarise across surfaces and name relationships"),
    _c("load.user_override", "10", "D", "User can override AI layout decisions"),
    # §11 — Multi-agent intelligence network
    _c(
        "agents.orchestrator",
        "11",
        "C",
        "Orchestrator — decompose, allocate, track, merge, resolve",
        "staged",
        "ai.agent.loop",
        "A sequential loop exists; a task graph does not.",
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
        "ai.departments.platform_engineering",
        "",
    ),
    _c("agents.news", "11", "C", "News intelligence agent"),
    _c(
        "agents.vision",
        "11",
        "C",
        "Vision agent",
        "staged",
        "ai.vision.detect:interpret",
        "Interpretation exists; it is not yet an agent on the bus.",
    ),
    _c("agents.voice", "11", "C", "Voice agent — recognition, synthesis, turn management"),
    _c(
        "agents.memory",
        "11",
        "C",
        "Memory agent — retrieval, consolidation, governance",
        "staged",
        "ai.memory.store",
        "A store exists; an agent that governs it does not.",
    ),
    _c("agents.notification", "11", "C", "Notification agent — severity, escalation, interruption"),
    _c("agents.data", "11", "C", "Data agent — acquisition, validation, freshness"),
    _c("agents.development", "11", "C", "Development agent — code, debugging, architecture"),
    # §12 — Agent-to-agent communication
    _c(
        "bus.message_envelope",
        "12",
        "C",
        "Typed message — task id, correlation id, priority, status, confidence, evidence, expiry",
    ),
    _c("bus.pubsub", "12", "C", "Publish/subscribe event bus"),
    _c("bus.lifecycle_events", "12", "C", "Task lifecycle events"),
    _c(
        "bus.streaming_partials",
        "12",
        "C",
        "Streaming partial results",
        "staged",
        "ai.gateway.client:GatewayClient",
        "The gateway streams; the bus does not exist yet.",
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
    _c("bus.task_graph", "12", "C", "Task graph rather than a sequential queue"),
    # §13 — Debate and conflict resolution
    _c("debate.opposing_perspectives", "13", "C", "Invoke opposing perspectives for high-value decisions"),
    _c("debate.no_forced_consensus", "13", "C", "Do not force artificial consensus"),
    _c("debate.record_claims", "13", "C", "Record competing claims and evidence"),
    _c("debate.evidence_weighting", "13", "C", "Weight evidence by quality and freshness"),
    _c(
        "debate.calibration",
        "13",
        "C",
        "Track agent calibration and historical reliability",
        "staged",
        "ai.evals.suite:run_suite",
        "The scoring mechanism exists; per-agent calibration does not.",
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
    _c("parallel.event_triggered", "14", "C", "Event-triggered tasks"),
    _c("parallel.long_running", "14", "C", "Long-running research jobs"),
    _c("parallel.streaming_progress", "14", "C", "Streaming task progress", "live", "ai.jobs.progress:publish", ""),
    _c("parallel.budgets", "14", "C", "Cancellation and resource budgets", "live", "ai.gateway.budget:check", ""),
    _c(
        "parallel.priority_queues",
        "14",
        "C",
        "Concurrency limits and priority queues",
        "staged",
        "ai.jobs.runner:DEFAULT_MAX_CONCURRENT",
        "Limits exist; priority queues do not.",
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
    _c("reason.thesis", "15", "B", "State the thesis"),
    _c("reason.counter_thesis", "15", "B", "State the counter-thesis"),
    _c("reason.evidence", "15", "B", "Show key evidence"),
    _c("reason.assumptions", "15", "B", "Identify assumptions"),
    _c("reason.missing_information", "15", "B", "Identify missing information"),
    _c("reason.confidence", "15", "B", "Calibrated confidence where possible"),
    _c("reason.what_would_change_it", "15", "B", "Explain what would change the conclusion"),
    _c("reason.risk_alternatives", "15", "B", "Provide risk and alternative actions"),
    # §16 — Memory and knowledge
    _c("memory.working", "16", "B", "Working memory for the current turn"),
    _c("memory.session", "16", "B", "Session memory"),
    _c("memory.project", "16", "B", "Project memory for long-running work", "live", "ai.memory.store", ""),
    _c(
        "memory.long_term",
        "16",
        "B",
        "Long-term memory for approved persistent facts",
        "staged",
        "ai.memory.sql_backend",
        "Durable storage exists; approval governance does not.",
    ),
    _c("memory.episodic", "16", "B", "Episodic memory for significant events"),
    _c("memory.knowledge_graph", "16", "B", "Knowledge graph across entities, projects, tasks"),
    _c("memory.provenance", "16", "B", "Memory provenance and timestamps", "staged", "ai.memory.store", ""),
    _c("memory.user_controls", "16", "B", "User review, correction and deletion"),
    # §17 — Voice and real-time conversation
    _c(
        "voice.streaming_stt",
        "17",
        "A",
        "Low-latency streaming speech recognition",
        "staged",
        "frontend/src/hooks/useVoice.ts",
        "Recognition exists; it is not low-latency streaming.",
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
    _c("voice.interruptible", "17", "A", "Interruptible responses and barge-in"),
    _c(
        "voice.push_to_talk",
        "17",
        "A",
        "Push-to-talk and optional continuous conversation",
        "staged",
        "frontend/src/hooks/useVoice.ts",
        "",
    ),
    _c("voice.wake_word", "17", "A", "Wake word where privacy-appropriate"),
    _c("voice.pronunciation", "17", "A", "Pronunciation dictionary for names and financial terms"),
    _c("voice.turn_detection", "17", "A", "Turn detection"),
    _c("voice.preferences", "17", "A", "Adjustable speech speed and voice preference"),
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
    _c("vision.gesture", "18", "A", "Gesture recognition"),
    _c("vision.pointing", "18", "A", "Pointing and object reference"),
    _c("vision.attention_aware", "18", "A", "Optional attention-aware interaction"),
    _c("vision.source_selection", "18", "A", "Screen and camera source selection"),
    _c("vision.local_processing", "18", "C", "Local processing where feasible"),
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
    _c("monitor.user_watches", "19", "C", "User-defined watches and thresholds"),
    _c(
        "monitor.health_watchers",
        "19",
        "C",
        "Market, system, data and agent health monitoring",
        "live",
        "ai.awareness.watchers",
        "Watchers raise a proposal and never act.",
    ),
    _c("monitor.severity", "19", "C", "Four notification severities"),
    _c("monitor.quiet_hours", "19", "C", "Quiet hours and sleep mode"),
    _c("monitor.escalation", "19", "C", "Escalation rules"),
    _c("monitor.alarm_scheduling", "19", "C", "Alarm scheduling"),
    _c("monitor.wake_conditions", "19", "C", "User-configured wake-up conditions"),
    _c("monitor.dedup", "19", "C", "Notification deduplication and anti-spam"),
    _c("monitor.explain_interruption", "19", "C", "Explain why an interruption occurred"),
    # §20 — Trading and HOPEFX integration
    _c("trading.mode_awareness", "20", "C", "Live and paper trading awareness", "live", "api.safe_agent_platform", ""),
    _c("trading.independent_risk", "20", "C", "Independent risk agent", "live", "ai.departments.risk_compliance", ""),
    _c("trading.war_room", "20", "D", "Market war room generated on demand"),
    _c("trading.thesis_counter", "20", "B", "Trade thesis and counter-thesis"),
    _c("trading.correlation", "20", "B", "News, macro, technical and microstructure correlation"),
    _c("trading.kill_switch_awareness", "20", "C", "Risk limits and kill-switch awareness", "live", "risk.manager", ""),
    _c("trading.explainability", "20", "B", "Explainability for AI-generated trade analysis"),
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
    _c("viz.heatmap", "21", "D", "Heatmaps for intensity"),
    _c("viz.network_graph", "21", "D", "Network graphs for relationships"),
    _c("viz.timeline", "21", "D", "Timelines for chronology"),
    _c("viz.distributions", "21", "D", "Probability distributions for uncertainty"),
    _c("viz.tables", "21", "D", "Tables for precise comparison"),
    _c("viz.scientific_3d", "21", "D", "3D and scientific models where they aid understanding"),
    _c("viz.media_panels", "21", "D", "Video and image panels"),
    _c("viz.drill_down", "21", "D", "Interactive drill-down"),
    _c("viz.selection_intelligence", "21", "B", "Choose the representation that suits the information"),
    # §22 — Real system monitoring
    _c(
        "telemetry.host",
        "22",
        "C",
        "GPU, CPU and memory telemetry",
        note="§3 lists this as existing; it is not in this repository.",
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
    _c("telemetry.agent_health", "22", "C", "Agent health"),
    _c("telemetry.model_availability", "22", "C", "Model availability", "live", "ai.gateway.breakers", ""),
    _c("telemetry.data_freshness", "22", "C", "Data freshness", "live", "data_layer.orchestrator", ""),
    _c("telemetry.security_events", "22", "C", "Security events"),
    _c("telemetry.spend", "22", "C", "Cost and spend ceilings", "live", "ai.gateway.budget", ""),
    _c(
        "telemetry.no_decorative_values",
        "22",
        "C",
        "No fake live values in production",
        "staged",
        "api.ai_core",
        "The durability block reports what is real; host metrics are still absent.",
    ),
    # §23 — Dynamic UI architecture
    _c("ui.component_registry", "23", "D", "Component registry for renderable surface types"),
    _c("ui.schema_driven_panels", "23", "D", "Schema-driven panel generation"),
    _c("ui.layout_engine", "23", "D", "Layout engine independent of content"),
    _c("ui.animation_engine", "23", "A", "Animation engine independent of business logic"),
    _c("ui.scene_graph", "23", "D", "Scene graph for spatial awareness"),
    _c("ui.workspace_store", "23", "D", "State store for workspace sessions"),
    _c(
        "ui.event_streaming",
        "23",
        "D",
        "WebSocket event streaming for live updates",
        "live",
        "api.ws_live",
        "15 typed channels with a private-channel rule.",
    ),
    _c("ui.virtualization", "23", "D", "Virtualisation for high-density displays"),
    _c("ui.frame_protection", "23", "A", "Resource-aware rendering and frame-rate protection"),
    _c(
        "ui.accessibility",
        "23",
        "D",
        "Accessibility and reduced-motion support",
        "staged",
        "frontend/src/index.css",
        "Present in places; must hold for generated panels too.",
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
        "ai.jobs.runner",
        "A bounded pool exists; isolated workers do not.",
    ),
    _c("stack.event_bus", "24", "C", "Event bus — Redis streams or equivalent"),
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
        "staged",
        "frontend/src/components/intelligence/VisualIntelligenceWorkspaces.tsx",
        "Camera is gated; memory and microphone controls are not centralised.",
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
    _c("perf.large_workspaces", "26", "D", "Render large workspaces efficiently"),
    _c("perf.reduce_animation_under_load", "26", "A", "Pause or reduce animation under load"),
    _c(
        "perf.degraded_states",
        "26",
        "D",
        "Graceful offline and degraded states",
        "staged",
        "frontend/src/hooks/useWebSocket.ts",
        "Stale-feed detection exists.",
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
    _c("a11y.keyboard", "27", "D", "Keyboard navigation"),
    _c("a11y.screen_reader", "27", "D", "Screen-reader semantics"),
    _c("a11y.captions", "27", "A", "Captions and transcripts for voice"),
    _c("a11y.reduced_motion", "27", "A", "Reduced motion mode", "staged", "frontend/src/index.css", ""),
    _c("a11y.high_contrast", "27", "D", "High contrast option"),
    _c("a11y.responsive", "27", "D", "Responsive layouts", "staged", "frontend/src/index.css", ""),
    _c("a11y.touch_and_mouse", "27", "D", "Touch and mouse support"),
    _c("a11y.focus_states", "27", "D", "Clear focus states"),
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
        note="§3 lists this as existing; it is not in this repository.",
    ),
    _c(
        "legacy.neural_engine",
        "22",
        "C",
        "Neural engine indicator bound to real model state",
        note="§3 lists this as existing; it is not in this repository.",
    ),
    _c(
        "legacy.sleep_monitor",
        "19",
        "C",
        "Sleep monitor bound to the notification policy",
        note="§3 lists this as existing; it is not in this repository.",
    ),
    _c(
        "legacy.multi_display_console",
        "10",
        "D",
        "Multi-display console",
        "staged",
        "frontend/src/hooks/useAICommandCenter.ts",
        "Six live sources with degraded-source tracking.",
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
)


# ── verification ──────────────────────────────────────────────────────────────


def verify_one(cap: Capability) -> Discrepancy | None:
    """Resolve one capability's evidence. Returns a Discrepancy, or None if sound.

    Three locator shapes, checked in order of specificity:

    * `package.module:Attribute` — the module must import AND carry the symbol.
      Checking only the module would pass a file whose contents were deleted.
    * `package.module` — the module must import.
    * `path/to/file` — the file must exist, for evidence that is not Python.
    """
    if cap.state == "planned":
        return Discrepancy(cap.id, "planned capabilities carry no evidence") if cap.evidence else None
    if not cap.evidence:
        return Discrepancy(cap.id, f"state is {cap.state!r} with no evidence to check")

    locator = cap.evidence
    if "/" in locator or locator.endswith((".ts", ".tsx", ".css", ".py", ".json")):
        if not (_ROOT / locator).exists():
            return Discrepancy(cap.id, f"file does not exist: {locator}")
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
        "sections": sorted({c.section for c in REGISTRY}, key=int),
    }


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
