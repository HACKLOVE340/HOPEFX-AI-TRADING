# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
``ta`` API compatibility shim backed by ``ta-lib`` (C extension).

When the pure-Python ``ta`` package cannot be installed (build failures on
certain platforms), this module is injected into ``sys.modules`` as ``ta``
so that existing code using the OOP ``ta.momentum.RSIIndicator(...)`` API
keeps working without modification.

Public surface exposed
----------------------
ta.momentum.RSIIndicator(close, window)
ta.momentum.StochasticOscillator(high, low, close)
ta.trend.MACD(close, window_slow, window_fast, window_sign)
ta.trend.EMAIndicator(close, window)
ta.trend.ADXIndicator(high, low, close, window)
ta.volatility.BollingerBands(close, window, window_dev)
ta.volatility.AverageTrueRange(high, low, close, window)
"""

from __future__ import annotations

import sys
import types

import numpy as np
import pandas as pd

try:
    import talib as _talib

    _TALIB_OK = True
except ImportError:
    _TALIB_OK = False


def _to_np(s: pd.Series) -> np.ndarray:
    return np.asarray(s, dtype=np.float64)


def _wrap(arr: np.ndarray, index: pd.Index) -> pd.Series:
    return pd.Series(arr, index=index, dtype=float)


# ── Momentum ─────────────────────────────────────────────────────────────────


class RSIIndicator:
    def __init__(self, close: pd.Series, window: int = 14, fillna: bool = False):
        self._close = close
        self._window = window

    def rsi(self) -> pd.Series:
        if _TALIB_OK:
            arr = _talib.RSI(_to_np(self._close), timeperiod=self._window)
        else:
            arr = _rsi_numpy(self._close, self._window)
        return _wrap(arr, self._close.index)


class StochasticOscillator:
    def __init__(
        self,
        high: pd.Series,
        low: pd.Series,
        close: pd.Series,
        window: int = 14,
        smooth_window: int = 3,
        fillna: bool = False,
    ):
        self._high = high
        self._low = low
        self._close = close
        self._window = window
        self._smooth = smooth_window

    def stoch(self) -> pd.Series:
        if _TALIB_OK:
            k, _ = _talib.STOCH(
                _to_np(self._high),
                _to_np(self._low),
                _to_np(self._close),
                fastk_period=self._window,
                slowk_period=self._smooth,
                slowd_period=self._smooth,
            )
        else:
            k = _stoch_numpy(self._high, self._low, self._close, self._window, self._smooth)
        return _wrap(k, self._close.index)

    def stoch_signal(self) -> pd.Series:
        if _TALIB_OK:
            _, d = _talib.STOCH(
                _to_np(self._high),
                _to_np(self._low),
                _to_np(self._close),
                fastk_period=self._window,
                slowk_period=self._smooth,
                slowd_period=self._smooth,
            )
        else:
            d = _stoch_signal_numpy(self._high, self._low, self._close, self._window, self._smooth)
        return _wrap(d, self._close.index)


# ── Trend ─────────────────────────────────────────────────────────────────────


class MACD:
    def __init__(
        self,
        close: pd.Series,
        window_slow: int = 26,
        window_fast: int = 12,
        window_sign: int = 9,
        fillna: bool = False,
    ):
        self._close = close
        self._slow = window_slow
        self._fast = window_fast
        self._sign = window_sign
        if _TALIB_OK:
            m, s, h = _talib.MACD(
                _to_np(close),
                fastperiod=window_fast,
                slowperiod=window_slow,
                signalperiod=window_sign,
            )
        else:
            m, s, h = _macd_numpy(close, window_fast, window_slow, window_sign)
        self._m = _wrap(m, close.index)
        self._s = _wrap(s, close.index)
        self._h = _wrap(h, close.index)

    def macd(self) -> pd.Series:
        return self._m

    def macd_signal(self) -> pd.Series:
        return self._s

    def macd_diff(self) -> pd.Series:
        return self._h


class EMAIndicator:
    def __init__(self, close: pd.Series, window: int = 14, fillna: bool = False):
        self._close = close
        self._window = window

    def ema_indicator(self) -> pd.Series:
        if _TALIB_OK:
            arr = _talib.EMA(_to_np(self._close), timeperiod=self._window)
        else:
            arr = (
                self._close.ewm(span=self._window, adjust=False)
                .mean()
                .values  # healer: ignore — NaN for warmup bars is expected TA behaviour; callers use _wrap
            )
        return _wrap(arr, self._close.index)


class ADXIndicator:
    def __init__(
        self,
        high: pd.Series,
        low: pd.Series,
        close: pd.Series,
        window: int = 14,
        fillna: bool = False,
    ):
        self._high = high
        self._low = low
        self._close = close
        self._window = window

    def adx(self) -> pd.Series:
        if _TALIB_OK:
            arr = _talib.ADX(
                _to_np(self._high),
                _to_np(self._low),
                _to_np(self._close),
                timeperiod=self._window,
            )
        else:
            arr = _adx_numpy(self._high, self._low, self._close, self._window)
        return _wrap(arr, self._close.index)

    def adx_pos(self) -> pd.Series:
        if _TALIB_OK:
            arr = _talib.PLUS_DI(
                _to_np(self._high),
                _to_np(self._low),
                _to_np(self._close),
                timeperiod=self._window,
            )
        else:
            arr = np.full(len(self._close), np.nan)
        return _wrap(arr, self._close.index)

    def adx_neg(self) -> pd.Series:
        if _TALIB_OK:
            arr = _talib.MINUS_DI(
                _to_np(self._high),
                _to_np(self._low),
                _to_np(self._close),
                timeperiod=self._window,
            )
        else:
            arr = np.full(len(self._close), np.nan)
        return _wrap(arr, self._close.index)


# ── Volatility ────────────────────────────────────────────────────────────────


class BollingerBands:
    def __init__(
        self,
        close: pd.Series,
        window: int = 20,
        window_dev: int = 2,
        fillna: bool = False,
    ):
        self._close = close
        self._window = window
        self._dev = window_dev
        if _TALIB_OK:
            u, m, lo = _talib.BBANDS(
                _to_np(close),
                timeperiod=window,
                nbdevup=window_dev,
                nbdevdn=window_dev,
            )
        else:
            u, m, lo = _bbands_numpy(close, window, window_dev)
        self._upper = _wrap(u, close.index)
        self._mid = _wrap(m, close.index)
        self._lower = _wrap(lo, close.index)

    def bollinger_hband(self) -> pd.Series:
        return self._upper

    def bollinger_mavg(self) -> pd.Series:
        return self._mid

    def bollinger_lband(self) -> pd.Series:
        return self._lower

    def bollinger_pband(self) -> pd.Series:
        denom = (self._upper - self._lower).replace(0, np.nan)
        return ((self._close - self._lower) / denom).fillna(0.5)

    def bollinger_wband(self) -> pd.Series:
        denom = self._mid.replace(0, np.nan)
        return ((self._upper - self._lower) / denom).fillna(0.0)

    def bollinger_hband_indicator(self) -> pd.Series:
        return (self._close > self._upper).astype(float)

    def bollinger_lband_indicator(self) -> pd.Series:
        return (self._close < self._lower).astype(float)


class AverageTrueRange:
    def __init__(
        self,
        high: pd.Series,
        low: pd.Series,
        close: pd.Series,
        window: int = 14,
        fillna: bool = False,
    ):
        self._high = high
        self._low = low
        self._close = close
        self._window = window

    def average_true_range(self) -> pd.Series:
        if _TALIB_OK:
            arr = _talib.ATR(
                _to_np(self._high),
                _to_np(self._low),
                _to_np(self._close),
                timeperiod=self._window,
            )
        else:
            arr = _atr_numpy(self._high, self._low, self._close, self._window)
        return _wrap(arr, self._close.index)


# ── Pure-numpy fallback implementations ──────────────────────────────────────
# Used only when ta-lib is also unavailable.


def _rsi_numpy(close: pd.Series, period: int) -> np.ndarray:
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(
        com=period - 1, min_periods=period
    ).mean()  # healer: ignore — NaN for warmup bars is expected TA behaviour
    avg_loss = loss.ewm(
        com=period - 1, min_periods=period
    ).mean()  # healer: ignore — NaN for warmup bars is expected TA behaviour
    rs = avg_gain / (avg_loss + 1e-12)
    return (100.0 - 100.0 / (1.0 + rs)).values


def _stoch_numpy(high, low, close, k_period=14, d_period=3) -> np.ndarray:
    lo = low.rolling(k_period).min()
    hi = high.rolling(k_period).max()
    k = 100.0 * (close - lo) / (hi - lo + 1e-12)
    return k.rolling(d_period).mean().values  # healer: ignore — NaN for warmup bars is expected TA behaviour


def _stoch_signal_numpy(high, low, close, k_period=14, d_period=3) -> np.ndarray:
    k = pd.Series(_stoch_numpy(high, low, close, k_period, d_period), index=close.index)
    return k.rolling(d_period).mean().values  # healer: ignore — NaN for warmup bars is expected TA behaviour


def _macd_numpy(close, fast=12, slow=26, signal=9):
    ema_fast = close.ewm(
        span=fast, adjust=False
    ).mean()  # healer: ignore — NaN for warmup bars is expected TA behaviour
    ema_slow = close.ewm(
        span=slow, adjust=False
    ).mean()  # healer: ignore — NaN for warmup bars is expected TA behaviour
    macd = ema_fast - ema_slow
    sig = macd.ewm(span=signal, adjust=False).mean()  # healer: ignore — NaN for warmup bars is expected TA behaviour
    hist = macd - sig
    return macd.values, sig.values, hist.values


def _bbands_numpy(close, window=20, dev=2):
    mid = close.rolling(window).mean()  # healer: ignore — NaN for warmup bars is expected TA behaviour
    std = close.rolling(window).std()  # healer: ignore — NaN for warmup bars is expected TA behaviour
    upper = mid + dev * std
    lower = mid - dev * std
    return upper.values, mid.values, lower.values


def _atr_numpy(high, low, close, period=14) -> np.ndarray:
    tr = pd.concat(  # healer: ignore — NaN for warmup bars is expected TA behaviour
        [
            high - low,
            (high - close.shift(1)).abs(),
            (low - close.shift(1)).abs(),
        ],
        axis=1,
    ).max(axis=1)
    return (
        tr.ewm(com=period - 1, min_periods=period)
        .mean()
        .values  # healer: ignore — NaN for warmup bars is expected TA behaviour
    )


def _adx_numpy(high, low, close, period=14) -> np.ndarray:
    tr = pd.concat(  # healer: ignore — NaN for warmup bars is expected TA behaviour
        [
            high - low,
            (high - close.shift(1)).abs(),
            (low - close.shift(1)).abs(),
        ],
        axis=1,
    ).max(axis=1)
    plus_dm = (high.diff()).clip(lower=0)
    minus_dm = (-low.diff()).clip(lower=0)
    mask = plus_dm < minus_dm
    plus_dm[mask] = 0.0
    mask2 = minus_dm < plus_dm
    minus_dm[mask2] = 0.0
    atr = tr.ewm(
        com=period - 1, min_periods=period
    ).mean()  # healer: ignore — NaN for warmup bars is expected TA behaviour
    # Replace NaN ATR (warmup period) with a near-zero safe denominator so the
    # division below does not silently propagate NaN through valid data rows.
    # Use 1e-12 (not 0.0) to avoid computing 100*dm / (0+1e-12) ≈ 1e14 for warmup
    # rows; instead the denominator is always at least 2e-12 which is negligible
    # relative to real ATR values (typically >> 0.01 for any traded instrument).
    atr_safe = atr.fillna(1e-12)
    # Warmup rows in EWM means are NaN until min_periods is reached; coerce to
    # 0.0 before division so NaNs do not leak into pdi/mdi calculations.
    plus_dm_ewm = plus_dm.ewm(com=period - 1, min_periods=period).mean().fillna(0.0)
    minus_dm_ewm = minus_dm.ewm(com=period - 1, min_periods=period).mean().fillna(0.0)
    pdi = 100 * plus_dm_ewm / (atr_safe + 1e-12)
    mdi = 100 * minus_dm_ewm / (atr_safe + 1e-12)
    dx = 100 * (pdi - mdi).abs() / (pdi + mdi + 1e-12)
    return (
        dx.ewm(com=period - 1, min_periods=period)
        .mean()
        .values  # healer: ignore — NaN for warmup bars is expected TA behaviour
    )


# ── Module assembly ───────────────────────────────────────────────────────────


def _build_fake_ta_module() -> types.ModuleType:
    """Assemble a fake ``ta`` module tree and inject into sys.modules."""
    ta_mod = types.ModuleType("ta")
    ta_mod.__package__ = "ta"

    momentum = types.ModuleType("ta.momentum")
    momentum.RSIIndicator = RSIIndicator
    momentum.StochasticOscillator = StochasticOscillator

    trend = types.ModuleType("ta.trend")
    trend.MACD = MACD
    trend.EMAIndicator = EMAIndicator
    trend.ADXIndicator = ADXIndicator

    volatility = types.ModuleType("ta.volatility")
    volatility.BollingerBands = BollingerBands
    volatility.AverageTrueRange = AverageTrueRange

    ta_mod.momentum = momentum
    ta_mod.trend = trend
    ta_mod.volatility = volatility

    sys.modules["ta"] = ta_mod
    sys.modules["ta.momentum"] = momentum
    sys.modules["ta.trend"] = trend
    sys.modules["ta.volatility"] = volatility

    return ta_mod


def ensure_ta_available() -> None:
    """Call this early in app startup to make ``import ta`` succeed."""
    if "ta" in sys.modules:
        return
    try:
        import ta  # noqa: F401 — check if real package is importable
    except ImportError:
        _build_fake_ta_module()


# Auto-inject on import of this shim module
ensure_ta_available()
