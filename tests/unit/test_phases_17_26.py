"""
Unit tests for Phases 17-26 modules.
"""

import pytest
from datetime import datetime, timedelta


# ==================== Phase 17: Dashboard Tests ====================

@pytest.mark.unit
class TestDashboardService:
    """Test the Dashboard Service."""

    @pytest.fixture
    def dashboard_service(self):
        """Create dashboard service."""
        from dashboard import DashboardService
        return DashboardService()

    def test_dashboard_initialization(self, dashboard_service):
        """Test dashboard initialization."""
        assert dashboard_service is not None
        assert dashboard_service.active_layout_id == "default"

    def test_default_layout_exists(self, dashboard_service):
        """Test default layout is created."""
        layout = dashboard_service.get_active_layout()
        assert layout is not None
        assert layout.name == "Default Trading Dashboard"
        assert len(layout.widgets) > 0

    def test_get_portfolio_summary(self, dashboard_service):
        """Test getting portfolio summary data."""
        from dashboard import DashboardWidgetType
        
        data = dashboard_service.get_widget_data(DashboardWidgetType.PORTFOLIO_SUMMARY)
        assert 'total_balance' in data
        assert 'available_balance' in data
        assert 'unrealized_pnl' in data

    def test_create_custom_layout(self, dashboard_service):
        """Test creating custom layout."""
        from dashboard import DashboardWidget, DashboardWidgetType
        
        widgets = [
            DashboardWidget(
                widget_id="custom_1",
                widget_type=DashboardWidgetType.PERFORMANCE_CHART,
                title="Custom Chart",
                position={"row": 0, "col": 0, "width": 12, "height": 4}
            )
        ]
        
        layout = dashboard_service.create_layout("Custom Layout", widgets)
        assert layout is not None
        assert layout.name == "Custom Layout"


# ==================== Phase 18: Chart Replay Tests ====================

@pytest.mark.unit
class TestChartReplayEngine:
    """Test the Chart Replay Engine."""

    @pytest.fixture
    def replay_engine(self):
        """Create replay engine."""
        from replay import ChartReplayEngine
        return ChartReplayEngine()

    def test_replay_initialization(self, replay_engine):
        """Test replay engine initialization."""
        assert replay_engine is not None
        assert len(replay_engine.sessions) == 0

    def test_create_session(self, replay_engine):
        """Test creating replay session."""
        session = replay_engine.create_session(
            symbol="XAUUSD",
            timeframe="1H",
            start_date=datetime(2024, 1, 1),
            end_date=datetime(2024, 1, 31),
            initial_balance=100000
        )
        
        assert session is not None
        assert session.symbol == "XAUUSD"
        assert session.initial_balance == 100000

    def test_set_speed(self, replay_engine):
        """Test setting replay speed."""
        from replay import ReplaySpeed
        
        session = replay_engine.create_session(
            symbol="XAUUSD",
            timeframe="1H",
            start_date=datetime(2024, 1, 1),
            end_date=datetime(2024, 1, 31)
        )
        
        result = replay_engine.set_speed(ReplaySpeed.SPEED_10X)
        assert result is True
        assert session.speed == ReplaySpeed.SPEED_10X

    def test_get_session_summary(self, replay_engine):
        """Test getting session summary."""
        replay_engine.create_session(
            symbol="XAUUSD",
            timeframe="1H",
            start_date=datetime(2024, 1, 1),
            end_date=datetime(2024, 1, 31)
        )
        
        summary = replay_engine.get_session_summary()
        assert 'session_id' in summary
        assert 'symbol' in summary
        assert 'initial_balance' in summary


# ==================== Phase 19: No-Code Builder Tests ====================

@pytest.mark.unit
class TestNoCodeStrategyBuilder:
    """Test the No-Code Strategy Builder."""

    @pytest.fixture
    def strategy_builder(self):
        """Create strategy builder."""
        from nocode import NoCodeStrategyBuilder
        return NoCodeStrategyBuilder()

    def test_builder_initialization(self, strategy_builder):
        """Test builder initialization."""
        assert strategy_builder is not None
        assert len(strategy_builder.templates) > 0

    def test_create_strategy(self, strategy_builder):
        """Test creating a strategy."""
        strategy = strategy_builder.create_strategy(
            name="Test Strategy",
            description="A test strategy",
            symbol="EURUSD",
            timeframe="1H"
        )
        
        assert strategy is not None
        assert strategy.name == "Test Strategy"
        assert strategy.symbol == "EURUSD"

    def test_add_rule(self, strategy_builder):
        """Test adding a rule to strategy."""
        strategy = strategy_builder.create_strategy(
            name="Test Strategy",
            description="Test",
            symbol="EURUSD",
            timeframe="1H"
        )
        
        rule = strategy_builder.add_rule(
            strategy.strategy_id,
            name="Buy Rule",
            conditions=[
                {
                    'left': {'type': 'RSI', 'period': 14},
                    'operator': '<',
                    'right': 30
                }
            ],
            action={'type': 'BUY', 'position_size': 1.0}
        )
        
        assert rule is not None
        assert rule.name == "Buy Rule"

    def test_get_available_indicators(self, strategy_builder):
        """Test getting available indicators."""
        indicators = strategy_builder.get_available_indicators()
        assert len(indicators) > 0
        assert any(i['type'] == 'RSI' for i in indicators)

    def test_get_templates(self, strategy_builder):
        """Test getting strategy templates."""
        templates = strategy_builder.get_templates()
        assert len(templates) > 0


# ==================== Phase 21: AI Explainability Tests ====================

@pytest.mark.unit
class TestAIExplainer:
    """Test the AI Explainability Engine."""

    @pytest.fixture
    def ai_explainer(self):
        """Create AI explainer."""
        from explainability import AIExplainer
        return AIExplainer()

    def test_explainer_initialization(self, ai_explainer):
        """Test explainer initialization."""
        assert ai_explainer is not None
        assert len(ai_explainer.explanation_history) == 0

    def test_explain_prediction(self, ai_explainer):
        """Test explaining a prediction."""
        # Create mock model
        class MockModel:
            pass
        
        features = {
            'rsi': 25,
            'macd': 0.5,
            'sma_20': 1.1,
            'volume_ratio': 1.2
        }
        
        explanation = ai_explainer.explain_prediction(
            model=MockModel(),
            features=features,
            prediction=0.8,
            prediction_class='BUY'
        )
        
        assert explanation is not None
        assert explanation.prediction_class == 'BUY'
        assert len(explanation.feature_contributions) > 0
        assert explanation.natural_language != ""

    def test_generate_counterfactual(self, ai_explainer):
        """Test generating counterfactual explanation."""
        features = {'rsi': 75, 'macd': -0.5}
        
        counterfactual = ai_explainer.generate_counterfactual(
            features=features,
            current_prediction='SELL',
            target_prediction='BUY'
        )
        
        assert counterfactual is not None
        assert 'changes_needed' in counterfactual


# ==================== Phase 22: Research Notebooks Tests ====================

@pytest.mark.unit
class TestResearchNotebookEngine:
    """Test the Research Notebook Engine."""

    @pytest.fixture
    def notebook_engine(self):
        """Create notebook engine."""
        from research import ResearchNotebookEngine
        return ResearchNotebookEngine()

    def test_engine_initialization(self, notebook_engine):
        """Test engine initialization."""
        assert notebook_engine is not None
        assert len(notebook_engine.templates) > 0

    def test_create_notebook(self, notebook_engine):
        """Test creating a notebook."""
        notebook = notebook_engine.create_notebook(
            title="Test Notebook",
            description="A test notebook",
            author="test_user"
        )
        
        assert notebook is not None
        assert notebook.title == "Test Notebook"
        assert len(notebook.cells) == 0

    def test_add_cell(self, notebook_engine):
        """Test adding cells to notebook."""
        from research import CellType
        
        notebook = notebook_engine.create_notebook(
            title="Test",
            description="Test",
            author="test"
        )
        
        cell = notebook_engine.add_cell(
            notebook.notebook_id,
            CellType.CODE,
            "print('Hello World')"
        )
        
        assert cell is not None
        assert cell.cell_type == CellType.CODE

    def test_create_from_template(self, notebook_engine):
        """Test creating notebook from template."""
        notebook = notebook_engine.create_from_template(
            template_id="strategy_development",
            title="My Strategy",
            author="test_user"
        )
        
        assert notebook is not None
        assert len(notebook.cells) > 0


# ==================== Phase 23: Execution Transparency Tests ====================

@pytest.mark.unit
class TestExecutionTransparencyEngine:
    """Test the Execution Transparency Engine."""

    @pytest.fixture
    def transparency_engine(self):
        """Create transparency engine."""
        from transparency import ExecutionTransparencyEngine
        return ExecutionTransparencyEngine()

    def test_engine_initialization(self, transparency_engine):
        """Test engine initialization."""
        assert transparency_engine is not None
        assert len(transparency_engine.executions) == 0

    def test_record_execution(self, transparency_engine):
        """Test recording an execution."""
        execution = transparency_engine.record_execution(
            order_id="order_1",
            symbol="XAUUSD",
            side="BUY",
            requested_price=1950.00,
            executed_price=1950.05,
            requested_size=1.0,
            executed_size=1.0,
            latency_ms=50,
            broker="TestBroker"
        )
        
        assert execution is not None
        assert execution.symbol == "XAUUSD"
        assert execution.slippage != 0

    def test_generate_report(self, transparency_engine):
        """Test generating execution report."""
        # Record some executions
        for i in range(5):
            transparency_engine.record_execution(
                order_id=f"order_{i}",
                symbol="XAUUSD",
                side="BUY",
                requested_price=1950.00 + i,
                executed_price=1950.00 + i + 0.02,
                requested_size=1.0,
                executed_size=1.0,
                latency_ms=50 + i * 10,
                broker="TestBroker"
            )
        
        report = transparency_engine.generate_report()
        assert report is not None
        assert report.total_executions == 5

    def test_get_slippage_distribution(self, transparency_engine):
        """Test getting slippage distribution."""
        # Record some executions
        transparency_engine.record_execution(
            order_id="order_1",
            symbol="XAUUSD",
            side="BUY",
            requested_price=1950.00,
            executed_price=1950.05,
            requested_size=1.0,
            executed_size=1.0,
            latency_ms=50,
            broker="TestBroker"
        )
        
        distribution = transparency_engine.get_slippage_distribution()
        assert 'buckets' in distribution
        assert 'counts' in distribution


# ==================== Phase 25: Teams Tests ====================

@pytest.mark.unit
class TestTeamManager:
    """Test the Team Manager."""

    @pytest.fixture
    def team_manager(self):
        """Create team manager."""
        from teams import TeamManager
        return TeamManager()

    def test_manager_initialization(self, team_manager):
        """Test manager initialization."""
        assert team_manager is not None
        assert len(team_manager.teams) == 0

    def test_create_team(self, team_manager):
        """Test creating a team."""
        team = team_manager.create_team(
            name="Test Team",
            owner_email="owner@test.com",
            owner_name="Test Owner"
        )
        
        assert team is not None
        assert team.name == "Test Team"
        assert len(team.members) == 1

    def test_invite_member(self, team_manager):
        """Test inviting a team member."""
        from teams import UserRole
        
        team = team_manager.create_team(
            name="Test Team",
            owner_email="owner@test.com",
            owner_name="Test Owner"
        )
        
        invitation = team_manager.invite_member(
            team_id=team.team_id,
            email="member@test.com",
            role=UserRole.TRADER,
            invited_by=team.owner_id
        )
        
        assert invitation is not None
        assert invitation.email == "member@test.com"

    def test_has_permission(self, team_manager):
        """Test permission checking."""
        from teams import Permission
        
        team = team_manager.create_team(
            name="Test Team",
            owner_email="owner@test.com",
            owner_name="Test Owner"
        )
        
        # Owner should have all permissions
        assert team_manager.has_permission(
            team.team_id,
            team.owner_id,
            Permission.TRADE_EXECUTE
        )

    def test_get_team_summary(self, team_manager):
        """Test getting team summary."""
        team = team_manager.create_team(
            name="Test Team",
            owner_email="owner@test.com",
            owner_name="Test Owner"
        )
        
        summary = team_manager.get_team_summary(team.team_id)
        assert summary is not None
        assert summary['name'] == "Test Team"
        assert summary['member_count'] == 1
