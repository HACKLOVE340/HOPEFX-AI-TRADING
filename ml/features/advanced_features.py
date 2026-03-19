"""
Advanced ML Feature Engineering for Trading
- Technical indicator features
- Market microstructure features
- Sentiment features
- Volatility features
- Correlation features
"""

import logging
from typing import Dict, List, Tuple, Optional, Any
import numpy as np
import pandas as pd
from scipy import stats
from scipy.signal import hilbert

logger = logging.getLogger(__name__)

class AdvancedFeatureEngineer:
    """Enterprise-grade feature engineering"""
    
    def __init__(self, lookback_periods: int = 252):
        """
        Initialize feature engineer
        
        Args:
            lookback_periods: Number of periods for historical calculations
        """
        self.lookback_periods = lookback_periods
    
    def engineer_features(self,
                         df: pd.DataFrame,
                         include_sentiment: bool = True) -> pd.DataFrame:
        """
        Engineer all features
        
        Args:
            df: OHLCV DataFrame
            include_sentiment: Include sentiment features
            
        Returns:
            DataFrame with engineered features
        """
        
        features_df = df.copy()
        
        # Price-based features
        features_df = self._add_price_features(features_df)
        
        # Volatility features
        features_df = self._add_volatility_features(features_df)
        
        # Trend features
        features_df = self._add_trend_features(features_df)
        
        # Momentum features
        features_df = self._add_momentum_features(features_df)
        
        # Volume features
        features_df = self._add_volume_features(features_df)
        
        # Pattern features
        features_df = self._add_pattern_features(features_df)
        
        # Microstructure features
        features_df = self._add_microstructure_features(features_df)
        
        # Remove NaN values
        features_df = features_df.dropna()
        
        return features_df
    
    def _add_price_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """Add price-based features"""
        
        df['returns'] = df['close'].pct_change()
        df['log_returns'] = np.log(df['close'] / df['close'].shift(1))
        
        # Price position in range
        df['high_low_ratio'] = (df['close'] - df['low']) / (df['high'] - df['low'] + 1e-10)
        
        # Close to open
        df['close_open_ratio'] = df['close'] / df['open']
        
        # Body size
        df['body_size'] = abs(df['close'] - df['open']) / (df['high'] - df['low'] + 1e-10)
        
        # Upper/Lower shadow
        df['upper_shadow'] = (df['high'] - np.maximum(df['open'], df['close'])) / (df['high'] - df['low'] + 1e-10)
        df['lower_shadow'] = (np.minimum(df['open'], df['close']) - df['low']) / (df['high'] - df['low'] + 1e-10)
        
        # N-period returns
        for period in [2, 5, 10, 20, 60]:
            df[f'returns_{period}d'] = df['close'].pct_change(period)
        
        return df
    
    def _add_volatility_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """Add volatility features"""
        
        # Historical volatility (standard deviation)
        for period in [10, 20, 60]:
            df[f'volatility_{period}d'] = df['returns'].rolling(period).std()
        
        # Parkinson volatility (high-low range based)
        df['parkinson_vol'] = np.sqrt(np.log(df['high'] / df['low'])**2 / (4 * np.log(2)))
        
        # Garman-Klass volatility
        hl = np.log(df['high'] / df['low'])
        co = np.log(df['close'] / df['open'])
        df['garman_klass_vol'] = np.sqrt(0.5 * hl**2 - (2 * np.log(2) - 1) * co**2)
        
        # True Range
        df['tr'] = np.maximum(
            df['high'] - df['low'],
            np.maximum(
                abs(df['high'] - df['close'].shift()),
                abs(df['low'] - df['close'].shift())
            )
        )
        
        # ATR
        for period in [14, 20]:
            df[f'atr_{period}'] = df['tr'].rolling(period).mean()
        
        # Volatility of volatility
        df['vol_of_vol'] = df['volatility_20d'].rolling(20).std()
        
        return df
    
    def _add_trend_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """Add trend features"""
        
        # Moving averages
        for period in [5, 10, 20, 50, 200]:
            df[f'sma_{period}'] = df['close'].rolling(period).mean()
            df[f'ema_{period}'] = df['close'].ewm(span=period).mean()
        
        # Price vs MA relationships
        df['price_sma_20_ratio'] = df['close'] / (df['sma_20'] + 1e-10)
        df['price_sma_50_ratio'] = df['close'] / (df['sma_50'] + 1e-10)
        
        # Trend strength (ADX-like)
        df['trend_strength'] = self._calculate_trend_strength(df)
        
        # Slope of moving average
        for period in [20, 50]:
            sma = df[f'sma_{period}']
            df[f'sma_{period}_slope'] = sma.diff() / sma.shift() * 100
        
        return df
    
    def _add_momentum_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """Add momentum features"""
        
        # RSI
        for period in [14, 21]:
            df[f'rsi_{period}'] = self._calculate_rsi(df['close'], period)
        
        # MACD
        df['macd'], df['macd_signal'], df['macd_hist'] = self._calculate_macd(df['close'])
        
        # Momentum
        for period in [10, 20]:
            df[f'momentum_{period}'] = df['close'] - df['close'].shift(period)
        
        # Rate of Change
        for period in [5, 10, 20]:
            df[f'roc_{period}'] = ((df['close'] - df['close'].shift(period)) / 
                                   df['close'].shift(period) * 100)
        
        # Stochastic Oscillator
        df['stoch_k'], df['stoch_d'] = self._calculate_stochastic(df, period=14)
        
        # Williams %R
        df['williams_r'] = self._calculate_williams_r(df, period=14)
        
        return df
    
    def _add_volume_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """Add volume features"""
        
        # Volume SMA
        for period in [5, 20]:
            df[f'volume_sma_{period}'] = df['volume'].rolling(period).mean()
        
        # Volume ratio
        df['volume_ratio'] = df['volume'] / (df['volume_sma_20'] + 1e-10)
        
        # On Balance Volume
        df['obv'] = (np.sign(df['close'].diff()) * df['volume']).fillna(0).cumsum()
        
        # Money Flow Index
        df['mfi'] = self._calculate_mfi(df, period=14)
        
        # Volume Rate of Change
        df['volume_roc'] = df['volume'].pct_change() * 100
        
        # Accumulation/Distribution
        df['ad'] = ((df['close'] - df['low']) - (df['high'] - df['close'])) / (df['high'] - df['low'] + 1e-10) * df['volume']
        
        return df
    
    def _add_pattern_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """Add candlestick pattern features"""
        
        # Hammer/Hanging man
        body = abs(df['close'] - df['open'])
        upper_shadow = df['high'] - np.maximum(df['close'], df['open'])
        lower_shadow = np.minimum(df['close'], df['open']) - df['low']
        
        df['hammer_score'] = (lower_shadow > 2 * upper_shadow) & (body < body.rolling(20).mean())
        
        # Doji
        df['doji_score'] = body < 0.1 * (df['high'] - df['low'])
        
        # Engulfing
        df['bullish_engulfing'] = ((df['close'] > df['open']) & 
                                   (df['close'] > df['open'].shift()) &
                                   (df['open'] < df['close'].shift()))
        
        df['bearish_engulfing'] = ((df['close'] < df['open']) & 
                                   (df['close'] < df['open'].shift()) &
                                   (df['open'] > df['close'].shift()))
        
        return df
    
    def _add_microstructure_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """Add market microstructure features"""
        
        # Bid-ask spread (approximation)
        df['spread_estimate'] = (df['high'] - df['low']) / df['close'] * 100
        
        # Price impact
        df['price_impact'] = abs(df['close'] - df['open']) / df['close'] * 100
        
        # Liquidity-adjusted volume
        df['amihud_illiquidity'] = abs(df['returns']) / (df['volume'] + 1)
        
        # Order flow toxicity (Easley-OFT)
        df['oft'] = self._calculate_order_flow_toxicity(df)
        
        return df
    
    def _calculate_rsi(self, prices: pd.Series, period: int = 14) -> pd.Series:
        """Calculate Relative Strength Index"""
        
        delta = prices.diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
        
        rs = gain / (loss + 1e-10)
        rsi = 100 - (100 / (1 + rs))
        
        return rsi
    
    def _calculate_macd(self, prices: pd.Series) -> Tuple[pd.Series, pd.Series, pd.Series]:
        """Calculate MACD"""
        
        ema12 = prices.ewm(span=12).mean()
        ema26 = prices.ewm(span=26).mean()
        
        macd = ema12 - ema26
        signal = macd.ewm(span=9).mean()
        hist = macd - signal
        
        return macd, signal, hist
    
    def _calculate_stochastic(self,
                             df: pd.DataFrame,
                             period: int = 14) -> Tuple[pd.Series, pd.Series]:
        """Calculate Stochastic Oscillator"""
        
        low_min = df['low'].rolling(period).min()
        high_max = df['high'].rolling(period).max()
        
        k = 100 * ((df['close'] - low_min) / (high_max - low_min + 1e-10))
        d = k.rolling(3).mean()
        
        return k, d
    
    def _calculate_williams_r(self, df: pd.DataFrame, period: int = 14) -> pd.Series:
        """Calculate Williams %R"""
        
        high_max = df['high'].rolling(period).max()
        low_min = df['low'].rolling(period).min()
        
        wr = -100 * ((high_max - df['close']) / (high_max - low_min + 1e-10))
        
        return wr
    
    def _calculate_mfi(self, df: pd.DataFrame, period: int = 14) -> pd.Series:
        """Calculate Money Flow Index"""
        
        typical_price = (df['high'] + df['low'] + df['close']) / 3
        money_flow = typical_price * df['volume']
        
        positive_flow = money_flow.where(typical_price > typical_price.shift(), 0)
        negative_flow = money_flow.where(typical_price < typical_price.shift(), 0)
        
        positive_sum = positive_flow.rolling(period).sum()
        negative_sum = negative_flow.rolling(period).sum()
        
        mfi = 100 - (100 / (1 + (positive_sum / (negative_sum + 1e-10))))
        
        return mfi
    
    def _calculate_trend_strength(self, df: pd.DataFrame) -> pd.Series:
        """Calculate trend strength"""
        
        sma20 = df['close'].rolling(20).mean()
        sma50 = df['close'].rolling(50).mean()
        
        # Distance from both SMAs (normalized)
        strength = abs(sma20 - sma50) / sma20 * 100
        
        return strength
    
    def _calculate_order_flow_toxicity(self, df: pd.DataFrame) -> pd.Series:
        """Calculate order flow toxicity indicator"""
        
        returns = df['close'].pct_change()
        volume = df['volume']
        
        # Simplified OFT: correlation between volume spikes and price movements
        oft = abs(returns) * (volume / volume.rolling(20).mean())
        
        return oft