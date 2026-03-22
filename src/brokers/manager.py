"""
Broker manager with circuit breaker and failover.
"""
import asyncio
from typing import Dict, Optional, Type, List
from decimal import Decimal
from datetime import datetime
import structlog

from src.brokers.base import BaseBroker, TickData, Order, OrderSide, Position
from src.core.circuit_breaker import CircuitBreaker
from src.config.settings import get_settings

logger = structlog.get_logger()


class BrokerManager:
    """
    Manages multiple broker connections with failover and circuit breaking.
    Production-grade implementation with health monitoring.
    """
    
    def __init__(self):
        self._brokers: Dict[str, BaseBroker] = {}
        self._circuit_breakers: Dict[str, CircuitBreaker] = {}
        self._default_broker: Optional[str] = None
        self._health_check_task: Optional[asyncio.Task] = None
        self._settings = get_settings()
        
    def register_broker(self, name: str, broker: BaseBroker, 
                       is_default: bool = False,
                       failure_threshold: int = 5,
                       recovery_timeout: int = 60) -> None:
        """Register a broker with circuit breaker protection."""
        self._brokers[name] = broker
        self._circuit_breakers[name] = CircuitBreaker(
            failure_threshold=failure_threshold,
            recovery_timeout=recovery_timeout,
            name=f"broker_{name}"
        )
        
        if is_default or self._default_broker is None:
            self._default_broker = name
            
        logger.info("broker_registered", name=name, default=is_default)
    
    async def connect_all(self) -> Dict[str, bool]:
        """Connect to all registered brokers."""
        results = {}
        for name, broker in self._brokers.items():
            try:
                cb = self._circuit_breakers[name]
                if cb.can_execute():
                    success = await broker.connect()
                    results[name] = success
                    if success:
                        cb.record_success()
                    else:
                        cb.record_failure()
                else:
                    results[name] = False
                    logger.warning("broker_circuit_open", broker=name)
            except Exception as e:
                results[name] = False
                self._circuit_breakers[name].record_failure()
                logger.error("broker_connect_failed", broker=name, error=str(e))
        
        # Start health monitoring
        self._health_check_task = asyncio.create_task(self._health_monitor())
        return results
    
    async def disconnect_all(self) -> None:
        """Disconnect from all brokers."""
        if self._health_check_task:
            self._health_check_task.cancel()
            try:
                await self._health_check_task
            except asyncio.CancelledError:
                pass
        
        for name, broker in self._brokers.items():
            try:
                await broker.disconnect()
                logger.info("broker_disconnected", name=name)
            except Exception as e:
                logger.error("broker_disconnect_error", name=name, error=str(e))
    
    async def get_best_broker(self) -> Optional[BaseBroker]:
        """Get best available broker based on health and latency."""
        healthy_brokers = []
        
        for name, broker in self._brokers.items():
            cb = self._circuit_breakers[name]
            if cb.can_execute() and broker.is_connected:
                healthy_brokers.append((name, broker))
        
        if not healthy_brokers:
            logger.error("no_healthy_brokers_available")
            return None
            
        # For now, return first healthy; could add latency-based selection
        return healthy_brokers[0][1]
    
    async def place_order(self, order: Order, 
                         broker_name: Optional[str] = None) -> Dict:
        """Place order with failover."""
        brokers_to_try = []
        
        if broker_name and broker_name in self._brokers:
            brokers_to_try.append(broker_name)
        else:
            # Try default first, then others
            if self._default_broker:
                brokers_to_try.append(self._default_broker)
            brokers_to_try.extend([n for n in self._brokers.keys() 
                                  if n not in brokers_to_try])
        
        last_error = None
        for name in brokers_to_try:
            cb = self._circuit_breakers[name]
            if not cb.can_execute():
                continue
                
            broker = self._brokers[name]
            try:
                result = await broker.place_order(order)
                cb.record_success()
                logger.info("order_placed", broker=name, 
                           symbol=order.symbol, side=order.side)
                return {"broker": name, "result": result}
            except Exception as e:
                cb.record_failure()
                last_error = e
                logger.error("order_failed", broker=name, error=str(e))
        
        raise last_error or Exception("No available brokers to place order")
    
    async def get_positions(self, broker_name: Optional[str] = None) -> List[Position]:
        """Get positions from specific or best broker."""
        broker = await self._get_broker_or_best(broker_name)
        return await broker.get_positions()
    
    async def get_quote(self, symbol: str, 
                        broker_name: Optional[str] = None) -> TickData:
        """Get quote with automatic failover."""
        brokers_to_try = self._get_priority_list(broker_name)
        
        for name in brokers_to_try:
            cb = self._circuit_breakers[name]
            if not cb.can_execute():
                continue
                
            broker = self._brokers[name]
            try:
                quote = await broker.get_quote(symbol)
                cb.record_success()
                return quote
            except Exception as e:
                cb.record_failure()
                logger.warning("quote_fetch_failed", broker=name, 
                              symbol=symbol, error=str(e))
        
        raise Exception(f"Could not get quote for {symbol} from any broker")
    
    def _get_priority_list(self, preferred: Optional[str] = None) -> List[str]:
        """Get broker priority list."""
        names = list(self._brokers.keys())
        if preferred and preferred in names:
            names.remove(preferred)
            names.insert(0, preferred)
        return names
    
    async def _get_broker_or_best(self, name: Optional[str]) -> BaseBroker:
        """Get specific broker or best available."""
        if name:
            if name not in self._brokers:
                raise ValueError(f"Unknown broker: {name}")
            return self._brokers[name]
        
        broker = await self.get_best_broker()
        if not broker:
            raise Exception("No healthy brokers available")
        return broker
    
    async def _health_monitor(self) -> None:
        """Background health monitoring."""
        while True:
            try:
                await asyncio.sleep(30)  # Check every 30 seconds
                for name, broker in self._brokers.items():
                    healthy = await broker.health_check()
                    cb = self._circuit_breakers[name]
                    if healthy:
                        cb.record_success()
                    else:
                        cb.record_failure()
                    logger.debug("health_check", broker=name, healthy=healthy)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("health_monitor_error", error=str(e))
