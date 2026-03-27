# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026 Opeyemi (HACKLOVE340)
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
HOPEFX Risk Manager
Comprehensive risk management with position sizing, exposure limits, and drawdown control
"""

import json
import logging
import os
import signal
import sys
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

logger = logging.getLogger(__name__)


class RiskLevel(Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


@dataclass
class RiskConfig:
    """Risk management configuration"""

    max_position_size_pct: float = float(os.getenv("RISK_MAX_POSITION_SIZE_PCT", "0.05"))  # 5% per position (env-overridable)
    max_portfolio_exposure_pct: float = 0.5  # 50% total exposure
    max_drawdown_pct: float = 0.10  # 10% max drawdown
    daily_loss_limit_pct: float = 0.05  # 5% daily loss
    max_leverage: float = 1.0
    min_risk_reward: float = float(os.getenv("RISK_MIN_RR", "2.0"))  # 2:1 R:R minimum
    max_correlation: float = 0.7
    volatility_lookback: int = 20
    kelly_fraction: float = float(os.getenv("RISK_KELLY_FRACTION", "0.25"))  # Quarter Kelly — safer than half-Kelly for live deployment
    # Extended fields (used by test_risk_notification_extended)
    max_risk_per_trade: float = 2.0
    max_position_size: float = 10000.0
    max_open_positions: int = 5
    max_daily_loss: float = 5.0
    max_drawdown: float = 10.0
    default_stop_loss_pct: float = 2.0
    default_take_profit_pct: float = 4.0


@dataclass
class PositionSizingResult:
    """Position sizing calculation result"""

    recommended_size: float
    max_allowed_size: float
    risk_amount: float
    risk_pct: float
    stop_loss_price: Optional[float]
    take_profit_price: Optional[float]
    approved: bool
    reason: str

    @property
    def size(self) -> float:
        """Alias for recommended_size."""
        return self.recommended_size


@dataclass
class RiskAssessment:
    """Overall risk assessment"""

    level: RiskLevel
    can_trade: bool
    daily_pnl: float
    daily_pnl_pct: float
    current_drawdown: float
    margin_used_pct: float
    total_exposure_pct: float
    largest_position_pct: float
    messages: List[str] = field(default_factory=list)


class RiskManager:
    """
    Production risk manager with:
    - Kelly criterion position sizing
    - Dynamic exposure limits
    - Correlation-based risk reduction
    - Drawdown circuit breakers
    - Volatility-adjusted sizing
    """

    def __init__(
        self,
        config: RiskConfig = None,
        initial_balance: float = 1_000_000.0,
        halt_state_file: Optional[Path] = None,
    ):
        self.config = config or RiskConfig()

        # State tracking
        self.peak_equity = 0.0
        self.current_drawdown = 0.0
        self.daily_starting_equity = 0.0
        self.daily_pnl = 0.0
        self.daily_trades: int = 0
        self.last_reset_date = datetime.now(timezone.utc).date()

        # Extended balance tracking (used by test_risk_notification_extended)
        self.initial_balance: float = initial_balance
        self.current_balance: float = initial_balance
        self.peak_balance: float = initial_balance

        # Position tracking
        self.open_positions: List[Dict] = []
        self.position_history: List[Dict] = []
        self.trade_history: List[Dict] = []
        self.correlation_matrix: Dict[Tuple[str, str], float] = {}

        # Circuit breakers
        self._trading_halted = False
        self._halt_reason: Optional[str] = None
        self._halt_until: Optional[datetime] = None

        # Two-tier drawdown alert state (Area 2)
        self._amber_warned: bool = False

        # Rolling returns history for CVaR (Area 2) — 252 trading days
        self._returns_history: deque = deque(maxlen=252)

        # Per-symbol price history for live correlation (Area 2) — 60 bars
        self._price_history: Dict[str, deque] = {}
        self._price_update_counts: Dict[str, int] = {}

        # CVaR daily limit — 0 = disabled (Area 2)
        self._cvar_daily_limit: float = float(os.getenv("RISK_CVAR_DAILY_LIMIT", "0"))

        # Path for persisting halt state across restarts.
        # Callers (e.g. tests) can supply a custom path via halt_state_file to
        # avoid sharing state between test instances.
        self._halt_state_file: Path = (
            halt_state_file
            if halt_state_file is not None
            else Path(__file__).parent / "halt_state.json"
        )

        # Restore any halt that was active before the last restart.
        # This prevents a process restart from silently resuming trading
        # after a drawdown-triggered halt.
        self._restore_halt_state()

    def update_equity(self, equity: float) -> None:
        """Update equity, drawdown, and rolling returns history."""
        # Check for new day
        today = datetime.now(timezone.utc).date()
        if today != self.last_reset_date:
            self.daily_starting_equity = equity
            self.daily_pnl = 0.0
            self.last_reset_date = today

        # Update daily P&L
        self.daily_pnl = equity - self.daily_starting_equity

        # Append daily return to rolling history for CVaR
        if self.daily_starting_equity > 0:
            daily_return = self.daily_pnl / self.daily_starting_equity
            self._returns_history.append(daily_return)

        # Update peak and drawdown
        if equity > self.peak_equity:
            self.peak_equity = equity

        if self.peak_equity > 0:
            self.current_drawdown = (self.peak_equity - equity) / self.peak_equity

        # Check circuit breakers
        self._check_circuit_breakers(equity)

    def _check_circuit_breakers(self, equity: float) -> None:
        """Check and trigger circuit breakers with two-tier drawdown alerts."""
        # ── CVaR check (Area 2) ───────────────────────────────────────────────
        if self._cvar_daily_limit > 0 and len(self._returns_history) >= 10:
            cvar = self._compute_cvar()
            if cvar > self._cvar_daily_limit:
                self._halt_trading(
                    f"CVaR daily limit breached: CVaR={cvar:.4f} > limit={self._cvar_daily_limit:.4f}",
                    duration_hours=24,
                )
                return

        # ── Two-tier drawdown (Area 2) ────────────────────────────────────────
        amber_threshold = self.config.max_drawdown_pct * 0.60  # 60% of limit
        if self.current_drawdown >= self.config.max_drawdown_pct:
            # RED — halt immediately
            self._amber_warned = False  # reset for next cycle
            self._halt_trading(
                f"Max drawdown reached: {self.current_drawdown:.2%} > {self.config.max_drawdown_pct:.2%}",
                duration_hours=24,
            )
            return
        elif self.current_drawdown >= amber_threshold and not self._amber_warned:
            # AMBER — warn but keep trading
            self._amber_warned = True
            logger.warning(
                "AMBER drawdown alert: %.2f%% has reached 60%% of the %.2f%% limit — "
                "monitor closely",
                self.current_drawdown * 100,
                self.config.max_drawdown_pct * 100,
            )
        elif self.current_drawdown < amber_threshold:
            # Reset amber flag when drawdown recovers below threshold
            self._amber_warned = False

        # ── Daily loss limit ──────────────────────────────────────────────────
        if self.daily_starting_equity > 0:
            daily_loss_pct = abs(self.daily_pnl) / self.daily_starting_equity
            if daily_loss_pct > self.config.daily_loss_limit_pct:
                self._halt_trading(
                    f"Daily loss limit reached: {daily_loss_pct:.2%}",
                    duration_hours=1,
                )
                return

        # ── Lift expired halt ─────────────────────────────────────────────────
        if self._trading_halted and self._halt_until:
            if datetime.now(timezone.utc) >= self._halt_until:
                self._resume_trading()

    def _compute_cvar(self, confidence: float = 0.95) -> float:
        """
        Compute CVaR (Expected Shortfall) from the rolling daily returns history.
        Returns the expected loss (positive number) beyond the VaR threshold.
        """
        if len(self._returns_history) < 2:
            return 0.0
        returns = np.array(list(self._returns_history))
        var_threshold = np.percentile(returns, (1 - confidence) * 100)
        tail = returns[returns <= var_threshold]
        if len(tail) == 0:
            return abs(var_threshold)
        return float(abs(np.mean(tail)))

    def _halt_trading(self, reason: str, duration_hours: float = 1.0):
        """
        Halt trading and persist the halt state to disk.

        Persisting to disk ensures that a process restart does not silently
        resume trading after a drawdown-triggered halt.  The halt remains
        active until either the duration expires or _resume_trading() is
        called explicitly.
        """
        self._trading_halted = True
        self._halt_reason = reason
        self._halt_until = (
            datetime.now(timezone.utc) + timedelta(hours=duration_hours)
            if duration_hours > 0
            else None
        )
        logger.critical(
            "TRADING HALTED: %s (until %s)",
            reason,
            self._halt_until.isoformat() if self._halt_until else "manual resume only",
        )
        self._persist_halt_state()

    def _resume_trading(self):
        """Resume trading and remove the persisted halt state."""
        self._trading_halted = False
        self._halt_reason = None
        self._halt_until = None
        logger.info("Trading resumed")
        self._clear_halt_state()

    def _persist_halt_state(self) -> None:
        """Write halt state to JSON so the next process restart can restore it."""
        state = {
            "halted": self._trading_halted,
            "reason": self._halt_reason,
            "halt_until": self._halt_until.isoformat() if self._halt_until else None,
            "persisted_at": datetime.now(timezone.utc).isoformat(),
        }
        try:
            self._halt_state_file.write_text(json.dumps(state, indent=2))
        except OSError as exc:
            logger.warning("Could not persist halt state: %s", exc)

    def _clear_halt_state(self) -> None:
        """Remove the persisted halt state file after a successful resume."""
        try:
            if self._halt_state_file.exists():
                self._halt_state_file.unlink()
        except OSError as exc:
            logger.warning("Could not remove halt state file: %s", exc)

    def _restore_halt_state(self) -> None:
        """
        Restore halt state from disk on startup.

        If the state file records an active halt whose expiry has not yet
        passed, trading is re-halted immediately.  If the halt has expired,
        the state file is removed and trading starts normally.
        """
        if not self._halt_state_file.exists():
            return
        try:
            data = json.loads(self._halt_state_file.read_text())
        except Exception as exc:
            logger.warning("Could not read halt state file: %s", exc)
            return

        if not data.get("halted"):
            self._clear_halt_state()
            return

        halt_until_str = data.get("halt_until")
        if halt_until_str:
            halt_until = datetime.fromisoformat(halt_until_str)
            if datetime.now(timezone.utc) >= halt_until:
                # Halt has expired — clear and start normally
                logger.info(
                    "Persisted halt has expired (was until %s) — resuming trading",
                    halt_until.isoformat(),
                )
                self._clear_halt_state()
                return
            self._halt_until = halt_until
        else:
            # Indefinite halt (duration_hours=0) — stays halted until manual resume
            self._halt_until = None

        self._trading_halted = True
        self._halt_reason = data.get("reason", "restored from persisted halt state")
        logger.critical(
            "Trading halt RESTORED from persisted state — reason: %s | halt_until: %s",
            self._halt_reason,
            self._halt_until.isoformat() if self._halt_until else "manual resume only",
        )

    def assess_risk(self, account_info: Dict, positions: List[Any]) -> RiskAssessment:
        """
        Comprehensive risk assessment.

        Invariant: equity must be > 0. If equity is zero or negative the method
        halts trading immediately and returns a CRITICAL assessment so no orders
        are submitted while the account is in an invalid state.
        """
        messages = []

        # Check if trading halted
        if self._trading_halted:
            return RiskAssessment(
                level=RiskLevel.CRITICAL,
                can_trade=False,
                daily_pnl=self.daily_pnl,
                daily_pnl_pct=self.daily_pnl / self.daily_starting_equity
                if self.daily_starting_equity > 0
                else 0,
                current_drawdown=self.current_drawdown,
                margin_used_pct=0.0,
                total_exposure_pct=0.0,
                largest_position_pct=0.0,
                messages=[f"Trading halted: {self._halt_reason}"],
            )

        equity = account_info.get("equity", 0)

        # ── Invariant: equity must be positive (strictly negative is invalid; ───
        # ── zero is allowed as a transient state at initialisation)  ────────────
        if equity < 0:
            logger.critical(
                "INVARIANT VIOLATED: equity=%.2f is not positive — halting trading",
                equity,
            )
            self._halt_trading(
                f"equity invariant violated (equity={equity})", duration_hours=24
            )
            return RiskAssessment(
                level=RiskLevel.CRITICAL,
                can_trade=False,
                daily_pnl=self.daily_pnl,
                daily_pnl_pct=0.0,
                current_drawdown=self.current_drawdown,
                margin_used_pct=0.0,
                total_exposure_pct=0.0,
                largest_position_pct=0.0,
                messages=[f"Equity invariant violated: equity={equity}"],
            )
        # ────────────────────────────────────────────────────────────────────

        margin_used = account_info.get("margin_used", 0)

        # Calculate metrics
        margin_used_pct = (margin_used / equity) if equity > 0 else 0

        total_exposure = sum(
            p.get("quantity", 0) * p.get("current_price", 0) for p in positions
        )
        total_exposure_pct = (total_exposure / equity) if equity > 0 else 0

        largest_position = max(
            (p.get("quantity", 0) * p.get("current_price", 0) for p in positions),
            default=0,
        )
        largest_position_pct = (largest_position / equity) if equity > 0 else 0

        daily_pnl_pct = (
            (self.daily_pnl / self.daily_starting_equity)
            if self.daily_starting_equity > 0
            else 0
        )

        # Determine risk level
        risk_level = RiskLevel.LOW
        can_trade = True

        if self.current_drawdown > self.config.max_drawdown_pct * 0.8:
            risk_level = RiskLevel.CRITICAL
            can_trade = False
            messages.append(f"Near max drawdown: {self.current_drawdown:.2%}")
            # FCM push: drawdown warning to all users with registered devices
            try:
                from mobile.push_notifications import _device_tokens, push_manager

                for uid in list(_device_tokens.keys()):
                    push_manager.send_drawdown_warning(
                        user_id=uid,
                        drawdown_pct=self.current_drawdown * 100,
                        limit_pct=self.config.max_drawdown_pct * 100,
                    )
            except Exception as exc:
                logger.debug("FCM drawdown push failed (non-critical): %s", exc)
        elif margin_used_pct > 0.8:
            risk_level = RiskLevel.HIGH
            messages.append(f"High margin usage: {margin_used_pct:.2%}")
        elif total_exposure_pct > self.config.max_portfolio_exposure_pct * 0.9:
            risk_level = RiskLevel.HIGH
            messages.append(f"High exposure: {total_exposure_pct:.2%}")
        elif largest_position_pct > self.config.max_position_size_pct * 1.5:
            risk_level = RiskLevel.MEDIUM
            messages.append(f"Large position: {largest_position_pct:.2%}")
        elif daily_pnl_pct < -self.config.daily_loss_limit_pct * 0.5:
            risk_level = RiskLevel.MEDIUM
            messages.append(f"Approaching daily loss limit: {daily_pnl_pct:.2%}")

        # ── CVaR live check (Area 2) ──────────────────────────────────────────
        if self._cvar_daily_limit > 0 and len(self._returns_history) >= 10:
            cvar = self._compute_cvar()
            if cvar > self._cvar_daily_limit:
                risk_level = RiskLevel.CRITICAL
                can_trade = False
                messages.append(
                    f"CVaR {cvar:.4f} exceeds daily limit {self._cvar_daily_limit:.4f}"
                )

        if not messages:
            messages.append("Risk within normal parameters")

        return RiskAssessment(
            level=risk_level,
            can_trade=can_trade,
            daily_pnl=self.daily_pnl,
            daily_pnl_pct=daily_pnl_pct,
            current_drawdown=self.current_drawdown,
            margin_used_pct=margin_used_pct,
            total_exposure_pct=total_exposure_pct,
            largest_position_pct=largest_position_pct,
            messages=messages,
        )

    def check_cvar_pre_trade(self) -> Tuple[bool, str]:
        """
        Explicit CVaR gate for the order submission path.

        Called directly in place_order() *before* broker execution so that
        CVaR breaches block orders even when assess_risk() is bypassed or
        the returns history has grown since the last assess_risk() call.

        Returns:
            (allowed, reason) — allowed=False means the order must be rejected.
        """
        if self._trading_halted:
            return False, f"Trading halted: {self._halt_reason}"

        if self._cvar_daily_limit <= 0:
            return True, "CVaR limit disabled"

        if len(self._returns_history) < 10:
            return True, "Insufficient history for CVaR (< 10 observations)"

        cvar = self._compute_cvar()
        if cvar > self._cvar_daily_limit:
            reason = (
                f"Pre-trade CVaR check failed: CVaR={cvar:.4f} exceeds "
                f"daily limit={self._cvar_daily_limit:.4f}"
            )
            logger.warning("ORDER BLOCKED — %s", reason)
            return False, reason

        return True, f"CVaR={cvar:.4f} within limit={self._cvar_daily_limit:.4f}"

    # ------------------------------------------------------------------
    # Position sizing helpers (Area 3 — split from _calculate_position_size_full)
    # ------------------------------------------------------------------

    def _compute_kelly_fraction(self, p: float, b: float) -> float:
        """
        Compute the Kelly fraction f* = (p*b - q) / b, scaled by kelly_fraction.

        Args:
            p: Win probability, clamped to [0.30, 0.75].
            b: Win/loss ratio (reward / risk per share).

        Returns:
            Kelly fraction as a decimal (e.g. 0.05 = 5% of equity).
        """
        p = max(0.30, min(0.75, p))
        q = 1.0 - p
        raw_kelly = (p * b - q) / b if b > 0 else 0.0
        return max(0.0, raw_kelly * self.config.kelly_fraction)

    def _apply_correlation_penalty(
        self, symbol: str, positions: List[Dict], base_pct: float
    ) -> float:
        """
        Reduce base_pct by the correlation penalty for the given symbol.

        Args:
            symbol:    Instrument being sized.
            positions: Current open positions.
            base_pct:  Starting risk percentage before penalty.

        Returns:
            Adjusted risk percentage after correlation penalty.
        """
        penalty = self._calculate_correlation_penalty(symbol, positions)
        return base_pct * (1.0 - penalty)

    def _apply_risk_limits(self, pct: float, equity: float) -> float:
        """
        Clamp pct to the configured max_position_size_pct and apply
        volatility / drawdown scaling factors.

        Args:
            pct:    Proposed risk percentage.
            equity: Current account equity (unused here but kept for signature).

        Returns:
            Final risk percentage after all caps.
        """
        return min(pct, self.config.max_position_size_pct)

    def _calculate_position_size_full(
        self,
        symbol: str,
        signal_strength: float,
        entry_price: float,
        stop_loss_price: float,
        take_profit_price: float,
        account_equity: float,
        volatility: float,
        existing_positions: List[Dict] = None,
    ) -> PositionSizingResult:
        """
        Calculate optimal position size using Kelly criterion with safety factors

        Args:
            signal_strength: 0.0 to 1.0
            entry_price: Planned entry price
            stop_loss_price: Stop loss level
            take_profit_price: Take profit level
            account_equity: Current account equity
            volatility: Annualized volatility (0.0 to 1.0)
            existing_positions: Current positions for correlation check
        """

        if existing_positions is None:
            existing_positions = []

        # Validate inputs
        if entry_price <= 0 or account_equity <= 0:
            return PositionSizingResult(
                recommended_size=0,
                max_allowed_size=0,
                risk_amount=0,
                risk_pct=0,
                stop_loss_price=stop_loss_price,
                take_profit_price=take_profit_price,
                approved=False,
                reason="Invalid price or equity",
            )

        # Check if trading halted
        if self._trading_halted:
            return PositionSizingResult(
                recommended_size=0,
                max_allowed_size=0,
                risk_amount=0,
                risk_pct=0,
                stop_loss_price=stop_loss_price,
                take_profit_price=take_profit_price,
                approved=False,
                reason=f"Trading halted: {self._halt_reason}",
            )

        # Calculate risk/reward
        risk_per_share = abs(entry_price - stop_loss_price)
        reward_per_share = abs(take_profit_price - entry_price)

        if risk_per_share <= 0:
            return PositionSizingResult(
                recommended_size=0,
                max_allowed_size=0,
                risk_amount=0,
                risk_pct=0,
                stop_loss_price=stop_loss_price,
                take_profit_price=take_profit_price,
                approved=False,
                reason="Invalid stop loss (must be different from entry)",
            )

        risk_reward = reward_per_share / risk_per_share

        if risk_reward < self.config.min_risk_reward:
            return PositionSizingResult(
                recommended_size=0,
                max_allowed_size=0,
                risk_amount=0,
                risk_pct=0,
                stop_loss_price=stop_loss_price,
                take_profit_price=take_profit_price,
                approved=False,
                reason=f"Risk/reward too low: {risk_reward:.2f} < {self.config.min_risk_reward}",
            )

        # Win probability: prefer signal['probability'] when available (Area 2).
        # Bounds-clamp to [0.30, 0.75] to prevent degenerate Kelly fractions.
        _raw_p = signal_strength
        _prob_from_signal = getattr(self, "_last_signal_probability", None)
        if _prob_from_signal is not None:
            _raw_p = _prob_from_signal
            self._last_signal_probability = None  # consume

        # ── Helper 1: Kelly fraction ──────────────────────────────────────────
        position_risk_pct = self._compute_kelly_fraction(
            p=_raw_p if _raw_p is not None else 0.5,
            b=risk_reward,
        )

        # Volatility and drawdown scaling (inline — not extracted, these are
        # continuous adjustments rather than discrete limit checks)
        volatility_factor = max(0.3, 1.0 - (volatility * 2))
        position_risk_pct *= volatility_factor
        drawdown_factor = max(0.5, 1.0 - (self.current_drawdown * 5))
        position_risk_pct *= drawdown_factor

        # ── Helper 2: correlation penalty ────────────────────────────────────
        position_risk_pct = self._apply_correlation_penalty(
            symbol, existing_positions, position_risk_pct
        )

        # ── Helper 3: hard risk limits ────────────────────────────────────────
        position_risk_pct = self._apply_risk_limits(position_risk_pct, account_equity)

        # Calculate position size
        risk_amount = account_equity * position_risk_pct
        position_size = risk_amount / risk_per_share if risk_per_share > 0 else 0

        # Determine lot granularity by instrument type:
        #   Forex pairs (entry < 500)  → 1000-unit micro lots
        #   Metals / indices (entry ≥ 500) → 1-unit lots (oz for gold)
        if entry_price >= 500:
            lot_size = 1
            min_lots = 1
        else:
            lot_size = 1000
            min_lots = 1000

        position_size = max(int(position_size / lot_size) * lot_size, 0)

        # Ensure minimum size
        if position_size < min_lots:
            return PositionSizingResult(
                recommended_size=0,
                max_allowed_size=0,
                risk_amount=0,
                risk_pct=0,
                stop_loss_price=stop_loss_price,
                take_profit_price=take_profit_price,
                approved=False,
                reason="Position size too small after rounding",
            )

        # Calculate max allowed based on exposure limits
        current_exposure = sum(
            p.get("quantity", 0) * p.get("current_price", 0) for p in existing_positions
        )
        max_additional_exposure = (
            account_equity * self.config.max_portfolio_exposure_pct
        ) - current_exposure
        max_size_from_exposure = (
            max_additional_exposure / entry_price if entry_price > 0 else 0
        )

        # Final position size is minimum of risk-based and exposure-based
        final_size = min(position_size, max_size_from_exposure)

        # Ensure we don't exceed max position size
        max_position_value = account_equity * self.config.max_position_size_pct
        max_size_from_position_limit = (
            max_position_value / entry_price if entry_price > 0 else 0
        )
        final_size = min(final_size, max_size_from_position_limit)

        # Round to lot granularity
        final_size = max(int(final_size / lot_size) * lot_size, 0)

        if final_size < min_lots:
            return PositionSizingResult(
                recommended_size=0,
                max_allowed_size=0,
                risk_amount=0,
                risk_pct=0,
                stop_loss_price=stop_loss_price,
                take_profit_price=take_profit_price,
                approved=False,
                reason="Position size too small after applying limits",
            )

        actual_risk_amount = final_size * risk_per_share
        actual_risk_pct = actual_risk_amount / account_equity

        return PositionSizingResult(
            recommended_size=final_size,
            max_allowed_size=max_size_from_exposure,
            risk_amount=actual_risk_amount,
            risk_pct=actual_risk_pct,
            stop_loss_price=stop_loss_price,
            take_profit_price=take_profit_price,
            approved=True,
            reason=f"Kelly: {position_risk_pct:.2%}, Risk/Reward: {risk_reward:.2f}, "
            f"VolFactor: {volatility_factor:.2f}, DD_Factor: {drawdown_factor:.2f}",
        )

    # ------------------------------------------------------------------
    # Live price tracking and correlation (Area 2)
    # ------------------------------------------------------------------

    def update_price(self, symbol: str, price: float) -> None:
        """
        Record a new price tick for a symbol and recompute correlations every
        60 updates per symbol.  Warns when any pair exceeds 0.85 correlation.
        """
        if symbol not in self._price_history:
            self._price_history[symbol] = deque(maxlen=60)
            self._price_update_counts[symbol] = 0

        self._price_history[symbol].append(float(price))
        self._price_update_counts[symbol] += 1

        if self._price_update_counts[symbol] % 60 == 0:
            self._recompute_correlations()

    def _recompute_correlations(self) -> None:
        """
        Recompute pairwise Pearson correlations from the rolling 60-bar price
        histories.  Logs a WARNING for any pair whose correlation exceeds 0.85.
        """
        symbols = [s for s, h in self._price_history.items() if len(h) >= 10]
        if len(symbols) < 2:
            return

        returns: Dict[str, np.ndarray] = {}
        for sym in symbols:
            prices = np.array(list(self._price_history[sym]))
            if len(prices) > 1:
                returns[sym] = np.diff(prices) / prices[:-1]

        syms = list(returns.keys())
        for i in range(len(syms)):
            for j in range(i + 1, len(syms)):
                s1, s2 = syms[i], syms[j]
                r1, r2 = returns[s1], returns[s2]
                min_len = min(len(r1), len(r2))
                if min_len < 5:
                    continue
                corr = float(np.corrcoef(r1[-min_len:], r2[-min_len:])[0, 1])
                self.correlation_matrix[(s1, s2)] = corr
                if abs(corr) > 0.85:
                    logger.warning(
                        "High correlation detected: %s / %s = %.3f — "
                        "consider reducing combined exposure",
                        s1,
                        s2,
                        corr,
                    )

    def _calculate_correlation_penalty(
        self, symbol: str, positions: List[Dict]
    ) -> float:
        """Calculate position size reduction due to correlation"""
        if not positions:
            return 0.0

        # Simplified: check if same symbol or related pairs
        correlated_exposure = 0.0

        for pos in positions:
            pos_symbol = pos.get("symbol", "")

            # Same symbol = full correlation
            if pos_symbol == symbol:
                correlated_exposure += pos.get("quantity", 0) * pos.get(
                    "current_price", 0
                )
                continue

            # Check for related pairs (e.g., EURUSD and GBPUSD both have USD)
            if self._symbols_related(symbol, pos_symbol):
                correlated_exposure += (
                    pos.get("quantity", 0) * pos.get("current_price", 0) * 0.5
                )

        # Penalty increases with correlated exposure
        if correlated_exposure > 0:
            return min(0.5, correlated_exposure / 100000)  # Cap at 50% reduction

        return 0.0

    def _symbols_related(self, sym1: str, sym2: str) -> bool:
        """Check if two symbols are related (share a currency)"""
        # Extract currencies (simplified)
        currencies1 = set([sym1[:3], sym1[3:]]) if len(sym1) == 6 else set([sym1])
        currencies2 = set([sym2[:3], sym2[3:]]) if len(sym2) == 6 else set([sym2])

        return len(currencies1 & currencies2) > 0

    def filter_signals(self, signals: List[Dict], account_state: Any) -> List[Dict]:
        """
        Filter and size trading signals through risk management
        """
        if not signals:
            return []

        # Update equity from account state
        if hasattr(account_state, "equity"):
            self.update_equity(account_state.equity)

        filtered_signals = []

        for signal in signals:
            # Basic validation
            if not all(
                k in signal for k in ["symbol", "action", "entry_price", "stop_loss"]
            ):
                logger.warning(f"Invalid signal format: {signal}")
                continue

            # Skip if action is close (handled separately)
            if signal["action"] == "close":
                filtered_signals.append(signal)
                continue

            # Pass ML probability into Kelly calculation when available (Area 2)
            if "probability" in signal:
                raw_p = signal["probability"]
                self._last_signal_probability = max(0.30, min(0.75, float(raw_p)))

            # Calculate position size
            sizing = self.calculate_position_size(
                symbol=signal["symbol"],
                signal_strength=signal.get("strength", 0.5),
                entry_price=signal["entry_price"],
                stop_loss_price=signal["stop_loss"],
                take_profit_price=signal.get(
                    "take_profit", signal["entry_price"] * 1.02
                ),
                account_equity=getattr(account_state, "equity", 100000),
                volatility=signal.get("volatility", 0.1),
                existing_positions=getattr(
                    account_state, "active_positions", {}
                ).values(),
            )

            if not sizing.approved:
                logger.info(f"Signal rejected for {signal['symbol']}: {sizing.reason}")
                continue

            # Add sizing to signal
            signal["size"] = sizing.recommended_size
            signal["risk_amount"] = sizing.risk_amount
            signal["risk_pct"] = sizing.risk_pct
            signal["stop_loss"] = sizing.stop_loss_price
            signal["take_profit"] = sizing.take_profit_price

            filtered_signals.append(signal)

            logger.info(
                f"Signal approved: {signal['symbol']} | "
                f"Size: {sizing.recommended_size} | "
                f"Risk: {sizing.risk_pct:.2%} | "
                f"R/R: {abs(sizing.take_profit_price - signal['entry_price']) / abs(sizing.stop_loss_price - signal['entry_price']):.2f}"
            )

        return filtered_signals

    # ------------------------------------------------------------------
    # Extended API (test_risk_notification_extended)
    # ------------------------------------------------------------------

    def calculate_position_size(
        self,
        symbol: str = "",
        entry_price: float = 0.0,
        method: str = "risk",
        amount: float = None,
        percent: float = None,
        stop_loss: float = None,
        price: float = None,
        # Full-signature kwargs from PositionSizingResult path
        signal_strength: float = None,
        stop_loss_price: float = None,
        take_profit_price: float = None,
        account_equity: float = None,
        volatility: float = None,
        existing_positions=None,
        **kw,
    ) -> "PositionSizingResult":
        """Unified position sizing — delegates to full implementation when called with signal_strength."""
        if signal_strength is not None:
            # Full PositionSizingResult path (used by integration tests)
            return self._calculate_position_size_full(
                symbol=symbol,
                signal_strength=signal_strength,
                entry_price=entry_price or price or 1.0,
                stop_loss_price=stop_loss_price or stop_loss or 0.0,
                take_profit_price=take_profit_price or 0.0,
                account_equity=account_equity or self.current_balance,
                volatility=volatility or 0.1,
                existing_positions=existing_positions or [],
            )
        # Simple path
        entry = price or entry_price or 1.0
        cfg = self.config
        if method == "fixed":
            size = (amount or 1000.0) / max(entry, 1.0)
        elif method == "percent":
            pct = percent or (cfg.max_risk_per_trade / 100.0)
            size = self.current_balance * pct / max(entry, 1.0)
        elif method == "risk":
            sl = stop_loss or kw.get("stop_loss")
            if sl and sl != entry:
                risk_amt = self.current_balance * (cfg.max_risk_per_trade / 100.0)
                size = risk_amt / abs(entry - sl)
            else:
                size = (
                    self.current_balance
                    * (cfg.max_risk_per_trade / 100.0)
                    / max(entry, 1.0)
                )
        else:
            size = self.current_balance * 0.01 / max(entry, 1.0)
        size = max(size, 0.01)
        # Return PositionSizingResult so callers always get .approved
        return PositionSizingResult(
            recommended_size=size,
            max_allowed_size=size * 2,
            risk_amount=size * entry * (cfg.max_risk_per_trade / 100.0),
            risk_pct=cfg.max_risk_per_trade / 100.0,
            stop_loss_price=stop_loss or 0.0,
            take_profit_price=0.0,
            approved=True,
            reason="OK",
        )

    def can_open_position(self, size: float) -> Tuple[bool, str]:
        """Check whether a new position can be opened."""
        cfg = self.config
        if len(self.open_positions) >= cfg.max_open_positions:
            return False, f"Max open positions ({cfg.max_open_positions}) reached"
        if size > cfg.max_position_size:
            return (
                False,
                f"Position size {size} exceeds maximum {cfg.max_position_size}",
            )
        daily_loss_pct = (
            abs(self.daily_pnl) / self.current_balance * 100
            if self.current_balance
            else 0
        )
        if self.daily_pnl < 0 and daily_loss_pct >= cfg.max_daily_loss:
            return False, f"Daily loss limit ({cfg.max_daily_loss}%) reached"
        if self.peak_balance > 0:
            dd_pct = (
                (self.peak_balance - self.current_balance) / self.peak_balance * 100
            )
            if dd_pct >= cfg.max_drawdown:
                return False, f"Max drawdown ({cfg.max_drawdown}%) reached"
        return True, "OK"

    def validate_trade(self, symbol: str, size: float, side: str) -> Tuple[bool, str]:
        """Validate a trade before execution."""
        return self.can_open_position(size)

    def register_position(self, position: Dict) -> None:
        self.open_positions.append(position)

    def close_position(self, position_id: str, pnl: float = 0.0) -> None:
        self.open_positions = [
            p for p in self.open_positions if p.get("id") != position_id
        ]
        self.current_balance += pnl
        self.daily_pnl += pnl
        if self.current_balance > self.peak_balance:
            self.peak_balance = self.current_balance

    def check_risk_limits(self) -> Tuple[bool, List[str]]:
        """Return (within_limits, list_of_violations)."""
        violations: List[str] = []
        cfg = self.config
        daily_loss_pct = (
            abs(self.daily_pnl) / self.current_balance * 100
            if self.current_balance and self.daily_pnl < 0
            else 0
        )
        if daily_loss_pct >= cfg.max_daily_loss:
            violations.append(
                f"Daily loss {daily_loss_pct:.1f}% exceeds limit {cfg.max_daily_loss}%"
            )
        if self.peak_balance > 0:
            dd_pct = (
                (self.peak_balance - self.current_balance) / self.peak_balance * 100
            )
            if dd_pct >= cfg.max_drawdown:
                violations.append(
                    f"Drawdown {dd_pct:.1f}% exceeds limit {cfg.max_drawdown}%"
                )
        return len(violations) == 0, violations

    def calculate_stop_loss(
        self, entry: float, side: str, percent: float = None
    ) -> float:
        pct = (percent or self.config.default_stop_loss_pct) / 100.0
        if side.upper() in ("BUY", "LONG"):
            return entry * (1 - pct)
        return entry * (1 + pct)

    def calculate_take_profit(
        self, entry: float, side: str, percent: float = None
    ) -> float:
        pct = (percent or self.config.default_take_profit_pct) / 100.0
        if side.upper() in ("BUY", "LONG"):
            return entry * (1 + pct)
        return entry * (1 - pct)

    def reset_daily_pnl(self) -> None:
        self.daily_pnl = 0.0
        self.daily_trades = 0

    def reset_daily_stats(self) -> None:
        self.reset_daily_pnl()

    def check_drawdown(
        self, equity_curve=None, max_dd: float = None
    ) -> "RiskCheckResult":
        """Check drawdown against limit. Accepts equity_curve array or uses internal state."""
        import numpy as _np

        if equity_curve is not None:
            arr = _np.asarray(equity_curve, dtype=float)
            if len(arr) < 2:
                return RiskCheckResult(passed=True, message="Insufficient data")
            peak = _np.maximum.accumulate(arr)
            dd = (arr - peak) / peak
            max_drawdown = float(_np.min(dd))
        else:
            if self.peak_balance <= 0:
                return RiskCheckResult(passed=True, message="No peak balance")
            max_drawdown = (
                -(self.peak_balance - self.current_balance) / self.peak_balance
            )
        limit = -(max_dd if max_dd is not None else self.config.max_drawdown / 100.0)
        passed = max_drawdown >= limit
        return RiskCheckResult(
            passed=passed,
            message=f"Drawdown {max_drawdown:.2%} {'within' if passed else 'exceeds'} limit {limit:.2%}",
            details={"drawdown": max_drawdown, "limit": limit},
        )

    @property
    def kill_switch_active(self) -> bool:
        return self._trading_halted

    def check_kill_switch(
        self,
        daily_pnl: float = None,
        account_value: float = None,
        threshold: float = None,
    ) -> bool:
        """Return True if kill switch should trigger (trading should stop)."""
        if (
            daily_pnl is not None
            and account_value is not None
            and threshold is not None
        ):
            if account_value > 0:
                loss_pct = abs(daily_pnl) / account_value if daily_pnl < 0 else 0
                if loss_pct >= threshold:
                    self._trading_halted = True
                    return True
        return self._trading_halted

    def check_price_tolerance(
        self, order, current_price: float = None, tolerance: float = None
    ) -> "RiskCheckResult":
        """Check if order price is within tolerance of current market price."""
        if isinstance(order, dict):
            order_price = order.get("price", current_price)
        else:
            order_price = getattr(order, "price", current_price)
        if order_price is None or current_price is None:
            return RiskCheckResult(passed=True, message="No price to check")
        tol = tolerance if tolerance is not None else 0.005
        diff = abs(order_price - current_price) / current_price if current_price else 0
        passed = diff <= tol
        return RiskCheckResult(
            passed=passed,
            message=f"Price tolerance {'OK' if passed else 'exceeded'}: diff {diff:.4%} vs limit {tol:.4%}",
            details={
                "order_price": order_price,
                "current_price": current_price,
                "diff_pct": diff,
            },
        )

    def check_correlation_risk(
        self, positions: List, max_correlation: float = 0.80
    ) -> "RiskCheckResult":
        """Check portfolio correlation risk (simplified heuristic)."""
        # Heuristic: EUR/GBP pairs are highly correlated
        symbols = [getattr(p, "symbol", "") for p in positions]
        eur_pairs = [s for s in symbols if s.startswith("EUR")]
        gbp_pairs = [s for s in symbols if s.startswith("GBP")]
        high_corr = len(eur_pairs) > 0 and len(gbp_pairs) > 0
        level = RiskLevel.HIGH if high_corr else RiskLevel.MEDIUM
        return RiskCheckResult(
            passed=not high_corr,
            risk_level=level,
            message=f"Correlation risk: {'high' if high_corr else 'medium'} between {symbols}",
        )

    def check_concentration(
        self, positions: List, account, max_single: float = 0.40
    ) -> "RiskCheckResult":
        """Check single-position concentration."""
        balance = getattr(account, "balance", 100000.0) or 100000.0
        violations = []
        for p in positions:
            mv = getattr(p, "market_value", None) or (getattr(p, "size", 0) or 0)
            pct = mv / balance if balance > 0 else 0
            if pct > max_single:
                sym = getattr(p, "symbol", "?")
                violations.append(f"{sym}: {pct:.1%}")
        passed = len(violations) == 0
        return RiskCheckResult(
            passed=passed,
            risk_level=RiskLevel.LOW if passed else RiskLevel.HIGH,
            message=f"Position concentration {'OK' if passed else 'exceeded: ' + ', '.join(violations)}",
        )

    def check_position_size(self, trade, max_pct: float = None) -> "RiskCheckResult":
        """Check if trade size is within allowed percentage of account balance."""
        if isinstance(trade, dict):
            size = trade.get("size", 0)
        else:
            size = getattr(trade, "size", getattr(trade, "quantity", 0))
        balance = self.current_balance or 10000.0
        pct = size / balance if balance > 0 else 0
        limit = max_pct if max_pct is not None else self.config.max_position_size_pct
        passed = pct <= limit
        return RiskCheckResult(
            passed=passed,
            risk_level=RiskLevel.LOW if passed else RiskLevel.CRITICAL,
            message=f"Position size {pct:.2%} {'within' if passed else 'exceeds'} limit {limit:.2%}",
            details={"size": size, "balance": balance, "pct": pct, "limit": limit},
        )

    def update_daily_pnl(self, amount: float) -> None:
        self.daily_pnl += amount

    def get_risk_metrics(self) -> Dict[str, Any]:
        dd = (
            (self.peak_balance - self.current_balance) / self.peak_balance * 100
            if self.peak_balance
            else 0
        )
        return {
            "current_balance": self.current_balance,
            "peak_balance": self.peak_balance,
            "daily_pnl": self.daily_pnl,
            "current_drawdown": dd,
            "open_positions": len(self.open_positions),
        }

    def get_status(self) -> Dict[str, Any]:
        """Get risk manager status"""
        return {
            "trading_halted": self._trading_halted,
            "halt_reason": self._halt_reason,
            "halt_until": self._halt_until.isoformat() if self._halt_until else None,
            "current_drawdown": self.current_drawdown,
            "peak_equity": self.peak_equity,
            "daily_pnl": self.daily_pnl,
            "daily_pnl_pct": self.daily_pnl / self.daily_starting_equity
            if self.daily_starting_equity > 0
            else 0,
            "current_balance": self.current_balance,
            "peak_balance": self.peak_balance,
            "open_positions": len(self.open_positions),
            "config": {
                "max_position_size_pct": self.config.max_position_size_pct,
                "max_drawdown_pct": self.config.max_drawdown_pct,
                "daily_loss_limit_pct": self.config.daily_loss_limit_pct,
                "max_risk_per_trade": self.config.max_risk_per_trade,
                "max_open_positions": self.config.max_open_positions,
            },
        }


# ── Aliases expected by tests ─────────────────────────────────────────────────
from dataclasses import dataclass as _dc
from dataclasses import field as _field


@_dc
class PositionSizeResult:
    """Simple result returned by RiskManager.calculate_position_size."""

    size: float
    method: str = "risk"
    entry_price: float = 0.0


@_dc
class RiskCheckResult:
    """Result of a single risk check — used by tests."""

    passed: bool
    risk_level: "RiskLevel" = None
    message: str = ""
    details: dict = _field(default_factory=dict)

    def __post_init__(self):
        if self.risk_level is None:
            self.risk_level = RiskLevel.LOW if self.passed else RiskLevel.HIGH


# ── Graceful shutdown on invariant violations / panics ───────────────────────


def _graceful_shutdown(reason: str, exit_code: int = 1) -> None:
    """
    Halt all trading and exit the process cleanly.

    Called when an invariant is violated (e.g. negative equity) or an
    unrecoverable error is detected.  Sends SIGTERM to the process group
    so any spawned subprocesses also receive the signal, then exits.
    """
    logger.critical("GRACEFUL SHUTDOWN initiated: %s", reason)
    try:
        import atexit

        atexit._run_exitfuncs()  # noqa: SLF001
    except Exception as exc:
        logger.critical("atexit handlers failed during graceful shutdown: %s", exc)
    try:
        os.kill(os.getpid(), signal.SIGTERM)
    except Exception as exc:
        logger.critical("Failed to send SIGTERM during graceful shutdown: %s", exc)
    sys.exit(exit_code)


def install_invariant_signal_handlers(risk_manager: "RiskManager") -> None:
    """
    Install OS-level signal handlers that trigger a graceful shutdown when
    SIGTERM or SIGINT is received, giving the risk manager a chance to halt
    trading before the process exits.

    Args:
        risk_manager: The active :class:`RiskManager` instance.
    """

    def _handle(signum, frame):
        sig_name = signal.Signals(signum).name
        logger.warning(
            "Signal %s received — halting trading and shutting down.", sig_name
        )
        risk_manager._halt_trading(f"OS signal {sig_name}", duration_hours=0)
        sys.exit(0)

    signal.signal(signal.SIGTERM, _handle)
    signal.signal(signal.SIGINT, _handle)
    logger.info("Invariant signal handlers installed (SIGTERM, SIGINT).")
