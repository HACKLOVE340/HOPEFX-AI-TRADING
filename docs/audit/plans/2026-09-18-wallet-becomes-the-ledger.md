# The fiat wallet becomes the ledger the money path writes through

**Closes:** `WALLET-DEAD` (P0, Money) · unblocks `AML-UNREACHED` (P0, Compliance)
**Owner decision, 2026-09-18:** the wallet is the ledger, not retired.
**Skills:** `hopefx-money-precision`, `hopefx-dead-controls`, `test-driven-development`,
`verification-before-completion`, `postgresql-table-design` (Task 1's constraint).

---

## 1. What is actually wrong

`payments/wallet.py::WalletManager` is ~700 lines of correct exact-`Decimal`
ledger — balance validation, a reconciliation check that refuses regardless of
`HOPEFX_INVARIANT_MODE`, a rollback when the ledger write is refused, freeze and
transfer paths. **No production module calls `credit_wallet` or `debit_wallet`.**
Measured, not assumed:

```
$ grep -rn "credit_wallet\|debit_wallet" --include="*.py" . | grep -v .venv | grep -v ^./tests/
payments/wallet.py:600      self.debit_wallet(...)     # transfer_between_wallets
payments/wallet.py:608      self.credit_wallet(...)    # transfer_between_wallets
payments/wallet.py:621      self.credit_wallet(...)    # transfer_between_wallets
```

Both sides are dead. `wallet_transactions` is therefore permanently empty, which
is what makes AML's daily-count and daily-volume rules unfireable and what
`health_check_service.py` aggregates to zero.

### The trap, and why the obvious fix is worse than nothing

`_apply_movement` auto-creates a wallet on **credit** (`sign > 0`) but on
**debit** refuses with `"Wallet not found"`, and then refuses again with
`"Insufficient subscription balance"` when `before < amount`.

So wiring `POST /payments/withdraw` straight through `debit_wallet` — the
one-line change this finding invites — would make **every withdrawal fail**,
write **no** ledger row, and leave AML's daily rules exactly as unfireable as
they are today. It would satisfy "a production caller exists" and deliver
nothing. **Credit must land first.** That is the whole reason for the task
order below.

---

## 2. Task 1 — credit the wallet when a deposit is CONFIRMED

**Not when the PaymentIntent is created.** `_fiat_deposit_impl` creates an
intent; no money has moved at that point. Money is received at
`payment_intent.succeeded`, which arrives at the signature-verified webhook
`api/billing.py::stripe_webhook`.

**Files**
- Modify: `api/billing.py` (dispatch `payment_intent.succeeded` to the ledger)
- Modify: `database/models.py` (`WalletTransaction` — the constraint below)
- Create: `alembic/versions/<rev>_wallet_txn_reference_unique.py`
- Test: a new `test_deposit_credits_the_wallet_ledger.py` under `tests/unit/` (does not exist yet)

### Idempotency is the whole risk in this task

A Stripe webhook can be delivered more than once — retries, replays, and
at-least-once delivery are normal, not exceptional. A repeated
`payment_intent.succeeded` that credits twice **creates capital out of
nothing**. That is a P0 in its own right, and it must be refused by the
*database*, not by a read-then-write in Python, which races.

`WalletTransaction.transaction_id` is already `unique=True`, but that id is
generated per call (`_new_transaction_id`), so it cannot deduplicate. `reference`
— where the Stripe id would live — is **not** unique. So:

- Add `UniqueConstraint("user_id", "reference", name="uq_wallet_txn_user_reference")`,
  with the migration. A partial index excluding `NULL` is required, because
  existing rows legitimately carry `reference = NULL` and Postgres treats NULLs
  as distinct anyway — state this explicitly in the migration rather than
  relying on that behaviour being remembered.
- The credit passes `reference=f"stripe:{payment_intent_id}"`, and an
  `IntegrityError` on that constraint is caught and treated as **success,
  already applied** — not an error. A retried webhook must return 200, or Stripe
  keeps retrying forever.

### Money precision

Stripe amounts are **integer cents**. Convert `Decimal(cents) / 100` — never via
`float`, never `Decimal(x)` on a float. `_validate_amount` refuses anything that
is not a whole number of cents, so a wrong conversion fails loudly rather than
silently rounding.

### Steps

- [ ] Write `test_a_confirmed_deposit_credits_the_wallet` — drive the webhook, assert a `wallet_transactions` row and the balance.
- [ ] Write `test_a_replayed_webhook_credits_only_once` — deliver the SAME event twice, assert exactly one row and one balance movement. **This is the test that matters.**
- [ ] Run both; watch them fail on the pre-fix tree.
- [ ] Add the constraint + migration; `python scripts/schema_migration_check.py --check` must stay clean.
- [ ] Wire the dispatch; make both tests pass.
- [ ] `python scripts/correction_register.py --id WALLET-DEAD` — expect it to move off OWNER.

---

## 3. Task 2 — debit the wallet on withdrawal, BEHIND A FLAG

**Files**
- Modify: `api/payments.py::fiat_withdraw`
- Test: a new `test_withdrawal_debits_the_wallet_ledger.py` under `tests/unit/` (does not exist yet)

Only reachable once Task 1 lands, because a debit needs funds.

### It ships default-off, and that is not caution

`api/billing.py::get_balance` says in its own docstring "Return the
authenticated user's wallet balance" and then reads the **broker account**,
falling back to the **subscription manager**. It never reads the wallet ledger.

So the number a user sees and the number `debit_wallet` checks come from two
different sources, and the ledger has no historical credits — nothing wrote it
until Task 1. Wiring the debit unflagged means every withdrawal refuses with
`402 Insufficient subscription balance` for users the UI is simultaneously
telling they have funds. That is not a safety improvement, it is an outage that
looks like a money bug, and the pressure to "fix" it would land on the balance
check — which is a real gate.

`WITHDRAWAL_DEBITS_LEDGER` defaults to **false**. Off, the endpoint behaves
exactly as it does today. On, it writes through the ledger. Flipping it is a
deliberate act, taken after wallet balances are reconciled against whatever is
authoritative — a separate question, tracked as `BALANCE-SOURCE-SPLIT`.

### The refusal mapping was incomplete — there are eight, not four

`debit_wallet` and the `_apply_movement` beneath it can refuse for eight
distinct reasons. Collapsing them hides a **ledger-corruption event behind a
402**, and an operator reading "insufficient funds" for a failed database write
debugs the wrong thing for an hour.

| Refusal from the ledger | HTTP | Why not something else |
|---|---|---|
| `Amount must be positive` / `whole number of cents` / `not a valid number` | **422** | The request is malformed; the caller can fix it. |
| `Wallet not found` | **404** | Nothing to debit. Distinct from having a wallet with no money. |
| `Insufficient {kind} balance` | **402** | The one case that genuinely is "not enough money". |
| `Wallet is {status}` | **409** | An operator FROZE this wallet. Deliberate, and must not read as a balance problem or the freeze looks like a bug. |
| `Withdrawal blocked: {reason}` (AML) | **403** | Refused by compliance, carrying the gate's own reason. |
| `Withdrawal temporarily unavailable (compliance check failed)` | **503** | The gate errored and failed closed. Retryable; not the caller's fault. |
| `Balance did not reconcile; movement refused` | **500** | **Corruption.** Decimal arithmetic on whole cents is exact, so a mismatch is not drift. Never a 4xx: nothing the caller did caused it and nothing they change will fix it. |
| `Movement refused by invariant: {reason}` | **409** | A constitutional invariant refused. Distinct from AML and from balance. |

### Do NOT loosen either AML screen

`debit_wallet` fails closed **unconditionally**; `_screen_withdrawal_for_aml`
mirrors `require_kyc` — strict in production, pass-through in development. That
asymmetry was deliberate, and `_screen_withdrawal_for_aml`'s docstring gives the
reason: the ledger method had no dev callers, and "a blanket fail-closed here
would reject every local and test run — which is how a gate gets disabled by
whoever is trying to work."

**Task 2 breaks that premise.** Wiring the endpoint through `debit_wallet` gives
that method dev callers for the first time. In development the endpoint's screen
passes through and the ledger's screen still fails closed, so every local and
test withdrawal refuses — and the next person to hit it "fixes" it by loosening
a real fail-closed gate, exactly as predicted.

The answer is not to relax either one. It is to make a gate **reachable**: the
tests wire a real `AMLGate` over a real session factory, as
`test_withdrawal_is_screened_by_aml.py` already does. Two screens on a money
path is defence in depth, and a comment must say so, or someone deletes one as
duplication.

### Steps

- [ ] `test_the_flag_defaults_to_off_and_nothing_is_debited` — the default path is unchanged.
- [ ] `test_a_withdrawal_writes_a_debit_row` — flag on: assert the row and the new balance.
- [ ] `test_a_withdrawal_over_balance_is_refused_with_402_and_writes_nothing` — assert the status AND that no row appeared.
- [ ] `test_a_frozen_wallet_is_409_not_402` — the mapping is load-bearing, not decorative.
- [ ] `test_a_reconciliation_failure_is_5xx_not_4xx` — corruption must never read as a client error.
- [ ] `test_the_daily_count_rule_can_now_fire` — the point of the exercise: six same-day withdrawals, the sixth refused by AML's 5-per-day rule, impossible before this.
- [ ] Amend the `WARNING — NOT YET PERSISTED` docstring to say what is true with the flag on and off, rather than deleting it — nothing is disbursed either way.

## 4. Out of scope, stated so it is not mistaken for done

- **Actual disbursement.** Task 2 records the debit; it does not send money.
  `FIAT_PROVIDER` remains unconfigured and the endpoint still queues nothing.
  The ledger is the point here, not the payout rail.
- **Where the balance comes from other than Stripe deposits.** `/billing/balance`
  reads the broker account and the subscription manager. Reconciling those
  against the wallet is a separate question and a separate finding.
- `_validate_amount`'s comment says `balance_after` is "persisted to a Float
  column". It is `Numeric(18, 2)`. Correct the comment; the reasoning it gives
  for refusing sub-cent amounts stands on its own.

## 5. How this gets proved

Per-task: the named tests, red before green. At the end: the full fast suite on
**both** interpreters (3.11 and 3.12 — a 3.12-only defect shipped an unloadable
model as recently as this week), `ruff check .`, and
`python scripts/correction_register.py --check` showing WALLET-DEAD off OWNER
and AML-UNREACHED's measured line naming rows it can now count.
