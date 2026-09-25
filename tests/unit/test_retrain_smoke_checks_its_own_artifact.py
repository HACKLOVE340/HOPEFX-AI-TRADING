# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
tests/unit/test_retrain_smoke_checks_its_own_artifact.py
==========================================================
docs/ai/MASTER_OUTSTANDING.md §A0: "``retrain_horizon5.py --smoke`` writes no
``advanced_oos.pkl``, so the smoke step in ``retrain.yml`` has only ever
passed on the committed file."

Root cause (fixed in ``ml/train_advanced.py``): the ``--smoke`` override
inside ``ml.train_advanced.main()`` forced ``--oos-years`` to ``0.0``
unconditionally, discarding whatever ``scripts/retrain_horizon5.py`` passed
(it computes ``1.0`` specifically so a smoke CI run gets a real OOS split).
With ``oos_years=0``, ``split_oos_by_date()`` always returns ``X_oos=None``,
so ``oos_eval_advanced()`` — the only function that writes
``advanced_oos.pkl``, ``advanced_oos_meta.json`` and
``calibration_report.json`` — never ran. Combined with the CI workflow never
passing ``--output-dir`` (so it defaulted to the committed ``ml/saved_models``,
where ``advanced_oos.pkl`` already existed from an earlier, real run), the
smoke gate could only ever "pass" against a file the smoke run itself never
touched.

This file covers the two halves of the fix, both at the level a CI workflow
actually exercises:

1. ``verify_output_artifacts()`` (``retrain_horizon5.py --verify-only``) must
   fail when the OOS evaluation that stamps ``advanced_oos_meta.json`` with
   ``feature_set_version`` / ``oos_accuracy`` / ``oos_n`` never ran for the
   artifact at ``--output-dir`` — regardless of whether ``advanced_oos.pkl``
   itself happens to exist there — and must load and score the pickle rather
   than trusting its byte count.
2. The real ``--smoke`` path, run once end to end into a throwaway
   ``--output-dir``, writes a genuinely scoreable model there and never
   touches ``ml/saved_models``.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

import scripts.retrain_horizon5 as rh5

_ROOT = Path(__file__).resolve().parents[2]
_PACKAGED = _ROOT / "ml" / "saved_models"


def _parse(monkeypatch, *argv: str):
    monkeypatch.setattr(sys, "argv", ["retrain_horizon5.py", *argv])
    return rh5.parse_args()


def _write_fake_output(
    out_dir: Path,
    *,
    oos_n,
    feature_set_version,
    features: list[str],
    horizon: int = 5,
    pkl_bytes: bytes | None = None,
) -> None:
    """The four artifacts ``verify_output_artifacts`` checks, at a size that
    fits a unit test — a real ``LogisticRegression``, not xgboost."""
    import joblib
    from sklearn.linear_model import LogisticRegression

    if pkl_bytes is not None:
        (out_dir / "advanced_oos.pkl").write_bytes(pkl_bytes)
    else:
        rng = np.random.default_rng(0)
        X = pd.DataFrame(rng.normal(size=(20, len(features))), columns=features)
        y = pd.Series([0, 1] * 10)
        model = LogisticRegression().fit(X, y)
        joblib.dump(model, out_dir / "advanced_oos.pkl")

    oos_meta = {
        "feature_set_version": feature_set_version,
        "oos_accuracy": 0.6 if oos_n else None,
        "oos_n": oos_n,
    }
    (out_dir / "advanced_oos_meta.json").write_text(json.dumps(oos_meta))
    (out_dir / "horizon5_meta.json").write_text(json.dumps({"horizon": horizon}))
    (out_dir / "horizon5_training_report.json").write_text(
        json.dumps({"horizon": horizon, "final": {"features": features}})
    )


# ── verify_output_artifacts: must check THIS run's own OOS, not just bytes ──


def test_verify_output_artifacts_passes_when_this_runs_oos_actually_ran(monkeypatch, tmp_path):
    args = _parse(monkeypatch, "--output-dir", str(tmp_path))
    _write_fake_output(tmp_path, oos_n=42, feature_set_version=2, features=["a", "b", "c"])
    assert rh5.verify_output_artifacts(args) is True


def test_verify_output_artifacts_fails_when_oos_was_never_run(monkeypatch, tmp_path):
    """The exact shape of the pre-fix bug: advanced_oos.pkl and its sidecar
    JSON files all exist, but nothing recorded that an OOS evaluation ever
    produced them."""
    args = _parse(monkeypatch, "--output-dir", str(tmp_path))
    _write_fake_output(tmp_path, oos_n=None, feature_set_version=None, features=["a", "b", "c"])
    assert rh5.verify_output_artifacts(args) is False


def test_verify_output_artifacts_fails_when_oos_n_is_zero(monkeypatch, tmp_path):
    args = _parse(monkeypatch, "--output-dir", str(tmp_path))
    _write_fake_output(tmp_path, oos_n=0, feature_set_version=2, features=["a", "b", "c"])
    assert rh5.verify_output_artifacts(args) is False


def test_verify_output_artifacts_fails_when_the_pickle_cannot_score(monkeypatch, tmp_path):
    """Existing, non-empty bytes at the path are not evidence of a working
    model — the gate must actually load and score them."""
    args = _parse(monkeypatch, "--output-dir", str(tmp_path))
    _write_fake_output(
        tmp_path,
        oos_n=42,
        feature_set_version=2,
        features=["a", "b", "c"],
        pkl_bytes=b"not a real pickle, just non-empty bytes",
    )
    assert rh5.verify_output_artifacts(args) is False


# ── end to end: the real --smoke path, into a throwaway --output-dir ────────


def test_smoke_path_writes_a_real_scoreable_advanced_oos_pkl_to_the_output_dir(tmp_path):
    """Runs the exact two commands the CI workflow now runs: the smoke train,
    then ``--verify-only`` against that same directory. Proves by execution —
    not by reading the source — that the fixed pipeline produces a real
    artifact the check can load, and that neither step touches the committed
    ``ml/saved_models`` directory."""
    before = {p.name: p.stat().st_mtime_ns for p in _PACKAGED.iterdir() if p.is_file()}

    out = tmp_path / "smoke-out"
    train = subprocess.run(
        [sys.executable, str(_ROOT / "scripts" / "retrain_horizon5.py"), "--smoke", "--output-dir", str(out)],
        cwd=_ROOT,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert train.returncode == 0, train.stdout[-4000:] + train.stderr[-4000:]
    assert (out / "advanced_oos.pkl").is_file(), "the smoke run wrote no advanced_oos.pkl to --output-dir"

    oos_meta = json.loads((out / "advanced_oos_meta.json").read_text())
    assert oos_meta.get("oos_n"), f"no OOS samples were recorded: {oos_meta}"
    assert oos_meta.get("feature_set_version") is not None

    verify = subprocess.run(
        [sys.executable, str(_ROOT / "scripts" / "retrain_horizon5.py"), "--verify-only", "--output-dir", str(out)],
        cwd=_ROOT,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert verify.returncode == 0, (
        "the produced artifact failed its own verification: " + verify.stdout[-4000:] + verify.stderr[-4000:]
    )

    after = {p.name: p.stat().st_mtime_ns for p in _PACKAGED.iterdir() if p.is_file()}
    assert after == before, "the smoke run touched ml/saved_models"


@pytest.mark.parametrize("output_dir_flag", [[]])
def test_smoke_without_output_dir_defaults_to_the_packaged_directory(monkeypatch, output_dir_flag):
    """Documents the trap the workflow fell into: omit ``--output-dir`` and
    every write lands in the committed directory, where an old
    ``advanced_oos.pkl`` already satisfies every artifact-presence check.
    This is exactly why the workflow must always pass ``--output-dir``
    explicitly — covered for the real workflow YAML in
    test_retrain_workflow_checks_its_own_output.py."""
    args = _parse(monkeypatch, *output_dir_flag)
    assert Path(args.output_dir).resolve() == _PACKAGED.resolve()
