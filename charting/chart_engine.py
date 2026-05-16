# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""Chart engine — Chart and ChartEngine classes with full indicator computation."""

import json
import logging
from pathlib import Path
from typing import Any

try:
    from enum import StrEnum
except ImportError:
    from enum import Enum

    class StrEnum(str, Enum):  # Python 3.10 compat
        pass


logger = logging.getLogger(__name__)

# Lazy import — indicators module is pure-Python, no heavy deps
_indicator_library = None


def _get_indicator_library():
    global _indicator_library
    if _indicator_library is None:
        try:
            from charting.indicators import indicator_library

            _indicator_library = indicator_library
        except Exception as exc:
            logger.debug("IndicatorLibrary unavailable: %s", exc)
    return _indicator_library


class ChartType(StrEnum):
    """Chart type enum. Inherits from str so values compare equal to strings."""

    CANDLESTICK = "candlestick"
    LINE = "line"
    BAR = "bar"
    AREA = "area"
    HEIKIN_ASHI = "heikin_ashi"


class Chart:
    """Single chart with indicators and drawings."""

    def __init__(
        self,
        symbol: str,
        timeframe: str = "1H",
        chart_type: ChartType = ChartType.CANDLESTICK,
    ):
        self.symbol = symbol
        self.timeframe = timeframe
        self.chart_type = chart_type
        self.indicators: list[dict[str, Any]] = []
        self.drawings: list[dict[str, Any]] = []
        self.candles: list[dict[str, Any]] = []

    def add_indicator(self, name: str, **params) -> None:
        """Register an indicator by name. Values are computed lazily in render()."""
        self.indicators.append({"name": name, "params": params})

    def compute_indicator(self, name: str, **params) -> list[float]:
        """Compute an indicator over the current candle series and return values.

        Uses the full IndicatorLibrary so all 20 indicator types are available.
        Returns an empty list when the library is unavailable or candles are empty.
        """
        lib = _get_indicator_library()
        if lib is None or not self.candles:
            return []
        close = [c["close"] for c in self.candles]
        try:
            return lib.calculate(name, close, **params)
        except Exception as exc:
            logger.debug("compute_indicator(%s) failed: %s", name, exc)
            return []

    def compute_indicator_hlcv(
        self,
        name: str,
        **params,
    ) -> dict[str, list[float]]:
        """Compute a multi-series indicator (MACD, BB, ADX, Stochastic, Ichimoku).

        Returns a dict of named series. Falls back to {"values": []} on error.
        """
        if not self.candles:
            return {"values": []}
        close = [c["close"] for c in self.candles]
        high = [c["high"] for c in self.candles]
        low = [c["low"] for c in self.candles]
        volume = [c.get("volume", 0.0) for c in self.candles]
        try:
            from charting.indicators import (
                ADX,
                ATR,
                BollingerBands,
                CMF,
                DonchianChannels,
                Ichimoku,
                KeltnerChannels,
                MACD,
                MFI,
                OBV,
                Stochastic,
                VWAP,
            )

            name_upper = name.upper()
            if name_upper == "MACD":
                macd, sig, hist = MACD(**params).calculate_full(close)
                return {"macd": macd, "signal": sig, "histogram": hist}
            if name_upper in ("BB", "BBANDS", "BOLLINGER"):
                u, m, lo = BollingerBands(**params).calculate_full(close)
                return {"upper": u, "middle": m, "lower": lo}
            if name_upper == "ATR":
                return {"values": ATR(**params).calculate_hlc(high, low, close)}
            if name_upper in ("STOCH", "STOCHASTIC"):
                stoch = Stochastic(**params)
                return {"k": stoch.calculate(close), "d": stoch.calculate_d(close)}
            if name_upper == "ADX":
                adx, pdi, mdi = ADX(**params).calculate_full(high, low, close)
                return {"adx": adx, "plus_di": pdi, "minus_di": mdi}
            if name_upper == "VWAP":
                return {"values": VWAP().calculate_hlcv(high, low, close, volume)}
            if name_upper == "OBV":
                return {"values": OBV().calculate_cv(close, volume)}
            if name_upper == "CMF":
                return {"values": CMF(**params).calculate_hlcv(high, low, close, volume)}
            if name_upper == "MFI":
                return {"values": MFI(**params).calculate_hlcv(high, low, close, volume)}
            if name_upper in ("KC", "KELTNER"):
                u, m, lo = KeltnerChannels(**params).calculate_full(high, low, close)
                return {"upper": u, "middle": m, "lower": lo}
            if name_upper in ("DC", "DONCHIAN"):
                u, m, lo = DonchianChannels(**params).calculate_full(high, low)
                return {"upper": u, "middle": m, "lower": lo}
            if name_upper == "ICHIMOKU":
                ich = Ichimoku(**params).calculate_full(high, low, close)
                return ich
            # Fallback: single-series
            lib = _get_indicator_library()
            if lib:
                return {"values": lib.calculate(name, close, **params)}
        except Exception as exc:
            logger.debug("compute_indicator_hlcv(%s) failed: %s", name, exc)
        return {"values": []}

    def add_drawing(self, drawing_type: str, **params) -> None:
        self.drawings.append({"type": drawing_type, "params": params})

    def add_candle(
        self,
        open_price: float,
        high: float,
        low: float,
        close: float,
        volume: float = 0,
        timestamp=None,
    ) -> None:
        self.candles.append(
            {
                "open": open_price,
                "high": high,
                "low": low,
                "close": close,
                "volume": volume,
                "timestamp": timestamp,
            }
        )

    def render(self, output_format: str = "plotly") -> dict[str, Any]:
        """Render the chart to a serialisable dict.

        Indicator values are computed from the current candle series at render
        time so the caller always gets up-to-date values without manual
        recomputation.
        """
        # Compute indicator values for all registered indicators
        computed_indicators = []
        for ind in self.indicators:
            name = ind["name"]
            params = ind.get("params", {})
            # Try multi-series first (MACD, BB, ADX, etc.)
            multi = self.compute_indicator_hlcv(name, **params)
            if len(multi) > 1 or (len(multi) == 1 and "values" not in multi):
                computed_indicators.append(
                    {
                        "name": name,
                        "params": params,
                        "series": multi,
                    }
                )
            else:
                values = multi.get("values") or self.compute_indicator(name, **params)
                computed_indicators.append(
                    {
                        "name": name,
                        "params": params,
                        "values": values,
                    }
                )

        return {
            "symbol": self.symbol,
            "timeframe": self.timeframe,
            "type": self.chart_type,
            "format": output_format,
            "indicators": computed_indicators,
            "drawings": self.drawings,
            "candles": self.candles,
            "bar_count": len(self.candles),
        }

    def export_to_json(self, filepath: str) -> None:
        with Path(filepath).open("w", encoding="utf-8") as f:
            json.dump(self.render(), f, indent=2, default=str)

    def clear(self) -> None:
        self.candles.clear()
        self.indicators.clear()
        self.drawings.clear()


class ChartEngine:
    """Manages multiple Chart instances with full indicator computation."""

    # Default indicator set applied to every new chart
    DEFAULT_INDICATORS: list[dict[str, Any]] = [
        {"name": "EMA", "params": {"period": 21}},
        {"name": "EMA", "params": {"period": 50}},
        {"name": "SMA", "params": {"period": 200}},
        {"name": "BB", "params": {"period": 20, "std_dev": 2.0}},
        {"name": "RSI", "params": {"period": 14}},
        {"name": "MACD", "params": {"fast": 12, "slow": 26, "signal": 9}},
        {"name": "ATR", "params": {"period": 14}},
        {"name": "VWAP", "params": {}},
        {"name": "OBV", "params": {}},
        {"name": "ADX", "params": {"period": 14}},
    ]

    def __init__(self) -> None:
        self.charts: dict[str, Chart] = {}

    def create_chart(
        self,
        symbol: str,
        timeframe: str = "1H",
        chart_type: ChartType = ChartType.CANDLESTICK,
        add_default_indicators: bool = True,
    ) -> Chart:
        """Create a new Chart and optionally register the default indicator set."""
        chart = Chart(symbol, timeframe, chart_type)
        if add_default_indicators:
            for ind in self.DEFAULT_INDICATORS:
                chart.add_indicator(ind["name"], **ind["params"])
        key = f"{symbol}_{timeframe}"
        self.charts[key] = chart
        return chart

    def get_chart(self, key: str) -> Chart | None:
        return self.charts.get(key)

    def remove_chart(self, key: str) -> bool:
        if key in self.charts:
            del self.charts[key]
            return True
        return False

    def list_available_indicators(self) -> list[str]:
        """Return all indicator names registered in the IndicatorLibrary."""
        lib = _get_indicator_library()
        if lib is None:
            return []
        return lib.list_indicators()

    def compute_all_indicators(
        self,
        symbol: str,
        timeframe: str = "1H",
    ) -> dict[str, Any]:
        """Compute all default indicators for the named chart and return results.

        Returns {} when the chart doesn't exist or has no candles.
        """
        key = f"{symbol}_{timeframe}"
        chart = self.charts.get(key)
        if chart is None or not chart.candles:
            return {}
        return chart.render()["indicators"]
