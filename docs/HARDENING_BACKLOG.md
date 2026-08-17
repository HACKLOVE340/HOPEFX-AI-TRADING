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
| S4-01 | HIGH — **FIXED** | Drift guard and both feature-validation gates run on a vector the model **never scores** | `inference_engine.py:796,857,903` |
| S4-02 | HIGH | NaN/Inf features imputed with `0.0` and scored anyway | `inference_engine.py:427-435` |
| S4-03 | HIGH | ">95% zeros — possible silent upstream data failure" is logged, then traded on | `inference_engine.py:437-447` |
| S4-04 | MEDIUM | `DRIFT_BLOCK` defaults to **false** — drift warns and trades | `inference_engine.py:78` |
| S4-05 | MEDIUM | Drift guard silently disables itself when training stats are missing | `inference_engine.py:645-647` |
| S4-06 | MEDIUM | Feature-builder fallback changes the feature set and logs at `debug` | `inference_engine.py:384-397` |
| S4-07 | LOW | Docstring promises a feature-count-mismatch gate that does not exist | `inference_engine.py:360` |

### S4-01 — The drift guard watches features the model does not use (HIGH) — FIXED

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

**Fixed** by making the guard follow the model rather than forcing the two
builders together:

* `AdvancedModelPredictor` records the exact matrix it hands to
  `model.predict_proba` in `last_scored_features` — after column alignment,
  imputation and ordering, so it is what the model really saw, not the raw
  builder output. It is cleared at the top of every `predict_proba`, so a call
  that returns neutral without scoring cannot leave a stale row behind.
* `InferenceEngine._features_for_drift_check()` prefers that matrix and falls
  back to the engine's own vector only when the predictor exposes none —
  warning once when it does, because that is degraded coverage, not clean
  coverage.
* The drift check moved from step 3b (before scoring) to step 4b (after), since
  the scored matrix does not exist until the model has run. `_check_feature_drift`
  appends to a rolling buffer, so it must be called exactly once per prediction
  — running it on both vectors would double-count. The cost is one
  already-computed probability discarded when `DRIFT_BLOCK` trips.
* `_check_feature_drift(None)` now returns False *without* touching the buffer,
  and is documented as "nothing was scored" rather than "no drift" — the S4-05
  distinction.

Not addressed: the two builders still exist. Unifying them is a larger change
that risks altering the live feature vector, and the guard now watches the
right one either way.

### S6-05 — A mock auth service outlived its test and approved every login (HIGH) — FIXED

The single remaining failure of the Round 3 sweep, and it was not flakiness.

`tests/integration/test_api_routing.py::test_login_with_invalid_credentials_returns_401`
passed alone and failed in the full run with `assert 200 in (401, 400, ...)` —
`POST /api/auth/login` returned **200 OK for invalid credentials**.

Bisected to `tests/unit/test_auth_coverage.py`. Its `client` fixture calls
`auth.router.set_auth_service(mock_svc)` — a **module global** — with a mock
whose `login()` returns `(True, "Login successful", {...})` unconditionally, and
never restores it. From that fixture onward, every login in the process was
answered by a service that approves anything.

Three test files installed an auth service; none restored it:

| File | set | restore |
|---|---|---|
| `tests/unit/test_auth_coverage.py` | 2 | 0 |
| `tests/integration/test_auth_flow.py` | 1 | 0 |
| `tests/e2e/test_auth_billing_trading.py` | 2 | 0 |

**The red test is the smaller half of this.** Any auth assertion running after
that fixture was exercising a mock that always succeeds rather than the real
service — the S12-01 pattern again: tests that look like they verify a safety
property while verifying nothing. How much downstream auth coverage was
hollowed out has not been quantified.

`auth/router.py` already had `reset_rate_limit_state()` "to prevent cross-module
state leakage", so the convention existed — the auth service simply had no
counterpart.

**Fix:** added `reset_auth_service()` alongside it, and made `set_auth_service()`
return the value it displaced so a caller can restore without touching globals.
All three fixtures converted to `yield` + reset.
`tests/unit/test_auth_service_isolation.py` pins the hooks and adds an AST guard
that fails if any of those files installs an auth service without restoring it.

Verified against the original cross-file reproduction: the two-file run that
produced `200 OK` for a bad password now passes.

### S4-06 — The stationarity test certified features it never examined (MEDIUM) — FIXED

`StationarityTester.test()` returned a **permissive** result when `statsmodels`
could not be imported:

```python
return StationarityResult(
    adf_pvalue=0.01,        # what a confidently stationary series produces
    kpss_pvalue=0.10,
    is_stationary=True,     # ← certifies a test that never ran
    method="SKIPPED (statsmodels unavailable)",
)
```

The fabricated p-values are worse than the boolean. `adf_pvalue=0.01` reads as
strong evidence, so any caller looking at the numbers rather than `method` saw a
confident pass. Every feature was waved into training and inference regardless
of whether it was stationary — which is the one thing this check exists to
prevent.

`statsmodels` is in `requirements.txt`, so a correct deployment has it; this is
the behaviour on an import failure, and it must be "unknown, therefore not
stationary" rather than "passed". Same principle as the drift guard in S4-05.

**Fix:** fail closed — `is_stationary=False`, `adf_pvalue=1.0` (no evidence
against a unit root), `kpss_pvalue=0.0`, a `— fail-closed` suffix on `method`,
and a WARNING naming the feature. Controls in the new test file confirm the
tester still passes white noise and still rejects a random walk when statsmodels
*is* present, so the fix did not simply make it useless.

**Ninth test found protecting a defect.**
`test_ml_pipeline_full.py::test_test_without_statsmodels` asserted
`is_stationary is True` — it *required* the tester to certify a series it had
not examined. Corrected, with added assertions that the p-values do not
impersonate a result.

### S4-05b — A diagnostics test that could never fail (LOW) — FIXED

`test_diagnostics.py::test_missing_required_vars_reported_as_critical` popped
`SECRET_KEY` and asserted the env-var check reported `critical`. But
`SECRET_KEY` is not the required variable — it is one of three accepted
*aliases* for `SECURITY_JWT_SECRET` (`security/diagnostics.py:327`), which the
suite sets at import. The canonical name was still present, the check correctly
returned `ok`, and the assertion fired against code that was behaving properly.

The production check was right; the test was wrong. It now clears the canonical
name and every alias, and a companion test pins the aliasing behaviour it
tripped over.

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
| S7-02 | HIGH — **FIXED** | Crash between broker ack and `add_position` leaves a permanently untracked live position | `trade_executor.py:352-388` |
| S7-03 | HIGH | Boot restores persisted positions with **no reconciliation** against the broker | `position_manager.py:595-615` |
| S7-04 | MEDIUM | A malformed record aborts restore mid-loop, leaving partial state and no log | `position_manager.py:605-615` |
| S7-05 | MEDIUM — **FIXED** | No idempotency key on the `TradeExecutor` broker path | `trade_executor.py:352` |

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

### S7-02 — The ack-to-persist window (HIGH) — FIXED

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

**Fixed** together with S7-05, which is its prerequisite:

* `TradeExecutor` takes an optional `state_store` and generates a
  `client_order_id` (`hopefx-<16 hex>`) per order, passed to
  `place_market_order` so a broker fill can be traced back to a local intent.
* The intent — symbol, side, quantity, SL/TP, `decision_id`,
  `risk_approval_token` — is journalled **before** submission and cleared only
  after `add_position` returns.
* `PositionManager.audit_order_intents()` reports every surviving intent at
  boot at CRITICAL, saying whether that symbol is currently open. Without this
  the journal would be state nothing reads — the defect class this round keeps
  finding. `restore_from_redis` calls it after the broker reconciliation.
* Journal failures are logged, never fatal: a Redis outage must not make us
  disown a position the broker filled, and paper/dev runs have no store at all
  (reported once at WARNING rather than blocking trading).

Wired in `core/startup_factories.py::init_trade_executor`, which shares the
PositionManager's Redis store. Three mutations verified to fail the tests:
journalling after the broker call, dropping the `client_order_id`, and clearing
the intent before the position is tracked.

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
| S8-03 | MEDIUM — **PARTLY FIXED** | No sequence numbers — a client cannot detect messages missed across a reconnect | throughout |
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

**Partially fixed — gap *detection* only.** Every outbound message now carries
`channel` and a monotonic `seq`, stamped by `LiveConnectionManager._stamp()` in
both `broadcast()` and `send_to_user()`. A client tracks the last seq per
channel; a jump means it missed something.

The counter is **per channel, not per connection**, deliberately: the payload is
serialised once per broadcast and shared by every subscriber, which is the O(1)
fan-out S8-01's fix depends on. A per-connection counter forces a re-serialise
per client. A test asserts all subscribers receive byte-identical payloads so
this cannot be undone accidentally.

**Still open: resume/snapshot.** A client that detects a gap has no way to
recover except to reload — there is no snapshot-on-subscribe for `positions`,
`account` or `risk`. That needs a per-channel snapshot source and is a feature
rather than a fix. Detection first is still worth having: the UI can now *tell*
it is out of sync, which is what S9-03's positions panel uses.

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
| S9-02 | MEDIUM — **FIXED** | The only freshness signal shown is ingest-time confidence, which never decays | `LivePriceTicker.tsx:217` |
| S9-03 | MEDIUM — **PARTLY FIXED** | ~79% of components and pages render no error state | `frontend/src` |

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

**Fixed for the sharpest case: the positions panel.** `PositionsTable` rendered
`filtered.length === 0` as "📭 No open positions", and `positions` comes from
the WebSocket store — so a stalled feed, a dropped socket or a failed load all
produced an empty array and a confident claim that the trader was flat. That is
the false negative that matters here: it is the panel checked before deciding
whether to intervene, and it read identically whether you were genuinely flat or
the client had no idea.

`EmptyPositions` now distinguishes three states — unknown (`feedStale` or
`wsStatus !== 'connected'`), broker-initialising, and genuinely flat — and the
unknown case says "Can't confirm positions … check your broker directly before
acting". It consumes the `feedStale` flag added for S9-01.

**One existing test was asserting the defect.** `pages.test.tsx`'s "shows no open
positions when positions list is empty" rendered with the store default
`wsStatus: 'disconnected'` and asserted the confident empty state — i.e. it
required the panel to claim you were flat while the socket was down. Corrected
to set a live feed, with a companion test for the disconnected case.

**Still open: the rest of the ~79%.** Orders, account equity and risk-limit
views have not been triaged, and the runtime pass below was still not performed.

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
| S10-05 | — **FIXED** | No latency or data-age indicator anywhere | see S9-01 |

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
| S12-04b | **CRITICAL** | Equity never reached the risk manager, so the drawdown circuit breaker could not trip | `hopefx_engine.py` |

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

#### S1-01b — The same broker-local AccountInfo in `brokers/ibkr.py` (CRITICAL) — FIXED

Found while re-verifying S1-01. The OANDA copy was removed; an identical one
in `brokers/ibkr.py:117` was not, because the original sweep looked at the
OANDA path only.

It had both of S1-01's defects: `nav` instead of `equity`, and no `.get()`.
`RiskManager.assess_risk` reads `account_info.get("equity")`, so an IBKR-backed
account raised `AttributeError` inside the pre-trade risk assessment — the
exact failure that blocked 100% of trades on live OANDA. `execution/execution.py:475`
imports `IBKRBroker`, so this was a live path.

**Fix:** deleted the local dataclass, imported `brokers.base.AccountInfo`, and
mapped IBKR's vocabulary onto the canonical fields — `NetLiquidation` → `equity`
(the `.nav` alias still resolves), `BuyingPower` → `margin_available`,
`positions_count` now populated. `tests/unit/test_account_info_contract.py`
gained an AST guard that fails if any module under `brokers/` defines
`AccountInfo` again, plus a test running `assess_risk`'s exact call against the
IBKR return type.

#### S12-04b — The drawdown circuit breaker could not trip (CRITICAL) — FIXED

Fourth instance of the same family, and the worst placed. Found by an AST sweep
for async broker calls whose result is dereferenced without being awaited — a
*different shape* from S12-04/S12-04a, which the `run_in_executor` guard could
not see. `hopefx_engine.py::_update_equity`:

```python
info = self._broker.get_account_info()   # async def on every broker
equity = float(info.get("equity", 0))    # AttributeError on a coroutine
```

The `AttributeError` was caught by the method's own
`except Exception: logger.warning("Equity update failed: %s", exc)` — confirmed
verbatim in the test output — so it failed silently on every cycle.

`RiskManager.update_equity()` is not bookkeeping. It recomputes peak equity,
current drawdown and daily drawdown, and **auto-halts trading when the drawdown
limit is breached** (`risk/manager.py:1289`). Never calling it means all three
stay at their initial values, so **the drawdown circuit breaker cannot trip no
matter how much the account loses**.

Three sibling broker calls in the same file were already correctly guarded with
`inspect.isawaitable`; this one was not — the same "fix applied to one of N
copies" mechanism S13-01 documents, this time within a single function's
neighbours.

**Fix:** routed through `execution.broker_call.call_broker`, plus an
`_acct_field()` helper so both the `AccountInfo` dataclass and the plain-dict
connector responses are read correctly.

`tests/unit/test_broker_calls_are_awaited.py` gained a second AST guard for this
shape — an assignment from a bare async broker call whose bound name is
dereferenced on the next line — and `hopefx_engine.py` was added to the
money-path list. Verified to fail when the fix is reverted.

**Scope note, stated plainly.** A codebase-wide sweep flags ~333 call sites of
this general shape. Most are false positives: sync brokers, results awaited by a
caller, or correct helpers like `brain/brain.py`'s `_await_or_return`. The four
confirmed instances were on the money path and are fixed; a full triage of the
remainder is a separate piece of work, not something this round completed.

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

### S1-13 / S1-14 — The configured position cap was never enforced (HIGH) — FIXED

Found by installing `hypothesis` and running `tests/unit/test_property_based.py`,
which had **never executed** in this environment — see the verification note
below.

**S1-13.** `size_order` and `calculate_position_size` clamped notional with the
module global `_MAX_POSITION_PCT` (`RISK_MAX_POSITION_PCT`, default 0.05) and
never read `self._config.max_position_size_pct`. A caller constructing
`RiskManager(config=RiskConfig(max_position_size_pct=0.02))` got 5% applied, not
the 2% it asked for — a risk limit accepted, stored, reported back through
`get_limits()`, and silently not enforced. The property test caught it as:

    Dollar risk 215.00 exceeds max 200.00 (equity=10000 size=5.0 sl_dist=43.00)

Fixed by clamping with `min(_MAX_POSITION_PCT, config.max_position_size_pct)` —
config may tighten the environment ceiling, never loosen it. Both directions are
asserted.

**S1-14.** Nothing capped *loss at the stop*, only notional (exposure). Added a
risk-at-stop clamp for callers that supply a stop. Its reach is narrow and worth
stating precisely rather than overclaiming: it only binds when
`stop_distance > entry_price`, which is impossible for a long (the notional cap
already implies the risk cap there) and reachable only for a short whose stop
sits further above entry than the entry price itself. In that case it pulls
notional below the minimum and the trade is refused, which is correct.

**On causation — the honest sequence.** Neither defect was introduced this
round, and neither was newly *created* by S1-06 or S1-12. They were **masked**:
S1-06 had Kelly bounded by `_MAX_POSITION_PCT`, so it saturated at 0.05 for
every signal and sizing never came close to either cap. The property test was
passing for the wrong reason. Fixing Kelly removed the accident that was hiding
a real breach.

**Verification note — a genuine gap in this round's earlier claims.** The
"zero new failures against the audit baseline" statements on the preceding
commits were true for the tests that *ran*, and 30 test files never collected in
this container for want of `hypothesis`, `scipy`, `scikit-learn`, `matplotlib`,
`joblib`, `websockets` and `fakeredis` — all of which are declared in
`requirements-ci.txt`, so CI would have caught this. Two of the uncollected
files (`test_property_based.py`, `test_risk_properties.py`) target
`risk/manager.py`, the module changed most invasively. That limitation was not
stated at the time; it should have been. After installing the missing packages,
the 30 files were re-run against both trees: **147 failures on each, zero new**,
once S1-13 was fixed.

**S7-02 follow-up — a startup-ordering fragility, found and closed in the same
pass.** `init_trade_executor` reads the PositionManager's Redis store, but
`trade_executor` cannot declare `position_manager` as a registry dependency:
`core/component_registry.py` runs a Kahn topological sort in which a *failed*
dependency causes the dependent to be **skipped**, so a Redis outage would have
stopped trading entirely rather than merely stopped journalling. Ordering was
therefore relying on registration position. `TradeExecutor._resolve_store()` now
resolves the journal lazily on first use, so an executor constructed before the
position manager still picks it up.

### S1-12 — Kelly's payoff term is derived from confidence, not reward:risk (MEDIUM) — FIXED

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

**Fixed exactly to that scope**, and no wider — the scoping is the interesting
part:

* `_kelly(probability, confidence, reward_risk=None)` uses the ratio as `b` when
  one is supplied; otherwise the confidence proxy is unchanged.
* `_reward_risk_from_prices()` derives it from entry/stop/target, returning
  `None` for a missing stop or a stop sitting on the entry (zero risk,
  undefined ratio). `None` means "fall back", never "assume something
  favourable".
* `calculate_position_size` forwards its `stop_loss_price` / `take_profit_price`
  through `_MinimalSignal` so they reach sizing.
* `_STOP_ATR_MULT` / `_TARGET_ATR_MULT` now drive `_compute_stop_take`, and
  `_DEFAULT_REWARD_RISK` is derived from them rather than written out twice.

**Deliberately not defaulted.** `size_order` does *not* fall back to
`_DEFAULT_REWARD_RISK`. `confidence` feeds nothing else in that function, so
always supplying a ratio would drop confidence out of sizing entirely and make
position size insensitive to signal quality — a much larger change than this
finding asks for, and one that needs the backtest comparison the finding calls
for. Callers with real stops get the correct payoff term; callers without keep
their existing behaviour.

**Sizing impact, for the callers that do supply stops** (p=0.55, confidence 0.7):

| stops | old `b` | old kelly_f | new `b` | new kelly_f |
|---|---|---|---|---|
| none (legacy) | 2.10 | 0.3357 | — | 0.3357 (unchanged) |
| 1:1 | 2.10 | 0.3357 | 1.00 | 0.1000 |
| 2:1 | 2.10 | 0.3357 | 2.00 | 0.3250 |
| 1.5:1 (ATR 2x/3x) | 2.10 | 0.3357 | 1.50 | 0.2500 |

Note it is not a uniform reduction: the old proxy *under*-stated `b` at low
confidence, so a low-confidence signal with generous stops now sizes larger.
Run the backtest comparison before live.

**One regression caught by this change and fixed with it:**
`_reward_risk_from_prices` originally coerced with `float()`, which accepts
anything implementing `__float__` — a `MagicMock` returns `1.0`. A signal
carrying no stops at all was therefore read as a fabricated 1:1 ratio, and
`test_pre_trade_invariant_gate.py::test_corrupt_signal_sizes_zero_even_in_monitor_mode`
started sizing 1.28 on a NaN-confidence signal. The helper now requires a
genuine `int`/`float`. That was a real robustness hole, not just a fixture
artefact: any object with `__float__` could have set the payoff term.


---

## Round 4 — Slice F1: runtime failure matrix

Scope: 12 money-relevant pages rendered against five broken-backend states plus
a healthy control, with the axios adapter stubbed so the real `hooks/useApi`
runs. `frontend/src/test/f1_runtime_failure_matrix.test.tsx`.

This is the pass S9-03 recorded as **not performed**.

**The instrument matters.** A word-list classifier ("does the page say error?")
was tried first and discarded: it reported `ERROR_SHOWN` on *healthy* pages
because a connection badge renders the word "disconnected". The objective
question needs no vocabulary — **does the page render differently when the
backend is unreachable?** If output is identical whether the backend is healthy
or dead, the user cannot tell, and that is the finding.

**Two instrument failures were caught and corrected before reporting:**

1. The first stub set `axios.defaults.adapter` only. `api` is built with
   `axios.create()` at import time, which snapshots the defaults — so **zero
   requests were intercepted** and every page trivially looked "identical". The
   harness now stubs `api.defaults.adapter` too and counts requests per render;
   a page with no requests is no longer asserted on.
2. `Trading` reported CRASH in all six states including healthy. It is a harness
   artefact: the shared `src/test/setup.ts` mocks `lightweight-charts` without
   `HistogramSeries`. Not a product defect; excluded.

| ID | Sev | Issue | Location |
|----|-----|-------|----------|
| F1-01 | **HIGH** — **FIXED** | Three pages issue requests, every request fails, and the page renders byte-identically to the healthy case | `Watchlist`, `TradeJournal`, `RiskCalculator` |
| F1-02 | MEDIUM | Three more are indistinguishable under a dead or silent WebSocket | `Wallet`, `PriceAlerts`, `Portfolio` |
| F1-03 | LOW | The shared chart mock is incomplete, so chart pages cannot be render-tested | `src/test/setup.ts` |

### F1-01 — Pages that cannot tell you the backend is gone (HIGH)

| Page | requests issued | identical to healthy in |
|---|---|---|
| `RiskCalculator` | 3 | 5/5 states |
| `Watchlist` | 2 | 5/5 states |
| `TradeJournal` | 4 | 5/5 states |

Verified verbatim. `Watchlist` with the backend **completely unreachable**
renders its full symbol list and the line:

> *"Live prices refresh every 5 seconds."*

— which is false, with no indication anywhere. Every request it made failed.
This is the S9-03 shape (a confident statement the data does not support),
confirmed at runtime rather than inferred from reading.

`TradeJournal` renders "All Trades (n)" and "Mistakes (n)" counts identically
whether those counts were fetched or the fetch failed.

**Contrast — what correct looks like:** `Dashboard`, `TradingDashboard` and
`Performance` render differently in **all five** failure states. The capability
exists in this codebase; it is not applied uniformly.

### F1-02 — Blind to the socket specifically (MEDIUM)

`Wallet`, `PriceAlerts` and `Portfolio` degrade visibly when HTTP fails but are
unchanged when the WebSocket is dead or silent. Given S9-01 (the client could
not detect a stalled feed at all until this round), a dead socket is the more
likely production failure of the two.

**Harness limits, stated:** jsdom not a browser; pages rendered without the
app's theme/auth/layout providers, so some render empty here and would not in
the app; only pages that issued a request are asserted on. A dev-server pass
against a genuinely stopped backend is still worth doing — this catches the
cheap majority in CI.


### F1-01 — FIXED

All three had the same shape: a `catch` that swallowed the failure and silently
substituted a fallback.

| Page | was | now |
|---|---|---|
| `Watchlist` | `catch { /* show empty list */ }` + `catch { /* keep existing prices */ }` | 5/5 identical → **2/5** |
| `RiskCalculator` | `catch { /* fall back to store prices */ }` | 5/5 → **2/5** |
| `TradeJournal` | `Promise.allSettled` rejections → `setTrades([])`, `setStats(null)` | 5/5 → **2/5** |

The remaining 2/5 are `wsDead` and `wsSilent`, where HTTP succeeds — these pages
take their data over HTTP, so being unchanged there is correct, not a gap.

Degrading was never the problem; degrading *invisibly* was, because the page
then stated things it could not know. `Watchlist` announced **"Live prices
refresh every 5 seconds"** with every request failing. `RiskCalculator` showed a
green live-price dot while feeding a fallback price into position sizing.
`TradeJournal` rendered "All Trades (0)" as fact.

**Fix:** `hooks/useDataFreshness.ts` gives a page one place to record "my last
load failed"; `components/ui/StaleDataNotice.tsx` renders it (`role="status"`,
`aria-live="polite"` — important, not an emergency). The liveness claims are now
conditional: Watchlist's subtitle changes, and RiskCalculator's green dot is
suppressed while the fetch is failing.

**A defect introduced and caught during this fix.** `useDataFreshness` first
returned a fresh object every render. `TradeJournal` puts it in `fetchAll`'s
dependency array, so `fetchAll` was a new function every render, which re-ran
its effect, which fetched again — an unbounded request loop. The F1 harness's
own request counter caught it: **138 requests in a single render pass** where 4
were expected. The hook is now memoised, with two regression tests on object
identity. Worth noting the instrument found a bug in its own fix.

### F1-03 — the harness's limits, restated after use — **CORRECTED, see F1-04**

> This entry originally read: *"Two further artefacts appeared while iterating
> and are not product defects: `Dashboard` and `Performance` intermittently
> render empty inside the F1 file … order or timing pollution within the shared
> process. Recorded rather than chased."*
>
> **That was wrong, and wrong in the expensive direction.** Both pages were
> *crashing*, on a real product defect, and I filed it as instrument noise.
> "Renders empty" was a throw during render taking the whole route down. The
> tell was in the run output the whole time — vitest reported six unhandled
> `TypeError`s naming `Dashboard.tsx:499` and `Performance.tsx:412` — and I
> attributed it to test pollution without reading them. Chasing it would have
> cost one grep. See **F1-04**.

The genuine harness limits stand as listed in the slice header: jsdom is not a
browser; pages render without the app's providers; `lightweight-charts` is
mocked without `HistogramSeries`, so chart pages throw for reasons unrelated to
the backend (this is why `Trading` still reads `crash` in every column).


### S9-02 + S10-05 — FIXED together

They were one defect seen from two sides. S10-05: no data-age indicator existed
anywhere, so a frozen price and a live one were visually identical. S9-02: the
one freshness cue that *did* exist — `LivePriceTicker`'s "94%" quality score —
is assigned when a tick is ingested and never re-evaluated as it ages, so a tick
graded GOOD at 14:00 still read 94% at 15:00.

Compounded with S9-01, a stalled feed showed a frozen price **and** a reassuring
green percentage. The single visible cue actively reinforced the illusion rather
than correcting it.

**Fix:**
* `formatAge()` and `DATA_STALE_AFTER_MS` in `lib/utils` — age in the words a
  trader reads at a glance ("just now", "42s ago", "4m ago"). Negative ages from
  clock skew read as "just now"; a `-5s ago` invites distrust of the widget.
* `qualityIsMeaningful(lastDataAt)` — a missing timestamp returns **false**.
  Never assume fresh.
* `components/ui/DataAge.tsx` — `role="status"`, `aria-live="polite"`, and it
  re-renders on a 1s timer. Without the timer the age would freeze at whatever
  it was when the parent last rendered, which is the same class of bug it exists
  to expose.
* `LivePriceTicker` now shows an "Updated · 42s ago" indicator, and the quality
  percentage is **never painted healthy-green while the data is stale** — it
  greys out and appends "(as of last tick)".

Age is computed from **client arrival time**, not the server's `timestamp`
field: server clock skew cannot corrupt it, and "how long since we last heard"
is the question actually being asked.

Mutation-verified: forcing `qualityLive = true` (the original behaviour) fails
the end-to-end ticker test.

---

### S10-02 — FIXED (the frontend half)

The backlog entry above says *"this is not a frontend fix"*, and for the
split-brain source that remains true — S2-01 must still be fixed in the backend.
But reading the three surfaces turned up a second, independent defect that *is*
entirely frontend: they did not agree with each other.

| Surface | read |
|---|---|
| `AccountBar.tsx:157` | `account.kill_switch` |
| `RiskTransparencyStrip.tsx:42` | `risk.kill_switch_active ?? account.kill_switch` |
| `RiskDashboard.tsx:74` | `account.kill_switch` |

Three renderings of one fact, from two fields, with three precedences. A backend
populating `riskSnapshot.kill_switch_active` but not `account.kill_switch`
produced one badge reading HALTED and two reading nothing — on the same screen,
about the same switch. That is the S13-01 duplication pattern, in which every
duplicated pair found in this codebase had already produced a defect.

**Fix:** one `selectKillSwitch` in the store, deliberately an **OR** and not a
precedence chain:

```ts
export const selectKillSwitch = (s: AppStore): boolean =>
  Boolean(s.riskSnapshot?.kill_switch_active) || Boolean(s.account?.kill_switch);
```

A safety indicator may over-report, never under-report. All three surfaces now
read it, pinned by a test that greps each file and fails if any re-derives the
value itself.

---

### F1-02 — FIXED, and the finding was partly wrong

The entry above named `Wallet`, `PriceAlerts` and `Portfolio`. Two of those were
right; `Wallet` was not.

**`Wallet` has no socket dependency at all** — four one-shot HTTP reads on
mount, no `useStore`, no subscription. Rendering identically under a dead socket
is *correct* for that page, and bolting a feed warning onto it would have been
noise that trains a user to ignore the warnings that matter. What it genuinely
lacks is any statement of when the balance was read: fetched once at mount,
never refreshed, and displayed as a current figure indefinitely. That is S10-05
(data age), not a socket defect, and it is fixed as such — a `<DataAge>` beside
the balance with a 2-minute stale threshold.

The two real ones:

- **`PriceAlerts`** — the page whose entire promise is that it will tell you
  when something happens. Its Live Triggers tab read *"No live triggers yet.
  Alerts fire here in real-time via WebSocket."* With the socket down that
  sentence is false — nothing will ever appear there — and an empty list was
  shown for "nothing has triggered" and for "your alert channel is dead" alike.
  The S10-01 empty-vs-unknown defect, on the worst possible page for it.
- **`Portfolio`** — equity, margin, free margin, unrealized and daily P&L, all
  read from socket-fed store fields, all frozen at their last value with nothing
  saying so. Unrealized P&L is the number a trader watches to decide whether to
  close.

Two more surfaced once the instrument was fixed (below):

- **`Watchlist`** — worse than a display problem. The page overlays socket ticks
  *on top of* its 5-second HTTP price snapshot, so a stalled feed did not merely
  fail to update a row: it overwrote a **current** polled price with a frozen
  one, under the banner "Live prices refresh every 5 seconds". The overlay is
  now gated on the feed being live.
- **`Dashboard`'s connection badge** — said "Live", in glowing green, for as
  long as the socket was open, including while nothing had arrived for minutes.
  It is the one cue a trader glances at to decide whether the prices beside it
  can be trusted. It now describes the *feed*: "Stalled" in amber, with the age.

**Fix:** one `selectFeedLive` in the store, and `components/ui/LiveFeedNotice.tsx`
to render it.

```ts
export const selectFeedLive = (s: AppStore): boolean =>
  s.wsStatus === 'connected' && !s.feedStale && s.lastDataAt != null;
```

The third condition is the one that is easy to leave out. Connected-but-nothing-
received-yet is *unknown*, not live, and rendering unknown as live is S10-01 one
step earlier. `PositionsTable` had already begun the S10-02 drift with an inline
copy of the first two conditions; it now reads the shared selector, and a grep
test fails if any surface re-derives it.

#### The instrument was measuring nothing — failure #4

Before any of the above could be trusted, the harness had to be fixed, for the
fourth time in this slice.

**The ws\* axis had never been exercised.** The matrix swapped
`globalThis.WebSocket` for a `DeadSocket`/`SilentSocket` — but `useWebSocket` is
mounted in exactly one place, `App.tsx:475`, and this harness renders page
components directly. **No scenario ever constructed a socket.** Neither stub was
ever instantiated. The two ws\* rows differed from the control only by whatever
the harness itself wrote into the store, and what it wrote for `healthy` was
`wsStatus: 'disconnected'` from the shared `beforeEach` — while `wsSilent`
explicitly set `'connected'`. **The control was the most broken state in the
matrix, and every ws\* result was measured against it.** The comparison ran
backwards.

The fix drives the store directly, because the store is what the pages read:
`healthy` gets a fresh tick and `lastDataAt: Date.now()`; `wsDead` gets no tick
at all; `wsSilent` gets `feedStale: true` with the last tick it received still
sitting there — the S9-01 shape, and the reason a page cannot judge freshness
from "do I have a price?".

A second correction: `SOCKET_FED`, the list of pages the ws\* axis can judge,
listed `Performance` on first writing. `Performance` has no `useStore` in it at
all. Removed.

**Result: 12 failing ws\* rows → 0.** Pages exempted from that axis, with the
reason recorded in the test: `Wallet`, `TradeJournal`, `PnLDashboard`,
`Performance` (REST-only), and `RiskCalculator` under `wsDead` specifically —
its socket use is a *fallback* reached only when HTTP fails, so with no tick in
the store and healthy HTTP it is right to say nothing. The misleading case is a
tick that exists and has stopped moving, which is `wsSilent`, and that one is
asserted.

---

### F1-04 — A partial payload takes down the whole route (HIGH)

What F1-03 misfiled as harness noise. Three sites, one shape: a field read
without a guard on a payload that is documented — by the component's own copy —
to arrive incomplete.

**`Performance.tsx:412`** — `pub.total_trades.toString()`. The four stats beside
it *are* guarded, two of them with the subtitle **"Need 50+ trades"**. So the
component knows this payload arrives partially populated, and two of its six
tiles were left out. The same page guards the same field correctly 140 lines
later (`wr.total_trades ?? '—'`) — the S13-01 duplication pattern again: two
copies of one rule, one of them wrong. `max_drawdown_pct` had the same gap, and
`start_date` was guarded against the `'—'` sentinel but not against absence, so
it printed **"Paper trading started: undefined."**

**`Dashboard.tsx:481`** — `if (err || !regime)` catches null and nothing else.
An object without a `regime` field passed the guard and threw on `.replace` of
undefined. `confidence` and `volatility` had the same gap.

`.toString()` on undefined throws *inside render*, and a throw in render takes
the route down, not the tile. A user asking "how is my strategy doing?" got a
blank screen.

**Fix:** guards at each site, and the interfaces widened to `| null` — typing
these as required is what let the crash past `tsc` in the first place. The
regime panel additionally tracks whether the request has returned, so a response
that arrived carrying no regime says "Regime data unavailable" instead of
spinning forever: unknown rendered as loading is the same silent-failure shape
one layer down.

**Both pages are now scoreable by the matrix** — their rows read `?` in every
column, healthy included, because they never rendered. `Dashboard` immediately
reported a real F1-02 finding on its first honest run (the "Live" badge above).

#### Nine tests were asserting the defective behaviour

Found and corrected while fixing the above — each had pinned in the old
behaviour:

- `integration.test.tsx` required the badge to read **"Live"** on an open socket
  that had delivered nothing. That is S9-01 stated as a requirement.
- `pages.test.tsx` set `wsStatus: 'connected', feedStale: false` — with no
  `lastDataAt` — and required a confident "No open positions".
- `pages_portfolio_performance.test.tsx`'s *"renders account summary section"*
  matched `/balance/i` against a page whose `account` is null, so it was passing
  on the page **subtitle** ("Balances, equity curve, …") and had never once
  looked at the account summary. It now sets an account and asserts the tile.

---

## Round 4 — Slice F2: money-committing surfaces

Scope: every surface where a click moves capital — `OrderEntryForm`,
`PositionsTable` close and close-all, `VoiceTradingPanel`, `Wallet`
deposit/withdraw, `CryptoCheckout`, `PricingPage`. The playbook's questions:
can it double-submit; does it confirm with the actual numbers; what does it do
when the price it quotes is stale; **what happens if the request times out**.

### F2-01 — "Order failed" is a claim, and on a timeout it is a false one (HIGH)

`OrderEntryForm.tsx:340`, `PositionsTable.tsx:236` and `:251`,
`VoiceTradingPanel.tsx:93`, `Wallet.tsx:94`.

The axios instance carries `timeout: 30_000` (`useApi.ts:15`). A broker that
takes 31 seconds produces an error with **no `response`**, which falls through
every one of these catches to its generic branch:

| surface | said |
|---|---|
| `OrderEntryForm` | `Order failed` |
| `PositionsTable` | `Close failed` / `Close all failed` |
| `VoiceTradingPanel` | `Command failed. Nothing was executed.` — **spoken aloud** |
| `Wallet` | `Deposit failed.` / `Withdrawal failed.` |

None of that is known. A timeout means the answer never came back, not that the
order was refused — it may be live at the broker right now. And the natural
response to "Order failed" is to place it again, at which point the trader holds
double the position they intended with one stop covering half of it. The voice
panel is the sharpest: it asserts *"Nothing was executed"* out loud, and for the
kill-switch branch that tells an operator trading is still running when it may
already have been halted.

**The distinction already exists in this codebase**, reasoned out in exactly
these terms — for logging in:

```
/** True only for a DEFINITIVE auth rejection … as opposed to a
 *  timeout/network/5xx, which says nothing about whether the session is
 *  actually valid. */
export function _isDefiniteAuthRejection(err: unknown): boolean
                                                    — useApi.ts:198
```

Written once, correctly, and the path that moves money never got it. S13-01 in
its most expensive form.

**Fix:** `describeSubmitFailure(err, what)` in `lib/utils.ts` returns
`{ message, outcomeKnown }`. `response` present → the server refused, definitive.
`request` present with no response → unknown, and the copy says so: *"We never
heard back about your order. It may have gone through — check your open
positions before doing anything else."* Deliberately **not** "try again", which
is what `extractApiError`'s timeout copy says and is right for a read and wrong
for a write. Close and close-all additionally `invalidate()` on an unknown
outcome, so the panel refetches the truth instead of showing an exposure that
may no longer exist.

### F2-02 — One resolver slot for a dialog that can be asked twice (MEDIUM)

`ConfirmDialog.tsx:72`

```ts
const confirm = useCallback((opts) => {
  setState({ open: true, opts });
  return new Promise<boolean>(resolve => { resolverRef.current = resolve; });
}, []);
```

`resolverRef` is one slot. A second `confirm()` overwrote the first resolver and
the first promise was then **never settled** — not resolved, not rejected. Every
caller awaits it before setting its busy flag:

```ts
const ok = await confirm({ … });
if (!ok) return;
setSubmitting(true);            // OrderEntryForm.tsx:328
```

so the displaced caller hung forever and its `finally` never ran. A submit
button disabled while a confirmation is pending stays disabled for the life of
the page.

Reachable because `setSubmitting(true)` comes *after* the await, so the submit
button is live for as long as the dialog is open. The backdrop blocks the mouse
but focus is not trapped, so Enter still submits the form behind it.

**It did not fire two orders** — the surviving resolver belonged to the second
call, so exactly one action proceeded. The defect is the abandoned promise, not
a double-submit. **Fix:** settle the displaced promise `false` before opening
the new one. Nobody is looking at a dialog that has been replaced, and the only
safe answer to a confirmation nobody saw is no.

### Examined and **not** defects

- **`CryptoCheckout`** — `/payments/crypto/address` and the Flutterwave init
  both move no money: the first mints a deposit address, the second returns a
  link the user must complete on the processor's own page. A timeout on either
  is genuinely retryable and "please try again" is correct advice. No change.
- **`OrderEntryForm` confirmation content** — already restates symbol, side,
  quantity, entry, stop, take profit and **max loss at stop** (S10-01/S10-03),
  so the person confirming can check the magnitude rather than agree to a
  category. Now warns from `selectFeedLive` rather than a local `feedStale`
  read, so an order priced before the first tick arrives is covered too, and the
  rule has one copy rather than two (the S10-02 drift).

### A test that proved nothing, caught by mutation

The first version of the double-submit test passed identically with and without
the fix. `vi.resetModules()` gives `OrderEntryForm` a fresh `ConfirmDialog`
module with a fresh React context, so pairing it with the top-level
`ConfirmDialogProvider` import gave the form a provider it could not see —
`useConfirm` fell back to its always-refuse stub (`ConfirmDialog.tsx:47`) and no
dialog ever opened. The test asserted its way through an early return. The
provider is now imported from the same module graph, and the escape hatch is
gone: if the dialog does not open, the test fails rather than passing quietly.

That fallback is itself correct — refusing when there is no provider is
fail-closed, and it is commented as such. It is only dangerous in a test that
does not notice it has been taken.

---

## Round 4 — Slice F4: routing, guards, and authorization

Scope: 86 `<Route>` declarations in `App.tsx`, four guards (`AuthGuard`,
`AdminGuard`, `SuperAdminGuard`, `SubscriptionGate`) and the three helpers that
compose them (`gated()`, `adminOnly()`, `superAdminOnly()`).

### Route/page reconciliation — clean

70 lazy route components, **every one resolving to a real file**, and **no
top-level page in `src/pages` without a route**. No dead routes, no orphaned
pages. Recorded rather than tested.

Every privileged route goes through a helper, and all three helpers nest their
guard inside `AuthGuard`. That composition is now pinned by a test, because
three of the four guards are only safe *because* of it:

| guard | with no `user` | why it needs AuthGuard |
|---|---|---|
| `SuperAdminGuard` | spinner | a logged-out visitor gets a spinner that never resolves |
| `SubscriptionGate` | spinner | same |
| `AdminGuard` | spinner *only if* `isAuth` | with `isAuth` false and a persisted user it falls through to the role check |

None of those is reachable through `App.tsx` today. They are one careless
`<AdminGuard>` on a route away from being reachable.

### Flash of protected content — none found

The playbook's emphasised question. All four guards render a spinner while the
role is unresolved, and tests now pin that a logged-out visitor and an
authenticated-but-unsynced visitor both get **no children** from `AdminGuard`,
`SuperAdminGuard` and `SubscriptionGate`.

### F4-01 — `/profile/me` bypasses the gate on `/profile` (MEDIUM)

```
App.tsx:606   <Route path="/profile"     element={wrap(gated('profile', <Profile />))} />
App.tsx:607   <Route path="/profile/:id" element={wrap(<Profile />)} />
```

`/profile/:id` carrying no guard is deliberate — one trader viewing another's
public profile, the same design as the `Leaderboard` and `Marketplace` public
previews (the comment at `App.tsx:588` says so). The defect is that `Profile`
decided *which view* to show from the URL:

```ts
Profile.tsx:32   const isOwn = !id || id === 'me' || id === currentUser?.id;
```

So `/profile/me` resolved to `isOwn === true` — the full own-profile view, edit
controls included, calling `profileApi.get(undefined)` exactly as the gated
route does — at a URL with neither `AuthGuard` nor the subscription gate.

**What this does and does not expose — CORRECTED.**

> The first version of this entry called it *"a complete subscription bypass …
> got the page, the data, and the ability to edit it."* **That was wrong.**
> `PLAN_FEATURES.profile` is `'free'` and free is rank 0, so
> `hasFeatureAccess(…, 'profile')` is true for every authenticated user:
> `gated('profile', …)` blocks nobody on plan grounds and is effectively
> `AuthGuard` alone. I asserted a severity from the route table without reading
> the feature map it depends on.

What it actually was: `/profile/me` bypassed **`AuthGuard`**, so a logged-out
visitor reached the own-profile view — which then fails its own API call, since
`GET /profiles/me` and `PUT /profiles/me` both carry `Depends(get_current_user)`
(`api/profiles.py:136,145`). A broken page for an anonymous visitor; no data
leak, and nothing a logged-in user did not already have.

The fix stands on its own merits — the own-profile view has no business being
reachable from an unguarded route, and this exact pattern *is* a live bypass for
any feature whose required plan is not `free`. `/profile/:id` was the only route
in all 86 sharing a component with a guarded route, so it is also the only place
the pattern occurs.

**The generalisation is the real finding, and it is F4-01b below.**

**Fix:** a self-referencing id redirects to `/profile`, which is guarded, before
rendering or fetching. Public viewing of *other* traders is unchanged and tested
so it stays that way. Only the guarded route can now produce `isOwn`.

### F4-01b — the plan gate existed on neither side (HIGH) — **FIXED**

Chasing the corrected F4-01 to its real form. `SubscriptionGate` in React and
`PLAN_FEATURES` in TypeScript are UI affordances, not authorization: anyone with
devtools can set the store's plan, and nothing stops a direct call carrying a
valid free-tier token.

**This was already found once**, for the no-code Strategy Builder, and the note
left behind states it exactly:

> "every route in `api/nocode.py` depended on `get_current_user` alone, which
>  checks *authentication* and never *plan*. So the advertised gate existed on
>  neither side."
>                          — `tests/unit/test_nocode_plan_gate.py`

`api/nocode.py` was fixed. **The same shape survived in every other paid
feature.** Of ~60 API routers, five enforced a plan; the rest depended on
`get_current_user` alone:

| route | feature | advertised | was |
|---|---|---|---|
| `/api/copy-trading/*` | copy-trading | professional | auth only |
| `/api/indicators` (user CRUD) | indicators | professional | auth only |
| `/api/accounts/sub-accounts/*` | sub-accounts | elite | auth only |
| `/api/accounts/teams/*` | teams | enterprise | auth only |
| `/api/alerts/*` | alerts | starter | auth only |

A free-tier account reached every one. Each is now `Depends(require_plan(…))` at
the advertised tier — 8 failing-first cases, all confirmed reaching a 200 before
the fix. Admin and superadmin bypass by design, pinned by a test, because adding
a gate without that would have silently broken support workflows.

**Deliberately not gated**, so the omissions read as decisions rather than
oversights:

- `/api/indicators/builtin` — standard indicator definitions, no user data and
  nothing proprietary. Pinned open so the gate cannot creep onto it.
- `/api/billing/*` — `wallet` is advertised as starter, but billing is also
  **how a user upgrades**. Gating it behind a paid plan locks a free user out of
  the page that sells them the plan. That surface needs a narrower gate than
  "the billing router"; recorded, not guessed at.
- `/api/risk/*` — `prop-firm` (professional) and `risk-calculator` (starter)
  share one prefix across two routers, so it needs per-endpoint work rather than
  a router-level dependency. Not done here.

**Blast radius, measured rather than hoped for:** 21 failures, all in
`test_custom_indicators_api.py`, whose fixture gave its caller no subscription.
Those tests exercise CRUD and 404 handling, not the gate, so the fixture now
grants the plan the feature is advertised at — the same shape as the nocode
test's. Backend after: **15,147 passed, 0 failed.**

### F4-02 — `AuthGuard`'s `requiredRole` is dead (LOW)

`AuthGuard` accepts a `requiredRole` prop and implements a full `ROLE_RANK`
comparison with its own Access Denied screen. **No route uses it** — every role
check in `App.tsx` goes through `AdminGuard` or `SuperAdminGuard`, which have
their own, differently-worded denial screens. The only callers are seven cases
in `components.test.tsx`, so the tests keep alive a code path production never
takes.

Not fixed: deleting it is a judgement call about which of the two role
mechanisms should survive, and the redundant one is the *safe* kind of dead
code. Recorded for F10 (dead code and duplication), where that call belongs.

---

## Round 4 — Slice F3: state, freshness, and the store

Scope: all 33 state fields in `src/store/index.ts` — what writes each, what reads
it, what happens when it goes stale — then the React Query layer separately: 83
`useQuery` call sites and their `staleTime` / `refetchInterval`.

### F3-01 — the HTTP fallback is switched off by the failure it exists for (HIGH)

`hooks/useOrchestratorData.ts`, three queries, with the comment above the first
saying exactly what it is for:

```ts
// ── Account (every 10s — fallback when WS is down) ──────────────────────
refetchInterval: wsStatus === 'connected' ? false : 10_000,   // :277  account
refetchInterval: wsStatus === 'connected' ? false : 10_000,   // :321  positions
refetchInterval: wsStatus === 'connected' ? false : 15_000,   // :354  signals
```

The fallback is right. Its **trigger** is not. "WS is down" is measured as
`wsStatus !== 'connected'`, and S9-01 is precisely that `wsStatus` *stays*
`'connected'` while the server's broadcast loop stalls: socket open, nothing
arriving, nothing erroring, nothing reconnecting.

So in the one failure this fallback was written for, it never fires. Account,
positions and signals freeze at their last pushed value, and the polling that
would have refreshed them is suppressed by the flag that failed to notice. A
stalled feed is not a state the app rides out — it is permanent until something
else forces a refetch.

**It compounds with F1-02 in an unhappy way.** The notices added there now tell
the user their balances and P&L may have moved, while the app holds a working
HTTP path it has switched off. It could have been self-healing and was instead
merely honest.

**Fix:** key all three to `selectFeedLive` — connected **and** not stale **and**
something has arrived. A stall now repairs itself within one interval, and the
recovery is automatic rather than requiring a reload.

The remaining 80 query sites were read and are sane: nothing money-bearing
serves cached data indefinitely, the longest `staleTime` on a trading surface is
2 minutes (`performance/equity-curve`), and the only hour-long one is
`GeopoliticalRiskPage`, which is appropriate for its data.

### F3-02 — `lastHeartbeat` is a decoy (LOW)

Of the store's 33 state fields, **every one has at least one reader except
`lastHeartbeat`, which has zero.** The playbook named it as the known example
and it was still there.

Being unused is not the problem. Being unused *under that name* is: it is the
field a reader reaches for when they want "is the feed alive?", it is kept
faithfully up to date, and the codebase had to grow `lastDataAt` and `feedStale`
to answer that question because nothing consumed this one. A heartbeat says the
transport is open — which is the exact thing S9-01 showed keeps being true while
no data arrives.

**Fix:** kept (dropping it would make `useWebSocket` discard a message type
silently) and documented at the declaration as *not* the freshness signal, with
a pointer to `lastDataAt` / `feedStale` / `selectFeedLive`. Pinned by a test, so
the field cannot quietly go back to looking like the answer.

---

## Round 4 — Slice F5: numbers, money, and precision

Scope: every place a price, size, P&L, percentage or currency value is formatted
or computed in the frontend, cross-checked against what the backend sends for
the same field.

### F5-01 — two instrument tables, already drifted (MEDIUM)

`api/trading.py::_SYMBOL_CATALOGUE` is the server's instrument spec and is
served to clients at `GET /api/trading/symbols`. The risk calculator does not
read it: `RiskCalculator.tsx` carries its own hardcoded `SYMBOLS` map of pip and
contract sizes, and sizes positions from that.

They disagreed on **ETH/USD** — `0.01` on the client against `0.1` on the
server.

**Stated precisely rather than alarmingly.** The sizing formula is

```
stopPips       = stopDist / pipSize
pipValuePerLot = pipSize * contractSize
lotSize        = riskAmount / (stopPips * pipValuePerLot)
```

`pipSize` cancels, so **lot size and max loss were correct** — verified by
running `calculate()` at both values. What was wrong were the two figures shown
beside them: the pip count and the pip value, both out by 10×. On a $100 ETH
stop the tool reported *"10,000 pips"*.

`contractSize` does **not** cancel, so a divergence there would move the
suggested position itself. All six symbols agree on it.

Gold specifically was checked against the backend audit's S3 precedent and is
consistent on both sides: pip `0.01`, contract 100 oz — not FX's `0.0001` at
100,000.

**Fix:** value corrected, and a test in `tests/unit/` now parses the `SYMBOLS`
map out of the `.tsx` and compares every entry against `_SYMBOL_CATALOGUE`. The
copy may exist; it may not disagree. **Follow-up:** the calculator should read
`/api/trading/symbols` and stop keeping a copy. That is a real change to a
position-sizing tool — it needs a load state, and F1-01 established this page
must not silently substitute a fallback — so it is recorded rather than done in
passing.

### F5-02 — a side comparison that decided the sign of a number (HIGH)

`lib/utils.ts::positionSide` already owns this rule, and its docstring says why
it exists:

> The API is inconsistent: some endpoints return `side`, others `direction`, and
> either may be absent — which is why `pos.direction.toLowerCase()` crashed
> PnLDashboard (audit #37/#40) while **three other call sites each wrote their
> own slightly different comparison**. `null` means "not reported", which
> callers must render as unknown rather than defaulting to short.

`PositionsTable.tsx:351` was a fourth:

```ts
const pnlPct =
  ((pos.current_price - pos.entry_price) / pos.entry_price) * 100 *
  (pos.side === 'long' ? 1 : -1);
```

Every case the helper handles, this got wrong:

| reported as | rendered |
|---|---|
| `side: 'buy'` | **−10% on a profitable long** |
| `side: 'LONG'` | same, on case alone |
| `direction: 'long'`, no `side` | same |
| nothing at all | −1, i.e. **defaults to short** — the one thing the docstring forbids |

And the badge one line below *does* call `positionSide(pos)`, so the same row
displayed **LONG** beside a percentage signed as if it were short. Two elements
disagreeing about one position, on screen, simultaneously.

`Portfolio.tsx:550` had the same shape in the allocation breakdown — a `'buy'`
position counted as short exposure.

**Fix:** both use `positionSide`, and an unreported direction now renders `—`
rather than a guessed sign. Four further hand-rolled copies
(`t.side === 'long' || t.side === 'buy'`, in `Portfolio`, `Trading`, `Trade`,
`Performance`) are consolidated onto the helper — same rule, written five times,
each missing the `direction` fallback and case normalisation.

**Deliberately left alone:** the ~40 other `side ===` / `direction ===`
comparisons the grep turned up drive arrows, badge colours and filter buttons.
Miscoding a colour is cosmetic and belongs to F7; miscoding a sign is a wrong
number. Only the latter was in scope here.

### Checked and clean

`fmtPnl`, `fmtPrice`, `fmtPct`, `fmtPctRaw`, `fmtCompact`, `fmtSpread` — all
null-safe, all sign-correct. `fmtPnl`'s negative branch was the audit-#… defect
where every loss rendered positive; it is fixed and stays fixed.

---

## Round 4 — Slice F6: loading, empty, and error states, triaged by consequence

The playbook asks for triage, not a sweep: the views where an empty or missing
state can be misread as a *meaningful* value, and for each, whether "couldn't
load" is distinguishable from "nothing here".

| surface | verdict |
|---|---|
| positions | **fixed earlier** — S9-03/S10-01, three-way empty/unknown/broker-starting |
| account equity | **fixed earlier** — F1-02, `LiveFeedNotice` + `DataAge` |
| alerts | **fixed earlier** — F1-02, Live Triggers tab distinguishes the two |
| risk limits | **clean** (below) |
| open orders | **n/a** — no standing-order view exists; orders are market-only through `OrderEntryForm` |
| KYC status | **F6-01, fixed** |

### F6-01 — a failed load manufactured a compliance state (MEDIUM)

`KYCPage.tsx:149`

```ts
} catch {
  setError('Failed to load KYC status. Please refresh.');
  setKycState({ status: 'not_started', submitted_at: null,
                reviewed_at: null, rejection_reason: null, documents: [] });
}
```

The error handler does not fall through to a default — it **constructs** a
status object and asserts `not_started`. The page then rendered the full "Not
Started" card, put the step indicator on step 1, and offered the document upload
form, all describing a state nobody checked.

An error banner sits above it, so the failure is technically visible. But the
page is making a specific contradicting claim at the same time:

- a user whose documents are `under_review` is told they have not begun, and the
  obvious response to that is to upload everything again;
- an `approved` user is told to start verifying;
- a `rejected` user is not shown the rejection reason they came for.

**Fix:** an `unknown` status that is explicitly *not* a server state — the
client's answer when it could not ask. It renders an amber "Status unavailable"
card, takes the step indicator to step 0, hides the upload form (`canSubmit`
already excluded it), and says in words: *"Nothing has changed — refresh to try
again, and don't re-submit documents until this loads."*

### Checked and clean

- **`RiskDashboard`** — the surface most likely to have this defect, and it does
  not. `marginLevel` falls back to `0`, but every displayed figure is guarded by
  `{account ? … : '—'}`, and `marginLevelIsSafe(0)` returns true by design (no
  position, no margin risk) rather than painting a false liquidation warning.
- Everything else is cosmetic, as the playbook predicted. Said and moved on.

---

## Round 4 — Slice F11: do the tests assert anything?

Run last, because it says how much to trust the rest.

### The measurement, including two wrong answers on the way

Three automated classifiers, three numbers, and the first two were wrong:

1. *"58 tests where every assertion is a mount/defined check."* Wrong — it
   counted `expect(found).toBeTruthy()` after a **text-matching** `find()`,
   which is a genuine output assertion.
2. *"132 tests with no content-dependent assertion."* Wrong the other way — it
   flagged `store.test.ts`, `trading_logic.test.ts` and
   `risk_calculator_math.test.ts`, which are pure logic tests that correctly
   render nothing. `expect(store.positions).toHaveLength(2)` is a strong
   assertion.
3. *"67 of 624 rendering tests assert nothing about output."* Still wrong — it
   flagged tests whose assertions live in a helper (`pctOf(container)`) and
   `renderHook` tests that assert on hook state.

**The categories do not separate mechanically.** Reported as a fact about the
method rather than dressed up as a result, because a number nobody checked is
exactly what this slice exists to find.

### What the suite actually looks like

- **0 tests with zero assertions**, out of 1,264.
- **No weak test on a money path or a guard.** The mount-only tests are on
  admin, affiliate, marketplace, social and tools pages.
- The `renders without crashing` family (~25) is honestly named and earns its
  keep: F1-04 found `Dashboard` and `Performance` both crashing on a partial
  payload, which is exactly what those catch.
- **13 test files `vi.mock('../hooks/useApi')` wholesale**, so the real request
  layer, its interceptors and every failure branch are unexercised there. This
  is why the F1 harness stubs the axios *adapter* instead — already recorded in
  its header, and the reason F1 found what the page tests could not.

### F11-01 — one test verified hollow, by mutation (LOW) — **FIXED**

`pages_register_profile_watchlist.test.tsx :: renders profile username after
load`

```ts
const el = document.querySelector('h1');
expect(el).toBeTruthy();
```

Its name promises the username; it asserts an `<h1>` exists. **Verified by
deleting `{profile.display_name || profile.username}` from `Profile.tsx` — the
test still passed.** It would also pass on an error page that happens to have a
heading.

Now asserts the heading's text, and the same mutation fails.

Its three siblings (Win Rate / Avg P&L / Sharpe stat cards) were checked and are
fine — they match on `innerHTML` for their label text.

**Verdict on the suite: better than the slice assumed.** The backend precedent —
nine tests found asserting defective behaviour — has a frontend counterpart of
nine, all already found and corrected in earlier slices of this round (the badge
required to read "Live" on a dead socket; the account-summary test passing on a
page subtitle; the positions panel required to claim "no open positions" while
disconnected). This slice adds one more.

---

## Round 4 — Slices F7–F10

### F7-01 — colour is not the sole carrier of meaning — **clean, now pinned**

The one F7 question that is a safety duty rather than taste: *"Are red/green the
only carriers of long/short and P&L sign?"* **No**, on both counts:

- `SideBadge` renders `▲ Long` / `▼ Short` — glyph and word, colour as
  reinforcement.
- `fmtPnl` renders `+$50.00` / `-$50.00`. Its own docstring records the version
  where it did not: *"the negative branch previously produced an empty sign
  while still taking Math.abs, so every loss rendered as a positive number …
  Colour usually carried the meaning; the number did not."* Under deuteranopia
  that page had **no loss indicator at all**.

Pinned by tests that read the text with styling ignored, which is what a
red-green colour-blind trader effectively does with these two hues.

**Not claimed:** whether the most decision-relevant number is the most
prominent, and whether the hierarchy scans in under a second. The S10 scope note
already recorded that reading components cannot settle that, and it still
cannot. It needs a real screen.

Two other F7 questions are answered by work already done this round: *"can a
user tell at a glance whether the system is live, degraded, or halted?"* — three
distinct states now (F1-02/F10-01) where there were two, and one kill-switch
source (S10-02) where there were three. *"Does the UI imply more certainty than
the data supports?"* — that is the whole of F1-02, S9-02 and F6-01.

### F8-01 — the confirmation guarding every destructive action was not focus-trapped (MEDIUM)

`ConfirmDialog` declares `role="dialog"` and `aria-modal="true"`, and its
backdrop blocks the **mouse**. The keyboard walked straight out:

| behaviour | before |
|---|---|
| focus moves into the dialog | ✅ (`autoFocus` on the confirm button) |
| Tab stays inside | ❌ escaped on the second Tab |
| Shift+Tab stays inside | ❌ |
| Escape closes | ✅ |
| focus returns to the trigger | ❌ fell to `<body>` |

The markup said the page behind was inert and the behaviour said otherwise; a
screen-reader user got the worse of the two.

**Filed under the money path, not general a11y,** because with focus back on the
submit button behind the dialog, Enter re-submits the form. That is the
mechanism behind **F2-02** — that entry fixed the consequence (a promise that
never settled); this fixes the cause.

Fixed: Tab/Shift+Tab cycle within the dialog, focus is restored to the element
that opened it, Escape unchanged. The whole close-all path is now operable by
keyboard alone, and there is a test that says so.

### F9-01 — measured render cost of a tick (LOW)

`setPrice` gives `prices` and `priceHistory` a new object identity on every tick,
which is correct — it is how zustand notifies. The cost lands on **ten call
sites that subscribe to the whole map** rather than to one symbol, so they
re-render on every tick of every instrument including ones they never display.
`selectPrice(symbol)` already exists for exactly this.

Measured, not asserted: a component on `selectPrice` records **zero** re-renders
across three ticks in other instruments; the whole-map subscriber re-renders for
all of them.

**Converted one** (`AIChart`) and stopped. In `OrderEntryForm` and
`RiskCalculator` the symbol is declared *after* the subscription, so the change
means reordering hooks — restructuring a money path for a gain jsdom cannot
measure. The remaining sites are recorded with the number rather than churned;
`LivePriceTicker` and `Watchlist` genuinely need the whole map.

### F9-02 — nothing grows without bound — **clean**

Five arrays append and all five are capped: price history at `MAX_TICK_HISTORY`,
signals at `MAX_SIGNALS`, news at 50, triggered alerts at 100, recent paths at 6.
Everything else replaces wholesale. Pinned with 1,000-tick and 500-item loops.

### F10-01 — the "LIVE" badge exists three times; F1-02 fixed one (HIGH)

The S13-01 prediction landing exactly. Three near-duplicate trading pages each
carry their own liveness badge:

| surface | was |
|---|---|
| `Dashboard` `WsBadge` | **fixed in F1-02** |
| `Trade.tsx:219` status dot | `wsStatus === 'connected'` → green, pulsing, "live" |
| `Trading.tsx:177` TopBar pill | `wsStatus === 'connected'` → "● LIVE" |

Two of the three went on saying LIVE, in green, through a stalled feed — the
defect F1-02 exists to fix — because a fix applied to one half of a duplicate
does not reach the other when nobody knows the other exists.

`Trade`'s broker-status banner had the same shape one step further on: it was
suppressed by `wsStatus === 'connected'`, hiding the warning during the outage
it describes.

All three now read `selectFeedLive` and distinguish **live / stalled /
disconnected**. A test greps every one of them and fails on a fourth copy.

### F10-02 — two role mechanisms, and a rank table defined twice (LOW)

`AuthGuard` accepts a `requiredRole` prop, carries **its own byte-identical copy
of `ROLE_RANK`**, and re-implements inline the comparison that
`lib/subscription.ts::hasRole` already provides — a second role mechanism
alongside `AdminGuard`/`SuperAdminGuard`, with different denial copy. **No route
uses it** (all 11 privileged routes go through the helpers); its only callers are
seven tests.

F4-02 deferred the decision here. Resolved by consolidation rather than deletion:
`AuthGuard` now imports `hasRole`, so the capability and its tests survive and
the duplicate constant is gone. The two mechanisms agreed today — S13-01's record
in this codebase is that duplicated pairs do not stay agreeing.

### F10 route/page reconciliation

Already done in F4 and clean: 70 lazy route components, every one resolving to a
real file, no top-level page without a route. Not repeated.

### A contract test caught this work

`type_accuracy_contract.test.ts` rejected the focus trap's `items[0]!` /
`items[items.length - 1]!` — the repo's own `noUncheckedIndexedAccess` guard
(audit #38) firing on new code, correctly. Rewritten as bind-then-check.

---

## Round 4 — closing the deferred follow-ups

### F4-01b (continued) — `/api/risk` per-endpoint gates — **FIXED**

Deferred from the first pass because `/api/risk` is shared by two routers at two
different tiers, so it needed per-endpoint work rather than one router-level
dependency. Done:

| route | feature | tier |
|---|---|---|
| `/api/risk/prop-firm/*` (7 routes) | prop-firm | professional |
| `/api/risk/calculator/*` (3 routes) | risk-calculator | starter |

**`/api/risk/live-price/{symbol}` is deliberately left at authentication-only,
and pinned open.** It returns a mid price, not the paid feature: the sizing
arithmetic runs in the browser, and what a subscription buys is the saved
calculation history beside it. Gating a quote would protect nothing and would
break the entry auto-fill for anyone who reaches the page another way.

Backend after: **15,172 passed, 0 failed** — no blast radius this time; the
prop-firm and calculator tests already gave their callers subscriptions.

That leaves one recorded and undone: the **`/api/billing` wallet gate**, which
still needs to be narrower than "the billing router" because billing is how a
user upgrades. Gating it would lock a free user out of the page that sells them
the plan.

### S10-04 — **CORRECTED, and fixed**

> The original entry read: *"31 of 204 `.tsx` files reference any `aria-`
> attribute (~15%). `OrderEntryForm.tsx` has exactly one … The order inputs
> (symbol, side, quantity, SL, TP) carry no `aria-label`."*
>
> **The second sentence measured the wrong thing.** The inputs *are* labelled,
> and labelled the better way: `Field` renders `<label htmlFor={id}>` against
> `<input id={id}>`, which is native association and is preferred over
> `aria-label`. `getByLabelText(/quantity/i)` finds them. Counting `aria-`
> attributes cannot see correct native labelling, so a file doing it right
> scores zero — which is how a metric produced a finding that was not there.
> Same failure as the F1-04 mis-attribution and the F4-01 severity claim: a
> number asserted without checking what it was counting.

What was genuinely missing is on the two controls that are **not** native
inputs:

```tsx
<button type="button" onClick={() => setSide(s)}
        className={cn(..., side === s && s === 'buy' ? '…green…' : '…')}>
```

Buy/Sell and Market/Limit/Stop are buttons whose selected state lived **only in
a CSS class**. Tabbing through announced *"Buy, button. Sell, button."* with
nothing to say which was active — on the control that decides the direction of
an order, beside a submit button that commits capital in that direction. It is
also F7-01 applied to a control rather than a readout: green/red was the sole
visual carrier of the selection.

**Fix:** `aria-pressed` on both toggle sets, and `role="group"` with a name on
each. Together with F8-01's focus trap, the order path — choose side, choose
type, fill the fields, submit, confirm, cancel — is now operable and
comprehensible by keyboard alone.

**Still open from S10-04:** there is no keyboard shortcut affordance for order
entry or the kill switch. That is a feature decision, not a defect, and is left
to the product rather than invented here.

---

## Round 4 — PR #265 automated review, and the last two deferrals

### G-01 — startup reconciliation could not read live OANDA positions (P1) — **FIXED**

Raised by automated review on PR #265 as **thirteen threads restating one
finding**. Verified against the code before acting on it; both halves are real.

**1. The method does not exist.** `startup_factories.py:1151` wires
`AsyncOANDAConnector`, an alias for `brokers.oanda.OANDABroker` (`oanda.py:632`).
That class implements `get_open_positions()` and **not** the `get_positions()`
that `PositionManager._reconcile_with_broker` awaits. The call raises
`AttributeError`, the handler catches it, logs *"restored state is UNVERIFIED"*,
and returns the persisted Redis snapshot untouched.

The sync `OANDAConnector` further down the same module *does* have
`get_positions()`, returning objects — which is presumably why nobody noticed.
It is neither the class production wires nor async.

**2. Even reachable, the records are the wrong shape.**
`get_open_positions()` returns `list[dict]`; the reconciler does
`getattr(p, "symbol", None)`. A dict has no `.symbol`, so `live_by_symbol` stays
empty — and an empty broker view is the most dangerous possible misreading here,
because **every persisted position is then dropped as closed** and no
broker-only position is adopted. It looks exactly like "the account is flat".

*One correction to the report:* `get_open_positions()` already maps `instrument`
onto a `symbol` key, so the key name is not the problem — attribute-vs-mapping
access is.

Reconciliation exists to catch exactly what a restart creates: positions closed,
opened or resized while the process was down. Inert, live OANDA exposure sits
outside position limits, stop monitoring, risk tracking and the dashboard, while
the operator is told the restore succeeded.

Same family as **S1-01** (a second `AccountInfo`), **S13-03** (BUY submitted as
SELL) and **S12-04** (never-awaited broker coroutines): the money path and the
broker disagreeing about a contract, failing upward.

**Fix, both sides.** A normalised async `OANDABroker.get_positions()` returning
`brokers.base.Position`, with the decisions stated rather than implied —
quantity is a magnitude and direction lives in `side` (OANDA reports shorts
negative; leaking that sign gives downstream sizing a negative position); a
hedged account's two legs are **netted**, because the reconciler's model is one
position per symbol; a net-flat hedge is not a position; a malformed record is
skipped rather than fatal. And `_broker_field()` in the reconciler, which reads
mappings as well as objects — kept even though the OANDA side now returns proper
objects, because the next adapter to return dicts should degrade to a wrong
number, not to a silent flat account.

### F4-01b (final) — the narrow billing gate — **FIXED**

The last deferral. Most of `/api/billing` stays open **on purpose**: billing is
how a user upgrades, so gating `/plans`, `/subscription`, `/stripe/*`,
`/payments/*` or `/payment-methods` would lock a free account out of the page
that sells them the plan. Those are now **pinned open** by a test.

Two groups inside it are not that:

| routes | tier | was |
|---|---|---|
| `/api/billing/elite/*` (5) | elite | auth only |
| `/api/billing/balance`, `/transactions` | starter | auth only |

`/elite/*` is the sharper find and was not in the original scope: dedicated
account-manager contact, support tickets and custom-development requests, each
labelled **"(Elite)"** in its own route summary, each reachable by any
authenticated free-tier account.

### S10-04 (rest) — keyboard shortcuts — **FIXED**

Recorded as *"a feature decision, not a defect, left to the product"*. Doing it
made the gap sharper than the entry: auditing where the kill switch can actually
be thrown, **every trigger lives in Settings or the superadmin panel**. A trader
watching a position run against them had to navigate away from the trading
screen to halt trading — at the moment navigating away is the worst thing to ask.

`hooks/useHotkeys.ts`, written around what a shortcut layer on this surface must
**refuse** to do:

- **never fire while typing** — a bare `b` for "buy" that also fired inside the
  quantity field would arm a direction on a keystroke meant as text;
- **never fire while a dialog is open** — a confirmation is a question, and the
  answer must come from the dialog;
- **never bypass a confirmation** — a shortcut is an accelerator for reaching a
  control, not a way around the guard on it.

Bound: `b` / `s` for order side (with the letter shown on the button, since a
shortcut nobody knows about is not an affordance), and `Shift+K` to halt
trading — a modifier deliberately, because "halt all trading" must not be one
stray keystroke away. It opens the same confirmation a button would, states in
words that **open positions are not closed**, and reports a timeout through
`describeSubmitFailure` (F2-01) rather than claiming a halt failed when it may
have succeeded.

---

## Round 4 — the three remaining follow-ups, closed

### F5-01 (follow-up) — the calculator reads the server's catalogue — **FIXED**

`useInstrumentSpecs` fetches `GET /api/trading/symbols`, so the server — the
same catalogue the backtester, order path and symbol search use — is now the
authority for pip and contract sizes.

The rule that shaped the design: **F1-01 forbids a silent fallback on this
page.** That finding was this very component swallowing a failed price fetch and
quietly substituting a store price, *while that price is the input to position
sizing*. Replacing one silent substitution with another would be the same defect
in a different coat. So the built-in table survives as an offline default — it
is legitimate, because `test_instrument_specs_match_the_frontend.py` fails CI if
it ever disagrees with the server — and the page **says** when it is on it.

`quoteIsUsd` is derived rather than fetched: the catalogue has no such field and
it is a property of the symbol.

### S12-04e/f/g — the un-awaited tail, triaged — **FIXED**

The backlog carried "~333 un-awaited broker call sites still need triage". **That
number was a raw grep and it was wrong.** An AST pass that filters properly:

| filter | count |
|---|---|
| method-name match anywhere | 266 |
| …with a broker-shaped receiver, inside `async def` | 37 |
| …excluding `wait_for` / `gather` / `create_task` / `iscoroutine` guards | 6 |
| …**real, after reading every one** | **4** |

**S12-04e (CRITICAL) — the kill switch could not close a position.**
`CircuitBreaker._execute_kill_switch` called `self.broker.get_positions()`
without awaiting. Against an async broker that is a coroutine: truthy, so the
"nothing to close" exit never fired; `cancel_all_orders()` built a second
coroutine and dropped it; `for position in positions` raised
`TypeError: 'coroutine' object is not iterable` straight into the retry loop's
`except`. Three attempts, nothing closed, then a final `len()` on another
coroutine inside the escalation branch. **The most important control in the
product could not close anything**, and the operator was told it had partially
failed — of a mechanism that never ran. Reproduced exactly (three logged
`'coroutine' object is not iterable`) before the fix.

**S12-04f** — `trader_full.OrderGateway.place_market_order` never awaited
`place_order`, so the order never reached the broker; `cancel_order` was
annotated `-> bool` and returned a coroutine, so every caller's `if success:`
was true whatever the broker did.

**S12-04g** — `health_check_service._check_broker` ran `broker.get_account_info()`
inside an executor, so against an async broker the future resolved to a
coroutine, the balance read came back `None`, and the check reported the broker
**ok** having read nothing.

All four now use `execution/broker_call.call_broker`, which awaits a coroutine
function and runs a sync one in an executor — correct against either shape.

**Verified NOT bugs and left alone rather than churned:**
`execution/fix_router.py:483` runs `broker.place_order` in an executor with the
comment "PaperTradingBroker.place_order is synchronous" — checked, it is `def`,
not `async def`, so the comment is accurate and the executor right.
`brain/brain.py` binds then awaits through `asyncio.wait_for` at all seven sites.

### S1-12 — the Kelly backtest comparison — **DONE**

`scripts/kelly_sizing_comparison.py`, output in `docs/KELLY_SIZING_COMPARISON.txt`.
It drives the real `RiskManager._kelly` over real XAUUSD bars, sizing each signal
under both rules. Stated as what it is: a **sizing comparison, not a strategy
backtest** — win probabilities are swept rather than predicted, so nothing
depends on trusting the model.

The change: `b = max(0.5, confidence * 3.0)` → `b = |target−entry| / |entry−stop|`.
With the risk manager's own ATR stops (2.0×ATR target / 1.0×ATR stop) the real
`b` is 2.0, so break-even is **33.3%**.

Sizing: the new rule is **smaller in 12 of 25** confidence×probability cells and
larger in 8 — it is not uniformly more conservative, it is *correctly* keyed. The
old rule sized up to **+44% larger** at high confidence, which is exactly the
defect: confidence was standing in for odds.

The simulation is where it matters, swept **around** break-even with costs:

| true p | rule | median end | p(lose 50%) | median max DD |
|---|---|---|---|---|
| 30.3% | old | 86,457 | 0% | 20.4% |
| 30.3% | **new** | **100,000** | 0% | **0.0%** |
| 33.3% *(break-even)* | old | 86,467 | 4% | 36.7% |
| 33.3% | **new** | **100,000** | **0%** | **0.0%** |
| 38.3% *(real edge)* | old | 312,086 | 1% | 43.8% |
| 38.3% | new | 286,141 | **0%** | **32.4%** |

**The new rule refuses to trade below the real break-even.** The old one could
not: its break-even moved with model confidence rather than with the stops, so a
confident model kept it sizing into a negative-expectancy trade. With a genuine
edge the new rule gives up ~8% of median return for ~11 points less drawdown.

*A correction on the way there:* the first version of the simulation swept
p = 0.45–0.55 against b = 2.0 — an edge of +0.35 per unit risked — and printed
median endings of 10²⁴ with zero ruin for both rules. That is not a result, it
is a range where the question cannot be asked. Rewritten to sweep at and below
break-even, with costs.

---

## T — Account isolation (multi-tenancy)

**Reported:** users see trades they did not place; a superadmin's trade is
visible to, and moves the numbers of, everyone else.

**Confirmed, and the cause is architectural rather than a missing filter.**
`app_state.broker` is one process-wide engine with one account. Every logged-in
user — trader, admin and superadmin alike — trades against it and reads from it.
Two comments say so outright:

* `api/trading.py` — *"app_state.broker is a single process-wide paper engine
  shared by every logged-in user, so its get_positions() returns EVERYONE's
  positions."*
* `api/ws_live.py` — *"single-account deployment … BEFORE enabling multi-tenant
  accounts this MUST become `send_to_user(owner_id, …)` so one user cannot
  receive another's balance/PnL."*

Isolation was deferred while the product was single-account, and the filters
added since landed unevenly.

### T-01 — the broker nets every user into one position per symbol  (CRITICAL)

`PaperTradingBroker.positions` is a `dict[str, Position]` keyed by **symbol**,
and `_update_position` merges into the existing entry with the comment *"For
simplicity, assume same side"*. Two users buying XAUUSD do not get two
positions. Demonstrated directly:

    two orders, 1.0 lot and 3.0 lots
    → 1 position, id="XAUUSD", qty=4.0, entry=weighted average

The position id **is the symbol**. So capital is commingled in a single object,
`close_position("XAUUSD")` closes it for both users, and there is nothing to
attribute a share of it to either.

This is why read-filtering cannot fix it, and why filtering alone is not even
safe: with one netted position per symbol, at most one user can own the matching
row, so gating positions before fixing the broker makes the *other* user's own
position disappear from their screen.

`PaperTradingBroker.__init__` already accepts `user_id`. It is assigned to
`self._user_id` and never read — the seam exists, unused.

### T-02 — read surfaces that were never scoped  (HIGH)

Gated already: `GET /trading/trades` (filters on `user.sub`),
`GET /trading/positions` (owned-id filter, fails closed).

Not gated — every authenticated user sees the shared book:

| Surface | State |
|---|---|
| `GET /trading/orders` | no filter at all |
| `GET /trading/balance`, `/account` | the one global account's balance/equity/margin/PnL |
| `api/portfolio.py` (3 sites) | no user filter anywhere in the file |
| `api/ws_live.py` account broadcaster | `broadcast("account", …)` to every subscriber |
| `push_position_update` / `push_position_close` | fall back to `broadcast` when `user_id` is None |
| `_broadcast_fill_ws` | fills go to the whole `trades` channel |
| `api/broker.py:359`, `api/graphql_schema.py:469` | unscoped |

### T-03 — the operator bypass  (MEDIUM)

`_owned_position_ids` returned `None` — meaning *apply no filter* — for `admin`
and `superadmin`. That is the reported behaviour. Decision taken: operators are
ordinary traders on the ordinary endpoints; whole-book access moves to explicit
`/api/superadmin/*` routes that name the account and are audited.

### T-04 — the orders table has no writer  (MEDIUM)

Nothing in the codebase inserts into `database.models.Order`. Orders exist only
on the broker, so there are no rows to attribute even once the model can see
`user_id`. Per-user order history needs the write path to persist them.

### Resolved

**T-01 — fixed.** `core/account_registry.py` gives every user their own
`PaperTradingBroker`, keyed off the `user_id` the constructor already accepted,
with an explicit per-user Redis namespace so state survives a restart without
colliding. Two users trading XAUUSD now hold two positions; closing one leaves
the other open; one user's P&L no longer moves another's balance.

A live venue (`oanda`, `mt5`, `ibkr`, …) is **one real account** and cannot be
split in-process. The registry reports `isolated=False` with a reason rather
than presenting two users with "their own" view of one account, and each caller
decides what that means: `/trading/orders` shows nothing, `api/portfolio.py`
reports no data, the WebSocket account push is skipped.

**T-02 — fixed.** Every surface now resolves the caller's account:

| Surface | Now |
|---|---|
| `GET /trading/orders` | the caller's own account; nothing when not isolated |
| `/trading/balance`, `/account`, `/positions`, close, close-all, hedge | `_user_broker_call(user.sub, …)` |
| `api/portfolio.py` (3 sites) | `_user_broker(user)`; `None` when not isolated |
| WS account broadcaster | one message per connected user via `send_to_user` |
| `push_position_update` / `push_position_close` | owner required; dropped and logged without one |
| fill notifications | `send_to_user`, not `broadcast("trades", …)` |
| `api/broker.py` `/status` | connectivity stays deployment-wide; balance and positions are the caller's |
| `api/graphql_schema.py` | `_live_account(user_id)` via a non-creating `peek` |

`tests/unit/test_no_shared_broker_in_handlers.py` is an AST guard: a new handler
that calls `_broker_call` or `app_state.broker.<method>()` fails the build. The
gaps appeared because the filter was applied by hand, endpoint by endpoint —
this stops that recurring.

**T-03 — fixed.** `_owned_position_ids` no longer returns the "no filter"
sentinel for any role, and the IDOR carve-out that let operators close another
user's position is gone. Whole-book access moved to
`/api/superadmin/trading/*`: read-only, superadmin-only, the account named in
the request, every call written to the hash-chained audit log.

### Still open

**T-04 — orders are not persisted.** Nothing writes `database.models.Order`, so
per-user order *history* depends on the broker's in-memory list plus the trades
table. The ownership column and `core.tenancy.owned_order_ids` are ready for
when a writer exists.

**Per-user risk limits.** `RiskManager` and the kill switch still act
process-wide. That is right for the kill switch — it is an emergency stop for
the venue — and wrong for per-user drawdown limits, which should be evaluated
per account.

**The autonomous engine's account.** `app_state.broker` remains the engine's own
book. Whether the bot should trade each user's account is a product decision,
not a defect, and is deliberately unchanged here.

### Notes from the fix

### Done so far

* `core/tenancy.py` — one place that resolves ownership, failing closed to an
  empty book whenever ownership cannot be established.
* `Order.user_id` declared on the model. The **column** has existed since
  migration `o1p2q3r4s5t6`; the model never declared it, so the ORM had no
  attribute to filter on. Schema was right, model was blind. No new migration
  was needed — the one drafted for it was deleted once that was established.

---

## Round 5 — pre-launch security checklist (30-item external checklist)

Scope: a general-purpose pre-launch checklist for web apps, applied to this
repo — secrets, database access, auth/authorization, rate limiting and abuse,
input/output handling, payments, AI features, and deployment/ops. 915 route
decorators across 70 routers in `api/`, plus the frontend and mobile bundles,
the nginx config, and the middleware stack.

**Most of the checklist was already satisfied**, and several items were
satisfied *better* than the checklist asks. Recorded rather than tested, because
re-verifying them is a grep and inventing tests for them adds no signal:

| checklist item | state in this repo |
|---|---|
| Secrets in frontend | none. `frontend/src` and `mobile-app/src` reference only `VITE_API_URL`, `VITE_WS_URL`, `VITE_NUCLEAR_WS_URL`, `import.meta.env.DEV` |
| Secrets in git history | clean. Only `.env.example` / `.env.production.example` were ever committed; `k8s/k8s-secrets.yaml` is a `<BASE64_...>` placeholder template |
| Session tokens | already stronger than the checklist. Access token is held in Zustand **memory only** — `AuthGuard.tsx` and `useApi.ts` both say so explicitly — with refresh over an http-only cookie. Nothing auth-shaped in `localStorage` |
| Password hashing | bcrypt cost 12 with a BLAKE2b pre-hash to dodge bcrypt's 72-byte truncation |
| SQL injection | parameterized throughout. The two dynamic `UPDATE`s (`api/accounts.py`, `api/journal.py`) allowlist column names and bind every value |
| XSS | no `dangerouslySetInnerHTML` or `innerHTML` in any production component |
| File uploads | type allowlist, size cap, and filename sanitisation to a safe alphabet; avatar names are derived from a hash of the user id, so no user-controlled path component |
| Webhook signatures | verified on every provider — Stripe via `construct_event`, Sumsub/Onfido/Paystack via `hmac.compare_digest` |
| Server-side pricing | plans resolve server-side; the checkout amount is additionally bounded by `MAX_CHECKOUT_AMOUNT_USD` |
| Error messages | `api/error_details.py::safe_error()` returns an exception *class name* plus a log reference, keeping DSNs, paths and SQL fragments off the wire |
| Security headers | CSP, HSTS, X-Frame-Options, X-Content-Type-Options, Referrer-Policy, Permissions-Policy, at both nginx and `core/middleware.py` |
| Debug/docs in prod | `docs_url`, `redoc_url` and `openapi_url` are all `None` when `APP_ENV=production`; Vite emits no source maps |
| Prometheus `/metrics` | already restricted to private ranges at nginx |
| Prompt injection | user input stays in a `user`-role message and never interpolates into the system prompt; chat sessions are keyed per authenticated user so histories cannot bleed |

Row-level security (checklist items 3–4) does not map here: this is SQLAlchemy
against Postgres/SQLite with authorization in the application layer, not a
Supabase-style client-direct database with an anon key on the frontend. The
equivalent control is per-record ownership, which `core/tenancy.py` centralises
(Round 3 T-03) and which is enforced in the handlers.

### P-01 — operator telemetry and model internals were anonymous (HIGH) — FIXED

22 GET endpoints across five routers answered with no token:

```
/api/observability/{traces,metrics,alerts,services,latency-histogram}
/api/mlops/{health,drift,shadow,retrain/history,models/{id}/metrics}
/api/tracing/{config,spans}
/api/ml/{drift-report,drift/status,sharpe-circuit-breaker/status,model-drift,
         ab-tests,training-jobs,explain/{model},feature-importance/{model}}
/api/transparency/audit-log
```

**Round 4 Slice F4 looked directly at this and found it clean** — and was right
about what it checked. F4 audited `App.tsx`: `/observability` and `/ml-ops` both
go through `adminOnly()`, all four guards render a spinner while the role is
unresolved, and tests pin the composition. The restriction was real. It was just
**only in the SPA**. Skipping the React app and requesting the JSON directly
returned it. This is the exact shape the checklist warns about — a rule that
lives in the frontend is not an access control — and a frontend-only audit
cannot see it, because from inside `App.tsx` everything looks correctly gated.

Two of the 22 are worth naming:

- **`/api/ml/explain/{model}` returned SHAP feature importances.** On a trading
  system that is not diagnostics, it is the edge. The same data was *already*
  gated at `require_role("trader")` on the sibling `/api/ml/feature-importances`
  — so the codebase already held the opinion that this is not public, and one
  route disagreed with the other.
- **`/api/transparency/audit-log` returned config changes and risk events.** Its
  neighbours in that router (`/decisions`, `/explain/{trade}`, `/stats`,
  `/statement`) are public *on purpose* — the router exists so a client or
  auditor can verify behaviour without an account. So the fix is one route, not
  the router, and the test suite pins **both** halves: `/audit-log` must 401 and
  the other three must still 200. Over-correcting here would have removed a
  product feature in the name of security.

Guards were placed to match what the code already implied: router-level on
`observability`, `ml_ops` and `tracing` (wholly operator-facing, so it also
covers routes added later), route-level on `ml` and `transparency` (mixed-access
routers, where a router-level guard would wrongly raise the floor for the
user-facing routes). Levels follow the existing convention — `admin` for the ops
views the superadmin pages consume, `trader` for the two model-explanation
routes, matching their already-gated sibling. `trader` is the default role at
registration, so no ordinary user lost access.

`tests/unit/test_internal_telemetry_requires_auth.py` asserts on the resolved
dependency graph, not source text, so moving a guard between route and router
keeps it passing while removing one fails.

### P-02 — an unauthenticated route burned a third-party quota (MEDIUM) — FIXED

`GET /api/macro/refresh` invalidated the 1-hour FRED cache (`feed._cache_ts =
None`) and re-fetched on every call, with no token — then pushed the result into
`MacroStore`, which live inference reads. Two problems in one: a free lever for
exhausting the FRED API quota, and an anonymous write into a path that feeds the
model. The sibling `/api/macro/features` already required a token; `/refresh`
was shaped like a health check and got treated as one. Now requires auth.

### P-03 — rate limiting was configured but never applied (HIGH) — FIXED

`rate_limiting_configuration.GLOBAL_DEFAULT_RATE` documents itself as *"applied
to every endpoint that has no explicit decorator"*, and
`api/platform.py::setup_rate_limiting()` builds a Redis-backed slowapi `Limiter`
and stores it on `app.state`. **Neither was consumed.** There is not one
`@limiter.limit()` decorator in the repository, so the Limiter's only effect was
installing a 429 handler for an exception nothing raised.

What made this invisible is that the important endpoints *were* limited — each
by a different mechanism it brought itself:

| surface | mechanism |
|---|---|
| login / register / password reset | `auth/router.py` per-IP limiter + nginx `limit_req zone=auth` |
| withdrawals | `rate_limit_dependency(WITHDRAWAL_RATE)` |
| WS handshakes | `rate_limiting/websocket_limiter.py` |
| **everything else** | **nothing** |

So spot-checking rate limiting found a working limiter every time, while ML
inference, backtest submission and every LLM-backed route were unmetered.

`core/middleware.DefaultRateLimitMiddleware` now supplies the documented
default, registered in `register_all()`. Keyed per bearer token when present,
falling back to client IP — keying on IP alone would put an office behind one
NAT address into a single bucket, which is a denial of service against paying
users rather than protection from anyone. The key is a SHA-256 prefix, not the
raw JWT, because it is stored in Redis. Health probes and provider webhooks are
exempt: a 429 to a Kubernetes probe reads as an unhealthy pod, and providers
retry webhooks in bursts after an outage where the HMAC signature is the real
control. The limiter fails **open** on internal error — a broken counter must
not be able to take the API down — and logs when it does.

### P-04 — no per-user cap on LLM spend (HIGH) — FIXED

`api/chat.py`'s own docstring reasoned about this risk — *"without auth, any bot
that discovers the URL can run up OpenAI charges indefinitely"* — and solved it
with authentication. But auth answers **who**, not **how much**. A single
registered account could loop `/api/brain/complete` (a raw prompt passthrough)
and drain the provider budget overnight. P-03's rate limiter does not close it
either: rate bounds burst, and a caller staying just under the limit still runs
unbounded over a day. The two controls measure different things and neither
substitutes for the other.

`core/ai_quota.py` adds the cumulative dimension — a rolling 24-hour per-user
count over the same Redis window — applied to the routes that actually spend:
`/api/chat`, `/api/brain/{chat,complete,embed,analyze}`, `/api/voice/{tts,stt}`.
Operators are exempt by default (`AI_QUOTA_EXEMPT_ROLES`); they run the system
and are not the abuse case. `AI_DAILY_LIMIT_PER_USER=0` is treated as a
misconfigured env var rather than a silent shutdown of every AI feature, since
the deliberate version has its own switch.

### P-05 — nginx served dotfiles (LOW, defence in depth) — FIXED

No `location` block denied hidden paths. Nothing is exposed today, because every
unmatched path is proxied to FastAPI, which serves the SPA from its own static
mount and has no route that would return a dotfile. It stops being true the
moment anyone adds a `root`/`alias` block to serve assets from disk — at which
point `/.git/config` and `/.env` become live URLs and the repository, history
included, is readable.

The rule is `location ~ /\.(?!well-known)`, and **the exclusion is
load-bearing**: a blanket `/.` deny also swallows
`/.well-known/acme-challenge/`, which is how certbot proves domain ownership —
so the "hardening" would have silently broken TLS renewal and taken the site
down about 60 days later. Verified by rendering the template and running nginx
against it: dotfiles 404, ACME challenge 200.

### Operator actions — not code, cannot be fixed in-repo

Four checklist items are account/console settings. They are listed here so the
pre-launch pass has a record of what code cannot close:

- **Billing caps and usage alerts** on Anthropic/OpenAI, the FRED key, Stripe,
  the email provider, and the hosting account. P-03 and P-04 bound abuse from
  outside and from users; neither bounds a bug in our own retry logic. A
  provider-side cap is the only control that does.
- **Automatic backups**, with a restore actually rehearsed.
- **Two-factor** on hosting, database, domain registrar, email, GitHub, and the
  payment provider. Note that this repo ships `api/two_factor.py` for *end
  users*, which is a different thing from 2FA on the operator accounts.
- **Bot protection** on public signup. `auth/router.py` rate-limits registration
  per IP, which slows a single-source flood but not a distributed one. Worth a
  CAPTCHA before open signup, verified server-side.

---

## Round 5b — pre-launch checklist, second 20-item list

The first list (Round 5, P-01…P-05) covered secrets, access control, injection,
payments and deployment. This second list covers the auth *flow* — session
lifecycle, reset links, enumeration, lockout — plus request limits and
surface reduction.

**Already satisfied**, verified rather than assumed:

| item | state |
|---|---|
| HSTS, CSRF tokens, CORS lockdown, secure cookie flags | done, and covered in Round 5 (both nginx and `core/middleware.py`) |
| Expire reset links | `password_reset_expires = now + 1 h`, checked on redemption, **and** the token is stored as a hash (`_hash_token`) rather than in the clear, with a signed outer envelope carrying its own expiry |
| Rate limit password resets | `_check_ip_rate_limit` on `/forgot-password` and `/reset-password`, plus nginx `limit_req zone=auth` |
| Lock accounts after failed logins | 5 failures → 15-minute lockout, Redis-backed with a DB fallback so it holds across pods |
| Reset sessions on password change | correct on the `/reset-password` path — `AuthService.reset_password` calls `logout_all`. **Not** on the authenticated change-password path; see Q-01 |
| Disable directory listing | no `autoindex` in nginx (off by default) and `StaticFiles` does not index |
| Remove default admin routes | no adminer/phpMyAdmin/pgAdmin exposed; the `/admin` string in `core/page_routes.py` is an SPA client-side route in the history-fallback list, and the admin *API* is `require_role`-gated |
| Sanitize before storing, whitelist upload types, verify payment webhooks, set prices server-side, block prompt injection, cap AI usage | covered in Round 5 (items 13–22 there) |
| Log security events | login attempts are recorded (`_record`), plus the hash-chained audit log and Sentry with PII scrubbing |

### Q-01 — change-password could not work, three ways (HIGH) — FIXED

`POST /api/auth/change-password` in `api/settings_extended.py`. Each defect
below is independently fatal:

1. **It used a column that does not exist.** It read and wrote
   `user.password_hash`; the column on `database.user_models.User` is
   `hashed_password`. `hasattr(User, "password_hash")` is `False`, so the first
   comparison raised `AttributeError`, the route's broad `except Exception`
   caught it, and **every request returned 500** — "Password change failed.
   Please try again." Nobody could change their password, ever. That is not
   merely a broken feature: a user who believes their credential is compromised
   had no way to rotate it, and the error told them to retry.

2. **It used a second hashing scheme.** It hashed with bare
   `bcrypt.hashpw(password)`. Registration and login go through
   `auth.jwt.hash_password`/`verify_password`, which BLAKE2b pre-hash the input
   before bcrypt to avoid bcrypt's 72-byte truncation. So with the column fixed
   but the scheme left alone, `checkpw` would reject every correct current
   password, and any hash it did write would not verify at login — **locking the
   user out of their own account**. `auth/service.py` already carries a comment
   about this exact class of failure happening once before, when that module
   used `pbkdf2_sha256` while `auth.jwt` used bcrypt. The test suite now pins
   that a raw-bcrypt hash does *not* verify through `auth.jwt`, so the
   incompatibility is a checked property rather than a claim.

3. **It did not revoke sessions.** Changing a password is what someone does when
   they think another party has access; leaving existing sessions valid means
   that party keeps it. `logout_all` now runs after a successful change, *after*
   the commit and outside the DB block — a revocation failure must not turn a
   completed change into a 500 that tells the user it did not happen, so it is
   logged at ERROR and reported as `sessions_revoked: false` instead.

Also fixed in passing: `mgr.session()` was entered via `ctx.__enter__()` and
never exited, leaking a DB session on every call; and the route accepted a
`current_password` guess with no rate limit, so it is now throttled like login.

Two other modules — `mobile/api.py` and `mobile/api_v2.py` — also hash with raw
bcrypt. Left alone deliberately: they are self-consistent (both register and
verify with the same raw scheme), so they are not broken today. They *are* the
same latent trap if they ever share a user store with the main auth service.
Recorded rather than changed, because unifying them touches the mobile login
path and deserves its own change.

### Q-02 — two endpoints enumerated the user table (MEDIUM) — FIXED

`/forgot-password` always returned 200 and its docstring said "Always returns
200 to prevent email enumeration". The status code was uniform; **the body was
not.** `request_password_reset` returns `"Password reset email sent"` for a
known address and `"If that email is registered, a reset link has been sent."`
for an unknown one, and the route returned that string verbatim. Two different
responses is all an attacker needs, so the uniform status bought nothing. The
defence was real, sincerely intended, and undone one layer up.

`/resend-verification` was blunter: `raise HTTPException(400, detail=msg)` where
`msg` is `"Email not found"`. A plain existence oracle.

Both now return a single fixed string held in a module constant
(`_ENUMERATION_SAFE_RESET_MESSAGE`, `_ENUMERATION_SAFE_VERIFY_MESSAGE`) so the
"same response on every path" property lives in one place and is testable. The
real reason is logged server-side. `"Email already verified"` is folded into the
uniform response too — that an address is registered *and* verified is more than
an unauthenticated caller should learn.

The fix is at the HTTP boundary, not in the service: `AuthService` still returns
distinct messages to its own callers, and a test pins that, so the next person
does not "fix" it by making the service lie internally.

### Q-03 — request bodies were capped only by nginx (MEDIUM) — FIXED

`client_max_body_size 10M` was set in nginx and nowhere else. `docker-compose`
publishes the app on `8000:8000`, so a caller reaching the host directly
bypassed it entirely and could post a body of any size for the worker to buffer.
This is not a hypothetical: `setup_compression()` in `core/middleware.py`
already documents that exact bypass as its own reason for compressing in-app
rather than trusting nginx's `gzip`. The same argument applies to body size and
had not been carried across.

`BodySizeLimitMiddleware` now enforces `MAX_REQUEST_BODY_BYTES` (default 10 MiB,
matching nginx). It checks `Content-Length` on the cheap path and **also meters
the stream when the header is absent** — otherwise `Transfer-Encoding: chunked`
skips the check, which is the usual way a header-only guard is defeated. Upload
routes that legitimately carry the largest bodies and already enforce their own
per-route caps are exempt. Registered outside the rate limiter so an oversized
body is refused on its header without first spending a token from the caller's
rate-limit budget.

### Operator actions from this list

- **Restrict database permissions.** `docker-compose` and `DEPLOYMENT.md` use a
  single role with `GRANT ALL PRIVILEGES`. The app needs DML on its own schema,
  not ownership of the database; a separate migration role and a least-privilege
  runtime role is the shape to aim for. Not changed here — it is deployment
  configuration, and getting it wrong locks the app out of its own tables.
- **Bot protection on signup** (carried over from Round 5, still open).

---

## Round 6 — backend-fundamentals audit (Top 50 backend concepts)

Scope: the 50-concept backend handbook applied to this repo. Most concepts were
already implemented, several better than the reference: connection pooling
(pool_size 20 / max_overflow 40 / pool_pre_ping / pool_recycle 3600), pagination
(97 limit/offset/cursor parameters across the API), API versioning (`/api/v1`
aliases), API gateway, circuit breaker, health checks (liveness / readiness /
startup / deep), observability (metrics + logs + traces), distributed lock (the
kill-switch Redis latch), CDN, cache-aside, and webhook signature verification.

Four real findings.

### R-01 — a retried order was a second order (HIGH) — FIXED

Migration `b2c3d4e5f6a7` adds `UNIQUE(client_order_id)` and states its scope in
its own docstring: *"Prevents duplicate order submission on broker retry (network
timeout **between API and broker**)"*. That is one hop. Nothing covered
client → API: a lost response, a load-balancer timeout or a double-tap arrived as
a genuinely new request, the engine minted a fresh `client_order_id`, the UNIQUE
constraint had nothing to collide with, and a **second real position opened**.

The per-user order rate limit does not close this — two distinct requests inside
the window are both legitimate to a limiter, which bounds frequency, not
duplication. And the other half of the pair already existed: this codebase
retries upstream calls with exponential backoff, as does any mobile client on a
timeout. Concepts #10 and #41 are a pair, and only #41 was present.

`POST /api/trading/orders` now honours an `Idempotency-Key` header
(`core/idempotency.py`): first use executes and stores; a replay returns the
original response with `Idempotency-Replayed: true`; an in-flight replay gets
409; the same key with a different body gets 422. The key is claimed before any
side effect, and released on failure so a risk-gate rejection stays retryable.
Optional rather than mandatory, because making it required is a breaking API
change that belongs to whoever owns the mobile release.

### R-02 — sizing recommended trades the executor rejects (HIGH) — FIXED

`RiskManager.calculate_position_size` caps by *percentage of equity*;
`validation.OrderValidator` rejects on an *absolute lot count* (`max_qty`,
default 10.0). Two different units, never reconciled. At $1M equity the sizing
engine returned **10.2564 lots**, reported `approved`, and the executor answered
`"Quantity 10.2564 exceeds maximum 10.0"` — a correctly sized trade that simply
did not execute, with nothing in the sizing result explaining why.

Sizing now clamps to `_executable_lot_ceiling()`, which reads
`OrderValidatorConfig.max_qty` (overridable via `ORDER_MAX_QTY`) so the two
limits cannot drift apart again. Clamping down rather than raising the
validator's ceiling: the ceiling is a real safety limit, and reducing a size
cannot create risk that was not already approved.

**This was invisible until the environment was fixed.** `test_risk_manager.py`
could not even be collected without `xgboost` installed, so the assertion that
caught it had never run in a web session.

### R-03 — one Redis blip disabled distributed rate limiting for good (HIGH) — FIXED

`rate_limiting/advanced.py` had two switches that only turned off:

1. **Permanent disable.** Any exception set `_redis_available = False`, and
   `_get_redis()` then returned `None` for the rest of the process's life — the
   cached client was non-None, so the reconnect branch was unreachable. A Redis
   failover of a few seconds therefore turned a fleet-wide rate limit into
   per-worker counting **indefinitely**, with no further log line saying so.
   This matters more now that P-03 made this limiter the default for every
   endpoint rather than a handful.
2. **Loop rebinding.** The async client was cached once and `redis.asyncio` binds
   its pool to the loop it was created on, so any second event loop in the
   process raised "Event loop is closed" on every call — silently falling back.

Failures now set a cooldown (`RATE_LIMIT_REDIS_RETRY_SECONDS`, default 30s) and
re-probe; the client is rebuilt when the running loop changes.

### R-04 — two of my own tests were not hermetic (MEDIUM) — FIXED

`core.idempotency.reset_for_testing()` cleared only the in-process dict, and the
rate-limiter fixture did the same. Both stores prefer Redis when one is
reachable, so state survived between tests and between whole pytest runs (24 h
and window TTLs). The tests passed on a machine with no Redis and failed on one
with it — backwards, since the Redis path is the one production uses. Both now
purge their own key prefix (never `FLUSHDB`, which would take the kill-switch
latch with it).

### Environment, not defects

The ~360 failures and ~82 collection errors a fresh web session showed were
**all** environmental. Every missing module is declared in `requirements-ci.txt`;
the container simply never installed it. `.claude/hooks/session-start.sh` now
provisions a session (venv + requirements-ci.txt + npm + Redis + PYTHONPATH +
a per-session JWT secret), so a web session sees what CI sees.

A venv is used deliberately: this image's pip, setuptools and wheel are all
Debian-packaged without RECORD files, so `pip install --upgrade pip` fails
outright and `ta`, `crcmod` and `ed25519-blake2b` fail to build against the
system setuptools.

### R-05 — the kill switch could halt one pod and tell no one (HIGH) — FIXED

`KillSwitch._write_redis_latch()` writes the key every other pod polls to halt
itself. Both of its failure paths were effectively invisible:

* `_get_latch_redis()` swallows every exception and returns `None`. The write sat
  behind `if r is not None:` with no `else`, so an unreachable Redis produced
  **no write and no log line at all** — the quietest possible failure for the
  loudest possible control.
* The exception path logged at `warning` and called itself *"(non-fatal)"*. It is
  not non-fatal. This pod has stopped trading; the others have not been told and
  keep trading against a book the operator believes is flat.

That outcome already has a name here: **S2-01, "Split-brain kill switch",
CRITICAL**. It was reached then by having two `KillSwitch` instances. An
unwritable latch reaches the same destination by a different route, and the code
described it as routine.

Now: `CRITICAL` on both paths, naming the consequence ("other pods have NOT been
told and may still be trading"), plus a `latch_broadcast_ok` field on `status()`
— `None` before any attempt, `False` when the halt was local-only. A log line
alone is too easy to miss for this control; an operator checking kill-switch
status has to be able to see that the broadcast failed.

Deliberately still does **not** raise: the local halt has already succeeded, and
throwing would unwind the one stop that did work.

### Suite status after provisioning

With `.claude/hooks/session-start.sh` provisioning the environment, the full unit
suite is **15,991 passed, 0 failed, 0 errors** (49 skipped, 11 deselected). The
~364 failures and ~82 collection errors a bare container showed were
environmental in their entirety — and, as R-02 proved, they were also hiding a
real money-path defect.
