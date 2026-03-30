# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
risk/manager.py
================
RiskManager — orchestrator-integrated position sizing and risk control.

Design invariants
-----------------
- Data quality consumed from orchestrator.get_latest_tick().confidence.
  Any trade where orchestrator reports quality below MIN_DATA_QUALITY is
  hard-rejected before sizing even begins.
- News sentiment from orchestrator.get_ml_features() gates position sizing:
  high absolute sentiment → reduced size (uncertainty scaling).
- Macro impact score from orchestrator gates max allowable position size.
- All sizing decisions written to DataLineageStore.
- No broker API called anywhere in this file.
- Kelly criterion with fractional scaling for position sizing.
- Drawdown-adaptive sizing: size scales down as drawdown increases.

Position sizing formula
-----------------------
  base_size   = account_equity * kelly_f * KELLY_FRACTION
  quality_f   = data_quality_confidence
  sentiment_f = 1 - |sentiment_score| * SENT_SCALE
  impact_f    = 1 - impact_score * IMPACT_SCALE
  dd_f        = 1 - (current_dd / MAX_DD) * DD_SCALE
  final_size  = base_size * quality_f * sentiment_f * impact_f * dd_f
  final_size  = clamp(final_size, MIN_SIZE, MAX_SIZE)
"""
from __future__ import annotations

import json
import logging
import os
import signal as _signal
import sys
import uuid
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np

logger = logging.getLogger(__name__)

# ── risk config (all env-overridable) ─────────────────────────────────────────
_ACCOUNT_EQUITY      = float(os.getenv("RISK_ACCOUNT_EQUITY",       "100000"))
_MAX_POSITION_PCT    = float(os.getenv("RISK_MAX_POSITION_PCT",      "0.05"))
_MIN_POSITION_PCT    = float(os.getenv("RISK_MIN_POSITION_PCT",      "0.001"))
_KELLY_FRACTION      = float(os.getenv("RISK_KELLY_FRACTION",        "0.25"))
_MAX_DAILY_LOSS_PCT  = float(os.getenv("RISK_MAX_DAILY_LOSS_PCT",    "0.05"))
_MAX_DRAWDOWN_PCT    = float(os.getenv("RISK_MAX_DRAWDOWN_PCT",      "0.10"))
_MAX_OPEN_POSITIONS  = int(os.getenv("RISK_MAX_OPEN_POSITIONS",      "3"))
_MIN_DATA_QUALITY    = float(os.getenv("RISK_MIN_DATA_QUALITY",      "0.40"))
_SENT_SIZE_SCALE     = float(os.getenv("RISK_SENT_SIZE_SCALE",       "0.40"))
_IMPACT_SIZE_SCALE   = float(os.getenv("RISK_IMPACT_SIZE_SCALE",     "0.50"))
_DD_SIZE_SCALE       = float(os.getenv("RISK_DD_SIZE_SCALE",         "0.80"))
_VAR_WINDOW          = int(os.getenv("RISK_VAR_WINDOW",              "100"))
_VAR_CONFIDENCE      = float(os.getenv("RISK_VAR_CONFIDENCE",        "0.95"))


# ── Enums ─────────────────────────────────────────────────────────────────────

class RiskLevel:
    LOW      = "low"
    MEDIUM   = "medium"
    HIGH     = "high"
    CRITICAL = "critical"


# ── Data classes ──────────────────────────────────────────────────────────────

@dataclass
class PositionSizingResult:
    """
    Result of a position sizing calculation.

    Returned by RiskManager.size_order() and consumed by:
      - execution/hopefx_engine.py  (quantity field)
      - execution/smart_router.py   (quantity field)
      - risk/__init__.py            (re-exported as PositionSize alias)
    """
    symbol:          str
    direction:       str
    quantity:        float          # position size in units (oz for gold)
    notional_usd:    float          # USD value of position
    stop_loss_usd:   float          # absolute stop loss price
    take_profit_usd: float          # absolute take profit price
    risk_usd:        float          # max loss on this trade
    kelly_f:         float = 0.0    # raw Kelly fraction used
    quality_f:       float = 1.0    # data quality scaling factor
    sentiment_f:     float = 1.0    # sentiment scaling factor
    impact_f:        float = 1.0    # macro impact scaling factor
    dd_f:            float = 1.0    # drawdown scaling factor
    lineage_id:      str   = ""
    created_at:      "datetime" = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )

    # Convenience: allow attribute access as .size (legacy callers)
    @property
    def size(self) -> float:
        return self.quantity

    @property
    def lot_size(self) -> float:
        return self.quantity


@dataclass
class RiskAssessment:
    """
    Full risk assessment for a proposed trade.

    Produced by RiskManager.assess() and consumed by Gatekeeper.
    """
    symbol:          str
    direction:       str
    approved:        bool
    risk_level:      str            # RiskLevel constant
    reason:          str            # human-readable approval/rejection reason
    sizing:          "Optional[PositionSizingResult]" = None
    data_quality:    float = 1.0
    sentiment_score: float = 0.0
    impact_score:    float = 0.0
    drawdown_pct:    float = 0.0
    daily_dd_pct:    float = 0.0
    open_positions:  int   = 0
    var_95:          float = 0.0
    timestamp:       "datetime" = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )


@dataclass
class RiskConfig:
    """Risk management configuration — mirrors env vars for runtime inspection."""
    max_position_size_pct: float = _MAX_POSITION_PCT
    min_position_size_pct: float = _MIN_POSITION_PCT
    kelly_fraction:        float = _KELLY_FRACTION
    max_daily_loss_pct:    float = _MAX_DAILY_LOSS_PCT
    max_drawdown_pct:      float = _MAX_DRAWDOWN_PCT
    max_open_positions:    int   = _MAX_OPEN_POSITIONS
    min_data_quality:      float = _MIN_DATA_QUALITY
    # Alias accepted at construction time; maps to max_daily_loss_pct.
    daily_loss_limit_pct:  float = field(default=-1.0, repr=False)

    def __post_init__(self) -> None:
        # If caller passed daily_loss_limit_pct, treat it as max_daily_loss_pct.
        if self.daily_loss_limit_pct >= 0:
            self.max_daily_loss_pct = self.daily_loss_limit_pct
        # Normalise alias to match canonical field so comparisons are consistent.
        self.daily_loss_limit_pct = self.max_daily_loss_pct


@dataclass
class SizedOrder:
    """Output of RiskManager.size_order()."""
    order_id:        str
    symbol:          str
    direction:       str
    quantity:        float
    notional_usd:    float
    kelly_f:         float
    quality_f:       float
    sentiment_f:     float
    impact_f:        float
    dd_f:            float
    stop_loss_usd:   float
    take_profit_usd: float
    risk_usd:        float
    lineage_id:      str
    created_at:      datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class RiskState:
    """Mutable risk state — updated on every fill and equity update."""
    account_equity:  float
    peak_equity:     float
    day_open_equity: float
    open_positions:  int   = 0
    daily_pnl:       float = 0.0
    total_pnl:       float = 0.0
    trade_day:       int   = 0

    @property
    def current_drawdown(self) -> float:
        if self.peak_equity <= 0:
            return 0.0
        return max(0.0, (self.peak_equity - self.account_equity) / self.peak_equity)

    @property
    def daily_drawdown(self) -> float:
        if self.day_open_equity <= 0:
            return 0.0
        return max(0.0, (self.day_open_equity - self.account_equity) / self.day_open_equity)

    def update_equity(self, equity: float) -> None:
        today = datetime.now(timezone.utc).day
        if today != self.trade_day:
            self.day_open_equity = equity
            self.trade_day       = today
        self.account_equity = equity
        if equity > self.peak_equity:
            self.peak_equity = equity


@dataclass
class DrawdownCheckResult:
    """Result of RiskManager.check_drawdown()."""
    passed:              bool
    current_drawdown:    float   # fraction, e.g. 0.05 = 5 %
    daily_drawdown:      float
    max_drawdown_pct:    float
    max_daily_loss_pct:  float


# ── RiskManager ───────────────────────────────────────────────────────────────

class RiskManager:
    """
    Orchestrator-integrated risk manager.

    Wiring
    ------
    - Reads data quality from orchestrator.get_latest_tick().confidence
    - Reads sentiment + macro features from orchestrator.get_ml_features()
    - Writes all sizing decisions to lineage_store
    - Never calls any broker for price data

    Usage
    -----
        rm = RiskManager(orchestrator=orchestrator, lineage_store=lineage_store)
        sized = rm.size_order(signal)
        if sized.quantity > 0:
            await router.route_and_execute(...)
    """

    def __init__(
        self,
        config: Optional[RiskConfig] = None,
        orchestrator=None,
        lineage_store=None,
        initial_balance: Optional[float] = None,
        halt_state_file: Optional[Any] = None,
    ) -> None:
        self._orch    = orchestrator
        self._lineage = lineage_store
        self._config  = config or RiskConfig()
        self._halt_state_file: Optional[Path] = (
            Path(halt_state_file) if halt_state_file is not None else None
        )

        # initial_balance overrides the env-var default when supplied directly
        equity = float(initial_balance) if initial_balance is not None else _ACCOUNT_EQUITY

        self._state   = RiskState(
            account_equity  = equity,
            peak_equity     = equity,
            day_open_equity = equity,
            trade_day       = datetime.now(timezone.utc).day,
        )
        self._pnl_history:    deque = deque(maxlen=_VAR_WINDOW)
        self._sizing_history: List[Dict] = []
        self._halt:           bool  = False
        self._halt_reason:    str   = ""

        # Restore persisted halt state so a restart after a halt does not
        # silently resume trading.
        self._restore_halt_state()
        self._install_signal_handlers()

    # ── Public API ────────────────────────────────────────────────────────────

    def assess(self, signal) -> "RiskAssessment":
        """
        Full risk assessment for a proposed trade signal.

        Returns RiskAssessment with approved=True/False and full context.
        Consumed by Gatekeeper and execution pipeline.
        """
        data_quality    = self._get_data_quality(signal)
        features        = self._get_orchestrator_features(signal)
        sentiment_score = float(features.get("news_sentiment_score", 0.0))
        impact_score    = float(features.get("macro_impact_score",   0.0))

        # Check halt conditions
        if self._halt:
            return RiskAssessment(
                symbol        = getattr(signal, "symbol", "XAU_USD"),
                direction     = getattr(signal, "direction", "long"),
                approved      = False,
                risk_level    = RiskLevel.CRITICAL,
                reason        = f"halted:{self._halt_reason}",
                data_quality  = data_quality,
                sentiment_score = sentiment_score,
                impact_score  = impact_score,
                drawdown_pct  = self._state.current_drawdown * 100,
                daily_dd_pct  = self._state.daily_drawdown * 100,
                open_positions = self._state.open_positions,
                var_95        = self.value_at_risk(),
            )

        if self._state.daily_drawdown >= _MAX_DAILY_LOSS_PCT:
            return RiskAssessment(
                symbol        = getattr(signal, "symbol", "XAU_USD"),
                direction     = getattr(signal, "direction", "long"),
                approved      = False,
                risk_level    = RiskLevel.CRITICAL,
                reason        = f"daily_dd:{self._state.daily_drawdown*100:.2f}%",
                data_quality  = data_quality,
                drawdown_pct  = self._state.current_drawdown * 100,
                daily_dd_pct  = self._state.daily_drawdown * 100,
                open_positions = self._state.open_positions,
            )

        if data_quality < _MIN_DATA_QUALITY:
            return RiskAssessment(
                symbol        = getattr(signal, "symbol", "XAU_USD"),
                direction     = getattr(signal, "direction", "long"),
                approved      = False,
                risk_level    = RiskLevel.HIGH,
                reason        = f"data_quality:{data_quality:.3f}",
                data_quality  = data_quality,
                sentiment_score = sentiment_score,
                impact_score  = impact_score,
            )

        # Compute sizing
        sizing = self.size_order(signal)
        approved = sizing.quantity > 0

        # Determine risk level
        dd = self._state.current_drawdown
        if dd > _MAX_DRAWDOWN_PCT * 0.8:
            risk_level = RiskLevel.HIGH
        elif dd > _MAX_DRAWDOWN_PCT * 0.5:
            risk_level = RiskLevel.MEDIUM
        else:
            risk_level = RiskLevel.LOW

        return RiskAssessment(
            symbol          = getattr(signal, "symbol", "XAU_USD"),
            direction       = getattr(signal, "direction", "long"),
            approved        = approved,
            risk_level      = risk_level,
            reason          = "approved" if approved else "zero_size",
            sizing          = sizing if approved else None,
            data_quality    = data_quality,
            sentiment_score = sentiment_score,
            impact_score    = impact_score,
            drawdown_pct    = self._state.current_drawdown * 100,
            daily_dd_pct    = self._state.daily_drawdown * 100,
            open_positions  = self._state.open_positions,
            var_95          = self.value_at_risk(),
        )

    def size_order(self, signal) -> "PositionSizingResult":
        """
        Compute position size for a signal.

        All scaling factors derived from orchestrator data.
        Returns SizedOrder with quantity=0 if any hard gate fails.
        """
        symbol     = getattr(signal, "symbol",     "XAU_USD")
        direction  = getattr(signal, "direction",  "long")
        conf       = getattr(signal, "confidence", 0.0)
        prob       = getattr(signal, "probability", 0.5)
        order_id   = str(uuid.uuid4())
        lineage_id = str(uuid.uuid4())

        def _zero(reason: str = "") -> PositionSizingResult:
            if reason:
                logger.warning("RiskManager: zero-size — %s", reason)
            return PositionSizingResult(
                symbol=symbol, direction=direction,
                quantity=0.0, notional_usd=0.0,
                stop_loss_usd=0.0, take_profit_usd=0.0, risk_usd=0.0,
                lineage_id=lineage_id,
            )

        if self._halt:
            return _zero(f"halted:{self._halt_reason}")

        if self._state.daily_drawdown >= _MAX_DAILY_LOSS_PCT:
            self._halt_trading("daily_drawdown_limit")
            return _zero("daily_drawdown_limit")

        if self._state.current_drawdown >= _MAX_DRAWDOWN_PCT:
            self._halt_trading("max_drawdown_limit")
            return _zero("max_drawdown_limit")

        if self._state.open_positions >= _MAX_OPEN_POSITIONS:
            return _zero(f"max_open_positions:{self._state.open_positions}")

        # ── Data quality gate — orchestrator is authoritative ──────────────
        data_quality = self._get_data_quality(signal)
        if data_quality < _MIN_DATA_QUALITY:
            return _zero(f"data_quality:{data_quality:.3f}<{_MIN_DATA_QUALITY}")

        # ── Pull features from orchestrator ────────────────────────────────
        features        = self._get_orchestrator_features(signal)
        sentiment_score = float(features.get("news_sentiment_score", 0.0))
        impact_score    = float(features.get("macro_impact_score",   0.0))

        # ── Scaling factors ────────────────────────────────────────────────
        quality_f   = self._quality_factor(data_quality)
        sentiment_f = self._sentiment_factor(sentiment_score)
        impact_f    = self._impact_factor(impact_score)
        dd_f        = self._drawdown_factor()
        kelly_f     = self._kelly(prob, conf)

        # ── Size computation ───────────────────────────────────────────────
        equity       = self._state.account_equity
        max_notional = equity * _MAX_POSITION_PCT
        min_notional = equity * _MIN_POSITION_PCT
        base_notional  = equity * kelly_f * _KELLY_FRACTION
        final_notional = base_notional * quality_f * sentiment_f * impact_f * dd_f
        final_notional = max(min_notional, min(final_notional, max_notional))

        mid_price = getattr(signal, "tick_mid", 1900.0)
        if mid_price <= 0:
            mid_price = 1900.0
        quantity = final_notional / mid_price

        # ── Stop / TP ──────────────────────────────────────────────────────
        spread      = getattr(signal, "tick_spread", 1.0)
        atr_proxy   = max(spread * 10, mid_price * 0.005)
        tp_dist     = atr_proxy * 2.0
        stop_loss_usd   = mid_price - atr_proxy if direction == "long" else mid_price + atr_proxy
        take_profit_usd = mid_price + tp_dist   if direction == "long" else mid_price - tp_dist
        risk_usd        = quantity * atr_proxy

        sized = PositionSizingResult(
            symbol          = symbol,
            direction       = direction,
            quantity        = round(quantity, 4),
            notional_usd    = round(final_notional, 2),
            kelly_f         = round(kelly_f, 4),
            quality_f       = round(quality_f, 4),
            sentiment_f     = round(sentiment_f, 4),
            impact_f        = round(impact_f, 4),
            dd_f            = round(dd_f, 4),
            stop_loss_usd   = round(stop_loss_usd, 4),
            take_profit_usd = round(take_profit_usd, 4),
            risk_usd        = round(risk_usd, 2),
            lineage_id      = lineage_id,
        )

        self._sizing_history.append({
            "order_id":    order_id,
            "symbol":      symbol,
            "direction":   direction,
            "quantity":    sized.quantity,
            "notional":    sized.notional_usd,
            "quality_f":   quality_f,
            "sentiment_f": sentiment_f,
            "impact_f":    impact_f,
            "dd_f":        dd_f,
            "kelly_f":     kelly_f,
            "timestamp":   datetime.now(timezone.utc).isoformat(),
        })

        self._write_sizing_lineage(sized)

        logger.info(
            "SIZED %s %s qty=%.4f notional=$%.0f "
            "kelly=%.3f qual=%.3f sent=%.3f imp=%.3f dd=%.3f",
            direction, symbol, sized.quantity, sized.notional_usd,
            kelly_f, quality_f, sentiment_f, impact_f, dd_f,
        )
        return sized

    # ── Convenience public API (used by tests and downstream callers) ─────────

    @property
    def kill_switch_active(self) -> bool:
        """True when trading has been halted via _halt_trading()."""
        return self._halt

    def calculate_position_size(
        self,
        symbol: str,
        entry_price: float,
        account_balance: float,
        direction: str = "long",
        confidence: float = 0.7,
        probability: float = 0.55,
    ) -> "PositionSizingResult":
        """Convenience wrapper around size_order() for callers that supply
        raw parameters rather than a signal object."""

        class _Signal:
            pass

        sig = _Signal()
        sig.symbol = symbol          # type: ignore[attr-defined]
        sig.direction = direction    # type: ignore[attr-defined]
        sig.confidence = confidence  # type: ignore[attr-defined]
        sig.probability = probability  # type: ignore[attr-defined]
        sig.data_quality = 1.0       # type: ignore[attr-defined]
        sig.features = {}            # type: ignore[attr-defined]
        # Temporarily update equity so sizing reflects the supplied balance.
        prev_equity = self._state.account_equity
        self._state.account_equity = account_balance
        result = self.size_order(sig)
        self._state.account_equity = prev_equity
        return result

    def validate_trade(
        self,
        symbol: str,
        quantity: float,
        direction: str = "buy",
    ) -> "tuple[bool, str]":
        """Return (allowed, reason) for a proposed trade.

        Checks halt state, drawdown limits, and open-position cap.
        Does not perform full sizing — use assess() for that.
        """
        if self._halt:
            return False, f"halted:{self._halt_reason}"
        if self._state.daily_drawdown >= self._config.max_daily_loss_pct:
            return False, f"daily_drawdown:{self._state.daily_drawdown*100:.2f}%"
        if self._state.current_drawdown >= self._config.max_drawdown_pct:
            return False, f"drawdown:{self._state.current_drawdown*100:.2f}%"
        if self._state.open_positions >= self._config.max_open_positions:
            return False, f"max_positions:{self._config.max_open_positions}"
        if quantity <= 0:
            return False, "quantity_zero"
        return True, "approved"

    def check_drawdown(self) -> "DrawdownCheckResult":
        """Return a DrawdownCheckResult with current drawdown metrics."""
        dd = self._state.current_drawdown
        daily_dd = self._state.daily_drawdown
        passed = (
            dd < self._config.max_drawdown_pct
            and daily_dd < self._config.max_daily_loss_pct
        )
        return DrawdownCheckResult(
            passed=passed,
            current_drawdown=dd,
            daily_drawdown=daily_dd,
            max_drawdown_pct=self._config.max_drawdown_pct,
            max_daily_loss_pct=self._config.max_daily_loss_pct,
        )

    # ── Equity / position updates ─────────────────────────────────────────────

    def on_fill(self, symbol: str, direction: str, quantity: float, fill_price: float) -> None:
        self._state.open_positions += 1

    def on_close(self, symbol: str, pnl: float) -> None:
        self._state.open_positions = max(0, self._state.open_positions - 1)
        self._state.daily_pnl     += pnl
        self._state.total_pnl     += pnl
        self._pnl_history.append(pnl)

    def update_equity(self, equity: float) -> None:
        self._state.update_equity(equity)

    # ── Scaling factors ───────────────────────────────────────────────────────

    def _quality_factor(self, data_quality: float) -> float:
        lo = _MIN_DATA_QUALITY
        hi = 1.0
        if hi <= lo:
            return 1.0
        return 0.5 + 0.5 * (data_quality - lo) / (hi - lo)

    def _sentiment_factor(self, sentiment_score: float) -> float:
        return 1.0 - min(abs(sentiment_score), 1.0) * _SENT_SIZE_SCALE

    def _impact_factor(self, impact_score: float) -> float:
        return 1.0 - min(impact_score, 1.0) * _IMPACT_SIZE_SCALE

    def _drawdown_factor(self) -> float:
        dd   = self._state.current_drawdown
        frac = dd / max(_MAX_DRAWDOWN_PCT, 1e-9)
        return max(0.1, 1.0 - frac * _DD_SIZE_SCALE)

    @staticmethod
    def _kelly(probability: float, confidence: float) -> float:
        p = max(0.01, min(probability, 0.99))
        q = 1.0 - p
        b = max(0.5, confidence * 3.0)
        kelly = (p * b - q) / b
        return max(0.0, min(kelly, _MAX_POSITION_PCT))

    # ── Orchestrator data access ──────────────────────────────────────────────

    def _get_data_quality(self, signal) -> float:
        """Authoritative source: orchestrator tick confidence."""
        if self._orch is not None:
            try:
                tick = self._orch.get_latest_tick()
                if tick is not None:
                    return tick.confidence
            except Exception as exc:
                logger.debug("RiskManager: orchestrator tick fetch failed: %s", exc)
        return getattr(signal, "data_quality", 1.0)

    def _get_orchestrator_features(self, signal) -> Dict:
        """Authoritative source: orchestrator ML features."""
        if self._orch is not None:
            try:
                return self._orch.get_ml_features()
            except Exception as exc:
                logger.debug("RiskManager: orchestrator features fetch failed: %s", exc)
        return getattr(signal, "features", {})

    # ── Public orchestrator convenience accessors ─────────────────────────────

    def get_current_gold_price(self) -> Optional[float]:
        """
        Return the current consensus gold mid price from the orchestrator.

        Returns None if the orchestrator is unavailable or no tick exists.
        Used by downstream consumers (execution engine, UI) that need the
        current price alongside risk metrics.
        """
        if self._orch is not None:
            try:
                return self._orch.get_current_gold_price()
            except Exception as exc:
                logger.debug("RiskManager.get_current_gold_price error: %s", exc)
        return None

    def get_macro_impact_score(self) -> float:
        """
        Return the current macro calendar impact score [0, 1].

        Delegates to orchestrator.get_macro_impact_score().
        Returns 0.0 (no impact) when orchestrator is unavailable.
        """
        if self._orch is not None:
            try:
                return self._orch.get_macro_impact_score()
            except Exception as exc:
                logger.debug("RiskManager.get_macro_impact_score error: %s", exc)
        return 0.0

    # ── Halt-state persistence ────────────────────────────────────────────────

    def _persist_halt_state(self) -> None:
        """Write halt state to disk so restarts do not silently resume trading."""
        if self._halt_state_file is None:
            return
        try:
            self._halt_state_file.write_text(
                json.dumps({"halt": self._halt, "reason": self._halt_reason}, indent=2)
            )
        except OSError as exc:
            logger.warning("RiskManager: could not persist halt state: %s", exc)

    def _restore_halt_state(self) -> None:
        """Re-apply halt state from disk on startup."""
        if self._halt_state_file is None or not self._halt_state_file.exists():
            return
        try:
            data = json.loads(self._halt_state_file.read_text())
            if data.get("halt"):
                self._halt        = True
                self._halt_reason = data.get("reason", "restored from halt_state_file")
                logger.critical(
                    "RiskManager: halt restored from %s — reason=%s",
                    self._halt_state_file, self._halt_reason,
                )
        except Exception as exc:
            logger.warning("RiskManager: could not restore halt state: %s", exc)

    def _clear_halt_state(self) -> None:
        """Remove the halt-state file after a successful resume."""
        if self._halt_state_file is None:
            return
        try:
            if self._halt_state_file.exists():
                self._halt_state_file.unlink()
        except OSError as exc:
            logger.warning("RiskManager: could not clear halt state file: %s", exc)

    # ── Halt ──────────────────────────────────────────────────────────────────

    def _halt_trading(self, reason: str) -> None:
        self._halt        = True
        self._halt_reason = reason
        logger.critical("RiskManager: TRADING HALTED — reason=%s", reason)
        self._persist_halt_state()

    def resume_trading(self) -> None:
        """Manual resume — requires explicit operator action."""
        self._halt        = False
        self._halt_reason = ""
        self._clear_halt_state()
        logger.warning("RiskManager: trading RESUMED by operator")

    # ── VaR ───────────────────────────────────────────────────────────────────

    def value_at_risk(self) -> float:
        if len(self._pnl_history) < 10:
            return 0.0
        arr = np.array(list(self._pnl_history))
        return float(np.percentile(arr, (1 - _VAR_CONFIDENCE) * 100))

    # ── Signal handlers ───────────────────────────────────────────────────────

    def _install_signal_handlers(self) -> None:
        def _handle(signum, frame):
            sig_name = _signal.Signals(signum).name
            logger.warning("Signal %s received — halting trading.", sig_name)
            self._halt_trading(f"OS_signal:{sig_name}")
            sys.exit(0)
        try:
            _signal.signal(_signal.SIGTERM, _handle)
            _signal.signal(_signal.SIGINT,  _handle)
        except (OSError, ValueError):
            pass  # not in main thread

    # ── Lineage ───────────────────────────────────────────────────────────────

    def _write_sizing_lineage(self, sized: "PositionSizingResult") -> None:
        if self._lineage is None:
            return
        try:
            self._lineage.record_signal(
                direction     = f"SIZE:{sized.direction}",
                confidence    = sized.kelly_f,
                probability   = sized.quality_f,
                features_hash = sized.lineage_id[:16],
                model_version = (
                    f"risk:q={sized.quality_f:.2f}"
                    f",s={sized.sentiment_f:.2f}"
                    f",i={sized.impact_f:.2f}"
                    f",d={sized.dd_f:.2f}"
                ),
                lineage_id    = sized.lineage_id,
                symbol        = sized.symbol,
            )
        except Exception as exc:
            logger.debug("RiskManager lineage write failed: %s", exc)

    # ── Diagnostics ───────────────────────────────────────────────────────────

    def metrics(self) -> Dict[str, Any]:
        return {
            "account_equity":   round(self._state.account_equity, 2),
            "peak_equity":      round(self._state.peak_equity, 2),
            "current_drawdown": round(self._state.current_drawdown * 100, 3),
            "daily_drawdown":   round(self._state.daily_drawdown * 100, 3),
            "daily_pnl":        round(self._state.daily_pnl, 2),
            "total_pnl":        round(self._state.total_pnl, 2),
            "open_positions":   self._state.open_positions,
            "var_95":           round(self.value_at_risk(), 2),
            "halt":             self._halt,
            "halt_reason":      self._halt_reason,
        }


# ── Module-level singleton ────────────────────────────────────────────────────
# Wired to the orchestrator singleton so data quality, sentiment, and macro
# features are sourced from the authoritative data layer at every size call.
def _make_risk_manager() -> RiskManager:
    try:
        from data_layer.orchestrator import orchestrator
        return RiskManager(orchestrator=orchestrator)
    except Exception:
        return RiskManager()  # no orchestrator in test/minimal environments


risk_manager = _make_risk_manager()
