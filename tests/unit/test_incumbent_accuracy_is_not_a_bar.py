"""A0 fix #2 — retire the incumbent's 0.5734 as the comparison bar.

The committed ``advanced_oos.pkl`` (sha256 ``dc7454d8…``) records OOS accuracy
0.5734. Measured 2026-09-24 (docs/audit/2026-09-24-a0-no-edge-investigation.md
Q4): on the SAME window always-predict-up scores 0.5516, and 37% of that
window's bars are synthetic month-mean bars from ``XAUUSD_50Y.csv``. On clean
``XAUUSD_40Y.csv`` features the same bytes score 0.534 against always-up 0.558.
So 0.5734 is base rate plus leakage, and anything that uses it as "the number
to beat", or quotes it as the model's quality without its baseline, repeats the
error.

These tests read the REAL ``ml/saved_models/registry.json`` and never write it.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
REGISTRY = ROOT / "ml" / "saved_models" / "registry.json"
INCUMBENT_SHA = "dc7454d8b0cae44e34d2d6b2f2882021e24a01062500cf30792447b546c87ed4"  # pragma: allowlist secret — a model sha256, not a credential

# What the annotation must NOT have changed (values at 5b22f8a6 / 0392f0d3).
_PROTECTED = {
    "advanced_oos_v1": {
        "sha256": INCUMBENT_SHA,
        "file": "ml/saved_models/advanced_oos.pkl",
        "state": "staging",
        "n_trades": 1260,
    },
    "advanced_oos_v2": {
        "sha256": INCUMBENT_SHA,
        "file": "ml/saved_models/advanced_oos.pkl",
        "state": "staging",
        "n_trades": 2016,
    },
    "xgb_horizon5_v1": {
        "sha256": INCUMBENT_SHA,
        "file": "ml/saved_models/advanced_oos.pkl",
        "state": "retired",
        "n_trades": 2016,
        "sharpe": 1.52,
    },
    "xgb_horizon5_v3": {
        "sha256": INCUMBENT_SHA,
        "file": "ml/saved_models/advanced_oos.pkl",
        "state": "active",
        "n_trades": 2016,
        "sharpe": 1.52,
    },
}


def _versions() -> dict:
    return json.loads(REGISTRY.read_text())["versions"]


def _incumbent_entries() -> dict:
    return {n: e for n, e in _versions().items() if e.get("sha256") == INCUMBENT_SHA}


def test_harness_sees_the_four_incumbent_entries():
    assert sorted(_incumbent_entries()) == sorted(_PROTECTED)


def test_annotation_changed_no_identity_or_state_field():
    versions = _versions()
    for name, fields in _PROTECTED.items():
        for key, value in fields.items():
            assert versions[name][key] == value, f"{name}.{key} changed"
        assert "trained_at" not in versions[name] or versions[name]["trained_at"]


def test_every_entry_for_the_same_bytes_records_the_same_auc():
    """Four entries, one sha256, four AUCs (0.7108 / 0.5427 / 0.5427 / 0.582).
    Identical bytes cannot have scored four AUCs on one window; only 0.582
    reproduces from the artifact."""
    aucs = {n: e.get("oos_auc") for n, e in _incumbent_entries().items()}
    assert set(aucs.values()) == {0.582}, aucs


@pytest.mark.parametrize("name", sorted(_PROTECTED))
def test_incumbent_entries_record_their_base_rate_and_leakage(name):
    entry = _versions()[name]
    assert entry["oos_majority_baseline_accuracy"] == pytest.approx(0.5516)
    assert entry["oos_leakage_contaminated"] is True
    assert entry["oos_clean_data_accuracy"] == pytest.approx(0.534)
    assert entry["oos_clean_data_majority_baseline_accuracy"] == pytest.approx(0.5578)
    assert entry["oos_clean_data_accuracy"] < entry["oos_clean_data_majority_baseline_accuracy"]
    assert "base rate" in entry["metrics_caveat"]


def test_the_incumbent_cannot_pass_the_promotion_skill_gate():
    """No AUC confidence bound was ever measured for these bytes, so the
    base-rate gate refuses them — and only rollback, which is ungated, can
    restore them."""
    from ml.oos_skill import skill_over_base_rate_check

    ok, reason = skill_over_base_rate_check(_versions()["xgb_horizon5_v3"])
    assert ok is False
    assert "oos_auc_ci_low" in reason


def test_retrain_with_ticks_judges_by_base_rate_not_by_the_previous_accuracy():
    """The script compared the new accuracy with the previous one (a key it
    could not even find, so the bar was always 0.0). Its verdict is now the
    same base-rate rule the registry enforces."""
    import importlib

    mod = importlib.import_module("scripts.retrain_with_ticks")
    assert not hasattr(mod, "load_existing_accuracy")

    high_but_unmeasured = {"oos": {"accuracy": 0.9}}
    ok, reason = mod.new_model_verdict(high_but_unmeasured)
    assert ok is False and "missing" in reason

    skilful = {
        "oos": {
            "oos_accuracy": 0.62,
            "oos_majority_baseline_accuracy": 0.55,
            "oos_auc_ci_low": 0.53,
        }
    }
    assert mod.new_model_verdict(skilful)[0] is True

    always_up = {
        "oos": {
            "oos_accuracy": 0.5516,
            "oos_majority_baseline_accuracy": 0.5516,
            "oos_auc_ci_low": 0.53,
        }
    }
    assert mod.new_model_verdict(always_up)[0] is False


def test_superadmin_model_list_shows_accuracy_beside_its_baseline():
    from api.superadmin.ml_ai import list_ml_models

    body = asyncio.run(list_ml_models(user=None))
    rows = {m["name"]: m for m in body["models"]}
    active = rows["xgb_horizon5_v3"]
    assert active["accuracy"] == pytest.approx(57.34)
    assert active["baseline_accuracy"] == pytest.approx(55.16)
    assert active["beats_base_rate"] is False  # not measured with an AUC bound → not shown as skill
    assert active["metrics_caveat"]
    # An entry with no baseline recorded is "unknown", never "beats".
    assert rows["rf_gcf_v1"]["beats_base_rate"] is None


def test_model_identity_doc_states_the_baseline_beside_57_34():
    doc = (ROOT / "ml" / "saved_models" / "MODEL_IDENTITY.md").read_text()
    rows = [ln for ln in doc.splitlines() if ln.startswith("| OOS accuracy ") and "57.34" in ln]
    assert rows, "the active model's metrics table has no 57.34% accuracy row"
    assert all("55.16" in ln for ln in rows), rows


def test_superadmin_status_quotes_the_baseline_with_the_accuracy():
    """The status tile printed OOS ACCURACY 57.34 alone, which reads as skill."""
    from api.superadmin.ml_ai import get_ml_status

    body = asyncio.run(get_ml_status(user=None))
    assert body["accuracy_baseline"] == pytest.approx(55.16)
    assert body["beats_base_rate"] is False
