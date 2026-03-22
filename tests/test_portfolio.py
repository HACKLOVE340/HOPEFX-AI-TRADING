import pytest
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from hopefx.portfolio.manager import PortfolioManager

class TestPortfolioManager:
    
    def test_portfolio_construction(self, test_config, sample_market_data):
        """Test portfolio construction with multiple assets."""
        manager = PortfolioManager(test_config)
        
        assets = {
            'XAUUSD': 0.4,
            'EURUSD': 0.3,
            'GBPUSD': 0.2,
            'USDJPY': 0.1
        }
        
        portfolio = manager.create_portfolio(
            name='Test Portfolio',
            assets=assets,
            rebalancing='monthly'
        )
        
        assert portfolio.total_exposure == 1.0
        assert portfolio.asset_count == 4
    
    def test_correlation_matrix(self, test_config):
        """Test correlation calculation between assets."""
        manager = PortfolioManager(test_config)
        
        # Generate correlated returns
        np.random.seed(42)
        returns = pd.DataFrame({
            'XAUUSD': np.random.normal(0.001, 0.02, 100),
            'EURUSD': np.random.normal(0.0005, 0.015, 100),
            'GBPUSD': np.random.normal(0.0008, 0.018, 100)
        })
        
        corr_matrix = manager.calculate_correlation(returns)
        
        assert corr_matrix.shape == (3, 3)
        assert np.allclose(np.diag(corr_matrix), 1.0)
        assert -1 <= corr_matrix.iloc[0, 1] <= 1
    
    def test_optimization(self, test_config):
        """Test portfolio optimization."""
        manager = PortfolioManager(test_config)
        
        returns = pd.DataFrame({
            'asset_a': np.random.normal(0.001, 0.02, 252),
            'asset_b': np.random.normal(0.0005, 0.015, 252),
            'asset_c': np.random.normal(0.0008, 0.025, 252)
        })
        
        optimal = manager.optimize(
            returns,
            method='sharpe',  # Maximize Sharpe ratio
            constraints={'max_weight': 0.5}
        )
        
        assert sum(optimal['weights'].values()) == pytest.approx(1.0)
        assert all(w <= 0.5 for w in optimal['weights'].values())
        assert optimal['expected_sharpe'] > 0
    
    def test_risk_contribution(self, test_config):
        """Test risk parity calculations."""
        manager = PortfolioManager(test_config)
        
        weights = {'XAUUSD': 0.5, 'EURUSD': 0.5}
        cov_matrix = pd.DataFrame({
            'XAUUSD': [0.0004, 0.0001],
            'EURUSD': [0.0001, 0.0002]
        }, index=['XAUUSD', 'EURUSD'])
        
        risk_contrib = manager.calculate_risk_contribution(weights, cov_matrix)
        
        assert sum(risk_contrib.values()) == pytest.approx(1.0)
        assert risk_contrib['XAUUSD'] > risk_contrib['EURUSD']  # Higher vol
