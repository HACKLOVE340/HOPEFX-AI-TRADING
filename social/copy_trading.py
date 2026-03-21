"""
CopyTradingEngine — canonical entry point for social/copy_trading.

Re-exports from the full implementation in advanced_copy_trading.py so that
social/__init__.py can import from a stable name regardless of which file
holds the implementation.
"""

from .advanced_copy_trading import CopyTradingEngine, FollowerConfig, TraderProfile as CopyTraderProfile
from dataclasses import dataclass as _dc, field as _field
from typing import Optional as _Opt
from datetime import datetime as _dt


@_dc
class CopyRelationship:
    """Represents a follower→leader copy relationship."""
    follower_id: str
    leader_id: str
    copy_ratio: float = 1.0
    active: bool = True
    created_at: _dt = _field(default_factory=_dt.utcnow)
    max_drawdown_pct: float = 0.10
    max_position_size: _Opt[float] = None


__all__ = ["CopyTradingEngine", "FollowerConfig", "CopyTraderProfile", "CopyRelationship"]
