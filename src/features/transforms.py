"""Feature transformations."""
from __future__ import annotations

import numpy as np
from sklearn.preprocessing import RobustScaler


class CyclicalEncoder:
    """Encode cyclical time features."""
    
    @staticmethod
    def encode_hour(hour: int) -> tuple[float, float]:
        """Encode hour as sin/cos."""
        angle = 2 * np.pi * hour / 24
        return np.sin(angle), np.cos(angle)
    
    @staticmethod
    def encode_dayofweek(day: int) -> tuple[float, float]:
        """Encode day of week as sin/cos."""
        angle = 2 * np.pi * day / 7
        return np.sin(angle), np.cos(angle)
    
    @staticmethod
    def encode_month(month: int) -> tuple[float, float]:
        """Encode month as sin/cos."""
        angle = 2 * np.pi * month / 12
        return np.sin(angle), np.cos(angle)


class RobustFeatureScaler:
    """Robust scaler wrapper with persistence."""
    
    def __init__(self) -> None:
        self.scaler = RobustScaler()
        self._fitted = False
    
    def fit_transform(self, X: np.ndarray) -> np.ndarray:
        """Fit and transform."""
        result = self.scaler.fit_transform(X)
        self._fitted = True
        return result
    
    def transform(self, X: np.ndarray) -> np.ndarray:
        """Transform."""
        if not self._fitted:
            raise RuntimeError("Scaler not fitted")
        return self.scaler.transform(X)
    
    def get_params(self) -> dict:
        """Get scaler parameters for persistence."""
        return {
            "center": self.scaler.center_.tolist() if hasattr(self.scaler, 'center_') else [],
            "scale": self.scaler.scale_.tolist() if hasattr(self.scaler, 'scale_') else [],
        }
