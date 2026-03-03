"""
Tests for the 7 experimental modules and their FastAPI router factories.

Verifies that each module:
1. Can be imported without errors
2. Exports a create_*_router() factory function
3. The factory creates a router with the expected URL prefix and at least the
   advertised minimum number of routes
4. Core engine methods work without external dependencies
"""

import os
import pytest
from unittest.mock import patch


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _route_paths(router) -> list:
    return [r.path for r in router.routes]


# ---------------------------------------------------------------------------
# Research module
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestResearchModule:
    def test_imports(self):
        from research import ResearchNotebookEngine, create_research_router
        assert callable(create_research_router)

    def test_router_prefix_and_routes(self):
        from research import ResearchNotebookEngine, create_research_router
        engine = ResearchNotebookEngine()
        router = create_research_router(engine)
        assert router.prefix == "/api/research"
        paths = _route_paths(router)
        assert any("notebooks" in p for p in paths)
        assert any("templates" in p for p in paths)
        assert len(paths) >= 5

    def test_engine_create_notebook(self):
        from research import ResearchNotebookEngine
        engine = ResearchNotebookEngine()
        nb = engine.create_notebook(
            title="Test", description="desc", author="tester"
        )
        assert nb.notebook_id
        assert nb.title == "Test"

    def test_engine_search_notebooks(self):
        from research import ResearchNotebookEngine
        engine = ResearchNotebookEngine()
        engine.create_notebook(title="My NB", description="x", author="a")
        results = engine.search_notebooks(query="My NB")
        assert len(results) >= 1

    def test_engine_get_templates(self):
        from research import ResearchNotebookEngine
        engine = ResearchNotebookEngine()
        templates = engine.get_templates()
        assert isinstance(templates, list)


# ---------------------------------------------------------------------------
# Explainability module
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestExplainabilityModule:
    def test_imports(self):
        from explainability import AIExplainer, create_explainability_router
        assert callable(create_explainability_router)

    def test_router_prefix_and_routes(self):
        from explainability import AIExplainer, create_explainability_router
        explainer = AIExplainer()
        router = create_explainability_router(explainer)
        assert router.prefix == "/api/explainability"
        paths = _route_paths(router)
        assert any("explain" in p for p in paths)
        assert any("history" in p for p in paths)
        assert len(paths) >= 4

    def test_engine_explain_prediction(self):
        from explainability import AIExplainer
        explainer = AIExplainer()
        explanation = explainer.explain_prediction(
            model=None,
            features={"rsi": 55.0, "macd": 0.003, "sma_20": 1900.0},
            prediction=0.75,
            prediction_class="BUY",
        )
        assert explanation.prediction_class == "BUY"
        assert explanation.explanation_id

    def test_engine_explanation_history(self):
        from explainability import AIExplainer
        explainer = AIExplainer()
        explainer.explain_prediction(
            model=None,
            features={"rsi": 50.0},
            prediction=0.6,
            prediction_class="HOLD",
        )
        history = explainer.get_explanation_history(limit=5)
        assert isinstance(history, list)
        assert len(history) >= 1


# ---------------------------------------------------------------------------
# Transparency module
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestTransparencyModule:
    def test_imports(self):
        from transparency import ExecutionTransparencyEngine, create_transparency_router
        assert callable(create_transparency_router)

    def test_router_prefix_and_routes(self):
        from transparency import ExecutionTransparencyEngine, create_transparency_router
        engine = ExecutionTransparencyEngine()
        router = create_transparency_router(engine)
        assert router.prefix == "/api/transparency"
        paths = _route_paths(router)
        assert any("executions" in p for p in paths)
        assert any("report" in p for p in paths)
        assert len(paths) >= 4

    def test_engine_record_execution(self):
        from transparency import ExecutionTransparencyEngine, FOREX_PIP_MULTIPLIER
        engine = ExecutionTransparencyEngine()
        requested = 1950.0
        executed = 1950.5
        record = engine.record_execution(
            order_id="ORD001",
            symbol="XAUUSD",
            side="BUY",
            requested_price=requested,
            executed_price=executed,
            requested_size=0.1,
            executed_size=0.1,
            latency_ms=45.0,
            broker="OANDA",
        )
        assert record.execution_id
        # slippage = (executed - requested) * FOREX_PIP_MULTIPLIER (XAUUSD contains 'USD')
        expected_slippage = (executed - requested) * FOREX_PIP_MULTIPLIER
        assert record.slippage == pytest.approx(expected_slippage, rel=0.01)

    def test_engine_audit_trail(self):
        from transparency import ExecutionTransparencyEngine
        engine = ExecutionTransparencyEngine()
        engine.record_execution(
            order_id="ORD002",
            symbol="XAUUSD",
            side="SELL",
            requested_price=1960.0,
            executed_price=1959.8,
            requested_size=0.2,
            executed_size=0.2,
            latency_ms=30.0,
            broker="OANDA",
        )
        trail = engine.get_execution_audit_trail(limit=10)
        assert isinstance(trail, list)
        assert len(trail) >= 1


# ---------------------------------------------------------------------------
# Teams module
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestTeamsModule:
    def test_imports(self):
        from teams import TeamManager, create_teams_router
        assert callable(create_teams_router)

    def test_router_prefix_and_routes(self):
        from teams import TeamManager, create_teams_router
        manager = TeamManager()
        router = create_teams_router(manager)
        assert router.prefix == "/api/teams"
        paths = _route_paths(router)
        assert any("invite" in p for p in paths)
        assert any("permissions" in p or "members" in p for p in paths)
        assert len(paths) >= 6

    def test_engine_create_team(self):
        from teams import TeamManager
        manager = TeamManager()
        team = manager.create_team(
            name="Alpha Team",
            owner_email="alice@example.com",
            owner_name="Alice",
        )
        assert team.team_id
        assert team.name == "Alpha Team"

    def test_engine_get_team_summary(self):
        from teams import TeamManager
        manager = TeamManager()
        team = manager.create_team(
            name="Beta Team",
            owner_email="bob@example.com",
            owner_name="Bob",
        )
        summary = manager.get_team_summary(team.team_id)
        assert summary is not None
        assert summary["name"] == "Beta Team"
        assert summary["member_count"] >= 1  # Owner is a member

    def test_engine_has_permission(self):
        from teams import TeamManager, Permission
        manager = TeamManager()
        team = manager.create_team(
            name="Gamma Team",
            owner_email="carol@example.com",
            owner_name="Carol",
            owner_id="user_003",
        )
        # Owner should have trade execute permission
        assert manager.has_permission(team.team_id, "user_003", Permission.TRADE_EXECUTE)


# ---------------------------------------------------------------------------
# No-Code Builder module
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestNoCodeModule:
    def test_imports(self):
        from nocode import NoCodeStrategyBuilder, create_nocode_router
        assert callable(create_nocode_router)

    def test_router_prefix_and_routes(self):
        from nocode import NoCodeStrategyBuilder, create_nocode_router
        builder = NoCodeStrategyBuilder()
        router = create_nocode_router(builder)
        assert router.prefix == "/api/nocode"
        paths = _route_paths(router)
        assert any("strategies" in p for p in paths)
        assert any("indicators" in p for p in paths)
        assert len(paths) >= 5

    def test_engine_create_strategy(self):
        from nocode import NoCodeStrategyBuilder
        builder = NoCodeStrategyBuilder()
        strategy = builder.create_strategy(
            name="My RSI Strategy",
            description="Buy when RSI < 30",
            symbol="XAUUSD",
            timeframe="1h",
        )
        assert strategy.strategy_id
        assert strategy.name == "My RSI Strategy"
        assert strategy.symbol == "XAUUSD"

    def test_engine_get_available_indicators(self):
        from nocode import NoCodeStrategyBuilder
        builder = NoCodeStrategyBuilder()
        indicators = builder.get_available_indicators()
        assert isinstance(indicators, list)
        assert len(indicators) > 5

    def test_engine_get_templates(self):
        from nocode import NoCodeStrategyBuilder
        builder = NoCodeStrategyBuilder()
        templates = builder.get_templates()
        assert isinstance(templates, list)

    def test_engine_export_to_python(self):
        from nocode import NoCodeStrategyBuilder
        builder = NoCodeStrategyBuilder()
        strategy = builder.create_strategy(
            name="Export Test",
            description="",
            symbol="XAUUSD",
            timeframe="4h",
        )
        code = builder.export_to_python(strategy.strategy_id)
        assert code is not None
        assert "class" in code or "def" in code or "strategy" in code.lower()


# ---------------------------------------------------------------------------
# Replay Engine module
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestReplayModule:
    def test_imports(self):
        from replay import ChartReplayEngine, create_replay_router
        assert callable(create_replay_router)

    def test_router_prefix_and_routes(self):
        from replay import ChartReplayEngine, create_replay_router
        engine = ChartReplayEngine()
        router = create_replay_router(engine)
        assert router.prefix == "/api/replay"
        paths = _route_paths(router)
        assert any("sessions" in p for p in paths)
        assert any("play" in p for p in paths)
        assert any("pause" in p for p in paths)
        assert len(paths) >= 5

    def test_engine_create_session(self):
        from datetime import datetime
        from replay import ChartReplayEngine
        engine = ChartReplayEngine()
        session = engine.create_session(
            symbol="XAUUSD",
            timeframe="1h",
            start_date=datetime(2024, 1, 1),
            end_date=datetime(2024, 1, 31),
            initial_balance=50000.0,
        )
        assert session.session_id
        assert session.symbol == "XAUUSD"
        assert session.initial_balance == 50000.0

    def test_engine_play_pause_stop(self):
        from datetime import datetime
        from replay import ChartReplayEngine, ReplayState
        engine = ChartReplayEngine()
        session = engine.create_session(
            symbol="EURUSD",
            timeframe="15m",
            start_date=datetime(2024, 6, 1),
            end_date=datetime(2024, 6, 10),
        )
        sid = session.session_id
        assert engine.pause(sid) is True
        assert engine.stop(sid) is True

    def test_engine_get_session_summary(self):
        from datetime import datetime
        from replay import ChartReplayEngine
        engine = ChartReplayEngine()
        session = engine.create_session(
            symbol="XAUUSD",
            timeframe="1d",
            start_date=datetime(2024, 1, 1),
            end_date=datetime(2024, 3, 31),
        )
        summary = engine.get_session_summary(session.session_id)
        assert summary.get("symbol") == "XAUUSD"
        assert "initial_balance" in summary


# ---------------------------------------------------------------------------
# ML module
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestMLModule:
    def test_imports(self):
        from ml import TechnicalFeatureEngineer, create_ml_router
        assert callable(create_ml_router)

    def test_router_prefix_and_routes(self):
        from ml import TechnicalFeatureEngineer, create_ml_router
        engineer = TechnicalFeatureEngineer()
        router = create_ml_router(engineer)
        assert router.prefix == "/api/ml"
        paths = _route_paths(router)
        assert any("status" in p for p in paths)
        assert any("features" in p for p in paths)
        assert len(paths) >= 2

    def test_feature_engineer_create_features(self):
        import pandas as pd
        import numpy as np
        from ml import TechnicalFeatureEngineer

        engineer = TechnicalFeatureEngineer()
        # Generate synthetic OHLCV data (300 bars to avoid NaN-heavy output)
        n = 300
        close = 1900 + np.cumsum(np.random.randn(n)) * 5
        df = pd.DataFrame({
            "open": close - np.random.uniform(1, 5, n),
            "high": close + np.random.uniform(1, 5, n),
            "low": close - np.random.uniform(1, 5, n),
            "close": close,
            "volume": np.random.uniform(1000, 5000, n),
        })
        features_df = engineer.create_features(df)
        assert len(features_df) > 0
        assert len(engineer.feature_names) > 10

    def test_feature_engineer_get_feature_groups(self):
        from ml import TechnicalFeatureEngineer
        engineer = TechnicalFeatureEngineer()
        groups = engineer.get_feature_groups()
        assert isinstance(groups, dict)

    def test_ml_module_exports(self):
        import ml
        for name in ["BaseMLModel", "LSTMPricePredictor", "RandomForestTradingClassifier",
                     "TechnicalFeatureEngineer", "create_ml_router"]:
            assert name in ml.__all__, f"'{name}' missing from ml.__all__"


# ---------------------------------------------------------------------------
# Feature flag integration check
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestFeatureFlagIntegration:
    """Verify the feature flags for experimental modules exist and are wired."""

    def test_all_experimental_flags_exist(self):
        from config.feature_flags import FeatureFlags
        ff = FeatureFlags()
        reg = ff.registry()
        expected = {
            "RESEARCH_MODULE",
            "EXPLAINABILITY",
            "TRANSPARENCY_REPORTS",
            "TEAMS_MODULE",
            "NOCODE_BUILDER",
            "REPLAY_ENGINE",
            "ML_PREDICTIONS",
        }
        for name in expected:
            assert name in reg, f"Feature flag '{name}' missing from registry"

    def test_experimental_flags_off_by_default(self):
        from config.feature_flags import FeatureFlags
        ff = FeatureFlags()
        for name in ("RESEARCH_MODULE", "EXPLAINABILITY", "TRANSPARENCY_REPORTS",
                     "TEAMS_MODULE", "NOCODE_BUILDER", "REPLAY_ENGINE", "ML_PREDICTIONS"):
            assert getattr(ff, name) is False, (
                f"Experimental flag {name} should be off by default"
            )

    def test_env_var_enables_research(self):
        from config.feature_flags import FeatureFlags
        with patch.dict(os.environ, {"FEATURE_RESEARCH": "true"}):
            ff = FeatureFlags()
            assert ff.RESEARCH_MODULE is True

    def test_env_var_enables_ml_predictions(self):
        from config.feature_flags import FeatureFlags
        with patch.dict(os.environ, {"FEATURE_ML_PREDICTIONS": "true"}):
            ff = FeatureFlags()
            assert ff.ML_PREDICTIONS is True

    def test_app_state_has_experimental_attributes(self):
        """app.AppState must declare slots for all experimental engines."""
        import sys
        from unittest.mock import MagicMock, patch
        # Stub heavy optional deps so app.py can be imported in a test environment
        stubs = {
            mod: MagicMock()
            for mod in ("uvicorn", "sqlalchemy", "sqlalchemy.orm")
            if mod not in sys.modules
        }
        with patch.dict(sys.modules, stubs):
            from app import AppState
            state = AppState()
            for attr in ("research_engine", "explainer", "transparency_engine",
                         "teams_manager", "nocode_builder", "replay_engine",
                         "ml_feature_engineer"):
                assert hasattr(state, attr), f"AppState missing attribute '{attr}'"
                assert getattr(state, attr) is None  # None until flag is on
