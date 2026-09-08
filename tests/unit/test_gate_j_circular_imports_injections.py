# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""Gate J — circular imports across the trading packages.

A cycle causes ImportError or a subtly half-initialised module depending on
import order, and the gate's own header names the consequence it exists to
prevent: a circular import can "silently corrupt module-level singletons
(e.g. the kill switch state)". It had no test.

Injecting found that it never looked at the kill switch. `_py_files` did
`pkg_dir = root / package; if not pkg_dir.exists(): return []`, and
`kill_switch` is a single top-level file — `kill_switch.py`, not
`kill_switch/` — so it resolved to nothing while the PASS line went on
listing `kill_switch` among the packages checked. Confirmed by execution
against the real gate: a genuine `core.uses_ks` ↔ `kill_switch` cycle
reported "no circular imports detected". This is the same single-file
blind spot found in gate_e (§E6), in a second gate.

The mirror deliberately avoids pytest's `tmp_path`. This gate's
EXCLUDED_PATTERNS matches "test_" as a substring of the full path, and
tmp_path names its directories after the test function, so every file in
such a mirror is excluded before anything is scanned — the same trap that
made gate_e's first test suite pass vacuously.
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
GATE = REPO / "scripts" / "ci" / "gate_j_circular_imports.py"


@pytest.fixture
def mirror() -> Iterator[Path]:
    """A disposable repository holding the real gate and two guarded packages."""
    base = Path(tempfile.mkdtemp(prefix="gate_j_mirror_"))
    root = base / "repo"
    (root / "scripts" / "ci").mkdir(parents=True)
    shutil.copy2(GATE, root / "scripts" / "ci" / GATE.name)
    for pkg in ("core", "risk"):
        (root / pkg).mkdir()
        (root / pkg / "__init__.py").write_text("", encoding="utf-8")
    (root / "core" / "settled.py").write_text("import logging\n\nlog = logging.getLogger(__name__)\n", encoding="utf-8")
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


def _write(root: Path, rel: str, source: str) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(source, encoding="utf-8")
    assert path.read_text(encoding="utf-8") == source, "injection did not land — it would prove nothing"


class TestTheMirrorIsFaithful:
    def test_an_untouched_mirror_passes(self, mirror: Path) -> None:
        result = _run(mirror)
        assert result.returncode == 0, result.stdout + result.stderr

    def test_the_gate_actually_built_a_graph(self, mirror: Path) -> None:
        # "no cycles across 0 modules" would pass every case below trivially.
        result = _run(mirror)
        assert "across 3 modules" in result.stdout, result.stdout


class TestItCatchesRealCycles:
    def test_a_two_module_cycle_fails(self, mirror: Path) -> None:
        _write(mirror, "core/a.py", "import core.b\n")
        _write(mirror, "core/b.py", "import core.a\n")
        result = _run(mirror)
        assert result.returncode == 1
        assert "core.a" in result.stdout and "core.b" in result.stdout

    def test_a_three_module_cycle_fails(self, mirror: Path) -> None:
        _write(mirror, "core/a.py", "import core.b\n")
        _write(mirror, "core/b.py", "import core.c\n")
        _write(mirror, "core/c.py", "import core.a\n")
        result = _run(mirror)
        assert result.returncode == 1
        assert "3 modules" in result.stdout

    def test_a_cycle_across_two_guarded_packages_fails(self, mirror: Path) -> None:
        _write(mirror, "core/uses_risk.py", "from risk.engine import compute\n")
        _write(mirror, "risk/engine.py", "from core.uses_risk import helper\n\n\ndef compute():\n    return 1\n")
        result = _run(mirror)
        assert result.returncode == 1
        assert "core.uses_risk" in result.stdout and "risk.engine" in result.stdout

    def test_a_diamond_without_a_cycle_passes(self, mirror: Path) -> None:
        # The positive control: shared dependencies are not cycles, and a gate
        # that called them cycles would be unusable.
        _write(mirror, "core/a.py", "import core.b\nimport core.c\n")
        _write(mirror, "core/b.py", "import core.d\n")
        _write(mirror, "core/c.py", "import core.d\n")
        _write(mirror, "core/d.py", "x = 1\n")
        result = _run(mirror)
        assert result.returncode == 0, result.stdout


class TestTheKillSwitchIsActuallyInTheGraph:
    """kill_switch is a single top-level file, not a package directory."""

    def test_a_cycle_through_kill_switch_fails(self, mirror: Path) -> None:
        _write(mirror, "core/uses_ks.py", "import kill_switch\n")
        _write(mirror, "kill_switch.py", "import core.uses_ks\n")
        result = _run(mirror)
        assert result.returncode == 1, "a cycle through kill_switch.py was reported as no cycle at all"
        assert "kill_switch" in result.stdout
        assert "core.uses_ks" in result.stdout

    def test_kill_switch_is_counted_even_without_a_cycle(self, mirror: Path) -> None:
        _write(mirror, "kill_switch.py", "import logging\n")
        result = _run(mirror)
        assert result.returncode == 0, result.stdout
        # 3 from the base mirror + kill_switch.py
        assert "across 4 modules" in result.stdout, result.stdout


class TestDocumentedScope:
    def test_a_deferred_import_inside_a_function_is_not_an_edge(self, mirror: Path) -> None:
        # Documented and deliberate: a function-level import is the standard
        # way to break a cycle, so it must not be reported as one.
        _write(mirror, "core/a.py", "def get():\n    import core.b\n\n    return core.b\n")
        _write(mirror, "core/b.py", "def get():\n    import core.a\n\n    return core.a\n")
        result = _run(mirror)
        assert result.returncode == 0, result.stdout

    def test_the_module_level_form_of_the_same_pair_does_fail(self, mirror: Path) -> None:
        # The control that gives the exemption above its meaning.
        _write(mirror, "core/a.py", "import core.b\n")
        _write(mirror, "core/b.py", "import core.a\n")
        assert _run(mirror).returncode == 1

    def test_external_imports_do_not_create_edges(self, mirror: Path) -> None:
        _write(mirror, "core/a.py", "import logging\nimport json\nfrom pathlib import Path\n")
        result = _run(mirror)
        assert result.returncode == 0, result.stdout


class TestTheRealTreeStillPasses:
    def test_the_real_gate_passes_and_now_includes_kill_switch(self) -> None:
        result = subprocess.run(  # nosec B603 — fixed argument list, no shell
            [sys.executable, str(GATE)],
            capture_output=True,
            text=True,
            check=False,
            cwd=REPO,
        )
        assert result.returncode == 0, f"the real tree has a circular import:\n{result.stdout}"
        # 401 before kill_switch.py entered the graph, 402 after. Pinned as a
        # lower bound so adding modules does not turn this into a chore.
        count = int(result.stdout.split("across ")[1].split(" modules")[0])
        assert count >= 402, f"the graph shrank to {count} modules — something stopped being scanned"
