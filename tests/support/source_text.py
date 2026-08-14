# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
tests/support/source_text.py
============================
Read a source file with its prose removed, for tests that assert on code.

Why this exists
---------------
Tests in this repository routinely pin a fix by asserting that some string is
present in — or absent from — a module's source. That works right up until the
module *documents the defect it fixes*, which the convention here encourages.
Then the explanation contains the very string the test is checking for, and the
assertion passes or fails for the wrong reason.

It has happened four times:

* ``test_bootstrap_prod_seeds_a_usable_account.py`` — an assertion that
  ``filter_by(id=...)`` was gone matched the comment explaining why it was gone.
* ``test_pre_commit_healer_docstrings.py`` — the placeholder scan matched its
  own description of a placeholder.
* ``test_audit_trail_returns_its_fields.py`` — a check that the 'Resource ID'
  column was deleted matched the JSX comment saying it was deleted.
* ``test_redis_probes_agree_or_say_why.py`` — a check that the misleading
  "check REDIS_URL" message was gone matched the comment quoting it.

Each time the fix was a private helper in that one file, so the next test file
started from scratch and made the mistake again. Hence a shared one.

Usage
-----
    from tests.support.source_text import code_only

    assert "check REDIS_URL" not in code_only(module_or_path)
"""

from __future__ import annotations

import ast
import io
import pathlib
import re
import tokenize
from types import ModuleType

__all__ = ["code_only", "python_code_only", "tsx_code_only"]


def _resolve(target: str | pathlib.Path | ModuleType) -> pathlib.Path:
    if isinstance(target, ModuleType):
        file = getattr(target, "__file__", None)
        if not file:
            raise ValueError(f"{target!r} has no __file__")
        return pathlib.Path(file)
    return pathlib.Path(target)


def python_code_only(target: str | pathlib.Path | ModuleType) -> str:
    """Python source with every docstring and comment blanked out.

    Prose is **redacted in place**, not deleted, so the surviving code keeps its
    exact original spacing. That matters: an earlier version of this helper
    re-joined tokens with spaces, which turned ``{"client": "async"}`` into
    ``{ "client" : "async" }`` and broke every substring assertion it was meant
    to serve.

    Docstrings are located by AST rather than by pattern, so a triple-quoted
    *value* assigned to a variable survives — it is code, not prose.
    """
    path = _resolve(target)
    src = path.read_text(encoding="utf-8")
    tree = ast.parse(src)

    doc_lines: set[int] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef):
            continue
        body = getattr(node, "body", None)
        if not body:
            continue
        first = body[0]
        if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant) and isinstance(first.value.value, str):
            doc_lines.update(range(first.lineno, (first.end_lineno or first.lineno) + 1))

    lines = src.splitlines(keepends=True)

    # Blank comment text where it sits, keeping the line's leading code.
    for tok in tokenize.generate_tokens(io.StringIO(src).readline):
        if tok.type != tokenize.COMMENT:
            continue
        row, col = tok.start
        line = lines[row - 1]
        lines[row - 1] = line[:col] + "\n" if line.endswith("\n") else line[:col]

    for row in doc_lines:
        if 1 <= row <= len(lines):
            lines[row - 1] = "\n" if lines[row - 1].endswith("\n") else ""

    return "".join(lines)


def tsx_code_only(target: str | pathlib.Path) -> str:
    """TypeScript/TSX source with JSX, block and line comments removed."""
    src = _resolve(target).read_text(encoding="utf-8")
    src = re.sub(r"\{/\*.*?\*/\}", "", src, flags=re.S)  # {/* JSX comment */}
    src = re.sub(r"/\*.*?\*/", "", src, flags=re.S)  # /* block */ and /** jsdoc */
    src = re.sub(r"^[ \t]*//.*$", "", src, flags=re.M)  # // line
    return src


def code_only(target: str | pathlib.Path | ModuleType) -> str:
    """Dispatch on file extension. Modules are always Python."""
    if isinstance(target, ModuleType):
        return python_code_only(target)
    path = pathlib.Path(target)
    if path.suffix in (".ts", ".tsx", ".js", ".jsx"):
        return tsx_code_only(path)
    return python_code_only(path)
