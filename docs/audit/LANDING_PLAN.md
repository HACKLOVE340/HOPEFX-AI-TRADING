# Landing the audit branch — LANDED 2026-09-18

> **This plan was not used, and the branch landed anyway.** Kept because the
> evidence it produced is real and the reasons it was abandoned generalise.
> Read this box before reading anything below it: everything after it is
> written in the present tense about a state that no longer holds.

`claude/add-new-skills-lys862` merged into `main` on **2026-09-18** as PR #315,
merge commit **9cdc37a** — 666 commits, 1,561 files, in **one merge**, not nine
slices. The branch is now **80 commits and 140 files ahead of `main`** (measured;
`scripts/doc_metrics.py --sync` maintains both figures), and that figure is
follow-up work, not a backlog to land.

## Why the nine slices were abandoned

Two slices were cut and proven green in isolation before the approach was
dropped, and both manifests are real evidence — `SLICE1_MANIFEST.md` (128 files,
nineteen gates, 554 passed) and `SLICE2_MANIFEST.md` (46 files, 19,164 passed). What
they proved, between them, is that **the path partition does not match the
dependency graph**:

* Slice 1's artefacts are whole-repository indices. An index of a partial tree
  cannot be complete, so several gates could not run at all on their own slice.
* Slice 2 was scoped as two directories and needed **24 source files drawn from
  six**, every addition forced by an import error or a failing assertion.
* `social/` was named in **no slice at all**, and it holds a revenue-split
  function. A path in no slice lands in no PR.

By slice 5 or 6 the slices would have overlapped enough to stop being
independent PRs — `core/startup_factories.py` alone is +783 lines and was
already blocking two of slice 2's tests.

The review the slicing was meant to buy also was not available: greptile refuses
at 100 files, and nine PRs of ~170 files each get read no more carefully than
one. The safety argument that replaced it was **execution**: the full fast suite
green on Python 3.11 **and** 3.12 (25,243 passed, 0 failed, clean tree on both)
at the merged head, because GitHub Actions had assigned no runner to any job for
twelve days (F95) and no CI run has ever executed against any of this.

Merging while Actions was down was the safest window rather than the riskiest:
nothing deployed on the merge, and `main`'s own `deploy.yml` was at that moment
**ungated** — it fired on every push to `main` and SSHed into the production VPS
with no CI dependency. The merge replaced it with the branch's CI-gated version.

## What still applies

The recipe in §"The recipe, proven" is sound and worth reusing for any future
large landing. So are the three rules slice 2 established: a money control
travels with the money rather than with its directory, a generated document
travels with the code that generates it, and a test file travels to the latest
slice it depends on. The slice tables below are a record of an approach, not a
queue of work.

---

## 1. What is actually on the branch

Measured against `origin/main`, not estimated:

| | Files | Note |
|---:|---:|---|
| **Added** | 1,010 | Tests, docs, new `ai/` and `frontend/` modules. Additive, low review risk. |
| **Renamed** | 39 | 34 are pure renames (`R100`); 5 carry edits. |
| **Modified** | 507 | The real review surface. |
| — of those, money/safety path | **53** | `payments/ monetization/ execution/ risk/ brokers/ invariants/ auth/ security/ database/ alembic/` |
| Total | 1,556 | +313,638 / −11,470 |

**Nothing is deleted** — `git diff --name-status` reports 0 `D` entries. 1,010 of
the 1,556 files did not exist on `main`, so most of the diff cannot break
anything that currently runs. A reviewer's attention belongs on the 53.

These figures were 889 / 357 / 62 / 1,246 when this plan was written on
2026-09-14 and are re-measured above on 2026-09-17. Only the header line's two
figures are maintained by `scripts/doc_metrics.py --sync`; this table is not,
so it drifted while the header stayed current — re-measure it with
`git diff --name-status origin/main...HEAD` rather than trusting it.

## 2. What it delivers, measured rather than claimed

`scripts/correction_register.py` probes the code rather than reading a
changelog, so it can be run against either tree and the two answers compared:

```
on origin/main :  76 findings · OPEN 54 · PARTIAL  3 · OWNER 5 · UNVERIFIED 1 · FIXED 13
on this branch :  76 findings · OPEN  4 · PARTIAL 11 · OWNER 5 · UNVERIFIED 1 · FIXED 55
```

Re-measured 2026-09-13. The plan recorded 73/51/12 against 73/14/45 when written;
the register has since grown by three findings and the branch has closed more.

**50 findings improve. None regress.** 42 move OPEN → FIXED (AI-GATE, AI-SURFACE,
DEPLOY-CHART, F106, F120, F123, F130, F135, F136, F137, F142, F144, F159, F173,
F178/F98, F184, F187, F199, F200, F201, F203, F204, F205, F208, F209, F214, F215,
F216, F217, F219, F220, F221/F105, F222, F80, F81, F84, F96, F99, FIX-STORE,
KS-SELFHEAL, ML-LEAK, ROUTER-TO) and 8 move OPEN → PARTIAL (AFF-TIER, F147, F175,
F198, F31/F32, F61/F107, F97, OF-VOTER).

The plan recorded 37 improving (33 → FIXED, 4 → PARTIAL) when written. The lists
are generated by comparing the two registers per finding id, not retyped.

Several of the PARTIALs above have since advanced — F31/F32, F97 and A8 are
FIXED as of 2026-09-14. This block is a dated snapshot of a comparison, not a
live figure; re-run the command below rather than reading it as today's state.

That is a second witness, and it is not prose. Reproduce it with:

```bash
git worktree add --detach /tmp/wt-main origin/main
git -C /tmp/wt-main checkout <branch-head> -- scripts/ docs/audit/CORRECTION_REGISTER.md
python /tmp/wt-main/scripts/correction_register.py     # main's state
python scripts/correction_register.py                  # this branch's state
```

**It is not CI.** It measures structure, not behaviour. See §5.

## 3. Why not one pull request

1,556 files cannot be reviewed. A PR that size is approved on trust, which
defeats the point of review — and this branch touches order routing, payouts,
authentication and model loading.

## 4. The slices

Each is cut **by path from the branch head onto `main`**, so every PR is a
coherent diff of final state rather than a temporal cut through 650 interleaved
commits. Order matters: tooling first, so the ratchets are on `main` guarding
everything that follows.

| # | Slice | Paths | Why here |
|---|---|---|---|
| 1 | **Measurement & gates** | `scripts/`, `.pre-commit-config.yaml`, `docs/GATE_EVIDENCE.toml`, `docs/REGISTRY.toml`, `docs/COVERAGE_UNMEASURABLE.txt`, `docs/FRESHNESS_BASELINE.toml`, `docs/audit/CORRECTION_REGISTER.md`, matching tests | Lands the ratchets first. Everything after it is then guarded by checks already on `main`. |
| 2 | **Money** | `payments/`, `monetization/`, `social/marketplace.py`, `invariants/enforcement.py`, `invariants/ai.py`, `database/models.py`, `api/payments.py`, `api/billing.py`, `api/superadmin/financial.py`, `docs/API_ENDPOINTS.md` + tests | F31/F32, F135, F136, F203, F204, F205, F206, F207, F208, F222. **Cut and proven green — `SLICE2_MANIFEST.md`.** The scope above is measured, not planned: `payments/` + `monetization/` alone cannot import. |
| 3 | **Order path** | `execution/`, `risk/`, `brokers/`, `invariants/`, `core/risk/` + tests | F61/F107, F81, F84, F142, FIX-STORE, ROUTER-TO. Needs the closest reading. |
| 4 | **Auth & security** | `auth/`, `security/`, `api/security/`, `database/`, `alembic/` + tests | F99, F130, F144, F184. |
| 5 | **ML & backtesting** | `ml/`, `backtesting/`, `strategies/`, `analysis/`, `news/`, `data/` + tests | F80, F119, F120, F123, F125, F145, F147, ML-LEAK, OF-VOTER. |
| 6 | **AI layer** | `ai/`, `support/` + tests | Almost entirely new files. AI-GATE, AI-SURFACE. |
| 7 | **API & runtime** | `api/`, `core/`, `mobile/`, `notifications/`, `data_layer/` + tests | F198, F199, F214, F219, F220. |
| 8 | **Frontend** | `frontend/`, `dashboard/` | F149, F150, F173, F175, F187, F201, F209, F210. |
| 9 | **Docs & skills** | `docs/`, `.claude/`, root `*.md`, `deployments/`, `.github/` | F216, F217, F96, F97. |

Tests travel with the slice they cover. `tests/` holds 358 changed files; split
them by the module each one names, not as a block.

**The nine slices do not partition the tree.** `social/` is named in no row
above, and `social/marketplace.py` holds `StrategyMarketplace.split_revenue` —
a revenue split, i.e. money. It was found only because 41 slice-2 tests failed
on it. A path in no slice is a path that lands in no PR, so before cutting
slice 3, run the partition against the tree and close every gap:

```bash
comm -23 <(git ls-tree -d --name-only ea24b4f | sort) <(printf '%s\n' <the paths named above> | sort)
```

`social/` is now assigned to slice 2 for `marketplace.py`; its other seven files
(copy trading, leaderboards, profiles, performance) are unchanged from `main`
and need no slice.

### The recipe, proven

Slice 1+2 was built on `origin/main` and its tests run green in isolation
(30 passed) before this plan was written. For each slice:

```bash
git worktree add --detach /tmp/wt-slice origin/main
git -C /tmp/wt-slice checkout <branch-head> -- <paths for this slice>
cd /tmp/wt-slice && pytest <the tests for this slice> -q     # must be green
pre-commit run --all-files                                    # must be clean
```

Only then cut the branch and open the PR. A slice whose tests do not pass in
isolation has an undeclared dependency on a later slice — move the dependency
forward rather than merging out of order.

### Slice 1 does not pass in isolation — measured 2026-09-17

That rule was applied to slice 1 as this table specifies it, and slice 1 fails
it. The "30 passed" above was true when the slice was three scripts; the slice
is now 52 scripts and 20 test files, and the gates in it read documents and
import packages that this plan schedules for slices 6 and 9.

Cut onto `origin/main` exactly as the recipe says, with the 33 test files that
name `scripts`:

| Slice 1 contains | Result |
|---|---:|
| 58 files (52 `scripts/`, 5 `docs/`, `.pre-commit-config.yaml`) + tests | **147 failed, 402 passed** |
| \+ `docs/ai/specs/` (11 files, from slice 9) | 128 failed, 421 passed |
| \+ `ai/` and `invariants/` (from slice 6) | **90 failed, 459 passed** |

The dependency is not incidental, and it is not a bug in the gates. Two of them
refuse rather than reporting a number they cannot stand behind:

```
group4_preservation : source not found: docs/ai/specs/GROUP4_master_ai_operating_system.txt
doc_metrics         : REFUSED — docs/ai/MASTER_OUTSTANDING.md is missing — refusing to report a count
```

`doc_metrics` is the clearest case and the 54 failures that did not move at any
step above: it exists to check that living documents state the measured figures,
so it cannot be green on a tree that does not carry those documents. **A
figure-checking gate is inseparable from the documents it polices.**

So the ordering needs one of these decisions, and it is the owner's:

1. **Fold the data into slice 1** — `docs/ai/specs/` and `docs/ai/MASTER_OUTSTANDING.md`
   travel with the gates that read them. Smallest change, and it keeps the
   "ratchets first" principle that motivates the order.
2. **Land slice 1 with its document-reading gates disabled**, and enable them in
   slice 9. Keeps the slice small; ships a hook that does not run, which is the
   defect the `hopefx-dead-controls` skill exists to prevent.
3. **Reorder** so documents precede gates. Loses the guarantee that everything
   after slice 1 is guarded.

Option 1 is the recommendation: the failures are concentrated in gates whose
inputs are data files, not code, so moving the data forward costs one slice a
few documents rather than restructuring the sequence.

The remaining 90 were not driven to zero, deliberately — each further package
added pulls the slice closer to the whole branch, which is the thing this plan
exists to avoid. The number to act on is the shape of the dependency, not its
tail.

### Option 1 was executed. It is not sufficient, and the reason is structural

`docs/ai/specs/` and `docs/ai/MASTER_OUTSTANDING.md` were folded in and the
slice driven as far as it goes. It does not reach green, and the residue is not
a fold that was missed.

| Step | Failed | Passed |
|---|---:|---:|
| Slice 1 as the table specifies it, 33 test files | 147 | 402 |
| \+ `docs/ai/specs/` and `MASTER_OUTSTANDING.md` | 95 | 422 |
| \+ move the three `ai/`-coupled gates out, pull in every test `GATE_EVIDENCE.toml` cites, trim the indices | 24 | 470 |
| \+ move every subsystem gate out (frontend, ml, api, alembic, coverage) — 115 files, 24 test files | **5** | 336 |

The fold did work: `group4_preservation` went green and `doc_metrics` stopped
reporting a missing document. It then refused for a second reason —
`spatial_capabilities`, which `doc_metrics.measure()` calls unconditionally,
cannot resolve `ai.spatial`. Folding `ai/spatial/` and `ai/hub/` in (11 files)
did not close it either: the spatial register's evidence locators name
`ai/departments/` and `frontend/src/hub/spatial.ts`, and `capability_callers`
refuses because its positive control `PresenceAnywhere` lives in the frontend.
Both refusals are correct — neither gate will report a number it cannot stand
behind — and both are unreachable before slices 6 and 8.

**The five that remain are all one thing, and no fold fixes them:**

```
gate_evidence  : gate_chroma_embedded_only, gate_j_circular_imports have no row
                 — their evidence tests are in later slices
aos_conformance: AOS-API-001 names scripts/api_documentation_generator.py, gone with slice 7
docs_freshness : its positive control hard-codes ai/gateway/, so the parent is absent
correction_reg.: the model probes degrade to UNVERIFIED with no ml/ to import
```

**Slice 1 is the measurement layer, and every artefact in it is a
whole-repository index** — the correction register, the gate-evidence ledger,
the document registry, the freshness baseline, the coverage baseline, the AOS
register. An index of a tree that is not there cannot be complete, and the
entries it is missing *are* the other eight slices. This is not a dependency
that can be moved forward; it is the slice's own subject matter.

Two consequences for landing, and they replace the recommendation above:

1. **Slice 1's tests cannot be its merge gate in isolation.** What slice 1
   should be reviewed for is the machinery — that each gate is correct and can
   fail — and that is proven on the full tree, where the whole suite passes
   (25,242 passed, 43 skipped, 0 failed, measured 2026-09-17). Demanding green
   in isolation demands that the measurement layer measure nothing.
2. **Every index regenerates at every slice, not just the register.** §"One
   wrinkle in slice 1" says this for `CORRECTION_REGISTER.md`. It is true of
   `GATE_EVIDENCE.toml`, `REGISTRY.toml`, `FRESHNESS_BASELINE.toml`, the
   coverage baseline and `AOS_INVARIANT_REGISTER.toml` as well, and each of
   those has an `--adopt` or `--generate` for exactly that.

A gate travels with the subsystem it measures, the same rule the plan already
applies to tests. On that rule slice 1 holds 23 gates rather than 33; the
frontend ratchets go to slice 8, the model and coverage gates to slice 5, the
API documentation gate to slice 7, the migration gate to slice 4, and
`spatial_capabilities`, `capability_callers` and `doc_metrics` to slice 6.

### One wrinkle in slice 1

`correction_register.py --check` compares the document against what it probes.
Landed on `main` alone, it measures **51 OPEN**, not the branch's 14, so slice 1
must ship a register regenerated against `main`:

```bash
python scripts/correction_register.py --write   # regenerate §3, keeping the prose
```

Each later slice then flips its own findings and regenerates again. That is the
register working as designed — it describes the tree it is on — and it makes
every PR state, mechanically, what it just fixed.

### Slice 2 is cut and green — measured 2026-09-18

`pytest -m "not slow and not e2e"` on `origin/main` + slice 2: **19,164 passed,
39 skipped, 0 failed** (12m40s, exit 0). 46 files. Full detail, including the
reproduction commands, in `SLICE2_MANIFEST.md`.

Three things it established that apply to every slice after it:

1. **A money control travels with the money, not with its directory.** Money
   crosses `payments/`, `monetization/`, `social/`, `invariants/`, `database/`
   and `api/`. The cent-truncation fix (`int(10.999 * 100)` charges 1099) lives
   in `api/payments.py`, which the plan puts in slice 7. A path-based cut
   separates a money defect from its fix.
2. **A generated document travels with the code that generates it.**
   `docs/API_ENDPOINTS.md` is rendered from the registered routers, so adding
   two refund-policy routes broke a test nowhere near `payments/`. Regenerate
   it *in the slice* — the branch head's copy reflects all nine slices.
3. **A test file travels to the latest slice it depends on.** Four files were
   cut and withdrawn to slices 6 and 7. None was weakened or deleted to reach
   green, including the two that fail *because*
   `monetization/marketplace_submission.py` correctly refuses to approve
   uncontained strategy code when the sandbox is absent.

The isolation run alone would have missed one of these. Only the **full fast
suite** catches a slice that breaks something already on `main`; run it for
every slice, not the slice's own tests.

## 5. What none of this substitutes for

**F95.** GitHub Actions has not run on this branch, or on `main`, for the whole
period. Every "verified" line in every commit message here means *one careful
person ran it locally*. The register delta in §2 is a structural cross-check,
not a behavioural one: it can tell you a guard exists and is wired, and it
cannot tell you the suite passes on a clean machine.

**Fix the billing before merging any slice.** Not because a slice is unsafe
without it, but because the first thing each PR should show is a green build,
and today none of them can.
