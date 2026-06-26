#!/usr/bin/env python3
# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
scripts/forensic_replay.py — replay a past decision or failure for forensics.

Drives ``forensics.replay`` to reconstruct decisions (why did the AI do that;
would today's controls allow it?) and to confirm failures reproduce (regression
checks). Reads JSON / JSONL record files; never trades.

Usage
-----
    # Replay one or many recorded DECISIONS (decision -> ... -> trade chain)
    python scripts/forensic_replay.py decision --file decisions.jsonl

    # Replay recorded FAILURES (confirm they still reproduce)
    python scripts/forensic_replay.py failure --file failures.json

    # Inline single record
    python scripts/forensic_replay.py failure --record '{"kind":"reconciliation","inputs":{"internal_value":1,"external_value":9,"value_tol":0.01},"expected_violation":true}'

Exit codes: 0 = all decisions reconstructable / all failures behaved as expected;
1 = a gap (a non-reconstructable decision, or a failure that did not reproduce).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from forensics.replay import load_records, replay_batch


def main() -> int:
    ap = argparse.ArgumentParser(description="HOPEFX forensic replay (decision / failure)")
    ap.add_argument("mode", choices=("decision", "failure"), help="what to replay")
    ap.add_argument("--file", help="JSON array or JSONL file of records")
    ap.add_argument("--record", help="a single inline JSON record")
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    args = ap.parse_args()

    if args.record:
        records = [json.loads(args.record)]
    elif args.file:
        records = load_records(args.file)
    else:
        ap.error("provide --file or --record")
        return 2

    report = replay_batch(records, mode=args.mode)

    if args.json:
        print(json.dumps(report, indent=2))
    else:
        s = report["summary"]
        print(f"Forensic replay — {args.mode}  ({s['total']} record(s))\n" + "=" * 52)
        for r in report["results"]:
            if args.mode == "failure":
                icon = "✅" if r.get("reproduced") else "❌"
                print(
                    f"{icon} {r.get('kind'):18s} expected_violation={r.get('expected_violation')} "
                    f"observed={r.get('observed_violation')}"
                )
            else:
                icon = "✅" if r.get("reconstructable") else "❌"
                print(
                    f"{icon} decision={r.get('decision_id')} reconstructable={r.get('reconstructable')} "
                    f"would_pass_today={r.get('would_pass_today')}"
                )
                if r.get("trace_gaps"):
                    print(f"      missing links: {r['trace_gaps']}")
            for v in r.get("violations", []):
                print(f"      → [{v['severity']}] {v['rule']}: {v['message']}")
            if r.get("error"):
                print(f"      → error: {r['error']}")
        print("=" * 52)
        print(json.dumps(s))

    # Exit non-zero on a forensic gap.
    if args.mode == "failure":
        bad = [r for r in report["results"] if not r.get("reproduced")]
    else:
        bad = [r for r in report["results"] if not r.get("reconstructable")]
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
