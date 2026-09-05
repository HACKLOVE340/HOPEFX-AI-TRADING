#!/usr/bin/env python3
# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
scripts/adopt_legacy_positions.py — move the shared paper book to real accounts.

Why this exists
---------------
Until ``core/account_registry.py``, every logged-in user traded against one
process-wide ``PaperTradingBroker`` whose Redis namespace was ``paper``. Its
state lives under::

    hopefx:paper:positions:<symbol>     hopefx:paper:positions:index
    hopefx:paper:orders:<id>            hopefx:paper:orders:index
    hopefx:paper:balance

Each user now gets their own broker, namespaced ``user:<user_id>``. Nothing
reads the old namespace any more, so on the first restart after the upgrade
every open position stops appearing anywhere and each user's account starts at
its initial balance. The positions are not deleted — they sit in Redis under a
key nobody opens — but from the UI they have vanished.

This tool moves them across. Run it with the app stopped.

What it will not do
-------------------
``PaperTradingBroker.positions`` is keyed by *symbol*, and ``_update_position``
merged same-side fills into the existing entry. Two users who both bought
XAUUSD did not end up with two positions; they ended up with one, quantity
summed and entry price averaged. **The information needed to split that back
apart no longer exists**, so this script will not guess. It reports what is
there and moves only what you name.

``--assign SYMBOL=USER_ID`` moves the whole position. That is exactly right
when one user traded the symbol, which is the usual case for a single-operator
deployment, and simply wrong otherwise.

``--assign SYMBOL=USER_ID:QTY`` splits by quantity when you know the split.
Be aware that ``entry_price`` is the blended average of the merged fills, so
each side of a split inherits an entry price neither user actually got, and
their P&L will be off by the difference. The tool prints this warning whenever
a split is requested. It is an approximation offered because it beats
attributing one user's money to another — not because it is accurate.

Usage
-----
    # 1. Look before touching anything. This is the default.
    python scripts/adopt_legacy_positions.py

    # 2. Dry run of a specific plan — shows every write, performs none.
    python scripts/adopt_legacy_positions.py --assign XAUUSD=3f2a...  \\
                                             --assign EURUSD=91bc...

    # 3. Do it. Writes a JSON backup of the legacy namespace first.
    python scripts/adopt_legacy_positions.py --assign XAUUSD=3f2a... --apply

Safety
------
* Read-only unless ``--apply`` is passed.
* ``--apply`` writes a full JSON backup of the legacy namespace first and
  aborts if it cannot.
* Refuses to write into a symbol the target user already holds, rather than
  merging — merging is the defect this whole change set exists to remove.
* Idempotent: an assignment that has already been applied finds nothing left
  in the legacy namespace and reports that.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from execution.redis_state import RedisStateStore, _balance_key

UTC = timezone.utc

LEGACY_NAMESPACE_DEFAULT = "paper"


# ---------------------------------------------------------------------------
# Redis
# ---------------------------------------------------------------------------


def connect_redis(url: str | None = None):
    """Connect the same way PaperTradingBroker does, so this tool and the app
    always agree about which Redis holds the book."""
    import redis as redis_lib

    redis_url = (url or os.getenv("REDIS_URL", "")).strip() or "redis://localhost:6379/0"
    password = os.getenv("REDIS_PASSWORD", "").strip()
    # Shared helper: the inline version raised ValueError on an empty or
    # schemeless REDIS_URL instead of degrading.
    from cache.redis_client import inject_redis_password

    redis_url = inject_redis_password(redis_url, password)
    client = redis_lib.from_url(redis_url, decode_responses=True, socket_connect_timeout=5)
    client.ping()
    return client


def discover_user_namespaces(client) -> list[str]:
    """Namespaces that already look like per-user accounts."""
    found: set[str] = set()
    for key in client.scan_iter("hopefx:user:*:positions:index", count=100):
        parts = key.split(":")
        if len(parts) >= 4:
            found.add(f"{parts[1]}:{parts[2]}")
    for key in client.scan_iter("hopefx:user:*:balance", count=100):
        parts = key.split(":")
        if len(parts) >= 4:
            found.add(f"{parts[1]}:{parts[2]}")
    return sorted(found)


# ---------------------------------------------------------------------------
# Assignments
# ---------------------------------------------------------------------------


class Assignment:
    """One ``SYMBOL=USER_ID`` or ``SYMBOL=USER_ID:QTY`` instruction."""

    __slots__ = ("quantity", "symbol", "user_id")

    def __init__(self, symbol: str, user_id: str, quantity: float | None) -> None:
        self.symbol = symbol
        self.user_id = user_id
        self.quantity = quantity

    def __repr__(self) -> str:  # pragma: no cover - diagnostics only
        qty = "all" if self.quantity is None else f"{self.quantity:g}"
        return f"<Assignment {self.symbol} → {self.user_id} qty={qty}>"


def parse_assignment(spec: str) -> Assignment:
    if "=" not in spec:
        raise ValueError(f"expected SYMBOL=USER_ID[:QTY], got {spec!r}")
    symbol, _, target = spec.partition("=")
    symbol = symbol.strip()
    target = target.strip()
    if not symbol or not target:
        raise ValueError(f"expected SYMBOL=USER_ID[:QTY], got {spec!r}")
    quantity: float | None = None
    if ":" in target:
        target, _, qty_raw = target.partition(":")
        target = target.strip()
        try:
            quantity = float(qty_raw)
        except ValueError as exc:
            raise ValueError(f"quantity in {spec!r} is not a number") from exc
        if quantity <= 0:
            raise ValueError(f"quantity in {spec!r} must be positive")
    if not target:
        raise ValueError(f"expected SYMBOL=USER_ID[:QTY], got {spec!r}")
    return Assignment(symbol, target, quantity)


def load_mapping_file(path: Path) -> list[Assignment]:
    """A JSON object of ``{"XAUUSD": "user-id"}`` or ``{"XAUUSD": [{"user_id":
    "...", "quantity": 1.5}, ...]}``."""
    raw = json.loads(path.read_text())
    out: list[Assignment] = []
    for symbol, target in raw.items():
        if isinstance(target, str):
            out.append(Assignment(symbol, target, None))
            continue
        for entry in target:
            out.append(Assignment(symbol, entry["user_id"], float(entry["quantity"])))
    return out


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------


def describe_legacy_book(client, namespace: str) -> dict[str, Any]:
    store = RedisStateStore(client, namespace=namespace)
    positions = store.load_positions()
    orders = store.load_orders()
    raw_balance = client.get(_balance_key(namespace))
    balance = None
    if raw_balance:
        try:
            balance = float(json.loads(raw_balance)["balance"])
        except (ValueError, KeyError, TypeError):
            balance = None
    return {"positions": positions, "orders": orders, "balance": balance}


def print_report(book: dict[str, Any], namespace: str, user_namespaces: list[str]) -> None:
    positions = book["positions"]
    balance = book["balance"]
    balance_text = "(never persisted)" if balance is None else f"${balance:,.2f}"
    print(f"\nLegacy namespace: hopefx:{namespace}:*")
    print(f"  balance:   {balance_text}")
    print(f"  positions: {len(positions)}")
    print(f"  orders:    {len(book['orders'])}")

    if positions:
        print("\n  symbol      side   quantity      entry     current   unrealised")
        print("  " + "-" * 64)
        for p in sorted(positions, key=lambda x: str(x.get("symbol", ""))):
            print(
                f"  {p.get('symbol', '?')!s:<11} {p.get('side', '?')!s:<6} "
                f"{float(p.get('quantity', 0)):>9,.4f} "
                f"{float(p.get('entry_price', 0)):>10,.2f} "
                f"{float(p.get('current_price', 0)):>11,.2f} "
                f"{float(p.get('unrealized_pnl', 0)):>12,.2f}"
            )

    print(f"\nExisting per-user accounts in Redis: {len(user_namespaces)}")
    for ns in user_namespaces:
        print(f"  {ns}")

    if positions:
        print(
            "\nNothing has been moved. Every position above is invisible to the "
            "application\nuntil it is assigned to a user. Name each one:\n"
        )
        for p in sorted(positions, key=lambda x: str(x.get("symbol", ""))):
            print(f"  --assign {p.get('symbol', '?')}=<user_id>")
        print("\nThen re-run with --apply.")


# ---------------------------------------------------------------------------
# Migration
# ---------------------------------------------------------------------------


def plan_moves(book: dict[str, Any], assignments: list[Assignment]) -> tuple[list[dict], list[str]]:
    """Turn assignments into concrete writes. Returns (moves, problems)."""
    by_symbol = {str(p.get("symbol", "")): p for p in book["positions"]}
    moves: list[dict] = []
    problems: list[str] = []

    grouped: dict[str, list[Assignment]] = {}
    for a in assignments:
        grouped.setdefault(a.symbol, []).append(a)

    for symbol, group in grouped.items():
        position = by_symbol.get(symbol)
        if position is None:
            problems.append(f"{symbol}: not in the legacy namespace — already moved, or never there")
            continue
        total = float(position.get("quantity", 0))
        whole = [a for a in group if a.quantity is None]
        if whole and len(group) > 1:
            problems.append(f"{symbol}: mixes a whole-position assignment with a split; pick one")
            continue
        if whole:
            moves.append({"symbol": symbol, "user_id": whole[0].user_id, "quantity": total, "position": position})
            continue

        requested = sum(a.quantity or 0.0 for a in group)
        if requested > total + 1e-9:
            problems.append(f"{symbol}: split totals {requested:g} but only {total:g} is held")
            continue
        for a in group:
            moves.append({"symbol": symbol, "user_id": a.user_id, "quantity": a.quantity, "position": position})
        if requested < total - 1e-9:
            problems.append(
                f"{symbol}: NOTE {total - requested:g} of {total:g} stays in the legacy namespace and remains invisible"
            )
    return moves, problems


def apply_moves(client, legacy_namespace: str, moves: list[dict], *, dry_run: bool) -> list[str]:
    legacy = RedisStateStore(client, namespace=legacy_namespace)
    log: list[str] = []
    remaining: dict[str, float] = {}

    for move in moves:
        symbol = move["symbol"]
        user_ns = f"user:{move['user_id']}"
        target = RedisStateStore(client, namespace=user_ns)

        existing = {str(p.get("symbol", "")) for p in target.load_positions()}
        if symbol in existing:
            log.append(
                f"REFUSED {symbol} → {user_ns}: that account already holds {symbol}. "
                f"Merging is the defect this migration removes; close one side first."
            )
            continue

        new_position = dict(move["position"])
        new_position["quantity"] = float(move["quantity"])
        new_position["_adopted_from"] = f"hopefx:{legacy_namespace}"
        new_position["_adopted_at"] = datetime.now(UTC).isoformat()

        if dry_run:
            log.append(f"WOULD WRITE {symbol} qty={move['quantity']:g} → hopefx:{user_ns}:positions:{symbol}")
        else:
            target.save_position(new_position)
            log.append(f"wrote {symbol} qty={move['quantity']:g} → hopefx:{user_ns}:positions:{symbol}")

        held = remaining.get(symbol, float(move["position"].get("quantity", 0)))
        remaining[symbol] = held - float(move["quantity"])

    for symbol, left in remaining.items():
        if left > 1e-9:
            log.append(f"kept {symbol} qty={left:g} in hopefx:{legacy_namespace} (unassigned)")
            continue
        if dry_run:
            log.append(f"WOULD REMOVE {symbol} from hopefx:{legacy_namespace}")
        else:
            legacy.remove_position(symbol)
            log.append(f"removed {symbol} from hopefx:{legacy_namespace}")
    return log


def write_backup(book: dict[str, Any], path: Path, namespace: str) -> None:
    path.write_text(
        json.dumps(
            {
                "namespace": namespace,
                "captured_at": datetime.now(UTC).isoformat(),
                "balance": book["balance"],
                "positions": book["positions"],
                "orders": book["orders"],
            },
            indent=2,
        )
    )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Move the shared paper-trading book into per-user accounts.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--redis-url", default=None, help="defaults to $REDIS_URL")
    parser.add_argument(
        "--legacy-namespace",
        default=LEGACY_NAMESPACE_DEFAULT,
        help=f"namespace the shared broker used (default: {LEGACY_NAMESPACE_DEFAULT})",
    )
    parser.add_argument(
        "--assign",
        action="append",
        default=[],
        metavar="SYMBOL=USER_ID[:QTY]",
        help="assign a legacy position to a user; repeatable",
    )
    parser.add_argument("--mapping", type=Path, default=None, help="JSON file of assignments")
    parser.add_argument(
        "--apply",
        action="store_true",
        help="actually write. Without it nothing is modified.",
    )
    parser.add_argument("--backup", type=Path, default=None, help="where to write the pre-change JSON backup")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    try:
        client = connect_redis(args.redis_url)
    except Exception as exc:
        print(f"cannot reach Redis: {exc}", file=sys.stderr)
        return 2

    book = describe_legacy_book(client, args.legacy_namespace)

    assignments: list[Assignment] = []
    try:
        for spec in args.assign:
            assignments.append(parse_assignment(spec))
        if args.mapping:
            assignments.extend(load_mapping_file(args.mapping))
    except (ValueError, KeyError, json.JSONDecodeError) as exc:
        print(f"bad assignment: {exc}", file=sys.stderr)
        return 2

    if not assignments:
        print_report(book, args.legacy_namespace, discover_user_namespaces(client))
        return 0

    if any(a.quantity is not None for a in assignments):
        print(
            "\nWARNING: a quantity split was requested.\n"
            "  The legacy book merged same-side fills, so entry_price is a blended\n"
            "  average of trades that happened at different prices. Each side of the\n"
            "  split inherits an entry price neither user actually got, and their P&L\n"
            "  will be wrong by that difference. The original per-fill prices are gone.\n"
        )

    moves, problems = plan_moves(book, assignments)
    for problem in problems:
        print(f"  ! {problem}")
    if not moves:
        print("\nnothing to move.")
        return 1 if problems else 0

    if args.apply:
        backup = args.backup or Path(f"hopefx-legacy-book-{datetime.now(UTC):%Y%m%dT%H%M%SZ}.json")
        try:
            write_backup(book, backup, args.legacy_namespace)
        except OSError as exc:
            print(f"refusing to write: backup to {backup} failed: {exc}", file=sys.stderr)
            return 2
        print(f"\nbackup written to {backup}")

    print()
    for line in apply_moves(client, args.legacy_namespace, moves, dry_run=not args.apply):
        print(f"  {line}")

    if not args.apply:
        print("\nDry run — nothing was modified. Re-run with --apply.")
    else:
        print(
            "\nDone. Start the app and confirm each user sees their positions before "
            "trading.\nThe legacy balance was NOT moved: per-user accounts start at "
            "INITIAL_BALANCE and\ncash cannot be attributed from a commingled book."
        )
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
