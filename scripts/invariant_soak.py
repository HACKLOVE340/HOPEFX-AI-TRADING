#!/usr/bin/env python3
# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
scripts/invariant_soak.py — watch the invariant enforcement layer during the soak.

Polls GET /health/invariants on an interval and prints a running summary: the
mode, engine health, cumulative counters, and any NEW violations since the last
poll. This is the operator's view while the layer runs in MONITOR before flipping
to ENFORCE (see docs/INVARIANT_ROLLOUT.md).

Exit codes:
  0 — soak ended cleanly (Ctrl-C) with no checker errors and engine healthy
  1 — engine became unhealthy or checker errors were observed during the soak

Usage
-----
    python scripts/invariant_soak.py                         # localhost:8000, 30s
    python scripts/invariant_soak.py --url http://host:8000 --interval 15
    python scripts/invariant_soak.py --once                  # single snapshot

Stdlib only.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request

_COUNTER_KEYS = ("checks", "violations", "blocked", "halts_signalled", "checker_errors")


def _fetch(url: str, timeout: float) -> tuple[int, dict]:
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, json.loads(resp.read() or b"{}")
    except urllib.error.HTTPError as e:
        body = e.read() or b"{}"
        try:
            return e.code, json.loads(body)
        except Exception:
            return e.code, {}
    except Exception as e:
        return 0, {"error": str(e)}


def _print_snapshot(data: dict, prev: dict | None) -> None:
    mode = data.get("mode", "?")
    healthy = data.get("engine_healthy")
    counters = data.get("counters", {})
    stamp = time.strftime("%H:%M:%S")
    health_icon = "✅" if healthy else "❌"
    deltas = {}
    if prev is not None:
        pc = prev.get("counters", {})
        deltas = {k: counters.get(k, 0) - pc.get(k, 0) for k in _COUNTER_KEYS}

    def _d(k: str) -> str:
        d = deltas.get(k, 0)
        return f" (+{d})" if d else ""

    print(
        f"[{stamp}] mode={mode} engine={health_icon} "
        f"checks={counters.get('checks', 0)}{_d('checks')} "
        f"violations={counters.get('violations', 0)}{_d('violations')} "
        f"blocked={counters.get('blocked', 0)}{_d('blocked')} "
        f"halts={counters.get('halts_signalled', 0)}{_d('halts_signalled')} "
        f"checker_errors={counters.get('checker_errors', 0)}{_d('checker_errors')}"
    )

    # Surface any newly-recorded violations (the 'recent' ring buffer).
    recent = data.get("recent", [])
    prev_recent = (prev or {}).get("recent", [])
    new = recent[len(prev_recent):] if len(recent) >= len(prev_recent) else recent
    for item in new:
        print(f"        ⚠ {item.get('kind')}: {item.get('reason')} "
              f"(mode={item.get('mode')}, would_block={not item.get('allowed')})")


def main() -> int:
    ap = argparse.ArgumentParser(description="HOPEFX invariant enforcement soak monitor")
    ap.add_argument("--url", default="http://127.0.0.1:8000", help="base URL of the running app")
    ap.add_argument("--interval", type=float, default=30.0, help="poll interval seconds (default 30)")
    ap.add_argument("--timeout", type=float, default=10.0, help="HTTP timeout seconds")
    ap.add_argument("--once", action="store_true", help="print a single snapshot and exit")
    args = ap.parse_args()

    endpoint = args.url.rstrip("/") + "/health/invariants"
    print(f"Soak monitor → {endpoint} (interval {args.interval}s). Ctrl-C to stop.\n")

    prev: dict | None = None
    saw_problem = False
    try:
        while True:
            status, data = _fetch(endpoint, args.timeout)
            if status == 0:
                print(f"[{time.strftime('%H:%M:%S')}] unreachable: {data.get('error')}")
            elif status not in (200, 503) or "error" in data:
                print(f"[{time.strftime('%H:%M:%S')}] HTTP {status}: {data}")
            else:
                _print_snapshot(data, prev)
                if not data.get("engine_healthy") or data.get("counters", {}).get("checker_errors", 0):
                    saw_problem = True
                prev = data
            if args.once:
                break
            time.sleep(args.interval)
    except KeyboardInterrupt:
        print("\n— soak monitor stopped —")

    return 1 if saw_problem else 0


if __name__ == "__main__":
    sys.exit(main())
