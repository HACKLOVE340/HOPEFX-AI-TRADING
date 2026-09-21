# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
ml/model_paths.py
=================
Where model artifacts live. One answer, for readers and writers alike.

There used to be five answers. Three writers each resolved ``ML_MODEL_DIR``
themselves, with two different defaults (``ml/saved_models`` twice,
``ml/models`` once); ``.env.example`` documented a third (``models``); the Helm
chart sets a fourth in production (``/app/data/models``). Both readers —
``ml/inference_engine.py`` and ``ml/__init__.py`` — ignored the variable
entirely and hardcoded ``Path(__file__).parent / "saved_models"``.

The consequence was not untidiness. In production, Helm points every trainer at
``/app/data/models`` while inference loads the packaged ``ml/saved_models``, so
retraining has never changed what the model serves: it writes files nothing
reads, and the container keeps serving the artifacts baked in at build time.
``ml/hourly_trainer.py``'s ``ml/models`` default was worse — no reader consults
that path under any configuration at all.

Readers search rather than switch
---------------------------------
``find_model_file`` prefers ``ML_MODEL_DIR`` and falls back to the packaged
directory. Switching outright would be the more obviously "correct" refactor
and the more dangerous one: a pod whose configured directory is empty — first
boot before any retrain, a volume that failed to mount — would find no model at
all. On a system that sizes and places real trades, a configuration mistake
must not become an outage or a silent degradation. Searching means fresh
artifacts win when they exist and behaviour is unchanged when they do not, with
a warning naming the directory that came up empty.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)

_ENV_VAR = "ML_MODEL_DIR"


def packaged_model_dir() -> Path:
    """The ``ml/saved_models`` directory that ships with the code.

    These artifacts are committed deliberately and checksum-verified in CI (see
    CLAUDE.md), so this is the floor every deployment can rely on.
    """
    return Path(__file__).parent / "saved_models"


def configured_model_dir() -> Path | None:
    """The directory ``ML_MODEL_DIR`` names, or None when it is unset.

    A blank or whitespace-only value counts as unset: ``ML_MODEL_DIR=`` in an
    env file would otherwise resolve to the process working directory, which
    varies with how the service was started.
    """
    raw = os.getenv(_ENV_VAR, "")
    raw = raw.strip() if isinstance(raw, str) else ""
    return Path(raw) if raw else None


def model_dir() -> Path:
    """Where models are written, and the first place they are looked for."""
    return configured_model_dir() or packaged_model_dir()


def find_model_file(name: str) -> Path | None:
    """Locate artifact *name*, preferring ``ML_MODEL_DIR``.

    Returns None when neither directory holds it, so callers keep whatever
    fail-closed behaviour they already had for a missing model rather than
    receiving a path that does not exist.
    """
    if not name:
        return None

    configured = configured_model_dir()
    if configured is not None:
        candidate = configured / name
        if candidate.exists():
            return candidate

    fallback = packaged_model_dir() / name
    if fallback.exists():
        if configured is not None:
            # The signal that a deployment is misconfigured. Falling back
            # silently is how "retraining does nothing" went unnoticed.
            logger.warning(
                "%s is set to %s but %r is not there; falling back to the packaged %s. "
                "Retrained artifacts in the configured directory are not being served.",
                _ENV_VAR,
                configured,
                name,
                fallback.parent,
            )
        return fallback

    return None
