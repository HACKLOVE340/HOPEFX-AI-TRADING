#!/usr/bin/env python3
# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""Replace inline font sizes with the type-scale tokens that already equal them.

## Why this exists

`data-density` is stamped on every route by `PageSurface`, `index.css` fully
specifies three tiers across eleven tokens each, and CLAUDE.md documents it
accurately. It reaches almost nothing: measured 2026-09-15, **29** class usages
in the whole application read a density token, against **2,871** inline
`fontSize: <number>` and 1,089 numeric spacing utilities. A literal pixel is not
in the cascade, so no tier can change it — which is why the interface does not
feel dense at any setting. Recorded as DENSITY-CANNOT-REACH in the correction
register.

This is the boring half of closing it, and it is the same shape as
`frontend_token_codemod.py`, which did it for colour. Read that file's docstring
first; the hazards are the same ones with one addition.

## Only byte-identical substitutions

Every entry in `EXACT` maps a number to a token whose **base** (`:root`,
which is the `promax` tier) value is byte-identical to it:

    fontSize: 13   ->   fontSize: 'var(--fs-body)'      because --fs-body: 13px

So **at the default density nothing moves by a single pixel**, and the diff is
reviewable by reading the table rather than by looking at 400 files. What it
buys is the other two tiers: a literal cannot respond to `[data-density]` and
`var(--fs-body)` does.

Sizes that are merely *near* a token are NOT touched. The four largest buckets —
12px (638 uses), 11px (532), 10px (255) and 14px (217) — sit between tokens, and
picking one is a design decision per call site, not a substitution: 12 could be
`--fs-body` (13) or `--fs-label` (11.5), and choosing wrong changes what the
page looks like today. `--check` lists them with counts so the next pass can be
ranked, exactly as the colour codemod does for its ambiguous shades.

## Spacing is deliberately out of scope

`padding: 14` is byte-identical to `--pad-card`, and it is not safely
substitutable: 14px of padding might be a card, a row, a modal or a button, and
`--pad-card` retunes all four together. A type scale maps cleanly because a font
size has one job; padding does not. That stays a per-site decision.

## The hazards

Two are inherited from the colour codemod and one is new.

**`var()` is resolved by the cascade, and a canvas is not the cascade.** So this
only writes inside contexts guaranteed to be CSS: a JSX `style={{ … }}`
attribute, and a top-level style-object declaration in a file that imports no
chart library and touches no canvas. The exclusion is computed from the source,
not typed.

**A number is not a string.** React appends `px` to a numeric `fontSize` and
passes a string through untouched, so the replacement must be quoted:
`fontSize: 13` becomes `fontSize: 'var(--fs-body)'`. An unquoted `var(--fs-body)`
is a syntax error, which is loud; a numeric token handed to a chart is silent,
which is why the canvas rule above is not optional.

**Chart libraries take `fontSize` as a number.** `lightweight-charts` accepts
`layout: { fontSize: 12 }` and would be handed a string it cannot parse. Those
options are never inside a `style={{ … }}` attribute, so rule 1 is safe by
construction; rule 2 excludes chart files outright.

## Usage

    python scripts/frontend_size_codemod.py --check     # report, write nothing
    python scripts/frontend_size_codemod.py --apply     # rewrite in place
    python scripts/frontend_size_codemod.py --selftest  # mapping still exact?

Idempotent: running it twice changes nothing the second time.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

# The span-finding and the canvas exclusion are imported rather than copied.
# They encode the one hazard that makes this not a sed one-liner, and two
# implementations of it would drift — the second one silently, because the file
# that broke would be a chart nobody opened.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from frontend_token_codemod import (
    _balanced_spans,
    _reads_canvas,
    _STYLE_ATTR,
    _STYLE_DECL,
)

REPO = Path(__file__).resolve().parent.parent
SRC = REPO / "frontend" / "src"

# ── The table. Every entry is byte-identical to the token's base value. ───────
#
# Verified against frontend/src/index.css by --selftest, which fails if any
# mapping stops being exact — a token whose scale is retuned must drop out of
# this table rather than silently start moving hundreds of call sites.
EXACT: dict[str, str] = {
    "10.5": "--fs-micro",
    "11.5": "--fs-label",
    "13": "--fs-body",
    "15": "--fs-value",
    "17": "--fs-title",
    "21": "--fs-head",
    "28": "--fs-hero",
}

# Sizes that appear often and sit BETWEEN tokens. Reported, never rewritten:
# each needs a decision per call site, because rounding one to its neighbour
# changes what the page looks like at the default density.
AMBIGUOUS = ("14", "16", "18", "20", "22", "24", "9")

# ── The ULTRA table ──────────────────────────────────────────────────────────
#
# `:root` declares the PROMAX values, so the table above could not see the three
# commonest literals in the tree: `fontSize: 12` (x638), `11` (x532) and `10`
# (x257) are byte-exact at the ULTRA tier and match nothing at `:root`. That is
# 1,436 sites the codemod existed to convert and was structurally blind to.
#
# Ultra is not an edge case here: `frontend/src/lib/densityPref.ts` defaults a
# person to it, and `PageSurface` stamps it on every data surface, which is what
# most of this application is.
#
# `15` is DELIBERATELY ABSENT. It is `--fs-value` at `:root` and `--fs-title` at
# ultra, so converting it under either anchor would leave the same literal
# meaning two different things depending on which run touched it. Any value
# exact at both anchors is excluded rather than resolved by precedence, and
# `selftest_ultra` fails if one is ever added back.
EXACT_ULTRA: dict[str, str] = {
    "10": "--fs-micro",
    "11": "--fs-label",
    "12": "--fs-body",
    "13.5": "--fs-value",
    "19": "--fs-head",
    "26": "--fs-hero",
}

# `fontSize: 13` / `fontSize: 13,` / `fontSize: 13 }` — a bare numeric literal
# only. Anything computed (`fontSize: size * 0.115`) is left alone: it is not a
# literal, and a token cannot participate in arithmetic.
_FONT_SIZE = re.compile(r"\bfontSize:\s*(\d+(?:\.\d+)?)\s*(?=[,}\n])")


def _substitute(segment: str, counts: dict[str, int], table: dict[str, str] | None = None) -> str:
    lookup = EXACT if table is None else table

    def repl(m: re.Match[str]) -> str:
        token = lookup.get(m.group(1))
        if token is None:
            return m.group(0)
        counts[token] = counts.get(token, 0) + 1
        # Quoted: React appends `px` to a number and passes a string through.
        return f"fontSize: 'var({token})'"

    return _FONT_SIZE.sub(repl, segment)


def rewrite(
    text: str, allow_declarations: bool, table: dict[str, str] | None = None
) -> tuple[str, dict[str, int]]:
    """Rewrite literal sizes to tokens. `table` picks the anchor; default `:root`."""
    counts: dict[str, int] = {}

    spans = _balanced_spans(text, _STYLE_ATTR, "{", "}")
    if allow_declarations:
        spans += _balanced_spans(text, _STYLE_DECL, "{", "}")

    # Apply right-to-left so earlier offsets stay valid, and drop any span
    # contained in one already applied — a style={{}} inside a style object
    # would otherwise be rewritten twice and double-count.
    spans.sort(key=lambda s: (s[0], -s[1]))
    merged: list[tuple[int, int]] = []
    for start, end in spans:
        if merged and start < merged[-1][1]:
            continue
        merged.append((start, end))

    out = text
    for start, end in reversed(merged):
        out = out[:start] + _substitute(out[start:end], counts, table) + out[end:]
    return out, counts


def _declared(selector: str) -> dict[str, str]:
    """The custom properties a selector's block declares, comments stripped."""
    css = (SRC / "index.css").read_text(encoding="utf-8")
    at = css.index(selector)
    open_at = css.index("{", at)
    depth, end = 0, len(css)
    for i in range(open_at, len(css)):
        if css[i] == "{":
            depth += 1
        elif css[i] == "}":
            depth -= 1
            if depth == 0:
                end = i
                break
    block = css[open_at:end]
    return {
        m.group(1): m.group(2).strip().lower()
        for m in re.finditer(r"(--[\w-]+)\s*:\s*([^;]+);", re.sub(r"/\*.*?\*/", " ", block, flags=re.S))
    }


def selftest_ultra() -> int:
    """The ultra table must be exact against `[data-density="ultra"]`.

    And must not overlap the `:root` table: a number exact at both anchors would
    mean two different tokens depending on which run converted it, and nothing
    in the file would say which was intended.
    """
    declared = _declared('[data-density="ultra"]')
    bad = [
        f"  fontSize: {number} -> {token}, but {token} is {declared.get(token)!r} at ultra"
        for number, token in EXACT_ULTRA.items()
        if declared.get(token) != f"{number}px"
    ]
    overlap = sorted(set(EXACT) & set(EXACT_ULTRA))
    if overlap:
        bad.append(f"  {overlap} is exact at BOTH anchors — it must be in neither table")
    if bad:
        print("frontend_size_codemod: the ultra mapping is not safe:", file=sys.stderr)
        print("\n".join(bad), file=sys.stderr)
        print("\nA retuned token must LEAVE this table, not silently move its call sites.", file=sys.stderr)
        return 1
    print(f"frontend_size_codemod: all {len(EXACT_ULTRA)} ultra mappings are exact and do not overlap :root")
    return 0


def selftest() -> int:
    """Every mapping must still be byte-identical to its token's base value."""
    css = (SRC / "index.css").read_text(encoding="utf-8")
    at = css.index(":root")
    open_at = css.index("{", at)
    depth, end = 0, len(css)
    for i in range(open_at, len(css)):
        if css[i] == "{":
            depth += 1
        elif css[i] == "}":
            depth -= 1
            if depth == 0:
                end = i
                break
    base = css[open_at:end]
    declared = {
        m.group(1): m.group(2).strip().lower()
        for m in re.finditer(r"(--[\w-]+)\s*:\s*([^;]+);", re.sub(r"/\*.*?\*/", " ", base, flags=re.S))
    }

    bad = []
    for number, token in EXACT.items():
        value = declared.get(token)
        if value != f"{number}px":
            bad.append(f"  fontSize: {number} -> {token}, but {token} is {value!r}")
    if bad:
        print("frontend_size_codemod: mapping is no longer exact:", file=sys.stderr)
        print("\n".join(bad), file=sys.stderr)
        print("\nA retuned token must LEAVE this table, not silently move its call sites.", file=sys.stderr)
        return 1
    print(f"frontend_size_codemod: all {len(EXACT)} mappings are exact")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--apply", action="store_true", help="rewrite files in place")
    ap.add_argument("--check", action="store_true", help="report what would change")
    ap.add_argument("--selftest", action="store_true", help="verify the mapping is still exact")
    ap.add_argument(
        "--anchor",
        choices=("root", "ultra"),
        default="root",
        help=(
            "which tier a literal must be byte-identical to. 'root' (default) is the promax "
            "scale :root declares; 'ultra' is the tier densityPref defaults a person to and "
            "PageSurface stamps on every data surface. The two tables never share a number."
        ),
    )
    args = ap.parse_args()

    if args.selftest:
        return selftest() or selftest_ultra()
    if selftest() != 0 or selftest_ultra() != 0:
        return 1

    table = EXACT_ULTRA if args.anchor == "ultra" else EXACT

    total: dict[str, int] = {}
    touched = 0
    for path in sorted(SRC.rglob("*")):
        if path.suffix not in (".tsx", ".ts") or path.name.endswith(".d.ts"):
            continue
        if "/test/" in path.as_posix() or path.name.endswith((".test.ts", ".test.tsx")):
            continue
        text = path.read_text(encoding="utf-8")
        new, counts = rewrite(text, allow_declarations=not _reads_canvas(text), table=table)
        if new == text:
            continue
        touched += 1
        for k, v in counts.items():
            total[k] = total.get(k, 0) + v
        if args.apply:
            path.write_text(new, encoding="utf-8")

    moved = sum(total.values())
    verb = "replaced" if args.apply else "would replace"
    print(
        f"frontend_size_codemod[{args.anchor}]: {verb} {moved} literal size(s) across {touched} file(s)"
    )
    for token, n in sorted(total.items(), key=lambda kv: -kv[1]):
        print(f"  {n:>5}  var({token})")

    if args.check:
        src_all = "\n".join(
            p.read_text(encoding="utf-8")
            for p in SRC.rglob("*")
            if p.suffix in (".tsx", ".ts") and "/test/" not in p.as_posix()
        )
        print("\nStill literal, and needing a decision rather than a substitution:")
        for size in AMBIGUOUS:
            n = len(re.findall(rf"\bfontSize:\s*{re.escape(size)}\s*(?=[,}}\n])", src_all))
            if n:
                print(f"  {n:>5}  fontSize: {size}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
