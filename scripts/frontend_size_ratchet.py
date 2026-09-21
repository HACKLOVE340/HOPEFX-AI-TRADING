#!/usr/bin/env python3
# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""Sizes the density control cannot reach may only decrease.

## The defect this holds

`PageSurface` stamps `data-density` on every route and `index.css` fully
specifies three tiers — `comfortable` / `promax` / `ultra` — across eleven
tokens each. All of that is true, and on most pages it changes nothing, because
a literal pixel is not in the cascade:

    style={{ fontSize: 12 }}      no tier can change this
    className="p-4 gap-3"         nor this

That is `DENSITY-CANNOT-REACH` in the correction register, and it is the same
defect as the colour literals in the size dimension: a control that exists, is
documented accurately, and never runs.

## Why a ratchet, and why now

The colour side has had a codemod and a ratchet since 2026-09-14, and the
ratchet is the half that made the codemod worth running — without it the count
grows back while the decisions are being made.

The size side has had only the codemod (`frontend_size_codemod.py`), which
retired 763 call sites and then stopped, because what remains needs a DECISION
rather than a substitution: 12px appears 638 times and 11px 532 times, and both
sit BETWEEN type-scale tokens. Rounding 638 sites by a pixel would abandon the
codemod's entire safety argument, which is that nothing moves at the default
density. That decision is the owner's.

Keeping the number from growing while it is made is not the owner's decision,
and is what this does. `FRONTEND_HANDOVER.md` named it as the next step: "A size
ratchet (mirroring frontend_colour_ratchet.py) would stop the count growing
while this is decided. It does not exist yet."

## The rule, same as the colour and page-shell ratchets

    recorded + same count        -> passes
    recorded + MORE sizes        -> blocks
    NOT recorded + any size      -> blocks (a new file is where new debt arrives)
    recorded + zero sizes now    -> BLOCKS, with one instruction: delete the
                                    line. An entry that no longer describes
                                    anything is how a ratchet stops being one.

## One counter, not two

`count_split()` here is the ONLY definition of what counts, and
`scripts/correction_register.py::_p_density_cannot_reach` calls it rather than
keeping its own regexes. Two counters of the same population drift at the first
edit — `frontend_page_shell_ratchet` had exactly that bug and printed "37 of 72"
against a real population of 63.

## Usage

    python scripts/frontend_size_ratchet.py --report
    python scripts/frontend_size_ratchet.py --adopt
    python scripts/frontend_size_ratchet.py --check
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import NamedTuple

# An inline pixel font size. Deliberately the same shape the register's probe
# used, and deliberately NOT the codemod's pattern: the codemod requires a
# terminator so it never rewrites `fontSize: 13 + offset`, because rewriting an
# expression is unsafe. COUNTING that site is not unsafe, and it is debt either
# way — the density control cannot reach `13 + offset` either.
_SIZE_RE = re.compile(r"fontSize:\s*[0-9]")

# Tailwind's numeric spacing utilities. `p-card`, `gap-grid` and the rest of the
# token-reading classes are the goal, not the debt, so only the numeric forms
# are counted.
_SPACE_RE = re.compile(r"\b(?:p|px|py|gap)-[0-9]+\b")

# The utilities that DO read the token layer. Counted for the report, never
# against the baseline: this is the number that should rise.
_TOKEN_RE = re.compile(r"\b(p-card|p-row|gap-grid|text-body|text-value|text-title|text-label|text-micro)\b")

SCANNED_SUFFIXES = (".tsx",)

BASELINE_REL = Path("docs") / "FRONTEND_SIZE_DEBT.json"


# A line whose first non-space character opens or continues a comment is prose,
# and prose is not debt. This repository has been bitten twice by a scanner that
# could not tell the two apart: `security/code_analyzer.py`'s `nan_leak` rule
# scanned docstrings as source (F255), and `scripts/verify_skill_claims.py` then
# called four correct files broken because each carried a comment quoting the
# defect it fixed (F257). A ratchet is the worst place for it — a file gets a
# line in the baseline for explaining itself, and the explanation can never be
# retired because there is nothing to convert.
#
# Measured when this was added: one such line existed, and it is the shape
# exactly —
#
#     // The dismiss control was a 14px icon in p-1 — about 22px square, half the
#
# in `frontend/src/test/presence_anywhere_overlay.test.tsx`, which held a place
# in the baseline for a sentence about a size it had already fixed. The file
# leaves the record entirely and the total falls by one.
_COMMENT_RE = re.compile(r"^\s*(?://|/?\*)")


def _code(text: str) -> str:
    """`text` with whole-line comments removed."""
    return "\n".join(line for line in text.splitlines() if not _COMMENT_RE.match(line))


def _frontend_src(root: Path) -> Path:
    return root / "frontend" / "src"


def count_sizes(root: Path) -> dict[str, int]:
    """Map repo-relative path -> unreachable-size count, omitting files with none."""
    src = _frontend_src(root)
    counts: dict[str, int] = {}
    if not src.is_dir():
        return counts
    for path in sorted(src.rglob("*")):
        if not path.is_file() or path.suffix not in SCANNED_SUFFIXES:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        code = _code(text)
        n = len(_SIZE_RE.findall(code)) + len(_SPACE_RE.findall(code))
        if n:
            counts[path.relative_to(root).as_posix()] = n
    return counts


def count_split(root: Path) -> tuple[int, int, int]:
    """(token-reading utilities, inline fontSize, numeric spacing utilities).

    The register's DENSITY-CANNOT-REACH probe calls this, so the figure it
    prints and the figure this gate holds cannot disagree.
    """
    src = _frontend_src(root)
    tokens = sizes = space = 0
    if not src.is_dir():
        return (0, 0, 0)
    for path in sorted(src.rglob("*.tsx")):
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        code = _code(text)
        tokens += len(_TOKEN_RE.findall(code))
        sizes += len(_SIZE_RE.findall(code))
        space += len(_SPACE_RE.findall(code))
    return (tokens, sizes, space)


# ── the display band ─────────────────────────────────────────────────────────
#
# `--fs-hero` is 26px at `ultra` — the tier `frontend/src/lib/densityPref.ts`
# gives a person by default, and the tier `frontend_size_codemod.py` is anchored
# to. So a literal of 28px or more is beyond the top of the type scale: no token
# can reach it, and none is being added by a substitution.
#
# The obvious next move is to extend the scale with a `--fs-display` tier and
# convert the band. Measured on 2026-09-18 that is wrong for most of it: the
# majority of these sites size an EMOJI, where `fontSize` is the only lever a
# glyph has. Each one disappears when `frontend_emoji_ratchet.py` does its job
# and the emoji becomes an SVG sized by `width`/`height` — at which point a
# `--fs-display` token minted to reach it has no callers and no reason.
#
# So the band is CLASSIFIED, not just counted, and the classification is
# measured on every run rather than remembered from this comment.
DISPLAY_FLOOR = 28

_DISPLAY_RE = re.compile(r"fontSize:\s*(\d+)")

# Glyph blocks, deliberately narrower than "anything above U+2000". Four of the
# largest sites in this tree are OUTSIDE the emoji block proper — U+23F3 is
# Miscellaneous Technical, U+2622/U+2705 are Miscellaneous Symbols, U+2B50 is
# Miscellaneous Symbols and Arrows — so a classifier that knew only
# U+1F000-U+1FAFF would call them `type`. Widening further to Arrows and
# Mathematical Operators would go the other way and call a heading containing
# `->` a glyph, so the ranges stop short of those.
_GLYPH_RE = re.compile(
    "["
    "\u2300-\u23ff"  # Miscellaneous Technical  (hourglass, alarm clock)
    "\u2600-\u27bf"  # Miscellaneous Symbols + Dingbats
    "\u2b00-\u2bff"  # Miscellaneous Symbols and Arrows (star)
    "\ufe0f"  # variation selector-16 (emoji presentation)
    "\U0001f000-\U0001faff"
    "]"
)


class DisplaySite(NamedTuple):
    """One size beyond the top of the type scale, and what it is sizing."""

    path: str
    line: int
    px: int
    kind: str  # "glyph" | "type"


# A style object entry — `alertIcon: {` — whose `fontSize` sits on a later line.
_STYLE_KEY_RE = re.compile(r"^\s*([A-Za-z_$][\w$]*)\s*:\s*\{")

# A SCREAMING_SNAKE table named in a JSX child: `{STATUS_ICON[status]}`. Only
# this shape, because a lowercase identifier such as `meta` or `icon` appears
# all over a file and would make the second pass agree with everything.
_CHILD_TABLE_RE = re.compile(r"\{\s*([A-Z][A-Z0-9_]*)\b")

_STYLE_KEY_LOOKBACK = 6


# An icon sized by the cascade: `<ClipboardList size="1em" aria-hidden />`.
# `1em` writes straight into the SVG's width/height, so the surrounding
# `fontSize` is what sizes it — the declaration is load-bearing and is NOT a
# candidate for a type token.
_EM_ICON_RE = re.compile(r"<[A-Z]\w*\b[^>]*size=\"1em\"")


def _classify(window: str) -> str:
    """What is this font size actually sizing?

    Three answers, not two. `glyph` and `type` were the original pair; `icon`
    arrived the moment `frontend_emoji_codemod.py` converted a pictograph inside
    `style={{ fontSize: 32 }}` to a Lucide element at `size="1em"`. The
    declaration still does the sizing — it is now what makes the SVG 32px — but
    the glyph it used to size is gone, so a two-way classifier reads it as
    `type` and it starts arguing for a display token it has no use for. 27 sites
    moved that way in a single commit.
    """
    if _EM_ICON_RE.search(window):
        return "icon"
    return "glyph" if _GLYPH_RE.search(window) else "type"


def _names_this_site_is_reachable_by(lines: list[str], i: int) -> list[str]:
    """The style key holding this size, and any glyph table named in its child.

    A one-line window sees the glyph only when the glyph is beside the size.
    Three sites in this tree put it elsewhere — a style object used 160 lines
    away, and a `Record<string, string>` of emoji at the top of the file — and
    all three were counted as `type`, which is the expensive direction to be
    wrong in: `type` is the side that argues for a new token.
    """
    names: list[str] = []
    for back in range(_STYLE_KEY_LOOKBACK):
        j = i - back
        if j < 0:
            break
        m = _STYLE_KEY_RE.match(lines[j])
        if m:
            names.append(m.group(1))
            break
    names.extend(_CHILD_TABLE_RE.findall("\n".join(lines[i : i + 2])))
    return names


def _reclassify_by_name(lines: list[str], i: int) -> str:
    """Second pass: what does the thing that USES this site actually render?"""
    for name in _names_this_site_is_reachable_by(lines, i):
        # `s.alertIcon`, `styles.alertIcon`, `st['alertIcon']`, `const STATUS_ICON`
        use = re.compile(r"""(?:[.\['"]|\bconst\s+)""" + re.escape(name) + r"\b")
        for j, line in enumerate(lines):
            if j == i or not use.search(line):
                continue
            window = "\n".join(lines[max(0, j - 1) : j + 3])
            if _EM_ICON_RE.search(window):
                return "icon"
            if _GLYPH_RE.search(window):
                return "glyph"
    return "type"


def display_band(root: Path) -> list[DisplaySite]:
    """Every inline font size at or above `DISPLAY_FLOOR`, classified.

    The window is the matching line plus one either side, because the glyph is
    as often the JSX child on the next line as it is on the same one.
    """
    src = _frontend_src(root)
    out: list[DisplaySite] = []
    if not src.is_dir():
        return out
    for path in sorted(src.rglob("*.tsx")):
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except (UnicodeDecodeError, OSError):
            continue
        for i, line in enumerate(lines):
            if _COMMENT_RE.match(line):
                continue
            for m in _DISPLAY_RE.finditer(line):
                px = int(m.group(1))
                if px < DISPLAY_FLOOR:
                    continue
                window = "\n".join(lines[max(0, i - 1) : i + 2])
                kind = _classify(window)
                if kind == "type":
                    kind = _reclassify_by_name(lines, i)
                out.append(DisplaySite(path.relative_to(root).as_posix(), i + 1, px, kind))
    return out


def display_split(root: Path) -> dict[str, int]:
    """{"glyph": n, "type": m} over the display band."""
    split = {"glyph": 0, "icon": 0, "type": 0}
    for site in display_band(root):
        split[site.kind] += 1
    return split


def load_baseline(root: Path) -> dict[str, int]:
    path = root / BASELINE_REL
    if not path.exists():
        return {}
    return dict(json.loads(path.read_text(encoding="utf-8")).get("files", {}))


def adopt(root: Path) -> int:
    counts = count_sizes(root)
    tokens, sizes, space = count_split(root)
    path = root / BASELINE_REL
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "_comment": (
                    "Inline `fontSize: <n>` and numeric Tailwind spacing utilities per file "
                    "in frontend/src — the sizes the density control cannot reach, because a "
                    "literal pixel is not in the cascade. This number may only FALL. A file "
                    "that reaches zero must have its line DELETED rather than left at 0: an "
                    "entry describing nothing is how a ratchet stops being one. See "
                    "scripts/frontend_size_ratchet.py and, for how to retire a size safely, "
                    "scripts/frontend_size_codemod.py --check."
                ),
                "_reachable": (
                    f"{tokens} token-reading utilities against {sizes} inline fontSize and "
                    f"{space} numeric spacing utilities. The first number is the one that "
                    "should rise; it is recorded here as context and is NOT ratcheted."
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
    print(f"frontend_size_ratchet: adopted {sum(counts.values())} sizes across {len(counts)} files")
    return 0


def check(root: Path) -> int:
    current = count_sizes(root)
    baseline = load_baseline(root)

    if not baseline:
        print("frontend_size_ratchet: no baseline — run --adopt", file=sys.stderr)
        return 1

    failures: list[str] = []
    improved = 0

    for rel, now in sorted(current.items()):
        was = baseline.get(rel)
        if was is None:
            failures.append(
                f"{rel}: {now} unreachable size(s) in a file with no baseline entry. "
                f"Use the type-scale and spacing tokens (text-body, text-value, p-card, "
                f"gap-grid, …) — a literal pixel is not in the cascade, so the density "
                f"setting cannot change it."
            )
        elif now > was:
            failures.append(
                f"{rel}: {now} unreachable sizes, up from {was}. This list may only shrink. "
                f"Reach for a token rather than raising the baseline."
            )
        elif now < was:
            improved += was - now

    for rel, was in sorted(baseline.items()):
        if rel not in current and (root / rel).exists():
            failures.append(
                f"{rel}: now has zero unreachable sizes (was {was}) and must leave the "
                f"record. Delete its line from {BASELINE_REL.as_posix()} — an entry that "
                f"no longer describes anything is how a ratchet quietly stops being one."
            )

    total_now = sum(current.values())
    total_was = sum(baseline.values())
    print(f"frontend_size_ratchet: {total_now} unreachable size(s) across {len(current)} files (baseline {total_was})")
    if improved:
        print(
            f"frontend_size_ratchet: {improved} size(s) retired since the baseline — run --adopt to bank the progress"
        )

    split = display_split(root)
    band = sum(split.values())
    if band:
        head = (
            f"frontend_size_ratchet: {band} of those are beyond the type scale "
            f"(>= {DISPLAY_FLOOR}px, above --fs-hero at ultra) — "
            f"{split['glyph']} sizing a glyph, {split['icon']} sizing an icon at 1em, "
            f"{split['type']} sizing type."
        )
        if split["type"]:
            tail = (
                " The glyph side belongs to frontend_emoji_ratchet.py: its sizes vanish when "
                "the emoji becomes an SVG. Only the type side is an argument for extending the "
                "scale, and --fs-display-sm / --fs-display / --fs-display-lg already exist — "
                "assign one by ROLE, by hand. The codemod's tables deliberately exclude these "
                "sizes, because a bulk rewrite cannot tell a glyph from type."
            )
        else:
            tail = (
                " Every typographic site in the band reaches a token. What is left sizes a "
                "glyph or an icon: the glyph side disappears with the emoji rather than being "
                "converted, and the icon side is load-bearing \u2014 it is what makes the SVG that "
                "size. python scripts/frontend_emoji_ratchet.py --check"
            )
        print(head + tail)

    if failures:
        print(f"\nfrontend_size_ratchet: {len(failures)} file(s) moved the wrong way:", file=sys.stderr)
        for f in failures:
            print(f"  {f}", file=sys.stderr)
        print(
            "\nWhy this blocks: the density control is stamped on every route and cannot "
            "change a literal pixel, so every added literal makes a live control slightly "
            "more dead. See scripts/frontend_size_ratchet.py and "
            "`python scripts/correction_register.py --id DENSITY-CANNOT-REACH`.",
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
    ap.add_argument("files", nargs="*", help=argparse.SUPPRESS)
    args = ap.parse_args(argv)

    root = Path(args.root).resolve() if args.root else Path(__file__).resolve().parents[1]

    if args.report:
        print(
            json.dumps(
                {
                    "files": count_sizes(root),
                    "display_band": {
                        "floor_px": DISPLAY_FLOOR,
                        "split": display_split(root),
                        "sites": [s._asdict() for s in display_band(root)],
                    },
                },
                indent=1,
                sort_keys=True,
            )
        )
        return 0
    if args.adopt:
        return adopt(root)
    return check(root)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
