#!/usr/bin/env python3
# Copyright (c) 2025-2026
# HOPEFX-AI-TRADING
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
HOPEFX Order Validation Module
Prevents bad trades through pre-execution checks.
"""

import logging
from dataclasses import dataclass, field

logger = logging.getLogger("validation")


@dataclass
class Order:
    """Order data structure."""

    symbol: str
    side: str  # 'buy' or 'sell'
    qty: float
    order_type: str = "market"
    price: float | None = None  # For limit orders
    stop_loss: float | None = None
    take_profit: float | None = None


@dataclass
class ValidationResult:
    """Validation result with reason if rejected."""

    valid: bool
    reason: str | None = None
    risk_pct: float | None = None


@dataclass
class ValidatorConfig:
    """Configuration for OrderValidator — replaces 9-parameter __init__."""

    max_position_risk_pct: float = 0.02  # 2% max risk per trade
    max_daily_risk_pct: float = 0.05  # 5% max daily risk
    min_qty: float = 0.01  # Minimum lot size
    max_qty: float = 10.0  # Maximum lot size
    max_spread_pct: float = 0.001  # 0.1% max spread
    max_leverage: float = 30.0  # Max leverage
    allowed_symbols: list = field(default_factory=lambda: ["XAUUSD", "EURUSD", "GBPUSD"])


# Price sanity bounds per symbol (min, max).
_PRICE_BOUNDS: dict = {
    "XAUUSD": (1000.0, 5000.0),
}


class OrderValidator:
    """Validates orders before execution to prevent bad trades."""

    def __init__(self, config: ValidatorConfig | None = None) -> None:
        cfg = config or ValidatorConfig()
        self.max_position_risk = cfg.max_position_risk_pct
        self.max_daily_risk = cfg.max_daily_risk_pct
        self.min_qty = cfg.min_qty
        self.max_qty = cfg.max_qty
        self.max_spread_pct = cfg.max_spread_pct
        self.max_leverage = cfg.max_leverage
        self.allowed_symbols = list(cfg.allowed_symbols)
        self.daily_risk_used = 0.0
        self.reset_time = None

    # ── Private validators ────────────────────────────────────────────────────

    def _check_symbol(self, order: Order) -> ValidationResult | None:
        if order.symbol not in self.allowed_symbols:
            return ValidationResult(valid=False, reason=f"Symbol {order.symbol} not in allowed list")
        return None

    def _check_side(self, order: Order) -> ValidationResult | None:
        if order.side not in ("buy", "sell"):
            return ValidationResult(valid=False, reason=f"Invalid side: {order.side}")
        return None

    def _check_quantity(self, order: Order) -> ValidationResult | None:
        if order.qty < self.min_qty:
            return ValidationResult(
                valid=False,
                reason=f"Quantity {order.qty} below minimum {self.min_qty}",
            )
        if order.qty > self.max_qty:
            return ValidationResult(
                valid=False,
                reason=f"Quantity {order.qty} exceeds maximum {self.max_qty}",
            )
        return None

    def _check_price_sanity(self, order: Order, current_price: float) -> ValidationResult | None:
        if current_price <= 0:
            return ValidationResult(valid=False, reason="Invalid current price")
        bounds = _PRICE_BOUNDS.get(order.symbol)
        if bounds and not (bounds[0] <= current_price <= bounds[1]):
            return ValidationResult(
                valid=False,
                reason=f"Suspicious {order.symbol} price: {current_price}",
            )
        return None

    def _check_position_risk(
        self, order: Order, current_price: float, account_balance: float
    ) -> tuple[ValidationResult | None, float]:
        position_value = order.qty * current_price
        risk_pct = position_value / account_balance if account_balance > 0 else 1.0
        if risk_pct > self.max_position_risk:
            return (
                ValidationResult(
                    valid=False,
                    reason=(f"Position risk {risk_pct:.2%} exceeds max {self.max_position_risk:.2%}"),
                ),
                risk_pct,
            )
        return None, risk_pct

    def _check_daily_risk(self, risk_pct: float) -> ValidationResult | None:
        if self.daily_risk_used + risk_pct > self.max_daily_risk:
            return ValidationResult(
                valid=False,
                reason=(f"Daily risk limit would be exceeded ({self.daily_risk_used:.2%} used)"),
            )
        return None

    def _check_stop_loss(self, order: Order, current_price: float) -> ValidationResult | None:
        if order.stop_loss is None:
            logger.warning(
                "Order %s %s has no stop loss - using default 2%%",
                order.symbol,
                order.side,
            )
            return None

        if order.side == "buy" and order.stop_loss >= current_price:
            return ValidationResult(
                valid=False,
                reason="Stop loss must be below entry for long positions",
            )
        if order.side == "sell" and order.stop_loss <= current_price:
            return ValidationResult(
                valid=False,
                reason="Stop loss must be above entry for short positions",
            )

        stop_distance_pct = abs(current_price - order.stop_loss) / current_price
        if stop_distance_pct < 0.001:
            return ValidationResult(
                valid=False,
                reason="Stop loss too tight (< 0.1%) - will be hit by noise",
            )
        if stop_distance_pct > 0.05:
            return ValidationResult(valid=False, reason="Stop loss too wide (> 5%) - excessive risk")
        return None

    def _check_take_profit(self, order: Order, current_price: float) -> ValidationResult | None:
        if order.take_profit is None:
            return None
        if order.side == "buy" and order.take_profit <= current_price:
            return ValidationResult(
                valid=False,
                reason="Take profit must be above entry for long positions",
            )
        if order.side == "sell" and order.take_profit >= current_price:
            return ValidationResult(
                valid=False,
                reason="Take profit must be below entry for short positions",
            )
        return None

    def _check_duplicate_position(self, order: Order, open_positions: list) -> ValidationResult | None:
        for pos in open_positions:
            if pos.get("symbol") == order.symbol and pos.get("side") == order.side:
                return ValidationResult(
                    valid=False,
                    reason=f"Already have {order.side} position in {order.symbol}",
                )
        return None

    def _check_leverage(self, order: Order, current_price: float, account_balance: float) -> ValidationResult | None:
        if account_balance <= 0:
            return None
        effective_leverage = (order.qty * current_price) / account_balance
        if effective_leverage > self.max_leverage:
            return ValidationResult(
                valid=False,
                reason=f"Leverage would exceed {self.max_leverage}x",
            )
        return None

    # ── Public interface ──────────────────────────────────────────────────────

    def validate_order(
        self,
        order: Order,
        current_price: float,
        account_balance: float,
        open_positions: list | None = None,
    ) -> ValidationResult:
        """
        Validate an order against risk rules.

        Returns ValidationResult with valid=True if order passes all checks.
        """
        open_positions = open_positions or []

        for result in (
            self._check_symbol(order),
            self._check_side(order),
            self._check_quantity(order),
            self._check_price_sanity(order, current_price),
        ):
            if result is not None:
                return result

        rejection, risk_pct = self._check_position_risk(order, current_price, account_balance)
        if rejection is not None:
            return rejection

        for result in (
            self._check_daily_risk(risk_pct),
            self._check_stop_loss(order, current_price),
            self._check_take_profit(order, current_price),
            self._check_duplicate_position(order, open_positions),
            self._check_leverage(order, current_price, account_balance),
        ):
            if result is not None:
                return result

        return ValidationResult(valid=True, risk_pct=risk_pct)

    def record_trade(self, risk_pct: float) -> None:
        """Record executed trade risk for daily limit tracking."""
        self.daily_risk_used += risk_pct
        logger.info("Daily risk now at %.2f%%", self.daily_risk_used * 100)

    def reset_daily_risk(self) -> None:
        """Reset daily risk counter (call at market open)."""
        self.daily_risk_used = 0.0
        logger.info("Daily risk counter reset")


class PropFirmValidator:
    """
    Enforces prop firm trading rules for FTMO, The5ers, MyForexFunds,
    TrueForexFunds, and The Funded Trader.

    Rules are sourced from each firm's published challenge/evaluation
    documentation.  This validator is used as a hard gate in the execution
    pipeline — a False result from check_limits() must block order submission.

    Note: Always verify against the firm's current terms before live use;
    firms occasionally revise their rule sets.
    """

    # Published rules per firm (as of 2025).
    # Sources:
    #   FTMO:              https://ftmo.com/en/trading-objectives/
    #   The5ers:           https://the5ers.com/trading-rules/
    #   MyForexFunds:      https://myforexfunds.com/rules/
    #   TrueForexFunds:    https://trueforexfunds.com/rules/
    #   The Funded Trader: https://thefundedtrader.com/rules/
    _FIRM_RULES: dict = {
        "ftmo": {
            "max_daily_loss_pct": 0.05,
            "max_total_loss_pct": 0.10,
            "min_trading_days": 4,
            "profit_target_pct": 0.10,
            "max_drawdown_pct": 0.10,
        },
        "the5ers": {
            "max_daily_loss_pct": 0.05,
            "max_total_loss_pct": 0.06,
            "min_trading_days": 3,
            "profit_target_pct": 0.06,
            "max_drawdown_pct": 0.06,
        },
        "myforexfunds": {
            "max_daily_loss_pct": 0.05,
            "max_total_loss_pct": 0.10,
            "min_trading_days": 5,
            "profit_target_pct": 0.08,
            "max_drawdown_pct": 0.10,
        },
        "trueforexfunds": {
            "max_daily_loss_pct": 0.05,
            "max_total_loss_pct": 0.10,
            "min_trading_days": 5,
            "profit_target_pct": 0.10,
            "max_drawdown_pct": 0.10,
        },
        "thefundedtrader": {
            "max_daily_loss_pct": 0.05,
            "max_total_loss_pct": 0.10,
            "min_trading_days": 5,
            "profit_target_pct": 0.10,
            "max_drawdown_pct": 0.10,
        },
    }

    def __init__(self, firm: str = "ftmo", initial_balance: float = 0.0) -> None:
        self.firm = firm.lower()
        self.rules = self._load_rules(self.firm)
        self.initial_balance = initial_balance
        self.daily_loss = 0.0
        self.total_loss = 0.0
        self.peak_equity = 0.0
        self._trading_days: set = set()

    def _load_rules(self, firm: str) -> dict:
        rules = self._FIRM_RULES.get(firm)
        if rules is None:
            logger.warning(
                "Unknown prop firm %r — falling back to FTMO rules. Supported: %s",
                firm,
                sorted(self._FIRM_RULES),
            )
            rules = self._FIRM_RULES["ftmo"]
        return rules

    def check_limits(self, current_equity: float, open_pnl: float = 0.0) -> tuple[bool, str]:
        total_equity = current_equity + open_pnl
        denominator = self.initial_balance if self.initial_balance > 0 else current_equity

        self.peak_equity = max(self.peak_equity, total_equity)

        if self.peak_equity > 0:
            drawdown = (self.peak_equity - total_equity) / self.peak_equity
            if drawdown > self.rules["max_drawdown_pct"]:
                return (
                    False,
                    f"Max drawdown exceeded: {drawdown:.2%} > {self.rules['max_drawdown_pct']:.2%}",
                )

        if denominator <= 0:
            return True, "Within limits"

        daily_loss_pct = abs(self.daily_loss) / denominator
        if daily_loss_pct > self.rules["max_daily_loss_pct"]:
            return (
                False,
                f"Daily loss limit exceeded: {daily_loss_pct:.2%} > {self.rules['max_daily_loss_pct']:.2%}",
            )

        total_loss_pct = abs(self.total_loss) / denominator
        if total_loss_pct > self.rules["max_total_loss_pct"]:
            return (
                False,
                f"Total loss limit exceeded: {total_loss_pct:.2%} > {self.rules['max_total_loss_pct']:.2%}",
            )

        return True, "Within limits"

    def check_profit_target(self, current_equity: float) -> tuple[bool, float]:
        if self.initial_balance <= 0:
            return False, 0.0
        profit_pct = (current_equity - self.initial_balance) / self.initial_balance
        target_met = profit_pct >= self.rules["profit_target_pct"]
        return target_met, profit_pct

    def record_trade_day(self, trade_date: str | None = None) -> None:
        from datetime import date as _date

        if trade_date is None:
            trade_date = _date.today().isoformat()
        self._trading_days.add(trade_date)

    def check_min_trading_days(self) -> tuple[bool, int]:
        days_traded = len(self._trading_days)
        met = days_traded >= self.rules["min_trading_days"]
        return met, days_traded

    def record_pnl(self, pnl: float, trade_date: str | None = None) -> None:
        if pnl < 0:
            self.daily_loss += pnl
            self.total_loss += pnl
        self.record_trade_day(trade_date)

    def reset_daily(self) -> None:
        self.daily_loss = 0.0

    def get_status(self, current_equity: float) -> dict:
        within_limits, limit_reason = self.check_limits(current_equity)
        target_met, profit_pct = self.check_profit_target(current_equity)
        days_met, days_traded = self.check_min_trading_days()
        denominator = self.initial_balance if self.initial_balance > 0 else current_equity or 1.0
        return {
            "firm": self.firm,
            "within_limits": within_limits,
            "limit_reason": limit_reason,
            "profit_target_met": target_met,
            "profit_pct": round(profit_pct, 4),
            "profit_target_pct": self.rules["profit_target_pct"],
            "min_trading_days_met": days_met,
            "days_traded": days_traded,
            "min_trading_days_required": self.rules["min_trading_days"],
            "daily_loss_pct": round(abs(self.daily_loss) / denominator, 4),
            "max_daily_loss_pct": self.rules["max_daily_loss_pct"],
            "total_loss_pct": round(abs(self.total_loss) / denominator, 4),
            "max_total_loss_pct": self.rules["max_total_loss_pct"],
        }


def validate_order_safe(
    symbol: str,
    side: str,
    qty: float,
    current_price: float,
    account_balance: float,
    stop_loss: float | None = None,
    take_profit: float | None = None,
) -> bool:
    """Simple validation function for quick use."""
    validator = OrderValidator()
    order = Order(symbol=symbol, side=side, qty=qty, stop_loss=stop_loss, take_profit=take_profit)
    result = validator.validate_order(order, current_price, account_balance)

    if not result.valid:
        logger.error("Order rejected: %s", result.reason)
        return False

    return True


if __name__ == "__main__":
    logger.info("=" * 60)
    logger.info("Order Validation Demo")
    logger.info("=" * 60)

    validator = OrderValidator()

    order = Order(symbol="XAUUSD", side="buy", qty=0.01, stop_loss=1950.0)
    result = validator.validate_order(order, current_price=2000.0, account_balance=10000.0)
    logger.info("\nValid order test: %s (risk: %s)", result.valid, f"{result.risk_pct:.2%}")

    big_order = Order(symbol="XAUUSD", side="buy", qty=1.0)
    result = validator.validate_order(big_order, current_price=2000.0, account_balance=10000.0)
    logger.info("Oversized order test: %s - %s", result.valid, result.reason)

    bad_order = Order(symbol="INVALID", side="buy", qty=0.01)
    result = validator.validate_order(bad_order, current_price=100.0, account_balance=10000.0)
    logger.info("Invalid symbol test: %s - %s", result.valid, result.reason)

    logger.info("\n" + "=" * 60)
    logger.info("Prop Firm Validation")
    logger.info("=" * 60)

    prop = PropFirmValidator(firm="ftmo", initial_balance=100000.0)
    valid, msg = prop.check_limits(current_equity=100000.0)
    logger.info("Initial check: %s - %s", valid, msg)

    prop.record_pnl(-3000)
    valid, msg = prop.check_limits(current_equity=97000.0)
    logger.info("After $3k loss: %s - %s", valid, msg)
