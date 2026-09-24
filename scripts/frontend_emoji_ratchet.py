#!/usr/bin/env python3
# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""Emoji in `frontend/src` may only decrease.

## Why this exists

`navConfig.ts` already carries the reasoning, written when the sidebar's icons
were replaced with Lucide components (F170):

> Emoji render differently on every OS, cannot inherit `currentColor` so they
> ignore theme/hover/disabled state, are announced literally by screen readers,
> and cannot sit on the optical grid.

`.claude/skills/ui-ux-pro-max` states the rule flatly — *"Use SVG icons, not
emojis"* — and lists it among the things that make a UI read as unprofessional.

The sidebar was fixed. The rest of the frontend was not, and on 2026-09-13 still
carried **1,407 emoji across 154 files**. The concentration says what they are
being used for: `PlatformConfiguration.tsx` alone has 136, `Settings.tsx` 52,
`SystemReliabilitySection.tsx` 62 — these are section icons, status glyphs and
button affordances, i.e. exactly the icon role the rule is about.

`CommandPalette.tsx` had 60 until this commit, in a hand-maintained navigation
list sitting directly beneath its own `import { NAV_ITEMS }` — which carries a
Lucide component per entry. That list had drifted (F175): `Dashboard` pointed at
`/home`, `2FA Setup` pointed at `/2fa` which is not a route, and eleven pages
added to the sidebar since were not offered at all. The emoji were the visible
symptom of a duplicate source of truth.

## What this is, and is not

Converting 154 files is a codemod and the owner's call. This is not that. It
records today's count per file and refuses to let it grow, so that when the
conversion happens it stays done — a cleanup with no ratchet behind it is undone
within a month.

The rules mirror `scripts/frontend_colour_ratchet.py` exactly, deliberately: a
second ratchet with different semantics is a second thing to remember.

    recorded + fewer emoji than recorded  -> passes (progress)
    recorded + same count                 -> passes
    recorded + MORE emoji                 -> blocks
    NOT recorded + any emoji              -> blocks (a new file is where new
                                             debt actually arrives)
    recorded + zero emoji now             -> BLOCKS, with one instruction:
                                             delete the line. An entry that no
                                             longer describes anything is how a
                                             ratchet quietly stops being one.

## What counts as an emoji, and what deliberately does not

Whole Unicode ranges, chosen so that the glyphs used in the ICON role are in
and the ones used as text are out. It is a range sweep, not a presentation test
— the distinction matters, and this paragraph used to get it wrong.

It said "only ranges whose characters have emoji presentation", which is not
what the code does: `☀-➿` takes in the whole of Miscellaneous Symbols and
Dingbats, including `✓ ✕ ✗`, which have TEXT presentation by default — no
variation selector, no colour, set in the page's font. 70 of those were in the
tree while the docstring promised they were not counted, so a contributor who
read this and reached for `✓` was blocked by a gate documented not to block.

They stay counted and this paragraph was corrected instead, because the ROLE is
what the rule is about: `✕` is a close button and `✓` is a status mark, and both
should be an SVG for the same reasons a pictograph should.
`tests/unit/test_frontend_emoji_ratchet.py::test_text_presentation_dingbats_are_counted`
now pins that, so the two cannot disagree again.

What is genuinely out is everything in the neighbouring blocks, because it is
legitimate UI text and counting it would make the gate absurd:

* `─ │ ├ ┤` (U+2500 block) — 79,148 occurrences, all of them comment banners in
  this repository. A regex that swept "symbols" would report eighty thousand
  violations and be switched off within the hour.
* `→ ← ↑ ↓ ↵ ▲ ▼ ▶ ⌘ ≈ ≥ ●` — arrows, key glyphs and maths. `⌘K` is the correct
  way to write that shortcut; an SVG would be worse.

Included beyond the two obvious blocks: regional-indicator flags
(U+1F1E6–U+1F1FF), the emoji-presentation media and clock controls
(U+23E9–U+23FA, e.g. `⏳ ⏸ ⏱`), and the handful of pictographs stranded in
U+2B05–U+2B55 (`⬇ ⭐ ⬛`).

U+FE0F, the variation selector that forces emoji presentation, is *not* counted
separately — it always follows a base character that already is.

## What the ratchet cannot express

A glyph in a **string context the browser renders itself** — `document.title`, a
`title` attribute, a desktop notification body — has no SVG alternative, because
there is no markup there. `features/chart-bot/hooks/useNuclearWS.ts` holds the
only one in the tree: a radiation glyph flashed into the page title on a
severity>=8 nuclear alert, which is precisely when the operator is likely to be
on another tab. That file stays in the baseline at 1 on purpose, and says so at
the call site. If a second such case appears, the honest fix is an explicit
exemption with a reason — not driving the count to zero by deleting a signal.

## Usage

    python scripts/frontend_emoji_ratchet.py --report   # counts, as JSON
    python scripts/frontend_emoji_ratchet.py --adopt    # write the baseline
    python scripts/frontend_emoji_ratchet.py --check    # the gate

`--check` is the pre-commit hook. It reads the whole tree rather than only the
staged files: the "delete the line when it reaches zero" rule cannot be
evaluated from a staged subset.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

#: See the module docstring for why each range is in, and why the arrows and
#: box-drawing characters beside them are out.
EMOJI_RE = re.compile(
    "["
    "\U0001f1e6-\U0001f1ff"  # regional indicators (flags)
    "\U0001f300-\U0001faff"  # pictographs, transport, supplemental
    "☀-➿"  # miscellaneous symbols and dingbats
    "⬅-⬇"  # ⬅ ⬆ ⬇
    "⬛⬜⭐⭕"  # ⬛ ⬜ ⭐ ⭕
    "⏩-⏺"  # media controls and clocks with emoji presentation
    "]"
)

SCANNED_SUFFIXES = (".tsx", ".ts", ".jsx", ".js", ".css")

#: Files whose emoji are the subject rather than the interface. The ratchet's
#: own tests write emoji on purpose; so does the test that asserts the palette
#: has none.
EXEMPT_PARTS = ("/test/", "/__tests__/")

BASELINE_REL = Path("docs") / "FRONTEND_EMOJI_DEBT.json"


def _frontend_src(root: Path) -> Path:
    return root / "frontend" / "src"


def _is_exempt(rel: str) -> bool:
    return any(part in rel for part in EXEMPT_PARTS)


def count_emoji(root: Path) -> dict[str, int]:
    """Map repo-relative path -> emoji count, omitting files with none."""
    src = _frontend_src(root)
    counts: dict[str, int] = {}
    if not src.is_dir():
        return counts
    for path in sorted(src.rglob("*")):
        if not path.is_file() or path.suffix not in SCANNED_SUFFIXES:
            continue
        rel = path.relative_to(root).as_posix()
        if _is_exempt(rel):
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        n = len(EMOJI_RE.findall(text))
        if n:
            counts[rel] = n
    return counts


def load_baseline(root: Path) -> dict[str, int]:
    path = root / BASELINE_REL
    if not path.exists():
        return {}
    return dict(json.loads(path.read_text(encoding="utf-8")).get("files", {}))


def adopt(root: Path) -> int:
    counts = count_emoji(root)
    path = root / BASELINE_REL
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "_comment": (
                    "Emoji per file in frontend/src. This number may only fall. See "
                    "scripts/frontend_emoji_ratchet.py for why emoji cannot serve as "
                    "icons, and for the rule that a file reaching zero must be DELETED "
                    "from this list rather than left at 0 — an entry describing nothing "
                    "is how a ratchet stops being one."
                ),
                "_total": sum(counts.values()),
                "files": counts,
            },
            indent=1,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    print(f"frontend_emoji_ratchet: adopted {sum(counts.values())} emoji across {len(counts)} files")
    return 0


def check(root: Path) -> int:
    current = count_emoji(root)

    # A baseline file that exists but holds an empty `files` map — the state
    # this repository reached on 2026-09-24, driving the count to genuine
    # zero — is not "no baseline". `load_baseline` returning `{}` in both
    # cases used to make `if not baseline` treat them the same and block a
    # correct, fully-adopted zero with "run --adopt", which had already been
    # run. The file's presence on disk is what distinguishes them.
    if not (root / BASELINE_REL).exists():
        print("frontend_emoji_ratchet: no baseline — run --adopt", file=sys.stderr)
        return 1

    baseline = load_baseline(root)

    failures: list[str] = []
    improved = 0

    for rel, now in sorted(current.items()):
        was = baseline.get(rel)
        if was is None:
            failures.append(
                f"{rel}: {now} emoji in a file with no baseline entry. Use a Lucide "
                f"component — `import {{ Check }} from 'lucide-react'` — as the sidebar "
                f"does. An emoji cannot inherit currentColor, so it ignores hover, "
                f"disabled and theme, and a screen reader announces it literally."
            )
        elif now > was:
            failures.append(
                f"{rel}: {now} emoji, up from {was}. This list may only shrink. Replace "
                f"the added emoji with a Lucide icon rather than raising the baseline."
            )
        elif now < was:
            improved += was - now

    for rel, was in sorted(baseline.items()):
        if rel not in current:
            path = root / rel
            if path.exists():
                failures.append(
                    f"{rel}: now has zero emoji (was {was}) and must leave the record. "
                    f"Delete its line from {BASELINE_REL.as_posix()} — an entry that no "
                    f"longer describes anything is how a ratchet quietly stops being one."
                )
            # A deleted file simply leaves; that is progress, not a violation.

    total_now = sum(current.values())
    total_was = sum(baseline.values())
    print(f"frontend_emoji_ratchet: {total_now} emoji across {len(current)} files (baseline {total_was})")
    if improved:
        print(f"frontend_emoji_ratchet: {improved} emoji removed since the baseline — run --adopt to bank the progress")

    if failures:
        print(f"\nfrontend_emoji_ratchet: {len(failures)} file(s) moved the wrong way:", file=sys.stderr)
        for f in failures:
            print(f"  {f}", file=sys.stderr)
        print(
            "\nWhy this blocks: emoji-as-icons is the one rule ui-ux-pro-max states "
            "flatly, and navConfig.ts records what it costs. See "
            "scripts/frontend_emoji_ratchet.py.",
            file=sys.stderr,
        )
        return 1

    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", default=None, help="repository root (default: this script's repo)")
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--report", action="store_true", help="print per-file counts as JSON")
    mode.add_argument("--adopt", action="store_true", help="write today's counts as the baseline")
    mode.add_argument("--check", action="store_true", help="fail if any count rose")
    # pre-commit passes staged filenames; the gate reads the whole tree, so
    # accept and ignore them rather than erroring on them.
    ap.add_argument("files", nargs="*", help=argparse.SUPPRESS)
    args = ap.parse_args(argv)

    root = Path(args.root).resolve() if args.root else Path(__file__).resolve().parents[1]

    if args.report:
        print(json.dumps(count_emoji(root), indent=1, sort_keys=True))
        return 0
    if args.adopt:
        return adopt(root)
    return check(root)


if __name__ == "__main__":
    raise SystemExit(main())
