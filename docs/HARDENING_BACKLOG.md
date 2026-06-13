# HOPEFX Top‑Tier Hardening Backlog

Phase‑1 deliverable of the staged hardening program. This is a **concrete,
repo‑specific** backlog grounded in actual code audits — not generic advice.
It records what is already in place, what was fixed, and what remains, ranked by
risk to the critical path: **signal → risk → execution → broker**.

> Scope note: items reference real `file:line` locations. Severity reflects
> impact on capital/correctness, not effort. "Fixed" items link to the commit
> intent; "Open" items include a recommended minimal fix.

---

## 0. Plan assessment (what already exists — do not rebuild)

The proposed staged plan is sound, but **Phase 2 (quality gates) is largely
already implemented** in this repo. Verified present:

| Gate | Where |
|------|-------|
| ruff + ruff-format | `.pre-commit-config.yaml`, `ci.yml` PR gate (changed files) |
| bandit | pre-commit + `security-scan.yml` (`api auth brokers config core execution ml risk strategies`) |
| detect-secrets + custom `check-secrets` | pre-commit |
| mypy **strict** | `ci.yml` — `risk/analytics.py`, `risk/advanced_analytics.py`, `api/` |
| pytest + coverage gates (80%) | `tests.yml` — `risk/`, `execution/`, `kill_switch.py`, `brokers/` |
| dependency / supply-chain | pip-audit, Trivy, CodeQL, Codacy, Fortify |
| runtime safety defaults | `PAPER_TRADING=true`, `IS_FORCE_TLS`, `STALE_MODEL_BLOCK=true` |
| model integrity | `ml/verify_model.py` (SHA-256 vs `registry.json`) in retrain CI |

**Implication:** effort should go to (a) the **open findings** below and (b)
**widening existing gates** (e.g. mypy-strict scope), not standing up new CI.

---

## 1. Fixed this hardening pass (verified, committed)

Critical-path safety and correctness defects closed, each with tests:

- **Kill switch was a silent no-op** on the pre-trade gate, ExecutionEngine, and
  nuclear-signal paths — now fails closed via the module singleton.
- **OMS booked phantom orders** when a broker response lacked an explicit status
  — now requires positive acceptance confirmation.
- **Decision engine ignored ML output and swallowed the stale-model block**
  (`predict()` dict mishandled → `KeyError`; `RuntimeError` eaten) — now uses
  calibrated confidence and fails closed on stale/drift.
- **CVaR gate false-blocked profitable accounts** (`abs(mean(tail))`) — now a
  true expected-shortfall (`max(0, -mean(tail))`).
- **Position-sizing equity TOCTOU** — `size_order` now snapshots all gate inputs
  under one lock and takes `equity_override`; no shared-state mutation.
- **Stale/future-dated ticks reached the price surface** — orchestrator
  freshness gate matched to DQE threshold + future-tick rejection in
  `validate_tick`.
- **LLM-generated code execution** gated behind `LLM_CODE_EXECUTION_ENABLED`
  (fail closed).
- **Money-input caps** on accounts/payments/billing; **KYC enforced** on fiat
  withdrawal.
- **Configurable feed quorum** (`MIN_FEED_QUORUM`) for gold consensus.
- **Least-privilege gates** on the allocator pod-return and security-dashboard
  telemetry endpoints.
- **Test infrastructure**: fixed a systemic `Path(__file__).parent.parent` bug
  that had silently disabled **~124 security/regression tests** (JWT pentest,
  auth pentest, hardcoded-secret guard, prop-firm enforcement).

---

## 2. Open findings — prioritized

### CRITICAL — fix before any live-capital milestone
_None outstanding._ (The two data-layer criticals — stale-gate doubling and
future-date acceptance — were fixed this pass.)

### HIGH

| ID | Status | Area | Issue | Resolution |
|----|--------|------|-------|------------|
| H1 | ✅ FIXED | resilience | `CircuitBreaker.call()` unlocked: concurrent probes exceed `half_open_max_calls`; stale `successes`. | `asyncio.Lock` around admission + bookkeeping (not the call); `successes=0` on HALF_OPEN entry. |
| H2 | ✅ FIXED | data integrity | Single-source `cross_source_consensus` returned full confidence (no cross-validation). | Multiply confidence by `DQE_SINGLE_SOURCE_CONF_FACTOR` (0.5) when `< 2` inliers; complements `MIN_FEED_QUORUM`. |
| H3 | ◑ PARTIAL | brokers | No `newClientOrderId` → retried submit = duplicate fill. | Adapter now accepts `client_order_id`→`newClientOrderId` + handles `-2010`. **Remaining:** wire OMS id through the heterogeneous dispatch (see §4). |
| H4 | ✅ FIXED | ml supply-chain | `joblib.load` with no checksum at load → pickle RCE on tampered artifact. | `_verify_model_integrity` checks SHA-256 vs `registry.json`; refuse on mismatch, warn when untracked. |

### MEDIUM — all fixed this pass

| ID | Status | Area | Resolution |
|----|--------|------|------------|
| M1 | ✅ FIXED | data integrity | Evaluate staleness before the jump check; skip jump on the first post-gap tick (stale baseline). |
| M2 | ✅ FIXED | look-ahead | Documented exact `as_of` causal scope + warn when supplied (micro/tick/macro are live, non-causal). |
| M3 | ✅ FIXED | persistence | zset member keyed by `ts_ns` (no same-ms collapse); `zrevrangebyscore` returns newest N. |
| M4 | ✅ FIXED | ml monitor | Pass `predicted_direction` (decay monitor now fires) + real OHLCV window when available. |
| M5 | ✅ FIXED | brokers | MT5 market fills validated (reject degenerate, flag PARTIAL); pending orders rest correctly. |
| M6 | ✅ FIXED | auth/compliance | `require_kyc` gates on a wired `compliance_manager` (via app.state/global), not app identity. |
| M7 | ✅ FIXED | UI/transport | WS `enqueue` routes off-loop puts via `call_soon_threadsafe`. |

### Investigated, intentionally NOT changed (rationale recorded)

- **Leverage/margin "hard block" on priceless market orders** — conflicts with a
  verified intended path (`test_successful_execution`): the broker fills market
  orders at market and enforces margin; upstream `size_order` bounds quantity.
  Blocking would break legitimate trading.

---

## 3. Widen existing gates (low-risk, high-leverage)

- **mypy strict scope**: extend beyond `risk/analytics*.py` + `api/` to
  `risk/manager.py`, `risk/pre_trade_gate.py`, `execution/engine.py`,
  `execution/oms.py`, `ml/inference_engine.py`, `core/decision/`. Add
  incrementally (per-file) to avoid a wall of errors.
- **Import discipline**: add a CI check that new code does not import the legacy
  shims (`backtest/`, `strategy/`, `data/`, `websocket/manager.py`) — enforces
  the canonical-vs-legacy rule in `CLAUDE.md`.
- **Dead-file / path-resolution guard**: the resurrected `parents[2]` bug shows
  source-scanning tests need a shared, correct repo-root helper. Add a
  `tests/conftest.py` `REPO_ROOT` fixture and migrate scanners onto it.

---

## 4. Broker-interface idempotency (H3) — design note

A correct fix for duplicate-order risk needs a stable client order id threaded
end to end:

1. `OMS` already carries `client_order_id` (`execution/oms.py:217`).
2. Add `client_order_id: str | None = None` (trailing kwarg, backward compatible)
   to `BrokerBase.place_order` and each adapter.
3. OANDA already idempotency-handles a client ref; Binance maps it to
   `newClientOrderId` and treats `-2010` as "already submitted"; MT5 maps to
   `comment`/`magic`.
4. Verify every caller (`brokers/manager.py`, `execution/*`) passes the OMS id.

Deferred from this pass because it touches the broker contract and all adapters;
it warrants its own change with full caller analysis and adapter tests.

---

## 5. Operational phases (roadmap — process/infra, not in-repo code)

These are valid but are ops deliverables, tracked here for completeness:

- **Observability**: structured logging already uses trace context in parts;
  standardize a request/trade correlation id across API → engine → execution.
- **SLO/alerts**: order failure rate, p99 decision latency, drawdown-breach,
  model-freshness (`STALE_MODEL_BLOCK` age) — wire to the existing Prometheus
  gauges (`hopefx_gold_*`, consensus price/active sources).
- **Incident playbooks**: broker down, Redis down, stale/bad model, runaway
  execution (kill-switch drill). Reference the kill-switch flag-file/env/Redis
  latch precedence already in `kill_switch.py`.
- **Release**: feature-flag new behavior (pattern established:
  `LLM_CODE_EXECUTION_ENABLED`, `MIN_FEED_QUORUM`); canary in paper mode first,
  then capped live exposure.
- **Governance**: weekly legacy-shim retirement; monthly dependency review
  (pip-audit/Trivy already run); quarterly retrain + drift audit
  (`quarterly_retrain.yml` exists).

---

## 6. Status

All HIGH and MEDIUM findings are resolved except the **broad half of H3** —
wiring the OMS `client_order_id` through the heterogeneous broker dispatch to
each adapter (the Binance adapter already accepts and honours it; see §4). That
remains deferred as a dedicated change with full caller analysis + adapter tests,
to avoid an unverified rewrite across ~15 adapters.

Remaining (non-blocking, low-risk):
- **§3 gate-widening**: extend mypy-strict scope incrementally; add a legacy-import
  discipline CI check (only after confirming no current code trips it).
- **§5 operational** items (observability/SLO/playbooks/governance): process/infra.
</content>
