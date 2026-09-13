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
**72 tracked · OPEN 18 · PARTIAL 7 · OWNER 5 · UNVERIFIED 1 · FIXED 41**

### OPEN — 18

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

#### AI-GATE · Two acceptance tests the AI layer must not ship without

- **Priority** P1 · **Area** AI authority
- **Measured now** acceptance tests present — out-of-scope action: False, execution-without-approval: False. `enforce_agent_action` and `ToolBus.invoke` exist and are called; what is missing is the pair of build-failing tests that keep them that way as the AI layer grows
- **Fix** Adopt both before writing more agent code: an agent calling an action outside its scope must FAIL THE BUILD, and a proposal executing without an approval record must fail the build. `enforce_agent_action` and `ToolBus.invoke` already run outside tests, so this is about keeping them enforced as the layer grows — without these, the spec's approval queue is the same shape as F176: a control described accurately and enforced by convention. Note the inherited prerequisites, each tracked here: the AI kill switch depends on F139 (now fixed), and the agent sandbox on F130 (open — unsigned patches) and F184 (fixed).
- **Write this test first** The two tests are the deliverable. Write them red: grant an agent a narrow scope, call outside it, assert refusal; submit a proposal with no approval record, assert it does not execute.
- **Verify** `python scripts/correction_register.py --id AI-GATE`
- **Skills** `hopefx-dead-controls`, `hopefx-invariants`, `threat-modelling`
- **Full evidence** docs/audit/REMEDIATION_PLAN.md — AI Core section

#### F106 · Nothing tests the TradeExecutor ↔ real-connector join

- **Priority** P1 · **Area** Tests
- **Measured now** TradeExecutor is tested against MagicMock brokers only. A mock with no spec agrees with every call, so the signature mismatch that F61 describes survives the whole suite
- **Fix** `TradeExecutor` is tested against `MagicMock` brokers. A mock with no spec agrees with every call, which is exactly how F61's signature mismatch — `place_order` versus `place_market_order` — survives the whole suite and surfaces at the first live order. Use `create_autospec(RealConnector)` so the mock rejects what the real class would.
- **Write this test first** Re-run the existing executor tests against an autospec of each connector and watch the ones with wrong signatures fail.
- **Verify** `python scripts/correction_register.py --id F106`
- **Skills** `hopefx-dead-controls`, `test-driven-development`
- **Full evidence** docs/audit/REMEDIATION_PLAN.md — Phase 5

#### F123 · `/walk-forward/run` performs no walk-forward analysis

- **Priority** P1 · **Area** Quant
- **Measured now** api/backtesting.py never imports backtesting/walk_forward.py, which already implements this correctly with a purge gap. The endpoint reports results from a procedure that is not walk-forward
- **Fix** `api/backtesting.py` never imports `backtesting/walk_forward.py`, which already implements this correctly with a purge gap. The endpoint returns results labelled walk-forward from a procedure that is not one — the worst kind of backtest defect, because look-ahead leakage shows up as a good number. Delegate to the existing analyser.
- **Write this test first** A leakage test: construct a series where an in-sample-fit strategy scores well and a purged walk-forward does not, and assert the endpoint reports the second.
- **Verify** `python scripts/correction_register.py --id F123`
- **Skills** `backtesting-frameworks`
- **Full evidence** docs/audit/REMEDIATION_PLAN.md — Phase 5

#### F218 · Model tables that exist only via `create_all()` and have no migration

- **Priority** P1 · **Area** Persistence
- **Measured now** 36 of 44 tables have no migration: account_snapshots, accounts, ai_department_memory, ai_signals, aml_alerts, api_keys
- **Fix** `create_all()` never ALTERs, so these tables drift silently between a fresh install and an upgraded one. Add the missing migrations, then a CI check comparing `__tablename__`s against the migration history.
- **Write this test first** The CI check itself is the test: assert every `__tablename__` appears in `alembic/versions/`, and watch it fail with one removed.
- **Verify** `python scripts/correction_register.py --id F218`
- **Skills** `test-driven-development`
- **Full evidence** docs/audit/REMEDIATION_PLAN.md — Phase 4

#### F220 · Device tokens live in a module dict

- **Priority** P1 · **Area** Money
- **Measured now** _device_tokens is a module-level dict with no backing store — a correctly configured FCM stops delivering after a deploy, and each worker holds a different set
- **Fix** `_device_tokens` is a module-level dict with no backing store, so a correctly configured FCM stops delivering after a deploy and each worker holds a different set. This is what makes F219's fix incomplete: the send now reports honestly, and still has nobody to send to.
- **Write this test first** Register a token, simulate a restart by reimporting the module, assert the token is still there.
- **Verify** `python scripts/correction_register.py --id F220`
- **Skills** `hopefx-dead-controls`
- **Full evidence** docs/audit/REMEDIATION_PLAN.md — Phase 6

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

#### F108 · Test files that define tests and assert nothing

- **Priority** P2 · **Area** Tests
- **Measured now** 2 test file(s) define tests and assert nothing: tests/unit/test_backtest.py, tests/unit/test_risk_calculations.py
- **Fix** Two files remain. A test that cannot fail is a measurement that cannot fail — the defining defect of this codebase, in the suite that is supposed to catch it. Give each an assertion or delete it.
- **Write this test first** The probe is the test: assert no unit-test file defines a test without asserting.
- **Verify** `python scripts/correction_register.py --id F108`
- **Skills** `hopefx-dead-controls`, `test-driven-development`
- **Full evidence** docs/audit/REMEDIATION_PLAN.md — Phase 5

#### F173 · `/dashboard` renders no headings

- **Priority** P2 · **Area** Frontend
- **Measured now** frontend/src/pages/Dashboard.tsx renders 0 h1-h3 elements — a screen reader gets no outline
- **Fix** `Dashboard.tsx` renders zero `h1`–`h3` across 1,027 lines, so a screen reader gets no document outline for the product's main page. `/landing` renders 24.
- **Write this test first** A render test asserting the page exposes exactly one `h1` and a sensible heading order.
- **Verify** `python scripts/correction_register.py --id F173`
- **Skills** `ui-ux-pro-max`
- **Full evidence** docs/audit/REMEDIATION_PLAN.md — Phase 6

#### F187 · Dashboard metrics do not drill through

- **Priority** P2 · **Area** Frontend
- **Measured now** frontend/src/pages/Dashboard.tsx has 1 onClick handler(s) — the metrics do not drill through
- **Fix** One `onClick` in the whole page. A dashboard whose numbers cannot be opened is a readout, not an application — and per F185 the endpoints behind them (`/equity-curve`, `/history`, `/depth/{symbol}`, `/microstructure`) already exist. Both halves are built; nothing joins them.
- **Write this test first** For each metric tile, a test asserting a click navigates to the page that explains it.
- **Verify** `python scripts/correction_register.py --id F187`
- **Skills** `ui-ux-pro-max`
- **Full evidence** docs/audit/REMEDIATION_PLAN.md — Phase 6

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

#### AFF-TIER · A level upgrade advances one tier per conversion

- **Priority** P3 · **Area** Money
- **Measured now** check_level_upgrade returns the first qualifying tier above the current one, so an affiliate whose numbers already clear a higher tier is granted the next one up and earns the lower commission rate until the following conversion
- **Fix** `check_level_upgrade` walks the levels above the current one and returns the FIRST that qualifies, so an affiliate whose referral count and revenue already clear a higher tier is granted only the next one up. They earn the lower commission rate until the following conversion triggers another check. Whether tiers should be skippable is a commercial decision rather than a bug, so the behaviour is pinned by a test that says so rather than quietly changed — if the policy changes, that test should fail and be rewritten.
- **Write this test first** tests/unit/test_affiliate_commissions_conserve.py::test_check_level_upgrade_advances_one_tier_per_call pins today's behaviour.
- **Verify** `python scripts/correction_register.py --id AFF-TIER`
- **Skills** `hopefx-money-precision`
- **Full evidence** This session, 2026-09-13 — found while covering affiliate.py

#### F175 · Emoji used as UI icons

- **Priority** P3 · **Area** Frontend
- **Measured now** 124 frontend source file(s) still carry emoji
- **Fix** Done for `frontend/src`: no source file carries emoji. `ui-ux-pro-max` forbids emoji as icons; use the SVG set.
- **Write this test first** n/a
- **Verify** `python scripts/correction_register.py --id F175`
- **Skills** `ui-ux-pro-max`
- **Full evidence** docs/audit/REMEDIATION_PLAN.md — Phase 6

#### F223 · Test files named after the coverage metric

- **Priority** P3 · **Area** Tests
- **Measured now** 39 test file(s) named after the metric rather than the behaviour (was 75) — these hold the highest concentration of assertion-free tests
- **Fix** Down from 75. A file called `*_coverage_boost.py` says what it was written for rather than what it protects, and these hold the highest concentration of assertion-free tests. Rename to the behaviour; where a name already claims one (`..._skips_outside_pod`), assert that behaviour.
- **Write this test first** None — this is a rename. The value is that the next reader can tell what breaking the test would mean.
- **Verify** `python scripts/correction_register.py --id F223`
- **Skills** `test-driven-development`
- **Full evidence** docs/audit/REMEDIATION_PLAN.md — Phase 5

### PARTIAL — 7

#### F31/F32 · Affiliate money state is in memory, and the payout is a TOCTOU

- **Priority** P0 · **Area** Money
- **Measured now** commissions are conserved and serialised — a withdrawal settles exactly what it pays, and both payout paths hold the manager lock across the whole read-modify-write. Persistence is still absent: the ledger is module dicts, so a restart erases what affiliates are owed and each worker holds its own
- **Fix** **Money conservation is fixed** (2026-09-13). Three ways commission left the ledger without being paid, all reproduced before the fix and all now covered by `tests/unit/test_affiliate_commissions_conserve.py`: (1) `request_withdrawal` tested its running total *before* adding each referral, so the one that crossed the requested amount was marked PAID in full — two 60.00 commissions against a 100.00 withdrawal **destroyed 20.00**, deterministically, behind a live endpoint at `api/monetization.py:1542`; (2) a conversion landing between a payout's total and its settlement pass was settled without being in the total — **70.00 destroyed**, F203's shape one module over; (3) two concurrent payout requests each saw the full balance — **300.00 paid against 150.00 earned**. Referrals now carry `commission_paid` so a withdrawal can settle part of one, and both payout paths plus `convert_referral` hold an `RLock` across the whole read-modify-write. **Persistence remains**: the ledger is still module dicts, so a restart erases what affiliates are owed and each worker holds its own. That half needs schema — revenue_split writes through a session factory into ledger tables — and lands in F218 territory, so it is deliberately not bundled here.
- **Write this test first** For the remaining half: credit a commission, rebuild the manager from its store, and assert the balance survived. It will fail today.
- **Verify** `python scripts/correction_register.py --id F31/F32`
- **Skills** `hopefx-money-precision`
- **Full evidence** docs/audit/REMEDIATION_PLAN.md — Phase 2

#### F147 · The order-flow subsystem is mounted and never fed

- **Priority** P1 · **Area** Dead controls
- **Measured now** constructed=True fed=False — 2,791 LOC mounted behind three routers with no tick source, so its endpoints return empty structures that read as 'no imbalance' rather than 'not measured'
- **Fix** 2,791 LOC constructed in `startup_factories.py` and mounted behind three routers, with no tick source attached. Its endpoints return empty structures, which a caller reads as 'no imbalance' rather than 'not measured' — a zero produced from missing measurement, which the audit plan's own decision rules call misleading rather than neutral. Either subscribe it to the tick feed or make its endpoints report unavailability.
- **Write this test first** Assert the endpoint reports 'not measured' with no feed attached, rather than a zero-valued structure.
- **Verify** `python scripts/correction_register.py --id F147`
- **Skills** `hopefx-dead-controls`
- **Full evidence** docs/audit/REMEDIATION_PLAN.md — Phase 5

#### F180/F181/F182/F183 · Two classes named `SecureVault`

- **Priority** P1 · **Area** Security
- **Measured now** 2 classes named SecureVault (1 besides the live one in config/vault.py): security/encryption.py:40: class SecureVault:. Down from three, but a name collision on a credential store is how the wrong one gets imported — `rotate_key()` on the unreferenced copy returns True and destroys every credential
- **Fix** Down from three; `config/vault.py` is the live one and is genuinely good (Argon2id, crash-safe rotation). `security/encryption.py` still defines a second. A name collision on a credential store is how the wrong one gets imported, and the unreferenced copy is dangerous rather than merely redundant: `rotate_key()` returns True and destroys every credential, a random salt when `HOPEFX_SALT` is unset loses everything on restart, and `encrypt()` falls back to base64 while `decrypt()` honours it. Delete it or rename it; do not leave two importable.
- **Write this test first** A test asserting exactly one importable `SecureVault`, and that it is the config/vault.py one.
- **Verify** `python scripts/correction_register.py --id F180/F181/F182/F183`
- **Skills** `hopefx-dead-controls`
- **Full evidence** docs/audit/REMEDIATION_PLAN.md — Phase 3

#### F198 · `/kyc` returns raw JSON 404 on direct navigation

- **Priority** P1 · **Area** Frontend
- **Measured now** the /api/kyc alias exists; the bare /kyc router still shadows the SPA route
- **Fix** `api/kyc.py` mounts a router at the bare `/kyc` prefix, which shadows the SPA route. The correctly-prefixed `/api/kyc` alias already exists, so the fix is to drop the bare mount. KYC is a regulatory gate — a user following a verification email currently gets a JSON error.
- **Write this test first** A direct-`GET` probe asserting every SPA route returns 200 with an HTML content type, not JSON.
- **Verify** `python scripts/correction_register.py --id F198`
- **Skills** `ui-ux-pro-max`, `test-driven-development`
- **Full evidence** docs/audit/REMEDIATION_PLAN.md — Phase 6

#### F206 · `int(amount * 100)` truncates cents against the payee

- **Priority** P1 · **Area** Money
- **Measured now** 2 site(s) still truncate: monetization/stripe_integration.py:297: amount_cents = int(amount * 100) — revenue_split now quantizes ROUND_HALF_UP, so this is the remainder, not the whole finding
- **Fix** `revenue_split.py` now quantizes ROUND_HALF_UP; `monetization/stripe_integration.py` still truncates. Truncation toward zero always takes the same side of the rounding, so the loss accumulates in one direction. Use the same helper.
- **Write this test first** A test asserting 0.999 becomes 100 cents, not 99 — and watch it fail on the truncating call site.
- **Verify** `python scripts/correction_register.py --id F206`
- **Skills** `hopefx-money-precision`
- **Full evidence** docs/audit/REMEDIATION_PLAN.md — Phase 2

#### F61/F107 · `BROKER_TYPE=oanda` cannot place an order

- **Priority** P1 · **Area** Brokers
- **Measured now** the bare alias remains, but a test now forces it to fail loudly rather than at the first live order — building the adapter is a feature, not a fix
- **Fix** Half done, deliberately. `AsyncOANDAConnector = OANDABroker` is still a bare alias with no `place_market_order`, but a test now makes that fail where someone can see it instead of at the first live order. Writing the adapter is a feature and needs a practice venue to test against: `place_order` takes `direction` ('long'/'short') and returns a dict, while the caller passes an `_OrderSide` and expects a `MarketOrderResult`. Guessed wrong, it places the opposite side. Live OANDA is the stated next milestone, so this is the gating item.
- **Write this test first** The existing loud-failure test stays; the adapter needs paper-venue contract tests for side, quantity and result shape before it is wired.
- **Verify** `pytest tests/unit/test_broker_type_oanda_is_not_silently_broken.py -q`
- **Skills** `hopefx-money-precision`, `systematic-debugging`
- **Full evidence** docs/audit/REMEDIATION_PLAN.md — Phase 3

#### F94 · Regime detection and position sizing

- **Priority** P2 · **Area** Quant
- **Measured now** the 0.5x unknown-regime multiplier is gone from risk/, and 31 module(s) consume a regime (e.g. core/analytics/realtime_heatmap.py), but no reference(s) reach risk/manager.py or risk/position_sizing.py. Whether sizing SHOULD be regime-aware is a strategy decision, so this is reported as measured rather than closed
- **Fix** The specific harm F94 named — an unrouted regime leaving every position at the 0.5x 'unknown' multiplier — is gone: no such multiplier exists in `risk/`. Regimes are consumed elsewhere (signal composition, analytics). Whether *sizing* should be regime-aware at all is a strategy question, not a defect, so this is reported as measured rather than closed. Decide it deliberately or close it.
- **Write this test first** If sizing becomes regime-aware: a test asserting the size differs between a known and an unknown regime, and that unknown is the conservative one.
- **Verify** `python scripts/correction_register.py --id F94`
- **Skills** `risk-metrics-calculation`
- **Full evidence** docs/audit/REMEDIATION_PLAN.md — Phase 3

### OWNER — 5

#### A9 · `UNIQUE(client_order_id)` is documented as the duplicate-fill guard and never fires

- **Priority** OWNER · **Area** Money
- **Measured now** UNIQUE(client_order_id) is latent — no production writer populates the column (measured: 500 inserts, 500 NULLs, 0 refusals). The live guard is the intent journal in execution/trade_executor.py.
- **Fix** Make it live (writers persist the id, `IntegrityError` becomes the duplicate signal), drop the constraint, or leave it latent as it now stands. If it is made live, feed it from `trade_executor`'s 64-bit id — never from `execution/oms.py`, whose `str(uuid.uuid4())[:8]` is 32 bits against a globally unique index.
- **Write this test first** Under option 1: a test inserting the same client_order_id twice and asserting the second is refused, not silently accepted.
- **Verify** `python scripts/correction_register.py --id A9`
- **Skills** `hopefx-money-precision`, `hopefx-dead-controls`
- **Full evidence** docs/ai/MASTER_OUTSTANDING.md §A9

#### AI-SCOPE · AI Core scope questions the owner has not settled

- **Priority** OWNER · **Area** AI authority
- **Measured now** scope and hardware questions the owner has not answered
- **Fix** Four decisions, none of which engineering should default. (a) Confirm the six Business Operations department names before rebuilding Figma — the Starter-plan rate limit makes iteration expensive and the current file is already out of date. (b) Confirm VPS RAM/VRAM before locking a local model size, and settle F178/F98 first so 'what is deployed' is a known quantity. (c) Decide whether customizable settings return to scope — theme, department visibility, notification thresholds, default autonomy per department — dropped from later spec drafts and distinct from the per-action autonomy dial. (d) Sequence the AI Gateway, internal MCP tool bus, response cache, guardrails-as-pipeline and formalised evals.
- **Write this test first** None — these are scope decisions. Each becomes a plan once chosen.
- **Verify** `docs/audit/plans/2026-09-05-ai-core.md`
- **Full evidence** docs/audit/REMEDIATION_PLAN.md — AI Core section

#### F146 · Drift is measured and does not block by default

- **Priority** OWNER · **Area** ML
- **Measured now** the block path exists and DRIFT_BLOCK defaults to false, so drift is advisory in the shipped configuration. Turning it on is a trading-behaviour decision
- **Fix** The block path now exists — `DRIFT_BLOCK` — but ships false, so drift is advisory in the deployed configuration. Turning it on stops inference when the feature distribution moves, which is a trading-behaviour decision with a real cost either way: block and you halt on a regime change; do not and you trade a model outside its training distribution. The code is ready for either.
- **Write this test first** Whichever default is chosen: a test that shifts a feature past the z-threshold and asserts the configured behaviour.
- **Verify** `python scripts/correction_register.py --id F146`
- **Skills** `hopefx-dead-controls`
- **Full evidence** docs/audit/REMEDIATION_PLAN.md — Phase 1

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
- **Fix** Two credentials. (a) The superadmin credential named in the AI Core spec as item 6 — 'above everything in this plan'. Its location is still unconfirmed: the tracked working tree reads as placeholders, so the file or commit holding it has to be named before it can be rotated. (b) A Vercel token (`vck_…`) was pasted into a chat session. It was never written to disk or into any commit — verified — but it left the machine, so it must be rotated. The tracked working tree reads as placeholders; `prop_firm_mode.json` and `.env.example` are committed deliberately and must stay placeholder-only.
- **Write this test first** None — this is a credential action, not a behaviour.
- **Verify** `detect-secrets scan (already in pre-commit)`
- **Full evidence** docs/audit/REMEDIATION_PLAN.md — spec item 6; this session

### UNVERIFIED — 1

#### F172 · Icon-only buttons without an accessible name

- **Priority** P2 · **Area** Frontend
- **Measured now** not decidable by regex — a JSX attribute containing `>` breaks any attempt to bracket the opening tag. Wire eslint-plugin-jsx-a11y and this becomes a real measurement
- **Fix** Deliberately UNVERIFIED. Two regex attempts each produced a confident wrong answer (one said FIXED across 552 buttons, the other found 9 offending files) because a JSX opening tag cannot be bracketed by a regex — an attribute may contain `>`, and `onClick={() => nav('/x')}` ends the match at the arrow. Add `eslint-plugin-jsx-a11y` and let a real parser answer it; that lint rule IS the fix, and the count comes with it.
- **Write this test first** The lint rule itself, run in CI. Break one button's label and watch it fail.
- **Verify** `npm run lint  (once jsx-a11y is wired)`
- **Skills** `ui-ux-pro-max`
- **Full evidence** docs/audit/REMEDIATION_PLAN.md — Phase 6

### FIXED — 41

#### F130 · The self-healer patch queue accepted every unsigned entry

- **Priority** P0 · **Area** Security
- **Measured now** the no-key branch returns False, running unsigned needs an explicit HEAL_ALLOW_UNSIGNED_PATCHES opt-in that warns on every use, and test_self_healer_fails_closed.py injects the cases. Exercised directly as well as read: no key rejects, key with no _sig rejects, a tampered signature rejects, only a correct signature is accepted
- **Fix** Done, and this register said otherwise until 2026-09-13 — the entry was carried over from REMEDIATION_PLAN and its probe read `ai/improve/proposal.py`, which deliberately never names the key (it cannot sign and cannot apply, asserted by parsing the file). The control is in `security/self_healer.py`. `_patch_entry_is_trusted` used to return True for every entry when no key was set, and no shipped configuration set one, so there was no deployment in which it was on. It now fails closed; running unsigned needs an explicit `HEAL_ALLOW_UNSIGNED_PATCHES` opt-in that warns on every use and cannot override a configured key.
- **Write this test first** Already carried by tests/unit/test_self_healer_fails_closed.py — seven tests injecting no key, a key with no `_sig`, a correct signature, a tampered signature, the opt-in, and the opt-in against a configured key.
- **Verify** `pytest tests/unit/test_self_healer_fails_closed.py -q`
- **Skills** `hopefx-dead-controls`, `hopefx-invariants`
- **Full evidence** docs/audit/REMEDIATION_PLAN.md — Phase 3

#### F135 · Wallet ledger `transaction_id` collided at one-second resolution

- **Priority** P0 · **Area** Money
- **Measured now** payments/wallet.py:99: return f"TXN-{datetime.now(UTC).strftime('%Y%m%d')}-{uuid.uuid4().hex[:8].upper()}"
- **Fix** Done: the id carries a `uuid4` suffix, so two movements in the same second no longer collide and drop a row.
- **Write this test first** Carried by the wallet ledger tests.
- **Verify** `python scripts/correction_register.py --id F135`
- **Skills** `hopefx-money-precision`
- **Full evidence** docs/audit/REMEDIATION_PLAN.md — Phase 2

#### F136 · The wallet balance was an unlocked read-modify-write

- **Priority** P0 · **Area** Money
- **Measured now** wallet balance mutation is serialised by a lock
- **Fix** Done: mutation is serialised by an `RLock`.
- **Write this test first** A concurrency test: two simultaneous movements, assert the total is conserved.
- **Verify** `python scripts/correction_register.py --id F136`
- **Skills** `hopefx-money-precision`
- **Full evidence** docs/audit/REMEDIATION_PLAN.md — Phase 2

#### F138 · `verify_balance_after` was never called — the check that catches F135/F136

- **Priority** P0 · **Area** Invariants
- **Measured now** 4 production caller(s): invariants/enforcement.py:46: verify_balance_after,
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

#### F145 · Missing features were zero-filled before scaling

- **Priority** P0 · **Area** ML
- **Measured now** the imputation happens in scaled space, so a missing feature arrives neutral
- **Fix** Done: imputation happens in scaled space, so a missing feature reaches the model as neutral rather than -15 sigma. It was measured at -15σ for price and -3.3σ for RSI with 48.2% of the vector missing — a confident prediction from a vector the model had never seen the like of.
- **Write this test first** n/a
- **Verify** `python scripts/correction_register.py --id F145`
- **Skills** `ml-pipeline-workflow`
- **Full evidence** docs/audit/REMEDIATION_PLAN.md — Phase 5

#### F159 · Critical alerts never left the log

- **Priority** P0 · **Area** Dead controls
- **Measured now** no self-comparison guard stands between an alert and its delivery
- **Fix** Done: the `singleton is not self` guard is gone. It could never open, because the guard and the delivery were the same branch — emergency stops, drawdown breaches and circuit-breaker trips were log lines for the life of the module.
- **Write this test first** An injection test: trip a breaker with a stub transport and assert the transport was called.
- **Verify** `python scripts/correction_register.py --id F159`
- **Skills** `hopefx-dead-controls`
- **Full evidence** docs/audit/REMEDIATION_PLAN.md — Phase 1

#### F176 · `invariant_coverage.py` printed `FULL COVERAGE ✅` from hardcoded booleans

- **Priority** P0 · **Area** Dead controls
- **Measured now** prints DECLARED — the matrix no longer presents itself as a measurement
- **Fix** Done: the report now prints `DECLARED — critical-component matrix (not a measurement)`. The remaining work is the real fix — each dimension resolving to a probe that can fail — which is tracked as its own item, not this one.
- **Write this test first** Already carried by the report's own tests.
- **Verify** `python scripts/invariant_coverage.py`
- **Skills** `hopefx-dead-controls`
- **Full evidence** docs/audit/REMEDIATION_PLAN.md — Phase 1

#### F184 · The self-healer counted 'could not run tests' as 'tests passed'

- **Priority** P0 · **Area** Dead controls
- **Measured now** test_self_healer_fails_closed.py pins the distinction
- **Fix** Done: `test_self_healer_fails_closed.py` pins the distinction.
- **Write this test first** n/a
- **Verify** `pytest tests/unit/test_self_healer_fails_closed.py -q`
- **Skills** `hopefx-dead-controls`
- **Full evidence** docs/audit/REMEDIATION_PLAN.md — Phase 3

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

#### F207 · Every payout claimed every historical transaction

- **Priority** P0 · **Area** Money
- **Measured now** payouts are scoped by last_payout_at
- **Fix** Done: payouts are scoped by `last_payout_at`, so reconciliation no longer double-counts.
- **Write this test first** n/a
- **Verify** `python scripts/correction_register.py --id F207`
- **Skills** `hopefx-money-precision`
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

#### F81 · The hedge was marked active before the broker call

- **Priority** P0 · **Area** Risk
- **Measured now** the failure path returns before _hedge_active is set, so a failed hedge is a real retry rather than a latched success
- **Fix** Done: `_hedge_active` is set after a successful placement, and the failure path returns without recording anything, so the next call is a real retry. The account used to be unhedged while every dashboard said hedged, with the duplicate-activation guard latched so no retry was possible.
- **Write this test first** Already carried by the orchestrator's hedge tests.
- **Verify** `python scripts/correction_register.py --id F81`
- **Skills** `hopefx-dead-controls`
- **Full evidence** docs/audit/REMEDIATION_PLAN.md — Phase 5

#### F84 · The data-layer safety gate was skipped in the condition it exists for

- **Priority** P0 · **Area** Risk
- **Measured now** is_safe_to_trade() is consulted without an _started conjunct
- **Fix** Done: the `_started` conjunct is gone. `_started = True` is the last line of `start()`, so a failure anywhere in startup left it False and the gate was skipped in exactly the state it was written to catch.
- **Write this test first** Already carried; `execution/engine.py` documents the removal at the call site.
- **Verify** `python scripts/correction_register.py --id F84`
- **Skills** `hopefx-dead-controls`
- **Full evidence** docs/audit/REMEDIATION_PLAN.md — Phase 3

#### ROUTER-TO · A fallback broker timeout re-routed and risked a duplicate fill

- **Priority** P0 · **Area** Brokers
- **Measured now** 2 TimeoutError clause(s) — the fallback loop must stop the chain, not re-route
- **Fix** Done: a timeout in the fallback loop stops the chain. A timeout is not a confirmed failure, so the order outcome is unknown and re-routing can place a second live order.
- **Write this test first** tests/unit/test_brokers_smart_router_coverage.py::TestExecuteWithFallback::test_a_fallback_timeout_does_not_place_a_second_order
- **Verify** `pytest tests/unit/test_brokers_smart_router_coverage.py -q`
- **Skills** `hopefx-money-precision`, `hopefx-dead-controls`
- **Full evidence** This session, 2026-09-13 — commit 12bef2bb

#### AI-SURFACE · Superadmin surface must differ by capability, not by a UI branch

- **Priority** P1 · **Area** AI authority
- **Measured now** server-side capability enforcement is pinned with a 403 assertion
- **Fix** Done for the enforcement half: server-side capability is pinned with a 403 assertion. The remaining work is structural — separate components rather than `if (isSuperAdmin)` branches, plus the direct-GET probe from F198 applied to the operator routes, so an unprivileged user cannot reach an admin view by typing its URL.
- **Write this test first** A 403 test per privileged endpoint, and a direct-GET probe per operator route.
- **Verify** `pytest tests/unit/test_superadmin_capabilities_are_server_enforced.py -q`
- **Skills** `threat-modelling`, `ui-ux-pro-max`
- **Full evidence** docs/audit/REMEDIATION_PLAN.md — AI Core section

#### F119 · Annualised return divided 252 by the sample length

- **Priority** P1 · **Area** Quant
- **Measured now** no annualisation divides 252 by the sample length; backtesting/metrics.py scales by sqrt(252)
- **Fix** Done: `backtesting/metrics.py` scales by `sqrt(252)`. The old form understated by 34x on hourly bars, and Calmar inherited it.
- **Write this test first** n/a
- **Verify** `python scripts/correction_register.py --id F119`
- **Skills** `risk-metrics-calculation`
- **Full evidence** docs/audit/REMEDIATION_PLAN.md — Phase 5

#### F120 · Sortino's denominator was the std of losing observations

- **Priority** P1 · **Area** Quant
- **Measured now** calculate_sortino_ratio uses downside_deviation about the target
- **Fix** Done: `calculate_sortino_ratio` uses downside deviation about the target. The old form measured dispersion *among* losses rather than shortfall below target, so its bias flipped sign with the return distribution.
- **Write this test first** n/a
- **Verify** `python scripts/correction_register.py --id F120`
- **Skills** `risk-metrics-calculation`
- **Full evidence** docs/audit/REMEDIATION_PLAN.md — Phase 5

#### F125 · The regime EMA weighted the oldest bar most

- **Priority** P1 · **Area** Quant
- **Measured now** _ema recurses forward over the series, so the newest bar carries alpha
- **Fix** Done: `_ema` recurses forward, so alpha lands on the newest bar. The `reversed()` that remains in `ml/regime.py` is `_calculate_duration` counting backwards through state history, which is correct.
- **Write this test first** n/a
- **Verify** `python scripts/correction_register.py --id F125`
- **Skills** `risk-metrics-calculation`
- **Full evidence** docs/audit/REMEDIATION_PLAN.md — Phase 5

#### F137 · `amount_crypto` was a `Float` and could not hold 18-decimal tokens

- **Priority** P1 · **Area** Money
- **Measured now** database/models.py:1144: amount_crypto = Column(Numeric(28, 8), nullable=False)
- **Fix** Done: the column is `Numeric(28, 8)`.
- **Write this test first** n/a
- **Verify** `python scripts/correction_register.py --id F137`
- **Skills** `hopefx-money-precision`
- **Full evidence** docs/audit/REMEDIATION_PLAN.md — Phase 2

#### F144 · Login is user-enumerable by timing

- **Priority** P1 · **Area** Security
- **Measured now** the unknown-user branch verifies the supplied password against a fixed dummy hash before refusing. Measured: 309 ms vs 1.2 ms (257x) before, 313 ms vs 309 ms (1.01x) after
- **Fix** Done 2026-09-13. `login` returned as soon as the SELECT missed, so a registered address paid bcrypt at cost 12 and an unregistered one paid a failed lookup. Both branches already returned the same message, so the response gave nothing away and the clock gave away the customer list — no credentials needed, and no lockout counter to trip, because an address that does not exist has nothing to increment. Re-measured rather than trusting the audit's 268.74 ms: **309.04 ms against 1.20 ms, a 257x gap**; after the fix 312.98 ms against 309.12 ms, **1.01x**. The unknown-user branch now verifies the supplied password against a fixed dummy hash, computed on first use so no process pays ~300 ms merely to import the module.
- **Write this test first** Carried by tests/unit/test_login_does_not_enumerate_users.py: a deterministic one asserting verification actually runs for an unknown email (the mechanism, so it says the same thing on a loaded runner), a loose statistical one on the outcome, identical refusal messages, and a positive control that a correct password still authenticates — without which every other assertion is satisfied by a login that refuses everyone.
- **Verify** `python scripts/correction_register.py --id F144`
- **Skills** `threat-modelling`
- **Full evidence** docs/audit/REMEDIATION_PLAN.md — Phase 3

#### F149 · The GodMode watchlist sparkline was `Math.random()`

- **Priority** P1 · **Area** Frontend
- **Measured now** Math.random() survives only for element ids, never for a plotted value
- **Fix** Done: `Math.random()` survives only for element ids and reconnect jitter, never for a plotted value.
- **Write this test first** n/a
- **Verify** `python scripts/correction_register.py --id F149`
- **Skills** `ui-ux-pro-max`, `hopefx-dead-controls`
- **Full evidence** docs/audit/REMEDIATION_PLAN.md — Phase 6

#### F150 · 'Copy API key' built the key client-side

- **Priority** P1 · **Area** Frontend
- **Measured now** no client-side API-key construction remains
- **Fix** Done: the client asks the server to mint a key rather than assembling one that could never authenticate.
- **Write this test first** n/a
- **Verify** `python scripts/correction_register.py --id F150`
- **Skills** `ui-ux-pro-max`
- **Full evidence** docs/audit/REMEDIATION_PLAN.md — Phase 6

#### F160 · The broker probe reported `ok` from configuration

- **Priority** P1 · **Area** Dead controls
- **Measured now** broker_status calls the connector for account info and positions
- **Fix** Done: `broker_status` calls the connector for account info and positions, so an unreachable venue can no longer read as healthy.
- **Write this test first** n/a
- **Verify** `python scripts/correction_register.py --id F160`
- **Skills** `hopefx-dead-controls`
- **Full evidence** docs/audit/REMEDIATION_PLAN.md — Phase 1

#### F214 · The Phase-3 paper-trading gate gated nothing

- **Priority** P1 · **Area** Dead controls
- **Measured now** test_phase_gates_actually_gate.py pins that the store is withheld until the gate is met, and that a gate which raises fails closed
- **Fix** Done: `test_phase_gates_actually_gate.py` pins that the online-learner store is withheld until the gate is met, and that a gate which raises fails closed.
- **Write this test first** n/a
- **Verify** `pytest tests/unit/test_phase_gates_actually_gate.py -q`
- **Skills** `hopefx-dead-controls`
- **Full evidence** docs/audit/REMEDIATION_PLAN.md — Phase 1

#### F215 · `.env.example` enabled the one flag whose code default is False

- **Priority** P1 · **Area** Config
- **Measured now** FEATURE_ONLINE_LEARNING=false, matching the code default
- **Fix** Done: `FEATURE_ONLINE_LEARNING=false`, matching the code default. It had been blending an unvalidated model at 30% weight into live signals on a fresh install.
- **Write this test first** The `.env.example`-matches-code-default test in the Phase C plan.
- **Verify** `python scripts/correction_register.py --id F215`
- **Skills** `hopefx-dead-controls`
- **Full evidence** docs/audit/REMEDIATION_PLAN.md — Phase 1

#### F219 · Push notifications returned True while sending nothing

- **Priority** P1 · **Area** Dead controls
- **Measured now** the disabled/no-token branch returns False
- **Fix** Done: the disabled/no-token branch returns False. With all three Firebase variables blank by default, every push on a fresh deployment used to report success and reach no device.
- **Write this test first** n/a
- **Verify** `python scripts/correction_register.py --id F219`
- **Skills** `hopefx-dead-controls`
- **Full evidence** docs/audit/REMEDIATION_PLAN.md — Phase 1

#### F222 · `revenue_split.py` had zero tests

- **Priority** P1 · **Area** Tests
- **Measured now** 2 test file(s): tests/unit/test_revenue_split_money.py, tests/unit/test_revenue_splits_conserve.py
- **Fix** Done: two test modules now cover it.
- **Write this test first** n/a
- **Verify** `pytest tests/unit/test_revenue_split_money.py -q`
- **Skills** `test-driven-development`
- **Full evidence** docs/audit/REMEDIATION_PLAN.md — Phase 2

#### F80 · The nuclear wordmap matched by bare substring

- **Priority** P1 · **Area** Quant
- **Measured now** news/nuclear_wordmap_scorer.py matches on word boundaries
- **Fix** Done: the scorer compiles `\b...\b` patterns from escaped terms, so a headline containing 'coupon' no longer scores 'coup' and trips hedge mode.
- **Write this test first** n/a
- **Verify** `python scripts/correction_register.py --id F80`
- **Skills** `hopefx-dead-controls`
- **Full evidence** docs/audit/REMEDIATION_PLAN.md — Phase 5

#### F99 · The placeholder-secret test skipped the case it exists for

- **Priority** P1 · **Area** Security
- **Measured now** covers ['DB_ENCRYPTION_KEY', 'POSTGRES_PASSWORD']
- **Fix** Done: `DB_ENCRYPTION_KEY` and `POSTGRES_PASSWORD` are both covered.
- **Write this test first** n/a
- **Verify** `pytest tests/unit/test_placeholder_secrets_are_rejected.py -q`
- **Skills** `hopefx-dead-controls`
- **Full evidence** docs/audit/REMEDIATION_PLAN.md — Phase 3

#### FIX-STORE · FIX session continuity on an ephemeral sequence store

- **Priority** P1 · **Area** Brokers
- **Measured now** start() refuses reset_on_logon=False on a $TMPDIR store
- **Fix** Done: `IBKRFIXBridge.start()` refuses `reset_on_logon=False` when `store_path` resolves under `tempfile.gettempdir()`.
- **Write this test first** tests/unit/test_ibkr_fix_bridge.py::TestStart::test_start_refuses_session_continuity_on_an_ephemeral_store
- **Verify** `pytest tests/unit/test_ibkr_fix_bridge.py -q`
- **Skills** `hopefx-fix-bridge`, `hopefx-dead-controls`
- **Full evidence** This session, 2026-09-13 — commit 08df737a

#### F103/F104 · `brain/` and `news/` coverage gates could not pass

- **Priority** P2 · **Area** Tests
- **Measured now** in [run] source: ['brain', 'news'] — a package outside the source set cannot fail a coverage gate, whatever percentage the job prints
- **Fix** Done: both packages are inside `[run] source`. A package outside the source set cannot fail a coverage gate whatever percentage the job prints.
- **Write this test first** n/a
- **Verify** `python scripts/correction_register.py --id F103/F104`
- **Skills** `hopefx-dead-controls`
- **Full evidence** docs/audit/REMEDIATION_PLAN.md — Phase 0

#### F201 · `/academy` advertised 15 unavailable courses as available

- **Priority** P2 · **Area** Frontend
- **Measured now** no page advertises unavailable content as available
- **Fix** Done: no page advertises unavailable content as included in a plan. That was a false statement to a paying subscriber.
- **Write this test first** n/a
- **Verify** `python scripts/correction_register.py --id F201`
- **Skills** `ui-ux-pro-max`
- **Full evidence** docs/audit/REMEDIATION_PLAN.md — Phase 6

#### F205 · A log call with more placeholders than arguments cannot emit

- **Priority** P2 · **Area** Money
- **Measured now** no money-module log call has more placeholders than arguments
- **Fix** Done across `monetization/` and `payments/`. The failing record was the one a `failure_reason` told the operator to go and read.
- **Write this test first** n/a
- **Verify** `python scripts/correction_register.py --id F205`
- **Skills** `hopefx-dead-controls`
- **Full evidence** docs/audit/REMEDIATION_PLAN.md — Phase 2

#### F209 · Two dashboards, with the nav pointing at the weaker one

- **Priority** P2 · **Area** Frontend
- **Measured now** /home redirects to /dashboard — one canonical dashboard
- **Fix** Done: `/home` redirects to `/dashboard`, so there is one canonical dashboard.
- **Write this test first** n/a
- **Verify** `python scripts/correction_register.py --id F209`
- **Skills** `ui-ux-pro-max`
- **Full evidence** docs/audit/REMEDIATION_PLAN.md — Phase 6

#### F216 · `CLAUDE.md` called `data/` legacy

- **Priority** P2 · **Area** Docs
- **Measured now** CLAUDE.md describes data/ as live runtime infrastructure, with the measured LOC and importer counts
- **Fix** Done: it now describes `data/` as live runtime infrastructure with measured LOC and importer counts. The old text sat at the top of every assistant's context and routed new tick-feed work into the wrong package.
- **Write this test first** n/a
- **Verify** `python scripts/correction_register.py --id F216`
- **Skills** `doc-freshness-review`
- **Full evidence** docs/audit/REMEDIATION_PLAN.md — Phase 3

#### F217 · Four packages owned 'market data' and no document drew the boundary

- **Priority** P2 · **Area** Docs
- **Measured now** decided in docs/decisions/0013-data-owns-streaming-data-layer-owns-access.md
- **Fix** Done: ADR 0013 decides it. It is a rule describing what the code already does, not a licence to move the 106 production importers.
- **Write this test first** n/a
- **Verify** `python scripts/adr.py --list`
- **Skills** `doc-freshness-review`
- **Full evidence** docs/audit/REMEDIATION_PLAN.md — Phase 3

#### F210 · Duplicate route aliases rendering identical pages

- **Priority** P3 · **Area** Frontend
- **Measured now** 88 distinct paths, none declared twice
- **Fix** Done: 88 distinct paths, none declared twice, so breadcrumbs and active-nav agree.
- **Write this test first** n/a
- **Verify** `python scripts/correction_register.py --id F210`
- **Skills** `ui-ux-pro-max`
- **Full evidence** docs/audit/REMEDIATION_PLAN.md — Phase 6


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

### Coverage of the source documents

Every open checkbox in `docs/audit/REMEDIATION_PLAN.md` now has a probe here.
That was the last gap: an earlier version of this file tracked 27 findings and
said roughly fifty more still needed probes written.

Eight of those fifty were the AI Core section's planning items rather than
defects. They are folded into **AI-GATE**, **AI-SURFACE** and **AI-SCOPE** above
rather than listed one by one, because four of them are one scope decision wearing
four hats.

The step-by-step task checkboxes inside `docs/audit/plans/*.md` are deliberately
**not** mirrored here. Those are execution steps for work already tracked above —
"write the failing test", "run it", "commit" — and copying them would turn this
register into a task list with 200 rows and no signal. Work them in their own
plan; this file tracks the finding, not the keystrokes.

To add a finding: write a probe in `scripts/correction_register.py` and append a
`Finding(...)`. The `--check` gate then keeps the count true. A probe that cannot
honestly decide should return `UNVERIFIED` with the reason — see F172, where a
regex cannot parse JSX and two attempts produced two different confident wrong
answers.

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
