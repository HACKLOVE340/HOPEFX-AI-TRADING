# CLAUDE.md

Guidance for Claude Code (and other AI assistants) working in this repository.

This file is intentionally short. The authoritative, detailed guides are:

- **[AGENTS.md](AGENTS.md)** — full agent guide: layout, conventions, testing, ML, workflows.
- **[ARCHITECTURE.md](ARCHITECTURE.md)** — canonical module map, key entry points, env flags.
- **[CONTRIBUTING.md](CONTRIBUTING.md)** — contribution workflow.
- **`.claude/skills/flow-by-flow/SKILL.md`** — start every development task here;
  its sibling `flow-prototype` owns the UI/UX approval surface. Both are installed
  and version-locked at `2.0.1`; see the Agent Skills section of AGENTS.md.

Read those before any non-trivial change. The notes below are the high-signal subset.

---

## Picking up mid-programme — start here

If you are joining this work rather than starting it, **run this first**:

```bash
python scripts/backlog_report.py        # what is left, measured from the code
```

It reads the registries, the specifications and the working tree, so its answer
is always today's. Everything below is the shape; that command is the state.

| Question | Where it is answered |
|---|---|
| **How does this branch reach `main`?** | `docs/audit/LANDING_PLAN.md` — 656 commits and 1,558 files ahead, cut into nine reviewable slices with a proven recipe. Read it before opening a pull request. |
| **What do I fix next?** | **`docs/audit/CORRECTION_REGISTER.md`** — one entry per finding, each with the fix, the test to write first and the command that proves it. Status is probed from the code by `python scripts/correction_register.py`, not typed, so it cannot quietly go stale. **Start here.** |
| **I am picking up the frontend / AI-presence work — what is done and what is next?** | **`docs/audit/FRONTEND_HANDOVER.md`** — what was built and why it is shaped that way, what is left in the order to do it, what is deliberately NOT worth doing, and the six traps this thread actually fell into. Start there before the plan. |
| What was the frontend plan, and which parts are done? | `docs/audit/plans/2026-09-15-frontend-ultra.md` — Tasks 1–2 landed, 3–11 open. The handover above supersedes it where they differ, because it was measured later. |
| What is outstanding, and what must the owner decide? | `docs/ai/MASTER_OUTSTANDING.md` — §A is decisions only the owner can make |
| What is left, in what order, and how long? | `docs/ai/PROGRAMME_PLAN.md` — audit, sequence and effort, measured 2026-09-09 |
| Which spec capabilities are live, staged or planned? | `python scripts/backlog_report.py` · `ai/hub/capabilities.py` |
| Which safety gates have been proven able to fail? | `python scripts/gate_evidence.py` · `docs/GATE_EVIDENCE.toml` |
| What does the AI OS specification require that this repo does not yet enforce? | `python scripts/aos_conformance.py` · `docs/ai/specs/AOS_INVARIANT_REGISTER.toml` |
| What can the spatial/3D system claim, and what must it refuse to? | `docs/ai/specs/SPATIAL_INTELLIGENCE.md` · `ai/spatial/assurance.py` · `invariants/spatial.py` |
| Which spatial capabilities actually exist, measured? | `python scripts/spatial_capabilities.py` · `docs/ai/specs/SPATIAL_CAPABILITIES.toml` |
| Why does the light/dark toggle change nothing *yet*? | `frontend/src/index.css` now defines both themes and the document ground follows them; the 189 files that still paint their own literals do not (201 at the audit; 1,777 literals reached the token layer on 2026-09-14). `python scripts/frontend_colour_ratchet.py --check` · `docs/FRONTEND_COLOUR_DEBT.json` |
| Why are there still emoji where icons belong? | `python scripts/frontend_emoji_ratchet.py --check` · `docs/FRONTEND_EMOJI_DEBT.json` |
| How are the four specification groups organised? | `docs/ai/BACKLOG_GROUPS.md` |
| What binds every group? | `docs/ai/specs/GROUP4_CONSTITUTION.md` — T0, twelve Articles, INV-01…21 |
| How do I recover the database? | `docs/runbooks/database-restore.md` |
| How do I run the model without a market feed? | `python scripts/predict_offline.py` · `ml/cached_series.py` |
| Is the feature-drift guard running, and what is it measuring? | `python scripts/drift_guard_report.py` · ADR 0019 — most of today's z is zero-filled features, not drift |
| Do we know the identity of the model artifacts we ship? | `python scripts/model_provenance_report.py` · `ml/saved_models/model_checksums.json` |
| Which model loaders reach no integrity check at all? | `python scripts/model_provenance_report.py --check` · `docs/MODEL_PROVENANCE_DEBT.json` |
| Does every ORM table have a migration, or only `create_all()`? | `python scripts/schema_migration_check.py --check` |
| Which controls have no accessible name? | `cd frontend && npm run lint` · `frontend/a11y-debt.json` |
| What is the standard page, and which pages are not on it yet? | `frontend/src/components/system/PageShell.tsx` — four widths replace twelve, a consistent header (or the page's own, via the `hero` slot), and a footer that is derived rather than forgotten. 61 of 62 migrated — only `/terminal` is off, by the owner's decision. `python scripts/frontend_page_shell_ratchet.py --check` · `docs/FRONTEND_PAGE_SHELL_DEBT.json`. The gate reads code, not prose: it was `"PageShell" in text` until 2026-09-15, when a `// TODO: migrate this page to PageShell` comment was shown to clear it |
| Which pages actually show live data, and which are static? | `python scripts/frontend_data_reachability.py` — measures the IMPORT GRAPH, not the page file. 70 of 73 routed pages reach live data (67 in their own file, 3 through a child or the store); the three that do not are `DocsPage`, `PrivacyPolicy` and `TermsAndRiskDisclosure`, and all three are documents. It does not block: a static page is a legitimate page. It replaced a hand-grepped list in FRONTEND_HANDOVER.md that named five already-wired pages as needing a fetch |
| Why does every page have a "Where to next" footer now? | `PageSurface` renders one for any page that does not claim the slot, so a page cannot be a dead end. Links come from `frontend/src/lib/related.ts`, derived from navConfig. `npx vitest run src/test/no_page_is_a_dead_end.test.tsx` |
| What is the AI presence's face doing, and what decided it? | `frontend/src/hub/headModes.ts` — eleven modes (panicking · refusing · worried · concerned · speaking · listening · mimicking · detection · reaction · awareness · dormant), each chosen by `chooseHeadMode` from the same measurements the presence machine reads. There is no `setMode`: a settable mood is a decorative live value with a face. `npx vitest run src/test/the_head_has_modes.test.ts` |
| Why is the head a shaded hologram and not an ellipse? | `frontend/src/hub/head.ts` — `headMesh` gives it volume and orientation, `faceRelief` gives it a face (brow, sockets, nose, lips, chin), and `headSurface` gives it a lit surface. The old head was an outline, and an outline has no orientation. Colours are `--holo` / `--holo-bright` in `index.css`, read at runtime because a canvas is not the cascade. `npx vitest run src/test/the_head_has_a_skull.test.ts src/test/the_head_has_a_face.test.ts src/test/the_head_is_lit.test.ts` |
| Why is the head's surface cached? | One head is ~900 quads, and canvas has no way to draw them but a fill and a stroke each. Twelve heads on a review page measured **3.1 FPS**; the surface is now painted once per pose into an offscreen canvas and blitted, and one 460px head measures **44.8 FPS with one `drawImage` per frame**. `PresenceCore.tsx::drawSurface` |
| How does the head on every page know the platform is talking? | `frontend/src/hub/speechBus.ts` — speech was component state inside `useVoice`, so `PresenceAnywhere`'s mouth was painted shut on every page while the assistant spoke. `npx vitest run src/test/the_head_everywhere_hears_the_voice.test.ts` |
| Why does the sidebar only show 14 things now? | `frontend/src/components/sidebar/navConfig.ts` — items carry a `hub`, and `frontend/src/pages/Hub.tsx` renders what is behind each one. 61 destinations, nothing removed; `npx vitest run src/test/nav_hub_reachability.test.ts` fails if any becomes unreachable |
| How is a page's density and palette chosen? | `frontend/src/components/system/PageSurface.tsx` — one table, stamped on every route as `data-density` and `data-surface`, plus the person's own setting from `frontend/src/lib/densityPref.ts` (Settings → Appearance → Density). Tiers are `comfortable` / `promax` / `ultra`, `ultra` by default; AI routes get the instrument palette. The preference overrides the table in both directions with one floor it cannot cross: a data surface never loosens below `ultra`, because how many rows of open risk fit on screen is not a taste question |
| Why do the terminals show flat candles, and nothing at 1h? | Two separate things, both diagnosed 2026-09-15 and neither in the chart code. **Flat candles:** the bars really are flat — measured on the daily series the platform serves offline, 62 of 500 have no body or no wicks. `frontend/src/lib/barQuality.ts` says so on all four live charts instead of drawing them silently. Timestamp conversion is `frontend/src/lib/chartTime.ts` — one copy, after five diverging ones of which two placed a pre-2001 millisecond bar in the year 32,633. **Nothing at 1h:** XAUUSD has no intraday source without a live feed — its yfinance ticker is deliberately empty (Yahoo delisted it, verified 2026-07-26; a previous hand-maintained copy served delisted `GC=F` futures as spot) and the bundled CSV is daily/weekly only. The endpoint correctly 503s with the feed to configure rather than fabricating. Do not put a yfinance ticker back. **And note the asymmetry:** `/ai-chart-dashboard` renders six panels at 1h, and five of those six symbols (EURUSD, GBPUSD, USDJPY, BTCUSD, ETHUSD) have a working yfinance ticker — XAUUSD, the instrument this platform trades, is the one that does not. The 503 now names the timeframes bundled history CAN serve, so an operator can tell a broken timeframe from a broken instrument. |
| Why does changing the density barely change anything? | It reaches less than it should. `data-density` is real and proven live in a browser (gap 16→10→7px, body 15→13→12px, card padding 20→14→10px), but literal pixels are not in the cascade. 763 inline font sizes were converted on 2026-09-15 and **2,108** remain, with 1,089 numeric spacing utilities. Same defect as the colour literals, in the size dimension. `python scripts/correction_register.py --id DENSITY-CANNOT-REACH` |
| What stops the unreachable-size count growing while that is decided? | `python scripts/frontend_size_ratchet.py --check` · `docs/FRONTEND_SIZE_DEBT.json` — 3,198 sizes the density control cannot reach (2,107 inline `fontSize`, 1,091 numeric spacing utilities) across 194 files, held at a baseline that may only fall. Same rule as the colour ratchet, including that a file reaching zero must have its line DELETED. `scripts/correction_register.py`'s DENSITY-CANNOT-REACH probe imports its counter, so the gate and the register cannot print different numbers for the same thing |
| How do I retire an inline font size? | `python scripts/frontend_size_codemod.py --check` · `--apply`. Only substitutes a number byte-identical to a type-scale token at the DEFAULT density, so nothing moves at `promax` and the other two tiers gain 763 call sites. Never inside a canvas or chart-option call, and never in an expression — `fontSize: 13 + offset` is arithmetic. `--check` ranks the sizes that sit BETWEEN tokens (12px ×638, 11px ×532) and need a decision per site rather than a substitution |
| How do I retire a colour literal? | `python scripts/frontend_token_codemod.py --check` · `--apply`. Only substitutes literals that are byte-identical to a token, and never inside a canvas or chart-option call — `var()` is resolved by the cascade, and a canvas is not the cascade |
| What colour, size, spacing or duration should I use in the frontend? | `frontend/src/index.css` — the token layer: both themes, a seven-step type scale, a pro-max density scale, and the `data-surface="ai"` instrument palette. Reach them through the Tailwind roles in `tailwind.config.ts` (`bg-surface`, `text-dim`, `text-title`, `p-card`), never a literal. `frontend/src/test/design_tokens.test.ts` holds the set complete |
| Which committed price history is safe to train on? | `ml.cached_series.CLEAN_SINCE` — 2020+ for XAUUSD; `scripts/clamp_ohlc.py` for the rest |
| Which documents are authoritative, and who owns them? | `docs/REGISTRY.toml` |
| A document states a figure — is it still true? | `python scripts/doc_metrics.py --check` · `--sync` (what `pre-commit` runs) maintains the two per-commit figures and checks the rest |
| Why is it like this? Who decided, and what was rejected? | `python scripts/adr.py --list` · `docs/decisions/` |
| How did that decision actually turn out? | `docs/decisions/outcomes/NNNN.md` — the ledger half of Chapter 9 (ADR 0020). `adr.py --check` refuses a missing outcome or an overdue review |
| What did the platform decide today, and what did it refuse? | `ai/ledger/decisions.py::summary()` · refusals are first-class entries |
| What was this release *for*? | `python -m deployment.change_records --report` · trading-path commits should carry an `Expected-Effect:` trailer — a warning, not a block |

**Every number in those documents is a snapshot; every number the scripts print
is current.** Where they disagree, the script is right and the document is stale
— fix the document.

The ratcheted checks below run in `pre-commit`, so a regression blocks rather
than accumulating: document registry, documentation freshness, Group 4 source
preservation, volume-index drift, gate injection evidence, stated-figure drift,
per-module coverage, frontend colour literals, frontend sizes the density
control cannot reach, frontend emoji, ungated model
loaders, ORM tables without a migration, AOS invariant conformance, spatial
capability evidence, and correction-register drift.

**They only block once the hook is installed.** Until 2026-09-09 nothing
installed it, so on a fresh clone that sentence described something that was not
happening — every one of those gates protected only whoever remembered
`pre-commit run --all-files` by hand. `python scripts/bootstrap_dev.py` now runs
`pre-commit install`; if you cloned before that, run it, or run `pre-commit
install` directly. See MASTER_OUTSTANDING §E20.

### Standing rule from the owner — documentation ships with every push

**Never push code without updating the documents it makes stale.** Not "when it
seems worth it" — every push. A document that still looks current while carrying
a number that stopped being true is worse than no document, because a reader
acts on it without checking.

Concretely, before every commit:

1. If you changed what a gate, registry or ledger measures, run the script and
   update every document that states its figure.
   `python scripts/doc_metrics.py --check` blocks on the ones it can verify.
2. If you added a file a contributor must find, name it in the routing table
   above and in `ARCHITECTURE.md`.
3. If you closed a ranked gap, strike it through in the Group 2 or Group 3 gap
   list **with its evidence**, and update `docs/ai/MASTER_OUTSTANDING.md`.
4. If a document and a script disagree, the script is right — fix the document.

The commit message carries the reasoning; the documents carry the state. A
successor gets both or neither.

---

## What this is

HOPEFX is a Python/FastAPI + React/Vite AI trading platform for XAUUSD (gold):
ML inference, risk management, and multi-broker execution. Backend is a FastAPI
app; frontend is a React/TypeScript SPA. Status: paper trading active; live OANDA
is the next milestone.

This is a **money-moving system**. Prefer targeted, verified changes over broad
rewrites. Never weaken a risk gate, kill switch, or staleness/drift check without
explicit instruction.

---

## Canonical vs. legacy directories (common pitfall)

Add new code to the **canonical** dir, never the legacy shim:

| Domain | Use (canonical) | Do NOT add code to |
|--------|-----------------|--------------------|
| Backtesting | `backtesting/` | `backtest/` (re-export shim) |
| Strategies | `strategies/` | `strategy/` (live ML engine only) |
| Data pipeline | `data_layer/` for market-data *access* | *(nothing — see the note below)* |

WebSocket work goes in `api/ws_live.py`. The old standalone `websocket/`
server is **deleted** — never recreate a top-level `websocket/` package: it
shadows the `websocket-client` library for the whole project and silently
disables the REST fallback in `market_data/mt5_live_feed.py` (audit S13-02a).

Import market-data *access* via the public surface only:
`data_layer.orchestrator`, `data_layer.tick_store`, `data_layer.feeds.*`.

**`data/` is live runtime infrastructure.** These three docs used to describe it
as legacy data files, which was wrong and actionable: it told contributors to put
tick-feed and depth-of-market work in `data_layer/`, splitting one subsystem
across two packages (F216). The measured reality:

| Package | LOC | Production importers | What it is |
|---|---:|---:|---|
| `data_layer/` | 19,610 | 86 | Market-data **access**: orchestrator, tick store, feed adapters. The canonical public surface. |
| `data/` | 6,259 | 20 | Live **streaming and serving**: `real_time_price_engine.py`, `scheduler.py`, `depth_of_market.py`, `tick_feed.py`, `time_and_sales.py`, `streaming.py`, `feeds/macro.py`. Constructed in `core/startup_factories.py`, mounts three HTTP routers via `core/router_registry.py`, and `ml/training.py` reads its macro feed. |
| `market_data/` | 4,031 | 6 | Broker-side feeds, e.g. `mt5_live_feed.py`. |

**The boundary is now decided — ADR 0013, 2026-09-09.** It is a rule, not a
refactor, and it describes what the code already does:

* **`data/`** — live streaming and serving. The price engine, scheduler,
  depth-of-market, tick feed, time-and-sales, streaming, macro feed.
* **`data_layer/`** — market-data **access**. Orchestrator, tick store, feed
  adapters. The canonical public surface.
* **`market_data/`** — broker-side feeds.

This paragraph previously said the boundary was documented nowhere and that this
file would not invent one (F217). That was right at the time — inventing a
boundary without the owner is how a guess becomes a convention — and it left the
defect class live, so contributors kept splitting one subsystem across two
packages.

It does **not** authorise moving existing code across the line. A module on the
wrong side stays there until there is a reason beyond tidiness: the 106
production importers are the cost, and they have not changed.

---

## Key entry points

| File | Purpose |
|------|---------|
| `app.py` | FastAPI app factory, startup/shutdown lifecycle |
| `hopefx_engine.py` | Standalone engine: NuclearStreamer → Brain → Risk → Broker |
| `run.py` | CLI runner (`--mode paper \| live \| api \| backtest`) — `engine` is NOT a mode; `run.py --help` is the source |
| `core/decision/HOPEFXDecisionEngine.py` | Central 5-phase decision pipeline |
| `ml/inference_engine.py` | Live inference with stale/drift gating |
| `risk/manager.py` | Pre-trade gate, VaR/CVaR, Kelly sizing, kill switch |
| `execution/oms.py` | Order Management System |
| `api/server.py` | FastAPI router aggregator |

---

## Commands

```bash
# Backend
python scripts/bootstrap_dev.py     # one-time: .env + dev users + install the git hooks
python run.py --mode api            # run FastAPI (port 8000)

# Tests (Python)
pytest -m "not slow and not e2e"    # fast suite (what CI runs)
pytest tests/unit/ -m "not slow"    # unit only
pytest --cov=. --cov-report=term-missing

# Lint / format (run before committing)
ruff check .                        # lint — must be clean
ruff format .                       # format
pre-commit run --all-files          # full gate (ruff, bandit, detect-secrets, merge-conflict)

# Frontend (frontend/)
npm ci && npm run dev               # Vite dev server (port 5173)
npm run typecheck && npm run build  # tsc --noEmit + vite build
npm test                            # vitest
```

Test markers: `unit`, `integration`, `e2e`, `slow`, `requires_redis`, `asyncio`.
`e2e` and `slow` are always skipped in CI.

---

## Before committing — non-negotiable

1. `ruff check .` is clean and the files you touched **compile**
   (`python -m py_compile <file>`).
2. **Run the hooks** — `pre-commit run --all-files`. They are configured
   (ruff, bandit, detect-secrets, and `check-merge-conflict`) but only protect
   you if you actually run them. Do **not** commit with `--no-verify`:
   that is exactly how merge-conflict markers and lint regressions slip in.
3. No leftover conflict markers (`<<<<<<<`, `=======`, `>>>>>>>`).
4. Never commit secrets or real credentials. `prop_firm_mode.json` and
   `.env.example` carry **placeholders only**.

---

## Skills — use them, every time

**Standing instruction from the owner (2026-09-06): use the relevant skills on
every task, always.** Not "when it seems worth it" — every time. They exist
because this codebase has cost real money to get wrong, and each one encodes a
class of mistake already made here.

`.claude/skills/` holds **55** skills (`licenses/` is not one). All of them are
listed below. An earlier version of this file listed only thirteen "the ones
that earn their keep most often" — that was wrong in a way that mattered: a
skill nobody can see is a skill nobody loads, and the omitted 48 included every
Python-craft, observability, threat-modelling and incident skill in the set.

It held 61 until 2026-09-11. Six were removed and one added, for overlap rather
than for irrelevance: `planning-workflows` routed to slash commands this
repository does not have, `review-automation-orchestrator` was a dispatcher over
skills already listed here, `skill-authoring` was merged into `writing-skills` (its one unique section — a prohibition on remote skill-fetch URLs — and all six of its reference files carried over rather than lost), and
the four threat skills were four entry points to one activity — now
`threat-modelling`, with all 83,746 bytes of their reference material preserved
verbatim. Nothing was removed for being unused: a single session's log is a
sample, not a measurement, and almost every skill's subject genuinely exists in
this repository. See `.claude/skills/README.md` for the evidence behind each.

### Always, on every task

| Skill | When |
|---|---|
| `flow-by-flow` | **Start every development task here.** Picks mode, depth and risk floor, and names the affected flows. |
| `brainstorming` | Before any *creative* work — a new feature, component, or behaviour change. Explores intent before implementation. |
| `test-driven-development` | Before writing implementation code, for every feature and every bugfix. |
| `verification-before-completion` | Before claiming anything is done, fixed, or passing. Evidence before assertions. |
| `systematic-debugging` | The moment anything surprises you — a bug, a failing test, an unexpected result. |

### HOPEFX-specific — these encode defects already made here

| Skill | When |
|---|---|
| `hopefx-money-precision` | Prices, quantities, lot sizes, notional, P&L, balances, equity, fees, commissions; any Decimal↔float boundary; any reconciliation tolerance; any `==` on a monetary value. |
| `hopefx-invariants` | `verify_*` / `catastrophic_*` predicates, `enforce_*` call sites, `HOPEFX_INVARIANT_MODE`, fail-closed behaviour, or a refused pre-trade check. |
| `hopefx-dead-controls` | Any gate, guard, kill switch, health probe, alert, or "is it safe" check — **especially** when it looks correct but you have not traced that it runs. |
| `hopefx-fix-bridge` | `brokers/ibkr_fix_bridge.py`, `execution/fix_adapter.py`, FIX 4.4 sessions, sequence numbers, logon/heartbeat/reconnect, XAUUSD symbol mapping. |

### Planning and execution

| Skill | When |
|---|---|
| `writing-plans` | A spec or multi-step task, before touching code. |
| `executing-plans` | A written plan to execute with review checkpoints. |
| `using-git-worktrees` | Feature work needing isolation from the current workspace. |

### Review

| Skill | When |
|---|---|
| `requesting-code-review` | Completing a task or major feature, before merging. |
| `receiving-code-review` | Acting on review feedback — verification, not performative agreement. |
| `code-review-excellence` | Reviewing PRs, setting review standards. |
| `pr-review-fix` | Triaging CI failures and review comments across open PRs in batch. |
| `codebase-audit` | Full codebase review, severity triage, issues, worktree fixes. |
| `doc-freshness-review` | Documentation drift — `docs/`, `CLAUDE.md`, `AGENTS.md`, `ARCHITECTURE.md`, `CONTRIBUTING.md`, `README.md`, `DEPLOYMENT.md`. |

### Python craft — reach for these by symptom

| Skill | When |
|---|---|
| `python-resilience` | Retries, exponential backoff, timeouts, fault tolerance, transient failures. |
| `python-error-handling` | Input validation, exception hierarchies, partial/batch failure. |
| `python-resource-management` | Context managers, cleanup, connections, file handles, streaming. |
| `python-background-jobs` | Task queues, workers, event-driven work, long-running operations. |
| `async-python-patterns` | asyncio, concurrency, async/await, I/O-bound systems. |
| `python-type-safety` | Type hints, generics, protocols, mypy/pyright configuration. |
| `python-testing-patterns` | pytest, fixtures, mocking, test suite structure. |
| `python-anti-patterns` | Checklist before finalising an implementation or when debugging a smell. |
| `python-performance-optimization` | Profiling with cProfile/memory profilers; slow code, bottlenecks. |
| `python-observability` | Structured logging, metrics, tracing, debugging production. |

### Trading, ML and data

| Skill | When |
|---|---|
| `backtesting-frameworks` | Look-ahead bias, survivorship bias, transaction costs, strategy validation. |
| `risk-metrics-calculation` | VaR, CVaR, Sharpe, Sortino, drawdown, risk limits. |
| `ml-pipeline-workflow` | End-to-end MLOps: data prep → training → validation → deployment. |
| `data-quality-frameworks` | Validation rules, data contracts, tick/feed quality and freshness. |
| `lightweight-charts` | TradingView lightweight-charts — series, scales, realtime data, plugins. |

### API, data storage and services

| Skill | When |
|---|---|
| `api-design-principles` | Designing or reviewing REST/GraphQL APIs and API standards. |
| `fastapi-templates` | New FastAPI apps, async patterns, dependency injection. |
| `postgresql-table-design` | PostgreSQL schema design or review — types, indexes, constraints. |

### Security and compliance

| Skill | When |
|---|---|
| `threat-modelling` | Threat modelling a system or feature, end to end: STRIDE → attack paths → controls that actually run → security requirements and test cases. Names this platform's four trust boundaries. |
| `sast-configuration` | Static analysis / DevSecOps scanning setup. |
| `k8s-security-policies` | NetworkPolicy, PodSecurity, RBAC. |
| `pci-compliance` | Handling payment card data. |
| `stripe-integration` | Stripe checkout, subscriptions, webhooks, refunds. |

### Operations, observability and incidents

| Skill | When |
|---|---|
| `prometheus-configuration` | Metric collection, storage, alerting rules. |
| `grafana-dashboards` | Operational dashboards and metric visualisation. |
| `distributed-tracing` | Jaeger/Tempo, request flows across services. |
| `slo-implementation` | SLIs, SLOs, error budgets. |
| `incident-runbook-templates` | Step-by-step runbooks, escalation paths, recovery. |
| `on-call-handoff-patterns` | Shift handoffs, mid-incident transfer, on-call onboarding. |
| `postmortem-writing` | Blameless postmortems, root cause, action items. |

### UI, UX and frontend

| Skill | When |
|---|---|
| `ui-ux-pro-max` | **Any UI work** — styles, palettes, typography, charts, accessibility. Has a pre-delivery checklist; run it. |
| `flow-prototype` | Prototyping a complete interactive flow across screens and states **before** production UI. Owns the approval surface. |
| `frontend-design` | Visual direction — typography and aesthetics that do not read as templated defaults. |
| `e2e-testing-patterns` | Playwright/Cypress suites, flaky-test debugging. |
| `webapp-testing` | Driving a local web app with Playwright; screenshots, browser logs. |

### Skill maintenance

| Skill | When |
|---|---|
| `writing-skills` | Creating/editing skills and verifying them before deployment. |
| `manage-local-skills` | Standardising and syncing local skills into agent directories. |

---

Two rules that come from those skills and are worth repeating here, because
they are the ones most often skipped under time pressure:

1. **Every fix ships with a test that fails on the pre-fix tree.** Run it
   against the old code — `git stash`, run, `git stash pop` — and watch it
   fail. A test that has never failed proves nothing.
2. **Prove by execution, not by reading.** Reproduce the defect by running it
   before you fix it, and re-run the same reproduction after. Nine of the
   defects found in this repository read as correct.

## Gotchas

- **Python 3.12** is the production target — it is what `Dockerfile` runs
  (`python:3.12-slim`). CI tests **3.11 and 3.12**; the retrain workflows also
  run 3.12 so model artifacts are pickled on the same interpreter that loads
  them in production.
  This previously said 3.10 "matches the Docker image", which was false in both
  directions: the image was already 3.12, and 3.10 was tested by nothing.
  Because the stated reason for pinning is pickle compatibility on the
  committed `.pkl` artifacts, anyone following that advice produced artifacts
  under an interpreter neither CI nor production ever loaded. If you change the
  Dockerfile's Python, change the retrain workflows in the same commit.
- Model `.pkl`/`.zip` artifacts under `ml/saved_models/` and `ml/rl_models/`
  are **intentionally committed** (whitelisted in `.gitignore`).
  `dashboard/dist/` is **intentionally committed** so the server can serve the
  UI without a build step. Don't "clean these up."
- **Only one model artifact is checksum-verified in CI.** This line used to say
  the artifacts under both directories were, which is not what runs.
  `ci.yml:398` runs `python -m ml.verify_model`, and that verifies the sha256 of
  the single **active** model named in `ml/saved_models/registry.json`. Nothing
  verifies `ml/rl_models/` at all, and no workflow or hook reads
  `ml/saved_models/model_checksums.json`. **The runtime does, though** — this
  bullet previously said nothing read it, which was wrong in the direction that
  matters: `ml/__init__.py::_verify_checksum` reads the manifest on every model
  load and is fail-closed in production. That manifest **was** wrong from its
  first commit — 2 mismatches and 1 listed-but-absent, so two artifacts did not
  load in production while `python -m ml.verify_model` exited 0 because it was
  not looking at them. **Resolved: 11 entries, 11 files, all verifying under
  `APP_ENV=production`** (§A8 has the evidence and what settled each side).
  `python scripts/correction_register.py --id A8` re-measures it; do not take
  this sentence's word for it.
  **And running the suite used to break it.**
  `tests/unit/test_coverage_boost_ml_misc.py::test_oos_eval_returns_dict` called
  `oos_eval` without redirecting `MODEL_DIR`, so every run rewrote the committed
  `xgb_macro_oos.pkl`. It was invisible on Python **3.11**, where the retrained
  bytes are byte-identical to the committed ones — the tree stayed clean and the
  provenance ratchet passed having never been exercised. On **3.12**, which is
  what the Dockerfile runs, the bytes differ and the artifact stops verifying: a
  green suite produced a model production refuses to load. `tests/conftest.py`
  now refuses any write to the 11 manifest artifacts, so the next such writer
  fails loudly. `--id SUITE-REWRITES-MODEL`. **Run the suite on 3.12 as well as
  3.11 before trusting it** — this defect is invisible on 3.11 by construction.
  Still true and still open: `_try_load` returns `None` for both "absent" and
  "integrity refused", so a caller cannot tell them apart; 7 artefacts on disk
  are in no manifest; and 12 of 14 ML modules reach no integrity check at all,
  `ml/inference_engine.py` among them. `python
  scripts/model_provenance_report.py --check` holds those at their baseline so
  they cannot grow.
- `WORDMAP.json` is gitignored; copy from `WORDMAP.json.example` locally.
  `prop_firm_mode.json` is **not** — `.gitignore` commits it deliberately with
  placeholder credentials so CI has a config to load. This file previously said
  it was gitignored, and the file's own `_comment` said so too, which invites
  putting real credentials in a tracked file. Keep credentials in environment
  variables. Note it also ships `enabled: true` with the FTMO ruleset, so a
  fresh deployment starts with those prop-firm limits active.
- **An API deployment carries a trading engine unless you say otherwise.**
  Production runs `python app.py` (the Dockerfile's CMD), which builds the
  component registry; the registry registers `engine`, and
  `init_trading_engine` auto-starts it whenever `TRADING_MODE` is not `live` —
  `ENGINE_AUTOSTART` defaults to **true** on that branch. Live is properly
  gated and needs `ENGINE_AUTOSTART=true` **and** `LIVE_TRADING_ENABLED=true`,
  so the exposure is paper rather than real money, but "the API process is
  healthy" has never meant "the engine is or is not running".

  | Want | Set |
  |---|---|
  | API only — serve HTTP, trade nothing | `ENGINE_AUTOSTART=false` |
  | API + paper engine (the default) | leave `ENGINE_AUTOSTART` unset |
  | Live | `ENGINE_AUTOSTART=true` **and** `LIVE_TRADING_ENABLED=true`, plus the kill switch and deployment gates |

  `GET /health` reports `engine` as `unavailable` / `stopped` / `healthy`, so
  the choice is visible from outside the process. It is deliberately NOT part of
  the overall verdict — an API-only deployment has no engine by design, and a
  permanently "degraded" field is one operators learn to ignore.
  `ENGINE_AUTOSTART` was documented nowhere until 2026-09-14 (audit F58/F118).
- **The committed model is 167 days old and the freshness gate now blocks on
  it.** `_check_model_staleness()` used to read the artifact's filesystem
  mtime, so deploying a stale model was how the staleness gate got cleared: the
  clone rewrites the timestamp, the gate read "0.69 days", and the check that
  exists to stop the platform trading on an out-of-date model passed because the
  out-of-date model had just been copied. Age now comes from a timestamp bound
  to the artifact's sha256 in `ml/saved_models/registry.json`, which is a
  property of the bytes — copying, touching or re-registering cannot change it.
  With `MODEL_MAX_AGE_DAYS=30` and `STALE_MODEL_BLOCK=true` (both defaults),
  **inference is now refused** until a current model is registered. That is the
  gate working. Do not raise the limit or disable the check to get trading back:
  that restores exactly the behaviour the fix removed. See
  `python scripts/correction_register.py --id MODEL-166-DAYS-OLD` — it measures
  the shipped artifact, so it closes itself when a current model is registered —
  and `--id MODEL-AGE-IS-MTIME` for the defect.
- **Chat history is per user, not per worker.** `POST /api/brain/chat` held one
  module-level `LLMAgent` for the whole process, so every user of a worker
  shared one conversation — reproduced with two identities, where user A's
  account number appeared verbatim in user B's outgoing prompt. Conversations
  are keyed on (authenticated `sub`, client session label); `ChatRequest`
  carries no user field, because an identity in the body is an identity the
  caller chooses. `--id CHAT-SHARED-HISTORY`.
- `test-results.xml` is a CI-generated artifact — never commit it.
</content>
</invoke>
