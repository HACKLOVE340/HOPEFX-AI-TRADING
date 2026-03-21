"""
CopyTradingEngine — canonical entry point for social/copy_trading.

Re-exports from the full implementation in advanced_copy_trading.py so that
social/__init__.py can import from a stable name regardless of which file
holds the implementation.
"""

from .advanced_copy_trading import CopyTradingEngine, FollowerConfig, TraderProfile as CopyTraderProfile

__all__ = ["CopyTradingEngine", "FollowerConfig", "CopyTraderProfile"]
