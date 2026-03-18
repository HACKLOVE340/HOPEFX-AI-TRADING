"""TWAP (Time Weighted Average Price) execution algorithm."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from decimal import Decimal
from typing import List

from hopefx.execution.brokers.base import Order, OrderResult


class TWAPExecutor:
    """Execute large orders over time to minimize market impact."""

    def __init__(
        self,
        total_quantity: Decimal,
        num_slices: int = 10,
        duration_minutes: int = 60,
        price_tolerance: Decimal = Decimal("0.001")
    ) -> None:
        self.total_qty = total_quantity
        self.num_slices = num_slices
        self.slice_qty = total_quantity / num_slices
        self.interval = (duration_minutes * 60) / num_slices
        self.tolerance = price_tolerance
        
        self._slices: List[OrderResult] = []
        self._target_vwap: Decimal = Decimal("0")
        self._actual_vwap: Decimal = Decimal("0")

    async def execute(
        self,
        base_order: Order,
        router: any
    ) -> List[OrderResult]:
        """Execute TWAP slices."""
        start_time = datetime.utcnow()
        end_time = start_time + timedelta(minutes=self.duration_minutes)

        for i in range(self.num_slices):
            slice_start = datetime.utcnow()
            
            # Check if we're within time window
            if datetime.utcnow() > end_time:
                break

            # Check price tolerance
            current_price = await self._get_market_price(base_order.symbol)
            if self._target_vwap > 0:
                deviation = abs(current_price - self._target_vwap) / self._target_vwap
                if deviation > self.tolerance:
                    # Pause execution, price moved too much
                    await asyncio.sleep(self.interval / 2)
                    continue

            # Execute slice
            slice_order = Order(
                symbol=base_order.symbol,
                side=base_order.side,
                quantity=self.slice_qty,
                order_type="market"
            )

            result = await router.route_order(slice_order)
            self._slices.append(result)

            # Update VWAP
            self._actual_vwap = self._calculate_vwap()

            # Wait for next slice
            elapsed = (datetime.utcnow() - slice_start).total_seconds()
            remaining = self.interval - elapsed
            if remaining > 0:
                await asyncio.sleep(remaining)

        return self._slices

    def _calculate_vwap(self) -> Decimal:
        """Calculate volume-weighted average price."""
        if not self._slices:
            return Decimal("0")
        
        total_value = sum(
            s.filled_qty * s.filled_price for s in self._slices
        )
        total_volume = sum(s.filled_qty for s in self._slices)
        
        return total_value / total_volume if total_volume > 0 else Decimal("0")

    async def _get_market_price(self, symbol: str) -> Decimal:
        """Get current market price."""
        from hopefx.data.feed import feed_manager
        tick = feed_manager.get_best_price(symbol)
        return tick.mid if tick else Decimal("0")
