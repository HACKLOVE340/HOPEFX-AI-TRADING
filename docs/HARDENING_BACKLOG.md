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
