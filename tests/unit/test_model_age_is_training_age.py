# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""A model's age is when it was TRAINED, not when its file was last written.

`_check_model_staleness()` measured `model_path.stat().st_mtime`. Reproduced on
the audited revision against a disposable file:

    90-day-old artifact           -> stale=True   age=90.0
    same bytes, timestamp touched -> stale=False  age=0.0

No retraining occurred. Every ordinary operational act writes that timestamp —
`git checkout`, `docker build`, `cp -r`, `rsync` without `-t`, restoring a
backup, an editor saving nearby — so the gate that exists to stop the platform
trading on an out-of-date model was cleared by deploying the out-of-date model.
It fails in the unsafe direction and silently.

The replacement reads a timestamp bound to the artifact's SHA-256 in
`ml/saved_models/registry.json`, so the answer is a property of the BYTES:
copying, deploying or touching cannot change it, and the only thing that can is
actually training a new model and registering it.

Where an artifact's bytes appear under several registry versions, the EARLIEST
timestamp wins. Re-registering unchanged bytes under a new version is the touch
defect wearing a different hat, and the earliest date is also the conservative
one — it can only make a model look older, never younger.

Fail-closed is the whole point, so every way provenance can be unusable —
absent, malformed, not matching the bytes, or dated in the future — reports
STALE rather than fresh. `STALE_MODEL_BLOCK` (default true) then blocks the
trade, which is the correct answer to "I cannot tell you how old this model is".
"""

from __future__ import annotations

import json
import os
import time
from datetime import datetime, timedelta, timezone

import pytest

import ml.inference_engine as ie


BYTES = b"pretend-this-is-a-trained-model"


@pytest.fixture
def saved(tmp_path, monkeypatch):
    """A throwaway model directory with one artifact and a registry."""
    import hashlib

    monkeypatch.setattr(ie, "_SAVED", tmp_path)
    monkeypatch.setattr(ie, "_MODEL_MAX_AGE_DAYS", 30.0)
    art = tmp_path / "advanced_oos.pkl"
    art.write_bytes(BYTES)
    ie._model_sha256.cache_clear() if hasattr(ie._model_sha256, "cache_clear") else None
    return tmp_path, art, hashlib.sha256(BYTES).hexdigest()


def _registry(root, sha, *, trained: str | None = None, registered: str | None = None, extra=None):
    entry = {"file": "ml/saved_models/advanced_oos.pkl", "sha256": sha}
    if trained:
        entry["trained_at"] = trained
    if registered:
        entry["registered_at"] = registered
    versions = {"v1": entry}
    if extra:
        versions.update(extra)
    (root / "registry.json").write_text(json.dumps({"active_version": "v1", "versions": versions}), encoding="utf-8")


def _iso(days_ago: float) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days_ago)).isoformat()


def _engine():
    eng = ie.InferenceEngine.__new__(ie.InferenceEngine)
    eng._active_model_path = None
    eng._model_stale = False
    eng._model_age_days = None
    return eng


# ── The reported defect ───────────────────────────────────────────────────────


def test_touching_an_old_artifact_does_not_make_it_fresh(saved):
    """The reproduction, as a regression test."""
    root, art, sha = saved
    _registry(root, sha, trained=_iso(90))
    eng = _engine()

    assert eng._check_model_staleness() is True
    aged = eng._model_age_days

    now = time.time()
    os.utime(art, (now, now))
    assert art.read_bytes() == BYTES, "the repro is only valid if the bytes are unchanged"

    assert eng._check_model_staleness() is True, "touching the file retrained nothing"
    assert eng._model_age_days == pytest.approx(aged, abs=0.01)


def test_copying_an_old_artifact_does_not_make_it_fresh(saved, tmp_path):
    root, art, sha = saved
    _registry(root, sha, trained=_iso(90))
    copy = root / "copied.pkl"
    copy.write_bytes(art.read_bytes())  # a fresh mtime, identical bytes

    eng = _engine()
    eng._active_model_path = copy
    assert eng._check_model_staleness() is True


def test_a_genuinely_new_model_passes(saved):
    root, art, sha = saved
    _registry(root, sha, trained=_iso(2))
    eng = _engine()
    assert eng._check_model_staleness() is False
    assert eng._model_age_days == pytest.approx(2.0, abs=0.1)


# ── Fail-closed on unusable provenance ────────────────────────────────────────


def test_no_registry_at_all_is_stale(saved):
    eng = _engine()
    assert eng._check_model_staleness() is True


def test_malformed_registry_is_stale(saved):
    root, _art, _sha = saved
    (root / "registry.json").write_text("{not json", encoding="utf-8")
    eng = _engine()
    assert eng._check_model_staleness() is True


def test_provenance_for_different_bytes_is_stale(saved):
    """A registry entry whose sha256 does not match the artifact on disk
    describes a different model, so it says nothing about this one."""
    root, _art, _sha = saved
    _registry(root, "0" * 64, trained=_iso(1))
    eng = _engine()
    assert eng._check_model_staleness() is True


def test_missing_timestamp_is_stale(saved):
    root, _art, sha = saved
    _registry(root, sha)
    eng = _engine()
    assert eng._check_model_staleness() is True


def test_unparseable_timestamp_is_stale(saved):
    root, _art, sha = saved
    _registry(root, sha, trained="last tuesday")
    eng = _engine()
    assert eng._check_model_staleness() is True


def test_a_future_dated_model_is_stale(saved):
    """Beyond clock skew, a future date is a broken or forged record, and the
    arithmetic would otherwise hand it a negative age — permanently fresh."""
    root, _art, sha = saved
    _registry(root, sha, trained=(datetime.now(timezone.utc) + timedelta(days=3)).isoformat())
    eng = _engine()
    assert eng._check_model_staleness() is True


def test_small_clock_skew_is_tolerated(saved):
    root, _art, sha = saved
    _registry(root, sha, trained=(datetime.now(timezone.utc) + timedelta(seconds=30)).isoformat())
    eng = _engine()
    assert eng._check_model_staleness() is False


# ── Which timestamp wins ──────────────────────────────────────────────────────


def test_the_earliest_matching_timestamp_wins(saved):
    """Re-registering unchanged bytes under a new version must not reset the age."""
    root, _art, sha = saved
    _registry(
        root,
        sha,
        trained=_iso(90),
        extra={"v2": {"file": "x", "sha256": sha, "trained_at": _iso(1)}},
    )
    eng = _engine()
    assert eng._check_model_staleness() is True
    assert eng._model_age_days == pytest.approx(90.0, abs=0.1)


def test_registered_at_is_used_when_no_training_time_is_recorded(saved):
    """Today's registry carries `registered_at` and no `trained_at`. It is still
    bound to the sha and still immune to a touch, so it is the best available
    answer — and the gate must not be disabled for want of a better one."""
    root, _art, sha = saved
    _registry(root, sha, registered=_iso(90))
    eng = _engine()
    assert eng._check_model_staleness() is True
    assert eng._model_age_days == pytest.approx(90.0, abs=0.1)


# ── The existing protection stays on ──────────────────────────────────────────


def test_the_gate_can_still_be_disabled_deliberately(saved):
    root, _art, sha = saved
    _registry(root, sha, trained=_iso(900))
    ie._MODEL_MAX_AGE_DAYS = 30.0
    eng = _engine()
    assert eng._check_model_staleness() is True


def test_max_age_zero_still_disables_the_check(saved, monkeypatch):
    monkeypatch.setattr(ie, "_MODEL_MAX_AGE_DAYS", 0.0)
    eng = _engine()
    assert eng._check_model_staleness() is False


def test_a_missing_model_file_is_still_not_stale(saved):
    """Absent is handled elsewhere as unavailable; reporting it stale here would
    mislabel the reason a trade was refused."""
    root, art, _sha = saved
    art.unlink()
    eng = _engine()
    assert eng._check_model_staleness() is False


# ── The reason has to be actionable, not just present ─────────────────────────


def test_the_two_ways_provenance_can_be_missing_are_told_apart(saved):
    """ "No entry describes these bytes" and "the entry has no timestamp" are the
    same outcome and different jobs.

    Removing the `not matched` branch left all fifteen tests here green, because
    an unmatched digest leaves `stamps` empty and the next check refuses anyway.
    A branch no test distinguishes is a control nobody holds, and what it changes
    is the instruction an operator reads at 3am: one says register this artifact,
    the other says add a trained_at to the entry that already exists. Fixing the
    wrong one leaves the platform refusing to trade.
    """
    root, _art, sha = saved

    _registry(root, "0" * 64, trained=_iso(1))
    when, why = ie._model_training_time(root / "advanced_oos.pkl")
    assert when is None
    assert "no registry entry matches" in why, why

    _registry(root, sha)  # matches the bytes, carries no timestamp
    when, why = ie._model_training_time(root / "advanced_oos.pkl")
    assert when is None
    assert "no usable trained_at" in why, why
