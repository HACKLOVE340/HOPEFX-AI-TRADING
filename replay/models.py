# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""replay/models.py — Data models for chart replay."""

import logging
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)


class ReplaySpeed(Enum):
    """Replay speed options"""

    PAUSED = 0
    SPEED_1X = 1
    SPEED_2X = 2
    SPEED_5X = 5
    SPEED_10X = 10
    SPEED_50X = 50
    SPEED_100X = 100


class ReplayState(Enum):
    """Replay state"""

    IDLE = "idle"
    PLAYING = "playing"
    PAUSED = "paused"
    FINISHED = "finished"


@dataclass
class ReplaySession:
    """Replay session configuration"""

    session_id: str
    symbol: str
    timeframe: str
    start_date: datetime
    end_date: datetime
    current_date: datetime
    speed: ReplaySpeed = ReplaySpeed.SPEED_1X
    state: ReplayState = ReplayState.IDLE
    initial_balance: float = 100000.0
    current_balance: float = 100000.0
    trades: list[dict[str, Any]] = field(default_factory=list)
    positions: list[dict[str, Any]] = field(default_factory=list)
    created_at: datetime = field(default_factory=datetime.now)


@dataclass
class ReplayBar:
    """Single bar of replay data"""

    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float
