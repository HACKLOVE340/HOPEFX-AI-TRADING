# Phase D — AI Core prerequisites · DONE

**Goal:** close the three controls that must hold before AI Core work begins,
because an autonomous component inherits every one of them.

**Spec:** `docs/audit/CODE_READING_FINDINGS.md` (F139, F130, F184)

| # | Finding | Sev | Outcome |
|---|---------|-----|---------|
| 1 | F139 | CRITICAL | Both manifest sets now grant the kill switch all five layers |
| 2 | F130 | HIGH | The patch queue fails closed and is configurable |
| 3 | F184 | MEDIUM | "Could not run tests" is no longer "tests passed" |

### Task 1 — F139: the kill switch loses three of five layers on one manifest set

- [x] Test: both shipped sets ship the kill-switch ConfigMap.
- [x] Test: both grant get+patch on it, scoped by `resourceNames`, no wildcards.
- [x] Test: each Deployment names a ServiceAccount that a RoleBinding binds.
- [x] Test: the flag file lives on a volume when the root filesystem is read-only.
- [x] Test: `KILL_SWITCH_FLAG_FILE` actually relocates the flag.
- [x] Test: an unwritable flag is reported at ERROR, and activation still succeeds.
- [x] Implement: `deployments/k8s/kill-switch-rbac.yaml`,
      `deployments/k8s/kill-switch-configmap.yaml`, `serviceAccountName`, a
      `/app/state` volume on both sets, `KILL_SWITCH_FLAG_FILE` in the code.
- [x] Commit.

**Found while doing it:** layer 2 was worse than filed. The audit recorded "does
not survive a pod replacement"; in fact both deployments run
`readOnlyRootFilesystem: true` with no volume covering `/app`, so the write
raised `OSError` into a WARNING handler and the file layer never worked at all.
There was also no environment override, so nothing could move it.

### Task 2 — F130: the patch queue accepts anything

- [x] Test: with no key, a patch is rejected and the refusal is logged at ERROR.
- [x] Test: a correctly signed patch is accepted; a tampered one is not.
- [x] Test: running unsigned requires an explicit opt-in, logged loudly.
- [x] Test: the opt-in cannot bypass a key that IS set.
- [x] Test: the key is reachable from shipped configuration.
- [x] Implement: fail closed; `HEAL_ALLOW_UNSIGNED_PATCHES` as the deliberate
      development escape; both env examples document the key and how to make one.
- [x] Commit.

### Task 3 — F184: "could not run tests" counted as "tests passed"

- [x] Test: a test run that cannot start returns False.
- [x] Implement: return False and log at ERROR, matching the timeout branch.
- [x] Commit.

### Task 4 — Verify

- [ ] Fresh worktree with `static/`, full fast suite, failure set diffed.
- [ ] Update `CODE_READING_FINDINGS.md` and `FIX_PHASES.md`; push.
