# HOPEFX — Deep Code Analysis (A → Z, traced, not described)

A structured, evidence-grounded walk through the real wiring of the platform —
every claim traced to specific files/lines by reading the code, not the docs.
Written so an engineer can verify each point and a non-engineer can follow the
shape. Companion to `docs/PLATFORM_AUDIT.md` (verdicts) — this is the *mechanism*.

_Analysis date: 2026-06-27. Method: direct source tracing of the money path,
intelligence layer, safety architecture, data layer, execution, and UI._

---

## 0. Executive summary (the honest one-paragraph)

HOPEFX is a **large, genuinely integrated** XAUUSD trading platform: a five-phase
decision pipeline takes a tick → signal → ML probability → **risk gate** →
execution → post-trade, with **multiple hard blocks** at the risk stage and a
**single enforced choke-point** (`enforce_order_authorization`) at all three
broker entry points. The intelligence is **real but modest** (a horizon-5
ensemble, ~57% OOS accuracy, significant but below the 0.68 production bar). The
safety system is **real and now partially active** (order-authorization +
pre-trade enforced; reconciliation/ledger staged). Data is **real and
multi-sourced with failover**; brokers are **real multi-broker connectors**; the
default mode is **paper trading with live trading gated off**. It is an advanced,
well-wired **research / paper-trading platform**, not a proven live money-maker.

---

## 1. Architecture map (the layers, top to bottom)

```
Frontend (React 19 SPA, 69 pages, 629 wired API calls, real role gates)
        │  HTTPS / WS
API layer (FastAPI, 74 routers, 933 routes, JWT + 4 roles)   ← api/, core/router_registry.py
        │
Decision Engine (5-phase pipeline)                           ← core/decision/HOPEFXDecisionEngine.py
   1 Signal → 2 ML → 3 Risk Gate → 4 Execution → 5 Post-trade
        │            │              │              │
   strategies/    ml/           risk/          execution/  → brokers/ (OANDA/MT5/IBKR/Alpaca/Binance/paper)
        │            │              │
        └──── invariants/ (337 pure predicates) via invariants/enforcement.py façade ────┘
        │
Data layer (multi-source feeds + circuit breakers)           ← data_layer/orchestrator.py
Persistence (SQLAlchemy, graceful in-memory fallback)        ← api/db_store.py
```

---

## 2. The money path — traced end to end (the most important section)

### 2.1 Decision pipeline — `core/decision/HOPEFXDecisionEngine.py` (748 lines)
`process_tick()` → `_pipeline(ctx)` runs five sequential phases, each able to stop
the trade and record *why* (`DecisionPhase` / `DecisionOutcome` enums):

| Phase | Method | Can block? |
|---|---|---|
| 1 Signal generation | `_phase1_signal` | yes (no signal → stop) |
| 2 ML enrichment | `_phase2_ml` (async) | adjusts probability |
| 3 **Risk gate** | `_phase3_risk` (async) | **yes — the gate** |
| 4 Execution | `_phase4_execute` (async) | yes (broker refusal) |
| 5 Post-trade | `_phase5_post_trade` | logging/audit |

Concurrency is guarded (a lock keeps "risk state is never read mid-update" unless
`allow_concurrent=True`) — i.e. sizing reads a consistent risk snapshot.

### 2.2 Phase 3 risk gate — multiple hard blocks (`_phase3_risk`)
Traced sequence, each path returns `None` (trade refused):
1. Gatekeeper check → blocked → `return None` (logs reason).
2. **No broker/account info → block** ("size against it; block the trade instead") — fails *safe*, not open.
3. `self._risk.assess_risk(account, positions)` → not acceptable → block.
4. `self._risk.calculate_position_size(...)` → `not approved or recommended_size <= 0` → block.
5. Else `approved_size` set and returned.

### 2.3 Risk manager — `risk/manager.py`
- Imports `enforce_pre_trade` (line 52) — the constitutional pre-trade invariants.
- **Kelly sizing**: `base_size = account_equity * kelly_f * KELLY_FRACTION` (capped fraction, default 0.25).
- **Drawdown-adaptive**: a `dd_f` factor scales size down as drawdown rises; `current_drawdown` / `daily_drawdown` tracked; `max_drawdown_pct` enforced.
- **VaR** present in the assessment path.
- **Mints the approval token**: `risk_approval_token = f"rat-{lineage_id}"` (line 838) — this is the proof an order passed the gate.

### 2.4 The choke-point — order authorization at *every* broker entry
`enforce_order_authorization(order)` refuses any order lacking a
`risk_approval_token` **and** a `decision_id`. It is wired at all three execution
surfaces (no broker call bypasses it):
- `execution/oms.py:200`
- `execution/smart_router.py:554`
- `execution/trade_executor.py:335`

And it is **enforced** (not just logged) as of the staged rollout
(`HOPEFX_INVARIANT_ENFORCE_KINDS=order_authorization,pre_trade`).

### 2.5 ML inference safety — `ml/inference_engine.py`
- **Stale-model block is ON by default**: `_STALE_MODEL_BLOCK = getenv("STALE_MODEL_BLOCK","true")` — a stale model refuses to serve unless an operator explicitly disables it. (A genuinely conservative default.)
- **Drift guard**: rolling `_drift_buffer` + KS-test vs `feature_stats.json`; `_DRIFT_BLOCK` defaults *false* (warn-only) — tunable to block.
- **Fallback path** + Prometheus counters (`hopefx_inference_fallback_total`, predict latency) for observability.

### 2.6 Reconciliation → kill switch
`core/position_reconciler.py` calls `enforce_reconciliation(...)`; on a
book-value/PnL breach `should_halt` is set and the caller trips the
`KillSwitch` (`kill_switch.py` — `activate()/is_active()`, admin-gated endpoint).
Currently **monitor** (logs, does not auto-halt) until soaked — by design.

**Money-path verdict:** the path is real, sequential, and *fails safe* (missing
account info → block; stale model → block; no approval token → block). The only
deliberate "advisory until soaked" pieces are the kill-switch-tripping checks.

---

## 3. Intelligence layer (honest, code-grounded)

- **Active model** (`ml/saved_models/registry.json` → `xgb_horizon5_v3`): horizon=5,
  193 features, trained on the bundled 50-year CSV (OANDA-free), **OOS 0.5734 ±
  0.011 over 2,016 trades, binomial p≈0 (significant), Sharpe-gate passed** — but
  **below the project's own 0.68 production bar** (`advanced_oos_meta.json`).
- **Real artifacts**: 25 MB RandomForest, XGBoost, stacking ensemble, PPO RL zip,
  feature scaler — loaded with **SHA-256 integrity verification**
  (`ml/live_inference.py::_verify_model_integrity` vs `registry.json`).
- **LLM "brain"** (`brain/llm_agent.py`): real Anthropic/OpenAI wrapper, **requires
  a paid key** (raises if unset) — it's someone else's LLM behind your key, not a
  proprietary trading oracle.
- **Honest read:** a real, reproducible, *small* edge (~57%), not institutional
  alpha. The model is correctly **horizon-aligned** to the 5-bar execution hold
  (the fix that closed the accuracy/P&L disconnect).

---

## 4. Safety architecture — what actually blocks

| Layer | Mechanism | Active state |
|---|---|---|
| Invariant library | **337 pure predicates / 37 modules** (`invariants/`), each `verify_* -> list[Violation]` | always computable |
| Enforcement façade | `invariants/enforcement.py` — `effective_mode(kind)` per-check staging | **monitor global + enforce: order_authorization, pre_trade** |
| Risk manager | Kelly, drawdown, VaR, exposure, per-symbol caps | in the trade path (Phase 3) |
| Order authorization | token + decision_id at 3 broker entries | **enforced** |
| Pre-trade | finite price/conf, crossed book, **stale-tick freshness**, min-confidence | **enforced** |
| Reconciliation / ledger | book-value/PnL + capital-equation → kill switch | **monitor** (staged; promote after soak) |
| ML staleness | stale model refuses to serve | **on by default** |
| Kill switch | global halt, admin-gated | reachable; tripped by reconciliation in enforce |

**Fail-safe design:** `HOPEFX_INVARIANT_FAIL_CLOSED=0` so a *checker bug* can't
halt the desk; checker exceptions are swallowed + logged (`_safe`), never raised
into the money path; every façade call returns an `EnforcementResult`.

---

## 5. Data layer — `data_layer/orchestrator.py` (real, multi-sourced)

- `MarketDataOrchestrator` with **per-source `CircuitBreaker`** and a
  `_WebSocketBroadcaster` for live push.
- **Tick quality is tracked**: `tick_confidence`, `tick_spread_pct`,
  `tick_source_count` — and a cached tick **without a `source` field is rejected**
  (`raise ValueError`), so provenance is mandatory.
- **Real gold feeds (7):** metals_dev, goldapi, metalpriceapi, metals_api,
  commodity_api, yahoo (+ manager).
- **Real macro feeds (6):** FRED, CFTC COT, IMF gold, WGC, yahoo_macro, store_bridge.
- **Real news feeds (5):** alpha_vantage, finnhub, fmp, newsapi, newsdata.
- Macro CSV fallback loads at startup so features are "never zero" offline.

## 6. Execution & brokers — real multi-broker

| Connector | Lines | Notes |
|---|---|---|
| `brokers/paper_trading.py` | 1,170 | the default working mode |
| `brokers/oanda_broker.py` | 815 | primary live target |
| `brokers/mt5_broker.py` | 754 | |
| `brokers/binance.py` | 707 | |
| `brokers/alpaca.py` | 553 | |
| `brokers/ibkr.py` | 480 | |

Live trading is **off by default** (`config/feature_flags.py: LIVE_TRADING`,
"intentionally off"), gated behind the **broker-agnostic** 30/90-day paper-run
gates (`PAPER_RUN_START_UTC` / `PAPER_FILL_COUNT`, any broker).

## 7. Frontend — `frontend/src/` (real, wired, role-gated)

- **629** wired backend API calls (`hooks/useApi.ts`), **69** pages, 57 components.
- **Real RBAC**: `isSuperAdmin`/`isAdmin`/`hasRole` + guards used across 17 files;
  superadmin-only surfaces (e.g. voice trading) self-gate.
- Voice layer (4 modes) wired: assistant talk+listen, opt-in spoken alerts,
  superadmin voice trading (confirmation-gated, routes through the same risk-gated
  order API), optional cloud TTS/STT with Web-Speech fallback.

## 8. Persistence & infra

- `api/db_store.py`: **SQLAlchemy** session management that **degrades gracefully
  to in-memory** when no DB is configured (works without a DB, loses data on
  restart in that mode).
- Docker / k8s (configmap, deployments) / Grafana / Prometheus / nginx present;
  20 GitHub workflows.

## 9. Quality & security posture (current)

- **Tests:** backend **14,791 passed / 0 failed** (`-m "not slow and not e2e"`),
  frontend **1,102 passed**. `ruff check` + `ruff format` clean repo-wide.
- **Security:** every **High** Dependabot alert fixed (PyJWT HS256 forgery,
  cryptography/OpenSSL, starlette SSRF, vite, undici, form-data, ws, aiohttp 3.14);
  one residual **Moderate** (js-yaml) is RN-toolchain-locked, build-time/local
  only, documented in `docs/SECURITY_DEPENDENCIES.md`.
- **CI:** red at the **GitHub Actions billing/runner level** (no runner assigned,
  logs 404) — infrastructure, not code.

## 10. Honest completeness verdict

| Dimension | State |
|---|---|
| Money-path wiring | **Complete & fail-safe** (traced; multi-block; choke-point enforced) |
| Safety library | **Complete** (337 predicates) — enforcement **staged on**, kill-switch checks pending soak |
| Intelligence | **Real but early** — ~57% OOS, below the 0.68 bar; needs paper-run validation |
| Data / brokers | **Complete & real** — multi-source feeds, multi-broker, paper default |
| Frontend | **Complete & wired** — RBAC, 629 calls, voice |
| Tests / lint | **Green** (14,791 + 1,102; clean) |
| Live-money readiness | **Not yet** — by design: live off, edge unproven, paper gates unmet |

### What "complete" honestly means here
The **engineering** is complete and verified: the trade path is fully wired and
fails safe, the safety net is built and partially enforced, the data/broker
plumbing is real, and the whole thing is green on tests + lint. What is **not**
complete is **earned trust for live capital** — that requires a real paper-trading
run (any broker, 30/90 days) and a model edge proven past the 0.68 bar. Those are
deliberate operational milestones, not missing code.

### The only non-code items remaining (external)
1. GitHub Actions billing (→ green CI).
2. A real broker paper run (→ flips the gates).
3. The Expo/RN upgrade per `docs/MOBILE_UPGRADE.md` (→ clears the last Moderate alerts).

---

## 11. Whole-app capability map (the full product, not just trading)

HOPEFX is a full multi-tenant trading **SaaS**, not only an engine: **933 routes
across 74 routers**, **67 feature flags in 16 categories**, **~110 UI screens**
(69 pages + 17 settings sub-pages + 24 superadmin sections). By domain:

### Trading & strategies
`trading` (37), `advanced_trading` (14), `advanced_orders` (7 — OCO/trailing/
iceberg), `signals` (18), `nuclear` + `nuclear_strategy` (23 — the high-conviction
engine), `dynamic_strategies` (8), `copy_trading` (7), `prop_firm` (7 — prop-firm
rule tracking), `broker` (4). Strategy library: MA/EMA/Bollinger/breakout/MACD/
RSI/SMC-ICT (feature-flagged).

### Intelligence (ML / AI)
`ml` (25), `brain` (16 — LLM agent), `ml_anomaly` (8), `ml_ops` (7), `online_learner`
(4), `explain` (4 — explainability), `nocode` (4 — no-code strategy builder).
Backed by `ml/` (inference engine, regime, RL, drift, registry) + `strategies/`.

### Money & business (the SaaS spine)
`monetization` (**49** — the largest router: plans, usage, entitlements),
`billing` (31), `payments` (6), `pricing` (5), `accounts` (11), `kyc` (6),
`affiliate`, crypto checkout. 5-tier plan system (free→elite) with role+plan gates.

### Analytics & research
`backtesting` (17), `performance` (11), `portfolio` (14), `portfolio_allocator`
(9), `pnl_dashboard` (7), `tca` (6 — transaction-cost analysis), `journal` (12),
`custom_indicators` (12), `transparency` (4), `risk_calculator` (4), plus
A/B testing, walk-forward, pattern-detector, correlation, replay (UI).

### Market data & alerting
`data_layer` (9), `macro` (8), `calendar` (9 — economic calendar), `watchlist`
(6), `alerts` (8 — price alerts), geopolitical-risk + news-sentiment (UI).

### Social & community
`social_feed` (8), `community_chat` (12), `copy_trading` (7), leaderboard, teams.

### Admin, security & ops
`admin` (38), `whitelabel_admin` (12 — white-label/multi-brand), `security_dashboard`
(18), `health` (8), `observability` (5), `tracing` (3), `chaos` (6 — chaos/mutation
testing), auto-heal + system-reliability + audit-log (UI). Superadmin console has
**24 sub-sections** (users, financial, ML, engine, compliance, GDPR, rate-limiting,
reporting, …).

### Identity, settings & platform
`two_factor` (6), `profiles` (13), `settings` + `settings_extended` +
`settings_new_endpoints` (28 — **17 settings sub-pages**), `platform` (15),
`mobile` (10), `voice` (3), `notifications` (9), `status` (10), `pages` (14).

### Honest maturity note on the surface
This breadth is **real and wired** (629 frontend calls hit it), but breadth ≠
uniform depth. Money-movement, auth/RBAC, data, and the decision/risk path are the
deeply-built, well-tested core. Several feature-flagged areas are explicitly
`EXPERIMENTAL`/`BETA` in the registry (e.g. advanced order types, parts of the
nuclear engine, online learning) — present and routed, but earlier-stage. The
flag registry itself is the source of truth for what's production vs experimental.
