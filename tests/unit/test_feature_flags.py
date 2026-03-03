"""
Tests for config/feature_flags.py
"""

import os
import pytest
from unittest.mock import patch

from config.feature_flags import FeatureFlags, FeatureStatus, flags


@pytest.mark.unit
class TestFeatureStatus:
    """Tests for the FeatureStatus enum."""

    def test_values(self):
        assert FeatureStatus.STABLE == "stable"
        assert FeatureStatus.BETA == "beta"
        assert FeatureStatus.EXPERIMENTAL == "experimental"
        assert FeatureStatus.DISABLED == "disabled"

    def test_all_statuses_present(self):
        statuses = {s.value for s in FeatureStatus}
        assert statuses == {"stable", "beta", "experimental", "disabled"}


@pytest.mark.unit
class TestFeatureFlags:
    """Tests for the FeatureFlags class."""

    # ── defaults ─────────────────────────────────────────────────────────

    def test_stable_features_on_by_default(self):
        """All STABLE-status features must be enabled when no env vars are set.

        LIVE_TRADING is explicitly excluded: it is STABLE in implementation
        but intentionally off by default as a safety guard.
        """
        ff = FeatureFlags()
        reg = ff.registry()
        safety_exceptions = {"LIVE_TRADING"}
        for name, info in reg.items():
            if info["status"] == FeatureStatus.STABLE.value and name not in safety_exceptions:
                assert info["default"] is True, (
                    f"STABLE feature {name} should default to True"
                )

    def test_experimental_features_off_by_default(self):
        """All EXPERIMENTAL features must be disabled when no env vars are set."""
        ff = FeatureFlags()
        reg = ff.registry()
        for name, info in reg.items():
            if info["status"] == FeatureStatus.EXPERIMENTAL.value:
                assert info["default"] is False, (
                    f"EXPERIMENTAL feature {name} should default to False"
                )

    def test_live_trading_off_by_default(self):
        """LIVE_TRADING is a special case — STABLE but off by default for safety."""
        ff = FeatureFlags()
        assert ff.LIVE_TRADING is False

    def test_paper_trading_on_by_default(self):
        ff = FeatureFlags()
        assert ff.PAPER_TRADING is True

    def test_risk_manager_on_by_default(self):
        ff = FeatureFlags()
        assert ff.RISK_MANAGER is True

    # ── env-var overrides ─────────────────────────────────────────────────

    def test_env_var_enables_experimental_feature(self):
        """Setting env-var to 'true' enables an experimental feature."""
        with patch.dict(os.environ, {"FEATURE_ML_PREDICTIONS": "true"}):
            ff = FeatureFlags()
            assert ff.ML_PREDICTIONS is True

    def test_env_var_disables_stable_feature(self):
        """Setting env-var to 'false' disables a normally-on stable feature."""
        with patch.dict(os.environ, {"FEATURE_BACKTESTING": "false"}):
            ff = FeatureFlags()
            assert ff.BACKTESTING is False

    def test_env_var_false_variants(self):
        """All falsy string variants disable a feature."""
        for falsy in ("0", "false", "no", "off", "FALSE", "No", "OFF"):
            with patch.dict(os.environ, {"FEATURE_BACKTESTING": falsy}):
                ff = FeatureFlags()
                assert ff.BACKTESTING is False, (
                    f"Expected BACKTESTING=False for env value '{falsy}'"
                )

    def test_env_var_truthy_variants(self):
        """Non-falsy strings enable a feature."""
        for truthy in ("1", "true", "yes", "on", "True", "YES"):
            with patch.dict(os.environ, {"FEATURE_ML_PREDICTIONS": truthy}):
                ff = FeatureFlags()
                assert ff.ML_PREDICTIONS is True, (
                    f"Expected ML_PREDICTIONS=True for env value '{truthy}'"
                )

    def test_global_flags_singleton_uses_live_env(self):
        """The module-level `flags` singleton reads from the live environment."""
        with patch.dict(os.environ, {"FEATURE_REPLAY": "true"}):
            assert flags.REPLAY_ENGINE is True
        # Back to default after context exits
        assert flags.REPLAY_ENGINE is False

    # ── registry ──────────────────────────────────────────────────────────

    def test_registry_returns_dict(self):
        ff = FeatureFlags()
        reg = ff.registry()
        assert isinstance(reg, dict)
        assert len(reg) > 0

    def test_registry_entry_has_required_keys(self):
        ff = FeatureFlags()
        for name, info in ff.registry().items():
            assert "name" in info, f"{name} missing 'name'"
            assert "env_var" in info, f"{name} missing 'env_var'"
            assert "enabled" in info, f"{name} missing 'enabled'"
            assert "default" in info, f"{name} missing 'default'"
            assert "status" in info, f"{name} missing 'status'"
            assert "description" in info, f"{name} missing 'description'"

    def test_registry_env_var_names_are_unique(self):
        ff = FeatureFlags()
        env_vars = [info["env_var"] for info in ff.registry().values()]
        assert len(env_vars) == len(set(env_vars)), "Duplicate env_var names found"

    def test_registry_all_statuses_valid(self):
        ff = FeatureFlags()
        valid_statuses = {s.value for s in FeatureStatus}
        for name, info in ff.registry().items():
            assert info["status"] in valid_statuses, (
                f"{name} has invalid status '{info['status']}'"
            )

    def test_registry_env_var_prefix(self):
        """Every env-var in the registry must start with FEATURE_."""
        ff = FeatureFlags()
        for name, info in ff.registry().items():
            assert info["env_var"].startswith("FEATURE_"), (
                f"{name}: env_var '{info['env_var']}' must start with FEATURE_"
            )

    # ── enabled / disabled helpers ────────────────────────────────────────

    def test_enabled_features_returns_list(self):
        ff = FeatureFlags()
        enabled = ff.enabled_features()
        assert isinstance(enabled, list)
        assert len(enabled) > 0

    def test_disabled_features_returns_list(self):
        ff = FeatureFlags()
        disabled = ff.disabled_features()
        assert isinstance(disabled, list)

    def test_enabled_and_disabled_are_disjoint(self):
        ff = FeatureFlags()
        enabled = set(ff.enabled_features())
        disabled = set(ff.disabled_features())
        assert enabled.isdisjoint(disabled)

    def test_enabled_plus_disabled_covers_all(self):
        ff = FeatureFlags()
        all_flags = set(ff.registry().keys())
        covered = set(ff.enabled_features()) | set(ff.disabled_features())
        assert covered == all_flags

    # ── well-known flags exist ────────────────────────────────────────────

    def test_key_flags_exist_in_registry(self):
        ff = FeatureFlags()
        reg = ff.registry()
        for expected in (
            "STRATEGY_MANAGER",
            "PAPER_TRADING",
            "LIVE_TRADING",
            "RISK_MANAGER",
            "ORDER_FLOW_DASHBOARD",
            "BACKTESTING",
            "ADMIN_DASHBOARD",
            "ML_PREDICTIONS",
            "RESEARCH_MODULE",
            "EXPLAINABILITY",
        ):
            assert expected in reg, f"Expected flag '{expected}' in registry"

    def test_attribute_access_matches_registry(self):
        """Direct attribute access must return the same value as registry lookup."""
        ff = FeatureFlags()
        reg = ff.registry()
        assert ff.ORDER_FLOW_DASHBOARD == reg["ORDER_FLOW_DASHBOARD"]["enabled"]
        assert ff.BACKTESTING == reg["BACKTESTING"]["enabled"]
        assert ff.ML_PREDICTIONS == reg["ML_PREDICTIONS"]["enabled"]

    # ── log_summary smoke test ────────────────────────────────────────────

    def test_log_summary_does_not_raise(self, caplog):
        ff = FeatureFlags()
        import logging
        with caplog.at_level(logging.INFO, logger="config.feature_flags"):
            ff.log_summary()
        # Just check it doesn't raise and produces some output
        assert len(caplog.records) >= 1
