# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""Change records with an expected effect — Group 2 Chapter 6.

    python -m deployment.change_records --range HEAD~1..HEAD
    python -m deployment.change_records --check-message .git/COMMIT_EDITMSG

The last open piece of Decision Governance. `scripts/adr.py` records design
decisions by humans (§E22); `ai/ledger/decisions.py` records operational
decisions by the system (§E23); this is the same prediction field one layer
down, attached to a deployment.

Chapter 6's own sentence for why:

    A deployment log records that something happened, and a change record
    records what it was *for*. Only the second can be evaluated. **A history
    without predictions cannot teach anything.**

## Generated, not written

Every field but one comes from git and the tree. The exception is the expected
effect, and that is the point: it is the only field a machine cannot derive, and
the only one that makes the record evaluable.

It arrives as an `Expected-Effect:` commit trailer. Trailers are already how this
repository carries structured commit metadata — `Co-Authored-By`,
`Claude-Session` — and a prediction kept anywhere else drifts away from the
commit it describes, which is how a change record becomes a second thing to
maintain rather than a by-product of committing.

## The tier is derived from path prefixes, and this module says so

Chapter 6 sources "packages touched" from Chapter 1's **package register**. That
register does not exist — it is ranked item 10, still open. So the tier here is
derived from path prefixes, which is a weaker thing, and `TIER_SOURCE` names it.

Substituting a path table for the register silently would make the register look
delivered, which is exactly the shape §E20 had to correct in §E5: a document
claiming a measurement nobody took. When Chapter 1 lands, this table is what it
replaces.

## Advisory by default, enforcing on request

The owner chose **warn over block** on 2026-09-09 (ADR 0012). A missing
prediction prints a warning and the commit proceeds; `CHANGE_RECORD_ENFORCE=1`
turns the same finding into a non-zero exit, so the policy is configuration
rather than a code change.

The obvious objection is that a gate which only warns is a gate people learn to
scroll past, and it is a fair one. Three things answer it, and all three are
asserted in `tests/unit/test_change_record_gate_injections.py`:

* the warning names the exact trailer to add, so acting on it is cheaper than
  ignoring it;
* it names `CHANGE_RECORD_ENFORCE`, so the switch is discoverable without
  reading this file;
* `--report` measures the real KPI over a range. A warning whose effect is never
  measured is precisely the thing the objection is about, and this is what turns
  "are people writing predictions?" from an opinion into a number.

`validate()` is unchanged by the policy: it reports the problem either way. The
decision is about the exit code, never about the truth.

## Unknown is not safe

A path matching no known prefix is `unknown`, never `presentation`, and an
`unknown` change needs a prediction just as a `core` one does. Rule 2 in the
place it costs most: a blast radius nobody classified is not a small blast
radius, and the alternative is that the first unclassified package added to this
repository is the one that ships unpredicted.
"""

from __future__ import annotations

import argparse
import dataclasses
import os
import re
import subprocess  # nosec B404 — git, fixed args
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

ROOT = Path(__file__).resolve().parent.parent

#: Where the tier comes from. Named so a reader is not left to assume it is
#: Chapter 1's register, which does not exist yet.
TIER_SOURCE: Final[str] = "path-prefix"

#: Set to "1" to make a missing prediction fail the commit instead of warning.
#:
#: Advisory by default, on the owner's decision (ADR 0012). Named in the warning
#: itself so the switch is discoverable without reading this file.
ENFORCE_ENV: Final[str] = "CHANGE_RECORD_ENFORCE"


def enforcing() -> bool:
    return os.getenv(ENFORCE_ENV, "").strip() == "1"


#: Ordered most severe first. `unknown` sits ABOVE presentation deliberately:
#: see the module docstring.
TIER_ORDER: Final[tuple[str, ...]] = ("core", "ai", "unknown", "presentation")

#: Path prefix -> risk tier. Chapter 6 names three: the trading path, the AI
#: path, and presentation.
#:
#: `core` is everything that can move money or decide that money should move.
#: `ml/` is in it rather than in `ai/` because the inference engine sits inside
#: the trading decision, not beside it.
TIER_BY_PREFIX: Final[dict[str, str]] = {
    # ── the trading path ──────────────────────────────────────────────────────
    "risk/": "core",
    "execution/": "core",
    "brokers/": "core",
    "ml/": "core",
    "strategies/": "core",
    "strategy/": "core",
    "core/": "core",
    "invariants/": "core",
    "kill_switch.py": "core",
    "market_data/": "core",
    "data_layer/": "core",
    "data/": "core",
    "portfolio/": "core",
    "compliance/": "core",
    "payments/": "core",
    "monetization/": "core",
    "database/": "core",
    "alembic/": "core",
    "auth/": "core",
    "security/": "core",
    "api/": "core",
    "backtesting/": "core",
    # CI is the control plane for every gate here, and a change to it can
    # silently disable a safety check. Not hypothetical: §E20 found the
    # pre-commit hooks had never been installed, so seven ratcheted checks
    # protected nobody for as long as they had existed.
    ".github/": "core",
    ".pre-commit-config.yaml": "core",
    # ── the AI path ───────────────────────────────────────────────────────────
    "ai/": "ai",
    "brain/": "ai",
    "news/": "ai",
    "analytics/": "ai",
    "explainability/": "ai",
    # ── presentation and material that ships no behaviour ────────────────────
    "frontend/": "presentation",
    "dashboard/": "presentation",
    "mobile/": "presentation",
    "mobile-app/": "presentation",
    "static/": "presentation",
    "docs/": "presentation",
    "tests/": "presentation",
    "scripts/": "presentation",
    "assets/": "presentation",
    "templates/": "presentation",
}

_TRAILER = re.compile(r"^expected-effect:[ \t]*(.*)$", re.IGNORECASE)


@dataclasses.dataclass(frozen=True)
class ChangeRecord:
    """One release, and what it was for.

    Frozen: `observe` and `rolled_back` return a new record rather than editing
    this one, for the same reason `ai/ledger/decisions.py` does — a record whose
    outcome can be revised eventually agrees with whoever looked last.
    """

    change_id: str
    at: str
    actor: str
    commits: tuple[str, ...]
    paths: tuple[str, ...]
    expected_effect: str | None
    approvals: tuple[str, ...] = ()
    observed_effect: dict[str, Any] | None = None
    rollback: dict[str, Any] | None = None

    @property
    def risk_tier(self) -> str:
        return tier_for_paths(self.paths)

    @property
    def packages(self) -> tuple[str, ...]:
        return tuple(sorted({p.split("/", 1)[0] for p in self.paths if p}))

    def to_dict(self) -> dict[str, Any]:
        data = dataclasses.asdict(self)
        data["risk_tier"] = self.risk_tier
        data["packages"] = list(self.packages)
        data["tier_source"] = TIER_SOURCE
        return data


def tier_for_paths(paths: list[str] | tuple[str, ...]) -> str:
    """The most severe tier among the paths touched.

    No paths is `unknown`, not `presentation`: a change nobody could describe is
    not a change nobody needs to think about.
    """
    if not paths:
        return "unknown"
    found = {_tier_for_path(p) for p in paths if p}
    if not found:
        return "unknown"
    for tier in TIER_ORDER:
        if tier in found:
            return tier
    return "unknown"


#: Suffixes that ship no behaviour, used only for files at the repository ROOT.
#:
#: The root is where a blanket rule does the most damage in both directions.
#: Letting everything there fall through to `unknown` made editing CLAUDE.md
#: demand a deployment prediction — friction with no safety in it, and friction
#: is how a gate earns a bypass. Calling the whole root presentation would be the
#: opposite mistake: `app.py`, `run.py`, `hopefx_engine.py` and `trader_full.py`
#: all live there and all start the trading path.
_ROOT_PROSE_SUFFIXES: Final[tuple[str, ...]] = (
    ".md",
    ".txt",
    ".toml",
    ".cfg",
    ".ini",
    ".gitignore",
    ".yaml",
    ".yml",
    ".json",
    ".example",
)


def _tier_for_path(path: str) -> str:
    # `removeprefix`, not `lstrip("./")`: lstrip strips a CHARACTER SET, so it
    # turned ".gitignore" into "gitignore" and would have turned
    # ".github/workflows/ci.yml" into "github/workflows/ci.yml" — a path that
    # matches no prefix and lands in the wrong tier silently.
    normalised = str(path).replace("\\", "/").removeprefix("./")
    # Longest prefix first, so `core/decision/` cannot be shadowed by a shorter
    # entry that happens to sort earlier.
    for prefix in sorted(TIER_BY_PREFIX, key=len, reverse=True):
        if normalised == prefix or normalised.startswith(prefix):
            return TIER_BY_PREFIX[prefix]

    if "/" not in normalised:
        # At the root. Prose is presentation; anything else — a .py above all —
        # is treated as core, because a new file at the root is more likely a
        # second entry point than a note.
        lowered = normalised.lower()
        if lowered.endswith(_ROOT_PROSE_SUFFIXES) or lowered.startswith("."):
            return "presentation"
        return "core"

    return "unknown"


def requires_expected_effect(tier: str) -> bool:
    """Which tiers must state a prediction.

    Chapter 6 says `core`. `unknown` is included because failing open on an
    unclassified package would make the *first new package* the one that ships
    without a prediction — and a rule whose first exception is the case nobody
    anticipated is not a rule.
    """
    return tier in {"core", "unknown"}


def expected_effect(message: str) -> str | None:
    """Read the `Expected-Effect:` trailer, or None.

    Returns None for a trailer with nothing after it. A blank trailer is
    somebody satisfying a linter, and recording it as a stated prediction would
    make the KPI — change records with a stated expected effect — measure
    compliance with a regex instead of the presence of a thought.
    """
    lines = (message or "").splitlines()
    for index, line in enumerate(lines):
        match = _TRAILER.match(line.strip())
        if not match:
            continue
        parts = [match.group(1).strip()]
        # Continuation lines: an indented line under a trailer belongs to it.
        for follow in lines[index + 1 :]:
            if follow.startswith((" ", "\t")) and follow.strip():
                parts.append(follow.strip())
            else:
                break
        text = " ".join(p for p in parts if p).strip()
        return text or None
    return None


def validate(record: ChangeRecord) -> list[str]:
    """Problems with this record. Empty means it can ship."""
    problems: list[str] = []
    tier = record.risk_tier
    if requires_expected_effect(tier) and not (record.expected_effect or "").strip():
        problems.append(
            f"a {tier}-tier change must state an Expected-Effect: without a prediction the telemetry "
            "after deploy has nothing to be compared against, and correlation is guesswork "
            f"(packages touched: {', '.join(record.packages) or 'none'})"
        )
    return problems


def _git(*args: str) -> str:
    result = subprocess.run(  # nosec B603 B607 — fixed args, no shell
        ["git", *args],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
    )
    return result.stdout if result.returncode == 0 else ""


def from_git(ref_range: str = "HEAD~1..HEAD") -> ChangeRecord:
    """Build the record from git. Everything here is derived, nothing invented."""
    commits = tuple(line for line in _git("rev-list", ref_range).split() if line)
    paths = tuple(sorted({p for p in _git("diff", "--name-only", ref_range).splitlines() if p.strip()}))
    head = commits[0] if commits else (_git("rev-parse", "HEAD").strip() or "unknown")
    message = _git("log", "-1", "--pretty=%B", head) if commits else ""
    actor = (_git("log", "-1", "--pretty=%an", head).strip() if commits else "") or "unknown"

    return ChangeRecord(
        change_id=head[:12],
        at=datetime.now(UTC).isoformat(),
        actor=actor,
        commits=commits,
        paths=paths,
        expected_effect=expected_effect(message),
        # PR reviews are the source Chapter 6 names. There is no PR here, and an
        # empty tuple is honest about that rather than inventing an approver.
        approvals=(),
    )


def _commits_in(ref_range: str) -> list[tuple[str, str, tuple[str, ...]]]:
    """(sha, message, paths) for each commit in the range. Newest first."""
    out: list[tuple[str, str, tuple[str, ...]]] = []
    for sha in (line for line in _git("rev-list", ref_range).split() if line):
        message = _git("log", "-1", "--pretty=%B", sha)
        paths = tuple(sorted(p for p in _git("show", "--name-only", "--pretty=format:", sha).splitlines() if p.strip()))
        out.append((sha, message, paths))
    return out


def coverage_report(ref_range: str = "HEAD~20..HEAD") -> dict[str, Any]:
    """Chapter 6's KPI, measured: how many changes that needed a prediction have one.

    `coverage` is **None** when nothing in the range needed one. A perfect score
    from an empty denominator is the oldest fabricated metric there is, and this
    module refuses to report one — the same rule the risk gate applies to data
    quality and the ledger applies to confidence.
    """
    rows = _commits_in(ref_range)
    needing = 0
    stated = 0
    missing: list[dict[str, str]] = []
    for sha, message, paths in rows:
        tier = tier_for_paths(paths)
        if not requires_expected_effect(tier):
            continue
        needing += 1
        if (expected_effect(message) or "").strip():
            stated += 1
        else:
            missing.append({"commit": sha[:12], "tier": tier, "subject": message.splitlines()[0] if message else ""})
    return {
        "range": ref_range,
        "changes": len(rows),
        "needing_prediction": needing,
        "with_prediction": stated,
        "coverage": (stated / needing) if needing else None,
        "missing": missing,
    }


def observe(record: ChangeRecord, *, observed: str, held: bool) -> ChangeRecord:
    """Attach what the telemetry showed after the deploy."""
    if record.observed_effect is not None:
        raise ValueError(f"{record.change_id} already has an observed effect; it is attached once")
    if not (record.expected_effect or "").strip():
        raise ValueError(
            f"{record.change_id} states no expected effect, so there is no prediction to score the "
            "observation against — which is the whole reason this field is required"
        )
    return dataclasses.replace(
        record,
        observed_effect={
            "observed": str(observed),
            "held": bool(held),
            "expected": record.expected_effect,
            "at": datetime.now(UTC).isoformat(),
        },
    )


def rolled_back(record: ChangeRecord, *, reason: str) -> ChangeRecord:
    """Record that this change was rolled back, and why.

    The reason is required. "Rolled back" on its own tells the next reader that
    something went wrong and nothing about what, which makes the rollback
    unusable as evidence.
    """
    if not str(reason).strip():
        raise ValueError("a rollback must carry its reason; 'it was rolled back' teaches nobody anything")
    return dataclasses.replace(record, rollback={"occurred": True, "reason": str(reason).strip()})


def _report(record: ChangeRecord) -> None:
    print(f"change      {record.change_id}")
    print(f"actor       {record.actor}")
    print(f"commits     {len(record.commits)}")
    print(f"packages    {', '.join(record.packages) or 'none'}")
    print(f"risk tier   {record.risk_tier}   (derived from {TIER_SOURCE}; Ch 1's register is not built)")
    print(f"expected    {record.expected_effect or '— none stated —'}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Change records with an expected effect (Group 2 Ch 6).")
    parser.add_argument("--range", default="HEAD~1..HEAD", help="git range to describe")
    parser.add_argument(
        "--check-message",
        default=None,
        help="path to a commit message; check the staged change against it (commit-msg hook)",
    )
    parser.add_argument(
        "--report",
        action="store_true",
        help="measure Chapter 6's KPI over --range: how many changes that needed a prediction have one",
    )
    args = parser.parse_args(argv)

    if args.report:
        report = coverage_report(args.range)
        print(f"range               {report['range']}")
        print(f"changes             {report['changes']}")
        print(f"needing a prediction {report['needing_prediction']}")
        print(f"with one            {report['with_prediction']}")
        if report["coverage"] is None:
            # Not 100%. Nothing in this range needed a prediction, so the KPI is
            # undefined, and a perfect score from an empty denominator is a
            # fabricated measurement.
            print("coverage            — undefined: no change in this range needed a prediction")
        else:
            print(f"coverage            {report['coverage'] * 100:.0f}%   (Ch 6 target: 100% of core-tier)")
        for row in report["missing"]:
            print(f"  no prediction  {row['commit']}  [{row['tier']}]  {row['subject'][:60]}")
        return 0

    if args.check_message:
        message = Path(args.check_message).read_text(encoding="utf-8")
        paths = tuple(sorted(p for p in _git("diff", "--cached", "--name-only").splitlines() if p.strip()))
        record = ChangeRecord(
            change_id="staged",
            at=datetime.now(UTC).isoformat(),
            actor="staged",
            commits=(),
            paths=paths,
            expected_effect=expected_effect(message),
        )
    else:
        record = from_git(args.range)

    problems = validate(record)
    if not problems:
        if not args.check_message:
            _report(record)
        return 0

    # Advisory by default (ADR 0012). The finding is identical either way; only
    # the exit code differs.
    label = "FAIL" if enforcing() else "WARN"
    _report(record)
    for problem in problems:
        print(f"\n{label}  {problem}", file=sys.stderr)
    print(
        "\nAdd a trailer to the commit message, for example:\n"
        "\n    Expected-Effect: refused trades fall to zero within one session\n"
        "\nIt is the only field here a machine cannot derive, and the only one that makes the\n"
        "record evaluable afterwards.",
        file=sys.stderr,
    )
    if enforcing():
        return 1
    print(
        f"\nThis is a WARNING, not a block: the commit will proceed. Set {ENFORCE_ENV}=1 to make it "
        "fail instead.\nMeasure how often it is being acted on with:  "
        "python -m deployment.change_records --report --range HEAD~20..HEAD",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
