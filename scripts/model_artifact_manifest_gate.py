#!/usr/bin/env python3
# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""A model artefact may not change without its recorded checksum changing with it.

`ml/saved_models/model_checksums.json` is not documentation. `ml/__init__.py`
::_verify_checksum reads it on every model load and, in production, refuses the
load when the bytes do not match — so an artefact whose recorded hash has gone
stale is an artefact that does not load.

That is exactly what happened, and how (MASTER_OUTSTANDING §A8). The manifest has
one commit in its whole history. `feature_scaler.pkl` and
`stacking_ensemble.pkl` have three each, two of them afterwards. One of those two
is `05efdbab` — *"fix(mobile): register must not issue tokens when it cannot
create the user"* — whose diff carries both model binaries, 710 changed lines of
`feature_stats.json` and a newly created `feature_importances.json`, none of it
connected to mobile authentication. The test suite had leaked them into the
working tree and they were committed with whatever else was in flight.

The leak itself is fixed in `tests/unit/test_ml_training_pipeline.py`, which now
snapshots the whole directory instead of a hand-typed list of six names. This
gate is the second half: it makes the *class* of accident impossible to commit,
whatever leaks it in.

## What it refuses, and what it deliberately does not

It compares **staged** bytes against the manifest, and only for artefacts this
commit actually touches. So:

* changing an artefact and not the manifest — **refused**;
* changing an artefact and the manifest together — allowed, which is the
  intended workflow;
* an artefact already mismatching before this commit — **allowed**, because
  nothing here changed it.

That last exemption is deliberate. Two artefacts mismatch today, and whether to
regenerate the manifest, gate on it, or investigate is an owner decision
(§A8). A gate that blocked every commit until that decision was made would be
this repository deciding it by attrition.

Usage:
    python scripts/model_artifact_manifest_gate.py           # pre-commit
    python scripts/model_artifact_manifest_gate.py --all     # audit the tree
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path


def _repo_root() -> Path:
    """The repository this gate is being run against, not the one it lives in.

    Derived from git rather than from ``__file__``. pre-commit always invokes it
    from the repository root so the two agree in practice — but resolving it
    from the script's own path made the gate impossible to exercise against a
    throwaway repository, and a gate that cannot be tested in isolation cannot
    be shown to fail. Falls back to the script's parent when git is unavailable.
    """
    out = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        capture_output=True,
        text=True,
        check=False,
    ).stdout.strip()
    return Path(out) if out else Path(__file__).resolve().parents[1]


ROOT = _repo_root()
ARTEFACT_DIR = Path("ml/saved_models")
MANIFEST = ARTEFACT_DIR / "model_checksums.json"

#: Extensions the loader actually verifies. `ml/__init__.py::_try_load` gates a
#: `joblib.load` / `pickle.load`, and the manifest correspondingly lists only
#: `.pkl`, `.pt` and `.zip`. The ten `.json` files beside them are metadata and
#: training reports that nothing checksums.
#:
#: Scoping matters more than it looks. The first version of this gate treated
#: every file in the directory as an artefact and refused a staged
#: `advanced_oos_meta.json` for "not being listed" — a file the manifest is not
#: supposed to list. A gate that refuses correct commits is one people switch
#: off, and then it protects nothing at all.
_ARTEFACT_SUFFIXES = {".pkl", ".pt", ".zip", ".joblib", ".onnx", ".h5", ".safetensors"}


def _is_artefact(path: Path) -> bool:
    return path.suffix in _ARTEFACT_SUFFIXES


def _git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, check=False).stdout


def _staged_paths() -> list[Path]:
    out = _git("diff", "--cached", "--name-only", "--diff-filter=ACMR")
    return [Path(line) for line in out.splitlines() if line.strip()]


def _staged_bytes(path: Path) -> bytes | None:
    """The content this commit would record, which is not necessarily on disk."""
    r = subprocess.run(
        ["git", "show", f":{path.as_posix()}"],
        cwd=ROOT,
        capture_output=True,
        check=False,
    )
    return r.stdout if r.returncode == 0 else None


def _manifest_from(raw: bytes | None) -> dict[str, str]:
    if not raw:
        return {}
    try:
        loaded = json.loads(raw)
    except (ValueError, UnicodeDecodeError):
        return {}
    return loaded if isinstance(loaded, dict) else {}


def check_staged() -> int:
    staged = _staged_paths()
    artefacts = [p for p in staged if p.parent == ARTEFACT_DIR and _is_artefact(p)]
    if not artefacts:
        return 0

    manifest_staged = MANIFEST in staged
    raw = (
        _staged_bytes(MANIFEST)
        if manifest_staged
        else ((ROOT / MANIFEST).read_bytes() if (ROOT / MANIFEST).exists() else None)
    )
    recorded = _manifest_from(raw)

    problems: list[str] = []
    for path in artefacts:
        content = _staged_bytes(path)
        if content is None:
            continue
        digest = hashlib.sha256(content).hexdigest()
        want = recorded.get(path.name)
        if want is None:
            problems.append(
                f"  {path.name}: staged, and not listed in {MANIFEST.name}. "
                "An artefact the baseline does not mention is one _verify_checksum "
                "refuses to load in production."
            )
        elif want != digest:
            problems.append(f"  {path.name}: staged bytes are sha256 {digest[:16]}…, the manifest records {want[:16]}…")

    if not problems:
        print(f"model artefacts: {len(artefacts)} staged, all match {MANIFEST.name}")
        return 0

    print(f"REFUSED — {len(problems)} staged model artefact(s) disagree with {MANIFEST}:")
    print("\n".join(problems))
    print(
        "\nThe manifest gates the load: ml/__init__.py::_verify_checksum reads it on "
        "every model load and refuses in production when the bytes do not match, so "
        "committing this leaves an artefact that does not load.\n"
        "\nIf you meant to change these artefacts, regenerate the manifest and stage it "
        "in the same commit. If you did NOT — and a test leaking them into the working "
        "tree is how this happened before (§A8) — unstage them:\n"
        f"    git restore --staged --worktree {ARTEFACT_DIR}/"
    )
    return 1


def check_all() -> int:
    """Audit the committed tree. Reports; never used as the commit gate."""
    manifest_path = ROOT / MANIFEST
    if not manifest_path.exists():
        print(f"{MANIFEST} does not exist")
        return 1
    recorded = _manifest_from(manifest_path.read_bytes())
    mismatch, absent = [], []
    for name, want in sorted(recorded.items()):
        f = ROOT / ARTEFACT_DIR / name
        if not f.exists():
            absent.append(name)
        elif hashlib.sha256(f.read_bytes()).hexdigest() != want:
            mismatch.append(name)
    print(f"{len(recorded)} recorded · {len(mismatch)} mismatch · {len(absent)} listed but absent")
    for n in mismatch:
        print(f"  MISMATCH {n}")
    for n in absent:
        print(f"  ABSENT   {n}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--all", action="store_true", help="audit the committed tree")
    ap.add_argument("filenames", nargs="*", help="ignored; pre-commit passes these")
    args = ap.parse_args()
    return check_all() if args.all else check_staged()


if __name__ == "__main__":
    sys.exit(main())
