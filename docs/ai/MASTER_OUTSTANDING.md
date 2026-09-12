# What is left to build, fix or pick

**Tier:** T2 — canonical reference · **Owner:** hacklove340 · **Status:** current as at 2026-09-08

> **Updated the same day** when the complete Group 4 document (Volumes I–XX)
> arrived. What it changed is in §F. It did not shrink this list; it added two
> constitutional Articles, one new High item, and one new control.

This is the single place that answers "what is outstanding". It has two halves and
they are not equally trustworthy, so they are separated:

* **§A — Decisions only the owner can make.** Four of them. Nothing below them
  moves until they are picked, and each is stated with what it costs either way.
* **§B — Work.** Ranked, with the measurement behind each item.

> **The numbers in §B go stale.** They were measured on 2026-09-08. Re-run
> `python scripts/backlog_report.py` for the current ones — that command reads
> the registries, the specifications and the code, and its answer is always
> today's. A list typed into a message is wrong the moment somebody acts on it.
> This document holds the *shape* of the backlog; the report holds the numbers.

---

## §A — Decisions to pick

These are not blocked on engineering. They are blocked on someone deciding.

### A1. Backup and restore — how much recovery is enough? *(partly delivered)*

**Delivered in Phase R1**, because it did not need the decision: `database/restore.py`
verifies before it restores and refuses six ways a backup arrives worthless, and the
round trip is proven by execution — SQLite in the fast suite, a real `pg_dump`
restored into a real PostgreSQL 16.13 database with matching checksums in the
integration suite. `celery_app.database_backup` now verifies what it wrote.
`docs/runbooks/database-restore.md` is the 3am procedure.

**Building it found two live defects a survey could not have:**

* **SQLite backups of a WAL database restored to nothing.** Committed rows live in
  the `-wal` sidecar; the backup copied the main file alone. Reproduced by
  execution. The nightly job logged success every time. **Any SQLite backup taken
  before 2026-09-08 is suspect** — the runbook carries a sweep that finds them,
  and `--verify` refuses them by name.
* **`pg_dump` was buffered entirely in memory** before writing, so a
  production-sized database would have exhausted the worker mid-incident.

**Still yours to pick, and now the only thing blocking the rest:**

| Question | Why it cannot be defaulted |
|---|---|
| **RPO** — how much data may be lost? | Today it is **24 hours by schedule, not by decision**. That number came from a cron entry, not from anyone weighing it |
| **RTO** — how long may a restore take? | Decides whether snapshots are enough, or whether this needs WAL archiving and point-in-time recovery |

Those two answers decide whether PITR gets built. Everything else in this item is
done and tested.

### ~~A2. `data/` ÷ `data_layer/` — where does new market-data code go?~~ · **DECIDED 2026-09-09 — ADR 0013**

> Split by role, as a rule rather than a refactor: `data/` owns streaming and
> serving, `data_layer/` owns access, `market_data/` owns broker-side feeds.
> No code moves. The reasoning below is kept as the record of why it was open.

**The measurement.** `data_layer/` is 19,610 LOC with 86 production importers;
`data/` is 6,259 LOC with 20; `market_data/` is 4,031 with 6. All three are live.
**The boundary between them is documented nowhere.**

**The cost of not deciding:** it already caused one defect class — contributors
were told to put tick-feed and depth-of-market work in `data_layer/`, which
splits one subsystem across two packages. The holding position (extend whichever
package the module already lives in, and say which in the PR) is workable but
guarantees the split widens.

**Recommendation:** decide it as a one-paragraph ADR, not a refactor. The
refactor can wait; the rule cannot.

### ~~A3. Nightly `slow` and `e2e` runs — pay the CI minutes or not?~~ · **DECIDED 2026-09-09 — ADR 0014**

> Nightly, not per-PR. Measured: **209 tests** carry those markers and have
> never gated anything. The reasoning below is kept as the record.

**The measurement.** Both markers are skipped in CI, always. Process isolation
(`ai/jobs/isolation.py`) is specified in detail and **exercised by nothing that
runs**. So is a good deal of the e2e surface.

**Either way costs something:** running them nightly costs CI minutes; not
running them means the isolation guarantees are claims. This needs a decision,
not a default — the default is already in force and it is "never run them".

### A4. Does Group 2 own deterministic auto-remediation?

**The line drawn** in Group 2 Chapter 16 is *"does it require a hypothesis?"* —
auto-rollback on an error-rate breach is a threshold (Group 2); auto-rollback on
an anomaly score is inference (Group 1). It has not yet met a borderline case.
Not urgent. Recorded so the first borderline case is decided rather than drifted.

### A5. The frontend colour codemod — do we spend 2–3 sessions to revive three features?

**Not a design question.** The design system is already chosen and correct:
twelve semantic tokens in `frontend/src/index.css`, a working `ThemeContext`, a
user-facing light/dark/system control, and `tailwind.config.ts` wired for
`[data-theme="dark"]`. Nothing needs deciding about *what* the colours should be.

**What needs deciding is whether to pay for the wiring.** 8,021 hardcoded hex
literals across 202 files (measured — `python scripts/frontend_colour_ratchet.py
--check`), almost all inside inline `style={{…}}` objects, which cannot
participate in a cascade. Until they are tokens:

* the light/dark toggle changes nothing on screen — it is a dead control;
* a white-label tenant's brand colour cannot reach the product it brands;
* five different greys keep drifting apart as "muted text".

| Option | Cost | What it leaves |
|---|---|---|
| **Do the codemod** — map 210 literals onto the 12 tokens, add a `[data-theme="light"]` block | 2–3 sessions, one large mechanical diff across 202 files | Three features alive; a themeable product |
| **Leave it** | nothing now | Ship with a toggle that does nothing and a white-label feature that cannot brand. Both currently *look* delivered, which is the part that costs later |
| **Partial** — tokens only in the pages a white-label tenant actually sees | ~1 session | Branding works where it is sold; the toggle stays dead elsewhere |

**Already done and not waiting on this decision:** the ratchet
(`scripts/frontend_colour_ratchet.py`, in pre-commit, 26th gate in
`GATE_EVIDENCE.toml`). The number can no longer grow, so the codemod is worth
doing whenever it is done, and stays done afterwards. Full evidence in §E26.

### A6. Two paper-trading engines, and an import decides which one runs

`brokers/__init__.py` defines a 623-line `PaperTradingBroker` at lines 280–902,
then at line 1274 rebinds the name:

```python
try:
    from brokers.paper_trading import PaperTradingBroker as _PTB
    PaperTradingBroker = _PTB
except Exception as _exc:
    logger.warning("PaperTradingBroker import failed: %s", _exc)
```

Normally the local class is unreachable — measured: no package attribute points
at it, and `create_broker("paper", …)` builds `brokers.paper_trading`'s. But it
is not dead code. Block that import and the same call builds the local one
instead, announced by a single WARNING:

```
PaperTradingBroker import failed: simulated: brokers/paper_trading.py is broken
create_broker('paper') -> brokers.PaperTradingBroker
```

So the platform carries two paper-trading engines with different fill
simulation, different slippage, different commission accounting and different
persistence, and which one runs depends on whether an import succeeded. Nobody
has characterised how their results differ, and a paper P&L is what the live
decision is sized against.

**What needs deciding is which one is the paper broker.**

| Option | Cost | What it leaves |
|---|---|---|
| **Delete lines 280–902** and let a failed import fail loudly | ~1 session, plus whatever `create_broker` should do instead | One engine. A broken `paper_trading.py` becomes an error instead of a silent substitution |
| **Keep the fallback and characterise it** | 2+ sessions — the two engines need a differential test before either can be trusted | Two engines, known to agree, and a WARNING nobody reads |
| **Leave it** | nothing now | A failure mode that changes which trading engine runs and says so once, at WARNING |

**Why this is here and not just done:** deleting 623 lines removes a fallback,
and removing a fallback is a behaviour change on the money path. Found while
raising `brokers/__init__.py` for the coverage-floor programme — the class
accounts for most of the module's uncovered 28%, and testing an engine that
only runs in an uncharacterised failure mode is the wrong order of work.
`brokers/__init__.py` therefore stays in `docs/COVERAGE_UNMEASURABLE.txt` with
this decision named, which the programme allows: "to the floor **or to a stated
decision**".

---

### A7. Which of our own model artifacts do we actually know the identity of?

Prompted by a framing the owner brought on open-weight versus open-source
models: weights alone are the finished product, not the recipe. Pointed inward,
at a repository that **commits** its models and trades on them, it asks whether
our own artifacts are open-weight to us or open-source to us — and the first
thing that question exposes is not reproducibility, it is identity.

Measured — `python scripts/model_provenance_report.py`, `APP_ENV=production`:

```
LISTED BUT ABSENT: 1 · MISMATCH: 2 · NOT LISTED: 2 · ok: 13
```

* **Two committed artifacts no longer hash to their recorded digest** —
  `ml/saved_models/feature_scaler.pkl` and `ml/saved_models/stacking_ensemble.pkl`.
  `ml._verify_checksum` returns `False` for both under `APP_ENV=production`,
  which is the gate working correctly. Nobody has decided whether the file or
  the record is the right one.
* `model_checksums.json` lists `lstm_signal.pt`, which is not committed.
* `ml/saved_models/rl/hopefx_ppo.zip` and `ml/rl_models/nuclear_decision_ppo.zip`
  are in no baseline at all.
* Four of the five model directories **self-baseline in production**:
  `_bootstrap_allowed` exempts any directory that is not the packaged one. That
  exemption is right for `ML_MODEL_DIR`, where an operator's retrain job writes
  and no shipped baseline can exist. It is wrong for `GCF/`, `XAU_USD/`, `rl/`
  and `rl_models/`, whose contents are committed — there, the check establishes
  its reference from the artifact it is meant to verify.
* **Two of the fourteen modules that load a model artifact reach any integrity
  check**, and they reach different ones. There are two systems —
  `ml._verify_checksum` against `model_checksums.json` (fail-closed in
  production) and `_verify_integrity` against `registry.json` (fail-open by
  documented design). `ml/inference_engine.py`, named in CLAUDE.md as the live
  inference entry point, reaches neither.

**The exemption is not theoretical, and measuring it tripped it.** Writing this
entry, `ml._verify_checksum` was called directly on three artifacts with
`APP_ENV=production`, to see what the gate would say. It did not merely answer.
Because `_bootstrap_allowed` exempts every directory that is not the packaged
one, the call *wrote three new trust baselines* — into
`ml/saved_models/GCF/`, `ml/saved_models/XAU_USD/` and `ml/rl_models/` —
recording as canonical whatever happened to be on disk at 23:34 on 2026-09-11.
They were deleted, not committed: committing them would have settled the third
question below by accident, in the direction of "whatever a session found is now
the reference". A check that establishes its own baseline is not a check, and
the easiest way to see that is to watch it happen.

**The decision is not "go fix the hashes."** Recomputing a mismatched digest to
match the file destroys the only evidence that the two ever disagreed, and
`scripts/resave_models.py` will do exactly that if pointed at this. What needs
deciding:

| Question | Why it is the owner's |
|---|---|
| For the two mismatches — is the **file** current and the record stale, or the record right and the artifact substituted? | Only the person who ran the retrain knows. The answer decides whether to re-record or to restore. |
| Should committed subdirectories lose the self-baselining exemption? | Tightening a gate is allowed without instruction, but this one would start refusing loads that succeed today. |
| One integrity system or two? | `model_checksums.json` and `registry.json` are different records with different failure stances over overlapping files. |
| Do the other twelve loaders need a check, or are they off the money path? | `ml/inference_engine.py` plainly is not. The rest need triage before work. |

**Already done and not waiting on this decision:**
`scripts/model_provenance_report.py` measures all three surfaces and repairs
nothing. `tests/unit/test_model_provenance_report.py` puts each bad condition on
disk and asserts the report names it, so its numbers are numbers it could have
printed differently, and two more tests assert the report writes nothing — it
must not become the thing it reports on. Four mutations were run against it,
including one that makes the report call the writing gate: it recreated the same
three baseline files, and the tests caught it.

**Genuinely third-party weights** are a much smaller surface than the phrase
"our AI" suggests: the LLM vendors in `ai/gateway/vendors.py` — Moonshot,
DeepSeek, Qwen, Mistral, Groq, xAI, OpenRouter, Together — are **hosted APIs**,
so no weights are downloaded and the open-weight question does not arise; what
governs them is each vendor's terms, not a model licence. The one downloaded
open-weight dependency is `ProsusAI/finbert` via `sentence-transformers` in
`data_layer/sentiment/engine.py`. Its licence is recorded nowhere in this
repository, which is worth fixing whatever is decided above.

---

### A8. The advanced risk engine reports zero risk, and its kill switch cannot fire

`MonteCarloRiskEngine.add_asset` is the only public way to put an asset into the
engine. It fits a GARCH model and records the returns column. **It never fits
the copula.** `calculate_portfolio_risk` then hits its own first guard —

```python
if not self.garch_models or not self.copula.marginals:
    return RiskMetrics(var_95=0.0, var_99=0.0, cvar_95=0.0, ...)
```

— and returns all zeros. Measured, using nothing but the public API:

```
after add_asset x2:
  garch_models     ['EURUSD', 'XAUUSD']
  copula.marginals {}
  risk -> RiskMetrics(var_95=0.0, var_99=0.0, cvar_95=0.0, cvar_99=0.0,
                      volatility=0.0, max_drawdown=0.0, tail_risk=0.0,
                      correlation_stress=0.0)
  violations       []
  kill switch      False

after e.copula.fit(e.historical_returns) by hand:
  var_95 = -0.000375   cvar_95 = -0.000459
```

The guard's comment says it returns zero metrics "when no assets have been
added". Two assets *had* been added. The condition it tests is not the condition
it describes, and the difference is the whole defect.

Downstream, `_check_limits` compares `0.0 < -0.02`, `0.0 < -0.03` and
`0.0 < -0.10`. All three are False, always. So `_trigger_kill_switch` is
unreachable through the public API — the purest form of the
`hopefx-dead-controls` first sub-shape, a guard that can never open.

**A second, smaller one in the same class:** `self.limits` declares
`"tail_risk": 3.0` and `_check_limits` never reads it. Three of the four
declared limits are enforced. The unenforced one is the tail-risk limit, which
is precisely the limit that exists to catch what VaR misses.

**What needs deciding is whether this engine should work or go.**

| Option | Cost | What it leaves |
|---|---|---|
| **Fit the copula lazily** in `calculate_portfolio_risk` from `historical_returns` | ~1 session incl. tests | An engine that computes. But `CopulaRiskModel.fit` runs `stats.johnsonsu.fit` per column — expensive, and it can fail to converge on real returns, inside what is now a risk call |
| **Make `add_asset` refit the copula** each time | similar | Simpler to read; O(n²) fitting as assets are added |
| **Delete the engine** | ~1 session of removal | No production module constructs it. `core/acceleration/gpu_engine.py` re-exports it and nothing else does |
| **Leave it** | nothing now | A risk engine that answers "no risk" and a kill switch that cannot fire, both of which currently *look* implemented |

**Why this is not just fixed:** no production module constructs
`MonteCarloRiskEngine` or `RealTimeRiskMonitor`, so this is latent rather than
live — and "make the risk engine compute different numbers" is not a change to
take without the owner, even when the current numbers are zero. Deleting it may
well be the better answer, and that is not a call for a coverage task.

**Already done and not waiting on this decision:** `core/risk/__init__.py` no
longer ships a stale copy of the engine (`a84bcf58`), and
`GARCHModel.forecast` no longer returns a volatility of exactly zero on a
non-stationary fit — it had two failure modes selected by whether `omega` was a
Python `float` or an `np.float64` from `fit`.

---

### A9. Three encodings of "which spellings mean long"

`database.models.Position.side` is a free-text `String(10)`. Three places in
this repository independently answer the question "does this value mean long?",
and they do not agree:

| Where | Encoding | Covers |
|---|---|---|
| `database/repositories/position_repository.py:147` | SQL `case` | `"long"`, `"buy"` |
| `brokers/base.py:207` | `_SIDE_BUY_ALIASES` | `"BUY"`, `"LONG"`, `"buy"`, `"long"` |
| `core/position_reconciler.py` | `_LONG_SIDES`, added today | `"buy"`, `"long"`, case-insensitively |

Before today the reconciler's answer was `== "buy"` alone, and a long stored as
`"long"` had its unrealized P&L written to the database with the sign inverted.
That is fixed. The duplication is not, and it is the same shape that produced
two `PaperTradingBroker` classes (§A6) and two risk engines (`a84bcf58`): one
fact, several copies, drifting apart at different rates.

**What needs deciding is where the answer lives.** The reconciler cannot simply
import `brokers/base.py` — that executes `brokers/__init__.py`, the whole broker
package with its optional-SDK guards, and inverts the core-to-brokers
dependency. So the options are:

| Option | Cost | What it leaves |
|---|---|---|
| **A neutral module** both can import, under `core/` and free of broker imports | ~half a session, three call sites | One encoding. The SQL case still has to mirror it by hand, because it runs in the database |
| **Constrain the column** to an enum at the schema level | a migration, plus every writer | The question stops existing. Most work, most durable |
| **Leave three copies** and test each | nothing now | They drift again, and the next divergence is another inverted number |

**Why this is not just done:** picking where a shared constant lives is an
architecture decision, and `CLAUDE.md`'s canonical-directory table is the sort
of thing it would need a line in. Raised from Task 5e of the coverage-floor
programme, which found the defect it caused.

---

### A10. The position reconciler prices XAUUSD off Yahoo Finance, and skips the cycle when it cannot

`PositionReconciler._get_price` is the only price source the reconciliation loop
has:

```python
import yfinance as yf
ticker = yf.Ticker(symbol)
hist = ticker.history(period="1d", interval="1m")
if not hist.empty:
    return float(hist["Close"].iloc[-1])
except Exception as _exc:
    logger.debug("Suppressed exception: %s", _exc)
return None
```

Two things follow, and the second is the serious one.

**It is the wrong feed.** This platform has `data_layer/` — an orchestrator, a
tick store, feed adapters — and a live price engine in `data/`. The reconciler
reaches past all of it for a free equities API, using the platform's own symbol
spelling. Yahoo does not quote `XAUUSD`; its gold tickers are `GC=F` and
`XAUUSD=X`. No translation happens here.

**A `None` skips everything.** `_reconcile_once` does:

```python
price = await self._get_price(pos.symbol)
if price is None:
    continue
```

So a symbol the feed cannot price gets no P&L update, no drift comparison
against the broker, no contribution to the aggregate book value that the
reconciliation invariant checks, and no exposure figure. The position is simply
absent from the cycle. The only trace is one `logger.debug`, which is off in
production.

That is the first `hopefx-dead-controls` sub-shape wearing a feed: the guard
below it can never open, because the value it guards on never arrives. The
reconciler is constructed in production at `core/startup_factories.py:2829`, and
`stats` would report cycles climbing and `mismatches` at zero — a healthy-looking
counter for a loop that reconciled nothing.

**What needs deciding is which feed the reconciler uses.**

| Option | Cost | What it leaves |
|---|---|---|
| **Read `data_layer.orchestrator`**, the canonical market-data surface | ~1 session, plus deciding what a stale tick means to a reconciler | One feed, the platform's own, with the staleness machinery already built |
| **Keep yfinance and map the symbols** | ~half a session | A second market-data path, a third-party dependency on the reconciliation loop, and rate limits |
| **Leave it** | nothing now | A reconciliation loop that may be skipping every position while its cycle counter climbs |

**Whatever is chosen, the `logger.debug` should be an ERROR** — a reconciler that
cannot price a position is not a debug-level event. That much is not a design
question, but it is not changed here either, because raising the level without
fixing the feed would turn a silent no-op into a log flood, and the two belong
in one commit.

**Already measured, not fixed:** `tests/unit/test_position_reconciler_gates.py`
covers all three `_get_price` outcomes, including the one where the whole cycle
is skipped, so the behaviour is pinned while the decision is open.

---

### A11. `outbox_events.idempotency_key` has two schemas, and the code only works under one

`database/models.py:1263` declares the column with `unique=True`. The migration
that adds it to an existing table —
`alembic/versions/n1o2p3q4r5s6_add_journal_subaccounts_billing_profiles.py:237`
— adds it without:

```python
sa.Column("idempotency_key", sa.String(128), nullable=True),
```

So `outbox_events` has one shape if the database was built by
`Base.metadata.create_all` (tests, a fresh deployment) and another if it was
built by migrations (any upgraded environment). Nothing compares them.

It decides whether live code runs. `OutboxRelay._relay_batch` skips a duplicate
by looking for *another* row with the same key that is already published:

```python
already = (session.query(OutboxEvent)
           .filter(OutboxEvent.idempotency_key == row.idempotency_key,
                   OutboxEvent.published_at.isnot(None),
                   OutboxEvent.id != row.id).first())
```

Under a UNIQUE column two such rows cannot exist, so `already` is always `None`
and the branch is unreachable by construction. Under the migrated shape it
works as written. Found by a test that inserted two rows with the same key and
died on an `IntegrityError`.

**What needs deciding is which shape is correct**, and that is a question about
what the key is for:

| Option | Cost | What it leaves |
|---|---|---|
| **UNIQUE is right** — the database rejects the duplicate at write time | a migration adding the constraint, plus handling `IntegrityError` at every `write_outbox_event` call site | Duplicates impossible. The relay's skip branch is then dead code and should be deleted rather than left looking load-bearing |
| **Non-unique is right** — duplicates are tolerated and the relay de-duplicates | a migration dropping `unique=True` from the model | The relay branch is live and is the mechanism. Fresh deployments stop differing from upgraded ones |
| **Leave it** | nothing now | Two schemas, one of which silently disables a de-duplication guard, and no test that would notice |

**Why this is not just done:** it is a migration either way, on a compliance
audit table, and which direction is correct depends on whether a duplicate
`idempotency_key` is an error to refuse or a condition to absorb. That is the
owner's call.

**Already done:** `tests/unit/test_outbox_relay_against_a_real_db.py` covers
both shapes — one test asserts the `create_all` constraint exists, another
builds the migrated shape and drives the skip branch through it — so whichever
way the decision goes, the behaviour under both is pinned.

---

### A12. Two latent defects in `ml/signal_features.py`, both about a number changing meaning

Raised together because neither has a production caller — `ml/regime.py` imports
only `FeatureVector` — and both are the same species: a value that keeps its
name while changing what it means.

**`volume_trend_{p}` depends on how much history you passed.** It is
`mean(volumes[-p:]) / mean(volumes[-2p:-p]) - 1`, and `extract_features` admits
any series of at least `max(lookback) + 10` bars — 60 for the defaults
`[5, 10, 20, 50]`. For `p = 50` the denominator slice `[-100:-50]` then clamps
to whatever exists. Measured on identical rising volume:

```
 60 bars -> +0.2871   (numerator 50 bars, denominator 10 bars)
 80 bars -> +0.3493   (numerator 50 bars, denominator 30 bars)
100 bars -> +0.4016   (numerator 50 bars, denominator 50 bars)
```

Same market, three answers. A model trained on long windows and served from a
short buffer is fed a different feature under the same column name — train/serve
skew, arriving silently.

**`confidence` is documented `# 0 to 1` and is not bounded.**
`SignalEnsemble.predict` computes `abs(probability - 0.5) * 2`, and
`_get_model_prediction` takes whatever `predict()` returns. A regressor is under
no obligation to return 0–1, so a model answering 2.5 yields a confidence of
4.0. Anything sizing a position off that reads four times the stated maximum.

**What needs deciding.** Both fixes change behaviour:

| | Option | What it costs |
|---|---|---|
| volume_trend | require `2 * max(lookback)` bars | `extract_features` starts returning `None` for 60–99 bar inputs it accepts today |
| | compute the denominator over the bars available and name the feature for it | the feature stops being comparable across window lengths, which is the honest version of what it already does |
| confidence | clamp the probability to [0, 1] at `_get_model_prediction` | a model returning 2.5 is silently truncated rather than flagged — arguably it should raise |
| | raise on an out-of-range probability | a live ensemble starts throwing where it used to return a number |

Availability versus correctness on a feature path, twice. The owner's call.

**Already done:** `tests/unit/test_ml_signal_features.py` pins both, each in a
class whose docstring says it is recording the behaviour rather than blessing
it, and each with an assertion message telling the next reader to update this
entry if the behaviour changes. The suite also holds the property that matters
most in a feature module — causality: appending future bars must not change any
value computed earlier, asserted per indicator.

---

### A13. A causal guarantee asserted by two layers and disclaimed by the third

Three modules describe the same mechanism. The bottom one is honest; the two
above it are not, and they cite each other.

**`data_layer/orchestrator.py::get_ml_features` — the producer, accurate:**

> Causal guarantee (IMPORTANT — partial):
>   - HONORED by `as_of`: sentiment, macro calendar, temporal features.
>   - NOT honored (always reflect CURRENT live state): microstructure,
>     tick-quality, and FRED macro features…
>   Consequently, calling this with a PAST `as_of` … leaks present-time
>   micro/tick/macro data into a row labeled causal — look-ahead bias.
>   **Do NOT use the micro/tick/macro features in a causal training or
>   walk-forward pipeline.**

**`ml/features_extended.py::add_data_layer_features` — the consumer:**

> `as_of` : If provided, only use data available at this timestamp
> (**causal guarantee for backtesting**).

**`data_layer/replay/engine.py` — the caller:**

> **Causal guarantee** — … The ML pipeline's `add_data_layer_features(as_of=cursor)`
> **enforces this at the feature level.**

So the replay engine names the consumer as its enforcement, the consumer
advertises a guarantee, and the producer states in terms that three of its
feature groups do not provide one. `backtesting/replay_connector.py` wires the
replay engine into `BacktestEngine`.

**And the injection is constant regardless.** `get_ml_features()` returns a dict
of scalars — one moment's reading — and each is assigned `d["dl_x"] = scalar`,
which pandas broadcasts to every row. Measured with a live orchestrator
returning non-zero values, on a 500-bar frame spanning 2023-01-01 to 2023-01-21:

```
dl_spread      first=0.35   last=0.35   distinct=1
dl_macro_vix   first=17.9   last=17.9   distinct=1
36 of 36 dl_ columns constant
```

Two consequences. Within one frame, 36 zero-variance columns cannot inform a
split and contribute nothing. Across frames built at different moments, the
constant becomes a proxy for *when the frame was built* — concatenate a Monday
and a Tuesday batch for training and `dl_macro_vix` tells the model which batch
a row came from.

**What needs deciding.**

| Option | Cost | What it leaves |
|---|---|---|
| **Make the injection per-row** — reconstruct each feature point-in-time from stored history | large: the orchestrator would need point-in-time reads for micro/tick/macro, which it says it does not have | Features that mean what their name says, and a real causal guarantee |
| **Drop the non-causal groups** from any training path and keep them live-only | ~1 session | Honest features, fewer of them. The replay engine loses its claim and should stop making it |
| **Correct the two docstrings** and leave the behaviour | hours | The code is unchanged but nobody is misled into training on it. Minimum honest action |
| **Leave it** | nothing now | Two documents asserting a guarantee their own foundation disclaims, above a backtest path |

**Why this is not just fixed:** the third option is safe and I could have taken
it, but correcting a docstring to say "these features are not causal" without
deciding what happens to the pipeline that consumes them would leave a
contradiction of a different kind — a backtest path knowingly fed non-causal
features. The three belong in one decision.

**Already done:** `tests/unit/test_ml_features_extended_data_layer.py` pins the
constancy, the per-call variation across moments, `as_of` reaching the
orchestrator, and the NaN/inf scrub, each with an assertion message pointing
back here if the behaviour changes.

---

### A14. Three gaps in the pre-trade gates, found while covering `execution/engine.py`

The engine carries seven checks between a signal and a broker. They are well
built and they fail closed — six mutations against them all die. These three are
what the coverage work turned up around the edges.

**1. `_check_margin` raises `ValueError` where it promises to block.** Its
docstring says "any unexpected exception from the broker API blocks the trade
rather than allowing it through". The handlers cover `(AttributeError,
TypeError)` and `(RuntimeError, OSError)`. A non-numeric string — the shape a
malformed JSON account payload actually takes — makes `float()` raise
`ValueError`, which is neither:

```
_check_margin(...) -> ValueError: could not convert string to float: 'not a number'
```

`_check_leverage` has the identical pair of handlers and the same `float()`
calls. **Whether `execute()` compensates is not established.** In every
configuration tried, an earlier data-layer gate blocked first and the margin
check was never reached, so the question could not be answered from outside.
`execute()` does document "Returns ExecutionReport — never raises", so it may
well hold; it was not demonstrated.

**2. An order with no price skips both the margin and the leverage gate.** Both
compute `notional = price * quantity` and return early when it is not positive:

```python
if notional <= 0:   # _check_margin
    return None
if price <= 0:      # _check_leverage
    return None
```

The comment justifies it — the margin impact of an order you cannot price is not
computable, so blocking would be a false positive. The condition that produces
it, though, is price enrichment having failed: no data layer, no tick feed.
Measured: the same order, same account with `margin_available=0` and
`margin_used=1,000,000`, is blocked with a price and permitted without one.

**3. Self-trade prevention is off whenever its module is unavailable.**
`_check_self_trade` catches `(ImportError, AttributeError, TypeError,
RuntimeError)`, logs at **DEBUG**, and returns `None` — which means allow. The
docstring states the choice ("Non-fatal on STP unavailability"), so it is
deliberate; the level is the problem. DEBUG is not emitted in production, so a
market-abuse control being off leaves no trace an operator would see. This is
`hopefx-dead-controls` sub-shape 4 verbatim.

**What needs deciding.**

| | Option | Note |
|---|---|---|
| 1 | Add `ValueError` to both handler tuples | Small and strictly fail-closed. The only reason it is not done here is the programme's rule against behaviour changes inside a coverage commit |
| 2 | Block an unpriced order instead of skipping | Turns a missing price into a refusal to trade — safer, and a availability change on the market-order path |
| 2 | Require enrichment to succeed before the gates | Moves the decision earlier, same trade |
| 3 | Raise the STP swallow from DEBUG to ERROR | Explicitly allowed by CLAUDE.md ("Raising a log level is not weakening"). Needs no decision beyond noticing |

**Already done:** `tests/unit/test_execution_engine_gates.py` pins all three —
the `ValueError` as it is, the priced/unpriced contrast on the same account, and
the STP fallthrough — each with a docstring saying it records the behaviour
rather than endorses it.

---

---

### A15. The attack feed on the security dashboard can only ever read zero

`GET /api/security/attacks` backs the KPI strip on `SecurityDashboard.tsx`. Both
stores behind it — `security.monitor._event_buffer` and
`api.security_dashboard._attack_log` — are written by exactly one function each,
and **neither function has a caller anywhere in the repository**:

```
$ grep -rn "record_attack" --include="*.py" . | grep -v ./.venv
./api/security_dashboard.py:96:def record_attack_event(...)     <- a different function
./security/monitor.py:31:def record_attack(event) -> None:      <- the definition
```

`record_attack_event`'s own docstring says *"Called by middleware / auth
rate-limiter to record an attack."* Nothing calls it. The endpoint therefore
returns `{"events": [], "total": 0}` whatever is happening to the platform —
shown to an operator who is looking at it precisely because they suspect
something is wrong. Recorded as F273.

**Why this is not a patch.** Three questions have to be answered before anything
is wired, and none of them has a defensible default:

| Question | Why it cannot be defaulted |
|---|---|
| **Which events count as attacks?** | Failed logins, 429s, invalid JWTs and SQLi probes have wildly different base rates. Pick wrong and the feed is either empty or unreadable |
| **Where does the recorder run?** | Middleware sees every request and costs on every request; the auth rate-limiter sees only the interesting ones and misses unauthenticated probes |
| **What does it cost per request?** | This is the request path of a money-moving system. A deque append is free; anything that touches Redis on the hot path is not |

**Holding position:** the buffer's semantics are pinned by
`tests/unit/test_security_monitor_feed.py` (newest-first, bounded, a total that
keeps counting past the window it can hold), so the day it is wired the
behaviour is already specified. The feed stays honestly empty until then —
which is better than the alternative only because nobody currently believes it.
That last part is the risk: the dashboard does not say "not wired", it says
"0 attacks".

### A16. Which router owns the lockdown path, and should clearing it reach Redis?

Fixing F272 — the admin lockdown switch that reported success and moved nothing
— surfaced two things that are ownership questions rather than defects.

**1. `lift()` does not undo what `trigger()` did.** What actually stops traffic
is `HOPEFXBrain.trigger_full_lockdown`, which sets `lockdown:active` in Redis
with a 3600-second TTL; `core/health.py:204` reads that key and fails the pod's
readiness probe. `LockdownManager.trigger` fires it.
`LockdownManager.lift` has no matching call, so clearing the lockdown through
the dashboard flips the in-process flag and leaves the Redis key set until the
TTL expires — the pod can stay out of the load balancer for up to an hour after
an operator has declared the incident over.

**2. Two routers claim `/api/security/lockdown`.** `api/security_dashboard.py`
and `security/global_fortress.py` both use `prefix="/api/security"` and both
define `GET /lockdown` and `POST /lockdown/clear`. Measured on the real app
(1,327 routes) in the default configuration, only `api.security_dashboard`
serves them — `security_brain` is behind `F.init_security_brain` and off — so
there is no live collision today. **Enabling that flag creates one**, and which
handler wins depends on registration order rather than on anyone's intent.

The two are one question: if the dashboard owns the path, its clear must reach
Redis, and `global_fortress`'s duplicate routes should go. If the brain owns it,
the dashboard's lockdown endpoints should go. Leaving both is the only option
that is certainly wrong, and it is the current state.

Recorded as F274. The asymmetry is asserted rather than left implicit —
`test_lifting_does_not_reach_the_brain` fails with *"unexpected — update F274,
the asymmetry is gone"* if someone closes it without updating the record.

## §B — Work, ranked

Numbers measured 2026-09-08. Re-run `scripts/backlog_report.py` for current ones.

### B0. Where each number comes from

| Source | What it measures | Reading on 2026-09-08 |
|---|---|---|
| `ai/hub/capabilities.py` | Specification capabilities and their evidence | 233 rows · 230 live · 3 staged · 233/233 evidence resolves |
| `scripts/capability_callers.py` | Live rows with no production caller | 154 screened · **37 flagged** |
| `docs/REGISTRY.toml` | Documents, tiers, owners, contested subjects | 201 registered · **197 unowned** · 3 contested subjects |
| `docs/FRESHNESS_BASELINE.toml` | Stale references in living documents | **41 outstanding** |
| `GROUP4_CONSTITUTION.md` | Architectural invariants | 21 recorded · **11 not yet AVAILABLE** |
| `invariants/registry.py` | Do the constitution's cited predicates exist? | 12 named · **12 resolve** ✓ |
| `scripts/group4_preservation.py` | Has any title from either Group 4 source been dropped? | 304 titles · **0 missing** ✓ |
| `scripts/gate_evidence.py` | Which gates have been proven able to fail? | 29 gates · **29 proven · 0 unproven** ✓ |

### B1. Critical — do these first

| # | Item | Where | Why it ranks here |
|---:|---|---|---|
| ~~1~~ | ~~**Tested backup and restore**~~ | Group 2 Ch 9 | **DONE — Phase R1.** Round trip proven against SQLite and live PostgreSQL. Point-in-time recovery and a decided RPO remain and inherit the rank — see §A1 |
| ~~1~~ | ~~**Rule 1 injection evidence**~~ | Group 2 Ch 0, 19, 20 | **DONE — Phases R2–R12.** Ratchet 13→10→8→7→6→5→4→3→2→1→0. All 23 gates now carry an injection test that was watched to fail. Proving them keeps finding defects — gate M passed with no dataset, gate E's dead-file detector had never actually detected a dead file — though not every gate is broken: gate C (docker-compose safety defaults) was already alive. Run `python scripts/gate_evidence.py` for the current list |

### B2. High

| # | Item | Where |
|---:|---|---|
| 2 | Acceleration answer-invariance — cache age carried, downgrade always visible | Group 2 Ch 28, 32, 33 |
| 3 | Data egress and sovereignty boundary | Group 2 Ch 13 — blocks Group 1 §23/§24 |
| 4 | Correlation key joining metrics, traces, logs and changes | Group 2 Ch 14 — blocks Group 1 §16 |
| ~~5~~ | ~~Change records carrying their expected effect~~ | **DONE 2026-09-09 — see §E24.** `deployment/change_records.py`, enforced at `commit-msg`. Group 1 §16, §21 and §32 are unblocked |
| 6 | Authority Tiers 0 and 3 (four of six exist) | Group 2 Ch 10 · INV-09 · Group 4 Ch 6 |
| 7 | Stated degradation order, trading path excluded from it | Group 2 Ch 34 |
| 8 | Progressive delivery and automated rollback | Group 2 Ch 5 |
| 9 | Package ownership register with enforced edges | Group 2 Ch 1 · INV-01 |
| 10 | Injection evidence as a traceability link | Group 3 Ch 13 |
| ~~11~~ | ~~ADR system, back-filling the eight known decisions~~ | **DONE 2026-09-09 — see §E22.** `docs/decisions/`, nine records, gated in pre-commit |
| 12 | Failure memory with the five questions | Group 3 Ch 8 — seven lessons currently live only in a transcript |
| ~~13~~ | ~~**Decision Governance** — Architecture Decision Registry and Decision Ledger carrying *expected outcome, actual outcome, lessons*~~ | **DONE 2026-09-09 — §E22 (registry) and §E23 (ledger).** `ai/ledger/`, wired to the money path's refusals. Group 2 Ch 6's change records remain separate and open |
| ~~14~~ | ~~**The second, unverified backup path**~~ | Group 2 Ch 9 |
| ~~15~~ | ~~**`risk/manager.py`'s 1.0 default for unmeasured data quality**~~ | Group 2 Ch 34 · INV-14 — **DONE 2026-09-09, see §E12** |
| ~~16~~ | ~~`trader_full.py` builds a RiskManager with no orchestrator, so it now refuses every size~~ **DONE 2026-09-09.** Wired in `RiskManager.setup()` — the real construction site, not the line §E12 named |
| ~~19~~ | ~~**441 malformed OHLC bars in `data/XAUUSD_40Y.csv`**~~ | **Owner chose clamp + restrict, DONE 2026-09-09 — see §E18.** Re-sourcing 2000–2019 from a vendor remains open and needs network access |
| 18 | `accuracy_7d` on `/ml/status` is training-time OOS accuracy, not a 7-day rolling figure | Renaming a published API field is a contract change — see §E13 |
| ~~20~~ | ~~**The per-module coverage gate had never taken a measurement**~~ | **DONE 2026-09-09 — see §E20.** `--cov=<dotted.module>` double-loaded numpy for every module in the repository; the 361-entry record is an artefact of that, not a census of untested modules |
| ~~21~~ | ~~**No pre-commit hook is installed, so no ratcheted check runs automatically**~~ | **DONE 2026-09-09 — see §E20.** `scripts/bootstrap_dev.py::install_git_hooks()` runs `pre-commit install --install-hooks` and warns rather than failing when it cannot. Whether CI should also run the hooks remains an owner decision |
| ~~17~~ | ~~`RiskAssessment.data_quality` still reports a 1.0 fallback via `_get_data_quality()`~~ **DONE 2026-09-09 — and it was a second live gate, not just a report. See §E16** | Reporting only — the *gate* is fixed (§E12). Narrowing the reported record means widening the type to `float \| None` and updating its consumers |

**Item 14 was found while building Phase R1, deliberately left alone, and is now
DONE (2026-09-08).** `trigger_backup` no longer reimplements `pg_dump`/`shutil`
itself — it calls `database/backup.py::run_backup()` and then
`database/restore.py::verify_backup()` before reporting success, the same
verified path Phase R1 proved for the scheduled backup job. Folding it into the
restore change would have widened that change past what could be reviewed as
one thing, so it stayed its own commit with its own tests, as recorded here.

**Fixing it found a defect this entry did not name.** The `except Exception`
around the old dump logic set `status = "completed"` unconditionally — so a
missing `pg_dump` binary, a permission error, or a timeout all reported success,
with `size_mb: 0.0` and a `location` nothing had written. Same shape as gate M
and gate K in §E3/§E4: success reported for work that did not happen. Fixed by
making failure (including a backup that writes but does not verify) report
`status: "failed"`, `ok: false`, and a `safe_error()`-scrubbed reason rather than
the raw exception string — a first pass returned `str(exc)` directly and
`tests/unit/test_exception_info_exposure.py`'s ratchet caught it. Proven by
`tests/unit/test_superadmin.py::TestBackupTriggerEndpoint` (3 tests: failed run,
verified success, and a backup that writes but fails verification — each
red-green checked by reverting the fix and confirming the test fails first).

**Item 13 is not a fourth thing.** It is items 11 (ADR system) and 5 (change
records with expected effect) seen from a third source, and the complete Group 4
document names the field the other two omit: *actual* outcome compared against
expected. Build them as one artefact or you get half a ledger three times.

### B3. Medium

Group 2: incident declaration and postmortem (Ch 15) · capacity forecasting and
load-shed (Ch 7, 34 — Redis reports `maxmemory` unlimited on a bounded host) ·
latency budgets per stage (Ch 17) · nightly `slow`/`e2e` (Ch 5, 19 — decision A3)
· routing decisions recording their reason (Ch 30) · SBOM and dependency
provenance (Ch 12) · administrator console starting with refusals (Ch 26) · debt
measurement and budget (Ch 22) · execution-target abstraction and capability
probe (Ch 29).

Group 3: root/docs duplicate contracts (Ch 1, 3) · outcome memory linkage (Ch 8)
· backlog item records and duplicate detection (Ch 11) · idea relationship graph
(Ch 12) · decision ledger unification (Ch 7).

### B4. Low

API versioning and deprecation policy (Group 2 Ch 21) · retention and
classification policy (Ch 25) · `data/` ÷ `data_layer/` boundary (Ch 1, 25 —
decision A2) · semantic search with provenance (Group 3 Ch 16) · tiering the six
dated audits and archiving completed plans (Group 3 Ch 1, 4).

---

## §C — Standing debt, not a project

These do not finish; they shrink. Each is held by a ratchet: the current number
is the baseline, new violations block, and the baseline may only fall.

| Debt | Baseline | Mechanism |
|---|---:|---|
| Documents with no owner | 197 | `scripts/docs_registry.py --check` |
| Stale references in living documents | 41 | `scripts/docs_freshness.py` |
| Live capabilities with no production caller | 37 flagged of 154 | `scripts/capability_callers.py` |
| Contested document subjects | 3 | named in `docs/REGISTRY.toml` |
| Modules with recorded coverage debt | 230 | `docs/COVERAGE_UNMEASURABLE.txt` · `scripts/pre_commit_coverage.py` |

**The 230 is not 230 untested modules.** Every entry was recorded because
measurement returned `None`, and until §E20 measurement returned `None` for
*everything* — so the list began as a census of one broken invocation. It is
kept rather than deleted because it is now the ratchet that lets the repaired
gate
bite without blocking every commit that touches any of those files: a recorded
module reports its real number without blocking, and blocks the moment it clears
the floor and stops needing the entry. The honest count of under-covered modules
will be whatever `--adopt` measures; nobody has spent the two hours yet.

It read **361** here for a long time, against a record that has been shrinking
since: 250 entries a dozen commits ago, 233 today. The coverage-floor programme
took 259 to 233. Nothing checked the figure, so it stayed at 361 while the thing
it described moved — which is the failure mode the whole §E22 ratchet exists to
stop, occurring in the document that describes the ratchet. `doc_metrics.py` now
verifies it: see `coverage_debt` in `_CLAIMS`.

**The caller sweep is a screen, not a verdict.** Symbol matching misses aliases
and dynamic lookup, so each of the 37 is one row to *inspect*, not one defect to
fix. The three `arch.layer_*` rows at `prod=0` were named here as the ones to
look at first. **They have now been inspected, and they are false positives** —
their locator is `layer_state`, the §4 roll-up helper, which *is* called, at
`ai/hub/capabilities.py:2667`, inside the module that defines it. The screen
reports `prod=0 any=1` because it looks for callers outside the defining file.
Nothing is dead there; the rows stay flagged and the count stays 37 because the
screen is behaving as documented.

**Inspecting them did find a real gap next door, and it is now closed.** The
`arch.layer_b.intelligence` row cites `ai.agent.loop` as its evidence, and that
module — the Think → Execute → Monitor → Improve loop — had no caller anywhere
outside `ai/agent/` and its own tests. The registry could not see it:
`verify()` asks whether the evidence *resolves*, not whether anything *runs*.
`ai/agent/sweep.py` and `init_ai_agent_sweep` are now that caller — a scheduled,
read-only health sweep, which is the caller the loop's own docstring was
written for. See §E9.

## §D — Staged, not live

Three capability rows are staged: `arch.layer_a.presence` (§4),
`vision.gesture` and `vision.pointing` (§18). Staged means the specification is
written and the evidence locator resolves, but the row is not claimed live.

## §E — Constitutional invariants not yet AVAILABLE

Eleven of twenty-one. INV-03 (*every subsystem has an owner or governance
authority*) is the only **NEW** one, and it is the same fact as the 197 unowned
documents in §C — one gap, two views. The other ten are PARTIAL: they exist and
under-reach, with the shortfall named per row in `GROUP4_CONSTITUTION.md`.

---

## How this document stays honest

It is registered in `docs/REGISTRY.toml` at T2 and checked by
`scripts/docs_freshness.py` like every other living document: a path it names
that stops existing is a blocking finding, not a silent rot. The counts, though,
are a snapshot by nature — which is why the generated report exists and why this
document points at it rather than trying to be it.


---

## §E2 — What Phase R1 changed (2026-09-08)

| | |
|---|---|
| Built | `database/restore.py` · `docs/runbooks/database-restore.md` · `tests/integration/test_database_restore_postgres.py` |
| Fixed | The WAL backup defect · the misleading `.sql.gz` name · `pg_dump` memory buffering · rotation that would have stopped silently at the extension change |
| Proven | 23 tests. Every refusal by handing the code the exact broken artefact; the round trip against a live PostgreSQL 16.13 with matching checksums |
| A control that could not fail | **One of my own**, caught by injection: a "leaves no partial file" test that the atomic staging already guaranteed, so deleting the cleanup did not fail it. Replaced with the falsifiable property — an existing database is untouched when a restore fails |
| Operational consequence | **Sweep the backup directory.** Any SQLite artefact from before today may restore to nothing, and `--verify` is what tells you which |

## §E3 — Phase R3: turning the Rule 1 ratchet (2026-09-08)

Five gates were scoped by consequence. **Three proven, two deferred**, and
proving them found two more dead controls.

| Gate | Outcome |
|---|---|
| `check-secrets` | **Proven, and a bypass fixed.** The placeholder allowlist matched the whole line, so a real credential containing `xxx`, `none`, `null` or `tbd` was skipped. Verified against the real tree: 27 blocked lines before and after, so no new false positives |
| `gate_i_migration_chain` | **Proven.** All six failure classes caught. My first probe reported two live rules as dead — both injections were no-ops against the root migration. The test now asserts each injection changed the file before running the gate |
| `gate_m_ml_edge` | **Proven, and a fail-open fixed.** It exited 0 when the A/B dataset was missing, so a rename turned the ML edge guard off with CI green. The dataset is committed, so absence is a defect; `AB_ALLOW_SKIP=1` is the explicit local opt-out |
| `gate_d_model_accuracy` | **Deferred.** It validates 38 MB of model artefacts resolved from `__file__`, with no env indirection, so a per-test mirror would make the suite slow. Needs a manifest-level injection instead — a different design, not more of the same |
| `coverage-gate` | **Deferred.** Not started; scope was spent on the two defects found above |

Two probes of my own were wrong before they were right — a no-op `sed` against
the migration root, and a test credential containing the substring `EXAMPLE`
which the scanner allowlists. Both would have reported a live control as dead.
**Verifying that the injection applied is now part of the method**, not an
afterthought.

## §E4 — Phase R4, and what comes next (2026-09-08)

Ratchet 10 → 8. Two gates proven, one dead behaviour fixed, one blind spot
recorded rather than silently widened.

| Gate | Outcome |
|---|---|
| `gate_b_env_consistency` | **Proven.** An undocumented `${VAR}` reference fails; a literal value does not, which is its documented scope; deleting either input fails closed |
| `gate_k_requirements_consistency` | **Proven, and a fail-open fixed.** `[gate-k] SKIP` on a missing requirements file exited **0** — CI and production could install different code with nothing disagreeing. Same shape as gate M, one phase later |
| `coverage-gate` | **Not reached.** Scope went to the two defects above |
| `gate_j_circular_imports` | **Not reached** |

### Recorded, not fixed — the build toolchain is unguarded

`gate_k`'s `_SKIP_NAMES` excludes `pip`, `wheel` and `setuptools`, and every rule
iterates the parsed sets, so **the CVE-pinned build toolchain is checked by
nothing in that gate**. requirements.txt pins those three against four named
CVEs; the lock could drift below them and gate K would still pass.

Widening the exclusion is a scope decision with a real cost — build-toolchain
versions in a lock are often environment-specific, and false positives train
people to bypass gates. `test_gate_k_requirements_injections.py` pins the
exclusion at exactly those three so it cannot quietly grow, and this is the
record so it cannot be forgotten while the gate looks green.

**Decide it deliberately.** Either extend gate K to cover them, or state in
requirements.txt why they are out of scope.

---

## What is next

In order, and each is a command away from being verified rather than assumed:

1. ~~**Finish the ratchet.**~~ **DONE in R12** — all 23 gates carry injection
   evidence. What replaces it: the findings those phases produced are still
   open. The 12 dead-file candidates from §E6 and the 7 `data_layer` import
   violations recorded in §E9 are both real work, and the second is waiting
   on decision **A2**.
2. **Decision Governance** (§B2 item 13) — the single highest-leverage new build.
   Three documents name the same missing artefact from three angles; build them
   as one or you get half a ledger three times.
3. **The owner's decisions in §A**, chiefly **A1**: RPO is 24 hours because of a
   cron entry, not because anyone weighed it. That and RTO decide whether
   point-in-time recovery gets built.
4. **The 361 unmeasurable modules** (§E5). Not a phase — a standing ratchet.
   Worth attacking opportunistically: whenever you touch a module on that list,
   make its test import it and drop the line.

## §E5 — Phase R5 (2026-09-08)

Ratchet 8 → 7. One gate proven, and it was the most inverted defect found yet.

### The coverage gate passed the worst coverage

| Module state | Gate result before R5 |
|---|---|
| 25% covered | **FAIL**, exit 1 — correct |
| 0% covered (test never imports it) | **pass**, exit 0 |
| Test file will not import at all | **pass**, exit 0 |

When the module under test is never imported, coverage collects no data and
prints no `TOTAL` line, so the parser returned `None` — and `None` took the "warn
but do not block" branch. **The worse the coverage, the quieter the path through
the gate.** Rule 2 says an unmeasured value is absent, never zero; here it was
being treated as success.

An unmeasurable module now fails. `SKIP_COVERAGE_GATE=1` was already the
documented emergency bypass, so no second escape hatch was added.

### The fix immediately found a real hole

`database/backup.py` — the module that takes every database snapshot — resolved
to `tests/unit/test_database.py` via the `test_{parent}.py` fallback, and that
file never imports it. So it had **no effective coverage check at all**, and the
gate reported nothing wrong.

| Module | Before | After |
|---|---:|---:|
| `database/backup.py` | unmeasurable (silently) | **95%** |
| `database/restore.py` | 78% (below the 80% threshold) | **95%** |

Both are Phase R1 code. The PostgreSQL dump path is tested at the subprocess
boundary — argument list, streamed output, failure handling, and that the
password travels in the environment rather than argv where `ps` would show it —
while the real `pg_dump` stays covered by the integration suite against a live
server.

### And it surfaced debt worth naming: 361 modules

Repository-wide, **361 modules resolve to a test file that never imports them**.
Every one had been passing the coverage gate while contributing nothing to
coverage. That is not a number to fix in a phase, so it is recorded as a ratchet
in `docs/COVERAGE_UNMEASURABLE.txt`: the list may only shrink, and a **new**
unmeasurable module blocks the commit.

The seed is static — every module whose resolved test file never mentions it —
because measuring all 539 candidates takes about two hours. That is safe in the
direction it errs: an entry only matters when measurement returns `None`, and a
measurable module is judged on its number either way. Verified by execution — a
baselined module at 25% still fails. A list that were too *narrow* would block
legitimate work, so the seed is deliberately wide.
`python scripts/pre_commit_coverage.py --adopt` replaces it with the exact
measured set.

**This is now the largest single piece of recorded debt in the repository**, and
it is the honest reading of what the coverage gate was hiding. Paying it down is
one module at a time: make the test file import the module it is named for.

> **Correction, 2026-09-09 (§E20).** Two claims in this section are false, and
> both are the kind this document exists to prevent.
>
> "361 modules resolve to a test file that never imports them" was never
> measured. The gate could not measure *anything* — `--cov=<dotted.module>`
> made coverage re-import numpy's C extension in a process that had already
> imported it, so every module in the repository returned `None`. The 361 is a
> census of one broken invocation, not of 361 untested modules.
>
> "Verified by execution — a baselined module at 25% still fails" describes a
> comparison the gate had no means to make. It reads as evidence and is not.
> Written in the same phase that made unmeasurable modules fail, which is
> exactly when a claim of verification is least likely to be re-checked.
>
> `database/backup.py` at 95% and `database/restore.py` at 95% stand — those
> were measured with the full suite, not through this gate.
>
> §E20 repairs the invocation and re-reads the list as recorded coverage debt.

## §E6 — Phase R6 (2026-09-08)

Ratchet 7 → 6. One gate proven, and three real defects found inside it —
the dead-file detector had, as far as this phase could tell, never actually
detected a dead file in any of its five guarded packages.

### The guard that checked nothing

`GUARDED_PACKAGES` names `kill_switch`, but `kill_switch` is a single
top-level file (`kill_switch.py`), not a package directory.
`_collect_py_files` checked `root / "kill_switch"` only, which is never a
directory, and returned `[]` without ever looking at the file. A completely
unimported `kill_switch.py` passed Gate E clean, in the real repository,
before this fix.

### The prefix that made every sibling look live

`import execution.live` added both `"execution.live"` **and** the bare
prefix `"execution"` to the imported-names set, so
`"execution.orphan".startswith("execution" + ".")` was `True` purely
because a *different* file in the same package had been imported — never
because `orphan.py` itself had been. Confirmed directly against the real
repository (not the mirror): `"execution"`, `"risk"`, `"core"`, and
`"brokers"` were all in that set before this fix. In a codebase where each
guarded package is imported from *somewhere*, which is always, this meant
the gate could not have reported a real dead file in any of them, ever.
Fixed by splitting the collected names into `exact` (a specific dotted name
an import statement actually named) and `bare_packages` (a name imported
with **no** further qualification at all, e.g. a literal `import
execution`) — only the second grants "every submodule is reachable via
attribute access."

### Fixing that one immediately exposed a third

With the prefix bug gone, ~100 genuinely-live files across `core/` and
`brokers/` started reporting as dead. The cause: `EXCLUDED_PATTERNS` served
two different questions with one list. Keeping `app.py`, `celery_app.py`,
and `__init__.py` out of the *guarded-candidate* scan is correct — they are
run directly or are package boilerplate, not "a module someone imports."
But the same list also kept them out of the *import-source* scan, and real
production wiring lives in exactly those files:
`app.py: from core.health import register_health_routes`,
`brokers/__init__.py: from brokers.smart_router import SmartOrderRouter`.
Excluding them from the source scan made everything they alone import look
unreferenced. Split into `EXCLUDED_PATTERNS` (guarded-candidate scope,
unchanged) and a new `IMPORT_SCAN_EXCLUDED_PATTERNS` (source scope — drops
`__init__` and the entry-point filenames, keeps the non-Python and
test-only exclusions).

### What real execution against the repository still finds

After all three fixes, a real run reports **12** files across `brokers/`,
`core/`, `execution/`, and `risk/` with no detectable production caller —
down from 124 with only the prefix fix, and 32 with the prefix and
entry-point fixes together. At least one (`risk/risk_manager.py`) is a
documented backwards-compatibility shim exercised only by its own tests,
which may be a correct finding rather than a defect. The 12 are not
individually triaged here — proving the gate can fail is this phase's job;
which of its findings are real dead code and which need one more scan
refinement is real follow-up work, tracked separately, the same way R3–R5
left their own findings for the next phase rather than resolving everything
in one commit.

## §E7 — Phase R7 (2026-09-08)

Ratchet 6 → 5. One gate proven, and this one was already alive.

`gate_c_docker_compose.py` checks four structural safety defaults in
`docker-compose.yml`: `PAPER_TRADING` defaults to `true`, `IS_FORCE_TLS` and
`REDIS_FORCE_TLS` default to `false`, and `alertmanager` uses `build:` (so
its envsubst entrypoint runs) rather than `image:`. Injected against a real
mutated copy of the repository's actual compose file, not a synthetic one —
so an injection also proves the gate's string anchors still match the real
file's current layout, not a layout it used to have. All four defaults
correctly fail when flipped; a missing file is reported rather than
crashing; and a sanity probe — temporarily disabling the `PAPER_TRADING`
check itself and re-running the suite — confirmed the tests would have
caught that regression, before trusting the clean pass on the real gate.

The gate ships two code paths: `_check_yaml` (PyYAML present) and
`_check_regex`, a fallback for when it is not. A fallback nobody exercises
is exactly the shape this repository keeps finding dead, so both were
proven directly against the same four injected cases rather than trusting
that whichever one CI happens to run is the one under test.

No defect found this time. Not every gate is broken; this is the check
that says so with evidence rather than assumption.

## §E8 — Phase R8 (2026-09-08)

Ratchet 5 → 4. One gate proven, and like gate C it was already alive.

`gate_h_wordmap_schema.py` validates `WORDMAP.json.example`, the reference
file operators copy to `WORDMAP.json`. The consequence it guards is quiet:
if the example loses its structure, `NuclearWordmapScorer` silently falls
back to built-in keywords, so a misconfiguration looks like normal
operation. All eight documented rules were injected into a real mutated
copy of the file — invalid JSON, a missing `nuclear_risk` key, that key as
a list rather than an object, an uppercase category name, a non-object
category, an empty category, an empty keyword string, an over-length
keyword, a non-numeric weight, weights above 10 and below 0, too few
categories, and too few total keywords. All refused.

Two of those cases are worth separating, because they are the ones a
truncation defect would actually produce: the category floor and the
keyword floor fire independently, so a file that keeps all eight categories
but strips each to one keyword is still caught.

As with gate C, the clean first run was not taken at face value: disabling
the weight-range check in a scratch copy turned both range tests red, then
the real file was restored and the suite reran clean.

No defect found. Two gates in a row alive is worth stating plainly — the
ratchet's value is the evidence either way, not a defect count.

## §E9 — Phase R9 (2026-09-08)

Ratchet 4 → 3. One gate proven, two real gaps found in it, and seven
pre-existing violations that had been invisible because of them.

### The rule named three modules; the code required three segments

`gate_g_import_discipline.py` enforces that canonical packages reach
`data_layer` only through its public surface — `data_layer.orchestrator`,
`data_layer.tick_store`, `data_layer.feeds.*`. The check required
`len(parts) >= 3` before examining anything, so a two-segment path like
`from data_layer.sentiment import get_sentiment` was never looked at.
"Three names are public" and "paths with three segments are checked" are
not the same rule, and the second was what shipped.

Separately, `_is_data_layer_internal` examined only `ast.ImportFrom`, so
the plain `import data_layer.internal.thing` form was not checked at all.

Both were confirmed by execution at exit 0 against the real gate before
being fixed, alongside two controls that correctly exited 1 — so the probe
distinguished a dead rule from a rule the injection had simply missed.

### What that had been hiding

| File | Import |
|---|---|
| `api/signals.py:1228` | `data_layer.sentiment` |
| `api/trading.py:4574` | `data_layer.microstructure` |
| `ml/inference_engine.py:1097` | `data_layer.validation` |
| `ml/train_advanced.py:131` | `data_layer.validation` |
| `backtesting/data_handler.py:72` | `data_layer.validation` |
| `backtesting/engine_config.py:220` | `data_layer.validation` |
| `backtesting/engine_config.py:593` | `data_layer.validation` |

These are **recorded in `KNOWN_VIOLATIONS`, not fixed**, which is what that
list is for: the gate now warns on them, exits 0, and fails hard on
anything new. Fixing them is not mechanical — three modules are imported
from outside `data_layer` today, so resolving it means deciding what that
package's public surface actually is. That is **decision A2**, and a gate
change is not the place to make it.

The escape hatch is pinned in both directions, because a debt list that
could silence anything else would be an off-switch: a listed violation
warns and exits 0, an unlisted one alongside it still fails, and a listed
entry does not cover the same file on another line. That last property —
the keys carry line numbers — means editing a file above one of these
imports turns a known violation into a new one. Loud rather than silent,
so it is recorded in the gate's own comment rather than redesigned here.

## §E10 — Phase R10 (2026-09-08)

Ratchet 3 → 2. One gate proven, and the defect is the same one this
ratchet has now found three times.

`gate_f_doc_consistency.py` checks that the API shown in fenced `python`
blocks in ARCHITECTURE.md, AGENTS.md and CONTRIBUTING.md is the API the
code actually has. A missing document was skipped and the gate exited 0.
With all three absent it printed:

```text
[gate-f] SKIP  ARCHITECTURE.md (file not found)
[gate-f] SKIP  AGENTS.md (file not found)
[gate-f] SKIP  CONTRIBUTING.md (file not found)
[gate-f] PASS — checked 3 docs, no violations
```

Two failures in one message. Renaming a document turned the gate off with
CI green — the gate M and gate K shape a third time — and *"checked 3
docs"* was `len(DOCS_TO_SCAN)`, the length of a constant tuple, not a
count of anything opened. That is F176's shape as well: a number that
cannot report having measured nothing.

Fixed as gates M and K were, deliberately reusing their convention rather
than inventing a third one: a missing document fails closed,
`DOC_ALLOW_SKIP=1` is the explicit local opt-out alongside `AB_ALLOW_SKIP`
and `REQ_ALLOW_SKIP`, and the reported count now comes from what was
actually read.

Both rules were injected as well — an import of a module that does not
exist, a name missing from a real module, and a PascalCase class the
repository never defines all fail — along with the documented non-findings
that keep the gate usable: external and stdlib prefixes, the SKIP_NAMES
placeholders a doc example is expected to invent, and prose outside a
fenced block.

## §E11 — Phase R11 (2026-09-08)

Ratchet 2 → 1. One gate proven, and the defect is one already found in
this ratchet — in a different gate.

`gate_j_circular_imports.py` builds an intra-repo import graph and looks
for cycles across eleven trading packages. Its own header states the
consequence it exists to prevent: a circular import can "silently corrupt
module-level singletons (**e.g. the kill switch state**)".

It never looked at the kill switch. `_py_files` did `pkg_dir = root /
package; if not pkg_dir.exists(): return []`, and `kill_switch` is a
single top-level file — `kill_switch.py`, not `kill_switch/` — so it
resolved to nothing, while the PASS line went on listing `kill_switch`
among the packages checked. Confirmed by execution: a genuine
`core.uses_ks` ↔ `kill_switch` cycle produced *"Gate J PASSED — no
circular imports detected"*.

**This is §E6's defect in a second gate.** Same root cause, same shape,
found six phases apart, in code written by the same hand as the gate that
had it first. The lesson is not about either gate: any rule that resolves
a "package" as `root / name` shares it, and the repository has at least
one guarded name that is a module rather than a package. Both are now
fixed the same way.

The real graph goes from 401 to 402 modules with the fix and still passes,
so this closed a blind spot without changing the verdict on the tree as it
stands. The rest of the gate is alive: two-module, three-module and
cross-package cycles all fail, a diamond is correctly not a cycle, and the
deliberate exemption for deferred function-level imports is pinned against
the module-level form of the same pair, so it is a scoped exemption rather
than a hole.

## §E12 — Phase R12 — the ratchet reaches zero (2026-09-08)

Ratchet 1 → 0. **All 23 gates now carry injection evidence.**

`gate_d_model_accuracy.py` was deferred twice, and the reason recorded in
§E3 was: it "validates 38 MB of model artefacts resolved from `__file__`,
with no env indirection, so a per-test mirror would make the suite slow" —
it "needs a manifest-level injection instead, a different design".

**That premise was wrong, and this is the finding.** The gate does not
require the artefacts to be *large*; it requires them to be *consistent*.
What it checks is agreement — the `current.pkl` symlink resolves to the
registered file, its SHA-256 matches the registry, the meta agrees with
the registry, the Sharpe gate passed on a credible number of trades. A
28-byte file whose real SHA-256 is written into a synthetic registry
exercises every one of those, integrity hash included, against a real
symlink in a real subprocess.

The mirrors are about a kilobyte. Twenty-two injections run in four
seconds. No env indirection had to be added to the production script, and
nothing in the suite reads or writes the real `ml/saved_models/`.

Fifteen distinct refusals were confirmed, and the wrapper was proven to
propagate rather than report its own success: an inner exit 3 stays 3 and
never prints PASSED — the shape gates M, K and F each had in a different
form. The gate is alive; the blocker was an assumption about what it
needed, not the gate.

### What the twelve phases actually bought

| Gate | Outcome |
|---|---|
| `gate_e_dead_files` | **Three defects.** Had never detected a dead file in any guarded package |
| `gate_g_import_discipline` | **Two defects.** The rule named three modules; the code required three path segments |
| `gate_f_doc_consistency` | **One defect.** A missing document was a skip, and a skip was a pass |
| `gate_j_circular_imports` | **One defect.** Never had the kill switch in its graph |
| `gate_c_docker_compose` | Alive |
| `gate_h_wordmap_schema` | Alive |
| `gate_d_model_accuracy` | Alive — the deferral was the defect |

Seven real defects in four gates, and three gates confirmed sound. Two of
those defects were the *same* defect — a guarded name resolved as
`root / name` when it is a file, not a directory — found in gate E and
again in gate J, six phases apart.

**What this does not mean.** Every gate can now be shown to fail when it
should. Nothing here says the tree is clean: gate E's fix surfaced 12
dead-file candidates and gate G's surfaced 7 recorded import violations,
all still open. The ratchet's job was to make the controls trustworthy;
using them is the next job.

## §E9 — The agentic loop got its caller (2026-09-09)

Not a gate phase. `ai/agent/loop.py` implements spec §2's `agent/` — Think →
Execute → Monitor → Improve — and `ai/hub/capabilities.py` cites `ai.agent.loop`
as the evidence that `arch.layer_b.intelligence` is **live**. Measured, nothing
outside `ai/agent/` and its own tests imported it.

**The registry is not able to catch this, by construction.** `verify()` resolves
an evidence locator: it imports the module and checks the attribute exists. That
is a real check and it is the one F176 was about. But "the evidence resolves"
and "something calls it" are different claims, and only the first is measured.
`scripts/capability_callers.py` exists for the second, which is why it is kept
as a separate screen.

### What was built

`ai/agent/sweep.py` — a deterministic health sweep — and
`init_ai_agent_sweep`, registered in `core/startup_factories.py` beside
`ai_awareness` with the same `required=False`. It is the caller the loop's own
docstring named: *"A deterministic planner is what the tests drive and what a
scheduled health sweep wants."* A model-driven planner is the same interface and
can replace it; doing the deterministic one first means the wiring is proven
before a language model is near the tool bus.

### The filter that looked obvious and was wrong

The first design chose any permitted action whose handler needs no arguments.
Measured against the live registry, **every** READ_ONLY handler defaults all of
its parameters — so that rule admits `markets_execution.shadow_place_order`,
`platform_engineering.run_tests`, `research_intelligence.run_backtest` and
`walk_forward_validate`. On a 15-minute timer that is shadow orders in the audit
trail every interval, and a backtest and the test suite running on the box that
executes trades.

So the sweep names the health checks it wants and **intersects them with
`context.permitted`**, the allowlist the loop computed from the department's own
registry. The intersection is what makes a named set safe: it can only narrow
what the loop already allowed. A renamed check means the sweep calls one thing
fewer — the direction an error here has to fail in. `test_it_never_calls_order_
shaped_or_expensive_tools` pins it across every department.

### Three narrowings, none of them removed

The loop refuses anything outside `permitted_actions(department)` before the bus
is reached; the bus consults the permission registry and `enforce_agent_action`
after that; the sweep narrows once more. This change adds the third and touches
neither of the first two.

### Two test-methodology corrections, recorded

* The caller assertion first searched for the substring `run_loop` and **passed
  before anything was wired** — `hopefx_engine.py` and `nuclear/nuclear_agent.py`
  each define an unrelated `run_loop`/`_run_loop`. It now parses imports with
  `ast`. A text match tests how code is written, not what it imports.
* Registration is not execution, so the suite drives `init_ai_agent_sweep`
  itself and asserts a task is scheduled — and asserts that with no tool bus it
  schedules nothing rather than reporting a clean sweep it never ran.

## §E10 — The model quality gate got its caller (2026-09-09)

`ml/model_quality_gate.py` is well built — `require_pass()` raises rather than
returning a falsy result, `evaluate()` treats a missing score as a **failure**
rather than a zero, every refusal carries a reason code — and it was invoked by
nothing outside its own tests. A fail-closed gate nobody calls is worse than no
gate: it reads to a reviewer as though model quality is checked.

### It was aimed at the wrong place first

The obvious guess is `ml/model_registry.py::promote()`. Wrong, and the module
says so: it exists to be consulted *"before a candidate reaches paper or live
execution"*. That is the **inference** path. Registry promotion already has its
own gate (OOS accuracy, p-value, Sharpe, PnL reconciliation); this one asks
whether a *prediction* can be trusted right now.

### The three signals already existed, judged by hand

`predict()` was already making all three judgements inline, as strings in the
evidence blob, against a bare `0.3`:

    "calibration_state":  "isotonic" if self._calibrator is not None else "raw",
    "drift_state":        "detected" if drift else "clear_or_unavailable",
    "data_quality_state": "valid" if data_quality >= 0.3 else "degraded",

— and `data_quality` was computed under a comment reading *"for downstream
gating"*, then used only to set a Prometheus gauge. Nothing gated on it.

So the wiring replaces three hand-rolled judgements with the component built to
make them. **Every threshold is a value the file already used**
(`_DRIFT_Z_THRESHOLD`, and the `0.3`, now named `_MIN_DATA_QUALITY`). None is
invented — a gate configured with numbers nobody chose fails at a boundary
nobody agreed to.

Blocking is opt-in (`MODEL_QUALITY_BLOCK`, default false), the same shape as
`DRIFT_BLOCK`. Wiring a gate in must not silently change when this system
declines to trade. When it *is* enabled it raises `RuntimeError` specifically,
which `HOPEFXDecisionEngine._phase2_ml` treats as a hard ML filter rather than
falling back to non-ML confidence — a quality refusal must not degrade into
"trade on less information". An unevaluable gate raises too: not a passed gate.

### Two findings this surfaced, neither fixed here

1. **Every prediction today is uncalibrated.**
   `ml/saved_models/isotonic_calibrator.pkl` does not exist, so `_calibrate()`
   silently returns the raw probability. Nothing said so before; the gate now
   scores it 0.0 and records `calibration_state: "raw"`. `_MIN_CALIBRATION`
   defaults to 0.0, so this is tolerated and *visible* rather than enforced —
   raising it to 1.0 would refuse every prediction in the current deployment.
   Training records no Brier or ECE score, so there is no honest calibration
   *error* to read; the score is a presence signal and is documented as one.

2. ~~**`risk/manager.py::_get_data_quality` defaults to 1.0 when it cannot
   measure.**~~ **Fixed 2026-09-09 — see §E12.** `size_order()` now gates on
   `_measured_data_quality()`, which returns `None` when nothing measured the
   feed, and refuses. Evidence:
   `tests/unit/test_risk_data_quality_is_measured.py` (21 tests; 13 fail
   against the pre-fix tree). See the correction in §E12 — an earlier version
   of that section wrongly reported S5-02/S5-03 as still open.

## §E11 — advanced_ai.py: superseded, kept, pinned (2026-09-09)

Third module in a row with no production caller, and the first where "give it
a caller" was the **wrong** answer. The symptom is identical to §E9 and §E10;
the cause is not.

`ai/agent/loop.py` and `ml/model_quality_gate.py` were *built and never
called*. `ml/advanced_ai.py` (698 lines) is *superseded* — each of its three
subsystems has a more developed replacement that is already wired:

| in advanced_ai.py          | superseded by                         | wired into                            |
|----------------------------|---------------------------------------|---------------------------------------|
| `PPORLAgent`, `TradingEnv` | `ml/rl_agent.py`                      | `api/ml.py`, `ml/training_manager.py` |
| `OnlineRetrainer`          | `ml/online_learner.py`                | `api/online_learner.py`               |
| `VectorRAGNewsSentiment`   | `ai/departments/news_intelligence.py` | `ai/awareness/watchers.py`            |

`ml/rl_agent.py` additionally has `RLMetrics`, `RLAgentTrainer`,
`walk_forward_eval` and `get_rl_agent()`. Wiring `PPORLAgent` in beside it puts
a second, less developed PPO agent and a second online retrainer into a live
money-moving system, with no way to tell afterwards which one acted. So: not
wired, and — per the owner's standing instruction — **not deleted either**.

### What "marked" means here, so it does not rot

`tests/unit/test_advanced_ai_is_superseded.py` pins two things:

1. **Nothing in production imports it.** Verified by injecting a real
   `from ml.advanced_ai import PPORLAgent` into `ml/model_paths.py` and
   watching the test refuse, naming the offending file, then reverting. A pin
   nobody has seen refuse is not a pin.
2. **The supersession claim is checked, not asserted.** Each named replacement
   must exist AND itself be imported by production code. A pointer to a module
   that was later renamed is exactly how a note like this quietly becomes
   false — F176 applied to prose.

Writing that test found a bug in the test: the first import matcher recorded
only `node.module`, so `from ai.departments import news_intelligence` — the
normal way this repository reaches a department — read as importing
`ai.departments` and nothing else, and it reported `news_intelligence.py` as
having no caller. Same shape as the gate E prefix defect.

### One capability is genuinely unique and is not being discarded

`VectorRAGNewsSentiment` is embedding-based (FAISS + sentence-transformers).
The live path is the keyword wordmap scorer via
`api/news_feed.py::_get_nuclear_scorer`; semantic sentiment exists nowhere else
in the repository. Adopting it means putting model weights and resident memory
on the box that executes orders, so it is tracked as its own proposal to be
decided on its merits — not settled as a side effect of "this file needs a
caller".

## §E12 — The risk gate that could not fire (2026-09-09)

Fourth in the same family as §E9–§E11, and the first one in the **money path**.
`ai/agent/loop.py` and `ml/model_quality_gate.py` were controls that existed and
were never called. This is a control that existed, *was* called on every trade,
and could not reach its own failure branch.

### The defect

`RiskManager.size_order()` refuses to size when data quality is below
`RISK_MIN_DATA_QUALITY` (0.40). The value came from:

```python
def _get_data_quality(self, signal) -> float:
    if self._orch is not None:
        try:
            tick = self._orch.get_latest_tick()
            if tick is not None:
                return tick.confidence
        except Exception:
            ...
    return getattr(signal, "data_quality", 1.0)
```

`core.domain_models.Signal` has **no** `data_quality` field — verified by
introspecting `Signal.model_fields`, not by reading. So that `getattr` default
was not a rarely-taken fallback. It was the answer in every case except "the
orchestrator returned a fresh tick":

* no orchestrator wired onto the RiskManager
* `get_latest_tick()` raised
* `get_latest_tick()` returned `None` — Redis down, gold feed down, or the
  cached tick older than `DQE_STALE_THRESHOLD_S` (30 s) and discarded

Each of those scored **1.0 — perfect** and passed `< 0.40`. The gate could only
fire when the feed was *working* and honestly reporting low confidence. In the
condition it was written for — the feed being down or stale — it was
structurally unable to refuse.

Running the pre-fix tree against a dead feed shows it reaching sizing and being
stopped several gates later by an unrelated check (`tick_mid_unavailable`),
which is why the hole never surfaced as a bad trade in testing: a different
gate happened to catch it, for a different reason, in one arrangement of inputs.

### The same fabrication, one level up

`_MinimalSignal` — the adapter `calculate_position_size()` wraps its arguments
in — hardcoded `self.data_quality = 1.0` with no constructor parameter, so no
caller could set it. `HOPEFXDecisionEngine._phase3_risk` (the central 5-phase
pipeline) and `core/signal_engine.py`'s auto-trade path both size through it.
Every one of those trades asserted flawless market data that nothing had looked
at.

### What changed

`_measured_data_quality()` now distinguishes three cases the old code collapsed
into 1.0:

| case | result |
|---|---|
| orchestrator produced a tick | that confidence — the measurement |
| caller *supplied* a `data_quality` | honoured — an assertion somebody made |
| neither | `None` → `size_order()` refuses with `data_quality:unmeasured` |

The distinction that matters is between a value a caller **supplied** and a
`getattr` **default**: the first is a claim someone is accountable for, the
second is silence read as perfection. Rule 2, in the position-sizing path.

Alongside it:

* `_MinimalSignal.data_quality` defaults to `None` instead of `1.0`, and
  `calculate_position_size()` takes a `data_quality=` argument so callers that
  genuinely measure it (backtests, replays) can still say so.
* `_zero_sizing()` now carries its reason onto the result via
  `_halt_reason_override`, so `result.reason` names the gate that refused
  instead of the generic `"position_size_zero"`. It was logged and dropped
  before, so a caller — or an operator reading a lineage record rather than a
  log — could see *that* sizing refused but not *why*.

Deliberately **not** changed: `_get_data_quality()` keeps its `float` signature
and its 1.0 fallback, because `assess_risk()` feeds it into
`RiskAssessment.data_quality`, typed `float`. Narrowing the reported record is a
wider change than closing the sizing hole, and is tracked rather than smuggled
in alongside it.

### Why this is safe to enforce now

Both deployed paths build `RiskManager` **with** an orchestrator —
`hopefx_engine.py` explicitly, and `core/startup_factories.py::init_risk_manager`
for the FastAPI app the container actually runs (`Dockerfile` → `app.py`). So
the new refusal fires exactly when the orchestrator cannot produce a tick, which
is the condition the gate exists for.

`trader_full.py:677` builds a RiskManager with no orchestrator and will now
refuse every size. It is **not** a deployed entry point (`run.py` uses
`HopeFXEngine`), and the refusal is diagnosable rather than silent — it returns
`reason="data_quality:unmeasured"`. Wiring it to the orchestrator, or having it
assert its own quality, is tracked in §B.

### What this does NOT close — CORRECTED 2026-09-09

**The paragraph that stood here was wrong, and wrong in the direction that
matters: it reported an open hole in the money path that had already been
closed.** It read:

> `docs/HARDENING_BACKLOG.md` S5-02 and S5-03 (both open) describe the
> consequence: with Redis down, `orchestrator.get_latest_tick()` falls through
> to the in-memory consensus tick, which carries no age check […] "the feed is
> gone" is now caught; "the feed stopped and nobody noticed" is not.

S5-02 and S5-03 were fixed before this phase began. `GoldTick.is_valid()`
(`data_layer/types.py:143`) bounds age with `DQE_STALE_THRESHOLD_S` — explicitly
"so there is one staleness rule rather than one per read path" — and
`GoldFeedManager.get_latest_tick()` (`data_layer/feeds/gold/manager.py:424`)
checks it on the default consensus branch, warning instead of serving.
`tests/unit/test_tick_staleness_enforced.py` (8 tests) has been green
throughout.

Measured rather than read: a tick graded `GOOD` with confidence 0.99 reports
`is_valid() is False` at 31 s, and the consensus branch declines to serve it.

**The two fixes compose, which is the part the wrong paragraph obscured.** A
stalled feed now fails at the read (`is_valid()` → the manager returns nothing),
so the orchestrator returns `None`, so `_measured_data_quality()` returns `None`,
so `size_order()` refuses with `data_quality:unmeasured`. "The feed stopped and
nobody noticed" ends in a refusal, not a trade.

**How the error happened, because the mechanism matters more than the
correction.** The claim was taken from `docs/HARDENING_BACKLOG.md`, where those
entries still read as open, and was never checked against the code. That is the
exact failure this repository's own rule exists to prevent — *"if a document and
a script disagree, the script is right"* — committed while fixing a defect of
the same family, and it reached a commit message, a published page and a report
to the owner before anyone ran it. `HARDENING_BACKLOG.md` now carries a FIXED
banner on both entries and a warning that its paths predate the move under
`data_layer/`.

What genuinely remains open here is narrower: `_get_data_quality()` still
reports a 1.0 fallback into `RiskAssessment.data_quality` (§B item 17), and
`trader_full.py` still builds a RiskManager with no orchestrator (§B item 16).

### Evidence

`tests/unit/test_risk_data_quality_is_measured.py` — 21 tests. Against the
pre-fix `risk/manager.py`, 12 fail. The 16 existing tests that had to change
were all asserting the fail-open: they built a RiskManager with no orchestrator
and expected a sized position. They now pass `data_quality=1.0` explicitly, so
the assumption is stated in the test rather than supplied by a default.


## §E13 — The drift score that could not report a broken monitor (2026-09-09)

Fifth in the family, and the first one **found by running the application
rather than reading it**. §E9–§E12 came out of code review and registry
screens. This one came out of a booted server answering a real request.

`GET /api/superadmin/ml/status` on a live instance returned:

```json
{"status":"healthy","active_model":"advanced_oos_v1",
 "predictions_today":0,"accuracy_7d":57.34,"drift_score":0.0}
```

A drift score of **0.0 — no drift** from a monitor that had never seen a
prediction, on the same line as `predictions_today: 0`.

### The defect

`api/superadmin/ml_ai.py::_live_drift_score()` returned a hardcoded `0.0` in
four cases: no Redis client, no `ml:drift:status` key, a malformed payload, or
any exception — the last logged at `logger.debug`, which is off in production.
A fifth followed from `.get("drift_score", 0.0)`: a status document that
carried no score at all became a measured zero.

`0.0` is the **best** value on this scale, so "the monitor is down" and
"measured, healthy" were the same reading. `DriftBar` paints below 0.1 green,
so an unreachable monitor rendered as a green **0.000** beside every model.

The function's own docstring said it existed *"so the dashboard never shows a
hardcoded zero while real drift exists"* — while being the hardcoded zero. It
was written to fix a worse version (every row literally `0.0`), and fixed the
rows without fixing the fallback.

### The test asserted it, again

`tests/unit/test_ml_drift_wiring.py` pinned the defect as the requirement, the
third time in this audit that a green suite has described one:

```python
def test_live_drift_score_defaults_zero_when_unavailable(...):
    assert ml_ai._live_drift_score() == 0.0

def test_live_drift_score_never_raises(...):
    assert ml_ai._live_drift_score() == 0.0  # best-effort, swallows errors
```

"Never raises" was right and is kept. The value it fell back to was not.

### What changed

`_live_drift_score() -> float | None` returns `None` when it could not measure,
and logs at WARNING rather than DEBUG. Both endpoints carry a `drift_state`:

| state | meaning |
|---|---|
| `measured` | a real reading, including a genuine 0.0 |
| `unmeasured` | the monitor could not be read |
| `not_serving` | a staged or retired version, which nothing measures |

`/ml/models` rows for non-serving versions previously sent `0.0` under a
comment saying that was correct. Not serving is not zero drift, and the bar
painted it green either way.

The frontend moved with it: `drift_score` is `number | null`, `DriftBar`
renders "— not measured" / "— not serving" in grey with an explanatory title
instead of a bar, and the summary tile reads "not measured". Without that a
`null` would have crashed `.toFixed(3)`.

Two neighbours in the same handler, fixed in the same pass: `get_ml_status`
swallowed an InferenceEngine failure at DEBUG while reporting every figure at
its zero default, and `list_ml_models` did the same for a registry failure and
a directory-scan failure. All three now log at WARNING and say what the reader
is looking at instead.

### Not fixed here, recorded instead

`accuracy_7d` is the active model's **training-time out-of-sample** accuracy,
not a 7-day rolling live figure — nothing computes one. The UI label ("OOS
ACCURACY") is honest; the API field name is not. Documented in the endpoint
docstring and the frontend interface rather than renamed, because renaming a
published field is a contract change. Tracked in §B.

### Evidence

`tests/unit/test_ml_drift_wiring.py` — 12 tests, 10 of which fail against the
pre-fix handler (watched, via git stash). Confirmed end to end on a booted
server: `{"drift_score":null,"drift_state":"unmeasured"}`, and the superadmin
console renders "Drift Score — not measured".


## §E14 — The model abstained and would not say why (2026-09-09)

Found the same way as §E13 — by running it. The owner asked to see the AI run,
so it was handed a 300-bar hourly XAUUSD window. It answered:

```json
{"direction":"neutral","probability":0.5,"confidence":0.0,
 "model_version":"fallback","fallback":true}
```

and nothing else. Nothing in the logs at INFO or WARNING either.

**The abstention was correct.** 300 hourly bars resample to roughly 12 daily,
below `_MIN_BARS`, and the model is trained on daily data — so it refused
rather than guessing. That is the behaviour anyone would want.

The defect is that the reason existed and went somewhere no caller can read.
Every abstention path did three things:

```python
_PROM.fallback_total.labels(symbol=sym_label, reason="insufficient_daily_bars").inc()
logger.debug(...)          # DEBUG is off in production
return base_result         # carries no reason
```

The cause lived in a Prometheus label. `HOPEFXDecisionEngine`,
`core/signal_engine.py` and the dashboards — every real consumer of
`predict()` — saw a flat neutral with no explanation. Diagnosing this at all
meant reading the value back out of the metrics registry by hand.

Ten paths behaved that way: `insufficient_bars`, `insufficient_daily_bars`,
`feature_build_failed`, `feature_validation_failed`, `stale_model`,
`feature_drift`, `model_fallback`, `reduced_feature_set`, `nan_features`,
`all_zero_features`. A neutral signal is the system declining to trade; an
operator who cannot tell a short data window from a drifting model from a stale
artifact cannot act on it.

### What changed

A single `_abstain(result, reason, detail)` helper inside `predict()` now
records the abstention once, in all three places at once — the returned
`reason`, the Prometheus counter, and a log line at INFO with the specifics.
One call site, so the metric and the payload cannot drift apart. `stale_model`
keeps its own branch shape because it may raise, and gained the reason and a
WARNING; the served-prediction path carries `reason: ""`.

The same run also confirms the §E12 fix from the other direction: the evidence
payload reports `data_quality: null` rather than a fabricated 1.0.

### Evidence

`tests/unit/test_inference_abstention_says_why.py` — 6 tests, 5 of which fail
against the pre-fix engine. Re-running the AI now prints:

```
INFO ml.inference_engine: InferenceEngine: abstaining for XAU_USD —
  insufficient_daily_bars (300 intraday bars resampled to too few daily)
reason  'insufficient_daily_bars'
```


## §E15 — Offline prediction, and 441 bars that never happened (2026-09-09)

The owner asked for the AI to be able to predict without a live feed. It turned
out it already could — and the work of proving that surfaced a data defect.

### The data was already there

`data/XAUUSD_40Y.csv` (6415 daily bars, 2000→2026) has been committed for a
long time. Handed 400 of its bars, the engine returns a genuine prediction:
`advanced_oos_v1`, `fallback: False`, 222 features built, `probability 0.4974`
— neutral because that sits between the thresholds, which is a real "no edge"
answer rather than an abstention.

What was missing was a way to *reach* it that carries provenance. Every
existing reader drops it: `api/trading.py` opens the file inline for charts,
`backtesting/cli_runner.py` has its own `load_ohlcv_csv`, and neither returns an
as-of date. A caller gets a DataFrame indistinguishable from a live one — and
this series ends 168 days before today.

`ml/cached_series.py` returns a `CachedSeries` instead: frame plus `source`,
`as_of`, `age_days`, `is_stale`, and a `describe()` that says "cached" out loud.
`as_of` is the last bar, never the read.

**Not wired as a fallback inside the engine, deliberately.** Cached history
reaching `size_order()` would put fabricated freshness back into the path §E12
just closed: the gate refuses when data quality is unmeasured, and a CSV has no
tick confidence to measure. Offline prediction is an explicit request —
`scripts/predict_offline.py` — and it prints how old the data was.

### What the sanity test found

The test began as `assert (high >= low).all()`. It failed, and the failure was
the data:

| violation | count |
|---|---:|
| high < low outright | 1 |
| high below the open/close body | 236 |
| low above the open/close body | 227 |
| **distinct malformed bars** | **441 of 6415 (6.9%)** |

All before 2020 — 416 in the 2000s, 25 in the 2010s — and none in the window
the model predicted on, so that result stands.

It matters anyway, because this is the **primary** file. `api/trading.py`
prefers it for charts under a comment reading *"the clean 40Y file … no
corrupted bars"*, `scripts/build_50y_data.py` calls it *"highest quality
2000+"*, and the 50Y training builds draw on it. Every rolling high, low, ATR
and true range over an affected window is computed from bars that never
happened. `XAUUSD_5Y.csv` and `XAUUSD_2Y.csv` are clean.

**Not repaired.** Dropping or rewriting those bars invents prices for a market
that has already closed. The loader counts them, `describe()` prints a ⚠ line,
and the choice — re-source, clamp with recorded provenance, restrict training
to 2020+, or accept and document — is the owner's, because each one changes
what the models are trained on. Tracked in §B.

### Evidence

`tests/unit/test_cached_series.py` — 18 tests, 17 of which fail without the
module; one marked `slow` drives a real prediction end to end and would fail on
an abstention. `scripts/predict_offline.py` prints the whole chain: provenance,
the staleness warning, the 48% macro feature imputation the engine reports for
itself, the decision, and `data_quality: None` — unmeasured, which offline is
the honest answer.


## §E16 — The same gate, one method over (2026-09-09)

§B item 17 was filed as a reporting problem: `RiskAssessment.data_quality`
defaulted to 1.0, so a risk record produced with the feed down claimed flawless
data. Fixing it found that `assess()` carries its **own** data-quality gate,
which §E12 missed:

```python
data_quality = self._get_data_quality(signal)   # 1.0 fallback
...
if data_quality < _MIN_DATA_QUALITY:            # cannot fire on an unmeasured feed
```

Identical to the defect §E12 closed in `size_order()`, in the method next to it.
§E12 fixed one call site and left the other, because the finding had been framed
around sizing.

**The trade was still refused** — `assess()` calls `size_order()`, which does
refuse — so this was not an open path to a bad trade. What it produced was a
rejection that lied about itself: `reason: "zero_size"` and
`data_quality: 1.0`, naming neither the cause nor the truth. An operator reading
that cannot tell a dead feed from an ordinary zero-size result, and those need
different responses.

### What changed

* `RiskAssessment.data_quality` is `float | None`, defaulting to `None`.
* `_rejected_assessment()` no longer defaults it to 1.0.
* `assess()` gates on `_measured_data_quality()` and rejects an unmeasured feed
  as `data_quality:unmeasured`, with its own branch — `None < 0.40` is a
  `TypeError`, so widening the type without widening the comparison would have
  traded a silent hole for a crash in the money path.

Blast radius checked first: nothing outside `risk/manager.py` reads the field.
`api/graphql_schema.py` builds a different assessment shape and never touches
it, so no external consumer depended on the old type.

### The lesson worth keeping

A defect found at one call site is a defect *shape*, not a location. §E12's
write-up named `getattr(signal, "data_quality", 1.0)` and traced it to
`size_order()`; the same expression was two methods away, reached by
`_get_data_quality()`, and nothing in that phase went looking. Grep the
expression, not the symptom.

### Evidence

`tests/unit/test_risk_assessment_reports_unmeasured.py` — 11 tests, 5 of which
fail against the pre-fix tree, including one asserting the gate does not raise
on `None`. 2300 pass across the risk/gatekeeper/sizing/invariant slice.


## §E17 — The Gatekeeper had no data source, and scored that perfect (2026-09-09)

§E16 ended on "grep the expression, not the symptom". Doing that found
`getattr(signal, "data_quality", 1.0)` a third time, in `risk/gatekeeper.py` —
and pulling the thread found three defects stacked, each hiding the next.

### 1. The fail-closed reader had a fail-open branch

`_get_data_quality_from_orch()` exists to be fail-closed and says so in its own
comment. It returns `0.0` when the tick read raises, and `0.0` when there is no
tick. Then:

```python
if getattr(self, "_orch", None) is None:
    return 1.0          # the one unmeasured state that does not block
```

An absent orchestrator is the *least* measured state there is, and it was the
only one scored perfect.

### 2. Nothing assigned the attribute the factory read

Measured on a booted instance:

```
gatekeeper = Gatekeeper
  gk._orch = None
  gk._get_data_quality_from_orch() -> 1.0
```

`core/startup_factories.py` built it with
`orchestrator=getattr(s, "data_orchestrator", None)`. **`data_orchestrator` is
assigned nowhere in the codebase** — the live orchestrator is stored by
`core/startup_helpers.py` as `data_layer_orchestrator`. One word apart, and
invisible because a missing orchestrator produced a perfect score rather than
an error.

`_run_checks_on_dict` — the event-bus path (`bus.subscribe(CH_SIGNAL)`) — calls
that reader directly, so gate step 5 compared `1.0 < 0.40` forever. Driven in a
test, the gate returned `set()`: no failures for a signal with no measurable
data quality.

### 3. Fixing the name was not enough — the orchestrator did not exist yet

With the name corrected, `gk._orch` was *still* None. The component registry
runs `init_decision_engine`, which builds the Gatekeeper, before
`startup_event` reaches `start_data_layer_orchestrator`. The Gatekeeper is
constructed while no orchestrator exists.

At that point the gate was fail-closed with nothing to measure — correct, and
still not a working gate, because it would block every signal.
`start_data_layer_orchestrator` now back-fills consumers built before it.

Measured after all three fixes:

```
app_state.data_layer_orchestrator = MarketDataOrchestrator
gatekeeper = Gatekeeper
  gk._orch = MarketDataOrchestrator      ← wired
  gk._get_data_quality_from_orch() -> 0.0 ← no gold feed in the sandbox: blocks
```

### A fourth test asserting the defect

```python
def test_data_quality_fallback_when_no_orch(self):
    gk = _make_gk()
    assert gk._get_data_quality_from_orch() == pytest.approx(1.0)
```

Three lines above `test_data_quality_fallback_on_exception`, commented
*"Fail-closed: exception from orchestrator returns 0.0 to block the trade"*.
The same file pinned fail-closed for an exception and fail-open for a missing
orchestrator, in adjacent tests, and the contradiction went unnoticed — because
a perfect score raises nothing. Four other tests built bare Gatekeepers and
expected a clean pass; they now supply a feed that reports healthy, so they test
the confidence and spread gates they claim to rather than riding on the
fail-open.

### Evidence

`tests/unit/test_gatekeeper_data_quality_fail_closed.py` — 9 tests, 3 failing
against the pre-fix tree, plus one `slow` test proving the late-bind (it fails
when the back-fill is reverted). 4272 pass across the
gatekeeper/risk/startup/decision/execution/connector/data-layer slice.


## §E18 — 441 bars repaired, and kept distinguishable from real ones (2026-09-09)

§E15 measured 441 impossible bars in `data/XAUUSD_40Y.csv` and deliberately did
not touch them, because rewriting a price is inventing one. Presented with the
options, the owner chose **clamp with recorded provenance, and default to the
clean 2020+ window** — both, because the second is what keeps the first honest.

### The repair

`scripts/clamp_ohlc.py` applies the smallest edit that makes a bar possible:

```
high := max(high, open, close)
low  := min(low,  open, close)
```

Open and close are never touched — those are prints; the extremes are the
fields contradicting them. Run against the real file:

```
source     data/XAUUSD_40Y.csv  (sha256 7ffc2bf58397…)
bars       6415
edited     441  (6.9%)
range      2001-02-13 → 2011-11-14
wrote      data/XAUUSD_40Y_clamped.csv
provenance data/XAUUSD_40Y_clamped.provenance.json
```

The source is byte-identical afterwards, checked by hash. The sidecar records
the source's sha256 and every edited bar with its before and after, so a later
reader can tell both what changed and whether the repair still matches its
input.

### Why the clean window matters more than the repair

A clamped high is the *lowest high consistent with the body*, not what the
market reached. It is a reconstruction, and this repository's recurring defect
is exactly a reconstructed or defaulted value reaching a consumer that cannot
tell it from a real one. So:

* `CLEAN_SINCE["XAUUSD"] = 2020-01-01` records where the data needs no repair —
  1567 bars, verified `no OHLC violations` by the same check that found the
  441;
* `load_cached_daily(..., since=...)` trims to it, and
  `scripts/predict_offline.py` now defaults to it, with `--full-history` to opt
  back in;
* a series loaded from a file with a provenance sidecar reports
  `repaired: True` and says so in `describe()`.

Three views, all correct at once:

```
REPAIRED  … XAUUSD_40Y_clamped.csv · ⚑ repaired: 441 bars reconstructed   (0 violations)
ORIGINAL  … XAUUSD_40Y.csv · ⚠ 441 malformed bars (6.9%)                  (untouched)
CLEAN     … 1567 bars · 2020-01-02 → 2026-03-25                           (no warning)
```

### Still open

Re-sourcing 2000–2019 from a data vendor, which would replace reconstructions
with observations. Not possible here — the egress proxy blocks yfinance and
every market source tried — so it needs a Codespace with network access.

### Evidence

`tests/unit/test_ohlc_clamp_and_clean_window.py` — 14 tests, 13 failing before
the implementation. They pin that clean bars are byte-identical after the
repair, that open and close are never altered, that the source is not modified,
that every edit is recorded with before and after, and that the window
advertised as clean really is. 1758 pass across the affected slice.


## §E19 — 23 dependency advisories, and the audit that never ran (2026-09-09)

Dependabot reported 29 open alerts. The GitHub App backing this session has no
Dependabot permission — `/repos/.../dependabot/alerts` returns
`403 Resource not accessible by integration` — so rather than read the list, the
dependency trees were scanned directly with `pip-audit` and `npm audit`.

### What is actually exposed

| surface | advisories | **reaches production** |
|---|---:|---:|
| `frontend/` npm | 21 (17 high, 4 moderate) | **0** |
| `dashboard/` npm | 2 (1 high, 1 moderate) | **0** |
| `requirements.txt` | 1 (`nltk`) | 1 |
| installed venv | 2 (`nltk`, `ecdsa`) | 2 |

`npm audit --omit=dev` returns **NONE** for both workspaces: every one of the 23
npm findings is build tooling — the `@babel/*` chain behind `vite-plugin-pwa`,
`browserslist`/`autoprefixer`, `js-yaml`, `vitest`. Nothing vulnerable is
shipped to a browser. That is a materially different picture from "19 high", and
worth stating plainly rather than reporting the raw count.

It is not nothing: a compromised build chain writes the bundle a browser
executes. `npm audit fix` cleared all 23 without a breaking change, and the
result was verified rather than assumed — `tsc --noEmit` clean, `vite build`
clean (77 assets), **2594 frontend tests pass**.

### The two Python advisories, traced

Neither is imported by first-party code; both are transitive, and neither has a
published fix.

* **`ecdsa` 0.19.2 · PYSEC-2026-1325** — a Minerva timing attack on P-256 that
  leaks the nonce from `SigningKey.sign_digest()`. Verification is unaffected.
  Pulled in by `hdwallet`, which `payments/crypto/bitcoin.py` uses for **BIP84
  address derivation** only; signing and broadcast are delegated to BitGo,
  Fireblocks or Bitcoin Core RPC. JWT auth is `HS256` everywhere — no ECDSA.
  No `sign_digest` call exists in this repository.
* **`nltk` 3.10.3 · PYSEC-2026-3740** — a file-sandbox bypass in
  `TransitionParser`. Pulled in by `textblob` for `news/sentiment.py`.
  `TransitionParser` is not referenced anywhere in the codebase.

### The finding underneath the findings

The Python dependency gate in `.github/workflows/security-scan.yml` is well
built: it blocks only on advisories that have a **published fix**, so an
unfixable one is information rather than a stuck pipeline. Both of the above
correctly pass it.

**No workflow ran `npm audit` at all.** bandit, safety, pip-audit, Trivy and
CodeQL are all wired; the npm dependency trees were watched by nothing, which is
how 23 advisories accumulated unnoticed. A new `npm-audit` job now runs over
`frontend` and `dashboard` under the same policy as the Python gate.

Proven by execution rather than asserted: the gate's exact logic exits 1 against
the pre-fix lockfile ("BLOCKED: 2 high/critical advisory(s) have a published
fix") and 0 against the fixed one.

### Not done

Reconciling against Dependabot's own list of 29, which needs the API permission
this session lacks. The gap between 23 and 29 is most likely Dependabot counting
per-manifest and including `requirements-dev.txt` / `requirements-optional.txt`
separately.


## §E20 — Twelve orphans, triaged rather than silenced (2026-09-09)

Gate E reported zero dead files for its whole life. §E3–§E12 fixed three stacked
defects in its own detection — single-file guarded packages skipped,
bare-package imports unresolved, and a substring match excluding every mirrored
test file — and it immediately failed CI with twelve unreferenced modules,
5,178 lines between them.

That failure is the gate working. Resolving it is the work that follows.

### The triage

Deleting is not an option, and wiring twelve modules blind would be worse than
leaving them: several are alternates for something already running. Each is
recorded in `KNOWN_UNWIRED` with the reason it stays.

| module | why it has no caller |
|---|---|
| `brokers/oanda_ws.py` | Tombstone — its own docstring says REMOVED; streaming moved to `data_feed.NuclearStreamer` |
| `core/tenancy.py` | **Superseded, verified** — see below |
| `risk/risk_manager.py` | 63-line backwards-compatibility shim re-exporting `risk.manager` |
| `execution/execution.py` | Alternative startup wiring, like `trader_full.py`; invoked by hand, not imported |
| `core/acceleration/gpu_engine.py` | Requires CUDA; already omitted from coverage for the same reason |
| `brokers/mt5_zmq_bridge.py` | MetaTrader 5 is Windows-only; the SDK will not install in CI or on the Linux VPS |
| `core/domain_models.py` | Pydantic schema; production duck-types these objects via `getattr` rather than importing the classes |
| `risk/analytics.py` | `risk/advanced_analytics.py` is the wired one |
| `risk/position_sizing.py` | `risk/manager.py` carries the sizing that runs |
| `core/circuit_breaker.py` | `utils/fault_guard.py` is the wired one |
| `risk/compliance/prop_engine.py` | Prop-firm config is read elsewhere |
| `brokers/prop_firms/all_brokers.py` | 1301 lines of prop-firm adapters, no current caller |

### The one that looked like a security hole

`core/tenancy.py` exists because — in its own words — *"the filters added
afterwards landed on some endpoints and not others: `GET /api/trading/positions`
filtered, `GET /api/trading/orders` did not, `/balance` did not,
`api/portfolio.py` did not, and the WebSocket account broadcaster pushed one
account's equity to every subscriber."*

A module written to close a multi-tenant data leak, imported by nothing, is
alarming. Checked rather than assumed: all three named endpoints filter today
via `_resolve_account(user.sub)` and `_user_broker_call(user.sub, ...)`. A
different mechanism — per-user broker accounts — closed the leak, which is why
`tenancy.py` never acquired a caller. **Not a live gap.**

### Keeping the list a debt and not a graveyard

An allowlist with no pressure on it becomes an off-switch — the lesson from
gate-g, whose line-keyed entries taught people to bump numbers. Three properties
are pinned by test:

1. every entry carries a substantial, non-placeholder reason;
2. no entry has since been wired (a module that gained a caller must leave);
3. every listed file still exists.

And the one that matters most: an orphan **not** in the registry still fails the
gate, proven by mirroring a tree with an unimported module and watching it exit 1.

### Evidence

`tests/unit/test_gate_e_known_unwired_is_a_debt_not_an_offswitch.py` — 6 tests.
`python scripts/ci/gate_e_dead_files.py` now exits 0, printing all twelve with
their reasons rather than hiding them.


## §F — What the complete Group 4 source changed (2026-09-08)

The owner supplied the full Volumes I–XX document. The earlier source was a table
of contents; this one carries a statement under every section. **It is not a
superset**: it names 118 sections where v1 named 186 chapters, so neither
replaces the other and both are now listed side by side in
`GROUP4_VOLUME_INDEX.md`.

| What changed | Detail |
|---|---|
| **Two Articles added** | XI — Reversibility · XII — Privacy. The source's System Constitution names twelve principles; this document carried ten. Both were already enforced in code (`core/idempotency.py`, `core/outbox.py`; `ai/privacy/consent.py`) and neither was written down, so the document changed, not the code |
| **One new High item** | Decision Governance (§B2 item 14) |
| **One new control** | `scripts/group4_preservation.py` — 304 titles across both sources, checked against what the repository actually lists. Proven able to fail by deleting a row from each source's table and watching it report the omission |
| **Four volumes renamed** | III, IV, VIII and XIX carry longer titles in v2; both names are recorded in the index |
| **One concrete addition to Part VIII** | NPU joins the execution-target set (`cpu`, `gpu`, `npu`, `remote`, `local-model`, `distributed`) |
| **A declaration contract** | Fourteen fields every subsystem must declare, plus ten mandatory engineering requirements. Group 4 Ch 8. **Specified and unenforced** — a candidate for the next gate, not a claim that one exists |
| **Nothing removed** | The preservation rule is now mechanical rather than intentional |

### The owner's six governing principles, and where two of them are thin

Recorded in full at Group 4 Chapter 12. Four have real enforcement. Two do not:

* **Measure intelligence rather than assuming it** — Article X, the weakest of the
  twelve. Enforced by habit (every phase reports measured numbers) and by
  Group 2 Rule 2, but by no gate.
* **Preserve institutional memory** — INV-13. `ai/memory/` exists; decision memory
  and failure memory are specified and unbuilt. This is §B2 items 12–14.

Claiming six-for-six would be exactly the assertion Article II forbids.

## §E20 — The coverage gate had never measured anything (2026-09-09)

Found the way §E13 and §E14 were: by running the thing rather than reading it.
The gate had a test suite, an injection suite, a ratchet file and a 361-module
debt record. What it did not have was a single successful measurement, in its
entire life.

```
pytest <test> --cov=risk.manager --cov-config=.coveragerc
    numpy/_core/multiarray.py:11: in <module>
        from . import _multiarray_umath, overrides
    ImportError: cannot load module more than once per process
```

Every module in scope imports numpy transitively through `tests/conftest.py`, so
the failure was total. The gate reported it as

> coverage could not be measured (test: …) — the test may not import the module,
> or may fail to collect

which blames the test file, and whose natural next move is `SKIP_COVERAGE_GATE=1`.
A gate that cannot run *and* misattributes why is worse than no gate: it teaches
the bypass.

### The cause, isolated by bisecting rather than reading

| invocation | result |
|---|---|
| `pytest <test>` | works |
| `pytest <test> --cov=risk.manager` | ImportError — dotted **module** |
| `pytest <test> --cov=risk` | works — **package** |
| `pytest <test> --cov=risk/manager.py` | no error, collects nothing (`.coveragerc` `source` wins) |

Nothing to do with numpy being broken; it imports fine under `coverage run`
alone. Resolving a dotted *module* name makes coverage import the module itself.
A package name resolves as a directory and imports nothing.

The gate now measures the top-level package and reads the module's own row out of
the report. `TOTAL` is deliberately **not** a fallback: under a package-wide
`--cov` it is the package's number, and reporting it as the module's would be a
fabricated measurement of precisely the kind this gate exists to catch.

### Three real numbers, where there had been none

```
DEBT risk/gatekeeper.py:      21% < 80%   (recorded)
DEBT api/superadmin/ml_ai.py: 48% < 80%   (recorded)
FAIL risk/manager.py:         43% < 80%   (not recorded — blocks)
```

One figure needs stating so nobody reads it as a collapse: `risk/manager.py`
measures 43% here and 89.65% in `.coveragerc`'s recorded figure. Both are right —
this gate runs one test file, that figure runs the whole suite. Quoting the
gate's number as the module's coverage understates it by 46 points, so the
module docstring now says so.

### Repairing it was the easy half

`docs/COVERAGE_UNMEASURABLE.txt` records 361 modules, and — see the correction
now attached to §E5 — every entry is an artefact of the broken invocation. Fixing
the invocation without touching the list would swing the gate from passing
everything to blocking every commit that touches any of 361 files, and a gate
that blocks work people must do gets switched off. That is the same outcome by a
different route.

So the record became a ratchet with pressure in both directions, the shape the
document registry and gate-evidence ledger already use:

| state | outcome |
|---|---|
| recorded, under the floor | **DEBT** — real number on stderr, does not block |
| recorded, at or above the floor | **BLOCKS** — delete the line |
| not recorded, under the floor | blocks |
| not recorded, unmeasurable | blocks |

The second row is the tooth. Without it this is an allowlist, and an allowlist
under no pressure is how a ratchet stops being one. `--adopt` now preserves the
file's header rather than rewriting it, so regenerating cannot quietly revert the
record's meaning to the pre-repair wording.

`risk/manager.py` is deliberately **not** added to the record. It blocked before
this change and blocks after, so nothing regressed — and putting the pre-trade
gate, VaR/CVaR and Kelly sizing on a debt list to make a commit go through is the
one move this entire exercise argues against.

### What the same run turned up

`pytest -m "not slow and not e2e"` finished **6 failed, 21539 passed**. All six
are closed, and none by editing a test until it went quiet.

**Four were one defect.** `ml/cached_series.py::_check_integrity` judged whether a
bar was possible with three comparisons, and every comparison against NaN is
False — so a bar with a missing high satisfied all three and was counted sound.
The report then said "no OHLC violations" about a series that cannot be used for
anything. The whole point of that module is that a caller cannot tell a good
series from a bad one by looking at a DataFrame, so an integrity report that
clears bad data is not a weak measurement but a fabricated one.

Caught by the repository's own analyzer (`security/code_analyzer.py`, category
`nan_leak`) — the four failing tests were its zero-findings gates, and all four
were right to fail. Fixed by masking every comparison with a finiteness check
first, the order every predicate in `invariants/` uses. NaN bars are counted
separately as `non_finite`, because a missing value contradicts nothing and
folding it into `high_below_low` would put a violation in the record that the
data does not contain. Measured against the real file: `XAUUSD_40Y.csv` has **0**
non-finite bars, so §E15's and §E18's 441/6415 figure is unchanged.

**One was a test encoding the defect §E12 removed.**
`test_full_trading_cycle` built a RiskManager with no orchestrator and expected a
$20,000 position — which passed only because unmeasured data quality scored a
perfect 1.0. It has a data layer now, and the refusal it used to contradict is
held beside it by `test_the_cycle_refuses_without_a_data_layer`, so the wiring
cannot be mistaken for working around a red light.

**One was surface, not substance.** Two injection tests asserted the gate's old
wording. Both requirements still hold and are asserted more directly: an operator
must still be able to tell "coverage is low" from "coverage is unknown", and that
distinction is now *stronger* — a module its test never imports reports 0.00%,
which is a measurement, and calling it unknown would be the same Rule 2 error
pointed the other way.

### And the gates themselves had never been installed

This was found by noticing that a commit produced no hook output. There was no
hook. Every ratcheted check CLAUDE.md leans on — document registry, doc
freshness, Group 4 preservation, volume index, gate evidence, doc metrics, and
this coverage gate — protected only a contributor who remembered
`pre-commit run --all-files` by hand. CLAUDE.md's own sentence, "the ratcheted
checks below run in `pre-commit`, so a regression blocks rather than
accumulating", was describing something that was not happening.

Configured, accurate, never invoked: the §E9–§E12 shape, applied to the
machinery whose job is catching that shape. Which is also why it went unnoticed
so long — the gate that would have flagged it was one of the ones not running.

`scripts/bootstrap_dev.py::install_git_hooks()` now runs
`pre-commit install --install-hooks`. It deliberately does **not** fail
bootstrap: a developer without `pre-commit` on PATH still needs a working `.env`
and seeded users, and a bootstrap that dies on an optional step is one people
stop running, which would leave the hooks uninstalled for a second reason. It
returns False and warns — including on a non-zero exit, because reporting
success for work that did not happen is the defect this repository has spent the
most time removing.

Proven by running it: no hook before, `.git/hooks/pre-commit` after, and every
commit from that point ran the full set.

**Still an owner decision:** whether CI should also run `pre-commit run
--all-files`. Installing locally closes the gap for anyone who bootstraps; it
does not close it for anyone who does not, and a CI job changes what blocks a
merge.

## §E21 — The camera that was there all along (2026-09-09)

§18's `vision.gesture` and `vision.pointing` were the last two rows of the AI Hub
plan with real work in them, and they had been staged across two phases on one
recorded reason:

> There is no camera in the environment this was built in. Installing a
> two-megabyte runtime and an eight-megabyte model into a platform that moves
> money, and never executing either once, is committing code on faith.

The reasoning was sound. The premise was not, and nobody re-checked it — a
decision recorded as settled is the hardest kind to re-examine, which is why it
survived two phases of work that touched the files either side of it.

**Chromium serves a video file as a webcam.** `--use-fake-device-for-media-stream`
with `--use-file-for-fake-video-capture` has existed for years. What was missing
was the idea, not the hardware.

### What it took to falsify

| Claim on record | Measured |
|---|---|
| the dependency is a supply-chain question | `npm view @mediapipe/tasks-vision` resolves; the model host returns 206 |
| there is no camera | Chromium 141 fakes one from a `.y4m` |
| a hand to point it at | MediaPipe publishes its own test photograph |

### What now exists

* `hub/handDetector.ts` — the producer `landmarks.ts` was deliberately missing.
  The runtime arrives through a dynamic `import()`, so an operator who never
  turns this on downloads none of it — verified against the built bundle, where
  no chunk contains the detector.
* `hub/handGestureSource.ts` — a run of frames becomes one gesture track. A hand
  has no pointer-up, so a gesture ends when the hand LEAVES, and "leaves" is a
  RUN of empty frames rather than one: a single dropped detection mid-swipe is
  ordinary, and cutting the track there makes two gestures too short to read.
* `scripts/fetch_hand_model.py` — deploy-time fetch, sha256-verified, into this
  origin. Not committed: 7.8 MB against a 500 KB cap, and its absence is a
  *state* (`unconfigured`) rather than a break.
* `npm run prove:hands` — two phases. The detector against a still photograph;
  then the whole chain off a fake camera.

### The evidence

```
PHASE 1  21 landmarks · a 5-point track · pointing at "order-ticket"
PHASE 2  76 frames · 4 tracks · swipe_left ×4 · 481–600px over 326–441ms
```

`swipe_left` from a hand travelling left to right is the assertion doing work:
the console mirrors the camera because an operator sees their own reflection,
and a version that followed the raw coordinate would move focus the opposite way
from the gesture.

### Three defects the proof found, none of which a reading would have

1. **`landmarkStatus` reported "your browser cannot run it" about a runtime it
   had never tried to load.** The branch read `runtimeAvailable !== true` with
   the comment "an unmeasured runtime is absent, never present" — half of Rule 2.
   Not claiming an unprobed runtime works is right; stating it as broken is the
   same error reversed. Since consent is checked *before* the runtime loads, the
   ordinary "hasn't said yes yet" case hit this, so every such operator was sent
   to look for a browser fault that did not exist. `unsupported` now means
   probed and failed.
2. **A closed detector claimed the same thing.** Switching camera gestures OFF
   reported `unsupported`. Caught by the proof printing `closedState`, and the
   proof's own assertion was too weak to catch it — it ruled out one wrong answer
   and let the others through.
3. **The synthetic gesture was wrong three times, and `recogniseGesture` was
   right each time.** A 1.6-second swipe (`SWIPE_MAX_MS` is 600), then a 30fps
   video the detector undersampled to two points, then five positions that jumped
   128px and lost MediaPipe's inter-frame tracking. Each time the temptation was
   to loosen a threshold; each time that would have changed what a swipe means
   for POINTER input, to accommodate a video file.

### Why the rows are still staged

Nothing an operator can reach turns this on. `visionSource.ts` — §18's source
selector — has no production consumer either, so there is no existing control to
extend, and adding one is a UI change to a trading console.

**Whether this console may watch its operator through a webcam is the owner's
decision.** Marking a capability live that nothing can reach is precisely the
dead-control shape this registry exists to catch, and is the same reason Phase I3
refused to call these rows live for pointer input.

So the position moved from *blocked on something unverifiable* to *one decision
from live, with the code proven by execution*.

### The owner decided, and it is built — 233/233

**Opt-in toggle, off by default.** Shipped as the "Hands" control in
`PresenceStage`, beside Talk / Stop / Aloud, with the status reason on its
tooltip so an operator whose gesture does nothing learns which of the four
absences it is.

`useHandGestures` opens nothing while it is off — not "opens and closes", not
"prompts and is refused". `hub_camera_toggle_is_off_by_default.test.tsx` asserts
that rendering the stage never calls `getUserMedia`, because "off by default" is
exactly the property that survives review and dies to a later one-line change.
Every camera track is stopped on disable and on unmount: the hardware light
going out is how the operator knows it stopped.

The pointer and the camera now go through **one** `applyGesture`. Two rules for
what a swipe is would eventually disagree, and an operator could not be told
which one their console was using.

    233 rows · 233 live · 0 staged · 0 planned · 233/233 evidence resolves

§4's `arch.layer_a.presence` moved by itself, which is the derivation working:
nothing typed it live, the layers beneath it closed and it followed.

### "The camera should be able to work in background as well"

Owner's request, mid-build, and it caught a defect that was already written.

The loop was `requestAnimationFrame` — the obvious choice for anything reading
video, and wrong here: **browsers stop firing rAF entirely in a hidden tab.**
Switch tabs and the camera stays open, the hardware light stays on, and not one
frame is read. A control that looks alive and does nothing, shipped into the
exact feature where the operator can see it is watching them.

`hub/backgroundTicker.ts` drives the loop from a dedicated Worker instead. A
hidden document's timers are throttled to roughly one a second — too slow for a
500ms swipe — and a Worker's are not. There is no `visibilitychange` handling
anywhere, deliberately: a loop that switches strategy on visibility has a second
path that only runs when nobody is looking at it. A Worker that cannot be built
(a CSP without `blob:`) falls back to `setInterval` and *reports* that it did,
because a throttled loop beats no loop and pretending they are equivalent does
not.

**What is proven and what is not**, kept apart:

* **Proven by execution** — the loop is Worker-driven (`tickerKind: "worker"` in
  the phase 2 transcript), and `startTicker` never touches rAF (unit-asserted
  with a spy).
* **Not proven here** — that frames keep arriving with the tab genuinely hidden.
  Headless Chromium reports every page `visible`; `bringToFront()` on another tab
  does not change it, and there is no CDP override — `Emulation.setPageVisibilityOverride`
  does not exist, and `Page.setWebLifecycleState` leaves `visibilityState` alone.
  Both were tried. The proof therefore asserts the mechanism and *reports* the
  hidden-frame count rather than requiring it: an assertion that can only pass
  vacuously is worse than none.

## §E22 — Decisions get numbers, and the ratchet that proves gates work was one command from broken (2026-09-09)

Group 3 Chapter 6 opens with "Nothing in the repository implements ADRs", and
names the cost precisely: **re-litigation**. A decision whose reasoning is not
recorded is re-argued whenever someone new meets it, and sometimes reversed by
someone who does not know what it was protecting.

This session produced two of exactly that, which is why it was built now:

* §E20 corrected §E5's "verified by execution" claim — written in the very phase
  that made the check fail, and never re-checked.
* §E21 reversed a two-phase-old conclusion whose premise ("there is no camera
  here") nobody had re-examined.

Both were recoverable only because the reasoning had been written down
*somewhere*. `docs/ai/AI_HUB_DECISIONS.md` is that somewhere, and Group 3 names
its three limits exactly: it cannot be pointed at from a code comment, it cannot
be superseded in part, and it grows without bound.

### Nine records, and one real supersede chain

`docs/decisions/`, numbered and immutable, plus `scripts/adr.py`
(`--list`, `--check`, `new "Title"`). The spec named eight decisions to
back-fill; there are nine, because **0007 → 0009 is a decision this repository
genuinely reversed**: "ship everything except the model, there is no camera
here" superseded by "fetch it at deploy time, Chromium serves a video file as a
webcam".

That chain is the argument for the whole chapter in one file pair. The old
record is not edited and not deleted — it keeps its reasoning, gains a status,
and points at what replaced it.

### What is enforced, and the defect behind each rule

| Rule | Why |
|---|---|
| Two options minimum | One option is justification written after the fact |
| Every section, none empty | An empty heading is what a template leaves behind, and it passes a naive check |
| Immutable once accepted | A record that can be rewritten records what we *currently believe* we decided |
| A supersede must resolve | `superseded by 0042` pointing at nothing tells a reader their answer exists somewhere |
| Gapless numbering | So `see 0007` is stable for ever, and a gap cannot hide a deleted record |

Immutability is checked against **git**, not a hash manifest: a manifest is a
second file to edit, and the history is already authoritative. The one permitted
edit is a status becoming `superseded by NNNN` — proven both ways by execution,
a content change exiting 1 and a status-only change exiting 0.

### Adding the gate broke two other gates, and both were right to break

**The gate ledger refused it immediately.** `adr-check` appeared as a 24th gate
with no row in `GATE_EVIDENCE.toml`: *"A new gate ships with evidence it can
fail, or it is treated as absent (Rule 1)."* Exactly the intended behaviour, on
the first new gate since the ratchet reached zero.

**Then `--generate` corrupted the ledger.** The documented way to add a row
interpolated human-written text straight into a TOML basic string:

    f'injected = "{prior.injected}"'

`gate_d_model_accuracy`'s row contains a quoted phrase, so regenerating produced
TOML that would not parse, and every subsequent `--check` died before reporting
anything. **The ratchet that proves every other gate can fail was one documented
command away from being silently disabled** — and a backslash would have been
worse than a quote, parsing as an escape sequence and quietly altering the
recorded evidence rather than failing loudly.

Fixed with a real escaper and a round-trip test that regenerates the *committed*
ledger and re-parses it, so the tool can no longer write something it cannot
read. Found only because adding a gate is the operation that exercises it.

**And the freshness checker started calling a naming rule a stale path.** Group 3
writes `docs/decisions/NNNN-short-title.md` as a pattern; the moment
`docs/decisions/` existed, the checker resolved it and blocked. A false positive
that arrives precisely when the specified thing gets built is the worst timing
for a gate people can silence, so paths containing a template token are now
recognised as patterns.

### Measured after

    adr.py --check        9 records, all well formed
    gate_evidence.py      29 gates · 29 proven able to fail · 0 unproven
    docs_registry.py      0 blocking (all nine registered T3, owned)
    docs_freshness.py     0 blocking · doc_metrics 0 drifted

The stated gate figure in §B0 moved 23 → 24 in the same commit, because a
document carrying a number that stopped being true is worse than no document.

### What remains of item 13

The **Registry** half is done. The **Decision Ledger** (Group 3 Ch 7) and
**outcome memory** (Ch 8) are not: an append-only record of decisions made by
*automated* actors, with refusals as first-class entries, and a stated
prediction so an observed outcome has something to be compared against.
That is the half that makes the platform experienced rather than merely
knowledgeable, and it is still open.

## §E23 — The ledger, and the caller that keeps it from being scenery (2026-09-09)

§E22 built the Architecture Decision *Registry* — design decisions by humans.
This is the other half of ranked item 13: Group 3 Chapter 7's ledger of
*operational* decisions by the system, and Chapter 8's outcome linkage.

### Why a fourth recorder, when three already exist

`ai/gateway/audit.py` records model calls, `ai/improve/proposal.py` records
AI-proposed changes, pull requests record approvals — and the spec's diagnosis
is that this is precisely why nobody can answer "what did the platform decide
today?". The risk of getting it wrong was making that four unanswerable
questions instead of three, so `ai/ledger/` **consumes** rather than restates:
authority tiers imported from `ai/policy/roles.py`, calibration delegated to
`ai/core/calibration.py`, credential screening from `ai/guardrails/output.py`.
Recorded as ADR 0010, including the failure mode — if a later change has the
ledger keeping its own tier list, this decision has been undone in substance
while the file still exists.

### The three properties that make it worth having

**Refusals are entries, not absences.** A ledger of actions *taken* cannot tell
a system that was never asked from one that refused, and on this platform the
refusals are the evidence that governance worked. A refusal must name the
control that produced it, because Chapter 7's own KPI is refusals recorded
versus refusals observed — and "something said no" cannot be checked against a
control's logs.

**A prediction is required.** Chapter 8 makes it load-bearing: without a stated
expectation an observed outcome has nothing to be compared against and learning
degrades into narrative. A decision cannot be recorded without one; a refusal
needs none, because nothing happened.

**Unmeasured stays unmeasured.** Confidence is `None` when nobody stated one,
never 0.5, and its calibration class is `None` with it. A governance record is
the worst possible place to reintroduce the defect §E12 through §E21 kept
finding.

### Two rules deliberately differ from the ADR gate

* **One option is allowed here.** An ADR with one option is justification
  written afterwards. An automated router legitimately has one candidate when
  the others are unavailable, and demanding a second would make the ledger
  describe a choice nobody had.
* **`held` must be stated.** Accuracy is never inferred from prose. Comparing a
  free-text prediction against a free-text observation would manufacture exactly
  the unmeasured figure this work has been removing; what the module guarantees
  is that the question was *asked*.

### The caller, because a ledger nobody writes to is scenery

Building this without one would have committed the F176 shape inside the module
meant to record it — Chapter 7's KPI is ledger coverage, and a schema with no
callers has zero coverage while every unit test passes.

`risk/manager.py::_zero_sizing` is the first caller and not an arbitrary one: it
is the single funnel every sizing refusal passes through, and those refusals —
`data_quality:unmeasured` above all — are this repository's clearest evidence
that a gate did its job. Until now the only record of one was a WARNING line.

**Recording never changes what the money path decides.** A ledger write that
raised would turn a refusal into a crash, strictly worse than the defect it
documents. So it is wrapped, and wrapped at ERROR rather than silently: F248's
alert failures went unnoticed for as long as they did because a handler swallowed
them. `test_a_broken_ledger_does_not_break_a_refusal` injects a raising ledger
and asserts the refusal still happens; the test that the refusal happens at all
is asserted *first*, so a wiring bug cannot hide behind it.

### And it gave calibration the caller it never had

`ai/core/calibration.py` has `record()` and `resolve()`. Nothing called
`resolve()`, so every stated confidence stayed unscored and `assess()` had
nothing to assess — a measurement apparatus with no inputs, which reads as
working. `outcomes.observe()` closes that loop.

### One defect in the tooling shipped an hour earlier

`adr.py new "Title"` — the invocation the README and the module docstring both
give — failed with *unrecognized arguments*: `new` was a single positional and
the title had nowhere to go. Found by running it. A tool whose documented
invocation does not work teaches people it is broken, and sends them back to
recording decisions in commit messages, which is the thing §E22 exists to stop.
Fixed, with tests that run the documented command.

### Measured

    pytest -k "risk or ledger or calibration"    1988 passed
    test_decision_ledger.py                      24
    test_ledger_outcomes.py                      20
    test_risk_refusals_reach_the_ledger.py       8   (5 fail on the pre-wiring tree)
    adr.py --check                               10 records, all well formed
    docs_registry / docs_freshness / doc_metrics 0 blocking · 0 drifted

### What is still open from item 13

Group 2 Chapter 6's **change records carrying an expected effect** — the same
prediction field one layer down, attached to a deployment rather than a
decision. Ranked item 5, still open, and now the only part of Decision
Governance that is not built.

## §E24 — Change records, and a hole in the gate that enforces gates (2026-09-09)

Ranked item 5, and the last open part of Decision Governance. §E22 recorded
design decisions by humans, §E23 operational decisions by the system; this is
the same prediction field one layer down, attached to a deployment.

Chapter 6's own sentence for why:

> A deployment log records that something happened, and a change record records
> what it was *for*. Only the second can be evaluated. **A history without
> predictions cannot teach anything.**

### Generated, not written — except the one field that matters

Every field comes from git and the tree. The exception is the expected effect,
which is the point: it is the only field a machine cannot derive and the only one
that makes the record evaluable. It arrives as an `Expected-Effect:` commit
trailer, because trailers are already how this repository carries structured
commit metadata (`Co-Authored-By`, `Claude-Session`) and a prediction kept
anywhere else drifts from the commit it describes.

Enforced at **`commit-msg`**, not `pre-commit`: the trailer being checked does not
exist yet at the earlier stage.

### The tier is derived from paths, and the module says so

Chapter 6 sources "packages touched" from Chapter 1's package register, which
**does not exist** — ranked item 10, still open. `TIER_SOURCE = "path-prefix"` is
printed on every report and the docstring states it plainly, because a path table
silently substituted for the register would make item 10 look delivered. That is
the shape §E20 had to correct in §E5. Recorded as ADR 0011, including what would
constitute reversing it.

**Unknown is not safe.** An unclassified path is `unknown`, never `presentation`,
and `unknown` requires a prediction exactly as `core` does. Rule 2 where it costs
most: the alternative is that the first unclassified package added to this
repository is the one that ships unpredicted.

### Two defects the first version had, both found by running it

**`lstrip("./")` strips a character SET, not a prefix.** `.gitignore` became
`gitignore`, and `.github/workflows/ci.yml` would have become
`github/workflows/ci.yml` — a path matching no prefix, landing in the wrong tier
silently. Caught by a parametrised root-path test.

**The root fell through to `unknown`,** so editing `CLAUDE.md` demanded a
deployment prediction. Friction with no safety in it, and friction is how a gate
earns a bypass. Calling the whole root `presentation` would have been the
opposite error: `app.py`, `run.py`, `hopefx_engine.py` and `trader_full.py` all
live there and all start the trading path. Root prose is presentation; anything
else at the root is `core`.

`.github/` and `.pre-commit-config.yaml` are classified `core` on evidence rather
than instinct: CI is the control plane for every gate here, and §E20 found the
pre-commit hooks had never been installed, so seven ratcheted checks protected
nobody.

### And the gate that enforces gates could not see it

`scripts/gate_evidence.py` discovered hooks by matching `scripts/*.py` entries.
This hook runs `python -m deployment.change_records`, so **it was invisible**: the
ledger reported 24 gates before and after it was added, and `--check` passed.

Any gate written as a module rather than a script was silently exempt from Rule 1
— a hole in the census that every other gate's evidence depends on. Discovery now
matches `python -m <dotted.module>` too, but only for modules this repository
owns, since a `python -m` of a third-party tool is not a gate we can carry
evidence for. Adding the match immediately produced the block it should have
produced an hour earlier, and `tests/unit/test_change_record_gate_injections.py`
is what it then demanded.

That is the third time this session that adding something exposed a hole in the
machinery meant to catch holes — the ledger's TOML writer in §E22, the coverage
gate's single-file measurement in §E23, and now the gate census.

### One more dead control, one hook type over

`bootstrap_dev.py` ran `pre-commit install`, which installs only the `pre-commit`
hook type. The change-record gate runs at `commit-msg`, so a fresh clone would
have had it as a dead control from the day it shipped — §E20's defect, repeated
one hook type over. Both types are installed now.

### Measured

    change_records                                42 tests
    change-record gate injections                 15 tests
    gate_evidence.py                              29 gates · 29 proven · 0 unproven
    adr.py --check                                11 records, all well formed
    docs_registry / docs_freshness / doc_metrics  0 blocking · 0 drifted

Run against real history: the §E23 commit reports `core` (it touches `risk/`) and
is correctly refused for stating no expected effect; the §18 commit reports `ai`
and is not.

### What this unblocks

Group 1 §16 (operational correlation — "what deployed just before latency rose"
is unanswerable without it), §21 (technical-debt forecasting, which needs
modification frequency per package) and §32 (outcome memory).

**Decision Governance is now complete**: ADRs for human design decisions, the
ledger for automated operational ones, change records for deployments, and one
prediction field running through all three.

### The owner chose warn over block, and the KPI is measured rather than met

Asked directly, the owner chose **warn** (ADR 0012). Implemented literally,
Chapter 6's 100% target would have refused 4 of this session's last 12 commits —
a real change to how the only committer commits, and the kind of interruption
that ends in a bypass. §E20 is this repository's own example of a gate switched
off rather than satisfied.

The objection to warning is real and the record does not pretend otherwise: a
gate that only warns is one people learn to scroll past. Three things answer it,
each asserted in the injection suite:

* the warning names the exact trailer to add, so acting is cheaper than ignoring;
* `CHANGE_RECORD_ENFORCE=1` blocks with no code change, so the policy is
  configuration and can be turned on in CI, on one branch, or permanently;
* `--report` measures the KPI, because **a warning whose effect is never measured
  is precisely what the objection is about**.

`validate()` is unaffected by the policy. It reports the problem either way — the
decision is about the exit code, never about the truth.

The first measurement, over this session's own commits:

    changes 12 · needing a prediction 5 · with one 1 · coverage 20%

A real starting number rather than a target met by force. `coverage` is **None**
when nothing in a range needed a prediction — a perfect score from an empty
denominator is the oldest fabricated metric there is, and this module refuses to
report one, the same rule the risk gate applies to data quality and the ledger to
confidence.

`docs/GATE_EVIDENCE.toml` now carries the caveat that this is the one gate in the
ledger that does not block by default. Twenty-five gates counted as blocking when
one is advisory would be the same fabrication the ledger exists to prevent.

## §E25 — The platform audit, and what it found (2026-09-09)

A full audit, measured rather than reviewed: 708,885 lines of Python across
1,882 files and 124,027 of TypeScript across 444 are more than anyone reads in
a session, and this repository carries enough instrumentation that reading the
gauges is the better audit. The sequence and effort estimates it produced live
in **`docs/ai/PROGRAMME_PLAN.md`**, which is living rather than dated — Group 3
item 14 is *tier the six dated audits*, and a seventh would grow the debt.

### What the instruments said

    backend tests        21,732 pass · 0 fail · 30 skipped
    frontend tests        2,645 pass · 0 fail  (136 files)
    CI gates                 14 of 14 pass
    gate evidence            29 gates · 29 proven able to fail · 0 unproven
    security analyzer         0 findings
    invariant predicates    339 across 34 modules
    spec capabilities       233 rows · 233 live · 0 staged
    decision records         12, all well formed
    stated figures           16 · 0 drifted
    npm advisories            0  (frontend and dashboard)
    python advisories         6  across 3 packages
    TODO/FIXME markers        4  in 708k lines

### Three advisories, assessed for reachability rather than listed

None has a fix version. A CVE in a package nothing calls is a different problem
from one in the money path, so each was traced to a caller.

**`ecdsa` 0.19.2 — Minerva timing attack (P1, reachable).** Leaks the P-256
nonce and from it the private key; key generation, signing and ECDH all
affected. Pulled in by `hdwallet`, which `payments/crypto/address_generator.py`,
`payments/crypto/bitcoin.py` and `api/billing.py` use for BIP44/BIP84
derivation. That is the money path. Narrow in practice — the attack needs timing
observed across many derivations — but with no upgrade to take it is a decision
rather than a patch: accept with a recorded reason, move derivation off the
request path, or replace `hdwallet`.

**`chromadb` 1.5.9 — four CVEs including pre-auth RCE (P2, NOT reachable).**
Every one targets the ChromaDB **HTTP server**: the `/api/v2/tenants/…`
endpoints, cross-tenant authorization, `SimpleRBACAuthorizationProvider`.
`research/vector_store.py` constructs `chromadb.PersistentClient(path=…)` — an
embedded client — and no compose, k8s or helm manifest starts a Chroma service.
It is genuinely used (`brain/llm_agent.py`, `ml/rl_agent.py`,
`ml/signal_scorer.py`), so removal is not free. The control that keeps this
assessment true rather than turning it into folklore is a gate asserting no
`HttpClient` and no server.

**`nltk` 3.10.3 — model-path sandbox bypass (P2).** Caller-controlled model
paths escape the enforced root. Reached through `textblob` in
`news/sentiment.py`, where the paths are TextBlob's own corpora rather than
caller-controlled, so the precondition does not hold.

### The caller screen's 38 rows are mostly the screen working

34 of the 38 show `prod=1` — one production reference, which is the definition
site. Only the four §4 roll-ups show `prod=0`, and those were already
established as false positives: `layer_state` is called inside the module that
defines it. The screen is behaving exactly as its own output says it does. What
it lacks is not a fix but a narrower question, and the package register supplies
one.

### The finding that shapes the plan

**Six of the eleven outstanding constitutional invariants close from one build.**
INV-01 (purpose), INV-02 (inputs and outputs), INV-03 (owner — the only NEW
one), INV-04 (KPIs), INV-07 (versioning and lifecycle) and INV-14 (retirement
dependencies) are all per-subsystem declarations, which is what Group 2 Chapter
1's **package ownership register** is. It also retires ADR 0011's compromise,
gives the 197 unowned documents an owner to follow, turns the caller screen's
"inspect this" into "ask this person", and is the input Group 2 item 18 (debt
budget) and item 22 (`data/` ÷ `data_layer/`) both need.

Nothing else outstanding has that shape, which is why it is Phase 1 and why the
plan is ordered by dependency rather than by size.

### The estimate

**≈ 25.5 sessions of build, plus 2.5 blocked on owner decisions — call it 28**,
where a session is one complete slice: failing test, implementation, evidence,
documentation, commit. Phases 3 to 5 touch the trading path and telemetry and
carry ±50%; the governance phases ±20%. The full breakdown, per phase and per
item, is in the programme plan.

---

## §E26 — The frontend page audit: three finished features, none of them connected (2026-09-09)

Measured across all 70 page components in `frontend/src/pages`, 87 routes and
every component, by running counters over the tree rather than reading it.

### What is sound, and should not be touched

87 routes, each wrapped in an `ErrorBoundary`. Four guard tiers compose
correctly — `AuthGuard` → `SubscriptionGate` (36 routes plan-gated by feature
key) → `AdminGuard` → `SuperAdminGuard`. 59 sidebar entries, **zero** pointing
at a route that does not exist. 62 of 70 pages issue real API calls. Settings
and SuperAdmin are decomposed into 45 focused `*Section` components.

Two of these were reported wrong on the first pass and corrected before
publication: a regex for `useQuery(` missed `useQuery<Type>({` and claimed 45
pages fetched nothing, and a route scan reported `/admin` unguarded when
`adminOnly()` wraps it in `AuthGuard` + `AdminGuard`. Rule 2 applies to audits
of the UI exactly as it applies to the engine.

### One root cause, three dead features

| Signal | Count |
|---|---:|
| Hardcoded hex literals in `frontend/src` | **8,021** (202 files) |
| …in `pages/` + `components/` alone | 7,340 (210 distinct) |
| `var(--…)` uses in `pages/` + `components/` | **58** |
| Inline `style={{…}}` blocks in `pages/` | 4,000 |
| `className=` in `pages/` | 1,010 |
| `dark:` variants in `pages/` + `components/` | **1** |
| `[data-theme="light"]` rules in any stylesheet | **0** |

Inline styles cannot participate in a cascade — they cannot respond to a
`[data-theme]` attribute, a media query, or a variable they do not name. From
that one fact:

* **The light/dark toggle is a dead control.** `ThemeContext.tsx` reads
  `prefers-color-scheme`, persists the choice and stamps `data-theme`;
  `AppearanceSection.tsx` offers light / dark / system; `tailwind.config.ts`
  declares `darkMode: ['class', '[data-theme="dark"]']`. Every part is correct.
  No stylesheet responds. Choosing Light saves a preference and changes nothing.
* **White-label branding cannot reach the product.** `WhitelabelAdmin.tsx`
  collects and sends a tenant's `primary_color`; the surface is 8,021 literals.
* **Five greys are doing "muted text"** — `#64748b` (673), `#94a3b8` (517),
  `#475569` (412) and more, the Tailwind slate ramp transcribed by hand.

**Closed this session:** `scripts/frontend_colour_ratchet.py` +
`docs/FRONTEND_COLOUR_DEBT.json`, wired into pre-commit and registered in
`GATE_EVIDENCE.toml` (29 gates, 29 proven). The count may now only fall. The
codemod that would actually revive the three features is **owner's call** — see
§A.

### Pages that cannot report their own failure

* **59 of 62 data-wired pages carry no staleness signal.**
  `hooks/useDataFreshness.ts` was built for audit F1-01 and adopted by exactly
  the three pages that audit named: Watchlist, RiskCalculator, TradeJournal.
  This is the same shape as the Sortino defect closed the same day — a correct
  fix connected only where the defect was found.
* **43 genuinely silent `catch` blocks across 22 pages.** (A first count of 90
  across 32 was wrong: the detector did not recognise `setAddressError` and
  `setErr` as surfacing.) Worst: `CryptoCheckout.tsx` payment-status poll —
  **closed this session**, it now degrades visibly after three consecutive
  failures while continuing to poll. That makes four pages of sixty-two.
* **Nine wired pages have no error path**; three have no loading affordance.
  Including `AutoHealDashboard` — a page about the platform noticing its own
  faults, which does not notice its own.

### Accessibility

138 `aria-*` and 51 `role=` across 392 buttons; **43 of 70 pages carry
neither**. Only seven real toggles exist in the whole page tree — most of what
reads as a switch is a styled button, so a screen reader gets no on/off state.
`prefers-reduced-motion` is respected in 10 places and focus styling appears
224 times; both should be kept.

### Remaining, in order

| # | Move | Buys | Size |
|---|---|---|---|
| 1 | Map the 210 hex values onto the 12 tokens; add a `[data-theme="light"]` block | Light mode works; white-label reaches the product; pages stop drifting. One change, three features revived. **Owner's call — see §A.** | 2–3 sessions |
| 2 | Spread `useDataFreshness` to the other 58 pages | No page claims data is live while its loads fail | 2 sessions |
| 3 | Error and loading states for the nine and the three | Start with `AutoHealDashboard` | 1 session |
| 4 | Real `role="switch"` toggles, then ARIA on the 43 bare pages | Perceivable state for keyboard and screen-reader users | 1–2 sessions |

### The rule this audit produces

Every finding here is one defect wearing different clothes: something built
correctly and then not connected to the surface it was built for. The theme
system. The white-label colour. `useDataFreshness`, at three sites of
sixty-two. The Sortino fix, at two call sites of eight.

**A fix is not finished until you have counted the other places with the same
shape.** That is one grep, and it would have caught every item above at the
time it was introduced rather than today.

Report: https://claude.ai/code/artifact/dffb0262-46cc-48bb-acf8-e9ce45077d9d

---

## §E27 — Money that did not conserve, and a backtest that could see tomorrow (2026-09-10)

Two money defects and one backtest defect, each reproduced by execution before
it was touched and re-run after.

### The sub-account transfer created and destroyed money

`api/accounts.py` computed each side of a movement with its own `round(x, 2)`:

    new_src_bal = round(src_bal - req.amount, 2)
    new_dst_bal = round(dst_bal + req.amount, 2)

Two independent roundings of two independent floats, so the two results were
under no obligation to sum to what went in. Measured:

    src=10.125 dst=20.125 amt=5.00  ->  30.250 becomes 30.240   a cent destroyed
    src=33.335 dst=66.665 amt=1.00  -> 100.000 becomes 100.010   a cent created

`round` is also ROUND_HALF_EVEN, the wrong tie-break for money. Sub-cent
balances are reachable: `initial_balance` is a plain float with no cent
constraint. This violates "No Hidden Capital" in `invariants/constitution.py`.

Fixed: `Decimal(str(...))` at the boundary, the amount quantised **once** with
ROUND_HALF_UP, and that same Decimal applied to both sides with no second
rounding — so conservation holds by construction. A reconciliation check now
**refuses the write** if the totals ever disagree; it is unreachable today and
exists to catch a future edit that reintroduces a `round()`. The response
reports what moved, not what was asked for.

### Two marketplaces split revenue the same way, and disagreed with each other

Counting the other places with the same shape — the rule §E26 produced — found
`social/marketplace.py:92` and `monetization/marketplace.py:1029`. Both split a
purchase with two independent roundings, and on the same sale they disagreed:

    price=12.575  ->  social 12.570 (-0.005)   monetization 12.580 (+0.005)

Both now route through one quantise-then-subtract rule, with a test pinning
that they agree — a creator's payout must not depend on which code path sold
the strategy.

**A correction worth recording:** the first version of that test asserted
`fee + payout == price` and failed against a *correct* implementation. A
sub-cent price cannot be charged, so the split has nothing to conserve against;
what must hold is that it sums to the **charged** amount. The test was wrong,
not the fix, and the reasoning sits in the file rather than the assertion being
quietly relaxed. This differs from the transfer deliberately: there the
sub-cent values are stored balances, which are real and must not be restated.

### The backtester handed every strategy the complete future

`backtesting/engine_config.py` — the canonical engine — built its price
snapshot correctly, masked `df["timestamp"] <= timestamp`, and then called:

    strategy.generate_signals(timestamp=timestamp, prices=current_prices, data=all_data)

`all_data` is every symbol's **complete** frame, future bars included. Thirty
lines above, the engine constructed the control designed to catch exactly this:

    # Initialise the BacktestBarGuard to catch any strategy that tries to
    # peek at future bars during the simulation loop.
    _bar_guard = BacktestBarGuard(_all_ts)
    logger.debug("BacktestBarGuard active: %d timestamps", len(_all_ts))

`_bar_guard` was never referenced again — F176, a control that exists, reads
correctly, logs that it is active, and never runs. Its failure path logged at
DEBUG, so a run that could not even build the guard looked identical to one
that could.

Measured over 120 bars, with harness liveness asserted first (the first two
harnesses were themselves broken — one never awaited the coroutine, one let the
engine load its own empty data, and each reported zero peeks while exercising
nothing):

    engine actually ran       : True        strategy was called: 120 times
    read a FUTURE bar         : 119 of 120
    first peek                : at 2024-01-01 00:00 it read close=1997.94
                                from a bar that had not happened
    guard raised              : NO

After: **0 of 120**, with the strategy still called 120 times.

Fixed structurally rather than by trusting strategies: the engine now slices
each symbol to `timestamp` and passes that view, so there is no future to read.
The slice is a `searchsorted` plus an `.iloc` view, which also replaced an
O(bars x rows) boolean mask per symbol per bar. The guard is kept as the second
line, `lookahead_protection` records which defence was in force (`"not_run"`
until a run sets it — an unmeasured value is absent, never best-case), and the
build failure now logs at WARNING.

`backtesting/engine.py` had the same dead-construction shape with
`FeatureTimestampGuard`, though its `no_lookahead_context` around the strategy
call is a real live defence. The guard is now reachable as
`engine.feature_guard` rather than a local that nothing read. `enhanced_engine.py`
passes one tick at a time and `multi_symbol_backtest.py` has no strategy
callback, so neither had the hole — checked rather than assumed.

**Why this ranks above the rest of the backlog:** look-ahead is the one backtest
defect that makes every other number meaningless, because a strategy that can
see the next bar can be arbitrarily profitable. Every backtest run before this
commit was capable of it, whether or not any strategy took the opportunity.

---

## §E28 — Three controls that could not fail, and a regression I shipped (2026-09-10)

### The ChromaDB CVE acceptance was prose

`.trivyignore.yaml` suppresses four chromadb CVEs — CVE-2026-45829, 45830,
45831, 45833, two of them **pre-authentication code injection** — on one stated
ground: this platform runs the embedded `PersistentClient` only, so there is no
listener and no pre-auth request path. The acceptance says so itself:

    This acceptance stops holding the moment anyone runs chroma as a server or
    points the client at a remote host.

Nothing was checking that. The suppression was true when written and one line
in an unrelated pull request away from being false, with the CVEs staying
suppressed either way.

**Closed:** `scripts/ci/gate_chroma_embedded_only.py`, a CI job, and the 27th
row in `GATE_EVIDENCE.toml`. Six injected violations are each refused —
`HttpClient`, `AsyncHttpClient`, a chroma compose service, `uvicorn
chromadb.app`, `Settings(chroma_server_host=…)`, `CHROMA_SERVER_HOST` in an env
file — and three negative cases prove it does not cry wolf. Python is parsed
with the AST rather than grepped, because a comment describing the ban is not a
violation and the repository has already had a checker that read prose as
source (F255). It fails closed: scanning zero files exits 1.

### Calibration was measuring whether a file existed

`ml/inference_engine.py` fed `ModelQualityGate` this:

    calibration_score = 1.0 if self._calibrator is not None else 0.0

A loaded-but-badly-fitted isotonic calibrator scored a perfect 1.0 and cleared
any `MIN_CALIBRATION`; a well-calibrated raw model scored 0.0 and failed every
threshold above zero. The engine's own docstring said as much and named the
fix.

**Closed:** `ml/calibration_metrics.py` computes Brier and Expected Calibration
Error on held-out predictions and reports `calibration_score = 1 - ECE`, the
[0, 1] form the gate already takes. `ml/train_advanced.py` measures it on the
OOS set it already has — `proba` against `y_oos` — and writes
`saved_models/calibration_report.json`; the engine reads it back. Proven end to
end by execution:

    no report on disk    -> None    (unmeasured; the gate fails closed)
    calibrated model     -> 1.0000  (ECE=0.0000)
    says 98%, right half -> 0.5200  (ECE=0.4800)

Under the old code both models scored 1.0. Every unmeasurable path returns
`None`, never a flattering default: too few samples, nothing finite after
dropping NaNs, or single-class held-out data. A training run that cannot
measure deletes the report rather than writing a placeholder.

### Two operator endpoints reported success for work that did not happen

Found by raising coverage on the two superadmin modules (#13) — `ml_ai.py` 55%
and `system_health.py` 30%, i.e. most of two operator-facing surfaces had never
been executed by a test. Writing the tests found three live defects:

* **`POST /system-health/jobs/{id}/run` returned 200 for a job that does not
  exist**, with the note "Scheduler not available — job queued". Nothing queued
  anything, and the note blamed a scheduler that was running fine. Now 404 for
  an unknown job, 503 when the scheduler is genuinely unreachable, and the
  message says plainly that nothing was scheduled.
* **`DELETE /system/api-keys/{id}` returned `{"ok": true}` for a key it never
  touched** — and also when Redis was absent entirely, because the whole block
  sat behind `if rc:` and fell through to the same success. "I revoked that
  key" is a security claim that has to be true. Now 404 when no key matched,
  503 when the store is unreachable, and the count of keys actually revoked is
  returned.
* **`GET /ml/rl/status` leaked the absolute server path** —
  `/home/<user>/HOPEFX-AI-TRADING/ml/saved_models/rl` — naming the deployment
  account, install root and directory layout in an API response. Now
  repo-relative.

Coverage after: `ml_ai.py` 55% → 62%, `system_health.py` 30% → 70%. Both remain
recorded debt with better numbers rather than being declared done.

### A regression I shipped, found by the baseline run

Commit `a4eec54` (the F120 Sortino completion) changed
`risk.advanced_analytics.calculate_sortino_ratio` to return a finite 0.0
instead of `inf`, and updated the test asserting the old behaviour in
`tests/unit/test_advanced_risk_analytics.py`. A **second** file,
`tests/unit/test_risk_advanced_analytics_cov.py`, asserted the same thing and
was missed, so the branch shipped red and stayed red until a clean-worktree
baseline run surfaced it.

That is the same shape as the defect the commit was fixing — a change applied
at one of two sites — and it is recorded here rather than quietly corrected,
because the rule §E26 produced ("count the other places with the same shape")
evidently applies to tests as well as to code. Fixed, and a repository-wide
grep confirms no other test asserts the old `inf`.

**Method note.** The working tree showed six failures and the clean HEAD
baseline showed one, with the two sets disjoint and every one of the six
passing in isolation. Diffing failure *sets* rather than counts is what
separated one real regression from five order-dependent flakes; comparing the
counts alone would have suggested the changes broke five things.

---

## §E29 — Feed failover: what existed, and the half that did not (2026-09-10)

Asked for by the owner as "AI supplies the feed when the feed is down". The
answer has a hard no in it and a real feature next to it, and both are recorded
here because the no is the more important half.

### The refusal, stated once

**An LLM must never generate a market price.** A generated XAUUSD quote is
indistinguishable from a real one — right magnitude, right volatility, right
decimals — and it flows into position sizing, VaR, stop placement and an order.
Every defect this programme has removed is a value nothing measured presented as
though something had; a fabricated price is that defect with the largest
possible blast radius. No configuration flag, no "emergency only" mode.

Where AI genuinely helps at the feed layer: reasoning *over* real data —
instrument specs, symbol mapping, explaining why a feed degraded, news and
geopolitical context. Not manufacturing the number.

### What was already built (verified, not assumed)

* `data_layer/feeds/gold/manager.py` — six providers (GoldAPI, Metals.dev,
  Yahoo, Metals-API, MetalpriceAPI, CommodityPriceAPI) in priority order, a
  circuit breaker per feed, confidence-weighted cross-source consensus, Redis
  pub/sub, Prometheus.
* `MarketDataOrchestrator.get_latest_tick()` — refuses a cached tick with no
  `source` rather than labelling it with a fabricated origin; discards one that
  is stale **or** future-dated; returns `None` rather than a price it cannot
  stand behind; no longer answers a non-gold symbol with the gold price.
* Production constructs it: `MarketDataOrchestrator.start()`, line 476.

**A correction worth recording:** the first trace said `GoldFeedManager` was
constructed only by a validation script and was therefore dead. That was a
truncated grep — `head -10` cut the orchestrator's two matches. The chain is
wired. Same failure mode as the frontend audit's first pass, and caught the
same way: by checking the measurement before reporting it.

### What did not exist, and now does

When every source is down, work still arrives — a signal fires, an operator
clicks, a scheduled rebalance comes due — and the only answers were `None` and a
log line. An outage left no trace beyond an absence of trades, which looks
exactly like a quiet market.

`data_layer/outage.py`:

* **`FeedHealth`** — healthy / degraded / outage, the age of the last tick, how
  many providers answer. Two inputs, neither sufficient alone: a fresh tick with
  every provider dead is an **outage that has not surfaced yet**, and calling it
  healthy is how an operator learns about an outage from a customer. `age_s` is
  `None` when no tick has ever arrived, never `0.0` — a zero age reads as
  perfectly fresh, which is the worst possible reading of "we have never had a
  price".
* **`DeferredWorkQueue`** — bounded, so an outage cannot become an
  out-of-memory incident. Overflow drops the **oldest** (during a long outage
  the newest intents are formed against the most recent known price) and counts
  every drop.
* **`FeedOutageSupervisor`** — returns held work **only on the recovery edge**,
  never on every healthy observation, which would replay it forever.

**The rule that shapes all of it: a deferred trade action is never replayed
automatically.** The market moved. An intent formed against a pre-outage price
is not valid after it — acting on it is serving a stale tick one layer up, with
an order at the end. The module has no broker, no OMS and no execute path;
`drain()` returns data carrying each item's age and the price context believed
at deferral, and the caller re-decides. A test asserts the surface stays free of
`execute`/`submit`/`send`/`on_drain`, because that callback is the tempting
future edit that turns a forty-minute-old signal into a live order.

An item past `FEED_REPLAY_MAX_AGE_S` (default 300s) comes back **marked
expired, not dropped** — an expired intent is evidence a signal fired and
nothing happened.

Wired into `MarketDataOrchestrator._observe_feed_health()`, called on **both**
the success and the empty path of `get_latest_tick` — a supervisor that only
hears about successes cannot notice an outage. Exposed at
`GET /api/data-layer/feed-status` (JWT), which is the source of truth the 59 of
62 frontend pages carrying no staleness signal (§E26) should read.

Proven by execution on the real orchestrator method, not only in tests:

    before any observation : outage  | age_s: None
    after an empty read    : outage  | outage_since recorded
    deferred while down    : 2
    after recovery         : healthy | pending: 0, handed back for re-decision
    queue surface          : as_dict, defer, drain, dropped, pending
                             — no execute, no submit, no broker

### Still open at this layer

* Failover covers **gold only**. A non-gold symbol gets `None` rather than a
  chain — correct (better than a wrong price) but not covered.
* Nothing calls `supervisor.defer()` yet. The queue is wired and observed;
  the decision engine and scheduler have not been taught to use it, so today it
  records outages without holding work. That is the next step and is named
  rather than implied.
* The frontend does not read `/feed-status` yet — §E26 item 2.

---

## §E30 — The emergency halt reported success for a halt that did not happen (2026-09-10)

`POST /superadmin/nuclear/halt` is the control of last resort — the thing a
superadmin reaches for when the platform must stop trading now. It ended in an
unconditional:

    return {"ok": True, "kill_switch_active": True, "reason": reason}

**Four separate paths reached that line having halted nothing:**

| Path | What happened | Why it was invisible |
|---|---|---|
| No kill switch resolved | `if ks is not None:` skipped the entire activation block | Response still said `kill_switch_active: True` |
| Activation raised | `except` logged at ERROR, then fell through | The ERROR was correct; the response was not |
| Cross-pod propagation failed | `except Exception: pass` on the Redis write every other pod reads | **The local halt worked, so nothing looked wrong** — the rest of the fleet kept trading |
| No Redis client at all | `if rc:` skipped it | Silent |

The third is the dangerous one. An operator hits emergency stop during an
incident, this pod halts, Redis is down, every other pod keeps filling orders,
and the response is a green tick.

On top of that the halt banner was fired as a bare
`asyncio.create_task(...)` whose result nobody held. The event loop keeps only a
**weak** reference to a task, so CPython may collect it before it sends — and
the failure path logged at `logger.debug`, which is off in production. A halt
nobody was told about left no trace. That is `hopefx-dead-controls` sub-shape 4
verbatim, and the same family as F248.

### What it does now

Each leg reports its own outcome and the response carries them:

    everything works            HTTP 200  ok=True   legs={local: activated, propagation: written, broadcast: sent}
    redis down (fleet trading)  HTTP 200  ok=False  legs={local: activated, propagation: failed: ConnectionError, ...}
                                  ! The halt did NOT propagate to other pods. Halt them
                                    directly before assuming trading has stopped.
    switch wedged               HTTP 200  ok=False  legs={local: failed: RuntimeError, propagation: written, ...}
    no switch, redis ok         HTTP 200  ok=False  legs={local: no_switch, propagation: written, ...}
    NOTHING halted              HTTP 500  "EMERGENCY HALT FAILED — nothing was halted.
                                           Stop trading manually."

`ok` is true only when both the local switch and the cross-pod propagation
succeeded. `kill_switch_active` is true when *anything* was halted, so a partial
halt is neither a lie nor a false alarm. Total failure is a **500** — a 200
there would be the worst possible answer.

The broadcast is now awaited with a 2s timeout through
`_broadcast_or_report()`, which holds a strong reference in `_BACKGROUND_TASKS`,
returns a delivery status, and logs failures at ERROR naming what nobody was
told. `nuclear_resume` is held to the identical standard: a resume that clears
this pod but not Redis leaves the fleet halted while the operator believes
trading is back, and they find out from a fill that never arrives.

### Method note

Twelve tests, nine red before the fix (the three that passed were the
happy-path ones — the machinery worked, the *reporting* was the defect). Before
committing, the neighbouring suite `test_superadmin_nuclear_controls_resolution.py`
was run deliberately to check whether it encoded the old behaviour. It did not.

That check happened **first** this time. Three earlier commits in this
programme changed a behaviour and were caught later by a full run or a baseline
because a second test file asserted the old contract — the Sortino `inf` (two
files), the calibration presence signal (three tests), and the generated API
doc. Looking before changing costs one command; finding out afterwards costs a
red branch.

---

## §E31 — The AI was dead without an API key (2026-09-10)

Owner requirement: *"our local model should be our primary model, so our AI can
be active if an API token is not available — it should not be waiting for a key
before it activates. If a key is dictated it can switch."*

Measured first, with every provider credential unset:

    credentialed providers : []
    embedding    chain=['openai', 'google']                 answerable legs=0
    fast         chain=['anthropic', 'anthropic', 'google'] answerable legs=0
    reasoning    chain=['anthropic', 'openai', 'google']    answerable legs=0
    vision       chain=['google', 'anthropic']              answerable legs=0

**All four roles resolved to chains that could not answer.** `ai/local_model.py`
— which the owner had already required to start with the application — was
running on the box and was in no chain, because the policy read *"local
inference is optional and never a primary"*: it joined only when a superadmin
set `llm_local_enabled`, and then last.

### What changed in `ai/gateway/chain.py`

Local now joins four ways, in descending order of deliberateness:

| Route | Effect |
|---|---|
| `llm_local_only` | The exclusive privacy mode. **Unchanged** — a ceiling, not a preference |
| `llm_local_first` | Local leads; hosted legs remain behind it as fallback |
| `llm_local_enabled` | Appended last (the pre-existing behaviour) |
| *automatic* | Leads when **no leg in that role's chain** is credentialed |

Plus: a ready local runtime is now reachable as a last resort in every chain,
not only when `llm_local_enabled` was set. A deployment that never touched that
setting used to lose the AI entirely the moment its providers went down.

Automatic promotion is a **floor, not a preference**. A credentialed hosted
provider keeps the lead, so a deployment paying for a frontier model is never
quietly downgraded because ollama happens to be up — that is the owner's "if a
key is dictated it can switch". The check is per-role rather than global, which
is more precise than it first appears: with only an `ANTHROPIC_API_KEY`, the
`embedding` chain (`openai`, `google`) genuinely cannot answer, so local
correctly leads *that* chain while `reasoning` still leads with Anthropic.

### The trap this could easily have become

`providers.local_inference_enabled()` returns `is_credentialed("ollama")`, and
"credentialed" for ollama means `OLLAMA_BASE_URL` is a **non-empty string**.
Promoting on that evidence would have replaced a chain that cannot answer with
one that cannot answer *and claims it can* — strictly worse, because the caller
stops looking for the real problem. `ai/local_model.py::is_ready()` probes, and
`chain._local_is_ready()` calls it; a probe that raises is not-ready, and says
so. Two tests pin it, one of them by patching `local_inference_enabled` to True
while the probe says False and asserting local is **not** promoted.

An automatic promotion logs at WARNING naming the role and saying capability is
materially lower — a local answer must never quietly pass for a frontier one.

### Method note

The first version of the probe test read `inspect.getsource(_local_is_ready)`
and asserted the string `local_inference_enabled` was absent. It failed —
because that function's docstring *explains* why it does not use it. A checker
that reads prose is not reading code; this repository has had that defect
before (F255), and it is no better in a test than in an analyzer. Rewritten to
assert behaviour.

Before committing, every test touching `resolve_chain` / `LOCAL_PROVIDER` /
`llm_local` was run to check whether any encoded the old "never a primary"
policy. None did — 106 pass.

---

## §E32 — What the operator has actually looked at (2026-09-10)

Owner requirement: everything on the AI Core page should run in the background
and surface itself — *"pop it up or ask if operator want to check, or if it been
a while you have check it, or operator haven't request for it at all."*

Three of the four pieces already existed, and they are good:

| Piece | Where |
|---|---|
| Background observation | `ai/awareness/watchers.py` — departments notice on their own and raise proposals. Structurally unable to act: no tool-bus import, and `Observation` has no field that could express one |
| When the AI may interrupt | `ai/notify/policy.py` — quiet hours, sleep mode, dedup, rate limits, with a hard floor: a CRITICAL notification is never suppressed, enforced by `decide()` returning before any suppression path exists |
| Whether anyone is looking | `frontend/src/hub/attention.ts` — tab visibility, focus, idle time, no camera; "unknown is not away" |
| **What has been looked at** | **Did not exist.** A grep for `last_reviewed` / `unseen` / `acknowledged_at` across `ai/`, `api/` and `frontend/src` returned one hit, and it was a comment |

So *"it has been a while since you checked this"* was a sentence the platform
could not say.

### `ai/awareness/reviewed.py`

Eight declared surfaces — drift, calibration, risk limits, feed status, the AI
proposal queue, the audit trail, the decision ledger, open positions — each with
a label, a stated cadence, and a one-line reason it matters. **Declared, not
discovered:** a registry that guessed from routes would raise "you have not
looked at /api/health lately", and noise is how a notification channel dies.

### The honesty problem the design turns on

"You have never reviewed this" is a claim about a person, and it is only as good
as the memory behind it. A store that lost its contents on restart would report
every surface as never-reviewed, and the AI would greet an operator who reads
the drift report daily by telling them they have never opened it. Say that once
and they learn to ignore the mechanism entirely.

So the store declares whether it survives a restart, and the state carries it:

    durable store, no record   -> "never"    (a fact about the operator)
    volatile store, no record  -> "unknown"  (a fact about the store)

`due_for_review()` returns **nothing at all** from a volatile store, so the
first thing an operator sees after a deploy is not a list of things they are
wrongly told they have neglected. `get_tracker()` falls back to an explicitly
non-durable `InMemoryReviewStore` rather than to a volatile store that claims
durability.

That is Rule 2 — an unmeasured value is absent, never best-case — pointed at the
person using the platform rather than at a price.

### Cadence is declared, never assumed

A surface with no stated cadence cannot be overdue and is not fresh either; it
is `no_cadence`. `open_positions` is deliberately in that state: being "overdue"
on it would mean the operator had stopped trading. Inventing a default would
manufacture urgency about something nobody said was urgent — the same defect as
inventing a data-quality score.

### It reports; it does not act

Same rule as `Observation`. The module has no notifier, no route opener and no
scheduler — a tracker that could act would be a scheduler with an opinion about
your attention. It states a fact and `ai/notify/policy.py` decides whether that
fact is worth interrupting anyone for. A test asserts the surface stays free of
`execute`/`send`/`notify`/`open`/`act`/`trigger`/`run`.

Exposed as a read on the AI Core surface and a write on the notifications one:

    GET  /api/ai-core/review-status
    POST /api/ai-notifications/reviewed/{surface_id}

The split is deliberate and was enforced by a test rather than remembered. The
first version put both on `api/ai_core.py`, and
`tests/unit/test_ai_core_surface.py` refused it: *"the AI Core read surface
exposes ['POST']"*. That router is **read-only by construction** — a property
worth keeping, so the write moved to the router that already accepts
acknowledgements rather than the contract being relaxed to fit. The same test
also required the new GET to carry a capability row in `ai/policy/roles.py`.

An unregistered id is a 404, not a silent no-op: a typo that returns 200 makes
the surface it was meant for look permanently neglected.

### Still open

Nothing calls `mark_reviewed()` yet — the frontend has to report when a panel is
actually opened, and no page does that today. The tracker and its endpoints are
wired and exercised; the reporting half is the next step, and is named here
rather than implied.

---

## §E33 — A support desk with a floor, and the test that could not prove it (2026-09-10)

The owner asked for a support surface where the AI engages, issues reach a
human, the operator can watch in real time and take over, and *"different AI in
different aspects of any question"*.

**Half of that already existed and nothing used it.** `ai/departments/` holds
eleven specialists — research, markets_execution, risk_compliance, data_ops,
news_intelligence, system_ops, platform_engineering, memory_ops,
notification_ops, vision_ops, voice_interface — each delegating to code that
already exists and returning `available: False` rather than a number it did not
get. What was missing was the customer-facing flow around them: nothing routed a
question to a specialist, and nothing decided when a person had to be involved.

### What was built

`support/triage.py`. One decision and only that decision: **who** should handle
a question, and **whether a human must**. It cannot answer and it cannot act —
no broker, no OMS, no mailer, no refund path — and a test asserts the surface
stays free of `send`/`reply`/`execute`/`place_order`/`close_position`/`refund`,
because a triage module that could also reply is one edit away from replying to
something it should have escalated.

The safety property is a **floor**, not a threshold:

> Some categories always reach a human, whatever the AI's confidence.

Financial advice. Anything touching an account, a balance or a withdrawal. A
complaint or legal notice. A suspected security incident. Not "escalate when
unsure" — *always*, because "unsure" cannot catch the case that matters: an AI
that is wrong **and** certain. Two of those are not obviously support
questions and are worth naming: *"should I buy gold?"* is regulated advice this
platform is not licensed to give, and *"someone logged into my account"* needs a
person within minutes — an AI that answers it helpfully has delayed the response.

Enforced the way `ai/notify/policy.py` enforces its CRITICAL floor: structurally.
The escalation decision returns before any auto-answer path is reachable,
`TriageResult` carries no field that could turn it off, and an escalated result
carries `suggested_reply=None` so no UI can send a draft for a ticket meant for
a person. Routing is declared in `DEPARTMENT_ROUTES` and a test asserts every
target exists in `ai.departments.DEPARTMENTS` — a route to a department nobody
built is a dead end discovered at 3am by a customer. A question matching nothing
goes to a human with `department=None`, not to a plausible default: guessing
"probably research" is Rule 2 at the support desk.

### The finding: twenty tests that could not fail

The first version of the floor suite asserted `needs_human is True` and nothing
more. Running the counterfactual — turning the floor into a threshold, `if hit
is not None and confidence < MIN_CONFIDENCE` — left **36 of 37 tests green**.

They passed for the wrong reason. With the floor disabled, "withdraw my balance"
matches no *category* either, falls through to the unroutable branch, and
escalates from there. The suite was measuring "these phrases do not route
anywhere", not "the floor caught them".

That is the F176 shape — a measurement that cannot fail — and it is no better in
a test file than it was in `invariant_coverage.py`. Two changes fixed it:

* each case now names the **category** the floor must attribute it to, so an
  escalation arriving from any other branch fails; and
* a `MIXED` set holds questions that *also* match a routable category — *"should
  I close my position, my drawdown is nearly at the limit"*, *"my order was
  rejected and I want a refund"*, *"the price feed was frozen so I am reporting
  you to the regulator"*. Without the floor those reach a department and get
  answered by an AI.

Same counterfactual against the strengthened suite: **36 failed, 16 passed**.

### A second finding, from a test reaching for a constant

`support/__init__.py` re-exported the `triage` *function* under the same name as
the `triage` *module*, so `import support.triage as mod` returned the function —
`import a.b as c` resolves `b` as an attribute of `a` before falling back to
`sys.modules`. The test hit `AttributeError: 'function' object has no attribute
'DEPARTMENT_ROUTES'`, which reads like a typo rather than like a package that
overwrote its own name. The package no longer re-exports the callable; a test
asserts `support.triage` is a module.

`support/` is at **100% statement and branch coverage**, 57 tests.

### Still open — the desk is one decision, not a desk

Named rather than implied:

* **No ticket model.** Nothing persists a conversation, its state, or its
  history. Triage returns a decision and forgets it.
* **No operator queue.** Nothing collects escalated tickets for a person to
  work, and nothing assigns or claims them.
* **No real-time handoff.** The owner asked to watch in real time and take over;
  there is no channel, no presence, and no takeover.
* **No UI.** Per CLAUDE.md, an operator surface of this size needs a
  `flow-prototype` approval pass before production implementation — that is the
  owner's call to make, not one to take unilaterally.
* **Nothing calls `triage()` yet.** It is reachable and tested; no endpoint or
  agent invokes it. The same gap as `mark_reviewed()` in §E32 and
  `supervisor.defer()` in §E29 — a built control with no caller is exactly the
  defect class this programme keeps removing, and it is recorded here so it is
  not mistaken for finished work.

---

## §E34 — The ticket the AI cannot close (2026-09-10)

§E33 built the decision and named what was missing: no ticket model, no operator
queue, no handoff. This is the store, and it exists mostly to make two refusals
possible.

**An escalated ticket cannot be resolved by the AI.** The floor in triage is
worth nothing if the thing it escalated to can be marked resolved a moment later
by the same AI it escalated away from. `resolve(actor=Actor.AI)` on a ticket
whose `needs_human` is set returns `Outcome(allowed=False, reason=...)` — the
shape `invariants/enforcement.py` uses, where the caller reads whether it was
allowed. A transition that logs and proceeds is the F176 shape.

**Two operators cannot claim the same ticket.** The second claim is refused and
*names the holder*: "someone else has it" is not something the second operator
can act on at 3am. Re-claiming your own ticket is not an error, because a
refreshed page must not read as a conflict.

Around those: `needs_human` is sticky (a customer who mentions a withdrawal and
then changes the subject has not made the ticket safe to auto-close), the queue
is oldest-first (newest-first starves whoever has waited longest), a customer
reply reopens a resolved ticket rather than requiring a new one, and only the
holder may release.

`first_response_at` is nullable with **no default**, in the model and in the
migration. NULL means nothing has responded. A column stamped at creation would
report a desk answering every ticket instantly — Rule 2, at the support desk.

### The finding: every conversation escalated on its second turn

`test_reopening_a_resolved_ticket_is_allowed` failed with `awaiting_operator`
where it expected `open`. The follow-up path was re-running the whole of
`triage` on *"that did not work"*: that matches no category, hits the
unroutable-goes-to-a-human branch, and escalates.

So *every* conversation would have escalated on its second turn, and the
operator queue would have filled with people saying "thanks" — a queue nobody
can work is a queue nobody reads, and the real escalations sink in it.

The distinction the code was missing: **routing is decided once per thread; the
floor applies to every message.** The unroutable rule exists to stop *routing a
guess*, and on a follow-up there is nothing to route. `support.triage.check_floor`
is now the floor alone, `triage()` calls it, and `add_message` calls only it. Nine
tests pin both halves — five conversational replies that must not escalate, four
that must.

That defect was not visible by reading. It surfaced because a test written for
an unrelated property (reopening) ran the path.

`support/` is at **100% statement and branch coverage on `tickets.py`**, 99.3%
across the package, 98 tests. `alembic upgrade head` was run against a real
SQLite file and the resulting columns and indexes inspected, rather than
inferred from the migration source.

### Still open

* **No real-time handoff.** The owner asked to watch the queue live and take
  over; there is no channel, no presence and no push. `operator_queue()` is a
  poll.
* **No API surface.** Nothing HTTP-facing reaches `TicketStore` yet, so no
  customer can open a ticket and no operator can see one.
* **The AI does not answer yet.** `triage` names a department; nothing asks that
  department for an answer and writes it back as a message.
* **No UI**, and per CLAUDE.md an operator surface of this size needs a
  `flow-prototype` approval pass before production implementation — the owner's
  call, not one to take unilaterally.

---

## §E35 — The support AI answers from facts, or says it cannot (2026-09-10)

§E33 decided who should answer; §E34 recorded the conversation and refused what
the AI must not do to it. Neither produced a reply. `support/answering.py` does,
and almost all of its design is what it refuses.

**It never answers an escalated ticket, and never calls the model for one.** The
check runs before anything is spent. A drafted reply on an escalated ticket is a
suggestion wearing a refusal's clothes — it ends up in front of an operator who
is about to paste it.

**No reachable model means no answer.** Not a canned fallback, not "we are
looking into it". A deployment with no gateway leg, a budget refusal, a timeout
and a dead vendor all produce `available=False` and a ticket for a person. A
desk that invents a reply while the AI is down is worse than one that admits it,
because the customer cannot tell the difference — the same argument that stops
`ai/gateway/chain.py` promoting a local runtime it has not probed. An empty
completion is treated the same way: a blank reply is a failure that looks like a
success.

**A fact the department could not measure is stated as `not measured`, never
dropped.** Dropping it hands the model a gap to fill. `ai/departments/` already
returns `available: False` rather than a number it did not get; this carries the
same rule into the prompt.

"Different AI in different aspects" is `DEPARTMENT_BRIEFS`: eight briefs, one per
routed department, each with its own scope and its own limits — Markets &
Execution never states the status of an order not in the facts; Data Ops never
quotes a price, because a price in a support reply is stale the moment it is
written; Risk & Compliance explains a limit rather than how to get around it;
Account & Platform never asks for a password, a one-time code or an API key. A
test asserts no two briefs are identical, because one prompt with a name
substituted into it is not a team of specialists.

### The finding: sixteen tests, and the main rule unproven

Deleting the escalation branch entirely left **all sixteen tests green**.

An escalated `TriageResult` carries `department=None`, so execution fell through
into the *unroutable* branch and returned a refusal that satisfied every
assertion — for a completely different reason. The suite could not tell which
control had fired. That is the third time in this programme a counterfactual has
caught a test proving the wrong thing (§E33's floor, and the `_local_is_ready`
source-reading test before it), and the second time in two days that the
fallthrough was doing the work.

Triage returning a department alongside an escalation is a plausible change — an
operator wants to know whose queue it belongs in — and it would have converted
that accident into a model call on a ticket the floor had already escalated. The
suite now pins the escalation branch with a decision the fallthrough cannot
rescue, and asserts the refusal carries triage's *own* reason rather than merely
a non-empty string. Same counterfactual now fails two tests.

### A guard that today's code cannot open, kept and proven

Coverage showed the "routable but unowned" branch never executing: `triage` sets
`needs_human` whenever it has no department, so it is unreachable through the
real function. That is the guard-that-can-never-open shape from
`hopefx-dead-controls` — but deleting it is the wrong fix. It is the last thing
between a future triage change and `_build_prompt(department=None)`, which
composes the fallback brief and lets a generalist answer a question nobody owns.
It stays, and a test now puts the system in the state that opens it.

`support/answering.py` is at **100% statement and branch coverage**, 22 tests;
`support/` is at 134 tests overall.

### Still open

* **No API surface.** Nothing HTTP-facing reaches any of this. A customer cannot
  open a ticket and an operator cannot see one.
* **No real-time handoff**, still. `operator_queue()` is a poll.
* **No UI**, and it needs a `flow-prototype` approval pass first.

---

## §E36 — The support desk reaches HTTP, and an id is not authorisation (2026-09-10)

§E33–E35 built a desk nothing could reach: no customer could open a ticket, no
operator could see one. `api/support.py` is that surface, and the properties
worth having are about who may read what.

The finding it is written against is **S6-02's shape**. `api/advanced_orders.py`
declared a router with no dependencies and three routes with no ownership check,
so `GET /{order_id}` enumerated every user's stop levels. A support thread is
the same class of data — it holds what a customer said about their account,
their money and their losses.

* **Ownership is checked on every customer read and write.** The ticket id is 32
  random hex characters, which makes guessing hard and authorises nothing. A
  hard-to-guess identifier is not a permission model.
* **A ticket that exists but belongs to someone else answers 404, not 403.** A
  403 confirms the id is real, which is a free oracle for an enumerator.
* **Two routers, two roles.** `/api/support/tickets/*` gates at `starter` (a
  starter-tier customer with a billing problem is exactly who needs a ticket);
  `/api/support/queue/*` gates at `admin`. Router-level dependencies, so a route
  added later inherits the gate rather than needing to remember it (S6-01).
* **Bodies are bounded** at 8,000 characters. Unbounded text is a storage
  problem and a prompt-cost problem at once, and the second one is billed.

Auth is asserted by **calling every route anonymously**, not by reading the
router's structure. The first version checked `router.dependencies` and could
not: Starlette records each inclusion as an opaque `_IncludedRouter` with no
such attribute — the trap `core/router_registry.py` documents at length. The
sweep enumerates routes via `iter_api_routes`, asserts the list is non-empty so
it cannot pass vacuously, and calls each one.

### Two new store methods, and why `escalate` exists

`TicketStore.tickets_for()` filters **in the query**: a read that fetches every
ticket and discards other people's is one forgotten filter away from returning
them. Newest-first, the opposite of the operator queue, and deliberately — a
customer looks for what they raised last, an operator for who has waited longest.

`TicketStore.escalate()` is how `answering`'s refusal becomes somebody's queue
item. The floor is not the only way a ticket needs a human: an AI that could not
answer leaves a ticket nobody is working, and **a ticket nobody is working looks
identical to one that was answered**. It is sticky like the floor, never
overwrites the floor's own reason, and never takes a ticket off an operator
already on it.

### The test that was testing the wrong path

`test_a_reply_lands_and_reports_the_new_state` failed asserting
`needs_human is False`. The cause was the honest path working: the test
environment has no reachable gateway, so `answer_question` refused, the router
escalated, and the ticket correctly reached a person. Two tests written without
an available AI were quietly testing the escalation path while claiming to test
the AI one. An `ai_available` fixture now makes that explicit.

Two guards today's code cannot open are kept and **proven able to fire** rather
than deleted: the 409 on a customer reply (without it a future store refusal
would be discarded and the endpoint would report success for a message it did
not save — the "success reported for work that did not happen" shape) and
`answering`'s unowned-department branch from §E35.

The router is registered in `core/router_registry.py`, and the ten mounted
routes were listed by running the app rather than read off the source.

`api/support.py` is at **98.3% coverage** (the two misses are the dependency
pass-throughs), 30 tests; the support suites are 197 tests including the
auth-coverage gates.

### Still open

* **No real-time handoff.** `GET /api/support/queue` is a poll. The owner asked
  to watch it live; a WebSocket on `api/ws_live.py` is the next step.
* **No UI**, and per CLAUDE.md an operator console needs a `flow-prototype`
  approval pass before production implementation — the owner's call.
* **`answer_question` is called with no facts.** The department briefs are
  written to answer from a FACTS block, and nothing yet gathers one from the
  department's own read-only actions. Every reply today is answered from the
  brief alone, which is why the briefs are the strict half of the design.

---

## §E37 — The coverage gate blamed the test for a config exclusion (2026-09-10)

Found by trying to commit §E36. Registering the support router meant touching
`core/router_registry.py`, and the per-module coverage gate blocked:

    core/router_registry.py: coverage could not be measured
    (test: tests/unit/test_core_router_registry.py) —
    the test may not import the module, or may fail to collect

That diagnosis was wrong in a way that costs a reader real time. The test
imports the module on line 19 and nine tests exercised `register_routers`
directly. The actual cause was `.coveragerc`, which listed
`core/router_registry.py` under `[run] omit` — so coverage was *configured* not
to measure it, reported `no-data-collected`, and the gate turned that into an
accusation about the test.

Verified pre-existing: the same failure reproduces on the clean tree with the
change stashed. Every commit touching that file was already blocked, and the
message pointed at the wrong file to fix.

### Three things were wrong, and all three are fixed

**The exclusion's stated reason was false.** `.coveragerc` justified it as
"require full app context; covered by integration/e2e tests, not unit tests" —
written while `tests/unit/test_core_router_registry.py` already existed and
passed. The entry is gone, and the config now records what happened instead of
the claim that was not true.

**25% of the module had never been exercised.** Measured with the exclusion
lifted: 74.7%. The gap was the sixty-odd
`try: import … except Exception: logger.warning(…)` fallbacks around the
optional routers — the branches that decide what happens when part of the API
cannot load. That matters for S6-01's reason: a router that disappears quietly
is indistinguishable from one that was never meant to exist. The app comes up,
the endpoint 404s, and nothing says why. Three tests now make thirty-one
packages unimportable and assert the app still serves, that the failures are
logged, and that the log names the router **and** the reason. 87%.

Building that harness surfaced its own trap: the failing importer matched
`from .security import router` inside `api/superadmin/__init__.py`, because a
relative import arrives at `__import__` as `name="security", level=1`. It broke
an unrelated package and the `ImportError` escaped `register_routers` entirely,
so the test failed for a reason unconnected to the branch under test. It now
matches `level == 0` only. The harness also snapshots and restores
`sys.modules`, because evicting packages to defeat the import cache otherwise
hands every later test in the session a second copy of each one.

**The gate now names a config exclusion.** `_coveragerc_omits()` reads the omit
list, and an excluded module reports `EXCLUDED by .coveragerc [run] omit` with
the fix — remove the line and add the tests it then needs — instead of blaming
the test. It still **blocks**: an exclusion is not permission, or the omit list
becomes the way to switch the gate off. A missing config is not an exclusion,
so it fails toward measuring. Eleven tests, including that a `[report]` pattern
is not an omit of a file.

This is the same rule as F176: a report must distinguish what it measured from
what it was told. The gate was told nothing and reported a conclusion about the
test.

---

## §A6 — DECIDED 2026-09-10: record `api/ws_live.py`, land the WebSocket fix

**Owner chose option 1**, then authorised option 2. **CLOSED 2026-09-10.**
Recorded in `docs/COVERAGE_UNMEASURABLE.txt` with its measured 34% -> 35% and
the four conditions ADR 0017 now requires; the patch was applied, the
parked-work directory it lived in is gone, and the live operator queue was
unblocked (§E39). Option 2 — raising the module past the floor and deleting the
entry — was then done: `api/ws_live.py` is at **81%** and the entry is gone.
See §E45. The debt this section exists to justify no longer exists.

The original decision text follows, kept because the reasoning is the reason the
entry is defensible.

---

### The situation

The support desk needs a live operator queue — the owner asked to watch it in
real time and take over. That means broadcasting on a channel **only operators
may join**, and `LiveConnectionManager.subscribe()` currently adds whatever
channel name it is handed with no check of who is asking.
`_PRIVATE_CHANNELS` does not help: it keeps private data out of the
"empty subscription means every channel" firehose (S8-02) and says nothing
about a client that *does* subscribe. Any authenticated account could have
subscribed to `support_queue` and read other customers' subject lines and
escalation reasons.

The fix is written and passing — `docs/pending/ws-privileged-channels.patch`,
11 new tests, and the 629 existing WebSocket tests still green. It adds a
per-channel role requirement, records the token's `role` claim on the
connection, refuses rather than silently dropping, and drops the role on
disconnect so a reused connection id cannot inherit an operator's.

### Why it cannot be committed

`api/ws_live.py` measures **34%** against the per-module coverage gate's 80%
floor and is **not** recorded in `docs/COVERAGE_UNMEASURABLE.txt`. The gate
blocks every commit that touches the file. Measured on the clean tree with the
change stashed — pre-existing, and the patch raises it to 35%.

The module is 2,425 lines, and the check has to live where `subscribe` lives.
There is no placement that avoids the file.

### The options

1. **Record `api/ws_live.py` in the debt list.** Its header says the list may
   only shrink, and `tests/unit/test_coverage_gate_ratchet.py` enforces the
   pressure. Adding an entry is expanding an allowlist. It is arguably the
   right call anyway: the module was already in debt, and the static seed
   ("every module whose resolved test file never mentions it") missed it only
   because `tests/unit/test_api.py` mentions it. The entry would be honest and
   keeps its own pressure — it blocks the moment the module clears the floor.
   **Cost: one line, and a precedent.**
2. **Raise `api/ws_live.py` to 80%.** ~500 more statements covered in a
   2,425-line module. **Cost: a project, and out of proportion to a 40-line
   security fix.**
3. **Leave it.** The `subscribe` hole stays open (it is only exploitable for
   channels that exist, so no support channel is added), and the support desk
   stays a poll. **Cost: no live queue, and the hole is still there for the
   next private channel someone adds.**

My recommendation is **1**, with the entry carrying the measured 34% and this
section as its reason — and option 2 filed as the work that removes it.

Note the gate found the same class of problem twice today: §E37's
`core/router_registry.py` was excluded by `.coveragerc` under a justification
that was false, and this one is excluded by an omission in the ratchet's seed.
Neither was a module anybody had decided not to test.

---

## §E38 — A test that edited the code it was testing (2026-09-10)

A regression I shipped in §E37, caught by re-running the neighbouring suites
rather than by review.

`test_a_baselined_module_does_not_block` pointed the gate at its own baseline by
reading the copied script and string-replacing this exact line:

    BASELINE_PATH = Path(__file__).resolve().parent.parent / "docs" / "COVERAGE_UNMEASURABLE.txt"

§E37 split that line to introduce `REPO_ROOT`. The replacement stopped matching
— silently, because `str.replace` on a missing needle is a no-op — so the copied
gate read the **real** repository's baseline, `mymod/thing.py` was not in it, and
a test about the ratchet failed for a reason that had nothing to do with the
ratchet.

Confirmed by worktree rather than by reading: green at `57848f5`, red at
`b932dd2`. The failure set, not a count.

`COVERAGE_BASELINE_PATH` is now a real seam, and the test uses it. Source
surgery on an implementation line is a trap for whoever touches that line next,
and it fails in the worst way — quietly, pointing at the wrong subsystem.

The new variable is an escape hatch and is documented as one: anyone who can set
it can point the gate at a file listing every module. It adds no capability,
because the same person can already set `SKIP_COVERAGE_GATE=1`, which is
documented and louder.

---

## §E39 — The operator queue is live (2026-09-10)

§A6 decided; this is what the decision unblocked.

`api/ws_live.py`'s privileged-channel patch is applied (see §A6 and ADR 0017 for
why it could be), and `api/support.py` now pushes every queue change on
`support_queue` — a channel that is **privileged and private**: a customer
cannot subscribe to it, and it is never delivered through the implicit
"empty subscription = all channels" firehose. Both properties are asserted.

Six events: `escalated`, `claimed`, `released`, `resolved`, `customer_replied`,
`operator_replied`. `GET /api/support/queue` remains, so a console that misses a
frame resynchronises rather than drifting.

### Three rules, each with the failure it prevents

**A broadcast is never the operation.** The ticket transition is the work; the
push is a notification about it. If the socket is down the claim still happened,
the reply is still saved, and the customer is still answered — and the failure
logs at **ERROR**, because a console that has silently stopped updating looks
exactly like a quiet queue. That is F248: three alert call sites raised
`TypeError` into a DEBUG handler, so a tripped circuit breaker notified nobody
for as long as the code existed.

**Nothing is announced for a transition that did not happen.** `_transition`
runs the store call first, lets `_apply` raise on a refusal, and only then
re-reads and announces. A losing claim publishes nothing.

**No message bodies travel.** The payload carries what a row needs — id,
subject, status, department, category, holder, timestamps. An operator opens the
thread to read it. A broadcast carrying every customer message puts the whole
conversation into every connected console's memory and into any log that records
frames.

The mutating routes became `async def` with the blocking store and model calls
on `run_in_threadpool`, so the broadcast can be awaited after the commit without
an inference holding the event loop.

### The finding: the ordering rule was unproven

Four counterfactuals were run. Three failed as they should. The fourth — moving
`_announce` **above** the store call — left all fifteen tests green.

The event *names* were still right; only the payload was the pre-transition
state, and a refused claim's broadcast was covered by nothing. So a claim that
lost a race would have put a row on every console showing an operator who does
not hold the ticket, while the operator who does hold it watched their row get
taken. That is §E30's "success reported for work that did not happen", one layer
up.

Four tests now pin it: a losing claim and a refused reply announce nothing, and
the payload is asserted to be the state *after* the transition. Same
counterfactual now fails all four.

That is the fourth time in this programme a counterfactual has caught a suite
proving something other than what it claimed — §E33's floor, §E35's escalation
branch, and the `_local_is_ready` source-reading test before them. **The pattern
is always the same: the test asserted an outcome that a second, unrelated code
path also produces.**

`api/support.py` is at 97% with the support suites, 19 real-time tests, 1,093
tests across the affected areas.

### Still open

* **No UI.** Per CLAUDE.md an operator console needs a `flow-prototype` approval
  pass before production implementation — the owner's call.
* **`answer_question` is still called with no facts.** The department briefs are
  written to answer from a FACTS block and nothing gathers one from the
  departments' read-only actions.
* **`api/ws_live.py` at 35%** — recorded debt, not permission. §A6 option 2.

---

## §A7 — APPROVED 2026-09-10: the operator console is built

**All four verdicts approved by the owner in conversation** — queue triage,
claim→answer→resolve, the live channel, and the visual direction. Recorded here
rather than in the prototype's own store: the store held no document, so the
approval is the owner's direct statement, which is authority. Saying the store
carried it would be a claim the evidence does not support.

Built as `frontend/src/pages/SupportConsole.tsx` at `/support-console`,
admin-gated, sidebar entry under Admin. See §E40 for what the build found.

**The prototype is superseded.** It never entered the repository — it lived in a
scratchpad and as a published artifact — so there was nothing in production to
tear down, and a grep confirms no review controls, mock adapters or seed data
reached the page. The artifact stays as the approval record and must not be
linked as though it were the product.

The original decision text follows, because the reasoning is what was approved.

---

**Was: awaiting approval.** CLAUDE.md routes any major UI/UX change through
`flow-prototype` before production implementation, and that skill is explicit:
*"If no approver is reachable, halt before production UI. Questions forbidden is
not approval. No post-hoc approval."* So the console exists as a throwaway
review surface and nothing more.

**Review it here:** https://claude.ai/code/artifact/1527f1a7-d04c-4d42-ad3e-74fa76e61d4f

Read-only, deterministic mock seed, no broker, no database, no message ever
sent. Eleven states are reachable from the rail; each one annotates its
container choice, state change, motion and recovery path. Verdicts and notes are
stored in the artifact's own store, so what you mark comes back to me.

### What is being asked

Four verdicts — queue triage, claim→answer→resolve, the live channel, and the
visual direction.

### The design decisions worth disagreeing with

* **The console reuses HOPEFX's own tokens** (`frontend/src/index.css`) rather
  than a new palette: `#080c14` ground, `#00d4ff` accent, 224px rail, 56px
  topbar. The recommendation engine proposed glassmorphism in gold and purple;
  the product's existing language outranks it.
* **Queue state deliberately does not use the market palette.** Green and red
  mean price direction on this platform. A red row must not read as "down", so
  waiting is amber, held-by-you is cyan, held-by-someone-else is slate, and red
  is reserved for the escalation floor's own severity.
* **The signature element is the escalation ribbon** — every row carries *why*
  the floor sent it, in the floor's own words, because an operator taking over
  mid-thread needs the reason and not just the fact.
* **Rejected:** a KPI-card hero (nobody triages by average handle time) and a
  chat-bubble layout (it hides the audit trail that makes this desk defensible).
* **A claim is inline, not a modal.** It is small and reversible; a modal would
  be theatre. A *conflict* is an inline banner rather than a toast, because a
  toast that disappears takes the holder's name with it.

### What the prototype does not prove

A browser prototype proves interaction intent. It does not prove native
behaviour, backend correctness, or production performance. The live channel is
simulated — the real one is `support_queue`, landed in §E39.

### After approval

The prototype is deleted, not absorbed: review controls, mock adapters and
abandoned pathways do not reach production. The decision and its reasoning are
recorded here.

---

## §E40 — The operator console, and an identity I guessed (2026-09-10)

§A7 approved; this is the production build. `frontend/src/pages/SupportConsole.tsx`
at `/support-console`, admin-gated through the same `adminOnly()` wrapper as
`/ai-core`, with a sidebar entry in the Admin group.

Three pieces: `supportApi` in `hooks/useApi.ts` (both surfaces, kept separate
because the server gates them separately and a client that blurs them invites a
button the server refuses), `hooks/useSupportQueue.ts` for the live channel, and
the page.

### The live source is a measurement, not a decoration

`useSupportQueue` owns its **own** socket rather than joining the app-wide one.
The app-wide connection subscribes for every signed-in user, and asking it to
add a channel only admins may join would make the server refuse on every
ordinary session — noise that trains people to ignore the refusal that matters.

It reports one of three sources and never guesses: `live` (a frame arrived
within 25s), `poll` (the socket is quiet or closed — React Query's interval is
what is feeding the page), `refused` (the server said this role may not join).
The subscribe reply is read for what it **granted**, not what was asked for,
because §E39 made the server return refusals rather than dropping them.

A socket that is open but silent is not feeding the page. Without the staleness
timer the pill would read "live" for as long as the connection object survived —
which is the whole failure this feature exists to prevent.

### The finding: I derived the operator's identity by guessing

The first version worked out "who am I" from the queue: *the first ticket
someone holds must be mine*. A test caught it on the first run. A ticket held by
`ops-ren` rendered as **"you"** — so the console showed another operator's work
as this operator's, offered Release on it, and hid the holder's name in exactly
the place it was needed.

That is Rule 2 at its most expensive: an unmeasured value presented as the best
case. It now comes from the authenticated session, `useStore(st => st.user?.id)`.

Worth noting the shape, because it is the same one four counterfactuals have
found in this programme: **the wrong value was indistinguishable from the right
one in the common case.** With one held ticket, guessing works. It only breaks
when a second operator exists — which is the entire point of a queue.

### Five counterfactuals, all failing correctly

| Break | Result |
|---|---|
| Live pill hardcoded to `live` | 2 failed |
| Claim offered on a ticket another operator holds | 1 failed |
| A failed queue request renders as an empty queue | 1 failed |
| Escalation reason dropped from the row | 2 failed |
| Composer enabled regardless of who holds it | 1 failed |

Every rule the owner approved is load-bearing rather than decorative.

### The colour ratchet blocked my own commit, and was right to

§E27's ratchet refused the first version of the page: **25 hardcoded hex
literals in a file with no baseline entry.** 8,046 against a baseline of 8,021.

The fix is not an exemption. The queue semantics genuinely did not exist as
tokens — waiting, held-by-you, held-by-someone-else, resolved, and the
escalation red — so they were **added to `frontend/src/index.css`**, which is
the one file the ratchet exempts because it is where tokens are defined. The
page now carries **zero** colour literals and the count is back to exactly
8,021 across 202 files.

That makes this the rare page whose light theme and white-label branding
actually work, which is the whole reason the ratchet exists. A gate that blocks
the person who wrote it, on their own commit, and produces a better result than
the version it refused, is a gate doing its job.

`npx tsc --noEmit` clean, `npm run build` emits
`static/assets/SupportConsole-*.js`, 151 tests green across the console, nav
contract, route guards, page and API-contract suites. (A workbox globbing
warning appeared in one build and did not reproduce in three subsequent runs,
including on the clean tree — intermittent, and not introduced here.)

### Still open

* **`answer_question` is still called with no facts.** The department briefs are
  written to answer from a FACTS block and nothing gathers one from the
  departments' read-only actions. Unchanged by this work, and the last
  substantial gap in the desk.
* **No customer-facing ticket UI.** `supportApi` carries the customer half and
  the endpoints exist; no page uses them yet, so customers still have no way in.
* **`api/ws_live.py` at 35%** — recorded debt under ADR 0017, §A6 option 2.

---

## §E41 — The customer ticket UI, and a classifier oracle on the wire (2026-09-10)

`frontend/src/pages/Support.tsx` at `/support`, behind plain `AuthGuard` with no
plan gate — the backend admits `starter`, which is the lowest role, and putting
support behind a paid tier is how a billing complaint becomes unreachable.

### The finding: the customer surface was shipping the triage internals

`my_ticket` and `my_tickets` returned `TicketView.as_dict()` — the **operator's**
projection — to the customer who raised the ticket. Three fields do not belong
there, and one of them is a security problem rather than a taste problem:

* **`matched_on`** is the exact phrase that tripped the floor: `"withdraw"`,
  `"is … going up"`. Handing it back is a **classifier oracle**. Probe a few
  phrasings, learn which words reach a person and which reach the AI, then
  phrase around the floor. The floor is this platform's regulatory guard — it is
  what stops the AI answering "should I buy gold?" — so that is not a curiosity.
* **`escalation_reason`** is wording written for an operator. *"This platform is
  not licensed to give financial advice"* reads as a lecture to the person who
  asked, and explains the classifier's reasoning to someone with no need for it.
* **`assigned_operator_id`** names the staff member handling them.

`TicketView.as_customer_dict()` is the projection, and the endpoints use it. Six
tests failed on the pre-fix tree. One asserts against the **whole response body**
rather than a key list, because a field removed from the projection but echoed
in a message body or a status string is the same leak with a different name.

Removing the reasoning must not remove the fact: a test holds that the customer
still learns `needs_human` and the ticket's state.

A UI that declined to render those fields would not have fixed this. The data
was on the wire.

### What the page does differently from the operator console

* **A customer can tell who answered.** Every reply is attributed and an AI
  reply says so. Letting a machine's answer pass as a person's is an honesty
  problem before it is a regulatory one.
* **An escalated ticket says a person is coming** — in as many words, and it
  says the assistant was taken off the conversation *on purpose*. The
  alternative is a customer watching a thread that never moves.
* **There is no live channel here.** `support_queue` is operator-only; giving
  customers one would be a channel carrying other people's tickets. The page
  polls at 15s and says nothing about being "live", because it is not.

### Two tests that were passing for the wrong reason

The counterfactual sweep found the empty-ticket guard **unproven**: deleting it
left all eleven tests green.

    await waitFor(() => expect(open).not.toHaveBeenCalled());

`waitFor` resolves on its **first tick** — before React Query has invoked the
mutation at all — so this measured "not yet", not "not at all". A negative
assertion with no barrier in front of it proves nothing. Both suites now put a
positive observation first: wait for the refusal message (customer page), or
send a real body and watch that call land (console), so the silence that follows
is a measured absence.

Strengthening the console's version exposed a second one. It asserted the
empty-reply guard while the composer was **disabled** — the seeded ticket said
`assigned_operator_id: 'me'` but nothing had signed anyone in, so `mine` was
false and the button was inert. The test had never reached the guard. It now
seeds the store, which is the identity source §E40 established.

That is the sixth time in this programme a counterfactual has caught a suite
proving something other than what it claimed.

### Verification

Ratchet at exactly 8,021 across 202 files — the new page carries **zero** colour
literals. `tsc --noEmit` clean; build emits `Support-*.js` and
`SupportConsole-*.js`. **164 frontend tests** across both support pages, nav
contract, route guards, page and API-contract suites; **205 backend tests**
across the five support suites and the app-surface gate.

### Still open

* **`answer_question` is still called with no facts** — the last substantial gap
  in the desk, and unchanged by this work.
* **`api/ws_live.py` at 35%** — recorded debt under ADR 0017, §A6 option 2.

---

## §E42 — The facts reach the answer, and READ_ONLY is not "safe to send" (2026-09-10)

The last substantial gap in the desk. `support.answering` composed a FACTS block
and told the model to state no figure that was not in it — and **nothing filled
that block**. Every reply came from the department brief alone, so the strictest
half of the design was carrying the whole thing.

`support/facts.py` fills it from the routed department's own read-only actions.
`answer_question(facts=None)` now gathers; `facts={}` still means a caller
deliberately decided there are none. Conflating those two would make a
deliberate empty block indistinguishable from an unmeasured one, which is the
distinction the module exists to keep.

### The finding: the obvious implementation was a disclosure path

"Call every implemented READ_ONLY action that needs no arguments" is the natural
rule. Measured against the real registry, it calls:

    platform_engineering.scan_secrets      -> secret-scanner findings
    platform_engineering.walk_code         -> source
    platform_engineering.run_tests         -> the test suite, per support ticket
    research_intelligence.run_backtest     -> a backtest, per support ticket
    markets_execution.shadow_place_order   -> a simulated order

The first two are the serious ones: their output would be pasted into a prompt
sent to a **third-party model**.

> **The risk tier describes what an action does to the platform. It says nothing
> about what its output is, and the output is what travels.**

So `SUPPORT_FACTS` is a per-department **allowlist**, and the dangerous
exclusions are asserted by name, so putting one back is a deliberate act rather
than a diff nobody reads. Arguments are never invented either — only `operator`,
and only because `support_desk` is this caller's real identity, the same one
`answering` spends its model budget under.

### Two things running it found that reading it did not

**`default=str` makes everything serialisable.** The first `_renderable` used
`json.dumps(value, default=str)`, so a bare `object()` became
`"<object object at 0x7f…>"` — the unrenderable check passed and a memory
address was on its way to a hosted model as a measurement. A timestamp and a
`Decimal` are facts worth coercing; an arbitrary object is not, and `_coerce`
now refuses it.

**A permanently-unmeasurable fact was allowlisted.** Running the gatherer
against the real registry showed `news_intelligence.score_geopolitical_risk`
answering `nothing to score: 'text' was empty` — for every ticket, forever,
because the text to score is an argument this desk will not invent. A fact that
can never be measured is noise in a billed prompt and a control that can never
fire. Removed, with a test holding it out by name.

### What a real ticket now carries

Measured, not described — every allowlisted handler invoked against the live
registry:

| Department | Fact | Result |
|---|---|---|
| markets_execution | query_broker_status | `available: false, reason: broker_unavailable` |
| risk_compliance | check_drawdown | `available: true, passed: true` |
| data_ops | feed_health / stale_sources | `available: false` — no quality engine in this process |
| system_ops | service_health / recent_failures | `available: true`, 260 B / 1,967 B |
| research_intelligence | score_regime | `available: false, no_regime_for_symbol` |
| platform_engineering, notification_ops, news_intelligence | — | declare nothing, deliberately |

The departments' own `available: false` honesty flows straight into the prompt,
so the model is told *"broker_unavailable"* rather than left to guess a broker
state. That is the whole point: `ai/departments/` refuses to invent a number,
and the fact block refuses to hide that it refused.

### Rules held by test

* A handler that raises, times out, or returns something unrenderable
  contributes `None` → rendered as `not measured`, and logged at **ERROR**: a
  gatherer that quietly returns nothing looks exactly like a system with nothing
  to report (F248).
* A spent budget records absence rather than **omitting the key** — a key that
  vanishes lets the model assume the department had nothing to say.
* One dead action does not blank the block.
* A broken gatherer never takes the answer down; the facts improve an answer and
  are not a precondition for one.
* An escalated question gathers nothing — no measurement, no spend, no model
  call. The floor returns first.

Five counterfactuals, all failing correctly: allowlist widened to the dangerous
actions (4 failed), a failed handler contributing a plausible value (2), an
unserialisable value passed through (3), explicit facts overwritten by gathering
(2), and a broken gatherer taking the answer down (1).

`support/facts.py` at **100% statement and branch coverage**;
`support/answering.py` at 100%. **292 tests** across the support and department
suites.

### The desk is complete

Triage decides, tickets record and refuse, answering drafts from measured facts
or says it cannot, the API serves both audiences with separate projections, the
queue is live, and both consoles are built. What remains is operational rather
than structural:

* **`api/ws_live.py` at 35%** — recorded debt under ADR 0017, §A6 option 2.
* **No end-to-end test** drives a customer question through triage → facts →
  gateway → ticket → operator queue in one run. Each seam is tested; the chain
  is not.

---

## §E43 — The desk proven as a system, and nine tests that passed against a dead chain (2026-09-10)

`tests/integration/test_support_desk_end_to_end.py` — 18 tests driving a
customer question through the whole chain: triage → facts → gateway → ticket →
broadcast → operator queue → claim → reply → resolve → back to the customer.

Every seam already had a suite. Nothing ran the chain, so a break **between** two
green modules had nowhere to show up.

Real throughout: `support.triage`, `support.facts` and the department handlers it
calls, `support.tickets` on a real SQLite file, `api/support.py`'s routers, and
FastAPI's own dispatch. Two seams stood in for: the **gateway** (the one network
boundary, so the suite needs no model and no credential) and the **broadcast**,
which is *wrapped* rather than replaced so the real coroutine still runs and the
frames are captured.

Marked `integration`, not `e2e`. CI runs `-m "not slow and not e2e"`, so an
`e2e` mark would have made this a test that never runs — the defect class it
exists to catch, applied to itself.

### The finding: nine tests passed against a chain that wrote nothing

`hopefx-dead-controls` records F255 — a code-analyzer test wrote its sample into
`tmp_path`, the analyzer skipped any path containing `/test`, and every "this
must still be flagged" case passed against a scanner that never executed.

> **A harness that never ran agrees with every assertion.**

That was tested here rather than trusted. Breaking `open_ticket` so the store
commits nothing left **9 of 18 tests green** — including
`test_it_does_not_reach_the_operator_queue` and
`test_and_nothing_was_broadcast_for_it`, which assert *absences* and therefore
pass perfectly against a desk that does nothing at all.

`TestTheHarnessIsLive` is what catches it: five tests proving the routes are
mounted, a row reaches the real database, the gateway seam is reached, the fact
gatherer is reached, and a frame is broadcast — **before** any journey asserts
what did or did not happen. Under the silent-write break,
`test_a_ticket_reaches_the_real_database` fails and the harness declares itself
dead instead of quietly agreeing.

### Six inter-module breaks, each caught

| Break | Failures |
|---|---|
| The API stops asking the AI to answer | 6 |
| An unanswerable ticket is no longer escalated (silent ticket) | 2 |
| Facts are gathered but never passed to the prompt | 1 |
| An escalation is stored but never announced on the live channel | 3 |
| The customer projection reverts to the operator one | 1 |
| The operator queue stops filtering on `needs_human` | 1 |

None of these is visible to a unit suite: each module keeps its own tests green
while the chain between them is severed.

Under break 1 the two liveness tests fail *first* —
`test_the_gateway_seam_is_actually_reached` and
`test_the_fact_gatherer_is_actually_reached` — so the diagnosis points at the
severed call rather than at the six downstream assertions that also went red.

### What the chain proves that no unit test could

* A **real department handler**'s answer travels into a **real prompt**:
  `markets_execution.query_broker_status` reports `available: false` and the
  model is told `broker_unavailable` rather than left to guess a broker state.
* The floor **returns before either seam** — `gateway.call_count == 0` and
  `gather.call_count == 0` on an escalated question. No measurement, no spend,
  no model call.
* The frame sequence over one full handoff is exactly
  `escalated → claimed → operator_replied → resolved`.
* The customer reads the resolved thread with the operator's reply in it, and
  the raw response body contains neither `matched_on` nor `escalation_reason`.
* A customer reply after resolution reopens the ticket and puts it back in the
  queue.

289 tests green across the end-to-end, support and department suites.

### The desk is done

Triage decides, tickets record and refuse, answering drafts from measured facts
or says it cannot, the API serves both audiences with separate projections, the
queue is live, both consoles are built, and the chain is proven as a system.

The only outstanding item was **`api/ws_live.py` at 35%** — recorded debt under
ADR 0017, §A6 option 2. Closed in §E45; the module is at 81% and the entry is
deleted.

---

## §E44 — ws_live 32% → 48%, a wrong-side stop, and a ceiling that is not 80% (2026-09-10)

§A6 option 2, attempted. `tests/unit/test_ws_live_behaviour.py` — 53 tests
against the live socket's origin check, auth handshake, ATR stop-loss maths,
private-channel routing, broadcaster restart, and the three other endpoints'
auth. The module went from **32.11%** to **48%**.

**The debt entry stays.** 80% is not reachable by testing alone, and that is
measured rather than estimated. See below.

### The defect: a stop on the wrong side of the price

`_compute_atr_sl_tp` — 53 statements of money maths that had **never executed
once** — decided long or short with:

    is_long = direction in ("long", "buy")

Anything else was treated as a short. `"LONG"` or `"BUY"` therefore returned
`sl = 2030.0` against a `mid` of `2000.0`: a stop **above** a long entry, which
does not protect the position, it closes it.

Today's only caller lower-cases and maps to exactly `"long"`/`"short"` before
calling, so the hazard was not reachable — but the function is module-level with
a permissive signature, and the next caller need not be so careful. It now
normalises case and whitespace, which cannot change behaviour for the two
strings that reach it today. Three parametrised tests pin it.

Also verified for the first time: the percentage fallback really is 1% of mid,
the multipliers really are re-read from `SL_ATR_MULT`/`TP_ATR_MULT` at call
time as documented, the CSV tier really does produce a different level from the
fallback, and a malformed CSV falls through instead of taking the signal
broadcaster down.

### Why 80% is not reachable by testing

Three harnesses for the broadcaster loops had to be **killed**:

1. a patched `asyncio.sleep` raising `CancelledError` after N calls — but
   `ws_live.asyncio` *is* the global asyncio module, so the patch replaced sleep
   for the whole process, pytest-asyncio included;
2. the same patch yielding instead of raising — every broadcaster became a spin
   loop that outran the canceller;
3. real sleeps, `wait_for`, and a cancel — still hung, because something inside
   the loops blocks in a way cancellation does not interrupt.

The same shape holds for the three endpoints' **post-auth** paths: an
authenticated admin on `/ws/audit-events` enters a polling loop that
`wait_for` cannot interrupt either. Their auth and refusal paths are fully
covered; their loops are not.

Measured against the AST:

| Region | Statements | Testable in-process |
|---|---:|---|
| 7 broadcaster `while True` loops | ~269 | no |
| 3 endpoint post-auth loops | ~217 | no |
| module total (coverage-counted) | 1,104 | — |

Ceiling with both excluded: **~56%**. Even excluding only the broadcasters, and
assuming every other line were covered: **75.6%**. Neither reaches 80%.

A test that faked the event bus, Redis and the price feed to walk those loops
would prove the fakes work. That is the coverage theatre this repository already
has a name for, and it is worth less than the honest number.

### What would reach 80%, and why it was not done

Extract each loop body into a callable unit so the `while True` shell is three
lines and the body is testable:

    async def _tick_once() -> None: ...        # testable
    async def _eventbus_tick_broadcaster():
        while True:
            await _tick_once()
            await asyncio.sleep(_INTERVAL)

Mechanical, and behaviour-preserving in principle. It is also a structural
change to seven loops in the live WebSocket surface of a money-moving system,
verifiable here only by unit test — there is no real feed in this environment.
That is a **different decision** from the one taken in §A6, so it is filed
rather than assumed.

**Deleting the entry at 48% would be actively harmful**: the gate's rule is that
an unrecorded module below the floor *blocks*, so removing the line puts
`api/ws_live.py` back to blocking every commit that touches it — the state §A6
was created to escape. The line goes when the number clears 80%, and the gate
enforces that itself: a recorded module at or above the floor blocks with one
instruction, *delete this line*.

### §A6 option 2 — restated for the owner

* **Do the extraction.** ~7 loops, mechanical, unlocks ~269 statements and, with
  the endpoint loops, 80%. Cost: a structural change to the live socket,
  unverifiable here against a real feed.
* **Leave it at 48%** with the entry recorded and this section as its reason.
  Cost: the module keeps recorded debt, and the loops stay unexercised.

I did not choose between these. The first is a live-surface refactor and the
owner said "raise past 80%", not "restructure the broadcasters".


---

## §E45 — ws_live 48% → 81%, and the entry is deleted (2026-09-10)

§E44 concluded that 80% was **not reachable by testing alone** and put the
ceiling at ~56%, because seven broadcaster loops and three endpoint post-auth
loops block uninterruptibly in-process. That measurement was right about the
code as it stood. The conclusion drawn from it was wrong: the obstacle was the
**shape** of the module, not the difficulty of the tests. The owner authorised
the extraction §E44 had filed, and it is done.

`api/ws_live.py` measures **81%**. Its line in `docs/COVERAGE_UNMEASURABLE.txt`
is deleted, which the gate itself demanded — a recorded module that reaches the
floor **blocks**, with one instruction. It did, and that is the ratchet working
in the direction nobody ever tests.

### The shape of the change

Ten `while True:` bodies became callable units; each shell is now three lines.
Nothing about what the loops do changed — the bodies are the same statements in
the same order.

`break` cannot cross a function boundary, so every extracted body returns a
**sentinel**: the next state, or `None` meaning *the socket should close*. The
shells act on it. That contract is asserted structurally, not by convention:
`TestTheShellsStillDrainTheirBodies` parses `api/ws_live.py` and fails if any
loop calls a body without honouring the `None`.

| Body | What it decides |
|---|---|
| `_heartbeat_once`, `_account_update_once` | keepalive and account push |
| `_price_live_only_once`, `_yfinance_price_once` | what price reaches a dashboard |
| `_chartbot_once`, `_signal_message_once` | signal fan-out |
| `_eventbus_tick_once` | reconnect backoff (the attempt counter round-trips through the return) |
| `_pubsub_pump_once` | whether a notification or an audit record is delivered |
| `_heartbeat_only_once` | the Redis-less fallback |
| `_nuclear_stream_once` | whether an operator is told trading has halted |

The two pub/sub pumps were byte-identical apart from the message type, so they
are now one body with a **required** `message_type` — a caller that forgets it
fails rather than silently labelling an audit record as a notification.

### The extraction was the risk, and it bit

An AST-guided extractor did the mechanical work, and three of its bugs mattered:

1. `continue` rewritten to `return` by **indentation** — which loop a `continue`
   belongs to is an AST question, not a whitespace one. Ruff caught it.
2. Pre-loop statements dropped, leaving `_POLL_INTERVAL` undefined. Ruff caught it.
3. The near-miss: `walk(stmt, False)` where `stmt` *was* the `For` node
   converted the heartbeat's **inner** `continue` into a `return`, so the first
   dead connection would have aborted the whole sweep instead of skipping it.
   Nothing caught that but reading the output. It is pinned by a test now.

`_eventbus_tick_once` also fell through returning `None`, which would have
indexed the backoff table with `None` on reconnect; and the first fix put
`return attempt` **before** the `await asyncio.sleep(delay)`, which would have
made the reconnect spin. The repo's own unreachable-code gate caught the second.

### The defect the extraction caused, and the test that now catches it

Hoisting `_get_nuclear_state()` out of `ws_nuclear` put a `def` between
`@router.websocket("/ws/nuclear")` and the function it was written for. Python
does not complain. The decorator registered the **helper** — a synchronous,
zero-argument function — and `ws_nuclear` was never registered at all. The
module still imported, still linted, still type-checked, and the kill-switch
dashboard feed pointed at something that cannot accept a socket.

Shipped in commit `9c16c20`. Found by running the route table, not by reading
it. The hoist had also left a duplicate, unreachable copy of the body after the
`return`; that is gone too.

`tests/unit/test_ws_routes_are_wired.py` now asserts the wiring itself: every
`WebSocketRoute` in the module resolves to an async endpoint that takes an
argument, `/ws/nuclear` resolves to `ws_nuclear`, and no `_`-prefixed helper is
registered as an endpoint. This is the F176 shape — a control that exists and
never runs — and the route table is the wiring, so the wiring is what gets
asserted.

An earlier version of the shell test **re-implemented the shell inside the
test** and drove that. It would have passed against a shell that had lost its
call entirely, which is the one thing it existed to catch. It reads the module
now.

### What the extraction made testable, and what that found

The endpoints terminate now, so `ws_notifications`, `ws_audit_events` and
`ws_nuclear` can be driven **connect → auth → stream → teardown** against a fake
socket. Eighteen tests do. Among them: every non-admin role — including
`"administrator"` and `"ADMIN"` — is refused the audit stream, which is the
whole platform's superadmin action log (S6-02 shape, and it had never executed).

Two findings, both recorded rather than changed:

* **A Redis outage reaches these endpoints two ways and they behave
  differently.** A factory that *raises* degrades to a keepalive-only loop and
  the socket stays up; a factory that *returns None* closes it with 1011. Only
  the first is a fallback. Which one a client gets is a product decision, so
  both are pinned by test and neither is altered here.
* **The yfinance price path** derives bid, ask and `change_pct` itself and had
  never executed. It is correct: the spread straddles the mid, a first tick
  reports `0.0` rather than inventing a move (Rule 2), a non-positive price is
  refused rather than quoted, and one bad symbol does not stop the other eight.
  All of that is now asserted rather than assumed.

### Counterfactuals

Every guard added here was broken on purpose and watched to fail:

| Break | Goes red |
|---|---|
| a shell drops its body call | `test_each_body_is_called_from_a_loop_that_acts_on_the_sentinel` |
| `ws_audit_events` labels its stream `notification` | `test_the_endpoint_passes_its_own_message_type` |
| `_nuclear_stream_once` forgets `last_severity` | the crossing and resume tests |
| the `/ws/nuclear` decorator slips onto a helper | four tests in `test_ws_routes_are_wired.py` |

The message-type case is the one worth keeping: it passed the **first** time.
Every direct test of the shared pump stayed green, because the body does exactly
what it is told — only the call site proves which label an admin actually gets.
A parameter is not a control until something asserts its caller.

### One fixture bug, for the record

The first nuclear tests failed because the fake socket raised
`WebSocketDisconnect` whenever it had no queued input. A real client with
nothing to say produces a `TimeoutError`; the stream continues. The fake made
every pass look like a closing socket, turning assertions about the stream into
assertions about the teardown. Suspect the measurement — it held again.


---

## §E46 — Three safety failures that told nobody (2026-09-10)

The same defect three times, in the auth surface, each found by executing the
path rather than reading it. None of them is a bug in the control; each is a
control that stops working and reports it at DEBUG, which is off in production
(F248). The one moment the system is unprotected is the one moment nobody is
told.

`auth/service.py` went **67% → 81%** on the way, so it clears the floor and
needs no debt entry.

### 1. The change-password throttle

`/api/auth/change-password` takes `current_password`, which makes it a
credential-guessing surface: a stolen access token is a session, the password
is the account. The throttle is what stands between those two states, and it
was wrapped in `except Exception` that logged at DEBUG and carried on.

Failing open there is **correct** — a limiter fault must not lock a user out of
changing their own password, which is what they do when they think someone else
has access. What was wrong is that the log named the *fault*
("rate limit unavailable") and not the *consequence*. It now says the request
was served unthrottled, at ERROR, with the user and the address.

The throttle itself had never been executed by any test. The existing suite for
this route asserts source text — that the module does not name a column, that
it imports the right helper — which is how a route can be well covered and
never run.

### 2. Token revocation reads as "not revoked" during a Redis outage

`_TokenBlacklist.is_revoked()` falls back to a per-process set when the Redis
read fails. That set is authoritative only for a process that has never reached
Redis; once Redis has been serving, the JTIs live there and the set is empty —
so the call returns False and **a revoked token is accepted as valid**
(STRIDE-S). `revoke()` fails the same way in reverse: the write lands in one
process, so "sign out everywhere" leaves the token live on every other worker.

Both logged `"Suppressed exception: %s"` at DEBUG.

Both now log at ERROR naming the consequence. **Neither behaviour is changed** —
failing closed would sign every user out during a Redis blip, and which side to
fail on is an owner decision, filed rather than taken. Both are pinned as
*observed* by `tests/unit/test_token_revocation_survives_redis.py`, so a future
change of posture is deliberate and visible.

### 3. TOTP secrets stored in plaintext

`encrypt_totp_secret()` returns the **plaintext** when `CONFIG_ENCRYPTION_KEY`
is unset, and `setup_2fa()` wrote it to the column under the comment
`# encrypted at rest`. The fallback carried its own comment —
`# fallback: store plain (warn in logs)` — and no warning was written anywhere.
A control described in a comment and implemented nowhere.

`config/startup_validator.py` requires the key for production, so this is a
misconfiguration path rather than a certain hole. It is still the second factor
for every user, and a database leak in that state is a complete 2FA bypass.
Now logged at ERROR; the false comment is corrected; whether enrolment should
*refuse* without a key is filed for the owner.

### What the coverage bought

The 2FA enrolment path and the account-lockout path had never executed —
between them most of the 33-point gap. Driven now against a real in-memory
SQLite with the real ORM models, not a stubbed `query()`, because the defects
worth catching there live in the interaction with the database: a secret stored
in the clear, a second factor live before it is confirmed, a lockout that counts
the wrong rows. A fake session answers for all three.

### Two harness bugs of my own, both the F255 shape

Worth recording because both would have left green tests proving nothing:

* A test asserting the throttle short-circuits before the password compare
  **passed with the throttle removed** — the DB was unreachable, so
  `verify_password` ran on no path at all. Fixed by giving the test a working
  DB seam and asserting liveness (the compare is reachable) before asserting
  the count.
* A fixture that set `auth.service._redis_sync = None` to "force the DB
  fallback" did nothing: the login path does `import redis as _redis_sync`
  **inside** the function, so that name is a local, not a module attribute. The
  tests were running against the real Redis in this environment, one test's
  lockout key outlived it, and a later test found the account already locked —
  under a randomised order, which made it look like a product bug. The seam
  that exists is `redis.from_url`.

Every guard added here was broken on purpose and watched to fail: silencing
each of the three logs, enabling 2FA at enrolment, and letting `disable_2fa`
keep the secret.


### 4. And a gate of ours that had been red since ff765d2

`scripts/ci/gate_g_import_discipline.py` enforces `data_layer`'s public surface
— exactly `orchestrator`, `tick_store`, `feeds.*`, as CLAUDE.md documents.
`api/data_layer.py` reached past it with `from data_layer.outage import
get_supervisor` when the feed-outage supervisor was added in ff765d2. The gate
has reported that as a **NEW violation** ever since, and
`tests/unit/test_gate_g_import_discipline_injections.py` has been red with it.
Nobody acted on it, this session included, until a full-suite run surfaced it.

The fix is not to widen the surface — that retires a rule to avoid following
it. Feed health is now exposed **on** the surface as
`data_layer.orchestrator.get_feed_outage_status()`, which is where the
relationship already lived: the orchestrator is what feeds the supervisor its
observations on every read. `api/data_layer.py` calls that.

Found on the way, and pinned rather than fixed: `data_layer/__init__.py:42`
binds the singleton `orchestrator` over the submodule name, so
`from data_layer import orchestrator` yields a `MarketDataOrchestrator`
**instance**, and — because `import a.b as c` resolves `b` as an attribute of
`a` before consulting `sys.modules` — so does `import data_layer.orchestrator
as m`. Only `from data_layer.orchestrator import <name>` reaches the module.
This is the same shadowing that cost time in `support/__init__.py` earlier in
this programme. Unbinding it is an API change for 86 production importers, so
it is documented by test instead.

### A contaminated measurement, for the record

The first full-suite run of this change reported six failures, five of them in
`test_password_change_and_enumeration.py`. All five passed in isolation. The
run had been launched **before** the edits and was still going while the
counterfactual passes were deliberately breaking and restoring the very files
those tests read. The suite was measuring me, not the code.

Diff failure sets, never counts — and never run a suite across your own edits.


---

## §E47 — What is left, measured; and one dead control armed (2026-09-10)

`python scripts/backlog_report.py` on a clean tree. The numbers below are that
run, not a recollection.

| Section | Measured |
|---|---|
| Specification capabilities | 233 rows · **233 live** · 0 staged · 0 planned · 0 discrepancies |
| Live capabilities with no production caller | 157 screened · **38 flagged** → **37** after this change |
| Documentation debt | 224 registered · 197 with no owner · 3 duplicate subjects · 41 stale refs |
| Group 2 platform gaps | 19 outstanding (3 struck through) |
| Group 3 knowledge gaps | 6 outstanding (8 struck through) |
| Group 4 invariants | 21 recorded · **11 not yet AVAILABLE** |
| Safety gates | 29 gates · 29 proven able to fail · **0 unproven** |
| Coverage debt | 365 modules recorded |
| Owner decisions | §A1 (RPO/RTO), §A4, §A5, plus three opened this session |

Nothing is *planned but unbuilt* in the specification — every row is live. The
work left is in the second line: capabilities that are live and that nothing
calls.

### The one fixed here: `sec.secrets` was never armed

`ai/guardrails/output.py` scans model output two ways — regex shapes for
credentials with a distinctive form, and exact matches against **this
deployment's real values**. The module states plainly why the second exists:

> Patterns cannot cover a secret with no distinctive shape — this platform's
> own JWT signing key, a broker password, the system prompt. Registering the
> live values is what makes leakage of those detectable at all, and it is the
> only mechanism here that can catch system-prompt echo.

and `register_known_secret` states when it runs:

> Called at startup with values already in the process (the JWT signing
> secret, broker passwords).

**Nothing called it.** The only callers were tests. `_KNOWN` was empty in every
running process, so the exact-match arm scanned against nothing, the
system-prompt echo check did not exist, and `StreamScanner`'s holdback never
widened past its fixed floor. F176 exactly: a control that exists, is
documented accurately, and is never invoked.

`register_deployment_secrets()` now reads 21 named environment variables and
registers the values present; `init_env` calls it once the secrets are resolved
into the process. It returns a **count**, never the values or the names of what
matched — a registrar that returned its findings would copy the secret into the
caller's log line, which is the failure `_refuse` exists to avoid. Failure to
arm logs at ERROR and never blocks startup.

The counterfactual is kept in the suite as a test: without registration, output
containing the signing secret passes the scanner. That is what production did.

Screen after the change: **38 → 37**, with `sec.secrets` gone from the list.

### The 37 that remain, classified

Not a verdict — the screen matches symbols and misses aliases — but every row
below was inspected, not assumed.

**4 are false positives.** `arch.layer_a…d` are *derived roll-ups*:
`layer_state()` computes them from the rows beneath and is called at
`ai/hub/capabilities.py:2667`. They have no caller *of the id* by design. The
screen should know its own roll-up ids; until it does it reports four permanent
false positives, and a screen that always cries wolf four times teaches readers
to skim it.

**24 are the AI Hub frontend, and this is one finding, not 24.** Every one is a
module under `frontend/src/hub/` — `layout.ts`, `panelSchema.ts`, `modes.ts`,
`attention.ts`, `visionSource.ts`, `frameTriage.ts`, `a11yContrast.ts`,
`a11yLiveRegion.ts`, `a11yBreakpoints.ts`, `voicePrefs.ts`, `pronunciation.ts`,
`projection.ts`, `cognitiveStream.ts`, `SurfaceView.tsx`, `layoutStrategy.ts`.
They exist, they are tested, and **no component imports them**. Verified by
example rather than by count: `COLLAPSE_ABOVE` is used inside `place()`, which
is exported and imported nowhere — `hub/layout.ts`'s only non-test importer,
`PresencePanel.tsx`, takes `readLayout` and `suggestLayout` and nothing else.
`CognitiveStream` is imported only by `hub_panels_and_stream.test.ts`.

So the Hub's frontend was built as a library and never mounted. Wiring it is a
**build**, not a fix, and it is major UI work — which under `flow-by-flow` needs
a `flow-prototype` approval surface before any production UI lands. It is not
started here for that reason, and demoting the 24 registry rows to make the
screen quiet would be manufacturing a clean number, which is the defect this
programme exists to remove.

**9 are backend rows.** They were inspected, and the result corrects what the
sentence here first said — that each had "the same shape `sec.secrets` had".
**Eight of the nine are false positives.** The screen matches a symbol; production
reaches these another way:

| Row | Why the screen missed it |
|---|---|
| `perf.bounded_concurrency` | `DEFAULT_MAX_CONCURRENT` is a **default argument** of `JobRunner.__init__`; nobody names it. `get_runner()` runs from `api/safe_agent_platform.py` (3 sites) and `api/ai_core.py`. |
| `improve.patch_generator` | reached by **factory**: `core/startup_factories.py:770` calls `patcher.build_patcher()`, not `GatewayPatcher`. |
| `improve.honest_cycle_report` | same import: `from ai.improve import cycle, patcher` at line 763. |
| `parallel.long_running` | `ai.jobs.store` is imported by `ai/jobs/runner.py`, which production imports. Reached through a chain. |
| `debate.no_forced_consensus` | `ai.debate.session` is imported by `ai/agent/orchestrator.py`, `ai/debate/trade.py` and the package `__init__`. |
| `memory.working`, `memory.session` | `api/ai_memory.py` does `from ai.memory import tiers`. |
| `memory.user_controls` | `api/ai_memory.py` does `from ai.memory import governance`, at seven call sites. |

The `from pkg import module` form defeated my own first sweep twice before I
noticed — the grep looked for `from pkg.module import`. Worth writing down: it
is the same class of miss the screen makes.

**One is real.** `parallel.event_triggered` — `ai/bus/triggers.py` is reached by
nothing: not by symbol, not by module, not by `ai/bus/__init__.py`, which
re-exports `agent_bus`, `graph` and `lifecycle` and not `triggers`. Wiring
event-triggered parallel work into production is a feature decision, not a bug
fix, so it is filed rather than invented.

So the honest total: of 38 flagged, **1 was a dead control and is fixed**
(`sec.secrets`), 4 are roll-ups by design, 8 are backend false positives, 1 is a
real backend gap, and 24 are the unmounted Hub frontend.

**The screen itself was the thing worth fixing.** Thirteen of its 38 rows were
false — a third — and a report that cries wolf a third of the time teaches
readers to skim it, which is how `sec.secrets` survived in it. **Done below.**

### A regression this change shipped, caught by the clean run

Lifting `core/startup_factories.py` from the omit list turned
`test_coverage_gate_ratchet.py::TestReadingTheOmitList::test_it_finds_a_real_entry`
red: it proved `_coveragerc_omits()` works by naming a module that was in the
list, and the list no longer had it. A legitimate pin, broken by a legitimate
change.

It now names `core/acceleration/gpu_engine.py` — an exclusion whose reason is a
property of the machine (no CUDA in CI) rather than a claim about the test
suite, so lifting *that* would be a real decision rather than a correction. A
second test derives entries from the file itself and asserts the helper matches
every concrete one, so the next honest lift does not break the helper's own
test. And `test_startup_factories_is_no_longer_omitted` pins the lift, mirroring
`test_router_registry_is_no_longer_omitted` from §E37.

The first draft of the derived test picked `*/setup.py` — the first entry, and a
glob. Handing a pattern back to a matcher asserts it matches itself, which is
true of a matcher that does nothing. It filters to concrete paths now.


### And an exclusion that hid a module from the ratchet entirely

Arming the guardrail meant touching `core/startup_factories.py`, and the
coverage gate refused it:

> EXCLUDED by .coveragerc [run] omit, so it cannot be measured. Remove its line
> from the omit list (and add the tests it then needs) rather than looking for
> a missing import.

The justification in `.coveragerc` was *"Startup factories require full app
context; covered by integration/e2e tests, not unit tests."* False, and false in
exactly the way `core/router_registry.py`'s was in §E37 — a defect the file's
own comment already documents, three lines above the entry:
`tests/unit/test_startup_factories.py` and
`tests/unit/test_core_startup_factories.py` exercise it directly, **59 tests**
between them.

The exclusion is worse than recorded debt. A recorded module reports a number
and applies pressure; an excluded one reports nothing, can show neither debt nor
progress, and blocks any commit that touches it with a diagnosis that points at
a missing import which is not missing.

The omit is lifted. Measured with it lifted: **49%**, on a clean worktree at
`1a4a0a0` with the change absent, and **49%** after — so ADR 0017's conditions
1 and 2 are proven rather than claimed, and it is recorded in
`docs/COVERAGE_UNMEASURABLE.txt` with its evidence. It leaves the list when it
clears 80%, and the gate blocks until the line is deleted.

Two exclusions have now been found false under the same wording. The rest of
that omit list is worth the same look, and it has not had one.


---

## §E48 — The caller screen stops crying wolf, and catches itself lying (2026-09-10)

§E47 measured the screen's own error rate: 13 of 38 rows false, a third. Two
changes, both against that measured triage rather than a guess.

### Roll-ups are excluded, because they are false by construction

`arch.layer_a..d` are derived roll-ups — `layer_state()` computes each from the
rows beneath it — so they have no caller *of the id* by design. The screen now
reads `ROLLUP_IDS` (already exported by `ai/hub/capabilities.py`) and skips
them. Four permanent wolves, gone: 157 rows screened became 153.

### Module reachability is a SECOND signal, not a replacement

A symbol is not the only way to reach code. Production reaches the flagged
backend rows through a default argument, a factory, an import chain, and
`from pkg import module` — the form that defeated two hand-written sweeps. Each
row now carries `module_reached`, and the report splits:

* **UNREACHED** — nothing names the symbol *and* nothing imports its module.
  The strongest evidence this screen can give. **10 rows.**
* **SYMBOL-ONLY** — the module is imported, the symbol never named. Often a
  default, a factory or a chain, and then the row is false. Sometimes the
  module is imported for a *different* export and the symbol really is dead,
  which is exactly `hub/layout.ts`: imported for `readLayout`, while
  `COLLAPSE_ABOVE` sits behind an exported `place()` nobody calls. **23 rows.**

**Deliberately not folded into `uncalled`.** Dropping symbol-only rows would
have hit the ~25 figure §E47 predicted, and would have made the screen a report
that cannot fail — the shape this programme exists to remove. Both signals are
printed; the reader gets a triage *order*, not a shorter list. The prediction of
~25 is corrected to **33** for that reason, and the correction is the point.

### The screen was counting its own prose

Documenting the triage put `DEFAULT_MAX_CONCURRENT`, `GatewayPatcher` and
`COLLAPSE_ABOVE` into this module's docstrings. The sweep searches the
repository, so it found itself, counted itself as a production caller, and
**three rows silently left the flagged list.**

`security/code_analyzer.py` scanned docstrings as source (F255);
`scripts/verify_skill_claims.py` called four correct files broken because each
carried a comment quoting the defect it fixed. This is the same trap from the
other side, and worse: a false positive here wastes an inspection, a false
negative hides a dead control, which is the only thing the screen is for.

The module now excludes its own file, exactly as it already excluded
`ai/hub/capabilities.py`. Two tests pin it — one asserts the sweep does not
match its own source, one asserts the consequence, that a symbol named only in
the screen's prose stays flagged. Corroborated by the control symbol itself
dropping from 4 production files to 3: `CONTROL_SYMBOL = "PresenceAnywhere"`
was being counted too.

### Where the numbers land

| | |
|---|---|
| Rows screened | 157 → **153** (roll-ups excluded) |
| Flagged | 38 → **33** (37 after `sec.secrets` was armed, −4 roll-ups) |
| Unreached | **10** — `parallel.event_triggered` plus 9 unmounted Hub modules |
| Symbol-only | **23** — the 7 backend false positives and 16 Hub rows whose module is imported for another export |

Every remaining row is one to inspect. None is a wolf the reader has to learn
to ignore.

---

## §E49 — The omit list was an accumulation, not a policy (2026-09-10)

Two exclusions had been found false under the same wording, each by accident —
`core/router_registry.py` (§E37) and `core/startup_factories.py` (§E47). A
third look, this time at every entry rather than the one a commit happened to
touch, found the pattern rather than the instances.

**18 of 23 concrete entries had unit tests importing them.**

| Module | Unit tests importing it | Stated reason |
|---|---:|---|
| `execution/engine.py` | 11 | measured-number comment (an earlier, partial fix) |
| `brokers/oanda.py` | 7 | "live-only — require real credentials" |
| `execution/fix_adapter.py` | 6 | measured-number comment |
| `execution/fix_router.py` | 5 | measured-number comment |
| `core/middleware.py` | 5 | "FastAPI-wired, covered by API integration tests" |
| `core/decision/HOPEFXDecisionEngine.py` | 4 | "requires full app wiring; covered by integration tests" |
| `brokers/oanda_stream.py`, `execution/hopefx_engine.py`, `core/page_routes.py` | 3 each | as above |
| `brokers/oanda_ws.py`, `execution/execution.py`, `core/risk/advanced_engine.py` | 2 each | as above |
| `brokers/interactive_brokers.py`, `ml/advanced_ai.py`, `execution/legacy.py`, `execution/_prom_metrics.py`, `core/health.py`, `core/acceleration/__init__.py` | 1 each | as above |

That set is the order path, the central decision pipeline, a risk engine, and
the broker for the next live-trading milestone. **The code that moves the money,
with a coverage figure nobody could see.**

The list was not a policy anyone maintained. It was an accumulation, each entry
inheriting a justification written for a different file. ADR 0018 records the
rule that replaces it: **a module unit tests import may not be excluded.**

### What survives, and why it can be trusted

Four entries remain, each with a reason that is a property of the machine or of
the module's dependencies rather than a claim about the test suite:

    core/acceleration/gpu_engine.py   CUDA hardware, absent in CI
    ml/rl_agent.py                    heavy optional deps, no unit importer
    core/background_tasks.py          no unit importer
    core/email_webhook.py             no unit importer

`tests/unit/test_coveragerc_exclusions_are_honest.py` re-checks all four on
**every run**, so the reason cannot expire unnoticed. An allowlist nobody
re-checks becomes a permission list. Both directions are counterfactually
proven: re-adding `execution/fix_adapter.py` turns the gate red, and making a
unit test import `gpu_engine` turns its allowlist entry red.

### Two entries the first pass got wrong, and how

* `core/acceleration/__init__.py` was excluded as "hardware-dependent". It is
  not: `tests/unit/test_core_acceleration.py` imports it without a GPU, because
  the package init guards on `HAS_TORCH`. The exclusion was inherited from the
  file beside it.
* `core/metrics.py` reached my own DELIBERATE list on the first pass, because
  no test contains `import core.metrics`. One contains
  `patch("core.metrics.SHARPE_N_TRADES")` — and patching by string imports the
  module. An import statement is not the only way a test reaches code, and the
  gate checks that form now.

### The superseded improvement, and why it was not enough

An earlier pass had already replaced the false justification on `execution/*`
with the modules' **measured** coverage, written into a `.coveragerc` comment,
and left the instruction "do not re-add a justification that names a test suite
without checking that the suite exists". That was right, and this builds on it.

Its limit is mechanical: a number in a comment has no pressure behind it. Five
of the six figures in that comment were already stale. The debt list does what
the comment cannot — the gate reads it, reports the current figure on every
commit that touches the module, and blocks with one instruction the moment one
reaches 80%.

### The numbers the lift made visible

Measured by `scripts/pre_commit_coverage.py` itself, so each figure is what the
gate will report rather than a number from a different kind of run.

| Module | Coverage |
|---|---:|
| `brokers/oanda_ws.py` | **100%** |
| `execution/engine.py` | 77% |
| `execution/_prom_metrics.py` | 75% |
| `brokers/oanda.py` | 73% |
| `brokers/interactive_brokers.py` | 69% |
| `core/middleware.py` | 67% |
| `execution/legacy.py`, `core/decision/HOPEFXDecisionEngine.py` | 66% |
| `brokers/oanda_stream.py` | 64% |
| `execution/hopefx_engine.py` | 63% |
| `core/page_routes.py` | 58% |
| `execution/fix_router.py` | 57% |
| `execution/fix_adapter.py` | 35% |
| `core/metrics.py` | 33% |
| `core/risk/advanced_engine.py` | 27% |
| `execution/execution.py` | 18% |
| `core/health.py` | **0%** |

Three things in that table were not visible from anywhere before.

**Fourteen of them were already recorded as debt.** They sat in
`COVERAGE_UNMEASURABLE.txt` *and* in `.coveragerc`'s omit at the same time, so
the entry could never be acted on: the gate cannot report a figure for a module
it may not measure, and the line described nothing. Belt and braces, where the
belt made the braces unreachable.

**One had earned its way off and nobody could tell.** `brokers/oanda_ws.py`
measures **100%** — excluded, recorded as debt, and fully covered. The gate
demanded its line be deleted the instant it could see it. An exclusion hides a
success exactly as well as it hides a failure, and this is the case that shows
it, because there was nothing to fix and no way to find out.

**`core/health.py` measures 0%.** A health endpoint with no test executing it,
excluded as "covered by API integration tests".

Only **two** needed a new line: `execution/engine.py` at 77% — three points off
the floor and the cheapest win in the file — and
`core/decision/HOPEFXDecisionEngine.py` at 66%, the central 5-phase pipeline
CLAUDE.md names as a key entry point.

### And a CI gate that has been measuring a curated subset

`.github/workflows/ci.yml` runs:

    coverage report --rcfile=.coveragerc --include="execution/*" --fail-under=80

The omit applies at collection, so the coverage data had no rows for
`execution/execution.py`, `hopefx_engine.py`, `fix_adapter.py`, `fix_router.py`,
`legacy.py`, `_prom_metrics.py` or `engine.py` — most of the package.
**"execution/ ≥ 80%" was a true statement about whatever was left.**

This is the same defect an earlier pass already fixed for `risk/`, and the test
that pins it (`test_the_risk_core_is_measured`) exists because of that fix. For
`risk/` it worked out — those files measure 82–89%. For `execution/` it does
not: the package's real figures are the table above.

**Not decided here.** Changing the floor on a money-path gate is the owner's
call, and the options — ratchet it to today's measured number, hold at 80 and
accept red CI, or scope it to a named list — trade differently. Filed. What is
not optional is that the number changed, and it is visible rather than quiet.

---

## §E50 — §A35 confirmed, and the audit chain does not cover who did what (2026-09-10)

The filed claim was that a superadmin action taken during an audit-storage
outage leaves a chain that still verifies clean. Confirmed by execution, and it
is four defects rather than one — plus a fifth found on the way that is more
serious than the item this started from.

### 1. `verify_integrity()` verifies its own memory

It walks `self.records`, the in-memory list. A record whose write failed is
still in that list, so the chain verifies clean over records the file does not
contain — and the file is the only artefact anyone outside the process can
inspect. A check that reads its own memory cannot disagree with itself (F176).

`verify_persisted_integrity()` reads the log file. It returns True, False, or
**None when there is nothing to verify** — an empty or absent log is not a
verified one, and reporting it as True is how an outage becomes a clean bill of
health (Rule 2).

### 2. The async write's exception was discarded

`_persist_record` scheduled `_async_write` with
`add_done_callback(lambda _: None)` — a callback that throws the result away,
exceptions included. Under FastAPI there IS a running loop, so **this is the
path production takes.**

Not *silent*, precisely, and the first draft of this section said it was:
asyncio emits "Task exception was never retrieved" when the task is
garbage-collected. That is not a substitute — it arrives at an unpredictable
time, from the `asyncio` logger, naming no record, no actor and no action. The
callback now retrieves the result and reports the loss **with the record's
identity**, which is what an operator needs to reconcile the gap.

### 3. `mkdir` sat outside the try that guarded the write

An unwritable log location raised `FileNotFoundError` straight into `append()`,
so the audit write could **crash the superadmin action it was recording** —
while an ordinary write failure two lines later was swallowed. One fault, two
opposite behaviours, neither designed. Both now report through one path and
neither raises into the caller.

### 4. The sync and async paths reported differently

Unified on `_report_lost_record`, so the message shape does not depend on
whether an event loop happened to be running.

### 5. The chain does not cover `actor`, `action`, `level` or `category`

Found because a test that tampered with `actor` in the persisted log **still
verified clean**. `_calculate_hash` hashes exactly four things:

    {"seq", "prev_hash", "timestamp", "data_hash"}

The payload is protected. **The attribution is not.** Rewriting who performed an
action, or what the action was, leaves a log both verifiers pass.

This is the SEC/CFTC trade-reporting chain, and "who did what" is the entire
point of the artefact. It is the most serious finding in this sequence, and it
is **pinned as observed, not fixed**: widening the hash input invalidates every
record already written, so it needs a versioned record format and a decision
about existing logs — a change to a compliance artefact, not a bug fix. Filed,
with a recommendation.

`tests/unit/test_audit_persistence_failures_are_visible.py` parametrises all
four fields, tampers with each, and asserts verification still returns True.
When the fix lands, that test flips to asserting detection.

### One harness bug of my own, the third of this shape

The async test passed before the fix. It matched asyncio's GC warning, whose
traceback repr contains the path `compliance/auditor.py` — so a naive
`"audit" in message` check found it and proved nothing. The assertion now
requires a record from the `compliance.auditor` logger itself, and that the
message names the lost record. Same family as the `_redis_sync` fixture (§E46)
and the global-count assertion (§E47): a search that can match something other
than what you meant is not a measurement.

---

## §E51 — The production-readiness script said "ready" without checking, and "not ready" without cause (2026-09-10)

Reached from §E49's `execution/` measurement: `execution/execution.py` measures
17.75% and has **no production importer**, so it looked like a quarantine
candidate. Tracing who touches it led to
`scripts/e2e_production_validation.py`, whose 22 checks stand behind the
sentence *"All critical checks passed. System is production-ready."* and none
of which was tested.

### Two checks named an import they never performed

**"Execution: ExecutionEngine imports cleanly, no forbidden imports"** read
`execution/execution.py` as TEXT and imported nothing. `ExecutionEngine` is in
`execution/engine.py` — a different file the check never opened. So it screened
a module with no production importer while the class in its own title went
unchecked, and "imports cleanly" was tested by nothing. It also checked exactly
one forbidden pattern where the neighbouring checks test seven and nine.

**"API: data_layer router importable, no forbidden imports"** did the
forbidden-import half properly and never imported the router.

Both now do what their names promise: import first, then screen the file that
defines what they imported. Neither is loosened — both still fail on a
forbidden import, and now also on an import error, which is what they always
claimed to catch.

### And it was failing on a rule two other gates contradict

Run by hand, the script reported a CRITICAL violation and printed "Fix before
deploying":

    core/startup_factories.py: from data_layer.feeds.

`data_layer.feeds.*` is **public**. CLAUDE.md line 114 says so, ADR 0013 says
so, and `scripts/ci/gate_g_import_discipline.py` — the gate that actually runs
in pre-commit — holds `"feeds"` in `DATA_LAYER_PUBLIC`. Three sources against
one script, and the script is the one not wired into CI, so the disagreement
was invisible until someone ran it.

The import it flagged is legitimate and predates this work (`4ad538e`). The
script's list was stricter than the documented boundary. It is aligned now, and
a test fails if the two lists diverge again — because two gates enforcing one
boundary must not disagree about where it is, and *a detector that cries wolf
trains its readers to ignore it*, which is a warning this repository already
wrote down in `compliance/auditor.py` about this exact failure mode.

**After: 21 checks recorded, 0 failures.**

### The script is not run in CI

`grep` over `.github/` and `Makefile` finds nothing. All 22 checks are
advisory, which is how a check could name the wrong file, and a rule could
contradict pre-commit, for as long as either has existed. Wiring it in is a
decision about build time and about what should block a deploy — filed, not
taken.

### Three of my own filtering mistakes, in one investigation

Worth recording together, because they are one habit:

* I nearly reported `validate_environment` as having no production caller —
  `head -6` had cut `app.py` out of the results (§E50 context).
* An AST sweep flagged three checks as asserting nothing. All three are
  genuine: `__import__(m)` raises, and `raise AssertionError` is not an
  `assert` node. My detector counted the wrong things, and only reading the
  bodies caught it.
* Hunting the failing check, I filtered the run output with `grep -vE "INFO"` —
  and `record()` logs failures at INFO, so I removed exactly the line I was
  looking for.

Each was a search that could match something other than what I meant. The same
shape as the harness bugs in §E46, §E47 and §E50, on the reading side rather
than the writing side.

---

## §E52 — The AI OS specification, mapped against what this repository actually enforces (2026-09-10)

The owner supplied `MASTER_AI_OPERATING_SYSTEM_CCAM_DERIVED_ARCHITECTURE_SPECIFICATION_v1.0`
with a directive that begins *"Do not treat this document as permission to
replace, bypass, weaken, disable, or ignore anything that already exists"* and
*"First inspect and understand the existing system."*

So the first deliverable is not code. It is an answer to the question the
directive implies: **of the 26 invariants the specification names in its §30,
which does this platform already enforce?**

### The answer

    26 AOS invariants · 3 covered · 13 partial · 10 absent

*As first mapped on 2026-09-10 this read `2 covered ... 11 absent`. The figure
above is the current one, because this is a living document and the check in
`scripts/doc_metrics.py` measures it against the register on every commit.
AOS-EVID-028 moved from absent to covered on 2026-09-11 — see §E54.*

`docs/ai/specs/AOS_INVARIANT_REGISTER.toml` carries the map, one row per
invariant, each naming the predicates or mechanism that enforce it and — where
they do not — stating the gap. The two covered are `AOS-GOV-070` (No
Self-Elevation → `verify_no_privilege_escalation`) and `AOS-API-001`
(executable/API/documentation reconciliation → the API doc generator plus the
test that fails when the committed file drifts).

**This is a map, not a plan.** Several of the eleven absent rows are meaningful
only once the AI OS has planes this repository does not have. Which of them to
build is the owner's call, and nothing here presumes it.

### Why it is a TOML file with a checker, and not a document

A prose conformance map is a claim that was true once. Rename a predicate and
every row naming it keeps reading as coverage; the map cannot tell you it has
gone stale. That is F255 — a checker that reads prose is not reading code.

`scripts/aos_conformance.py` resolves every claim instead of reading it: each
name in `predicates` must exist in `invariants.registry.discover_predicates()`,
each path in `mechanism` must exist on disk, `COVERED` must carry one of those
two, `ABSENT` may carry neither, and `PARTIAL`/`ABSENT` must say what is
missing. It runs in `pre-commit`, triggered by the register, by the script, and
by **any change under `invariants/`** — because a rename there is precisely
what turns a row into fiction.

Its positive control refuses (exit 2, not a finding) when the registry
discovers no predicates at all. Without it, an `invariants` package that failed
to import would make every row resolve identically and the run would still
print a total.

### One row was already fiction, and the checker is why it is not now

`AOS-API-001` was written as `COVERED` naming `verify_platform_identity`. That
predicate is real — and it asserts the platform gained no *undeclared
capabilities*, which is a different claim entirely from API/documentation
reconciliation. It would have resolved green forever while describing something
the repository does not do. The row now names the generator and the test that
actually enforce it, and the register grew a `mechanism` field so a control
enforced by a script rather than a predicate can be stated honestly instead of
borrowing a predicate that fits the schema.

### `verify_dual_control` is two different predicates

Mapping the register surfaced a name collision. `invariants/assurance.py`
defines `verify_dual_control(action_sensitive, distinct_approvers)` under **No
Loss Of Human Control**; `invariants/governance.py` defines
`verify_dual_control(approvals, required)` under **No Unauthorized Capital
Movement**. Different signatures, different constitutional rules, same name.

Python keeps them apart by module. A register naming predicates as bare strings
cannot, and the first version of the checker flattened the inventory into a set
— which is also why it reported 338 predicates where CLAUDE.md and the
invariants skill both say 339. Both numbers were right: 339 definitions, 338
distinct names.

The inventory is now kept as `name -> [modules]`. A bare name defined in more
than one module resolves, but is reported as a note asking the row to qualify
it; a qualified name (`governance.verify_dual_control`) is checked against that
module. Neither predicate has a production caller today — only tests — so
nothing is mis-wired. It is a trap for the next person who greps.

### Documentation that can no longer drift

`scripts/doc_metrics.py` now measures the four AOS figures, so a document
stating them is checked against the register on every commit. Each pattern
requires the separator the report line uses (`3 covered · 13 partial`), because
"covered", "partial" and "absent" are ordinary English — the same narrowing
`gates_total` needed after it read "8 gates left" as a total.

Adding the gate took the evidence ledger 27 → 28, which made six lines of this
document stale in the same commit. Those are corrected. Three tests in
`test_doc_metrics.py` were also filtering drift by metric across the whole
repository rather than by their own fixture, so real drift anywhere made them
red under a name that said the opposite; they are scoped now.

---

## §E53 — CI has enforced nothing for two days, and the coverage gate has 683 unreported findings (2026-09-11)

Both found while trying to land an ordinary documentation commit. Neither was
caused by it. Both are the same shape as every other finding in this programme:
a control that exists, is configured correctly, and does not run.

### CI is not running. It has not run for at least 30 consecutive pushes.

Runs 4357–4386, spanning 2026-09-09 09:18 to 2026-09-10 02:07, every one
`failure`, with durations of **3 to 72 seconds**.

In run `34428186962` all seven jobs — `pre-commit`, `test (3.11)`,
`test (3.12)`, `typecheck`, `frontend`, `build-cpp-shim`, `dependency-scan` —
were created at `02:07:20` and completed at `02:07:22`. Two seconds, all of
them, simultaneously. Their logs return **HTTP 404**.

A job that fails on a test produces logs. A job with no logs that ends two
seconds after creation never started. Seven of them ending together is not seven
failures; it is one refusal upstream of all of them — the signature of GitHub
Actions being disabled for the repository or an account spending limit being
reached.

**This is owner-actionable and nothing in the repository can fix it.** It needs
the repository's Actions settings and the account's billing checked.

The consequence is the part that matters. `.github/workflows/ci.yml` runs
`pre-commit/action@v3.0.1`, which defaults to `--all-files` — so CI is where the
*whole* gate set was supposed to run, as opposed to the staged subset a local
commit sees. For at least two days:

* the pre-commit gate set has enforced nothing in CI;
* the 3.11/3.12 test matrix has run nothing;
* typecheck, the frontend build and the dependency scan have run nothing.

Every "CI enforces this" sentence in these documents has been false for that
period. The gates themselves are fine — `pre-commit run` locally still passes
each one, and that is what has actually been holding the line.

### The per-module coverage gate has 683 findings it has never reported

Running `pre-commit run --all-files` locally — which took about 90 minutes,
because it invokes pytest once per module, roughly 400 times, two at a time —
produced:

| Finding | Count |
|---|---:|
| Modules in `docs/COVERAGE_UNMEASURABLE.txt` that now measure ≥ 80% and must leave the record | 156 |
| Modules where coverage could not be measured (the paired test does not import the module, or fails to collect) | 297 |
| Modules genuinely below the 80% floor | 230 |
| **Distinct modules involved** | **292** |

The gate is not broken. Its **scope** was never what the documentation implies.
The hook carries `pass_filenames: true`, so on a commit it measures only the
modules in that commit. The full sweep was CI's job, and CI is dead. So these
683 findings have been accumulating with nothing able to report them.

156 of them are *good news that the ratchet cannot record*: modules that
improved past the floor while their exclusion lines sit in
`COVERAGE_UNMEASURABLE.txt` claiming otherwise. An exclusion that no longer
describes anything is exactly how a ratchet quietly stops being one — the gate
says so in its own message, and no one has been able to hear it.

### Why this commit was not blocked by either

The change that surfaced them is markdown plus one test file: **zero production
Python**. Run as a real commit runs it, `pre-commit run` on the staged set
reports the coverage gate as `(no files to check)` and every other hook as
`Passed`. The 292 failing modules are ones this work never touched.

That attribution is by construction rather than by a clean-worktree baseline —
the counterfactual would cost another 90 minutes, and it is recorded here as not
run rather than implied.

---

## §E54 — Spatial intelligence starts with what it may not claim (2026-09-11)

The owner specified a Spatial Intelligence & World Creation system: a universal
3D builder, a construction brain, an interactive world model, a simulation
laboratory, a construction time machine, a video director, a multi-agent design
studio, a what-if laboratory, automatic design alternatives, reality-to-3D,
3D-to-reality documentation, spatial memory, a persistent digital twin, an
AR/VR layer and spatial voice interaction — integrated as a native AI OS
capability rather than a separate 3D feature.

And named one feature **absolutely essential**: *the AI should know what it does
not know.*

That one is built. The other fifteen are specified in
`docs/ai/specs/SPATIAL_INTELLIGENCE.md` with their status measured from the tree.

### Why that one first, and not the builder

A 3D system produces persuasive artifacts. A generated house looks built; a
generated car looks engineered; a solver returns a number to four decimals. Each
is a value nothing verified, presented as though something had — the defect
class this programme has spent itself removing, now with the widest blast radius
it has had, because the output is *beautiful* and beauty reads as correctness.

Build the renderer first and every later safety rule is retrofitted onto a
system whose outputs already look authoritative. Build the ladder first and
every capability that lands has to say what rung it earned.

### The ladder, and the four rules that are enforced

`NOT_ASSESSED → VISUALIZED → PROCEDURALLY_GENERATED → ESTIMATED → SIMULATED →
VALIDATED → EXTERNALLY_VERIFIED → HUMAN_APPROVED`

1. **A claim rises only on evidence supporting that rung.** A finite-element run
   is evidence for `SIMULATED`; it is not evidence anyone approved anything.
2. **A claim may always fall, with no evidence.** Learning something is worse
   must never need a permit, or the system sits on stale assurance.
3. **A composite is the MINIMUM of its parts.** Not the mean, not the best. This
   single rule is what stops "the render finished" becoming "the house is safe
   to build".
4. **Readiness is never inferred from assurance.** `EXTERNALLY_VERIFIED` is not
   approval; approval is a named person on every required aspect.

Plus the floor: an aspect nobody assessed is `NOT_ASSESSED` **and appears in the
report**. Never omitted — a missing row reads as a row with nothing wrong, so a
report that drops the unexamined gets shorter as the work gets sloppier. Rule 2
of this codebase, applied where the unmeasured thing is whether a building
stands up.

So the system cannot say "this house is safe to build". It says:

    3D design                        PROCEDURALLY_GENERATED
    Structural simulation            SIMULATED
    Building-code compliance         NOT_ASSESSED
    Professional engineering review  NOT_ASSESSED     required
    Overall                          NOT_ASSESSED     (rule 3)
    Construction readiness           NOT READY        blocking: 2 aspects

### It is enforced, not merely available

`ai/spatial/assurance.py` holds the rules at the construction site.
`invariants/spatial.py` holds five predicates at the boundary where a spatial
result crosses into a decision — because a module holding correct rules that no
decision path consults is F176, and it would be an expensive instance.

Predicate count **339 → 344**. Both constitutional rules used are pre-existing
(*No Unverified AI Decision*, *No Silent Failure*); inventing a new one is a
governance decision, not a code change.

### This closes an AOS gap that was open

**AOS-EVID-028, Epistemic Monotonicity Requires Evidence** — recorded ABSENT
when the register was built on 2026-09-10 — is now COVERED by
`spatial.verify_epistemic_monotonicity`. AOS-STATE-019 gained two predicates.

    26 AOS invariants · 3 covered · 13 partial · 10 absent

The spatial work needed that invariant first and hardest, which is why it is the
one that got built. The register updated itself the moment the predicates
landed, and `doc_metrics` then blocked on two lines of this document still
stating the old figure — the ratchet doing exactly its job.

### Three capabilities are already partly real, and set the standard

They were found by inspection before any design, and their discipline is why
this extends them rather than starting beside them:

* `frontend/src/hub/spatial.ts` — *"Position is measured or it is not claimed."*
  No `DOMRect`, no position; it says "the risk table" rather than inventing a
  corner.
* `frontend/src/hub/sceneGraph.ts` — refusals rather than silent nothings; an
  unknown id throws, and a containment cycle is refused at the edge.
* `frontend/src/hub/surface3d.ts` — *"A hole is never interpolated."*
  `warrants3D` refuses more often than it accepts, and WebGL stays honestly
  unavailable rather than claimed.

### Evidence

32 tests, all red before the modules existed. Every rule proven able to fail by
mutating the implementation rather than a fixture: seven mutations of the ladder
(allow an unevidenced rise, ignore what evidence supports, make falling require
evidence, composite takes the best part, empty composite turns optimistic,
readiness settles for `SIMULATED`, unassessed aspects dropped from the report) —
each killed exactly the tests that describe it, and the restored baseline is
green. A further test asserts the registry actually discovers all five
predicates, because the naming convention *is* the registration mechanism.

### Not claimed

No solver, renderer, reconstruction pipeline or video encoder exists. Fifteen of
sixteen capabilities are `planned`, and the specification says so in a table
measured from the tree rather than aspired to.

---

## §E55 — The 3D builder begins with a graph, not a renderer (2026-09-11)

Capability #1, the Universal 3D Builder, started — and specifically its
*representation*, approved as the first slice ahead of geometry-first and
generator-first.

The reason is that every question the surrounding capabilities actually ask is a
graph question, and none of them needs triangles to be answered:

    "What is this connected to?"     connections_of
    "What happens if I remove it?"   removal_impact
    "In what order is it built?"     assembly_order
    "What does it take to build?"    bill_of_materials

The Construction Brain (#2), the Interactive World Model (#3), the Time Machine
(#5), the What-If Laboratory (#8) and the documentation generator (#11) all sit
on those four. Geometry attaches to a component later; a component cannot attach
to geometry retroactively without redoing the model, which is what decides the
order.

`ai/spatial/world.py`. Four capability rows moved from `planned` to `partial`,
and the specification says which half of each is real.

### A load path is a claim

`removal_impact` returns `PROCEDURALLY_GENERATED` and never more. The graph knows
a beam supports a floor because **somebody declared the connection** — an
assertion about a drawing, not a measurement of a building.

Enforced twice deliberately: the result carries its rung, and
`verify_structural_claim_requires_solver` refuses a republished claim at
`SIMULATED` or above with no solver run. A rule enforced only at its source is a
rule enforced by whoever remembers it, and *"the model says the floor stays up"*
becoming *"the floor stays up"* is the step that turns a drawing into a
demolition decision. Predicates **344 → 345**.

### Refusals taken from code that already works here

* **A support cycle is refused when the edge is added** — `ai/bus/graph.py`'s
  rule. A cycle found at traversal means a structure has already been ordered,
  costed or drawn on the assumption it was sound.
* **Only `SUPPORTS` is held acyclic.** Pipes and wiring legitimately loop; a ring
  main is not a structural impossibility, and refusing it would teach people to
  model plumbing as something else.
* **An unknown id raises** — `frontend/src/hub/sceneGraph.ts`'s rule. An empty
  list for a typo reads identically to one for a component that genuinely carries
  nothing. One is a misspelling, the other is a cantilever.
* **A component with a second support is not reported unsupported.** A warning
  that fires on every removal is one people switch off, and the second beam is
  the whole reason the floor is still up.

### Two tests were passing for the wrong reason, and the counterfactual found it

Nine mutations were run against the implementation. Seven killed the tests that
describe them. **Two survived**, and both were tests green for a reason other
than the one they named:

* *"a connection to an unknown component is refused"* used `SUPPORTS`. With the
  endpoint guard deleted the call still raised `UnknownComponent` — from the
  cycle check reaching `supports('ghost')`. Same exception, different rule, test
  none the wiser. It now uses `FEEDS`, which never reaches the cycle check, so
  only the endpoint guard can refuse it, and it additionally asserts no dangling
  edge was left behind.
* *"a non-structural cycle is allowed"* used a pure `FEEDS` loop. The detector
  only walks `SUPPORTS` edges, so that loop is invisible to it whether or not the
  check is kind-scoped — the test could not distinguish the two. A second test
  now uses a **mixed** loop (a riser supports a pump that feeds back into it),
  which is the case that actually discriminates.

Re-run after the fixes, both mutations die. This is the third time in this
programme that a green test has turned out to be measuring something other than
its name, and the second time the counterfactual is what caught it — reading the
tests would not have.

### Evidence

41 tests for the world model and its invariant, all red before the modules
existed. **100% statement and branch coverage** across `ai/spatial/assurance.py`,
`ai/spatial/world.py` and `invariants/spatial.py` — 61 tests over the three.
Nine mutations, each killing exactly the tests that describe it, baseline
restored green. The diamond test exists because the cycle detector's visited-set
branch was the one line coverage could not reach: without it the detector
re-walks a subtree per path, which is exponential on a real structure.

### Not claimed

No geometry, no renderer, no solver, no generation from text, sketch, image,
voice or CAD. The builder can describe a structure and answer questions about it;
it cannot draw one, and the specification's status table says so.

---

## §E56 — The Time Machine, and the rule it protects that was untested (2026-09-11)

Capability #5, the Construction Time Machine, on top of `assembly_order()`.
`ai/spatial/timeline.py`: step through a build, inspect any stage, branch from
any point. Capability #8's branching comes with it, because *"what if this
building were twice as tall"* is a branch taken at a stage and compared against
the trunk, and the branch has to know what it diverged from.

Five rules:

1. **A Construction snapshots its world.** `World` is mutable — `add` and
   `connect` are public and are how anything gets built. A live reference would
   let history rewrite itself: edit the world, and the build recorded an hour ago
   silently becomes a different build, with no diff and no event.
2. **A stage is `PROCEDURALLY_GENERATED`.** A sequence derived from declared
   dependencies, not an observation of anybody building anything.
3. **`at()` out of range raises.** Clamping answers "step 999" with a picture of
   a finished building.
4. **A connection is live only when both ends exist.** Otherwise stage 1 shows a
   beam bolted to a floor that has not been built. Real in the design from the
   moment it is declared; real in the build only once both ends are standing.
5. **A branch never mutates its trunk**, and records where it diverged.

### Rule 1 was the headline rule and the tests did not cover it

Seven mutations. Six killed their tests. The survivor was **replacing the
snapshot with a live reference** — the single thing the module exists to
prevent — and all fourteen tests stayed green.

The test asserted on `stages()`, which is computed once in `__init__` and frozen
either way, so it is identical whether the world is copied or referenced. Adding
a component afterwards did not discriminate either: `at()` filters connections to
what is standing, and a newly added component never is.

What discriminates is a connection between two components that are **already
installed**. It passes the standing filter, so with a live reference it appears
in a state recorded before it was drawn. Two tests now cover it — that one, and a
direct `Construction(w).world is not w`. Re-run, the mutation dies.

That is the fourth green test in this programme found to be measuring something
other than its name, and the third caught by mutation rather than by reading.
The pattern is consistent enough to state plainly: **a test written from the
same understanding that produced the code inherits its blind spots.** Only
breaking the code finds them.

### A smaller one, worth recording

`test_a_branch_rebuilt_after_an_edit_reflects_it` was written asking for step 5
of a three-step build. `StageOutOfRange` refused it — rule 3 catching an
off-by-three in the test that was written to exercise rule 5. A guard that fires
on its author the same hour it is written is a good sign about the guard.

### Evidence

16 Time Machine tests, all red before the module existed. Seven mutations, each
now killing exactly the tests that describe it. **100% statement and branch
coverage across the whole `ai/spatial` package and `invariants/spatial.py`** —
79 tests over four modules, 252 statements, 76 branches, none missed.

`World` gained one public accessor, `component(id)`, added test-first and holding
the same rule as every other lookup there: an unknown id raises rather than
returning `None`.

### Not claimed

No playback UI, no speed control, no solver behind the branches. The Time Machine
can produce the sequence and the state at any point in it; nothing animates it,
and the What-If Laboratory can branch but cannot yet tell you what the branch
would cost or whether it would stand.

---

## §E57 — The simulation frame ships before the physics, and the comparison refuses to rank (2026-09-11)

The owner asked for the previous entry's "not claimed" list to be closed: no
playback UI, no speed control, no solver, and a What-If Laboratory that could
branch but could not say what a branch would cost or whether it would stand.

Three of the four are now addressed. The UI is not, and deliberately: a major
UI/UX surface needs `flow-prototype`'s approval gate before production
implementation, and that gate is not something to skip because the backend is
ready.

### The Simulation Laboratory is a frame with nothing in it, on purpose

`ai/spatial/simulation.py` can name nine domains and refuse all nine. That is
the useful half, and it shipped first for a specific reason.

A laboratory that always returns a number is the most dangerous component in
this system. `removal_impact` is safe because it is labelled
`PROCEDURALLY_GENERATED` and its graph is visible. **A simulation result looks
like physics.** Answer a structural question with a thermal solver, or with a
plausible default because nothing was registered, and the answer is
indistinguishable from one a finite-element run produced.

| Situation | Result |
|---|---|
| No solver for the domain | `NOT_ASSESSED`, naming the domain |
| Solver declines this model | `NOT_ASSESSED` — never fall back to another domain |
| Solver raises | `NOT_ASSESSED`, carrying the failure, still naming the solver |
| Solver fails deciding applicability | `NOT_ASSESSED` — a solver that cannot decide has not decided |
| Solver claims `VALIDATED` or above | clamped to `SIMULATED` |
| Solver claims `ESTIMATED` | kept — the clamp is a ceiling, not a floor |
| Two solvers for one domain | refused at registration |

**No solver is registered.** When a real one is adapted in, every rule above is
already standing between it and a build decision, rather than being retrofitted
around a component that has been returning numbers for a month.

### The comparison refuses to rank, and the refusal is the deliverable

`ai/spatial/compare.py` gives component and bill-of-materials deltas at
`PROCEDURALLY_GENERATED` — facts about two graphs, cheap and always available.

`better_on()` is the other half, and it mostly says no. It refuses unless **both**
sides carry a finding at `SIMULATED` or better. The case that matters is one side
simulated and the other silent: a table showing `0.62` against a blank cell reads
as though the blank lost. **A side with no finding has not scored badly; it has
not been measured.**

So the return is `(None, reason)`, and the reason is the value: *"the branch was
not assessed for structural"* is actionable; *"no significant difference"* is a
lie that closes the question. A tie — both measured, both equal — is reported as
a tie, because that is a real answer.

Non-finite values refuse rather than compare: `NaN < x` is `False` in both
directions, so an unguarded ranking hands the win to whichever side is checked
second.

### Playback is a state machine, not an animation

`ai/spatial/playback.py`: pause, resume, seek, speed. No timers, no threads, no
event loop — `advance(dt)` is a pure function of state and elapsed seconds, so
every rule is testable without a clock and a UI can drive it from
`requestAnimationFrame` without the logic ending up inside a component.

One apparent contradiction, stated so it does not read as an inconsistency:
`Construction.at()` **raises** out of range while playback **clamps**. They are
different questions. "Step 999" of a four-step build is nonsense and deserves a
refusal; running past the end is what happens every time a video finishes. The
clamp sets `finished` and stops `playing`, because a player silently sitting on
the last frame is indistinguishable from one that has stalled.

Speed is positive and finite. Zero is pause, and pause has its own flag —
conflating them lets `playing` and `speed == 0` disagree about what the player is
doing. Fractional progress accumulates rather than truncating per call, or a
caller ticking at 60fps would never move at all.

### Evidence

51 new tests, all red before their modules existed. **18 mutations across the
three modules, every one killed** — including the ones that matter most: a
no-solver domain returning an estimate, a fall-back to another domain's solver,
an unclamped self-certification, ranking with a finding on only one side, ranking
`ESTIMATED` against `SIMULATED`, comparing `NaN`, and a playback that reaches the
end silently. None survived.

**100% statement and branch coverage across all seven spatial modules** —
`ai/spatial/{assurance,compare,playback,simulation,timeline,world}.py` and
`invariants/spatial.py`. 413 statements, 106 branches, none missed, 130 tests.

Coverage found one real gap while it was at it: the handler for a solver that
raises *while deciding applicability* was written and never tested — an untested
handler on a safety path, which is the `hopefx-dead-controls` shape. It has a
test now. The two remaining partial branches were `Protocol` method stubs, whose
bodies are structural declarations that never execute; they are marked
`# pragma: no cover` with the reason, rather than given a test that would only
exercise `...`.

### Still not claimed

No solver of any kind. No geometry, no renderer, no reconstruction, no video. No
UI — the playback state machine has no front end, and building one crosses into
`flow-prototype`'s approval gate. The What-If Laboratory can branch, diff and
refuse to rank; it cannot tell you whether a building stands, because nothing in
this repository can compute that.

---

## §E58 — The spatial status table stops being prose (2026-09-11)

`SPATIAL_INTELLIGENCE.md` carried sixteen capabilities and a status for each.
That table is the answer to *"what can this system actually do"*, which makes it
the most load-bearing prose in the specification and the worst thing to leave as
prose: rename a module and the row keeps saying `partial` while pointing at a
file that is gone.

Same problem `AOS_INVARIANT_REGISTER.toml` had, solved the same way.
`docs/ai/specs/SPATIAL_CAPABILITIES.toml` holds the statuses,
`scripts/spatial_capabilities.py` **resolves** every claim — a module that
imports, an attribute that exists (dotted, so `World.assembly_order` names the
method rather than vaguely pointing at a class), a path on disk — and it runs in
`pre-commit`, triggered by the register, the script, **and any change under
`ai/spatial/` or `invariants/spatial.py`**.

    16 spatial capabilities · 1 built · 9 partial · 6 planned
    29 evidence locators, all resolving

### Why it is not in `ai/hub/capabilities.py`

That was the first instinct, and it was wrong. The hub registry's `section` field
is traceability to the **AI Hub specification's** §4–§27 — its own docstring says
"the specification section that asks for it. Traceability both ways." The spatial
capabilities come from a different specification, so giving them AI Hub section
numbers would corrupt the one property that registry exists to hold. A second
register, checked the same way, keeps both honest.

Note also that `ai/hub/capabilities.py` already has `spatial.*` rows —
`scene_model`, `panel_registry`, `viewport_awareness` — and they are the
**frontend** spatial layer, screen geometry rather than 3D. Two different
subjects sharing a word, which is worth knowing before someone greps.

### `planned` may name nothing

Taken from the hub registry, which learned it the hard way: *"a pointer to
nothing reads as progress"*. A planned row citing a module that exists for other
reasons is how a roadmap starts describing work nobody did. Six rows carry no
evidence and are required to carry none.

### Two mutations survived, and both were real missing tests

Nine rules, neutralised one at a time. Seven killed their tests. **Two survived**:
`partial` with no evidence, and `planned` with no gap. Both were genuine gaps —
only their `built` and `partial` counterparts had been written, so half of each
pair was enforced by nothing. Both have tests now and both mutations die.

That is the fifth time in this programme a mutation has found a green suite
measuring less than it appeared to, and the fourth found by mutation rather than
reading.

### And the new metric cried wolf immediately

Ratcheting the three spatial figures into `doc_metrics.py` produced an instant
false positive: `(\d+)\s+planned\s*·` matched the **AI Hub registry's** own report
line — `233 rows · 233 live · 0 staged · 0 planned` — and called a true sentence
drift.

Exactly the trap `gates_total` fell into with "8 gates left", and the same fix:
narrow the pattern rather than the writing. The spatial patterns now anchor to
their neighbour (`capabilities · N built`, `partial · N planned`) instead of a
trailing separator, and a regression test feeds the registry's real line in and
asserts it is *not* read as a spatial figure.

A check that cries wolf gets switched off, which would have cost more than the
drift it was built to catch.

### Then the two ratchets collided with each other

Writing *this entry* produced a second false positive immediately. The AOS
pattern `(\d+)\s+partial\s*·` matched the spatial register's own line —
`16 spatial capabilities · 1 built · 9 partial · 6 planned` — and reported
`aos_partial=9, measured 13`.

Two ratchets built weeks apart, colliding on one English word. The AOS patterns
are now neighbour-anchored too (`invariants · N covered`, `covered · N partial`,
`partial · N absent`), and the spatial line is pinned as a case that must *not*
be read as an AOS figure.

A third defect fell out of fixing it: the parametrised test that proves a stale
figure is caught bumped the **first** number in its sample line. With
neighbour-anchored patterns the captured number is the second, so the "stale"
sample was still correct and the test failed while the code was right. The helper
now uses the claim's own regex to find the number it captures. A test that
constructs its own fixture by assumption inherits the assumption.

### Evidence

21 tests for the checker, all red before it existed. Nine mutations, each now
killing exactly the tests that describe it. Gate ledger **28 → 29 gates, 29
proven able to fail, 0 unproven** — the new gate shipped with its injection
evidence, and that increment made six lines of this document stale in the same
commit, which `doc_metrics` blocked on.

`docs_registry` also blocked, on a registry row I added for the TOML. Investigated
rather than patched: `DOC_GLOBS` is `docs/**/*.md`, `docs/**/*.txt` and `*.md`, so
a `.toml` entry can only ever read as dangling — and neither
`AOS_INVARIANT_REGISTER.toml` nor `GATE_EVIDENCE.toml` is registered either. The
row was the anomaly, not the file. Removed.
