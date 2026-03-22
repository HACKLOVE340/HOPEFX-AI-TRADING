"""hopefx.social.copy_trading — shim for tests"""
from social.copy_trading import CopyTradingEngine, CopyRelationship
from social.advanced_copy_trading import TraderProfile as CopyTrader, FollowerConfig

__all__ = ["CopyTradingEngine", "CopyRelationship", "CopyTrader", "FollowerConfig"]
