#!/usr/bin/env python3
# HOPEFX-AI-TRADING — Gate E: dead file detection.
#
# Finds Python modules that are never imported by any other module in the repo.
# A "dead" file may indicate:
#   • Unused code that adds maintenance burden and attack surface
#   • A module that was intended to be wired but was accidentally disconnected
#
# False-positive categories are excluded via EXCLUDED_PATTERNS and
# KNOWN_ENTRY_POINTS.  The gate fails only when a file in GUARDED_PACKAGES
# is completely unreferenced — these are the packages where dead code matters
# most (execution paths, risk, ML inference).
#
# Exits 0 on pass, 1 on failure.
from __future__ import annotations

import ast
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

# ── Modules with no production caller, each with the reason it stays ──────────
#
# Same idiom as gate-g's KNOWN_VIOLATIONS: a recorded debt, not an off-switch.
# Anything NOT listed here still fails the gate, so a newly orphaned file blocks
# the build. A reason is mandatory — `scripts/ci/` has a test asserting every
# entry carries one, and asserting that no entry has quietly become wired.
#
# This gate reported zero for its whole life until 2026-09-09, when three
# stacked defects in its own detection were fixed (single-file guarded packages
# were skipped, bare-package imports were not resolved, and every mirrored test
# file was excluded by a substring match). Turning it on surfaced these twelve
# at once. They are triaged, not silenced — the owner's standing instruction is
# that nothing is deleted, so each is recorded with what replaced it or why it
# has no caller yet.
KNOWN_UNWIRED: dict[str, str] = {
    # ── Superseded: something else does this job now ──────────────────────────
    "brokers/oanda_ws.py": (
        "Tombstone. Its own docstring says REMOVED — OANDAStreamAdapter moved to "
        "data_feed.NuclearStreamer. Kept so an old import fails loudly with a "
        "pointer rather than an opaque ModuleNotFoundError."
    ),
    "core/tenancy.py": (
        "Superseded. Written because /api/trading/orders, /balance and portfolio "
        "did not filter rows by owner. Verified 2026-09-09: all three now resolve "
        "per-user broker accounts via _resolve_account(user.sub) and "
        "_user_broker_call(user.sub, ...), so the leak it targeted is closed by a "
        "different mechanism. Not a live security gap."
    ),
    "risk/risk_manager.py": (
        "Backwards-compatibility shim re-exporting risk.manager. 63 lines, kept "
        "so external or older imports keep resolving."
    ),
    # ── Alternative entry points, reachable by hand, not deployed ─────────────
    "execution/execution.py": (
        "Alternative startup wiring, like trader_full.py. The container runs "
        "app.py and run.py uses HopeFXEngine, so nothing imports this — it is "
        "invoked directly when someone wants the standalone execution system."
    ),
    # ── Hardware or environment gated ─────────────────────────────────────────
    "core/acceleration/gpu_engine.py": (
        "Requires CUDA. Already omitted from coverage for the same reason "
        "(.coveragerc). Imported only when a GPU is present."
    ),
    "brokers/mt5_zmq_bridge.py": (
        "ZeroMQ bridge to MetaTrader 5, which is Windows-only. The MT5 SDK is "
        "not installable in CI or on the Linux VPS, so nothing imports it there."
    ),
    # ── Type and utility libraries used by tests and future callers ───────────
    "core/domain_models.py": (
        "Pydantic v2 domain models (Signal, Position, Account...). Production "
        "code duck-types these objects via getattr rather than importing the "
        "classes, so the library has no import edge despite being the schema "
        "those objects are built to."
    ),
    # ── Built, not yet wired. Each needs a decision, not deletion ─────────────
    "risk/analytics.py": "Quantitative risk analytics engine; risk/advanced_analytics.py is the wired one.",
    "risk/position_sizing.py": "ATR/fixed-risk/Kelly sizing; risk/manager.py carries the sizing that runs.",
    "core/circuit_breaker.py": "Broker-API circuit breaker; utils/fault_guard.py is the wired one.",
    "risk/compliance/prop_engine.py": "Prop-firm compliance engine; prop_firm_mode.json config is read elsewhere.",
    "brokers/prop_firms/all_brokers.py": "Prop-firm broker adapters, 1301 lines, no current caller.",
}


# Packages where dead files are a real risk (unused execution/risk code)
GUARDED_PACKAGES: frozenset[str] = frozenset(
    {
        "execution",
        "risk",
        "kill_switch",
        "brokers",
        "core",
    }
)

# Patterns whose files are intentionally standalone and never imported —
# used to decide what's checked AS a guarded candidate.
EXCLUDED_PATTERNS: tuple[str, ...] = (
    "test_",
    "conftest",
    "__init__",
    "migrations/",
    "alembic/",
    "scripts/",
    "frontend/",
    "dashboard/",
    "mobile",
    "docs/",
    "helm/",
    "k8s/",
    ".venv/",
    "site-packages/",
    # Entry-point scripts run directly, not imported
    "manage.py",
    "wsgi.py",
    "asgi.py",
    "celery_app.py",
    "app.py",
    "trader_full.py",
    "connect_to_life.py",
    "main.py",
    "worker.py",
)

# A DELIBERATELY SMALLER list — non-Python-source trees and test-only code,
# used to decide what's scanned AS A SOURCE of imports. Entry-point scripts
# (app.py, celery_app.py, ...) and __init__.py are excluded above from being
# checked as guarded candidates, correctly — they're run directly or are
# package boilerplate, not "a module someone imports". But they are exactly
# where late route/task registration and package re-exports live
# (`app.py:1053: from core.health import register_health_routes`,
# `brokers/__init__.py: from brokers.smart_router import SmartOrderRouter`),
# so excluding them here too made the file they import look dead. Sharing
# one list for both questions is what caused it.
IMPORT_SCAN_EXCLUDED_PATTERNS: tuple[str, ...] = (
    "test_",
    "conftest",
    "migrations/",
    "alembic/",
    "scripts/",
    "frontend/",
    "dashboard/",
    "mobile",
    "docs/",
    "helm/",
    "k8s/",
    ".venv/",
    "site-packages/",
)


def _collect_py_files(root: Path, package: str) -> list[Path]:
    pkg_dir = root / package
    if pkg_dir.is_dir():
        return [p for p in pkg_dir.rglob("*.py") if not any(exc in str(p) for exc in EXCLUDED_PATTERNS)]
    # Some guarded names are a single top-level module, not a package
    # directory — kill_switch.py, not kill_switch/. Treat it as the one
    # file to check rather than silently checking nothing.
    single_file = root / f"{package}.py"
    if single_file.is_file() and not any(exc in str(single_file) for exc in EXCLUDED_PATTERNS):
        return [single_file]
    return []


def _module_name(path: Path, root: Path) -> str:
    rel = path.relative_to(root)
    return str(rel).replace("/", ".").removesuffix(".py")


def _collect_all_imports(root: Path) -> tuple[set[str], set[str]]:
    """
    Return (exact, bare_packages) from every import statement across the repo.

    exact          : dotted names a specific import statement actually named
                      ("execution.live" from `import execution.live`, or from
                      `from execution import live`).
    bare_packages   : names imported with NO further qualification at all
                      ("execution" from a literal `import execution`) — the
                      only case where "the parent is imported, so treat every
                      submodule as reachable via attribute access" applies.

    The two must stay separate. `import execution.live` used to add both
    "execution.live" AND "execution" (as a synthesised prefix) to one set,
    so `execution.orphan.startswith("execution" + ".")` was True purely
    because a *sibling* was imported — every file in a guarded package
    counted as live the moment anything else in that package was imported,
    which in a real codebase is always. Injecting a genuinely dead file
    next to an imported one caught nothing until this split existed.
    """
    exact: set[str] = set()
    bare_packages: set[str] = set()
    for py_file in root.rglob("*.py"):
        if any(exc in str(py_file) for exc in IMPORT_SCAN_EXCLUDED_PATTERNS):
            continue
        try:
            source = py_file.read_text(encoding="utf-8", errors="replace")
            tree = ast.parse(source, filename=str(py_file))
        except SyntaxError:
            continue

        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    exact.add(alias.name)
                    if "." not in alias.name:
                        bare_packages.add(alias.name)

            elif isinstance(node, ast.ImportFrom) and node.module:
                # `from A.B.C import D` genuinely runs A/B/C.py regardless of
                # what D is — a class, function, or a further submodule — so
                # the module itself is unambiguously live. This is not the
                # same shape as the ast.Import prefix bug above: `exact` is
                # matched exactly, not by prefix, so this cannot also grant
                # liveness to A/B/other.py the way a bare `import A` would.
                exact.add(node.module)
                # `from execution import live` additionally names
                # execution.live specifically, in case D names a genuine
                # submodule file (execution/live.py) rather than an
                # attribute of execution itself.
                for alias in node.names:
                    if alias.name != "*":
                        exact.add(f"{node.module}.{alias.name}")

    return exact, bare_packages


def main() -> int:
    exact_imports, bare_packages = _collect_all_imports(REPO_ROOT)
    dead: list[str] = []

    for package in sorted(GUARDED_PACKAGES):
        for py_file in _collect_py_files(REPO_ROOT, package):
            mod = _module_name(py_file, REPO_ROOT)
            # A file is "live" if:
            #   1. Its full module name is imported (e.g., "execution.engine")
            #   2. A genuinely bare parent package is imported — "import
            #      execution" with no further qualification — so every
            #      submodule is reachable via attribute access
            # Do NOT mark a file live just because a SIBLING import happened
            # to be qualified with the same package prefix (e.g. `import
            # execution.other` must not make "execution.signal_engine" live).
            is_live = mod in exact_imports or any(mod.startswith(bp + ".") for bp in bare_packages)
            if not is_live:
                dead.append(str(py_file.relative_to(REPO_ROOT)))

    known = [d for d in dead if d in KNOWN_UNWIRED]
    dead = [d for d in dead if d not in KNOWN_UNWIRED]

    if known:
        print(f"Gate E: {len(known)} recorded unwired module(s) — reason on each, not silenced:")
        for path in sorted(known):
            print(f"  · {path}")
            print(f"      {KNOWN_UNWIRED[path]}")
        print()

    if dead:
        print(f"Gate E FAILED — {len(dead)} potentially dead file(s) in guarded packages:")
        for d in sorted(dead):
            print(f"  {d}")
        print()
        print("Either wire these modules into the codebase or move them to scripts/.")
        return 1

    print(f"Gate E PASSED — no dead files found in guarded packages ({', '.join(sorted(GUARDED_PACKAGES))}).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
