# HOPEFX — The Fix Plan

**224 findings · 36 CRITICAL · 70 HIGH · 58 MEDIUM · 15 LOW**

Audit complete: every backend package over 200 LOC read, all 82 SPA routes
rendered and measured, `tests/` (221,598 LOC) audited.

Detail for every finding is in `CODE_READING_FINDINGS.md`. Architecture in
`PLATFORM_ARCHITECTURE.md`. This file is the ordered work list.

---

## How this plan is ordered

Not by severity. By **what unblocks the rest**, then by **what loses money or
misleads a user**, then by everything else. Three principles:

1. **Nothing below is verified until CI runs.** Phase 0 first.
2. **A control that reports success without acting is worse than no control.**
   This is the single most repeated defect in the codebase — it appears 9 times
   across unrelated subsystems. Phase 1 is dedicated to it.
3. **Fix the measurement before the thing being measured**, wherever a metric
   is currently incapable of failing.

---

## PHASE 0 — Restore the ability to verify anything (blocked on the owner)

- [ ] **F95 · CI has not run on `main` for 30+ consecutive pushes.** All 30
      recent `ci.yml` runs failed with `runner_id: 0`, no runner assigned, no
      step executed — the signature of an Actions billing/spending limit.
      **Cannot be fixed from code.** Check GitHub → Billing → Actions.
      *Everything in this plan is unverified until this is green.*
- [ ] **F96 ·** `deploy.yml` has no `needs:` and fires on every push to `main`.
      Gate it on CI passing.
- [ ] **F97 ·** `appleboy/ssh-action@v1.2.5` is the only unpinned action across
      18 workflows, and it holds `VPS_SSH_KEY`. Pin to a 40-char SHA.
- [ ] **F103/F104 ·** `brain/` and `news/` coverage gates cannot pass (not in
      `[run] source`); the job named "Coverage gate (≥70%)" has no failure path.

---

## PHASE 1 — Controls that report success without acting

The defining defect of this codebase. Each of these returns a positive result
for work that did not happen.

- [ ] **F176 · `scripts/invariant_coverage.py` prints `FULL COVERAGE ✅` from
      hardcoded `True` literals.** CRITICAL. `CRITICAL_COMPONENTS` in
      `invariants/registry.py:77` is a hand-typed dict; `coverage_counts()`
      counts how many entries say `True`. It cannot fail. It reports
      `order_execution` protected (F151 disproves), `risk_engine` protected
      (F142 disproves), `kill_switch` recoverable (F139 disproves).
      **Interim fix today:** stop printing `FULL COVERAGE ✅`; print
      `DECLARED (unverified)`. **Real fix:** each dimension resolves to a probe
      that can fail.
- [ ] **F204 · payouts marked `PAID` with no transfer.** CRITICAL. With the
      `stripe` package absent, `process_weekly_payouts` sets `status=PAID`,
      `completed_at`, and zeroes the balance. Proved: $400 → $0, no money moved.
      Introduce `PayoutStatus.SIMULATED`, leave the balance untouched, and
      refuse the cycle when no transfer backend exists. **Fail closed.**
- [ ] **F219 · push notifications return `True` while sending nothing.** HIGH.
      Default deployment: all three Firebase vars blank in `.env.example`, so
      every notification logs and returns success. Return `False` when
      `fcm_enabled` is false or the user has no tokens.
- [ ] **F214 · the Phase-3 paper-trading gate gates nothing.** HIGH.
      `phase3_ready()` is called once, into a health dict.
      `_get_online_learner_store()` checks only the flag. Require
      `flags.ONLINE_LEARNING and get_gate().phase3_ready()[0]`.
- [ ] **F215 · `.env.example` enables the one flag whose code default is
      `False`.** HIGH. `FEATURE_ONLINE_LEARNING=true` (line 830) blends an
      unvalidated model at 30% weight into live signals. Set it to `false`.
- [ ] **F160 ·** the broker probe reports `ok` from config rather than a live check.
- [ ] **F159 ·** critical alerts never leave the log.
- [ ] **F146 ·** drift coverage is computed and gates nothing.
- [ ] **F205 ·** `logger.exception("...creator=%s error=%s", one_arg)` — two
      placeholders, one argument, so the record **cannot emit** while
      `failure_reason` says "check server logs".

---

## PHASE 2 — Money correctness

- [ ] **F203 · a sale during a payout is destroyed.** CRITICAL.
      `bal.pending_usd = Decimal("0.00")` zeroes instead of subtracting.
      Proved: $40 lost. Change to `-= amount` and add a lock. There is **no
      `threading.Lock` anywhere in the module**, and `process_weekly_payouts`
      iterates `_balances` while `record_sale` mutates it.
- [ ] **F208 · creator balances, sales and payouts exist only in RAM.**
      CRITICAL. Plain dicts, zero persistence calls in 432 lines, behind 7 live
      endpoints. Every restart erases what creators are owed; each worker holds
      a different balance. Same for `affiliate.py` (750 LOC).
- [ ] **F222 · `revenue_split.py` has zero tests.** Write them *with* the fix —
      the five defects above are all one test file away from being caught.
- [ ] **F135 ·** wallet ledger `transaction_id` collides (timestamp to the
      second) and rows are silently dropped; append a `uuid4`.
- [ ] **F136 ·** the wallet balance is an unlocked read-modify-write.
- [ ] **F138 ·** `invariants/payments.py verify_balance_after` is never called —
      it is the check that catches F135 and F136.
- [ ] **F206 ·** `int(amount * 100)` truncates payout cents against the creator.
- [ ] **F207 ·** every payout claims every historical transaction; reconciliation
      double-counts.
- [ ] **F137 ·** `amount_crypto` is a `Float` and cannot hold 18-decimal tokens.
- [ ] **F31/F32 ·** affiliate and subscription money state in memory, payout TOCTOU.

---

## PHASE 3 — The stop-loss chain and risk gates

- [x] **F45 ·** local SL/TP monitor read `pos.position_id`; the field is `.id`. **FIXED**
- [x] **F60/F106 ·** `trade_executor` crashed after the fill on `order.status.value`
      and `order.id`. **FIXED**
- [x] **F151 ·** a user's stop-loss was accepted, forwarded and discarded; the API
      now reports `stop_loss_placed`. **FIXED**
- [x] **F169 ·** the UI now warns when a filled order left the position unprotected. **FIXED**
- [ ] **F61/F107 · `BROKER_TYPE=oanda` cannot place an order.**
      `AsyncOANDAConnector = OANDABroker` is an alias with no
      `place_market_order` (it has `place_order`). **Live OANDA is the stated
      next milestone and `k8s-configmap.yaml` already sets
      `BROKER_TYPE=oanda, OANDA_PRACTICE=false`.**
- [ ] **F142 · the ACTIVE paper path has no risk layer.** `PaperRunner` →
      `bus.publish` → `FIXRouter._route`, whose only gate is `if self._halted`.
- [ ] **F84 ·** the data-layer safety gate is skipped in the condition it exists for.
- [ ] **F94 · regime detection never runs** → regime permanently `"unknown"` →
      **every position sized at 0.5×**.
- [ ] **F139 ·** `deployments/k8s/` disables cross-pod kill-switch propagation.
- [ ] **F130 ·** self-healer patch signing is off and set nowhere.
- [ ] **F184 ·** the self-healer counts "could not run tests" as "tests passed".

---

## PHASE 4 — Config that contradicts the code

Four manifest pairs now disagree. Each is "whichever `kubectl apply` ran last wins".

- [ ] **F178 ·** `k8s/k8s-configmap.yaml` says `HOPEFX_INVARIANT_MODE=enforce`;
      `deployments/k8s/configmap.yaml` says `monitor`. Both ConfigMaps are named
      `hopefx-config`.
- [ ] **F98 ·** two ConfigMaps named `hopefx-config` with contradictory safety values.
- [ ] **F216 · `CLAUDE.md` calls `data/` legacy "CSV + old utilities".**
      It holds `real_time_price_engine.py` (1,107 LOC), `tick_feed.py`,
      `depth_of_market.py`, and is imported **22× from production** including
      5× in `startup_factories.py`. Three HTTP routers mount from it. The
      instruction is actionable, wrong, and sits at the top of every AI
      assistant's context. **Decide** whether `data/` is canonical for
      real-time feeds or the migration is incomplete, and say which.
- [ ] **F217 ·** four packages own "market data" (`data_layer/`, `data/`,
      `data_feed/`, `market_data/`) and no document draws the boundary.

---

## PHASE 5 — Security and credentials

- [ ] **F180/F181/F182/F183 · three classes named `SecureVault`.** Only
      `config/vault.py` is live (and is genuinely good — Argon2id, crash-safe
      rotation). The other two are unreferenced and dangerous:
      `rotate_key()` returns `True` and **destroys every credential**; a random
      salt when `HOPEFX_SALT` is unset loses everything on restart;
      `encrypt()` falls back to **base64** and `decrypt()` honours it.
      **Delete `security/encryption.py` and `security/vault.py`.** They are a
      trap: the broken ones have the richer-looking API.
- [ ] **F144 ·** login is user-enumerable by timing — 268.74 ms measured gap.
- [ ] **F99 ·** the placeholder-secret test skips the case it exists for,
      exempting `DB_ENCRYPTION_KEY` and `POSTGRES_PASSWORD`.

---

## PHASE 6 — Tests and the measurements that hide all of the above

- [ ] **F221 · the coverage gate measures 34% of the application.** CRITICAL.
      `[run] source` names 13 packages = 127,878 of 367,949 LOC. Never measured:
      `api/` (61,033 — the largest package), `monetization/`, `payments/`,
      `security/`, `database/`, `invariants/`, `data_layer/`, `data/`.
      The `omit` list then removes `risk/manager.py`, `risk/pre_trade_gate.py`,
      `execution/engine.py` and the decision engine from *inside* the measured
      packages. Add the money packages and `api/` to `source`; justify each
      `omit` entry or delete it.
- [ ] **F222 · 13 critical modules are never named in a test.** ~2,800 LOC of
      money code, including `payments/crypto/address_generator.py` — a wrong
      deposit address is an irrecoverable loss.
- [ ] **F223 ·** 75 test files named after the coverage metric
      (`*_coverage_boost.py`, `*_coverage2.py`), and they hold the highest
      concentration of assertion-free tests. Rename to the behaviour they
      protect; where a test name claims a behaviour
      (`..._skips_outside_pod`), assert that behaviour.
- [ ] **F105 ·** the 80% gates measure the packages with the risk logic omitted.
- [ ] **F108 ·** 14 tests assert nothing against a class that has never existed.
- [ ] **F106 ·** nothing tests the `TradeExecutor` ↔ real-connector join.
- [ ] **F218 ·** 14 model tables have no migration; they exist only via
      `create_all()`, which never ALTERs. Includes `aml_alerts`, `chargebacks`,
      `crypto_payments`, `tax_reports`, `gdpr_requests`,
      `reconciliation_records`. Add a CI check comparing `__tablename__`s to
      migrations (~20 lines).

---

## PHASE 7 — Correctness bugs (isolated, low risk to fix)

- [ ] **F119 ·** annualised return uses `252/len(equity)` on hourly bars —
      **34× understated**; Calmar inherits it.
- [ ] **F120 ·** Sortino denominator is std of losing observations, not downside
      deviation; the bias flips sign with distribution shape.
- [ ] **F125 ·** the regime EMA iterates `reversed()` — oldest bar weighted **7.4×** the newest.
- [ ] **F145 ·** missing features zero-filled **before** scaling — measured
      **−15σ** for price, **−3.3σ** for RSI, with 48.2% of the vector missing.
- [ ] **F80 ·** the nuclear wordmap matches by bare substring — a headline
      containing "coupon" scores severity 7 and triggers hedge mode.
- [ ] **F81 ·** the hedge is marked active before the broker call.
- [ ] **F123 ·** `/walk-forward/run` performs no walk-forward analysis; a correct
      implementation with a purge gap already exists in `backtesting/walk_forward.py`.
- [ ] **F147 ·** the order-flow subsystem is mounted and never fed (2,791 LOC).
- [ ] **F149 ·** the GodMode watchlist sparkline is `Math.random()`.
- [ ] **F150 ·** "Copy API key" builds the key client-side; it can never authenticate.
- [ ] **F220 ·** device tokens in a module dict — lost on restart, so even a
      correctly configured FCM stops delivering after a deploy.

---

## PHASE 8 — The product: what users see

### 8a. Broken or misleading (fix first)

- [ ] **F198 · `/kyc` and `/mobile` return raw JSON 404 on direct navigation.**
      HIGH. 2 of 82 routes. In-app nav works, which is why it survives testing.
      **KYC is a regulatory gate** — a user following a verification email gets
      `{"detail":"No route for GET /kyc"}`. Cause: `api/kyc.py:33` mounts a
      router at the bare `/kyc` prefix. The correctly-prefixed
      `kyc_alias_router` at `/api/kyc` **already exists** — retire the bare
      mount (keeping the two external webhook URLs), move mobile v2 under
      `/api/mobile/v2`, add both to `_SPA_ROUTES`.
- [ ] **F194 ·** `/news` shows "ARTICLES 1" above "No recent news". Two
      endpoints disagree; a third honestly reports the sentiment engine is
      unavailable and the UI is wired to the one that returns a confident `0.0`.
      **A neutral market is indistinguishable from a broken engine.**
- [x] **F189 ·** `/correlation` blocked ~20 s then discarded the server's
      explanation. **FIXED** — renders the note and the missing symbols.
- [ ] **F200 ·** `/docs` is blank in every deployment: the CSP blocks the
      Swagger CDN the page loads. Vendor `swagger-ui-dist`.
- [ ] **F201 ·** `/academy` says "15 available on your plan"; all 15 are
      COMING SOON. That is a false statement to a subscriber.
- [ ] **F199 ·** `_SPA_ROUTES` is hand-maintained (60 entries) and `App.tsx`
      declares 83. Generate it, or add the direct-`GET`-returns-200 test that
      found F198.

### 8b. Drill-down — the product is a readout, not an application

- [x] **F187 (partial) ·** 29 dashboard tiles wired; `/dashboard` clickable
      metrics **1/104 → 36/101**, outbound links 8 → 55. **FIXED**
- [ ] **F187 (remaining) · 65 metrics still inert on `/dashboard`**, in
      `LivePriceTicker`, `MicrostructurePanel`, `OrderBookDepth`,
      `LiveSignalFeed`, `OrchestratorHealthGrid`, `SentimentGauge`,
      `MacroCalendar`. Plus `/master-control` (46 metrics, 0 clickable),
      `/watchlist` (0/16), `/performance` (0/8), `/status` (10 rows, all inert).
      **Aggregate: 46 of 82 routes have zero clickable metrics.**
- [ ] **F192/F225 · NOT a blocker — corrected.** `Trade.tsx:460` already reads
      `location.state.signal` (symbol, direction, entry, stop, target,
      quantity), and `Watchlist.tsx:309` / `TradeJournal.tsx:254` already pass
      it. **The in-app handoff works and is better than a query param.** Use it
      for the remaining drill-down work. The residual gap is narrower: no
      `useSearchParams`, so `/trade?symbol=X` is ignored and a ticket cannot be
      **bookmarked or shared**. Seed from the param when router state is absent.
- [ ] **F188/F196 ·** 31 of 82 routes are navigational dead ends.

### 8c. Structure and information architecture

- [ ] **F209 · there are two dashboards and the nav points at the weaker one.**
      HIGH. `/dashboard` (`TradingDashboard`): **0 canvases, 0 tables**.
      `/home` (`Dashboard`): **7 canvases, 1 table**, and it titles itself
      "📊 Dashboard" — but the sidebar labels it **"Live Feed"**.
      **Decide whether these should be one page.** This also revises F193:
      charting is not missing, it is on the other dashboard.
- [ ] **F210 ·** 12 of 82 routes are duplicate aliases rendering identical pages
      (`/trading` = `/ai-charts` = `/ai-chart`; `/feed` = `/social-feed` =
      `/social`; `/risk-calc` = `/risk-calculator`; `/audit` = `/audit-log`;
      `/reliability` = `/system-reliability`). Pick a canonical path, redirect
      the rest, so breadcrumbs and active-nav agree.
- [ ] **F173 ·** `/dashboard` renders **zero** `h1`–`h3`. `/landing` renders 24.
- [ ] **F174/F190/F193 ·** charts and tables exist on only 5 and 7 routes
      respectively — and per F185 `api/trading.py` already serves
      `/equity-curve`, `/history`, `/depth/{symbol}` and `/microstructure`.
      **Both halves are built.** Nothing draws them on the pages that need them.
- [ ] **F171 ·** 82–128 touch targets under 44px per page (CRITICAL rubric rule).
- [ ] **F172 ·** icon-only buttons without `aria-label` (10 on `/dashboard`).
- [ ] **F175 ·** 1,472 emoji remain in 151 files (`CommandPalette.tsx` keeps its
      own hard-coded emoji list and does not read `navConfig`).
- [ ] **F167 ·** sidebar "Sign out" overlaps the search hint on every page.

### 8d. Capability already built and not surfaced — the growth list

**F185: 309 of 891 endpoints (34%) have no UI.** Ordered by user-visible value
per unit of work, since the backend is already done:

1. **`api/advanced_orders.py`** (7 endpoints) — **OCO, stop-limit,
   trailing-stop**, built and unreachable. Highest trader-visible value.
2. **`api/trading.py`** `/equity-curve` + `/history` — the chart and the trade
   table that 8c is missing.
3. **`api/ml.py`** `/explain/{model}` + `/feature-importance` — turns "trust the
   AI" into "here is why"; it is the differentiator the landing page claims.
4. **`api/status.py`** (10 endpoints, zero UI) — incidents and history, which a
   subscriber checks before funding an account (see F212).
5. **`api/custom-indicators`** `test` + `deploy` + `builtin` — **F186**: two
   parallel indicator APIs exist and the page is wired to the weaker one.
6. **`api/portfolio_allocator.py`** + `api/portfolio.py` factor endpoints — the
   institutional layer.

---

## What the per-page analysis added (F225-F228 + design spec)

- **F226 ·** `/dashboard` is a 271-LOC layout shell with **zero** store reads,
  handlers or inputs. "The dashboard is too basic" is a property of the nine
  panels it composes — and of the choice to compose *those* nine: five of the
  nine describe the platform's machinery rather than the user's money. Fixes
  belong in the panels.
- **F227 ·** the pages that *do* things (alerts, copy-trading, risk calculator,
  TCA) are well-featured; the pages that *show* things (home, pnl, leaderboard,
  watchlist, dashboard) are read-only — and those are the ones subscribers open
  most. `/home`: 879 LOC, 8 store slices, **zero actions**. `/pnl`: 849 LOC,
  refresh and pagination only, **0 form inputs**.
- **The gating constraint is `useOrchestratorData.ts`** (751 LOC), a single
  global fetcher calling ~25 APIs into the store. A page can only render what
  it fetched. Much of F185's 34% gap is the bootstrap never fetching, not pages
  ignoring — so surfacing built capability is mostly adding fetches there.
- **Per-page design spec** in `CODE_READING_FINDINGS.md` gives, for each core
  page: what it renders, what drives it, what functions it lacks, and which
  **already-built** endpoints supply them.

## PHASE 9 — AI Core build (spec received, NOT started)

Full intake and audit cross-reference: **`AI_CORE_SPEC_INTAKE.md`**.

- [ ] **Rotate the exposed superadmin credential** (spec item 6). Above
      everything in this plan. Location not yet confirmed — the tracked working
      tree reads as placeholders; needs the file or commit named.
- [ ] **Prerequisites the spec does not know about.** The AI kill switch
      inherits **F139** (cross-pod propagation denied — no RBAC in
      `deployments/k8s/`); the agent sandbox inherits **F130** (patch signing
      off, key set nowhere) and **F184** ("could not run tests" recorded as
      "tests passed" on the patch gate). Fix these first or the AI layer ships
      with a decorative emergency stop and a second unsigned code-execution path.
- [ ] **Adopt two acceptance tests before writing agent code:** an agent
      calling an action outside its scope must FAIL THE BUILD, and a proposal
      executing without an approval record must fail the build. The spec's
      approval queue is otherwise the same shape as F176 — a control that is
      described accurately and enforced by convention.
- [ ] **The eval gate must declare its own coverage.** **F221** — the existing
      coverage gate measures 34% of the application and omits the risk manager;
      a new gate added to that culture inherits the blind spot.
- [ ] **Superadmin surface ≠ user surface** (hive chat and AI Core). Capability
      split, not styling: server-side enforcement with a 403 test per endpoint,
      the direct-GET probe from **F198**, and separate components rather than
      `if (isSuperAdmin)` branches. **Hive chat details still to come.**
- [ ] Confirm the six Business Operations department names, then rebuild Figma
      once (Starter-plan rate limit makes iteration expensive). The current file
      is out of date per the spec's own Section 10.
- [ ] Confirm VPS RAM/VRAM before locking a local model size — and settle
      **F98/F178** first (two ConfigMaps named `hopefx-config` with
      contradictory safety values) so "what is deployed" is a known quantity.
- [ ] Restore **customizable settings** to scope (theme, department visibility,
      notification thresholds, default autonomy per department) — dropped from
      later spec drafts, distinct from the per-action autonomy dial.
- [ ] Then: AI Gateway, internal MCP tool bus, response cache, guardrails-as-
      pipeline, formalized evals (spec Section 3).

## Not yet examined

* **41 sub-views** inside `/superadmin` (24 sections) and `/settings` (17) were
  measured only on their default tab, not individually.
* The large packages — `api/` (61k), `ml/` (31k), `scripts/` (22k), `core/`
  (21k) — were entered through their entry points and followed along the **live
  paths**. Files off those paths were not read line by line.

---

## Method notes worth keeping

Recorded because they changed conclusions during this audit:

* **A measurement that makes the codebase look far worse than the surrounding
  evidence suggests is more likely a broken measurement than a discovery.**
  Three times: "89% of the API has no UI" (real: 34%), "329 dead invariants"
  (real: ~31 reachable of 362), "36 of 41 tables have no migration" (real: 14).
  Check against a case known to work before reporting.
* **A module-name grep is not a reachability test.** Three near-misses
  (`nuclear/`, `teams/`, the `invariants` facade).
* **Trace reachability before assigning severity.** F158 (a skill naming an
  unreachable module as live) and F180 (dangerous code with no importers) are
  the two directions of the same error.
* **Execute rather than assert.** F204 and F205 were both found by driving a
  failure path, not by reading it. F137 and F101 were both *downgraded* after
  measurement contradicted the hypothesis.
* **A check that cannot fail is the defect.** F176 is the extreme case; my own
  `npx tsc --noEmit | head -5 && echo TSC-CLEAN` had the same bug.
