# HOPEFX Audit Playbook

How to get a **complete and trustworthy** picture of what is wrong with this
system — frontend, backend, engine, data, ML, ops, design — using an AI
assistant without drowning in generic advice.

This is a method plus a set of copy‑paste prompts. It is the process that
produced `HARDENING_BACKLOG.md`, generalised so it can be re‑run on schedule.

---

## Why "audit the whole app" does not work

This repo is ~1,350 Python files, ~330 TypeScript files, ~100 top‑level
directories, 480 test files and 21 CI workflows. A single "find everything
wrong" request fails for mechanical reasons:

| Problem | Consequence |
|---|---|
| The codebase does not fit in one context window | The assistant samples ~30 files and pattern‑matches the rest |
| "Wrong" is undefined | Risk‑gate bugs and UI copy bugs get the same weight |
| No verification step | Findings are never traced; roughly half are false, and you cannot tell which half |

Unbounded audits produce **confident, plausible, unverified** output. That is
worse than no audit in a money‑moving system, because it consumes the attention
you would otherwise spend on real defects.

The fix is not a better single question. It is **narrow scope, a stated
standard of correctness, and a required proof** — repeated on a schedule.

---

## The four rules

### 1. Slice by blast radius

One audit session per slice, fresh context each time. Never combine slices —
context spent on button alignment is context not spent on fill accounting.
Work top‑down through the priority table below; do not reorder for
convenience.

### 2. Ask for invariants first, bugs second

This is the single biggest quality lever.

> ❌ `Find bugs in risk/manager.py`
>
> ✅ `List the 12 invariants risk/manager.py must hold for the system never to
> exceed max daily drawdown. Then, for each, trace the code and say whether it
> holds — CONFIRMED violated, PLAUSIBLE, or holds.`

The first prompt is an open hunt for anything that looks unusual. The second
supplies a specification to check against, which makes **"no violations
found"** a real result rather than an absence of effort. It also surfaces
missing invariants — the gate nobody ever wrote.

### 3. Require an output contract, and no fixes on the first pass

Every finding must carry:

- **Severity** — impact on capital or correctness, not effort
- **`file:line`** — a real location, not a module name
- **What breaks** — one sentence
- **Concrete failure scenario** — specific inputs/state → specific wrong outcome
- **Smallest fix** — minimal diff, not a redesign
- **Verdict** — `CONFIRMED` (traced in code) or `PLAUSIBLE` (needs runtime proof)

The failure scenario is the filter. If the assistant cannot write one, the
finding was pattern‑matching and should be dropped before you ever see it.

Keep audit and repair as separate passes. Mixing them means fixes land while
scope is still moving, and you lose the ability to triage by severity.

### 4. Make it run, not just read

Static reading finds perhaps 60% of real defects. The remainder only appears
under execution: a stalled tick feed, a broker returning `TIMEOUT`, a process
restart mid‑fill, a frontend pointed at a backend returning 500s. Every slice
below has a "run it" clause for this reason.

---

## Slices, in priority order

| # | Slice | Primary paths | Why at this rank |
|---|---|---|---|
| 1 | Money path | `core/decision/`, `risk/manager.py`, `execution/`, `brokers/` | The only slice that can lose real capital |
| 2 | Gates & kill switch | `risk/`, `kill_switch.py`, `invariants/`, `compliance/` | Last line of defense; must fail **closed** |
| 3 | Backtest ↔ live parity | `backtesting/`, `strategies/`, `ml/` | If these diverge, every performance number is fiction |
| 4 | ML integrity | `ml/inference_engine.py`, `features/` | Silent failure mode — degrades without erroring |
| 5 | Data layer | `data_layer/`, `data_feed/`, `market_data/` | Bad input defeats every downstream gate |
| 6 | Auth, secrets, money‑in | `auth/`, `api/`, `security/`, `payments/`, `monetization/` | Breach and fraud blast radius |
| 7 | State & crash recovery | `database/`, `alembic/`, `execution/redis_state.py` | Already an open item in the backlog |
| 8 | Realtime transport | `api/ws_live.py` | Backpressure, per‑channel auth, reconnect |
| 9 | Frontend correctness | `frontend/src/`, `dashboard/src/` | Stale‑as‑live display, money rounding, races |
| 10 | Frontend & UX design | `frontend/src/` | Trading surfaces have specific design duties |
| 11 | Ops & deployment | `Dockerfile`, `docker/`, `k8s/`, `helm/`, `.github/workflows/` | Config drift, health checks, workflow sprawl |
| 12 | Test quality | `tests/` | Mocks that hide bugs are worse than no tests |
| 13 | Dead code & duplication | repo root | Parallel copies mean fixes silently do not apply |

---

## The prompts

Run one per session. Each assumes a fresh context.

### Slice 1 — Money path (start here)

```
Audit the money path only: core/decision/HOPEFXDecisionEngine.py →
risk/manager.py → execution/oms.py → brokers/.

Step 1: list every invariant that must hold for a signal to become a
correctly-sized, correctly-booked order. Include position sizing, rounding,
idempotency, partial fills, rejections, and P&L attribution.

Step 2: trace each invariant in the actual code.

Report only CONFIRMED or PLAUSIBLE violations. For each: severity, file:line,
what breaks, a concrete failure scenario (specific inputs → specific wrong
outcome), and the smallest fix. Do not apply fixes.

Drop any finding that would apply equally to any Python repo.
Append results to docs/HARDENING_BACKLOG.md as a new Round.
```

### Slice 1b — Adversarial variant (finds different defects)

```
You are trying to lose $50,000 through this system without tripping the kill
switch or any prop-firm limit. You control broker latency, tick feed
staleness, order rejections, partial fills, and process restarts.

Walk me through the cheapest attack, step by step, citing the exact file:line
that permits each step. Then rank the steps by how cheap the fix is.
```

Run 1 and 1b both. Invariant framing finds missing gates; adversarial framing
finds gates that exist but can be walked around.

### Slice 2 — Gates and kill switch

```
Audit every risk gate, kill switch and prop-firm limit: risk/, kill_switch.py,
invariants/, compliance/.

For each gate: does it fail OPEN or CLOSED when its dependency errors, times
out, or returns None? Show me the exception path at file:line. A gate that
permits a trade when its own check crashes is CRITICAL.

Then: can any gate be bypassed by calling a lower-level function directly? List
every call site that reaches the broker without passing through the gate.
```

### Slice 3 — Backtest ↔ live parity

```
Do backtesting/ and the live engine share the same signal, sizing and fill
logic, or are there two implementations?

Map every place the logic diverges, with file:line on both sides. For each
divergence say which direction it biases results (optimistic/pessimistic).

Then check the backtester specifically for: lookahead bias, survivorship,
fill-at-mid assumptions, missing fees, missing slippage, and bar-close
execution that live could never achieve. Give a concrete example trade for
each finding.
```

### Slice 4 — ML integrity

```
Audit ml/inference_engine.py and features/ for train/serve skew.

Compare the feature computation used at training time against the one used at
inference, field by field. Report any difference in ordering, scaling, fill
policy for missing values, or time window.

Then verify the staleness and drift gates: what exactly happens when a model is
stale, when drift is detected, and when a feature is NaN? Trace to file:line.
Does the system degrade to a safe default, or trade on garbage?
```

### Slice 5 — Data layer

```
Audit data_layer/ for input integrity: gaps, duplicate ticks, out-of-order
timestamps, timezone/DST handling, weekend and rollover boundaries, and stale
feed detection.

For each: what does the system do today, and what should it do? Show file:line.

Then trace one tick end to end, from feed ingress to the decision engine, and
list every place its timestamp or price could be silently altered.
```

### Slice 6 — Auth, secrets, money-in

```
Audit auth/, api/, security/, payments/, monetization/.

Enumerate every API route and mark: auth required? role checked? tenant/user
isolation enforced on the query itself, not just the handler? rate limited?

Report every route where a user could read or modify another user's data.
Then audit payments/ and monetization/ for idempotency, replay, and
double-credit paths. Give file:line and a concrete exploit sequence for each.
```

Also run the built-in `/security-review` on the branch diff — it is scoped to
changes, so it complements this rather than duplicating it.

### Slice 7 — State and crash recovery

```
Simulate a hard process kill at each of these moments and tell me what state is
left behind and whether boot recovers it correctly:
  1. after broker ack, before local persist
  2. mid partial fill
  3. after SL/TP trigger, before the close is booked
  4. mid database migration

Trace execution/redis_state.py and database/ recovery paths at file:line. Are
restored orders and positions reconciled against live broker state on boot?
```

### Slice 8 — Realtime transport

```
Audit api/ws_live.py: per-channel authorization, backpressure when a client is
slow, reconnect and resubscribe semantics, message ordering, and what a client
sees after a disconnect gap.

Can a slow consumer degrade the engine? Show the queue/buffer at file:line and
what happens when it fills.
```

### Slice 9 — Frontend correctness

```
Audit frontend/src/ for correctness, not aesthetics:

  1. Can stale data ever render as if it were live? Find every price/PnL
     display and check whether it carries a freshness signal.
  2. Money and quantity formatting: any float rounding, toFixed, or locale
     handling that could display a wrong number.
  3. What renders when the backend is down, slow, or returns 500? Per view.
  4. Race conditions: out-of-order responses, double-submit on order actions,
     stale closures in effects.
  5. Any place the UI asserts success before the backend confirmed it.

file:line and a reproduction for each.
```

Add the run-it clause: point the dev server at a backend that is stopped, and
at one returning 500s, and report what each view actually does.

### Slice 10 — Frontend and UX design

```
Review frontend/src/ as a trading surface, against these duties:
  - Can the user tell, in under a second, whether the system is live, paused,
    or killed?
  - Is every destructive or capital-committing action confirmed, and is the
    confirmation specific (amount, symbol, direction)?
  - Is latency visible — does the user know when data is 5s old?
  - Information hierarchy: is the most decision-relevant number the most
    prominent one on each screen?
  - Colour: is red/green the only carrier of meaning anywhere?
  - Keyboard and screen-reader access on order entry.

Report gaps with the screen and component, ranked by how much money a
misreading could cost.
```

### Slice 11 — Ops and deployment

```
Audit Dockerfile, docker/, docker-compose*.yml, k8s/, helm/ and
.github/workflows/.

  1. Config drift: list every env var read in code but absent from
     .env.example, and every one documented but unread.
  2. Are health checks real (do they verify feed + broker + DB), or do they
     return 200 unconditionally?
  3. There are 21 workflows. Which are dead, duplicated, or never green?
  4. Does the Docker image match the documented Python 3.10 target everywhere?
  5. Secrets: anything reachable in a built image or a workflow log.
```

### Slice 12 — Test quality

```
There are ~480 test files. Assess whether they actually protect the money path.

  1. Find tests that assert nothing, or only assert the mock was called.
  2. Find mocks that would hide a real bug — e.g. a broker mock that always
     fills fully at the requested price.
  3. List every skipped, xfail, or permanently-disabled test and why.
  4. For the money path specifically (slice 1), which invariants have NO test?

Then write one failing test for the highest-severity untested invariant. A
failing test is the proof; produce that before any fix.
```

### Slice 13 — Dead code and duplication

```
The repo root has ~100 directories, including these parallel pairs:
backtest/ vs backtesting/, strategy/ vs strategies/, data/ vs data_layer/,
websocket/ vs api/ws_live.py, mobile/ vs mobile-app/.

For each pair and for every top-level directory: is it live (imported on a
runtime path), a documented shim, or dead? Show the import evidence.

Then find logic that exists in two places and could drift — where fixing one
copy would silently fail to fix the system. Rank by what a fix landing in the
wrong copy would cost.

Propose deletions. Deleting is the deliverable here, not adding.
```

---

## How to ask, in general

Applies to any prompt, not just audits.

**Say what "wrong" means for this slice.** "Wrong" in `risk/` is "a gate can be
bypassed." "Wrong" in the frontend is "shows stale data as live." Without a
standard, the answer regresses to generic advice.

**Ban the generic.** Add: *"drop any finding that would apply equally to any
Python/React repo."* This single sentence removes most of the noise.

**Ask for the failing test, not the fix.** A test that fails on current code and
passes after the change is proof. A described fix is an assertion.

**Ask for CONFIRMED vs PLAUSIBLE.** Forces the distinction between traced and
guessed, and tells you which findings still need runtime verification.

**Ask what would be deleted.** "What can we remove?" consistently surfaces more
value here than "what should we add?"

**Cap the output.** *"Top 10 by severity"* produces better findings than
*"list everything"* — a cap forces ranking, and ranking forces judgement.

**Give a reproduction path.** If a bug is reachable by running something, say
how to run it. Verified beats inferred every time.

---

## Cadence and record‑keeping

Findings go in **one cumulative document — `docs/HARDENING_BACKLOG.md`** — as
numbered Rounds. Dated snapshot files (`AUDIT_2026-07-26.md`,
`AUDIT_SIDEBAR_2026-07-27.md`, …) fragment the record: nobody can answer "what
is still open" without reading all of them. A single backlog with Fixed/Open
status answers that in one read.

Suggested rhythm:

| When | What |
|---|---|
| Every PR | `pre-commit run --all-files`, `/code-review`, `/security-review` on the diff |
| Weekly | One slice from 1–5, rotating |
| Before any live‑capital milestone | Slices 1, 2, 3, 7 — all four, no exceptions |
| Quarterly | Slices 11, 12, 13 |

Existing automation that already covers ground — do not re‑ask by hand:
CodeQL, Fortify, Codacy and the security‑scan workflow in `.github/workflows/`,
plus `ruff`, `bandit` and `detect-secrets` via pre‑commit.

---

## The order that matters most

If you only ever run three of these: **slice 1 (money path), slice 2 (gates
fail closed), slice 3 (backtest parity).** In that order. Everything else is
recoverable; those three are how a paper‑profitable system loses real money on
its first live day.
