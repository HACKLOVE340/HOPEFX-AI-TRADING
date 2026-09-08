# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""`scripts/pre_commit_coverage.py` — the gate that stops coverage rotting.

It had no test, and injecting into it found the most inverted failure yet:

    module at 25% coverage   -> FAIL, exit 1     (correct)
    module at  0% coverage   -> pass,  exit 0     (the defect)
    test file that will not import -> pass, exit 0 (the defect)

**The worse the coverage, the more likely the gate let it through.**

The cause is exact. `_run_coverage` parses the `TOTAL` line out of pytest-cov's
terminal report. When the module is never imported by its test, coverage collects
nothing and prints no table at all — only:

    CoverageWarning: Module mymod.thing was never imported. (module-not-imported)
    CoverageWarning: No data was collected. (no-data-collected)
    WARNING: Failed to generate report: No data to report.

so the parser returns `None`, and `None` took the "warn but don't block" branch.
Rule 2 says an unmeasured value is absent, never zero — here it was being treated
as *success*, which is worse than zero.

An unmeasurable module now fails. `SKIP_COVERAGE_GATE=1` was already the
documented emergency bypass, so the fix needed no new escape hatch — a second one
would just be a second thing to reach for.

Every case runs against a disposable tree. The gate resolves test files by
relative path and shells out to pytest in the working directory, so the mirror is
a small real project rather than a mock.
"""

from __future__ import annotations

import os
import shutil
import subprocess  # nosec B404 — runs the gate under test, fixed argument list
import sys
import textwrap
from pathlib import Path

import pytest

pytestmark = [pytest.mark.unit]

REPO = Path(__file__).resolve().parents[2]
GATE = REPO / "scripts" / "pre_commit_coverage.py"

_MODULE_WITH_FOUR_FUNCTIONS = """
def covered(x):
    return x + 1


def uncovered_a(x):
    if x > 0:
        return "a"
    return "b"


def uncovered_b(x):
    total = 0
    for i in range(x):
        total += i
    return total


def uncovered_c(x):
    try:
        return 1 / x
    except ZeroDivisionError:
        return None
"""


@pytest.fixture
def project(tmp_path: Path) -> Path:
    """A disposable project the gate can resolve paths inside."""
    root = tmp_path / "proj"
    (root / "scripts").mkdir(parents=True)
    (root / "tests" / "unit").mkdir(parents=True)
    (root / "mymod").mkdir()
    shutil.copy2(GATE, root / "scripts" / GATE.name)
    shutil.copy2(REPO / ".coveragerc", root / ".coveragerc")
    (root / "mymod" / "__init__.py").write_text("", encoding="utf-8")
    (root / "mymod" / "thing.py").write_text(_MODULE_WITH_FOUR_FUNCTIONS, encoding="utf-8")
    return root


def _write_test(root: Path, body: str) -> None:
    (root / "tests" / "unit" / "test_thing.py").write_text(textwrap.dedent(body), encoding="utf-8")


def _run(root: Path, *args: str, **env: str) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    environment.update(env)
    return subprocess.run(  # nosec B603 — fixed argument list, no shell
        [sys.executable, "scripts/pre_commit_coverage.py", *(args or ("mymod/thing.py",))],
        cwd=root,
        capture_output=True,
        text=True,
        env=environment,
        check=False,
    )


class TestTheHarnessMeasuresSomething:
    """A gate that measured nothing would pass every case below."""

    def test_a_well_covered_module_passes(self, project: Path) -> None:
        _write_test(
            project,
            """
            from mymod.thing import covered, uncovered_a, uncovered_b, uncovered_c

            def test_everything():
                assert covered(1) == 2
                assert uncovered_a(1) == "a"
                assert uncovered_a(-1) == "b"
                assert uncovered_b(3) == 3
                assert uncovered_c(2) == 0.5
                assert uncovered_c(0) is None
            """,
        )
        result = _run(project)
        assert result.returncode == 0, f"{result.stdout}\n{result.stderr}"
        assert "OK" in result.stdout, result.stdout

    def test_an_under_covered_module_fails(self, project: Path) -> None:
        _write_test(
            project,
            """
            from mymod.thing import covered

            def test_only_one_function():
                assert covered(1) == 2
            """,
        )
        result = _run(project)
        assert result.returncode != 0, "an under-covered module passed the coverage gate"
        assert "below" in result.stderr or "FAIL" in result.stderr


class TestAnUnmeasurableModuleIsNotAPass:
    """The defect. Both cases exited 0 before this phase."""

    def test_a_module_the_test_never_imports_fails(self, project: Path) -> None:
        # 0% coverage: coverage collects no data and prints no TOTAL line, so the
        # parser returned None and the gate waved it through.
        _write_test(
            project,
            """
            def test_nothing_at_all():
                assert True
            """,
        )
        result = _run(project)
        assert result.returncode != 0, (
            "a module at 0% coverage passed the gate — the worse the coverage, the more likely it was let through"
        )

    def test_a_test_file_that_cannot_be_collected_fails(self, project: Path) -> None:
        _write_test(
            project,
            """
            import a_module_that_does_not_exist  # noqa: F401

            from mymod.thing import covered

            def test_one():
                assert covered(1) == 2
            """,
        )
        assert _run(project).returncode != 0, "a broken test import silently disabled the gate"

    def test_the_failure_says_it_could_not_measure(self, project: Path) -> None:
        # An operator seeing this must be able to tell "coverage is low" from
        # "coverage is unknown" — they need different fixes.
        _write_test(project, "def test_nothing():\n    assert True\n")
        combined = _run(project).stderr + _run(project).stdout
        assert "could not" in combined.lower() or "unmeasur" in combined.lower(), combined


class TestTheDocumentedBypassStillWorks:
    """The other half of Rule 1. A gate with no working escape hatch gets
    deleted rather than bypassed."""

    def test_skip_coverage_gate_skips(self, project: Path) -> None:
        _write_test(project, "def test_nothing():\n    assert True\n")
        result = _run(project, SKIP_COVERAGE_GATE="1")
        assert result.returncode == 0
        assert "SKIP" in result.stdout

    def test_a_module_with_no_test_file_is_still_skipped(self, project: Path) -> None:
        # Documented behaviour: a new module with no tests yet is not the
        # coverage gate's business.
        (project / "mymod" / "untested.py").write_text("def f():\n    return 1\n", encoding="utf-8")
        assert _run(project, "mymod/untested.py").returncode == 0

    def test_an_excluded_path_is_still_skipped(self, project: Path) -> None:
        (project / "scripts" / "helper.py").write_text("def f():\n    return 1\n", encoding="utf-8")
        assert _run(project, "scripts/helper.py").returncode == 0


class TestTheUnmeasurableBaselineIsARatchet:
    """Making an unmeasurable module fail was correct, but a hard cutover would
    have blocked every commit touching pre-existing debt — and a gate that
    blocks work people must do gets switched off with SKIP_COVERAGE_GATE=1.

    The debt is not small: **361 modules** resolve to a test file that never
    imports them. So the recorded set is a generated file, the same ratchet the
    document registry, the freshness checker and the gate-evidence ledger use.
    """

    def test_the_baseline_file_exists_and_is_populated(self) -> None:
        from scripts.pre_commit_coverage import BASELINE_PATH, _load_baseline

        assert BASELINE_PATH.exists(), (
            f"{BASELINE_PATH.name} is missing. Regenerate with `python scripts/pre_commit_coverage.py --adopt`."
        )
        baseline = _load_baseline()
        # A silently empty baseline would make every entry below "new" and block
        # every commit — the failure mode this file exists to prevent.
        assert len(baseline) > 50, f"baseline holds only {len(baseline)} entries — regenerate it"

    def test_every_baselined_module_still_exists(self) -> None:
        # An entry for a deleted file is debt that looks unpaid forever and
        # hides the fact that it was actually resolved.
        from scripts.pre_commit_coverage import _load_baseline

        missing = sorted(rel for rel in _load_baseline() if not (REPO / rel).exists())
        assert missing == [], f"baselined but deleted — drop these entries: {missing}"

    def test_no_baselined_module_is_a_test_or_excluded_path(self) -> None:
        from scripts.pre_commit_coverage import _is_excluded, _load_baseline

        for rel in sorted(_load_baseline()):
            path = Path(rel)
            assert not _is_excluded(path), f"{rel} is excluded from the gate; it cannot be debt"
            assert not path.name.startswith("test_"), rel

    def test_a_baselined_module_does_not_block(self, project: Path, monkeypatch) -> None:
        import scripts.pre_commit_coverage as gate

        baseline_file = project / "baseline.txt"
        baseline_file.write_text("mymod/thing.py\n", encoding="utf-8")
        monkeypatch.setenv("PYTHONPATH", str(project))
        _write_test(project, "def test_nothing():\n    assert True\n")

        # Point the copied gate at this project's baseline.
        gate_src = (project / "scripts" / "pre_commit_coverage.py").read_text(encoding="utf-8")
        gate_src = gate_src.replace(
            'BASELINE_PATH = Path(__file__).resolve().parent.parent / "docs" / "COVERAGE_UNMEASURABLE.txt"',
            'BASELINE_PATH = Path(__file__).resolve().parent.parent / "baseline.txt"',
        )
        (project / "scripts" / "pre_commit_coverage.py").write_text(gate_src, encoding="utf-8")

        result = _run(project)
        assert result.returncode == 0, f"a baselined module blocked:\n{result.stderr}"
        assert "BASELINED" in result.stderr
        assert gate  # the constant is importable from the real module

    def test_a_new_unmeasurable_module_still_blocks(self, project: Path) -> None:
        # The whole purpose. The baseline is a record of what was, not a licence
        # for what comes next.
        (project / "mymod" / "fresh.py").write_text("def f():\n    return 1\n", encoding="utf-8")
        (project / "tests" / "unit" / "test_fresh.py").write_text(
            "def test_nothing():\n    assert True\n", encoding="utf-8"
        )
        assert _run(project, "mymod/fresh.py").returncode != 0
