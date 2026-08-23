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

### B2 — creator balance persistence · BLOCKED ON YOU
* **F208** — creator balances, sales and payouts exist only in RAM. **There is
  no table for any of them** — this is a schema decision, not a write-path fix.
  Cheapest possible moment: nothing to migrate. Needs your call on what a
  creator balance, a sale and a payout look like as tables.

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

## Phase D — AI Core prerequisites
Do these immediately before AI Core work, not after.

* **F139** — cross-pod kill-switch propagation denied (no RBAC in
  `deployments/k8s/`). An AI kill switch inherits this.
* **F130** — self-healer patch signing off, key set nowhere.
* **F184** — `_run_tests()` returns `True` on `FileNotFoundError`: "could not
  test" recorded as "tests passed" on the gate that admits a patch.

## Phase E — Risk gates
* **F142** — the ACTIVE paper path has no risk layer at all.
* **F84** — the data-layer gate is skipped in the condition it exists for.
* **F94** — regime detection never runs → **every position sized at 0.5×**.
* **F61/F107** — `BROKER_TYPE=oanda` cannot place an order, and the k8s
  ConfigMap already sets it.

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
