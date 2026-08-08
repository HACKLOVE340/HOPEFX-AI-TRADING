#!/usr/bin/env python3
# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
S1-12 — what the Kelly change does to position size, measured on real XAUUSD.

The backlog carried "a backtest comparison for the Kelly sizing change before
live". This is that comparison.

**What changed.** ``RiskManager._kelly`` takes Kelly's ``b`` — how much a trade
wins per unit risked. It used to synthesise it from the model's confidence::

    b = max(0.5, confidence * 3.0)          # before (S1-12)
    b = |target - entry| / |entry - stop|   # after, when stops are known

Those are different quantities. Break-even win rate is ``1/(1+b)``, so under the
old rule it moved with the model's *certainty* rather than with the trade's
actual stop and target: at ``confidence=0.7`` the code assumed 2.1:1 odds, and
any win probability above 0.323 counted as positive edge — on odds nothing
verified.

**What this script does, and does not do.** It drives the real
``RiskManager._kelly`` over real XAUUSD bars, sizing each signal both ways, and
reports the distribution of the difference plus an equity simulation. It is a
**sizing comparison**, not a strategy backtest: it does not claim the strategy is
profitable, only what the sizing rule change does to exposure and drawdown for a
given edge. The win probabilities are swept rather than predicted, precisely so
the result does not depend on trusting the model.

Run:  python scripts/kelly_sizing_comparison.py
      python scripts/kelly_sizing_comparison.py --csv data/XAUUSD_5Y.csv --trials 20000
"""

from __future__ import annotations

import argparse
import csv
import math
import random
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from risk.manager import _KELLY_FRACTION, _MAX_KELLY_FRACTION, RiskManager

# ATR multiples the risk manager itself uses to derive a stop and target when a
# caller supplies none — so the reward:risk sampled here matches production.
from risk.manager import _STOP_ATR_MULT, _TARGET_ATR_MULT


def load_bars(path: Path, limit: int | None = None) -> list[dict[str, float]]:
    rows: list[dict[str, float]] = []
    with path.open(newline="") as fh:
        for r in csv.DictReader(fh):
            try:
                bar = {
                    "high": float(r.get("High") or r.get("high") or 0),
                    "low": float(r.get("Low") or r.get("low") or 0),
                    "close": float(r.get("Close") or r.get("close") or 0),
                }
            except (TypeError, ValueError):
                continue
            if bar["close"] > 0 and bar["high"] >= bar["low"]:
                rows.append(bar)
            if limit and len(rows) >= limit:
                break
    return rows


def atr(bars: list[dict[str, float]], i: int, period: int = 14) -> float:
    lo = max(0, i - period)
    window = bars[lo:i] or bars[: i + 1]
    if not window:
        return 0.0
    return statistics.fmean(b["high"] - b["low"] for b in window)


def old_kelly(probability: float, confidence: float) -> float:
    """The pre-S1-12 rule, reproduced exactly for comparison."""
    p = max(0.01, min(probability, 0.99))
    q = 1.0 - p
    b = max(0.5, confidence * 3.0)
    return max(0.0, min((p * b - q) / b, _MAX_KELLY_FRACTION))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", default="data/XAUUSD_5Y.csv")
    ap.add_argument("--trials", type=int, default=10_000)
    ap.add_argument("--equity", type=float, default=100_000.0)
    ap.add_argument("--seed", type=int, default=7)
    args = ap.parse_args()

    random.seed(args.seed)

    path = Path(args.csv)
    if not path.exists():
        print(f"no such file: {path}", file=sys.stderr)
        return 2
    bars = load_bars(path)
    if len(bars) < 100:
        print(f"not enough bars in {path} ({len(bars)})", file=sys.stderr)
        return 2

    print(f"XAUUSD bars: {len(bars):,} from {path}")
    print(f"Kelly fraction in use: {_KELLY_FRACTION}   cap: {_MAX_KELLY_FRACTION}\n")

    # ── 1. The reward:risk the new rule actually sees, on real bars ──────────
    rrs = []
    for i in range(20, len(bars)):
        a = atr(bars, i)
        if a <= 0:
            continue
        stop_d = a * _STOP_ATR_MULT
        target_d = a * _TARGET_ATR_MULT
        if stop_d > 0:
            rrs.append(target_d / stop_d)
    rr_med = statistics.median(rrs)
    print("── Reward:risk from the risk manager's own ATR stops ──")
    print(
        f"   median b = {rr_med:.3f}   (constant by construction: "
        f"target {_TARGET_ATR_MULT}×ATR / stop {_STOP_ATR_MULT}×ATR)"
    )
    print(f"   break-even win rate = 1/(1+b) = {1 / (1 + rr_med):.1%}\n")

    # ── 2. Sizing, swept across confidence and win probability ──────────────
    print("── Kelly fraction: old (confidence proxy) vs new (real R:R) ──")
    print(f"   {'conf':>6} {'p(win)':>8} {'b_old':>7} {'b_new':>7} {'f_old':>8} {'f_new':>8} {'Δ notional':>12}")
    rows = []
    for conf in (0.55, 0.60, 0.70, 0.80, 0.90):
        for p in (0.40, 0.50, 0.55, 0.60, 0.70):
            f_old = old_kelly(p, conf)
            f_new = RiskManager._kelly(p, conf, reward_risk=rr_med)
            n_old = args.equity * f_old * _KELLY_FRACTION
            n_new = args.equity * f_new * _KELLY_FRACTION
            delta = (n_new / n_old - 1) if n_old > 0 else float("inf") if n_new > 0 else 0.0
            rows.append((conf, p, f_old, f_new, n_old, n_new))
            d = "—" if not math.isfinite(delta) else f"{delta:+.0%}"
            print(
                f"   {conf:>6.2f} {p:>8.2f} {max(0.5, conf * 3):>7.2f} {rr_med:>7.2f} "
                f"{f_old:>8.4f} {f_new:>8.4f} {d:>12}"
            )

    bigger = sum(1 for *_x, o, n in rows if n > o + 1e-12)
    smaller = sum(1 for *_x, o, n in rows if n < o - 1e-12)
    print(f"\n   new rule sizes SMALLER in {smaller}/{len(rows)} cells, larger in {bigger}/{len(rows)}")

    # ── 3. Equity simulation, swept AROUND the break-even ───────────────────
    #
    # The first version of this swept p = 0.45–0.55 against b = 2.0, where the
    # edge is +0.35 per unit risked and both rules simply compound: median
    # endings of 10^24 and zero ruin, which says nothing about either. The
    # question a sizing rule has to answer is what happens when the edge is
    # *absent* — at and below the 1/(1+b) break-even — because that is the case
    # the model is wrong about, and being wrong is what sizing protects against.
    #
    # Costs are charged too: a 30-cent XAUUSD spread against an ATR-derived stop
    # is a real drag that a costless simulation hides.
    breakeven = 1.0 / (1.0 + rr_med)
    spread_cost = 0.02  # fraction of the amount risked, per round trip

    print(f"\n── Equity simulation — 500 trades, {max(200, args.trials // 50)} paths ──")
    print(f"   break-even win rate is {breakeven:.1%}; costs {spread_cost:.0%} of risk per trade")
    print(f"   {'true p':>8} {'rule':>6} {'median end':>13} {'p(lose 50%)':>12} {'med maxDD':>10}")
    for true_p in (breakeven - 0.08, breakeven - 0.03, breakeven, breakeven + 0.05):
        for label, use_new in (("old", False), ("new", True)):
            ends, dds = [], []
            for _ in range(max(200, args.trials // 50)):
                eq = args.equity
                peak = eq
                dd = 0.0
                for _t in range(500):
                    conf = random.uniform(0.55, 0.9)
                    f = RiskManager._kelly(true_p, conf, reward_risk=rr_med) if use_new else old_kelly(true_p, conf)
                    stake = eq * f * _KELLY_FRACTION
                    if stake <= 0:
                        continue
                    eq += stake * rr_med if random.random() < true_p else -stake
                    eq -= stake * spread_cost
                    if eq <= args.equity * 0.01:
                        eq = 0.0
                        break
                    peak = max(peak, eq)
                    dd = max(dd, 1 - eq / peak)
                ends.append(eq)
                dds.append(dd)
            med = statistics.median(ends)
            ruin = sum(1 for e in ends if e < args.equity * 0.5) / len(ends)
            print(f"   {true_p:>8.1%} {label:>6} {med:>13,.0f} {ruin:>11.0%} {statistics.median(dds):>10.1%}")

    print("\nRead this as a sizing comparison, not a profitability claim: the win")
    print("probabilities are swept, not predicted, so nothing here depends on")
    print("trusting the model. What it shows is how much exposure each rule takes")
    print("for a given edge, and what that costs when the edge is absent.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
