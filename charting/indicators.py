"""
Technical Indicators Library

Advanced charting indicators including:
- Moving Averages (SMA, EMA, WMA)
- Oscillators (RSI, Stochastic, MACD)
- Volatility (Bollinger Bands, ATR, Keltner Channels)
- Trend (ADX, Ichimoku Cloud, Parabolic SAR)
- Volume (OBV, VWAP, Volume Profile)
- Fibonacci (Retracements, Extensions, Pivots)
"""

from typing import List, Dict, Any, Tuple, Optional
import numpy as np


class Indicator:
    """Base indicator class"""
    def __init__(self, name: str, period: int = 14):
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


class WMA(Indicator):
    """Weighted Moving Average"""
    def calculate(self, data: List[float]) -> List[float]:
        if len(data) < self.period:
            return []

        result = []
        weights = list(range(1, self.period + 1))
        weight_sum = sum(weights)

        for i in range(len(data) - self.period + 1):
            weighted_sum = sum(w * p for w, p in zip(weights, data[i:i+self.period]))
            result.append(weighted_sum / weight_sum)
        return result


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


class MACD(Indicator):
    """
    Moving Average Convergence Divergence

    Returns tuple of (macd_line, signal_line, histogram)
    """
    def __init__(self, name: str = 'MACD', fast_period: int = 12,
                 slow_period: int = 26, signal_period: int = 9):
        super().__init__(name, fast_period)
        self.fast_period = fast_period
        self.slow_period = slow_period
        self.signal_period = signal_period

    def calculate(self, data: List[float]) -> Dict[str, List[float]]:
        if len(data) < self.slow_period:
            return {'macd': [], 'signal': [], 'histogram': []}

        # Calculate EMAs
        fast_ema = EMA('fast', self.fast_period).calculate(data)
        slow_ema = EMA('slow', self.slow_period).calculate(data)

        # Align lengths
        min_len = min(len(fast_ema), len(slow_ema))
        fast_ema = fast_ema[-min_len:]
        slow_ema = slow_ema[-min_len:]

        # MACD line
        macd_line = [f - s for f, s in zip(fast_ema, slow_ema)]

        # Signal line (EMA of MACD)
        if len(macd_line) >= self.signal_period:
            signal_line = EMA('signal', self.signal_period).calculate(macd_line)
        else:
            signal_line = []

        # Histogram
        if signal_line:
            histogram = [m - s for m, s in zip(macd_line[-len(signal_line):], signal_line)]
        else:
            histogram = []

        return {
            'macd': macd_line,
            'signal': signal_line,
            'histogram': histogram
        }


class BollingerBands(Indicator):
    """
    Bollinger Bands

    Returns tuple of (upper_band, middle_band, lower_band)
    """
    def __init__(self, name: str = 'BB', period: int = 20, std_dev: float = 2.0):
        super().__init__(name, period)
        self.std_dev = std_dev

    def calculate(self, data: List[float]) -> Dict[str, List[float]]:
        if len(data) < self.period:
            return {'upper': [], 'middle': [], 'lower': []}

        middle = SMA('middle', self.period).calculate(data)
        upper = []
        lower = []

        for i in range(len(data) - self.period + 1):
            window = data[i:i + self.period]
            std = np.std(window)
            upper.append(middle[i] + self.std_dev * std)
            lower.append(middle[i] - self.std_dev * std)

        return {
            'upper': upper,
            'middle': middle,
            'lower': lower
        }


class Stochastic(Indicator):
    """
    Stochastic Oscillator

    Returns %K and %D lines
    """
    def __init__(self, name: str = 'Stoch', k_period: int = 14,
                 d_period: int = 3, smooth: int = 3):
        super().__init__(name, k_period)
        self.k_period = k_period
        self.d_period = d_period
        self.smooth = smooth

    def calculate_with_hlc(self, high: List[float], low: List[float],
                           close: List[float]) -> Dict[str, List[float]]:
        """Calculate with high, low, close data"""
        if len(close) < self.k_period:
            return {'k': [], 'd': []}

        k_values = []
        for i in range(self.k_period - 1, len(close)):
            highest_high = max(high[i - self.k_period + 1:i + 1])
            lowest_low = min(low[i - self.k_period + 1:i + 1])

            if highest_high == lowest_low:
                k = 50  # Prevent division by zero
            else:
                k = 100 * (close[i] - lowest_low) / (highest_high - lowest_low)
            k_values.append(k)

        # Smooth %K
        if self.smooth > 1 and len(k_values) >= self.smooth:
            smoothed_k = SMA('k', self.smooth).calculate(k_values)
        else:
            smoothed_k = k_values

        # Calculate %D (SMA of %K)
        if len(smoothed_k) >= self.d_period:
            d_values = SMA('d', self.d_period).calculate(smoothed_k)
        else:
            d_values = []

        return {'k': smoothed_k, 'd': d_values}

    def calculate(self, data: List[float]) -> Dict[str, List[float]]:
        """Calculate using close prices only (simplified)"""
        return self.calculate_with_hlc(data, data, data)


class ATR(Indicator):
    """
    Average True Range

    Measures market volatility
    """
    def calculate_with_hlc(self, high: List[float], low: List[float],
                           close: List[float]) -> List[float]:
        """Calculate ATR with high, low, close data"""
        if len(close) < 2:
            return []

        true_ranges = []
        for i in range(1, len(close)):
            tr = max(
                high[i] - low[i],
                abs(high[i] - close[i - 1]),
                abs(low[i] - close[i - 1])
            )
            true_ranges.append(tr)

        if len(true_ranges) < self.period:
            return []

        # Calculate ATR using EMA of true range
        atr_values = [sum(true_ranges[:self.period]) / self.period]
        multiplier = 2 / (self.period + 1)

        for tr in true_ranges[self.period:]:
            atr = (tr - atr_values[-1]) * multiplier + atr_values[-1]
            atr_values.append(atr)

        return atr_values

    def calculate(self, data: List[float]) -> List[float]:
        """Calculate using close prices only (simplified)"""
        return self.calculate_with_hlc(data, data, data)


class ADX(Indicator):
    """
    Average Directional Index

    Measures trend strength (0-100)
    """
    def calculate_with_hlc(self, high: List[float], low: List[float],
                           close: List[float]) -> Dict[str, List[float]]:
        """Calculate ADX with high, low, close data"""
        if len(close) < self.period + 1:
            return {'adx': [], 'plus_di': [], 'minus_di': []}

        # Calculate +DM, -DM, and TR
        plus_dm = []
        minus_dm = []
        true_ranges = []

        for i in range(1, len(close)):
            up_move = high[i] - high[i - 1]
            down_move = low[i - 1] - low[i]

            if up_move > down_move and up_move > 0:
                plus_dm.append(up_move)
            else:
                plus_dm.append(0)

            if down_move > up_move and down_move > 0:
                minus_dm.append(down_move)
            else:
                minus_dm.append(0)

            tr = max(
                high[i] - low[i],
                abs(high[i] - close[i - 1]),
                abs(low[i] - close[i - 1])
            )
            true_ranges.append(tr)

        # Calculate smoothed values
        def smooth_values(values: List[float], period: int) -> List[float]:
            if len(values) < period:
                return []
            smoothed = [sum(values[:period])]
            for v in values[period:]:
                smoothed.append(smoothed[-1] - (smoothed[-1] / period) + v)
            return smoothed

        smoothed_tr = smooth_values(true_ranges, self.period)
        smoothed_plus_dm = smooth_values(plus_dm, self.period)
        smoothed_minus_dm = smooth_values(minus_dm, self.period)

        if not smoothed_tr:
            return {'adx': [], 'plus_di': [], 'minus_di': []}

        # Calculate +DI and -DI
        plus_di = []
        minus_di = []
        for i in range(len(smoothed_tr)):
            if smoothed_tr[i] == 0:
                plus_di.append(0)
                minus_di.append(0)
            else:
                plus_di.append(100 * smoothed_plus_dm[i] / smoothed_tr[i])
                minus_di.append(100 * smoothed_minus_dm[i] / smoothed_tr[i])

        # Calculate DX
        dx = []
        for i in range(len(plus_di)):
            di_sum = plus_di[i] + minus_di[i]
            if di_sum == 0:
                dx.append(0)
            else:
                dx.append(100 * abs(plus_di[i] - minus_di[i]) / di_sum)

        # Calculate ADX (smoothed DX)
        if len(dx) < self.period:
            return {'adx': [], 'plus_di': plus_di, 'minus_di': minus_di}

        adx = [sum(dx[:self.period]) / self.period]
        for d in dx[self.period:]:
            adx.append((adx[-1] * (self.period - 1) + d) / self.period)

        return {'adx': adx, 'plus_di': plus_di, 'minus_di': minus_di}

    def calculate(self, data: List[float]) -> Dict[str, List[float]]:
        """Calculate using close prices only (simplified)"""
        return self.calculate_with_hlc(data, data, data)


class IchimokuCloud(Indicator):
    """
    Ichimoku Kinko Hyo (Ichimoku Cloud)

    Complete trading system with:
    - Tenkan-sen (Conversion Line): 9-period high+low/2
    - Kijun-sen (Base Line): 26-period high+low/2
    - Senkou Span A (Leading Span A): (Tenkan + Kijun)/2, shifted 26 periods ahead
    - Senkou Span B (Leading Span B): 52-period high+low/2, shifted 26 periods ahead
    - Chikou Span (Lagging Span): Close shifted 26 periods back
    """
    def __init__(self, name: str = 'Ichimoku', tenkan_period: int = 9,
                 kijun_period: int = 26, senkou_b_period: int = 52,
                 displacement: int = 26):
        super().__init__(name, tenkan_period)
        self.tenkan_period = tenkan_period
        self.kijun_period = kijun_period
        self.senkou_b_period = senkou_b_period
        self.displacement = displacement

    def _calculate_midpoint(self, high: List[float], low: List[float],
                            period: int) -> List[float]:
        """Calculate (highest high + lowest low) / 2 for a period"""
        if len(high) < period:
            return []

        result = []
        for i in range(period - 1, len(high)):
            highest = max(high[i - period + 1:i + 1])
            lowest = min(low[i - period + 1:i + 1])
            result.append((highest + lowest) / 2)
        return result

    def calculate_with_hlc(self, high: List[float], low: List[float],
                           close: List[float]) -> Dict[str, List[float]]:
        """Calculate Ichimoku Cloud with high, low, close data"""
        if len(close) < self.senkou_b_period:
            return {
                'tenkan_sen': [],
                'kijun_sen': [],
                'senkou_span_a': [],
                'senkou_span_b': [],
                'chikou_span': []
            }

        # Tenkan-sen (Conversion Line)
        tenkan_sen = self._calculate_midpoint(high, low, self.tenkan_period)

        # Kijun-sen (Base Line)
        kijun_sen = self._calculate_midpoint(high, low, self.kijun_period)

        # Senkou Span B (Leading Span B)
        senkou_span_b = self._calculate_midpoint(high, low, self.senkou_b_period)

        # Senkou Span A (Leading Span A) - average of Tenkan and Kijun
        # Align lengths
        min_len = min(len(tenkan_sen), len(kijun_sen))
        tenkan_aligned = tenkan_sen[-min_len:]
        kijun_aligned = kijun_sen[-min_len:]
        senkou_span_a = [(t + k) / 2 for t, k in zip(tenkan_aligned, kijun_aligned)]

        # Chikou Span (Lagging Span) - close price shifted back
        chikou_span = close[self.displacement:]

        return {
            'tenkan_sen': tenkan_sen,
            'kijun_sen': kijun_sen,
            'senkou_span_a': senkou_span_a,
            'senkou_span_b': senkou_span_b,
            'chikou_span': chikou_span
        }

    def calculate(self, data: List[float]) -> Dict[str, List[float]]:
        """Calculate using close prices only (simplified)"""
        return self.calculate_with_hlc(data, data, data)


class FibonacciRetracement:
    """
    Fibonacci Retracement Calculator

    Standard Fibonacci levels: 0%, 23.6%, 38.2%, 50%, 61.8%, 78.6%, 100%
    Extension levels: 127.2%, 161.8%, 261.8%
    """
    RETRACEMENT_LEVELS = [0.0, 0.236, 0.382, 0.5, 0.618, 0.786, 1.0]
    EXTENSION_LEVELS = [1.272, 1.618, 2.618]

    @staticmethod
    def calculate_levels(swing_high: float, swing_low: float,
                         is_uptrend: bool = True) -> Dict[str, float]:
        """
        Calculate Fibonacci retracement levels

        Args:
            swing_high: The high point of the swing
            swing_low: The low point of the swing
            is_uptrend: True if measuring retracement in uptrend

        Returns:
            Dictionary of level names to price values
        """
        diff = swing_high - swing_low
        levels = {}

        for level in FibonacciRetracement.RETRACEMENT_LEVELS:
            if is_uptrend:
                price = swing_high - (diff * level)
            else:
                price = swing_low + (diff * level)
            levels[f'{level * 100:.1f}%'] = price

        return levels

    @staticmethod
    def calculate_extensions(swing_high: float, swing_low: float,
                             is_uptrend: bool = True) -> Dict[str, float]:
        """Calculate Fibonacci extension levels"""
        diff = swing_high - swing_low
        levels = {}

        for level in FibonacciRetracement.EXTENSION_LEVELS:
            if is_uptrend:
                price = swing_high + (diff * (level - 1))
            else:
                price = swing_low - (diff * (level - 1))
            levels[f'{level * 100:.1f}%'] = price

        return levels

    @staticmethod
    def auto_detect_swings(high: List[float], low: List[float],
                           lookback: int = 20) -> Tuple[float, float]:
        """
        Auto-detect swing high and low from price data

        Args:
            high: List of high prices
            low: List of low prices
            lookback: Period to look back for swing detection

        Returns:
            Tuple of (swing_high, swing_low)
        """
        if len(high) < lookback or len(low) < lookback:
            return (max(high), min(low)) if high and low else (0, 0)

        recent_high = high[-lookback:]
        recent_low = low[-lookback:]

        return (max(recent_high), min(recent_low))


class VolumeProfile:
    """
    Volume Profile / Volume by Price

    Shows volume distribution at different price levels
    """
    @staticmethod
    def calculate(close: List[float], volume: List[float],
                  num_bins: int = 24) -> Dict[str, Any]:
        """
        Calculate volume profile

        Args:
            close: List of close prices
            volume: List of volume values
            num_bins: Number of price bins

        Returns:
            Dictionary with price levels and volume at each level
        """
        if not close or not volume or len(close) != len(volume):
            return {'levels': [], 'volumes': [], 'poc': None}

        price_min = min(close)
        price_max = max(close)
        if price_min == price_max:
            return {'levels': [price_min], 'volumes': [sum(volume)], 'poc': price_min}

        bin_size = (price_max - price_min) / num_bins
        levels = [price_min + (i + 0.5) * bin_size for i in range(num_bins)]
        volumes = [0.0] * num_bins

        for price, vol in zip(close, volume):
            bin_idx = int((price - price_min) / bin_size)
            bin_idx = min(bin_idx, num_bins - 1)
            volumes[bin_idx] += vol

        # Point of Control (POC) - price level with highest volume
        poc_idx = volumes.index(max(volumes))
        poc = levels[poc_idx]

        return {
            'levels': levels,
            'volumes': volumes,
            'poc': poc,
            'value_area_high': None,  # Can be calculated
            'value_area_low': None    # Can be calculated
        }


class OBV(Indicator):
    """
    On-Balance Volume

    Cumulative volume indicator that adds volume on up days
    and subtracts on down days
    """
    def calculate_with_volume(self, close: List[float],
                              volume: List[float]) -> List[float]:
        """Calculate OBV with close prices and volume"""
        if len(close) < 2 or len(volume) < 2:
            return []

        obv = [0]
        for i in range(1, len(close)):
            if close[i] > close[i - 1]:
                obv.append(obv[-1] + volume[i])
            elif close[i] < close[i - 1]:
                obv.append(obv[-1] - volume[i])
            else:
                obv.append(obv[-1])

        return obv

    def calculate(self, data: List[float]) -> List[float]:
        """Calculate using equal volume (simplified)"""
        return self.calculate_with_volume(data, [1] * len(data))


class VWAP(Indicator):
    """
    Volume Weighted Average Price

    Typically calculated for intraday sessions
    """
    @staticmethod
    def calculate(high: List[float], low: List[float],
                  close: List[float], volume: List[float]) -> List[float]:
        """
        Calculate VWAP

        Args:
            high: List of high prices
            low: List of low prices
            close: List of close prices
            volume: List of volume values

        Returns:
            List of VWAP values
        """
        if not all([high, low, close, volume]):
            return []

        typical_price = [(h + l + c) / 3 for h, l, c in zip(high, low, close)]
        tp_volume = [tp * v for tp, v in zip(typical_price, volume)]

        cumulative_tp_vol = []
        cumulative_vol = []
        vwap_values = []

        running_tp_vol = 0
        running_vol = 0

        for i in range(len(close)):
            running_tp_vol += tp_volume[i]
            running_vol += volume[i]
            cumulative_tp_vol.append(running_tp_vol)
            cumulative_vol.append(running_vol)

            if running_vol > 0:
                vwap_values.append(running_tp_vol / running_vol)
            else:
                vwap_values.append(typical_price[i])

        return vwap_values


class KeltnerChannels(Indicator):
    """
    Keltner Channels

    Similar to Bollinger Bands but uses ATR instead of standard deviation
    """
    def __init__(self, name: str = 'Keltner', period: int = 20,
                 atr_period: int = 10, multiplier: float = 2.0):
        super().__init__(name, period)
        self.atr_period = atr_period
        self.multiplier = multiplier

    def calculate_with_hlc(self, high: List[float], low: List[float],
                           close: List[float]) -> Dict[str, List[float]]:
        """Calculate Keltner Channels with high, low, close data"""
        # Calculate middle line (EMA of close)
        middle = EMA('middle', self.period).calculate(close)

        # Calculate ATR
        atr_indicator = ATR('atr', self.atr_period)
        atr_values = atr_indicator.calculate_with_hlc(high, low, close)

        if not middle or not atr_values:
            return {'upper': [], 'middle': [], 'lower': []}

        # Align lengths
        min_len = min(len(middle), len(atr_values))
        middle = middle[-min_len:]
        atr_values = atr_values[-min_len:]

        upper = [m + self.multiplier * a for m, a in zip(middle, atr_values)]
        lower = [m - self.multiplier * a for m, a in zip(middle, atr_values)]

        return {
            'upper': upper,
            'middle': middle,
            'lower': lower
        }

    def calculate(self, data: List[float]) -> Dict[str, List[float]]:
        """Calculate using close prices only (simplified)"""
        return self.calculate_with_hlc(data, data, data)


class ParabolicSAR(Indicator):
    """
    Parabolic Stop and Reverse

    Trend-following indicator that provides entry/exit signals
    """
    def __init__(self, name: str = 'PSAR', acceleration: float = 0.02,
                 max_acceleration: float = 0.2):
        super().__init__(name, 1)
        self.acceleration = acceleration
        self.max_acceleration = max_acceleration

    def calculate_with_hl(self, high: List[float],
                          low: List[float]) -> Dict[str, Any]:
        """Calculate Parabolic SAR with high and low data"""
        if len(high) < 2:
            return {'sar': [], 'trend': []}

        n = len(high)
        sar = [0.0] * n
        trend = [1] * n  # 1 for uptrend, -1 for downtrend
        ep = [0.0] * n   # Extreme point
        af = [self.acceleration] * n  # Acceleration factor

        # Initialize
        if high[1] > high[0]:
            trend[0] = 1
            sar[0] = low[0]
            ep[0] = high[0]
        else:
            trend[0] = -1
            sar[0] = high[0]
            ep[0] = low[0]

        for i in range(1, n):
            if trend[i - 1] == 1:  # Uptrend
                sar[i] = sar[i - 1] + af[i - 1] * (ep[i - 1] - sar[i - 1])
                sar[i] = min(sar[i], low[i - 1], low[i - 2] if i > 1 else low[i - 1])

                if low[i] < sar[i]:
                    trend[i] = -1
                    sar[i] = ep[i - 1]
                    ep[i] = low[i]
                    af[i] = self.acceleration
                else:
                    trend[i] = 1
                    if high[i] > ep[i - 1]:
                        ep[i] = high[i]
                        af[i] = min(af[i - 1] + self.acceleration, self.max_acceleration)
                    else:
                        ep[i] = ep[i - 1]
                        af[i] = af[i - 1]
            else:  # Downtrend
                sar[i] = sar[i - 1] + af[i - 1] * (ep[i - 1] - sar[i - 1])
                sar[i] = max(sar[i], high[i - 1], high[i - 2] if i > 1 else high[i - 1])

                if high[i] > sar[i]:
                    trend[i] = 1
                    sar[i] = ep[i - 1]
                    ep[i] = high[i]
                    af[i] = self.acceleration
                else:
                    trend[i] = -1
                    if low[i] < ep[i - 1]:
                        ep[i] = low[i]
                        af[i] = min(af[i - 1] + self.acceleration, self.max_acceleration)
                    else:
                        ep[i] = ep[i - 1]
                        af[i] = af[i - 1]

        return {'sar': sar, 'trend': trend}

    def calculate(self, data: List[float]) -> Dict[str, Any]:
        """Calculate using close prices only (simplified)"""
        return self.calculate_with_hl(data, data)


class IndicatorLibrary:
    """Library of technical indicators with TradingView-like capabilities"""

    def __init__(self):
        self.indicators = {
            # Moving Averages
            'SMA': SMA,
            'EMA': EMA,
            'WMA': WMA,
            # Oscillators
            'RSI': RSI,
            'MACD': MACD,
            'Stochastic': Stochastic,
            # Volatility
            'BB': BollingerBands,
            'BollingerBands': BollingerBands,
            'ATR': ATR,
            'KeltnerChannels': KeltnerChannels,
            # Trend
            'ADX': ADX,
            'Ichimoku': IchimokuCloud,
            'IchimokuCloud': IchimokuCloud,
            'ParabolicSAR': ParabolicSAR,
            'PSAR': ParabolicSAR,
            # Volume
            'OBV': OBV,
        }

    def get_indicator(self, name: str, period: int = 14, **kwargs) -> Indicator:
        """Get indicator instance"""
        if name in self.indicators:
            indicator_class = self.indicators[name]
            try:
                return indicator_class(name, period, **kwargs)
            except TypeError:
                # Some indicators have different constructor signatures
                return indicator_class(name, period)
        raise ValueError(f"Unknown indicator: {name}")

    def list_indicators(self) -> List[str]:
        """List available indicators"""
        return list(self.indicators.keys())

    def get_indicator_info(self) -> Dict[str, Dict[str, Any]]:
        """Get information about all indicators"""
        return {
            'SMA': {
                'name': 'Simple Moving Average',
                'category': 'Moving Average',
                'default_period': 20
            },
            'EMA': {
                'name': 'Exponential Moving Average',
                'category': 'Moving Average',
                'default_period': 20
            },
            'WMA': {
                'name': 'Weighted Moving Average',
                'category': 'Moving Average',
                'default_period': 20
            },
            'RSI': {
                'name': 'Relative Strength Index',
                'category': 'Oscillator',
                'default_period': 14
            },
            'MACD': {
                'name': 'Moving Average Convergence Divergence',
                'category': 'Oscillator',
                'default_periods': {'fast': 12, 'slow': 26, 'signal': 9}
            },
            'Stochastic': {
                'name': 'Stochastic Oscillator',
                'category': 'Oscillator',
                'default_periods': {'k': 14, 'd': 3}
            },
            'BB': {
                'name': 'Bollinger Bands',
                'category': 'Volatility',
                'default_period': 20,
                'default_std_dev': 2.0
            },
            'ATR': {
                'name': 'Average True Range',
                'category': 'Volatility',
                'default_period': 14
            },
            'KeltnerChannels': {
                'name': 'Keltner Channels',
                'category': 'Volatility',
                'default_period': 20
            },
            'ADX': {
                'name': 'Average Directional Index',
                'category': 'Trend',
                'default_period': 14
            },
            'Ichimoku': {
                'name': 'Ichimoku Cloud',
                'category': 'Trend',
                'default_periods': {
                    'tenkan': 9, 'kijun': 26,
                    'senkou_b': 52, 'displacement': 26
                }
            },
            'ParabolicSAR': {
                'name': 'Parabolic Stop and Reverse',
                'category': 'Trend',
                'default_params': {'acceleration': 0.02, 'max_acceleration': 0.2}
            },
            'OBV': {
                'name': 'On-Balance Volume',
                'category': 'Volume',
                'default_period': None
            },
            'VolumeProfile': {
                'name': 'Volume Profile / Volume by Price',
                'category': 'Volume',
                'default_bins': 24
            },
            'VWAP': {
                'name': 'Volume Weighted Average Price',
                'category': 'Volume',
                'default_period': None
            },
            'FibonacciRetracement': {
                'name': 'Fibonacci Retracement',
                'category': 'Drawing Tool',
                'levels': [0.0, 0.236, 0.382, 0.5, 0.618, 0.786, 1.0]
            }
        }
