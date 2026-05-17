#!/usr/bin/env python3
# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# AGPL-3.0 — Share all modifications
"""
scripts/pre_commit_healer.py
============================
Pre-commit hook: static integrity check on staged Python files.

Detects production code quality issues that the self-healer would flag:
  1. Bare `pass` in non-trivial function/method bodies (not in except/abstract)
  2. TODO / FIXME / HACK / XXX markers in production paths
  3. raise NotImplementedError in non-abstract methods
  4. Hardcoded placeholder values (CHANGE_ME, your_api_key, etc.)  # healer: ignore
  5. Mock/stub class definitions outside test files

Exit codes
----------
0 — all checks passed
1 — one or more issues found (commit blocked)

Usage (called by pre-commit framework)
---------------------------------------
    python scripts/pre_commit_healer.py file1.py file2.py ...
"""

from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

# ── Patterns ──────────────────────────────────────────────────────────────────

_TODO_RE = re.compile(r"#\s*(TODO|FIXME|HACK|XXX)\b", re.IGNORECASE)
_PLACEHOLDER_RE = re.compile(
    # Match hardcoded placeholder values in string literals and assignments.
    # Deliberately narrow to avoid false positives in docstrings/comments:
    # - CHANGE_ME / CHANGEME: explicit sentinel values
    # - your_api_key / your_secret: common credential placeholders
    # - <YOUR_*>: angle-bracket template tokens
    # - INSERT_HERE: explicit insertion marker
    # NOT matched: PLACEHOLDER, PENDING (too common in legitimate prose)
    r"(CHANGE_ME|CHANGEME|your_api_key|your_secret|<YOUR_[A-Z_]+>|INSERT_HERE)",  # healer: ignore
    re.IGNORECASE,
)
_MOCK_CLASS_RE = re.compile(r"^class\s+(Mock|Fake|Stub|Dummy)\w*\s*[:(]", re.MULTILINE)

# Abstract method decorators — pass is valid here
_ABSTRACT_DECORATORS = frozenset({"abstractmethod", "abc.abstractmethod"})


def _is_test_file(path: Path) -> bool:
    parts = path.parts
    return (
        any(p in ("tests", "test_unit", "test_integration", "examples") for p in parts)
        or path.name.startswith("test_")
        or path.name.endswith("_test.py")
    )


def _has_abstract_decorator(func_node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    for dec in func_node.decorator_list:
        if isinstance(dec, ast.Name) and dec.id in _ABSTRACT_DECORATORS:
            return True
        if isinstance(dec, ast.Attribute) and dec.attr in _ABSTRACT_DECORATORS:
            return True
    return False


def _body_is_only_pass(body: list[ast.stmt]) -> bool:
    """Return True when the function body is only `pass` (possibly with a docstring)."""
    non_doc = [
        s
        for s in body
        if not (isinstance(s, ast.Expr) and isinstance(s.value, ast.Constant) and isinstance(s.value.value, str))
    ]
    return len(non_doc) == 1 and isinstance(non_doc[0], ast.Pass)


def check_file(path: Path) -> list[str]:
    """Return a list of issue strings for the given file."""
    issues: list[str] = []
    is_test = _is_test_file(path)

    try:
        source = path.read_text(encoding="utf-8")
    except Exception as exc:
        return [f"{path}: could not read file: {exc}"]

    lines = source.splitlines()

    # ── Line-level checks ─────────────────────────────────────────────────────
    for lineno, line in enumerate(lines, 1):
        # Allow per-line suppression via healer: ignore or noqa:healer tag
        if "# noqa: healer" in line or "# healer: ignore" in line:
            continue

        # TODO/FIXME/HACK/XXX in production code  # healer: ignore
        if not is_test and _TODO_RE.search(line):
            issues.append(f"{path}:{lineno}: TODO/FIXME marker in production code: {line.strip()!r}")

        # Hardcoded placeholders — skip lines that are:
        # - inside comments explaining what to change (pragma allowlist)
        # - part of placeholder-detection code (checking for CHANGE_ME values)
        # - example/documentation strings (contain 'example', 'sample', 'doc')
        if _PLACEHOLDER_RE.search(line):
            stripped = line.strip()
            # Skip if this is a comment or docstring explaining the placeholder
            if stripped.startswith("#") or stripped.startswith('"""') or stripped.startswith("'''"):
                continue
            # Skip if the line is checking FOR placeholder values (detection code)
            if "in self._PLACEHOLDER_VALUES" in line or "startswith" in line or "PLACEHOLDER_VALUES" in line:
                continue
            # Skip pragma allowlist lines
            if "pragma: allowlist" in line or "nosec" in line:
                continue
            issues.append(f"{path}:{lineno}: hardcoded placeholder value: {stripped!r}")

    # ── Mock class definitions outside test files ─────────────────────────────
    if not is_test and _MOCK_CLASS_RE.search(source):
        for m in _MOCK_CLASS_RE.finditer(source):
            lineno = source[: m.start()].count("\n") + 1
            matched_line = lines[lineno - 1] if lineno <= len(lines) else ""
            if "# healer: ignore" in matched_line or "# noqa: healer" in matched_line:
                continue
            issues.append(
                f"{path}:{lineno}: mock/stub class definition in production code: {m.group().strip()!r}. "
                "Add a production guard (assert_not_production) or move to tests/."
            )

    # ── AST-level checks ──────────────────────────────────────────────────────
    try:
        tree = ast.parse(source, filename=str(path))
    except SyntaxError as exc:
        issues.append(f"{path}: syntax error: {exc}")
        return issues

    # Null-object / graceful-degradation class names whose methods are
    # intentionally no-ops (optional dependency stubs for prometheus, OTel,
    # torch, CUDA, etc.).  Methods in these classes are exempt from the
    # bare-pass check.
    _NULL_CLASS_NAMES = frozenset(
        {
            "_Noop",
            "_Stub",
            "_NullCtx",
            "_NullSpanCtx",
            "_FakeModule",
            "_NullTxn",
            "_NoopTxn",
            "_C",
            # OTel no-op span/tracer (including inner _Span classes)
            "_NoOpSpan",
            "_NoOpTracer",
            "_NoopSpan",
            "_NoopTracer",
            "_Span",
            # Prometheus no-op histogram/counter/gauge/metric
            "_NoOpHistogram",
            "_NoOpCounter",
            "_NoOpGauge",
            "_NoopCounter",
            "_NoopMetric",
            "_NoopGauge",
            "_NoopHistogram",
            # Generic null-object patterns
            "_NullBroker",
            "_NullCache",
            "_NullDB",
        }
    )

    # Build a mapping: function node → enclosing class name (if any)
    _func_to_class: dict[int, str | None] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            for item in ast.walk(node):
                if isinstance(item, ast.FunctionDef | ast.AsyncFunctionDef) and item is not node:
                    _func_to_class[id(item)] = node.name

    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            continue

        # Skip abstract methods — pass is valid there
        if _has_abstract_decorator(node):
            continue

        # Skip dunder methods where pass is conventional
        if node.name in ("__init_subclass__", "__class_getitem__"):
            continue

        # Skip no-op context manager / gym interface methods
        if node.name in ("__enter__", "__exit__", "render", "set_attribute", "add_event"):
            continue

        # Skip methods inside null-object / graceful-degradation stub classes
        enclosing_class = _func_to_class.get(id(node))
        if enclosing_class in _NULL_CLASS_NAMES:
            continue

        # Bare pass body in non-test, non-abstract function
        if not is_test and _body_is_only_pass(node.body):
            issues.append(
                f"{path}:{node.lineno}: bare `pass` body in {node.name}() — "
                "implement the function or raise NotImplementedError with a clear message."
            )

        # raise NotImplementedError in non-abstract, non-test functions
        if not is_test:
            for child in ast.walk(ast.Module(body=node.body, type_ignores=[])):
                if isinstance(child, ast.Raise):
                    exc_node = child.exc
                    if exc_node is None:
                        continue
                    name = None
                    if isinstance(exc_node, ast.Name):
                        name = exc_node.id
                    elif isinstance(exc_node, ast.Call) and isinstance(exc_node.func, ast.Name):
                        name = exc_node.func.id
                    if name == "NotImplementedError":
                        # Allow per-line suppression via healer: ignore
                        raise_line = lines[child.lineno - 1] if child.lineno <= len(lines) else ""
                        if "# healer: ignore" in raise_line or "# noqa: healer" in raise_line:
                            continue
                        issues.append(
                            f"{path}:{child.lineno}: raise NotImplementedError in {node.name}() — "
                            "implement the function fully before committing."
                        )

    return issues


def main(argv: list[str]) -> int:
    if not argv:
        print("pre_commit_healer: no files to check", file=sys.stderr)
        return 0

    all_issues: list[str] = []
    for arg in argv:
        path = Path(arg)
        if path.suffix != ".py":
            continue
        if not path.exists():
            continue
        all_issues.extend(check_file(path))

    if all_issues:
        print("pre_commit_healer: issues found — commit blocked:\n", file=sys.stderr)
        for issue in all_issues:
            print(f"  {issue}", file=sys.stderr)
        print(
            f"\n{len(all_issues)} issue(s) found. Fix them before committing.",
            file=sys.stderr,
        )
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
