# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""The frontend colour ratchet must be able to fail.

The frontend page audit (2026-09-09) measured 7,340 hardcoded hex literals
across `frontend/src/pages` and `frontend/src/components`, 210 of them
distinct, against 58 uses of `var(--…)`. This ratchet's scope is all of
`frontend/src`, so its recorded total is higher — 8,021 across 202 files.
Three features are dead because of it: the light/dark toggle (no
`[data-theme="light"]` rule exists anywhere and exactly one `dark:` variant is
used), white-label brand colour (it cannot reach a surface built from
literals), and visual consistency (five different greys are doing "muted
text").

Replacing those literals is a codemod and an owner decision. This ratchet is
neither: it records today's count per file and refuses to let it grow, so the
codemod is worth doing and stays done.

Every test here exists because `hopefx-dead-controls` is about gates that read
correctly and never fire. A ratchet that cannot say no is a comment.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts" / "frontend_colour_ratchet.py"


def run(*args: str, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        capture_output=True,
        text=True,
        cwd=str(cwd or REPO),
        # The whole point is inspecting non-zero exits — a raising call would
        # turn every gate-blocks-correctly assertion into an error.
        check=False,
    )


@pytest.fixture
def project(tmp_path: Path) -> Path:
    """A miniature frontend with a known literal count."""
    src = tmp_path / "frontend" / "src"
    (src / "pages").mkdir(parents=True)
    (src / "pages" / "A.tsx").write_text(
        "export const A = () => <div style={{ color: '#64748b', background: '#1e293b' }} />;\n"
    )
    (src / "pages" / "B.tsx").write_text("export const B = () => <div style={{ color: 'var(--text)' }} />;\n")
    return tmp_path


# ── the measurement ───────────────────────────────────────────────────────────


def test_counts_hex_literals_per_file(project: Path):
    result = run("--report", "--root", str(project), cwd=project)
    assert result.returncode == 0, result.stderr
    counts = json.loads(result.stdout)
    assert counts["frontend/src/pages/A.tsx"] == 2
    # A file with no literals must be absent, not present with a zero.
    assert "frontend/src/pages/B.tsx" not in counts


def test_a_hex_inside_a_comment_still_counts(project: Path):
    """A literal in a comment is a literal someone will copy.

    Being clever about comments here would only teach contributors where the
    blind spot is. The ratchet counts the character sequence.
    """
    (project / "frontend" / "src" / "pages" / "C.tsx").write_text("// was #ff0000\n")
    counts = json.loads(run("--report", "--root", str(project), cwd=project).stdout)
    assert counts["frontend/src/pages/C.tsx"] == 1


def test_three_digit_and_eight_digit_hex_both_count(project: Path):
    (project / "frontend" / "src" / "pages" / "D.tsx").write_text("const a = '#fff'; const b = '#00ff00cc';\n")
    counts = json.loads(run("--report", "--root", str(project), cwd=project).stdout)
    assert counts["frontend/src/pages/D.tsx"] == 2


# ── the ratchet ───────────────────────────────────────────────────────────────


def test_adopt_then_check_passes(project: Path):
    assert run("--adopt", "--root", str(project), cwd=project).returncode == 0
    assert (project / "docs" / "FRONTEND_COLOUR_DEBT.json").exists()
    assert run("--check", "--root", str(project), cwd=project).returncode == 0


def test_a_new_literal_in_a_baselined_file_blocks(project: Path):
    run("--adopt", "--root", str(project), cwd=project)
    a = project / "frontend" / "src" / "pages" / "A.tsx"
    a.write_text(a.read_text().replace("/>;", "data-x='#abcdef' />;"))

    result = run("--check", "--root", str(project), cwd=project)
    assert result.returncode == 1, "adding a literal must block"
    assert "A.tsx" in result.stderr
    assert "3" in result.stderr and "2" in result.stderr


def test_a_literal_in_a_brand_new_file_blocks(project: Path):
    """A new file is where new debt actually arrives."""
    run("--adopt", "--root", str(project), cwd=project)
    (project / "frontend" / "src" / "pages" / "New.tsx").write_text("const c = '#123456';\n")

    result = run("--check", "--root", str(project), cwd=project)
    assert result.returncode == 1
    assert "New.tsx" in result.stderr


def test_removing_literals_passes(project: Path):
    run("--adopt", "--root", str(project), cwd=project)
    a = project / "frontend" / "src" / "pages" / "A.tsx"
    a.write_text(a.read_text().replace("'#64748b'", "'var(--text-muted)'"))
    assert run("--check", "--root", str(project), cwd=project).returncode == 0


def test_reaching_zero_requires_deleting_the_line(project: Path):
    """An entry that no longer describes anything is how a ratchet stops being one.

    Same rule the coverage gate enforces: the list may only shrink, and a file
    that is clean must leave it rather than sit there as permission.
    """
    run("--adopt", "--root", str(project), cwd=project)
    a = project / "frontend" / "src" / "pages" / "A.tsx"
    a.write_text("export const A = () => <div style={{ color: 'var(--text-muted)' }} />;\n")

    result = run("--check", "--root", str(project), cwd=project)
    assert result.returncode == 1, "a file that reached zero must be removed from the baseline"
    assert "A.tsx" in result.stderr
    assert "delete" in result.stderr.lower()


def test_the_recorded_total_is_reported(project: Path):
    run("--adopt", "--root", str(project), cwd=project)
    result = run("--check", "--root", str(project), cwd=project)
    assert "2" in result.stdout, result.stdout


# ── the real repository ───────────────────────────────────────────────────────


def test_the_committed_baseline_matches_the_tree():
    """The baseline in the repo describes the repo, today.

    If this fails, someone added colour literals without the hook installed.
    Run `python scripts/frontend_colour_ratchet.py --check` to see where.
    """
    baseline = REPO / "docs" / "FRONTEND_COLOUR_DEBT.json"
    if not baseline.exists():
        pytest.skip("baseline not adopted yet")
    result = run("--check")
    assert result.returncode == 0, result.stderr


def test_every_recorded_file_really_contains_what_the_record_claims():
    """A sanity check on the counter that does not go stale as the debt is paid.

    This asserted `total > 5000` — a floor set when the measurement was 8,021 on
    2026-09-09 — to catch the failure mode the coverage gate already had once,
    where a broken measurement read as 361 clean modules. The intent was right
    and the implementation was backwards: retiring colour literals is the WORK,
    so the check failed at 3,557 for the one reason that is not a defect. A floor
    under a number whose job is to fall forbids finishing, and the only ways past
    it are to weaken it or to stop — which is how a gate teaches people to route
    around gates. (The emoji ratchet's identical floor was corrected the same way
    on 2026-09-14; this one was still failing, and had been since the colour
    migration crossed it.)

    So assert the property the floor was standing in for: that the record
    describes the tree. Every recorded file exists and really does contain the
    number of literals recorded against it. A counter that broke and returned
    near-zero, or that drifted from the files it names, fails this at any debt
    level — including zero, where it passes vacuously and correctly, because
    there is then nothing left to describe.

    It checks the SCAN and the AGGREGATION, not the definition of a colour
    literal: it reuses the script's own `HEX_RE` and exemptions. The definition
    is held by the injection tests above.
    """
    baseline = REPO / "docs" / "FRONTEND_COLOUR_DEBT.json"
    if not baseline.exists():
        pytest.skip("baseline not adopted yet")

    sys.path.insert(0, str(REPO / "scripts"))
    try:
        from frontend_colour_ratchet import count_literals
    finally:
        sys.path.pop(0)

    recorded = json.loads(baseline.read_text())["files"]
    measured = count_literals(REPO)

    wrong = []
    for rel, n in recorded.items():
        if not (REPO / rel).exists():
            wrong.append(f"{rel}: recorded {n}, file does not exist")
        elif measured.get(rel) != n:
            wrong.append(f"{rel}: recorded {n}, tree has {measured.get(rel, 0)}")
    assert not wrong, "the record does not describe the tree:\n  " + "\n  ".join(wrong[:10])
    assert all(v > 0 for v in recorded.values()), "an entry recording zero describes nothing"
