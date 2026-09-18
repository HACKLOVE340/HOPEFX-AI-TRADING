# The Three Document Groups — taxonomy, coverage, and the plan

**Status:** living. Created from the two uploaded files, measured against the code.
**Rule:** additive. Nothing in either source document is dropped. Where a capability
already exists, this file says so and points at it rather than re-specifying it.

---

## 1. The two files are different kinds of artifact

This matters, because treating them the same would produce the wrong work.

| File | What it actually is | Role |
|---|---|---|
| `text.txt` | A **specification** — 64 sections, "Advanced Intelligence, Cognition, Autonomy and Evolution Architecture" | **Group 1 content.** A living master document in its own right. |
| `text_25.txt` | An **instruction** — it commissions two documents and defines the three-group taxonomy | **The brief for Groups 2 and 3.** Not itself a spec. |

`text_25.txt` names the taxonomy that both files then live inside, and it names
`text.txt` as Group 1. So the two files are not siblings: one is the map, the
other is one of the territories.

---

## 2. The taxonomy, and the rule that keeps it clean

| Group | Document | Status |
|---|---|---|
| **Group 0** | AI Hub Institutional Master Architecture Specification v1.0 (31 §§) | **Delivered.** 233 registry rows, 230 live. |
| **Group 1** | Advanced Intelligence, Cognition, Autonomy and Evolution Architecture (64 §§) | Uploaded as `text.txt`. Coverage mapped below. |
| **Group 2** | Master Platform Engineering, Operations, Infrastructure and Governance | **Delivered.** 35 chapters across nine Parts — `specs/GROUP2_platform_engineering_operations_governance.md` |
| **Group 3** | Master Documentation, Knowledge Management and Architecture Governance | **Delivered.** 18 chapters — `specs/GROUP3_documentation_knowledge_architecture_governance.md` |
| **Group 4** | Master AI Operating System — Execution, Intelligence, Acceleration, Autonomy, Governance and Evolution | **Received, 3.8% written.** 20 volumes and 186 chapters listed, **7 written**. See `GROUP4_ANALYSIS.md` |

`text_25.txt` did not know about Group 0 — the 31-section spec already delivered.
It is added here as Group 0 rather than folded into Group 1, because merging them
would make the delivered work invisible and invite it being re-specified.

**Classification rule — one question, asked in order:**

1. Does it change *how the AI thinks, perceives, decides, learns or evolves*? → **Group 1**
2. Does it change *how the platform is built, run, deployed, secured or measured*? → **Group 2**
3. Does it change *how we record, organise, govern or retrieve knowledge about 1 and 2*? → **Group 3**
4. Does it change *what the operator sees and says to the AI*? → **Group 0**

A single item belongs to exactly one group. Where it touches another, the owning
group **references** the relationship; it does not copy the content. That rule is
the whole defence against the duplicate and conflicting specifications Group 3
exists to prevent.

### Group 4 did not fit the rule — RESOLVED: Option B adopted

Group 4's own completeness rule enumerates areas Groups 1, 2 and 3 already own —
multi-model, multi-agent, memory, perception, governance, security, research,
platform engineering. It is therefore **not a fifth sibling but a proposed
reorganisation that absorbs the others**.

Two viable readings, both costed in `GROUP4_ANALYSIS.md` §2:

* **Option A** — Group 4 becomes the umbrella and Groups 0–3 become volumes inside
  it. One table of contents for everything, at the cost of re-indexing delivered
  work into a numbering where 179 of 186 chapters do not exist.
* **Option B — ADOPTED** — Group 4's **written** Volume I becomes the
  constitutional layer above all groups; its unwritten Volumes II–XX become an
  index pointing at the owning group; Volume VIII (Acceleration) becomes new
  Group 2 content, since no group owns it.

The recommendation rests on a measurement, not a preference: Volume I is 100%
written and constrains everything; Volumes II–XX are 0% written and duplicate
documents that are complete. **Adopting the empty structure over the full ones
would trade delivered specification for an index.**

**Decided by the owner on 2026-09-08: Option B.** What that produced:

| Piece | Where it landed |
|---|---|
| Volume I | `docs/ai/specs/GROUP4_CONSTITUTION.md` — **T0**, twelve Articles, INV-01…INV-21, fifteen chapters |
| Volumes II–XX, both enumerations | `docs/ai/specs/GROUP4_VOLUME_INDEX.md` — **T1**, every title from both sources routed to its owner |
| Volume VIII, Acceleration | Group 2 Part VIII, Chapters 28–34 — the one area no group owned |
| The sources | `GROUP4_master_ai_operating_system.txt` (v1) and `GROUP4_master_ai_operating_system_v2_complete.txt` (v2), both preserved verbatim |

**Later the same day the complete Volumes I–XX document arrived**, and Option B
held rather than being revisited: v2 carries a statement under every section but
names 118 sections where v1 named 186 chapters, so it is **not a superset**.
Neither source replaces the other; both are listed side by side.

All 304 titles across the two sources survive. Nothing removed, which is the rule
the source document opens with — and `python scripts/group4_preservation.py` is
what makes that a measurement rather than a promise.

**Precedence.** The constitution sits at T0 — above the four master
specifications, and above code on constitutional Articles: where code violates an
Article, the code is the defect. Everywhere else Group 3 Chapter 3's order stands
and running code wins.

**Where the outstanding work now shows up.** `python scripts/backlog_report.py`
sections 6 and 7: the invariants not yet AVAILABLE (told — the constitution's own
status column) and whether every predicate the constitution cites still exists in
`invariants/` (measured). A renamed verifier makes section 7 say so.

---

## 3. Coverage of Group 1 against the code

Measured, not assumed. `AVAILABLE` means a named module implements it and the
capability registry carries a row whose evidence resolves. `PARTIAL` means some of
it exists and the gap is named. `NEW` means nothing implements it.

### AVAILABLE — already built, do not re-specify

| § | Capability | Where it lives |
|---|---|---|
| 5 | Multi-model orchestration | `ai/gateway/` (3,283 LOC) — `chain.py:DEFAULT_CHAINS`, `vendors.py` |
| 6 | Provider & API-key layer | `ai/gateway/providers.py`, `discovery.py`; secrets never enter agent context |
| 12 | Continuous self-evaluation | `ai/evals/` — `suite`, `runner`, `gate`, `schedule`, `store` |
| 13 | Confidence calibration | `ai/core/calibration.py` — `MIN_SAMPLE=20`, `TOLERANCE=0.10`, tracks stated vs. actual |
| 14 | AI nervous system | `ai/bus/` — `agent_bus`, `graph`, `lifecycle`, `triggers` |
| 18 | Multi-agent consensus | `ai/debate/session.py` — `DECISIVE_RATIO`, weighted by evidence, **not** majority vote |
| 19 | Adversarial reasoning | `ai/core/challenger.py` — `challenge(reasoning)` |
| 29 | Autonomous code intelligence | `ai/improve/` — `walker`, `finding`, `proposal`, `patcher` |
| 31 | Institutional memory | `ai/memory/` — `tiers`, `graph`, `governance`, `store` |
| 49 | Intelligence resource economics | `ai/gateway/budget.py`, `budget_store.py`, `breakers.py` |
| 51 | AI capability registry | `ai/hub/capabilities.py` (233 rows, self-verifying) + `ai/departments/` |
| 57 | Institutional operating model | `ai/departments/` — **11 departments already registered** |
| 50 | Emergency intelligence mode | `frontend/src/hub/modes.ts:emergency` |
| 26 | Security mode switching | `ai/guardrails/`, `ai/telemetry/security.py` |

**§13, §18 and §19 are exact matches** — the spec describes behaviour the code
already has, down to "consensus does not mean majority vote."

### PARTIAL — real gap, named

| § | Capability | What exists | What is missing |
|---|---|---|---|
| 4 | Intelligence Governor | `ai/agent/orchestrator.py:decompose`, `ai/core/depth.py` | complexity estimation, model selection, escalation, **stopping decisions** |
| 9 | Cognition core | `ai/debate/reasoning.py:Reasoning` (thesis, counter, evidence, assumptions, confidence) | the full 10-stage pipeline; simulation and outcome-learning stages |
| 15 | Sensory system | `ai/telemetry/` + `ai/awareness/watchers.py` | business sensors; intelligence sensors (hallucination rate) |
| 23 | Human-only boundary | `ai/vault/` — protects **paths** | protecting **data**: which content may reach an external model |
| 32 | Outcome memory | memory tiers exist | decision → prediction → outcome → accuracy → lesson linkage |
| 33 | Failure memory | incident logging | structured cause/detection/fix/prevention record |
| 35 | Innovation incubator | `ai/improve/cycle.py` | the discovery→benchmark→adoption lifecycle |
| 37 | Backlog intelligence | `ai/hub/capabilities.py` (capabilities, not backlog) | duplicate/conflict/prerequisite detection over *ideas* |
| 47 | Uncertainty management | `ReasoningIncomplete` refuses; confidence carried | the escalation menu (investigate / consult / simulate / defer) |
| 48 | Decision ledger | `ai/gateway/audit.py`, `ai/improve/proposal.py` | one ledger across all decision types |
| 52 | Agent performance evaluation | `ai/telemetry/agents.py` | retire/replace policy on poor performers |
| 59 | Human authority model | `ai/policy/roles.py` — VIEW/PROPOSE/APPROVE/EXECUTE (**4**) | Tiers 0–5 (**6**); observation and plan-generation tiers absent |

### NEW — nothing implements these

§7 model capability database · §8 benchmarking laboratory · §10 scientific method
engine · §11 curiosity engine · **§16 operational correlation** · §17 impact
analysis · §20 forecast intelligence · §21 technical-debt forecasting · §22
standards guardian · §24 local private agents · §30 mentor system · §34 research
intelligence · §36 capability evolution engine · §38 idea relationship graph ·
§39 platform intelligence index · §40 quantitative reasoning · §41 quantum-ready
· §42 autonomous experimentation · §43 simulation before action · §44 digital
twin · §45 cognitive diversity · §46 epistemic status · §53 dynamic agent teams ·
§54 hierarchical/peer structures · §55 recursive improvement · §56 continuous
architecture review

**Roughly 26 available or partial, 26 new, out of 64.**

---

## 4. Name collisions — where "we already have that" would be wrong

The failure this codebase has already committed once, when `agents.system`
pointed at `platform_engineering` and §11 reported twelve agents with eleven
present. Same word, different capability:

| Spec asks for | We have something called that | They are not the same |
|---|---|---|
| **§16 Correlation Intelligence** — deployment → latency → errors → root cause | `ai/debate/correlation.py` | It correlates **news/macro/technical/microstructure signals to gold price moves**. Operational correlation shares nothing but the noun. |
| **§59 six authority tiers** (0 observe … 5 restricted) | `ai/policy/roles.py` four capabilities | Four is not six. Tier 0 (observation-only) and Tier 3 (plan generation) have no equivalent. |
| **§7 capability profiles** (reasoning/coding/maths scores) | `ai/gateway/discovery.py:list_models` | Lists *which models exist per provider*. It carries no capability scores. |
| **§8 dynamic per-capability rankings** | `ai/evals/` | Runs a pass/fail gate. It does not rank models per capability. |
| **§31 institutional memory** | `ai/memory/` | Stores conversation and knowledge tiers. It does not preserve decisions, experiments or benchmarks as first-class records. |

Each of these is recorded so that the coverage map cannot later be read as
closing a row it does not close.

---

## 5. How this gets built

**Group 1 gets the same mechanism that carried Group 0** — a capability registry
with resolving evidence, extended with the lesson Group 0 ended on: `verify()`
resolves a locator but has no opinion on whether anything *calls* it, so Group 1's
registry adds a caller check to every row.

Order, by dependency rather than by section number:

| Wave | Sections | Why first |
|---|---|---|
| **W1 — close the partials** | 4, 9, 47, 59, 48 | Cheapest real gain: the code is already there and under-reaching. §59's tiers gate everything below. |
| **W2 — perception** | 15, **16**, 17 | Operational correlation is the highest-value new engine, and §17 needs it. |
| **W3 — model intelligence** | 7, 8, 52 | Capability profiles then rankings then agent scoring; §8 depends on §7. |
| **W4 — scientific loop** | 10, 11, 42, 43, 46 | Curiosity feeds the scientific method feeds experimentation. §46 makes their output honest. |
| **W5 — memory and learning** | 32, 33, 30, 34 | Outcome and failure memory before the mentor that reads them. |
| **W6 — evolution** | 35, 36, 37, 38, 55, 56, 39 | Everything above must exist before the system can evaluate itself. |
| **W7 — sovereignty and forecast** | 23, 24, 20, 21, 22 | §23's data boundary is a security change and wants its own care. |
| **W8 — research horizon** | 40, 41, 44, 45, 53, 54 | Genuinely exploratory; scheduled last, honestly. |

**Groups 2 and 3 are written before W1 starts**, not after. `text_25.txt` asks for
them as documents, and they are the ones that say how the work is governed and
recorded — writing them last would mean building Group 1 under rules that did not
yet exist.

---

## 6. What was not decided here

* ~~Whether Group 2 should absorb the operational half of §16, §20, §21 and §22.~~
  **RESOLVED in Group 2 Chapter 16.** They stay in Group 1; Group 2 owns their
  inputs and enforcement points, and the interface between the two documents is
  one table. The deciding question is not "is it about operations" but **"does it
  require a hypothesis?"** — a threshold does not, a correlation between a deploy
  and a latency change does.
* §41 (quantum-ready) is kept verbatim as the source document requires, and
  flagged: the source itself says it must not be marketing terminology. It stays
  in W8 as research, with no implementation claim.
