# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""`scripts.repo_scan.iter_tracked_files` — the fix for F-worktree-scan.

`tests/unit/test_no_model_call_bypasses_the_gateway.py` failed twice because it
scanned copies of `ai/gateway/adapters.py` sitting inside
`.claude/worktrees/agent-*/` — agent worktrees live *inside* the repo
directory, and `.claude/worktrees/` is gitignored, but a plain
`pathlib.Path.rglob()` walks the filesystem, not the index, so it does not
know that. `tests/unit/test_advanced_ai_is_superseded.py` walks the whole tree
the same way and slowed past its timeout under load for the same reason: more
worktrees on disk means more bytes to walk for a scan that should never have
seen them.

This module is the one shared place that answers "what does this repository
actually contain": `git ls-files`, not the filesystem. Every repo-wide scanner
should build its file list from `iter_tracked_files`, not from its own
`rglob()` call.
"""

from __future__ import annotations

import pathlib
import subprocess

import pytest

pytestmark = pytest.mark.unit

from scripts.repo_scan import REPO_ROOT, iter_tracked_files


def _init_repo(tmp_path: pathlib.Path) -> pathlib.Path:
    """A minimal real git repo with one tracked file, for a synthetic worktree fixture."""
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, check=True)
    (repo / "ai" / "gateway").mkdir(parents=True)
    (repo / "ai" / "gateway" / "adapters.py").write_text("REAL_ADAPTER = True\n", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=repo, check=True)
    return repo


def _plant_untracked_worktree_copy(repo: pathlib.Path) -> pathlib.Path:
    """A throwaway file inside a `.claude/worktrees/x/` copy, exactly as an agent worktree
    checked out alongside the real repo would leave one — never `git add`-ed."""
    copy_dir = repo / ".claude" / "worktrees" / "agent-x" / "ai" / "gateway"
    copy_dir.mkdir(parents=True)
    copy_file = copy_dir / "adapters.py"
    copy_file.write_text("COPY_ADAPTER = True\n", encoding="utf-8")
    return copy_file


def test_red_a_naive_rglob_walks_into_the_untracked_worktree_copy(tmp_path):
    """RED: this is the defect. A plain filesystem walk cannot tell a real
    source file from a copy left by an agent worktree — it has no notion of
    "tracked" at all."""
    repo = _init_repo(tmp_path)
    copy_file = _plant_untracked_worktree_copy(repo)

    naively_found = {p.relative_to(repo).as_posix() for p in repo.rglob("*.py")}

    assert copy_file.relative_to(repo).as_posix() in naively_found, (
        "fixture is broken: expected the untracked worktree copy to be on disk and visible to a plain rglob"
    )


def test_green_iter_tracked_files_excludes_the_untracked_worktree_copy(tmp_path):
    """GREEN: `iter_tracked_files` answers from `git ls-files`, so the copy an
    agent worktree leaves under `.claude/worktrees/` — never committed — never
    appears, regardless of what the filesystem holds."""
    repo = _init_repo(tmp_path)
    _plant_untracked_worktree_copy(repo)

    found = {p.relative_to(repo).as_posix() for p in iter_tracked_files(repo, "*.py")}

    assert found == {"ai/gateway/adapters.py"}
    assert not any(".claude" in rel for rel in found)


def test_iter_tracked_files_falls_back_to_a_filtered_walk_without_git(tmp_path, monkeypatch):
    """If `git` itself is unavailable (an exported tree, no `.git`), the helper
    still answers rather than silently returning nothing — by walking the
    filesystem but excluding the same directories a tracked-only answer would
    have skipped."""
    root = tmp_path / "no_git"
    (root / "ai").mkdir(parents=True)
    (root / "ai" / "real.py").write_text("REAL = 1\n", encoding="utf-8")
    (root / ".claude" / "worktrees" / "agent-x").mkdir(parents=True)
    (root / ".claude" / "worktrees" / "agent-x" / "copy.py").write_text("COPY = 1\n", encoding="utf-8")
    (root / ".venv" / "lib").mkdir(parents=True)
    (root / ".venv" / "lib" / "vendored.py").write_text("VENDORED = 1\n", encoding="utf-8")

    def _fake_run(*_args, **_kwargs):
        raise FileNotFoundError("git not found")

    monkeypatch.setattr("scripts.repo_scan.subprocess.run", _fake_run)

    found = {p.relative_to(root).as_posix() for p in iter_tracked_files(root, "*.py")}

    assert found == {"ai/real.py"}


def test_iter_tracked_files_never_silently_scans_nothing_on_the_real_repo():
    """A helper that quietly returns an empty list would make every scanner
    built on it "pass" by seeing nothing to complain about — the F176 shape
    (a measurement that cannot fail). The real repository has hundreds of
    tracked .py files; this asserts the helper actually saw them."""
    found = list(iter_tracked_files(REPO_ROOT, "*.py"))
    assert len(found) > 200, f"expected a non-trivial number of tracked .py files, got {len(found)}"


def test_iter_tracked_files_on_the_real_repo_excludes_claude_worktrees():
    """Direct proof against the real tree: nothing `iter_tracked_files` returns
    lives under `.claude/worktrees/`, however many agent worktrees are checked
    out alongside this one right now.

    `.claude/` itself is NOT excluded wholesale — `.claude/skills/**` is
    genuinely committed, and a scanner that dropped it would be hiding real
    source, not agent-worktree noise. Only `.claude/worktrees/` is gitignored
    (see `.gitignore`), so only it must never appear.
    """
    found = list(iter_tracked_files(REPO_ROOT, "*.py"))
    offenders = [p for p in found if ".claude/worktrees" in p.relative_to(REPO_ROOT).as_posix()]
    assert offenders == []
    # And the exclusion is specific, not a side effect of dropping all of
    # .claude/ -- confirm real, committed files under .claude/ still surface.
    assert any(".claude/skills" in p.relative_to(REPO_ROOT).as_posix() for p in found)
