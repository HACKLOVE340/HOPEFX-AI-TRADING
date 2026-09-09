#!/usr/bin/env python3
# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""Architecture Decision Records — Group 3 Chapter 6.

    python scripts/adr.py --check              # validate every record
    python scripts/adr.py --list               # what has been decided
    python scripts/adr.py new "Pin Python"     # start the next record

## Why numbered files rather than the narrative that already exists

`docs/ai/AI_HUB_DECISIONS.md` is a good document and not a system. Group 3
Chapter 6 names its three limits precisely: it cannot be pointed at from a code
comment, it cannot be superseded in part, and it grows without bound. Numbered,
individually addressable, immutable records fix exactly those three and lose
nothing but the pleasure of a continuous narrative.

The cost of not having them is **re-litigation** — a decision whose reasoning is
not recorded is re-argued whenever someone new meets it, and sometimes reversed
by someone who does not know what it was protecting. This session produced two:
§E20 corrected a "verified by execution" claim written in the very phase that
made the check fail, and §E21 reversed a two-phase-old conclusion whose premise
nobody had re-examined. Both were recoverable only because the reasoning had
been written down somewhere.

## The rules, and why each one is a defect that already happened

* **Two options, or it was not a decision.** The spec's own rule. A record with
  one option documents an implementation and reads as justification after the
  fact.
* **Every section the spec names, none of them empty.** A heading with nothing
  under it is what a template leaves behind, and it passes a naive check while
  telling a reader nothing.
* **Immutable once accepted**, the only permitted edit being a status becoming
  `superseded by NNNN`. A record that can be rewritten is a record of what we
  currently believe we decided.
* **A supersede reference must resolve.** Pointing at a record that does not
  exist is worse than no status: it tells a reader their answer is somewhere.
* **Sequential and gapless.** So "see 0007" is stable for ever, and so a gap
  cannot hide a deleted record.

Immutability is checked against git rather than a hash manifest, because a
manifest is a second thing to edit and git already holds the history.
"""

from __future__ import annotations

import argparse
import dataclasses
import datetime as dt
import re
import subprocess  # nosec B404 — git, fixed args
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DECISIONS = ROOT / "docs" / "decisions"

#: Exactly the sections Group 3 Chapter 6 tabulates, in its order.
REQUIRED_SECTIONS: tuple[str, ...] = (
    "Context",
    "Options considered",
    "Decision",
    "Consequences",
    "Evidence",
)

_FILENAME = re.compile(r"^(\d{4})-[a-z0-9][a-z0-9-]*\.md$")
_HEADING = re.compile(r"^#\s+(\d{4})\.\s+(.+?)\s*$", re.MULTILINE)
_STATUS = re.compile(r"^-\s*Status:\s*(.+?)\s*$", re.MULTILINE)
_SUPERSEDED = re.compile(r"^superseded by (\d{4})$")
_SECTION = re.compile(r"^##\s+(.+?)\s*$", re.MULTILINE)
#: A bullet is an option. Nested continuation lines are not.
_OPTION = re.compile(r"^[-*]\s+\S", re.MULTILINE)


@dataclasses.dataclass(frozen=True)
class Problem:
    path: Path
    message: str


@dataclasses.dataclass(frozen=True)
class Record:
    path: Path
    number: int
    title: str
    status: str
    sections: dict[str, str]

    @property
    def options(self) -> list[str]:
        return _OPTION.findall(self.sections.get("Options considered", ""))

    @property
    def superseded_by(self) -> int | None:
        match = _SUPERSEDED.match(self.status)
        return int(match.group(1)) if match else None


def _sections(text: str) -> dict[str, str]:
    """Heading -> body. Bodies are kept so emptiness can be judged."""
    found: dict[str, str] = {}
    matches = list(_SECTION.finditer(text))
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        found[match.group(1)] = text[match.end() : end].strip()
    return found


def parse(path: Path) -> Record:
    text = path.read_text(encoding="utf-8")
    heading = _HEADING.search(text)
    status = _STATUS.search(text)
    return Record(
        path=path,
        number=int(heading.group(1)) if heading else -1,
        title=heading.group(2) if heading else "",
        status=status.group(1) if status else "",
        sections=_sections(text),
    )


def records(directory: Path = DECISIONS) -> list[Record]:
    if not directory.exists():
        return []
    return [parse(p) for p in sorted(directory.glob("*.md")) if _FILENAME.match(p.name)]


def next_number(directory: Path = DECISIONS) -> int:
    existing = records(directory)
    return max((r.number for r in existing), default=0) + 1


def validate_directory(directory: Path = DECISIONS) -> list[Problem]:
    problems: list[Problem] = []
    if not directory.exists():
        return [Problem(directory, "docs/decisions/ does not exist")]

    found = records(directory)
    numbers = {r.number for r in found}

    for path in sorted(directory.glob("*.md")):
        if path.name == "README.md":
            continue
        if not _FILENAME.match(path.name):
            problems.append(Problem(path, f"{path.name} is not NNNN-short-title.md, so it cannot be referenced stably"))

    for record in found:
        problems.extend(_validate_one(record, numbers))

    # Duplicates and gaps, once, across the set.
    seen: dict[int, Path] = {}
    for record in found:
        if record.number in seen:
            problems.append(
                Problem(
                    record.path,
                    f"duplicate decision number {record.number:04d}, also {seen[record.number].name} — "
                    "two records with one number make every reference ambiguous",
                )
            )
        else:
            seen[record.number] = record.path

    if found:
        highest = max(numbers)
        for expected in range(1, highest + 1):
            if expected not in numbers:
                problems.append(
                    Problem(
                        directory,
                        f"decision {expected:04d} is missing — numbering must be gapless, because a gap "
                        "is indistinguishable from a record somebody deleted instead of superseding",
                    )
                )
    return problems


def _validate_one(record: Record, numbers: set[int]) -> list[Problem]:
    problems: list[Problem] = []
    path = record.path

    if record.number < 0:
        return [Problem(path, "no `# NNNN. Title` heading")]

    filename_number = int(_FILENAME.match(path.name).group(1))  # type: ignore[union-attr]
    if filename_number != record.number:
        return [
            Problem(
                path,
                f"filename says {filename_number:04d} and the heading says {record.number:04d}; "
                "a reference to either would find the wrong record",
            )
        ]

    status = record.status
    if status in {"proposed", "accepted"}:
        pass
    elif _SUPERSEDED.match(status):
        target = record.superseded_by
        if target not in numbers:
            problems.append(
                Problem(
                    path,
                    f"superseded by {target:04d}, which does not exist — a dangling supersede is worse "
                    "than no status, because it tells a reader their answer is somewhere",
                )
            )
    else:
        problems.append(Problem(path, f"status {status!r} is not proposed, accepted, or `superseded by NNNN`"))

    for section in REQUIRED_SECTIONS:
        if section not in record.sections:
            problems.append(Problem(path, f"no `## {section}` section"))
        elif not record.sections[section].strip():
            problems.append(
                Problem(path, f"`## {section}` is empty — a heading with nothing under it is a template, not a record")
            )

    if "Options considered" in record.sections and len(record.options) < 2:
        problems.append(
            Problem(
                path,
                f"only {len(record.options)} option listed; an ADR needs at least two options, or it "
                "documents an implementation rather than a decision",
            )
        )
    return problems


def immutability_problems(directory: Path = DECISIONS) -> list[Problem]:
    """Accepted records must not change, except their status line.

    Checked against git rather than a hash manifest: a manifest is a second file
    to edit, and the history is already authoritative. A record git has never
    seen is new, which is the one time editing it freely is correct.
    """
    problems: list[Problem] = []
    for record in records(directory):
        relative = record.path.relative_to(ROOT).as_posix()
        committed = _git_show(f"HEAD:{relative}")
        if committed is None:
            continue  # new in the working tree
        if _without_status(committed) != _without_status(record.path.read_text(encoding="utf-8")):
            problems.append(
                Problem(
                    record.path,
                    "an accepted record was edited; supersede it with a new record instead — the only "
                    "change an accepted ADR may carry is its status becoming `superseded by NNNN`",
                )
            )
    return problems


def _without_status(text: str) -> str:
    return _STATUS.sub("- Status: <ignored>", text)


def _git_show(reference: str) -> str | None:
    try:
        result = subprocess.run(  # nosec B603 B607 — fixed args, no shell
            ["git", "show", reference],
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
        )
    except Exception:
        return None
    return result.stdout if result.returncode == 0 else None


TEMPLATE = """# {number:04d}. {title}

- Status: proposed
- Date: {date}

## Context

<What forced a decision. Facts, not preferences.>

## Options considered

- **<Option A>.** Costs: <what it costs>.
- **<Option B>.** Costs: <what it costs>.

## Decision

<What was chosen.>

## Consequences

<What this makes easy, and what it makes hard.>

## Evidence

<Measurements that informed it. A command someone can re-run beats a claim.>
"""


def slugify(title: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
    return slug or "decision"


def create(title: str, directory: Path = DECISIONS) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    number = next_number(directory)
    path = directory / f"{number:04d}-{slugify(title)}.md"
    path.write_text(
        TEMPLATE.format(number=number, title=title, date=dt.date.today().isoformat()),
        encoding="utf-8",
    )
    return path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Architecture Decision Records — Group 3 Chapter 6.")
    parser.add_argument("--check", action="store_true", help="validate every record; non-zero exit on a problem")
    parser.add_argument("--list", action="store_true", help="what has been decided")
    parser.add_argument("new", nargs="?", help="start the next record with this title")
    args = parser.parse_args(argv)

    if args.new:
        path = create(args.new)
        print(f"wrote {path.relative_to(ROOT)}")
        print("Fill in every section. Two options minimum, or it is not a decision.")
        return 0

    if args.list:
        for record in records():
            print(f"  {record.number:04d}  {record.status:<22}  {record.title}")
        return 0

    problems = validate_directory() + immutability_problems()
    for problem in problems:
        try:
            name = problem.path.relative_to(ROOT)
        except ValueError:
            name = problem.path
        print(f"FAIL  {name}: {problem.message}", file=sys.stderr)
    total = len(records())
    if problems:
        print(f"\nadr: {len(problems)} problem(s) across {total} record(s)", file=sys.stderr)
        return 1
    print(f"adr: {total} decision record(s), all well formed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
