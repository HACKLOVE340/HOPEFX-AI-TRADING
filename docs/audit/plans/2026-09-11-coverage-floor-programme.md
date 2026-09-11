# Coverage Floor Programme — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: use `executing-plans` to work this
> plan task by task. Steps use checkbox (`- [ ]`) syntax for tracking.
> `flow-by-flow` picks mode and depth for each task, as CLAUDE.md requires.

**Goal:** Take the 259 modules still recorded below the 80% per-module coverage
floor to the floor or to a stated decision, money path first, so
`docs/COVERAGE_UNMEASURABLE.txt` shrinks to the set that genuinely cannot meet it.

**Architecture:** The record is a ratchet, not an allowlist. `_judge` in
`scripts/pre_commit_coverage.py` blocks a recorded module that reaches the floor
with one instruction — delete the line — so every module raised here leaves the
record in the same commit that raises it. Work is ordered by consequence rather
than by cost, because this is a money-moving system: a test written for
`risk/` buys more than three written for `charting/`.

**Tech Stack:** Python 3.12 (CI also tests 3.11), pytest, pytest-cov,
`unittest.mock.create_autospec`, pre-commit (ruff, bandit, detect-secrets).

**Spec:** none. This plan argues from measurement: every figure below comes from
`scripts/pre_commit_coverage.py` run with the per-invocation coverage isolation
added in `0f5e7eb4`. Re-measure rather than trusting these numbers if the tree
has moved — see Task 1.

---

## Global Constraints

Copied verbatim from `CLAUDE.md`; they apply to every task below.

- **Python 3.12 is the production target.** CI tests 3.11 and 3.12.
- **Never weaken a risk gate, kill switch, or staleness/drift check without
  explicit instruction.** Raising a log level or tightening a check is not
  weakening; lowering a threshold to match code is.
- **Every fix ships with a test that fails on the pre-fix tree.** Run it against
  the old code — `git stash`, run, `git stash pop` — and watch it fail.
- **Prove by execution, not by reading.** Reproduce before fixing, re-run after.
- **Before committing:** `ruff check .` clean, touched files compile
  (`python -m py_compile`), `pre-commit run` on the staged files. Never
  `--no-verify`.
- **No secrets, no credentials, no `test-results.xml`.**
- **The coverage record may only shrink.** A module that reaches the floor has
  its line deleted in the same commit.
- **Canonical dirs:** `backtesting/` not `backtest/`; `strategies/` not
  `strategy/`; WebSocket work in `api/ws_live.py`; never create a top-level
  `websocket/` package.

### Measurement rules (learned the hard way — see `0f5e7eb4`)

- A figure from this gate is the module against **its paired test files only**.
  It is **not** the module's suite-wide coverage and the two must never be
  compared. `risk/manager.py` reads 43% here and 89.65% suite-wide; both correct.
- **Always confirm a removal with the real gate** before committing it:
  `python scripts/pre_commit_coverage.py <module>` must exit 0. Two wrong
  removals were caught this way and only this way.
- Coverage measurement can vary run to run. `database/async_connection.py` reads
  78.70% and 80.14% on different runs and straddles the floor. Treat a module
  within ±2 points of 80 as unsettled and measure it twice.

---

## Current state (measured 2026-09-11)

```
record: 263 entries
  259  below the floor      <- this plan
    4  genuinely unmeasurable
```

Distribution of the 259, by consequence and by distance from the floor:

| Group | 0% | <25 | 25–49 | 50–69 | 70–79 | total |
|---|---:|---:|---:|---:|---:|---:|
| Money path (`risk` `execution` `brokers` `ml` `core` `compliance` `payments` `monetization` `portfolio` `kill_switch`) | 8 | 8 | 13 | 24 | 15 | **68** |
| Everything else | 62 | 30 | 48 | 35 | 16 | **191** |

**Worked example, already landed:** `c007dad8` took `execution/execution.py`
from 17.75% to 82% with 59 tests and four killed mutations, and removed its line.
Task 3's recipe is that commit, generalised.

---

## File structure

| Path | Responsibility |
|---|---|
| `docs/COVERAGE_UNMEASURABLE.txt` | The ratchet. Shrinks only. One line deleted per module raised. |
| `tests/unit/test_<parent>_<name>.py` | Where a new suite goes so the gate pairs it. See naming rule in Task 3. |
| `scripts/pre_commit_coverage.py` | The gate. Do not edit to make a module pass. |
| `docs/ai/MASTER_OUTSTANDING.md` | Gets one §E entry per landed batch. |

---

## Task 0: Decisions only the owner can make

These block or shape work below. None is an engineering question. Do not guess
any of them; each is stated with what it costs either way.

- [ ] **0a. `notify_fill`'s swallowed failures** — `execution/execution.py:596`
      and `:606`

Both handlers log at `logger.debug`, which is off in production:

```python
except (RuntimeError, TypeError) as exc:
    logger.debug("notify_fill Redis update failed: %s", exc)
```

`notify_fill` runs on every confirmed fill to keep the Redis cache and the replay
engine consistent with what actually executed. A failure in either leaves them
inconsistent and tells nobody — `hopefx-dead-controls` sub-shape 4, the F248
shape, on the money path.

*Recommended:* raise both to `logger.error` naming what did not happen. It cannot
weaken anything — the handler still swallows, so the engine loop is unaffected —
and it is the same remedy F248 took. **Cost of not doing it:** a fill whose cache
or replay write fails stays invisible. Task 2 implements this on a yes.

- [ ] **0b. The omit-list sanity floor** —
      `tests/unit/test_coverage_gate_states_its_scope.py:65`

`assert report["omitted_from_source_loc"] > 1_000` measures **806**. Red since
2026-09-10, caused by `7af5af33` cutting the omit list from 23 exclusions to 4 —
a real improvement that fell through a floor calibrated against the old list.

*Recommended:* re-express the assertion to prove the omit list is **counted**
rather than pinning its size (e.g. assert it equals the sum of the omitted
modules the report enumerates). **Do not simply lower 1_000 to 800** — that is
weakening a check to match the code, which the Global Constraints forbid.
*Alternative:* leave it red as honest signal. Task 4 implements the re-expression
on a yes.

- [ ] **0c. GitHub Actions assigns no runners**

`ci.yml`'s last real run on this branch was #4386 (2026-09-10 02:07). Every push
since produces a zero-job `startup_failure`. All 19 workflow files parse cleanly;
`main` is in the same state; the repository diagnosed the identical signature in
`6591f74` as "an account-level Actions billing matter, not a code one".

*Needed:* check **Settings → Actions → General** (enabled?) and the account's
**billing / spending limit**. Nothing in the repository can fix this. Until it is
fixed, `ci.yml`'s `pre-commit --all-files` — the only thing that runs the WHOLE
gate set — has not run, and every "CI enforces this" sentence in these documents
is false.

---

## Task 1: Re-measure before trusting any number here

**Files:** none modified. Produces `/tmp/…/measured.json` for Tasks 3–6.

**Interfaces:**
- Produces: a JSON list of `{"module": str, "pct": float|None, "state": "DEBT"|"STALE"|"UNMEASURABLE"}`
  consumed by every batch task below.

- [ ] **Step 1: Run the gate over every recorded entry**

```bash
cd /home/user/HOPEFX-AI-TRADING
grep -vE '^\s*(#|$)' docs/COVERAGE_UNMEASURABLE.txt > /tmp/recorded.txt
.venv/bin/python scripts/pre_commit_coverage.py $(tr '\n' ' ' < /tmp/recorded.txt) > /tmp/regate.log 2>&1
```

Expected: roughly 40 minutes. Safe to run in parallel since `0f5e7eb4`; if you
parallelise, keep the isolation and cross-check a sample against a sequential run.

- [ ] **Step 2: Split the log into the three verdicts**

```bash
grep -c 'must leave the record' /tmp/regate.log   # stale: delete these lines now
grep -c 'DEBT'                  /tmp/regate.log   # below floor or unmeasurable
```

- [ ] **Step 3: Delete any stale lines and confirm each with the real gate**

For every module the log says "must leave the record":

```bash
sed -i '\#^<module>$#d' docs/COVERAGE_UNMEASURABLE.txt
.venv/bin/python scripts/pre_commit_coverage.py <module>   # must print OK and exit 0
```

A module that does **not** exit 0 goes straight back into the record. This step
caught `backtest/transaction_costs.py` (harness said ≥80, gate said 0%) and
`database/async_connection.py` (80.14 vs 78.70).

- [ ] **Step 4: Commit**

```bash
git add docs/COVERAGE_UNMEASURABLE.txt
git commit -m "Re-measure the coverage record and drop the stale entries"
```

---

## Task 2: Raise `notify_fill`'s swallowed failures to ERROR

**Only if Task 0a is answered yes.**

**Files:**
- Modify: `execution/execution.py:596`, `execution/execution.py:606`
- Test: `tests/unit/test_execution_execution.py`

**Interfaces:**
- Consumes: `ex._wire_notify_fill(orchestrator)`, `_Redis` and `_Replay` autospec
  sources already defined in that test file.
- Produces: no signature change. `notify_fill` still swallows; only the log level
  and message change.

- [ ] **Step 1: Write the failing test**

```python
def test_a_failed_cache_write_is_reported_at_error(self, caplog) -> None:
    """DEBUG is off in production, so a fill whose cache write fails corrects
    nothing and tells nobody. The handler must say what did not happen."""
    redis = create_autospec(_Redis, instance=True)
    redis.lpush.side_effect = RuntimeError("redis down")
    orch = self._orchestrator(redis=redis)
    ex._wire_notify_fill(orch)

    with caplog.at_level(logging.ERROR):
        orch.notify_fill("XAUUSD", "BUY", 1.0, 2400.0, "f9", "s9", "oanda", 3.0)

    assert any(r.levelno >= logging.ERROR for r in caplog.records), (
        "a fill that did not reach the cache was reported below ERROR"
    )
    assert "f9" in caplog.text, "the report must name the fill that was lost"
```

- [ ] **Step 2: Run it and watch it fail**

Run: `.venv/bin/python -m pytest tests/unit/test_execution_execution.py -k error -v`
Expected: FAIL — no record at ERROR, because the handler logs at DEBUG.

- [ ] **Step 3: Raise both handlers**

```python
        except (RuntimeError, TypeError) as exc:
            logger.error(
                "notify_fill: fill %s (%s %s qty=%s @ %s) was NOT written to the "
                "cache: %s — the cache now disagrees with what executed",
                fill_id, direction, symbol, quantity, fill_price, exc,
            )
```

and, for the replay handler:

```python
        except (RuntimeError, AttributeError, ValueError, TypeError) as exc:
            logger.error(
                "notify_fill: replay engine was NOT told about fill %s (%s %s "
                "qty=%s @ %s): %s — replay now disagrees with what executed",
                fill_id, direction, symbol, quantity, fill_price, exc,
            )
```

- [ ] **Step 4: Run the test and the whole file**

Run: `.venv/bin/python -m pytest tests/unit/test_execution_execution.py -q`
Expected: PASS, 60+ tests. The existing fill tests assert outcomes, not log
levels, so none of them should turn red. If one does, read it before changing it.

- [ ] **Step 5: Prove it can fail**

```bash
sed -i 's/logger.error(\n                "notify_fill: fill/logger.debug("notify_fill: fill/' execution/execution.py
.venv/bin/python -m pytest tests/unit/test_execution_execution.py -k error -q   # must FAIL
git checkout execution/execution.py
```

- [ ] **Step 6: Commit**

```bash
.venv/bin/python -m pre_commit run --files execution/execution.py tests/unit/test_execution_execution.py
git add execution/execution.py tests/unit/test_execution_execution.py
git commit -m "A fill the cache never recorded now says so at ERROR"
```

---

## Task 3: The recipe — raising one module

Every module in Tasks 4–6 follows this. It is `c007dad8` generalised. Read it
once; each later task names only its modules and what is special about them.

**Interfaces:**
- Consumes: a module path and its measured percentage from Task 1.
- Produces: a test file named so the gate pairs it, and one deleted line in
  `docs/COVERAGE_UNMEASURABLE.txt`.

- [ ] **Step 1: Find where the gate looks for the tests**

```bash
.venv/bin/python -c "
import sys; sys.path.insert(0,'scripts')
from pathlib import Path
import pre_commit_coverage as g
p = Path('<module>')
print('paired:', [str(t) for t in g._find_test_files(p)])
"
```

For a module at `<parent>/<name>.py` the gate accepts five name-matched
candidates — under `tests/unit/` a file called `test_` + the module's own stem,
`test_` + parent + `_` + stem, or `test_` + parent; and under `tests/` the first
two of those — **plus any test file that imports the module**. A new file named
outside that set and importing nothing is invisible to the gate. The
parent-and-stem form under `tests/unit/` is always safe; `_find_test_files` in
`scripts/pre_commit_coverage.py` is the authority, and Step 1 prints what it
actually resolved.

- [ ] **Step 2: Get the uncovered lines**

```bash
.venv/bin/python -c "
import sys; sys.path.insert(0,'scripts')
from pathlib import Path
import pre_commit_coverage as g
p = Path('<module>')
pct, out = g._run_coverage(p, g._find_test_files(p))
print('pct:', pct)
print([l for l in out.splitlines() if l.startswith(str(p))])
"
```

- [ ] **Step 3: Write tests for behaviour, in this order**

1. **Gates, guards and fail-closed paths first.** A refusal that has never run is
   the highest-value thing in the file. Cover every branch that returns "no".
2. **Failure and exception paths.** These are where success is reported for work
   that did not happen.
3. **The success path.**
4. Getters and formatting last, and only if needed to reach the floor.

Two rules, both from defects this repository has already shipped:

- Use `create_autospec(RealClass, instance=True)` wherever the production call
  depends on a signature. A bare `MagicMock` accepts arguments the real object
  rejects — F242 and F248 shipped green that way.
- Assert **outcomes**, never log text or `inspect.getsource`. A checker that
  reads prose is not reading code (F255).

- [ ] **Step 4: Measure**

Repeat Step 2. Below 80? Back to Step 3 with the remaining line ranges.

- [ ] **Step 5: Mutate, and watch the tests die**

Pick the two or three properties the module exists to hold. Break each one in the
source, run the file's tests, confirm a failure, restore. A test that has never
failed proves nothing. Record which mutations you ran in the commit message.

- [ ] **Step 6: Confirm with the real gate, then delete the line**

```bash
.venv/bin/python scripts/pre_commit_coverage.py <module>
# FAIL "... must leave the record" == raised. Now delete the line:
sed -i '\#^<module>$#d' docs/COVERAGE_UNMEASURABLE.txt
.venv/bin/python scripts/pre_commit_coverage.py <module>   # must print OK, exit 0
```

- [ ] **Step 7: Check the neighbours, then commit**

```bash
.venv/bin/python -m pytest tests/unit/test_<parent>*.py -q     # no regressions
.venv/bin/python -m ruff check --fix <test file> && .venv/bin/python -m ruff format <test file>
.venv/bin/python -m pre_commit run --files <test file> docs/COVERAGE_UNMEASURABLE.txt
git add <test file> docs/COVERAGE_UNMEASURABLE.txt
git commit -m "<module> N% -> M%"
```

If the work uncovers a defect — and it will — **do not fix it in the coverage
commit**. Record it in the commit message and raise it, exactly as `c007dad8`
did with `notify_fill`. A behaviour change hidden inside a test commit is
invisible to review.

---

## Task 4: Money path, the eight at 0%

**Files:** one test file per module; `docs/COVERAGE_UNMEASURABLE.txt`.

These carry the most consequence and are measured at **zero** — their paired
tests do not import them at all. Follow Task 3 for each, one commit per module.

- [ ] `core/risk/__init__.py`
- [ ] `core/safety_config_report.py`
- [ ] `core/strategy_engine.py`
- [ ] `core/health.py`
- [ ] `core/compat_router.py`
- [ ] `core/analytics/__init__.py`
- [ ] `ml/predictor.py`
- [ ] `portfolio/factor_model.py`

**Special to this task:** a package `__init__.py` at 0% usually means the test
imports the package's *submodules* and never the package. Check whether the
`__init__` has real logic (re-export guards, lazy imports, `__all__` policing)
before writing tests — if it has none, its floor is reached by a single test that
imports it and asserts its public surface.

`core/safety_config_report.py` is a safety reporter: apply `hopefx-dead-controls`
and check it can report a *failure*, not only a pass, before writing anything.

---

## Task 5: Money path, the rest

Sixty modules, in this order. One commit per module, Task 3's recipe each time.

- [x] **5a. `execution/fix_adapter.py` (35% -> 98%)** — **REQUIRED SUB-SKILL:
      `hopefx-fix-bridge`.** FIX 4.4 sessions, sequence numbers,
      logon/heartbeat/reconnect, XAUUSD symbol mapping. Read that skill before
      writing a line; sequence-number handling is not guessable.
      Done. The uncovered two-thirds was the whole quickfix callback surface,
      unreachable because quickfix is a C extension `requirements-ci.txt`
      cannot build, so the backend that carries production orders was the one
      no test could load. Reached with a hand-written FIX 4.4 stand-in, which
      surfaced three defects on that backend — see the commit.
- [x] **5b. `ml/train_rl_nuclear.py` (14% -> 99%)**, `ml/verify_model.py`
      (17% -> 100%), `ml/advanced_ai.py` (27% -> 99%), `ml/train_with_macro.py`
      (24% -> 98%) — **REQUIRED SUB-SKILL: `ml-pipeline-workflow`.** Training
      entry points; test the argument handling and the refusal paths, not a
      training run.
      Done. The common obstacle was the same as 5a's: gymnasium,
      stable-baselines3, faiss and sentence-transformers are all absent from
      `requirements-ci.txt` (sb3 needs PyTorch), so the code behind their
      import guards could not be reached at all. Each module is loaded a second
      time with the libraries stubbed, which is what made the findings visible.
      Six defects found; two fixed, four raised — see the commits.
- [ ] **5c. `brokers/__init__.py` (25%)**, `brokers/ibkr_broker.py` (38%),
      `brokers/ibkr_connector.py` (44%) — broker adapters. Every `connect()` has
      a refused path and a raised path; both matter more than the happy one.
- [ ] **5d. `core/risk/advanced_engine.py` (27%)**, `core/metrics.py` (33%) —
      **REQUIRED SUB-SKILL: `risk-metrics-calculation`** for the former.
- [ ] **5e. The remaining 50–79% money modules**, highest first:
      `core/position_reconciler.py` (79.2), `core/outbox.py` (78.6),
      `brokers/manager.py` (78.5), `ml/signal_features.py` (77.7),
      `ml/features_extended.py` (77.7), `brokers/oanda_broker.py` (77.4),
      `execution/engine.py` (76.6), then the rest in descending order.

**Special to this task:** anything touching prices, quantities, lot sizes, P&L or
balances requires **`hopefx-money-precision`** — Decimal/float boundaries and
`==` on monetary values. Anything touching a `verify_*` / `catastrophic_*`
predicate or `HOPEFX_INVARIANT_MODE` requires **`hopefx-invariants`**.

---

## Task 6: Everything else — 191 modules, cheapest first

Not one commit per module. Batch by package, one commit per batch, because these
carry less consequence and a 191-commit series is unreviewable.

- [ ] **6a. The 16 non-money modules already at 70–79%.** Nearest the floor,
      cheapest to clear. One commit for the batch.
- [ ] **6b. `api/` (51 modules, median 27%).** By router, one commit per router
      group. Most are FastAPI handlers: test the 401, the 404, the validation
      refusal, then the 200. **REQUIRED SUB-SKILL: `fastapi-templates`.**
- [ ] **6c. `strategies/` (11, median 68.5%)** — **REQUIRED SUB-SKILL:
      `backtesting-frameworks`** for look-ahead bias in the fixtures.
- [ ] **6d. `security/` (7, median 0%)** — **REQUIRED SUB-SKILL:
      `threat-modelling`.** A security module at 0% is a control nobody has
      watched fail.
- [ ] **6e. The remaining packages** — `data_layer`, `database`, `notifications`,
      `social`, `charting`, `analytics`, `invariants`, `chaos`, `utils`,
      `monetization`, `payments`, `portfolio`, `reports`, `config`,
      `market_data`, `brain`, `cache`, `analysis`, `backtesting`,
      `enhanced_backtest_engine.py` — one commit per package.

**Special to this task:** a module here that turns out to be dead code is a
finding, not a test target. `scripts/ci/gate_e_dead_files.py` exists; run it
before writing tests for anything in `charting/`, `social/` or `chaos/`, and
raise a removal rather than testing something nothing calls.

---

## Task 7: Close the programme

- [ ] **Step 1: Re-measure the whole record** (Task 1, Steps 1–2).

- [ ] **Step 2: Every remaining entry states why it cannot be raised**

The record should now hold only modules that genuinely cannot be measured or
genuinely should not be tested. Each surviving line gets a reason in the header,
grouped — "needs a live broker session", "generated", "entry point with no
importable surface". An entry with no reason is an entry nobody has looked at.

- [ ] **Step 3: Record it in `docs/ai/MASTER_OUTSTANDING.md`**

One §E entry: what the record held at the start (263), what it holds now, how
many modules were raised, which defects the work uncovered, and what is left
with the reason it is left.

- [ ] **Step 4: Re-check the floor itself**

With the record small, ask whether 80 is still the right floor and whether
`COVERAGE_THRESHOLD` should rise. That is a Task 0-class decision — propose, do
not set it.

---

## Self-review

**Spec coverage.** There is no spec; the plan argues from measurement. Every one
of the 259 modules is claimed by exactly one task: 8 in Task 4, 60 in Task 5,
191 in Task 6. 8 + 60 + 191 = 259. The three open findings are Tasks 0a, 0b, 0c.

**Placeholders.** Task 3 carries the full recipe with real commands; Task 2
carries the real test and the real replacement code. Tasks 4–6 name specific
modules with measured percentages rather than "the rest". The one deliberate
generalisation is Task 6's batching, and it names the batch boundaries and the
per-batch skill.

**Type consistency.** Task 1 produces `{"module", "pct", "state"}` and Tasks 4–6
consume exactly those keys. Task 2's test reuses `_Redis`, `_Replay` and
`self._orchestrator` as they are already defined in
`tests/unit/test_execution_execution.py`. Task 3's `_find_test_files` and
`_run_coverage` are the real function names in `scripts/pre_commit_coverage.py`.

**Known gap, stated rather than hidden:** Task 6 is 191 modules and will not fit
one sitting. It is ordered so that stopping after any batch leaves the record
smaller and the tree green, which is the property that matters if the programme
is paused.
