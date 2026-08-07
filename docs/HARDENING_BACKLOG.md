# HOPEFX Top‑Tier Hardening Backlog

Phase‑1 deliverable of the staged hardening program. This is a **concrete,
repo‑specific** backlog grounded in actual code audits — not generic advice.
It records what is already in place, what was fixed, and what remains, ranked by
risk to the critical path: **signal → risk → execution → broker**.

> Scope note: items reference real `file:line` locations. Severity reflects
> impact on capital/correctness, not effort. "Fixed" items link to the commit
> intent; "Open" items include a recommended minimal fix.

---

## Round 2 — deep audit of previously-untouched areas (all fixed/verified)

Money/compliance, real-time transport, order-routing/exit, secrets:

| Sev | Area | Issue | Resolution |
|-----|------|-------|------------|
| CRITICAL | payments | AML withdrawal gate failed OPEN (`except: (allowing)`) | Fail closed on compliance error |
| CRITICAL | payments | KYC status read from a non-existent Wallet field → always "unverified" | Resolve real status via `compliance_manager.is_kyc_approved` |
| HIGH | monetization | Affiliate self-referral + arbitrary `referred_user_id` from body | Reject self-referral; bind referred user to authed caller |
| HIGH | monetization | Stripe webhook had no replay/idempotency → free end_date extends | Dedup by event id (bounded FIFO) |
| HIGH | api/ws | Private channels (account/equity/risk) delivered via empty-sub firehose | Private channels require explicit subscribe |
| HIGH | api/ws | `/ws/notifications` + `/ws/audit-events` bypassed Redis TLS enforcement | Route via `cache.redis_client.get_redis` |
| CRITICAL | execution | SL/TP monitor could close the WRONG same-symbol position | Verify position_id before PM close |
| CRITICAL | execution | SL/TP partial fills booked as full flat (naked remainder) | Detect + CRITICAL alert on partial |
| HIGH | execution | SL/TP booked P&L at trigger price, not actual fill | Use broker fill price |
| HIGH | execution | SL/TP `_get_mid` acted on stale ticks (feed stall → blind net) | Reject stale ticks (`SLTP_MAX_TICK_AGE_S`) |
| HIGH | routing | Both smart routers failed over on TIMEOUT → duplicate fills | Treat timeout as unknown; no re-route |
| MEDIUM | execution | FIX-fallback rounded OANDA units to 0 (silent no-op order) | Reject zero-unit orders |
| MEDIUM | config | Vault `_derive_key` used PBKDF2 despite advertising Argon2id | Switch to Argon2id |
| n/a | prop_firms | Daily DD == total DD | Confirmed conservative/fail-safe (over-blocks); dead `drawdown_mode` removed; precise daily DD needs a rollover snapshot hook (documented) |
| n/a | tests | More `parent.parent` repo-root path bugs (paper_runner, ml_training_pipeline, k6) | Fixed to `parents[2]`; resurrected dormant tests |

Open (lower-priority, documented for next pass):
- **Sentry scrub gaps** (`monitoring/sentry_config.py`): also scrub `logentry`/
  `breadcrumbs`/`contexts`; broaden OANDA-token regex.
- **redis_state crash-recovery** (`execution/redis_state.py`): reconcile restored
  orders/positions against live broker state on boot; prune orphan index members.
- **Persistent audit log** for subscription/affiliate money actions; back the
  in-memory monetization managers with a DB.
- **Affiliate payout atomicity**: per-referral partial settlement + per-affiliate
  lock to remove the TOCTOU double-pay window.
- **WS query-string token** on notifications/audit endpoints (leaks into logs):
  move to in-band auth handshake — deferred (client-contract change).

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
| H3 | ✅ FIXED | brokers | No `newClientOrderId` → retried submit = duplicate fill. | Binance adapter accepts `client_order_id`→`newClientOrderId` + handles `-2010`; ExecutionEngine forwards `request_id` as `client_order_id` to any broker whose signature accepts it (others unaffected). |
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

**All HIGH and MEDIUM findings are resolved.** H3 now wires `client_order_id`
on the canonical ExecutionEngine path (forwarded only to brokers whose signature
accepts it) in addition to the Binance adapter's `newClientOrderId` handling.

Verified: full fast unit suite (`pytest -m "not slow and not e2e"`, excluding two
files that need `matplotlib`) passes with all declared deps installed.

Remaining (non-blocking, low-risk — not defects):
- **§3 gate-widening**: extend mypy-strict scope incrementally; add a legacy-import
  discipline CI check (only after confirming no current code trips it).
- **§5 operational** items (observability/SLO/playbooks/governance): process/infra.
- **Data note**: `ml/saved_models/stacking_ensemble.pkl` SHA-256 does not match its
  `registry.json` entry (stale registry vs artifact) — reconcile via the retrain
  pipeline; the active `advanced_oos.pkl` matches and loads fine.

---

## Round 3 — Slice 1: money path (signal → risk → OMS → broker)

Scope: `core/decision/HOPEFXDecisionEngine.py`, `risk/manager.py`,
`execution/trade_executor.py`, `execution/oms.py`, `brokers/`.
Method: invariants enumerated first, then traced in code (see
`docs/AUDIT_PLAYBOOK.md`). All findings below are **CONFIRMED** — traced to a
specific line and a reproducible failure scenario. **None are fixed yet.**

The theme: the money path has **two parallel implementations** (the standalone
`hopefx_engine.py` and the API's `HOPEFXDecisionEngine` → `TradeExecutor`), and
several controls are wired into only one of them. The decision-engine path —
the one the FastAPI app uses — is missing gates the standalone engine has.

| ID | Sev | Area | Issue | Location |
|----|-----|------|-------|----------|
| S1-01 | CRITICAL | brokers/decision | Live OANDA blocks 100% of trades: `AccountInfo` has no `.get()` | `brokers/oanda.py:109`, `HOPEFXDecisionEngine.py:457` |
| S1-02 | CRITICAL | decision | Fabricated $100k equity fallback contradicts the guard 20 lines above it | `HOPEFXDecisionEngine.py:475` |
| S1-03 | CRITICAL | risk/execution | Drawdown circuit breaker does not halt the sizing path (two halt flags) | `trade_executor.py:592`, `risk/manager.py:728,1665` |
| S1-04 | HIGH | risk | Max-open-positions gate is dead on the decision-engine path | `risk/manager.py:748`, `trade_executor.py` |
| S1-05 | HIGH | execution | Risk-approval token is forged when absent — "No Unauthorized Trade" can never fail | `trade_executor.py:330` |
| S1-06 | HIGH | risk | Kelly sizing is a constant — signal quality does not affect size | `risk/manager.py:1056-1058,1241-1246` |
| S1-07 | MEDIUM | risk | Position floor defeats every risk-scaling factor | `risk/manager.py:796-799` |
| S1-08 | MEDIUM | risk | `existing_positions` silently discarded into `**kwargs` | `risk/manager.py:1043`, `HOPEFXDecisionEngine.py:489` |
| S1-09 | MEDIUM | risk | `direction` never passed — sizing always computed as "long" | `HOPEFXDecisionEngine.py:481-490` |
| S1-10 | MEDIUM | decision | ML phase-store adjustments fail open (bare `except: pass`) | `HOPEFXDecisionEngine.py:404-413` |
| S1-11 | LOW | compliance | Compliance audit-trail write failure swallowed at `debug` level | `HOPEFXDecisionEngine.py:583-584` |

### S1-01 — Live OANDA blocks every trade (CRITICAL)

`brokers/oanda.py:109` defines a **second, incompatible** `AccountInfo`
dataclass (fields: `account_id, currency, balance, nav, unrealized_pnl,
margin_used, margin_available, positions_count, timestamp`). It is a plain
dataclass with **no `.get()` and no `__getitem__`**, unlike
`brokers/base.py:278` which provides both plus an `equity` field.

`AsyncOANDAConnector` is an alias for `OANDABroker` (`brokers/oanda.py:634`),
so `BROKER_TYPE=oanda` wires the class returning the *oanda-local* type
(`core/startup_factories.py:1151-1153`).

The decision engine then does dict-style access on it:

- `HOPEFXDecisionEngine.py:457` — `account_info = await broker.get_account_info()`
- `HOPEFXDecisionEngine.py:468` → `risk/manager.py:1656` — `account_info.get("equity")`

**Failure scenario:** operator sets `BROKER_TYPE=oanda` for the live milestone.
Every tick reaches phase 3, `assess_risk` raises `AttributeError: 'AccountInfo'
object has no attribute 'get'`, the broad handler at
`HOPEFXDecisionEngine.py:505` catches it, and the result is
`RISK_BLOCKED` with `gate_reason="risk error: ..."`. The system trades **zero**
times and the dashboard attributes it to a risk limit, not a wiring bug. Paper
mode is unaffected because `PaperTradingBroker` returns the *base* `AccountInfo`
(`brokers/paper_trading.py:23`) — so this breaks on exactly the switch that is
the next milestone.

**Minimal fix:** delete the duplicate dataclass in `brokers/oanda.py` and return
`brokers.base.AccountInfo` (mapping `NAV → equity`), as the sync
`OANDAConnector` already does at `brokers/oanda.py:895-902`.

### S1-02 — Fabricated $100k equity (CRITICAL, latent)

`HOPEFXDecisionEngine.py:447-455` deliberately blocks when no broker is present,
with the comment *"Do NOT fabricate a $100k account and size against it"*.
Twenty lines later, line 475 does exactly that:

```python
equity: float = float(account_info.get("equity", 100_000.0))
```

`AccountInfo.get()` (`brokers/base.py:291`) is `getattr(self, key, default)` —
it returns the default for a **missing field**, not just a missing dict key.
Any broker whose account object lacks an `equity` attribute silently sizes
against $100,000.

**Failure scenario:** the natural fix for S1-01 is to add a `.get()` shim to the
oanda-local `AccountInfo` (which has `nav`, not `equity`). That converts a
fail-closed bug into a silent one: a $2,000 live account sizes every position
against $100,000 — **50× intended exposure** on the first live trade. The
sizing clamp at `risk/manager.py:1081` does not help, because `assess_risk`
already called `update_equity(100_000)` at `risk/manager.py:1661`, so
`true_equity` used by the clamp is the same fabricated number.

**Minimal fix:** no default — block when equity is absent or ≤ 0, matching the
stated intent at line 447. Additionally: `assess_risk` reading
`get("equity") or get("balance")` (`risk/manager.py:1656`) silently falls back
to **balance**, which excludes unrealized P&L — a drawdown gate computed on
balance is blind to floating losses on open positions.

### S1-03 — Drawdown circuit breaker does not stop new orders (CRITICAL)

`RiskManager` carries **two halt flags**: `_halt` and `_trading_halted`.
`_halt_trading()` (`risk/manager.py:1355-1359`) correctly sets both, persists
the halt, and fires the app kill switch.

`TradeExecutor._trigger_drawdown_halt_if_needed()`
(`execution/trade_executor.py:585-595`) bypasses that method and sets the
attribute directly:

```python
self.risk_manager._trading_halted = True
self.risk_manager._halt_reason = reason
```

But the two functions the decision engine calls read **only `_halt`**:

- `risk/manager.py:728` — `halted = self._halt` (in `size_order`)
- `risk/manager.py:1665` — `if self._halt:` (in `assess_risk`)

**Failure scenario:** account drawdown crosses `DRAWDOWN_HALT_PCT` after a
losing close. The executor logs `DRAWDOWN CIRCUIT BREAKER TRIGGERED — halting
trading` at WARNING and sets `_trading_halted=True`. On the very next tick,
phase 3 calls `assess_risk` (`_halt` is False → `can_trade=True`) then
`size_order` (`_halt` is False → returns a normal size), and a new order is
routed. The operator is looking at a log line that says trading is halted while
the system keeps opening positions. The halt is also never persisted
(`_persist_halt_state()` is skipped) and the app-level kill switch never fires,
so it does not survive a restart either.

**Minimal fix:** have `_trigger_drawdown_halt_if_needed` call
`risk_manager._halt_trading(reason)` instead of assigning the attribute; make
`size_order`/`assess_risk` read `self._halt or self._trading_halted` as the
other six call sites already do (`risk/manager.py:898,1513,2045,2165,2194,2218`).

### S1-04 — Max-open-positions gate never fires (HIGH)

`size_order` blocks at `risk/manager.py:748` when
`self._state.open_positions >= _MAX_OPEN_POSITIONS` (default 3). That counter is
incremented only by `notify_position_opened()` (`risk/manager.py:689`), whose
**only production callers are in the standalone `hopefx_engine.py`** (lines 718,
1293, 1356, 1549). `TradeExecutor` never calls it — its only `risk_manager`
interactions are `update_equity`, `record_trade_outcome`, and the halt
assignment (`execution/trade_executor.py:500,508,592`).

**Failure scenario:** running via the FastAPI app (`run.py --mode api`),
`open_positions` stays `0` for the lifetime of the process. The gate compares
`0 >= 3` and never fires, so the decision engine opens an unbounded number of
concurrent positions. `RiskManager.on_fill()` (`risk/manager.py:1103`) exists
for this purpose but has **no production caller at all** — only
`tests/unit/test_risk_manager_coverage.py:474`.

**Minimal fix:** call `notify_position_opened/closed` from `TradeExecutor` on
fill and on close, or derive the count from `position_tracker` inside
`size_order` rather than from mutable local state.

### S1-05 — Risk-approval token is forged (HIGH)

`risk/manager.py:116-118` documents `risk_approval_token` as *"Proof this sizing
passed the full risk gate — copied onto the Order so the OMS can refuse any
order that never went through risk (No Unauthorized Trade)"*, and
`invariants/enforcement.py:556` checks it.

`execution/trade_executor.py:330` manufactures one when it is missing:

```python
signal["risk_approval_token"] = signal.get("risk_approval_token") or f"rat-{signal.get('signal_id', 'te')}"
```

The decision engine's `exec_signal` (`HOPEFXDecisionEngine.py:524-533`) carries
neither `risk_approval_token` nor `signal_id`, so **every** decision-engine order
is stamped with the literal constant `"rat-te"`, and `decision_id` falls back to
the same string on the next line.

**Failure scenario:** the authorization invariant is a truthiness check, so it
passes on the forged value. Any path reaching `TradeExecutor.execute_signal()`
with a hand-built dict — a manual API call, a strategy that bypasses
`size_order` entirely, a future refactor — is auto-issued proof it passed risk.
The control cannot detect the one thing it exists to detect. This is currently
masked because `HOPEFX_INVARIANT_MODE` defaults to `monitor`
(`invariants/enforcement.py:78`), so the OMS only logs; flipping to `enforce`
per `docs/INVARIANT_ROLLOUT.md` will **not** fix it — the check will still pass.

**Minimal fix:** propagate `sizing.risk_approval_token` from
`HOPEFXDecisionEngine._phase3_risk` into `exec_signal`, and make
`trade_executor.py:330` reject rather than mint a missing token.

### S1-06 — Kelly sizing is a constant (HIGH)

Three defects compound in `calculate_position_size`:

1. **`probability` is never passed.** The decision engine
   (`HOPEFXDecisionEngine.py:481-490`) omits it, so the default `0.55`
   (`risk/manager.py:1038`) is used on every trade.
2. **Confidence is floored at 0.7.** `risk/manager.py:1058` computes
   `effective_confidence = max(confidence, signal_strength)` where `confidence`
   defaults to `0.7`. Since the ML gate admits signals from `0.52` upward
   (`HOPEFX_ML_THRESHOLD`), any ML confidence below `0.7` is discarded and
   `0.7` is used instead.
3. **Kelly saturates.** `_kelly()` (`risk/manager.py:1241-1246`) returns
   `max(0.0, min(kelly, _MAX_POSITION_PCT))` — it caps a *bankroll fraction*
   with a *position-size* percentage (`0.05`). With `p=0.55, conf=0.7`:
   `b = 2.1`, `kelly = 0.336` → clamped to `0.05`. The clamp binds for any
   `p > 0.356`.

**Failure scenario:** `base_notional = equity × kelly_f × _KELLY_FRACTION`
= `equity × 0.05 × 0.25` = **exactly 1.25% of equity on every single trade**,
whether the ML gave 0.53 or 0.95. The Kelly criterion, the ML probability, and
the signal confidence have no effect on size. A 0.53-confidence marginal signal
is sized identically to a 0.95-confidence one.

**Minimal fix:** pass `probability=result.ml_probability` from the decision
engine; drop the `0.7` default (use `signal_strength` directly); cap the Kelly
fraction with its own constant rather than reusing `_MAX_POSITION_PCT`.

### S1-07 — Position floor defeats all risk scaling (MEDIUM)

`risk/manager.py:796-799`:

```python
final_notional = max(
    equity * _MIN_POSITION_PCT,
    min(final_notional, equity * _MAX_POSITION_PCT),
)
```

Every risk-reducing factor — `quality_f` (data quality), `sentiment_f`,
`impact_f` (macro), `dd_f` (drawdown) — multiplies into `final_notional`
*before* this floor. When they collectively drive the size to zero, the `max()`
lifts it back to `equity × 0.001`.

**Failure scenario:** data quality is degraded, drawdown is elevated, and a
high-impact macro event is live. Every scaling factor pushes toward "do not
trade", the computed notional is ~0 — and the system still opens a position at
0.1% of equity. Combined with S1-04 (no open-position cap on this path), these
minimum-size positions accumulate without bound. Only the hard early-return
gates can actually prevent a trade; the graduated risk factors cannot.

**Minimal fix:** apply the floor only when `final_notional > 0`, and return zero
size when the scaled notional falls below the minimum viable position.

### S1-08 / S1-09 — Sizing inputs silently discarded (MEDIUM)

`calculate_position_size` accepts `**kwargs` (`risk/manager.py:1043`) and pops
only `price`. The decision engine passes `existing_positions=positions`
(`HOPEFXDecisionEngine.py:489`) — it lands in `**kwargs` and is **discarded**.
There is no portfolio-level exposure or correlation check at sizing time; the
only positional constraint is the count-based gate that S1-04 shows is dead.

Likewise `direction` is never passed, so `_MinimalSignal` is built with the
default `"long"` (`risk/manager.py:1036,1065`) for **short trades too**. The
returned `PositionSizingResult.direction` is wrong in the audit record, and
`_compute_stop_take` (`risk/manager.py:818`) computes long-shaped stops. On the
decision-engine path those are overwritten at lines 1094-1097, but
`hopefx_engine.py:1254` consumes `sized.stop_loss_usd` directly.

**Minimal fix:** make the signature explicit (no silent `**kwargs`) so a
mis-named argument raises instead of vanishing; pass `direction`.

### S1-10 / S1-11 — Fail-open ML adjustments, silent compliance failures

`_apply_phase_stores` (`HOPEFXDecisionEngine.py:404-413`) wraps anomaly
weighting, online blending, and deep-ensemble blending in a bare
`except Exception: pass`. These adjustments exist to *reduce* confidence on
anomalous data; when they throw, the unadjusted probability is used and the
trade proceeds. A persistent import or runtime error in `core.signal_engine`
disables all three silently — there is no counter or warning, only `pass`.

`HOPEFXDecisionEngine.py:583-584` logs a failed compliance-audit write at
`debug` level. A regulatory audit trail that fails to record a trade should not
be observable only at debug verbosity.


