"""
Technical Indicators Library
"""

from typing import List, Dict, Any
import numpy as np


class Indicator:
    """Base indicator class"""
    def __init__(self, name: str, period: int):
        self.name = name
        self.period = period

    def calculate(self, data: List[float]) -> List[float]:
        """Calculate indicator values"""
        raise NotImplementedError


class SMA(Indicator):
    """Simple Moving Average"""
    def calculate(self, data: List[float]) -> List[float]:
        if len(data) < self.period:
            return []

        result = []
        for i in range(len(data) - self.period + 1):
            avg = sum(data[i:i+self.period]) / self.period
            result.append(avg)
        return result


class EMA(Indicator):
    """Exponential Moving Average"""
    def calculate(self, data: List[float]) -> List[float]:
        if len(data) < self.period:
            return []

        multiplier = 2 / (self.period + 1)
        ema_values = [sum(data[:self.period]) / self.period]

        for price in data[self.period:]:
            ema = (price - ema_values[-1]) * multiplier + ema_values[-1]
            ema_values.append(ema)

        return ema_values


class RSI(Indicator):
    """Relative Strength Index"""
    def calculate(self, data: List[float]) -> List[float]:
        if len(data) < self.period + 1:
            return []

        deltas = [data[i] - data[i-1] for i in range(1, len(data))]
        gains = [d if d > 0 else 0 for d in deltas]
        losses = [-d if d < 0 else 0 for d in deltas]

        avg_gain = sum(gains[:self.period]) / self.period
        avg_loss = sum(losses[:self.period]) / self.period

        rsi_values = []
        for i in range(self.period, len(deltas)):
            if avg_loss == 0:
                rsi = 100
            else:
                rs = avg_gain / avg_loss
                rsi = 100 - (100 / (1 + rs))
            rsi_values.append(rsi)

            avg_gain = (avg_gain * (self.period - 1) + gains[i]) / self.period
            avg_loss = (avg_loss * (self.period - 1) + losses[i]) / self.period

        return rsi_values


class IndicatorLibrary:
    """Library of technical indicators"""

    def __init__(self):
        self.indicators = {
            'SMA': SMA,
            'EMA': EMA,
            'RSI': RSI,
        }

    def get_indicator(self, name: str, period: int = 14) -> Indicator:
        """Get indicator instance"""
        if name in self.indicators:
            return self.indicators[name](name, period)
        raise ValueError(f"Unknown indicator: {name}")

    def list_indicators(self) -> List[str]:
        """List available indicators"""
        return list(self.indicators.keys())
