# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# AGPL-3.0 — Share all modifications
"""
tests/unit/test_lockdown_actually_locks_down.py
===============================================
The admin lockdown toggle reported success and changed nothing.

Found under the coverage-floor programme, Task 6d, applying
``.claude/skills/threat-modelling`` to the **operator surfaces** trust
boundary.  Stage 1 names the threat plainly:

    An operator sees an attack in progress, hits the lockdown switch, is told
    the platform is locked down, and orders keep flowing.

Stage 3 — *which control stops it, and does that control run?* — is where this
repository has been bitten before, and it is where this was found.

``api/security_dashboard.py`` called three methods on the singleton returned by
``security.lockdown.get_lockdown_manager()``::

    mgr.activate(reason=..., activated_by=user.sub)      # line 252
    mgr.clear(cleared_by=user.sub)                       # lines 236, 294

``LockdownManager`` has neither.  It has ``trigger(reason, triggered_by)`` and
``lift(lifted_by)``, and both are ``async def``.  So every call raised
``AttributeError`` into::

    except Exception as _exc:
        logger.debug("Lockdown manager unavailable (enable path), ...")

— DEBUG, which is off in production — and fell through to a module-level
``_lockdown_state`` dict.  The endpoint then returned
``{"status": "active", "lockdown_active": True}`` to the admin.

Two of this platform's four dead-control shapes, stacked:

  * **#2, success reported for work that did not happen.**  The POST's
    response is a constant, not a reading of what the call achieved.
  * **#4, the evidence swallowed by ``except``.**  An ``AttributeError`` on a
    safety control logged at DEBUG is a silent failure by construction.

The tell was visible from the outside without reading either file, and it is
what ``SecurityDashboard.tsx`` shows an operator: ``GET /lockdown`` reads
``mgr.status()``, which exists and does *not* raise, so the GET reports the
singleton — ``active: False`` — while the POST that just "succeeded" wrote only
to the fallback dict.  Toggle lockdown on, refresh the page, and the badge says
the platform is open.

These tests fail on the pre-fix tree at ``5496d0a8``.
"""

from __future__ import annotations

import ast
import inspect
import logging
import os
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("SECURITY_JWT_SECRET", "test-secret-key-32chars-minimum!!")

from api.auth import TokenPayload, get_current_user, require_role

_REPO_ROOT = Path(__file__).resolve().parents[2]
_ROUTER_SRC = _REPO_ROOT / "api" / "security_dashboard.py"


@pytest.fixture(autouse=True)
def _fresh_singleton():
    """Reset both the manager singleton and the router's fallback dict.

    The manager is a process-wide singleton and the fallback is a module
    global; a test that leaves either set would let the next one pass on
    residue rather than on its own POST.
    """
    import api.security_dashboard as dash
    import security.lockdown as lockdown_mod

    lockdown_mod._lockdown_instance = None
    dash._lockdown_state = {"active": False, "reason": None, "activated_at": None}
    yield
    lockdown_mod._lockdown_instance = None
    dash._lockdown_state = {"active": False, "reason": None, "activated_at": None}


@pytest.fixture
def client() -> TestClient:
    from api.security_dashboard import router

    app = FastAPI()
    admin = TokenPayload(sub="admin-1", role="admin")
    app.dependency_overrides[get_current_user] = lambda: admin
    app.dependency_overrides[require_role("admin")] = lambda: admin
    app.include_router(router)
    return TestClient(app, raise_server_exceptions=False)


class TestTheSwitchMovesTheThingItReportsOn:
    """POST then GET. Nothing more exotic than what the dashboard itself does."""

    def test_activating_the_lockdown_makes_the_status_endpoint_say_so(self, client):
        posted = client.post("/api/security/lockdown", json={"enable": True, "reason": "under attack"})
        assert posted.status_code == 200
        assert posted.json()["lockdown_active"] is True

        # The same question the frontend asks on its next poll.
        got = client.get("/api/security/lockdown")
        assert got.status_code == 200
        assert got.json()["lockdown_active"] is True, (
            "the POST said the platform is locked down and the GET says it is not; one of them is lying to the operator"
        )

    def test_the_manager_singleton_is_the_thing_that_changed(self, client):
        from security.lockdown import get_lockdown_manager

        client.post("/api/security/lockdown", json={"enable": True, "reason": "under attack"})
        assert get_lockdown_manager().is_active is True, "the lockdown lives in a module-level dict nothing else reads"

    def test_the_reason_the_operator_typed_survives_the_round_trip(self, client):
        client.post("/api/security/lockdown", json={"enable": True, "reason": "credential stuffing"})
        assert client.get("/api/security/lockdown").json()["reason"] == "credential stuffing"

    def test_the_operator_who_triggered_it_is_recorded(self, client):
        client.post("/api/security/lockdown", json={"enable": True, "reason": "x"})
        # Repudiation (STRIDE-R): a lockdown nobody is named for cannot be
        # reviewed afterwards.
        assert client.get("/api/security/lockdown").json()["triggered_by"] == "admin-1"


class TestLiftingIt:
    def test_disable_clears_what_enable_set(self, client):
        client.post("/api/security/lockdown", json={"enable": True, "reason": "x"})
        cleared = client.post("/api/security/lockdown", json={"enable": False})
        assert cleared.status_code == 200
        assert cleared.json()["lockdown_active"] is False
        assert client.get("/api/security/lockdown").json()["lockdown_active"] is False

    def test_the_dedicated_clear_endpoint_clears_it_too(self, client):
        from security.lockdown import get_lockdown_manager

        client.post("/api/security/lockdown", json={"enable": True, "reason": "x"})
        assert get_lockdown_manager().is_active is True

        resp = client.post("/api/security/lockdown/clear")
        assert resp.status_code == 200
        assert get_lockdown_manager().is_active is False
        assert client.get("/api/security/lockdown").json()["lockdown_active"] is False

    def test_clearing_a_lockdown_that_was_never_set_is_not_an_error(self, client):
        assert client.post("/api/security/lockdown/clear").status_code == 200
        assert client.get("/api/security/lockdown").json()["lockdown_active"] is False


class TestTheCallSitesResolve:
    """The general guard, so the next rename is caught by a test and not by an operator.

    A router that calls a method by a name the class does not define is only
    ever one ``except Exception`` away from reporting success; the name itself
    is checkable without running anything.
    """

    @staticmethod
    def _attributes_called_on_the_manager() -> set[str]:
        tree = ast.parse(_ROUTER_SRC.read_text(encoding="utf-8"))
        names: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and node.value.id == "mgr":
                names.add(node.attr)
        return names

    def test_every_name_the_router_reaches_for_exists_on_the_class(self):
        from security.lockdown import LockdownManager

        called = self._attributes_called_on_the_manager()
        assert called, "the AST walk found no manager calls — the fixture has drifted"
        missing = sorted(n for n in called if not hasattr(LockdownManager, n))
        assert missing == [], (
            f"api/security_dashboard.py calls {missing} on LockdownManager, which has no such attribute"
        )

    def test_a_coroutine_method_is_never_called_without_await(self):
        """``mgr.trigger(...)`` without ``await`` returns a coroutine and does nothing.

        Renaming the methods without awaiting them would leave the endpoint
        just as dead, and just as confident — so assert the shape, not only
        the name.
        """
        from security.lockdown import LockdownManager

        tree = ast.parse(_ROUTER_SRC.read_text(encoding="utf-8"))
        unawaited: list[str] = []
        for parent in ast.walk(tree):
            for _field, value in ast.iter_fields(parent):
                items = value if isinstance(value, list) else [value]
                for node in items:
                    if not isinstance(node, ast.Call):
                        continue
                    func = node.func
                    if not (
                        isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name) and func.value.id == "mgr"
                    ):
                        continue
                    method = getattr(LockdownManager, func.attr, None)
                    # A bare ast.Call reached through any field other than
                    # ast.Await.value is not awaited.
                    if method is not None and inspect.iscoroutinefunction(method) and not isinstance(parent, ast.Await):
                        unawaited.append(f"{func.attr}() at line {node.lineno}")
        assert unawaited == [], f"async LockdownManager methods called without await: {unawaited}"


class TestTheFailureIsAudible:
    """Shape #4: a safety control that fails must not do so at DEBUG.

    ``CLAUDE.md`` forbids weakening a risk gate; raising a log level is the
    opposite, and it is what turns the next occurrence of this defect into
    something an operator can see.
    """

    def test_a_manager_that_cannot_activate_is_logged_at_error(self, client, caplog, monkeypatch):
        import security.lockdown as lockdown_mod

        class _Broken(lockdown_mod.LockdownManager):
            async def trigger(self, *a, **kw):  # type: ignore[override]
                raise RuntimeError("redis is down")

        monkeypatch.setattr(lockdown_mod, "_lockdown_instance", _Broken())

        with caplog.at_level(logging.DEBUG, logger="api.security_dashboard"):
            resp = client.post("/api/security/lockdown", json={"enable": True, "reason": "x"})

        assert resp.status_code == 503  # and says so, rather than answering "active"
        records = [r for r in caplog.records if "redis is down" in r.getMessage()]
        assert records, "the failure was not logged at all"
        assert all(r.levelno >= logging.ERROR for r in records), (
            f"a failed lockdown was logged at {[r.levelname for r in records]}"
        )

    def test_a_lockdown_that_did_not_take_is_not_reported_as_active(self, client, monkeypatch):
        """The half that actually protects the operator.

        Logging louder helps whoever reads logs.  Not claiming success is what
        stops the dashboard from showing a lock that is not there — so the
        endpoint refuses with 503 rather than composing a cheerful response out
        of the request it was handed.
        """
        import security.lockdown as lockdown_mod

        class _Broken(lockdown_mod.LockdownManager):
            async def trigger(self, *a, **kw):  # type: ignore[override]
                raise RuntimeError("redis is down")

        monkeypatch.setattr(lockdown_mod, "_lockdown_instance", _Broken())

        resp = client.post("/api/security/lockdown", json={"enable": True, "reason": "x"})
        assert resp.status_code == 503
        assert resp.json().get("lockdown_active") is not True, (
            "the platform is not locked down and the operator was told it is"
        )
        # And the singleton agrees, so the next GET cannot contradict the POST.
        assert lockdown_mod._lockdown_instance.is_active is False


class TestTheDelegationToTheBrain:
    """``trigger()`` forwards to HOPEFXBrain; ``lift()`` does not. Both matter.

    ``security.global_fortress.HOPEFXBrain.trigger_full_lockdown`` is what
    actually stops traffic: it sets ``lockdown:active`` in Redis with a
    3600-second TTL, which ``core/health.py:204`` reads to fail the pod's
    readiness probe.  ``LockdownManager.trigger`` fires it when a brain is
    running.

    ``LockdownManager.lift`` has no matching call.  Clearing the lockdown
    through the admin API therefore flips the in-process flag and leaves the
    Redis key set until its TTL expires — the pod stays out of the load
    balancer for up to an hour after an operator has declared the incident
    over.  ``global_fortress``'s own ``POST /lockdown/clear`` deletes the key;
    the dashboard's does not reach it.

    Recorded as F274 rather than changed here: the two routers both claim
    ``/api/security/*`` and which one is mounted depends on the
    ``init_security_brain`` flag, so the correct owner of the clear path is a
    decision, not a patch.
    """

    @pytest.fixture
    def brain(self, monkeypatch):
        import security.global_fortress as gf

        class _Brain:
            def __init__(self) -> None:
                self.locked_down_with: list[str] = []

            async def trigger_full_lockdown(self, ip: str) -> None:
                self.locked_down_with.append(ip)

        stub = _Brain()
        monkeypatch.setattr(gf, "_brain_instance", stub, raising=False)
        return stub

    @pytest.mark.asyncio
    async def test_triggering_reaches_the_brain(self, brain):
        import asyncio

        from security.lockdown import LockdownManager

        await LockdownManager().trigger(reason="credential stuffing", triggered_by="admin-1")
        # ensure_future schedules it; yield once so the task runs.
        await asyncio.sleep(0)
        assert brain.locked_down_with == ["manual:credential stuffing"]

    @pytest.mark.asyncio
    async def test_lifting_does_not_reach_the_brain(self, brain):
        import asyncio

        from security.lockdown import LockdownManager

        mgr = LockdownManager()
        await mgr.trigger(reason="x")
        await asyncio.sleep(0)
        brain.locked_down_with.clear()

        await mgr.lift(lifted_by="admin-1")
        await asyncio.sleep(0)
        assert brain.locked_down_with == [], "unexpected — update F274, the asymmetry is gone"
        assert mgr.is_active is False

    @pytest.mark.asyncio
    async def test_a_brain_that_raises_does_not_stop_the_local_lockdown(self, monkeypatch):
        """Fail-closed on the part it controls.

        The local flag must be set even when the delegation cannot be made;
        refusing to record the lockdown because Redis is unreachable would
        leave the operator with neither.
        """
        import security.global_fortress as gf

        class _Exploding:
            async def trigger_full_lockdown(self, ip: str) -> None:
                raise RuntimeError("redis down")

        monkeypatch.setattr(gf, "_brain_instance", _Exploding(), raising=False)

        from security.lockdown import LockdownManager

        mgr = LockdownManager()
        state = await mgr.trigger(reason="x", triggered_by="admin-1")
        assert state["active"] is True
        assert mgr.is_active is True

    @pytest.mark.asyncio
    async def test_no_brain_at_all_is_not_an_error(self, monkeypatch):
        import security.global_fortress as gf

        monkeypatch.setattr(gf, "_brain_instance", None, raising=False)

        from security.lockdown import LockdownManager

        mgr = LockdownManager()
        assert (await mgr.trigger(reason="x"))["active"] is True


class TestTheStatusDict:
    @pytest.mark.asyncio
    async def test_a_fresh_manager_reports_inactive_with_no_timestamp(self):
        from security.lockdown import LockdownManager

        assert LockdownManager().status() == {
            "active": False,
            "reason": "",
            "triggered_at": None,
            "triggered_by": "system",
        }

    @pytest.mark.asyncio
    async def test_the_timestamp_is_timezone_aware_iso8601(self):
        from datetime import datetime

        from security.lockdown import LockdownManager

        mgr = LockdownManager()
        stamped = (await mgr.trigger(reason="x"))["triggered_at"]
        assert datetime.fromisoformat(stamped).tzinfo is not None

    @pytest.mark.asyncio
    async def test_lifting_keeps_the_reason_so_the_incident_is_still_readable(self):
        """Deliberate, and asserted so a later "tidy-up" has to argue with it.

        ``lift()`` clears ``_active`` only.  The reason and the actor survive,
        which is what lets a post-incident reviewer see what the lockdown was
        for after it has been cleared.
        """
        from security.lockdown import LockdownManager

        mgr = LockdownManager()
        await mgr.trigger(reason="credential stuffing", triggered_by="admin-1")
        state = await mgr.lift(lifted_by="admin-2")
        assert state["active"] is False
        assert state["reason"] == "credential stuffing"
        assert state["triggered_by"] == "admin-1"
