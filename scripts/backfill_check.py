# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
scripts/backfill_check.py
=========================
READ-ONLY audit: find customers who completed a payment and received nothing.

Why this exists
---------------
Until the activation bridge landed (api/payments.py::_activate_subscription_for_payment),
a completed crypto payment updated the `crypto_payments` row and nothing else — the
customer paid and stayed on the Free tier. Revenue reconciled, so nothing looked wrong.

Run this to enumerate affected accounts. Once activation has been live for a while,
historical victims become indistinguishable from ordinary new activations, so capture
the output and keep it: it is both the list of people to contact and the evidence.

Usage
-----
    python scripts/backfill_check.py            # human-readable table
    python scripts/backfill_check.py --csv      # CSV to stdout, for a spreadsheet

Writes nothing. Safe to hand to whoever runs your hosting.
"""

from __future__ import annotations

import argparse
import csv
import sys

from sqlalchemy import text

# Completed payments whose payer does not hold the tier they paid for.
# Ordered worst-first: users still on `free` paid and got literally nothing.
_QUERY = text(
    """
    SELECT cp.payment_id,
           cp.user_id,
           u.email,
           cp.plan_id      AS paid_for,
           u.plan          AS currently_has,
           cp.amount_usd,
           cp.currency,
           cp.confirmed_at,
           cp.tx_hash
    FROM crypto_payments cp
    JOIN users u ON u.id = cp.user_id
    WHERE cp.status = 'complete'
      AND (u.plan IS NULL OR u.plan = 'free' OR u.plan <> cp.plan_id)
    ORDER BY cp.confirmed_at DESC
    """
)

# Sanity check described in the audit: if _save_payment could not reach the DB it
# logged a warning and continued, so an empty result does not by itself prove that
# no customer was affected.
_TOTAL_PAYMENTS = text("SELECT COUNT(*) FROM crypto_payments")

# Tier ordering, so we can tell "paid to upgrade, never upgraded" apart from
# "has since bought a higher tier" — only the former is a victim.
_RANK = {"free": 0, "starter": 1, "professional": 2, "enterprise": 3, "elite": 4}


def _classify(paid_for: str | None, currently_has: str | None) -> str:
    """Describe the gap between what was paid for and what the account holds."""
    have = (currently_has or "free").lower()
    want = (paid_for or "").lower()
    if have == "free":
        return "PAID, GOT NOTHING"
    if _RANK.get(have, -1) < _RANK.get(want, -1):
        return "UNDER-GRANTED"
    return "ok (has same or higher)"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--csv", action="store_true", help="emit CSV instead of a table")
    args = parser.parse_args()

    try:
        from database.connection import SessionLocal
    except Exception as exc:
        print(f"Cannot import the database layer: {exc}", file=sys.stderr)
        print("Run from the repository root with the app's environment active.", file=sys.stderr)
        return 2

    db = SessionLocal()
    try:
        rows = db.execute(_QUERY).fetchall()
        total_payments = db.execute(_TOTAL_PAYMENTS).scalar() or 0
    except Exception as exc:
        print(f"Query failed: {exc}", file=sys.stderr)
        return 2
    finally:
        db.close()

    if args.csv:
        writer = csv.writer(sys.stdout)
        writer.writerow(
            [
                "payment_id",
                "user_id",
                "email",
                "paid_for",
                "currently_has",
                "classification",
                "amount_usd",
                "currency",
                "confirmed_at",
                "tx_hash",
            ]
        )
        for r in rows:
            writer.writerow(
                [
                    r.payment_id,
                    r.user_id,
                    r.email,
                    r.paid_for,
                    r.currently_has,
                    _classify(r.paid_for, r.currently_has),
                    r.amount_usd,
                    r.currency,
                    r.confirmed_at,
                    r.tx_hash,
                ]
            )
        return 0

    if not rows:
        print("No mismatched payments found.")
        if total_payments == 0:
            print(
                "\nNote: crypto_payments is empty. Either no crypto payment has ever completed,\n"
                "or payments were never persisted. Before concluding nobody was affected, grep\n"
                'your logs for "DB unavailable — payment" — _save_payment warns and continues.'
            )
        return 0

    print(f"{len(rows)} payment(s) where the account does not hold the tier paid for:\n")
    owed = 0.0
    victims = 0
    for r in rows:
        verdict = _classify(r.paid_for, r.currently_has)
        amount = float(r.amount_usd or 0)
        if verdict != "ok (has same or higher)":
            owed += amount
            victims += 1
        print(
            f"  {(r.email or '?'):<34} paid for {(r.paid_for or '?'):<13} "
            f"has {(r.currently_has or 'none'):<13} ${amount:>10,.2f}  "
            f"{r.confirmed_at}  {r.payment_id}  [{verdict}]"
        )

    print(f"\n{victims} account(s) owed an upgrade. Value received without delivery: ${owed:,.2f}")
    if victims:
        print(
            "\nTo remediate, set each account to the tier it paid for — one at a time, checking\n"
            "the row first. `plan` on the users table is the durable record:\n"
            "    UPDATE users SET plan = '<paid_for>' WHERE id = '<user_id>';"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
