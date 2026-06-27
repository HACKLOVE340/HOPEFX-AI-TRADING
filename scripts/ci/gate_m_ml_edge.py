#!/usr/bin/env python3
# HOPEFX-AI-TRADING — Gate M: ML edge regression guard.
#
# Runs ml/ab_baseline.py on a pinned dataset and fails if the ML model stops
# beating the rule baseline on the leakage-safe OOS split. This catches silent
# regressions in the ML edge (bad feature changes, label leakage, model
# degradation) that unit tests cannot see.
#
# Thresholds (env-overridable):
#   AB_MIN_LIFT     default 0.0   — ML directional accuracy must be >= baseline
#                                   (observed lift is ~+0.03 on XAUUSD_40Y, so a
#                                   0.0 floor leaves ~3pp of headroom — not flaky).
#   AB_MIN_ML_ACC   default 0.52  — ML accuracy sanity floor (must beat a coin).
#   AB_CSV          default data/XAUUSD_40Y.csv
#   AB_HORIZON      default 5
#   AB_OOS_YEARS    default 3
#
# The A/B trains an XGBoost with a fixed random_state on a committed CSV, so the
# result is deterministic. If the dataset or ML deps are unavailable the gate
# SKIPS (exit 0) rather than producing a flaky failure.
#
# Exits 0 on pass/skip, 1 when the ML edge has regressed below threshold.
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
REPORT_PATH = REPO_ROOT / "ml" / "saved_models" / "ab_baseline_report.json"


def _skip(msg: str) -> int:
    print(f"Gate M SKIPPED — {msg}")
    return 0


def main() -> int:
    csv = os.getenv("AB_CSV", "data/XAUUSD_40Y.csv")
    horizon = os.getenv("AB_HORIZON", "5")
    oos_years = os.getenv("AB_OOS_YEARS", "3")
    min_lift = float(os.getenv("AB_MIN_LIFT", "0.0"))
    min_ml_acc = float(os.getenv("AB_MIN_ML_ACC", "0.52"))

    csv_path = REPO_ROOT / csv
    if not csv_path.exists():
        return _skip(f"dataset not found: {csv}")

    try:
        import xgboost  # noqa: F401
        import sklearn  # noqa: F401
    except ImportError as exc:
        return _skip(f"ML deps unavailable ({exc})")

    print(f"Gate M — running A/B: csv={csv} horizon={horizon} oos_years={oos_years}")
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "ml.ab_baseline",
            "--csv",
            str(csv_path),
            "--horizon",
            horizon,
            "--oos-years",
            oos_years,
        ],
        cwd=str(REPO_ROOT),
        check=False,
    )
    if result.returncode != 0:
        print(f"Gate M FAILED — ml.ab_baseline exited {result.returncode}")
        return 1

    if not REPORT_PATH.exists():
        print(f"Gate M FAILED — report not produced at {REPORT_PATH}")
        return 1

    report = json.loads(REPORT_PATH.read_text())
    lift = float(report.get("ml_accuracy_lift", -1.0))
    ml_acc = float(report.get("ml", {}).get("accuracy", 0.0))
    base_acc = float(report.get("baseline", {}).get("accuracy", 0.0))

    print(
        f"Gate M — baseline_acc={base_acc:.3f} ml_acc={ml_acc:.3f} "
        f"lift={lift:+.3f} (min_lift={min_lift:+.3f}, min_ml_acc={min_ml_acc:.3f})"
    )

    failures = []
    if lift < min_lift:
        failures.append(f"ML lift {lift:+.3f} < required {min_lift:+.3f} — the ML no longer beats the rule baseline")
    if ml_acc < min_ml_acc:
        failures.append(f"ML accuracy {ml_acc:.3f} < floor {min_ml_acc:.3f}")

    if failures:
        print("Gate M FAILED — ML edge regression:")
        for f in failures:
            print(f"  • {f}")
        print("See docs/AB_ML_VS_BASELINE.md. Investigate features/labels/model before merging.")
        return 1

    print("Gate M PASSED — ML still beats the rule baseline on the leakage-safe OOS split.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
