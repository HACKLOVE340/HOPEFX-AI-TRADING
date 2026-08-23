---
name: hopefx-money-precision
description: Use when changing code that computes prices, quantities, lot sizes, notional, P&L, balances, equity, fees, or commissions; when a value crosses between Decimal and float at a module boundary; when adding or widening a reconciliation tolerance; or when a monetary assertion in a test compares with `==`.
---

# Money Precision in HOPEFX

## Overview

This codebase is **split**: the billing side is `Decimal`, the trading side is
`float`. Both choices are defensible. The bug class lives at **the boundary
between them**, and in the tolerances that were added to paper over float drift.

**Core principle:** money never silently changes representation. A conversion is
a decision, and it belongs at a named, tested edge — not inline in an f-string.

## The map (verified, not assumed)

| Region | Representation | Files |
|---|---|---|
| Payments / monetization | `Decimal` | all of `payments/`, `monetization/` (24 files) |
| Order state | `Decimal` | `execution/oms.py`, `execution/tca.py` |
| Live position state | **`float`** | `execution/position_tracker.py` (35 importers) |
| ~~`portfolio/pms.py`~~ | `Decimal` but **UNREACHABLE** | no caller anywhere — see below |
| Sizing / routing | `Decimal` | `risk/position_sizing.py`, `brokers/smart_router.py` |
| Risk engine | **`float`** | `risk/manager.py` |
| Invariant predicates | **`float`** | `invariants/constitution.py` |
| FIX order wire | **`float`** | `execution/fix_adapter.py` (`FIXOrder.quantity`, `.price`) |
| Most broker adapters | **`float`** | `brokers/` |

## `portfolio/pms.py` is Decimal and dead — do not rely on it

`portfolio/pms.py` maintains correct `Decimal` discipline on every monetary
field. It also has **no consumers**: nothing imports the `portfolio` package
level, and nothing imports `portfolio.pms` directly. `portfolio/manager.py` is in
the same position — 550 LOC with no reachable caller. A name collision hides it:
both files define a class called `PortfolioManager`, and `__init__.py` imports
one as `PortfolioManager` and the other as `PMS`.

Every live position is carried by `execution/position_tracker.py`, whose
`Position` is `float` on `quantity`, `entry_price`, `current_price`,
`unrealized_pnl`, `realized_pnl`, `commission`, `stop_loss` and `take_profit`.

So when you are reasoning about precision on a position, the file to read is
`position_tracker.py`, not `pms.py`. Verified in the audit as F158.

## The boundary rule

`execution/oms.py` holds `Decimal` internally and drops to `float` on the way
out — lines 254, 258, 411, 412:

```python
# execution/oms.py — the guarantee ends here
"quantity": float(order.quantity),
"price":    float(order.price) if order.price else None,
```

That is correct for JSON serialization. It is **not** correct as an input to
further arithmetic. Before you write `float(some_decimal)`, answer:

1. Is this value leaving the process (JSON, log, metric, wire)? → conversion is fine.
2. Will anything downstream do arithmetic on it? → keep `Decimal`, or you have
   just reintroduced drift after `oms.py` spent effort avoiding it.

Going the other way, **never** `Decimal(some_float)` — it inherits the binary
error verbatim. Use `Decimal(str(x))`, or better, carry the string from source.

## Tolerances are evidence, not a solution

These exist because float drift is real:

| Location | Tolerance | What it forgives |
|---|---|---|
| `invariants/constitution.py:36` | `_EPS = 1e-9` | fill qty / negative balance edges |
| `verify_pnl_reconciliation` | `tol=0.01` | realized+unrealized vs total |
| `verify_capital_conservation` | `tol=0.01` | allocated+available+reserved vs total |
| `verify_ledger_*` | `tol=0.01` | opening+deposits+realized−withdrawals−fees vs closing |
| `risk/manager.py:2020` | `tolerance=0.02` | risk reconciliation |

A `tol=0.01` on capital conservation means **up to one cent per check can vanish
without tripping the invariant**. That is a deliberate trade, and it is fine — as
long as nobody widens it to silence a failure.

**Never widen a tolerance to make a check pass.** A reconciliation that needs a
bigger epsilon is reporting a real defect: an ordering change, a double-count, or
a float path that should have been `Decimal`. Fix the arithmetic. Widening a
constitutional tolerance is weakening a risk gate — see `CLAUDE.md`.

## Tests

841 assertions in `tests/` compare a monetary quantity with `==`. Do not add the
842nd:

```python
# ❌ passes today, fails when an unrelated summation reorders
assert account.equity == 10_432.17

# ✅ states the precision you actually require
assert account.equity == pytest.approx(10_432.17, abs=0.01)

# ✅ better, when the value is Decimal — exactness is the point
assert order.quantity == Decimal("1.25")
```

If the value is `Decimal`, assert exact equality against a `Decimal("...")`
literal. Reaching for `approx` on a `Decimal` means the representation is not
buying you anything and something upstream already went through `float`.

## Common mistakes

| Mistake | Why it bites |
|---|---|
| `Decimal(1.1)` | Stores `1.100000000000000088817841970012523233890533447265625` |
| `float(qty) * float(price)` after OMS | Throws away the precision OMS maintained |
| Widening `tol` to fix a red test | Silences a real reconciliation defect |
| `round(x, 2)` for money | Banker's rounding; use `Decimal.quantize` with an explicit `ROUND_HALF_UP` |
| Comparing accumulated P&L with `==` | Summation order changes the last bits |
| `Decimal` in a hot tick loop | ~100x slower than float; keep `float` in `data_layer/` ingest, convert at the order edge |

## Where the line should sit

Tick ingest and indicator maths stay `float` — they are statistical, high-volume,
and precision-tolerant. Anything that becomes **an order, a fill, a balance, or
an invoice** should be `Decimal` by the time it is authoritative. Today
`risk/manager.py` sits on the float side of that line while `risk/position_sizing.py`
sits on the Decimal side; when you touch either, move toward `Decimal`, never away.
