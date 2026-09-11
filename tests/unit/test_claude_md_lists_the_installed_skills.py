# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""`CLAUDE.md`'s skill tables must match what is on disk, both directions.

The owner's standing instruction is to use the relevant skills on every task,
and `CLAUDE.md` is the only place the full set is enumerated. That makes the
list load-bearing in a specific way: **a skill nobody can see is a skill nobody
loads**, and a listed skill that no longer exists sends a reader to a dead path.

This drift is silent. Removing a directory does not touch `CLAUDE.md`, and
adding one does not either — the 2026-09-11 prune had to reconcile both lists by
hand, which is precisely the step that gets skipped next time.

Deliberately two assertions, not one count. A count matches when a skill is
added and another removed in the same commit, which is the case most likely to
go wrong.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

REPO = Path(__file__).resolve().parents[2]
SKILLS = REPO / ".claude" / "skills"

#: A skill row in one of CLAUDE.md's tables: `| \`name\` | when to use it |`.
_ROW = re.compile(r"^\| `([a-z0-9-]+)` \|", re.M)


def _named_in_claude_md() -> set[str]:
    return set(_ROW.findall((REPO / "CLAUDE.md").read_text(encoding="utf-8")))


def _installed() -> set[str]:
    return {p.parent.name for p in SKILLS.glob("*/SKILL.md")}


def test_the_skills_directory_is_not_empty() -> None:
    """Positive control. Both assertions below pass trivially against an empty
    directory and an unreadable CLAUDE.md — two empty sets agree perfectly."""
    installed = _installed()
    assert len(installed) > 20, f"only {len(installed)} skills found — the glob is wrong, not the repo"
    assert len(_named_in_claude_md()) > 20, "CLAUDE.md yielded almost no skill rows — the row pattern is wrong"


def test_every_skill_named_in_claude_md_exists() -> None:
    missing = sorted(_named_in_claude_md() - _installed())
    assert not missing, f"CLAUDE.md names skills that are not installed: {missing}"


def test_every_installed_skill_is_named_in_claude_md() -> None:
    unlisted = sorted(_installed() - _named_in_claude_md())
    assert not unlisted, f"installed but not listed in CLAUDE.md, so nothing will load them: {unlisted}"


def test_the_stated_count_matches_the_directory() -> None:
    """CLAUDE.md states the number in prose. Prose drifts faster than tables."""
    stated = re.search(r"holds \*\*(\d+)\*\* skills", (REPO / "CLAUDE.md").read_text(encoding="utf-8"))
    assert stated, "CLAUDE.md no longer states a skill count in the expected shape"
    assert int(stated.group(1)) == len(_installed())
