#!/usr/bin/env python3
# HOPEFX-AI-TRADING — Gate F: documentation/code consistency.
#
# Scans ARCHITECTURE.md, AGENTS.md, and CONTRIBUTING.md for Python
# identifiers used in code blocks (class names, function names, import paths).
# For each identifier, checks that the symbol or module actually exists in the
# repository.  This prevents documentation drift such as:
#   • Referencing a class with the wrong capitalisation (NuclearWordmapScorer
#     instead of NuclearWordMapScorer)
#   • Documenting a method that has been renamed (.score() → .score_event())
#   • Importing from a path that no longer exists
#
# Rules checked
# -------------
# 1. ``from <module> import <name>`` in fenced code blocks:
#    - The module path must resolve to a .py file under REPO_ROOT.
#    - The imported name must be defined at the top level of that module.
# 2. Class/function instantiation ``<Name>(`` found in fenced Python blocks:
#    - The name must exist somewhere in the repo as a class or function
#      definition (``class Name`` / ``def Name``).
#
# Exits 0 on pass, 1 on failure.
from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

# Docs to scan for code examples
DOCS_TO_SCAN: tuple[Path, ...] = (
    REPO_ROOT / "ARCHITECTURE.md",
    REPO_ROOT / "AGENTS.md",
    REPO_ROOT / "CONTRIBUTING.md",
)

# Identifiers that are external packages or stdlib — skip module resolution
EXTERNAL_PREFIXES: tuple[str, ...] = (
    "fastapi",
    "pydantic",
    "sqlalchemy",
    "redis",
    "pytest",
    "asyncio",
    "os",
    "sys",
    "json",
    "logging",
    "pathlib",
    "typing",
    "dataclasses",
    "abc",
    "enum",
    "datetime",
    "collections",
    "itertools",
    "functools",
    "contextlib",
    "threading",
    "multiprocessing",
    "subprocess",
    "shutil",
    "tempfile",
    "io",
    "re",
    "math",
    "random",
    "time",
    "hashlib",
    "hmac",
    "secrets",
    "base64",
    "struct",
    "copy",
    "inspect",
    "importlib",
    "unittest",
    "http",
    "urllib",
    "socket",
    "ssl",
    "email",
    "html",
    "xml",
    "csv",
    "configparser",
    "argparse",
    "strategies.base",  # known public API
    "brokers.base",
    "brokers.factory",
)

# Names that are builtins, placeholders, or well-known patterns — skip lookup
SKIP_NAMES: frozenset[str] = frozenset(
    {
        "BaseStrategy",
        "BaseBroker",
        "MyStrategy",
        "MyBroker",
        "Signal",
        "SignalType",
        "Order",
        "Position",
        "APIRouter",
        "Depends",
        "app",
        "router",
        "logger",
        "print",
        "True",
        "False",
        "None",
    }
)


def _extract_python_blocks(md_path: Path) -> list[tuple[int, str]]:
    """Return (start_line, code) for all ```python fenced blocks."""
    blocks: list[tuple[int, str]] = []
    lines = md_path.read_text(encoding="utf-8").splitlines()
    in_block = False
    block_lines: list[str] = []
    block_start = 0
    for i, line in enumerate(lines, 1):
        if not in_block and re.match(r"^```python\s*$", line):
            in_block = True
            block_start = i
            block_lines = []
        elif in_block and re.match(r"^```\s*$", line):
            blocks.append((block_start, "\n".join(block_lines)))
            in_block = False
        elif in_block:
            block_lines.append(line)
    return blocks


def _module_path_to_file(module: str) -> Path | None:
    """Translate a dotted module name to a .py file under REPO_ROOT."""
    parts = module.split(".")
    # Try as package (__init__.py)
    pkg_init = REPO_ROOT.joinpath(*parts) / "__init__.py"
    if pkg_init.exists():
        return pkg_init
    # Try as module file
    mod_file = REPO_ROOT.joinpath(*parts[:-1]) / f"{parts[-1]}.py"
    if mod_file.exists():
        return mod_file
    # Try as top-level module file
    top_file = REPO_ROOT / f"{parts[0]}.py"
    if len(parts) == 1 and top_file.exists():
        return top_file
    return None


def _top_level_names(py_file: Path) -> frozenset[str]:
    """Return class and function names defined at the top level of a module."""
    try:
        tree = ast.parse(py_file.read_text(encoding="utf-8"), filename=str(py_file))
    except SyntaxError:
        return frozenset()
    names: set[str] = set()
    for node in ast.iter_child_nodes(tree):
        if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            names.add(node.name)
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    names.add(target.id)
    return frozenset(names)


def _repo_defines_name(name: str) -> bool:
    """Return True if any Python file in the repo defines `name` as a class/func."""
    pattern_class = re.compile(rf"^class {re.escape(name)}\b", re.MULTILINE)
    pattern_func = re.compile(rf"^def {re.escape(name)}\b", re.MULTILINE)
    for py_file in REPO_ROOT.rglob("*.py"):
        # Skip virtual environments and cache dirs
        if any(
            part in py_file.parts
            for part in (".venv", "venv", "__pycache__", "node_modules")
        ):
            continue
        try:
            src = py_file.read_text(encoding="utf-8")
        except OSError:
            continue
        if pattern_class.search(src) or pattern_func.search(src):
            return True
    return False


def check_doc(md_path: Path) -> list[str]:
    """Return a list of violation messages for a single documentation file."""
    violations: list[str] = []
    blocks = _extract_python_blocks(md_path)

    for block_line, code in blocks:
        # ── Rule 1: from <module> import <name> ──────────────────────────────
        for match in re.finditer(
            r"^from\s+([\w.]+)\s+import\s+([\w,\t *]+)", code, re.MULTILINE
        ):
            module = match.group(1)
            imported_names = [n.strip() for n in match.group(2).split(",")]

            if any(module.startswith(ext) for ext in EXTERNAL_PREFIXES):
                continue

            py_file = _module_path_to_file(module)
            if py_file is None:
                violations.append(
                    f"{md_path.name}:{block_line}: module `{module}` not found in repo"
                )
                continue

            defined = _top_level_names(py_file)
            for name in imported_names:
                name = name.strip()
                if not name or name == "*" or name in SKIP_NAMES:
                    continue
                if name not in defined:
                    violations.append(
                        f"{md_path.name}:{block_line}: `{name}` not found in "
                        f"`{module}` ({py_file.relative_to(REPO_ROOT)})"
                    )

        # ── Rule 2: ClassName( instantiation ─────────────────────────────────
        for match in re.finditer(r"\b([A-Z][A-Za-z0-9]+)\s*\(", code):
            name = match.group(1)
            if name in SKIP_NAMES:
                continue
            # Only check names that look like project classes (PascalCase, 4+ chars)
            if len(name) < 4:
                continue
            if not _repo_defines_name(name):
                violations.append(
                    f"{md_path.name}:{block_line}: class/function `{name}` is "
                    f"referenced in documentation but not defined in the codebase"
                )

    return violations


def main() -> int:
    all_violations: list[str] = []

    for doc_path in DOCS_TO_SCAN:
        if not doc_path.exists():
            print(f"[gate-f] SKIP  {doc_path.name} (file not found)")
            continue
        violations = check_doc(doc_path)
        all_violations.extend(violations)

    if all_violations:
        print("[gate-f] FAIL — documentation/code consistency violations:\n")
        for v in all_violations:
            print(f"  ✗ {v}")
        print(
            f"\n  {len(all_violations)} violation(s). "
            "Update the documentation snippet to match the actual API."
        )
        return 1

    print(f"[gate-f] PASS — checked {len(DOCS_TO_SCAN)} docs, no violations")
    return 0


if __name__ == "__main__":
    sys.exit(main())
