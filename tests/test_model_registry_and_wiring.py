# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
tests/test_model_registry_and_wiring.py
=======================================
Unit tests for:
  - ml.model_registry.ModelRegistry  (SHA-256, promotion gate, symlink)
  - ml.advanced_predictor.AdvancedPredictor._verify_integrity
  - core.live_trading_gate.LiveTradingGate._check_sharpe_gate (null-check)
  - brokers.oanda_paper_clock.OandaPaperClock.record_fill / sharpe_status
"""

from __future__ import annotations

import hashlib
import json
import os
import pathlib
import tempfile
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_RNG = __import__("numpy").random.default_rng(42)


def _tmp_pkl(content: bytes = b"fake-model-bytes") -> pathlib.Path:
    """Write *content* to a temp file and return its Path."""
    fd, path = tempfile.mkstemp(suffix=".pkl")
    with os.fdopen(fd, "wb") as fh:
        fh.write(content)
    return pathlib.Path(path)


def _sha256(path: pathlib.Path) -> str:
    h = hashlib.sha256()
    h.update(path.read_bytes())
    return h.hexdigest()


def _make_registry(tmp_path: pathlib.Path):
    from ml.model_registry import ModelRegistry

    return ModelRegistry(registry_path=tmp_path / "registry.json")


# ===========================================================================
# ModelRegistry — registration
# ===========================================================================


class TestModelRegistryRegister:
    def test_register_creates_entry(self, tmp_path):
        reg = _make_registry(tmp_path)
        pkl = _tmp_pkl()
        entry = reg.register(
            name="v1",
            file_path=pkl,
            oos_accuracy=0.65,
            oos_auc=0.71,
            oos_p_value=0.001,
            sharpe_gate_passed=True,
            n_trades=700,
            feature_count=176,
        )
        assert entry["name"] == "v1"
        assert entry["state"] == "staging"
        assert len(entry["sha256"]) == 64
        assert entry["oos_accuracy"] == pytest.approx(0.65)
        pkl.unlink()

    def test_register_computes_correct_sha256(self, tmp_path):
        reg = _make_registry(tmp_path)
        content = b"deterministic-content-xyz"
        pkl = _tmp_pkl(content)
        expected = hashlib.sha256(content).hexdigest()
        entry = reg.register("v_sha", pkl, oos_accuracy=0.61, oos_p_value=0.01, sharpe_gate_passed=True)
        assert entry["sha256"] == expected
        pkl.unlink()

    def test_register_missing_file_raises(self, tmp_path):
        reg = _make_registry(tmp_path)
        with pytest.raises(FileNotFoundError):
            reg.register("v_missing", pathlib.Path("/nonexistent/model.pkl"))

    def test_register_empty_name_raises(self, tmp_path):
        reg = _make_registry(tmp_path)
        pkl = _tmp_pkl()
        with pytest.raises(ValueError, match="name"):
            reg.register("", pkl)
        pkl.unlink()

    def test_register_invalid_state_raises(self, tmp_path):
        reg = _make_registry(tmp_path)
        pkl = _tmp_pkl()
        with pytest.raises(ValueError, match="state"):
            reg.register("v_bad", pkl, state="production")
        pkl.unlink()

    def test_register_persists_to_disk(self, tmp_path):
        reg = _make_registry(tmp_path)
        pkl = _tmp_pkl()
        reg.register(
            "v_persist",
            pkl,
            oos_accuracy=0.62,
            oos_p_value=0.02,
            sharpe_gate_passed=True,
        )
        # Re-load from disk
        reg2 = _make_registry(tmp_path)
        assert "v_persist" in reg2.list_versions()
        pkl.unlink()

    def test_register_multiple_versions(self, tmp_path):
        reg = _make_registry(tmp_path)
        for i in range(3):
            pkl = _tmp_pkl(f"model-{i}".encode())
            reg.register(
                f"v{i}",
                pkl,
                oos_accuracy=0.60 + i * 0.01,
                oos_p_value=0.01,
                sharpe_gate_passed=True,
            )
            pkl.unlink()
        assert len(reg.list_versions()) == 3


# ===========================================================================
# ModelRegistry — promotion gate
# ===========================================================================


class TestModelRegistryPromotionGate:
    def _reg_with_entry(self, tmp_path, *, acc, pval, sharpe_ok) -> tuple:
        reg = _make_registry(tmp_path)
        pkl = _tmp_pkl()
        reg.register(
            "v_gate",
            pkl,
            oos_accuracy=acc,
            oos_p_value=pval,
            sharpe_gate_passed=sharpe_ok,
        )
        return reg, pkl

    def test_promote_passes_all_checks(self, tmp_path):
        reg, pkl = self._reg_with_entry(tmp_path, acc=0.65, pval=0.001, sharpe_ok=True)
        entry = reg.promote("v_gate")
        assert entry["state"] == "production"
        assert entry["promoted_at"] is not None
        assert reg.active_version()["name"] == "v_gate"
        pkl.unlink()

    def test_promote_blocked_low_accuracy(self, tmp_path):
        reg, pkl = self._reg_with_entry(tmp_path, acc=0.55, pval=0.001, sharpe_ok=True)
        with pytest.raises(RuntimeError, match="accuracy"):
            reg.promote("v_gate")
        pkl.unlink()

    def test_promote_blocked_high_pvalue(self, tmp_path):
        reg, pkl = self._reg_with_entry(tmp_path, acc=0.65, pval=0.10, sharpe_ok=True)
        with pytest.raises(RuntimeError, match="p-value"):
            reg.promote("v_gate")
        pkl.unlink()

    def test_promote_blocked_sharpe_gate_not_passed(self, tmp_path):
        reg, pkl = self._reg_with_entry(tmp_path, acc=0.65, pval=0.001, sharpe_ok=False)
        with pytest.raises(RuntimeError, match="[Ss]harpe"):
            reg.promote("v_gate")
        pkl.unlink()

    def test_promote_unknown_version_raises(self, tmp_path):
        reg = _make_registry(tmp_path)
        with pytest.raises(KeyError):
            reg.promote("nonexistent")

    def test_promote_retires_previous_production(self, tmp_path):
        reg = _make_registry(tmp_path)
        pkl1 = _tmp_pkl(b"model-1")
        pkl2 = _tmp_pkl(b"model-2")
        reg.register("v1", pkl1, oos_accuracy=0.62, oos_p_value=0.01, sharpe_gate_passed=True)
        reg.register("v2", pkl2, oos_accuracy=0.65, oos_p_value=0.001, sharpe_gate_passed=True)
        reg.promote("v1")
        reg.promote("v2")
        assert reg.get_version("v1")["state"] == "retired"
        assert reg.get_version("v2")["state"] == "production"
        pkl1.unlink()
        pkl2.unlink()

    def test_active_version_none_before_promotion(self, tmp_path):
        reg = _make_registry(tmp_path)
        assert reg.active_version() is None
        assert reg.active_path() is None


# ===========================================================================
# ModelRegistry — integrity verification
# ===========================================================================


class TestModelRegistryVerify:
    def test_verify_passes_for_correct_digest(self, tmp_path):
        reg = _make_registry(tmp_path)
        pkl = _tmp_pkl(b"correct-content")
        reg.register("v_ok", pkl, oos_accuracy=0.62, oos_p_value=0.01, sharpe_gate_passed=True)
        ok, msg = reg.verify("v_ok")
        assert ok is True
        assert "OK" in msg
        pkl.unlink()

    def test_verify_fails_for_tampered_artifact(self, tmp_path):
        reg = _make_registry(tmp_path)
        pkl = _tmp_pkl(b"original-content")
        reg.register(
            "v_tamper",
            pkl,
            oos_accuracy=0.62,
            oos_p_value=0.01,
            sharpe_gate_passed=True,
        )
        # Tamper with the file after registration
        pkl.write_bytes(b"tampered-content")
        ok, msg = reg.verify("v_tamper")
        assert ok is False
        assert "MISMATCH" in msg
        pkl.unlink()

    def test_verify_fails_for_missing_artifact(self, tmp_path):
        reg = _make_registry(tmp_path)
        pkl = _tmp_pkl(b"will-be-deleted")
        reg.register("v_del", pkl, oos_accuracy=0.62, oos_p_value=0.01, sharpe_gate_passed=True)
        pkl.unlink()
        ok, msg = reg.verify("v_del")
        assert ok is False
        assert "missing" in msg.lower() or "Artifact" in msg

    def test_verify_unknown_version(self, tmp_path):
        reg = _make_registry(tmp_path)
        ok, msg = reg.verify("nonexistent")
        assert ok is False
        assert "not found" in msg

    def test_verify_active_no_active_version(self, tmp_path):
        reg = _make_registry(tmp_path)
        ok, msg = reg.verify_active()
        assert ok is False
        assert "No active" in msg

    def test_verify_active_after_promotion(self, tmp_path):
        reg = _make_registry(tmp_path)
        pkl = _tmp_pkl(b"production-model")
        reg.register("v_prod", pkl, oos_accuracy=0.65, oos_p_value=0.001, sharpe_gate_passed=True)
        reg.promote("v_prod")
        ok, _ = reg.verify_active()
        assert ok is True
        pkl.unlink()


# ===========================================================================
# ModelRegistry — bootstrap_from_meta
# ===========================================================================


class TestModelRegistryBootstrap:
    def test_bootstrap_registers_from_meta(self, tmp_path):
        meta = {
            "oos_accuracy": 0.6635,
            "oos_auc": 0.7108,
            "oos_p_value": 0.0,
            "feature_count": 176,
            "sharpe_gate": {"gate_passed": True, "n_trades": 1260, "se": 0.041},
        }
        meta_path = tmp_path / "meta.json"
        meta_path.write_text(json.dumps(meta))
        pkl = _tmp_pkl(b"bootstrap-model")

        reg = _make_registry(tmp_path)
        entry = reg.bootstrap_from_meta(meta_path=meta_path, model_path=pkl, name="v_boot")
        assert entry is not None
        assert entry["oos_accuracy"] == pytest.approx(0.6635)
        assert entry["sharpe_gate_passed"] is True
        pkl.unlink()

    def test_bootstrap_promotes_when_requested(self, tmp_path):
        meta = {
            "oos_accuracy": 0.65,
            "oos_auc": 0.71,
            "oos_p_value": 0.001,
            "feature_count": 176,
            "sharpe_gate": {"gate_passed": True, "n_trades": 700},
        }
        meta_path = tmp_path / "meta.json"
        meta_path.write_text(json.dumps(meta))
        pkl = _tmp_pkl(b"promoted-model")

        reg = _make_registry(tmp_path)
        entry = reg.bootstrap_from_meta(meta_path=meta_path, model_path=pkl, name="v_promo", promote=True)
        assert entry["state"] == "production"
        pkl.unlink()

    def test_bootstrap_skips_if_already_registered(self, tmp_path):
        meta = {
            "oos_accuracy": 0.65,
            "oos_p_value": 0.001,
            "sharpe_gate": {"gate_passed": True},
        }
        meta_path = tmp_path / "meta.json"
        meta_path.write_text(json.dumps(meta))
        pkl = _tmp_pkl(b"idempotent-model")

        reg = _make_registry(tmp_path)
        reg.bootstrap_from_meta(meta_path=meta_path, model_path=pkl, name="v_idem")
        # Second call should be a no-op
        entry2 = reg.bootstrap_from_meta(meta_path=meta_path, model_path=pkl, name="v_idem")
        assert entry2 is not None
        assert len(reg.list_versions()) == 1
        pkl.unlink()

    def test_bootstrap_returns_none_for_missing_artifact(self, tmp_path):
        reg = _make_registry(tmp_path)
        entry = reg.bootstrap_from_meta(model_path=pathlib.Path("/nonexistent/model.pkl"), name="v_none")
        assert entry is None


# ===========================================================================
# AdvancedPredictor — _verify_integrity
# ===========================================================================


class TestAdvancedPredictorIntegrity:
    """Tests for the pre-serve SHA-256 integrity check."""

    def _make_predictor(self, path):
        from ml.advanced_predictor import AdvancedPredictor

        return AdvancedPredictor(model_path=pathlib.Path(path))

    def test_integrity_unchecked_before_load(self, tmp_path):
        p = self._make_predictor("/tmp/nonexistent_model.pkl")
        assert p._integrity_ok is None

    def test_integrity_fails_for_missing_file(self, tmp_path):
        p = self._make_predictor("/tmp/nonexistent_model.pkl")
        ok = p._verify_integrity()
        assert ok is False
        assert "missing" in p._integrity_msg.lower() or "Artifact" in p._integrity_msg

    def test_integrity_warns_and_passes_when_no_registry(self, tmp_path):
        """No digest on record → fail-open with a warning."""
        import ml.model_registry as mr

        original = mr._registry
        mr._registry = None  # force fresh singleton with empty registry

        pkl = _tmp_pkl(b"unregistered-model")
        # Point registry at an empty temp dir so no manifest exists
        empty_reg_path = tmp_path / "empty_registry.json"
        from ml.model_registry import ModelRegistry

        mr._registry = ModelRegistry(registry_path=empty_reg_path)

        p = self._make_predictor(str(pkl))
        ok = p._verify_integrity()
        assert ok is True
        assert "skipping" in p._integrity_msg.lower() or "No SHA-256" in p._integrity_msg

        pkl.unlink()
        mr._registry = original

    def test_integrity_passes_with_matching_digest(self, tmp_path):
        import ml.model_registry as mr

        original = mr._registry

        pkl = _tmp_pkl(b"registered-model-content")
        reg = _make_registry(tmp_path)
        reg.register(
            "v_match",
            pkl,
            oos_accuracy=0.65,
            oos_p_value=0.001,
            sharpe_gate_passed=True,
        )
        reg.promote("v_match")
        mr._registry = reg

        p = self._make_predictor(str(pkl))
        ok = p._verify_integrity()
        assert ok is True
        assert "OK" in p._integrity_msg

        pkl.unlink()
        mr._registry = original

    def test_integrity_fails_with_mismatched_digest(self, tmp_path):
        import ml.model_registry as mr

        original = mr._registry

        pkl = _tmp_pkl(b"original-content")
        reg = _make_registry(tmp_path)
        reg.register(
            "v_mismatch",
            pkl,
            oos_accuracy=0.65,
            oos_p_value=0.001,
            sharpe_gate_passed=True,
        )
        reg.promote("v_mismatch")

        # Corrupt the manifest digest
        manifest = json.loads((tmp_path / "registry.json").read_text())
        manifest["versions"]["v_mismatch"]["sha256"] = "deadbeef" * 8
        (tmp_path / "registry.json").write_text(json.dumps(manifest))
        mr._registry = reg

        p = self._make_predictor(str(pkl))
        ok = p._verify_integrity()
        assert ok is False
        assert "MISMATCH" in p._integrity_msg

        pkl.unlink()
        mr._registry = original

    def test_integrity_result_in_stats(self, tmp_path):
        p = self._make_predictor("/tmp/nonexistent_model.pkl")
        p._verify_integrity()
        s = p.stats
        assert "integrity_ok" in s
        assert "integrity_msg" in s
        assert s["integrity_ok"] is False

    def test_load_blocked_on_integrity_failure(self, tmp_path):
        """_load() must return False when integrity check fails."""
        import ml.model_registry as mr

        original = mr._registry

        pkl = _tmp_pkl(b"tampered-model")
        reg = _make_registry(tmp_path)
        reg.register(
            "v_block",
            pkl,
            oos_accuracy=0.65,
            oos_p_value=0.001,
            sharpe_gate_passed=True,
        )
        reg.promote("v_block")

        # Corrupt manifest digest so integrity fails
        manifest = json.loads((tmp_path / "registry.json").read_text())
        manifest["versions"]["v_block"]["sha256"] = "badhash" * 9
        (tmp_path / "registry.json").write_text(json.dumps(manifest))
        mr._registry = reg

        from ml.advanced_predictor import AdvancedPredictor

        p = AdvancedPredictor(model_path=pkl)
        result = p._load()
        assert result is False
        assert p._model is None

        pkl.unlink()
        mr._registry = original


# ===========================================================================
# LiveTradingGate — _check_sharpe_gate null-check
# ===========================================================================


class TestLiveTradingGateNullCheck:
    """Verify that missing/empty pooled metrics are treated as gate-blocked."""

    def _gate_with_report(self, tmp_path: pathlib.Path, report: dict[str, Any]):
        """Write *report* to the expected path and return a LiveTradingGate."""
        results_dir = tmp_path / "backtest" / "results"
        results_dir.mkdir(parents=True, exist_ok=True)
        (results_dir / "multi_symbol_report.json").write_text(json.dumps(report))

        import core.live_trading_gate as g

        original_root = g.ROOT
        g.ROOT = tmp_path
        gate = g.LiveTradingGate()
        g.ROOT = original_root
        return gate, tmp_path, g

    def _run_check(self, tmp_path, report):
        results_dir = tmp_path / "backtest" / "results"
        results_dir.mkdir(parents=True, exist_ok=True)
        (results_dir / "multi_symbol_report.json").write_text(json.dumps(report))

        import core.live_trading_gate as g

        original = g.ROOT
        g.ROOT = tmp_path
        gate = g.LiveTradingGate()
        passed, msg = gate._check_sharpe_gate()
        g.ROOT = original
        return passed, msg

    def test_pooled_none_is_blocked(self, tmp_path):
        passed, msg = self._run_check(tmp_path, {"pooled": None})
        assert passed is False
        assert "pooled" in msg.lower() or "BLOCKED" in msg

    def test_pooled_empty_dict_is_blocked(self, tmp_path):
        passed, _ = self._run_check(tmp_path, {"pooled": {}})
        assert passed is False

    def test_pooled_key_absent_is_blocked(self, tmp_path):
        passed, _ = self._run_check(tmp_path, {"symbols": []})
        assert passed is False

    def test_pooled_wrong_type_is_blocked(self, tmp_path):
        passed, _ = self._run_check(tmp_path, {"pooled": "not-a-dict"})
        assert passed is False

    def test_valid_pooled_gate_passed(self, tmp_path):
        report = {
            "pooled": {
                "n_total_trades": 952,
                "sharpe_gate_passed": True,
                "pooled_sharpe_se": 0.082,
                "pooled_sharpe": 3.27,
            }
        }
        passed, msg = self._run_check(tmp_path, report)
        assert passed is True
        assert "952" in msg

    def test_valid_pooled_gate_blocked_low_n(self, tmp_path):
        report = {
            "pooled": {
                "n_total_trades": 100,
                "sharpe_gate_passed": False,
                "pooled_sharpe_se": 0.45,
                "pooled_sharpe": 1.2,
            }
        }
        passed, msg = self._run_check(tmp_path, report)
        assert passed is False
        assert "100" in msg

    def test_no_report_file_falls_through_to_meta(self, tmp_path):
        """When no report file exists, gate falls back to OOS meta."""
        import core.live_trading_gate as g

        original = g.ROOT
        g.ROOT = tmp_path  # no backtest/results/ dir → file not found
        gate = g.LiveTradingGate()
        passed, _ = gate._check_sharpe_gate()
        g.ROOT = original
        # Without meta either, should be blocked
        assert passed is False


# ===========================================================================
# OandaPaperClock — SharpeProgressTracker wiring
# ===========================================================================


class TestOandaPaperClockTrackerWiring:
    def _make_clock(self, tmp_path: pathlib.Path):
        from brokers.oanda_paper_clock import OandaPaperClock

        return OandaPaperClock(stamp_path=tmp_path / "stamp.json")

    def test_tracker_initialised_on_construction(self, tmp_path):
        clock = self._make_clock(tmp_path)
        assert clock._sharpe_tracker is not None

    def test_record_fill_increments_n_trades(self, tmp_path):
        clock = self._make_clock(tmp_path)
        s = clock.record_fill(0.012, symbol="XAU_USD")
        assert s["n_trades"] == 1

    def test_record_fill_accumulates_across_calls(self, tmp_path):
        clock = self._make_clock(tmp_path)
        for r in [0.01, -0.005, 0.008, 0.003, -0.002]:
            clock.record_fill(r)
        s = clock.sharpe_status()
        assert s["n_trades"] == 5

    def test_record_fill_returns_status_dict(self, tmp_path):
        clock = self._make_clock(tmp_path)
        s = clock.record_fill(0.015)
        for key in (
            "n_trades",
            "sharpe",
            "sharpe_se",
            "gate_passed",
            "pct_to_gate",
            "message",
        ):
            assert key in s, f"Missing key: {key}"

    def test_sharpe_status_available_true(self, tmp_path):
        clock = self._make_clock(tmp_path)
        snap = clock.sharpe_status()
        assert snap["available"] is True

    def test_sharpe_status_gate_not_passed_initially(self, tmp_path):
        clock = self._make_clock(tmp_path)
        clock.record_fill(0.01)
        snap = clock.sharpe_status()
        assert snap["gate_passed"] is False

    def test_sharpe_status_gate_passes_with_enough_trades(self, tmp_path):
        """Gate passes when target_n and target_sharpe are both met."""
        from brokers.oanda_paper_clock import OandaPaperClock

        # Use a low target so the test runs fast
        clock = OandaPaperClock(stamp_path=tmp_path / "stamp.json")
        clock._sharpe_tracker.__init__(target_n=5, target_sharpe=0.5, annualise=252)
        rng = __import__("numpy").random.default_rng(0)
        for r in rng.normal(0.05, 0.001, 5):
            clock.record_fill(float(r))
        snap = clock.sharpe_status()
        assert snap["gate_passed"] is True

    def test_status_includes_sharpe_progress(self, tmp_path):
        clock = self._make_clock(tmp_path)
        clock.record_fill(0.01)
        st = clock.status()
        assert "sharpe_progress" in st
        assert st["sharpe_progress"]["n_trades"] == 1

    def test_status_sharpe_progress_present_when_not_started(self, tmp_path):
        """sharpe_progress key must appear even when the clock has no stamp."""
        clock = self._make_clock(tmp_path)
        st = clock.status()
        assert "sharpe_progress" in st

    def test_prometheus_gauges_updated_on_fill(self, tmp_path):
        """Prometheus gauges are called without raising."""
        clock = self._make_clock(tmp_path)
        mock_gauge = MagicMock()
        with (
            patch("core.metrics.SHARPE_N_TRADES", mock_gauge),
            patch("core.metrics.SHARPE_RATIO", mock_gauge),
            patch("core.metrics.SHARPE_GATE_PASSED", mock_gauge),
        ):
            clock.record_fill(0.01)
        # set() should have been called at least once per gauge
        assert mock_gauge.set.call_count >= 1

    def test_record_fill_returns_empty_when_tracker_none(self, tmp_path):
        clock = self._make_clock(tmp_path)
        clock._sharpe_tracker = None
        result = clock.record_fill(0.01)
        assert result == {}

    def test_sharpe_status_returns_unavailable_when_tracker_none(self, tmp_path):
        clock = self._make_clock(tmp_path)
        clock._sharpe_tracker = None
        snap = clock.sharpe_status()
        assert snap["available"] is False

    def test_pct_to_gate_increases_with_fills(self, tmp_path):
        clock = self._make_clock(tmp_path)
        s1 = clock.record_fill(0.01)
        s2 = clock.record_fill(0.01)
        assert s2["pct_to_gate"] >= s1["pct_to_gate"]

    def test_record_fill_logs_structured_message(self, tmp_path, caplog):
        import logging

        clock = self._make_clock(tmp_path)
        with caplog.at_level(logging.INFO, logger="brokers.oanda_paper_clock"):
            clock.record_fill(0.012, symbol="EUR_USD")
        assert any("EUR_USD" in r.message for r in caplog.records)
