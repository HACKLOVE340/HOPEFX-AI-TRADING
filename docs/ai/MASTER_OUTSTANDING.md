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
| `scripts/gate_evidence.py` | Which gates have been proven able to fail? | 25 gates · **25 proven · 0 unproven** ✓ |

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
| ~~5~~ | ~~Change records carrying their expected effect~~ | **DONE 2026-09-09 — see §E24.** `deployment/change_records.py`, enforced at `commit-msg`. Group 1 §16, §21 and §32 are unblocked |
| 6 | Authority Tiers 0 and 3 (four of six exist) | Group 2 Ch 10 · INV-09 · Group 4 Ch 6 |
| 7 | Stated degradation order, trading path excluded from it | Group 2 Ch 34 |
| 8 | Progressive delivery and automated rollback | Group 2 Ch 5 |
| 9 | Package ownership register with enforced edges | Group 2 Ch 1 · INV-01 |
| 10 | Injection evidence as a traceability link | Group 3 Ch 13 |
| ~~11~~ | ~~ADR system, back-filling the eight known decisions~~ | **DONE 2026-09-09 — see §E22.** `docs/decisions/`, nine records, gated in pre-commit |
| 12 | Failure memory with the five questions | Group 3 Ch 8 — seven lessons currently live only in a transcript |
| ~~13~~ | ~~**Decision Governance** — Architecture Decision Registry and Decision Ledger carrying *expected outcome, actual outcome, lessons*~~ | **DONE 2026-09-09 — §E22 (registry) and §E23 (ledger).** `ai/ledger/`, wired to the money path's refusals. Group 2 Ch 6's change records remain separate and open |
| ~~14~~ | ~~**The second, unverified backup path**~~ | Group 2 Ch 9 |
| ~~15~~ | ~~**`risk/manager.py`'s 1.0 default for unmeasured data quality**~~ | Group 2 Ch 34 · INV-14 — **DONE 2026-09-09, see §E12** |
| ~~16~~ | ~~`trader_full.py` builds a RiskManager with no orchestrator, so it now refuses every size~~ **DONE 2026-09-09.** Wired in `RiskManager.setup()` — the real construction site, not the line §E12 named |
| ~~19~~ | ~~**441 malformed OHLC bars in `data/XAUUSD_40Y.csv`**~~ | **Owner chose clamp + restrict, DONE 2026-09-09 — see §E18.** Re-sourcing 2000–2019 from a vendor remains open and needs network access |
| 18 | `accuracy_7d` on `/ml/status` is training-time OOS accuracy, not a 7-day rolling figure | Renaming a published API field is a contract change — see §E13 |
| ~~20~~ | ~~**The per-module coverage gate had never taken a measurement**~~ | **DONE 2026-09-09 — see §E20.** `--cov=<dotted.module>` double-loaded numpy for every module in the repository; the 361-entry record is an artefact of that, not a census of untested modules |
| ~~21~~ | ~~**No pre-commit hook is installed, so no ratcheted check runs automatically**~~ | **DONE 2026-09-09 — see §E20.** `scripts/bootstrap_dev.py::install_git_hooks()` runs `pre-commit install --install-hooks` and warns rather than failing when it cannot. Whether CI should also run the hooks remains an owner decision |
| ~~17~~ | ~~`RiskAssessment.data_quality` still reports a 1.0 fallback via `_get_data_quality()`~~ **DONE 2026-09-09 — and it was a second live gate, not just a report. See §E16** | Reporting only — the *gate* is fixed (§E12). Narrowing the reported record means widening the type to `float \| None` and updating its consumers |

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
| Modules with recorded coverage debt | 361 | `docs/COVERAGE_UNMEASURABLE.txt` · `scripts/pre_commit_coverage.py` |

**The 361 is not 361 untested modules.** Every entry was recorded because
measurement returned `None`, and until §E20 measurement returned `None` for
*everything* — so the list is a census of one broken invocation. It is kept
rather than deleted because it is now the ratchet that lets the repaired gate
bite without blocking every commit that touches any of those files: a recorded
module reports its real number without blocking, and blocks the moment it clears
the floor and stops needing the entry. The honest count of under-covered modules
will be whatever `--adopt` measures; nobody has spent the two hours yet.

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

> **Correction, 2026-09-09 (§E20).** Two claims in this section are false, and
> both are the kind this document exists to prevent.
>
> "361 modules resolve to a test file that never imports them" was never
> measured. The gate could not measure *anything* — `--cov=<dotted.module>`
> made coverage re-import numpy's C extension in a process that had already
> imported it, so every module in the repository returned `None`. The 361 is a
> census of one broken invocation, not of 361 untested modules.
>
> "Verified by execution — a baselined module at 25% still fails" describes a
> comparison the gate had no means to make. It reads as evidence and is not.
> Written in the same phase that made unmeasurable modules fail, which is
> exactly when a claim of verification is least likely to be re-checked.
>
> `database/backup.py` at 95% and `database/restore.py` at 95% stand — those
> were measured with the full suite, not through this gate.
>
> §E20 repairs the invocation and re-reads the list as recorded coverage debt.

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

## §E10 — The model quality gate got its caller (2026-09-09)

`ml/model_quality_gate.py` is well built — `require_pass()` raises rather than
returning a falsy result, `evaluate()` treats a missing score as a **failure**
rather than a zero, every refusal carries a reason code — and it was invoked by
nothing outside its own tests. A fail-closed gate nobody calls is worse than no
gate: it reads to a reviewer as though model quality is checked.

### It was aimed at the wrong place first

The obvious guess is `ml/model_registry.py::promote()`. Wrong, and the module
says so: it exists to be consulted *"before a candidate reaches paper or live
execution"*. That is the **inference** path. Registry promotion already has its
own gate (OOS accuracy, p-value, Sharpe, PnL reconciliation); this one asks
whether a *prediction* can be trusted right now.

### The three signals already existed, judged by hand

`predict()` was already making all three judgements inline, as strings in the
evidence blob, against a bare `0.3`:

    "calibration_state":  "isotonic" if self._calibrator is not None else "raw",
    "drift_state":        "detected" if drift else "clear_or_unavailable",
    "data_quality_state": "valid" if data_quality >= 0.3 else "degraded",

— and `data_quality` was computed under a comment reading *"for downstream
gating"*, then used only to set a Prometheus gauge. Nothing gated on it.

So the wiring replaces three hand-rolled judgements with the component built to
make them. **Every threshold is a value the file already used**
(`_DRIFT_Z_THRESHOLD`, and the `0.3`, now named `_MIN_DATA_QUALITY`). None is
invented — a gate configured with numbers nobody chose fails at a boundary
nobody agreed to.

Blocking is opt-in (`MODEL_QUALITY_BLOCK`, default false), the same shape as
`DRIFT_BLOCK`. Wiring a gate in must not silently change when this system
declines to trade. When it *is* enabled it raises `RuntimeError` specifically,
which `HOPEFXDecisionEngine._phase2_ml` treats as a hard ML filter rather than
falling back to non-ML confidence — a quality refusal must not degrade into
"trade on less information". An unevaluable gate raises too: not a passed gate.

### Two findings this surfaced, neither fixed here

1. **Every prediction today is uncalibrated.**
   `ml/saved_models/isotonic_calibrator.pkl` does not exist, so `_calibrate()`
   silently returns the raw probability. Nothing said so before; the gate now
   scores it 0.0 and records `calibration_state: "raw"`. `_MIN_CALIBRATION`
   defaults to 0.0, so this is tolerated and *visible* rather than enforced —
   raising it to 1.0 would refuse every prediction in the current deployment.
   Training records no Brier or ECE score, so there is no honest calibration
   *error* to read; the score is a presence signal and is documented as one.

2. ~~**`risk/manager.py::_get_data_quality` defaults to 1.0 when it cannot
   measure.**~~ **Fixed 2026-09-09 — see §E12.** `size_order()` now gates on
   `_measured_data_quality()`, which returns `None` when nothing measured the
   feed, and refuses. Evidence:
   `tests/unit/test_risk_data_quality_is_measured.py` (21 tests; 13 fail
   against the pre-fix tree). See the correction in §E12 — an earlier version
   of that section wrongly reported S5-02/S5-03 as still open.

## §E11 — advanced_ai.py: superseded, kept, pinned (2026-09-09)

Third module in a row with no production caller, and the first where "give it
a caller" was the **wrong** answer. The symptom is identical to §E9 and §E10;
the cause is not.

`ai/agent/loop.py` and `ml/model_quality_gate.py` were *built and never
called*. `ml/advanced_ai.py` (698 lines) is *superseded* — each of its three
subsystems has a more developed replacement that is already wired:

| in advanced_ai.py          | superseded by                         | wired into                            |
|----------------------------|---------------------------------------|---------------------------------------|
| `PPORLAgent`, `TradingEnv` | `ml/rl_agent.py`                      | `api/ml.py`, `ml/training_manager.py` |
| `OnlineRetrainer`          | `ml/online_learner.py`                | `api/online_learner.py`               |
| `VectorRAGNewsSentiment`   | `ai/departments/news_intelligence.py` | `ai/awareness/watchers.py`            |

`ml/rl_agent.py` additionally has `RLMetrics`, `RLAgentTrainer`,
`walk_forward_eval` and `get_rl_agent()`. Wiring `PPORLAgent` in beside it puts
a second, less developed PPO agent and a second online retrainer into a live
money-moving system, with no way to tell afterwards which one acted. So: not
wired, and — per the owner's standing instruction — **not deleted either**.

### What "marked" means here, so it does not rot

`tests/unit/test_advanced_ai_is_superseded.py` pins two things:

1. **Nothing in production imports it.** Verified by injecting a real
   `from ml.advanced_ai import PPORLAgent` into `ml/model_paths.py` and
   watching the test refuse, naming the offending file, then reverting. A pin
   nobody has seen refuse is not a pin.
2. **The supersession claim is checked, not asserted.** Each named replacement
   must exist AND itself be imported by production code. A pointer to a module
   that was later renamed is exactly how a note like this quietly becomes
   false — F176 applied to prose.

Writing that test found a bug in the test: the first import matcher recorded
only `node.module`, so `from ai.departments import news_intelligence` — the
normal way this repository reaches a department — read as importing
`ai.departments` and nothing else, and it reported `news_intelligence.py` as
having no caller. Same shape as the gate E prefix defect.

### One capability is genuinely unique and is not being discarded

`VectorRAGNewsSentiment` is embedding-based (FAISS + sentence-transformers).
The live path is the keyword wordmap scorer via
`api/news_feed.py::_get_nuclear_scorer`; semantic sentiment exists nowhere else
in the repository. Adopting it means putting model weights and resident memory
on the box that executes orders, so it is tracked as its own proposal to be
decided on its merits — not settled as a side effect of "this file needs a
caller".

## §E12 — The risk gate that could not fire (2026-09-09)

Fourth in the same family as §E9–§E11, and the first one in the **money path**.
`ai/agent/loop.py` and `ml/model_quality_gate.py` were controls that existed and
were never called. This is a control that existed, *was* called on every trade,
and could not reach its own failure branch.

### The defect

`RiskManager.size_order()` refuses to size when data quality is below
`RISK_MIN_DATA_QUALITY` (0.40). The value came from:

```python
def _get_data_quality(self, signal) -> float:
    if self._orch is not None:
        try:
            tick = self._orch.get_latest_tick()
            if tick is not None:
                return tick.confidence
        except Exception:
            ...
    return getattr(signal, "data_quality", 1.0)
```

`core.domain_models.Signal` has **no** `data_quality` field — verified by
introspecting `Signal.model_fields`, not by reading. So that `getattr` default
was not a rarely-taken fallback. It was the answer in every case except "the
orchestrator returned a fresh tick":

* no orchestrator wired onto the RiskManager
* `get_latest_tick()` raised
* `get_latest_tick()` returned `None` — Redis down, gold feed down, or the
  cached tick older than `DQE_STALE_THRESHOLD_S` (30 s) and discarded

Each of those scored **1.0 — perfect** and passed `< 0.40`. The gate could only
fire when the feed was *working* and honestly reporting low confidence. In the
condition it was written for — the feed being down or stale — it was
structurally unable to refuse.

Running the pre-fix tree against a dead feed shows it reaching sizing and being
stopped several gates later by an unrelated check (`tick_mid_unavailable`),
which is why the hole never surfaced as a bad trade in testing: a different
gate happened to catch it, for a different reason, in one arrangement of inputs.

### The same fabrication, one level up

`_MinimalSignal` — the adapter `calculate_position_size()` wraps its arguments
in — hardcoded `self.data_quality = 1.0` with no constructor parameter, so no
caller could set it. `HOPEFXDecisionEngine._phase3_risk` (the central 5-phase
pipeline) and `core/signal_engine.py`'s auto-trade path both size through it.
Every one of those trades asserted flawless market data that nothing had looked
at.

### What changed

`_measured_data_quality()` now distinguishes three cases the old code collapsed
into 1.0:

| case | result |
|---|---|
| orchestrator produced a tick | that confidence — the measurement |
| caller *supplied* a `data_quality` | honoured — an assertion somebody made |
| neither | `None` → `size_order()` refuses with `data_quality:unmeasured` |

The distinction that matters is between a value a caller **supplied** and a
`getattr` **default**: the first is a claim someone is accountable for, the
second is silence read as perfection. Rule 2, in the position-sizing path.

Alongside it:

* `_MinimalSignal.data_quality` defaults to `None` instead of `1.0`, and
  `calculate_position_size()` takes a `data_quality=` argument so callers that
  genuinely measure it (backtests, replays) can still say so.
* `_zero_sizing()` now carries its reason onto the result via
  `_halt_reason_override`, so `result.reason` names the gate that refused
  instead of the generic `"position_size_zero"`. It was logged and dropped
  before, so a caller — or an operator reading a lineage record rather than a
  log — could see *that* sizing refused but not *why*.

Deliberately **not** changed: `_get_data_quality()` keeps its `float` signature
and its 1.0 fallback, because `assess_risk()` feeds it into
`RiskAssessment.data_quality`, typed `float`. Narrowing the reported record is a
wider change than closing the sizing hole, and is tracked rather than smuggled
in alongside it.

### Why this is safe to enforce now

Both deployed paths build `RiskManager` **with** an orchestrator —
`hopefx_engine.py` explicitly, and `core/startup_factories.py::init_risk_manager`
for the FastAPI app the container actually runs (`Dockerfile` → `app.py`). So
the new refusal fires exactly when the orchestrator cannot produce a tick, which
is the condition the gate exists for.

`trader_full.py:677` builds a RiskManager with no orchestrator and will now
refuse every size. It is **not** a deployed entry point (`run.py` uses
`HopeFXEngine`), and the refusal is diagnosable rather than silent — it returns
`reason="data_quality:unmeasured"`. Wiring it to the orchestrator, or having it
assert its own quality, is tracked in §B.

### What this does NOT close — CORRECTED 2026-09-09

**The paragraph that stood here was wrong, and wrong in the direction that
matters: it reported an open hole in the money path that had already been
closed.** It read:

> `docs/HARDENING_BACKLOG.md` S5-02 and S5-03 (both open) describe the
> consequence: with Redis down, `orchestrator.get_latest_tick()` falls through
> to the in-memory consensus tick, which carries no age check […] "the feed is
> gone" is now caught; "the feed stopped and nobody noticed" is not.

S5-02 and S5-03 were fixed before this phase began. `GoldTick.is_valid()`
(`data_layer/types.py:143`) bounds age with `DQE_STALE_THRESHOLD_S` — explicitly
"so there is one staleness rule rather than one per read path" — and
`GoldFeedManager.get_latest_tick()` (`data_layer/feeds/gold/manager.py:424`)
checks it on the default consensus branch, warning instead of serving.
`tests/unit/test_tick_staleness_enforced.py` (8 tests) has been green
throughout.

Measured rather than read: a tick graded `GOOD` with confidence 0.99 reports
`is_valid() is False` at 31 s, and the consensus branch declines to serve it.

**The two fixes compose, which is the part the wrong paragraph obscured.** A
stalled feed now fails at the read (`is_valid()` → the manager returns nothing),
so the orchestrator returns `None`, so `_measured_data_quality()` returns `None`,
so `size_order()` refuses with `data_quality:unmeasured`. "The feed stopped and
nobody noticed" ends in a refusal, not a trade.

**How the error happened, because the mechanism matters more than the
correction.** The claim was taken from `docs/HARDENING_BACKLOG.md`, where those
entries still read as open, and was never checked against the code. That is the
exact failure this repository's own rule exists to prevent — *"if a document and
a script disagree, the script is right"* — committed while fixing a defect of
the same family, and it reached a commit message, a published page and a report
to the owner before anyone ran it. `HARDENING_BACKLOG.md` now carries a FIXED
banner on both entries and a warning that its paths predate the move under
`data_layer/`.

What genuinely remains open here is narrower: `_get_data_quality()` still
reports a 1.0 fallback into `RiskAssessment.data_quality` (§B item 17), and
`trader_full.py` still builds a RiskManager with no orchestrator (§B item 16).

### Evidence

`tests/unit/test_risk_data_quality_is_measured.py` — 21 tests. Against the
pre-fix `risk/manager.py`, 12 fail. The 16 existing tests that had to change
were all asserting the fail-open: they built a RiskManager with no orchestrator
and expected a sized position. They now pass `data_quality=1.0` explicitly, so
the assumption is stated in the test rather than supplied by a default.


## §E13 — The drift score that could not report a broken monitor (2026-09-09)

Fifth in the family, and the first one **found by running the application
rather than reading it**. §E9–§E12 came out of code review and registry
screens. This one came out of a booted server answering a real request.

`GET /api/superadmin/ml/status` on a live instance returned:

```json
{"status":"healthy","active_model":"advanced_oos_v1",
 "predictions_today":0,"accuracy_7d":57.34,"drift_score":0.0}
```

A drift score of **0.0 — no drift** from a monitor that had never seen a
prediction, on the same line as `predictions_today: 0`.

### The defect

`api/superadmin/ml_ai.py::_live_drift_score()` returned a hardcoded `0.0` in
four cases: no Redis client, no `ml:drift:status` key, a malformed payload, or
any exception — the last logged at `logger.debug`, which is off in production.
A fifth followed from `.get("drift_score", 0.0)`: a status document that
carried no score at all became a measured zero.

`0.0` is the **best** value on this scale, so "the monitor is down" and
"measured, healthy" were the same reading. `DriftBar` paints below 0.1 green,
so an unreachable monitor rendered as a green **0.000** beside every model.

The function's own docstring said it existed *"so the dashboard never shows a
hardcoded zero while real drift exists"* — while being the hardcoded zero. It
was written to fix a worse version (every row literally `0.0`), and fixed the
rows without fixing the fallback.

### The test asserted it, again

`tests/unit/test_ml_drift_wiring.py` pinned the defect as the requirement, the
third time in this audit that a green suite has described one:

```python
def test_live_drift_score_defaults_zero_when_unavailable(...):
    assert ml_ai._live_drift_score() == 0.0

def test_live_drift_score_never_raises(...):
    assert ml_ai._live_drift_score() == 0.0  # best-effort, swallows errors
```

"Never raises" was right and is kept. The value it fell back to was not.

### What changed

`_live_drift_score() -> float | None` returns `None` when it could not measure,
and logs at WARNING rather than DEBUG. Both endpoints carry a `drift_state`:

| state | meaning |
|---|---|
| `measured` | a real reading, including a genuine 0.0 |
| `unmeasured` | the monitor could not be read |
| `not_serving` | a staged or retired version, which nothing measures |

`/ml/models` rows for non-serving versions previously sent `0.0` under a
comment saying that was correct. Not serving is not zero drift, and the bar
painted it green either way.

The frontend moved with it: `drift_score` is `number | null`, `DriftBar`
renders "— not measured" / "— not serving" in grey with an explanatory title
instead of a bar, and the summary tile reads "not measured". Without that a
`null` would have crashed `.toFixed(3)`.

Two neighbours in the same handler, fixed in the same pass: `get_ml_status`
swallowed an InferenceEngine failure at DEBUG while reporting every figure at
its zero default, and `list_ml_models` did the same for a registry failure and
a directory-scan failure. All three now log at WARNING and say what the reader
is looking at instead.

### Not fixed here, recorded instead

`accuracy_7d` is the active model's **training-time out-of-sample** accuracy,
not a 7-day rolling live figure — nothing computes one. The UI label ("OOS
ACCURACY") is honest; the API field name is not. Documented in the endpoint
docstring and the frontend interface rather than renamed, because renaming a
published field is a contract change. Tracked in §B.

### Evidence

`tests/unit/test_ml_drift_wiring.py` — 12 tests, 10 of which fail against the
pre-fix handler (watched, via git stash). Confirmed end to end on a booted
server: `{"drift_score":null,"drift_state":"unmeasured"}`, and the superadmin
console renders "Drift Score — not measured".


## §E14 — The model abstained and would not say why (2026-09-09)

Found the same way as §E13 — by running it. The owner asked to see the AI run,
so it was handed a 300-bar hourly XAUUSD window. It answered:

```json
{"direction":"neutral","probability":0.5,"confidence":0.0,
 "model_version":"fallback","fallback":true}
```

and nothing else. Nothing in the logs at INFO or WARNING either.

**The abstention was correct.** 300 hourly bars resample to roughly 12 daily,
below `_MIN_BARS`, and the model is trained on daily data — so it refused
rather than guessing. That is the behaviour anyone would want.

The defect is that the reason existed and went somewhere no caller can read.
Every abstention path did three things:

```python
_PROM.fallback_total.labels(symbol=sym_label, reason="insufficient_daily_bars").inc()
logger.debug(...)          # DEBUG is off in production
return base_result         # carries no reason
```

The cause lived in a Prometheus label. `HOPEFXDecisionEngine`,
`core/signal_engine.py` and the dashboards — every real consumer of
`predict()` — saw a flat neutral with no explanation. Diagnosing this at all
meant reading the value back out of the metrics registry by hand.

Ten paths behaved that way: `insufficient_bars`, `insufficient_daily_bars`,
`feature_build_failed`, `feature_validation_failed`, `stale_model`,
`feature_drift`, `model_fallback`, `reduced_feature_set`, `nan_features`,
`all_zero_features`. A neutral signal is the system declining to trade; an
operator who cannot tell a short data window from a drifting model from a stale
artifact cannot act on it.

### What changed

A single `_abstain(result, reason, detail)` helper inside `predict()` now
records the abstention once, in all three places at once — the returned
`reason`, the Prometheus counter, and a log line at INFO with the specifics.
One call site, so the metric and the payload cannot drift apart. `stale_model`
keeps its own branch shape because it may raise, and gained the reason and a
WARNING; the served-prediction path carries `reason: ""`.

The same run also confirms the §E12 fix from the other direction: the evidence
payload reports `data_quality: null` rather than a fabricated 1.0.

### Evidence

`tests/unit/test_inference_abstention_says_why.py` — 6 tests, 5 of which fail
against the pre-fix engine. Re-running the AI now prints:

```
INFO ml.inference_engine: InferenceEngine: abstaining for XAU_USD —
  insufficient_daily_bars (300 intraday bars resampled to too few daily)
reason  'insufficient_daily_bars'
```


## §E15 — Offline prediction, and 441 bars that never happened (2026-09-09)

The owner asked for the AI to be able to predict without a live feed. It turned
out it already could — and the work of proving that surfaced a data defect.

### The data was already there

`data/XAUUSD_40Y.csv` (6415 daily bars, 2000→2026) has been committed for a
long time. Handed 400 of its bars, the engine returns a genuine prediction:
`advanced_oos_v1`, `fallback: False`, 222 features built, `probability 0.4974`
— neutral because that sits between the thresholds, which is a real "no edge"
answer rather than an abstention.

What was missing was a way to *reach* it that carries provenance. Every
existing reader drops it: `api/trading.py` opens the file inline for charts,
`backtesting/cli_runner.py` has its own `load_ohlcv_csv`, and neither returns an
as-of date. A caller gets a DataFrame indistinguishable from a live one — and
this series ends 168 days before today.

`ml/cached_series.py` returns a `CachedSeries` instead: frame plus `source`,
`as_of`, `age_days`, `is_stale`, and a `describe()` that says "cached" out loud.
`as_of` is the last bar, never the read.

**Not wired as a fallback inside the engine, deliberately.** Cached history
reaching `size_order()` would put fabricated freshness back into the path §E12
just closed: the gate refuses when data quality is unmeasured, and a CSV has no
tick confidence to measure. Offline prediction is an explicit request —
`scripts/predict_offline.py` — and it prints how old the data was.

### What the sanity test found

The test began as `assert (high >= low).all()`. It failed, and the failure was
the data:

| violation | count |
|---|---:|
| high < low outright | 1 |
| high below the open/close body | 236 |
| low above the open/close body | 227 |
| **distinct malformed bars** | **441 of 6415 (6.9%)** |

All before 2020 — 416 in the 2000s, 25 in the 2010s — and none in the window
the model predicted on, so that result stands.

It matters anyway, because this is the **primary** file. `api/trading.py`
prefers it for charts under a comment reading *"the clean 40Y file … no
corrupted bars"*, `scripts/build_50y_data.py` calls it *"highest quality
2000+"*, and the 50Y training builds draw on it. Every rolling high, low, ATR
and true range over an affected window is computed from bars that never
happened. `XAUUSD_5Y.csv` and `XAUUSD_2Y.csv` are clean.

**Not repaired.** Dropping or rewriting those bars invents prices for a market
that has already closed. The loader counts them, `describe()` prints a ⚠ line,
and the choice — re-source, clamp with recorded provenance, restrict training
to 2020+, or accept and document — is the owner's, because each one changes
what the models are trained on. Tracked in §B.

### Evidence

`tests/unit/test_cached_series.py` — 18 tests, 17 of which fail without the
module; one marked `slow` drives a real prediction end to end and would fail on
an abstention. `scripts/predict_offline.py` prints the whole chain: provenance,
the staleness warning, the 48% macro feature imputation the engine reports for
itself, the decision, and `data_quality: None` — unmeasured, which offline is
the honest answer.


## §E16 — The same gate, one method over (2026-09-09)

§B item 17 was filed as a reporting problem: `RiskAssessment.data_quality`
defaulted to 1.0, so a risk record produced with the feed down claimed flawless
data. Fixing it found that `assess()` carries its **own** data-quality gate,
which §E12 missed:

```python
data_quality = self._get_data_quality(signal)   # 1.0 fallback
...
if data_quality < _MIN_DATA_QUALITY:            # cannot fire on an unmeasured feed
```

Identical to the defect §E12 closed in `size_order()`, in the method next to it.
§E12 fixed one call site and left the other, because the finding had been framed
around sizing.

**The trade was still refused** — `assess()` calls `size_order()`, which does
refuse — so this was not an open path to a bad trade. What it produced was a
rejection that lied about itself: `reason: "zero_size"` and
`data_quality: 1.0`, naming neither the cause nor the truth. An operator reading
that cannot tell a dead feed from an ordinary zero-size result, and those need
different responses.

### What changed

* `RiskAssessment.data_quality` is `float | None`, defaulting to `None`.
* `_rejected_assessment()` no longer defaults it to 1.0.
* `assess()` gates on `_measured_data_quality()` and rejects an unmeasured feed
  as `data_quality:unmeasured`, with its own branch — `None < 0.40` is a
  `TypeError`, so widening the type without widening the comparison would have
  traded a silent hole for a crash in the money path.

Blast radius checked first: nothing outside `risk/manager.py` reads the field.
`api/graphql_schema.py` builds a different assessment shape and never touches
it, so no external consumer depended on the old type.

### The lesson worth keeping

A defect found at one call site is a defect *shape*, not a location. §E12's
write-up named `getattr(signal, "data_quality", 1.0)` and traced it to
`size_order()`; the same expression was two methods away, reached by
`_get_data_quality()`, and nothing in that phase went looking. Grep the
expression, not the symptom.

### Evidence

`tests/unit/test_risk_assessment_reports_unmeasured.py` — 11 tests, 5 of which
fail against the pre-fix tree, including one asserting the gate does not raise
on `None`. 2300 pass across the risk/gatekeeper/sizing/invariant slice.


## §E17 — The Gatekeeper had no data source, and scored that perfect (2026-09-09)

§E16 ended on "grep the expression, not the symptom". Doing that found
`getattr(signal, "data_quality", 1.0)` a third time, in `risk/gatekeeper.py` —
and pulling the thread found three defects stacked, each hiding the next.

### 1. The fail-closed reader had a fail-open branch

`_get_data_quality_from_orch()` exists to be fail-closed and says so in its own
comment. It returns `0.0` when the tick read raises, and `0.0` when there is no
tick. Then:

```python
if getattr(self, "_orch", None) is None:
    return 1.0          # the one unmeasured state that does not block
```

An absent orchestrator is the *least* measured state there is, and it was the
only one scored perfect.

### 2. Nothing assigned the attribute the factory read

Measured on a booted instance:

```
gatekeeper = Gatekeeper
  gk._orch = None
  gk._get_data_quality_from_orch() -> 1.0
```

`core/startup_factories.py` built it with
`orchestrator=getattr(s, "data_orchestrator", None)`. **`data_orchestrator` is
assigned nowhere in the codebase** — the live orchestrator is stored by
`core/startup_helpers.py` as `data_layer_orchestrator`. One word apart, and
invisible because a missing orchestrator produced a perfect score rather than
an error.

`_run_checks_on_dict` — the event-bus path (`bus.subscribe(CH_SIGNAL)`) — calls
that reader directly, so gate step 5 compared `1.0 < 0.40` forever. Driven in a
test, the gate returned `set()`: no failures for a signal with no measurable
data quality.

### 3. Fixing the name was not enough — the orchestrator did not exist yet

With the name corrected, `gk._orch` was *still* None. The component registry
runs `init_decision_engine`, which builds the Gatekeeper, before
`startup_event` reaches `start_data_layer_orchestrator`. The Gatekeeper is
constructed while no orchestrator exists.

At that point the gate was fail-closed with nothing to measure — correct, and
still not a working gate, because it would block every signal.
`start_data_layer_orchestrator` now back-fills consumers built before it.

Measured after all three fixes:

```
app_state.data_layer_orchestrator = MarketDataOrchestrator
gatekeeper = Gatekeeper
  gk._orch = MarketDataOrchestrator      ← wired
  gk._get_data_quality_from_orch() -> 0.0 ← no gold feed in the sandbox: blocks
```

### A fourth test asserting the defect

```python
def test_data_quality_fallback_when_no_orch(self):
    gk = _make_gk()
    assert gk._get_data_quality_from_orch() == pytest.approx(1.0)
```

Three lines above `test_data_quality_fallback_on_exception`, commented
*"Fail-closed: exception from orchestrator returns 0.0 to block the trade"*.
The same file pinned fail-closed for an exception and fail-open for a missing
orchestrator, in adjacent tests, and the contradiction went unnoticed — because
a perfect score raises nothing. Four other tests built bare Gatekeepers and
expected a clean pass; they now supply a feed that reports healthy, so they test
the confidence and spread gates they claim to rather than riding on the
fail-open.

### Evidence

`tests/unit/test_gatekeeper_data_quality_fail_closed.py` — 9 tests, 3 failing
against the pre-fix tree, plus one `slow` test proving the late-bind (it fails
when the back-fill is reverted). 4272 pass across the
gatekeeper/risk/startup/decision/execution/connector/data-layer slice.


## §E18 — 441 bars repaired, and kept distinguishable from real ones (2026-09-09)

§E15 measured 441 impossible bars in `data/XAUUSD_40Y.csv` and deliberately did
not touch them, because rewriting a price is inventing one. Presented with the
options, the owner chose **clamp with recorded provenance, and default to the
clean 2020+ window** — both, because the second is what keeps the first honest.

### The repair

`scripts/clamp_ohlc.py` applies the smallest edit that makes a bar possible:

```
high := max(high, open, close)
low  := min(low,  open, close)
```

Open and close are never touched — those are prints; the extremes are the
fields contradicting them. Run against the real file:

```
source     data/XAUUSD_40Y.csv  (sha256 7ffc2bf58397…)
bars       6415
edited     441  (6.9%)
range      2001-02-13 → 2011-11-14
wrote      data/XAUUSD_40Y_clamped.csv
provenance data/XAUUSD_40Y_clamped.provenance.json
```

The source is byte-identical afterwards, checked by hash. The sidecar records
the source's sha256 and every edited bar with its before and after, so a later
reader can tell both what changed and whether the repair still matches its
input.

### Why the clean window matters more than the repair

A clamped high is the *lowest high consistent with the body*, not what the
market reached. It is a reconstruction, and this repository's recurring defect
is exactly a reconstructed or defaulted value reaching a consumer that cannot
tell it from a real one. So:

* `CLEAN_SINCE["XAUUSD"] = 2020-01-01` records where the data needs no repair —
  1567 bars, verified `no OHLC violations` by the same check that found the
  441;
* `load_cached_daily(..., since=...)` trims to it, and
  `scripts/predict_offline.py` now defaults to it, with `--full-history` to opt
  back in;
* a series loaded from a file with a provenance sidecar reports
  `repaired: True` and says so in `describe()`.

Three views, all correct at once:

```
REPAIRED  … XAUUSD_40Y_clamped.csv · ⚑ repaired: 441 bars reconstructed   (0 violations)
ORIGINAL  … XAUUSD_40Y.csv · ⚠ 441 malformed bars (6.9%)                  (untouched)
CLEAN     … 1567 bars · 2020-01-02 → 2026-03-25                           (no warning)
```

### Still open

Re-sourcing 2000–2019 from a data vendor, which would replace reconstructions
with observations. Not possible here — the egress proxy blocks yfinance and
every market source tried — so it needs a Codespace with network access.

### Evidence

`tests/unit/test_ohlc_clamp_and_clean_window.py` — 14 tests, 13 failing before
the implementation. They pin that clean bars are byte-identical after the
repair, that open and close are never altered, that the source is not modified,
that every edit is recorded with before and after, and that the window
advertised as clean really is. 1758 pass across the affected slice.


## §E19 — 23 dependency advisories, and the audit that never ran (2026-09-09)

Dependabot reported 29 open alerts. The GitHub App backing this session has no
Dependabot permission — `/repos/.../dependabot/alerts` returns
`403 Resource not accessible by integration` — so rather than read the list, the
dependency trees were scanned directly with `pip-audit` and `npm audit`.

### What is actually exposed

| surface | advisories | **reaches production** |
|---|---:|---:|
| `frontend/` npm | 21 (17 high, 4 moderate) | **0** |
| `dashboard/` npm | 2 (1 high, 1 moderate) | **0** |
| `requirements.txt` | 1 (`nltk`) | 1 |
| installed venv | 2 (`nltk`, `ecdsa`) | 2 |

`npm audit --omit=dev` returns **NONE** for both workspaces: every one of the 23
npm findings is build tooling — the `@babel/*` chain behind `vite-plugin-pwa`,
`browserslist`/`autoprefixer`, `js-yaml`, `vitest`. Nothing vulnerable is
shipped to a browser. That is a materially different picture from "19 high", and
worth stating plainly rather than reporting the raw count.

It is not nothing: a compromised build chain writes the bundle a browser
executes. `npm audit fix` cleared all 23 without a breaking change, and the
result was verified rather than assumed — `tsc --noEmit` clean, `vite build`
clean (77 assets), **2594 frontend tests pass**.

### The two Python advisories, traced

Neither is imported by first-party code; both are transitive, and neither has a
published fix.

* **`ecdsa` 0.19.2 · PYSEC-2026-1325** — a Minerva timing attack on P-256 that
  leaks the nonce from `SigningKey.sign_digest()`. Verification is unaffected.
  Pulled in by `hdwallet`, which `payments/crypto/bitcoin.py` uses for **BIP84
  address derivation** only; signing and broadcast are delegated to BitGo,
  Fireblocks or Bitcoin Core RPC. JWT auth is `HS256` everywhere — no ECDSA.
  No `sign_digest` call exists in this repository.
* **`nltk` 3.10.3 · PYSEC-2026-3740** — a file-sandbox bypass in
  `TransitionParser`. Pulled in by `textblob` for `news/sentiment.py`.
  `TransitionParser` is not referenced anywhere in the codebase.

### The finding underneath the findings

The Python dependency gate in `.github/workflows/security-scan.yml` is well
built: it blocks only on advisories that have a **published fix**, so an
unfixable one is information rather than a stuck pipeline. Both of the above
correctly pass it.

**No workflow ran `npm audit` at all.** bandit, safety, pip-audit, Trivy and
CodeQL are all wired; the npm dependency trees were watched by nothing, which is
how 23 advisories accumulated unnoticed. A new `npm-audit` job now runs over
`frontend` and `dashboard` under the same policy as the Python gate.

Proven by execution rather than asserted: the gate's exact logic exits 1 against
the pre-fix lockfile ("BLOCKED: 2 high/critical advisory(s) have a published
fix") and 0 against the fixed one.

### Not done

Reconciling against Dependabot's own list of 29, which needs the API permission
this session lacks. The gap between 23 and 29 is most likely Dependabot counting
per-manifest and including `requirements-dev.txt` / `requirements-optional.txt`
separately.


## §E20 — Twelve orphans, triaged rather than silenced (2026-09-09)

Gate E reported zero dead files for its whole life. §E3–§E12 fixed three stacked
defects in its own detection — single-file guarded packages skipped,
bare-package imports unresolved, and a substring match excluding every mirrored
test file — and it immediately failed CI with twelve unreferenced modules,
5,178 lines between them.

That failure is the gate working. Resolving it is the work that follows.

### The triage

Deleting is not an option, and wiring twelve modules blind would be worse than
leaving them: several are alternates for something already running. Each is
recorded in `KNOWN_UNWIRED` with the reason it stays.

| module | why it has no caller |
|---|---|
| `brokers/oanda_ws.py` | Tombstone — its own docstring says REMOVED; streaming moved to `data_feed.NuclearStreamer` |
| `core/tenancy.py` | **Superseded, verified** — see below |
| `risk/risk_manager.py` | 63-line backwards-compatibility shim re-exporting `risk.manager` |
| `execution/execution.py` | Alternative startup wiring, like `trader_full.py`; invoked by hand, not imported |
| `core/acceleration/gpu_engine.py` | Requires CUDA; already omitted from coverage for the same reason |
| `brokers/mt5_zmq_bridge.py` | MetaTrader 5 is Windows-only; the SDK will not install in CI or on the Linux VPS |
| `core/domain_models.py` | Pydantic schema; production duck-types these objects via `getattr` rather than importing the classes |
| `risk/analytics.py` | `risk/advanced_analytics.py` is the wired one |
| `risk/position_sizing.py` | `risk/manager.py` carries the sizing that runs |
| `core/circuit_breaker.py` | `utils/fault_guard.py` is the wired one |
| `risk/compliance/prop_engine.py` | Prop-firm config is read elsewhere |
| `brokers/prop_firms/all_brokers.py` | 1301 lines of prop-firm adapters, no current caller |

### The one that looked like a security hole

`core/tenancy.py` exists because — in its own words — *"the filters added
afterwards landed on some endpoints and not others: `GET /api/trading/positions`
filtered, `GET /api/trading/orders` did not, `/balance` did not,
`api/portfolio.py` did not, and the WebSocket account broadcaster pushed one
account's equity to every subscriber."*

A module written to close a multi-tenant data leak, imported by nothing, is
alarming. Checked rather than assumed: all three named endpoints filter today
via `_resolve_account(user.sub)` and `_user_broker_call(user.sub, ...)`. A
different mechanism — per-user broker accounts — closed the leak, which is why
`tenancy.py` never acquired a caller. **Not a live gap.**

### Keeping the list a debt and not a graveyard

An allowlist with no pressure on it becomes an off-switch — the lesson from
gate-g, whose line-keyed entries taught people to bump numbers. Three properties
are pinned by test:

1. every entry carries a substantial, non-placeholder reason;
2. no entry has since been wired (a module that gained a caller must leave);
3. every listed file still exists.

And the one that matters most: an orphan **not** in the registry still fails the
gate, proven by mirroring a tree with an unimported module and watching it exit 1.

### Evidence

`tests/unit/test_gate_e_known_unwired_is_a_debt_not_an_offswitch.py` — 6 tests.
`python scripts/ci/gate_e_dead_files.py` now exits 0, printing all twelve with
their reasons rather than hiding them.


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

## §E20 — The coverage gate had never measured anything (2026-09-09)

Found the way §E13 and §E14 were: by running the thing rather than reading it.
The gate had a test suite, an injection suite, a ratchet file and a 361-module
debt record. What it did not have was a single successful measurement, in its
entire life.

```
pytest <test> --cov=risk.manager --cov-config=.coveragerc
    numpy/_core/multiarray.py:11: in <module>
        from . import _multiarray_umath, overrides
    ImportError: cannot load module more than once per process
```

Every module in scope imports numpy transitively through `tests/conftest.py`, so
the failure was total. The gate reported it as

> coverage could not be measured (test: …) — the test may not import the module,
> or may fail to collect

which blames the test file, and whose natural next move is `SKIP_COVERAGE_GATE=1`.
A gate that cannot run *and* misattributes why is worse than no gate: it teaches
the bypass.

### The cause, isolated by bisecting rather than reading

| invocation | result |
|---|---|
| `pytest <test>` | works |
| `pytest <test> --cov=risk.manager` | ImportError — dotted **module** |
| `pytest <test> --cov=risk` | works — **package** |
| `pytest <test> --cov=risk/manager.py` | no error, collects nothing (`.coveragerc` `source` wins) |

Nothing to do with numpy being broken; it imports fine under `coverage run`
alone. Resolving a dotted *module* name makes coverage import the module itself.
A package name resolves as a directory and imports nothing.

The gate now measures the top-level package and reads the module's own row out of
the report. `TOTAL` is deliberately **not** a fallback: under a package-wide
`--cov` it is the package's number, and reporting it as the module's would be a
fabricated measurement of precisely the kind this gate exists to catch.

### Three real numbers, where there had been none

```
DEBT risk/gatekeeper.py:      21% < 80%   (recorded)
DEBT api/superadmin/ml_ai.py: 48% < 80%   (recorded)
FAIL risk/manager.py:         43% < 80%   (not recorded — blocks)
```

One figure needs stating so nobody reads it as a collapse: `risk/manager.py`
measures 43% here and 89.65% in `.coveragerc`'s recorded figure. Both are right —
this gate runs one test file, that figure runs the whole suite. Quoting the
gate's number as the module's coverage understates it by 46 points, so the
module docstring now says so.

### Repairing it was the easy half

`docs/COVERAGE_UNMEASURABLE.txt` records 361 modules, and — see the correction
now attached to §E5 — every entry is an artefact of the broken invocation. Fixing
the invocation without touching the list would swing the gate from passing
everything to blocking every commit that touches any of 361 files, and a gate
that blocks work people must do gets switched off. That is the same outcome by a
different route.

So the record became a ratchet with pressure in both directions, the shape the
document registry and gate-evidence ledger already use:

| state | outcome |
|---|---|
| recorded, under the floor | **DEBT** — real number on stderr, does not block |
| recorded, at or above the floor | **BLOCKS** — delete the line |
| not recorded, under the floor | blocks |
| not recorded, unmeasurable | blocks |

The second row is the tooth. Without it this is an allowlist, and an allowlist
under no pressure is how a ratchet stops being one. `--adopt` now preserves the
file's header rather than rewriting it, so regenerating cannot quietly revert the
record's meaning to the pre-repair wording.

`risk/manager.py` is deliberately **not** added to the record. It blocked before
this change and blocks after, so nothing regressed — and putting the pre-trade
gate, VaR/CVaR and Kelly sizing on a debt list to make a commit go through is the
one move this entire exercise argues against.

### What the same run turned up

`pytest -m "not slow and not e2e"` finished **6 failed, 21539 passed**. All six
are closed, and none by editing a test until it went quiet.

**Four were one defect.** `ml/cached_series.py::_check_integrity` judged whether a
bar was possible with three comparisons, and every comparison against NaN is
False — so a bar with a missing high satisfied all three and was counted sound.
The report then said "no OHLC violations" about a series that cannot be used for
anything. The whole point of that module is that a caller cannot tell a good
series from a bad one by looking at a DataFrame, so an integrity report that
clears bad data is not a weak measurement but a fabricated one.

Caught by the repository's own analyzer (`security/code_analyzer.py`, category
`nan_leak`) — the four failing tests were its zero-findings gates, and all four
were right to fail. Fixed by masking every comparison with a finiteness check
first, the order every predicate in `invariants/` uses. NaN bars are counted
separately as `non_finite`, because a missing value contradicts nothing and
folding it into `high_below_low` would put a violation in the record that the
data does not contain. Measured against the real file: `XAUUSD_40Y.csv` has **0**
non-finite bars, so §E15's and §E18's 441/6415 figure is unchanged.

**One was a test encoding the defect §E12 removed.**
`test_full_trading_cycle` built a RiskManager with no orchestrator and expected a
$20,000 position — which passed only because unmeasured data quality scored a
perfect 1.0. It has a data layer now, and the refusal it used to contradict is
held beside it by `test_the_cycle_refuses_without_a_data_layer`, so the wiring
cannot be mistaken for working around a red light.

**One was surface, not substance.** Two injection tests asserted the gate's old
wording. Both requirements still hold and are asserted more directly: an operator
must still be able to tell "coverage is low" from "coverage is unknown", and that
distinction is now *stronger* — a module its test never imports reports 0.00%,
which is a measurement, and calling it unknown would be the same Rule 2 error
pointed the other way.

### And the gates themselves had never been installed

This was found by noticing that a commit produced no hook output. There was no
hook. Every ratcheted check CLAUDE.md leans on — document registry, doc
freshness, Group 4 preservation, volume index, gate evidence, doc metrics, and
this coverage gate — protected only a contributor who remembered
`pre-commit run --all-files` by hand. CLAUDE.md's own sentence, "the ratcheted
checks below run in `pre-commit`, so a regression blocks rather than
accumulating", was describing something that was not happening.

Configured, accurate, never invoked: the §E9–§E12 shape, applied to the
machinery whose job is catching that shape. Which is also why it went unnoticed
so long — the gate that would have flagged it was one of the ones not running.

`scripts/bootstrap_dev.py::install_git_hooks()` now runs
`pre-commit install --install-hooks`. It deliberately does **not** fail
bootstrap: a developer without `pre-commit` on PATH still needs a working `.env`
and seeded users, and a bootstrap that dies on an optional step is one people
stop running, which would leave the hooks uninstalled for a second reason. It
returns False and warns — including on a non-zero exit, because reporting
success for work that did not happen is the defect this repository has spent the
most time removing.

Proven by running it: no hook before, `.git/hooks/pre-commit` after, and every
commit from that point ran the full set.

**Still an owner decision:** whether CI should also run `pre-commit run
--all-files`. Installing locally closes the gap for anyone who bootstraps; it
does not close it for anyone who does not, and a CI job changes what blocks a
merge.

## §E21 — The camera that was there all along (2026-09-09)

§18's `vision.gesture` and `vision.pointing` were the last two rows of the AI Hub
plan with real work in them, and they had been staged across two phases on one
recorded reason:

> There is no camera in the environment this was built in. Installing a
> two-megabyte runtime and an eight-megabyte model into a platform that moves
> money, and never executing either once, is committing code on faith.

The reasoning was sound. The premise was not, and nobody re-checked it — a
decision recorded as settled is the hardest kind to re-examine, which is why it
survived two phases of work that touched the files either side of it.

**Chromium serves a video file as a webcam.** `--use-fake-device-for-media-stream`
with `--use-file-for-fake-video-capture` has existed for years. What was missing
was the idea, not the hardware.

### What it took to falsify

| Claim on record | Measured |
|---|---|
| the dependency is a supply-chain question | `npm view @mediapipe/tasks-vision` resolves; the model host returns 206 |
| there is no camera | Chromium 141 fakes one from a `.y4m` |
| a hand to point it at | MediaPipe publishes its own test photograph |

### What now exists

* `hub/handDetector.ts` — the producer `landmarks.ts` was deliberately missing.
  The runtime arrives through a dynamic `import()`, so an operator who never
  turns this on downloads none of it — verified against the built bundle, where
  no chunk contains the detector.
* `hub/handGestureSource.ts` — a run of frames becomes one gesture track. A hand
  has no pointer-up, so a gesture ends when the hand LEAVES, and "leaves" is a
  RUN of empty frames rather than one: a single dropped detection mid-swipe is
  ordinary, and cutting the track there makes two gestures too short to read.
* `scripts/fetch_hand_model.py` — deploy-time fetch, sha256-verified, into this
  origin. Not committed: 7.8 MB against a 500 KB cap, and its absence is a
  *state* (`unconfigured`) rather than a break.
* `npm run prove:hands` — two phases. The detector against a still photograph;
  then the whole chain off a fake camera.

### The evidence

```
PHASE 1  21 landmarks · a 5-point track · pointing at "order-ticket"
PHASE 2  76 frames · 4 tracks · swipe_left ×4 · 481–600px over 326–441ms
```

`swipe_left` from a hand travelling left to right is the assertion doing work:
the console mirrors the camera because an operator sees their own reflection,
and a version that followed the raw coordinate would move focus the opposite way
from the gesture.

### Three defects the proof found, none of which a reading would have

1. **`landmarkStatus` reported "your browser cannot run it" about a runtime it
   had never tried to load.** The branch read `runtimeAvailable !== true` with
   the comment "an unmeasured runtime is absent, never present" — half of Rule 2.
   Not claiming an unprobed runtime works is right; stating it as broken is the
   same error reversed. Since consent is checked *before* the runtime loads, the
   ordinary "hasn't said yes yet" case hit this, so every such operator was sent
   to look for a browser fault that did not exist. `unsupported` now means
   probed and failed.
2. **A closed detector claimed the same thing.** Switching camera gestures OFF
   reported `unsupported`. Caught by the proof printing `closedState`, and the
   proof's own assertion was too weak to catch it — it ruled out one wrong answer
   and let the others through.
3. **The synthetic gesture was wrong three times, and `recogniseGesture` was
   right each time.** A 1.6-second swipe (`SWIPE_MAX_MS` is 600), then a 30fps
   video the detector undersampled to two points, then five positions that jumped
   128px and lost MediaPipe's inter-frame tracking. Each time the temptation was
   to loosen a threshold; each time that would have changed what a swipe means
   for POINTER input, to accommodate a video file.

### Why the rows are still staged

Nothing an operator can reach turns this on. `visionSource.ts` — §18's source
selector — has no production consumer either, so there is no existing control to
extend, and adding one is a UI change to a trading console.

**Whether this console may watch its operator through a webcam is the owner's
decision.** Marking a capability live that nothing can reach is precisely the
dead-control shape this registry exists to catch, and is the same reason Phase I3
refused to call these rows live for pointer input.

So the position moved from *blocked on something unverifiable* to *one decision
from live, with the code proven by execution*.

### The owner decided, and it is built — 233/233

**Opt-in toggle, off by default.** Shipped as the "Hands" control in
`PresenceStage`, beside Talk / Stop / Aloud, with the status reason on its
tooltip so an operator whose gesture does nothing learns which of the four
absences it is.

`useHandGestures` opens nothing while it is off — not "opens and closes", not
"prompts and is refused". `hub_camera_toggle_is_off_by_default.test.tsx` asserts
that rendering the stage never calls `getUserMedia`, because "off by default" is
exactly the property that survives review and dies to a later one-line change.
Every camera track is stopped on disable and on unmount: the hardware light
going out is how the operator knows it stopped.

The pointer and the camera now go through **one** `applyGesture`. Two rules for
what a swipe is would eventually disagree, and an operator could not be told
which one their console was using.

    233 rows · 233 live · 0 staged · 0 planned · 233/233 evidence resolves

§4's `arch.layer_a.presence` moved by itself, which is the derivation working:
nothing typed it live, the layers beneath it closed and it followed.

### "The camera should be able to work in background as well"

Owner's request, mid-build, and it caught a defect that was already written.

The loop was `requestAnimationFrame` — the obvious choice for anything reading
video, and wrong here: **browsers stop firing rAF entirely in a hidden tab.**
Switch tabs and the camera stays open, the hardware light stays on, and not one
frame is read. A control that looks alive and does nothing, shipped into the
exact feature where the operator can see it is watching them.

`hub/backgroundTicker.ts` drives the loop from a dedicated Worker instead. A
hidden document's timers are throttled to roughly one a second — too slow for a
500ms swipe — and a Worker's are not. There is no `visibilitychange` handling
anywhere, deliberately: a loop that switches strategy on visibility has a second
path that only runs when nobody is looking at it. A Worker that cannot be built
(a CSP without `blob:`) falls back to `setInterval` and *reports* that it did,
because a throttled loop beats no loop and pretending they are equivalent does
not.

**What is proven and what is not**, kept apart:

* **Proven by execution** — the loop is Worker-driven (`tickerKind: "worker"` in
  the phase 2 transcript), and `startTicker` never touches rAF (unit-asserted
  with a spy).
* **Not proven here** — that frames keep arriving with the tab genuinely hidden.
  Headless Chromium reports every page `visible`; `bringToFront()` on another tab
  does not change it, and there is no CDP override — `Emulation.setPageVisibilityOverride`
  does not exist, and `Page.setWebLifecycleState` leaves `visibilityState` alone.
  Both were tried. The proof therefore asserts the mechanism and *reports* the
  hidden-frame count rather than requiring it: an assertion that can only pass
  vacuously is worse than none.

## §E22 — Decisions get numbers, and the ratchet that proves gates work was one command from broken (2026-09-09)

Group 3 Chapter 6 opens with "Nothing in the repository implements ADRs", and
names the cost precisely: **re-litigation**. A decision whose reasoning is not
recorded is re-argued whenever someone new meets it, and sometimes reversed by
someone who does not know what it was protecting.

This session produced two of exactly that, which is why it was built now:

* §E20 corrected §E5's "verified by execution" claim — written in the very phase
  that made the check fail, and never re-checked.
* §E21 reversed a two-phase-old conclusion whose premise ("there is no camera
  here") nobody had re-examined.

Both were recoverable only because the reasoning had been written down
*somewhere*. `docs/ai/AI_HUB_DECISIONS.md` is that somewhere, and Group 3 names
its three limits exactly: it cannot be pointed at from a code comment, it cannot
be superseded in part, and it grows without bound.

### Nine records, and one real supersede chain

`docs/decisions/`, numbered and immutable, plus `scripts/adr.py`
(`--list`, `--check`, `new "Title"`). The spec named eight decisions to
back-fill; there are nine, because **0007 → 0009 is a decision this repository
genuinely reversed**: "ship everything except the model, there is no camera
here" superseded by "fetch it at deploy time, Chromium serves a video file as a
webcam".

That chain is the argument for the whole chapter in one file pair. The old
record is not edited and not deleted — it keeps its reasoning, gains a status,
and points at what replaced it.

### What is enforced, and the defect behind each rule

| Rule | Why |
|---|---|
| Two options minimum | One option is justification written after the fact |
| Every section, none empty | An empty heading is what a template leaves behind, and it passes a naive check |
| Immutable once accepted | A record that can be rewritten records what we *currently believe* we decided |
| A supersede must resolve | `superseded by 0042` pointing at nothing tells a reader their answer exists somewhere |
| Gapless numbering | So `see 0007` is stable for ever, and a gap cannot hide a deleted record |

Immutability is checked against **git**, not a hash manifest: a manifest is a
second file to edit, and the history is already authoritative. The one permitted
edit is a status becoming `superseded by NNNN` — proven both ways by execution,
a content change exiting 1 and a status-only change exiting 0.

### Adding the gate broke two other gates, and both were right to break

**The gate ledger refused it immediately.** `adr-check` appeared as a 24th gate
with no row in `GATE_EVIDENCE.toml`: *"A new gate ships with evidence it can
fail, or it is treated as absent (Rule 1)."* Exactly the intended behaviour, on
the first new gate since the ratchet reached zero.

**Then `--generate` corrupted the ledger.** The documented way to add a row
interpolated human-written text straight into a TOML basic string:

    f'injected = "{prior.injected}"'

`gate_d_model_accuracy`'s row contains a quoted phrase, so regenerating produced
TOML that would not parse, and every subsequent `--check` died before reporting
anything. **The ratchet that proves every other gate can fail was one documented
command away from being silently disabled** — and a backslash would have been
worse than a quote, parsing as an escape sequence and quietly altering the
recorded evidence rather than failing loudly.

Fixed with a real escaper and a round-trip test that regenerates the *committed*
ledger and re-parses it, so the tool can no longer write something it cannot
read. Found only because adding a gate is the operation that exercises it.

**And the freshness checker started calling a naming rule a stale path.** Group 3
writes `docs/decisions/NNNN-short-title.md` as a pattern; the moment
`docs/decisions/` existed, the checker resolved it and blocked. A false positive
that arrives precisely when the specified thing gets built is the worst timing
for a gate people can silence, so paths containing a template token are now
recognised as patterns.

### Measured after

    adr.py --check        9 records, all well formed
    gate_evidence.py      25 gates · 25 proven able to fail · 0 unproven
    docs_registry.py      0 blocking (all nine registered T3, owned)
    docs_freshness.py     0 blocking · doc_metrics 0 drifted

The stated gate figure in §B0 moved 23 → 24 in the same commit, because a
document carrying a number that stopped being true is worse than no document.

### What remains of item 13

The **Registry** half is done. The **Decision Ledger** (Group 3 Ch 7) and
**outcome memory** (Ch 8) are not: an append-only record of decisions made by
*automated* actors, with refusals as first-class entries, and a stated
prediction so an observed outcome has something to be compared against.
That is the half that makes the platform experienced rather than merely
knowledgeable, and it is still open.

## §E23 — The ledger, and the caller that keeps it from being scenery (2026-09-09)

§E22 built the Architecture Decision *Registry* — design decisions by humans.
This is the other half of ranked item 13: Group 3 Chapter 7's ledger of
*operational* decisions by the system, and Chapter 8's outcome linkage.

### Why a fourth recorder, when three already exist

`ai/gateway/audit.py` records model calls, `ai/improve/proposal.py` records
AI-proposed changes, pull requests record approvals — and the spec's diagnosis
is that this is precisely why nobody can answer "what did the platform decide
today?". The risk of getting it wrong was making that four unanswerable
questions instead of three, so `ai/ledger/` **consumes** rather than restates:
authority tiers imported from `ai/policy/roles.py`, calibration delegated to
`ai/core/calibration.py`, credential screening from `ai/guardrails/output.py`.
Recorded as ADR 0010, including the failure mode — if a later change has the
ledger keeping its own tier list, this decision has been undone in substance
while the file still exists.

### The three properties that make it worth having

**Refusals are entries, not absences.** A ledger of actions *taken* cannot tell
a system that was never asked from one that refused, and on this platform the
refusals are the evidence that governance worked. A refusal must name the
control that produced it, because Chapter 7's own KPI is refusals recorded
versus refusals observed — and "something said no" cannot be checked against a
control's logs.

**A prediction is required.** Chapter 8 makes it load-bearing: without a stated
expectation an observed outcome has nothing to be compared against and learning
degrades into narrative. A decision cannot be recorded without one; a refusal
needs none, because nothing happened.

**Unmeasured stays unmeasured.** Confidence is `None` when nobody stated one,
never 0.5, and its calibration class is `None` with it. A governance record is
the worst possible place to reintroduce the defect §E12 through §E21 kept
finding.

### Two rules deliberately differ from the ADR gate

* **One option is allowed here.** An ADR with one option is justification
  written afterwards. An automated router legitimately has one candidate when
  the others are unavailable, and demanding a second would make the ledger
  describe a choice nobody had.
* **`held` must be stated.** Accuracy is never inferred from prose. Comparing a
  free-text prediction against a free-text observation would manufacture exactly
  the unmeasured figure this work has been removing; what the module guarantees
  is that the question was *asked*.

### The caller, because a ledger nobody writes to is scenery

Building this without one would have committed the F176 shape inside the module
meant to record it — Chapter 7's KPI is ledger coverage, and a schema with no
callers has zero coverage while every unit test passes.

`risk/manager.py::_zero_sizing` is the first caller and not an arbitrary one: it
is the single funnel every sizing refusal passes through, and those refusals —
`data_quality:unmeasured` above all — are this repository's clearest evidence
that a gate did its job. Until now the only record of one was a WARNING line.

**Recording never changes what the money path decides.** A ledger write that
raised would turn a refusal into a crash, strictly worse than the defect it
documents. So it is wrapped, and wrapped at ERROR rather than silently: F248's
alert failures went unnoticed for as long as they did because a handler swallowed
them. `test_a_broken_ledger_does_not_break_a_refusal` injects a raising ledger
and asserts the refusal still happens; the test that the refusal happens at all
is asserted *first*, so a wiring bug cannot hide behind it.

### And it gave calibration the caller it never had

`ai/core/calibration.py` has `record()` and `resolve()`. Nothing called
`resolve()`, so every stated confidence stayed unscored and `assess()` had
nothing to assess — a measurement apparatus with no inputs, which reads as
working. `outcomes.observe()` closes that loop.

### One defect in the tooling shipped an hour earlier

`adr.py new "Title"` — the invocation the README and the module docstring both
give — failed with *unrecognized arguments*: `new` was a single positional and
the title had nowhere to go. Found by running it. A tool whose documented
invocation does not work teaches people it is broken, and sends them back to
recording decisions in commit messages, which is the thing §E22 exists to stop.
Fixed, with tests that run the documented command.

### Measured

    pytest -k "risk or ledger or calibration"    1988 passed
    test_decision_ledger.py                      24
    test_ledger_outcomes.py                      20
    test_risk_refusals_reach_the_ledger.py       8   (5 fail on the pre-wiring tree)
    adr.py --check                               10 records, all well formed
    docs_registry / docs_freshness / doc_metrics 0 blocking · 0 drifted

### What is still open from item 13

Group 2 Chapter 6's **change records carrying an expected effect** — the same
prediction field one layer down, attached to a deployment rather than a
decision. Ranked item 5, still open, and now the only part of Decision
Governance that is not built.

## §E24 — Change records, and a hole in the gate that enforces gates (2026-09-09)

Ranked item 5, and the last open part of Decision Governance. §E22 recorded
design decisions by humans, §E23 operational decisions by the system; this is
the same prediction field one layer down, attached to a deployment.

Chapter 6's own sentence for why:

> A deployment log records that something happened, and a change record records
> what it was *for*. Only the second can be evaluated. **A history without
> predictions cannot teach anything.**

### Generated, not written — except the one field that matters

Every field comes from git and the tree. The exception is the expected effect,
which is the point: it is the only field a machine cannot derive and the only one
that makes the record evaluable. It arrives as an `Expected-Effect:` commit
trailer, because trailers are already how this repository carries structured
commit metadata (`Co-Authored-By`, `Claude-Session`) and a prediction kept
anywhere else drifts from the commit it describes.

Enforced at **`commit-msg`**, not `pre-commit`: the trailer being checked does not
exist yet at the earlier stage.

### The tier is derived from paths, and the module says so

Chapter 6 sources "packages touched" from Chapter 1's package register, which
**does not exist** — ranked item 10, still open. `TIER_SOURCE = "path-prefix"` is
printed on every report and the docstring states it plainly, because a path table
silently substituted for the register would make item 10 look delivered. That is
the shape §E20 had to correct in §E5. Recorded as ADR 0011, including what would
constitute reversing it.

**Unknown is not safe.** An unclassified path is `unknown`, never `presentation`,
and `unknown` requires a prediction exactly as `core` does. Rule 2 where it costs
most: the alternative is that the first unclassified package added to this
repository is the one that ships unpredicted.

### Two defects the first version had, both found by running it

**`lstrip("./")` strips a character SET, not a prefix.** `.gitignore` became
`gitignore`, and `.github/workflows/ci.yml` would have become
`github/workflows/ci.yml` — a path matching no prefix, landing in the wrong tier
silently. Caught by a parametrised root-path test.

**The root fell through to `unknown`,** so editing `CLAUDE.md` demanded a
deployment prediction. Friction with no safety in it, and friction is how a gate
earns a bypass. Calling the whole root `presentation` would have been the
opposite error: `app.py`, `run.py`, `hopefx_engine.py` and `trader_full.py` all
live there and all start the trading path. Root prose is presentation; anything
else at the root is `core`.

`.github/` and `.pre-commit-config.yaml` are classified `core` on evidence rather
than instinct: CI is the control plane for every gate here, and §E20 found the
pre-commit hooks had never been installed, so seven ratcheted checks protected
nobody.

### And the gate that enforces gates could not see it

`scripts/gate_evidence.py` discovered hooks by matching `scripts/*.py` entries.
This hook runs `python -m deployment.change_records`, so **it was invisible**: the
ledger reported 24 gates before and after it was added, and `--check` passed.

Any gate written as a module rather than a script was silently exempt from Rule 1
— a hole in the census that every other gate's evidence depends on. Discovery now
matches `python -m <dotted.module>` too, but only for modules this repository
owns, since a `python -m` of a third-party tool is not a gate we can carry
evidence for. Adding the match immediately produced the block it should have
produced an hour earlier, and `tests/unit/test_change_record_gate_injections.py`
is what it then demanded.

That is the third time this session that adding something exposed a hole in the
machinery meant to catch holes — the ledger's TOML writer in §E22, the coverage
gate's single-file measurement in §E23, and now the gate census.

### One more dead control, one hook type over

`bootstrap_dev.py` ran `pre-commit install`, which installs only the `pre-commit`
hook type. The change-record gate runs at `commit-msg`, so a fresh clone would
have had it as a dead control from the day it shipped — §E20's defect, repeated
one hook type over. Both types are installed now.

### Measured

    change_records                                42 tests
    change-record gate injections                 15 tests
    gate_evidence.py                              25 gates · 25 proven · 0 unproven
    adr.py --check                                11 records, all well formed
    docs_registry / docs_freshness / doc_metrics  0 blocking · 0 drifted

Run against real history: the §E23 commit reports `core` (it touches `risk/`) and
is correctly refused for stating no expected effect; the §18 commit reports `ai`
and is not.

### What this unblocks

Group 1 §16 (operational correlation — "what deployed just before latency rose"
is unanswerable without it), §21 (technical-debt forecasting, which needs
modification frequency per package) and §32 (outcome memory).

**Decision Governance is now complete**: ADRs for human design decisions, the
ledger for automated operational ones, change records for deployments, and one
prediction field running through all three.

### The owner chose warn over block, and the KPI is measured rather than met

Asked directly, the owner chose **warn** (ADR 0012). Implemented literally,
Chapter 6's 100% target would have refused 4 of this session's last 12 commits —
a real change to how the only committer commits, and the kind of interruption
that ends in a bypass. §E20 is this repository's own example of a gate switched
off rather than satisfied.

The objection to warning is real and the record does not pretend otherwise: a
gate that only warns is one people learn to scroll past. Three things answer it,
each asserted in the injection suite:

* the warning names the exact trailer to add, so acting is cheaper than ignoring;
* `CHANGE_RECORD_ENFORCE=1` blocks with no code change, so the policy is
  configuration and can be turned on in CI, on one branch, or permanently;
* `--report` measures the KPI, because **a warning whose effect is never measured
  is precisely what the objection is about**.

`validate()` is unaffected by the policy. It reports the problem either way — the
decision is about the exit code, never about the truth.

The first measurement, over this session's own commits:

    changes 12 · needing a prediction 5 · with one 1 · coverage 20%

A real starting number rather than a target met by force. `coverage` is **None**
when nothing in a range needed a prediction — a perfect score from an empty
denominator is the oldest fabricated metric there is, and this module refuses to
report one, the same rule the risk gate applies to data quality and the ledger to
confidence.

`docs/GATE_EVIDENCE.toml` now carries the caveat that this is the one gate in the
ledger that does not block by default. Twenty-five gates counted as blocking when
one is advisory would be the same fabrication the ledger exists to prevent.
