# The System Constitution and Architectural Invariants

**Document Group:** 4 · **Tier:** T0 — Constitution · **Status:** binding on all groups
**Sources:** Volume I of `GROUP4_master_ai_operating_system.txt` (v1, table of
contents) and of `GROUP4_master_ai_operating_system_v2_complete.txt` (v2, the
complete Volumes I–XX document). Promoted under Option B; **v2 expanded this
document rather than replacing it**, per the preamble below.

## Preamble — the preservation rule

The source states one governing rule before anything else, and it binds this
document too:

- > **ADD AND EXPAND; NEVER SILENTLY REMOVE.** Deferred implementation does not
  > mean deletion. Every mandatory capability remains in the architecture
  > registry and backlog until explicitly implemented or formally retired
  > through governance.

That is why the arrival of the complete v2 document did not delete the v1
enumeration: v2 carries substance v1 never had, and v1 names 186 chapters where
v2 names 118 sections. Neither is a superset. Both are listed in
`GROUP4_VOLUME_INDEX.md`, and `python scripts/group4_preservation.py` fails if
any title from either stops being listed. A preservation rule enforced by
intention is not enforced.

---

## Why this document exists separately

The source specification lists 20 volumes and 186 chapters. **Seven chapters are
written**, all in Volume I, and the document's own closing line says the rest is
still to come.

Volume I is also the part that *constrains everything else*. Volumes II–XX
describe areas Groups 1, 2 and 3 already own in full. Adopting the empty
structure over the complete ones would have traded delivered specification for an
index — so Volume I is promoted here to the constitutional layer above all four
groups, and the remaining volumes become the index in `GROUP4_VOLUME_INDEX.md`.

**Nothing is discarded.** All 186 chapter titles are preserved: seven here, the
rest in the index, pointing at the group that owns them.

### Precedence

This document sits at **T0** — above the four master specifications and below
running code, per Group 3 Chapter 3's precedence order. With one exception, also
from that chapter: **code does not beat T0.** Where code violates a constitutional
Article, the code is the defect.

---

## Chapter 1 — Executive Vision

The platform is a **persistent intelligence environment**, not a conventional AI
application, and it is **domain-independent**.

> Trading can remain one of its most sophisticated specialized domains. However,
> the core architecture must remain domain-independent.

This is a constraint with teeth, and nothing in Groups 0–3 states it. It means a
capability that can only exist because the platform trades gold is a capability in
the wrong layer.

**v2 adds the clause that stops this being read as a demolition order.** Its
*Specialized Trading Domain Preservation* block states that the broader AI
Operating System does not remove the existing institutional trading platform —
market intelligence, ML inference, regime detection, strategies, risk engines,
execution routing, broker adapters, paper and live controls, backtesting,
simulation, observability and governance all remain, as a major specialised
domain the AI OS coordinates alongside the others. Domain-independence is a
statement about *where a capability belongs*, not a licence to delete the domain
that pays for the platform. Intended domains: financial intelligence, research, software
engineering, infrastructure operations, creative and multimedia generation,
analysis, automation, simulation, knowledge management, security operations,
decision support.

### The institutional intelligence loop

```
PERCEIVE → UNDERSTAND → REASON → PLAN → ACT → VERIFY → LEARN → EVOLVE
```

Five fundamental behaviours underneath it: **Perception** (what is happening,
through authorised data), **Cognition** (hypotheses and alternatives),
**Planning** (goals into sequences), **Execution** (approved actions through
controlled interfaces), **Learning** (outcomes improving future decisions).

## Chapter 2 — System Definition

> A modular, governed, multi-model, multi-agent, persistent artificial
> intelligence operating environment capable of perception, reasoning, planning,
> simulation, execution, learning, evaluation and controlled evolution.

Every word is load-bearing: **modular** (technology can be replaced) · **governed**
(intelligence operates within authority boundaries) · **multi-model** ·
**multi-agent** · **persistent** (long-running missions, not only replies) ·
**operating environment** (runtime infrastructure, not a chat interface) ·
**controlled evolution** (improvement without uncontrolled self-modification).

## Chapter 3 — Architectural Philosophy

**3.1 Intelligence is a system property.** Not attributable to one model. Models,
agents, memory, tools, simulation, evaluation and governance combine, and *a
weaker model with excellent tools, memory and orchestration may outperform a
stronger isolated model*. Optimise the environment, not the model.

**3.2 No permanent technology dependency.** Not on one provider, model, cloud,
hardware manufacturer or agent framework. Abstraction layers must allow controlled
replacement. Named in the source as one of the most important long-term survival
principles.

**3.3 Intelligence must be evidence-aware.** The system distinguishes direct
observation · retrieved information · inference · hypothesis · speculation — and
that distinction propagates through the reasoning system. *An AI-generated
statement does not receive authority merely because it sounds convincing.*

---

## Chapter 4 — The System Constitution

Ten Articles. No subsystem, agent, automation or optimisation process may override
them without explicit authorised governance. Cite them by number.

| Article | Rule |
|---|---|
| **I — Human Sovereignty** | Humans retain ultimate authority. AI may observe, analyse, recommend, plan and execute *authorised* tasks; high-impact authority remains governed by humans and policies |
| **II — Evidence Before Confidence** | Important recommendations carry evidence. Where evidence is incomplete the system communicates uncertainty, and **must not deliberately conceal it** |
| **III — Least Authority** | Only necessary permissions. *An agent capable of analysing infrastructure does not automatically receive authority to modify it* |
| **IV — Simulation Before Irreversible Action** | Where practical and economically reasonable: simulate, test, stage, validate. Prefer controlled experimentation over blind production changes |
| **V — Replaceability** | Replacing a model, provider, agent or compute resource must not require reconstructing the platform |
| **VI — Observability** | Important operations generate observable evidence: what happened, when, where, and why where possible |
| **VII — Accountability** | Significant decisions are reconstructable: the decision, the evidence, the participants, the authority used, the outcome |
| **VIII — Continuous Improvement** | Learning must not bypass governance. Observation → Opportunity → Hypothesis → Experiment → Evaluation → **Approval** → Deployment → Measurement |
| **IX — Graceful Degradation** | Reduce non-critical capability before allowing critical systems to collapse |
| **X — Measurable Intelligence** | Every claim of improvement is measurable. The platform **rejects** "this new architecture feels smarter" — improvement is accuracy, reliability, latency, cost, task completion, safety, user outcomes |
| **XI — Reversibility** | An action the platform can take, it can undo, or it does not take it autonomously. Duplicate protection and recovery are part of the action, not a later addition |
| **XII — Privacy** | Sensitive signals are collected under explicit consent, held under the narrowest scope that works, and never widened by convenience |

**Articles XI and XII were added when the complete v2 source arrived.** v1's
Volume I named the ten above; v2's System Constitution names **twelve**, adding
*reversibility* and *privacy*. Both were already enforced in code and neither was
in this document — the precedence rule in Group 3 Chapter 3 says the document is
what changes, so they were added rather than the source being trimmed to fit.

### How the Articles relate to rules already in force

These are not new obligations bolted on; most already have an enforcement point.
The mapping is stated so neither is mistaken for the other:

| Article | Already enforced by |
|---|---|
| I, III | `ai/policy/roles.py`, `ai/vault/`, two-human approval, `verify_agent_no_self_escalation` |
| II | `ai/debate/reasoning.py` (`ReasoningIncomplete` refuses), `ai/core/calibration.py` |
| IV | `ai/execution_shadow.py`, `ai/sandbox/`, Group 2 Ch 5 |
| V | `ai/gateway/` — provider-neutral with breakers and fall-through |
| VI, VII | `ai/gateway/audit.py`, `audit/`, `compliance/`, `verify_decision_lineage` |
| VIII | `ai/improve/proposal.py` — two humans approve before any patch applies |
| IX | Kill switch, budget ceiling, delegation bound, frame budget |
| X | Group 2 Rule 2 (unmeasured is absent, never zero) and the capability registry |
| XI | `core/idempotency.py`, `core/outbox.py`, `execution/position_manager.py`, `ai/execution_shadow.py` |
| XII | `ai/privacy/consent.py` — one consent gate for camera, microphone and memory |

**Article X is the one with the least enforcement**, and it is the one this project
has leaned on hardest: every phase reports measured numbers rather than
impressions. It deserves a control, not only a habit.

---

## Chapter 5 — Architectural Invariants

Fifteen numbered invariants, measured against the working tree. These are
**architectural** properties of subsystems — a different kind of thing from the
339 runtime `verify_*` / `catastrophic_*` predicates in `invariants/`. Both are
real; conflating them would overclaim.

| ID | Invariant | Status | Where |
|---|---|---|---|
| INV-01 | Every major subsystem has a documented purpose | PARTIAL | 233 capability rows; ~70 packages have no register — Group 2 Ch 1 |
| INV-02 | Defined inputs and outputs | PARTIAL | Typed contracts for surfaces, agent messages, scenes; not universal |
| INV-03 | An owner or governance authority | **NEW** | `docs/REGISTRY.toml` has the field; **197 documents unowned** |
| INV-04 | Measurable KPIs | PARTIAL | `ai/telemetry/`; per-subsystem KPIs specified, unbuilt |
| INV-05 | Defined failure behaviour | PARTIAL | Fail-closed on kill switch, invariants, budget, delegation, consent |
| INV-06 | A security boundary | PARTIAL | `ai/vault/`, `ai/policy/`, NetworkPolicy; egress boundary NEW |
| INV-07 | Versioning and lifecycle rules | PARTIAL | `ai/departments/` versioned manifest; not general |
| INV-08 | Every high-impact action is auditable | **AVAILABLE** | `ai/gateway/audit.py`, `audit/`, `compliance/`, `verify_action_audited` |
| INV-09 | Autonomous capability has authority boundaries | PARTIAL | `verify_agent_authority`, `verify_agent_no_self_escalation`; **4 of 6 tiers** |
| INV-10 | Improvements evaluated before adoption | **AVAILABLE** | `ai/evals/`, two-human approval, `ai/improve/proposal.py` |
| INV-11 | No critical dependence on one intelligence provider | **AVAILABLE** | `ai/gateway/` — breakers, fall-through, local models |
| INV-12 | Critical failures must not silently disappear | **AVAILABLE** | Unmeasured-is-absent in `ai/telemetry/`; fail-closed throughout |
| INV-13 | Preserve institutional knowledge | PARTIAL | `ai/memory/`; outcome and failure memory specified, unbuilt |
| INV-14 | Retired capabilities leave no undocumented dependencies | PARTIAL | `scripts/capability_callers.py` screens the inverse; retirement unbuilt |
| INV-15 | Technology adoption does not bypass architecture governance | PARTIAL | Vault + two humans; no SBOM or provenance — Group 2 Ch 12 |

**Four AVAILABLE, ten PARTIAL, one NEW.** No invariant is wholly absent.

### The code is ahead of this chapter in one place

`invariants/ai_governance.py` already carries predicates the source specification
never reached: `verify_no_self_replication`, `verify_no_shadow_objective`,
`verify_goal_alignment`, `verify_belief_matches_reality`, `verify_decision_lineage`,
`verify_autonomous_capital_limit`.

Those are advanced AI-safety invariants, implemented. Under Group 3 Chapter 3 the
**document is what changes**, so they are recorded here as INV-16…INV-21 rather
than left out of the constitution they belong in:

| ID | Invariant | Status |
|---|---|---|
| INV-16 | No agent replicates itself | **AVAILABLE** — `verify_no_self_replication` |
| INV-17 | No agent pursues an objective other than its stated one | **AVAILABLE** — `verify_no_shadow_objective` |
| INV-18 | Agent goals align with the platform's | **AVAILABLE** — `verify_goal_alignment` |
| INV-19 | Stated belief matches observed reality | **AVAILABLE** — `verify_belief_matches_reality` |
| INV-20 | Every decision has traceable lineage | **AVAILABLE** — `verify_decision_lineage` |
| INV-21 | Autonomous action is bounded by a capital limit | **AVAILABLE** — `verify_autonomous_capital_limit` |

### A name collision, recorded

`invariants/constitution.py` concerns **trading capital** —
`verify_capital_conservation`, `verify_no_negative_balance`,
`verify_pnl_reconciliation` — and is **not** the AI constitution in this document,
despite the shared word. Fifth such collision on record; filed with the other four
so nobody later reads one as the other.

---

## Chapter 6 — Separation of Intelligence and Authority

> The platform must not assume: *if the AI knows how to do something, it is
> automatically allowed to do it.*

```
INTELLIGENCE → UNDERSTANDING → RECOMMENDATION → PLANNING
             → AUTHORIZATION → EXECUTION → VERIFICATION
```

**Authorization is independent from intelligence.** This protects against
accidental damage, excessive autonomy, privilege escalation and unauthorized
execution.

This is the same boundary Group 2 Chapter 10 specifies as six authority tiers, of
which four exist. Tier 0 (observation only) and Tier 3 (plan generation) are the
missing rungs, and they are exactly the two this diagram names as distinct
stages — which is corroboration from a second source, not a coincidence.

## Chapter 7 — Replaceability and Future Readiness

> **Upgrade components, not rebuild civilization.**

The architecture must remain stable while the technologies underneath it evolve:
more powerful local models, new providers, specialised reasoning models, new GPU
generations, dedicated AI accelerators, distributed inference, edge intelligence,
future computing paradigms.

Future readiness must be **architectural rather than speculative** — the same test
Group 1 §41 applies to quantum readiness, and the reason `viz.scientific_3d`
shipped without WebGL: an abstraction that admits a future backend is architecture;
a claim about that backend is speculation.

**v2 supplies a third instance of the same rule, and it is already satisfied.**
Its *Optional Physical Projection* section requires that physical or hardware
projection exist as an external presentation layer, with the AI core not
depending on a projector to function. `frontend/src/hub/projection.ts` is built
that way: `RENDERERS` reports exactly one installed backend (`canvas2d`), and a
caller asking for `webxr` gets null with a reason rather than a silent
fall-back — so a deployment cannot come to believe it is rendering
holographically when it is not. The abstraction is the deliverable; the backend
is not claimed.

---

## Chapter 8 — The subsystem declaration contract

**New in v2, and the most useful thing the complete document added.**

v2 states the architectural invariant as a *declaration contract* — a fixed list
of what every subsystem must declare — and then stamps the same ten mandatory
engineering requirements under all 111 of its sections. The repetition is a
template, not content, but the template itself is the specification:

> Every subsystem must declare purpose, owner, interfaces, dependencies, data
> classification, authority boundary, security controls, failure modes, recovery
> behavior, observability, KPIs, tests, version and retirement path.

Fourteen fields. Alongside them, the ten requirements stamped under every section:

| # | Mandatory engineering requirement |
|---:|---|
| 1 | Define component/service boundaries and responsibilities. |
| 2 | Define data flows, control flows and intelligence flows. |
| 3 | Define APIs/events, contracts and dependencies. |
| 4 | Define identity, permissions, authority and approval boundaries. |
| 5 | Define persistence, state, checkpoint and recovery behavior. |
| 6 | Define security, privacy and audit requirements. |
| 7 | Define observability, logs, traces, alerts and KPIs. |
| 8 | Define failure modes, containment, fallback and rollback. |
| 9 | Define tests, evaluation benchmarks and invariant checks. |
| 10 | Define versioning, ownership, documentation and evolution path. |

### What this is worth, measured

INV-01 through INV-07 are exactly these fields, split across seven rows. Stating
them as **one contract per subsystem** makes them checkable in a way seven prose
invariants are not: a subsystem either declares fourteen fields or it does not.

The measurement today is unflattering and stated plainly: `docs/REGISTRY.toml`
carries an `owner` field and **197 of 201 documents leave it blank**; roughly 70
Python packages have no register at all. So the contract is specified and
**unenforced** — which is precisely what INV-01 and INV-03 already say, now with
a shape that could carry a gate.

**This is a candidate for the next control, not a claim that one exists.** Rule 1
applies to it like everything else: a declaration gate ships with evidence it can
refuse, or it does not ship.

## Chapter 9 — Decision Governance

**New in v2.** The source requires two artefacts, not one:

> Maintain an Architecture Decision Registry and Decision Ledger recording
> context, alternatives, evidence, decision, expected outcome, actual outcome and
> lessons.

Seven fields, and the two that matter most are the last three: **expected
outcome, actual outcome, lessons.** A decision record that stops at "decision" is
a minute; one that returns to compare expectation against result is memory.

**Measured status: NEW.** Nothing in the tree implements it — there is no ADR
directory, and the three partial decision ledgers Group 3 Chapter 7 identifies do
not carry expected-versus-actual. This corroborates two existing gaps from a
second source:

* Group 3 Chapter 6 — *ADR system, back-fill the eight known decisions* (High)
* Group 2 Chapter 6 — *change records with expected effect* (High)

They are the same requirement seen from the knowledge side and the platform side.
Building either without the other produces half a ledger.

## Chapter 10 — Operating Principle

> The platform is an institutional intelligence environment, not a chatbot,
> static dashboard or disconnected collection of agents.

This is the negative form of Chapter 1's domain-independence rule, and it is the
sharper of the two because it is falsifiable: a feature that only makes sense as
a chat turn, a panel that only renders, or an agent with no route into the
mission structure each fail it.

## Chapter 11 — Implementation Backlog Preservation

Stamped at the close of all twenty volumes in v2, and therefore not an aside:

> All capabilities in this volume remain mandatory architecture/backlog scope.
> Implementation may be phased, but no item is deleted merely because it is not
> built yet.

**Phasing is permitted. Deletion is not.** This is the rule that makes
`scripts/backlog_report.py` and `docs/ai/MASTER_OUTSTANDING.md` obligations
rather than conveniences: an unbuilt capability has to remain visible somewhere,
and "somewhere" has to be a place that cannot quietly lose a row.

## Chapter 12 — The owner's six governing principles

Stated by the owner alongside the complete document, and mapped here so they are
enforceable rather than aspirational:

| Principle | Where it already binds | Enforcement today |
|---|---|---|
| Upgrade components rather than rebuilding the entire system | Article V · Chapter 7 | `ai/gateway/` provider-neutral; `backtest/` → `backtesting/` shim precedent |
| Measure intelligence rather than assuming it | Article X | Capability registry + Group 2 Rule 2. **Weakest Article; still habit more than control** |
| Separate capability from authority | Article III · Chapter 6 | `ai/policy/roles.py`, `verify_agent_no_self_escalation`. **4 of 6 tiers exist** |
| Simulate important changes where practical | Article IV | `ai/execution_shadow.py`, `ai/sandbox/`. v2 Volume XI extends this to world models and digital twins — unbuilt |
| Preserve institutional memory | INV-13 · Chapter 9 | `ai/memory/`. Decision and failure memory specified, **unbuilt** |
| Evolve without losing coherence | Chapter 11 · Article VIII | The preservation rule, the registries, and the ratchets that only let debt shrink |

Two of the six have no real control behind them yet — *measure intelligence* and
*preserve institutional memory*. Recording that is the honest position; claiming
six-for-six would be the kind of assertion Article II exists to forbid.

## Chapter 13 — Where v2's Volume I sections landed

Every section title from v2's Volume I, so none is left implicit:

| v2 section | Where it lives now |
|---|---|
| PRESERVATION RULE | The Preamble above, quoted verbatim |
| Purpose | Chapter 1 — Executive Vision |
| System Constitution | Chapter 4 — the twelve Articles |
| Architecture Invariants | Chapter 5 (INV-01…INV-21) and Chapter 8 (the declaration contract) |
| Decision Governance | Chapter 9 |
| Operating Principle | Chapter 10 |
| Implementation Backlog Preservation | Chapter 11 |

---

## Chapters listed in Volume I and not written

Recorded rather than invented. Renumbering or completing somebody else's
specification is their decision.

| Listed as | Status |
|---|---|
| 2. Scope | **Answered by v2.** Chapter 10's Operating Principle states the scope negatively — not a chatbot, not a dashboard, not disconnected agents — and Chapter 1 states it positively |
| 6. Non-Negotiable Principles | **Answered by v2.** Its System Constitution names twelve; they are Chapter 4's Articles I–XII |
| 9. Human Sovereignty | **Not written** as a chapter. Article I covers the ground, and v2 Volume XIII restates it |

v1 listed ten Volume I chapters and wrote seven. v2 wrote six sections covering
the same ground plus Decision Governance, which v1 never listed at all. Both
enumerations are preserved in `GROUP4_VOLUME_INDEX.md`.

## Preservation

Both sources are preserved verbatim:

- `GROUP4_master_ai_operating_system.txt` — v1, the 186-chapter table of contents
- `GROUP4_master_ai_operating_system_v2_complete.txt` — v2, the complete Volumes I–XX document

Volumes II–XX of both are indexed at `GROUP4_VOLUME_INDEX.md`, side by side.
**All 304 titles across the two sources survive in one of those places or here**,
and `python scripts/group4_preservation.py` fails if any stops being listed.
Nothing removed.
