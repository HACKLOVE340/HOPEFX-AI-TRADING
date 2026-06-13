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

| ID | Area | File:line | Issue | Recommended fix |
|----|------|-----------|-------|-----------------|
| H1 | resilience | `resilience/circuit_breaker.py:59-82` | Generic `CircuitBreaker.call()` has **no lock**: concurrent coroutines all flip OPEN→HALF_OPEN and exceed `half_open_max_calls`; `successes` not reset on entering HALF_OPEN (stale count can prematurely close). | Guard `call()` with `asyncio.Lock` (as `ServiceCircuitBreaker` does); reset `successes=0` on HALF_OPEN entry. |
| H2 | data integrity | `data_layer/quality/engine.py:463-543` | `cross_source_consensus` with a single live source returns that source's price at **full confidence** — no cross-validation, no `source_count` flag. | Return degraded confidence (or expose `source_count`) when `len(inliers) < 2` so risk gates can react. Pairs with `MIN_FEED_QUORUM`. |
| H3 | brokers | `brokers/binance.py:139-218` | No `newClientOrderId`; a retried submit becomes a **new order** → duplicate fills on transient network errors. | Thread a deterministic `client_order_id` through the broker interface; map Binance `-2010`/duplicate to "already submitted". **Requires interface change — see §4.** |
| H4 | ml supply-chain | `ml/live_inference.py:199`, `ml/inference_engine.py:1433` | `joblib.load` of model artifacts with **no checksum at load time** (registry/CI verifies separately; arbitrary `model_path` is unverified) → pickle RCE on tampered artifact. | Compute SHA-256 of resolved path, compare to `registry.json` when a tracked entry exists; refuse on mismatch, warn (not fail) when untracked (dev/test). |

### MEDIUM

| ID | Area | File:line | Issue | Recommended fix |
|----|------|-----------|-------|-----------------|
| M1 | data integrity | `data_layer/quality/engine.py:197,317-343` | Post-silence recovery: first tick after a >stale gap is only marked STALE; jump check runs against a stale `last_mid` (spurious reject or silent accept). | Reset jump baseline (`last_mid`) when `is_stale()` is true before jump check. |
| M2 | look-ahead | `data_layer/orchestrator.py:839-905,1116-1165` | `get_ml_features(as_of=...)` forwards `as_of` only to sentiment/calendar; tick/micro/OHLCV ignore it → look-ahead bias in any causal/backtest use. | Thread `as_of` into tick/micro/OHLCV accessors, or document that `as_of` is non-causal for those and forbid in training pipelines. |
| M3 | persistence | `data_layer/tick_store.py:373-434` | Redis zset member keyed by `ts_ms:bid|ask|vol|src`; same-ms identical ticks collapse (silent loss); unbounded read returns oldest-first window. | Include `ts_ns`/monotonic counter in member; use `zrevrangebyscore` for newest-first bounded reads. |
| M4 | ml monitor | `execution/trade_executor.py:735-747` → `ml/inference_engine.py:472-518` | Online-learning/`update_online` fed a feature schema it doesn't consume (`close` guard no-ops) → live-accuracy degradation monitor never fires. | Pass real OHLCV window + `predicted_direction`, or align `update_online` to the outcome schema the executor sends. |
| M5 | brokers | `brokers/mt5.py:251-272` | MT5 `place_order` reports requested price/qty on degenerate `order_send` results; partial fills shown as FILLED; no `volume>0`/`price>0` guard. | Validate `result.volume>0 and result.price>0`; set `PARTIAL` when `volume<quantity`; reject degenerate results (mirror OANDA `_parse_fill`). |
| M6 | auth/compliance | `api/auth.py:356-357` | `require_kyc` bypasses for any app instance ≠ the `app.py` singleton; `api/server.py`'s separate app (real order routes) would skip KYC if served. | Gate on whether `compliance_manager` is wired (resolve via `request.app.state`/global), not app identity — **carefully**, to preserve test isolation. |
| M7 | UI/transport | `data_layer/orchestrator.py:220-267` | `_WebSocketBroadcaster._connections` mutated without a lock; `enqueue` may cross threads onto an asyncio.Queue (single-loop contract). Monitoring path only. | Use `loop.call_soon_threadsafe` if cross-thread; guard the set with a lock. |

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

## 6. Suggested execution order

1. **H1** circuit-breaker lock (small, isolated, fail-fast correctness).
2. **H2** single-source consensus confidence (pairs with `MIN_FEED_QUORUM`).
3. **H4** model checksum at load (supply-chain; guard untracked paths to avoid
   breaking dev).
4. **H3** broker idempotency (interface change; §4).
5. **M1–M7** as capacity allows; **§3** gate-widening in parallel (cheap wins).
</content>
