"""
Feature Engineering for Trading ML Models

Comprehensive feature engineering pipeline for creating
technical indicators and derived features from OHLCV data.
"""

from typing import Dict, List, Optional, Any
import numpy as np
import pandas as pd
import logging

logger = logging.getLogger(__name__)


class TechnicalFeatureEngineer:
    """
    Feature engineering for trading strategies.
    
    Creates technical indicators and derived features from OHLCV data:
    - Trend indicators (MA, EMA, MACD)
    - Momentum indicators (RSI, Stochastic, ROC)
    - Volatility indicators (Bollinger Bands, ATR)
    - Volume indicators
    - Price patterns
    - Statistical features
    """
    
    def __init__(self, config: Optional[Dict] = None):
        """
        Initialize feature engineer.
        
        Args:
            config: Configuration with feature settings
        """
        self.config = config or {}
        self.feature_names: List[str] = []
        self.logger = logging.getLogger(__name__)
    
    def create_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Create all technical features.
        
        Args:
            df: DataFrame with OHLCV columns
            
        Returns:
            DataFrame with added features
        """
        df = df.copy()
        
        # Ensure required columns exist
        required = ['open', 'high', 'low', 'close', 'volume']
        if not all(col in df.columns for col in required):
            raise ValueError(f"DataFrame must contain columns: {required}")
        
        # Create features
        df = self._add_trend_features(df)
        df = self._add_momentum_features(df)
        df = self._add_volatility_features(df)
        df = self._add_volume_features(df)
        df = self._add_price_patterns(df)
        df = self._add_statistical_features(df)
        
        # Remove NaN values from feature creation
        df = df.dropna()
        
        # Store feature names (excluding OHLCV)
        self.feature_names = [col for col in df.columns if col not in required]
        
        self.logger.info(f"Created {len(self.feature_names)} features")
        
        return df
    
    def _add_trend_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """Add trend-following indicators."""
        close = df['close']
        
        # Simple Moving Averages
        for period in [5, 10, 20, 50, 100, 200]:
            df[f'sma_{period}'] = close.rolling(window=period).mean()
        
        # Exponential Moving Averages
        for period in [5, 10, 20, 50, 100]:
            df[f'ema_{period}'] = close.ewm(span=period, adjust=False).mean()
        
        # MACD
        exp1 = close.ewm(span=12, adjust=False).mean()
        exp2 = close.ewm(span=26, adjust=False).mean()
        df['macd'] = exp1 - exp2
        df['macd_signal'] = df['macd'].ewm(span=9, adjust=False).mean()
        df['macd_hist'] = df['macd'] - df['macd_signal']
        
        # Price relative to MAs
        for period in [20, 50, 200]:
            df[f'close_to_sma_{period}'] = (close - df[f'sma_{period}']) / df[f'sma_{period}']
        
        # MA crossovers (1 if short > long, -1 if short < long)
        df['sma_10_20_cross'] = np.where(df['sma_10'] > df['sma_20'], 1, -1)
        df['sma_20_50_cross'] = np.where(df['sma_20'] > df['sma_50'], 1, -1)
        df['ema_12_26_cross'] = np.where(df['ema_12'] > df['ema_26'], 1, -1)
        
        return df
    
    def _add_momentum_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """Add momentum indicators."""
        close = df['close']
        high = df['high']
        low = df['low']
        
        # RSI
        for period in [7, 14, 21]:
            delta = close.diff()
            gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
            loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
            rs = gain / loss
            df[f'rsi_{period}'] = 100 - (100 / (1 + rs))
        
        # Stochastic Oscillator
        for period in [14, 21]:
            low_min = low.rolling(window=period).min()
            high_max = high.rolling(window=period).max()
            df[f'stoch_k_{period}'] = 100 * (close - low_min) / (high_max - low_min)
            df[f'stoch_d_{period}'] = df[f'stoch_k_{period}'].rolling(window=3).mean()
        
        # Rate of Change (ROC)
        for period in [5, 10, 20]:
            df[f'roc_{period}'] = ((close - close.shift(period)) / close.shift(period)) * 100
        
        # Momentum
        for period in [5, 10, 20]:
            df[f'momentum_{period}'] = close - close.shift(period)
        
        # Williams %R
        for period in [14, 21]:
            high_max = high.rolling(window=period).max()
            low_min = low.rolling(window=period).min()
            df[f'williams_r_{period}'] = -100 * (high_max - close) / (high_max - low_min)
        
        return df
    
    def _add_volatility_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """Add volatility indicators."""
        close = df['close']
        high = df['high']
        low = df['low']
        
        # Bollinger Bands
        for period in [20, 50]:
            sma = close.rolling(window=period).mean()
            std = close.rolling(window=period).std()
            df[f'bb_upper_{period}'] = sma + (std * 2)
            df[f'bb_lower_{period}'] = sma - (std * 2)
            df[f'bb_width_{period}'] = (df[f'bb_upper_{period}'] - df[f'bb_lower_{period}']) / sma
            df[f'bb_position_{period}'] = (close - df[f'bb_lower_{period}']) / (df[f'bb_upper_{period}'] - df[f'bb_lower_{period}'])
        
        # Average True Range (ATR)
        for period in [7, 14, 21]:
            high_low = high - low
            high_close = np.abs(high - close.shift())
            low_close = np.abs(low - close.shift())
            true_range = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
            df[f'atr_{period}'] = true_range.rolling(window=period).mean()
        
        # Historical Volatility
        for period in [10, 20, 30]:
            returns = np.log(close / close.shift())
            df[f'volatility_{period}'] = returns.rolling(window=period).std() * np.sqrt(252)
        
        return df
    
    def _add_volume_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """Add volume-based indicators."""
        volume = df['volume']
        close = df['close']
        
        # Volume Moving Averages
        for period in [5, 10, 20]:
            df[f'volume_sma_{period}'] = volume.rolling(window=period).mean()
            df[f'volume_ratio_{period}'] = volume / df[f'volume_sma_{period}']
        
        # On-Balance Volume (OBV)
        df['obv'] = (np.sign(close.diff()) * volume).fillna(0).cumsum()
        
        # Volume Price Trend (VPT)
        df['vpt'] = (volume * ((close - close.shift()) / close.shift())).fillna(0).cumsum()
        
        # Money Flow Index (MFI)
        typical_price = (df['high'] + df['low'] + close) / 3
        money_flow = typical_price * volume
        
        for period in [14, 21]:
            positive_flow = money_flow.where(typical_price > typical_price.shift(), 0).rolling(window=period).sum()
            negative_flow = money_flow.where(typical_price < typical_price.shift(), 0).rolling(window=period).sum()
            mfi_ratio = positive_flow / negative_flow
            df[f'mfi_{period}'] = 100 - (100 / (1 + mfi_ratio))
        
        return df
    
    def _add_price_patterns(self, df: pd.DataFrame) -> pd.DataFrame:
        """Add price pattern features."""
        open_price = df['open']
        high = df['high']
        low = df['low']
        close = df['close']
        
        # Candle body and shadow
        df['body'] = close - open_price
        df['body_pct'] = (close - open_price) / open_price
        df['upper_shadow'] = high - np.maximum(open_price, close)
        df['lower_shadow'] = np.minimum(open_price, close) - low
        df['total_range'] = high - low
        
        # Candle patterns (simplified)
        df['is_bullish'] = (close > open_price).astype(int)
        df['is_bearish'] = (close < open_price).astype(int)
        df['is_doji'] = (np.abs(close - open_price) / (high - low) < 0.1).astype(int)
        
        # Price gaps
        df['gap'] = open_price - close.shift()
        df['gap_pct'] = df['gap'] / close.shift()
        
        # Higher highs, lower lows
        df['higher_high'] = (high > high.shift()).astype(int)
        df['lower_low'] = (low < low.shift()).astype(int)
        df['higher_low'] = (low > low.shift()).astype(int)
        df['lower_high'] = (high < high.shift()).astype(int)
        
        return df
    
    def _add_statistical_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """Add statistical features."""
        close = df['close']
        
        # Returns
        df['returns_1'] = close.pct_change()
        df['returns_5'] = close.pct_change(5)
        df['returns_10'] = close.pct_change(10)
        df['returns_20'] = close.pct_change(20)
        
        # Log returns
        df['log_returns_1'] = np.log(close / close.shift())
        df['log_returns_5'] = np.log(close / close.shift(5))
        
        # Rolling statistics
        for period in [10, 20]:
            df[f'mean_{period}'] = close.rolling(window=period).mean()
            df[f'std_{period}'] = close.rolling(window=period).std()
            df[f'skew_{period}'] = close.rolling(window=period).skew()
            df[f'kurt_{period}'] = close.rolling(window=period).kurt()
        
        # Z-score
        for period in [20, 50]:
            mean = close.rolling(window=period).mean()
            std = close.rolling(window=period).std()
            df[f'zscore_{period}'] = (close - mean) / std
        
        # Percentile rank
        for period in [20, 50]:
            df[f'percentile_{period}'] = close.rolling(window=period).apply(
                lambda x: pd.Series(x).rank(pct=True).iloc[-1]
            )
        
        return df
    
    def create_labels(
        self,
        df: pd.DataFrame,
        method: str = 'forward_return',
        **kwargs
    ) -> pd.Series:
        """
        Create labels for supervised learning.
        
        Args:
            df: DataFrame with price data
            method: Labeling method ('forward_return', 'trend', 'breakout')
            **kwargs: Method-specific parameters
            
        Returns:
            Series of labels
        """
        close = df['close']
        
        if method == 'forward_return':
            # Label based on forward return
            periods = kwargs.get('periods', 5)
            threshold = kwargs.get('threshold', 0.01)  # 1%
            
            forward_return = close.shift(-periods) / close - 1
            
            labels = pd.Series(1, index=df.index)  # HOLD
            labels[forward_return > threshold] = 2  # BUY
            labels[forward_return < -threshold] = 0  # SELL
            
        elif method == 'trend':
            # Label based on trend direction
            periods = kwargs.get('periods', 10)
            
            future_ma = close.shift(-periods).rolling(window=periods).mean()
            current_price = close
            
            labels = pd.Series(1, index=df.index)  # HOLD
            labels[future_ma > current_price] = 2  # BUY
            labels[future_ma < current_price] = 0  # SELL
            
        elif method == 'breakout':
            # Label based on breakout from range
            lookback = kwargs.get('lookback', 20)
            threshold = kwargs.get('threshold', 0.02)  # 2%
            
            high_max = df['high'].rolling(window=lookback).max()
            low_min = df['low'].rolling(window=lookback).min()
            
            future_high = df['high'].shift(-1)
            future_low = df['low'].shift(-1)
            
            labels = pd.Series(1, index=df.index)  # HOLD
            labels[future_high > high_max * (1 + threshold)] = 2  # BUY (breakout up)
            labels[future_low < low_min * (1 - threshold)] = 0  # SELL (breakout down)
            
        else:
            raise ValueError(f"Unknown labeling method: {method}")
        
        return labels
    
    def get_feature_groups(self) -> Dict[str, List[str]]:
        """
        Get features grouped by type.
        
        Returns:
            Dict mapping group names to feature lists
        """
        groups = {
            'trend': [f for f in self.feature_names if any(x in f for x in ['sma', 'ema', 'macd'])],
            'momentum': [f for f in self.feature_names if any(x in f for x in ['rsi', 'stoch', 'roc', 'momentum', 'williams'])],
            'volatility': [f for f in self.feature_names if any(x in f for x in ['bb', 'atr', 'volatility'])],
            'volume': [f for f in self.feature_names if any(x in f for x in ['volume', 'obv', 'vpt', 'mfi'])],
            'pattern': [f for f in self.feature_names if any(x in f for x in ['body', 'shadow', 'bullish', 'bearish', 'doji', 'gap', 'higher', 'lower'])],
            'statistical': [f for f in self.feature_names if any(x in f for x in ['returns', 'mean', 'std', 'skew', 'kurt', 'zscore', 'percentile'])],
        }
        return groups
