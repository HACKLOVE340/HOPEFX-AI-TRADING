#!/usr/bin/env python3
# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# AGPL-3.0 — Share all modifications
"""
scripts/resave_models.py
========================
Re-saves all .pkl model files using joblib with compress=3 so they load
correctly across Python 3.10 / 3.11 / 3.12 without pickle protocol errors.

Run this INSIDE the Docker container (Python 3.10) after any Python upgrade:

    docker compose run --rm app python scripts/resave_models.py

What it does
------------
1. Loads each .pkl in ml/saved_models/ using joblib.
2. Re-saves it in-place with joblib (compress=3, protocol=4).
3. Recomputes and updates ml/saved_models/model_checksums.json.

If a file cannot be loaded (e.g. already corrupt), it is skipped with a
warning — the original file is left untouched.
"""

from __future__ import annotations

import hashlib
import json
import logging
import sys
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(message)s")
log = logging.getLogger(__name__)

MODEL_DIR = Path(__file__).parent.parent / "ml" / "saved_models"
CHECKSUM_FILE = MODEL_DIR / "model_checksums.json"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def resave_all() -> int:
    try:
        import joblib
    except ImportError:
        log.error("joblib not installed — run: pip install joblib")
        return 1

    pkls = sorted(MODEL_DIR.glob("*.pkl"))
    if not pkls:
        log.warning("No .pkl files found in %s", MODEL_DIR)
        return 0

    log.info("Python %s | joblib %s", sys.version.split()[0], joblib.__version__)
    log.info("Found %d model files in %s", len(pkls), MODEL_DIR)

    checksums: dict[str, str] = {}
    errors = 0

    for pkl in pkls:
        log.info("Processing %s ...", pkl.name)
        try:
            model = joblib.load(pkl)  # nosec B301 - pkl iterates ml/saved_models directory
        except Exception as exc:
            log.warning("  SKIP — cannot load %s: %s", pkl.name, exc)
            errors += 1
            continue

        try:
            joblib.dump(model, pkl, compress=3, protocol=4)
            digest = sha256(pkl)
            checksums[pkl.name] = digest
            log.info("  OK — re-saved  sha256=%s", digest[:16] + "...")
        except Exception as exc:
            log.error("  FAIL — could not re-save %s: %s", pkl.name, exc)
            errors += 1

    # Update checksum registry
    try:
        CHECKSUM_FILE.write_text(json.dumps(checksums, indent=2))
        log.info("Checksums updated → %s (%d entries)", CHECKSUM_FILE, len(checksums))
    except Exception as exc:
        log.warning("Could not write checksums: %s", exc)

    if errors:
        log.warning("%d file(s) could not be processed — retrain required.", errors)
        log.warning("  docker compose run --rm app python ml/train_advanced.py --years 50 --oos-years 3")
    else:
        log.info("All models re-saved successfully. Restart the app to reload.")

    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(resave_all())
