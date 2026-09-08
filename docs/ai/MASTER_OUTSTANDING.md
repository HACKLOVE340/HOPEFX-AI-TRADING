# What is left to build, fix or pick

**Tier:** T2 — canonical reference · **Owner:** hacklove340 · **Status:** current as at 2026-09-08

> **Updated the same day** when the complete Group 4 document (Volumes I–XX)
> arrived. What it changed is in §F. It did not shrink this list; it added two
> constitutional Articles, one new High item, and one new control.

This is the single place that answers "what is outstanding". It has two halves and
they are not equally trustworthy, so they are separated:

* **§A — Decisions only the owner can make.** Four of them. Nothing below them
  moves until they are picked, and each is stated with what it costs either way.
* **§B — Work.** Ranked, with the measurement behind each item.

> **The numbers in §B go stale.** They were measured on 2026-09-08. Re-run
> `python scripts/backlog_report.py` for the current ones — that command reads
> the registries, the specifications and the code, and its answer is always
> today's. A list typed into a message is wrong the moment somebody acts on it.
> This document holds the *shape* of the backlog; the report holds the numbers.

---

## §A — Decisions to pick

These are not blocked on engineering. They are blocked on someone deciding.

### A1. Backup and restore — how much recovery is enough? *(partly delivered)*

**Delivered in Phase R1**, because it did not need the decision: `database/restore.py`
verifies before it restores and refuses six ways a backup arrives worthless, and the
round trip is proven by execution — SQLite in the fast suite, a real `pg_dump`
restored into a real PostgreSQL 16.13 database with matching checksums in the
integration suite. `celery_app.database_backup` now verifies what it wrote.
`docs/runbooks/database-restore.md` is the 3am procedure.

**Building it found two live defects a survey could not have:**

* **SQLite backups of a WAL database restored to nothing.** Committed rows live in
  the `-wal` sidecar; the backup copied the main file alone. Reproduced by
  execution. The nightly job logged success every time. **Any SQLite backup taken
  before 2026-09-08 is suspect** — the runbook carries a sweep that finds them,
  and `--verify` refuses them by name.
* **`pg_dump` was buffered entirely in memory** before writing, so a
  production-sized database would have exhausted the worker mid-incident.

**Still yours to pick, and now the only thing blocking the rest:**

| Question | Why it cannot be defaulted |
|---|---|
| **RPO** — how much data may be lost? | Today it is **24 hours by schedule, not by decision**. That number came from a cron entry, not from anyone weighing it |
| **RTO** — how long may a restore take? | Decides whether snapshots are enough, or whether this needs WAL archiving and point-in-time recovery |

Those two answers decide whether PITR gets built. Everything else in this item is
done and tested.

### A2. `data/` ÷ `data_layer/` — where does new market-data code go?

**The measurement.** `data_layer/` is 19,610 LOC with 86 production importers;
`data/` is 6,259 LOC with 20; `market_data/` is 4,031 with 6. All three are live.
**The boundary between them is documented nowhere.**

**The cost of not deciding:** it already caused one defect class — contributors
were told to put tick-feed and depth-of-market work in `data_layer/`, which
splits one subsystem across two packages. The holding position (extend whichever
package the module already lives in, and say which in the PR) is workable but
guarantees the split widens.

**Recommendation:** decide it as a one-paragraph ADR, not a refactor. The
refactor can wait; the rule cannot.

### A3. Nightly `slow` and `e2e` runs — pay the CI minutes or not?

**The measurement.** Both markers are skipped in CI, always. Process isolation
(`ai/jobs/isolation.py`) is specified in detail and **exercised by nothing that
runs**. So is a good deal of the e2e surface.

**Either way costs something:** running them nightly costs CI minutes; not
running them means the isolation guarantees are claims. This needs a decision,
not a default — the default is already in force and it is "never run them".

### A4. Does Group 2 own deterministic auto-remediation?

**The line drawn** in Group 2 Chapter 16 is *"does it require a hypothesis?"* —
auto-rollback on an error-rate breach is a threshold (Group 2); auto-rollback on
an anomaly score is inference (Group 1). It has not yet met a borderline case.
Not urgent. Recorded so the first borderline case is decided rather than drifted.

---

## §B — Work, ranked

Numbers measured 2026-09-08. Re-run `scripts/backlog_report.py` for current ones.

### B0. Where each number comes from

| Source | What it measures | Reading on 2026-09-08 |
|---|---|---|
| `ai/hub/capabilities.py` | Specification capabilities and their evidence | 233 rows · 230 live · 3 staged · 233/233 evidence resolves |
| `scripts/capability_callers.py` | Live rows with no production caller | 154 screened · **37 flagged** |
| `docs/REGISTRY.toml` | Documents, tiers, owners, contested subjects | 201 registered · **197 unowned** · 3 contested subjects |
| `docs/FRESHNESS_BASELINE.toml` | Stale references in living documents | **41 outstanding** |
| `GROUP4_CONSTITUTION.md` | Architectural invariants | 21 recorded · **11 not yet AVAILABLE** |
| `invariants/registry.py` | Do the constitution's cited predicates exist? | 12 named · **12 resolve** ✓ |
| `scripts/group4_preservation.py` | Has any title from either Group 4 source been dropped? | 304 titles · **0 missing** ✓ |
| `scripts/gate_evidence.py` | Which gates have been proven able to fail? | 23 gates · 16 proven · **7 unproven** |

### B1. Critical — do these first

| # | Item | Where | Why it ranks here |
|---:|---|---|---|
| ~~1~~ | ~~**Tested backup and restore**~~ | Group 2 Ch 9 | **DONE — Phase R1.** Round trip proven against SQLite and live PostgreSQL. Point-in-time recovery and a decided RPO remain and inherit the rank — see §A1 |
| 1 | **Rule 1 injection evidence — 7 of 23 gates still unproven** | Group 2 Ch 0, 19, 20 | **Mechanism built (R2); ratchet 13→10→8→7 (R3–R5).** 16 proven. Proving them keeps finding defects: gate M passed with no dataset, and the secret scanner skipped real credentials containing `xxx` or `none`. Run `python scripts/gate_evidence.py` for the current list |

### B2. High

| # | Item | Where |
|---:|---|---|
| 2 | Acceleration answer-invariance — cache age carried, downgrade always visible | Group 2 Ch 28, 32, 33 |
| 3 | Data egress and sovereignty boundary | Group 2 Ch 13 — blocks Group 1 §23/§24 |
| 4 | Correlation key joining metrics, traces, logs and changes | Group 2 Ch 14 — blocks Group 1 §16 |
| 5 | Change records carrying their expected effect | Group 2 Ch 6 — blocks Group 1 §16, §21, §32 |
| 6 | Authority Tiers 0 and 3 (four of six exist) | Group 2 Ch 10 · INV-09 · Group 4 Ch 6 |
| 7 | Stated degradation order, trading path excluded from it | Group 2 Ch 34 |
| 8 | Progressive delivery and automated rollback | Group 2 Ch 5 |
| 9 | Package ownership register with enforced edges | Group 2 Ch 1 · INV-01 |
| 10 | Injection evidence as a traceability link | Group 3 Ch 13 |
| 11 | ADR system, back-filling the eight known decisions | Group 3 Ch 6 |
| 12 | Failure memory with the five questions | Group 3 Ch 8 — seven lessons currently live only in a transcript |
| 13 | **Decision Governance** — Architecture Decision Registry and Decision Ledger carrying *expected outcome, actual outcome, lessons* | Group 4 Ch 9 · Group 3 Ch 6 · Group 2 Ch 6 |
| ~~14~~ | ~~**The second, unverified backup path**~~ | Group 2 Ch 9 |

**Item 14 was found while building Phase R1, deliberately left alone, and is now
DONE (2026-09-08).** `trigger_backup` no longer reimplements `pg_dump`/`shutil`
itself — it calls `database/backup.py::run_backup()` and then
`database/restore.py::verify_backup()` before reporting success, the same
verified path Phase R1 proved for the scheduled backup job. Folding it into the
restore change would have widened that change past what could be reviewed as
one thing, so it stayed its own commit with its own tests, as recorded here.

**Fixing it found a defect this entry did not name.** The `except Exception`
around the old dump logic set `status = "completed"` unconditionally — so a
missing `pg_dump` binary, a permission error, or a timeout all reported success,
with `size_mb: 0.0` and a `location` nothing had written. Same shape as gate M
and gate K in §E3/§E4: success reported for work that did not happen. Fixed by
making failure (including a backup that writes but does not verify) report
`status: "failed"`, `ok: false`, and a `safe_error()`-scrubbed reason rather than
the raw exception string — a first pass returned `str(exc)` directly and
`tests/unit/test_exception_info_exposure.py`'s ratchet caught it. Proven by
`tests/unit/test_superadmin.py::TestBackupTriggerEndpoint` (3 tests: failed run,
verified success, and a backup that writes but fails verification — each
red-green checked by reverting the fix and confirming the test fails first).

**Item 13 is not a fourth thing.** It is items 11 (ADR system) and 5 (change
records with expected effect) seen from a third source, and the complete Group 4
document names the field the other two omit: *actual* outcome compared against
expected. Build them as one artefact or you get half a ledger three times.

### B3. Medium

Group 2: incident declaration and postmortem (Ch 15) · capacity forecasting and
load-shed (Ch 7, 34 — Redis reports `maxmemory` unlimited on a bounded host) ·
latency budgets per stage (Ch 17) · nightly `slow`/`e2e` (Ch 5, 19 — decision A3)
· routing decisions recording their reason (Ch 30) · SBOM and dependency
provenance (Ch 12) · administrator console starting with refusals (Ch 26) · debt
measurement and budget (Ch 22) · execution-target abstraction and capability
probe (Ch 29).

Group 3: root/docs duplicate contracts (Ch 1, 3) · outcome memory linkage (Ch 8)
· backlog item records and duplicate detection (Ch 11) · idea relationship graph
(Ch 12) · decision ledger unification (Ch 7).

### B4. Low

API versioning and deprecation policy (Group 2 Ch 21) · retention and
classification policy (Ch 25) · `data/` ÷ `data_layer/` boundary (Ch 1, 25 —
decision A2) · semantic search with provenance (Group 3 Ch 16) · tiering the six
dated audits and archiving completed plans (Group 3 Ch 1, 4).

---

## §C — Standing debt, not a project

These do not finish; they shrink. Each is held by a ratchet: the current number
is the baseline, new violations block, and the baseline may only fall.

| Debt | Baseline | Mechanism |
|---|---:|---|
| Documents with no owner | 197 | `scripts/docs_registry.py --check` |
| Stale references in living documents | 41 | `scripts/docs_freshness.py` |
| Live capabilities with no production caller | 37 flagged of 154 | `scripts/capability_callers.py` |
| Contested document subjects | 3 | named in `docs/REGISTRY.toml` |

**The caller sweep is a screen, not a verdict.** Symbol matching misses aliases
and dynamic lookup, so each of the 37 is one row to *inspect*, not one defect to
fix. The three `arch.layer_*` rows at `prod=0` are the ones to look at first.

## §D — Staged, not live

Three capability rows are staged: `arch.layer_a.presence` (§4),
`vision.gesture` and `vision.pointing` (§18). Staged means the specification is
written and the evidence locator resolves, but the row is not claimed live.

## §E — Constitutional invariants not yet AVAILABLE

Eleven of twenty-one. INV-03 (*every subsystem has an owner or governance
authority*) is the only **NEW** one, and it is the same fact as the 197 unowned
documents in §C — one gap, two views. The other ten are PARTIAL: they exist and
under-reach, with the shortfall named per row in `GROUP4_CONSTITUTION.md`.

---

## How this document stays honest

It is registered in `docs/REGISTRY.toml` at T2 and checked by
`scripts/docs_freshness.py` like every other living document: a path it names
that stops existing is a blocking finding, not a silent rot. The counts, though,
are a snapshot by nature — which is why the generated report exists and why this
document points at it rather than trying to be it.


---

## §E2 — What Phase R1 changed (2026-09-08)

| | |
|---|---|
| Built | `database/restore.py` · `docs/runbooks/database-restore.md` · `tests/integration/test_database_restore_postgres.py` |
| Fixed | The WAL backup defect · the misleading `.sql.gz` name · `pg_dump` memory buffering · rotation that would have stopped silently at the extension change |
| Proven | 23 tests. Every refusal by handing the code the exact broken artefact; the round trip against a live PostgreSQL 16.13 with matching checksums |
| A control that could not fail | **One of my own**, caught by injection: a "leaves no partial file" test that the atomic staging already guaranteed, so deleting the cleanup did not fail it. Replaced with the falsifiable property — an existing database is untouched when a restore fails |
| Operational consequence | **Sweep the backup directory.** Any SQLite artefact from before today may restore to nothing, and `--verify` is what tells you which |

## §E3 — Phase R3: turning the Rule 1 ratchet (2026-09-08)

Five gates were scoped by consequence. **Three proven, two deferred**, and
proving them found two more dead controls.

| Gate | Outcome |
|---|---|
| `check-secrets` | **Proven, and a bypass fixed.** The placeholder allowlist matched the whole line, so a real credential containing `xxx`, `none`, `null` or `tbd` was skipped. Verified against the real tree: 27 blocked lines before and after, so no new false positives |
| `gate_i_migration_chain` | **Proven.** All six failure classes caught. My first probe reported two live rules as dead — both injections were no-ops against the root migration. The test now asserts each injection changed the file before running the gate |
| `gate_m_ml_edge` | **Proven, and a fail-open fixed.** It exited 0 when the A/B dataset was missing, so a rename turned the ML edge guard off with CI green. The dataset is committed, so absence is a defect; `AB_ALLOW_SKIP=1` is the explicit local opt-out |
| `gate_d_model_accuracy` | **Deferred.** It validates 38 MB of model artefacts resolved from `__file__`, with no env indirection, so a per-test mirror would make the suite slow. Needs a manifest-level injection instead — a different design, not more of the same |
| `coverage-gate` | **Deferred.** Not started; scope was spent on the two defects found above |

Two probes of my own were wrong before they were right — a no-op `sed` against
the migration root, and a test credential containing the substring `EXAMPLE`
which the scanner allowlists. Both would have reported a live control as dead.
**Verifying that the injection applied is now part of the method**, not an
afterthought.

## §E4 — Phase R4, and what comes next (2026-09-08)

Ratchet 10 → 8. Two gates proven, one dead behaviour fixed, one blind spot
recorded rather than silently widened.

| Gate | Outcome |
|---|---|
| `gate_b_env_consistency` | **Proven.** An undocumented `${VAR}` reference fails; a literal value does not, which is its documented scope; deleting either input fails closed |
| `gate_k_requirements_consistency` | **Proven, and a fail-open fixed.** `[gate-k] SKIP` on a missing requirements file exited **0** — CI and production could install different code with nothing disagreeing. Same shape as gate M, one phase later |
| `coverage-gate` | **Not reached.** Scope went to the two defects above |
| `gate_j_circular_imports` | **Not reached** |

### Recorded, not fixed — the build toolchain is unguarded

`gate_k`'s `_SKIP_NAMES` excludes `pip`, `wheel` and `setuptools`, and every rule
iterates the parsed sets, so **the CVE-pinned build toolchain is checked by
nothing in that gate**. requirements.txt pins those three against four named
CVEs; the lock could drift below them and gate K would still pass.

Widening the exclusion is a scope decision with a real cost — build-toolchain
versions in a lock are often environment-specific, and false positives train
people to bypass gates. `test_gate_k_requirements_injections.py` pins the
exclusion at exactly those three so it cannot quietly grow, and this is the
record so it cannot be forgotten while the gate looks green.

**Decide it deliberately.** Either extend gate K to cover them, or state in
requirements.txt why they are out of scope.

---

## What is next

In order, and each is a command away from being verified rather than assumed:

1. **Finish the ratchet — seven gates left.** `python scripts/gate_evidence.py`
   lists them. Two phases at the current rate. Every phase so far has found a
   real defect, so this is still the cheapest place to find them:
   `gate_j_circular_imports`, `gate_g_import_discipline`, `gate_c_docker_compose`,
   `gate_e_dead_files`, `gate_f_doc_consistency`, `gate_h_wordmap_schema`,
   `gate_d_model_accuracy`.
   `gate_d` needs a manifest-level injection — it resolves 38 MB of artefacts
   from `__file__` with no env indirection, so a per-test mirror is too slow.
2. **Decision Governance** (§B2 item 13) — the single highest-leverage new build.
   Three documents name the same missing artefact from three angles; build them
   as one or you get half a ledger three times.
3. **The owner's decisions in §A**, chiefly **A1**: RPO is 24 hours because of a
   cron entry, not because anyone weighed it. That and RTO decide whether
   point-in-time recovery gets built.
4. **The 361 unmeasurable modules** (§E5). Not a phase — a standing ratchet.
   Worth attacking opportunistically: whenever you touch a module on that list,
   make its test import it and drop the line.

## §E5 — Phase R5 (2026-09-08)

Ratchet 8 → 7. One gate proven, and it was the most inverted defect found yet.

### The coverage gate passed the worst coverage

| Module state | Gate result before R5 |
|---|---|
| 25% covered | **FAIL**, exit 1 — correct |
| 0% covered (test never imports it) | **pass**, exit 0 |
| Test file will not import at all | **pass**, exit 0 |

When the module under test is never imported, coverage collects no data and
prints no `TOTAL` line, so the parser returned `None` — and `None` took the "warn
but do not block" branch. **The worse the coverage, the quieter the path through
the gate.** Rule 2 says an unmeasured value is absent, never zero; here it was
being treated as success.

An unmeasurable module now fails. `SKIP_COVERAGE_GATE=1` was already the
documented emergency bypass, so no second escape hatch was added.

### The fix immediately found a real hole

`database/backup.py` — the module that takes every database snapshot — resolved
to `tests/unit/test_database.py` via the `test_{parent}.py` fallback, and that
file never imports it. So it had **no effective coverage check at all**, and the
gate reported nothing wrong.

| Module | Before | After |
|---|---:|---:|
| `database/backup.py` | unmeasurable (silently) | **95%** |
| `database/restore.py` | 78% (below the 80% threshold) | **95%** |

Both are Phase R1 code. The PostgreSQL dump path is tested at the subprocess
boundary — argument list, streamed output, failure handling, and that the
password travels in the environment rather than argv where `ps` would show it —
while the real `pg_dump` stays covered by the integration suite against a live
server.

### And it surfaced debt worth naming: 361 modules

Repository-wide, **361 modules resolve to a test file that never imports them**.
Every one had been passing the coverage gate while contributing nothing to
coverage. That is not a number to fix in a phase, so it is recorded as a ratchet
in `docs/COVERAGE_UNMEASURABLE.txt`: the list may only shrink, and a **new**
unmeasurable module blocks the commit.

The seed is static — every module whose resolved test file never mentions it —
because measuring all 539 candidates takes about two hours. That is safe in the
direction it errs: an entry only matters when measurement returns `None`, and a
measurable module is judged on its number either way. Verified by execution — a
baselined module at 25% still fails. A list that were too *narrow* would block
legitimate work, so the seed is deliberately wide.
`python scripts/pre_commit_coverage.py --adopt` replaces it with the exact
measured set.

**This is now the largest single piece of recorded debt in the repository**, and
it is the honest reading of what the coverage gate was hiding. Paying it down is
one module at a time: make the test file import the module it is named for.

## §F — What the complete Group 4 source changed (2026-09-08)

The owner supplied the full Volumes I–XX document. The earlier source was a table
of contents; this one carries a statement under every section. **It is not a
superset**: it names 118 sections where v1 named 186 chapters, so neither
replaces the other and both are now listed side by side in
`GROUP4_VOLUME_INDEX.md`.

| What changed | Detail |
|---|---|
| **Two Articles added** | XI — Reversibility · XII — Privacy. The source's System Constitution names twelve principles; this document carried ten. Both were already enforced in code (`core/idempotency.py`, `core/outbox.py`; `ai/privacy/consent.py`) and neither was written down, so the document changed, not the code |
| **One new High item** | Decision Governance (§B2 item 14) |
| **One new control** | `scripts/group4_preservation.py` — 304 titles across both sources, checked against what the repository actually lists. Proven able to fail by deleting a row from each source's table and watching it report the omission |
| **Four volumes renamed** | III, IV, VIII and XIX carry longer titles in v2; both names are recorded in the index |
| **One concrete addition to Part VIII** | NPU joins the execution-target set (`cpu`, `gpu`, `npu`, `remote`, `local-model`, `distributed`) |
| **A declaration contract** | Fourteen fields every subsystem must declare, plus ten mandatory engineering requirements. Group 4 Ch 8. **Specified and unenforced** — a candidate for the next gate, not a claim that one exists |
| **Nothing removed** | The preservation rule is now mechanical rather than intentional |

### The owner's six governing principles, and where two of them are thin

Recorded in full at Group 4 Chapter 12. Four have real enforcement. Two do not:

* **Measure intelligence rather than assuming it** — Article X, the weakest of the
  twelve. Enforced by habit (every phase reports measured numbers) and by
  Group 2 Rule 2, but by no gate.
* **Preserve institutional memory** — INV-13. `ai/memory/` exists; decision memory
  and failure memory are specified and unbuilt. This is §B2 items 12–14.

Claiming six-for-six would be exactly the assertion Article II forbids.
