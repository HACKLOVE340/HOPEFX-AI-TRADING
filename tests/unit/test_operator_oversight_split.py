# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
tests/unit/test_operator_oversight_split.py
============================================
Operators are ordinary traders on the ordinary endpoints.

``_owned_position_ids`` returned ``None`` for ``admin`` and ``superadmin``, and
``None`` meant *apply no filter*, so an operator saw everybody's positions on
``GET /api/trading/positions`` — and their own trades showed up in the shared
book that every other user was reading. That is the behaviour that was reported.

Oversight still exists, but it moved to ``/api/superadmin/trading/*`` where the
account is named in the request and the read is written to the audit log. This
file pins both halves: the ordinary endpoints no longer special-case a role, and
the operator endpoints exist and are superadmin-only.
"""

from __future__ import annotations

import ast
import inspect
import pathlib

import pytest

pytestmark = pytest.mark.unit

_TRADING = pathlib.Path(__file__).resolve().parents[2] / "api" / "trading.py"


class _User:
    def __init__(self, sub: str, role: str):
        self.sub = sub
        self.role = role


# ── The bypass is gone ───────────────────────────────────────────────────────


def test_ownership_no_longer_branches_on_role():
    """The specific line that caused the report was ``if user.role in ("admin",
    "superadmin"): return None``."""
    from api import trading

    src = inspect.getsource(trading._owned_position_ids)
    assert "superadmin" not in src or "return None" not in src, (
        "_owned_position_ids still returns None (meaning 'no filter') for a role"
    )


def test_ownership_never_returns_none():
    """``None`` was the sentinel for 'show everything'. Removing the sentinel
    removes the failure mode: the function can only ever return a set of ids."""
    from api import trading

    tree = ast.parse(inspect.getsource(trading._owned_position_ids))
    returns = [n for n in ast.walk(tree) if isinstance(n, ast.Return)]
    assert returns, "no return statements found — did the function change shape?"
    for node in returns:
        assert not (isinstance(node.value, ast.Constant) and node.value.value is None), (
            f"line {node.lineno} still returns None, the 'show the whole book' sentinel"
        )


@pytest.mark.parametrize("role", ["trader", "admin", "superadmin"])
def test_no_role_is_exempt_from_ownership(role, monkeypatch):
    """With no database, ownership cannot be established, so every role — not
    just ordinary users — gets an empty book rather than the shared one."""
    from api import trading

    monkeypatch.setattr(trading, "app_state", None)
    assert trading._owned_position_ids(_User("u-1", role)) == set()


def test_no_trading_handler_branches_on_an_operator_role():
    """Checked on the parsed code, not the text.

    A first version of this grepped the source for "superadmin" and failed on
    the docstring that explains the fix — measuring the prose instead of the
    behaviour. What matters is whether any executable comparison in
    ``api/trading.py`` tests a role against "admin" or "superadmin"; comments
    and docstrings are not code.
    """
    tree = ast.parse(_TRADING.read_text(encoding="utf-8"))
    offenders: list[str] = []

    # The subscription gate exempts operators from *billing*, which has nothing
    # to do with whose positions anybody can see. Excluded by name rather than
    # by loosening the rule.
    billing_gate = next(
        (
            n
            for n in ast.walk(tree)
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == "_check_subscription_gate"
        ),
        None,
    )
    exempt_lines: set[int] = set()
    if billing_gate is not None:
        exempt_lines = {n.lineno for n in ast.walk(billing_gate) if hasattr(n, "lineno")}

    for node in ast.walk(tree):
        if not isinstance(node, ast.Compare) or node.lineno in exempt_lines:
            continue
        literals: list[str] = []
        for side in [node.left, *node.comparators]:
            if isinstance(side, ast.Constant) and isinstance(side.value, str):
                literals.append(side.value)
            elif isinstance(side, (ast.Tuple, ast.List, ast.Set)):
                literals += [e.value for e in side.elts if isinstance(e, ast.Constant) and isinstance(e.value, str)]
        if {"admin", "superadmin"} & set(literals):
            offenders.append(f"line {node.lineno}: {ast.unparse(node)}")

    assert not offenders, (
        "api/trading.py still branches on an operator role — whole-book access "
        "belongs on /api/superadmin/trading/*:\n  " + "\n  ".join(offenders)
    )


# ── Oversight exists, and is operator-only ───────────────────────────────────


def test_the_operator_endpoints_exist():
    from api.superadmin.trading_oversight import router

    paths = {r.path for r in router.routes}
    assert paths == {
        "/trading/accounts",
        "/trading/accounts/{account_user_id}",
        "/trading/positions",
    }


def test_every_operator_endpoint_requires_superadmin():
    from api.superadmin.trading_oversight import router

    for route in router.routes:
        deps = str(getattr(route, "dependant", "")) + str(getattr(route, "dependencies", ""))
        source = inspect.getsource(route.endpoint)
        assert "_require_superadmin" in source or "_require_superadmin" in deps, (
            f"{route.path} does not require superadmin"
        )


def test_reading_another_account_is_audited():
    """Looking at someone else's book must be a recorded event, not an
    invisible one — that is most of the justification for the endpoint."""
    import api.superadmin.trading_oversight as oversight

    for name in ("list_accounts", "get_account_detail", "all_positions"):
        src = inspect.getsource(getattr(oversight, name))
        assert "_log_superadmin_action" in src, f"{name} does not write an audit record"


def test_the_detail_route_names_the_account_in_the_path():
    """The account inspected is an explicit argument rather than an implication
    of the caller's role."""
    import api.superadmin.trading_oversight as oversight

    sig = inspect.signature(oversight.get_account_detail)
    assert "account_user_id" in sig.parameters


def test_oversight_is_read_only():
    """Closing someone else's position from an operator seat is a different
    decision with different consequences; it is not smuggled in here."""
    from api.superadmin.trading_oversight import router

    methods = set()
    for route in router.routes:
        methods |= set(getattr(route, "methods", set()))
    assert methods <= {"GET", "HEAD"}, f"oversight exposes mutating methods: {sorted(methods)}"
