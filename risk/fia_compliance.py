# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
# risk/fia_compliance.py
"""
FIA 2024 Automated Trading Risk Controls Implementation
Reference: FIA 2024 Automated Trading Risk Controls Report
"""

import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
UTC = timezone.utc
from enum import Enum

logger = logging.getLogger(__name__)


class RiskControlStatus(Enum):
    PASS = "pass"  # nosec B105 — enum value, not a password
    WARNING = "warning"
    BLOCK = "block"
    KILL_SWITCH = "kill_switch"


@dataclass
class RiskCheckResult:
    status: RiskControlStatus
    rule: str
    message: str
    timestamp: datetime
    metadata: dict | None = None


class FIAComplianceManager:
    """
    FIA 2024 Compliant Risk Control System
    Implements all mandatory pre-trade and post-trade controls
    """

    def __init__(self, config: dict):
        self.config = config
        self.kill_switch_active = False
        self.daily_pnl = 0.0
        self.orders_today = 0
        self.positions_intraday = {}
        self.last_order_time = None
        self.message_count = 0
        self.message_window_start = datetime.now(UTC)

        # Callbacks
        self.kill_switch_callbacks: list[Callable] = []

    # =========================================================================
    # FIA 1.1: Maximum Order Size
    # =========================================================================
    def check_max_order_size(self, order_size: float, symbol: str) -> RiskCheckResult:
        """Validate order size against maximum limits"""
        max_size = self.config.get("max_order_size", 100)  # lots
        self.config.get("max_order_notional", 1000000)  # USD

        if abs(order_size) > max_size:
            return RiskCheckResult(
                status=RiskControlStatus.BLOCK,
                rule="FIA_1.1_MAX_ORDER_SIZE",
                message=f"Order size {order_size} exceeds max {max_size}",
                timestamp=datetime.now(UTC),
                metadata={"requested": order_size, "limit": max_size},
            )

        return RiskCheckResult(
            status=RiskControlStatus.PASS,
            rule="FIA_1.1_MAX_ORDER_SIZE",
            message="Order size within limits",
            timestamp=datetime.now(UTC),
        )

    # =========================================================================
    # FIA 1.2: Maximum Intraday Position
    # =========================================================================
    def check_intraday_position(
        self,
        symbol: str,
        new_position: float,
    ) -> RiskCheckResult:
        """Validate against maximum intraday position limits"""
        max_position = self.config.get("max_intraday_position", 500)  # lots

        current = self.positions_intraday.get(symbol, 0)
        projected = current + new_position

        if abs(projected) > max_position:
            return RiskCheckResult(
                status=RiskControlStatus.BLOCK,
                rule="FIA_1.2_MAX_INTRADAY_POSITION",
                message=f"Position {projected} would exceed max {max_position}",
                timestamp=datetime.now(UTC),
                metadata={
                    "current": current,
                    "projected": projected,
                    "limit": max_position,
                },
            )

        self.positions_intraday[symbol] = projected
        return RiskCheckResult(
            status=RiskControlStatus.PASS,
            rule="FIA_1.2_MAX_INTRADAY_POSITION",
            message="Position within limits",
            timestamp=datetime.now(UTC),
        )

    # =========================================================================
    # FIA 1.3: Price Tolerance (Price Collars)
    # =========================================================================
    def check_price_tolerance(
        self,
        order_price: float,
        reference_price: float,
        tolerance_pct: float = 0.02,
    ) -> RiskCheckResult:
        """Validate order price is within tolerance of reference price"""
        if reference_price <= 0:
            return RiskCheckResult(
                status=RiskControlStatus.BLOCK,
                rule="FIA_1.3_PRICE_TOLERANCE",
                message="Invalid reference price",
                timestamp=datetime.now(UTC),
            )

        deviation = abs(order_price - reference_price) / reference_price

        if deviation > tolerance_pct:
            return RiskCheckResult(
                status=RiskControlStatus.BLOCK,
                rule="FIA_1.3_PRICE_TOLERANCE",
                message=f"Price {order_price} deviates {deviation:.2%} from reference {reference_price}",
                timestamp=datetime.now(UTC),
                metadata={"deviation": deviation, "tolerance": tolerance_pct},
            )

        return RiskCheckResult(
            status=RiskControlStatus.PASS,
            rule="FIA_1.3_PRICE_TOLERANCE",
            message="Price within tolerance",
            timestamp=datetime.now(UTC),
        )

    # =========================================================================
    # FIA 1.5: Kill Switch (Loss Limits)
    # =========================================================================
    def check_kill_switch(
        self,
        daily_pnl: float,
        capital: float,
        threshold_pct: float = 0.03,
    ) -> RiskCheckResult:
        """Activate kill switch if daily loss exceeds threshold"""
        self.daily_pnl = daily_pnl

        loss_pct = abs(daily_pnl) / capital if capital > 0 else 0

        if loss_pct >= threshold_pct:
            self.kill_switch_active = True

            # Notify all registered callbacks
            for callback in self.kill_switch_callbacks:
                try:
                    callback(daily_pnl, loss_pct)
                except Exception as e:
                    logger.error("Kill switch callback error: %s", e)

            return RiskCheckResult(
                status=RiskControlStatus.KILL_SWITCH,
                rule="FIA_1.5_KILL_SWITCH",
                message=f"Daily loss {loss_pct:.2%} exceeded threshold {threshold_pct:.2%}",
                timestamp=datetime.now(UTC),
                metadata={"daily_pnl": daily_pnl, "loss_pct": loss_pct},
            )

        return RiskCheckResult(
            status=RiskControlStatus.PASS,
            rule="FIA_1.5_KILL_SWITCH",
            message="Loss within limits",
            timestamp=datetime.now(UTC),
        )

    def register_kill_switch_callback(self, callback: Callable):
        """Register callback for kill switch activation"""
        self.kill_switch_callbacks.append(callback)

    # =========================================================================
    # FIA 3.1: Market Data Validation
    # =========================================================================
    def validate_market_data(self, tick_data: dict) -> RiskCheckResult:
        """Validate market data for staleness and reasonability"""
        checks = []

        # Check timestamp staleness
        tick_time = tick_data.get("timestamp")
        if tick_time:
            if isinstance(tick_time, int | float):
                tick_time = datetime.fromtimestamp(tick_time)
            age = (datetime.now(UTC) - tick_time).total_seconds()
            checks.append(("staleness", age < 30))  # 30 seconds max

        # Check price reasonability
        bid = tick_data.get("bid", 0)
        ask = tick_data.get("ask", 0)
        checks.append(("valid_prices", bid > 0 and ask > 0 and ask > bid))

        # Check spread reasonability
        if bid > 0:
            spread_pct = (ask - bid) / bid
            checks.append(("reasonable_spread", spread_pct < 0.01))  # 1% max

        failed = [name for name, passed in checks if not passed]

        if failed:
            return RiskCheckResult(
                status=RiskControlStatus.BLOCK,
                rule="FIA_3.1_MARKET_DATA_VALIDATION",
                message=f"Market data validation failed: {failed}",
                timestamp=datetime.now(UTC),
                metadata={"failed_checks": failed, "tick_data": tick_data},
            )

        return RiskCheckResult(
            status=RiskControlStatus.PASS,
            rule="FIA_3.1_MARKET_DATA_VALIDATION",
            message="Market data valid",
            timestamp=datetime.now(UTC),
        )

    # =========================================================================
    # FIA 3.4: Message Throttling
    # =========================================================================
    def check_message_throttle(self) -> RiskCheckResult:
        """Throttle message rate to prevent system overload"""
        now = datetime.now(UTC)
        window_seconds = 1

        # Reset window
        if (now - self.message_window_start).total_seconds() > window_seconds:
            self.message_window_start = now
            self.message_count = 0

        self.message_count += 1
        max_messages = self.config.get("max_messages_per_second", 50)

        if self.message_count > max_messages:
            return RiskCheckResult(
                status=RiskControlStatus.BLOCK,
                rule="FIA_3.4_MESSAGE_THROTTLE",
                message=f"Message rate {self.message_count}/sec exceeds max {max_messages}",
                timestamp=datetime.now(UTC),
                metadata={"count": self.message_count, "limit": max_messages},
            )

        return RiskCheckResult(
            status=RiskControlStatus.PASS,
            rule="FIA_3.4_MESSAGE_THROTTLE",
            message="Message rate within limits",
            timestamp=datetime.now(UTC),
        )

    # =========================================================================
    # FIA 3.5: Self-Trade Prevention
    # =========================================================================
    def check_self_trade(
        self,
        order: dict,
        resting_orders: list[dict],
        prevention_level: str = "account",
    ) -> RiskCheckResult:
        """Prevent wash trades and self-matching"""
        order_side = order.get("side")
        order_price = order.get("price")

        for resting in resting_orders:
            # Check if opposing side
            if resting.get("side") == order_side:
                continue

            # Check if prices cross
            resting_price = resting.get("price")
            if order_side == "buy" and order_price >= resting_price:
                return RiskCheckResult(
                    status=RiskControlStatus.BLOCK,
                    rule="FIA_3.5_SELF_TRADE_PREVENTION",
                    message=f"Self-trade detected: buy {order_price} crosses sell {resting_price}",
                    timestamp=datetime.now(UTC),
                    metadata={"order": order, "resting": resting},
                )
            if order_side == "sell" and order_price <= resting_price:
                return RiskCheckResult(
                    status=RiskControlStatus.BLOCK,
                    rule="FIA_3.5_SELF_TRADE_PREVENTION",
                    message=f"Self-trade detected: sell {order_price} crosses buy {resting_price}",
                    timestamp=datetime.now(UTC),
                    metadata={"order": order, "resting": resting},
                )

        return RiskCheckResult(
            status=RiskControlStatus.PASS,
            rule="FIA_3.5_SELF_TRADE_PREVENTION",
            message="No self-trade detected",
            timestamp=datetime.now(UTC),
        )

    # =========================================================================
    # Master Validation
    # =========================================================================
    async def validate_order(
        self,
        order: dict,
        market_data: dict,
        portfolio_state: dict,
    ) -> list[RiskCheckResult]:
        """Run all FIA compliance checks on an order"""
        results = []

        # Check kill switch first
        kill_result = self.check_kill_switch(
            portfolio_state.get("daily_pnl", 0),
            portfolio_state.get("capital", 100000),
            self.config.get("daily_loss_limit", 0.03),
        )
        results.append(kill_result)

        if kill_result.status == RiskControlStatus.KILL_SWITCH:
            return results  # Stop all trading

        # Run other checks
        checks = [
            self.check_max_order_size(order.get("size", 0), order.get("symbol")),
            self.check_intraday_position(order.get("symbol"), order.get("size", 0)),
            self.check_price_tolerance(
                order.get("price", 0),
                market_data.get("mid", 0),
                self.config.get("price_tolerance", 0.02),
            ),
            self.validate_market_data(market_data),
            self.check_message_throttle(),
        ]

        results.extend(checks)

        # Log any blocks
        for result in results:
            if result.status in [
                RiskControlStatus.BLOCK,
                RiskControlStatus.KILL_SWITCH,
            ]:
                logger.warning("Risk control blocked: %s - %s", result.rule, result.message)

        return results
