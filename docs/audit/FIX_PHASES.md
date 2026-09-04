# Fix phases — backend

## How the work is numbered

Three separate bodies of work, one scheme each — stated here because using
three at once was confusing:

| Track | Numbering | State |
|---|---|---|
| **UI rebuild** | phases **1–12** | **complete** — ~20 pages, 8 shared components |
| **Backend fixes** | phases **A–H** (this file) | starting at A |
| **AI Core build** | not numbered | spec recorded; sequences **after fix phase D**, whose findings are its prerequisites |

Counted as bodies of work, AI Core is the thirteenth. It is lettered out of the
fix sequence rather than numbered into it because it is new construction, not
remediation.

**Owner-blocked, above everything:**
* **Rotate the exposed superadmin credential.** Location not confirmed — the
  tracked tree reads as placeholders. Needs the file or commit named.
* **F95 — CI has not run on `main` for 30+ pushes.** Actions billing. Every
  fix below is unverified by CI until this is green.

---

## Phase A — Money: the payout path *(starting now)*
`monetization/revenue_split.py` · zero tests today · 7 live endpoints

* **F204** — payouts marked `PAID` with no transfer when the Stripe package is
  absent. Balance zeroed. **Fail closed.**
* **F203** — `pending_usd = Decimal("0.00")` destroys money arriving mid-payout.
  Proved: **$40 lost**. Subtract, and lock the read-modify-write.
* **F205** — `logger.exception("…%s error=%s", one_arg)` cannot emit, so failed
  payouts are diagnostically blind while `failure_reason` says "check logs".
* **F206** — `int(amount * 100)` truncates cents against the creator.
* **F207** — every payout claims every historical transaction; reconciliation
  double-counts.
* **Tests written first**, demonstrating each failure before the fix.

## Phase B — Money: persistence and the wallet

### B1 — the wallet write path · DONE
* **F135** — wallet ledger ids collide (timestamp to the second); rows silently
  dropped. **Proved: 50 credits produced 1 distinct id.** Now
  `TXN-%Y%m%d-<uuid4[:8]>`, matching `payments/transaction_manager.py`.
* **F136** — wallet balance is an unlocked read-modify-write. **Proved: $32
  deposited, $4 recorded; and a $100 wallet overdrawn to −$60.** One `RLock`
  now covers read → check → write → ledger row.
* **F138** — `verify_balance_after` is never called. Wired — but *not* by
  calling the predicate from the money path, which would blur the line the
  `hopefx-invariants` skill draws. Added `enforce_wallet_movement` to
  `invariants/enforcement.py` under the existing `ledger` kind, so the violation
  is counted and visible through `enforcement.status`.
* **F234** — readers never took the lock, so a torn balance was still
  observable mid-transfer. A defect in the *first* version of the F136 fix.
* **F235** — sub-cent amounts diverge memory from the `Float` ledger column.
  Refused rather than rounded.
* **F237** — `_load_balance_from_db` restored a commission balance into the
  subscription wallet, and never restored commission at all.

Note on enforcement mode: `HOPEFX_INVARIANT_MODE` defaults to `monitor`, where
`allowed` is `True` even for a CONSTITUTIONAL violation. Money safety therefore
cannot rest on it. The write path refuses on its own exact-Decimal check
regardless of mode; the invariant makes the violation *observable*.

### B2 — creator ledger persistence · DONE
* **F208** — closed. Three tables (`creator_sales`, `creator_payouts`,
  `creator_balances`) plus migration `s1t2u3v4w5x6`. Events are the truth, the
  balance is a re-derivable cache. Money is `Numeric(18,2)` — the first exact
  decimal columns in a schema whose other 104 money columns are `Float`.
* **Refund policy is yours to set** — Superadmin → Financial → Refund Policy,
  stored in `config_store`. The policy applied is stamped on the refund, so
  changing the setting never rewrites history.
* **F238** — the split CHECK was exact on PostgreSQL and refused a correct
  1c + 6c = 7c split on SQLite. Now compared in integer cents.
* **F239** — the refund-policy commit broke the generated API-doc gate. A green
  targeted suite is not a green build.

## How the remaining phases are ordered

Phases A and B are complete. The six below are ordered by **what moves money or
loses it**, not by how many findings each contains. Two things decide position:

1. **Does it move money right now?** A defect on a live path outranks a defect in
   a report, however alarming the report's wording.
2. **Does anything else depend on it?** Phase F (measurement) is deliberately
   late: fixing the coverage gate before the code it measures just produces a
   more accurate picture of a system still doing the wrong thing.

Each phase gets its own executable plan under `docs/audit/plans/` when it starts.
They are separate documents on purpose — one plan per subsystem, each producing
something testable on its own. Writing all six up front would mean five stale
plans by the time we reached them.

| Order | Phase | Why here | Plan |
|-------|-------|----------|------|
| **1** | **E — Risk gates** | The only phase where the defects move money on a path that is running today | `plans/2026-09-04-phase-e-risk-gates.md` |
| 2 | C — Controls that report success without acting | The signature defect; nothing here moves money, but it is why nobody noticed E | not written yet |
| 3 | G — Correctness bugs | Isolated, low blast radius, individually provable. Cheap once C makes failures visible | not written yet |
| 4 | D — AI Core prerequisites | Blocks the AI Core build. Not urgent until that starts | not written yet |
| 5 | H — Config contradicting code | Two ConfigMaps with conflicting safety values; dangerous, but only on a k8s deploy | not written yet |
| 6 | F — Measurement integrity | Last on purpose: measuring accurately is worth most once the code is right | not written yet |

**E before C** is the call worth defending. C contains the most *embarrassing*
findings — a coverage report printing `FULL COVERAGE ✅` from a hardcoded `True`.
But an honest report of a broken risk layer is still a broken risk layer. E is
where money is being sized and routed with no gate at all, on the path
`CLAUDE.md` describes as the platform's current status.

---

## Phase E — Risk gates · NEXT

Full plan: `docs/audit/plans/2026-09-04-phase-e-risk-gates.md`

* **F142** — CRITICAL. **The active paper pipeline has no risk layer at all.**
  `run.py:372-380` routes `PAPER_TRADING=true` to `PaperRunner`, not to the
  engine every other finding examined. `FIXRouter._route` has exactly one gate —
  `if self._halted` — and then goes straight to the broker. No `RiskManager`, no
  sizing, no stop-loss, no drawdown or exposure check. Size is the constant
  `PAPER_ORDER_UNITS` (default 1000).
* **F94** — HIGH, proven by execution. `RegimeRouter.route()` is never called, so
  `_last_regime` stays `"unknown"` from the constructor, and
  `_REGIME_SIZE_MAP.get(name.upper(), 0.5)` therefore **halves every position**.
* **F61 / F107** — CRITICAL. `AsyncOANDAConnector = OANDABroker` is a bare alias;
  the class has no `place_market_order`, which `trade_executor.py:409` calls.
  `BROKER_TYPE=oanda` raises `AttributeError` before an order is built — and
  `k8s-configmap.yaml:33-34` already sets it with `OANDA_PRACTICE=false`.
* **F84** — the data-layer gate is skipped in the condition it exists for.

## Phase C — Controls that report success without acting
The codebase's signature defect.

* **F176** — `invariant_coverage.py` prints `FULL COVERAGE ✅` from hardcoded
  `True`. Interim: print `DECLARED (unverified)`. Real: probes that can fail.
* **F214** — the Phase-3 gate is computed into a health dict and gates nothing.
* **F215** — `.env.example` enables `FEATURE_ONLINE_LEARNING`, the one flag
  whose code default is `False`, gated on a 90-day paper run.
* **F219** — push notifications return `True` with FCM off and zero tokens.
* **F160** — the broker probe reports `ok` from config, not a live check.
* **F159** — critical alerts never leave the log.
* **F240** — *(new, fixed in this session)* the SL/TP monitor swallowed an
  `AttributeError` every poll and checked nothing. Kept here as the reference
  example of the shape.

## Phase D — AI Core prerequisites
Do these immediately before AI Core work, not after.

* **F139** — cross-pod kill-switch propagation denied (no RBAC in
  `deployments/k8s/`). An AI kill switch inherits this.
* **F130** — self-healer patch signing off, key set nowhere.
* **F184** — `_run_tests()` returns `True` on `FileNotFoundError`: "could not
  test" recorded as "tests passed" on the gate that admits a patch.

## Phase F — Measurement integrity
* **F221** — the coverage gate measures **34%** of the application and omits
  the risk manager and the decision engine.
* **F222** — 13 critical modules never named in a test, including
  `payments/crypto/address_generator.py`.
* **F218** — 14 model tables have no migration; they exist only via
  `create_all()`, which never ALTERs.
* **F99 / F105 / F106 / F108** — tests that skip the case they exist for,
  gates that measure the wrong thing, a class that never existed.

## Phase G — Correctness bugs (isolated, low risk)
* **F119** annualised return **34× understated** · **F120** Sortino denominator
* **F125** regime EMA weights the oldest bar **7.4×** the newest
* **F145** features zero-filled **before** scaling — measured **−15σ**
* **F80** wordmap matches bare substrings ("coupon" → severity 7)
* **F81** hedge marked active before the broker call

## Phase H — Config that contradicts the code
* **F98 / F178** — two ConfigMaps named `hopefx-config` with contradictory
  safety values; last `kubectl apply` wins.
* **F216 / F217** — `CLAUDE.md` calls `data/` legacy; it holds the live
  real-time price engine and is imported 22× from production.

---

## Test-integrity work (done, out of band)

Not a numbered phase — it was prerequisite to trusting any verification the
phases above depend on.

* **F240** — the SL/TP monitor never fired a stop (`pos.id` vs `position_id`).
* **F241** — the suite read the developer's `.env`; `app.py:12` loads it at
  import, during collection.
* **F242** — `MagicMock` fixtures silently diverging from the real object.
* **F243** — the paper broker's test isolation was bypassed by an explicit
  namespace, so state accumulated in Redis across runs.
* **F244** — a fresh worktree omits gitignored build artifacts (`static/`), so
  four tests fail for reasons unrelated to the change under test.

Result: the fast suite is **17171 passed, 0 failed** — green for the first time
in this audit. Every phase below can now be verified against a clean baseline,
which was not previously true.
