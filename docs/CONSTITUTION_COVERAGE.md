# Platform Constitution — Coverage Map

> Honest, tracked status of every constitutional rule from the invariant
> framework (`Best.txt`) against the **actual** HOPEFX codebase. This is the
> "account for everything" artifact: each rule is **Enforced**, **Partial**
> (with location), or **Gap** (with severity + recommendation). It is the
> roadmap the framework's own sections 9–11 call for — invariants are a program
> of work, not a one-shot. Nothing in the file is left unaddressed here.

**Legend:** ✅ Enforced · 🟡 Partial · ❌ Gap
**Mechanisms now in place:**
- **`invariants/` — ~65 pure invariant predicates across 6 domain modules (35 tests, all green):**
  - `constitution.py` — order state machine, PnL/capital conservation, duplicate-id, tick/spread, finiteness, human control
  - `market.py` — order book, multi-feed agreement, freshness/staleness, clock drift, future-event, event sequence, causal order, market-open/halt, delisting
  - `risk.py` — daily loss, drawdown, VaR, leverage, margin buffer, liquidation distance, liquidity, per-dimension exposure, concentration, dependency, catastrophic-loss kill triggers
  - `ai.py` — model-approved/hash, drift, confidence, entropy, ensemble dominance, consensus, feature/embedding integrity, hallucination pre-trade guard, explainability, agent authority/tool/loop/self-escalation/memory ownership
  - `execution.py` — slippage, latency budget, broker reconciliation, reported-vs-actual reality, settlement balance, full pre-trade gate
  - `governance.py` — no-lookahead, no-data-leakage, after-cost viability, pod isolation, audit immutability/completeness, segregation-of-duties, dual control, config drift, deployment gates, human supremacy
- `scripts/runtime_invariant_check.py` — boots app + probes endpoints + asserts output invariants + scans the event log
- `hopefx_observability.py` — whole-platform capture (DEBUG) + uncaught/thread/asyncio/unraisable hooks → **No Silent Failure** substrate

---

## The 20 Constitutional Rules

| # | Rule | Status | Where enforced / gap & recommendation |
|---|------|--------|----------------------------------------|
| 1 | No Unauthorized Trade | 🟡 | `risk/manager.py` PreTradeGate + `kill_switch.py` gate the order path; `verify_within_limit` library check. **Gap:** no invariant asserting AI cannot reach the broker bypassing the gate. *Rec: add a runtime assertion that every broker order carries a risk-approval token.* |
| 2 | No Unauthorized Capital Movement | 🟡 | Wallet/withdrawal endpoints require auth + role. **Gap:** no `verify_capital_equation` wired to a ledger endpoint. *Rec: expose a treasury/ledger reconciliation endpoint, assert the capital equation each cycle.* |
| 3 | No Hidden Loss | 🟡 | `verify_pnl_reconciliation`, `verify_no_negative_balance` (library + tests). **Gap:** not yet asserted against a live account/PnL endpoint (account exposes realized/unrealized but no single `total_pnl`). *Rec: add `total_pnl` to `/trading/account`, wire the check.* |
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
| 14 | No Loss Of Human Control | ✅ | `verify_human_control` (library) asserts the kill switch is wired and operable; `kill_switch.py` provides engage/query + cross-pod propagation via Redis EventBus. |
| 15 | No Unbounded Failure | 🟡 | Circuit breakers (`resilience/`, feed circuits), kill switch. **Gap:** no blast-radius invariant. *Rec: chaos test + assert containment.* |
| 16 | No Unrecoverable Failure | 🟡 | Auto-rollback, self-healer, hot-standby modules exist. **Gap:** recovery paths not continuously verified. *Rec: periodic restore/failover drill assertion.* |
| 17 | No Unexplained System Behavior | ✅ | `hopefx_observability.py` captures every logger + all uncaught/thread/asyncio/unraisable exceptions to `hopefx_all.log` + `hopefx_events.jsonl`; checker scans the log and fails on any logged exception. |
| 18 | No Critical Single Point Of Failure | 🟡 | Redis EventBus, async DB pool, multi-source feeds with failover. **Gap:** SPOF inventory not invariant-checked. *Rec: dependency-graph SPOF audit.* |
| 19 | No Unverified AI Decision | 🟡 | Confidence gating + shadow backtest in nuclear pipeline; ML drift/staleness gating in `ml/inference_engine.py`. **Gap:** no `confidence ≥ min` invariant at the API. *Rec: assert prediction confidence + market-data freshness pre-trade.* |
| 20 | No Silent Failure | ✅ | The observability harness is the substrate; the runtime checker turns "looks right, behaves wrong" into a CI failure (proven on real bugs this session). |

**Tally:** ✅ 5 fully enforced · 🟡 13 partial (foundation + recommendation) · ❌ 1 gap. Up from 0 explicit enforcement at session start.

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
