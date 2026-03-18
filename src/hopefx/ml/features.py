import numpy as np
import pandas as pd
from numba import njit
from scipy import stats
from sklearn.preprocessing import RobustScaler


class FeatureEngineer:
    """Real-time feature computation: vol clustering, order-flow, Hawkes, cycles."""
    
    def __init__(self, window: int = 100) -> None:
        self.window = window
        self._scaler = RobustScaler()
        self._fitted = False
        
        # Hawkes process parameters
        self.hawkes_mu = 0.1
        self.hawkes_alpha = 0.5
        self.hawkes_beta = 0.7
        self._hawkes_intensity = 0.0
        
        # Buffers
        self._prices: list[float] = []
        self._volumes: list[float] = []
        self._returns: list[float] = []
    
    def update(self, price: float, volume: float) -> dict[str, float]:
        """Online update with O(1) amortized computation."""
        if len(self._prices) > 0:
            ret = np.log(price / self._prices[-1])
            self._returns.append(ret)
        
        self._prices.append(price)
        self._volumes.append(volume)
        
        # Maintain window
        if len(self._prices) > self.window:
            self._prices.pop(0)
            self._volumes.pop(0)
            if len(self._returns) > self.window - 1:
                self._returns.pop(0)
        
        return self._compute_features()
    
    def _compute_features(self) -> dict[str, float]:
        if len(self._prices) < 20:
            return {}
        
        prices = np.array(self._prices)
        returns = np.array(self._returns) if self._returns else np.array([0.0])
        volumes = np.array(self._volumes)
        
        # Volatility clustering (GARCH-like)
        vol = np.std(returns[-20:])
        vol_long = np.std(returns[-50:]) if len(returns) >= 50 else vol
        vol_cluster = vol / (vol_long + 1e-8)
        
        # Hawkes intensity update
        if len(self._returns) > 1:
            jump = abs(self._returns[-1]) > 2 * vol if vol > 0 else False
            self._hawkes_intensity = (
                self.hawkes_mu + 
                self.hawkes_alpha * jump + 
                np.exp(-self.hawkes_beta) * self._hawkes_intensity
            )
        
        # Technical indicators
        sma20 = np.mean(prices[-20:])
        sma50 = np.mean(prices[-50:]) if len(prices) >= 50 else sma20
        rsi = self._compute_rsi(prices, 14)
        atr = self._compute_atr(prices, 14)
        macd = self._compute_macd(prices)
        
        # Order flow (volume profile)
        vwap = np.sum(prices * volumes) / np.sum(volumes) if np.sum(volumes) > 0 else prices[-1]
        vwap_dev = (prices[-1] - vwap) / vwap if vwap != 0 else 0
        
        # Cyclical features (time of day, day of week)
        # Assuming we track timestamp externally or use last index
        hour = len(self._prices) % 24  # Placeholder - use actual timestamp in prod
        sin_hour = np.sin(2 * np.pi * hour / 24)
        cos_hour = np.cos(2 * np.pi * hour / 24)
        
        return {
            "returns_last": float(returns[-1]) if len(returns) > 0 else 0.0,
            "volatility_20": float(vol),
            "vol_cluster_ratio": float(vol_cluster),
            "hawkes_intensity": float(self._hawkes_intensity),
            "sma20": float(sma20),
            "sma50": float(sma50),
            "trend_ratio": float(sma20 / sma50) if sma50 != 0 else 1.0,
            "rsi_14": float(rsi),
            "atr_14": float(atr),
            "macd_line": float(macd["line"]),
            "macd_signal": float(macd["signal"]),
            "macd_hist": float(macd["hist"]),
            "vwap_deviation": float(vwap_dev),
            "volume_sma20": float(np.mean(volumes[-20:])),
            "sin_hour": float(sin_hour),
            "cos_hour": float(cos_hour),
            "price_momentum": float(prices[-1] / prices[-20] - 1) if len(prices) >= 20 else 0.0,
        }
    
    @staticmethod
    @njit(cache=True)
    def _compute_rsi(prices: np.ndarray, period: int) -> float:
        if len(prices) < period + 1:
            return 50.0
        deltas = np.diff(prices)
        gains = np.where(deltas > 0, deltas, 0)
        losses = np.where(deltas < 0, -deltas, 0)
        avg_gain = np.mean(gains[-period:])
        avg_loss = np.mean(losses[-period:])
        if avg_loss == 0:
            return 100.0
        rs = avg_gain / avg_loss
        return 100 - (100 / (1 + rs))
    
    @staticmethod
    def _compute_atr(prices: np.ndarray, period: int) -> float:
        if len(prices) < period + 1:
            return 0.0
        highs = prices[1:]
        lows = prices[:-1]
        tr = np.abs(highs - lows)
        return float(np.mean(tr[-period:]))
    
    @staticmethod
    def _compute_macd(prices: np.ndarray, fast: int = 12, slow: int = 26, signal: int = 9) -> dict:
        if len(prices) < slow:
            return {"line": 0.0, "signal": 0.0, "hist": 0.0}
        ema_fast = pd.Series(prices).ewm(span=fast, adjust=False).mean().iloc[-1]
        ema_slow = pd.Series(prices).ewm(span=slow, adjust=False).mean().iloc[-1]
        macd_line = ema_fast - ema_slow
        # Simplified signal line computation
        signal_line = macd_line * 0.9  # Approximation for online
        return {
            "line": float(macd_line),
            "signal": float(signal_line),
            "hist": float(macd_line - signal_line)
        }
    
    def fit_scaler(self, features_batch: np.ndarray) -> None:
        """Fit RobustScaler on initial batch."""
        self._scaler.fit(features_batch)
        self._fitted = True
    
    def transform(self, features: dict[str, float]) -> np.ndarray:
        vec = np.array(list(features.values())).reshape(1, -1)
        if self._fitted:
            return self._scaler.transform(vec)[0]
        return vec[0]
