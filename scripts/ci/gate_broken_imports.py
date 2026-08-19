#!/usr/bin/env python3
# HOPEFX-AI-TRADING — Gate: broken local-import detection.
#
# An audit found ``from <local.module> import <Name>`` statements where <Name>
# does not actually exist in <local.module> — usually a rename that did not
# propagate.  A broad ``except ImportError`` around the import then swallows the
# failure and a feature silently dies.
#
# This gate is a pure static (AST-based, no runtime import) checker.  For every
# ``from <local.dotted.module> import <Name>`` in the repo it:
#   1. resolves <local.dotted.module> to its ``.py`` file (module or package),
#   2. flags <Name> if it is NOT bound at top level in that file, where "bound"
#      means: a ``def``/``async def``, a ``class``, a top-level assignment
#      (incl. annotated/augmented/tuple-unpack), an ``import ... as Name`` /
#      ``import Name``, or a ``from ... import Name`` / ``from ... import x as
#      Name``.
#
# Only *local* modules (those that resolve to a file inside the repo) are
# checked.  Third-party / stdlib imports are ignored.  When a package is
# imported and <Name> resolves to a real submodule file (``pkg/Name.py``) or a
# subpackage (``pkg/Name/__init__.py``), it is considered valid even if not
# re-exported from ``__init__``.
#
# ``__all__`` / star-exports and ``__getattr__`` module hooks are treated as
# "cannot statically prove broken" and are NOT flagged (to avoid false
# positives on lazy re-export shims).
#
# Exits 0 on pass, 1 on any broken import.
from __future__ import annotations

import ast
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

# Directories we never want to scan (vendored / generated / non-source trees).
EXCLUDED_DIR_PARTS: frozenset[str] = frozenset(
    {
        ".venv",
        "venv",
        "site-packages",
        "node_modules",
        "frontend",
        "dashboard",
        "mobile-app",
        ".git",
        "build",
        "dist",
        "__pycache__",
    }
)


# ── Known-broken baseline ────────────────────────────────────────────────────
# Imports that name a symbol the target module does not define, recorded with a
# justification so this gate can run in CI and block *new* occurrences without
# first requiring every historical one to be fixed.
#
# This is a baseline, not an excuse list. Two rules keep it from rotting:
#   1. Every entry needs a reason a reviewer can check, and a backlog reference
#      where the fix is tracked.
#   2. A stale entry — one that is no longer broken — FAILS the gate, so fixing
#      an import forces the entry to be deleted in the same change.
#
# Keyed by (file, imported name, source module); no line numbers, so ordinary
# edits above an entry do not invalidate it.
KNOWN_BROKEN: dict[tuple[str, str, str], str] = {
    # Deliberate forward compatibility. KillSwitch._resolve_active_broker tries
    # these two accessors before the one that resolves today
    # (core.app_state.app_state.broker). Documented in HARDENING_BACKLOG S-38,
    # which is the defect caused by the chain NOT having that third step.
    ("kill_switch.py", "get_active_broker", "execution.engine"): "S-38 forward-compat step 1 of 3; step 3 resolves",
    ("kill_switch.py", "get_router", "execution.smart_router"): "S-38 forward-compat step 2 of 3; step 3 resolves",
    # ── Features written against an API that was never built (S-41) ──────────
    # Each degrades to a documented no-op today. Fixing them is implementation
    # work, not a rename, and several need a product decision first.
    (
        "api/admin.py",
        "email_service",
        "core.email_service",
    ): "S-41 admin password reset; module is functions, needs a reset token",
    ("api/admin.py", "get_email_service", "core.email_service"): "S-41 SMTP test; no public generic send_email",
    (
        "api/news_feed.py",
        "NewsFeedManager",
        "data_layer.feeds.news.base",
    ): "S-41 no manager class exists; NewsFeedBase is abstract",
    ("api/nocode.py", "StateMachineEngine", "nocode.state_machine"): "S-41 validate_graph exists nowhere in the repo",
    (
        "api/superadmin/risk_management.py",
        "_GLOBAL_REGISTRY",
        "risk.circuit_breakers",
    ): "S-41 reset/force-open call methods CircuitBreaker lacks",
    ("ml/continuous_learning.py", "train_model", "ml.training"): "S-41 train_ml_pipeline has a different signature",
    (
        "ml/training_manager.py",
        "retrain_advanced_predictor",
        "ml.train_advanced",
    ): "S-41 no programmatic retrain entry point",
    ("ml/training_manager.py", "retrain_lstm", "ml.lstm_signal_layer"): "S-41 no retrain function exists",
    (
        "strategies/dynamic_registry.py",
        "DynamicStrategy",
        "database.models",
    ): "S-41 no such model or migration; registry is memory-only",
}


def _is_excluded(path: Path) -> bool:
    return any(part in EXCLUDED_DIR_PARTS for part in path.parts)


def _iter_py_files(root: Path):
    for p in root.rglob("*.py"):
        if _is_excluded(p.relative_to(root)):
            continue
        yield p


def _module_to_file(module: str, root: Path) -> Path | None:
    """Resolve a dotted module name to a ``.py`` file inside the repo.

    Returns the module file (``a/b.py``) or the package init
    (``a/b/__init__.py``), or ``None`` if it does not resolve to a local file.
    """
    rel = Path(*module.split("."))
    mod_file = root / rel.with_suffix(".py")
    if mod_file.exists():
        return mod_file
    pkg_init = root / rel / "__init__.py"
    if pkg_init.exists():
        return pkg_init
    return None


def _is_local_module(module: str, root: Path) -> bool:
    return _module_to_file(module, root) is not None


def _submodule_exists(package_module: str, name: str, root: Path) -> bool:
    """True if ``package_module.name`` resolves to a local submodule/subpackage."""
    return _module_to_file(f"{package_module}.{name}", root) is not None


def _top_level_bindings(tree: ast.Module) -> tuple[set[str], bool]:
    """Return (names bound at module top level, has_dynamic_export).

    ``has_dynamic_export`` is True when the module defines ``__all__`` via a
    non-trivial construct, a module-level ``__getattr__``, or a wildcard
    ``from x import *`` — cases where static analysis cannot prove a name is
    absent, so callers should not flag it.
    """
    names: set[str] = set()
    dynamic = False

    def _add_target(target: ast.expr) -> None:
        if isinstance(target, ast.Name):
            names.add(target.id)
        elif isinstance(target, (ast.Tuple, ast.List)):
            for elt in target.elts:
                _add_target(elt)
        elif isinstance(target, ast.Starred):
            _add_target(target.value)

    def _visit(body: list[ast.stmt]) -> None:
        nonlocal dynamic
        for node in body:
            # Record the name but do NOT descend into def/class bodies — those
            # introduce a new (non-module) scope.
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                names.add(node.name)
            elif isinstance(node, ast.Assign):
                for t in node.targets:
                    _add_target(t)
            elif isinstance(node, (ast.AnnAssign, ast.AugAssign)):
                _add_target(node.target)
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    bound = alias.asname or alias.name.split(".")[0]
                    names.add(bound)
            elif isinstance(node, ast.ImportFrom):
                for alias in node.names:
                    if alias.name == "*":
                        dynamic = True
                        continue
                    names.add(alias.asname or alias.name)
            # Recurse into module-level control-flow blocks: names bound inside
            # ``if``/``try``/``with``/``for``/``while`` are still module-level
            # (commonly feature-flag-guarded definitions).
            elif isinstance(node, ast.If):
                _visit(node.body)
                _visit(node.orelse)
            elif isinstance(node, ast.Try):
                _visit(node.body)
                for handler in node.handlers:
                    _visit(handler.body)
                _visit(node.orelse)
                _visit(node.finalbody)
            elif isinstance(node, (ast.With, ast.AsyncWith)):
                _visit(node.body)
            elif isinstance(node, (ast.For, ast.AsyncFor, ast.While)):
                _visit(node.body)
                _visit(node.orelse)

    _visit(tree.body)

    if "__all__" in names or "__getattr__" in names:
        dynamic = True

    # Modules that inject names dynamically via ``globals().update(...)`` /
    # ``globals()[name] = ...`` (e.g. lazy re-export shims) cannot be resolved
    # statically — treat them as dynamic so we don't false-positive.
    if not dynamic:
        for sub in ast.walk(tree):
            if isinstance(sub, ast.Call) and isinstance(sub.func, ast.Name) and sub.func.id == "globals":
                dynamic = True
                break

    return names, dynamic


# Cache of file -> (bindings, dynamic) to avoid re-parsing target modules.
_BINDING_CACHE: dict[Path, tuple[set[str], bool]] = {}


def _bindings_for_file(path: Path) -> tuple[set[str], bool]:
    if path in _BINDING_CACHE:
        return _BINDING_CACHE[path]
    try:
        tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"), filename=str(path))
        result = _top_level_bindings(tree)
    except SyntaxError:
        # If the target module cannot be parsed, don't flag against it.
        result = (set(), True)
    _BINDING_CACHE[path] = result
    return result


def _check_file(py_file: Path, root: Path) -> list[tuple[int, str, str]]:
    """Return list of (lineno, bad_name, target_module) for broken imports."""
    broken: list[tuple[int, str, str]] = []
    try:
        tree = ast.parse(py_file.read_text(encoding="utf-8", errors="replace"), filename=str(py_file))
    except SyntaxError:
        return broken

    for node in ast.walk(tree):
        if not isinstance(node, ast.ImportFrom):
            continue
        # Skip relative imports (``from . import x``) — resolving them robustly
        # is out of scope; the audit targets absolute local imports.
        if node.level and node.level > 0:
            continue
        module = node.module
        if not module:
            continue
        target = _module_to_file(module, root)
        if target is None:
            continue  # not a local module — third-party/stdlib, ignore

        bindings, dynamic = _bindings_for_file(target)
        if dynamic:
            continue

        for alias in node.names:
            if alias.name == "*":
                continue
            name = alias.name
            if name in bindings:
                continue
            # ``from pkg import submodule`` where submodule is a real file.
            if _submodule_exists(module, name, root):
                continue
            broken.append((node.lineno, name, module))

    return broken


def main() -> int:
    findings: list[tuple[str, int, str, str]] = []

    for py_file in sorted(_iter_py_files(REPO_ROOT)):
        for lineno, name, module in _check_file(py_file, REPO_ROOT):
            rel = str(py_file.relative_to(REPO_ROOT))
            findings.append((rel, lineno, name, module))

    new_findings = [f for f in findings if (f[0], f[2], f[3]) not in KNOWN_BROKEN]
    seen = {(rel, name, module) for rel, _, name, module in findings}
    stale = [key for key in KNOWN_BROKEN if key not in seen]

    failed = False

    if new_findings:
        failed = True
        print(f"Gate broken-imports FAILED — {len(new_findings)} new broken local import(s):")
        for rel, lineno, name, module in sorted(new_findings):
            print(f"  {rel}:{lineno}  imports '{name}' from '{module}' — not defined there")
        print()
        print("Fix the import name (find the real symbol) or guard it with a")
        print("clear degradation path instead of a hard failure.")
        print("If it is genuinely intentional, add it to KNOWN_BROKEN in this")
        print("file with a reason and a backlog reference.")

    if stale:
        failed = True
        print(f"Gate broken-imports FAILED — {len(stale)} stale KNOWN_BROKEN entr(ies):")
        for rel, name, module in sorted(stale):
            print(f"  {rel}  '{name}' from '{module}' — no longer broken; delete this entry")
        print()
        print("An allowlist entry that no longer describes a real defect hides")
        print("the next one. Remove it in the change that fixed the import.")

    if failed:
        return 1

    print(
        f"Gate broken-imports PASSED — no new broken local imports "
        f"({len(KNOWN_BROKEN)} known, tracked in docs/HARDENING_BACKLOG.md)."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
