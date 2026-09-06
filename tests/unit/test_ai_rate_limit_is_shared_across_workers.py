# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""The AI platform's rate limit counted per process, in a second mechanism.

`api/safe_agent_platform.py` kept `_REQUEST_WINDOW` and `_BUDGET_WINDOW` as
module dicts. With `API_WORKERS>1` each worker enforced its own full allowance,
so the configured 20/minute was 20 per worker — and it reset on every restart.
`ai/gateway/budget_store.py` records the identical lesson for the spend ceiling:
the number in the settings form quietly stops meaning what it says.

It is also a SECOND limiter. `rate_limiting/advanced.py` already implements a
Redis-backed sliding window with an in-process fallback, a loop-rebinding fix
and a re-probe cooldown — all of which this module's dict does not have and
would have had to grow. Two mechanisms for one job is two places for the same
bug, and only one of them gets the next fix.

## The trap this file mostly exists for

Making `_enforce_rate_limit` async means every call site needs `await`. A
missed one creates a coroutine, never runs it, and the limit silently stops
existing — a control that is called, reads correctly, and does nothing. Python
emits a RuntimeWarning nobody reads in production. So the last test here walks
the module's AST and checks every single call site, rather than trusting six
edits to have been made.

These tests fail on the pre-fix tree.
"""

from __future__ import annotations

import ast
import inspect
import pathlib
import uuid

import pytest

pytestmark = pytest.mark.unit


class _Token:
    def __init__(self, sub: str) -> None:
        self.sub = sub
        self.role = "admin"


def _fresh(label: str) -> _Token:
    """A subject no other test — or earlier run of this one — has spent.

    The limiter is genuinely shared: conftest points tests at a live Redis, and
    a sliding window there outlives the process that filled it. Reusing a fixed
    operator id made this file collide with its own previous run, which is the
    same class of shared-state coupling the change under test exists to create.
    That it can collide at all is the evidence the window is not per-process.
    """
    return _Token(f"{label}-{uuid.uuid4()}")


@pytest.fixture(autouse=True)
def _clean():
    import rate_limiting.advanced as rl

    rl._fallback_limiter._windows.clear()
    yield
    rl._fallback_limiter._windows.clear()


# ── it uses the shared limiter, not a private dict ────────────────────────────


def test_the_shared_limiter_exposes_a_public_entry_point():
    """`_redis_is_allowed` is the real Redis-or-fallback path, and its name says
    private. A second module reaching for it is how a private helper becomes an
    interface nobody may change."""
    import rate_limiting.advanced as rl

    assert hasattr(rl, "is_allowed"), "no public entry point on the shared limiter"


def test_the_ai_platform_no_longer_keeps_its_own_window():
    import api.safe_agent_platform as sp

    src = pathlib.Path(inspect.getfile(sp)).read_text(encoding="utf-8")
    assert "_REQUEST_WINDOW" not in src, "the per-process request window is still there"
    assert "_BUDGET_WINDOW" not in src, "the per-process research window is still there"


def test_the_ai_platform_uses_the_shared_limiter():
    import api.safe_agent_platform as sp

    src = pathlib.Path(inspect.getfile(sp)).read_text(encoding="utf-8")
    assert "rate_limiting" in src, "the AI platform is not using the shared limiter"


# ── it still limits ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_the_limit_still_binds():
    """The point of the change is not to lose the limit while relocating it."""
    from fastapi import HTTPException

    import api.safe_agent_platform as sp

    user = _fresh("req")
    for _ in range(sp._MAX_REQUESTS_PER_MINUTE):
        await sp._enforce_rate_limit(user)

    with pytest.raises(HTTPException) as exc:
        await sp._enforce_rate_limit(user)
    assert exc.value.status_code == 429


@pytest.mark.asyncio
async def test_one_operator_hitting_the_limit_does_not_block_another():
    import api.safe_agent_platform as sp

    a, b = _fresh("req-a"), _fresh("req-b")
    for _ in range(sp._MAX_REQUESTS_PER_MINUTE):
        await sp._enforce_rate_limit(a)

    await sp._enforce_rate_limit(b)  # must not raise


@pytest.mark.asyncio
async def test_the_research_budget_still_binds():
    from fastapi import HTTPException

    import api.safe_agent_platform as sp

    user = _fresh("research")
    for _ in range(sp._MAX_RESEARCH_UNITS_PER_HOUR):
        await sp._consume_research_budget(user)

    with pytest.raises(HTTPException):
        await sp._consume_research_budget(user)


@pytest.mark.asyncio
async def test_the_two_limits_do_not_share_a_counter():
    """A request limit consumed by research calls would refuse ordinary work
    for a reason nobody could see."""
    import api.safe_agent_platform as sp

    user = _fresh("mixed")
    for _ in range(sp._MAX_REQUESTS_PER_MINUTE):
        await sp._enforce_rate_limit(user)

    await sp._consume_research_budget(user)  # must not raise


# ── the trap: an unawaited limiter is no limiter ──────────────────────────────


def test_every_call_site_awaits_the_limiter():
    """A missed `await` creates a coroutine, never runs it, and the limit
    silently stops existing. Six edits are six chances to miss one, so this
    walks the AST rather than trusting them."""
    import api.safe_agent_platform as sp

    tree = ast.parse(pathlib.Path(inspect.getfile(sp)).read_text(encoding="utf-8"))
    guarded = {"_enforce_rate_limit", "_consume_research_budget"}

    awaited: list[int] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Await) and isinstance(node.value, ast.Call):
            fn = node.value.func
            if isinstance(fn, ast.Name) and fn.id in guarded:
                awaited.append(node.lineno)

    bare: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id in guarded
            and node.lineno not in awaited
        ):
            bare.append((node.lineno, node.func.id))

    assert not bare, f"call sites that create a coroutine and never run it: {bare}"
    assert awaited, "no call site calls the limiter at all"
