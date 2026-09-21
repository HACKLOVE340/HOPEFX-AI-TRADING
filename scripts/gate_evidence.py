# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""Rule 1, made checkable instead of remembered.

    python scripts/gate_evidence.py            # report
    python scripts/gate_evidence.py --check    # fail on a regression
    python scripts/gate_evidence.py --generate # add rows for new gates
    python scripts/gate_evidence.py --adopt    # set the baseline (once)

Group 2's first rule:

    A control that cannot fail is not a control. Every gate, guard, probe,
    alert, invariant, evaluation and health check ships with evidence that it is
    capable of returning a negative result. A control with no such record is
    treated as absent.

The evidence has been accumulating in commit messages, terminal scrollback and
test docstrings. None of that is auditable, so in practice the rule was enforced
by whoever remembered it. **Seven controls that could not fail have been found in
this repository**, two of them in code that had been running nightly, and every
one was found by breaking it on purpose rather than by reading it.

## What this ledger does

Gates are **discovered**, never hand-listed. A list of gates goes stale the first
time somebody adds one, and the omission is indistinguishable from compliance.
Two sources are discovered:

* `scripts/ci/gate_*.py` — the CI gates.
* `.pre-commit-config.yaml` — hooks whose `entry` runs one of *this repository's*
  own scripts.

Third-party hooks (ruff, bandit, detect-secrets, the `pre-commit-hooks` set) are
deliberately **out of scope**: their ability to fail is their maintainers'
responsibility and is covered by their own suites. What is ours is the
configuration, and a misconfiguration shows up as our gates failing, not theirs.

## What it does not cover, said plainly

The 339 `verify_*` / `catastrophic_*` predicates under `invariants/` are controls
too, and they are **not** in this ledger. They are a different shape — pure
functions returning violations rather than processes that exit non-zero — and
they need their own mechanism. Recording that here is better than a ledger that
silently implies the invariants are covered.

## What "proven" means here, exactly — and what it does not

A row is `proven` when it cites a test that **introduces the defect the gate
exists to catch** and asserts the gate refuses. Not "a test exists": a test that
injects. The distinction is the whole rule — three of the seven controls found
dead in this repository had tests, and those tests passed against the broken code.

This check verifies the cited test **exists**. It does not run it. That is Rule 4
applied to itself — evidence that resolves is not evidence that runs — and the
division is deliberate: CI runs the full suite on every push, so a cited test that
breaks or starts skipping fails there, loudly, rather than making pre-commit slow
enough that people reach for `--no-verify`. If the suite ever stops covering
`tests/unit/`, this ledger silently weakens, and that is the assumption to check
first if it ever looks too green.

## The ratchet

Gates without evidence today are the baseline. New gates must arrive with
evidence or the check blocks; recorded debt may only shrink. The baseline is a
count rather than a list because the debt is uniform — every row in it says the
same thing, "nobody has demonstrated this can fail".
"""

from __future__ import annotations

import argparse
import re
import sys
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Final

REPO: Final = Path(__file__).resolve().parent.parent
LEDGER: Final = REPO / "docs" / "GATE_EVIDENCE.toml"

#: A hook is ours when its entry runs a script from this repository.
#: A hook entry that runs code THIS repository owns.
#:
#: Two forms, because matching only the first left a hole in the gate that
#: enforces gates: a hook whose entry is `python -m deployment.change_records`
#: was invisible to discovery, so it was silently exempt from Rule 1 — the
#: ledger reported the same count before and after it was added, and `--check`
#: passed. Every other gate's evidence is only as trustworthy as the census.
_OURS: Final = re.compile(r"(?:python\s+)?(scripts/[\w/]+\.(?:py|sh))")
_OURS_MODULE: Final = re.compile(r"python\s+-m\s+([\w]+(?:\.[\w]+)+)")

_HOOK_ID: Final = re.compile(r"^\s*-\s*id:\s*(\S+)\s*$")
_HOOK_ENTRY: Final = re.compile(r"^\s*entry:\s*(.+?)\s*$")


class EvidenceBroken(RuntimeError):
    """The check could not be performed, so its result means nothing."""


@dataclass(frozen=True)
class Gate:
    id: str
    kind: str
    runs: str


@dataclass(frozen=True)
class Entry:
    id: str
    kind: str = ""
    evidence: str = ""
    injected: str = ""
    note: str = ""


@dataclass(frozen=True)
class Baseline:
    unproven_count: int = 0


@dataclass
class Report:
    gates: int = 0
    proven: int = 0
    unproven: int = 0
    blocking: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


def _ci_gates(repo: Path) -> list[Gate]:
    directory = repo / "scripts" / "ci"
    if not directory.is_dir():
        return []
    return [Gate(p.stem, "ci_gate", str(p.relative_to(repo))) for p in sorted(directory.glob("gate_*.py"))]


def _precommit_gates(repo: Path) -> list[Gate]:
    config = repo / ".pre-commit-config.yaml"
    if not config.exists():
        return []
    out: list[Gate] = []
    current = ""
    for line in config.read_text(encoding="utf-8").splitlines():
        if m := _HOOK_ID.match(line):
            current = m.group(1)
            continue
        if (m := _HOOK_ENTRY.match(line)) and current:
            entry = m.group(1)
            if script := _OURS.search(entry):
                out.append(Gate(current, "precommit_hook", script.group(1)))
            elif module := _OURS_MODULE.search(entry):
                dotted = module.group(1)
                # Only ours: a `python -m` of a third-party tool is not a gate
                # this repository owns and cannot carry our injection evidence.
                if (repo / Path(dotted.replace(".", "/") + ".py")).exists():
                    out.append(Gate(current, "precommit_hook", dotted))
            current = ""
    return out


def discover_gates(repo: Path | None = None) -> list[Gate]:
    """Every gate this repository owns, found rather than remembered."""
    repo = repo or REPO
    gates = _ci_gates(repo) + _precommit_gates(repo)
    seen: dict[str, Gate] = {}
    for gate in gates:
        seen.setdefault(gate.id, gate)
    return list(seen.values())


def load(path: Path | None = None) -> tuple[list[Entry], Baseline]:
    path = path or LEDGER
    if not path.exists():
        return [], Baseline()
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    entries = [
        Entry(
            id=row["id"],
            kind=row.get("kind", ""),
            evidence=row.get("evidence", ""),
            injected=row.get("injected", ""),
            note=row.get("note", ""),
        )
        for row in data.get("gate", [])
    ]
    baseline = Baseline(unproven_count=int(data.get("baseline", {}).get("unproven_count", 0)))
    return entries, baseline


def check(
    repo: Path | None = None,
    ledger: Path | None = None,
    extra_gate_ids: list[str] | None = None,
    evidence_override: dict[str, str] | None = None,
) -> Report:
    """Has anything regressed against the ratchet?

    ``extra_gate_ids`` and ``evidence_override`` exist so the tests can prove
    this check fires, rather than asserting it does. A control whose own tests
    only ever feed it a clean tree is the defect it was built to catch.
    """
    repo = repo or REPO
    gates = discover_gates(repo)
    if extra_gate_ids:
        gates = gates + [Gate(g, "ci_gate", "invented") for g in extra_gate_ids]
    if not gates:
        raise EvidenceBroken(
            f"no gates discovered under {repo} — refusing to report a clean result from a sweep that examined nothing"
        )

    entries, baseline = load(ledger)
    by_id = {e.id: e for e in entries}
    report = Report(gates=len(gates))

    for gate in gates:
        entry = by_id.get(gate.id)
        if entry is None:
            report.blocking.append(
                f"{gate.id}: no row in {LEDGER.name}. A new gate ships with evidence it can "
                "fail, or it is treated as absent (Rule 1)."
            )
            continue
        evidence = (evidence_override or {}).get(gate.id, entry.evidence)
        if not evidence:
            report.unproven += 1
            continue
        if not (repo / evidence).exists():
            report.blocking.append(f"{gate.id}: cites evidence {evidence}, which does not exist.")
            continue
        report.proven += 1

    if report.unproven > baseline.unproven_count:
        report.blocking.append(
            f"gates without injection evidence rose to {report.unproven} "
            f"(baseline {baseline.unproven_count}). The ratchet only turns one way."
        )
    elif report.unproven < baseline.unproven_count:
        report.notes.append(
            f"{baseline.unproven_count - report.unproven} gate(s) proven since the baseline — "
            f"lower `unproven_count` to {report.unproven} in {LEDGER.name} to hold the ground."
        )
    return report


def toml_string(value: str) -> str:
    """Render *value* as a TOML basic string that reads back unchanged.

    The fields below are written by humans and preserved across regeneration,
    and they were preserved by interpolation:

        f'injected = "{prior.injected}"'

    `gate_d_model_accuracy`'s note contains a quoted phrase, so regenerating the
    ledger produced TOML that would not parse — and this ledger is the Rule 1
    ratchet, so one run of the documented `--generate` disabled the check that
    proves every other gate can fail. A backslash was worse than a quote: it
    parsed, as an escape sequence, silently altering the recorded evidence.

    Backslash first, or the escapes this adds get escaped again.
    """
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    escaped = escaped.replace("\n", "\\n").replace("\r", "\\r").replace("\t", "\\t")
    return f'"{escaped}"'


def generate(repo: Path | None = None, ledger: Path | None = None) -> str:
    """Rewrite the ledger, preserving every human-written field."""
    repo = repo or REPO
    ledger = ledger or LEDGER
    existing = {e.id: e for e in load(ledger)[0]}
    _, baseline = load(ledger)

    lines = [
        "# Gate injection evidence — Group 2 Rule 1.",
        "#",
        "# Generated by scripts/gate_evidence.py. Rows are discovered; the",
        "# `evidence`, `injected` and `note` fields are written by humans and",
        "# preserved across regeneration.",
        "#",
        "# evidence — path to a test that introduces the defect and asserts the",
        "#            gate refuses. Not 'a test exists': a test that injects.",
        "# injected — what defect was introduced. Rule 1's claim is about a",
        "#            specific failure, not about coverage.",
        "",
    ]
    unproven = 0
    for gate in sorted(discover_gates(repo), key=lambda g: (g.kind, g.id)):
        prior = existing.get(gate.id, Entry(gate.id))
        if not prior.evidence:
            unproven += 1
        lines += [
            "[[gate]]",
            f"id = {toml_string(gate.id)}",
            f"kind = {toml_string(gate.kind)}",
            f"runs = {toml_string(gate.runs)}",
            f"evidence = {toml_string(prior.evidence)}",
            f"injected = {toml_string(prior.injected)}",
        ]
        if prior.note:
            lines.append(f"note = {toml_string(prior.note)}")
        lines.append("")

    lines += [
        "[baseline]",
        "# Gates with no injection evidence, as at adoption. May only fall.",
        f"unproven_count = {baseline.unproven_count or unproven}",
        "",
    ]
    text = "\n".join(lines)
    ledger.write_text(text, encoding="utf-8")
    return text


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Gate injection evidence (Rule 1).")
    parser.add_argument("--check", action="store_true", help="Exit non-zero on a regression")
    parser.add_argument("--generate", action="store_true", help="Add rows for newly discovered gates")
    parser.add_argument("--adopt", action="store_true", help="Set the baseline from the current state")
    args = parser.parse_args(argv)

    if args.generate or args.adopt:
        if args.adopt:
            entries, _ = load()
            unproven = sum(1 for e in entries if not e.evidence)
            text = LEDGER.read_text(encoding="utf-8") if LEDGER.exists() else ""
            if text:
                LEDGER.write_text(
                    re.sub(r"unproven_count = \d+", f"unproven_count = {unproven}", text),
                    encoding="utf-8",
                )
        generate()
        print(f"wrote {LEDGER.relative_to(REPO)}")
        return 0

    try:
        report = check()
    except EvidenceBroken as exc:
        print(f"REFUSED — {exc}", file=sys.stderr)
        return 2

    print(f"gate evidence: {report.gates} gates · {report.proven} proven able to fail · {report.unproven} unproven")
    for note in report.notes:
        print(f"  note  {note}")
    for block in report.blocking:
        print(f"  BLOCK {block}", file=sys.stderr)
    if args.check and report.blocking:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
