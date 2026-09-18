#!/usr/bin/env python3
# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""Which routed pages have no live data anywhere behind them.

## Why this script exists — the measurement it replaces was wrong

`docs/audit/FRONTEND_HANDOVER.md` carried a list headed "Eleven routed pages
call no API at all", naming five as "worth wiring": `AIAssistant`,
`NuclearDashboardPage`, `SystemReliability`, `PositionDetail` and
`GeopoliticalRiskPage`.

Re-measured 2026-09-15, **all five were already data-wired** — by three
different mechanisms, none of which a grep of the page file can see:

    AIAssistant           renders <AIChat>, which calls aiAssistantApi.send
    NuclearDashboardPage  renders <NuclearDashboard> from features/chart-bot
    SystemReliability     lazy-loads superadmin/SystemReliabilitySection
    GeopoliticalRiskPage  calls useQuery(fetchWorldMonitorViews) itself
    PositionDetail        reads useStore(selectPositions) — the global store,
                          hydrated by whoever fetched the positions

The list was produced by looking for a fetch **in the page file**. A page that
delegates to a child, or reads a store someone else filled, looks identical to
a page with nothing behind it. The handover had already noticed two of these
(`Settings` and `Hub`, exempted by hand as "shells whose children fetch") — the
exemption was the tell that the predicate was wrong, not that those two were
special.

Acting on that list would have been worse than ignoring it: adding a second
fetch to a page whose child already fetches duplicates a request, and can put
two sources of truth on one screen.

So the predicate is reachability through the **import graph**, which is what
"does this page show live data" actually means.

## What counts as reaching data

A page reaches data when it, or any module it transitively imports from within
`frontend/src`, contains a call that crosses the process boundary or reads the
store that such a call fills:

    somethingApi.foo(...)      the 71 API objects in hooks/useApi.ts
    api.get / api.post / ...   the shared axios instance
    fetch(...)                 the platform primitive
    useQuery / useMutation     react-query, whose queryFn does the call
    new WebSocket / openAuthenticatedWebSocket
    useStore(select...)        global state, hydrated by a fetch elsewhere

**Comments and string literals are stripped first.** A checker that reads prose
as code is a defect this repository has now found five times (F255, F257, the
skill-claims verifier, and `_on_shell` accepting a `// TODO: migrate this page
to PageShell` comment as a migration). `_no_comments` and `_no_strings` are tested
directly, in `tests/unit/test_frontend_data_reachability.py`, against a file
whose only `fetch(` is inside a comment and one whose only `fetch(` is inside a
string.

## What it deliberately does NOT do

It does not block, and it is not a ratchet. A static page is a legitimate page
— `PrivacyPolicy`, `TermsAndRiskDisclosure`, `NotFound` and `DocsPage` are
correct with no data behind them, and a gate that pushed them to fetch
something would be making the product worse to move a number. This prints a
list for a human to read.

## Usage

    python scripts/frontend_data_reachability.py            # the report
    python scripts/frontend_data_reachability.py --json     # machine-readable
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

# Reuse the router-derived page discovery rather than keeping a second copy of
# it: the page-shell ratchet's own history is that a hand-typed page list fell
# behind by 42 entries.
sys.path.insert(0, str(REPO / "scripts"))
import frontend_page_shell_ratchet as _ratchet

# The module, not the two functions: they read `_ratchet.REPO`, and importing
# them by name would bind this file's tests to the real tree forever. `measure`
# points it at whatever REPO is when it runs.


_SRC = ("frontend", "src")

# Extensions tried, in order, when resolving `./foo` to a file on disk.
_EXTS = (".tsx", ".ts", ".jsx", ".js")

# The data layer ITSELF. Importing the module that DEFINES `superadminApi` is
# not calling it, and every page reaches these through PageShell -> navConfig,
# so counting them makes the measurement say "yes" for everything — which is
# how the first run of this script reported DocsPage, a page whose only state
# is a search box, as reaching live data via hooks/useApi.ts.
#
# They stay in the WALK (a module that both defines and calls is possible);
# they are only excluded from the marker match.
_DEFINITION_MODULES = frozenset(
    {
        "frontend/src/hooks/useApi.ts",
        "frontend/src/lib/ws.ts",
        "frontend/src/store/index.ts",
    }
)

# `api.get<StatusData>('/2fa/status')` is a call. Without this, the first run
# of this script reported TwoFactorSetup — which makes five calls — as having no
# data behind it, because a TypeScript generic sits between the method name and
# the parenthesis. A security page reported as static is exactly the wrong way
# for a measurement to be wrong.
_GENERIC = r"(?:<[^<>;\n]*(?:<[^<>;\n]*>)?[^<>;\n]*>\s*)?"

_DATA_MARKERS: tuple[tuple[str, re.Pattern[str]], ...] = (
    # `superadminApi.get(...)`, `aiAssistantApi.send(...)` — the 71 objects
    # exported from hooks/useApi.ts. Lower-cased first letter so a TYPE named
    # `ApiError` does not match.
    ("api-object", re.compile(r"\b[a-z]\w*Api\s*\.\s*\w+\s*" + _GENERIC + r"\(")),
    # The shared axios instance itself.
    ("axios", re.compile(r"\bapi\s*\.\s*(?:get|post|put|patch|delete)\s*" + _GENERIC + r"\(")),
    ("fetch", re.compile(r"(?<![\w.])fetch\s*\(")),
    ("react-query", re.compile(r"\buse(?:Query|Mutation|InfiniteQuery)\s*\(")),
    ("websocket", re.compile(r"\bnew\s+WebSocket\s*\(|\bopenAuthenticatedWebSocket\s*\(")),
    # The global store. `useStore(selectPositions)` is live data on the screen;
    # it just was not fetched by this component.
    ("store", re.compile(r"\buseStore\s*\(\s*select\w+")),
)


def _no_comments(text: str) -> str:
    """`text` with comments blanked and string bodies KEPT, lengths preserved.

    Import specifiers live inside strings, so the import walk reads this one.
    Blanking rather than deleting keeps the shape of the file, so a marker
    cannot be manufactured by splicing two lines together.
    """
    out = list(text)
    i = 0
    n = len(text)
    while i < n:
        ch = text[i]
        nxt = text[i + 1] if i + 1 < n else ""
        if ch == "/" and nxt == "/":
            while i < n and text[i] != "\n":
                out[i] = " "
                i += 1
        elif ch == "/" and nxt == "*":
            out[i] = out[i + 1] = " "
            i += 2
            while i < n and not (text[i] == "*" and i + 1 < n and text[i + 1] == "/"):
                if text[i] != "\n":
                    out[i] = " "
                i += 1
            if i < n:
                out[i] = " "
                if i + 1 < n:
                    out[i + 1] = " "
                i += 2
        elif ch in "\"'`":
            # Skip OVER the literal without blanking it: `_no_strings` does
            # that, and the import walk needs the specifier intact. Stepping
            # through here is still required, so that a `//` or `/*` inside a
            # string (a URL, a regex) is not mistaken for a comment.
            quote = ch
            i += 1
            while i < n:
                if text[i] == "\\":
                    i += 2
                    continue
                if text[i] == quote:
                    break
                i += 1
            i += 1
        else:
            i += 1
    return "".join(out)


def _no_strings(code: str) -> str:
    """Comment-free `code` with string BODIES blanked, lengths preserved.

    The marker search reads this one: `"fetch("` written inside a string is a
    piece of text, not a call. A template literal's `${...}` is code and is
    left alone — `` `${api.get(u)}` `` really is a call.
    """
    out = list(code)
    i = 0
    n = len(code)
    while i < n:
        ch = code[i]
        if ch not in "\"'`":
            i += 1
            continue
        quote = ch
        i += 1
        while i < n:
            if code[i] == "\\":
                out[i] = " "
                if i + 1 < n:
                    out[i + 1] = " "
                i += 2
                continue
            if code[i] == quote:
                break
            if quote == "`" and code[i] == "$" and i + 1 < n and code[i + 1] == "{":
                depth = 0
                while i < n:
                    if code[i] == "{":
                        depth += 1
                    elif code[i] == "}":
                        depth -= 1
                        if depth == 0:
                            i += 1
                            break
                    i += 1
                continue
            if code[i] != "\n":
                out[i] = " "
            i += 1
        i += 1
    return "".join(out)


def _resolve(spec: str, importer: Path, src: Path) -> Path | None:
    """Resolve a relative or `@/`-aliased import to a file inside src."""
    if spec.startswith("@/"):
        base = src / spec[2:]
    elif spec.startswith("."):
        base = (importer.parent / spec).resolve()
    else:
        return None  # a package, not our code
    for ext in _EXTS:
        cand = base.with_suffix(base.suffix + ext) if base.suffix == "" else Path(str(base) + ext)
        if cand.is_file():
            return cand
    if base.is_file():
        return base
    for ext in _EXTS:
        cand = base / f"index{ext}"
        if cand.is_file():
            return cand
    return None


_IMPORT = re.compile(
    r"""(?:import|export)\s+(?:[\w*{}\s,]+\s+from\s+)?['"]([^'"]+)['"]"""
    r"""|import\s*\(\s*['"]([^'"]+)['"]\s*\)"""
)


def _imports(code: str) -> list[str]:
    specs = []
    for m in _IMPORT.finditer(code):
        specs.append(m.group(1) or m.group(2))
    return [s for s in specs if s]


def _reaches_data(entry: Path, src: Path, limit: int = 4000) -> tuple[bool, str, Path | None]:
    """Walk `entry`'s import graph; return the first data marker found.

    Breadth-first so the shallowest evidence wins — a page that fetches for
    itself should not be reported as reaching data through a grandchild.
    """
    seen: set[Path] = set()
    queue: list[Path] = [entry]
    while queue and len(seen) < limit:
        mod = queue.pop(0)
        if mod in seen or not mod.is_file():
            continue
        seen.add(mod)
        try:
            raw = mod.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        code = _no_comments(raw)
        rel = mod.relative_to(REPO).as_posix() if mod.is_relative_to(REPO) else mod.as_posix()
        if rel not in _DEFINITION_MODULES:
            for name, pattern in _DATA_MARKERS:
                if pattern.search(_no_strings(code)):
                    return True, name, mod
        for spec in _imports(code):
            target = _resolve(spec, mod, src)
            if target is not None and target not in seen:
                queue.append(target)
    return False, "", None


def measure() -> dict[str, object]:
    _ratchet.REPO = REPO
    src = REPO.joinpath(*_SRC)
    pages_dir = src / "pages"
    routed = _ratchet._routed_pages()
    public = _ratchet._public_pages()

    wired: dict[str, dict[str, str]] = {}
    static: list[str] = []
    for path in sorted(pages_dir.rglob("*.tsx")):
        if path.name.endswith(".test.tsx") or path.stem not in routed:
            continue
        ok, marker, where = _reaches_data(path, src)
        rel = path.relative_to(REPO).as_posix()
        if ok and where is not None:
            wired[rel] = {
                "via": marker,
                "in": where.relative_to(REPO).as_posix(),
                "own": str(where == path).lower(),
            }
        else:
            static.append(rel)
    return {
        "routed": len(wired) + len(static),
        "wired": wired,
        "static": sorted(static),
        "public": sorted(public),
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    args = ap.parse_args(argv)

    result = measure()
    if args.json:
        print(json.dumps(result, indent=1, sort_keys=True))
        return 0

    wired = result["wired"]
    static = result["static"]
    assert isinstance(wired, dict) and isinstance(static, list)
    own = sum(1 for v in wired.values() if v["own"] == "true")
    print(
        f"frontend_data_reachability: {len(wired)} of {result['routed']} routed pages "
        f"reach live data ({own} fetch for themselves, "
        f"{len(wired) - own} through a child or the store)"
    )
    if static:
        print("\nNo live data anywhere behind these — check each is static BY DESIGN:")
        for rel in static:
            print(f"  {rel}")
    print("\nThis gate does not block. A static page is a legitimate page.")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
