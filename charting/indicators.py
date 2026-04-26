# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""Technical indicators for charting — full production suite.

Indicators implemented
----------------------
Moving averages : SMA, EMA, WMA, DEMA, TEMA
Momentum       : RSI, Stochastic %K/%D, Williams %R, CCI, ROC, MFI
Trend          : MACD (line / signal / histogram), ADX / +DI / -DI
Volatility     : Bollinger Bands, ATR, Keltner Channels, Donchian Channels
Volume         : OBV, VWAP, CMF (Chaikin Money Flow)
Composite      : Ichimoku Cloud (Tenkan / Kijun / Senkou A & B / Chikou)

All calculations are pure-Python with no external dependencies so the
charting module can be imported in any environment.
"""

import abc
import logging
import math

logger = logging.getLogger(__name__)


# ── Abstract base ─────────────────────────────────────────────────────────────


class Indicator(abc.ABC):
    """Abstract base class for all technical indicators."""

    def __init__(self, name: str, period: int = 14):
        self.name = name
        self.period = period

    @abc.abstractmethod
    def calculate(self, data: list[float]) -> list[float]:
        """Compute indicator values over *data*. Returns a list (may be shorter than input)."""


# ── Moving averages ───────────────────────────────────────────────────────────


class SMA(Indicator):
    """Simple Moving Average."""

    def __init__(self, name: str = "SMA", period: int = 14):
        super().__init__(name, period)

    def calculate(self, data: list[float]) -> list[float]:
        if len(data) < self.period:
            return []
        result = []
        for i in range(self.period - 1, len(data)):
            window = data[i - self.period + 1 : i + 1]
            result.append(sum(window) / self.period)
        return result


class WMA(Indicator):
    """Weighted Moving Average — linearly weighted, most-recent bar highest weight."""

    def __init__(self, name: str = "WMA", period: int = 14):
        super().__init__(name, period)

    def calculate(self, data: list[float]) -> list[float]:
        if len(data) < self.period:
            return []
        weights = list(range(1, self.period + 1))
        denom = sum(weights)
        result = []
        for i in range(self.period - 1, len(data)):
            window = data[i - self.period + 1 : i + 1]
            result.append(sum(w * p for w, p in zip(weights, window)) / denom)
        return result


class EMA(Indicator):
    """Exponential Moving Average."""

    def __init__(self, name: str = "EMA", period: int = 14):
        super().__init__(name, period)

    def calculate(self, data: list[float]) -> list[float]:
        if len(data) < self.period:
            return []
        k = 2.0 / (self.period + 1)
        sma = sum(data[: self.period]) / self.period
        result = [sma]
        for price in data[self.period :]:
            result.append(price * k + result[-1] * (1 - k))
        return result


class DEMA(Indicator):
    """Double Exponential Moving Average — reduces lag vs plain EMA."""

    def __init__(self, name: str = "DEMA", period: int = 14):
        super().__init__(name, period)

    def calculate(self, data: list[float]) -> list[float]:
        ema1 = EMA(period=self.period).calculate(data)
        if not ema1:
            return []
        ema2 = EMA(period=self.period).calculate(ema1)
        if not ema2:
            return []
        offset = len(ema1) - len(ema2)
        return [2 * e1 - e2 for e1, e2 in zip(ema1[offset:], ema2)]


class TEMA(Indicator):
    """Triple Exponential Moving Average."""

    def __init__(self, name: str = "TEMA", period: int = 14):
        super().__init__(name, period)

    def calculate(self, data: list[float]) -> list[float]:
        ema1 = EMA(period=self.period).calculate(data)
        if not ema1:
            return []
        ema2 = EMA(period=self.period).calculate(ema1)
        if not ema2:
            return []
        ema3 = EMA(period=self.period).calculate(ema2)
        if not ema3:
            return []
        n1, n2, n3 = len(ema1), len(ema2), len(ema3)
        min_len = min(n1, n2, n3)
        return [
            3 * ema1[n1 - min_len + i] - 3 * ema2[n2 - min_len + i] + ema3[i]
            for i in range(min_len)
        ]


class RSI(Indicator):
    """Relative Strength Index."""

    def __init__(self, name: str = "RSI", period: int = 14):
        super().__init__(name, period)

    def calculate(self, data: list[float]) -> list[float]:
        if len(data) <= self.period:
            return []
        gains, losses = [], []
        for i in range(1, len(data)):
            diff = data[i] - data[i - 1]
            gains.append(max(diff, 0))
            losses.append(max(-diff, 0))

        avg_gain = sum(gains[: self.period]) / self.period
        avg_loss = sum(losses[: self.period]) / self.period

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


# ── Momentum ──────────────────────────────────────────────────────────────────


class Stochastic(Indicator):
    """Stochastic Oscillator — %K and %D lines.

    calculate() returns %K values. Use calculate_d() for the signal line.
    """

    def __init__(self, name: str = "Stochastic", period: int = 14, smooth_k: int = 3):
        super().__init__(name, period)
        self.smooth_k = smooth_k

    def calculate(self, data: list[float]) -> list[float]:
        """Return raw %K (unsmoothed)."""
        if len(data) < self.period:
            return []
        result = []
        for i in range(self.period - 1, len(data)):
            window = data[i - self.period + 1 : i + 1]
            lo, hi = min(window), max(window)
            rng = hi - lo
            result.append(100.0 * (data[i] - lo) / rng if rng else 50.0)
        return result

    def calculate_d(self, data: list[float]) -> list[float]:
        """Return %D (SMA of %K with smooth_k period)."""
        k = self.calculate(data)
        return SMA(period=self.smooth_k).calculate(k)


class WilliamsR(Indicator):
    """Williams %R — momentum oscillator, range -100 to 0."""

    def __init__(self, name: str = "WilliamsR", period: int = 14):
        super().__init__(name, period)

    def calculate(self, data: list[float]) -> list[float]:
        if len(data) < self.period:
            return []
        result = []
        for i in range(self.period - 1, len(data)):
            window = data[i - self.period + 1 : i + 1]
            lo, hi = min(window), max(window)
            rng = hi - lo
            result.append(-100.0 * (hi - data[i]) / rng if rng else -50.0)
        return result


class CCI(Indicator):
    """Commodity Channel Index.

    Requires high, low, close lists of equal length.
    calculate() accepts close prices only for the single-series interface;
    use calculate_hlc() for the proper three-series version.
    """

    def __init__(self, name: str = "CCI", period: int = 20):
        super().__init__(name, period)

    def calculate(self, data: list[float]) -> list[float]:
        """Approximate CCI using close as typical price (high=low=close)."""
        return self.calculate_hlc(data, data, data)

    def calculate_hlc(
        self,
        high: list[float],
        low: list[float],
        close: list[float],
    ) -> list[float]:
        if len(close) < self.period:
            return []
        tp = [(h + l + c) / 3 for h, l, c in zip(high, low, close)]
        result = []
        for i in range(self.period - 1, len(tp)):
            window = tp[i - self.period + 1 : i + 1]
            mean = sum(window) / self.period
            mad = sum(abs(x - mean) for x in window) / self.period
            result.append((tp[i] - mean) / (0.015 * mad) if mad else 0.0)
        return result


class ROC(Indicator):
    """Rate of Change — percentage change over *period* bars."""

    def __init__(self, name: str = "ROC", period: int = 14):
        super().__init__(name, period)

    def calculate(self, data: list[float]) -> list[float]:
        if len(data) <= self.period:
            return []
        result = []
        for i in range(self.period, len(data)):
            prev = data[i - self.period]
            result.append(100.0 * (data[i] - prev) / prev if prev else 0.0)
        return result


class MFI(Indicator):
    """Money Flow Index — volume-weighted RSI.

    calculate() accepts close prices only; use calculate_hlcv() for proper MFI.
    """

    def __init__(self, name: str = "MFI", period: int = 14):
        super().__init__(name, period)

    def calculate(self, data: list[float]) -> list[float]:
        return self.calculate_hlcv(data, data, data, [1.0] * len(data))

    def calculate_hlcv(
        self,
        high: list[float],
        low: list[float],
        close: list[float],
        volume: list[float],
    ) -> list[float]:
        if len(close) <= self.period:
            return []
        tp = [(h + l + c) / 3 for h, l, c in zip(high, low, close)]
        mf = [t * v for t, v in zip(tp, volume)]
        result = []
        for i in range(self.period, len(tp)):
            pos_mf = sum(
                mf[j] for j in range(i - self.period + 1, i + 1) if tp[j] > tp[j - 1]
            )
            neg_mf = sum(
                mf[j] for j in range(i - self.period + 1, i + 1) if tp[j] < tp[j - 1]
            )
            if neg_mf == 0:
                result.append(100.0)
            else:
                mfr = pos_mf / neg_mf
                result.append(100.0 - 100.0 / (1.0 + mfr))
        return result


# ── Trend ─────────────────────────────────────────────────────────────────────


class MACD(Indicator):
    """MACD — Moving Average Convergence Divergence.

    Returns (macd_line, signal_line, histogram) via calculate_full().
    calculate() returns the MACD line only for the single-series interface.
    """

    def __init__(
        self,
        name: str = "MACD",
        fast: int = 12,
        slow: int = 26,
        signal: int = 9,
    ):
        super().__init__(name, slow)
        self.fast = fast
        self.slow = slow
        self.signal_period = signal

    def calculate(self, data: list[float]) -> list[float]:
        macd_line, _, _ = self.calculate_full(data)
        return macd_line

    def calculate_full(
        self, data: list[float]
    ) -> tuple[list[float], list[float], list[float]]:
        """Return (macd_line, signal_line, histogram)."""
        ema_fast = EMA(period=self.fast).calculate(data)
        ema_slow = EMA(period=self.slow).calculate(data)
        if not ema_fast or not ema_slow:
            return [], [], []
        # Align: ema_slow is shorter (seeded later)
        offset = len(ema_fast) - len(ema_slow)
        macd_line = [f - s for f, s in zip(ema_fast[offset:], ema_slow)]
        signal_line = EMA(period=self.signal_period).calculate(macd_line)
        if not signal_line:
            return macd_line, [], []
        sig_offset = len(macd_line) - len(signal_line)
        histogram = [m - s for m, s in zip(macd_line[sig_offset:], signal_line)]
        return macd_line, signal_line, histogram


class ADX(Indicator):
    """Average Directional Index with +DI and -DI.

    Use calculate_full(high, low, close) for all three series.
    calculate() accepts close only (approximation).
    """

    def __init__(self, name: str = "ADX", period: int = 14):
        super().__init__(name, period)

    def calculate(self, data: list[float]) -> list[float]:
        adx, _, _ = self.calculate_full(data, data, data)
        return adx

    def calculate_full(
        self,
        high: list[float],
        low: list[float],
        close: list[float],
    ) -> tuple[list[float], list[float], list[float]]:
        """Return (adx, plus_di, minus_di)."""
        n = len(close)
        if n < self.period + 1:
            return [], [], []

        tr_list, plus_dm, minus_dm = [], [], []
        for i in range(1, n):
            h, l, pc = high[i], low[i], close[i - 1]
            tr_list.append(max(h - l, abs(h - pc), abs(l - pc)))
            up = high[i] - high[i - 1]
            dn = low[i - 1] - low[i]
            plus_dm.append(up if up > dn and up > 0 else 0.0)
            minus_dm.append(dn if dn > up and dn > 0 else 0.0)

        def _smooth(series: list[float], p: int) -> list[float]:
            if len(series) < p:
                return []
            out = [sum(series[:p])]
            for v in series[p:]:
                out.append(out[-1] - out[-1] / p + v)
            return out

        atr_s = _smooth(tr_list, self.period)
        pdm_s = _smooth(plus_dm, self.period)
        mdm_s = _smooth(minus_dm, self.period)

        plus_di = [100 * p / a if a else 0.0 for p, a in zip(pdm_s, atr_s)]
        minus_di = [100 * m / a if a else 0.0 for m, a in zip(mdm_s, atr_s)]
        dx = [
            100 * abs(p - m) / (p + m) if (p + m) else 0.0
            for p, m in zip(plus_di, minus_di)
        ]
        adx = _smooth(dx, self.period)
        # Align all to shortest
        min_len = min(len(adx), len(plus_di), len(minus_di))
        return adx[-min_len:], plus_di[-min_len:], minus_di[-min_len:]


# ── Volatility ────────────────────────────────────────────────────────────────


class BollingerBands(Indicator):
    """Bollinger Bands — upper, middle (SMA), lower bands.

    calculate() returns the middle band. Use calculate_full() for all three.
    """

    def __init__(self, name: str = "BB", period: int = 20, std_dev: float = 2.0):
        super().__init__(name, period)
        self.std_dev = std_dev

    def calculate(self, data: list[float]) -> list[float]:
        _, mid, _ = self.calculate_full(data)
        return mid

    def calculate_full(
        self, data: list[float]
    ) -> tuple[list[float], list[float], list[float]]:
        """Return (upper, middle, lower)."""
        if len(data) < self.period:
            return [], [], []
        upper, mid, lower = [], [], []
        for i in range(self.period - 1, len(data)):
            window = data[i - self.period + 1 : i + 1]
            mean = sum(window) / self.period
            variance = sum((x - mean) ** 2 for x in window) / self.period
            std = math.sqrt(variance)
            mid.append(mean)
            upper.append(mean + self.std_dev * std)
            lower.append(mean - self.std_dev * std)
        return upper, mid, lower


class ATR(Indicator):
    """Average True Range.

    calculate() accepts close only (approximation: TR = |close[i] - close[i-1]|).
    Use calculate_hlc() for the proper high/low/close version.
    """

    def __init__(self, name: str = "ATR", period: int = 14):
        super().__init__(name, period)

    def calculate(self, data: list[float]) -> list[float]:
        return self.calculate_hlc(data, data, data)

    def calculate_hlc(
        self,
        high: list[float],
        low: list[float],
        close: list[float],
    ) -> list[float]:
        if len(close) <= self.period:
            return []
        tr_list = []
        for i in range(1, len(close)):
            tr_list.append(
                max(
                    high[i] - low[i],
                    abs(high[i] - close[i - 1]),
                    abs(low[i] - close[i - 1]),
                )
            )
        # Wilder smoothing (same as ADX)
        atr = [sum(tr_list[: self.period]) / self.period]
        for tr in tr_list[self.period :]:
            atr.append((atr[-1] * (self.period - 1) + tr) / self.period)
        return atr


class KeltnerChannels(Indicator):
    """Keltner Channels — EMA ± multiplier × ATR.

    calculate() returns the middle line. Use calculate_full() for all three.
    """

    def __init__(
        self,
        name: str = "KC",
        period: int = 20,
        atr_period: int = 10,
        multiplier: float = 2.0,
    ):
        super().__init__(name, period)
        self.atr_period = atr_period
        self.multiplier = multiplier

    def calculate(self, data: list[float]) -> list[float]:
        mid, _, _ = self.calculate_full(data, data, data)
        return mid

    def calculate_full(
        self,
        high: list[float],
        low: list[float],
        close: list[float],
    ) -> tuple[list[float], list[float], list[float]]:
        ema = EMA(period=self.period).calculate(close)
        atr = ATR(period=self.atr_period).calculate_hlc(high, low, close)
        if not ema or not atr:
            return [], [], []
        min_len = min(len(ema), len(atr))
        mid = ema[-min_len:]
        upper = [m + self.multiplier * a for m, a in zip(mid, atr[-min_len:])]
        lower = [m - self.multiplier * a for m, a in zip(mid, atr[-min_len:])]
        return upper, mid, lower


class DonchianChannels(Indicator):
    """Donchian Channels — highest high / lowest low over *period* bars."""

    def __init__(self, name: str = "DC", period: int = 20):
        super().__init__(name, period)

    def calculate(self, data: list[float]) -> list[float]:
        mid, _, _ = self.calculate_full(data, data)
        return mid

    def calculate_full(
        self,
        high: list[float],
        low: list[float],
    ) -> tuple[list[float], list[float], list[float]]:
        if len(high) < self.period:
            return [], [], []
        upper, lower, mid = [], [], []
        for i in range(self.period - 1, len(high)):
            h_win = high[i - self.period + 1 : i + 1]
            l_win = low[i - self.period + 1 : i + 1]
            hi, lo = max(h_win), min(l_win)
            upper.append(hi)
            lower.append(lo)
            mid.append((hi + lo) / 2)
        return upper, mid, lower


# ── Volume ────────────────────────────────────────────────────────────────────


class OBV(Indicator):
    """On-Balance Volume."""

    def __init__(self, name: str = "OBV", period: int = 1):
        super().__init__(name, period)

    def calculate(self, data: list[float]) -> list[float]:
        """Approximate OBV using close prices only (volume assumed = 1)."""
        return self.calculate_cv(data, [1.0] * len(data))

    def calculate_cv(
        self, close: list[float], volume: list[float]
    ) -> list[float]:
        if not close:
            return []
        obv = [volume[0]]
        for i in range(1, len(close)):
            if close[i] > close[i - 1]:
                obv.append(obv[-1] + volume[i])
            elif close[i] < close[i - 1]:
                obv.append(obv[-1] - volume[i])
            else:
                obv.append(obv[-1])
        return obv


class VWAP(Indicator):
    """Volume-Weighted Average Price — resets each session.

    calculate() accepts close only (volume assumed = 1).
    Use calculate_hlcv() for the proper version.
    """

    def __init__(self, name: str = "VWAP", period: int = 1):
        super().__init__(name, period)

    def calculate(self, data: list[float]) -> list[float]:
        return self.calculate_hlcv(data, data, data, [1.0] * len(data))

    def calculate_hlcv(
        self,
        high: list[float],
        low: list[float],
        close: list[float],
        volume: list[float],
    ) -> list[float]:
        if not close:
            return []
        cum_tp_vol = 0.0
        cum_vol = 0.0
        result = []
        for h, l, c, v in zip(high, low, close, volume):
            tp = (h + l + c) / 3
            cum_tp_vol += tp * v
            cum_vol += v
            result.append(cum_tp_vol / cum_vol if cum_vol else tp)
        return result


class CMF(Indicator):
    """Chaikin Money Flow — measures buying/selling pressure over *period* bars."""

    def __init__(self, name: str = "CMF", period: int = 20):
        super().__init__(name, period)

    def calculate(self, data: list[float]) -> list[float]:
        return self.calculate_hlcv(data, data, data, [1.0] * len(data))

    def calculate_hlcv(
        self,
        high: list[float],
        low: list[float],
        close: list[float],
        volume: list[float],
    ) -> list[float]:
        if len(close) < self.period:
            return []
        mfv = []
        for h, l, c, v in zip(high, low, close, volume):
            rng = h - l
            clv = ((c - l) - (h - c)) / rng if rng else 0.0
            mfv.append(clv * v)
        result = []
        for i in range(self.period - 1, len(mfv)):
            vol_sum = sum(volume[i - self.period + 1 : i + 1])
            mfv_sum = sum(mfv[i - self.period + 1 : i + 1])
            result.append(mfv_sum / vol_sum if vol_sum else 0.0)
        return result


# ── Composite ─────────────────────────────────────────────────────────────────


class Ichimoku(Indicator):
    """Ichimoku Cloud — Tenkan-sen, Kijun-sen, Senkou A & B, Chikou Span.

    calculate() returns Tenkan-sen. Use calculate_full() for all components.
    """

    def __init__(
        self,
        name: str = "Ichimoku",
        tenkan: int = 9,
        kijun: int = 26,
        senkou_b: int = 52,
    ):
        super().__init__(name, kijun)
        self.tenkan = tenkan
        self.kijun = kijun
        self.senkou_b_period = senkou_b

    def _midpoint(self, high: list[float], low: list[float], period: int) -> list[float]:
        if len(high) < period:
            return []
        result = []
        for i in range(period - 1, len(high)):
            h_win = high[i - period + 1 : i + 1]
            l_win = low[i - period + 1 : i + 1]
            result.append((max(h_win) + min(l_win)) / 2)
        return result

    def calculate(self, data: list[float]) -> list[float]:
        return self._midpoint(data, data, self.tenkan)

    def calculate_full(
        self,
        high: list[float],
        low: list[float],
        close: list[float],
    ) -> dict[str, list[float]]:
        tenkan = self._midpoint(high, low, self.tenkan)
        kijun = self._midpoint(high, low, self.kijun)
        # Senkou A = (Tenkan + Kijun) / 2, aligned
        min_tk = min(len(tenkan), len(kijun))
        senkou_a = [
            (t + k) / 2
            for t, k in zip(tenkan[-min_tk:], kijun[-min_tk:])
        ]
        senkou_b = self._midpoint(high, low, self.senkou_b_period)
        # Chikou = close shifted back kijun periods (represented as current close)
        chikou = list(close)
        return {
            "tenkan": tenkan,
            "kijun": kijun,
            "senkou_a": senkou_a,
            "senkou_b": senkou_b,
            "chikou": chikou,
        }


# ── Registry ──────────────────────────────────────────────────────────────────


class IndicatorLibrary:
    """Registry of all available indicators."""

    def __init__(self) -> None:
        self.indicators: dict[str, type[Indicator]] = {
            # Moving averages
            "SMA": SMA,
            "EMA": EMA,
            "WMA": WMA,
            "DEMA": DEMA,
            "TEMA": TEMA,
            # Momentum
            "RSI": RSI,
            "STOCHASTIC": Stochastic,
            "STOCH": Stochastic,
            "WILLIAMSR": WilliamsR,
            "WILLIAMS_R": WilliamsR,
            "CCI": CCI,
            "ROC": ROC,
            "MFI": MFI,
            # Trend
            "MACD": MACD,
            "ADX": ADX,
            # Volatility
            "BB": BollingerBands,
            "BBANDS": BollingerBands,
            "BOLLINGER": BollingerBands,
            "ATR": ATR,
            "KC": KeltnerChannels,
            "KELTNER": KeltnerChannels,
            "DC": DonchianChannels,
            "DONCHIAN": DonchianChannels,
            # Volume
            "OBV": OBV,
            "VWAP": VWAP,
            "CMF": CMF,
            # Composite
            "ICHIMOKU": Ichimoku,
        }

    def get_indicator(self, name: str, **params) -> Indicator:
        cls = self.indicators.get(name.upper())
        if cls is None:
            raise ValueError(
                f"Unknown indicator: {name!r}. "
                f"Available: {', '.join(sorted(self.indicators))}"
            )
        period = params.get("period", 14)
        # Pass extra params to constructors that accept them
        try:
            return cls(name=name, period=period, **{k: v for k, v in params.items() if k != "period"})
        except TypeError:
            return cls(name=name, period=period)

    def list_indicators(self) -> list[str]:
        return sorted(set(self.indicators.keys()))

    def register(self, name: str, cls: type[Indicator]) -> None:
        self.indicators[name.upper()] = cls

    def calculate(
        self,
        name: str,
        data: list[float],
        **params,
    ) -> list[float]:
        """Convenience: get indicator by name and calculate in one call."""
        return self.get_indicator(name, **params).calculate(data)


# Module-level singleton
indicator_library = IndicatorLibrary()

# Aliases used by existing imports
TechnicalIndicators = IndicatorLibrary
