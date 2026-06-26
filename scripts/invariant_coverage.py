#!/usr/bin/env python3
# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
scripts/invariant_coverage.py — the Invariant Coverage Report.

At platform scale, the risk is complexity: a critical component that nobody
checks, monitors, alerts on, or can recover. This report answers, in one place:

  1. What invariants exist?            (auto-discovered registry — one source of truth)
  2. Is every critical component       (coverage matrix from the manifest)
     protected / monitored / alerted / recoverable?
  3. Do the meta-coverage invariants   (invariants.meta.verify_*_coverage)
     pass?

Exit codes: 0 = full coverage, 1 = a coverage gap (recovery gaps are surfaced as
warnings, since DB/Redis single-instance is a known infra choice — see the SPOF
inventory in scripts/runtime_invariant_check.py).

Usage:
    python scripts/invariant_coverage.py            # human report
    python scripts/invariant_coverage.py --json     # machine-readable
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from invariants import meta
from invariants.registry import CRITICAL_COMPONENTS, coverage_counts, registry_summary


def build_report() -> dict:
    summary = registry_summary()
    counts = coverage_counts()

    # Run the meta-coverage invariants. Recovery is a warning (known infra gap).
    gaps: list[dict] = []
    p, pt = counts["protected"]
    a, at = counts["alerted"]
    m, mt = counts["monitored"]
    r, rt = counts["recoverable"]
    checks = [
        ("invariant", meta.verify_invariant_coverage(p, pt), "ERROR"),
        ("monitoring", meta.verify_monitoring_coverage(m, mt) if hasattr(meta, "verify_monitoring_coverage") else [], "ERROR"),
        ("alert", meta.verify_alert_coverage(a, at), "ERROR"),
        ("recovery", meta.verify_recovery_coverage(r, rt), "WARN"),
    ]
    for name, violations, severity in checks:
        for v in violations:
            gaps.append({"dimension": name, "severity": severity, "message": v.message})

    return {"registry": summary, "coverage": {k: list(v) for k, v in counts.items()}, "gaps": gaps}


def main() -> int:
    ap = argparse.ArgumentParser(description="HOPEFX invariant coverage report")
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    args = ap.parse_args()

    report = build_report()
    errors = [g for g in report["gaps"] if g["severity"] == "ERROR"]

    if args.json:
        print(json.dumps(report, indent=2))
        return 1 if errors else 0

    reg = report["registry"]
    print("HOPEFX Invariant Coverage Report\n" + "=" * 48)
    print(f"Registry: {reg['predicates']} predicates across {reg['modules']} modules")
    for mod, n in reg["by_module"].items():
        print(f"   {n:3d}  {mod}")
    print("-" * 48)
    print("Critical-component coverage:")
    for dim, (cov, tot) in report["coverage"].items():
        icon = "✅" if cov == tot else "⚠️ "
        print(f"   {icon} {dim:12s} {cov}/{tot}")
    print("-" * 48)
    print("Critical components:")
    for name, c in CRITICAL_COMPONENTS.items():
        flags = " ".join(k[0].upper() if c.get(k) else f"-{k[0]}" for k in ("protected", "monitored", "alerted", "recoverable"))
        print(f"   {name:20s} [{flags}]")
    if report["gaps"]:
        print("-" * 48)
        for g in report["gaps"]:
            print(f"   {('❌' if g['severity'] == 'ERROR' else '⚠️ ')} {g['dimension']}: {g['message']}")
    print("=" * 48)
    print("FULL COVERAGE ✅" if not errors else f"{len(errors)} coverage gap(s) ❌")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
