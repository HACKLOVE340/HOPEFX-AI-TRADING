# Phase C — Controls That Report Success Without Acting

> **For agentic workers:** implement task-by-task. Each task ends with an
> independently testable deliverable and a commit.

**Goal:** Stop six controls reporting success for work they did not do.

**Architecture:** No new subsystems. Each fix makes an existing component
report what actually happened — either by doing the work it claimed, or by
saying plainly that it did not. Where a control cannot be made real cheaply, it
is made *honest* and the gap is named, never left green.

**Findings:** F176, F214, F215, F219, F160, F159. Full text in
`docs/audit/CODE_READING_FINDINGS.md`.

## Global Constraints

- **Never weaken a risk gate, kill switch, or staleness/drift check.** Every
  task adds refusals or accuracy; none removes a check.
- A control that cannot verify itself must report **unknown**, never **ok**.
  "Degraded" and "unverified" are honest; green is not.
- `ruff check .` clean and all 15 pre-commit hooks pass before each commit.
- Verify in a fresh worktree **with `static/` copied in** (F244).
- Branch `claude/add-new-skills-lys862`. No PR unless asked.

## Ordering

F215 first — it is a one-line config change that stops every fresh deployment
enabling an ungated experimental feature, and it is the precondition F214 then
enforces in code. F159 last: it is the largest, and the others are independent
of it.

| Task | Finding | Severity | Shape |
|---|---|---|---|
| 1 | F215 | HIGH | `.env.example` contradicts a deliberate code default |
| 2 | F214 | HIGH | A gate is computed and gates nothing |
| 3 | F219 | HIGH | Returns `True` for a no-op |
| 4 | F160 | MEDIUM | Reports `ok` from an env var |
| 5 | F176 | CRITICAL | Reports `FULL COVERAGE ✅` from hardcoded literals |
| 6 | F159 | CRITICAL | Critical alerts never leave the log |

---

### Task 1 — F215: stop shipping an ungated experimental flag enabled

`.env.example:830` and `.env:830` set `FEATURE_ONLINE_LEARNING=true`. Its
`_FeatureDef` default is `False`, and its own description says
*"Enable with FEATURE_ONLINE_LEARNING=true after gate passes."*
`scripts/bootstrap_dev.py` generates `.env` from the template, so every
developer and every fresh deployment starts in the state the flag forbids.

Audited: five other EXPERIMENTAL flags are enabled in the template and all five
have `default=True` in code. This is the only one that overrides a deliberate
`False`.

- [ ] Test: every `FEATURE_*` in `.env.example` matches its `_FeatureDef` default,
      or is listed in an explicit exceptions map with a written reason.
- [ ] Set `FEATURE_ONLINE_LEARNING=false` in `.env.example` and `.env`.
- [ ] Commit.

### Task 2 — F214: make the phase gate gate something

`phase3_ready()` is called once, at `ml/inference_engine.py:1558`, and its
result goes into a health dict. `core/signal_engine.py:280
_get_online_learner_store()` — the function that decides whether the online
learner blends into live signals — reads the flag and never consults the gate.

- [ ] Test: with the flag on and the gate unmet, the store is not returned.
- [ ] Test: with the flag on and the gate met, it is.
- [ ] Test: a gate that raises fails closed (feature stays off).
- [ ] Test: the refusal names the gate's reason, so an operator can act on it.
- [ ] Implement in `_get_online_learner_store`.
- [ ] Commit.

### Task 3 — F219: stop returning True for a notification nobody received

`mobile/push_notifications.py:173` returns `True` when FCM is disabled or the
user has no tokens. All three Firebase variables are blank in `.env.example`, so
this is the default state. Callers at `api/trading.py:780` and
`api/signals.py:456` receive `True` and cannot tell.

- [ ] Test: FCM disabled → falsy result, and the caller can see why.
- [ ] Test: no device tokens → falsy result.
- [ ] Test: a real send still reports success.
- [ ] Test: the log line is kept — dev observability was the reason for the branch.
- [ ] Implement, keeping the return type callers already handle.
- [ ] Commit.

### Task 4 — F160: a health probe that contacted nothing must not say ok

`infrastructure/health_engine.py:276` falls through to an env-var read when
Redis is unreachable and returns `status: "ok"` for `BROKER_TYPE=paper`. The
`detail` string says "(config only)" and is honest, but `ok_count` and
`_STATUS_RANK` aggregate on `status`, so every rollup and badge shows green.

- [ ] Test: with no Redis, the status is not `ok` regardless of `BROKER_TYPE`.
- [ ] Test: with Redis reporting connected, the status is `ok`.
- [ ] Test: with Redis reporting disconnected, the status is not `ok`.
- [ ] Implement: unreachable Redis → `unknown`/`degraded`, detail unchanged.
- [ ] Commit.

### Task 5 — F176: a scorecard that cannot fail is not a scorecard

`CRITICAL_COMPONENTS` is 12 hand-typed dicts of `True`. `coverage_counts()`
counts how many say `True`. It inspects no code, calls no predicate, probes
nothing — so `scripts/invariant_coverage.py` prints `FULL COVERAGE ✅` and
cannot print anything else.

Real probes for twelve components are a project. The honest interim is to stop
the report claiming verification it has not performed.

- [x] Test: the report never prints `FULL COVERAGE` from declarations alone.
- [x] Test: the output states these are declarations, not measurements.
- [x] Test: `coverage_counts()` still returns the declared counts — the manifest
      is a legitimate statement of intent; only the *claim* was false.
- [x] Implement: rename the reported dimension to DECLARED, and print an explicit
      "not verified by probe" line naming which components have real coverage
      checks and which do not (`PROBED_COMPONENTS` — currently empty, and the
      report says so).
- [x] Commit.

### Task 6 — F159: critical alerts must leave the process

`AlertEngine.send_alert` delegates to `get_alert_engine()` only when the
singleton `is not self`. `notifications/__init__.py` re-exports
`get_alert_engine` from `notifications.alert_engine`, which returns the
`AlertEngine` singleton — so the guard and the delivery are the same branch and
the delegation never fires. Emergency stops and drawdown breaches reach the log
and stop there.

- [x] Test: `send_alert` on the singleton reaches a configured channel.
- [x] Test: it does not recurse when no separate manager exists.
- [x] Test: a delivery failure is reported, not swallowed.
- [x] Test: with no channel configured at all, the result says so rather than
      claiming delivery.
- [x] Implement: resolve the NotificationManager explicitly rather than by
      identity comparison against a function that returns self.
- [x] Commit.


**Done.** Task 5: `scripts/invariant_coverage.py` separates a MEASURED registry
section (introspection, real) from a DECLARED matrix (the manifest), prints the
not-verified notice and the probe list, and no longer prints `FULL COVERAGE`.
`main()` now takes `argv` — reading `sys.argv` meant the test harness parsed
pytest's own arguments, exited 2, and handed three assertions an empty string to
pass against.

Task 6 grew: F159's guard was one of five defects on the same path. Fixing only
the guard would have left `notifications.send_alert()` a bare `logger.log`
(F247), three call sites raising swallowed `TypeError`s (F248), an advertised
email channel nothing dispatches (F249), and a superadmin test-alert button
reporting delivery on channels it never reached (F250). All five are fixed; see
`CODE_READING_FINDINGS.md`.

### Task 7 — Verify

- [ ] Fresh worktree, `static/` copied in, full fast suite, failure set diffed
      against baseline.
- [ ] Update `CODE_READING_FINDINGS.md` and `FIX_PHASES.md`.
- [ ] Push.
