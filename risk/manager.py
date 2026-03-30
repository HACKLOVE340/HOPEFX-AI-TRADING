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
_ACCOUNT_EQUITY      = float(os.getenv("RISK_ACCOUNT_EQUITY",       "1000000"))
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

    # Extended API: .approved and .recommended_size for downstream consumers
    @property
    def approved(self) -> bool:
        """True when the sizing produced a non-zero quantity."""
        return self.quantity > 0

    @property
    def recommended_size(self) -> float:
        """Alias for quantity — the recommended position size in units."""
        return self.quantity

    @property
    def reason(self) -> str:
        """Human-readable reason for the sizing decision."""
        if self.quantity <= 0:
            return "position_size_zero"
        return "approved"


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

    # Alias: tests and downstream callers use .can_trade
    @property
    def can_trade(self) -> bool:
        return self.approved

    # Alias: .level maps to .risk_level
    @property
    def level(self) -> str:
        return self.risk_level


@dataclass
class RiskCheckResult:
    """
    Generic result for individual risk checks (position size, price tolerance,
    drawdown, correlation, concentration).

    Used by check_position_size(), check_price_tolerance(), check_drawdown(),
    check_correlation_risk(), and check_concentration().
    """
    passed:     bool
    risk_level: str = RiskLevel.LOW
    message:    str = ""
    value:      float = 0.0
    threshold:  float = 0.0


@dataclass
class TradeAssessment:
    """
    Lightweight trade-readiness assessment returned by assess_risk().

    Consumed by tests and downstream callers that need a simple
    can_trade / level answer without a full signal object.
    """
    can_trade:  bool
    level:      str = RiskLevel.LOW
    reason:     str = ""
    drawdown:   float = 0.0
    daily_dd:   float = 0.0
    messages:   List[str] = field(default_factory=list)


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

        # CVaR pre-trade gate
        # Stores recent per-trade return fractions (pnl / equity at entry).
        # Limit to 500 observations — enough for stable 95th-percentile CVaR.
        self._returns_history: deque = deque(maxlen=500)
        # Daily CVaR limit as a fraction of equity (0 = disabled).
        self._cvar_daily_limit: float = float(
            os.getenv("RISK_CVAR_DAILY_LIMIT", "0.0")
        )
        # Expose _trading_halted as an alias so tests can set it directly.
        self._trading_halted: bool = False

        # Precise drawdown tracker (trailing HWM + daily reset)
        try:
            from risk.drawdown_tracker import DrawdownTracker
            self._dd_tracker = DrawdownTracker(
                initial_balance=equity,
                max_total_dd_pct=self._config.max_drawdown_pct,
                max_daily_dd_pct=self._config.max_daily_loss_pct,
            )
        except Exception:
            self._dd_tracker = None

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

    # ── Direct state attribute proxies (used by tests and monitoring) ─────────

    @property
    def peak_equity(self) -> float:
        return self._state.peak_equity

    @peak_equity.setter
    def peak_equity(self, value: float) -> None:
        self._state.peak_equity = float(value)

    @property
    def daily_starting_equity(self) -> float:
        return self._state.day_open_equity

    @daily_starting_equity.setter
    def daily_starting_equity(self, value: float) -> None:
        self._state.day_open_equity = float(value)

    def calculate_position_size(
        self,
        symbol: str,
        entry_price: float,
        account_balance: Optional[float] = None,
        account_equity: Optional[float] = None,
        direction: str = "long",
        confidence: float = 0.7,
        probability: float = 0.55,
        signal_strength: float = 0.7,
        stop_loss_price: Optional[float] = None,
        take_profit_price: Optional[float] = None,
        volatility: float = 0.0,
        **kwargs,
    ) -> "PositionSizingResult":
        """
        Convenience wrapper around size_order() for callers that supply
        raw parameters rather than a signal object.

        Accepts both the legacy (account_balance) and extended
        (account_equity, signal_strength, stop_loss_price, take_profit_price,
        volatility) signatures so that all callers are satisfied.

        Returns a PositionSizingResult with an additional .approved property
        and .recommended_size alias for downstream consumers.
        """
        equity = float(
            account_equity or account_balance or self._state.account_equity or _ACCOUNT_EQUITY
        )
        # Use signal_strength as confidence when confidence is at default
        effective_confidence = max(confidence, signal_strength)

        class _Signal:
            pass

        sig = _Signal()
        sig.symbol = symbol                          # type: ignore[attr-defined]
        sig.direction = direction                    # type: ignore[attr-defined]
        sig.confidence = effective_confidence        # type: ignore[attr-defined]
        sig.probability = probability                # type: ignore[attr-defined]
        sig.data_quality = 1.0                       # type: ignore[attr-defined]
        sig.features = {}                            # type: ignore[attr-defined]

        # Temporarily update equity so sizing reflects the supplied balance.
        prev_equity = self._state.account_equity
        self._state.account_equity = equity
        result = self.size_order(sig)
        self._state.account_equity = prev_equity

        # Patch stop/take-profit if supplied
        if stop_loss_price is not None:
            result.stop_loss_usd = float(stop_loss_price)
        if take_profit_price is not None:
            result.take_profit_usd = float(take_profit_price)

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
        # Keep precise DrawdownTracker in sync
        if self._dd_tracker is not None:
            self._dd_tracker.update(equity=equity)
        # Auto-halt when drawdown limits are breached.
        if not self._halt:
            dd = self._state.current_drawdown
            daily_dd = self._state.daily_drawdown
            if dd >= self._config.max_drawdown_pct:
                self._halt_trading(
                    f"auto_halt:drawdown={dd*100:.2f}%>={self._config.max_drawdown_pct*100:.1f}%"
                )
            elif daily_dd >= self._config.max_daily_loss_pct:
                self._halt_trading(
                    f"auto_halt:daily_loss={daily_dd*100:.2f}%>={self._config.max_daily_loss_pct*100:.1f}%"
                )

    @property
    def current_drawdown(self) -> float:
        """Current drawdown fraction from peak equity (0.0–1.0)."""
        if self._dd_tracker is not None:
            return self._dd_tracker.current_total_dd
        return self._state.current_drawdown

    def record_partial_fill(self, pnl: float) -> None:
        """Record a partial fill P&L — updates daily realised P&L in DrawdownTracker."""
        self._state.daily_pnl += pnl
        self._state.total_pnl += pnl
        if self._dd_tracker is not None:
            self._dd_tracker.record_fill(pnl=pnl)

    def check_modify_order(
        self,
        current_equity: float,
        new_stop_loss_distance: float,
        lots: float,
        account_balance: float,
        pip_value: float = 10.0,
    ) -> tuple:
        """Validate a modify-order request against current risk limits.

        Delegates to DrawdownTracker.check_modify when available, otherwise
        performs a simple notional-risk check.

        Returns (allowed: bool, reason: str).
        """
        if self._dd_tracker is not None:
            return self._dd_tracker.check_modify(
                current_equity=current_equity,
                new_stop_loss_distance=new_stop_loss_distance,
                lots=lots,
                account_balance=account_balance,
                pip_value=pip_value,
            )
        # Fallback: simple notional risk check
        risk_usd = new_stop_loss_distance * lots * pip_value
        risk_pct = risk_usd / account_balance if account_balance > 0 else 0.0
        if risk_pct > self._config.max_position_size_pct:
            return (False, f"risk {risk_pct*100:.2f}% exceeds limit {self._config.max_position_size_pct*100:.1f}%")
        return (True, "OK")

    def get_drawdown_status(self) -> dict:
        """Return a snapshot of current drawdown state as a plain dict."""
        if self._dd_tracker is not None:
            t = self._dd_tracker
            total_dd = t.current_total_dd
            daily_dd = t.current_daily_dd
            return {
                "total_hwm":          t.total_hwm,
                "total_drawdown_pct": total_dd,
                "daily_drawdown_pct": daily_dd,
                "daily_realised_pnl": t.daily_realised_pnl,
                "total_breach":       total_dd >= t.max_total_dd_pct,
                "daily_breach":       daily_dd >= t.max_daily_dd_pct,
            }
        # Fallback from internal state
        return {
            "total_hwm":          self._state.peak_equity,
            "total_drawdown_pct": self._state.current_drawdown,
            "daily_drawdown_pct": self._state.daily_drawdown,
            "daily_realised_pnl": self._state.daily_pnl,
            "total_breach":       self._state.current_drawdown >= self._config.max_drawdown_pct,
            "daily_breach":       self._state.daily_drawdown >= self._config.max_daily_loss_pct,
        }

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
        self._halt           = True
        self._trading_halted = True
        self._halt_reason    = reason
        logger.critical("RiskManager: TRADING HALTED — reason=%s", reason)
        self._persist_halt_state()

    def resume_trading(self) -> None:
        """Manual resume — requires explicit operator action."""
        self._halt           = False
        self._trading_halted = False
        self._halt_reason    = ""
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

    # ── Legacy / convenience API (required by tests) ──────────────────────────

    def assess_risk(
        self,
        account_info: Dict[str, Any],
        positions: List[Any],
    ) -> "TradeAssessment":
        """
        Lightweight trade-readiness check from raw account info dict.

        Parameters
        ----------
        account_info : dict with keys 'equity' and/or 'balance'
        positions    : list of open positions (used for open-position count)

        Returns TradeAssessment with can_trade, level, reason, drawdown fields.
        """
        equity = float(account_info.get("equity") or account_info.get("balance") or 0.0)
        if equity > 0:
            self.update_equity(equity)

        dd = self._state.current_drawdown
        daily_dd = self._state.daily_drawdown

        if self._halt:
            return TradeAssessment(
                can_trade=False,
                level=RiskLevel.CRITICAL,
                reason=f"halted:{self._halt_reason}",
                drawdown=dd,
                daily_dd=daily_dd,
            )

        if dd >= self._config.max_drawdown_pct:
            return TradeAssessment(
                can_trade=False,
                level=RiskLevel.CRITICAL,
                reason=f"max_drawdown_exceeded:{dd*100:.2f}%",
                drawdown=dd,
                daily_dd=daily_dd,
            )

        if daily_dd >= self._config.max_daily_loss_pct:
            return TradeAssessment(
                can_trade=False,
                level=RiskLevel.HIGH,
                reason=f"daily_loss_limit:{daily_dd*100:.2f}%",
                drawdown=dd,
                daily_dd=daily_dd,
            )

        n_pos = len(positions) if positions else self._state.open_positions
        if n_pos >= self._config.max_open_positions:
            return TradeAssessment(
                can_trade=False,
                level=RiskLevel.MEDIUM,
                reason=f"max_positions:{self._config.max_open_positions}",
                drawdown=dd,
                daily_dd=daily_dd,
            )

        # CVaR pre-trade gate
        cvar_ok, cvar_msg = self.check_cvar_pre_trade()
        if not cvar_ok:
            return TradeAssessment(
                can_trade=False,
                level=RiskLevel.HIGH,
                reason="cvar_limit_exceeded",
                drawdown=dd,
                daily_dd=daily_dd,
                messages=[cvar_msg],
            )

        level = RiskLevel.LOW
        if dd > self._config.max_drawdown_pct * 0.75:
            level = RiskLevel.MEDIUM
        elif dd > self._config.max_drawdown_pct * 0.50:
            level = RiskLevel.LOW

        return TradeAssessment(
            can_trade=True,
            level=level,
            reason="approved",
            drawdown=dd,
            daily_dd=daily_dd,
            messages=[cvar_msg],
        )

    def check_position_size(
        self,
        trade: Any,
        max_pct: float = 0.05,
    ) -> "RiskCheckResult":
        """
        FIA 1.1: Validate that a trade's notional size does not exceed max_pct
        of the current account equity.

        Parameters
        ----------
        trade   : object with .size (units) and .entry_price attributes
        max_pct : maximum allowed fraction of equity (e.g. 0.05 = 5%)
        """
        try:
            size = float(getattr(trade, "size", 0) or 0)
            price = float(getattr(trade, "entry_price", 0) or 0)
            # size is treated as the USD notional of the position.
            # For FX positions, size represents the position value in account
            # currency (e.g. size=10,000 means $10,000 notional exposure).
            # entry_price is used only when size is zero (fallback).
            notional = size if size > 0 else (price or 0.0)
            equity = self._state.account_equity or _ACCOUNT_EQUITY
            pct = notional / equity if equity > 0 else 0.0

            if pct > max_pct:
                return RiskCheckResult(
                    passed=False,
                    risk_level=RiskLevel.CRITICAL,
                    message=(
                        f"Position size {pct*100:.1f}% exceeds limit {max_pct*100:.1f}% "
                        f"(notional=${notional:,.0f}, equity=${equity:,.0f})"
                    ),
                    value=pct,
                    threshold=max_pct,
                )

            level = RiskLevel.LOW
            if pct > max_pct * 0.80:
                level = RiskLevel.MEDIUM
            return RiskCheckResult(
                passed=True,
                risk_level=level,
                message=f"Position size {pct*100:.2f}% within limit {max_pct*100:.1f}%",
                value=pct,
                threshold=max_pct,
            )
        except Exception as exc:
            logger.debug("check_position_size error: %s", exc)
            return RiskCheckResult(passed=True, risk_level=RiskLevel.LOW, message="check_skipped")

    def check_price_tolerance(
        self,
        order: Any,
        current_price: float,
        tolerance: float = 0.02,
    ) -> "RiskCheckResult":
        """
        FIA 1.3: Validate that the order price is within tolerance of the
        current market price.

        Parameters
        ----------
        order         : dict or object with 'price' key/attribute
        current_price : current market mid price
        tolerance     : maximum allowed deviation as a fraction (e.g. 0.02 = 2%)
        """
        try:
            if isinstance(order, dict):
                order_price = float(order.get("price", current_price))
            else:
                order_price = float(getattr(order, "price", current_price))

            if current_price <= 0:
                return RiskCheckResult(passed=True, message="no_reference_price")

            deviation = abs(order_price - current_price) / current_price

            if deviation > tolerance:
                return RiskCheckResult(
                    passed=False,
                    risk_level=RiskLevel.HIGH,
                    message=(
                        f"Price tolerance exceeded: order={order_price:.5f} "
                        f"market={current_price:.5f} deviation={deviation*100:.2f}% "
                        f"> tolerance={tolerance*100:.1f}%"
                    ),
                    value=deviation,
                    threshold=tolerance,
                )

            return RiskCheckResult(
                passed=True,
                risk_level=RiskLevel.LOW,
                message=f"Price within tolerance: deviation={deviation*100:.3f}%",
                value=deviation,
                threshold=tolerance,
            )
        except Exception as exc:
            logger.debug("check_price_tolerance error: %s", exc)
            return RiskCheckResult(passed=True, message="check_skipped")

    def check_kill_switch(
        self,
        daily_pnl: float,
        account_value: float,
        threshold: float = 0.03,
    ) -> bool:
        """
        FIA 1.5: Activate kill switch if daily loss exceeds threshold.

        Parameters
        ----------
        daily_pnl     : current day's P&L (negative = loss)
        account_value : total account value
        threshold     : loss fraction that triggers halt (e.g. 0.03 = 3%)

        Returns True if kill switch was triggered, False otherwise.
        Sets self.kill_switch_active = True on trigger.
        """
        if account_value <= 0:
            return False
        loss_pct = abs(min(daily_pnl, 0.0)) / account_value
        if loss_pct >= threshold:
            self._halt_trading(
                f"kill_switch:daily_loss={loss_pct*100:.2f}%>={threshold*100:.1f}%"
            )
            return True
        return False

    def check_drawdown(
        self,
        equity_curve: Any = None,
        max_dd: float = None,
    ) -> "RiskCheckResult":
        """
        Validate that the current (or supplied) drawdown does not exceed max_dd.

        Parameters
        ----------
        equity_curve : optional list of equity values; if supplied, computes
                       drawdown from the curve rather than internal state
        max_dd       : maximum allowed drawdown fraction (default: config value)
        """
        limit = max_dd if max_dd is not None else self._config.max_drawdown_pct

        if equity_curve is not None and len(equity_curve) >= 2:
            arr = np.array(equity_curve, dtype=float)
            peak = np.maximum.accumulate(arr)
            dd_series = (peak - arr) / np.where(peak > 0, peak, 1.0)
            current_dd = float(dd_series[-1])
        else:
            current_dd = self._state.current_drawdown

        if current_dd > limit:
            return RiskCheckResult(
                passed=False,
                risk_level=RiskLevel.CRITICAL,
                message=(
                    f"Drawdown {current_dd*100:.2f}% exceeds limit {limit*100:.1f}%"
                ),
                value=current_dd,
                threshold=limit,
            )

        level = RiskLevel.LOW
        if current_dd > limit * 0.75:
            level = RiskLevel.HIGH
        elif current_dd > limit * 0.50:
            level = RiskLevel.MEDIUM

        return RiskCheckResult(
            passed=True,
            risk_level=level,
            message=f"Drawdown {current_dd*100:.2f}% within limit {limit*100:.1f}%",
            value=current_dd,
            threshold=limit,
        )

    def check_correlation_risk(
        self,
        positions: List[Any],
        max_correlation: float = 0.80,
    ) -> "RiskCheckResult":
        """
        Estimate portfolio correlation risk from position symbols.

        Uses a static correlation table for major FX pairs. Returns HIGH
        risk level when any pair exceeds max_correlation.

        Parameters
        ----------
        positions       : list of Position objects with .symbol attribute
        max_correlation : maximum allowed pairwise correlation
        """
        # Static correlation table for major FX pairs (approximate)
        _CORR: Dict[tuple, float] = {
            ("EURUSD", "GBPUSD"): 0.87,
            ("GBPUSD", "EURUSD"): 0.87,
            ("EURUSD", "AUDUSD"): 0.72,
            ("AUDUSD", "EURUSD"): 0.72,
            ("EURUSD", "NZDUSD"): 0.68,
            ("USDJPY", "USDCHF"): 0.75,
            ("USDCHF", "USDJPY"): 0.75,
            ("GBPUSD", "AUDUSD"): 0.65,
            ("XAUUSD", "AUDUSD"): 0.55,
        }

        symbols = [getattr(p, "symbol", "") for p in positions]
        max_found = 0.0
        worst_pair = ("", "")

        for i, s1 in enumerate(symbols):
            for j, s2 in enumerate(symbols):
                if i >= j:
                    continue
                corr = _CORR.get((s1, s2), _CORR.get((s2, s1), 0.0))
                if corr > max_found:
                    max_found = corr
                    worst_pair = (s1, s2)

        if max_found >= max_correlation:
            level = RiskLevel.HIGH
        elif max_found >= max_correlation * 0.75:
            level = RiskLevel.MEDIUM
        else:
            level = RiskLevel.LOW

        return RiskCheckResult(
            passed=max_found < max_correlation,
            risk_level=level,
            message=(
                f"Max correlation {max_found:.2f} between {worst_pair[0]}/{worst_pair[1]}"
                if worst_pair[0] else "No correlated pairs detected"
            ),
            value=max_found,
            threshold=max_correlation,
        )

    def check_concentration(
        self,
        positions: List[Any],
        account: Any,
        max_single: float = 0.40,
    ) -> "RiskCheckResult":
        """
        Validate that no single position exceeds max_single fraction of
        account balance.

        Parameters
        ----------
        positions  : list of Position objects with .market_value attribute
        account    : Account object with .balance attribute
        max_single : maximum allowed single-position concentration
        """
        try:
            balance = float(getattr(account, "balance", 0) or 0)
            if balance <= 0:
                return RiskCheckResult(passed=True, message="no_balance_data")

            worst_sym = ""
            worst_pct = 0.0
            for pos in positions:
                mv = float(getattr(pos, "market_value", 0) or 0)
                pct = mv / balance
                if pct > worst_pct:
                    worst_pct = pct
                    worst_sym = getattr(pos, "symbol", "?")

            if worst_pct > max_single:
                return RiskCheckResult(
                    passed=False,
                    risk_level=RiskLevel.HIGH,
                    message=(
                        f"Concentration risk: {worst_sym} is {worst_pct*100:.1f}% "
                        f"of account (limit {max_single*100:.1f}%)"
                    ),
                    value=worst_pct,
                    threshold=max_single,
                )

            return RiskCheckResult(
                passed=True,
                risk_level=RiskLevel.LOW,
                message=f"Max concentration {worst_pct*100:.1f}% within limit",
                value=worst_pct,
                threshold=max_single,
            )
        except Exception as exc:
            logger.debug("check_concentration error: %s", exc)
            return RiskCheckResult(passed=True, message="check_skipped")

    # ── Diagnostics ───────────────────────────────────────────────────────────

    # ── CVaR pre-trade gate ───────────────────────────────────────────────────

    def _compute_cvar(self, confidence: float = 0.95) -> float:
        """Compute Conditional Value-at-Risk (CVaR / Expected Shortfall).

        Returns the mean of the worst (1-confidence) fraction of returns as a
        positive number (i.e. the expected loss magnitude).
        """
        if len(self._returns_history) < 2:
            return 0.0
        arr = np.array(list(self._returns_history), dtype=float)
        cutoff = np.percentile(arr, (1.0 - confidence) * 100)
        tail = arr[arr <= cutoff]
        if len(tail) == 0:
            return 0.0
        return float(abs(np.mean(tail)))

    def check_cvar_pre_trade(self, confidence: float = 0.95) -> tuple:
        """Pre-trade CVaR gate.  Returns (allowed: bool, reason: str).

        Rules
        -----
        - If trading is halted, block immediately.
        - If _cvar_daily_limit == 0, gate is disabled → always pass.
        - Fewer than 10 observations → insufficient history → pass.
        - CVaR > _cvar_daily_limit → block.
        """
        # Check halt flag (supports both _halt and _trading_halted)
        if self._halt or getattr(self, "_trading_halted", False):
            reason = self._halt_reason or getattr(self, "_halt_reason", "halted")
            return (False, f"trading halted: {reason}")

        if self._cvar_daily_limit <= 0.0:
            return (True, "CVaR gate disabled")

        if len(self._returns_history) < 10:
            return (True, f"Insufficient history ({len(self._returns_history)} obs) for CVaR")

        cvar = self._compute_cvar(confidence=confidence)
        if cvar > self._cvar_daily_limit:
            return (
                False,
                f"Pre-trade CVaR check failed: CVaR={cvar:.4f} exceeds limit {self._cvar_daily_limit:.4f}",
            )
        return (True, f"CVaR={cvar:.4f} within limit {self._cvar_daily_limit:.4f}")

    def record_return(self, pnl: float, equity_at_entry: float) -> None:
        """Record a completed trade return for CVaR tracking."""
        if equity_at_entry > 0:
            self._returns_history.append(pnl / equity_at_entry)

    def check_risk_limits(self) -> tuple:
        """Check all active risk limits and return (passed: bool, reason: str).

        Evaluates drawdown, daily loss, open-position count, and kill-switch
        state.  Returns (True, "ok") when all limits are within bounds.
        """
        cfg = self._config
        state = self._state

        if self._halt:
            return (False, f"trading halted: {self._halt_reason}")

        if state.current_drawdown > cfg.max_drawdown_pct:
            return (
                False,
                f"drawdown {state.current_drawdown*100:.2f}% exceeds limit "
                f"{cfg.max_drawdown_pct*100:.1f}%",
            )

        daily_loss_pct = (
            abs(state.daily_pnl) / state.account_equity
            if state.account_equity > 0
            else 0.0
        )
        if state.daily_pnl < 0 and daily_loss_pct > cfg.daily_loss_limit_pct:
            return (
                False,
                f"daily loss {daily_loss_pct*100:.2f}% exceeds limit "
                f"{cfg.daily_loss_limit_pct*100:.1f}%",
            )

        max_pos = getattr(cfg, "max_open_positions", _MAX_OPEN_POSITIONS)
        if state.open_positions >= max_pos:
            return (
                False,
                f"open positions {state.open_positions} at limit {max_pos}",
            )

        return (True, "ok")

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
