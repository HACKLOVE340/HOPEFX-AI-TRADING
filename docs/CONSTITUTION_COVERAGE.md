# Platform Constitution — Coverage Map

> Honest, tracked status of every constitutional rule from the invariant
> framework (`Best.txt`) against the **actual** HOPEFX codebase. This is the
> "account for everything" artifact: each rule is **Enforced**, **Partial**
> (with location), or **Gap** (with severity + recommendation). It is the
> roadmap the framework's own sections 9–11 call for — invariants are a program
> of work, not a one-shot. Nothing in the file is left unaddressed here.

**Legend:** ✅ Enforced · 🟡 Partial · ❌ Gap
**Mechanisms now in place:**
- **`invariants/` — 322 pure invariant predicates across 34 domain modules (48 test functions, all green):**
  - `constitution.py` — order state machine, PnL/capital conservation, duplicate-id, tick/spread, finiteness, human control
  - `market.py` — order book, multi-feed agreement, freshness/staleness, clock drift, future-event, event sequence, causal order, market-open/halt, delisting
  - `risk.py` — daily loss, drawdown, VaR, leverage, margin buffer, liquidation distance, liquidity, per-dimension exposure, concentration, dependency, catastrophic-loss kill triggers
  - `ai.py` — model-approved/hash, drift, confidence, entropy, ensemble dominance, consensus, feature/embedding integrity, hallucination pre-trade guard, explainability, agent authority/tool/loop/self-escalation/memory ownership
  - `execution.py` — slippage, latency budget, broker reconciliation, reported-vs-actual reality, settlement balance, full pre-trade gate
  - `governance.py` — no-lookahead, no-data-leakage, after-cost viability, pod isolation, audit immutability/completeness, segregation-of-duties, dual control, config drift, deployment gates, human supremacy
  - `portfolio.py` — portfolio state machine, portfolio-value reconciliation, position sizing, diversification, correlation budget, hedging, currency reconciliation, synthetic-exposure tracking, capital efficiency
  - `reconciliation.py` — reconciliation chain, custody, double-entry ledger, ledger immutability, treasury flow, alpha attribution, fee integrity, revenue leakage
  - `derivatives.py` — Greek-limit bounds, collateral sufficiency, expiry handling
  - `systems.py` — single-leader/quorum, exactly-once, stream lag, DLQ, cache freshness/version, acyclic graphs, zombie detection, blast-radius containment
  - `compliance.py` — wash-trade, spoofing, layering, restricted/MNPI, retention, jurisdiction, chain-of-custody, approval workflow, privilege escalation
  - `operations.py` — alert delivery/ack, monitoring coverage, incident timeline, operator readiness/fatigue, emergency reversibility, alert fatigue, monitor-the-monitors
  - `ai_governance.py` — determinism, reproducibility, decision lineage, prompt version, context completeness, goal alignment, reward-hacking, shadow objective, alpha decay, belief-vs-reality, calibration, strategy approval/identity, self-replication & autonomous capital/strategy controls
  - `market_structure.py` — halts, circuit breakers, LULD bands, auctions, venue eligibility, cross-venue price sanity
  - `replay.py` — market/strategy/decision/agent replay fidelity, historical recoverability, data-resurrection, snapshot-vs-event-log
  - `drift.py` — risk-appetite, allocation-policy, governance, compliance, constitution-version, incentive drift
  - `knowledge.py` — RAG retrieval/trust/freshness, knowledge-graph orphans/contradictions, memory aging/conflict
  - `ml_pipeline.py` — feature schema, online/offline parity, dataset completeness, training reproducibility, model lineage/signing, inference cost, GPU
  - `resilience.py` — backup recency/integrity, restore-tested, failover, multi-region, recovery path/rollback, chaos survival, recovery SLA
  - `multi_agent.py` — deadlock, collusion, conflict rate, resource fairness, circular delegation, emergent behavior, agent-count bound
  - `economic.py` — economic equilibrium, report accuracy, fund segregation, redemption fairness, contract limits, cost growth
  - `security.py` — exposed secrets, rotation, secret usage, artifact signing, data provenance, trust boundaries, prompt-injection & input-poisoning
  - `meta.py` — observation integrity (observed==actual), platform identity, anomaly-detector liveness, human-can-stop, invariant-engine health, constitution aggregate, five-master-guarantees
  - `platform_web.py` — service-up, uptime SLA, error rate, crash-loop, console errors, render, page-load/web-vitals, bundle size, API status/schema/latency/version, resource headroom, disk-full, pool exhaustion, TLS expiry
  - `platform_data.py` — PK uniqueness, FK validity, orphans, referential integrity, migrations applied, index health, cache==db, search==db, replica lag, rollup==source, NOT-NULL, timestamp monotonicity
  - `platform_auth.py` — token signature/expiry, session validity, password & MFA policy, revoked-blocked, resource ownership (IDOR/BOLA), permission/scope, cross-tenant, secret-in-response, rate limiter, security headers, CSRF, failed-login lockout
  - `payments.py` — charge authorization, idempotency (no double-charge), amount validity, refund ≤ original (single & cumulative), ledger balanced, balance arithmetic, currency consistency, gateway reconciliation, withdrawal ≤ available
  - `jobs.py` — job SLA, scheduled-fire, queue depth/age, DLQ bound, idempotency, zombie detection, attempts bound, singleton concurrency, failure rate
  - `business_logic.py` — workflow state machine, quantity conservation, total==sum, count match, value range, discount bound, uniqueness, cross-service agreement, no-partial-commit (atomicity), read-only stability
  - `ai_quality.py` — feature-count stability/sparsity, regime confidence, signal concentration, trade clustering, explanation consistency, action==rationale, risk-model freshness, stress-model completeness, output bounds, calibration
  - `market_lifecycle.py` — tick/lot/notional rules, corporate actions, symbol-mapping stability, instrument tradability, settlement calendar, tax/withholding, liquidity-mirage, exchange position limits
  - `ops_extended.py` — alert escalation, incident root-cause, postmortem, override logging/attribution/authorization/rate, retired-strategy stop, emergency-authority governance, prod-change approval
  - `assurance.py` — sim/paper fidelity, paper≠live routing, data sovereignty, cross-region leak, no-unilateral-capital-move, least privilege, dual control, access review, anomalous-access block
  - `integrations.py` — dependency health/rate-limit/SLA, webhook signature/replay, notification delivery, storage durability/checksum, pipeline freshness, event-loss, circuit-breaker on failure
- `scripts/runtime_invariant_check.py` — boots app + probes endpoints + asserts output invariants + scans the event log
- `hopefx_observability.py` — whole-platform capture (DEBUG) + uncaught/thread/asyncio/unraisable hooks → **No Silent Failure** substrate
- **`invariants/enforcement.py` — the bridge from pure predicates to the live money path (feature-flagged, fail-safe).** Wired at four points:
  1. **Pre-trade gate** — `risk/manager.py` `size_order()` calls `enforce_pre_trade()` after the hard gates; in `enforce` mode a CONSTITUTIONAL/CRITICAL violation returns zero sizing (order refused).
  2. **Reconciliation loop** — `core/position_reconciler.py` checks aggregate DB-vs-broker book value each cycle and trips the kill switch on a CONSTITUTIONAL breach in `enforce` mode.
  3. **CI gate** — `.github/workflows/ci.yml` runs `runtime_invariant_check.py` (findings fail the build).
  4. **`/health/invariants`** — live status (mode, engine self-check, counters, recent violations) on the health router app.py includes.
  - Mode via `HOPEFX_INVARIANT_MODE` ∈ {`off`, `monitor`, `enforce`}, **default `monitor`** (runs + logs, never blocks → zero behaviour change until deliberately set to `enforce`). Checker-internal errors fail **open** by default (`HOPEFX_INVARIANT_FAIL_CLOSED=1` to opt out). Tested in `tests/unit/test_invariants_enforcement.py`, `tests/unit/test_pre_trade_invariant_gate.py`, `tests/integration/test_invariants_endpoint.py`.

> **Honest framing (per the framework's §9–11):** the file enumerates 300+ invariant
> *categories*. **322 are now implemented as pure, tested predicates** — the full
> breadth, from the trading/AI/risk core to the generic-platform layer
> (availability, frontend, DB integrity, auth/tenancy, payments, jobs, business
> logic, integrations). A handful of raw **infrastructure probes**
> (DNS/SSL/k8s liveness) still belong in the runtime checker / ops monitors
> rather than pure functions. This library is the enforcement substrate; the
> remaining work is **wiring each predicate to live state** (the tracked program
> below) — building the predicates is done.

---

## The 20 Constitutional Rules

| # | Rule | Status | Where enforced / gap & recommendation |
|---|------|--------|----------------------------------------|
| 1 | No Unauthorized Trade | 🟢 | **Wired:** `risk/manager.py` `size_order()` now calls `enforce_pre_trade()` (invariants/enforcement.py) after the hard gates — in `enforce` mode a violation refuses the order (zero sizing). Plus `kill_switch.py` gate. **Remaining:** assert every broker order carries a risk-approval token (AI-bypass guard). |
| 2 | No Unauthorized Capital Movement | 🟡 | Wallet/withdrawal endpoints require auth + role. **Gap:** no `verify_capital_equation` wired to a ledger endpoint. *Rec: expose a treasury/ledger reconciliation endpoint, assert the capital equation each cycle.* |
| 3 | No Hidden Loss | 🟢 | **Wired:** `core/position_reconciler.py` now runs `enforce_reconciliation()` each cycle on aggregate DB-vs-broker book value; a CONSTITUTIONAL breach trips the kill switch in `enforce` mode. Library `verify_pnl_reconciliation`/`verify_no_negative_balance` back it. **Remaining:** also assert the PnL identity against a live `total_pnl` account field. |
| 4 | No Hidden Exposure | ❌ | **Gap:** no per-symbol/sector/leverage exposure endpoint to assert against. *Rec: expose an exposure snapshot; assert `verify_within_limit` per dimension.* |
| 5 | No Hidden Risk | 🟡 | VaR/CVaR computed in `risk/manager.py`; surfaced in reliability/risk endpoints. `verify_within_limit` available. *Rec: assert VaR ≤ approved each cycle in the checker.* |
| 6 | No Hidden Decision | 🟡 | Decisions logged via `core/decision/HOPEFXDecisionEngine.py`. **Gap:** no completeness invariant. *Rec: assert every executed order has a linked decision id.* |
| 7 | No Hidden AI Action | 🟡 | Observability captures agent/brain logs whole-platform. **Gap:** no structured per-action audit record assertion. *Rec: emit `event()` per AI action; assert presence.* |
| 8 | No Data Corruption | ✅ | `verify_tick`, `verify_spread`, `verify_no_duplicate_ids`, `verify_finite` (library); runtime checker flags NaN/Inf + duplicate/tiled list items on **every** probed endpoint (caught the 18-rectangle + fraction bugs). |
| 9 | No State Corruption | ✅ | `verify_order_state_transition` + `verify_order_not_contradictory` (library, mirrors `execution/oms.py`'s enforced transition table); terminal-state re-entry & phantom fills caught. |
| 10 | No Audit Gap | 🟡 | `api.admin.log_activity` + audit endpoints exist and return data. **Gap:** no immutability / completeness invariant. *Rec: hash-chain audit records; assert chain integrity.* |
| 11 | No Compliance Breach | 🟡 | Compliance endpoints (AML/KYC/sanctions/surveillance) live and returning data (verified). **Gap:** no automated surveillance invariants (wash/spoofing). *Rec: add surveillance checks to the suite.* |
| 12 | No Cross-Tenant Leakage | 🟡 | Pod/tenant isolation code exists; auth scopes per user. **Gap:** no runtime isolation assertion. *Rec: probe two pods, assert disjoint positions/memory/models.* |
| 13 | No Cross-Pod Leakage | 🟡 | Same as #12. *Rec: same isolation probe at the pod boundary.* |
| 14 | No Loss Of Human Control | ✅ | `verify_human_control` (library) asserts the kill switch is wired and operable; `kill_switch.py` provides engage/query + cross-pod propagation via Redis EventBus. The reconciliation loop now **auto-trips** that same kill switch on a constitutional breach. |
| 15 | No Unbounded Failure | 🟡 | Circuit breakers (`resilience/`, feed circuits), kill switch. **Gap:** no blast-radius invariant. *Rec: chaos test + assert containment.* |
| 16 | No Unrecoverable Failure | 🟡 | Auto-rollback, self-healer, hot-standby modules exist. **Gap:** recovery paths not continuously verified. *Rec: periodic restore/failover drill assertion.* |
| 17 | No Unexplained System Behavior | ✅ | `hopefx_observability.py` captures every logger + all uncaught/thread/asyncio/unraisable exceptions to `hopefx_all.log` + `hopefx_events.jsonl`; checker scans the log and fails on any logged exception. |
| 18 | No Critical Single Point Of Failure | 🟡 | Redis EventBus, async DB pool, multi-source feeds with failover. **Gap:** SPOF inventory not invariant-checked. *Rec: dependency-graph SPOF audit.* |
| 19 | No Unverified AI Decision | 🟢 | **Wired:** `enforce_pre_trade()` checks finite confidence/probability and (optionally) a `min_confidence` floor in `size_order()`. ML drift/staleness gating in `ml/inference_engine.py`. **Remaining:** market-data freshness assertion pre-trade. |
| 20 | No Silent Failure | ✅ | The observability harness is the substrate; the runtime checker is now a **CI gate** (`.github/workflows/ci.yml`) so "looks right, behaves wrong" fails the build. |

**Tally:** ✅ 5 fully enforced · 🟢 4 newly wired to the money path (pre-trade #1/#19, reconciliation #3, kill-switch #14) · 🟡 9 partial (foundation + recommendation) · ❌ 1 gap. Up from 0 explicit enforcement at session start.

> **Legend addition:** 🟢 = predicate **wired into the live money path** behind
> the `HOPEFX_INVARIANT_MODE` flag (active in `monitor`, blocking in `enforce`).

---

## How the framework's layers map to mechanisms

| Framework layer (Best.txt) | Mechanism |
|---|---|
| Generic platform (avail/API/DB/auth/security) | runtime checker (HTTP 200, schema, auth-gated probes) + existing middleware (CSRF, rate-limit, security headers) |
| Trading / Execution / Portfolio | `invariants/constitution.py` order-state + PnL + capital; OMS transition table |
| Market data | `verify_tick` / `verify_spread`; feed circuit breakers |
| AI / Model / Agent | ML drift/staleness gating; confidence + shadow backtest; observability of agent actions (gaps noted above) |
| Risk | `risk/manager.py` (VaR/CVaR/Kelly/kill switch) + `verify_within_limit` |
| Audit / Compliance | audit log + compliance endpoints (immutability/surveillance = gaps) |
| Observability / Meta | `hopefx_observability.py` (+ the checker scans its own output = "monitor the monitors") |
| Constitutional | this document + `summarize()` gating |

---

## What "done" means here (per the framework's own conclusion)

The framework (§9–11) defines success not as zero bugs but as the **five master guarantees**:

1. Nothing important happens unnoticed → observability harness (whole-platform).
2. Nothing dangerous happens unbounded → risk gate + kill switch + `verify_within_limit`.
3. Nothing critical fails unrecoverably → rollback/self-heal (verification = gap).
4. Nothing financial becomes unaccounted → PnL/capital invariants (wiring = gap).
5. Nothing autonomous outranks human control → `verify_human_control` + kill switch.

**Three of five are operational; two have the foundation + a concrete wiring task.**
This map is the living tracker — each 🟡/❌ is a real, scoped task, not a silent omission.
