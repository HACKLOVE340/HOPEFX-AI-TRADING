"""
Trading domain enumerations.
Institutional-grade type safety.
"""

from enum import Enum, IntEnum


class TradeDirection(str, Enum):
    LONG = "LONG"
    SHORT = "SHORT"
    FLAT = "FLAT"


class OrderType(str, Enum):
    MARKET = "MARKET"
    LIMIT = "LIMIT"
    STOP = "STOP"
    STOP_LIMIT = "STOP_LIMIT"
    TRAILING_STOP = "TRAILING_STOP"
    OCO = "OCO"  # One-Cancels-Other


class OrderStatus(str, Enum):
    PENDING = "PENDING"
    SUBMITTED = "SUBMITTED"
    PARTIAL_FILL = "PARTIAL_FILL"
    FILLED = "FILLED"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"


class TimeInForce(str, Enum):
    GTC = "GTC"  # Good Till Cancelled
    IOC = "IOC"  # Immediate Or Cancel
    FOK = "FOK"  # Fill Or Kill
    GTD = "GTD"  # Good Till Date
    DAY = "DAY"


class PositionStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"
    HEDGED = "HEDGED"


class SignalStrength(IntEnum):
    WEAK = 1
    MODERATE = 2
    STRONG = 3
    VERY_STRONG = 4


class PropFirm(str, Enum):
    FTMO = "FTMO"
    MY_FOREX_FUNDS = "MFF"
    THE5ERS = "THE5ERS"
    TOPSTEP = "TOPSTEP"
    NONE = "NONE"


class DataFrequency(str, Enum):
    TICK = "TICK"
    SECOND_1 = "1S"
    MINUTE_1 = "1M"
    MINUTE_5 = "5M"
    MINUTE_15 = "15M"
    MINUTE_30 = "30M"
    HOUR_1 = "1H"
    HOUR_4 = "4H"
    DAILY = "1D"


class BrokerType(str, Enum):
    OANDA = "OANDA"
    INTERACTIVE_BROKERS = "IBKR"
    META_TRADER_5 = "MT5"
    BINANCE = "BINANCE"
    ALPACA = "ALPACA"
    PAPER = "PAPER"


class StrategyState(str, Enum):
    INITIALIZING = "INITIALIZING"
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"
    STOPPED = "STOPPED"
    ERROR = "ERROR"


class RiskLevel(IntEnum):
    LOW = 1
    MEDIUM = 2
    HIGH = 3
    CRITICAL = 4
    EMERGENCY = 5
