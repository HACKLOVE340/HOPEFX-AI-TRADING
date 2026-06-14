# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
nocode/ml_nodes.py
===================
ML Nodes for the No-Code Strategy Builder.

Enables users to incorporate machine learning predictions into their
no-code strategies without writing any ML code. Nodes connect to the
existing ML inference pipeline and model registry.

Node Types:
- PredictionNode: Get real-time predictions from trained models
- ConfidenceFilterNode: Filter signals based on ML confidence
- EnsembleNode: Combine multiple model predictions
- FeatureNode: Extract and transform features for ML input
- RegimeNode: Detect market regime using ML classification

Usage:
    from nocode.ml_nodes import MLNodeRegistry, PredictionNode

    registry = MLNodeRegistry()
    pred_node = registry.create_node("prediction", model_name="gold_direction_v3")
    result = await pred_node.execute(market_data)
"""
from __future__ import annotations

import logging
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any

import numpy as np

UTC = timezone.utc
logger = logging.getLogger(__name__)


# ── Enums ─────────────────────────────────────────────────────────────────────


class MLNodeType(Enum):
    PREDICTION = "prediction"
    CONFIDENCE_FILTER = "confidence_filter"
    ENSEMBLE = "ensemble"
    FEATURE = "feature"
    REGIME = "regime"
    ANOMALY = "anomaly"


class EnsembleMethod(Enum):
    AVERAGE = "average"
    WEIGHTED_AVERAGE = "weighted_average"
    MAJORITY_VOTE = "majority_vote"
    STACKING = "stacking"


class MarketRegime(Enum):
    TRENDING_UP = "trending_up"
    TRENDING_DOWN = "trending_down"
    RANGING = "ranging"
    HIGH_VOLATILITY = "high_volatility"
    LOW_VOLATILITY = "low_volatility"
    BREAKOUT = "breakout"


# ── Data Models ───────────────────────────────────────────────────────────────


@dataclass
class MLNodeResult:
    """Result from an ML node execution."""
    node_type: MLNodeType
    value: float | None = None
    confidence: float = 0.0
    regime: MarketRegime | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))
    latency_ms: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "node_type": self.node_type.value,
            "value": self.value,
            "confidence": self.confidence,
            "regime": self.regime.value if self.regime else None,
            "metadata": self.metadata,
            "timestamp": self.timestamp.isoformat(),
            "latency_ms": self.latency_ms,
        }


# ── Base ML Node ──────────────────────────────────────────────────────────────


class BaseMLNode(ABC):
    """Abstract base class for all ML nodes."""

    def __init__(self, node_id: str, config: dict[str, Any] | None = None) -> None:
        self.node_id = node_id
        self.config = config or {}
        self._execution_count = 0
        self._total_latency_ms = 0.0

    @property
    @abstractmethod
    def node_type(self) -> MLNodeType:
        """Return the type of this node."""

    @abstractmethod
    async def execute(self, data: dict[str, Any]) -> MLNodeResult:
        """Execute the node and return a result."""

    @property
    def avg_latency_ms(self) -> float:
        if self._execution_count == 0:
            return 0.0
        return self._total_latency_ms / self._execution_count

    def to_dict(self) -> dict[str, Any]:
        return {
            "node_id": self.node_id,
            "node_type": self.node_type.value,
            "config": self.config,
            "execution_count": self._execution_count,
            "avg_latency_ms": self.avg_latency_ms,
        }


# ── Prediction Node ──────────────────────────────────────────────────────────


class PredictionNode(BaseMLNode):
    """
    Get real-time predictions from a trained model.

    Connects to the ML inference engine to get predictions from
    any registered model in the model registry.
    """

    @property
    def node_type(self) -> MLNodeType:
        return MLNodeType.PREDICTION

    async def execute(self, data: dict[str, Any]) -> MLNodeResult:
        """Execute prediction using the inference engine."""
        start = time.time()

        model_name = self.config.get("model_name", "")
        features = self._extract_features(data)

        try:
            # Connect to the real inference engine
            from ml.inference_engine import get_inference_engine

            engine = get_inference_engine()
            prediction = await engine.predict(
                model_name=model_name,
                features=features,
            )

            latency = (time.time() - start) * 1000
            self._execution_count += 1
            self._total_latency_ms += latency

            return MLNodeResult(
                node_type=self.node_type,
                value=float(prediction.get("prediction", 0)),
                confidence=float(prediction.get("confidence", 0)),
                metadata={
                    "model_name": model_name,
                    "feature_count": len(features) if features is not None else 0,
                },
                latency_ms=latency,
            )

        except ImportError:
            # Fallback if inference engine not available
            latency = (time.time() - start) * 1000
            self._execution_count += 1
            self._total_latency_ms += latency
            return MLNodeResult(
                node_type=self.node_type,
                value=None,
                confidence=0.0,
                metadata={"error": "inference_engine_not_available"},
                latency_ms=latency,
            )
        except Exception as exc:
            latency = (time.time() - start) * 1000
            self._execution_count += 1
            self._total_latency_ms += latency
            logger.error("PredictionNode execution failed: %s", exc)
            return MLNodeResult(
                node_type=self.node_type,
                value=None,
                confidence=0.0,
                metadata={"error": str(exc)},
                latency_ms=latency,
            )

    def _extract_features(self, data: dict[str, Any]) -> np.ndarray | None:
        """Extract features from market data for model input."""
        feature_keys = self.config.get("feature_keys", [])

        if feature_keys:
            values = []
            indicators = data.get("indicators", {})
            for key in feature_keys:
                val = indicators.get(key, data.get(key))
                if val is not None:
                    values.append(float(val))
                else:
                    values.append(0.0)
            return np.array(values)

        # Default: use all available numeric indicators
        indicators = data.get("indicators", {})
        if indicators:
            values = [float(v) for v in indicators.values() if isinstance(v, (int, float))]
            return np.array(values) if values else None

        return None


# ── Confidence Filter Node ────────────────────────────────────────────────────


class ConfidenceFilterNode(BaseMLNode):
    """
    Filter signals based on ML model confidence.

    Only passes through signals where the model confidence exceeds
    a configurable threshold. Useful for reducing false signals.
    """

    @property
    def node_type(self) -> MLNodeType:
        return MLNodeType.CONFIDENCE_FILTER

    async def execute(self, data: dict[str, Any]) -> MLNodeResult:
        """Filter based on confidence threshold."""
        start = time.time()

        threshold = float(self.config.get("threshold", 0.7))
        input_confidence = float(data.get("ml_confidence", 0))
        input_value = data.get("ml_prediction")

        passes = input_confidence >= threshold

        latency = (time.time() - start) * 1000
        self._execution_count += 1
        self._total_latency_ms += latency

        return MLNodeResult(
            node_type=self.node_type,
            value=float(input_value) if input_value is not None and passes else None,
            confidence=input_confidence if passes else 0.0,
            metadata={
                "threshold": threshold,
                "passes_filter": passes,
                "input_confidence": input_confidence,
            },
            latency_ms=latency,
        )


# ── Ensemble Node ─────────────────────────────────────────────────────────────


class EnsembleNode(BaseMLNode):
    """
    Combine predictions from multiple models.

    Supports averaging, weighted averaging, majority voting,
    and stacking ensemble methods.
    """

    def __init__(self, node_id: str, config: dict[str, Any] | None = None) -> None:
        super().__init__(node_id, config)
        self._child_nodes: list[PredictionNode] = []

    @property
    def node_type(self) -> MLNodeType:
        return MLNodeType.ENSEMBLE

    def add_model(self, model_name: str, weight: float = 1.0) -> None:
        """Add a model to the ensemble."""
        node = PredictionNode(
            node_id=f"{self.node_id}_child_{len(self._child_nodes)}",
            config={"model_name": model_name, "weight": weight},
        )
        self._child_nodes.append(node)

    async def execute(self, data: dict[str, Any]) -> MLNodeResult:
        """Execute all child models and combine predictions."""
        start = time.time()

        method = EnsembleMethod(self.config.get("method", "average"))
        results: list[MLNodeResult] = []

        # Execute all child nodes
        for child in self._child_nodes:
            result = await child.execute(data)
            if result.value is not None:
                results.append(result)

        if not results:
            latency = (time.time() - start) * 1000
            self._execution_count += 1
            self._total_latency_ms += latency
            return MLNodeResult(
                node_type=self.node_type,
                value=None,
                confidence=0.0,
                metadata={"error": "no_valid_predictions"},
                latency_ms=latency,
            )

        # Combine predictions
        combined_value, combined_confidence = self._combine(results, method)

        latency = (time.time() - start) * 1000
        self._execution_count += 1
        self._total_latency_ms += latency

        return MLNodeResult(
            node_type=self.node_type,
            value=combined_value,
            confidence=combined_confidence,
            metadata={
                "method": method.value,
                "model_count": len(results),
                "individual_predictions": [r.value for r in results],
            },
            latency_ms=latency,
        )

    def _combine(
        self, results: list[MLNodeResult], method: EnsembleMethod
    ) -> tuple[float, float]:
        """Combine predictions using the specified method."""
        values = [r.value for r in results if r.value is not None]
        confidences = [r.confidence for r in results]

        if not values:
            return 0.0, 0.0

        if method == EnsembleMethod.AVERAGE:
            return float(np.mean(values)), float(np.mean(confidences))

        elif method == EnsembleMethod.WEIGHTED_AVERAGE:
            weights = [
                float(child.config.get("weight", 1.0))
                for child in self._child_nodes[:len(values)]
            ]
            total_weight = sum(weights)
            if total_weight == 0:
                return float(np.mean(values)), float(np.mean(confidences))
            weighted_val = sum(v * w for v, w in zip(values, weights)) / total_weight
            weighted_conf = sum(c * w for c, w in zip(confidences, weights)) / total_weight
            return weighted_val, weighted_conf

        elif method == EnsembleMethod.MAJORITY_VOTE:
            # Binary classification: > 0.5 = buy, <= 0.5 = sell
            votes = [1 if v > 0.5 else 0 for v in values]
            majority = sum(votes) / len(votes)
            agreement = max(majority, 1 - majority)
            return majority, agreement

        return float(np.mean(values)), float(np.mean(confidences))


# ── Regime Detection Node ─────────────────────────────────────────────────────


class RegimeNode(BaseMLNode):
    """
    Detect the current market regime using ML classification.

    Classifies the market into regimes (trending, ranging, volatile, etc.)
    to help strategies adapt their behavior.
    """

    @property
    def node_type(self) -> MLNodeType:
        return MLNodeType.REGIME

    async def execute(self, data: dict[str, Any]) -> MLNodeResult:
        """Detect market regime from price data."""
        start = time.time()

        try:
            prices = data.get("close_prices", data.get("close", []))
            if not prices or len(prices) < 20:
                return MLNodeResult(
                    node_type=self.node_type,
                    regime=MarketRegime.RANGING,
                    confidence=0.0,
                    metadata={"error": "insufficient_data"},
                    latency_ms=(time.time() - start) * 1000,
                )

            prices_arr = np.array(prices[-100:], dtype=float)

            # Calculate regime indicators
            returns = np.diff(prices_arr) / prices_arr[:-1]
            volatility = np.std(returns) * np.sqrt(252)
            trend_strength = abs(np.mean(returns)) / (np.std(returns) + 1e-10)

            # ADX-like directional strength
            sma_20 = np.mean(prices_arr[-20:])
            sma_50 = np.mean(prices_arr[-50:]) if len(prices_arr) >= 50 else sma_20
            price_vs_sma = (prices_arr[-1] - sma_20) / sma_20

            # Classify regime
            regime, confidence = self._classify_regime(
                volatility, trend_strength, price_vs_sma, returns
            )

            latency = (time.time() - start) * 1000
            self._execution_count += 1
            self._total_latency_ms += latency

            return MLNodeResult(
                node_type=self.node_type,
                value=confidence,
                confidence=confidence,
                regime=regime,
                metadata={
                    "volatility": float(volatility),
                    "trend_strength": float(trend_strength),
                    "price_vs_sma": float(price_vs_sma),
                },
                latency_ms=latency,
            )

        except Exception as exc:
            latency = (time.time() - start) * 1000
            self._execution_count += 1
            self._total_latency_ms += latency
            logger.error("RegimeNode execution failed: %s", exc)
            return MLNodeResult(
                node_type=self.node_type,
                regime=MarketRegime.RANGING,
                confidence=0.0,
                metadata={"error": str(exc)},
                latency_ms=latency,
            )

    def _classify_regime(
        self,
        volatility: float,
        trend_strength: float,
        price_vs_sma: float,
        returns: np.ndarray,
    ) -> tuple[MarketRegime, float]:
        """Classify market regime based on computed features."""
        vol_threshold = float(self.config.get("vol_threshold", 0.25))
        trend_threshold = float(self.config.get("trend_threshold", 0.3))

        # High volatility regime
        if volatility > vol_threshold:
            if trend_strength > trend_threshold:
                if price_vs_sma > 0:
                    return MarketRegime.TRENDING_UP, min(trend_strength, 1.0)
                else:
                    return MarketRegime.TRENDING_DOWN, min(trend_strength, 1.0)
            return MarketRegime.HIGH_VOLATILITY, min(volatility / vol_threshold, 1.0)

        # Low volatility
        if volatility < vol_threshold * 0.5:
            # Check for breakout potential
            recent_range = np.max(returns[-10:]) - np.min(returns[-10:])
            if recent_range > 2 * np.std(returns):
                return MarketRegime.BREAKOUT, 0.7
            return MarketRegime.LOW_VOLATILITY, 0.8

        # Trending check
        if trend_strength > trend_threshold:
            if price_vs_sma > 0:
                return MarketRegime.TRENDING_UP, min(trend_strength, 1.0)
            else:
                return MarketRegime.TRENDING_DOWN, min(trend_strength, 1.0)

        # Default: ranging
        return MarketRegime.RANGING, 0.6


# ── Anomaly Detection Node ────────────────────────────────────────────────────


class AnomalyNode(BaseMLNode):
    """
    Detect anomalous market conditions that may indicate
    unusual events (flash crashes, liquidity gaps, etc.).
    """

    @property
    def node_type(self) -> MLNodeType:
        return MLNodeType.ANOMALY

    async def execute(self, data: dict[str, Any]) -> MLNodeResult:
        """Detect anomalies in market data."""
        start = time.time()

        try:
            prices = data.get("close_prices", data.get("close", []))
            volumes = data.get("volumes", data.get("volume", []))

            if not prices or len(prices) < 30:
                return MLNodeResult(
                    node_type=self.node_type,
                    value=0.0,
                    confidence=0.0,
                    metadata={"error": "insufficient_data"},
                    latency_ms=(time.time() - start) * 1000,
                )

            prices_arr = np.array(prices[-100:], dtype=float)
            returns = np.diff(prices_arr) / prices_arr[:-1]

            # Z-score based anomaly detection
            mean_return = np.mean(returns[:-1])
            std_return = np.std(returns[:-1])
            latest_return = returns[-1]

            z_score = abs(latest_return - mean_return) / (std_return + 1e-10)

            # Volume anomaly (if available)
            vol_anomaly = 0.0
            if volumes and len(volumes) >= 30:
                vol_arr = np.array(volumes[-30:], dtype=float)
                vol_mean = np.mean(vol_arr[:-1])
                vol_std = np.std(vol_arr[:-1])
                vol_anomaly = abs(vol_arr[-1] - vol_mean) / (vol_std + 1e-10)

            # Combined anomaly score
            threshold = float(self.config.get("z_threshold", 3.0))
            anomaly_score = max(z_score, vol_anomaly)
            is_anomaly = anomaly_score > threshold

            latency = (time.time() - start) * 1000
            self._execution_count += 1
            self._total_latency_ms += latency

            return MLNodeResult(
                node_type=self.node_type,
                value=float(anomaly_score),
                confidence=min(anomaly_score / threshold, 1.0) if is_anomaly else 0.0,
                metadata={
                    "z_score": float(z_score),
                    "vol_anomaly": float(vol_anomaly),
                    "is_anomaly": is_anomaly,
                    "threshold": threshold,
                },
                latency_ms=latency,
            )

        except Exception as exc:
            latency = (time.time() - start) * 1000
            self._execution_count += 1
            self._total_latency_ms += latency
            return MLNodeResult(
                node_type=self.node_type,
                value=0.0,
                confidence=0.0,
                metadata={"error": str(exc)},
                latency_ms=latency,
            )


# ── ML Node Registry ─────────────────────────────────────────────────────────


class MLNodeRegistry:
    """
    Registry for creating and managing ML nodes in the No-Code builder.

    Provides a factory method for creating nodes by type and manages
    the lifecycle of all active nodes.
    """

    def __init__(self) -> None:
        self._nodes: dict[str, BaseMLNode] = {}
        self._node_counter = 0

    def create_node(
        self, node_type: str, config: dict[str, Any] | None = None, **kwargs: Any
    ) -> BaseMLNode:
        """Create a new ML node of the specified type."""
        self._node_counter += 1
        node_id = f"ml_node_{self._node_counter}"

        # Merge kwargs into config
        node_config = config or {}
        node_config.update(kwargs)

        node_type_enum = MLNodeType(node_type)

        if node_type_enum == MLNodeType.PREDICTION:
            node = PredictionNode(node_id, node_config)
        elif node_type_enum == MLNodeType.CONFIDENCE_FILTER:
            node = ConfidenceFilterNode(node_id, node_config)
        elif node_type_enum == MLNodeType.ENSEMBLE:
            node = EnsembleNode(node_id, node_config)
        elif node_type_enum == MLNodeType.REGIME:
            node = RegimeNode(node_id, node_config)
        elif node_type_enum == MLNodeType.ANOMALY:
            node = AnomalyNode(node_id, node_config)
        else:
            raise ValueError(f"Unknown ML node type: {node_type}")

        self._nodes[node_id] = node
        return node

    def get_node(self, node_id: str) -> BaseMLNode | None:
        """Get a node by ID."""
        return self._nodes.get(node_id)

    def remove_node(self, node_id: str) -> bool:
        """Remove a node from the registry."""
        return self._nodes.pop(node_id, None) is not None

    def list_nodes(self) -> list[dict[str, Any]]:
        """List all registered nodes."""
        return [node.to_dict() for node in self._nodes.values()]

    def get_available_types(self) -> list[dict[str, Any]]:
        """Get all available ML node types with descriptions."""
        return [
            {
                "type": MLNodeType.PREDICTION.value,
                "name": "Prediction",
                "description": "Get real-time predictions from trained ML models",
                "config_schema": {"model_name": "str", "feature_keys": "list[str]"},
            },
            {
                "type": MLNodeType.CONFIDENCE_FILTER.value,
                "name": "Confidence Filter",
                "description": "Filter signals by ML confidence threshold",
                "config_schema": {"threshold": "float (0-1)"},
            },
            {
                "type": MLNodeType.ENSEMBLE.value,
                "name": "Ensemble",
                "description": "Combine predictions from multiple models",
                "config_schema": {"method": "average|weighted_average|majority_vote"},
            },
            {
                "type": MLNodeType.REGIME.value,
                "name": "Regime Detection",
                "description": "Detect current market regime (trending, ranging, etc.)",
                "config_schema": {"vol_threshold": "float", "trend_threshold": "float"},
            },
            {
                "type": MLNodeType.ANOMALY.value,
                "name": "Anomaly Detection",
                "description": "Detect anomalous market conditions",
                "config_schema": {"z_threshold": "float"},
            },
        ]


# ── Module-level singleton ────────────────────────────────────────────────────

_registry: MLNodeRegistry | None = None


def get_ml_node_registry() -> MLNodeRegistry:
    """Return the module-level MLNodeRegistry singleton."""
    global _registry
    if _registry is None:
        _registry = MLNodeRegistry()
    return _registry
