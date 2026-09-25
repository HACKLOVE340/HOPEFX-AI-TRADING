#!/usr/bin/env python
# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""Read-only crypto deposit-address collision report.

MASTER_OUTSTANDING §A11's "found on the way" defect: until 2026-09-25 every BTC
deposit address request returned the same address (HD index 0, for every
user), and ETH / USDT_ERC20 could reuse indices across workers and collide
with each other (they derive from the same path on one mnemonic, so ETH index
*n* and USDT_ERC20 index *n* were the same address). The fix
(``payments/crypto/address_generator.py``) stops new collisions; it does not
undo the ones already issued. The owner action recorded in §A11 is:

    Every BTC payment already issued shares one address, and early ETH/USDT
    payments may share addresses. Reconcile deposits to those addresses by
    amount and time.

This script is that reconciliation report. It is READ-ONLY: it opens the
database in a read-only mode (SQLite ``mode=ro`` URI; PostgreSQL a read-only
transaction via ``SET TRANSACTION READ ONLY``, rolled back rather than
committed) and never writes to any database or file other than the optional
``--output`` path it is given. It does not touch a blockchain, an exchange, or
any network service of any kind — it only reads what this platform already
recorded about its own payments and orders.

A stored crypto payment or order can live in either of two places, and this
script reads both:

* ``crypto_payments`` — a real table (``database/models.py::CryptoPayment``),
  written by ``api/payments.py::generate_deposit_address``.
* the billing order store — before 2026-09-24,
  ``api/billing.py::create_crypto_order`` wrote its orders through
  ``api.db_store.db_set``, a JSON blob keyed ``crypto_order:{order_id}`` in the
  ``configurations`` table (a key-value store), not a dedicated table.

IMPORTANT — this script does not, and must not, decide who owns a deposit sent
to a shared address, and it credits nothing. Matching an on-chain deposit to
one of the payments listed against a colliding address is a MANUAL step for
the account owner: compare the deposit's amount and timestamp against the
`expected amount` / `created` columns this report prints for every payment on
that address. No payment on a colliding address should be auto-credited from
this report or from any automation build on top of it.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import sqlalchemy as sa
from sqlalchemy.engine import Engine
from sqlalchemy.engine.url import make_url

REPO_ROOT = Path(__file__).resolve().parent.parent

EXIT_NO_COLLISIONS = 0
EXIT_COLLISIONS_FOUND = 1
EXIT_ERROR = 2

# Prefix for the per-order key `api/billing.py::create_crypto_order` writes
# (``crypto_order:{order_id}``). Deliberately does NOT match
# ``crypto_orders:{user_id}`` (plural, the per-user index list of the same
# orders) — that key holds duplicates of records already read from the
# singular keys, and counting it too would double-count every billing order.
_BILLING_ORDER_KEY_PREFIX = "crypto_order:"


# ─────────────────────────────────────────────────────────────────────────────
# Data model
# ─────────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class PaymentRecord:
    """One stored crypto payment or order, from either storage location."""

    source: str  # "crypto_payments" | "billing_order"
    id: str  # payment_id or order_id
    user_id: str | None
    currency: str | None
    network: str | None
    address: str
    amount_usd: Decimal | None
    amount_crypto: Decimal | None
    status: str | None
    created_at: str | None

    @property
    def chain(self) -> str:
        return chain_for(self.currency, self.network)


@dataclass
class CollisionGroup:
    chain: str
    address: str
    payments: list[PaymentRecord] = field(default_factory=list)

    @property
    def count(self) -> int:
        return len(self.payments)

    @property
    def mixed_currency_eth_usdt_erc20(self) -> bool:
        """True when this address is shared by an ETH payment and a
        USDT-on-ERC20 payment — the specific collision named in §A11: both
        derive from the same BIP44 path on one mnemonic, so ETH index *n* and
        USDT_ERC20 index *n* are the same address."""
        currencies = {(p.currency or "").upper() for p in self.payments}
        has_eth = "ETH" in currencies
        has_usdt_erc20 = any(
            (p.currency or "").upper() == "USDT" and (p.network or "").upper() == "ERC20" for p in self.payments
        )
        return has_eth and has_usdt_erc20


def chain_for(currency: str | None, network: str | None) -> str:
    """Best-effort chain label for grouping, from the stored currency/network.

    Not authoritative on-chain identity — it is a display/grouping label
    derived from what this platform recorded about the payment, matching
    ``payments/crypto/address_generator.py``'s derivation rules:

    * BTC is always its own chain.
    * ETH is the Ethereum chain.
    * USDT on network "ERC20" shares the Ethereum chain (same BIP44 path as
      ETH — the exact collision this report exists to find).
    * USDT on any other/absent network defaults to TRC20
      (``payments/crypto/usdt.py::USDTClient.generate_deposit_address``'s
      default), which is a distinct address format from ETH/BTC and cannot
      collide with them by address string alone.

    A billing order (the ``configurations`` key-value store) never recorded a
    network at all, so a USDT order there is grouped under its historical
    default (TRC20) unless the caller supplied one.
    """
    currency_u = (currency or "").strip().upper()
    network_u = (network or "").strip().upper()
    if currency_u == "BTC":
        return "BTC"
    if currency_u == "ETH":
        return "ETH"
    if currency_u == "USDT":
        if network_u == "ERC20":
            return "ETH"
        if network_u == "BEP20":
            return "BEP20"
        return "TRC20"
    return currency_u or "UNKNOWN"


# ─────────────────────────────────────────────────────────────────────────────
# Database access — read-only
# ─────────────────────────────────────────────────────────────────────────────


def resolve_database_url(cli_value: str | None) -> str:
    """The DB URL to read: ``--database-url`` if given, else the same config
    the app itself uses (``DATABASE_URL``, falling back to the app's default
    dev SQLite path)."""
    if cli_value:
        return cli_value
    try:
        # Reuses the app's own resolution (env var, else the same dev SQLite
        # fallback path `database/connection.py` uses) rather than
        # re-implementing it here and risking the two drifting apart.
        from database.connection import _default_db_url

        return _default_db_url()
    except Exception:
        import os

        return os.getenv("DATABASE_URL", "")


def open_read_only_engine(database_url: str) -> Engine:
    """Open ``database_url`` such that a write through the returned engine
    fails, rather than merely being a convention this script chooses not to
    break.

    SQLite: reopened as a ``file:...?mode=ro`` URI — SQLite itself refuses any
    write on such a connection (``OperationalError: attempt to write a
    readonly database``).

    PostgreSQL (and other server engines): a normal connection, but every
    transaction this script opens on it issues ``SET TRANSACTION READ ONLY``
    as its first statement (see :func:`read_only_connection`) and is always
    rolled back, never committed.
    """
    url = make_url(database_url)
    if url.get_backend_name() == "sqlite":
        database = url.database
        if not database or database == ":memory:":
            raise ValueError(
                "A SQLite in-memory database has nothing durable to read read-only; pass a file-backed --database-url."
            )
        abs_path = Path(database).resolve()
        if not abs_path.exists():
            raise FileNotFoundError(f"SQLite database not found: {abs_path}")
        ro_url = f"sqlite:///file:{abs_path}?mode=ro&uri=true"
        return sa.create_engine(ro_url)
    # Non-SQLite (PostgreSQL etc.): rely on read_only_connection() to enforce
    # READ ONLY per-transaction; the engine itself is a normal one.
    return sa.create_engine(database_url)


def _read_only_transaction(engine: Engine):
    """A connection whose current transaction is READ ONLY and will be rolled
    back, never committed. For SQLite the file-level ``mode=ro`` already makes
    any write impossible, so this is a plain connection; for PostgreSQL it
    issues ``SET TRANSACTION READ ONLY`` as the transaction's first statement,
    per the requirement that a server-side engine enforce read-only at the
    transaction level, not only by caller discipline.
    """
    conn = engine.connect()
    if engine.dialect.name != "sqlite":
        trans = conn.begin()
        conn.execute(sa.text("SET TRANSACTION READ ONLY"))
        return conn, trans
    return conn, None


def _close_read_only_transaction(conn, trans) -> None:
    try:
        if trans is not None:
            trans.rollback()  # never commit — this connection never writes
    finally:
        conn.close()


def load_crypto_payments(engine: Engine) -> list[PaymentRecord]:
    """Every row of the ``crypto_payments`` table.

    Queried through the ORM's mapped ``Table`` (typed columns), not a raw
    ``SELECT ... `` string: SQLite stores a ``Numeric`` column as a native
    REAL (float), and only the column's own type (``asdecimal=True`` on
    ``Numeric``) applies the result processor that reconstructs the exact
    ``Decimal`` at the column's declared scale. A raw-text query would read
    back a float and reintroduce the drift the column exists to avoid
    (hopefx-money-precision).
    """
    from database.models import CryptoPayment

    table = CryptoPayment.__table__
    conn, trans = _read_only_transaction(engine)
    try:
        inspector = sa.inspect(engine)
        if table.name not in inspector.get_table_names():
            return []
        stmt = sa.select(
            table.c.payment_id,
            table.c.user_id,
            table.c.currency,
            table.c.network,
            table.c.address,
            table.c.amount_usd,
            table.c.amount_crypto,
            table.c.status,
            table.c.created_at,
        )
        rows = conn.execute(stmt).mappings()
        records = []
        for row in rows:
            records.append(
                PaymentRecord(
                    source="crypto_payments",
                    id=row["payment_id"],
                    user_id=row["user_id"],
                    currency=row["currency"],
                    network=row["network"],
                    address=row["address"],
                    amount_usd=_as_decimal(row["amount_usd"]),
                    amount_crypto=_as_decimal(row["amount_crypto"]),
                    status=row["status"],
                    created_at=_as_iso(row["created_at"]),
                )
            )
        return records
    finally:
        _close_read_only_transaction(conn, trans)


def load_billing_orders(engine: Engine) -> list[PaymentRecord]:
    """Every billing-order JSON blob stored under ``crypto_order:{id}`` in the
    ``configurations`` key-value table (pre-2026-09-24 storage path;
    ``create_crypto_order`` still writes here — it has not been migrated to a
    dedicated table)."""
    from database.models import Configuration

    table = Configuration.__table__
    conn, trans = _read_only_transaction(engine)
    try:
        inspector = sa.inspect(engine)
        if table.name not in inspector.get_table_names():
            return []
        stmt = sa.select(table.c.config_key, table.c.config_value).where(
            table.c.config_key.like(f"{_BILLING_ORDER_KEY_PREFIX}%")
        )
        rows = conn.execute(stmt).mappings()
        records = []
        for row in rows:
            if not row["config_value"]:
                continue
            try:
                order = json.loads(row["config_value"])
            except (TypeError, ValueError):
                continue
            if not isinstance(order, dict):
                continue
            address = order.get("address")
            if not address:
                continue
            records.append(
                PaymentRecord(
                    source="billing_order",
                    id=order.get("order_id", row["config_key"]),
                    user_id=order.get("user_id"),
                    currency=order.get("currency"),
                    network=order.get("network"),  # not recorded by create_crypto_order; usually None
                    address=address,
                    amount_usd=_as_decimal(order.get("amount_usd")),
                    amount_crypto=_as_decimal(order.get("amount_crypto")),
                    status=order.get("status"),
                    created_at=order.get("created_at"),
                )
            )
        return records
    finally:
        _close_read_only_transaction(conn, trans)


def _as_decimal(value: Any) -> Decimal | None:
    if value is None:
        return None
    if isinstance(value, Decimal):
        return value
    # Never `Decimal(float)` — it inherits the float's binary error verbatim.
    # Route every non-Decimal value through its string form (hopefx-money-precision).
    return Decimal(str(value))


def _as_iso(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


# ─────────────────────────────────────────────────────────────────────────────
# Grouping and reporting
# ─────────────────────────────────────────────────────────────────────────────


def group_by_chain_and_address(records: list[PaymentRecord]) -> dict[tuple[str, str], list[PaymentRecord]]:
    groups: dict[tuple[str, str], list[PaymentRecord]] = {}
    for record in records:
        key = (record.chain, record.address)
        groups.setdefault(key, []).append(record)
    return groups


def find_collisions(groups: dict[tuple[str, str], list[PaymentRecord]]) -> list[CollisionGroup]:
    collisions = []
    for (chain, address), payments in groups.items():
        if len(payments) > 1:
            collisions.append(CollisionGroup(chain=chain, address=address, payments=list(payments)))
    # Deterministic order for stable output/diffing.
    collisions.sort(key=lambda g: (g.chain, g.address))
    return collisions


@dataclass
class Report:
    collisions: list[CollisionGroup]
    total_payments: int
    distinct_addresses: int
    total_amount_usd: Decimal


def build_report(records: list[PaymentRecord]) -> Report:
    groups = group_by_chain_and_address(records)
    collisions = find_collisions(groups)
    total_amount_usd = sum((r.amount_usd for r in records if r.amount_usd is not None), Decimal("0"))
    return Report(
        collisions=collisions,
        total_payments=len(records),
        distinct_addresses=len(groups),
        total_amount_usd=total_amount_usd,
    )


def _payments_affected(report: Report) -> int:
    return sum(g.count for g in report.collisions)


# ─────────────────────────────────────────────────────────────────────────────
# Output formatting
# ─────────────────────────────────────────────────────────────────────────────


def _payment_to_dict(p: PaymentRecord) -> dict:
    return {
        "source": p.source,
        "id": p.id,
        "user_id": p.user_id,
        "currency": p.currency,
        "network": p.network,
        "expected_amount_usd": str(p.amount_usd) if p.amount_usd is not None else None,
        "expected_amount_crypto": str(p.amount_crypto) if p.amount_crypto is not None else None,
        "status": p.status,
        "created_at": p.created_at,
    }


def format_json(report: Report) -> str:
    payload = {
        "collisions": [
            {
                "chain": g.chain,
                "address": g.address,
                "count": g.count,
                "mixed_currency_eth_usdt_erc20": g.mixed_currency_eth_usdt_erc20,
                "payments": [_payment_to_dict(p) for p in g.payments],
            }
            for g in report.collisions
        ],
        "summary": {
            "total_payments": report.total_payments,
            "distinct_addresses": report.distinct_addresses,
            "colliding_addresses": len(report.collisions),
            "payments_affected": _payments_affected(report),
            "total_amount_usd": str(report.total_amount_usd),
        },
    }
    return json.dumps(payload, indent=2)


def format_text(report: Report) -> str:
    lines = ["Crypto deposit-address collision report", "=" * 40, ""]
    if not report.collisions:
        lines.append("No colliding addresses found.")
    for g in report.collisions:
        lines.append(f"Chain: {g.chain}  Address: {g.address}  ({g.count} payments/orders)")
        if g.mixed_currency_eth_usdt_erc20:
            lines.append(
                "  ** MIXED CURRENCY: ETH and USDT (ERC20) share this address — same BIP44 path, same mnemonic **"
            )
        for p in g.payments:
            lines.append(
                f"    - [{p.source}] id={p.id} user={p.user_id} "
                f"currency={p.currency} amount_usd={p.amount_usd} "
                f"created_at={p.created_at} status={p.status}"
            )
        lines.append("")
    lines.append("Summary")
    lines.append("-------")
    lines.append(f"Total payments/orders read : {report.total_payments}")
    lines.append(f"Distinct (chain, address)  : {report.distinct_addresses}")
    lines.append(f"Colliding addresses        : {len(report.collisions)}")
    lines.append(f"Payments/orders affected   : {_payments_affected(report)}")
    lines.append(f"Total expected amount (USD): {report.total_amount_usd}")
    lines.append("")
    lines.append(
        "Matching an on-chain deposit to one of the payments above by amount and "
        "time is a MANUAL owner step. Do not auto-credit any payment on a "
        "colliding address from this report."
    )
    return "\n".join(lines)


# ─────────────────────────────────────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────────────────────────────────────


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="crypto_address_collision_report.py",
        description=(
            "Read-only reconciliation report for MASTER_OUTSTANDING §A11 owner action (a): "
            "which stored crypto deposit addresses were issued to more than one payment or "
            "order (the BTC-index-0 and ETH/USDT_ERC20 derivation collisions fixed 2026-09-25). "
            "Reads the crypto_payments table and the billing order store (configurations "
            "table) and groups every stored payment/order by (chain, address). "
            "\n\n"
            "This script never performs an on-chain lookup or any other network call, and it "
            "opens the database read-only. Matching an actual on-chain deposit to one of the "
            "payments listed against a colliding address, by its amount and time, is a MANUAL "
            "step for the account owner — this report does not do it and produces no automatic "
            "crediting. No payment on a colliding address should be credited automatically "
            "from this report."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--database-url",
        default=None,
        help="Database URL to read. Defaults to the app's own DATABASE_URL (or its dev SQLite fallback).",
    )
    parser.add_argument(
        "--format",
        choices=("text", "json"),
        default="text",
        help="Output format (default: text).",
    )
    parser.add_argument(
        "--output",
        default=None,
        help="Optional file path to write the report to, instead of stdout. The only file this script ever writes.",
    )
    return parser


def run(argv: list[str] | None = None) -> int:
    parser = _build_arg_parser()
    args = parser.parse_args(argv)

    try:
        database_url = resolve_database_url(args.database_url)
        if not database_url:
            print("error: no database URL resolved (set DATABASE_URL or pass --database-url)", file=sys.stderr)
            return EXIT_ERROR
        engine = open_read_only_engine(database_url)
        try:
            records = load_crypto_payments(engine) + load_billing_orders(engine)
        finally:
            engine.dispose()

        report = build_report(records)
        text = format_json(report) if args.format == "json" else format_text(report)

        if args.output:
            Path(args.output).write_text(text + "\n", encoding="utf-8")
        else:
            print(text)

        return EXIT_COLLISIONS_FOUND if report.collisions else EXIT_NO_COLLISIONS
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_ERROR


def main() -> None:
    sys.exit(run())


if __name__ == "__main__":
    main()
