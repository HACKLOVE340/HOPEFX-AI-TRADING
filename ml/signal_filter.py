# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""

# ── Module constants ─────────────────────────────────────────────────────────
_DEFAULT_CONFIDENCE_THRESHOLD = 0.5
_DEFAULT_CONFIDENCE_LONG = 0.55
_DEFAULT_CONFIDENCE_SHORT = 0.45
_RSI_OVERBOUGHT = 70
_RSI_OVERSOLD = 30
_RSI_NEUTRAL = 50
_RSI_PERIOD = 14
_ATR_PERIOD = 20
_MIN_SIGNAL_BARS = 5
_SPREAD_PERIOD = 10
_MAX_SPREAD_BARS = 3
_REGIME_LOOKBACK = 20
_VOLATILITY_LOOKBACK = 90

ml/signal_filter.py
===================
Production-grade signal quality filter applied before any order is sent.

The reconciled backtest root cause investigation showed that 66% directional
accuracy does NOT equal tradeable edge when:
  - The accuracy metric measures 1-bar direction
  - The hold period is 5 bars (accumulates mean-reversion noise)
  - Transaction costs are $70 round-trip

This module implements four independent gates. A signal must pass ALL gates
to be forwarded to the execution path. Any gate failure returns a FilterResult
with ``passed=False`` and a reason string.

Gates
-----
1. Confidence gate
   Signal probability must exceed SIGNAL_THRESHOLD_LONG / SIGNAL_THRESHOLD_SHORT.
   Default: 0.58 long, 0.42 short (configurable via env vars).

2. Expected value gate
   EV = confidence × avg_win - (1 - confidence) × avg_loss > EV_MIN_THRESHOLD.
   Uses a rolling window of recent trade outcomes per symbol.
   Default: EV_MIN_THRESHOLD = 0.0 (positive EV required).

3. Regime filter
   Block signals in HIGH_VOL or MEAN_REVERTING regimes where the model's
   directional accuracy is historically lower.
   Configurable via REGIME_FILTER_ENABLED env var.

4. Multi-timeframe confluence filter
   Require that the H4 and D1 trend direction agree with the signal direction.
   Configurable via MTF_CONFLUENCE_REQUIRED env var.

Usage
-----
    from ml.signal_filter import SignalFilter, FilterResult

    filt = SignalFilter()
    result = filt.check(signal_payload, ohlcv=df, symbol="XAUUSD")
    if not result.passed:
        logger.info("Signal blocked: %s", result.reason)
        return
    # proceed to execution
"""

from __future__ import annotations

import logging
import os
from collections import deque
from dataclasses import dataclass
from typing import Any

import numpy as np

logger = logging.getLogger(__name__)

# ── Environment-configurable thresholds ──────────────────────────────────────
_THRESHOLD_LONG = float(os.getenv("SIGNAL_THRESHOLD_LONG", "0.58"))
_THRESHOLD_SHORT = float(os.getenv("SIGNAL_THRESHOLD_SHORT", "0.42"))
_EV_MIN = float(os.getenv("EV_MIN_THRESHOLD", "0.0"))
_EV_WINDOW = int(os.getenv("EV_WINDOW", "50"))
_REGIME_FILTER = os.getenv("REGIME_FILTER_ENABLED", "true").lower() == "true"
_MTF_CONFLUENCE = os.getenv("MTF_CONFLUENCE_REQUIRED", "false").lower() == "true"
_MIN_CONFIDENCE_ABS = float(os.getenv("MIN_CONFIDENCE_ABS", "0.55"))
_BLACKOUT_GATE = os.getenv("BLACKOUT_GATE_ENABLED", "true").lower() == "true"
_CIRCUIT_BREAKER = os.getenv("CIRCUIT_BREAKER_ENABLED", "true").lower() == "true"
# Circuit-breaker: halt all signals when rolling accuracy drops below this
_CB_MIN_ACCURACY = float(os.getenv("CB_MIN_ACCURACY", "0.45"))
# Circuit-breaker: minimum outcomes before the breaker can trip
_CB_MIN_OUTCOMES = int(os.getenv("CB_MIN_OUTCOMES", "30"))


# ── Prometheus metrics (optional) ────────────────────────────────────────────


def _init_prometheus():
    try:
        from prometheus_client import Counter, Gauge

        class _M:
            signals_checked = Counter(
                "hopefx_signal_filter_checked_total",
                "Total signals evaluated by SignalFilter",
                ["symbol", "direction"],
            )
            signals_passed = Counter(
                "hopefx_signal_filter_passed_total",
                "Signals that passed all gates",
                ["symbol", "direction"],
            )
            signals_blocked = Counter(
                "hopefx_signal_filter_blocked_total",
                "Signals blocked by a gate",
                ["symbol", "gate"],
            )
            ev_gauge = Gauge(
                "hopefx_signal_filter_ev",
                "Current expected value estimate",
                ["symbol"],
            )
            accuracy_gauge = Gauge(
                "hopefx_signal_filter_accuracy",
                "Rolling prediction accuracy",
                ["symbol"],
            )
            circuit_breaker_trips = Counter(
                "hopefx_signal_filter_circuit_breaker_trips_total",
                "Number of times the circuit breaker tripped",
                ["symbol"],
            )

        return _M()
    except ImportError:

        class _Noop:
            class _C:
                def labels(self, **_kw):
                    return self

                def inc(self, *a, **kw):
                    pass

                def set(self, *a, **kw):
                    pass

            def __getattr__(self, _):
                return self._C()

        return _Noop()


_PROM = _init_prometheus()


@dataclass
class FilterResult:
    """Result of a signal quality check."""

    passed: bool
    reason: str = ""
    gate: str = ""  # which gate blocked (empty if passed)
    confidence: float = 0.0
    expected_value: float = 0.0
    regime: str = "unknown"
    mtf_aligned: bool | None = None

    def __bool__(self) -> bool:
        return self.passed


@dataclass
class _TradeOutcome:
    """Minimal record of a completed trade for EV calculation."""

    pnl_pct: float
    direction: int  # 1=long, -1=short
    confidence: float


class SignalFilter:
    """
    Multi-gate signal quality filter.

    Gates (evaluated in order — first failure short-circuits):
    1. Circuit-breaker  — halt all signals when rolling accuracy < CB_MIN_ACCURACY
    2. Blackout window  — block during macro HIGH-impact event windows
    3. Confidence       — probability must exceed direction-specific threshold
    4. Expected value   — rolling EV must be positive (after 10+ outcomes)
    5. Regime           — block in HIGH_VOL / MEAN_REVERTING regimes
    6. MTF confluence   — H4/D1 trend must agree with signal direction

    Regime-conditional threshold tightening
    ----------------------------------------
    When the orchestrator reports a MEAN_REVERTING regime the confidence
    thresholds are tightened by 5% to require higher conviction before
    forwarding a directional signal.

    Prometheus instrumentation
    --------------------------
    All gate decisions are exported as Prometheus counters/gauges when
    prometheus_client is installed.  Degrades gracefully when absent.

    Thread-safety
    -------------
    Read operations (check, ev_stats, get_stats) are thread-safe.
    Write operations (record_outcome) should be called from a single
    writer thread (the execution path).
    """

    def __init__(self) -> None:
        # Per-symbol rolling trade outcome windows
        self._outcomes: dict[str, deque[_TradeOutcome]] = {}
        # Global outcome window (used when per-symbol window is too small)
        self._global_outcomes: deque[_TradeOutcome] = deque(maxlen=_EV_WINDOW * 3)
        # Circuit-breaker state
        self._cb_tripped: dict[str, bool] = {}  # per-symbol trip state
        self._cb_trip_count: int = 0

    # ── Public API ────────────────────────────────────────────────────────────

    def check(
        self,
        signal: dict[str, Any],
        ohlcv: Any | None = None,
        symbol: str | None = None,
    ) -> FilterResult:
        """
        Run all gates against a signal payload.

        Parameters
        ----------
        signal : dict with keys: direction, confidence/probability, symbol
        ohlcv  : optional pandas DataFrame with OHLCV columns (for regime check)
        symbol : override signal['symbol'] for outcome lookup

        Returns FilterResult — check .passed before forwarding to execution.
        """
        sym = symbol or signal.get("symbol", "UNKNOWN")
        direction = signal.get("direction", "HOLD")
        confidence = self._extract_confidence(signal)

        _PROM.signals_checked.labels(symbol=sym, direction=direction).inc()

        # ── Gate 0: Circuit-breaker ───────────────────────────────────────────
        if _CIRCUIT_BREAKER:
            result = self._gate_circuit_breaker(sym, direction, confidence)
            if not result.passed:
                _PROM.signals_blocked.labels(symbol=sym, gate="circuit_breaker").inc()
                return result

        # ── Gate 1: Macro blackout window ─────────────────────────────────────
        if _BLACKOUT_GATE:
            result = self._gate_blackout(direction, confidence)
            if not result.passed:
                _PROM.signals_blocked.labels(symbol=sym, gate="blackout").inc()
                return result

        # ── Regime-conditional threshold tightening ───────────────────────────
        # Pull current regime from orchestrator; tighten thresholds in
        # MEAN_REVERTING regime where directional accuracy is historically lower.
        regime_str = self._get_current_regime(ohlcv)

        # ── Gate 2: Confidence (regime-adjusted) ──────────────────────────────
        result = self._gate_confidence(direction, confidence, regime=regime_str)
        if not result.passed:
            _PROM.signals_blocked.labels(symbol=sym, gate="confidence").inc()
            return result

        # ── Gate 3: Expected value ────────────────────────────────────────────
        result = self._gate_expected_value(sym, confidence, direction)
        if not result.passed:
            _PROM.signals_blocked.labels(symbol=sym, gate="expected_value").inc()
            return result

        # ── Gate 4: Regime filter (optional, requires OHLCV) ─────────────────
        if _REGIME_FILTER and ohlcv is not None:
            result = self._gate_regime(ohlcv, direction, confidence)
            if not result.passed:
                _PROM.signals_blocked.labels(symbol=sym, gate="regime").inc()
                return result

        # ── Gate 5: MTF confluence (optional) ────────────────────────────────
        if _MTF_CONFLUENCE:
            result = self._gate_mtf_confluence(sym, direction, confidence)
            if not result.passed:
                _PROM.signals_blocked.labels(symbol=sym, gate="mtf_confluence").inc()
                return result

        ev = self._compute_ev(sym, confidence)
        _PROM.signals_passed.labels(symbol=sym, direction=direction).inc()
        _PROM.ev_gauge.labels(symbol=sym).set(ev)

        return FilterResult(
            passed=True,
            reason="all gates passed",
            confidence=confidence,
            expected_value=ev,
            regime=regime_str,
        )

    def filter(
        self,
        signal: dict[str, Any],
        ohlcv: Any | None = None,
        symbol: str | None = None,
    ) -> FilterResult:
        """Alias for check() — provided for backward compatibility."""
        return self.check(signal=signal, ohlcv=ohlcv, symbol=symbol)

    def record_outcome(
        self,
        symbol: str,
        pnl_pct: float,
        direction: int,
        confidence: float,
    ) -> None:
        """
        Record a completed trade outcome for EV and circuit-breaker calculation.

        Call this from the execution path after a trade closes.
        Updates Prometheus accuracy gauge immediately.
        """
        outcome = _TradeOutcome(pnl_pct=pnl_pct, direction=direction, confidence=confidence)
        if symbol not in self._outcomes:
            self._outcomes[symbol] = deque(maxlen=_EV_WINDOW)
        self._outcomes[symbol].append(outcome)
        self._global_outcomes.append(outcome)

        # Update Prometheus accuracy gauge
        try:
            recent = list(self._outcomes[symbol])[-_CB_MIN_OUTCOMES:]
            if len(recent) >= 5:
                win_rate = sum(1 for o in recent if o.pnl_pct > 0) / len(recent)
                _PROM.accuracy_gauge.labels(symbol=symbol).set(win_rate)
        except Exception:  # nosec B110 - Prometheus metric failure must not affect signal filtering
            pass

    def ev_stats(self, symbol: str | None = None) -> dict[str, Any]:
        """Return EV statistics for monitoring/API exposure."""
        outcomes = list(self._outcomes.get(symbol or "", [])) or list(self._global_outcomes)
        if not outcomes:
            return {
                "n": 0,
                "ev": None,
                "win_rate": None,
                "avg_win": None,
                "avg_loss": None,
            }
        pnls = [o.pnl_pct for o in outcomes]
        wins = [p for p in pnls if p > 0]
        losses = [p for p in pnls if p <= 0]
        avg_win = float(np.mean(wins)) if wins else 0.0
        avg_loss = float(np.mean(losses)) if losses else 0.0
        win_rate = len(wins) / len(pnls)
        ev = win_rate * avg_win + (1 - win_rate) * avg_loss
        return {
            "n": len(pnls),
            "ev": round(ev, 6),
            "win_rate": round(win_rate, 4),
            "avg_win": round(avg_win, 6),
            "avg_loss": round(avg_loss, 6),
            "threshold": _EV_MIN,
        }

    def get_stats(self) -> dict[str, Any]:
        """
        Return aggregate filter statistics for health endpoints.

        Includes global EV stats, per-symbol outcome counts, circuit-breaker
        state, and current gate configuration.
        """
        global_stats = self.ev_stats(None)
        per_symbol: dict[str, Any] = {}
        for sym, dq in self._outcomes.items():
            if dq:
                per_symbol[sym] = self.ev_stats(sym)

        return {
            "global": global_stats,
            "per_symbol": per_symbol,
            "symbols_tracked": len(self._outcomes),
            "global_outcomes_buffered": len(self._global_outcomes),
            "circuit_breaker": {
                "enabled": _CIRCUIT_BREAKER,
                "trip_count": self._cb_trip_count,
                "tripped": dict(self._cb_tripped),
                "min_accuracy": _CB_MIN_ACCURACY,
                "min_outcomes": _CB_MIN_OUTCOMES,
            },
            "config": {
                "threshold_long": _THRESHOLD_LONG,
                "threshold_short": _THRESHOLD_SHORT,
                "ev_min": _EV_MIN,
                "ev_window": _EV_WINDOW,
                "min_confidence_abs": _MIN_CONFIDENCE_ABS,
                "regime_filter_enabled": _REGIME_FILTER,
                "mtf_confluence_required": _MTF_CONFLUENCE,
                "blackout_gate_enabled": _BLACKOUT_GATE,
                "circuit_breaker_enabled": _CIRCUIT_BREAKER,
            },
        }

    # ── Gate implementations ──────────────────────────────────────────────────

    def _gate_circuit_breaker(self, symbol: str, direction: str, confidence: float) -> FilterResult:
        """
        Gate 0: Circuit-breaker — halt all signals when rolling accuracy is too low.

        Trips when:
          - At least CB_MIN_OUTCOMES outcomes have been recorded, AND
          - Rolling win-rate < CB_MIN_ACCURACY

        Resets automatically when win-rate recovers above CB_MIN_ACCURACY.
        """
        outcomes = list(self._outcomes.get(symbol, [])) or list(self._global_outcomes)
        if len(outcomes) < _CB_MIN_OUTCOMES:
            return FilterResult(passed=True, confidence=confidence)

        pnls = [o.pnl_pct for o in outcomes[-_CB_MIN_OUTCOMES:]]
        win_rate = sum(1 for p in pnls if p > 0) / len(pnls)

        # Update Prometheus accuracy gauge
        _PROM.accuracy_gauge.labels(symbol=symbol).set(win_rate)

        was_tripped = self._cb_tripped.get(symbol, False)

        if win_rate < _CB_MIN_ACCURACY:
            if not was_tripped:
                self._cb_tripped[symbol] = True
                self._cb_trip_count += 1
                _PROM.circuit_breaker_trips.labels(symbol=symbol).inc()
                logger.warning(
                    "SignalFilter: circuit breaker TRIPPED for %s (win_rate=%.3f < %.3f, n=%d)",
                    symbol,
                    win_rate,
                    _CB_MIN_ACCURACY,
                    len(pnls),
                )
            return FilterResult(
                passed=False,
                gate="circuit_breaker",
                reason=(
                    f"Circuit breaker: win_rate={win_rate:.3f} < "
                    f"threshold={_CB_MIN_ACCURACY:.3f} over last {len(pnls)} trades"
                ),
                confidence=confidence,
            )

        # Auto-reset when accuracy recovers
        if was_tripped:
            self._cb_tripped[symbol] = False
            logger.info(
                "SignalFilter: circuit breaker RESET for %s (win_rate=%.3f recovered)",
                symbol,
                win_rate,
            )

        return FilterResult(passed=True, confidence=confidence)

    def _gate_blackout(self, direction: str, confidence: float) -> FilterResult:
        """
        Gate 1: Block signals during macro HIGH-impact event blackout windows.

        Reads from data_layer.orchestrator.is_blackout_window().
        Falls back to pass when orchestrator is unavailable.
        """
        try:
            from data_layer.orchestrator import orchestrator

            if orchestrator.is_blackout_window():
                return FilterResult(
                    passed=False,
                    gate="blackout",
                    reason="Macro HIGH-impact event blackout window — no signals",
                    confidence=confidence,
                )
        except Exception as exc:
            logger.debug("SignalFilter: blackout gate orchestrator error: %s", exc)
        return FilterResult(passed=True, confidence=confidence)

    def _get_current_regime(self, ohlcv: Any | None) -> str:
        """
        Determine the current market regime for threshold tightening.

        Priority:
        1. Orchestrator ML features (macro_is_blackout, micro_ofi)
        2. OHLCV-based Hurst + volatility (same logic as _gate_regime)
        3. "unknown" fallback
        """
        # Try orchestrator first
        try:
            from data_layer.orchestrator import orchestrator

            feats = orchestrator.get_ml_features()
            if feats:
                # Use micro_ofi as a proxy for trending vs mean-reverting
                ofi = float(feats.get("micro_ofi", 0.0))
                sentiment = float(feats.get("news_sentiment_score", 0.0))
                # Strong OFI + sentiment alignment → trending
                if abs(ofi) > 0.5 and abs(sentiment) > 0.3:
                    return "TRENDING"
        except Exception:  # nosec B110 - feature unavailable; fall back to OHLCV regime
            pass

        # Fall back to OHLCV-based regime
        if ohlcv is not None:
            try:
                import numpy as _np

                closes = _np.array(ohlcv["close"].values[-50:], dtype=float)
                if len(closes) >= 20:
                    hurst = self._hurst_exponent(closes)
                    log_ret = _np.diff(_np.log(closes))
                    rv_14 = float(_np.std(log_ret[-14:])) if len(log_ret) >= 14 else 0.0
                    rv_90 = float(_np.std(log_ret)) if len(log_ret) >= 20 else rv_14
                    if rv_90 > 0 and rv_14 > 2.0 * rv_90:
                        return "HIGH_VOL"
                    if hurst < 0.45:
                        return "MEAN_REVERTING"
                    if hurst > 0.55:
                        return "TRENDING"
            except Exception:  # nosec B110 - Hurst computation unavailable; return unknown regime
                pass

        return "unknown"

    def _gate_confidence(self, direction: str, confidence: float, regime: str = "unknown") -> FilterResult:
        """
        Gate 2: confidence must exceed the direction-specific threshold.

        Regime-conditional tightening:
          MEAN_REVERTING → thresholds tightened by 0.05 (require higher conviction)
          HIGH_VOL       → thresholds tightened by 0.03 (model less reliable)
          TRENDING       → standard thresholds
        """
        dir_upper = direction.upper()

        # HOLD / NEUTRAL signals are never forwarded
        if dir_upper in ("HOLD", "NEUTRAL", ""):
            return FilterResult(
                passed=False,
                gate="confidence",
                reason="HOLD/NEUTRAL signal — not forwarded to execution",
                confidence=confidence,
            )

        # Regime-conditional threshold adjustment
        tighten = 0.0
        if regime == "MEAN_REVERTING":
            tighten = 0.05
        elif regime == "HIGH_VOL":
            tighten = 0.03

        threshold_long = _THRESHOLD_LONG + tighten
        threshold_short = _THRESHOLD_SHORT - tighten
        min_conf = _MIN_CONFIDENCE_ABS + tighten

        # Hard floor (regime-adjusted)
        if confidence < min_conf:
            return FilterResult(
                passed=False,
                gate="confidence",
                reason=(
                    f"confidence {confidence:.3f} < floor {min_conf:.3f}"
                    + (f" (regime={regime} tighten={tighten:+.2f})" if tighten else "")
                ),
                confidence=confidence,
                regime=regime,
            )

        # Direction-specific threshold (regime-adjusted)
        if dir_upper in ("BUY", "LONG"):
            if confidence < threshold_long:
                return FilterResult(
                    passed=False,
                    gate="confidence",
                    reason=(
                        f"BUY confidence {confidence:.3f} < threshold {threshold_long:.3f}"
                        + (f" (regime={regime})" if tighten else "")
                    ),
                    confidence=confidence,
                    regime=regime,
                )
        elif dir_upper in ("SELL", "SHORT") and confidence > threshold_short:
            return FilterResult(
                passed=False,
                gate="confidence",
                reason=(
                    f"SELL confidence {confidence:.3f} > threshold {threshold_short:.3f}"
                    + (f" (regime={regime})" if tighten else "")
                ),
                confidence=confidence,
                regime=regime,
            )

        return FilterResult(passed=True, confidence=confidence, regime=regime)

    def _gate_expected_value(self, symbol: str, confidence: float, direction: str) -> FilterResult:
        """
        Gate 2: Expected value must be positive.

        EV = win_rate × avg_win + (1 - win_rate) × avg_loss

        When fewer than 10 outcomes are available, skip this gate (insufficient
        data to estimate EV reliably). This prevents the gate from blocking all
        signals at startup.
        """
        outcomes = list(self._outcomes.get(symbol, [])) or list(self._global_outcomes)

        if len(outcomes) < 10:
            # Insufficient history — skip EV gate, use confidence-only
            return FilterResult(passed=True, confidence=confidence, expected_value=0.0)

        pnls = [o.pnl_pct for o in outcomes]
        wins = [p for p in pnls if p > 0]
        losses = [p for p in pnls if p <= 0]
        win_rate = len(wins) / len(pnls)
        avg_win = float(np.mean(wins)) if wins else 0.0
        avg_loss = float(np.mean(losses)) if losses else 0.0
        ev = win_rate * avg_win + (1 - win_rate) * avg_loss

        if ev <= _EV_MIN:
            return FilterResult(
                passed=False,
                gate="expected_value",
                reason=(
                    f"EV={ev:.5f} <= threshold {_EV_MIN:.5f} "
                    f"(win_rate={win_rate:.1%}, avg_win={avg_win:.5f}, "
                    f"avg_loss={avg_loss:.5f}, n={len(pnls)})"
                ),
                confidence=confidence,
                expected_value=ev,
            )

        return FilterResult(passed=True, confidence=confidence, expected_value=ev)

    def _gate_regime(
        self,
        ohlcv: Any,
        direction: str,
        confidence: float,
    ) -> FilterResult:
        """
        Gate 3: Block signals in regimes where the model historically underperforms.

        Uses a lightweight volatility-based regime classifier:
        - HIGH_VOL: realised vol > 2× 90-day median → block (model accuracy drops)
        - MEAN_REVERTING: price oscillates around mean → block directional signals

        Falls back to pass if OHLCV data is insufficient.
        """
        try:
            closes = np.array(ohlcv["close"].values[-100:], dtype=float)
            if len(closes) < 20:
                return FilterResult(passed=True, confidence=confidence, regime="unknown")

            # Realised vol: 14-bar rolling std of log returns
            log_ret = np.diff(np.log(closes))
            if len(log_ret) < 14:
                return FilterResult(passed=True, confidence=confidence, regime="unknown")

            rv_14 = float(np.std(log_ret[-14:]))
            rv_90 = float(np.std(log_ret[-90:])) if len(log_ret) >= 90 else rv_14

            # HIGH_VOL: current vol > 2× long-run vol
            if rv_90 > 0 and rv_14 > 2.0 * rv_90:
                return FilterResult(
                    passed=False,
                    gate="regime",
                    reason=(
                        f"HIGH_VOL regime: rv14={rv_14:.5f} > 2×rv90={2 * rv_90:.5f}. "
                        "Model accuracy historically lower in high-vol regimes."
                    ),
                    confidence=confidence,
                    regime="HIGH_VOL",
                )

            # MEAN_REVERTING: Hurst exponent < 0.45 (persistent mean reversion)
            hurst = self._hurst_exponent(closes[-50:]) if len(closes) >= 50 else 0.5
            if hurst < 0.45:
                return FilterResult(
                    passed=False,
                    gate="regime",
                    reason=(
                        f"MEAN_REVERTING regime: Hurst={hurst:.3f} < 0.45. "
                        "Directional signals have negative edge in mean-reverting markets."
                    ),
                    confidence=confidence,
                    regime="MEAN_REVERTING",
                )

            regime = "TRENDING" if hurst > 0.55 else "RANDOM_WALK"
            return FilterResult(passed=True, confidence=confidence, regime=regime)

        except Exception as exc:
            logger.debug("Regime gate error (pass-through): %s", exc)
            return FilterResult(passed=True, confidence=confidence, regime="unknown")

    def _gate_mtf_confluence(self, symbol: str, direction: str, confidence: float) -> FilterResult:
        """
        Gate 4: Multi-timeframe confluence.

        Requires H4 and D1 trend direction to agree with the signal.
        Uses MTFFusionStore if available; falls back to pass if unavailable.
        """
        try:
            from research.pipeline.mtf_fusion import get_mtf_store

            store = get_mtf_store()
            if store is None:
                return FilterResult(passed=True, confidence=confidence, mtf_aligned=None)

            features = store.get(symbol, {})
            if not features:
                return FilterResult(passed=True, confidence=confidence, mtf_aligned=None)

            # MTF features: h4_trend_up, d1_trend_up (1=up, 0=down/neutral)
            h4_up = features.get("h4_trend_up", 0.5)
            d1_up = features.get("d1_trend_up", 0.5)
            dir_upper = direction.upper()

            if dir_upper in ("BUY", "LONG"):
                aligned = h4_up > 0.5 and d1_up > 0.5
            elif dir_upper in ("SELL", "SHORT"):
                aligned = h4_up < 0.5 and d1_up < 0.5
            else:
                aligned = True

            if not aligned:
                return FilterResult(
                    passed=False,
                    gate="mtf_confluence",
                    reason=(f"MTF not aligned: direction={direction} h4_trend_up={h4_up:.2f} d1_trend_up={d1_up:.2f}"),
                    confidence=confidence,
                    mtf_aligned=False,
                )

            return FilterResult(passed=True, confidence=confidence, mtf_aligned=True)

        except Exception as exc:
            logger.debug("MTF confluence gate error (pass-through): %s", exc)
            return FilterResult(passed=True, confidence=confidence, mtf_aligned=None)

    # ── Helpers ───────────────────────────────────────────────────────────────

    @staticmethod
    def _extract_confidence(signal: dict[str, Any]) -> float:
        """
        Extract normalised confidence [0, 1] from a signal dict.

        Handles both raw probability (0–1) and percentage (0–100) formats.
        """
        raw = signal.get("probability") or signal.get("confidence") or 0.5
        val = float(raw)
        # Normalise percentage to [0, 1]
        if val > 1.0:
            val = val / 100.0
        return max(0.0, min(1.0, val))

    @staticmethod
    def _hurst_exponent(prices: np.ndarray) -> float:
        """
        Estimate Hurst exponent using R/S analysis.

        H < 0.5 → mean-reverting
        H ≈ 0.5 → random walk
        H > 0.5 → trending

        Returns 0.5 on failure (neutral — no regime filter applied).
        """
        try:
            n = len(prices)
            if n < 20:
                return 0.5
            lags = range(2, min(n // 2, 20))
            rs_vals = []
            for lag in lags:
                sub = prices[:lag]
                mean = np.mean(sub)
                dev = np.cumsum(sub - mean)
                r = np.max(dev) - np.min(dev)
                s = np.std(sub, ddof=1)
                if s > 0:
                    rs_vals.append(np.log(r / s))
            if len(rs_vals) < 3:
                return 0.5
            log_lags = np.log(list(lags[: len(rs_vals)]))
            hurst = float(np.polyfit(log_lags, rs_vals, 1)[0])
            return max(0.0, min(1.0, hurst))
        except (ValueError, FloatingPointError):
            return 0.5

    def _compute_ev(self, symbol: str, confidence: float) -> float:
        """Compute current EV estimate for a symbol."""
        stats = self.ev_stats(symbol)
        if stats["ev"] is None:
            return 0.0
        return float(stats["ev"])


# ── Module-level singleton ────────────────────────────────────────────────────

_FILTER_SINGLETON: SignalFilter | None = None


def get_signal_filter() -> SignalFilter:
    """Return the module-level SignalFilter singleton (created on first call)."""
    global _FILTER_SINGLETON
    if _FILTER_SINGLETON is None:
        _FILTER_SINGLETON = SignalFilter()
    return _FILTER_SINGLETON
