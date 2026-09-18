# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""`health()` must not report two contradictory answers to "how old is this model".

Measured against the committed artifact on 2026-09-14, the payload said:

    last_trained_at : 2026-06-26      (from advanced_oos_meta.json)
    model_age_days  : 166.75          (from registry.json, 2026-04-01)
    stale_model     : True

and `MlSafetyStrip.tsx` renders `last_trained_at` as "Trained: 26/06/2026". So an
operator saw a model trained twelve weeks ago flagged stale at twenty-four, with
nothing on the screen to say which number the gate used or why they differ.

The disagreement is real and predates this: the meta file's `validated_at` is
when the artifact was last validated, while the earliest registry version
carrying its sha256 is 2026-04-01 — the same bytes, re-registered. The mtime the
gate used to read (0.69 days) disagreed with BOTH, which is why nobody noticed.

Reconciling the meta file and the registry is an ML-side decision, not this
module's. What this module owes an operator is that the number it BLOCKS on is
visible and attributable. So `model_provenance_at` is reported alongside the age
it was computed from, additively — `last_trained_at` keeps its meaning and its
UI contract.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone

import pytest

import ml.inference_engine as ie


@pytest.fixture
def engine_with_provenance(tmp_path, monkeypatch):
    monkeypatch.setattr(ie, "_SAVED", tmp_path)
    monkeypatch.setattr(ie, "_MODEL_MAX_AGE_DAYS", 30.0)
    art = tmp_path / "advanced_oos.pkl"
    art.write_bytes(b"bytes")
    trained = datetime.now(timezone.utc) - timedelta(days=90)
    (tmp_path / "registry.json").write_text(
        json.dumps(
            {
                "versions": {
                    "v1": {
                        "sha256": hashlib.sha256(b"bytes").hexdigest(),
                        "trained_at": trained.isoformat(),
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    return ie.InferenceEngine(), trained


def test_health_states_the_timestamp_the_gate_actually_used(engine_with_provenance):
    engine, trained = engine_with_provenance
    health = engine.health()

    assert "model_provenance_at" in health, "health reports an age with nothing to say where it came from"
    assert health["model_provenance_at"] is not None
    reported = datetime.fromisoformat(health["model_provenance_at"])
    assert abs((reported - trained).total_seconds()) < 2, (
        f"health names {reported.isoformat()}, the gate used {trained.isoformat()}"
    )


def test_the_reported_age_and_the_reported_provenance_agree(engine_with_provenance):
    """The two numbers must be arithmetic on each other, not two guesses."""
    engine, _trained = engine_with_provenance
    health = engine.health()

    assert health["model_age_days"] is not None
    reported = datetime.fromisoformat(health["model_provenance_at"])
    implied = (datetime.now(timezone.utc) - reported).total_seconds() / 86_400.0
    assert health["model_age_days"] == pytest.approx(implied, abs=0.01), (
        f"age {health['model_age_days']} does not follow from {health['model_provenance_at']}"
    )


def test_unusable_provenance_is_reported_as_unknown_not_omitted(tmp_path, monkeypatch):
    """Stale with no age is the fail-closed case, and an operator needs to be
    told that the age is UNKNOWN rather than left to read a missing key as fine."""
    monkeypatch.setattr(ie, "_SAVED", tmp_path)
    monkeypatch.setattr(ie, "_MODEL_MAX_AGE_DAYS", 30.0)
    (tmp_path / "advanced_oos.pkl").write_bytes(b"orphan")  # no registry

    health = ie.InferenceEngine().health()
    assert health["stale_model"] is True
    assert health["model_age_days"] is None
    assert health["model_provenance_at"] is None
    assert health["model_provenance_reason"], "nothing says WHY the age is unknown"
