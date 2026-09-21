# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""Rule 1 evidence for the `adr-check` gate: the defects it must refuse.

A gate ships with proof it can fail, or it is treated as absent. This file
introduces each defect the gate exists to catch and asserts the refusal — not
"a test exists", but a test that injects.

The immutability case is the one worth having. It runs the gate against a real
throwaway git repository, commits a record, edits it, and checks the gate
notices — because the enforcement is a `git show` comparison, and a test that
mocked git would prove only that the mock was called.
"""

from __future__ import annotations

import importlib.util
import pathlib
import subprocess  # nosec B404 — git in a temp dir, fixed args
import sys

import pytest

pytestmark = pytest.mark.unit

REPO = pathlib.Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def adr():
    spec = importlib.util.spec_from_file_location("adr_injections", REPO / "scripts" / "adr.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


VALID = """# 0001. A real decision

- Status: accepted
- Date: 2026-09-09

## Context

Something forced a choice.

## Options considered

- **First.** Costs: one thing.
- **Second.** Costs: another thing.

## Decision

The first.

## Consequences

Makes one thing easy and another hard.

## Evidence

A command anyone can re-run.
"""


def _write(directory: pathlib.Path, name: str, body: str) -> pathlib.Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / name
    path.write_text(body, encoding="utf-8")
    return path


class TestTheGateRefusesEachDefect:
    def test_the_clean_case_passes_first(self, adr, tmp_path) -> None:
        # Asserted before the injections, so a gate that refuses EVERYTHING
        # cannot masquerade as one that works.
        _write(tmp_path, "0001-a.md", VALID)
        assert adr.validate_directory(tmp_path) == []

    def test_one_option(self, adr, tmp_path) -> None:
        _write(tmp_path, "0001-a.md", VALID.replace("- **Second.** Costs: another thing.\n", ""))
        assert adr.validate_directory(tmp_path)

    def test_a_missing_section(self, adr, tmp_path) -> None:
        _write(tmp_path, "0001-a.md", VALID.replace("## Evidence", "## Notes"))
        assert adr.validate_directory(tmp_path)

    def test_an_empty_section(self, adr, tmp_path) -> None:
        _write(tmp_path, "0001-a.md", VALID.replace("A command anyone can re-run.\n", ""))
        assert adr.validate_directory(tmp_path)

    def test_a_dangling_supersede(self, adr, tmp_path) -> None:
        _write(tmp_path, "0001-a.md", VALID.replace("Status: accepted", "Status: superseded by 0099"))
        assert adr.validate_directory(tmp_path)

    def test_a_numbering_gap(self, adr, tmp_path) -> None:
        _write(tmp_path, "0001-a.md", VALID)
        _write(tmp_path, "0003-c.md", VALID.replace("# 0001.", "# 0003."))
        assert adr.validate_directory(tmp_path)

    def test_a_filename_that_cannot_be_referenced(self, adr, tmp_path) -> None:
        _write(tmp_path, "decision-about-python.md", VALID)
        assert adr.validate_directory(tmp_path)


class TestImmutabilityAgainstRealGit:
    """The enforcement is `git show`, so the test uses git."""

    @staticmethod
    def _git(repo: pathlib.Path, *args: str) -> None:
        subprocess.run(  # nosec B603 B607 — fixed args, temp dir
            ["git", *args],
            cwd=str(repo),
            check=True,
            capture_output=True,
            text=True,
        )

    @pytest.fixture()
    def mirror(self, tmp_path, adr):
        repo = tmp_path / "mirror"
        (repo / "docs" / "decisions").mkdir(parents=True)
        (repo / "scripts").mkdir()
        self._git(repo, "init", "-q")
        self._git(repo, "config", "user.email", "t@example.com")
        self._git(repo, "config", "user.name", "t")
        _write(repo / "docs" / "decisions", "0001-a.md", VALID)
        self._git(repo, "add", "-A")
        self._git(repo, "commit", "-qm", "record")

        # Point the module at this tree for the duration.
        original = adr.ROOT
        adr.ROOT = repo
        yield repo
        adr.ROOT = original

    def test_an_untouched_record_is_fine(self, adr, mirror) -> None:
        assert adr.immutability_problems(mirror / "docs" / "decisions") == []

    def test_editing_an_accepted_record_is_refused(self, adr, mirror) -> None:
        path = mirror / "docs" / "decisions" / "0001-a.md"
        path.write_text(VALID.replace("The first.", "Actually the second."), encoding="utf-8")
        problems = adr.immutability_problems(mirror / "docs" / "decisions")
        assert problems, "an accepted record was rewritten and the gate allowed it"
        assert "supersede it" in problems[0].message

    def test_changing_only_the_status_is_permitted(self, adr, mirror) -> None:
        """The one edit an accepted record may carry.

        Without this the gate would forbid superseding, and a rule that forbids
        the correct action is one people route around.
        """
        path = mirror / "docs" / "decisions" / "0001-a.md"
        path.write_text(VALID.replace("Status: accepted", "Status: superseded by 0002"), encoding="utf-8")
        assert adr.immutability_problems(mirror / "docs" / "decisions") == []

    def test_a_record_git_has_never_seen_is_not_refused(self, adr, mirror) -> None:
        _write(mirror / "docs" / "decisions", "0002-b.md", VALID.replace("# 0001.", "# 0002."))
        assert adr.immutability_problems(mirror / "docs" / "decisions") == []
