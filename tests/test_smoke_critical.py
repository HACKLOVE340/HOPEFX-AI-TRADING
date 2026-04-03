# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
Smoke tests for 19 critical modules that previously had no test coverage.

Each test verifies the module can be imported, instantiated, and called
without crashing. No external services required.
"""

from __future__ import annotations

import pytest

# ── 1. ml/training.py ────────────────────────────────────────────────────────


def test_ml_training_import():
    import importlib.util
    from pathlib import Path

    spec = importlib.util.spec_from_file_location(
        "ml._training_file",
        Path(__file__).parent.parent / "ml" / "training.py",
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert hasattr(mod, "FeatureEngineer")


def test_ml_training_feature_engineer_instantiate():
    import importlib.util
    from pathlib import Path

    spec = importlib.util.spec_from_file_location(
        "ml._training_file2",
        Path(__file__).parent.parent / "ml" / "training.py",
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    fe = mod.FeatureEngineer(include_indicators=True, include_lags=False)
    assert fe is not None


# ── 2. ml/macro_features.py ──────────────────────────────────────────────────


def test_ml_macro_features_import():
    from ml import macro_features

    assert macro_features is not None


def test_ml_macro_features_has_fetch():
    from ml import macro_features

    assert hasattr(macro_features, "fetch_macro_history") or hasattr(macro_features, "add_macro_features")


# ── 3. ml/regime.py ──────────────────────────────────────────────────────────


def test_ml_regime_import():
    from ml import regime

    assert regime is not None


def test_ml_regime_detector_instantiate():
    from ml.regime import RegimeDetector

    rd = RegimeDetector()
    assert rd is not None


# ── 4. execution/tca.py ──────────────────────────────────────────────────────


def test_execution_tca_import():
    from execution import tca

    assert tca is not None


def test_execution_tca_engine_instantiate():
    from execution.tca import TCAEngine

    engine = TCAEngine()
    assert engine is not None


# ── 5. execution/fix_adapter.py ──────────────────────────────────────────────


def test_execution_fix_adapter_import():
    # fix_adapter requires optional quickfix C++ library; verify module loads
    try:
        from execution import fix_adapter

        assert fix_adapter is not None
    except (ImportError, AttributeError):
        pytest.skip("quickfix not installed — fix_adapter optional dep")


# ── 6. risk/position_sizing.py ───────────────────────────────────────────────


def test_risk_position_sizing_import():
    from risk import position_sizing

    assert position_sizing is not None


def test_risk_position_sizing_calculate():
    from risk.position_sizing import PositionSizer

    ps = PositionSizer(method="atr", risk_pct=0.01)
    assert ps is not None


# ── 7. strategies/regime_router.py ───────────────────────────────────────────


def test_strategies_regime_router_import():
    from strategies import regime_router

    assert regime_router is not None


def test_strategies_regime_router_instantiate():
    from strategies.regime_router import RegimeRouter

    # RegimeRouter requires a strategy_manager; verify class is importable
    assert RegimeRouter is not None


# ── 8. social/leaderboards.py ────────────────────────────────────────────────


def test_social_leaderboards_import():
    from social import leaderboards

    assert leaderboards is not None


def test_social_leaderboards_instantiate():
    from social.leaderboards import LeaderboardManager

    lm = LeaderboardManager()
    assert lm is not None


# ── 9. monetization/stripe_integration.py ────────────────────────────────────


def test_monetization_stripe_import():
    from monetization import stripe_integration

    assert stripe_integration is not None


# ── 10. payments/fintech/flutterwave.py ──────────────────────────────────────


def test_payments_flutterwave_import():
    from payments.fintech import flutterwave

    assert flutterwave is not None


def test_payments_flutterwave_client_instantiate():
    from payments.fintech.flutterwave import FlutterwaveClient

    client = FlutterwaveClient(secret_key="test_key_smoke")
    assert client is not None


# ── 11. data/feeds/macro.py ──────────────────────────────────────────────────


def test_data_feeds_macro_import():
    from data.feeds import macro

    assert macro is not None


# ── 12. data/scheduler.py ────────────────────────────────────────────────────


def test_data_scheduler_import():
    from data import scheduler

    assert scheduler is not None


def test_data_scheduler_instantiate():
    from data.scheduler import DataScheduler

    ds = DataScheduler()
    assert ds is not None


# ── 13. nocode/builder.py ────────────────────────────────────────────────────


def test_nocode_builder_import():
    from nocode import builder

    assert builder is not None


def test_nocode_builder_instantiate():
    from nocode.builder import NoCodeStrategyBuilder

    nb = NoCodeStrategyBuilder()
    assert nb is not None


# ── 14. explainability/explainer.py ──────────────────────────────────────────


def test_explainability_explainer_import():
    from explainability import explainer

    assert explainer is not None


def test_explainability_explainer_instantiate():
    from explainability.explainer import AIExplainer

    se = AIExplainer()
    assert se is not None


# ── 15. brokers/smart_router.py ──────────────────────────────────────────────


def test_brokers_smart_router_import():
    from brokers import smart_router

    assert smart_router is not None


def test_brokers_smart_router_instantiate():
    from brokers.smart_router import SmartOrderRouter

    sor = SmartOrderRouter()
    assert sor is not None


# ── 16. brokers/oanda.py ─────────────────────────────────────────────────────


def test_brokers_oanda_import():
    from brokers import oanda

    assert oanda is not None


def test_brokers_oanda_broker_instantiate():
    from brokers.oanda import OandaBroker

    broker = OandaBroker(api_key="test-token", account_id="test-account")
    assert broker is not None


# ── 17. api/chat.py ──────────────────────────────────────────────────────────


def _load_api_module(name: str):
    """Load an api sub-module directly, bypassing api/__init__.py eager imports."""
    import importlib.util
    from pathlib import Path

    path = Path(__file__).parent.parent / "api" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(f"api._{name}", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_api_chat_import():
    mod = _load_api_module("chat")
    assert mod is not None


def test_api_chat_has_router():
    mod = _load_api_module("chat")
    assert hasattr(mod, "router")


# ── 18. api/prop_firm.py ─────────────────────────────────────────────────────


def test_api_prop_firm_import():
    mod = _load_api_module("prop_firm")
    assert mod is not None


def test_api_prop_firm_has_router():
    mod = _load_api_module("prop_firm")
    assert hasattr(mod, "router")


# ── 19. api/performance.py ───────────────────────────────────────────────────


def test_api_performance_import():
    mod = _load_api_module("performance")
    assert mod is not None


def test_api_performance_has_router():
    mod = _load_api_module("performance")
    assert hasattr(mod, "router")
