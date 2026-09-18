#!/usr/bin/env python3
# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""Every ORM table must be created by a migration, not only by `create_all()`.

## Why this exists

`Base.metadata.create_all()` creates what is missing and **never ALTERs**. A
fresh install gets today's schema; a database upgraded from an older release
keeps whatever it had. The two drift apart silently, and nothing notices until a
query fails on one of them (F218).

## Why it is a script and not a regex

F218 was recorded as *"36 of 44 tables have no migration"*. It was **4**, and
then 0 — the number came from a probe searching the migration text for

    create_table(  "table_name"

and this repository does not write that. Three ways it misses:

* **The idempotency wrapper.** Nearly every migration defines a local
  ``_tbl(name, *args, **kwargs)`` that calls ``op.create_table`` only when the
  table is absent, so re-running an upgrade is safe. 35 of 43 tables are created
  through it, and the literal never sits next to ``create_table``.
* **Module-level name constants.** ``ai_department_memory``, ``sessions``,
  ``support_tickets`` and ``support_messages`` are created as
  ``op.create_table(_TABLE, ...)`` with ``_TABLE = "..."`` at module scope.
* **A second models module.** ``database/user_models.py`` declares three more
  tables and was not looked at.

So it reported 32 tables as missing that were not, while a real gap would have
been invisible in the noise. This resolves names instead of matching text: the
file is parsed, module-level string constants are resolved, and any call whose
target ends in ``create_table`` — or is a known wrapper — is followed.

## Usage

    python scripts/schema_migration_check.py            # report
    python scripts/schema_migration_check.py --check    # the gate
"""

from __future__ import annotations

import argparse
import ast
import sys
from pathlib import Path

#: Resolved at call time, not from ``__file__``. Rooting a gate at its own
#: location makes it impossible to exercise against a throwaway repository, and
#: a gate that cannot be tested in isolation cannot be shown to fail — the same
#: defect scripts/model_artifact_manifest_gate.py had to be fixed for.
REPO = Path(__file__).resolve().parents[1]

#: Where ORM tables are declared. `user_models.py` was the module the original
#: probe did not know about.
MODEL_FILES = ("database/models.py", "database/user_models.py")

MIGRATIONS = "alembic/versions"

#: Local helpers that forward to `op.create_table`. Each is a closure defined
#: inside `upgrade()` that skips the call when the table already exists, so the
#: table name is its first argument just as it is for `create_table` itself.
_WRAPPERS = frozenset({"_tbl", "_create_table_if_missing"})


def _module_constants(tree: ast.Module) -> dict[str, str]:
    """Module-level ``NAME = "literal"`` bindings, for resolving `_TABLE`."""
    found: dict[str, str] = {}
    for node in tree.body:
        if not isinstance(node, ast.Assign) or not isinstance(node.value, ast.Constant):
            continue
        if not isinstance(node.value.value, str):
            continue
        for target in node.targets:
            if isinstance(target, ast.Name):
                found[target.id] = node.value.value
    return found


def _call_name(func: ast.expr) -> str:
    if isinstance(func, ast.Attribute):
        return func.attr
    if isinstance(func, ast.Name):
        return func.id
    return ""


def declared_tables(repo: Path | None = None) -> dict[str, str]:
    """Every ``__tablename__`` in the ORM, mapped to the file declaring it."""
    repo = repo or REPO
    tables: dict[str, str] = {}
    for rel in MODEL_FILES:
        path = repo / rel
        if not path.is_file():
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Assign) or not isinstance(node.value, ast.Constant):
                continue
            if not isinstance(node.value.value, str):
                continue
            if any(isinstance(t, ast.Name) and t.id == "__tablename__" for t in node.targets):
                tables.setdefault(node.value.value, rel)
    return tables


def migrated_tables(repo: Path | None = None) -> dict[str, str]:
    """Every table a migration creates, mapped to the migration that creates it."""
    repo = repo or REPO
    created: dict[str, str] = {}
    base = repo / MIGRATIONS
    if not base.is_dir():
        return created
    for path in sorted(base.glob("*.py")):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:
            continue
        constants = _module_constants(tree)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not node.args:
                continue
            name = _call_name(node.func)
            if name != "create_table" and name not in _WRAPPERS:
                continue
            first = node.args[0]
            if isinstance(first, ast.Constant) and isinstance(first.value, str):
                created.setdefault(first.value, path.name)
            elif isinstance(first, ast.Name) and first.id in constants:
                created.setdefault(constants[first.id], path.name)
    return created


def check(repo: Path | None = None, verbose: bool = True) -> int:
    declared = declared_tables(repo)
    created = migrated_tables(repo)

    if not declared:
        print("schema migrations: no __tablename__ found — the scan is broken, not the ORM", file=sys.stderr)
        return 1
    if not created:
        print("schema migrations: no migration creates any table — the scan is broken", file=sys.stderr)
        return 1

    missing = sorted(set(declared) - set(created))
    if verbose:
        print(f"schema migrations: {len(declared)} ORM table(s), {len(created)} created by a migration")

    if missing:
        print(f"\nschema migrations: {len(missing)} table(s) exist only via create_all():", file=sys.stderr)
        for name in missing:
            print(f"  {name}  (declared in {declared[name]})", file=sys.stderr)
        print(
            "\ncreate_all() creates what is missing and never ALTERs, so a database upgraded "
            "from an older release keeps whatever it had while a fresh install gets today's "
            "schema. Add a migration in alembic/versions/ that creates the table.",
            file=sys.stderr,
        )
        return 1
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", action="store_true", help="exit non-zero if any table has no migration")
    ap.add_argument("--root", default=None, help="repository root (default: this script's repo)")
    ap.add_argument("files", nargs="*", help=argparse.SUPPRESS)
    args = ap.parse_args(argv)

    root = Path(args.root).resolve() if args.root else REPO

    if args.check:
        return check(root)

    declared, created = declared_tables(root), migrated_tables(root)
    print(f"{len(declared)} ORM table(s); {len(created)} created by a migration\n")
    for name in sorted(declared):
        where = created.get(name)
        print(f"  {'ok      ' if where else 'MISSING '} {name:<28} {where or '— create_all() only'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
