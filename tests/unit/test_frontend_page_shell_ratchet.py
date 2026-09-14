# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""The page-shell ratchet must be able to refuse.

Rule 1 of this repository: a control that cannot fail is not a control. A
ratchet is the easiest kind to get wrong that way — it passes on a healthy
tree, which is also what a broken measurement does.

So each refusal below is driven against a real tree rather than asserted from
reading the source: the scanner is pointed at a temporary pages directory, and
the three transitions that matter are made to happen.

The fourth test is the sanity floor. `frontend_colour_ratchet` learned this the
hard way and `scripts/pre_commit_coverage.py` learned it twice: a glob that
stops matching reports zero findings, and zero findings from a ratchet is
indistinguishable from success unless something asserts the scan found a tree
at all.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts" / "frontend_page_shell_ratchet.py"


def _load(pages: Path, record: Path):
    """Import the module with its scan root pointed at a throwaway tree."""
    spec = importlib.util.spec_from_file_location("page_shell_ratchet", SCRIPT)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    # REPO too, not just PAGES: measure() keys its record by a path relative
    # to the repository root, and a tmp tree is not under it.
    mod.REPO = pages.parent
    mod.PAGES = pages
    mod.RECORD = record
    return mod


ON_SHELL = "import { PageShell } from '../components/system/PageShell';\nexport default function P() { return null; }\n"
OFF_SHELL = "export default function P() { return null; }\n"


@pytest.fixture()
def tree(tmp_path: Path):
    pages = tmp_path / "pages"
    pages.mkdir()
    (pages / "Alpha.tsx").write_text(OFF_SHELL, encoding="utf-8")
    (pages / "Beta.tsx").write_text(OFF_SHELL, encoding="utf-8")
    (pages / "Gamma.tsx").write_text(ON_SHELL, encoding="utf-8")
    return pages, tmp_path / "record.json"


def test_records_only_the_pages_that_are_off_the_shell(tree):
    pages, record = tree
    mod = _load(pages, record)
    measured = mod.measure()
    assert sorted(measured) == ["pages/Alpha.tsx", "pages/Beta.tsx"], measured
    assert "pages/Gamma.tsx" not in measured, "a page on the shell must not be recorded"


def test_refuses_a_new_page_that_skips_the_shell(tree):
    """Where new inconsistency actually arrives."""
    pages, record = tree
    mod = _load(pages, record)
    mod.save(mod.measure())

    (pages / "Delta.tsx").write_text(OFF_SHELL, encoding="utf-8")
    now, recorded = mod.measure(), mod.load()
    arrived = set(now) - set(recorded)
    assert arrived == {"pages/Delta.tsx"}, "a brand-new page off the shell must be refused, not absorbed"


def test_refuses_an_entry_that_no_longer_describes_anything(tree):
    """A page that reaches the shell must LEAVE the record.

    An entry describing nothing is how a ratchet quietly stops being one: it
    remains as a standing permission for a file that no longer needs it.
    """
    pages, record = tree
    mod = _load(pages, record)
    mod.save(mod.measure())

    (pages / "Alpha.tsx").write_text(ON_SHELL, encoding="utf-8")
    now, recorded = mod.measure(), mod.load()
    migrated = set(recorded) - set(now)
    assert migrated, "a migrated page must be reported so its line is deleted"


def test_a_reverted_migration_is_refused(tree):
    """The regression this gate exists to stop."""
    pages, record = tree
    mod = _load(pages, record)
    mod.save(mod.measure())

    # Gamma was on the shell and so was never recorded. Reverting it makes it
    # an unrecorded page that is off the shell — the same signal as a new one,
    # which is correct: both are a page without the standard frame.
    (pages / "Gamma.tsx").write_text(OFF_SHELL, encoding="utf-8")
    now, recorded = mod.measure(), mod.load()
    assert set(now) - set(recorded), "a reverted migration must be refused"


def test_the_real_record_describes_a_real_tree():
    """A sanity floor, against the committed record rather than a fixture.

    If this collapses the measurement broke, not the debt — the failure mode
    where a scanner that matches nothing reports a clean tree.
    """
    record = json.loads((REPO / "docs" / "FRONTEND_PAGE_SHELL_DEBT.json").read_text(encoding="utf-8"))
    files = record["files"]
    assert record["_total"] == len(files)
    assert len(files) > 40, "too few pages recorded — the scan probably matched nothing"
    for rel in files:
        assert (REPO / rel).exists(), f"{rel} is recorded but does not exist"
        assert "PageShell" not in (REPO / rel).read_text(encoding="utf-8"), (
            f"{rel} is on the shell and must leave the record"
        )
