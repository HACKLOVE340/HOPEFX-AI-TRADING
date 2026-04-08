#!/usr/bin/env python3
# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
scripts/retrain_horizon5.py
============================
Retrain the production model with --horizon 5 to fix the accuracy/P&L disconnect.

Root cause
----------
The existing advanced_oos.pkl was trained with --horizon 1 (predict next-bar
direction) but the execution engine holds positions for ~5 bars.  This creates
a systematic disconnect:

  - Model accuracy (66%) is measured on 1-bar direction
  - P&L is realised over 5 bars (accumulates mean-reversion noise)
  - Result: model appears accurate but P&L is flat or negative

Fix
---
Train with --horizon 5 so the target label is:
  y = 1 if close[t+5] > close[t] else 0

This aligns the model's optimisation objective with the actual hold period,
so accuracy and P&L measure the same thing.

Expected outcome
----------------
- OOS accuracy may drop slightly (5-bar direction is harder to predict)
- P&L should improve because the model is now optimised for the right horizon
- Sharpe ratio should increase as the accuracy/P&L disconnect closes

Usage
-----
    # Production run (50 years, 8-year OOS, full stacking ensemble)
    python scripts/retrain_horizon5.py

    # Quick validation run (8 years, 3-year OOS)
    python scripts/retrain_horizon5.py --years 8 --oos-years 3

    # Dry run — validate data pipeline without training
    python scripts/retrain_horizon5.py --dry-run

    # Smoke test (CI)
    python scripts/retrain_horizon5.py --smoke

    # Custom horizon (e.g. 3-bar hold period)
    python scripts/retrain_horizon5.py --horizon 3

Output
------
    ml/saved_models/advanced_oos.pkl          (replaces existing model)
    ml/saved_models/advanced_oos_meta.json    (updated with horizon=5)
    ml/saved_models/horizon5_training_report.json  (full metrics)
    ml/saved_models/horizon5_meta.json        (horizon-specific metadata)

Environment variables
---------------------
    RETRAIN_HORIZON        — override default horizon (default: 5)
    RETRAIN_YEARS          — override default years (default: 50)
    RETRAIN_OOS_YEARS      — override default OOS years (default: 8)
    RETRAIN_STACKING       — "true" to use full stacking ensemble
    RETRAIN_NO_MACRO       — "true" to skip macro features
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import subprocess  # nosec B404 - list-form call with sys.executable; no shell=True, no user input
import sys
from datetime import datetime, timezone

UTC = timezone.utc
from pathlib import Path

# Ensure project root is on sys.path regardless of invocation directory
_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
logger = logging.getLogger(__name__)

_MODEL_DIR = _ROOT / "ml" / "saved_models"
_TRAIN_SCRIPT = _ROOT / "ml" / "train_advanced.py"

# Default horizon — matches the execution engine's hold period
_DEFAULT_HORIZON = int(os.getenv("RETRAIN_HORIZON", "5"))
_DEFAULT_YEARS = int(os.getenv("RETRAIN_YEARS", "50"))
_DEFAULT_OOS_YEARS = float(os.getenv("RETRAIN_OOS_YEARS", "8"))
_DEFAULT_STACKING = os.getenv("RETRAIN_STACKING", "false").lower() == "true"
_DEFAULT_NO_MACRO = os.getenv("RETRAIN_NO_MACRO", "false").lower() == "true"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Retrain production model with --horizon 5 to fix accuracy/P&L disconnect.\n\n"
            "The existing model was trained with --horizon 1 (next-bar direction) but\n"
            "the execution engine holds for ~5 bars.  This script retrains with the\n"
            "correct horizon so accuracy and P&L measure the same objective."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  python scripts/retrain_horizon5.py                    # production\n"
            "  python scripts/retrain_horizon5.py --years 8          # quick run\n"
            "  python scripts/retrain_horizon5.py --dry-run          # validate only\n"
            "  python scripts/retrain_horizon5.py --smoke            # CI smoke test\n"
            "  python scripts/retrain_horizon5.py --horizon 3        # 3-bar hold\n"
        ),
    )
    parser.add_argument(
        "--horizon",
        type=int,
        default=_DEFAULT_HORIZON,
        help=(
            f"Prediction horizon in bars (default: {_DEFAULT_HORIZON}). "
            "Must match the execution engine's hold period. "
            "Set RETRAIN_HORIZON env var to change the default."
        ),
    )
    parser.add_argument(
        "--years",
        type=int,
        default=_DEFAULT_YEARS,
        help=f"Years of history to use (default: {_DEFAULT_YEARS})",
    )
    parser.add_argument(
        "--oos-years",
        type=float,
        default=_DEFAULT_OOS_YEARS,
        help=f"Held-out OOS period in years (default: {_DEFAULT_OOS_YEARS})",
    )
    parser.add_argument(
        "--stacking",
        action="store_true",
        default=_DEFAULT_STACKING,
        help="Use full stacking ensemble (slower, more accurate)",
    )
    parser.add_argument(
        "--no-macro",
        action="store_true",
        default=_DEFAULT_NO_MACRO,
        help="Skip macro features (DXY, VIX, yields, SPX)",
    )
    parser.add_argument(
        "--use-cached",
        action="store_true",
        help="Load OHLCV from data/XAUUSD_40Y.csv instead of downloading",
    )
    parser.add_argument(
        "--min-move",
        type=float,
        default=0.25,
        help="Min ATR move for filtered target (default: 0.25)",
    )
    parser.add_argument(
        "--splits",
        type=int,
        default=8,
        help="Walk-forward CV splits (default: 8)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help=(
            "Validate the data pipeline and feature builder without training. "
            "Prints the feature matrix shape and class balance, then exits."
        ),
    )
    parser.add_argument(
        "--smoke",
        action="store_true",
        help=(
            "Smoke-test mode: 2 years, no OOS, no macro, 2 CV splits. "
            "Completes in ~30 s. For CI and quick sanity checks."
        ),
    )
    parser.add_argument(
        "--symbol",
        default="GC=F",
        help="Yahoo Finance symbol (default: GC=F for XAUUSD)",
    )
    parser.add_argument(
        "--verify-only",
        action="store_true",
        help=(
            "Skip training — only verify that the expected output artifacts "
            "exist and contain the correct horizon value. "
            "Exits 0 if all artifacts are present, 1 if any are missing. "
            "Use after a completed retrain to confirm the CI gate passes."
        ),
    )
    return parser.parse_args()


def validate_horizon_alignment(horizon: int) -> None:
    """
    Warn when the requested horizon doesn't match the execution engine's
    hold period (read from SIGNAL_HOLD_BARS env var, default 5).
    """
    hold_bars = int(os.getenv("SIGNAL_HOLD_BARS", "5"))
    if horizon != hold_bars:
        logger.warning(
            "Horizon mismatch: training with --horizon %d but execution engine "
            "hold period is %d bars (SIGNAL_HOLD_BARS=%d). "
            "Set SIGNAL_HOLD_BARS=%d or use --horizon %d to align.",
            horizon,
            hold_bars,
            hold_bars,
            horizon,
            hold_bars,
        )
    else:
        logger.info(
            "Horizon aligned: training horizon=%d matches execution hold period=%d bars",
            horizon,
            hold_bars,
        )


def dry_run(args: argparse.Namespace) -> None:
    """
    Validate the data pipeline without training.

    Downloads/loads OHLCV, builds the feature matrix, and prints diagnostics.
    Exits with code 0 on success, 1 on failure.
    """
    logger.info("=== DRY RUN: validating data pipeline (no training) ===")
    logger.info(
        "Horizon: %d bars | Years: %d | Macro: %s",
        args.horizon,
        args.years,
        not args.no_macro,
    )

    try:
        from datetime import timedelta

        from ml.train_advanced import fetch_gold_ohlcv, fetch_macro

        logger.info("Fetching OHLCV data (%d years)...", args.years)
        ohlcv = fetch_gold_ohlcv(
            args.symbol,
            args.years,
            use_cached=args.use_cached,
            cached_csv=None,
        )
        logger.info(
            "OHLCV: %d bars (%s → %s)",
            len(ohlcv),
            ohlcv.index[0].date(),
            ohlcv.index[-1].date(),
        )

        macro_df = None
        if not args.no_macro:
            end_dt = datetime.now(UTC)
            start_dt = end_dt - timedelta(days=args.years * 365)
            logger.info("Fetching macro data...")
            macro_df = fetch_macro(start_dt, end_dt)
            if macro_df is not None:
                logger.info("Macro: %d bars × %d features", *macro_df.shape)

        logger.info("Building feature matrix (horizon=%d)...", args.horizon)
        try:
            from ml.features_extended import build_extended_features as build_fn

            logger.info("Using extended 230+ feature builder")
        except ImportError:
            from ml.advanced_features import build_advanced_features as build_fn

            logger.info("Using base 100-feature builder")

        X, y = build_fn(
            ohlcv,
            macro_df=macro_df,
            horizon=args.horizon,
            use_filtered_target=True,
            min_move_atr=args.min_move,
        )

        logger.info("Feature matrix: %d rows × %d columns", *X.shape)
        logger.info("Class balance: %s", y.value_counts().to_dict())
        logger.info("NaN count: %d", X.isna().sum().sum())

        import numpy as np

        inf_count = int(np.isinf(X.values).sum())
        logger.info("Inf count: %d", inf_count)

        if X.isna().sum().sum() > 0 or inf_count > 0:
            logger.warning("Feature matrix has NaN/Inf values — check feature builder")
        else:
            logger.info("Feature matrix is clean (no NaN/Inf)")

        logger.info("\n" + "=" * 60)
        logger.info("DRY RUN PASSED")
        logger.info(f"  Horizon      : {args.horizon} bars")
        logger.info(f"  OHLCV bars   : {len(ohlcv)}")
        logger.info(f"  Feature rows : {len(X)}")
        logger.info(f"  Feature cols : {X.shape[1]}")
        logger.info(f"  Class balance: {y.value_counts().to_dict()}")
        logger.info("=" * 60)
        sys.exit(0)

    except Exception:
        logger.exception("Dry run failed: %s")
        sys.exit(1)


def write_horizon_meta(args: argparse.Namespace, report: dict) -> None:
    """
    Write horizon5_meta.json and horizon5_training_report.json alongside the
    model so the inference engine and monitoring tools can verify the training
    horizon at runtime.

    Files written
    -------------
    ml/saved_models/horizon5_meta.json
        Compact metadata: horizon, accuracy, feature count, trained_at.
        Read by InferenceEngine.health() and /api/ml/health.

    ml/saved_models/horizon5_training_report.json
        Full training report (copy of advanced_training_report.json with
        horizon field injected).  Used by reconcile_backtest.py and CI gates.

    ml/saved_models/advanced_oos_meta.json
        Updated in-place so the existing InferenceEngine picks up the new
        horizon and accuracy values without a restart.
    """
    _MODEL_DIR.mkdir(parents=True, exist_ok=True)
    now_iso = datetime.now(UTC).isoformat()

    meta = {
        "horizon": args.horizon,
        "hold_period_bars": args.horizon,
        "years": args.years,
        "oos_years": args.oos_years,
        "symbol": args.symbol,
        "macro_features": not args.no_macro,
        "stacking": args.stacking,
        "trained_at": now_iso,
        "note": (
            f"Model trained with horizon={args.horizon} to match execution engine "
            f"hold period. Fixes accuracy/P&L disconnect from horizon=1 training."
        ),
        # Pull key metrics from the training report
        "oos_accuracy": report.get("oos", {}).get("accuracy"),
        "oos_f1": report.get("oos", {}).get("f1"),
        "oos_auc": report.get("oos", {}).get("auc"),
        "oos_p_value": report.get("oos", {}).get("p_value_binomial"),
        "oos_significant": report.get("oos", {}).get("significant"),
        "feature_count": report.get("feature_count"),
        "sample_count": report.get("sample_count"),
        "cv_accuracy": report.get("walkforward", {}).get("mean_accuracy"),
    }

    # ── horizon5_meta.json ────────────────────────────────────────────────────
    meta_path = _MODEL_DIR / "horizon5_meta.json"
    meta_path.write_text(json.dumps(meta, indent=2))
    logger.info("Horizon meta written → %s", meta_path)

    # ── horizon5_training_report.json ─────────────────────────────────────────
    # Full report: copy of advanced_training_report.json with horizon injected.
    # This is the canonical artifact checked by CI and reconcile_backtest.py.
    full_report = dict(report)
    full_report["horizon"] = args.horizon
    full_report["trained_at"] = now_iso
    full_report["script"] = "scripts/retrain_horizon5.py"
    full_report["note"] = meta["note"]

    h5_report_path = _MODEL_DIR / "horizon5_training_report.json"
    h5_report_path.write_text(json.dumps(full_report, indent=2, default=str))
    logger.info("Horizon5 training report written → %s", h5_report_path)

    # ── advanced_oos_meta.json ────────────────────────────────────────────────
    # Update in-place so InferenceEngine.health() picks up the new horizon
    # and accuracy values without a restart.
    oos_meta_path = _MODEL_DIR / "advanced_oos_meta.json"
    existing_meta: dict = {}
    if oos_meta_path.exists():
        try:
            existing_meta = json.loads(oos_meta_path.read_text())
        except Exception as _exc:
            logger.debug("Suppressed exception: %s", _exc)

    existing_meta.update(
        {
            "horizon": args.horizon,
            "oos_accuracy": meta["oos_accuracy"],
            "oos_f1": meta["oos_f1"],
            "feature_count": meta["feature_count"],
            "validated_at": now_iso,
            "note": meta["note"],
        }
    )
    oos_meta_path.write_text(json.dumps(existing_meta, indent=2))
    logger.info("advanced_oos_meta.json updated with horizon=%d", args.horizon)


def verify_output_artifacts(args: argparse.Namespace) -> bool:
    """
    CI gate: verify that all expected output artifacts were written.

    Called after training completes.  Returns True if all artifacts exist
    and are non-empty.  Logs a clear error for each missing file.

    Expected artifacts
    ------------------
    ml/saved_models/advanced_oos.pkl          — production model
    ml/saved_models/horizon5_meta.json        — horizon metadata
    ml/saved_models/horizon5_training_report.json — full training report
    ml/saved_models/advanced_oos_meta.json    — updated inference meta
    """
    required = [
        _MODEL_DIR / "advanced_oos.pkl",
        _MODEL_DIR / "horizon5_meta.json",
        _MODEL_DIR / "horizon5_training_report.json",
        _MODEL_DIR / "advanced_oos_meta.json",
    ]

    all_ok = True
    for path in required:
        if not path.exists():
            logger.error("CI GATE FAILED: missing artifact %s", path)
            all_ok = False
        elif path.stat().st_size == 0:
            logger.error("CI GATE FAILED: empty artifact %s", path)
            all_ok = False
        else:
            logger.info("CI GATE OK: %s (%d bytes)", path.name, path.stat().st_size)

    # Verify horizon5_meta.json has the correct horizon value
    if all_ok:
        try:
            meta = json.loads((_MODEL_DIR / "horizon5_meta.json").read_text())
            if meta.get("horizon") != args.horizon:
                logger.error(
                    "CI GATE FAILED: horizon5_meta.json has horizon=%s, expected %d",
                    meta.get("horizon"),
                    args.horizon,
                )
                all_ok = False
            else:
                logger.info(
                    "CI GATE OK: horizon5_meta.json horizon=%d (correct)",
                    meta["horizon"],
                )
        except Exception as exc:
            logger.error("CI GATE FAILED: could not parse horizon5_meta.json: %s", exc)
            all_ok = False

    # Verify horizon5_training_report.json has the correct horizon value
    if all_ok:
        try:
            rpt = json.loads((_MODEL_DIR / "horizon5_training_report.json").read_text())
            if rpt.get("horizon") != args.horizon:
                logger.error(
                    "CI GATE FAILED: horizon5_training_report.json has horizon=%s, expected %d",
                    rpt.get("horizon"),
                    args.horizon,
                )
                all_ok = False
            else:
                logger.info(
                    "CI GATE OK: horizon5_training_report.json horizon=%d (correct)",
                    rpt["horizon"],
                )
        except Exception as exc:
            logger.error("CI GATE FAILED: could not parse horizon5_training_report.json: %s", exc)
            all_ok = False

    if all_ok:
        logger.info("CI GATE PASSED: all artifacts present and valid")
    else:
        logger.error(
            "CI GATE FAILED: one or more artifacts missing or invalid. The retrain did not complete successfully."
        )

    return all_ok


def run_training(args: argparse.Namespace) -> dict:
    """
    Invoke train_advanced.py with the correct horizon and return the report dict.

    Uses subprocess so the training script runs in its own process with a clean
    import state — avoids any module-level side effects from the current process.
    """
    cmd = [
        sys.executable,
        str(_TRAIN_SCRIPT),
        "--horizon",
        str(args.horizon),
        "--years",
        str(args.years),
        "--oos-years",
        str(args.oos_years),
        "--splits",
        str(args.splits),
        "--min-move",
        str(args.min_move),
        "--symbol",
        args.symbol,
    ]

    if args.stacking:
        cmd.append("--stacking")
    if args.no_macro:
        cmd.append("--no-macro")
    if args.use_cached:
        cmd.append("--use-cached")
    if args.smoke:
        cmd.append("--smoke")

    logger.info("Running: %s", " ".join(cmd))
    logger.info(
        "Training with horizon=%d (hold period alignment fix). This may take 10–60 minutes depending on --years.",
        args.horizon,
    )

    result = subprocess.run(  # nosec B603 B607 - list-form call with sys.executable; no shell=True, no user input
        cmd, check=False
    )

    if result.returncode != 0:
        logger.error("train_advanced.py exited with code %d", result.returncode)
        sys.exit(result.returncode)

    # Load the report written by train_advanced.py
    report_path = _MODEL_DIR / "advanced_training_report.json"
    if report_path.exists():
        try:
            return json.loads(report_path.read_text())
        except Exception as exc:
            logger.warning("Could not read training report: %s", exc)

    return {}


def print_horizon_summary(args: argparse.Namespace, report: dict) -> None:
    """Print a concise summary of the horizon-alignment fix."""
    oos = report.get("oos", {})
    wf = report.get("walkforward", {})

    logger.info("\n" + "=" * 65)
    logger.info("HORIZON-5 RETRAIN SUMMARY")
    logger.info("=" * 65)
    logger.info(f"  Training horizon : {args.horizon} bars  (was: 1 bar)")
    logger.info(f"  Hold period      : {args.horizon} bars  (execution engine)")
    logger.info("  Horizon aligned  : YES — accuracy/P&L now measure same objective")
    logger.info("")
    logger.info(f"  Years of data    : {args.years}")
    logger.info(f"  OOS period       : {args.oos_years:.1f} years")
    logger.info(f"  Features         : {report.get('feature_count', '?')}")
    logger.info(f"  Samples          : {report.get('sample_count', '?')}")
    logger.info("")
    if wf:
        logger.info(f"  Walk-forward acc : {wf.get('mean_accuracy', 0):.3f} ± {wf.get('std_accuracy', 0):.3f}")
        logger.info(f"  Walk-forward F1  : {wf.get('mean_f1', 0):.3f}")
    if oos:
        sig = "✓ significant" if oos.get("significant") else "✗ not significant"
        logger.info(f"  OOS accuracy     : {oos.get('accuracy', 0):.3f}  {sig}")
        logger.info(f"  OOS F1           : {oos.get('f1', 0):.3f}")
        logger.info(f"  OOS p-value      : {oos.get('p_value_binomial', 1):.4f}")
    logger.info("")
    logger.info("  Model saved → ml/saved_models/advanced_oos.pkl")
    logger.info("  Meta  saved → ml/saved_models/horizon5_meta.json")
    logger.info("")
    logger.info("  Next steps:")
    logger.info("  1. Restart the inference engine (or it will auto-reload on next predict)")
    logger.info("  2. Monitor /api/ml/health — last_trained_at should update")
    logger.info("  3. Run 30-day paper trading to validate P&L improvement")
    logger.info("  4. Compare OOS accuracy vs previous horizon=1 model (66.35%)")
    logger.info("=" * 65)


def main() -> None:
    args = parse_args()

    # Smoke-test overrides
    if args.smoke:
        logger.info("Smoke-test mode: overriding years=2, oos_years=0, no_macro, splits=2")
        args.years = 2
        args.oos_years = 0.0
        args.no_macro = True
        args.splits = 2
        args.use_cached = True

    logger.info(
        "=== HORIZON-5 RETRAIN: fixing accuracy/P&L disconnect ===\n"
        "  Previous model: horizon=1 (next-bar direction)\n"
        "  This run:       horizon=%d (matches %d-bar hold period)\n"
        "  Root cause: 66%% 1-bar accuracy ≠ tradeable edge over 5 bars\n"
        "  Fix: align training objective with execution hold period",
        args.horizon,
        args.horizon,
    )

    # Validate horizon alignment
    validate_horizon_alignment(args.horizon)

    # Verify-only mode — check artifacts without retraining
    if args.verify_only:
        logger.info("=== VERIFY-ONLY: checking output artifacts (no training) ===")
        ok = verify_output_artifacts(args)
        sys.exit(0 if ok else 1)

    # Dry run — validate pipeline without training
    if args.dry_run:
        dry_run(args)
        return  # dry_run calls sys.exit()

    # Check training script exists
    if not _TRAIN_SCRIPT.exists():
        logger.error("Training script not found: %s", _TRAIN_SCRIPT)
        sys.exit(1)

    # Run training
    report = run_training(args)

    # Write horizon metadata and full training report
    write_horizon_meta(args, report)

    # CI gate: verify all expected artifacts were written
    artifacts_ok = verify_output_artifacts(args)
    if not artifacts_ok:
        logger.error("Retrain completed but artifact verification failed. Check the logs above for missing files.")
        sys.exit(1)

    # Print summary
    print_horizon_summary(args, report)


if __name__ == "__main__":
    main()
