import numpy as np
from scipy import stats
from scipy.spatial.distance import jensenshannon


class DriftDetector:
    """KS test + PSI for model input drift."""
    
    def __init__(self, reference_data: np.ndarray, psi_threshold: float = 0.2) -> None:
        self.reference = reference_data
        self.psi_threshold = psi_threshold
        self._reference_hist = self._compute_hist(reference_data)
    
    def _compute_hist(self, data: np.ndarray, bins: int = 10) -> np.ndarray:
        hist, _ = np.histogram(data, bins=bins, range=(np.min(self.reference), np.max(self.reference)))
        return hist / (np.sum(hist) + 1e-8)
    
    def ks_test(self, current: np.ndarray) -> tuple[bool, float]:
        """Kolmogorov-Smirnov test."""
        statistic, p_value = stats.ks_2samp(self.reference, current)
        return p_value < 0.05, p_value
    
    def psi(self, current: np.ndarray) -> tuple[bool, float]:
        """Population Stability Index."""
        current_hist = self._compute_hist(current)
        psi = np.sum((self._reference_hist - current_hist) * 
                     np.log(self._reference_hist / (current_hist + 1e-8) + 1e-8))
        return psi > self.psi_threshold, psi
    
    def detect(self, current: np.ndarray) -> dict[str, any]:
        ks_drifted, ks_p = self.ks_test(current)
        psi_drifted, psi_val = self.psi(current)
        
        return {
            "drifted": ks_drifted or psi_drifted,
            "ks_p_value": float(ks_p),
            "psi_value": float(psi_val),
            "ks_drifted": ks_drifted,
            "psi_drifted": psi_drifted
        }
