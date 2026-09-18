#!/usr/bin/env python3
# HOPEFX-AI-TRADING — Gate G: import discipline.
#
# Canonical vs. legacy directory rule (from AGENTS.md):
#
#   Domain          Canonical       Legacy (do NOT import from)
#   ---------       ----------      ---------------------------
#   Backtesting     backtesting/    backtest/
#   Strategies      strategies/     strategy/
#   Data pipeline   data_layer/     data/
#
# This gate scans every Python file in the GUARDED_PACKAGES and CANONICAL_DIRS
# and rejects any file that imports directly from a legacy package.
#
# Legacy packages are allowed to import from each other (re-export shims).
# Only imports FROM legacy packages INTO canonical packages are flagged.
#
# Additionally checks:
#   • data_layer/ internal sub-packages are not imported directly from outside
#     data_layer/ — only the public surface (data_layer.orchestrator,
#     data_layer.tick_store, data_layer.feeds.*) is allowed.
#
# KNOWN_VIOLATIONS tracks pre-existing legacy imports that pre-date this gate.
# These are reported as warnings (not failures) so CI is not broken by
# existing technical debt.  New violations — any not in this list — fail hard.
# When a KNOWN_VIOLATION is fixed, remove it from the list to keep the gate
# tight.
#
# Exits 0 on pass (or warn-only known violations), 1 on new violations.
from __future__ import annotations

import sys
import ast
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

# Packages that must not import from legacy directories
GUARDED_PACKAGES: tuple[str, ...] = (
    "api",
    "brain",
    "core",
    "execution",
    "ml",
    "risk",
    "strategies",
    "backtesting",
    "data_layer",
    "brokers",
    "auth",
    "news",
    "portfolio",
    "compliance",
    "monetization",
)

# Legacy top-level package names that canonical packages must not import from
LEGACY_PACKAGES: frozenset[str] = frozenset({"backtest", "strategy"})

# data_layer internal sub-packages that should not be imported directly from outside
# Only these top-level data_layer names are part of the public surface
DATA_LAYER_PUBLIC: frozenset[str] = frozenset(
    {
        "orchestrator",
        "tick_store",
        "feeds",
        # Allow direct sub-imports when the caller is inside data_layer itself
    }
)

# Pre-existing violations that predate this gate.
# Format: "relative/path/to/file.py:lineno"
# These are reported as warnings, not failures.
# Remove entries here when the underlying import is fixed.
#
# The seven below were invisible until the data_layer rule was fixed to check
# two-segment paths and `import x.y` statements (it previously required three
# segments and examined only `from x.y import z`). They are recorded rather
# than fixed because the fix is not mechanical: it means deciding what
# data_layer's public surface actually is — sentiment, microstructure and
# validation are all imported from outside it today — which is owner decision
# A2 in docs/ai/MASTER_OUTSTANDING.md, not a gate change.
#
# The keys are `path:imported-module`, NOT `path:line`. They were line-based,
# and that comment said so, adding that "editing a file above one of these
# imports turns a known violation into a 'new' one ... recorded here rather
# than redesigned in passing". It happened: unrelated edits to
# ml/inference_engine.py moved its data_layer.validation import from line 1097
# to 1184, and the gate failed CI claiming a new violation in an import nobody
# had touched.
#
# That failure mode is worse than the granularity it bought. The fix for a
# false "new violation" is to bump a number — and bumping a number is
# indistinguishable, in a diff, from allowlisting a genuinely new import. A
# gate whose repair procedure is "edit the allowlist until it passes" teaches
# people to do exactly the thing it exists to prevent.
#
# Keying on the imported module keeps the record narrow where narrowness
# means something: a listed entry covers `api/signals.py` importing
# `data_layer.sentiment`, and nothing else — not another module in that file,
# not that module in another file. It is insensitive only to *where in the
# file* the import sits, which was never the debt.
KNOWN_VIOLATIONS: frozenset[str] = frozenset(
    {
        "api/signals.py:data_layer.sentiment",
        "api/trading.py:data_layer.microstructure",
        "ml/inference_engine.py:data_layer.validation",
        "ml/train_advanced.py:data_layer.validation",
        "backtesting/data_handler.py:data_layer.validation",
        # engine_config.py imports data_layer.validation twice (was lines 220
        # and 593). One entry, because it is one piece of debt.
        "backtesting/engine_config.py:data_layer.validation",
    }
)


def _is_legacy_import(node: ast.Import | ast.ImportFrom) -> tuple[bool, str, str]:
    """Return (is_violation, reason, dotted_module) for an import node.

    The dotted module is what KNOWN_VIOLATIONS is keyed on, so it identifies
    the debt independently of where in the file the import happens to sit.
    """
    if isinstance(node, ast.ImportFrom) and node.module:
        parts = node.module.split(".")
        top = parts[0]
        if top in LEGACY_PACKAGES:
            return True, f"import from legacy package `{node.module}`", node.module
    elif isinstance(node, ast.Import):
        for alias in node.names:
            parts = alias.name.split(".")
            if parts[0] in LEGACY_PACKAGES:
                return True, f"import of legacy package `{alias.name}`", alias.name
    return False, "", ""


def _is_data_layer_internal(node: ast.Import | ast.ImportFrom, file_path: Path) -> tuple[bool, str, str]:
    """Return (is_violation, reason, dotted_module) for a data_layer internal import."""
    # Skip files inside data_layer/ — they can import each other freely
    try:
        file_path.relative_to(REPO_ROOT / "data_layer")
        return False, "", ""
    except ValueError:  # nosec B110 - relative_to raises ValueError when path is not under data_layer
        pass

    # Both statement forms reach data_layer internals, and both must be
    # checked. `import data_layer.internal.thing` was previously not examined
    # at all: only ImportFrom was.
    if isinstance(node, ast.ImportFrom) and node.module:
        candidates = [node.module]
    elif isinstance(node, ast.Import):
        candidates = [alias.name for alias in node.names]
    else:
        return False, "", ""

    for dotted in candidates:
        parts = dotted.split(".")
        # `>= 2`, not `>= 3`: the public surface is exactly the three names in
        # DATA_LAYER_PUBLIC, so `from data_layer.sentiment import x` is as much
        # a direct internal import as `data_layer.internal.thing` is. Requiring
        # three segments meant every top-level private module — sentiment,
        # microstructure — passed unexamined.
        if len(parts) >= 2 and parts[0] == "data_layer" and parts[1] not in DATA_LAYER_PUBLIC:
            return (
                True,
                (
                    f"direct import of data_layer internal `{dotted}` — "
                    f"use `data_layer.orchestrator`, `data_layer.tick_store`, "
                    f"or `data_layer.feeds.*` instead"
                ),
                dotted,
            )
    return False, "", ""


def check_file(py_file: Path) -> list[tuple[str, bool]]:
    """Return (message, is_known) pairs for a single Python file."""
    try:
        src = py_file.read_text(encoding="utf-8")
        tree = ast.parse(src, filename=str(py_file))
    except (OSError, SyntaxError):
        return []

    results: list[tuple[str, bool]] = []
    rel = py_file.relative_to(REPO_ROOT)

    for node in ast.walk(tree):
        if not isinstance(node, ast.Import | ast.ImportFrom):
            continue

        is_legacy, reason, dotted = _is_legacy_import(node)
        if is_legacy:
            # Keyed on the module; the line number stays in the *message* so a
            # human still gets taken straight to the import.
            is_known = f"{rel}:{dotted}" in KNOWN_VIOLATIONS
            results.append((f"{rel}:{node.lineno}: {reason}", is_known))
            continue

        is_internal, reason, dotted = _is_data_layer_internal(node, py_file)
        if is_internal:
            is_known = f"{rel}:{dotted}" in KNOWN_VIOLATIONS
            results.append((f"{rel}:{node.lineno}: {reason}", is_known))

    return results


def main() -> int:
    new_violations: list[str] = []
    known_warnings: list[str] = []

    for pkg in GUARDED_PACKAGES:
        pkg_dir = REPO_ROOT / pkg
        if not pkg_dir.is_dir():
            continue
        for py_file in sorted(pkg_dir.rglob("*.py")):
            if any(part in py_file.parts for part in (".venv", "venv", "__pycache__", "node_modules")):
                continue
            for msg, is_known in check_file(py_file):
                if is_known:
                    known_warnings.append(msg)
                else:
                    new_violations.append(msg)

    # Also scan top-level files that are part of the application
    for top_file in sorted(REPO_ROOT.glob("*.py")):
        if top_file.name.startswith("test_"):
            continue
        for msg, is_known in check_file(top_file):
            if is_known:
                known_warnings.append(msg)
            else:
                new_violations.append(msg)

    if known_warnings:
        print("[gate-g] WARN  pre-existing legacy imports (fix and remove from KNOWN_VIOLATIONS):\n")
        for w in known_warnings:
            print(f"  ⚠ {w}")
        print()

    if new_violations:
        print("[gate-g] FAIL — NEW import discipline violations:\n")
        for v in new_violations:
            print(f"  ✗ {v}")
        legacy_list = ", ".join(sorted(LEGACY_PACKAGES))
        print(
            f"\n  {len(new_violations)} new violation(s). "
            f"Do not import from legacy packages: {legacy_list}. "
            "See AGENTS.md — Canonical vs. Legacy Directories."
        )
        return 1

    status = "PASS" if not known_warnings else "PASS (with known warnings)"
    print(f"[gate-g] {status} — checked {len(GUARDED_PACKAGES)} packages, no new legacy imports")
    return 0


if __name__ == "__main__":
    sys.exit(main())
