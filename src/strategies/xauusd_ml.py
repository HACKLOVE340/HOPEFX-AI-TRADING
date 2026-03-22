"""
XAUUSD ML-powered trading strategy.
"""

import numpy as np
import pandas as pd
from datetime import datetime

from src.domain.enums import SignalStrength, TradeDirection
from src.domain.models import Account, MarketData, OHLCV, Signal
from src.ml.features import FeatureEngineer
from src.ml.models.ensemble import EnsembleModel
from src.strategies.base import Strategy


class XAUUSDMLStrategy(Strategy):
    """
    XAUUSD-specific ML strategy with gold market microstructure awareness.
    """
    
    def __init__(
        self,
        strategy_id: str = "xauusd_ml_ensemble",
        parameters: dict | None = None
    ):
        super().__init__(strategy_id, parameters)
        
        self.feature_engineer = FeatureEngineer(
            lookback=parameters.get("lookback", 100)
        )
        self.model: EnsembleModel | None = None
        self._price_history: list[OHLCV] = []
        self._min_history = 50
        self._prediction_threshold = parameters.get("threshold", 0.6)
        self._cooldown_minutes = parameters.get("cooldown", 15)
        self._last_signal_time: datetime | None = None
    
    async def initialize(self) -> None:
        """Load ML model."""
        from src.ml.registry import ModelRegistry
        
        registry = ModelRegistry()
        self.model = registry.get_production_model("xauusd_ensemble")
        self._initialized = True
    
    async def on_market_data(self, data: MarketData) -> Signal | None:
        """Generate trading signal from ML prediction."""
        if isinstance(data, OHLCV):
            self._price_history.append(data)
        
        # Maintain window
        if len(self._price_history) > self._min_history * 2:
            self._price_history = self._price_history[-self._min_history * 2:]
        
        # Check cooldown
        if self._last_signal_time:
            time_since = (datetime.now() - self._last_signal_time).total_seconds() / 60
            if time_since < self._cooldown_minutes:
                return None
        
        # Need minimum history
        if len(self._price_history) < self._min_history:
            return None
        
        # Generate features
        df = self._ohlcv_to_dataframe(self._price_history)
        features_df = self.feature_engineer.create_features(df)
        
        if len(features_df) < 1:
            return None
        
        # Get feature vector
        feature_cols = self.feature_engineer.get_feature_columns()
        latest_features = features_df[feature_cols].iloc[-1:].values
        
        # Predict
        if self.model:
            proba = self.model.predict_proba(latest_features)[0]
            prediction = 1 if proba > self._prediction_threshold else 0
            
            # Determine direction and strength
            if proba > self._prediction_threshold:
                direction = TradeDirection.LONG
                strength = (proba - 0.5) * 2  # Scale to 0-1
            elif proba < (1 - self._prediction_threshold):
                direction = TradeDirection.SHORT
                strength = ((1 - proba) - 0.5) * 2
            else:
                return None
            
            # Map strength to enum
            if strength > 0.8:
                signal_strength = SignalStrength.VERY_STRONG
            elif strength > 0.6:
                signal_strength = SignalStrength.STRONG
            elif strength > 0.4:
                signal_strength = SignalStrength.MODERATE
            else:
                signal_strength = SignalStrength.WEAK
            
            signal = Signal(
                strategy_id=self.strategy_id,
                symbol="XAUUSD",
                direction=direction,
                strength=float(strength),
                confidence=float(proba),
                features={
                    "rsi": float(features_df["rsi_14"].iloc[-1]),
                    "atr_ratio": float(features_df["atr_ratio"].iloc[-1]),
                    "macd": float(features_df["MACD_12_26_9"].iloc[-1]),
                    "bb_position": float(features_df["bb_position"].iloc[-1]),
                },
                metadata={
                    "model_version": self.model.version,
                    "signal_strength": signal_strength.value
                }
            )
            
            self._metrics["signals_generated"] += 1
            self._last_signal_time = datetime.now()
            
            return signal
        
        return None
    
    def _ohlcv_to_dataframe(self, ohlcv_list: list[OHLCV]) -> pd.DataFrame:
        """Convert OHLCV list to DataFrame."""
        data = {
            "open": [float(o.open) for o in ohlcv_list],
            "high": [float(o.high) for o in ohlcv_list],
            "low": [float(o.low) for o in ohlcv_list],
            "close": [float(o.close) for o in ohlcv_list],
            "volume": [o.volume for o in ohlcv_list],
        }
        index = [o.timestamp for o in ohlcv_list]
        return pd.DataFrame(data, index=index)
    
    async def on_fill(self, order_id: str, fill_price: float, quantity: float) -> None:
        """Track fills."""
        self._metrics["trades_taken"] += 1
