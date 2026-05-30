#!/usr/bin/env python3
# HOPEFX-AI-TRADING — Gate I: Alembic migration chain integrity.
#
# Verifies that the Alembic migration history forms a valid, linear chain:
#   1. Exactly one root migration (down_revision is None).
#   2. Exactly one head migration (revision not referenced by any down_revision).
#   3. No duplicate revision IDs.
#   4. No broken links (every down_revision points to an existing revision).
#   5. No cycles in the revision graph.
#   6. All migration files are part of the same connected chain.
#
# A broken migration chain means `alembic upgrade head` will fail in production,
# potentially leaving the database schema in an inconsistent state.
#
# Exits 0 on pass, 1 on failure.
from __future__ import annotations

import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
VERSIONS_DIR = REPO_ROOT / "alembic" / "versions"

# Matches: revision: str = "abc123"  (with optional pragma comment)
_REVISION_RE = re.compile(r'^revision\s*(?::\s*\S+)?\s*=\s*["\']([^"\']+)["\']', re.MULTILINE)
# Matches: down_revision: str | ... = "abc123" or = None or = ("a", "b")
_DOWN_RE = re.compile(
    r'^down_revision\s*(?::\s*\S+(?:\s*\|\s*\S+)*)?\s*=\s*(.+)$',
    re.MULTILINE,
)


def _parse_down_revision(raw: str) -> set[str] | None:
    """
    Parse the raw RHS of a ``down_revision = …`` assignment.

    Returns:
        None          if the migration is the root (down_revision is None).
        set[str]      containing one or more parent revision IDs.
    """
    raw = raw.strip()
    # Strip inline comments
    raw = re.sub(r"\s*#.*", "", raw).strip()

    if raw in ("None", ""):
        return None

    # Tuple form: ("abc", "def")
    ids = re.findall(r'["\']([^"\']+)["\']', raw)
    if ids:
        return set(ids)

    return None  # unrecognised form — treat as root to avoid false positives


def _collect_migrations(versions_dir: Path) -> dict[str, set[str] | None]:
    """
    Return mapping: revision_id → set_of_parent_ids | None (for root).
    """
    migrations: dict[str, set[str] | None] = {}

    for py_file in sorted(versions_dir.glob("*.py")):
        text = py_file.read_text(encoding="utf-8")

        rev_m = _REVISION_RE.search(text)
        if not rev_m:
            continue  # not a migration file (e.g. __init__.py)

        rev_id = rev_m.group(1).strip()

        down_m = _DOWN_RE.search(text)
        if down_m:
            parents = _parse_down_revision(down_m.group(1))
        else:
            parents = None  # treat missing down_revision as root

        migrations[rev_id] = parents

    return migrations


def _detect_cycle(
    rev_id: str,
    graph: dict[str, set[str] | None],
    visited: set[str],
    path: set[str],
) -> list[str] | None:
    """Return the cycle path if one is found, else None."""
    if rev_id in path:
        return [rev_id]
    if rev_id in visited:
        return None
    visited.add(rev_id)
    path.add(rev_id)
    parents = graph.get(rev_id)
    if parents:
        for parent in parents:
            result = _detect_cycle(parent, graph, visited, path)
            if result is not None:
                return [rev_id, *result]
    path.discard(rev_id)
    return None


def main() -> int:  # noqa: C901
    if not VERSIONS_DIR.exists():
        print(f"[gate-i] SKIP  {VERSIONS_DIR} not found — no Alembic migrations to validate.")
        return 0

    migrations = _collect_migrations(VERSIONS_DIR)

    if not migrations:
        print("[gate-i] SKIP  No migration files found.")
        return 0

    failures: list[str] = []

    # ── 1. Duplicate revision IDs ─────────────────────────────────────────────
    # _collect_migrations already uses a dict so duplicates would silently
    # overwrite. Re-scan for them explicitly.
    all_rev_ids: list[str] = []
    for py_file in sorted(VERSIONS_DIR.glob("*.py")):
        text = py_file.read_text(encoding="utf-8")
        for m in _REVISION_RE.finditer(text):
            all_rev_ids.append(m.group(1).strip())
    seen: set[str] = set()
    for rid in all_rev_ids:
        if rid in seen:
            failures.append(f"Duplicate revision ID: {rid}")
        seen.add(rid)

    # ── 2. Broken down_revision links ─────────────────────────────────────────
    for rev_id, parents in migrations.items():
        if parents is None:
            continue
        for parent in parents:
            if parent not in migrations:
                failures.append(
                    f"Revision {rev_id!r} references unknown parent {parent!r}"
                )

    # ── 3. Exactly one root ───────────────────────────────────────────────────
    roots = [rid for rid, parents in migrations.items() if parents is None]
    if len(roots) == 0:
        failures.append("No root migration found (every revision has a down_revision).")
    elif len(roots) > 1:
        failures.append(
            f"Multiple root migrations found (expected 1, got {len(roots)}): "
            + ", ".join(sorted(roots))
        )

    # ── 4. Exactly one head ───────────────────────────────────────────────────
    all_parents: set[str] = set()
    for parents in migrations.values():
        if parents:
            all_parents.update(parents)
    heads = [rid for rid in migrations if rid not in all_parents]
    if len(heads) == 0:
        failures.append("No head migration found — possible cycle or empty chain.")
    elif len(heads) > 1:
        failures.append(
            f"Multiple heads found (merge migrations not yet supported): "
            + ", ".join(sorted(heads))
            + "\n  Run `alembic merge heads` to create a merge migration."
        )

    # ── 5. Cycle detection ────────────────────────────────────────────────────
    visited: set[str] = set()
    for rev_id in migrations:
        cycle = _detect_cycle(rev_id, migrations, visited, set())
        if cycle:
            failures.append(f"Cycle detected in migration chain: {' → '.join(cycle)}")
            break  # one cycle report is enough

    # ── 6. All nodes reachable from root ──────────────────────────────────────
    if len(roots) == 1:
        # Build child graph for forward traversal
        children: dict[str, list[str]] = {rid: [] for rid in migrations}
        for rev_id, parents in migrations.items():
            if parents:
                for parent in parents:
                    if parent in children:
                        children[parent].append(rev_id)

        reachable: set[str] = set()
        stack = [roots[0]]
        while stack:
            node = stack.pop()
            if node in reachable:
                continue
            reachable.add(node)
            stack.extend(children.get(node, []))

        unreachable = set(migrations) - reachable
        if unreachable:
            failures.append(
                f"{len(unreachable)} migration(s) unreachable from root: "
                + ", ".join(sorted(unreachable))
            )

    if failures:
        print(f"Gate I FAILED — {len(failures)} migration chain issue(s):")
        for f in failures:
            print(f"  • {f}")
        return 1

    print(
        f"Gate I PASSED — {len(migrations)} migrations form a valid linear chain "
        f"(root: {roots[0]!r}, head: {heads[0]!r})."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
