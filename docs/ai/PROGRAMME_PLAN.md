# The remaining programme — audit, sequence, and effort

**Status:** living. Supersedes itself; not a dated snapshot.
**Measured:** 2026-09-09. Every figure below came from a script in this
repository, named beside it. Re-run rather than trust: `python scripts/backlog_report.py`.

**Why living rather than `AUDIT_2026-09-09.md`:** Group 3 item 14 is *"tier the
six dated audits and archive completed plans"*. Adding a seventh would grow the
debt this document is meant to help pay down.

---

## 1. Where the platform actually is

| Measured | Value | Instrument |
|---|---:|---|
| Backend tests | **21,732 pass · 0 fail · 30 skipped** | `pytest -m "not slow and not e2e"` |
| Frontend tests | **2,640 pass · 0 fail** (135 files) | `vitest run` |
| CI gates | **14 of 14 pass** | `scripts/ci/gate_*.py` |
| Gate injection evidence | **25 gates · 25 proven able to fail · 0 unproven** | `scripts/gate_evidence.py` |
| Static security analyzer | **0 findings** | `security/code_analyzer.py` |
| Invariant predicates | **339 across 34 modules** | `invariants/registry.py` |
| Spec capabilities | **233 rows · 233 live · 0 staged** | `ai/hub/capabilities.py` |
| Decision records | **12, all well formed** | `scripts/adr.py --check` |
| Documentation figures | **16 stated · 0 drifted** | `scripts/doc_metrics.py` |
| npm advisories | **0** (frontend and dashboard) | `npm audit` |
| Python advisories | **6 across 3 packages** | `pip-audit` |
| Debt markers (TODO/FIXME) | **4** in 708k lines | `grep` |

**Scale:** 708,885 Python LOC across 1,882 files; 124,027 TypeScript LOC across
444; 281,758 lines of test across 835 files; 83 top-level packages.

The instrumentation is the unusual thing here. Most of this audit was reading
gauges the repository already carries, which is why it can be re-run in twenty
minutes rather than re-derived.

---

## 2. New findings from this audit

Nothing critical. Three dependency advisories, assessed for **reachability**
rather than reported as a list, because a CVE in a package nothing calls is a
different problem from one in the money path.

### F1 · `ecdsa` 0.19.2 — Minerva timing attack (P1)

`PYSEC-2026-1325`. A timing attack on P-256 can leak the nonce and, from it, the
private key. Key generation, signing and ECDH are all affected. **No fix version
exists.**

**Reachable.** Pulled in by `hdwallet`, which `payments/crypto/address_generator.py`,
`payments/crypto/bitcoin.py` and `api/billing.py` use for BIP44/BIP84 derivation
— deposit addresses. That is the money path.

Narrow in practice: the attack needs an attacker able to observe timing across
many derivations. It is not remote code execution. But there is no upgrade to
take, so this is a decision, not a patch: accept with a recorded reason, move
derivation off the request path, or replace `hdwallet`.

### F2 · `chromadb` 1.5.9 — four CVEs including pre-auth RCE (P2, not reachable)

`PYSEC-2026-311` (pre-auth RCE), `CVE-2026-45830`, `CVE-2026-45831`,
`CVE-2026-45833`. **No fix version exists.**

**Not reachable as deployed.** Every one of the four targets the ChromaDB
**HTTP server** — `/api/v2/tenants/...` endpoints, cross-tenant authorization,
`SimpleRBACAuthorizationProvider`. `research/vector_store.py` constructs
`chromadb.PersistentClient(path=...)`, an embedded client, and no
docker-compose, k8s or helm manifest starts a Chroma service.

It is genuinely used — `brain/llm_agent.py`, `ml/rl_agent.py` and
`ml/signal_scorer.py` all import it — so removing it is not free. The right
control is a gate asserting we never construct an `HttpClient` or start a
server, so the assessment stays true rather than becoming folklore.

### F3 · `nltk` 3.10.3 — model-path sandbox bypass (P2)

`PYSEC-2026-3740`. Caller-controlled model paths escape the enforced root.
**No fix version exists.** Pulled in by `textblob`, used by `news/sentiment.py`.
Our model paths are TextBlob's own corpora, not caller-controlled, so the
precondition does not hold here.

### F4 · The caller screen's 38 rows are mostly screen artifact (P3)

`scripts/capability_callers.py` flags 38 of 157. **34 of those show `prod=1`** —
one production reference, which is the definition site itself. Only the four §4
roll-ups show `prod=0`, and those were already established as false positives:
`layer_state` is called inside the module that defines it.

The screen is behaving as documented. What it needs is not fixing but a
narrower question, and the package register gives it one.

---

## 3. The one thing to build first, and why

**The package ownership register** (Group 2 Chapter 1, ranked item 10).

It is not the largest item or the most interesting. It is first because more
depends on it than on anything else outstanding:

| It closes | How |
|---|---|
| **INV-01** every subsystem has a documented purpose | the register's `purpose` field |
| **INV-02** defined inputs and outputs | its declared edges |
| **INV-03** an owner or governance authority *(the only NEW invariant)* | its `owner` field |
| **INV-04** measurable KPIs | per-package KPI declaration |
| **INV-07** versioning and lifecycle rules | per-package lifecycle |
| **INV-14** retired capabilities leave no undocumented dependencies | edges make retirement checkable |
| ADR 0011's compromise | the change record's risk tier stops being a path table |
| 197 unowned documents | document ownership follows package ownership |
| the 38-row caller screen | ownership turns "inspect this" into "ask this person" |
| Group 2 item 18 (debt budget) | needs modification frequency per package |
| Group 2 item 22 (`data/` ÷ `data_layer/`) | is an ownership question |

**Six of the eleven outstanding constitutional invariants close from one build.**
Nothing else outstanding has that shape.

It also must not duplicate `scripts/ci/gate_g_import_discipline.py`, which
already enforces canonical-versus-legacy edges and carries its own
`KNOWN_VIOLATIONS` ratchet. The register declares the edges; gate G stays the
thing that enforces them.

---

## 4. The sequence

Ordered by dependency, not by size. Effort is in **work sessions** — one session
is a complete slice: failing test, implementation, evidence, documentation,
commit. Roughly ten such slices fit in a long day.

### Phase 1 — Ownership · 2 sessions

| # | Item | Sessions |
|---|---|---:|
| G2-10 | Package ownership register, edges declared not re-enforced | 1.5 |
| — | Document ownership pass: the 197 unowned follow package owners | 0.5 |

**Unblocks:** six invariants, three ranked items, the caller screen, ADR 0011.

### Phase 2 — Authority and refusal · 2.5 sessions

| # | Item | Sessions |
|---|---|---:|
| G2-7 | Authority Tiers 0 and 3 (observe-only, and the top tier) — closes INV-09 | 1 |
| G2-15 | Routing decisions record why they chose a path — a second ledger caller | 0.5 |
| G2-17 | Administrator console, starting with refusals | 1 |

The ledger already records refusals with the control that produced them, so the
console has content on day one. **Needs a `flow-prototype` approval surface
before production UI** — that is a stop condition, not a formality.

### Phase 3 — Correlation and incidents · 3.5 sessions

| # | Item | Sessions |
|---|---|---:|
| G2-5 | Correlation key joining metrics, traces, logs and change records | 1.5 |
| G2-13 | Latency budgets per stage | 1 |
| G2-11 | Incident declaration, timeline, postmortem | 1 |

Change records landed in §E24, so "what deployed just before latency rose"
becomes answerable here. Failure memory already exists for the postmortem half.

### Phase 4 — Delivery safety · 4 sessions

| # | Item | Sessions |
|---|---|---:|
| G2-8 | Stated degradation order, trading path excluded — closes INV-05 | 1.5 |
| G2-9 | Progressive delivery and automated rollback | 1.5 |
| G2-12 | Capacity forecasting and load-shed policy | 1 |

Money path. Article IX is enforced in four places today with no stated order of
what is shed first, which is the defect this phase exists to close.

### Phase 5 — Boundaries and supply chain · 5 sessions

| # | Item | Sessions |
|---|---|---:|
| G2-4 | Data egress and sovereignty boundary — closes INV-06 | 1.5 |
| G2-3 | Acceleration answer-invariance: cache age carried, downgrade visible | 1.5 |
| G2-16 | SBOM and dependency provenance | 0.5 |
| G2-19 | Execution-target abstraction and capability probe | 1 |
| F1–F3 | The three advisories: assess, decide, gate, record as ADRs | 0.5 |

### Phase 6 — Knowledge · 3 sessions

| # | Item | Sessions |
|---|---|---:|
| G3-5 | Injection evidence as a traceability link | 0.5 |
| G3-10 | Backlog item records with duplicate detection | 1 |
| G3-11 | Idea relationship graph | 1 |
| G3-14 | Tier the six dated audits, archive completed plans | 0.5 |

### Phase 7 — The rest · 3 sessions

| # | Item | Sessions |
|---|---|---:|
| #13 | Coverage on `api/superadmin/ml_ai.py` and `system_health.py` | 1 |
| #16 | A real calibration metric recorded at training time | 1 |
| G2-20 | API versioning and deprecation policy | 0.5 |
| G2-21 | Retention and classification policy | 0.5 |

### Phase 8 — the four that were blocked · 3 sessions

**All four decided on 2026-09-09.** Nothing in the programme now waits on the
owner. Each carries its decision record.

| # | Item | Decision | Sessions |
|---|---|---|---:|
| G2-22 | `data/` ÷ `data_layer/` boundary | **ADR 0013** — split by role, no code moves | 0.5 |
| G2-14 | Nightly `slow` / `e2e` run | **ADR 0014** — nightly, not per-PR (209 tests) | 0.5 |
| G3-8 | Root/`docs` duplicate contracts | **ADR 0016** — root wins; ARCHITECTURE re-subjected | 0.5 |
| G3-13 | Semantic search with provenance | **ADR 0015** — adopt embeddings, `faiss-cpu`, no torch unless measured | 1.5 |

G3-13 grew from 1 session to 1.5: ADR 0015 adopts the feature over a
recommendation against it, and the two constraints that bound the cost —
CPU-only index, and an embedder evaluated before reaching for `torch` — are work
that a plain `pip install sentence-transformers` would not have been.

---

## 5. How long

**≈ 28.5 sessions.** Nothing waits on a decision any more — all four were made
on 2026-09-09. The figure moved from 28 because ADR 0015's constraints add half a
session to G3-13.

What that means in calendar time depends entirely on how much of it runs in
sessions like today's. For reference, today closed ten slices: the coverage-gate
repair, six suite failures, the git hooks, the deployment guides, §18's camera
end to end, the ADR system, the decision ledger, change records, the warn
policy, and the spec correction.

| Pace | Calendar |
|---|---|
| Sessions like today (≈10 slices) | **3 working days** |
| One focused session a day | **4 weeks** |
| Two or three sessions a week | **10–12 weeks** |

The honest caveat: Phases 3 to 5 touch the trading path and telemetry, where the
work is less predictable than governance plumbing. Treat those estimates as
±50%, and Phases 1, 2, 6 and 7 as ±20%.

**None of it is blocked on anything but your four decisions**, and only 2.5
sessions sit behind them.

---

## 6. Your decisions — all four made

Taken on 2026-09-09. Three matched the recommendation; one was overruled, which
is recorded as such rather than smoothed over.

| Decision | Chosen | Record |
|---|---|---|
| **A2** `data/` ÷ `data_layer/` | Split by role, as a rule. No code moves | ADR 0013 |
| **A3** Nightly `slow`/`e2e` | Nightly, not per-PR. 209 tests that gated nothing | ADR 0014 |
| **#17** Embedding news sentiment | **Adopt** — against the recommendation to decline | ADR 0015 |
| Doc authority | Root wins for contributing and deployment; ARCHITECTURE re-subjected | ADR 0016 |

**On #17.** The recommendation was to decline: `faiss` is absent, the usual path
pulls `torch`, and `requirements.txt` already pins around torch to avoid
accidental GPU builds. The owner adopted it anyway, knowing that. ADR 0015 keeps
the objection visible and turns it into two constraints — `faiss-cpu` only, and
an embedder measured before `torch` is accepted — so the cost stays bounded
rather than arriving by default.

**Still open, blocking nothing:** `DRIFT_BLOCK`'s default (task #6), and the two
findings this audit raised — the `ecdsa` advisory in the payments path (#26) and
gating ChromaDB to embedded use (#27).

## 7. Standing debt — shrinks, never finishes

Held by ratchets: the number may only fall, and a new violation blocks.

| Debt | Now | Mechanism |
|---|---:|---|
| Documents with no owner | 197 | `scripts/docs_registry.py --check` — Phase 1 addresses most |
| Stale references in living documents | 41 | `scripts/docs_freshness.py` |
| Modules with recorded coverage debt | 235 | `docs/COVERAGE_UNMEASURABLE.txt` — measured, not a snapshot: `scripts/doc_metrics.py --check` verifies it |
| Capabilities flagged with no production caller | 38 | `scripts/capability_callers.py` — F4 above; mostly screen artifact |
| Contested document subjects | 3 | needs the authority decision |
| Change records stating an expected effect | 29% | `deployment/change_records.py --report` — advisory by ADR 0012 |

That last one is the one to watch. If it does not rise, the warning is being
scrolled past and the honest response is `CHANGE_RECORD_ENFORCE=1`, not a lower
target.
