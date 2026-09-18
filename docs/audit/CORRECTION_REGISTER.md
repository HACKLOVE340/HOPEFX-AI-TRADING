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
python scripts/correction_register.py --write    # regenerate §3 below, keeping §1-§2 and §4-§6
#   NOT `--markdown > this file`: that writes only §3 and deletes the other five.
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
**100 tracked · OPEN 1 · PARTIAL 9 · OWNER 7 · UNVERIFIED 0 · FIXED 83**

### OPEN — 1

#### DENSITY-CANNOT-REACH · The density control is stamped on every route and can reach almost nothing

- **Priority** P2 · **Area** Frontend
- **Measured now** 33 token-reading utilities against 2107 inline fontSize and 1091 numeric spacing utilities — 3198 sizes the density control cannot reach
- **Fix** `PageSurface` stamps `data-density` on every route, `index.css` fully specifies three tiers across eleven tokens each, and CLAUDE.md documents it as "one table, stamped on every route". Every part of that is true and none of it reaches a pixel on most pages: the tokens the tiers redefine are consumed by 29 class usages in the whole application, against 2,871 inline `fontSize: <number>` and 1,089 numeric Tailwind spacing utilities. A literal pixel is not in the cascade, so no tier can change it. That is why the interface does not feel dense at any setting, and it is the dead-control shape: a control that exists, is documented accurately, and never runs. It is the same defect as the 3,555 colour literals, in the size dimension — and the colour side already has a codemod and a ratchet, which is the precedent for closing this one. NOT fixed by making density a user preference: that made the control settable, which is a different thing from making it effective, and shipping the control without recording this would have been shipping a second dead control on top of the first.
- **Write this test first** frontend/src/test/density_is_not_a_dead_control.test.ts proves the three tiers are specified, monotonic and separated by a real margin rather than a rounding one — parsed from index.css, because the tiers live inside `@layer base`, which jsdom's CSSOM drops entirely, so a `getComputedStyle` assertion here would have been a test of jsdom's coverage rather than of the cascade. The live cascade is proved in a browser. This entry stays OPEN until the literal sizes reach the token layer; the probe counts both sides from the tree, so it closes itself and cannot be closed by assertion.
- **Verify** `python scripts/correction_register.py --id DENSITY-CANNOT-REACH`
- **Skills** `hopefx-dead-controls`, `verification-before-completion`
- **Full evidence** Measured 2026-09-15 while making density a user choice

### PARTIAL — 9

#### BALANCE-SOURCE-SPLIT · The balance a user is shown and the balance a withdrawal checks are different numbers

- **Priority** P1 · **Area** Money
- **Measured now** the response now reports the ledger alongside the shown balance and whether they agree, so the split is visible and measurable — but the shown number still comes from the broker or the subscription manager, not the ledger a withdrawal is refused against. Reconciliation is an owner decision, not a refactor
- **Fix** `api/billing.py::get_balance` says in its own docstring "Return the authenticated user's wallet balance" and then reads the BROKER account, falling back to the subscription manager. It never reads `wallet_transactions`. Meanwhile ADR 0021 makes the fiat wallet the ledger a withdrawal debits, and `_apply_movement` refuses when `before < amount`. So the number the UI shows and the number the refusal is computed from come from two different sources, and the ledger carries no history — nothing wrote it before deposits began crediting it. This is why `WITHDRAWAL_DEBITS_LEDGER` ships default-FALSE: with it on today, a user the UI says has funds is refused 402, which is an outage that looks like a money bug, and the pressure to fix it falls on the balance check, which is a real gate. The fix is reconciliation, not a wider tolerance and not a removed check: decide what is authoritative, and make `get_balance` read that, or seed the ledger from it. Deleting the docstring's promise instead would leave two numbers and no statement that they disagree.
- **Write this test first** Assert that the value `/billing/balance` returns and the value a withdrawal is checked against come from the same source. It fails today at the point where one reads the broker and the other reads the ledger. Until then, `test_withdrawal_debits_the_wallet_ledger.py::test_the_flag_defaults_to_off_and_nothing_is_debited` pins the safe default.
- **Verify** `python scripts/correction_register.py --id BALANCE-SOURCE-SPLIT`
- **Skills** `hopefx-money-precision`, `verification-before-completion`
- **Full evidence** This session, 2026-09-18 — surfaced while planning the withdrawal debit (ADR 0021)

#### F147 · Order flow answered as though it had measured, and had two analyzers

- **Priority** P1 · **Area** Dead controls
- **Measured now** /delta, /levels and /footprint refuse a symbol with no ingested ticks, as /analysis and /profile already did; /stats reports `ingesting`; the dashboard no longer derives a bias from nothing; and init_order_flow returns the same analyzer the router serves, so wiring a feed to it would actually reach the endpoints. A tick source is still not subscribed — that is a product decision, and the endpoints now say so instead of answering zero
- **Fix** Done 2026-09-13, on the honesty half — and a second defect underneath it. **(a) Zeros presented as measurements.** `/analysis` and `/profile` already 404ed with no data; `/delta` returned `cumulative_delta: 0`, `/levels` an empty level set and `/footprint` an empty list — each identical to a real, balanced, quiet tape. The dashboard was worse: `get_market_bias` returned `{bias: neutral, strength: weak}`, a defensible trading read synthesised from zero ticks. All now refuse, matching the convention the router had already set for itself, and `/stats` states `ingesting` so an operator can tell a quiet tape from a dead subscription. **(b) Two analyzers, and the feedable one was unreachable.** `init_order_flow` built its own `OrderFlowAnalyzer()` and mounted a duplicate of the same paths with a plain `include_router`, while the registry mounted the module global; FastAPI resolves to the first, so the startup service was shadowed. Measured: two trades into it and `/delta` still answered 0. Anyone wiring a tick feed to the obvious object would have seen nothing change, with no error. It now returns the analyzer that serves. **Subscribing a tick source remains open** — which symbols, what rate, what retention is a product decision, and the endpoints now say `not measured` rather than guessing in the meantime.
- **Write this test first** Carried by tests/unit/test_order_flow_says_when_it_has_no_data.py — refusals per endpoint, positive controls that a fed symbol is served (one of which caught the dashboard tests passing against a wrong route prefix), the delta's real value, the `ingesting` flag, and that the startup service is the served analyzer.
- **Verify** `python scripts/correction_register.py --id F147`
- **Skills** `hopefx-dead-controls`
- **Full evidence** docs/audit/REMEDIATION_PLAN.md — Phase 5

#### F198 · `/kyc` returns raw JSON 404 on direct navigation

- **Priority** P1 · **Area** Frontend
- **Measured now** /kyc serves the SPA again — nothing claimed it, and only the string in _passthrough_prefixes was refusing it. /mobile remains a genuine collision: App.tsx declares the page AND router_registry mounts the mobile API sub-application at the same path (measured: one exact route, one Mount). Serving the SPA there would shadow a live API, so resolving it means renaming the page or moving the mount to /api/mobile — a product choice, pinned by a test so the exemption cannot quietly become permanent
- **Fix** Half done. `/kyc` serves the SPA again: measured, nothing claimed that path at all — zero exact routes, zero sub-routes — and the only thing refusing it was the string `kyc` in the catch-all's `_passthrough_prefixes`. A user following a verification email got `{"detail":"No route for GET /kyc"}` on a regulatory gate. Sub-paths still pass through on the prefix, so `/kyc/webhooks/sumsub` keeps reaching its handler — answering a provider webhook with the SPA shell would be worse than 404ing it. **`/mobile` is a real collision and stays open**: App.tsx declares the page and `core/router_registry.py` mounts the mobile API sub-application at the same path, so serving the SPA there would shadow a live API. Renaming the page or moving the mount to `/api/mobile` is a product choice.
- **Write this test first** tests/unit/test_every_spa_route_serves_the_app.py found both routes independently, without being told the finding existed, by asking whether a direct GET returns HTML. `/mobile` is exempted with its reason and pinned by test_the_mobile_collision_is_still_a_collision, so the exemption fails the day it stops being true.
- **Verify** `pytest tests/unit/test_every_spa_route_serves_the_app.py -q`
- **Skills** `ui-ux-pro-max`, `test-driven-development`
- **Full evidence** docs/audit/REMEDIATION_PLAN.md — Phase 6

#### F61/F107 · `BROKER_TYPE=oanda` cannot place an order

- **Priority** P1 · **Area** Brokers
- **Measured now** the adapter is written, maps OrderSide/long/short and refuses anything else rather than defaulting to SELL, and both startup paths refuse a connector that cannot place an order (pinned by tests). NOT venue-verified: every test runs against a stubbed place_order and nothing here has spoken to OANDA. Record a practice order in docs/VENUE_EVIDENCE.toml to close it — the probe reads that file, so this can reach FIXED without anyone editing the probe
- **Fix** Half done, deliberately. `AsyncOANDAConnector = OANDABroker` is still a bare alias with no `place_market_order`, but a test now makes that fail where someone can see it instead of at the first live order. Writing the adapter is a feature and needs a practice venue to test against: `place_order` takes `direction` ('long'/'short') and returns a dict, while the caller passes an `_OrderSide` and expects a `MarketOrderResult`. Guessed wrong, it places the opposite side. Live OANDA is the stated next milestone, so this is the gating item.
- **Write this test first** The existing loud-failure test stays; the adapter needs paper-venue contract tests for side, quantity and result shape before it is wired.
- **Verify** `pytest tests/unit/test_broker_type_oanda_is_not_silently_broken.py -q`
- **Skills** `hopefx-money-precision`, `systematic-debugging`
- **Full evidence** docs/audit/REMEDIATION_PLAN.md — Phase 3

#### F172 · Controls without an accessible name

- **Priority** P2 · **Area** Frontend
- **Measured now** 17 violation(s) across 12 file(s), measured by a parser rather than a regex and capped: the rule is an error everywhere except these files, so new debt fails `npm run lint`, and a11y_debt_is_accurate.test.ts refuses an entry that no longer describes anything. Fixing the rest is follow-up work
- **Fix** Was deliberately UNVERIFIED: two regex attempts each produced a confident wrong answer (one said FIXED across 552 buttons, the other found 9 offending files) because a JSX opening tag cannot be bracketed by a regex — an attribute may contain `>`, and `onClick={() => nav('/x')}` ends the match at the arrow. **Measured 2026-09-13 with a parser: 138 violations across 67 files.** `eslint-plugin-jsx-a11y` is now a devDependency and `jsx-a11y/control-has-associated-label` is an ERROR in eslint.config.js, downgraded to `warn` only for the files listed in `frontend/a11y-debt.json` — so a violation in any other file fails `npm run lint` and new debt cannot arrive quietly, while the existing 67 do not wall off a codebase nobody could then adopt the rule in. **Classified 2026-09-14, and the original framing was wrong:** exactly ONE of the 138 is a button (input 108, textarea 17, div 5, td 4, th 2, button 1, option 1), and 16 are controls already labelled by a sibling `<label htmlFor>` that a static rule cannot resolve. The title said icon-only buttons, so a successor would have gone looking for buttons and found one. **Auth flow cleared 2026-09-14** — Login (3), Register (4) and Profile (4) are off the list, 138 -> 127 across 64 files. Profile's three edit-form labels were bound to nothing and its avatar upload had no name at all; Login and Register were the false-positive shape and were made resolvable with `aria-labelledby`, not with a duplicated `aria-label`. The rest is follow-up work and is not this entry.
- **Write this test first** src/test/a11y_debt_is_accurate.test.ts runs eslint and compares it to the list entry by entry. Three refusals proven by injection: a listed file with no violations left must be DELETED from the list (otherwise the entry is a standing permission), a count that ROSE inside an already-listed file (invisible to eslint, since the whole file is downgraded), and a new violating file (which eslint also errors on independently). It uses spawnSync rather than execFileSync because eslint exits non-zero on this tree's 14 pre-existing errors from other rules, and a throwing call discarded the JSON and failed with 'Command failed' — a red for the wrong reason. src/test/auth_flow_controls_have_names.test.tsx asserts the other half, which the ratchet cannot: that the names RESOLVE in a DOM. A cleared debt entry only says the rule went quiet. Red-green — the Profile assertions fail on the pre-fix tree (git stash of the three pages), while Login and Register pass on it, which is the honest split: those two were already labelled and the change made the association machine-checkable.
- **Verify** `npm run lint · npx vitest run src/test/a11y_debt_is_accurate.test.ts src/test/auth_flow_controls_have_names.test.tsx`
- **Skills** `ui-ux-pro-max`
- **Full evidence** docs/audit/REMEDIATION_PLAN.md — Phase 6

#### F94 · Regime detection and position sizing

- **Priority** P2 · **Area** Quant
- **Measured now** the 0.5x unknown-regime multiplier is gone from risk/, and 31 module(s) consume a regime (e.g. core/analytics/realtime_heatmap.py), but no reference(s) reach risk/manager.py or risk/position_sizing.py. Whether sizing SHOULD be regime-aware is a strategy decision, so this is reported as measured rather than closed
- **Fix** The specific harm F94 named — an unrouted regime leaving every position at the 0.5x 'unknown' multiplier — is gone: no such multiplier exists in `risk/`. Regimes are consumed elsewhere (signal composition, analytics). Whether *sizing* should be regime-aware at all is a strategy question, not a defect, so this is reported as measured rather than closed. Decide it deliberately or close it.
- **Write this test first** If sizing becomes regime-aware: a test asserting the size differs between a known and an unknown regime, and that unknown is the conservative one.
- **Verify** `python scripts/correction_register.py --id F94`
- **Skills** `risk-metrics-calculation`
- **Full evidence** docs/audit/REMEDIATION_PLAN.md — Phase 3

#### OF-VOTER · One of three order-flow bias voters can never vote

- **Priority** P2 · **Area** Quant
- **Measured now** the voter declines knowingly rather than raising on every call, and the bias now carries its quorum (bias_voters / bias_voters_total), so a two-of-three majority cannot read as three. The vote itself is still absent: wiring it means choosing which of the analyzer's seven methods is a directional read, which is a quantitative decision and not a wiring fix
- **Fix** `OrderFlowDashboard._bias_vote_advanced` calls `self._adv.analyze(symbol)`. `AdvancedOrderFlowAnalyzer` has no `analyze` — its surface is `get_aggression_metrics`, `get_pressure_gauges`, `get_order_flow_oscillator`, `detect_delta_divergence`, `get_stacked_imbalances`, `get_volume_clusters` and `get_volume_imbalance_by_level`. Every call raises `AttributeError` into a handler that logs at WARNING and returns None, so `get_bias`'s majority is decided by two voters while reading as three. Wiring it stays a quantitative decision — choosing which of those seven methods is a directional read is a modelling choice, and picking one to make the count come out right would be inventing a signal, which is worse than declining to emit one. Two halves of it were NOT that decision and are fixed: the voter now checks for the capability and declines, warning once per process rather than raising `AttributeError` on every call; and `bias_with_quorum` plus `get_summary`'s `bias_voters` / `bias_voters_total` report how many of the three declared voters answered, so a consumer weighting this signal can see the quorum instead of reading a majority of two as a majority of three. `get_bias` is unrouted today — reachable only from `get_summary`, which nothing serves — so nothing acts on it yet.
- **Write this test first** tests/unit/test_order_flow_says_when_it_has_no_data.py carries three, all red against the pre-fix module: the voter declines without raising and warns exactly once across two calls, `bias_with_quorum` reports fewer voters than it declares, and `get_summary` carries the quorum beside the bias. The first was written as a grep for `self._adv.analyze(` and failed against the FIXED code, because the new docstring quotes the call it replaced — a text match tests how code is written, so it asserts behaviour instead.
- **Verify** `python scripts/correction_register.py --id OF-VOTER`
- **Skills** `hopefx-dead-controls`
- **Full evidence** This session, 2026-09-13 — found while covering order_flow_dashboard.py

#### AFF-TIER · A level upgrade advances one tier per conversion

- **Priority** P3 · **Area** Money
- **Measured now** still one tier per conversion — a commercial decision, not closed here. But the shortfall is now legible rather than silent: highest_qualifying_level() reports the tier the numbers earn and tiers_behind() reports the gap, so paying below it is a visible choice. Today's behaviour is pinned by a test that must be rewritten if the policy changes
- **Fix** `check_level_upgrade` walks the levels above the current one and returns the FIRST that qualifies, so an affiliate whose referral count and revenue already clear a higher tier is granted only the next one up. They earn the lower commission rate until the following conversion triggers another check — bronze to platinum is three conversions at 10%, 15% and 20% before the 25% their numbers already earned. Whether tiers should be skippable is a COMMERCIAL decision rather than a bug, and is not made here; today's behaviour is pinned by a test that must be rewritten if the policy changes. What was not a commercial decision, and is fixed: the shortfall was invisible. The method's name and signature gave a caller no way to tell 'the next step' from 'the level they qualify for', so an affiliate was under-paid by omission rather than by policy. `highest_qualifying_level()` now reports the tier the numbers earn and `tiers_behind()` the gap, so paying below it is a visible choice someone can price.
- **Write this test first** tests/unit/test_affiliate_commissions_conserve.py carries five: today's one-step policy is pinned by name, the earned tier and the gap are asserted against it, a control proves an up-to-date affiliate reports no gap, and two guard the arithmetic — that BOTH thresholds are required (`and` becoming `or` is a one-character change that raises every commission rate and would pass everything else) and that a tier is earned exactly AT its threshold. Four fail against the pre-fix module.
- **Verify** `python scripts/correction_register.py --id AFF-TIER`
- **Skills** `hopefx-money-precision`
- **Full evidence** This session, 2026-09-13 — found while covering affiliate.py

#### F175 · Emoji used as UI icons

- **Priority** P3 · **Area** Frontend
- **Measured now** 750 emoji across 125 files remain, capped: the ratchet is wired into pre-commit and proven able to fail, so the number can only go down. CommandPalette's 60 are gone — its hand-written nav list, which had drifted from NAV_ITEMS (Dashboard to /home, 2FA Setup to a route that does not exist, eleven sidebar pages never added), is now derived from NAV_ITEMS with its Lucide icons. Converting the remaining 154 files is a codemod and an owner decision
- **Fix** The plan recorded this as done for `frontend/src` — 'no source file carries emoji'. It was not: 1,389 across 145 files on 2026-09-13, concentrated exactly where icons live (PlatformConfiguration.tsx 136, SystemReliabilitySection.tsx 62, Settings.tsx 52). `ui-ux-pro-max` forbids emoji as icons and navConfig.ts already records the cost (F170): no `currentColor`, so they ignore theme, hover and disabled state; per-platform rendering; announced literally by a screen reader. Capped by a ratchet rather than closed by a 154-file codemod, which is the owner's call.
- **Write this test first** Carried by test_frontend_emoji_ratchet.py (five injections plus the exclusion test that keeps 79,148 box-drawing characters out of scope) and command_palette_follows_nav.test.tsx (the palette follows NAV_ITEMS and renders no emoji; four of its five assertions fail against the pre-fix component).
- **Verify** `python scripts/correction_register.py --id F175`
- **Skills** `ui-ux-pro-max`
- **Full evidence** docs/audit/REMEDIATION_PLAN.md — Phase 6

### OWNER — 7

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
- **Measured now** the block path exists; code defaults DRIFT_BLOCK=false, MODEL_QUALITY_BLOCK=false, DRIFT_Z_THRESHOLD=4.0, while 4 of 4 deployment surface(s) set DRIFT_BLOCK=true and the deployed chart sets DRIFT_Z_THRESHOLD=3.0, not 4.0. ADR 0019 is proposed, not accepted — the decision is the owner's and the measured z is dominated by zero-filled features (python scripts/drift_guard_report.py)
- **Fix** The block path exists and works — proven in both directions by injection — but the code default ships false while all four deployment surfaces set it true. Recorded for decision in ADR 0019, which also carries the two riders this finding omitted: `MODEL_QUALITY_BLOCK` is advisory for the same reason and its own comment ties it to this default, and `DRIFT_Z_THRESHOLD` is 4.0 in code against 3.0 in the deployed chart. The decision is not the one-line flip it looks like: measured 2026-09-13, 12 of the 14 features over the threshold had a live value of exactly 0.0, because a feature the pipeline cannot supply is zero-filled before the guard sees it. The guard is largely measuring imputation, so blocking on it today converts a feed outage into a total trading halt reported as `feature_drift`. Separate the two before flipping the default — `python scripts/drift_guard_report.py` shows the split.
- **Write this test first** Whichever default is chosen: a test that shifts a feature past the z-threshold and asserts the configured behaviour — and one that asserts a zero-filled feature is not counted as drift, which is the half that decides whether blocking is safe.
- **Verify** `python scripts/correction_register.py --id F146`
- **Skills** `hopefx-dead-controls`
- **Full evidence** docs/audit/REMEDIATION_PLAN.md — Phase 1

#### F95 · GitHub Actions does not run — every gate below is unverified until it does

- **Priority** OWNER · **Area** CI
- **Measured now** account-level; no repository change can clear it
- **Fix** Not fixable from code. Check GitHub → Billing → Actions. Runs end with no runner assigned, which is the billing signature.

**Confirmed against the API 2026-09-13**, so this is measured rather than inferred. Run 34780841624 on PR #315 (head 3cc8e217): 68 checks, every one `failure`, the whole run created and closed in 39 seconds — individual jobs in ONE TO THREE seconds. `GET /actions/jobs/103787449312` returns `runner_id: 0`, `runner_name: ""`, `runner_group_id: 0`, and the job log 404s because nothing ever ran. Workflow runs ARE still being created — this one is run_number 5740 — so Actions is not disabled; no job reaches a machine.

The practical consequence is worth stating plainly, because 68 red checks read as 68 defects: **none of them is a code failure, and a green PR is currently unreachable by any change to this repository.** A week-old batch of the same failures (SHAs e55fcc37 and 067086ea, 2026-09-06) shows the identical 1-3 second signature, so nothing has executed in at least that long either.
- **Write this test first** None — this is an account setting, not a behaviour.
- **Verify** `Observe a green `ci.yml` run on a fresh push.`
- **Skills** `verification-before-completion`
- **Full evidence** docs/audit/REMEDIATION_PLAN.md — Phase 0

#### MODEL-166-DAYS-OLD · The model the platform ships is months past its own freshness limit

- **Priority** OWNER · **Area** ML
- **Measured now** the shipped model is 170 days old against a 30-day limit
- **Fix** Not a new defect; a fact the old gate was hiding. With age read from the artifact's sha256-bound provenance rather than its mtime, the committed advanced_oos.pkl measures 166 days old against MODEL_MAX_AGE_DAYS=30, while the mtime the gate used to read said 0.69 days — the file having been written by the clone. Four registry versions (advanced_oos_v1/v2, xgb_horizon5_v1/v3) carry the SAME sha256, so the bytes have not changed since 2026-04-01 whatever they were re-registered as; even taking the latest of those four (2026-06-26) the model is 80 days old, so it is past the limit on any reading. STALE_MODEL_BLOCK defaults to true, so with this fix in place inference is refused until the situation is resolved. That is the gate doing its job, and it is why this is recorded rather than quietly worked around: lowering the check or raising MODEL_MAX_AGE_DAYS to make the platform trade again would restore exactly the behaviour the fix removed. Three ways out, and all three are the owner's to choose: retrain and register a model; decide 30 days is the wrong limit for this strategy and change it deliberately, with the reason recorded; or run with MODEL_MAX_AGE_DAYS=0 in a non-trading deployment. This entry reports OWNER until the measured age is inside the limit, and it cannot be closed by editing a document.
- **Write this test first** No test — a test asserting the model is fresh would fail for a true reason and be deleted. The probe measures the shipped artifact directly, so it closes itself when a current model is registered.
- **Verify** `python scripts/correction_register.py --id MODEL-166-DAYS-OLD`
- **Skills** `verification-before-completion`
- **Full evidence** This session, 2026-09-14 — surfaced by fixing MODEL-AGE-IS-MTIME

#### MODEL-PROVENANCE-DISAGREES · Two records disagree by nearly three months about when the same bytes were trained

- **Priority** OWNER · **Area** ML
- **Measured now** the meta file and the registry disagree by 87 days about the same bytes
- **Fix** `advanced_oos_meta.json` gives `validated_at` 2026-06-26; the earliest `registry.json` version carrying the artifact's sha256 gives 2026-04-01 — the same bytes, and the probe above states today's gap rather than a figure typed here that would drift. Nothing had ever compared them, and the mtime the staleness gate used to read (0.69 days) agreed with neither, which is why the disagreement was invisible. It is now visible in one payload: `health()` reports `last_trained_at` 2026-06-26 from the meta file beside `model_age_days` 166.75 from the registry, and `MlSafetyStrip.tsx` renders the former as "Trained: 26/06/2026" next to a stale badge — an operator reading that screen saw a model trained twelve weeks ago flagged stale at twenty-four. Engineering has done what it can without deciding: `health()` now also reports `model_provenance_at`, the timestamp the gate actually blocked on, so the age it enforces is attributable rather than a third unexplained figure — and both screens that render a training date (`MlSafetyStrip.tsx`, `ModelHealthWorkspace.tsx`) now show THAT date, falling back to the meta file's only when the gate reports no provenance, so the date on screen is the one the platform acted on. Which record is right is an ML-side call — most likely `validated_at` means validated rather than trained, in which case the artifact needs a real `trained_at` — and picking one silently would be engineering deciding what a model's age means.
- **Write this test first** tests/unit/test_health_states_one_model_age.py — three tests, red before the fix: the payload must name the timestamp the gate used, the age must be arithmetic on it, and unusable provenance must be reported as unknown WITH a reason rather than omitted. frontend/src/test/the_trained_date_matches_the_staleness_claim.test.tsx — three more, for the screen: it must prefer the gate's date, fall back to the meta file's when there is none, and show nothing rather than a wrong date when neither is known.
- **Verify** `python scripts/correction_register.py --id MODEL-PROVENANCE-DISAGREES`
- **Skills** `test-driven-development`, `verification-before-completion`
- **Full evidence** This session, 2026-09-14 — surfaced by fixing MODEL-AGE-IS-MTIME

#### SEC-ROTATE · Rotate the credentials exposed outside the repository

- **Priority** OWNER · **Area** Security
- **Measured now** credential rotation is an account action outside the repository
- **Fix** Two credentials. (a) The superadmin credential named in the AI Core spec as item 6 — 'above everything in this plan'. Its location is still unconfirmed: the tracked working tree reads as placeholders, so the file or commit holding it has to be named before it can be rotated. (b) A Vercel token (`vck_…`) was pasted into a chat session. It was never written to disk or into any commit — verified — but it left the machine, so it must be rotated. The tracked working tree reads as placeholders; `prop_firm_mode.json` and `.env.example` are committed deliberately and must stay placeholder-only.
- **Write this test first** None — this is a credential action, not a behaviour.
- **Verify** `detect-secrets scan (already in pre-commit)`
- **Full evidence** docs/audit/REMEDIATION_PLAN.md — spec item 6; this session

### FIXED — 83

#### A8 · Two committed model artifacts fail the integrity baseline that gates their load

- **Priority** P0 · **Area** ML
- **Measured now** all 11 listed artifacts match their recorded sha256
- **Fix** `feature_scaler.pkl` and `stacking_ensemble.pkl` do not match the sha256 recorded in `ml/saved_models/model_checksums.json`. That file is not decorative: `ml/__init__.py::_verify_checksum` reads it on every load and, in production, returns False rather than bootstrapping — so `_try_load` returns None and the artifact is simply absent to the caller. Two consequences to fix together. (a) **Settled 2026-09-13 by git history, not by asking.** The manifest has ONE commit (`334e50f3`) and the artifacts hash to `d20ee7a6…`/`4714e96b…` AT THAT COMMIT while it records `b236e4aa…`/`dc33b5a1…` — so it never described any committed version of these files; it was wrong the moment it was written. The bytes on disk are neither the manifest's nor the leak's (`05efdbab`): they are `776b59cf`, *fix(ml): a missing feature reaches the model as neutral, not as -15 sigma (F145)* — a named, deliberate regeneration. So there was nothing to restore, and re-recording blesses a deliberate fix rather than an accident. Both entries re-recorded; `_verify_checksum` under APP_ENV=production went False -> True for both, verified by execution before and after. The evidence the two ever disagreed now lives here and in the commit, which is what the earlier caution was protecting. **Closed 2026-09-14.** `lstm_signal.pt` was listed and never committed. Inert to _verify_checksum, which only reads files that exist — but strictly MORE permissive than not listing it: in production an unlisted file is refused outright (MODEL NOT IN INTEGRITY BASELINE) while a listed one loads if its bytes match the recorded hash, so a record for a file nobody has ever shipped is a pre-approved load. It is a training target of `scripts/train_lstm_signal.py` and the only other use of the name is a training-job label in `api/ml.py`, so the entry went rather than the file arriving. All 11 remaining entries were then run through `_verify_checksum` under APP_ENV=production and all 11 returned True. (b) **Done 2026-09-13 — this half was never an owner decision.** `ml/advanced_predictor.py` guarded `if self._meta_scaler is not None`, so a refused or absent scaler removed the transform and fed RAW probabilities into a Ridge fitted on standardised ones. Its coefficients are in units of standard deviations from the training mean, so the output is not a probability of anything — and it was clipped into [0,1] and returned as the ensemble's answer. Success reported for work that did not happen, on the money path, behind a guard that reads like an ordinary None check. The blend is now extracted into `_blend_probabilities`; an unusable meta-blender falls through to the weighted average — the path this ensemble used before the blender existed, so it is a fallback rather than a halt — and logs at ERROR once per process instead of passing silently. `_try_load` still returns None identically for absent and refused, which matters less now its most consequential caller refuses rather than degrading. What REMAINS for the owner is (a): which side of each mismatch is wrong. Meanwhile `scripts/model_provenance_report.py --check` ratchets the surrounding debt — 12 ungated loaders, 7 unlisted artifacts — so it cannot grow while (a) is open, and deliberately does not block on the mismatches.
- **Write this test first** `tests/unit/test_model_artifact_manifest_gate.py::test_the_manifest_describes_exactly_what_ships` — fails on the pre-fix tree with `['lstm_signal.pt'] are recorded ... but do not ship`. It asserts both directions, because an artefact that ships WITHOUT an entry is the 7-unlisted debt and this must not quietly permit a new one. Still uncovered, and still worth writing: an injection test that corrupts a committed artefact and asserts the caller can tell refusal from absence.
- **Verify** `python scripts/correction_register.py --id A8`
- **Skills** `hopefx-dead-controls`
- **Full evidence** docs/ai/MASTER_OUTSTANDING.md §A8

#### AML-UNREACHED · Every AML withdrawal rule is unreachable in production

- **Priority** P0 · **Area** Compliance
- **Measured now** the withdrawal path consults the AML gate (api/payments.py, payments/wallet.py) and the ledger it counts against is written
- **Fix** `compliance/aml.py::check_withdrawal` enforces a single-transaction cap, a daily withdrawal count, a daily volume limit and sanctions/PEP screening. It is built correctly and wired correctly — `core/startup_factories.py::init_aml` hands it a session factory through the registered `aml` component — and it is never consulted. The gate itself was proved to work, called directly against a populated ledger: a 40,000 withdrawal was refused by the 10,000 single cap, and a 100 withdrawal was refused after six same-day rows by the 5-per-day rule. The defect is reachability, and it is doubled. `check_withdrawal` has exactly one production call site — `payments/wallet.py::debit_wallet` — inside the class WALLET-DEAD shows nothing calls. And the live endpoint that withdraws money, `POST /payments/withdraw`, never mentions it: it checks KYC through a dependency, a minimum amount and a rate limit, and returns. What is NOT true today is that money leaves unscreened — that endpoint is documented NOT YET PERSISTED, queues nothing and disburses nothing. That is exactly why this is worth fixing now rather than later: the day `FIAT_PROVIDER` is configured and the endpoint is made real, it would have disbursed without ever touching the gate, and the gate would still have looked wired at startup to anyone who read it. **Half-closed 2026-09-13**: `api/payments.py::_screen_withdrawal_for_aml` now consults the gate before the endpoint returns, refusing with a 403 carrying the gate's own reason. Strictness mirrors `require_kyc`, which guards the same endpoint — reject in production when the gate cannot be reached, pass through in development where nothing wires one, `HOPEFX_REQUIRE_AML_STRICT` overriding either way. The amount crosses as `Decimal(str(x))`, because the gate compares against Decimal thresholds. The single cap and sanctions/PEP screening therefore fire today. The daily count and volume rules still cannot, and no amount of work on this endpoint will change that: they read `wallet_transactions`, which nothing writes while WALLET-DEAD stands. That is why this reads PARTIAL rather than FIXED.
- **Write this test first** `tests/unit/test_withdrawal_is_screened_by_aml.py` — six of its ten tests fail on the pre-fix tree. A spy proves the call happens; a real `AMLGate` over a real session factory, driven through the endpoint, proves the refusal is real. The pair that pass both ways are controls: a sub-minimum request is still rejected on its own terms without consulting the gate, and a withdrawal under every limit is still allowed, so a gate that refused everything could not pass as a fix.
- **Verify** `python scripts/correction_register.py --id AML-UNREACHED`
- **Skills** `hopefx-dead-controls`, `test-driven-development`
- **Full evidence** Found while measuring WALLET-DEAD

#### CHART-GATE-VACUOUS · The deployed-chart safety gate emptied itself on the repoint it exists to catch

- **Priority** P0 · **Area** Config
- **Measured now** every synced path is resolved to (env, manifests) whether or not it is a chart, and a second positive control fails when a synced path yields neither
- **Fix** DEPLOY-CHART's suite proves the chart ArgoCD syncs states all three safety keys and ships the kill switch. Its header claimed it 'follows `spec.source.path` rather than naming a directory, so repointing ArgoCD moves the assertions with it instead of silently emptying them'. It did not: `_charts()` filtered synced paths to those containing a `Chart.yaml`, and every assertion iterated that list, so a path without one produced an EMPTY list and each `assert not missing` passed over nothing. Measured by repointing `spec.source.path` — `docs` (no manifest, no posture) and `invariants` (no yaml at all) BOTH left all seven tests green, and those are the original P0 exactly: ArgoCD syncing a path that carries none of the safety posture. `deployments/k8s` also passed, having checked nothing. Fixed by resolving every synced path to (env, manifests) — from values.yaml for a chart, from ConfigMap data and container env for a plain directory — and adding a second positive control, because the first asserts only that some Application names a directory and `docs` satisfies that.
- **Write this test first** tests/unit/test_the_deployed_chart_carries_the_safety_posture.py — `test_every_synced_path_is_checkable` is the new control. Red-green by repointing at the fixed revision: docs 7 pass -> 5 fail, invariants 7 pass -> 6 fail, deployments/k8s 7 pass -> 8 pass and now actually read. Every repoint was injected, measured and reverted; the two deployment files are byte-identical to before.
- **Verify** `python scripts/correction_register.py --id CHART-GATE-VACUOUS`
- **Skills** `hopefx-dead-controls`, `verification-before-completion`
- **Full evidence** This session, 2026-09-14 — found while confirming DEPLOY-CHART by injection

#### CHAT-SHARED-HISTORY · One conversation per worker, shared by every user on it

- **Priority** P0 · **Area** Security
- **Measured now** keyed on (authenticated sub, session label), serialised, bounded and expiring
- **Fix** POST /api/brain/chat held a module-level `_chat_agent`, built on first use and reused for every request in the worker. LLMAgent keeps the conversation on the instance, and nothing about the authenticated caller chose which instance answered, so one worker had one history shared by everyone on it. Reproduced by calling the endpoint function with two identities and a recording backend: user A's "my account number is 9137-SECRET-ALPHA" appeared verbatim in the outgoing prompt sent on behalf of user B. On this platform that box holds balances, positions, strategy and intent, so it is a confidentiality defect rather than untidiness. Conversations are now keyed on (authenticated `sub`, client session label) — the subject first, because a session id is a label the client picks and keying on it alone would let anyone read another user's history by guessing one, or by two clients both defaulting to the same string. `ChatRequest` still carries no user field, for the same reason. Each conversation has its own lock (LLMAgent.chat appends the user turn, awaits, then appends the reply, so concurrent requests interleave into a history whose turns do not alternate), the registry is LRU-bounded, idle conversations expire, and a token with no subject is refused rather than falling back to a shared agent.
- **Write this test first** tests/unit/test_chat_history_is_per_user.py — ten tests, each injection-proven. Two of them were rewritten for proving nothing: the concurrency test took the lock inside the TEST body, so it still passed with the lock deleted from the endpoint (it was proving that asyncio.Lock works), and the clearing test popped a key from the registry dict and asserted the other was still there, which tests dict.pop. Both now drive the endpoint. A tenth walks the route's dependency chain to `get_current_user`, because every other test supplies a TokenPayload directly and would keep passing if the route were ever handed a shared or body-supplied identity.
- **Verify** `pytest tests/unit/test_chat_history_is_per_user.py -q`
- **Skills** `test-driven-development`, `verification-before-completion`, `hopefx-dead-controls`
- **Full evidence** External audit of 40cb9419, 2026-09-14 — reproduced here before the fix

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
- **Measured now** payments/wallet.py:119: return f"TXN-{datetime.now(UTC).strftime('%Y%m%d')}-{uuid.uuid4().hex[:8].upper()}"
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
- **Measured now** 4 production caller(s): invariants/enforcement.py:78: verify_balance_after,
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
- **Measured now** creator ledger writes through a session factory, and startup wires the singleton to it through the registered revenue_ledger component
- **Fix** Done, in two halves. The write-through, the three ledger tables and the reload landed first. They then ran nowhere: `revenue_engine = RevenueSplitEngine()` was built with no session factory and nothing assigned one, so `if not self._session_factory: return` was taken on every write and a restart still erased every creator balance — the persistence was complete, correct and unreachable, and this probe read FIXED throughout because it only asked whether the code existed. `monetization.revenue_split.init_revenue_engine` now wires the singleton and reloads its working set, `core.startup_factories.init_revenue_ledger` calls it, and the `revenue_ledger` component registers it after `database`. The probe measures both halves, and `tests/unit/test_creator_ledger_is_actually_persisted.py` executes them rather than grepping for them.
- **Write this test first** `tests/unit/test_creator_ledger_is_actually_persisted.py` — four of its six tests fail on the pre-fix tree; the two that pass are controls proving the persistence layer itself worked and only the wiring was missing.
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

#### F31/F32 · Affiliate money state is in memory, and the payout is a TOCTOU

- **Priority** P0 · **Area** Money
- **Measured now** affiliate commissions are conserved, serialised and persisted — the ledger writes through to affiliates/affiliate_referrals/affiliate_payouts, and startup wires the singleton through the registered affiliate_ledger component
- **Fix** **Money conservation is fixed** (2026-09-13). Three ways commission left the ledger without being paid, all reproduced before the fix and all now covered by `tests/unit/test_affiliate_commissions_conserve.py`: (1) `request_withdrawal` tested its running total *before* adding each referral, so the one that crossed the requested amount was marked PAID in full — two 60.00 commissions against a 100.00 withdrawal **destroyed 20.00**, deterministically, behind a live endpoint at `api/monetization.py:1542`; (2) a conversion landing between a payout's total and its settlement pass was settled without being in the total — **70.00 destroyed**, F203's shape one module over; (3) two concurrent payout requests each saw the full balance — **300.00 paid against 150.00 earned**. Referrals now carry `commission_paid` so a withdrawal can settle part of one, and both payout paths plus `convert_referral` hold an `RLock` across the whole read-modify-write. **Persistence landed 2026-09-13.** Three tables (`affiliates`, `affiliate_referrals`, `affiliate_payouts`) with `Numeric(18, 2)` money and a migration, a write-through on every mutation — the payout and the referrals it settled in one transaction, so a payout cannot land without them — a reload that rebuilds the code and user-id indexes as well as the records, and `init_affiliate_manager` wired by the registered `affiliate_ledger` component. That last part is the half F208 proves is not optional: the creator ledger's identical write-through ran nowhere for months because nothing handed the singleton a factory. Adding the `Numeric(18, 2)` columns also exposed AFF-CENTS — the commission carried a fraction of a cent that could never be paid.
- **Write this test first** For the remaining half: credit a commission, rebuild the manager from its store, and assert the balance survived. It will fail today.
- **Verify** `python scripts/correction_register.py --id F31/F32`
- **Skills** `hopefx-money-precision`
- **Full evidence** docs/audit/REMEDIATION_PLAN.md — Phase 2

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

#### MODEL-AGE-IS-MTIME · Deploying a stale model was how the staleness gate got cleared

- **Priority** P0 · **Area** ML
- **Measured now** age comes from a sha256-bound timestamp in registry.json
- **Fix** `_check_model_staleness()` measured the artifact's filesystem mtime. Reproduced against a disposable file: a 90-day-old artifact reported stale=True age=90.0; the SAME BYTES with the timestamp touched reported stale=False age=0.0, with no retraining. Every ordinary operational act writes that timestamp — git checkout, docker build, cp -r, rsync without -t, restoring a backup — so the gate that exists to stop the platform trading on an out-of-date model was cleared by the act of deploying the out-of-date model. It failed in the unsafe direction and silently. Age now comes from a timestamp bound to the artifact's sha256 in registry.json, which makes it a property of the BYTES: `trained_at` preferred, `registered_at` as the fallback (today's registry records only the latter, and it is still sha-bound and still immune to a touch). Where several versions carry the same digest the EARLIEST wins — re-registering unchanged bytes under a new version is the same defect wearing a different hat, and the earliest date can only make a model look older. Every way provenance can be unusable — absent, malformed, not matching the bytes, or future-dated beyond clock skew — reports STALE, so STALE_MODEL_BLOCK blocks, which is the right answer to "I cannot tell you how old this model is". SEE MODEL-166-DAYS-OLD: turning this on revealed that the committed model is well past the limit, which the mtime had been hiding.
- **Write this test first** tests/unit/test_model_age_is_training_age.py — fifteen tests, twelve of which fail when the mtime read is put back. Two existing tests asserted the defect (test_fresh_file_returns_false, test_fresh_model_not_stale: a just-written file with no provenance was "fresh") and were rewritten with what they used to claim recorded in the docstring, not deleted.
- **Verify** `pytest tests/unit/test_model_age_is_training_age.py tests/unit/test_inference_engine.py tests/unit/test_ml_inference_engine.py -q`
- **Skills** `test-driven-development`, `verification-before-completion`, `hopefx-dead-controls`, `systematic-debugging`
- **Full evidence** External audit of 40cb9419, 2026-09-14 — reproduced here before the fix

#### ROUTER-OVERRULE · A router policy denial was overruled by the engine that asked for it

- **Priority** P0 · **Area** Brokers
- **Measured now** a router policy denial is terminal on the fallback path; only an allow-listed transport gap may still place directly
- **Fix** `hopefx_engine._execute_decision` falls back to a direct `broker.place_order` when ExecutionEngine is unavailable. On that path it called SmartRouter and then did this: if the status was `rejected` or `error`, log a warning and place the order anyway. `rejected` is not only 'no venue was reachable' — `execution/smart_router.py` returns it for five POLICY denials: `unauthorized:…` (enforce_order_authorization refused, logged CRITICAL as 'Router BLOCKED order', under a comment reading *no order may reach a broker without a risk-approval token + decision id*), `spread_too_wide:…`, `sentiment_blackout:…`, `macro_impact_blackout:…` and `fia_throttle:…` (FIA 3.4). All five were followed by the order reaching the broker. The purest `hopefx-dead-controls` shape: the control fires correctly and the caller ignores it. The path runs only when ExecutionEngine is unavailable, which makes it rare rather than safe — the 12-check pre-trade gate is absent there too, so the router's verdict was the last policy control standing. Fixed by classifying the refusal: `_router_refusal_is_terminal` allow-lists the transport GAPS (`no_brokers_available` — nothing transmitted, and the pre-route gates already passed to reach it) and treats everything else as terminal. An allow-list, not a deny-list, so a policy reason added to the router later is terminal by default rather than silently overruled. `all_brokers_failed:…`, `timeout:…` and an exception out of the router are terminal too: a broker was reached, so an order may be in flight and sending another is the duplicate fill ROUTER-TO exists to prevent — recovering those needs order-identity reconciliation, not a retry.
- **Write this test first** `tests/unit/test_router_policy_denial_is_terminal.py` — 17 of its 20 tests fail on the pre-fix tree. They drive the real `_execute_decision` with a spy broker rather than re-implementing its branch. The 3 that pass both ways are controls: a policy-clean transport gap must STILL be able to place (otherwise 'never trade' passes every other test), a routed fill must not be sent twice, and the reason strings asserted here are checked to be strings the router really produces rather than fiction.
- **Verify** `python scripts/correction_register.py --id ROUTER-OVERRULE`
- **Skills** `hopefx-dead-controls`, `test-driven-development`
- **Full evidence** Found 2026-09-14 from an external source-inspection review (M03), then reproduced here

#### ROUTER-TO · A fallback broker timeout re-routed and risked a duplicate fill

- **Priority** P0 · **Area** Brokers
- **Measured now** 2 TimeoutError clause(s) — the fallback loop must stop the chain, not re-route
- **Fix** Done: a timeout in the fallback loop stops the chain. A timeout is not a confirmed failure, so the order outcome is unknown and re-routing can place a second live order.
- **Write this test first** tests/unit/test_brokers_smart_router_coverage.py::TestExecuteWithFallback::test_a_fallback_timeout_does_not_place_a_second_order
- **Verify** `pytest tests/unit/test_brokers_smart_router_coverage.py -q`
- **Skills** `hopefx-money-precision`, `hopefx-dead-controls`
- **Full evidence** This session, 2026-09-13 — commit 12bef2bb

#### WALLET-DEAD · The wallet ledger has no production consumer, so `wallet_transactions` is never written

- **Priority** P0 · **Area** Money
- **Measured now** the wallet ledger has 2 production consumer(s): api/billing.py, api/payments.py
- **Fix** `payments/wallet.py::WalletManager` is 700 lines of correct, tested, exact-Decimal ledger — balance validation, a rollback when the ledger write is refused, freeze and transfer paths — and no production module uses it. Measured by an exhaustive sweep of every tracked `.py`: the only references are its own module, the `payments/__init__.py` export, `core/app_state.py` declaring the slot as `None`, and `core/startup_factories.py::init_wallet`, which builds one into `app_state.wallet_manager` that nothing ever reads. Dynamic access was checked too — no string form of the name appears anywhere. This is `portfolio/pms.py`'s shape (F158), not F208's: the module is not merely unwired, it is unreferenced. The user-facing surface reads elsewhere — `/billing/balance` reads the broker account and the subscription manager, `/billing/transactions` reads Stripe and subscription events. So `WalletManager` is the only production writer of `wallet_transactions`, and it never runs: the table is permanently empty, which is what makes AML-UNREACHED's daily rules unfireable and what `health_check_service.py` aggregates to zero. The fix is a decision, not a refactor: either the wallet becomes the ledger the withdrawal path writes through, or it is retired and AML and the health check are pointed at whatever is authoritative instead. Deleting it silently is the one wrong answer — the AML rules would then read an empty table with nothing left to explain why.
- **Write this test first** Assert a production caller exists: drive a withdrawal through the API and assert a row lands in `wallet_transactions`. It will fail today, at the point where there is no path from any endpoint to the ledger.
- **Verify** `python scripts/correction_register.py --id WALLET-DEAD`
- **Skills** `hopefx-money-precision`, `hopefx-dead-controls`
- **Full evidence** Found while wiring the creator and affiliate ledgers (F208, F31/F32)

#### AFF-CENTS · An affiliate commission carried a fraction of a cent that could never be paid

- **Priority** P1 · **Area** Money
- **Measured now** commissions are quantized to cents with ROUND_HALF_UP where they become authoritative
- **Fix** `Referral.convert` stored `subscription_amount * commission_rate` raw. Decimal multiplication keeps every digit, so 10% of 3,333.33 was 333.3330. Reproduced with no concurrency and no database: withdrawing the 333.33 that *can* be paid left 0.0030 outstanding, which is below MIN_PAYOUT (100.00) so no withdrawal could ever take it, and which kept `outstanding_commission` above zero so the referral never reached PAID — it sat in the CONVERTED working set permanently, showing the affiliate a pending balance they could not withdraw. The new `Numeric(18, 2)` ledger columns exposed the same defect from the other side: storage truncated 333.3330 to 333.33, so the database and memory disagreed about what was owed. Fixed by quantizing to cents with ROUND_HALF_UP where the commission becomes authoritative, matching `monetization/revenue_split.py`. `round()` would round half to even, which is not how money rounds.
- **Write this test first** `tests/unit/test_affiliate_commission_is_payable_in_cents.py` — eight of its ten tests fail on the pre-fix tree, including the stranding reproduction above.
- **Verify** `python scripts/correction_register.py --id AFF-CENTS`
- **Skills** `hopefx-money-precision`, `test-driven-development`
- **Full evidence** Found while adding the affiliate ledger tables (F31/F32, second half)

#### AGENT-DEADLINE-UNENFORCED · An agent run that blew its deadline reported success

- **Priority** P1 · **Area** AI
- **Measured now** one absolute deadline, rechecked after planning and after each tool call
- **Fix** `run_loop` checked the clock at the TOP of each step and nowhere else, so the budget bounded when work was allowed to START rather than when it had to be finished. Reproduced with a planner that consumed 2s against a 1s budget: completed=True, stopped_reason="planner_finished". That is worse than a late answer — `completed` is what a caller reads to decide whether to act on the run, and `_remember()` writes it to memory, so a run that blew its deadline became a successful precedent for the next one. There is now one absolute deadline computed once (not re-derived per step, which would let N steps of just-under-the-limit each pass while the run ran N times over), rechecked after the planner returns and after every tool call, and `LoopContext.remaining_seconds` tells the planner how long it has so an overrun can be avoided rather than only detected. What it deliberately does NOT claim is cancellation: Python cannot interrupt arbitrary synchronous code, and a thread timeout only abandons the waiter while the work continues — and a tool handler here may be mid-way through a broker or database call, so abandoning one is worse than waiting. The loop bounds what it STARTS and what it ACCEPTS, and says so. The remaining time is NOT given to tool handlers, which is a deliberate gap: `ToolBus.invoke` forwards `**context` straight to `registered.handler(**context)`, so an extra keyword raises TypeError in every handler that does not declare it — every tool on the platform. Doing it properly needs an opt-in on the registration the way `wants_operator` already works, which is a change to the tool contract rather than to this loop. An earlier draft of the fix CLAIMED in a comment that handlers were told; that comment was false and is corrected, because a note describing a mechanism that does not exist is the same defect class as a gate that does not run.
- **Write this test first** tests/unit/test_agent_deadline_is_enforced.py — nine tests. Four injections were run; one of them (removing the post-tool recheck) initially passed all of them, which made that branch a control no test held, so a ninth test was added for what it actually changes: the audit record. It now fails under that injection.
- **Verify** `pytest tests/unit/test_agent_deadline_is_enforced.py tests/unit/test_agentic_loop.py -q`
- **Skills** `test-driven-development`, `verification-before-completion`, `hopefx-dead-controls`
- **Full evidence** External audit of 40cb9419, 2026-09-14 — reproduced here before the fix

#### AI-GATE · Two acceptance tests the AI layer must not ship without

- **Priority** P1 · **Area** AI authority
- **Measured now** scope: tests/unit/test_agent_actions_are_enforced_not_prompted.py · approval: tests/unit/test_agent_actions_are_enforced_not_prompted.py · enforced through the bus: tests/unit/test_ai_tool_bus.py
- **Fix** Adopt both before writing more agent code: an agent calling an action outside its scope must FAIL THE BUILD, and a proposal executing without an approval record must fail the build. `enforce_agent_action` and `ToolBus.invoke` already run outside tests, so this is about keeping them enforced as the layer grows — without these, the spec's approval queue is the same shape as F176: a control described accurately and enforced by convention. Note the inherited prerequisites, each tracked here: the AI kill switch depends on F139 (now fixed), and the agent sandbox on F130 (open — unsigned patches) and F184 (fixed).
- **Write this test first** The two tests are the deliverable. Write them red: grant an agent a narrow scope, call outside it, assert refusal; submit a proposal with no approval record, assert it does not execute.
- **Verify** `python scripts/correction_register.py --id AI-GATE`
- **Skills** `hopefx-dead-controls`, `hopefx-invariants`, `threat-modelling`
- **Full evidence** docs/audit/REMEDIATION_PLAN.md — AI Core section

#### AI-SURFACE · Superadmin surface must differ by capability, not by a UI branch

- **Priority** P1 · **Area** AI authority
- **Measured now** server-side capability enforcement is pinned with a 403 assertion
- **Fix** Done for the enforcement half: server-side capability is pinned with a 403 assertion. The remaining work is structural — separate components rather than `if (isSuperAdmin)` branches, plus the direct-GET probe from F198 applied to the operator routes, so an unprivileged user cannot reach an admin view by typing its URL.
- **Write this test first** A 403 test per privileged endpoint, and a direct-GET probe per operator route.
- **Verify** `pytest tests/unit/test_superadmin_capabilities_are_server_enforced.py -q`
- **Skills** `threat-modelling`, `ui-ux-pro-max`
- **Full evidence** docs/audit/REMEDIATION_PLAN.md — AI Core section

#### DRIFT-ABSENCE · A feed outage was scored as feature drift

- **Priority** P1 · **Area** ML
- **Measured now** absence and drift are counted apart, z_max is over measured features only, absence is logged at ERROR and both counts are on the status payload. Whether absence should itself halt inference is a separate gate and is the owner's call (DRIFT-ABSENCE)
- **Fix** `_check_feature_drift` scored every feature as `|live - train_mean| / std`. A feature the pipeline could not supply arrives ZERO-FILLED, so its z is large whenever the training mean is far from zero — and absent data read as drift. Measured on the shipped stats: 103 of 176 features zero-filled, and 12 of the 14 exceeding z=4.0 absent rather than drifted; at the deployed chart's z=3.0 it is 15 of 15. So with DRIFT_BLOCK armed a FEED OUTAGE halts the desk and the log blames the model — an operator chases a retrain while the real fault is a dead feed. This became live when DEPLOY-CHART set DRIFT_BLOCK=true on the chart ArgoCD deploys, which previously set nothing and inherited the false default. Fixed with the same rule scripts/drift_guard_report.py already used — live exactly zero while the training mean is not — so the block fires on distribution change, `z_max` is computed over measured features only (it feeds model-quality scoring, which would otherwise draw a second wrong conclusion from the same missing data), absence is logged at ERROR, and both counts reach the status payload. **Whether absence should itself halt inference is NOT decided here**: it arguably should — a model predicting from 103 zero-filled features is not predicting from much — but that is a new gate with its own blast radius, and inventing it would be the same mistake in the other direction. That is the owner's call.
- **Write this test first** tests/unit/test_drift_guard_separates_absence_from_drift.py — seven, six red on the pre-fix tree. Two are controls that matter: a genuine 30-sigma move must STILL be caught (a guard that stopped reporting drift would pass the main test), and a feature whose TRAINING mean is legitimately zero must not be exempted — otherwise the rule becomes a hole in the guard rather than a fix to it.
- **Verify** `python scripts/correction_register.py --id DRIFT-ABSENCE`
- **Skills** `hopefx-dead-controls`, `verification-before-completion`
- **Full evidence** This session, 2026-09-13 — measured by scripts/drift_guard_report.py

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
- **Measured now** database/models.py:1229: amount_crypto = Column(Numeric(28, 8), nullable=False)
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

#### F180/F181/F182/F183 · Two classes named `SecureVault`

- **Priority** P1 · **Area** Security
- **Measured now** one SecureVault, in config/vault.py
- **Fix** Done: `security/encryption.py`'s copy is renamed `CredentialCipher`, so exactly one importable class is called `SecureVault` and it is the live one in `config/vault.py` (Argon2id, crash-safe rotation). Renamed rather than deleted: the module is load-bearing — `hash_password` has 31 production references and `verify_password` 18 — so only the misleading name went. The new name is what it is: it holds no credentials, only a key, a cipher and a salt, which is why `rotate_key` refuses. This entry previously said that `rotate_key()` 'returns True and destroys every credential'. Measured by execution 2026-09-13 it RAISES RuntimeError, pinned by test_rotation_never_returns_true — fixed earlier and never re-measured here, so the register was describing a danger that had already been closed. What remained, and is now closed, was the name collision itself. Still true and unaddressed: a random salt when `HOPEFX_SALT` is unset loses anything this cipher encrypted across a restart — harmless while nothing in production constructs it, and a trap if anything starts.
- **Write this test first** A test asserting exactly one importable `SecureVault`, and that it is the config/vault.py one.
- **Verify** `python scripts/correction_register.py --id F180/F181/F182/F183`
- **Skills** `hopefx-dead-controls`
- **Full evidence** docs/audit/REMEDIATION_PLAN.md — Phase 3

#### F206 · `int(amount * 100)` truncates cents against the payee

- **Priority** P1 · **Area** Money
- **Measured now** every amount-to-cents conversion rounds rather than truncates
- **Fix** Truncation toward zero always takes the same side of the rounding, so the loss accumulates in one direction. Closed across four sites, in three passes, which is the point worth keeping: `revenue_split.py` quantizes ROUND_HALF_UP; `monetization/stripe_integration.py`'s charge and refund now use `to_cents`; `payments/payment_gateway.py` quantizes inline rather than importing across the package boundary; and `api/payments.py`'s Stripe deposit was found on 2026-09-13, months after the others, because the probe scanned `monetization/` and `payments/` and never looked in `api/`. A 10.999 deposit was collected as 10.99, and 1.005 lost its cent twice — once to the float's binary error, once to the truncation. The probe now scans `api/*.py` too, and was injection-tested against exactly that site.
- **Write this test first** A test asserting 0.999 becomes 100 cents, not 99 — and watch it fail on the truncating call site.
- **Verify** `python scripts/correction_register.py --id F206`
- **Skills** `hopefx-money-precision`
- **Full evidence** docs/audit/REMEDIATION_PLAN.md — Phase 2

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

#### F218 · Model tables that exist only via `create_all()` and have no migration

- **Priority** P1 · **Area** Persistence
- **Measured now** all 50 ORM tables across 2 models module(s) are created by a migration; pinned by tests/unit/test_schema_migration_check.py
- **Fix** `create_all()` never ALTERs, so a table with no migration drifts silently between a fresh install and an upgraded one. **The count was wrong, and that is the finding.** It read '36 of 44 tables have no migration'; measured with names resolved rather than matched as text it is 0 of 47. The probe searched the migration corpus for a string literal beside `create_table(`, and this repository does not write that: 35 tables are created through a local `_tbl()` idempotency wrapper, four via `op.create_table(_TABLE, ...)` against a module-level constant, and three live in `database/user_models.py`, which the probe never read — so a genuine gap THERE would have been missed entirely. 32 false positives is worse than no probe: a real missing migration is invisible in that noise, and the figure was quoted as a P1 in three documents. The CI check F218 asked for now exists as `scripts/schema_migration_check.py --check`, wired into pre-commit and registered in GATE_EVIDENCE.toml.
- **Write this test first** tests/unit/test_schema_migration_check.py, deliberately in two halves. It can fail: a table added to EITHER models module with no migration is refused, removing a migration is refused, and a scan finding no tables or no migrations fails closed rather than certifying a tree it never read. It does not cry wolf: all three real declaration styles — plain literal, `_tbl()` wrapper, module-level constant — are exercised against a throwaway tree and must be recognised, because two of the three are exactly what produced the 32 false positives.
- **Verify** `python scripts/correction_register.py --id F218`
- **Skills** `test-driven-development`
- **Full evidence** docs/audit/REMEDIATION_PLAN.md — Phase 4

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

#### F97 · The only action holding `VPS_SSH_KEY` is float-pinned

- **Priority** P1 · **Area** CI
- **Measured now** every secret-holding action is pinned to a commit SHA
- **Fix** `appleboy/ssh-action@v1.2.5` was a tag, and a tag is mutable: whoever controls it controls a step that receives the private deploy key for the production VPS. It was the only `uses:` in the repository that both takes a secret and floats. **Closed 2026-09-14.** An earlier session recorded it as a ratchet rather than guessing, because the GitHub API is scoped to this repository and a guessed SHA breaks every deploy — the right call. The lookup that does work is `git ls-remote`, which the API being blocked had masked. Resolved to `0ff4204d59e8e51228ff73bce53f80d53301dee2`, and verified twice before pinning: `git ls-remote --tags` returns ONE ref for v1.2.5 with no `^{}` peel, so the tag is lightweight and that IS the commit rather than a tag object; the object was then fetched and confirmed to be a commit carrying `action.yml`. `_UNPINNED_SECRET_ACTIONS` is now empty, which cost the ratchet its teeth — with nothing exempted, "no offenders" is the whole verdict — so the scan now refuses to report clean when it matched nothing, and a positive control asserts the detector still calls a tagged secret-holding step an offender. Injection-tested end to end.
- **Write this test first** tests/unit/test_deploy_workflow_is_gated_and_pinned.py — the ratchet, proven by injecting a second secret-holding action on a tag and watching it refuse.
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

#### FIELD-NO-LABEL · Every settings field showed a label and had no accessible name

- **Priority** P1 · **Area** Frontend
- **Measured now** the settings Field label encloses its control, so every call site is named without an id; RiskCalculator's Label is a real <label> carrying htmlFor
- **Fix** `frontend/src/pages/settings/ui.tsx`'s `Field` rendered `<label>Protected Paths</label>` and then the control as a SIBLING, with no `for` and no id. It is used in ~60 places, so across every settings page a label was on screen and the control had no name; clicking the label did nothing. `RiskCalculator`'s `Label` was worse — a styled `<div>`, no association possible at all — on the page where a mistyped number becomes a position size. Fixed by making the settings label WRAP its control, which needs no ids and corrects all ~60 call sites without touching one of them, and by making RiskCalculator's Label a real `<label>` with `htmlFor` (plus `display:block`, since `<label>` is inline and the `<div>` it replaces was not). Part of 82 -> 18 on the jsx-a11y rule, with 29 files leaving a11y-debt.json.
- **Write this test first** frontend/a11y-debt.json is the ratchet and `src/test/a11y_debt_is_accurate.test.ts` fails on an entry that no longer describes anything — it caught 29 stale entries the moment these were fixed. Verified at runtime too: Chromium's accessibility tree reports 0 controls without an accessible name across all 93 routes, and that probe was itself injection-tested before being believed.
- **Verify** `python scripts/correction_register.py --id FIELD-NO-LABEL`
- **Skills** `hopefx-dead-controls`, `verification-before-completion`
- **Full evidence** This session, 2026-09-14 — measured with eslint-plugin-jsx-a11y and Chromium's AX tree

#### FIX-STORE · FIX session continuity on an ephemeral sequence store

- **Priority** P1 · **Area** Brokers
- **Measured now** start() refuses reset_on_logon=False on a $TMPDIR store
- **Fix** Done: `IBKRFIXBridge.start()` refuses `reset_on_logon=False` when `store_path` resolves under `tempfile.gettempdir()`.
- **Write this test first** tests/unit/test_ibkr_fix_bridge.py::TestStart::test_start_refuses_session_continuity_on_an_ephemeral_store
- **Verify** `pytest tests/unit/test_ibkr_fix_bridge.py -q`
- **Skills** `hopefx-fix-bridge`, `hopefx-dead-controls`
- **Full evidence** This session, 2026-09-13 — commit 08df737a

#### LINK-DUP-KEY · A link list rendered what its source did not say

- **Priority** P1 · **Area** Frontend
- **Measured now** all 4 link renderers key on destination AND label, and the call site that failed points at a tab that pill could not previously reach
- **Fix** `/2fa-setup` listed `/settings` twice in one CrossLinkBar, once as "Settings" and once as "API Keys", and the four link renderers keyed on destination alone. What a repeated key does here was MEASURED rather than inferred from React's warning, and the warning misleads: on first mount both links render and nothing is wrong; on the next re-render that reorders the list React DUPLICATES the shared key, so a three-link bar becomes four anchors with a stale pill and the wrong order. It does not drop anything. Nothing throws, and a test that only mounts sees nothing — which is why this survived a suite of 2,809. Two separate defects: the DATA ("API Keys" pointed at /settings, not at its tab, so that pill could never reach the page it names) and the CLASS (CrossLinkBar, RelatedPages, EmptyState and SubPageGrid all keyed on destination, so any caller passing two routes to one page hits it). Both fixed; an AST scan of all 482 source files found only two other arrays with a repeated destination, both already keyed correctly.
- **Write this test first** frontend/src/test/no_link_is_silently_dropped.test.tsx — five, all red on the pre-fix tree. They RE-RENDER with a reorder, because a mount-only assertion passes on the broken tree: the first draft of this test passed against the defect.
- **Verify** `npx vitest run src/test/no_link_is_silently_dropped.test.tsx`
- **Skills** `test-driven-development`, `verification-before-completion`
- **Full evidence** This session, 2026-09-14 — found by driving all 93 routes in a browser

#### LOAD-AMBIGUITY · A refused model artifact was indistinguishable from one never installed

- **Priority** P1 · **Area** ML
- **Measured now** load_artifact reports absent / refused / unreadable separately, and the registry path reports a refused ACTIVE model at CRITICAL instead of returning the same value as an unconfigured registry
- **Fix** `ml.__init__._try_load` returned `None` for three different things: the file is absent, `_verify_checksum` REFUSED it (a mismatch, or in production a file that arrived unlisted — an integrity event), or it passed integrity and failed to unpickle. One caller could not afford the ambiguity. `_load_from_registry` checks `pkl_file.exists()` ITSELF before loading, so a `None` there can only mean refused or unreadable — never absent — and it returned `(None, "")`, which is exactly what it returns when there is no registry configured at all. `_load_models` is a priority chain (registry-active, then advanced_oos.pkl, then the macro and baseline pairs), so an integrity refusal on the ACTIVE model fell through and loaded a DIFFERENT model, with a warning as the only trace at the decision point. The control fired correctly and the caller carried on — hopefx-dead-controls, second shape. `load_artifact` now returns absent / refused / unreadable with a reason; `_try_load` is a thin wrapper over it so its five call sites are untouched; and the registry path logs a refused active model at CRITICAL, naming that inference is about to continue on a model that was not the one selected. The fall-through POLICY is deliberately unchanged — whether an integrity refusal should halt inference or substitute is the owner's call, and §A8 scopes engineering to making the distinction available. Also corrected while here: the remediation message told operators to re-save models on Python 3.10, which is an interpreter neither CI nor production runs.
- **Write this test first** `tests/unit/test_artifact_load_distinguishes_refusal_from_absence.py` — six of its eight fail on the pre-fix tree. It builds a real manifest, tampers one artifact after recording it, and asserts each outcome separately; the control that passes both ways is `_try_load` still returning None for every failure, because changing that contract would be a refactor rather than this fix.
- **Verify** `python scripts/correction_register.py --id LOAD-AMBIGUITY`
- **Skills** `hopefx-dead-controls`, `test-driven-development`
- **Full evidence** MASTER_OUTSTANDING §A8 — named there as the half engineering may do without a decision

#### ML-LEAK · The smoke retrain leaks committed model artifacts into the working tree

- **Priority** P1 · **Area** ML
- **Measured now** the fixture snapshots every file in ml/saved_models/ instead of a named subset, so a writer added tomorrow is covered the day it lands; and scripts/model_artifact_manifest_gate.py refuses a staged artefact whose recorded checksum did not change with it
- **Fix** Done 2026-09-13, both halves. `ml/train_advanced.py` writes eight artifacts into `ml/saved_models/` and the `_SMOKE_OVERWRITES` restore list named six, so two leaked into the working tree after every suite run and were committed alongside whatever else was in flight. The fixture now snapshots the whole directory — a restore list that must be kept in step with a writer is a list that falls out of step — and `scripts/model_artifact_manifest_gate.py` refuses a staged artefact whose recorded checksum did not change with it, so the class of accident cannot be committed however it leaks in. **This was the root cause of A8** — proven, not surmised: `model_checksums.json` has one commit (`334e50f3`), while `feature_scaler.pkl` and `stacking_ensemble.pkl` have three each, and one of the later two is `05efdbab`, a *mobile authentication* fix that carried `feature_scaler.pkl`, `stacking_ensemble.pkl`, `feature_stats.json` and a new `feature_importances.json` for no reason connected to its subject. Fix the list, then add the gate: a commit that changes an artifact under `ml/saved_models/` without regenerating the manifest should not pass.
- **Write this test first** Carried by test_ml_training_pipeline.py (mutate every artefact train_advanced writes, discovered from its source, and assert all are handed back) and test_model_artifact_manifest_gate.py (seven injections against a real throwaway repository).
- **Verify** `python scripts/correction_register.py --id ML-LEAK`
- **Skills** `hopefx-dead-controls`, `test-driven-development`
- **Full evidence** This session, 2026-09-13 — reproduced by execution

#### MODE-SPLIT · The startup plan that is printed is not the system that is started

- **Priority** P1 · **Area** Runtime
- **Measured now** run.py resolves the mode once (core/run_mode.py) and both the printed plan and the dispatch read it; BROKER_TYPE and OANDA_ENVIRONMENT are published from that one decision
- **Fix** `run.py` derived the engine twice, on different conditions: `_get_pipeline` asked `mode == 'paper' or PAPER_TRADING`, while `_run_trading` asked `PAPER_TRADING or args.broker == 'paper'`. `--mode paper` sets OANDA_PRACTICE, BROKER, DEFAULT_BROKER and INGEST_EXCHANGE — never PAPER_TRADING — and the defaults are `--mode paper --broker oanda`. So plain `python run.py` printed the paper pipeline and started HopeFXEngine, a different subsystem set. Reproduced by execution: displayed-is-paper=True, dispatch-takes-paper=False. It did NOT place real orders — `--mode paper` also sets TRADING_MODE=paper and `_execute_decision` returns before any broker call — and that second, independent control is what bounded it, which is luck rather than design. Two name collisions travelled with it: run.py wrote BROKER while `brokers/factory.py` reads `BROKER_TYPE or BROKER`, so an ambient .env value silently beat the explicit flag; and `--mode paper` forced OANDA_PRACTICE while `brokers/oanda.py` reads OANDA_ENVIRONMENT, which nothing set. `core/run_mode.py` now resolves once — a frozen `ResolvedRunMode` carrying requested mode, effective mode, engine, broker, venue, trading mode, the environment it implies, its reasons and its conflicts — and `run.py` reads it for both the printed plan and the dispatch, publishes every name from that one decision, and exits 2 on a contradiction rather than picking a side. **One regression shipped with the first version and was caught the next day**: it published TRADING_MODE unconditionally, so `--mode api` rewrote a deliberate `TRADING_MODE=live` to paper — exactly what the pre-resolver run.py preserved on purpose, with a comment saying why. Safer-sounding and still wrong: it is the operator's setting and the API is the production serving process. Only the two trading run modes pin it now; api and backtest report it and publish no override, and the probe checks that. M05 travelled with it: CLAUDE.md and AGENTS.md both documented `--mode api | engine | backtest`, and `engine` has never been a mode — `python run.py --mode engine` is an argparse error, so an agent following the two files it is told to read first issued a command that cannot run.
- **Write this test first** `tests/unit/test_run_mode_resolves_once.py` — all 29 fail on the pre-fix tree. They assert the printed plan and the resolved engine agree for every combination that used to diverge, that `_setup_env` publishes BROKER_TYPE and both venue names, that a contradiction exits 2, and that neither T0 document names a mode the parser rejects. The mode list is asserted identical in `core/run_mode.py` and `run.py`, because two copies of one list is how the documented set drifted in the first place.
- **Verify** `python scripts/correction_register.py --id MODE-SPLIT`
- **Skills** `hopefx-dead-controls`, `test-driven-development`, `doc-freshness-review`
- **Full evidence** Found 2026-09-14 from an external source-inspection review (M01/M02/M05), reproduced here

#### REFUSAL-AS-FAILURE · Every non-admin was told the platform had failed, on every page

- **Priority** P1 · **Area** Frontend
- **Measured now** a 403 renders an empty surface; a timeout or 500 is still reported
- **Fix** `PresenceAnywhereMount` is rendered for EVERY authenticated user (`{isAuth && <PresenceAnywhereMount />}` in App.tsx) and fetches `/api/ai-core/capabilities/app`, which is `Depends(_viewer)` with `_VIEWER_ROLE = "admin"`. So for every non-admin the request is refused by design — and the component treated the refusal as a load failure, rendering a permanent amber "I could not load what I am allowed to do here (Error: HTTP 403)." to a user for whom nothing was broken. Ruled out a credential fault by execution first: signed in as a trader in Chromium, /api/auth/me returned 200 over the same cookie, so the platform answered and the answer was "not you". A 403 now renders an empty surface and the honest "Nothing on this page is exposed to me"; 401, timeouts and 5xx are still reported, because those really are unloaded.
- **Write this test first** frontend/src/test/a_refusal_is_not_a_failure.test.tsx — two tests, held apart so that "swallow the error" cannot pass. The first draft asserted on the COLLAPSED overlay and found the message in neither case, so the 403 test passed while measuring nothing.
- **Verify** `npx vitest run src/test/a_refusal_is_not_a_failure.test.tsx`
- **Skills** `test-driven-development`, `verification-before-completion`, `hopefx-dead-controls`
- **Full evidence** This session, 2026-09-14 — found by capturing HTTP status while driving migrated routes

#### SUITE-REWRITES-MODEL · Running the test suite overwrote a model artifact production verifies fail-closed

- **Priority** P1 · **Area** ML
- **Measured now** the conftest guard is present and the oos_eval writer redirects MODEL_DIR
- **Fix** `tests/unit/test_coverage_boost_ml_misc.py::test_oos_eval_returns_dict` called `ml.train_with_macro.oos_eval` without redirecting that module's `MODEL_DIR`, and `oos_eval` dumps the model it trains (train_with_macro.py:536). Every run of this suite therefore rewrote the committed `ml/saved_models/xgb_macro_oos.pkl`, whose sha256 is in `model_checksums.json` and is enforced fail-closed by `ml/__init__.py::_verify_checksum` in production. Nothing caught it because on the 3.11 interpreter the retrained bytes are IDENTICAL to the committed ones — the tree stayed clean and the provenance ratchet passed, having never been exercised. On the 3.12 interpreter that ships the image, the bytes differ and the artifact stops verifying: a green suite produced a model production refuses to load. Neither a grep nor an AST sweep found the writer; a probe that wrapped `joblib.dump` and recorded the stack did. Fix: redirect MODEL_DIR in that test, and guard the whole suite in conftest so the next one fails loudly instead of silently. The guard refuses writes to the 11 manifest artifacts only — writing a NEW file into the model directory stays allowed, because `test_ml_online_learner.py` must do that to exercise the permitted-directory check in `SklearnOnlineLearner.load`.
- **Write this test first** The guard IS the regression test, and it is the only formulation that fails deterministically on both interpreters: an assertion on the artifact's bytes passes on the older interpreter even while the write happens. Proven red by stashing only the test fix and running the unfixed test against the guard on 3.11 — it raised the guard's AssertionError.
- **Verify** `python scripts/correction_register.py --id SUITE-REWRITES-MODEL`
- **Skills** `test-driven-development`, `verification-before-completion`
- **Full evidence** This session, 2026-09-18 — surfaced by running the suite on Python 3.12 for the first time

#### ADR-LEDGER · Decisions record what was chosen and never what happened

- **Priority** P2 · **Area** Docs
- **Measured now** all 20 accepted decision(s) carry an outcome record — 16 observed, 4 pending with a review date — and adr.py requires both ledger fields, refusing an overdue review
- **Fix** Done 2026-09-13. The constitution requires a Decision Registry AND a Decision Ledger across seven fields; `scripts/adr.py` enforced the first five, nothing asked for **actual outcome** or **lessons**, and 0 of 19 records carried either — so every decision was a minute and none was memory. The governance choice was between a second artefact and a permitted amendment section, and it went to the second artefact (**ADR 0020**): `docs/decisions/outcomes/NNNN.md`, keyed by decision number and deliberately mutable, so ADR immutability keeps no exception to argue about later. `records()` globs non-recursively, so an outcome is never parsed as a decision record and `immutability_problems` never sees one — asserted, not left to the glob's shape. Three rules stop it being a box to tick: `pending` is counted separately from `observed`, a pending entry needs `Review by:` and an overdue one fails `--check`, and a `proposed` record is owed nothing. **The back-fill is what earned it**: writing nineteen entries surfaced two decisions recorded and never applied — 0014's nightly slow/e2e tier does not exist (210 tests selected by no workflow) and 0016's registry re-subjecting was never made (`subject = "architecture"` still, contested count 3 not 0 — applied the same day, baseline cleared with it, and now asserted against the live registry rather than the baseline). Neither was visible from the registry, because a registry records intent.
- **Write this test first** Carried by tests/unit/test_adr_outcome_ledger.py — 16 of its 18 cases are red on the pre-fix tree; the 2 that are green both times are the immutability guards, which must not change. Positive controls run against this probe: removing one outcome takes it to OPEN, and flipping nine entries to `pending` takes it to PARTIAL.
- **Verify** `python scripts/correction_register.py --id ADR-LEDGER`
- **Skills** `doc-freshness-review`, `test-driven-development`
- **Full evidence** docs/ai/specs/GROUP4_CONSTITUTION.md Chapter 9 · Group 3 Ch 6 · Group 2 Ch 6

#### API-TRADING-ROLE · `/health` could not say whether the API process was running a trading engine

- **Priority** P2 · **Area** Runtime
- **Measured now** /health reports the engine as unavailable/stopped/healthy without folding it into the overall verdict, and ENGINE_AUTOSTART — the API-only switch — is documented
- **Fix** Production runs `python app.py` — the Dockerfile's CMD — not `run.py`, so the run-mode resolver is not in that path at all. `app.py` builds the component registry, the registry registers `engine`, and `init_trading_engine` auto-starts it whenever `TRADING_MODE` is not live: `ENGINE_AUTOSTART` defaults to **true** on that branch. Live is properly gated (it needs ENGINE_AUTOSTART and LIVE_TRADING_ENABLED both), so the exposure is paper rather than real money. Two things were missing rather than wrong. `core/health.py::_probe_components` reported api, config, database, cache, auth, risk_manager, compliance, prop_enforcer, strategy_brain, websocket, email, broker and kill_switch — and not the engine, so `/health` answered identically whether or not this process was trading. And `ComponentRegistry.status_summary()` / `all_required_ok()` carry the docstring 'for health endpoints' with ZERO consumers, written for a caller that never arrived. `/health` now reports the engine as unavailable / stopped / healthy. It is deliberately NOT in the `critical` list that decides the overall verdict: an API-only deployment has no engine by design, and a permanently degraded field is one operators learn to ignore. `ENGINE_AUTOSTART=false` IS the API-only profile and already worked — it is reused rather than replaced with a new name, because a fourth spelling of one run-configuration concept is the defect MODE-SPLIT was about. What it lacked was documentation (audit F58 said 'documented nowhere'; F118 downgraded the gating half and left that one standing) and any way to see its effect from outside the process. Both are now closed.
- **Write this test first** `tests/unit/test_api_process_declares_its_trading_role.py` — seven of its nine fail on the pre-fix tree. The two that pass both ways are the API-only profile itself, which already worked: ENGINE_AUTOSTART=false schedules no engine, and the default paper deployment still does — the second is the positive control, because 'never trade' would otherwise pass the first while removing the product.
- **Verify** `python scripts/correction_register.py --id API-TRADING-ROLE`
- **Skills** `hopefx-dead-controls`, `test-driven-development`, `doc-freshness-review`
- **Full evidence** Found 2026-09-14 from an external source-inspection review (M04), grounded here

#### BALANCE-ZERO-RAISES · A broker balance of exactly zero crashed the balance lookup, silently

- **Priority** P2 · **Area** Money
- **Measured now** _account_field reads the attribute, then the mapping, without conflating zero
- **Fix** `api/billing.py::get_balance` read the broker account as `float(getattr(account, "balance", 0) or account.get("balance", 0))`. The `or` conflates "the attribute is missing" with "the attribute is ZERO", because 0.0 is falsy. A broker reporting a genuine zero therefore fell through to the mapping branch, and an object-style account has no `.get`, so it raised AttributeError — into an `except Exception` that logged at DEBUG, which is off in production. The user was shown whatever the next source produced, and nothing recorded why. Fixed by `_account_field`, which tries the attribute, then the mapping, and treats None rather than falsiness as absence. The same `except` now logs at WARNING: the difference between an operator seeing why a balance was wrong and seeing nothing.
- **Write this test first** `tests/unit/test_the_balance_says_where_it_came_from.py::test_a_zero_balance_does_not_crash_the_broker_read`, parametrised over an object-style and a mapping-style account because the fix has two branches and one that works only for the shape the test uses is not a fix. Red on the pre-fix tree for the object-style case.
- **Verify** `python scripts/correction_register.py --id BALANCE-ZERO-RAISES`
- **Skills** `hopefx-money-precision`, `test-driven-development`
- **Full evidence** This session, 2026-09-18 — surfaced by a test asserting a real zero is not a failed lookup

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
- **Measured now** all 916 unit-test files that define a test also assert
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

#### GATE-UNMEASURED · The coverage gate reported a module it never measured as below the floor

- **Priority** P2 · **Area** Tests
- **Measured now** a module the gate could not measure is counted and reported apart from one below the floor, and a timeout says so rather than blaming a missing import
- **Fix** `_run_coverage` returns `(None, reason)` and the reason distinguishes a TIMEOUT from a run that produced no row. `main` printed the reason as raw output but never passed it to `_judge`, so the verdict always read *the test may not import the module, or may fail to collect*. For `run.py` that is simply wrong: it is imported by 74 resolved test files, nothing is missing, and the gate ran out of its 600s budget — a reader following the message goes looking for an import that is already there. The summary line then said `N module(s) below 80% coverage threshold` about a module whose coverage nobody knows, which is rule 2 — an unmeasured value is absent, never zero — failing inside the gate that enforces it. `Verdict` now carries `unmeasured`, a timeout says so and names the resolved test-set size as the likely cost, and the summary counts the two apart. The conflation was visible only because run.py's debt entry had to explain in prose what the gate should have said itself.
- **Write this test first** `tests/unit/test_coverage_gate_says_why_it_could_not_measure.py` — eight of its nine fail on the pre-fix tree, including one that drives `main` with a stubbed measurement and asserts the summary does not claim a figure it never took. The control that passes both ways is the genuine collection failure keeping its original advice, which is right for the case it was written for.
- **Verify** `python scripts/correction_register.py --id GATE-UNMEASURED`
- **Skills** `hopefx-dead-controls`, `test-driven-development`
- **Full evidence** Found 2026-09-14 while recording run.py as debt under ADR 0017

#### MIGRATE-OVER-CREATEALL · `alembic upgrade head` cannot run over a database built by `create_all()`

- **Priority** P2 · **Area** Persistence
- **Measured now** every migration that creates one of the 50 ORM tables checks first, so a create_all() database can be brought under migration control
- **Fix** `create_all()` is called from five places — `database/connection.py`, `database/models.py`, `cli.py` (twice), `scripts/bootstrap_dev.py` and `scripts/create_superadmin.py` — so a developer who bootstraps and then runs `alembic upgrade head` hits this, and a deployment first stood up that way can **never** be brought under migration control. Reproduced: build the schema with `Base.metadata.create_all()` (47 tables), then `alembic upgrade head` fails at `m1n2o3p4q5r6 -> n1o2p3q4r5s6` with `sqlite3.OperationalError: table trade_journal already exists`. Most migrations define a local `_tbl()` wrapper that skips an existing table for exactly this reason; three do not, and `n1o2p3q4r5s6` is simply the first one reached. The fix is to give those three the same guard their siblings already use — not to change what `create_all()` does. Recorded in docs/audit/TODO.md as 'still open, deliberately not fixed here', where nothing measured it; tracked now so it cannot be lost.
- **Write this test first** **Fixed 2026-09-13.** Both migrations now define the `_tbl()` / `_idx()` guards their siblings already use. tests/unit/test_migrations_run_over_a_create_all_database.py carries four, two of them red on the pre-fix tree: upgrade-to-head over a create_all() database, and the same run twice (an operator re-running a failed deploy). Two are controls and both earned their place — one asserts create_all() really produced the colliding table, without which the regression could pass for want of a collision; the other asserts a FRESH migration run still creates all 47 tables, because a guard computing `_existing_tables` wrongly would make every create_table a no-op and leave an empty schema behind a green run. Verified up -> down -> up as well, and the pre-existing column-level suite (test_migrated_schema_matches_models.py, 9 tests) still passes.
- **Verify** `python scripts/correction_register.py --id MIGRATE-OVER-CREATEALL`
- **Skills** `test-driven-development`, `systematic-debugging`
- **Full evidence** This session, 2026-09-13 — reproduced by execution; noted but untracked in docs/audit/TODO.md #3

#### SHELL-NO-GROW · The standard page stopped where its content stopped

- **Priority** P2 · **Area** Frontend
- **Measured now** PageShell's className carries flex-[1_0_auto], matching the .page-content it replaced
- **Fix** `PageShell` replaced `.page-content` without the one layout rule that class carried: `flex: 1 0 auto` inside `.app-shell-scroller`, which is a flex column. With no flex rule the shell took the initial `flex: 0 1 auto`, so a page shorter than the viewport ended at its content and left bare scroller beneath it. Measured at 1440x900 in a 900px scroller: /observability 540, /support 560, /transparency 701 against /portfolio 2074, /dashboard 2066 and every other unmigrated page filling. Nothing was clipped — a flex item's `min-height: auto` floors it at its content height, and /academy (1459) and /chat (2927) were measured rendering at natural height and scrolling — so this was invisible to every test and to a screenshot of a long page. The fix is `flex-[1_0_auto]` and deliberately NOT `flex-1`: that is `1 1 0%`, which index.css records as having clamped every page to the viewport and trapped taller content.
- **Write this test first** frontend/src/test/page_shell_fills_the_scroller.test.tsx — red on the pre-fix tree. jsdom computes no flex layout, so the test holds the class contract and the browser measurement is the execution proof; both are recorded.
- **Verify** `npx vitest run src/test/page_shell_fills_the_scroller.test.tsx`
- **Skills** `test-driven-development`, `verification-before-completion`
- **Full evidence** This session, 2026-09-14 — found by measuring migrated pages against legacy ones in Chromium

#### F210 · Duplicate route aliases rendering identical pages

- **Priority** P3 · **Area** Frontend
- **Measured now** 94 distinct paths, none declared twice
- **Fix** Done: 88 distinct paths, none declared twice, so breadcrumbs and active-nav agree.
- **Write this test first** n/a
- **Verify** `python scripts/correction_register.py --id F210`
- **Skills** `ui-ux-pro-max`
- **Full evidence** docs/audit/REMEDIATION_PLAN.md — Phase 6

#### F223 · Test files named after the coverage metric

- **Priority** P3 · **Area** Tests
- **Measured now** no test file is named after the coverage metric
- **Fix** **Done 2026-09-13.** A file called `*_coverage_boost.py` says what it was written for rather than what it protects. The last 39 are renamed after the behaviour they assert, derived from their own test names — `test_execution_coverage6.py` asserts stop-loss and take-profit breaches, `test_kill_switch_coverage2.py` asserts the Redis latch, `test_risk_modules_coverage.py` asserts self-trade prevention. The original finding also said these held the highest concentration of assertion-free tests; that was true when written and is not now — F108 measures it, and every unit-test file that defines a test asserts. `docs/audit/CODE_READING_FINDINGS.md` keeps the original list as the evidence, with a note that the names in it no longer exist and that `git log --follow` resolves any of them.
- **Write this test first** None — this is a rename, so the tests are their own regression: all 2,611 in the renamed files pass and the suite still collects 24,169. The coverage gate pairs a module to its tests by IMPORT as well as by filename (`_find_test_files`), which is why renaming does not orphan a module's coverage — verified rather than assumed.
- **Verify** `python scripts/correction_register.py --id F223`
- **Skills** `test-driven-development`
- **Full evidence** docs/audit/REMEDIATION_PLAN.md — Phase 5

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
| **F146** | Whether feature drift blocks inference, and at what z | The code default and all four deployment surfaces disagree. ADR 0019 is drafted and `proposed`; accepting or rejecting it is the decision. Most of today's measured z is zero-filled features, not drift — `python scripts/drift_guard_report.py`. |
| **AI-SCOPE** | What the AI Core is allowed to claim and to do | Scope, not implementation. Engineering can build whichever answer; it cannot pick which one is honest. |
| **MODEL-166-DAYS-OLD** | Retrain, change the limit deliberately, or run without the gate | The shipped `advanced_oos.pkl` measures **167 days old** against `MODEL_MAX_AGE_DAYS=30`, and `STALE_MODEL_BLOCK` defaults to true, so inference is refused. This is not new — the gate read the artifact's **mtime**, which the clone rewrote to "0.69 days", so deploying a stale model was how the staleness gate got cleared (MODEL-AGE-IS-MTIME). Four registry versions share one sha256, so the bytes are unchanged since 2026-04-01; even the latest of the four is 80 days. Retrain and register, or decide 30 days is the wrong limit for this strategy and record why, or run `MODEL_MAX_AGE_DAYS=0` in a deployment that is not trading. Raising the limit to get trading back restores exactly what the fix removed. See MASTER_OUTSTANDING §A0. |
| **MODEL-PROVENANCE-DISAGREES** | Which record says when the model was trained | `advanced_oos_meta.json` gives `validated_at` 2026-06-26; the earliest `registry.json` version carrying the artifact's sha256 gives 2026-04-01 — the same bytes, nearly three months apart. Nothing had ever compared them, and the mtime the gate used to read agreed with neither. `health()` now reports `model_provenance_at` so the age it blocks on is attributable, but which record is *right* decides what a model's age means on this platform — most likely `validated_at` means validated and the artifact needs a real `trained_at`. Engineering picking one silently is engineering deciding policy. |
| **WALLET-DEAD** | Is the fiat wallet the withdrawal ledger, or is it retired? | `WalletManager` is ~700 lines of correct, tested, exact-`Decimal` ledger with **no production consumer**, and it is the only writer of `wallet_transactions` — which AML's daily withdrawal rules and the health check both read, and therefore both read empty. Either it becomes the ledger the withdrawal path writes through, or it is retired and those two readers are repointed in the same change. Deleting it silently is the one certainly-wrong answer. See MASTER_OUTSTANDING §A20. |

Every finding the register measures as OWNER appears here. It carried five rows
while the register measured six, because nothing checked the two against each
other, and a decision absent from this table is a decision nobody is asked to
make — `tests/unit/test_correction_register_gate.py` now asserts it, and caught
`MODEL-166-DAYS-OLD` missing from this table on the commit that added it.

The reverse does not hold, deliberately: a decision can outlive the status of
the finding that surfaced it. F61/F107 measures PARTIAL and F178/F98 measures
FIXED, while "build the OANDA adapter now?" and "which k8s tree is real?" are
both still yours to answer. What is asserted is that every row names a finding
the register actually tracks, so a renamed id cannot sit here pointing at
nothing.

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
