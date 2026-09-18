# 0021. The fiat wallet is the ledger the money path writes through

- Status: accepted
- Date: 2026-09-18

## Context

`payments/wallet.py::WalletManager` is roughly 700 lines of correct exact-`Decimal`
ledger: balance validation, a reconciliation check that refuses regardless of
`HOPEFX_INVARIANT_MODE`, a rollback when the ledger write is refused, and freeze
and transfer paths. **No production module calls `credit_wallet` or
`debit_wallet`.** The only callers are inside `wallet.py` itself, in
`transfer_between_wallets`. Dynamic access was checked too: no string form of the
name appears anywhere in the tree.

So `wallet_transactions` is permanently empty, and two things downstream depend
on it being written:

* `compliance/aml.py::check_withdrawal`'s **daily withdrawal count** and **daily
  volume** rules read that table. They cannot fire. The single-transaction cap
  and sanctions/PEP screening do fire, via `api/payments.py::_screen_withdrawal_for_aml`.
* `health_check_service.py` aggregates the same table, and aggregates zero.

This could not be closed by engineering alone: nothing recorded whether the fiat
wallet was meant to be the ledger or was superseded. The user-facing surface
reads elsewhere — `/billing/balance` reads the broker account and the
subscription manager, `/billing/transactions` reads Stripe and subscription
events — so "retire it" was a genuine option rather than a straw man.

## Options considered

- **Make the wallet the ledger the money path writes through.** Costs: the
  deposit and withdrawal paths gain a real persistence step, which means an
  idempotency constraint and a migration, and the withdrawal endpoint stops
  being a no-op that always succeeds. A deposit must become attributable to a
  user before any of it can work (see Evidence).
- **Retire it, and repoint AML and the health check at whatever is
  authoritative.** Costs: the platform keeps no first-party money ledger; AML's
  daily rules have to be rewritten against Stripe and broker data that were
  never designed to answer "how much did this user withdraw today"; ~700 lines
  of tested exact-`Decimal` code is deleted and would have to be rebuilt the day
  a ledger is wanted.
- **Delete it silently.** Rejected outright, and named here because it is the
  path of least resistance: the AML rules would then read an empty table with
  nothing left in the tree to explain why they never fire.

## Decision

**The wallet is the ledger.** `POST /payments/deposit` (on confirmation) and
`POST /payments/withdraw` write through `WalletManager`, and
`wallet_transactions` becomes the record AML's daily rules count.

Owner decision, 2026-09-18.

## Consequences

**Easier.** AML's daily count and volume rules become fireable for the first
time — they are correct code that has never had rows to read. The health check
starts aggregating something real. Every money movement gets an exact-`Decimal`
audit row with a reconciliation check that refuses rather than drifts.

**Harder.** Every withdrawal now needs funds in the ledger, so the credit side
must land first — a debit against an empty wallet refuses with "Wallet not
found" or "Insufficient subscription balance". Wiring the withdrawal first, which
is what the finding invites, would make every withdrawal fail, write no row, and
leave the AML rules exactly as unfireable as before.

Stripe webhooks are delivered at least once, so the credit path needs a database
uniqueness constraint rather than a read-then-write check in Python. A replayed
`payment_intent.succeeded` that credits twice creates capital out of nothing.

**Out of scope.** This decides where money is *recorded*, not how it is
*disbursed*. `FIAT_PROVIDER` remains unconfigured and the withdrawal endpoint
still queues nothing.

## Evidence

```bash
# Nothing in production moves this ledger — the only hits are wallet.py itself.
grep -rn "credit_wallet\|debit_wallet" --include="*.py" . | grep -v .venv | grep -v ^./tests/

# What the register measures, and why it read OWNER rather than OPEN.
python scripts/correction_register.py --id WALLET-DEAD
python scripts/correction_register.py --id AML-UNREACHED
```

The prerequisite found while planning this, and fixed first: `POST
/payments/deposit` authenticated the caller and then called
`_fiat_deposit_impl(req)` without the identity, so the Stripe PaymentIntent
carried `metadata={"reference": ...}` and nothing naming the depositor. On
`payment_intent.succeeded` the payload gives the Stripe *customer* id and that
reference, neither of which resolves to a `user_id` here — so a confirmed
deposit could not be credited to any wallet, and there was no way to discover
which one it should have been. The endpoint's own docstring said as much: "The
customer is told where to send money and the system will not recognise it
arriving."

Pinned by `tests/unit/test_a_deposit_is_attributable_to_a_user.py`, four tests,
all four red on the pre-fix tree.

The plan this decision governs is
`docs/audit/plans/2026-09-18-wallet-becomes-the-ledger.md`.
