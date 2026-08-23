# HOPEFX — Code-Reading Audit Log (in progress)

Findings from a read-only pass over the actual source, not the docs. Every entry
was verified against code at the file:line cited; entries that dissolved on
inspection are recorded as retracted rather than deleted, so they are not
re-found later and re-reported as bugs.

**Status: in progress.** ~95 files read directly by me, plus 4 completed domain audits (execution, brokers, ML, payments) and the API/security domain done directly. Eight
domain audits were running when this was written; their findings are not yet
merged in.

Severity is impact on capital/correctness, not effort.

# HOPEFX — Understanding + Findings Log
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

════════ AGENT FINDINGS (2 of 8 completed; 6 died on session limit) ════════

## F24 — *** TRAIN/SERVE SKEW: 48.2% OF MODEL FEATURES ARE ZERO-FILLED LIVE *** · CRITICAL
INDEPENDENTLY RE-VERIFIED BY ME, not just relayed. Ran both builders against the
shipped artifact:
    SERVE  ml/advanced_features.build_advanced_features  -> 101 cols
    TRAIN  ml/features_extended.build_extended_features  -> 194 cols
    MODEL  advanced_oos.pkl feature_names_in_            -> 193
    MISSING AT SERVE: 93 / 193 = 48.2%
    by prefix: inst_ 39, ri_ 26, of_ 17, frac_ 11
Cause — two different builders:
    ml/train_advanced.py:1323   from ml.features_extended import build_extended_features
    ml/live_inference.py:327    from ml.advanced_features import build_advanced_features
features_extended.py:912-916 adds add_orderflow_features, add_fractal_features,
add_regime_interactions, add_institutional_edge_features on top of the base
builder. The serve path never calls them, so those 93 columns CANNOT exist live.
Handling — ml/live_inference.py:444-465: computes impute_frac (0.482), logs a
WARNING, then `for col in missing: X[col] = 0.0` and predicts anyway. No abstain.
The warning text blames "MacroStore or data layer likely unavailable" — a
transient-sounding cause for a PERMANENT structural gap. It fires every bar, which
is exactly why it reads as noise.
Agent measured the effect on real scoring: corr 0.5576 between true and served
probabilities, direction agreement 62.8%, variance collapsed (std .0416 -> .0289),
and long triggers at >=0.58 went 14/1440 -> 0/1440.
=> The served model is a different, variance-collapsed model. The 0.5734 OOS in
advanced_oos_meta.json does not describe what actually predicts in production.
ONLY the live_trading_gate (OOS<0.60) currently stops this from moving money.
Severity: CRITICAL.

## F25 — model staleness measured from FILE MTIME, not trained_at · HIGH
ml/inference_engine.py:718  age_seconds = time.time() - model_path.stat().st_mtime
Agent measured on this checkout: mtime 2026-08-17 -> 3.7 days -> not stale;
trained_at 2026-06-26 -> 55.0 days -> stale. MODEL_MAX_AGE_DAYS=30.
A 55-day-old model is passing a 30-day gate RIGHT NOW. Any git clone, docker
build, rsync or CI artifact restore resets mtime, so STALE_MODEL_BLOCK (default
true) can never fire. trained_at is present in the metadata and is ignored here.
Severity: HIGH. Source line verified by me.

## F26 — the "Sharpe gate" never reads the Sharpe ratio · HIGH
ml/train_advanced.py:900   gate_passed = n_trades >= target_n     # sharpe unused
ml/train_advanced.py:1168  sharpe_gate_check(n_trades=n, sharpe=1.52, ...)  # literal
n is OOS BARS (2016), not trades — which is why the metadata shows
n_trades == oos_n == 2016. So gate_passed = (2016>=600) = True unconditionally and
sharpe 1.52 is a hardcoded constant, not a measurement. model_registry.py:789
lifts sharpe_gate_passed from that field and :288 enforces it.
=> a model with a genuinely NEGATIVE Sharpe passes the registry Sharpe gate.
A correct implementation exists (train_advanced.py:1012 SharpeProgressTracker,
which does compare sharpe >= target) and is not used by the artifact writer.
Severity: HIGH. (agent-reported; source lines not yet re-verified by me)

## F27 — registry state vocabulary is inconsistent; circuit breaker cannot retire · HIGH
sharpe_circuit_breaker.py:490 retires only if state == "production";
model_registry.py:385 promote() writes "production";
verify_model.py:122 fails anything != "active";
registry.json records the live entry as state="active".
=> the Sharpe circuit breaker trips, fires its CRITICAL alert, then silently
no-ops the retirement — the failing model stays active.
Also: active model oos_accuracy 0.5734 < REGISTRY_MIN_OOS_ACC 0.60, and its state
is "active" not "production" — the fingerprint of a manifest edited by hand rather
than promoted through promote(), which would have raised.
And live scoring never consults the registry at all: live_inference.py:183
hardcodes _SAVED/"advanced_oos.pkl".
Severity: HIGH. (agent-reported)

## F28 — two shipped artifacts fail their recorded SHA-256 · MEDIUM-HIGH
feature_scaler.pkl MISMATCH, stacking_ensemble.pkl MISMATCH, lstm_signal.pt MISSING.
advanced_oos.pkl / current.pkl / rf_* / xgb_* verify OK. The live model is clean and
live_inference._verify_model_integrity does fail closed on a registry-tracked
mismatch — but two tracked artifacts are already drifted in the committed tree,
so the checksum manifest is not actually enforced in CI as claimed.
Severity: MEDIUM-HIGH. (agent-reported)

## F29 — abstention gates validate a vector that is then discarded · MEDIUM
inference_engine.py:411-447 builds the CORRECT 193-feature matrix via
features_extended and runs the S4-02/S4-03 abstain gates on it (NaN/Inf, >95%
zeros). Then :1151 calls predictor.predict_proba(ohlcv, ...) passing RAW OHLCV, and
the predictor rebuilds its own 101-col matrix. The validated vector is never scored.
So the "non_zero_pct < 0.05" check inspects a healthy vector while the vector
actually scored is 48% structural zeros.
Severity: MEDIUM. (agent-reported)

## F30 — the drift guard DETECTS the skew and is configured not to block · MEDIUM
S4-01 no longer holds — the guard now watches predictor.last_scored_features, i.e.
the real scored matrix (coverage 176/193 = 91.2%). Agent replayed the serving
vector: 12 of 176 monitored features exceed z=4.0 and ALL 12 are F24 zero-fills
(frac_perm_ent_10 z=19.3, frac_perm_ent_5 z=12.2, inst_buy_pressure_20 z=10.0...).
_DRIFT_BLOCK defaults false, so it warns and passes the trade through.
=> the one independent detector of F24 is switched to warn-only by default.
Severity: MEDIUM. (agent-reported)

════════ PAYMENTS / MONEY (agent-reported, not yet re-verified by me) ════════

## F31 — all affiliate + subscription money state is IN-MEMORY ONLY · CRITICAL
monetization/affiliate.py:316-320 (_affiliates/_referrals/_payouts) and
subscription.py:306-307 (_subscriptions) are plain dicts. No session_factory /
session.add / commit() anywhere in either file.
=> a pod restart erases every referral, accrued commission and payout record;
already-paid payouts vanish so the same commissions accrue again. Confirms the
backlog's "persistent audit log" item is still OPEN.

## F32 — affiliate payout TOCTOU double-pay; NO lock on any money path · CRITICAL
affiliate.py:495-528 read pending -> create Payout -> mark referrals PAID, with no
lock and no atomic compare-and-set. Agent grepped all of monetization/ + payments/
for threading.Lock|asyncio.Lock|RLock|with_for_update: only two hits, both in
payments/crypto/, neither on a money path.
=> two concurrent POST /affiliate/{id}/withdraw (api/monetization.py:1525, self-serve)
both read the same pending and both pay it.

## F33 — partial settlement forfeits the remainder · HIGH
affiliate.py:662-668 marks a referral fully PAID even when only part of its
commission was needed. Withdraw $100 against a single $300 referral -> referral
marked PAID, $200 unrecoverable.

## F34 — a FAILED payout permanently destroys the commission · HIGH
fail_payout (affiliate.py:556-563) does not restore referral state; referrals were
flipped to PAID BEFORE the transfer was attempted. Transfer bounces -> payout
FAILED, referrals stay PAID, pending reads $0, no record the money is owed.

## F35 — creator payout double-pay + no Stripe idempotency key · HIGH
revenue_split.py:311-364 unlocked read-then-zero; _stripe.Transfer.create at :371
passes NO idempotency_key. Also, if the transfer succeeds at Stripe but the
response times out, :389-392 marks FAILED without zeroing pending -> the next
cycle pays again.

## F36 — crypto webhook signature can be DISABLED in production · HIGH
api/payments.py:426-436  verify = os.getenv("CRYPTO_WEBHOOK_VERIFY","true") != "false"
The production fail-closed branch lives INSIDE _verify_webhook_hmac (:375-383),
which is never reached when verify is False. With CRYPTO_WEBHOOK_VERIFY=false any
unauthenticated caller can POST {"payment_id":...,"status":"complete"} and be
granted a paid plan (:483-489). The docstring at :373 claims production is enforced.

## F37 — crypto webhook never validates the amount received, nor expiry · HIGH
Handler reads only status/confirmations/tx_hash (:457-459). Expected amount_crypto /
amount_usd are persisted at :151-153 and never compared; expires_at (:157) never
checked. An underpayment reported "complete" grants the full plan.

## F38 — AML withdrawal gate is correct code on a DEAD path · HIGH
wallet.py:337-379 fails closed correctly, BUT debit_wallet/credit_wallet have zero
callers outside wallet.py. The only live withdrawal endpoint, api/payments.py:639
fiat_withdraw, does no balance check, no debit, and never touches the AML gate.

## F39 — wallet balance restore reads the wrong ledger row · HIGH
_load_balance_from_db (wallet.py:126-141) returns the latest balance_after for the
user REGARDLESS of wallet_type (notes carries the type but is not filtered on);
create_wallet then assigns it to subscription_balance and hard-codes
commission_balance = 0.00 (:171-172). After a restart a user whose last transaction
was a commission credit has their subscription balance overwritten and their entire
commission balance zeroed.

## F40 — second-resolution IDs collide, silently desyncing ledger from memory · HIGH
wallet.py:282,:393 and compliance.py:92 build IDs as TXN-/AML-%Y%m%d%H%M%S.
WalletTransaction.transaction_id is unique=True (database/models.py:756). Two
transactions in the same second -> uniqueness violation swallowed by
except Exception: logger.error (wallet.py:119-120) -> in-memory balance moves with
NO ledger row. api/payments.py:184,:588 already fixed this class with UUIDs;
wallet and compliance were missed.

## F41 — early renewal TRUNCATES paid time · MEDIUM-HIGH
activation.py:246-248  existing.end_date = now + timedelta(days=duration_days)
Assignment, not extension. Renew with 12 days left -> those 12 days are lost.

## F42 — refund rounding creates/destroys a cent · MEDIUM
revenue_split.py:216-217 sale uses ROUND_HALF_UP; :268,:270 refund omits rounding=
(defaults ROUND_HALF_EVEN) AND recomputes the fee instead of reusing
orig.platform_fee. Sale+full refund leaves the creator 1c short, permanently, per
refunded transaction.

## F43 — no double-entry invariant; enforce_ledger_reconciliation is not on any write path · MEDIUM
WalletTransaction (models.py:750-765) is single-entry. The only production caller of
enforce_ledger_reconciliation is health_check_service.py:442, whose own docstring
says "Read-only — never gates trading". Its inputs are also wrong: opening and
closing are both the SAME current snapshot (:437-438), so the identity cannot hold
once any deposit exists -> a permanent CONSTITUTIONAL violation operators learn to
ignore. verify_double_entry exists (invariants/reconciliation.py:63) with no caller.
CONNECTS TO MY F18: this is one of the 7 inert enforce_* wrappers.

## F44 — Flutterwave tx_ref is deterministic, so renewals silently no-op · MEDIUM
api/billing.py:620-623 tx_ref = "FLW-" + sha256(user:plan:amount:currency)[:24] —
no nonce, no period. Next month's renewal produces the identical tx_ref, the verify
endpoint short-circuits on the cached record (:666-673) and returns
{"verified":true,"idempotent":true} WITHOUT collecting payment or re-activating.

════════ EXECUTION AGENT (3 of 8 done) — 20 findings, top ones re-verified by me ════════

## F45 — *** NO WORKING STOP-LOSS: broker never gets one, and the local monitor is dead *** · CRITICAL
RE-VERIFIED BY ME, EMPIRICALLY. Two independent halves, both confirmed:

(a) No broker-side stop is ever placed.
    execution/trade_executor.py:409-414 calls place_market_order(symbol, side,
    quantity, client_order_id) — stop_loss/take_profit are NOT passed; they are
    only written onto the local Position object at :466-467.
    brokers/base.py:554-560 discards them even when passed, and says so:
      "bracket SL/TP not applied at entry (per-broker); they are logged and ignored"
    execution/engine.py:1336-1343 likewise omits them from _po_kwargs.

(b) The compensating local monitor throws on its first position, forever.
    hopefx_engine.py:475-479 (inside HopeFXEngine.start()) constructs
      ExecutionEngine(position_manager=self._position_tracker)   <- a PositionTracker
    execution/engine.py:430-437 then starts SLTPMonitor(position_manager=that).
    sl_tp_monitor.py:194 positions = self._pm.get_all_positions()
    sl_tp_monitor.py:202 `if pos.position_id in self._closing:`   <- AttributeError
    Proven by running it:
        PositionTracker.get_all_positions : exists, returns list[Position]  (:149)
        Position has .id                  : True
        Position has .position_id         : False
        reading pos.position_id           -> AttributeError
    The monitor's own comment at :200 says "get_all_positions() returns
    dict[str, Position]" — that is PositionManager's signature (:538), not
    PositionTracker's (:149, returns a list). It was written for a different class.
    sl_tp_monitor.py:181-184 _loop catches it: logger.error(...) then sleeps and
    retries every poll. So it fails silently-ish forever, at ERROR level, with no
    alert and no halt.
    _close_position would also TypeError: it calls self._pm.close_position(symbol=,
    fill_price=) but PositionTracker.close_position takes (position_id, exit_price,
    commission) (:95).

CORRECTION TO THE AGENT: it claimed "in the app.py/container path the SL/TP monitor
does not exist" because core/startup_factories.py never constructs an
ExecutionEngine. That is wrong — startup_factories.py:2941 init_trading_engine()
constructs HopeFXEngine INSIDE the API process, and line 475 sits inside
HopeFXEngine.start(), so the monitor IS constructed and started there. The monitor
exists; it is simply dead on arrival because of the attribute mismatch. Same
outcome, different mechanism — worth stating correctly.

NET: an open position has no broker stop and no functioning local stop watcher.
Loss is bounded only by margin call.
Severity: CRITICAL.

## F46 — risk_approval_token is carried but never verified · HIGH (agent-reported)
Minted at risk/manager.py:1017 as f"rat-{lineage_id}". Read in exactly three
places, all pure truthiness: trade_executor.py:355-372, oms.py:196-207,
smart_router.py:549-558, all feeding enforcement.py:573 `if not _get(...)`.
No issued-token registry, no binding to symbol/side/qty/notional, no expiry, no
single-use consumption, no signature. Any non-empty string authorizes any order.
S1-05 removed the manufactured constant from TradeExecutor, but the check it feeds
is still unfalsifiable in substance — a stale or foreign token passes identically.
COMPOUNDING (agent): trade_executor.py:378 derives decision_id FROM the token
immediately before enforcement checks decision_id is non-empty — so the
"No Hidden Decision" half is unfalsifiable at that call site too.
AND (agent): HOPEFXDecisionEngine.py:553/:595 stores the token as INSTANCE state,
so two decisions in flight on one engine carry the wrong symbol's token.

## F47 — a gate REJECTION triggers the bypass · CRITICAL (agent-reported)
hopefx_engine.py:1519-1527: when SmartRouter returns
{"status":"rejected","reason":"unauthorized:..."} from enforce_order_authorization,
the caller logs "SmartRouter rejected — falling back to direct order" and then
calls self._broker.place_order(**order_kwargs) DIRECTLY, with no gate.
The sr_request built at :1493-1506 carries no risk_approval_token and no
decision_id, so under enforce mode it is rejected by construction.
=> the constitutional gate's refusal is the trigger for bypassing it.

## F48 — router "unknown" (timeout) is classified as success · CRITICAL (agent-reported)
execution/smart_router.py:616-620 deliberately returns status="unknown" on timeout
so the caller will reconcile rather than assume. hopefx_engine.py:1509 tests
`status not in ("rejected","error")` — "unknown" passes. :1530 then reads
result.get("fill_price", exec_price), and the key is absent, so the REQUESTED price
is booked as the fill. The branch written to prevent an unverified position is the
branch that creates one.

## F49 — large orders silently void; a phantom full-size position is booked · CRITICAL (agent-reported)
smart_router.py:217 wires self._algo.set_broker_submit_fn(self._submit_child_order).
_submit_child_order is (self, child_order_dict: dict) — one positional param, no
**kwargs. algo_orders.py:256-266 calls it with symbol=, side=, quantity=,
order_type=, metadata= -> TypeError, which is not caught by :299 or :814, so the
algo task dies on its first child. Meanwhile _route_via_algo returned
{"status":"algo_submitted"}, which hopefx_engine.py:1509 treats as a fill.
=> orders >= ALGO_LARGE_ORDER_THRESHOLD (default 10.0) are never sent anywhere, and
the system books a full-size position it does not hold. Closing that phantom later
sends a REAL opposite-side market order.

## F50 — cancel never reaches the broker · HIGH (agent-reported)
oms.py:334-340 cancel_order() only transitions to PENDING_CANCEL. Nothing in the
repo transitions PENDING_CANCEL -> CANCELLED and nothing calls the broker to cancel.
A "cancelled" partially-filled order stays live at the broker forever.
Related: OCO _cancel_siblings (:457-468) relies on this, so BOTH legs of an OCO can
fill; and bracket exits created by _place_bracket_exits (:497-529) are never
submitted at all — TP and SL sit in CREATED forever.

## F51 — FIX adapter discards every fill after the first report · HIGH (agent-reported)
fix_adapter.py:1063-1064 pops the pending future on the FIRST ExecutionReport of any
non-REJECTED ExecType — including NEW ("0") and PARTIAL_FILL. Real FIX sessions send
ExecType=0 first, so send_order returns filled_qty=0 and all subsequent reports are
discarded at :1066-1071 as "unsolicited exec report" (debug level).

## F52 — order idempotency is effectively absent · HIGH (agent-reported)
client_order_id is minted fresh per call (trade_executor.py:405) — a correlation id,
not an idempotency key. It never reaches the broker anyway: brokers/base.py:562-568
drops it. TradeExecutor._pending_orders (:131) is read at :1045 but NEVER WRITTEN.
self._lock (:133) is not taken in _execute_open. Neither router carries a dedup key.

## F53 — crash recovery never reconciles ORDERS against the broker · HIGH (agent-reported)
redis_state.py load_state_on_boot() is a pure Redis read — no broker call in the
file. Position reconciliation exists (position_manager.py:639) but only diffs
positions; persisted orders are never compared to the broker's open orders.
audit_order_intents() (:661) only LOGS orphans at CRITICAL (:684-698) — never
cancels, adopts or flattens. Its only handle is client_order_id, which per F52 was
never transmitted, so its own instruction "Verify against the broker" cannot be
executed. Under --mode engine PositionTracker is in-memory only: no persistence,
no reconciliation at all.

## F54 — timeout re-routing holes (agent-reported)
Both routers' PRIMARY leg is correct (returns unknown, does not re-route). Holes:
  brokers/smart_router.py:195-214 fallback loop wraps _execute_with_timeout in a
    bare `except Exception: continue` — a TimeoutError on fallback #1 advances to #2.
  execution/smart_router.py:598-602 any non-"filled" result — the comment names
    "partial" — re-routes the FULL quantity to the next broker.
  execution/smart_router.py:621-624 ConnectionError/RuntimeError after the write is
    treated as confirmed failure and re-routed.
  hopefx_engine.py:1328-1332 an ExecutionEngine TimeoutError -> status ERROR ->
    "falling back to direct" -> resubmits. Duplicate fill.

## F55 — OMS state-machine defects (agent-reported)
  :291-293 a broker TIMEOUT is recorded as REJECTED; OrderStatus has no UNKNOWN
    member and VALID_TRANSITIONS has no unknown sink. A live order is recorded as
    refused, so the strategy resizes as flat and resubmits.
  :307-332 fill_order mutates filled_quantity/avg_fill_price FIRST, then
    _transition rejects PARTIALLY_FILLED -> PARTIALLY_FILLED (not in the table at
    :127) and returns False. Quantity silently absorbed, no event, no history record
    for fills 2..N of a multi-fill order.
  :342-349 expire_orders: PARTIALLY_FILLED -> EXPIRED is illegal so _transition
    returns False, but active_orders.discard() runs UNCONDITIONALLY. A live
    partially-filled resting order becomes invisible to the OMS.
  :148-153 create_order always transitions CREATED -> CREATED (illegal), so every
    creation logs "Invalid transition" and writes NO order_history record.
  :488-494 create_bracket registers a GLOBAL FILLED callback closing over that
    bracket's prices; after M brackets any single fill fires all M callbacks.
CONNECTS TO MY F17: I found the invariant table is MORE permissive than the OMS.
These are cases where the OMS table is too STRICT for its own code paths — the two
tables are wrong in opposite directions.

## F56 — ExecutionEngine.execute() has no authorization gate at all · HIGH (agent-reported)
ExecutionRequest (engine.py:140-153) has no risk_approval_token and no decision_id
field, and grep for "enforce_" in execution/engine.py returns only the docstring.
The path hopefx_engine.py calls the "canonical execution path" (:471) enforces
PreTradeGate but never the No-Unauthorized-Trade invariant.
Also :1382 an unrecognised broker status defaults to SUBMITTED, which counts as
success -> a "successful" report with filled_quantity=0 is booked as an open
position at exec_price.

## F57 — conflicting k8s enforcement defaults (agent-reported, extends my F3/F10)
k8s/k8s-configmap.yaml:40 sets HOPEFX_INVARIANT_MODE "enforce";
deployments/k8s/configmap.yaml:14 sets "monitor".
A SECOND k8s configmap I had not found. In monitor mode enforcement.py:249-252
returns allowed=True unconditionally, so every gate in F46/F47/F56 logs and permits.

## F45-SCOPE — the dead SL/TP monitor is LIVE IN THE DEFAULT PAPER CONFIG (verified by me)
core/startup_factories.py:2975-2982:
    mode = os.getenv("TRADING_MODE", "paper").lower()
    if mode == "live":
        autostart = ENGINE_AUTOSTART=="true" AND LIVE_TRADING_ENABLED=="true"   # both default false
    else:
        autostart = os.getenv("ENGINE_AUTOSTART", "true") == "true"             # DEFAULT TRUE
=> In the DEFAULT configuration (TRADING_MODE unset -> "paper"), ENGINE_AUTOSTART
   defaults to "true", so HopeFXEngine.start() runs, ExecutionEngine is built, and
   SLTPMonitor is started — and then throws AttributeError on every poll for every
   open position. The failure is happening today in any paper deployment that holds
   a position; it is visible as a repeating "SLTPMonitor._loop error" at ERROR level.
   Flipping to live does NOT fix it — the same dead monitor is what a live position
   would rely on.
The asymmetry itself is good design: live requires TWO explicit flags, paper does not.

## S11-02 ANSWERED — "the two flags that gate unsafe trading" are:
    ENGINE_AUTOSTART        (default "true" in paper, must be "true" for live)
    LIVE_TRADING_ENABLED    (default "false"; required for live in addition)
core/startup_factories.py:2977-2979. Backlog S11-02 says they are undocumented —
worth confirming against .env.example / DEPLOYMENT.md in the CI audit.
Note these are DISTINCT from the other live gates already logged:
    FEATURE_LIVE_TRADING  (core/live_trading_gate.py:79)
    LIVE_MODE_CONFIRMED   (execution/engine.py:46)
    TRADING_MODE, BROKER_TYPE
=> at least SIX separate env vars participate in "is this thing allowed to trade",
   across four modules, with different defaults. That surface is itself a finding.

## F58 — ENGINE_AUTOSTART is undocumented and defaults to TRUE · MEDIUM-HIGH (verified)
grep across .env.example, .env.production.example and DEPLOYMENT.md:
    LIVE_TRADING_ENABLED  -> documented (.env.example:198)
    ENGINE_AUTOSTART      -> DOCUMENTED NOWHERE
CORRECTION TO MY OWN NOTE: it has TWO defaults in the same function —
    :2977 live branch  getenv("ENGINE_AUTOSTART", "false")   conservative, good
    :2982 paper branch getenv("ENGINE_AUTOSTART", "true")    autostarts by default
The mode-dependent default is sound design (live is conservative). The finding is
purely that the flag is undocumented, i.e. the flag that
decides whether the trading engine starts at all is invisible to an operator reading
the env templates. This is the concrete, still-open half of backlog S11-02.

## F59 — ALL THREE stop-loss mechanisms are non-functional in the production path · CRITICAL
Traced to the end, each verified:

  1. BROKER-SIDE SL/TP — explicitly discarded.
     trade_executor.py:409-414 never passes stop_loss/take_profit.
     brokers/base.py:554-560 discards them when passed and says so in the docstring.
     execution/engine.py:1336-1343 also omits them.

  2. SLTPMonitor — started, then throws on every poll.
     Reached in the live path (hopefx_engine.py:475 inside start(), autostarted by
     default in paper per F45-SCOPE). Handed a PositionTracker; reads
     pos.position_id at sl_tp_monitor.py:202; PositionTracker's Position has .id.
     AttributeError, caught by _loop, logged at ERROR, retried forever.

  3. IntraTradeMonitor — the 200ms SL/TP poller docs/architecture.md advertises.
     Constructed ONLY at execution/hopefx_engine.py:177.
     execution/hopefx_engine.py is imported ONLY by execution/execution.py:263.
     execution/execution.py is imported by NOTHING in production — the only two
     grep hits are a string in scripts/e2e_production_validation.py:524 and an
     unrelated attribute access (execution.execution_id) in transparency/engine.py:132.
     => it sits two hops behind a module nothing calls.

CORRECTION TO MY OWN F20: I wrote that execution/hopefx_engine.py is "imported only
by tests". That was wrong — execution/execution.py:263 imports it. The conclusion is
unchanged (no production consumer) but it takes one more hop than I said, and I
should not have stated the stronger claim.

ROOT CAUSE — 12 distinct classes named Position in production code, with
incompatible identity fields:
    execution/position_tracker.py:23   -> .id
    execution/position_manager.py:118  -> .position_id
    brokers/base.py:212                -> .id
    portfolio/pms.py:24                -> no id field at all
    + database/models.py, brokers/__init__.py, backtesting/{engine,enhanced_engine}.py,
      api/graphql_schema.py, forward_test.py, core/types.py, core/domain_models.py
Any function typed "takes a Position" is ambiguous. F45 is one realized instance.
BOUNDED: hopefx_engine.py:478 is the ONLY site passing a PositionTracker into a
position_manager= parameter, so this specific confusion has exactly one occurrence.
risk/intra_trade_monitor.py reads .position_id in 9 places but uses its OWN
OpenPosition type, so it is internally consistent — it is simply unreachable.

Severity: CRITICAL. An open position in the production path has no stop of any kind.

════════ BROKER AGENT (4 of 8 done) — 22 findings; top 4 re-verified by me ════════

## F60 — *** trade_executor.py:416 CRASHES ON EVERY NON-PAPER BROKER, AFTER THE FILL *** · CRITICAL
PROVEN BY RUNNING IT:
    MarketOrderResult.status type = <class 'str'>
    r.status.value -> AttributeError: 'str' object has no attribute 'value'
brokers/base.py:539,573 place_market_order returns MarketOrderResult;
its `status` field is annotated `str` (:363).
execution/trade_executor.py:416  `if order.status.value in ("filled","partial"):`
This line is OUTSIDE any try block.
Paper survives only because paper_trading.py:1064 OVERRIDES place_market_order and
returns a raw Order whose status IS an enum. Every BrokerConnector-derived live
broker (MT5Connector, IBKRConnector, Alpaca, Binance, ByBit, CCXT, CME, CPPShim)
raises here.
FAILURE CHAIN — and it compounds with F59:
    order submitted -> FILLS at the broker
    -> AttributeError unwinds at :416
    -> add_position() (:445) never runs        => position invisible to the tracker
    -> _clear_intent() (:462) never runs       => intent journal left dirty
    -> notify_position_opened() never runs     => risk manager never sees it
    -> and per F59 no stop of any kind is armed
=> a filled live position the system does not know it holds, with no stop.
Severity: CRITICAL.

## F61 — the live OANDA broker cannot place an order through TradeExecutor · CRITICAL
PROVEN BY RUNNING IT:
    OANDABroker.place_market_order exists: False
    OANDABroker.get_order          exists: False
    is BrokerConnector subclass:    False
core/startup_factories.py:1153-1155 wires brokers.oanda.OANDABroker as app.broker.
execution/trade_executor.py:409 calls self.broker.place_market_order(...).
=> AttributeError before any order is built. The stated next milestone (live OANDA)
cannot place a single order through this path.
Severity: CRITICAL.

## F62 — paper_trading.py:1064 INVERTS the side when handed an OrderSide enum · HIGH (latent)
PROVEN: str(OrderSide.BUY) == 'OrderSide.BUY'; .lower() == 'orderside.buy';
not in ("buy","long") -> resolves to SELL.
The sibling at paper_trading.py:683 gets it right — its tuple includes
"ORDERSIDE.BUY". So the two methods in the SAME FILE disagree.
SCOPING CORRECTION TO THE AGENT (it called this CRITICAL and live): the main path
does NOT trigger it. execution/trade_executor.py:224 sets `side = signal["action"]`
— a lowercase str — and :449 confirms (`"long" if side == "buy"`). A str "buy" is
handled correctly. The bug fires only for a caller passing the enum, which is the
ABC's DECLARED type (base.py:534 `side: "OrderSide | str"`). So: real, proven, and
a live trap for any correct-by-the-signature caller — but not currently inverting
the executor's trades. Downgraded CRITICAL -> HIGH (latent).

## F63 — no unit/lot/contract conversion layer anywhere · CRITICAL (agent-reported)
hopefx_engine.py:1453-1463 sends the SAME risk-sized quantity as OANDA "units"
(troy oz) or MT5 "lots" (100 oz). risk/manager.py:175 aliases lot_size and size to
the same float. mt5.py:237 "volume": float(quantity); cme_comex.py:301 says
"quantity is in contracts (1 = 100 oz)" and _CME_MULTIPLIER is used only for
notional REPORTING (:175), never to convert the incoming size.
=> risk sizes 30 oz; BROKER_TYPE=mt5 submits 30 LOTS = 3,000 oz ~ $7.2M notional.
100x over-size. Same for CME contracts and ibkr_broker.py CONTFUT/GC.
NOT YET RE-VERIFIED BY ME — high priority to confirm.

## F64 — brokers/__init__.py:1087 is S13-03 UN-FIXED in a shadow OANDABroker · CRITICAL (agent-reported)
    units = quantity if side == "buy" else -quantity     # strict lowercase
then :1091 str(int(units)) truncates, and :1110 OrderSide(side) raises ValueError
for "BUY" AFTER the order has already filled.
`brokers.OANDABroker` resolves to THIS class, not brokers.oanda.OANDABroker.
=> side="BUY" opens a SHORT at OANDA, then ValueError propagates and the caller
believes the order failed. Inverted AND phantom.
CONNECTS TO MY F20/F21 (duplicate classes): a third same-name collision.

## F65 — OandaBroker / MT5Broker signatures cannot be called by the router · CRITICAL (agent-reported)
oanda_broker.py:237 place_order(self, order_params: dict) but manager.py:379 and
base.py:556 call place_order(symbol=, side=, order_type=, quantity=).
Agent verified: TypeError: missing a required argument: 'order_params'.
manager.py:206-213 registers this class as "oanda" and :247-266 puts it in the
FAILOVER chain. => IBKR primary drops, failover selects OANDA, every order raises
TypeError, nothing is placed. Same defect at mt5_broker.py:183 (symbol_or_params).

## F66 — six connectors compare side by IDENTITY while a competing OrderSide exists · HIGH
brokers/__init__.py:49 OrderSide values "buy"/"sell"; brokers/base.py:149 "BUY"/"SELL".
Identity comparisons `side == OrderSide.BUY` at mt5.py:218, mt5_broker.py:212,
ibkr_connector.py:523, interactive_brokers.py:181, ccxt_connector.py:159,
cme_comex.py:430 all fall through to SELL for the wrong class.
Currently no production module imports brokers.OrderSide — ONE import away from a
repeat of S13-03. hopefx_engine.py:1443-1450 documents this exact mechanism, yet
the duplicate enum survives.

## F67 — the kill switch reports positions closed that are still open · HIGH (agent-reported)
brokers/base.py:518-522 treats any truthy return as a successful close.
ibkr_connector.py:679 returns True WITHOUT checking the close order;
ccxt_connector.py:242 and alpaca.py:361 likewise; ibkr_broker.py:431 returns a
dict, so {"success": False} is truthy and counts as closed.
And TWO connectors can never close at all: cpp_shim_connector.py:287-290 returns
False unconditionally; cme_comex.py:372-380 returns False whenever IBKR is absent.
Both are registered in factory.py:129-146, so the kill switch can select them and
then be unable to flatten.
=> drawdown breach fires the kill switch, logs "closed XAUUSD", positions stay open.
COMPOUNDS F59: no stop, and the last-resort flatten reports false success.

## F68 — no close_position anywhere returns a closed QUANTITY · HIGH (agent-reported)
Every connector returns bool or dict. A partial close is indistinguishable from a
full one at the connector boundary — and the executor already assumes full (my F45
notes trade_executor.py:770 reports filled_quantity=position.quantity).
mt5.py:404 close_volume = quantity or position.volume applied PER TICKET: closing
0.5 with two open tickets closes 0.5 from EACH; quantity=0.0 silently means
"close everything".

## F69 — oanda_stream.py:336 truncates units to zero (the live hopefx_engine path) · HIGH
str(int(signed_units)) — int() not round(), and no zero guard, unlike oanda.py:146-165
which RAISES on rounding to zero. 0.9 oz -> "0" -> OANDA rejects UNITS_INVALID ->
:358-360 swallows it and returns None. 3.9 oz silently becomes 3.

## F70 — a timed-out OANDA order is reported as REJECTED · HIGH (agent-reported)
oanda.py:456-458 after retries returns {"status":"rejected","reason":"max_retries:timeout"}.
The order may have filled. brokers/smart_router.py:165-172 explicitly refuses to do
this ("a timeout is NOT a confirmed failure"); oanda.py does it anyway.
=> caller sizes the next signal as flat and doubles the position.

## F71 — CME_PAPER_FALLBACK defaults to TRUE · HIGH (agent-reported)
cme_comex.py:131; connect() :269 sets connected = fix or ibkr or paper_fallback;
place_order :314 routes to _place_paper.
=> BROKER_TYPE=cme with no FIX credentials reports CONNECTED, publishes
connected=True, and the executor books SIMULATED fills as real positions and P&L.

## F72 — fabricated equity=0.0 in connectors, which base.py:315-325 forbids · MED-HIGH
ccxt_connector.py:269 and :272 (the latter INSIDE except, so a transient exchange
error reports zero equity), cme_comex.py:332-338, cpp_shim_connector.py:267-273.
ibkr_connector.py:686 correctly RAISES instead — that is the right pattern.
CONNECTS TO MY F16 (the $100k fabricated default): same rule, opposite direction —
0.0 fails safe for sizing but misreports the account.

## CLEAN (agent verified, worth recording): no hardcoded secrets, no credential
defaults, no tokens in URLs, no credentials logged, and NO TLS bypass anywhere in
brokers/ (grep for verify=False / ssl=False / CERT_NONE returns nothing). All auth
via Authorization headers. Every BrokerConnector subclass has __abstractmethods__
== () — zero NotImplementedError in brokers/.

## F63-VERIFIED — the unit confusion is real, and it is bounded at 10 · CRITICAL (re-verified by me)
Chain, every line confirmed:
  risk/manager.py:992   quantity = final_notional / mid_price
                        final_notional is USD, mid_price is USD/troy-oz
                        => quantity is TROY OUNCES.
  risk/manager.py:171-176  `size` and `lot_size` are BOTH `return self.quantity`
                        — the same number exposed under two unit names.
  risk/manager.py:1302-1306  clamps quantity to _executable_lot_ceiling(), and the
                        log line calls the result "lots":
                        "clamped %.4f -> %.4f lots to stay inside the order
                         validator's max_qty"
  risk/manager.py:67-91 that ceiling is ORDER_MAX_QTY, else
                        OrderValidatorConfig().max_qty, else 10.0.
  hopefx_engine.py:1453-1465  dispatches the SAME `quantity`:
                        OANDAStream -> {"units": quantity}     (ounces — CORRECT)
                        everything else -> {"lots": quantity}  (100 oz each — WRONG)
  mt5.py:237            "volume": float(quantity), docstring says "1.0 = standard lot"
  cme_comex.py:301      "quantity is in contracts (1 contract = 100 troy oz)";
                        _CME_MULTIPLIER is used only for notional REPORTING (:175).

So the value is computed in ounces, clamped against a ceiling the code labels
"lots", exposed under both names, then interpreted as ounces by one broker and as
lots/contracts by the others. 1 XAUUSD lot = 100 oz => 100x.

BOUNDING — the agent did not note this, and it matters:
the clamp caps quantity at 10.0 by default, so the worst case is 10 "lots" =
1,000 oz ~= $1.9M notional, not an unbounded blowup. On $100k equity that is still
~19x leverage from a sizing routine whose own cap is 5% of equity.
COMPOUNDS F49: 10.0 is ALSO the default ALGO_LARGE_ORDER_THRESHOLD, so a size at
the ceiling routes into the algo path that dies on a TypeError while the caller
books a phantom position.
Severity: CRITICAL (bounded). The root defect is that no unit is ever named in a
type — `quantity: float` means ounces here and lots there.

## F73 — the anti-drift import is broken, so the lot ceiling IS the restated constant · HIGH (found + verified by me)
risk/manager.py:88   from validation import OrderValidatorConfig
validation.py:41     class ValidatorConfig:        <-- the real name
                     :47  max_qty: float = 10.0   # "Maximum lot size"
There is no OrderValidatorConfig anywhere in validation.py. The import ALWAYS fails.
Proven by running it:
    DEBUG risk.manager: could not read OrderValidatorConfig.max_qty
        (cannot import name 'OrderValidatorConfig' from 'validation') — using 10.0
    _executable_lot_ceiling() = 10.0
So the function always takes its `except` branch and returns the hardcoded 10.0,
at DEBUG level, invisibly.
Its own docstring states the purpose it is failing to serve:
    "Read its limit rather than restating the number, so the two cannot drift into
     disagreeing — which is exactly what had happened (see the clamp in
     calculate_position_size)."
The mechanism written to prevent a drift regression is broken, silently, and has
restored exactly the condition it was added to remove. Benign TODAY only because
both constants happen to be 10.0; the moment an operator edits
ValidatorConfig.max_qty, the risk manager will not see it and the clamp diverges
from the validator that rejects the order — the original bug, back.
ORDER_MAX_QTY still works (it is checked before the import), so the env override
is the only path that currently propagates.
ALSO CONFIRMS F63's unit confusion from the other side: validation.py:47 documents
max_qty as "Maximum lot size", while risk/manager.py:992 computes the value it
clamps as troy OUNCES. The ceiling and the quantity are in different units.
Severity: HIGH (latent regression + confirms the unit mismatch).

## F64-CORRECTED — the shadow OANDABroker S13-03 inversion is REAL but DEAD CODE · MEDIUM (latent)
The agent rated this CRITICAL. The defect is exactly as described, and I confirmed
every part of it by running it:
    brokers.OANDABroker is brokers.oanda.OANDABroker  ->  False   (two classes, one name)
    brokers/__init__.py OrderSide values              ->  ['buy','sell']
    brokers/base.py     OrderSide values              ->  'BUY'/'SELL'
    "BUY" == "buy"                                    ->  False
      => brokers/__init__.py:1087  units = quantity if side == "buy" else -quantity
         with side="BUY" yields units = -quantity  => a SELL when a BUY was meant
    OrderSide("BUY")                                  ->  ValueError: 'BUY' is not a
         valid OrderSide   — and :1110 raises this AFTER the HTTP POST has filled
    :1091 str(int(units))                             ->  truncates (0.9 -> "0")
So all four sub-defects are genuine: inversion, truncation, post-fill ValueError,
and a duplicate class name.

BUT IT IS UNREACHABLE. Traced every path:
  - No production module does `from brokers import OANDABroker`.
    ml/pnl_reconciler.py:521 explicitly imports `from brokers.oanda import OANDABroker`
    — the CORRECT one.
  - The only construction site is brokers/__init__.py:1251, inside a MODULE-LEVEL
    function `create_broker(broker_type, config)` at :1236.
  - That module-level create_broker has NO production caller. Every grep hit is
    `BrokerFactory.create_broker` — a classmethod on brokers/factory.py:35, a
    different function that production actually uses
    (hopefx_engine.py:592,594,1483; core/startup_factories.py:1207).
=> S13-03 survives verbatim in a code path nothing calls.
Severity: CRITICAL -> MEDIUM (latent landmine). Still worth removing: two classes
named OANDABroker, and a module-level create_broker whose name shadows the intended
BrokerFactory.create_broker, so one wrong import reactivates a known-catastrophic bug.

## RUNNING TALLY OF MY CORRECTIONS TO AGENT SEVERITIES
  F62 paper-broker side inversion   CRITICAL -> HIGH (latent)
        real, but trade_executor passes a lowercase str which is handled correctly
  F64 shadow OANDABroker inversion  CRITICAL -> MEDIUM (latent)
        real, but the only constructor has no production caller
  F63 unit confusion                CRITICAL, BOUNDED at 10 (agent missed the clamp)
  F45 SL/TP monitor                 mechanism corrected — the monitor IS started,
        it is dead on an AttributeError, not absent as the agent claimed
  F59 stop-loss                     UPGRADED — traced all three mechanisms, all dead
  F73 broken anti-drift import      NEW, found by me, not any agent
Pattern: agents are excellent at finding the defect and unreliable at reachability.
Every severity claim needs the call-graph traced before it is believed.

════════ API AUTHORIZATION — done by me (the agent died on quota) ════════

## F74 — API AUTHZ ON STATE-CHANGING MONEY/ORDER ENDPOINTS IS CLEAN · NO FINDING
AST sweep over all of api/ (986 routes parsed). Filtered to STATE-CHANGING
(POST/PUT/DELETE/PATCH) endpoints whose path or handler name matches
order|trade|withdraw|payout|transfer|deposit|kill.?switch|risk|retrain|promote|
subscri|entitle|balance|wallet|affiliate|cancel|position|leverage:

    state-changing + sensitive           : 65
      guarded by Depends() injection     : 65   (100%)
      guarded ONLY by an in-body check   : 0
      no auth detected at all            : 0

=> Answers the "dependency injection vs forgettable in-body check" question:
   it is dependency injection, everywhere, on every sensitive write endpoint.
   That is the robust pattern — a new endpoint cannot silently omit it the way a
   manual `if user.role != ...` can be forgotten.
Spot-checked the two scariest by hand, both correct:
   api/gateway.py:219  POST /api/v1/emergency/kill-switch
       Depends(self.security) + self._verify_token(..., required_role="superadmin")
   api/gateway.py:229  POST /api/v1/orders
       Depends(self.security) + self._verify_token(..., required_role="trader")

## MY OWN FALSE POSITIVE — recorded so it is not repeated
My FIRST sweep reported 18 sensitive endpoints "without auth", including
POST /api/v1/emergency/kill-switch and POST /api/v1/orders. That was MY bug:
the auth dependency is `Depends(self.security)`, and my AUTH_HINT regex matched
(user|role|admin|auth|superadmin|token|require|kyc|plan|api_key) — none of which
appear in the string "self.security". Widening the pattern to include
security|credential|bearer|http dropped the false positives to zero.
I caught this by reading the two flagged endpoints before reporting them. Had I
relayed the first run, I would have told the user their kill switch was
unauthenticated. Exactly the failure mode I have been correcting in the agents.
LESSON: a detector's negative result is only as good as its pattern list. Always
read a sample of what it flags before believing the count.

## REMAINING API QUESTIONS — NOT YET ANSWERED (agent died before reaching them)
  - IDOR: endpoints taking user_id/account_id/affiliate_id from body/query without
    binding to the authed caller. api/monetization.py:1525 affiliate withdraw is the
    known money endpoint to check.
  - WebSocket auth on connect + per-channel authorization (api/ws_live.py + 33 files)
  - SQLi / path traversal / SSRF / unsafe pickle / CORS / secrets in logs
  - GET endpoints that leak (my sweep filtered to state-changing only, deliberately)

## F75 — IDOR on money endpoints: CLEAN · NO FINDING (verified by me)
AST sweep: state-changing sensitive endpoints taking an explicit *_id path/body
param = 5. All 5 carry an ownership binding. Hand-read the money one rather than
trusting the regex (my earlier false positive taught me not to):
  api/monetization.py:1526 POST /affiliate/{affiliate_id}/withdraw
      async def withdraw_affiliate_commission(affiliate_id, request,
                                              user = Depends(get_current_user)):
          """Owner-only: this moves commission money, and `affiliate_id` came
             straight from the path with no ownership check."""
          _assert_affiliate_owner(affiliate_id, user)      <-- first statement
  The docstring documents the historical bug it fixes.
  Others: /sub-accounts/{account_id}/transfer, /affiliate/{id}/payment-method,
          /subscription/{id}/cancel, /copy/{trader_id} — all bound.
IMPORTANT DISTINCTION: this does NOT neutralise F32 (affiliate TOCTOU double-pay).
Ownership binding stops someone ELSE draining your commission; it does nothing
about the OWNER firing two concurrent withdrawals of their own balance. Authz is
clean; concurrency is not. Two different properties.

## F76 — WebSocket auth: CLEAN and fails closed · NO FINDING (verified by me)
api/ws_live.py:98   WS_AUTH_REQUIRED defaults "true"
api/ws_live.py:101-105  if APP_ENV == production and not WS_AUTH_REQUIRED:
                            raise RuntimeError(...)
    -> a hard failure at MODULE IMPORT. Production cannot start with WS auth off.
    The comment states the stake plainly: "all WS data (prices, signals, account
    updates) would otherwise be broadcast to unauthenticated connections."
Connect flow (ws_live at :1670): origin check first (_reject_ws_bad_origin, close
4403) -> connection cap rejected with 1008 BEFORE accept() -> accept + "connected"
-> _ws_auth_gate requires an auth message within AUTH_TIMEOUT_SECONDS or closes
4001 -> "auth_ok" with user_id -> heartbeat miss limit closes 1001.
api/community_chat.py:507 uses the same WS_AUTH_REQUIRED default.

## F77 — injection / deserialisation / CORS sweep: CLEAN · NO FINDING (verified by me)
Across api/ + auth/ + security/:
    raw SQL f-string / % / concat in execute()   0
    unsafe yaml.load                             0
    SSRF (request to a user-supplied url var)    0
    eval( / exec(                                0 REAL — all 4 hits are false
        positives: a docstring saying "no eval() or exec()"
        (api/advanced_trading.py:698), a comment in security/self_healer.py:378,
        and TWO YARA MALWARE RULES in security/antivirus.py:366,381 that contain
        "eval(base64_decode" and "exec(compile(" as detection strings.
    shell=True                                   0 REAL — all 4 hits are `# nosec`
        comments whose text says "no shell=True, no user input".
    pickle.load                                  1, api/superadmin/ml_ai.py:452,
        annotated "path-confined local model file".
CORS (api/server.py:156-169, :314-321):
    ALLOWED_ORIGINS env, default http://localhost:3000, split on comma — never "*".
    allow_credentials=True with an explicit origin list, explicit method and
    header allowlists.
    PRODUCTION HARD-FAIL: :162-169 sys.exit(1) if APP_ENV=production and every
    origin is still localhost/127. — refuses to boot misconfigured.
api/gateway.py:102 pins ["https://hopefx.com","https://app.hopefx.com"].

## API DOMAIN VERDICT (done by me; the agent died on quota twice)
authz on 65/65 sensitive write endpoints ....... CLEAN (dependency injection)
IDOR binding on 5/5 id-taking money endpoints .. CLEAN
WebSocket auth ................................. CLEAN, fails closed at import
SQLi / SSRF / yaml / eval / shell / CORS ....... CLEAN
The perimeter is well built. Every serious defect found this session is INSIDE it:
execution (F59/F60/F61), ML inference (F24), money concurrency (F31/F32/F34).
Still not covered: GET-only endpoints (my sweeps filtered to state-changing), and
the ~22 `except: pass` handlers in ws_live.py.

## F78 — LLM code execution: a REAL RCE surface, correctly gated OFF · NO FINDING (verified by me)
brain/llm_agent.py generates strategy Python from a model and CAN exec() it.
The code names its own risk with unusual precision (:85-91):
    "_compile_strategy ultimately exec()s model-produced Python *in this parent
     process* (the subprocess step only smoke-tests instantiation; the strategy
     object is needed in-process for backtesting). The AST denylist is the
     parent's only protection and a denylist cannot stop dunder-traversal escapes
     (e.g. ().__class__.__bases__[0].__subclasses__() reaching os without
     importing it). In a money-moving system this path must be OFF by default and
     only enabled deliberately in an isolated research/dev context."
Gate: :92 LLM_CODE_EXECUTION_ENABLED defaults "false".
Enforcement VERIFIED at :464 — the FIRST statement of _compile_strategy:
    if not _LLM_CODE_EXEC_ENABLED:
        return (None, "LLM code execution is disabled...")
It returns before ast.parse. Fails closed.
Defence in depth present but explicitly acknowledged as insufficient on its own:
an AST denylist (_ast_sandbox_check at :430) blocking eval/exec/open/__import__/
subprocess/importlib/tempfile and attribute-based os.system/os.popen, plus a
subprocess smoke test.
ASSESSMENT: this is the most self-aware security code in the repository. The author
identified the exact escape their mitigation cannot stop, wrote it down, and turned
the feature off by default rather than trusting the denylist. Correct handling.
NOT A FINDING.

## F79 — ARCHITECTURE.md overstates the LLM sandbox · LOW (doc)
ARCHITECTURE.md "Security Fixes Applied (v1.18)" #1 reads:
    "LLM sandbox subprocess isolation | brain/llm_agent.py"
That phrasing implies the model-generated code runs isolated in a subprocess.
The code says otherwise, in its own words: the exec happens "in this parent
process" and "the subprocess step only smoke-tests instantiation".
A reader trusting the doc would conclude the RCE surface is contained by process
isolation, and might therefore enable LLM_CODE_EXECUTION_ENABLED believing the
subprocess is the boundary. The doc should say what the code says: exec is
in-process, the denylist is the only parent protection, and the flag is the
real control.
Severity: LOW as a doc defect, but it misdescribes the one control that matters
on an RCE path.

════════ DATA/BRAIN AGENT (5 of 8) — 16 findings; top chain re-verified by me ════════

## F80 — *** A HEADLINE CONTAINING "coupon" OPENS A REAL SHORT ON GOLD *** · CRITICAL
VERIFIED END TO END BY RUNNING THE ACTUAL CODE.

Step 1 — the matcher is a bare substring test, no word boundaries:
  news/nuclear_wordmap_scorer.py:284   `if term in text_lower:`
  (punctuation is stripped to spaces first at :275-276)
  Terms that collide with ordinary English, with their real weights:
      "nuclear war" 10.0 (:49)   "coup" 7.0 (:90)   "depression" 7.5 (:167)
      "gold standard" 6.0 (:186) "risk off" 5.0 (:192)

Step 2 — I ran the real scorer. Output, verbatim:
  "Treasury coupon auction results beat expectations"  -> sev  7  hedge_mode   ['coup']
  "IAEA issues nuclear warning over inspections"       -> sev 10  nuclear_mode ['nuclear war']
  "Tropical depression forms off the Florida coast"    -> sev  8  hedge_mode   ['depression']
  "ETF seen as the gold standard of liquidity"         -> sev  6  pause        ['gold standard']
  "Markets in risk off mode ahead of data"             -> sev  5  pause        ['risk off']
  "Quiet session, gold drifts sideways"                -> sev  0  normal       []

Step 3 — hedge_mode places a REAL MARKET ORDER:
  brain/nuclear_supervisor.py:462-467  if rl_action == ACTION_HEDGE: await trigger_hedge_mode()
  risk/orchestrator.py:325-331
      result = await broker.place_order(symbol=symbol,
                                        units=-self._hedge_units,   # negative = short
                                        order_type="MARKET",
                                        label="NUCLEAR_HEDGE")

Step 4 — the substring path is the DEFAULT and the FALLBACK, not legacy-dead:
  news/geopolitical_llm.py gates the LLM replacement behind
  GEOPOLITICAL_LLM_EXTRACTION, "default OFF", and its own docstring says
  "With the flag off this class behaves exactly like NuclearWordMapScorer",
  and score_event_llm "falls back to the WORDMAP on any failure (no key, parse
  error, exception)". There is NO configuration in which the substring scorer is
  bypassed — off, it IS the scorer; on, it is still the fallback.

Step 5 — wiring: hopefx_engine.py:295 register_news_callback(supervisor.on_new_event);
  connect_to_life.py:426 also calls on_new_event. Live public news feeds.

NET: a routine fixed-income headline using the word "coupon", or an IAEA story
using "nuclear warning", or a weather story using "depression", opens an
unhedged-direction market short on XAU_USD — or trips the kill switch. The trigger
text arrives from public news, so it is both accident-prone and attacker-influenceable.
Severity: CRITICAL.
REMAINING UNCERTAINTY (stated honestly): I verified the callback registration and
the order call, but have NOT confirmed a live news provider is configured in the
default container, so I cannot say this fires today without a news key. The code
path is complete and unguarded; only feed configuration stands in front of it.

## F81 — hedge is marked ACTIVE before the order is attempted, and never rolled back · CRITICAL
risk/orchestrator.py, verified by reading:
  :318  self._hedge_active = True          <-- set BEFORE any broker call
  :325  result = await broker.place_order(...)
  :334-335  except Exception as exc: logger.error("Hedge order failed: %s", exc)
  :343-349  HedgePosition(..., order_id=order_id) appended REGARDLESS, order_id=None on failure
  :314-316  a retry returns early because _hedge_active is already True
=> If the hedge order fails, the system, its persisted state and its dashboards all
report "hedged" while the account is completely UNHEDGED — during the exact event
the hedge exists for — and no retry is possible.
Also: :341 when no broker is present it logs "Manual hedge required" and STILL
appends the HedgePosition, so the same false-hedged state is recorded.
Severity: CRITICAL.

## F82-F94 — remaining data-layer findings (agent-reported, NOT yet re-verified by me)
  #1  consensus weight = confidence/latency/spread; the inverse-spread term lets a
      feed quoting a 0.01 spread take ~96% of the weight and then evict honest
      feeds as "outliers" against a mean it dominates. Latency term is inert
      because _make_tick stamps datetime.now(UTC). CRITICAL if confirmed.
  #2  MIN_FEED_QUORUM defaults to 1 (manager.py:305) — a lone feed can drive execution.
  #3  3->2 feed loss changes confidence not at all; no gate observes it.
  #4  MIN_CONFIDENCE floor (0.30) EQUALS the is_safe_to_trade gate (<0.30), so with
      >=2 inliers the gate is mathematically unreachable.
  #5  SUSPECT ticks are never filtered from consensus; detect_arbitrage,
      compute_ml_anomaly_score, get_kalman_price, mark_source_stale have ZERO callers.
  #6  Jump filter never runs for the three 60s-poll feeds because _is_stale (>30s) is
      always true for them — and they are structurally excluded from consensus while
      still being published to Redis.
  #8  NuclearStreamer uses ONE global _last_price across all sources, so a single
      >5% divergent feed can silence the entire stream (alternating rejection).
  #9  RegimeRouter computes a confidence and never uses it; UNKNOWN routes to
      TrendFollowing. Two incompatible regime taxonomies (brain vs router).
  #10 Plan-gate key miss defaults to "starter" (fail-open on entitlement); the live
      brain path never passes user_plan at all, so only starter strategies ever run.
  #11a RL escalation has no upper clamp; _normalize_obs silently returns RAW obs on
      VecNormalize failure — obs the policy never saw in training.
  #13 execution/engine.py:687 `if orchestrator._started and not is_safe_to_trade()`
      — if start() raised partway, _started stays False and the ENTIRE safety gate
      is skipped. ml/inference_engine.py:1404 fails closed on the same condition.
  #14 Lee-Ready tie-break is `mid >= (bid+ask)/2` where mid IS the midpoint by
      construction — always True. Permanent synthetic buy pressure into ML features.
  #15 DQE docstring claims lineage writes; there are none. Rejections log at DEBUG.
  #16 cached tick confidence defaults to 1.0 on a missing field (latent).

## F82-VERIFIED — inverse-spread weighting lets ONE feed own 96% of the consensus · CRITICAL
Formula confirmed at data_layer/quality/engine.py:505-516:
    lat  = max(state.p95_latency(), 1.0)
    sprd = max(t.spread, 0.01)
    weights[src] = state.confidence / lat / sprd
I recomputed the normalised weights myself. Synthetic spread is 0.0002 x $2350 = $0.47
(data_layer/feeds/gold/base.py:296-325 synthesises it for every feed except GoldAPI):

  three honest feeds, all synthetic:        33.3% / 33.3% / 33.3%     <- correct
  one feed quoting a tight spread (0.001,
  floored to 0.01 by max(t.spread,0.01)):    2.0% /  2.0% / 95.9%     <- dominance

Then the outlier gate (engine.py:518-523, CROSS_SOURCE_MAX_DIFF = 0.003) is measured
against consensus_p1 — a mean the dominant feed already owns 95.9% of. So:
    an honest feed is EXCLUDED once divergence exceeds  0.313%
    the dominant feed is excluded only above           7.35%
and MAX_JUMP_PCT = 0.005 (0.5%/tick) means 7.35% is unreachable in one tick.
=> the gate evicts the HONEST sources and keeps the outlier. Excluded sources are
also penalised -0.02 confidence each tick (engine.py:523), so they degrade further.

Two readings, both real:
  ADVERSARIAL — a compromised/hijacked feed quoting a tight spread takes the
    consensus to its own price within one tick.
  NO ADVERSARY REQUIRED — GoldAPI is the only feed supplying REAL bid/ask
    (feeds/gold/goldapi.py:71-77); an honest tight quote in a thin session gives it
    ~96% of the weight by accident.
There is NO cap on any single source's normalised weight anywhere in the function.
Severity: CRITICAL. VERIFIED BY MY OWN COMPUTATION.

## F83-VERIFIED — the confidence gate is unreachable with >=2 sources · HIGH (with a correction)
data_layer/quality/engine.py:59   MIN_CONFIDENCE = env DQE_MIN_CONFIDENCE, default 0.30
data_layer/quality/engine.py:195  self.confidence = max(MIN_CONFIDENCE, min(1.0, ...))
data_layer/orchestrator.py:1094   if tick.confidence < 0.30: return False
Every per-source confidence is clamped to >= 0.30; consensus is a weighted average
with weights summing to 1, so consensus >= 0.30; and 0.30 < 0.30 is False.
=> with >=2 inliers the gate can NEVER fire, however degraded every feed is.

CORRECTION TO THE AGENT: it wrote that the gate "can only ever fire via the
single-source x0.5 path" and implied 0.5 always passes. More precisely: the
single-source factor (DQE_SINGLE_SOURCE_CONF_FACTOR, 0.5) yields 0.15-0.50, so the
gate CAN fire on a single DEGRADED source (0.30 x 0.5 = 0.15 < 0.30) but not on a
single healthy one (1.0 x 0.5 = 0.50). The accurate statement is: the gate is
unreachable with >=2 sources, and reachable with exactly one source only once that
source has degraded to roughly 0.60 confidence or below.
Both thresholds are the same literal 0.30, so raising DQE_MIN_CONFIDENCE alone
would not help — it raises the floor and the gate together.

## F84-VERIFIED — the data-layer safety gate is skipped in exactly the condition it exists for · CRITICAL (proven by execution)
execution/engine.py:687, inside `_enrich_price_from_data_layer`:

    if orchestrator._started and not orchestrator.is_safe_to_trade():
        await self._inc_blocks()
        return self._blocked_report(request, "[DATA_LAYER] Unsafe trading conditions ...", t0)

The `_started` conjunct makes the whole gate a no-op whenever the data layer is
not running. That is not a rare state — it is the *normal degraded state*, and
it is produced by a code path that deliberately swallows the failure:

core/startup_helpers.py:95-116 `start_data_layer_orchestrator` is documented
"(non-fatal)". It wraps `orchestrator.start()` in
`asyncio.wait_for(..., timeout=ORCHESTRATOR_STARTUP_TIMEOUT_S default 60.0)`
and catches BOTH `TimeoutError` and bare `Exception`, logging each at
**warning** level and returning normally. The app then continues to serve and
to execute orders.

`_started = True` is set at data_layer/orchestrator.py:573 — the very END of
`start()`, after all ten feed-startup steps. So a timeout or a raise anywhere in
those ten steps leaves `_started` False permanently, with no retry.

PROVEN BY RUNNING IT (scratchpad/f13.py against the real singleton):
    fresh singleton _started = False
    is_safe_to_trade()       = False        <-- the check says UNSAFE
    gate expression blocked? = False        <-- but nothing is blocked
    ... after asyncio.wait_for(o.start(), timeout=0.001):
    after timeout, _started  = False
    gate blocked?            = False

So `is_safe_to_trade()` correctly reports unsafe and the caller discards that
answer. Every check the gate is supposed to enforce is bypassed:
  1. macro-event blackout window   (is_blackout_window)
  2. no live tick at all           (tick is None -> fail closed)
  3. tick confidence < 0.30
  4. gold feed with zero active sources for >30s

WHAT MAKES THIS A DEFECT RATHER THAN A DESIGN CHOICE — the sibling call sites of
the same function do not do this, and one of them says in a comment that failing
open here is wrong:
  * ml/inference_engine.py:1391-1407 — wraps it and on ANY failure to reach the
    orchestrator logs "failing CLOSED (not safe)" and returns False.
  * execution/hopefx_engine.py:392 — `if not self._orch.is_safe_to_trade():`,
    no `_started` guard at all.
  * data_layer/orchestrator.py:1089-1093 — inside the function itself, the
    author wrote "No tick means no live price — fail CLOSED: a missing tick must
    NOT be treated as safe to trade."
execution/engine.py:687 is the only call site that inverts that decision, and it
is the one on the order-placement path.

Severity CRITICAL: this is a risk-gate bypass on the execution path, reachable
by nothing more than a slow or unreachable feed at boot — the same condition
that makes trading unsafe is the condition that disables the check for it.

## F85-VERIFIED — the price-jump filter is 100% dead on three of the six gold feeds · HIGH (proven by execution)
The staleness threshold is shorter than three feeds' own poll intervals, so those
feeds are *by construction* always "stale" at the moment their next tick is
validated — and the jump check is gated behind not-stale.

    data_layer/quality/engine.py:53   STALE_THRESHOLD_S = 30.0   (DQE_STALE_THRESHOLD_S)
    data_layer/quality/engine.py:52   MAX_JUMP_PCT      = 0.005  (0.5%)
    data_layer/quality/engine.py:198  is_stale() -> (time.time() - last_tick_ts) > 30 and last_tick_ts > 0
    data_layer/quality/engine.py:331  _is_stale = state.is_stale()
    data_layer/quality/engine.py:334  if state.last_mid > 0 and not _is_stale:   <-- jump check

    data_layer/feeds/gold/manager.py:52-59  _POLL_INTERVALS
        GOLDAPI 5.0 | METALS_DEV 10.0 | YAHOO 5.0
        METALS_API 60.0 | METALPRICEAPI 60.0 | COMMODITY_API 60.0

`state.last_tick_ts` is not written until engine.py:448 — long AFTER the jump
check at :334. So when tick N is validated, `last_tick_ts` still holds tick N-1's
arrival time, which for a 60-second feed is always ~60s old. 60 > 30, so
`_is_stale` is True on every tick after the first, and the guard at :334 is never
satisfied. This is not intermittent: for METALS_API, METALPRICEAPI and
COMMODITY_API the jump filter never executes at all.

PROVEN BY RUNNING THE REAL ENGINE (scratchpad/f6.py) — identical DataQualityEngine,
identical tick sequence, only the cadence differs:

  60-second cadence (the real METALS_API interval):
    t=+  0s mid= 3300.0 -> quality=good     conf=1.000  jump_count=0
    t=+ 60s mid= 3301.0 -> quality=stale    conf=0.981  jump_count=0
    t=+120s mid= 3302.0 -> quality=stale    conf=0.962  jump_count=0
    t=+180s mid= 9999.0 -> quality=stale    conf=0.943  jump_count=0   <-- +203%, ACCEPTED
    t=+240s mid= 3303.0 -> quality=stale    conf=0.924  jump_count=0

  5-second cadence, same engine, same jump:
    t=+ 15s mid= 9999.0 -> quality=rejected conf=0.000  jump_count=1   <-- REJECTED
    ("DQE jump detected source=metals_api jump_pct=2.0282 mid=9999.00 prev=3302.00")

A 203% move passes on the slow feeds and is rejected on the fast ones. Note the
bad tick is not caught by the sanity bounds either: MAX_GOLD_PRICE is 10000.0
(engine.py:63), so 9999 is in range — and the realistic corruptions (a decimal
shift, a stale cached quote, a provider returning silver) sit comfortably inside
500..10000 too.

The rationale comment at :325-330 is sound in itself — after a genuine silence
gap the pre-gap `last_mid` is a bad baseline. The defect is that the code cannot
distinguish "this feed went silent" from "this feed polls slower than the
staleness threshold", so a normal, healthy, on-schedule 60s feed is permanently
treated as recovering-from-a-gap.

SECOND-ORDER EFFECT (different duty cycle — stated separately because it is NOT
100%): three other places filter on `not is_stale()` and evaluate it at their own
call time, not inside validate_tick:
    engine.py:596-597  best_source()      — highest-confidence non-stale source
    engine.py:661      generate_report()  — the `active` source list
    engine.py:671      the reconstructed last_known_ticks fed to cross_source_consensus
For a 60s feed, `is_stale()` is False for the 30s following each tick and True for
the next 30s. So these three sources flicker in and out of consensus and out of
best_source on a ~50% duty cycle, and the consensus composition changes every 30
seconds with no price having moved. Combined with F82 (inverse-spread weighting),
a feed dropping out of the consensus set redistributes its weight abruptly.

Severity HIGH: the jump filter is one of only two defences against a corrupt
price entering the consensus (the other is the 500..10000 bounds check, which is
far too wide to catch a plausible bad quote), and it is switched off on half the
feeds by an interaction between two constants that were plainly chosen
independently. Non-obvious from reading either file alone.

## F86-VERIFIED-WITH-CORRECTION — the Lee-Ready quote rule is degenerate, but the agent's "always True" is wrong · MEDIUM
data_layer/microstructure/engine.py:617-625:

    if self._last_mid > 0:
        if mid > self._last_mid:      is_buy = True
        elif mid < self._last_mid:    is_buy = False
        else:
            # Quote rule: trade at or above mid = buy
            is_buy = mid >= (tick.bid + tick.ask) / 2
    else:
        is_buy = True   # first tick — assume buy

THE AGENT SAID this is "always True — permanent synthetic buy pressure". The
first half is right in substance, the quantifier is not. Measured, not reasoned:

Every tick that reaches this code has bid/ask synthesised symmetrically around
mid, so (bid+ask)/2 is mid *up to 4-decimal rounding*:
  * data_layer/feeds/gold/base.py:309-325 `_make_tick` —
      bid = mid - mid*spread_pct/2, ask = mid + mid*spread_pct/2, each round(...,4)
    Used by commodity_api, metalpriceapi, metals_api, metals_dev, yahoo.
    GoldAPI is the one feed that passes real bid/ask (goldapi.py:77).
  * data_layer/feeds/gold/manager.py:334-344 — the CONSENSUS tick, which is the
    only tick the microstructure engine ever sees (see F87), is built as
      bid = round(consensus_mid - half_spread, 4)
      ask = round(consensus_mid + half_spread, 4)
      mid = round(consensus_mid, 4)
    — symmetric again.

MEASURED (scratchpad/f14b.py, replicating the synthesis exactly):
    realistic gold, 2dp quotes (3200-3400)   True  88.41%
    realistic gold, 4dp quotes               True  87.49%
    wide range 1000-4000, 2dp                True  88.53%
The independent rounding of bid and ask makes (bid+ask)/2 land a hair above mid
about one time in eight, so the branch is ~88% buy, not 100%.

That correction does not rescue the code. A tie-break is supposed to be
informative; this one is comparing a number to itself plus float noise. It
carries no information about trade direction at all — it is 88/12 noise dressed
as microstructure. Combined with the `is_buy = True` first-tick default, the
buy/sell split fed to `buy_pressure`, OFI and the 16 ML features
(engine.py:209-224, :752 `buy_pressure = buy_vol/total`) is biased long by
construction whenever consecutive mids are equal — and F87 shows equal
consecutive mids are the *common* case on this path, not the rare one.

Severity MEDIUM, downgraded from the agent's implied CRITICAL: it corrupts an ML
feature rather than bypassing a gate, and only on the tie branch.

## F87-VERIFIED — the microstructure engine, tick cache, lineage and WebSocket fan-out are driven by READS, not by the feed · HIGH (found while checking F86)
`MarketDataOrchestrator._on_tick` (data_layer/orchestrator.py:772) is the single
side-effect hub: it drives the microstructure engine (:787), the Redis tick
cache, the lineage store, every registered tick subscriber, and the WebSocket
broadcast queue.

It has EXACTLY ONE call site — orchestrator.py:767 — and it sits on the
cache-miss branch of `get_latest_tick`:

    def get_latest_tick(self, symbol="XAU_USD"):
        if self._redis_store._r:
            cached = self._redis_store.get_tick(symbol)
            if cached and -5.0 <= age_s <= 30.0:
                return tick                      # <-- _on_tick NOT called
        if self._gold_feed and _is_gold_symbol(symbol):
            tick = self._gold_feed.get_latest_tick()
            if tick:
                tick = self._norm.normalize_tick(tick)
                self._on_tick(tick)              # <-- the ONLY invocation
                return tick

Verified there is no producer-side path in:
  * `GoldFeedManager` holds no callback and no orchestrator reference at all
    (grep for callback/_subscribers/orchestrator in manager.py: only two
    comment matches, no code).
  * `_uptime_loop` (orchestrator.py:668-690) only sets a Prometheus gauge and
    writes a health blob to Redis. It never reads a tick.
So nothing pushes. The feeds poll into `_latest`/`_consensus_tick` and stop there.

CONSEQUENCES, in order of severity:
1. With Redis HEALTHY, `_on_tick` fires only once the cached tick has aged past
   30s — so the microstructure history advances at most ~2/minute, and only if
   somebody happens to ask for a price. The engine needs 10 ticks before it
   returns anything but zeros (engine.py:216-217), i.e. ~5 minutes of *demand*,
   not of market time.
2. With Redis DOWN, `_on_tick` fires on EVERY read. The tick history then
   measures how often callers poll, not how often the price changed — and
   concurrent readers append the *same* consensus tick repeatedly. Those
   duplicates are exactly `mid == self._last_mid`, which is the degenerate
   quote-rule branch in F86. The two defects compound: the more readers, the
   more synthetic buy ticks.
3. The tick history is therefore irregularly sampled in both modes, while OFI,
   `buy_pressure` and the rolling statistics computed over it all assume an even
   tick stream.
4. The same applies to the WebSocket broadcast and the lineage record: a client
   watching the live feed is served whatever the cache-miss pattern produced.

Severity HIGH: 16 features that reach the ML pipeline are computed over a
sampling process determined by cache behaviour and request volume. This is not a
crash — it is silent, and it would look like a plausible feature series in any
downstream inspection.

## F88 — the strategy plan gate: the agent got the direction right and the path wrong · CORRECTED (proven by execution)
AGENT CLAIM #10: "Plan-gate key miss defaults to 'starter' (fail-open on
entitlement); the live brain path never passes user_plan at all, so only starter
strategies ever run."

Both halves are true *of `StrategyManager`*. Neither describes the production
path, because the object injected into the brain in production is not a
`StrategyManager`. Traced the call graph rather than trusting it:

`brain/brain.py:853` is the ONLY call site (verified by grep across the repo):
    signals = await asyncio.wait_for(
        self.strategy_manager.generate_signals(self.state.market_regime,
                                               self.price_engine), timeout=10.0)
Two positional args, no `user_plan`. But `self.strategy_manager` is duck-typed
and there are two different classes that can land there:

PATH 1 — the FastAPI production path. core/startup_factories.py:1744:
    strategy_manager = getattr(s, "strategy_brain", None)
    b.inject_components(..., strategy_manager=strategy_manager, ...)
`s.strategy_brain` is built by `init_strategy_brain` (:1513-1529) and is a
**StrategyBrain**, registering MA_Crossover, RSI, MACD, BB.
`strategies/strategy_brain.py` contains NO occurrence of "plan", "PLAN" or
"tier" anywhere — its `generate_signals(market_regime, price_engine)` (:495) has
no entitlement check of any kind.
=> On the real API path the tier gate does not fail open. It is ABSENT.
   `STRATEGY_PLAN_REQUIREMENTS` and the `_plan_satisfies` check at
   strategies/manager.py:606-614 are DEAD CODE in production — the only caller
   never holds a StrategyManager. A reader auditing manager.py would conclude
   tiers are enforced on signal generation; they are not enforced anywhere.

PATH 2 — the standalone engine. hopefx_engine.py:396-400:
    sm = StrategyManager()
    self._brain.inject(strategy_manager=sm)
    logger.info("StrategyManager injected into brain (%d strategies)", ...)
`preload_defaults` defaults to False (manager.py:465), so nothing is registered.
PROVEN (scratchpad/f10.py):
    hopefx_engine.py:398  StrategyManager()  -> strategies registered: 0
The engine injects an EMPTY strategy manager and announces it at INFO as
"(0 strategies)". `generate_signals` iterates `self.strategies.values()` over an
empty dict and returns []. The standalone engine generates no strategy signals
at all. This is the most consequential fact here and the agent did not report it.

PATH 3 — the degraded fallback. `init_strategy_brain` is registered
`required=False` (startup_factories.py:2699), so when it fails, :1797
`sm = s.strategy_brain or StrategyManager(preload_defaults=True)` yields a real
StrategyManager with three strategies. There the gate DOES fire, at the
`user_plan="starter"` default:
    TrendFollowing   starter        True
    MeanReversion    professional   False   <-- silenced
    Breakout         professional   False   <-- silenced
Two of three strategies are dropped, logged at `logger.debug` (manager.py:608),
i.e. invisible at the default log level.

THE FAIL-OPEN (agent's first half) is real and is LATENT:
    required = STRATEGY_PLAN_REQUIREMENTS.get(strategy.name, "starter")
A strategy whose name is absent from the table is granted to the lowest tier.
The names actually used elsewhere in the codebase do not match the table —
StrategyBrain registers "MA_Crossover", "RSI", "BB" while the table lists
"EMAcrossover", "RSIReversal", "BollingerBands" — so any future wiring of those
into a StrategyManager would key-miss and silently become free. It does not bite
today only because those objects never reach this function.

FOR THE RECORD, the whole table at `user_plan="starter"` (proven, f10.py):
    TrendFollowing/EMAcrossover/RSIReversal/Ichimoku -> True
    MACD/BollingerBands/Breakout/MeanReversion/Stochastic -> False
    SMC_ICT (enterprise) -> False        StrategyBrain (elite) -> False

Severity: HIGH for path 2 (an engine that silently generates no signals) and for
the dead-code gate (monetisation not enforced where the code says it is);
MEDIUM for the latent fail-open. NOT the "only starter strategies run in
production" the agent described — in production no tier check runs at all.

## F89-CORRECTED — NuclearStreamer's anomaly filter picks a winner by ARRIVAL ORDER, not by correctness · HIGH (proven by execution)
AGENT CLAIM #8: "NuclearStreamer uses ONE global _last_price across all sources,
so a single >5% divergent feed can silence the entire stream (alternating
rejection)."

The premise is right, the failure mode is not. There is no alternation and the
stream is never silenced. What actually happens is a permanent lock-out of every
source that disagrees with whichever source ticked first.

data_feed/nuclear_streamer.py:303-305 — note the asymmetry the author left:
    self._price_lock  = asyncio.Lock()
    self._last_price: float | None = None      # <-- ONE value, all sources
    self._anomaly_counts: dict[str, int] = {}  # <-- per source
    self._dedup_cache: dict[str, deque] = {}   # <-- per source
Everything else in this class is keyed by source. The price is not.

:654-668, inside `process_tick`:
    async with self._price_lock:
        if self._last_price is not None:
            pct_change = abs((price - self._last_price)/self._last_price)*100.0
            if pct_change > self.anomaly_jump_pct:      # default 5.0 (:262)
                self._anomaly_counts[source] += 1
                return          # <-- returns BEFORE updating _last_price
        self._last_price = price
Because the discard path returns before the assignment, a rejected source never
gets to move the baseline. The first source to tick sets `_last_price` and then
rejects every divergent source forever — and `_last_price` is never reset
anywhere (assigned only at :304 and :668, no timeout, no per-source expiry), so
the lock-in lasts for the life of the process.

PROVEN (scratchpad/f8b.py — two feeds 6% apart, jittered so dedup never fires):
    --- feedA (3300) ticks first (threshold anomaly_jump_pct=5.0%) ---
      feedA: 5/5 accepted
      feedB: 0/5 accepted
      _last_price=3300.44  anomaly_counts={'feedB': 5}
    --- feedB (3500) ticks first ---
      feedA: 0/5 accepted
      feedB: 5/5 accepted
      _last_price=3500.52  anomaly_counts={'feedA': 5}
Same code, same feeds, same prices — the only variable is which one arrived
first, and it fully determines which price the platform trades on.

WHY THIS MATTERS: the filter has no notion of which price is correct. If the
broken feed (a decimal shift, per-gram instead of per-ounce, a provider
returning silver) happens to connect first, it takes ownership of `_last_price`
and every *correct* feed is discarded as the anomaly, indefinitely, while the
stream keeps publishing the wrong price at full rate and looks perfectly healthy.
`_anomaly_counts` records the rejections per source, but nothing reads it to
decide the baseline was wrong.

METHOD NOTE (recorded because it nearly produced a wrong finding): my first
attempt fed each source the identical price repeatedly and measured 5 rejections
but `anomaly_counts == 1`. The discrepancy was the per-source dedup ring buffer
(:307-312) swallowing ticks 2-5 before they reached the anomaly check — not the
anomaly filter at all. Jittering the prices isolated the mechanism. Reasoning
alone would have reported the wrong cause.

Severity HIGH: a silent, permanent, order-dependent choice of which price feed
the whole nuclear stream trusts, with no way to observe it went the wrong way.

## F90-VERIFIED — four quality functions are dead, and the engine's own anomaly verdict is discarded by the consensus · MEDIUM
AGENT CLAIM #5, verified exactly as stated. Both halves hold.

(a) ZERO CALLERS anywhere in the repo (grep excluding .venv, definitions
    excluded from the match):
      data_layer/quality/engine.py:650  mark_source_stale()
      data_layer/quality/engine.py:699  get_kalman_price()
      data_layer/quality/engine.py:719  detect_arbitrage()
      data_layer/quality/engine.py:778  compute_ml_anomaly_score()
        — one caller, get_all_ml_anomaly_scores() at :832, which itself has
          ZERO callers. Transitively dead, including the sklearn
          IsolationForest path behind it.
    So the Kalman filter is computed on every tick (:361-363) and its smoothed
    price is never read by anything; the per-source ML anomaly features are
    accumulated on every tick (:428) and never scored; and there is no way for
    any operator or watchdog to mark a source stale, because the function that
    would do it is never called.

(b) SUSPECT TICKS ARE NOT EXCLUDED FROM CONSENSUS. engine.py:500:
        valid = {src: t for src, t in ticks.items()
                 if t.is_valid() and t.quality != TickQuality.REJECTED}
    TickQuality has four members (data_layer/types.py:62-66): GOOD, STALE,
    SUSPECT, REJECTED. Only REJECTED is filtered — GOOD, STALE and SUSPECT all
    enter the weighted consensus.

    SUSPECT is the verdict of the engine's three statistical detectors: Kalman
    innovation > 3 sigma (:366-370), rolling z-score (:429-435), and Mahalanobis
    distance > 6.0 (:412-418). When any of them fires, the ONLY consequence that
    survives is a confidence penalty of 0.01, 0.03 or 0.02 respectively.

    That penalty is negligible against the weighting in F82. The weight is
    `confidence / latency / max(spread, 0.01)`: the spread term alone varies the
    weight by two orders of magnitude, so a 0.06 confidence deduction (all three
    detectors firing at once, on a 1.0 baseline) barely moves a source's share.
    A source can be flagged anomalous by every detector the engine has and still
    carry the consensus.

Severity MEDIUM: no gate is bypassed, but roughly half of the DataQualityEngine
— the Kalman filter, the IsolationForest scorer, the arbitrage detector — is
computed or maintained on the hot path and never consulted by anything, and the
detectors that DO run have no effective authority over the price that results.
This is worth knowing before anyone cites "the DQE validates ticks" as a control.

## F91-CORRECTED — the RL nuclear supervisor: obs fail-open is real and live; the missing clamp is latent · MEDIUM
AGENT CLAIM #11a: "RL escalation has no upper clamp; _normalize_obs silently
returns RAW obs on VecNormalize failure — obs the policy never saw in training."

Both parts are literally true. Their weight is different from what the claim
implies, in opposite directions, so recording the corrected version.

(a) THE OBS FAIL-OPEN IS REAL AND LIVE. brain/nuclear_supervisor.py:303-319:
        if self._vec_normalize is None:
            return obs                                  # path 1
        try:
            ... return self._vec_normalize.normalize_obs(batched)...
        except Exception as exc:
            logger.debug("VecNormalize.normalize_obs failed (%s) — using raw obs")
            return obs                                  # path 2
    Path 1 is entered when `_load_vec_normalize` fails, which it does quietly
    (:293-301 logs a WARNING; :256-260 logs at DEBUG when the file is simply
    absent). Path 2 swallows ANY exception at DEBUG.
    The observation space is bounded — decoded from the committed artifact below
    as Box(shape=(7,), low=[0,0,-1,...], high=[1,5,1,...]) — and the policy was
    trained on VecNormalize-scaled inputs. Returning raw obs feeds the policy
    values it never saw, and nothing above the DEBUG line records that it
    happened. `predict()` does not validate bounds.

(b) THE MISSING UPPER CLAMP IS LATENT TODAY, and the agent did not credit the
    mitigation that makes it so. :392-397:
        if   severity >= 9: rl_action = max(rl_action, ACTION_NUCLEAR)
        elif severity >= 7: rl_action = max(rl_action, ACTION_HEDGE)
        elif severity >= 5: rl_action = max(rl_action, ACTION_PAUSE)
    These are a FLOOR. The RL agent can escalate above the rule-based decision
    but can never de-escalate below it, so an out-of-distribution observation
    cannot make the supervisor under-react at severity >= 5. That is correct,
    deliberate design and it bounds (a).

    The hazard is what happens if `rl_action` ever exceeds ACTION_NUCLEAR.
    `_execute_action` (:446-485) is an `==` chain — ACTION_NUCLEAR(3),
    ACTION_HEDGE(2), ACTION_PAUSE(1) — and everything unmatched FALLS THROUGH to
    the ACTION_NORMAL tail, which de-escalates `nuclear_level` when severity < 3.
    So an action of 4 at severity 9 would compute `max(4, 3) = 4`, match no
    branch, and be executed as "normal" — the severity-9 floor defeated by the
    very value it was meant to raise. Fails toward NORMAL, not toward NUCLEAR:
    the opposite of what "no upper clamp" suggests.

    NOT REACHABLE TODAY. I decoded the committed artifact rather than assuming
    (scratchpad, stubbing gymnasium to unpickle the spaces out of the .zip):
        ml/rl_models/nuclear_decision_ppo.zip
          action_space      = Discrete(n=4, start=0)
          observation_space = Box(shape=(7,), dtype=float32,
                                  low=[0, 0, -1, ...], high=[1, 5, 1, ...])
    Discrete(4) matches ACTION_NORMAL..ACTION_NUCLEAR and Box(7,) matches
    `_build_rl_observation`'s 7-dim vector (:329-345). Both artifacts are present
    and committed (nuclear_decision_ppo.zip, nuclear_decision_vecnorm.pkl).

(c) NOTHING VALIDATES THAT MATCH. `_load_rl_agent` (:225-244) calls
    `PPO.load(path)` and checks only that it did not raise — no assertion on
    action-space size or observation-space shape. A retrain that changed either,
    or a wrong file at the path, is undetected at load; the action-space case
    then lands in (b) and the obs-shape case raises inside `predict()` at :389,
    which sits in NO try/except within `on_new_event`. Given ml/rl_models/ is
    checksum-verified in CI (per CLAUDE.md) the drift risk is managed, but the
    code itself has no guard.

Severity MEDIUM: (a) is live but bounded by the severity floor; (b) and (c) are
latent and cheap to close (clamp with min(), assert the spaces at load).

## F92-VERIFIED — losing feeds is invisible to every downstream gate until only one remains · MEDIUM
AGENT CLAIMS #2 and #3, both confirmed; recording them together because they are
the same hole seen from two sides.

The consensus confidence (data_layer/quality/engine.py:551) is a weight-average
over the INLIERS, and the weights are renormalised to sum to 1 first (:547-548):
    norm_w2 = {s: w/total_w2 ...}
    conf    = sum(self._sources[s].confidence * norm_w2[s] for s in inliers)
Renormalisation is exactly what erases the source count. Losing a feed
redistributes its share among the survivors and leaves the number unchanged:
    3 healthy sources (confidence 1.0 each) -> consensus confidence 1.000
    2 healthy sources (confidence 1.0 each) -> consensus confidence 1.000
    1 healthy source                        -> consensus confidence 0.500
Only the explicit `len(inliers) < 2` branch (:558-560, factor
DQE_SINGLE_SOURCE_CONF_FACTOR=0.5) registers anything, and only at exactly one
source. A 3->2 loss — half the redundancy gone — produces no signal anywhere:
same confidence, no gate, no counter, no log.

And the single-source degrade that does fire is not enough to trip anything.
Per F83 the gate is `tick.confidence < 0.30` (orchestrator.py:1094); a lone
healthy source yields 0.500, which passes. Combined with
    MIN_FEED_QUORUM default 1 (feeds/gold/manager.py:305)
a single feed can drive execution end to end. The code says so itself, in the
comment at manager.py:297-304: "Default 1 preserves prior single-feed behaviour;
operators handling live capital should raise this to >= 2 so a lone source can
never drive execution."
That is an honest, documented default rather than a hidden bug — so #2 is a
RISKY DEFAULT, not a defect. It is recorded here because the deployment this
repo ships (prop_firm_mode.json enabled, live OANDA as the next milestone) is
precisely the "handling live capital" case the comment warns about, and nothing
in the startup path raises it or warns that it is 1.

## F93-VERIFIED — the DQE claims lineage writes it does not make; cached ticks default to full confidence · LOW/MEDIUM
AGENT CLAIMS #15 and #16, both confirmed.

(#15) data_layer/quality/engine.py:31, in the module docstring:
    "All decisions are logged with structured fields and written to the lineage store."
The file never imports or touches the lineage store. The only two occurrences of
"lineage" in the whole module are field copies — `lineage_id=tick.lineage_id` at
:474 and :868 — which propagate an id the DQE did not create and does not
persist. Every accept/reject decision it makes is logged and then gone.
Worse, the rejections are logged at DEBUG (`_reject`, :846-852) — invisible at
default log level. The one exception is the cross-source outlier exclusion at
:524, which does log at WARNING.
The lineage store that DOES exist is written from the orchestrator's `_on_tick`
— which per F87 runs only on the Redis cache-miss read path. So the "immutable
audit trail" records cache misses, not the tick stream, and contains no record
of a single DQE rejection.
Severity LOW as a defect, but it matters for anyone treating the lineage store
as the audit answer to "why did we trade on that price".

(#16) data_layer/orchestrator.py:721, rehydrating a tick from the Redis cache:
    confidence=cached.get("confidence", 1.0),
A cached entry missing the `confidence` key is rehydrated at FULL confidence —
the one value that passes every downstream gate unconditionally. The adjacent
lines show the author's own better instinct: `source` is required and raises if
absent (:709-711, "rather than labelling the tick with a fabricated origin"),
`spread` defaults to 0.0 and `lineage_id` to "". Confidence is the only field
that defaults to the maximally permissive value instead of the neutral one.
Latent: the writer currently always sets the field. It becomes live the moment a
cache entry is written by an older/newer version, by hand, or by any other
producer. Severity MEDIUM-latent; a one-word fix (default 0.0) makes it fail
closed like its neighbours.

## F94 — *** REGIME DETECTION NEVER RUNS, AND ITS UNUSED DEFAULT HALVES EVERY POSITION *** · HIGH (proven by execution)
AGENT CLAIM #9: "RegimeRouter computes a confidence and never uses it; UNKNOWN
routes to TrendFollowing. Two incompatible regime taxonomies (brain vs router)."

Every part is true, and following it to the sizing code turns it into something
much larger than a routing nit.

STEP 1 — `RegimeRouter.route()` IS NEVER CALLED. Grepping `\.route(` across the
repo (excluding .venv, tests, and the unrelated `research/pipeline` RegimeRouter
and `execution/order_algorithms.py` order router) leaves only
strategies/regime_router.py:27 — a usage example inside a docstring — and an
ASCII diagram in brain/hopefx_brain.py:28. Nothing invokes it.
`init_regime_router` (core/startup_factories.py:1793) builds the object and
stores it on app_state; `api/trading.py:3872-3875` reads `regime_history()` from
it. The detector itself is never run.

STEP 2 — so its state never leaves the constructor. :302-303:
    self._last_regime: str = REGIME_UNKNOWN   # "unknown"
    self._last_confidence: float = 0.0
`route()` (:316-318) is the only writer of both.

STEP 3 — that constant propagates into live position sizing:
    strategies/regime_router.py:397  status()["current_regime"] -> "unknown"
    core/regime_router.py            get_current_regime() reads status()
    core/signal_engine.py:1958-1963  regime_name = regime_result["regime"]
    core/signal_engine.py:1471       regime_scalar = get_regime_position_scalar(regime_name)
    core/signal_engine.py:175-181    return _REGIME_SIZE_MAP.get(name.upper(), 0.5)
    core/signal_engine.py:1472-1481  if regime_scalar < 1.0:
                                         scaled_size = sizing.recommended_size * regime_scalar
                                         return scaled_size

PROVEN BY RUNNING THE REAL OBJECTS:
    RegimeRouter fresh (route() is never called anywhere in the app):
       status()["current_regime"] = 'unknown'
       status()["confidence"]     = 0.0
    get_current_regime() -> regime = 'unknown'
    get_regime_position_scalar('unknown') = 0.5
    so signal_engine.py:1473  scaled_size = recommended_size * 0.5

EVERY position that goes through this path is sized at exactly HALF the size the
risk manager approved, permanently, and the log line at :1474 reports it as
"Regime-conditional sizing ... regime=unknown scalar=0.50" — which reads like the
feature working rather than a detector that never ran.

_DEFAULT_REGIME_SIZE_MAP (signal_engine.py:148-156) is entirely inert:
    TRENDING_UP 1.0 | TRENDING_DOWN 1.0 | MEAN_REVERTING 0.6 | RANGE_BOUND 0.5
    HIGH_VOL 0.3    | LOW_VOL 0.8       | UNKNOWN 0.5
Only the UNKNOWN row is ever selected. The 0.3 high-volatility de-risking that
this table exists to provide can never engage.

The direction is conservative — half size, not double — so this is not a runaway
risk. It is still a HIGH finding: a documented adaptive risk control is dead, its
protective branch unreachable, and the platform silently trades at half its
intended size while logging as if the control were live.

THE REST OF CLAIM #9, confirmed:
  * confidence is computed by `detect_regime` (:86-139, returns
    (label, confidence)), stored, logged and published in the REGIME_CHANGE
    event (:341) — but `_select_strategy(regime)` (:354) takes only the regime.
    Confidence never influences routing. A regime detected at 0.3 (the UNKNOWN
    fallback at :139) routes identically to one at 1.0. There is no minimum.
  * `REGIME_UNKNOWN: "TrendFollowing"` (:75), documented at :20 as the "safe
    default". Routing an unrecognised regime to a trend-following strategy is a
    directional bet, not a safe default. Moot today since route() never runs.
  * The taxonomy problem is bigger than "two". There are FIVE separate
    `MarketRegime` enums, none of which share members with the router's strings:
        ml/regime.py:44   brain/brain.py:44   analysis/market_analysis.py:56
        nocode/ml_nodes.py:65   backtesting/enhanced_engine.py:104
    plus the seven REGIME_* string constants in strategies/regime_router.py:49-55.
    Six taxonomies for one concept. Note `_REGIME_SIZE_MAP`'s keys match the
    router's strings (upper-cased) and NOT any of the enums — so even if a brain
    regime were routed into the sizing call, `.get(name.upper(), 0.5)` would miss
    and return the same 0.5 default. The fail-open default is what hides the
    mismatch.

================================================================================
AGENT 2 — CI / CONFIG / TEST INTEGRITY.  Findings F95-F118.
Every CRITICAL and every structural HIGH below was RE-VERIFIED BY ME before
being recorded; the verification is stated inline. Items I did not personally
re-run are marked (agent-reported, not re-verified).
================================================================================

## F95 — *** CI HAS NOT RUN ON main FOR AT LEAST 30 CONSECUTIVE PUSHES *** · CRITICAL (found by me, resolving the agent's UNVERIFIED question)
The agent could not determine whether ci.yml is actually enforced and correctly
said so. I queried the GitHub Actions API directly. The answer changes the
weight of every other CI finding in this section.

Last 30 ci.yml runs on main — `Counter({'failure': 30})`, an unbroken streak:
    2026-08-18T08:01:26  failure  #4042  6591f742     <-- most recent
    2026-08-14T19:51:34  failure  #4033  6258d6a1
    ... every run in between ...
    2026-08-13T18:26:42  failure  #3999  d235ff8d
Not one success in the returned window (total_count 3474 runs overall).

These are NOT test failures. Jobs for run #4042 (id 32114265315):
    test (3.11)       created 08:01:26  completed 08:01:28   failure
    test (3.12)       created 08:01:27  completed 08:01:29   failure
    dependency-scan / frontend / typecheck / pre-commit / build-cpp-shim
                      all created 08:01:27, all completed by 08:01:29, all failure
    e2e               skipped
Every job died within 2 seconds of creation. Fetching one directly:
    "id": 95640157674, "name": "test (3.12)", "conclusion": "failure",
    "runner_id": 0, "runner_name": "",
    "started_at": "2026-08-18T08:01:27Z", "completed_at": "2026-08-18T08:01:29Z"
NO RUNNER WAS EVER ASSIGNED. Not a single step executed. The signature —
instant failure across all jobs, no runner, no logs — is an account-level
rejection before scheduling (Actions spending limit / billing / Actions
disabled). The precise cause is UNVERIFIED: I cannot read billing settings.

WHY THIS IS THE HEADLINE. Combined with F96, the deployment path has been
running with ZERO test signal:
  * deploy.yml has no `needs:` and triggers on `push: branches: [main]`, so it
    does not depend on CI passing — and CI has not produced a result at all.
  * Every gate discussed in F97-F108 — the coverage thresholds, Gates A-L, the
    invariant check, pre-commit, typecheck — has been inert for at least five
    days of pushes to main.
So the correct reading of this whole section is not "these gates are weak". It
is "these gates have not executed", and the weaknesses below describe what would
still get through even once someone restores CI.
Severity CRITICAL. This is also the single most actionable item in the entire
audit: it is a settings fix, not a code fix.

## F96 — production deploys are gated on nothing · CRITICAL (verified by me)
.github/workflows/deploy.yml — read in full:
    on:
      push:
        branches: [main]
        paths-ignore: ["**/*.md", "docs/**", "diagnostics/**"]
      workflow_dispatch: {}
    jobs:
      deploy:
        name: SSH deploy
        runs-on: ubuntu-latest
        env: { VPS_HOST: ${{ secrets.VPS_HOST }} }
        steps:
          - name: Deploy over SSH
            if: ${{ env.VPS_HOST != '' }}
            uses: appleboy/ssh-action@v1.2.5
There is NO `needs:` and no `workflow_run` gate. The job races CI rather than
following it; per F95 there is no CI result to follow anyway. Any push to main
SSHes into the VPS and runs deployments/deploy.sh.

## F97 — the only unpinned action in the repo is the one holding the production SSH key · HIGH (verified by me)
Swept all 18 workflows for `uses:` lines not pinned to a 40-char SHA. Exactly
one result:
    deploy.yml:52   uses: appleboy/ssh-action@v1.2.5
Every other action across every workflow is SHA-pinned, most with an explicit
"pinned to SHA for supply-chain safety" comment. The single exception is the
step that receives `secrets.VPS_SSH_KEY` — the private key for the production
host. A floating tag can be re-pointed by the upstream owner or by anyone who
compromises that account.

## F98 — two ConfigMaps with the SAME NAME define contradictory safety settings; last apply wins · CRITICAL (verified by me)
    k8s/k8s-configmap.yaml:7-8          name: hopefx-config   namespace: hopefx
    deployments/k8s/configmap.yaml:4-5  name: hopefx-config   namespace: hopefx
Both Deployments mount it:
    k8s/k8s-deployment.yaml:76-78          envFrom: - configMapRef: name: hopefx-config
    deployments/k8s/deployment.yaml:28-30  envFrom: - configMapRef: name: hopefx-config
`kubectl apply` REPLACES `data` wholesale, so whichever file was applied last
defines the safety posture for both deployments.

What the two files actually say:
    k8s/k8s-configmap.yaml:33  OANDA_PRACTICE: "false"      <-- real money
    k8s/k8s-configmap.yaml:34  BROKER_TYPE: "oanda"
    k8s/k8s-configmap.yaml:39  # CRITICAL: HOPEFX_INVARIANT_MODE must be
                               #   "enforce" when BROKER_TYPE != "paper".
    k8s/k8s-configmap.yaml:40  HOPEFX_INVARIANT_MODE: "enforce"
    k8s/k8s-configmap.yaml:43  DRIFT_BLOCK: "true"
    k8s/k8s-configmap.yaml:46  STALE_MODEL_BLOCK: "true"

    deployments/k8s/configmap.yaml:14  HOPEFX_INVARIANT_MODE: "monitor"
    deployments/k8s/configmap.yaml     DRIFT_BLOCK      — ABSENT
    deployments/k8s/configmap.yaml     STALE_MODEL_BLOCK — ABSENT
Applying the second file last downgrades enforcement to `monitor` AND deletes
both ML safety flags, dropping DRIFT_BLOCK to its code default `false`
(ml/inference_engine.py:81) — i.e. trading on drifted models, with real-money
OANDA credentials, while the sibling file's own comment declares that
combination CRITICAL. One file states an invariant; the other silently voids it.

## F99 — the placeholder-secret test skips on precisely the case its docstring claims to catch · CRITICAL (verified by me, run)
tests/unit/test_placeholder_secrets_are_rejected.py:151-165. Docstring:
    "A new required secret added to .env.example with a placeholder is caught
     here rather than in production."
The body:
    src = inspect.getsource(... "config.startup_validator" ...)
    if f'"{name}"' not in src:
        pytest.skip(f"{name} is not read by the startup validator")
It greps the VALIDATOR'S SOURCE TEXT for the variable name and skips when
absent. But "the validator does not know about this secret yet" IS the new-secret
case. The guard inverts the property the test exists to assert.

RAN IT (`pytest tests/unit/test_placeholder_secrets_are_rejected.py -q -rs`):
    21 passed, 8 skipped
    SKIPPED  BOOTSTRAP_ADMIN_PASSWORD is not read by the startup validator
    SKIPPED  BOOTSTRAP_SUPERADMIN_PASSWORD ...
    SKIPPED  BOOTSTRAP_TRADER_PASSWORD ...
    SKIPPED  BYBIT_API_KEY ...      SKIPPED  BYBIT_API_SECRET ...
    SKIPPED  DB_ENCRYPTION_KEY ...  SKIPPED  GRAFANA_ADMIN_PASSWORD ...
    SKIPPED  POSTGRES_PASSWORD ...
Eight published placeholders — including the DATABASE ENCRYPTION KEY and the
Postgres password and three bootstrap admin passwords — are exempted from the
test written to reject them. A deployment shipping the published
`CHANGE_ME_generate_32byte_urlsafe_b64_key` produces a green skip.

## F100 — the shipped .env weakens the drawdown circuit breaker 3x · HIGH (verified by me)
    execution/trade_executor.py:62   DRAWDOWN_HALT_PCT = getenv("DRAWDOWN_HALT_PCT", "0.05")
    .env.example:1512                DRAWDOWN_HALT_PCT=0.15            <-- 3x weaker
    connect_to_life.py:100           DD_HARD_STOP_PCT  = getenv("DD_HARD_STOP_PCT", "0.03")
    .env.example:1511                DD_HARD_STOP_PCT=0.10             <-- 3.3x weaker
This is not hypothetical: DEPLOYMENT.md:210 instructs, verbatim,
    # Copy environment template
    cp .env.example .env
so the real deployment procedure installs the weaker values. The breaker that
halts trading fires after 15% of equity is gone instead of 5%.
The suite cannot see it: every test imports the constant and compares against
itself rather than asserting the number
(test_trade_executor_comprehensive.py:299, test_execution_coverage_boost.py:1711,
test_execution_coverage2.py:576 — agent-reported, not re-run by me).

## F101 — .env.production.example ships Redis TLS OFF and drops both ML safety flags · HIGH (agent-reported)
    .env.production.example:192  REDIS_FORCE_TLS=false
    .env.production.example      DRIFT_BLOCK, STALE_MODEL_BLOCK — both ABSENT
                                 (so DRIFT_BLOCK falls to its code default false)
scripts/ci/gate_l_safety_invariants.py rule L-6 requires REDIS_FORCE_TLS=true —
but Gate L reads only three files (.env.example, config/feature_flags.py,
ml/inference_engine.py, lines 42-127). It never opens .env.production.example,
docker-compose.yml, or either ConfigMap. The file named "production" is outside
the reach of the gate that checks production safety defaults.
STRUCTURAL CAUSE, and it explains F98/F100/F101 together: the only fail-closed
gate has a three-file blind spot, and tests/system/test_env_consistency.py:422
(`if ref.has_default: continue`) additionally exempts any var that HAS a code
default — i.e. exactly the safety flags.

## F102 — a boot-time migration fabricates trade direction and price · HIGH (verified by me)
alembic/versions/j1k2l3m4n5o6_trade_notnull_cascade.py:45-47, inside `upgrade()`:
    op.execute("UPDATE trades SET side = 'BUY' WHERE side IS NULL")
    op.execute("UPDATE trades SET entry_price = 0.0 WHERE entry_price IS NULL")
    op.execute("UPDATE trades SET entry_quantity = 0.0 WHERE entry_quantity IS NULL")
The comment calls 'BUY' "the safest neutral default for legacy rows where the
direction was not recorded". There is no neutral default for a trade direction:
a fabricated BUY at entry_price 0.0 is a fictional trade that will be counted by
every P&L, win-rate and drawdown computation that reads the table.

And it runs UNATTENDED AT EVERY CONTAINER BOOT (verified):
    Dockerfile:91          CMD ["bash","-c","scripts/preflight.sh && python app.py"]
    scripts/preflight.sh:181  if [ "${SKIP_MIGRATIONS:-false}" != "true" ]; then
    scripts/preflight.sh:205      timeout "${MIGRATION_TIMEOUT}" python3 -m alembic upgrade head
No operator prompt, no dry-run, no backup step. Correct handling would be to
fail the migration and make a human decide.
`SKIP_MIGRATIONS` is documented in Dockerfile:90 and preflight.sh:12 but appears
in NO env template (grep across .env.example, .env.production.example,
docker-compose.yml, k8s/, deployments/ returns nothing).

## F103 — coverage gates for brain/ and news/ CANNOT PASS · HIGH (verified by me, reproduced)
    .coveragerc [run] source = auth risk brokers execution market_data ml config
                               kill_switch compliance analytics backtesting core
`brain` and `news` are NOT in that list, so no data is ever collected for them.
But ci.yml gates on them anyway:
    ci.yml:432  coverage report --rcfile=.coveragerc --include="brain/*" --fail-under=70
    ci.yml:438  coverage report --rcfile=.coveragerc --include="news/*" --fail-under=70
REPRODUCED LOCALLY (ran a small suite under --cov, then the two gate commands
verbatim):
    --- brain/ gate (ci.yml:432) ---   No data to report.   exit=1
    --- news/ gate (ci.yml:438) ---    No data to report.   exit=1
Neither has `continue-on-error`. They fail every run in which they execute. Per
F95 they have not executed for at least 30 pushes, which is why nobody noticed.

## F104 — the job named "Coverage gate (>=70%)" contains no failure path · HIGH (verified by me)
tests.yml:500-595. The job has exactly four steps: checkout, download artifact,
extract percentage, post PR comment. There is no `exit 1` and no
`core.setFailed` anywhere in it. It renders a FAIL badge into a PR comment and
exits 0.
tests.yml:525-534 makes it worse:
    try:  ... parse coverage.xml ... print(f'{combined:.1f}')
    except Exception:  print('0.0')
A missing or corrupt coverage.xml renders "0.0%" — displayed as failing — and
still passes. (The real threshold that does block is `--cov-fail-under=70` at
ci.yml:373 / tests.yml:124.)

## F105 — the 80% gates measure the packages with the risk logic deleted · HIGH (agent-reported)
.coveragerc `omit` (:29-95) removes from the very packages the gates claim to protect:
    risk/       4,399 of 11,851 lines (37%) omitted — INCLUDING risk/manager.py
                (2,620 lines: the pre-trade gate, VaR/CVaR, Kelly sizing, kill
                switch — the file CLAUDE.md names as the risk core), plus
                pre_trade_gate.py, gatekeeper.py, post_trade_analyzer.py
    execution/  5,775 of 16,928 lines (34%) omitted — engine.py (1,621),
                fix_adapter.py (1,119), hopefx_engine.py (1,073)
    also omitted: core/decision/HOPEFXDecisionEngine.py (the 5-phase pipeline),
                  brokers/oanda*.py, brokers/interactive_brokers.py
"risk/ >= 80%" is therefore a true statement about the two thirds of risk/ that
is not the dangerous part. Cross-reference F106: trade_executor.py IS measured,
and its broken line 416 counts as covered.

## F106 — F60 CONFIRMED INDEPENDENTLY, plus a second break I had missed · CRITICAL
The agent reproduced my F60 (`order.status.value` → AttributeError, status is a
plain str per brokers/base.py:340) and found a SECOND defect on the same path
that I had not: `MarketOrderResult` exposes `order_id`, not `id`, so
`order.id` at trade_executor.py:438/447/467/496/501 also raises.
Reachable via BROKER_TYPE=alpaca|binance|bybit|ccxt|ibkr|cme — 13 connectors
inherit brokers/base.py:531-573 without overriding
(core/startup_factories.py:1042).

HOW IT SURVIVED 16,218 PASSING TESTS — three independent reasons, agent-verified:
  * tests/unit/test_trade_executor_comprehensive.py:33-37 builds the broker's
    order as a bare MagicMock() and hand-sets `order.status.value = "filled"`
    and `order.id`. A MagicMock returns a child mock for ANY attribute, so
    line 416 passes regardless of the real contract — and --cov counts it covered.
  * tests/unit/test_broker_connectors_conformance.py:68 asserts
    `r.status.lower() == "filled"` — i.e. asserts status IS a str.
  * ZERO test files import both TradeExecutor and MarketOrderResult/a real
    connector. Both halves are internally consistent; nothing tests the join.
This is the cleanest example in the audit of why coverage percentage is not
evidence: the line is covered, executed, and wrong.

## F107 — BROKER_TYPE=oanda cannot place an order · CRITICAL (verified by me, run)
brokers/oanda.py:681  `AsyncOANDAConnector = OANDABroker` — a bare alias.
PROBED AT RUNTIME:
    AsyncOANDAConnector -> <class 'brokers.oanda.OANDABroker'>
    issubclass(BrokerConnector) = False
    hasattr place_market_order  = False
    order-ish methods: ['_post_order_with_retry', 'cancel_order', 'place_order']
core/startup_factories.py:1154 wires this class in for BROKER_TYPE=oanda;
execution/trade_executor.py:409 calls `self.broker.place_market_order(...)`,
which raises AttributeError before an order is even constructed.
Live OANDA is the stated next milestone (CLAUDE.md) and k8s/k8s-configmap.yaml:33-34
already sets BROKER_TYPE=oanda with OANDA_PRACTICE=false.
brokers/oanda.py is in .coveragerc omit (:35), so no coverage gate touches it.
Corroborates and sharpens my F61.

## F108 — 14 of 37 tests in one file assert nothing, against a class that never existed · HIGH (agent-reported)
tests/unit/test_auth_analytics_backtest_coverage.py wraps whole test bodies —
assertion included — in `except (ImportError, AttributeError): pytest.skip(...)`
(e.g. :245-267). The agent verified `PerformanceAnalyzer` does not exist in
analytics/performance.py (the real class is `PerformanceAnalytics`, :173) and
that `git log -S "class PerformanceAnalyzer"` returns NOTHING — the name was
wrong in the first commit and every test referencing it has always skipped.
Silently unexercised: Sharpe ratio, max drawdown, VaR, portfolio metrics,
portfolio optimisation, Monte Carlo, execution handler, report generation.
analytics/ IS in .coveragerc source, so these skips suppress nothing visible.

## F109 — CI cannot run both halves of the broker guards in any single environment · HIGH (agent-reported)
requirements-ci.txt:9 excludes `ib_insync` ("no broker available in CI") while
requirements.txt:131 makes it a hard production dependency. Consequence: the only
two tests that construct an InteractiveBrokersConnector
(test_broker_connectors.py:1544, :1551) ALWAYS skip in CI — confirmed verbatim
`SKIPPED [1] ...:1544: ib_insync not installed`. Same for `quickfix` (the FIX
engine). And test_broker_sdk_guards.py:143 skips when the package IS installed,
so the two directions are mutually exclusive: no environment runs both.

## F110 — two mechanisms turn "the production app cannot boot" into green · HIGH (agent-reported; currently DORMANT — see F111)
  * scripts/runtime_invariant_check.py:733 exits 2 on "BOOT FAILED — app did not
    become ready (syntax/import/startup error)"; ci.yml:410-411 converts exit 2
    into `::warning` + `exit 0`. The one step whose job is to boot the app and
    assert behaviour treats "won't boot" as a pass. ci.yml:413's bare `exit 0`
    also swallows any code >= 3 (e.g. 137/OOM).
  * tests/integration/{test_api,test_api_routing,test_compliance_risk,
    test_invariants_endpoint}.py catch SystemExit on `from app import app` and
    `pytest.skip(allow_module_level=True)`. app.py:172 is
    `validate_environment(strict=True)  # calls sys.exit(1) on failure`, so a
    config regression that stops production booting silently empties the
    integration suite instead of failing it.

## F111 — measured skip reality, correcting our shared hypothesis · NOTE (agent-measured)
Full local runs:
  * tests/unit -m "not slow and not e2e": 1 failed, 16218 passed, 50 skipped,
    11 deselected (20m42s)
  * tests/integration + tests/system: 810 passed, 0 SKIPPED
So the module-level import guards in F110 are LATENT, not firing. The real
damage is a different pattern: guards that wrap the ASSERTION and catch
AttributeError, or that grep source text and skip on absence — F99 and F108.
Those do not protect against a missing dependency; they protect against the code
being wrong.
The 50 skips break down as: F99 (8), F108 (14), amtool not installed (6), torch
not installed (5), advanced_training_report.json absent (3), ib_insync (2),
MT5 package installed (2).
Two more worth naming:
  * test_risk_coverage.py:235,245 — "calculate_position_size signature differs",
    "kelly_criterion not exported". POSITION-SIZING tests self-disabling.
  * test_ml_inference_training.py:312 — "Insufficient data for walk-forward:
    Found input variables with inconsistent numbers of samples: [1, 500]" — a
    genuine sklearn shape error laundered into a skip.
The 1 failure is test_ml_training.py::TestXGBoostModel::test_predict_proba_shape,
`Timeout (>120.0s)` — hardware speed, not logic. Whether it fails on CI runners
is UNVERIFIED (and per F95, moot for now).

## F112 — five pairs of CI jobs share identical display names · MEDIUM (agent-reported)
tests.yml: `auth-coverage` (:189) and `gate-a-auth-coverage` (:603) both render
as "Gate A — auth coverage (all mutating routes)"; likewise Gates B/C/D/E. They
run different implementations (pytest vs scripts/ci/gate_*.py). Branch
protection matches required checks BY NAME, so which one is enforced is
ambiguous.

## F113 — the security workflows cannot fail the build · HIGH (agent-reported)
  * security-scan.yml — bandit (:37,:41), safety (:77,:78,:82), trivy (:129) all
    `|| true`; SARIF upload and TruffleHog `continue-on-error` (:138,:160).
    NOTHING in this workflow can fail the build.
  * codeql.yml:29,68,78 — continue-on-error on init AND analyze. CodeQL findings
    never block.
  * ci.yml:164-176 — mypy on api/, risk/, ml/ all `|| true`.
  * ci.yml:78 — `pip-audit ... || true` then a Python block whose
    `except: sys.exit(0)` (:301) treats a missing report as "no vulns". If
    pip-audit crashes, the gate passes silently.
  * codacy.yml:28,54 and docs.yml:32,66 — continue-on-error, documented as
    missing tokens / Pages not enabled. Not defects.
  * fortify.yml:23, jekyll-docker.yml:6 — workflow_dispatch only, deliberately
    disabled with explanatory comments. NOT defects.
  * lockfile.yml:4-6 — triggers on `push` to requirements.txt but NOT
    `pull_request`, so a PR changing deps never regenerates or validates the
    lock. Holds contents:write + pull-requests:write.
  * summary.yml:4 — issues:[opened] only; never runs on PRs.
  * quarterly_retrain.yml:248 — continue-on-error, documented as optional.

## F114 — Python version: packaging still advertises the untested 3.10 · MEDIUM (agent-reported)
Correct and consistent: Dockerfile:35 python:3.12-slim; ci.yml:186 and
tests.yml:36 matrix ["3.11","3.12"]; retrain.yml:88,172 and
quarterly_retrain.yml:125,175,229 all 3.12 — matching CLAUDE.md's pickle
requirement.
Two gaps:
  * ruff.toml:5 `target-version = "py311"` — lints against 3.11 while production
    runs 3.12.
  * pyproject.toml:31 `requires-python = ">=3.10"` + :22 classifier 3.10 — pip
    installs happily on 3.10, which NO workflow tests. This is the exact error
    CLAUDE.md documents as already corrected ("3.10 was tested by nothing"),
    still live in the packaging metadata.
release.yml:48,88 builds the sdist/wheel on 3.11 (pure-Python, no pickle impact).

## F115 — a downgrade that destroys every 2FA secret · MEDIUM (agent-reported)
alembic/versions/q1r2s3t4u5v6_widen_totp_secret_for_encryption.py:41-49. Its own
comment: "any encrypted values longer than 64 bytes will be silently truncated."
Upgrade widens users.totp_secret to TEXT for AES-GCM (~80 chars); downgrade
narrows it back to VARCHAR(64). Every secret written after the upgrade is
destroyed on rollback.

## F116 — no workflow ever runs `alembic downgrade` · MEDIUM (agent-reported)
ci.yml:291 runs `alembic upgrade head` only. scripts/ci/gate_i_migration_chain.py
validates revision LINKAGE, not reversibility. scripts/test_migrations.py:154-166
implements a full `downgrade base` -> `upgrade head` round-trip and is wired into
NO workflow. All 21 downgrade() bodies are untested, including F115.

## F117 — a second migration path that swallows failure · LOW (latent, agent-reported)
docker/entrypoint.sh:33  `alembic upgrade head || echo "Migration warning (continuing)"`
The app then starts on a half-migrated schema, contradicting preflight.sh's
hard-fail. Mitigating: referenced only by docker/Dockerfile:55, NOT the root
Dockerfile that production builds. Dead for the shipped image; a live trap if
anyone switches images.

## F118 — ENGINE_AUTOSTART undocumented, but the gating itself is correct · LOW (agent-verified, downgrades my F58)
Absent from .env.example, .env.production.example, docker-compose.yml and both
ConfigMaps; it appears only in this audit log. BUT the live gating is right:
startup_factories.py:2977-2982 requires ENGINE_AUTOSTART=true AND
LIVE_TRADING_ENABLED=true when TRADING_MODE=live, both defaulting false; the
paper-mode default of true is safe.
So F58 is a DISCOVERABILITY defect, not a safety one. Correcting my earlier
MEDIUM-HIGH down to LOW.

================================================================================
BACKTESTING INTEGRITY (domain 3) — done by me; the agent died on session quota
after its first message. F119 onward.
================================================================================

## F119 — annualised return is computed as if hourly bars were days; reported ~34x too low · HIGH (proven by arithmetic on the real formula)
backtesting/engine_config.py:1026, inside `_calculate_results`:
    annual_return = (1 + total_return) ** (252.0 / max(len(equity_values), 1)) - 1
    calmar        = float(annual_return / max_drawdown) if max_drawdown > 0 else 0.0
`equity_values` holds one entry PER BAR, and the engine runs on HOURLY bars:
    engine_config.py:581  df = await self.data_loader.load_data(symbol, "1h", ...)
    engine_config.py:85   bars_per_day: float = 24.0  # 24 for H1, 6 for H4, 1 for D
So the exponent 252/len(equity_values) treats a bar count as a day count.

COMPUTED FROM THE REAL FORMULA:
    1 year, +100%    bars=6048   reported=  2.930%   correct= 100.000%   34.1x low
    1 year, +30%     bars=6048   reported=  1.099%   correct=  30.000%   27.3x low
    2 years, +50%    bars=12096  reported=  0.848%   correct=  22.474%   26.5x low
A strategy that doubled capital in a year is reported as returning 2.93%.
CALMAR (:1027) is annual_return / max_drawdown, so it carries the identical error
and is meaningless as published.

Correct exponent: 252 / (len(equity_values)/bars_per_day), i.e.
252*bars_per_day/len(equity_values) — off by exactly bars_per_day = 24.

WHAT MAKES THIS A CLEAR SLIP RATHER THAN A CONVENTION: the same function handles
bars_per_day correctly everywhere else —
    :990   ann_factor = np.sqrt(252.0 * max(self.config.bars_per_day, 1e-9))
    :1008  avg_hold_days = avg_hold_bars / self.config.bars_per_day
    :1009  trade_ann_factor = np.sqrt(252.0 / max(avg_hold_days, 0.04))
Line 1026 is the one place the divisor was omitted.
Direction is CONSERVATIVE (it understates performance), which is very likely why
it has never been questioned — an understated backtest tempts nobody. It still
makes annual_return and Calmar unusable, and it would mask a genuinely good
strategy as flat.

## F120 — the Sortino denominator is the wrong statistic, in BOTH engines · MEDIUM (proven by execution)
Both implementations compute the denominator as the standard deviation of the
losing observations only:
    backtesting/metrics.py:135-142
        downside_returns = returns[returns < 0]
        ... np.sqrt(252) * (excess_returns.mean() / downside_returns.std())
    backtesting/engine_config.py:1018-1023
        downside = bar_returns[bar_returns < 0]
        downside_std = float(np.std(downside))
        sortino = float(np.mean(bar_returns) / downside_std * ann_factor)

`returns[returns<0].std()` measures the DISPERSION AMONG THE LOSSES — deviation
about the mean loss, over only the losing periods. Downside deviation is
`sqrt(mean(min(r - target, 0)^2))`, a root-mean-square about the TARGET taken
over ALL periods. Different denominator, different N, different centre.

MEASURED against the textbook definition (scratchpad/bt_sortino2.py, real
PerformanceMetrics, 1000 periods each):
    symmetric normal returns
        used 0.005866   correct 0.006636   REPORTED 2.392  CORRECT 2.115  1.13x HIGH
    negatively skewed (many small wins, rare big losses — the realistic shape)
        used 0.010652   correct 0.007610   REPORTED 0.786  CORRECT 1.101  0.71x LOW
    fat left tail (2% shock days)
        used 0.011289   correct 0.008827   REPORTED -0.448 CORRECT -0.573 0.78x LOW

CORRECTING MY OWN FIRST HYPOTHESIS: I expected this to inflate Sortino
uniformly. It does not. The bias flips sign with the shape of the return
distribution — it overstates for symmetric returns and UNDERSTATES for the
negatively-skewed distributions that trading strategies actually produce. The
defect is that the number is not Sortino at all, not that it points one way.
Severity MEDIUM: a reported metric is wrong in an unpredictable direction. It is
not a gate and does not size a position.

## F121 — fills are referenced to the SAME BAR'S CLOSE that produced the signal · MEDIUM (structural, verified by reading the loop)
backtesting/engine_config.py:622-643, per bar:
    mask = df["timestamp"] <= timestamp
    row = df[mask].iloc[-1]
    current_prices[symbol] = float(row["close"])       # <-- bar N close
    ...
    signals = strategy.generate_signals(timestamp=timestamp, prices=current_prices, data=all_data)
    self._process_signal(signal, timestamp, current_prices, current_bars)
and :782-788 `place_market_order(symbol, action, quantity, current_price, ...)`.
The decision is made from bar N's close and the fill is referenced to bar N's
close. In live trading that close is not knowable until the bar has ended, so
the order can only be worked at bar N+1. This is the classic same-bar-close
fill; it flatters any strategy whose signal is triggered by the close itself.

MITIGATED, not eliminated: slippage is applied in the ADVERSE direction and
scales with the bar range, so the fill is never better than the close —
    :335-337  slippage = self._calculate_slippage(current_price, bar_high, bar_low)
              fill_price = current_price*(1+slippage) if side=="buy"
                           else current_price*(1-slippage)
That converts an impossible fill into a pessimistic one of unknown adequacy. It
is a reasonable proxy, but it is not the same as filling at the next bar's open,
and nothing in the config offers that option.

## F122 — the engine hands strategies the ENTIRE future; only the adapter slices it · MEDIUM (structural)
engine_config.py:640-642 passes `data=all_data` — every symbol's COMPLETE
DataFrame, including all bars after `timestamp`. Point-in-time discipline is not
enforced by the engine; it is delegated to the strategy.
The supported path does it correctly:
    backtesting/strategy_adapter.py:152  history = frame[frame["timestamp"] <= timestamp]
    (docstring :28 states this explicitly, and api/advanced_trading.py:229-230
     wraps every API-launched strategy in BacktestStrategyAdapter)
But `add_strategy` (engine_config.py:555-557) is
    def add_strategy(self, strategy: Any):
        self.strategies.append(strategy)
— no type check, no adapter requirement. Any object exposing
`generate_signals(timestamp, prices, data)` is accepted and receives the
unsliced future. engine_config.py:1299 (`quick_backtest`) does exactly that: it
calls `engine.add_strategy(strategy)` on the caller's raw object.
LATENT for the shipped strategies, which go through the adapter. The hazard is
that the safe path is a convention rather than an invariant, and the unsafe one
is the more obvious API.

## BACKTESTING — VERIFIED CLEAN (recorded so this is not re-audited)
These are the things I went looking for and did NOT find. Several are better
than typical:
  * TRANSACTION COSTS ARE REAL AND SYMMETRIC. engine_config.py:341-347 —
    `rt_frac = self._tc.round_trip_cost_frac(ticker)` then
    `commission = cost * rt_frac / 2.0`, explicitly "half the round-trip cost on
    entry, half on exit (symmetric)". Costs are charged on both sides, as bps of
    notional, not a token flat fee.
  * SLIPPAGE IS ADVERSE, NEVER FAVOURABLE (:337, above) and is derived from the
    actual bar high/low rather than a constant.
  * BUYING POWER IS CHECKED. :350-351 rejects the order when
    cost + commission > cash, so the backtest cannot trade money it does not
    have.
  * WALK-FORWARD USES A PURGE/EMBARGO GAP. backtesting/walk_forward.py:75-86 —
    train_end -> purge_start/purge_end -> test_start, with the comment
    "purge_start:purge_end is the embargo gap between train and test". This is
    the López de Prado precaution against leakage across the split boundary and
    most backtesters omit it.
  * TRADE-LEVEL SHARPE IS ANNUALISED CORRECTLY, and the author documented WHY
    bar-level Sharpe was rejected (:985-999): "Flat no-trade bars inflate the
    bar-level Sharpe by suppressing the denominator... Bar-level Sharpe
    (previously reported as 4.68) was inflated by flat no-trade days". That is a
    real, correctly diagnosed overfitting trap that was found and fixed.
  * A SHARPE STANDARD ERROR IS REPORTED. :1014-1015
    `sharpe_se = 1/sqrt(2*(N-1))`. Publishing an uncertainty alongside a Sharpe
    is unusual and good practice.
  * STRATEGY EXCEPTIONS ARE NOT SWALLOWED SILENTLY. :645-651 appends to
    `self.strategy_errors`, with the comment that a run where this fired on
    every bar "used to be indistinguishable from a strategy that chose not to
    trade". Same fix in strategy_adapter.py:159-161.
  * AN EMPTY STRATEGY LIST IS AN ERROR, not a 0.00% result (:570-575).
  * EXITS CLOSE THE ACTUAL POSITION rather than a freshly Kelly-sized quantity
    (:761-772), with the reasoning written out.

## F123 — *** THE WALK-FORWARD ENDPOINT PERFORMS NO WALK-FORWARD ANALYSIS *** · CRITICAL (proven by arithmetic on the real code)
`POST /walk-forward/run` (api/backtesting.py:560-640), gated at
`require_plan("professional")`, persisted via `_persist_wf_result` and rendered
in the frontend as out-of-sample validation. It does none of the three things
walk-forward analysis consists of.

The fold loop (:598-616) computes real-looking date boundaries:
    fold_start = start_dt + timedelta(days=i*fold_days)
    fold_end   = fold_start + timedelta(days=fold_days)
    train_end  = fold_start + timedelta(days=int(fold_days*req.train_ratio))
and then passes NONE of them to the backtest. It passes DURATIONS:
    train_result = _run_real_backtest(strategy, symbol, int((train_end - fold_start).days), capital)
    test_result  = _run_real_backtest(strategy, symbol, int((fold_end  - train_end ).days), capital)
The dates survive only as display labels in the result dict (:620-624).

And `_run_real_backtest` (api/backtesting.py:423-441) anchors every window to NOW:
    end_dt   = datetime.now(UTC)
    start_dt = end_dt - timedelta(days=days)

COMPUTED WITH THE ENDPOINT'S OWN DEFAULTS (n_splits=5, train_ratio=0.7, 3 years):
    fold_days = 219
    fold | LABEL shown to the user                        | days actually passed
      1  | 2023-08-23..2024-01-23 / 2024-01-23..2024-03-29 | train=153 test=66
      2  | 2024-03-29..2024-08-29 / 2024-08-29..2024-11-03 | train=153 test=66
      3  | 2024-11-03..2025-04-05 / 2025-04-05..2025-06-10 | train=153 test=66
      4  | 2025-06-10..2025-11-10 / 2025-11-10..2026-01-15 | train=153 test=66
      5  | 2026-01-15..2026-06-17 / 2026-06-17..2026-08-22 | train=153 test=66

THREE SEPARATE DEFECTS, each fatal on its own:

1. THE TEST SET IS A SUBSET OF THE TRAINING SET. Both windows end at `now`, so
   every fold backtests train=[now-153d, now] and test=[now-66d, now]. The
   "out-of-sample" period is the last 66 days OF THE IN-SAMPLE PERIOD. This is
   not leakage at the boundary — the test data is wholly contained in the train
   data. It is the most contaminated split possible.

2. ALL FIVE FOLDS ARE THE SAME TWO BACKTESTS. `fold_days` is constant, so
   `train_end - fold_start` is 153 days and `fold_end - train_end` is 66 days
   for EVERY i. The loop runs the identical pair five times and labels the
   results with five different historical periods spanning 2023-2026. The
   reported per-fold variation — the whole point of walk-forward — can only be
   backtest nondeterminism. `avg_test_sharpe` (:637) averages five copies of one
   number and reports it as a cross-fold mean.

3. NOTHING IS OPTIMISED. Genuine walk-forward fits parameters on train and
   applies the FROZEN parameters to test. Here `_run_real_backtest` is called
   with the same `req.strategy_params` both times; `train_result` and
   `test_result` are just two runs of the same unchanged strategy. The
   train/test distinction is decorative.

WHAT MAKES THIS WORSE: the repo already contains a CORRECT implementation.
backtesting/walk_forward.py:75-86 does anchored rolling windows with a
purge/embargo gap between train and test, and :99-103 optimises on the training
window then evaluates the winner on the held-out window. It is exported from
backtesting/__init__.py:34. The endpoint does not use it.

Severity CRITICAL. Every other backtesting finding here distorts a number; this
one manufactures the specific evidence an operator would rely on to conclude a
strategy generalises before committing real money. A user reading this output
sees five independent out-of-sample periods agreeing with each other. There is
one in-sample period, counted five times.

================================================================================
FRONTEND (domain 8) — 95,599 LOC TypeScript, 302 files. Done by me.
================================================================================

## F124 — THE FRONTEND IS THE BEST-ENGINEERED LAYER IN THIS REPOSITORY · NO FINDING (verified by running it)
Recording this in detail because it is the opposite of the pattern everywhere
else in the audit, and because it means this surface does not need re-auditing.

  * `npm run typecheck` (tsc --noEmit) passes CLEAN across all 95,599 lines.
    And it is a meaningful pass — tsconfig.json has
        "strict": true,
        "noUncheckedIndexedAccess": true,     <-- rarely enabled; very strict
        "noFallthroughCasesInSwitch": true
  * NO FABRICATED DATA. Swept for Math.random / mockData / MOCK_ / fakeData /
    DUMMY / sampleData outside tests. Three hits, all legitimate: a modal id
    (Modal.tsx:57), WebSocket reconnect jitter (useWebSocket.ts:473), and
    placeholder *text* in inputs. Nothing invents a number.
  * MONEY FORMATTERS FAIL TO "—", NEVER TO 0. lib/utils.ts:91-138 — every one of
    fmtPrice/fmtPct/fmtPctRaw/fmtPnl/fmtCompact begins
    `if (value == null || !isFinite(value)) return '—';`. A missing value renders
    as a dash, not as a plausible zero.
  * fmtPnl CARRIES ITS OWN BUG HISTORY (:112-129): "The negative branch
    previously produced an empty sign while still taking Math.abs, so every loss
    rendered as a positive number — a -$500 position read as '$500.00' in the
    positions table, the portfolio summary and the performance page. Colour
    usually carried the meaning; the number did not." Found, fixed, documented.
  * THE JWT IS NEVER PERSISTED. useApi.ts:161 "Use the in-memory Zustand token
    only — never localStorage"; :261 "Store in Zustand memory only — never in
    localStorage"; AuthGuard.tsx:7 the same. localStorage is used only for the
    theme and a dismissed banner. This is the correct XSS posture and most
    codebases get it wrong.
  * THE STALE-FEED WATCHDOG IS REAL, AND IT DEFENDS AGAINST MY OWN F87.
    This chain is fully wired — I traced every link because the repeated backend
    pattern is a control that is never invoked:
        useWebSocket.ts:62   FEED_STALE_AFTER_MS = HEARTBEAT_INTERVAL_MS * 2
        useWebSocket.ts:343  startFeedWatchdog()  — setInterval every 5s
        useWebSocket.ts:346-350
             if (wsStatus !== 'connected') return;
             if (lastDataAt == null) return;
             const stale = Date.now() - lastDataAt > FEED_STALE_AFTER_MS;
             if (stale !== feedStale) setFeedStale(stale);
        useWebSocket.ts:443  startFeedWatchdog() IS CALLED on connect
        useWebSocket.ts:457,508  cleared on close and on unmount
        store/index.ts:607   selectFeedLive = wsStatus === 'connected'
                                              && !feedStale && lastDataAt != null
    The comment at :332-341 states the failure mode exactly: "`lastHeartbeat`
    was written to the store on every heartbeat and read nowhere outside test
    files... The `noLiveFeed` banner is not a substitute: it only fires when the
    *server* volunteers that condition, which a stalled server cannot do."
    That is the same class of defect as F87, identified and closed on the client.
  * AND THE FALLBACK IS KEYED CORRECTLY. useOrchestratorData.ts:277-283:
    "keyed to `selectFeedLive`, not `wsStatus`. This fallback exists for a dead
    feed, and `wsStatus` stays 'connected' through the one failure mode that
    matters... Keyed to the connection flag, the fallback was switched off during
    precisely the outage it was written for."
  * ORDER ENTRY REFUSES TO SIZE AGAINST A STALE PRICE.
    OrderEntryForm.tsx:238-241 consumes selectFeedLive and surfaces it in the
    confirmation dialog.
  * ERROR BOUNDARIES ARE PER-PANEL, not just top-level. PanelErrorBoundary.tsx
    and withPanelGuard.tsx wrap the risky data panels (RiskDashboard,
    MicrostructurePanel, OrderBookDepth, LivePriceTicker, MacroCalendar,
    SentimentGauge), and App.tsx:371 wraps every route. A bad payload degrades
    one panel rather than blanking the app.

THE ONE REAL GAP — the network boundary is asserted, not validated:
  * NO runtime validation library is present (no zod/io-ts/yup/valibot/ajv in
    package.json).
  * 142 unchecked `as` casts on API responses, e.g.
        useOrchestratorData.ts:272  return res.data as AccountMetrics;
    TypeScript's strictness stops at the wire. Every backend response is
    ASSERTED to match its interface, never CHECKED.
  Severity MEDIUM, not higher, for two reasons I verified rather than assumed:
  a crash is contained by the per-panel boundaries above, and the formatters
  degrade to "—" rather than 0. The genuine exposure is not a crash but
  WELL-TYPED WRONG DATA — a field that is present, correctly shaped, and
  semantically false passes the cast silently. That is exactly what several
  backend findings produce (F16 fabricated equity, F72 equity=0.0, F94's
  permanently "unknown" regime), and no amount of frontend strictness can catch
  it. Runtime schema validation at the boundary would not catch it either; the
  fix belongs on the server.

## F125 — the regime EMA is computed backwards; the oldest bar outweighs the newest 7.4x · MEDIUM (proven by execution)
api/trading.py:3788-3794, serving the regime badge in AIChart.tsx:117-125:

    ema20 = closes[-1]
    for c in reversed(closes[-20:]):
        ema20 = ema20 * 0.9 + c * 0.1
    ema50 = closes[-1]
    for c in reversed(closes[-min(50, len(closes)):]):
        ema50 = ema50 * 0.96 + c * 0.04

`reversed()` walks the window newest -> oldest. In this recurrence the value
folded in LAST carries the full 0.1 coefficient and each earlier one decays by
0.9, so the weighting is inverted end to end.

MEASURED by replicating the loop exactly:
    weight applied to the NEWEST bar (folded first) : 0.01351
    weight applied to the OLDEST bar (folded last)  : 0.10000
    -> the oldest bar carries 7.4x the weight of the newest

    steadily RISING series, last close 3295:  code 3238.92   correct EMA20 3254.59
    steadily FALLING series, last close 2705: code 2761.08   correct EMA20 2745.41

BEING PRECISE ABOUT THE IMPACT: the classification is NOT reversed. The code EMA
still sits below price in an uptrend and above it in a downtrend, so
`ema_spread > 0.005` still means "up". What is wrong is the responsiveness — the
indicator is dominated by the oldest bar in its window, so it lags far more than
a 20-period EMA should and the derived `confidence`
(:3813 `min(0.90, 0.55 + abs(ema_spread)*15)`) is computed from a spread that is
not the spread between a 20- and a 50-period EMA. Both numbers are displayed to
the trader as a regime badge and a confidence figure.

AND IT IS A SEVENTH REGIME TAXONOMY. This endpoint computes its own
"trending_up"/"trending_down"/"ranging" inline, unrelated to the router's seven
REGIME_* strings and to all five MarketRegime enums catalogued in F94.
Note the endpoint DOES guard against the dead router (:3835
`if status_dict.get("current_regime", "unknown") != "unknown":`), so the UI is
not showing F94's stuck "unknown" — it falls through to this inline computation
instead. F94's sizing impact is unaffected: core/signal_engine.py reads
`status()` directly with no such guard.

================================================================================
NUCLEAR / NEWS PIPELINE (domain 6) — completing what F80/F89/F91 started.
================================================================================

## F126 — the nuclear pipeline is FULLY WIRED and its signals place real orders · NO FINDING, but essential context
Recording this first because my own initial reading was wrong and the correction
matters for how every other nuclear finding should be weighted.

A caller count on the individual modules is MISLEADING here. Counting imports
from outside the package gives zero for signal_composer, strategy_engine,
itos_cone_engine and shadow_backtest (2,607 LOC) — which looks like dead code.
It is not. nuclear/nuclear_agent.py:56-62 imports ALL of them:
    from nuclear.feature_builder    import FeatureBuilder, MultiTimeframeFeatures
    from nuclear.itos_cone_engine   import ItosCone, ItosConeEngine
    from nuclear.redis_stream_reader import RedisStreamReader, get_stream_reader
    from nuclear.regime_classifier  import RegimeClassifier, RegimeResult
    from nuclear.shadow_backtest    import BacktestResult, ShadowBacktestEngine
    from nuclear.signal_composer    import NuclearSignal, SignalComposer
    from nuclear.strategy_engine    import NuclearStrategyEngine
`nuclear/__init__.py:23-25` exports only the agent, which is why the package
reads as dead from outside. The whole pipeline runs behind one entry point.

AND IT REACHES EXECUTION:
    hopefx_engine.py:495-496  get_nuclear_agent(...); await agent.start()
    hopefx_engine.py:627-632  tasks.append(agent.run_loop(
                                  interval_s=NUCLEAR_INTERVAL_S default 5,
                                  on_signal=self._on_nuclear_signal))
    hopefx_engine.py:637-644  _on_nuclear_signal converts an APPROVED
                              NuclearSignal into an ExecutionRequest and routes
                              it through the ExecutionEngine.
The kill switch is checked there and FAILS CLOSED, with the reasoning written
out (:645-660): "The ExecutionEngine path enforces this too, but the fallback to
direct broker calls below does not — so check here as well". Any error in the
check drops the signal. Correct.

*** THE COMPOUNDING FACT: in hopefx_engine.py the nuclear agent is very likely
the ONLY signal source. *** Per F88, hopefx_engine.py:398 injects a
`StrategyManager()` with preload_defaults=False — zero strategies — into the
brain. So the brain contributes nothing there and every order originates from
this pipeline. That makes F80 (the wordmap scoring a headline containing
"coupon" at severity 7 and triggering hedge_mode) a defect on the primary order
path of the standalone engine, not a peripheral one.

## F127 — the nuclear shadow backtest is CORRECTLY point-in-time · NO FINDING (verified by reading the slicing)
Notable because F123 shows the same repository shipping a walk-forward endpoint
with the test set inside the training set. This one is right.
    nuclear/shadow_backtest.py:346-348
        bars_at_tick = {tf: [b for b in bars
                             if (b.close_time or b.open_time) <= tick.timestamp]
                        for tf, bars in bars_by_tf.items()}
    :436  docstring: "Walk-forward bar simulation: generate signal on bar[i],
                      exit on bar[i+1]"
    :445  walk_bars = bars[-(n_bars+1):]
    :447-448  for i in range(len(walk_bars)-1):
                  history = bars[: -(n_bars - i)] if (n_bars - i) > 0 else bars
I checked the slice arithmetic rather than trusting the comment, because
off-by-one here is exactly where lookahead enters. With n_bars=5:
    i=0 -> signal bar = bars[-6], exit = bars[-5], history = bars[:-5]
           (history ends AT bars[-6] — the signal bar's own close, which is
            knowable when it closes. Correct.)
    i=4 -> signal bar = bars[-2], exit = bars[-1], history = bars[:-1]. Correct.
No lookahead at either end of the walk.

## F128 — an APPROVED live order needs only THREE backtest trades · MEDIUM (bounded by the sizing caps)
nuclear/signal_composer.py:535-562 `_evaluate_approval` is correctly implemented
and matches its docstring exactly (RR floor first, then the confidence floor,
then the conjunction):
    if rr < self._rr_min:                     -> REJECTED
    if confidence < self._conf_pending:       -> REJECTED
    if confidence >= self._conf_approved and bt_trades >= self._min_bt_trades:
                                              -> APPROVED
The thresholds (:70-76):
    _CONF_APPROVED = 0.60   _CONF_PENDING = 0.45   _RR_MIN = 1.5
    _MIN_BACKTEST_TRADES = 3
THREE trades is the entire evidentiary bar for releasing an order to a broker.
With exactly 3 trades the win rate can only take four values —
    reachable win_rate with 3 trades: [0.0, 0.333, 0.667, 1.0]
— so "backtest validated" carries essentially no statistical information, and
that win rate then feeds the Kelly fraction at :424-429.

WHY THIS IS MEDIUM AND NOT HIGH — the design bounds the consequence, and I
computed the actual range rather than assuming:
    _KELLY_CAP = 0.25   _BASE_RISK_PCT = 0.01   _MAX_RISK_PCT = 0.02
    risk_pct      = min(BASE*(0.5 + conf*0.5), MAX)
    position_size = min(risk_pct*(kelly*0.5 + 0.5), MAX)
      conf=0.60 kelly=0.00 -> position_size = 0.00400
      conf=0.60 kelly=0.25 -> position_size = 0.00500
      conf=1.00 kelly=0.00 -> position_size = 0.00500
      conf=1.00 kelly=0.25 -> position_size = 0.00625
Across the ENTIRE confidence and Kelly space the position is 0.40%-0.625% of
equity against a 2% cap. Kelly's total influence is a 1.25x swing, because the
`+ 0.5` term floors its contribution. A meaningless 3-trade Kelly estimate
therefore cannot produce a dangerous position. Two further mitigations are real:
`wr = bt.win_rate if bt.total_trades >= self._min_bt_trades else 0.5` (:424)
falls back to neutral rather than optimistic, and `confidence_score`
(shadow_backtest.py:150-166) explicitly includes
`sample_score = min(total_trades/20, 1.0)` weighted 0.25, so a small sample does
suppress confidence.
The finding is that the GATE is weak evidence, not that the outcome is unsafe.
Raising _MIN_BACKTEST_TRADES is a one-constant change.

## F129 — an EIGHTH regime taxonomy · LOW (extends F94)
nuclear/regime_classifier.py:60-68 defines its own nine regime strings:
    trending_up, trending_down, breakout, mean_reverting, range_bound,
    high_vol, low_vol, crisis, unknown
It overlaps strategies/regime_router.py's seven but is not the same set — it
adds `breakout` and `crisis`. Running total of independent "market regime"
vocabularies in this one repository:
    1  strategies/regime_router.py      7 REGIME_* strings
    2  ml/regime.py                     MarketRegime enum
    3  brain/brain.py                   MarketRegime enum
    4  analysis/market_analysis.py      MarketRegime enum
    5  nocode/ml_nodes.py               MarketRegime enum
    6  backtesting/enhanced_engine.py   MarketRegime enum
    7  api/trading.py:3812-3826         inline trending_up/trending_down/ranging
    8  nuclear/regime_classifier.py     9 REGIME_* strings
Eight vocabularies, no shared type, no conversion layer between any pair. Per
F94 the one that drives position sizing is the one whose detector never runs,
and `_REGIME_SIZE_MAP.get(name.upper(), 0.5)` fails open to 0.5 on any name it
does not recognise — which is what hides the mismatch between all eight.

================================================================================
SELF-HEALER / SECURITY TOOLING (domain 5) — security/ 9,924 LOC. Done by me.
This subsystem WRITES PYTHON SOURCE FILES IN THE RUNNING TREE, so reachability
was traced before any severity was assigned.
================================================================================

## F130 — the self-healer's patch-signing control is OFF BY DEFAULT and set NOWHERE · HIGH (conditional on entry point — see the reachability section)
security/self_healer.py:133-139:
    # Patches written to fixes:approved must be signed with this key so that a
    # compromised Redis instance cannot inject arbitrary code.  Set
    # HEAL_PATCH_SIGNING_KEY in the environment (min 32 bytes recommended).
    # If unset, signing is skipped and a warning is emitted on every drain cycle.
    _PATCH_SIGNING_KEY: bytes = os.getenv("HEAL_PATCH_SIGNING_KEY", "").encode()

and :328-349 `_patch_entry_is_trusted`:
    if not _PATCH_SIGNING_KEY:
        logger.warning("SelfHealer: HEAL_PATCH_SIGNING_KEY not set — patch queue
                        trust verification disabled.  Set this env var to
                        prevent Redis injection.")
        return True                      # <-- ACCEPTS THE PATCH
    ...
    return _verify_patch_signature(raw, sig)

The HMAC check is correctly built — `hmac.new(key, payload, sha256)` and
`hmac.compare_digest` (:318-326), no timing leak, no truthiness bug. It simply
does not run.

GREPPED THE ENTIRE REPOSITORY FOR `HEAL_PATCH_SIGNING_KEY`, all file types,
excluding .venv and this audit log: it appears ONLY inside self_healer.py.
Not in .env.example, not in .env.production.example, not in docker-compose.yml,
not in k8s/k8s-configmap.yaml, not in deployments/k8s/configmap.yaml. There is
no shipped configuration in which this control is on. This is the same shape as
F101 — a fail-open safety flag outside the reach of Gate L's three-file scan.

The author's own comment names the exact threat the control exists to stop:
"a compromised Redis instance cannot inject arbitrary code". With the key unset,
whatever can RPUSH to the Redis list `fixes:approved` (:916
`redis.lrange("fixes:approved", 0, -1)`) has its Python written into the source
tree, subject only to the defence-in-depth checks in F131.

*** REACHABILITY — this is why it is HIGH and not CRITICAL. ***
The drain loop only runs when the healer's background tasks are started, and
only ONE entry point does that:
    connect_to_life.py:347-353   from security.self_healer import start_healer
                                 await _start_healer(...)
    self_healer.py:2158-2167     start_healer -> asyncio.create_task(healer.run())
    self_healer.py:733-754       run() starts 7 loops, including
                                 _patch_loop and _claude_fix_loop
`connect_to_life.py` IS a real entry point — scripts/ci/gate_e_dead_files.py:57
lists it under "Entry-point scripts run directly, not imported".
But the CONTAINERISED PRODUCTION PATH DOES NOT START IT. Dockerfile:91 is
`scripts/preflight.sh && python app.py`, and app.py contains no reference to the
healer (grepped). What app.py DOES get is the HTTP router —
core/router_registry.py:525-528 registers `/api/security/heal/*` unconditionally.
So: in the Docker deployment the patch loops are dormant and only the endpoints
exist; running connect_to_life.py directly turns the full autonomous patcher on.

AT THE DEFAULT CONFIG, once started, here is what is and is not live — I read
each gate rather than assuming:
    :508  self._enabled       = True
    :509  self._aggressiveness = "medium"       # low|medium|aggressive|nuclear
    :901  Redis patch drain runs when `self._enabled and aggressiveness != "low"`
                                                        -> ON at "medium"
    :1266 LLM patches require aggressiveness in ("aggressive","nuclear")
                                                        -> OFF at "medium"
    :1285 LLM patches also require ANTHROPIC_API_KEY, else the queue is cleared
    :980  categories in _require_approval_categories (["nuclear","e2e"], :571)
          are diverted to `heal:pending_approval` unless aggressiveness=="nuclear"
So the LLM-authored path is off by default — correct posture, and worth saying
plainly. The Redis-queued path is ON by default, and it is the one whose
signature check is disabled.

## F131 — the remaining defence is a denylist, and the code says so itself · MEDIUM (context for F130)
With F130's signature check inert, `_validate_patch_content` (:356-403) is the
only thing between the Redis queue and the file system. It is thoughtfully
built, and it is a denylist:
    _DANGEROUS_CALLS (:141-157): exec, eval, compile, __import__, subprocess,
        os.system, os.popen, open, socket, urllib, requests, httpx
    _DANGEROUS_ATTRS (:158-171): system, popen, execve, execvp, spawn, Popen,
        call, check_call, check_output, run
    plus a sensitive-path regex over string literals (.env, id_rsa, .pem,
    /etc/passwd …) and a 50%-shrink guard.
The header comment at :140 is candid: "This is a defence-in-depth check on top
of the compile() gate." The author did not intend it as the primary control —
the HMAC signature was the primary control, and F130 is that it never runs.

Structural limits, stated factually and without a recipe:
  * The scan visits `ast.Call` nodes only. `import` and `ImportFrom` statements
    are never examined, so module imports are unrestricted; `importlib` is
    absent from both lists.
  * Only direct `Name` calls and `Attribute` calls are matched. Any denylist
    keyed to identifiers at parse time cannot see indirection, by construction.
  * The sensitive-path regex inspects `ast.Constant` string literals only.
These are inherent properties of AST denylists rather than oversights; the
correct remedy is the one the author already designed — set the signing key so
untrusted entries never reach the validator.

GOOD DESIGN WORTH RECORDING, because this module gets a lot right:
  * MAX_PATCH_SIZE 64 KB (:107).
  * A backup is taken before every write — `shutil.copy2(path, dest)` (:265).
  * The 50%-shrink guard exists specifically to stop "wholesale deletion of
    safety logic" (:363-364) — someone thought about the adversarial case.
  * On a failed import after patching, it reverts with `git checkout --` and
    validates the path first: "unsafe path rejected for git rollback" (:286-308).
  * `_import_ok` (:406-418) treats ANY read/compile error as unsafe, not just
    SyntaxError.
  * Diagnostics are disabled in development/test (:1552) with the reasoning
    written out.

## F132 — the heal router's auth fails open on ImportError · LOW (latent — I checked, it does not currently fire)
security/self_healer.py:2175-2209. Both dependencies have the same shape:
    def _heal_require_auth(request):        # read endpoints
        try:
            from auth.jwt import decode_access_token as _decode
            ... _decode(token)
        except HTTPException: raise
        except ImportError:  # nosec B110
            logger.warning("SelfHealer router: auth.jwt unavailable, auth skipped")
        except Exception as exc: raise HTTPException(401) from exc
    def _heal_require_admin(request):       # mutating endpoints
        ... except ImportError: "admin check skipped"
Falling through the `except ImportError` branch returns None, which FastAPI
treats as a satisfied dependency — the endpoint executes unauthenticated.

I HYPOTHESISED THIS WAS REACHABLE AND IT IS NOT — recording the check so it is
not re-raised. `decode_access_token` does lazy-import `auth.service` inside the
function (auth/jwt.py:169), which looked like a live path to an ImportError
escaping into the caller's handler. It is not: auth/jwt.py:173-174 catches that
ImportError itself. And `from auth.jwt import decode_access_token` imports
cleanly here (verified by running it) — it needs only `jwt` and `bcrypt`, both
hard dependencies.
So the fail-open requires auth.jwt itself to become unimportable, which would
break the whole application anyway. LATENT. The endpoint structure is otherwise
correct: read endpoints take `_heal_require_auth`, every mutating endpoint takes
`_heal_require_admin` (:2239, :2243, :2249, :2266, :2287, :2294), and none of
them applies a patch — they trigger scans, analyses and diagnostics only.

## F133 — the token-revocation check fails open · LOW
auth/jwt.py:167-175, inside `decode_access_token`:
    if jti:
        try:
            from auth.service import is_access_token_revoked
            if is_access_token_revoked(jti):
                raise jwt.InvalidTokenError("Token has been revoked")
        except ImportError:
            ...  # nosec B110
    return payload
If `auth.service` cannot be imported, a REVOKED token is accepted as valid — the
blacklist is silently skipped rather than failing closed. `auth.service` pulls in
the database layer, so this is more plausible than F132's trigger (a missing DB
driver, a circular import during startup ordering). Narrow, but it is a
revocation control that degrades to "allow" rather than "deny".

## F134 — the LLM default model is a generation behind · LOW (informational)
security/self_healer.py:1479  `model = os.getenv("ANTHROPIC_MODEL", "claude-opus-4-5")`
The current generation is the Claude 5 family (claude-opus-5, claude-sonnet-5,
claude-fable-5), with claude-haiku-4-5 alongside. The default here pins the
previous generation. It is overridable by ANTHROPIC_MODEL and only matters when
the LLM fix path is enabled (aggressive/nuclear + API key), so this is a currency
note rather than a defect.

================================================================================
DATABASE / ORM (domain 4) — database/ 4,880 LOC + the payments write path.
Agent 2 covered alembic; this is the schema and the code that writes to it.
================================================================================

## F135 — *** WALLET LEDGER ROWS COLLIDE AND ARE SILENTLY DROPPED *** · CRITICAL (proven by execution)
payments/wallet.py:284 (deposit) and :396 (withdrawal), identical in both:
    "transaction_id": f"TXN-{datetime.now(UTC).strftime('%Y%m%d%H%M%S')}",
A wall-clock timestamp to the SECOND, with no user id, no counter, no random
suffix — used as the value for
    database/models.py:756
    transaction_id = Column(String(50), unique=True, nullable=False, index=True)

PROVEN BY RUNNING THE REAL GENERATOR:
    5 transactions generated in 0.0001s:
      TXN-20260822024522
      TXN-20260822024522
      TXN-20260822024522
      TXN-20260822024522
      TXN-20260822024522
    distinct ids : 1 of 5
Any two wallet transactions ANYWHERE IN THE SYSTEM inside the same second
collide on the unique index. Not per-user — the constraint is global.

AND THE FAILURE IS SWALLOWED. payments/wallet.py:104-121 `_persist_transaction`:
    with self._session_factory() as session:
        session.add(WalletTransaction(transaction_id=txn["transaction_id"], ...))
        session.commit()
    except Exception as exc:
        logger.error("Wallet DB write failed: %s", exc)
The IntegrityError is caught and logged. But the in-memory balance was ALREADY
mutated before this call (:270-277 `wallet.subscription_balance += amount`), and
the function returns success to its caller.

CONSEQUENCE: the money moves in the wallet object, the audit row never lands.
The ledger and the balance diverge, permanently and silently, with only an ERROR
line in the log. And because `_load_balance_from_db` (:123-138) rebuilds the
balance by reading the LATEST `balance_after` row —
    session.query(WalletTransaction).filter_by(user_id=user_id)
           .order_by(WalletTransaction.id.desc()).first()
— a dropped row means a process restart restores the balance from BEFORE the
dropped transaction. The user's deposit disappears, or their withdrawal is
refunded, depending on which row was lost.
Fix is trivial: append a uuid4 (the codebase already does this elsewhere, e.g.
GoldTick.lineage_id).

## F136 — the wallet balance is a read-modify-write with no lock · HIGH
payments/wallet.py:270-277 mutates an in-memory wallet object
(`wallet.subscription_balance += amount`) and then records the result as
`balance_after`. `_load_balance_from_db` rehydrates it with an unlocked
`ORDER BY id DESC LIMIT 1`.
There is no `SELECT ... FOR UPDATE`, no `with_for_update()`, no atomic
`UPDATE ... SET balance = balance + :amount`, and no unique constraint or
transaction isolation making the sequence safe (grepped for `with_for_update`
and `FOR UPDATE` across payments/ — no hits). Two concurrent deposits for the
same user both read the same starting balance and both write a `balance_after`
computed from it: a classic lost update.
The in-memory dict makes this worse rather than better — with more than one
worker process (the deployment runs uvicorn/gunicorn and a separate Celery
worker, celery_app.py) each has its OWN `_transaction_history` and wallet
objects, so they cannot even see each other's writes.

## F137 — every money column in the schema is Float; the Decimal discipline dies at the ORM boundary · MEDIUM (narrower than I first assumed — measured)
`grep -n "Numeric\|DECIMAL" database/models.py database/user_models.py` returns
NOTHING. Every monetary column in the schema is `Column(Float)`: trade
entry/exit price, realized/unrealized/total P&L, commission, swap, account
balance and equity, wallet `amount` and `balance_after` (:759-760), crypto
`amount_usd`/`amount_crypto` (:1071-1072), `Chargeback.amount` (:1192),
`TaxReport.total_revenue`/`taxable_amount` (:1241-1242), and payment
reconciliation `expected_amount`/`actual_amount` (:1293-1294).

This directly contradicts the layer above it. Per the money-precision map,
`payments/` and `monetization/` maintain `Decimal` throughout — and
payments/wallet.py shows the seam explicitly:
    :290, :401   "balance_after": float(...)        <-- Decimal -> float to store
    :138         return Decimal(str(row.balance_after))   <-- float -> Decimal to read
The read side uses `Decimal(str(x))`, which is the CORRECT idiom — the author
knew the rule. The column type is what forces the lossy trip in the first place.

I TESTED THE ACTUAL HARM RATHER THAN ASSERTING IT, AND MOST OF MY HYPOTHESIS DID
NOT HOLD. Recording the measurements so this is not overstated later:
  * Single store/load of typical USD amounts is LOSSLESS.
    Decimal('19.99'), '0.1', '1234567.89', '0.07', '99.95' all round-trip
    exactly through float64 — float64 carries 15-17 significant digits and
    Python's repr picks the shortest round-tripping string.
  * Accumulating 10,000 x 0.07 drifts by 9.1E-11 — negligible against a cent.
  * SUM over 200,000 randomised money rows: float 99874402117.279053 vs
    Decimal 99874402117.28 — drift 0.00095, UNDER one cent. Revenue aggregation
    is not materially broken.
  * WHERE IT DOES BITE — `amount_crypto` (:1072). 18-decimal token amounts
    exceed float64's precision:
        Decimal('1.23456789012345678')          -> 1.2345678901234567   LOSSY
        Decimal('12345678.123456789012345678')  -> 12345678.12345679    LOSSY
        Decimal('0.000000012345678')            -> exact
    ERC-20 amounts are 18-decimal by standard, so this column cannot represent
    them faithfully.
So the finding is NOT "float money is catastrophic" — for USD it is adequate in
practice. It is (a) a real precision defect on `amount_crypto`, and (b) an
architectural one: the schema throws away a type guarantee the application layer
spends real effort maintaining, so the next requirement that needs exactness
fails silently rather than loudly. `taxable_amount` as a float is the one to fix
first on principle even though the measured drift is sub-cent.

## F138 — an invariant exists for the balance arithmetic and nothing calls it here · LOW
invariants/payments.py:84
    def verify_balance_after(before: float, delta: float, after: float,
                             tol: float = 0.01) -> list[Violation]
Exactly the predicate that would catch F135's dropped rows and F136's lost
updates. Grepping the wallet write path shows no call to it — payments/wallet.py
computes `balance_after` and persists it without ever asserting
before + delta == after. Same shape as the recurring pattern in this audit: the
control is written, correct, and not wired in.

================================================================================
SCRIPTS / OPS (domain 7) + the kill-switch durability chain it exposed.
================================================================================

## F139 — *** THE deployments/k8s/ MANIFEST SET DISABLES CROSS-POD KILL-SWITCH PROPAGATION *** · CRITICAL
The kill switch is designed with five independent activation layers precisely so
that no single dependency can silence it (kill_switch.py:205-216):
    1. in-memory flag       2. kill_switch.flag file       3. env var
    4. Redis latch (ks:latch, TTL 7d)
    5. K8s ConfigMap watcher — the documented Redis-down fallback
and the docstring states the intent plainly: "When Redis is down: ... The K8s
ConfigMap watcher (priority 5) provides cross-pod propagation."
Layer 5 is started unconditionally (:295 `_k8s_configmap_watcher`) and written on
activation (:938 `_write_k8s_configmap(reason)`).

LAYER 5 REQUIRES RBAC, AND ONLY ONE OF THE TWO MANIFEST SETS GRANTS IT.
  k8s/  — CORRECT, and carefully done. k8s/kill-switch-rbac.yaml defines a Role
    scoped with `resourceNames: ["hopefx-kill-switch"]` and verbs limited to
    ["get","patch"] — genuine least privilege — bound to ServiceAccount
    `hopefx-api`, and k8s-deployment.yaml:39 sets `serviceAccountName: hopefx-api`.
  deployments/k8s/ — NO RBAC FILE EXISTS in that directory (contents: configmap,
    deployment, hpa, namespace, service), and deployment.yaml sets NO
    `serviceAccountName` (grepped: only two `securityContext` hits, :16 and :33).
    Pods therefore run as the namespace `default` ServiceAccount, which the
    RoleBinding does not name. Every `get`/`patch` on the kill-switch ConfigMap
    is denied by RBAC.

LAYER 2 DOES NOT SURVIVE A POD REPLACEMENT EITHER.
    kill_switch.py:78  _DEFAULT_FLAG_FILE = Path(__file__).parent / "kill_switch.flag"
That resolves inside the image layer (/app/kill_switch.flag), not onto a volume.
  * docker-compose.yml DOES declare a persistent `trading_state:/app/state`
    volume (:110, :199, :272) — the right home for this file — but the flag is
    not written there, and nothing sets `flag_file=` outside a test script
    (scripts/validate_ml_flow.py:610 is the only override in the repo).
  * k8s/k8s-deployment.yaml mounts only `tmp` (emptyDir) and `app-logs`; neither
    covers /app, and emptyDir does not survive rescheduling anyway.
So the comment at :107 — "JSON state file sits next to the flag file and survives
restarts" — is true for a process restart inside a live container and false for
a container replacement, which is the normal Kubernetes event.

LAYER 4 IS EXPLICITLY OPTIONAL. scripts/preflight.sh:258-266 downgrades an
unreachable Redis from `fail` to `warn` and continues, with the reasoning
written out. That is a defensible choice on its own — the orchestrator's own
startup log even names the cost: "Trading continues in degraded mode (no tick
cache, no kill-switch propagation)".

NET EFFECT for a cluster deployed from `deployments/k8s/`: layer 4 is optional,
layer 5 is denied by RBAC, layer 2 evaporates on reschedule, layer 1 is
per-process, and layer 3 requires a redeploy to change. An operator who hits the
kill switch stops the pod they reached and no other, and the halt does not
survive a restart. That directory ALSO sets HOPEFX_INVARIANT_MODE=monitor and
omits DRIFT_BLOCK/STALE_MODEL_BLOCK (F98), so the same manifest set that breaks
the kill switch also drops invariant enforcement and model-drift blocking.
Severity CRITICAL: this is the control of last resort on a money-moving system,
and one of the two shipped manifest sets silently removes three of its five
layers.

## F140 — scripts/ is clean on destructive operations · NO FINDING (verified)
Swept all 71 scripts for `DROP TABLE|DROP DATABASE|TRUNCATE|rm -rf|shutil.rmtree|
.delete()|DELETE FROM`. Two hits, both benign:
  * scripts/build_frontend.sh — `rm -rf` on build output only.
  * scripts/seed_demo_trades.py:192 — `db.query(Trade).filter(
    Trade.user_id == DEMO_USER_ID).delete()`, scoped to
    `DEMO_USER_ID = "demo-seed-user"` (:44) and defaulting `APP_ENV=development`
    (:34). The `--user_id` flag (:176) can retarget it, but that is an explicit
    operator argument, not an accident.
No script drops a table, truncates, or deletes across users.

## F141 — preflight.sh gates startup correctly · NO FINDING (verified)
scripts/preflight.sh uses a real `fail() { ...; exit 1; }` (:24) and applies it
where it matters: Python version below 3.12 (:40), a missing .env with required
vars absent (:60), any missing required env var (:94), and a failed Alembic
migration (:230). The Python-level `validate_environment(strict=True)` runs at
step 7. The only downgrade to `warn` is Redis (F139 above), and it is documented
with its rationale rather than silently loosened.

================================================================================
ENTRY-POINT ARCHITECTURE — four entry points, four different pipelines.
This section answers "how is it SUPPOSED to work vs how does it ACTUALLY work".
================================================================================

## F142 — *** THE ACTIVE PAPER PIPELINE HAS NO RISK LAYER AT ALL *** · CRITICAL
CLAUDE.md states the platform's status as "paper trading active". `run.py`
routes that mode to `PaperRunner`, NOT to the engine every other finding in this
audit examined:
    run.py:372-380   _paper_mode = PAPER_TRADING == "true"
                     if _paper_mode or args.broker == "paper":
                         from execution.paper_runner import PaperRunner
                         runner = PaperRunner(); await runner.run()
    run.py:387-394   else: from hopefx_engine import HopeFXEngine

THE ACTUAL PAPER PATH (execution/paper_runner.py:689-758 `_tick_loop`):
    OandaPricePoll (REST poll)          :96
      -> OHLCVBuffer (builds bars from ticks)   :186
        -> InferenceSignalAdapter (ML on bar close)   :304
          -> bus.publish(CH_ORDER, {symbol, direction, units, mid,
                                    confidence, timestamp})       :731-744
            -> FIXRouter._route()  (execution/fix_router.py:320)
              -> paper broker

WHAT IS NOT IN THAT PATH — verified by reading `_route` in full (:320-360):
    if self._halted:            <-- kill switch, the ONLY gate
        return
    symbol    = order_request.get("symbol", "XAU/USD")
    direction = order_request.get("direction", "BUY").upper()
    units     = float(order_request.get("units", DEFAULT_UNITS))
    ... straight to _send_paper / _send_fix
  * NO RiskManager.assess()      * NO pre-trade gate
  * NO position sizing           * NO Kelly, no risk-per-trade, no equity scaling
  * NO stop-loss or take-profit  — neither is in the order_request payload
  * NO ExecutionEngine           — so none of its OTel/TCA/gate logic applies
  * NO drawdown check            * NO exposure or correlation limit

SIZE IS A FIXED CONSTANT. paper_runner.py:87
    _ORDER_UNITS: float = float(os.environ.get("PAPER_ORDER_UNITS", "1000"))
and :657 passes it verbatim into every order_request. Every trade is 1000 units
regardless of equity, volatility, confidence or open exposure.

The only safety control on this path is the kill switch, reached through
FIXRouter's breach listener (:309-314, halts on kill_switch_active / kill_event /
kill_switch).

This reframes a large part of the audit. F45/F59 (no working stop-loss),
F60/F61/F107 (broker call breaks), F63 (unit confusion), F84 (data-layer gate
bypass), F88 (empty StrategyManager) all describe `hopefx_engine` /
`ExecutionEngine` — the path used in LIVE mode. The path actually running today
does not reach that code at all. It is simpler, and it has less protection, not
more: the risk stack those findings describe as broken is not merely broken here,
it is absent.
Severity CRITICAL: this is the running configuration, and an ML signal becomes a
broker order with one boolean between them.

## F143 — `--dry-run` describes a live pipeline that does not exist · HIGH
`run.py --dry-run` exists so an operator can confirm what is about to start
before committing real money. `_get_pipeline` (:317-341) is called from exactly
one place — `_print_plan` at :302 — i.e. it is display text only.

For LIVE mode it promises:
    "EventBus (Redis pub/sub)"
    "FaultGuard (circuit breaker + heartbeat)"
    "NewsCalendarFeed (ForexFactory → Redis)"
    "MarketIngest (XAUUSD ticks via ccxt.pro)"
    "StrategyEngine (ML signal — AdvancedModelPredictor)"
    "Gatekeeper (prop-firm risk checks)"
    "FIXRouter (order execution + OANDA REST fallback)"
Live mode runs `HopeFXEngine`. Counting occurrences in hopefx_engine.py:
    FaultGuard 0   MarketIngest 0   NewsCalendarFeed 0   Gatekeeper 0
    FIXRouter 0    EventBus 0
All six classes DO exist in the repo (utils/fault_guard.py, data/market_ingest.py,
data/news_calendar_feed.py, risk/gatekeeper.py, execution/fix_router.py) — this
is a stale description of a superseded architecture, not fiction. But five of the
six are genuinely not in the live path:
  * Gatekeeper — risk/manager.py names it only in DOCSTRINGS (:221 "consumed by
    Gatekeeper", :666 "Consumed by Gatekeeper and execution pipeline"). No
    import, no call. The documented consumer does not consume.
  * FIXRouter — zero hits in execution/engine.py, brokers/factory.py, execution/oms.py.
  * EventBus is the one exception: execution/engine.py does use it, so it is in
    the live path indirectly.
What HopeFXEngine actually wires (:377-589): RiskManager, HopeFXBrain,
SniperEntryEngine, AdvancedPredictor, risk_orchestrator, PositionTracker, OMS,
ExecutionEngine, NuclearStrategyAgent, OANDAStream/MT5Bridge, BrokerFactory,
drift_monitor.
The PAPER description is accurate by contrast — OandaPricePoll, TickSignalEngine,
FillRecorder are all real members of paper_runner.py.
Severity HIGH: the one tool whose entire purpose is telling an operator what will
run is wrong about the money-moving mode.

================================================================================
AUTH (2,395 LOC) — previously only auth/jwt.py had been read.
================================================================================

## F144 — login is user-enumerable by timing, despite an enumeration-safe message · MEDIUM (proven by measurement)
auth/service.py:427-430, in `login`:
    if not user:
        _record(False, "user_not_found")
        return False, "Invalid credentials", None
The RESPONSE is identical for a missing user and a wrong password — the author
deliberately avoided message-based enumeration, and elsewhere uses a named
constant `_ENUMERATION_SAFE_VERIFY_MESSAGE` (router.py:627) for the same reason.

But the not-found branch returns BEFORE any password hashing happens, while the
user-exists branch runs bcrypt at cost factor 12 (auth/jwt.py:180). There is no
dummy-hash compensation anywhere in the file (grepped for dummy/_DUMMY/
constant.time/timing — no hits).

MEASURED with the real functions:
    user EXISTS  (bcrypt runs) :   268.75 ms
    user MISSING (early return):     0.0021 ms
    observable difference      :   268.74 ms
269 ms is far above any plausible network jitter, so a single request reveals
whether an address is registered.

MITIGATIONS THAT ARE REAL — checked before assigning severity:
  * `/login` carries `Depends(_login_rate_limit_dep)` (router.py:635), an IP
    rate limit defaulting to 10 requests per 60 s
    (`AUTH_RATE_LIMIT_REQUESTS` / `AUTH_RATE_LIMIT_WINDOW_SECONDS`, :197-198).
  * Every attempt is written to `LoginAttempt` with ip_address and
    failure_reason (:404-416), so enumeration leaves an audit trail.
  * Brute-force lockout is Redis-backed with a DB fallback and is cross-pod
    (:432-436).
At 10 requests/minute a bulk sweep is slow, but a targeted check — "is this
person a customer?" — is one request. Severity MEDIUM. The standard fix is to
verify against a fixed dummy hash on the not-found path so both branches pay the
same bcrypt cost.

## AUTH — VERIFIED CLEAN (recorded so it is not re-audited)
  * TOTP FAILS CLOSED. auth/service.py:235-258 defines the TOTP helpers twice —
    once against pyotp, once in an `except ImportError` fallback whose
    `verify_totp` logs "pyotp not installed — 2FA verification always fails" and
    returns False. That is the correct posture, and notably the OPPOSITE of the
    ImportError fail-opens in security/self_healer.py (F132) and auth/jwt.py's
    revocation check (F133).
  * NO EVENT-LOOP BLOCKING. AuthService is synchronous by design and its
    docstring claims "auth/router.py already applies this pattern for all 16
    call-sites". Verified: 17 `asyncio.to_thread` uses in router.py and ZERO
    unwrapped direct service calls.
  * Passwords are bcrypt cost 12 with a BLAKE2b pre-hash (auth/jwt.py:178-181).
  * Tokens are issued as HttpOnly cookies, with the refresh cookie scoped to
    /api/auth/refresh (router.py:643-647).
  * Login attempts are recorded for BOTH outcomes, with IP and failure reason.

================================================================================
RESEARCH / ML PIPELINE — the root cause of F24.
================================================================================

## F145 — *** F24's ROOT CAUSE: missing features are zero-filled BEFORE scaling, so the model sees extremes, not neutrals *** · CRITICAL (proven by computation)
F24 recorded that 48.2% of model features are zero-filled live. This is the
mechanism, and it makes the finding materially worse than "zero-filled" implies.

The training pipeline DOES persist a feature contract:
    research/pipeline/orchestrator.py:533  self._feature_cols = list(X_train_df.columns)
    research/pipeline/orchestrator.py:603  "feature_cols": self._feature_cols,   -> run_meta.json
and the predictor DOES read and align to it — ml/__init__.py:311, :326-330:

    if self._feature_cols:
        for col in self._feature_cols:
            if col not in X_in.columns:
                X_in[col] = 0.0            # <-- silent fill, RAW space
        X_in = X_in[self._feature_cols]
    X_in = X_in.replace([np.inf, -np.inf], np.nan).fillna(0.0)

    if self._scaler is not None:           # :335-337
        X_in = self._scaler.transform(X_in)

Alignment is correct in principle — the ordering is what breaks it. The fill
happens in RAW feature space and the scaler runs AFTERWARDS, so a missing
feature reaches the model as `z = (0 - mean) / std`, not as 0.

COMPUTED for feature scales typical of a gold model:
    feature                    mean       std    z the model sees
    RSI_14                    50.00     15.00              -3.33   extreme
    close price             3000.00    200.00             -15.00   extreme
    ATR_14                    12.00      4.00              -3.00
    volume                 50000.00  20000.00              -2.50
    spread                     0.40      0.15              -2.67
    MACD_hist                  0.00      1.50               0.00   neutral
    pct_return_1               0.00      0.01               0.00   neutral

Only features already centred on zero land anywhere near neutral. Every feature
on a natural scale — price, RSI, ATR, volume, spread — is pushed to a value the
model saw almost never in training. With 48.2% of the vector missing, the model
is not being handed an incomplete observation; it is being handed a confident
description of a market that has never existed.

That the model still reports OOS 0.5734 is consistent with this: the live
inference distribution is not the distribution it was validated on.

THE CORRECT FIX IS ORDERING, NOT THE FILL VALUE. Fill after scaling (so 0.0
means "at the training mean"), or better, refuse to predict when coverage falls
below a threshold — the engine already computes exactly that number (see below).

TWO SMALLER FAIL-OPENS ON THE SAME PATH:
  * ml/__init__.py:337-339 — `scaler.transform` failure is caught and logged at
    DEBUG, and the UNSCALED frame is then passed to the base learners.
  * ml/__init__.py:344-350 — a base learner raising in predict_proba substitutes
    0.5 (neutral). That one is reasonable and logged at WARNING.

## F146 — the inference engine already MEASURES this, and the measurement is not wired to a refusal · HIGH
ml/inference_engine.py:231-241 tracks, with the failure named in its own comment:
    # A stats file whose feature names do not match what the model produces
    # leaves the guard measuring nothing while looking healthy, so coverage
    # is part of "active" rather than a separate diagnostic.
    self._drift_covered: int = 0
    self._drift_total: int = 0
    self._drift_uncovered: list[str] = []   # WHICH features are unwatched
The author identified precisely the train/serve mismatch in F145 and instrumented
it — coverage counts, plus the names of the uncovered features so an operator can
see which. What is missing is the step from measurement to refusal: nothing
blocks a prediction when coverage is 51.8%. This is the same shape as the
recurring pattern (§3.3 of PLATFORM_ARCHITECTURE.md) — the control exists, is
correct, and does not gate anything.

## RESEARCH PIPELINE — VERIFIED CLEAN
  * SYNTHETIC DATA IS OFF BY DEFAULT AND TRAIN-ONLY.
    orchestrator.py:101  use_synthetic_augment: bool = False  # (slow; off by default)
    orchestrator.py:550-551  augments X_train/y_train ONLY — the TimeGAN output
    never touches validation or test. Correct practice; the obvious way to get
    this wrong is to augment before splitting, and it does not.
  * `is_synthetic` and `is_forward_filled` are excluded from the feature set
    (orchestrator.py:328), so the augmentation flags cannot leak as predictors.
  * research/pipeline/paper_trading_gate.py exists as a named promotion gate
    rather than models being shipped straight from training.
