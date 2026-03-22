"""Drift detection using KS test and PSI."""
from __future__ import annotations

import numpy as np
from scipy import stats
from typing import Deque
from collections import deque


class DriftDetector:
    """Statistical drift detection."""
    
    def __init__(self, window_size: int = 1000, threshold: float = 0.05) -> None:
        self.reference_window: Deque[np.ndarray] = deque(maxlen=window_size)
        self.current_window: Deque[np.ndarray] = deque(maxlen=window_size)
        self.threshold = threshold
        self._has_reference = False
    
    def set_reference(self, data: np.ndarray) -> None:
        """Set reference distribution."""
        self.reference_window.clear()
        for sample in data:
            self.reference_window.append(sample)
        self._has_reference = True
    
    async def update(self, features: np.ndarray, prediction: float) -> float:
        """Update detector and return drift score."""
        self.current_window.append(features)
        
        if not self._has_reference:
            if len(self.current_window) >= self.reference_window.maxlen:
                self.reference_window = self.current_window.copy()
                self._has_reference = True
            return 0.0
        
        # Calculate PSI (Population Stability Index)
        if len(self.current_window) < 100:
            return 0.0
        
        psi_score = self._calculate_psi()
        
        # Reset if drift detected
        if psi_score > 0.25:  # Significant drift
            self.reference_window = self.current_window.copy()
        
        return psi_score
    
    def _calculate_psi(self) -> float:
        """Calculate PSI between reference and current."""
        ref_data = np.array(list(self.reference_window))
        cur_data = np.array(list(self.current_window))
        
        # Bin the data
        bins = 10
        ref_hist, edges = np.histogram(ref_data[:, 0], bins=bins, density=True)
        cur_hist, _ = np.histogram(cur_data[:, 0], bins=edges, density=True)
        
        # Add epsilon to avoid division by zero
        ref_hist = ref_hist + 1e-10
        cur_hist = cur_hist + 1e-10
        
        # Calculate PSI
        psi = np.sum((ref_hist - cur_hist) * np.log(ref_hist / cur_hist))
        
        return float(psi)
    
    def _calculate_ks(self) -> float:
        """Calculate Kolmogorov-Smirnov statistic."""
        ref_data = np.array(list(self.reference_window))[:, 0]
        cur_data = np.array(list(self.current_window))[:, 0]
        
        statistic, _ = stats.ks_2samp(ref_data, cur_data)
        return float(statistic)
