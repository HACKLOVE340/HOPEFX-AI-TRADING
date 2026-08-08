# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
tests/unit/test_auth_service_isolation.py
=========================================
Round 3 audit, Slice 6 (docs/HARDENING_BACKLOG.md S6-05).

`auth.router.set_auth_service()` writes a **module global**. Three test files
call it with a mock and none of them restore it:

    tests/unit/test_auth_coverage.py       (2 set, 0 restore)
    tests/integration/test_auth_flow.py    (1 set, 0 restore)
    tests/e2e/test_auth_billing_trading.py (2 set, 0 restore)

`test_auth_coverage.py`'s mock returns ``(True, "Login successful", {...})``
unconditionally. Once its `client` fixture runs, **every later test in the same
process gets an auth service that approves any credentials**. That is how
`tests/integration/test_api_routing.py::test_login_with_invalid_credentials_returns_401`
came to see `200 OK` for a bad password in the full suite while passing on its
own — the single remaining failure of the Round 3 sweep.

The consequence is bigger than one red test: any auth assertion running after
that fixture is exercising a mock that always succeeds, not the real service.
Same family as S12-01 — tests that appear to verify a safety property while
verifying nothing.

`auth/router.py` already had `reset_rate_limit_state()` "to prevent cross-module
state leakage", so the convention existed; the auth service simply had no
counterpart. These tests pin that it does now, and that it is used.
"""

from __future__ import annotations

import ast
import pathlib

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]


def test_the_module_offers_a_way_to_undo_set_auth_service():
    """Without a restore hook, every caller is forced to leak."""
    from auth import router

    assert hasattr(router, "reset_auth_service"), (
        "auth.router has set_auth_service() but no reset_auth_service(); a test "
        "that installs a mock has no supported way to put the real one back "
        "(S6-05)"
    )


def test_reset_restores_the_previous_service():
    from auth import router

    sentinel = object()
    original = router._auth_service
    try:
        router.set_auth_service(sentinel)
        assert router._auth_service is sentinel
        router.reset_auth_service()
        assert router._auth_service is None, "reset did not clear the injected service"
    finally:
        router._auth_service = original


def test_set_auth_service_returns_the_previous_value_for_restoration():
    """Returning the old value lets a caller restore without touching globals."""
    from auth import router

    original = router._auth_service
    try:
        first = object()
        second = object()
        prev = router.set_auth_service(first)
        assert prev is original
        prev2 = router.set_auth_service(second)
        assert prev2 is first, "set_auth_service did not return the value it displaced"
    finally:
        router._auth_service = original


# ── the leak itself ───────────────────────────────────────────────────────────


LEAKY_FILES = (
    "tests/unit/test_auth_coverage.py",
    "tests/integration/test_auth_flow.py",
    "tests/e2e/test_auth_billing_trading.py",
)


@pytest.mark.parametrize("rel_path", LEAKY_FILES)
def test_no_test_file_installs_an_auth_service_without_restoring_it(rel_path: str):
    """A mock auth service must not outlive the test that installed it.

    `test_auth_coverage.py`'s mock approves every login, so leaving it in place
    silently disables authentication for the rest of the run.
    """
    path = REPO_ROOT / rel_path
    if not path.exists():
        pytest.skip(f"{rel_path} not present")

    src = path.read_text(encoding="utf-8")
    if "set_auth_service" not in src:
        pytest.skip(f"{rel_path} no longer installs an auth service")

    tree = ast.parse(src)
    sets = sum(
        1
        for n in ast.walk(tree)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "set_auth_service"
    )
    restores = src.count("reset_auth_service")

    assert restores >= 1, (
        f"{rel_path} calls set_auth_service {sets}x and never calls "
        f"reset_auth_service. The mock outlives the test and every later login "
        f"in the process is answered by it (S6-05)."
    )
