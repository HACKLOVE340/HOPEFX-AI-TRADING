# Slice 2 — Money: the cut, and what it proved

**Status:** cut and proven green in isolation on `origin/main` (`cc7203f`), 2026-09-18.
**Source:** branch `claude/add-new-skills-lys862` at `ea24b4f`.
**Companion:** `LANDING_PLAN.md` §4 (the nine slices) · `SLICE1_MANIFEST.md`.

Reproduce the cut exactly:

```bash
git worktree add --detach /tmp/wt-slice2 origin/main
git -C /tmp/wt-slice2 checkout ea24b4f -- \
    payments monetization social/marketplace.py \
    invariants/enforcement.py invariants/ai.py database/models.py \
    api/payments.py api/billing.py api/superadmin/financial.py
git -C /tmp/wt-slice2 checkout ea24b4f -- <the 21 test files listed below>
cd /tmp/wt-slice2 && PYTHONPATH=$PWD python scripts/api_documentation_generator.py
pytest -m "not slow and not e2e" -q
```

---

## 1. What the plan said, and what the code said

The plan scoped slice 2 as **`payments/`, `monetization/` + tests**. That is 17
changed files. The cut that actually passes is **24 source files**, because
four dependencies were undeclared. None of them was discretionary — each was
found by an import error or a failing assertion, not by judgement.

| # | What the plan missed | Why it had to come forward | Cost |
|---|---|---|---|
| 1 | `invariants/enforcement.py` + `invariants/ai.py` | `payments/wallet.py` imports `enforce_wallet_movement`, which does not exist on `main`. `enforcement.py` is a **single file serving both the money path and the AI control plane** — it cannot be split by slice, and its `enforce_agent_action` needs one new predicate in `invariants/ai.py`. | +173 lines |
| 2 | `database/models.py` | The creator-ledger ORM rows (`CreatorSale`, `CreatorPayoutRow`, `CreatorBalanceRow`) live here and are absent from `main`. They are **nested** class definitions, so a `^class` grep misses them. | +404 / −26 |
| 3 | `social/marketplace.py` | `StrategyMarketplace.split_revenue` — a **revenue split**, i.e. money. 41 of the 62 first-round failures were this one file. | +27 / −3 |
| 4 | `api/payments.py`, `api/billing.py`, `api/superadmin/financial.py` | Three money-path HTTP handlers: the fiat-deposit cent rounding, the crypto deposit address, and the refund policy. | +204 / −10 |

### `social/` is in no slice at all

`social/` is named **nowhere** in `LANDING_PLAN.md` §4. It is not an oversight
in slice 2's scope — it is a gap in the nine-slice partition, and it holds a
money function. Eight files, of which one is changed. **Fix the plan, not just
this slice**: any path that is in no slice is a path that lands in no PR.

### A money fix that lives outside the money slice

`tests/unit/test_money_rounds_to_cents_never_truncates.py` names its own
subject: `api/payments.py::_fiat_deposit_impl`, where `int(10.999 * 100)` is
`1099` — the customer is charged £10.99 for a £10.999 deposit and **the cent
has to come from somewhere**. The defect is money; the file is `api/`, which
the plan puts in slice 7.

A path-based partition cannot keep money defences together, because money
crosses `payments/`, `monetization/`, `social/`, `invariants/`, `database/` and
`api/`. This is the same lesson slice 1 taught in the measurement dimension —
**a gate travels with the subsystem it measures** — restated for money:
*a money control travels with the money, not with its directory.*

### And its corollary, found here

`docs/API_ENDPOINTS.md` is **generated from the registered routers**.
`api/superadmin/financial.py` adds two refund-policy routes, so the slice makes
the committed document stale and `test_api_endpoint_doc_is_generated.py` fails
— a test that is nowhere near `payments/`. The document is regenerated in the
slice rather than copied from the branch head, because the branch head's copy
reflects all nine slices' routers. The diff is exactly two lines.

**A generated document travels with the code that generates it.**

---

## 2. What is deferred, and to where

Four test files were cut and then withdrawn. Each fails for a dependency that
belongs to a later slice, and **no test was weakened or deleted from the branch
to achieve green** — they land with the slice they actually cover.

| Test file | Blocked on | Lands in |
|---|---|---|
| `test_marketplace_runs_code_in_the_sandbox.py` | `ai.sandbox.runner` — the `ai/` package does not exist on `main` | Slice 6 |
| `test_marketplace_audit_catches_escapes.py` | same | Slice 6 |
| `test_creator_ledger_is_actually_persisted.py` | `core/startup_factories.py::init_revenue_ledger` (+783 lines — the runtime wiring for every subsystem) | Slice 7 |
| `test_affiliate_ledger_survives_a_restart.py` | `core/startup_factories.py::init_affiliate_ledger` | Slice 7 |

A test **file** cannot be split across slices, so a file travels to the *latest*
slice it depends on — even when some of its cases would pass here.

### The sandbox refusal is the control working

`monetization/marketplace_submission.py` rejects a submission with
`"Sandbox unavailable (No module named 'ai'); refusing to approve uncontained
code"`. That is fail-closed behaviour, correct, and the reason two marketplace
tests fail in this slice. **It was not relaxed to get green.** A slice that
made uncontained strategy code approvable would have passed its tests and
broken the platform.

---

## 3. Evidence

| Gate | Command | Result |
|---|---|---|
| Slice tests in isolation | `pytest <the 21 files + 11 regression files>` | **650 passed, 0 failed** |
| Full fast suite on the cut | `pytest -m "not slow and not e2e"` | see §4 |
| Lint | `ruff check <all 24 source files + tests>` | **All checks passed** |
| Compile | `python -m py_compile` on every changed `.py` | clean |
| Generated doc | `pytest tests/unit/test_api_endpoint_doc_is_generated.py` | **9 passed** |

The isolation run is not the proof on its own. The **full fast suite** is: the
slice adds seven files outside its declared paths onto `main`, and only a whole-
suite run can show whether anything already on `main` breaks. It did catch one
— the generated-document failure in §1 — which the slice-only run did not.

---

## 4. Suite result

```
$ pytest -m "not slow and not e2e" -q          # in the slice 2 worktree
19164 passed, 39 skipped, 171 deselected in 760.60s (0:12:40)
EXIT=0
```

**Zero failures**, on `origin/main` + slice 2 alone. For comparison, the first
cut of this slice — `payments/` and `monetization/` only, exactly as the plan
scoped it — collected 5 import errors and could not run at all; the second cut
ran 62 failures. The four undeclared dependencies in §1 are the whole of the
difference.

---

## 5. The file list — 46 files

| `api/billing.py` | modified |
| `api/payments.py` | modified |
| `api/superadmin/financial.py` | modified |
| `database/models.py` | modified |
| `docs/API_ENDPOINTS.md` | modified |
| `invariants/ai.py` | modified |
| `invariants/enforcement.py` | modified |
| `monetization/affiliate.py` | modified |
| `monetization/marketplace.py` | modified |
| `monetization/marketplace_submission.py` | modified |
| `monetization/payment_processor.py` | modified |
| `monetization/refund_policy.py` | new |
| `monetization/revenue_split.py` | modified |
| `monetization/stripe_integration.py` | modified |
| `monetization/stripe_live.py` | modified |
| `monetization/subscription.py` | modified |
| `payments/crypto/address_generator.py` | modified |
| `payments/crypto/bitcoin.py` | modified |
| `payments/crypto/ethereum.py` | modified |
| `payments/crypto/usdt.py` | modified |
| `payments/fintech/paystack.py` | modified |
| `payments/payment_gateway.py` | modified |
| `payments/transaction_manager.py` | modified |
| `payments/wallet.py` | modified |
| `social/marketplace.py` | modified |
| `tests/unit/test_access_codes_cannot_be_reused.py` | new |
| `tests/unit/test_affiliate_commission_is_payable_in_cents.py` | new |
| `tests/unit/test_affiliate_commissions_conserve.py` | new |
| `tests/unit/test_creator_ledger_persistence.py` | new |
| `tests/unit/test_creator_ledger_schema.py` | new |
| `tests/unit/test_crypto_deposit_addresses_are_real.py` | new |
| `tests/unit/test_crypto_payment_records_persist_and_verify.py` | new |
| `tests/unit/test_monetization.py` | modified |
| `tests/unit/test_money_rounds_to_cents_never_truncates.py` | new |
| `tests/unit/test_nocode_plan_gate.py` | modified |
| `tests/unit/test_password_hashing_and_jwt_lifecycle.py` | new |
| `tests/unit/test_payment_currency_is_explicit.py` | new |
| `tests/unit/test_payment_processor_reports_reality.py` | new |
| `tests/unit/test_paystack_client_charges_correctly.py` | new |
| `tests/unit/test_refund_policy_api.py` | new |
| `tests/unit/test_refund_policy_applied.py` | new |
| `tests/unit/test_refund_policy_setting.py` | new |
| `tests/unit/test_revenue_split_money.py` | new |
| `tests/unit/test_revenue_splits_conserve.py` | new |
| `tests/unit/test_transaction_state_machine.py` | new |
| `tests/unit/test_wallet_ledger.py` | new |
