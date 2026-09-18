#!/usr/bin/env python3
# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""Replace an emoji used as an icon with the Lucide element that means it.

## What this does, and what it deliberately does not

`scripts/frontend_emoji_ratchet.py` records the debt and refuses to let it grow.
Its docstring says converting the tree "is a codemod and the owner's call. This
is not that." The owner asked for it on 2026-09-18. This is that — for the half
that is mechanical.

The rule that makes it safe is narrow: **convert only a glyph that sits outside
every string literal, in a `.tsx` file.** A bare glyph in that position can only
be JSX children; anywhere else in TypeScript it would not parse. The failures
either side of that line are asymmetric, which is why it is drawn there:

* converting inside a string yields `'<Zap /> Plan'` — an eleven-character
  literal rendered to the user, silently, and shipped;
* refusing to convert costs nothing. The glyph stays in the ratchet, counted,
  and a human decides.

So roughly a third of the tree's emoji are out of reach here BY DESIGN, and
`--check` names each one and why:

* **a `label:` / `title:` string in a data array.** `{ id: 'report', label:
  '📊 Live Report' }` cannot hold an element until the component that renders it
  takes an icon. That is a component-API change, per component.
* **a regional-indicator flag.** Lucide has no flags. On Windows the pair
  already renders as the two letters, so the honest replacement is a country
  code, which is a content decision.
* **a face.** `😌 😰 😤` in the sentiment strip are a scale, not an icon set.
* **a whole-line comment.** Prose wants rewording; an element in a comment is
  dead text.

## Alignment

Lucide renders `<svg class="lucide …" stroke="currentColor">`, which is an
inline element and sits on the baseline — a glyph does not. `index.css` carries
one rule, `.lucide { vertical-align: -0.125em; }`, so 200 call sites do not each
carry an inline style. `currentColor` is the other half of the point: an emoji
cannot take the colour of the text it sits in, and this does.

## Size

Every emission is `size={13}`, which is `--fs-body` at `:root` — these glyphs
sit in body text. `--check` flags any line that also sets a `fontSize`, because
a glyph sized 40px in a hero block is not a 13px icon and wants a human.

## Usage

    python scripts/frontend_emoji_codemod.py --check   # what it would do
    python scripts/frontend_emoji_codemod.py --apply
"""

from __future__ import annotations

import argparse
import collections
import re
from pathlib import Path

#: Glyph -> Lucide component. Only glyphs whose icon meaning is unambiguous.
#: A glyph absent from here is reported by `--check`, never guessed at.
ICONS: dict[str, str] = {
    "⚠": "AlertTriangle",
    "✅": "CheckCircle2",
    "⚡": "Zap",
    "✓": "Check",
    "\U0001f4ca": "BarChart3",
    "✕": "X",
    "✗": "X",
    "❌": "XCircle",
    "\U0001f916": "Bot",
    "\U0001f4c8": "TrendingUp",
    "\U0001f4c9": "TrendingDown",
    "\U0001f6e1": "Shield",
    "\U0001f512": "Lock",
    "\U0001f513": "LockOpen",
    "\U0001f50d": "Search",
    "\U0001f50e": "Search",
    "⚙": "Settings",
    "\U0001f4e1": "RadioTower",
    "\U0001f527": "Wrench",
    "\U0001f6e0": "Wrench",
    "\U0001f4cb": "ClipboardList",
    "\U0001f501": "Repeat",
    "\U0001f504": "RefreshCw",
    "\U0001f4d3": "NotebookPen",
    "\U0001f6d1": "OctagonAlert",
    "☢": "Radiation",
    "⬇": "ArrowDownToLine",
    "⏳": "Hourglass",
    "\U0001f3c6": "Trophy",
    "\U0001f30d": "Globe",
    "\U0001f30e": "Globe",
    "\U0001f30f": "Globe",
    "\U0001f310": "Globe",
    "\U0001f514": "Bell",
    "\U0001f4bc": "Briefcase",
    "⏸": "Pause",
    "⏹": "Square",
    "⏭": "SkipForward",
    "⏱": "Timer",
    "\U0001f4ac": "MessageSquare",
    "\U0001f3af": "Target",
    "\U0001f52c": "Microscope",
    "\U0001f9e0": "Brain",
    "\U0001f441": "Eye",
    "\U0001f4b3": "CreditCard",
    "\U0001f4c5": "Calendar",
    "⭐": "Star",
    "★": "Star",
    "☆": "Star",
    "\U0001f50c": "Plug",
    "\U0001f5fa": "Map",
    "\U0001f5d1": "Trash2",
    "\U0001f465": "Users",
    "\U0001f464": "User",
    "\U0001f9d1": "User",
    "\U0001f4f7": "Camera",
    "\U0001f4f8": "Camera",
    "\U0001f4c4": "FileText",
    "\U0001f6d2": "ShoppingCart",
    "\U0001f91d": "Handshake",
    "\U0001f6a8": "Siren",
    "\U0001f3e6": "Landmark",
    "\U0001f3db": "Landmark",
    "❓": "HelpCircle",
    "\U0001f3a4": "Mic",
    "\U0001f399": "Mic",
    "\U0001f50a": "Volume2",
    "\U0001f508": "Volume1",
    "\U0001f680": "Rocket",
    "\U0001f4d0": "Ruler",
    "\U0001f517": "Link",
    "\U0001f4e7": "Mail",
    "⚔": "Swords",
    "\U0001f525": "Flame",
    "\U0001f56f": "Flame",
    "\U0001f6e2": "Fuel",
    "\U0001f4f1": "Smartphone",
    "\U0001f4f2": "Smartphone",
    "\U0001f4b0": "Banknote",
    "\U0001f4b9": "TrendingUp",
    "\U0001faaa": "IdCard",
    "\U0001f5c4": "Database",
    "⚖": "Scale",
    "⛔": "Ban",
    "\U0001f6ab": "Ban",
    "\U0001f550": "Clock",
    "\U0001f4ed": "Inbox",
    "\U0001f3ac": "Clapperboard",
    "\U0001f3a7": "Headphones",
    "\U0001f48e": "Gem",
    "\U0001f4de": "Phone",
    "\U0001f3ab": "Ticket",
    "\U0001f4e6": "Package",
    "\U0001f6a2": "Ship",
    "\U0001f30b": "Mountain",
    "\U0001f3d4": "Mountain",
    "\U0001f5a5": "Monitor",
    "\U0001f4bb": "Laptop",
    "⚑": "Flag",
    "\U0001f6a9": "Flag",
    "\U0001f4e4": "Upload",
    "✍": "PenLine",
    "\U0001f4be": "Save",
    "\U0001f511": "Key",
    "\U0001f319": "Moon",
    "☀": "Sun",
    "\U0001f4a1": "Lightbulb",
    "\U0001fa7a": "Stethoscope",
    "\U0001f3d7": "Construction",
    "\U0001f4da": "Library",
    "\U0001f522": "Hash",
    "\U0001f4dc": "Scroll",
    "\U0001f9ea": "FlaskConical",
    "\U0001f3e5": "Activity",
    "\U0001f329": "CloudLightning",
}

#: Everything the ratchet counts, so `--check` can report what it skipped.
_EMOJI_RE = re.compile("[\U0001f1e6-\U0001f1ff\U0001f300-\U0001faff☀-➿⬀-⯿⏩-⏺]")

_COMMENT_RE = re.compile(r"^\s*(?://|/?\*)")

#: `1em`, not a pixel count. Lucide writes `size` straight into the SVG's
#: `width`/`height`, and `width="1em"` follows the inherited font size — so the
#: icon tracks `data-density` exactly as the glyph it replaces did, and a glyph
#: that was 32px inside `style={{ fontSize: 32 }}` becomes a 32px icon with no
#: per-site decision and no edit to the surrounding style.
#:
#: A pixel number would have been the obvious choice and is the wrong one twice:
#: it freezes the icon out of the cascade, which is the whole defect
#: `frontend_size_ratchet.py` exists for, and it forces this codemod to guess a
#: size for 94 display glyphs it has no business sizing.
SIZE = '"1em"'


def outside_strings(line: str) -> list[tuple[int, int]]:
    """Spans of `line` that are not inside a `'`, `"` or backtick literal.

    A single pass with a quote state and a backslash escape. The escape matters:
    `'it\\'s ⚠'` is one string, and a scanner that treats the inner quote as a
    close reopens outside it and converts a glyph that is inside.
    """
    spans: list[tuple[int, int]] = []
    quote: str | None = None
    start = 0
    i = 0
    while i < len(line):
        ch = line[i]
        if quote:
            if ch == "\\":
                i += 2
                continue
            if ch == quote:
                quote = None
                start = i + 1
        elif ch in "'\"`":
            if start < i:
                spans.append((start, i))
            quote = ch
        i += 1
    if quote is None and start < len(line):
        spans.append((start, len(line)))
    return spans


def rewrite(text: str) -> tuple[str, dict[str, int], list[tuple[str, str]]]:
    """(new text, {icon: n}, [(glyph, why it was skipped)])."""
    counts: collections.Counter[str] = collections.Counter()
    skipped: list[tuple[str, str]] = []
    out_lines: list[str] = []

    for line in text.splitlines(keepends=True):
        if not _EMOJI_RE.search(line):
            out_lines.append(line)
            continue
        if _COMMENT_RE.match(line):
            skipped.extend((g, "in a comment") for g in _EMOJI_RE.findall(line))
            out_lines.append(line)
            continue

        spans = outside_strings(line)
        pieces: list[str] = []
        cursor = 0
        for m in _EMOJI_RE.finditer(line):
            glyph = m.group(0)
            if not any(a <= m.start() < b for a, b in spans):
                skipped.append((glyph, "inside a string"))
                continue
            icon = ICONS.get(glyph)
            if icon is None:
                skipped.append((glyph, "no icon mapped"))
                continue
            pieces.append(line[cursor : m.start()])
            pieces.append(f"<{icon} size={SIZE} aria-hidden />")
            cursor = m.end()
            # A variation selector belongs to the glyph it follows.
            if cursor < len(line) and line[cursor] == "️":
                cursor += 1
            counts[icon] += 1
        pieces.append(line[cursor:])
        out_lines.append("".join(pieces))

    return "".join(out_lines), dict(counts), skipped


_LUCIDE_IMPORT_RE = re.compile(r"^import \{([^}]*)\} from 'lucide-react';\s*$", re.M)


def _ensure_import(text: str, names: set[str]) -> str:
    """Add only the names the file does not already import from lucide-react.

    A file may carry MORE THAN ONE lucide import — `Settings.tsx` does, one for
    its own chrome and one for its tab table — and merging into the first
    without reading the rest produced `Duplicate identifier 'Zap'`. Loud, caught
    by `tsc`, but it means the union is what matters, not the first match.
    """
    matches = list(_LUCIDE_IMPORT_RE.finditer(text))
    if matches:
        have: set[str] = set()
        for m in matches:
            have |= {n.strip() for n in m.group(1).split(",") if n.strip()}
        missing = names - have
        if not missing:
            return text
        first = matches[0]
        merged = ", ".join(sorted({n.strip() for n in first.group(1).split(",") if n.strip()} | missing))
        return text[: first.start()] + f"import {{ {merged} }} from 'lucide-react';" + text[first.end() :]
    imports = list(re.finditer(r"^import .*?;$", text, re.M | re.S))
    if not imports:
        raise ValueError("no import statement to anchor a lucide import to")
    last = imports[-1]
    return (
        text[: last.end()] + "\nimport { " + ", ".join(sorted(names)) + " } from 'lucide-react';" + text[last.end() :]
    )


def run(root: Path, apply: bool) -> int:
    src = root / "frontend" / "src"
    total = collections.Counter()
    skipped_all: collections.Counter[tuple[str, str]] = collections.Counter()
    touched = 0

    for path in sorted(src.rglob("*.tsx")):
        if "/test/" in path.as_posix() or "/__tests__/" in path.as_posix():
            continue
        text = path.read_text(encoding="utf-8")
        new, counts, skipped = rewrite(text)
        skipped_all.update(skipped)
        if not counts:
            continue
        total.update(counts)
        touched += 1
        if apply:
            path.write_text(_ensure_import(new, set(counts)), encoding="utf-8")

    verb = "converted" if apply else "would convert"
    print(f"frontend_emoji_codemod: {verb} {sum(total.values())} glyph(s) in {touched} file(s)")
    for icon, n in total.most_common(15):
        print(f"  {n:>4}  <{icon} />")

    if skipped_all:
        print(f"\n{sum(skipped_all.values())} glyph(s) left for a human:")
        by_reason: collections.Counter[str] = collections.Counter()
        for (_g, why), n in skipped_all.items():
            by_reason[why] += n
        for why, n in by_reason.most_common():
            glyphs = sorted({g for (g, w) in skipped_all if w == why})[:12]
            print(f"  {n:>4}  {why}: {' '.join(glyphs)}")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", default=None)
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true", help="report without writing")
    mode.add_argument("--apply", action="store_true", help="rewrite the tree")
    args = ap.parse_args(argv)
    root = Path(args.root).resolve() if args.root else Path(__file__).resolve().parents[1]
    return run(root, apply=args.apply)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
