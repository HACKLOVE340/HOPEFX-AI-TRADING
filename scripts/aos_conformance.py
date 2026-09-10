# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""The AOS conformance register, made checkable instead of read.

    python scripts/aos_conformance.py            # report
    python scripts/aos_conformance.py --check    # exit non-zero on a broken claim

`docs/ai/specs/AOS_INVARIANT_REGISTER.toml` maps the 26 invariants of §30 of the
MASTER_AI_OPERATING_SYSTEM specification onto what *this* repository already
enforces. The specification's own §32 says to inspect and preserve before
extending, and its §1 says never to mark an item VERIFIED without direct
evidence. This script is how that rule survives contact with a codebase that
keeps moving.

## Why a script and not a document

A prose conformance map is a claim that was true once. Rename a predicate and
every row naming it keeps reading as coverage — the map cannot tell you it has
gone stale, and a reader acts on it without checking. That is F255 exactly: a
checker that reads prose is not reading code.

So every claim in the register is **resolved**, not read:

* each name in `predicates` must exist in `invariants.registry.discover_predicates()`,
  written either bare (`verify_x`) or module-qualified (`governance.verify_x`);
* each path in `mechanism` must exist on disk;
* `COVERED` must carry one of those two forms of evidence;
* `ABSENT` may carry neither — naming a predicate contradicts the label;
* `PARTIAL` and `ABSENT` must say what is missing, and `COVERED` must not.

## One name is not one predicate

`verify_dual_control` is defined twice — `invariants/assurance.py` takes
`(action_sensitive, distinct_approvers)` under "No Loss Of Human Control";
`invariants/governance.py` takes `(approvals, required)` under "No Unauthorized
Capital Movement". Different signatures, different constitutional rules, same
name. Python keeps them apart by module; a register naming predicates as bare
strings cannot. A checker that flattened the inventory into a set would resolve
such a name green while being unable to say which predicate the row means.

So the inventory is kept as `name -> [modules]`, a bare name that lands in more
than one module is reported as a **note** (the claim resolves, but the row
should qualify it), and a qualified name is checked against that module rather
than against the name alone.

## The positive control

Before trusting any result the checker asserts the registry discovered
predicates at all. Without that, an `invariants` package that failed to import
would yield an empty inventory, every row would resolve identically, and the
run would still print a total. A harness that never ran agrees with every
assertion; this one refuses instead (exit 2).

## What this does NOT claim

A `COVERED` row means a live predicate or mechanism enforces the invariant's
substance. It does **not** mean the invariant is wired into a production call
path — that is `scripts/capability_callers.py`'s question — nor that the control
has been proven able to fail, which is `scripts/gate_evidence.py`'s. Three
different questions, three ledgers, deliberately not merged.
"""

from __future__ import annotations

import argparse
import sys
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from invariants.registry import discover_predicates

REPO = Path(__file__).resolve().parent.parent
REGISTER = REPO / "docs" / "ai" / "specs" / "AOS_INVARIANT_REGISTER.toml"

COVERED = "COVERED"
PARTIAL = "PARTIAL"
ABSENT = "ABSENT"
STATUSES = (COVERED, PARTIAL, ABSENT)


class ConformanceBroken(RuntimeError):
    """The check could not be performed — its own preconditions failed.

    Distinct from a blocking finding: a finding means the register is wrong, this
    means the answer would be meaningless. Never downgrade one to the other.
    """


@dataclass(frozen=True)
class Entry:
    id: str
    title: str
    status: str
    predicates: tuple[str, ...]
    gap: str
    mechanism: tuple[str, ...]


@dataclass
class Report:
    entries: int
    covered: int
    partial: int
    absent: int
    known_predicates: int  # distinct NAMES
    definitions: int  # distinct (module, name) pairs — the documented 339
    blocking: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


def _known_predicates() -> dict[str, list[str]]:
    """`{predicate_name: [modules that define it]}` — never flattened to a set.

    Two modules may define the same name (see the module docstring), and
    collapsing that loses exactly the fact a reader of the register needs.
    """
    out: dict[str, list[str]] = {}
    for module, names in discover_predicates().items():
        for name in names:
            out.setdefault(name, []).append(module)
    return {name: sorted(mods) for name, mods in out.items()}


def load(path: Path | None = None) -> tuple[list[Entry], dict]:
    """Parse the register. Raises ConformanceBroken if it cannot be trusted."""
    target = Path(path) if path is not None else REGISTER
    if not target.exists():
        raise ConformanceBroken(f"register not found: {target}")
    data = tomllib.loads(target.read_text(encoding="utf-8"))
    meta = data.pop("meta", {})

    entries: list[Entry] = []
    for key, row in data.items():
        if not isinstance(row, dict):
            continue
        entries.append(
            Entry(
                id=key,
                title=str(row.get("title", "")),
                status=str(row.get("status", "")),
                predicates=tuple(row.get("predicates", []) or ()),
                gap=str(row.get("gap", "")).strip(),
                mechanism=tuple(row.get("mechanism", []) or ()),
            )
        )

    if not entries:
        raise ConformanceBroken(f"register has no entries: {target}")

    declared = meta.get("entries")
    if declared is not None and int(declared) != len(entries):
        raise ConformanceBroken(f"register declares {declared} entries but carries {len(entries)}")

    return entries, meta


def check(path: Path | None = None) -> Report:
    """Resolve every claim in the register. Returns findings; raises on refusal."""
    entries, _meta = load(path)

    known = _known_predicates()
    if not known:
        # Positive control. Without it an unimportable `invariants` package would
        # read as "every predicate is missing" — or, with the comparison the other
        # way round, as silent agreement. Neither is an answer.
        raise ConformanceBroken(
            "invariants.registry discovered no predicates — the map cannot be resolved against nothing"
        )

    report = Report(
        entries=len(entries),
        covered=sum(1 for e in entries if e.status == COVERED),
        partial=sum(1 for e in entries if e.status == PARTIAL),
        absent=sum(1 for e in entries if e.status == ABSENT),
        known_predicates=len(known),
        definitions=sum(len(mods) for mods in known.values()),
    )

    for entry in entries:
        if entry.status not in STATUSES:
            report.blocking.append(f"{entry.id}: unknown status {entry.status!r} (expected one of {STATUSES})")
            continue

        for name in entry.predicates:
            module, _, bare = name.rpartition(".")
            modules = known.get(bare, [])
            if not modules:
                report.blocking.append(
                    f"{entry.id}: names predicate {name!r}, which no module under invariants/ defines"
                )
            elif module and module not in modules:
                report.blocking.append(
                    f"{entry.id}: names predicate {name!r}, but invariants/{module}.py does not define "
                    f"{bare!r} (it lives in {', '.join(modules)})"
                )
            elif not module and len(modules) > 1:
                report.notes.append(
                    f"{entry.id}: {bare!r} is defined in {len(modules)} modules ({', '.join(modules)}) — "
                    "qualify the claim so it names one"
                )

        for rel in entry.mechanism:
            if not (REPO / rel).exists():
                report.blocking.append(f"{entry.id}: names mechanism {rel!r}, which does not exist")

        if entry.status == COVERED:
            if not entry.predicates and not entry.mechanism:
                report.blocking.append(f"{entry.id}: COVERED with no evidence — name a predicate or a mechanism")
            if entry.gap:
                report.blocking.append(f"{entry.id}: COVERED but states a gap — it is PARTIAL")
        else:
            if not entry.gap:
                report.blocking.append(f"{entry.id}: {entry.status} without a gap — say what is missing")
            if entry.status == ABSENT and (entry.predicates or entry.mechanism):
                report.blocking.append(f"{entry.id}: ABSENT but names evidence — it is PARTIAL or COVERED")

    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="AOS §30 invariant conformance register.")
    parser.add_argument("--check", action="store_true", help="Exit non-zero on a broken claim")
    args = parser.parse_args(argv)

    try:
        report = check()
    except ConformanceBroken as exc:
        print(f"REFUSED — {exc}", file=sys.stderr)
        return 2

    print(
        f"AOS conformance: {report.entries} invariants · "
        f"{report.covered} covered · {report.partial} partial · {report.absent} absent "
        f"(resolved against {report.definitions} live predicate definitions, "
        f"{report.known_predicates} distinct names)"
    )
    for note in report.notes:
        print(f"  note  {note}")
    for block in report.blocking:
        print(f"  BLOCK {block}", file=sys.stderr)
    if args.check and report.blocking:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
