# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""Nothing from either Group 4 source may go missing.

    python scripts/group4_preservation.py

The Group 4 specification opens with one rule:

    ADD AND EXPAND; NEVER SILENTLY REMOVE. Deferred implementation does not
    mean deletion.

Two sources now exist and they do not enumerate the same things:

| Source | Shape | Count |
|---|---|---:|
| `GROUP4_master_ai_operating_system.txt` (v1) | Table of contents, 20 volumes | 186 numbered chapters |
| `GROUP4_master_ai_operating_system_v2_complete.txt` (v2) | Complete prose, 20 volumes + AI Hub | 117 named sections |

v2 is not a superset. It carries substance v1 never had — a statement under every
section, a Decision Governance section, an AI Hub and Experience block, a trading
domain preservation clause — while naming far fewer items than v1's 186. So
adopting either alone drops titles the other names, and the rule above forbids
that whichever direction it happens in.

## What this checks, and what it deliberately does not

Every title from both sources must still be **listed** in one of the repository's
`GROUP4_*.md` documents. Listed, not merely mentioned: only markdown table rows
and list items count. Prose is excluded on purpose — otherwise a title deleted
from the index would still "pass" because the word appears in a sentence
somewhere, and generic titles like `Purpose`, `Caching`, `Audit` and
`Verification` would pass no matter what. That is the difference between a check
and a check-shaped object.

It does **not** check that any of it is implemented. Coverage against the code is
`scripts/backlog_report.py`; this is only the anti-omission control.

## It refuses rather than reporting clean

A source it cannot read, or a corpus with no documents in it, raises
:class:`PreservationBroken`. Rule 3: a checker that examined nothing must not
return "nothing missing", because that is indistinguishable from success.
"""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Final

REPO: Final = Path(__file__).resolve().parent.parent
SPECS: Final = REPO / "docs" / "ai" / "specs"

V1: Final = SPECS / "GROUP4_master_ai_operating_system.txt"
V2: Final = SPECS / "GROUP4_master_ai_operating_system_v2_complete.txt"

#: Stamped after all but one section in v2, and after every volume. Repetition is
#: the document's template, not its content; counting it would inflate the total
#: and hide a genuine omission behind a large "preserved" number.
_V2_BOILERPLATE: Final = frozenset({"Mandatory Engineering Requirements", "Purpose"})

#: The cover block. A document's own name is not one of its sections.
_V2_BANNER: Final = frozenset(
    {
        "MASTER AI OPERATING SYSTEM",
        "COMPLETE MASTER ARCHITECTURE, ENGINEERING, OPERATIONS, ACCELERATION, EXECUTION AND GOVERNANCE SPECIFICATION",
        "Authoritative Consolidated Blueprint — Volumes I–XX",
    }
)
_V2_PER_VOLUME_CLOSER: Final = "Implementation Backlog Preservation"

#: `\t12.\tIntelligence Governor`
_V1_CHAPTER = re.compile(r"^\t(\d+)\.\t(.+?)\s*$")
_V1_VOLUME = re.compile(r"^(VOLUME [IVX]+ — .+?)\s*$")

#: v2 was extracted with one paragraph per line; bullets carry a leading `\t- `.
_V2_VOLUME = re.compile(r"^((?:VOLUME [IVX]+ — |AI HUB AND |SPECIALIZED |FINAL ).+?)\s*$")

#: Only listed lines count as preservation. See the module docstring.
_LISTED = re.compile(r"^\s*(?:\||[-*+]\s|\d+\.\s)")


class PreservationBroken(RuntimeError):
    """The check could not be performed, so its result means nothing."""


@dataclass(frozen=True)
class Section:
    source: str
    volume: str
    title: str


@dataclass(frozen=True)
class Report:
    missing: list[Section]
    titles_checked: int
    documents_read: int


def _read(path: Path) -> str:
    if not path.exists():
        raise PreservationBroken(f"source not found: {path}")
    text = path.read_text(encoding="utf-8")
    if not text.strip():
        raise PreservationBroken(f"source is empty: {path}")
    return text


def v1_chapters(path: Path | None = None) -> list[Section]:
    """The 186 numbered chapters of the v1 table of contents."""
    path = path or V1
    volume = ""
    out: list[Section] = []
    seen: set[int] = set()
    for line in _read(path).splitlines():
        if m := _V1_VOLUME.match(line):
            volume = m.group(1)
            continue
        if m := _V1_CHAPTER.match(line):
            number = int(m.group(1))
            # The table of contents is repeated further down the source; take
            # each chapter number once so the count is chapters, not lines.
            if number in seen:
                continue
            seen.add(number)
            out.append(Section("v1", volume, m.group(2)))
    if not out:
        raise PreservationBroken(f"no chapters parsed from {path.name}")
    return out


def v2_sections(path: Path | None = None) -> list[Section]:
    """The substantive named sections of the complete v2 document."""
    path = path or V2
    volume = ""
    out: list[Section] = []
    closer_recorded = False
    lines = _read(path).splitlines()
    # Everything above the rule is this repository's provenance note, not the
    # source. Parsing it would report our own header as unpreserved content.
    for start, line in enumerate(lines):
        if line.startswith("=" * 20):
            lines = lines[start + 1 :]
            break
    else:
        raise PreservationBroken(f"{path.name} has no provenance rule; refusing to guess where the source starts")
    for i, line in enumerate(lines):
        stripped = line.strip()
        if not stripped or line.startswith("\t"):
            continue
        if m := _V2_VOLUME.match(stripped):
            volume = m.group(1)
            continue
        if stripped in _V2_BOILERPLATE or stripped in _V2_BANNER:
            continue
        if stripped == _V2_PER_VOLUME_CLOSER:
            # Stamped once per volume; the title is one item, not twenty.
            if closer_recorded:
                continue
            closer_recorded = True
        # A heading is a short line followed by its statement paragraph. Body
        # paragraphs are long; volume banners were consumed above.
        if len(stripped) > 90 or stripped.endswith("."):
            continue
        if i + 1 < len(lines) and not lines[i + 1].strip():
            continue
        out.append(Section("v2", volume, stripped))
    if not out:
        raise PreservationBroken(f"no sections parsed from {path.name}")
    return out


def _corpus(corpus_dir: Path | None = None) -> tuple[set[str], int]:
    """Every *listed* line across the Group 4 documents, normalised."""
    corpus_dir = corpus_dir or SPECS
    documents = sorted(corpus_dir.glob("GROUP4_*.md"))
    if not documents:
        raise PreservationBroken(f"no GROUP4_*.md documents found in {corpus_dir}")
    listed: set[str] = set()
    for doc in documents:
        for line in doc.read_text(encoding="utf-8").splitlines():
            if _LISTED.match(line):
                listed.add(_normalise(line))
    if not listed:
        raise PreservationBroken(
            f"{len(documents)} documents read but no listed lines found — the corpus parser matched nothing"
        )
    return listed, len(documents)


def _normalise(text: str) -> str:
    return re.sub(r"[^a-z0-9 ]+", " ", text.lower()).strip()


def check(
    sources: list[Path] | None = None,
    corpus_dir: Path | None = None,
) -> Report:
    """Which source titles are no longer listed anywhere in the corpus?"""
    if sources is None:
        sections = v1_chapters() + v2_sections()
    else:
        sections = []
        for path in sources:
            sections.extend(
                v1_chapters(path) if path.name.endswith(".txt") and "v2" not in path.name else v2_sections(path)
            )

    listed, documents_read = _corpus(corpus_dir)
    blob = "\n".join(sorted(listed))
    missing = [s for s in sections if _normalise(s.title) not in blob]
    return Report(missing=missing, titles_checked=len(sections), documents_read=documents_read)


def main() -> int:
    try:
        report = check()
    except PreservationBroken as exc:
        print(f"REFUSED — {exc}", file=sys.stderr)
        return 2
    print(
        f"group4 preservation: {report.titles_checked} source titles · "
        f"{report.documents_read} documents · {len(report.missing)} missing"
    )
    for s in report.missing:
        print(f"  MISSING  [{s.source}] {s.volume} — {s.title}")
    return 1 if report.missing else 0


if __name__ == "__main__":
    raise SystemExit(main())
