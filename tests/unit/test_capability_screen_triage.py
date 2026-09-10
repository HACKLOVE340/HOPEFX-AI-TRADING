# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""The caller screen should only flag rows worth inspecting.

`scripts/capability_callers.py` matches the evidence SYMBOL. That is a screen,
and it says so — but a third of what it flagged was false, measured in §E47:
13 of 38. A report that cries wolf a third of the time teaches readers to skim
it, and skimming is how `sec.secrets` survived sitting in the list while a
genuinely dead security control went unarmed for the life of the module.

Two things it could not know, and now does:

* **Derived roll-ups have no caller of their id by design.** `arch.layer_a..d`
  are computed by `layer_state()` from the rows beneath them. Flagging them is
  false by construction — four permanent wolves.

* **A symbol is not the only way to reach code.** Production reaches these
  through a default argument (`DEFAULT_MAX_CONCURRENT` is `JobRunner`'s
  default), a factory (`build_patcher()` rather than `GatewayPatcher`), an
  import chain, and `from pkg import module` — which defeated the author's own
  grep twice. Module reachability is reported ALONGSIDE the symbol count, not
  instead of it, so nothing is hidden: the reader gets a triage order rather
  than a shorter list.

The second signal is deliberately NOT used to drop rows. A module can be
imported for one export while the capability's own symbol is unreachable —
`hub/layout.ts` is imported for `readLayout`, and `COLLAPSE_ABOVE` still is not
reached. Collapsing the two would turn a screen into a measurement that cannot
fail.
"""

from __future__ import annotations

import pytest

pytestmark = [pytest.mark.unit]


@pytest.fixture(scope="module")
def screen():
    import importlib

    return importlib.import_module("scripts.capability_callers")


class TestTheSweepStillProvesItself:
    """The positive control the module already insists on. Without it every
    assertion below is about a sweep that may have read nothing."""

    def test_the_control_symbol_is_found(self, screen):
        assert screen.assert_sweep_works() >= screen.CONTROL_MIN_FILES


class TestRollUpsAreNotFlagged:
    def test_the_registry_still_has_roll_ups(self):
        """Liveness: if ROLLUP_IDS were empty the exclusion would be a no-op
        and the assertions below would pass against a screen that does nothing.
        """
        from ai.hub.capabilities import ROLLUP_IDS

        assert ROLLUP_IDS, "no roll-up ids — this exclusion cannot be tested"

    def test_no_roll_up_appears_in_the_screened_rows(self, screen):
        from ai.hub.capabilities import ROLLUP_IDS

        screened = {r.capability for r in screen.sweep()}

        assert screened.isdisjoint(ROLLUP_IDS), (
            f"derived roll-ups are screened for callers of their id: {sorted(screened & ROLLUP_IDS)}"
        )


class TestModuleReachabilityIsReportedSeparately:
    def test_a_row_carries_whether_its_module_is_reached(self, screen):
        rows = screen.sweep()

        assert rows, "nothing screened — the assertions below would be vacuous"
        assert hasattr(rows[0], "module_reached")

    def test_a_default_argument_is_recognised_as_reached(self, screen):
        """`DEFAULT_MAX_CONCURRENT` is `JobRunner.__init__`'s default; nobody
        names it, but `ai.jobs.runner` is imported by api/safe_agent_platform.py
        and api/ai_core.py."""
        rows = {r.capability: r for r in screen.sweep()}
        row = rows.get("perf.bounded_concurrency")

        assert row is not None, "the row vanished from the registry — update this test"
        assert row.module_reached is True

    def test_a_factory_reached_module_is_recognised(self, screen):
        """`core/startup_factories.py` does `from ai.improve import cycle,
        patcher` and calls `patcher.build_patcher()` — never `GatewayPatcher`."""
        rows = {r.capability: r for r in screen.sweep()}
        row = rows.get("improve.patch_generator")

        assert row is not None
        assert row.module_reached is True

    def test_a_from_package_import_module_is_recognised(self, screen):
        """The form that defeated the author's own grep twice:
        `api/ai_memory.py` does `from ai.memory import governance`."""
        rows = {r.capability: r for r in screen.sweep()}
        row = rows.get("memory.user_controls")

        assert row is not None
        assert row.module_reached is True

    def test_a_genuinely_unreached_module_is_reported_as_such(self, screen):
        """`ai/bus/triggers.py` is reached by nothing — not by symbol, not by
        module, and `ai/bus/__init__.py` re-exports agent_bus, graph and
        lifecycle and not triggers. The one real backend gap of the nine."""
        rows = {r.capability: r for r in screen.sweep()}
        row = rows.get("parallel.event_triggered")

        assert row is not None
        assert row.module_reached is False, "ai.bus.triggers now has an importer — good; update §E47"

    def test_reachability_does_not_silently_unflag_a_row(self, screen):
        """A module imported for one export says nothing about another. Keeping
        both signals is what stops this becoming a report that cannot fail."""
        rows = {r.capability: r for r in screen.sweep()}
        row = rows.get("perf.bounded_concurrency")

        assert row.uncalled is True, "module reachability was folded into `uncalled` and hid the row"


class TestTheScreenDoesNotCountItsOwnProse:
    """A checker that reads prose is not reading code.

    `security/code_analyzer.py` once scanned docstrings as if they were source
    (F255), and `scripts/verify_skill_claims.py` called four correct files
    broken because each carried a comment quoting the defect it fixed. This
    module walked into the same trap from the other side: documenting the
    triage put `DEFAULT_MAX_CONCURRENT`, `GatewayPatcher` and `COLLAPSE_ABOVE`
    into its own docstrings, the sweep counted itself as a production caller,
    and THREE ROWS SILENTLY LEFT THE FLAGGED LIST.

    A false positive in this screen wastes an inspection. A false negative
    hides a dead control, which is what the screen exists to find — so this is
    the direction that matters.
    """

    def test_the_screens_own_source_is_not_searched(self, screen):
        import subprocess

        # A symbol that appears in this module's prose and in exactly one
        # production module. If the screen searched itself it would see two.
        cmd = [
            "rg",
            "-l",
            "--no-messages",
            "DEFAULT_MAX_CONCURRENT",
            *screen._EXCLUDE,
            *screen._EXCLUDE_TESTS,
            str(screen.REPO),
        ]
        out = subprocess.run(cmd, capture_output=True, text=True, stdin=subprocess.DEVNULL, check=False).stdout
        hits = [line for line in out.strip().split("\n") if line]

        assert not any(h.endswith("scripts/capability_callers.py") for h in hits), (
            "the screen counts its own documentation as a production caller, so any symbol it "
            "explains stops being flagged"
        )

    def test_a_symbol_named_only_in_the_screens_prose_stays_flagged(self, screen):
        """The consequence, at the level that matters."""
        rows = {r.capability: r for r in screen.sweep()}
        row = rows.get("perf.bounded_concurrency")

        assert row is not None, "the row vanished from the registry — update this test"
        assert row.uncalled is True, "documenting this row is what un-flagged it"
