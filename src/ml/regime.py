# src/ml/regime.py
from hmmlearn.hmm import GaussianHMM

class RegimeDetector:
    """Hidden Markov Model for market regimes."""
    
    def __init__(self, n_regimes: int = 3):
        self.model = GaussianHMM(n_components=n_regimes, covariance_type="full")
        self.regimes = {0: "TREND_UP", 1: "MEAN_REVERT", 2: "RANGE"}
    
    def fit(self, returns: np.ndarray) -> None:
        """Fit on historical returns."""
        features = np.column_stack([
            returns,
            np.abs(returns),
            np.roll(returns, 1)  # Autocorr
        ])
        self.model.fit(features)
    
    def predict(self, recent_returns: np.ndarray) -> str:
        """Predict current regime."""
        hidden_state = self.model.predict(recent_returns)[-1]
        return self.regimes.get(hidden_state, "UNKNOWN")
