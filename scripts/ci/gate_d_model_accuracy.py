#!/usr/bin/env python3
# HOPEFX-AI-TRADING — Gate D: ML model accuracy consistency.
#
# Delegates to ml/verify_model.py which checks:
#   • Saved model exists and can be loaded
#   • Out-of-sample Sharpe gate metadata is present
#   • Model was not trained with CI stubs (ci_mode=False)
#   • Basic accuracy metrics are within expected ranges
#
# Exits 0 when the model passes all checks, 1 on any failure.
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def main() -> int:
    env = os.environ.copy()
    env.setdefault("ENVIRONMENT", "testing")
    env.setdefault("ML_CI_MODE", "true")

    result = subprocess.run(
        [sys.executable, "-m", "ml.verify_model"],
        cwd=str(REPO_ROOT),
        env=env,
        capture_output=False,
        check=False,  # let output flow to stdout/stderr
    )

    if result.returncode != 0:
        print(f"\nGate D FAILED — ml.verify_model exited {result.returncode}")
        return result.returncode

    print("Gate D PASSED — ML model accuracy verification OK.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
