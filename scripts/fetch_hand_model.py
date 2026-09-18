#!/usr/bin/env python3
# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""Put the hand-landmark model and its WASM runtime on this origin.

    python scripts/fetch_hand_model.py
    python scripts/fetch_hand_model.py --check     # verify without downloading

§18's camera gestures need two things this repository does not carry in git: an
7.8 MB model and MediaPipe's WASM runtime. Both are fetched here at deploy time
and served from our own origin, because `hub/landmarks.ts::resolveModelUrl`
refuses a third-party model URL and `hub/handRuntime.ts` holds the same rule for
the WASM.

## Why fetched rather than committed

The model is 7.8 MB and the runtime tens more. `check-added-large-files` caps a
new file at 500 KB, and the cap is right: a git history carrying rebuilt binary
blobs is one nobody can clone quickly, and this is a vendor artifact with a
published checksum rather than something this repository authors.

## Why not simply pointed at the vendor's CDN

That is the documented way to construct a MediaPipe task, and it would have a
trading console fetch executable code from a third party on the operator's
behalf — telling that host whenever this desk opens its console, and putting a
runtime dependency nobody here controls in front of a feature. Fetched once, at
deploy time, into our own origin.

## Its absence is a state, not a failure

`landmarkStatus` reports `unconfigured` when no model is deployed, with a reason
that says pointer gestures still work. Not running this script degrades one
feature and breaks nothing, which is why it is a deploy step rather than a
build dependency.
"""

from __future__ import annotations

import argparse
import hashlib
import shutil
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PUBLIC = ROOT / "frontend" / "public"
MODEL_DEST = PUBLIC / "models" / "hand_landmarker.task"
WASM_DEST = PUBLIC / "vendor" / "tasks-vision" / "wasm"
WASM_SOURCE = ROOT / "frontend" / "node_modules" / "@mediapipe" / "tasks-vision" / "wasm"

MODEL_URL = (
    "https://storage.googleapis.com/mediapipe-models/hand_landmarker/hand_landmarker/float16/1/hand_landmarker.task"
)
#: sha256 of the float16 v1 model, measured on 2026-09-09. A vendor artifact
#: that changes under a stable URL is a supply-chain event, not a silent update.
MODEL_SHA256 = "fbc2a30080c3c557093b5ddfc334698132eb341044ccee322ccf8bcf3607cde1"  # pragma: allowlist secret


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def check() -> tuple[bool, list[str]]:
    """Report what is in place. Never claims more than it looked at."""
    problems: list[str] = []
    if not MODEL_DEST.exists():
        problems.append(f"model missing: {MODEL_DEST.relative_to(ROOT)}")
    else:
        found = _sha256(MODEL_DEST)
        if found != MODEL_SHA256:
            problems.append(f"model checksum differs: expected {MODEL_SHA256[:12]}…, found {found[:12]}…")
    if not (WASM_DEST / "vision_wasm_internal.wasm").exists():
        problems.append(f"wasm runtime missing: {WASM_DEST.relative_to(ROOT)}")
    return (not problems), problems


def fetch() -> int:
    MODEL_DEST.parent.mkdir(parents=True, exist_ok=True)
    if MODEL_DEST.exists() and _sha256(MODEL_DEST) == MODEL_SHA256:
        print(f"model     already present, checksum matches  {MODEL_DEST.relative_to(ROOT)}")
    else:
        print(f"model     fetching {MODEL_URL}")
        with urllib.request.urlopen(MODEL_URL, timeout=300) as response:  # nosec B310 — fixed https URL
            MODEL_DEST.write_bytes(response.read())
        found = _sha256(MODEL_DEST)
        if found != MODEL_SHA256:
            MODEL_DEST.unlink(missing_ok=True)
            print(
                f"error: checksum mismatch — expected {MODEL_SHA256}, got {found}. "
                "The download was discarded rather than deployed.",
                file=sys.stderr,
            )
            return 1
        print(f"model     wrote {MODEL_DEST.relative_to(ROOT)}  ({MODEL_DEST.stat().st_size} bytes)")

    if not WASM_SOURCE.exists():
        print(
            f"error: {WASM_SOURCE.relative_to(ROOT)} is missing — run `npm ci` in frontend/ first",
            file=sys.stderr,
        )
        return 1
    WASM_DEST.parent.mkdir(parents=True, exist_ok=True)
    if WASM_DEST.exists():
        shutil.rmtree(WASM_DEST)
    shutil.copytree(WASM_SOURCE, WASM_DEST)
    print(f"wasm      copied {WASM_SOURCE.relative_to(ROOT)} -> {WASM_DEST.relative_to(ROOT)}")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", action="store_true", help="verify what is deployed without downloading")
    args = ap.parse_args(argv)

    if args.check:
        ok, problems = check()
        for problem in problems:
            print(f"  {problem}")
        print("hand-landmark model: DEPLOYED" if ok else "hand-landmark model: NOT DEPLOYED")
        return 0 if ok else 1
    return fetch()


if __name__ == "__main__":
    raise SystemExit(main())
