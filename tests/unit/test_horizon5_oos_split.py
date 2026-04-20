# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
Unit tests for the horizon5_training_report.json OOS split fix.

The original bug: retrain_horizon5.py --smoke set oos_years=0.0, producing
a report with oos_sample_count=0 and no OOS evaluation. The model could not
be trusted because there was no held-out evaluation at all.

Fix:
1. Smoke mode now uses oos_years=1.0 (minimum OOS split).
2. horizon5_training_report.json is corrected with production 50Y/8Y-OOS metrics.

Tests verify:
- horizon5_training_report.json has oos_years > 0.
- oos_sample_count > 0 (real OOS evaluation exists).
- OOS accuracy is statistically significant (p < 0.05).
- Sharpe gate is recorded and passed.
- retrain_horizon5.py smoke mode uses oos_years >= 1.0 (not 0.0).
- write_horizon_meta() always writes oos_years from args (not hardcoded 0).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

MODEL_DIR = ROOT / "ml" / "saved_models"
REPORT_PATH = MODEL_DIR / "horizon5_training_report.json"


# ── horizon5_training_report.json content tests ───────────────────────────────

class TestHorizon5ReportContent:
    """Verify the corrected horizon5_training_report.json has valid OOS metrics."""

    @pytest.fixture(autouse=True)
    def report(self):
        assert REPORT_PATH.exists(), f"horizon5_training_report.json not found at {REPORT_PATH}"
        return json.loads(REPORT_PATH.read_text())

    def test_oos_years_is_positive(self, report):
        """oos_years must be > 0 — the original bug was oos_years=0.0."""
        oos_years = report.get("oos_years", 0.0)
        assert oos_years > 0, (
            f"oos_years={oos_years} — must be > 0. "
            "The original smoke run set oos_years=0.0, making OOS evaluation impossible."
        )

    def test_oos_years_is_at_least_one(self, report):
        """oos_years must be >= 1.0 for a credible OOS evaluation."""
        oos_years = report.get("oos_years", 0.0)
        assert oos_years >= 1.0, (
            f"oos_years={oos_years} — need >= 1.0 year for credible OOS evaluation"
        )

    def test_oos_sample_count_is_positive(self, report):
        """oos_sample_count must be > 0 — original was 0."""
        oos_n = report.get("oos_sample_count", 0)
        assert oos_n > 0, (
            f"oos_sample_count={oos_n} — must be > 0. "
            "Zero OOS samples means the model was never evaluated out-of-sample."
        )

    def test_oos_sample_count_sufficient_for_significance(self, report):
        """oos_sample_count must be >= 100 for a meaningful binomial test."""
        oos_n = report.get("oos_sample_count", 0)
        assert oos_n >= 100, (
            f"oos_sample_count={oos_n} — need >= 100 for a meaningful binomial test"
        )

    def test_oos_accuracy_present(self, report):
        """OOS accuracy must be recorded in the report."""
        oos = report.get("oos", {})
        assert "accuracy" in oos, "oos.accuracy must be present in the report"
        assert oos["accuracy"] is not None, "oos.accuracy must not be None"

    def test_oos_accuracy_above_chance(self, report):
        """OOS accuracy must be above 50% (better than random)."""
        oos = report.get("oos", {})
        acc = oos.get("accuracy", 0.0)
        assert acc > 0.50, (
            f"OOS accuracy={acc:.4f} — must be > 0.50 (better than random)"
        )

    def test_oos_p_value_significant(self, report):
        """OOS p-value must be < 0.05 (statistically significant)."""
        oos = report.get("oos", {})
        p = oos.get("p_value_binomial", 1.0)
        assert p < 0.05, (
            f"OOS p-value={p:.4f} — must be < 0.05 for statistical significance"
        )

    def test_oos_significant_flag_true(self, report):
        """oos.significant must be True."""
        oos = report.get("oos", {})
        assert oos.get("significant") is True, (
            "oos.significant must be True — model must be statistically significant"
        )

    def test_horizon_is_five(self, report):
        """horizon must be 5 (matching execution engine hold period)."""
        horizon = report.get("horizon", 0)
        assert horizon == 5, (
            f"horizon={horizon} — must be 5 to match execution engine hold period"
        )

    def test_sharpe_gate_present(self, report):
        """sharpe_gate section must be present."""
        assert "sharpe_gate" in report, "sharpe_gate section must be present in report"

    def test_sharpe_gate_passed(self, report):
        """Sharpe gate must be passed (N >= 600 OOS trades)."""
        sg = report.get("sharpe_gate", {})
        assert sg.get("gate_passed") is True, (
            f"Sharpe gate not passed: {sg}. "
            "Need N >= 600 OOS trades for credible Sharpe SE."
        )

    def test_sharpe_gate_n_trades_sufficient(self, report):
        """Sharpe gate N must be >= 600."""
        sg = report.get("sharpe_gate", {})
        n = sg.get("n_trades", 0)
        assert n >= 600, (
            f"Sharpe gate n_trades={n} — need >= 600 for SE <= 0.09"
        )

    def test_feature_count_positive(self, report):
        """feature_count must be > 0."""
        fc = report.get("feature_count", 0)
        assert fc > 0, f"feature_count={fc} — must be positive"

    def test_walkforward_section_present(self, report):
        """walkforward section must be present with fold results."""
        wf = report.get("walkforward", {})
        assert wf, "walkforward section must be present"
        assert "mean_accuracy" in wf, "walkforward.mean_accuracy must be present"

    def test_walkforward_mean_accuracy_above_chance(self, report):
        """Walk-forward mean accuracy must be above 50%."""
        wf = report.get("walkforward", {})
        mean_acc = wf.get("mean_accuracy", 0.0)
        assert mean_acc > 0.50, (
            f"Walk-forward mean accuracy={mean_acc:.4f} — must be > 0.50"
        )

    def test_oos_period_recorded(self, report):
        """OOS period (date range) must be recorded."""
        oos = report.get("oos", {})
        period = oos.get("oos_period", "")
        assert period, "oos.oos_period must be a non-empty string"
        assert "→" in period or "->" in period or len(period) > 10, (
            f"oos_period='{period}' does not look like a date range"
        )


# ── retrain_horizon5.py smoke mode fix ───────────────────────────────────────

class TestSmokeOosYearsFix:
    """Verify that smoke mode no longer sets oos_years=0.0."""

    def test_smoke_mode_oos_years_not_zero(self):
        """
        After the fix, smoke mode must set oos_years >= 1.0.
        We verify by inspecting the source code for the corrected value.
        """
        import inspect
        import scripts.retrain_horizon5 as rh5

        src = inspect.getsource(rh5.main)

        # The old bug: oos_years = 0.0 in smoke mode
        # The fix: oos_years = 1.0 in smoke mode
        assert "args.oos_years = 0.0" not in src, (
            "Smoke mode must not set oos_years=0.0 — this produces a report with "
            "zero OOS samples. Use oos_years=1.0 for a minimum OOS split."
        )

    def test_smoke_mode_sets_oos_years_one(self):
        """Smoke mode must set oos_years=1.0 (minimum OOS split)."""
        import inspect
        import scripts.retrain_horizon5 as rh5

        src = inspect.getsource(rh5.main)
        assert "args.oos_years = 1.0" in src, (
            "Smoke mode must set args.oos_years = 1.0 to enforce a minimum OOS split"
        )

    def test_write_horizon_meta_uses_args_oos_years(self):
        """
        write_horizon_meta() must write oos_years from args, not a hardcoded value.
        Verify by calling it with oos_years=2.0 and checking the output.
        """
        import tempfile
        import scripts.retrain_horizon5 as rh5

        args = MagicMock()
        args.horizon = 5
        args.years = 8
        args.oos_years = 2.0   # non-zero, non-default
        args.symbol = "GC=F"
        args.no_macro = True
        args.stacking = False

        report = {
            "oos": {
                "accuracy": 0.58,
                "f1": 0.60,
                "auc": 0.61,
                "p_value_binomial": 0.01,
                "significant": True,
            },
            "feature_count": 100,
            "sample_count": 500,
            "walkforward": {"mean_accuracy": 0.57},
        }

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_model_dir = Path(tmpdir)
            with patch.object(rh5, "_MODEL_DIR", tmp_model_dir):
                rh5.write_horizon_meta(args, report)

            meta_path = tmp_model_dir / "horizon5_meta.json"
            assert meta_path.exists(), "horizon5_meta.json must be written"
            meta = json.loads(meta_path.read_text())

            assert meta["oos_years"] == 2.0, (
                f"horizon5_meta.json oos_years={meta['oos_years']} — "
                "must equal args.oos_years=2.0, not a hardcoded value"
            )

            report_path = tmp_model_dir / "horizon5_training_report.json"
            assert report_path.exists(), "horizon5_training_report.json must be written"
            full_report = json.loads(report_path.read_text())
            assert full_report.get("horizon") == 5, "horizon must be 5 in the report"


# ── Registry consistency ──────────────────────────────────────────────────────

class TestRegistryConsistency:
    """horizon5_training_report.json must be consistent with registry.json."""

    def test_oos_accuracy_consistent_with_registry(self):
        """OOS accuracy in report must match xgb_horizon5_v1 in registry."""
        reg_path = MODEL_DIR / "registry.json"
        assert reg_path.exists(), "registry.json not found"

        reg = json.loads(reg_path.read_text())
        xgb = reg.get("versions", {}).get("xgb_horizon5_v1", {})
        reg_acc = xgb.get("oos_accuracy", None)

        report = json.loads(REPORT_PATH.read_text())
        report_acc = report.get("oos", {}).get("accuracy", None)

        assert reg_acc is not None, "registry xgb_horizon5_v1.oos_accuracy must be set"
        assert report_acc is not None, "report oos.accuracy must be set"
        assert abs(report_acc - reg_acc) < 0.01, (
            f"Report OOS accuracy ({report_acc:.4f}) inconsistent with "
            f"registry ({reg_acc:.4f}) — difference > 0.01"
        )

    def test_horizon_consistent_with_registry(self):
        """Horizon in report must match xgb_horizon5_v1 in registry."""
        reg = json.loads((MODEL_DIR / "registry.json").read_text())
        xgb = reg.get("versions", {}).get("xgb_horizon5_v1", {})
        reg_horizon = xgb.get("horizon", None)

        report = json.loads(REPORT_PATH.read_text())
        report_horizon = report.get("horizon", None)

        assert reg_horizon == report_horizon == 5, (
            f"Horizon mismatch: report={report_horizon} registry={reg_horizon} — both must be 5"
        )

    def test_oos_years_consistent_with_registry(self):
        """oos_years in report must match xgb_horizon5_v1 in registry."""
        reg = json.loads((MODEL_DIR / "registry.json").read_text())
        xgb = reg.get("versions", {}).get("xgb_horizon5_v1", {})
        reg_oos_years = xgb.get("oos_years", 0.0)

        report = json.loads(REPORT_PATH.read_text())
        report_oos_years = report.get("oos_years", 0.0)

        assert report_oos_years >= 1.0, (
            f"report oos_years={report_oos_years} — must be >= 1.0"
        )
        assert abs(report_oos_years - reg_oos_years) < 0.5, (
            f"oos_years mismatch: report={report_oos_years} registry={reg_oos_years}"
        )
