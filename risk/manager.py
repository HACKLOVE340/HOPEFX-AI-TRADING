"""
Risk Manager

Manages trading risk including position sizing, stop losses, and portfolio limits.
"""

from typing import Dict, Optional, Any
from dataclasses import dataclass
from enum import Enum
import logging

logger = logging.getLogger(__name__)


class PositionSizeMethod(Enum):
    """Position sizing methods"""
    FIXED = "FIXED"
    PERCENT_BALANCE = "PERCENT_BALANCE"
    KELLY_CRITERION = "KELLY_CRITERION"
    RISK_BASED = "RISK_BASED"


@dataclass
class RiskConfig:
    """Risk management configuration"""
    max_risk_per_trade: float = 2.0  # Percentage of account
    max_position_size: float = 10000.0  # Maximum position in base currency
    max_leverage: float = 1.0
    max_open_positions: int = 5
    max_daily_loss: float = 5.0  # Percentage of account
    max_drawdown: float = 20.0  # Percentage
    position_size_method: PositionSizeMethod = PositionSizeMethod.PERCENT_BALANCE
    default_stop_loss_pct: float = 2.0  # Percentage
    default_take_profit_pct: float = 4.0  # Percentage


@dataclass
class PositionSize:
    """Position size calculation result"""
    size: float  # Position size in base currency
    risk_amount: float  # Amount at risk
    stop_loss_price: Optional[float] = None
    take_profit_price: Optional[float] = None
    notes: Optional[str] = None


class RiskManager:
    """
    Manages trading risk and position sizing.

    Features:
    - Position sizing calculations
    - Risk per trade validation
    - Portfolio limits enforcement
    - Drawdown monitoring
    """

    def __init__(self, config: RiskConfig, initial_balance: float = 10000.0):
        """
        Initialize risk manager.

        Args:
            config: Risk configuration
            initial_balance: Starting account balance
        """
        self.config = config
        self.initial_balance = initial_balance
        self.current_balance = initial_balance
        self.open_positions = []
        self.daily_pnl = 0.0
        self.daily_trades = 0  # Track daily trades
        self.total_pnl = 0.0
        self.peak_balance = initial_balance
        # Aliases for backward compatibility
        self.max_positions = config.max_open_positions
        self.max_drawdown = config.max_drawdown / 100.0  # Convert to decimal
        self.max_position_size = config.max_position_size

        logger.info(
            f"Risk Manager initialized with balance: ${initial_balance:,.2f}"
        )

    def calculate_position_size(
        self,
        symbol: Optional[str] = None,
        entry_price: float = 0.0,
        price: Optional[float] = None,  # Alias for entry_price
        stop_loss_price: Optional[float] = None,
        stop_loss: Optional[float] = None,  # Alias for stop_loss_price
        confidence: float = 1.0,
        **kwargs  # Accept additional parameters for flexibility
    ) -> PositionSize:
        """
        Calculate appropriate position size based on risk parameters.

        Args:
            symbol: Trading symbol (optional, for logging)
            entry_price: Planned entry price
            price: Alias for entry_price
            stop_loss_price: Stop loss price (optional)
            stop_loss: Alias for stop_loss_price
            confidence: Signal confidence (0.0 to 1.0)
            **kwargs: Additional parameters (method, amount, percent, risk_percent)

        Returns:
            PositionSize object with calculated values
        """
        # Handle parameter aliases
        if price is not None:
            entry_price = price
        if stop_loss is not None:
            stop_loss_price = stop_loss
            
        # Use default entry price if not provided
        if entry_price == 0.0:
            entry_price = 1.0
            
        # Calculate risk amount
        risk_pct = self.config.max_risk_per_trade * confidence
        risk_amount = self.current_balance * (risk_pct / 100.0)

        # Check if specific method is requested via kwargs
        method = kwargs.get('method', self.config.position_size_method)
        if isinstance(method, str):
            method_map = {
                'fixed': PositionSizeMethod.FIXED,
                'percent': PositionSizeMethod.PERCENT_BALANCE,
                'risk': PositionSizeMethod.RISK_BASED,
            }
            method = method_map.get(method, self.config.position_size_method)

        # Calculate position size based on method
        if method == PositionSizeMethod.FIXED or method == 'FIXED':
            amount = kwargs.get('amount', self.config.max_position_size)
            size = min(amount, risk_amount * 10)

        elif method == PositionSizeMethod.PERCENT_BALANCE or method == 'PERCENT_BALANCE':
            percent = kwargs.get('percent', risk_pct / 100.0)
            size = self.current_balance * percent
            size = min(size, self.config.max_position_size)

        elif method == PositionSizeMethod.RISK_BASED or method == 'RISK_BASED':
            if stop_loss_price:
                # Calculate size based on distance to stop loss
                risk_per_unit = abs(entry_price - stop_loss_price)
                if risk_per_unit > 0:
                    size = risk_amount / risk_per_unit
                    size = min(size, self.config.max_position_size)
                else:
                    size = risk_amount * 10
            else:
                size = risk_amount * 10

        else:
            size = risk_amount * 10

        # Calculate stop loss and take profit if not provided
        if not stop_loss_price:
            stop_loss_price = entry_price * (
                1 - self.config.default_stop_loss_pct / 100.0
            )

        take_profit_price = entry_price * (
            1 + self.config.default_take_profit_pct / 100.0
        )

        return PositionSize(
            size=round(size, 2),
            risk_amount=round(risk_amount, 2),
            stop_loss_price=round(stop_loss_price, 2) if stop_loss_price else None,
            take_profit_price=round(take_profit_price, 2),
            notes=f"Risk: {risk_pct:.2f}%, Method: {method if isinstance(method, str) else method.value if hasattr(method, 'value') else str(method)}"
        )

    def can_open_position(self, position_size: float) -> tuple[bool, str]:
        """
        Check if a new position can be opened.

        Args:
            position_size: Proposed position size

        Returns:
            Tuple of (can_open, reason)
        """
        # Check max open positions
        if len(self.open_positions) >= self.config.max_open_positions:
            return False, f"Max open positions reached ({self.config.max_open_positions})"

        # Check position size limit
        if position_size > self.config.max_position_size:
            return False, f"Position size exceeds maximum (${self.config.max_position_size:,.2f})"

        # Check daily loss limit
        daily_loss_pct = abs(self.daily_pnl / self.current_balance * 100)
        if self.daily_pnl < 0 and daily_loss_pct >= self.config.max_daily_loss:
            return False, f"Daily loss limit reached ({self.config.max_daily_loss}%)"

        # Check drawdown
        current_drawdown = self._calculate_drawdown()
        if current_drawdown >= self.config.max_drawdown:
            return False, f"Max drawdown exceeded ({self.config.max_drawdown}%)"

        return True, "Position approved"

    def register_position(self, position: Dict[str, Any]):
        """
        Register a new open position.

        Args:
            position: Position details
        """
        self.open_positions.append(position)
        logger.info(
            f"Registered position: {position.get('symbol')} "
            f"size={position.get('size')}"
        )

    def close_position(self, position_id: str, pnl: float):
        """
        Close a position and update metrics.

        Args:
            position_id: Position identifier
            pnl: Profit/Loss from position
        """
        # Remove from open positions
        self.open_positions = [
            p for p in self.open_positions
            if p.get('id') != position_id
        ]

        # Update balances
        self.current_balance += pnl
        self.daily_pnl += pnl
        self.total_pnl += pnl

        # Update peak balance
        if self.current_balance > self.peak_balance:
            self.peak_balance = self.current_balance

        logger.info(
            f"Closed position {position_id}: PnL=${pnl:.2f}, "
            f"Balance=${self.current_balance:.2f}"
        )

    def reset_daily_pnl(self):
        """Reset daily P&L counter"""
        self.daily_pnl = 0.0
        self.daily_trades = 0  # Also reset daily trades
        logger.info("Daily P&L reset")

    def reset_daily_stats(self):
        """Reset daily statistics (alias for reset_daily_pnl)"""
        self.reset_daily_pnl()

    def update_daily_pnl(self, pnl: float):
        """
        Update daily P&L.

        Args:
            pnl: Profit/loss to add to daily total
        """
        self.daily_pnl += pnl
        logger.debug(f"Daily P&L updated: {pnl:+.2f}, Total: {self.daily_pnl:.2f}")

    def validate_trade(
        self,
        symbol: str,
        size: float,
        side: str,
        **kwargs
    ) -> tuple[bool, str]:
        """
        Validate if a trade can be executed.

        Args:
            symbol: Trading symbol
            size: Position size
            side: Trade side (BUY/SELL)
            **kwargs: Additional parameters

        Returns:
            Tuple of (is_valid, reason)
        """
        # Check max open positions
        if len(self.open_positions) >= self.config.max_open_positions:
            return False, f"Max open positions reached ({self.config.max_open_positions})"

        # Check position size limit
        if size > self.config.max_position_size:
            return False, f"Position size exceeds maximum (${self.config.max_position_size:,.2f})"

        # Check daily loss limit
        daily_loss_pct = abs(self.daily_pnl / self.current_balance * 100) if self.current_balance > 0 else 0
        if self.daily_pnl < 0 and daily_loss_pct >= self.config.max_daily_loss:
            return False, f"Daily loss limit reached ({self.config.max_daily_loss}%)"

        # Check drawdown
        current_drawdown = self._calculate_drawdown()
        max_drawdown_pct = self.config.max_drawdown
        if current_drawdown >= max_drawdown_pct:
            return False, f"Max drawdown exceeded ({max_drawdown_pct}%)"

        return True, ""

    def check_risk_limits(self) -> tuple[bool, list]:
        """
        Check all risk limits.

        Returns:
            Tuple of (within_limits, list_of_violations)
        """
        violations = []

        # Check max positions
        if len(self.open_positions) >= self.config.max_open_positions:
            violations.append(f"Max positions: {len(self.open_positions)}/{self.config.max_open_positions}")

        # Check daily loss
        daily_loss_pct = abs(self.daily_pnl / self.current_balance * 100) if self.current_balance > 0 else 0
        if self.daily_pnl < 0 and daily_loss_pct >= self.config.max_daily_loss:
            violations.append(f"Daily loss limit: {daily_loss_pct:.2f}%/{self.config.max_daily_loss}%")

        # Check drawdown
        current_drawdown = self._calculate_drawdown()
        if current_drawdown >= self.config.max_drawdown:
            violations.append(f"Max drawdown: {current_drawdown:.2f}%/{self.config.max_drawdown}%")

        return len(violations) == 0, violations

    def calculate_stop_loss(
        self,
        entry_price: float,
        side: str = "BUY",
        percent: Optional[float] = None,
        **kwargs
    ) -> float:
        """
        Calculate stop loss price.

        Args:
            entry_price: Entry price
            side: Trade side (BUY/SELL)
            percent: Stop loss percentage (optional)
            **kwargs: Additional parameters

        Returns:
            Stop loss price
        """
        if percent is None:
            percent = self.config.default_stop_loss_pct

        if side.upper() in ["BUY", "LONG"]:
            # For long positions, stop loss is below entry
            stop_loss = entry_price * (1 - percent / 100.0)
        else:
            # For short positions, stop loss is above entry
            stop_loss = entry_price * (1 + percent / 100.0)

        return round(stop_loss, 5)

    def calculate_take_profit(
        self,
        entry_price: float,
        side: str = "BUY",
        percent: Optional[float] = None,
        **kwargs
    ) -> float:
        """
        Calculate take profit price.

        Args:
            entry_price: Entry price
            side: Trade side (BUY/SELL)
            percent: Take profit percentage (optional)
            **kwargs: Additional parameters

        Returns:
            Take profit price
        """
        if percent is None:
            percent = self.config.default_take_profit_pct

        if side.upper() in ["BUY", "LONG"]:
            # For long positions, take profit is above entry
            take_profit = entry_price * (1 + percent / 100.0)
        else:
            # For short positions, take profit is below entry
            take_profit = entry_price * (1 - percent / 100.0)

        return round(take_profit, 5)

    def _calculate_drawdown(self) -> float:
        """
        Calculate current drawdown percentage.

        Returns:
            Drawdown percentage
        """
        if self.peak_balance > 0:
            drawdown = (self.peak_balance - self.current_balance) / self.peak_balance * 100
            return max(0.0, drawdown)
        return 0.0

    def get_risk_metrics(self) -> Dict[str, Any]:
        """
        Get current risk metrics.

        Returns:
            Dictionary of risk metrics
        """
        return {
            'current_balance': round(self.current_balance, 2),
            'initial_balance': round(self.initial_balance, 2),
            'total_pnl': round(self.total_pnl, 2),
            'daily_pnl': round(self.daily_pnl, 2),
            'open_positions': len(self.open_positions),
            'max_positions': self.config.max_open_positions,
            'current_drawdown': round(self._calculate_drawdown(), 2),
            'max_drawdown': self.config.max_drawdown,
            'daily_loss_pct': round(abs(self.daily_pnl / self.current_balance * 100), 2) if self.current_balance > 0 else 0.0,
            'max_daily_loss': self.config.max_daily_loss,
        }

    def get_status(self) -> Dict[str, Any]:
        """
        Get risk manager status.

        Returns:
            Status dictionary
        """
        metrics = self.get_risk_metrics()
        metrics['config'] = {
            'max_risk_per_trade': self.config.max_risk_per_trade,
            'max_position_size': self.config.max_position_size,
            'position_size_method': self.config.position_size_method.value,
        }
        return metrics
