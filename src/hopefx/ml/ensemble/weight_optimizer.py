"""Dynamic ensemble weight optimization."""

from __future__ import annotations

import numpy as np
from scipy.optimize import minimize
from typing import Dict, List
from dataclasses import dataclass


@dataclass
class ModelPerformance:
    model_id: str
    recent_returns: List[float]
    sharpe: float
    max_dd: float
    prediction_accuracy: float


class EnsembleOptimizer:
    """Optimize model weights using Bayesian methods."""

    def __init__(self, lookback_window: int = 30) -> None:
        self.lookback = lookback_window
        self.performance_history: Dict[str, List[ModelPerformance]] = {}
        self.current_weights: Dict[str, float] = {}

    def update_weights(self, performances: List[ModelPerformance]) -> Dict[str, float]:
        """Calculate optimal weights using Sharpe ratio optimization."""
        if len(performances) < 2:
            return {p.model_id: 1.0 / len(performances) for p in performances}

        # Objective: maximize Sharpe ratio of ensemble
        def negative_sharpe(weights: np.ndarray) -> float:
            ensemble_returns = np.zeros(self.lookback)
            for i, perf in enumerate(performances):
                ensemble_returns += weights[i] * np.array(perf.recent_returns)
            
            if np.std(ensemble_returns) == 0:
                return 0
            
            sharpe = np.mean(ensemble_returns) / np.std(ensemble_returns)
            return -sharpe  # Minimize negative Sharpe

        # Constraints: weights sum to 1, each weight >= 0
        constraints = {'type': 'eq', 'fun': lambda w: np.sum(w) - 1}
        bounds = [(0, 1) for _ in performances]
        
        # Initial guess: equal weights
        x0 = np.ones(len(performances)) / len(performances)

        result = minimize(
            negative_sharpe,
            x0,
            method='SLSQP',
            bounds=bounds,
            constraints=constraints
        )

        self.current_weights = {
            perf.model_id: weight 
            for perf, weight in zip(performances, result.x)
        }

        return self.current_weights

    def get_confidence_adjusted_prediction(
        self,
        predictions: Dict[str, float],
        confidences: Dict[str, float]
    ) -> float:
        """Weight predictions by model confidence."""
        total_weight = 0
        weighted_sum = 0

        for model_id, pred in predictions.items():
            weight = self.current_weights.get(model_id, 0.5)
            confidence = confidences.get(model_id, 0.5)
            adjusted_weight = weight * confidence
            
            weighted_sum += pred * adjusted_weight
            total_weight += adjusted_weight

        return weighted_sum / total_weight if total_weight > 0 else 0.5
