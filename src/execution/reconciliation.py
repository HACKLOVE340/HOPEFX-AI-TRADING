"""Position reconciliation engine."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any

import structlog

from src.core.types import Position
from src.execution.brokers.base import Broker
from src.risk.kill_switch import kill_switch

logger = structlog.get_logger()


@dataclass
class ReconciliationDiff:
    symbol: str
    field: str
    local_value: Any
    broker_value: Any
    severity: str  # WARNING, CRITICAL


class PositionReconciler:
    """1-second heartbeat reconciliation."""
    
    def __init__(self, broker: Broker, tolerance: Decimal = Decimal("0.0001")):
        self.broker = broker
        self.tolerance = tolerance
        self._local_positions: dict[str, Position] = {}
        self._last_reconcile: datetime | None = None
        self._running = False
        self._failures = 0
        self._max_failures = 3
    
    async def start(self) -> None:
        """Start reconciliation loop."""
        self._running = True
        asyncio.create_task(self._reconcile_loop())
        logger.info("Reconciliation started")
    
    async def stop(self) -> None:
        self._running = False
    
    def update_local(self, position: Position) -> None:
        """Update local position state."""
        self._local_positions[position.id] = position
    
    async def _reconcile_loop(self) -> None:
        """1-second reconciliation."""
        while self._running:
            try:
                diffs = await self._reconcile()
                
                if diffs:
                    critical = [d for d in diffs if d.severity == "CRITICAL"]
                    if critical:
                        self._failures += 1
                        logger.error(f"Critical reconciliation diffs: {critical}")
                        
                        if self._failures >= self._max_failures:
                            await kill_switch.kill(
                                reason=f"Reconciliation failed {self._failures} times",
                                source="reconciler"
                            )
                    else:
                        logger.warning(f"Reconciliation warnings: {diffs}")
                else:
                    self._failures = max(0, self._failures - 1)  # Decay
                    
            except Exception as e:
                logger.error(f"Reconciliation error: {e}")
                self._failures += 1
            
            await asyncio.sleep(1.0)
    
    async def _reconcile(self) -> list[ReconciliationDiff]:
        """Compare local vs broker positions."""
        broker_positions = await self.broker.get_positions()
        broker_map = {p.id: p for p in broker_positions}
        
        diffs = []
        
        # Check local positions exist at broker
        for local_id, local_pos in self._local_positions.items():
            if local_id not in broker_map:
                diffs.append(ReconciliationDiff(
                    symbol=local_pos.symbol,
                    field="existence",
                    local_value="PRESENT",
                    broker_value="MISSING",
                    severity="CRITICAL"
                ))
                continue
            
            broker_pos = broker_map[local_id]
            
            # Quantity check
            qty_diff = abs(local_pos.quantity - broker_pos.quantity)
            if qty_diff > self.tolerance:
                diffs.append(ReconciliationDiff(
                    symbol=local_pos.symbol,
                    field="quantity",
                    local_value=float(local_pos.quantity),
                    broker_value=float(broker_pos.quantity),
                    severity="CRITICAL"
                ))
            
            # Price check (slippage tolerance)
            price_diff_pct = abs(local_pos.entry_price - broker_pos.entry_price) / local_pos.entry_price
            if price_diff_pct > Decimal("0.001"):  # 10 bps
                diffs.append(ReconciliationDiff(
                    symbol=local_pos.symbol,
                    field="entry_price",
                    local_value=float(local_pos.entry_price),
                    broker_value=float(broker_pos.entry_price),
                    severity="WARNING"
                ))
        
        # Check for broker positions we don't know about
        for broker_id, broker_pos in broker_map.items():
            if broker_id not in self._local_positions:
                diffs.append(ReconciliationDiff(
                    symbol=broker_pos.symbol,
                    field="existence",
                    local_value="MISSING",
                    broker_value="PRESENT",
                    severity="CRITICAL"
                ))
        
        self._last_reconcile = datetime.utcnow()
        return diffs
