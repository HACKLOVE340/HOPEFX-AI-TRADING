# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
tests/unit/test_retrain_workflow_checks_its_own_output.py
============================================================
docs/ai/MASTER_OUTSTANDING.md §A0: "``retrain_horizon5.py --smoke`` writes no
``advanced_oos.pkl``, so the smoke step in ``retrain.yml`` has only ever
passed on the committed file."

Half of that defect was in the workflow YAML itself: the smoke step never
passed ``--output-dir``, so it wrote into the default — the committed
``ml/saved_models`` — and the following "Verify model integrity" step ran
``ml.verify_model``, which checks the COMMITTED registry entry, not anything
the smoke run produced.

These tests parse the workflow YAML (never grep its prose) and assert the
smoke-validate job in both retrain workflows:

* always passes ``--output-dir`` on the training step, pointed somewhere
  other than the committed ``ml/saved_models``;
* checks that SAME directory in its following verification step, using
  ``retrain_horizon5.py --verify-only`` — which loads and scores the
  produced artifact — rather than ``ml.verify_model``, which never looks at
  the run's own output;
* never references a bare ``ml/saved_models`` path in either step's ``run:``.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

pytestmark = pytest.mark.unit

_ROOT = Path(__file__).resolve().parents[2]
_WORKFLOWS = _ROOT / ".github" / "workflows"

# (workflow file, job name, training step name, check step name)
_SMOKE_JOBS = [
    (
        "retrain.yml",
        "smoke-validate",
        "Smoke — validate retrain pipeline (no data download)",
        "Verify smoke artifact (this run's own output — never the committed model)",
    ),
    (
        "quarterly_retrain.yml",
        "smoke-validate",
        "Smoke validate retrain pipeline",
        "Verify smoke artifact (this run's own output — never the committed model)",
    ),
]


def _step(job: dict, name: str) -> dict:
    for step in job["steps"]:
        if step.get("name") == name:
            return step
    raise AssertionError(f"no step named {name!r} in job {job}")


def _output_dir_arg(run: str) -> str | None:
    m = re.search(r"--output-dir\s+(\S+)", run)
    return m.group(1) if m else None


@pytest.mark.parametrize("workflow_file,job_name,train_step_name,check_step_name", _SMOKE_JOBS)
def test_smoke_train_step_passes_an_output_dir(workflow_file, job_name, train_step_name, check_step_name):
    doc = yaml.safe_load((_WORKFLOWS / workflow_file).read_text(encoding="utf-8"))
    job = doc["jobs"][job_name]
    step = _step(job, train_step_name)
    run = step.get("run") or ""

    assert "retrain_horizon5.py" in run and "--smoke" in run, run
    out_dir = _output_dir_arg(run)
    assert out_dir, f"{workflow_file}::{job_name}::{train_step_name!r} does not pass --output-dir: {run!r}"
    assert "saved_models" not in out_dir, (
        f"{workflow_file}::{job_name}::{train_step_name!r} points --output-dir at the committed directory: {out_dir!r}"
    )


@pytest.mark.parametrize("workflow_file,job_name,train_step_name,check_step_name", _SMOKE_JOBS)
def test_smoke_check_step_verifies_the_same_output_dir_it_just_trained_into(
    workflow_file, job_name, train_step_name, check_step_name
):
    doc = yaml.safe_load((_WORKFLOWS / workflow_file).read_text(encoding="utf-8"))
    job = doc["jobs"][job_name]
    train_run = _step(job, train_step_name).get("run") or ""
    check_run = _step(job, check_step_name).get("run") or ""

    assert "retrain_horizon5.py" in check_run and "--verify-only" in check_run, check_run
    assert "ml.verify_model" not in check_run, (
        f"{workflow_file}::{job_name}::{check_step_name!r} still calls ml.verify_model, which checks the "
        f"COMMITTED registry entry — never this run's own --output-dir: {check_run!r}"
    )

    train_out = _output_dir_arg(train_run)
    check_out = _output_dir_arg(check_run)
    assert check_out, f"{workflow_file}::{job_name}::{check_step_name!r} does not pass --output-dir: {check_run!r}"
    assert check_out == train_out, (
        f"{workflow_file}::{job_name} trains into {train_out!r} but verifies {check_out!r} — "
        "the check would not be looking at the artifact this run produced"
    )


@pytest.mark.parametrize("workflow_file,job_name,train_step_name,check_step_name", _SMOKE_JOBS)
def test_smoke_job_never_calls_ml_verify_model(workflow_file, job_name, train_step_name, check_step_name):
    """ml.verify_model checks advanced_oos.pkl's sha256 against the ALREADY-
    COMMITTED registry.json entry — an anti-tampering check for a model
    presumed unchanged, not a check that anything this run trained is real."""
    doc = yaml.safe_load((_WORKFLOWS / workflow_file).read_text(encoding="utf-8"))
    job = doc["jobs"][job_name]
    for step in job["steps"]:
        run = step.get("run") or ""
        assert "ml.verify_model" not in run and "verify_model.py" not in run, (
            f"{workflow_file}::{job_name}::{step.get('name')!r} calls ml.verify_model: {run!r}"
        )
