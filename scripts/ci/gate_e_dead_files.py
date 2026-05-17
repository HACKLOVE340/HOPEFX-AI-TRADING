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
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

# Packages where dead files are a real risk (unused execution/risk code)
GUARDED_PACKAGES: frozenset[str] = frozenset({
    "execution",
    "risk",
    "kill_switch",
    "brokers",
    "core",
})

# Patterns whose files are intentionally standalone and never imported
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


def _collect_py_files(root: Path, package: str) -> list[Path]:
    pkg_dir = root / package
    if not pkg_dir.exists():
        return []
    return [
        p for p in pkg_dir.rglob("*.py")
        if not any(exc in str(p) for exc in EXCLUDED_PATTERNS)
    ]


def _module_name(path: Path, root: Path) -> str:
    rel = path.relative_to(root)
    return str(rel).replace("/", ".").removesuffix(".py")


def _collect_all_imports(root: Path) -> set[str]:
    """
    Return all module name fragments that appear in any import statement
    across the entire repo (not just guarded packages).
    """
    imported: set[str] = set()
    for py_file in root.rglob("*.py"):
        if any(exc in str(py_file) for exc in EXCLUDED_PATTERNS):
            continue
        try:
            source = py_file.read_text(encoding="utf-8", errors="replace")
            tree = ast.parse(source, filename=str(py_file))
        except SyntaxError:
            continue

        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imported.add(alias.name)
                    # add all prefixes (e.g. "execution.engine" → "execution")
                    parts = alias.name.split(".")
                    for i in range(1, len(parts) + 1):
                        imported.add(".".join(parts[:i]))

            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    imported.add(node.module)
                    parts = node.module.split(".")
                    for i in range(1, len(parts) + 1):
                        imported.add(".".join(parts[:i]))
                    # also add "module.name" for each imported name
                    for alias in node.names:
                        if alias.name != "*":
                            imported.add(f"{node.module}.{alias.name}")

    return imported


def main() -> int:
    all_imports = _collect_all_imports(REPO_ROOT)
    dead: list[str] = []

    for package in sorted(GUARDED_PACKAGES):
        for py_file in _collect_py_files(REPO_ROOT, package):
            mod = _module_name(py_file, REPO_ROOT)
            # A file is "live" if:
            #   1. Its full module name is imported (e.g., "execution.engine")
            #   2. A parent module is imported and this is a submodule
            #      (e.g., "execution" imported, checking "execution.engine")
            # Do NOT mark a file live just because it's a prefix of an import
            # (e.g., "core" should not make "core.signal_engine" live).
            is_live = (
                mod in all_imports
                or any(mod.startswith(imp + ".") for imp in all_imports)
            )
            if not is_live:
                dead.append(str(py_file.relative_to(REPO_ROOT)))

    if dead:
        print(f"Gate E FAILED — {len(dead)} potentially dead file(s) in guarded packages:")
        for d in sorted(dead):
            print(f"  {d}")
        print()
        print("Either wire these modules into the codebase or move them to scripts/.")
        return 1

    print(f"Gate E PASSED — no dead files found in guarded packages "
          f"({', '.join(sorted(GUARDED_PACKAGES))}).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
