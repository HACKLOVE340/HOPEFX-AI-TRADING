"""
Timeframe Management
"""

from typing import List, Dict


class Timeframe:
    TICK = "tick"
    S1 = "1s"
    S5 = "5s"
    S15 = "15s"
    S30 = "30s"
    M1 = "1m"
    M5 = "5m"
    M15 = "15m"
    M30 = "30m"
    H1 = "1h"
    H4 = "4h"
    D1 = "1d"
    W1 = "1w"
    MN1 = "1M"


class TimeframeManager:
    """Manages chart timeframes"""
    
    def __init__(self):
        self.supported_timeframes = [
            Timeframe.M1, Timeframe.M5, Timeframe.M15, Timeframe.M30,
            Timeframe.H1, Timeframe.H4, Timeframe.D1, Timeframe.W1
        ]
    
    def get_timeframe_seconds(self, timeframe: str) -> int:
        """Get seconds in a timeframe"""
        mapping = {
            '1m': 60,
            '5m': 300,
            '15m': 900,
            '30m': 1800,
            '1h': 3600,
            '4h': 14400,
            '1d': 86400,
            '1w': 604800,
        }
        return mapping.get(timeframe, 60)
    
    def list_timeframes(self) -> List[str]:
        """List supported timeframes"""
        return self.supported_timeframes
