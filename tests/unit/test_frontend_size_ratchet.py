# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""The size ratchet must be able to refuse.

Rule 1 of this repository: a control that cannot fail is not a control, and a
ratchet is the easiest kind to get that wrong — it passes on a healthy tree,
which is exactly what a broken measurement also does.

So every refusal is driven against a real throwaway tree rather than asserted
from reading the source, and the last test is the sanity floor: a glob that
stops matching reports zero findings, and zero findings from a ratchet is
indistinguishable from success unless something asserts it scanned a tree at
all.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts" / "frontend_size_ratchet.py"


def _load():
    spec = importlib.util.spec_from_file_location("size_ratchet", SCRIPT)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _tree(tmp_path: Path, files: dict[str, str]) -> Path:
    src = tmp_path / "frontend" / "src"
    for rel, body in files.items():
        p = src / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(body, encoding="utf-8")
    return tmp_path


# Two unreachable sizes: one inline fontSize, one numeric spacing utility.
TWO = 'export default () => <div className="p-4" style={{ fontSize: 12 }} />;\n'
ONE = 'export default () => <div className="p-4" />;\n'
NONE = 'export default () => <div className="p-card" style={{ fontSize: "var(--fs-body)" }} />;\n'


def test_it_counts_both_populations(tmp_path):
    mod = _load()
    root = _tree(tmp_path, {"pages/A.tsx": TWO})
    assert mod.count_sizes(root) == {"frontend/src/pages/A.tsx": 2}


def test_a_token_reading_page_is_not_debt(tmp_path):
    mod = _load()
    root = _tree(tmp_path, {"pages/A.tsx": NONE})
    assert mod.count_sizes(root) == {}


def test_a_count_that_rose_blocks(tmp_path, capsys):
    mod = _load()
    root = _tree(tmp_path, {"pages/A.tsx": ONE})
    assert mod.adopt(root) == 0
    (root / "frontend" / "src" / "pages" / "A.tsx").write_text(TWO, encoding="utf-8")
    assert mod.check(root) == 1
    assert "up from 1" in capsys.readouterr().err


def test_a_new_file_with_any_size_blocks(tmp_path, capsys):
    mod = _load()
    root = _tree(tmp_path, {"pages/A.tsx": ONE})
    assert mod.adopt(root) == 0
    (root / "frontend" / "src" / "pages" / "B.tsx").write_text(TWO, encoding="utf-8")
    assert mod.check(root) == 1
    assert "no baseline entry" in capsys.readouterr().err


def test_a_file_that_reached_zero_must_leave_the_record(tmp_path, capsys):
    """The half a ratchet usually gets wrong. An entry left at 0 is a standing
    permission to add two sizes back without anything noticing."""
    mod = _load()
    root = _tree(tmp_path, {"pages/A.tsx": TWO})
    assert mod.adopt(root) == 0
    (root / "frontend" / "src" / "pages" / "A.tsx").write_text(NONE, encoding="utf-8")
    assert mod.check(root) == 1
    assert "must leave the record" in capsys.readouterr().err


def test_a_deleted_file_simply_leaves(tmp_path):
    """Progress, not a violation — and the reason the check above tests for the
    file's EXISTENCE rather than only for its absence from the counts."""
    mod = _load()
    root = _tree(tmp_path, {"pages/A.tsx": TWO, "pages/B.tsx": ONE})
    assert mod.adopt(root) == 0
    (root / "frontend" / "src" / "pages" / "A.tsx").unlink()
    assert mod.check(root) == 0


def test_an_unchanged_tree_passes(tmp_path):
    mod = _load()
    root = _tree(tmp_path, {"pages/A.tsx": TWO})
    assert mod.adopt(root) == 0
    assert mod.check(root) == 0


def test_a_fall_is_reported_but_does_not_block(tmp_path, capsys):
    mod = _load()
    root = _tree(tmp_path, {"pages/A.tsx": TWO})
    assert mod.adopt(root) == 0
    (root / "frontend" / "src" / "pages" / "A.tsx").write_text(ONE, encoding="utf-8")
    assert mod.check(root) == 0
    assert "run --adopt to bank the progress" in capsys.readouterr().out


def test_a_missing_baseline_blocks_rather_than_passing(tmp_path):
    """The failure mode that matters most: no baseline must not read as clean."""
    mod = _load()
    root = _tree(tmp_path, {"pages/A.tsx": TWO})
    assert mod.check(root) == 1


def test_an_empty_tree_with_no_baseline_blocks(tmp_path, capsys):
    """This test exists because an injection survived without it.

    Removing the `if not baseline` guard left all ten other tests green: with a
    populated tree every file then failed as "no baseline entry", so the check
    still returned 1 and nothing noticed. The guard's real job is the case those
    tests never reach — nothing scanned AND nothing recorded, where the loops
    below have no work and the function falls through to `return 0`. A moved or
    renamed `frontend/src` reads exactly like a clean tree, which is how a gate
    stops being one.
    """
    mod = _load()
    root = tmp_path  # no frontend/src at all
    assert mod.count_sizes(root) == {}
    assert mod.check(root) == 1
    assert "no baseline" in capsys.readouterr().err


def test_the_register_and_the_ratchet_count_the_same_population():
    """One counter, not two. The probe in correction_register.py imports
    `count_split` from here; if that import is ever replaced by a second set of
    regexes, these two numbers are free to drift apart."""
    mod = _load()
    _tokens, sizes, space = mod.count_split(REPO)
    assert sizes + space == sum(mod.count_sizes(REPO).values())


def test_the_committed_baseline_still_describes_the_tree():
    """The sanity floor, against the repository itself."""
    mod = _load()
    counts = mod.count_sizes(REPO)
    assert len(counts) > 50, "the scan stopped finding the frontend"
    baseline = json.loads((REPO / mod.BASELINE_REL).read_text(encoding="utf-8"))
    assert baseline["_total"] == sum(baseline["files"].values())
    assert mod.check(REPO) == 0
