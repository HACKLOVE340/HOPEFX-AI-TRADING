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
| `scripts/gate_evidence.py` | Which gates have been proven able to fail? | 23 gates · **23 proven · 0 unproven** ✓ |

### B1. Critical — do these first

| # | Item | Where | Why it ranks here |
|---:|---|---|---|
| ~~1~~ | ~~**Tested backup and restore**~~ | Group 2 Ch 9 | **DONE — Phase R1.** Round trip proven against SQLite and live PostgreSQL. Point-in-time recovery and a decided RPO remain and inherit the rank — see §A1 |
| ~~1~~ | ~~**Rule 1 injection evidence**~~ | Group 2 Ch 0, 19, 20 | **DONE — Phases R2–R12.** Ratchet 13→10→8→7→6→5→4→3→2→1→0. All 23 gates now carry an injection test that was watched to fail. Proving them keeps finding defects — gate M passed with no dataset, gate E's dead-file detector had never actually detected a dead file — though not every gate is broken: gate C (docker-compose safety defaults) was already alive. Run `python scripts/gate_evidence.py` for the current list |

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
fix. The three `arch.layer_*` rows at `prod=0` were named here as the ones to
look at first. **They have now been inspected, and they are false positives** —
their locator is `layer_state`, the §4 roll-up helper, which *is* called, at
`ai/hub/capabilities.py:2667`, inside the module that defines it. The screen
reports `prod=0 any=1` because it looks for callers outside the defining file.
Nothing is dead there; the rows stay flagged and the count stays 37 because the
screen is behaving as documented.

**Inspecting them did find a real gap next door, and it is now closed.** The
`arch.layer_b.intelligence` row cites `ai.agent.loop` as its evidence, and that
module — the Think → Execute → Monitor → Improve loop — had no caller anywhere
outside `ai/agent/` and its own tests. The registry could not see it:
`verify()` asks whether the evidence *resolves*, not whether anything *runs*.
`ai/agent/sweep.py` and `init_ai_agent_sweep` are now that caller — a scheduled,
read-only health sweep, which is the caller the loop's own docstring was
written for. See §E9.

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

1. ~~**Finish the ratchet.**~~ **DONE in R12** — all 23 gates carry injection
   evidence. What replaces it: the findings those phases produced are still
   open. The 12 dead-file candidates from §E6 and the 7 `data_layer` import
   violations recorded in §E9 are both real work, and the second is waiting
   on decision **A2**.
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

## §E6 — Phase R6 (2026-09-08)

Ratchet 7 → 6. One gate proven, and three real defects found inside it —
the dead-file detector had, as far as this phase could tell, never actually
detected a dead file in any of its five guarded packages.

### The guard that checked nothing

`GUARDED_PACKAGES` names `kill_switch`, but `kill_switch` is a single
top-level file (`kill_switch.py`), not a package directory.
`_collect_py_files` checked `root / "kill_switch"` only, which is never a
directory, and returned `[]` without ever looking at the file. A completely
unimported `kill_switch.py` passed Gate E clean, in the real repository,
before this fix.

### The prefix that made every sibling look live

`import execution.live` added both `"execution.live"` **and** the bare
prefix `"execution"` to the imported-names set, so
`"execution.orphan".startswith("execution" + ".")` was `True` purely
because a *different* file in the same package had been imported — never
because `orphan.py` itself had been. Confirmed directly against the real
repository (not the mirror): `"execution"`, `"risk"`, `"core"`, and
`"brokers"` were all in that set before this fix. In a codebase where each
guarded package is imported from *somewhere*, which is always, this meant
the gate could not have reported a real dead file in any of them, ever.
Fixed by splitting the collected names into `exact` (a specific dotted name
an import statement actually named) and `bare_packages` (a name imported
with **no** further qualification at all, e.g. a literal `import
execution`) — only the second grants "every submodule is reachable via
attribute access."

### Fixing that one immediately exposed a third

With the prefix bug gone, ~100 genuinely-live files across `core/` and
`brokers/` started reporting as dead. The cause: `EXCLUDED_PATTERNS` served
two different questions with one list. Keeping `app.py`, `celery_app.py`,
and `__init__.py` out of the *guarded-candidate* scan is correct — they are
run directly or are package boilerplate, not "a module someone imports."
But the same list also kept them out of the *import-source* scan, and real
production wiring lives in exactly those files:
`app.py: from core.health import register_health_routes`,
`brokers/__init__.py: from brokers.smart_router import SmartOrderRouter`.
Excluding them from the source scan made everything they alone import look
unreferenced. Split into `EXCLUDED_PATTERNS` (guarded-candidate scope,
unchanged) and a new `IMPORT_SCAN_EXCLUDED_PATTERNS` (source scope — drops
`__init__` and the entry-point filenames, keeps the non-Python and
test-only exclusions).

### What real execution against the repository still finds

After all three fixes, a real run reports **12** files across `brokers/`,
`core/`, `execution/`, and `risk/` with no detectable production caller —
down from 124 with only the prefix fix, and 32 with the prefix and
entry-point fixes together. At least one (`risk/risk_manager.py`) is a
documented backwards-compatibility shim exercised only by its own tests,
which may be a correct finding rather than a defect. The 12 are not
individually triaged here — proving the gate can fail is this phase's job;
which of its findings are real dead code and which need one more scan
refinement is real follow-up work, tracked separately, the same way R3–R5
left their own findings for the next phase rather than resolving everything
in one commit.

## §E7 — Phase R7 (2026-09-08)

Ratchet 6 → 5. One gate proven, and this one was already alive.

`gate_c_docker_compose.py` checks four structural safety defaults in
`docker-compose.yml`: `PAPER_TRADING` defaults to `true`, `IS_FORCE_TLS` and
`REDIS_FORCE_TLS` default to `false`, and `alertmanager` uses `build:` (so
its envsubst entrypoint runs) rather than `image:`. Injected against a real
mutated copy of the repository's actual compose file, not a synthetic one —
so an injection also proves the gate's string anchors still match the real
file's current layout, not a layout it used to have. All four defaults
correctly fail when flipped; a missing file is reported rather than
crashing; and a sanity probe — temporarily disabling the `PAPER_TRADING`
check itself and re-running the suite — confirmed the tests would have
caught that regression, before trusting the clean pass on the real gate.

The gate ships two code paths: `_check_yaml` (PyYAML present) and
`_check_regex`, a fallback for when it is not. A fallback nobody exercises
is exactly the shape this repository keeps finding dead, so both were
proven directly against the same four injected cases rather than trusting
that whichever one CI happens to run is the one under test.

No defect found this time. Not every gate is broken; this is the check
that says so with evidence rather than assumption.

## §E8 — Phase R8 (2026-09-08)

Ratchet 5 → 4. One gate proven, and like gate C it was already alive.

`gate_h_wordmap_schema.py` validates `WORDMAP.json.example`, the reference
file operators copy to `WORDMAP.json`. The consequence it guards is quiet:
if the example loses its structure, `NuclearWordmapScorer` silently falls
back to built-in keywords, so a misconfiguration looks like normal
operation. All eight documented rules were injected into a real mutated
copy of the file — invalid JSON, a missing `nuclear_risk` key, that key as
a list rather than an object, an uppercase category name, a non-object
category, an empty category, an empty keyword string, an over-length
keyword, a non-numeric weight, weights above 10 and below 0, too few
categories, and too few total keywords. All refused.

Two of those cases are worth separating, because they are the ones a
truncation defect would actually produce: the category floor and the
keyword floor fire independently, so a file that keeps all eight categories
but strips each to one keyword is still caught.

As with gate C, the clean first run was not taken at face value: disabling
the weight-range check in a scratch copy turned both range tests red, then
the real file was restored and the suite reran clean.

No defect found. Two gates in a row alive is worth stating plainly — the
ratchet's value is the evidence either way, not a defect count.

## §E9 — Phase R9 (2026-09-08)

Ratchet 4 → 3. One gate proven, two real gaps found in it, and seven
pre-existing violations that had been invisible because of them.

### The rule named three modules; the code required three segments

`gate_g_import_discipline.py` enforces that canonical packages reach
`data_layer` only through its public surface — `data_layer.orchestrator`,
`data_layer.tick_store`, `data_layer.feeds.*`. The check required
`len(parts) >= 3` before examining anything, so a two-segment path like
`from data_layer.sentiment import get_sentiment` was never looked at.
"Three names are public" and "paths with three segments are checked" are
not the same rule, and the second was what shipped.

Separately, `_is_data_layer_internal` examined only `ast.ImportFrom`, so
the plain `import data_layer.internal.thing` form was not checked at all.

Both were confirmed by execution at exit 0 against the real gate before
being fixed, alongside two controls that correctly exited 1 — so the probe
distinguished a dead rule from a rule the injection had simply missed.

### What that had been hiding

| File | Import |
|---|---|
| `api/signals.py:1228` | `data_layer.sentiment` |
| `api/trading.py:4574` | `data_layer.microstructure` |
| `ml/inference_engine.py:1097` | `data_layer.validation` |
| `ml/train_advanced.py:131` | `data_layer.validation` |
| `backtesting/data_handler.py:72` | `data_layer.validation` |
| `backtesting/engine_config.py:220` | `data_layer.validation` |
| `backtesting/engine_config.py:593` | `data_layer.validation` |

These are **recorded in `KNOWN_VIOLATIONS`, not fixed**, which is what that
list is for: the gate now warns on them, exits 0, and fails hard on
anything new. Fixing them is not mechanical — three modules are imported
from outside `data_layer` today, so resolving it means deciding what that
package's public surface actually is. That is **decision A2**, and a gate
change is not the place to make it.

The escape hatch is pinned in both directions, because a debt list that
could silence anything else would be an off-switch: a listed violation
warns and exits 0, an unlisted one alongside it still fails, and a listed
entry does not cover the same file on another line. That last property —
the keys carry line numbers — means editing a file above one of these
imports turns a known violation into a new one. Loud rather than silent,
so it is recorded in the gate's own comment rather than redesigned here.

## §E10 — Phase R10 (2026-09-08)

Ratchet 3 → 2. One gate proven, and the defect is the same one this
ratchet has now found three times.

`gate_f_doc_consistency.py` checks that the API shown in fenced `python`
blocks in ARCHITECTURE.md, AGENTS.md and CONTRIBUTING.md is the API the
code actually has. A missing document was skipped and the gate exited 0.
With all three absent it printed:

```text
[gate-f] SKIP  ARCHITECTURE.md (file not found)
[gate-f] SKIP  AGENTS.md (file not found)
[gate-f] SKIP  CONTRIBUTING.md (file not found)
[gate-f] PASS — checked 3 docs, no violations
```

Two failures in one message. Renaming a document turned the gate off with
CI green — the gate M and gate K shape a third time — and *"checked 3
docs"* was `len(DOCS_TO_SCAN)`, the length of a constant tuple, not a
count of anything opened. That is F176's shape as well: a number that
cannot report having measured nothing.

Fixed as gates M and K were, deliberately reusing their convention rather
than inventing a third one: a missing document fails closed,
`DOC_ALLOW_SKIP=1` is the explicit local opt-out alongside `AB_ALLOW_SKIP`
and `REQ_ALLOW_SKIP`, and the reported count now comes from what was
actually read.

Both rules were injected as well — an import of a module that does not
exist, a name missing from a real module, and a PascalCase class the
repository never defines all fail — along with the documented non-findings
that keep the gate usable: external and stdlib prefixes, the SKIP_NAMES
placeholders a doc example is expected to invent, and prose outside a
fenced block.

## §E11 — Phase R11 (2026-09-08)

Ratchet 2 → 1. One gate proven, and the defect is one already found in
this ratchet — in a different gate.

`gate_j_circular_imports.py` builds an intra-repo import graph and looks
for cycles across eleven trading packages. Its own header states the
consequence it exists to prevent: a circular import can "silently corrupt
module-level singletons (**e.g. the kill switch state**)".

It never looked at the kill switch. `_py_files` did `pkg_dir = root /
package; if not pkg_dir.exists(): return []`, and `kill_switch` is a
single top-level file — `kill_switch.py`, not `kill_switch/` — so it
resolved to nothing, while the PASS line went on listing `kill_switch`
among the packages checked. Confirmed by execution: a genuine
`core.uses_ks` ↔ `kill_switch` cycle produced *"Gate J PASSED — no
circular imports detected"*.

**This is §E6's defect in a second gate.** Same root cause, same shape,
found six phases apart, in code written by the same hand as the gate that
had it first. The lesson is not about either gate: any rule that resolves
a "package" as `root / name` shares it, and the repository has at least
one guarded name that is a module rather than a package. Both are now
fixed the same way.

The real graph goes from 401 to 402 modules with the fix and still passes,
so this closed a blind spot without changing the verdict on the tree as it
stands. The rest of the gate is alive: two-module, three-module and
cross-package cycles all fail, a diamond is correctly not a cycle, and the
deliberate exemption for deferred function-level imports is pinned against
the module-level form of the same pair, so it is a scoped exemption rather
than a hole.

## §E12 — Phase R12 — the ratchet reaches zero (2026-09-08)

Ratchet 1 → 0. **All 23 gates now carry injection evidence.**

`gate_d_model_accuracy.py` was deferred twice, and the reason recorded in
§E3 was: it "validates 38 MB of model artefacts resolved from `__file__`,
with no env indirection, so a per-test mirror would make the suite slow" —
it "needs a manifest-level injection instead, a different design".

**That premise was wrong, and this is the finding.** The gate does not
require the artefacts to be *large*; it requires them to be *consistent*.
What it checks is agreement — the `current.pkl` symlink resolves to the
registered file, its SHA-256 matches the registry, the meta agrees with
the registry, the Sharpe gate passed on a credible number of trades. A
28-byte file whose real SHA-256 is written into a synthetic registry
exercises every one of those, integrity hash included, against a real
symlink in a real subprocess.

The mirrors are about a kilobyte. Twenty-two injections run in four
seconds. No env indirection had to be added to the production script, and
nothing in the suite reads or writes the real `ml/saved_models/`.

Fifteen distinct refusals were confirmed, and the wrapper was proven to
propagate rather than report its own success: an inner exit 3 stays 3 and
never prints PASSED — the shape gates M, K and F each had in a different
form. The gate is alive; the blocker was an assumption about what it
needed, not the gate.

### What the twelve phases actually bought

| Gate | Outcome |
|---|---|
| `gate_e_dead_files` | **Three defects.** Had never detected a dead file in any guarded package |
| `gate_g_import_discipline` | **Two defects.** The rule named three modules; the code required three path segments |
| `gate_f_doc_consistency` | **One defect.** A missing document was a skip, and a skip was a pass |
| `gate_j_circular_imports` | **One defect.** Never had the kill switch in its graph |
| `gate_c_docker_compose` | Alive |
| `gate_h_wordmap_schema` | Alive |
| `gate_d_model_accuracy` | Alive — the deferral was the defect |

Seven real defects in four gates, and three gates confirmed sound. Two of
those defects were the *same* defect — a guarded name resolved as
`root / name` when it is a file, not a directory — found in gate E and
again in gate J, six phases apart.

**What this does not mean.** Every gate can now be shown to fail when it
should. Nothing here says the tree is clean: gate E's fix surfaced 12
dead-file candidates and gate G's surfaced 7 recorded import violations,
all still open. The ratchet's job was to make the controls trustworthy;
using them is the next job.

## §E9 — The agentic loop got its caller (2026-09-09)

Not a gate phase. `ai/agent/loop.py` implements spec §2's `agent/` — Think →
Execute → Monitor → Improve — and `ai/hub/capabilities.py` cites `ai.agent.loop`
as the evidence that `arch.layer_b.intelligence` is **live**. Measured, nothing
outside `ai/agent/` and its own tests imported it.

**The registry is not able to catch this, by construction.** `verify()` resolves
an evidence locator: it imports the module and checks the attribute exists. That
is a real check and it is the one F176 was about. But "the evidence resolves"
and "something calls it" are different claims, and only the first is measured.
`scripts/capability_callers.py` exists for the second, which is why it is kept
as a separate screen.

### What was built

`ai/agent/sweep.py` — a deterministic health sweep — and
`init_ai_agent_sweep`, registered in `core/startup_factories.py` beside
`ai_awareness` with the same `required=False`. It is the caller the loop's own
docstring named: *"A deterministic planner is what the tests drive and what a
scheduled health sweep wants."* A model-driven planner is the same interface and
can replace it; doing the deterministic one first means the wiring is proven
before a language model is near the tool bus.

### The filter that looked obvious and was wrong

The first design chose any permitted action whose handler needs no arguments.
Measured against the live registry, **every** READ_ONLY handler defaults all of
its parameters — so that rule admits `markets_execution.shadow_place_order`,
`platform_engineering.run_tests`, `research_intelligence.run_backtest` and
`walk_forward_validate`. On a 15-minute timer that is shadow orders in the audit
trail every interval, and a backtest and the test suite running on the box that
executes trades.

So the sweep names the health checks it wants and **intersects them with
`context.permitted`**, the allowlist the loop computed from the department's own
registry. The intersection is what makes a named set safe: it can only narrow
what the loop already allowed. A renamed check means the sweep calls one thing
fewer — the direction an error here has to fail in. `test_it_never_calls_order_
shaped_or_expensive_tools` pins it across every department.

### Three narrowings, none of them removed

The loop refuses anything outside `permitted_actions(department)` before the bus
is reached; the bus consults the permission registry and `enforce_agent_action`
after that; the sweep narrows once more. This change adds the third and touches
neither of the first two.

### Two test-methodology corrections, recorded

* The caller assertion first searched for the substring `run_loop` and **passed
  before anything was wired** — `hopefx_engine.py` and `nuclear/nuclear_agent.py`
  each define an unrelated `run_loop`/`_run_loop`. It now parses imports with
  `ast`. A text match tests how code is written, not what it imports.
* Registration is not execution, so the suite drives `init_ai_agent_sweep`
  itself and asserts a task is scheduled — and asserts that with no tool bus it
  schedules nothing rather than reporting a clean sweep it never ran.

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
