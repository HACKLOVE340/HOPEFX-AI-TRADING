# HOPEFX — Correction Register

**The single list of what is left to fix.** One entry per finding, each with the
fix, the test to write first, and the command that proves it. If you are picking
up this programme, start here and nowhere else.

> **Status is measured, not remembered.** Every entry below is probed against the
> code by `scripts/correction_register.py` and regenerated from that probe. Where
> this document and the script disagree, the script is right — that is the
> repository's standing rule, and `pre-commit` enforces it here.

```bash
python scripts/correction_register.py            # status of everything, now
python scripts/correction_register.py --id A8    # one finding, in full
python scripts/correction_register.py --check    # what pre-commit runs
python scripts/correction_register.py --markdown # regenerate §3 below
```

---

## 1. Why this file exists

The outstanding work was spread across fifteen documents totalling about 29,000
lines: `docs/audit/REMEDIATION_PLAN.md` (80 open checkboxes), five plans under
`docs/audit/plans/`, and three prose registers — `CODE_READING_FINDINGS.md`
(9,203 lines), `HARDENING_BACKLOG.md` (7,806) and
`docs/ai/MASTER_OUTSTANDING.md` (6,359). Nothing was wrong with any of them
individually. Together they had no answer to "what do I do next".

**This file does not replace them.** They hold the evidence: how each defect was
found, what was measured, what was ruled out. That reasoning is worth keeping and
is not reproduced here. This file holds the *work*, and points at them.

### What it deliberately is not

A copy of those 80 open checkboxes. Measured on 2026-09-13, **half of them
describe work that is already done** — F135's wallet id carries a `uuid4` suffix,
F137's `amount_crypto` is `Numeric(28, 8)`, F139's kill-switch RBAC exists in both
k8s trees, F142's `FIXRouter` takes an injected `OrderGate`, F176 prints
`DECLARED` instead of `FULL COVERAGE ✅`. Copying them forward would have broken
the audit plan's own Phase 11 rule — *no previously fixed defect is re-reported as
open without evidence of regression* — and would have cost the reader their first
hour on work that does not exist.

That is why each entry carries a probe rather than a checkbox. A checkbox records
what someone believed when they typed it. A probe records what the code says when
you ask.

---

## 2. How to work an item

Do not skip to the fix. This sequence is the repository's correction protocol,
and every step of it has caught something here at least once.

1. **Read the full evidence first.** The `Full evidence` line points at the
   document that explains *why*. A fix built from this summary alone will be the
   wrong fix about a third of the time — several findings here were revised once
   someone read the original.
2. **Reproduce it.** `python scripts/correction_register.py --id <ID>` prints
   what the probe currently sees. Prove by execution, never by reading: nine of
   the defects in this repository read as correct.
3. **Write the test named in `Write this test first`, and run it RED.** Watch it
   fail, and check it fails *for the stated reason* — a test that errors on a
   fixture signature is not a red. `git stash` the fix and re-run if you need to
   be sure.
4. **Make the smallest change that turns it green.** No adjacent refactor.
5. **Expect neighbouring tests to turn red, and read them before you "fix" them.**
   Three suites in this repository encoded a defect as the requirement. If a test
   goes red under your fix, the question is not how to make it pass — it is
   whether the behaviour it asserts is one anybody would want.
6. **Run the gates.** `ruff check .`, `pre-commit run --files <changed>`, the
   affected test files, and `python scripts/correction_register.py --check`.
7. **Update the documents your change made stale**, in the same commit. If you
   changed what a gate measures, run the script and fix every document stating
   its figure.

### Two rules that are not negotiable

- **Never weaken a risk gate, kill switch, or staleness/drift check** to make a
  test pass. Widening a reconciliation tolerance to silence a failure is the same
  offence. If a check needs a bigger epsilon, it is reporting a real defect.
- **Every fix ships with a test that fails on the pre-fix tree.** A test that has
  never failed proves nothing.

### Priorities

| | Meaning |
|---|---|
| **P0** | Capital loss, data loss or corruption, auth bypass, a safety gate that cannot refuse |
| **P1** | Normal-path failure, or a control that silently does not run |
| **P2** | Correctness or consistency with bounded blast radius |
| **P3** | Minor UX, naming, cosmetic |
| **OWNER** | Not engineering's to decide — see §4 |

### Statuses

| | Meaning |
|---|---|
| **OPEN** | The probe still finds the defect |
| **PARTIAL** | The harm is contained but the capability is absent — read the entry, the remainder is usually a feature |
| **OWNER** | Blocked on a decision only the owner can make |
| **UNVERIFIED** | Cannot honestly be called open or fixed with the evidence available |
| **FIXED** | The probe confirms it is gone. Kept, not deleted — a register that forgets what it closed invites the same defect back |

---

## 3. The register

<!-- generated by scripts/correction_register.py — do not hand-edit this block -->
**27 tracked · OPEN 9 · PARTIAL 2 · OWNER 3 · UNVERIFIED 0 · FIXED 13**

### OPEN — 9

#### A8 · Two committed model artifacts fail the integrity baseline that gates their load

- **Priority** P0 · **Area** ML
- **Measured now** 2 of 12 artifacts fail their recorded sha256 (feature_scaler.pkl, stacking_ensemble.pkl); 1 listed but absent (lstm_signal.pt). ml/__init__.py::_verify_checksum reads this file on every load and refuses in production, so each mismatch is a refused load
- **Fix** `feature_scaler.pkl` and `stacking_ensemble.pkl` do not match the sha256 recorded in `ml/saved_models/model_checksums.json`. That file is not decorative: `ml/__init__.py::_verify_checksum` reads it on every load and, in production, returns False rather than bootstrapping — so `_try_load` returns None and the artifact is simply absent to the caller. Two consequences to fix together. (a) Establish which side is wrong — the recorded hash or the committed bytes — before regenerating anything; regenerating first destroys the only evidence, and the manifest has one commit in its whole history and already carried three mismatches at that commit, so it has never been correct. (b) `_try_load` returns None identically for 'file absent' and 'integrity refused'. A caller cannot tell a tampered artifact from an uninstalled one, and `ml/advanced_predictor.py:1004` then guards `if self._meta_scaler is not None`, so a refused scaler means unscaled meta-input rather than a refusal to predict. Make the two outcomes distinguishable.
- **Write this test first** An injection test: corrupt one committed artifact and assert the load is refused AND that the caller can tell refusal from absence — the second half is the part no current test covers.
- **Verify** `python scripts/correction_register.py --id A8`
- **Skills** `hopefx-dead-controls`
- **Full evidence** docs/ai/MASTER_OUTSTANDING.md §A8

#### F178/F98 · Two ConfigMaps named `hopefx-config` with contradictory safety values

- **Priority** P0 · **Area** Config
- **Measured now** contradictory values across ConfigMaps: [('deployments/k8s/configmap.yaml', 'monitor'), ('k8s/k8s-configmap.yaml', 'enforce')]
- **Fix** `k8s/` says `HOPEFX_INVARIANT_MODE=enforce`; `deployments/k8s/` says `monitor`. Both objects carry the same name, so which one is live depends on apply order. Decide which tree deploys, delete or rename the other, and add a test that fails on two ConfigMaps sharing a name.
- **Write this test first** A manifest test asserting no two ConfigMaps share `metadata.name`, and that `HOPEFX_INVARIANT_MODE` is `enforce` wherever `BROKER_TYPE != paper`.
- **Verify** `python scripts/correction_register.py --id F178/F98`
- **Skills** `hopefx-invariants`, `test-driven-development`
- **Full evidence** docs/audit/REMEDIATION_PLAN.md — Phase 3

#### F218 · Model tables that exist only via `create_all()` and have no migration

- **Priority** P1 · **Area** Persistence
- **Measured now** 36 of 44 tables have no migration: account_snapshots, accounts, ai_department_memory, ai_signals, aml_alerts, api_keys
- **Fix** `create_all()` never ALTERs, so these tables drift silently between a fresh install and an upgraded one. Add the missing migrations, then a CI check comparing `__tablename__`s against the migration history.
- **Write this test first** The CI check itself is the test: assert every `__tablename__` appears in `alembic/versions/`, and watch it fail with one removed.
- **Verify** `python scripts/correction_register.py --id F218`
- **Skills** `test-driven-development`
- **Full evidence** docs/audit/REMEDIATION_PLAN.md — Phase 4

#### F96 · `deploy.yml` fires on every push to `main` with no CI gate

- **Priority** P1 · **Area** CI
- **Measured now** deploy.yml has no `needs:` and no `workflow_run:` — it fires on push regardless of CI
- **Fix** Add `needs:` on the CI job, or convert the trigger to `workflow_run` completed+success. A deploy that cannot observe a red build is not gated.
- **Write this test first** A workflow-lint test asserting every deploying workflow declares a dependency on a verification workflow.
- **Verify** `python scripts/correction_register.py --id F96`
- **Skills** `test-driven-development`
- **Full evidence** docs/audit/REMEDIATION_PLAN.md — Phase 0

#### F97 · The only action holding `VPS_SSH_KEY` is float-pinned

- **Priority** P1 · **Area** CI
- **Measured now** 1 unpinned action refs; secret-holding: .github/workflows/deploy.yml: appleboy/ssh-action@v1.2.5
- **Fix** Pin `appleboy/ssh-action` to a 40-character commit SHA. A moving tag on an action that receives a deploy key is a supply-chain hole with a credential behind it.
- **Write this test first** A test that walks `.github/workflows/*.yml` and fails on any `uses:` ref that is not a 40-hex SHA where the step also references a secret.
- **Verify** `python scripts/correction_register.py --id F97`
- **Skills** `test-driven-development`
- **Full evidence** docs/audit/REMEDIATION_PLAN.md — Phase 0

#### ML-LEAK · The smoke retrain leaks committed model artifacts into the working tree

- **Priority** P1 · **Area** ML
- **Measured now** 2 artifact(s) written by the smoke retrain and not restored: calibration_report.json, feature_importances.json
- **Fix** `ml/train_advanced.py` writes eight artifacts into `ml/saved_models/`; the `_SMOKE_OVERWRITES` restore list in `tests/unit/test_ml_training_pipeline.py` names six. The uncovered ones stay dirty after the suite runs and get committed alongside whatever else was in flight. **This is the root cause of A8** — proven, not surmised: `model_checksums.json` has one commit (`334e50f3`), while `feature_scaler.pkl` and `stacking_ensemble.pkl` have three each, and one of the later two is `05efdbab`, a *mobile authentication* fix that carried `feature_scaler.pkl`, `stacking_ensemble.pkl`, `feature_stats.json` and a new `feature_importances.json` for no reason connected to its subject. Fix the list, then add the gate: a commit that changes an artifact under `ml/saved_models/` without regenerating the manifest should not pass.
- **Write this test first** Run the smoke retrain and assert `git status --porcelain ml/saved_models/` is empty afterwards — the assertion the current fixture is missing. Watch it fail with one name removed from the restore list.
- **Verify** `python scripts/correction_register.py --id ML-LEAK`
- **Skills** `hopefx-dead-controls`, `test-driven-development`
- **Full evidence** This session, 2026-09-13 — reproduced by execution

#### F199 · `_SPA_ROUTES` is hand-maintained and disagrees with `App.tsx`

- **Priority** P2 · **Area** Frontend
- **Measured now** core/page_routes.py lists 60; App.tsx declares 89 — hand-maintained
- **Fix** Generate the list from `App.tsx`, or add the direct-`GET`-returns-200 test that found F198 — either removes the hand-maintenance. Prefer the test: it catches the class, not just the drift.
- **Write this test first** The same direct-GET probe as F198.
- **Verify** `python scripts/correction_register.py --id F199`
- **Skills** `ui-ux-pro-max`, `test-driven-development`
- **Full evidence** docs/audit/REMEDIATION_PLAN.md — Phase 6

#### F200 · `/docs` is blank in every deployment

- **Priority** P2 · **Area** Frontend
- **Measured now** /docs loads the Swagger CDN, which the CSP blocks — the page is blank in every deployment
- **Fix** The CSP blocks the Swagger CDN the page loads. Vendor `swagger-ui-dist` and serve it locally rather than widening the CSP.
- **Write this test first** A test asserting `/docs` returns a body referencing a same-origin asset.
- **Verify** `python scripts/correction_register.py --id F200`
- **Skills** `ui-ux-pro-max`
- **Full evidence** docs/audit/REMEDIATION_PLAN.md — Phase 6

#### F175 · Emoji used as UI icons

- **Priority** P3 · **Area** Frontend
- **Measured now** 124 frontend source file(s) still carry emoji
- **Fix** Done for `frontend/src`: no source file carries emoji. `ui-ux-pro-max` forbids emoji as icons; use the SVG set.
- **Write this test first** n/a
- **Verify** `python scripts/correction_register.py --id F175`
- **Skills** `ui-ux-pro-max`
- **Full evidence** docs/audit/REMEDIATION_PLAN.md — Phase 6

### PARTIAL — 2

#### F198 · `/kyc` returns raw JSON 404 on direct navigation

- **Priority** P1 · **Area** Frontend
- **Measured now** the /api/kyc alias exists; the bare /kyc router still shadows the SPA route
- **Fix** `api/kyc.py` mounts a router at the bare `/kyc` prefix, which shadows the SPA route. The correctly-prefixed `/api/kyc` alias already exists, so the fix is to drop the bare mount. KYC is a regulatory gate — a user following a verification email currently gets a JSON error.
- **Write this test first** A direct-`GET` probe asserting every SPA route returns 200 with an HTML content type, not JSON.
- **Verify** `python scripts/correction_register.py --id F198`
- **Skills** `ui-ux-pro-max`, `test-driven-development`
- **Full evidence** docs/audit/REMEDIATION_PLAN.md — Phase 6

#### F61/F107 · `BROKER_TYPE=oanda` cannot place an order

- **Priority** P1 · **Area** Brokers
- **Measured now** the bare alias remains, but a test now forces it to fail loudly rather than at the first live order — building the adapter is a feature, not a fix
- **Fix** Half done, deliberately. `AsyncOANDAConnector = OANDABroker` is still a bare alias with no `place_market_order`, but a test now makes that fail where someone can see it instead of at the first live order. Writing the adapter is a feature and needs a practice venue to test against: `place_order` takes `direction` ('long'/'short') and returns a dict, while the caller passes an `_OrderSide` and expects a `MarketOrderResult`. Guessed wrong, it places the opposite side. Live OANDA is the stated next milestone, so this is the gating item.
- **Write this test first** The existing loud-failure test stays; the adapter needs paper-venue contract tests for side, quantity and result shape before it is wired.
- **Verify** `pytest tests/unit/test_broker_type_oanda_is_not_silently_broken.py -q`
- **Skills** `hopefx-money-precision`, `systematic-debugging`
- **Full evidence** docs/audit/REMEDIATION_PLAN.md — Phase 3

### OWNER — 3

#### A9 · `UNIQUE(client_order_id)` is documented as the duplicate-fill guard and never fires

- **Priority** OWNER · **Area** Money
- **Measured now** UNIQUE(client_order_id) is latent — no production writer populates the column (measured: 500 inserts, 500 NULLs, 0 refusals). The live guard is the intent journal in execution/trade_executor.py.
- **Fix** Make it live (writers persist the id, `IntegrityError` becomes the duplicate signal), drop the constraint, or leave it latent as it now stands. If it is made live, feed it from `trade_executor`'s 64-bit id — never from `execution/oms.py`, whose `str(uuid.uuid4())[:8]` is 32 bits against a globally unique index.
- **Write this test first** Under option 1: a test inserting the same client_order_id twice and asserting the second is refused, not silently accepted.
- **Verify** `python scripts/correction_register.py --id A9`
- **Skills** `hopefx-money-precision`, `hopefx-dead-controls`
- **Full evidence** docs/ai/MASTER_OUTSTANDING.md §A9

#### F95 · GitHub Actions does not run — every gate below is unverified until it does

- **Priority** OWNER · **Area** CI
- **Measured now** account-level; no repository change can clear it
- **Fix** Not fixable from code. Check GitHub → Billing → Actions. Runs end in `startup_failure` with no runner assigned, which is the billing signature.
- **Write this test first** None — this is an account setting, not a behaviour.
- **Verify** `Observe a green `ci.yml` run on a fresh push.`
- **Skills** `verification-before-completion`
- **Full evidence** docs/audit/REMEDIATION_PLAN.md — Phase 0

#### SEC-ROTATE · Rotate the credentials exposed outside the repository

- **Priority** OWNER · **Area** Security
- **Measured now** credential rotation is an account action outside the repository
- **Fix** A Vercel token (`vck_…`) was pasted into a chat session. It was never written to disk or into any commit — verified — but it left the machine, so it must be rotated. The tracked working tree reads as placeholders; `prop_firm_mode.json` and `.env.example` are committed deliberately and must stay placeholder-only.
- **Write this test first** None — this is a credential action, not a behaviour.
- **Verify** `detect-secrets scan (already in pre-commit)`
- **Full evidence** docs/audit/REMEDIATION_PLAN.md — spec item 6; this session

### FIXED — 13

#### F135 · Wallet ledger `transaction_id` collided at one-second resolution

- **Priority** P0 · **Area** Money
- **Measured now** payments/wallet.py:99: return f"TXN-{datetime.now(UTC).strftime('%Y%m%d')}-{uuid.uuid4().hex[:8].upper()}"
- **Fix** Done: the id carries a `uuid4` suffix, so two movements in the same second no longer collide and drop a row.
- **Write this test first** Carried by the wallet ledger tests.
- **Verify** `python scripts/correction_register.py --id F135`
- **Skills** `hopefx-money-precision`
- **Full evidence** docs/audit/REMEDIATION_PLAN.md — Phase 2

#### F138 · `verify_balance_after` was never called — the check that catches F135/F136

- **Priority** P0 · **Area** Invariants
- **Measured now** 2 production caller(s): invariants/enforcement.py:46: verify_balance_after,
- **Fix** Done: the predicate has production callers. An invariant with no call site is not a control, however correct the predicate.
- **Write this test first** An injection test: break the balance arithmetic and watch the invariant refuse.
- **Verify** `python scripts/correction_register.py --id F138`
- **Skills** `hopefx-invariants`, `hopefx-dead-controls`
- **Full evidence** docs/audit/REMEDIATION_PLAN.md — Phase 2

#### F139 · `deployments/k8s/` disabled cross-pod kill-switch propagation

- **Priority** P0 · **Area** Risk
- **Measured now** kill-switch RBAC manifests: deployments/k8s/kill-switch-rbac.yaml, k8s/kill-switch-rbac.yaml
- **Fix** Done: `kill-switch-rbac.yaml` exists in both k8s trees.
- **Write this test first** n/a
- **Verify** `python scripts/correction_register.py --id F139`
- **Skills** `hopefx-dead-controls`
- **Full evidence** docs/audit/REMEDIATION_PLAN.md — Phase 3

#### F142 · The active paper path had no risk layer

- **Priority** P0 · **Area** Risk
- **Measured now** FIXRouter takes an injected OrderGate
- **Fix** Done: `FIXRouter` takes an injected `OrderGate`; production injects the real `RiskManager`, tests inject a stub.
- **Write this test first** Carried by tests/unit/test_order_gate.py.
- **Verify** `python scripts/correction_register.py --id F142`
- **Skills** `hopefx-invariants`, `hopefx-dead-controls`
- **Full evidence** docs/audit/plans/2026-09-04-phase-e-risk-gates.md

#### F176 · `invariant_coverage.py` printed `FULL COVERAGE ✅` from hardcoded booleans

- **Priority** P0 · **Area** Dead controls
- **Measured now** prints DECLARED — the matrix no longer presents itself as a measurement
- **Fix** Done: the report now prints `DECLARED — critical-component matrix (not a measurement)`. The remaining work is the real fix — each dimension resolving to a probe that can fail — which is tracked as its own item, not this one.
- **Write this test first** Already carried by the report's own tests.
- **Verify** `python scripts/invariant_coverage.py`
- **Skills** `hopefx-dead-controls`
- **Full evidence** docs/audit/REMEDIATION_PLAN.md — Phase 1

#### F203 · A sale recorded during a payout was destroyed

- **Priority** P0 · **Area** Money
- **Measured now** balance is decremented under a lock
- **Fix** Done: the balance is decremented rather than zeroed, under an `RLock`.
- **Write this test first** Carried by tests/unit/test_revenue_splits_conserve.py.
- **Verify** `python scripts/correction_register.py --id F203`
- **Skills** `hopefx-money-precision`
- **Full evidence** docs/audit/REMEDIATION_PLAN.md — Phase 2

#### F204 · Payouts marked `PAID` with no transfer

- **Priority** P0 · **Area** Money
- **Measured now** PayoutStatus.SIMULATED exists — a payout with no transfer backend is no longer PAID
- **Fix** Done: `PayoutStatus.SIMULATED` exists, so a cycle with no transfer backend no longer claims money moved.
- **Write this test first** Carried by tests/unit/test_revenue_split_money.py.
- **Verify** `python scripts/correction_register.py --id F204`
- **Skills** `hopefx-money-precision`, `hopefx-dead-controls`
- **Full evidence** docs/audit/REMEDIATION_PLAN.md — Phase 2

#### F208 · Creator balances, sales and payouts existed only in RAM

- **Priority** P0 · **Area** Money
- **Measured now** creator ledger writes through a session factory
- **Fix** Done: the creator ledger writes through a session factory.
- **Write this test first** Carried by the revenue-split money tests.
- **Verify** `python scripts/correction_register.py --id F208`
- **Skills** `hopefx-money-precision`
- **Full evidence** docs/audit/REMEDIATION_PLAN.md — Phase 2

#### F221/F105 · The coverage gate omitted the money path

- **Priority** P0 · **Area** Tests
- **Measured now** no safety module appears in the omit list
- **Fix** Done for the omit list: no safety module is hidden. The wider half of F221 — `[run] source` naming a subset of the application — is tracked by the coverage-floor programme, not closed here.
- **Write this test first** tests/unit/test_coverage_gate_states_its_scope.py::test_the_safety_modules_are_not_omitted
- **Verify** `pytest tests/unit/test_coverage_gate_states_its_scope.py -q`
- **Skills** `hopefx-dead-controls`, `test-driven-development`
- **Full evidence** docs/audit/plans/2026-09-11-coverage-floor-programme.md

#### ROUTER-TO · A fallback broker timeout re-routed and risked a duplicate fill

- **Priority** P0 · **Area** Brokers
- **Measured now** 2 TimeoutError clause(s) — the fallback loop must stop the chain, not re-route
- **Fix** Done: a timeout in the fallback loop stops the chain. A timeout is not a confirmed failure, so the order outcome is unknown and re-routing can place a second live order.
- **Write this test first** tests/unit/test_brokers_smart_router_coverage.py::TestExecuteWithFallback::test_a_fallback_timeout_does_not_place_a_second_order
- **Verify** `pytest tests/unit/test_brokers_smart_router_coverage.py -q`
- **Skills** `hopefx-money-precision`, `hopefx-dead-controls`
- **Full evidence** This session, 2026-09-13 — commit 12bef2bb

#### F137 · `amount_crypto` was a `Float` and could not hold 18-decimal tokens

- **Priority** P1 · **Area** Money
- **Measured now** database/models.py:1144: amount_crypto = Column(Numeric(28, 8), nullable=False)
- **Fix** Done: the column is `Numeric(28, 8)`.
- **Write this test first** n/a
- **Verify** `python scripts/correction_register.py --id F137`
- **Skills** `hopefx-money-precision`
- **Full evidence** docs/audit/REMEDIATION_PLAN.md — Phase 2

#### F222 · `revenue_split.py` had zero tests

- **Priority** P1 · **Area** Tests
- **Measured now** 2 test file(s): tests/unit/test_revenue_split_money.py, tests/unit/test_revenue_splits_conserve.py
- **Fix** Done: two test modules now cover it.
- **Write this test first** n/a
- **Verify** `pytest tests/unit/test_revenue_split_money.py -q`
- **Skills** `test-driven-development`
- **Full evidence** docs/audit/REMEDIATION_PLAN.md — Phase 2

#### FIX-STORE · FIX session continuity on an ephemeral sequence store

- **Priority** P1 · **Area** Brokers
- **Measured now** start() refuses reset_on_logon=False on a $TMPDIR store
- **Fix** Done: `IBKRFIXBridge.start()` refuses `reset_on_logon=False` when `store_path` resolves under `tempfile.gettempdir()`.
- **Write this test first** tests/unit/test_ibkr_fix_bridge.py::TestStart::test_start_refuses_session_continuity_on_an_ephemeral_store
- **Verify** `pytest tests/unit/test_ibkr_fix_bridge.py -q`
- **Skills** `hopefx-fix-bridge`, `hopefx-dead-controls`
- **Full evidence** This session, 2026-09-13 — commit 08df737a


---

## 4. Owner decisions — engineering must not default these

Each of these changes what something *means*, not just what it does. Picking one
silently would be engineering deciding policy. They are listed above with their
measured state; this section says what the choice is.

| | Decision | Why it is yours |
|---|---|---|
| **F95** | GitHub Actions billing | No repository change clears it. Until it is green, every gate in this file is unverified — that is the honest status, not a pessimistic one. |
| **A9** | `UNIQUE(client_order_id)`: make it live, drop it, or leave it latent | Making it live changes the money path's failure mode. Dropping it removes a stated intent. Leaving it latent is defensible and is what the code now says. |
| **SEC-ROTATE** | Rotate the exposed Vercel token | An account action. The token was never written to disk or into a commit — verified — but it left the machine. |
| **F178/F98** | Which k8s tree deploys | Two ConfigMaps share the name `hopefx-config` with contradictory `HOPEFX_INVARIANT_MODE` values, so which is live depends on apply order. Engineering can add the duplicate-name test; only you can say which tree is real. |
| **F61/F107** | Whether to build the OANDA adapter now | Live OANDA is the stated next milestone. The adapter needs a practice venue to test against — guessed at, it can place the opposite side of an intended trade. |

---

## 5. What is not in this file, and where it lives

| Not here | Where | Why |
|---|---|---|
| Why each defect was found, and what was ruled out | `docs/audit/CODE_READING_FINDINGS.md` | 9,203 lines of evidence. Summarising it would lose the reasoning that makes a fix correct. |
| Hardening items S7-xx, S13-xx | `docs/HARDENING_BACKLOG.md` | A separate programme with its own numbering, referenced from the code. |
| Specification capabilities and platform gaps | `python scripts/backlog_report.py` | Already measured, and re-measured on every run. Duplicating its output here would create a second number to keep true. |
| The four backlog groups and the constitution | `docs/ai/BACKLOG_GROUPS.md`, `docs/ai/specs/GROUP4_CONSTITUTION.md` | Constitutional scope, not defect scope. |
| Step-by-step task plans | `docs/audit/plans/` | This file says *what*; those say *how*, in bite-sized steps with their own checkboxes. |
| How the audit is conducted | The owner's Audit & Correction Plan (PDF, 2026-09-12) | Methodology: evidence levels, phases, the standard finding record. This file is its Unified Finding Register deliverable. |

### Findings not yet triaged into this register

`docs/audit/REMEDIATION_PLAN.md` holds roughly fifty further open checkboxes —
mostly P2/P3 frontend and quant items (F119, F120, F125, F145, F80, F123, F147,
F149, F150, F171–F175, F187–F210). They are **not** listed above because each
needs a probe written before its status can be stated honestly, and an unprobed
entry here would be the checkbox problem again in a new file. Add them by writing
a probe in `scripts/correction_register.py` and appending a `Finding(...)`; the
`--check` gate then keeps the count true.

---

## 6. Keeping this file honest

`pre-commit` runs `python scripts/correction_register.py --check`. It fails if
the headline counts in §3 disagree with what the probes measure, or if a tracked
finding is missing from the document.

To prove that gate can actually fail — the standard this repository holds every
control to:

```bash
python scripts/correction_register.py --selftest
```

It writes a deliberately wrong count into this file, confirms `--check` refuses
it, and restores the original. A gate nobody has watched fail is not a gate.
