#!/usr/bin/env python3
# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""Pages not yet on the standard shell may only decrease.

## What was measured, 2026-09-14

Across `frontend/src/pages`, 74 page components:

  * **twelve different page widths** — 360, 420, 460, 480, 520, 700, 800, 900,
    1100, 1200, 1400, 1500 — each chosen once, with nothing to say which was
    right for what;
  * **31 of 74** used `PageHeader`, so 43 had no breadcrumb, no consistent
    title treatment, and nowhere standard for their actions;
  * **40 of 74** ended in nothing: no outbound link anywhere in the content
    area, so a reader could only leave by the sidebar.

That is what "the pages are not standard" means, precisely. The token layer
fixed the colours inside the frame; `components/system/PageShell.tsx` is the
frame.

## Why a ratchet rather than a rewrite

Rewriting 74 pages in one change is unreviewable, and this repository has
already learned what happens to a cleanup with no ratchet behind it: it is
undone within a month and the same defect returns with a fresh explanation.

So the rule is the one the colour, emoji and a11y ratchets use:

    recorded, and now on the shell    -> BLOCKS, with one instruction: delete
                                        the line. An entry describing nothing
                                        is how a ratchet stops being one.
    recorded, still not on the shell  -> passes
    NOT recorded, not on the shell    -> BLOCKS. A new page is where new
                                        inconsistency actually arrives, and a
                                        new page has no excuse: PageShell
                                        exists and is one import.

The dead-end half is NOT counted here, because it is already solved
structurally: `PageSurface` renders a derived footer for any page that does
not claim the slot, so a page cannot be a cul-de-sac whether or not it has
been migrated. See `no_page_is_a_dead_end.test.tsx`.

## Usage

    python scripts/frontend_page_shell_ratchet.py --check
    python scripts/frontend_page_shell_ratchet.py --adopt
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
PAGES = REPO / "frontend" / "src" / "pages"
RECORD = REPO / "docs" / "FRONTEND_PAGE_SHELL_DEBT.json"


# A page is a file the ROUTER mounts. Everything else under `pages/` renders
# inside another page's frame, and putting it on the shell would be the wrong
# change: a section rendered as a tab of Settings would gain a second page
# header, a second width constraint inside an already-constrained page, and a
# "Where to next" footer in the middle of a tab panel.
#
# This used to be a hand-typed list of eight names, and the list could not keep
# up. Measured 2026-09-14: of the 80 files it reported as pages off the shell,
# 40 were `settings/*Section` or `superadmin/*Section` panels and two were
# component libraries (`settings/ui.tsx`, `superadmin/ui.tsx`). ZERO of them
# are mounted on a `<Route>`; `Settings.tsx` alone renders 40 of them as tab
# content. So half the debt was not debt, and — the part that matters — the
# number could be improved by making the UI worse. A gate whose figure rewards
# the wrong change is the shape this repository calls a dead control.
def _routed_pages() -> set[str]:
    """Page modules reachable from a `<Route>`, read from App.tsx."""
    # Resolved from REPO at call time, not bound at import: the tests point REPO
    # at a throwaway tree, and a module-level path would keep reading this one.
    app = REPO / "frontend" / "src" / "App.tsx"
    text = app.read_text(encoding="utf-8") if app.exists() else ""
    # `const X = lazy(() => import('./pages/Foo'))` and plain imports alike.
    mods = set(re.findall(r"import\(\s*['\"]\./pages/([\w/]+)['\"]\s*\)", text))
    mods |= set(re.findall(r"from\s+['\"]\./pages/([\w/]+)['\"]", text))
    return {m.split("/")[-1] for m in mods}


def _public_pages() -> set[str]:
    """Pages mounted OUTSIDE `<AppShell />` — reachable without signing in.

    PageShell derives its footer from navConfig, which is the authenticated
    navigation, and renders a breadcrumb that assumes the app chrome. Neither
    belongs on a page an anonymous visitor reads: the privacy policy offering
    "Where to next: Portfolio, Risk Calculator" to someone who is not signed in
    is worse than offering nothing.

    App.tsx states this structurally — the public routes sit in the outer
    `<Routes>` block, ahead of `<Route path="/*" element={<AppShell />} />`, and
    that file's own comment says "anonymous visitors still reach the page". So
    read it from there rather than maintaining a second list by hand: the eight
    names that were hardcoded here had already fallen behind by three
    (PrivacyPolicy, TermsAndRiskDisclosure, PricingPage).
    """
    app = REPO / "frontend" / "src" / "App.tsx"
    if not app.exists():
        return set()
    text = app.read_text(encoding="utf-8")
    catch_all = text.find('path="/*"')
    if catch_all == -1:
        return set()
    start = text.rfind("<Routes>", 0, catch_all)
    if start == -1:
        return set()
    block = text[start:catch_all]
    return set(re.findall(r"element=\{<(\w+)\s*/?>", block))


# Routed, but deliberately not on the shell: a full-bleed surface, or a page
# where a breadcrumb and a "where to next" footer would be wrong.
# Six of the eight names that used to live here — LandingPage, Login, Register,
# ForgotPassword, ResetPassword and Onboarding — are now DERIVED by
# _public_pages(), along with the three the list had missed. What is left is the
# pair the router cannot tell you about.
EXEMPT = {
    "NotFound.tsx",  # a bare message; a breadcrumb to nowhere is worse
    "MobilePage.tsx",  # a full-bleed surface with no header by design
}


def _is_page(path: Path, routed: set[str], public: set[str]) -> bool:
    """One predicate for what this gate measures, used by BOTH the numerator and
    the denominator. They were two comprehensions and drifted apart at the first
    edit: the ratio printed 37 of 72 while the real population was 63."""
    if path.name in EXEMPT or path.name.endswith(".test.tsx"):
        return False
    if path.stem not in routed:
        return False  # renders inside another page's frame; see _routed_pages
    return path.stem not in public  # reachable signed-out; see _public_pages


def _on_shell(text: str) -> bool:
    return "PageShell" in text


def measure() -> dict[str, int]:
    """Pages NOT on the shell, by file name. The value is always 1 — this is a
    set, kept in the same shape as the other ratchets' records so the same
    tooling reads it."""
    out: dict[str, int] = {}
    routed = _routed_pages()
    public = _public_pages()
    if not routed:
        # A scan that matches nothing agrees with every assertion. Refuse rather
        # than report zero pages off the shell.
        raise SystemExit(
            "frontend_page_shell_ratchet: App.tsx named no page modules — the scan is "
            "wrong, or the router moved. Refusing to report a figure."
        )
    for path in sorted(PAGES.rglob("*.tsx")):
        if not _is_page(path, routed, public):
            continue
        rel = path.relative_to(REPO).as_posix()
        if not _on_shell(path.read_text(encoding="utf-8")):
            out[rel] = 1
    return out


def load() -> dict[str, int]:
    if not RECORD.exists():
        return {}
    return json.loads(RECORD.read_text(encoding="utf-8")).get("files", {})


def save(files: dict[str, int]) -> None:
    RECORD.write_text(
        json.dumps(
            {
                "_comment": (
                    "Page components not yet built on components/system/PageShell.tsx, as of "
                    "2026-09-14. This list may only SHRINK. A page that reaches the shell must "
                    "have its line DELETED — an entry that no longer describes anything is how a "
                    "ratchet quietly stops being one. A page NOT on this list and not on the "
                    "shell blocks: a new page is where new inconsistency arrives, and PageShell "
                    "is one import. See scripts/frontend_page_shell_ratchet.py."
                ),
                "_total": len(files),
                "files": dict(sorted(files.items())),
            },
            indent=1,
        )
        + "\n",
        encoding="utf-8",
    )


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--adopt", action="store_true")
    args = ap.parse_args()

    now = measure()
    recorded = load()
    # The denominator is the same population the numerator measures: routed
    # pages. Counting every file under `pages/` made the ratio flatter than the
    # truth by including 40 panels that must never be on the shell.
    _routed, _public = _routed_pages(), _public_pages()
    total_pages = len([p for p in PAGES.rglob("*.tsx") if _is_page(p, _routed, _public)])

    if args.adopt or not recorded:
        save(now)
        print(
            f"frontend_page_shell_ratchet: adopted {len(now)} page(s) off the shell "
            f"({total_pages - len(now)} of {total_pages} migrated)"
        )
        return 0

    migrated = sorted(set(recorded) - set(now))
    arrived = sorted(set(now) - set(recorded))

    print(
        f"frontend_page_shell_ratchet: {len(now)} page(s) off the shell "
        f"(baseline {len(recorded)}) · {total_pages - len(now)} of {total_pages} migrated"
    )

    if arrived:
        print("\nNot on the shell and not recorded — a new page, or a migration reverted:", file=sys.stderr)
        for f in arrived:
            print(f"  {f}", file=sys.stderr)
        print(
            "\nBuild it on components/system/PageShell.tsx. It gives the page one of the three "
            "standard widths, a consistent header, and a footer that is derived rather than "
            "forgotten.",
            file=sys.stderr,
        )
        return 1

    if migrated:
        print("\nThese pages reached the shell and must leave the record:", file=sys.stderr)
        for f in migrated:
            print(f"  {f}", file=sys.stderr)
        print("\nRun --adopt to bank the progress.", file=sys.stderr)
        return 1

    if len(now) < len(recorded):
        print("Progress is unbanked — run --adopt.", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
