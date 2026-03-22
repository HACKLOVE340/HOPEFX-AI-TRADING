"""
Advanced ML Feature Engineering for Trading
- Technical indicator features
- Market microstructure features
- Volatility features
- Correlation features
- Entropy features
- Deep learning ready features
"""

import logging
from typing import Dict, List, Tuple, Optional, Any
import numpy as np
import pandas as pd
from scipy import stats
from scipy.signal import hilbert
from datetime import datetime

logger = logging.getLogger(__name__)

class AdvancedFeatureEngineer:
    """Enterprise-grade feature engineering"""
    
    def __init__(self, lookback_periods: int = 252):
        """Initialize feature engineer"""
        self.lookback_periods = lookback_periods
    
    def engineer_features(self,
                         df: pd.DataFrame,
                         include_advanced: bool = True) -> pd.DataFrame:
        """
        Engineer all features
        
        Args:
            df: OHLCV DataFrame
            include_advanced: Include advanced features
            
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
        
        if include_advanced:
            # Entropy features
            features_df = self._add_entropy_features(features_df)
            
            # Fractal features
            features_df = self._add_fractal_features(features_df)
            
            # Regime features
            features_df = self._add_regime_features(features_df)
        
        # Remove NaN values
        features_df = features_df.dropna()
        
        logger.info(f"Engineered {len(features_df.columns)} features")
        return features_df
    
    def _add_price_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """Add price-based features"""
        
        df['returns'] = df['close'].pct_change()
        df['log_returns'] = np.log(df['close'] / df['close'].shift(1))
        
        # Price position in range
        df['high_low_ratio'] = (df['close'] - df['low']) / (df['high'] - df['low'] + 1e-10)
        
        # Close to open
        df['close_open_ratio'] = df['close'] / df['open']
        
        # Body size (normalized)
        range_size = df['high'] - df['low']
        df['body_size'] = abs(df['close'] - df['open']) / (range_size + 1e-10)
        
        # Shadows
        df['upper_shadow'] = (df['high'] - np.maximum(df['open'], df['close'])) / (range_size + 1e-10)
        df['lower_shadow'] = (np.minimum(df['open'], df['close']) - df['low']) / (range_size + 1e-10)
        
        # Multi-period returns
        for period in [2, 5, 10, 20, 60]:
            df[f'returns_{period}d'] = df['close'].pct_change(period)
        
        # Price acceleration
        df['price_accel'] = df['returns'].diff()
        
        # Price jerk (3rd derivative)
        df['price_jerk'] = df['price_accel'].diff()
        
        return df
    
    def _add_volatility_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """Add volatility features"""
        
        # Historical volatility
        for period in [10, 20, 60]:
            df[f'volatility_{period}d'] = df['returns'].rolling(period).std()
        
        # Parkinson volatility
        hl_ratio = np.log(df['high'] / df['low'])
        df['parkinson_vol'] = np.sqrt(np.mean(hl_ratio**2) / (4 * np.log(2)))
        
        # Garman-Klass volatility
        hl = np.log(df['high'] / df['low'])
        co = np.log(df['close'] / df['open'])
        df['garman_klass_vol'] = np.sqrt(0.5 * hl**2 - (2 * np.log(2) - 1) * co**2)
        
        # True Range & ATR
        df['tr'] = np.maximum(
            df['high'] - df['low'],
            np.maximum(
                abs(df['high'] - df['close'].shift()),
                abs(df['low'] - df['close'].shift())
            )
        )
        
        for period in [14, 20]:
            df[f'atr_{period}'] = df['tr'].rolling(period).mean()
        
        # Volatility of volatility
        df['vol_of_vol'] = df['volatility_20d'].rolling(20).std()
        
        # Normalized volatility
        df['vol_normalized'] = df['volatility_20d'] / df['volatility_20d'].rolling(60).mean()
        
        return df
    
    def _add_trend_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """Add trend features"""
        
        # Moving averages
        for period in [5, 10, 20, 50, 200]:
            df[f'sma_{period}'] = df['close'].rolling(period).mean()
            df[f'ema_{period}'] = df['close'].ewm(span=period).mean()
        
        # Price vs MA
        df['price_sma_20_ratio'] = df['close'] / (df['sma_20'] + 1e-10)
        df['price_ema_20_ratio'] = df['close'] / (df['ema_20'] + 1e-10)
        
        # Trend strength
        df['trend_strength'] = self._calculate_trend_strength(df)
        
        # Slope of MA
        for period in [20, 50]:
            sma = df[f'sma_{period}']
            df[f'sma_{period}_slope'] = sma.diff() / sma.shift() * 100
        
        # Price distance from MA
        for period in [20, 50, 200]:
            sma = df[f'sma_{period}']
            df[f'price_dist_sma_{period}'] = (df['close'] - sma) / sma * 100
        
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
            df[f'momentum_pct_{period}'] = (df['close'] - df['close'].shift(period)) / df['close'].shift(period) * 100
        
        # Rate of Change
        for period in [5, 10, 20]:
            df[f'roc_{period}'] = ((df['close'] - df['close'].shift(period)) / df['close'].shift(period) * 100)
        
        # Stochastic
        df['stoch_k'], df['stoch_d'] = self._calculate_stochastic(df, period=14)
        
        # Williams %R
        df['williams_r'] = self._calculate_williams_r(df, period=14)
        
        # CCI (Commodity Channel Index)
        df['cci'] = self._calculate_cci(df, period=20)
        
        return df
    
    def _add_volume_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """Add volume features"""
        
        # Volume SMA
        for period in [5, 20]:
            df[f'volume_sma_{period}'] = df['volume'].rolling(period).mean()
        
        # Volume ratio
        df['volume_ratio'] = df['volume'] / (df['volume_sma_20'] + 1e-10)
        
        # OBV (On Balance Volume)
        df['obv'] = (np.sign(df['close'].diff()) * df['volume']).fillna(0).cumsum()
        
        # MFI (Money Flow Index)
        df['mfi'] = self._calculate_mfi(df, period=14)
        
        # Volume ROC
        df['volume_roc'] = df['volume'].pct_change() * 100
        
        # Accumulation/Distribution
        hlc_ratio = (df['close'] - df['low']) - (df['high'] - df['close'])
        df['ad'] = (hlc_ratio / (df['high'] - df['low'] + 1e-10)) * df['volume']
        
        # Volume-price trend
        df['vpt'] = df['ad'].cumsum()
        
        return df
    
    def _add_pattern_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """Add candlestick pattern features"""
        
        body = abs(df['close'] - df['open'])
        upper_shadow = df['high'] - np.maximum(df['close'], df['open'])
        lower_shadow = np.minimum(df['close'], df['open']) - df['low']
        range_size = df['high'] - df['low']
        
        # Hammer/Hanging Man
        df['hammer_score'] = (lower_shadow > 2 * upper_shadow).astype(int) * (body < body.rolling(20).mean()).astype(int)
        
        # Doji
        df['doji_score'] = (body < 0.1 * (df['high'] - df['low'])).astype(int)
        
        # Engulfing
        df['bullish_engulfing'] = (
            (df['close'] > df['open']).astype(int) *
            (df['close'] > df['open'].shift()).astype(int) *
            (df['open'] < df['close'].shift()).astype(int)
        )
        
        df['bearish_engulfing'] = (
            (df['close'] < df['open']).astype(int) *
            (df['close'] < df['open'].shift()).astype(int) *
            (df['open'] > df['close'].shift()).astype(int)
        )
        
        # Marubozu (no shadows)
        df['marubozu_score'] = ((upper_shadow < body * 0.01).astype(int) * (lower_shadow < body * 0.01).astype(int))
        
        return df
    
    def _add_microstructure_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """Add market microstructure features"""
        
        # Spread estimate
        df['spread_estimate'] = (df['high'] - df['low']) / df['close'] * 100
        
        # Price impact
        df['price_impact'] = abs(df['close'] - df['open']) / df['close'] * 100
        
        # Amihud illiquidity
        df['amihud_illiquidity'] = abs(df['returns']) / (df['volume'] + 1)
        
        # VWAP (Volume Weighted Average Price)
        typical_price = (df['high'] + df['low'] + df['close']) / 3
        df['vwap'] = (typical_price * df['volume']).rolling(20).sum() / df['volume'].rolling(20).sum()
        
        # Distance from VWAP
        df['price_vwap_dist'] = (df['close'] - df['vwap']) / df['vwap'] * 100
        
        return df
    
    def _add_entropy_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """Add entropy and information features"""
        
        # Approximate entropy
        for period in [10, 20]:
            df[f'entropy_{period}'] = df['returns'].rolling(period).apply(
                lambda x: self._calculate_entropy(x),
                raw=True
            )
        
        # Permutation entropy
        df['perm_entropy_10'] = df['returns'].rolling(10).apply(
            lambda x: self._calculate_permutation_entropy(x),
            raw=True
        )
        
        return df
    
    def _add_fractal_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """Add fractal/scaling features"""
        
        # Hurst exponent
        for period in [20, 50]:
            df[f'hurst_{period}'] = df['returns'].rolling(period).apply(
                lambda x: self._calculate_hurst(x),
                raw=True
            )
        
        # Detrended fluctuation analysis
        df['dfa_10'] = df['returns'].rolling(10).apply(
            lambda x: self._calculate_dfa(x),
            raw=True
        )
        
        return df
    
    def _add_regime_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """Add regime detection features"""
        
        # Volatility regime
        vol_20 = df['volatility_20d']
        vol_ma = vol_20.rolling(60).mean()
        df['vol_regime'] = (vol_20 > vol_ma).astype(int)
        
        # Trend regime
        df['trend_regime'] = ((df['ema_20'] > df['ema_50']).astype(int) * 2 - 1)
        
        # Momentum regime
        df['momentum_regime'] = np.sign(df['rsi_14'] - 50)
        
        return df
    
    # ============ INDICATOR CALCULATIONS ============
    
    def _calculate_rsi(self, prices: pd.Series, period: int = 14) -> pd.Series:
        """Calculate RSI"""
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
        """Calculate MFI"""
        typical_price = (df['high'] + df['low'] + df['close']) / 3
        money_flow = typical_price * df['volume']
        
        positive_flow = money_flow.where(typical_price > typical_price.shift(), 0)
        negative_flow = money_flow.where(typical_price < typical_price.shift(), 0)
        
        positive_sum = positive_flow.rolling(period).sum()
        negative_sum = negative_flow.rolling(period).sum()
        
        mfi = 100 - (100 / (1 + (positive_sum / (negative_sum + 1e-10))))
        return mfi
    
    def _calculate_cci(self, df: pd.DataFrame, period: int = 20) -> pd.Series:
        """Calculate CCI"""
        typical_price = (df['high'] + df['low'] + df['close']) / 3
        sma = typical_price.rolling(period).mean()
        mad = typical_price.rolling(period).apply(lambda x: np.mean(np.abs(x - x.mean())))
        
        cci = (typical_price - sma) / (0.015 * mad + 1e-10)
        return cci
    
    def _calculate_trend_strength(self, df: pd.DataFrame) -> pd.Series:
        """Calculate trend strength"""
        sma20 = df['close'].rolling(20).mean()
        sma50 = df['close'].rolling(50).mean()
        
        strength = abs(sma20 - sma50) / sma20 * 100
        return strength
    
    def _calculate_entropy(self, prices: np.ndarray, base: int = 2) -> float:
        """Calculate approximate entropy"""
        try:
            # Simple entropy based on price differences
            returns = np.diff(prices)
            if len(returns) == 0:
                return 0
            
            # Bin returns into positive/negative
            bins = np.array([returns < 0, returns >= 0])
            counts = np.sum(bins, axis=1)
            probs = counts / len(returns)
            probs = probs[probs > 0]
            
            entropy = -np.sum(probs * np.log(probs + 1e-10))
            return entropy
        except:
            return 0
    
    def _calculate_permutation_entropy(self, prices: np.ndarray, order: int = 3) -> float:
        """Calculate permutation entropy"""
        try:
            if len(prices) < order:
                return 0
            
            orderings = []
            for i in range(len(prices) - order + 1):
                ordering = tuple(np.argsort(prices[i:i+order]))
                orderings.append(ordering)
            
            unique, counts = np.unique(orderings, return_counts=True)
            probs = counts / len(orderings)
            entropy = -np.sum(probs * np.log(probs + 1e-10))
            
            return entropy / np.log(np.math.factorial(order))
        except:
            return 0
    
    def _calculate_hurst(self, prices: np.ndarray) -> float:
        """Calculate Hurst exponent"""
        try:
            if len(prices) < 10:
                return 0.5
            
            returns = np.diff(np.log(prices))
            cumulative = np.cumsum(returns)
            
            # Rescaled range analysis
            mean = np.mean(cumulative)
            deviations = cumulative - mean
            
            max_dev = np.max(deviations)
            min_dev = np.min(deviations)
            range_val = max_dev - min_dev
            
            std_dev = np.std(returns, ddof=1)
            
            if std_dev > 0 and range_val > 0:
                hurst = np.log(range_val / std_dev) / np.log(len(prices))
                return max(0, min(hurst, 1))
            
            return 0.5
        except:
            return 0.5
    
    def _calculate_dfa(self, prices: np.ndarray) -> float:
        """Calculate Detrended Fluctuation Analysis"""
        try:
            if len(prices) < 10:
                return 0.5
            
            # Simple DFA approximation
            returns = np.diff(np.log(prices))
            cumulative = np.cumsum(returns - np.mean(returns))
            
            # Fit polynomial trend
            x = np.arange(len(cumulative))
            coeffs = np.polyfit(x, cumulative, 1)
            trend = np.polyval(coeffs, x)
            
            fluctuation = np.sqrt(np.mean((cumulative - trend) ** 2))
            
            return fluctuation
        except:
            return 0.5