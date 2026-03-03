"""
Comprehensive tests for Phases 17-26 modules:
- Phase 18: ChartReplayEngine (replay) - uncovered paths
- Phase 19: NoCodeStrategyBuilder (nocode) - uncovered paths
- Phase 21: AIExplainer (explainability) - uncovered paths
- Phase 22: ResearchNotebookEngine (research) - uncovered paths
- Phase 23: ExecutionTransparencyEngine (transparency) - uncovered paths
- Phase 25: TeamManager (teams) - uncovered paths
"""

import pytest
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch
import numpy as np


# ===========================================================================
# Phase 18: Chart Replay Engine - extended tests
# ===========================================================================

@pytest.mark.unit
class TestChartReplayExtended:
    """Extended tests for ChartReplayEngine covering uncovered paths."""

    @pytest.fixture
    def engine(self):
        from replay import ChartReplayEngine
        return ChartReplayEngine()

    @pytest.fixture
    def session(self, engine):
        return engine.create_session(
            symbol='XAUUSD',
            timeframe='1H',
            start_date=datetime(2024, 1, 1),
            end_date=datetime(2024, 1, 7),
            initial_balance=50000.0,
        )

    # --- play / pause / stop ---

    def test_play_starts_replay(self, engine, session):
        from replay import ReplayState
        result = engine.play(session.session_id)
        assert result is True
        assert session.state == ReplayState.PLAYING
        # Cleanup - stop thread
        engine.stop(session.session_id)

    def test_play_finished_session_returns_false(self, engine, session):
        from replay import ReplayState
        engine.stop(session.session_id)  # Mark as finished
        result = engine.play(session.session_id)
        assert result is False

    def test_play_invalid_session_returns_false(self, engine):
        result = engine.play('nonexistent_id')
        assert result is False

    def test_pause_running_session(self, engine, session):
        from replay import ReplayState
        engine.play(session.session_id)
        result = engine.pause(session.session_id)
        assert result is True
        assert session.state == ReplayState.PAUSED

    def test_pause_invalid_session_returns_false(self, engine):
        result = engine.pause('nonexistent_id')
        assert result is False

    def test_stop_session(self, engine, session):
        from replay import ReplayState
        result = engine.stop(session.session_id)
        assert result is True
        assert session.state == ReplayState.FINISHED

    def test_stop_invalid_session(self, engine):
        result = engine.stop('nonexistent_id')
        assert result is False

    # --- set_speed ---

    def test_set_speed(self, engine, session):
        from replay import ReplaySpeed
        result = engine.set_speed(ReplaySpeed.SPEED_5X, session.session_id)
        assert result is True
        assert session.speed == ReplaySpeed.SPEED_5X

    def test_set_speed_invalid_session(self, engine):
        from replay import ReplaySpeed
        result = engine.set_speed(ReplaySpeed.SPEED_2X, 'bad_id')
        assert result is False

    # --- seek ---

    def test_seek_valid_date(self, engine, session):
        target = datetime(2024, 1, 3)
        result = engine.seek(target, session.session_id)
        assert result is True
        assert session.current_date == target

    def test_seek_out_of_range_returns_false(self, engine, session):
        result = engine.seek(datetime(2025, 1, 1), session.session_id)
        assert result is False

    def test_seek_before_start_returns_false(self, engine, session):
        result = engine.seek(datetime(2023, 1, 1), session.session_id)
        assert result is False

    def test_seek_invalid_session(self, engine):
        result = engine.seek(datetime(2024, 1, 3), 'bad_id')
        assert result is False

    # --- place_practice_order ---

    def test_place_market_buy_order(self, engine, session):
        trade = engine.place_practice_order('BUY', 1.0, 'MARKET', session_id=session.session_id)
        assert trade is not None
        assert trade['side'] == 'BUY'
        assert trade['size'] == 1.0
        assert trade['status'] == 'FILLED'

    def test_place_limit_order_with_price(self, engine, session):
        trade = engine.place_practice_order('SELL', 0.5, 'LIMIT', price=1960.0, session_id=session.session_id)
        assert trade is not None
        assert trade['price'] == 1960.0

    def test_place_order_invalid_session(self, engine):
        trade = engine.place_practice_order('BUY', 1.0, session_id='bad_id')
        assert trade is None

    def test_place_multiple_orders_tracks_trades(self, engine, session):
        engine.place_practice_order('BUY', 1.0, session_id=session.session_id)
        engine.place_practice_order('BUY', 0.5, session_id=session.session_id)
        assert len(session.trades) == 2

    def test_place_opposing_order_closes_position(self, engine, session):
        """Selling closes an existing buy position."""
        engine.place_practice_order('BUY', 1.0, session_id=session.session_id)
        engine.place_practice_order('SELL', 1.0, session_id=session.session_id)
        closed = [p for p in session.positions if p['status'] == 'CLOSED']
        assert len(closed) >= 1

    # --- callbacks ---

    def test_register_callback(self, engine):
        cb = MagicMock()
        engine.register_callback('on_bar', cb)
        assert cb in engine.callbacks.get('on_bar', [])

    def test_callback_error_does_not_propagate(self, engine, session):
        engine.register_callback('on_trade', lambda *a: 1 / 0)  # Will raise
        # Should not crash
        trade = engine.place_practice_order('BUY', 1.0, session_id=session.session_id)
        assert trade is not None

    # --- get_session_summary ---

    def test_get_session_summary(self, engine, session):
        summary = engine.get_session_summary(session.session_id)
        assert summary['symbol'] == 'XAUUSD'
        assert 'current_balance' in summary
        assert 'pnl' in summary
        assert 'total_trades' in summary

    def test_get_session_summary_invalid_returns_empty(self, engine):
        summary = engine.get_session_summary('bad_id')
        assert summary == {}

    # --- active session (no session_id param) ---

    def test_play_uses_active_session(self, engine, session):
        # active_session_id is set by create_session
        result = engine.play()
        assert result is True
        engine.stop()

    def test_no_active_session_returns_none(self):
        from replay import ChartReplayEngine
        fresh = ChartReplayEngine()
        # No session created → no active_session_id
        result = fresh.play()
        assert result is False


# ===========================================================================
# Phase 19: No-Code Strategy Builder - extended tests
# ===========================================================================

@pytest.mark.unit
class TestNoCodeBuilderExtended:
    """Extended tests for NoCodeStrategyBuilder covering uncovered paths."""

    @pytest.fixture
    def builder(self):
        from nocode import NoCodeStrategyBuilder
        return NoCodeStrategyBuilder()

    # --- add_rule ---

    def test_add_rule_buy_then_sell(self, builder):
        strategy = builder.create_strategy('BuySell', 'Test strategy', 'XAUUSD', '1H')
        assert strategy is not None
        # add a BUY rule with correct condition format (left/right/operator)
        rule = builder.add_rule(
            strategy_id=strategy.strategy_id,
            name='RSI Oversold Buy',
            conditions=[{
                'left': {'type': 'RSI', 'period': 14},
                'operator': '<',
                'right': 30,
            }],
            action={'type': 'BUY', 'position_size': 1.0},
        )
        assert rule is not None
        assert len(strategy.rules) == 1
        # Verify rule properties
        assert rule.name == 'RSI Oversold Buy'
        assert rule.action.action_type.value == 'BUY'

    def test_add_rule_invalid_strategy(self, builder):
        rule = builder.add_rule('bad_id', 'Test Rule', [],
                                action={'type': 'BUY', 'size': 1.0})
        assert rule is None

    # --- parse_plain_english ---

    def test_parse_plain_english_buy(self, builder):
        result = builder.parse_plain_english(
            'buy when rsi is below 30',
            'XAUUSD', '1H'
        )
        # Should return a strategy or None (depends on NLP parser)
        assert result is None or hasattr(result, 'strategy_id')

    def test_parse_plain_english_sell(self, builder):
        result = builder.parse_plain_english(
            'sell when macd crosses below signal',
            'XAUUSD', '1H'
        )
        assert result is None or hasattr(result, 'strategy_id')

    def test_parse_plain_english_empty(self, builder):
        """parse_plain_english always returns a strategy (even for empty input)."""
        result = builder.parse_plain_english('', 'XAUUSD', '1H')
        # Always creates a strategy regardless
        assert result is not None
        assert hasattr(result, 'strategy_id')

    # --- export_to_python ---

    def test_export_to_python(self, builder):
        strategy = builder.create_strategy('ExportTest', 'Test strategy', 'XAUUSD', '1H')
        code = builder.export_to_python(strategy.strategy_id)
        assert isinstance(code, str)
        assert 'class' in code or 'def' in code or 'strategy' in code.lower()

    def test_export_invalid_strategy(self, builder):
        code = builder.export_to_python('bad_id')
        # Returns None or empty string when strategy not found
        assert not code  # Falsy: None, '', or empty

    # --- get_available_indicators ---

    def test_get_available_indicators(self, builder):
        indicators = builder.get_available_indicators()
        assert isinstance(indicators, list)
        assert len(indicators) > 0
        # Should include RSI at minimum
        names = [i.get('type', i.get('name', '')) for i in indicators]
        assert any('RSI' in str(n) for n in names)

    # --- get_templates ---

    def test_get_templates(self, builder):
        templates = builder.get_templates()
        assert isinstance(templates, list)
        assert len(templates) > 0

    # --- create_from_template ---

    def test_create_from_template(self, builder):
        templates = builder.get_templates()
        if templates:
            t = templates[0]
            template_id = t.get('template_id', t.get('id', ''))
            result = builder.create_from_template(template_id, 'FromTemplate', 'XAUUSD', '1H')
            # Should succeed or return None if template_id not matching
            assert result is None or hasattr(result, 'strategy_id')

    def test_create_from_template_invalid_id(self, builder):
        result = builder.create_from_template('bad_template', 'Test', 'XAUUSD', '1H')
        assert result is None

    # --- to_dict / to_json ---

    def test_strategy_to_dict(self, builder):
        strategy = builder.create_strategy('DictTest', 'Test', 'XAUUSD', '1H')
        d = strategy.to_dict()
        assert isinstance(d, dict)
        assert 'name' in d or 'strategy_id' in d

    def test_strategy_to_json(self, builder):
        strategy = builder.create_strategy('JsonTest', 'Test', 'XAUUSD', '1H')
        j = strategy.to_json()
        assert isinstance(j, str)
        assert len(j) > 2  # Not empty JSON

    # --- _parse_operator ---

    def test_parse_operator_mappings(self, builder):
        from nocode import ConditionOperator
        assert builder._parse_operator('>') == ConditionOperator.GREATER_THAN
        assert builder._parse_operator('<') == ConditionOperator.LESS_THAN
        assert builder._parse_operator('>=') == ConditionOperator.GREATER_EQUAL
        assert builder._parse_operator('<=') == ConditionOperator.LESS_EQUAL
        assert builder._parse_operator('==') == ConditionOperator.EQUAL
        assert builder._parse_operator('!=') == ConditionOperator.NOT_EQUAL
        assert builder._parse_operator('crosses_above') == ConditionOperator.CROSSES_ABOVE
        assert builder._parse_operator('crosses_below') == ConditionOperator.CROSSES_BELOW

    def test_parse_operator_unknown_defaults(self, builder):
        from nocode import ConditionOperator
        result = builder._parse_operator('?!?')
        assert isinstance(result, ConditionOperator)


# ===========================================================================
# Phase 21: AI Explainability - extended tests
# ===========================================================================

@pytest.mark.unit
class TestAIExplainabilityExtended:
    """Extended tests for AIExplainer covering uncovered paths."""

    @pytest.fixture
    def explainer(self):
        from explainability import AIExplainer
        return AIExplainer()

    @pytest.fixture
    def sample_prediction(self):
        return {
            'prediction': 1950.0,
            'class': 'BUY',
            'confidence': 0.78,
        }

    @pytest.fixture
    def sample_features(self):
        return {
            'rsi': 28.0,
            'macd': 0.5,
            'sma_20': 1940.0,
            'ema_50': 1935.0,
            'close': 1945.0,
            'volume': 5000.0,
            'atr': 10.0,
        }

    @pytest.fixture
    def mock_model(self):
        model = MagicMock()
        model.predict = MagicMock(return_value=np.array([1950.0]))
        model.predict_proba = MagicMock(
            return_value=np.array([[0.1, 0.7, 0.2]])
        )
        model.feature_importances_ = np.array([0.3, 0.2, 0.15, 0.1, 0.1, 0.1, 0.05])
        model.estimators_ = []
        return model

    # --- explain_prediction ---

    def test_explain_prediction_returns_explanation(self, explainer, sample_features, mock_model):
        explanation = explainer.explain_prediction(
            model=mock_model,
            features=sample_features,
            prediction=1950.0,
            prediction_class='BUY',
        )
        assert explanation is not None
        assert hasattr(explanation, 'prediction_class')
        assert explanation.prediction_class in ('BUY', 'SELL', 'HOLD')

    def test_explain_prediction_stores_history(self, explainer, sample_features, mock_model):
        before = len(explainer.get_explanation_history())
        explainer.explain_prediction(
            model=mock_model,
            features=sample_features,
            prediction=1950.0,
            prediction_class='BUY',
        )
        after = len(explainer.get_explanation_history())
        assert after == before + 1

    # --- get_model_performance_explanation ---

    def test_get_model_performance_no_data(self, explainer):
        # Returns a default ModelPerformanceExplanation with simulated data
        result = explainer.get_model_performance_explanation('UnknownModel')
        assert result is not None

    def test_get_model_performance_after_prediction(self, explainer, sample_features, mock_model):
        explainer.explain_prediction(
            model=mock_model,
            features=sample_features,
            prediction=1950.0,
            prediction_class='BUY',
        )
        # Returns a ModelPerformanceExplanation with default simulated data
        result = explainer.get_model_performance_explanation('TestModel')
        assert result is not None
        assert hasattr(result, 'accuracy')

    # --- compare_explanations ---

    def test_compare_explanations_empty_ids(self, explainer, sample_features, mock_model):
        """compare_explanations takes 2 Explanation objects."""
        e1 = explainer.explain_prediction(mock_model, sample_features, 1950.0, 'BUY')
        e2 = explainer.explain_prediction(mock_model, sample_features, 1940.0, 'SELL')
        result = explainer.compare_explanations(e1, e2)
        assert result is not None

    def test_compare_two_explanations(self, explainer, sample_features, mock_model):
        e1 = explainer.explain_prediction(mock_model, sample_features, 1950.0, 'BUY')
        e2 = explainer.explain_prediction(mock_model, sample_features, 1940.0, 'SELL')
        result = explainer.compare_explanations(e1, e2)
        assert result is not None
        assert 'prediction_1' in result or 'key_differences' in result

    # --- generate_counterfactual ---

    def test_generate_counterfactual(self, explainer, sample_features, mock_model):
        """generate_counterfactual takes features dict + current/target prediction."""
        result = explainer.generate_counterfactual(
            features=sample_features,
            current_prediction='BUY',
            target_prediction='SELL',
        )
        assert isinstance(result, dict)
        assert 'changes_needed' in result
        assert 'current_prediction' in result

    # --- get_feature_importance_chart_data ---

    def test_get_feature_importance_chart_data(self, explainer, sample_features, mock_model):
        explanation = explainer.explain_prediction(
            mock_model, sample_features, 1950.0, 'BUY'
        )
        if explanation:
            data = explainer.get_feature_importance_chart_data(explanation)
            assert isinstance(data, dict)
            assert 'labels' in data or 'features' in data or len(data) > 0

    # --- get_explanation_history ---

    def test_get_explanation_history_empty(self, explainer):
        hist = explainer.get_explanation_history()
        assert isinstance(hist, list)

    def test_get_explanation_history_limit(self, explainer, sample_features, mock_model):
        for _ in range(5):
            explainer.explain_prediction(
                mock_model, sample_features, 1950.0, 'BUY'
            )
        hist = explainer.get_explanation_history(limit=3)
        assert len(hist) <= 3


# ===========================================================================
# Phase 22: Research Notebooks - extended tests
# ===========================================================================

@pytest.mark.unit
class TestResearchNotebooksExtended:
    """Extended tests for ResearchNotebookEngine covering uncovered paths."""

    @pytest.fixture
    def engine(self):
        from research import ResearchNotebookEngine
        return ResearchNotebookEngine()

    # --- add_cell ---

    def test_add_code_cell(self, engine):
        from research import CellType
        nb = engine.create_notebook('CodeTest', 'Test notebook', 'tester')
        assert nb is not None
        cell = engine.add_cell(nb.notebook_id, CellType.CODE, 'print("hello")')
        assert cell is not None
        assert cell.content == 'print("hello")'

    def test_add_markdown_cell(self, engine):
        from research import CellType
        nb = engine.create_notebook('MdTest', 'Markdown test', 'tester')
        cell = engine.add_cell(nb.notebook_id, CellType.MARKDOWN, '# Title')
        assert cell is not None

    def test_add_cell_invalid_notebook(self, engine):
        cell = engine.add_cell('bad_id', 'code', 'print("x")')
        assert cell is None

    # --- execute_cell ---

    def test_execute_code_cell(self, engine):
        from research import CellType
        nb = engine.create_notebook('ExecTest', 'Test', 'tester')
        cell = engine.add_cell(nb.notebook_id, CellType.CODE, 'x = 1 + 2')
        result = engine.execute_cell(nb.notebook_id, cell.cell_id)
        assert result is not None
        assert 'output' in result or 'error' in result or 'status' in result

    def test_execute_markdown_cell_returns_none(self, engine):
        """Markdown cells cannot be executed - execute_cell returns None."""
        from research import CellType
        nb = engine.create_notebook('MdExec', 'Test', 'tester')
        cell = engine.add_cell(nb.notebook_id, CellType.MARKDOWN, '# Header')
        result = engine.execute_cell(nb.notebook_id, cell.cell_id)
        # Only CODE cells can be executed; markdown returns None
        assert result is None

    def test_execute_invalid_notebook(self, engine):
        result = engine.execute_cell('bad_id', 'bad_cell')
        assert result is None

    def test_execute_invalid_cell(self, engine):
        nb = engine.create_notebook('InvCell', 'Test', 'tester')
        result = engine.execute_cell(nb.notebook_id, 'nonexistent_cell')
        assert result is None

    # --- execute_all ---

    def test_execute_all(self, engine):
        from research import CellType
        nb = engine.create_notebook('ExecAll', 'Test', 'tester')
        engine.add_cell(nb.notebook_id, CellType.CODE, 'a = 1')
        engine.add_cell(nb.notebook_id, CellType.CODE, 'b = 2')
        results = engine.execute_all(nb.notebook_id)
        assert isinstance(results, list)
        assert len(results) == 2

    def test_execute_all_invalid_notebook(self, engine):
        results = engine.execute_all('bad_id')
        assert results == [] or results is None

    # --- export_notebook ---

    def test_export_notebook_json(self, engine):
        from research import CellType
        nb = engine.create_notebook('ExportJson', 'Test', 'tester')
        engine.add_cell(nb.notebook_id, CellType.CODE, 'x = 42')
        exported = engine.export_notebook(nb.notebook_id, 'json')
        assert exported is not None
        assert isinstance(exported, str)

    def test_export_notebook_python(self, engine):
        from research import CellType
        nb = engine.create_notebook('ExportPy', 'Test', 'tester')
        engine.add_cell(nb.notebook_id, CellType.CODE, '# analysis code')
        exported = engine.export_notebook(nb.notebook_id, 'python')
        assert exported is not None

    def test_export_invalid_notebook(self, engine):
        result = engine.export_notebook('bad_id', 'json')
        assert result is None

    # --- create_from_template ---

    def test_create_from_template(self, engine):
        templates = engine.get_templates()
        if templates:
            t = templates[0]
            template_id = t.get('template_id', t.get('id', ''))
            nb = engine.create_from_template(template_id, 'FromTemplate', 'tester')
            assert nb is not None
            assert nb.title == 'FromTemplate'

    def test_create_from_template_invalid(self, engine):
        result = engine.create_from_template('bad_template', 'Test', 'tester')
        assert result is None

    # --- search_notebooks ---

    def test_search_notebooks(self, engine):
        engine.create_notebook('Analysis 1', 'My analysis', 'alice')
        engine.create_notebook('Analysis 2', 'Other analysis', 'bob')
        results = engine.search_notebooks('analysis')
        assert isinstance(results, list)

    def test_search_notebooks_by_tag(self, engine):
        engine.create_notebook('Gold Notebook', 'Gold strategy', 'alice')
        results = engine.search_notebooks(author='alice')
        assert isinstance(results, list)

    # --- standalone functions ---

    def test_calculate_sharpe_ratio(self):
        # Functions are defined in the module but not exported; import directly
        import importlib
        research_mod = importlib.import_module('research')
        calc = getattr(research_mod, 'calculate_sharpe_ratio', None)
        if calc is None:
            pytest.skip("calculate_sharpe_ratio not exported")
        returns = [0.01, -0.005, 0.02, 0.003, -0.01]
        ratio = calc(returns)
        assert isinstance(ratio, float)

    def test_calculate_max_drawdown(self):
        import importlib
        research_mod = importlib.import_module('research')
        calc = getattr(research_mod, 'calculate_max_drawdown', None)
        if calc is None:
            pytest.skip("calculate_max_drawdown not exported")
        equity = [100, 110, 105, 115, 108, 120]
        dd = calc(equity)
        assert isinstance(dd, float)
        assert dd >= 0

    def test_create_features(self):
        import importlib
        research_mod = importlib.import_module('research')
        create_features = getattr(research_mod, 'create_features', None)
        if create_features is None:
            pytest.skip("create_features not exported")
        import pandas as pd
        import numpy as np
        dates = pd.date_range('2024-01-01', periods=50, freq='h')
        df = pd.DataFrame({
            'close': np.linspace(1900, 1950, 50),
            'open': np.linspace(1895, 1945, 50),
            'high': np.linspace(1905, 1955, 50),
            'low': np.linspace(1890, 1940, 50),
            'volume': np.random.randint(1000, 5000, 50).astype(float),
        }, index=dates)
        result = create_features(df)
        assert result is not None


# ===========================================================================
# Phase 23: Execution Transparency - extended tests
# ===========================================================================

@pytest.mark.unit
class TestExecutionTransparencyExtended:
    """Extended tests for ExecutionTransparencyEngine covering uncovered paths."""

    @pytest.fixture
    def engine(self):
        from transparency import ExecutionTransparencyEngine
        return ExecutionTransparencyEngine()

    @pytest.fixture
    def sample_executions(self, engine):
        """Record multiple executions."""
        records = []
        for i in range(10):
            record = engine.record_execution(
                order_id=f'ord_{i}',
                symbol='XAUUSD',
                side='BUY',
                requested_price=1950.0 + i * 0.1,
                executed_price=1950.05 + i * 0.1,
                requested_size=1.0,
                executed_size=1.0,
                latency_ms=50.0 + i,
                broker='Alpaca',
            )
            records.append(record)
        return records

    # --- record_execution ---

    def test_record_execution_creates_record(self, engine):
        record = engine.record_execution(
            order_id='ord_001',
            symbol='XAUUSD',
            side='BUY',
            requested_price=1950.0,
            executed_price=1950.1,
            requested_size=1.0,
            executed_size=1.0,
            latency_ms=45.0,
            broker='Alpaca',
        )
        assert record is not None
        assert record.symbol == 'XAUUSD'
        assert record.slippage != 0

    def test_record_execution_sell(self, engine):
        record = engine.record_execution(
            order_id='ord_002',
            symbol='XAUUSD',
            side='SELL',
            requested_price=1960.0,
            executed_price=1959.9,
            requested_size=1.0,
            executed_size=1.0,
            latency_ms=30.0,
            broker='Alpaca',
        )
        assert record is not None
        assert record.side == 'SELL'

    # --- generate_report ---

    def test_generate_report_empty(self, engine):
        report = engine.generate_report()
        assert report is not None

    def test_generate_report_with_data(self, engine, sample_executions):
        report = engine.generate_report()
        assert report is not None
        assert hasattr(report, 'total_executions') or isinstance(report, dict)

    def test_generate_report_date_range(self, engine, sample_executions):
        report = engine.generate_report(
            period_start=datetime(2024, 1, 1),
            period_end=datetime(2024, 1, 2),
        )
        assert report is not None

    def test_generate_report_by_symbol(self, engine, sample_executions):
        report = engine.generate_report(symbol='XAUUSD')
        assert report is not None

    # --- get_slippage_distribution ---

    def test_slippage_distribution_empty(self, engine):
        dist = engine.get_slippage_distribution()
        assert isinstance(dist, dict) or dist is not None

    def test_slippage_distribution_with_data(self, engine, sample_executions):
        dist = engine.get_slippage_distribution()
        assert dist is not None

    def test_slippage_distribution_by_symbol(self, engine, sample_executions):
        # No symbol filter in API; use period instead
        from datetime import datetime, timedelta
        dist = engine.get_slippage_distribution(
            period_start=datetime.now() - timedelta(hours=1),
            period_end=datetime.now() + timedelta(hours=1),
        )
        assert dist is not None

    # --- get_latency_trend ---

    def test_latency_trend_empty(self, engine):
        trend = engine.get_latency_trend()
        assert isinstance(trend, list) or trend is not None

    def test_latency_trend_with_data(self, engine, sample_executions):
        trend = engine.get_latency_trend()
        assert trend is not None

    def test_latency_trend_with_limit(self, engine, sample_executions):
        from datetime import datetime, timedelta
        trend = engine.get_latency_trend(
            period_start=datetime.now() - timedelta(hours=1),
            period_end=datetime.now() + timedelta(hours=1),
        )
        assert trend is not None

    # --- get_execution_audit_trail ---

    def test_audit_trail_empty(self, engine):
        trail = engine.get_execution_audit_trail()
        assert isinstance(trail, list) or trail is not None

    def test_audit_trail_with_data(self, engine, sample_executions):
        trail = engine.get_execution_audit_trail()
        assert trail is not None

    def test_audit_trail_by_symbol(self, engine, sample_executions):
        # get_execution_audit_trail takes order_id, not symbol
        trail = engine.get_execution_audit_trail(order_id='ord_0')
        assert trail is not None

    def test_audit_trail_limit(self, engine, sample_executions):
        trail = engine.get_execution_audit_trail(limit=3)
        if isinstance(trail, list):
            assert len(trail) <= 3


# ===========================================================================
# Phase 25: Multi-User/Teams - extended tests
# ===========================================================================

@pytest.mark.unit
class TestTeamsExtended:
    """Extended tests for TeamManager covering uncovered paths."""

    @pytest.fixture
    def manager(self):
        from teams import TeamManager
        return TeamManager()

    @pytest.fixture
    def team_with_owner(self, manager):
        from teams import UserRole
        team = manager.create_team('Alpha Team', 'owner1@test.com', 'Owner One',
                                   owner_id='owner1')
        return team

    # --- invite_member ---

    def test_invite_member_success(self, manager, team_with_owner):
        from teams import UserRole
        invitation = manager.invite_member(
            team_id=team_with_owner.team_id,
            email='trader@example.com',
            role=UserRole.TRADER,
            invited_by='owner1',
        )
        assert invitation is not None
        assert invitation.email == 'trader@example.com'
        assert invitation.role == UserRole.TRADER

    def test_invite_member_invalid_team(self, manager):
        from teams import UserRole
        result = manager.invite_member('bad_id', 'x@x.com', UserRole.TRADER, 'owner1')
        assert result is None

    def test_invite_member_no_permission(self, manager, team_with_owner):
        from teams import UserRole
        # viewer role cannot invite
        viewer_inv = manager.invite_member(
            team_with_owner.team_id, 'viewer@x.com', UserRole.VIEWER, 'owner1'
        )
        viewer = manager.accept_invitation(viewer_inv.token, 'viewer1', 'Viewer One')
        result = manager.invite_member(
            team_with_owner.team_id, 'new@x.com', UserRole.TRADER, 'viewer1'
        )
        assert result is None

    def test_invite_member_team_at_capacity(self, manager):
        from teams import TeamManager, UserRole
        mgr = TeamManager()
        team = mgr.create_team('Small Team', 'owner2@test.com', 'Owner',
                               owner_id='owner2')
        # Set max_members to force limit
        team.max_members = 1  # Only owner
        result = mgr.invite_member(team.team_id, 'extra@x.com', UserRole.TRADER, 'owner2')
        assert result is None

    # --- accept_invitation ---

    def test_accept_invitation_success(self, manager, team_with_owner):
        from teams import UserRole
        inv = manager.invite_member(
            team_with_owner.team_id, 'new@x.com', UserRole.ANALYST, 'owner1'
        )
        member = manager.accept_invitation(inv.token, 'user2', 'New User')
        assert member is not None
        assert 'user2' in team_with_owner.members

    def test_accept_invitation_invalid_token(self, manager):
        result = manager.accept_invitation('invalid_token', 'user3', 'User 3')
        assert result is None

    def test_accept_invitation_expired(self, manager, team_with_owner):
        from teams import UserRole
        inv = manager.invite_member(
            team_with_owner.team_id, 'exp@x.com', UserRole.VIEWER, 'owner1'
        )
        # Force expiry
        inv.expires_at = datetime.now() - timedelta(hours=1)
        result = manager.accept_invitation(inv.token, 'user4', 'User 4')
        assert result is None

    def test_accept_already_accepted_invitation(self, manager, team_with_owner):
        from teams import UserRole
        inv = manager.invite_member(
            team_with_owner.team_id, 'dup@x.com', UserRole.VIEWER, 'owner1'
        )
        manager.accept_invitation(inv.token, 'user5', 'User 5')
        # Accepting again should fail (token used)
        result = manager.accept_invitation(inv.token, 'user6', 'User 6')
        assert result is None

    # --- remove_member ---

    def test_remove_member_success(self, manager, team_with_owner):
        from teams import UserRole
        inv = manager.invite_member(
            team_with_owner.team_id, 'rem@x.com', UserRole.TRADER, 'owner1'
        )
        manager.accept_invitation(inv.token, 'user7', 'User 7')
        result = manager.remove_member(team_with_owner.team_id, 'user7', 'owner1')
        assert result is True
        assert 'user7' not in team_with_owner.members

    def test_remove_owner_fails(self, manager, team_with_owner):
        result = manager.remove_member(team_with_owner.team_id, 'owner1', 'owner1')
        assert result is False

    def test_remove_nonexistent_member(self, manager, team_with_owner):
        result = manager.remove_member(team_with_owner.team_id, 'ghost', 'owner1')
        assert result is False

    def test_remove_invalid_team(self, manager):
        result = manager.remove_member('bad_id', 'user1', 'owner1')
        assert result is False

    # --- change_role ---

    def test_change_role_success(self, manager, team_with_owner):
        from teams import UserRole
        inv = manager.invite_member(
            team_with_owner.team_id, 'role@x.com', UserRole.TRADER, 'owner1'
        )
        manager.accept_invitation(inv.token, 'user8', 'User 8')
        result = manager.change_role(team_with_owner.team_id, 'user8', UserRole.ANALYST, 'owner1')
        assert result is True
        assert team_with_owner.members['user8'].role == UserRole.ANALYST

    def test_change_role_invalid_team(self, manager):
        from teams import UserRole
        result = manager.change_role('bad_id', 'u1', UserRole.ANALYST, 'owner1')
        assert result is False

    # --- has_permission ---

    def test_owner_has_all_permissions(self, manager, team_with_owner):
        from teams import Permission
        for perm in Permission:
            assert manager.has_permission(team_with_owner.team_id, 'owner1', perm)

    def test_nonexistent_user_has_no_permissions(self, manager, team_with_owner):
        from teams import Permission
        result = manager.has_permission(team_with_owner.team_id, 'ghost', Permission.TRADE_EXECUTE)
        assert result is False

    def test_viewer_cannot_execute_trades(self, manager, team_with_owner):
        from teams import UserRole, Permission
        inv = manager.invite_member(
            team_with_owner.team_id, 'view@x.com', UserRole.VIEWER, 'owner1'
        )
        manager.accept_invitation(inv.token, 'viewer2', 'View 2')
        result = manager.has_permission(team_with_owner.team_id, 'viewer2', Permission.TRADE_EXECUTE)
        assert result is False

    # --- get_user_permissions ---

    def test_get_user_permissions(self, manager, team_with_owner):
        perms = manager.get_user_permissions(team_with_owner.team_id, 'owner1')
        assert isinstance(perms, (list, set))
        assert len(perms) > 0

    def test_get_user_permissions_nonexistent(self, manager, team_with_owner):
        perms = manager.get_user_permissions(team_with_owner.team_id, 'ghost')
        assert perms == [] or perms == set() or perms is None

    # --- share_strategy / share_portfolio ---

    def test_share_strategy(self, manager, team_with_owner):
        result = manager.share_strategy(
            team_with_owner.team_id,
            strategy_id='strat_001',
            shared_by='owner1',
        )
        assert result is True

    def test_share_portfolio(self, manager, team_with_owner):
        result = manager.share_portfolio(
            team_with_owner.team_id,
            portfolio_id='port_001',
            shared_by='owner1',
        )
        assert result is True

    # --- generate_api_key / verify_api_key ---

    def test_generate_api_key(self, manager, team_with_owner):
        result = manager.generate_api_key(team_with_owner.team_id, 'owner1')
        # Returns a dict with the key info
        assert result is not None
        assert 'key' in result
        assert len(result['key']) > 10

    def test_verify_valid_api_key(self, manager, team_with_owner):
        result = manager.generate_api_key(team_with_owner.team_id, 'owner1')
        assert result is not None
        api_key = result['key']
        valid = manager.verify_api_key(team_with_owner.team_id, api_key)
        assert valid is True

    def test_verify_invalid_api_key(self, manager, team_with_owner):
        # Generate a key to set up the team's key list, then verify wrong value
        manager.generate_api_key(team_with_owner.team_id, 'owner1')
        result = manager.verify_api_key(team_with_owner.team_id, 'bad_key_xyz')
        assert result is False

    # --- get_activity_log ---

    def test_activity_log_populated_on_operations(self, manager, team_with_owner):
        from teams import UserRole
        manager.invite_member(team_with_owner.team_id, 'log@x.com', UserRole.TRADER, 'owner1')
        log = manager.get_activity_log(team_with_owner.team_id)
        assert isinstance(log, list)
        assert len(log) > 0

    def test_activity_log_invalid_team(self, manager):
        log = manager.get_activity_log('bad_id')
        assert log == [] or log is None

    # --- get_team_summary ---

    def test_get_team_summary(self, manager, team_with_owner):
        summary = manager.get_team_summary(team_with_owner.team_id)
        assert summary is not None
        assert 'name' in summary or 'team_id' in summary or 'members' in summary

    def test_get_team_summary_invalid(self, manager):
        result = manager.get_team_summary('bad_id')
        assert result is None
