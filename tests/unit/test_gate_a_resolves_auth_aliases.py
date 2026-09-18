"""Gate A must resolve a shared auth dependency alias, and must not trust its name.

A router may share one alias across its endpoints:

    def _admin(user: TokenPayload = Depends(require_role("admin"))) -> TokenPayload: ...

    @router.post("/x")
    async def x(user: TokenPayload = Depends(_admin)): ...

FastAPI resolves the nested dependency, so the route *is* protected. Gate A
originally matched on a fixed list of alias names, so it reported 22 genuinely
authenticated endpoints in api/safe_agent_platform.py and
api/professional_control_plane.py as missing auth.

The tempting fix — adding "_admin" to AUTH_DEPENDS_MARKERS — would make the
gate trust a spelling it never checks, so `def _admin(): return None` would
pass. These tests pin the stronger behaviour: the alias is resolved to its
definition and only counts when that definition carries real auth.
"""

import ast
import textwrap

from scripts.ci.gate_a_auth_coverage import _has_auth_depends, _verified_auth_aliases


def _analyse(source: str) -> tuple[frozenset[str], list[ast.AST]]:
    tree = ast.parse(textwrap.dedent(source))
    aliases = frozenset(_verified_auth_aliases(tree))
    routes = [
        n
        for n in ast.walk(tree)
        if isinstance(n, ast.FunctionDef | ast.AsyncFunctionDef) and n.name.startswith("route_")
    ]
    return aliases, routes


def test_a_real_alias_is_resolved_and_accepted() -> None:
    aliases, (route,) = _analyse(
        """
        def _admin(user: TokenPayload = Depends(require_role("admin"))) -> TokenPayload:
            return user

        @router.post("/x")
        async def route_ok(user: TokenPayload = Depends(_admin)) -> dict:
            return {}
        """
    )
    assert "_admin" in aliases
    assert _has_auth_depends(route, aliases)


def test_a_fake_alias_is_still_a_violation() -> None:
    """The whole point: the alias is verified, not trusted by name."""
    aliases, (route,) = _analyse(
        """
        def _admin():
            return None

        @router.post("/x")
        async def route_fake(user = Depends(_admin)) -> dict:
            return {}
        """
    )
    assert "_admin" not in aliases, "an alias that enforces nothing must not be trusted"
    assert not _has_auth_depends(route, aliases)


def test_an_assigned_alias_is_resolved() -> None:
    """api/superadmin/_shared.py uses `_require_superadmin = require_role("superadmin")`."""
    aliases, (route,) = _analyse(
        """
        _gate = require_role("superadmin")

        @router.post("/x")
        async def route_assigned(user: TokenPayload = Depends(_gate)) -> dict:
            return {}
        """
    )
    assert "_gate" in aliases
    assert _has_auth_depends(route, aliases)


def test_an_unauthenticated_route_is_still_a_violation() -> None:
    aliases, (route,) = _analyse(
        """
        @router.post("/x")
        async def route_naked() -> dict:
            return {}
        """
    )
    assert not _has_auth_depends(route, aliases)
