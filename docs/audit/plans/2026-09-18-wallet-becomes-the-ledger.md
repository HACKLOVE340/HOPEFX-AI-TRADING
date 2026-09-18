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

## 3. Task 2 — debit the wallet on withdrawal

**Files**
- Modify: `api/payments.py::fiat_withdraw`
- Test: a new `test_withdrawal_debits_the_wallet_ledger.py` under `tests/unit/` (does not exist yet)

Only reachable once Task 1 lands, because a debit needs funds.

`debit_wallet` already consults the AML gate itself, and the endpoint already
calls `_screen_withdrawal_for_aml`. Keep **both**: the endpoint's screen
produces the precise 403 with the gate's reason and honours
`HOPEFX_REQUIRE_AML_STRICT`; the ledger's screen is the one that cannot be
bypassed by a future caller that forgets. Two screens on a money path is
defence in depth, not redundancy — but say so in a comment, or someone deletes
one as duplication.

Map the refusals to honest status codes, and do not collapse them:
`"Insufficient subscription balance"` → **402**, `"Wallet not found"` → **404**,
AML refusal → **403**, `"Ledger write failed; movement refused"` → **503**.
A withdrawal that was refused because the ledger write failed is not the same
event as one refused for want of funds, and an operator reading a 402 for a
failed database write will debug the wrong thing.

### Steps

- [ ] `test_a_withdrawal_writes_a_debit_row` — assert the row and the new balance.
- [ ] `test_a_withdrawal_over_balance_is_refused_and_writes_nothing` — assert 402 AND that no row appeared.
- [ ] `test_the_daily_count_rule_can_now_fire` — the point of the whole exercise: six same-day withdrawals, the sixth refused by AML's 5-per-day rule, which is impossible today.
- [ ] Remove the `WARNING — NOT YET PERSISTED` block from the docstring **only when it stops being true**.

---

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
