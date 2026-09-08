# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""Gate I — the Alembic chain must stay a single, linear, connected history.

A broken chain means `alembic upgrade head` fails, which means the database
cannot be built or **restored** — so this gate sits directly under the Phase R1
restore work. It had no test.

It is alive: all six failure classes it documents are caught. That claim cost one
correction worth recording, because it is the failure this repository keeps
making in a new disguise.

## The first probe reported two dead rules. Both reports were wrong.

The duplicate-id injection rewrote the *root* migration's revision to the value
it already had — a no-op. The broken-link injection used a pattern matching
`= "..."` against the root's `= None`, and also did nothing. The gate passed both
times, and a passing gate after a no-op injection is indistinguishable from a
gate that cannot fail.

So every case below **asserts the injection actually changed the file** before
running the gate. `_inject` fails loudly rather than silently proving nothing.
"""

from __future__ import annotations

import re
import shutil
import subprocess  # nosec B404 — runs the gate under test, fixed argument list
import sys
from pathlib import Path

import pytest

pytestmark = [pytest.mark.unit]

REPO = Path(__file__).resolve().parents[2]
GATE = REPO / "scripts" / "ci" / "gate_i_migration_chain.py"
VERSIONS = REPO / "alembic" / "versions"


@pytest.fixture
def mirror(tmp_path: Path) -> Path:
    """A disposable repository holding the real gate and the real migrations."""
    root = tmp_path / "repo"
    (root / "scripts" / "ci").mkdir(parents=True)
    (root / "alembic" / "versions").mkdir(parents=True)
    shutil.copy2(GATE, root / "scripts" / "ci" / GATE.name)
    for path in VERSIONS.glob("*.py"):
        shutil.copy2(path, root / "alembic" / "versions" / path.name)
    return root


def _run(root: Path) -> int:
    return subprocess.run(  # nosec B603 — fixed argument list, no shell
        [sys.executable, str(root / "scripts" / "ci" / GATE.name)],
        capture_output=True,
        text=True,
        check=False,
    ).returncode


def _inject(path: Path, pattern: str, replacement: str) -> None:
    """Edit, and prove the edit happened.

    An injection that quietly fails to apply leaves the gate passing, and a
    passing gate after a no-op injection looks exactly like a gate that cannot
    fail. That mistake was made while writing this file.
    """
    before = path.read_text(encoding="utf-8")
    after = re.sub(pattern, replacement, before, count=1, flags=re.MULTILINE)
    assert after != before, f"injection {pattern!r} did not apply to {path.name} — it would prove nothing"
    path.write_text(after, encoding="utf-8")


def _a_non_root_migration(root: Path) -> Path:
    """A migration with a real parent — the root has `down_revision = None`,
    which most injections cannot meaningfully target."""
    for path in sorted((root / "alembic" / "versions").glob("*.py")):
        text = path.read_text(encoding="utf-8")
        if re.search(r'^down_revision[^=\n]*=\s*"', text, re.MULTILINE):
            return path
    pytest.fail("no non-root migration found — the fixture cannot express these injections")


class TestTheMirrorIsFaithful:
    def test_an_untouched_mirror_passes(self, mirror: Path) -> None:
        assert _run(mirror) == 0, "the mirror does not reproduce the real chain"

    def test_the_mirror_holds_the_real_migrations(self, mirror: Path) -> None:
        # A mirror with no migrations would pass every gate trivially.
        copied = list((mirror / "alembic" / "versions").glob("*.py"))
        assert len(copied) == len(list(VERSIONS.glob("*.py"))) >= 10, len(copied)


class TestEveryFailureClassIsCaught:
    def test_a_duplicate_revision_id_is_caught(self, mirror: Path) -> None:
        target = _a_non_root_migration(mirror)
        root_id = re.search(r'^revision[^=\n]*=\s*"([^"]+)"', target.read_text(), re.MULTILINE)
        assert root_id
        other = next(p for p in sorted((mirror / "alembic" / "versions").glob("*.py")) if p != target)
        stolen = re.search(r'^revision[^=\n]*=\s*"([^"]+)"', other.read_text(), re.MULTILINE)
        assert stolen
        _inject(target, r'^revision(\s*:[^=\n]*)?=\s*"[^"]+"', f'revision: str = "{stolen.group(1)}"')
        assert _run(mirror) != 0

    def test_a_broken_down_revision_link_is_caught(self, mirror: Path) -> None:
        target = _a_non_root_migration(mirror)
        _inject(
            target,
            r'^down_revision([^=\n]*)=\s*"[^"]+"',
            r'down_revision\1= "revision_that_does_not_exist"',
        )
        assert _run(mirror) != 0

    def test_a_second_head_is_caught(self, mirror: Path) -> None:
        root_id = self._root_id(mirror)
        (mirror / "alembic" / "versions" / "zz_second_head.py").write_text(
            f'revision: str = "second_head_xyz"\ndown_revision: str | None = "{root_id}"\n',
            encoding="utf-8",
        )
        assert _run(mirror) != 0

    def test_a_second_root_is_caught(self, mirror: Path) -> None:
        (mirror / "alembic" / "versions" / "zz_second_root.py").write_text(
            'revision: str = "second_root_xyz"\ndown_revision: str | None = None\n',
            encoding="utf-8",
        )
        assert _run(mirror) != 0

    def test_a_disconnected_island_is_caught(self, mirror: Path) -> None:
        versions = mirror / "alembic" / "versions"
        (versions / "zz_island_a.py").write_text(
            'revision: str = "island_a_xyz"\ndown_revision: str | None = "island_b_xyz"\n',
            encoding="utf-8",
        )
        (versions / "zz_island_b.py").write_text(
            'revision: str = "island_b_xyz"\ndown_revision: str | None = "island_a_xyz"\n',
            encoding="utf-8",
        )
        assert _run(mirror) != 0

    @staticmethod
    def _root_id(mirror: Path) -> str:
        for path in sorted((mirror / "alembic" / "versions").glob("*.py")):
            text = path.read_text(encoding="utf-8")
            if re.search(r"^down_revision[^=\n]*=\s*None", text, re.MULTILINE):
                m = re.search(r'^revision[^=\n]*=\s*"([^"]+)"', text, re.MULTILINE)
                assert m
                return m.group(1)
        pytest.fail("no root migration found in the mirror")


class TestTheInjectionGuardItself:
    """`_inject` is the thing standing between this file and a suite of tests
    that prove nothing. It gets its own test."""

    def test_a_pattern_that_matches_nothing_fails_loudly(self, tmp_path: Path) -> None:
        path = tmp_path / "m.py"
        path.write_text('revision: str = "abc"\n', encoding="utf-8")
        with pytest.raises(AssertionError, match="did not apply"):
            _inject(path, r"^this_pattern_matches_nothing", "x")

    def test_a_replacement_identical_to_the_original_fails_loudly(self, tmp_path: Path) -> None:
        # The exact mistake made while writing this file: rewriting a value to
        # the value it already had.
        path = tmp_path / "m.py"
        path.write_text('revision: str = "abc"\n', encoding="utf-8")
        with pytest.raises(AssertionError, match="did not apply"):
            _inject(path, r'^revision: str = "abc"', 'revision: str = "abc"')
