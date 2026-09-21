# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
tests/unit/test_dynamic_strategy_trust_boundary.py
==================================================
`strategies/dynamic_registry._compile_strategy` runs `exec` on caller-supplied
Python (CodeQL alert #24744). That is deliberate — custom strategies are the
product — and it is accepted on the strength of **who can reach the endpoint**,
not on the strength of the restricted namespace.

This file exists to keep those two things from being confused:

1. It **pins the denylist and the hole found in it**. `ASTSafetyValidator`
   is a real filter — it blocks every textbook escape — but it is a denylist,
   and while writing this file a working bypass turned up:
   `type.__dict__['__subclasses__'](object)` passed validation and reached 715
   classes, because `visit_Attribute` never sees a subscript. That is closed
   now. The lesson kept here is that it took ten minutes to find, so nobody
   should relax the auth gate on the strength of the filter.

2. It **pins the auth gates**, which are the real control. If someone drops
   `_require_admin()` from the register endpoint, the exec becomes reachable by
   any authenticated user and this suite fails loudly.

An admin can already halt the engine, move funds through the broker adapters
and rewrite risk limits. Code execution grants nothing further to an account
holding those. A *non-admin* reaching it would be a different matter entirely,
which is exactly what test 2 protects.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

_REPO = Path(__file__).resolve().parents[2]


# ── 1. The namespace is not a sandbox ─────────────────────────────────────────


def test_the_validator_blocks_the_textbook_escapes():
    """It is a real denylist, not decoration — these must stay blocked."""
    from strategies.dynamic_registry import ASTSafetyValidator

    for src in (
        "x = ().__class__.__bases__[0].__subclasses__()",
        "x = object.__subclasses__()",
        "x = (lambda: 0).__globals__",
        "x = ().__class__.__mro__",
        "x = getattr((), '__class__')",
    ):
        validator = ASTSafetyValidator()
        validator.visit(ast.parse(src))
        assert validator.errors, f"validator no longer blocks: {src}"


def test_the_subscript_bypass_stays_closed():
    """A real hole, found while documenting the boundary, and closed.

    `visit_Attribute` only sees `ast.Attribute` nodes, so it caught
    `x.__subclasses__` but not `x.__dict__['__subclasses__']` — a subscript
    whose key is a string constant. That passed validation and reached 715
    classes from inside the restricted namespace.
    """
    from strategies.dynamic_registry import ASTSafetyValidator

    for src in (
        "x = type.__dict__['__subclasses__'](object)",
        "x = f.__dict__['__globals__']",
        "x = c.__dict__['__mro__']",
    ):
        validator = ASTSafetyValidator()
        validator.visit(ast.parse(src))
        assert validator.errors, f"subscript bypass reopened: {src}"


def test_legitimate_indexing_still_passes():
    """The subscript check must not break strategies reading their own config."""
    from strategies.dynamic_registry import ASTSafetyValidator

    for src in (
        "x = params['period']",
        "x = self.config['risk']",
        "class S:\n    def generate_signal(self, d):\n        return sum([1, 2, 3])",
    ):
        validator = ASTSafetyValidator()
        validator.visit(ast.parse(src))
        assert validator.errors == [], f"legitimate code rejected: {src!r} -> {validator.errors}"


def test_a_restricted_builtins_namespace_is_escapable_in_principle():
    """Why the denylist is depth and not a boundary.

    With no AST filter in front of it, a restricted `__builtins__` gives up the
    whole type hierarchy from a bare tuple literal. The validator is what stops
    that here — which is precisely why the validator being a denylist matters,
    and why the auth gate below is the control that is actually relied on.

    Benign: counts what is reachable and does nothing with it.
    """
    namespace = {"__builtins__": {"range": range, "len": len}}

    exec(compile("reached = ().__class__.__bases__[0].__subclasses__()", "<t>", "exec"), namespace)

    assert len(namespace["reached"]) > 50


# ── 2. The gates are the real control ─────────────────────────────────────────


def _route_decorated_function(rel: str, func_name: str) -> ast.AsyncFunctionDef:
    tree = ast.parse((_REPO / rel).read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.AsyncFunctionDef | ast.FunctionDef) and node.name == func_name:
            return node
    raise AssertionError(f"{func_name} not found in {rel}")


def _dependency_calls(func: ast.AST) -> set[str]:
    """Names of functions called inside `Depends(...)` in the signature."""
    names: set[str] = set()
    for default in [*func.args.defaults, *func.args.kw_defaults]:
        if default is None:
            continue
        for node in ast.walk(default):
            if isinstance(node, ast.Call):
                fn = node.func
                if isinstance(fn, ast.Name):
                    names.add(fn.id)
                elif isinstance(fn, ast.Attribute):
                    names.add(fn.attr)
    return names


def test_registering_raw_strategy_source_requires_admin():
    """The single control standing between arbitrary code exec and the internet."""
    func = _route_decorated_function("api/dynamic_strategies.py", "register_strategy")

    deps = _dependency_calls(func)

    assert "_require_admin" in deps, (
        "register_strategy no longer requires admin — arbitrary code execution "
        f"is now reachable by a lower tier. Dependencies found: {sorted(deps)}"
    )


def test_the_nocode_deploy_path_is_plan_gated():
    """It compiles from a vetted template, but still reaches the same exec."""
    func = _route_decorated_function("api/nocode.py", "deploy_template")

    deps = _dependency_calls(func)

    assert "require_plan" in deps, f"deploy_template lost its plan gate. Dependencies found: {sorted(deps)}"


def test_no_other_route_module_calls_the_compiler_directly():
    """`_compile_strategy` must only be reached through the gated entry points."""
    offenders = []
    for path in (_REPO / "api").rglob("*.py"):
        src = path.read_text(encoding="utf-8")
        if "_compile_strategy" in src:
            offenders.append(str(path.relative_to(_REPO)))

    assert offenders == [], f"api modules calling the compiler directly, bypassing register_strategy: {offenders}"


# ── 3. The boundary is written down ───────────────────────────────────────────


def test_the_trust_boundary_is_documented_at_the_exec_site():
    """The next person to read this needs to know the gate is the control."""
    import re

    src = (_REPO / "strategies" / "dynamic_registry.py").read_text(encoding="utf-8")
    # The docstring is line-wrapped, so match on normalised whitespace.
    flat = re.sub(r"\s+", " ", src)

    assert "Trust boundary" in flat
    assert "defence in depth, not a boundary" in flat, "the docstring must not imply this is a sandbox"
    assert "must not be described as a sandbox" in flat
    assert "_require_admin()" in flat, "the docstring must name the actual control"
