# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
The model integrity check gates a ``pickle.load``, so it must not fail open.

``ml/__init__.py:_try_load`` calls ``_verify_checksum(path)`` and, if it passes,
hands the file to ``joblib.load`` and then to ``pickle.load``. What that check
permits is therefore arbitrary code execution, not a wrong prediction.

``_verify_checksum`` returned ``True`` in three separate cases:

1. the checksum file did not exist — it recorded a baseline from whatever was on
   disk and allowed the load;
2. the checksum file could not be parsed — "skipping verification";
3. the file was not listed in the baseline — it recorded and allowed.

Each is a one-step bypass for anyone who can write to the model directory:
delete the baseline, corrupt it, or give the payload a name the baseline does
not mention.

Case 1 was not hypothetical. ``model_checksums.json`` was **not committed**, so
on every fresh deployment the file was absent and the check established its own
reference from the artefacts it existed to verify. It could only ever have
caught tampering that happened after the first load inside a container that was
about to be replaced. The baseline is committed now.

Bootstrapping is still right in two places and both are tested below: a
development environment with no shipped baseline, and any directory that is not
the packaged one — `ML_MODEL_DIR` holds files an operator's own retrain job just
wrote, and no shipped baseline can cover those.

Surfaced while investigating CodeQL's critical alert on PR #315
(`py/unsafe-deserialization` at `ml/__init__.py`). CodeQL cannot see a checksum
gate as a sanitiser — and in this case it was right not to.
"""

from __future__ import annotations

import json
import pathlib

import pytest

pytestmark = pytest.mark.unit

_PACKAGED = pathlib.Path(__file__).resolve().parents[2] / "ml" / "saved_models"
_BASELINE = _PACKAGED / "model_checksums.json"


@pytest.fixture
def a_packaged_model() -> pathlib.Path:
    models = sorted(_PACKAGED.glob("*.pkl"))
    if not models:
        pytest.skip("no packaged .pkl artefacts in this checkout")
    return models[0]


@pytest.fixture
def restore_baseline():
    """Put the committed baseline back whatever a test does to it."""
    original = _BASELINE.read_bytes() if _BASELINE.exists() else None
    yield
    if original is None:
        _BASELINE.unlink(missing_ok=True)
    else:
        _BASELINE.write_bytes(original)


# ── The baseline must actually ship ──────────────────────────────────────────


def test_the_integrity_baseline_is_committed():
    """The headline. Without this file in the repository, the check had nothing
    to compare against on a fresh deploy and said so by allowing the load."""
    import subprocess

    tracked = subprocess.run(
        ["git", "ls-files", "--error-unmatch", str(_BASELINE.relative_to(_PACKAGED.parents[1]))],
        capture_output=True,
        cwd=_PACKAGED.parents[1],
        check=False,
    )
    assert tracked.returncode == 0, (
        "ml/saved_models/model_checksums.json is not tracked by git; the integrity "
        "check has no shipped reference and bootstraps from the files it verifies"
    )


def test_the_baseline_covers_every_packaged_model():
    stored = json.loads(_BASELINE.read_text())
    on_disk = {p.name for p in _PACKAGED.glob("*.pkl")}
    missing = sorted(on_disk - set(stored))
    assert not missing, f"packaged models absent from the baseline: {missing}"


def test_the_baseline_matches_the_committed_artefacts(a_packaged_model):
    """If this fails, either an artefact changed without the baseline being
    regenerated, or the baseline was regenerated against a modified artefact."""
    import ml

    assert ml._verify_checksum(a_packaged_model) is True


# ── Production must refuse, not bootstrap ────────────────────────────────────


@pytest.mark.parametrize("app_env", ["production", "staging", "prod", "Production"])
def test_a_missing_baseline_refuses_in_production(monkeypatch, a_packaged_model, restore_baseline, app_env):
    import ml

    monkeypatch.setenv("APP_ENV", app_env)
    _BASELINE.unlink()
    assert ml._verify_checksum(a_packaged_model) is False, "deleting the baseline still permits a pickle.load"


def test_an_unreadable_baseline_refuses_in_production(monkeypatch, a_packaged_model, restore_baseline):
    import ml

    monkeypatch.setenv("APP_ENV", "production")
    _BASELINE.write_text("{ this is not json")
    assert ml._verify_checksum(a_packaged_model) is False, "a corrupt baseline still permits a pickle.load"


def test_a_model_absent_from_the_baseline_refuses_in_production(monkeypatch, a_packaged_model, restore_baseline):
    """The subtlest of the three: an attacker need not touch the baseline at
    all, only choose a filename it does not mention."""
    import ml

    monkeypatch.setenv("APP_ENV", "production")
    stored = json.loads(_BASELINE.read_text())
    stored.pop(a_packaged_model.name, None)
    _BASELINE.write_text(json.dumps(stored))
    assert ml._verify_checksum(a_packaged_model) is False, "a model file the baseline does not list is still loaded"


def test_a_tampered_model_still_refuses(monkeypatch, a_packaged_model, restore_baseline):
    """The one case that always worked. It must keep working."""
    import ml

    monkeypatch.setenv("APP_ENV", "production")
    stored = json.loads(_BASELINE.read_text())
    stored[a_packaged_model.name] = "0" * 64
    _BASELINE.write_text(json.dumps(stored))
    assert ml._verify_checksum(a_packaged_model) is False


# ── Where bootstrapping is still correct ─────────────────────────────────────


@pytest.mark.parametrize("app_env", ["development", "dev", "test", "local"])
def test_development_still_bootstraps(monkeypatch, a_packaged_model, restore_baseline, app_env):
    """A developer with no baseline must still be able to run the app."""
    import ml

    monkeypatch.setenv("APP_ENV", app_env)
    _BASELINE.unlink()
    assert ml._verify_checksum(a_packaged_model) is True


def test_a_retrain_directory_bootstraps_even_in_production(monkeypatch, tmp_path):
    """`ML_MODEL_DIR` holds files the operator's own retrain job wrote. No
    shipped baseline can cover them, so refusing there would break retraining
    rather than protect anything."""
    import ml

    monkeypatch.setenv("APP_ENV", "production")
    model = tmp_path / "retrained.pkl"
    model.write_bytes(b"not really a pickle, never loaded by this test")

    assert ml._bootstrap_allowed(tmp_path) is True
    assert ml._verify_checksum(model) is True
    assert (tmp_path / "model_checksums.json").exists(), "the retrain directory got no baseline of its own"


def test_the_packaged_directory_is_not_bootstrappable_in_production(monkeypatch):
    import ml

    monkeypatch.setenv("APP_ENV", "production")
    assert ml._bootstrap_allowed(_PACKAGED) is False
