"""
Feature engineering for XAUUSD ML pipeline.
"""

import numpy as np
import pandas as pd
import pandas_ta as ta
from typing import Literal


class FeatureEngineer:
    """
    Production feature engineering with TA-Lib indicators.
    Generates features for LSTM/XGBoost models.
    """
    
    def __init__(self, lookback: int = 100):
        self.lookback = lookback
    
    def create_features(
        self,
        df: pd.DataFrame,
        include_targets: bool = False
    ) -> pd.DataFrame:
        """
        Generate feature set from OHLCV data.
        
        Features:
        - Price action: returns, log returns, volatility
        - Technical: RSI, MACD, Bollinger, ATR, OBV, VWAP
        - Microstructure: order flow imbalance (if available)
        - Temporal: cyclical time features
        """
        data = df.copy()
        
        # Basic returns
        data["returns"] = data["close"].pct_change()
        data["log_returns"] = np.log(data["close"] / data["close"].shift(1))
        data["volatility_20"] = data["returns"].rolling(20).std()
        
        # RSI
        data["rsi_14"] = ta.rsi(data["close"], length=14)
        data["rsi_7"] = ta.rsi(data["close"], length=7)
        
        # MACD
        macd = ta.macd(data["close"])
        data = pd.concat([data, macd], axis=1)
        
        # Bollinger Bands
        bbands = ta.bbands(data["close"], length=20, std=2)
        data = pd.concat([data, bbands], axis=1)
        data["bb_position"] = (data["close"] - data["BBL_20_2.0"]) / (
            data["BBU_20_2.0"] - data["BBL_20_2.0"]
        )
        
        # ATR
        data["atr_14"] = ta.atr(data["high"], data["low"], data["close"], length=14)
        data["atr_ratio"] = data["atr_14"] / data["close"]
        
        # OBV
        data["obv"] = ta.obv(data["close"], data["volume"])
        data["obv_ema"] = ta.ema(data["obv"], length=20)
        
        # VWAP
        data["vwap"] = ta.vwap(data["high"], data["low"], data["close"], data["volume"])
        data["vwap_deviation"] = (data["close"] - data["vwap"]) / data["vwap"]
        
        # Moving averages
        data["sma_20"] = ta.sma(data["close"], length=20)
        data["sma_50"] = ta.sma(data["close"], length=50)
        data["ema_12"] = ta.ema(data["close"], length=12)
        data["ema_26"] = ta.ema(data["close"], length=26)
        
        # Trend strength
        data["adx"] = ta.adx(data["high"], data["low"], data["close"])["ADX_14"]
        
        # Cyclical time features
        data["hour_sin"] = np.sin(2 * np.pi * data.index.hour / 24)
        data["hour_cos"] = np.cos(2 * np.pi * data.index.hour / 24)
        data["dayofweek_sin"] = np.sin(2 * np.pi * data.index.dayofweek / 7)
        data["dayofweek_cos"] = np.cos(2 * np.pi * data.index.dayofweek / 7)
        
        # Lagged features
        for lag in [1, 3, 5, 10]:
            data[f"returns_lag_{lag}"] = data["returns"].shift(lag)
            data[f"rsi_lag_{lag}"] = data["rsi_14"].shift(lag)
        
        # Target (future returns)
        if include_targets:
            data["target_1h"] = data["close"].shift(-1) / data["close"] - 1
            data["target_direction"] = (data["target_1h"] > 0).astype(int)
        
        # Drop NaN
        data = data.dropna()
        
        return data
    
    def get_feature_columns(self) -> list[str]:
        """Return list of feature column names."""
        return [
            "returns", "log_returns", "volatility_20",
            "rsi_14", "rsi_7", "MACD_12_26_9", "MACDh_12_26_9", "MACDs_12_26_9",
            "bb_position", "atr_ratio", "obv_ema",
            "vwap_deviation", "sma_20", "sma_50", "ema_12", "ema_26", "adx",
            "hour_sin", "hour_cos", "dayofweek_sin", "dayofweek_cos",
            "returns_lag_1", "returns_lag_3", "returns_lag_5", "returns_lag_10",
            "rsi_lag_1", "rsi_lag_3", "rsi_lag_5", "rsi_lag_10"
        ]
