# AGENTS-IMPROVEMENT-SPEC.md

Audit of agent/AI-assistant guidance in this repository, with a concrete
improvement plan.

---

## What Was Audited

| File / Location | Exists? |
|-----------------|---------|
| `AGENTS.md` | ❌ Missing (created by this session) |
| `.ona/skills/` | ❌ Missing |
| `.cursor/rules/` | ❌ Missing |
| `.github/PULL_REQUEST_TEMPLATE.md` | ❌ Missing |
| `ARCHITECTURE.md` | ✅ Present |
| `README.md` | ✅ Present |
| `DEPLOYMENT.md` | ✅ Present |
| `.devcontainer/devcontainer.json` | ✅ Present |
| `.gitpod/automations.yaml` | ✅ Present |
| `pyproject.toml` | ✅ Present |
| `pytest.ini` | ✅ Present |
| `ruff.toml` | ✅ Present |

---

## What's Good

1. **`ARCHITECTURE.md` is accurate and detailed.** Canonical vs. legacy module
   map, ML model facts, component status table, and key env flags are all
   present and up to date (last updated v1.19).

2. **`pyproject.toml` is well-structured.** mypy strict overrides on
   `risk/analytics`, `api/`, and `ml/inference_engine` are appropriate for
   risk-critical code. Bandit skips are documented with rationale.

3. **`ruff.toml` is thorough.** Per-file ignores are documented with reasons.
   `PLR2004` suppression for domain-specific numeric literals is correct.

4. **`pytest.ini` is complete.** Markers are defined, asyncio mode is set,
   timeout is configured, and CI-fast mode is documented.

5. **`.gitpod/automations.yaml` is production-quality.** Redis, backend, and
   frontend services have `ready` probes. Dev env vars are set correctly.

6. **`devcontainer.json` is well-commented.** Explains why Python 3.10 is
   pinned (pickle protocol parity), why Redis is installed via apt, and what
   `bootstrap_dev.py` does.

7. **CI is comprehensive.** 15 workflows cover linting, type checking, security
   scanning, Docker smoke tests, and scheduled ML retraining.

8. **Security posture is documented.** `ARCHITECTURE.md` lists all 13 security
   fixes applied in v1.18 with file references.

---

## What's Missing

### 1. `AGENTS.md` — No agent guidance existed
The most critical gap. No file told an AI agent how to navigate this large,
complex codebase. Created in this session.

### 2. No PR template
`.github/PULL_REQUEST_TEMPLATE.md` is absent. PRs have no standard structure,
making it easy for agents to write low-quality PR descriptions.

### 3. No `.ona/skills/` or `.cursor/rules/`
No workspace-level agent skill files. Agents working in this repo have no
project-specific workflows to follow for common tasks (e.g., adding a strategy,
adding a broker, running the ML pipeline).

### 4. `AGENTS.md` lacked task-specific workflows
The newly created `AGENTS.md` covers orientation and conventions but does not
include step-by-step workflows for the most common agent tasks.

### 5. `DEPLOYMENT.md` version mismatch
`DEPLOYMENT.md` states "Python 3.12 required" but `devcontainer.json` and
`pyproject.toml` use Python 3.10. This will mislead agents setting up
production environments.

### 6. No `CONTRIBUTING.md`
No document describes the branching strategy, commit message format, or review
process. Agents cannot follow project conventions they are not told about.

### 7. `ruff.toml` has excessive ignore list
Over 60 rules are suppressed globally. Many suppressions (e.g., `S105`, `S106`,
`S108`, `S110`, `S112` — hardcoded password/temp file checks) are security-
relevant and should be scoped to `tests/` only, not silently ignored everywhere.

### 8. No documented test coverage target
`pytest.ini` and `.coveragerc` exist but no minimum coverage threshold is
enforced in CI. Agents adding code have no signal about whether their changes
are adequately tested.

### 9. ML model facts are split across two files
`ARCHITECTURE.md` and `README.md` both document ML model metrics, but with
different numbers (README shows 56.5% OOS accuracy; ARCHITECTURE.md shows
`null` OOS accuracy with a note about retraining). This inconsistency will
confuse agents reasoning about model quality.

### 10. No `WORDMAP.json` documentation
`WORDMAP.json` is gitignored (correctly) but there is no documentation on how
to obtain or regenerate it. Agents setting up a fresh environment will hit
import errors from `nuclear/` without knowing why.

---

## What's Wrong

### 1. Python version inconsistency (blocking)
- `devcontainer.json`: `python:3.10-bullseye`
- `pyproject.toml`: `requires-python = ">=3.10"`
- `DEPLOYMENT.md`: "Python 3.12 required (matches `python:3.12-slim`)"
- `Dockerfile`: needs verification

This is a concrete correctness bug. An agent following `DEPLOYMENT.md` will
build a Python 3.12 production image that may fail to load `advanced_oos.pkl`
(serialised on Python 3.10).

### 2. `ruff.toml` suppresses security rules globally
`S105` (hardcoded password), `S106` (hardcoded password in function call),
`S108` (probable insecure temp file), `S110` (try/except/pass), `S112`
(try/except/continue) are suppressed at the top-level `ignore` list, not just
in `tests/`. This means security-relevant patterns in production code are
silently ignored.

### 3. `DEPLOYMENT.md` is stale
References v1.17 but the codebase is at v11.0.0 (per `pyproject.toml`). The
version numbering scheme changed and the deployment guide was not updated.

### 4. `README.md` OOS accuracy figures conflict with `ARCHITECTURE.md`
README header table: "56.5% OOS accuracy, N=2,016 bars, 2017–2026 OOS period"
ARCHITECTURE.md: "OOS accuracy: null — trained with `--years 2 --oos-years 0`"
One of these is wrong. An agent reasoning about model quality will get
contradictory information depending on which file it reads first.

### 5. `WORDMAP.json.example` exists but `WORDMAP.json` is gitignored with no
   generation instructions
The nuclear strategy system depends on `WORDMAP.json`. The example file exists
but there is no `scripts/generate_wordmap.py` or documentation on how to
produce the real file. A fresh environment will fail silently.

---

## Improvement Plan

### Priority 1 — Correctness (fix before next agent session)

**1.1 Resolve Python version inconsistency**
- Verify `Dockerfile` base image version
- Update `DEPLOYMENT.md` to match `devcontainer.json` (Python 3.10)
- Or update `devcontainer.json` to match `Dockerfile` — pick one and document
  the decision in `ARCHITECTURE.md`

**1.2 Reconcile ML model accuracy figures**
- Determine which number is current: README's 56.5% or ARCHITECTURE.md's null
- Update the stale file to match, with a note on when the figure was last
  verified
- Add a single source-of-truth pointer: "For current model metrics, see
  `ml/saved_models/advanced_oos_meta.json`"

**1.3 Scope security rule suppressions in `ruff.toml`**
- Remove `S105`, `S106`, `S108`, `S110`, `S112` from the global `ignore` list
- Add them only to `tests/**` and `scripts/**` per-file-ignores where they are
  genuinely acceptable

### Priority 2 — Agent Guidance (add in next iteration)

**2.1 Add PR template**

Create `.github/PULL_REQUEST_TEMPLATE.md`:
```markdown
## What
<!-- One sentence: what does this PR change? -->

## Why
<!-- Motivation: what problem does it solve or what feature does it add? -->

## How
<!-- Non-obvious implementation decisions only. Skip if straightforward. -->

## Test plan
<!-- How was this tested? Which test markers cover it? -->

## Checklist
- [ ] `ruff check .` passes
- [ ] `mypy` passes on changed modules
- [ ] Tests added or updated
- [ ] `ARCHITECTURE.md` updated if module map changed
- [ ] `AGENTS.md` updated if conventions changed
```

**2.2 Add `CONTRIBUTING.md`**

Document:
- Branch naming: `feature/`, `fix/`, `chore/` prefixes
- Commit message format (imperative mood, ≤72 chars subject)
- PR review requirements
- How to run the full CI check locally before pushing

**2.3 Add `WORDMAP.json` generation instructions**

Add a section to `ARCHITECTURE.md` or `docs/` explaining:
- What `WORDMAP.json` is (nuclear strategy semantic scorer)
- How to generate it from `WORDMAP.json.example`
- Or add `scripts/generate_wordmap.py` with a stub that creates a usable
  development version

**2.4 Add coverage enforcement to CI**

In `tests.yml`, add a `--cov-fail-under=70` flag (or whatever the current
baseline is). This gives agents a concrete signal when their changes reduce
coverage.

**2.5 Expand `AGENTS.md` with task workflows**

Add a "Common Agent Workflows" section with step-by-step instructions for:
- Adding a new API endpoint (including plan-gating)
- Adding a new strategy (canonical directory, registration, backtest)
- Adding a new broker (base class, router wiring, mock test)
- Running ML training and updating model facts
- Debugging a failing CI workflow

### Priority 3 — Quality of Life

**3.1 Update `DEPLOYMENT.md` version number**
Change "v1.17" to match `pyproject.toml` version (currently 11.0.0) and
update the Python version requirement.

**3.2 Add `.ona/skills/` workspace skills**

Create skill files for the two most common agent tasks:
- `.ona/skills/add-strategy.md` — workflow for adding a backtestable strategy
- `.ona/skills/run-ml-pipeline.md` — workflow for training and evaluating models

**3.3 Consolidate duplicate test configuration**

`pytest.ini`, `pytest_configuration.ini`, and `setup.cfg` all contain pytest
config. Consolidate into `pytest.ini` only and delete the others to avoid
agents reading stale config.

---

## Summary Table

| Issue | Severity | Effort | Priority |
|-------|----------|--------|----------|
| Python version inconsistency | High | Low | 1 |
| ML accuracy figures conflict | High | Low | 1 |
| Security rules suppressed globally | Medium | Low | 1 |
| No PR template | Medium | Low | 2 |
| No `CONTRIBUTING.md` | Medium | Low | 2 |
| No WORDMAP generation docs | Medium | Medium | 2 |
| No coverage enforcement | Low | Low | 2 |
| `AGENTS.md` missing task workflows | Medium | Medium | 2 |
| `DEPLOYMENT.md` stale version | Low | Low | 3 |
| No `.ona/skills/` files | Low | Medium | 3 |
| Duplicate pytest config files | Low | Low | 3 |
