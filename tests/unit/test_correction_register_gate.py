# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""The correction-register gate must be able to refuse.

`docs/audit/CORRECTION_REGISTER.md` is the single list of outstanding work, and
its value rests entirely on its status column being measured rather than
remembered. The pre-commit hook `correction-register` is what enforces that. A
hook nobody has watched fail is not a hook — Group 2 Rule 1 — so each test below
introduces a specific way the register can go wrong and asserts `--check`
refuses it.

The register is restored after every test; none of these mutate the tree that
survives the run.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "correction_register.py"
REGISTER = ROOT / "docs" / "audit" / "CORRECTION_REGISTER.md"


def _check() -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), "--check"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )


@pytest.fixture
def register_restored():
    """Hand back the original bytes whatever the test does to the file."""
    original = REGISTER.read_text()
    try:
        yield original
    finally:
        REGISTER.write_text(original)


def test_the_gate_passes_on_the_committed_register():
    """The positive control.

    Without this, every refusal below could be a script that refuses
    everything — which would pass the injections and prove nothing.
    """
    r = _check()
    assert r.returncode == 0, f"clean tree should pass:\n{r.stdout}\n{r.stderr}"
    assert "document agrees" in r.stdout


def test_a_wrong_headline_count_is_refused(register_restored):
    """The drift that made fifteen separate fix lists untrustworthy.

    A register whose counts no longer match the code is the checkbox problem in
    a new file. This is the case that fires when someone lands a fix and does
    not regenerate.
    """
    original = register_restored
    m = re.search(r"\*\*(\d+) tracked", original)
    assert m, "the register has no headline to check"
    REGISTER.write_text(original.replace(m.group(0), f"**{int(m.group(1)) + 7} tracked", 1))

    r = _check()
    assert r.returncode != 0, "a wrong count must not pass"
    assert "STALE" in r.stdout


def test_a_changed_status_count_is_refused(register_restored):
    """Not just the total — the OPEN/FIXED split is the part people read.

    A register that keeps the right total while calling an open item fixed is
    worse than one that is obviously stale, because it reads as current.
    """
    original = register_restored
    m = re.search(r"OPEN (\d+) · PARTIAL (\d+)", original)
    assert m, "the register has no status breakdown"
    REGISTER.write_text(original.replace(m.group(0), f"OPEN {int(m.group(1)) - 1} · PARTIAL {int(m.group(2)) + 1}", 1))

    r = _check()
    assert r.returncode != 0, "a wrong OPEN/PARTIAL split must not pass"
    assert "STALE" in r.stdout


def test_a_dropped_finding_is_refused(register_restored):
    """Deleting an entry must not be a way to make the register agree.

    The counts alone would not catch this if someone edited both; the gate also
    asserts every tracked finding still has a section.
    """
    original = register_restored
    m = re.search(r"^#### (\S+) ·", original, re.MULTILINE)
    assert m, "the register has no finding sections"
    heading = m.group(0)
    REGISTER.write_text(original.replace(heading, "#### (removed) ·", 1))

    r = _check()
    assert r.returncode != 0, f"a dropped finding must not pass:\n{r.stdout}"
    assert "absent from the register" in r.stdout


def test_a_missing_register_is_refused(register_restored):
    """Fail closed. Deleting the document must not read as 'nothing outstanding'."""
    REGISTER.unlink()
    r = _check()
    assert r.returncode != 0, "a missing register must not pass"
    assert "MISSING" in r.stdout


def test_a_probe_that_raises_does_not_report_the_finding_fixed():
    """A broken probe is UNVERIFIED, never FIXED.

    The failure mode this guards is the one the register exists to avoid: a
    measurement that cannot fail. If an exception inside a probe were swallowed
    into a passing status, the register would quietly report clean as the code
    moved out from under it.
    """
    sys.path.insert(0, str(ROOT))
    try:
        from scripts.correction_register import FIXED, UNVERIFIED, Finding

        def _boom() -> tuple[str, str]:
            raise RuntimeError("probe is broken")

        f = Finding("TEST", "t", "P3", "test", "src", "fix", "test first", "verify", _boom)
        status, evidence = f.measure()
        assert status == UNVERIFIED
        assert status != FIXED
        assert "RuntimeError" in evidence
    finally:
        sys.path.remove(str(ROOT))
