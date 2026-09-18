#!/usr/bin/env python3
# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""Hardcoded colour literals in `frontend/src` may only decrease.

## Why this exists

The frontend page audit on 2026-09-09 measured, across `frontend/src/pages` and
`frontend/src/components`:

    7,340 hardcoded hex literals   (210 distinct)
       58 uses of var(--…)
    4,000 inline style={{…}} blocks
    1,010 className= attributes

`frontend/src/index.css` declares twelve well-chosen semantic tokens — `--bg`,
`--surface`, `--raised`, `--border`, `--text`, `--text-muted`, `--accent`,
`--bull`, `--bear` and three layout measures. Almost nothing uses them.

Three finished features are dead as a direct result, and none of them is dead
because it was built badly:

  * **The light/dark toggle.** `ThemeContext.tsx` reads `prefers-color-scheme`,
    persists the choice and stamps `data-theme` on the document element;
    `AppearanceSection.tsx` offers light / dark / system; `tailwind.config.ts`
    is configured with `darkMode: ['class', '[data-theme="dark"]']`. All
    correct. And no `[data-theme="light"]` rule exists in any stylesheet in the
    project, and exactly one `dark:` variant appears in all 70 pages plus every
    component. Choosing Light saves the preference and changes nothing.

  * **White-label branding.** `WhitelabelAdmin.tsx` collects a tenant's brand
    colour and sends it. The surface it is meant to brand is 7,340 literals, so
    the colour can only reach the handful of places that read a token.

  * **Visual consistency.** Five different greys are doing "muted text"
    (`#64748b` 673 times, `#94a3b8` 517, `#475569` 412, `#334155` 513,
    `#1e293b` 569 — the Tailwind slate ramp, transcribed by hand). Nothing says
    which grey means which thing, so pages drift apart by default.

Inline styles cannot participate in a cascade: they cannot respond to a
`[data-theme]` attribute, a media query, or a variable they do not name. That
one fact is the whole cause.

## What this script is, and is not

Replacing the literals is a codemod, and it is the owner's call. This is not
that. This records today's count per file and refuses to let it grow, so that
when the codemod happens it stays done — a cleanup with no ratchet behind it is
undone within a month, and then the same three features are dead again with a
fresh explanation.

The rules mirror `scripts/pre_commit_coverage.py`, deliberately, because the
repository already has one ratchet and a second one with different semantics is
a second thing to remember:

    recorded + fewer literals than recorded  -> passes (progress)
    recorded + same count                    -> passes
    recorded + MORE literals                 -> blocks
    NOT recorded + any literal               -> blocks (a new file is where new
                                                debt actually arrives)
    recorded + zero literals now             -> BLOCKS, with one instruction:
                                                delete the line. An entry that
                                                no longer describes anything is
                                                how a ratchet quietly stops
                                                being one.

## Usage

    python scripts/frontend_colour_ratchet.py --report   # counts, as JSON
    python scripts/frontend_colour_ratchet.py --adopt    # write the baseline
    python scripts/frontend_colour_ratchet.py --check    # the gate

`--check` is the pre-commit hook. It reads the whole tree rather than only the
staged files: the "delete the line when it reaches zero" rule cannot be
evaluated from a staged subset, and the scan is fast enough that there is no
reason to.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

# 3, 4, 6 or 8 hex digits, not followed by another word character — so `#abc`
# matches but the `#abcdefgh` of an id or a fragment does not. Deliberately not
# comment-aware: a literal written in a comment is a literal the next
# contributor copies, and exempting comments only advertises the blind spot.
HEX_RE = re.compile(r"#(?:[0-9a-fA-F]{8}|[0-9a-fA-F]{6}|[0-9a-fA-F]{4}|[0-9a-fA-F]{3})(?![0-9a-zA-Z_])")

SCANNED_SUFFIXES = (".tsx", ".ts", ".jsx", ".js", ".css")

# index.css is where the tokens are DEFINED. Its literals are the palette, not
# debt, and forbidding them would forbid having a palette at all.
EXEMPT = ("src/index.css",)

BASELINE_REL = Path("docs") / "FRONTEND_COLOUR_DEBT.json"


def _frontend_src(root: Path) -> Path:
    return root / "frontend" / "src"


def _is_exempt(rel: str) -> bool:
    return any(rel.endswith(e) for e in EXEMPT)


def count_literals(root: Path) -> dict[str, int]:
    """Map repo-relative path -> literal count, omitting files with none."""
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
        n = len(HEX_RE.findall(text))
        if n:
            counts[rel] = n
    return counts


def load_baseline(root: Path) -> dict[str, int]:
    path = root / BASELINE_REL
    if not path.exists():
        return {}
    return dict(json.loads(path.read_text(encoding="utf-8")).get("files", {}))


def adopt(root: Path) -> int:
    counts = count_literals(root)
    path = root / BASELINE_REL
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "_comment": (
                    "Hardcoded colour literals per file in frontend/src. This number may "
                    "only fall. See scripts/frontend_colour_ratchet.py for why these "
                    "literals keep three finished features dead, and for the rule that a "
                    "file reaching zero must be DELETED from this list rather than left "
                    "at 0 — an entry describing nothing is how a ratchet stops being one."
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
    print(f"frontend_colour_ratchet: adopted {sum(counts.values())} literals across {len(counts)} files")
    return 0


def check(root: Path) -> int:
    current = count_literals(root)
    baseline = load_baseline(root)

    if not baseline:
        print("frontend_colour_ratchet: no baseline — run --adopt", file=sys.stderr)
        return 1

    failures: list[str] = []
    improved = 0

    for rel, now in sorted(current.items()):
        was = baseline.get(rel)
        if was is None:
            failures.append(
                f"{rel}: {now} colour literal(s) in a file with no baseline entry. "
                f"Use the tokens in frontend/src/index.css (var(--text), var(--surface), …) "
                f"— a new literal is new debt, and the light theme and white-label "
                f"branding both depend on this number falling."
            )
        elif now > was:
            failures.append(
                f"{rel}: {now} colour literals, up from {was}. This list may only shrink. "
                f"Replace the added literal with a token rather than raising the baseline."
            )
        elif now < was:
            improved += was - now

    for rel, was in sorted(baseline.items()):
        if rel not in current:
            path = root / rel
            if path.exists():
                failures.append(
                    f"{rel}: now has zero colour literals (was {was}) and must leave the "
                    f"record. Delete its line from {BASELINE_REL.as_posix()} — an entry "
                    f"that no longer describes anything is how a ratchet quietly stops "
                    f"being one."
                )
            # A deleted file simply leaves; that is progress, not a violation.

    total_now = sum(current.values())
    total_was = sum(baseline.values())
    print(f"frontend_colour_ratchet: {total_now} colour literals across {len(current)} files (baseline {total_was})")
    if improved:
        print(
            f"frontend_colour_ratchet: {improved} literal(s) removed since the baseline — "
            f"run --adopt to bank the progress"
        )

    if failures:
        print(
            f"\nfrontend_colour_ratchet: {len(failures)} file(s) moved the wrong way:",
            file=sys.stderr,
        )
        for f in failures:
            print(f"  {f}", file=sys.stderr)
        print(
            "\nWhy this blocks: 7,340 hardcoded literals are why the light/dark toggle "
            "changes nothing and why a white-label tenant's brand colour cannot reach the "
            "product. See scripts/frontend_colour_ratchet.py.",
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
        print(json.dumps(count_literals(root), indent=1, sort_keys=True))
        return 0
    if args.adopt:
        return adopt(root)
    return check(root)


if __name__ == "__main__":
    raise SystemExit(main())
