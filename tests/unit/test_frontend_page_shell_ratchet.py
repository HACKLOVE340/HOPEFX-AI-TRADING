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


#: A router that mounts three of the four files below. `Panel` is deliberately
#: absent: it stands for the `settings/*Section` and `superadmin/*Section`
#: files, which render inside another page and must never be measured as pages.
APP = """
const Alpha = lazy(() => import('./pages/Alpha'));
const Beta  = lazy(() => import('./pages/Beta'));
const Gamma = lazy(() => import('./pages/Gamma'));
"""


def _router(root: Path, source: str = APP) -> None:
    app = root / "frontend" / "src"
    app.mkdir(parents=True, exist_ok=True)
    (app / "App.tsx").write_text(source, encoding="utf-8")


@pytest.fixture()
def tree(tmp_path: Path):
    pages = tmp_path / "pages"
    pages.mkdir()
    (pages / "Alpha.tsx").write_text(OFF_SHELL, encoding="utf-8")
    (pages / "Beta.tsx").write_text(OFF_SHELL, encoding="utf-8")
    (pages / "Gamma.tsx").write_text(ON_SHELL, encoding="utf-8")
    # Off the shell AND not routed — a panel. It must not be counted.
    (pages / "Panel.tsx").write_text(OFF_SHELL, encoding="utf-8")
    _router(tmp_path)
    return pages, tmp_path / "record.json"


def test_a_file_that_is_not_routed_is_not_a_page(tree):
    """Half the recorded debt was never a page.

    Measured on the real tree 2026-09-14: of 80 files reported as pages off the
    shell, 40 were `settings/*Section` or `superadmin/*Section` panels and two
    were component libraries. NONE is mounted on a `<Route>` — `Settings.tsx`
    alone renders 40 of them as tab content — so putting one on the shell would
    give a tab panel its own page header, a second width constraint inside an
    already-constrained page, and a "Where to next" footer in the middle of it.

    The figure could therefore be improved by making the interface worse, which
    is the shape this repository calls a dead control. A page is what the router
    mounts.
    """
    pages, record = tree
    mod = _load(pages, record)
    measured = mod.measure()
    assert "pages/Panel.tsx" not in measured, "a file the router never mounts was counted as a page off the shell"
    assert sorted(measured) == ["pages/Alpha.tsx", "pages/Beta.tsx"], measured


def test_a_page_reachable_signed_out_is_not_measured(tmp_path: Path):
    """PageShell's footer is the authenticated navigation.

    `/privacy`, `/terms`, `/risk-disclosure` and `/pricing` are mounted outside
    `<AppShell />` — App.tsx's own comment says "anonymous visitors still reach
    the page". Offering such a reader "Where to next: Portfolio, Risk
    Calculator" is worse than offering nothing, so these must never be counted
    as debt. Three of them were, because the exemption was a hand-typed list
    that had fallen behind.
    """
    pages = tmp_path / "pages"
    pages.mkdir()
    (pages / "Alpha.tsx").write_text(OFF_SHELL, encoding="utf-8")
    (pages / "Legal.tsx").write_text(OFF_SHELL, encoding="utf-8")
    _router(
        tmp_path,
        "const Alpha = lazy(() => import('./pages/Alpha'));\n"
        "const Legal = lazy(() => import('./pages/Legal'));\n"
        "<Routes>\n"
        '  <Route path="/legal" element={<Legal />} />\n'
        '  <Route path="/*" element={<AppShell />} />\n'
        "</Routes>\n",
    )
    mod = _load(pages, tmp_path / "record.json")
    assert mod._public_pages() == {"Legal"}
    measured = mod.measure()
    assert "pages/Legal.tsx" not in measured, "a signed-out page was counted as debt"
    assert "pages/Alpha.tsx" in measured


def test_the_ratio_counts_the_same_population_it_measures(tmp_path: Path):
    """Numerator and denominator were two comprehensions, and drifted.

    The printed ratio read `37 of 72` while the real population was 63: one had
    been corrected and the other had not. They share one predicate now.
    """
    pages = tmp_path / "pages"
    pages.mkdir()
    (pages / "Alpha.tsx").write_text(OFF_SHELL, encoding="utf-8")
    (pages / "Gamma.tsx").write_text(ON_SHELL, encoding="utf-8")
    (pages / "Panel.tsx").write_text(OFF_SHELL, encoding="utf-8")  # not routed
    _router(
        tmp_path,
        "const Alpha = lazy(() => import('./pages/Alpha'));\nconst Gamma = lazy(() => import('./pages/Gamma'));\n",
    )
    mod = _load(pages, tmp_path / "record.json")
    routed, public = mod._routed_pages(), mod._public_pages()
    counted = [p for p in pages.rglob("*.tsx") if mod._is_page(p, routed, public)]
    assert {p.name for p in counted} == {"Alpha.tsx", "Gamma.tsx"}
    assert set(mod.measure()) == {"pages/Alpha.tsx"}
    assert len(mod.measure()) <= len(counted), "more pages off the shell than pages"


def test_it_refuses_to_report_a_figure_when_it_can_find_no_router(tmp_path: Path):
    """A scan that matches nothing agrees with every assertion.

    With no App.tsx the routed set is empty, and "no page is off the shell" and
    "the scan broke" would render identically — as success.
    """
    pages = tmp_path / "pages"
    pages.mkdir()
    (pages / "Alpha.tsx").write_text(OFF_SHELL, encoding="utf-8")
    mod = _load(pages, tmp_path / "record.json")
    with pytest.raises(SystemExit) as exc:
        mod.measure()
    assert "named no page modules" in str(exc.value)


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

    # A file that exists but is not mounted is not a page yet, so it is not
    # counted — and nothing is lost by that, because the gate catches it the
    # moment it becomes one. Both halves are asserted, because "not counted"
    # would otherwise be indistinguishable from a hole.
    (pages / "Delta.tsx").write_text(OFF_SHELL, encoding="utf-8")
    assert "pages/Delta.tsx" not in mod.measure(), (
        "a file the router does not mount is not a page; counting it is what let 40 tab panels into this record"
    )

    _router(pages.parent, APP + "const Delta = lazy(() => import('./pages/Delta'));\n")
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

    # The floor belongs on the POPULATION, not on the debt.
    #
    # It read `len(files) > 40` — a floor on how much work is left, which holds
    # only until the work succeeds. It broke the moment the scan was corrected
    # to count routed pages instead of every file under `pages/` (80 -> 38), and
    # it would break again on the day the last page is migrated, reporting a
    # finished job as a broken scanner. What actually distinguishes "nothing is
    # wrong" from "nothing was measured" is whether the scan found any pages AT
    # ALL, so that is what is asserted.
    spec = importlib.util.spec_from_file_location("page_shell_real", SCRIPT)
    assert spec and spec.loader
    live = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(live)
    routed = live._routed_pages()
    assert len(routed) > 50, f"the router names only {len(routed)} page modules — the scan is broken, or App.tsx moved"
    assert len(files) <= len(routed), "more pages recorded than the router mounts"
    for rel in files:
        assert (REPO / rel).exists(), f"{rel} is recorded but does not exist"
        assert "PageShell" not in (REPO / rel).read_text(encoding="utf-8"), (
            f"{rel} is on the shell and must leave the record"
        )
