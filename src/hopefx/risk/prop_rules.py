from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Protocol

import structlog

logger = structlog.get_logger()


@dataclass
class PropConstraint:
    max_daily_loss_pct: Decimal = Decimal("0.05")  # 5%
    max_total_loss_pct: Decimal = Decimal("0.10")  # 10%
    min_trading_days: int = 5
    max_position_size: Decimal = Decimal("100")  # Lots
    forbidden_symbols: list[str] = None  # type: ignore[assignment]
    required_stop_loss: bool = True
    max_risk_per_trade_pct: Decimal = Decimal("0.02")  # 2%


class PropRuleEngine(Protocol):
    """Protocol for prop firm rule engines."""

    def validate_trade(self, symbol: str, size: Decimal, stop_loss: Decimal | None) -> tuple[bool, str]:
        ...

    def validate_account_state(self, equity: Decimal, daily_pnl: Decimal, total_pnl: Decimal) -> tuple[bool, str]:
        ...


class FTMORuleEngine:
    """FTMO Challenge & Verification rules."""

    def __init__(self) -> None:
        self.constraints = PropConstraint(
            max_daily_loss_pct=Decimal("0.05"),
            max_total_loss_pct=Decimal("0.10"),
            min_trading_days=4,
            max_position_size=Decimal("50"),
            required_stop_loss=True,
            max_risk_per_trade_pct=Decimal("0.02"),
        )
        self._trading_days: set[str] = set()
        self._max_equity: Decimal = Decimal("0")

    def validate_trade(
        self,
        symbol: str,
        size: Decimal,
        stop_loss: Decimal | None,
    ) -> tuple[bool, str]:
        """Validate trade against FTMO rules."""
        # Check stop loss requirement
        if self.constraints.required_stop_loss and stop_loss is None:
            return False, "FTMO: Stop loss required on all trades"

        # Check position size
        if size > self.constraints.max_position_size:
            return False, f"FTMO: Position size {size} exceeds max {self.constraints.max_position_size}"

        return True, "approved"

    def validate_account_state(
        self,
        equity: Decimal,
        daily_pnl: Decimal,
        total_pnl: Decimal,
    ) -> tuple[bool, str]:
        """Validate account state."""
        starting_balance = Decimal("100000")  # Example

        # Daily loss limit
        daily_loss_pct = abs(daily_pnl) / starting_balance
        if daily_loss_pct > self.constraints.max_daily_loss_pct:
            return False, f"FTMO: Daily loss limit breached ({daily_loss_pct:.2%})"

        # Total loss limit
        total_loss_pct = abs(total_pnl) / starting_balance
        if total_loss_pct > self.constraints.max_total_loss_pct:
            return False, f"FTMO: Total loss limit breached ({total_loss_pct:.2%})"

        return True, "compliant"

    def record_trading_day(self, date: str) -> None:
        """Record active trading day."""
        self._trading_days.add(date)

    def check_min_trading_days(self) -> tuple[bool, int]:
        """Check if minimum trading days met."""
        return len(self._trading_days) >= self.constraints.min_trading_days, len(self._trading_days)


class MyForexFundsRuleEngine:
    """MyForexFunds specific rules."""

    def __init__(self) -> None:
        self.constraints = PropConstraint(
            max_daily_loss_pct=Decimal("0.05"),
            max_total_loss_pct=Decimal("0.12"),
            min_trading_days=5,
            max_position_size=Decimal("100"),
            required_stop_loss=False,  # MFF doesn't require SL
            max_risk_per_trade_pct=Decimal("0.05"),
        )

    def validate_trade(
        self,
        symbol: str,
        size: Decimal,
        stop_loss: Decimal | None,
    ) -> tuple[bool, str]:
        """Validate trade."""
        if size > self.constraints.max_position_size:
            return False, f"MFF: Position size exceeds limit"

        return True, "approved"

    def validate_account_state(
        self,
        equity: Decimal,
        daily_pnl: Decimal,
        total_pnl: Decimal,
    ) -> tuple[bool, str]:
        """Validate account."""
        return True, "compliant"


class PropRuleManager:
    """Manager for multiple prop firm rule sets."""

    def __init__(self) -> None:
        self.engines: dict[str, PropRuleEngine] = {
            "ftmo": FTMORuleEngine(),
            "mff": MyForexFundsRuleEngine(),
            "generic": FTMORuleEngine(),  # Default to FTMO rules
        }
        self._active_engine: str = "generic"

    def set_prop_firm(self, firm: str) -> None:
        """Set active prop firm."""
        if firm not in self.engines:
            raise ValueError(f"Unknown prop firm: {firm}")
        self._active_engine = firm
        logger.info("prop_rules.set_firm", firm=firm)

    def validate(self, symbol: str, size: Decimal, stop_loss: Decimal | None) -> tuple[bool, str]:
        """Validate against active rules."""
        engine = self.engines[self._active_engine]
        return engine.validate_trade(symbol, size, stop_loss)

    def check_account(self, equity: Decimal, daily_pnl: Decimal, total_pnl: Decimal) -> tuple[bool, str]:
        """Check account compliance."""
        engine = self.engines[self._active_engine]
        return engine.validate_account_state(equity, daily_pnl, total_pnl)


# Global prop rule manager
prop_rules = PropRuleManager()
