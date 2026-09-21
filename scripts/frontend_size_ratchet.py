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
        n = len(_SIZE_RE.findall(text)) + len(_SPACE_RE.findall(text))
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
        tokens += len(_TOKEN_RE.findall(text))
        sizes += len(_SIZE_RE.findall(text))
        space += len(_SPACE_RE.findall(text))
    return (tokens, sizes, space)


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
        print(json.dumps(count_sizes(root), indent=1, sort_keys=True))
        return 0
    if args.adopt:
        return adopt(root)
    return check(root)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
