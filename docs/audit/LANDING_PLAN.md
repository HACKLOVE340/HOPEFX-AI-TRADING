# Landing the audit branch

`claude/add-new-skills-lys862` is **551 commits and 1,227 files ahead of `main`**,
and has been since 20 August. Nothing on it has been merged, and no CI run has
ever executed against any of it.

This document is how it gets onto `main` without asking anyone to approve
275,894 lines on trust.

---

## 1. What is actually on the branch

Measured against `origin/main`, not estimated:

| | Files | Note |
|---:|---:|---|
| **Added** | 876 | Tests, docs, new `ai/` and `frontend/` modules. Additive, low review risk. |
| **Modified** | 351 | The real review surface. |
| — of those, money/safety path | **54** | `payments/ monetization/ execution/ risk/ brokers/ invariants/ auth/ security/ database/ alembic/` |
| Total | 1,227 | +275,894 / −5,730 |

**Nothing is deleted.** 876 of the 1,227 files did not exist on `main`, so most
of the diff cannot break anything that currently runs. A reviewer's attention
belongs on the 54.

## 2. What it delivers, measured rather than claimed

`scripts/correction_register.py` probes the code rather than reading a
changelog, so it can be run against either tree and the two answers compared:

```
on origin/main :  73 findings · OPEN 51 · PARTIAL 4 · OWNER 5 · UNVERIFIED 1 · FIXED 12
on this branch :  73 findings · OPEN 14 · PARTIAL 8 · OWNER 5 · UNVERIFIED 1 · FIXED 45
```

**37 findings improve. None regress.** 33 move OPEN → FIXED (F80, F81, F84, F96,
F99, F120, F123, F130, F135, F136, F137, F142, F144, F159, F184, F201, F203,
F204, F205, F208, F209, F214, F215, F216, F217, F219, F220, F221/F105, F222,
AI-SURFACE, FIX-STORE, ML-LEAK, ROUTER-TO) and 4 move OPEN → PARTIAL (F31/F32,
F61/F107, F97, F147).

That is a second witness, and it is not prose. Reproduce it with:

```bash
git worktree add --detach /tmp/wt-main origin/main
git -C /tmp/wt-main checkout <branch-head> -- scripts/ docs/audit/CORRECTION_REGISTER.md
python /tmp/wt-main/scripts/correction_register.py     # main's state
python scripts/correction_register.py                  # this branch's state
```

**It is not CI.** It measures structure, not behaviour. See §5.

## 3. Why not one pull request

1,227 files cannot be reviewed. A PR that size is approved on trust, which
defeats the point of review — and this branch touches order routing, payouts,
authentication and model loading.

## 4. The slices

Each is cut **by path from the branch head onto `main`**, so every PR is a
coherent diff of final state rather than a temporal cut through 551 interleaved
commits. Order matters: tooling first, so the ratchets are on `main` guarding
everything that follows.

| # | Slice | Paths | Why here |
|---|---|---|---|
| 1 | **Measurement & gates** | `scripts/`, `.pre-commit-config.yaml`, `docs/GATE_EVIDENCE.toml`, `docs/REGISTRY.toml`, `docs/COVERAGE_UNMEASURABLE.txt`, `docs/FRESHNESS_BASELINE.toml`, `docs/audit/CORRECTION_REGISTER.md`, matching tests | Lands the ratchets first. Everything after it is then guarded by checks already on `main`. |
| 2 | **Money** | `payments/`, `monetization/` + tests | F31/F32, F135, F136, F203, F204, F205, F206, F207, F208, F222. Highest value, smallest blast radius. |
| 3 | **Order path** | `execution/`, `risk/`, `brokers/`, `invariants/`, `core/risk/` + tests | F61/F107, F81, F84, F142, FIX-STORE, ROUTER-TO. Needs the closest reading. |
| 4 | **Auth & security** | `auth/`, `security/`, `api/security/`, `database/`, `alembic/` + tests | F99, F130, F144, F184. |
| 5 | **ML & backtesting** | `ml/`, `backtesting/`, `strategies/`, `analysis/`, `news/`, `data/` + tests | F80, F119, F120, F123, F125, F145, F147, ML-LEAK, OF-VOTER. |
| 6 | **AI layer** | `ai/`, `support/` + tests | Almost entirely new files. AI-GATE, AI-SURFACE. |
| 7 | **API & runtime** | `api/`, `core/`, `mobile/`, `notifications/`, `data_layer/` + tests | F198, F199, F214, F219, F220. |
| 8 | **Frontend** | `frontend/`, `dashboard/` | F149, F150, F173, F175, F187, F201, F209, F210. |
| 9 | **Docs & skills** | `docs/`, `.claude/`, root `*.md`, `deployments/`, `.github/` | F216, F217, F96, F97. |

Tests travel with the slice they cover. `tests/` holds 353 changed files; split
them by the module each one names, not as a block.

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

### One wrinkle in slice 1

`correction_register.py --check` compares the document against what it probes.
Landed on `main` alone, it measures **51 OPEN**, not the branch's 14, so slice 1
must ship a register regenerated against `main`:

```bash
python scripts/correction_register.py --markdown   # regenerate §3 of the register
```

Each later slice then flips its own findings and regenerates again. That is the
register working as designed — it describes the tree it is on — and it makes
every PR state, mechanically, what it just fixed.

## 5. What none of this substitutes for

**F95.** GitHub Actions has not run on this branch, or on `main`, for the whole
period. Every "verified" line in every commit message here means *one careful
person ran it locally*. The register delta in §2 is a structural cross-check,
not a behavioural one: it can tell you a guard exists and is wired, and it
cannot tell you the suite passes on a clean machine.

**Fix the billing before merging any slice.** Not because a slice is unsafe
without it, but because the first thing each PR should show is a green build,
and today none of them can.
