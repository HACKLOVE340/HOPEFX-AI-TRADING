# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
tests/unit/test_no_shared_broker_in_handlers.py
================================================
A request handler must never read the shared process-wide broker.

``_broker_call`` operates on ``app_state.broker`` — the deployment's own
account, the one the autonomous engine trades. ``_user_broker_call`` resolves
the *caller's* account through ``core.account_registry``. They look almost
identical at a call site, and the difference is whose money is being read or
moved.

This is exactly how the original leak happened: the filter was added to some
endpoints and not others, and nothing noticed the ones that were missed. A
reviewer will not reliably catch a single ``_broker_call(`` inside a new
handler. This test will.

It is a source-level check on purpose. The alternative — asserting behaviour per
endpoint — needs a fixture per route and silently covers nothing when someone
adds route number 41.
"""

from __future__ import annotations

import ast
import pathlib

import pytest

pytestmark = pytest.mark.unit

_TRADING = pathlib.Path(__file__).resolve().parents[2] / "api" / "trading.py"

# Functions permitted to touch the shared broker, with the reason each is
# allowed. Anything else using it is a cross-user read waiting to be reported.
_ALLOWED = {
    # The wrapper itself, and the shared-broker accessor it documents.
    "_broker_call",
    "_call_on",
    "_user_broker_call",
    "_resolve_account",
}


def _module() -> ast.Module:
    return ast.parse(_TRADING.read_text(encoding="utf-8"))


def _enclosing_functions(tree: ast.Module) -> list[tuple[str, ast.AST]]:
    out: list[tuple[str, ast.AST]] = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            out.append((node.name, node))
    return out


def test_no_handler_calls_the_shared_broker():
    tree = _module()
    offenders: list[str] = []

    for name, func in _enclosing_functions(tree):
        if name in _ALLOWED:
            continue
        for node in ast.walk(func):
            if not isinstance(node, ast.Call):
                continue
            target = node.func
            if isinstance(target, ast.Name) and target.id == "_broker_call":
                offenders.append(f"{name}() at line {node.lineno}")

    assert not offenders, (
        "these functions call _broker_call, which reads the shared "
        "process-wide account rather than the caller's own:\n  "
        + "\n  ".join(offenders)
        + "\nUse _user_broker_call(user.sub, ...) — see core/account_registry.py "
        "and backlog T-01."
    )


def test_no_handler_reaches_into_app_state_broker_directly():
    """``app_state.broker`` bypasses the registry just as effectively as
    ``_broker_call`` does. Readiness checks (``if not app_state.broker``) are
    fine — those ask whether the engine booted, not whose positions these are —
    so only attribute *access followed by a call* is flagged."""
    tree = _module()
    offenders: list[str] = []

    for name, func in _enclosing_functions(tree):
        if name in _ALLOWED:
            continue
        for node in ast.walk(func):
            # app_state.broker.<method>(...)
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and isinstance(node.func.value, ast.Attribute)
                and node.func.value.attr == "broker"
                and isinstance(node.func.value.value, ast.Name)
                and node.func.value.value.id == "app_state"
            ):
                offenders.append(f"{name}() calls app_state.broker.{node.func.attr}() at line {node.lineno}")

    assert not offenders, "these functions call methods on the shared broker directly:\n  " + "\n  ".join(offenders)


def test_the_two_helpers_are_actually_different():
    """A regression guard on the guard: if someone 'simplifies'
    _user_broker_call into _broker_call the tests above keep passing while every
    user is back on one account."""
    source = _TRADING.read_text(encoding="utf-8")
    assert "get_account_registry" in source, "api/trading.py no longer resolves per-user accounts at all"
    assert "async def _user_broker_call" in source


def test_every_user_broker_call_passes_an_identity():
    """``_user_broker_call(method, ...)`` with the method name in the user slot
    would resolve an account named 'get_positions' — a silent, shared fallback.
    The first argument must look like a user reference, not a broker method."""
    tree = _module()
    bad: list[str] = []

    for name, func in _enclosing_functions(tree):
        for node in ast.walk(func):
            if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)):
                continue
            if node.func.id != "_user_broker_call" or not node.args:
                continue
            first = node.args[0]
            if isinstance(first, ast.Constant) and isinstance(first.value, str):
                bad.append(f"{name}() line {node.lineno}: first arg is the literal {first.value!r}")

    assert not bad, "the user identity argument looks wrong:\n  " + "\n  ".join(bad)
