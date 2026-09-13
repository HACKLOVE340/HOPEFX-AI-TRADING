# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""The frontend emoji ratchet must be able to fail.

`navConfig.ts` records why emoji cannot serve as icons (F170) — no
`currentColor`, per-platform rendering, announced literally by screen readers —
and the sidebar was converted to Lucide on that basis. The rest of the frontend
was not: 1,389 emoji across 145 files on 2026-09-13, concentrated exactly where
icons live (`PlatformConfiguration.tsx` 136, `SystemReliabilitySection.tsx` 62,
`Settings.tsx` 52).

Converting them is a codemod and an owner decision. This ratchet is neither: it
records today's count and refuses to let it grow.

Two groups of tests matter more than the rest.

**The injections** — every rule is exercised by introducing the defect and
asserting the refusal, because `hopefx-dead-controls` is about gates that read
correctly and never fire.

**The exclusions** — `test_box_drawing_and_arrows_are_not_emoji` is not a nicety.
This repository contains 79,148 box-drawing characters, nearly all of them
comment banners. A regex that swept "symbols" would report eighty thousand
violations on its first run and be switched off the same hour, and then the
gate protects nothing. The narrow range is what makes it survivable.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts" / "frontend_emoji_ratchet.py"


def run(*args: str, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        capture_output=True,
        text=True,
        cwd=str(cwd or REPO),
        # The whole point is inspecting non-zero exits.
        check=False,
    )


@pytest.fixture
def project(tmp_path: Path) -> Path:
    """A miniature frontend with a known emoji count."""
    src = tmp_path / "frontend" / "src"
    (src / "pages").mkdir(parents=True)
    (src / "pages" / "A.tsx").write_text(
        "export const A = () => <div>\U0001f4ca Stats ⚡ Fast</div>;\n",
        encoding="utf-8",
    )
    (src / "pages" / "B.tsx").write_text(
        "import { Zap } from 'lucide-react';\nexport const B = () => <Zap />;\n",
        encoding="utf-8",
    )
    return tmp_path


# ── the measurement ───────────────────────────────────────────────────────────


def test_counts_emoji_per_file(project: Path):
    result = run("--report", "--root", str(project), cwd=project)
    assert result.returncode == 0, result.stderr
    counts = json.loads(result.stdout)
    assert counts["frontend/src/pages/A.tsx"] == 2
    # A clean file must be absent, not present with a zero.
    assert "frontend/src/pages/B.tsx" not in counts


def test_box_drawing_and_arrows_are_not_emoji(project: Path):
    """The exclusion that makes the gate usable at all.

    79,148 box-drawing characters live in this repository's comment banners, and
    `→`, `↑↓`, `↵` and `⌘` are legitimate UI text — `⌘K` is the correct way to
    write that shortcut. A gate that flagged them would be switched off, and a
    gate that is switched off is the defect this whole skill set is about.
    """
    (project / "frontend" / "src" / "pages" / "Chrome.tsx").write_text(
        "// ─── Header ───\nexport const C = () => <div>⌘K → open ↑↓ navigate ↵ select ▲ ▼ ≈ ≥</div>;\n",
        encoding="utf-8",
    )
    counts = json.loads(run("--report", "--root", str(project), cwd=project).stdout)
    assert "frontend/src/pages/Chrome.tsx" not in counts


def test_flags_clocks_and_stranded_pictographs_count(project: Path):
    """The three ranges outside the two obvious blocks, each present in the tree."""
    (project / "frontend" / "src" / "pages" / "Edge.tsx").write_text(
        "const a = '\U0001f1fa\U0001f1f8'; const b = '⏳'; const c = '⭐'; const d = '⬇';\n",
        encoding="utf-8",
    )
    counts = json.loads(run("--report", "--root", str(project), cwd=project).stdout)
    # Two regional indicators make one flag; the ratchet counts characters.
    assert counts["frontend/src/pages/Edge.tsx"] == 5


def test_an_emoji_in_a_comment_still_counts(project: Path):
    """A glyph in a comment is a glyph the next contributor copies into JSX."""
    (project / "frontend" / "src" / "pages" / "D.tsx").write_text("// TODO: use ✅ here\n", encoding="utf-8")
    counts = json.loads(run("--report", "--root", str(project), cwd=project).stdout)
    assert counts["frontend/src/pages/D.tsx"] == 1


def test_test_files_are_exempt(project: Path):
    """The suite asserting the palette has no emoji necessarily contains one."""
    tdir = project / "frontend" / "src" / "test"
    tdir.mkdir()
    (tdir / "emoji.test.tsx").write_text("const EMOJI = '\U0001f4ca';\n", encoding="utf-8")
    counts = json.loads(run("--report", "--root", str(project), cwd=project).stdout)
    assert "frontend/src/test/emoji.test.tsx" not in counts


# ── the ratchet: each rule injected ───────────────────────────────────────────


def test_adopt_then_check_passes(project: Path):
    assert run("--adopt", "--root", str(project), cwd=project).returncode == 0
    assert (project / "docs" / "FRONTEND_EMOJI_DEBT.json").exists()
    assert run("--check", "--root", str(project), cwd=project).returncode == 0


def test_a_new_emoji_in_a_baselined_file_blocks(project: Path):
    run("--adopt", "--root", str(project), cwd=project)
    a = project / "frontend" / "src" / "pages" / "A.tsx"
    a.write_text(a.read_text(encoding="utf-8").replace("</div>", "\U0001f680</div>"), encoding="utf-8")

    result = run("--check", "--root", str(project), cwd=project)
    assert result.returncode == 1, "adding an emoji must block"
    assert "A.tsx" in result.stderr
    assert "3" in result.stderr and "2" in result.stderr


def test_an_emoji_in_a_brand_new_file_blocks(project: Path):
    """A new file is where new debt actually arrives."""
    run("--adopt", "--root", str(project), cwd=project)
    (project / "frontend" / "src" / "pages" / "New.tsx").write_text(
        "export const N = () => <span>\U0001f525</span>;\n", encoding="utf-8"
    )

    result = run("--check", "--root", str(project), cwd=project)
    assert result.returncode == 1
    assert "New.tsx" in result.stderr
    assert "lucide" in result.stderr.lower()


def test_removing_emoji_passes(project: Path):
    run("--adopt", "--root", str(project), cwd=project)
    a = project / "frontend" / "src" / "pages" / "A.tsx"
    a.write_text(a.read_text(encoding="utf-8").replace("⚡ ", ""), encoding="utf-8")
    assert run("--check", "--root", str(project), cwd=project).returncode == 0


def test_reaching_zero_requires_deleting_the_line(project: Path):
    """An entry that no longer describes anything is how a ratchet stops being one."""
    run("--adopt", "--root", str(project), cwd=project)
    (project / "frontend" / "src" / "pages" / "A.tsx").write_text(
        "import { BarChart3 } from 'lucide-react';\nexport const A = () => <BarChart3 />;\n",
        encoding="utf-8",
    )

    result = run("--check", "--root", str(project), cwd=project)
    assert result.returncode == 1, "a file that reached zero must be removed from the baseline"
    assert "A.tsx" in result.stderr
    assert "delete" in result.stderr.lower()


def test_a_deleted_file_simply_leaves(project: Path):
    run("--adopt", "--root", str(project), cwd=project)
    (project / "frontend" / "src" / "pages" / "A.tsx").unlink()
    assert run("--check", "--root", str(project), cwd=project).returncode == 0


def test_check_without_a_baseline_refuses(tmp_path: Path):
    (tmp_path / "frontend" / "src").mkdir(parents=True)
    result = run("--check", "--root", str(tmp_path), cwd=tmp_path)
    assert result.returncode == 1
    assert "no baseline" in result.stderr


# ── the real repository ───────────────────────────────────────────────────────


def test_the_committed_baseline_matches_the_tree():
    """The baseline in the repo describes the repo, today."""
    if not (REPO / "docs" / "FRONTEND_EMOJI_DEBT.json").exists():
        pytest.skip("baseline not adopted yet")
    result = run("--check")
    assert result.returncode == 0, result.stderr


def test_the_baseline_records_the_measured_scale():
    """A sanity floor: if this number collapses, the counter broke, not the debt.

    The same failure mode the coverage gate had once, where a broken measurement
    read as 361 clean modules. 1,389 was the measurement on 2026-09-13.
    """
    baseline = REPO / "docs" / "FRONTEND_EMOJI_DEBT.json"
    if not baseline.exists():
        pytest.skip("baseline not adopted yet")
    total = sum(json.loads(baseline.read_text())["files"].values())
    assert total > 900, f"baseline total {total} is far below the recorded 1,389 — check the counter"


def test_the_command_palette_left_the_record():
    """F175's evidence, asserted where it cannot quietly regress.

    CommandPalette.tsx carried 60 emoji in a hand-maintained navigation list
    that duplicated NAV_ITEMS and had drifted from it. It now derives from
    NAV_ITEMS and renders Lucide components, so it must not be in the baseline
    at all.
    """
    baseline = REPO / "docs" / "FRONTEND_EMOJI_DEBT.json"
    if not baseline.exists():
        pytest.skip("baseline not adopted yet")
    files = json.loads(baseline.read_text())["files"]
    assert "frontend/src/components/CommandPalette.tsx" not in files
