"""Rolling window cross-validation for production."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd
from sklearn.model_selection import TimeSeriesSplit
from sklearn.metrics import mean_squared_error, r2_score

import structlog

logger = structlog.get_logger()


@dataclass
class CVResult:
    fold: int
    train_start: str
    train_end: str
    test_start: str
    test_end: str
    mse: float
    r2: float
    feature_importance: dict[str, float]


class RollingCrossValidator:
    """4-hour rolling CV with PurgedKFold."""
    
    def __init__(
        self,
        n_splits: int = 5,
        purge_gap: int = 10,
        retrain_interval_hours: float = 4.0
    ):
        self.n_splits = n_splits
        self.purge_gap = purge_gap
        self.retrain_interval = retrain_interval_hours * 3600
        
        self._last_retrain = 0.0
        self._cv_history: list[CVResult] = []
        self._is_retraining = False
    
    async def check_and_retrain(
        self,
        model: Any,
        data: pd.DataFrame,
        feature_cols: list[str],
        target_col: str
    ) -> bool:
        """Check if retrain needed and execute."""
        now = asyncio.get_event_loop().time()
        
        if now - self._last_retrain < self.retrain_interval:
            return False
        
        if self._is_retraining:
            return False
        
        self._is_retraining = True
        
        try:
            results = await self._execute_cv(model, data, feature_cols, target_col)
            
            # Check for degradation
            recent_r2 = [r.r2 for r in results]
            if np.mean(recent_r2) < 0.3:  # Model degraded
                logger.critical(f"Model degraded: R2={np.mean(recent_r2):.3f}")
                # Trigger fallback or alert
            
            self._cv_history.extend(results)
            self._last_retrain = now
            
            return True
            
        finally:
            self._is_retraining = False
    
    async def _execute_cv(
        self,
        model: Any,
        data: pd.DataFrame,
        feature_cols: list[str],
        target_col: str
    ) -> list[CVResult]:
        """Execute time-series CV."""
        from src.ml.training import PurgedKFold
        
        X = data[feature_cols].values
        y = data[target_col].values
        
        cv = PurgedKFold(n_splits=self.n_splits, purge_gap=self.purge_gap)
        
        results = []
        for fold, (train_idx, test_idx) in enumerate(cv.split(X)):
            X_train, X_test = X[train_idx], X[test_idx]
            y_train, y_test = y[train_idx], y[test_idx]
            
            # Async fit
            await asyncio.to_thread(model.fit, X_train, y_train)
            
            # Predict
            y_pred = model.predict(X_test)
            
            mse = mean_squared_error(y_test, y_pred)
            r2 = r2_score(y_test, y_pred)
            
            # Feature importance (if available)
            importance = {}
            if hasattr(model, "feature_importances_"):
                importance = dict(zip(feature_cols, model.feature_importances_))
            
            result = CVResult(
                fold=fold,
                train_start=str(data.index[train_idx[0]]),
                train_end=str(data.index[train_idx[-1]]),
                test_start=str(data.index[test_idx[0]]),
                test_end=str(data.index[test_idx[-1]]),
                mse=mse,
                r2=r2,
                feature_importance=importance
            )
            results.append(result)
            
            logger.info(f"CV fold {fold}: MSE={mse:.6f}, R2={r2:.3f}")
        
        return results
    
    def get_degradation_alert(self) -> dict[str, Any] | None:
        """Check for model degradation."""
        if len(self._cv_history) < 10:
            return None
        
        recent = self._cv_history[-10:]
        r2_values = [r.r2 for r in recent]
        
        # Trend detection
        if len(r2_values) >= 5:
            slope = np.polyfit(range(len(r2_values)), r2_values, 1)[0]
            if slope < -0.01:  # Declining
                return {
                    "alert": "DEGRADATION_TREND",
                    "slope": slope,
                    "current_r2": np.mean(r2_values[-3:]),
                    "recommended_action": "RETRAIN" if slope < -0.05 else "MONITOR"
                }
        
        return None
