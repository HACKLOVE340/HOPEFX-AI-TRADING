# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# AGPL-3.0 — Share all modifications
"""
tests/unit/test_security_monitor_feed.py
=========================================
The attack feed behind ``GET /api/security/attacks``, and what it can say.

Coverage-floor programme, Task 6d.  ``security/monitor.py`` was recorded at
48.72% and ``security/__init__.py`` at nothing; both back an operator surface,
so ``.claude/skills/threat-modelling`` applies and stage 3 is the interesting
one.

**Read this before trusting the number on the dashboard.**  Stage 3 asks which
call site invokes the control.  For the *read* half — ``recent_attacks()``,
``attack_count()``, ``summary()`` — the answer is ``api/security_dashboard.py``
lines 86-88, and the tests below exercise it.  For the *write* half there is no
answer:

    $ grep -rn "record_attack" --include="*.py" . | grep -v ./.venv
    ./api/security_dashboard.py:96:def record_attack_event(...)     <- a different function
    ./security/monitor.py:31:def record_attack(event) -> None:      <- the definition

``security.monitor.record_attack`` has **no caller in this repository**, and
neither does ``api.security_dashboard.record_attack_event``, whose own
docstring says "Called by middleware / auth rate-limiter to record an attack."
Nothing calls it either.  So both buffers are empty by construction and
``GET /api/security/attacks`` returns ``{"events": [], "total": 0}`` whatever is
happening to the platform — the third dead-control shape, *a measurement that
cannot fail*, pointed at an operator who is looking at it precisely because
they suspect something is wrong.

That is recorded as a finding rather than fixed here: wiring attack recording
into the request path of a money-moving system is a behaviour change with an
owner, not a coverage task.  See ``docs/audit/CODE_READING_FINDINGS.md`` F273.

What these tests do is make the buffer's behaviour true *when something does
call it*, so the day it is wired the semantics are already pinned: newest
first, bounded, timestamped, and counting monotonically past the window it can
hold.
"""

from __future__ import annotations

import importlib
from datetime import datetime

import pytest

import security.monitor as monitor_mod


@pytest.fixture(autouse=True)
def _empty_buffer():
    """The buffer and the counter are module globals shared by every test."""
    monitor_mod._event_buffer.clear()
    monitor_mod._total_count = 0
    monitor_mod._monitor_instance = None
    yield
    monitor_mod._event_buffer.clear()
    monitor_mod._total_count = 0
    monitor_mod._monitor_instance = None


@pytest.fixture
def feed() -> monitor_mod.SecurityMonitor:
    return monitor_mod.get_security_monitor()


class TestWhatTheOperatorSeesWhenNothingHasHappened:
    def test_an_untouched_feed_is_empty_rather_than_absent(self, feed):
        assert feed.recent_attacks() == []
        assert feed.attack_count() == 0

    def test_the_summary_is_shaped_for_the_dashboard_even_when_empty(self, feed):
        assert feed.summary() == {"total_attacks": 0, "recent_10": []}


class TestRecording:
    def test_an_event_reaches_the_feed(self, feed):
        monitor_mod.record_attack({"event_type": "brute_force", "ip": "10.0.0.9"})
        assert feed.attack_count() == 1
        assert feed.recent_attacks()[0]["ip"] == "10.0.0.9"

    def test_an_event_without_a_timestamp_is_given_one(self, feed):
        monitor_mod.record_attack({"event_type": "sqli"})
        stamped = feed.recent_attacks()[0]["timestamp"]
        # Parses, and is the ISO-8601 the dashboard renders.
        assert datetime.fromisoformat(stamped).tzinfo is not None

    def test_a_caller_supplied_timestamp_is_left_alone(self, feed):
        monitor_mod.record_attack({"event_type": "sqli", "timestamp": "2026-01-01T00:00:00+00:00"})
        assert feed.recent_attacks()[0]["timestamp"] == "2026-01-01T00:00:00+00:00"

    def test_the_caller_s_dict_is_not_mutated(self, feed):
        """The stamping path copies rather than writing into the caller's dict.

        A recorder that edits what it was handed is a recorder a middleware
        cannot safely call with a request-scoped dict.
        """
        event = {"event_type": "sqli"}
        monitor_mod.record_attack(event)
        assert "timestamp" not in event

    def test_newest_first(self, feed):
        for i in range(5):
            monitor_mod.record_attack({"event_type": "probe", "n": i})
        assert [e["n"] for e in feed.recent_attacks()] == [4, 3, 2, 1, 0]

    def test_the_limit_takes_the_newest_not_the_oldest(self, feed):
        """The bug this pins: ``events[-limit:]`` then reversed.

        Slicing from the front and reversing would hand the operator the five
        oldest probes during an incident, newest-looking but stale.
        """
        for i in range(20):
            monitor_mod.record_attack({"event_type": "probe", "n": i})
        assert [e["n"] for e in feed.recent_attacks(limit=5)] == [19, 18, 17, 16, 15]

    def test_a_limit_larger_than_the_feed_returns_what_there_is(self, feed):
        monitor_mod.record_attack({"event_type": "probe", "n": 0})
        assert len(feed.recent_attacks(limit=500)) == 1

    def test_the_summary_carries_at_most_ten(self, feed):
        for i in range(25):
            monitor_mod.record_attack({"event_type": "probe", "n": i})
        summary = feed.summary()
        assert summary["total_attacks"] == 25
        assert len(summary["recent_10"]) == 10
        assert summary["recent_10"][0]["n"] == 24


class TestTheBufferIsBounded:
    def test_it_stops_growing_at_its_maximum(self, feed):
        for i in range(monitor_mod._MAX_EVENTS + 50):
            monitor_mod.record_attack({"event_type": "flood", "n": i})
        assert len(monitor_mod._event_buffer) == monitor_mod._MAX_EVENTS

    def test_the_total_keeps_counting_past_what_the_buffer_holds(self, feed):
        """A flood that overruns the window must not read as a smaller flood.

        ``attack_count()`` is the KPI on SecurityDashboard.tsx; if it were
        ``len(buffer)`` it would plateau at 1000 exactly when the number
        mattered most.
        """
        total = monitor_mod._MAX_EVENTS + 50
        for i in range(total):
            monitor_mod.record_attack({"event_type": "flood", "n": i})
        assert feed.attack_count() == total

    def test_the_oldest_events_are_the_ones_dropped(self, feed):
        for i in range(monitor_mod._MAX_EVENTS + 3):
            monitor_mod.record_attack({"event_type": "flood", "n": i})
        kept = [e["n"] for e in feed.recent_attacks(limit=monitor_mod._MAX_EVENTS)]
        assert kept[0] == monitor_mod._MAX_EVENTS + 2
        assert min(kept) == 3


class TestTheSingleton:
    def test_every_caller_gets_the_same_feed(self):
        assert monitor_mod.get_security_monitor() is monitor_mod.get_security_monitor()

    def test_an_event_recorded_through_one_handle_is_visible_from_another(self):
        first = monitor_mod.get_security_monitor()
        monitor_mod.record_attack({"event_type": "probe"})
        assert monitor_mod.get_security_monitor().attack_count() == first.attack_count() == 1


class TestThePackageReExports:
    """``security/__init__.py`` swallows each import at DEBUG, so a broken
    re-export would present as a missing name at the call site rather than as
    an error at import time."""

    def test_the_two_documented_helpers_are_importable_from_the_package(self):
        import security

        importlib.reload(security)
        assert callable(security.get_security_monitor)
        assert callable(security.get_lockdown_manager)

    def test_the_package_level_helper_returns_the_same_singleton_as_the_module(self):
        import security

        assert security.get_security_monitor() is monitor_mod.get_security_monitor()


class TestWhatThePackageDoesWhenASubmoduleWillNotImport:
    """Each re-export in ``security/__init__.py`` is wrapped in
    ``except Exception: logger.debug(...)``.

    The intent is legitimate — the security package should not take the whole
    application down because one optional subsystem is missing.  The cost is
    that the *reason* is invisible in production, and the symptom surfaces
    later and elsewhere as ``ImportError: cannot import name
    'get_lockdown_manager'`` at whichever call site reached for it first.

    These pin that behaviour so the trade stays a decision rather than a
    surprise, and cover the three branches nothing else reaches.
    """

    @staticmethod
    def _reload_with_broken(name: str, caplog):
        import builtins
        import logging
        import sys

        real_import = builtins.__import__

        def _fail(mod, *args, **kwargs):
            if mod == name:
                raise ImportError(f"simulated: {name} is unavailable")
            return real_import(mod, *args, **kwargs)

        saved = {k: v for k, v in sys.modules.items() if k == "security" or k.startswith("security.")}
        try:
            for key in list(saved):
                del sys.modules[key]
            builtins.__import__ = _fail
            with caplog.at_level(logging.DEBUG, logger="security"):
                return importlib.import_module("security")
        finally:
            builtins.__import__ = real_import
            for key in [k for k in sys.modules if k == "security" or k.startswith("security.")]:
                del sys.modules[key]
            sys.modules.update(saved)

    @pytest.mark.parametrize(
        ("module", "missing_name"),
        [
            ("security.monitor", "get_security_monitor"),
            ("security.lockdown", "get_lockdown_manager"),
            ("security.antivirus", "get_av_engine"),
        ],
    )
    def test_the_package_still_imports_and_the_name_is_simply_absent(self, module, missing_name, caplog):
        package = self._reload_with_broken(module, caplog)
        assert not hasattr(package, missing_name)

    def test_the_reason_is_recorded_somewhere_even_if_only_at_debug(self, caplog):
        self._reload_with_broken("security.lockdown", caplog)
        assert any("security.lockdown unavailable" in r.getMessage() for r in caplog.records), (
            "a subsystem vanished and the package said nothing at all"
        )

    def test_one_broken_submodule_does_not_take_the_others_with_it(self, caplog):
        package = self._reload_with_broken("security.antivirus", caplog)
        assert callable(package.get_security_monitor)
        assert callable(package.get_lockdown_manager)
