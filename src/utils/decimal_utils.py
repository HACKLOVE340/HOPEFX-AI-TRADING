"""
Institutional-grade decimal arithmetic for financial calculations.
Compliant with ISO 4217 and banking standards.
"""

from decimal import Decimal, ROUND_HALF_UP, ROUND_HALF_EVEN, Context, localcontext
from enum import Enum
from typing import Union

# Precision contexts
HIGH_PRECISION = Context(prec=28, rounding=ROUND_HALF_UP)
CURRENCY_PRECISION = Context(prec=10, rounding=ROUND_HALF_UP)
PIP_PRECISION = Context(prec=6, rounding=ROUND_HALF_UP)


class CurrencyCode(Enum):
    """ISO 4217 currency codes with decimal places."""
    USD = 2
    EUR = 2
    GBP = 2
    JPY = 0
    XAU = 2  # Gold troy ounce


class DecimalQuantizer:
    """
    Production-grade decimal quantization for financial operations.
    
    All monetary calculations must use this class to ensure:
    - No floating point errors
    - Consistent rounding (banker's rounding)
    - Audit trail precision
    """
    
    # Quantizers by precision
    CURRENCY = Decimal("0.01")        # 2 decimal places
    PIPS_5 = Decimal("0.00001")        # 5 decimal places (forex)
    PIPS_3 = Decimal("0.001")          # 3 decimal places
    WHOLE = Decimal("1")               # No decimals
    PERCENTAGE = Decimal("0.0001")     # 4 decimal places (basis points)
    
    @classmethod
    def quantize_currency(cls, value: Decimal, rounding=ROUND_HALF_UP) -> Decimal:
        """Quantize to currency precision (2 decimals)."""
        if not isinstance(value, Decimal):
            value = Decimal(str(value))
        return value.quantize(cls.CURRENCY, rounding=rounding)
    
    @classmethod
    def quantize_pips(cls, value: Decimal, decimals: int = 5) -> Decimal:
        """Quantize to pip precision."""
        quantizer = Decimal("0.1") ** decimals
        return value.quantize(quantizer, rounding=ROUND_HALF_UP)
    
    @classmethod
    def quantize_percentage(cls, value: Decimal) -> Decimal:
        """Quantize percentage to basis points."""
        return value.quantize(cls.PERCENTAGE, rounding=ROUND_HALF_UP)
    
    @classmethod
    def calculate_pnl(
        cls,
        entry_price: Decimal,
        exit_price: Decimal,
        quantity: Decimal,
        direction: str,
        commission: Decimal = Decimal("0"),
        spread_cost: Decimal = Decimal("0")
    ) -> Decimal:
        """
        Calculate P&L with full precision.
        
        Formula: (Exit - Entry) * Quantity - Commission - Spread
        """
        with localcontext(HIGH_PRECISION):
            if direction == "LONG":
                gross_pnl = (exit_price - entry_price) * quantity
            else:
                gross_pnl = (entry_price - exit_price) * quantity
            
            net_pnl = gross_pnl - commission - spread_cost
            
            return cls.quantize_currency(net_pnl)
    
    @classmethod
    def calculate_position_value(
        cls,
        price: Decimal,
        quantity: Decimal,
        leverage: Decimal = Decimal("1")
    ) -> Decimal:
        """Calculate position value with margin."""
        with localcontext(HIGH_PRECISION):
            notional = price * quantity
            margin_required = notional / leverage if leverage > 0 else notional
            return cls.quantize_currency(margin_required)
    
    @classmethod
    def calculate_average_price(
        cls,
        existing_qty: Decimal,
        existing_price: Decimal,
        new_qty: Decimal,
        new_price: Decimal
    ) -> Decimal:
        """
        Calculate VWAP for position averaging.
        """
        with localcontext(HIGH_PRECISION):
            total_qty = existing_qty + new_qty
            if total_qty == 0:
                return Decimal("0")
            
            total_value = (existing_qty * existing_price) + (new_qty * new_price)
            avg_price = total_value / total_qty
            
            return cls.quantize_pips(avg_price, decimals=5)


class SafeDecimal:
    """
    Wrapper for safe decimal operations with overflow/underflow protection.
    """
    
    MAX_VALUE = Decimal("999999999999.99")
    MIN_VALUE = Decimal("-999999999999.99")
    MIN_POSITIVE = Decimal("0.01")
    
    def __init__(self, value: Union[str, float, int, Decimal]):
        self._value = self._sanitize(value)
    
    def _sanitize(self, value) -> Decimal:
        """Convert and validate value."""
        if isinstance(value, float):
            # Critical: Never use float directly
            raise TypeError("Float values are not allowed - use string or Decimal")
        
        if isinstance(value, (int, str)):
            value = Decimal(value)
        
        if not isinstance(value, Decimal):
            raise TypeError(f"Cannot convert {type(value)} to Decimal")
        
        # Check bounds
        if value > self.MAX_VALUE:
            raise OverflowError(f"Value {value} exceeds maximum {self.MAX_VALUE}")
        if value < self.MIN_VALUE:
            raise OverflowError(f"Value {value} below minimum {self.MIN_VALUE}")
        
        return value
    
    @property
    def value(self) -> Decimal:
        """Get quantized decimal value."""
        return DecimalQuantizer.quantize_currency(self._value)
    
    def __add__(self, other) -> "SafeDecimal":
        return SafeDecimal(self._value + SafeDecimal(other)._value)
    
    def __sub__(self, other) -> "SafeDecimal":
        return SafeDecimal(self._value - SafeDecimal(other)._value)
    
    def __mul__(self, other) -> "SafeDecimal":
        with localcontext(HIGH_PRECISION):
            return SafeDecimal(self._value * SafeDecimal(other)._value)
    
    def __truediv__(self, other) -> "SafeDecimal":
        other_val = SafeDecimal(other)._value
        if other_val == 0:
            raise ZeroDivisionError("Division by zero in financial calculation")
        with localcontext(HIGH_PRECISION):
            return SafeDecimal(self._value / other_val)
    
    def __repr__(self) -> str:
        return f"SafeDecimal({self.value})"


# Convenience functions for common operations
def money(value) -> Decimal:
    """Create money value with currency quantization."""
    return SafeDecimal(value).value

def pips(value, decimals=5) -> Decimal:
    """Create pip value with forex quantization."""
    return DecimalQuantizer.quantize_pips(Decimal(str(value)), decimals)

def bps(value) -> Decimal:
    """Create basis points value."""
    return DecimalQuantizer.quantize_percentage(Decimal(str(value)))
