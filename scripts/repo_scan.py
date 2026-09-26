# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
scripts/repo_scan.py
=====================
The one shared answer to "what files does this repository actually contain?",
for every scanner that used to walk the filesystem with `Path.rglob()` or
`os.walk()` and hand-roll its own exclusion list.

Why this exists
----------------
Agent worktrees live *inside* the repo directory, at `.claude/worktrees/`,
which `.gitignore` excludes — but a plain filesystem walk has no notion of
"tracked" and happily descends into them. That produced two real failures:

* `tests/unit/test_no_model_call_bypasses_the_gateway.py` failed twice because
  it scanned a copy of `ai/gateway/adapters.py` sitting inside
  `.claude/worktrees/agent-*/`, which another agent's worktree had checked out
  next to this one.
* `tests/unit/test_advanced_ai_is_superseded.py` walks the whole tree the same
  way, and slowed past its 120s `pytest-timeout` under load, because more
  worktrees on disk is more bytes to walk for a scan that should never have
  seen them.

Every hand-rolled skip list in this repository (`.venv`, `node_modules`,
`__pycache__`, ...) was written before `.claude/worktrees/` existed and would
need the same line added by hand in a dozen places, which is exactly how this
class of bug recurs. `git ls-files` is the one query that is right by
construction: an untracked file, wherever it sits, is never tracked, so it
never appears.

Usage
-----
    from scripts.repo_scan import iter_tracked_files

    python_files = iter_tracked_files(REPO_ROOT, "*.py")

This replaces `root.rglob(pattern)` one-for-one. Any additional, *semantic*
exclusion a scanner applies on top (skip `tests/`, skip `frontend/`, skip a
named false-positive file) is a decision about what the scan means, not about
what the filesystem holds, and stays in the caller.
"""

from __future__ import annotations

import pathlib
import subprocess

__all__ = ["REPO_ROOT", "iter_tracked_files"]

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent

#: Used only when `git` itself is unavailable (an exported tree with no
#: `.git`, or a sandboxed test that stubs `git` out). Kept as a last resort,
#: not the primary mechanism — see the module docstring for why a hand-rolled
#: list is the thing this helper exists to stop repeating.
_FALLBACK_EXCLUDED_PARTS = frozenset(
    {
        ".claude",
        ".git",
        ".venv",
        "venv",
        "node_modules",
        "__pycache__",
        "site-packages",
        "dist",
        "build",
        ".mypy_cache",
        ".pytest_cache",
    }
)


def _git_ls_files(root: pathlib.Path) -> list[str] | None:
    """Tracked files under `root`, as paths relative to `root`.

    Returns `None` — never an empty list — when `git` could not answer, so a
    caller can tell "git said there is nothing here" (a real, if unusual,
    answer) apart from "git could not be asked" (the fallback path).
    """
    try:
        result = subprocess.run(
            ["git", "-C", str(root), "ls-files", "-z", "--", "."],
            capture_output=True,
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    raw = result.stdout.decode("utf-8", errors="replace")
    return [p for p in raw.split("\0") if p]


def iter_tracked_files(root: pathlib.Path | str, pattern: str = "*") -> list[pathlib.Path]:
    """Every git-tracked file under `root` whose name matches `pattern`.

    The repo-wide-scanner-safe replacement for `pathlib.Path(root).rglob(pattern)`.
    An untracked copy of the repo sitting inside `root` — an agent worktree
    under `.claude/worktrees/`, a stray `.venv`, a `node_modules` — is never
    tracked, so it is never returned, with no exclusion list to maintain.

    `pattern` is matched with `PurePath.match`, so a bare pattern like
    `"*.py"` matches on the file's name regardless of depth, same as
    `rglob("*.py")` did.

    Falls back to a directory walk that excludes the well-known offender
    directories (see `_FALLBACK_EXCLUDED_PARTS`) when `git` itself cannot
    answer, so a caller still gets a real answer instead of silently seeing
    nothing — a scanner that scans zero files "passes" every check it runs,
    which is its own defect shape (see `.claude/skills/hopefx-dead-controls`).
    """
    resolved_root = pathlib.Path(root).resolve()
    tracked = _git_ls_files(resolved_root)
    if tracked is not None:
        return [p for p in (resolved_root / rel for rel in tracked) if p.match(pattern)]

    found: list[pathlib.Path] = []
    for path in resolved_root.rglob(pattern):
        if _FALLBACK_EXCLUDED_PARTS & set(path.parts):
            continue
        found.append(path)
    return found
