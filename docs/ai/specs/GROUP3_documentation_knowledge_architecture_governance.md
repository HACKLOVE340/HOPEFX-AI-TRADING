# Master Documentation, Knowledge Management and Architecture Governance Specification

**Document Group:** 3 of 4 · **Status:** Living Architecture Specification
**Relationship rule:** additive. This document governs the *other* documents. It
does not restate their content; it defines how they are structured, owned,
versioned, related, retired and retrieved.

---

## 0. The problem, measured

Most documentation specifications open with principles. This one opens with
measurements taken from the working tree, because the problem it exists to solve
is not hypothetical here — it is present, countable, and already costing.

### Finding 1 — Four documents describe the same API, and they conflict

| File | Lines | Stated base URL |
|---|---:|---|
| `docs/API.md` | 439 | `https://your-domain.com` |
| `docs/API_ENDPOINTS.md` | 1,170 | — |
| `docs/API_GUIDE.md` | 625 | — |
| `docs/API_REFERENCE.md` | 851 | `http://localhost:8000` |

**3,085 lines about one API across four files.** This is not merely duplication.
Two of them state *different base URLs*, which makes it a **conflict**: a reader
following the wrong document calls the wrong host. There is no marker anywhere
saying which is authoritative.

### Finding 2 — Two contributor contracts have diverged

`CONTRIBUTING.md` exists at the repository root (126 lines) **and** at
`docs/CONTRIBUTING.md` (375 lines). `DEPLOYMENT.md` likewise: 656 lines at root,
834 in `docs/`. Different lengths mean different content, which means at least one
is wrong, and nothing declares which.

### Finding 3 — Roughly two thirds of the documentation is unreachable

190 files under `docs/`. `mkdocs.yml` carries 64 navigation entries. **Around 126
files are not reachable through the published site** — they exist, they are
indexed by nothing, and they are found only by someone who already knows the
filename.

### Finding 4 — Point-in-time reports live alongside living documents

Six dated audit files (`AUDIT_2026-07-26.md`, `AUDIT_SIDEBAR_2026-07-27.md`, …)
sit in the same directory as `ARCHITECTURE.md`. A dated snapshot and a living
contract have opposite lifecycles — one is correct for ever at its date, the other
is wrong the moment it drifts — and mixing them means a reader cannot tell which
kind of thing they are holding.

### Finding 5 — There is no decision record system

A search for ADRs returns nothing. `docs/ai/AI_HUB_DECISIONS.md` is the closest
artefact and it is a single narrative file written during one workstream, not a
structured, indexed, referenceable record.

### What these five findings have in common

Every one is a **failure of relationship, not of content.** The four API documents
are individually decent. The problem is that nothing states how they relate, which
is authoritative, or when each was last true.

That is the thesis of this entire document: **knowledge fails at the joins.**

---

## How to read this document

| Marker | Meaning |
|---|---|
| **AVAILABLE** | Implemented; named with its location so nobody rebuilds it |
| **PARTIAL** | Exists and under-reaches; the gap stated precisely |
| **NEW** | Nothing implements it |

Each chapter carries the thirteen elements the brief requires: purpose · scope ·
problems solved · architecture · processes and workflows · ownership and
governance · versioning · relationships with other documents · quality controls ·
KPIs · lifecycle · future evolution · **why this design**.

---

# PART I — THE ARCHITECTURE OF KNOWLEDGE

## Chapter 1 — Document Architecture and Hierarchy

**Status: PARTIAL.** A hierarchy exists implicitly — root contracts, `docs/`,
`docs/ai/`, `docs/archive/` — and is nowhere declared, which is why four API
documents could accumulate without anything objecting.

### Purpose and scope

To give every document a place, and to make the place mean something. Scope is all
written artefacts in the repository that a human or an agent reads to decide
something: contracts, specifications, guides, records, plans and reports. Code
comments are out of scope; they belong to the code.

### Problems solved

Duplication (Finding 1), divergence (Finding 2), unreachability (Finding 3) and
category confusion (Finding 4) are all symptoms of one absence: no declared
hierarchy with rules about what may live where.

### Architecture: five tiers, by lifecycle

The tiers are separated by **how they age**, because that is the property that
determines how they must be governed.

| Tier | Kind | Ages by | Examples | Governance |
|---|---|---|---|---|
| **T0 Constitution** | Rules that bind all work | Amendment only | `CLAUDE.md`, `AGENTS.md`, `CONTRIBUTING.md`, `CODE_OF_CONDUCT.md` | Two-human approval; vault-protected |
| **T1 Master specifications** | The four Groups | Absorbing new sections | Groups 0–3 | Owner approval; living |
| **T2 Canonical references** | One authoritative statement per subject | Drifting from code | `ARCHITECTURE.md`, `DEPLOYMENT.md`, the API reference | Freshness-checked against code |
| **T3 Records** | Immutable statements about a moment | Never — correct at their date for ever | ADRs, decision ledger entries, postmortems, audit reports | Append-only; never edited, superseded instead |
| **T4 Working documents** | Plans, drafts, working notes | Completion | Phase plans, `docs/audit/plans/` | Archived on completion |

### The rule that prevents Finding 1

**Exactly one T2 document per subject.** A subject is a thing a reader would search
for: "the API", "deployment", "the architecture". Four API documents means three
of them are T2 impostors — either merged into the canonical one, demoted to T3
(dated snapshots), or deleted.

The registry (Chapter 2) enforces this: a second T2 document claiming an occupied
subject fails the check.

### Processes and workflows

```
new document proposed
        │
        ├─ what tier?  ── T3/T4 → place and register, done
        │                 T0/T1 → owner approval required
        ▼
      T2 → is the subject already claimed?
              │
              ├─ yes → merge into the canonical document, or justify a split
              │        by narrowing BOTH subjects so neither overlaps
              └─ no  → claim the subject in the registry
```

### Ownership and governance

Every document has exactly one owner. Tier decides who may approve changes. **A
document with no owner is a document nobody will notice is wrong**, and the
registry refuses to accept one.

### Versioning

T0 and T1 carry explicit versions and a change history. T2 carries a
last-verified-against-code date rather than a version, because its correctness is
relative to the code, not to itself. T3 is immutable and versionless — superseded,
never revised. T4 is versioned by git alone.

### Relationships with other documents

This chapter is the parent of every other chapter here. It also constrains Group 2
Chapter 1 (the package register) by analogy: both are about declared structure with
machine enforcement, and they deliberately share that shape so contributors learn
one pattern.

### Quality controls

* Every file under `docs/` has a registry entry declaring tier, owner and subject.
* No two T2 documents claim the same subject.
* No T3 document is modified after creation (git history check).
* Every T2 document has a last-verified date within policy.

### KPIs

| KPI | Current | Target |
|---|---|---|
| Documents with a registry entry | 0 of 190 | 100% |
| Subjects with more than one T2 document | ≥ 1 (the API) | 0 |
| Documents unreachable from the index | ~126 | 0 |
| T2 documents past their freshness window | unmeasured | 0 |

### Lifecycle and evolution

Phase 1: register what exists and tier it — a measurement exercise, not a
rewrite. Phase 2: resolve the T2 collisions found. Phase 3: enforce in CI. Phase
4: the registry gains relationships (Chapter 15) so the hierarchy becomes a graph
rather than a tree.

### Why this design

Because tiering by *subject* or by *audience* — the two obvious alternatives —
would not have caught any of the five findings. Tiering by **how a document ages**
does: it immediately separates the six dated audits from the living architecture,
and it makes "exactly one canonical statement per subject" expressible as a rule a
machine can check. **The failure mode was relationship, so the taxonomy is built
out of relationships.**

---

## Chapter 2 — The Master Index and Document Registry

**Status: NEW.** `mkdocs.yml`'s 64-entry navigation is the closest thing, and it
covers roughly a third of the corpus.

### Purpose and scope

One machine-readable file that knows every document: what it is, who owns it, what
subject it claims, when it was last verified, what it depends on, and what state
it is in. Scope is every file in Chapter 1's five tiers.

### Problems solved

Finding 3 directly — a document not in the index is invisible. And Finding 1
indirectly: a subject claim is only enforceable if subjects are recorded.

### Architecture

`docs/REGISTRY.toml`, one entry per document:

| Field | Purpose |
|---|---|
| `path` | Location, and the identity |
| `tier` | T0–T4 |
| `subject` | The thing it is authoritative about. T2 only, and unique |
| `owner` | One name. Never a team, never empty |
| `state` | `draft` · `active` · `superseded` · `archived` |
| `superseded_by` | Required when state is `superseded` |
| `verified_against` | Code paths this document describes |
| `verified_at` | Date of last verification |
| `depends_on` | Documents this one assumes |
| `groups` | Which of Groups 0–3 it belongs to, if any |

### The generation rule, and why it matters

**The registry is generated from the filesystem and enriched by hand — never the
reverse.** A registry hand-written from memory omits exactly the files nobody
remembers, which are the ones most likely to be stale. The generator walks
`docs/`, adds unknown files as `draft` with no owner, and CI fails while any entry
lacks an owner.

This is the same discipline as Group 0's capability registry and Group 2's package
register: **derive from truth, then annotate.** The three share the pattern
deliberately.

### Processes and workflows

```
CI on every PR
   │
   ├─ walk docs/ ──► file present, no registry entry     → FAIL (name the file)
   ├─               registry entry, no file              → FAIL (dangling)
   ├─               T2 subject claimed twice             → FAIL (name both)
   ├─               entry with no owner                  → FAIL
   ├─               T3 file modified since creation      → FAIL
   └─               T2 verified_at older than policy     → WARN, then FAIL at 2× policy
```

### Quality controls and the anti-decoration rule

The registry must prove it can fail. Per Group 2 Rule 1, the check ships with
injection evidence: an unregistered file is added, CI is confirmed to fail, and
the evidence is recorded. **A registry check that has never rejected anything is
indistinguishable from one that examines nothing** — and this session already
produced a sweep that reported 154 findings while reading no files at all.

### KPIs

Registry coverage (100%), entries without an owner (0), dangling entries (0),
duplicate subject claims (0), and mean age of `verified_at` across T2.

### Why this design

Because an index maintained by hand is a second document that can drift from the
first — and the whole problem is drift. Generating the skeleton means the registry
cannot silently omit a file; requiring an owner means it cannot silently accept
one nobody is accountable for.

---

## Chapter 3 — Source of Truth and Conflict Resolution

**Status: NEW.** Finding 1 is unresolvable today because nothing states precedence.

### Purpose and scope

To make "which one is right?" answerable without asking a person. Scope: any case
where two artefacts make incompatible claims — two documents, or a document and
the code.

### The precedence order

Stated once, and it governs every conflict:

```
running code
      ▲
      │  (code wins: a document describing behaviour the code does not have is wrong)
      │
executable specification (tests, invariants, registries)
      ▲
      │
T0 constitution ─► T1 master specification ─► T2 canonical reference ─► T3 record ─► T4 working
```

Two consequences worth stating explicitly:

1. **Code beats documentation, always.** A document is a claim about code; when
   they disagree the document is out of date. The response is to fix the document,
   not to argue.
2. **A T3 record is never wrong.** It records what was believed at a date. When
   later knowledge contradicts it, the record stands and a new record supersedes
   it. Editing a record destroys the only evidence of what was known when.

### The exception, stated deliberately

Code does *not* beat T0. If the code violates a constitutional rule — a weakened
risk gate, a bypassed approval — **the code is the defect**, not the rule. This
exception exists because the alternative makes the constitution descriptive rather
than binding.

### Processes and workflows

On detecting a conflict:

1. Identify the tiers involved.
2. Apply precedence. The loser is corrected or superseded, never silently deleted.
3. If both are the same tier and the same subject, that is a Chapter 1 violation —
   one must be merged or demoted.
4. Record the resolution in the decision ledger (Chapter 9) if the choice was
   non-obvious.

### KPIs

Open unresolved conflicts (0), mean time to resolution, and conflicts detected
automatically versus by a reader hitting one (the second number should trend to 0).

### Why this design

Because the four API documents have coexisted precisely because there was no rule
to break. Precedence turns an ambiguity into a violation, and a violation is
something CI can find.

---
# PART II — DOCUMENTS AS LIVING OBJECTS

## Chapter 4 — Document Lifecycle, Ownership and Retirement

**Status: PARTIAL.** `docs/archive/` demonstrates that archival happens; nothing
governs when, and nothing distinguishes archived-because-finished from
archived-because-abandoned.

### Purpose and scope

A document is not created and then permanent. It has states, transitions, and an
end. Scope: every registered document.

### Architecture: the state machine

```
   draft ──────► active ──────► superseded ──────► archived
     │             │  ▲               │                │
     │             │  └── revised ────┘                │
     └── deleted   └────────────────────────────► archived (obsolete)
```

| State | Meaning | Who may set it |
|---|---|---|
| `draft` | Written, not yet authoritative. **Readers must not rely on it** | Author |
| `active` | Authoritative for its subject | Owner (T2/T3/T4); owner + approval (T0/T1) |
| `superseded` | A named successor exists; kept for history | Owner, and `superseded_by` is mandatory |
| `archived` | No longer maintained; correct at a date or never | Owner |

### The retirement rule

**A document is retired, never deleted**, with one exception: a `draft` that was
never `active` may be deleted, because nothing ever relied on it.

The reason is Finding 4 inverted. Deleting a document destroys the ability to
answer "what did we believe in July?" — and that question is asked during every
incident review. Archival costs bytes; deletion costs the audit trail.

### Ownership

One owner per document, a person and not a team. A team owner means the document
is owned by whoever last felt guilty about it.

When an owner leaves or a domain moves, ownership transfers explicitly — the
registry entry changes and that change is reviewed. An orphaned document is
detected by CI (Chapter 2) and blocks.

### Processes and workflows

| Trigger | Action |
|---|---|
| The code it describes changes | Owner re-verifies; `verified_at` updated or document corrected |
| A superseding document is written | Old moves to `superseded` with a pointer; both stay reachable |
| A phase or plan completes | T4 moves to `archived` |
| An audit is produced | Created directly as T3, immutable, dated |
| Freshness window exceeded | WARN, then FAIL at twice the window |

### Quality controls

* No `superseded` document without `superseded_by`.
* No `active` T2 document past its freshness window.
* No document in any state without an owner.
* T3 immutability enforced against git history, not against intent.

### KPIs

Documents past freshness (0), orphaned documents (0), mean time from code change
to affected-document re-verification, and archived-versus-deleted ratio (deletions
should be near zero).

### Why this design

Because the failure this prevents is subtle: not a wrong document, but a document
whose *status* is unknown. A reader who cannot tell whether they are holding a
draft, a current contract or a two-year-old snapshot will treat all three the
same, and will be wrong about two of them.

---

## Chapter 5 — Versioning and Change History

**Status: PARTIAL.** Git provides complete change history for everything. What is
missing is *meaning*: a diff shows what changed, not whether the change was
material.

### Purpose and scope

To answer "what changed, and did it matter?" without reading every diff. Scope:
T0 and T1 documents, where changes bind other work.

### Architecture

Git is the substrate and is not replaced. On top of it, T0 and T1 carry an
explicit **change log with materiality**:

| Field | Purpose |
|---|---|
| Version | Semantic: major = a rule changed, minor = content added, patch = clarification |
| Date, author, approver | Accountability |
| Materiality | `binding` (changes what others must do) · `additive` · `editorial` |
| Affects | Which other documents or code this change obliges to change |

The `affects` field is what makes the log actionable. A binding change to `CLAUDE.md`
that obliges a change in `AGENTS.md` should say so, rather than leaving the second
document quietly inconsistent.

### The versioning rule for living documents

A master specification that absorbs a new section gets a **minor** bump. One that
changes an existing rule gets a **major** bump, and every document listing it as a
dependency is flagged for review. This is how a living document stays living
without becoming untrustworthy.

### KPIs

Binding changes without an `affects` list (0), documents flagged by a dependency's
major bump and not reviewed (0), and version drift between a document's stated
version and its change log.

### Why this design

Because "living document" is often a euphemism for "unversioned", and an
unversioned document cannot be depended on — a reader cannot say which version they
built against. Materiality is the minimum metadata that makes the difference between
a typo fix and a rule change visible without reading the diff.

---

# PART III — DECISIONS AND MEMORY

## Chapter 6 — Architecture Decision Records

**Status: NEW.** Nothing in the repository implements ADRs.
`docs/ai/AI_HUB_DECISIONS.md` is a narrative from one workstream — valuable, and
not a system.

### Purpose and scope

An ADR records a decision that was hard, at the moment it was made, including the
options rejected. Scope: any decision that constrains future work and where a
reasonable engineer might later ask "why on earth is it like this?"

### Problems solved

Decisions currently live in commit messages, in one narrative file, and in the
memory of whoever made them. The specific cost is **re-litigation**: a decision
whose reasoning is not recorded is re-argued every time someone new encounters it,
and sometimes reversed by someone who does not know what it was protecting.

### Architecture

`docs/decisions/NNNN-short-title.md`, sequentially numbered, immutable (T3):

| Section | Content |
|---|---|
| Status | `proposed` · `accepted` · `superseded by NNNN` |
| Context | What forced a decision. Facts, not preferences |
| Options considered | Each with its cost. **At least two, or it was not a decision** |
| Decision | What was chosen |
| Consequences | What this makes easy, and what it makes hard |
| Evidence | Measurements that informed it |

### The rule that keeps them honest

**An ADR with one option is not an ADR.** If only one path was considered, the
record is documentation of an implementation, not of a decision, and it belongs in
a T2 reference instead.

### Decisions already made that should be back-filled

These exist in narrative form and should become numbered records, because each is
already being referenced as precedent:

| Decision | Currently recorded in |
|---|---|
| Pointer input gets its own capability rows; `vision.*` stays staged | `AI_HUB_DECISIONS.md` |
| The landmark model is not vendored, because it cannot be executed here | `AI_HUB_DECISIONS.md` |
| Delegation is bounded three ways, not by depth alone | `AI_HUB_DECISIONS.md` |
| A grant crosses the process boundary instead of the ledger | `AI_HUB_DECISIONS.md` |
| 3D is not WebGL; a projected mesh needs no GPU | `AI_HUB_DECISIONS.md` |
| Operational intelligence stays in Group 1; Group 2 owns its inputs | Group 2 Ch 16 |
| Model artefacts and `dashboard/dist/` are committed deliberately | `CLAUDE.md` |
| Python 3.12 is pinned so pickles load on the interpreter that made them | `CLAUDE.md` |

Back-filling is not archaeology for its own sake: each of these is a decision
someone will otherwise reverse.

### Governance, versioning, lifecycle

Immutable once accepted. Superseded by a new record, never edited. Numbered
sequentially so a reference like "see 0007" is stable for ever.

### KPIs

Decisions referenced in review that have no ADR (target 0), ADRs with fewer than
two options (0), and re-litigation events — a decision re-argued with no new
evidence (trending to 0).

### Why this design

Because the alternative already exists here and its limits are visible: one
narrative file is excellent to read and impossible to reference. `AI_HUB_DECISIONS.md`
cannot be pointed at from a code comment, cannot be superseded in part, and grows
without bound. **Numbered, immutable, individually addressable records solve
exactly those three problems** and lose nothing but the pleasure of a continuous
narrative.

---

## Chapter 7 — The Decision Ledger

**Status: PARTIAL.** `ai/gateway/audit.py` records model calls; `ai/improve/proposal.py`
records AI-proposed changes; approvals are recorded in pull requests. There is no
single ledger.

### Purpose and scope

Where an ADR records a *design* decision by a human, the ledger records an
*operational* decision by the system: which model was chosen, which agent was
trusted, which recommendation was accepted, which action was refused. Scope: every
decision made by an automated actor that had a consequence.

### Architecture

One append-only ledger, one schema, regardless of who decided:

| Field | Notes |
|---|---|
| Decision ID, timestamp | |
| Actor | Human, agent or system component |
| Authority tier | Group 2 Ch 10's tiers — what this actor was permitted |
| Context | What was being decided |
| Options and the one chosen | |
| Evidence | Group 1 §2.4's evidence structure |
| Confidence, and its calibration class | From `ai/core/calibration.py` |
| **Outcome** | Filled later, by the linkage in Chapter 8 |
| **Refused?** | And by which control |

### The property that makes it worth having

**Refusals are recorded as first-class entries, not as absences.** A ledger of
actions taken cannot distinguish a system that was never asked from one that
refused — and on a governed platform the refusals are the evidence that governance
worked. Group 2 Chapter 23 makes the same argument for the audit trail; this is the
same principle applied to decisions rather than events.

### Relationships

Feeds Chapter 8 (outcome memory) and Group 1 §48. Consumes Group 2 Chapter 10
(authority tiers) and Group 2 Chapter 6 (change records).

### KPIs

Ledger coverage of automated decisions (100%), decisions with an outcome attached
(target > 80% within the outcome window), and refusals recorded versus refusals
observed in logs — a gap means the ledger is missing entries.

### Why this design

Because the components already record their own decisions in their own shapes, and
that is precisely why no one can answer "what did the platform decide today?" One
schema across all actors is what turns per-component logging into a ledger.

---

## Chapter 8 — Institutional Memory: Outcome, Failure and Lessons

**Status: NEW as a system.** `ai/memory/` stores knowledge tiers; nothing links a
decision to what happened next.

### Purpose and scope

To make the platform experienced rather than merely knowledgeable. Scope: three
linked records — outcome, failure, and lesson.

### Architecture

**Outcome memory** closes the loop on Chapter 7:

```
decision ──► prediction ──► action ──► observed outcome ──► accuracy ──► lesson
```

The **prediction** is the load-bearing field. Without a stated expectation, an
observed outcome has nothing to be compared against and "learning" degrades into
narrative. This is why Group 2 Chapter 6 requires change records to carry an
expected effect: it is the same field, one layer down.

**Failure memory** is not a log. Each entry answers five questions:

| Question | Why it is required |
|---|---|
| What failed? | The observable |
| Why? | The cause, not the symptom |
| How was it detected? | Reveals whether detection was luck |
| How was it fixed? | The repair |
| How is recurrence prevented? | The control added — and its injection evidence |

The third question is the one usually skipped and the most valuable: a failure
found by a customer and a failure found by a test are the same failure with very
different lessons.

### The lessons this session produced, entered as the first records

These are entered here rather than left in a transcript, because that is the entire
point of the chapter:

| Lesson | Failure it came from | Control added |
|---|---|---|
| An assertion a second code path can also satisfy proves nothing | A consent check passed while consent was granted to everybody | Rule 1 injection evidence |
| A precondition destroyed before the assertion means the assertion is untested | Pointer tests fired an event before asserting the initial state | Same |
| A concurrency test that cannot reach the race passes without the lock | Two versions passed with the lock removed | Widen the window deterministically at the race point |
| Shared state leaks between test cases and reads as a pass | A "refuses to draw" test looked at the previous test's output | Scope assertions to their own container |
| A tool can report confidently having examined nothing | A sweep reported 154 findings; ripgrep was reading stdin | Positive control asserted before trusting any sweep |
| Evidence that resolves is not evidence that runs | A worker runtime marked live with no caller | Caller check alongside resolution |
| An injection that silently fails to apply inverts the conclusion | A whitespace mismatch after formatting | Grep to confirm the injection landed |

Seven records. Each has a control, and each control has an owner in Group 2.

### Processes and workflows

Outcome records are opened automatically when a ledger entry is created and closed
by a scheduled job that reads telemetry in the outcome window. Failure records are
opened by an incident declaration (Group 2 Ch 15) and are **required to close it**.

### Quality controls

* No incident closes without a failure record.
* No failure record closes without an answer to all five questions.
* A prevention control with no injection evidence does not count as prevention.

### KPIs

Decisions with outcomes attached, prediction accuracy over time (this is the
platform's actual learning curve), repeat failures with the same root cause
(trending to 0), and lessons with a control versus lessons with only a resolution.

### Why this design

Because "we should remember this" is what everyone says after an incident and
nobody has a place to put. The five questions and the mandatory control are the
minimum structure that turns a recollection into something that changes behaviour.
**A lesson without a control is a wish.**

---
# PART IV — THE BACKLOG AS A SYSTEM

## Chapter 9 — Backlog Architecture and the Four Groups

**Status: PARTIAL.** `docs/ai/BACKLOG_GROUPS.md` establishes the taxonomy and the
coverage map; the backlog itself is still four master documents plus a capability
registry, not a queryable structure.

### Purpose and scope

To make the backlog a system with relationships rather than a list with an order.
Scope: every idea, requirement, capability and improvement not yet delivered.

### The four groups

| Group | Document | Subject |
|---|---|---|
| **0** | AI Hub Master Architecture | What the operator sees and says to the AI |
| **1** | Advanced Intelligence Architecture | How the AI thinks, perceives, decides, learns, evolves |
| **2** | Platform Engineering & Operations | How the platform is built, run, secured, measured |
| **3** | Documentation & Knowledge Governance | How we record, organise and retrieve knowledge about 0–2 |

The brief named three groups. Group 0 is added because the 31-section
specification was already delivered — 233 capability rows, 230 live — and folding
it into Group 1 would have made delivered work invisible and invited its
re-specification.

### Why groups rather than one backlog

Three reasons, in order of weight:

1. **Different cadences.** Group 2 work is scheduled against incidents and
   capacity; Group 1 against research; Group 0 against operator need. One backlog
   forces one prioritisation over three different clocks.
2. **Different reviewers.** A delegation bound and a chart palette need different
   eyes.
3. **Different failure modes.** Group 2's worst case is an outage; Group 1's is a
   confident wrong answer; Group 0's is an unusable screen. Ranking them against
   each other requires a common unit that does not exist.

### Why not more groups

Because every additional group adds a classification boundary, and boundaries are
where items get lost. Four is the fewest that separates the three cadences above
plus the meta-layer that governs them.

### Why this design

Because the alternative — one backlog with tags — was tried implicitly and produced
`ROADMAP_GAPS.md`, `roadmap.md`, six dated audits and a set of completion reports in
`docs/archive/`, none of which reference each other. **Tags do not create
ownership; groups do.**

---

## Chapter 10 — Classification Rules

**Status: NEW.** The rules exist in `BACKLOG_GROUPS.md`; they are not yet
enforceable or exhaustive.

### Purpose

To route any future item to exactly one group, deterministically, so that two
people classifying the same item agree.

### The primary rule — asked in order, first match wins

1. Does it change **how the AI thinks, perceives, decides, learns or evolves**?
   → **Group 1**
2. Does it change **how the platform is built, run, deployed, secured or
   measured**? → **Group 2**
3. Does it change **how we record, organise, govern or retrieve knowledge** about
   1 and 2? → **Group 3**
4. Does it change **what the operator sees and says to the AI**? → **Group 0**

Order matters and is not alphabetical. Rule 1 is first because intelligence
capabilities most often *look* like something else — an operational forecaster
looks like operations, a documentation assistant looks like documentation — and
asking about function first prevents subject matter from capturing them.

### The tie-breaker — the hypothesis test

When an item plausibly satisfies two rules, ask: **does it require a hypothesis?**

* No — it is a threshold, a rule, a transformation → the *subject-matter* group.
* Yes — it forms an explanation and could be wrong → **Group 1**.

Worked examples, including the ones that were genuinely hard:

| Item | Naive | Correct | Why |
|---|---|---|---|
| Auto-rollback when error rate exceeds 5% | Group 1 (it acts alone) | **Group 2** | A threshold. No hypothesis. |
| Correlating a deploy to a latency rise | Group 2 (it is about ops) | **Group 1** | Forms a causal explanation that can be wrong |
| Technical-debt forecasting | Group 2 | **Group 1** | Predicts; Group 2 supplies the inputs |
| Duplicate detection across the backlog | Group 1 (it reasons) | **Group 3** | Rule 3 matches first: it is about knowledge |
| An admin console showing refusals | Group 2 | **Group 2** | Administrator experience, not operator |
| A capability registry caller check | Group 0 | **Group 3** | Governs how capability truth is recorded |

### The one-group rule and its consequence

An item belongs to **exactly one** group. Where it touches another, the owning
group *references* the relationship; it does not copy the content. The interface
is a table, as in Group 2 Chapter 16.

This has a cost worth naming: cross-group work needs coordination that a single
backlog would not. That cost is accepted, because the alternative is the same
content in two documents drifting apart — which is Finding 1 at the backlog level.

### Quality controls

* Every backlog item declares its group at creation.
* Items referenced by two groups are checked for duplication in review.
* Reclassification is recorded with a reason — a pattern of reclassification means
  the rules need sharpening, and that signal is worth preserving.

### KPIs

Items classified into two groups (0), reclassification rate (a rising rate means
the rules are failing), and classification disagreement in review.

### Why this design

Because a classification scheme is only worth having if two people applying it
independently agree. The ordered rules plus one tie-breaker were chosen over a
decision tree precisely because they are short enough to remember, and a rule
nobody remembers is applied inconsistently.

---

## Chapter 11 — Backlog Intelligence: Duplicates, Conflicts and Prerequisites

**Status: NEW.** Group 1 §37 asks for this. The mechanics belong here; the
reasoning belongs there.

### Purpose

To make the backlog notice things about itself that a reader would only find by
reading all of it.

### What it must detect

| Detection | Signal | Example from this platform |
|---|---|---|
| **Duplicate** | Two items proposing the same capability | Four API documents (Finding 1) at the document level |
| **Conflict** | Two items whose designs are incompatible | Two base URLs in the API docs |
| **Missing prerequisite** | An item depending on one not scheduled | Group 1 §16 needs Group 2 Ch 14's correlation key |
| **Combinable** | Two items sharing most of their implementation | §7 capability profiles and §8 rankings |
| **Outdated** | An item whose premise no longer holds | Rows staged as "blocked" that were buildable |
| **Already built** | An item whose capability exists | 26 of Group 1's 64 sections |

The last two are the highest value and the most humbling: **the coverage map found
26 sections already built and six rows wrongly marked blocked.** An item wrongly
believed outstanding costs the same as one wrongly believed done.

### Architecture

Detection runs against structured item records, not prose. Each item carries:
identifier, group, title, a one-line capability claim, dependencies, evidence
locator if built, and state.

The detectors are deliberately **conservative and advisory**. A duplicate detector
that auto-merges will eventually merge two things that differed in a way it could
not see. It proposes; a human decides.

### Quality controls

Per Group 2 Rule 1: each detector ships with injection evidence — a known duplicate
is planted and the detector must find it. A detector that has never found anything
is indistinguishable from one that examines nothing, which is a failure this
session has already produced once.

### KPIs

Duplicates found before implementation versus after (the second is the expensive
kind), prerequisites detected before a blocked start, and false-positive rate — a
detector nobody trusts is not used.

### Why this design

Because the alternative is a human reading 64 sections against a 233-row registry,
which was done once by hand for this analysis and is not repeatable at the cadence
the backlog changes.

---

## Chapter 12 — The Idea Relationship Graph

**Status: NEW.** Group 1 §38 asks for it.

### Purpose

Ideas are not independent. Recording their edges prevents isolated development —
building a curiosity engine that no research engine feeds, or a recogniser nothing
calls.

### Architecture

A directed graph over backlog items and delivered capabilities:

| Edge | Meaning | Enforcement |
|---|---|---|
| `depends_on` | Cannot start until the target exists | Blocks scheduling |
| `enables` | Inverse; used for prioritisation | Advisory |
| `duplicates` | Same capability | Requires resolution |
| `conflicts_with` | Incompatible designs | Requires a decision record |
| `supersedes` | Replaces | Target moves to superseded |
| `evidences` | An item is implemented by a code locator | Feeds Chapter 13 |

### The edge that matters most

`depends_on`, because it is the one that is *wrong by omission*. The delegation
bound was recorded as blocked for months on the grounds that "recursive delegation
does not exist yet to bound" — a `depends_on` edge to the worker boundary would
have made it schedulable the moment that boundary shipped, instead of leaving it to
be re-triaged by hand.

### KPIs

Items with no edges (suspicious — genuinely isolated work is rare), cycles detected
(0; a cycle means the decomposition is wrong), and items unblocked automatically by
a dependency completing.

### Why this design

Because a graph is the only structure in which "what did completing X unblock?" is
a query rather than a memory exercise.

---

# PART V — TRACEABILITY AND CAPABILITY GOVERNANCE

## Chapter 13 — Requirement → Implementation → Test → KPI Traceability

**Status: PARTIAL, and unusually strong for the part that exists.** Group 0's
capability registry links 233 rows to evidence locators that are machine-verified
to resolve.

### Purpose

To answer, for any requirement: is it built, is it tested, is it measured, and does
anything call it?

### Architecture: the four links

```
requirement ──► implementation ──► test ──► KPI
     │                │              │        │
   backlog        evidence       injection  telemetry
    item          locator        evidence    metric
```

| Link | Mechanism | Status |
|---|---|---|
| Requirement → implementation | Evidence locator on the registry row | **AVAILABLE** |
| Implementation → *called* | Caller check | **NEW** |
| Implementation → test | Test naming the capability | PARTIAL |
| Test → *can fail* | Injection evidence | **NEW** |
| Capability → KPI | Telemetry metric per capability | PARTIAL |

### The two NEW links, and why they are the important ones

The registry verifies that an evidence locator **resolves**. It has no opinion
about whether anything **calls** it. That gap produced a live row pointing at a
worker runtime imported by nothing outside its own tests — a dead control inside
the work that closed a row about isolation.

The second gap is the same shape one level down: a test that exists is not a test
that can fail. Five were found in a single session.

Together these give the traceability chain its actual requirement:

> **A capability is traced when its evidence resolves, something calls it, a test
> names it, and that test has been shown to fail.**

Anything less is a chain with a link that only looks connected.

### Quality controls

The caller check has a known limitation, stated rather than hidden: it matches by
symbol, so it would miss a capability invoked through an alias or a dynamic lookup.
It is a screen, not a proof, and its output is triaged rather than trusted.

### KPIs

Rows whose evidence resolves (currently 233/233), rows with a production caller
(unmeasured before this chapter), tests with injection evidence, and capabilities
with a KPI.

### Why this design

Because the registry already proved that machine-verified evidence beats a
hand-maintained checklist — it caught a roll-up claiming live with two of
eighty-two constituents staged. The two new links extend the same idea to the two
places the mechanism was blind, both of which have already produced real defects.

---

## Chapter 14 — Capability and Architecture Governance

**Status: AVAILABLE for capabilities, PARTIAL for architecture.**

### Purpose

To govern what the platform *claims* to be able to do, and to keep the claim honest.

### The registry contract

Every capability row declares: identifier, section, layer, title, state, evidence
locator, and a note. Three rules govern the state field:

1. **A capability nothing calls is `staged`, not `live`.** The dead-control rule.
2. **Roll-ups are derived, never typed.** A layer's state is computed from its
   constituents. Typing one live is how `arch.layer_c.workforce` claimed live with
   two of eighty-two constituents staged.
3. **The identifier constrains the evidence, not the reverse.** Renaming a
   capability to fit what was built is how `agents.system` came to point at
   `platform_engineering` and §11 reported twelve agents with eleven present.

Rule 3 is the one under constant pressure, because it is the one that stands
between a nearly-finished row and a finished-looking one.

### Architecture governance

Group 2 Chapter 1's package register is the artefact; Group 1 §22 and §56 watch it
for drift. This chapter owns the *record* of architectural decisions about it —
which boundaries exist, why, and which are deliberately unagreed.

Currently one boundary is formally unagreed: `data/` versus `data_layer/`. It is
recorded as an open question with a written holding position, which is the correct
state for a boundary nobody has decided — far better than an invented rule that
contributors follow inconsistently.

### KPIs

Rows live without a caller (0), roll-ups typed rather than derived (0), identifier
drift events (0), and boundaries formally unagreed (currently 1, tracked).

### Why this design

Because the registry's value is entirely in its trustworthiness. A registry that
overclaims once is a registry nobody reads afterwards, and the three rules above
are each derived from a real overclaim that happened here.

---
# PART VI — QUALITY, RETRIEVAL AND MAINTENANCE

## Chapter 15 — Documentation Quality Assurance and Freshness

**Status: PARTIAL.** A `doc-freshness-review` skill exists and encodes the drift
problem; `update_docs.yml` and `docs.yml` run. Nothing measures drift.

### Purpose and scope

Documentation rots silently. Unlike code, nothing fails when a document becomes
wrong — it simply misleads, and the cost lands on whoever trusted it. Scope: T0–T2
documents, where being wrong changes what someone does.

### Problems solved

The corpus already carries known, corrected examples of exactly this rot, and they
are worth citing because they show the shape:

* Three documents described `data/` as legacy data files. It is live runtime
  infrastructure with 20 production importers. The wrong description was
  **actionable** — it told contributors to put tick-feed work in the wrong package.
* `CLAUDE.md` stated Python 3.10 "matches the Docker image". The image was already
  3.12 and 3.10 was tested by nothing. Because the stated reason was pickle
  compatibility, anyone following it produced artefacts under an interpreter
  neither CI nor production ever loaded.
* `prop_firm_mode.json` was described as gitignored, and its own comment agreed. It
  is tracked — which invites putting a real credential in a committed file.

Each was a plausible sentence that a careful reader would have believed.

### Architecture: three checks, increasing in cost

| Check | Catches | Cost |
|---|---|---|
| **Structural** | Broken links, missing registry entries, dangling references, orphaned files | Cheap; every PR |
| **Referential** | A document naming a file, symbol, env var or command that no longer exists | Moderate; every PR |
| **Semantic** | A document whose *claims* about behaviour are no longer true | Expensive; scheduled, AI-assisted, human-confirmed |

The referential check is the highest value per unit of effort, and it would have
caught the Python 3.10 error, the `prop_firm_mode.json` error, and every stale path
reference in the corpus. **A document that names a symbol is making a checkable
claim**, and most damaging documentation errors are of exactly that kind.

### Processes and workflows

* Structural and referential run in CI and block.
* Semantic review runs on a schedule against T2 documents whose `verified_against`
  code paths changed since `verified_at`. Changed code plus an unrefreshed document
  is the exact drift signal, and it is computable.
* Findings become proposals; a human confirms. **The AI does not edit T0 or T1.**

### Quality controls on the checks themselves

Per Group 2 Rule 1: each check ships with injection evidence. A deliberately broken
reference is introduced and the check must fail. This chapter is where that rule
matters most, because a freshness check that stops examining anything produces the
most reassuring possible output — silence.

### KPIs

| KPI | Current | Target |
|---|---|---|
| Broken references | unmeasured | 0 |
| T2 documents past freshness | unmeasured | 0 |
| Documents describing code that changed since verification | unmeasured | 0 |
| Documentation errors found by a reader rather than a check | — | trending to 0 |

The final KPI is the honest one: it counts the failures the system did not catch.

### Why this design

Because the three known errors were all *referential* — they named a version, a
file and a package. None required understanding; all required checking. Building
the expensive semantic layer first would have caught none of them sooner.

---

## Chapter 16 — Semantic Search, Retrieval and Context Management

**Status: PARTIAL.** `ai/memory/graph.py` provides a knowledge graph; the route
catalogue is derived and searchable. Neither indexes documentation.

### Purpose

To make the corpus answerable. 190 documents that can only be grepped are 190
documents most people will not find.

### Architecture

Three retrieval modes for three questions:

| Question | Mode | Example |
|---|---|---|
| "Where is the authoritative statement about X?" | Registry lookup by subject | Chapter 2 |
| "What have we said about X anywhere?" | Semantic search over the corpus | NEW |
| "What is connected to X?" | Graph traversal | Chapter 12 |

Only the second is genuinely new, and it must answer with **provenance**: which
document, which tier, which state, when last verified. A search result from an
archived T3 snapshot and one from an active T2 reference are different kinds of
answer, and presenting them identically recreates Finding 1 inside the search box.

### The lesson already paid for

A search that scored every word of three letters or more once matched **850 of
2,234 routes** for a single query, because "current" appears in a third of the
docstrings. A result set that large is the same as no result set.

Two rules follow: **drop stopwords**, and **bound the result set** — a truncated
prefix hides whole areas silently, so the bound must be stated to the reader rather
than applied invisibly.

### Context management

When documentation is retrieved *for a model* rather than a human, two further
constraints apply, both already established elsewhere in the platform:

1. **Retrieval is not permission.** Seeing a document does not authorise acting on
   it. The allowlist refuses independently.
2. **Classification governs retrieval.** A `SOVEREIGN` document is not retrievable
   into a context bound for an external provider — Group 2 Chapter 13.

### KPIs

Query success rate, provenance completeness (100% — no result without tier and
state), and result-set sizes above the bound (0).

### Why this design

Because search without provenance is worse than no search on a corpus that
contains four conflicting API documents: it will confidently return one of them.

---

## Chapter 17 — AI-Assisted Documentation Maintenance

**Status: PARTIAL.** `ai/improve/` walks code, produces findings and prepares
proposals requiring two human approvals; the vault protects paths from
AI-proposed change.

### Purpose

To let the AI do the work documentation maintenance actually is — finding drift,
proposing corrections, detecting duplicates — without letting it become the author
of its own rules.

### The authority boundary

| Tier | AI may | AI may not |
|---|---|---|
| T0 Constitution | Report drift | Propose or edit. Ever. |
| T1 Master specs | Propose an addition | Change a rule, or apply anything |
| T2 References | Propose a correction with evidence | Apply without review |
| T3 Records | Read | Modify — records are immutable |
| T4 Working | Draft and update | — |

The T0 line is absolute and worth its own sentence: **the AI may not propose
changes to the rules that govern it.** Not because a proposal would necessarily be
bad, but because a system that can propose amendments to its own constraints has
constraints that are negotiable, and the whole architecture rests on them not being.

### What the AI is genuinely good at here

Naming it honestly, because the boundary above is only defensible if the value is
real: it does not get bored. Checking 190 documents for broken references, or
cross-referencing 64 spec sections against 233 registry rows, is work humans do
badly at volume and skip when tired. That is the value — thoroughness, not
judgement.

### Quality controls

* Every AI-produced proposal carries evidence that resolves.
* Two human approvals for anything touching a vault path.
* The proposer is never the approver.
* AI-proposed changes are marked as such in the change history, permanently.

### KPIs

Proposal acceptance rate (very low means noise; very high means rubber-stamping —
both are bad), drift found by AI versus by a reader, and T0 change proposals
attempted (0, structurally).

### Why this design

Because the failure mode is not a bad edit — it is **the appearance of maintenance**.
A corpus that an AI has confidently reviewed and left wrong is more dangerous than
one nobody has looked at, because the first is trusted. Hence: evidence on every
proposal, humans on every application, and the constitution off-limits.

---

# PART VII — MEASUREMENT AND EVOLUTION

## Chapter 18 — KPIs, Lifecycle and the Path Forward

**Status: NEW.**

### The consolidated measurement

| Domain | Leading | Lagging |
|---|---|---|
| Structure | Registry coverage, orphaned documents | Duplicate subjects |
| Freshness | Documents past window, changed-code-unrefreshed | Errors found by readers |
| Decisions | ADR coverage of hard decisions | Re-litigation events |
| Memory | Outcomes attached to decisions | Repeat failures, same root cause |
| Backlog | Duplicates found before implementation | Wasted work on already-built items |
| Traceability | Rows with callers, tests with injection evidence | Dead controls found in production |

### The health rule, restated

As in Group 2: **no single index.** Knowledge health is a vector with a
worst-element rule, and the red domain is named. A composite that averages a
missing decision record against a stale link hides the first.

### The prioritised gap list

| # | Gap | Chapter | Priority | Why |
|---|---|---|---|---|
| 1 | Document registry with owners and tiers | 2 | **Critical** | Everything else queries it; ~126 documents are currently invisible |
| 2 | Resolve the four API documents | 1, 3 | **Critical** | A live conflict — two different base URLs, no authority marker |
| 3 | Referential freshness check | 15 | High | Would have caught all three known documentation errors |
| 4 | Caller check on the capability registry | 13, 14 | High | Closes the gap that produced a dead control marked live |
| 5 | Injection evidence as a traceability link | 13 | High | Five tests that could not fail, in one session |
| 6 | ADR system + back-fill the eight known decisions | 6 | High | Each is already cited as precedent with no citable record |
| 7 | Failure memory with the five questions | 8 | High | Seven lessons currently exist only in a transcript |
| 8 | Root/docs duplicate contracts resolved | 1, 3 | Medium | `CONTRIBUTING`, `DEPLOYMENT` diverged |
| 9 | Outcome memory linkage | 8 | Medium | Needs Group 2 Ch 6 change records first |
| 10 | Backlog item records + duplicate detection | 11 | Medium | Manual coverage mapping is not repeatable |
| 11 | Idea relationship graph | 12 | Medium | Would have unblocked the delegation bound automatically |
| 12 | Decision ledger unification | 7 | Medium | Three partial ledgers today |
| 13 | Semantic search with provenance | 16 | Low | Registry lookup covers the common case first |
| 14 | Tier the six dated audits, archive completed plans | 1, 4 | Low | Cheap, and clears the category confusion |

### Lifecycle of this document

Group 3 is T1: living, versioned, and it absorbs new sections rather than being
rewritten. It is also the only document that governs its own governance, so a
change here is a binding change and carries an `affects` list per Chapter 5.

### Why this design, for the whole document

Because the temptation with a knowledge-management specification is to design an
elegant system and hope the corpus grows into it. This one is built backwards from
five measured findings — four API documents, two diverged contracts, 126 invisible
files, six mistiered audits, no decision records — and every chapter traces to at
least one of them.

The five findings share one cause, which is the thesis: **knowledge fails at the
joins.** Not the writing. The relationships between the writing.

---

## Appendix A — Scope boundaries

| Topic | Owning group |
|---|---|
| What the operator sees and says | Group 0 |
| Cognition, memory *semantics*, curiosity, evolution | Group 1 |
| Infrastructure, delivery, security, observability | Group 2 |
| Trading strategy and risk semantics | Trading architecture |

Group 1 §31–33 (institutional, outcome, failure memory) and Group 3 Chapter 8
overlap deliberately and are **not** duplicates: Group 1 owns how the AI *uses*
memory to reason; Group 3 owns how the records are structured, owned and retained.
The interface is the record schema in Chapter 8.

## Appendix B — Evidence base

Measured on the working tree:

* 190 files under `docs/`; 173 markdown; 66 in `docs/` root
* `mkdocs.yml` navigation: 64 entries → ~126 files unreachable
* Four API documents: 439 + 1,170 + 625 + 851 = **3,085 lines**, two conflicting base URLs
* `CONTRIBUTING.md` 126 (root) vs 375 (docs); `DEPLOYMENT.md` 656 vs 834
* Six dated audit documents in the living-documents directory
* ADR search: no results
* 12 root-level contract documents
* Existing machinery: `doc-freshness-review` skill, `update_docs.yml`, `docs.yml`,
  `docs/archive/`, `ai/memory/graph.py`, `ai/improve/` proposal flow, `ai/vault/`

## Appendix C — Open questions

1. **Where the four API documents consolidate to.** Merging is obvious; which file
   survives, and whether the endpoint listing stays separate from the guide, is a
   decision for whoever owns the API surface.
2. **Whether `docs/` root should be flattened into subject directories.** 66 files
   in one directory is navigable by search and not by browsing. Deferred until the
   registry exists, because the registry makes the answer measurable.
3. **Retention period for T3 records.** Immutability is settled; how long they are
   retained is not, and it interacts with Group 2 Chapter 25.
