# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""The emergency halt must not report success for a halt that did not happen.

`POST /superadmin/nuclear/halt` is the control of last resort: the thing a
superadmin reaches for when the platform must stop trading NOW. It ended in an
unconditional

    return {"ok": True, "kill_switch_active": True, "reason": reason}

reached by four paths that halted nothing:

1. **No kill switch at all.** `ks = _get_kill_switch()` returns `None` when
   neither `app_state.kill_switch` nor the module singleton resolves. The whole
   activation block is skipped by `if ks is not None:` and the response still
   said the switch was active.

2. **Activation raised.** `ks.activate(reason)` sat in a `try` whose `except`
   logged at ERROR — correctly — and then fell through to the same success.

3. **Cross-pod propagation failed silently.** The Redis write that every other
   pod reads was wrapped in `except Exception: pass`. With Redis down, the
   switch was set on one pod and the rest of the fleet kept trading, while the
   operator was told the halt succeeded. `if rc:` skipped it just as quietly
   when no client existed.

4. **The halt banner never reached anyone.** The WebSocket broadcast was fired
   as `asyncio.create_task(...)` with no reference held. The event loop keeps
   only a weak reference to a task, so CPython may collect it before it runs;
   and the failure path logged at DEBUG, which is off in production.

Four ways to halt nothing and be told it worked. `hopefx-dead-controls` calls
this "success reported for work that did not happen" and names the remedy:
mutate state after the work, from its result, and have the caller report *that*
rather than a constant.

These tests pin the honest contract: the response names what actually happened
on each leg, a halt that could not propagate does not read as a clean success,
and the resume path is held to the same standard — because a resume that only
half-applies leaves pods halted with an operator who believes trading is back.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


@pytest.fixture
def client() -> TestClient:
    from api.auth import TokenPayload
    from api.superadmin import router
    from api.superadmin._shared import require_superadmin_2fa

    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[require_superadmin_2fa] = lambda: TokenPayload(
        sub="test-superadmin", role="superadmin", two_factor_verified=True
    )
    return TestClient(app, raise_server_exceptions=False)


class _Switch:
    """A kill switch that records whether it was actually asked to stop."""

    def __init__(self, *, raises: bool = False) -> None:
        self.activated = False
        self.deactivated = False
        self._raises = raises

    def activate(self, reason: str) -> None:
        if self._raises:
            raise RuntimeError("switch wedged")
        self.activated = True

    def deactivate(self) -> None:
        if self._raises:
            raise RuntimeError("switch wedged")
        self.deactivated = True


class _Redis:
    def __init__(self, *, raises: bool = False) -> None:
        self.written: dict[str, str] = {}
        self._raises = raises

    def set(self, key, value, ex=None):
        if self._raises:
            raise ConnectionError("redis down")
        self.written[key] = value

    def delete(self, *keys):
        if self._raises:
            raise ConnectionError("redis down")
        for k in keys:
            self.written.pop(k, None)


def _halt(client: TestClient, *, switch, redis):
    with (
        patch("api.superadmin.nuclear_controls._get_kill_switch", return_value=switch),
        patch("cache.redis_client.get_sync_redis_client", return_value=redis),
    ):
        return client.post("/api/superadmin/nuclear/halt", json={"reason": "test halt"})


class TestAHaltThatWorkedSaysSo:
    def test_the_switch_is_actually_activated(self, client):
        switch, redis = _Switch(), _Redis()
        resp = _halt(client, switch=switch, redis=redis)

        assert resp.status_code == 200, resp.text
        assert switch.activated is True, "the endpoint returned without stopping anything"
        body = resp.json()
        assert body["ok"] is True
        assert body["kill_switch_active"] is True

    def test_it_propagates_to_the_other_pods(self, client):
        switch, redis = _Switch(), _Redis()
        _halt(client, switch=switch, redis=redis)
        assert redis.written.get("kill_switch:active") == "1", "without this key every other pod keeps trading"

    def test_the_response_says_what_each_leg_did(self, client):
        """An operator at 3am needs to know which parts took effect."""
        resp = _halt(client, switch=_Switch(), redis=_Redis())
        body = resp.json()
        assert "local" in body or "legs" in body, f"the response does not report per-leg outcomes: {sorted(body)}"


class TestAHaltThatDidNotHappenDoesNotReportSuccess:
    def test_no_kill_switch_is_not_a_successful_halt(self, client):
        """`ks is None` skipped the whole activation block and still said active."""
        resp = _halt(client, switch=None, redis=_Redis())
        body = resp.json()
        assert not (resp.status_code == 200 and body.get("ok") is True and body.get("kill_switch_active") is True), (
            "the endpoint reported an active kill switch with no kill switch to activate"
        )

    def test_an_activation_failure_is_not_a_successful_halt(self, client):
        resp = _halt(client, switch=_Switch(raises=True), redis=_Redis())
        body = resp.json()
        assert not (body.get("ok") is True and body.get("kill_switch_active") is True), (
            "activation raised and the endpoint still reported the switch active"
        )

    def test_a_failed_cross_pod_write_is_visible(self, client):
        """Redis down: this pod halted, the rest of the fleet did not.

        The most dangerous of the four, because the local halt genuinely
        worked — so nothing looks wrong until another pod fills an order.
        """
        switch = _Switch()
        resp = _halt(client, switch=switch, redis=_Redis(raises=True))

        assert switch.activated is True, "the local halt should still have happened"
        body = resp.json()
        text = resp.text.lower()
        assert body.get("ok") is not True or "propagat" in text or "pod" in text, (
            "a halt that reached only this pod reported a clean success: " + resp.text[:300]
        )

    def test_no_redis_client_is_reported_not_skipped(self, client):
        switch = _Switch()
        resp = _halt(client, switch=switch, redis=None)
        assert switch.activated is True
        assert resp.json().get("ok") is not True or "propagat" in resp.text.lower()


class TestTheBroadcastCannotBeCollected:
    def test_the_halt_banner_task_is_referenced(self):
        """An unreferenced task may be garbage-collected before it sends.

        The event loop holds only a weak reference to a task. Firing the halt
        broadcast as a bare `asyncio.create_task(...)` means CPython is free to
        collect it mid-flight, and the operator's banner never appears.
        """
        import api.superadmin.nuclear_controls as nc

        assert hasattr(nc, "_BACKGROUND_TASKS"), "the module must hold a strong reference to in-flight broadcast tasks"

    def test_a_broadcast_failure_is_not_logged_at_debug(self):
        """DEBUG is off in production, so a halt nobody saw left no trace."""
        import inspect

        import api.superadmin.nuclear_controls as nc

        source = inspect.getsource(nc)
        assert 'logger.debug("nuclear_halt WS broadcast skipped' not in source
        assert 'logger.debug("nuclear_resume WS broadcast skipped' not in source


class TestResumeIsHeldToTheSameStandard:
    def _resume(self, client, *, switch, redis):
        with (
            patch("api.superadmin.nuclear_controls._get_kill_switch", return_value=switch),
            patch("cache.redis_client.get_sync_redis_client", return_value=redis),
        ):
            return client.post("/api/superadmin/nuclear/resume")

    def test_a_working_resume_clears_both_places(self, client):
        switch, redis = _Switch(), _Redis()
        redis.written["kill_switch:active"] = "1"
        resp = self._resume(client, switch=switch, redis=redis)

        assert resp.status_code == 200, resp.text
        assert switch.deactivated is True
        assert "kill_switch:active" not in redis.written

    def test_a_resume_that_left_the_fleet_halted_says_so(self, client):
        """Worth as much as the halt case, in the other direction.

        A resume that clears this pod but not Redis leaves the other pods
        halted while the operator believes trading is back — and they will find
        out from a missing fill.
        """
        resp = self._resume(client, switch=_Switch(), redis=_Redis(raises=True))
        body = resp.json()
        assert body.get("ok") is not True or "propagat" in resp.text.lower(), (
            "a partial resume reported a clean success: " + resp.text[:300]
        )

    def test_no_kill_switch_on_resume_is_reported(self, client):
        resp = self._resume(client, switch=None, redis=_Redis())
        assert resp.json().get("ok") is not True or "local" in resp.text.lower()
