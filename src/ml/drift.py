"""
Model drift detection using KS test and PSI.
"""

from typing import Literal

import numpy as np
from scipy import stats

from src.core.logging_config import get_logger

logger = get_logger(__name__)


class DriftDetector:
    """
    Statistical drift detection for production ML models.
    """
    
    def __init__(
        self,
        reference_data: np.ndarray | None = None,
        psi_bins: int = 10,
        ks_threshold: float = 0.05,
        psi_threshold: float = 0.2
    ):
        self.reference_data = reference_data
        self.psi_bins = psi_bins
        self.ks_threshold = ks_threshold
        self.psi_threshold = psi_threshold
        
        self._reference_hist: np.ndarray | None = None
        self._bin_edges: np.ndarray | None = None
        
        if reference_data is not None:
            self._compute_reference_distribution()
    
    def _compute_reference_distribution(self) -> None:
        """Compute reference histogram."""
        self._bin_edges = np.histogram_bin_edges(
            self.reference_data,
            bins=self.psi_bins
        )
        self._reference_hist, _ = np.histogram(
            self.reference_data,
            bins=self._bin_edges,
            density=True
        )
        # Add smoothing to avoid division by zero
        self._reference_hist = self._reference_hist + 1e-10
        self._reference_hist = self._reference_hist / self._reference_hist.sum()
    
    def detect_drift(
        self,
        current_data: np.ndarray,
        method: Literal["ks", "psi", "both"] = "both"
    ) -> dict[str, Any]:
        """
        Detect drift between reference and current distributions.
        """
        results = {
            "drift_detected": False,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "metrics": {}
        }
        
        if method in ("ks", "both"):
            ks_stat, p_value = self._kolmogorov_smirnov(current_data)
            results["metrics"]["ks_statistic"] = ks_stat
            results["metrics"]["ks_p_value"] = p_value
            results["metrics"]["ks_drift"] = p_value < self.ks_threshold
            
            if p_value < self.ks_threshold:
                results["drift_detected"] = True
                logger.warning(f"KS drift detected: p={p_value:.4f}")
        
        if method in ("psi", "both"):
            psi = self._population_stability_index(current_data)
            results["metrics"]["psi"] = psi
            results["metrics"]["psi_drift"] = psi > self.psi_threshold
            
            if psi > self.psi_threshold:
                results["drift_detected"] = True
                logger.warning(f"PSI drift detected: {psi:.4f}")
        
        return results
    
    def _kolmogorov_smirnov(self, current_data: np.ndarray) -> tuple[float, float]:
        """Perform KS test."""
        if self.reference_data is None:
            raise ValueError("Reference data not set")
        
        statistic, p_value = stats.ks_2samp(self.reference_data, current_data)
        return statistic, p_value
    
    def _population_stability_index(self, current_data: np.ndarray) -> float:
        """Calculate PSI."""
        if self._reference_hist is None or self._bin_edges is None:
            raise ValueError("Reference distribution not computed")
        
        current_hist, _ = np.histogram(
            current_data,
            bins=self._bin_edges,
            density=True
        )
        current_hist = current_hist + 1e-10
        current_hist = current_hist / current_hist.sum()
        
        # PSI calculation
        psi = np.sum(
            (current_hist - self._reference_hist) * 
            np.log(current_hist / self._reference_hist)
        )
        
        return psi
    
    def update_reference(self, new_reference: np.ndarray) -> None:
        """Update reference distribution."""
        self.reference_data = new_reference
        self._compute_reference_distribution()
        logger.info("Reference distribution updated")
