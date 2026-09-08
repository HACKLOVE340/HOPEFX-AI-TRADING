# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""A number written in a document must still match what the code measures.

    python scripts/doc_metrics.py            # report
    python scripts/doc_metrics.py --check    # exit non-zero on drift

## Why this exists

The owner's standing rule is that documentation ships with every push. The
failure that rule guards against is not a missing file — it is a document that
still *looks* current while carrying a figure that stopped being true three
commits ago. A reader, human or agent, then acts on a number nobody re-measured.

`docs_freshness.py` catches a path that no longer exists and a claim the working
tree contradicts. It does not do arithmetic. So `22 gates · 12 proven` survives
in prose long after the ledger moves on, and nothing anywhere disagrees.

This closes that gap and nothing else. Each claim shape below is bound to the
script that measures it.

## Deliberately narrow

Only the figures that (a) appear in living documents and (b) have a script that
measures them are checked. A regex broad enough to catch every number in the
repository would produce false positives, and a check people learn to ignore is
worse than no check — they reach for `--no-verify`, which is how merge-conflict
markers get committed.

Adding a claim means adding one :class:`Claim` row and one measurement. If a
figure has no measuring script, it does not belong here; write it as prose that
names its source and date instead.

## Fail closed

A repository whose measurements cannot be read raises :class:`MetricsBroken`
rather than reporting no drift. Rule 2: an unmeasured value is absent, never
zero — and zero would silently "match" a document claiming zero.
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Final

REPO: Final = Path(__file__).resolve().parent.parent


class MetricsBroken(RuntimeError):
    """The measurements could not be taken, so a clean result would mean nothing."""


@dataclass(frozen=True)
class Claim:
    """One shape a document uses to state a measured figure."""

    metric: str
    pattern: re.Pattern[str]
    describes: str


@dataclass(frozen=True)
class Hit:
    path: Path
    line: int
    metric: str
    stated: int


@dataclass(frozen=True)
class Drift:
    path: Path
    line: int
    metric: str
    stated: int
    measured: int


@dataclass
class Report:
    checked: int = 0
    drift: list[Drift] = field(default_factory=list)
    documents: int = 0


#: Bound to the scripts that measure them. Each pattern captures exactly one
#: integer, in a shape specific enough that ordinary prose does not match it.
CLAIMS: Final[tuple[Claim, ...]] = (
    Claim("gates_total", re.compile(r"(\d+)\s+gates\b"), "scripts/gate_evidence.py"),
    Claim("gates_proven", re.compile(r"(\d+)\s+proven\b"), "scripts/gate_evidence.py"),
    Claim("gates_unproven", re.compile(r"(\d+)\s+unproven\b"), "scripts/gate_evidence.py"),
    Claim("source_titles", re.compile(r"(\d+)\s+(?:source\s+)?titles\b"), "scripts/group4_preservation.py"),
    Claim(
        "documents_registered",
        re.compile(r"(\d+)\s+documents\s+registered\b"),
        "scripts/docs_registry.py",
    ),
    Claim("documents_unowned", re.compile(r"(\d+)\s+unowned\b"), "scripts/docs_registry.py"),
)

#: Living documents only. Dated audits and archives are point-in-time records —
#: "refreshing" a historical figure would destroy the record it exists to be.
_LIVING: Final[tuple[str, ...]] = (
    "CLAUDE.md",
    "AGENTS.md",
    "ARCHITECTURE.md",
    "README.md",
    "CONTRIBUTING.md",
    "DEPLOYMENT.md",
    "docs/ai/MASTER_OUTSTANDING.md",
    "docs/ai/BACKLOG_GROUPS.md",
    "docs/ai/specs/GROUP2_platform_engineering_operations_governance.md",
    "docs/ai/specs/GROUP3_documentation_knowledge_architecture_governance.md",
    "docs/ai/specs/GROUP4_CONSTITUTION.md",
    "docs/runbooks/database-restore.md",
)


def measure(repo: Path | None = None) -> dict[str, int]:
    """Today's value for every metric a document may state."""
    repo = repo or REPO
    if not (repo / "scripts" / "gate_evidence.py").exists():
        raise MetricsBroken(f"{repo} does not look like this repository — refusing to report no drift")

    sys.path.insert(0, str(repo))
    try:
        from scripts.gate_evidence import check as gate_check
        from scripts.group4_preservation import check as preservation_check

        gates = gate_check(repo=repo)
        preservation = preservation_check()

        from scripts.docs_registry import load as registry_load

        entries, _ = registry_load()
    except Exception as exc:  # pragma: no cover - an unreadable source is the finding
        raise MetricsBroken(f"a measurement could not be taken: {exc}") from exc

    return {
        "gates_total": gates.gates,
        "gates_proven": gates.proven,
        "gates_unproven": gates.unproven,
        "source_titles": preservation.titles_checked,
        "documents_registered": len(entries),
        "documents_unowned": sum(1 for e in entries if not e.owner.strip()),
    }


def _documents(repo: Path, extra: list[Path] | None = None) -> list[Path]:
    found = [repo / name for name in _LIVING if (repo / name).exists()]
    return found + list(extra or [])


def scan(repo: Path | None = None, extra_documents: list[Path] | None = None) -> list[Hit]:
    """Every stated figure this checker knows how to verify."""
    repo = repo or REPO
    hits: list[Hit] = []
    for path in _documents(repo, extra_documents):
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            # A struck-through row is a historical record of what *was* true.
            if line.lstrip().startswith("| ~~"):
                continue
            for claim in CLAIMS:
                for match in claim.pattern.finditer(line):
                    hits.append(Hit(path, number, claim.metric, int(match.group(1))))
    return hits


def check(
    repo: Path | None = None,
    extra_documents: list[Path] | None = None,
) -> Report:
    repo = repo or REPO
    measured = measure(repo)
    hits = scan(repo, extra_documents)
    report = Report(checked=len(hits), documents=len(_documents(repo, extra_documents)))
    for hit in hits:
        expected = measured[hit.metric]
        if hit.stated != expected:
            report.drift.append(Drift(hit.path, hit.line, hit.metric, hit.stated, expected))
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Do documents still state the measured figures?")
    parser.add_argument("--check", action="store_true", help="Exit non-zero when a figure has drifted")
    args = parser.parse_args(argv)

    try:
        report = check()
    except MetricsBroken as exc:
        print(f"REFUSED — {exc}", file=sys.stderr)
        return 2

    print(
        f"doc metrics: {report.documents} living documents · {report.checked} stated figures "
        f"· {len(report.drift)} drifted"
    )
    for d in report.drift:
        print(
            f"  DRIFT {d.path.relative_to(REPO)}:{d.line} states {d.metric}={d.stated}, measured {d.measured}",
            file=sys.stderr,
        )
    if report.drift:
        print("\nUpdate the document, or re-measure — do not bypass.", file=sys.stderr)
    return 1 if (args.check and report.drift) else 0


if __name__ == "__main__":
    raise SystemExit(main())
