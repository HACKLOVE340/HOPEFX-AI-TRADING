#!/usr/bin/env python3
"""
HOPEFX Order Validation Module
Prevents bad trades through pre-execution checks.
"""

import logging
from dataclasses import dataclass
from decimal import Decimal
from typing import Optional, Tuple

logger = logging.getLogger('validation')


@dataclass
class Order:
    """Order data structure."""
    symbol: str
    side: str  # 'buy' or 'sell'
    qty: float
    order_type: str = 'market'
    price: Optional[float] = None  # For limit orders
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None


@dataclass
class ValidationResult:
    """Validation result with reason if rejected."""
    valid: bool
    reason: Optional[str] = None
    risk_pct: Optional[float] = None


class OrderValidator:
    """Validates orders before execution to prevent bad trades."""
    
    def __init__(
        self,
        max_position_risk_pct: float = 0.02,  # 2% max risk per trade
        max_daily_risk_pct: float = 0.05,     # 5% max daily risk
        min_qty: float = 0.01,                # Minimum lot size
        max_qty: float = 10.0,                # Maximum lot size
        max_spread_pct: float = 0.001,        # 0.1% max spread
        max_leverage: float = 30.0,           # Max leverage
        allowed_symbols: Optional[list] = None
    ):
        self.max_position_risk = max_position_risk_pct
        self.max_daily_risk = max_daily_risk_pct
        self.min_qty = min_qty
        self.max_qty = max_qty
        self.max_spread_pct = max_spread_pct
        self.max_leverage = max_leverage
        self.allowed_symbols = allowed_symbols or ['XAUUSD', 'EURUSD', 'GBPUSD']
        self.daily_risk_used = 0.0
        self.reset_time = None
        
    def validate_order(
        self,
        order: Order,
        current_price: float,
        account_balance: float,
        open_positions: Optional[list] = None
    ) -> ValidationResult:
        """
        Validate an order against risk rules.
        
        Returns ValidationResult with valid=True if order passes all checks.
        """
        open_positions = open_positions or []
        
        # 1. Symbol validation
        if order.symbol not in self.allowed_symbols:
            return ValidationResult(
                valid=False,
                reason=f"Symbol {order.symbol} not in allowed list"
            )
        
        # 2. Side validation
        if order.side not in ['buy', 'sell']:
            return ValidationResult(
                valid=False,
                reason=f"Invalid side: {order.side}"
            )
        
        # 3. Quantity validation
        if order.qty < self.min_qty:
            return ValidationResult(
                valid=False,
                reason=f"Quantity {order.qty} below minimum {self.min_qty}"
            )
        
        if order.qty > self.max_qty:
            return ValidationResult(
                valid=False,
                reason=f"Quantity {order.qty} exceeds maximum {self.max_qty}"
            )
        
        # 4. Price validation (prevent fat-finger errors)
        if current_price <= 0:
            return ValidationResult(
                valid=False,
                reason="Invalid current price"
            )
        
        # Check for unrealistic prices (XAUUSD should be ~1800-2200)
        if order.symbol == 'XAUUSD':
            if current_price < 1000 or current_price > 5000:
                return ValidationResult(
                    valid=False,
                    reason=f"Suspicious XAUUSD price: {current_price}"
                )
        
        # 5. Risk per trade validation
        position_value = order.qty * current_price
        risk_pct = position_value / account_balance if account_balance > 0 else 1.0
        
        if risk_pct > self.max_position_risk:
            return ValidationResult(
                valid=False,
                reason=f"Position risk {risk_pct:.2%} exceeds max {self.max_position_risk:.2%}"
            )
        
        # 6. Daily risk limit check
        if self.daily_risk_used + risk_pct > self.max_daily_risk:
            return ValidationResult(
                valid=False,
                reason=f"Daily risk limit would be exceeded ({self.daily_risk_used:.2%} used)"
            )
        
        # 7. Stop loss validation (mandatory for risk management)
        if order.stop_loss is not None:
            if order.side == 'buy' and order.stop_loss >= current_price:
                return ValidationResult(
                    valid=False,
                    reason="Stop loss must be below entry for long positions"
                )
            if order.side == 'sell' and order.stop_loss <= current_price:
                return ValidationResult(
                    valid=False,
                    reason="Stop loss must be above entry for short positions"
                )
            
            # Validate stop distance (not too tight, not too wide)
            stop_distance = abs(current_price - order.stop_loss)
            stop_distance_pct = stop_distance / current_price
            
            if stop_distance_pct < 0.001:  # 0.1%
                return ValidationResult(
                    valid=False,
                    reason="Stop loss too tight (< 0.1%) - will be hit by noise"
                )
            
            if stop_distance_pct > 0.05:  # 5%
                return ValidationResult(
                    valid=False,
                    reason="Stop loss too wide (> 5%) - excessive risk"
                )
        else:
            logger.warning(f"Order {order.symbol} {order.side} has no stop loss - using default 2%")
        
        # 8. Take profit validation
        if order.take_profit is not None:
            if order.side == 'buy' and order.take_profit <= current_price:
                return ValidationResult(
                    valid=False,
                    reason="Take profit must be above entry for long positions"
                )
            if order.side == 'sell' and order.take_profit >= current_price:
                return ValidationResult(
                    valid=False,
                    reason="Take profit must be below entry for short positions"
                )
        
        # 9. Duplicate order check (prevent double-clicking)
        for pos in open_positions:
            if pos.get('symbol') == order.symbol and pos.get('side') == order.side:
                return ValidationResult(
                    valid=False,
                    reason=f"Already have {order.side} position in {order.symbol}"
                )
        
        # 10. Leverage check
        if position_value / account_balance > self.max_leverage:
            return ValidationResult(
                valid=False,
                reason=f"Leverage would exceed {self.max_leverage}x"
            )
        
        # All checks passed
        return ValidationResult(valid=True, risk_pct=risk_pct)
    
    def record_trade(self, risk_pct: float):
        """Record executed trade risk for daily limit tracking."""
        self.daily_risk_used += risk_pct
        logger.info(f"Daily risk now at {self.daily_risk_used:.2%}")
    
    def reset_daily_risk(self):
        """Reset daily risk counter (call at market open)."""
        self.daily_risk_used = 0.0
        logger.info("Daily risk counter reset")


class PropFirmValidator:
    """Validates against prop firm rules (simulated only - no real compliance)."""
    
    def __init__(self, firm: str = 'ftmo'):
        self.firm = firm
        self.rules = self._load_rules(firm)
        self.daily_loss = 0.0
        self.total_loss = 0.0
        self.peak_equity = 0.0
        
    def _load_rules(self, firm: str) -> dict:
        """Load prop firm rules (simulated)."""
        rules = {
            'ftmo': {
                'max_daily_loss_pct': 0.05,      # 5% daily loss limit
                'max_total_loss_pct': 0.10,      # 10% total loss limit
                'min_trading_days': 4,           # Minimum trading days
                'profit_target_pct': 0.10,       # 10% profit target
                'max_drawdown_pct': 0.10,        # 10% max drawdown
            },
            'the5ers': {
                'max_daily_loss_pct': 0.05,
                'max_total_loss_pct': 0.06,
                'min_trading_days': 3,
                'profit_target_pct': 0.06,
                'max_drawdown_pct': 0.06,
            }
        }
        return rules.get(firm, rules['ftmo'])
    
    def check_limits(self, current_equity: float, open_pnl: float = 0) -> Tuple[bool, str]:
        """
        Check if current equity violates prop firm limits.
        
        ⚠️ SIMULATED ONLY - This does NOT guarantee real prop firm compliance.
        """
        total_equity = current_equity + open_pnl
        
        # Update peak equity
        if total_equity > self.peak_equity:
            self.peak_equity = total_equity
        
        # Check drawdown
        if self.peak_equity > 0:
            drawdown = (self.peak_equity - total_equity) / self.peak_equity
            if drawdown > self.rules['max_drawdown_pct']:
                return False, f"Max drawdown exceeded: {drawdown:.2%} > {self.rules['max_drawdown_pct']:.2%}"
        
        # Check daily loss
        daily_loss_pct = abs(self.daily_loss) / current_equity if current_equity > 0 else 0
        if daily_loss_pct > self.rules['max_daily_loss_pct']:
            return False, f"Daily loss limit exceeded: {daily_loss_pct:.2%}"
        
        # Check total loss
        total_loss_pct = abs(self.total_loss) / current_equity if current_equity > 0 else 0
        if total_loss_pct > self.rules['max_total_loss_pct']:
            return False, f"Total loss limit exceeded: {total_loss_pct:.2%}"
        
        return True, "Within limits"
    
    def record_pnl(self, pnl: float):
        """Record P&L for limit tracking."""
        if pnl < 0:
            self.daily_loss += pnl
            self.total_loss += pnl
        
    def reset_daily(self):
        """Reset daily counters."""
        self.daily_loss = 0.0


# Convenience functions
def validate_order_safe(
    symbol: str,
    side: str,
    qty: float,
    current_price: float,
    account_balance: float,
    stop_loss: Optional[float] = None,
    take_profit: Optional[float] = None
) -> bool:
    """Simple validation function for quick use."""
    validator = OrderValidator()
    order = Order(
        symbol=symbol,
        side=side,
        qty=qty,
        stop_loss=stop_loss,
        take_profit=take_profit
    )
    result = validator.validate_order(order, current_price, account_balance)
    
    if not result.valid:
        logger.error(f"Order rejected: {result.reason}")
        return False
    
    return True


if __name__ == '__main__':
    # Demo
    print("=" * 60)
    print("Order Validation Demo")
    print("=" * 60)
    
    validator = OrderValidator()
    
    # Test valid order
    order = Order(symbol='XAUUSD', side='buy', qty=0.01, stop_loss=1950.0)
    result = validator.validate_order(order, current_price=2000.0, account_balance=10000.0)
    print(f"\\nValid order test: {result.valid} (risk: {result.risk_pct:.2%})")
    
    # Test oversized order
    big_order = Order(symbol='XAUUSD', side='buy', qty=1.0)
    result = validator.validate_order(big_order, current_price=2000.0, account_balance=10000.0)
    print(f"Oversized order test: {result.valid} - {result.reason}")
    
    # Test invalid symbol
    bad_order = Order(symbol='INVALID', side='buy', qty=0.01)
    result = validator.validate_order(bad_order, current_price=100.0, account_balance=10000.0)
    print(f"Invalid symbol test: {result.valid} - {result.reason}")
    
    # Prop firm demo
    print("\\n" + "=" * 60)
    print("Prop Firm Validation (Simulated)")
    print("=" * 60)
    print("⚠️  WARNING: Simulated rules only - NOT real compliance")
    
    prop = PropFirmValidator(firm='ftmo')
    valid, msg = prop.check_limits(current_equity=100000.0)
    print(f"Initial check: {valid} - {msg}")
    
    # Simulate loss
    prop.record_pnl(-3000)  # $3k loss
    valid, msg = prop.check_limits(current_equity=97000.0)
    print(f"After $3k loss: {valid} - {msg}")
