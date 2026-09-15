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
import subprocess  # nosec B404 - reads git metadata, no user input
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
    #: Claims this run could not verify, because their measurement was
    #: unavailable here. Never folded into "no drift": a figure nobody could
    #: check is not a figure that matched.
    unmeasured: list[Hit] = field(default_factory=list)

    @property
    def policed_drift(self) -> list[Drift]:
        """Drift in the figures this module ENFORCES, i.e. all but the pair it
        maintains.

        `commits_ahead` / `files_ahead` / `commits_behind` change on every
        commit and the hook only runs on documentation changes, so a run of
        code-only commits takes them stale through nobody's fault. `--sync`
        maintains them; `--check` still SHOWS them, because a human reading the
        report wants the whole picture. What must not depend on them is an
        assertion about whether the tree is in order — that was three tests in
        `tests/unit/test_doc_metrics.py`, red for most of the life of any
        working tree. Use this for those.
        """
        return [d for d in self.drift if d.metric not in _COMMIT_BOUNDARY]


#: Bound to the scripts that measure them. Each pattern captures exactly one
#: integer, in a shape specific enough that ordinary prose does not match it.
CLAIMS: Final[tuple[Claim, ...]] = (
    # Anchored to the shapes that state a TOTAL. A bare `(\d+)\s+gates` also
    # matched "8 gates left", which is a count of what remains — a true sentence
    # the checker called drift. A check that forces awkward prose gets worked
    # around, so the pattern narrowed rather than the writing.
    Claim(
        "gates_total",
        re.compile(r"(\d+)\s+gates\s*(?:·|,|\bdiscovered\b)"),
        "scripts/gate_evidence.py",
    ),
    Claim("gates_proven", re.compile(r"(\d+)\s+proven\b"), "scripts/gate_evidence.py"),
    Claim("gates_unproven", re.compile(r"(\d+)\s+unproven\b"), "scripts/gate_evidence.py"),
    Claim("source_titles", re.compile(r"(\d+)\s+(?:source\s+)?titles\b"), "scripts/group4_preservation.py"),
    Claim(
        "documents_registered",
        re.compile(r"(\d+)\s+documents\s+registered\b"),
        "scripts/docs_registry.py",
    ),
    Claim("documents_unowned", re.compile(r"(\d+)\s+unowned\b"), "scripts/docs_registry.py"),
    # AOS §30 conformance. "covered", "partial" and "absent" are ordinary English,
    # so each pattern requires the separator the register's own report line uses
    # (`2 covered · 13 partial · 11 absent`). Without that anchor, "coverage is
    # partial in three modules" reads as a stated figure — the same trap the
    # gates_total pattern had to be narrowed out of.
    # Anchored to their neighbours, not to a trailing separator. The spatial
    # register's line — "16 spatial capabilities · 1 built · 9 partial · 6
    # planned" — also contains "N partial ·", so the looser pattern read it as an
    # AOS figure. Two ratchets built weeks apart, colliding on one English word.
    Claim("aos_entries", re.compile(r"(\d+)\s+AOS\s+invariants\b"), "scripts/aos_conformance.py"),
    Claim("aos_covered", re.compile(r"invariants\s*·\s*(\d+)\s+covered\b"), "scripts/aos_conformance.py"),
    Claim("aos_partial", re.compile(r"covered\s*·\s*(\d+)\s+partial\b"), "scripts/aos_conformance.py"),
    Claim("aos_absent", re.compile(r"partial\s*·\s*(\d+)\s+absent\b"), "scripts/aos_conformance.py"),
    # Spatial capability statuses, anchored to their NEIGHBOUR rather than to a
    # trailing separator. The looser `(\d+)\s+planned\s*·` read the AI Hub
    # registry's own line — "233 rows · 233 live · 0 staged · 0 planned" — as a
    # spatial figure and called it drift. Same trap `gates_total` fell into with
    # "8 gates left", and the same fix: narrow the pattern, not the writing.
    Claim("spatial_total", re.compile(r"(\d+)\s+spatial\s+capabilities\b"), "scripts/spatial_capabilities.py"),
    Claim("spatial_built", re.compile(r"capabilities\s*·\s*(\d+)\s+built\b"), "scripts/spatial_capabilities.py"),
    Claim("spatial_planned", re.compile(r"partial\s*·\s*(\d+)\s+planned\b"), "scripts/spatial_capabilities.py"),
    # The coverage record's size. Anchored to the exact phrase the two tables
    # that state it use, because a bare `(\d+)\s+modules` would match half the
    # prose in this repository — the same collision `gates_total` and
    # `spatial_planned` above had to be narrowed out of.
    #
    # This one is here because it drifted: both tables read 361 while the record
    # held 240, and `--check` reported no drift because nothing measured it. A
    # figure describing a ratchet, going stale for want of a ratchet.
    Claim(
        "coverage_debt",
        re.compile(r"recorded\s+coverage\s+debt\s*\|\s*(\d+)"),
        "scripts/pre_commit_coverage.py",
    ),
    # How many decisions are waiting on the owner. This is here because it
    # drifted badly: MASTER_OUTSTANDING's own summary read "Four of them" while
    # §A carried seventeen, so a reader trusting the summary believed the
    # owner's queue was a quarter of its real size. Measured by counting the
    # `### A<n>.` headings in §A, which is the list itself.
    # How far this branch is from `main`. Both documents that state it drifted —
    # LANDING_PLAN.md and CLAUDE.md read 565 commits / 1,246 files while the
    # branch was at 588 / 1,321 — because nothing measured either figure. A
    # contributor sizing the landing work from either was reading a number that
    # stopped being true 23 commits earlier.
    #
    # Anchored to the whole phrase, not to `(\d+)\s+commits`. LANDING_PLAN.md's
    # next line deliberately records what the figure *was* when the plan was
    # written ("this read 551 and 1,227"), and a looser pattern would call that
    # true historical sentence drift — whereupon the fix a reader reaches for is
    # to delete the record.
    Claim(
        "commits_ahead",
        re.compile(r"(\d[\d,]*)\s+commits\s+and\s+\d[\d,]*\s+files\s+ahead"),
        "git rev-list --count origin/main..HEAD",
    ),
    Claim(
        "files_ahead",
        re.compile(r"\d[\d,]*\s+commits\s+and\s+(\d[\d,]*)\s+files\s+ahead"),
        "git diff --name-only origin/main...HEAD",
    ),
    # The fast-forward claim. If this stops being 0 the branch has diverged, and
    # the landing plan's whole recipe — cut by path from the branch head onto
    # main — no longer describes the repository.
    Claim(
        "commits_behind",
        re.compile(r"rev-list\s+--count\s+HEAD\.\.origin/main`?\s+is\s+\*\*(\d[\d,]*)\*\*"),
        "git rev-list --count HEAD..origin/main",
    ),
    Claim(
        "owner_decisions",
        re.compile(r"Decisions only the owner can make\.\*\*\s*(\d+)\s+of them"),
        "docs/ai/MASTER_OUTSTANDING.md",
    ),
)

#: §A's entries, the thing `owner_decisions` counts.
_OWNER_HEADING: Final = re.compile(r"(?m)^###\s+A\d+\.")

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
    # Added 2026-09-14. It sits under docs/audit/, which is otherwise dated
    # records, so it was never scanned — and it is the one document CLAUDE.md
    # tells you to read before opening a pull request. `docs/REGISTRY.toml`
    # settles it rather than an opinion: tier T2, owned, `state = "active"`.
    "docs/audit/LANDING_PLAN.md",
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

        from scripts.aos_conformance import check as aos_check
        from scripts.spatial_capabilities import check as spatial_check
        from scripts.docs_registry import load as registry_load
        from scripts.pre_commit_coverage import _load_baseline as coverage_baseline

        entries, _ = registry_load()
        aos = aos_check()
        spatial = spatial_check()
    except Exception as exc:  # pragma: no cover - an unreadable source is the finding
        raise MetricsBroken(f"a measurement could not be taken: {exc}") from exc

    return {
        "gates_total": gates.gates,
        "gates_proven": gates.proven,
        "gates_unproven": gates.unproven,
        "source_titles": preservation.titles_checked,
        "documents_registered": len(entries),
        "documents_unowned": sum(1 for e in entries if not e.owner.strip()),
        "aos_entries": aos.entries,
        "aos_covered": aos.covered,
        "aos_partial": aos.partial,
        "aos_absent": aos.absent,
        "spatial_total": spatial.entries,
        "spatial_built": spatial.built,
        "spatial_planned": spatial.planned,
        "coverage_debt": len(coverage_baseline()),
        "owner_decisions": _count_owner_decisions(repo),
        **_branch_distance(repo),
    }


def _branch_distance_at(repo: Path, rev: str) -> dict[str, int]:
    """The branch distance measured at *rev*, or nothing at all.

    Returns an EMPTY dict when `origin/main` or *rev* does not resolve — a
    shallow or single-branch clone has no such ref. Zero would be the rule-2
    defect (an unmeasured value is absent, never zero) and would read as drift
    against every document stating a real number.

    Deliberately does not raise. `measure()` raising here would take the whole
    doc-metrics gate down in any checkout without the ref, turning a working
    check into a blocker — so the absence is carried up and *reported* instead,
    by name, as `Report.unmeasured`. That is a visible degradation rather than a
    silent one; `--check` still fails whenever the ref is present and a document
    disagrees, which is every ordinary working copy.
    """

    def _git(*args: str) -> str | None:
        try:
            done = subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True, timeout=30, check=False)
        except Exception:
            return None
        return done.stdout if done.returncode == 0 else None

    for ref in ("origin/main", rev):
        if _git("rev-parse", "--verify", "--quiet", ref) is None:
            return {}

    ahead = _git("rev-list", "--count", f"origin/main..{rev}")
    behind = _git("rev-list", "--count", f"{rev}..origin/main")
    files = _git("diff", "--name-only", f"origin/main...{rev}")
    if ahead is None or behind is None or files is None:
        return {}

    return {
        "commits_ahead": int(ahead.strip()),
        "commits_behind": int(behind.strip()),
        "files_ahead": len([line for line in files.splitlines() if line.strip()]),
    }


#: Metrics whose stated value may also be the value one commit ago — see
#: :func:`_accepted`.
_COMMIT_BOUNDARY: Final = frozenset({"commits_ahead", "files_ahead", "commits_behind"})


def _accepted(metric: str, measured: int, repo: Path) -> set[int]:
    """Every value a document may correctly state for *metric*.

    For most claims this is exactly one number. The branch-distance figures are
    different, and the difference is structural rather than a matter of taste:
    `pre-commit` runs BEFORE the commit exists, so a figure written during commit
    N states the distance as of N-1. It is correct when the hook checks it and
    one commit stale the instant it lands.

    Checked exactly, the gate is therefore red forever — every doc-touching
    commit reports a drift of one, gets refreshed, lands, and is off by one
    again. That is the check this module's docstring warns about, the one
    answered with `--no-verify`.

    So the distance at HEAD's parent is accepted too: exactly one commit of
    staleness, expressed in git's own terms rather than as a ±1 fudge, and
    nothing beyond it. Two commits stale is still drift.
    """
    if metric not in _COMMIT_BOUNDARY:
        return {measured}
    previous = _branch_distance_at(repo, "HEAD~1")
    return {measured} | ({previous[metric]} if metric in previous else set())


def _branch_distance(repo: Path) -> dict[str, int]:
    """The branch distance as of HEAD."""
    return _branch_distance_at(repo, "HEAD")


def _count_owner_decisions(repo: Path) -> int:
    """§A's entries, counted from the headings rather than from anyone's memory."""
    path = repo / "docs/ai/MASTER_OUTSTANDING.md"
    if not path.exists():
        raise MetricsBroken("docs/ai/MASTER_OUTSTANDING.md is missing — refusing to report a count")
    return len(_OWNER_HEADING.findall(path.read_text(encoding="utf-8")))


def _shown(path: Path) -> str:
    """A path to print. Falls back to the absolute form for documents outside
    the repository — `extra_documents` accepts any path, and `relative_to`
    raises rather than returning something useful when given one."""
    try:
        return str(path.relative_to(REPO))
    except ValueError:
        return str(path)


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
                    # `1,246`, as both documents write it. int() rejects the comma, and a
                    # pattern that stopped at it would read 1 — drift for the wrong
                    # reason on every run, until someone deleted the check.
                    hits.append(Hit(path, number, claim.metric, int(match.group(1).replace(",", ""))))
    return hits


def check(
    repo: Path | None = None,
    extra_documents: list[Path] | None = None,
    exact: bool = False,
) -> Report:
    """Compare every stated figure against what the code measures.

    `exact` drops the one-commit tolerance in :func:`_accepted`. It exists for
    `refresh(only=_COMMIT_BOUNDARY)`: the tolerance is right for JUDGING a
    figure (the hook runs before the commit exists) and wrong for choosing what
    to REWRITE. Selecting the rewrite set through the same tolerance banked the
    oldest value the gate would accept, so the document went two commits stale
    — hard drift — the moment one further commit landed, with nothing scheduled
    to fix it. Measured on this repository 2026-09-15, that had three tests in
    `tests/unit/test_doc_metrics.py` red through nobody's fault.
    """
    repo = repo or REPO
    measured = measure(repo)
    hits = scan(repo, extra_documents)
    report = Report(checked=len(hits), documents=len(_documents(repo, extra_documents)))
    for hit in hits:
        if hit.metric not in measured:
            report.unmeasured.append(hit)
            continue
        expected = measured[hit.metric]
        accepted = {expected} if exact else _accepted(hit.metric, expected, repo)
        if hit.stated not in accepted:
            report.drift.append(Drift(hit.path, hit.line, hit.metric, hit.stated, expected))
    return report


def refresh(repo: Path | None = None, only: frozenset[str] | None = None) -> list[Drift]:
    """Rewrite every drifted figure to what the code measures. Returns what changed.

    Most claims here move rarely — a gate is added, a document is registered —
    so hand-editing the number is proportionate. `commits_ahead` and
    `files_ahead` are different in kind: they change with *every commit*, and a
    check that demands a hand-edit on every commit is the check this module's
    own docstring warns about, the one people answer with `--no-verify`.

    So the fix is one command rather than a hunt through two documents. The
    thousands separator is preserved where the document used one, because
    rewriting `1,246` as `1321` would quietly restyle prose the author chose.
    """
    repo = repo or REPO
    # `exact` when syncing the volatile pair: see check()'s docstring. Rewriting
    # only what the gate would REFUSE leaves the document at the oldest figure
    # tolerance allows, which is one commit from being refused.
    drifted = [d for d in check(repo, exact=only is not None).drift if only is None or d.metric in only]
    by_path: dict[Path, list[Drift]] = {}
    for d in drifted:
        by_path.setdefault(d.path, []).append(d)

    for path, drifts in by_path.items():
        lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
        for d in drifts:
            line = lines[d.line - 1]
            claim = next(c for c in CLAIMS if c.metric == d.metric)
            match = next(
                (m for m in claim.pattern.finditer(line) if int(m.group(1).replace(",", "")) == d.stated),
                None,
            )
            if match is None:
                continue
            replacement = f"{d.measured:,}" if "," in match.group(1) else str(d.measured)
            start, end = match.span(1)
            lines[d.line - 1] = line[:start] + replacement + line[end:]
        path.write_text("".join(lines), encoding="utf-8")
    return drifted


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Do documents still state the measured figures?")
    parser.add_argument("--check", action="store_true", help="Exit non-zero when a figure has drifted")
    parser.add_argument(
        "--refresh",
        action="store_true",
        help="Rewrite drifted figures to the measured values, then report what changed",
    )
    parser.add_argument(
        "--sync",
        action="store_true",
        help="Maintain the per-commit figures, then check the rest (what pre-commit runs)",
    )
    args = parser.parse_args(argv)

    if args.sync:
        # The volatile pair is maintained; everything else is policed. A figure
        # that changes on every commit cannot be enforced by hand — the hook
        # only runs on doc changes, so a run of code-only commits takes it
        # several commits stale and blocks the next doc commit through no fault
        # of its author. `gates_total` is the opposite: it drifts because
        # something real changed, and quietly rewriting it would destroy the
        # only signal that it did.
        try:
            synced = refresh(only=_COMMIT_BOUNDARY)
        except MetricsBroken as exc:
            print(f"REFUSED — {exc}", file=sys.stderr)
            return 2
        for d in synced:
            print(f"  SYNCED {_shown(d.path)}:{d.line} {d.metric}: {d.stated} -> {d.measured}")
        return main(["--check"])

    if args.refresh:
        try:
            changed = refresh()
        except MetricsBroken as exc:
            print(f"REFUSED — {exc}", file=sys.stderr)
            return 2
        for d in changed:
            print(f"  UPDATED {_shown(d.path)}:{d.line} {d.metric}: {d.stated} -> {d.measured}")
        print(f"doc metrics: {len(changed)} figure(s) rewritten")
        return 0

    try:
        report = check()
    except MetricsBroken as exc:
        print(f"REFUSED — {exc}", file=sys.stderr)
        return 2

    line = (
        f"doc metrics: {report.documents} living documents · {report.checked} stated figures "
        f"· {len(report.drift)} drifted"
    )
    if report.unmeasured:
        line += f" · {len(report.unmeasured)} unverifiable"
    print(line)
    if report.unmeasured:
        # Said out loud, never folded into "no drift". A figure nobody could
        # check is not a figure that matched.
        for metric in sorted({h.metric for h in report.unmeasured}):
            describes = next((c.describes for c in CLAIMS if c.metric == metric), "?")
            print(
                f"  UNVERIFIABLE {metric}: `{describes}` could not be run here "
                "(origin/main not fetched?) — the figure was NOT checked",
                file=sys.stderr,
            )
    for d in report.drift:
        print(
            f"  DRIFT {_shown(d.path)}:{d.line} states {d.metric}={d.stated}, measured {d.measured}",
            file=sys.stderr,
        )
    if report.drift:
        print("\nUpdate the document, or re-measure — do not bypass.", file=sys.stderr)
    return 1 if (args.check and report.drift) else 0


if __name__ == "__main__":
    raise SystemExit(main())
