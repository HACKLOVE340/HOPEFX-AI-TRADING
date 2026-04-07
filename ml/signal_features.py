# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
HOPEFX ML Feature Engineering
Advanced features for AI signal generation
"""

import logging
from collections import deque
from dataclasses import dataclass
from typing import Any

import numpy as np

logger = logging.getLogger(__name__)


@dataclass
class FeatureVector:
    """ML feature vector"""

    symbol: str
    timestamp: float
    features: dict[str, float]
    label: float | None = None  # For training

    def to_array(self) -> np.ndarray:
        """Convert to numpy array"""
        return np.array(list(self.features.values()))

    def to_dict(self) -> dict:
        """Convert to plain dictionary."""
        return {
            "symbol": self.symbol,
            "timestamp": self.timestamp,
            "features": self.features,
            "label": self.label,
        }


class TechnicalIndicators:
    """Technical analysis indicators"""

    @staticmethod
    def sma(prices: np.ndarray, period: int) -> np.ndarray:
        """Simple Moving Average"""
        return np.convolve(prices, np.ones(period) / period, mode="valid")

    @staticmethod
    def ema(prices: np.ndarray, period: int) -> np.ndarray:
        """Exponential Moving Average"""
        alpha = 2 / (period + 1)
        ema = np.zeros_like(prices)
        ema[0] = prices[0]
        for i in range(1, len(prices)):
            ema[i] = alpha * prices[i] + (1 - alpha) * ema[i - 1]
        return ema

    @staticmethod
    def rsi(prices: np.ndarray, period: int = 14) -> np.ndarray:
        """Relative Strength Index"""
        deltas = np.diff(prices)
        gains = np.where(deltas > 0, deltas, 0)
        losses = np.where(deltas < 0, -deltas, 0)

        avg_gains = np.convolve(gains, np.ones(period) / period, mode="valid")
        avg_losses = np.convolve(losses, np.ones(period) / period, mode="valid")

        rs = avg_gains / (avg_losses + 1e-10)
        rsi = 100 - (100 / (1 + rs))
        return rsi

    @staticmethod
    def bollinger_bands(
        prices: np.ndarray,
        period: int = 20,
        std_dev: float = 2.0,
    ) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        """Bollinger Bands"""
        sma = TechnicalIndicators.sma(prices, period)
        std = np.array(
            [np.std(prices[i : i + period]) for i in range(len(prices) - period + 1)],
        )

        upper = sma + (std * std_dev)
        lower = sma - (std * std_dev)
        return upper, sma, lower

    @staticmethod
    def macd(
        prices: np.ndarray,
        fast: int = 12,
        slow: int = 26,
        signal: int = 9,
    ) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        """MACD"""
        ema_fast = TechnicalIndicators.ema(prices, fast)
        ema_slow = TechnicalIndicators.ema(prices, slow)

        macd_line = ema_fast[-len(ema_slow) :] - ema_slow
        signal_line = TechnicalIndicators.ema(macd_line, signal)
        histogram = macd_line[-len(signal_line) :] - signal_line

        return macd_line[-len(signal_line) :], signal_line, histogram

    @staticmethod
    def atr(
        high: np.ndarray,
        low: np.ndarray,
        close: np.ndarray,
        period: int = 14,
    ) -> np.ndarray:
        """Average True Range"""
        tr1 = high[1:] - low[1:]
        tr2 = np.abs(high[1:] - close[:-1])
        tr3 = np.abs(low[1:] - close[:-1])

        true_range = np.maximum(np.maximum(tr1, tr2), tr3)
        atr = np.convolve(true_range, np.ones(period) / period, mode="valid")
        return atr

    @staticmethod
    def obv(close: np.ndarray, volume: np.ndarray) -> np.ndarray:
        """On-Balance Volume"""
        obv = np.zeros_like(close)
        obv[0] = volume[0]

        for i in range(1, len(close)):
            if close[i] > close[i - 1]:
                obv[i] = obv[i - 1] + volume[i]
            elif close[i] < close[i - 1]:
                obv[i] = obv[i - 1] - volume[i]
            else:
                obv[i] = obv[i - 1]

        return obv


class FeatureEngineer:
    """
    ML feature engineering for trading signals

    Creates features from:
    - Price action (OHLCV)
    - Technical indicators
    - Market microstructure
    - Cross-asset relationships
    """

    def __init__(self, lookback_periods: list[int] | None = None):
        self.lookback_periods = lookback_periods or [5, 10, 20, 50]
        self._feature_cache: dict[str, deque] = {}
        self._cache_size = 1000

    def extract_features(
        self,
        symbol: str,
        ohlcv_data: list[Any],
        order_book: dict | None = None,
    ) -> FeatureVector | None:
        """
        Extract ML features from market data.

        Returns FeatureVector or None if insufficient data.
        """
        if len(ohlcv_data) < max(self.lookback_periods) + 10:
            return None

        try:
            # Convert to arrays
            opens = np.array([c.open for c in ohlcv_data])
            highs = np.array([c.high for c in ohlcv_data])
            lows = np.array([c.low for c in ohlcv_data])
            closes = np.array([c.close for c in ohlcv_data])
            volumes = np.array([c.volume for c in ohlcv_data])

            features: dict[str, float] = {}
            current_price = closes[-1]

            self._add_price_features(features, closes, highs, lows, volumes, current_price)
            self._add_indicator_features(features, closes, highs, lows, current_price)

            # 3. Market microstructure features (if order book provided)
            if order_book:
                bids = order_book.get("bids", [])
                asks = order_book.get("asks", [])

                if bids and asks:
                    best_bid = bids[0][0]
                    best_ask = asks[0][0]
                    spread = best_ask - best_bid
                    mid_price = (best_ask + best_bid) / 2

                    features["spread"] = spread
                    features["spread_pct"] = spread / mid_price if mid_price > 0 else 0

                    # Order book imbalance
                    bid_volume = sum(b[1] for b in bids[:5])
                    ask_volume = sum(a[1] for a in asks[:5])
                    features["ob_imbalance"] = (
                        (bid_volume - ask_volume) / (bid_volume + ask_volume + 1e-10)
                    )

            # 4. Pattern features — candlestick patterns
            features["body_size"] = abs(closes[-1] - opens[-1]) / (highs[-1] - lows[-1] + 1e-10)
            features["upper_shadow"] = (
                (highs[-1] - max(opens[-1], closes[-1])) / (highs[-1] - lows[-1] + 1e-10)
            )
            features["lower_shadow"] = (
                (min(opens[-1], closes[-1]) - lows[-1]) / (highs[-1] - lows[-1] + 1e-10)
            )

            # Trend strength
            if len(closes) >= 20:
                slope = np.polyfit(range(20), closes[-20:], 1)[0]
                features["trend_slope"] = slope / current_price if current_price > 0 else 0

            # Create and cache feature vector
            feature_vector = FeatureVector(
                symbol=symbol,
                timestamp=ohlcv_data[-1].timestamp if hasattr(ohlcv_data[-1], "timestamp") else 0,
                features=features,
            )

            if symbol not in self._feature_cache:
                self._feature_cache[symbol] = deque(maxlen=self._cache_size)
            self._feature_cache[symbol].append(feature_vector)

            return feature_vector

        except Exception as exc:  # pylint: disable=broad-exception-caught
            logger.error("Feature extraction error for %s: %s", symbol, exc)
            return None

    def _add_price_features(
        self,
        features: dict[str, float],
        closes: "np.ndarray",
        highs: "np.ndarray",
        lows: "np.ndarray",
        volumes: "np.ndarray",
        current_price: float,
    ) -> None:
        """Populate price-based and volume features for each lookback period."""
        for period in self.lookback_periods:
            features[f"return_{period}"] = (closes[-1] / closes[-period]) - 1
            features[f"volatility_{period}"] = np.std(
                np.diff(closes[-period:]) / closes[-period:-1],
            )
            period_high = np.max(highs[-period:])
            period_low = np.min(lows[-period:])
            features[f"price_position_{period}"] = (
                (current_price - period_low) / (period_high - period_low + 1e-10)
            )
            features[f"volume_trend_{period}"] = (
                np.mean(volumes[-period:]) / np.mean(volumes[-period * 2 : -period]) - 1
            )

    def _add_indicator_features(
        self,
        features: dict[str, float],
        closes: "np.ndarray",
        highs: "np.ndarray",
        lows: "np.ndarray",
        current_price: float,
    ) -> None:
        """Populate RSI, MACD, Bollinger Bands, and ATR features."""
        # RSI
        rsi = TechnicalIndicators.rsi(closes, 14)
        features["rsi"] = rsi[-1] if rsi.size > 0 else 50

        # MACD
        macd_line, signal_line, histogram = TechnicalIndicators.macd(closes)
        features["macd"] = macd_line[-1] if macd_line.size > 0 else 0
        features["macd_signal"] = signal_line[-1] if signal_line.size > 0 else 0
        features["macd_hist"] = histogram[-1] if histogram.size > 0 else 0

        # Bollinger Bands
        upper, middle, lower = TechnicalIndicators.bollinger_bands(closes)
        if upper.size > 0:
            features["bb_upper"] = upper[-1]
            features["bb_middle"] = middle[-1]
            features["bb_lower"] = lower[-1]
            features["bb_position"] = (
                (current_price - lower[-1]) / (upper[-1] - lower[-1] + 1e-10)
            )

        # ATR
        atr = TechnicalIndicators.atr(highs, lows, closes)
        features["atr"] = atr[-1] if atr.size > 0 else 0
        features["atr_pct"] = features["atr"] / current_price if current_price > 0 else 0

    @staticmethod
    def get_feature_importance(model: Any) -> dict[str, float]:
        """
        Return feature importances from a trained model.

        Supports:
        - sklearn / XGBoost models with ``feature_importances_`` attribute
        - Models with a ``get_feature_importances()`` method (XGBoostPredictor)

        Raises
        ------
        ValueError
            If the model exposes no recognised importance interface.
        """
        if model is None:
            raise ValueError("A trained model must be supplied; no model provided.")

        # XGBoostPredictor wrapper (ml/pipeline.py)
        if hasattr(model, "get_feature_importances") and callable(model.get_feature_importances):
            return model.get_feature_importances()

        # sklearn / XGBoost / LightGBM native attribute
        if hasattr(model, "feature_importances_"):
            importances = model.feature_importances_
            names = [str(i) for i in range(len(importances))]
            return dict(zip(names, importances.tolist(), strict=False))

        raise ValueError(
            f"Model of type {type(model).__name__!r} does not expose"
            " feature_importances_ or get_feature_importances()."
        )

    def detect_anomalies(self, symbol: str, threshold: float = 3.0) -> list[dict]:
        """
        Detect anomalous market conditions
        """
        if symbol not in self._feature_cache or len(self._feature_cache[symbol]) < 100:
            return []

        recent = list(self._feature_cache[symbol])[-100:]
        anomalies = []

        for feature_name in ["volatility_20", "rsi", "atr_pct"]:
            values = [r.features.get(feature_name, 0) for r in recent]
            mean = np.mean(values)
            std = np.std(values)

            current_value = recent[-1].features.get(feature_name, 0)
            z_score = abs(current_value - mean) / (std + 1e-10)

            if z_score > threshold:
                anomalies.append(
                    {
                        "feature": feature_name,
                        "value": current_value,
                        "z_score": z_score,
                        "mean": mean,
                        "std": std,
                        "severity": "high" if z_score > 5 else "medium",
                    },
                )

        return anomalies


class SignalEnsemble:
    """
    Ensemble of ML models for signal generation
    """

    def __init__(self):
        self.models: dict[str, Any] = {}
        self.weights: dict[str, float] = {}

    def add_model(self, name: str, model: Any, weight: float = 1.0):
        """Add model to ensemble"""
        self.models[name] = model
        self.weights[name] = weight

    def predict(self, features: FeatureVector) -> dict[str, Any]:
        """
        Generate ensemble prediction
        """
        predictions = {}
        total_weight = 0
        weighted_sum = 0

        for name, model in self.models.items():
            try:
                # Get prediction from model
                pred = self._get_model_prediction(model, features)
                predictions[name] = pred

                weight = self.weights.get(name, 1.0)
                weighted_sum += pred["probability"] * weight
                total_weight += weight

            except Exception as exc:  # pylint: disable=broad-exception-caught
                logger.error("Model %s prediction error: %s", name, exc)

        if total_weight == 0:
            return {"action": "hold", "confidence": 0, "probability": 0.5}

        ensemble_prob = weighted_sum / total_weight

        # Determine action
        if ensemble_prob > 0.7:
            action = "buy"
        elif ensemble_prob < 0.3:
            action = "sell"
        else:
            action = "hold"

        return {
            "action": action,
            "confidence": abs(ensemble_prob - 0.5) * 2,  # 0 to 1
            "probability": ensemble_prob,
            "individual_predictions": predictions,
        }

    def _get_model_prediction(self, model: Any, features: FeatureVector) -> dict:
        """
        Obtain a probability estimate from a single model.

        Supported interfaces (tried in order):
        1. ``predict_proba(X)`` — sklearn / XGBoost classifiers; returns P(class=1).
        2. ``predict(X)``       — models that return a probability directly (0–1).

        The feature vector is converted to a 2-D numpy array (1 × n_features)
        using the insertion order of ``features.features``.

        Raises
        ------
        TypeError
            If the model exposes neither ``predict_proba`` nor ``predict``.
        """
        X = features.to_array().reshape(1, -1)

        if hasattr(model, "predict_proba") and callable(model.predict_proba):
            proba = model.predict_proba(X)
            # sklearn returns shape (1, n_classes); take P(class=1)
            prob = float(proba[0, 1]) if proba.ndim == 2 else float(proba[0])
        elif hasattr(model, "predict") and callable(model.predict):
            raw = model.predict(X)
            prob = float(raw[0])
        else:
            raise TypeError(f"Model of type {type(model).__name__!r} exposes neither predict_proba() nor predict().")

        return {
            "probability": prob,
            "raw_output": {"feature_count": len(features.features)},
        }
