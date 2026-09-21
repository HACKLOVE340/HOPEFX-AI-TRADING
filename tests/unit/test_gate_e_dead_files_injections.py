# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""Gate E — a Python module in a guarded package that nothing imports.

Guards execution/, risk/, kill_switch, brokers/, core/: dead code there is
unused execution or risk logic, or a module that was meant to be wired and
was silently disconnected. It had no test.

REPO_ROOT is computed from __file__ with no env indirection, so proving this
means mirroring the real script at the same relative depth (scripts/ci/)
under a disposable root — the same shape as gate_i's mirror — rather than
monkeypatching a module constant, which would prove the function works, not
that the actual script pre-commit runs against a real tree does.

Injecting found a real defect, not just a coverage gap. `GUARDED_PACKAGES`
names "kill_switch", but `kill_switch` is a single top-level file
(`kill_switch.py`), not a directory. `_collect_py_files` does
`pkg_dir = root / package; if not pkg_dir.exists(): return []` — `root /
"kill_switch"` is never a directory, so it always returns `[]` and the
kill_switch guard silently checks nothing, in the real repository as it
stands today. A completely unimported `kill_switch.py` passes Gate E clean.
Fixed by treating a guarded name that resolves to `<name>.py` as a
single-file package: one file, checked the same way a package member is.
"""

from __future__ import annotations

import shutil
import subprocess  # nosec B404 — runs the gate under test, fixed argument list
import sys
import tempfile
from collections.abc import Iterator
from pathlib import Path

import pytest

pytestmark = [pytest.mark.unit]

REPO = Path(__file__).resolve().parents[2]
GATE = REPO / "scripts" / "ci" / "gate_e_dead_files.py"


@pytest.fixture
def mirror() -> Iterator[Path]:
    """A disposable repository holding the real gate and a minimal guarded tree.

    Deliberately NOT pytest's `tmp_path`: it names the directory after the
    test function, e.g. `.../test_an_unimported_module_in_a0/...`, and the
    gate's own EXCLUDED_PATTERNS matches "test_" as a SUBSTRING OF THE FULL
    PATH — so every file under a tmp_path mirror was silently excluded from
    every scan by the test harness's own directory name, independent of
    anything under test. Every assertion in this file passed vacuously
    (0 dead files because 0 files were ever scanned) until this was found.
    `tempfile.mkdtemp()` gives a path with no such collision.
    """
    base = Path(tempfile.mkdtemp(prefix="gate_e_mirror_"))
    root = base / "repo"
    (root / "scripts" / "ci").mkdir(parents=True)
    (root / "execution").mkdir()
    shutil.copy2(GATE, root / "scripts" / "ci" / GATE.name)
    (root / "execution" / "__init__.py").write_text("", encoding="utf-8")
    (root / "execution" / "live.py").write_text("def f() -> int:\n    return 1\n", encoding="utf-8")
    # The importer lives outside every guarded package and every excluded
    # pattern, so the gate's cross-repo import scan actually sees it.
    (root / "glue.py").write_text("import execution.live\n", encoding="utf-8")
    try:
        yield root
    finally:
        shutil.rmtree(base, ignore_errors=True)


def _run(root: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # nosec B603 — fixed argument list, no shell
        [sys.executable, str(root / "scripts" / "ci" / GATE.name)],
        capture_output=True,
        text=True,
        check=False,
        cwd=root,
    )


class TestTheMirrorIsFaithful:
    def test_an_untouched_mirror_passes(self, mirror: Path) -> None:
        result = _run(mirror)
        assert result.returncode == 0, result.stdout + result.stderr


class TestItCatchesARealOrphan:
    def test_an_unimported_module_in_a_guarded_package_fails(self, mirror: Path) -> None:
        (mirror / "execution" / "orphan.py").write_text("def g() -> int:\n    return 2\n", encoding="utf-8")
        result = _run(mirror)
        assert result.returncode == 1, "an unimported module in execution/ did not fail the gate"
        assert "execution/orphan.py" in result.stdout

    def test_a_dead_file_in_each_directory_guarded_package_is_caught(self, mirror: Path) -> None:
        # The case above only exercises execution/. Prove the other
        # directory-shaped guarded packages are actually scanned, not just
        # named in GUARDED_PACKAGES with nothing behind them — which is
        # exactly the defect this file goes on to find for kill_switch.
        for package in ("risk", "brokers", "core"):
            (mirror / package).mkdir(exist_ok=True)
            (mirror / package / "orphan.py").write_text("x = 1\n", encoding="utf-8")
        result = _run(mirror)
        assert result.returncode == 1
        for package in ("risk", "brokers", "core"):
            assert f"{package}/orphan.py" in result.stdout, f"{package}/orphan.py was not reported as dead"


class TestDocumentedExclusionsAreNotABypass:
    def test_a_test_file_in_a_guarded_package_is_not_flagged(self, mirror: Path) -> None:
        # "test_" is documented as intentionally standalone. If this silently
        # exempted every unimported file, it would be a bypass rather than a
        # scoped exclusion — prove it only exempts what it names.
        (mirror / "execution" / "test_something.py").write_text("def test_x():\n    assert True\n", encoding="utf-8")
        result = _run(mirror)
        assert result.returncode == 0, "a test_ file was flagged as dead — the exclusion regressed"

    def test_the_exclusion_does_not_swallow_a_real_orphan(self, mirror: Path) -> None:
        # The companion to the case above: excluding test_ files must not
        # also swallow a real orphan that happens to sit near one.
        (mirror / "execution" / "test_something.py").write_text("def test_x():\n    assert True\n", encoding="utf-8")
        (mirror / "execution" / "orphan.py").write_text("def g() -> int:\n    return 2\n", encoding="utf-8")
        result = _run(mirror)
        assert result.returncode == 1
        assert "execution/orphan.py" in result.stdout
        assert "execution/test_something.py" not in result.stdout


class TestTheKillSwitchGuardActuallyRuns:
    """kill_switch is a single top-level file, not a package directory.

    `_collect_py_files(root, "kill_switch")` used to check `root /
    "kill_switch"` only, which is never a directory, so it returned `[]`
    without ever looking at kill_switch.py — the guard silently checked
    nothing. Confirmed on the real repository before this fix: a completely
    unimported kill_switch.py passed Gate E clean.
    """

    def test_an_unimported_kill_switch_py_now_fails(self, mirror: Path) -> None:
        (mirror / "kill_switch.py").write_text("def orphaned() -> int:\n    return 3\n", encoding="utf-8")
        result = _run(mirror)
        assert result.returncode == 1, "an unimported kill_switch.py did not fail the gate"
        assert "kill_switch.py" in result.stdout

    def test_an_imported_kill_switch_py_still_passes(self, mirror: Path) -> None:
        (mirror / "kill_switch.py").write_text("def used() -> int:\n    return 4\n", encoding="utf-8")
        (mirror / "glue.py").write_text("import execution.live\nimport kill_switch\n", encoding="utf-8")
        result = _run(mirror)
        assert result.returncode == 0, result.stdout + result.stderr


class TestEntryPointsAndInitFilesStillCountAsImportSources:
    """EXCLUDED_PATTERNS correctly keeps app.py/__init__.py OUT of the
    guarded-candidate scan (they're run directly, or are package
    boilerplate — not "a module someone imports"). Reusing the same list
    to ALSO exclude them from the import-SOURCE scan was a second, separate
    bug: real production wiring lives in exactly these files —
    `app.py: from core.health import register_health_routes`,
    `brokers/__init__.py: from brokers.smart_router import SmartOrderRouter`
    — and excluding them made 100 real files across the tree look dead the
    moment this class's sibling tests fixed the prefix-pollution bug and
    the false "live" cover it provided came off.
    """

    def test_an_import_that_lives_only_in_app_py_still_counts(self, mirror: Path) -> None:
        (mirror / "execution" / "late_bound.py").write_text("def h() -> int:\n    return 5\n", encoding="utf-8")
        # app.py itself is excluded from the guarded scan (it's an entry
        # point, not a package member) — this only tests that ITS import
        # of a guarded file is still seen.
        (mirror / "app.py").write_text("from execution.late_bound import h\n", encoding="utf-8")
        result = _run(mirror)
        assert result.returncode == 0, result.stdout + result.stderr
        assert "execution/late_bound.py" not in result.stdout

    def test_a_reexport_inside_init_py_still_counts(self, mirror: Path) -> None:
        (mirror / "execution" / "reexported.py").write_text("def i() -> int:\n    return 6\n", encoding="utf-8")
        (mirror / "execution" / "__init__.py").write_text(
            "from execution.reexported import i  # noqa: F401\n", encoding="utf-8"
        )
        result = _run(mirror)
        assert result.returncode == 0, result.stdout + result.stderr
        assert "execution/reexported.py" not in result.stdout
