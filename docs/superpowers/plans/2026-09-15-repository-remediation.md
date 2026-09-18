# HOPEFX Repository Remediation Plan

> **For agentic workers:** Execute this plan task-by-task with failing-first tests, focused commits, and fresh verification evidence. Do not bypass hooks or weaken safety controls.

**Goal:** Reduce the repository’s measured correctness, safety, documentation, dependency, and operational debt to zero where it is mechanically fixable, while surfacing owner decisions instead of guessing.

**Architecture:** Work in small, reviewable batches on the current feature branch. Each batch starts from a measured finding, adds a regression test or executable proof, applies the smallest coherent fix, updates authoritative documentation when measurements change, and runs the applicable repository gates. Safety-critical and developer-workflow defects precede product polish.

**Tech Stack:** Python 3.12, FastAPI, pytest, mypy, Ruff, pre-commit, React/Vite, GitHub Actions, PostgreSQL/Redis, committed ML artifacts.

**Spec:** `AGENTS.md`, `CLAUDE.md`, `ARCHITECTURE.md`, `docs/ai/specs/GROUP4_CONSTITUTION.md`, `docs/ai/MASTER_OUTSTANDING.md`, and the measured output of `scripts/backlog_report.py`.

## Global Constraints

- A control that cannot fail is not a control; every new safety control requires defect-injection evidence.
- An unmeasured value is absent, never zero.
- Fail closed on anything that spends, trades, exposes, authorizes, or handles sensitive data.
- Never weaken a risk gate, kill switch, model-staleness check, drift check, or authorization boundary to make tests pass.
- Every behavioral fix ships with a regression test that failed before the fix.
- Documentation ships with every push; update every authoritative document made stale by a change.
- Use canonical directories only: `backtesting/`, `strategies/`, `data_layer/`, and `api/ws_live.py` for their respective domains.
- Do not commit secrets, real credentials, generated model changes unrelated to the task, or bypass hooks with `--no-verify`.
- Live broker activation, real-money trading, production deployment, destructive actions, and owner decisions remain stop conditions.

## Current Baseline — 2026-09-15

- Branch: `claude/add-new-skills-lys862`.
- Capability registry: 233/233 evidence entries resolve; 0 discrepancies.
- Gate evidence: 36/36 gates proven able to fail; 0 unproven.
- Caller screen: 153 rows screened; 33 flagged for inspection. This is a triage screen, not a verdict.
- Documentation registry: 252 documents; 197 unowned baseline entries.
- Documentation freshness: 36 stale references in living documents.
- Constitutional invariants: 21 recorded; 11 not yet `AVAILABLE`.
- Group 4 source preservation: 304 titles checked; 0 missing.
- Known static typing failure: 3 errors in `invariants/constitution.py` under the documented mypy command.
- Known infrastructure limitation: full-repository per-module coverage pre-commit hook is prohibitively long and previously terminated with exit 137; it must be optimized or bounded as its own work item, not silently skipped.
- Known external dependency exposure: GitHub reported 29 Dependabot vulnerabilities on the default branch; dependency remediation requires package-by-package verification and compatibility tests.

## Verified Follow-up Findings — 2026-09-16

- Frontend production build: fixed the Tailwind scanner regression caused by a
  dynamic class-shaped test assertion. The focused shell test, full Vitest
  suite, TypeScript check, and production build now pass; the change is tracked
  by issue #323 and pull request #325.
- Mypy bootstrap: corrected the invalid bare `type: ignore` in the Redis tick
  writer fixture and aligned the mypy language target with the documented
  Python 3.12 runtime so NumPy's current stubs parse correctly. A repository-
  wide run now reaches project code and reports the larger pre-existing
  annotation backlog; those errors remain separate remediation items and are
  not suppressed by this batch.

## Ordered Workstreams

### Workstream 1 — Developer and governance gates

1. Fix direct-script importability for all documented repository scripts, with one subprocess regression test per affected command.
2. Fix the three `mypy` errors in `invariants/constitution.py` with tests covering missing and present numeric values; preserve fail-closed semantics.
3. Make `docs_freshness.py` report stale references with actionable file/line evidence, then classify the 36 baseline findings into mechanical fixes versus owner decisions.
4. Bound or redesign the per-module coverage hook so it provides useful incremental proof without multi-hour unbounded execution. Preserve the ≥80% policy; change only orchestration and evidence collection.
5. Add a fast, project-owned verification command for the exact changed-file gate set, while retaining the full CI gate.

### Workstream 2 — Trading safety and model integrity

1. Resolve the stale production model decision through retraining/registration or an owner-approved policy change; do not weaken `STALE_MODEL_BLOCK`.
2. Complete the model provenance audit so every committed artifact has an integrity record and every loader reaches an integrity check.
3. Measure and repair any drift-guard false positives caused by missing data versus genuine feature drift.
4. Characterize or remove the duplicate paper-trading engine only after differential tests prove the selected behavior.
5. Verify every risk, kill-switch, execution, idempotency, and reconciliation control by execution and injection tests.

### Workstream 3 — Data, persistence, and recovery

1. Finish the owner’s RPO/RTO decision record before implementing PITR or changing backup schedules.
2. Verify migration coverage for every ORM table and repair missing migrations.
3. Exercise database restore, cross-object denial, wrong-role denial, and backup integrity in isolated environments.
4. Add bounded resource and timeout behavior to streaming and external-feed paths where measured.

### Workstream 4 — API, security, and dependencies

1. Inventory the 29 Dependabot findings and group upgrades by compatibility boundary; never bulk-upgrade without tests.
2. Run backend security scans and fix high-severity findings first.
3. Verify mutating-route authentication, object ownership, tenant isolation, replay protection, and error redaction.
4. Resolve or explicitly document known broken imports tracked by the repository baseline.

### Workstream 5 — Frontend and product debt

1. Finish the remaining standard-shell migration only where not owner-deliberately exempted.
2. Reduce colour, size, spacing, and emoji debt via proven codemods and ratchets; do not round visual values without an explicit design decision.
3. Keep live-data reachability and chart-time correctness measured; do not fabricate missing market data.
4. Run frontend typecheck, lint, tests, and accessibility checks after each focused batch.

### Workstream 6 — Documentation and ownership

1. Reduce unowned documents from the 197-entry baseline by assigning owners only where ownership is known.
2. Repair stale references that point to missing files or obsolete commands.
3. Keep `AGENTS.md`, `CLAUDE.md`, `ARCHITECTURE.md`, `CONTRIBUTING.md`, `README.md`, the registry, and generated reports synchronized.
4. Archive superseded historical documents only through the repository’s document-governance rules.

## Execution Protocol for Every Batch

1. Measure the finding with the repository script or a reproducible command.
2. Trace the root cause and identify the affected flow and regression surface.
3. Write a minimal regression test or executable injection proof.
4. Run the new test against the pre-fix tree and record the expected failure.
5. Implement the smallest safe fix.
6. Run the focused tests, lint, type checks, security checks, and applicable pre-commit hooks.
7. Update authoritative documents and generated metrics if the measured state changes.
8. Inspect the diff for unrelated generated artifacts, secrets, model changes, and conflict markers.
9. Commit one coherent batch with an imperative message and push only after fresh verification.
10. Re-run `PYTHONPATH=. python scripts/backlog_report.py`, `python scripts/gate_evidence.py`, and the relevant ratchets; record remaining failures honestly.

## Stop Conditions

Stop and request owner input when a fix changes trading policy, model freshness policy, RPO/RTO, dependency compatibility with material runtime impact, public API contracts, live-broker behavior, production deployment, permissions, or destructive data handling. Do not convert an owner decision into an engineering default.

## First Active Batch

The first post-plan batch is the `mypy` failure in `invariants/constitution.py`:

- Read the invariant implementation and adjacent tests.
- Identify why optional numeric values reach comparisons and arithmetic.
- Add failing tests for the missing-value path and valid-value path.
- Implement a fail-closed type-safe fix.
- Run the invariant tests, the documented mypy command, Ruff, pre-commit scoped hooks, and the backlog/gate reports.
- Commit and push only if all applicable checks pass.
