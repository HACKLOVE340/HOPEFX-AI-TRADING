# HOPEFX — Code-Reading Audit Log (in progress)

Findings from a read-only pass over the actual source, not the docs. Every entry
was verified against code at the file:line cited; entries that dissolved on
inspection are recorded as retracted rather than deleted, so they are not
re-found later and re-reported as bugs.

**Status: in progress.** ~95 of 1,838 source files read directly (~5%). Eight
domain audits were running when this was written; their findings are not yet
merged in.

Severity is impact on capital/correctness, not effort.

# HOPEFX — Understanding + Findings Log
(read-only pass; nothing fixed)

## F1 — ARCHITECTURE.md documents a deliberately-deleted module
`websocket/manager.py` appears twice (canonical module map; Security Fix #2).
CLAUDE.md: "never recreate a top-level websocket/ package — it shadows the
websocket-client library and silently disables the REST fallback in
market_data/mt5_live_feed.py (audit S13-02a)". Dir does not exist. VERIFIED.
Severity: MEDIUM (steers a reader into a known-bad change)

## F2 — ARCHITECTURE.md Security Fix #5 claims prop_firm_mode.json is gitignored
It is tracked. .gitignore:124 commits it on purpose for CI. CLAUDE.md already
corrected this and warns the stale claim invites real credentials in a tracked
file. ARCHITECTURE.md still carries it. VERIFIED.
Severity: MEDIUM (credential-handling misdirection)

## F3 — ARCHITECTURE.md says APP_ENV defaults to `production`; code says `development`
5 sites default to "development", trader_full.py:64 defaults to "paper".
Gates core/startup_factories.py: live-broker-without-enforce is sys.exit(1) only
when is_production, else a warning. All containers set APP_ENV=production
explicitly (Dockerfile:83, compose x3, entrypoint.sh:5 hard-fails if unset), so
exposure is limited to bare-metal/systemd runs. VERIFIED.
Severity: MEDIUM (bounded to non-container deploys)

## F4 — startup guard's broker detection does not cover BROKER_PRIMARY
Guard reads (BROKER_TYPE or BROKER); brokers/manager.py:159 reads BROKER_PRIMARY
defaulting to "ibkr" (a live broker). BUT BrokerManager.from_env() is called
nowhere in production and IBKR_PORT defaults to 7497 (paper). Latent only.
Severity: LOW-now / HIGH-if-wired

## F5 — docs/architecture.md contradicts itself on feature count
Overview: "193-feature stacking ensemble". Production Model table: "Features 176".
Data-flow diagram: "AdvancedAIEnsemble (176 features)". ARCHITECTURE.md: "Features 193".
Severity: LOW (doc), but it is the headline model spec.

## F6 — the deployed model does not meet its own promotion gate
docs/architecture.md: "OOS promotion gate: accuracy >= 0.60 AND p-value <= 0.05"
(REGISTRY_MIN_OOS_ACC = 0.60). Production model advanced_oos.pkl: OOS accuracy
**56.5%**. So the live model is below the documented promotion threshold.
Either the gate is not applied to it, it was grandfathered, or the doc is wrong.
Severity: HIGH — needs an answer, not a doc edit. UNRESOLVED.

## F7 — six module paths in docs/architecture.md do not exist
  brokers/alpaca_broker.py     -> actual: brokers/alpaca.py
  brokers/binance_broker.py    -> actual: brokers/binance.py
  brokers/bybit_broker.py      -> actual: brokers/bybit_connector.py
  brokers/paper_broker.py      -> actual: brokers/paper_trading.py
  execution/order_management.py-> actual: execution/oms.py
  execution/slippage_model.py  -> DOES NOT EXIST ANYWHERE
Severity: LOW-MEDIUM (navigation; oms.py mismatch also appears in CLAUDE.md as canonical)

## F8 — "MarketDataForbidden" rule is overstated in the doc
docs/architecture.md: "Price data methods raise MarketDataForbidden — use
orchestrator.get_latest_tick()". Reality: class is MarketDataForbiddenError,
defined TWICE (brokers/ibkr.py:99, brokers/oanda.py:99), enforced in only those
2 of 8 connectors. base.py declares get_market_data as a plain @abstractmethod
with no guard.
CORRECTION TO MY OWN READ: get_market_data() returns historical OHLCV bars, not
live ticks, and is legitimately called by core/signal_engine.py:399, api/ml.py:192,
api/advanced_trading.py:486, backtesting/data_sources.py:168. So this is a DOC
inaccuracy, not an architectural hole. paper_trading.py:1102 does raise under
APP_ENV=production because it returns synthetic series.
Severity: LOW (doc) / worth noting: ML features can be built from synthetic paper
data when not APP_ENV=production.

## F9 — router count understated
docs says "50+ routers"; 93 files define APIRouter(), 68 referenced by
core/router_registry.py. Checked for defined-but-unmounted: none found (detection
was permissive, so this is "no evidence of orphans", not a proof).
Severity: LOW

## F6 — RESOLVED BY FURTHER READING (was "model below its own gate")
core/live_trading_gate.py:80 _OOS_MIN_ACC=0.60; :227 `if acc < _OOS_MIN_ACC: return False`.
The gate READS the model's OOS metadata and BLOCKS live trading. Production model
is 56.5%, so live trading is correctly gated OFF. This is the system working as
designed, not a bypassed gate. Matches ARCHITECTURE.md "Live broker credentials
❌ Not configured" and CLAUDE.md "paper trading active; live OANDA is next".
Severity: NONE — retracted.

## F10 — DRIFT_BLOCK documented default is true; code default is false
ARCHITECTURE.md:156 says default `true`. ml/inference_engine.py:81 defaults
"false" (comment: "Default: 4.0 (warn only). Set DRIFT_BLOCK=true to block").
Set to true in .env.example:1214 and k8s/k8s-configmap.yaml:43 (with a CRITICAL
comment). NOT set in docker-compose.yml, docker/docker-compose.yml, or
.env.production.example.
=> k8s deploys block on drift; docker-compose and bare-metal only warn, while the
   docs tell the operator it defaults to blocking.
Severity: MEDIUM. VERIFIED.

## F11 — .env.production.example sets none of the ML/live safety gates
No DRIFT_BLOCK, STALE_MODEL_BLOCK, MODEL_MAX_AGE_DAYS, LIVE_MODE_CONFIRMED.
Combined with F3 (APP_ENV) and F10, the "production" template is the weakest of
the three production surfaces; k8s configmap is the strongest.
Severity: MEDIUM. VERIFIED.

## BACKLOG STATUS MAP (44 items with ### Sx-yy headings)
CRITICAL x5  — ALL fixed, all guarded by regression tests
  S1-01 live OANDA blocked every trade | S2-01 split-brain kill switch
  S3-01 frictionless backtest | S12-04 stop-loss never reached broker
  S13-03 every BUY submitted as SELL
31/44 cite a guard test in .py; +5 more cite frontend/workflow files;
S6-04 verified fixed in code without citing its ID.
=> Remaining genuinely-uncited: 7
   HIGH:   S1-03 (backlog self-corrects it: downgraded, halt does persist)
           S11-02 undocumented unsafe-trading flags
           S12-02 suite tests the lock never the key
           S3-02  fills on the signal's own bar
           S3-05  backtest and live share no code
   MEDIUM: S12-03 skips | S3-06 duplicated engines and cost models
CAVEAT: "uncited" != "open". S6-04 proves fixes land without citing the ID.

════════ CODE-READING PASS (actual source, not docs) ════════

## F12 — MODEL METRICS ARE WRONG IN EVERY DOC AND IN A SOURCE COMMENT
Ground truth ml/saved_models/advanced_oos_meta.json (the file ARCHITECTURE.md
itself names "Source of truth"):
    trained_at   2026-06-26        oos_accuracy 0.5734    oos_f1 0.6767
    oos_auc      0.582             feature_count 193      oos_n  2016
    oos_period   2016-08-17 → 2026-03-25                  horizon 5
Reported as:
  ARCHITECTURE.md      acc 56.5% | F1 0.6885 | AUC 0.5427 | trained 2026-05-08
                       | period 2017-03-09 → 2026-03-18   -> 5 fields WRONG
  docs/architecture.md acc 56.5% | features 176 (table) vs 193 (overview)
  core/signal_engine.py:73  "# Advanced ML predictor (122-feature, 68% OOS accuracy)"
                       -> BOTH wrong; 68% overstates a 57.34% model by 11 points
Cause: ARCHITECTURE.md says "Last updated 2026-04-17"; the model was retrained
2026-06-26, after that edit. feature_count=193 settles the 193/176/122 dispute.
Severity: HIGH (a source comment claiming 68% invites sizing/marketing decisions
on a number 11 points too high). VERIFIED against the artifact metadata.

## F13 — AUTOTRADE_MIN_SIGNAL_SCORE is silently ineffective when raised
core/signal_engine.py:1735
    if _grade not in ("STRONG","GOOD") and _score < _min_auto_score: return
ml/signal_scorer.py:36-39,80-82 derives grade FROM the composite score:
    >=0.75 STRONG | 0.60-0.75 GOOD | 0.45-0.60 FAIR | <0.45 WEAK
    _GOOD_THRESHOLD  = env SCORER_GOOD_THRESHOLD      (default 0.60)
    _min_auto_score  = env AUTOTRADE_MIN_SIGNAL_SCORE (default 0.60)
At defaults the two clauses are EQUIVALENT, so the `and` is redundant/harmless.
They are independently overridable. Raise AUTOTRADE_MIN_SIGNAL_SCORE to 0.70 to
be more conservative and NOTHING TIGHTENS: a 0.65 signal is graded GOOD, the
first clause is False, the `and` short-circuits, the order goes through.
The docstring above it states the intended behaviour that does not hold:
"FAIR and WEAK signals are published for human review but never auto-executed."
Fails closed correctly when scoring errors (setdefault UNKNOWN/0.5 -> blocked).
Severity: MEDIUM-HIGH latent — a safety knob that does nothing when tightened.
Same class as backlog "the gate that never fires" items. VERIFIED.

## Understanding — the real auto-trade gate chain (core/signal_engine.py:1713+)
 1 SIGNAL_ENGINE_AUTO_TRADE          default false
 2 _check_live_trading_gate()        5-check
 3 broker present                    else return
 4 direction in (BUY, SELL)
 5 signal grade/score gate           see F13
 6 risk_manager present              blocks explicitly if None
 7 _assess_risk_and_size()
 8 _place_order_and_notify()
Engine defaults: SIGNAL_ENGINE_SYMBOLS=XAUUSD, SIGNAL_ENGINE_INTERVAL=60s.
SL/TP fallbacks: ATR x1.5 stop / x3.0 target; 0.8% ATR proxy; 1.5% fixed stop.

## Understanding — app.py boot (actual code)
load_dotenv(override=False) -> Windows SelectorEventLoop + aiohttp ThreadedResolver
-> HOPEFXLogger (JSON in prod) -> validate_environment(strict=True) -> background
npm build if static/index.html missing -> Sentry -> rate limiting -> default
executor = ThreadPoolExecutor(IO_THREAD_POOL_SIZE, default 64) -> log_safety_config()
(S11-03) -> kill_switch.start() -> app.state.app_state set BEFORE startup task so
StartupGateMiddleware 503s during boot -> startup_event() as a background task so
uvicorn accepts immediately. Non-Exception BaseException from startup_event
(SystemExit from a gate) triggers an explicit hard exit, because the 64-thread
pool + OTel BatchSpanProcessor are non-daemon and would otherwise leave the
container "running" with nothing listening. That war story is in the code.
NOTE: IO_THREAD_POOL_SIZE=64 is the pool my asyncio.to_thread work now shares.

════════ FRONTEND / UI-UX (actual code) ════════

## F14 — muted text fails WCAG AA for body text (measured)
index.css tokens: --bg #080c14, --surface #0d1421, --raised #111827
Computed WCAG contrast for #64748b (slate-500):
    on --bg 4.11 | on --surface 3.87 | on --raised 3.73     (AA body text = 4.5)
Passes the 3.0 bar for large text / UI components only. Used at 9-10px in places,
where the "large text" exemption does NOT apply (large = >=18.66px bold / >=24px).
Real data rendered at this contrast, not just chrome:
    pages/Trade.tsx:141  the SPREAD value  {fmtPrice(tick.ask - tick.bid, 3)}
    pages/Trade.tsx:302  trade timestamps  {fmtDateTime(t.opened_at)}
    pages/Trade.tsx:216,228,272  9-10px uppercase column labels
All other tokens pass comfortably: --text 15.88, --accent 11.05, bull 11.72,
bear 5.09, conf.low 6.90, neon.amber 11.28 (all vs --bg).
Severity: MEDIUM (accessibility, 189 occurrences). VERIFIED BY COMPUTATION.

## F15 — --text-muted is a dead design token
index.css defines --text-muted: #64748b. Referenced 0 times anywhere.
The same colour is hardcoded as tailwind `text-slate-500` 189 times instead.
So the token layer is bypassed: changing --text-muted changes nothing, and a
future palette fix has to touch 189 sites rather than one variable.
Severity: LOW-MEDIUM (maintainability / theming correctness). VERIFIED.

## NOT A FINDING — bull/bear colour pair is colour-blind safe
bull #00e676 vs bear #ff1744 have only 2.30 contrast against EACH OTHER, which
would be a red-green colour-blindness failure if colour were the sole cue.
It is not: lib/utils.ts:123 fmtPnl() always prefixes '+' or '-', and the ticker
pairs colour with <TrendingUp/> / <TrendingDown/> icons (LandingPage.tsx:425-426).
Colour is redundant, not load-bearing. Retracted before reporting.

## Understanding — frontend architecture (actual code)
302 src files / 95,599 LOC. pages 112 files (49,480 LOC), components 66, features
31, hooks 12, test 69 files (17,812 LOC), store 1 file (644 LOC).
App.tsx: 70 React.lazy() page imports, 86 routes, composed guards —
    wrap(el)            = ErrorBoundary only (no auth)
    gated(key, el)      = AuthGuard > SubscriptionGate
    adminOnly(el)       = AuthGuard > AdminGuard
    superAdminOnly(el)  = AuthGuard > SuperAdminGuard
54 routes guarded / 32 ungated; the ungated set is redirects + the public
marketing & auth surface (/, /login, /register, /pricing, /terms, /privacy) plus
public content (/docs, /leaderboard, /marketplace, /profile/:id, /transparency,
/news, /system-status). Frontend routing is UX, not the security boundary.
State: zustand + persist. Slices: Auth, Price, Position, Signal, Account, Equity,
Risk. partialize persists user / isAuthenticated / plan / trial ONLY — the access
token is never persisted; a httpOnly refresh cookie drives silent refresh, and
isAuthenticated is reset to false on rehydrate so it is never trusted without a
live token. This is correct and the reasoning is in the code.
Design system: dark-first "terminal" palette, JetBrains Mono for numerals, Inter
for prose, xs:375px breakpoint, theme = light/dark/system via data-theme +
prefers-color-scheme (ThemeContext.tsx, AppearanceSection.tsx).

## Backend/frontend contract observed
api/transparency.py: /decisions, /explain/{trade_id}, /stats, /statement are
PUBLIC by design (platform's own decisions, published for auditability);
/audit-log requires auth. client_statement() takes no params — system-wide, not
per-client — and its own disclaimer says the model edge is "below the production
bar", consistent with oos_accuracy 0.5734 < the 0.60 live gate.
api/status.py: 9 public status endpoints (intended for a public status page),
/paper-trading/gate/fill requires auth.

## F16 — *** S1-02 IS STILL LIVE IN THE SECOND AUTO-TRADE PATH *** · HIGH
core/signal_engine.py:1440
    equity: float = account_info.get("equity", 100_000)

brokers/base.py:315-323 documents the rule this breaks, verbatim:
    "Note this is ``getattr``-based, so a **missing field returns the caller's
     default**. Callers must not pass a plausible-looking default for a value
     they cannot safely fabricate — notably account equity, where a default
     would be sized against as if it were real."

core/decision/HOPEFXDecisionEngine.py:487-500 honours it and says why:
    "No default. ... which is how a broker whose account object lacks `equity`
     would silently be sized against a fabricated six-figure balance. Block
     instead. ... that misattribution is what made S1-01 look like a risk limit
     for the whole of the live-OANDA path."

So S1-02 was fixed in the DecisionEngine path and the identical defect remains in
the parallel SignalEngine auto-trade path. `broker.get_account_info()` returns an
AccountInfo (base.py declares -> AccountInfo); signal_engine annotates it
`dict[str, Any]`, which is also wrong, and .get() is the getattr-based one.
base.py:281-288 records that a broker-local AccountInfo variant lacking `equity`
HAS shipped before ("Do not reintroduce a broker-local variant").

Failure scenario: SIGNAL_ENGINE_AUTO_TRADE=true + any broker whose AccountInfo
lacks an `equity` attribute -> every position is sized against a fabricated
$100,000 account, silently, with no error. On a real account of, say, $2,000
that is 50x over-sizing.
Reached only when SIGNAL_ENGINE_AUTO_TRADE=true (default false), and
assess_risk() runs first — but assess_risk reads equity the same way.
Repo-wide sweep: this is the ONLY live-path fabricated account default.
  brokers/__init__.py:1242, brokers/paper_trading.py:262 — paper initial_balance, legitimate
  api/prop_firm.py:114 — display-only, guarded by an _engine_live flag and a
                         visible "not yet initialised" message. Correct.
  every other .get("equity"/"balance"/"nav", 0) defaults to 0, which fails safe.
Minimal fix: mirror the DecisionEngine — read defensively, block on <=0, no default.
Severity: HIGH. VERIFIED.

## Understanding — risk/manager.py config surface (all env-overridable)
  RISK_MAX_POSITION_PCT      0.05     RISK_MIN_POSITION_PCT     0.001
  RISK_KELLY_FRACTION        0.25     RISK_MAX_KELLY_FRACTION   0.5
  RISK_STOP_ATR_MULT         1.0      RISK_TARGET_ATR_MULT      2.0
  RISK_MAX_DAILY_LOSS_PCT    0.05     RISK_MAX_DRAWDOWN_PCT     0.10
  RISK_MAX_OPEN_POSITIONS    3        RISK_MIN_DATA_QUALITY     0.40
  RISK_MAX_TICK_STALENESS_S  5.0      RISK_VAR_CONFIDENCE       0.95
  RISK_SENT_SIZE_SCALE 0.40 | RISK_IMPACT_SIZE_SCALE 0.50 | RISK_DD_SIZE_SCALE 0.80
Quarter-Kelly default is appropriately conservative. Sizing multiplies factor
scalars (quality/sentiment/impact/drawdown) so adverse conditions shrink size.
S1-06 fix noted in code: confidence was `max(confidence, signal_strength)`, which
floored every signal at the 0.7 default and made sizing blind to real edge.

## F17 — invariant order-state table does NOT mirror the OMS, despite saying so
invariants/constitution.py:60 comment: "Mirrors execution/oms.py's transition table."
Diffed both tables — divergent in 4 states, invariant strictly MORE permissive:
  CREATED           invariant also allows NEW, REJECTED
  NEW               invariant also allows ACKNOWLEDGED, CANCELLED, REJECTED
  PARTIALLY_FILLED  invariant also allows CANCELLED, EXPIRED
  ACKNOWLEDGED      a whole state the OMS OrderStatus enum does not have
"ACKNOWLEDGED" appears ONLY in invariants/constitution.py — no other file in the
repo uses it. Direction matters: the invariant is looser, so it never false-blocks;
it just cannot catch the OMS transitions it permits. The constitutional
"No State Corruption" check is weaker than the OMS's own guard.
Also: verify_order_state_transition() has NO production call site (only
invariants/__init__.py re-export + its own definition). Inert inline.
Severity: MEDIUM. VERIFIED by table diff.

## F18 — 7 of 16 enforce_* functions have no production call site
invariants/enforcement.py defines 16 enforce_* wrappers; enforcement.py itself
references only 20 of the 337 predicates.
  WIRED (9): enforce_pre_trade, enforce_order_authorization, enforce_reconciliation,
             enforce_ledger_reconciliation, enforce_exposure, enforce_var,
             enforce_trust_allocation, enforce_risk_appetite, enforce_human_approval
  INERT (7): enforce_action_audited, enforce_audit_chain, enforce_blast_radius,
             enforce_no_spof, enforce_pod_isolation, enforce_policy_governance,
             enforce_recovery_readiness
CONTEXT / partial defence: invariants/__init__.py states the design is two-tier —
"enforced inline (refuse/halt on violation) and verified externally (CI / ops via
scripts/runtime_invariant_check.py)". So a predicate with no inline enforcer is
not necessarily dead. But 7 enforce_* wrappers exist specifically to enforce
inline, and those 7 are not invoked by anything.
CORRECTION TO MY FIRST ATTEMPT: I initially measured "335 of 337 predicates
uncalled" by excluding invariants/ from the search — which excluded enforcement.py,
the very module that calls them. That number was meaningless; this is the real one.
Severity: MEDIUM. VERIFIED.

## F19 — invariant_coverage.py prints "FULL COVERAGE ✅" above its own warning
Actual run: recoverable 10/12; database and redis_cache show [P M A -r];
"⚠️ recovery: recovery coverage 10/12 (83%) below required 100%" — then the
summary line prints "FULL COVERAGE ✅" and exits 0.
NOT A BUG — deliberate and documented at scripts/invariant_coverage.py:17-19:
"recovery gaps are surfaced as warnings, since DB/Redis single-instance is a known
infra choice". recovery is severity WARN; only ERROR gaps set exit 1.
The only nit is the label: an operator scanning for the summary line sees a green
check two lines under a ⚠️ that says coverage is below the required level.
Severity: LOW (cosmetic reporting only). Recorded so it is not re-found as a bug.

## Understanding — what is ACTUALLY enforced inline, verified by running the tools
Registry: 338 predicates / 34 modules (scripts/invariant_coverage.py).
Critical-component coverage: protected 12/12, monitored 12/12, alerted 12/12,
recoverable 10/12 (database, redis_cache lack recovery — accepted infra choice).
The 12 declared critical components: order_execution, risk_engine, reconciliation,
kill_switch, market_data_feed, ml_inference, audit_log, database, redis_cache,
broker_connection, ledger_treasury, ai_agents.

## F20 — TWO different classes both named HopeFXEngine (not in the backlog)
  ./hopefx_engine.py:190            HopeFXEngine   1743 lines  <- the real one
        imported by run.py:387, core/startup_factories.py:2951, connect_to_life.py
  ./execution/hopefx_engine.py:127  HopeFXEngine   1073 lines  <- NO production consumer
        imported ONLY by tests (test_execution_full*.py, test_runtime_invariant_regressions.py)
1,073 lines kept alive solely by its own tests. Two same-named classes with
different behaviour is an import-order trap: `from hopefx_engine import HopeFXEngine`
vs `from execution.hopefx_engine import HopeFXEngine` silently give different objects.
Backlog S3-06 documents duplicated BACKTEST engines but does NOT mention this pair.
Severity: MEDIUM. VERIFIED. — extends S3-06.

## F21 — S3-06 is still open, and worse than written
Backlog says "two different classes named TransactionCostModel". There are THREE:
    backtesting/transaction_costs.py:99
    backtesting/enhanced_engine.py:298
    backtesting/engine.py:273
All four backtest engines still present: engine.py 946, enhanced_engine.py 2704,
backtest_engine.py 411, backtest/engine.py 43 (the documented re-export shim).
backtesting/cli_runner.py:249 still constructs BacktestEngine(...) with no cost
model — but S3-01 is fixed (guard test test_backtest_costs_not_free.py passes),
so the defaults inside the engine now carry cost, not the call site.
Severity: MEDIUM (open). VERIFIED.

## F22 — the data-quality floor is inconsistent three ways
  docs/architecture.md   : "is_safe_to_trade() returns False when data quality
                            below ENGINE_MIN_DATA_QUALITY (default 0.40)"
  data_layer/orchestrator.py:1094 : hardcoded `if tick.confidence < 0.30` —
                            different field, different threshold, NOT env-overridable
  execution/hopefx_engine.py:70   : ENGINE_MIN_DATA_QUALITY default 0.40 — a
                            DIFFERENT module (and per F20 it has no prod consumer)
  .env.example:1540               : ENGINE_MIN_DATA_QUALITY=0.80 — 2x the code default
So the doc attributes the wrong knob to the wrong function; the knob it names
lives in a module nothing imports; and the shipped example value is double the
code default. The real orchestrator floor (0.30) cannot be tuned at all.
Severity: MEDIUM. VERIFIED.

## Understanding — data_layer/orchestrator.py freshness (good code)
get_latest_tick(): Redis cache first, then in-memory GoldFeedManager. Cached tick
is served ONLY if -TICK_FUTURE_SKEW_TOLERANCE_S (5.0) <= age <= DQE_STALE_THRESHOLD_S
(30.0). Rejects future-dated ticks explicitly; the comment records both prior bugs
(a 2x buffer that re-served ticks the DQE would mark STALE, and negative ages
trivially passing an upper bound). Requires a known FeedSource rather than
fabricating an origin.
is_safe_to_trade(): blackout window -> tick is None (fails CLOSED) ->
confidence < 0.30 -> feed stalled >30s after start.

## F23 — kill-switch ops mechanisms are INERT under `run.py --mode engine` · MED-HIGH
kill_switch.KillSwitch.start() is the ONLY launcher of all of these (verified —
`_poll_loop` is created at exactly one site, line 297):
    _check_redis_latch()        startup cross-pod latch check
    _check_broker_cod()         broker Cancel-on-Disconnect verification
    event-bus KILL_SWITCH subscription
    _redis_breach_listener()    cross-pod kill propagation
    _k8s_configmap_watcher()    Redis-down fallback
    _poll_loop()                kill_switch.flag file + HOPEFX_KILL_SWITCH env var
hopefx_engine.py (the `run.py --mode engine` entry, run.py:387) NEVER calls
start() — grep for `_ks.start()` / `kill_switch.start()` returns nothing. It only
imports the singleton and reads `_ks.is_active()`, which returns the bare
in-memory `self._active`.
=> In --mode engine: dropping kill_switch.flag does nothing; HOPEFX_KILL_SWITCH=1
   (the documented K8s/ops override) does nothing; a latch set by another pod is
   never seen; broker CoD is never verified. Only an in-process activate() works.
The engine's own order path IS otherwise careful: hopefx_engine.py:1003-1026
blocks on ImportError AND on any exception from the check (fail-safe), and
line 155 does a startup pre-check.
BOUNDED — this is NOT the production path:
    Dockerfile:91  CMD ["bash","-c","scripts/preflight.sh && python app.py"]
    app.py:564     await kill_switch.start()          <- fully armed
    core/startup_factories.py:2941 init_trading_engine() hosts HopeFXEngine
                   INSIDE the API process, so the containerised engine shares the
                   started singleton and every mechanism works.
So the gap applies to standalone `run.py --mode engine` only — a documented entry
point in ARCHITECTURE.md and CLAUDE.md, but not what the container runs.
Same shape as F3: a real gap on a documented, non-containerised path.
Severity: MEDIUM-HIGH (bounded). VERIFIED.

## Understanding — kill switch design (kill_switch.py)
5-layer activation, in priority order: in-memory _active | kill_switch.flag file
(2s poll) | HOPEFX_KILL_SWITCH=1 env | Redis latch `ks:latch` TTL 7d | K8s
ConfigMap watcher (Redis-down fallback). Layers 2+3 are Redis-independent by
design. deactivate() requires HOPEFX_KILL_SWITCH_TOKEN, uses hmac constant-time
compare, and REFUSES when no token is configured (fails closed); the flag file
must additionally be removed by hand, deliberately forcing an explicit operator
action. reset_for_testing() is explicitly test-only. is_active() returns the bare
_active flag — layers 2-5 reach it only through the poll loop, which is why F23
matters.
