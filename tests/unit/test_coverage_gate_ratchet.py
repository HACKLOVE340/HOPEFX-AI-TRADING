# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""Making the gate able to measure must not turn it into a wall.

`docs/COVERAGE_UNMEASURABLE.txt` records 361 modules. Every one of them was
recorded because the gate could not measure it — and, as the sibling test
`test_coverage_gate_can_measure.py` establishes, *none* of them could be
measured, because `--cov=<dotted.module>` double-loaded numpy for all of them.
The list is therefore a record of one broken invocation, not of 361 untested
modules.

Repairing the invocation reveals their real numbers, and most are under the 80%
floor. Left alone, that converts a gate which quietly passed everything into one
that blocks every commit touching any of 361 files — and a gate that blocks work
people must do is switched off with `SKIP_COVERAGE_GATE=1`, which is worse than
either state.

So the recorded list becomes a ratchet, the same shape as the document registry,
the gate-evidence ledger and gate-e's `KNOWN_UNWIRED`:

* a recorded module reports its real number and does not block;
* a module that is **not** recorded must meet the floor, or it blocks;
* a recorded module that now meets the floor must leave the list, or it blocks —
  otherwise the record stops describing anything and the gate erodes.

The third rule is the one that makes it a ratchet rather than an allowlist.
"""

from __future__ import annotations

import pathlib
import sys

import pytest

pytestmark = pytest.mark.unit

REPO = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts"))


@pytest.fixture(scope="module")
def hook():
    import importlib.util

    spec = importlib.util.spec_from_file_location("pre_commit_coverage", REPO / "scripts" / "pre_commit_coverage.py")
    module = importlib.util.module_from_spec(spec)
    # Register before exec: @dataclass resolves its own module out of
    # sys.modules, and an unregistered one fails with a bare AttributeError.
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


PATH = pathlib.Path("risk/gatekeeper.py")
TEST = pathlib.Path("tests/unit/test_risk.py")


class TestAnUnrecordedModuleIsJudgedOnItsNumber:
    def test_at_or_above_the_floor_it_passes(self, hook) -> None:
        verdict = hook._judge(PATH, TEST, 84.0, recorded=False)
        assert verdict.ok
        assert "84" in verdict.message

    def test_below_the_floor_it_blocks(self, hook) -> None:
        verdict = hook._judge(PATH, TEST, 21.0, recorded=False)
        assert not verdict.ok
        assert "21" in verdict.message

    def test_unmeasured_still_blocks(self, hook) -> None:
        # Rule 2 — the reason this gate was repaired in the first place.
        verdict = hook._judge(PATH, TEST, None, recorded=False)
        assert not verdict.ok
        assert "could not be measured" in verdict.message


class TestARecordedModuleIsDebtNotPermission:
    def test_below_the_floor_it_reports_and_does_not_block(self, hook) -> None:
        verdict = hook._judge(PATH, TEST, 21.0, recorded=True)
        assert verdict.ok, "recorded debt must not block the commit that touches it"
        assert "21" in verdict.message, "the real number must be said out loud, not hidden behind the record"

    def test_the_message_names_it_as_debt(self, hook) -> None:
        verdict = hook._judge(PATH, TEST, 21.0, recorded=True)
        assert "DEBT" in verdict.message.upper()

    def test_unmeasured_and_recorded_still_does_not_block(self, hook) -> None:
        verdict = hook._judge(PATH, TEST, None, recorded=True)
        assert verdict.ok

    def test_reaching_the_floor_must_remove_the_entry(self, hook) -> None:
        """The ratchet tooth. Without it the list only ever grows stale."""
        verdict = hook._judge(PATH, TEST, 91.0, recorded=True)
        assert not verdict.ok, "a module that now clears the floor must leave the record"
        assert "docs/COVERAGE_UNMEASURABLE.txt" in verdict.message
        assert "91" in verdict.message


class TestTheRecordedListIsRealPaths:
    def test_every_recorded_path_exists(self, hook) -> None:
        gone = [p for p in sorted(hook._load_baseline()) if not (REPO / p).exists()]
        assert not gone, f"recorded but deleted — remove these lines: {gone[:10]}"


class TestAConfigExclusionSaysSoRatherThanBlamingTheTest:
    """The gate misdiagnosed its own blocking condition.

    `core/router_registry.py` sat in `.coveragerc`'s `[run] omit`, so
    measurement returned `None` and the gate reported "the test may not import
    the module, or may fail to collect" — while `tests/unit/test_core_router_registry.py`
    imports it on line 19 and nine tests exercised it. The message sent a reader
    hunting a missing import that was never missing, and the module blocked
    every commit that touched it.

    A report must distinguish what it measured from what it was told. "Nothing
    exercised this" and "the configuration forbade measuring it" have different
    fixes, and only the second one names its own.
    """

    def test_an_omitted_module_names_the_omit(self, hook) -> None:
        verdict = hook._judge(PATH, TEST, None, recorded=False, omitted=True)

        assert not verdict.ok, "a config exclusion must still block — it is not permission"
        assert "omit" in verdict.message.lower()
        assert "may not import the module" not in verdict.message, (
            "the gate still blames the test for a configuration exclusion"
        )

    def test_a_genuinely_unmeasured_module_keeps_the_original_message(self, hook) -> None:
        verdict = hook._judge(PATH, TEST, None, recorded=False, omitted=False)

        assert "may not import the module" in verdict.message

    def test_omission_does_not_change_a_module_that_measured(self, hook) -> None:
        """The flag explains an absent number; it must not colour a present one."""
        assert hook._judge(PATH, TEST, 84.0, recorded=False, omitted=True).ok


class TestReadingTheOmitList:
    def test_it_finds_a_real_entry(self, hook) -> None:
        """A genuinely hardware-dependent exclusion — there is no CUDA in CI.

        This used to name `core/startup_factories.py`, which was then lifted
        (§E47) because its stated reason was false, and this test went red. The
        example is now one whose reason is a property of the machine rather
        than a claim about the test suite, so lifting it would be a real
        decision rather than a correction.
        """
        import pathlib

        assert hook._coveragerc_omits(pathlib.Path("core/acceleration/gpu_engine.py")) is True

    def test_it_reads_whatever_the_file_actually_lists(self, hook) -> None:
        """Independent of any single name, so the next honest lift does not
        break the helper's own test — which is how this one broke."""
        import pathlib
        import re

        text = pathlib.Path(".coveragerc").read_text()
        block = text.split("omit", 1)[1]
        # Concrete paths only. A glob entry like `*/setup.py` handed back as a
        # Path would assert that the helper matches a pattern against itself,
        # which is true for a helper that does nothing.
        entries = [line.strip() for line in block.splitlines() if re.fullmatch(r"[\w./-]+\.py", line.strip() or "x x")]

        assert entries, "no concrete entry in the omit list — this proves nothing about a helper that reads it"
        for entry in entries:
            assert hook._coveragerc_omits(pathlib.Path(entry)) is True, f"the helper missed its own list: {entry}"

    def test_startup_factories_is_no_longer_omitted(self, hook) -> None:
        """The second exclusion found false under the same wording as
        `core/router_registry.py`: "requires full app context; covered by
        integration/e2e tests, not unit tests", while
        tests/unit/test_startup_factories.py and
        tests/unit/test_core_startup_factories.py exercise it directly, 59
        tests between them. Lifted 2026-09-10 (§E47); measured 49% and recorded
        as debt, where it applies pressure instead of being invisible.
        """
        import pathlib

        assert hook._coveragerc_omits(pathlib.Path("core/startup_factories.py")) is False

    def test_it_does_not_claim_an_unlisted_module(self, hook) -> None:
        import pathlib

        assert hook._coveragerc_omits(pathlib.Path("api/support.py")) is False

    def test_router_registry_is_no_longer_omitted(self, hook) -> None:
        """The exclusion whose stated reason was false.

        "Requires full app context; covered by integration/e2e tests" — while
        nine unit tests already exercised `register_routers` directly.
        """
        import pathlib

        assert hook._coveragerc_omits(pathlib.Path("core/router_registry.py")) is False

    def test_a_glob_entry_matches(self, hook) -> None:
        import pathlib

        assert hook._coveragerc_omits(pathlib.Path("whitelabel/anything.py")) is True

    def test_a_missing_config_is_not_an_exclusion(self, hook, tmp_path) -> None:
        """Fail toward measuring, not toward excusing."""
        import pathlib

        assert (
            hook._coveragerc_omits(pathlib.Path("core/acceleration/gpu_engine.py"), config=tmp_path / "nope") is False
        )

    def test_an_omit_pattern_on_the_assignment_line_is_read(self, hook, tmp_path) -> None:
        config = tmp_path / ".coveragerc"
        config.write_text("[run]\nomit = one_liner/*\nsource =\n    core\n")

        import pathlib

        assert hook._coveragerc_omits(pathlib.Path("one_liner/x.py"), config=config) is True
        assert hook._coveragerc_omits(pathlib.Path("core/x.py"), config=config) is False

    def test_a_pattern_under_another_section_is_not_an_omit(self, hook, tmp_path) -> None:
        """`[report] exclude_lines` entries are not exclusions of a file."""
        config = tmp_path / ".coveragerc"
        config.write_text("[run]\nomit =\n    real/*\n\n[report]\nexclude_lines =\n    fake/*\n")

        import pathlib

        assert hook._coveragerc_omits(pathlib.Path("real/x.py"), config=config) is True
        assert hook._coveragerc_omits(pathlib.Path("fake/x.py"), config=config) is False
