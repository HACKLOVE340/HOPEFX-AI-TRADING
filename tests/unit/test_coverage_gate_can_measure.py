# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""The coverage gate could not measure anything that imports numpy.

`scripts/pre_commit_coverage.py` ran:

    pytest <test> --cov=risk.manager --cov-config=.coveragerc ...

and got:

    numpy/_core/multiarray.py:11: in <module>
        from . import _multiarray_umath, overrides
    ImportError: cannot load module more than once per process

Every module in scope imports numpy through `tests/conftest.py`, so the hook
could not measure a single one. It reported that as:

    "coverage could not be measured (test: ...) — the test may not import the
     module, or may fail to collect"

which reads like a problem with the test, and invites `SKIP_COVERAGE_GATE=1`.
A gate that cannot run, and blames the code for it, is worse than no gate: it
teaches people the bypass.

## What it actually was

Isolated by bisecting the pytest invocation:

    pytest <test>                        -> works
    pytest <test> --cov=risk.manager     -> ImportError    (dotted MODULE)
    pytest <test> --cov=risk             -> works          (PACKAGE)
    pytest <test> --cov=risk/manager.py  -> no ImportError, but collects nothing
                                            (.coveragerc `source` wins)

Nothing to do with numpy being broken — numpy imports fine under `coverage run`
on its own. Resolving a dotted *module* name makes coverage import it in a way
that initialises numpy's C extension twice.

So the hook measures the top-level package and reads the module's own row out
of the report, which is the number it wanted all along.
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


class TestItAsksCoverageForSomethingItCanResolve:
    def test_the_command_targets_a_package_not_a_dotted_module(self, hook) -> None:
        cmd = hook._coverage_command(pathlib.Path("risk/manager.py"), [pathlib.Path("tests/unit/test_risk_manager.py")])
        cov_args = [a for a in cmd if a.startswith("--cov=")]
        assert cov_args == ["--cov=risk"], (
            f"--cov must name the package; a dotted module makes coverage double-load numpy. Got {cov_args}"
        )

    def test_a_nested_module_still_targets_its_top_level_package(self, hook) -> None:
        cmd = hook._coverage_command(
            pathlib.Path("api/superadmin/ml_ai.py"), [pathlib.Path("tests/unit/test_superadmin.py")]
        )
        assert "--cov=api" in cmd

    def test_the_rcfile_fail_under_is_neutralised(self, hook) -> None:
        # .coveragerc sets fail_under=70 for the whole project. The hook judges a
        # single module against its own floor, so the global one must not turn a
        # successful measurement into a non-zero exit the parser reads as failure.
        cmd = hook._coverage_command(pathlib.Path("risk/manager.py"), [pathlib.Path("tests/unit/test_risk_manager.py")])
        assert "--cov-fail-under=0" in cmd


class TestItReadsTheModulesOwnNumber:
    def test_it_parses_the_module_row_not_the_total(self, hook) -> None:
        report = (
            "Name                     Stmts   Miss Branch BrPart   Cover\n"
            "risk/drawdown_tracker.py   146     66     38     10  48.91%\n"
            "risk/manager.py           1088    563    276     47  43.26%\n"
            "-------------------------------------------------------------\n"
            "TOTAL                     4594   3467   1150     62  21.01%\n"
        )
        assert hook._parse_module_coverage(report, pathlib.Path("risk/manager.py")) == pytest.approx(43.26)

    def test_a_module_absent_from_the_report_is_none_not_zero(self, hook) -> None:
        # Rule 2 again: unmeasured is absent, never the worst case either. A 0.0
        # here would fail the gate for a module nothing measured, which is a
        # different problem from a module measured at 0%.
        report = "TOTAL   10  0  0  0  100.00%\n"
        assert hook._parse_module_coverage(report, pathlib.Path("risk/manager.py")) is None

    def test_a_genuine_zero_is_reported_as_zero(self, hook) -> None:
        report = "risk/stress_test.py   68   68   6   0   0.00%\nTOTAL  68  68  6  0  0.00%\n"
        assert hook._parse_module_coverage(report, pathlib.Path("risk/stress_test.py")) == 0.0


class TestItMeasuresEveryTestThatExercisesTheModule:
    """One name-matched test file is not the module's test suite.

    `_find_test_file` resolved `risk/manager.py` to `tests/unit/test_risk_manager.py`
    and stopped. That file covers 52% of it; the whole suite covers 89.65%, which
    is the figure `.coveragerc` records. The gate was therefore blocking the
    repository's most heavily tested money module for being under-tested.

    That is worse than a false positive. A gate that refuses correct code is one
    people bypass, and `SKIP_COVERAGE_GATE=1` is documented — so this defect ends
    with the gate switched off, which is exactly what §E20 repaired it from.

    The fix is to measure what actually exercises the module: every test file
    that imports it, found by reading the imports rather than by guessing from a
    filename.
    """

    def test_it_finds_more_than_the_name_match(self, hook) -> None:
        found = hook._find_test_files(pathlib.Path("risk/manager.py"))
        names = {p.name for p in found}
        assert "test_risk_manager.py" in names, "the name match must still be included"
        assert len(found) > 1, f"only found {names}; risk/manager.py is imported by many test files"

    def test_every_file_it_returns_exists(self, hook) -> None:
        for path in hook._find_test_files(pathlib.Path("risk/manager.py")):
            assert (REPO / path).exists(), path

    def test_it_finds_the_tests_that_import_the_module(self, hook) -> None:
        names = {p.name for p in hook._find_test_files(pathlib.Path("risk/manager.py"))}
        # Written this session, and each imports risk.manager directly.
        assert "test_risk_refusals_reach_the_ledger.py" in names

    def test_it_finds_a_from_package_import_module(self, hook) -> None:
        """`from ai.ledger import decisions` is the common form and was missed.

        The first matcher only looked for `from ai.ledger.decisions import`,
        `import ai.ledger.decisions` and `ai.ledger.decisions.` — so a module
        imported the ordinary way found no tests at all and was SKIPPED
        SILENTLY, which is the quietest possible failure for a coverage gate:
        the module reads as "new, not yet tested" while carrying 44 tests.
        """
        names = {p.name for p in hook._find_test_files(pathlib.Path("ai/ledger/decisions.py"))}
        assert "test_decision_ledger.py" in names, names

    def test_a_module_nothing_imports_returns_nothing(self, hook) -> None:
        assert hook._find_test_files(pathlib.Path("no/such/module.py")) == []

    def test_the_command_covers_every_file_found(self, hook) -> None:
        files = hook._find_test_files(pathlib.Path("risk/manager.py"))
        cmd = hook._coverage_command(pathlib.Path("risk/manager.py"), files)
        for path in files:
            assert str(path) in cmd


class TestItActuallyRuns:
    """The point of the exercise — end to end, against the real tree."""

    @pytest.mark.slow
    def test_it_measures_risk_manager_without_an_import_error(self, hook) -> None:
        pct, output = hook._run_coverage(
            pathlib.Path("risk/manager.py"), [pathlib.Path("tests/unit/test_risk_manager.py")]
        )
        assert "cannot load module more than once" not in output, "the numpy double-load is back:\n" + output[-2000:]
        assert pct is not None, "coverage still could not be measured:\n" + output[-2000:]
        assert 0.0 < pct <= 100.0
