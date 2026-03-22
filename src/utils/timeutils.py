"""
Time and date utility functions.
"""

from datetime import datetime, time, timezone
from typing import Generator

import pandas as pd
import pytz


def now_utc() -> datetime:
    """Get current UTC time."""
    return datetime.now(timezone.utc)


def is_market_open(
    dt: datetime | None = None,
    market: str = "forex"
) -> bool:
    """
    Check if market is open.
    
    Forex: Sunday 5pm ET - Friday 5pm ET
    """
    if dt is None:
        dt = now_utc()
    
    # Convert to ET
    et = pytz.timezone("America/New_York")
    local_dt = dt.astimezone(et)
    
    weekday = local_dt.weekday()
    current_time = local_dt.time()
    
    if market == "forex":
        # Closed weekends
        if weekday == 5:  # Saturday
            return False
        if weekday == 6 and current_time < time(17, 0):  # Sunday before 5pm
            return False
        if weekday == 4 and current_time >= time(17, 0):  # Friday after 5pm
            return False
        
        return True
    
    return False


def get_next_market_open(dt: datetime | None = None) -> datetime:
    """Get next market open time."""
    if dt is None:
        dt = now_utc()
    
    et = pytz.timezone("America/New_York")
    local_dt = dt.astimezone(et)
    
    # If weekend, move to Sunday 5pm
    if local_dt.weekday() == 5:  # Saturday
        next_open = local_dt.replace(hour=17, minute=0) + pd.Timedelta(days=1)
    elif local_dt.weekday() == 6 and local_dt.time() < time(17, 0):  # Sunday before open
        next_open = local_dt.replace(hour=17, minute=0)
    else:
        next_open = local_dt
    
    return next_open.astimezone(timezone.utc)


def trading_days(
    start: datetime,
    end: datetime,
    frequency: str = "D"
) -> Generator[datetime, None, None]:
    """Generate trading days between dates."""
    current = start
    while current <= end:
        if current.weekday() < 5:  # Monday-Friday
            yield current
        current += pd.Timedelta(days=1)


def align_to_bar(
    dt: datetime,
    frequency: str = "1min"
) -> datetime:
    """Align timestamp to bar boundary."""
    if frequency == "1min":
        return dt.replace(second=0, microsecond=0)
    elif frequency == "5min":
        minute = (dt.minute // 5) * 5
        return dt.replace(minute=minute, second=0, microsecond=0)
    elif frequency == "1h":
        return dt.replace(minute=0, second=0, microsecond=0)
    else:
        return dt


def parse_duration(duration_str: str) -> int:
    """
    Parse duration string to seconds.
    
    Examples: "1h", "30m", "1d"
    """
    unit = duration_str[-1]
    value = int(duration_str[:-1])
    
    multipliers = {
        's': 1,
        'm': 60,
        'h': 3600,
        'd': 86400,
    }
    
    return value * multipliers.get(unit, 1)
