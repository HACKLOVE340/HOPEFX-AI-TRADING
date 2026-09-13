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
**75 tracked · OPEN 6 · PARTIAL 9 · OWNER 5 · UNVERIFIED 1 · FIXED 54**

### OPEN — 6

#### A8 · Two committed model artifacts fail the integrity baseline that gates their load

- **Priority** P0 · **Area** ML
- **Measured now** 2 of 12 artifacts fail their recorded sha256 (feature_scaler.pkl, stacking_ensemble.pkl); 1 listed but absent (lstm_signal.pt). ml/__init__.py::_verify_checksum reads this file on every load and refuses in production, so each mismatch is a refused load
- **Fix** `feature_scaler.pkl` and `stacking_ensemble.pkl` do not match the sha256 recorded in `ml/saved_models/model_checksums.json`. That file is not decorative: `ml/__init__.py::_verify_checksum` reads it on every load and, in production, returns False rather than bootstrapping — so `_try_load` returns None and the artifact is simply absent to the caller. Two consequences to fix together. (a) Establish which side is wrong — the recorded hash or the committed bytes — before regenerating anything; regenerating first destroys the only evidence, and the manifest has one commit in its whole history and already carried three mismatches at that commit, so it has never been correct. (b) `_try_load` returns None identically for 'file absent' and 'integrity refused'. A caller cannot tell a tampered artifact from an uninstalled one, and `ml/advanced_predictor.py:1004` then guards `if self._meta_scaler is not None`, so a refused scaler means unscaled meta-input rather than a refusal to predict. Make the two outcomes distinguishable.
- **Write this test first** An injection test: corrupt one committed artifact and assert the load is refused AND that the caller can tell refusal from absence — the second half is the part no current test covers.
- **Verify** `python scripts/correction_register.py --id A8`
- **Skills** `hopefx-dead-controls`
- **Full evidence** docs/ai/MASTER_OUTSTANDING.md §A8

#### AI-GATE · Two acceptance tests the AI layer must not ship without

- **Priority** P1 · **Area** AI authority
- **Measured now** acceptance tests present — out-of-scope action: False, execution-without-approval: False. `enforce_agent_action` and `ToolBus.invoke` exist and are called; what is missing is the pair of build-failing tests that keep them that way as the AI layer grows
- **Fix** Adopt both before writing more agent code: an agent calling an action outside its scope must FAIL THE BUILD, and a proposal executing without an approval record must fail the build. `enforce_agent_action` and `ToolBus.invoke` already run outside tests, so this is about keeping them enforced as the layer grows — without these, the spec's approval queue is the same shape as F176: a control described accurately and enforced by convention. Note the inherited prerequisites, each tracked here: the AI kill switch depends on F139 (now fixed), and the agent sandbox on F130 (open — unsigned patches) and F184 (fixed).
- **Write this test first** The two tests are the deliverable. Write them red: grant an agent a narrow scope, call outside it, assert refusal; submit a proposal with no approval record, assert it does not execute.
- **Verify** `python scripts/correction_register.py --id AI-GATE`
- **Skills** `hopefx-dead-controls`, `hopefx-invariants`, `threat-modelling`
- **Full evidence** docs/audit/REMEDIATION_PLAN.md — AI Core section

#### F218 · Model tables that exist only via `create_all()` and have no migration

- **Priority** P1 · **Area** Persistence
- **Measured now** 36 of 44 tables have no migration: account_snapshots, accounts, ai_department_memory, ai_signals, aml_alerts, api_keys
- **Fix** `create_all()` never ALTERs, so these tables drift silently between a fresh install and an upgraded one. Add the missing migrations, then a CI check comparing `__tablename__`s against the migration history.
- **Write this test first** The CI check itself is the test: assert every `__tablename__` appears in `alembic/versions/`, and watch it fail with one removed.
- **Verify** `python scripts/correction_register.py --id F218`
- **Skills** `test-driven-development`
- **Full evidence** docs/audit/REMEDIATION_PLAN.md — Phase 4

#### OF-VOTER · One of three order-flow bias voters can never vote

- **Priority** P2 · **Area** Quant
- **Measured now** _bias_vote_advanced calls self._adv.analyze(), which AdvancedOrderFlowAnalyzer does not define — every call raises AttributeError into a WARNING handler and returns None, so the majority is decided by two voters wearing three hats
- **Fix** `OrderFlowDashboard._bias_vote_advanced` calls `self._adv.analyze(symbol)`. `AdvancedOrderFlowAnalyzer` has no `analyze` — its surface is `get_aggression_metrics`, `get_pressure_gauges`, `get_order_flow_oscillator`, `detect_delta_divergence`, `get_stacked_imbalances`, `get_volume_clusters` and `get_volume_imbalance_by_level`. Every call raises `AttributeError` into a handler that logs at WARNING and returns None, so `get_bias`'s majority is decided by two voters while reading as three. Deliberately pinned rather than repaired: choosing which of those methods constitutes a bullish or bearish read is a quantitative decision, and guessing one would be inventing a signal. `get_bias` is unrouted today — reachable only from `get_summary`, which nothing serves — so nothing acts on it yet.
- **Write this test first** tests/unit/test_order_flow_says_when_it_has_no_data.py::test_the_advanced_bias_voter_can_never_vote asserts the method is absent and the vote is None, and says to rewrite itself when the voter is wired.
- **Verify** `python scripts/correction_register.py --id OF-VOTER`
- **Skills** `hopefx-dead-controls`
- **Full evidence** This session, 2026-09-13 — found while covering order_flow_dashboard.py

#### AFF-TIER · A level upgrade advances one tier per conversion

- **Priority** P3 · **Area** Money
- **Measured now** check_level_upgrade returns the first qualifying tier above the current one, so an affiliate whose numbers already clear a higher tier is granted the next one up and earns the lower commission rate until the following conversion
- **Fix** `check_level_upgrade` walks the levels above the current one and returns the FIRST that qualifies, so an affiliate whose referral count and revenue already clear a higher tier is granted only the next one up. They earn the lower commission rate until the following conversion triggers another check. Whether tiers should be skippable is a commercial decision rather than a bug, so the behaviour is pinned by a test that says so rather than quietly changed — if the policy changes, that test should fail and be rewritten.
- **Write this test first** tests/unit/test_affiliate_commissions_conserve.py::test_check_level_upgrade_advances_one_tier_per_call pins today's behaviour.
- **Verify** `python scripts/correction_register.py --id AFF-TIER`
- **Skills** `hopefx-money-precision`
- **Full evidence** This session, 2026-09-13 — found while covering affiliate.py

#### F223 · Test files named after the coverage metric

- **Priority** P3 · **Area** Tests
- **Measured now** 39 test file(s) named after the metric rather than the behaviour (was 75) — these hold the highest concentration of assertion-free tests
- **Fix** Down from 75. A file called `*_coverage_boost.py` says what it was written for rather than what it protects, and these hold the highest concentration of assertion-free tests. Rename to the behaviour; where a name already claims one (`..._skips_outside_pod`), assert that behaviour.
- **Write this test first** None — this is a rename. The value is that the next reader can tell what breaking the test would mean.
- **Verify** `python scripts/correction_register.py --id F223`
- **Skills** `test-driven-development`
- **Full evidence** docs/audit/REMEDIATION_PLAN.md — Phase 5

### PARTIAL — 9

#### F31/F32 · Affiliate money state is in memory, and the payout is a TOCTOU

- **Priority** P0 · **Area** Money
- **Measured now** commissions are conserved and serialised — a withdrawal settles exactly what it pays, and both payout paths hold the manager lock across the whole read-modify-write. Persistence is still absent: the ledger is module dicts, so a restart erases what affiliates are owed and each worker holds its own
- **Fix** **Money conservation is fixed** (2026-09-13). Three ways commission left the ledger without being paid, all reproduced before the fix and all now covered by `tests/unit/test_affiliate_commissions_conserve.py`: (1) `request_withdrawal` tested its running total *before* adding each referral, so the one that crossed the requested amount was marked PAID in full — two 60.00 commissions against a 100.00 withdrawal **destroyed 20.00**, deterministically, behind a live endpoint at `api/monetization.py:1542`; (2) a conversion landing between a payout's total and its settlement pass was settled without being in the total — **70.00 destroyed**, F203's shape one module over; (3) two concurrent payout requests each saw the full balance — **300.00 paid against 150.00 earned**. Referrals now carry `commission_paid` so a withdrawal can settle part of one, and both payout paths plus `convert_referral` hold an `RLock` across the whole read-modify-write. **Persistence remains**: the ledger is still module dicts, so a restart erases what affiliates are owed and each worker holds its own. That half needs schema — revenue_split writes through a session factory into ledger tables — and lands in F218 territory, so it is deliberately not bundled here.
- **Write this test first** For the remaining half: credit a commission, rebuild the manager from its store, and assert the balance survived. It will fail today.
- **Verify** `python scripts/correction_register.py --id F31/F32`
- **Skills** `hopefx-money-precision`
- **Full evidence** docs/audit/REMEDIATION_PLAN.md — Phase 2

#### F147 · Order flow answered as though it had measured, and had two analyzers

- **Priority** P1 · **Area** Dead controls
- **Measured now** /delta, /levels and /footprint refuse a symbol with no ingested ticks, as /analysis and /profile already did; /stats reports `ingesting`; the dashboard no longer derives a bias from nothing; and init_order_flow returns the same analyzer the router serves, so wiring a feed to it would actually reach the endpoints. A tick source is still not subscribed — that is a product decision, and the endpoints now say so instead of answering zero
- **Fix** Done 2026-09-13, on the honesty half — and a second defect underneath it. **(a) Zeros presented as measurements.** `/analysis` and `/profile` already 404ed with no data; `/delta` returned `cumulative_delta: 0`, `/levels` an empty level set and `/footprint` an empty list — each identical to a real, balanced, quiet tape. The dashboard was worse: `get_market_bias` returned `{bias: neutral, strength: weak}`, a defensible trading read synthesised from zero ticks. All now refuse, matching the convention the router had already set for itself, and `/stats` states `ingesting` so an operator can tell a quiet tape from a dead subscription. **(b) Two analyzers, and the feedable one was unreachable.** `init_order_flow` built its own `OrderFlowAnalyzer()` and mounted a duplicate of the same paths with a plain `include_router`, while the registry mounted the module global; FastAPI resolves to the first, so the startup service was shadowed. Measured: two trades into it and `/delta` still answered 0. Anyone wiring a tick feed to the obvious object would have seen nothing change, with no error. It now returns the analyzer that serves. **Subscribing a tick source remains open** — which symbols, what rate, what retention is a product decision, and the endpoints now say `not measured` rather than guessing in the meantime.
- **Write this test first** Carried by tests/unit/test_order_flow_says_when_it_has_no_data.py — refusals per endpoint, positive controls that a fed symbol is served (one of which caught the dashboard tests passing against a wrong route prefix), the delta's real value, the `ingesting` flag, and that the startup service is the served analyzer.
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
- **Measured now** /kyc serves the SPA again — nothing claimed it, and only the string in _passthrough_prefixes was refusing it. /mobile remains a genuine collision: App.tsx declares the page AND router_registry mounts the mobile API sub-application at the same path (measured: one exact route, one Mount). Serving the SPA there would shadow a live API, so resolving it means renaming the page or moving the mount to /api/mobile — a product choice, pinned by a test so the exemption cannot quietly become permanent
- **Fix** Half done. `/kyc` serves the SPA again: measured, nothing claimed that path at all — zero exact routes, zero sub-routes — and the only thing refusing it was the string `kyc` in the catch-all's `_passthrough_prefixes`. A user following a verification email got `{"detail":"No route for GET /kyc"}` on a regulatory gate. Sub-paths still pass through on the prefix, so `/kyc/webhooks/sumsub` keeps reaching its handler — answering a provider webhook with the SPA shell would be worse than 404ing it. **`/mobile` is a real collision and stays open**: App.tsx declares the page and `core/router_registry.py` mounts the mobile API sub-application at the same path, so serving the SPA there would shadow a live API. Renaming the page or moving the mount to `/api/mobile` is a product choice.
- **Write this test first** tests/unit/test_every_spa_route_serves_the_app.py found both routes independently, without being told the finding existed, by asking whether a direct GET returns HTML. `/mobile` is exempted with its reason and pinned by test_the_mobile_collision_is_still_a_collision, so the exemption fails the day it stops being true.
- **Verify** `pytest tests/unit/test_every_spa_route_serves_the_app.py -q`
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

#### F97 · The only action holding `VPS_SSH_KEY` is float-pinned

- **Priority** P1 · **Area** CI
- **Measured now** 1 secret-holding action(s) still on a mutable tag (deploy.yml: appleboy/ssh-action@v1.2.5). A ratchet blocks a second one and the recorded set may only shrink; the pin itself needs the tag resolved to its 40-character SHA on GitHub
- **Fix** Half done, and the remaining half is blocked on something this session cannot do. `appleboy/ssh-action@v1.2.5` is a tag, and a tag is mutable: whoever controls it controls a step that receives the private deploy key for the production VPS. It is the only `uses:` in the repository that both takes a secret and floats. Resolving the tag to its 40-character commit SHA needs a lookup against `appleboy/ssh-action`, and this session's GitHub access is scoped to this repository — the API and a direct fetch both refuse. A guessed SHA breaks every deploy, so it is not guessed. What is in place is the invariant as a **ratchet**, the shape `FRESHNESS_BASELINE.toml` and `COVERAGE_UNMEASURABLE.txt` already use here: the one known reference is recorded, a second secret-holding action on a tag fails immediately, and a companion test fails if the recorded entry is left behind after the pin lands. To finish: resolve the SHA, write `appleboy/ssh-action@<sha>  # v1.2.5`, delete the line from `_UNPINNED_SECRET_ACTIONS`.
- **Write this test first** tests/unit/test_deploy_workflow_is_gated_and_pinned.py — the ratchet, proven by injecting a second secret-holding action on a tag and watching it refuse.
- **Verify** `pytest tests/unit/test_deploy_workflow_is_gated_and_pinned.py -q`
- **Skills** `test-driven-development`
- **Full evidence** docs/audit/REMEDIATION_PLAN.md — Phase 0

#### F94 · Regime detection and position sizing

- **Priority** P2 · **Area** Quant
- **Measured now** the 0.5x unknown-regime multiplier is gone from risk/, and 31 module(s) consume a regime (e.g. core/analytics/realtime_heatmap.py), but no reference(s) reach risk/manager.py or risk/position_sizing.py. Whether sizing SHOULD be regime-aware is a strategy decision, so this is reported as measured rather than closed
- **Fix** The specific harm F94 named — an unrouted regime leaving every position at the 0.5x 'unknown' multiplier — is gone: no such multiplier exists in `risk/`. Regimes are consumed elsewhere (signal composition, analytics). Whether *sizing* should be regime-aware at all is a strategy question, not a defect, so this is reported as measured rather than closed. Decide it deliberately or close it.
- **Write this test first** If sizing becomes regime-aware: a test asserting the size differs between a known and an unknown regime, and that unknown is the conservative one.
- **Verify** `python scripts/correction_register.py --id F94`
- **Skills** `risk-metrics-calculation`
- **Full evidence** docs/audit/REMEDIATION_PLAN.md — Phase 3

#### F175 · Emoji used as UI icons

- **Priority** P3 · **Area** Frontend
- **Measured now** 1389 emoji across 145 files remain, capped: the ratchet is wired into pre-commit and proven able to fail, so the number can only go down. CommandPalette's 60 are gone — its hand-written nav list, which had drifted from NAV_ITEMS (Dashboard to /home, 2FA Setup to a route that does not exist, eleven sidebar pages never added), is now derived from NAV_ITEMS with its Lucide icons. Converting the remaining 154 files is a codemod and an owner decision
- **Fix** The plan recorded this as done for `frontend/src` — 'no source file carries emoji'. It was not: 1,389 across 145 files on 2026-09-13, concentrated exactly where icons live (PlatformConfiguration.tsx 136, SystemReliabilitySection.tsx 62, Settings.tsx 52). `ui-ux-pro-max` forbids emoji as icons and navConfig.ts already records the cost (F170): no `currentColor`, so they ignore theme, hover and disabled state; per-platform rendering; announced literally by a screen reader. Capped by a ratchet rather than closed by a 154-file codemod, which is the owner's call.
- **Write this test first** Carried by test_frontend_emoji_ratchet.py (five injections plus the exclusion test that keeps 79,148 box-drawing characters out of scope) and command_palette_follows_nav.test.tsx (the palette follows NAV_ITEMS and renders no emoji; four of its five assertions fail against the pre-fix component).
- **Verify** `python scripts/correction_register.py --id F175`
- **Skills** `ui-ux-pro-max`
- **Full evidence** docs/audit/REMEDIATION_PLAN.md — Phase 6

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

### FIXED — 54

#### DEPLOY-CHART · The chart ArgoCD deploys carried none of the safety posture the tests verify

- **Priority** P0 · **Area** Config
- **Measured now** the chart ArgoCD syncs states all three safety keys at safe values and ships the kill switch's layer-5 ConfigMap with least-privilege RBAC
- **Fix** Twenty-three tests over `k8s/` and `deployments/k8s/` proved HOPEFX_INVARIANT_MODE, DRIFT_BLOCK, STALE_MODEL_BLOCK, the kill-switch ConfigMap and its RBAC were all correct. `k8s/argocd-app.yaml` syncs `spec.source.path: helm/hopefx`, which is neither tree and carried none of them — so the cluster ArgoCD builds ran with invariants in `monitor` (they observe and never refuse), DRIFT_BLOCK false (inference continues on a drifted feature distribution), no object for the kill switch's Redis-outage fallback to patch, and no RBAC to reach one. Worse, `prune: true` DELETES a kill-switch ConfigMap applied by hand from `k8s/`, because it is not in the chart. Defaults proven by execution, not read: `invariants.enforcement._DEFAULT_MODE == 'monitor'`, `ml.inference_engine._DRIFT_BLOCK is False`. Fixed: values.yaml states all three keys, and helm/hopefx/templates/kill-switch.yaml ships the ConfigMap, ServiceAccount, Role and RoleBinding with the same least privilege as `k8s/`.
- **Write this test first** Carried by tests/unit/test_the_deployed_chart_carries_the_safety_posture.py, which reads `spec.source.path` rather than naming a directory — so repointing ArgoCD moves the assertions with it instead of silently emptying them. Five of its seven assertions fail on the pre-fix tree; its positive control fails if the scan matches no Application, which is how the first draft's harness bug was caught.
- **Verify** `python scripts/correction_register.py --id DEPLOY-CHART`
- **Skills** `hopefx-dead-controls`, `hopefx-invariants`, `test-driven-development`
- **Full evidence** This session, 2026-09-13 — found by following spec.source.path instead of a directory

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

#### F178/F98 · Two ConfigMaps named `hopefx-config` with contradictory safety values

- **Priority** P0 · **Area** Config
- **Measured now** 5 ConfigMap(s), 4 distinct names, no divergent duplicate. The staged set runs monitor + enforce-kinds by design and names its broker, and the chart ArgoCD syncs states all three safety keys
- **Fix** `k8s/` says `HOPEFX_INVARIANT_MODE=enforce`; `deployments/k8s/` says `monitor`. Both objects carry the same name, so which one is live depends on apply order. Decide which tree deploys, delete or rename the other, and add a test that fails on two ConfigMaps sharing a name.
- **Write this test first** A manifest test asserting no two ConfigMaps share `metadata.name`, and that `HOPEFX_INVARIANT_MODE` is `enforce` wherever `BROKER_TYPE != paper`.
- **Verify** `python scripts/correction_register.py --id F178/F98`
- **Skills** `hopefx-invariants`, `test-driven-development`
- **Full evidence** docs/audit/REMEDIATION_PLAN.md — Phase 3

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

#### KS-SELFHEAL · ArgoCD self-heal reverts a pod-engaged kill switch

- **Priority** P0 · **Area** Config
- **Measured now** 1 ArgoCD Application(s): a sync cannot revert an engaged kill switch
- **Fix** Layer 5 of the kill switch engages by a pod PATCHING the `hopefx-kill-switch` ConfigMap to `kill_switch_active: "true"` through the Kubernetes API. `k8s/argocd-app.yaml` sets `syncPolicy.automated.selfHeal: true`, whose purpose in that file's own words is to *revert any manual changes made directly to live resources* — and a pod's API patch is exactly that, while Git says `false`. The control of last resort was switched back off by the deployment controller, on the next reconciliation and again every time it was re-engaged, while every manifest, RBAC rule and test read correct. Fixed with an `ignoreDifferences` entry on that ConfigMap's `/data`, which fails safe in both directions: an engaged switch survives a sync, and the documented reset is a `kubectl patch`, not a Git commit.
- **Write this test first** Carried by test_kill_switch_layers_survive_deployment.py::test_self_heal_cannot_revert_an_engaged_kill_switch, plus a companion asserting RespectIgnoreDifferences stays set — without it the exemption applies only to the diff view and the defect returns while the Git entry still reads correct.
- **Verify** `python scripts/correction_register.py --id KS-SELFHEAL`
- **Skills** `hopefx-dead-controls`, `hopefx-invariants`
- **Full evidence** This session, 2026-09-13 — found while closing F178/F98

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

#### F106 · Nothing tests the TradeExecutor ↔ real-connector join

- **Priority** P1 · **Area** Tests
- **Measured now** exercised against autospec'd connectors by tests/unit/test_trade_executor_against_real_connectors.py. Note the finding's premise was wrong: BrokerConnector.place_market_order is a concrete base method every connector inherits, so the signature mismatch F61 describes does not exist
- **Fix** `TradeExecutor` was tested against `MagicMock` brokers only. A mock with no spec agrees with every call, so nothing in the suite could tell a real connector surface from an invented one. Closed with `create_autospec(..., spec_set=True)` against all 15 concrete connectors. **The finding's stated cause was wrong, and this is the correction.** It said F61's mismatch — the executor calling `place_market_order` while connectors implement `place_order` — would surface at the first live order, and `grep -c 'def place_market_order' brokers/*.py` returns 1, which appears to confirm it. It does not. `BrokerConnector.place_market_order` is a CONCRETE base method (brokers/base.py:558) adapting the router's (symbol, side, quantity) contract onto each connector's `place_order`, handling sync and async bodies and normalising the result. Every connector inherits it; a per-file grep cannot see an inherited method, so it counted the one class that overrides it and called the other fourteen broken. An adapter was written against that phantom before these tests caught it — carrying a fallback branch getattr could never reach, a guard that can never open, added while closing a finding about guards that can never open. It was reverted.
- **Write this test first** Carried by tests/unit/test_trade_executor_against_real_connectors.py — 37 assertions across 15 connectors. Three are shaped to fail if a belief drifts: one fails the moment BrokerConnector.place_market_order is removed (when the register's original claim would become true), one fails if any override narrows the signature the executor calls, and a positive control shows in four lines why a spec-less mock could not have caught either outcome.
- **Verify** `python scripts/correction_register.py --id F106`
- **Skills** `hopefx-dead-controls`, `test-driven-development`
- **Full evidence** docs/audit/REMEDIATION_PLAN.md — Phase 5

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

#### F123 · `/walk-forward/run` tested on its own training data

- **Priority** P1 · **Area** Quant
- **Measured now** each fold is measured over its own window, the folds advance through time, and purge_days embargoes training from testing. Before: all five folds measured the same recent period with the test window inside the training window, and the fold dates were labels for a computation that never happened
- **Fix** Done 2026-09-13, and it was worse than this entry said. The endpoint computed five fold windows spanning three years and then discarded them: `_run_real_backtest(strategy, symbol, days, capital)` takes a *count of days* and always ends at `datetime.now(UTC)`. So all five folds measured the same recent period — train the last 153 days, test the last 66 — **with the test window contained entirely inside the training window**, which is total leakage rather than a missing purge gap, while the 2023-2026 fold dates reached the response as labels for a computation that never happened. `avg_test_sharpe` was the last 66 days' Sharpe averaged with itself. Each fold now runs over its own window through `_run_backtest_window`, the folds advance, and a `purge_days` embargo (default 5) separates training from testing. `WalkForwardEngine` is deliberately still not called: it is a parameter-grid optimiser and this endpoint validates one parameterisation, so using it would mean inventing a grid the caller did not ask for. Its purge semantics were the part worth borrowing.
- **Write this test first** Carried by tests/unit/test_walk_forward_actually_walks_forward.py — distinct periods per fold, no train/test overlap, an embargo of the requested width, reported dates equal to measured dates, and folds that advance. Two of them initially passed against the defect because they compared datetimes and the broken code called now() once per backtest; they compare dates now.
- **Verify** `python scripts/correction_register.py --id F123`
- **Skills** `backtesting-frameworks`
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

#### F220 · Device tokens were lost on every deploy

- **Priority** P1 · **Area** Money
- **Measured now** tokens are held in a shared store keyed per user, the broadcast enumerates it rather than this process's dict, and POST /register-push reports `durable` so a registration that will not survive a restart is not answered with an unqualified `registered: true`. Falls back to process memory when no store is reachable — degraded, and loud about it
- **Fix** Done 2026-09-13. `_device_tokens` was a module-level dict and nothing else, so **every deploy silently unregistered every device** — a correctly configured FCM with real credentials and real tokens simply stopped delivering, with no error, because the server believed the user had no devices. Each worker also held its own set, so registering through one and sending from another found nothing and looked like a flaky client. This is what made the F219 fix incomplete: the send became honest and still had nobody to reach. Tokens now live in a shared store (Redis, the same resolved-once pattern as `core/idempotency.py`; a table would need a migration and F218 says 36 of 44 have none), with process memory as a loud fallback. `register_device` returns whether the registration is DURABLE rather than an unconditional True, and `POST /register-push` passes that through as `durable` — it answered `registered: true` for registrations it knew would not outlive the process. **`broadcast_signal` mattered as much as the lookup**: it enumerated `_device_tokens.keys()` under the docstring "all registered users", so after a deploy it reached nobody and returned `notified: 0` as a success. Persisting per-user lookup alone would have made the endpoints look right and left the broadcast silently empty. `registered_users()` scans the token keys rather than maintaining a parallel index — a second copy that must be kept in step is this repository's most repeated defect, and a scan cannot disagree with the keys it scans.
- **Write this test first** Carried by tests/unit/test_device_tokens_survive_a_restart.py — survival across a simulated restart, cross-worker visibility of both registration and revocation, no duplicate on a retried register, the durability signal, a failing store degrading rather than dropping the device, and the broadcast reaching users this process never registered. The two cross-worker tests initially passed against the defect because both `workers` shared the module dict; they clear it now.
- **Verify** `python scripts/correction_register.py --id F220`
- **Skills** `hopefx-dead-controls`
- **Full evidence** docs/audit/REMEDIATION_PLAN.md — Phase 6

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

#### F96 · `deploy.yml` fires on every push to `main` with no CI gate

- **Priority** P1 · **Area** CI
- **Measured now** deploy triggers on the CI workflow completing and runs only when its conclusion is success; workflow_dispatch is allowed through explicitly
- **Fix** Done 2026-09-13. `deploy.yml` had no `needs:` and no `workflow_run:`, so the only thing between a push to main and `docker compose up` on the production VPS was the push. It now triggers on the CI workflow completing on main and runs only when the conclusion is `success` — the conclusion check matters as much as the trigger, because `workflow_run` fires on failure and cancellation too, and a trigger without it reads as a gate while shipping red builds. `workflow_dispatch` is allowed through explicitly so a manual deploy still works. Two consequences, both stated in the workflow: `workflow_run` does not support `paths-ignore`, so the docs-only skip is gone and a documentation push that passes CI now redeploys (idempotent, costs runner time); and deployment is now coupled to CI actually running, which while F95 holds means no deploy — but deploy.yml is not running today either, so nothing regresses and both return together when billing is restored.
- **Write this test first** tests/unit/test_deploy_workflow_is_gated_and_pinned.py asserts the gate exists and that it requires success rather than mere completion.
- **Verify** `pytest tests/unit/test_deploy_workflow_is_gated_and_pinned.py -q`
- **Skills** `test-driven-development`
- **Full evidence** docs/audit/REMEDIATION_PLAN.md — Phase 0

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

#### ML-LEAK · The smoke retrain leaks committed model artifacts into the working tree

- **Priority** P1 · **Area** ML
- **Measured now** the fixture snapshots every file in ml/saved_models/ instead of a named subset, so a writer added tomorrow is covered the day it lands; and scripts/model_artifact_manifest_gate.py refuses a staged artefact whose recorded checksum did not change with it
- **Fix** Done 2026-09-13, both halves. `ml/train_advanced.py` writes eight artifacts into `ml/saved_models/` and the `_SMOKE_OVERWRITES` restore list named six, so two leaked into the working tree after every suite run and were committed alongside whatever else was in flight. The fixture now snapshots the whole directory — a restore list that must be kept in step with a writer is a list that falls out of step — and `scripts/model_artifact_manifest_gate.py` refuses a staged artefact whose recorded checksum did not change with it, so the class of accident cannot be committed however it leaks in. **This was the root cause of A8** — proven, not surmised: `model_checksums.json` has one commit (`334e50f3`), while `feature_scaler.pkl` and `stacking_ensemble.pkl` have three each, and one of the later two is `05efdbab`, a *mobile authentication* fix that carried `feature_scaler.pkl`, `stacking_ensemble.pkl`, `feature_stats.json` and a new `feature_importances.json` for no reason connected to its subject. Fix the list, then add the gate: a commit that changes an artifact under `ml/saved_models/` without regenerating the manifest should not pass.
- **Write this test first** Carried by test_ml_training_pipeline.py (mutate every artefact train_advanced writes, discovered from its source, and assert all are handed back) and test_model_artifact_manifest_gate.py (seven injections against a real throwaway repository).
- **Verify** `python scripts/correction_register.py --id ML-LEAK`
- **Skills** `hopefx-dead-controls`, `test-driven-development`
- **Full evidence** This session, 2026-09-13 — reproduced by execution

#### F103/F104 · `brain/` and `news/` coverage gates could not pass

- **Priority** P2 · **Area** Tests
- **Measured now** in [run] source: ['brain', 'news'] — a package outside the source set cannot fail a coverage gate, whatever percentage the job prints
- **Fix** Done: both packages are inside `[run] source`. A package outside the source set cannot fail a coverage gate whatever percentage the job prints.
- **Write this test first** n/a
- **Verify** `python scripts/correction_register.py --id F103/F104`
- **Skills** `hopefx-dead-controls`
- **Full evidence** docs/audit/REMEDIATION_PLAN.md — Phase 0

#### F108 · Test files that define tests and assert nothing

- **Priority** P2 · **Area** Tests
- **Measured now** all 886 unit-test files that define a test also assert
- **Fix** Two files remain. A test that cannot fail is a measurement that cannot fail — the defining defect of this codebase, in the suite that is supposed to catch it. Give each an assertion or delete it.
- **Write this test first** The probe is the test: assert no unit-test file defines a test without asserting.
- **Verify** `python scripts/correction_register.py --id F108`
- **Skills** `hopefx-dead-controls`, `test-driven-development`
- **Full evidence** docs/audit/REMEDIATION_PLAN.md — Phase 5

#### F173 · `/dashboard` renders no headings

- **Priority** P2 · **Area** Frontend
- **Measured now** the page renders one h1 (from PageHeader) and an h2 per section, asserted against the rendered DOM including that no level is skipped
- **Fix** Done 2026-09-13, and the finding was overstated. It said the page renders zero h1-h3. It renders one h1 — from the shared `<PageHeader>` component, which a grep of Dashboard.tsx cannot see. The real gap was the level below: all seven section titles (Live Equity Curve, Open Positions, Active Signals, Market Regime, Risk Snapshot, ML Model Accuracy, Quick Navigation) were `<span>`s carrying a `cardTitle` style, so the page offered one landmark and no way for a screen reader to move between its regions. They are `<h2>` now; `margin: 0` and the explicit size neutralise the browser defaults, so the change is semantic with no visual difference.
- **Write this test first** frontend/src/test/dashboard_heading_outline.test.tsx asserts the outline against the RENDERED DOM — one h1, an h2 per named section, and no skipped level — which is the only way to see a heading a child component contributes.
- **Verify** `cd frontend && npx vitest run src/test/dashboard_heading_outline.test.tsx`
- **Skills** `ui-ux-pro-max`
- **Full evidence** docs/audit/REMEDIATION_PLAN.md — Phase 6

#### F187 · Dashboard metrics do not drill through

- **Priority** P2 · **Area** Frontend
- **Measured now** 8 headline figures are links to the page that explains them, each with a 44px minimum target and an accessible name naming the figure, its value and its destination
- **Fix** Not a defect, and this register said it was until 2026-09-13. The probe counted `onClick` in Dashboard.tsx, found one, and concluded the metrics do not drill through. They do, and did before this audit began: `StatCard` renders a react-router `<Link>` when given `to`, and all eight headline figures pass one — Balance to /wallet, Win Rate to /journal, Sharpe and Account DD to /performance, and so on. Each carries a 44px minimum target, a chevron affordance, and an `aria-label` naming the figure, its value and what the destination answers. The component's own docstring cites F187. Counting the wrong mechanism produced a confident wrong answer on a page this register called the product's front door.
- **Write this test first** Now covered by frontend/src/test/dashboard_heading_outline.test.tsx, which resolves the tiles by accessible name and asserts both the href and the target size.
- **Verify** `cd frontend && npx vitest run src/test/dashboard_heading_outline.test.tsx`
- **Skills** `ui-ux-pro-max`
- **Full evidence** docs/audit/REMEDIATION_PLAN.md — Phase 6

#### F199 · `_SPA_ROUTES` is hand-maintained and disagrees with `App.tsx`

- **Priority** P2 · **Area** Frontend
- **Measured now** the catch-all passes a bare page path through only when a route or mount really claims it, instead of guessing from a prefix string; and every path App.tsx declares is fetched directly in a test built on the real router registry, so a future router mounted at a bare prefix fails immediately
- **Fix** Done 2026-09-13, by testing the property instead of syncing the list. The gap between `_SPA_ROUTES` (60) and App.tsx (88) was never the defect: an unlisted path reaches the `/{full_path:path}` catch-all and still gets index.html, so the list is an optimisation. The defect was that the catch-all decided what is a server path from a hand-maintained prefix STRING — and `kyc`, `mobile` and `godmode` are both API namespaces and page names, so `/kyc` 404ed with nothing behind it. It now asks the route table: a bare page path passes through only when a route or mount really claims it. Every path App.tsx declares is fetched directly in a test built on the real router registry, so the next router mounted at a bare prefix fails immediately rather than shadowing a page silently.
- **Write this test first** tests/unit/test_every_spa_route_serves_the_app.py — extracts the routes from App.tsx rather than restating them, guards that the extraction still works before trusting what it reports, and checks the converse (that /api/ is not swallowed by the SPA).
- **Verify** `pytest tests/unit/test_every_spa_route_serves_the_app.py -q`
- **Skills** `ui-ux-pro-max`, `test-driven-development`
- **Full evidence** docs/audit/REMEDIATION_PLAN.md — Phase 6

#### F200 · `/docs` is blank in every deployment

- **Priority** P2 · **Area** Frontend
- **Measured now** the CSP admits the Swagger CDN exactly where /docs is mounted — everywhere except production, whose script-src stays 'self' and is guarded by its own test. The coupling is the invariant: a CDN allowed in production, or a docs page that still cannot load, both fail
- **Fix** Done 2026-09-13. Swagger UI fetches its JS and CSS from jsDelivr and the CSP admitted neither, so the page rendered empty with the reason visible only in the browser console. The finding said "blank in every deployment" and the difference decided the fix: `app.py` and `api/server.py` both set `docs_url=None if APP_ENV == "production"`, so in production /docs does not exist at all — it was blank in development, staging and local runs, which is where people open it. The CDN is now allowed **exactly where the page is mounted**, and production's `script-src 'self'` is untouched. Vendoring swagger-ui-dist — the usual answer — was rejected deliberately: `static/` is gitignored, so it would mean committing ~1.5 MB of vendor JavaScript to serve a page that does not exist in the environment the CSP protects.
- **Write this test first** tests/unit/test_docs_page_can_load_its_own_assets.py pins the coupling in both directions — the CDN is admitted iff the docs are mounted — plus a regression guard that production script-src stays 'self' with no unsafe-inline, so a later relaxation cannot pass as part of this fix.
- **Verify** `pytest tests/unit/test_docs_page_can_load_its_own_assets.py -q`
- **Skills** `ui-ux-pro-max`
- **Full evidence** docs/audit/REMEDIATION_PLAN.md — Phase 6

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
