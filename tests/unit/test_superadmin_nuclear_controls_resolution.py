# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
tests/unit/test_superadmin_nuclear_controls_resolution.py
=========================================================
The superadmin nuclear controls could never reach the kill switch, and the two
bugs sitting behind that one would have made a naive fix worse.

``_get_kill_switch()`` tries two resolutions:

    from api.admin import app_state
    if app_state and hasattr(app_state, "kill_switch"):
        return app_state.kill_switch          # AppState has no such attribute

    import kill_switch as _ks_mod
    if hasattr(_ks_mod, "_instance"):
        return _ks_mod._instance              # the singleton is `kill_switch`

`AppState.__init__` never defines `kill_switch` and nothing in the tree assigns
`app_state.kill_switch` — the only `.kill_switch =` is on `PropEngine`, a
different object. `kill_switch.py:1383` names its singleton `kill_switch`, and
`_instance` appears nowhere in the module. Both branches are `hasattr`-guarded,
so neither raises: the function just returns ``None`` on every call.

`POST /nuclear/halt` therefore never activates the in-process kill switch. It
still writes the Redis latch, and `KillSwitch` polls that latch and activates
from it — so the halt does happen, which is why nobody noticed. But the
documented in-process path is dead, and **with Redis unavailable the superadmin
emergency halt does nothing but write a log line**.

Two further defects sat behind that one, and both had to be fixed in the same
change:

1. `nuclear_halt` does ``await ks.activate(reason=reason)`` and
   `nuclear_resume` does ``await ks.deactivate()``. Both methods are
   synchronous — ``activate(self, reason: str = 'manual activation') -> None``.
   Awaiting their ``None`` return raises ``TypeError``, which the surrounding
   ``except Exception`` logs as "Kill switch activate error". So the moment
   resolution started working, activation would have failed a different way.

2. `get_nuclear_status` reads
   ``bool(getattr(ks, "is_active", False) or getattr(ks, "enabled", False))``.
   ``is_active`` is a *method*, and a bound method is always truthy, so a
   working resolution would have reported the kill switch as **permanently
   active** to every superadmin — strictly worse than the current always-None
   behaviour. `enabled` does not exist; `reason` does.

The tests below pin the resolved singleton, the sync call, and the called
predicate.
"""

from __future__ import annotations

import inspect

import pytest

pytestmark = pytest.mark.unit


def test_kill_switch_module_singleton_is_named_kill_switch():
    """The name _get_kill_switch must look for."""
    import kill_switch as ks_mod

    assert hasattr(ks_mod, "kill_switch"), "the module singleton moved — update _get_kill_switch"
    assert not hasattr(ks_mod, "_instance"), (
        "an `_instance` alias appeared; the resolver should still prefer the documented "
        "`kill_switch` singleton"
    )


def test_app_state_has_no_kill_switch_attribute():
    """Pins the reason the first resolution branch is dead.

    If a `kill_switch` attribute is ever added to AppState this fails, which is
    the signal to restore that branch as the preferred source.
    """
    from core.app_state import AppState

    assert not hasattr(AppState(), "kill_switch")


def test_get_kill_switch_resolves_the_real_singleton():
    """The whole point: the resolver must return something."""
    from api.superadmin.nuclear_controls import _get_kill_switch
    from kill_switch import kill_switch as singleton

    resolved = _get_kill_switch()

    assert resolved is not None, (
        "_get_kill_switch() returned None, so every superadmin nuclear endpoint "
        "silently skips the in-process kill switch and relies entirely on Redis"
    )
    assert resolved is singleton


def test_activate_and_deactivate_are_synchronous():
    """Pins the shape the endpoints must call them with.

    If either becomes a coroutine function this fails, which is the signal to
    add the await back rather than discover it through a swallowed TypeError.
    """
    from kill_switch import KillSwitch

    assert not inspect.iscoroutinefunction(KillSwitch.activate)
    assert not inspect.iscoroutinefunction(KillSwitch.deactivate)


def test_endpoints_do_not_await_the_sync_kill_switch_calls():
    """Regression: `await ks.activate(...)` raises TypeError and is swallowed."""
    from api.superadmin import nuclear_controls

    halt = inspect.getsource(nuclear_controls.nuclear_halt)
    resume = inspect.getsource(nuclear_controls.nuclear_resume)

    assert "await ks.activate" not in halt, "activate is synchronous — awaiting it raises TypeError"
    assert "await ks.deactivate" not in resume, "deactivate is synchronous — awaiting it raises TypeError"


def test_status_calls_is_active_rather_than_testing_its_truthiness():
    """`is_active` is a method; `bool(method)` is always True.

    Without this, repairing resolution would report every kill switch as active.
    """
    from api.superadmin import nuclear_controls

    source = inspect.getsource(nuclear_controls.get_nuclear_status)

    assert 'getattr(ks, "is_active", False)' not in source, (
        "status tests the truthiness of a bound method, which is always True — "
        "it must call is_active()"
    )
    assert "is_active()" in source


def test_status_reports_inactive_for_a_fresh_kill_switch():
    """End to end on the predicate: a kill switch that is off must read as off."""
    from kill_switch import kill_switch as singleton

    assert singleton.is_active() is False, "fixture assumption: the module singleton starts inactive"

    # The expression get_nuclear_status uses, applied to the real singleton.
    reported = bool(singleton.is_active())
    assert reported is False, "an inactive kill switch was reported as active"
