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
| S1-03 | HIGH | risk/execution | Drawdown halt is not persisted and does not propagate (two halt flags) — *corrected during Slice 2, see note* | `trade_executor.py:592`, `risk/manager.py:728,1665` |
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

### S1-03 — Drawdown halt is not persisted or propagated (HIGH)

> **Corrected during Slice 2.** This was first written up as "the breaker does
> not stop trading". That is **wrong** and the original severity (CRITICAL) was
> too high. `risk/pre_trade_gate.py:354` *does* read `_trading_halted`, and
> `TradeExecutor._execute_open` runs that gate before every order, so orders
> **are** blocked after the breaker fires. The real defects are narrower and are
> described below.


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
losing close. Because the assignment bypasses `_halt_trading()`, three of that
method's four effects are skipped:

1. **The halt is not persisted.** `_persist_halt_state()` never runs, so a
   process restart clears the halt and trading resumes automatically at the
   same drawdown that triggered the breaker.
2. **The app kill switch never fires.** `_halt_trading()` calls
   `ks.activate()` (`risk/manager.py:1363-1368`); the direct assignment does
   not, so no other subsystem is notified and no Redis/cross-pod propagation
   occurs.
3. **`assess_risk` and `size_order` report inconsistent state.** Both read only
   `_halt` (`risk/manager.py:728,1665`), so `assess_risk().can_trade` stays
   `True` and `size_order()` returns a normal size while trading is halted. Any
   API endpoint or dashboard surfacing `can_trade` shows the system as tradable.
   The order is still blocked one stage later by the pre-trade gate, so this is
   a state-reporting and wasted-work defect rather than an unblocked trade.

**Minimal fix:** call `risk_manager._halt_trading(reason)` instead of assigning
the attributes; make `size_order`/`assess_risk` read
`self._halt or self._trading_halted` as the other six call sites already do
(`risk/manager.py:898,1513,2045,2165,2194,2218`).

<details>
<summary>Original (incorrect) write-up, kept for the record</summary>


> ~~The operator is looking at a log line that says trading is halted while the
> system keeps opening positions.~~ Incorrect — the pre-trade gate blocks the
> order. Corrected above.

</details>

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



---

## Round 3 — Slice 2: gates and kill switch (fail-closed audit)

Scope: `risk/gatekeeper.py`, `risk/pre_trade_gate.py`, `kill_switch.py`,
`invariants/enforcement.py`, `compliance/`, `risk/fia_compliance.py`.
Questions asked: does each gate fail **open or closed** when its dependency
errors? Can any gate be bypassed by reaching the broker another way?

**Good news first — these fail closed and are correctly built:**

- `risk/pre_trade_gate.py:282-302` — a check that raises anything other than
  `TradeBlockedError` is wrapped in `RiskManagerError` and **blocks** the trade.
  "A broken risk check is not a pass" is implemented, not just commented.
- `risk/gatekeeper.py:388-403` — FIA compliance errors block the signal.
- `execution/oms.py:163-186` — the OMS kill-switch gate blocks on error.
- `kill_switch.py` — activation persists to a flag file and a state file, the
  env override is read at construction, and a poll loop plus Redis latch
  provide cross-pod propagation.

The defects below are **not** fail-open exception handlers — the previous
rounds cleaned those up. They are gates that are **wired to inputs that never
change**, so the check runs, passes, and is never able to fire.

| ID | Sev | Area | Issue | Location |
|----|-----|------|-------|----------|
| S2-01 | CRITICAL | kill switch | Split-brain: two `KillSwitch` instances; the ops mechanisms drive the one the money path does not read | `app.py:286`, `kill_switch.py:1341`, `pre_trade_gate.py:342` |
| S2-02 | HIGH | gatekeeper | `Gatekeeper.start()` is never called → gate checks 1, 3 and 4 can never fire | `startup_factories.py:3680`, `gatekeeper.py:232` |
| S2-03 | HIGH | gatekeeper | Spread gate (check 11) reads an attribute the signal never has → always 0.0 | `gatekeeper.py:497` |
| S2-04 | HIGH | compliance | FIA controls validate a hardcoded order size of 1.0, env capital, and `daily_pnl=0.0` | `gatekeeper.py:320,336-337` |
| S2-05 | MEDIUM | compliance | FIA 1.3 and 3.1 are always skipped on the decision-engine path | `gatekeeper.py:328,354-360` |
| S2-06 | LOW | risk | Kill-switch check silently passes if the import fails | `pre_trade_gate.py:343-344` |
| S2-07 | LOW | docs | `_run_fia_checks` docstring says errors are "non-blocking"; the code blocks | `gatekeeper.py:308-309` |

### S2-01 — Split-brain kill switch (CRITICAL)

There are **two separate `KillSwitch` objects** in a running process:

| | `app.kill_switch` | `kill_switch.kill_switch` |
|---|---|---|
| Created | `app.py:286` | `kill_switch.py:1341` (module singleton) |
| Redis event bus | yes | **no** |
| `start()` called | yes (`app.py:540`) | **never** |
| Poll loop / flag-file polling | running | **not running** |
| Activated by | `/kill-switch/*` router (`app.py:295`), `RiskManager._halt_trading` (`risk/manager.py:1364`) | `/nuclear/kill_switch/activate` (`api/nuclear.py:104`) |
| **Read by the money path** | **no** | **yes** — `pre_trade_gate.py:342` |

Only the module singleton is consulted before an order reaches the broker. Only
the app instance has the poll loop, the flag file watcher, and Redis cross-pod
propagation. Nothing synchronises them.

**Failure scenarios:**

1. **Operator hits the wrong endpoint.** `POST /kill-switch/activate` (the
   router registered in `app.py`) sets `app.kill_switch._active = True` and
   returns success. `pre_trade_gate._check_kill_switch()` reads the *module
   singleton*, which is still `False` — **orders continue to flow** while the
   API, the logs, and the health endpoint all report the kill switch as active.
   `/nuclear/kill_switch/activate` is the endpoint that actually stops trading.
   Two endpoints, indistinguishable from the outside, opposite effects.
2. **Flag file does nothing.** The documented ops runbook mechanism
   (`kill_switch.flag`, "polled every 2 s — survives process crash") is polled
   only by `app.kill_switch`. The module singleton has no poll loop, so writing
   the flag file never blocks a trade.
3. **Redis cross-pod activation does nothing.** Same reason — the listener runs
   on the app instance only.
4. **Auto-halt does not fire the gate's switch.** `RiskManager._halt_trading`
   activates `app.kill_switch` (`risk/manager.py:1364-1368`); the gate's
   instance stays inactive. (Trading is still blocked, but by the separate
   `_trading_halted` check, not by the kill switch.)
5. **Status is wrong either way.** Health routes are wired to `app.kill_switch`
   (`app.py:959`), so a `/nuclear`-activated kill switch reads as **inactive**
   on the dashboard while trading is in fact blocked.

Only `HOPEFX_KILL_SWITCH=1` works on both, because each reads it in `__init__`
(`kill_switch.py:137`).

**Minimal fix:** delete the `app.py:286` instantiation and have `app.py` import
and start the module singleton, so there is exactly one instance. Add a test
asserting `app.kill_switch is kill_switch.kill_switch`.

### S2-02 — Gatekeeper is never started; three of its checks are inert (HIGH)

`core/startup_factories.py:3680` builds the Gatekeeper inline:

```python
gatekeeper = Gatekeeper(orchestrator=getattr(s, "data_orchestrator", None))
```

`await gatekeeper.start()` is never called — there is no other assignment to
`s.gatekeeper` anywhere in the codebase. `start()` (`gatekeeper.py:232-244`) is
what launches `_breach_listener`, and `_breach_listener` (`gatekeeper.py:422`)
is the **only** production writer of two pieces of state:

- `self._equity.update(equity)` on `reason == "equity_update"`
- `self._kill_active = True` on `reason in ("kill_switch", "kill_event")`

With the listener never running:

- **Check 1 (kill switch, `gatekeeper.py:545`)** — `_kill_active` stays `False`.
  The only other writers are the FIA `KILL_SWITCH` status and
  `activate_kill_switch()`, which has no production caller.
- **Check 3 (daily drawdown, `:555`)** — `_equity.daily_dd` stays `0.0`, so
  `0.0 >= _DAILY_DD_LIMIT` is never true.
- **Check 4 (max drawdown, `:564`)** — same, `max_dd` stays `0.0`.

**Failure scenario:** the account is 8% down on the day. `Gatekeeper.evaluate()`
runs all 11 checks, checks 3 and 4 compare `0.0` against their limits, and the
gate returns `passed=True`. The `metrics()` endpoint reports
`daily_dd_pct: 0.0` and `max_dd_pct: 0.0` regardless of the real account.
Drawdown protection on this path depends entirely on `RiskManager` and
`PreTradeGate`; the Gatekeeper's own drawdown checks contribute nothing.

Note `start()` is also not safe to call as written — it `await`s
`self._signal_consumer()` forever (`gatekeeper.py:244`), so it must be launched
as a task, not awaited during startup.

**Minimal fix:** launch `_breach_listener` from the factory (or from
`__init__`), independently of the event-bus consumer loop; or have
`_run_checks_on_signal` read drawdown from `RiskManager` rather than from a
private tracker that nothing updates.

### S2-03 — Spread gate never fires (HIGH)

`gatekeeper.py:497` sources the spread for check 11:

```python
spread=getattr(signal, "tick_spread", 0.0),
```

The decision engine passes the **brain's** `Signal`
(`HOPEFXDecisionEngine.py:430` → `strategies/base.py:44`), whose fields are
`signal_type, symbol, price, timestamp, confidence, metadata`. There is no
`tick_spread`, so the default `0.0` is always used and
`0.0 > _MAX_SPREAD_USD` is never true.

**Failure scenario:** a news spike widens the XAUUSD spread to $8. The spread
gate — the control specifically meant to keep the system out of that market —
evaluates `0.0 > max` and passes. The order is placed into the spike and pays
the full spread on entry.

**Minimal fix:** read the spread from the orchestrator tick (as checks 5-8
already do via `_get_data_quality` / `_get_blackout`) instead of from a signal
attribute that this path never populates.

### S2-04 — FIA controls validate fabricated inputs (HIGH)

`_run_fia_checks` (`gatekeeper.py:318-338`) builds the order and portfolio dicts
that `FIAComplianceManager.validate_order()` scores, using `getattr` defaults
for fields the brain `Signal` does not carry:

| Field | Line | Value actually used | Should be |
|---|---|---|---|
| `order["size"]` | 320 | **`1.0`** (constant) | the approved position size |
| `order["side"]` | 321 | **`"long"`** (constant) | the signal direction |
| `portfolio_state["capital"]` | 337 | `INITIAL_BALANCE` env, default `100000` | live account equity |
| `portfolio_state["daily_pnl"]` | 336 | **`0.0`** (constant) | realised daily P&L |

`Signal` has no `quantity`, `size`, `direction`, or `daily_pnl` attribute, so
every default binds. Additionally the gate runs **before** sizing in the
decision pipeline (`HOPEFXDecisionEngine.py:430` vs `:481`), so the real size
does not exist yet at this point.

**Failure scenario:** FIA 2024 maximum-order-size and daily-loss-limit controls
are mandatory pre-trade risk controls. They are evaluated here against a
constant size of 1 unit, a constant $100k of capital, and a daily P&L of exactly
zero. The daily-loss control can never trigger — its input is hardcoded to 0.0.
An order of any real size passes the size control, because the control never
sees the real size.

**Minimal fix:** move the FIA call to *after* sizing and pass the approved size,
real direction, live equity, and the risk manager's `daily_pnl`.

### S2-05 / S2-06 / S2-07 — Lower severity

**S2-05:** `has_prices` (`gatekeeper.py:328`) requires `bid > 0 and ask > bid`.
The brain `Signal` carries `price` but no bid/ask, so `has_prices` is always
`False` on this path and FIA 1.3 (price tolerance) and FIA 3.1 (market-data
validation) are filtered out of the results at `:354-360`. This is deliberate
and documented, and the orchestrator data-quality gate is cited as the
compensating control — but it means two of the FIA rules are permanently
inactive for the primary trading path, which should be stated in the compliance
record rather than only in a code comment.

**S2-06:** `pre_trade_gate.py:341-344` — if `from kill_switch import kill_switch`
raises, `ks` is set to `None` and the check returns without blocking. Every
other failure mode in this file blocks; this one passes. The comment says the
import "should never fail", which is exactly the assumption worth removing from
a mandatory control.

**S2-07:** `gatekeeper.py:308-309` documents FIA errors as "logged and treated
as non-blocking so that a misconfigured compliance manager cannot halt all
trading". The code at `:388-403` does the opposite and blocks. The code is
right; the docstring is stale and describes a fail-open policy that would be a
defect if anyone implemented it from the documentation.

### Cross-cutting note

Slices 1 and 2 keep landing on the same root cause: **controls are attached to
state that only one of the two engine implementations maintains.** The
Gatekeeper's equity tracker, `RiskManager.open_positions`, the two halt flags,
and the two kill-switch instances are all examples. A gate whose input is never
written is indistinguishable, in logs and metrics, from a gate that is passing
legitimately — which is why these survived previous audit rounds. Worth a
dedicated fix pass that inventories every gate input and asserts, in a test,
that something writes it on the decision-engine path.

---

## Round 3 — Slice 3: backtest ↔ live parity

Scope: `backtesting/`, `backtest/`, `run.py --mode backtest`, compared against
the live path audited in Slices 1-2.
Question asked: do the backtester and the live engine share signal, sizing and
fill logic — and if not, in which direction does each divergence bias results?

**Every divergence found biases results optimistically.** There is no case where
the backtest is more pessimistic than live.

| ID | Sev | Issue | Location |
|----|-----|-------|----------|
| S3-01 | CRITICAL | The default backtest is **frictionless** — zero spread, zero slippage, zero commission | `engine.py:852-874,321,242-249` |
| S3-02 | HIGH | Signals fill at the **same bar's close** that generated them | `engine.py:431-433` |
| S3-03 | HIGH | Pip conversion hardcoded to the FX 4-decimal convention — 100× wrong for gold | `engine.py:271,273` |
| S3-04 | HIGH | Commission assumes a 100,000-unit FX lot; gold's contract is 100 oz | `engine.py:281` |
| S3-05 | HIGH | Backtest shares **no** signal, risk, or execution code with live | throughout |
| S3-06 | MEDIUM | Two `TransactionCostModel` classes and four engines; the correct cost model is not the one the CLI uses | `engine.py` vs `transaction_costs.py` |

### S3-01 — The default backtest has zero transaction costs (CRITICAL)

Three defaults compound:

1. `DataFrameDataHandler` (`engine.py:852-874`) synthesises each bar as
   `bid = close, ask = close`. The docstring says so plainly: *"bid = close and
   ask = close (mid-price approximation)"*. Therefore `tick.spread == 0.0`.
2. `BacktestEngine.__init__` (`engine.py:321`) falls back to
   `TransactionCostModel(seed=seed)` when no cost model is passed.
3. That model's defaults (`engine.py:242-249`) are `commission_per_lot=0.0`,
   `commission_rate=0.0`, `spread_pips=0.0`, `slippage_pips=0.0`.

`backtesting/cli_runner.py:249` — the path `run.py --mode backtest` uses —
constructs `BacktestEngine(initial_capital=..., data_frequency=...)` and passes
**no cost model**. So `calculate_costs()` returns `slippage = 0.0 * 0.0001 = 0.0`
and `commission = 0.0`, and the fill price is exactly `tick.ask` (== `close`).

**Failure scenario:** a strategy is evaluated on 5-minute XAUUSD bars, takes two
round trips a day for a year (~1,460 round trips) at 100 oz. Real cost is
roughly $0.40-$0.60 per ounce round trip (a 20-30¢ spread on gold plus
slippage) — about **$60,000-$90,000 of costs** that never appear in the equity
curve. Any strategy whose per-trade edge is smaller than the spread shows a
positive Sharpe in backtest and loses money live. This is the single largest
source of optimism in the reported numbers.

The correct machinery **already exists** and is simply not wired in:
`engine_config.py:433,474` handles the gold pip properly
(`pip = 0.10 if price > 100`), `transaction_costs.py` implements a
square-root impact model, and `enhanced_engine.py:1701` accepts a cost model.

**Minimal fix:** make the cost model a required argument of `BacktestEngine`
(no zero-cost default), and have `DataFrameDataHandler` apply a configured
spread around the close instead of `bid = ask = close`. A backtest with no
declared costs should refuse to run rather than silently report gross returns.

### S3-02 — Fills happen on the signal's own bar (HIGH)

`engine.py:399-433`, per bar, in order: process pending orders → update
positions → record equity → **call strategy** → `self._execute_signal(signal,
tick)` using the *same* `tick`.

Because `bid = ask = close`, a signal computed from bar N's close is filled at
bar N's close.

**Failure scenario:** live, that price is already history the moment the bar
closes. The earliest realistic fill is bar N+1's open plus decision and network
latency — the live pipeline adds five phases of work
(`HOPEFXDecisionEngine.process_tick`) before the broker call. On 5-minute gold
bars the close-to-next-open gap is routinely tens of cents, which is the same
order of magnitude as the entire per-trade edge these strategies target. The
`no_lookahead_context` guard at `engine.py:415` is a real control but a
different one — it blocks `shift(-N)` inside *feature* computation and says
nothing about *execution* timing.

**Minimal fix:** queue signals generated on bar N into `pending_orders` and fill
them from bar N+1 (the engine already has a `pending_orders` list and processes
it at the top of each iteration — the plumbing exists).

### S3-03 / S3-04 — Cost conversions use FX conventions on a gold system (HIGH)

`engine.py:271` and `:273`:

```python
slippage = self.slippage_pips * 0.0001  # Convert pips to price
```

This is unconditional. Gold's pip is `$0.10`, as this repo's own
`engine_config.py:433` documents (*"Gold (XAU/USD) pip convention: 1 pip = $0.10"*)
and implements at `:474`. So an operator who explicitly configures
`slippage_pips=3` to model realistic gold slippage gets **$0.0003** applied
instead of **$0.30** — a 1000× understatement, and economically indistinguishable
from zero at a $3,300 price.

`engine.py:281`:

```python
commission = self.commission_per_lot * (quantity / 100000)  # Standard lot size
```

100,000 units is the FX standard lot. A gold contract is **100 oz**. With
quantity expressed in ounces (as `risk/manager.py:813` produces —
`quantity = final_notional / mid_price`), a $7-per-lot commission on a 100 oz
trade books as **$0.007** instead of **$7**.

**Failure scenario:** a user who *does* the right thing — reads the docs, sets
realistic cost parameters — still gets a near-frictionless backtest, and has no
signal that the parameters were ignored. This is worse than S3-01, where at
least the zero is visible in the config.

**Minimal fix:** route both through the symbol-aware pip/contract logic that
`engine_config.py` already implements; delete the hardcoded constants.

### S3-05 — Backtest and live share no code (HIGH)

| Stage | Live (`--mode api`) | Backtest (`--mode backtest`) |
|---|---|---|
| Signal | `StrategyBrain.analyze_joint` — weighted multi-strategy consensus | `MACrossoverStrategy` or `MLInferenceStrategy` (`cli_runner.py:73,147`) |
| Risk / sizing | `risk/manager.py` `size_order` — Kelly, VaR/CVaR, drawdown factors, 11 gates | `InstitutionalRiskManager` (`enhanced_engine.py:1089`) — a separate implementation |
| Pre-trade gate | `PreTradeGate` (8 checks) + `Gatekeeper` (11 checks) + FIA | none |
| Execution | `TradeExecutor` → `broker.place_market_order` | `_execute_signal` → immediate synthetic fill |

The consequence runs both ways. None of the Slice 1-2 defects — the constant
Kelly fraction, the position floor, the dead spread gate, the split-brain kill
switch — are exercised by any backtest, so a backtest can never catch them.
And conversely, **the equity curve describes a system that will never run**: it
is a different strategy, sized by different maths, with no gates, filling at
prices the live system cannot get.

**Minimal fix:** this is a large change and should be planned, not patched. The
tractable first step is a **parity harness** — replay one historical day through
both paths and assert the same signals, sizes, and fill prices within a
tolerance. Divergence beyond tolerance should fail CI. Until that exists,
backtest Sharpe/return figures should not be quoted as expected live
performance in any document or UI.

### S3-06 — Duplicated engines and cost models (MEDIUM)

Four backtest engines exist (`backtesting/engine.py`,
`backtesting/enhanced_engine.py`, `backtesting/backtest_engine.py`,
`backtest/engine.py`) and **two different classes named `TransactionCostModel`**:

- `backtesting/engine.py:239` — `commission_per_lot`/`spread_pips`/`slippage_pips`,
  contains the S3-03/S3-04 conversion bugs. **This is the one the CLI uses.**
- `backtesting/transaction_costs.py` — `extra_spread_bps`/`spread_markup_bps`,
  square-root impact model. Used by `enhanced_engine.py` and `backtest_engine.py`.

Same name, different constructor signatures, different correctness. A reader who
verifies the cost model in `transaction_costs.py` and concludes the backtester
models costs correctly would be right about a class the default path never
instantiates. Per `CLAUDE.md`, `backtest/` is a re-export shim of `backtesting/`
— but it contains its own `engine.py`, `data_validator.py`,
`transaction_costs.py` and `multi_symbol_backtest.py`, so this needs verifying
in Slice 13 rather than assuming.

---

## Round 3 — Slice 4: ML integrity (train/serve skew, staleness, drift)

Scope: `ml/inference_engine.py`, `ml/features_extended.py`, `ml/advanced_predictor.py`.
Questions asked: does the feature computation at inference match training? What
happens when a model is stale, when drift fires, and when a feature is NaN?

**Working correctly — verified:**

- `STALE_MODEL_BLOCK` defaults to `true` (`inference_engine.py:73`) and raises
  `RuntimeError`, which `HOPEFXDecisionEngine.py:357-368` catches and treats as
  a hard filter. The stale-model path is genuinely fail-closed end to end.
- The look-ahead guard re-raises `LookAheadBiasError` rather than swallowing it
  (`inference_engine.py:882-891`).
- MTF columns are shifted one bar before joining (`:411`) to keep the
  in-progress higher-timeframe bar out of the feature set.
- Isotonic calibration and an ML circuit breaker are both wired in.

| ID | Sev | Issue | Location |
|----|-----|-------|----------|
| S4-01 | HIGH | Drift guard and both feature-validation gates run on a vector the model **never scores** | `inference_engine.py:796,857,903` |
| S4-02 | HIGH | NaN/Inf features imputed with `0.0` and scored anyway | `inference_engine.py:427-435` |
| S4-03 | HIGH | ">95% zeros — possible silent upstream data failure" is logged, then traded on | `inference_engine.py:437-447` |
| S4-04 | MEDIUM | `DRIFT_BLOCK` defaults to **false** — drift warns and trades | `inference_engine.py:78` |
| S4-05 | MEDIUM | Drift guard silently disables itself when training stats are missing | `inference_engine.py:645-647` |
| S4-06 | MEDIUM | Feature-builder fallback changes the feature set and logs at `debug` | `inference_engine.py:384-397` |
| S4-07 | LOW | Docstring promises a feature-count-mismatch gate that does not exist | `inference_engine.py:360` |

### S4-01 — The drift guard watches features the model does not use (HIGH)

There are **two independent feature-building paths** inside a single `predict()`
call:

```
predict()
├── :796  X = self._build_features(ohlcv, macro_df, mtf_df, symbol)   # path A
│         └── :857  drift = self._check_feature_drift(X)              # A is used HERE
│         └── :424-445  NaN/Inf + all-zero validation on X            # and HERE
└── :903  raw_prob = predictor.predict_proba(ohlcv, macro_df, symbol) # path B
          └── AdvancedPredictor builds its OWN features from raw ohlcv
```

`X` — the vector built, validated, and drift-checked — is **never passed to the
model**. The model receives the raw `ohlcv` DataFrame and rebuilds features
internally. Nothing asserts the two vectors agree in content, order, or count.

**Failure scenario:** the macro pipeline stalls. Path A (via
`build_extended_features_with_data_layer`) fails and falls back to
`build_extended_features` (`:384`), producing a *different* feature set —
without microstructure/sentiment/macro injection. The drift buffer now fills
with vectors from the fallback distribution and reports "no drift", because it
is internally consistent. Meanwhile path B may still be injecting live macro
features, or may be failing differently — either way the model is scored on
features whose distribution nothing is monitoring. Drift on the features that
actually drive predictions is invisible; drift on features nobody scores
triggers alerts.

The same applies to the NaN/Inf and all-zero gates: they clean and inspect `X`
and then discard it. A NaN in the vector the model *does* see is never detected.

**Minimal fix:** score the model on the same `X` the guards validated
(`predictor.predict_proba(X)` where the predictor accepts a prepared matrix), or
have `_build_features` and the predictor share one builder. Until then, the
drift/validation telemetry should not be described as covering the live model.

### S4-02 / S4-03 — Detectors with no actuator (HIGH)

`inference_engine.py:427-435`:

```python
if bad_cols:
    logger.warning("... %d features contain NaN/Inf ... — imputing with 0. "
                   "Investigate data pipeline to prevent systematic model degradation.")
    X = X.replace([np.inf, -np.inf], np.nan).fillna(0.0)
```

`inference_engine.py:437-447`:

```python
if non_zero_pct < 0.05:
    logger.warning("... feature vector is >95%% zeros ... — possible silent "
                   "upstream data failure. Check gold feed and macro pipeline.")
return X          # ← traded on regardless
```

Both messages correctly diagnose a condition serious enough to name in the log,
and neither changes the outcome. Nothing increments a blocking counter; nothing
abstains.

**Failure scenario for S4-02:** imputing `0.0` is not neutral. In this feature
space zero is a *meaningful* value — a z-score of 0 means "exactly average", an
RSI-derived feature at 0 means "maximally oversold", a return feature at 0 means
"no move". Filling a broken feed with zeros does not produce an uncertain
prediction; it produces a **confident** one, drawn from a region of feature
space the model was trained to interpret as a strong signal. A feed outage
therefore yields high-confidence trades rather than abstention.

**Failure scenario for S4-03:** the >95%-zeros check exists precisely because
someone anticipated a silent upstream failure. When it fires, the system logs
"possible silent upstream data failure" and places the trade anyway.

**Minimal fix:** return `None` (the existing neutral path, `:405`) when NaN/Inf
exceeds a small threshold or when `non_zero_pct < 0.05`, and count both in
`_fallback_count` / the Prometheus fallback counter so they are visible.

### S4-04 / S4-05 — Drift detection is off by default and by accident (MEDIUM)

`inference_engine.py:78` — `DRIFT_BLOCK` defaults to **false**: *"Default: 4.0
(warn only). Set DRIFT_BLOCK=true to block on drift."* So the shipped
configuration detects distribution drift, logs `FEATURE DRIFT detected ...
Continuing (set DRIFT_BLOCK=true to block)`, and trades.

This also hollows out the fail-closed handler at `:690-696`, which sets
`_drift_detected = True` when the drift computation itself throws, with the
comment *"Fail CLOSED ... so the DRIFT_BLOCK gate (when enabled) abstains"*.
With the default configuration the gate is not enabled, so failing closed sets a
flag that nothing acts on.

`inference_engine.py:645-647` is a second, quieter disablement:

```python
train_stats = self._load_train_stats()
if train_stats is None:
    # No training stats available — drift guard disabled
    return False
```

Returning `False` means "no drift", not "unknown". A missing or unreadable
training-stats file therefore silently disables drift detection with no warning
log and no status flag — and `_load_train_stats` returns `None` when the file
does not exist (`:612`). Note `docs/HARDENING_BACKLOG.md` already records a
related artifact-integrity gap: `stacking_ensemble.pkl` does not match its
`registry.json` checksum, so stale-artifact conditions in this repo are not
hypothetical.

**Minimal fix:** default `DRIFT_BLOCK=true` for the live profile (the same
reasoning that made `STALE_MODEL_BLOCK=true` the default); log a WARNING and
expose a health flag when training stats are absent rather than returning a
clean "no drift".

### S4-06 / S4-07 — Silent feature-set substitution (MEDIUM / LOW)

`inference_engine.py:384-397` catches **any** exception from
`build_extended_features_with_data_layer` and falls back to
`build_extended_features`, which omits the data-layer injection the docstring
describes as the live path (*"injects microstructure, sentiment, and macro
calendar features from the orchestrator"*). The fallback is logged at
`logger.debug`, so at the production INFO level a permanent switch to a reduced
feature set is invisible.

If the model was trained on the data-layer feature set, this is textbook
train/serve skew — the model scores a vector missing whole feature families,
which after the S4-02 imputation arrive as zeros rather than as an error.

`inference_engine.py:357-360` documents three validation gates, the third being
*"Feature count mismatch vs expected → log WARNING"*. Only gates 1 and 2 exist
in the code. There is no comparison of the built feature count against the
model's `n_features_in_` anywhere in the inference path —
`n_features_in_` is read once at `:1301`, purely for the status endpoint.

**Minimal fix:** log the fallback at WARNING and record it as a distinct
Prometheus reason; implement the documented gate by comparing against
`predictor._model.n_features_in_` and abstaining on mismatch.

---

## Round 3 — Slice 5: data layer integrity

Scope: `data_layer/orchestrator.py`, `data_layer/feeds/gold/manager.py`,
`data_layer/validation.py`, `data_layer/types.py`, `data_layer/tick_store.py`.
Questions asked: what happens on gaps, duplicate or out-of-order ticks, timezone
and DST boundaries, and a stalled feed?

**Working correctly — verified:**

- **Timezone discipline is clean.** Every `datetime` construction in
  `data_layer/` is UTC-aware (`datetime.now(UTC)`, `fromtimestamp(..., tz=UTC)`);
  there are no naive `datetime.now()` or deprecated `utcnow()` calls. DST is a
  non-issue because nothing works in local time.
- **Future-dated data is rejected** in both the OHLCV and feature-matrix
  validators (`validation.py:255-259,361-363`), raising `FutureLeakageError`.
- **The Redis cache read has a correct two-sided freshness gate**
  (`orchestrator.py:731-742`) — an upper bound on age *and* a clock-skew tolerance
  so a future-dated tick cannot pass by having a negative age.
- **Cross-symbol contamination was fixed**: the in-memory fallback is guarded by
  `_is_gold_symbol(symbol)` (`orchestrator.py:761`) so a cache miss on EUR_USD no
  longer returns the gold price relabelled.

The findings below are all the same shape: **freshness is enforced on one read
path and on none of the others.**

| ID | Sev | Issue | Location |
|----|-----|-------|----------|
| S5-01 | HIGH | The "never trade on a stale tick" invariant never executes on the decision-engine path | `risk/manager.py:352-359`, `invariants/enforcement.py:336-344` |
| S5-02 | HIGH | Tick `quality` is frozen at ingest — a stalled feed's last tick stays `GOOD` forever | `types.py:106-112`, `feeds/gold/manager.py:431-438` |
| S5-03 | MEDIUM | The consensus tick is returned with no validity or age check at all | `feeds/gold/manager.py:431-432` |

### S5-01 — The staleness invariant cannot fire (HIGH)

`risk/manager.py:770-776` calls the constitutional pre-trade invariant with a
staleness budget:

```python
_inv = enforce_pre_trade(signal, data_quality=..., equity=equity,
                         now=datetime.now(UTC).timestamp(),
                         max_staleness_s=_MAX_TICK_STALENESS_S)   # 5.0s
```

`invariants/enforcement.py:336-344` resolves the tick timestamp like this:

```python
tick_ts = next((getattr(signal, attr)
                for attr in ("tick_ts", "tick_timestamp", "ts", "timestamp")
                if isinstance(getattr(signal, attr, None), (int, float))
                and not isinstance(getattr(signal, attr, None), bool)), None)
```

Two independent reasons this never resolves on the live path:

1. **`_MinimalSignal` has no timestamp field at all.** Its `__slots__`
   (`risk/manager.py:352-359`) are exactly
   `confidence, data_quality, direction, features, probability, symbol, tick_mid`.
   `calculate_position_size` — the entry point the decision engine uses —
   constructs it at `:1063-1069` without any timestamp. All four candidate
   attributes are absent, so `tick_ts` is `None` and the freshness block is
   skipped.
2. **Even the brain's `Signal` would fail the type test.** Its `timestamp` is a
   `datetime` (`strategies/base.py:50`), and the comprehension requires
   `isinstance(..., (int, float))`. A `datetime` is neither, so it is filtered
   out.

**Failure scenario:** the gold feed stalls at 14:00. The orchestrator's Redis
gate discards the stale cached tick, but the in-memory fallback (S5-02/S5-03)
keeps serving the 14:00 price. At 14:20 a signal is generated from that
20-minute-old price. `size_order` calls `enforce_pre_trade` with a 5-second
staleness budget; the check finds no usable timestamp and passes. The order is
sized and routed against a price two hundred and forty budget-widths out of
date. The invariant named "No Unverified AI Decision: never trade on a stale
tick" contributes nothing.

**Minimal fix:** stamp `tick_ts` (as a POSIX float) onto `_MinimalSignal` from
the orchestrator tick that produced `tick_mid`, and accept `datetime` in the
enforcement comprehension. Add a test that a signal with a 60-second-old tick is
refused when `HOPEFX_INVARIANT_MODE=enforce`.

### S5-02 — Tick quality is a snapshot, not a live property (HIGH)

`GoldTick.is_valid()` (`types.py:106-112`) treats a tick as valid when
`quality not in (REJECTED, STALE)` and the prices are sane. `quality` is
assigned by the DataQualityEngine **when the tick is ingested** and the tick is
a frozen dataclass — it is never re-evaluated afterwards.

`GoldFeedManager` holds the last tick per source in `self._latest` and returns
it (`feeds/gold/manager.py:434-438`):

```python
for src in _PRIORITY:
    tick = self._latest.get(src)
    if tick and tick.quality != TickQuality.REJECTED and tick.is_valid():
        return tick
```

**Failure scenario:** a tick arrives at 14:00:00 and is graded `GOOD`. The
upstream feed then disconnects. `self._latest` still holds that tick, its
`quality` is still `GOOD`, and `is_valid()` still returns `True` — at 14:05, at
15:00, and the next morning. `active_sources()` (`:445`) uses the same predicate,
so the health endpoint reports the dead feed as an active source. Nothing in
this class measures age.

**Minimal fix:** make `is_valid()` (or the manager's read path) take a
`max_age_s` and compare against `tick.timestamp`, using the same
`DQE_STALE_THRESHOLD_S` the orchestrator already reads at
`orchestrator.py:731`.

### S5-03 — The consensus path skips even the validity check (MEDIUM)

`feeds/gold/manager.py:431-432`, the first two lines of `get_latest_tick` and
the default branch (`prefer_consensus=True`):

```python
if prefer_consensus and self._consensus_tick:
    return self._consensus_tick
```

No `is_valid()`, no `quality` check, no age check — the single-source fallback
below it at least calls `is_valid()`. So the *default* read path is the least
guarded one in the module.

This matters most when Redis is unavailable: `orchestrator.get_latest_tick`
only applies its freshness gate inside `if self._redis_store._r:`
(`orchestrator.py:702`). With Redis down, **every** price read falls through to
`_gold_feed.get_latest_tick()` at `:762`, which returns the unchecked consensus
tick — and `_on_tick(tick)` at `:766` then re-publishes it downstream as a fresh
observation.

**Failure scenario:** Redis outage plus feed stall. The orchestrator serves an
arbitrarily old consensus tick as the live price, re-emits it through
`_on_tick`, and `RiskManager._get_data_quality` (`risk/manager.py:1254`) reads
`tick.confidence` from it — the confidence recorded at ingest, which is high.
Gate check 5 (data quality) therefore passes on stale data, and per S5-01 the
staleness invariant does not run either. Two independent staleness controls,
both inert, on the same tick.

**Minimal fix:** apply `is_valid()` and an age bound on the consensus branch;
apply the orchestrator's freshness gate to the in-memory fallback at `:761-767`
as well as the Redis path, so there is one staleness rule rather than one per
read path.

---

## Round 3 — Slice 6: auth, secrets, money-in

Scope: `api/` (928 decorated routes across 74 files), `auth/`, `security/`,
`compliance/`, `payments/`, `monetization/`.
Method: enumerated every route decorator and classified it by whether any auth
dependency is reachable (route-level `Depends`, router-level `dependencies=`,
or a shared helper). 99 of 928 routes resolve with no auth dependency; most are
legitimately public (health, status, pricing, signature-verified webhooks). The
findings below are the ones where that is not the case.

**Working correctly — verified:**

- **Superadmin surface is properly gated.** Every route under
  `api/superadmin/` takes `Depends(_require_superadmin)` and logs via
  `_log_superadmin_action`. An earlier draft of this audit flagged 130+
  superadmin routes as unauthenticated; that was a false positive from a regex
  that did not match the shared helper name. They are covered.
- **KYC webhooks verify HMAC signatures** before processing
  (`api/kyc.py:191,220`) and reject with 400 on mismatch.
- **`KYCGateway.webhook_event` discards the status in the webhook body** and
  re-queries the provider (`compliance/kyc_provider.py:795-797`), so a forged
  webhook cannot itself set an approval. This is good defensive design and
  should be preserved deliberately — see S6-03.
- Round 2's payment fixes hold: Stripe webhook replay dedup, AML fail-closed,
  self-referral rejection.

| ID | Sev | Issue | Location |
|----|-----|-------|----------|
| S6-01 | HIGH | Auth helper returns `None` on `ImportError` — 7 endpoints, including arbitrary source-code registration, degrade to unauthenticated | `api/dynamic_strategies.py:80-97` |
| S6-02 | HIGH | Three unauthenticated endpoints expose every advanced order, system-wide, by ID | `api/advanced_orders.py:200,214,223` |
| S6-03 | MEDIUM | Webhook HMAC secret defaults to the empty string — signatures become forgeable when unconfigured | `compliance/kyc_provider.py:146,250,387` |
| S6-04 | MEDIUM | Model internals (SHAP, feature importances, drift) served unauthenticated | `api/ml.py:1899,1917` |

### S6-01 — Auth that disappears if an import fails (HIGH)

`api/dynamic_strategies.py:90-97`:

```python
def _require_admin():
    """Require admin role."""
    try:
        from api.auth import require_role
        return Depends(require_role("admin"))
    except ImportError:
        return None
```

Used as a default argument on seven endpoints, e.g.
`async def register_strategy(request: RegisterStrategyRequest, user=_require_admin())`.

Default arguments are evaluated **once, at import time**. If `api.auth` cannot
be imported at that moment — a circular import, a missing transitive dependency
(`python-jose`, `passlib`), a syntax error introduced during a refactor — the
helper returns `None`, `user=None` becomes an ordinary default parameter with no
`Depends` wrapper, and FastAPI mounts the route with **no authentication for the
lifetime of the process**. `_get_current_user()` at `:80-87` has the identical
shape.

**Failure scenario:** the endpoints so exposed are not read-only.
`POST /register` accepts arbitrary Python **source code** and compiles it
(`strategies/dynamic_registry.py`); `POST /activate` makes a compiled strategy
live for signal generation; `POST /{name}/{action_type}` performs arbitrary
registry actions. An import-time failure in an unrelated auth dependency
silently converts an admin-only remote-code-registration surface into a public
one. The failure mode is the wrong way round: an auth module that fails to
import should take the router down loudly, not open it quietly.

Two aggravating details: the router **is** mounted
(`core/router_registry.py:817-819`), and `register_strategy` hardcodes
`author_id="system"` with the comment *"Will be replaced with actual user ID
from auth"* — so even when auth works, the code-registration audit trail records
no actual user.

This pattern is contained to this one file — no other router in `api/` uses it.

**Minimal fix:** import `require_role` at module scope and let an `ImportError`
propagate. If graceful degradation is genuinely wanted, degrade to a dependency
that **denies** (`Depends(_always_403)`), never to `None`.

### S6-02 — Unauthenticated exposure of all advanced orders (HIGH)

`api/advanced_orders.py:33-36` declares `APIRouter(prefix="/api/orders/advanced",
tags=["Advanced Orders"])` with **no `dependencies=`**, and is mounted at
`core/router_registry.py:826-828`. Three of its routes take no auth dependency
and perform no ownership check:

| Route | Line | Exposure |
|---|---|---|
| `GET /api/orders/advanced/active` | 200 | **Every** active advanced order in the system — optionally filtered by `position_id`, never by user |
| `GET /api/orders/advanced/health` | 214 | Order-manager internals |
| `GET /api/orders/advanced/{order_id}` | 223 | Full detail of any order by ID |

There is no global authentication middleware to compensate:
`SubscriptionPaywallMiddleware` (`core/middleware.py:505`) explicitly passes
unauthenticated requests through — `if not token: return await call_next(request)`
— leaving 401s to each route's own dependency, which these routes do not have.

**Failure scenario:** an unauthenticated client calls
`GET /api/orders/advanced/active` and receives every user's live stop-loss,
take-profit and trailing-stop levels, sizes, and symbols. On a trading platform
those levels are the most sensitive data in the system — an observer who knows
where stops sit knows exactly where forced liquidations will occur.
`GET /{order_id}` additionally allows enumeration and cross-tenant reads. Note
`manager.get_active_orders(position_id=...)` accepts a caller-supplied
`position_id` with no check that the caller owns that position.

**Minimal fix:** add `dependencies=[Depends(require_role("trader"))]` to the
`APIRouter` and scope every query by the authenticated user id, as the
superadmin routers already do.

### S6-03 — HMAC verification with an empty default secret (MEDIUM)

`compliance/kyc_provider.py:385-389`:

```python
def verify_webhook(self, payload: bytes, signature: str) -> bool:
    webhook_token = os.getenv("ONFIDO_WEBHOOK_TOKEN", "")
    expected = hmac.new(webhook_token.encode(), payload, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)
```

`SumsubProvider` is the same shape — `self._secret = os.getenv("SUMSUB_SECRET_KEY", "")`
at `:146`, used as the HMAC key at `:250`. Sumsub at least warns once at startup
(`:147-154`); Onfido reads the env var inside the verify call with no warning at
all.

HMAC keyed with `b""` is a perfectly well-defined function. Any caller can
compute `hmac.new(b"", payload, sha256).hexdigest()` for a payload of their
choosing and produce a signature that `compare_digest` accepts. Unset
configuration therefore does not disable the webhook — it makes it **publicly
signable**.

**Current blast radius is limited**, and deliberately so: `webhook_event`
discards the status parsed from the body and calls `check_status(applicant_id)`,
which re-queries the provider and writes only what the provider returns
(`:795-797`, `:759-772`). So a forged webhook today yields unauthenticated
provider-API calls (quota consumption, applicant-id enumeration), not a KYC
approval.

**The escalation path is what makes this worth fixing now.** `parse_webhook`
already returns a status that the caller throws away — assigned to `_status` and
unused. That reads like an oversight and invites a future "fix" that uses it.
The moment anyone does, an unauthenticated attacker can approve their own KYC,
which per Round 2 is the gate on fiat withdrawal.

**Minimal fix:** return `False` from `verify_webhook` when the secret is empty,
and fail startup (or disable the webhook route) when the provider is configured
without its secret. Add a comment at `:795` recording that discarding the
webhook status is a deliberate control, not dead code.

### S6-04 — Model internals served unauthenticated (MEDIUM)

`api/ml.py` exposes six unauthenticated `GET` routes, of which two leak model
structure: `/explain/{model_name}` (SHAP feature importance, `:1899`) and
`/feature-importance/{model_name}` (`:1917`). The others (`/drift-report`,
`/drift/status`, `/model-drift`, `/sharpe-circuit-breaker/status`) expose the
system's live drift and circuit-breaker state.

This is an IP and reconnaissance concern rather than a capital-safety one:
feature importances over a 200+ feature model describe the strategy's edge
directly, and the drift endpoints tell an observer when the model is degraded —
i.e. when the system is least reliable. Both are useful to an adversary and to
a competitor, and neither needs to be public.

**Minimal fix:** move these under the same `require_role` used by the rest of
`api/ml.py`.

---

## Round 3 — Slice 7: state and crash recovery

Scope: `execution/redis_state.py`, `execution/position_manager.py`,
`execution/trade_executor.py`, `alembic/`.
Method: walked four crash points — (1) after broker ack, before local persist;
(2) mid partial fill; (3) after SL/TP trigger, before the close is booked;
(4) mid migration — and asked what state survives and whether boot recovers it.

Round 2 already recorded *"redis_state crash-recovery: reconcile restored
orders/positions against live broker state on boot"* as an open item. It is
still open; this slice makes the failure concrete and adds a **deterministic**
orphan-position path that needs no crash at all.

**Working correctly — verified:**

- `TradeExecutor` performs **no retries** around the broker call
  (`trade_executor.py:352`), so there is no duplicate-fill window from retry
  logic on this path.
- Partial fills are explicitly surfaced rather than silently rounded away
  (`:393-403`), and the `Position` is created from `order.filled_quantity`, not
  the requested size.
- Migrations are conventional; `drop_*` calls appear only in `downgrade()`.

| ID | Sev | Issue | Location |
|----|-----|-------|----------|
| S7-01 | HIGH | A **filled** order with a bad fill price is abandoned — broker holds the position, the system does not | `trade_executor.py:358-374` |
| S7-02 | HIGH | Crash between broker ack and `add_position` leaves a permanently untracked live position | `trade_executor.py:352-388` |
| S7-03 | HIGH | Boot restores persisted positions with **no reconciliation** against the broker | `position_manager.py:595-615` |
| S7-04 | MEDIUM | A malformed record aborts restore mid-loop, leaving partial state and no log | `position_manager.py:605-615` |
| S7-05 | MEDIUM | No idempotency key on the `TradeExecutor` broker path | `trade_executor.py:352` |

### S7-01 — A filled order the system refuses to track (HIGH)

`trade_executor.py:358-374`:

```python
if order.status.value in ("filled", "partial"):
    if not order.average_fill_price or not (order.average_fill_price > 0):
        logger.error("... order %s status=%s but average_fill_price=%s — skipping position open", ...)
        return ExecutionResult(success=False, ..., message="Invalid fill price — position not opened")
```

The guard is inside the `filled`/`partial` branch — it only runs for orders the
**broker has already executed**. The response is to log, skip
`position_tracker.add_position()`, and return `success=False`.

**Failure scenario:** a broker acknowledges a market order as `filled` but
returns `average_fill_price` of `0` or `None` — routine for venues that confirm
the fill and deliver the execution price in a subsequent message, and the exact
shape of an async or FIX fill report. The system now has a **live position it
has deliberately chosen not to record**. Consequences compound:

- `position_tracker` does not know about it → the SL/TP monitor never arms a
  stop, so the position runs unprotected.
- `PositionManager` never persists it → a restart cannot recover it.
- `_phase4_execute` sees `success=False` and returns `EXECUTION_ERROR`
  (`HOPEFXDecisionEngine.py:543-552`), so the operator is told the trade
  **failed**.
- The next signal on the same symbol sizes as if flat.

This requires no crash and no race — it is the deterministic behaviour of the
error path. Reporting failure for an order that filled is the worst available
outcome: it is strictly better to record the position at a provisional price and
alert, or to immediately flatten it.

**Minimal fix:** on this branch, re-query the broker for the fill price; if it
is still unavailable, open the position at the last known mid, mark it
`price_unconfirmed`, and raise a CRITICAL alert. Never return
`success=False` for an order the broker reports as filled.

### S7-02 — The ack-to-persist window (HIGH)

`trade_executor.py:352` awaits `broker.place_market_order(...)`; the position is
recorded 36 lines later at `:388` via `await self.position_tracker.add_position(position)`.
Between those two awaits the process can die — SIGKILL, OOM, pod eviction,
deploy.

**Failure scenario:** the broker fills 100 oz of XAUUSD and the process is
evicted before `add_position`. Nothing local ever knew about the order: it was
not written to Redis before submission, and no client-order-id links the broker
fill back to a local intent (S7-05). On restart, `restore_from_redis` replays
Redis, which has no record of it. The position is **invisible to every
subsystem** — unmonitored by SL/TP, absent from risk exposure, absent from the
dashboard — and stays open until a human reads the broker statement.

**Minimal fix:** write an intent record to Redis *before* the broker call and
clear it only after `add_position` succeeds. On boot, any intent record without
a matching position is a reconciliation candidate — which is exactly what S7-03
needs anyway.

### S7-03 — Boot trusts Redis over the broker (HIGH)

`position_manager.py:604-612`:

```python
state = await self._redis_store.load_state_on_boot()
positions = state.get("positions", [])
async with self._lock:
    for p_dict in positions:
        pos = Position.from_dict(p_dict)
        self._positions[pos.symbol] = pos
        _prom_positions_open_set(pos.symbol, 1)
```

Redis is treated as authoritative. The broker is never consulted, so restored
state is never checked against reality.

**Three failure scenarios, all live:**

1. **Closed while down.** A stop is hit at the broker while the process is
   restarting. Redis still holds the position; boot restores it. The system
   believes it is exposed when it is flat — it will refuse new entries on that
   symbol (position-count and exposure logic) and the Prometheus gauge reports a
   position that does not exist.
2. **Opened while down** (the S7-02 case). The broker has a position Redis does
   not. Boot restores nothing, and the position stays unmanaged.
3. **Quantity drift.** A partial close at the broker while down leaves the
   restored `quantity` stale, so every subsequent P&L and exposure figure for
   that symbol is wrong by the closed amount.

**Minimal fix:** after restoring, call `broker.get_positions()` and diff.
Broker-only positions get adopted (with an alert); Redis-only positions get
dropped (with an alert); quantity mismatches take the broker's number. The
broker is the only authority on what is actually open.

### S7-04 / S7-05 — Partial restore and missing idempotency (MEDIUM)

**S7-04:** the restore loop mutates `self._positions` **inside** the `try`, and
the handler catches only `(RuntimeError, OSError)`. A `KeyError` or
`ValueError` from `Position.from_dict` on record 3 of 5 propagates out — after
records 1 and 2 have already been inserted. The `logger.info("restored %d
position(s)")` line never runs, so the partial state is not even reported.
Recovery silently completes with a subset of positions.

*Minimal fix:* build the full list first, then swap it in under the lock; catch
per-record parse failures and alert on each rather than aborting the batch.

**S7-05:** `trade_executor.py:352` calls
`place_market_order(symbol=..., side=..., quantity=...)` with no
`client_order_id`. Round 2's H3 fix added idempotency to the canonical
`ExecutionEngine` path and the Binance adapter — **this path did not get it**.
There is no retry here today, so no duplicate-fill window exists right now; the
cost is that a broker fill cannot be correlated back to a local order, which is
precisely what S7-02 and S7-03 need to reconcile. Adding it is a prerequisite
for the other two fixes, not an independent nicety.

---

## Round 3 — Slice 8: realtime transport

Scope: `api/ws_live.py` (2,249 lines).
Questions asked: per-channel authorization, backpressure when a client is slow,
reconnect/resubscribe semantics, message ordering, and what a client sees after
a disconnect gap.

**Working correctly — verified:**

- `WS_AUTH_REQUIRED` defaults to `true` and is **enforced structurally**: the
  module raises `RuntimeError` at import when `APP_ENV=production` and the flag
  is off (`:96-101`). A misconfiguration cannot silently open the socket.
- Round 2's private-channel fix holds — `broadcast()` excludes
  `_PRIVATE_CHANNELS` from the "empty subscription = all channels" path
  (`:271-273`).
- Origin checking, a 20 s auth timeout, and heartbeat miss-limits are all
  implemented.

| ID | Sev | Issue | Location |
|----|-----|-------|----------|
| S8-01 | HIGH | No backpressure — one slow client stalls the tick feed for every client | `ws_live.py:275-283` |
| S8-02 | MEDIUM | `send_to_user` lacks the private-channel guard that `broadcast` has | `ws_live.py:309` |
| S8-03 | MEDIUM | No sequence numbers — a client cannot detect messages missed across a reconnect | throughout |
| S8-04 | LOW | Every send failure is logged at `debug` | `ws_live.py:256,282,315` |

### S8-01 — One slow consumer degrades everyone (HIGH)

`broadcast()` (`:275-283`) fans out sequentially, awaiting each socket in turn:

```python
for cid, subs in list(self._subscriptions.items()):
    if channel in subs or (not subs and implicit_all_ok):
        ws = self._connections.get(cid)
        if ws:
            try:
                await ws.send_text(payload)      # ← blocks the shared coroutine
```

There is no per-client send queue, no bounded buffer, and **no send timeout**.
Every `asyncio.wait_for` in this 2,249-line file wraps a `receive_text` — not one
wraps a send.

**Failure scenario:** a laptop sleeps with the dashboard tab open. The TCP
window freezes; the socket is not yet reset, so `send_text` blocks once the
kernel buffer fills rather than raising. The tick broadcaster
(`_eventbus_tick_broadcaster`, `:620`) is a single coroutine consuming
`bus.subscribe(CH_TICK)` and calling `broadcast()` per tick — so it is now
blocked inside that one client's send. **Every other connected trader stops
receiving price updates** until that socket errors or drains, and messages back
up in the Redis pubsub buffer behind it.

The 30-second stale-feed watchdog does not help: `_stale_deadline` is refreshed
at the top of each loop iteration (`:649`), and while the coroutine is blocked
inside `broadcast()` the loop is not iterating, so the watchdog cannot fire
either. The failure is silent in both directions — the stalled clients see a
frozen price, and the server logs nothing above `debug`.

For a trading UI a frozen price is not a cosmetic problem: it is the input a
human uses to decide whether to intervene, and slice 9 examines whether the
frontend can even tell that its feed has stopped.

**Minimal fix:** give each connection a bounded `asyncio.Queue` with a dedicated
writer task; on overflow, drop the oldest tick (prices are idempotent — the next
tick supersedes) and disconnect the client if the queue stays full. At minimum,
wrap the send in `asyncio.wait_for(..., timeout=1.0)` so one socket cannot hold
the fan-out.

### S8-02 — The private-channel guard was applied to only one of two senders (MEDIUM)

`broadcast()` (`:273`) computes `implicit_all_ok = channel not in self._PRIVATE_CHANNELS`
so `account`, `equity`, `risk`, `positions` and `alerts` are never delivered to a
connection that has not explicitly subscribed. `send_to_user()` (`:309`) has the
same `or not subs` fallback with **no such guard**:

```python
subs = self._subscriptions.get(cid, set())
if channel in subs or not subs:
```

This is scoped to `uid == user_id`, so it is not a cross-user leak — the data
reaches the right person. But a connection that is still mid-handshake, or has
deliberately subscribed to `prices` only, receives private account and risk
messages it never asked for. Given Round 2 fixed exactly this pattern in the
sibling method, this looks like the fix not being carried across.

**Minimal fix:** apply `implicit_all_ok` in `send_to_user` too, or require an
explicit subscription for private channels in both paths.

### S8-03 / S8-04 — No gap detection, and silent drops (MEDIUM / LOW)

**S8-03:** there is no per-connection sequence number anywhere in the file. The
only `seq` present is `tick_seq` read off an inbound event-bus message (`:918`)
and used to build a signal id. A client that drops and reconnects therefore
cannot tell whether it missed anything, and there is no resume or snapshot
mechanism.

For `prices` this is tolerable — the next tick supersedes. For **state**
channels it is not: `positions`, `account` and `risk` are delivered as updates,
so a missed `positions` message leaves the UI displaying a position that has
since closed, or omitting one that opened, **indefinitely** — until some later
update happens to correct it. Combined with S8-01 (drops are silent) and S7-03
(server-side position state may itself be wrong after a restart), there is no
layer in the stack that reconciles what the UI shows against what the broker
holds.

*Minimal fix:* attach a monotonic per-connection sequence number; on
`subscribe`, send a full snapshot for state channels before the first delta.

**S8-04:** all three send paths (`:256`, `:282`, `:315`) log failures at
`logger.debug`. Production runs at INFO, so a client losing messages — or being
disconnected by the error handler — produces no operational signal at all.
These should be INFO with a counter, or WARNING when a disconnect results.

---

## Round 3 — Slice 9: frontend correctness

Scope: `frontend/src` (204 `.tsx`, 61 `.ts`).
Questions asked: can stale data render as live? Is money formatting safe? What
renders when the backend is down? Any double-submit or stale-closure races?

**Working correctly — verified:**

- **Order entry is double-submit safe** — `OrderEntryForm.tsx:199,473` holds a
  `submitting` flag and disables the button on it (and on `isBlackout`).
- **Reconnect is bounded and correct** — exponential backoff capped at 30 s with
  a retry limit, and `_lastMid` is module-level so it survives reconnects
  (`useWebSocket.ts:47-50,187`).
- A stale-closure bug in SL/TP validation was previously found and fixed with a
  documented comment (`OrderEntryForm.tsx:318`) — the class of bug is known here.
- A `noLiveFeed` banner exists and is wired into `App.tsx:310-319`.

| ID | Sev | Issue | Location |
|----|-----|-------|----------|
| S9-01 | HIGH | The client cannot detect a stalled feed — `lastHeartbeat` is written and never read | `useWebSocket.ts:231`, `store:404` |
| S9-02 | MEDIUM | The only freshness signal shown is ingest-time confidence, which never decays | `LivePriceTicker.tsx:217` |
| S9-03 | MEDIUM | ~79% of components and pages render no error state | `frontend/src` |

### S9-01 — A frozen price under a green "connected" light (HIGH)

The hook records a heartbeat timestamp into the store on every server heartbeat
(`useWebSocket.ts:230-231` → `store:404-405`, `lastHeartbeat`). **Nothing reads
it.** A repo-wide search for `lastHeartbeat` returns the store definition and
eight test files — no component, no selector, no effect. There is no interval
anywhere comparing it against `Date.now()`.

The `noLiveFeed` banner is not a substitute: it is set only when the **server
explicitly sends** a `no_live_feed` message (`useWebSocket.ts:292`), and
`App.tsx:310` additionally requires `status === 'connected'`. It reports a
condition the server volunteers, not one the client observes.

**Failure scenario — this is the client half of S8-01.** The server's broadcast
loop blocks on one slow socket. The WebSocket stays `OPEN` at the TCP level, so
`wsStatus` remains `'connected'` and `onclose` never fires. No ticks arrive; no
heartbeats arrive; the server sends nothing, so `noLiveFeed` stays false. The
UI keeps rendering **the last price it received, indefinitely, with a green
connection indicator and no age anywhere on screen.**

A trader watching a frozen gold price they believe is live will size and time
entries against a number that may be minutes old — and per Slice 5, the server
may itself be serving a stale tick, so both layers can be wrong at once with no
indication in either.

`LivePriceTicker.tsx` contains no `timestamp`, `age`, `ago`, or `Date.now`
reference at all: there is no per-price freshness display to fall back on.

**Minimal fix:** an interval that flips a `feedStale` store flag when
`Date.now() - lastHeartbeat > 2 × HEARTBEAT_INTERVAL_MS`; grey out or overlay
every price surface while it is set. The value is already in the store — only
the consumer is missing.

### S9-02 — The freshness signal that never decays (MEDIUM)

`LivePriceTicker.tsx:217` renders `{(quality * 100).toFixed(0)}%` — the tick
quality/confidence from the data layer. It is the closest thing on screen to a
data-health indicator, and a trader will reasonably read a high number as "the
feed is healthy right now".

Per **S5-02**, that value is assigned when the tick is ingested and stored on a
frozen dataclass; it is never re-evaluated as the tick ages. A tick graded
`GOOD` at 14:00:00 still reports high confidence at 15:00. So the one visible
freshness cue reinforces the S9-01 illusion rather than correcting it: a stalled
feed displays a frozen price *and* a reassuring confidence percentage.

**Minimal fix:** depends on the S5-02 fix — once quality decays with age, this
display becomes meaningful. Until then, pair it with an explicit "last update"
age so the two cannot disagree silently.

### S9-03 — Most views have no failure state (MEDIUM)

36 of 169 files under `components/` and `pages/` reference `isError` or an
`error &&` render branch — roughly **21% coverage**. The remaining ~79% render
their success path only.

This is a diffuse finding rather than a single defect, and the severity varies
by view: an empty analytics chart is cosmetic, whereas a positions or account
panel that renders nothing on a failed fetch is indistinguishable from "you have
no open positions" — a false negative on exactly the screen a trader checks
before deciding whether to intervene.

**Minimal fix:** not a blanket sweep. Triage by consequence — start with the
views where an empty state could be misread as a *meaningful* zero (positions,
open orders, account equity, risk limits) and give those an explicit
"couldn't load" state distinct from "nothing here". The `react-query` `isError`
flag is already available at every one of these call sites.

**Verification note:** the "run it" clause of this slice — pointing the dev
server at a stopped backend and at one returning 500s, and recording what each
view actually does — was **not performed**. The findings above are from reading
the code. That runtime pass is worth doing before acting on S9-03, since it will
rank the views by real impact rather than by grep coverage.

---

## Round 3 — Slice 10: frontend and UX design (trading surface)

Scope: `frontend/src`, reviewed against the duties a capital-committing UI owes
its operator rather than against visual taste.

**Working correctly — verified:**

- **Close-all is properly confirmed.** `Trade.tsx:472-477` uses a `useConfirm`
  dialog with a `danger` variant and the text *"This will market-close every
  open position immediately. This cannot be undone."* `PositionsTable.tsx:10,24`
  implements an inline dialog deliberately instead of `window.confirm`, with the
  reasoning recorded in a comment.
- **Kill-switch state is persistently visible** in the account bar
  (`AccountBar.tsx:157-163`), not buried in a settings page.
- **P&L and deltas carry a sign, not just a colour** (`LivePriceTicker.tsx:147`,
  `delta >= 0 ? '+' : ''`), so red/green is not the sole carrier of meaning on
  that surface.

| ID | Sev | Issue | Location |
|----|-----|-------|----------|
| S10-01 | HIGH | Opening a position needs no confirmation; closing one does | `OrderEntryForm.tsx` |
| S10-02 | MEDIUM | The kill-switch badge may report the wrong instance | `AccountBar.tsx:157` + S2-01 |
| S10-03 | MEDIUM | Confirmations describe the action but not its magnitude | `Trade.tsx:472-477` |
| S10-04 | MEDIUM | ~15% of components carry any ARIA attribute; order entry has one | `frontend/src` |
| S10-05 | — | No latency or data-age indicator anywhere | see S9-01 |

### S10-01 — The confirmation is on the wrong action (HIGH)

`OrderEntryForm.tsx` contains no `confirm`, `useConfirm`, or dialog of any kind.
A single click on the submit button places a **live market order**. Meanwhile
close-all — which *reduces* exposure — is gated behind a danger-variant modal.

The risk asymmetry runs the other way: closing a position removes market
exposure and is recoverable by re-entering; opening one commits capital, arms a
stop, and is recoverable only by paying the spread again. A misclick or a
double-tap on a phone opens a real position at market.

This compounds with S9-01: the trader may be clicking against a price display
that has silently frozen, with no age indicator to warn them, and with no
confirmation step that would show them the price the order will actually be
sized against.

**Minimal fix:** reuse the existing `useConfirm` hook — it is already built,
already styled, and already used two files away. The confirmation should restate
**symbol, direction, quantity, entry price, stop-loss, and computed max loss**;
`OrderEntryForm.tsx:128` already computes `maxLoss`, so the number is in hand.

### S10-02 — The kill-switch badge inherits the split-brain problem (MEDIUM)

`AccountBar.tsx:157` renders the badge from `account.kill_switch`. Per **S2-01**
there are two `KillSwitch` instances, and the health/status routes are wired to
`app.kill_switch` (`app.py:959`) while the money path reads the module singleton
via `pre_trade_gate.py:342`.

**Failure scenario:** an operator activates the kill switch via
`/nuclear/kill_switch/activate` (the endpoint that actually stops trading). The
status route reads the *other* instance and reports inactive, so the badge stays
dark — the operator sees no confirmation that the most important control in the
system took effect, and may activate it again elsewhere or assume it failed.
The inverse is worse: activating via the app router lights the badge while
trading continues.

**This is not a frontend fix.** The UI is faithfully rendering what the API
reports; S2-01 must be fixed at the source. Recorded here because the badge is
where an operator will experience the bug.

### S10-03 / S10-04 / S10-05 — Confirmations, accessibility, latency

**S10-03:** the close-all dialog says *"every open position"* without stating
how many, in which symbols, or at what aggregate notional. A confirmation that
does not restate the magnitude cannot be checked by the person confirming it —
they are agreeing to a category, not to a quantity. The position count and
notional are already in the store.

**S10-04:** 31 of 204 `.tsx` files reference any `aria-` attribute (~15%).
`OrderEntryForm.tsx` has exactly one — `role="alert"` at `:493`. The order
inputs (symbol, side, quantity, SL, TP) carry no `aria-label`, and there is no
keyboard-shortcut affordance for order entry or for the kill switch. For a
surface where a mis-set field commits capital, label association is a
correctness feature, not only a compliance one.

**S10-05:** there is no latency, "last updated", or data-age indicator on any
price or position surface — the design consequence of S9-01. A trading UI should
make the *age* of its data as visible as the data itself; here the age is not
computed at all, so the operator has no way to distinguish a quiet market from a
dead feed.

**Scope note:** this slice was conducted by reading components, not by
exercising the running UI. Judgements about hierarchy, scan-time, and whether
system state is readable "in under a second" need a real screen to be
trustworthy, and are therefore deliberately **not** claimed here. What is
recorded above is limited to what the source establishes: which affordances
exist, which do not, and where a control's data source is provably wrong.

---

## Round 3 — Slice 11: ops and deployment

Scope: `Dockerfile`, `docker-compose*.yml`, `k8s/`, `helm/`,
`.github/workflows/` (21 files), `.env.example`.

**Working correctly — verified:**

- **Health probes are honest.** `/api/health/live` returns 200 unconditionally
  and *documents that it does* — correct for a Kubernetes liveness probe, which
  should only detect a wedged process. `/api/health/ready` returns **503 when a
  critical component is down** (`api/health.py:796+`). This is the right split;
  many systems get it backwards.
- **No secrets in compose.** `docker-compose.yml` contains no inline passwords,
  tokens, or keys.
- **Several dormant workflows are deliberate and documented** — `fortify.yml`
  ("requires a paid enterprise subscription"), `jekyll-docker.yml` ("This repo
  uses MkDocs, not Jekyll. Disabled automatic triggers"). Dormant-with-a-reason
  is not dead code.

| ID | Sev | Issue | Location |
|----|-----|-------|----------|
| S11-01 | HIGH | Four sources disagree on the Python version; the documented target is tested by nothing | `CLAUDE.md`, `Dockerfile:20`, `pyproject.toml:29`, `tests.yml:36` |
| S11-02 | HIGH | `STALE_MODEL_BLOCK` and `LIVE_TRADING_ENABLED` are absent from `.env.example` | `.env.example` |
| S11-03 | MEDIUM | 1,078 env vars read in code; 255 undocumented, 134 documented but never read | repo-wide |
| S11-04 | LOW | Three GitHub starter-template workflows unrelated to this project | `.github/workflows/` |

### S11-01 — The documented Python version is the one nothing runs (HIGH)

| Source | Python version |
|---|---|
| `CLAUDE.md` | *"**Python 3.10** is the production target (matches the Docker image — avoids pickle mismatches on model artifacts)"* |
| `Dockerfile:20` | `FROM python:3.12-slim` |
| `pyproject.toml:29`, `setup.py:35` | `>=3.10` |
| `.github/workflows/tests.yml:36` | matrix `["3.11", "3.12"]` |

The production image is **3.12**. CI tests **3.11 and 3.12**. So **3.10 — the
version the contributor guide instructs everyone to pin to — is exercised by
nothing**, and the parenthetical justifying it ("matches the Docker image") is
factually wrong.

**Failure scenario:** the stated reason for the pin is pickle compatibility on
model artifacts, and this repo **commits** its `.pkl`/`.zip` artifacts under
`ml/saved_models/` and `ml/rl_models/` (whitelisted in `.gitignore`,
checksum-verified in CI). A contributor who follows `CLAUDE.md`, installs 3.10,
and runs the retrain pipeline produces artifacts pickled under an interpreter
and dependency set that **no CI job and no production image ever loads**. The
checksum gate confirms the file is unmodified; it says nothing about whether it
deserialises correctly on 3.12. The existing note that
`stacking_ensemble.pkl` fails its `registry.json` checksum shows artifact drift
is already live in this repo.

**Minimal fix:** pick one version and make the other three follow. If 3.12 is
the intent, correct `CLAUDE.md` and add 3.12 to nothing (it is already there);
if 3.10 is the intent, change the `Dockerfile` and the CI matrix. Whichever is
chosen, the retrain workflow must run on the same interpreter as the production
image.

### S11-02 — The two flags that gate unsafe trading are undocumented (HIGH)

`.env.example` is thorough — 957 documented variables, including good practice
like `DRIFT_BLOCK=true` and `HOPEFX_INVARIANT_MODE=monitor`. Two are missing:

- **`STALE_MODEL_BLOCK`** — decides whether the system refuses to trade on a
  stale model (`ml/inference_engine.py:73`). Its code default is `true`, and
  Slice 4 confirmed the fail-closed path works end to end.
- **`LIVE_TRADING_ENABLED`** — gates live trading.

An operator who builds their `.env` from the template — the documented workflow
(`scripts/bootstrap_dev.py`) — produces a config that mentions neither. Both
then run on their code defaults, invisibly. For `STALE_MODEL_BLOCK` the default
is safe, so the risk is that an operator cannot *find* the flag to verify it,
and cannot tell whether the protection is on. The absence of the system's most
important safety switches from the file operators actually read is the defect,
independent of the default's direction.

Also absent and safety-relevant: `FIA_MAX_ORDER_SIZE`,
`FIA_MAX_INTRADAY_POSITION` (Slice 2 showed these controls receive fabricated
inputs — they are also unconfigurable from the template), `SLTP_MAX_TICK_AGE_S`,
`MCC_EMERGENCY_DD_PCT`, `FALLBACK_TO_PAPER`, `PAPER_RAISE_ON_STALE`.

**Correction to S4-04 (Slice 4):** that finding stated `DRIFT_BLOCK` defaults to
false and therefore ships in warn-only mode. The **code** default is indeed
`false` (`inference_engine.py:78`), but `.env.example:1089` sets
`DRIFT_BLOCK=true` with an explanatory comment — so an operator following the
documented setup gets blocking behaviour. S4-04 remains valid for any
environment not built from the template (containers, Kubernetes, CI), where the
code default governs, but it is **less severe than written**: the intended
configuration is correct and documented.

### S11-03 / S11-04 — Configuration surface and template workflows

**S11-03:** the codebase reads **1,078 distinct environment variables**. 255 are
read but not in `.env.example`; 134 are in `.env.example` but read nowhere
(dead config that will mislead an operator into thinking a knob exists).

The count itself is the finding. A system whose safety properties are decided by
env-var defaults — as Slices 2, 4 and 5 all showed — cannot be reasoned about
when there are a thousand of them and a quarter are undocumented. There is no
single place that answers "what configuration is this process actually running
under, and which safety gates are live?"

*Minimal fix:* a startup log line (or `/api/health/detailed` field) enumerating
the resolved values of the ~20 safety-critical flags — kill switch, invariant
mode, drift/stale blocking, risk limits, broker type, paper/live. Cheap, and it
would have made several findings in this round visible in production logs.

**S11-04:** `webpack.yml`, `python-package-conda.yml` and `static.yml` are
GitHub starter templates that do not match this project (it has no webpack
build, does not use conda, and `static.yml` is a Pages deploy superseded by
`docs.yml`). All three are `workflow_dispatch`-only so they cost nothing at
runtime — they are noise in the workflow list rather than a risk. Candidates for
deletion in Slice 13.

---

## Round 3 — Slice 12: test quality

Scope: `tests/` — 467 files, analysed by AST (not grep) to avoid miscounting.
Question asked: do these tests actually protect the money path?

**Working correctly — verified:**

- **15,098 test functions**, of which **481 (3.2%)** contain no assertion,
  `pytest.raises`, or mock assertion. As a ratio that is **good** — an initial
  regex-based estimate of this figure was far higher and was wrong; the AST
  count above is the accurate one.
- **Zero `xfail` markers.** Nothing is parked as "known broken".
- Coverage gates are real and enforced on the right modules — `tests.yml`
  requires 80% on `risk/`, `execution/`, `kill_switch.py`, `brokers/`.

The problem is not the quantity of tests or the assertion ratio. It is **what
the assertion-free tests are about**, and a structural blind spot that explains
why 467 test files did not catch a single Round 3 finding.

| ID | Sev | Issue | Location |
|----|-----|-------|----------|
| S12-01 | HIGH | Assertion-free tests cluster on exactly the safety properties this round found broken | `tests/integration/test_mcc_signal_pipeline.py:313`, others |
| S12-02 | HIGH | The suite tests gate *logic* against injected state, never that production code *writes* that state | structural |
| S12-03 | MEDIUM | 156 skip markers/calls | `tests/` |
| S12-04 | **CRITICAL** | SL/TP monitor never sends the closing order: `place_order` is invoked but never awaited | `execution/sl_tp_monitor.py:322` |
| S12-04a | **CRITICAL** | Same bug at 3 more sites; the margin gate was inert (fail-open) against every async broker | `execution/engine.py` |

### S12-04 — The stop-loss never reached the broker (CRITICAL) — FIXED

Found by *fixing* S12-01: once the assertion-free SL/TP tests were given real
assertions, they failed. The cause was not the new assertions.

`_close_position` sent the closing order like this:

```python
order = await loop.run_in_executor(
    None,
    lambda: self._broker.place_order(...),   # async def
)
if order is not None:
    ...   # book the close, alert "STOP_LOSS HIT: Closed ..."
```

`BaseBroker.place_order` is `async def` (`brokers/base.py:413`), as are the
OANDA (`brokers/oanda_broker.py:237`) and MT5 (`brokers/mt5_broker.py:182`)
implementations — every live path. The worker thread therefore only *built* a
coroutine and returned it. Awaiting the executor future yielded that coroutine
object, never an `Order`. It is not `None`, so the monitor took the success
branch: it booked the position closed and emitted a **critical** Telegram alert
reading `STOP_LOSS HIT: Closed BUY 1.0 XAUUSD` — while no order had been sent
and the position remained fully open at the broker.

Reproduced directly: `place_order.called == True`, `place_order.await_count == 0`.
`called` is True throughout, which is why any test asserting `.called` would
also have passed. Only `await_count` catches it.

Blast radius: the automated stop-loss/take-profit safety net was inert against
every async broker, and failed *silently upward* — the logs, the alert, and the
position manager all reported a successful close. Only the paper broker
(`brokers/paper_trading.py:517`, sync) actually worked, which is why paper
trading never surfaced it.

Two things hid this for as long as the suite has existed:
1. The SL/TP tests asserted nothing (S12-01).
2. Their fixture put plain `dict`s in the tick cache, but production stores
   `GoldTick` objects and `_get_mid` reads `hasattr(tick, "mid")`. So `_get_mid`
   returned `None` and the tests only ever exercised the "no price, skip" branch
   — the close path under test never ran at all.

**Fix:** keep the executor hop (so a blocking sync broker cannot stall the loop)
and await the result when it is awaitable:

```python
order = await loop.run_in_executor(None, lambda: self._broker.place_order(...))
if inspect.isawaitable(order):
    order = await order
```

Regression tests in `tests/unit/test_execution_wiring.py::TestSLTPMonitor` now
use a production-shaped tick, drain the spawned close task, and assert
`place_order.await_count == 1` plus the correct closing side and quantity.
Verified failing before the fix and passing after, with an identical
whole-suite failure set (zero regressions).

#### S12-04a — The same bug in three more places, including a fail-*open* margin gate (CRITICAL) — FIXED

Found while re-verifying S12-04. **The claim in S12-04 that the pattern was
isolated to `sl_tp_monitor.py` was wrong** — that grep was truncated at 40
results and `execution/engine.py` fell below the cut. A proper AST sweep for
`run_in_executor` targets that name an `async def` found three more live sites,
all in `execution/engine.py`:

| Site | Method | Consequence |
|---|---|---|
| `_check_margin` (was :923) | `get_account_info` | `equity` reads `0.0`; the buffer test is guarded by `if projected_used > 0 and equity > 0`, so it was **skipped entirely** — the margin gate blocked nothing |
| `_check_leverage` (was :993) | `get_account_info` | `equity` reads `0.0` → trips `equity <= 0` → blocks **every** order with the false reason "Account equity is zero or negative" |
| `_place_order_async` (was :1358) | `place_order` | `order.status` raises `AttributeError` on a coroutine |

The margin one is the serious one and it is the opposite of what its own
docstring promises: *"Fail-closed: any unexpected exception from the broker API
blocks the trade."* Reading a coroutine is not an exception — it yields a
plausible-looking `0.0`, and zero equity happens to be the value that turns the
check off. **The margin gate was inert against every async broker.** Verified
with a $100-free-margin account against a $23,500 order: it passed.

`ExecutionEngine` is constructed at `hopefx_engine.py:475`, so this is the live
path, not a dormant class.

**Fix:** added `execution/broker_call.py::call_broker`, which awaits an
`async def` broker method directly and runs a sync one in the thread pool, so
neither shape can be mis-called again. Applied at all three engine sites and at
`sl_tp_monitor.py` (replacing the S12-04 inline fix, so there is one
implementation rather than two — the S13-01 lesson). `api/health.py:1139` was
already correct via its own `iscoroutinefunction` branch and was converged onto
the helper for consistency.

`tests/unit/test_broker_calls_are_awaited.py` covers the helper, asserts the
margin gate still blocks an under-margined order and the leverage gate still
blocks 235x while passing a funded account, and adds an AST guard that fails if
any money-path file passes a bare async broker method to `run_in_executor`.

### S12-01 — Tests that name a safety property and verify nothing (HIGH)

`tests/integration/test_mcc_signal_pipeline.py:313-322`:

```python
def test_kill_switch_blocks_signal_processing(self):
    mcc = _make_mcc()
    mcc.kill_switch_triggered = True
    # Should silently return — no exception, no execution
    mcc._on_strategy_signal("strat1", StrategySignal(action="BUY", strength=0.9, confidence=0.9))
```

The test sets the kill switch, calls the handler, and asserts **nothing**. It
passes when the kill switch blocks the signal. It passes equally when the kill
switch does nothing at all and a full BUY order is routed to a broker — the only
failure it can detect is an exception. The comment asserts "no execution"; the
code does not.

The contrast sits eleven lines below it: `test_daily_loss_limit_rejects_signal`
(`:324`) captures `result = mcc._check_signal_risk(...)` and asserts on it. The
file knows how to write the assertion.

The same shape recurs on money-path controls — all confirmed assertion-free:

| Test | What it claims to cover |
|---|---|
| `test_kill_switch_blocks_signal_processing` | kill switch halts trading |
| `test_check_positions_sl_triggered` | stop-loss fires |
| `test_check_positions_tp_triggered` | take-profit fires |
| `test_reconcile_once_broker_exception` | reconciliation survives a broker error |
| `test_trigger_drift_halt_no_alert_engine` | drift halt without an alert engine |
| `test_execute_signal_no_broker_is_graceful` | execution with no broker |

A test named for a safety property that asserts nothing is **worse than no
test**: it produces a green check next to the property's name and closes the
question for anyone reading the suite. `test_kill_switch_blocks_signal_processing`
has been passing throughout the period in which — per **S2-01** and **S2-02** —
the kill switch had a split-brain instance problem and the Gatekeeper's
kill-switch check was inert.

**Minimal fix:** these are cheap to repair — assert the broker mock's
`place_market_order` was **not** called. Do these six first; the remaining 475
can be triaged later.

### S12-02 — The suite tests the lock, never the key (HIGH)

This is the structural finding, and it explains the whole round.

Reference counts across `tests/` for the state the Slice 1-2 gates depend on:

| Symbol | Test files referencing it | What Round 3 found |
|---|---|---|
| `max_open_positions` | 10 | S1-04: gate never fires — counter is never incremented |
| `notify_position_opened` | **1** | the *writer* of that counter |
| `tick_spread` | 11 | S2-03: always `0.0` — attribute absent on the live signal |
| `_trading_halted` | 21 | S1-03: set by a path that bypasses persistence |
| `consensus_tick` | **0** | S5-03: the default price read path, entirely untested |

The pattern is consistent. Ten test files exercise the max-open-positions gate —
by assigning `open_positions` directly and asserting the gate blocks. That
verifies the gate's *logic*, which is correct. **Nothing tests that anything on
the decision-engine path ever writes that value**, which is the actual defect.
Its sole writer is referenced by one test file.

Every Slice 1-2 finding has this shape: the gate works; the input is never
populated. Unit tests with injected state cannot see it, because injecting the
state is precisely the step production omits.

**Minimal fix:** add **wiring tests** — a small set that drives a signal through
the real decision-engine path with mocked broker/feed and asserts the *side
effects*, not the return values: that `open_positions` incremented, that the
Gatekeeper's equity tracker moved, that a spread was populated on the object
handed to the gate, that the sizing result's `risk_approval_token` reached the
executor. Roughly a dozen assertions would have caught most of Round 3.

### S12-03 — Skips (MEDIUM)

156 `@pytest.mark.skip` markers or `pytest.skip()` calls across the suite. Most
are legitimate environment guards (`requires_redis`, missing optional deps), but
the set has not been reviewed as a whole, and per the project's own history a
path bug once silently disabled ~124 security tests without anyone noticing.

*Minimal fix:* print skip reasons in CI summary output and fail the build if the
skip count rises, so silent disablement is visible.

### Deliverable not produced

The playbook's slice-12 prompt asks for **one failing test for the
highest-severity untested invariant**, as proof. That was **not written** — this
round is audit-only, no code changes. The test to write first is stated here so
it is not lost:

> Drive one signal through `HOPEFXDecisionEngine.process_tick` with a mocked
> broker and a `RiskManager` configured with `_MAX_OPEN_POSITIONS=1`, twice.
> Assert the second call is blocked. On current code it will not be (S1-04),
> because `TradeExecutor` never calls `notify_position_opened`.

---

## Round 3 — Slice 13: dead code and duplication

Scope: repo root, 63 top-level Python packages, analysed by AST import graph
(tests and vendored trees excluded).

**Correction to S3-06 (Slice 3):** that finding said `backtest/` "contains its
own `engine.py`, `data_validator.py`, `transaction_costs.py` … so this needs
verifying". **Verified: they are genuine re-export shims** — 38-44 lines each,
244 lines total, and `backtest/__init__.py` documents the arrangement clearly.
`CLAUDE.md` is accurate on this point and the concern was unfounded.

| ID | Sev | Issue |
|----|-----|-------|
| S13-01 | HIGH | Duplication is not a tidiness problem here — **every duplicated pair in this codebase has already produced a confirmed defect** |
| S13-02 | MEDIUM | Five top-level packages have zero production imports (~790 lines) |
| S13-02a | **HIGH** | `websocket/` shadowed the `websocket-client` library, making the MT5 feed's REST fallback unreachable | `market_data/mt5_live_feed.py:35` |
| S13-03 | **CRITICAL** | Duplicate `OrderSide` enums inverted direction: every BUY reached OANDA as a SELL | `hopefx_engine.py:1444`, `brokers/oanda_stream.py:303` |

### S13-03 — Every BUY was submitted to OANDA as a SELL (CRITICAL) — FIXED

The ninth duplication in the S13-01 table, found by working through it. It is
the most severe defect in this round: not a gate that failed to block, but a
trade that went the **wrong way**.

`brokers/__init__.py` does not re-export `brokers.base` — it *redefines*
`OrderSide`, `OrderType`, `OrderStatus`, `Order` and `Position` with different
member values:

```
brokers.OrderSide.BUY       -> <OrderSide.BUY: 'buy'>
brokers.base.OrderSide.BUY  -> <OrderSide.BUY: 'BUY'>
same class? False        BUY == BUY? False
```

`hopefx_engine.py:1444` imported the package-level one and put it in the order
kwargs. `brokers/oanda_stream.py:303` decided direction with:

```python
signed_units = units if side == OrderSide.BUY else -units   # brokers.base
```

The equality was always False, so **every long went to OANDA as negative units,
i.e. a short**. Sells were correct only by accident, because the wrong branch
happens to be the sell branch. Nothing raised, nothing logged: the order was
accepted, just backwards.

Live OANDA is the next milestone, and the standalone engine is one of the two
paths that reaches it.

Two independent defects, both fixed:

1. **The call site** now imports `OrderSide` from `brokers.base` — the enum
   `OANDAStream` actually compares against.
2. **The comparison itself** was fail-to-the-wrong-direction: `units if side ==
   BUY else -units` treats *anything not BUY* as a sell, so any unrecognised
   value silently becomes a short. Replaced with `_signed_units()`, which
   normalises on the member value (immune to the class split), accepts
   BUY/LONG/SELL/SHORT in either case, and **raises** on anything else rather
   than guessing a direction.

**Deliberately not done: collapsing the two enums.** `brokers/__init__.py`
serialises `side.value` into API payloads and Redis position keys, and the
frontend compares those against lowercase literals
(`SignalIntelligenceCard.tsx:24` `d === 'buy'`, `PositionsTable.tsx:86`
`side === 'long'`, `OrderEntryForm.tsx:237`). Unifying the classes flips those
payloads to uppercase and breaks the comparisons silently — swapping one quiet
bug for another. The unification is still the right end state; it needs to be
done as its own change, with the frontend comparisons and any persisted Redis
keys migrated in the same PR.

`tests/unit/test_order_side_identity.py` pins the hazard (the two enums are
still incompatible), the fix (the engine imports from `brokers.base`), and the
guard (direction survives either enum; unknown sides raise). Both fixes were
mutation-checked: reverting either one fails the suite.

### S13-01 — Every "two of these" produced a bug (HIGH)

Round 3 found 64 issues across 13 slices. The single strongest predictor of a
defect was **the existence of a second implementation of the same concept**:

| Duplicated concept | Where | Defect it produced |
|---|---|---|
| `AccountInfo` dataclass | `brokers/base.py:278` vs `brokers/oanda.py:109` | **S1-01** — live OANDA blocks 100% of trades; the oanda-local copy has no `.get()` and no `equity` field |
| `KillSwitch` instance | `app.py:286` vs `kill_switch.py:1341` | **S2-01** — split brain; the ops mechanisms drive the instance the money path never reads |
| Halt flag | `_halt` vs `_trading_halted` | **S1-03** — the drawdown breaker sets one, sizing reads the other |
| `TransactionCostModel` class | `backtesting/engine.py:239` vs `backtesting/transaction_costs.py` | **S3-06** — the correct cost model is not the one the CLI instantiates |
| Feature builder | `inference_engine._build_features` vs `AdvancedPredictor` internal | **S4-01** — the drift guard validates a vector the model never scores |
| Engine implementation | `hopefx_engine.py` (1,706 ln) vs `HOPEFXDecisionEngine` + `TradeExecutor` | **S1-04, S2-02** — position counter and Gatekeeper wiring exist on one path only |
| Price read path | orchestrator Redis branch vs in-memory fallback | **S5-03** — freshness enforced on one, absent on the other |
| Private-channel guard | `broadcast()` vs `send_to_user()` | **S8-02** — the Round 2 fix applied to one sibling method |

Eight duplications, eight confirmed defects. The mechanism is consistent: a fix,
a gate, or a validation is applied to one copy, and the other copy keeps the old
behaviour. Nothing fails — the second copy simply carries on being wrong, and no
test notices because (per **S12-02**) tests exercise units, not wiring.

**Two live duplicates not yet implicated in a defect** — worth checking before
they are:

- **Three engine implementations**: `hopefx_engine.py` (root, 1,706 lines, 5
  importers), `execution/hopefx_engine.py` (1,073 lines, 1 importer),
  `execution/engine.py` (1,625 lines). Plus `execution/async_engine.py` (741).
- **Two smart routers**, both live: `execution/smart_router.py` (714 lines, 7
  importers) and `brokers/smart_router.py` (296 lines, 3 importers). Round 2
  fixed a duplicate-fill bug in "both smart routers" — the fix had to be applied
  twice, which is the cost being paid here.

**Minimal fix — and the highest-leverage item in this round.** Do not attempt a
consolidation sweep. Instead, for each pair above, delete the copy with fewer
importers and redirect its callers, **one pair per PR, starting with
`AccountInfo` and `KillSwitch`** — those two alone close S1-01, S1-02 and S2-01,
which are three of the four CRITICALs. Then add a CI check that fails when two
classes with the same name are defined in different modules under
`brokers/`, `execution/` or `risk/`.

### S13-02 — Packages with no production consumers (MEDIUM)

Of 63 top-level Python packages, five are imported by nothing outside their own
tree and tests:

| Package | Lines | Prod imports | Test files | Note |
|---|---|---|---|---|
| `websocket/` | 237 | 0 | 0 | `CLAUDE.md` lists it as a standalone server superseded by `api/ws_live.py` |
| `backtest/` | 244 | 0 | 3 | Shim whose stated purpose is back-compat for imports that no longer exist |
| `src/` | 175 | 0 | 0 | |
| `strategy/` | 100 | 0 | 1 | `CLAUDE.md` lists it as "live ML engine only" |
| `hopefx_graphql/` | 35 | 0 | 0 | |

(The `"websocket"` strings in `api/status.py:655` and
`infrastructure/health_engine.py:526` are health-probe labels, not imports.)

~790 lines. The line count is not the point — the **navigational** cost is.
`CLAUDE.md` spends a prominent table warning contributors away from four of
these directories, which is a warning that only exists because the directories
do. Deleting them removes the hazard and the documentation of the hazard
together.

`backtest/` deserves a specific decision: a compatibility shim with **zero
remaining consumers** has completed its job. Its three test files test the shim
itself, so they go with it.

**Minimal fix:** delete `websocket/`, `src/`, `hopefx_graphql/`; delete
`backtest/` and `strategy/` after confirming no external consumer depends on the
published package surface; remove the corresponding rows from the `CLAUDE.md`
canonical-vs-legacy table.

#### S13-02a — `websocket/` was not merely dead, it was shadowing (HIGH) — FIXED

Severity revised upward while fixing this. `websocket/` sat at the repo root,
which is ahead of site-packages on `sys.path`, so it captured **every**
`import websocket` in the project — including the one in
`market_data/mt5_live_feed.py:35` that wants the `websocket-client` library:

```python
try:
    import websocket           # ← got the local dead package
    WEBSOCKET_AVAILABLE = True # ← True even with websocket-client absent
except ImportError:
    WEBSOCKET_AVAILABLE = False
```

`WEBSOCKET_AVAILABLE` is the flag that turns on the REST fallback. Because the
shadow made the import always succeed, the `except ImportError` branch was
unreachable: rather than degrading to REST when the client library was missing,
the feed proceeded to `websocket.WebSocketApp(...)` (line 225) and raised
`AttributeError`. Verified directly — `import websocket` resolved to
`/…/HOPEFX-AI-TRADING/websocket/__init__.py`, and `hasattr(websocket,
"WebSocketApp")` was `False` while the module reported itself available.

So the deletion is not cleanup; it restores a fallback path that could not run.

One trap worth recording: removing the tracked files is **not** sufficient. An
empty leftover directory still resolves as a PEP 420 namespace package and keeps
shadowing (observed: `<module 'websocket' (NamespaceLoader)>`). The directory
itself has to go.

`tests/unit/test_no_stdlib_package_shadowing.py` pins all three properties: no
shadowing package at the repo root, `import websocket` yields the real client or
fails cleanly, and `WEBSOCKET_AVAILABLE` never claims an API that is absent.

---

## Round 3 — summary

64 findings across 13 slices, all **CONFIRMED** (traced to a line with a
reproducible failure scenario). **None are fixed** — this round was audit-only,
per `docs/AUDIT_PLAYBOOK.md`.

| Slice | Area | Findings | Highest |
|---|---|---|---|
| 1 | Money path | 11 | CRITICAL |
| 2 | Gates & kill switch | 7 | CRITICAL |
| 3 | Backtest ↔ live parity | 6 | CRITICAL |
| 4 | ML integrity | 7 | HIGH |
| 5 | Data layer | 3 | HIGH |
| 6 | Auth & money-in | 4 | HIGH |
| 7 | State & crash recovery | 5 | HIGH |
| 8 | Realtime transport | 4 | HIGH |
| 9 | Frontend correctness | 3 | HIGH |
| 10 | Frontend & UX design | 5 | HIGH |
| 11 | Ops & deployment | 4 | HIGH |
| 12 | Test quality | 3 | HIGH |
| 13 | Dead code & duplication | 2 | HIGH |

**The four CRITICALs, in fix order:**

1. **S1-01** — `BROKER_TYPE=oanda` blocks 100% of trades (duplicate `AccountInfo`).
2. **S1-02** — the fix for S1-01, done naively, silently sizes against a
   fabricated $100k. Fix both together or neither.
3. **S2-01** — split-brain kill switch; one activation endpoint stops trading
   and the other does not.
4. **S3-01** — the default backtest is frictionless, so every performance
   figure quoted from it is gross of costs that would consume the edge.

**Two corrections made during the round**, recorded in place: S1-03 was
overstated as CRITICAL (the pre-trade gate does block; the real defects are
persistence and propagation), and S4-04 was overstated (the code default is
warn-only, but `.env.example` ships `DRIFT_BLOCK=true`). An early superadmin
auth finding was a regex false positive and was withdrawn before publication.

**The one structural theme.** Slices 1, 2, 5, 8 and 13 all reduce to the same
mechanism: **a control is applied to one of two implementations, and the other
keeps the old behaviour.** No exception is raised, no test fails, and the logs
of an inert gate are indistinguishable from those of a passing one. S13-01 lists
the eight pairs; consolidating `AccountInfo` and `KillSwitch` alone closes three
of the four CRITICALs.

**Recommended next actions**, in order:

1. Triage the 16 open Dependabot alerts (9 high) — outside this round's scope,
   but cheaper than anything in it.
2. Fix S1-01 + S1-02 together, then S2-01. All three are duplication removals.
3. Wire the cost model into `run.py --mode backtest` (S3-01) and re-run any
   published performance figure.
4. Add the dozen wiring assertions from S12-02 before fixing anything else in
   Slices 1-2 — otherwise the fixes have no regression net.

---

## Round 3 — new finding raised while fixing S1-06

### S1-12 — Kelly's payoff term is derived from confidence, not reward:risk (MEDIUM, open)

`RiskManager._kelly(probability, confidence)` computes the payoff odds as:

```python
b = max(0.5, confidence * 3.0)
kelly = (p * b - q) / b
```

`b` in the Kelly criterion is the **reward-to-risk ratio of the trade** — how
much is won per unit risked. Here it is synthesised from the model's
*confidence*, which is a different quantity entirely. The consequence is that
break-even shifts with confidence rather than with the trade's actual stop and
target: at `confidence=0.7` (`b=2.1`) the function treats any win probability
above **0.323** as positive edge, on the assumption of 2.1:1 odds that nothing
verifies.

The caller has the real numbers. `calculate_position_size` already receives
`stop_loss_price` and `take_profit_price`, so the true ratio is
`|tp - entry| / |entry - sl|` — for the decision engine's ATR-based stops
(`_resolve_sl_tp`: 2×ATR stop, 3×ATR target) that is a genuine `1.5`, not
`2.1`. Sizing is therefore currently more aggressive than the configured stops
justify.

**Why it was not fixed with S1-06:** this is a modelling decision, not the unit
confusion S1-06 addressed. Changing `b` changes the size of every trade, so it
wants its own change, its own review, and a backtest comparison — with real
costs now charged (S3-01), that comparison is finally meaningful.

**Minimal fix:** pass the reward:risk ratio into `_kelly` when SL/TP are known,
falling back to the confidence proxy only when they are not; assert in a test
that a 1:1 trade requires `p > 0.5` to size at all.
