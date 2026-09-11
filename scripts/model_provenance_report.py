#!/usr/bin/env python3
# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""What do we actually know about the model artifacts we ship?

The open-weight / open-source distinction is usually aimed outward, at somebody
else's model: weights alone are the finished product, not the recipe. Turned
inward it is a better question, because this repository *commits* its model
artifacts and then trades on them:

    Are our own models open-weight to us, or open-source to us?

An artifact is open-weight-to-us when we have the file and nothing that ties it
to the code, data and run that produced it. Then it cannot be reproduced, a
prediction cannot be explained, and — the part that bites first — nothing can
tell whether the file on disk is the file we think it is.

This script measures three things and asserts none of them:

1. **Identity.** Is every committed artifact listed in an integrity baseline,
   and does it still hash to what the baseline says?
2. **Reach.** Would `ml._verify_checksum` refuse a tampered file *in this
   directory*, or does the directory qualify for on-demand baselining and get a
   pass?
3. **Wiring.** Do the code paths that actually load these files reach *any*
   integrity check? There are two, they use different records, and one is
   fail-closed while the other is fail-open by design. A gate nothing calls is
   the defect shape this repository has shipped more than any other — and
   reporting the absence of one particular gate as "unguarded" is that same
   mistake pointed the other way, so this checks for both.

It prints the measurement. It does not repair anything, and in particular it
never recomputes a mismatched checksum: the recorded hash is the claim, the file
is the evidence, and quietly making them agree destroys the only signal that
they ever disagreed.

Usage:
    python scripts/model_provenance_report.py            # human-readable
    python scripts/model_provenance_report.py --json     # machine-readable
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parent.parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

#: Directories that hold committed model artifacts.
MODEL_DIRS: tuple[Path, ...] = (
    REPO / "ml" / "saved_models",
    REPO / "ml" / "saved_models" / "GCF",
    REPO / "ml" / "saved_models" / "XAU_USD",
    REPO / "ml" / "saved_models" / "rl",
    REPO / "ml" / "rl_models",
)

ARTIFACT_SUFFIXES = frozenset({".pkl", ".zip", ".pt", ".h5", ".joblib", ".onnx", ".safetensors"})

BASELINE_NAME = "model_checksums.json"

#: Loader calls that read a model artifact off disk. Each is checked for whether
#: the integrity gate is invoked anywhere near it.
LOADER_PATTERN = re.compile(
    r"\b(joblib\.load|pickle\.load|PPO\.load|torch\.load|xgb\.Booster|load_model)\s*\(",
)
#: Every integrity check this repository has, not just one of them. An earlier
#: version of this script looked only for `_verify_checksum` and would have
#: reported `ml/advanced_predictor.py` as unguarded — it has its own SHA-256
#: check against the model registry. Reporting the absence of one specific gate
#: as "no gate" is the same mistake this script exists to find.
GATES: dict[str, re.Pattern[str]] = {
    "ml._verify_checksum": re.compile(r"_verify_checksum|_try_load\b"),
    "registry digest": re.compile(r"_verify_integrity|sha256_file|model_registry"),
}


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _artifacts(directory: Path) -> list[Path]:
    if not directory.is_dir():
        return []
    return sorted(p for p in directory.iterdir() if p.suffix in ARTIFACT_SUFFIXES and p.is_file())


def survey_identity() -> list[dict[str, Any]]:
    """Every artifact, and whether the baseline in its own directory matches it."""
    rows: list[dict[str, Any]] = []
    for directory in MODEL_DIRS:
        artifacts = _artifacts(directory)
        if not artifacts:
            continue
        baseline_path = directory / BASELINE_NAME
        baseline: dict[str, str] = {}
        baseline_state = "absent"
        if baseline_path.exists():
            try:
                baseline = json.loads(baseline_path.read_text())
                baseline_state = "present"
            except Exception as exc:
                baseline_state = f"unreadable ({exc})"
        for artifact in artifacts:
            recorded = baseline.get(artifact.name)
            if recorded is None:
                verdict = "NOT LISTED"
            elif recorded == _sha256(artifact):
                verdict = "ok"
            else:
                verdict = "MISMATCH"
            rows.append(
                {
                    "path": str(artifact.relative_to(REPO)),
                    "directory": str(directory.relative_to(REPO)),
                    "baseline": baseline_state,
                    "verdict": verdict,
                    "size_kb": round(artifact.stat().st_size / 1024, 1),
                }
            )
        for name in baseline:
            if not (directory / name).exists():
                rows.append(
                    {
                        "path": str((directory / name).relative_to(REPO)),
                        "directory": str(directory.relative_to(REPO)),
                        "baseline": baseline_state,
                        "verdict": "LISTED BUT ABSENT",
                        "size_kb": None,
                    }
                )
    return rows


def survey_reach() -> list[dict[str, Any]]:
    """Would the gate refuse an unlisted file here, or baseline it and allow?

    `ml._bootstrap_allowed` permits on-demand baselining for any directory that
    is not the packaged one. That is deliberate — an operator's retrain job
    writes into `ML_MODEL_DIR` and no shipped baseline can exist for it — but it
    means a *committed* artifact in a subdirectory is outside the guarantee.
    """
    import ml

    rows = []
    for directory in MODEL_DIRS:
        if not _artifacts(directory):
            continue
        rows.append(
            {
                "directory": str(directory.relative_to(REPO)),
                "is_packaged_dir": directory.resolve() == ml._PACKAGED.resolve(),
                "self_baselines_in_production": ml._bootstrap_allowed(directory),
            }
        )
    return rows


def survey_wiring() -> list[dict[str, Any]]:
    """Which loader call sites sit in a module that never mentions the gate."""
    rows = []
    for source in sorted((REPO / "ml").rglob("*.py")):
        if "test" in source.name:
            continue
        try:
            text = source.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        calls = LOADER_PATTERN.findall(text)
        if not calls:
            continue
        found = [name for name, pattern in GATES.items() if pattern.search(text)]
        rows.append(
            {
                "module": str(source.relative_to(REPO)),
                "loader_calls": sorted(set(calls)),
                "gates": found,
            }
        )
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="emit the measurement as JSON")
    args = parser.parse_args()

    identity = survey_identity()
    reach = survey_reach()
    wiring = survey_wiring()

    if args.json:
        print(json.dumps({"identity": identity, "reach": reach, "wiring": wiring}, indent=2))
        return 0

    print("── Identity: does each artifact match its recorded hash? ──")
    for row in identity:
        print(f"  {row['verdict']:<18} {row['path']}")
    counts: dict[str, int] = {}
    for row in identity:
        counts[row["verdict"]] = counts.get(row["verdict"], 0) + 1
    print("  " + " · ".join(f"{k}: {v}" for k, v in sorted(counts.items())))

    print("\n── Reach: which directories the gate actually guarantees ──")
    print(f"  APP_ENV={os.getenv('APP_ENV', 'development')!r}")
    for row in reach:
        guaranteed = (
            "refuses an unlisted file" if not row["self_baselines_in_production"] else "SELF-BASELINES, then allows"
        )
        print(f"  {row['directory']:<32} {guaranteed}")

    print("\n── Wiring: which integrity check does each loader reach for? ──")
    for row in wiring:
        mark = " + ".join(row["gates"]) if row["gates"] else "NO INTEGRITY CHECK"
        print(f"  {row['module']:<34} {', '.join(row['loader_calls']):<28} {mark}")
    unguarded = [r["module"] for r in wiring if not r["gates"]]
    print(f"  {len(wiring) - len(unguarded)} of {len(wiring)} modules reach an integrity check")

    print("\nNothing here is repaired, and a mismatched checksum is never recomputed:")
    print("the recorded hash is the claim and the file is the evidence.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
