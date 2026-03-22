from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from decimal import Decimal
from enum import Enum, auto
from typing import Any

import structlog

logger = structlog.get_logger()


class OrderStatus(Enum):
    PENDING = auto()
    FILLED = auto()
    PARTIAL = auto()
    REJECTED = auto()
    CANCELLED = auto()


class OrderType(Enum):
    MARKET = auto()
    LIMIT = auto()
    STOP = auto()
    STOP_LIMIT = auto()


@dataclass
class Order:
    symbol: str
    side: str  # buy/sell
    quantity: Decimal
    order_type: OrderType
    price: Decimal | None = None
    stop_price: Decimal | None = None
    time_in_force: str = "GTC"
    client_order_id: str | None = None


@dataclass
class OrderResult:
    order_id: str
    status: OrderStatus
    filled_qty: Decimal
    filled_price: Decimal
    remaining_qty: Decimal
    commission: Decimal
    slippage: Decimal
    timestamp: str
    raw_response: Any = None


class BaseBroker(ABC):
    """Abstract base for all broker integrations."""

    def __init__(self, name: str, paper: bool = True) -> None:
        self.name = name
        self.paper = paper
        self._connected = False
        self._latency_ms: float = 0.0

    @abstractmethod
    async def connect(self) -> None:
        """Establish connection."""
        pass

    @abstractmethod
    async def disconnect(self) -> None:
        """Disconnect."""
        pass

    @abstractmethod
    async def place_order(self, order: Order) -> OrderResult:
        """Place order."""
        pass

    @abstractmethod
    async def cancel_order(self, order_id: str) -> bool:
        """Cancel order."""
        pass

    @abstractmethod
    async def get_position(self, symbol: str) -> dict[str, Any]:
        """Get current position."""
        pass

    @abstractmethod
    async def get_account(self) -> dict[str, Any]:
        """Get account info."""
        pass

    @property
    def connected(self) -> bool:
        """Connection status."""
        return self._connected

    @property
    def latency_ms(self) -> float:
        """Last measured latency."""
        return self._latency_ms
