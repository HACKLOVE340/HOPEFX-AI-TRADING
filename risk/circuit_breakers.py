# risk/circuit_breakers.py
"""
Market Circuit Breakers
Pause trading during extreme volatility or system stress
"""

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Dict, List, Optional
from enum import Enum
import logging

logger = logging.getLogger(__name__)

class CircuitState(Enum):
    CLOSED = "closed"      # Normal operation
    OPEN = "open"          # Trading halted
    HALF_OPEN = "half_open"  # Limited trading (reduced size)

@dataclass
class CircuitBreaker:
    name: str
    threshold: float
    duration: timedelta
    state: CircuitState = CircuitState.CLOSED
    triggered_at: Optional[datetime] = None
    trigger_count: int = 0

class CircuitBreakerManager:
    """
    Manages multiple circuit breakers for different risk scenarios
    """
    
    def __init__(self):
        self.breakers: Dict[str, CircuitBreaker] = {
            'volatility': CircuitBreaker(
                name='High Volatility',
                threshold=0.05,  # 5% move in 1 minute
                duration=timedelta(minutes=15)
            ),
            'drawdown': CircuitBreaker(
                name='Max Drawdown',
                threshold=0.10,  # 10% portfolio loss
                duration=timedelta(hours=1)
            ),
            'error_rate': CircuitBreaker(
                name='High Error Rate',
                threshold=0.10,  # 10% error rate
                duration=timedelta(minutes=30)
            ),
            'latency': CircuitBreaker(
                name='High Latency',
                threshold=2.0,  # 2 seconds
                duration=timedelta(minutes=10)
            )
        }
        
        self.error_count = 0
        self.total_operations = 0
    
    def check_volatility(self, price_change_pct: float) -> bool:
        """Check if volatility circuit breaker should trip"""
        breaker = self.breakers['volatility']
        
        if abs(price_change_pct) > breaker.threshold:
            self._trip_breaker(breaker, f"Price moved {price_change_pct:.2%}")
            return False  # Block trading
        
        return self._is_trading_allowed(breaker)
    
    def check_drawdown(self, current_drawdown: float) -> bool:
        """Check if drawdown circuit breaker should trip"""
        breaker = self.breakers['drawdown']
        
        if current_drawdown > breaker.threshold:
            self._trip_breaker(breaker, f"Drawdown {current_drawdown:.2%}")
            return False
        
        return self._is_trading_allowed(breaker)
    
    def record_error(self) -> bool:
        """Record operation error and check error rate"""
        self.error_count += 1
        self.total_operations += 1
        
        breaker = self.breakers['error_rate']
        error_rate = self.error_count / max(self.total_operations, 1)
        
        if error_rate > breaker.threshold:
            self._trip_breaker(breaker, f"Error rate {error_rate:.2%}")
            return False
        
        return self._is_trading_allowed(breaker)
    
    def check_latency(self, latency_ms: float) -> bool:
        """Check if latency circuit breaker should trip"""
        breaker = self.breakers['latency']
        
        if latency_ms > breaker.threshold * 1000:  # Convert to ms
            self._trip_breaker(breaker, f"Latency {latency_ms:.0f}ms")
            return False
        
        return self._is_trading_allowed(breaker)
    
    def _trip_breaker(self, breaker: CircuitBreaker, reason: str):
        """Trip a circuit breaker"""
        if breaker.state == CircuitState.CLOSED:
            breaker.state = CircuitState.OPEN
            breaker.triggered_at = datetime.now()
            breaker.trigger_count += 1
            
            logger.critical(
                f"CIRCUIT BREAKER TRIPPED: {breaker.name} - {reason}. "
                f"Trading halted for {breaker.duration}"
            )
    
    def _is_trading_allowed(self, breaker: CircuitBreaker) -> bool:
        """Check if trading is allowed for this breaker"""
        if breaker.state == CircuitState.CLOSED:
            return True
        
        if breaker.state == CircuitState.OPEN:
            # Check if we should transition to half-open
            elapsed = datetime.now() - breaker.triggered_at
            if elapsed > breaker.duration:
                breaker.state = CircuitState.HALF_OPEN
                logger.warning(f"Circuit breaker {breaker.name} entering half-open state")
                return True  # Allow limited trading
        
        if breaker.state == CircuitState.HALF_OPEN:
            # In half-open, allow trading but with reduced size
            return True
        
        return False
    
    def get_status(self) -> Dict:
        """Get status of all circuit breakers"""
        return {
            name: {
                'state': breaker.state.value,
                'triggered_at': breaker.triggered_at.isoformat() if breaker.triggered_at else None,
                'trigger_count': breaker.trigger_count
            }
            for name, breaker in self.breakers.items()
        }
