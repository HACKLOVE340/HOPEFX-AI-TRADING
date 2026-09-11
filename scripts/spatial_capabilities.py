# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""The spatial specification's status table, resolved instead of read.

    python scripts/spatial_capabilities.py            # report
    python scripts/spatial_capabilities.py --check    # fail on a broken claim

`docs/ai/specs/SPATIAL_INTELLIGENCE.md` carries sixteen capabilities — the
epistemic ladder plus the owner's fifteen — and a status for each. That table is
the answer to *"what can this system actually do"*, which makes it the most
load-bearing prose in the specification and the most dangerous to leave as prose:
rename a module and the row keeps saying `partial` while pointing at a file that
is gone.

Exactly the problem `AOS_INVARIANT_REGISTER.toml` had, solved the same way. The
statuses live in `SPATIAL_CAPABILITIES.toml`, every non-planned claim names
evidence, and this script **resolves** it:

* `module.path` — must import
* `module.path:Attribute` — must import and hold it; dotted (`World.assembly_order`) walks
* `dir/file.py` — must exist on disk

## Why `planned` may name nothing

Taken from `ai/hub/capabilities.py`, which learned it the hard way: *"a pointer
to nothing reads as progress"*. A planned row citing a module that happens to
exist for other reasons is how a roadmap starts describing work nobody did.

## The positive control

Before trusting any result the checker asks whether the universe it resolves
against is live at all. If `ai.spatial` cannot be imported, every `built` row
would resolve to "missing" — and a checker written the other way round would
find nothing to contradict and report clean. Either way the answer is
meaningless, so it refuses (exit 2) rather than reporting.

## What this does NOT claim

A resolving `built` row means the named code exists and imports. It does not mean
the capability is wired into a production caller — that is
`scripts/capability_callers.py`'s question — nor that its controls have been
proven able to fail, which is `scripts/gate_evidence.py`'s. Three questions,
three ledgers, deliberately not merged.
"""

from __future__ import annotations

import argparse
import importlib
import sys
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
REGISTER = REPO / "docs" / "ai" / "specs" / "SPATIAL_CAPABILITIES.toml"

BUILT = "built"
PARTIAL = "partial"
PLANNED = "planned"
STATUSES = (BUILT, PARTIAL, PLANNED)


class RegisterBroken(RuntimeError):
    """The check could not be performed, so a clean result would mean nothing."""


@dataclass(frozen=True)
class Entry:
    id: str
    title: str
    status: str
    evidence: tuple[str, ...]
    gap: str


@dataclass
class Report:
    entries: int
    built: int
    partial: int
    planned: int
    resolved: int = 0
    blocking: list[str] = field(default_factory=list)


def _universe_is_live() -> bool:
    """Can anything be resolved at all? The positive control's subject."""
    try:
        importlib.import_module("ai.spatial.world")
    except Exception:
        return False
    return True


def _resolve(locator: str) -> str | None:
    """Return a failure description, or None when the locator resolves."""
    if "/" in locator or locator.endswith(".py"):
        return None if (REPO / locator).exists() else f"path {locator!r} does not exist"

    module_name, _, attribute = locator.partition(":")
    try:
        module = importlib.import_module(module_name)
    except Exception as exc:
        return f"module {module_name!r} does not import ({exc.__class__.__name__}: {exc})"
    # Attributes may be dotted — `World.assembly_order` names a method, which is
    # better evidence than the class alone: renaming the method breaks the claim
    # instead of leaving it pointing vaguely at a class that still exists.
    target = module
    walked: list[str] = []
    for part in attribute.split(".") if attribute else []:
        if not hasattr(target, part):
            owner = ".".join([module_name, *walked]) if walked else module_name
            return f"{owner!r} has no attribute {part!r}"
        target = getattr(target, part)
        walked.append(part)
    return None


def load(path: Path | None = None) -> tuple[list[Entry], dict]:
    target = Path(path) if path is not None else REGISTER
    if not target.exists():
        raise RegisterBroken(f"register not found: {target}")
    data = tomllib.loads(target.read_text(encoding="utf-8"))
    meta = data.pop("meta", {})

    entries = [
        Entry(
            id=key,
            title=str(row.get("title", "")),
            status=str(row.get("status", "")),
            evidence=tuple(row.get("evidence", []) or ()),
            gap=str(row.get("gap", "")).strip(),
        )
        for key, row in data.items()
        if isinstance(row, dict)
    ]
    if not entries:
        raise RegisterBroken(f"register has no entries: {target}")

    declared = meta.get("entries")
    if declared is not None and int(declared) != len(entries):
        raise RegisterBroken(f"register declares {declared} entries but carries {len(entries)}")
    return entries, meta


def check(path: Path | None = None) -> Report:
    entries, _meta = load(path)

    if not _universe_is_live():
        raise RegisterBroken(
            "ai.spatial cannot be resolved against — every claim would read the same, so this is not an answer"
        )

    report = Report(
        entries=len(entries),
        built=sum(1 for e in entries if e.status == BUILT),
        partial=sum(1 for e in entries if e.status == PARTIAL),
        planned=sum(1 for e in entries if e.status == PLANNED),
    )

    for entry in entries:
        if entry.status not in STATUSES:
            report.blocking.append(f"{entry.id}: unknown status {entry.status!r} (expected one of {STATUSES})")
            continue

        for locator in entry.evidence:
            failure = _resolve(locator)
            if failure:
                report.blocking.append(f"{entry.id}: {failure}")
            else:
                report.resolved += 1

        if entry.status == PLANNED:
            if entry.evidence:
                report.blocking.append(
                    f"{entry.id}: planned but names evidence — a pointer to nothing reads as progress"
                )
            if not entry.gap:
                report.blocking.append(f"{entry.id}: planned without a gap — say what is missing")
        elif entry.status == PARTIAL:
            if not entry.evidence:
                report.blocking.append(f"{entry.id}: partial with no evidence — name what exists")
            if not entry.gap:
                report.blocking.append(f"{entry.id}: partial without a gap — say what is missing")
        else:  # built
            if not entry.evidence:
                report.blocking.append(f"{entry.id}: built with no evidence — name what exists")
            if entry.gap:
                report.blocking.append(f"{entry.id}: built but states a gap — it is partial")

    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Spatial capability register.")
    parser.add_argument("--check", action="store_true", help="Exit non-zero on a broken claim")
    args = parser.parse_args(argv)

    try:
        report = check()
    except RegisterBroken as exc:
        print(f"REFUSED — {exc}", file=sys.stderr)
        return 2

    print(
        f"spatial capabilities: {report.entries} capabilities · "
        f"{report.built} built · {report.partial} partial · {report.planned} planned "
        f"({report.resolved} evidence locators resolved)"
    )
    for block in report.blocking:
        print(f"  BLOCK {block}", file=sys.stderr)
    if args.check and report.blocking:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
