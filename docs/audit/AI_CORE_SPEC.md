# HOPEFX AI Core — Full Build Spec (as supplied)

**Recorded verbatim in substance on 2026-08-23 so the specification survives
outside chat.** Analysis, prerequisites and audit cross-references live
separately in `AI_CORE_SPEC_INTAKE.md`. This file is the source of truth for
*what was asked for*; that file is *what the audit says about it*.

Figma prototype: https://www.figma.com/design/TmdTVOynTywweydCaWlEWg

---

## 1. Origin and the central contradiction

Original ask: a superadmin AI page with "cloud-like consciousness" depth,
premium visualization beyond existing AI products, its own sandbox, teams of
specialised agents, full independence from external APIs — while generating
code, ideas and creative output at Claude-level capability.

Two requirements contradict:
* Claude-level generation requires a hosted API and a key.
* "No API keys" only holds for a self-hosted open-weight model, which is real
  but far less capable.

**Resolution: hybrid hosting.** A local model on the VPS for routine, private,
zero-marginal-cost work; an external API as an *additional, optional* tier for
heavier generation. Neither replaces the other.

**Restored requirement:** *customizable settings* — user/superadmin
configuration of interface and behaviour (theme, department visibility,
notification thresholds, default autonomy per department). Distinct from the
per-action autonomy dial. Dropped in later drafts; belongs back in.

## 2. Architecture spine

**Core principle:** every department can *recommend*. Nothing places a trade,
deploys code, rotates a credential or changes a setting without passing the
superadmin approval queue. A kill switch halts every agent instantly regardless
of what they are mid-task doing.

**Sandbox:** isolated per-session execution where agents run code, test
strategies or draft fixes without touching production.

**Four-part anatomy** (from MAL19INDUSTRIES/JARVIS-OS-V.2 — a small
single-maintainer repo, structure reused, not scale), applied to every
department:
* `agent/` — who is doing the reasoning
* `actions/` — what it is allowed to call
* `memory/` — what it persists
* `awareness/` — what it watches for on its own

**System spine** (ibraviz.ai JARVIS OS build, 6 Aug):

| Part | Role | HOPEFX mapping |
|---|---|---|
| Claude Code | routes every request to the right skill | **AI Core orchestrator** |
| Obsidian | everything lands as linked markdown | **Vault** — audit history, decision log, incident memory |
| Local voice | STT in, TTS out, audio never leaves the machine | **Local Voice** — voiceprint superadmin auth |
| One HUD | one screen, no tabs | **AI Core page** |

**Daily loop:** 7:00 morning brief · 9:00 plan today · 14:00 metrics pull ·
19:00 close the day · ask-anything at any time. Mapped to the superadmin daily
brief with HOPEFX content — platform health, market conditions, pending
approvals, security alerts.

## 3. The nine engineering concepts — current standing

| # | Concept | Standing | Upgrade required |
|---|---|---|---|
| 1 | **Agentic loops** | implicit only | wire Think → Execute → Monitor → Improve explicitly per department |
| 2 | **MCP** | partial | one internal MCP-style tool bus; wire a tool once, every department uses it |
| 3 | **Subagents / multi-agent** | mostly there | add a synthesis stage so the queue gets one coherent recommendation, not disconnected proposals |
| 4 | **AI Gateway** | missing | explicit layer between AI Core and both model tiers — auth, request logging, rate limits |
| 5 | **Inference economics** | missing | response cache in front of the gateway; repeated queries stop hitting the paid tier |
| 6 | **Evals** | loose | hard gate: test inputs → response → evaluation → pass/fail → metrics, before sandbox→live promotion |
| 7 | **Guardrails** | partial | make input validation and output screening literal, named, auditable stages |
| 8 | **Observability** | **already correct** | — |
| 9 | **The Bitter Lesson** | needs a stated exception | prefer general reasoning **except compliance-critical paths**: drawdown limits and prop-firm rules stay hard-coded. An adaptive risk rule is a liability. |

**Net: 5 of 9 need real architectural work, 1 needs formalising, 1 needs a
merge step, 1 already matches, 1 needs an exception.**

## 4. Department directory — two clusters, one AI Core

### Cluster A — Trading Core

**Markets & Execution** — *watch: OANDA disconnected*
`agent`: Execution Agent, Broker Liaison ·
`actions`: `place_order()`, `cancel_order()`, `sync_positions()`, `query_broker_status()` ·
`memory`: execution/fill history, slippage per symbol, last broker heartbeat ·
`awareness`: broker disconnect detection, orphaned-order flagging

**Risk & Compliance** — *active*
`agent`: Compliance Guard, Risk Monitor ·
`actions`: `check_drawdown()`, `validate_position_size()`, `block_deploy()`, `propose_derisk()` ·
`memory`: rule-set per prop firm, drawdown curve, past violations ·
`awareness`: live exposure vs rules, volatility-regime shift

**Research & Intelligence** — *active*
`agent`: Model Analyst, Research Scout ·
`actions`: `run_backtest()`, `fetch_market_news()`, `score_regime()`, `walk_forward_validate()` ·
`memory`: model version history, OOS accuracy log (59.9% on 50y gold), regime history ·
`awareness`: strategy drift vs trained regime, confidence calibration

**Platform Engineering** — *reviewing: credential rotation pending*
`agent`: Code Auditor, Deploy Sentinel ·
`actions`: `scan_secrets()`, `run_tests()`, `propose_fix()`, `check_broken_imports()` ·
`memory`: audit history (V19→V34), bug registry, dead execution paths ·
`awareness`: commits touching security-sensitive files, CI failure patterns

### Cluster B — Business Operations

| Department | Skills | Memory | Awareness |
|---|---|---|---|
| **Design** | `frontend-design`, `web-artifacts`, `dashboard-builder`, `algorithmic-art`, `brand-system`, `viz-generator` | design tokens, shipped screens, brand doc | flags templated output before it ships |
| **Marketing & Content** | `seo-audit`, `ai-search-ranking`, `ad-creative`, `content-strategy`, `email-sequences`, `market-psychology` | keyword/content calendar, campaign performance | ranking drift, competitor moves |
| **Social & Comms** | `social-posts`, `video-scripts`, `copywriting`, `pillar-content`, `investor-updates`, `press-response` | posting history, brand voice | engagement shifts, sentiment spikes |
| **Corporate Finance** | `dcf-model`, `pitch-deck`, `pricing-strategy`, `comps-analysis`, `runway-forecast`, `cap-table` | model versions, investor materials | runway thresholds, pricing impact |
| **Legal** | `contract-review`, `nda-triage`, `ip-protection`, `regulatory-tracking`, `docx-redline`, `data-privacy` | contract log, jurisdictional rules (Flutterwave/Paystack) | regulatory changes, renewals |
| **Client & Operations** | `sop-builder`, `incident-postmortem`, `support-triage`, `tenant-provisioning`, `internal-comms`, `payment-reconciliation` | tenant config, ticket history | churn signals, reconciliation gaps |

*"Growth & Business Intelligence" was folded into Marketing & Content and
Corporate Finance rather than kept as an empty placeholder. The reference
material's "Developers" crew maps onto Platform Engineering rather than
duplicating it. Some Business Ops skill names are verbatim from the reference,
others adapted — not an exact reproduction.*

## 5. Generative media

* **3D humanoid avatar** — rigged avatar (Ready Player Me or custom GLTF) in
  Three.js, driven by a TTS track (ElevenLabs or self-hosted) with real-time
  viseme/lip-sync. Not synthesised per request.
* **Image generation** — external API, or self-hosted SDXL on the VPS GPU if it
  must stay key-free. Self-hosted needs real GPU headroom (§8).
* **Video / "display movie"** — explicitly **phase 2**. Current models are slow
  and expensive even via API; self-hosting is a far bigger lift.
* **Live news / market awareness** — financial news APIs plus existing OANDA
  feeds, framed as *live access to the feeds you wire up*, never "knows
  everything".

## 6. Master capability list

Market intelligence · simulation & scenario planning · code & platform
self-awareness · autonomous agents (bounded, tool-using) · visualization &
presence · personalization & security (voiceprint superadmin auth, immutable
audit trail, autonomy dial) · knowledge & research · deep reasoning
(visible chain-of-reasoning, counterfactuals, second-agent self-critique,
root-cause chains) · security auditing **of our own platform only** ·
adaptive/learning behaviour · advanced quant · general knowledge & research ·
creative & content generation · business & operations intelligence ·
cross-domain reasoning · personal productivity (daily brief, long-term
priority memory) · trust & explainability (confidence + evidence, explicit
"I'm not sure", disagreement logging) · failure resilience (kill switch,
local/API failover, state recovery, circuit breakers) · AI-layer security
hardening (**prompt-injection defence: live news and user content are untrusted
data, not instructions**; encrypted memory at rest; **per-agent permission
scoping enforced at the tool layer, not just prompted**) · governance
(model version pinning, exportable regulatory-grade audit logs, eval harness) ·
continuous improvement loop · observability (full tracing, cost dashboard) ·
multi-modal input · notification/alerting with severity tiers ·
plugin architecture · data residency controls.

**Standing boundary, unchanged:** security work is auditing and hardening our
own systems. Attack tooling for systems we do not own stays out of scope
regardless of framing.

## 7. Skill ecosystem — three tiers

| Tier | Shape | HOPEFX mapping |
|---|---|---|
| **Plug-ins** | full teams in one install | future: "install the whole Risk & Compliance department" |
| **Skills** | single commands triggering workflows | **each department's `actions`/skill list (§4) is this tier today** |
| **MCP servers** | live read/write connections | OANDA is effectively one; future: live compliance-database connector |

## 8. Local model sizing

| Model size | RAM / VRAM |
|---|---|
| 1B–4B | 8 GB RAM |
| 7B–8B | 16 GB RAM / 8 GB VRAM |
| 13B–14B | 24 GB+ VRAM |
| 30B+ | 48 GB+ VRAM |
| 70B+ | multi-GPU (80 GB+) |

**Practical read:** 7B–8B (Qwen, Llama, Gemma, Mistral, DeepSeek via Ollama) is
the realistic local tier on the Hostinger VPS without a GPU upgrade. Past 13B
needs VRAM the box likely lacks. Ollama exposes `http://localhost:11434` — the
stack calls it like any internal service. **Confirm actual specs first.**

## 9. Tooling notes

* Claude Code custom skills install to `.claude/skills/` (project) or
  `~/.claude/skills/` (all projects) — not installable in the chat interface.
* Figma MCP connected; **Starter plan has a real rate limit**, already hit once.
* Playwright is a local MCP server for Claude Code (and **is available in this
  repo's environment** — the audit harness uses it).

## 10. Build history

* **Prototype v1** — obsidian/brass hero, canvas consciousness orb, live ticker,
  flat agent grid, static approval queue, capability showcase. Replaced.
* **Prototype v2** — same identity, six-department orbital network, centre
  AI Core node, click-to-expand detail using the four-part anatomy.
* **Figma "HOPEFX AI Core"** — v2 rebuilt natively. Two bugs found and fixed
  (overlapping two-line node label; `createAutoLayout()` defaulting to white
  fill on three frames).

**Known drift:** the Figma file holds **six nodes from the original draft**,
including "Growth & Business", which no longer exists. Four of its six now
belong to Trading Core; "Client & Operations" belongs to Business Operations
with a different skill set. **The file needs a rebuild, not an addition.**

## 11. Design system

* **Palette** — obsidian `#0B0D10`, panel `#14171C` / `#1B1F26`, brass accent
  `#C9A227` / `#E8B84B`. Chosen because it is literal gold, tying identity to
  XAUUSD rather than generic AI neon.
* **Typography** — Spectral (serif display), IBM Plex Sans (body),
  IBM Plex Mono (data/ticker/code).
* **Signature element** — the AI Core orbital diagram: a centre orchestrator
  node with department nodes on connecting lines, not a flat grid.
* **Planned, not built** — two-cluster layout (Trading Core inner, Business Ops
  outer), JARVIS four-part architecture strip beneath the hub, daily-brief loop
  panel.

## 12. Open items (as stated in the spec)

1. Build the AI Gateway, internal MCP tool bus, response cache, and formalised
   Guardrails/Evals pipelines (§3).
2. Confirm the six Business Operations department names and skill lists before
   they go into Figma — cheap now, costly after, given the rate limit.
3. Decide the two-cluster visual layout before rebuilding the orbit diagram.
4. Confirm actual VPS RAM/VRAM to lock a local model size.
5. Decide image generation: external API vs self-hosted SDXL.
6. **Rotate the exposed superadmin credential in git history** — flagged
   repeatedly, still unresolved, higher priority than everything above.
