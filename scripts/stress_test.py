#!/usr/bin/env python3
# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
scripts/stress_test.py — scenario stress test & resilience drill harness.

Institutional platforms must regularly simulate rare shocks — flash crashes,
liquidity freezes, exchange outages, AI manipulation — and verify the platform's
controls still hold ("anticipating the unthinkable" + "resilience drills"). This
harness runs a battery of named scenarios through the *pure invariant predicates*
(no live trading, no side effects) and reports which controls would fire.

Each scenario asserts the EXPECTED control response: a market-shock scenario
should trip the drawdown/daily-loss limits; a liquidity freeze should fail the
order-liquidity check; an exchange outage should keep the blast radius contained
via failover. A scenario "passes" when the controls respond as designed.

Run it on a schedule (e.g. weekly) or before a release. Stdlib + invariants only.

Usage
-----
    python scripts/stress_test.py            # run all scenarios, human report
    python scripts/stress_test.py --json     # machine-readable
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from invariants import risk, systems
from invariants.governance import verify_strategy_viable_after_costs
from invariants.market import verify_data_freshness
from invariants.resilience import verify_chaos_survival, verify_failover_ready


def _expect_violation(name: str, control: str, violations: list, expect: bool) -> dict:
    """A scenario step passes when the control fires (or stays silent) as designed."""
    fired = bool(violations)
    ok = fired == expect
    return {
        "scenario": name,
        "control": control,
        "expected": "fire" if expect else "hold",
        "observed": "fired" if fired else "held",
        "ok": ok,
        "detail": violations[0].message if violations else "",
    }


def run_scenarios() -> list[dict]:
    results: list[dict] = []

    # 1. Flash crash — a -12% intraday move must trip the drawdown limit.
    results.append(_expect_violation("flash_crash", "drawdown_limit", risk.verify_drawdown(0.12, 0.10), expect=True))
    results.append(
        _expect_violation("flash_crash", "daily_loss_limit", risk.verify_daily_loss(0.08, 0.05), expect=True)
    )

    # 2. Liquidity freeze — order dwarfs available liquidity → must be flagged.
    results.append(
        _expect_violation(
            "liquidity_freeze",
            "order_liquidity",
            risk.verify_order_liquidity(1_000_000, 500_000, max_fraction=0.25),
            expect=True,
        )
    )

    # 3. Stale feed (data outage) — a 120s-old tick must fail freshness.
    results.append(
        _expect_violation("data_outage", "market_data_freshness", verify_data_freshness(120.0, 5.0), expect=True)
    )

    # 4. Exchange outage — with failover (>=1 standby) the platform survives.
    results.append(_expect_violation("exchange_outage", "failover_ready", verify_failover_ready(1, 1), expect=False))
    results.append(
        _expect_violation("exchange_outage", "blast_radius", systems.verify_blast_radius_contained(1, 5), expect=False)
    )

    # 5. Cascading failure — most components down must breach blast-radius.
    results.append(
        _expect_violation("cascading_failure", "blast_radius", systems.verify_blast_radius_contained(4, 5), expect=True)
    )

    # 6. Chaos drill — broker + DB offline simultaneously must be survivable.
    results.append(
        _expect_violation(
            "chaos_drill",
            "chaos_survival",
            verify_chaos_survival({"broker_offline": True, "db_offline": True}),
            expect=False,
        )
    )

    # 7. Cost shock — fees/slippage spike makes a strategy unviable net.
    results.append(
        _expect_violation(
            "cost_shock", "after_cost_viability", verify_strategy_viable_after_costs(100, 60, 40, 20), expect=True
        )
    )

    # 8. Leverage spike — a 50x book must breach the leverage limit.
    results.append(_expect_violation("leverage_spike", "leverage_limit", risk.verify_leverage(50, 10), expect=True))

    return results


def main() -> int:
    ap = argparse.ArgumentParser(description="HOPEFX scenario stress test / resilience drill")
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    args = ap.parse_args()

    results = run_scenarios()
    failed = [r for r in results if not r["ok"]]

    if args.json:
        print(json.dumps({"results": results, "failed": len(failed), "total": len(results)}, indent=2))
    else:
        print("HOPEFX scenario stress test / resilience drill\n" + "=" * 48)
        for r in results:
            icon = "✅" if r["ok"] else "❌"
            print(f"{icon} {r['scenario']:18s} {r['control']:22s} expected={r['expected']:4s} observed={r['observed']}")
            if r["detail"]:
                print(f"      → {r['detail']}")
        print("=" * 48)
        print(f"{len(results) - len(failed)}/{len(results)} controls responded as designed.")
        if failed:
            print(f"⚠️  {len(failed)} control(s) did NOT respond as designed — investigate.")

    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
