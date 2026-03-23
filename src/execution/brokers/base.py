"""Abstract broker interface."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Optional

from src.core.types import Order, OrderStatus, OrderType, Position, Symbol


@dataclass
class OrderResult:
    """Result of a placed order."""
    order_id: str
    status: OrderStatus
    filled_qty: Decimal
    filled_price: Decimal
    remaining_qty: Decimal
    commission: Decimal
    slippage: Decimal
    timestamp: str
    raw_response: Optional[Any] = None


class Broker(ABC):
    """Abstract broker interface."""

    @abstractmethod
    async def connect(self) -> bool:
        """Connect to broker."""
        pass

    @abstractmethod
    async def disconnect(self) -> None:
        """Disconnect from broker."""
        pass

    @abstractmethod
    async def place_order(self, order: Order) -> Order:
        """Place order."""
        pass

    @abstractmethod
    async def cancel_order(self, order_id: str) -> bool:
        """Cancel order."""
        pass

    @abstractmethod
    async def get_positions(self) -> list[Position]:
        """Get open positions."""
        pass

    @abstractmethod
    async def get_account(self) -> dict[str, Any]:
        """Get account info."""
        pass

    @abstractmethod
    async def stream_quotes(self, symbols: list[Symbol], callback: callable) -> None:
        """Stream quotes."""
        pass


# Alias used by hopefx.execution.brokers.base imports
BaseBroker = Broker
