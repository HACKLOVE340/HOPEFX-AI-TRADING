# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# AGPL-3.0 — Share all modifications
"""
tests/unit/test_gate_a_markers_really_authenticate.py
======================================================
`scripts/ci/gate_a_auth_coverage.py` decides whether a mutating endpoint is
authenticated by matching the *source text* of its dependency default against
`AUTH_DEPENDS_MARKERS`. It is an AST scan, so it cannot follow indirection: a
name on that list is an **assertion** the gate makes and cannot check.

That is a real risk. If a helper on the list ever stops resolving the caller,
the gate keeps passing every route that uses it — a security gate quietly
turned off, which is worse than not having one. These tests check the claim.

The immediate reason for this file: Gate A had been red for seven endpoints —

    api/brain.py  chat(), brain_complete(), brain_embed(), analyze_market()
    api/chat.py   ai_chat()
    api/voice.py  tts(), stt()

— all of which authenticate through `Depends(ai_quota(feature=...))`. The
routes were fine; the gate's marker list had not learned the helper's name
when the AI quota was introduced. It was tempting to read a red auth gate as
"these routes are unprotected" and bolt a second dependency onto each. Reading
`core/ai_quota.py` shows the opposite, and this file records the reading in a
form that fails if it ever stops being true.
"""

from __future__ import annotations

import ast
import inspect
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_GATE = _REPO_ROOT / "scripts" / "ci" / "gate_a_auth_coverage.py"


@pytest.fixture
def scratch_api_dir(tmp_path_factory):
    """A throwaway `api/` tree the gate will actually scan.

    Deliberately not `tmp_path`: the gate skips any file with a `test_`-prefixed
    component anywhere in its path, and pytest names `tmp_path` after the test
    function — so a fixture directory called `test_..._caught0` made the gate
    scan zero files and report PASSED. The first version of the test below was
    green for that reason, which is the exact failure mode it exists to detect.
    """
    root = tmp_path_factory.mktemp("gatea") / "api"
    root.mkdir(parents=True)
    return root


def _point_gate_at(gate, scratch_api_dir: Path, monkeypatch) -> None:
    """Scan `scratch_api_dir` instead of the repo.

    `REPO_ROOT` moves with `SCAN_DIRS`: the gate renders each violation as
    `path.relative_to(REPO_ROOT)`, which raises for a path outside the repo.
    """
    monkeypatch.setattr(gate, "SCAN_DIRS", [scratch_api_dir])
    monkeypatch.setattr(gate, "REPO_ROOT", scratch_api_dir.parent)


def _gate_module():
    import importlib.util

    spec = importlib.util.spec_from_file_location("gate_a_auth_coverage", _GATE)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


@pytest.mark.unit
class TestAiQuotaReallyResolvesTheCaller:
    """The marker added for `ai_quota` is only sound while this holds."""

    def test_the_dependency_it_returns_depends_on_get_current_user(self):
        from core.ai_quota import ai_quota

        dependency = ai_quota(feature="chat")
        signature = inspect.signature(dependency)

        defaults = [p.default for p in signature.parameters.values()]
        assert defaults, f"{dependency.__name__} takes no dependency parameters — it authenticates nobody"

        resolved = {getattr(getattr(d, "dependency", None), "__name__", "") for d in defaults}
        assert "get_current_user" in resolved, (
            "ai_quota no longer resolves get_current_user, but Gate A still "
            "treats it as proof of authentication. Either restore the "
            "dependency or remove 'ai_quota' from AUTH_DEPENDS_MARKERS — "
            "otherwise every /api/brain, /api/chat and /api/voice mutating "
            "route passes the auth gate without an auth check."
        )

    def test_it_returns_the_authenticated_user(self):
        """Routes bind its result as `user: TokenPayload`, so it must be one."""
        from core.ai_quota import ai_quota

        source = inspect.getsource(ai_quota)
        assert "return user" in source

    def test_the_marker_is_actually_on_the_list(self):
        assert "ai_quota" in _gate_module().AUTH_DEPENDS_MARKERS


@pytest.mark.unit
class TestTheGatePassesAndStillHasTeeth:
    def test_the_gate_passes_on_the_current_tree(self):
        gate = _gate_module()

        assert gate.main() == 0, "Gate A is failing — run scripts/ci/gate_a_auth_coverage.py for the list"

    def test_an_unauthenticated_mutating_route_is_still_caught(self, scratch_api_dir, monkeypatch):
        """Proves the gate is not passing because it stopped looking."""
        gate = _gate_module()

        (scratch_api_dir / "leaky.py").write_text(
            "from fastapi import APIRouter\n"
            "router = APIRouter()\n"
            "@router.post('/danger')\n"
            "async def wire_money(amount: float):\n"
            "    return {'sent': amount}\n",
            encoding="utf-8",
        )
        _point_gate_at(gate, scratch_api_dir, monkeypatch)

        assert gate.main() == 1, "the gate accepted a mutating route with no auth dependency at all"

    def test_an_authenticated_one_passes(self, scratch_api_dir, monkeypatch):
        """The other half of the pair, so the check above cannot pass by always failing."""
        gate = _gate_module()

        (scratch_api_dir / "guarded.py").write_text(
            "from fastapi import APIRouter, Depends\n"
            "from api.auth import require_role\n"
            "router = APIRouter()\n"
            "@router.post('/danger')\n"
            "async def wire_money(amount: float, user=Depends(require_role('admin'))):\n"
            "    return {'sent': amount}\n",
            encoding="utf-8",
        )
        _point_gate_at(gate, scratch_api_dir, monkeypatch)

        assert gate.main() == 0


@pytest.mark.unit
class TestEveryMarkerNamesSomethingReal:
    """A marker that matches nothing is dead weight; one that matches too
    loosely is a hole. Both are worth knowing about."""

    def test_no_marker_is_an_empty_or_trivial_string(self):
        for marker in _gate_module().AUTH_DEPENDS_MARKERS:
            assert isinstance(marker, str) and len(marker) >= 4, (
                f"{marker!r} is short enough to match unrelated source text"
            )

    def test_no_route_currently_relies_on_a_loose_marker(self):
        """`security`, `_auth` and `_Depends` are substrings, not identifiers.

        Any dependency default whose source merely *contains* one of them
        counts as authenticated, so each is a potential free pass. Measured:
        Gate A passes with all three removed, i.e. nothing in the tree needs
        them today. Pinning that means a route that starts relying on one has
        to be looked at by a person rather than waved through.

        They are left in the gate rather than deleted — they were added for
        specific dynamic builders (`api/gateway.py`, `api/signals.py`) that may
        grow mutating routes later — but a failure here is the signal to check
        whether the route is really authenticated before widening anything.
        """
        gate = _gate_module()
        loose = {"security", "_auth", "_Depends"}

        assert loose <= set(gate.AUTH_DEPENDS_MARKERS), (
            "the loose markers changed — re-measure before editing this test"
        )

        gate.AUTH_DEPENDS_MARKERS = frozenset(set(gate.AUTH_DEPENDS_MARKERS) - loose)
        assert gate.main() == 0, (
            "a mutating route now passes Gate A only because of a loose "
            f"substring marker ({sorted(loose)}). Confirm it really "
            "authenticates the caller before leaving it that way."
        )

    def test_the_gate_still_parses_the_repo_it_scans(self):
        """A parse error would make the gate skip files silently."""
        gate = _gate_module()

        for directory in gate.SCAN_DIRS:
            for path in Path(directory).rglob("*.py"):
                ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
