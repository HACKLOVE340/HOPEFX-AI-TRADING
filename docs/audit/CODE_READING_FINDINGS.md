# HOPEFX — Code-Reading Audit Log (in progress)

Findings from a read-only pass over the actual source, not the docs. Every entry
was verified against code at the file:line cited; entries that dissolved on
inspection are recorded as retracted rather than deleted, so they are not
re-found later and re-reported as bugs.

**Status: in progress.** ~95 files read directly by me, plus 4 of 8 completed domain audits (execution, brokers, ML, payments). Eight
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
