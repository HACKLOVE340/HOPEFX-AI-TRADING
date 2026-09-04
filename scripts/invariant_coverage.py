#!/usr/bin/env python3
# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
scripts/invariant_coverage.py — the Invariant Coverage Report.

At platform scale, the risk is complexity: a critical component that nobody
checks, monitors, alerts on, or can recover. This report answers, in one place:

  1. What invariants exist?            MEASURED — the registry is discovered by
                                       introspection over the ``invariants``
                                       package on every run.
  2. What protection does each         DECLARED — the coverage matrix is the
     critical component *claim*?       hand-maintained manifest in
                                       ``invariants/registry.py``.
  3. Is that declaration internally    ``invariants.meta.verify_*_coverage``
     complete?                         over the declared counts.

**This report probes nothing.** It calls no predicate against a live component
and inspects no code path. Every value in the DECLARED section is a boolean
somebody typed; a literal cannot fail, so a complete matrix here is a statement
of intent, not evidence (F176). It previously printed ``FULL COVERAGE ✅`` off
those literals, which read as verification — and was measurably false while it
was printed: ``market_data_feed`` was declared protected while
``execution/engine.py`` skipped the data-layer gate in exactly the condition it
existed for (F84); ``order_execution`` was declared protected while the active
paper path had no risk layer at all (F142); ``kill_switch`` was declared alerted
while critical alerts never left the log (F159).

The manifest is still worth keeping and still worth gating on: a component
declared critical that does not even *claim* protection is a real gap. That is
all the exit code means.

Exit codes: 0 = the declaration is internally complete (NOT "verified"), 1 = a
declared gap (recovery gaps are surfaced as warnings, since DB/Redis
single-instance is a known infra choice — see the SPOF inventory in
scripts/runtime_invariant_check.py).

Usage:
    python scripts/invariant_coverage.py            # human report
    python scripts/invariant_coverage.py --json     # machine-readable
"""

from __future__ import annotations

import argparse
import json
import sys
import textwrap
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from invariants import meta
from invariants.registry import CRITICAL_COMPONENTS, coverage_counts, registry_summary

# Stated in one place so the human report and the JSON cannot drift apart.
NOT_VERIFIED_NOTICE = (
    "These flags are hand-maintained declarations in invariants/registry.py. "
    "They are NOT verified by probe: this report calls no predicate against a "
    "running component, so nothing below can fail on evidence."
)

# Components this report probes for real. Empty is the honest current answer;
# add a component here only when a probe actually runs against it, so the gap
# between what is declared and what is checked stays visible.
PROBED_COMPONENTS: tuple[str, ...] = ()


def build_report() -> dict:
    """Assemble the report.

    ``registry`` is measured (introspection). ``declared_coverage`` is the
    manifest, echoed as-is. The two are named differently on purpose: a consumer
    must be able to tell which is which without reading this file.
    """
    summary = registry_summary()
    counts = coverage_counts()

    # Run the meta-coverage invariants over the DECLARED counts. These check the
    # manifest against itself; they do not touch the components. Recovery is a
    # warning (known infra gap).
    gaps: list[dict] = []
    p, pt = counts["protected"]
    a, at = counts["alerted"]
    m, mt = counts["monitored"]
    r, rt = counts["recoverable"]
    checks = [
        ("invariant", meta.verify_invariant_coverage(p, pt), "ERROR"),
        (
            "monitoring",
            meta.verify_monitoring_coverage(m, mt) if hasattr(meta, "verify_monitoring_coverage") else [],
            "ERROR",
        ),
        ("alert", meta.verify_alert_coverage(a, at), "ERROR"),
        ("recovery", meta.verify_recovery_coverage(r, rt), "WARN"),
    ]
    for name, violations, severity in checks:
        for v in violations:
            gaps.append({"dimension": name, "severity": severity, "message": v.message})

    return {
        "measured": {
            "source": "introspection over the invariants package at run time",
            "registry": summary,
        },
        "declared": {
            "source": "invariants/registry.py CRITICAL_COMPONENTS (hand-maintained)",
            "verified_by_probe": False,
            "notice": NOT_VERIFIED_NOTICE,
            "coverage": {k: list(v) for k, v in counts.items()},
            "components": {name: dict(flags) for name, flags in CRITICAL_COMPONENTS.items()},
            "probed_components": list(PROBED_COMPONENTS),
        },
        # Kept at the top level: existing consumers read report["registry"] and
        # report["coverage"], and breaking them would be a second defect.
        "registry": summary,
        "coverage": {k: list(v) for k, v in counts.items()},
        "gaps": gaps,
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="HOPEFX invariant coverage report")
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    # argv is explicit so callers (tests, other scripts) are not parsing
    # whatever happens to be on sys.argv.
    args = ap.parse_args(argv)

    report = build_report()
    errors = [g for g in report["gaps"] if g["severity"] == "ERROR"]

    if args.json:
        print(json.dumps(report, indent=2))
        return 1 if errors else 0

    reg = report["registry"]
    print("HOPEFX Invariant Coverage Report\n" + "=" * 48)
    print("MEASURED — invariant registry, discovered by introspection this run")
    print(f"Registry: {reg['predicates']} predicates across {reg['modules']} modules")
    for mod, n in reg["by_module"].items():
        print(f"   {n:3d}  {mod}")
    print("-" * 48)
    print("DECLARED — critical-component matrix (not a measurement)")
    for line in textwrap.wrap(NOT_VERIFIED_NOTICE, width=74):
        print(f"  {line}")
    for dim, (cov, tot) in report["coverage"].items():
        print(f"   declared {dim:12s} {cov}/{tot}")
    if PROBED_COMPONENTS:
        print(
            f"  Probed for real ({len(PROBED_COMPONENTS)}/{len(CRITICAL_COMPONENTS)}): " + ", ".join(PROBED_COMPONENTS)
        )
    else:
        print(f"  Probed for real: none of the {len(CRITICAL_COMPONENTS)} components.")
    print("-" * 48)
    print("Critical components (declared flags):")
    for name, c in CRITICAL_COMPONENTS.items():
        flags = " ".join(
            k[0].upper() if c.get(k) else f"-{k[0]}" for k in ("protected", "monitored", "alerted", "recoverable")
        )
        print(f"   {name:20s} [{flags}]")
    if report["gaps"]:
        print("-" * 48)
        for g in report["gaps"]:
            print(f"   {('❌' if g['severity'] == 'ERROR' else '⚠️ ')} {g['dimension']}: {g['message']}")
    print("=" * 48)
    if errors:
        print(f"{len(errors)} declared gap(s) ❌")
    else:
        warns = len(report["gaps"]) - len(errors)
        tail = f" ({warns} declared warning(s))" if warns else ""
        print(f"Declaration internally complete{tail} — every critical component")
        print("declares the protections the meta-invariants require.")
        print("This is NOT a verification: no component was probed.")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
