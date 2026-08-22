# HOPEFX — How This Platform Actually Works

A ground-truth architecture document, written from the source rather than the
docs. Every claim here was verified by reading code at a cited `file:line`, and
most were confirmed by executing it. Where the design intent and the running
behaviour differ, both are stated.

Companion document: `CODE_READING_FINDINGS.md` (144 findings, F1–F143).

---

## 1. The single most important fact

**There is not one system here. There are four, and they share a repository
rather than an architecture.**

Four entry points each assemble a *different* pipeline from the same parts bin.
They are not layers of one design; they are alternative designs, built at
different times, all still present and all still runnable.

| Entry point | Started by | What it assembles |
|---|---|---|
| `app.py` | `Dockerfile:91` (production CMD) | FastAPI + routers. No trading loop. |
| `execution/paper_runner.py` | `run.py --mode paper` | REST poll → bars → ML → event bus → FIXRouter |
| `hopefx_engine.py` | `run.py --mode live` | NuclearStreamer → Brain → Risk → OMS → ExecutionEngine |
| `connect_to_life.py` | run directly | The above **plus** the autonomous self-healer |

Plus `celery_app.py` for scheduled work. A statement like "HOPEFX does X" is
almost always false unless it names which of these it means.

---

## 2. What each entry point actually starts

### 2.1 `app.py` — the production container

`Dockerfile:91` → `scripts/preflight.sh && python app.py`.

Assembles the FastAPI application: `core/router_registry.py` mounts every router,
`core/startup_factories.py` builds components into `ComponentRegistry`.

**It does not trade.** There is no trading loop in `app.py`. It serves the API,
the WebSocket broadcaster, and the dashboard. Trading happens only if
`ENGINE_AUTOSTART=true` **and** `LIVE_TRADING_ENABLED=true` when
`TRADING_MODE=live` (`startup_factories.py:2977-2982`) — both default false, which
is correct (F118).

It **does** mount `/api/security/heal/*` unconditionally
(`router_registry.py:525-528`) while starting none of the healer's loops — so in
the container the self-healer is HTTP-reachable but dormant (F130).

### 2.2 `paper_runner.py` — **the mode that is running today**

CLAUDE.md: *"paper trading active"*. `run.py:372-380` sends that to `PaperRunner`.

```
OandaPricePoll (REST, 1 poll per _TICK_INTERVAL_S)     paper_runner.py:96
  → OHLCVBuffer   (accumulates ticks into bars)                    :186
    → InferenceSignalAdapter  (ML inference, fires on bar close)   :304
      → bus.publish(CH_ORDER, {symbol, direction, units, …})   :731-744
        → FIXRouter._route()                          fix_router.py:320
          → PaperTradingBroker
```

**This path has no risk layer** (F142). `_route` contains exactly one gate —
`if self._halted` (the kill switch). No `RiskManager.assess()`, no pre-trade
gate, no position sizing, no stop-loss or take-profit anywhere in the payload,
no `ExecutionEngine`. Order size is `PAPER_ORDER_UNITS`, default **1000 units,
fixed**, independent of equity, volatility, confidence or open exposure
(`paper_runner.py:87`, used at `:657`).

### 2.3 `hopefx_engine.py` — live mode

```
NuclearStreamer (WebSocket ticks)          data_feed/nuclear_streamer.py
  → HOPEFXBrain            (strategy signals)
  → NuclearStrategyAgent   (parallel signal source)      hopefx_engine.py:627
  → RiskManager / risk_orchestrator
  → OMS + PositionTracker
  → ExecutionEngine → BrokerFactory → OANDA / MT5 / …
```

This is the path nearly every finding in the audit describes. Two things about
it are worth stating plainly:

* `hopefx_engine.py:398` injects `StrategyManager()` **without**
  `preload_defaults`, so the brain receives **zero strategies** (F88). Signals
  therefore come from `NuclearStrategyAgent` — very likely the only source.
* Its kill-switch check fails closed and is deliberately duplicated outside
  `ExecutionEngine`, with the reasoning written out (`:645-660`). That is correct.

### 2.4 `connect_to_life.py` — everything, plus autonomous patching

Everything above, and `security/self_healer.py`'s seven background loops
(`self_healer.py:733-754`) — including `_patch_loop`, which drains a Redis list
and **writes Python into the source tree**, and `_claude_fix_loop`, which asks an
LLM for patches. See §7.

---

## 3. The intended design, and where it diverged

### 3.1 What `--dry-run` claims

`run.py --dry-run` exists to tell an operator what is about to start. For **live**
mode it names: EventBus, FaultGuard, NewsCalendarFeed, MarketIngest,
StrategyEngine, Gatekeeper, FIXRouter.

`hopefx_engine.py` contains **zero references to all six** (F143). Every class
exists in the repo — so this is a stale description of a superseded architecture,
not invention — but five of the six are genuinely not in the live path. Only
`EventBus` survives, indirectly via `execution/engine.py`.

The **paper** description in the same function is accurate. The live one is not.

### 3.2 `Gatekeeper` — the clearest example of the pattern

`risk/gatekeeper.py` implements prop-firm risk checks. `risk/manager.py`
references it twice — both in **docstrings**:

```
:221  "Produced by RiskManager.assess() and consumed by Gatekeeper."
:666  "Consumed by Gatekeeper and execution pipeline."
```

No import. No call. The documented consumer does not consume.

### 3.3 The recurring shape

This is the single most common defect class in the codebase, and it is worth
naming because it explains most of the audit:

> **A control is designed correctly, implemented correctly, and never invoked.**

| Control | Implemented at | Why it never runs |
|---|---|---|
| Regime detection | `strategies/regime_router.py` | `route()` has zero callers → regime is permanently `"unknown"` → position scalar stuck at **0.5** (F94) |
| SL/TP monitor | `execution/sl_tp_monitor.py` | reads `pos.position_id`; the class has `.id` (F45) |
| `verify_balance_after` | `invariants/payments.py:84` | wallet write path never calls it (F138) |
| Patch signing | `security/self_healer.py:318-326` | `HEAL_PATCH_SIGNING_KEY` set in no config file (F130) |
| Kalman filter, IsolationForest | `data_layer/quality/engine.py` | computed every tick, read by nothing (F90) |
| `Gatekeeper` | `risk/gatekeeper.py` | referenced only in docstrings (F143) |
| Lot-ceiling anti-drift import | `risk/manager.py:88` | imports a name that does not exist (F73) |

The second most common shape: **a gate that fails open in exactly the condition
it exists for** — F84 (safety check skipped when the data layer failed to start),
F85 (jump filter dead on the feeds slower than the staleness threshold),
F139 (kill-switch propagation removed by the manifest set that also disables
invariant enforcement).

---

## 4. Data flow — what a price actually is

Six gold feeds, polled at different rates (`data_layer/feeds/gold/manager.py:52-59`):

```
GOLDAPI 5s │ METALS_DEV 10s │ YAHOO 5s │ METALS_API 60s │ METALPRICEAPI 60s │ COMMODITY_API 60s
        ↓
DataQualityEngine.validate_tick()      data_layer/quality/engine.py
        ↓
cross_source_consensus()  → weighted mid + confidence
        ↓
MarketDataOrchestrator.get_latest_tick()   ← Redis cache in front
```

Three things about this are not what they appear:

1. **Consensus weight is `confidence / latency / max(spread, 0.01)`** (`:505-511`).
   The inverse-spread term dominates: a feed quoting a tight spread takes **96%**
   of the normalised weight, then evicts honest feeds as outliers against a mean
   it defines (F82, recomputed).
2. **The jump filter never runs on three of six feeds.** `STALE_THRESHOLD_S=30`
   but those feeds poll every 60s, so `is_stale()` is always true when the check
   runs, and the check is gated behind not-stale. Proven: a **+203%** price jump
   is rejected at a 5s cadence and accepted at 60s (F85).
3. **The tick "stream" is pull-driven.** `_on_tick` — which drives the
   microstructure engine, the tick cache, lineage, subscribers and the WebSocket
   broadcast — has exactly one call site, on the Redis **cache-miss** branch of
   `get_latest_tick` (`orchestrator.py:767`). Nothing pushes from the feed side.
   The 16 microstructure ML features therefore sample *read volume*, not price
   changes (F87).

---

## 5. The ML path

`ml/inference_engine.py` gates on staleness and drift; `live_trading_gate`
requires OOS accuracy ≥ 0.60 and the committed model reports 0.5734.

The bigger issue is upstream: **48.2% of model features are zero-filled live**
(F24) — train/serve skew, where the model was fitted on features that the live
path does not supply.

`is_safe_to_trade()` (`data_layer/orchestrator.py:1076`) checks blackout, tick
presence, confidence ≥ 0.30 and feed liveness. `ml/inference_engine.py:1403`
consumes it correctly and **fails closed**. `execution/engine.py:687` consumes it
as `if orchestrator._started and not is_safe_to_trade()` — which disables the
whole check whenever the data layer failed to start, a failure
`core/startup_helpers.py:95-116` deliberately swallows as non-fatal (F84, proven).

---

## 6. Risk — where it exists and where it does not

| Path | Risk layer present? |
|---|---|
| `paper_runner` → FIXRouter (**running today**) | **No.** Kill switch only (F142) |
| `hopefx_engine` → ExecutionEngine | Yes — RiskManager, orchestrator, OMS, pre-trade gate |
| Nuclear agent → `_on_nuclear_signal` | Yes, plus a fail-closed kill-switch check |

Within the live path, sizing is genuinely well-bounded — I computed the range
rather than assuming: across the entire confidence/Kelly space a nuclear signal
produces **0.40%–0.625% of equity** against a 2% cap, because the `+0.5` term
floors Kelly's contribution to a 1.25× swing (F128). The `_MIN_BACKTEST_TRADES=3`
approval bar is weak evidence, but the design prevents weak evidence from
becoming a large position.

**Stop-losses are the exception.** `brokers/base.py:554-560` states that bracket
SL/TP are "logged and ignored" at entry; the local monitor that would compensate
is dead (F45); all three mechanisms fail on the live path (F59).

---

## 7. Kill switch and self-healing

The kill switch is well designed: five independent layers (`kill_switch.py:205-216`)
— in-memory, flag file, env var, Redis latch, K8s ConfigMap watcher — explicitly
so that Redis being down cannot silence it.

For a cluster deployed from **`deployments/k8s/`**, three of the five are gone
(F139): no RBAC file and no `serviceAccountName`, so ConfigMap `get`/`patch` is
denied; the flag file resolves into the image layer rather than the
`trading_state` volume, so it does not survive a pod replacement; Redis is
optional by preflight design. The **`k8s/`** set is correct by contrast, with a
Role scoped to `resourceNames` and verbs limited to `get`/`patch`.

The self-healer writes Python into the running tree. Its trust control — an HMAC
over the Redis patch queue, explicitly built "so that a compromised Redis
instance cannot inject arbitrary code" — returns `True` when the key is unset,
and `HEAL_PATCH_SIGNING_KEY` appears in **no configuration file anywhere in the
repository** (F130). At the default `aggressiveness="medium"` the LLM patch path
is off and the Redis patch path is on.

---

## 8. The frontend

Two web UIs (`frontend/` 96,803 LOC and `dashboard/src` 15,334 LOC) plus a React
Native app (`mobile-app/` 10,940 LOC). Only `frontend/` has been audited.

`frontend/` is **the best-engineered layer in the repository** (F124): typecheck
clean across 95k LOC under `strict` + `noUncheckedIndexedAccess`; no fabricated
data; money formatters degrade to `—` rather than `0`; the JWT is held in memory
and never persisted.

Its stale-feed watchdog is fully wired end to end and defends against precisely
the backend stall documented in F87 — with the failure named in its own comment:
*"`lastHeartbeat` was written to the store on every heartbeat and read nowhere
outside test files."*

Its one real gap: no runtime validation library and 142 unchecked `as` casts on
API responses. Contained by per-panel error boundaries, so the exposure is
well-typed *wrong* data rather than crashes — a server-side problem.

---

## 9. Eight vocabularies for one concept

"Market regime" is defined independently eight times, with no shared type and no
conversion between any pair:

```
strategies/regime_router.py      7 REGIME_* strings
ml/regime.py                     MarketRegime enum
brain/brain.py                   MarketRegime enum
analysis/market_analysis.py      MarketRegime enum
nocode/ml_nodes.py               MarketRegime enum
backtesting/enhanced_engine.py   MarketRegime enum
api/trading.py:3812-3826         inline trending_up / trending_down / ranging
nuclear/regime_classifier.py     9 REGIME_* strings
```

`_REGIME_SIZE_MAP.get(name.upper(), 0.5)` fails open to 0.5 on any unrecognised
name — which is what hides the mismatch between all eight, and why F94's dead
detector never surfaced as an error.

---

## 10. Honest coverage

| | LOC | Share |
|---|---:|---:|
| Deep-audited (read + executed) | 64,991 | 9% |
| Partially audited | 317,871 | 45% |
| Not audited | 330,815 | 46% |

1,911 source files: 894 application Python, 588 test Python, 429 TS/TSX.
Excluding `tests/`, roughly 78% of ~492k application LOC has been touched;
only 9% deeply.

**Largest unaudited areas:** `dashboard/` (15,799 — a second UI),
`mobile-app/` (10,940), `analysis/` (10,424), `research/` (9,325 — produces the
model features), `data/` (6,259), then ~40k across twenty smaller packages.
`auth/` (2,395) is the highest-risk gap for its size.
