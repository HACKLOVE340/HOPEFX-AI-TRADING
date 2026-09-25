# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
ml/feature_set.py
=================
The version of the feature DEFINITIONS, and the rule that stops a model being
fed features whose meaning changed after it was trained.

Why this exists (A0 fix #5, docs/audit/2026-09-24-a0-no-edge-investigation.md)
-----------------------------------------------------------------------------
Feature names are the train/serve contract: the live scorer aligns the frame it
builds to the model's ``feature_names_in_``. A name says nothing about what the
column MEANS, so a fix that changes a definition while keeping the name is
invisible to that alignment, and a fix that removes a name was worse: the
scorer zero-filled any missing column and only logged. After fix #5 the
committed model (``xgb_horizon5_v3``) would have been scored with
``inst_poc = 0`` (a gold price of zero) and with ``ri_vol_adj_mom`` carrying
values it had only ever seen as 0.0 — and nothing would have refused.

The version is carried by the ARTIFACT (an attribute on the pickled estimator,
set by training), not by the registry, so it is bound to the bytes it
describes. An artifact without it predates versioning and is feature set 1.

:func:`assert_feature_set_compatible` refuses an artifact that consumes a
feature that was removed or redefined after the feature set it was built on.
An old artifact that consumes none of them is unaffected and is allowed.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

#: The version the builders in ml/advanced_features.py and
#: ml/features_extended.py currently produce. Bump it, and add an entry to
#: FEATURE_SET_CHANGES, whenever a feature's DEFINITION changes or a feature is
#: removed — not only when one is renamed.
FEATURE_SET_VERSION = 2

#: What an artifact carries no stamp for: everything trained before versioning.
LEGACY_FEATURE_SET_VERSION = 1

#: Attribute training sets on the saved estimator.
MODEL_ATTR = "hopefx_feature_set_version"

#: Per version, what changed relative to the version before it.
FEATURE_SET_CHANGES: dict[int, dict[str, frozenset[str]]] = {
    2: {
        # D4: raw price levels (|corr(close)| > 0.9), replaced by ATR distances.
        "removed": frozenset({"inst_poc", "inst_vah", "inst_val"}),
        # D3: constant 0.0 by construction (first three) or computed with
        # momentum's sign forced to 0 (ri_signal_alignment). Same names, new values.
        # Swing levels: a fractal swing was used from the bar it formed, 5 bars
        # before it could be confirmed (look-ahead); now from confirmation.
        "redefined": frozenset(
            {
                "ri_regime_mom",
                "ri_vol_adj_mom",
                "ri_trend_vol_confirm",
                "ri_signal_alignment",
                "dist_to_swing_high",
                "dist_to_swing_low",
                "near_swing_high",
                "near_swing_low",
                "breakout_high",
                "breakout_low",
            }
        ),
        "added": frozenset({"inst_poc_dist_atr", "inst_vah_dist_atr", "inst_val_dist_atr"}),
    },
}


class FeatureSetMismatchError(RuntimeError):
    """A model would be scored on features whose definitions it was not trained on."""


def model_feature_set_version(model: Any) -> int:
    """The feature set ``model`` was trained on; 1 when it carries no stamp."""
    for obj in (model, getattr(model, "steps", [[None, None]])[-1][1]):
        v = getattr(obj, MODEL_ATTR, None)
        if isinstance(v, int) and not isinstance(v, bool):
            return v
    return LEGACY_FEATURE_SET_VERSION


def stamp_feature_set_version(model: Any, version: int = FEATURE_SET_VERSION) -> Any:
    """Record on ``model`` the feature set it was trained on. Returns ``model``."""
    setattr(model, MODEL_ATTR, int(version))
    return model


def model_feature_names(model: Any) -> list[str] | None:
    """The column names ``model`` was fitted on, or ``None`` if it records none."""
    names = getattr(model, "feature_names_in_", None)
    if names is None and hasattr(model, "steps"):
        names = getattr(model.steps[0][1], "feature_names_in_", None)
    return None if names is None else [str(n) for n in names]


def changed_since(version: int) -> dict[str, frozenset[str]]:
    """Every feature removed or redefined in versions after ``version``."""
    removed: set[str] = set()
    redefined: set[str] = set()
    for v, change in FEATURE_SET_CHANGES.items():
        if v > version:
            removed |= change.get("removed", frozenset())
            redefined |= change.get("redefined", frozenset())
    return {"removed": frozenset(removed), "redefined": frozenset(redefined)}


def assert_feature_set_compatible(model: Any, expected: Iterable[str] | None = None) -> None:
    """Refuse ``model`` if scoring it on today's features would change their meaning.

    Raises :class:`FeatureSetMismatchError` when the model was built on a newer
    feature set than this code produces, or when it consumes any feature that
    was removed or redefined after the feature set it was built on. A model
    that records no feature names cannot be checked by name and is allowed only
    when it is stamped with the current version.
    """
    version = model_feature_set_version(model)
    if version > FEATURE_SET_VERSION:
        raise FeatureSetMismatchError(
            f"model was built on feature set {version}, newer than the feature set {FEATURE_SET_VERSION} "
            "this code produces — refusing to score it on older definitions"
        )
    if version == FEATURE_SET_VERSION:
        return

    names = list(expected) if expected is not None else model_feature_names(model)
    if names is None:
        raise FeatureSetMismatchError(
            f"model was built on feature set {version} and records no feature names, so it cannot be shown "
            f"to avoid the features changed in feature set {FEATURE_SET_VERSION} — refusing"
        )
    changed = changed_since(version)
    removed = sorted(set(names) & changed["removed"])
    redefined = sorted(set(names) & changed["redefined"])
    if removed or redefined:
        raise FeatureSetMismatchError(
            f"model was built on feature set {version}; this code produces feature set {FEATURE_SET_VERSION}. "
            f"It consumes removed features {removed} and redefined features {redefined}. Scoring it would feed "
            "it values it was never trained on (a removed column would be zero-filled). Retrain on the current "
            "feature set — see docs/audit/2026-09-24-a0-no-edge-investigation.md D3/D4."
        )
