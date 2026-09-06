# HOPEFX — Outstanding Work

**Status date:** 2026-09-05 · **Branch:** `claude/add-new-skills-lys862` · **PR:** #315

Companion documents:

* `docs/audit/CODE_READING_FINDINGS.md` — the 277 findings, with evidence.
* `docs/audit/FIX_PHASES.md` — what each phase did. **The maintained tracker.**
* `docs/audit/AI_CORE_SPEC.md` — the AI Core specification.
* `docs/audit/REMEDIATION_PLAN.md` — **stale.** Its checkboxes list 80 items as
  open, including F80, F99, F105, F108, F139, F145, F159, F176 and F221, all of
  which are fixed and verified. Do not plan from it. Item 22 below retires it.

Phases A, B, C, D, E, G and H are complete and verified. Phase F is in progress.
Everything below is what is left.

## The list at a glance

23 items. Ordered by what moves money or loses it, not by how many findings
each contains — the same rule `FIX_PHASES.md` uses.

| # | Item | Severity | Blocked on |
|---|---|---|---|
| 1 | CodeQL: 11 alerts, 1 critical | CRITICAL | **owner** (triaged; needs the rule ID) |
| 1b | **Two committed models fail integrity and do not load** | CRITICAL | **owner** |
| 1c | F270 · async pool listened for non-existent events → readiness 503 forever | CRITICAL | fixed |
| 2 | Vercel check belongs to another project | noise | owner |
| 3 | F218 · 14 tables have no migration | MEDIUM | — |
| 4 | 51 money columns typed `Float` | HIGH | paying path done; trading side listed with reasons |
| 5 | F222 · 8 critical modules with no test | HIGH | 7 of 8 done; five found live defects |
| 6 | Crypto currency read from a free-text field | MEDIUM | fixed |
| 7 | OANDA adapter never run against the venue | HIGH | **owner** |
| 7b | `get_order` missing on OANDA, charged to the breaker | HIGH | part 1 no, part 2 owner |
| 8 | Coverage headroom — resolved, rule stands | — | — |
| 9 | Coverage measures 38.6% of the application | MEDIUM | — |
| 10 | `execution/` omissions, with measured debt | MEDIUM | — |
| 11 | F223 · 75 metric-named files, 1,125 assertion-free tests | HIGH | — |
| 12 | F104 · a "gate" that cannot fail | HIGH | fixed; it was also reporting the wrong number |
| 13–19 | **The AI Core — BUILT** (gateway, tool bus, guardrails, evals, cache, sandbox, AI Core page) | — | done |
| 20 | `static/` build artifact in CI | fixed; decision open | owner |
| 21 | F216/F217 · `data/` ↔ `data_layer/` boundary | MEDIUM | **owner** |
| 22 | `REMEDIATION_PLAN.md` is stale | MEDIUM | — |
| 23 | Owner-blocked questions | — | **owner** |
| 24 | F271 · the dependency scan reads the manifest that pins nothing | HIGH | fixed; 1 critical + 4 high were hidden |

**Read first if you read nothing else:** items 1, 4, 7b and 13–19.

Two things are true at once and both belong in your head: the platform's safety
controls are in better shape than when this audit started — every phase but F is
closed, with each fix carrying a test that fails on the pre-fix tree — and the
AI Core, which is the thing you asked for, has not been started. Items 13–19 are
not repairs. They are the build.

## Global constraints

Every item inherits these. They are not negotiable and not restated per item.

* Develop and push only on `claude/add-new-skills-lys862`.
* `ruff check .` clean; `pre-commit run --all-files` clean. Never `--no-verify`.
* Full gate before claiming done:
  `pytest tests/ -m "not slow and not e2e" --cov --cov-config=.coveragerc --cov-fail-under=70 --asyncio-mode=auto --timeout=120 -q`
* Never weaken a risk gate, kill switch, or staleness/drift check.
* Never commit secrets. `prop_firm_mode.json` and `.env.example` hold placeholders only.
* New code goes in `backtesting/`, `strategies/`, `data_layer/` — never the legacy shims.
* Never recreate a top-level `websocket/` package.
* Python 3.12 is the production target.
* **Every fix ships with a test that fails on the pre-fix tree.** Run it against
  the old code and watch it fail. A test that has never failed proves nothing.

---

## P0 — Blocking the current PR

### 1. CodeQL: 11 new alerts, 1 critical · OPEN — triaged as far as this session can

`CodeQL` fails on PR #315. **Still needs the owner** to read the Security tab,
because no code-scanning tool is exposed to this session: `get_check_run`
returns an empty `output.text` with no annotations, and the CodeQL CLI is not
installed here. What follows narrows it.

**Update 2026-09-05 21:24 — three of them now ARE attributable.** The count
moved for the first time in nine commits, and it moved exactly when the
`v0/hopefx-remediation` merge landed:

| Head | Commit | Critical | High |
|---|---|---:|---:|
| `42d67475` | last commit before the merge | 1 | 10 |
| `0097a440` | first CodeQL run after the merge | **2** | **12** |

So **1 critical and 2 high are new, and they are in v0's merged code** — a
search space of 15 files rather than 439. The other 11 remain unattributable
for the reason below.

Candidates in that new code, ranked by how CodeQL's Python queries score them:
`security/ai_repair_sandbox.py` writes caller-supplied source to a temp file and
invokes `subprocess.run([sys.executable, "-B", "-m", "py_compile", ...])` on it
— a request-to-subprocess path that `py/command-line-injection` or
`py/code-injection` would rate critical even though `py_compile` never executes
the module body. `api/safe_agent_platform.py` and
`strategies/dynamic_registry.py` are the next places to look.

**The alerts are not introduced by this branch's recent commits.** The count has
been identical — 1 critical / 10 high — across seven consecutive commits,
including one that changed only YAML and one (`d42fc59f`) that changed **a
single markdown file**. CodeQL re-ran on that docs-only commit and reported the
same "New alerts in code changed by this pull request". Its own summary admits
why: *"Alerts not introduced by this pull request might have been detected
because the code changes were too large"* — the diff is 439 files.

**Candidate sinks, measured locally** (production code only; `tests/`,
`scripts/` and `docs/` excluded). These are what CodeQL's Python queries would
flag at critical/high in a repository shaped like this one:

| Rule | Location | Disposition |
|---|---|---|
| `py/code-injection` | `strategies/dynamic_registry.py:555` — `exec(code_obj, allowed_globals)`, tainted from `api/dynamic_strategies.py:130` and `api/nocode.py:170` | **Already defended and documented.** `ASTSafetyValidator` blocks `__subclasses__`, `__bases__`, `__mro__`, `__code__`, `__globals__`, `__builtins__`, subscript attribute access, and 23 imports / 17 calls. The docstring at `:445` already states it is *"defence in depth, not a boundary, and must not be described as a sandbox."* If this is the critical alert, the disposition is **accept with that reason**, and the real fix is item 19 (a real sandbox). |
| `py/unsafe-deserialization` | 9 `pickle.load` sinks. Only one sits inside an API route: `api/superadmin/ml_ai.py:452` | Defended: superadmin auth, `re.fullmatch(r"[A-Za-z0-9_]{1,64}")` on the model name, and `Path.relative_to` confinement. CodeQL taint tracking frequently does not recognise `relative_to` as a sanitiser, so this is a **likely false positive**. The other 8 are in `research/`, `ml/` and `deployment_guide.py`, not request-reachable. |
| `py/code-injection` | `research/__init__.py:440` — `exec(compile(...))` notebook cell executor | Not request-reachable. |
| `actions/code-injection` | none | The workflow analyses `actions` as well as `python`. Scanned every `run:` block for the 12 documented untrusted `github.event.*` inputs: **zero hits**. The only two untrusted expressions (`summary.yml:34-35`) are `with:` inputs to `actions/ai-inference`, not shell, and the response is already passed to `gh` through an env var. |

**Do (owner):** open
`https://github.com/HACKLOVE340/HOPEFX-AI-TRADING/security/code-scanning?query=pr%3A315+tool%3ACodeQL+is%3Aopen`
and supply the rule ID, file and line for the critical alert. If it matches a
row above, the disposition is already written; if it does not, it is something
this triage missed and needs fixing here.
**Done when:** the critical alert is resolved or explicitly accepted with a reason.

### 1b. Two committed models fail their integrity check and do not load · CRITICAL — **mine**

Found while investigating CodeQL's critical alert. Measured, not inferred:

```
feature_scaler.pkl       verify=False  loaded=None
stacking_ensemble.pkl    verify=False  loaded=None
current.pkl              verify=True   loaded=YES
rf_macro.pkl             verify=True   loaded=YES
lstm_signal.pt           listed in the baseline, MISSING from disk
```

`_verify_checksum` refuses them on checksum mismatch — that branch always
worked — so `_try_load` returns `None` and neither model is available in **any**
environment, right now.

**Cause is my own commit.** `776b59c` (the F145 fix) rewrote the bytes of both
files — `feature_scaler.pkl` 8623→8623 bytes, `stacking_ensemble.pkl`
48693→48549 — and did not regenerate `ml/saved_models/model_checksums.json`. The
merge of `main` then brought that file from `334e50f`, describing main's
artefacts. Neither side is wrong on its own; together they do not agree.

**Why it needs you and not me.** The fix is to regenerate the baseline so it
matches whichever `.pkl` files are canonical — and I cannot determine which
those are. The two on disk came from my commit; main's baseline describes
different bytes. Blessing a set of model artefacts is a decision about what the
platform trades on.

**Do:**
1. Decide which artefacts are canonical — the ones on this branch, or main's.
2. Regenerate `model_checksums.json` from those, as a deliberate commit that says
   so, never as a side effect of a load.
3. Drop or restore the stale `lstm_signal.pt` entry: the baseline lists a file
   that is not on disk.
4. Fix `_record_checksums`, which globs `*.pkl` only. The baseline it maintains
   contains `.pt` and `.zip` entries it therefore cannot reproduce — regenerating
   silently narrows integrity coverage. I hit this myself: my first regeneration
   dropped both entries, and I reverted it.

**Add a CI gate** asserting every entry in the baseline exists and matches, and
that every packaged artefact is listed. This is the check that would have caught
it at the commit that caused it. `tests/unit/test_model_integrity_check_is_not_fail_open.py`
already asserts coverage and matching, so wiring it into a required job is small.

### 2. Vercel deployment failure · NOT OURS — confirm and dismiss

The failing Vercel status belongs to project `v0-new-project-8ud36nesln3`, a v0
scratch project. It builds no code in this repository.
**Do:** confirm with the repo owner, then disconnect the integration or mark the
check non-required. **Done when:** it no longer reports on this repo's PRs.

---

## P1 — Money and correctness

### 3. F218 — 14 tables exist only via `create_all()` · MEDIUM

```
aml_alerts  api_keys  broker_connections  chargebacks  config_store
crypto_payments  email_suppressions  gdpr_requests  outbox_events
reconciliation_records  sessions  tax_reports  watchlists  whitelabel_tenants
```

41 tables are declared by models; 27 are touched by a migration. `create_all()`
creates a missing table and **never alters an existing one**, so a column added
to any of these 14 appears on every fresh database and on no existing one — with
no migration to close the gap and no error. The oldest deployment fails at query
time, which is the worst place to find out.

**Do:** one Alembic migration per table using `_create_table_if_missing`, so it
is a no-op where `create_all()` already made the table. Then a test asserting
every `__tablename__` is covered by a migration, so number 15 cannot appear.
**Verify:** `alembic upgrade head` on an empty DB **and** on a DB built by
`create_all()`. **Done when:** the coverage test passes and CI's Gate I is green.

### 4. Money columns are `Float` · HIGH

Measured in `database/`: **51** money-ish columns typed `Float` against **8**
`Numeric`. The 8 are the creator-ledger tables added in Phase B — the only exact
columns in the schema. `Float` cannot represent 0.07 exactly; balances that are
summed repeatedly drift, and a drift in a balance column is money.

**Do:** do **not** convert all 51 at once. Order by exposure: wallet balances →
payments → P&L → analytics. Each conversion is `Numeric(18, 2)` plus a migration
plus a test asserting a repeated-addition case that `Float` fails.
**Read first:** the `hopefx-money-precision` skill. **Done when:** every column
on a path that pays or holds user money is `Numeric`, with the remainder listed
here and a reason for each.

**Status: the paying path is done.** Migration `t1u2v3w4x5y6`, tests in
`tests/unit/test_money_columns_are_exact.py` (12 of 13 fail on the pre-fix tree).
19 columns across 9 tables converted, ordered by exposure exactly as above:

| Table | Columns | Why |
|---|---|---|
| `wallet_transactions` | amount, balance_after | the ledger |
| `crypto_payments` | amount_usd, amount_crypto `(28,8)`, rate_usd `(28,8)` | a satoshi is 1e-8 |
| `chargebacks` | amount | money going back out |
| `billing_history` | amount | what a customer was charged |
| `reconciliation_records` | expected_amount, actual_amount, discrepancy | the check that detects drift was drifting itself |
| `tax_reports` | total_revenue, taxable_amount, tax_rate_pct `(9,6)`, tax_owed | a filing figure that drifts is a filing error |
| `aml_alerts` | amount | compared against a regulatory threshold |
| `whitelabel_tenants` | revenue_usd | what a tenant is owed |
| `sub_accounts` | initial_balance, current_balance, daily_loss_limit | held money, and a risk-gate threshold |

`api/payments.py` gained `_exact()`, so the three crypto amounts convert through
`Decimal(str(x))` at that edge — handing a float to a NUMERIC column would put
the drift straight back into a column made exact to remove it.

**Remainder, with the reason.** `trades`, `orders`, `positions`, `accounts`,
`account_snapshots`, `signals`, `ai_signals`, `predictions`, `tick_data`,
`order_book_snapshots`, `performance_metrics`, `performance_metric_samples` stay
`Float`, because their runtime does: `execution/position_tracker.py` holds every
live position as `float` across 35 importers. Converting the columns without the
runtime yields `Decimal` in the schema and `float` arithmetic above it — the
boundary bug the money-precision skill is about, not a fix for it. The list is
asserted in the test, so a new money column cannot land in neither list.

This migration stops the drift; it does not retroactively correct one. A balance
already stored drifted keeps its value. Correcting it is a reconciliation against
the append-only `wallet_transactions`, and belongs in its own change with its own
evidence.

### 5. F222 — 8 critical modules with no test · HIGH

Never named in any test file:

| LOC | Module |
|---:|---|
| 628 | ~~`monetization/payment_processor.py`~~ — done; found 2 defects, see below |
| 585 | ~~`portfolio/strategy_allocator.py`~~ — done; a 40% cap was awarding 80% |
| 427 | ~~`payments/transaction_manager.py`~~ — done; found a double-refund path |
| 354 | ~~`monetization/marketplace_submission.py`~~ — done; the code audit auto-approved escapes |
| 318 | ~~`payments/fintech/paystack.py`~~ — done; found a stale hard-coded FX rate |
| 282 | ~~`monetization/access_codes.py`~~ — done; no defect found, coverage only |
| 228 | `database/repositories/tick_data_repository.py` — **not done**; finding recorded below, needs a `TickQuality.UNKNOWN` decision |
| 208 | ~~`payments/payment_gateway.py`~~ — done, `tests/unit/test_payment_currency_is_explicit.py` |

I triaged all eight for a second F267 (a fabricated value on a money path).
**None fabricates.** `access_codes` uses SHA-256 as a typo checksum with
`secrets.choice` for the randomness, which is correct; `payment_processor` had
one broken log line, fixed under F268. So this is a coverage gap, not a live
loss — but `payment_processor.py` and `transaction_manager.py` move money with
nothing watching them.

**Order:** `payment_processor` → `transaction_manager` → `payment_gateway` →
`paystack` → `access_codes` → `marketplace_submission` → `strategy_allocator` →
`tick_data_repository`.
**Done when:** each is named by a test that exercises its real behaviour, not
its import.

**`payments/payment_gateway.py` — done** (`tests/unit/test_payment_currency_is_explicit.py`,
with item 6's fix).

**`monetization/payment_processor.py` — done, and writing the test found two
defects, both reproduced by execution before being fixed**
(`tests/unit/test_payment_processor_reports_reality.py`, 10 of 15 fail on the
pre-fix tree):

1. **A payment that was never charged was reported as succeeded · HIGH.**
   `create_stripe_payment_intent` returns `None` on any `StripeError` — a
   declined card, a rate limit, an outage. `process_payment` guarded only the
   id assignment (`if intent_id:`) and fell through to `mark_succeeded()`,
   `mark_invoice_paid()` and `SubscriptionStatus.ACTIVE`, returning `True`.
   Measured: no PaymentIntent, no money, status `succeeded`, subscription
   active. The signature defect of this audit — success reported for work that
   did not happen — sitting on the path that collects revenue, and reachable
   any time Stripe declines a card. It now raises `PaymentNotCharged`, which
   the existing handler turns into a failed payment with an unpaid invoice.
2. **Sub-cent amounts were truncated, not rounded · MEDIUM.**
   `int(amount * 100)` made `Decimal("10.999")` into 1099 cents. On a charge
   that under-bills; on a refund it keeps the remainder, which favours the
   platform against the customer. `to_cents()` quantizes HALF_UP per the
   `hopefx-money-precision` skill — `round()` would give banker's rounding,
   which is not what an invoice means.

**`payments/transaction_manager.py` — done, and it had a double refund ·
HIGH** (`tests/unit/test_transaction_state_machine.py`, 8 of 24 fail on the
pre-fix tree).

`update_transaction_status` assigned any status over any status. `cancel` and
`reverse` each guarded their own entry condition; `complete` and `fail` did not.
So a REVERSED transaction could be completed again, and then reversed again.
Measured through the module's own public API, with no tampering and no race:

    deposit 100.00 → complete → reverse → complete → reverse
    = 200.00 of reversals from one 100.00 deposit

Fixed with an `_ALLOWED_TRANSITIONS` table modelled on
`core/ai_contracts.py`'s — the pattern this audit already identified as right
for this problem. COMPLETED's only exit is REVERSED; REVERSED, FAILED and
CANCELLED are terminal; re-asserting the same status stays a no-op so an
idempotent webhook retry does not read as tampering. `reverse_transaction` now
goes through the same door rather than assigning the status directly, because a
second way to change a status is how the first one got missed.

**`payments/fintech/paystack.py` — done, and a hard-coded FX rate was deciding
what customers pay · HIGH** (`tests/unit/test_paystack_client_charges_correctly.py`,
11 of 22 fail on the pre-fix tree).

```python
_NGN_PER_USD = Decimal("775.00")  # approximate; update via FX feed in production
```

A USD price was multiplied by that constant to get the naira amount actually
charged. The comment concedes it is approximate; nothing ever updated it. The
naira has moved a long way from 775 — at a true rate near 1,600 the platform
billed a USD price and collected roughly half of it, silently, on every
transaction. A constant standing in for a measurement, with a comment admitting
the fact, is this audit's signature defect.

**Writing a newer number would be the same defect with a later date.** The rate
is configuration now (`PAYSTACK_NGN_PER_USD`, or a constructor argument), read
at call time so it can change without a restart, and an absent, zero, negative
or unparseable rate is **refused** — the same rule as item 6's currency field.
NGN charges need no rate and are unaffected.

Also fixed: `int(amount * 100)` truncated kobo in both `initialize_payment` and
`initiate_transfer`. On a charge that under-bills; on a **payout** it under-pays
the recipient and the platform keeps the remainder, which is the direction that
matters most.

**Open for the owner:** `PAYSTACK_NGN_PER_USD` has no value set anywhere. USD
charges through Paystack will now refuse until one is configured, which is the
intended behaviour — but if USD-via-Paystack is a live flow, it needs a rate, and
ideally a feed rather than a variable.

**`monetization/access_codes.py` — done, and it was sound**
(`tests/unit/test_access_codes_cannot_be_reused.py`, 18 cases). Unlike the three
above, this found **no defect**: the earlier triage was right. A code cannot be
redeemed twice, a revoked or expired one is refused, the entropy is
`secrets.choice` over 36^8, and redemption records who and when. So these tests
pass on the pre-fix tree too — they are a guard against regression, not evidence
of a fix, and that distinction is worth keeping honest.

One assertion deliberately **not** made: that the checksum is compared in
constant time. It is derived from the two public halves of the code, so anyone
can compute it; the secret is the random part, which is looked up rather than
compared. A `compare_digest` there would be security theatre. What does matter —
that passing the checksum is not the same as having been issued — is asserted by
forging a code that validates and confirming it cannot be redeemed.

**`monetization/marketplace_submission.py` — done, and its code audit
auto-approved sandbox escapes · HIGH**
(`tests/unit/test_marketplace_audit_catches_escapes.py`, 11 of 19 fail on the
pre-fix tree).

This is a code-review gate with **no human in the path**: it takes strategy code
from a creator, audits it, and on a pass sets the submission to APPROVED for
sale. Its security check walked the AST for `import` statements only. Measured:

| Submitted code | Before |
|---|---|
| `import os` | rejected |
| `__import__('os').system('id')` | **APPROVED** |
| `def run(x): return eval(x)` | **APPROVED** |
| `def run(p): exec(p)` | **APPROVED** |
| `getattr(builtins, '__import__')('os')` | **APPROVED** |
| `().__class__.__bases__[0].__subclasses__()` | **APPROVED** |
| `open('/etc/passwd').read()` | **APPROVED** |

The blocklist itself was the tell: it contained the strings `"exec"` and
`"eval"`, which can never appear as a module name — `import exec` is a syntax
error — so listing them caught nothing while making the gate look as though it
covered them. Exactly the audit's signature shape: a control that reads as
wider than it is.

The check now also refuses code-executing builtin calls, object-graph escape
attributes, and those same names reached as string literals. Ordinary strategy
code (pandas, numpy, a class with `__init__` and `__repr__`) still passes —
asserted, because a gate that refuses everything is not a fix.

**Stated in the code, not implied: this is a filter, not containment.** A static
check on adversarial source can always be worked around; what it buys is that
the obvious attempts do not sail through an automatic approval. Real containment
is `ai/sandbox/` (item 19), which runs code under rlimits with no network and a
scrubbed environment. The two are complementary and neither replaces the other.

**`portfolio/strategy_allocator.py` — done, three defects · HIGH**
(`tests/unit/test_strategy_allocator_limits_hold.py`, 10 of 18 fail on the
pre-fix tree). It decides what fraction of the book each strategy gets.

1. **The per-pod concentration cap was violated by the code enforcing it.**
   `_sharpe_proportional` clipped to `MAX_WEIGHT_PER_POD` and then divided by
   the reduced sum, which scales the clipped weight straight back over the cap.
   Measured: `sharpes [9.0, 0.5, 0.5]` → `[0.8, 0.1, 0.1]` against a cap of
   **0.4**. A risk limit that does not limit — and `CLAUDE.md` forbids weakening
   a risk gate, so this one arrived weakened. Replaced with water-filling: cap
   whoever is over, redistribute the excess to those still under, repeat. When
   every pod is at the cap the total is `n × cap`, and that remainder now stays
   **unallocated** rather than being scaled away — scaling it away is the bug.
2. **Strategies that all lose money received the whole book.** Every Sharpe
   negative → the clamped total is 0 → the fallback returned `ones(n) / n`, an
   equal split of 100% of capital across strategies that were all losing.
   Allocates nothing now.
3. **Correlations were computed over invented returns.** Shorter histories were
   zero-padded to the longest, so a pod with 3 days against one with 200
   contributed 197 fabricated 0.00% days. Zero is not "no data", it is "flat
   that day" — a measurement nobody made, feeding the optimiser that allocates
   capital. Measured, the padding turned a true correlation of 1.0 into 0.0578.
   It uses the overlapping window now, and reports identity ("unknown") when
   the overlap is too short to measure.

**`database/repositories/tick_data_repository.py` — NOT done, and it needs a
decision rather than a drive-by fix.**

The finding, measured: every tick written through this repository defaults to
`quality="good", confidence=1.0`.

```python
async def insert_tick(..., quality: str = "good", confidence: float = 1.0, ...)
#                            database/models.py:709,711 default the same way
```

That is a maximum-confidence claim nobody made, and it bypasses
`data_layer/quality/engine.py::DataQualityEngine`, which exists to compute
exactly these two fields. Same shape as the other findings above: a default that
asserts a measurement.

**Why it is not fixed here.** The obvious fix — default to "unknown" — needs
`TickQuality` to *have* an UNKNOWN member, and it does not
(`data_layer/types.py:62`: GOOD, STALE, SUSPECT, REJECTED). Adding one is a
domain change that ripples through `data_layer/types.py`'s own
`quality: TickQuality = TickQuality.GOOD` default, `orchestrator.py:720,1225`
(`TickQuality(cached.get("quality", "good"))`), the gold manager and the
normalisation pipeline — and it needs an answer to a question this session
should not settle alone: **is a tick of unknown quality usable for trading?**

Note that every downstream filter tests `quality != TickQuality.REJECTED`, so
"good" and "unknown" behave *identically* today. The change is therefore safe
behaviourally and purely about honesty of the record — which is why it is worth
doing, and why doing it in one place while `types.py` and the orchestrator keep
defaulting to "good" would leave three contradicting defaults and be worse than
the current state.

**Do:** add `TickQuality.UNKNOWN`, decide whether it is tradeable, change all
four default sites together, and cover the repository's real behaviour
(insert/bulk-insert/range queries/retention delete) — which is item 5's actual
done-condition for this module.

**Note for whoever takes the next module.** `monetization/__init__.py` and
`payments/crypto/__init__.py` re-export each singleton under its own module's
name, so `import monetization.payment_processor as m` binds the *instance* and
every `monkeypatch.setattr(m, ...)` silently lands on the object rather than the
module. Reach for `sys.modules["..."]` instead. This cost time on two of the
three modules tested so far.

### 6. `payment_gateway._process_crypto` reads the currency from a free-text field · MEDIUM

```python
currency = (payment.description or "BTC").strip().upper()
```

`payment.description` is a description. A blank one silently becomes **BTC**, so
a user paying in ETH could be handed a Bitcoin address. Since F267 the generator
raises on an unknown currency rather than inventing one, which contains the
blast radius — but the BTC default is still a guess about which chain a user's
money is on.
**Do:** carry the currency in its own field; refuse when it is absent.
**Done when:** a payment with no explicit currency is rejected, not defaulted.

**Status: fixed.** `Payment.currency` is its own field, and `_process_crypto`
raises when it is blank rather than defaulting. The address generator's own
check does not cover this and never did: `"BTC"` is a *known* currency, so a
defaulted guess passes validation and produces a perfectly valid address on the
wrong chain. Tests: `tests/unit/test_payment_currency_is_explicit.py` — 8 of 9
fail on the pre-fix tree.

This is also `payments/payment_gateway.py`'s first test, so it comes off item 5's
list of eight untested modules. `_process_bank` still reads
`"bank_code:account_number"` out of `description`, which is the same overloaded
field — but it *refuses* when the value is absent rather than defaulting, so it
is a readability problem, not this defect.

### 7. OANDA adapter is not venue-verified · HIGH — owner-blocked

`brokers/oanda*.py` is excluded from coverage and has never been run against
OANDA's sandbox from this session. Live OANDA is the next milestone, and F267
is exactly what "looks right, never executed against the real venue" produces.
**Do (owner):** provide practice-account credentials, or run the adapter against
the sandbox and share the transcript.
**Done when:** an order round-trips against OANDA practice and the fill is
reconciled.

### 7b. `get_order` is missing on OANDA, and the gap is charged to the broker · HIGH

**Found while writing this list, by checking F107 rather than trusting its
status.** F107's headline defect *is* fixed: `place_market_order` now exists on
the OANDA connector, is `async`, returns `MarketOrderResult`, and its signature
accepts exactly the keywords `execution/trade_executor.py:409` passes. When the
audit probed it, `hasattr(..., "place_market_order")` was `False`.

What survives is narrower and still live. `AsyncOANDAConnector` is
`brokers.oanda.OANDABroker`, which is **not** a `BrokerConnector` subclass — so
Python never enforces the ABC — and it does not implement `get_order`, one of
that ABC's eight abstract methods. The path is reachable:

```
api/advanced_orders.py:294  manager.get_order(order_id, user_id=...)
brokers/manager.py:410        return broker.get_order(order_id)   # AttributeError on OANDA
brokers/manager.py:412        self._record_failure(exc); raise
brokers/manager.py:687        _consecutive_failures[name] += 1
brokers/manager.py:707        -> resilience.service_circuit_breakers.broker_breaker
```

So a **missing client-side method is reported as broker unhealth**. Repeated
order-status lookups can trip the broker circuit breaker against an OANDA
account that is entirely healthy, and tripping that breaker stops trading.

**Do, in two parts, and keep them separate:**

1. **Now, and verifiable here:** `manager.get_order` must tell "this broker does
   not implement the call" apart from "the broker call failed". Only the second
   is a health signal. A `NotImplementedError`/`AttributeError` from the
   connector should raise a capability error that does **not** touch
   `_record_failure` or the breaker. Test it by configuring a connector without
   `get_order` and asserting the breaker's counter is unchanged.
2. **Owner-blocked, with item 7:** implement `get_order` on the OANDA connector
   against `GET /v3/accounts/{id}/orders/{orderID}`. **Do not write this from
   the API docs and call it done** — that is precisely the F267 shape: code that
   looks right and has never been executed against the venue. It needs a
   practice-account round-trip.

**Also:** make `OANDABroker` inherit `BrokerConnector`. The ABC would have caught
this at import. Check the other connectors for the same gap before assuming it is
only OANDA.

---

## P2 — Measurement integrity (rest of Phase F)

### 8. Coverage headroom · RESOLVED by the merge, keep the rule

Was 0.54 points (71.06% against a 70% floor) on this branch alone. Merging
`main` brought well-tested code and it is now **73.62%** — 3.62 points of
headroom, which is comfortable.

The rule this item existed for still stands: when a commit tips coverage under
the floor, the fix is to test the package that dropped it — **not** to remove a
package from `[run] source` or lower the floor. Both restore the number by
shrinking what it describes, which is the F221 defect returning.

### 9. Coverage still measures 38.6% of the application · MEDIUM

Outside `[run] source`: `api/` (42,233 statements), `scripts/` (15,106),
`data_layer/` (11,040), root (10,302), `analysis/` (6,690), `security/` (6,632),
`research/` (5,521), `data/` (3,803), `nuclear/`, `brain/`, `charting/`,
`data_feed/`. `api/` is the largest unmeasured package in the repository and it
is the whole public surface.
**Do:** add packages one at a time, each with the tests to keep the floor.
`security/` first — it is the smallest of the high-risk ones at 6,632.
**Done when:** measured share is above 60%, printed by
`scripts/coverage_scope_report.py` in CI.

### 10. `execution/` files still omitted, with measured debt · MEDIUM

Recorded in `.coveragerc`, not hidden: `execution/engine.py` 76.11%,
`core/decision/HOPEFXDecisionEngine.py` 64.71%, `execution/hopefx_engine.py`
63.05%, `execution/fix_adapter.py` 35.00%, `execution/execution.py` 17.75%.
`engine.py` is 4 points from the gate.
**Do:** test `engine.py` to 80% and delete its omit line first.
**Done when:** each file is either measured or carries a current number.

### 11. F223 — 75 test files named after the metric · HIGH

`test_coverage_boost_execution.py`, `test_brokers_low_coverage.py`,
`test_execution_coverage4.py`… and 1,125 test functions carry no assertion of
any kind (6.9% of the suite), concentrated in exactly those files.

These are not empty — they are "does not raise" smoke tests, which is a weak but
legitimate pattern. **The real defect is that the name claims more than the test
checks**: `test_write_k8s_configmap_skips_outside_pod` asserts nothing about
skipping, so if that method began making a live Kubernetes call outside a pod,
the test would still pass.
**Do:** on kill-switch, risk and execution files, give each assertion-free test a
real assertion or a name that admits what it does. Do not delete them wholesale.
**Done when:** no assertion-free test remains in `risk/`, `execution/` or
`kill_switch` coverage files.

### 12. F104 — the job named "Coverage gate (>=70%)" cannot fail · HIGH

`tests.yml:500-595`. Four steps: checkout, download artifact, extract
percentage, post PR comment. No `exit 1`, no `core.setFailed`. It renders a FAIL
badge into a PR comment and exits 0. Worse, `tests.yml:525-534`:

```python
try:   ... parse coverage.xml ... print(f'{combined:.1f}')
except Exception:  print('0.0')
```

A missing or corrupt `coverage.xml` renders "0.0%" — displayed as failing — and
still passes. The threshold that does block is `--cov-fail-under=70`
(`ci.yml:373`, `tests.yml:124`), so coverage is genuinely gated; this *second*
job is decoration that reads as a gate.
**Do:** make it fail on a real threshold, or rename it so it does not claim to
be a gate. **Done when:** its name and its exit code agree.

**Status: fixed — it fails now, and it was also reporting the wrong number.**

An `Enforce the coverage gate` step exits 1 below 70%, placed after the PR
comment (with `if: always()`) so a failing gate still leaves the author the
figure rather than a bare red check.

The `except Exception: print('0.0')` path is gone: a missing or corrupt
`coverage.xml` now fails the step. "I could not measure" is not "you scored
zero", and it certainly is not "you passed".

**A second defect this surfaced.** `(line_rate + branch_rate) / 2` is not the
figure the threshold checks. coverage.py reports covered over valid across lines
*and* branches together; averaging two rates computed over different
denominators gives a different number. Measured on a real report:

| Formula | Result |
|---|---|
| `(line_rate + branch_rate) / 2` (old) | 83.55% |
| `(lines_covered + branches_covered) / (lines_valid + branches_valid)` (new) | **85.25%** |
| what `pytest --cov` printed | **85.25%** |

So the badge on every PR showed a figure biased low and compared it against the
same 70. Both scripts were extracted from the YAML and run against a real
report, a corrupt one, a missing one, and at/above/below the threshold.

Locked in by `tests/unit/test_coverage_gate_can_fail.py` (4 of 6 fail on the
pre-fix tree).

**F103 is fixed** — not by me. Main's commit `4aa7ec6` wired `brain/` and
`news/` into `.coveragerc`, turning "No data to report" into real numbers
(brain 50.52% → above 70%, news 45.95% → above 70%). Merged into this branch.

---

## P3 — The AI Core

**Status: items 13–19 are built, tested and pushed.** Plan and per-task status:
`docs/audit/plans/2026-09-05-ai-core.md`. The sections below are kept as written
so the original findings stay legible next to what was done about them.

| Item | Delivered | Where |
|---|---|---|
| 13 · Gateway | chain, budget, audit, guardrail binding, real vendor adapters, real health probe | `ai/gateway/` |
| 14 · Tool bus | dual gate: `ToolPermissionRegistry.review` **and** `enforce_agent_action` — the latter's first production caller | `ai/tools/bus.py` |
| 15 · Response cache | keyed on prompt + model + tool state; a failure is never cached; a hit is not charged | `ai/cache/` |
| 16 · Evals gate | fails closed on no report, unknown target, stale report, failed required case, score below bar | `ai/evals/` |
| 17 · Guardrails | input screening, fencing, output validation without coercion, corroborated severity ceiling | `ai/guardrails/` |
| 18 · AI Core page | seven read endpoints, five workspaces, every panel on live state | `api/ai_core.py`, `frontend/src/pages/AICore.tsx` |
| 19 · Sandbox | rlimits, env allowlist, no-network preamble; containment proven with the static pre-filter disabled | `ai/sandbox/` |

Two things were added beyond the original items, both because the work exposed
them: an ordered per-role **chain editor** whose output the gateway actually
reads (`docs/audit/plans/...` Task 14), and a **model catalogue** whose review
dates expire in CI, so the defaults cannot go stale unnoticed a second time
(Task 15).


`docs/audit/AI_CORE_SPEC.md` is written. **The AI Core is not built.** Of the
nine concepts in §3, four exist as prerequisites and five have no implementation.
There is no AI Core page (71 pages, zero matches for "AI Core", "orbital" or
"department"), no local model service — `api/brain.py` calls ollama per request —
and no sandbox.

To answer the questions asked directly: **no**, the agent and the LLM do not
start with the app today, because there is nothing to start; the API keys reach
external models on demand only.

### 13. AI Gateway · NOT BUILT
One entry point for every model call: routing, timeouts, retries, budget
ceilings, and a per-call audit record. Everything below depends on it.

### 14. MCP tool bus · NOT BUILT
The typed tool surface the agent acts through. Every tool call must pass
`enforce_agent_action` — which exists (F260) and is wired to seven predicates,
so this is the piece that gives that gate something to gate.

### 15. Response cache · NOT BUILT
Keyed on prompt plus model plus tool state, with explicit invalidation.

### 16. Evals gate · NOT BUILT
A scored suite that must pass before sandbox → live. Spec §12 makes this the
promotion gate.

### 17. Guardrails · NOT BUILT
Output validation between the model and any action. `news/geopolitical_llm.py`
(F261) is the pattern to follow: fenced untrusted input, strict parsing, a
severity ceiling for uncorroborated claims.

### 18. AI Core page · NOT BUILT
The operator surface: what the agent did, what it proposed, what was refused and
why. **Read `.claude/skills/ui-ux-pro-max/SKILL.md` first** — it is installed and
the other 71 pages follow it.

### 19. Sandbox · NOT BUILT
Where an agent runs without touching a real venue. Prerequisite for item 16.

**Recommended order:** 13 → 17 → 14 → 19 → 16 → 15 → 18. The gateway first
because everything routes through it; guardrails before the tool bus so the bus
is never briefly unguarded.

---

## P4 — Hygiene and documentation

### 20. `static/` is a gitignored build artifact that tests need · FIXED, note the cause
Fixed this session in `conftest.py`: three tests could only pass on a machine
that had once run the frontend build, so they failed in CI on **every branch**.
The remaining question is whether CI should build the frontend instead of using
a placeholder shell. **Do:** decide, and if yes add the build step to `ci.yml`.

### 21. F216 / F217 — the `data/` ↔ `data_layer/` boundary is undefined · MEDIUM
`CLAUDE.md` now says plainly that no document defines it, rather than inventing
one. Until it is agreed, extend the package a module already lives in and say
which you chose in the PR. **Do (owner + engineer):** agree the boundary, then
write it down once. **Done when:** one document defines it and CLAUDE.md points
at that document.

### 22. `REMEDIATION_PLAN.md` is stale · MEDIUM
80 items marked open, many fixed and verified. A tracker that misreports state is
the documentation form of this audit's whole subject.
**Do:** reconcile against `FIX_PHASES.md` and this file, or delete it and leave
one tracker. **Recommended:** delete it. Two trackers is how it drifted.
**Done when:** exactly one document claims to track remaining work.

### 23. Owner-blocked · NEEDS YOU
* **Where the credential exposure was seen.** I scanned this repository's history
  with 13 patterns and found nothing. If it was seen elsewhere, that system needs
  the same scan — I cannot find what I cannot see.
* **VPS capability report on the real box.** `scripts/vps_capability_report.py`
  has only ever run here. Its output from this container says nothing about
  production.
* **Hive chat: superadmin vs user.** Behaviour still unspecified.
* **Refund policy.** Settable at Superadmin → Financial → Refund Policy; the
  applied policy is stamped on each refund, so changing it never rewrites
  history. It needs a value chosen deliberately.

---

### 24. F271 — the dependency scan reads the manifest that pins nothing · HIGH

`trivy fs .` reported `requirements.txt  pip  0` for as long as it has run.
That zero means "no version I could resolve", not "no vulnerabilities":
`requirements.txt` holds ranges (`chromadb>=0.4.0`), and the file with the real
pins, `requirements.lock`, is not a name Trivy recognises as a lock format.

The merge of `v0/hopefx-remediation` added a `uv.lock` that Trivy *does* read,
and it immediately reported 6 findings (2 CRITICAL, 4 HIGH) — including
chromadb 1.5.9 with two unfixed arbitrary-code-execution CVEs, which this
platform installs today.

All six are now accepted in `.trivyignore.yaml` with an exploit-path argument
and a 2026-12-05 expiry (chromadb is embedded-client only, ecdsa and nltk are
transitive and unreachable). **That closes the six, not the hole.**

**Also:** `security-scan.yml:139` passes `--ignore-unfixed`, which drops every
CVE with no upstream fix, permanently and with no record. All six of these have
no fix, so all six vanish there — that job reported success on the same commit
where `ci.yml` reported two criticals. A green "Trivy" check means "no CVE
somebody else has already fixed", not "no CVE". Decide whether that job should
stay lenient; if it does, its name should say so.

**Do:** make `requirements.lock` visible to the blocking scan — copy it to a
Trivy-recognised name in the job, or scan it explicitly. Then measure what comes
back; the number is currently unknown and could be large. Do **not** delete
`uv.lock` to restore green: it is the only manifest the scanner can currently
read, and removing it is the F221 defect.
**Done when:** the scan resolves concrete versions for every production
dependency, and its report is the pinned set rather than the range set.

**Status: fixed, and it was hiding real CVEs.** `ci.yml` now builds a
Trivy-readable manifest from `requirements.lock` and scans it with
`--exit-code 1` and the same `.trivyignore.yaml`. Measured 2026-09-06:

| Manifest | Findings |
|---|---|
| `requirements.txt` (ranges) | 0 — "no version I could resolve" |
| `uv.lock` | 6 (2 CRITICAL, 4 HIGH), all accepted |
| **`requirements.lock` (297 pins)** | **11 (3 CRITICAL, 8 HIGH)** |

The five extra findings all **had upstream fixes** and were therefore invisible
rather than accepted — a worse failure than seeing a CVE and arguing for it:

* `cryptography` 49.0.0 → **50.0.0** — CVE-2026-69247, PKCS#7 EnvelopedData
  decryption exposes a Bleichenbacher oracle through distinguishable errors.
  This platform uses `cryptography` for token and secret encryption.
* `nltk` 3.10.0 → **3.10.3** — CVE-2026-79675 (CRITICAL, JVM argument
  injection), CVE-2026-71513 (RCE via `AllowlistUnpickler` dotted-name bypass),
  CVE-2026-72818, CVE-2026-78680.

Both floors are raised in `requirements.txt` and `requirements-ci.txt` as well
as pinned in the lock, so a regenerated lock cannot drop back below the fix. The
running environment was already on both fixed versions — the lock was behind
what CI installs — and all 1,478 crypto/auth/NLP tests pass on them.

After the upgrade the pinned scan reports **0 un-accepted findings**, with
exactly the six pre-existing acceptances suppressed (verified with
`--show-suppressed`).

**`--ignore-unfixed` is gone from `security-scan.yml`.** That job's output is
the SARIF that populates the Security tab, which is precisely where an unfixed
CVE belongs — it cannot be resolved by a bump and needs a human decision.
Suppression now goes through `.trivyignore.yaml` for both jobs, so there is one
list of accepted risks with one set of expiry dates.

Locked in by `tests/unit/test_dependency_scan_reads_the_pins.py` (9 of 10 fail
on the pre-fix tree), which asserts the lock is scanned, the scan can fail,
neither workflow drops unfixed CVEs, both read the same acceptance file, and
both floors hold.

## What was fixed this session

For continuity, not for action.

| Finding | Summary |
|---|---|
| **F267 · CRITICAL** | Crypto deposit addresses nobody held the key to. `0x` + `sha256(...)` for ETH/USDT-ERC20 is valid Ethereum syntax with no private key; BTC returned the literal string `hopefx_btc_<uid>`. Ported to hdwallet v3, checked against published BIP44/BIP84 vectors. |
| **F99** | The placeholder-secret test skipped when the validator did not know a variable — the one case it existed to catch. 8 of 14 published placeholders were skipping, including `DB_ENCRYPTION_KEY` (silently disabled field-level encryption) and `BOOTSTRAP_SUPERADMIN_PASSWORD`. |
| **F105** | `risk/manager.py` was excluded from the `risk/ ≥ 80%` gate as "covered by integration tests". It measures 89.65% on the **unit** suite. `risk/` now reports 92.43% including the risk core. |
| **F108** | 14 tests skipping since their first commit against API names that never existed. Now 46 tests, 0 skipped. |
| **F221** | Coverage gate measured 26.9% of the application. Now 38.6%, printed in CI. |
| **F268** | 33 log calls that raise instead of logging, all on exception paths — including `brain/brain.py`'s CATASTROPHIC LOSS alert, which had never emitted. |
| **PR #315 CI** | Wordmap ambiguity guard orphaned by the merge; a test asserting the F145 defect; three SPA tests needing a gitignored build; 37 lint errors; `SocialFeed.tsx` lost its imports. |
