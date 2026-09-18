#!/usr/bin/env python3
# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""Replace hardcoded colour literals with the tokens that already equal them.

## What this does, and what it deliberately does not

`scripts/frontend_colour_ratchet.py` records the debt and refuses to let it
grow. Its own docstring says the replacement "is a codemod, and it is the
owner's call. This is not that." The owner asked for it on 2026-09-14. This is
that.

It is deliberately the *boring* half of the job. Every substitution in `EXACT`
below maps a literal to a token whose dark value is **byte-identical** to it:

    #64748b  ->  var(--text-muted)      because --text-muted: #64748b

So in the dark theme nothing moves by a single pixel or a single shade, and the
change is reviewable by reading the table rather than by looking at 201 files.
What it buys is the light theme and the AI surface: a literal cannot respond to
`[data-theme]`, and `var(--text-muted)` does. That one fact is the whole reason
the toggle was dead.

Colours that are merely *similar* to a token are NOT touched. `#1e293b` (568
uses), `#334155` (530), `#475569` (441), `#0f172a` (305) and `#3b82f6` (263)
are each doing more than one job — border in one place, raised surface in
another — and picking a role for them is a design decision per call site, not a
substitution. `--check` lists them with counts so the next pass can be ranked.

## The canvas hazard, which is why this is not a sed one-liner

`var()` is resolved by the CSS cascade. A canvas 2D context is not the cascade:

    createChart(el, { layout: { background: { color: '#0f172a' } } })   # canvas
    <div style={{ background: '#0f172a' }}>                            # CSS

The first renders transparent-black if you hand it `var(--surface)`; the second
is correct. `pages/Dashboard.tsx` contains both, four lines apart. So this only
ever writes inside contexts that are guaranteed to be CSS:

  1. a JSX `style={{ … }}` attribute — always CSS, in every file;
  2. a `className` Tailwind arbitrary value, `text-[#64748b]` — always CSS;
  3. a top-level style-object declaration (`const s = { … }`), and only in
     files that import no chart library and touch no canvas.

Rule 3 is where most of the repository's colour lives, and the exclusion list
is computed from the source, not typed: any file importing `lightweight-charts`
or calling `getContext` / `fillStyle` / `strokeStyle` is held to rules 1 and 2.

## Usage

    python scripts/frontend_token_codemod.py --check     # report, write nothing
    python scripts/frontend_token_codemod.py --apply     # rewrite in place

Idempotent: running it twice changes nothing the second time.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SRC = REPO / "frontend" / "src"

# ── The table. Every entry is byte-identical to the token's dark value. ───────
#
# Verified against frontend/src/index.css by --selftest, which fails if any
# mapping stops being exact — a token whose palette is retuned must drop out of
# this table rather than silently start moving 697 call sites.
EXACT: dict[str, str] = {
    "#080c14": "--bg",
    "#0d1421": "--surface",
    "#111827": "--raised",
    "#05070c": "--sunken",
    "#1e2d3d": "--border",
    "#2b3f56": "--border-strong",
    "#16222f": "--hairline",
    "#141c2b": "--surface-hover",
    "#e2e8f0": "--text",
    "#f8fafc": "--text-strong",
    "#94a3b8": "--text-dim",
    "#64748b": "--text-muted",
    "#56627a": "--text-faint",
    "#00d4ff": "--accent",
    "#60a5fa": "--link",
    "#38bdf8": "--focus",
    "#7dd3fc": "--info",
    "#00e676": "--bull",
    "#ff1744": "--bear",
    "#4ade80": "--gain",
    "#f87171": "--loss",
    "#fbbf24": "--warn",
    "#42d392": "--ok",
    "#f5b84b": "--degraded",
    "#f36d78": "--failed",
    "#a78bfa": "--ai-model",
    "#ffab00": "--q-waiting",
    "#7c8db5": "--q-theirs",
    "#4a5a72": "--q-done",
    "#ff4d6d": "--q-urgent",
    "#25000c": "--q-urgent-bg",
    "#ffc7d1": "--q-urgent-text",
    "#0a1a24": "--q-selected-bg",
    "#06404f": "--q-accent-edge",
}

# Literals that appear often and map to NO token exactly. Reported, never
# rewritten: each is doing more than one job and needs a decision per site.
AMBIGUOUS = (
    "#1e293b",
    "#334155",
    "#475569",
    "#0f172a",
    "#3b82f6",
    "#22c55e",
    "#ef4444",
    "#f59e0b",
    "#f1f5f9",
    "#1e3a5f",
)

CANVAS_MARKERS = ("lightweight-charts", "getContext(", "fillStyle", "strokeStyle", "createChart")

HEX = re.compile(r"#[0-9a-fA-F]{6}\b")


def _reads_canvas(text: str) -> bool:
    return any(m in text for m in CANVAS_MARKERS)


def _balanced_spans(text: str, opener: re.Pattern[str], open_ch: str, close_ch: str) -> list[tuple[int, int]]:
    """Spans from each match of `opener` to its balanced closing bracket."""
    spans: list[tuple[int, int]] = []
    for m in opener.finditer(text):
        depth = 0
        i = m.end() - 1  # sit on the first opening bracket of the match
        while i < len(text) and text[i] != open_ch:
            i += 1
        start = i
        while i < len(text):
            if text[i] == open_ch:
                depth += 1
            elif text[i] == close_ch:
                depth -= 1
                if depth == 0:
                    spans.append((start, i + 1))
                    break
            i += 1
    return spans


# `style={{` … matching `}}`; the outer brace is JSX, the inner is the object.
_STYLE_ATTR = re.compile(r"style=\{")
# A top-level style-object declaration: `const s = {`, `const panel: React.CSSProperties = {`.
_STYLE_DECL = re.compile(r"^const\s+\w+\s*(?::\s*[^=\n]*(?:CSSProperties|Record<[^=\n]*>)\s*)?=\s*\{", re.MULTILINE)
# A Tailwind arbitrary value: `text-[#64748b]`, `bg-[#0d1421]/60`.
_ARBITRARY = re.compile(r"(\[)(#[0-9a-fA-F]{6})(\])")


def _substitute(segment: str, counts: dict[str, int]) -> str:
    def repl(m: re.Match[str]) -> str:
        token = EXACT.get(m.group(0).lower())
        if token is None:
            return m.group(0)
        counts[token] = counts.get(token, 0) + 1
        return f"var({token})"

    return HEX.sub(repl, segment)


def rewrite(text: str, allow_declarations: bool) -> tuple[str, dict[str, int]]:
    counts: dict[str, int] = {}

    spans = _balanced_spans(text, _STYLE_ATTR, "{", "}")
    if allow_declarations:
        spans += _balanced_spans(text, _STYLE_DECL, "{", "}")

    # Apply right-to-left so earlier offsets stay valid, and drop any span that
    # is contained in one already applied — a style={{}} inside a style object
    # would otherwise be rewritten twice and double-count.
    spans.sort(key=lambda s: (s[0], -s[1]))
    merged: list[tuple[int, int]] = []
    for start, end in spans:
        if merged and start < merged[-1][1]:
            continue
        merged.append((start, end))

    out = text
    for start, end in reversed(merged):
        out = out[:start] + _substitute(out[start:end], counts) + out[end:]

    # Tailwind arbitrary values are CSS wherever they appear.
    def arb(m: re.Match[str]) -> str:
        token = EXACT.get(m.group(2).lower())
        if token is None:
            return m.group(0)
        counts[token] = counts.get(token, 0) + 1
        return f"[var({token})]"

    return _ARBITRARY.sub(arb, out), counts


def selftest() -> int:
    """Every mapping must still be byte-identical to its token's dark value."""
    css = (SRC / "index.css").read_text(encoding="utf-8")
    # The base :root block only — a light or AI value is not what pages carry.
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
    for literal, token in EXACT.items():
        value = declared.get(token)
        if value != literal:
            bad.append(f"  {literal} -> {token}, but {token} is {value!r}")
    if bad:
        print("frontend_token_codemod: mapping is no longer exact:", file=sys.stderr)
        print("\n".join(bad), file=sys.stderr)
        print("\nA retuned token must LEAVE this table, not silently move its call sites.", file=sys.stderr)
        return 1
    print(f"frontend_token_codemod: all {len(EXACT)} mappings are exact")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--apply", action="store_true", help="rewrite files in place")
    ap.add_argument("--check", action="store_true", help="report what would change")
    ap.add_argument("--selftest", action="store_true", help="verify the mapping is still exact")
    args = ap.parse_args()

    if args.selftest:
        return selftest()
    if selftest() != 0:
        return 1

    total: dict[str, int] = {}
    touched = 0
    for path in sorted(SRC.rglob("*")):
        if path.suffix not in (".tsx", ".ts") or path.name.endswith(".d.ts"):
            continue
        if "/test/" in path.as_posix() or path.name.endswith((".test.ts", ".test.tsx")):
            continue
        text = path.read_text(encoding="utf-8")
        new, counts = rewrite(text, allow_declarations=not _reads_canvas(text))
        if new == text:
            continue
        touched += 1
        for k, v in counts.items():
            total[k] = total.get(k, 0) + v
        if args.apply:
            path.write_text(new, encoding="utf-8")

    moved = sum(total.values())
    verb = "replaced" if args.apply else "would replace"
    print(f"frontend_token_codemod: {verb} {moved} literal(s) across {touched} file(s)")
    for token, n in sorted(total.items(), key=lambda kv: -kv[1])[:12]:
        print(f"  {n:>5}  var({token})")

    if args.check:
        src_all = "\n".join(p.read_text(encoding="utf-8") for p in SRC.rglob("*") if p.suffix in (".tsx", ".ts"))
        print("\nStill literal, and needing a decision rather than a substitution:")
        for lit in AMBIGUOUS:
            n = len(re.findall(re.escape(lit), src_all, re.IGNORECASE))
            if n:
                print(f"  {n:>5}  {lit}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
