"""Feature engineering: vol clustering, order flow, Hawkes, cycles."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd
import structlog
from scipy import stats

from src.core.types import Tick, OHLCV
from src.features.transforms import CyclicalEncoder, RobustFeatureScaler

logger = structlog.get_logger()


@dataclass
class FeatureVector:
    """Computed features."""
    timestamp: pd.Timestamp
    symbol: str
    
    # Price features
    returns: float
    log_returns: float
    volatility: float
    
    # Technical indicators
    rsi: float
    atr: float
    macd: float
    macd_signal: float
    obv: float
    vwap_dev

    # Order flow
    bid_ask_ratio: float
    volume_imbalance: float
    
    # Hawkes process intensity
    hawkes_intensity: float
    
    # Cyclical
    hour_sin: float
    hour_cos: float
    day_sin: float
    day_cos: float
    
    # Microstructure
    spread: float
    mid_price: float
    
    def to_dict(self) -> dict[str, float]:
        """Convert to flat dictionary for ML."""
        return {
            "returns": self.returns,
            "log_returns": self.log_returns,
            "volatility": self.volatility,
            "rsi": self.rsi,
            "atr": self.atr,
            "macd": self.macd,
            "macd_signal": self.macd_signal,
            "obv": self.obv,
            "vwap_dev": self.vwap_dev,
            "bid_ask_ratio": self.bid_ask_ratio,
            "volume_imbalance": self.volume_imbalance,
            "hawkes_intensity": self.hawkes_intensity,
            "hour_sin": self.hour_sin,
            "hour_cos": self.hour_cos,
            "day_sin": self.day_sin,
            "day_cos": self.day_cos,
            "spread": self.spread,
            "mid_price": self.mid_price,
        }


class FeatureEngineer:
    """Real-time feature engineering pipeline."""
    
    def __init__(self, window_sizes: list[int] | None = None) -> None:
        self.window_sizes = window_sizes or [14, 20, 50, 200]
        self.cyclical = CyclicalEncoder()
        self.scaler = RobustFeatureScaler()
        
        # State
        self._ticks_buffer: list[Tick] = []
        self._ohlcv_buffer: list[OHLCV] = []
        self._max_buffer = 1000
        
        # Hawkes process state
        self._hawkes_decay = 0.1
        self._hawkes_intensity = 0.0
        self._last_event_time: pd.Timestamp | None = None
        
        # Technical indicator state
        self._rsi_period = 14
        self._atr_period = 14
        self._macd_fast = 12
        self._macd_slow = 26
        self._macd_signal = 9
        self._obv = 0.0
        self._vwap_num = 0.0
        self._vwap_den = 0.0
    
    async def compute_from_tick(self, tick: Tick) -> FeatureVector:
        """Compute features from single tick."""
        self._ticks_buffer.append(tick)
        if len(self._ticks_buffer) > self._max_buffer:
            self._ticks_buffer.pop(0)
        
        # Build OHLCV from ticks if needed
        await self._update_ohlcv(tick)
        
        # Compute features
        features = await self._compute_all(tick)
        return features
    
    async def _update_ohlcv(self, tick: Tick) -> None:
        """Aggregate ticks to OHLCV."""
        current_minute = pd.Timestamp(tick.timestamp).floor("1min")
        
        if not self._ohlcv_buffer or self._ohlcv_buffer[-1].timestamp != current_minute:
            # New candle
            self._ohlcv_buffer.append(OHLCV(
                symbol=tick.symbol,
                timestamp=current_minute,
                open=tick.mid,
                high=tick.mid,
                low=tick.mid,
                close=tick.mid,
                volume=tick.volume,
                timeframe="1m"
            ))
        else:
            # Update current candle
            candle = self._ohlcv_buffer[-1]
            candle.high = max(candle.high, tick.mid)
            candle.low = min(candle.low, tick.mid)
            candle.close = tick.mid
            candle.volume += tick.volume
        
        if len(self._ohlcv_buffer) > self._max_buffer:
            self._ohlcv_buffer.pop(0)
    
    async def _compute_all(self, tick: Tick) -> FeatureVector:
        """Compute all feature components."""
        prices = pd.Series([t.mid for t in self._ticks_buffer])
        volumes = pd.Series([t.volume for t in self._ticks_buffer])
        
        # Price features
        returns, log_returns, volatility = self._compute_returns(prices)
        
        # Technical indicators
        rsi = self._compute_rsi(prices)
        atr = self._compute_atr()
        macd, macd_signal = self._compute_macd(prices)
        obv = self._compute_obv(prices, volumes)
        vwap_dev = self._compute_vwap_dev(tick.mid)
        
        # Order flow
        bid_ask_ratio = float(tick.bid / tick.ask) if tick.ask > 0 else 1.0
        volume_imbalance = self._compute_volume_imbalance(tick)
        
        # Hawkes process
        hawkes = self._update_hawkes(tick)
        
        # Cyclical
        ts = pd.Timestamp(tick.timestamp)
        hour_sin, hour_cos = self.cyclical.encode_hour(ts.hour)
        day_sin, day_cos = self.cyclical.encode_dayofweek(ts.dayofweek)
        
        return FeatureVector(
            timestamp=ts,
            symbol=tick.symbol,
            returns=returns,
            log_returns=log_returns,
            volatility=volatility,
            rsi=rsi,
            atr=atr,
            macd=macd,
            macd_signal=macd_signal,
            obv=obv,
            vwap_dev=vwap_dev,
            bid_ask_ratio=bid_ask_ratio,
            volume_imbalance=volume_imbalance,
            hawkes_intensity=hawkes,
            hour_sin=hour_sin,
            hour_cos=hour_cos,
            day_sin=day_sin,
            day_cos=day_cos,
            spread=float(tick.ask - tick.bid),
            mid_price=float(tick.mid)
        )
    
    def _compute_returns(self, prices: pd.Series) -> tuple[float, float, float]:
        """Compute return features."""
        if len(prices) < 2:
            return 0.0, 0.0, 0.0
        
        returns = prices.pct_change().dropna()
        log_returns = np.log(prices / prices.shift(1)).dropna()
        
        return (
            float(returns.iloc[-1]) if len(returns) > 0 else 0.0,
            float(log_returns.iloc[-1]) if len(log_returns) > 0 else 0.0,
            float(returns.std() * np.sqrt(252)) if len(returns) > 1 else 0.0  # Annualized vol
        )
    
    def _compute_rsi(self, prices: pd.Series, period: int = 14) -> float:
        """Compute RSI."""
        if len(prices) < period + 1:
            return 50.0
        
        deltas = prices.diff().dropna()
        gains = deltas.where(deltas > 0, 0.0)
        losses = (-deltas.where(deltas < 0, 0.0))
        
        avg_gains = gains.ewm(alpha=1/period, min_periods=period).mean()
        avg_losses = losses.ewm(alpha=1/period, min_periods=period).mean()
        
        rs = avg_gains.iloc[-1] / avg_losses.iloc[-1] if avg_losses.iloc[-1] != 0 else float('inf')
        rsi = 100 - (100 / (1 + rs))
        return float(rsi)
    
    def _compute_atr(self, period: int = 14) -> float:
        """Compute ATR from OHLCV."""
        if len(self._ohlcv_buffer) < period:
            return 0.0
        
        highs = pd.Series([c.high for c in self._ohlcv_buffer[-period:]])
        lows = pd.Series([c.low for c in self._ohlcv_buffer[-period:]])
        closes = pd.Series([c.close for c in self._ohlcv_buffer[-period:]])
        
        tr1 = highs - lows
        tr2 = abs(highs - closes.shift(1))
        tr3 = abs(lows - closes.shift(1))
        
        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        atr = tr.ewm(alpha=1/period, min_periods=period).mean()
        
        return float(atr.iloc[-1]) if len(atr) > 0 else 0.0
    
    def _compute_macd(self, prices: pd.Series) -> tuple[float, float]:
        """Compute MACD."""
        if len(prices) < 26:
            return 0.0, 0.0
        
        ema_fast = prices.ewm(span=self._macd_fast).mean()
        ema_slow = prices.ewm(span=self._macd_slow).mean()
        macd_line = ema_fast - ema_slow
        signal_line = macd_line.ewm(span=self._macd_signal).mean()
        
        return float(macd_line.iloc[-1]), float(signal_line.iloc[-1])
    
    def _compute_obv(self, prices: pd.Series, volumes: pd.Series) -> float:
        """Compute On-Balance Volume."""
        if len(prices) < 2:
            return self._obv
        
        price_change = prices.iloc[-1] - prices.iloc[-2]
        if price_change > 0:
            self._obv += float(volumes.iloc[-1])
        elif price_change < 0:
            self._obv -= float(volumes.iloc[-1])
        
        return self._obv
    
    def _compute_vwap_dev(self, current_price: float) -> float:
        """Compute VWAP deviation."""
        if len(self._ohlcv_buffer) < 20:
            return 0.0
        
        for candle in self._ohlcv_buffer[-20:]:
            typical = float((candle.high + candle.low + candle.close) / 3)
            self._vwap_num += typical * float(candle.volume)
            self._vwap_den += float(candle.volume)
        
        if self._vwap_den > 0:
            vwap = self._vwap_num / self._vwap_den
            return (current_price - vwap) / vwap
        
        return 0.0
    
    def _compute_volume_imbalance(self, tick: Tick) -> float:
        """Compute volume imbalance."""
        if len(self._ticks_buffer) < 10:
            return 0.0
        
        recent_ticks = self._ticks_buffer[-10:]
        buy_volume = sum(t.volume for t in recent_ticks if t.mid >= (t.bid + t.ask) / 2)
        total_volume = sum(t.volume for t in recent_ticks)
        
        return float(buy_volume / total_volume - 0.5) if total_volume > 0 else 0.0
    
    def _update_hawkes(self, tick: Tick) -> float:
        """Update Hawkes process intensity."""
        current_time = pd.Timestamp(tick.timestamp)
        
        if self._last_event_time is not None:
            dt = (current_time - self._last_event_time).total_seconds()
            decay = np.exp(-self._hawkes_decay * dt)
            self._hawkes_intensity = decay * self._hawkes_intensity + 1.0
        
        self._last_event_time = current_time
        return self._hawkes_intensity
