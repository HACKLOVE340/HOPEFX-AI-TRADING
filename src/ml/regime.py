"""Market regime detection using HMM and volatility clustering."""
from __future__ import annotations

import pickle
from dataclasses import dataclass
from enum import Enum, auto
from pathlib import Path
from typing import Any

import numpy as np
import structlog
from hmmlearn.hmm import GaussianHMM
from sklearn.mixture import GaussianMixture

from src.features.engineer import FeatureVector

logger = structlog.get_logger()


class MarketRegime(Enum):
    UNKNOWN = auto()
    TRENDING_UP = auto()
    TRENDING_DOWN = auto()
    MEAN_REVERTING = auto()
    RANGE_BOUND = auto()
    HIGH_VOL = auto()
    LOW_VOL = auto()


@dataclass
class RegimeResult:
    regime: MarketRegime
    confidence: float
    duration_bars: int
    transition_probability: float


class RegimeDetector:
    """Hidden Markov Model for regime detection."""
    
    def __init__(
        self,
        n_regimes: int = 5,
        lookback: int = 100,
        model_path: Path | None = None
    ) -> None:
        self.n_regimes = n_regimes
        self.lookback = lookback
        self.model_path = model_path or Path("./models/regime_hmm.pkl")
        
        # HMM for sequence modeling
        self.hmm = GaussianHMM(
            n_components=n_regimes,
            covariance_type="full",
            n_iter=100,
            random_state=42
        )
        
        # GMM for volatility clustering
        self.vol_gmm = GaussianMixture(n_components=3, random_state=42)
        
        # State mapping
        self._regime_map: dict[int, MarketRegime] = {}
        self._current_state: int = 0
        self._state_history: list[int] = []
        self._max_history = 1000
        
        self._is_fitted = False
    
    async def load(self) -> None:
        """Load or train model."""
        if self.model_path.exists():
            with open(self.model_path, "rb") as f:
                saved = pickle.load(f)
                self.hmm = saved["hmm"]
                self.vol_gmm = saved["vol_gmm"]
                self._regime_map = saved["regime_map"]
                self._is_fitted = True
            logger.info("Regime model loaded")
        else:
            logger.warning("No regime model found, will train on first data")
    
    async def detect(self, features: FeatureVector) -> tuple[MarketRegime, float]:
        """Detect current market regime."""
        # Build feature vector for HMM
        obs = np.array([
            features.returns,
            features.volatility,
            features.rsi / 100,  # Normalize
            features.macd,
            features.bid_ask_ratio,
            features.hawkes_intensity
        ]).reshape(1, -1)
        
        if not self._is_fitted:
            # First call - initialize with single observation
            return MarketRegime.UNKNOWN, 0.0
        
        # Decode hidden state
        logprob, state = self.hmm.decode(obs, algorithm="viterbi")
        
        # Update history
        self._state_history.append(state[0])
        if len(self._state_history) > self._max_history:
            self._state_history.pop(0)
        
        # Calculate confidence (posterior probability)
        posteriors = self.hmm.predict_proba(obs)[0]
        confidence = posteriors[state[0]]
        
        # Map to regime
        regime = self._regime_map.get(state[0], MarketRegime.UNKNOWN)
        
        # Volatility overlay
        vol_regime = self._classify_volatility(features.volatility)
        if vol_regime == MarketRegime.HIGH_VOL and confidence < 0.9:
            regime = MarketRegime.HIGH_VOL
        
        # Calculate duration in current regime
        duration = self._calculate_duration(state[0])
        
        # Transition probability
        transition_prob = self._estimate_transition(state[0])
        
        return regime, float(confidence)
    
    def _classify_volatility(self, vol: float) -> MarketRegime:
        """Classify volatility regime."""
        if vol > 0.5:
            return MarketRegime.HIGH_VOL
        elif vol < 0.1:
            return MarketRegime.LOW_VOL
        return MarketRegime.UNKNOWN
    
    def _calculate_duration(self, current_state: int) -> int:
        """Calculate bars in current regime."""
        count = 0
        for state in reversed(self._state_history):
            if state == current_state:
                count += 1
            else:
                break
        return count
    
    def _estimate_transition(self, state: int) -> float:
        """Estimate probability of regime change."""
        if len(self._state_history) < 2:
            return 0.0
        
        recent = self._state_history[-20:]
        changes = sum(1 for i in range(1, len(recent)) if recent[i] != recent[i-1])
        return changes / len(recent)
    
    async def fit(self, historical_data: np.ndarray) -> None:
        """Fit HMM on historical data."""
        # Data shape: (n_samples, n_features)
        self.hmm.fit(historical_data)
        
        # Determine regime mapping from statistics
        means = self.hmm.means_
        covars = self.hmm.covars_
        
        for i, (mean, cov) in enumerate(zip(means, covars)):
            ret_mean = mean[0]
            vol = np.sqrt(cov[0, 0])
            
            # Classify based on return mean and volatility
            if ret_mean > 0.001 and vol < 0.3:
                self._regime_map[i] = MarketRegime.TRENDING_UP
            elif ret_mean < -0.001 and vol < 0.3:
                self._regime_map[i] = MarketRegime.TRENDING_DOWN
            elif vol > 0.4:
                self._regime_map[i] = MarketRegime.HIGH_VOL
            elif abs(ret_mean) < 0.0005:
                self._regime_map[i] = MarketRegime.RANGE_BOUND
            else:
                self._regime_map[i] = MarketRegime.MEAN_REVERTING
        
        self._is_fitted = True
        
        # Save
        self.model_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.model_path, "wb") as f:
            pickle.dump({
                "hmm": self.hmm,
                "vol_gmm": self.vol_gmm,
                "regime_map": self._regime_map
            }, f)
        
        logger.info(f"Regime model trained: {self._regime_map}")
    
    def get_regime_statistics(self) -> dict[str, Any]:
        """Get statistics for each regime."""
        if not self._is_fitted:
            return {}
        
        stats = {}
        for state, regime in self._regime_map.items():
            duration = self._calculate_duration(state)
            stats[regime.name] = {
                "current_duration": duration,
                "mean_return": float(self.hmm.means_[state][0]),
                "volatility": float(np.sqrt(self.hmm.covars_[state][0, 0])),
                "transition_probs": self.hmm.transmat_[state].tolist()
            }
        
        return stats
