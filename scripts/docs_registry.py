# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""The document registry — Group 3 Chapter 2.

Every document in this repository, what it is, who owns it, and what it claims to
be authoritative about. Group 3 opened with five measured findings and every one
of them is a failure this file exists to make impossible to repeat:

* four documents describing the same API, two of them stating different base URLs
  and nothing marking which is authoritative;
* `CONTRIBUTING.md` and `DEPLOYMENT.md` existing twice, at different lengths;
* roughly 126 files reachable only by somebody who already knows the filename;
* six dated audit snapshots filed beside the living architecture;
* no decision records at all.

## Generated from the filesystem, enriched by hand, never the reverse

A registry written from memory omits exactly the files nobody remembers, which are
the ones most likely to be stale. `generate()` therefore walks the tree and MERGES:
human annotations survive, and unknown files arrive as `draft` with no owner so
that they are visible rather than absent.

## The ratchet, and why the obvious design would have been a dead control

Group 3 Chapter 2 says CI fails while any entry lacks an owner. Applied literally
on day one that fails on 190 documents, and a check that must be disabled to get
any work done is a check that gets disabled — which is `hopefx-dead-controls`
committed in the module that exists to prevent it.

So the enforcement is a **ratchet**. A baseline records what was already wrong at
adoption. Anything NEW fails immediately; the existing debt may only ever shrink.
Two shapes, chosen per rule:

* **Counted** for the large, uniform debt (unowned documents). The count may not
  increase.
* **Named** for the small, specific debt (a subject claimed twice). Each is listed
  explicitly, so a new collision fails even while a known one stands.

Named is better wherever the list is short enough to read, because a count tells
you the debt grew and a name tells you what grew.
"""

from __future__ import annotations

import argparse
import re
import tomllib
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Final

REPO = Path(__file__).resolve().parent.parent
REGISTRY_PATH = REPO / "docs" / "REGISTRY.toml"

#: Where documents live. Anything matching here must have an entry.
DOC_GLOBS: Final[tuple[str, ...]] = ("docs/**/*.md", "docs/**/*.txt", "*.md")

#: Directories whose contents are not governed documents.
EXCLUDED: Final[tuple[str, ...]] = ("node_modules", ".venv", "__pycache__", "site", "dashboard/dist")

#: Tiers, ordered by how the document AGES — see Group 3 Chapter 1. This ordering
#: is the taxonomy: T0 changes by amendment, T3 never changes at all.
TIERS: Final[tuple[str, ...]] = ("T0", "T1", "T2", "T3", "T4")

STATES: Final[tuple[str, ...]] = ("draft", "active", "superseded", "archived")

#: Tiers that claim to be authoritative about a subject. T3 is a dated record and
#: T4 is working material; neither claims authority, so neither can collide.
#:
#: This spans THREE tiers rather than only T2 because the first version checked T2
#: alone and therefore could not see the root `CONTRIBUTING.md` (T0) diverging from
#: `docs/CONTRIBUTING.md` (T2) — one of the five findings this module was built to
#: catch. A constitution document and a reference about the same subject is exactly
#: the collision that matters most, because the reader trusts both.
AUTHORITY_TIERS: Final[frozenset[str]] = frozenset({"T0", "T1", "T2"})

#: Root documents that bind all work. Amendment only, two-human approval.
CONSTITUTION: Final[frozenset[str]] = frozenset(
    {
        "CLAUDE.md",
        "AGENTS.md",
        "CONTRIBUTING.md",
        "CODE_OF_CONDUCT.md",
        "CLA.md",
        "NOTICE.md",
        "LICENSE-COMMERCIAL.md",
    }
)

#: A dated filename is a snapshot: correct at its date for ever, and never
#: revised. That is a T3 record, not a living reference, and filing it as one is
#: the category confusion Finding 4 measured.
DATED = re.compile(r"20\d{2}[-_]\d{2}[-_]\d{2}")


@dataclass
class Entry:
    path: str
    tier: str = "T2"
    subject: str = ""
    owner: str = ""
    state: str = "draft"
    superseded_by: str = ""
    note: str = ""

    def as_toml(self) -> str:
        lines = ["[[document]]", f'path = "{self.path}"']
        lines.append(f'tier = "{self.tier}"')
        if self.subject:
            lines.append(f'subject = "{self.subject}"')
        lines.append(f'owner = "{self.owner}"')
        lines.append(f'state = "{self.state}"')
        if self.superseded_by:
            lines.append(f'superseded_by = "{self.superseded_by}"')
        if self.note:
            lines.append(f'note = "{self.note}"')
        return "\n".join(lines)


@dataclass
class Baseline:
    """What was already wrong when the registry was adopted.

    The ratchet. New violations fail; recorded ones may only shrink.
    """

    adopted: str = ""
    unowned_count: int = 0
    known_duplicate_subjects: list[str] = field(default_factory=list)


@dataclass
class Finding:
    rule: str
    detail: str
    #: True when this violation is new — i.e. not covered by the baseline.
    blocking: bool = True


def _excluded(path: Path) -> bool:
    return any(part in EXCLUDED for part in path.parts)


def discover(root: Path | None = None) -> list[str]:
    """Every governed document on disk, as repo-relative POSIX paths, sorted."""
    base = root or REPO
    found: set[str] = set()
    for pattern in DOC_GLOBS:
        for path in base.glob(pattern):
            if path.is_file() and not _excluded(path.relative_to(base)):
                found.add(path.relative_to(base).as_posix())
    return sorted(found)


def infer_tier(path: str) -> str:
    """A first guess, to be corrected by a human. Never treated as authority.

    Ordered most-specific first: a dated file inside `docs/archive/` is archived
    working material, and the archive location is the stronger signal.
    """
    name = Path(path).name
    if "/" not in path and name in CONSTITUTION:
        return "T0"
    if path.startswith("docs/ai/specs/") or path.startswith("docs/ai/BACKLOG_GROUPS"):
        return "T1"
    if path.startswith("docs/archive/") or "/plans/" in path:
        return "T4"
    if DATED.search(name):
        return "T3"
    return "T2"


def infer_subject(path: str) -> str:
    """What a T2 document claims to be authoritative about.

    Deliberately coarse: `API.md`, `API_GUIDE.md`, `API_REFERENCE.md` and
    `API_ENDPOINTS.md` all reduce to `api`, which is the point — they are four
    documents about one subject and the registry should say so on the first run.
    """
    stem = Path(path).stem.lower()
    stem = re.sub(r"[-_]?20\d{2}[-_]\d{2}[-_]\d{2}", "", stem)
    stem = re.sub(r"^(the|a)[-_]", "", stem)
    for suffix in ("_guide", "_reference", "_endpoints", "_overview", "_docs", "_readme", "_api_reference"):
        if stem.endswith(suffix):
            stem = stem[: -len(suffix)]
            break
    return stem.strip("_-") or Path(path).stem.lower()


def load(path: Path | None = None) -> tuple[list[Entry], Baseline]:
    """Read the registry. A missing file is an empty registry, not an error."""
    target = path or REGISTRY_PATH
    if not target.exists():
        return [], Baseline()
    data = tomllib.loads(target.read_text(encoding="utf-8"))
    entries = [
        Entry(
            path=d["path"],
            tier=d.get("tier", "T2"),
            subject=d.get("subject", ""),
            owner=d.get("owner", ""),
            state=d.get("state", "draft"),
            superseded_by=d.get("superseded_by", ""),
            note=d.get("note", ""),
        )
        for d in data.get("document", [])
    ]
    b = data.get("baseline", {})
    baseline = Baseline(
        adopted=b.get("adopted", ""),
        unowned_count=int(b.get("unowned_count", 0)),
        known_duplicate_subjects=list(b.get("known_duplicate_subjects", [])),
    )
    return entries, baseline


def generate(existing: list[Entry], discovered: list[str]) -> list[Entry]:
    """Merge the filesystem into the registry, preserving every human annotation.

    New files arrive as `draft` with no owner. Entries whose file is gone are
    dropped here and reported by `check` — the generator does not decide that a
    document should disappear, it only stops inventing one that is not there.
    """
    by_path = {e.path: e for e in existing}
    out: list[Entry] = []
    for path in discovered:
        if path in by_path:
            out.append(by_path[path])
            continue
        tier = infer_tier(path)
        out.append(
            Entry(
                path=path,
                tier=tier,
                subject=infer_subject(path) if tier in AUTHORITY_TIERS else "",
                owner="",
                state="archived" if tier == "T4" and path.startswith("docs/archive/") else "draft",
            )
        )
    return sorted(out, key=lambda e: e.path)


def dump(entries: list[Entry], baseline: Baseline) -> str:
    header = (
        "# Document registry — Group 3 Chapter 2. GENERATED skeleton, hand-enriched.\n"
        "#\n"
        "# Regenerate with:  python scripts/docs_registry.py --generate\n"
        "# Check with:       python scripts/docs_registry.py --check\n"
        "#\n"
        "# Human edits to tier, subject, owner, state and note are PRESERVED across\n"
        "# regeneration. Only the set of paths is derived from disk.\n\n"
    )
    b = [
        "[baseline]",
        f'adopted = "{baseline.adopted}"',
        "# The ratchet. These record what was already wrong at adoption so that NEW",
        "# violations fail while existing debt is paid down. They may only shrink.",
        f"unowned_count = {baseline.unowned_count}",
        "known_duplicate_subjects = [" + ", ".join(f'"{s}"' for s in sorted(baseline.known_duplicate_subjects)) + "]",
        "",
    ]
    return header + "\n".join(b) + "\n" + "\n\n".join(e.as_toml() for e in entries) + "\n"


def check(entries: list[Entry], discovered: list[str], baseline: Baseline) -> list[Finding]:
    """Every violation, with `blocking` set by the ratchet.

    Returns findings rather than raising, so a caller can report all of them. A
    checker that stops at the first problem makes a reader fix one thing, run
    again, and find the next — three times for a three-line defect.
    """
    findings: list[Finding] = []
    registered = {e.path for e in entries}
    on_disk = set(discovered)

    for path in sorted(on_disk - registered):
        findings.append(Finding("unregistered", f"{path} is on disk with no registry entry", True))
    for path in sorted(registered - on_disk):
        findings.append(Finding("dangling", f"{path} has a registry entry and no file", True))

    for e in entries:
        if e.tier not in TIERS:
            findings.append(Finding("bad_tier", f"{e.path} has tier {e.tier!r}; expected one of {TIERS}", True))
        if e.state not in STATES:
            findings.append(Finding("bad_state", f"{e.path} has state {e.state!r}", True))
        if e.state == "superseded" and not e.superseded_by:
            findings.append(
                Finding("superseded_without_successor", f"{e.path} is superseded and names no successor", True)
            )

    # A subject claimed by two ACTIVE T2 documents is Finding 1: two authoritative
    # statements about one thing, with nothing saying which wins.
    claims: dict[str, list[str]] = {}
    for e in entries:
        if e.tier in AUTHORITY_TIERS and e.subject and e.state in ("active", "draft"):
            claims.setdefault(e.subject, []).append(e.path)
    for subject, paths in sorted(claims.items()):
        if len(paths) > 1:
            findings.append(
                Finding(
                    "duplicate_subject",
                    f"subject {subject!r} is claimed by {len(paths)} documents: {', '.join(sorted(paths))}",
                    blocking=subject not in baseline.known_duplicate_subjects,
                )
            )

    unowned = [e.path for e in entries if not e.owner.strip()]
    if len(unowned) > baseline.unowned_count:
        findings.append(
            Finding(
                "unowned_increased",
                f"{len(unowned)} documents have no owner; the baseline allows {baseline.unowned_count}. "
                "A document nobody owns is one nobody will notice is wrong.",
                True,
            )
        )
    elif unowned:
        findings.append(
            Finding(
                "unowned",
                f"{len(unowned)} documents have no owner (baseline {baseline.unowned_count}, not increased)",
                False,
            )
        )
    return findings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Document registry: generate and check.")
    parser.add_argument("--generate", action="store_true", help="Merge the filesystem into the registry")
    parser.add_argument("--check", action="store_true", help="Report violations; non-zero exit if any block")
    parser.add_argument("--adopt", action="store_true", help="Set the baseline from the current state (once)")
    args = parser.parse_args(argv)

    entries, baseline = load()
    discovered = discover()

    if args.generate or args.adopt:
        entries = generate(entries, discovered)
        if args.adopt:
            baseline.adopted = date.today().isoformat()
            baseline.unowned_count = sum(1 for e in entries if not e.owner.strip())
            dupes = {
                e.subject
                for e in entries
                if e.tier in AUTHORITY_TIERS
                and e.subject
                and sum(1 for o in entries if o.tier in AUTHORITY_TIERS and o.subject == e.subject) > 1
            }
            baseline.known_duplicate_subjects = sorted(dupes)
        REGISTRY_PATH.parent.mkdir(parents=True, exist_ok=True)
        REGISTRY_PATH.write_text(dump(entries, baseline), encoding="utf-8")
        print(f"registry: {len(entries)} documents written to {REGISTRY_PATH.relative_to(REPO)}")

    if args.check:
        findings = check(entries, discovered, baseline)
        blocking = [f for f in findings if f.blocking]
        for f in findings:
            print(f"{'FAIL' if f.blocking else 'note'}  [{f.rule}] {f.detail}")
        if not findings:
            print("registry: clean")
        print(f"\n{len(blocking)} blocking, {len(findings) - len(blocking)} baselined")
        return 1 if blocking else 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
