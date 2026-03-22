"""
Feature engineering for XAUUSD ML pipeline.
"""

import numpy as np
import pandas as pd
import ta
from typing import Literal


class FeatureEngineer:
    """
    Production feature engineering with technical indicators.
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
        data["rsi_14"] = ta.momentum.RSIIndicator(data["close"], window=14).rsi()
        data["rsi_7"]  = ta.momentum.RSIIndicator(data["close"], window=7).rsi()

        # MACD
        macd_ind = ta.trend.MACD(data["close"], window_slow=26, window_fast=12, window_sign=9)
        data["MACD_12_26_9"]  = macd_ind.macd()
        data["MACDh_12_26_9"] = macd_ind.macd_diff()
        data["MACDs_12_26_9"] = macd_ind.macd_signal()

        # Bollinger Bands
        bb = ta.volatility.BollingerBands(data["close"], window=20, window_dev=2)
        data["BBL_20_2.0"] = bb.bollinger_lband()
        data["BBU_20_2.0"] = bb.bollinger_hband()
        data["bb_position"] = (data["close"] - data["BBL_20_2.0"]) / (
            data["BBU_20_2.0"] - data["BBL_20_2.0"]
        )

        # ATR
        atr_ind = ta.volatility.AverageTrueRange(
            data["high"], data["low"], data["close"], window=14
        )
        data["atr_14"]    = atr_ind.average_true_range()
        data["atr_ratio"] = data["atr_14"] / data["close"]

        # OBV
        data["obv"]     = ta.volume.OnBalanceVolumeIndicator(data["close"], data["volume"]).on_balance_volume()
        data["obv_ema"] = data["obv"].ewm(span=20, adjust=False).mean()

        # VWAP (rolling approximation)
        typical_price          = (data["high"] + data["low"] + data["close"]) / 3
        data["vwap"]           = (typical_price * data["volume"]).rolling(20).sum() / data["volume"].rolling(20).sum()
        data["vwap_deviation"] = (data["close"] - data["vwap"]) / data["vwap"]

        # Moving averages
        data["sma_20"] = ta.trend.SMAIndicator(data["close"], window=20).sma_indicator()
        data["sma_50"] = ta.trend.SMAIndicator(data["close"], window=50).sma_indicator()
        data["ema_12"] = ta.trend.EMAIndicator(data["close"], window=12).ema_indicator()
        data["ema_26"] = ta.trend.EMAIndicator(data["close"], window=26).ema_indicator()

        # Trend strength (ADX)
        adx_ind     = ta.trend.ADXIndicator(data["high"], data["low"], data["close"], window=14)
        data["adx"] = adx_ind.adx()

        # Cyclical time features
        data["hour_sin"]      = np.sin(2 * np.pi * data.index.hour / 24)
        data["hour_cos"]      = np.cos(2 * np.pi * data.index.hour / 24)
        data["dayofweek_sin"] = np.sin(2 * np.pi * data.index.dayofweek / 7)
        data["dayofweek_cos"] = np.cos(2 * np.pi * data.index.dayofweek / 7)

        # Lagged features
        for lag in [1, 3, 5, 10]:
            data[f"returns_lag_{lag}"] = data["returns"].shift(lag)
            data[f"rsi_lag_{lag}"]     = data["rsi_14"].shift(lag)

        # Target (future returns)
        if include_targets:
            data["target_1h"]        = data["close"].shift(-1) / data["close"] - 1
            data["target_direction"] = (data["target_1h"] > 0).astype(int)

        return data.dropna()

    def get_feature_columns(self) -> list[str]:
        """Return list of feature column names."""
        return [
            "returns", "log_returns", "volatility_20",
            "rsi_14", "rsi_7", "MACD_12_26_9", "MACDh_12_26_9", "MACDs_12_26_9",
            "bb_position", "atr_ratio", "obv_ema",
            "vwap_deviation", "sma_20", "sma_50", "ema_12", "ema_26", "adx",
            "hour_sin", "hour_cos", "dayofweek_sin", "dayofweek_cos",
            "returns_lag_1", "returns_lag_3", "returns_lag_5", "returns_lag_10",
            "rsi_lag_1", "rsi_lag_3", "rsi_lag_5", "rsi_lag_10",
        ]
