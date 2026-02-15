"""
Tests for the ML module.
"""

import pytest
import numpy as np
import pandas as pd
from datetime import datetime, timedelta
from unittest.mock import Mock, patch, MagicMock

from ml.features.technical import TechnicalFeatureEngineer


class TestTechnicalFeatureEngineer:
    """Tests for TechnicalFeatureEngineer class."""
    
    @pytest.fixture
    def sample_ohlcv_data(self):
        """Create sample OHLCV data for testing."""
        np.random.seed(42)
        dates = pd.date_range(start='2024-01-01', periods=300, freq='D')
        
        # Generate realistic price data
        base_price = 100.0
        returns = np.random.randn(300) * 0.02  # 2% daily volatility
        prices = base_price * np.cumprod(1 + returns)
        
        df = pd.DataFrame({
            'open': prices * (1 + np.random.randn(300) * 0.005),
            'high': prices * (1 + np.abs(np.random.randn(300) * 0.01)),
            'low': prices * (1 - np.abs(np.random.randn(300) * 0.01)),
            'close': prices,
            'volume': np.random.randint(1000, 10000, 300).astype(float)
        }, index=dates)
        
        return df
    
    def test_feature_engineer_initialization(self):
        """Test TechnicalFeatureEngineer initialization."""
        fe = TechnicalFeatureEngineer()
        
        assert fe.config == {}
        assert fe.feature_names == []
    
    def test_feature_engineer_with_config(self):
        """Test TechnicalFeatureEngineer with config."""
        config = {'periods': [5, 10, 20]}
        fe = TechnicalFeatureEngineer(config=config)
        
        assert fe.config == config
    
    def test_create_features_missing_columns(self):
        """Test that create_features raises error with missing columns."""
        fe = TechnicalFeatureEngineer()
        
        df = pd.DataFrame({
            'open': [1.0, 2.0],
            'close': [1.1, 2.1]
        })
        
        with pytest.raises(ValueError) as exc_info:
            fe.create_features(df)
        
        assert "must contain columns" in str(exc_info.value)
    
    def test_create_features_basic(self, sample_ohlcv_data):
        """Test basic feature creation."""
        fe = TechnicalFeatureEngineer()
        
        result = fe.create_features(sample_ohlcv_data)
        
        # Check that features were created
        assert len(result.columns) > 5  # More than just OHLCV
        assert len(fe.feature_names) > 0
    
    def test_create_features_no_nan_in_result(self, sample_ohlcv_data):
        """Test that result has no NaN values."""
        fe = TechnicalFeatureEngineer()
        
        result = fe.create_features(sample_ohlcv_data)
        
        # NaN should be dropped
        assert result.isna().sum().sum() == 0
    
    def test_trend_features_created(self, sample_ohlcv_data):
        """Test that trend features are created."""
        fe = TechnicalFeatureEngineer()
        
        result = fe.create_features(sample_ohlcv_data)
        
        # Check for SMA features
        assert 'sma_5' in result.columns
        assert 'sma_20' in result.columns
        assert 'sma_50' in result.columns
        
        # Check for EMA features
        assert 'ema_5' in result.columns
        assert 'ema_20' in result.columns
        
        # Check for MACD features
        assert 'macd' in result.columns
        assert 'macd_signal' in result.columns
    
    def test_momentum_features_created(self, sample_ohlcv_data):
        """Test that momentum features are created."""
        fe = TechnicalFeatureEngineer()
        
        result = fe.create_features(sample_ohlcv_data)
        
        # Check for RSI features
        assert 'rsi_14' in result.columns
        
        # Check for other momentum indicators
        # (depends on implementation)
    
    def test_volatility_features_created(self, sample_ohlcv_data):
        """Test that volatility features are created."""
        fe = TechnicalFeatureEngineer()
        
        result = fe.create_features(sample_ohlcv_data)
        
        # Check for volatility features (e.g., Bollinger Bands)
        # Bollinger Bands or ATR should be present
        volatility_features = [col for col in result.columns if 'bb_' in col or 'atr' in col]
        assert len(volatility_features) >= 1
    
    def test_volume_features_created(self, sample_ohlcv_data):
        """Test that volume features are created."""
        fe = TechnicalFeatureEngineer()
        
        result = fe.create_features(sample_ohlcv_data)
        
        # Check for volume-related features
        volume_features = [col for col in result.columns if 'volume' in col.lower() or 'vol_' in col]
        assert len(volume_features) >= 1
    
    def test_feature_names_populated(self, sample_ohlcv_data):
        """Test that feature_names list is populated."""
        fe = TechnicalFeatureEngineer()
        
        result = fe.create_features(sample_ohlcv_data)
        
        # feature_names should not include OHLCV columns
        assert 'open' not in fe.feature_names
        assert 'close' not in fe.feature_names
        assert len(fe.feature_names) > 0
    
    def test_original_data_not_modified(self, sample_ohlcv_data):
        """Test that original DataFrame is not modified."""
        fe = TechnicalFeatureEngineer()
        original_columns = list(sample_ohlcv_data.columns)
        original_len = len(sample_ohlcv_data)
        
        fe.create_features(sample_ohlcv_data)
        
        # Original should be unchanged
        assert list(sample_ohlcv_data.columns) == original_columns
        assert len(sample_ohlcv_data) == original_len
    
    def test_create_features_returns_dataframe(self, sample_ohlcv_data):
        """Test that create_features returns a DataFrame."""
        fe = TechnicalFeatureEngineer()
        
        result = fe.create_features(sample_ohlcv_data)
        
        assert isinstance(result, pd.DataFrame)
    
    def test_multiple_calls_consistency(self, sample_ohlcv_data):
        """Test that multiple calls produce consistent results."""
        fe = TechnicalFeatureEngineer()
        
        result1 = fe.create_features(sample_ohlcv_data)
        result2 = fe.create_features(sample_ohlcv_data)
        
        # Results should be identical
        pd.testing.assert_frame_equal(result1, result2)
