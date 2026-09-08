# Group 4 — "Master AI Operating System": read, measured, and the question it raises

**Source:** `specs/GROUP4_master_ai_operating_system.txt`, preserved verbatim (711 lines).
**Status of this analysis:** measured against the working tree, not assumed.

---

## 1. What arrived, counted rather than eyeballed

| Measure | Count |
|---|---:|
| Lines | 711 |
| Volumes in the table of contents | 20 |
| Numbered chapters in the table of contents | **186** |
| Chapters actually **written** | **7** |
| Completion | **3.8%** |

The document says so itself, in its closing line: *"The next section should be Volume II."*
It is a **constitution plus a complete table of contents**, not a complete specification.
That is a legitimate and useful thing to have — the constitution is the part that
constrains everything else — but it must not be filed as if 186 chapters exist.

### Volume I is itself incomplete, and renumbered

Its own contents list ten chapters; seven are written, and the written numbering
diverges from the list:

| # in contents | Title | Written as |
|---|---|---|
| 1 | Executive Vision | CHAPTER 1 |
| 2 | **Scope** | **— not written** |
| 3 | System Definition | CHAPTER 2 |
| 4 | Architectural Philosophy | CHAPTER 3 |
| 5 | System Constitution | CHAPTER 4 |
| 6 | **Non-Negotiable Principles** | **— not written** (Articles I–X cover the ground) |
| 7 | Architectural Invariants | CHAPTER 5 |
| 8 | Intelligence and Authority Separation | CHAPTER 6 |
| 9 | **Human Sovereignty** | **— not written** (Article I covers the ground) |
| 10 | Replaceability and Future-Proofing | CHAPTER 7 |

Recorded rather than corrected: renumbering somebody else's specification is a
decision for its author, and the three gaps may be deliberate (two of the three
are substantially covered by Constitution articles).

---

## 2. The question this document raises

**It is not a fourth sibling. Its own DOCUMENT COMPLETENESS RULE enumerates areas
that Groups 1, 2 and 3 already own.**

| Its volumes | Already owned by |
|---|---|
| II–VII — runtime, cognition, multi-model, multi-agent, knowledge, perception | **Group 1** |
| **VIII — Acceleration** | **nobody. Genuinely new.** |
| IX–X — execution, reliability | **Group 2** |
| XI–XII — simulation, self-improvement | **Group 1** |
| XIII–XIV — governance, security | **Groups 1 and 2** |
| XV–XVI — research, capability evolution | **Group 1** |
| XVII–XIX — performance, quality, interfaces | **Group 2** |
| XX — institutional intelligence | **Groups 1 and 3** |

So this is a proposed **reorganisation that absorbs the existing documents**, not an
addition beside them. That is an architectural decision with real consequences
either way, and it belongs to the owner. Both options are viable:

**Option A — Group 4 becomes the umbrella.** Groups 0–3 become volumes inside it.
One table of contents for everything.
*Cost:* 186 chapters is a very large surface, and 179 of them do not exist. The
delivered work in Groups 0–3 would have to be re-indexed into the new numbering,
and until that is done the registry's section numbers stop matching the documents.

**Option B — Group 4 is the CONSTITUTION only; its other volumes are references.**
Volume I (the part that is written) becomes the constitutional layer above all
four groups. Volumes II–XX become an index that *points at* the owning group
rather than restating it. Volume VIII (Acceleration) becomes new Group 2 content.
*Cost:* the document's own ambition is trimmed to what is written.

**Recommendation: Option B**, for one reason that is not about preference. Volume I
is 100% written and is the part that constrains everything; volumes II–XX are 0%
written and duplicate documents that are 100% written. Adopting the empty
structure over the full ones would trade delivered specification for an index.
Option B keeps every word and loses nothing — which is the preservation rule this
document itself opens with.

**This is recorded as an open question, not decided.**

---

## 3. The fifteen architectural invariants, measured

Chapter 5 defines INV-01…INV-15. These are *architectural* invariants — properties
of subsystems — and are a different kind of thing from the 339 runtime
`verify_*` / `catastrophic_*` predicates in `invariants/`. Both are real; conflating
them would overclaim.

Measured against the working tree:

| ID | Invariant | Status | Evidence |
|---|---|---|---|
| INV-01 | Every major subsystem has a documented purpose | **PARTIAL** | 233 capability rows carry title + note; the ~70 top-level *packages* have no register (Group 2 Ch 1, NEW) |
| INV-02 | Defined inputs and outputs | **PARTIAL** | Typed contracts exist for surfaces, agent messages, scenes; not universal |
| INV-03 | An owner or governance authority | **NEW — measured gap** | `docs/REGISTRY.toml` has the field and **197 of 197 documents are unowned** |
| INV-04 | Measurable KPIs | **PARTIAL** | `ai/telemetry/` measures; per-subsystem KPIs are specified in Groups 2/3, not built |
| INV-05 | Defined failure behaviour | **PARTIAL** | Fail-closed is enforced on kill switch, invariants, budget, delegation, consent; not universal |
| INV-06 | A security boundary | **PARTIAL** | `ai/vault/`, `ai/policy/roles.py`, k8s NetworkPolicy; data-egress boundary is NEW (Group 2 Ch 13) |
| INV-07 | Versioning and lifecycle rules | **PARTIAL** | `ai/departments/` carries a versioned permissions manifest; not general |
| INV-08 | Every high-impact action is auditable | **AVAILABLE** | `ai/gateway/audit.py`, `audit/`, `compliance/` (2,518 LOC), `verify_action_audited` |
| INV-09 | Autonomous capability has authority boundaries | **PARTIAL** | `verify_agent_authority`, `verify_agent_no_self_escalation`, `verify_agent_count_bounded`; `ai/policy/roles.py` has **4 of the 6 tiers** |
| INV-10 | Improvements evaluated before adoption | **AVAILABLE** | `ai/evals/`, two-human approval on vault paths, `ai/improve/proposal.py` |
| INV-11 | No critical dependence on one intelligence provider | **AVAILABLE** | `ai/gateway/` — provider-neutral, per-vendor breakers, chain fall-through, local models |
| INV-12 | Critical failures must not silently disappear | **AVAILABLE** | Unmeasured-is-absent-never-zero in `ai/telemetry/`; fail-closed everywhere it spends, trades or exposes |
| INV-13 | Preserve institutional knowledge | **PARTIAL** | `ai/memory/` tiers and graph; outcome and failure memory specified (Group 3 Ch 8), not built |
| INV-14 | Retired capabilities leave no undocumented dependencies | **PARTIAL** | `scripts/capability_callers.py` screens for the inverse (built, uncalled); retirement is unbuilt |
| INV-15 | Technology adoption does not bypass architecture governance | **PARTIAL** | Vault + two-human approval; no dependency-provenance or SBOM (Group 2 Ch 12) |

**Three AVAILABLE, eleven PARTIAL, one NEW.** No invariant is wholly absent, which
is a genuinely strong position for a document arriving after the fact.

### A finding worth naming

`invariants/ai_governance.py` already carries predicates this specification has not
yet reached: `verify_no_self_replication`, `verify_no_shadow_objective`,
`verify_goal_alignment`, `verify_belief_matches_reality`, `verify_decision_lineage`,
`verify_autonomous_capital_limit`.

Those are advanced AI-safety invariants, already implemented. The specification's
Chapter 5 should absorb them rather than the reverse — **the code is ahead of the
document here**, and the precedence rule (Group 3 Chapter 3: code beats
documentation) says the document is what changes.

Note also that `invariants/constitution.py` is about **trading capital** —
`verify_capital_conservation`, `verify_no_negative_balance`, `verify_pnl_reconciliation` —
and is not the AI constitution this document describes, despite the shared name.
That is the fifth name collision recorded in this project, and it is filed with
the other four so nobody later reads one as the other.

---

## 4. What is genuinely new here

Stripping out what Groups 0–3 already own, the new material is:

1. **Volume VIII — Acceleration Architecture** (15 chapters). Hardware abstraction,
   dynamic compute routing, parallel and distributed execution, multi-level
   caching, predictive preloading, resource isolation, future accelerator
   integration. **No group owns this.** It is the single largest genuinely new
   area in the document.
2. **Chapter 4 — the System Constitution as ten numbered Articles.** Groups 0–3
   carry constitutional rules scattered across `CLAUDE.md`, `AGENTS.md` and four
   specifications. Ten numbered, citable Articles is better than scattered prose.
3. **Chapter 5 — INV-01…INV-15 as numbered, checkable architectural invariants.**
   The mapping above is only possible because they are numbered.
4. **Chapter 1 — domain independence.** The explicit statement that trading is one
   domain and the core must not be trading-specific. Nothing in Groups 0–3 says
   this, and it is a constraint with real architectural consequences.

---

## 5. Nothing has been discarded

The document opens with a preservation rule. It is honoured here:

* The source is preserved verbatim at `specs/GROUP4_master_ai_operating_system.txt`.
* Every one of its 186 chapter titles remains in that file.
* This analysis adds classification and measurement; it removes nothing.
* Where its content is already owned elsewhere, that is recorded as a
  **relationship**, not as a deletion — the same rule Groups 1–3 follow.
