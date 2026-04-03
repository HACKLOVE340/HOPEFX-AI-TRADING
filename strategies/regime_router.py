# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
strategies/regime_router.py
============================
Regime-aware strategy router.

Detects the current market regime from OHLCV data and automatically
selects the best-performing strategy for that regime based on historical
backtest results stored in a JSON manifest.

Regime → Strategy mapping (default, overridden by manifest):
  TRENDING_UP / TRENDING_DOWN  → TrendFollowing
  MEAN_REVERTING / RANGE_BOUND → MeanReversion
  HIGH_VOL                     → Breakout
  LOW_VOL                      → MeanReversion
  UNKNOWN                      → TrendFollowing (safe default)

Usage
-----
    from strategies.regime_router import RegimeRouter

    router = RegimeRouter(strategy_manager)
    regime, strategy_name = router.route(df)   # df = OHLCV DataFrame
    signals = await strategy_manager.strategies[strategy_name].generate_signals(...)
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
UTC = timezone.utc
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

# ── Regime labels (string form used throughout the app) ───────────────────────
REGIME_TRENDING_UP = "trending_up"
REGIME_TRENDING_DOWN = "trending_down"
REGIME_MEAN_REVERTING = "mean_reverting"
REGIME_RANGE_BOUND = "range_bound"
REGIME_HIGH_VOL = "high_vol"
REGIME_LOW_VOL = "low_vol"
REGIME_UNKNOWN = "unknown"

ALL_REGIMES = [
    REGIME_TRENDING_UP,
    REGIME_TRENDING_DOWN,
    REGIME_MEAN_REVERTING,
    REGIME_RANGE_BOUND,
    REGIME_HIGH_VOL,
    REGIME_LOW_VOL,
    REGIME_UNKNOWN,
]

# Default strategy per regime when no backtest history is available
_DEFAULT_REGIME_STRATEGY: dict[str, str] = {
    REGIME_TRENDING_UP: "TrendFollowing",
    REGIME_TRENDING_DOWN: "TrendFollowing",
    REGIME_MEAN_REVERTING: "MeanReversion",
    REGIME_RANGE_BOUND: "MeanReversion",
    REGIME_HIGH_VOL: "Breakout",
    REGIME_LOW_VOL: "MeanReversion",
    REGIME_UNKNOWN: "TrendFollowing",
}

_MANIFEST_PATH = Path(
    os.getenv("REGIME_MANIFEST", "ml/saved_models/regime_manifest.json"),
)


# ── Lightweight regime detector (no HMM dependency) ──────────────────────────


def detect_regime(df: pd.DataFrame, lookback: int = 50) -> tuple[str, float]:
    """
    Detect market regime from OHLCV DataFrame using simple indicators.

    Returns (regime_label, confidence) where confidence is 0.0–1.0.

    Requires columns: open, high, low, close, volume (volume optional).
    Uses the last ``lookback`` bars.
    """
    if len(df) < lookback:
        return REGIME_UNKNOWN, 0.0

    closes = df["close"].astype(float).to_numpy()[-lookback:]
    highs = df["high"].astype(float).to_numpy()[-lookback:]
    lows = df["low"].astype(float).to_numpy()[-lookback:]

    # ── Trend: compare short vs long EMA ─────────────────────────────────────
    ema_fast = _ema(closes, 10)
    ema_slow = _ema(closes, 30)
    trend_diff = (ema_fast[-1] - ema_slow[-1]) / (ema_slow[-1] + 1e-9)

    # ── Volatility: ATR relative to price ────────────────────────────────────
    atr = _atr(highs, lows, closes, 14)
    rel_atr = atr / (closes[-1] + 1e-9)

    # Historical volatility percentile
    returns = np.diff(closes) / (closes[:-1] + 1e-9)
    vol_now = np.std(returns[-14:]) if len(returns) >= 14 else 0.0
    vol_hist = np.std(returns) if len(returns) > 1 else 0.0
    vol_pct = vol_now / (vol_hist + 1e-9)

    # ── ADX-like trend strength ───────────────────────────────────────────────
    adx = _adx_approx(highs, lows, closes, 14)

    # ── Classification ────────────────────────────────────────────────────────
    if adx > 25:
        # Strong trend
        if trend_diff > 0.001:
            return REGIME_TRENDING_UP, min(adx / 50, 1.0)
        if trend_diff < -0.001:
            return REGIME_TRENDING_DOWN, min(adx / 50, 1.0)

    if vol_pct > 1.5:
        return REGIME_HIGH_VOL, min(vol_pct / 3, 1.0)

    if vol_pct < 0.6:
        return REGIME_LOW_VOL, 0.7

    if adx < 20:
        if rel_atr < 0.005:
            return REGIME_RANGE_BOUND, 0.7
        return REGIME_MEAN_REVERTING, 0.6

    return REGIME_UNKNOWN, 0.3


# ── Numeric helpers ───────────────────────────────────────────────────────────


def _ema(values: np.ndarray, period: int) -> np.ndarray:
    alpha = 2.0 / (period + 1)
    result = np.empty_like(values)
    result[0] = values[0]
    for i in range(1, len(values)):
        result[i] = alpha * values[i] + (1 - alpha) * result[i - 1]
    return result


def _atr(highs: np.ndarray, lows: np.ndarray, closes: np.ndarray, period: int) -> float:
    tr = np.maximum(
        highs[1:] - lows[1:],
        np.maximum(
            np.abs(highs[1:] - closes[:-1]),
            np.abs(lows[1:] - closes[:-1]),
        ),
    )
    if len(tr) < period:
        return float(np.mean(tr)) if len(tr) > 0 else 0.0
    return float(np.mean(tr[-period:]))


def _adx_approx(
    highs: np.ndarray,
    lows: np.ndarray,
    closes: np.ndarray,
    period: int,
) -> float:
    """Approximate ADX using directional movement."""
    if len(highs) < period + 1:
        return 0.0
    up_moves = highs[1:] - highs[:-1]
    down_moves = lows[:-1] - lows[1:]
    plus_dm = np.where((up_moves > down_moves) & (up_moves > 0), up_moves, 0.0)
    minus_dm = np.where((down_moves > up_moves) & (down_moves > 0), down_moves, 0.0)
    tr = np.maximum(
        highs[1:] - lows[1:],
        np.maximum(np.abs(highs[1:] - closes[:-1]), np.abs(lows[1:] - closes[:-1])),
    )
    atr_sum = np.sum(tr[-period:]) + 1e-9
    plus_di = 100 * np.sum(plus_dm[-period:]) / atr_sum
    minus_di = 100 * np.sum(minus_dm[-period:]) / atr_sum
    dx = 100 * abs(plus_di - minus_di) / (plus_di + minus_di + 1e-9)
    return float(dx)


# ── Manifest: per-regime strategy performance ─────────────────────────────────


@dataclass
class RegimePerformance:
    """Backtest performance of one strategy in one regime."""

    strategy_name: str
    regime: str
    sharpe: float = 0.0
    win_rate: float = 0.0
    total_trades: int = 0
    avg_return_pct: float = 0.0
    updated_at: str = field(
        default_factory=lambda: datetime.now(UTC).isoformat(),
    )


def load_regime_manifest() -> dict[str, list[RegimePerformance]]:
    """
    Load per-regime strategy performance from JSON manifest.

    Returns dict: regime_label → list of RegimePerformance sorted by Sharpe desc.
    """
    if not _MANIFEST_PATH.exists():
        return {}
    try:
        with Path(_MANIFEST_PATH).open(encoding="utf-8") as f:
            raw = json.load(f)
        result: dict[str, list[RegimePerformance]] = {}
        for regime, entries in raw.items():
            perfs = [RegimePerformance(**e) for e in entries]
            perfs.sort(key=lambda p: p.sharpe, reverse=True)
            result[regime] = perfs
        return result
    except Exception as exc:
        logger.warning("Could not load regime manifest: %s", exc)
        return {}


def save_regime_manifest(manifest: dict[str, list[RegimePerformance]]) -> None:
    """Persist regime performance manifest to disk."""
    _MANIFEST_PATH.parent.mkdir(parents=True, exist_ok=True)
    raw = {regime: [vars(p) for p in perfs] for regime, perfs in manifest.items()}
    with Path(_MANIFEST_PATH).open("w", encoding="utf-8") as f:
        json.dump(raw, f, indent=2)
    logger.info("Regime manifest saved: %s", _MANIFEST_PATH)


def update_regime_performance(
    strategy_name: str,
    regime: str,
    sharpe: float,
    win_rate: float,
    total_trades: int,
    avg_return_pct: float,
) -> None:
    """
    Update (or insert) a strategy's performance for a given regime.

    Called after each backtest run to keep the manifest current.
    """
    manifest = load_regime_manifest()
    entries = manifest.get(regime, [])

    # Replace existing entry for this strategy or append
    updated = False
    for entry in entries:
        if entry.strategy_name == strategy_name:
            entry.sharpe = sharpe
            entry.win_rate = win_rate
            entry.total_trades = total_trades
            entry.avg_return_pct = avg_return_pct
            entry.updated_at = datetime.now(UTC).isoformat()
            updated = True
            break

    if not updated:
        entries.append(
            RegimePerformance(
                strategy_name=strategy_name,
                regime=regime,
                sharpe=sharpe,
                win_rate=win_rate,
                total_trades=total_trades,
                avg_return_pct=avg_return_pct,
            ),
        )

    entries.sort(key=lambda p: p.sharpe, reverse=True)
    manifest[regime] = entries
    save_regime_manifest(manifest)


# ── RegimeRouter ──────────────────────────────────────────────────────────────


class RegimeRouter:
    """
    Routes incoming market data to the best strategy for the detected regime.

    Selection priority:
    1. Strategy with highest Sharpe in the manifest for this regime
       (only if it has ≥ 10 trades — avoids overfitting on tiny samples).
    2. Default mapping (_DEFAULT_REGIME_STRATEGY).
    3. First registered strategy (last resort).
    """

    def __init__(self, strategy_manager: Any):
        self._sm = strategy_manager
        self._manifest: dict[str, list[RegimePerformance]] = {}
        self._last_regime: str = REGIME_UNKNOWN
        self._last_confidence: float = 0.0
        self._regime_history: list[tuple[str, float, str]] = []  # (regime, conf, ts)
        self._reload_manifest()

    def _reload_manifest(self) -> None:
        self._manifest = load_regime_manifest()

    def route(self, df: pd.DataFrame) -> tuple[str, str]:
        """
        Detect regime from ``df`` and return (regime_label, strategy_name).

        The strategy_name is the key in StrategyManager.strategies.
        """
        regime, confidence = detect_regime(df)
        self._last_regime = regime
        self._last_confidence = confidence

        # Log regime changes
        ts = datetime.now(UTC).isoformat()
        if not self._regime_history or self._regime_history[-1][0] != regime:
            logger.info("Regime change → %s (confidence=%.2f)", regime, confidence)
            self._regime_history.append((regime, confidence, ts))
            if len(self._regime_history) > 500:
                self._regime_history = self._regime_history[-500:]

        strategy_name = self._select_strategy(regime)
        return regime, strategy_name

    def _select_strategy(self, regime: str) -> str:
        """Pick the best strategy for the given regime."""
        available = set(self._sm.strategies.keys()) if self._sm else set()

        # 1. Manifest-based selection
        self._reload_manifest()
        entries = self._manifest.get(regime, [])
        for entry in entries:
            if entry.strategy_name in available and entry.total_trades >= 10:
                logger.debug(
                    "Regime %s → %s (manifest Sharpe=%.2f, trades=%d)",
                    regime,
                    entry.strategy_name,
                    entry.sharpe,
                    entry.total_trades,
                )
                return entry.strategy_name

        # 2. Default mapping
        default = _DEFAULT_REGIME_STRATEGY.get(regime, "TrendFollowing")
        if default in available:
            return default

        # 3. First available
        if available:
            return next(iter(available))

        return "TrendFollowing"

    @property
    def current_regime(self) -> str:
        return self._last_regime

    @property
    def current_confidence(self) -> float:
        return self._last_confidence

    def regime_history(self, limit: int = 20) -> list[dict[str, Any]]:
        """Return recent regime transitions."""
        return [{"regime": r, "confidence": round(c, 3), "timestamp": ts} for r, c, ts in self._regime_history[-limit:]]

    def status(self) -> dict[str, Any]:
        """Return current routing status for the dashboard."""
        return {
            "current_regime": self._last_regime,
            "confidence": round(self._last_confidence, 3),
            "selected_strategy": self._select_strategy(self._last_regime),
            "manifest_entries": {
                regime: [
                    {
                        "strategy": p.strategy_name,
                        "sharpe": round(p.sharpe, 3),
                        "win_rate": round(p.win_rate, 3),
                        "trades": p.total_trades,
                    }
                    for p in perfs
                ]
                for regime, perfs in self._manifest.items()
            },
        }
