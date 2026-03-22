"""Technical indicators for charting."""

import logging
from typing import Any, Dict, List, Optional, Type

logger = logging.getLogger(__name__)


class Indicator:
    """Base indicator class."""

    def __init__(self, name: str, period: int = 14):
        self.name = name
        self.period = period

    def calculate(self, data: List[float]) -> List[float]:
        raise NotImplementedError(f"{self.__class__.__name__}.calculate() not implemented")


class SMA(Indicator):
    """Simple Moving Average."""

    def __init__(self, name: str = "SMA", period: int = 14):
        super().__init__(name, period)

    def calculate(self, data: List[float]) -> List[float]:
        if len(data) < self.period:
            return []
        result = []
        for i in range(self.period - 1, len(data)):
            window = data[i - self.period + 1: i + 1]
            result.append(sum(window) / self.period)
        return result


class EMA(Indicator):
    """Exponential Moving Average."""

    def __init__(self, name: str = "EMA", period: int = 14):
        super().__init__(name, period)

    def calculate(self, data: List[float]) -> List[float]:
        if len(data) < self.period:
            return []
        k = 2.0 / (self.period + 1)
        # Seed with SMA of first `period` values
        sma = sum(data[:self.period]) / self.period
        result = [sma]
        for price in data[self.period:]:
            result.append(price * k + result[-1] * (1 - k))
        return result


class RSI(Indicator):
    """Relative Strength Index."""

    def __init__(self, name: str = "RSI", period: int = 14):
        super().__init__(name, period)

    def calculate(self, data: List[float]) -> List[float]:
        if len(data) <= self.period:
            return []
        gains, losses = [], []
        for i in range(1, len(data)):
            diff = data[i] - data[i - 1]
            gains.append(max(diff, 0))
            losses.append(max(-diff, 0))

        avg_gain = sum(gains[:self.period]) / self.period
        avg_loss = sum(losses[:self.period]) / self.period

        result = []
        for i in range(self.period, len(gains)):
            if avg_loss == 0:
                result.append(100.0)
            else:
                rs = avg_gain / avg_loss
                result.append(100 - 100 / (1 + rs))
            avg_gain = (avg_gain * (self.period - 1) + gains[i]) / self.period
            avg_loss = (avg_loss * (self.period - 1) + losses[i]) / self.period

        return result


class IndicatorLibrary:
    """Registry of available indicators."""

    def __init__(self):
        self.indicators: Dict[str, Type[Indicator]] = {
            "SMA": SMA,
            "EMA": EMA,
            "RSI": RSI,
        }

    def get_indicator(self, name: str, **params) -> Indicator:
        cls = self.indicators.get(name.upper())
        if cls is None:
            raise ValueError(f"Unknown indicator: {name}")
        period = params.get("period", 14)
        return cls(name=name, period=period)

    def list_indicators(self) -> List[str]:
        return list(self.indicators.keys())

    def register(self, name: str, cls: Type[Indicator]) -> None:
        self.indicators[name.upper()] = cls


# Alias used by some imports
TechnicalIndicators = IndicatorLibrary
