#!/usr/bin/env python3
# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""What the feature-drift guard is actually measuring, right now.

    python scripts/drift_guard_report.py
    python scripts/drift_guard_report.py --top 25
    python scripts/drift_guard_report.py --json

Why this exists as a script rather than a paragraph in an ADR.

`DRIFT_BLOCK` reads as one switch, and it is the fourth of four conditions. The
guard is only running when the training stats load, when they cover at least
`DRIFT_MIN_COVERAGE` of the live vector, and when the rolling buffer has filled
`DRIFT_WINDOW` scored predictions. Each of the first three makes
`_check_feature_drift` return False, which at the `if drift and _DRIFT_BLOCK`
call site is indistinguishable from "measured, and clean". `drift_guard_active()`
and `drift_status()` exist to separate those cases; this report puts them in
front of a human alongside the number that matters.

And the number that matters is not `z_max` on its own. A feature the pipeline
could not supply is zero-filled before the guard sees it, and a zero against a
non-zero training mean is a large z — so an absent macro feed reads as drift.
Measured on the committed series on 2026-09-13, 12 of the 14 features over the
threshold had a live value of exactly 0.0. Blocking on that total halts trading
for a feed outage and reports `feature_drift`, which sends an operator to
retrain a model that was never the problem.

So the report separates the two populations. `drifted` is what `DRIFT_BLOCK`
claims to act on; `imputed` is what it would mostly act on today. See
docs/decisions/0019-drift-blocking-model-quality-blocking-and-the-z-threshold.md.

This reports; it decides nothing and changes no state.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def _rank(scored, train_stats, threshold: float) -> list[dict]:
    """z per feature, against the training distribution the guard compares to.

    Uses the single scored vector rather than the rolling buffer mean. Over a
    stable window the two agree closely, and requiring a full buffer would make
    this report cost `DRIFT_WINDOW` predictions to answer a question about
    coverage. `z_max` from `drift_status()` remains the authoritative figure;
    these are the per-feature contributions behind it.
    """
    row = scored.iloc[0]
    out: list[dict] = []
    for name in scored.columns:
        stat = train_stats.get(name)
        if stat is None:
            continue
        mean = float(stat.get("mean", 0.0))
        std = max(float(stat.get("std", 1.0)), 1e-9)
        live = float(row[name])
        out.append(
            {
                "feature": name,
                "z": abs(live - mean) / std,
                "live": live,
                "train_mean": mean,
                # A live value of exactly 0.0 against a non-zero training mean is
                # the imputation signature. It is not proof — a feature can
                # legitimately be zero — so this is reported as a population to
                # weigh, never as a reason to exempt a feature from the guard.
                "zero_filled": live == 0.0 and mean != 0.0,
                "over_threshold": abs(live - mean) / std > threshold,
            }
        )
    out.sort(key=lambda d: d["z"], reverse=True)
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--symbol", default="XAUUSD", help="cached symbol (default: XAUUSD)")
    ap.add_argument("--bars", type=int, default=400, help="bars fed to the model (default: 400)")
    ap.add_argument("--top", type=int, default=15, help="features to list (default: 15)")
    ap.add_argument("--json", action="store_true", dest="as_json", help="machine-readable output")
    args = ap.parse_args(argv)

    logging.basicConfig(level=logging.ERROR, format="  %(levelname)s %(name)s: %(message)s")

    import ml.inference_engine as ie
    from ml.cached_series import CLEAN_SINCE, load_cached_daily
    from ml.inference_engine import get_inference_engine

    try:
        series = load_cached_daily(args.symbol, since=CLEAN_SINCE.get(args.symbol.upper().replace("_", "")))
    except FileNotFoundError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    engine = get_inference_engine()
    sym = f"{series.symbol[:3]}_{series.symbol[3:]}"
    engine.predict(series.frame.tail(args.bars), symbol=sym)

    status = engine.drift_status()
    flags = {
        "DRIFT_BLOCK": ie._DRIFT_BLOCK,
        "MODEL_QUALITY_BLOCK": ie._MODEL_QUALITY_BLOCK,
        "STALE_MODEL_BLOCK": ie._STALE_MODEL_BLOCK,
        "DRIFT_Z_THRESHOLD": ie._DRIFT_Z_THRESHOLD,
        "DRIFT_MIN_COVERAGE": ie._DRIFT_MIN_COVERAGE,
        "DRIFT_WINDOW": ie._DRIFT_WINDOW,
    }

    ranked: list[dict] = []
    stats = getattr(engine, "_train_stats", None)
    scored = None
    for attr in ("_predictor", "predictor"):
        candidate = getattr(engine, attr, None)
        if candidate is not None and getattr(candidate, "last_scored_features", None) is not None:
            scored = candidate.last_scored_features
            break
    if stats and scored is not None and not scored.empty:
        ranked = _rank(scored, stats, ie._DRIFT_Z_THRESHOLD)

    over = [r for r in ranked if r["over_threshold"]]
    over_imputed = [r for r in over if r["zero_filled"]]
    payload = {
        "data": series.describe(),
        "flags": flags,
        "status": {k: status.get(k) for k in ("active", "reason", "covered", "total", "z_max", "drift_detected")},
        "compared": len(ranked),
        "over_threshold": len(over),
        "over_threshold_zero_filled": len(over_imputed),
        "zero_filled_total": sum(1 for r in ranked if r["zero_filled"]),
        "top": ranked[: args.top],
    }

    if args.as_json:
        print(json.dumps(payload, indent=2, default=float))
        return 0

    print("─" * 78)
    print("DATA")
    print("─" * 78)
    print(f"  {series.describe()}")
    if series.is_stale:
        print(f"  NOT LIVE — ends {series.age_days} days ago. Features needing a live store")
        print("  are zero-filled here, which inflates z. Read the split below, not z_max alone.")

    print()
    print("─" * 78)
    print("FLAGS AS IMPORTED")
    print("─" * 78)
    for key, value in flags.items():
        print(f"  {key:<22} {value}")

    print()
    print("─" * 78)
    print("IS THE GUARD RUNNING?")
    print("─" * 78)
    covered, total = status.get("covered") or 0, status.get("total") or 0
    pct = f"{covered / total * 100:.1f}%" if total else "n/a"
    print(f"  active         {status.get('active')}   reason: {status.get('reason')}")
    print(f"  coverage       {covered}/{total} ({pct}), floor {ie._DRIFT_MIN_COVERAGE:.0%}")
    print(f"  drift_detected {status.get('drift_detected')}   z_max {status.get('z_max')}")
    buffered = len(getattr(engine, "_drift_buffer", ()))
    if buffered < ie._DRIFT_WINDOW:
        # Without this line the two halves of this report contradict each other:
        # z_max reads 0.0 while the table below shows z up to 19. Both are right
        # — `_check_feature_drift` returns before scoring until the buffer fills
        # — and a reader who takes z_max as "all clear" has been misled by a
        # number that means "not measured yet". Unmeasured is never zero.
        print(
            f"  buffer         {buffered}/{ie._DRIFT_WINDOW} — z_max above is NOT a clean"
            " result, it is 'not measured yet'."
        )
        print(f"                 the guard cannot fire for the first {ie._DRIFT_WINDOW} predictions after any restart.")
    if not status.get("active"):
        print("  -> DRIFT_BLOCK cannot act: the guard is not running. Fix coverage first.")

    if ranked:
        print()
        print("─" * 78)
        print("WHAT THE z IS MADE OF")
        print("─" * 78)
        print(f"  {'z':>9}  {'feature':<28} {'live':>12} {'train_mean':>12}  zero-filled")
        for rec in ranked[: args.top]:
            mark = "YES" if rec["zero_filled"] else ""
            print(f"  {rec['z']:9.2f}  {rec['feature']:<28} {rec['live']:12.4f} {rec['train_mean']:12.4f}  {mark}")
        print()
        print(f"  compared            {len(ranked)}")
        print(f"  zero-filled         {payload['zero_filled_total']}")
        print(f"  over z={ie._DRIFT_Z_THRESHOLD:<5}         {len(over)}")
        print(f"    of which zero-filled  {len(over_imputed)}  <- absent data, not drift")
        print(f"    of which drifted      {len(over) - len(over_imputed)}")
        if over and len(over_imputed) > len(over) - len(over_imputed):
            print()
            print("  Most of what would trigger a block is missing data rather than drift.")
            print("  Enabling DRIFT_BLOCK in this state halts trading on a feed outage and")
            print("  reports it as feature_drift. See docs/decisions/0019-*.md.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
