#!/usr/bin/env python3
# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
scripts/derive_feature_stats.py
===============================
Turn the drift guard on now, without waiting for a retrain.

``ml/train_advanced.py`` now writes ``ml/saved_models/feature_stats.json``, but
that only helps the *next* training run. Until then
``InferenceEngine.drift_guard_active()`` stays False and drift goes undetected
on the model that is serving today.

It does not have to. ``ml/saved_models/feature_scaler.pkl`` is the
``StandardScaler`` extracted from the trained pipeline in ``train_final_model``
— the same file ``ml/advanced_predictor.py`` loads to normalise live features.
A fitted ``StandardScaler`` *is* the training distribution:

    feature_names_in_  the feature names, in order
    mean_              the training mean of each
    var_               the training variance of each

which is exactly the ``{"feature": {"mean": ..., "std": ...}}`` the guard reads.
No retrain, no data, no guessing — the numbers are already in the repo.

One trap, and it is the reason this is a script rather than a one-liner.
``scale_`` is *not* the standard deviation for every column: sklearn's
``_handle_zeros_in_scale`` replaces a zero scale with ``1.0`` so division stays
safe. In the committed scaler, 23 of 193 features have zero training variance
and therefore carry ``scale_ == 1.0``. Copying ``scale_`` blindly would write
``std=1.0`` for a constant feature, and the guard would then measure a real
deviation against a fabricated spread. This derives std from ``var_`` and drops
the degenerate columns instead, matching ``train_advanced.write_feature_stats``.

Coverage, measured against the live feature builder: the scaler describes 193
features, the live builder emits 229, and all 193 are present in the live set.
The 36 it does not cover are the ``dl_*`` data-layer injections (microstructure,
macro, sentiment) added after this model was fitted; they are genuinely not
monitored, which ``InferenceEngine.drift_status()`` reports rather than hides.

Usage
-----
    python scripts/derive_feature_stats.py             # report only
    python scripts/derive_feature_stats.py --apply
    python scripts/derive_feature_stats.py --apply --force   # overwrite
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

MODEL_DIR = ROOT / "ml" / "saved_models"
DEFAULT_SCALER = MODEL_DIR / "feature_scaler.pkl"
DEFAULT_OUTPUT = MODEL_DIR / "feature_stats.json"

# Variance at or below this counts as constant.
_ZERO_VAR = 1e-12


def derive_from_scaler(scaler: Any) -> tuple[dict[str, dict[str, float]], list[str]]:
    """Build drift-guard stats from a fitted StandardScaler.

    Returns ``(stats, dropped)``. ``dropped`` names the columns omitted because
    their training variance is zero — see the module docstring for why writing
    them would be worse than leaving them out.
    """
    names = getattr(scaler, "feature_names_in_", None)
    means = getattr(scaler, "mean_", None)
    variances = getattr(scaler, "var_", None)

    if names is None or means is None or variances is None:
        raise ValueError(
            "the scaler is missing feature_names_in_/mean_/var_ — it is either unfitted "
            "or was fitted on a bare array, so the feature names are unrecoverable"
        )

    stats: dict[str, dict[str, float]] = {}
    dropped: list[str] = []

    for name, mean, var in zip(names, means, variances, strict=True):
        key = str(name)
        if not np.isfinite(mean) or not np.isfinite(var) or var <= _ZERO_VAR:
            dropped.append(key)
            continue
        stats[key] = {"mean": float(mean), "std": float(np.sqrt(var))}

    return stats, dropped


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--scaler", type=Path, default=DEFAULT_SCALER)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--apply", action="store_true", help="write the file (default: report only)")
    parser.add_argument(
        "--force",
        action="store_true",
        help="overwrite an existing feature_stats.json (refused by default: a file from a real "
        "training run has better provenance than one derived from the scaler)",
    )
    args = parser.parse_args(argv)

    if not args.scaler.exists():
        print(f"error: no scaler at {args.scaler}", file=sys.stderr)
        return 2

    import joblib

    scaler = joblib.load(args.scaler)
    try:
        stats, dropped = derive_from_scaler(scaler)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    total = len(stats) + len(dropped)
    print(f"Scaler: {args.scaler}")
    print(f"  {total} feature(s) described")
    print(f"  {len(stats)} written")
    if dropped:
        print(f"  {len(dropped)} dropped as zero-variance (they can only ever yield z=0):")
        print(f"    {', '.join(dropped[:12])}{' …' if len(dropped) > 12 else ''}")

    if not stats:
        print("error: nothing usable to write", file=sys.stderr)
        return 2

    if args.output.exists() and not args.force:
        print(
            f"\n{args.output.name} already exists. Refusing to overwrite — a file written by a real "
            "training run describes the model better than one derived from the scaler. "
            "Pass --force if you are sure.",
            file=sys.stderr,
        )
        return 3

    if not args.apply:
        print("\nDry run — nothing written. Re-run with --apply.")
        return 1

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with Path(args.output).open("w", encoding="utf-8") as f:
        json.dump(stats, f, indent=2, sort_keys=True)
    print(f"\nWritten → {args.output}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
