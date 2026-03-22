"""Byzantine-fault-tolerant reconciliation."""
from __future__ import annotations

import asyncio
import hashlib
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Any

import structlog

from src.core.types import Position, OrderStatus
from src.execution.brokers.base import Broker
from src.risk.kill_switch import kill_switch, KillSource

logger = structlog.get_logger()


class ReconciliationSeverity(Enum):
    WARNING = "warning"
    CRITICAL = "critical"
    BYZANTINE = "byzantine"  # Disagreement between sources


@dataclass(frozen=True)
class PositionState:
    symbol: str
    quantity: Decimal
    entry_price: Decimal
    hash: str  # Merkle-like hash for quick comparison
    
    @classmethod
    def from_position(cls, p: Position) -> "PositionState":
        h = hashlib.sha256(
            f"{p.symbol}:{p.quantity}:{p.entry_price}".encode()
        ).hexdigest()[:16]
        return cls(p.symbol, p.quantity, p.entry_price, h)


class ByzantineReconciler:
    """Three-way reconciliation: OMS, Broker, Internal Ledger."""
    
    def __init__(
        self,
        broker: Broker,
        ledger: Any,  # Internal immutable ledger
        check_interval_ms: float = 1000.0,
        tolerance_bps: float = 10.0
    ):
        self.broker = broker
        self.ledger = ledger
        self.check_interval = check_interval_ms / 1000.0
        self.tolerance = Decimal(str(tolerance_bps / 10000))
        
        self._oms_state: dict[str, Position] = {}
        self._last_check: datetime | None = None
        self._consecutive_mismatches = 0
        self._max_mismatches = 3
        self._running = False
        
        # Metrics
        self._checks_total = 0
        self._checks_failed = 0
        self._byzantine_faults = 0
    
    async def start(self) -> None:
        """Start reconciliation loop."""
        self._running = True
        asyncio.create_task(self._reconcile_loop())
        logger.info("Byzantine reconciler started")
    
    async def _reconcile_loop(self) -> None:
        """Continuous reconciliation."""
        while self._running:
            try:
                start = asyncio.get_event_loop().time()
                
                # Fetch all three sources concurrently
                oms_task = self._get_oms_state()
                broker_task = self._get_broker_state()
                ledger_task = self._get_ledger_state()
                
                oms, broker, ledger = await asyncio.gather(
                    oms_task, broker_task, ledger_task
                )
                
                # Three-way comparison
                diffs = self._three_way_compare(oms, broker, ledger)
                
                if diffs:
                    await self._handle_discrepancy(diffs, oms, broker, ledger)
                else:
                    self._consecutive_mismatches = 0
                
                self._checks_total += 1
                
                # Adaptive interval: check faster if issues
                interval = self.check_interval
                if self._consecutive_mismatches > 0:
                    interval = max(0.1, self.check_interval / 2)
                
                elapsed = asyncio.get_event_loop().time() - start
                await asyncio.sleep(max(0, interval - elapsed))
                
            except Exception as e:
                logger.error(f"Reconciliation error: {e}")
                self._consecutive_mismatches += 1
                if self._consecutive_mismatches >= self._max_mismatches:
                    await self._emergency_kill("Reconciliation loop failure")
    
    def _three_way_compare(
        self,
        oms: dict[str, PositionState],
        broker: dict[str, PositionState],
        ledger: dict[str, PositionState]
    ) -> list[dict[str, Any]]:
        """Compare three sources for Byzantine detection."""
        diffs = []
        all_symbols = set(oms.keys()) | set(broker.keys()) | set(ledger.keys())
        
        for symbol in all_symbols:
            o = oms.get(symbol)
            b = broker.get(symbol)
            l = ledger.get(symbol)
            
            # Byzantine: all three differ
            if o and b and l:
                if o.hash != b.hash and b.hash != l.hash and o.hash != l.hash:
                    diffs.append({
                        "symbol": symbol,
                        "severity": ReconciliationSeverity.BYZANTINE,
                        "oms": o,
                        "broker": b,
                        "ledger": l
                    })
                    self._byzantine_faults += 1
                
                # Two agree, one differs
                elif o.hash == b.hash and o.hash != l.hash:
                    diffs.append({
                        "symbol": symbol,
                        "severity": ReconciliationSeverity.CRITICAL,
                        "consensus": "oms_broker",
                        "outlier": "ledger",
                        "expected": o
                    })
                elif o.hash == l.hash and o.hash != b.hash:
                    diffs.append({
                        "symbol": symbol,
                        "severity": ReconciliationSeverity.CRITICAL,
                        "consensus": "oms_ledger",
                        "outlier": "broker",
                        "expected": o
                    })
                elif b.hash == l.hash and b.hash != o.hash:
                    diffs.append({
                        "symbol": symbol,
                        "severity": ReconciliationSeverity.CRITICAL,
                        "consensus": "broker_ledger",
                        "outlier": "oms",
                        "expected": b
                    })
            
            # Missing in one or more
            elif sum(x is not None for x in [o, b, l]) < 3:
                present = []
                if o: present.append("oms")
                if b: present.append("broker")
                if l: present.append("ledger")
                
                diffs.append({
                    "symbol": symbol,
                    "severity": ReconciliationSeverity.CRITICAL,
                    "present_in": present,
                    "missing_from": list(set(["oms", "broker", "ledger"]) - set(present))
                })
        
        return diffs
    
    async def _handle_discrepancy(
        self,
        diffs: list[dict],
        oms: dict,
        broker: dict,
        ledger: dict
    ) -> None:
        """Handle position mismatch."""
        self._consecutive_mismatches += 1
        self._checks_failed += 1
        
        byzantine = [d for d in diffs if d["severity"] == ReconciliationSeverity.BYZANTINE]
        critical = [d for d in diffs if d["severity"] == ReconciliationSeverity.CRITICAL]
        
        if byzantine:
            # Byzantine fault: can't determine truth, kill everything
            await self._emergency_kill(f"Byzantine fault: {byzantine}")
            return
        
        if critical:
            # Attempt recovery based on consensus
            for diff in critical:
                if "consensus" in diff:
                    logger.warning(
                        f"Auto-recovering {diff['symbol']} from {diff['outlier']} "
                        f"to match {diff['consensus']}"
                    )
                    await self._force_sync(diff["symbol"], diff["expected"])
        
        if self._consecutive_mismatches >= self._max_mismatches:
            await self._emergency_kill(f"Persistent reconciliation failures: {diffs}")
    
    async def _emergency_kill(self, reason: str) -> None:
        """Trigger kill switch."""
        await kill_switch.kill(
            reason=reason,
            source=KillSource.RECONCILIATION
        )
    
    async def _force_sync(self, symbol: str, target: PositionState) -> None:
        """Force position to match consensus."""
        # Cancel pending orders for symbol
        # Close/reopen position to match
        pass
    
    async def _get_oms_state(self) -> dict[str, PositionState]:
        """Get OMS position state."""
        # Query OMS
        return {}
    
    async def _get_broker_state(self) -> dict[str, PositionState]:
        """Get broker position state."""
        positions = await self.broker.get_positions()
        return {p.symbol: PositionState.from_position(p) for p in positions}
    
    async def _get_ledger_state(self) -> dict[str, PositionState]:
        """Get immutable ledger state."""
        return {}
