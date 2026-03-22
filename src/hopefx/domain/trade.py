from dataclasses import dataclass
from datetime import datetime

dataclass
class Trade:
    id: int
    symbol: str
    side: str
    size: float
    entry_price: float
    timestamp: datetime