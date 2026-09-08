# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""What is left to build or fix — Group 3 Chapter 11.

One command that answers the question from **measured sources** rather than from
memory or a hand-maintained list. Run it and the answer is current; a list typed
into a message is wrong the moment somebody acts on it.

    python scripts/backlog_report.py

## Every number here is derived, and an unmeasured one says so

Rule 2 from Group 2: an unmeasured value is absent, never zero. Where a source
cannot be read, this report prints `unmeasured` and the reason. A report that
silently renders a missing measurement as `0` is worse than one that omits the
line, because zero looks like success.

## What it reads

| Source | Question it answers |
|---|---|
| `ai/hub/capabilities.py` | Which spec capabilities are not live? |
| `scripts/capability_callers.py` | Which live ones may have no caller? |
| `docs/REGISTRY.toml` | Which documents are unowned or claim a contested subject? |
| `docs/FRESHNESS_BASELINE.toml` | How many stale references are outstanding? |
| The four master specifications | Which ranked gaps remain? |
| `GROUP4_CONSTITUTION.md` | Which architectural invariants are not yet AVAILABLE? |
| `invariants/registry.py` | Does every predicate the constitution cites still exist? |
| `scripts/group4_preservation.py` | Has any title from either Group 4 source been dropped? |

The ranked gap lists in Groups 2 and 3 are prose, and prose is the one thing here
that is *told* rather than measured. It is labelled as such: `TOLD` in the source
column, so no reader mistakes a written intention for a measurement.
"""

from __future__ import annotations

import re
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent


@dataclass
class Section:
    title: str
    lines: list[str] = field(default_factory=list)
    note: str = ""


def _capabilities() -> Section:
    s = Section("1. Specification capabilities not yet live  [MEASURED]")
    try:
        from ai.hub.capabilities import REGISTRY, coverage, verify
    except Exception as exc:  # pragma: no cover - import failure is itself the finding
        s.note = f"unmeasured — the capability registry could not be imported: {exc}"
        return s

    c = coverage()
    report = verify()
    s.lines.append(
        f"{c['total']} rows · {c['live']} live · {c['staged']} staged · {c['planned']} planned "
        f"· {report.resolved}/{report.checked} evidence resolves · {len(report.discrepancies)} discrepancies"
    )
    for cap in REGISTRY:
        if cap.state != "live":
            s.lines.append(f"  §{cap.section:<4} {cap.state:<8} {cap.id:<38} {cap.title}")
    return s


def _callers() -> Section:
    s = Section("2. Live capabilities with no production caller  [MEASURED — a SCREEN, not a verdict]")
    try:
        from scripts.capability_callers import SweepBroken, sweep

        rows = sweep()
    except SweepBroken as exc:
        s.note = f"unmeasured — {exc}"
        return s
    except Exception as exc:  # pragma: no cover
        s.note = f"unmeasured — the caller sweep failed: {exc}"
        return s

    flagged = [r for r in rows if r.uncalled]
    s.lines.append(f"{len(rows)} rows screened · {len(flagged)} flagged")
    s.lines.append("Symbol matching misses aliases and dynamic lookup. Each row is one to INSPECT.")
    for r in sorted(flagged, key=lambda r: (r.production_files, r.section))[:12]:
        s.lines.append(f"  §{r.section:<4} {r.capability:<38} {r.symbol:<26} prod={r.production_files}")
    if len(flagged) > 12:
        s.lines.append(f"  … and {len(flagged) - 12} more — run scripts/capability_callers.py for all")
    return s


def _documents() -> Section:
    s = Section("3. Documentation debt  [MEASURED]")
    try:
        from scripts.docs_registry import load

        entries, baseline = load()
    except Exception as exc:  # pragma: no cover
        s.note = f"unmeasured — the document registry could not be read: {exc}"
        return s

    if not entries:
        s.note = "unmeasured — the document registry is empty; run scripts/docs_registry.py --generate"
        return s

    unowned = sum(1 for e in entries if not e.owner.strip())
    s.lines.append(f"{len(entries)} documents registered · {unowned} with no owner")
    for subject in baseline.known_duplicate_subjects:
        claimants = sorted(e.path for e in entries if e.subject == subject)
        s.lines.append(f"  subject '{subject}' claimed by {len(claimants)}: {', '.join(claimants)}")

    fresh = REPO / "docs" / "FRESHNESS_BASELINE.toml"
    if fresh.exists():
        data = tomllib.loads(fresh.read_text(encoding="utf-8"))
        s.lines.append(f"  {len(data.get('known', []))} stale references outstanding in living documents")
    else:
        s.lines.append("  stale references: unmeasured — no freshness baseline has been adopted")
    return s


_GAP_ROW = re.compile(r"^\|\s*(\d+)\s*\|\s*(.+?)\s*\|\s*([\w\s,]+?)\s*\|\s*\*{0,2}(\w+)\*{0,2}\s*\|")


#: A finished row is struck through rather than deleted, so the ranking keeps its
#: history: `| ~~1~~ | ~~Document registry with owners and tiers~~ | 2 | **DONE** |`.
_DONE_GAP_ROW = re.compile(r"^\|\s*~~\d+~~\s*\|")


#: The gap list is one table among many. Anchoring to its heading stops the parse
#: matching, for instance, the disaster-recovery tier table, whose rows also begin
#: `| 1 |` — which the first version did, reporting "Pod/node loss" as a gap.
_GAP_HEADING = re.compile(r"^#+\s*The prioritised gap list\s*$", re.M)


def _ranked_gaps(path: Path, label: str) -> Section:
    s = Section(f"{label}  [TOLD — prose, not measured]")
    if not path.exists():
        s.note = f"unmeasured — {path.name} is not present"
        return s
    text = path.read_text(encoding="utf-8")
    heading = _GAP_HEADING.search(text)
    if heading is None:
        s.note = "unmeasured — the document has no section headed 'The prioritised gap list'"
        return s
    # Stop at the next heading of the same or higher level.
    rest = text[heading.end() :]
    end = re.search(r"^#{1,3} ", rest, re.M)
    table = rest[: end.start()] if end else rest
    rows = [m.groups() for line in table.splitlines() if (m := _GAP_ROW.match(line))]
    done = len([line for line in table.splitlines() if _DONE_GAP_ROW.match(line)])
    if not rows:
        s.note = "unmeasured — no ranked gap table found in the document"
        return s
    if done:
        # Without this the list appears to start at 5, and a reader cannot tell
        # "four are finished" from "the parser lost four rows".
        s.lines.append(f"  ({done} already done and struck through in the document; the rest follow)")
    for num, gap, chapter, priority in rows:
        s.lines.append(f"  {num:>2}. [{priority:<8}] {gap}   (ch {chapter})")
    return s


#: `| INV-07 | Versioning and lifecycle rules | PARTIAL | ... |`. The status cell
#: may be wrapped in markdown bold, which is how the constitution marks the two
#: extremes — matching on the literal `**NEW**` would miss a plain `NEW`.
_INV_ROW = re.compile(r"^\|\s*(INV-\d+)\s*\|\s*(.+?)\s*\|\s*\*{0,2}([A-Z]+)\*{0,2}\s*(?:—[^|]*)?\|")

#: Every predicate the constitution cites by name, in backticks.
_NAMED_VERIFIER = re.compile(r"`((?:verify|catastrophic)_[a-z0-9_]+)`")


def _group4_invariants(path: Path) -> Section:
    """The constitution's own status column for INV-01…INV-21.

    Told, not measured: the statuses were measured when the document was written,
    but this function reads the document, not the code. The measured half is
    :func:`_group4_verifiers` below.
    """
    s = Section("6. Group 4 — constitutional invariants not yet AVAILABLE  [TOLD — the constitution's status column]")
    if not path.exists():
        s.note = f"unmeasured — {path.name} is not present"
        return s
    rows = [m.groups() for line in path.read_text(encoding="utf-8").splitlines() if (m := _INV_ROW.match(line))]
    if not rows:
        s.note = "unmeasured — the constitution has no INV-nn status table"
        return s
    outstanding = [r for r in rows if r[2] != "AVAILABLE"]
    s.lines.append(f"{len(rows)} invariants recorded · {len(outstanding)} not yet AVAILABLE")
    for ident, name, status in outstanding:
        s.lines.append(f"  {ident}  [{status:<8}] {name}")
    return s


def _group4_verifiers(path: Path) -> Section:
    """Does every predicate the constitution names still exist in the code?

    A constitution that cites `verify_goal_alignment` after somebody renamed it
    is a document pointing at nothing, and reads exactly like one that is
    correct. This is the only Group 4 line that is measured: the names come from
    the document, the resolution comes from :mod:`invariants.registry`.
    """
    s = Section("7. Group 4 — invariant verifiers the constitution names  [MEASURED]")
    if not path.exists():
        s.note = f"unmeasured — {path.name} is not present"
        return s
    named = sorted(set(_NAMED_VERIFIER.findall(path.read_text(encoding="utf-8"))))
    if not named:
        s.note = "unmeasured — the constitution names no predicate"
        return s
    try:
        from invariants.registry import discover_predicates

        known = {name for names in discover_predicates().values() for name in names}
    except Exception as exc:  # pragma: no cover - import failure is itself the finding
        s.note = f"unmeasured — the invariant registry could not be read: {exc}"
        return s
    if not known:
        s.note = "unmeasured — the invariant registry discovered no predicates"
        return s

    missing = [n for n in named if n not in known]
    s.lines.append(
        f"{len(named)} named by the constitution · {len(named) - len(missing)} resolve · {len(missing)} do not"
    )
    for n in missing:
        s.lines.append(f"  MISSING  {n} — named in the constitution, absent from invariants/")
    return s


def _group4_preservation(corpus_dir: Path | None = None) -> Section:
    """Is every title from both Group 4 sources still listed somewhere?

    The source opens with one rule — ADD AND EXPAND; NEVER SILENTLY REMOVE — and
    this is the mechanical form of it. It outranks the ranked gap lists: a gap is
    work not yet done, an omission is work that has disappeared.
    """
    s = Section("8. Group 4 — source preservation: nothing dropped from either source  [MEASURED]")
    try:
        from scripts.group4_preservation import PreservationBroken, check

        report = check(corpus_dir=corpus_dir)
    except PreservationBroken as exc:
        s.note = f"unmeasured — {exc}"
        return s
    except Exception as exc:  # pragma: no cover - import failure is itself the finding
        s.note = f"unmeasured — the preservation check failed: {exc}"
        return s

    s.lines.append(
        f"{report.titles_checked} source titles across 2 sources · "
        f"{report.documents_read} documents · {len(report.missing)} missing"
    )
    for m in report.missing:
        s.lines.append(f"  MISSING  [{m.source}] {m.volume} — {m.title}")
    return s


def build() -> list[Section]:
    specs = REPO / "docs" / "ai" / "specs"
    return [
        _capabilities(),
        _callers(),
        _documents(),
        _ranked_gaps(specs / "GROUP2_platform_engineering_operations_governance.md", "4. Group 2 — platform gaps"),
        _ranked_gaps(
            specs / "GROUP3_documentation_knowledge_architecture_governance.md", "5. Group 3 — knowledge gaps"
        ),
        _group4_invariants(specs / "GROUP4_CONSTITUTION.md"),
        _group4_verifiers(specs / "GROUP4_CONSTITUTION.md"),
        _group4_preservation(),
    ]


def render(sections: list[Section]) -> str:
    out: list[str] = ["WHAT IS LEFT TO BUILD OR FIX", "=" * 78, ""]
    for s in sections:
        out.append(s.title)
        out.append("-" * len(s.title))
        if s.note:
            out.append(f"  {s.note}")
        out.extend(s.lines)
        out.append("")
    out.append("Generated from the repository. Re-run rather than trusting a copy.")
    return "\n".join(out)


def main() -> int:
    print(render(build()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
