# execution/throttler.py
"""
Message Throttling - FIA 3.4 Compliant Rate Limiting
"""

import time
from collections import deque
from threading import Lock
from typing import Dict, Optional
from dataclasses import dataclass
from enum import Enum
import logging

logger = logging.getLogger(__name__)

class ThrottleLevel(Enum):
    NORMAL = "normal"
    WARNING = "warning"
    THROTTLED = "throttled"
    BLOCKED = "blocked"

@dataclass
class ThrottleState:
    messages_in_window: int
    window_start: float
    level: ThrottleLevel
    cooldown_until: Optional[float]

class MessageThrottler:
    """
    FIA 3.4: Message Throttle Implementation
    Prevents excessive messaging that could disrupt market activity
    """
    
    def __init__(
        self,
        max_messages_per_second: int = 50,
        max_messages_per_minute: int = 1000,
        burst_allowance: int = 10,
        cooldown_seconds: float = 1.0
    ):
        self.max_per_second = max_messages_per_second
        self.max_per_minute = max_messages_per_minute
        self.burst_allowance = burst_allowance
        self.cooldown = cooldown_seconds
        
        # Sliding windows
        self.second_window: deque = deque()
        self.minute_window: deque = deque()
        self.lock = Lock()
        
        self.state = ThrottleState(0, time.time(), ThrottleLevel.NORMAL, None)
    
    def can_send(self, message_type: str = "order") -> bool:
        """
        Check if message can be sent under current throttle rules
        FIA 3.4: Never reject order cancellations due to rate limits
        """
        # Never throttle cancellations (FIA requirement)
        if message_type in ["cancel", "cancel_all", "modify"]:
            return True
        
        with self.lock:
            now = time.time()
            
            # Clean old entries
            self._clean_windows(now)
            
            # Check cooldown
            if self.state.cooldown_until and now < self.state.cooldown_until:
                return False
            
            # Check limits
            if len(self.second_window) >= self.max_per_second + self.burst_allowance:
                self._enter_throttle_state(now)
                return False
            
            if len(self.minute_window) >= self.max_per_minute:
                self._enter_throttle_state(now, duration=60)
                return False
            
            return True
    
    def record_message(self, message_type: str = "order") -> None:
        """Record that a message was sent"""
        if message_type in ["cancel", "cancel_all"]:
            return  # Don't count cancellations
        
        with self.lock:
            now = time.time()
            self.second_window.append(now)
            self.minute_window.append(now)
            
            # Update state
            self.state = ThrottleState(
                messages_in_window=len(self.minute_window),
                window_start=self.state.window_start,
                level=self._calculate_level(),
                cooldown_until=self.state.cooldown_until
            )
    
    def _clean_windows(self, now: float) -> None:
        """Remove entries outside time windows"""
        # Keep entries from last second
        while self.second_window and now - self.second_window[0] > 1:
            self.second_window.popleft()
        
        # Keep entries from last minute
        while self.minute_window and now - self.minute_window[0] > 60:
            self.minute_window.popleft()
    
    def _enter_throttle_state(self, now: float, duration: Optional[float] = None) -> None:
        """Enter throttled state"""
        cooldown = duration or self.cooldown
        self.state = ThrottleState(
            messages_in_window=len(self.minute_window),
            window_start=now,
            level=ThrottleLevel.THROTTLED,
            cooldown_until=now + cooldown
        )
        logger.warning(f"Throttling activated for {cooldown}s")
    
    def _calculate_level(self) -> ThrottleLevel:
        """Calculate current throttle level"""
        second_usage = len(self.second_window) / self.max_per_second
        minute_usage = len(self.minute_window) / self.max_per_minute
        
        if second_usage > 1.0 or minute_usage > 0.9:
            return ThrottleLevel.BLOCKED
        elif second_usage > 0.8 or minute_usage > 0.7:
            return ThrottleLevel.THROTTLED
        elif second_usage > 0.6 or minute_usage > 0.5:
            return ThrottleLevel.WARNING
        else:
            return ThrottleLevel.NORMAL
    
    def get_status(self) -> Dict:
        """Get current throttle status"""
        return {
            'level': self.state.level.value,
            'messages_per_second': len(self.second_window),
            'messages_per_minute': len(self.minute_window),
            'max_per_second': self.max_per_second,
            'max_per_minute': self.max_per_minute,
            'in_cooldown': self.state.cooldown_until is not None and time.time() < self.state.cooldown_until
        }
