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


BASELINE = REPO / "docs" / "MODEL_PROVENANCE_DEBT.json"


def check() -> int:
    """The ratchet: neither list may grow, and a cleared entry must leave it.

    Two things this deliberately does NOT block on.

    **The two MISMATCH artifacts.** `feature_scaler.pkl` and
    `stacking_ensemble.pkl` do not match their recorded hashes, and because
    `ml/__init__.py::_verify_checksum` is fail-closed in production, they do not
    load there. Whether to regenerate the manifest, restore the bytes, or
    investigate is an owner decision (MASTER_OUTSTANDING A8) — the root cause is
    known (a test leaked them into the working tree, ML-LEAK) but "which bytes
    are the real ones" is not something a gate can answer. Blocking every commit
    until it is answered would be this repository deciding it by attrition.

    **The twelve ungated loaders.** Adding a fail-closed integrity check to
    `ml/inference_engine.py` today would refuse a model that currently loads and
    halt live inference. That is a deployment decision with a blast radius, not a
    tidy-up. What this refuses is the THIRTEENTH — a new loader added with no
    check, or a new artifact committed with no baseline entry.

    Usage:
        python scripts/model_provenance_report.py            # the full report
        python scripts/model_provenance_report.py --check    # the gate
        python scripts/model_provenance_report.py --adopt    # bank progress
    """
    if not BASELINE.exists():
        print(f"model provenance: no baseline at {BASELINE.relative_to(REPO)} — run --adopt", file=sys.stderr)
        return 1
    recorded = json.loads(BASELINE.read_text(encoding="utf-8"))

    now_ungated = {r["module"] for r in survey_wiring() if not r["gates"]}
    now_unlisted = {r["path"] for r in survey_identity() if r["verdict"] == "NOT LISTED"}

    if not survey_wiring():
        # A scan that matched nothing agrees with every rule below (F255).
        print("model provenance: no loader modules found — the scan is broken, not ml/", file=sys.stderr)
        return 1

    failures: list[str] = []
    for label, now, was, advice in (
        (
            "ungated loader",
            now_ungated,
            set(recorded.get("ungated_loaders", ())),
            "route the load through ml.__init__._try_load, or add a registry-digest check — "
            "a bare joblib.load gates arbitrary code execution, not merely a wrong prediction",
        ),
        (
            "unlisted artifact",
            now_unlisted,
            set(recorded.get("unlisted_artifacts", ())),
            "record it in the baseline its directory uses — an artifact no baseline mentions "
            "is one _verify_checksum refuses to load in production",
        ),
    ):
        for added in sorted(now - was):
            failures.append(f"NEW {label}: {added}\n      {advice}")
        for cleared in sorted(was - now):
            if (REPO / cleared).exists() or label == "ungated loader":
                failures.append(
                    f"{label} {cleared} is clean now and must leave "
                    f"{BASELINE.relative_to(REPO)} — an entry that no longer describes "
                    f"anything is how a ratchet quietly stops being one"
                )

    print(
        f"model provenance: {len(now_ungated)} ungated loader(s), {len(now_unlisted)} unlisted "
        f"artifact(s) (baseline {len(recorded.get('ungated_loaders', ()))} / "
        f"{len(recorded.get('unlisted_artifacts', ()))})"
    )
    if failures:
        print(f"\nmodel provenance: {len(failures)} regression(s):", file=sys.stderr)
        for f in failures:
            print(f"  {f}", file=sys.stderr)
        return 1
    return 0


def adopt() -> int:
    recorded = json.loads(BASELINE.read_text(encoding="utf-8")) if BASELINE.exists() else {}
    recorded["ungated_loaders"] = sorted(r["module"] for r in survey_wiring() if not r["gates"])
    recorded["unlisted_artifacts"] = sorted(r["path"] for r in survey_identity() if r["verdict"] == "NOT LISTED")
    BASELINE.write_text(json.dumps(recorded, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    print(
        f"model provenance: adopted {len(recorded['ungated_loaders'])} ungated loader(s), "
        f"{len(recorded['unlisted_artifacts'])} unlisted artifact(s)"
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="emit the measurement as JSON")
    parser.add_argument("--check", action="store_true", help="the gate: neither debt list may grow")
    parser.add_argument("--adopt", action="store_true", help="write today's lists as the baseline")
    parser.add_argument("files", nargs="*", help=argparse.SUPPRESS)
    args = parser.parse_args()

    if args.check:
        return check()
    if args.adopt:
        return adopt()

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
